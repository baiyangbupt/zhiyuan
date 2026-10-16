import asyncio
from types import SimpleNamespace

import pytest

from app.gateway.service import GatewayService
from app.gateway.conversation_actions import ConversationActionResult
from app.gateway.session_lifecycle import SessionLifecycle
from app.gateway.session_runtime import SessionRuntime
from app.gateway.ui_events import SessionKey


KEY = SessionKey("tenant-1", "session-1")


def make_gateway(**kwargs):
    return GatewayService(
        mode="codex_write", codex=SimpleNamespace(), legacy=None,
        message_store=None, binding_loader=lambda **arguments: None,
        snapshot_loader=kwargs.pop("snapshot_loader", lambda **arguments: {}),
        **kwargs,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("method, kind, extra", [
    ("get_current_snapshot", "gateway_read", {}),
    ("get_authoritative_snapshot", "gateway_read", {}),
    ("continue_after_action", "continuation", {
        "user_id": "user-1", "turn_id": "turn-1", "user_turn_watermark": 0,
        "action_result": {"actionStatus": "applied", "proposalRef": "proposal-1"},
    }),
    ("continue_after_proposal_preview", "continuation", {
        "user_id": "user-1", "turn_id": "turn-1", "user_turn_watermark": 0,
        "preview": {"status": "blocked"},
    }),
])
async def test_public_snapshot_and_continuation_waits_own_session(method, kind, extra):
    entered = asyncio.Event()

    async def load(**kwargs):
        entered.set()
        await asyncio.Event().wait()

    gateway = make_gateway(snapshot_loader=load)
    task = asyncio.create_task(getattr(gateway, method)(
        tenant_id=KEY.tenant_id, session_id=KEY.session_id, **extra,
    ))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        assert gateway.lifecycle.inspect(KEY).owners == {kind: 1}
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert gateway.lifecycle.inspect(KEY).total == 0


@pytest.mark.asyncio
async def test_turn_waiting_for_lock_is_owned_and_still_advances_user_watermark():
    gateway = make_gateway()
    lock = asyncio.Lock()
    gateway._session_locks[KEY] = lock
    await lock.acquire()
    task = asyncio.create_task(gateway.handle_turn(
        tenant_id=KEY.tenant_id, session_id=KEY.session_id,
        user_id="user-1", turn_id="turn-1", content="hello",
    ))
    try:
        await asyncio.sleep(0)
        assert gateway.user_turn_watermark(tenant_id=KEY.tenant_id, session_id=KEY.session_id) == 1
        assert gateway.lifecycle.inspect(KEY).owners == {"turn": 1}
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        lock.release()
    assert gateway.lifecycle.inspect(KEY).total == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("refresh", [False, True])
async def test_action_owns_execution_through_cancellation(monkeypatch, refresh):
    entered = asyncio.Event()

    async def execute(**kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("app.gateway.service.execute_conversation_action", execute)
    gateway = make_gateway()
    method = gateway.execute_action_and_refresh if refresh else gateway.execute_action
    task = asyncio.create_task(method(
        tenant_id=KEY.tenant_id, session_id=KEY.session_id, action={}, snapshot={},
    ))
    try:
        await entered.wait()
        assert gateway.lifecycle.inspect(KEY).owners == {"action": 2 if refresh else 1}
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert gateway.lifecycle.inspect(KEY).total == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["interrupt_codex_turn", "steer_codex_turn"])
async def test_control_owns_trusted_thread_lookup_and_io(method):
    entered = asyncio.Event()

    async def control(*args):
        entered.set()
        await asyncio.Event().wait()

    gateway = make_gateway()
    gateway._threads[KEY] = "thread-1"
    gateway.codex = SimpleNamespace(interrupt_turn=control, steer_turn=control)
    arguments = (KEY, "native-turn") if method.startswith("interrupt") else (KEY, "native-turn", "extra")
    task = asyncio.create_task(getattr(gateway, method)(*arguments))
    try:
        await entered.wait()
        assert gateway.lifecycle.inspect(KEY).owners == {"gateway_read": 1}
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert gateway.lifecycle.inspect(KEY).total == 0


def test_shared_registry_is_adopted_and_mismatch_is_rejected_even_on_late_binding():
    runtime = SessionRuntime()
    gateway = make_gateway(session_runtime=runtime)
    assert gateway.lifecycle is runtime.lifecycle
    with pytest.raises(ValueError, match="lifecycle"):
        make_gateway(session_runtime=runtime, lifecycle=SessionLifecycle())
    with pytest.raises(ValueError, match="lifecycle"):
        gateway.session_runtime = SessionRuntime()
    assert gateway.session_runtime is runtime
    gateway.session_runtime = SessionRuntime(lifecycle=runtime.lifecycle)


@pytest.mark.asyncio
async def test_applied_action_keeps_owner_through_failed_refresh_without_losing_result(monkeypatch):
    entered = asyncio.Event()
    release = asyncio.Event()

    async def execute(**kwargs):
        return ConversationActionResult(action_status="applied", proposal_ref="proposal-1")

    async def load(**kwargs):
        entered.set()
        await release.wait()
        raise RuntimeError("offline refresh unavailable")

    monkeypatch.setattr("app.gateway.service.execute_conversation_action", execute)
    gateway = make_gateway(snapshot_loader=load)
    task = asyncio.create_task(gateway.execute_action_and_refresh(
        tenant_id=KEY.tenant_id, session_id=KEY.session_id, action={}, snapshot={},
    ))
    try:
        await entered.wait()
        assert gateway.lifecycle.inspect(KEY).owners == {"action": 1}
    finally:
        release.set()
    result = await task
    assert result["actionResult"]["actionStatus"] == "applied"
    assert result["actionResult"]["proposalRef"] == "proposal-1"
    assert gateway.lifecycle.inspect(KEY).total == 0
