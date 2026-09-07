from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class WSMessage(BaseModel):
    """客户端 → 服务端 WebSocket 消息。"""

    type: Literal["chat"] = "chat"
    session_id: str
    user_id: str = ""
    content: str


class WSResponse(BaseModel):
    """服务端 → 客户端 WebSocket 响应。"""

    type: Literal[
        "reply",
        "error",
        "card",
        "planEditSelectPopup",
        "intentDetectSelectPopup",
        "intentConfirmPopup",
        "pendingConfirmationCard",
        "planningWorkspaceAction",
        "thinking",
        "assistant.delta",
        "assistant.completed",
        "planning.status",
        "evidence.updated",
        "recommendation.card",
        "recoverable.error",
    ]
    session_id: str
    content: str
