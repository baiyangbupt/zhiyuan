"""回归基线：Plan 路由不再依赖关键词 matcher。

该文件保留原文件名，避免测试清单漂移；内容改为直接验证
``app.tools.review_issue_registry`` 的 code → label / scope / action 契约。

该模块由生产代码 ``app/zhiyuan_agent/tools.py`` 使用，本文件是它在测试套件中的
唯一覆盖，因此断言直接打在这 5 个函数上，不经任何中间层。
"""

from __future__ import annotations

import pytest

from app.tools.review_issue_registry import (
    normalize_review_issue_code,
    review_issue_default_action_family,
    review_issue_label,
    review_issue_scope_kind,
    review_issue_supported_action_families,
)


@pytest.mark.parametrize(
    "code,expected_label,expected_kind,expected_default,expected_supported",
    [
        ("high_tuition", "高收费", "item_replacement", "review_plan", ["replace_units", "remove_units"]),
        ("cooperative_program", "中外合作", "item_replacement", "review_plan", ["replace_units", "remove_units"]),
        ("probability_inversion", "概率倒挂", "structural", "sort_ordered_plan", ["sort_ordered_plan"]),
        ("probability_gap", "梯度断层", "structural", "preview_fix_proposal", ["preview_fix_proposal"]),
        ("count_validation", "数量缺口", "structural", "preview_fix_proposal", ["preview_fix_proposal"]),
        ("edge_score", "边缘分", "structural", "preview_fix_proposal", ["preview_fix_proposal"]),
        ("plan_update_notice", "招生计划更新提示", "informational", None, []),
    ],
)
def test_review_issue_registry_is_code_based(
    code: str,
    expected_label: str,
    expected_kind: str,
    expected_default: str | None,
    expected_supported: list[str],
):
    assert review_issue_label(code) == expected_label
    assert review_issue_scope_kind(code) == expected_kind
    assert review_issue_default_action_family(code) == expected_default
    assert review_issue_supported_action_families(code) == expected_supported


@pytest.mark.parametrize(
    "value,expected_code",
    [
        ("HIGH_TUITION_RISK", "high_tuition"),
        ("cooperative", "cooperative_program"),
        ("sino_foreign", "cooperative_program"),
        ("限报条件涉及1个志愿", "admission_limit"),
        ("特殊类型招生项目费用较高", "special_enrollment"),
        ("录取率倒挂，建议按概率重新排序", "probability_inversion"),
        ("冲区数量偏多，稳保承接不足", "tier_gap"),
        ("本省保底不足", "safety_guard"),
        ("组内安全垫不足", "group_inner_safety_guard"),
    ],
)
def test_review_issue_registry_normalizes_aliases(value: str, expected_code: str):
    assert normalize_review_issue_code(value) == expected_code
