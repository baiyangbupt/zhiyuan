from app.domain import proposal_compiler


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
        reply="这轮还没有生成可确认的调整预览，所以不会改动当前方案。",
        guard_context="no_tool_action_boundary",
    )

    assert source.matched is True
    assert source.route == "no_tool_action_boundary_reply_guard"


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


def test_needs_plan_first_guard_allows_pre_score_adjustment_policy_question():
    resolution = proposal_compiler.resolve_needs_plan_first_guard(
        "批次线出来前先按模考估，后面咋调整",
        planning_summary={},
    )

    assert resolution.side_effect == "none"
    assert resolution.target_issues == []


def test_needs_plan_first_guard_still_blocks_current_plan_pre_score_mutation():
    resolution = proposal_compiler.resolve_needs_plan_first_guard(
        "当前方案按模考位次调整",
        planning_summary={},
    )

    assert resolution.side_effect == "needs_plan_first"
    assert resolution.target_issues == ["plan_mutation_without_referent"]


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
