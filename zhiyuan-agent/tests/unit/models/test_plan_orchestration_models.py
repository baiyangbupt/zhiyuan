"""Plan orchestration model tests."""

import pytest
from pydantic import ValidationError

from app.tools.plan_orchestration_models import (
    CompositePlanProposal,
    LinkedRepairAction,
    LinkedRepairProposal,
    PlanActionPlan,
    PlanAtomicAction,
    PlanDecisionReference,
    PlanEntityResolution,
    PlanGoal,
    normalize_plan_action_payload,
)


def test_plan_action_plan_defaults_keep_existing_single_action_shape():
    plan = PlanActionPlan(
        stage="preview",
        action_family="remove_units",
        user_goal="删掉法学",
        atomic_actions=[
            PlanAtomicAction(
                action_type="remove_units",
                source_major_names=["法学"],
            )
        ],
    )

    assert plan.composite_proposal is None
    assert plan.atomic_actions[0].source_major_names == ["法学"]


def test_plan_action_plan_keeps_compound_goal_inside_composite_proposal():
    goal = PlanGoal(
        goal_type="only_keep_scope",
        user_original_text="只保留临床医学，其他专业先不要",
        target_scopes=[{"entityType": "major", "name": "临床医学", "level": "level3"}],
        confidence="high",
    )
    proposal = CompositePlanProposal(
        goal=goal,
        intent_updates=[
            {
                "intentMode": "constraint",
                "constraintIntentType": "only_keep",
                "major_intents": {"level3": ["临床医学"]},
            }
        ],
        plan_actions=[
            PlanAtomicAction(
                action_type="remove_units",
                filters={"exclude_major_keyword": "临床医学"},
                reason="移出不在保留范围内的专业",
            )
        ],
        feasibility="ready",
    )
    plan = PlanActionPlan(
        stage="preview",
        action_family="remove_units",
        user_goal=goal.user_original_text,
        composite_proposal=proposal,
    )

    assert plan.composite_proposal is not None
    assert plan.composite_proposal.goal is not None
    assert plan.composite_proposal.goal.goal_type == "only_keep_scope"
    assert plan.composite_proposal.intent_updates[0]["constraintIntentType"] == "only_keep"
    assert plan.composite_proposal.plan_actions[0].action_type == "remove_units"
    assert plan.model_dump()["composite_proposal"]["feasibility"] == "ready"


def test_composite_plan_proposal_groups_goal_intent_and_actions():
    goal = PlanGoal(
        goal_type="must_include_scope",
        target_scopes=[{"entity_type": "major", "values": ["临床医学"]}],
    )
    proposal = CompositePlanProposal(
        source_version=12,
        goal=goal,
        intent_updates=[
            {
                "intentMode": "constraint",
                "constraintIntentType": "must_have",
                "targetScopes": goal.target_scopes,
            }
        ],
        plan_actions=[
            PlanAtomicAction(
                action_type="add_units",
                filters={"major_keyword": "临床医学"},
            )
        ],
        decision_references=[
            PlanDecisionReference(
                source="explicit_user_goal",
                dimension="target_scope",
                label="用户明确想保留或补入的范围",
                value={"entity_type": "major", "values": ["临床医学"]},
                weight_hint="hard",
                applies_to=["临床医学"],
            ),
            PlanDecisionReference(
                source="system_recommendation",
                dimension="priority_metrics",
                label="系统用于比较志愿优先级的参考指标",
                value=["推荐系数", "录取率"],
            ),
        ],
        feasibility="ready",
        impact_summary=["会先补入临床医学方向的候选，确认前不会改方案。"],
        requires_confirmation=True,
    )

    assert proposal.goal is not None
    assert proposal.goal.goal_type == "must_include_scope"
    assert proposal.has_plan_mutation is True
    assert proposal.requires_confirmation is True
    assert proposal.source_version == 12
    assert proposal.decision_references[0].weight_hint == "hard"
    assert proposal.decision_references[1].source == "system_recommendation"


def test_linked_repair_proposal_normalizes_strategy_and_apply_policy():
    proposal = LinkedRepairProposal(
        proposal_id="fp-1",
        strategy="rebalance_protect_ratio",
        status="ready",
        actions=[
            LinkedRepairAction(
                action_type="replace_volunteers",
                remove_volunteer_ids=["old-1"],
                candidate_volunteer_ids=["new-1"],
            ),
            LinkedRepairAction(action_type="remove_volunteers", volunteer_ids=["wrong"]),
        ],
    )

    assert proposal.strategy == "rebalance_tier_ratio"
    assert proposal.applyable is False
    assert [action.action_type for action in proposal.actions] == ["replace_volunteers"]


def test_linked_repair_proposal_marks_supported_ready_strategy_applyable():
    proposal = LinkedRepairProposal(
        proposal_id="fp-2",
        strategy="replace_risk_items",
        status="ready",
        actions=[
            LinkedRepairAction(action_type="replace_volunteers"),
        ],
    )

    assert proposal.applyable is True
    assert proposal.requires_confirmation is True


def test_linked_repair_proposal_user_goal_source_is_not_applyable_until_bridge_exists():
    proposal = LinkedRepairProposal(
        proposal_id="fp-user-goal",
        proposal_source="user_goal",
        strategy="replace_risk_items",
        status="ready",
        actions=[LinkedRepairAction(action_type="replace_volunteers")],
    )

    assert proposal.proposal_source == "user_goal"
    assert proposal.applyable is False
    assert proposal.requires_confirmation is True


def test_linked_repair_proposal_keeps_only_keep_replacement_preview_action():
    proposal = LinkedRepairProposal(
        proposal_id="fp-user-goal-only-keep",
        proposal_source="user_goal",
        strategy="only_keep_scope",
        status="preview_only",
        actions=[
            LinkedRepairAction(action_type="replace_volunteers"),
            LinkedRepairAction(action_type="remove_volunteers"),
        ],
    )

    assert proposal.proposal_source == "user_goal"
    assert proposal.applyable is False
    assert [action.action_type for action in proposal.actions] == [
        "replace_volunteers",
        "remove_volunteers",
    ]


def test_linked_repair_proposal_blocks_noop_and_cannot_satisfy():
    blocked = LinkedRepairProposal(
        proposal_id="fp-3",
        strategy="cannot_satisfy",
        status="ready",
        actions=[LinkedRepairAction(action_type="replace_volunteers")],
    )
    info = LinkedRepairProposal(
        proposal_id="fp-4",
        strategy="info",
        status="ready",
        actions=[LinkedRepairAction(action_type="sort_ordered_plan")],
    )

    assert blocked.status == "blocked"
    assert blocked.applyable is False
    assert blocked.requires_confirmation is False
    assert blocked.actions == []
    assert info.strategy == "no_op"
    assert info.status == "info"
    assert info.applyable is False
    assert info.requires_confirmation is False
    assert info.actions == []


def test_composite_plan_proposal_accepts_linked_repair_proposals():
    proposal = CompositePlanProposal(
        linked_fix_proposals=[
            {
                "proposal_id": "fp-5",
                "strategy": "fill_total_count",
                "status": "ready",
                "actions": [{"action_type": "fill_total_count"}],
            }
        ],
        feasibility="ready",
    )

    assert proposal.linked_fix_proposals[0].strategy == "fill_missing_count"
    assert proposal.linked_fix_proposals[0].applyable is True
    assert proposal.has_plan_mutation is True


def test_composite_plan_proposal_user_goal_preview_is_not_executable_mutation():
    proposal = CompositePlanProposal(
        linked_fix_proposals=[
            {
                "proposal_id": "ugp-1",
                "proposal_source": "user_goal",
                "strategy": "only_keep_scope",
                "status": "preview_only",
                "actions": [{"action_type": "replace_volunteers"}],
            }
        ],
        feasibility="preview_only",
    )

    assert proposal.linked_fix_proposals[0].applyable is False
    assert proposal.has_plan_mutation is False


def test_composite_plan_proposal_clarification_is_not_confirmable():
    goal = PlanGoal(goal_type="clarify", user_original_text="这些都不要")
    proposal = CompositePlanProposal(
        goal=goal,
        feasibility="ready",
        requires_confirmation=True,
    )

    assert proposal.feasibility == "needs_clarification"
    assert proposal.requires_confirmation is False


def test_plan_goal_exposes_user_visible_entity_ambiguity_notes():
    goal = PlanGoal(
        goal_type="exclude_scope",
        user_original_text="不想学工商管理",
        entity_resolutions=[
            PlanEntityResolution(
                raw_text="工商管理",
                entity_type="major",
                canonical_name="工商管理",
                canonical_level="level3",
                ambiguity="catalog_vs_admission_plan",
                user_visible_note="我先按具体专业工商管理理解；当前方案里也有包含工商管理的专业类，需要确认是否一起处理。",
            )
        ],
    )

    assert goal.has_entity_ambiguity is True
    assert goal.user_visible_entity_notes == [
        "我先按具体专业工商管理理解；当前方案里也有包含工商管理的专业类，需要确认是否一起处理。"
    ]


def test_plan_goal_clarify_forces_needs_clarification():
    goal = PlanGoal(goal_type="clarify", user_original_text="不想学工商管理")

    assert goal.needs_clarification is True


def test_plan_goal_rejects_unknown_goal_type():
    with pytest.raises(ValidationError):
        PlanGoal(goal_type="keep_everything")  # type: ignore[arg-type]


def test_legacy_top_level_compound_goal_is_ignored_by_plan_action_envelope():
    payload = normalize_plan_action_payload(
        {
            "stage": "preview",
            "action_family": "remove_units",
            "user_goal": "只保留临床医学",
            "goal": {
                "goal_type": "only_keep_scope",
                "target_scopes": [{"entityType": "major", "name": "临床医学"}],
            },
        }
    )
    plan = PlanActionPlan.model_validate(payload)

    assert plan.composite_proposal is None
    assert plan.atomic_actions == []
