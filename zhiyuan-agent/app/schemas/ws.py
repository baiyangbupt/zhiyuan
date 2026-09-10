from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class WSMessage(BaseModel):
    """客户端 → 服务端 WebSocket 消息。"""

    type: Literal["chat", "planEditSelect", "intentDetectSelect", "intentSelect", "pendingConfirmation"] = "chat"
    tenant_id: str = Field(default="", alias="tenantId")
    session_id: str = Field(alias="sessionId")
    user_id: str = Field(default="", alias="userId")
    content: str  # planEditSelect / intentDetectSelect / intentSelect 时为 JSON: {"selected": [...], "message_id": "..."}
    conversation_action: dict | None = Field(default=None, alias="conversationAction")

    model_config = ConfigDict(populate_by_name=True)


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
