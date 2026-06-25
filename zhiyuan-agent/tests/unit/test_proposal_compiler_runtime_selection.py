import json

from app.domain import proposal_compiler


class _Decision:
    def __init__(
        self,
        *,
        action_family: str = "preview_fix_proposal",
        confidence: float = 0.9,
        target_strategies=None,
        target_issue_codes=None,
        reply_focus=None,
    ):
        self.actionFamily = action_family
        self.confidence = confidence
        self.targetStrategies = target_strategies or []
        self.targetIssueCodes = target_issue_codes or []
        self.replyFocus = reply_focus or []


class _TurnDecision:
    def __init__(
        self,
        *,
        task_layer: str = "explore",
        side_effect: str = "readonly",
        scope_anchor: str = "general",
        scenario: str = "atomic_mutation",
        confidence: float = 0.9,
    ):
        self.taskLayer = task_layer
        self.sideEffect = side_effect
        self.scopeAnchor = scope_anchor
        self.scenario = scenario
        self.confidence = confidence


def _proposal(proposal_id: str, *, strategy: str = "", status: str = "ready", issue_codes=None):
    return {
        "proposal_id": proposal_id,
        "status": status,
        "strategy": strategy,
        "source_check_codes": list(issue_codes or []),
    }


def _latest_result(*proposals, selected_proposal_id: str = ""):
    result = {
        "facts": {
            "fix_proposals": {
                "proposals": list(proposals),
                "source_version_guard": 3,
            }
        }
    }
    if selected_proposal_id:
        result["selected_proposal_id"] = selected_proposal_id
    return result


def test_intent_preview_turn_decision_arbitration_allows_soft_readonly_aligned_preview():
    source = proposal_compiler.compile_runtime_intent_preview_turn_decision_arbitration_source(
        turn_decision=_TurnDecision(),
        turn_decision_blocks_intent_pending=True,
        semantic_intent_preview_requested=True,
        semantic_entity_kinds={"major"},
        preview_payload_entity_kinds={"major"},
        preview_candidate_valid=True,
    )

    assert source.matched is True
    assert source.allow_intent_pending is True
    assert source.route == "turn_decision_intent_preview_arbitration"
    assert source.blocking_reasons == []
    assert source.arbitration_dsl["sourceInputs"] == [
        "turn_decision",
        "intent_side_effect_decision",
        "intent_preview_payload",
        "intent_preview_candidate",
    ]


def test_intent_preview_turn_decision_arbitration_blocks_current_plan_atomic_mutation():
    source = proposal_compiler.compile_runtime_intent_preview_turn_decision_arbitration_source(
        turn_decision=_TurnDecision(
            task_layer="plan",
            side_effect="plan_preview",
            scope_anchor="current_plan",
            scenario="atomic_mutation",
        ),
        turn_decision_blocks_intent_pending=True,
        semantic_intent_preview_requested=True,
        semantic_entity_kinds={"major"},
        preview_payload_entity_kinds={"major"},
        preview_candidate_valid=True,
    )

    assert source.allow_intent_pending is False
    assert "current_plan_atomic_mutation_requires_plan_route" in source.blocking_reasons


def test_intent_preview_turn_decision_arbitration_blocks_plan_query_scope():
    source = proposal_compiler.compile_runtime_intent_preview_turn_decision_arbitration_source(
        turn_decision=_TurnDecision(
            task_layer="plan",
            side_effect="readonly",
            scope_anchor="current_plan",
            scenario="plan_query",
        ),
        turn_decision_blocks_intent_pending=True,
        semantic_intent_preview_requested=True,
        semantic_entity_kinds={"major"},
        preview_payload_entity_kinds={"major"},
        preview_candidate_valid=True,
    )

    assert source.allow_intent_pending is False
    assert "unsupported_turn_decision_scope_anchor_for_intent_override" in source.blocking_reasons
    assert "plan_query_turn_decision_cannot_be_intent_override" in source.blocking_reasons


def test_intent_preview_turn_decision_arbitration_blocks_mismatched_or_invalid_preview():
    source = proposal_compiler.compile_runtime_intent_preview_turn_decision_arbitration_source(
        turn_decision=_TurnDecision(),
        turn_decision_blocks_intent_pending=True,
        semantic_intent_preview_requested=True,
        semantic_entity_kinds={"school"},
        preview_payload_entity_kinds={"major"},
        preview_candidate_valid=False,
    )

    assert source.allow_intent_pending is False
    assert "invalid_intent_preview_candidate" in source.blocking_reasons
    assert "semantic_payload_entity_kind_mismatch" in source.blocking_reasons


def test_runtime_fix_selection_uses_selected_ready_proposal_id():
    result = proposal_compiler.select_fix_proposal_candidate_for_runtime(
        _latest_result(
            _proposal("fp-count", strategy="fill_missing_count"),
            _proposal("fp-gap", strategy="fill_probability_gap"),
            selected_proposal_id="fp-gap",
        )
    )

    assert result.proposal is not None
    assert proposal_compiler.proposal_id(result.proposal) == "fp-gap"
    assert result.selected_proposal_id == "fp-gap"
    assert result.blocking_reasons == []


def test_runtime_fix_selection_blocks_missing_selected_proposal_id_without_fallback():
    result = proposal_compiler.select_fix_proposal_candidate_for_runtime(
        _latest_result(
            _proposal("fp-count", strategy="fill_missing_count"),
            selected_proposal_id="fp-stale",
        )
    )

    assert result.proposal is None
    assert result.selected_proposal_id == "fp-stale"
    assert result.target_match_empty is False
    assert result.blocking_reasons == ["selected_fix_proposal_not_ready_or_missing"]


def test_runtime_fix_selection_marks_explicit_empty_target_scope():
    result = proposal_compiler.select_fix_proposal_candidate_for_runtime(
        _latest_result(_proposal("fp-count", strategy="fill_missing_count")),
        target_scope_explicit=True,
    )

    assert result.proposal is None
    assert result.target_match_empty is True
    assert result.blocking_reasons == ["explicit_target_scope_without_supported_target"]


def test_runtime_fix_selection_marks_target_scope_without_ready_match():
    result = proposal_compiler.select_fix_proposal_candidate_for_runtime(
        _latest_result(_proposal("fp-count", strategy="fill_missing_count")),
        target_strategies=["fill_probability_gap"],
        target_scope_explicit=True,
    )

    assert result.proposal is None
    assert result.target_strategies == ["fill_probability_gap"]
    assert result.target_match_empty is True
    assert result.blocking_reasons == ["no_ready_fix_proposal_for_target_scope"]


def test_runtime_fix_selection_blocks_ambiguous_target_scope():
    result = proposal_compiler.select_fix_proposal_candidate_for_runtime(
        _latest_result(
            _proposal("fp-count-a", strategy="fill_missing_count", issue_codes=["count_shortage"]),
            _proposal("fp-count-b", strategy="fill_missing_count", issue_codes=["count_shortage"]),
        ),
        target_strategies=["fill_missing_count"],
        target_issue_codes=["count_shortage"],
        target_scope_explicit=True,
    )

    assert result.proposal is None
    assert result.target_match_empty is False
    assert result.blocking_reasons == ["ambiguous_ready_fix_proposal_for_target_scope"]


def test_runtime_fix_selection_uses_unique_ready_proposal_without_target_scope():
    result = proposal_compiler.select_fix_proposal_candidate_for_runtime(
        _latest_result(
            _proposal("fp-count", strategy="fill_missing_count"),
            _proposal("fp-gap", strategy="fill_probability_gap", status="preview_only"),
        )
    )

    assert result.proposal is not None
    assert proposal_compiler.proposal_id(result.proposal) == "fp-count"
    assert result.selected_proposal_id == "fp-count"
    assert result.blocking_reasons == []


def test_runtime_fix_confirmation_source_requires_preview_fix_result():
    result = _latest_result(_proposal("fp-count", strategy="fill_missing_count"))
    result["action_family"] = "review_plan"
    result["result_kind"] = "review_result"

    source = proposal_compiler.runtime_fix_proposal_confirmation_source_from_result(result)

    assert source is None


def test_runtime_fix_confirmation_source_drops_untargeted_result_without_ready_match():
    result = _latest_result(_proposal("fp-count", strategy="fill_missing_count", status="preview_only"))
    result["action_family"] = "preview_fix_proposal"
    result["result_kind"] = "fix_proposal_preview"

    source = proposal_compiler.runtime_fix_proposal_confirmation_source_from_result(result)

    assert source is None


def test_runtime_fix_confirmation_source_preserves_empty_target_match_boundary():
    result = _latest_result(_proposal("fp-count", strategy="fill_missing_count"))
    result["action_family"] = "preview_fix_proposal"
    result["result_kind"] = "fix_proposal_preview"

    source = proposal_compiler.runtime_fix_proposal_confirmation_source_from_result(
        result,
        plan_payload={"target_strategies": ["fill_probability_gap"]},
    )

    assert source is not None
    assert source["target_strategies"] == ["fill_probability_gap"]
    assert source["target_match_empty"] is True


def test_runtime_fix_confirmation_source_uses_plan_payload_target_scope():
    result = _latest_result(_proposal("fp-count", strategy="fill_missing_count", issue_codes=["count_shortage"]))
    result["action_family"] = "preview_fix_proposal"
    result["result_kind"] = "fix_proposal_preview"

    source = proposal_compiler.runtime_fix_proposal_confirmation_source_from_result(
        result,
        plan_payload={
            "targetStrategies": ["fill_missing_count"],
            "targetIssueCodes": ["count_shortage"],
        },
    )

    assert source is not None
    assert source["target_strategies"] == ["fill_missing_count"]
    assert source["target_issue_codes"] == ["count_shortage"]
    assert source["target_match_empty"] is False


def test_compile_runtime_review_fix_source_builds_compiled_proposal():
    result = _latest_result(
        {
            **_proposal("fp-count", strategy="fill_missing_count", issue_codes=["count_shortage"]),
            "actions": [{"type": "add", "detail": "补足数量"}],
            "dryRunObservation": {"status": "ready"},
            "summary": "补足志愿数量",
        }
    )

    compiled_source = proposal_compiler.compile_runtime_review_fix_source(
        session_id="s1",
        latest_plan_result=result,
        target_strategies=["fill_missing_count"],
        target_issue_codes=["count_shortage"],
    )

    assert compiled_source.proposal is not None
    assert compiled_source.source_version_guard == 3
    assert compiled_source.proposal_source == "review_check"
    assert compiled_source.blocking_reasons == []
    assert compiled_source.compiled is not None
    assert compiled_source.compiled["pendingType"] == "plan_mutation"
    assert compiled_source.compiled["workspaceRefreshTargets"] == ["review"]
    assert compiled_source.compiled["proposalCandidates"][0]["proposalId"] == "fp-count"
    assert compiled_source.compiled["proposalCandidates"][0]["sourceVersionGuard"] == 3


def test_compile_user_goal_fix_proposal_refreshes_ordered_context():
    compiled = proposal_compiler.compile_user_goal_fix_proposal(
        session_id="s1",
        proposal={
            **_proposal("fp-current-plan", strategy="remove_units"),
            "actions": [{"type": "remove", "detail": "移出英语相关志愿"}],
            "dryRunObservation": {"status": "ready"},
        },
        source_version_guard=3,
        user_goal_request={"goalType": "current_plan_major_exclusion"},
        intent_payload={},
        summary="移出英语相关志愿",
    )

    assert compiled["pendingType"] == "plan_mutation"
    assert compiled["executionPayload"]["targetView"] == "ordered"
    assert compiled["workspaceRefreshTargets"] == ["ordered"]


def test_compile_runtime_review_fix_source_blocks_missing_version_guard():
    result = _latest_result(_proposal("fp-count", strategy="fill_missing_count"))
    result["facts"]["fix_proposals"].pop("source_version_guard")

    compiled_source = proposal_compiler.compile_runtime_review_fix_source(
        session_id="s1",
        latest_plan_result=result,
    )

    assert compiled_source.proposal is not None
    assert compiled_source.compiled is None
    assert compiled_source.blocking_reasons == ["missing_source_version_guard"]


def test_compile_runtime_review_fix_source_preserves_selection_blocking_reason():
    result = _latest_result(
        _proposal("fp-count", strategy="fill_missing_count"),
        _proposal("fp-gap", strategy="fill_probability_gap"),
    )

    compiled_source = proposal_compiler.compile_runtime_review_fix_source(
        session_id="s1",
        latest_plan_result=result,
    )

    assert compiled_source.proposal is None
    assert compiled_source.compiled is None
    assert compiled_source.blocking_reasons == ["missing_unique_ready_fix_proposal"]


def test_select_user_goal_fix_proposal_uses_goal_type_ready_match():
    selection = proposal_compiler.select_user_goal_fix_proposal(
        {
            "sourceVersionGuard": 7,
            "proposals": [
                _proposal("fp-count", strategy="fill_missing_count"),
                _proposal("fp-only", strategy="only_keep_scope"),
            ],
        },
        goal_type="only_keep_scope",
        fallback_source_version_guard=3,
    )

    assert selection.proposal is not None
    assert proposal_compiler.proposal_id(selection.proposal) == "fp-only"
    assert selection.proposal["proposalSource"] == "user_goal"
    assert selection.source_version_guard == 7
    assert selection.blocking_reasons == []


def test_select_user_goal_fix_proposal_preserves_fallback_proposal_when_no_ready_match():
    selection = proposal_compiler.select_user_goal_fix_proposal(
        {
            "proposals": [
                _proposal("fp-gap", strategy="fill_probability_gap"),
            ],
        },
        goal_type="only_keep_scope",
        fallback_source_version_guard=5,
    )

    assert selection.proposal is None
    assert selection.fallback_proposal is not None
    assert proposal_compiler.proposal_id(selection.fallback_proposal) == "fp-gap"
    assert selection.source_version_guard == 5
    assert selection.blocking_reasons == ["no_ready_user_goal_fix_proposal_for_goal_type"]


def test_select_user_goal_fix_proposal_blocks_missing_goal_type():
    selection = proposal_compiler.select_user_goal_fix_proposal(
        {
            "sourceVersionGuard": 7,
            "proposals": [
                _proposal("fp-count", strategy="fill_missing_count"),
            ],
        },
        goal_type="",
    )

    assert selection.proposal is None
    assert selection.fallback_proposal is not None
    assert selection.blocking_reasons == ["missing_user_goal_type"]


def test_compile_structured_user_goal_fix_request_source_builds_java_request_and_intent_payload():
    source = {
        "composite_proposal": {
            "source_version": 12,
            "goal": {
                "goal_type": "exclude_scope",
                "user_original_text": "避开经济与金融",
                "negative_scopes": [
                    {"entity_type": "major", "values": ["经济与金融"]},
                ],
                "confidence": "high",
            },
        },
    }

    compiled = proposal_compiler.compile_structured_user_goal_fix_request_source(
        source=source,
        context_source="plan_next_action_structured_goal",
    )

    assert compiled.matched is True
    assert compiled.goal_type == "exclude_scope"
    assert compiled.source_version_guard == 12
    assert compiled.user_goal_request["goalType"] == "exclude_scope"
    assert compiled.user_goal_request["sourceVersionGuard"] == 12
    assert compiled.user_goal_request["context"] == {"source": "plan_next_action_structured_goal"}
    assert compiled.user_goal_request["negativeScopes"][0]["entityType"] == "major"
    assert compiled.user_goal_request["negativeScopes"][0]["normalizedName"] == "经济与金融"
    assert compiled.intent_payload == {
        "selected": [{"major_intents": {"negative_level3": ["经济与金融"]}}],
        "intentMode": "constraint",
        "constraintIntentType": "default",
    }
    assert compiled.blocking_reasons == []


def test_compile_structured_user_goal_fix_request_source_blocks_without_version_guard():
    source = {
        "composite_proposal": {
            "goal": {
                "goal_type": "only_keep_scope",
                "target_scopes": [
                    {"entity_type": "school", "values": ["厦门大学"]},
                ],
            },
        },
    }

    compiled = proposal_compiler.compile_structured_user_goal_fix_request_source(
        source=source,
        context_source="plan_next_action_structured_goal",
    )

    assert compiled.matched is False
    assert compiled.goal_type == "only_keep_scope"
    assert compiled.user_goal_request == {}
    assert compiled.blocking_reasons == ["missing_source_version_guard"]


def test_compile_structured_goal_intent_input_source_preserves_override_payload():
    override = {
        "selected": [{"school_intents": {"colleges": ["厦门大学"]}}],
        "intentMode": "constraint",
        "constraintIntentType": "only_keep",
    }

    compiled = proposal_compiler.compile_structured_goal_intent_input_source(
        source={"composite_proposal": {"goal": {"goal_type": "exclude_scope"}}},
        intent_payload_override=override,
    )

    assert compiled.matched is True
    assert compiled.intent_payload is override
    assert compiled.selected_values == [{"school_intents": {"colleges": ["厦门大学"]}}]
    assert compiled.intent_mode == "constraint"
    assert compiled.raw_constraint_intent_type == "only_keep"


def test_resolve_structured_goal_clarification_returns_questions_and_scope_values():
    resolution = proposal_compiler.resolve_structured_goal_clarification(
        {
            "compositeProposal": {
                "feasibility": "needs_clarification",
                "goal": {
                    "goalType": "only_keep_scope",
                    "clarificationQuestions": ["按专业类还是具体专业处理？"],
                    "targetScopes": [{"entityType": "major", "values": ["计算机类"]}],
                },
            }
        }
    )

    assert resolution.needed is True
    assert resolution.questions == ["按专业类还是具体专业处理？"]
    assert resolution.scope_values == ["计算机类"]
    assert resolution.blocking_reasons == []


def test_resolve_intent_select_input_allows_preference_scope():
    resolution = proposal_compiler.resolve_intent_select_input(
        selected_values=[{"major_intents": {"level3": ["软件工程"]}}],
        merged={"major_intents": {"level3": ["软件工程"]}},
        intent_mode="preference",
        raw_constraint_intent_type="only_keep",
    )

    assert resolution.allowed is True
    assert resolution.intent_mode == "preference"
    assert resolution.constraint_intent_type == "default"
    assert resolution.blocking_reasons == []


def test_resolve_intent_select_input_blocks_empty_selected_values():
    resolution = proposal_compiler.resolve_intent_select_input(
        selected_values=[],
        merged={},
        intent_mode="preference",
        raw_constraint_intent_type="default",
    )

    assert resolution.allowed is False
    assert resolution.blocking_reasons == ["intent_select_requires_selected_values"]


def test_resolve_intent_preview_input_blocks_empty_selected_values_with_preview_reason():
    resolution = proposal_compiler.resolve_intent_preview_input(
        selected_values=[],
        merged={},
        intent_mode="preference",
        raw_constraint_intent_type="default",
    )

    assert resolution.allowed is False
    assert resolution.blocking_reasons == ["intent_preview_requires_selected_values"]


def test_resolve_intent_input_blocks_only_keep_without_positive_scope():
    resolution = proposal_compiler.resolve_intent_preview_input(
        selected_values=[{"city_intents": {"negative_province": ["安徽"]}}],
        merged={"city_intents": {"negative_province": ["安徽"]}},
        intent_mode="constraint",
        raw_constraint_intent_type="only_keep",
    )

    assert resolution.allowed is False
    assert resolution.constraint_intent_type == "default"
    assert resolution.blocking_reasons == ["constraint_intent_requires_scope"]


def test_resolve_intent_input_blocks_constraint_without_any_scope():
    resolution = proposal_compiler.resolve_intent_select_input(
        selected_values=[{"city_intents": {"province": []}}],
        merged={"city_intents": {"province": []}},
        intent_mode="constraint",
        raw_constraint_intent_type="must_have",
    )

    assert resolution.allowed is False
    assert resolution.blocking_reasons == ["constraint_intent_requires_scope"]


def test_resolve_intent_input_allows_constraint_negative_scope():
    resolution = proposal_compiler.resolve_intent_select_input(
        selected_values=[{"city_intents": {"negative_province": ["安徽"]}}],
        merged={"city_intents": {"negative_province": ["安徽"]}},
        intent_mode="constraint",
        raw_constraint_intent_type="exclude_hard",
    )

    assert resolution.allowed is True
    assert resolution.intent_mode == "constraint"
    assert resolution.constraint_intent_type == "exclude_hard"


def test_intent_payload_scope_helpers_detect_positive_and_negative_values():
    positive = {"major_intents": {"level3": ["软件工程"]}}
    negative = {"city_intents": {"negative_province": ["安徽"]}}

    assert proposal_compiler.intent_payload_has_positive_value(positive) is True
    assert proposal_compiler.intent_payload_has_negative_value(positive) is False
    assert proposal_compiler.intent_payload_has_positive_value(negative) is False
    assert proposal_compiler.intent_payload_has_negative_value(negative) is True
    assert proposal_compiler.intent_payload_has_required_constraint_scope(
        positive,
        constraint_intent_type="only_keep",
    ) is True
    assert proposal_compiler.intent_payload_has_required_constraint_scope(
        negative,
        constraint_intent_type="only_keep",
    ) is False
    assert proposal_compiler.intent_payload_has_required_constraint_scope(
        negative,
        constraint_intent_type="exclude_hard",
    ) is True


def test_runtime_fix_selection_blocks_multiple_ready_proposals_without_target_scope():
    result = proposal_compiler.select_fix_proposal_candidate_for_runtime(
        _latest_result(
            _proposal("fp-count", strategy="fill_missing_count"),
            _proposal("fp-gap", strategy="fill_probability_gap"),
        )
    )

    assert result.proposal is None
    assert result.blocking_reasons == ["missing_unique_ready_fix_proposal"]


def test_explicit_target_scope_from_result_normalizes_string_and_list_values():
    scope = proposal_compiler.explicit_fix_proposal_target_scope_from_result(
        {
            "targetStrategies": "fill_missing_count",
            "targetIssueCodes": ["count_shortage", "count_shortage", ""],
        }
    )

    assert scope.explicit is True
    assert scope.target_strategies == ["fill_missing_count"]
    assert scope.target_issue_codes == ["count_shortage"]


def test_semantic_decision_target_scope_respects_action_family_and_confidence():
    allowed = {"preview_fix_proposal"}

    low_confidence = proposal_compiler.semantic_decision_fix_proposal_target_scope(
        _Decision(confidence=0.4, target_strategies=["fill_missing_count"]),
        allowed_action_families=allowed,
        confidence_threshold=0.8,
    )
    wrong_action = proposal_compiler.semantic_decision_fix_proposal_target_scope(
        _Decision(action_family="query_state", target_strategies=["fill_missing_count"]),
        allowed_action_families=allowed,
        confidence_threshold=0.8,
    )
    accepted = proposal_compiler.semantic_decision_fix_proposal_target_scope(
        _Decision(target_strategies="fill_missing_count", target_issue_codes="count_shortage"),
        allowed_action_families=allowed,
        confidence_threshold=0.8,
    )

    assert low_confidence.explicit is False
    assert wrong_action.explicit is False
    assert accepted.explicit is True
    assert accepted.target_strategies == ["fill_missing_count"]
    assert accepted.target_issue_codes == ["count_shortage"]


def test_target_scope_precheck_uses_explicit_result_scope_without_semantic_decision():
    result = _latest_result(_proposal("fp-count", strategy="fill_missing_count"))
    result["target_strategies"] = ["fill_missing_count"]

    scope = proposal_compiler.resolve_fix_proposal_target_scope_precheck(result)

    assert scope.source == "explicit_result_scope"
    assert scope.explicit is True
    assert scope.needs_semantic_decision is False
    assert scope.target_strategies == ["fill_missing_count"]


def test_target_scope_precheck_skips_semantic_decision_when_selected_id_exists():
    scope = proposal_compiler.resolve_fix_proposal_target_scope_precheck(
        _latest_result(
            _proposal("fp-count", strategy="fill_missing_count"),
            selected_proposal_id="fp-count",
        )
    )

    assert scope.source == "selected_proposal_id"
    assert scope.explicit is False
    assert scope.needs_semantic_decision is False


def test_target_scope_precheck_skips_semantic_decision_without_ready_proposal():
    scope = proposal_compiler.resolve_fix_proposal_target_scope_precheck(
        _latest_result(_proposal("fp-count", strategy="fill_missing_count", status="preview_only"))
    )

    assert scope.source == "no_ready_fix_proposal"
    assert scope.needs_semantic_decision is False
    assert scope.blocking_reasons == ["missing_ready_fix_proposal"]


def test_target_scope_precheck_requests_semantic_decision_for_ready_unselected_proposals():
    scope = proposal_compiler.resolve_fix_proposal_target_scope_precheck(
        _latest_result(_proposal("fp-count", strategy="fill_missing_count"))
    )

    assert scope.source == "semantic_decision_required"
    assert scope.needs_semantic_decision is True


def test_target_scope_resolution_from_semantic_decision_normalizes_scope():
    scope = proposal_compiler.resolve_fix_proposal_target_scope_from_decision(
        _Decision(target_strategies="fill_missing_count", target_issue_codes=["count_shortage"]),
        allowed_action_families={"preview_fix_proposal"},
        confidence_threshold=0.8,
    )

    assert scope.source == "semantic_decision_scope"
    assert scope.explicit is True
    assert scope.target_strategies == ["fill_missing_count"]
    assert scope.target_issue_codes == ["count_shortage"]


def test_target_scope_resolution_from_semantic_decision_marks_no_scope():
    scope = proposal_compiler.resolve_fix_proposal_target_scope_from_decision(
        _Decision(action_family="query_state", target_strategies="fill_missing_count"),
        allowed_action_families={"preview_fix_proposal"},
        confidence_threshold=0.8,
    )

    assert scope.source == "semantic_decision_no_scope"
    assert scope.explicit is False
    assert scope.target_strategies == []
    assert scope.target_issue_codes == []


def test_semantic_decision_issue_codes_are_filtered_by_available_fix_proposals():
    context = {
        "fixProposals": {
            "proposals": [
                _proposal("fp-count", strategy="fill_missing_count", issue_codes=["count_shortage"]),
                _proposal("fp-gap", strategy="fill_probability_gap", issue_codes=["probability_gap"]),
            ]
        }
    }

    result = proposal_compiler.semantic_decision_target_issue_codes_for_context(
        _Decision(
            target_strategies=["fill_missing_count"],
            target_issue_codes=["count_shortage", "not_available"],
        ),
        allowed_action_families={"preview_fix_proposal"},
        confidence_threshold=0.8,
        target_strategies=["fill_missing_count"],
        context=context,
    )

    assert result == ["count_shortage"]


def test_semantic_decision_issue_codes_drop_when_strategy_conflicts_with_expected_target():
    context = {
        "fixProposals": {
            "proposals": [
                _proposal("fp-count", strategy="fill_missing_count", issue_codes=["count_shortage"]),
            ]
        }
    }

    result = proposal_compiler.semantic_decision_target_issue_codes_for_context(
        _Decision(
            target_strategies=["fill_probability_gap"],
            target_issue_codes=["count_shortage"],
        ),
        allowed_action_families={"preview_fix_proposal"},
        confidence_threshold=0.8,
        target_strategies=["fill_missing_count"],
        context=context,
    )

    assert result == []


def _review_context(*proposals):
    return {
        "lastActionFamily": "review_plan",
        "lastResultKind": "review_result",
        "fixProposals": {
            "readyCount": len(proposals),
            "blockedCount": 0,
            "previewOnlyCount": 0,
            "proposals": list(proposals),
        },
    }


def test_compile_runtime_review_refocus_source_builds_targeted_review_payload():
    latest_review = {
        "action_family": "review_plan",
        "result_kind": "review_result",
        "facts": {"risk_count": 1},
    }

    source = proposal_compiler.compile_runtime_review_refocus_source(
        content="一年学费最多两三万，方案里高收费多吗",
        latest_review_result=latest_review,
        recent_plan_context=_review_context(_proposal("fp-fee", strategy="replace_risk_items")),
        decision=_Decision(
            action_family="review_plan",
            target_issue_codes=["high_tuition", "cooperative_program"],
            target_strategies=["replace_risk_items"],
            reply_focus=["target_issue_only"],
        ),
        planning_version=18,
    )

    assert source.matched is True
    assert source.route == "review_target_refocus"
    assert source.side_effect == "readonly"
    assert source.target_issue_codes == ["high_tuition", "cooperative_program"]
    assert source.plan_payload == {
        "stage": "review",
        "action_family": "review_plan",
        "user_goal": "一年学费最多两三万，方案里高收费多吗",
        "requires_confirmation": False,
        "target_issue_codes": ["high_tuition", "cooperative_program"],
        "reply_focus": ["target_issue_only"],
        "target_strategies": ["replace_risk_items"],
        "planning_version": 18,
    }
    assert source.evidence_plan["trigger"] == "review_target_refocus"
    assert source.evidence_plan["sourceInputs"] == [
        "latest_review_result",
        "plan_semantic_action",
    ]


def test_compile_runtime_review_refocus_source_blocks_already_targeted_review():
    latest_review = {
        "action_family": "review_plan",
        "result_kind": "review_result",
        "facts": {"target_issue_codes": ["high_tuition"]},
    }

    source = proposal_compiler.compile_runtime_review_refocus_source(
        content="再看高收费",
        latest_review_result=latest_review,
        recent_plan_context={},
        decision=_Decision(
            action_family="review_plan",
            target_issue_codes=["high_tuition"],
            reply_focus=["target_issue_only"],
        ),
    )

    assert source.matched is False
    assert source.blocking_reasons == ["review_result_already_targeted"]


def test_compile_runtime_review_to_fix_preview_source_builds_preview_payload_with_target_scope():
    context = _review_context(
        _proposal("fp-fee", strategy="replace_risk_items", issue_codes=["high_tuition"]),
    )

    source = proposal_compiler.compile_runtime_review_to_fix_preview_source(
        content="高收费的先给我看处理预览",
        current_plan_context=context,
        decision=_Decision(
            action_family="preview_fix_proposal",
            target_strategies=["replace_risk_items"],
            target_issue_codes=["high_tuition"],
        ),
        planning_version=18,
    )

    assert source.matched is True
    assert source.route == "post_review_fix_preview"
    assert source.side_effect == "plan_preview"
    assert source.target_scope_explicit is True
    assert source.plan_payload == {
        "stage": "apply",
        "action_family": "preview_fix_proposal",
        "user_goal": "高收费的先给我看处理预览",
        "requires_confirmation": False,
        "target_strategies": ["replace_risk_items"],
        "target_issue_codes": ["high_tuition"],
        "planning_version": 18,
    }


def test_compile_runtime_review_to_fix_preview_source_blocks_missing_review_proposals():
    source = proposal_compiler.compile_runtime_review_to_fix_preview_source(
        content="给我看处理预览",
        current_plan_context={
            "lastActionFamily": "review_plan",
            "lastResultKind": "review_result",
            "fixProposals": {},
        },
        decision=_Decision(action_family="preview_fix_proposal"),
    )

    assert source.matched is False
    assert source.blocking_reasons == ["missing_review_fix_proposals"]


def test_compile_runtime_review_to_fix_preview_source_blocks_low_confidence_decision():
    source = proposal_compiler.compile_runtime_review_to_fix_preview_source(
        content="给我看处理预览",
        current_plan_context=_review_context(_proposal("fp-fee", strategy="replace_risk_items")),
        decision=_Decision(action_family="preview_fix_proposal", confidence=0.2),
    )

    assert source.matched is False
    assert source.blocking_reasons == ["semantic_decision_not_fix_preview"]


def test_resolve_plan_confirmation_candidate_allows_apply_payload_and_version_guard():
    candidate = {
        "action_family": "add_units",
        "plan_payload": json.dumps(
            {
                "stage": "apply",
                "action_family": "add_units",
                "requires_confirmation": False,
                "target_view": "ordered",
                "planning_version": 12,
                "atomic_actions": [{"action_type": "add_units", "volunteer_ids": ["v1"]}],
            },
            ensure_ascii=False,
        ),
    }

    resolution = proposal_compiler.resolve_plan_confirmation_candidate(candidate)

    assert resolution.allowed is True
    assert resolution.action_family == "add_units"
    assert resolution.target_view == "ordered"
    assert resolution.source_version_guard == 12
    assert resolution.blocking_reasons == []


def test_compile_runtime_plan_confirmation_source_builds_compiled_plan_candidate():
    candidate = {
        "action_family": "remove_units",
        "plan_payload": json.dumps(
            {
                "stage": "apply",
                "action_family": "remove_units",
                "requires_confirmation": False,
                "planning_version": 9,
                "atomic_actions": [{"action_type": "remove_units", "volunteer_ids": ["v1"]}],
            },
            ensure_ascii=False,
        ),
        "intent_update": {"selected": [{"major_intents": {"negative_level3": ["护理学"]}}]},
    }

    source = proposal_compiler.compile_runtime_plan_confirmation_source(
        session_id="s1",
        confirmation_candidate=candidate,
        source="unit_test",
        summary="移出护理学",
    )

    assert source.compiled is not None
    assert source.blocking_reasons == []
    assert source.compiled["pendingType"] == "plan_mutation"
    assert source.compiled["executionPayload"]["actionFamily"] == "remove_units"
    assert source.compiled["intentPayload"]["selected"] == [
        {"major_intents": {"negative_level3": ["护理学"]}}
    ]
    assert source.compiled["proposalCandidates"][0]["sourceVersionGuard"] == 9
    assert proposal_compiler.plan_sink_contract(source.compiled) == (True, [])


def test_compile_runtime_plan_confirmation_source_blocks_fix_proposal_in_plain_plan_sink():
    candidate = {
        "action_family": "apply_fix_proposal",
        "plan_payload": json.dumps(
            {
                "stage": "apply",
                "action_family": "apply_fix_proposal",
                "requires_confirmation": False,
                "planning_version": 7,
            },
            ensure_ascii=False,
        ),
    }

    source = proposal_compiler.compile_runtime_plan_confirmation_source(
        session_id="s1",
        confirmation_candidate=candidate,
        source="unit_test",
        summary="处理建议",
    )

    assert source.compiled is None
    assert source.blocking_reasons == ["plan_sink_rejects_fix_proposal_candidate"]


def test_compile_apply_then_generate_plan_source_builds_generate_plan_candidate():
    source = proposal_compiler.compile_apply_then_generate_plan_source(
        session_id="s-g14",
        user_prompt="现在基于这些出方案",
        pending_state={
            "pendingId": "pending-intent-g14",
            "kind": "intent_change",
            "status": "applied",
        },
        source_version_guard=19,
    )

    assert source.compiled is not None
    assert source.confirmation_candidate is not None
    assert source.blocking_reasons == []
    assert source.compiled["pendingType"] == "plan_mutation"
    assert source.compiled["executionPayload"]["actionFamily"] == "generate_plan"
    assert source.compiled["executionPayload"]["targetView"] == "ordered"
    assert proposal_compiler.plan_sink_contract(source.compiled) == (True, [])
    payload = json.loads(source.confirmation_candidate["plan_payload"])
    assert payload["stage"] == "apply"
    assert payload["action_family"] == "generate_plan"
    assert payload["planning_version"] == 19
    assert payload["requires_confirmation"] is False
    assert payload["facts"]["composite_source"] == "apply_pending_then_new_request"


def test_plan_candidate_resolution_blocks_action_family_mismatch():
    candidate = {
        "action_family": "add_units",
        "plan_payload": json.dumps(
            {
                "stage": "apply",
                "action_family": "remove_units",
                "requires_confirmation": False,
                "planning_version": 7,
                "atomic_actions": [{"action_type": "remove_units", "volunteer_ids": ["v1"]}],
            },
            ensure_ascii=False,
        ),
    }

    source = proposal_compiler.compile_runtime_plan_confirmation_source(
        session_id="s1",
        confirmation_candidate=candidate,
        source="unit_test",
        summary="动作族冲突",
    )

    assert source.compiled is None
    assert source.blocking_reasons == ["plan_candidate_action_family_mismatch"]


def test_plan_candidate_resolution_blocks_non_apply_stage():
    candidate = {
        "action_family": "add_units",
        "plan_payload": json.dumps(
            {
                "stage": "preview",
                "action_family": "add_units",
                "requires_confirmation": True,
                "planning_version": 7,
                "atomic_actions": [{"action_type": "add_units", "volunteer_ids": ["v1"]}],
            },
            ensure_ascii=False,
        ),
    }

    source = proposal_compiler.compile_runtime_plan_confirmation_source(
        session_id="s1",
        confirmation_candidate=candidate,
        source="unit_test",
        summary="预览不能直接入 sink",
    )

    assert source.compiled is None
    assert source.blocking_reasons == [
        "plan_candidate_requires_apply_stage",
        "plan_candidate_apply_payload_must_not_require_confirmation",
    ]


def test_pending_turn_resolution_compiles_readonly_impact_from_turn_decision():
    resolution = proposal_compiler.resolve_pending_turn_action(
        "先不确认，看看这个偏好会影响当前方案吗",
        pending_state={"status": "active", "kind": "intent_change"},
    )

    assert resolution.action == "none"
    assert resolution.side_effect == "none"
    assert resolution.pending_type == "intent"
    assert resolution.requires_model_decision is True

    compiled = proposal_compiler.compile_runtime_pending_turn_decision_source(
        "先不确认，看看这个偏好会影响当前方案吗",
        pending_state={"status": "active", "kind": "intent_change"},
        turn_decision=_TurnDecision(
            task_layer="pending",
            side_effect="readonly_while_pending",
            scope_anchor="pending_reference",
            scenario="pending_impact_query",
            confidence=0.92,
        ),
    )

    assert compiled.action == "ask_pending_impact"
    assert compiled.side_effect == "readonly_while_pending"
    assert compiled.pending_type == "intent"
    assert compiled.requires_model_decision is False


def test_post_apply_readonly_evidence_plan_uses_structured_target_issues():
    evidence_plan = proposal_compiler.compile_post_apply_readonly_evidence_plan(
        "删完了再看还剩多少，梯度还稳不稳",
        pending_state={"status": "active", "kind": "plan_mutation"},
        target_issues=["remaining_count", "tier_distribution", "risk_review"],
    )

    assert evidence_plan == {
        "type": "EvidencePlan",
        "trigger": "apply_pending_then_readonly",
        "scopeAnchor": "current_plan",
        "targetIssues": ["remaining_count", "tier_distribution", "risk_review"],
        "requiredInputs": ["active_pending", "formal_ordered_plan_after_apply"],
        "steps": [
            {
                "step": "apply_existing_pending",
                "purpose": "apply_active_pending_before_readonly_followup",
                "requiresAppliedPending": True,
            },
            {
                "step": "read_latest_plan_summary",
                "purpose": "answer_post_apply_plan_state",
                "requiresAppliedPending": True,
            },
            {
                "step": "review_tier_gradient",
                "purpose": "answer_post_apply_risk",
                "requiresAppliedPending": True,
            },
        ],
        "workspaceRefreshTargets": ["ordered", "review"],
        "toolBudget": {"maxToolCalls": 3, "batchPreferred": True},
        "noResultReason": "post_apply_plan_requires_refreshed_evidence",
        "mustNotAnswerWithoutEvidence": True,
    }


def test_compile_readonly_workspace_evidence_plan_from_prior_plan_attempt():
    source = proposal_compiler.compile_runtime_readonly_workspace_evidence_plan_source(
        current_result={
            "action_family": "query_state",
            "result_kind": "status_overview",
            "reply_focus": ["current_state", "tier_distribution"],
            "facts": {"risk_count": 1},
        },
        prior_plan_attempt_result={
            "action_family": "remove_units",
            "result_kind": "no_change",
        },
    )

    assert source.matched is True
    assert source.route == "post_plan_attempt_readonly_workspace_evidence"
    assert source.workspace_refresh_targets == ["ordered", "review"]
    assert source.evidence_plan["trigger"] == "post_plan_attempt_readonly_status_overview"
    assert source.evidence_plan["sourceInputs"] == [
        "current_execute_plan_action_result",
        "prior_plan_mutation_attempt_result",
    ]
    assert source.evidence_plan["priorAttempt"] == {
        "actionFamily": "remove_units",
        "resultKind": "no_change",
    }


def test_compile_readonly_workspace_evidence_plan_blocks_apply_pending_without_pending_entrypoint():
    source = proposal_compiler.compile_runtime_readonly_workspace_evidence_plan_source(
        current_result={
            "action_family": "query_state",
            "result_kind": "status_overview",
            "reply_focus": ["current_state"],
            "facts": {},
        },
        turn_decision=_TurnDecision(
            task_layer="mixed",
            side_effect="apply_pending_then_readonly",
            scope_anchor="current_plan",
            scenario="apply_pending_then_readonly_query",
            confidence=0.95,
        ),
    )

    assert source.matched is False
    assert "apply_pending_then_readonly_requires_active_pending_entrypoint" in source.blocking_reasons
    assert "missing_prior_plan_mutation_attempt" in source.blocking_reasons
    assert source.workspace_refresh_targets == []


def test_compile_workspace_presentation_refreshes_mutating_preview_result():
    source = proposal_compiler.compile_runtime_workspace_presentation_source(
        execute_plan_results=[
            {
                "applied": False,
                "action_family": "move_unit",
                "stage": "preview",
                "result_kind": "preview_only",
                "workspace_refresh_targets": ["ordered", "review"],
            }
        ]
    )

    assert source.matched is True
    assert source.route == "execute_plan_result_refresh"
    assert source.workspace_refresh_targets == ["ordered", "review"]
    assert source.workspace_view_targets == []
    assert source.result_is_readonly_no_refresh is False


def test_compile_workspace_presentation_blocks_readonly_review_refresh():
    source = proposal_compiler.compile_runtime_workspace_presentation_source(
        execute_plan_results=[
            {
                "applied": True,
                "action_family": "review_plan",
                "stage": "review",
                "result_kind": "review_result",
                "workspace_refresh_targets": ["review"],
            }
        ]
    )

    assert source.matched is True
    assert source.route == "execute_plan_result_no_refresh"
    assert source.workspace_refresh_targets == []
    assert source.result_is_readonly_no_refresh is True


def test_compile_workspace_presentation_strips_explanation_only_initial_refresh():
    source = proposal_compiler.compile_runtime_workspace_presentation_source(
        initial_refresh_targets=["ordered", "review"],
        execute_plan_results=[
            {
                "applied": False,
                "action_family": "preview_fix_proposal",
                "stage": "preview",
                "result_kind": "fix_proposal_preview",
                "workspace_refresh_targets": ["ordered", "review"],
            }
        ],
    )

    assert source.matched is True
    assert source.route == "explanation_only_result_no_refresh"
    assert source.workspace_refresh_targets == []
    assert source.latest_result_is_explanation_only is True


def test_compile_workspace_presentation_keeps_explanation_refresh_when_explicitly_allowed():
    source = proposal_compiler.compile_runtime_workspace_presentation_source(
        initial_refresh_targets=["review"],
        execute_plan_results=[
            {
                "applied": False,
                "action_family": "analyze_adjustment",
                "stage": "analysis",
                "result_kind": "adjustment_analysis",
            }
        ],
        allow_explanation_refresh=True,
    )

    assert source.matched is True
    assert source.workspace_refresh_targets == ["review"]
    assert source.latest_result_is_explanation_only is True


def test_compile_workspace_presentation_uses_structured_tool_call_fallback():
    source = proposal_compiler.compile_runtime_workspace_presentation_source(
        tool_call_names=["execute_plan_action"],
        execute_plan_action_call_families=["move_ordered_unit"],
    )

    assert source.matched is True
    assert source.route == "execute_plan_call_family"
    assert source.workspace_refresh_targets == ["ordered", "review"]


def test_compile_workspace_presentation_opens_view_after_prior_plan_attempt():
    source = proposal_compiler.compile_runtime_workspace_presentation_source(
        execute_plan_results=[
            {
                "action_family": "query_state",
                "result_kind": "status_overview",
                "reply_focus": ["current_state", "tier_distribution"],
                "facts": {"risk_count": 1},
            }
        ],
        include_result_view_targets=False,
        include_post_plan_attempt_view=True,
        prior_plan_attempt_result={
            "action_family": "remove_units",
            "result_kind": "no_change",
        },
    )

    assert source.matched is True
    assert source.workspace_refresh_targets == []
    assert source.workspace_view_targets == ["ordered", "review"]
    assert source.evidence_plan["trigger"] == "post_plan_attempt_readonly_status_overview"


def test_compile_semantic_plan_display_confirmation_card():
    source = proposal_compiler.compile_runtime_semantic_plan_display_source(
        action_family="preview_fix_proposal",
        result={"result_kind": "fix_proposal_preview"},
        pending_card_created=True,
    )

    assert source.matched is True
    assert source.route == "semantic_plan_confirmation_card"
    assert source.display_payload == {
        "presentation": "confirmation_card",
        "pendingCardType": "pendingConfirmationCard",
    }
    assert source.reply_plan["focus"] == ["confirmable_plan_mutation"]


def test_compile_semantic_plan_display_framework_conditional_options():
    source = proposal_compiler.compile_runtime_semantic_plan_display_source(
        action_family="review_plan",
        result={"result_kind": "review_result", "facts": {}},
        pending_card_created=False,
        prefer_conditional_options=True,
    )

    assert source.matched is True
    assert source.route == "semantic_plan_conditional_options"
    assert source.display_payload == {"presentation": "conditional_options"}


def test_compile_semantic_plan_display_conditional_options_from_fix_proposals():
    source = proposal_compiler.compile_runtime_semantic_plan_display_source(
        action_family="analyze_adjustment",
        result={
            "result_kind": "adjustment_analysis",
            "facts": {
                "fix_proposals": {
                    "blocked_count": 1,
                    "proposals": [{"proposal_id": "fp_1", "status": "blocked"}],
                }
            },
        },
        pending_card_created=False,
    )

    assert source.matched is True
    assert source.display_payload == {"presentation": "conditional_options"}
    assert source.reply_plan == {
        "mode": ["conditional_options"],
        "focus": ["review_or_repair_options"],
    }


def test_compile_semantic_plan_display_readonly_answer_without_options():
    source = proposal_compiler.compile_runtime_semantic_plan_display_source(
        action_family="review_plan",
        result={"result_kind": "review_result", "facts": {}},
        pending_card_created=False,
    )

    assert source.matched is True
    assert source.route == "semantic_plan_readonly_answer"
    assert source.display_payload == {"presentation": "readonly_answer"}


def test_compile_reply_guard_blocks_unbacked_plan_confirmation():
    source = proposal_compiler.compile_runtime_reply_guard_source(
        reply=(
            "已在当前方案里定位到汉语言文学相关志愿。\n\n"
            "确认后会执行以下操作：将这些志愿从当前方案中移除。"
        ),
        guard_context="plan_confirmation",
    )

    assert source.matched is True
    assert source.route == "unbacked_plan_confirmation_reply_guard"
    assert source.guard_type == "unbacked_plan_confirmation"
    assert "确认后会执行" not in source.stripped_reply
    assert source.display_payload == {"presentation": "readonly_boundary"}


def test_compile_reply_guard_ignores_intent_only_confirmation_copy():
    source = proposal_compiler.compile_runtime_reply_guard_source(
        reply="我可以把法学作为后续报考参考整理出来，请确认是否采纳这条偏好。",
        guard_context="plan_confirmation",
    )

    assert source.matched is False
    assert "reply_guard_not_needed" in source.blocking_reasons


def test_compile_reply_guard_detects_plan_preview_without_card():
    source = proposal_compiler.compile_runtime_reply_guard_source(
        reply="已列出调整预览：替换当前方案里的高收费志愿。确认前不会改动当前方案。",
        guard_context="plan_preview_without_card",
    )

    assert source.matched is True
    assert source.route == "plan_preview_without_card_reply_guard"
    assert source.guard_type == "plan_preview_without_card"


def test_compile_reply_guard_detects_recorded_intent_without_pending():
    source = proposal_compiler.compile_runtime_reply_guard_source(
        reply="已把优先网络与新媒体作为后续报考参考记下来，后续生成或调整方案会优先保证。",
        guard_context="recorded_intent_without_pending",
    )

    assert source.matched is True
    assert source.route == "recorded_intent_without_pending_reply_guard"
    assert source.reply_plan["focus"] == ["no_pending_intent_boundary"]


def test_compile_reply_guard_detects_no_tool_action_boundary():
    source = proposal_compiler.compile_runtime_reply_guard_source(
        reply="这轮还没有生成可执行的调整内容，所以不会改动当前方案。",
        guard_context="no_tool_action_boundary",
    )

    assert source.matched is True
    assert source.route == "no_tool_action_boundary_reply_guard"


def test_pending_turn_resolution_leaves_apply_then_new_plan_to_structured_decision():
    resolution = proposal_compiler.resolve_pending_turn_action(
        "现在基于这些出方案",
        pending_state={"status": "active", "kind": "intent_change"},
    )

    assert resolution.action == "none"
    assert resolution.side_effect == "none"
    assert resolution.pending_type == "intent"
    assert resolution.requires_model_decision is True


def test_pending_turn_resolution_routes_plan_short_confirmation_without_model_decision():
    resolution = proposal_compiler.resolve_pending_turn_action(
        "确认执行",
        pending_state={"status": "active", "kind": "plan_mutation"},
    )

    assert resolution.action == "confirm_pending"
    assert resolution.side_effect == "apply_existing_pending"
    assert resolution.pending_type == "plan"
    assert resolution.requires_model_decision is False


def test_pending_turn_resolution_routes_plan_action_scoped_confirmation_without_model_decision():
    pairs = (
        ("确认生成", "generate_plan"),
        ("确认生成方案", "generate_plan"),
        ("确认移动专业组", "move_ordered_unit"),
        ("确认删除", "remove_units"),
        ("确认加入", "add_units"),
        ("确认重排方案", "regenerate_order"),
    )
    for prompt, action_family in pairs:
        resolution = proposal_compiler.resolve_pending_turn_action(
            prompt,
            pending_state={
                "status": "active",
                "kind": "plan_mutation",
                "actionFamily": action_family,
            },
        )

        assert resolution.action == "confirm_pending"
        assert resolution.side_effect == "apply_existing_pending"
        assert resolution.pending_type == "plan"
        assert resolution.requires_model_decision is False


def test_pending_turn_resolution_routes_action_scoped_confirmation_from_plan_payload():
    resolution = proposal_compiler.resolve_pending_turn_action(
        "确认生成方案",
        pending_state={
            "status": "active",
            "kind": "plan_mutation",
            "executionPayload": {
                "planPayload": json.dumps({"action_family": "generate_plan"}),
            },
        },
    )

    assert resolution.action == "confirm_pending"
    assert resolution.side_effect == "apply_existing_pending"
    assert resolution.pending_type == "plan"
    assert resolution.requires_model_decision is False


def test_pending_turn_resolution_does_not_apply_mismatched_plan_action_confirmation():
    resolution = proposal_compiler.resolve_pending_turn_action(
        "确认生成方案",
        pending_state={
            "status": "active",
            "kind": "plan_mutation",
            "actionFamily": "remove_units",
        },
    )

    assert resolution.action != "confirm_pending"
    assert resolution.side_effect != "apply_existing_pending"
    assert resolution.pending_type == "plan"


def test_pending_turn_resolution_does_not_apply_intent_pending_for_plan_action_confirmation():
    resolution = proposal_compiler.resolve_pending_turn_action(
        "确认生成",
        pending_state={"status": "active", "kind": "intent_change"},
    )

    assert resolution.action == "none"
    assert resolution.pending_type == "intent"
    assert resolution.requires_model_decision is True


def test_pending_turn_resolution_routes_intent_short_confirmation_without_model_decision():
    resolution = proposal_compiler.resolve_pending_turn_action(
        "确认这个偏好",
        pending_state={"status": "active", "kind": "intent_change"},
    )

    assert resolution.action == "confirm_pending"
    assert resolution.side_effect == "apply_existing_pending"
    assert resolution.pending_type == "intent"
    assert resolution.requires_model_decision is False


def test_pending_turn_resolution_does_not_confirm_readonly_closure_ack():
    resolution = proposal_compiler.resolve_pending_turn_action(
        "先按这个吧",
        pending_state={"status": "active", "kind": "plan_mutation"},
    )

    assert resolution.action == "none"
    assert resolution.requires_model_decision is True


def test_pending_turn_resolution_does_not_cancel_soft_non_execution_query():
    resolution = proposal_compiler.resolve_pending_turn_action(
        "先不执行，看看这次调整会影响哪些候选",
        pending_state={"status": "active", "kind": "plan_mutation"},
    )

    assert resolution.action == "none"
    assert resolution.side_effect == "none"
    assert resolution.requires_model_decision is True


def test_runtime_plan_query_profile_compiler_builds_tuition_query_payload():
    compiled = proposal_compiler.compile_runtime_plan_query_profile_source(
        content="两万以上的都算贵 帮我看看有几个",
        query_profile={
            "queryType": "readonly_plan_query",
            "dimensions": ["tuition"],
            "filters": {"limit": 5, "min_tuition_per_year": 20000},
            "projection": {"mode": "count_with_examples", "limit": 5},
            "replyFocus": ["ordered_snapshot", "local_plan_query", "plan_filter_query", "tuition"],
        },
        planning_version=12,
        pending_exists=True,
    )

    assert compiled.matched is True
    assert compiled.route == "readonly_plan_query"
    assert compiled.side_effect == "readonly_while_pending"
    assert compiled.plan_query_dsl["filters"] == {"limit": 5, "min_tuition_per_year": 20000}
    assert compiled.plan_payload["atomic_actions"][0]["filters"] == {"limit": 5, "min_tuition_per_year": 20000}


def test_runtime_plan_query_profile_compiler_builds_candidate_slice_query_payload():
    compiled = proposal_compiler.compile_runtime_plan_query_profile_source(
        content="候选里稳档的有哪些",
        query_profile={
            "queryType": "readonly_plan_slice_query",
            "scopeAnchor": "candidate_pool",
            "dimensions": ["tier_segment"],
            "filters": {
                "limit": 5,
                "tier": "稳",
                "slice": "head",
                "include_fields": ["school", "major", "admission_probability"],
            },
            "projection": {
                "mode": "slice_examples",
                "limit": 5,
                "fields": ["school", "major", "admission_probability"],
            },
            "replyFocus": ["candidate_snapshot", "local_candidate_query", "candidate_slice_query"],
        },
        planning_version=12,
    )

    assert compiled.matched is True
    assert compiled.route == "readonly_plan_slice_query"
    assert compiled.action_family == "query_candidates"
    assert compiled.plan_query_dsl == {
        "type": "PlanQuery",
        "scopeAnchor": "candidate_pool",
        "sideEffect": "readonly",
        "queryType": "readonly_plan_slice_query",
        "dimensions": ["tier_segment"],
        "filters": {
            "limit": 5,
            "tier": "稳",
            "slice": "head",
            "include_fields": ["school", "major", "admission_probability"],
        },
        "projection": {
            "mode": "slice_examples",
            "limit": 5,
            "fields": ["school", "major", "admission_probability"],
        },
        "sourceVersionGuard": 12,
    }
    payload = compiled.plan_payload
    assert payload["action_family"] == "query_candidates"
    assert payload["atomic_actions"][0]["action_type"] == "query_candidates"
    assert payload["atomic_actions"][0]["filters"]["tier"] == "稳"
    assert "candidate_slice_query" in payload["reply_focus"]


def test_runtime_plan_query_profile_compiler_builds_count_summary_payload_from_structured_profile():
    compiled = proposal_compiler.compile_runtime_plan_query_profile_source(
        content="任意用户原话不参与编译判断",
        query_profile={
            "queryType": "readonly_plan_query",
            "scopeAnchor": "current_plan",
            "dimensions": ["count_summary"],
            "filters": {"limit": 5},
            "projection": {"mode": "count_summary", "limit": 5},
            "replyFocus": ["current_state", "count_summary"],
        },
        planning_version=13,
    )

    assert compiled.matched is True
    assert compiled.route == "readonly_plan_query"
    assert compiled.action_family == "query_state"
    assert compiled.plan_query_dsl["dimensions"] == ["count_summary"]
    assert compiled.plan_query_dsl["projection"]["mode"] == "count_summary"
    assert compiled.plan_payload["action_family"] == "query_state"
    assert compiled.plan_payload["facts"]["plan_query_dsl"]["projection"]["mode"] == "count_summary"


def test_runtime_plan_query_profile_compiler_builds_school_presence_payload_from_condition():
    compiled = proposal_compiler.compile_runtime_plan_query_profile_source(
        content="任意用户原话不参与编译判断",
        query_profile={
            "queryType": "readonly_plan_query",
            "scopeAnchor": "current_plan",
            "dimensions": ["school_presence"],
            "condition": {"filters": {"schoolKeywords": ["南京航空航天大学"]}},
            "filters": {"limit": 5},
            "projection": {"mode": "school_presence", "limit": 5},
            "replyFocus": ["ordered_snapshot", "local_plan_query", "school_presence_query"],
        },
        planning_version=13,
    )

    assert compiled.matched is True
    assert compiled.action_family == "query_ordered"
    assert compiled.plan_query_dsl["filters"]["school_keyword"] == "南京航空航天大学"
    assert compiled.plan_payload["atomic_actions"][0]["filters"]["school_keyword"] == "南京航空航天大学"
    assert "school_presence_query" in compiled.plan_payload["reply_focus"]


def test_runtime_plan_query_profile_compiler_resolves_pending_major_reference_from_state():
    compiled = proposal_compiler.compile_runtime_plan_query_profile_source(
        content="先不确认，当前方案里有没有相关专业",
        query_profile={
            "queryType": "readonly_pending_reference_query",
            "dimensions": ["pending_reference"],
            "filters": {"limit": 5},
            "projection": {"mode": "examples", "limit": 5},
            "pendingReferenceType": "major",
            "replyFocus": ["ordered_snapshot", "local_plan_query", "pending_reference_query"],
        },
        pending_exists=True,
        pending_state={
            "kind": "intent_change",
            "status": "active",
            "executionPayload": {
                "selectedData": {
                    "entityProfile": {"majorValues": ["网络与新媒体"]},
                    "selected": [{"major_intents": {"level3": ["网络与新媒体"]}}],
                },
                "merged": {"major_intents": {"level3": ["网络与新媒体"]}},
            },
        },
    )

    assert compiled.matched is True
    assert compiled.route == "readonly_pending_reference_query"
    assert compiled.plan_query_dsl["filters"] == {"limit": 5, "major_keyword": "网络与新媒体"}
    assert compiled.plan_payload["atomic_actions"][0]["filters"]["major_keyword"] == "网络与新媒体"


def test_runtime_plan_query_profile_compiler_rejects_none_profile():
    compiled = proposal_compiler.compile_runtime_plan_query_profile_source(
        content="删掉一个高收费",
        query_profile={"queryType": "none", "confidence": 0.9},
    )

    assert compiled.matched is False
    assert compiled.blocking_reasons == ["unsupported_plan_query_profile_type"]


def test_runtime_plan_query_profile_compiler_rejects_mutation_as_none_profile():
    compiled = proposal_compiler.compile_runtime_plan_query_profile_source(
        content="那把两万以上且跟我意向不沾边的先删掉",
        query_profile={"queryType": "none", "confidence": 0.9},
        planning_version=12,
    )

    assert compiled.matched is False
    assert compiled.blocking_reasons == ["unsupported_plan_query_profile_type"]


def test_pending_turn_resolution_allows_new_intent_exclusion_with_active_intent_pending():
    resolution = proposal_compiler.resolve_pending_turn_action(
        "把生物医学工程和智能医学工程加意向 排除临床医学和口腔",
        pending_state={"status": "active", "kind": "intent_change"},
    )

    assert resolution.action == "none"
    assert resolution.side_effect == "none"
    assert resolution.requires_model_decision is True


def test_pending_turn_resolution_still_cancels_explicit_pending_reject():
    resolution = proposal_compiler.resolve_pending_turn_action(
        "取消这次待采纳内容",
        pending_state={"status": "active", "kind": "intent_change"},
    )

    assert resolution.action == "reject_pending"
    assert resolution.side_effect == "cancel_existing_pending"
    assert resolution.requires_model_decision is False


def test_pending_turn_resolution_leaves_new_mutation_conflict_to_structured_decision():
    resolution = proposal_compiler.resolve_pending_turn_action(
        "这个方案还是不行，只要医学",
        pending_state={"status": "active", "kind": "intent_change"},
    )

    assert resolution.action == "none"
    assert resolution.side_effect == "none"
    assert resolution.pending_type == "intent"
    assert resolution.requires_model_decision is True
    assert resolution.blocking_reasons == []


def test_pending_turn_resolution_allows_new_explicit_intent_with_active_intent_pending():
    resolution = proposal_compiler.resolve_pending_turn_action(
        "把华中科技大学加到意向",
        pending_state={"status": "active", "kind": "intent_change"},
    )

    assert resolution.action == "none"
    assert resolution.side_effect == "none"
    assert resolution.pending_type == "intent"
    assert resolution.requires_model_decision is True
    assert resolution.blocking_reasons == []


def test_pending_turn_resolution_allows_soft_discussion_with_active_pending():
    resolution = proposal_compiler.resolve_pending_turn_action(
        "为什么只保留医学会影响当前方案",
        pending_state={"status": "active", "kind": "intent_change"},
    )

    assert resolution.action == "none"
    assert resolution.side_effect == "none"
    assert resolution.requires_model_decision is True


def test_pending_turn_resolution_blocks_without_active_pending():
    resolution = proposal_compiler.resolve_pending_turn_action(
        "确认执行",
        pending_state=None,
    )

    assert resolution.action == "none"
    assert resolution.requires_model_decision is False
    assert resolution.blocking_reasons == ["missing_active_pending"]


def test_needs_plan_first_guard_blocks_current_plan_reference_without_formal_plan():
    resolution = proposal_compiler.resolve_needs_plan_first_guard(
        "刚那个方案民办能少点不",
        planning_summary={"ordered_total": 0, "working_total": 0},
    )

    assert resolution.side_effect == "needs_plan_first"
    assert resolution.reference_resolution == "no_referent"
    assert resolution.requires_model_decision is False
    assert resolution.target_issues == ["college_type"]
    assert resolution.blocking_reasons == ["missing_formal_plan"]


def test_no_formal_plan_review_boundary_blocks_special_path_review_generation():
    resolution = proposal_compiler.resolve_no_formal_plan_review_boundary(
        "现在这版强基+普通批方案合理不",
        planning_summary={"orderedTotal": 0, "workingTotal": 0},
    )

    assert resolution.side_effect == "readonly"
    assert resolution.reference_resolution == "special_path_without_formal_plan"
    assert resolution.requires_model_decision is False
    assert resolution.reply_focus == ["strongbase", "regular_batch"]
    assert resolution.blocking_reasons == ["missing_formal_plan"]


def test_needs_plan_first_guard_allows_future_reference_without_current_plan():
    resolution = proposal_compiler.resolve_needs_plan_first_guard(
        "以后少推荐民办，优先公办",
        planning_summary={"ordered_total": 0, "working_total": 0},
    )

    assert resolution.side_effect == "none"
    assert resolution.requires_model_decision is True


def test_needs_plan_first_guard_allows_current_plan_when_plan_exists():
    resolution = proposal_compiler.resolve_needs_plan_first_guard(
        "方案里民办能少点不",
        planning_summary={"ordered_total": 30, "working_total": 0},
    )

    assert resolution.side_effect == "none"
    assert resolution.requires_model_decision is True


def test_no_active_pending_confirmation_guard_detects_short_confirmation():
    assert proposal_compiler.pending_turn_looks_no_active_pending_confirmation("确认执行") is True
    assert proposal_compiler.pending_turn_looks_no_active_pending_confirmation("确认这个偏好") is True
    assert proposal_compiler.pending_turn_looks_no_active_pending_confirmation("采纳这个") is True


def test_no_active_pending_confirmation_guard_ignores_readonly_closure_ack():
    assert proposal_compiler.pending_turn_looks_no_active_pending_confirmation("先按这个吧") is False


def test_compile_profile_change_replan_source_marks_current_profile_update_stale():
    source = proposal_compiler.compile_profile_change_replan_source(
        profile_scenario="current_student_update",
        proposed_profile={"score": "620", "province": "湖北", "subjectCombo": "物化生"},
        current_profile={"score": 548, "province": "湖南", "subjects": ["历史", "生物", "政治"]},
        planning_version=31,
    )

    assert source.matched is True
    assert source.route == "profile_change_replan_request"
    assert source.side_effect == "profile_change_replan"
    assert source.profile_change_dsl["type"] == "ProfileChangeReplan"
    assert source.profile_change_dsl["profileMode"] == "current_student_update"
    assert source.profile_change_dsl["proposedProfile"]["score"] == 620
    assert source.profile_change_dsl["proposedProfileSummary"] == "620分、湖北、物化生"
    assert source.profile_change_dsl["missingProfileFields"] == []
    assert source.profile_change_dsl["stalePlanPolicy"]["formalPlan"] == "preserve_as_old_until_recalculated"
    assert source.profile_change_dsl["sourceVersionGuard"] == 31
    assert "mark_existing_plan_stale_for_proposed_profile" in source.evidence_plan["steps"]


def test_compile_profile_change_replan_source_preserves_adhoc_as_non_mutating():
    source = proposal_compiler.compile_profile_change_replan_source(
        profile_scenario="adhoc_scenario",
        proposed_profile={"score": 515},
        current_profile={"score": 537},
        planning_version=7,
    )

    assert source.matched is True
    assert source.route == "profile_replan_adhoc_request"
    assert source.side_effect == "profile_replan_adhoc"
    assert source.profile_change_dsl["type"] == "ProfileReplanAdhoc"
    assert source.profile_change_dsl["stalePlanPolicy"]["formalPlan"] == "do_not_invalidate_current_plan"
    assert "do_not_update_profile" in source.profile_change_dsl["requiredAction"]


def test_compile_profile_change_replan_source_keeps_ambiguous_scope_non_mutating():
    source = proposal_compiler.compile_profile_change_replan_source(
        profile_scenario="ambiguous",
        proposed_profile={"rank": 24000, "province": "湖北"},
        current_profile={"score": 548},
    )

    assert source.matched is True
    assert source.side_effect == "profile_replan_ambiguous"
    assert source.profile_change_dsl["type"] == "ProfileReplanAmbiguous"
    assert "clarify_whether_to_update_current_student_profile" in source.profile_change_dsl["requiredAction"]
    assert source.profile_change_dsl["missingProfileFields"] == ["subjects"]


def test_compile_profile_change_replan_source_requires_structured_profile_values():
    source = proposal_compiler.compile_profile_change_replan_source(
        profile_scenario="current_student_update",
        proposed_profile={"score": 0, "province": "", "subjects": []},
    )

    assert source.matched is False
    assert source.blocking_reasons == ["missing_profile_change_values"]


def test_resolve_profile_change_replan_state_query_requires_structured_query_scenario():
    dsl = proposal_compiler.compile_profile_change_replan_source(
        profile_scenario="current_student_update",
        proposed_profile={"score": 620},
    ).profile_change_dsl

    no_query = proposal_compiler.resolve_profile_change_replan_state_query(
        profile_change_dsl=dsl,
        query_scenario="",
    )
    resolved = proposal_compiler.resolve_profile_change_replan_state_query(
        profile_change_dsl=dsl,
        query_scenario="profile_change_state_query",
    )

    assert no_query.matched is False
    assert no_query.blocking_reasons == ["missing_profile_state_query_intent"]
    assert resolved.matched is True
    assert resolved.route == "profile_change_stale_plan_state_query"
    assert resolved.side_effect == "readonly"


def _current_plan_atomic_turn_decision(**overrides):
    data = {
        "taskLayer": "plan",
        "sideEffect": "plan_preview",
        "scopeAnchor": "current_plan",
        "scenario": "atomic_mutation",
        "confidence": 0.95,
    }
    data.update(overrides)
    return data


def test_compile_current_plan_mutation_from_intent_preview_builds_remove_units_payload():
    source = proposal_compiler.compile_runtime_current_plan_mutation_from_intent_preview_source(
        content="不要这些专业",
        turn_decision=_current_plan_atomic_turn_decision(),
        merged_intent={
            "major_intents": {
                "negative_level3": ["英语"],
                "negative_level2": ["外国语言文学类"],
            }
        },
        intent_mode="constraint",
        constraint_intent_type="exclude_hard",
        summary="排除专业：英语",
        planning_version=4,
    )

    assert source.matched is True
    assert source.route == "current_plan_remove_preview"
    assert source.action_family == "remove_units"
    assert source.source_version_guard == 4
    assert source.mutation_dsl["type"] == "CurrentPlanMutation"
    assert source.mutation_dsl["selector"]["sourceMajorNames"] == ["英语", "外国语言文学类"]
    payload = source.plan_payload
    assert payload["stage"] == "preview"
    assert payload["action_family"] == "remove_units"
    assert payload["planning_version"] == 4
    assert payload["atomic_actions"][0]["filters"] == {
        "negative_level3": ["英语"],
        "negative_level2": ["外国语言文学类"],
    }
    assert payload["facts"]["currentPlanMutationDsl"]["actionFamily"] == "remove_units"


def test_compile_current_plan_mutation_blocks_future_reference_intent_scope():
    source = proposal_compiler.compile_runtime_current_plan_mutation_from_intent_preview_source(
        content="后面不要英语",
        turn_decision=_current_plan_atomic_turn_decision(scopeAnchor="future_reference"),
        merged_intent={"major_intents": {"negative_level3": ["英语"]}},
        intent_mode="constraint",
    )

    assert source.matched is False
    assert source.blocking_reasons == ["unsupported_current_plan_mutation_scope_anchor"]


def test_compile_current_plan_mutation_blocks_readonly_or_non_atomic_turn():
    source = proposal_compiler.compile_runtime_current_plan_mutation_from_intent_preview_source(
        content="看看英语相关的影响",
        turn_decision=_current_plan_atomic_turn_decision(sideEffect="readonly", scenario="plan_query"),
        merged_intent={"major_intents": {"negative_level3": ["英语"]}},
        intent_mode="constraint",
    )

    assert source.matched is False
    assert source.blocking_reasons == [
        "unsupported_current_plan_mutation_side_effect",
        "unsupported_current_plan_mutation_scenario",
    ]


def test_compile_current_plan_mutation_requires_constraint_negative_major_scope():
    source = proposal_compiler.compile_runtime_current_plan_mutation_from_intent_preview_source(
        content="当前方案处理一下",
        turn_decision=_current_plan_atomic_turn_decision(),
        merged_intent={"major_intents": {"level3": ["英语"]}},
        intent_mode="preference",
    )

    assert source.matched is False
    assert source.blocking_reasons == [
        "current_plan_mutation_requires_constraint_intent",
        "missing_current_plan_negative_major_scope",
    ]


def test_compile_atomic_plan_action_builds_plan_next_action_args_for_tuition_preference_scope():
    source = proposal_compiler.compile_runtime_atomic_plan_action_source(
        content="把两万以上且跟意向不沾边的先删掉",
        action_family="remove_units",
        confidence=0.95,
        min_tuition_per_year=20000,
        preference_fit="unrelated",
        planning_version=8,
    )

    assert source.matched is True
    assert source.route == "atomic_plan_action_preview"
    assert source.action_family == "remove_units"
    assert source.plan_next_action_args["action_family"] == "remove_units"
    assert source.plan_next_action_args["current_stage"] == "preview"
    assert source.plan_next_action_args["min_tuition_per_year"] == 20000
    assert source.plan_next_action_args["preference_fit"] == "unrelated"
    assert "planning_version" not in source.plan_next_action_args
    assert source.plan_action_dsl["type"] == "AtomicPlanActionDsl"
    assert source.plan_action_dsl["selector"]["min_tuition_per_year"] == 20000
    assert source.plan_action_dsl["selector"]["preference_fit"] == "unrelated"
    assert source.plan_action_dsl["sourceVersionGuard"] == 8


def test_compile_atomic_plan_action_blocks_unscoped_remove():
    source = proposal_compiler.compile_runtime_atomic_plan_action_source(
        content="删掉一些",
        action_family="remove_units",
        confidence=0.95,
    )

    assert source.matched is False
    assert source.blocking_reasons == ["missing_atomic_plan_action_scope"]
