"""回归基线：plan_orchestration_tool 中 8 个 _goal_requests_* 关键词匹配函数的 truth table。"""

from __future__ import annotations

import pytest

from app.tools.plan_orchestration_tool import (
    _goal_explicitly_requests_regeneration,
    _goal_explicitly_requests_reorder,
    _goal_requests_adjustment_analysis,
    _goal_requests_replacement,
    _goal_requests_stability_fill_preview,
    _goal_requests_structural_rebalance,
)
from app.tools.review_issue_registry import match_review_issue_code_from_goal
from tests.factories import make_review_issue


# ---------------------------------------------------------------------------
# _goal_requests_replacement
# ---------------------------------------------------------------------------

class TestGoalRequestsReplacement:
    @pytest.mark.parametrize("text,expected", [
        ("把高收费的换成正常的", True),
        ("替换成非中外合作的", True),
        ("补回几个稳的", True),
        ("补上两个保底的", True),
        ("补入候选", True),
        ("保持总数不变", True),
        ("补齐到96个", True),
        ("凑满方案", True),
        # 不匹配
        ("看看方案怎么样", False),
        ("帮我审查一下", False),
        ("重新排一下", False),
        ("更稳一点", False),
        ("删掉这几个", False),
        ("", False),
    ])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_truth_table(self, text: str, expected: bool, volunteer_model: str):
        assert _goal_requests_replacement(text) is expected


# ---------------------------------------------------------------------------
# _goal_explicitly_requests_reorder
# ---------------------------------------------------------------------------

class TestGoalExplicitlyRequestsReorder:
    @pytest.mark.parametrize("text,expected", [
        ("帮我重排一下", True),
        ("重新排序", True),
        ("重新排一下", True),
        ("排一排", True),
        ("排一下", True),
        ("帮我顺一下", True),
        ("弄顺了", True),
        ("理一下顺序", True),
        # 不匹配
        ("更稳一点", False),
        ("怎么优化", False),
        ("审查一下", False),
        ("看看方案", False),
        ("按这个思路来", False),
        ("", False),
    ])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_truth_table(self, text: str, expected: bool, volunteer_model: str):
        assert _goal_explicitly_requests_reorder(text) is expected


# ---------------------------------------------------------------------------
# _goal_requests_adjustment_analysis
# ---------------------------------------------------------------------------

class TestGoalRequestsAdjustmentAnalysis:
    @pytest.mark.parametrize("text,expected", [
        ("怎么调方案", True),
        ("怎么优化当前方案", True),
        ("更合理一些", True),
        ("更稳一点", True),
        ("稳一点", True),
        ("更保守一些", True),
        ("保守一点", True),
        ("风险低一点", True),
        ("降风险", True),
        ("按这个思路调", True),
        ("按更稳的思路来", True),
        ("弄一版更好的", True),
        ("优化一下方案", True),
        # 不匹配
        ("重新排一下", False),
        ("帮我审查", False),
        ("看看方案有什么建议", False),
        ("删掉高收费的", False),
        ("", False),
    ])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_truth_table(self, text: str, expected: bool, volunteer_model: str):
        assert _goal_requests_adjustment_analysis(text) is expected


# ---------------------------------------------------------------------------
# _goal_requests_stability_fill_preview
# ---------------------------------------------------------------------------

class TestGoalRequestsStabilityFillPreview:
    @pytest.mark.parametrize("text,expected", [
        ("补几个更稳的", True),
        ("稳一点的志愿", True),
        ("加几个保底", True),
        ("更保守一些", True),
        ("风险低一点的志愿", True),
        ("补稳几个", True),
        ("可确认预览", True),
        ("先给我一版", True),
        # 不匹配
        ("重新排一下", False),
        ("帮我审查", False),
        ("删掉这几个", False),
        ("补几个计算机的", False),
        ("", False),
    ])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_truth_table(self, text: str, expected: bool, volunteer_model: str):
        assert _goal_requests_stability_fill_preview(text) is expected


# ---------------------------------------------------------------------------
# _goal_requests_structural_rebalance
# ---------------------------------------------------------------------------

class TestGoalRequestsStructuralRebalance:
    @pytest.mark.parametrize("text,expected", [
        ("别动总数压冲区保区", True),  # 别动总数 + 保区
        ("总数不变压冲区", True),       # 总数不变 + 压冲区
        ("保持总数本地保底", True),     # 保持总数 + 本地保底
        ("保持总数本省保底", True),     # 保持总数 + 本省保底
        # 只有一半条件不匹配
        ("别动总数", False),
        ("保区", False),
        ("压冲区", False),
        ("本地保底", False),
        # 完全不匹配
        ("更稳一点", False),
        ("重新排一下", False),
        ("补几个稳的", False),
        ("", False),
    ])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_truth_table(self, text: str, expected: bool, volunteer_model: str):
        assert _goal_requests_structural_rebalance(text) is expected


# ---------------------------------------------------------------------------
# _goal_explicitly_requests_regeneration
# ---------------------------------------------------------------------------

class TestGoalExplicitlyRequestsRegeneration:
    @pytest.mark.parametrize("text,expected", [
        ("重新生成方案", True),
        ("重生成一版", True),
        ("重新出一版", True),
        ("重新给我一版方案", True),
        ("覆盖当前方案", True),
        ("覆盖掉当前方案", True),
        # 不匹配
        ("更稳一点", False),
        ("怎么优化", False),
        ("重新排一下", False),
        ("帮我审查", False),
        ("弄一版更好的", False),
        ("", False),
    ])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_truth_table(self, text: str, expected: bool, volunteer_model: str):
        assert _goal_explicitly_requests_regeneration(text) is expected


# ---------------------------------------------------------------------------
# match_review_issue_code_from_goal (review_issue_registry)
# ---------------------------------------------------------------------------

class TestMatchReviewIssueCodeFromGoal:
    """验证 review issue 关键词匹配的 truth table。"""

    @pytest.fixture()
    def review_issues(self) -> list[dict]:
        return [
            make_review_issue(code="high_tuition", label="高收费"),
            make_review_issue(code="cooperative_program", label="中外合作"),
            make_review_issue(code="admission_limit", label="限报条件"),
            make_review_issue(code="probability_inversion", label="概率倒挂"),
            make_review_issue(code="probability_gap", label="梯度断层"),
            make_review_issue(code="ratio_distribution", label="冲稳保配比"),
            make_review_issue(code="safety_guard", label="本省保底不足"),
            make_review_issue(code="count_validation", label="数量缺口"),
        ]

    @pytest.mark.parametrize("text,expected_code", [
        # 精确标签匹配
        ("删掉高收费的", "high_tuition"),
        ("把高学费项目去掉", "high_tuition"),
        ("中外合作的都不要", "cooperative_program"),
        ("中外合作办学的删掉", "cooperative_program"),
        ("限报的去掉", "admission_limit"),
        ("限制报考的删掉", "admission_limit"),
        ("概率倒挂怎么办", "probability_inversion"),
        ("录取概率倒挂的问题", "probability_inversion"),
        ("梯度断层怎么处理", "probability_gap"),
        ("冲稳保配比不合理", "ratio_distribution"),
        ("保区占比太少", "ratio_distribution"),
        ("本省保底不足", "safety_guard"),
        ("保底不足怎么补", "safety_guard"),
        ("数量不足", "count_validation"),
        ("补齐数量", "count_validation"),
        # 不匹配
        ("看看方案怎么样", None),
        ("帮我审查一下", None),
        ("更稳一点", None),
        ("重新排一下", None),
        ("", None),
    ])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_truth_table(self, text: str, expected_code: str | None, review_issues: list[dict], volunteer_model: str):
        result = match_review_issue_code_from_goal(text, review_issues)
        assert result == expected_code
