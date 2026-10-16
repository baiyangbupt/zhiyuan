from __future__ import annotations

import asyncio

import pytest

from app.gateway.ui_events import SessionKey
from app.gateway.user_input import INPUT_KIND_CHOICE, UserInputBroker, UserInputError


KEY = SessionKey("tenant-1", "session-1")
ANSWER = {"answers": {"major": {"answers": ["计算机类"]}}}


class FakeClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value


def broker_for_test(**options):
    options.setdefault("runtime_generation", "generation-1")
    options.setdefault("scope_resolver", lambda thread_id: KEY)
    return UserInputBroker(**options)


async def register(broker, rpc_id=1):
    return await broker._register(
        {"id": rpc_id, "params": {"threadId": "thread-1", "turnId": "native-turn-1"}},
        native_turn_id="native-turn-1",
        input_kind=INPUT_KIND_CHOICE,
        questions=[{"id": "major", "options": [{"label": "计算机类"}]}],
        question_ids=frozenset({"major"}),
        key=KEY,
    )


@pytest.mark.asyncio
async def test_timeout_releases_both_pending_and_reverse_index():
    broker = broker_for_test()
    record = await register(broker)
    record.expires_at = 0.0

    with pytest.raises(UserInputError, match="clarification_expired"):
        await broker._await_answer(record)

    assert broker._pending == {}
    assert broker._by_rpc == {}
    assert broker.snapshot(KEY) == []


@pytest.mark.asyncio
async def test_cancelled_waiter_releases_card_and_reverse_index():
    broker = broker_for_test()
    record = await register(broker)
    waiter = asyncio.create_task(broker._await_answer(record))
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    assert broker.snapshot(KEY) == []
    assert broker._pending == {}
    assert broker._by_rpc == {}


@pytest.mark.asyncio
async def test_emitter_failure_does_not_leave_an_unreachable_request():
    broker = broker_for_test()

    async def failing_emitter(key, event):
        raise RuntimeError("synthetic emit failure")

    broker.set_emitter(failing_emitter)
    with pytest.raises(RuntimeError, match="synthetic emit failure"):
        await register(broker)

    assert broker._pending == {}
    assert broker._by_rpc == {}


@pytest.mark.asyncio
async def test_cancellation_during_emit_also_releases_request():
    broker = broker_for_test()
    started = asyncio.Event()

    async def waiting_emitter(key, event):
        started.set()
        await asyncio.Event().wait()

    broker.set_emitter(waiting_emitter)
    task = asyncio.create_task(register(broker))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert broker._pending == {}
    assert broker._by_rpc == {}


@pytest.mark.asyncio
async def test_answer_releases_full_record_but_retains_lightweight_dedupe():
    broker = broker_for_test()
    record = await register(broker)

    assert await broker.answer(KEY, record.ui_request_id, ANSWER) == {"status": "accepted"}
    assert broker._pending == {}
    assert broker._by_rpc == {}
    assert await broker._await_answer(record) == ANSWER
    assert await broker.answer(KEY, record.ui_request_id, ANSWER) == {"status": "accepted"}
    different = {"answers": {"major": {"answers": ["其他"]}}}
    assert await broker.answer(KEY, record.ui_request_id, different) == {"status": "conflict"}
    with pytest.raises(PermissionError, match="clarification_scope_mismatch"):
        await broker.answer(SessionKey("other-tenant", "session-1"), record.ui_request_id, ANSWER)
    receipt = broker._answered[record.ui_request_id]
    assert not hasattr(receipt, "future")
    assert not hasattr(receipt, "questions")


@pytest.mark.asyncio
async def test_answer_receipts_have_fifo_capacity_and_ttl():
    clock = FakeClock()
    broker = broker_for_test(clock=clock, answer_cache_max_entries=2, answer_cache_ttl_seconds=10)
    records = []
    for rpc_id in range(3):
        record = await register(broker, rpc_id)
        await broker.answer(KEY, record.ui_request_id, ANSWER)
        await broker._await_answer(record)
        records.append(record)

    assert len(broker._answered) == 2
    assert await broker.answer(KEY, records[0].ui_request_id, ANSWER) == {"status": "unknown_request"}
    assert await broker.answer(KEY, records[1].ui_request_id, ANSWER) == {"status": "accepted"}
    clock.value += 10
    assert await broker.answer(KEY, records[2].ui_request_id, ANSWER) == {"status": "unknown_request"}
    assert broker._answered == {}


@pytest.mark.asyncio
async def test_already_expired_record_cannot_be_answered_before_timeout_task_runs():
    broker = broker_for_test()
    record = await register(broker)
    record.expires_at = 0.0

    assert await broker.answer(KEY, record.ui_request_id, ANSWER) == {"status": "unknown_request"}
    assert not record.answered
    with pytest.raises(UserInputError, match="clarification_expired"):
        await broker._await_answer(record)
    assert broker._by_rpc == {}


@pytest.mark.asyncio
async def test_runtime_expiry_releases_reverse_indices_and_answer_receipts():
    broker = broker_for_test()
    answered = await register(broker, 1)
    await broker.answer(KEY, answered.ui_request_id, ANSWER)
    pending = await register(broker, 2)

    broker.expire_runtime("generation-1")

    assert isinstance(pending.future.exception(), UserInputError)
    assert broker._pending == {}
    assert broker._by_rpc == {}
    assert await broker.answer(KEY, answered.ui_request_id, ANSWER) == {"status": "unknown_request"}


@pytest.mark.asyncio
async def test_foreign_generation_resolution_cannot_remove_current_request():
    broker = broker_for_test()
    record = await register(broker)
    try:
        broker.resolve_native("old-generation", 1, "resolved")
        assert broker.snapshot(KEY)
        assert not record.future.done()
    finally:
        if record.future.done() and not record.future.cancelled():
            record.future.exception()
        else:
            record.future.cancel()


@pytest.mark.asyncio
async def test_foreign_thread_resolved_notification_cannot_remove_current_request():
    broker = broker_for_test()
    record = await register(broker)
    try:
        broker.handle_notification("generation-1", {
            "method": "serverRequest/resolved", "params": {"threadId": "other-thread", "requestId": 1},
        })
        assert not record.future.done()
        assert broker.snapshot(KEY)
    finally:
        record.future.cancel()


@pytest.mark.asyncio
async def test_expiry_hook_failure_still_releases_both_indices():
    async def expire(record):
        raise RuntimeError("synthetic interrupt failure")

    broker = broker_for_test(on_expired=expire)
    record = await register(broker)
    record.expires_at = 0.0
    with pytest.raises(RuntimeError, match="synthetic interrupt failure"):
        await broker._await_answer(record)
    assert broker._pending == broker._by_rpc == {}


@pytest.mark.asyncio
async def test_runtime_rotation_invalidates_old_request_and_allows_reused_rpc_id():
    broker = broker_for_test()
    old = await register(broker)
    broker.start_runtime("generation-2")
    assert isinstance(old.future.exception(), UserInputError)
    current = await register(broker)
    try:
        broker.resolve_native("generation-1", 1, "resolved")
        assert not current.future.done()
        assert broker.snapshot(KEY)[0]["requestId"] == current.ui_request_id
        broker.resolve_native("generation-2", 1, "resolved")
        with pytest.raises(UserInputError, match="clarification_resolved"):
            await broker._await_answer(current)
        assert broker._by_rpc == {}
    finally:
        if not current.future.done():
            current.future.cancel()


@pytest.mark.asyncio
async def test_rpc_integer_and_string_ids_do_not_collide():
    broker = broker_for_test()
    integer_request = await register(broker, 1)
    string_request = await register(broker, "1")
    try:
        broker.resolve_native("generation-1", 1, "resolved")
        with pytest.raises(UserInputError, match="clarification_resolved"):
            await broker._await_answer(integer_request)
        assert not string_request.future.done()
        assert broker.snapshot(KEY)[0]["requestId"] == string_request.ui_request_id
    finally:
        string_request.future.cancel()


@pytest.mark.asyncio
async def test_duplicate_active_rpc_id_is_rejected_without_replacing_original():
    broker = broker_for_test()
    record = await register(broker)
    try:
        with pytest.raises(UserInputError, match="server_request_id_conflict"):
            await register(broker)
        assert len(broker._pending) == len(broker._by_rpc) == 1
        assert broker.snapshot(KEY)[0]["requestId"] == record.ui_request_id
    finally:
        record.future.cancel()


@pytest.mark.asyncio
async def test_old_waiter_cleanup_cannot_remove_reused_rpc_index():
    broker = broker_for_test()
    old = await register(broker)
    broker.resolve_native("generation-1", 1, "resolved")
    current = await register(broker)
    try:
        with pytest.raises(UserInputError, match="clarification_resolved"):
            await broker._await_answer(old)
        broker.resolve_native("generation-1", 1, "resolved")
        with pytest.raises(UserInputError, match="clarification_resolved"):
            await broker._await_answer(current)
        assert broker._pending == broker._by_rpc == {}
    finally:
        if not current.future.done():
            current.future.cancel()


@pytest.mark.asyncio
async def test_resolved_notification_uses_its_request_id_and_generation():
    broker = broker_for_test()
    record = await register(broker, "rpc-id")
    broker.handle_notification("generation-1", {
        "method": "serverRequest/resolved", "params": {"threadId": "thread-1", "requestId": "rpc-id"},
    })
    with pytest.raises(UserInputError, match="clarification_resolved"):
        await broker._await_answer(record)
    assert broker.snapshot(KEY) == []
    assert broker._by_rpc == {}


@pytest.mark.asyncio
async def test_expiry_hook_finishes_before_timeout_is_reported():
    entered = asyncio.Event()
    release = asyncio.Event()

    async def expire(record):
        assert record.native_thread_id == "thread-1"
        assert record.native_turn_id == "native-turn-1"
        entered.set()
        await release.wait()

    broker = broker_for_test(on_expired=expire)
    record = await register(broker)
    record.expires_at = 0.0
    waiter = asyncio.create_task(broker._await_answer(record))
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        assert not waiter.done()
        assert broker.snapshot(KEY) == []
        release.set()
        with pytest.raises(UserInputError, match="clarification_expired"):
            await waiter
        assert broker._by_rpc == {}
    finally:
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)


@pytest.mark.asyncio
async def test_unresolved_trusted_scope_does_not_fall_back_to_runtime_metadata():
    broker = broker_for_test(scope_resolver=lambda thread_id: None)
    with pytest.raises(PermissionError, match="clarification_scope_unavailable"):
        broker._scope_from_params({
            "threadId": "unknown-thread", "_meta": {"tenantId": "tenant-1", "sessionId": "session-1"},
        })


@pytest.mark.parametrize("options", [
    {"ttl_seconds": 0}, {"ttl_seconds": float("nan")}, {"ttl_seconds": float("inf")},
    {"answer_cache_max_entries": 0}, {"answer_cache_max_entries": True},
    {"answer_cache_ttl_seconds": 0}, {"answer_cache_ttl_seconds": float("nan")},
])
def test_invalid_lifecycle_configuration_is_rejected(options):
    with pytest.raises(ValueError):
        broker_for_test(**options)
