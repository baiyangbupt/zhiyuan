"""C1：WebSocket 握手前的访问校验。

这里验的是 Gateway 侧那一半：票据缺失、来源不符、票无效时的拒绝方式，
以及"拒绝发生在 accept 之前"这条结构约束（后者由接线方式保证，见 server.py）。
"""
from __future__ import annotations

import pytest

from app.gateway.access import AccessDenied, ConversationAccessGuard


ORIGIN = "http://127.0.0.1:3201"


def _guard(consume_result=None, *, allowed=(ORIGIN,)):
    calls: list[tuple] = []

    async def consume(ticket, origin):
        calls.append((ticket, origin))
        return consume_result

    return ConversationAccessGuard(consume, allowed_origins=allowed), calls


@pytest.mark.asyncio
async def test_a_valid_ticket_returns_the_server_side_identity() -> None:
    guard, calls = _guard({"tenantId": 1, "sessionId": 42, "userId": 7, "botId": 3})

    identity = await guard.verify("ticket-value", ORIGIN)

    assert identity.tenant_id == "1"
    assert identity.session_id == "42"
    assert identity.user_id == "7"
    assert calls == [("ticket-value", ORIGIN)]


@pytest.mark.asyncio
async def test_a_missing_ticket_is_refused_without_calling_java() -> None:
    guard, calls = _guard({"tenantId": 1})

    with pytest.raises(AccessDenied) as denied:
        await guard.verify(None, ORIGIN)

    assert denied.value.status == 401
    # 没有票就没有可消费的东西：白跑一次网络请求只会放大攻击面。
    assert calls == []


@pytest.mark.asyncio
async def test_a_non_allowlisted_origin_is_refused_without_consuming_the_ticket() -> None:
    guard, calls = _guard({"tenantId": 1})

    with pytest.raises(AccessDenied) as denied:
        await guard.verify("ticket-value", "https://evil.example.com")

    assert denied.value.status == 403
    # 关键：**不消费**。消费掉的话，一次攻击尝试就能把用户的票作废——
    # 那是一个可被利用的拒绝服务。
    assert calls == []


@pytest.mark.asyncio
async def test_a_missing_origin_is_refused() -> None:
    guard, _ = _guard({"tenantId": 1})

    with pytest.raises(AccessDenied) as denied:
        await guard.verify("ticket-value", None)

    assert denied.value.status == 403


@pytest.mark.asyncio
async def test_an_invalid_ticket_is_refused() -> None:
    guard, _ = _guard(None)

    with pytest.raises(AccessDenied) as denied:
        await guard.verify("used-or-expired", ORIGIN)

    # 无效/已用/过期**同一个回包**：区分开来等于告诉对方"这张票存在过"。
    assert denied.value.reason == "ticket_invalid"


@pytest.mark.asyncio
async def test_an_empty_allowlist_refuses_everything() -> None:
    guard, calls = _guard({"tenantId": 1}, allowed=())

    with pytest.raises(AccessDenied):
        await guard.verify("ticket-value", ORIGIN)

    assert calls == []


@pytest.mark.asyncio
async def test_the_guard_does_not_accept_an_identity_from_the_websocket_body() -> None:
    """身份只有一个来源：Java 用票换回来的那个。

    这条用"consume 返回什么就是什么"来证明——如果 guard 会合并 WS 传来的
    身份字段，它就必须有第二个输入参数；它没有。
    """
    guard, _ = _guard({"tenantId": 1, "sessionId": 42, "userId": 7})

    identity = await guard.verify("ticket-value", ORIGIN)

    assert identity.user_id == "7"
