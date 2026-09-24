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


def test_semantic_eval_requires_failed_status_to_expose_recovery_step() -> None:
    result = evaluate_trace(
        SemanticExpectation(
            case_id="failed-read-result",
            response_type="text",
            execution_status="failed",
            limitations_required=True,
            next_step_required=True,
        ),
        {
            "responseType": "text",
            "executionStatus": "failed",
            "limitations": ["工具查询失败"],
            "nextStep": "请稍后重试",
        },
    )

    assert result["passed"] is True


def test_semantic_eval_checks_conversation_action_type() -> None:
    result = evaluate_trace(
        SemanticExpectation(
            case_id="confirm-proposal",
            conversation_action_type="confirm_proposal",
        ),
        {"conversationAction": {"actionType": "cancel_proposal"}},
    )
    assert result["passed"] is False
    assert result["failures"] == ["conversation_action_mismatch"]


def test_semantic_eval_measures_the_requested_goal_type_not_the_ref() -> None:
    """写路径量的是 `proposalRequest.goalType`，**不是** `proposalRef`。

    写路径上新提案走 `proposalRequest`、`proposalRef` 保持空 ✓——只量 `proposalRef`
    （既有的 `proposal_required`）会把整条写路径漏掉，所以 P2 新开了
    `write-path-proposal` 场景 + 这条判据（真栈实测：模型给出 `goalType=fill_to_count` ✓）。
    """
    ok = evaluate_trace(
        SemanticExpectation(case_id="write-path", proposal_request_goal_type="fill_to_count"),
        {"proposalRef": None, "proposalGoalType": "fill_to_count"},
    )
    assert ok["passed"] is True
    assert ok["observed"]["proposalGoalType"] == "fill_to_count"

    wrong_goal = evaluate_trace(
        SemanticExpectation(case_id="write-path", proposal_request_goal_type="fill_to_count"),
        {"proposalRef": None, "proposalGoalType": "must_include_scope"},
    )
    assert wrong_goal["failures"] == ["proposal_goal_type_mismatch"]
