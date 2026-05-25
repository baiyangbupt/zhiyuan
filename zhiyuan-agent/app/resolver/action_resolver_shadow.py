"""ActionResolver shadow helpers.

The shadow path compares deterministic typed-action resolution with the
currently active routing decision. It never changes execution behavior.
"""

from __future__ import annotations

from typing import Any

from app.agent.context import PlanningSummary
from app.models.conversation_phase import ConversationPhase
from app.models.intent_frame import IntentFrame, TargetSpec
from app.resolver.action_resolver import ActionResolver
from app.resolver.plan_fast_router import PlanFastRouteDecision
from app.tools.plan_orchestration_models import PlanContextInputs


def plan_context_inputs_from_summary(summary: PlanningSummary | None) -> PlanContextInputs:
    """Build minimal resolver context from the lightweight planning summary."""
    if summary is None:
        return PlanContextInputs()
    return PlanContextInputs(
        phase=summary.phase,
        target_count=summary.ordered_target_total
        or summary.draft_target_total
        or summary.candidate_target_total,
        draft_count=summary.draft_total,
        ordered_count=summary.ordered_total,
        risk_count=summary.review_risk_count,
        warn_count=summary.review_warn_count,
        positive_majors=list(summary.positive_majors or []),
        positive_regions=list(summary.positive_regions or []),
        summary=(
            f"phase={summary.phase}; "
            f"ordered={summary.ordered_total}/{summary.ordered_target_total}; "
            f"draft={summary.draft_total}/{summary.draft_target_total}"
        ),
    )


def intent_frame_from_plan_fast_decision(
    text: str,
    decision: PlanFastRouteDecision,
) -> IntentFrame | None:
    """Translate a high-confidence fast-route decision into a typed frame."""
    raw = str(text or decision.user_goal or "").strip()
    action_family = decision.action_family
    target = TargetSpec()
    verb = "query"

    if action_family == "query_state":
        verb = "query"
    elif action_family == "review_plan":
        verb = "review"
    elif action_family == "sort_ordered_plan":
        verb = "sort"
    elif action_family == "move_unit":
        verb = "move"
        target.volunteer_refs = list(decision.volunteer_ids or [])
        target.position = decision.target_position
    elif action_family == "remove_units":
        verb = "remove"
        target.volunteer_refs = list(decision.volunteer_ids or [])
    elif action_family == "add_units":
        verb = "add"
        target.volunteer_refs = list(decision.volunteer_ids or [])
    elif action_family == "move_ordered_unit":
        verb = "move"
        target.unit_refs = _ordered_unit_refs(decision)
        target.position = decision.target_position
    elif action_family == "remove_ordered_unit":
        verb = "remove"
        target.unit_refs = _ordered_unit_refs(decision)
    else:
        return None

    return IntentFrame(
        task_layer="plan",
        topic="plan",
        verb=verb,  # type: ignore[arg-type]
        target=target,
        raw_utterance=raw,
    )


def action_resolver_shadow_from_plan_fast_decision(
    *,
    text: str,
    decision: PlanFastRouteDecision,
    planning_summary: PlanningSummary | None,
    phase: ConversationPhase | None = None,
) -> dict[str, Any] | None:
    """Resolve a plan fast-route decision through ActionResolver for logging."""
    frame = intent_frame_from_plan_fast_decision(text, decision)
    if frame is None:
        return None
    context = plan_context_inputs_from_summary(planning_summary)
    resolution = ActionResolver().resolve(frame, context, phase)
    action_family_match = resolution.action_family == decision.action_family
    return {
        "source": "plan_fast_route",
        "actualActionFamily": decision.action_family,
        "shadowActionFamily": resolution.action_family,
        "shadowStage": resolution.stage,
        "actionFamilyMatch": action_family_match,
        "stage": resolution.stage,
        "requiresConfirmation": resolution.requires_confirmation,
        "missingInputs": list(resolution.missing_inputs or []),
        "blockedReason": resolution.blocked_reason,
        "normalizationApplied": resolution.normalization_applied,
    }


def _ordered_unit_refs(decision: PlanFastRouteDecision) -> list[str]:
    if decision.unit_ids:
        return list(decision.unit_ids)
    if decision.source_position is not None:
        return [f"第{decision.source_position}个专业组"]
    return []
