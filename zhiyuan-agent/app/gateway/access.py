"""WebSocket 握手前的访问校验（C1）。

浏览器连 WS 时带一张一次性票据，Gateway 拿它去 Java 换回身份。
**身份不从 WS 报文或 query 串里解析**——解析权在服务端；浏览器只能出示票，
不能出示身份。

四条边界：
1. **accept 之前**校验。先接受再校验等于先开了一条匿名通道。
2. **Origin 必须命中白名单**，且与票据绑定的来源一致。通配会让绑定失去意义。
3. **票无效/已用/过期/来源不符回同一个拒绝**，不告诉对方是哪一种。
4. **没有票据就不放行**——本地开发也一样，否则"只在本地方便一下"会变成
   一个长期存在的匿名入口。
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


DEFAULT_ALLOWED_ORIGINS = ("http://127.0.0.1:3201",)

# 与 Java 侧 ConversationWsTicketStore 的语义对齐：三种失败共用一个结果。
REJECTION_REASON = "ticket_invalid"


@dataclass(frozen=True)
class TicketIdentity:
    tenant_id: str
    session_id: str
    user_id: str
    bot_id: str | None = None
    origin: str | None = None


class AccessDenied(RuntimeError):
    """握手被拒。调用方应当**不 accept** 直接关闭连接。"""

    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


def bind_message_identity(identity: TicketIdentity | None, payload: Any) -> dict[str, Any]:
    """Bind an inbound WebSocket message to the identity proven at handshake."""
    if not isinstance(identity, TicketIdentity) or not all(
        (identity.tenant_id, identity.session_id, identity.user_id)
    ):
        raise AccessDenied(403, "session_forbidden")
    if not isinstance(payload, dict):
        raise AccessDenied(403, "session_forbidden")

    scoped = dict(payload)
    for aliases, expected in (
        (("tenantId", "tenant_id"), identity.tenant_id),
        (("sessionId", "session_id"), identity.session_id),
        (("userId", "user_id"), identity.user_id),
    ):
        for alias in aliases:
            supplied = payload.get(alias)
            if supplied not in (None, "") and str(supplied) != expected:
                raise AccessDenied(403, "session_forbidden")
            scoped[alias] = expected
    return scoped


class ConversationAccessGuard:
    def __init__(
        self,
        consume: Callable[[str, str | None], Awaitable[dict[str, Any] | None]],
        *,
        allowed_origins: tuple[str, ...] = DEFAULT_ALLOWED_ORIGINS,
    ) -> None:
        self._consume = consume
        self._allowed_origins = tuple(origin for origin in allowed_origins if origin)

    async def verify(self, ticket: str | None, origin: str | None) -> TicketIdentity:
        if not ticket or not ticket.strip():
            raise AccessDenied(401, "ticket_required")
        if not self._origin_allowed(origin):
            # 来源不在白名单：连票都不必消费。消费掉会让一次攻击尝试
            # 顺手把用户的票作废——那是一个可被利用的拒绝服务。
            raise AccessDenied(403, "origin_forbidden")
        identity = await self._consume(ticket.strip(), origin)
        if not identity:
            raise AccessDenied(403, REJECTION_REASON)
        return TicketIdentity(
            tenant_id=str(identity.get("tenantId") or ""),
            session_id=str(identity.get("sessionId") or ""),
            user_id=str(identity.get("userId") or ""),
            bot_id=None if identity.get("botId") is None else str(identity.get("botId")),
            origin=identity.get("origin"),
        )

    def _origin_allowed(self, origin: str | None) -> bool:
        if not origin:
            # 没有 Origin 的握手（脚本/非浏览器）一律拒：来源不明就不能说
            # "这张票只在该来源有效"。
            return False
        return origin.strip() in self._allowed_origins
