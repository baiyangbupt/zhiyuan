import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import WebSocketDisconnect

from app.schemas import WSMessage
from app.server import _handle_gateway_ws_loop


def test_ws_message_accepts_structured_conversation_action_alias():
    message = WSMessage.model_validate(
        {
            "type": "pendingConfirmation",
                "sessionId": "s1",
            "content": "",
            "conversationAction": {
                "actionType": "confirm_proposal",
                "proposalRef": "pending-1",
                "expectedSourceVersion": 7,
            },
        }
    )

    assert message.conversation_action == {
        "actionType": "confirm_proposal",
        "proposalRef": "pending-1",
        "expectedSourceVersion": 7,
    }


def test_ws_message_remains_backward_compatible_without_action():
    message = WSMessage.model_validate({"sessionId": "s1", "content": "继续查询"})
    assert message.conversation_action is None


def test_ws_message_accepts_tenant_id_alias():
    message = WSMessage.model_validate(
        {"tenantId": "tenant-7", "sessionId": "s1", "content": "继续查询"}
    )

    assert message.tenant_id == "tenant-7"


@pytest.mark.parametrize("user_key", ["userId", "user_id"])
def test_ws_message_preserves_user_identity(user_key):
    message = WSMessage.model_validate({"sessionId": "s1", user_key: "u1", "content": "继续"})
    assert message.user_id == "u1"


@pytest.mark.asyncio
async def test_gateway_websocket_rejects_missing_tenant_before_calling_gateway():
    class Socket:
        def __init__(self):
            self.app = SimpleNamespace(state=SimpleNamespace(gateway_tenant_id=""))
            self.sent: list[dict] = []
            self.received = False

        async def receive_json(self):
            if self.received:
                raise WebSocketDisconnect()
            self.received = True
            return {"type": "chat", "sessionId": "s1", "userId": "u1", "content": "继续"}

        async def send_text(self, value: str):
            self.sent.append(json.loads(value))

    class Gateway:
        async def handle_turn(self, **kwargs):
            raise AssertionError("must not call gateway without tenant")

    socket = Socket()
    with pytest.raises(WebSocketDisconnect):
        await _handle_gateway_ws_loop(socket, Gateway())

    assert socket.sent[0]["type"] == "recoverable.error"
    assert "缺少 tenantId" in socket.sent[0]["content"]
