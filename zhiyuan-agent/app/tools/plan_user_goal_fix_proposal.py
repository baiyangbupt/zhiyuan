from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.tools.plan_goal_resolution import scope_entity_type, scope_value_list
from app.tools.plan_orchestration_models import LinkedRepairAction, LinkedRepairProposal, PlanGoal


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def scopes_for_user_goal_fix_req(
    scope: dict[str, Any],
    *,
    evidence_source: str,
) -> list[dict[str, Any]]:
    values = scope_value_list(scope)
    entity_type = scope_entity_type(scope) or "unknown"
    return [
        {
            "scopeType": entity_type,
            "entityType": entity_type,
            "name": value,
            "normalizedName": value,
            "rawText": value,
            "resolutionStatus": "resolved",
            "evidence": {
                "source": evidence_source,
                "values": values,
            },
        }
        for value in values
    ]


def build_user_goal_fix_proposal_req_from_plan_goal(
    plan_goal: PlanGoal,
    planning_version: int,
    *,
    context: dict[str, Any] | None = None,
    evidence_source: str = "plan_goal",
) -> dict[str, Any] | None:
    if plan_goal.needs_clarification:
        return None
    if plan_goal.goal_type not in {"only_keep_scope", "must_include_scope", "exclude_scope"}:
        return None
    target_scopes = [
        req_scope
        for scope in plan_goal.target_scopes
        if isinstance(scope, dict)
        for req_scope in scopes_for_user_goal_fix_req(scope, evidence_source=evidence_source)
    ]
    negative_scopes = [
        req_scope
        for scope in plan_goal.negative_scopes
        if isinstance(scope, dict)
        for req_scope in scopes_for_user_goal_fix_req(scope, evidence_source=evidence_source)
    ]
    if plan_goal.goal_type in {"only_keep_scope", "must_include_scope"} and not target_scopes:
        return None
    if plan_goal.goal_type == "exclude_scope" and not negative_scopes:
        return None
    return {
        "proposalSource": "user_goal",
        "goalType": plan_goal.goal_type,
        "userOriginalText": plan_goal.user_original_text,
        "confidence": plan_goal.confidence,
        "sourceVersionGuard": planning_version or None,
        "targetScopes": target_scopes,
        "negativeScopes": negative_scopes,
        "qualityGuards": [
            str(item or "").strip()
            for item in plan_goal.quality_guards
            if str(item or "").strip()
        ],
        "tradeoffGuards": [
            str(item or "").strip()
            for item in plan_goal.structure_targets
            if str(item or "").strip()
        ],
        "context": context or {},
    }


def build_user_goal_fix_proposal_req_from_goal_payload(
    goal: dict[str, Any],
    planning_version: int,
    *,
    context: dict[str, Any] | None = None,
    evidence_source: str = "confirmed_intent",
) -> dict[str, Any] | None:
    if not isinstance(goal, dict) or planning_version <= 0:
        return None
    goal_type = str(goal.get("goal_type") or goal.get("goalType") or "").strip()
    if goal_type not in {"only_keep_scope", "must_include_scope", "exclude_scope"}:
        return None
    target_scopes = [
        req_scope
        for item in goal.get("target_scopes", [])
        if isinstance(item, dict)
        for req_scope in scopes_for_user_goal_fix_req(item, evidence_source=evidence_source)
    ]
    negative_scopes = [
        req_scope
        for item in goal.get("negative_scopes", [])
        if isinstance(item, dict)
        for req_scope in scopes_for_user_goal_fix_req(item, evidence_source=evidence_source)
    ]
    if goal_type in {"only_keep_scope", "must_include_scope"} and not target_scopes:
        return None
    if goal_type == "exclude_scope" and not negative_scopes:
        return None
    return {
        "proposalSource": "user_goal",
        "goalType": goal_type,
        "userOriginalText": str(goal.get("user_original_text") or goal.get("userOriginalText") or "").strip(),
        "confidence": str(goal.get("confidence") or "high").strip(),
        "sourceVersionGuard": planning_version,
        "targetScopes": target_scopes,
        "negativeScopes": negative_scopes,
        "qualityGuards": [
            str(item or "").strip()
            for item in goal.get("quality_guards", [])
            if str(item or "").strip()
        ],
        "tradeoffGuards": [
            str(item or "").strip()
            for item in goal.get("structure_targets", [])
            if str(item or "").strip()
        ],
        "context": context or {},
    }


def linked_repair_action_from_backend(action: dict[str, Any]) -> LinkedRepairAction | None:
    if not isinstance(action, dict):
        return None
    action_type = str(action.get("actionType") or action.get("action_type") or "").strip()
    if not action_type:
        return None
    try:
        return LinkedRepairAction(
            action_type=action_type,  # type: ignore[arg-type]
            source_check_code=str(action.get("sourceCheckCode") or action.get("source_check_code") or "").strip(),
            summary=str(action.get("summary") or "").strip(),
            detail=str(action.get("detail") or "").strip(),
            unit_ids=list(action.get("unitIds") or action.get("unit_ids") or []),
            volunteer_ids=list(action.get("volunteerIds") or action.get("volunteer_ids") or []),
            remove_unit_ids=list(action.get("removeUnitIds") or action.get("remove_unit_ids") or []),
            remove_volunteer_ids=list(action.get("removeVolunteerIds") or action.get("remove_volunteer_ids") or []),
            candidate_unit_ids=list(action.get("candidateUnitIds") or action.get("candidate_unit_ids") or []),
            candidate_volunteer_ids=list(action.get("candidateVolunteerIds") or action.get("candidate_volunteer_ids") or []),
            replacement_pairs=list(action.get("replacementPairs") or action.get("replacement_pairs") or []),
        )
    except (TypeError, ValueError, ValidationError):
        return None


def linked_repair_proposal_from_backend(
    proposal: dict[str, Any],
    *,
    default_source: str,
    default_source_version_guard: int,
) -> LinkedRepairProposal | None:
    if not isinstance(proposal, dict):
        return None
    strategy = str(proposal.get("strategy") or "").strip()
    if not strategy:
        return None
    actions = [
        action
        for action in (
            linked_repair_action_from_backend(item)
            for item in (proposal.get("actions") or [])
            if isinstance(item, dict)
        )
        if action is not None
    ]
    try:
        return LinkedRepairProposal(
            proposal_id=str(proposal.get("proposalId") or proposal.get("proposal_id") or "").strip(),
            proposal_source=str(proposal.get("proposalSource") or proposal.get("proposal_source") or default_source or "user_goal").strip(),  # type: ignore[arg-type]
            source_version=_as_int(proposal.get("sourceVersion") or proposal.get("source_version")),
            source_review_version=_as_int(proposal.get("sourceReviewVersion") or proposal.get("source_review_version")),
            source_version_guard=_as_int(
                proposal.get("sourceVersionGuard") or proposal.get("source_version_guard"),
                default_source_version_guard,
            ),
            source_check_codes=list(proposal.get("sourceCheckCodes") or proposal.get("source_check_codes") or []),
            strategy=strategy,  # type: ignore[arg-type]
            status=str(proposal.get("status") or "preview_only").strip(),  # type: ignore[arg-type]
            title=str(proposal.get("title") or "").strip(),
            summary=str(proposal.get("summary") or "").strip(),
            impact=str(proposal.get("impact") or "").strip(),
            blocking_reason=str(proposal.get("blockingReason") or proposal.get("blocking_reason") or "").strip(),
            candidate_shortages=list(proposal.get("candidateShortages") or proposal.get("candidate_shortages") or []),
            actions=actions,
            dry_run_result=dict(proposal.get("dryRunResult") or proposal.get("dry_run_result") or {}),
            requires_confirmation=bool(proposal.get("requiresConfirmation")),
            applyable=False,
        )
    except (TypeError, ValueError, ValidationError):
        return None
