from app.engine.turn_trace import build_turn_trace
from app.gateway.contracts import TurnOutput


def test_turn_trace_records_observable_tool_and_clarification_facts() -> None:
    output = TurnOutput(
        responseType="clarification",
        message="还缺少省份",
        clarification="请提供省份",
        uncertainties=["province"],
    )
    trace = build_turn_trace(
        {
            "events": [
                {
                    "type": "mcpToolCall",
                    "toolName": "catalog.search_schools",
                    "status": "completed",
                    "arguments": {"query": "计算机"},
                }
            ]
        },
        output,
        entity_ids=["school-1", "school-1"],
    )

    assert trace.tool_calls == [
        {
            "name": "catalog.search_schools",
            "status": "completed",
            "argumentKeys": ["query"],
        }
    ]
    assert trace.entity_ids == ["school-1"]
    assert trace.clarification_requested is True
    assert trace.orchestration[0]["ready"] is True
    assert trace.orchestration[0]["missingArguments"] == []


def test_turn_trace_accepts_real_mcp_tool_field() -> None:
    output = TurnOutput(
        responseType="fact",
        message="已查询",
        evidenceRefs=[
            {
                "evidenceId": "ev-1",
                "sourceLevel": "authoritative",
                "dataVersion": "v1",
            }
        ],
    )
    trace = build_turn_trace(
        {
            "events": [
                {
                    "type": "item/mcpToolCall",
                    "tool": "admission.get_history",
                    "arguments": {"schoolId": "school-1"},
                }
            ]
        },
        output,
        entity_ids=["school-1"],
    )

    assert trace.tool_calls[0]["name"] == "admission.get_history"
    assert trace.orchestration[0]["missingArguments"] == [
        "majorId", "areaId", "batch", "year", "subjectType"
    ]
    assert trace.orchestration[0]["ready"] is False


def test_turn_trace_marks_repeated_identical_invocations() -> None:
    output = TurnOutput(responseType="text", message="已处理")
    trace = build_turn_trace(
        {
            "events": [
                {"type": "mcpToolCall", "toolName": "catalog.search_schools", "arguments": {"query": "计算机"}},
                {"type": "mcpToolCall", "toolName": "catalog.search_schools", "arguments": {"query": "计算机"}},
            ]
        },
        output,
        entity_ids=[],
    )

    assert trace.orchestration[0]["duplicate"] is False
    assert trace.orchestration[1]["duplicate"] is True
