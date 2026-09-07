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
    assert completed == {"type": "assistant.completed", "content": "已完成"}


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
