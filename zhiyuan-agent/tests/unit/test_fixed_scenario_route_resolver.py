from app.models.semantic_router import FixedScenarioRouteFrame, FixedScenarioRouteResult
from app.resolver.fixed_scenario_route_resolver import resolve_fixed_scenario_routes


def _result(frame: FixedScenarioRouteFrame) -> FixedScenarioRouteResult:
    return FixedScenarioRouteResult(status="success", frame=frame, durationMs=123, promptChars=456)


def test_fixed_scenario_resolver_accepts_major_compare_with_local_catalog():
    resolved = resolve_fixed_scenario_routes(
        _result(
            FixedScenarioRouteFrame(
                fixedScenario="major_compare.readonly",
                sideEffect="readonly",
                confidence=0.93,
                entities={"majorNames": ["法学", "财政学"]},
            )
        )
    )

    decision = resolved.major_compare_decision
    assert decision is not None
    assert decision.matched is True
    assert decision.major_names == ["法学", "财政学"]
    assert resolved.route_decision["selectedFixedScenario"] == "major_compare.readonly"


def test_fixed_scenario_resolver_blocks_open_major_fit_question_shape():
    resolved = resolve_fixed_scenario_routes(
        _result(
            FixedScenarioRouteFrame(
                fixedScenario="none",
                sideEffect="readonly",
                confidence=0.74,
                mustFallbackReason="open_major_fit_question",
            )
        )
    )

    assert resolved.major_compare_decision is None
    assert resolved.route_decision["fallbackReason"] == "open_major_fit_question"


def test_fixed_scenario_resolver_rejects_major_compare_without_two_valid_majors():
    resolved = resolve_fixed_scenario_routes(
        _result(
            FixedScenarioRouteFrame(
                fixedScenario="major_compare.readonly",
                sideEffect="readonly",
                confidence=0.96,
                entities={"majorNames": ["不存在专业", "财政学"]},
            )
        )
    )

    assert resolved.major_compare_decision is None
    assert resolved.route_decision["fallbackReason"] == "validated_major_count_1"


def test_fixed_scenario_resolver_builds_major_intent_preview_payload():
    resolved = resolve_fixed_scenario_routes(
        _result(
            FixedScenarioRouteFrame(
                fixedScenario="major_intent.preview",
                sideEffect="preview",
                confidence=0.91,
                entities={
                    "positiveMajorNames": ["会计学", "审计学"],
                    "negativeMajorNames": ["土木工程"],
                },
            )
        )
    )

    decision = resolved.major_intent_decision
    assert decision is not None
    assert decision.matched is True
    assert decision.major_intents == {
        "level3": ["会计学", "审计学"],
        "negative_level3": ["土木工程"],
    }
    assert decision.intent_mode == "constraint"


def test_fixed_scenario_resolver_builds_career_direction_decision():
    resolved = resolve_fixed_scenario_routes(
        _result(
            FixedScenarioRouteFrame(
                fixedScenario="career_direction.readonly",
                sideEffect="readonly",
                confidence=0.9,
                entities={"careerDirections": ["system_public_service", "further_study"]},
            )
        )
    )

    decision = resolved.career_direction_decision
    assert decision is not None
    assert decision.matched is True
    assert decision.direction_slots == ["system_public_service", "further_study"]


def test_fixed_scenario_resolver_blocks_apply_and_ambiguous_frames():
    apply_result = resolve_fixed_scenario_routes(
        _result(
            FixedScenarioRouteFrame(
                fixedScenario="major_intent.preview",
                sideEffect="apply",
                confidence=0.95,
                entities={"positiveMajorNames": ["会计学"]},
            )
        )
    )
    ambiguous_result = resolve_fixed_scenario_routes(
        _result(
            FixedScenarioRouteFrame(
                fixedScenario="major_compare.readonly",
                sideEffect="readonly",
                confidence=0.95,
                ambiguity=["专业简称不确定"],
                entities={"majorNames": ["财", "法"]},
            )
        )
    )

    assert apply_result.route_decision["fallbackReason"] == "apply_side_effect_not_allowed"
    assert ambiguous_result.route_decision["fallbackReason"] == "ambiguous_fixed_scenario"
