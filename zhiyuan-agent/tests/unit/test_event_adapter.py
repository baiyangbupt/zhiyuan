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


def test_raw_model_prose_never_leaves_adapter_before_validation() -> None:
    from app.gateway.event_adapter import adapt_notification
    secret = '某校最低分999分，保证录取'
    for item_type in (
        "item/agentMessage/delta", "agentMessage/delta", "assistant.delta",
        "turn/completed", "item/agentMessage/completed", "assistant.completed",
    ):
        assert adapt_codex_item({"type": item_type, "delta": secret, "message": secret}) is None
    for method in ("item/agentMessage/delta", "agentMessage/delta"):
        assert adapt_notification({"method": method, "params": {"delta": secret}}, "t1") == []
    progress = adapt_notification({"method": "item/started", "params": {
        "item": {"type": "mcpToolCall", "id": "c1", "tool": "admission.get_history"}
    }}, "t1")
    assert progress[0]["type"] == "tool.progress"
    assert secret not in json.dumps(progress)


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


def _interpretation_item(result: dict) -> dict:
    return {
        "method": "item/completed",
        "params": {
            "item": {
                "type": "mcpToolCall",
                "id": "call-1",
                "tool": "planning.interpret_admission",
                "status": "completed",
                "result": result,
            }
        },
    }


def test_event_adapter_emits_bounded_interpretation_preview() -> None:
    from app.gateway.event_adapter import adapt_notification

    scenarios = [
        {
            "scenarioId": "base",
            "label": "base",
            "structureStatus": "首个稳/保位置",
            "condition": "若前序均未满足",
            "landingEntry": {
                "level": "unit",
                "id": "u2",
                "position": 14,
                "schoolName": "潍坊学院",
                "majorName": None,
                "pathTier": "稳",
                "schoolRatio": 0.55,
            },
            "path": [{"id": "u%d" % index} for index in range(45)],
            "drivers": ["前序 13 条均为冲档", "校线录取率=56"],
            "caveats": ["结构说明，不是录取概率"],
            "evidenceRefs": [],
        }
    ]
    events = adapt_notification(
        _interpretation_item(
            {
                "structuredContent": {
                    "kind": "interpretation",
                    "data": {
                        "status": "completed",
                        "planVersion": 7,
                        "admissionMode": "major_group",
                        "safetyCoverage": "有保底档位",
                        "dataCompletenessBand": "完整",
                        "orderAnomaly": False,
                        "scenarios": scenarios,
                        "baseLanding": scenarios[0],
                        "caveats": ["审查：本省保底不足", "结构说明，不是录取概率"],
                        "caveatDetails": [
                            {
                                "text": "审查：本省保底不足",
                                "level": "hard",
                                "code": "safety_guard",
                            },
                            {
                                "text": "结构说明，不是录取概率",
                                "level": "soft",
                                "code": None,
                            },
                        ],
                    },
                }
            }
        ),
        "turn-1",
    )

    assert [event["type"] for event in events] == ["tool.progress", "interpretation.preview"]
    payload = events[1]["payload"]
    assert payload["planVersion"] == 7
    assert payload["safetyCoverage"] == "有保底档位"
    assert payload["baseLanding"]["label"] == "base"
    assert payload["scenarios"][0]["landingEntry"]["schoolName"] == "潍坊学院"
    # 有界：完整 path/evidenceRefs 不出去；drivers/caveats 截断。
    assert "path" not in payload["scenarios"][0]
    assert "evidenceRefs" not in payload["scenarios"][0]
    assert len(payload["scenarios"][0]["drivers"]) <= 3
    assert payload["caveatDetails"][0]["level"] == "hard"
    assert payload["caveatDetails"][0]["code"] == "safety_guard"
    assert payload["caveatDetails"][1]["level"] == "soft"
    assert "path" not in payload["caveatDetails"][0]


def test_event_adapter_accepts_interpretation_text_content_fallback() -> None:
    from app.gateway.event_adapter import adapt_notification

    text = json.dumps(
        {
            "kind": "interpretation",
            "data": {
                "status": "no_plan",
                "planVersion": 7,
                "safetyCoverage": "无法判断",
                "caveats": ["当前没有可解读的方案条目。"],
            },
        },
        ensure_ascii=False,
    )
    events = adapt_notification(
        _interpretation_item({"content": [{"type": "text", "text": text}]}),
        "turn-1",
    )

    assert [event["type"] for event in events] == ["tool.progress", "interpretation.preview"]
    assert events[1]["payload"]["status"] == "no_plan"
    assert events[1]["payload"]["safetyCoverage"] == "无法判断"


def test_event_adapter_ignores_failed_interpretation_result() -> None:
    from app.gateway.event_adapter import adapt_notification

    events = adapt_notification(
        _interpretation_item(
            {"structuredContent": {"data": {"status": "stale_interpretation"}}}
        ),
        "turn-1",
    )

    assert [event["type"] for event in events] == ["tool.progress"]
