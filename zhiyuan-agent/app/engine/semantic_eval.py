from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(slots=True)
class SemanticExpectation:
    """Observable expectations for a multi-turn dialogue case."""

    case_id: str
    required_entity_ids: set[str] = field(default_factory=set)
    required_tool_names: set[str] = field(default_factory=set)
    forbidden_tool_names: set[str] = field(default_factory=set)
    response_type: str | set[str] | None = None
    required_message_fragments: set[str] = field(default_factory=set)
    clarification_required: bool | None = None
    evidence_required: bool = False
    proposal_required: bool = False
    execution_status: str | None = None
    limitations_required: bool = False
    next_step_required: bool = False
    conversation_action_type: str | None = None
    # 写路径（P2）：要求模型**请求编译**一条提案、且目标（`proposalRequest.goalType`）是这个值。
    # 与 `proposal_required` 不同：后者量的 `proposalRef` 是"引用已有提案"，
    # 写路径上新提案走 `proposalRequest`（`proposalRef` 保持空）——只量它会整个漏掉。
    proposal_request_goal_type: str | None = None


def evaluate_trace(
    expectation: SemanticExpectation, trace: Mapping[str, Any]
) -> dict[str, Any]:
    calls = trace.get("toolCalls") or []
    names = {str(call.get("name") or "") for call in calls if isinstance(call, Mapping)}
    entities = {str(value) for value in trace.get("entityIds") or []}
    evidence = {str(value) for value in trace.get("evidenceIds") or []}
    failures: list[str] = []
    missing_entities = sorted(expectation.required_entity_ids - entities)
    missing_tools = sorted(expectation.required_tool_names - names)
    forbidden_tools = sorted(expectation.forbidden_tool_names & names)
    if missing_entities:
        failures.append("missing_entities")
    if missing_tools:
        failures.append("missing_tools")
    if forbidden_tools:
        failures.append("forbidden_tools")
    if expectation.response_type and (
        trace.get("responseType") not in expectation.response_type
        if isinstance(expectation.response_type, set)
        else trace.get("responseType") != expectation.response_type
    ):
        failures.append("response_type_mismatch")
    message = str(trace.get("message") or "")
    if any(fragment not in message for fragment in expectation.required_message_fragments):
        failures.append("message_reference_missing")
    if (
        expectation.clarification_required is not None
        and bool(trace.get("clarificationRequested")) != expectation.clarification_required
    ):
        failures.append("clarification_mismatch")
    if expectation.evidence_required and not evidence:
        failures.append("evidence_missing")
    if expectation.proposal_required and not trace.get("proposalRef"):
        failures.append("proposal_missing")
    if (
        expectation.proposal_request_goal_type
        and trace.get("proposalGoalType") != expectation.proposal_request_goal_type
    ):
        failures.append("proposal_goal_type_mismatch")
    if expectation.execution_status and trace.get("executionStatus") != expectation.execution_status:
        failures.append("execution_status_mismatch")
    if expectation.limitations_required and not trace.get("limitations"):
        failures.append("limitations_missing")
    if expectation.next_step_required and not trace.get("nextStep"):
        failures.append("next_step_missing")
    action = trace.get("conversationAction") or {}
    if expectation.conversation_action_type and action.get("actionType") != expectation.conversation_action_type:
        failures.append("conversation_action_mismatch")
    return {
        "caseId": expectation.case_id,
        "passed": not failures,
        "failures": failures,
        "observed": {
            "entities": sorted(entities),
            "tools": sorted(names),
            "evidenceIds": sorted(evidence),
            "responseType": trace.get("responseType"),
            "message": message,
            "clarificationRequested": bool(trace.get("clarificationRequested")),
            "proposalRef": trace.get("proposalRef"),
            "proposalGoalType": trace.get("proposalGoalType"),
            "executionStatus": trace.get("executionStatus"),
            "limitations": list(trace.get("limitations") or []),
            "nextStep": trace.get("nextStep"),
            "conversationAction": action,
        },
    }
