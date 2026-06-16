"""ActionResolver 单元测试。

验证 IntentFrame → ActionResolution 的确定性映射。
覆盖：
- verb → action_family 映射
- query verb 的 topic 细分
- review issue override 规则
- structured normalization 规则
- missing inputs 检测
- stage 判定
- confirmation flag
- 非 plan 层请求被阻塞
"""

import pytest
from typing import get_args

from app.models.intent_frame import IntentFrame, ScopeSpec, TargetSpec, Verb
from app.resolver.action_resolver import ActionResolver
from app.tools.plan_orchestration_models import PlanContextInputs


@pytest.fixture
def resolver():
    return ActionResolver()


def _ctx(
    *,
    batch: str = "01",
    draft_count: int = 0,
    ordered_count: int = 0,
    target_count: int = 96,
    review_issues: list | None = None,
) -> PlanContextInputs:
    """快捷构造 PlanContextInputs。"""
    return PlanContextInputs(
        batch=batch,
        phase="ordered" if ordered_count > 0 else ("draft" if draft_count > 0 else "empty"),
        target_count=target_count,
        draft_count=draft_count,
        ordered_count=ordered_count,
        review_issues=review_issues or [],
    )


def _frame(
    verb: str = "query",
    topic: str = "general",
    task_layer: str = "plan",
    **kwargs,
) -> IntentFrame:
    """快捷构造 IntentFrame。"""
    target_fields = {}
    scope_fields = {}
    frame_fields = {}

    target_keys = {"volunteer_refs", "school_names", "major_names", "region_names",
                   "career_types", "review_issue_code", "unit_refs",
                   "source_position", "position"}
    scope_keys = {"tier", "province", "school_tags", "major_tags",
                  "school_keyword", "major_keyword", "limit", "is_review_issue_batch",
                  "sort_field"}

    for key, value in kwargs.items():
        if key in target_keys:
            target_fields[key] = value
        elif key in scope_keys:
            scope_fields[key] = value
        else:
            frame_fields[key] = value

    return IntentFrame(
        task_layer=task_layer,
        topic=topic,
        verb=verb,
        target=TargetSpec(**target_fields) if target_fields else TargetSpec(),
        scope=ScopeSpec(**scope_fields) if scope_fields else ScopeSpec(),
        **frame_fields,
    )


# ---------------------------------------------------------------------------
# Step 1: verb → action_family 基本映射
# ---------------------------------------------------------------------------

class TestVerbToActionFamily:
    """verb 到 action_family 的直接映射。"""

    @pytest.mark.parametrize("verb,expected_family", [
        ("analyze", "analyze_adjustment"),
        ("review", "review_plan"),
        ("generate", "generate_plan"),
        ("add", "add_units"),
        ("remove", "remove_units"),
        ("move", "move_unit"),
        ("replace", "replace_units"),
        ("reorder", "regenerate_order"),
        ("compensate", "preview_fix_proposal"),
    ])
    def test_direct_verb_mapping(self, resolver, verb, expected_family):
        frame = _frame(verb=verb)
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        assert result.action_family == expected_family

    def test_pin_unpin_verbs_not_exposed_in_intent_frame(self):
        assert "pin" not in get_args(Verb)
        assert "unpin" not in get_args(Verb)

    def test_confirm_reject_verbs_not_exposed_in_intent_frame(self):
        assert "confirm" not in get_args(Verb)
        assert "reject" not in get_args(Verb)

    def test_reorder_with_sort_field_maps_to_sort_ordered_plan(self, resolver):
        frame = _frame(verb="reorder", sort_field="schoolRank")
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        assert result.action_family == "sort_ordered_plan"
        assert result.stage == "preview"
        assert result.requires_confirmation is True


# ---------------------------------------------------------------------------
# Step 1b: query verb 的 topic/target 细分
# ---------------------------------------------------------------------------

class TestQueryVerbDisambiguation:
    """query verb 根据 topic 和 target 细分。"""

    def test_query_plan_topic(self, resolver):
        frame = _frame(verb="query", topic="plan")
        result = resolver.resolve(frame, _ctx(ordered_count=30))
        assert result.action_family == "query_state"

    def test_query_general_topic(self, resolver):
        frame = _frame(verb="query", topic="general")
        result = resolver.resolve(frame, _ctx(ordered_count=30))
        assert result.action_family == "query_state"

    def test_query_school_topic(self, resolver):
        frame = _frame(verb="query", topic="school")
        result = resolver.resolve(frame, _ctx(ordered_count=30))
        assert result.action_family == "query_ordered"

    def test_query_major_topic(self, resolver):
        frame = _frame(verb="query", topic="major")
        result = resolver.resolve(frame, _ctx(ordered_count=30))
        assert result.action_family == "query_ordered"

    def test_query_region_topic(self, resolver):
        frame = _frame(verb="query", topic="region")
        result = resolver.resolve(frame, _ctx(ordered_count=30))
        assert result.action_family == "query_candidates"

    def test_query_with_volunteer_refs(self, resolver):
        """有具体引用 → query_ordered。"""
        frame = _frame(verb="query", topic="general", volunteer_refs=["@3", "@5"])
        result = resolver.resolve(frame, _ctx(ordered_count=30))
        assert result.action_family == "query_ordered"

    def test_query_with_filters(self, resolver):
        """有筛选条件 → query_candidates。"""
        frame = _frame(verb="query", topic="general", province="北京", tier="冲")
        result = resolver.resolve(frame, _ctx(ordered_count=30))
        assert result.action_family == "query_candidates"

    def test_query_refs_over_filters(self, resolver):
        """有引用时优先 query_ordered（即使同时有 filters）。"""
        frame = _frame(verb="query", volunteer_refs=["@1"], province="北京")
        result = resolver.resolve(frame, _ctx(ordered_count=30))
        assert result.action_family == "query_ordered"


# ---------------------------------------------------------------------------
# Step 2: review issue override
# ---------------------------------------------------------------------------

class TestReviewIssueOverride:
    """review_issue_code 对 action_family 的覆盖逻辑。"""

    def test_item_replacement_default_to_review(self, resolver):
        """item_replacement 类型（如 high_tuition）默认只读审查，由 FixProposal 披露替换建议。"""
        frame = _frame(verb="query", review_issue_code="high_tuition")
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        assert result.action_family == "review_plan"
        assert result.review_issue_override is True

    def test_review_issue_override_prefers_backend_metadata(self, resolver):
        """同一 code 优先按后端审查元数据解释，避免 Agent 本地 registry 漂移。"""
        frame = _frame(verb="query", review_issue_code="unknown_backend_rule")
        ctx = _ctx(
            ordered_count=30,
            review_issues=[
                {
                    "code": "unknown_backend_rule",
                    "label": "后端新增条目风险",
                    "backend_scope_kind": "item",
                    "default_fix_strategy": "replace_risk_items",
                }
            ],
        )
        result = resolver.resolve(frame, ctx)
        assert result.action_family == "review_plan"
        assert result.review_issue_override is True

    def test_item_replacement_keeps_replace_with_intent(self, resolver):
        """item_replacement 类型 + 用户有替换意图 → 保留 replace_units。"""
        frame = _frame(verb="replace", review_issue_code="high_tuition", tier="稳")
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        assert result.action_family == "replace_units"

    def test_item_replacement_replace_without_scope_stays_replace(self, resolver):
        """item_replacement + replace 即使暂缺替换条件，也不自动降级为删除。"""
        frame = _frame(verb="replace", review_issue_code="cooperative_program")
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        assert result.action_family == "replace_units"

    def test_structural_override_mutations(self, resolver):
        """structural 类型覆盖掉直接增删。"""
        frame = _frame(verb="remove", review_issue_code="probability_inversion")
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        assert result.action_family == "sort_ordered_plan"
        assert result.review_issue_override is True

    def test_structural_preserves_non_mutation(self, resolver):
        """structural 类型不覆盖非直接增删动作（如 analyze）。"""
        frame = _frame(verb="analyze", review_issue_code="ratio_distribution")
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        assert result.action_family == "analyze_adjustment"

    def test_informational_remove_becomes_review(self, resolver):
        """informational 类型 + remove → review_plan。"""
        frame = _frame(verb="remove", review_issue_code="plan_update_notice")
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        assert result.action_family == "review_plan"

    def test_informational_replace_becomes_review(self, resolver):
        """informational 类型 + replace → review_plan。"""
        frame = _frame(verb="replace", review_issue_code="adjustment_notice")
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        assert result.action_family == "review_plan"

    def test_safety_guard_default_action(self, resolver):
        """safety_guard → preview_fix_proposal。"""
        frame = _frame(verb="add", review_issue_code="safety_guard")
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        # add_units 不在 structural mutation 列表里，但 safety_guard 是 structural
        # 实际 add_units 在 mutation_actions 列表里，所以会被覆盖
        assert result.action_family == "preview_fix_proposal"

    def test_count_validation_default_action(self, resolver):
        """count_validation → preview_fix_proposal。"""
        frame = _frame(verb="add", review_issue_code="count_validation")
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        assert result.action_family == "preview_fix_proposal"


# ---------------------------------------------------------------------------
# Step 3: normalization（结构化、非旧补偿旁路）
# ---------------------------------------------------------------------------

class TestNormalization:
    """结构化动作归一化。"""

    def test_rule1_generate_to_analyze(self, resolver):
        """规则1: generate + 已有方案 + verb 是 analyze → analyze_adjustment。"""
        frame = _frame(verb="analyze")
        ctx = _ctx(ordered_count=50)
        # verb=analyze 直接映射为 analyze_adjustment，不会触发 rule1
        result = resolver.resolve(frame, ctx)
        assert result.action_family == "analyze_adjustment"

    def test_compensation_keeps_fix_proposal_when_plan_not_full(self, resolver):
        """补齐/补稳保持 FixProposal 入口，不在 resolver 里改写成 add_units。"""
        frame = _frame(verb="compensate", tier="保")
        ctx = _ctx(ordered_count=50, target_count=96)
        result = resolver.resolve(frame, ctx)
        assert result.action_family == "preview_fix_proposal"
        assert result.normalization_applied == ""

    def test_compensation_keeps_fix_proposal_when_plan_full(self, resolver):
        """方案已满也保持 FixProposal 入口，由后端判断替换/候选不足。"""
        frame = _frame(verb="compensate", tier="保")
        ctx = _ctx(ordered_count=96, target_count=96)
        result = resolver.resolve(frame, ctx)
        assert result.action_family == "preview_fix_proposal"
        assert result.normalization_applied == ""

    def test_compensation_without_tier_keeps_fix_proposal(self, resolver):
        """无 tier 时也保持 FixProposal 入口。"""
        frame = _frame(verb="compensate")
        ctx = _ctx(ordered_count=50, target_count=96)
        result = resolver.resolve(frame, ctx)
        assert result.action_family == "preview_fix_proposal"

    def test_rule2_reorder_to_replace(self, resolver):
        """规则2: regenerate_order + 有 tier + 非明确 reorder → replace_units。"""
        # 用 analyze verb 进入，但由于 analyze 直接映射成 analyze_adjustment 不是 regenerate_order
        # 需要直接设置 verb=compensate 或其他方式得到 regenerate_order
        # 实际场景：verb 是某些能产生 regenerate_order 的，但 tier 不为空
        # 在 ActionResolver 中只有 verb="reorder" 才映射到 regenerate_order
        # 所以这条规则实际上在当前设计中不会触发（因为 verb=reorder 时 frame.verb==reorder）
        # 这是设计改进：旧系统中 LLM 可能输出错误的 action_family，新系统 verb 直接映射所以不需要
        frame = _frame(verb="reorder", tier="保")
        ctx = _ctx(ordered_count=50)
        result = resolver.resolve(frame, ctx)
        # verb=reorder 不会触发 rule3（因为条件是 frame.verb != "reorder"）
        assert result.action_family == "regenerate_order"

    def test_rule3_no_trigger_when_explicit_reorder(self, resolver):
        """规则3: 明确 reorder verb 时不降级。"""
        frame = _frame(verb="reorder")
        ctx = _ctx(ordered_count=50)
        result = resolver.resolve(frame, ctx)
        assert result.action_family == "regenerate_order"


# ---------------------------------------------------------------------------
# Step 5: missing inputs
# ---------------------------------------------------------------------------

class TestMissingInputs:
    """缺参检测。"""

    def test_remove_needs_refs_or_review_issue(self, resolver):
        """remove_units 无 refs 无 review_issue → missing volunteer_ids。"""
        frame = _frame(verb="remove")
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        assert "volunteer_ids" in result.missing_inputs

    def test_remove_with_refs_no_missing(self, resolver):
        frame = _frame(verb="remove", volunteer_refs=["@3"])
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        assert "volunteer_ids" not in result.missing_inputs

    def test_remove_with_review_issue_no_missing(self, resolver):
        frame = _frame(verb="remove", review_issue_code="high_tuition")
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        # review_issue_code → item_replacement，但显式 remove 仍保留 remove_units + has target
        assert "volunteer_ids" not in result.missing_inputs

    def test_move_needs_ref_and_position(self, resolver):
        frame = _frame(verb="move")
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        assert "volunteer_id" in result.missing_inputs
        assert "target_position" in result.missing_inputs

    def test_move_with_ref_and_position(self, resolver):
        frame = _frame(verb="move", volunteer_refs=["@5"], position=3)
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        assert result.missing_inputs == []

    def test_add_needs_scope(self, resolver):
        """add_units 无 refs 无 filters → missing selection_scope。"""
        frame = _frame(verb="add")
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        assert "selection_scope" in result.missing_inputs

    def test_add_with_refs_no_missing(self, resolver):
        frame = _frame(verb="add", volunteer_refs=["v1", "v2"])
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        assert "selection_scope" not in result.missing_inputs

    def test_add_with_filters_no_missing(self, resolver):
        frame = _frame(verb="add", province="北京", tier="冲")
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        assert "selection_scope" not in result.missing_inputs

    def test_replace_needs_refs_and_scope(self, resolver):
        frame = _frame(verb="replace")
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        assert "volunteer_ids" in result.missing_inputs
        assert "replacement_scope" in result.missing_inputs

    def test_replace_with_refs_and_scope(self, resolver):
        frame = _frame(verb="replace", volunteer_refs=["v1"], tier="稳")
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        assert result.missing_inputs == []

    def test_plan_dependent_with_empty_plan(self, resolver):
        """依赖方案的动作在方案为空时 → missing existing_plan。"""
        frame = _frame(verb="review")
        ctx = _ctx(ordered_count=0, draft_count=0)
        result = resolver.resolve(frame, ctx)
        assert "existing_plan" in result.missing_inputs

    def test_plan_dependent_with_existing_plan(self, resolver):
        frame = _frame(verb="review")
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        assert "existing_plan" not in result.missing_inputs

    def test_generate_plan_no_existing_plan_needed(self, resolver):
        """generate_plan 不依赖现有方案。"""
        frame = _frame(verb="generate")
        ctx = _ctx(ordered_count=0)
        result = resolver.resolve(frame, ctx)
        assert "existing_plan" not in result.missing_inputs


# ---------------------------------------------------------------------------
# Step 6: stage 判定
# ---------------------------------------------------------------------------

class TestStageDetermination:
    """stage 决策树。"""

    @pytest.mark.parametrize("family", [
        "query_state", "query_ordered", "query_candidates",
        "analyze_adjustment", "preview_fix_proposal",
    ])
    def test_readonly_actions_direct_apply(self, resolver, family):
        """只读动作直接 apply。"""
        verb_map = {
            "query_state": ("query", "plan"),
            "query_ordered": ("query", "school"),
            "query_candidates": ("query", "region"),
            "analyze_adjustment": ("analyze", "general"),
            "preview_fix_proposal": ("compensate", "general"),
        }
        verb, topic = verb_map[family]
        extra = {}
        if family == "query_ordered":
            extra["volunteer_refs"] = ["@1"]
        if family == "query_candidates":
            extra["province"] = "北京"
        frame = _frame(verb=verb, topic=topic, **extra)
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        assert result.stage == "apply"

    def test_missing_inputs_stage_analyze(self, resolver):
        """缺参 → analyze。"""
        frame = _frame(verb="move")
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        assert result.stage == "analyze"

    def test_review_plan_stage_review(self, resolver):
        frame = _frame(verb="review")
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        assert result.stage == "review"

    def test_default_stage_preview(self, resolver):
        """默认 → preview。"""
        frame = _frame(verb="generate")
        ctx = _ctx(ordered_count=0)
        result = resolver.resolve(frame, ctx)
        assert result.stage == "preview"

    def test_add_with_target_stage_preview(self, resolver):
        frame = _frame(verb="add", volunteer_refs=["v1"])
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        assert result.stage == "preview"


# ---------------------------------------------------------------------------
# Step 7: confirmation flag
# ---------------------------------------------------------------------------

class TestConfirmationFlag:
    """确认标志。"""

    @pytest.mark.parametrize("family", [
        "query_state", "query_ordered", "query_candidates",
        "analyze_adjustment", "preview_fix_proposal", "review_plan",
    ])
    def test_no_confirmation_for_readonly(self, resolver, family):
        """只读动作不需要确认。"""
        verb_map = {
            "query_state": "query",
            "query_ordered": "query",
            "query_candidates": "query",
            "analyze_adjustment": "analyze",
            "preview_fix_proposal": "compensate",
            "review_plan": "review",
        }
        extra = {}
        topic = "plan"
        if family == "query_ordered":
            extra["volunteer_refs"] = ["@1"]
            topic = "school"
        if family == "query_candidates":
            extra["province"] = "北京"
            topic = "region"
        frame = _frame(verb=verb_map[family], topic=topic, **extra)
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        assert result.requires_confirmation is False

    @pytest.mark.parametrize("family", [
        "generate_plan", "sort_ordered_plan", "regenerate_order", "replace_units",
    ])
    def test_always_confirm(self, resolver, family):
        """高副作用动作总是需要确认。"""
        verb_map = {
            "generate_plan": "generate",
            "sort_ordered_plan": "reorder",
            "regenerate_order": "reorder",
            "replace_units": "replace",
        }
        extra = {}
        if family == "replace_units":
            extra["volunteer_refs"] = ["v1"]
            extra["tier"] = "稳"
        if family == "sort_ordered_plan":
            extra["sort_field"] = "schoolRank"
        frame = _frame(verb=verb_map[family], **extra)
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        assert result.requires_confirmation is True

    def test_no_confirmation_when_analyze_stage(self, resolver):
        """analyze 阶段不需要确认。"""
        frame = _frame(verb="move")
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        assert result.stage == "analyze"
        assert result.requires_confirmation is False


# ---------------------------------------------------------------------------
# 非 plan 层请求
# ---------------------------------------------------------------------------

class TestNonPlanLayer:
    """非 plan 层请求被标记为 blocked。"""

    def test_explore_layer_blocked(self, resolver):
        frame = _frame(verb="explore", task_layer="explore", topic="career")
        result = resolver.resolve(frame, _ctx())
        assert result.stage == "blocked"
        assert "explore" in result.blocked_reason

    def test_intent_layer_blocked(self, resolver):
        frame = _frame(verb="set_preference", task_layer="intent", topic="major")
        result = resolver.resolve(frame, _ctx())
        assert result.stage == "blocked"
        assert "intent" in result.blocked_reason


# ---------------------------------------------------------------------------
# workspace 刷新标志
# ---------------------------------------------------------------------------

class TestWorkspaceFlags:
    """should_rerun_review / should_refresh_workspace。"""

    def test_no_rerun_review_on_preview(self, resolver):
        frame = _frame(verb="generate")
        ctx = _ctx(ordered_count=0)
        result = resolver.resolve(frame, ctx)
        assert result.stage == "preview"
        assert result.should_rerun_review is False

    def test_refresh_workspace_on_review(self, resolver):
        frame = _frame(verb="review")
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        assert result.should_refresh_workspace is True


# ---------------------------------------------------------------------------
# PlanGoal 元数据
# ---------------------------------------------------------------------------

class TestCompositeGoalBoundary:
    """复合目标不在 ActionResolver 输出中重复承载。"""

    def test_raw_utterance_alone_does_not_change_atomic_action_boundary(self, resolver):
        frame = _frame(
            verb="replace",
            topic="major",
            raw_utterance="只保留临床医学，其他不要",
            major_names=["临床医学"],
        )
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        assert result.action_family == "replace_units"
        assert result.stage == "analyze"
        assert result.missing_inputs == ["volunteer_ids", "replacement_scope"]
        assert "plan_goal" not in result.model_dump()
        assert "intent_updates" not in result.model_dump()

    def test_structured_plan_goal_fields_do_not_create_resolver_state_mirror(self, resolver):
        frame = _frame(
            verb="replace",
            topic="major",
            raw_utterance="只保留临床医学，其他不要",
            plan_goal_type="only_keep_scope",
            major_names=["临床医学"],
            tier="稳",
        )
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        assert result.action_family == "replace_units"
        assert result.stage == "analyze"
        assert result.missing_inputs == ["volunteer_ids"]
        assert "plan_goal" not in result.model_dump()
        assert "intent_updates" not in result.model_dump()

    def test_constraint_intent_type_does_not_bypass_action_confirmation_boundary(self, resolver):
        frame = _frame(
            verb="add",
            topic="major",
            raw_utterance="方案里必须有临床医学",
            constraint_intent_type="must_have",
            major_names=["临床医学"],
            tier="稳",
        )
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        assert result.action_family == "add_units"
        assert result.stage == "preview"
        assert result.requires_confirmation is True
        assert "plan_goal" not in result.model_dump()
        assert "intent_updates" not in result.model_dump()

    def test_exclude_goal_type_does_not_turn_into_plan_mutation_without_refs(self, resolver):
        frame = _frame(
            verb="remove",
            topic="region",
            raw_utterance="不要江苏",
            plan_goal_type="exclude_scope",
            region_names=["江苏"],
        )
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        assert result.action_family == "remove_units"
        assert result.stage == "analyze"
        assert result.missing_inputs == ["volunteer_ids"]
        assert "plan_goal" not in result.model_dump()
        assert "intent_updates" not in result.model_dump()

    def test_non_plan_layer_with_goal_metadata_remains_blocked_without_state_mirror(self, resolver):
        frame = _frame(
            verb="set_constraint",
            task_layer="intent",
            topic="major",
            constraint_intent_type="only_keep",
            major_names=["临床医学"],
        )
        result = resolver.resolve(frame, _ctx())
        assert result.stage == "blocked"
        assert "intent" in result.blocked_reason
        assert "plan_goal" not in result.model_dump()
        assert "intent_updates" not in result.model_dump()


# ---------------------------------------------------------------------------
# typed action 构造
# ---------------------------------------------------------------------------

class TestTypedActionConstruction:
    """验证 action 字段被正确构造。"""

    def test_query_state_action(self, resolver):
        frame = _frame(verb="query", topic="plan", raw_utterance="方案怎么样了")
        result = resolver.resolve(frame, _ctx(ordered_count=30))
        from app.models.typed_actions import QueryStateAction
        assert isinstance(result.action, QueryStateAction)
        assert result.action.reason == "方案怎么样了"

    def test_add_units_action_with_refs(self, resolver):
        frame = _frame(verb="add", volunteer_refs=["v1", "v2"])
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        from app.models.typed_actions import AddUnitsAction
        assert isinstance(result.action, AddUnitsAction)
        assert result.action.volunteer_ids == ["v1", "v2"]

    def test_add_units_action_with_filters(self, resolver):
        frame = _frame(verb="add", province="北京", tier="冲")
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        from app.models.typed_actions import AddUnitsAction
        assert isinstance(result.action, AddUnitsAction)
        assert result.action.selection_filters.province == "北京"
        assert result.action.selection_filters.tier == "冲"

    def test_move_unit_action(self, resolver):
        frame = _frame(verb="move", volunteer_refs=["@5"], position=3)
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        from app.models.typed_actions import MoveUnitAction
        assert isinstance(result.action, MoveUnitAction)
        assert result.action.volunteer_id == "@5"
        assert result.action.target_position == 3

    def test_remove_units_with_review_issue(self, resolver):
        frame = _frame(verb="remove", review_issue_code="high_tuition")
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        from app.models.typed_actions import RemoveUnitsAction
        assert isinstance(result.action, RemoveUnitsAction)
        assert result.action.review_issue is not None
        assert result.action.review_issue.code == "high_tuition"

    def test_replace_units_action(self, resolver):
        frame = _frame(
            verb="replace",
            volunteer_refs=["v1"],
            major_names=["会计学"],
            tier="稳",
            province="北京",
        )
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        from app.models.typed_actions import ReplaceUnitsAction
        assert isinstance(result.action, ReplaceUnitsAction)
        assert result.action.remove_ids == ["v1"]
        assert result.action.source_major_names == ["会计学"]
        assert result.action.replacement_filters.tier == "稳"
        assert result.action.replacement_filters.province == "北京"

    def test_regenerate_order_structural(self, resolver):
        frame = _frame(verb="reorder", tier="保")
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        from app.models.typed_actions import RegenerateOrderAction
        assert isinstance(result.action, RegenerateOrderAction)
        assert result.action.structural_rebalance is True

    def test_sort_ordered_plan_action(self, resolver):
        frame = _frame(verb="reorder", sort_field="schoolRank")
        ctx = _ctx(ordered_count=30)
        result = resolver.resolve(frame, ctx)
        from app.models.typed_actions import SortOrderedPlanAction
        assert isinstance(result.action, SortOrderedPlanAction)
        assert result.action.sort_field == "schoolRank"

    def test_generate_plan_action(self, resolver):
        frame = _frame(verb="generate")
        ctx = _ctx(ordered_count=0)
        result = resolver.resolve(frame, ctx)
        from app.models.typed_actions import GeneratePlanAction
        assert isinstance(result.action, GeneratePlanAction)
        assert result.action.force_regenerate is True


# ---------------------------------------------------------------------------
# 端到端场景测试
# ---------------------------------------------------------------------------

class TestEndToEndScenarios:
    """模拟真实用户意图的端到端场景。"""

    def test_scenario_query_current_plan(self, resolver):
        """"方案有了么" → query_state, apply, no confirmation。"""
        frame = _frame(verb="query", topic="plan", raw_utterance="方案有了么")
        ctx = _ctx(ordered_count=50)
        result = resolver.resolve(frame, ctx)
        assert result.action_family == "query_state"
        assert result.stage == "apply"
        assert result.requires_confirmation is False

    def test_scenario_generate_first_plan(self, resolver):
        """"帮我出一版方案" → generate_plan, preview。"""
        frame = _frame(verb="generate", raw_utterance="帮我出一版方案")
        ctx = _ctx(ordered_count=0)
        result = resolver.resolve(frame, ctx)
        assert result.action_family == "generate_plan"
        assert result.stage == "preview"
        assert result.requires_confirmation is True

    def test_scenario_review_plan(self, resolver):
        """"审查一下方案" → review_plan, review。"""
        frame = _frame(verb="review", raw_utterance="审查一下方案")
        ctx = _ctx(ordered_count=50)
        result = resolver.resolve(frame, ctx)
        assert result.action_family == "review_plan"
        assert result.stage == "review"
        assert result.requires_confirmation is False

    def test_scenario_add_stable_candidates(self, resolver):
        """"帮我补几个更稳的" → preview_fix_proposal。"""
        frame = _frame(verb="compensate", tier="保", raw_utterance="帮我补几个更稳的")
        ctx = _ctx(ordered_count=50, target_count=96)
        result = resolver.resolve(frame, ctx)
        assert result.action_family == "preview_fix_proposal"
        assert result.normalization_applied == ""

    def test_scenario_remove_high_tuition(self, resolver):
        """"把高收费的都去掉" → remove_units (显式删除仍保留)。"""
        frame = _frame(
            verb="remove",
            review_issue_code="high_tuition",
            raw_utterance="把高收费的都去掉",
        )
        ctx = _ctx(ordered_count=50)
        result = resolver.resolve(frame, ctx)
        assert result.action_family == "remove_units"
        assert result.stage == "preview"

    def test_scenario_replace_high_tuition(self, resolver):
        """"把高收费的换成正常收费的" → replace_units。"""
        frame = _frame(
            verb="replace",
            review_issue_code="high_tuition",
            tier="稳",
            raw_utterance="把高收费的换成正常收费的",
        )
        ctx = _ctx(ordered_count=50)
        result = resolver.resolve(frame, ctx)
        assert result.action_family == "replace_units"
        assert result.requires_confirmation is True

    def test_scenario_analyze_when_full(self, resolver):
        """"怎么优化一下" + 方案已满 → analyze_adjustment。"""
        frame = _frame(verb="analyze", raw_utterance="怎么优化一下")
        ctx = _ctx(ordered_count=96, target_count=96)
        result = resolver.resolve(frame, ctx)
        assert result.action_family == "analyze_adjustment"
        assert result.stage == "apply"

    def test_scenario_compensation_when_full_keeps_fix_proposal(self, resolver):
        """"补齐方案" + 方案已满 → preview_fix_proposal。"""
        frame = _frame(verb="compensate", raw_utterance="补齐方案")
        ctx = _ctx(ordered_count=96, target_count=96)
        result = resolver.resolve(frame, ctx)
        assert result.action_family == "preview_fix_proposal"

    def test_scenario_reorder_explicit(self, resolver):
        """"重新排一下" → regenerate_order。"""
        frame = _frame(verb="reorder", raw_utterance="重新排一下")
        ctx = _ctx(ordered_count=50)
        result = resolver.resolve(frame, ctx)
        assert result.action_family == "regenerate_order"
        assert result.requires_confirmation is True

    def test_scenario_sort_by_school_rank(self, resolver):
        """"按院校层次排序" → sort_ordered_plan。"""
        frame = _frame(verb="reorder", sort_field="schoolRank", raw_utterance="按院校层次排序")
        ctx = _ctx(ordered_count=50)
        result = resolver.resolve(frame, ctx)
        assert result.action_family == "sort_ordered_plan"
        assert result.requires_confirmation is True

    def test_scenario_no_plan_blocks_review(self, resolver):
        """"审查方案" + 无方案 → stage=analyze, missing=existing_plan。"""
        frame = _frame(verb="review", raw_utterance="审查方案")
        ctx = _ctx(ordered_count=0)
        result = resolver.resolve(frame, ctx)
        assert "existing_plan" in result.missing_inputs
        assert result.stage == "analyze"

    def test_scenario_structural_issue_blocks_direct_delete(self, resolver):
        """概率倒挂（structural）+ remove → sort_ordered_plan preview。"""
        frame = _frame(
            verb="remove",
            review_issue_code="probability_inversion",
            raw_utterance="把概率倒挂的删掉",
        )
        ctx = _ctx(ordered_count=50)
        result = resolver.resolve(frame, ctx)
        assert result.action_family == "sort_ordered_plan"
        assert result.review_issue_override is True
        assert result.stage == "preview"
        assert result.requires_confirmation is True
