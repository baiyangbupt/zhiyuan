import json

from app.domain import proposal_compiler


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


def test_intent_preview_turn_decision_arbitration_allows_current_plan_durable_constraint_intent():
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
        constraint_intent_type="must_have",
    )

    assert source.allow_intent_pending is True
    assert source.blocking_reasons == []
    assert source.arbitration_dsl["constraintIntentType"] == "must_have"
    assert source.arbitration_dsl["durableConstraintIntent"] is True


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


def test_current_plan_mutation_anchor_includes_unsupported_pin_lock_actions():
    assert proposal_compiler.content_has_current_plan_mutation_anchor("把第一个志愿锁定在第一位") is True
    assert proposal_compiler.content_has_current_plan_mutation_anchor("冲档第一位固定不要动") is True
    assert proposal_compiler.content_has_current_plan_mutation_anchor("以后想考公但也怕太卷，先看看") is False


def test_compile_no_plan_atomic_action_boundary_uses_structured_action_family():
    source = proposal_compiler.compile_no_plan_atomic_action_boundary_source(
        "把广西师大统计加进来",
        action_family="add_units",
    )

    assert source.side_effect == "needs_plan_first"
    assert source.target_issues == ["plan_add_without_referent"]
    assert source.blocking_reasons == ["missing_formal_plan"]
    assert "加入当前方案的候选志愿" in source.primary_reply

    unmatched = proposal_compiler.compile_no_plan_atomic_action_boundary_source(
        "加入广东和江西",
        action_family="none",
    )
    assert unmatched.side_effect == "none"


def test_future_reference_anchor_does_not_treat_preference_fit_as_intent_write():
    assert proposal_compiler.content_has_future_reference_anchor("那把两万以上且跟我意向不沾边的先删掉") is False
    assert proposal_compiler.content_has_future_reference_anchor("把华中科技大学加到意向") is True
    assert proposal_compiler.content_has_future_reference_anchor("以后少推荐民办，优先公办") is True


def test_readonly_school_or_candidate_query_anchor_blocks_region_intent_fast_path():
    assert proposal_compiler.content_has_readonly_school_or_candidate_query_anchor("江西的大学有哪些适合我") is True
    assert proposal_compiler.content_has_readonly_school_or_candidate_query_anchor("候选里有哪些计算机机会") is True
    assert proposal_compiler.content_has_readonly_school_or_candidate_query_anchor("加入广东和江西") is False
    assert proposal_compiler.content_has_readonly_school_or_candidate_query_anchor("以后推荐江西的大学") is False


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


def test_build_structured_user_goal_fix_proposal_request_builds_java_request():
    goal = {
        "goal_type": "exclude_scope",
        "user_original_text": "避开经济与金融",
        "negative_scopes": [
            {"entity_type": "major", "values": ["经济与金融"]},
        ],
        "confidence": "high",
    }

    request = proposal_compiler.build_structured_user_goal_fix_proposal_request(
        goal,
        12,
        context={"source": "chat_service_constraint_confirmation"},
        evidence_source="confirmed_intent",
    )

    assert request["goalType"] == "exclude_scope"
    assert request["sourceVersionGuard"] == 12
    assert request["context"] == {"source": "chat_service_constraint_confirmation"}
    assert request["negativeScopes"][0]["entityType"] == "major"
    assert request["negativeScopes"][0]["normalizedName"] == "经济与金融"
    assert request["negativeScopes"][0]["evidence"]["source"] == "confirmed_intent"


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


def test_resolve_intent_input_keeps_default_constraint_for_hard_exclude_with_soft_positive_scope():
    resolution = proposal_compiler.resolve_intent_preview_input(
        selected_values=[
            {"major_intents": {"level3": ["网络与新媒体", "跨境电子商务"]}},
            {"major_intents": {"negative_level3": ["土木工程"]}},
        ],
        merged={
            "major_intents": {
                "level3": ["网络与新媒体", "跨境电子商务"],
                "negative_level3": ["土木工程"],
            }
        },
        intent_mode="constraint",
        raw_constraint_intent_type="default",
    )

    assert resolution.allowed is True
    assert resolution.intent_mode == "constraint"
    assert resolution.constraint_intent_type == "default"
    assert resolution.blocking_reasons == []


def test_intent_payload_scope_helpers_detect_positive_and_negative_values():
    positive = {"major_intents": {"level3": ["软件工程"]}}
    negative = {"city_intents": {"negative_province": ["安徽"]}}
    budget = {"tuition_budget": {"max_tuition_per_year": [20000]}}

    assert proposal_compiler.intent_payload_has_positive_value(positive) is True
    assert proposal_compiler.intent_payload_has_negative_value(positive) is False
    assert proposal_compiler.intent_payload_has_positive_value(negative) is False
    assert proposal_compiler.intent_payload_has_negative_value(negative) is True
    assert proposal_compiler.intent_payload_has_positive_value(budget) is True
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
    assert proposal_compiler.intent_payload_has_required_constraint_scope(
        budget,
        constraint_intent_type="default",
    ) is True


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


def test_resolve_plan_confirmation_candidate_allows_apply_payload_and_version_guard():
    candidate = {
        "action_family": "add_units",
        "plan_payload": {
            "stage": "apply",
            "action_family": "add_units",
            "requires_confirmation": False,
            "target_view": "ordered",
            "planning_version": 12,
            "atomic_actions": [{"action_type": "add_units", "volunteer_ids": ["v1"]}],
        },
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
        "plan_payload": {
            "stage": "apply",
            "action_family": "remove_units",
            "requires_confirmation": False,
            "planning_version": 9,
            "atomic_actions": [{"action_type": "remove_units", "volunteer_ids": ["v1"]}],
        },
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
        "plan_payload": {
            "stage": "apply",
            "action_family": "apply_fix_proposal",
            "requires_confirmation": False,
            "planning_version": 7,
        },
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
    payload = source.confirmation_candidate["plan_payload"]
    assert isinstance(payload, dict)
    assert payload["stage"] == "apply"
    assert payload["action_family"] == "generate_plan"
    assert payload["planning_version"] == 19
    assert payload["requires_confirmation"] is False
    assert payload["facts"]["composite_source"] == "apply_pending_then_new_request"


def test_plan_candidate_resolution_blocks_action_family_mismatch():
    candidate = {
        "action_family": "add_units",
        "plan_payload": {
            "stage": "apply",
            "action_family": "remove_units",
            "requires_confirmation": False,
            "planning_version": 7,
            "atomic_actions": [{"action_type": "remove_units", "volunteer_ids": ["v1"]}],
        },
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
        "plan_payload": {
            "stage": "preview",
            "action_family": "add_units",
            "requires_confirmation": True,
            "planning_version": 7,
            "atomic_actions": [{"action_type": "add_units", "volunteer_ids": ["v1"]}],
        },
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


def test_compile_blocked_intent_preview_for_plan_route_reply_preserves_selected_items():
    source = proposal_compiler.compile_blocked_intent_preview_for_plan_route_reply_source(
        turn_decision={
            "taskLayer": "plan",
            "sideEffect": "plan_preview",
            "scopeAnchor": "current_plan",
            "scenario": "atomic_mutation",
            "confidence": 0.95,
        },
        preview_payload={
            "intentMode": "constraint",
            "constraintIntentType": "must_have",
            "items": [
                {
                    "content": "把临床医学记成明确要满足的具体专业要求",
                    "selected": True,
                    "value": {"major_intents": {"level3": ["临床医学"]}},
                }
            ],
        },
    )

    assert source.matched is True
    assert source.route == "blocked_intent_preview_for_current_plan_mutation"
    assert "临床医学" in source.primary_reply
    assert "没有形成可执行的调整内容" in source.primary_reply
    assert source.display_payload["selectedItems"] == ["临床医学"]
    assert source.reply_plan["focus"] == ["current_plan_mutation_requires_plan_preview"]


def test_resolve_conditional_candidate_readonly_boundary_for_selection_scope():
    resolution = proposal_compiler.resolve_conditional_candidate_readonly_boundary(
        result={
            "action_family": "add_units",
            "result_kind": "error",
            "reply_focus": ["missing_inputs", "needs_candidate_selection"],
            "missing_inputs": ["selection_scope"],
        }
    )

    assert resolution.matched is True
    assert resolution.route == "conditional_candidate_selection_scope_boundary"
    assert resolution.reason_code == "selection_scope"
    assert resolution.missing_inputs == ["selection_scope"]


def test_resolve_conditional_candidate_readonly_boundary_for_missing_inputs():
    resolution = proposal_compiler.resolve_conditional_candidate_readonly_boundary(
        result={
            "action_family": "add_units",
            "result_kind": "error",
            "reply_focus": ["missing_inputs"],
            "missing_inputs": ["province", "score", "subjects"],
        }
    )

    assert resolution.matched is True
    assert resolution.route == "conditional_candidate_missing_inputs_boundary"
    assert resolution.reason_code == "missing_inputs"
    assert resolution.missing_inputs == ["province", "score", "subjects"]


def test_resolve_conditional_candidate_readonly_boundary_ignores_non_add_units():
    resolution = proposal_compiler.resolve_conditional_candidate_readonly_boundary(
        result={
            "action_family": "replace_units",
            "result_kind": "error",
            "reply_focus": ["missing_inputs"],
            "missing_inputs": ["selection_scope"],
        }
    )

    assert resolution.matched is False
    assert "unsupported_candidate_boundary_action_family" in resolution.blocking_reasons


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


def test_runtime_plan_query_profile_compiler_preserves_candidate_pool_condition_filters():
    compiled = proposal_compiler.compile_runtime_plan_query_profile_source(
        content="电力，铁道，航空职业技术学院，在海南招生的有哪几个学校呢",
        query_profile={
            "queryType": "readonly_plan_query",
            "scopeAnchor": "candidate_pool",
            "dimensions": ["item_list"],
            "condition": {
                "target": "candidate_pool",
                "filters": {
                    "provinceNames": ["海南"],
                    "schoolKeywords": ["电力", "铁道", "航空"],
                },
                "sort": {"field": "recommendation", "order": "desc"},
                "page": 1,
                "pageSize": 5,
            },
            "filters": {"limit": 5, "item_type": "school"},
            "projection": {"mode": "school_list", "limit": 5},
            "replyFocus": ["candidate_snapshot", "local_candidate_query", "school_list_query"],
        },
        planning_version=13,
    )

    assert compiled.matched is True
    assert compiled.action_family == "query_candidates"
    assert compiled.plan_query_dsl["filters"]["province_names"] == ["海南"]
    assert compiled.plan_query_dsl["filters"]["province_keyword"] == "海南"
    assert compiled.plan_query_dsl["filters"]["school_keywords"] == ["电力", "铁道", "航空"]
    assert compiled.plan_query_dsl["filters"]["school_keyword"] == "电力"
    action_filters = compiled.plan_payload["atomic_actions"][0]["filters"]
    assert action_filters["province_names"] == ["海南"]
    assert action_filters["school_keywords"] == ["电力", "铁道", "航空"]
    assert "school_list_query" in compiled.plan_payload["reply_focus"]


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


def test_needs_plan_first_guard_blocks_plan_mutation_without_formal_plan_referent():
    resolution = proposal_compiler.resolve_needs_plan_first_guard(
        "把会计审计相关替换成新媒体或跨境电商相关",
        planning_summary={"ordered_total": 0, "working_total": 0},
    )

    assert resolution.side_effect == "needs_plan_first"
    assert resolution.reference_resolution == "no_referent"
    assert resolution.requires_model_decision is False
    assert resolution.target_issues == ["plan_mutation_without_referent"]
    assert resolution.blocking_reasons == ["missing_formal_plan"]


def test_needs_plan_first_guard_blocks_plan_add_without_formal_plan_referent():
    resolution = proposal_compiler.resolve_needs_plan_first_guard(
        "把广西师大统计加进来",
        planning_summary={"ordered_total": 0, "working_total": 0},
    )

    assert resolution.side_effect == "needs_plan_first"
    assert resolution.reference_resolution == "no_referent"
    assert resolution.requires_model_decision is False
    assert resolution.target_issues == ["plan_add_without_referent"]
    assert "加入当前方案" in resolution.primary_reply
    assert resolution.blocking_reasons == ["missing_formal_plan"]


def test_needs_plan_first_guard_blocks_no_plan_dual_track_mutation():
    resolution = proposal_compiler.resolve_needs_plan_first_guard(
        "希望通过生物科学和化学这样的专业保住院校层次，在方案中增加湖南的湘潭大学、长沙理工、湖南科技大学、吉首大学、湖南农业大学、延边大学的工科专业组。去掉",
        planning_summary={"ordered_total": 0, "working_total": 0},
    )

    assert resolution.side_effect == "needs_plan_first"
    assert resolution.reference_resolution == "no_referent"
    assert resolution.target_issues == ["plan_mutation_without_referent"]
    assert "这轮诉求是" in resolution.primary_reply
    assert "生物科学" in resolution.primary_reply
    assert "湘潭大学" in resolution.primary_reply
    assert resolution.blocking_reasons == ["missing_formal_plan"]


def test_needs_plan_first_guard_blocks_implicit_sort_without_formal_plan_referent():
    resolution = proposal_compiler.resolve_needs_plan_first_guard(
        "按好学校排下看看",
        planning_summary={"ordered_total": 0, "working_total": 0},
    )

    assert resolution.side_effect == "needs_plan_first"
    assert resolution.reference_resolution == "no_referent"
    assert resolution.requires_model_decision is False
    assert resolution.target_issues == ["plan_mutation_without_referent"]
    assert "当前还没有生成正式方案" in resolution.primary_reply
    assert "不会改动当前方案" in resolution.primary_reply
    assert resolution.blocking_reasons == ["missing_formal_plan"]


def test_needs_plan_first_guard_preserves_career_direction_focus_without_formal_plan():
    resolution = proposal_compiler.resolve_needs_plan_first_guard(
        "当前方案对体制内稳定就业方向承接得怎么样，先不要改方案",
        planning_summary={"ordered_total": 0, "working_total": 0},
    )

    assert resolution.side_effect == "needs_plan_first"
    assert resolution.reference_resolution == "no_referent"
    assert resolution.target_issues == ["career_direction_support"]
    assert "体制内/考公导向" in resolution.primary_reply
    assert "稳定就业导向" in resolution.primary_reply
    assert "承接" in resolution.primary_reply
    assert "不会改动当前方案" in resolution.primary_reply
    assert resolution.display_payload["presentation"] == "readonly_boundary"
    assert resolution.display_payload["focusLabel"] == "体制内/考公导向、稳定就业导向的方案承接"
    assert resolution.reply_plan["focus"] == ["career_direction_support"]


def test_needs_plan_first_guard_preserves_recent_intent_conflict_focus():
    resolution = proposal_compiler.resolve_needs_plan_first_guard(
        "现在方案里哪些和这些要求冲突",
        planning_summary={"ordered_total": 0, "working_total": 0},
        recent_intent_summary="偏好专业类：财经类；排除专业：护理学、中西医结合类",
    )

    assert resolution.side_effect == "needs_plan_first"
    assert resolution.reference_resolution == "no_referent"
    assert resolution.target_issues == ["intent_conflict_check_without_referent"]
    assert "财经类" in resolution.primary_reply
    assert "护理学" in resolution.primary_reply
    assert "中西医结合类" in resolution.primary_reply
    assert "逐项判断哪些志愿冲突或不符合" in resolution.primary_reply
    assert "冲稳保或风险" not in resolution.primary_reply
    assert resolution.display_payload["recentIntentSummary"] == "偏好专业类：财经类；排除专业：护理学、中西医结合类"
    assert resolution.reply_plan["focus"] == ["intent_conflict_check_without_referent"]


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
