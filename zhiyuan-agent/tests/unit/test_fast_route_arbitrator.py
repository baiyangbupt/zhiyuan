from types import SimpleNamespace

from app.resolver.career_direction_fast_router import resolve_career_direction_fast_route
from app.resolver.fast_route_arbitrator import arbitrate_fast_route_candidates
from app.resolver.major_compare_fast_router import resolve_major_compare_fast_route
from app.resolver.major_intent_fast_router import resolve_major_intent_fast_route
from app.resolver.plan_fast_router import resolve_plan_fast_route
from app.resolver.plan_query_fast_router import resolve_plan_query_fast_route


def _arbitrate(prompt: str):
    return arbitrate_fast_route_candidates(
        prompt,
        plan_fast_decision=resolve_plan_fast_route(prompt),
        plan_query_decision=resolve_plan_query_fast_route(prompt),
        major_intent_decision=resolve_major_intent_fast_route(prompt),
        major_compare_decision=resolve_major_compare_fast_route(prompt),
        career_direction_decision=resolve_career_direction_fast_route(prompt),
    )


def test_arbitrator_keeps_explicit_plan_lookup_ahead_of_intent_preview():
    result = _arbitrate("孩子不想学医也不想护理，方案里有没有这种坑，先看看")

    assert result.selected_path == "plan_query_fast_route"
    assert result.selected.action_family == "query_volunteer_plan"
    assert {candidate.path for candidate in result.candidates} == {
        "plan_query_fast_route",
        "major_intent_fast_route",
    }


def test_arbitrator_routes_unscoped_intent_impact_to_intent_preview():
    result = _arbitrate("医学护理这些别碰，财会还能接受，先看看影响")

    assert result.selected_path == "major_intent_fast_route"
    assert result.selected.action_family == "preview_major_intent"


def test_arbitrator_blocks_thin_region_safety_plan_overview():
    result = _arbitrate("孩子就想去北京天津，但分数不算高，这样是不是太冒险，先别改")

    assert result.selected_path == "region_safety_tradeoff_route"
    assert result.candidates[0].path == "plan_fast_route"
    assert result.candidates[0].blockers == ["region_safety_tradeoff_needs_full_analysis"]
    assert result.candidates[1].path == "region_safety_tradeoff_route"
    assert result.candidates[1].action_family == "analyze_region_safety_tradeoff"


def test_arbitrator_routes_region_safety_tradeoff_without_plan_fast_candidate():
    result = _arbitrate("北京天津想去但别最后没学上这个取舍咋看")

    assert result.selected_path == "region_safety_tradeoff_route"
    assert result.selected.action_family == "analyze_region_safety_tradeoff"
    assert len(result.candidates) == 1


def test_arbitrator_allows_high_confidence_plan_status_and_mutation_preview():
    status_result = _arbitrate("这方案咋样，能不能说重点")
    move_result = _arbitrate("把第2个志愿移到第4位")

    assert status_result.selected_path == "plan_fast_route"
    assert status_result.selected.action_family == "query_state"
    assert status_result.selected.fixed_scenario == "plan.status_overview_readonly"
    assert move_result.selected_path == "plan_fast_route"
    assert move_result.selected.action_family == "move_unit"
    assert move_result.selected.fixed_scenario == "plan.numeric_volunteer_move_preview"
    assert move_result.selected.side_effect == "preview_confirmation"


def test_arbitrator_records_all_candidate_metadata_for_observability():
    result = arbitrate_fast_route_candidates(
        "当前方案里有没有生物工程",
        plan_query_decision=SimpleNamespace(
            matched=True,
            reason="readonly_plan_candidate_local_query",
            confidence="high",
        ),
    )

    decision = result.route_decision()
    assert decision["qualityFirst"] is True
    assert decision["selectedPath"] == "plan_query_fast_route"
    assert decision["selectedFixedScenario"] == "plan_query.plan_then_candidate_local_lookup_readonly"
    assert decision["candidates"][0]["eligible"] is True
    assert decision["candidates"][0]["quality"] == "high"
    assert decision["candidates"][0]["fixedScenario"] == "plan_query.plan_then_candidate_local_lookup_readonly"
    assert decision["semanticArbitrationNeeded"] is False
    assert decision["semanticArbitrationReason"] is None


def test_arbitrator_marks_close_mixed_candidates_for_semantic_arbitration_shadow():
    result = _arbitrate("孩子不想学医也不想护理，方案里有没有这种坑，先看看")

    decision = result.route_decision()
    assert decision["selectedPath"] == "plan_query_fast_route"
    assert decision["semanticArbitrationNeeded"] is True
    assert decision["semanticArbitrationReason"] == "close_fast_route_candidates"
    assert set(decision["semanticArbitrationCandidatePaths"]) == {
        "plan_query_fast_route",
        "major_intent_fast_route",
    }


def test_arbitrator_does_not_mark_single_high_confidence_plan_mutation():
    result = _arbitrate("把第2个志愿移到第4位")

    decision = result.route_decision()
    assert decision["selectedPath"] == "plan_fast_route"
    assert decision["semanticArbitrationNeeded"] is False
    assert decision["semanticArbitrationCandidatePaths"] == ["plan_fast_route"]


def test_arbitrator_marks_low_confidence_candidate_for_semantic_arbitration_shadow():
    result = arbitrate_fast_route_candidates(
        "这类问题先别直接按方案概览回答",
        plan_fast_decision=SimpleNamespace(
            matched=True,
            reason="plan_status_query",
            confidence="medium",
            action_family="query_state",
        ),
    )

    decision = result.route_decision()
    assert decision["selectedPath"] == "plan_fast_route"
    assert decision["semanticArbitrationNeeded"] is True
    assert decision["semanticArbitrationReason"] == "low_confidence_candidate"


def test_arbitrator_does_not_mark_structured_region_safety_fallback_for_shadow():
    result = arbitrate_fast_route_candidates(
        "孩子就想去北京天津，但分数不算高，这样是不是太冒险，先别改",
        plan_fast_decision=SimpleNamespace(
            matched=True,
            reason="plan_risk_status_query",
            confidence="high",
            action_family="query_state",
        ),
    )

    decision = result.route_decision()
    assert decision["selectedPath"] == "region_safety_tradeoff_route"
    assert decision["semanticArbitrationNeeded"] is False


def test_arbitrator_blocks_matched_candidate_outside_fixed_scenario_whitelist():
    result = arbitrate_fast_route_candidates(
        "开放问题不该直接进固定入口",
        plan_fast_decision=SimpleNamespace(
            matched=True,
            reason="manual_experimental_case",
            confidence="high",
            action_family="query_state",
        ),
    )

    assert result.selected_path is None
    assert result.fallback_reason == "quality_gate_blocked_fast_route"
    assert result.candidates[0].blockers == ["not_high_confidence_fixed_scenario"]


def test_arbitrator_does_not_route_professional_fit_question_as_major_compare():
    result = _arbitrate("物理不太好但选了物化地，计算机还现实吗")

    assert result.selected_path is None
    assert result.fallback_reason == "no_fast_route_candidate"


def test_arbitrator_keeps_exact_major_compare_as_fixed_readonly_scenario():
    result = _arbitrate("法学和财政学哪个更适合普通家庭女生，先只分析不要记偏好")

    assert result.selected_path == "major_compare_fast_route"
    assert result.selected.fixed_scenario == "major_compare.exact_two_level3_readonly"
