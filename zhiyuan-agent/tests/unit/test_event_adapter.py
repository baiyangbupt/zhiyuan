from __future__ import annotations

import json

from app.gateway.event_adapter import adapt_codex_item
from app.schemas.ws import WSResponse


def test_event_adapter_never_exposes_raw_tool_arguments() -> None:
    event = adapt_codex_item(
        {
            "type": "mcpToolCall",
            "tool": "admission.get_history",
            "arguments": {"userId": "secret", "schoolId": "school-1"},
            "status": "completed",
        }
    )

    assert event["type"] == "planning.status"
    assert "arguments" not in event
    assert "admission.get_history" not in json.dumps(event)
    assert "userId" not in json.dumps(event)


def test_event_adapter_maps_safe_assistant_delta_and_completion() -> None:
    delta = adapt_codex_item({"type": "item/agentMessage/delta", "delta": "候选"})
    completed = adapt_codex_item({"type": "turn/completed", "message": "已完成"})

    assert delta == {"type": "assistant.delta", "content": "候选"}
    # 终态走 **V1 白名单形状** ✓✓（`conversationEvents.mjs:35` ✓）：前端 V1 那条路
    # （`toConversationEvent` ✓，页面导入的就是它 ✓）从 `payload.message` 取答案 ✓；
    # 先前给的是 `content` ✗——V1 模型没有这个字段 ✓，会被丢掉 ✓
    #（真栈实测：帧到了、UI 渲染不出答案 ✓）。
    # 两者形状不同是**契约本身**这样写的 ✓（delta 走 `content` ✓、completed 走白名单 ✓），
    # 不是这里写错 ✓——所以断言也照契约分开写 ✓。
    assert completed == {
        "type": "assistant.completed",
        "payload": {
            "message": "已完成",
            "responseType": "text",
            "executionStatus": "completed",
            "limitations": [],
        },
    }


def test_event_adapter_drops_unknown_internal_items() -> None:
    assert adapt_codex_item({"type": "reasoning", "text": "private"}) is None


def test_ws_response_accepts_stable_gateway_event_types() -> None:
    for event_type in (
        "assistant.delta",
        "assistant.completed",
        "planning.status",
        "evidence.updated",
        "recommendation.card",
        "recoverable.error",
    ):
        response = WSResponse(type=event_type, session_id="session-1", content="{}")
        assert response.type == event_type
