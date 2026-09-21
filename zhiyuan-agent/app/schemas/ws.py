from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# 不携带用户文本的控制消息：`content` 必须为空串。
# 与 `chat` 分开，是为了让"这条是控制还是内容"在类型上可判，
# 而不是靠服务端去猜 content 里是不是 JSON。
CONTENT_FREE_MESSAGE_TYPES = frozenset({"turnInterrupt", "sessionResume"})


class WSMessage(BaseModel):
    """客户端 → 服务端 WebSocket 消息。

    v1 客户端会多带 `protocolVersion` / `turnId` / `clientRequestId`；
    老客户端不带这些字段，行为逐字不变——所以它们全部可选且有默认值。
    """

    type: Literal[
        "chat",
        "planEditSelect",
        "intentDetectSelect",
        "intentSelect",
        "pendingConfirmation",
        "clarificationAnswer",
        "turnInterrupt",
        "turnSteer",
        "sessionResume",
    ] = "chat"
    tenant_id: str = Field(default="", alias="tenantId")
    session_id: str = Field(alias="sessionId")
    user_id: str = Field(default="", alias="userId")
    content: str  # planEditSelect / intentDetectSelect / intentSelect 时为 JSON: {"selected": [...], "message_id": "..."}
    conversation_action: dict | None = Field(default=None, alias="conversationAction")

    protocol_version: int | None = Field(default=None, alias="protocolVersion")
    turn_id: str = Field(default="", alias="turnId")
    client_request_id: str = Field(default="", alias="clientRequestId")
    # 澄清回答与 chat 走不同字段：`conversationAction` 的语义是"确认/取消一个提案"，
    # 把它复用成回答选择题会让两种完全不同的确认混在一个字段里。
    clarification_answer: dict | None = Field(default=None, alias="clarificationAnswer")

    model_config = ConfigDict(populate_by_name=True)

    @model_validator(mode="after")
    def _enforce_content_rules(self) -> WSMessage:
        if self.type == "turnSteer":
            # turnSteer 是唯一一条必须带内容的控制消息：转述文本没有别的字段可放，
            # 而空的转述等于什么都没说——宁可明确报错，也不要静默变成空操作。
            if not self.content:
                raise ValueError("turn_steer_requires_content")
            return self
        if self.type in CONTENT_FREE_MESSAGE_TYPES and self.content:
            raise ValueError("control_message_must_not_carry_content")
        return self


class WSResponse(BaseModel):
    """服务端 → 客户端 WebSocket 响应（**旧 compat 格式**）。

    v1 的统一事件走 `app.gateway.ui_events.UiEvent`，不是这个模型：
    它的 `type` 是固定 Literal，把新事件名塞进来会立刻破坏老客户端的解析。
    两种格式不能同时生成两份终态消息。
    """

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
