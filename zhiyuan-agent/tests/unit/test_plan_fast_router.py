from __future__ import annotations

from app.resolver.plan_fast_router import resolve_plan_fast_route


def test_resolve_plan_fast_route_matches_plan_status_query():
    decision = resolve_plan_fast_route("看看现在的方案，给我一个结构化一点的结论")

    assert decision.matched is True
    assert decision.action_family == "query_state"
    assert decision.reason == "plan_status_query"


def test_resolve_plan_fast_route_matches_numeric_volunteer_move():
    decision = resolve_plan_fast_route("把第2个志愿移到第4位")

    assert decision.matched is True
    assert decision.action_family == "move_unit"
    assert decision.volunteer_ids == ["@2"]
    assert decision.target_position == 4


def test_resolve_plan_fast_route_matches_numeric_ordered_unit_move():
    decision = resolve_plan_fast_route("把第4个专业组移到第2位")

    assert decision.matched is True
    assert decision.action_family == "move_ordered_unit"
    assert decision.unit_ids == []
    assert decision.target_position == 2


def test_resolve_plan_fast_route_matches_sort_and_review():
    sort_decision = resolve_plan_fast_route("按院校层次排序")
    review_decision = resolve_plan_fast_route("审查一下方案")

    assert sort_decision.matched is True
    assert sort_decision.action_family == "sort_ordered_plan"
    assert review_decision.matched is True
    assert review_decision.action_family == "review_plan"


def test_resolve_plan_fast_route_does_not_match_ambiguous_name_operation():
    decision = resolve_plan_fast_route("把广西师大统计改到第3位")

    assert decision.matched is False
    assert decision.route_decision()["fallbackReason"] == "no_high_confidence_plan_pattern"
