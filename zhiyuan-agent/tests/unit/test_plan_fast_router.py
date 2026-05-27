from __future__ import annotations

from app.resolver.plan_fast_router import resolve_plan_fast_route


def test_resolve_plan_fast_route_matches_plan_status_query():
    decision = resolve_plan_fast_route("看看现在的方案，给我一个结构化一点的结论")

    assert decision.matched is True
    assert decision.action_family == "query_state"
    assert decision.reason == "plan_status_query"


def test_resolve_plan_fast_route_matches_colloquial_plan_status_query():
    decision = resolve_plan_fast_route("这方案咋样，能不能说重点")

    assert decision.matched is True
    assert decision.action_family == "query_state"
    assert decision.reason == "plan_status_query"


def test_resolve_plan_fast_route_matches_safety_status_question_as_readonly():
    decision = resolve_plan_fast_route("保底够不够啊")

    assert decision.matched is True
    assert decision.action_family == "query_state"
    assert decision.reason == "plan_safety_status_query"


def test_resolve_plan_fast_route_matches_colloquial_risk_status_as_readonly():
    decision = resolve_plan_fast_route("这版是不是太冲了，能不能给我说人话")

    assert decision.matched is True
    assert decision.action_family == "query_state"
    assert decision.reason == "plan_risk_status_query"


def test_resolve_plan_fast_route_matches_budget_and_region_risk_readonly():
    budget_decision = resolve_plan_fast_route("方案里中外合作是不是有点多，家里预算一般，帮我用大白话看下风险，先别动")
    region_decision = resolve_plan_fast_route("孩子就想去北京天津，但分数不算高，这样是不是太冒险，先别改")

    assert budget_decision.matched is True
    assert budget_decision.action_family == "query_state"
    assert region_decision.matched is True
    assert region_decision.action_family == "query_state"


def test_resolve_plan_fast_route_matches_colloquial_adjustment_analysis():
    decision = resolve_plan_fast_route("就按别太冒险的思路把这版调稳点，先给我看看会怎么动")

    assert decision.matched is True
    assert decision.action_family == "analyze_adjustment"
    assert decision.reason == "colloquial_adjustment_analysis"


def test_resolve_plan_fast_route_keeps_explicit_compensation_as_preview():
    decision = resolve_plan_fast_route("保底不够的话先给我补齐预览")

    assert decision.matched is True
    assert decision.action_family == "preview_compensation"


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


def test_resolve_plan_fast_route_matches_lazy_good_school_sort():
    decision = resolve_plan_fast_route("按好学校排下看看")

    assert decision.matched is True
    assert decision.action_family == "sort_ordered_plan"
    assert decision.reason == "explicit_sort_dimension"
    assert decision.filters == {"sort_field": "schoolRank"}


def test_resolve_plan_fast_route_matches_review_followup_adjustment_preview():
    decision = resolve_plan_fast_route("针对最严重的问题，先给我调整预览，不要直接执行")

    assert decision.matched is True
    assert decision.action_family == "analyze_adjustment"
    assert decision.reason == "review_followup_adjustment_preview"


def test_resolve_plan_fast_route_matches_review_followup_compensation_preview():
    decision = resolve_plan_fast_route("针对本省保底不足，先给我补齐预览，不要直接执行")

    assert decision.matched is True
    assert decision.action_family == "preview_compensation"
    assert decision.reason == "review_followup_compensation_preview"


def test_resolve_plan_fast_route_does_not_match_review_followup_readonly_question():
    decision = resolve_plan_fast_route("最严重的问题是什么，优先解决哪个")

    assert decision.matched is False
    assert decision.reason == "no_high_confidence_plan_pattern"


def test_resolve_plan_fast_route_does_not_match_generic_preview_without_review_anchor():
    decision = resolve_plan_fast_route("先给我一个预览，不要直接执行")

    assert decision.matched is False
    assert decision.reason == "no_high_confidence_plan_pattern"


def test_resolve_plan_fast_route_does_not_match_ambiguous_name_operation():
    decision = resolve_plan_fast_route("把广西师大统计、会计学改到第3位")

    assert decision.matched is False
    assert decision.route_decision()["fallbackReason"] == "no_high_confidence_plan_pattern"


def test_resolve_plan_fast_route_matches_named_volunteer_move():
    decision = resolve_plan_fast_route("把湖北工程学院的计算机科学与技术改到第3位")

    assert decision.matched is True
    assert decision.action_family == "move_unit"
    assert decision.reason == "named_volunteer_move"
    assert decision.volunteer_ids == ["湖北工程学院的计算机科学与技术"]
    assert decision.target_position == 3


def test_resolve_plan_fast_route_matches_named_volunteer_remove():
    decision = resolve_plan_fast_route("去掉湖北工程学院.计算机科学与技术")

    assert decision.matched is True
    assert decision.action_family == "remove_units"
    assert decision.reason == "named_volunteer_remove"
    assert decision.volunteer_ids == ["湖北工程学院.计算机科学与技术"]


def test_resolve_plan_fast_route_matches_named_candidate_add():
    decision = resolve_plan_fast_route("把湖北工程学院的计算机科学与技术如果在候选里，就加入方案")

    assert decision.matched is True
    assert decision.action_family == "add_units"
    assert decision.reason == "named_candidate_add"
    assert decision.volunteer_ids == ["湖北工程学院的计算机科学与技术"]


def test_resolve_plan_fast_route_matches_named_candidate_alias_add():
    decision = resolve_plan_fast_route("把广西师大统计加进来")

    assert decision.matched is True
    assert decision.action_family == "add_units"
    assert decision.volunteer_ids == ["广西师大统计"]


def test_resolve_plan_fast_route_does_not_match_readonly_named_query():
    decision = resolve_plan_fast_route("青岛城市学院相关专业是不是有多个，先帮我判断一下，不要直接改方案")

    assert decision.matched is False
    assert decision.reason == "no_high_confidence_plan_pattern"


def test_resolve_plan_fast_route_does_not_match_major_intent():
    decision = resolve_plan_fast_route("我想把计算机科学与技术作为偏好")

    assert decision.matched is False
    assert decision.reason == "no_high_confidence_plan_pattern"


def test_resolve_plan_fast_route_does_not_match_compound_named_mutation():
    decision = resolve_plan_fast_route("删掉山东英才学院的国际商务，然后从候选里再补一个稳档")

    assert decision.matched is False
    assert decision.reason == "no_high_confidence_plan_pattern"


def test_resolve_plan_fast_route_does_not_match_too_short_named_ref():
    decision = resolve_plan_fast_route("把会计改到第3位")

    assert decision.matched is False
    assert decision.reason == "no_high_confidence_plan_pattern"


def test_resolve_plan_fast_route_allows_major_name_with_he():
    decision = resolve_plan_fast_route("把国际经济与贸易改到第3位")

    assert decision.matched is True
    assert decision.action_family == "move_unit"
    assert decision.volunteer_ids == ["国际经济与贸易"]
