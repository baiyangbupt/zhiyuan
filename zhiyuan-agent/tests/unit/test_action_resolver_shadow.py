from app.agent.context import PlanningSummary
from app.resolver.action_resolver_shadow import action_resolver_shadow_from_plan_fast_decision
from app.resolver.plan_fast_router import resolve_plan_fast_route


def _summary() -> PlanningSummary:
    return PlanningSummary(
        phase="ordered",
        ordered_total=45,
        ordered_target_total=45,
        draft_total=45,
        draft_target_total=45,
    )


def test_action_resolver_shadow_matches_numeric_ordered_unit_move():
    decision = resolve_plan_fast_route("把第4个专业组移到第2位")

    shadow = action_resolver_shadow_from_plan_fast_decision(
        text="把第4个专业组移到第2位",
        decision=decision,
        planning_summary=_summary(),
    )

    assert shadow is not None
    assert shadow["actualActionFamily"] == "move_ordered_unit"
    assert shadow["shadowActionFamily"] == "move_ordered_unit"
    assert shadow["shadowStage"] == "preview"
    assert shadow["actionFamilyMatch"] is True
    assert shadow["missingInputs"] == []


def test_action_resolver_shadow_matches_sort_fast_route():
    decision = resolve_plan_fast_route("按院校层次排序")

    shadow = action_resolver_shadow_from_plan_fast_decision(
        text="按院校层次排序",
        decision=decision,
        planning_summary=_summary(),
    )

    assert shadow is not None
    assert shadow["actualActionFamily"] == "sort_ordered_plan"
    assert shadow["shadowActionFamily"] == "sort_ordered_plan"
    assert shadow["shadowStage"] == "preview"
    assert shadow["actionFamilyMatch"] is True
