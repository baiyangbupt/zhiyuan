import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import WebSocketDisconnect

from app.gateway.access import TicketIdentity
from app.server import (
    _compat_gateway_loop,
    _handle_control_message,
    _handle_ws_loop,
    _native_gateway_loop,
    ws_chat_compat,
)


class ScopedSocket:
    def __init__(self, payload, *, authenticated=True):
        self.payload = payload
        self.received = False
        self.closed = None
        self.sent = []
        self.state = SimpleNamespace(
            identity=TicketIdentity(tenant_id="1", session_id="42", user_id="7")
            if authenticated else None
        )
        self.app = SimpleNamespace(state=SimpleNamespace(gateway_tenant_id="1"))
        self.query_params = {}

    async def accept(self):
        pass

    async def receive_json(self):
        if self.received:
            raise WebSocketDisconnect()
        self.received = True
        return self.payload

    async def close(self, code=1000):
        self.closed = code

    async def send_text(self, text):
        self.sent.append(json.loads(text))

    async def send_json(self, payload):
        self.sent.append(payload)


class ScopedChannel:
    uses_v1 = False

    def bind_session(self, key):
        self.key = key

    def bind_turn(self, turn_id):
        self.turn_id = turn_id

    async def emit(self, event):
        pass

    async def emit_frame(self, event):
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["native", "compat", "legacy", "legacy_compat"])
@pytest.mark.parametrize("field,value", [
    ("tenantId", "2"), ("tenant_id", "2"),
    ("sessionId", "999"), ("session_id", "999"),
    ("userId", "888"), ("user_id", "888"),
])
async def test_messages_cannot_override_the_authenticated_connection(route, field, value, monkeypatch):
    payload = {"sessionId": "42", "userId": "7", "content": "hello", field: value}
    socket = ScopedSocket(payload)
    gateway = SimpleNamespace(handle_turn=AsyncMock(return_value={"reply": "stub"}))
    service = SimpleNamespace(handle_message=AsyncMock(return_value="stub"))
    saved = AsyncMock()
    monkeypatch.setattr("app.server.message_store.save_user_message", saved)
    monkeypatch.setattr("app.server.message_store.save_agent_message", AsyncMock())
    if route == "native":
        await _native_gateway_loop(socket, gateway, None, ScopedChannel())
    elif route == "compat":
        await _compat_gateway_loop(socket, gateway, "1", None, ScopedChannel())
    elif route == "legacy":
        try:
            await _handle_ws_loop(socket, service)
        except WebSocketDisconnect:
            pass
    else:
        monkeypatch.setattr("app.server._verify_conversation_access", AsyncMock(return_value=socket.state.identity))
        socket.app.state.chat_service = service
        await ws_chat_compat(socket, "1", "bot-1")
    assert socket.closed == 4403
    gateway.handle_turn.assert_not_awaited()
    service.handle_message.assert_not_awaited()
    saved.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["native", "compat"])
async def test_missing_message_identity_is_filled_only_from_the_ticket(route):
    socket = ScopedSocket({"content": "hello"})
    gateway = SimpleNamespace(handle_turn=AsyncMock(return_value={"reply": "stub"}))
    if route == "native":
        await _native_gateway_loop(socket, gateway, None, ScopedChannel())
    else:
        await _compat_gateway_loop(socket, gateway, "1", None, ScopedChannel())
    assert socket.closed is None
    arguments = gateway.handle_turn.await_args.kwargs
    assert (arguments["tenant_id"], arguments["session_id"], arguments["user_id"]) == ("1", "42", "7")


@pytest.mark.asyncio
async def test_missing_authenticated_identity_never_reaches_gateway():
    socket = ScopedSocket({"tenantId": "1", "sessionId": "42", "content": "hello"}, authenticated=False)
    gateway = SimpleNamespace(handle_turn=AsyncMock(return_value={"reply": "stub"}))
    await _native_gateway_loop(socket, gateway, None, ScopedChannel())
    assert socket.closed == 4403
    gateway.handle_turn.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("message_type", ["turnInterrupt", "turnSteer", "clarificationAnswer"])
async def test_control_messages_cannot_select_another_session(message_type):
    socket = ScopedSocket({})
    broker = SimpleNamespace(answer=AsyncMock(return_value={"status": "answered"}))
    socket.app.state.gateway_service = SimpleNamespace(user_input_broker=broker)
    runtime = SimpleNamespace(
        interrupt=AsyncMock(return_value={"status": "interrupting"}),
        steer=AsyncMock(return_value={"status": "steered"}),
    )
    await _handle_control_message(socket, {
        "type": message_type, "sessionId": "999", "turnId": "turn-1",
        "content": "continue", "clarificationAnswer": {"requestId": "request-1"},
    }, runtime, "1", ScopedChannel())
    assert socket.closed == 4403
    runtime.interrupt.assert_not_awaited()
    runtime.steer.assert_not_awaited()
    broker.answer.assert_not_awaited()
