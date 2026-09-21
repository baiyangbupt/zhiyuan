import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import WebSocketDisconnect

from app.schemas import WSMessage
from app.server import _handle_gateway_ws_loop

class _PermissiveAccessGuard:
    """测试替身：直接放行并返回固定身份。

    **只在测试里装**。生产路径无条件校验票据（见 app/gateway/access.py），
    它的正确性由 tests/integration/test_gateway_access.py 的 7 条覆盖——
    这里不重复验它，只负责让 WS 用例能连上。
    """

    def __init__(self, tenant_id: str = "test-tenant", bot_id: str = "test-bot") -> None:
        self._tenant_id = tenant_id
        self._bot_id = bot_id

    async def verify(self, ticket, origin):
        from app.gateway.access import TicketIdentity

        return TicketIdentity(
            tenant_id=self._tenant_id,
            session_id="test-session",
            user_id="test-user",
            bot_id=self._bot_id,
            origin=origin or "http://127.0.0.1:3201",
        )





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


@pytest.fixture(autouse=True)
def _permissive_access_guard():
    """生产路径无条件校验 WS 票据；测试装一个放行替身。"""
    from app.server import app as _app

    _app.state.conversation_access_guard = _PermissiveAccessGuard()
    yield
    _app.state.conversation_access_guard = None


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
    # 客户端断开现在被循环吞掉并正常返回（与 compat 路由一致），而不是往上抛。
    # 这条测试真正要验的是"缺 tenant 时不调用 gateway、且回了错误帧"，
    # 之前的 pytest.raises 只是用来终止循环，不是被测契约的一部分。
    await _handle_gateway_ws_loop(socket, Gateway())

    assert socket.sent[0]["type"] == "recoverable.error"
    assert "缺少 tenantId" in socket.sent[0]["content"]
