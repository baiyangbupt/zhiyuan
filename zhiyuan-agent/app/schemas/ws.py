from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class WSMessage(BaseModel):
    """客户端 → 服务端 WebSocket 消息。"""

    type: Literal["chat", "planEditSelect", "intentDetectSelect", "intentSelect", "pendingConfirmation"] = "chat"
    session_id: str
    user_id: str = ""
    content: str  # planEditSelect / intentDetectSelect / intentSelect 时为 JSON: {"selected": [...], "message_id": "..."}


class WSResponse(BaseModel):
    """服务端 → 客户端 WebSocket 响应。"""

    type: Literal[
        "reply",
        "error",
        "card",
        "interestAnalysisPopup",
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
    content: str  # interestAnalysisPopup / planEditSelectPopup / intentDetectSelectPopup / intentConfirmPopup 时为 JSON 字符串
