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

    # 增量与 live 那条路（`adapt_notification`）**同一份形状**：`{chunk, itemId?}`——
    # 此前这里是老形状 `content`（V1 白名单模型没有这个字段，到前端会被整条丢掉）。
    assert delta == {"type": "assistant.delta", "payload": {"chunk": "候选"}}
    # 终态走 **V1 白名单形状** ✓✓（`conversationEvents.mjs:35` ✓）：前端 V1 那条路
    # （`toConversationEvent` ✓，页面导入的就是它 ✓）从 `payload.message` 取答案 ✓；
    # 先前给的是 `content` ✗——V1 模型没有这个字段 ✓，会被丢掉 ✓
    #（真栈实测：帧到了、UI 渲染不出答案 ✓）。
    assert completed == {
        "type": "assistant.completed",
        "payload": {
            "message": "已完成",
            "responseType": "text",
            "executionStatus": "completed",
            "limitations": [],
        },
    }


def test_event_adapter_keeps_item_id_only_when_present() -> None:
    """`itemId` 是可选键 ✓：真 codex 带它 ✓、替身不带 ✓——不带时必须**不填** ✓，
    填个空串会让前端把一个 `''` 键当真 item 去归并 ✓。"""
    with_id = adapt_codex_item(
        {"type": "item/agentMessage/delta", "delta": "x", "itemId": "msg_1"}
    )
    without_id = adapt_codex_item({"type": "item/agentMessage/delta", "delta": "x"})

    assert with_id == {"type": "assistant.delta", "payload": {"chunk": "x", "itemId": "msg_1"}}
    assert without_id == {"type": "assistant.delta", "payload": {"chunk": "x"}}
    # 空增量不产事件（否则会凭空多出 `{"chunk": ""}` 的空帧）。
    assert adapt_codex_item({"type": "item/agentMessage/delta", "delta": ""}) is None


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
