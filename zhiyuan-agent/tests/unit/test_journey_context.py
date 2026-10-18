from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.gateway.contracts import ConversationTurnSnapshot
from app.gateway.journey import (
    PLANNED_ACTIONS,
    blocked_actions,
    context_text,
    derive_state_phase,
    derive_task_intent,
    from_snapshot,
    turn_journey_result,
)


def journey_block(**overrides):
    block = {
        "hasProfile": True,
        "profileMissing": [],
        "hasCandidates": True,
        "candidateEntryCount": 12,
        "candidateSourceVersion": 5,
        "hasPlan": True,
        "planEntryCount": 45,
        "orderedEntryCount": 45,
        "planInterpretable": True,
        "selectionTargetCount": 45,
        "selectionCurrentCount": 45,
        "planVersion": 87,
        "planContentDigest": "digest-v1",
        "candidateFreshness": "fresh",
        "planFreshness": "fresh",
        "planAdjustmentStale": False,
        "reviewFreshness": "fresh",
        "refreshRequirement": "none",
        "reviewSourceVersion": 86,
        "reviewStale": False,
        "tierQuotaGoal": False,
        "stale": False,
        "staleReasonCode": None,
        "staleMessage": None,
        "pendingStatus": None,
    }
    block.update(overrides)
    return block


def snapshot(block=None, *, version=87, stage="plan_review"):
    return ConversationTurnSnapshot(
        snapshotVersion=version,
        sessionId="s1",
        planningStage=stage,
        journey=block,
    )


def output(**overrides):
    values = {
        "response_type": "text",
        "proposal_request": None,
        "score_update_request": None,
        "career_update_request": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_state_phase_truth_table():
    assert derive_state_phase(has_profile=False, has_candidates=True, has_plan=True) == "discover"
    assert derive_state_phase(has_profile=True, has_candidates=False, has_plan=False) == "explore"
    assert derive_state_phase(has_profile=True, has_candidates=True, has_plan=False) == "candidates"
    assert derive_state_phase(has_profile=True, has_candidates=False, has_plan=True) == "build"
    assert derive_state_phase(has_profile=True, has_candidates=True, has_plan=True) == "build"


def test_missing_journey_is_tolerated() -> None:
    assert from_snapshot(snapshot(None)) is None
    assert turn_journey_result(snapshot(None), output(), []) is None


def test_working_only_plan_is_not_interpretable_and_recommends_fill() -> None:
    context = from_snapshot(
        snapshot(journey_block(planInterpretable=False, orderedEntryCount=0, hasPlan=True))
    )

    assert context is not None
    assert context.state_phase == "build"
    assert "interpret_admission" not in context.available_actions
    assert "review_plan" not in context.available_actions
    assert {item.action for item in context.blocked_actions} >= {
        "interpret_admission",
        "review_plan",
    }
    assert context.recommended_next == "fill_to_count"


def test_score_update_freshness_blocks_add_and_fill_but_keeps_interpret() -> None:
    context = from_snapshot(
        snapshot(
            journey_block(
                candidateFreshness="stale",
                planFreshness="stale",
                refreshRequirement="candidates",
                stale=True,
                staleReasonCode="score_detail_updated",
            )
        )
    )

    assert context is not None
    assert context.recommended_next == "recommend_candidates"
    assert "add_units" not in context.available_actions
    assert "add_units_by_scope" not in context.available_actions
    assert "fill_to_count" not in context.available_actions
    assert "interpret_admission" in context.available_actions
    reasons = {item.action: item.reason_code for item in context.blocked_actions}
    assert reasons["add_units"] == "candidate_stale"
    assert reasons["fill_to_count"] == "candidate_stale"


def test_plan_stale_keeps_fill_as_recompute_entry() -> None:
    context = from_snapshot(
        snapshot(journey_block(planFreshness="stale", refreshRequirement="plan"))
    )

    assert context is not None
    assert context.recommended_next == "fill_to_count"
    assert "fill_to_count" in context.available_actions
    assert "add_units" not in context.available_actions
    reasons = {item.action: item.reason_code for item in context.blocked_actions}
    assert reasons["add_units"] == "plan_stale"


def test_tier_quota_blocks_add_but_not_fill() -> None:
    context = from_snapshot(
        snapshot(
            journey_block(
                hasPlan=False,
                planEntryCount=0,
                orderedEntryCount=0,
                planInterpretable=False,
                planFreshness="absent",
                tierQuotaGoal=True,
                refreshRequirement="plan",
            )
        )
    )

    assert context is not None
    assert context.recommended_next == "fill_to_count"
    assert "fill_to_count" in context.available_actions
    assert "add_units" not in context.available_actions


def test_target_count_mismatch_blocks_add_units_and_scope_add() -> None:
    context = from_snapshot(
        snapshot(journey_block(selectionTargetCount=45, selectionCurrentCount=43))
    )

    assert context is not None
    reasons = {item.action: item.reason_code for item in context.blocked_actions}
    assert reasons["add_units"] == "target_count_mismatch"
    assert reasons["add_units_by_scope"] == "target_count_mismatch"
    assert "fill_to_count" in context.available_actions


def test_applying_blocks_writes_and_recommends_wait() -> None:
    context = from_snapshot(snapshot(journey_block(pendingStatus="applying")))

    assert context is not None
    assert context.recommended_next == "wait"
    for action in (
        "add_units",
        "add_units_by_scope",
        "fill_to_count",
        "update_score",
        "confirm",
        "cancel",
    ):
        assert action not in context.available_actions
    assert {item.action for item in context.blocked_actions} >= {
        "add_units",
        "fill_to_count",
        "confirm",
        "cancel",
    }


def test_active_pending_recommends_confirm() -> None:
    context = from_snapshot(snapshot(journey_block(pendingStatus="active")))

    assert context is not None
    assert context.recommended_next == "confirm"
    assert "confirm" in context.available_actions
    assert "cancel" in context.available_actions


def test_manual_review_digest_skips_repeat_review_recommendation() -> None:
    block = journey_block(
        reviewFreshness="stale",
        refreshRequirement="review",
        planContentDigest="digest-v1",
    )
    unseen = from_snapshot(snapshot(block))
    seen = from_snapshot(snapshot(block), manual_review_digest="digest-v1")

    assert unseen is not None and unseen.recommended_next == "review_plan"
    assert seen is not None and seen.manual_review_current is True
    assert seen.recommended_next == "interpret_admission"

    changed = from_snapshot(
        snapshot(journey_block(reviewFreshness="stale", refreshRequirement="review",
                               planContentDigest="digest-v2")),
        manual_review_digest="digest-v1",
    )
    assert changed is not None and changed.recommended_next == "review_plan"


def test_open_task_takes_precedence_over_default_recommendation() -> None:
    context = from_snapshot(snapshot(journey_block()), has_open_task=True)

    assert context is not None
    assert context.recommended_next == "continue_task"


def test_freshness_precedes_open_task() -> None:
    context = from_snapshot(
        snapshot(
            journey_block(
                candidateFreshness="stale",
                refreshRequirement="candidates",
            )
        ),
        has_open_task=True,
    )

    assert context is not None
    assert context.recommended_next == "recommend_candidates"


def test_task_intent_mapping_uses_tool_names_and_write_drafts() -> None:
    assert derive_task_intent(
        output(), ["planning.interpret_admission"], "build"
    ) == "interpret"
    assert derive_task_intent(output(response_type="review"), [], "build") == "review"
    assert derive_task_intent(output(response_type="fact"), [], "build") == "verify"
    assert derive_task_intent(
        output(), ["recommendation.compare_candidates"], "build"
    ) == "verify"
    assert derive_task_intent(
        output(proposal_request=object()), [], "build"
    ) == "adjust"
    assert derive_task_intent(
        output(proposal_request=object()), [], "candidates"
    ) is None
    assert derive_task_intent(
        output(), ["planning.interpret_admission", "recommendation.compare_candidates"], "build"
    ) == "interpret"


def test_turn_journey_result_records_phase_without_full_block() -> None:
    result = turn_journey_result(
        snapshot(journey_block()), output(response_type="review"), []
    )

    assert result == {"statePhase": "build", "taskIntent": "review", "phase": "review"}


def test_context_text_prioritizes_component_freshness_over_compat_stale_flags() -> None:
    context = from_snapshot(
        snapshot(
            journey_block(
                planAdjustmentStale=True,
                reviewFreshness="fresh",
                stale=True,
                staleReasonCode="plan_structure_changed",
                staleMessage="方案内容或顺序已调整，需要重新审查。",
            )
        )
    )
    assert context is not None

    text = context_text(context)

    assert "以本块为准" in text
    assert "结构调整不等于规则审查过期" in text
    assert "规则审查=fresh" in text


def test_context_text_is_bounded_and_carries_plan_version() -> None:
    context = from_snapshot(snapshot(journey_block()))
    assert context is not None

    text = context_text(context)

    assert "方案版本：87" in text
    assert "planning.interpret_admission 时 planVersion 必须用 87" in text
    assert "candidateSourceVersion" not in text
    assert "【当前旅程】" in text
    for action in PLANNED_ACTIONS:
        assert action in text


@pytest.mark.parametrize(
    "block",
    [
        journey_block(),
        journey_block(hasPlan=False, planInterpretable=False),
        journey_block(hasCandidates=False, candidateFreshness="absent"),
        journey_block(candidateFreshness="stale"),
        journey_block(tierQuotaGoal=True),
        journey_block(pendingStatus="applying"),
    ],
)
def test_planned_actions_never_enter_available(block) -> None:
    context = from_snapshot(snapshot(block))
    assert context is not None
    assert not (set(context.available_actions) & PLANNED_ACTIONS)
    assert context.recommended_next not in PLANNED_ACTIONS


def test_blocked_actions_are_first_hit_only() -> None:
    context = from_snapshot(
        snapshot(
            journey_block(
                pendingStatus="applying",
                candidateFreshness="stale",
                planFreshness="stale",
                tierQuotaGoal=True,
            )
        )
    )

    assert context is not None
    entries = [item for item in blocked_actions(context) if item.action == "add_units"]
    assert len(entries) == 1
    assert entries[0].reason_code == "pending_applying"
