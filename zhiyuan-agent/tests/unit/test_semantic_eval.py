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


def test_semantic_eval_checks_result_synthesis_status_and_next_step() -> None:
    result = evaluate_trace(
        SemanticExpectation(
            case_id="partial-read-result",
            response_type="fact",
            execution_status="partial",
            limitations_required=True,
            next_step_required=True,
        ),
        {
            "responseType": "fact",
            "executionStatus": "partial",
            "limitations": ["仅覆盖已成功返回的学校"],
            "nextStep": "继续查询未完成学校",
        },
    )

    assert result["passed"] is True


def test_semantic_eval_rejects_fact_without_domain_tool_and_evidence() -> None:
    result = evaluate_trace(
        SemanticExpectation(
            case_id="fact-without-tool",
            response_type="fact",
            required_tool_names={"admission.get_history"},
            evidence_required=True,
        ),
        {
            "responseType": "fact",
            "toolCalls": [],
            "evidenceIds": [],
        },
    )

    assert result["passed"] is False
    assert set(result["failures"]) == {"missing_tools", "evidence_missing"}


def test_semantic_eval_rejects_write_tool_in_mixed_read_write_request() -> None:
    result = evaluate_trace(
        SemanticExpectation(
            case_id="mixed-read-and-write-request",
            required_tool_names={"admission.get_history"},
            forbidden_tool_names={"plan_apply"},
            response_type="clarification",
            execution_status="blocked",
            clarification_required=True,
        ),
        {
            "toolCalls": [
                {"name": "admission.get_history"},
                {"name": "plan_apply"},
            ],
            "responseType": "clarification",
            "executionStatus": "blocked",
            "clarificationRequested": True,
        },
    )

    assert result["passed"] is False
    assert "forbidden_tools" in result["failures"]
