"""对接验证：ActionResolver 与旧 _normalize_adjustment_action_family 逻辑的一致性比较。

思路：
- 构造典型用户话语及对应的 IntentFrame
- 分别走旧路径（LLM 选 action_family + normalize）和新路径（IntentFrame → ActionResolver）
- 验证两者输出的 action_family 一致
- 标注已知的 intentional divergence（旧逻辑 false positive/negative 被修正的地方）
"""

from __future__ import annotations

import pytest

from app.models.intent_frame import IntentFrame, ScopeSpec, TargetSpec
from app.resolver.action_resolver import ActionResolver
from app.tools.plan_orchestration_tool import _normalize_adjustment_action_family
from tests.factories import make_plan_context_inputs


resolver = ActionResolver()

HAS_PLAN = make_plan_context_inputs(draft_count=30, ordered_count=30, target_count=30)
NO_PLAN = make_plan_context_inputs(draft_count=0, ordered_count=0, target_count=30)
NOT_FILLED = make_plan_context_inputs(draft_count=20, ordered_count=20, target_count=30)
FILLED = make_plan_context_inputs(draft_count=30, ordered_count=30, target_count=30)


# ---------------------------------------------------------------------------
# 场景定义: (user_text, llm_chosen_action_family, intent_frame, context)
# ---------------------------------------------------------------------------


def _frame(verb, topic="general", task_layer="plan", **kwargs) -> IntentFrame:
    target_kwargs = {}
    scope_kwargs = {}
    frame_kwargs = {}
    for key in ("volunteer_refs", "school_names", "major_names", "region_names",
                "review_issue_code", "position", "career_types"):
        if key in kwargs:
            target_kwargs[key] = kwargs.pop(key)
    for key in ("tier", "province", "school_tags", "major_tags",
                "school_keyword", "major_keyword", "limit", "is_review_issue_batch"):
        if key in kwargs:
            scope_kwargs[key] = kwargs.pop(key)
    for key in ("is_confirmation_of_previous", "raw_utterance"):
        if key in kwargs:
            frame_kwargs[key] = kwargs.pop(key)
    return IntentFrame(
        task_layer=task_layer,
        topic=topic,
        verb=verb,
        target=TargetSpec(**target_kwargs) if target_kwargs else TargetSpec(),
        scope=ScopeSpec(**scope_kwargs) if scope_kwargs else ScopeSpec(),
        **frame_kwargs,
    )


# ---------------------------------------------------------------------------
# 测试用例：旧路径 (normalize) 和新路径 (resolver) 应产出一致的 action_family
# ---------------------------------------------------------------------------


class TestDirectVerbMapping:
    """verb 直接映射到 action_family 的场景 — 无 normalization 介入。"""

    @pytest.mark.parametrize("user_text,llm_family,verb,expected", [
        # 查询类
        ("看看当前方案怎么样", "query_state", "query", "query_state"),
        ("审查一下方案", "review_plan", "review", "review_plan"),
        # 生成类（无现有方案）
        ("给我生成一个方案", "generate_plan", "generate", "generate_plan"),
        # 分析类
        ("帮我分析一下方案", "analyze_adjustment", "analyze", "analyze_adjustment"),
        # 补偿类
        ("看看有什么可以补齐的", "preview_compensation", "compensate", "preview_compensation"),
        # 重排
        ("帮我重排一下", "regenerate_order", "reorder", "regenerate_order"),
        # 增删改
        ("加上这个志愿", "add_units", "add", "add_units"),
        ("删掉这个志愿", "remove_units", "remove", "remove_units"),
        ("把这个移到第3位", "move_unit", "move", "move_unit"),
        ("锁定这个位置", "pin_unit", "pin", "pin_unit"),
        ("取消锁定", "unpin_unit", "unpin", "unpin_unit"),
        ("把这个换掉", "replace_units", "replace", "replace_units"),
    ])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_direct_mapping_consistent(
        self, user_text, llm_family, verb, expected, volunteer_model
    ):
        # 旧路径：LLM 直接选对了 action_family，normalize 不变
        old_result = _normalize_adjustment_action_family(llm_family, user_text, NO_PLAN)
        assert old_result == expected

        # 新路径：ActionResolver
        frame = _frame(verb, raw_utterance=user_text)
        resolution = resolver.resolve(frame, NO_PLAN)
        assert resolution.action_family == expected


class TestNormalizationRule1:
    """Rule 1: generate_plan + has_plan + !explicit_regen + analysis_intent → analyze_adjustment"""

    @pytest.mark.parametrize("user_text,verb,expected", [
        # 旧路径：LLM 选了 generate_plan 但 user_goal 含分析意图 → normalize 降级
        # 新路径：LLM 应输出 verb=analyze（因为用户话语语义是分析而非生成）
        ("怎么优化当前方案", "analyze", "analyze_adjustment"),
        ("更稳一点", "analyze", "analyze_adjustment"),
        ("降风险", "analyze", "analyze_adjustment"),
        ("按这个思路调", "analyze", "analyze_adjustment"),
    ])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_analysis_with_existing_plan(self, user_text, verb, expected, volunteer_model):
        # 旧路径
        old_result = _normalize_adjustment_action_family("generate_plan", user_text, HAS_PLAN)
        assert old_result == expected

        # 新路径：当用户说"更稳一点"，LLM 应输出 verb=analyze 而非 generate
        frame = _frame(verb, raw_utterance=user_text)
        resolution = resolver.resolve(frame, HAS_PLAN)
        assert resolution.action_family == expected

    @pytest.mark.parametrize("user_text", [
        "重新生成方案",
        "重新给我一版方案",
        "覆盖当前方案",
    ])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_explicit_regeneration_stays(self, user_text, volunteer_model):
        # 旧路径：显式重新生成不降级
        old_result = _normalize_adjustment_action_family("generate_plan", user_text, HAS_PLAN)
        assert old_result == "generate_plan"

        # 新路径：LLM 应输出 verb=generate
        frame = _frame("generate", raw_utterance=user_text)
        resolution = resolver.resolve(frame, HAS_PLAN)
        assert resolution.action_family == "generate_plan"


class TestNormalizationRule2:
    """Rule 2: preview_compensation + !filled + stability_fill → add_units"""

    @pytest.mark.parametrize("user_text,expected", [
        ("补几个更稳的", "add_units"),
        ("加几个保底", "add_units"),
        ("风险低一点的志愿", "add_units"),
        ("补稳几个", "add_units"),
    ])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_stability_fill_not_filled(self, user_text, expected, volunteer_model):
        # 旧路径
        old_result = _normalize_adjustment_action_family("preview_compensation", user_text, NOT_FILLED)
        assert old_result == expected

        # 新路径：当用户说"补几个更稳的"，LLM 应输出 verb=add + scope.tier="稳"
        frame = _frame("add", tier="稳", raw_utterance=user_text)
        resolution = resolver.resolve(frame, NOT_FILLED)
        assert resolution.action_family == expected


class TestNormalizationRule3:
    """Rule 3: regenerate_order + structural_rebalance → replace_units"""

    @pytest.mark.parametrize("user_text", [
        "别动总数，多弄一些保区的",
        "总数不变，压冲区增加保区",
        "保持总数不变，本地保底多一些",
    ])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_structural_rebalance_to_replace(self, user_text, volunteer_model):
        # 旧路径
        old_result = _normalize_adjustment_action_family("regenerate_order", user_text, HAS_PLAN)
        assert old_result == "replace_units"

        # 新路径：LLM 应识别出 verb=replace + scope.tier
        frame = _frame("replace", tier="保", raw_utterance=user_text)
        resolution = resolver.resolve(frame, HAS_PLAN)
        assert resolution.action_family == "replace_units"


class TestNormalizationRule4:
    """Rule 4: preview_compensation + filled_to_target → analyze_adjustment"""

    @pytest.mark.parametrize("user_text", [
        "看看补齐建议",
        "有什么可以补的",
    ])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_compensation_when_filled(self, user_text, volunteer_model):
        # 旧路径：方案已满时 compensation → analyze
        old_result = _normalize_adjustment_action_family("preview_compensation", user_text, FILLED)
        assert old_result == "analyze_adjustment"

        # 新路径：ActionResolver 有相同的 Rule 4
        frame = _frame("compensate", raw_utterance=user_text)
        resolution = resolver.resolve(frame, FILLED)
        assert resolution.action_family == "analyze_adjustment"


class TestNormalizationRule5:
    """Rule 5: regenerate_order + !explicit_reorder + analysis → analyze_adjustment"""

    @pytest.mark.parametrize("user_text,verb,expected", [
        # 旧路径：LLM 选了 regenerate_order 但 user_goal 是分析请求 → normalize 降级
        # 新路径：LLM 应输出 verb=analyze
        ("怎么优化方案", "analyze", "analyze_adjustment"),
        ("更合理一些", "analyze", "analyze_adjustment"),
    ])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_analysis_instead_of_reorder(self, user_text, verb, expected, volunteer_model):
        # 旧路径
        old_result = _normalize_adjustment_action_family("regenerate_order", user_text, HAS_PLAN)
        assert old_result == expected

        # 新路径
        frame = _frame(verb, raw_utterance=user_text)
        resolution = resolver.resolve(frame, HAS_PLAN)
        assert resolution.action_family == expected

    @pytest.mark.parametrize("user_text", [
        "帮我重排一下",
        "重新排序",
        "排一排",
    ])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_explicit_reorder_stays(self, user_text, volunteer_model):
        # 旧路径：显式 reorder 不降级
        old_result = _normalize_adjustment_action_family("regenerate_order", user_text, HAS_PLAN)
        assert old_result == "regenerate_order"

        # 新路径：verb=reorder 不触发 rule 5
        frame = _frame("reorder", raw_utterance=user_text)
        resolution = resolver.resolve(frame, HAS_PLAN)
        assert resolution.action_family == "regenerate_order"


# ---------------------------------------------------------------------------
# 端到端真实场景（模拟完整对话链路）
# ---------------------------------------------------------------------------


class TestEndToEndScenarios:
    """模拟真实用户话语 → IntentFrame → ActionResolver 的完整链路。"""

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_user_wants_safer_plan_with_existing(self, volunteer_model):
        """用户说"更稳一点"，方案已存在"""
        frame = _frame("analyze", raw_utterance="更稳一点")
        resolution = resolver.resolve(frame, HAS_PLAN)
        assert resolution.action_family == "analyze_adjustment"
        assert resolution.stage == "apply"

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_user_wants_to_replace_expensive(self, volunteer_model):
        """用户说"把高收费的换掉" + review issue"""
        frame = _frame(
            "replace",
            review_issue_code="high_tuition",
            raw_utterance="把高收费的换掉",
        )
        resolution = resolver.resolve(frame, HAS_PLAN)
        # review issue scope_kind=item_removal, 无 filters → 降级为 remove
        assert resolution.action_family == "remove_units"
        assert resolution.review_issue_override is True

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_user_wants_to_replace_expensive_with_filters(self, volunteer_model):
        """用户说"把高收费的换成正常收费的" + 有替换范围"""
        frame = _frame(
            "replace",
            review_issue_code="high_tuition",
            school_keyword="北京",
            raw_utterance="把高收费的换成北京的正常收费志愿",
        )
        resolution = resolver.resolve(frame, HAS_PLAN)
        # 有 filters → 保留 replace_units
        assert resolution.action_family == "replace_units"

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_user_adds_specific_volunteers(self, volunteer_model):
        """用户说"加上这几个"，带具体 ID"""
        frame = _frame(
            "add",
            volunteer_refs=["vol_001", "vol_002"],
            raw_utterance="加上这两个",
        )
        resolution = resolver.resolve(frame, HAS_PLAN)
        assert resolution.action_family == "add_units"
        assert resolution.missing_inputs == []

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_user_removes_without_ref(self, volunteer_model):
        """用户说"删掉"但没说删哪个"""
        frame = _frame("remove", raw_utterance="删掉")
        resolution = resolver.resolve(frame, HAS_PLAN)
        assert resolution.action_family == "remove_units"
        assert "volunteer_ids" in resolution.missing_inputs

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_user_first_time_generate(self, volunteer_model):
        """首次生成方案"""
        frame = _frame("generate", raw_utterance="帮我出一版方案")
        resolution = resolver.resolve(frame, NO_PLAN)
        assert resolution.action_family == "generate_plan"
        assert resolution.requires_confirmation is True

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_user_regenerate_with_existing(self, volunteer_model):
        """已有方案，显式要求重新生成"""
        frame = _frame("generate", raw_utterance="重新生成方案")
        resolution = resolver.resolve(frame, HAS_PLAN)
        assert resolution.action_family == "generate_plan"

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_user_compensation_plan_not_full(self, volunteer_model):
        """方案未满，用户要补齐"""
        frame = _frame("compensate", raw_utterance="帮我补齐方案")
        resolution = resolver.resolve(frame, NOT_FILLED)
        assert resolution.action_family == "preview_compensation"

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_user_move_to_position(self, volunteer_model):
        """用户说"把北京工业大学移到第5位"""
        frame = _frame(
            "move",
            volunteer_refs=["vol_005"],
            position=5,
            raw_utterance="把北京工业大学移到第5位",
        )
        resolution = resolver.resolve(frame, HAS_PLAN)
        assert resolution.action_family == "move_unit"
        assert resolution.missing_inputs == []

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_query_specific_volunteer(self, volunteer_model):
        """用户问"北京工业大学的志愿在哪"""
        frame = _frame(
            "query",
            topic="school",
            volunteer_refs=["北京工业大学"],
            raw_utterance="北京工业大学的志愿排第几",
        )
        resolution = resolver.resolve(frame, HAS_PLAN)
        assert resolution.action_family == "query_ordered"

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_query_candidates_with_filters(self, volunteer_model):
        """用户问"稳区有哪些北京的候选"""
        frame = _frame(
            "query",
            topic="region",
            tier="稳",
            province="北京",
            raw_utterance="稳区有哪些北京的候选",
        )
        resolution = resolver.resolve(frame, HAS_PLAN)
        assert resolution.action_family == "query_candidates"


# ---------------------------------------------------------------------------
# Intentional divergences: 新路径比旧路径更准确的场景
# ---------------------------------------------------------------------------


class TestIntentionalDivergences:
    """记录 ActionResolver 比旧关键词匹配更准确的已知改进点。"""

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_old_false_positive_stability_fill(self, volunteer_model):
        """旧逻辑 false positive: "先给我一版" 触发 stability_fill 规则

        旧路径：preview_compensation + "先给我一版" → add_units（误判）
        新路径：LLM 应正确输出 verb=generate 或 verb=compensate，不会被关键词误匹配
        """
        # 旧路径会把 "先给我一版" 误判为 stability_fill
        old_result = _normalize_adjustment_action_family("preview_compensation", "先给我一版", NOT_FILLED)
        assert old_result == "add_units"  # 旧逻辑的 false positive

        # 新路径：用户说"先给我一版"应该是 generate 而不是 add
        frame = _frame("generate", raw_utterance="先给我一版")
        resolution = resolver.resolve(frame, NOT_FILLED)
        assert resolution.action_family == "generate_plan"  # 新路径更准确

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_old_false_positive_analysis_on_reorder(self, volunteer_model):
        """旧逻辑 false positive: "怎么优化" + regenerate_order → analyze

        当用户确实想重排但表达含"优化"时，旧逻辑误降级。
        新路径：LLM 明确选了 verb=reorder 就不会被降级。
        """
        # 旧路径会把 "优化一下排序" 降级为 analyze
        old_result = _normalize_adjustment_action_family("regenerate_order", "优化一下排序", HAS_PLAN)
        assert old_result == "analyze_adjustment"  # 旧逻辑误降级

        # 新路径：如果 LLM 判断用户确实想 reorder
        frame = _frame("reorder", raw_utterance="优化一下排序")
        resolution = resolver.resolve(frame, HAS_PLAN)
        assert resolution.action_family == "regenerate_order"  # 新路径更准确
