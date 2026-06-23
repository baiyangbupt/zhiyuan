#!/usr/bin/env python3
"""Offline golden evaluator for TurnDecision -> ProposalCompiler contracts.

This is not runtime code. It validates 3.2.0 profile cases against deterministic
compiler invariants before any WebSocket or pending creation path is changed.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any


def _load_cases(path: str) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(cases, list):
        raise ValueError("case file must be a JSON array or {'cases': [...]}")
    return [case for case in cases if isinstance(case, dict)]


def _as_bool(data: dict[str, Any], key: str) -> bool:
    return bool(data.get(key))


def _planning_profile(case: dict[str, Any]) -> dict[str, Any]:
    value = case.get("planningStateProfile")
    return value if isinstance(value, dict) else {}


def _expected_turn(case: dict[str, Any]) -> dict[str, Any]:
    value = case.get("expectedTurnDecision")
    return value if isinstance(value, dict) else {}


def _expected_pending(case: dict[str, Any]) -> dict[str, Any]:
    value = case.get("expectedPending")
    return value if isinstance(value, dict) else {}


def _expected_proposal(case: dict[str, Any]) -> dict[str, Any]:
    value = case.get("expectedProposal")
    return value if isinstance(value, dict) else {}


def _expected_evidence_plan(case: dict[str, Any]) -> dict[str, Any]:
    value = case.get("expectedEvidencePlan")
    return value if isinstance(value, dict) else {}


def _reply_quality(case: dict[str, Any]) -> dict[str, Any]:
    value = case.get("replyQualityAssertions")
    return value if isinstance(value, dict) else {}


def _list_str(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value is None:
        return []
    return [str(value)]


def _unique_str(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _copy_payload_fields(source: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {key: source[key] for key in keys if key in source}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _is_pending_created(pending_type: str) -> bool:
    return pending_type not in {
        "none",
        "unchanged",
        "unchanged_existing_pending",
        "none_or_plan_mutation",
    }


def _workspace_refresh_targets(target_view: Any, expected_pending: dict[str, Any] | None = None) -> list[str]:
    configured = None
    if isinstance(expected_pending, dict) and "workspaceRefreshTargets" in expected_pending:
        configured = expected_pending.get("workspaceRefreshTargets")
    else:
        configured = target_view

    targets: list[str] = []
    for value in _list_str(configured):
        if value in {"ordered", "review", "candidate"} and value not in targets:
            targets.append(value)
    return targets


def _build_intent_payload(
    proposal: dict[str, Any],
    turn: dict[str, Any],
    output_type: str,
    pending_type: str,
) -> dict[str, Any] | None:
    payload = _copy_payload_fields(
        proposal,
        [
            "preferenceStrength",
            "preferenceScope",
            "negativeRegions",
            "admissionPath",
            "schools",
            "entityPolaritySpans",
        ],
    )
    if output_type != "intent_change" and pending_type != "intent_change" and not payload:
        return None
    payload.setdefault("scopeAnchor", str(turn.get("scopeAnchor") or "future_reference"))
    payload.setdefault("targetIssue", _list_str(turn.get("targetIssue")))
    return payload


def _build_execution_payload(
    *,
    pending_type: str,
    output_type: str,
    side_effect: str,
    scope_anchor: str,
    action_families: list[str],
    requires_confirmation: bool,
    target_view: Any,
    blocking_reasons: list[str],
) -> dict[str, Any] | None:
    if "plan_mutation_requires_formal_plan" in blocking_reasons:
        return None
    base = {
        "scopeAnchor": scope_anchor,
        "actionFamilies": action_families,
        "targetView": target_view,
        "requiresConfirmation": requires_confirmation,
    }
    if side_effect == "apply_pending_then_new_request":
        return {
            **base,
            "kind": "apply_existing_pending_then_followup",
            "stages": action_families,
            "newPendingType": pending_type,
            "applyExistingPending": True,
        }
    if pending_type == "plan_mutation":
        return {
            **base,
            "kind": "pending_plan_mutation",
            "applyPolicy": "java_proposal_after_confirm",
        }
    if pending_type == "intent_change":
        return {
            **base,
            "kind": "pending_intent_change",
            "applyPolicy": "intent_state_after_confirm",
        }
    if output_type == "apply_then_readonly":
        return {
            **base,
            "kind": "apply_existing_pending_then_readonly",
            "applyExistingPending": True,
            "newPendingType": "none",
        }
    if pending_type in {
        "none_or_plan_mutation",
        "plan_mutation_or_none",
        "plan_mutation_or_clarification",
    }:
        return {
            **base,
            "kind": "conditional_plan_mutation",
            "condition": "requires_supported_proposal_and_explicit_confirmation",
            "newPendingType": pending_type,
        }
    if pending_type == "unchanged_or_replace_after_user_choice":
        return {
            **base,
            "kind": "pending_conflict_resolution",
            "activePending": "unchanged",
            "requiresExplicitReplacementChoice": True,
            "newPendingType": "none_until_user_choice",
        }
    return None


def _build_display_payload(
    *,
    output_type: str,
    pending_type: str,
    target_view: Any,
    scope_anchor: str,
    action_families: list[str],
    target_issues: list[str],
    expected_pending: dict[str, Any],
    reply_quality: dict[str, Any],
    requires_confirmation: bool,
) -> dict[str, Any]:
    if output_type in {"clarification"} or pending_type == "unchanged_or_replace_after_user_choice":
        presentation = "clarification"
    elif output_type in {"provider_precheck", "latency_profile", "diagnostic"}:
        presentation = "diagnostic"
    elif pending_type in {"plan_mutation", "intent_change"} and requires_confirmation:
        presentation = "confirmation_card"
    elif "or_" in pending_type or "_or_" in pending_type:
        presentation = "conditional_options"
    else:
        presentation = "readonly_answer"
    pending_card_type = str(expected_pending.get("type") or "none")
    return {
        "presentation": presentation,
        "pendingCardType": pending_card_type,
        "targetView": target_view,
        "scopeAnchor": scope_anchor,
        "focus": target_issues,
        "actionFamilies": action_families,
        "mustMentionAny": _list_str(reply_quality.get("mustMentionAny")),
        "mustNotMention": _list_str(reply_quality.get("mustNotMention")),
    }


def _build_reply_plan(
    *,
    turn: dict[str, Any],
    evidence_plan: dict[str, Any],
    reply_quality: dict[str, Any],
    side_effect: str,
    pending_type: str,
    pending_exists: bool,
) -> dict[str, Any]:
    pending_reminder = (
        side_effect == "readonly_while_pending"
        or pending_type == "unchanged_existing_pending"
        or (pending_exists and pending_type == "unchanged_or_replace_after_user_choice")
    )
    return {
        "mode": _list_str(turn.get("replyMode")),
        "focus": _list_str(turn.get("targetIssue")),
        "mustAnswer": _list_str(reply_quality.get("mustAnswer")),
        "mustMentionAny": _list_str(reply_quality.get("mustMentionAny")),
        "mustNotMention": _list_str(reply_quality.get("mustNotMention")),
        "missingInfo": _list_str(turn.get("missingInfo")),
        "noResultReason": evidence_plan.get("noResultReason"),
        "pendingReminder": pending_reminder,
        "pendingConflict": pending_type == "unchanged_or_replace_after_user_choice",
    }


def _build_plan_action_dsl(
    proposal: dict[str, Any],
    *,
    scope_anchor: str,
    action_families: list[str],
    target_issues: list[str],
) -> dict[str, Any] | None:
    dsl = _as_dict(proposal.get("planActionDsl"))
    if not dsl and not any(
        family in {"pin_or_lock_unit", "move_ordered_unit", "move_unit"}
        for family in action_families
    ):
        return None
    result = {
        **dsl,
        "scopeAnchor": dsl.get("scopeAnchor") or scope_anchor,
        "actionFamilies": dsl.get("actionFamilies") or action_families,
        "targetIssue": dsl.get("targetIssue") or target_issues,
    }
    return result


def _build_evidence_contract(evidence_plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "requiredInputs": _list_str(evidence_plan.get("requiredInputs")),
        "steps": _list_str(evidence_plan.get("steps")),
        "toolBudget": _as_dict(evidence_plan.get("toolBudget")),
        "noResultReason": evidence_plan.get("noResultReason"),
    }


def _preference_values(preference_strength: dict[str, Any], key: str) -> list[str]:
    return _unique_str(_list_str(preference_strength.get(key)))


def _build_downstream_policy(
    *,
    proposal: dict[str, Any],
    turn: dict[str, Any],
) -> dict[str, Any] | None:
    preference_strength = _as_dict(proposal.get("preferenceStrength"))
    negative_regions = _unique_str(_list_str(proposal.get("negativeRegions")))
    admission_path = str(proposal.get("admissionPath") or "").strip()
    schools = _unique_str(_list_str(proposal.get("schools")))
    if not preference_strength and not negative_regions and not admission_path and not schools:
        return None

    scope = str(
        proposal.get("preferenceScope")
        or turn.get("scopeAnchor")
        or "future_reference"
    ).strip()
    only_keep = _preference_values(preference_strength, "only_keep")
    exclude_hard = _unique_str(_preference_values(preference_strength, "exclude_hard") + negative_regions)
    must_have = _preference_values(preference_strength, "must_have")
    primary = _preference_values(preference_strength, "primary")
    preferred = _preference_values(preference_strength, "preferred")
    acceptable = _preference_values(preference_strength, "acceptable")
    avoid_soft = _preference_values(preference_strength, "avoid_soft")

    replace_first: list[dict[str, Any]] = []
    if exclude_hard:
        replace_first.append(
            {
                "reason": "exclude_hard_violation",
                "values": exclude_hard,
                "policy": "remove_or_replace_before_ranking",
            }
        )
    if only_keep:
        replace_first.append(
            {
                "reason": "outside_only_keep_scope",
                "keepValues": only_keep,
                "policy": "remove_or_replace_out_of_scope_items",
            }
        )

    fill_priority: list[dict[str, Any]] = []
    if must_have:
        fill_priority.append(
            {
                "strength": "must_have",
                "values": must_have,
                "policy": "cover_at_least_one_without_dropping_unrelated_items",
            }
        )
    if primary:
        fill_priority.append(
            {
                "strength": "primary",
                "values": primary,
                "policy": "prefer_for_selection_and_replacement",
            }
        )
    if preferred:
        fill_priority.append(
            {
                "strength": "preferred",
                "values": preferred,
                "policy": "boost_after_primary",
            }
        )
    if acceptable:
        fill_priority.append(
            {
                "strength": "acceptable",
                "values": acceptable,
                "policy": "fallback_when_primary_or_preferred_insufficient_or_gradient_needed",
            }
        )

    protect_from_replacement: list[dict[str, Any]] = []
    for strength, values in (
        ("primary", primary),
        ("preferred", preferred),
        ("acceptable", acceptable),
    ):
        if values:
            protect_from_replacement.append(
                {
                    "strength": strength,
                    "values": values,
                    "policy": "do_not_replace_for_weaker_preference_without_conflict",
                }
            )

    return {
        "scope": scope or "future_reference",
        "admissionPath": admission_path or None,
        "pathEntities": {"schools": schools} if schools else {},
        "candidateSelection": {
            "hardFilterBeforeRanking": True,
            "onlyKeep": only_keep,
            "hardExclude": exclude_hard,
            "mustCover": must_have,
            "rankBoost": [
                {"strength": "primary", "values": primary, "weight": 3},
                {"strength": "preferred", "values": preferred, "weight": 2},
                {"strength": "acceptable", "values": acceptable, "weight": 1},
            ],
            "softAvoid": avoid_soft,
        },
        "replacementPolicy": {
            "replaceFirst": replace_first,
            "fillPriority": fill_priority,
            "protectFromReplacement": protect_from_replacement,
        },
    }


def _candidate_id(candidate: dict[str, Any], index: int) -> str:
    return str(candidate.get("id") or candidate.get("candidateId") or f"candidate-{index + 1}").strip()


def _candidate_type(candidate: dict[str, Any]) -> str:
    return str(candidate.get("type") or "").strip()


def _candidate_execution_authority(candidate: dict[str, Any]) -> str:
    return str(candidate.get("executionAuthority") or "").strip()


def _candidate_creates_pending(candidate: dict[str, Any]) -> bool:
    if "createsPending" in candidate:
        return bool(candidate.get("createsPending"))
    return _candidate_type(candidate) in {
        "intent_update_candidate",
        "java_user_goal_request_candidate",
        "java_fix_proposal_reference",
        "plan_action_dsl_candidate",
    }


def _proposal_candidates(proposal: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = _as_list(proposal.get("proposalCandidates"))
    result: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            continue
        result.append(
            {
                **candidate,
                "id": _candidate_id(candidate, index),
                "type": _candidate_type(candidate),
                "executionAuthority": _candidate_execution_authority(candidate),
            }
        )
    return result


def _java_fix_candidate_blocking_reasons(candidate: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    status = str(candidate.get("status") or candidate.get("proposalStatus") or "").strip()
    ready = bool(candidate.get("ready")) or status in {"ready", "appliable"}
    if not ready:
        reasons.append("java_fix_proposal_not_ready")
    actions = candidate.get("actions")
    has_actions = bool(candidate.get("hasActions")) or (isinstance(actions, list) and bool(actions))
    if not has_actions:
        reasons.append("java_fix_proposal_ready_without_actions")
    source_version_guard = _as_int(
        candidate.get("sourceVersionGuard") or candidate.get("source_version_guard")
    )
    if source_version_guard <= 0:
        reasons.append("java_fix_proposal_missing_source_version_guard")
    dry_run = _as_dict(candidate.get("dryRunObservation") or candidate.get("dryRun"))
    if not dry_run:
        reasons.append("java_fix_proposal_missing_dry_run_observation")
    for gap in _list_str(dry_run.get("contractGaps")):
        reasons.append(f"java_fix_proposal_contract_gap:{gap}")
    return reasons


def _arbitrate_proposal_candidates(
    candidates: list[dict[str, Any]],
    *,
    pending_exists: bool,
    side_effect: str,
    requested_pending_type: str,
) -> dict[str, Any]:
    by_type: dict[str, int] = {}
    for candidate in candidates:
        candidate_type = _candidate_type(candidate) or "unknown"
        by_type[candidate_type] = by_type.get(candidate_type, 0) + 1

    blocking_reasons: list[str] = []
    blocked_candidate_ids: list[str] = []
    pending_candidates = [candidate for candidate in candidates if _candidate_creates_pending(candidate)]
    readonly_candidates = [candidate for candidate in candidates if not _candidate_creates_pending(candidate)]
    rank_only_candidates = [
        candidate
        for candidate in candidates
        if _candidate_type(candidate) in {"rank_only_policy_candidate", "soft_avoid_rank_only_candidate"}
    ]

    for candidate in pending_candidates:
        if _candidate_type(candidate) == "java_fix_proposal_reference":
            java_reasons = _java_fix_candidate_blocking_reasons(candidate)
            if java_reasons:
                blocked_candidate_ids.append(str(candidate.get("id")))
                blocking_reasons.extend(java_reasons)

    if pending_exists and pending_candidates and side_effect not in {
        "apply_pending_then_new_request",
        "apply_pending_then_readonly",
        "conflict_with_existing_pending",
    }:
        blocking_reasons.append("active_pending_blocks_new_mutation_candidate")
        blocked_candidate_ids.extend(str(candidate.get("id")) for candidate in pending_candidates)

    if rank_only_candidates and requested_pending_type == "plan_mutation" and not pending_candidates:
        blocking_reasons.append("rank_only_policy_cannot_create_mutation")
        blocked_candidate_ids.extend(str(candidate.get("id")) for candidate in rank_only_candidates)

    blocked_set = {candidate_id for candidate_id in blocked_candidate_ids if candidate_id}
    valid_pending_candidates = [
        candidate
        for candidate in pending_candidates
        if str(candidate.get("id") or "") not in blocked_set
    ]

    decision = "none"
    selected_candidate_ids: list[str] = []
    merged_candidate_ids: list[str] = []
    if blocking_reasons and not valid_pending_candidates:
        decision = "block"
    elif len(valid_pending_candidates) == 1:
        decision = "select"
        selected_candidate_ids = [str(valid_pending_candidates[0].get("id"))]
    elif len(valid_pending_candidates) > 1:
        merge_groups = {
            str(candidate.get("mergeGroup") or "").strip()
            for candidate in valid_pending_candidates
        }
        merge_groups.discard("")
        if len(merge_groups) == 1 and all(candidate.get("mergeAllowed", True) for candidate in valid_pending_candidates):
            decision = "merge"
            merged_candidate_ids = [str(candidate.get("id")) for candidate in valid_pending_candidates]
            selected_candidate_ids = list(merged_candidate_ids)
        else:
            decision = "block"
            blocking_reasons.append("multiple_high_side_effect_candidates_require_arbitration")
            blocked_candidate_ids.extend(str(candidate.get("id")) for candidate in valid_pending_candidates)
    elif readonly_candidates:
        decision = "readonly"

    return {
        "total": len(candidates),
        "byType": by_type,
        "decision": decision,
        "selectedCandidateIds": _unique_str(selected_candidate_ids),
        "mergedCandidateIds": _unique_str(merged_candidate_ids),
        "blockedCandidateIds": _unique_str(blocked_candidate_ids),
        "blockingReasons": _unique_str(blocking_reasons),
    }


def _validate_preference_strength(
    preference_strength: dict[str, Any],
    blocking_reasons: list[str],
) -> None:
    if not preference_strength:
        return
    supported = {"primary", "acceptable", "preferred", "avoid_soft", "exclude_hard", "must_have", "only_keep"}
    unknown = sorted(set(preference_strength) - supported)
    if unknown:
        blocking_reasons.append("unsupported_preference_strength:" + ",".join(unknown))
    for key, value in preference_strength.items():
        if key in supported and not isinstance(value, list):
            blocking_reasons.append(f"preference_strength_{key}_must_be_list")


def _validate_entity_polarity_spans(
    spans: list[Any],
    blocking_reasons: list[str],
) -> None:
    if not spans:
        return
    supported = {"positive", "negative"}
    for index, span in enumerate(spans):
        if not isinstance(span, dict):
            blocking_reasons.append(f"entity_polarity_span_{index}_must_be_object")
            continue
        if not span.get("entity"):
            blocking_reasons.append(f"entity_polarity_span_{index}_missing_entity")
        polarity = str(span.get("polarity") or "")
        if polarity not in supported:
            blocking_reasons.append(f"entity_polarity_span_{index}_invalid_polarity")


def _validate_plan_action_dsl(
    dsl: dict[str, Any] | None,
    blocking_reasons: list[str],
) -> None:
    if not dsl:
        return
    if dsl.get("action") == "pin_or_lock_unit":
        if not dsl.get("selectors"):
            blocking_reasons.append("pin_or_lock_requires_selectors")
        if dsl.get("scopeAnchor") != "current_plan":
            blocking_reasons.append("pin_or_lock_scope_must_be_current_plan")
    if dsl.get("ordinalScope") == "within_tier" and not dsl.get("targetTier"):
        blocking_reasons.append("tier_local_ordinal_requires_target_tier")
    if dsl.get("action") in {"move_ordered_unit", "move_unit"} and dsl.get("scopeAnchor") == "current_plan.tier_segment":
        if dsl.get("ordinalScope") != "within_tier":
            blocking_reasons.append("tier_segment_move_requires_within_tier_ordinal")


def _validate_tool_budget(
    evidence_contract: dict[str, Any],
    blocking_reasons: list[str],
) -> None:
    budget = _as_dict(evidence_contract.get("toolBudget"))
    if not budget:
        return
    max_tool_calls = budget.get("maxToolCalls")
    if max_tool_calls is not None and (not isinstance(max_tool_calls, int) or max_tool_calls < 0):
        blocking_reasons.append("tool_budget_max_tool_calls_invalid")
    if len(_list_str(evidence_contract.get("steps"))) > 1 and "batchPreferred" not in budget:
        blocking_reasons.append("multi_step_evidence_requires_batch_preference")


def _compile_case(case: dict[str, Any]) -> dict[str, Any]:
    planning = _planning_profile(case)
    turn = _expected_turn(case)
    evidence_plan = _expected_evidence_plan(case)
    proposal = _expected_proposal(case)
    expected_pending = _expected_pending(case)
    reply_quality = _reply_quality(case)
    side_effect = str(turn.get("sideEffect") or "")
    task_layer = str(turn.get("taskLayer") or "")
    scope_anchor = str(turn.get("scopeAnchor") or "")
    pending_exists = _as_bool(planning, "pendingExists")
    formal_plan_present = _as_bool(planning, "formalPlanPresent")
    missing_info = [str(item) for item in turn.get("missingInfo") or []]
    action_families = [str(item) for item in proposal.get("actionFamilies") or []]
    target_issues = _list_str(turn.get("targetIssue"))
    target_view = expected_pending.get("targetView")
    evidence_contract = _build_evidence_contract(evidence_plan)

    blocking_reasons: list[str] = []
    output_type = str(proposal.get("type") or "readonly")
    pending_type = str(proposal.get("pendingType") or "none")
    requires_confirmation = bool(proposal.get("requiresConfirmation"))
    plan_action_dsl = _build_plan_action_dsl(
        proposal,
        scope_anchor=scope_anchor,
        action_families=action_families,
        target_issues=target_issues,
    )
    proposal_candidates = _proposal_candidates(proposal)
    candidate_arbitration = _arbitrate_proposal_candidates(
        proposal_candidates,
        pending_exists=pending_exists,
        side_effect=side_effect,
        requested_pending_type=pending_type,
    )
    blocking_reasons.extend(_list_str(candidate_arbitration.get("blockingReasons")))

    _validate_preference_strength(_as_dict(proposal.get("preferenceStrength")), blocking_reasons)
    _validate_entity_polarity_spans(_as_list(proposal.get("entityPolaritySpans")), blocking_reasons)
    _validate_plan_action_dsl(plan_action_dsl, blocking_reasons)
    _validate_tool_budget(evidence_contract, blocking_reasons)

    if side_effect in {"readonly", "readonly_while_pending", "needs_plan_first", "clarification"}:
        requires_confirmation = False
        if pending_type not in {"unchanged_existing_pending", "none"}:
            blocking_reasons.append("readonly_cannot_create_new_pending")
            pending_type = "unchanged_existing_pending" if pending_exists else "none"
        output_type = "readonly" if side_effect != "clarification" else "clarification"

    if side_effect == "readonly_while_pending":
        if not pending_exists:
            blocking_reasons.append("readonly_while_pending_requires_active_pending")
        pending_type = "unchanged_existing_pending"
        requires_confirmation = False

    if side_effect in {"apply_pending_then_new_request", "apply_pending_then_readonly"}:
        if not pending_exists:
            blocking_reasons.append("apply_pending_requires_active_pending")
        if side_effect == "apply_pending_then_new_request" and output_type != "apply_then_readonly":
            output_type = "composite"

    if task_layer == "pending" and side_effect == "readonly":
        if pending_exists:
            blocking_reasons.append("pending_readonly_unexpected_with_active_pending")
        pending_type = "none"
        requires_confirmation = False

    if side_effect in {"plan_preview", "composite_pending"} or pending_type == "plan_mutation":
        if not formal_plan_present and "generate_plan" not in action_families:
            blocking_reasons.append("plan_mutation_requires_formal_plan")
            pending_type = "none"
            requires_confirmation = False
            output_type = "clarification"

    if side_effect == "needs_plan_first":
        if formal_plan_present:
            blocking_reasons.append("needs_plan_first_but_formal_plan_present")
        pending_type = "none"
        requires_confirmation = False
        output_type = "readonly"
        if "formal_plan" not in missing_info:
            blocking_reasons.append("needs_plan_first_requires_formal_plan_missing_info")

    if side_effect == "conflict_with_existing_pending":
        if not pending_exists:
            blocking_reasons.append("pending_conflict_requires_active_pending")
        pending_type = "unchanged_or_replace_after_user_choice"
        requires_confirmation = False
        output_type = "clarification"

    if side_effect == "intent_pending":
        pending_type = "intent_change"
        requires_confirmation = True
        output_type = "intent_change"

    has_downstream_contract_gap = any(
        str(reason).startswith("java_fix_proposal_")
        or str(reason) == "rank_only_policy_cannot_create_mutation"
        for reason in blocking_reasons
    )
    if proposal_candidates and candidate_arbitration.get("decision") == "block":
        pending_type = "none"
        requires_confirmation = False
        output_type = "diagnostic" if has_downstream_contract_gap else "clarification"

    if proposal_candidates and has_downstream_contract_gap:
        if pending_type == "plan_mutation":
            pending_type = "none"
            requires_confirmation = False
            output_type = "diagnostic"

    if "negative_only" in case.get("tags", []) and side_effect == "intent_pending":
        if pending_type != "intent_change":
            blocking_reasons.append("negative_only_should_compile_to_intent_change")

    expected_required = bool(expected_pending.get("required"))
    actual_pending_created = _is_pending_created(pending_type)
    pending_requirement_ok = (actual_pending_created is True) if expected_required else True
    if expected_required and not actual_pending_created:
        blocking_reasons.append("expected_pending_not_created")
    intent_payload = _build_intent_payload(
        proposal=proposal,
        turn=turn,
        output_type=output_type,
        pending_type=pending_type,
    )
    execution_payload = _build_execution_payload(
        pending_type=pending_type,
        output_type=output_type,
        side_effect=side_effect,
        scope_anchor=scope_anchor,
        action_families=action_families,
        requires_confirmation=requires_confirmation,
        target_view=target_view,
        blocking_reasons=blocking_reasons,
    )
    display_payload = _build_display_payload(
        output_type=output_type,
        pending_type=pending_type,
        target_view=target_view,
        scope_anchor=scope_anchor,
        action_families=action_families,
        target_issues=target_issues,
        expected_pending=expected_pending,
        reply_quality=reply_quality,
        requires_confirmation=requires_confirmation,
    )
    reply_plan = _build_reply_plan(
        turn=turn,
        evidence_plan=evidence_plan,
        reply_quality=reply_quality,
        side_effect=side_effect,
        pending_type=pending_type,
        pending_exists=pending_exists,
    )
    downstream_policy = _build_downstream_policy(proposal=proposal, turn=turn)

    return {
        "caseId": case.get("caseId"),
        "taskLayer": task_layer,
        "sideEffect": side_effect,
        "scopeAnchor": scope_anchor,
        "outputType": output_type,
        "pendingType": pending_type,
        "requiresConfirmation": requires_confirmation,
        "executionPayload": execution_payload,
        "intentPayload": intent_payload,
        "displayPayload": display_payload,
        "replyPlan": reply_plan,
        "evidenceContract": evidence_contract,
        "planActionDsl": plan_action_dsl,
        "downstreamPolicy": downstream_policy,
        "proposalCandidates": proposal_candidates,
        "candidateArbitration": candidate_arbitration,
        "workspaceRefreshTargets": _workspace_refresh_targets(target_view, expected_pending),
        "blockingReasons": blocking_reasons,
        "pendingRequirementOk": pending_requirement_ok,
    }


def _evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    compiled = _compile_case(case)
    failures: list[dict[str, Any]] = []
    forbidden = set(str(item) for item in case.get("forbiddenDecisions") or [])
    if "no_pending_after_preview" in forbidden and compiled["sideEffect"] == "plan_preview":
        if compiled["pendingType"] == "none":
            failures.append({"field": "pendingType", "type": "forbidden_no_pending_after_preview"})
    if "plan_mutation_without_plan" in forbidden and "plan_mutation_requires_formal_plan" not in compiled["blockingReasons"]:
        planning = _planning_profile(case)
        if not bool(planning.get("formalPlanPresent")) and compiled["pendingType"] == "plan_mutation":
            failures.append({"field": "pendingType", "type": "plan_mutation_without_plan"})
    if not compiled["pendingRequirementOk"]:
        failures.append({"field": "pendingType", "type": "expected_pending_not_created"})
    return {
        **compiled,
        "passed": not failures,
        "failures": failures,
    }


def _bump_group(group: dict[str, dict[str, int]], key: str, passed: bool) -> None:
    group.setdefault(key, {"total": 0, "passed": 0, "failed": 0})
    group[key]["total"] += 1
    group[key]["passed" if passed else "failed"] += 1


def build_report(cases: list[dict[str, Any]]) -> dict[str, Any]:
    records = [_evaluate_case(case) for case in cases]
    by_side_effect: dict[str, dict[str, int]] = {}
    by_output_type: dict[str, dict[str, int]] = {}
    by_pending_type: dict[str, dict[str, int]] = {}
    blocking_reasons: dict[str, int] = {}
    for record in records:
        passed = bool(record["passed"])
        _bump_group(by_side_effect, str(record.get("sideEffect") or "unknown"), passed)
        _bump_group(by_output_type, str(record.get("outputType") or "unknown"), passed)
        _bump_group(by_pending_type, str(record.get("pendingType") or "unknown"), passed)
        for reason in record.get("blockingReasons") or []:
            blocking_reasons[reason] = blocking_reasons.get(reason, 0) + 1
    total = len(records)
    passed = sum(1 for record in records if record["passed"])
    return {
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "passRate": round(passed / total, 4) if total else None,
            "bySideEffect": by_side_effect,
            "byOutputType": by_output_type,
            "byPendingType": by_pending_type,
            "blockingReasons": blocking_reasons,
        },
        "records": records,
        "failureExamples": [record for record in records if not record["passed"]][:20],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate offline proposal compiler golden cases.")
    parser.add_argument("--cases", required=True, help="profile golden case JSON")
    parser.add_argument("--output", help="write JSON report")
    args = parser.parse_args()
    report = build_report(_load_cases(args.cases))
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
