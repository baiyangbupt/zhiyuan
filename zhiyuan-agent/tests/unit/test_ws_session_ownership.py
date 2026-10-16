import asyncio
from types import SimpleNamespace

import pytest

from app.gateway.access import TicketIdentity
from app.gateway.session_runtime import SessionRuntime
from app.gateway.ui_events import SessionKey
from app.server import _handle_gateway_compat_ws_loop, _handle_gateway_ws_loop


KEY = SessionKey("tenant-1", "session-1")


def socket_for(runtime, *, store=None):
    receiving = asyncio.Event()

    async def receive_json():
        receiving.set()
        await asyncio.Event().wait()

    async def send(payload):
        return None

    return SimpleNamespace(
        state=SimpleNamespace(identity=TicketIdentity(KEY.tenant_id, KEY.session_id, "user-1")),
        app=SimpleNamespace(state=SimpleNamespace(session_runtime=runtime, event_store=store)),
        query_params={}, receive_json=receive_json, send_json=send, send_text=send,
    ), receiving


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["native", "compat"])
async def test_trusted_connection_is_owned_before_first_message_and_released_on_cancel(route):
    runtime = SessionRuntime()
    socket, receiving = socket_for(runtime)
    coroutine = (
        _handle_gateway_ws_loop(socket, None) if route == "native"
        else _handle_gateway_compat_ws_loop(socket, None, KEY.tenant_id, "bot-1")
    )
    task = asyncio.create_task(coroutine)
    try:
        await receiving.wait()
        assert runtime.lifecycle.inspect(KEY).owners == {"connection": 1}
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert runtime.lifecycle.inspect(KEY).total == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.parametrize("detach", [False, True])
async def test_replay_failure_or_cancel_closes_connection_and_preserves_route_policy(monkeypatch, cancel, detach):
    entered = asyncio.Event()
    release = asyncio.Event()

    async def current_epoch(key):
        entered.set()
        await release.wait()
        raise RuntimeError("offline replay unavailable")

    runtime = SessionRuntime()
    runtime.detach_work(KEY, release.wait, label="detached action")
    await runtime.submit(KEY, client_request_id="", ui_turn_id="turn-1", work=asyncio.Event().wait)
    socket, receiving = socket_for(runtime, store=SimpleNamespace(current_epoch=current_epoch))
    monkeypatch.setattr("app.server._DETACH_ON_CLOSE", detach)
    task = asyncio.create_task(_handle_gateway_ws_loop(socket, None))
    try:
        await entered.wait()
        channel = runtime.current_channel(KEY)
        assert runtime.lifecycle.inspect(KEY).owners.get("connection") == 1
        if cancel:
            task.cancel()
        else:
            release.set()
        result = (await asyncio.gather(task, return_exceptions=True))[0]
        assert isinstance(result, asyncio.CancelledError if cancel else RuntimeError)
        assert runtime.lifecycle.inspect(KEY).owners.get("connection", 0) == 0
        assert runtime.current_channel(KEY) is (None if detach else channel)
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await runtime.cancel_all()
        await asyncio.gather(*runtime._detached)


@pytest.mark.asyncio
async def test_untrusted_query_does_not_create_session_ownership():
    runtime = SessionRuntime()
    socket, receiving = socket_for(runtime)
    socket.query_params = {"sessionId": "other-session"}
    task = asyncio.create_task(_handle_gateway_ws_loop(socket, None))
    try:
        await receiving.wait()
        assert runtime.lifecycle.inspect(SessionKey(KEY.tenant_id, "other-session")) is None
        assert runtime.lifecycle.inspect(KEY) is None
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
