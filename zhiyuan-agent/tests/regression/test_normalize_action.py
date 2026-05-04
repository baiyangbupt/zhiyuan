"""回归基线：_normalize_adjustment_action_family 的全分支 truth table。

5 个条件分支：
1. generate_plan + has_plan + !explicit_regen + requests_analysis → analyze_adjustment
2. preview_compensation + !filled_to_target + requests_stability_fill → add_units
3. regenerate_order + structural_rebalance → replace_units
4. preview_compensation + filled_to_target → analyze_adjustment
5. regenerate_order + !explicit_reorder + requests_analysis → analyze_adjustment
fallback: 原值返回
"""

from __future__ import annotations

import pytest

from app.tools.plan_orchestration_tool import _normalize_adjustment_action_family
from tests.factories import make_plan_context_inputs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ctx(*, draft_count: int = 0, ordered_count: int = 0, target_count: int = 30) -> object:
    """快捷构造 PlanContextInputs。"""
    return make_plan_context_inputs(
        draft_count=draft_count,
        ordered_count=ordered_count,
        target_count=target_count,
    )


HAS_PLAN = _ctx(draft_count=30, ordered_count=30, target_count=30)
NO_PLAN = _ctx(draft_count=0, ordered_count=0, target_count=30)
NOT_FILLED = _ctx(draft_count=20, ordered_count=20, target_count=30)
FILLED = _ctx(draft_count=30, ordered_count=30, target_count=30)


# ---------------------------------------------------------------------------
# Branch 1: generate_plan → analyze_adjustment
# (has_plan + !explicit_regen + requests_analysis)
# ---------------------------------------------------------------------------

class TestBranch1GeneratePlanToAnalyze:
    """generate_plan + has_plan + 非重生成 + 请求分析 → analyze_adjustment。"""

    @pytest.mark.parametrize("user_goal,expected", [
        # 触发 _goal_requests_adjustment_analysis 的文本
        ("怎么调方案", "analyze_adjustment"),
        ("怎么优化当前方案", "analyze_adjustment"),
        ("更合理一些", "analyze_adjustment"),
        ("更稳一点", "analyze_adjustment"),
        ("稳一点", "analyze_adjustment"),
        ("更保守一些", "analyze_adjustment"),
        ("保守一点", "analyze_adjustment"),
        ("风险低一点", "analyze_adjustment"),
        ("降风险", "analyze_adjustment"),
        ("按这个思路调", "analyze_adjustment"),
        ("优化一下方案", "analyze_adjustment"),
        # 不触发 _goal_requests_adjustment_analysis → 保持 generate_plan
        ("生成方案", "generate_plan"),
        ("给我一个方案", "generate_plan"),
    ])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_has_plan_requests_analysis(self, user_goal: str, expected: str, volunteer_model: str):
        result = _normalize_adjustment_action_family("generate_plan", user_goal, HAS_PLAN)
        assert result == expected

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_no_plan_stays_generate(self, volunteer_model: str):
        """没有现有方案时，generate_plan 保持不变。"""
        result = _normalize_adjustment_action_family("generate_plan", "更稳一点", NO_PLAN)
        assert result == "generate_plan"

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_explicit_regen_stays_generate(self, volunteer_model: str):
        """显式要求重新生成时，即使请求分析也保持 generate_plan。"""
        result = _normalize_adjustment_action_family("generate_plan", "重新生成方案更稳一点", HAS_PLAN)
        assert result == "generate_plan"


# ---------------------------------------------------------------------------
# Branch 2: preview_compensation → add_units
# (!filled_to_target + requests_stability_fill)
# ---------------------------------------------------------------------------

class TestBranch2CompensationToAddUnits:
    """preview_compensation + 未满 + 请求稳定补充 → add_units。"""

    @pytest.mark.parametrize("user_goal,expected", [
        # 触发 _goal_requests_stability_fill_preview 的文本
        ("补几个更稳的", "add_units"),
        ("稳一点的志愿", "add_units"),
        ("加几个保底", "add_units"),
        ("更保守一些", "add_units"),
        ("风险低一点的志愿", "add_units"),
        ("补稳几个", "add_units"),
        ("可确认预览", "add_units"),
        ("先给我一版", "add_units"),
        # 不触发 → 走后续分支
        ("看看方案怎么样", "preview_compensation"),
    ])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_not_filled_requests_fill(self, user_goal: str, expected: str, volunteer_model: str):
        result = _normalize_adjustment_action_family("preview_compensation", user_goal, NOT_FILLED)
        assert result == expected


# ---------------------------------------------------------------------------
# Branch 3: regenerate_order → replace_units
# (structural_rebalance)
# ---------------------------------------------------------------------------

class TestBranch3ReorderToReplace:
    """regenerate_order + 结构重平衡 → replace_units。"""

    @pytest.mark.parametrize("user_goal,expected", [
        # 触发 _goal_requests_structural_rebalance 的文本 (AND 条件)
        ("别动总数压冲区保区", "replace_units"),
        ("总数不变压冲区", "replace_units"),
        ("保持总数本地保底", "replace_units"),
        ("保持总数本省保底", "replace_units"),
        # 只有一半条件 → 不触发（走 branch 5 或 fallback）
        ("别动总数", "regenerate_order"),  # 缺少保区/冲区 → fallback
        ("保区", "regenerate_order"),       # 缺少总数 → fallback
    ])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_structural_rebalance(self, user_goal: str, expected: str, volunteer_model: str):
        result = _normalize_adjustment_action_family("regenerate_order", user_goal, HAS_PLAN)
        assert result == expected


# ---------------------------------------------------------------------------
# Branch 4: preview_compensation → analyze_adjustment
# (filled_to_target)
# ---------------------------------------------------------------------------

class TestBranch4CompensationFilledToAnalyze:
    """preview_compensation + 已满额 → analyze_adjustment。"""

    @pytest.mark.parametrize("user_goal", [
        "看看方案怎么样",
        "审查一下",
        "补几个更稳的",   # 即使请求补稳，已满额也走 analyze
        "",
    ])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_filled_to_target(self, user_goal: str, volunteer_model: str):
        result = _normalize_adjustment_action_family("preview_compensation", user_goal, FILLED)
        assert result == "analyze_adjustment"


# ---------------------------------------------------------------------------
# Branch 5: regenerate_order → analyze_adjustment
# (!explicit_reorder + requests_analysis)
# ---------------------------------------------------------------------------

class TestBranch5ReorderToAnalyze:
    """regenerate_order + 非显式重排 + 请求分析 → analyze_adjustment。"""

    @pytest.mark.parametrize("user_goal,expected", [
        # 触发 _goal_requests_adjustment_analysis 但不触发 _goal_explicitly_requests_reorder
        ("更稳一点", "analyze_adjustment"),
        ("怎么优化", "analyze_adjustment"),
        ("更合理一些", "analyze_adjustment"),
        ("保守一点", "analyze_adjustment"),
        # 显式重排 → 保持 regenerate_order
        ("重新排一下", "regenerate_order"),
        ("重新排序", "regenerate_order"),
        ("排一排", "regenerate_order"),
        ("排一下", "regenerate_order"),
        # 既不请求分析也不显式重排 → fallback
        ("看看方案", "regenerate_order"),
    ])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_reorder_vs_analyze(self, user_goal: str, expected: str, volunteer_model: str):
        result = _normalize_adjustment_action_family("regenerate_order", user_goal, HAS_PLAN)
        assert result == expected


# ---------------------------------------------------------------------------
# Fallback: 不触发任何分支 → 原值返回
# ---------------------------------------------------------------------------

class TestFallbackPassthrough:
    """不匹配任何条件 → 原值透传。"""

    @pytest.mark.parametrize("action_family", [
        "query_state",
        "query_draft",
        "query_ordered",
        "query_candidates",
        "review_plan",
        "add_units",
        "remove_units",
        "move_unit",
        "pin_unit",
        "unpin_unit",
        "replace_units",
        "apply_compensation",
    ])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_other_actions_passthrough(self, action_family: str, volunteer_model: str):
        result = _normalize_adjustment_action_family(action_family, "更稳一点", HAS_PLAN)
        assert result == action_family

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_empty_action_family(self, volunteer_model: str):
        result = _normalize_adjustment_action_family("", "更稳一点", HAS_PLAN)
        assert result == ""

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_whitespace_action_family(self, volunteer_model: str):
        result = _normalize_adjustment_action_family("  query_state  ", "更稳一点", HAS_PLAN)
        assert result == "query_state"
