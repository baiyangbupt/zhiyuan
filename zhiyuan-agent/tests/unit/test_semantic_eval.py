from app.engine.semantic_eval import SemanticExpectation, evaluate_trace


def test_semantic_eval_accepts_reference_and_evidence_trace() -> None:
    result = evaluate_trace(
        SemanticExpectation(
            case_id="followup-history",
            required_entity_ids={"school-1", "school-2"},
            required_message_fragments={"甲大学"},
            response_type="fact",
            evidence_required=True,
        ),
        {
            "entityIds": ["school-1", "school-2"],
            "evidenceIds": ["ev-1"],
            "responseType": "fact",
            "message": "甲大学历史分数",
            "clarificationRequested": False,
            "toolCalls": [],
        },
    )
    assert result["passed"] is True


def test_semantic_eval_rejects_write_tool_and_missing_clarification() -> None:
    result = evaluate_trace(
        SemanticExpectation(
            case_id="missing-history-scope",
            required_tool_names={"admission.get_history"},
            forbidden_tool_names={"plan_apply"},
            clarification_required=True,
        ),
        {
            "toolCalls": [{"name": "plan_apply"}],
            "responseType": "text",
            "clarificationRequested": False,
        },
    )
    assert result["passed"] is False
    assert set(result["failures"]) == {
        "missing_tools",
        "forbidden_tools",
        "clarification_mismatch",
    }
