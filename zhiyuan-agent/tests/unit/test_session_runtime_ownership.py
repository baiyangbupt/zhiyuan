import asyncio
from types import SimpleNamespace

import pytest

from app.gateway.session_lifecycle import SessionLifecycle
from app.gateway.session_runtime import ACCEPTED, ConnectionChannel, SessionRuntime
from app.gateway.ui_events import SessionKey


KEY = SessionKey("tenant-1", "session-1")


@pytest.mark.asyncio
async def test_queued_admission_is_owned_and_cancellation_releases_only_waiter():
    entered = asyncio.Event()
    release = asyncio.Event()

    async def admit(*args):
        entered.set()
        await release.wait()
        return ACCEPTED

    async def finish(*args):
        return None

    lifecycle = SessionLifecycle()
    runtime = SessionRuntime(lifecycle=lifecycle, store=SimpleNamespace(admit=admit, finish_request=finish))
    first = asyncio.create_task(runtime.submit(KEY, client_request_id="first", ui_turn_id="one", work=release.wait))
    await entered.wait()
    second = asyncio.create_task(runtime.submit(KEY, client_request_id="second", ui_turn_id="two", work=release.wait))
    await asyncio.sleep(0)
    assert lifecycle.inspect(KEY).owners == {"admission": 2}
    second.cancel()
    await asyncio.gather(second, return_exceptions=True)
    assert lifecycle.inspect(KEY).owners == {"admission": 1}
    release.set()
    assert await first == ACCEPTED
    await runtime.cancel_all()
    await asyncio.sleep(0)
    assert lifecycle.inspect(KEY).total == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("detached", [False, True])
async def test_task_owns_before_first_execution_and_releases_on_prestart_cancel(detached):
    lifecycle = SessionLifecycle()
    runtime = SessionRuntime(lifecycle=lifecycle)
    started = asyncio.Event()
    if detached:
        runtime.detach_work(KEY, started.wait, label="action")
        task = next(iter(runtime._detached))
        kind = "action"
    else:
        await runtime.submit(KEY, client_request_id="", ui_turn_id="one", work=started.wait)
        task = runtime._tasks[KEY]
        kind = "turn"
    assert lifecycle.inspect(KEY).owners == {kind: 1}
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert lifecycle.inspect(KEY).total == 0
    assert not started.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("detached", [False, True])
async def test_scheduling_failure_releases_owner_and_closes_coroutine(monkeypatch, detached):
    runtime = SessionRuntime()
    coroutines = []

    def cannot_schedule(coroutine):
        coroutines.append(coroutine)
        raise RuntimeError("cannot schedule")

    monkeypatch.setattr(asyncio, "create_task", cannot_schedule)
    with pytest.raises(RuntimeError, match="cannot schedule"):
        if detached:
            runtime.detach_work(KEY, asyncio.Event().wait, label="action")
        else:
            await runtime.submit(KEY, client_request_id="", ui_turn_id="one", work=asyncio.Event().wait)
    assert runtime.lifecycle.inspect(KEY).total == 0
    assert coroutines[0].cr_frame is None
    assert not runtime._tasks and not runtime._detached


@pytest.mark.asyncio
async def test_detached_handoff_and_status_write_have_continuous_ownership():
    runtime = SessionRuntime()
    action_started = asyncio.Event()
    release = asyncio.Event()
    status_entered = asyncio.Event()
    status_release = asyncio.Event()

    async def finish(key, request_id, payload):
        if '"completed"' in payload:
            status_entered.set()
            await status_release.wait()

    async def admit(*args):
        return ACCEPTED

    runtime._store = SimpleNamespace(admit=admit, finish_request=finish)

    async def action():
        assert runtime.lifecycle.inspect(KEY).owners.get("action") == 1
        action_started.set()
        await release.wait()

    async def turn():
        deferred = runtime.detach_work(KEY, action, label="action", client_request_id="request")
        assert runtime.lifecycle.inspect(KEY).owners == {"turn": 1, "action": 1}
        return deferred

    await runtime.submit(KEY, client_request_id="request", ui_turn_id="one", work=turn)
    turn_task = runtime._tasks[KEY]
    await action_started.wait()
    await turn_task
    assert runtime.lifecycle.inspect(KEY).owners == {"action": 1}
    detached = next(iter(runtime._detached))
    release.set()
    await status_entered.wait()
    assert runtime.lifecycle.inspect(KEY).owners == {"action": 1}
    status_release.set()
    await detached
    await asyncio.sleep(0)
    assert runtime.lifecycle.inspect(KEY).total == 0


@pytest.mark.asyncio
async def test_connections_are_independent_from_latest_delivery_route():
    runtime = SessionRuntime()

    async def send(frame):
        return True

    old = ConnectionChannel(send)
    new = ConnectionChannel(send)
    runtime.attach_connection(KEY, old)
    runtime.attach_connection(KEY, old)
    runtime.attach_connection(KEY, new)
    assert runtime.lifecycle.inspect(KEY).owners == {"connection": 2}
    with pytest.raises(ValueError):
        old.bind_session(SessionKey("other", "session-1"))
    runtime.detach_connection(KEY, old)
    assert runtime.current_channel(KEY) is new
    assert runtime.lifecycle.inspect(KEY).total == 2
    await old.close()
    assert runtime.lifecycle.inspect(KEY).owners == {"connection": 1}
    await new.close()
    await new.close()
    assert runtime.lifecycle.inspect(KEY).total == 0
    assert runtime.current_channel(KEY) is new


@pytest.mark.asyncio
async def test_connection_lease_covers_sender_cancellation_cleanup():
    runtime = SessionRuntime()
    sending = asyncio.Event()
    closing = asyncio.Event()
    release = asyncio.Event()

    async def send(frame):
        sending.set()
        try:
            await asyncio.Event().wait()
        finally:
            closing.set()
            await release.wait()

    channel = ConnectionChannel(send)
    runtime.attach_connection(KEY, channel)
    channel.start()
    await channel.emit_frame({})
    await sending.wait()
    closer = asyncio.create_task(channel.close())
    await closing.wait()
    assert runtime.lifecycle.inspect(KEY).owners == {"connection": 1}
    release.set()
    await closer
    assert runtime.lifecycle.inspect(KEY).total == 0


@pytest.mark.asyncio
async def test_publish_owns_during_persistence_even_if_connection_closes():
    entered = asyncio.Event()
    release = asyncio.Event()

    async def append(*args):
        entered.set()
        await release.wait()
        raise RuntimeError("store unavailable")

    async def send(frame):
        return True

    runtime = SessionRuntime()
    channel = ConnectionChannel(send, store=SimpleNamespace(append=append))
    runtime.attach_connection(KEY, channel)
    publishing = asyncio.create_task(runtime.publish(KEY, {"type": "test"}))
    await entered.wait()
    await channel.close()
    assert runtime.lifecycle.inspect(KEY).owners == {"publish": 1}
    release.set()
    assert await publishing is True
    assert runtime.lifecycle.inspect(KEY).total == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["request_status", "interrupt", "steer"])
async def test_standalone_runtime_reads_and_controls_own_their_wait(method):
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocked(*args):
        entered.set()
        await release.wait()

    runtime = SessionRuntime(
        store=SimpleNamespace(request_result=blocked),
        interrupt_impl=blocked, steer_impl=blocked,
    )
    if method == "request_status":
        coroutine = runtime.request_status(KEY, "request-1")
    else:
        runtime._store = None
        await runtime.submit(KEY, client_request_id="", ui_turn_id="one", work=release.wait)
        runtime.bind_codex_turn(KEY, "one", "native-one")
        coroutine = runtime.interrupt(KEY, "one") if method == "interrupt" else runtime.steer(KEY, "one", "extra")
    task = asyncio.create_task(coroutine)
    try:
        await entered.wait()
        assert runtime.lifecycle.inspect(KEY).owners.get("gateway_read") == 1
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        release.set()
        await runtime.cancel_all()
    assert runtime.lifecycle.inspect(KEY).total == 0


@pytest.mark.asyncio
async def test_connection_cleanup_is_shared_and_released_even_if_closer_is_cancelled():
    runtime = SessionRuntime()
    sending = asyncio.Event()
    closing = asyncio.Event()
    release = asyncio.Event()

    async def send(frame):
        sending.set()
        try:
            await asyncio.Event().wait()
        finally:
            closing.set()
            await release.wait()

    channel = ConnectionChannel(send)
    runtime.attach_connection(KEY, channel)
    channel.start()
    await channel.emit_frame({})
    await sending.wait()
    first = asyncio.create_task(channel.close())
    await closing.wait()
    second = asyncio.create_task(channel.close())
    await asyncio.sleep(0)
    assert not second.done()
    assert runtime.lifecycle.inspect(KEY).owners == {"connection": 1}
    first.cancel()
    await asyncio.gather(first, second, return_exceptions=True)
    assert runtime.lifecycle.inspect(KEY).total == 0
    await channel.close()


@pytest.mark.asyncio
async def test_channel_cannot_be_attached_to_another_registry_or_reopened():
    runtime = SessionRuntime()

    async def send(frame):
        return True

    channel = ConnectionChannel(send)
    runtime.attach_connection(KEY, channel)
    other = SessionRuntime()
    with pytest.raises(ValueError, match="lifecycle"):
        other.attach_connection(KEY, channel)
    assert other.lifecycle.inspect(KEY) is None
    await channel.close()
    with pytest.raises(ValueError, match="closed"):
        runtime.attach_connection(KEY, channel)
    with pytest.raises(ValueError, match="closed"):
        channel.start()
    assert runtime.lifecycle.inspect(KEY).total == 0


@pytest.mark.asyncio
async def test_sender_scheduling_failure_closes_coroutine_and_connection_can_release(monkeypatch):
    runtime = SessionRuntime()
    coroutines = []

    async def send(frame):
        return True

    def fail(coroutine):
        coroutines.append(coroutine)
        raise RuntimeError("sender cannot start")

    channel = ConnectionChannel(send)
    runtime.attach_connection(KEY, channel)
    monkeypatch.setattr(asyncio, "create_task", fail)
    with pytest.raises(RuntimeError, match="sender cannot start"):
        channel.start()
    await channel.close()
    assert runtime.lifecycle.inspect(KEY).total == 0
    assert coroutines[0].cr_frame is None


@pytest.mark.asyncio
async def test_server_detached_action_covers_watermark_terminal_and_continuation():
    from app.server import _run_action_work

    runtime = SessionRuntime()
    terminal_entered = asyncio.Event()
    terminal_release = asyncio.Event()
    continuation_entered = asyncio.Event()
    continuation_release = asyncio.Event()
    events = []

    def watermark(**kwargs):
        assert runtime.lifecycle.inspect(KEY).owners == {"action": 1}
        return 7

    async def snapshot(**kwargs):
        return {}

    async def execute(**kwargs):
        return {"actionResult": {"actionStatus": "applied", "proposalRef": "proposal-1"}}

    async def continuation(**kwargs):
        assert kwargs["user_turn_watermark"] == 7
        assert runtime.lifecycle.inspect(KEY).owners == {"action": 1}
        continuation_entered.set()
        await continuation_release.wait()
        return None

    async def emit(event):
        assert runtime.lifecycle.inspect(KEY).owners == {"action": 1}
        events.append(event)
        if event["type"] == "conversationAction.result":
            terminal_entered.set()
            await terminal_release.wait()

    gateway = SimpleNamespace(
        user_turn_watermark=watermark, get_authoritative_snapshot=snapshot,
        execute_action_and_refresh=execute, continue_after_action=continuation,
    )
    msg = SimpleNamespace(
        session_id=KEY.session_id, user_id="user-1", conversation_action={"proposalRef": "proposal-1"},
    )
    async def send(frame):
        return True

    channel = ConnectionChannel(send, store=object())
    runtime.detach_work(KEY, lambda: _run_action_work(
        gateway, msg, KEY.tenant_id, "turn-1", emit,
        channel, make_emit=lambda turn: emit,
    ), label="offline action")
    task = next(iter(runtime._detached))
    try:
        await asyncio.wait_for(terminal_entered.wait(), 1)
        assert runtime.lifecycle.inspect(KEY).owners == {"action": 1}
        terminal_release.set()
        await asyncio.wait_for(continuation_entered.wait(), 1)
        assert runtime.lifecycle.inspect(KEY).owners == {"action": 1}
    finally:
        terminal_release.set()
        continuation_release.set()
        await task
    assert [event["type"] for event in events] == ["conversationAction.result", "assistant.completed", "turn.completed"]
    assert runtime.lifecycle.inspect(KEY).total == 0
