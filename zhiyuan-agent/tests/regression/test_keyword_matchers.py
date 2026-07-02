"""回归基线：Plan 路由不再依赖关键词 matcher。

该文件保留原文件名，避免测试清单漂移；内容改为验证结构化字段契约。
"""

from __future__ import annotations

import pytest

from app.models.intent_frame import IntentFrame, ScopeSpec, TargetSpec
from app.resolver.action_resolver import ActionResolver
from app.tools.review_issue_registry import (
    normalize_review_issue_code,
    review_issue_default_action_family,
    review_issue_label,
    review_issue_scope_kind,
    review_issue_supported_action_families,
)
from tests.factories import make_plan_context_inputs


resolver = ActionResolver()
HAS_PLAN = make_plan_context_inputs(draft_count=30, ordered_count=30, target_count=30)


def _frame(verb: str, **kwargs) -> IntentFrame:
    target_fields = {}
    scope_fields = {}
    for key in (
        "volunteer_refs",
        "unit_refs",
        "school_names",
        "major_names",
        "region_names",
        "review_issue_code",
        "source_position",
        "position",
    ):
        if key in kwargs:
            target_fields[key] = kwargs.pop(key)
    for key in (
        "tier",
        "province",
        "school_tags",
        "major_tags",
        "school_keyword",
        "major_keyword",
        "limit",
        "sort_field",
        "preserve_count",
    ):
        if key in kwargs:
            scope_fields[key] = kwargs.pop(key)
    return IntentFrame(
        task_layer="plan",
        topic=kwargs.pop("topic", "general"),
        verb=verb,
        raw_utterance=kwargs.pop("raw_utterance", ""),
        target=TargetSpec(**target_fields),
        scope=ScopeSpec(**scope_fields),
    )


@pytest.mark.parametrize(
    "verb,scope_kwargs,expected_family",
    [
        ("analyze", {}, "analyze_adjustment"),
        ("add", {"tier": "稳"}, "add_units"),
        ("replace", {"tier": "保", "preserve_count": True}, "replace_units"),
        ("reorder", {}, "regenerate_order"),
        ("reorder", {"sort_field": "schoolRank"}, "sort_ordered_plan"),
        ("review", {}, "review_plan"),
    ],
)
@pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
def test_action_decision_comes_from_structured_verb_and_scope(
    verb: str,
    scope_kwargs: dict,
    expected_family: str,
    volunteer_model: str,
):
    result = resolver.resolve(_frame(verb, **scope_kwargs), HAS_PLAN)
    assert result.action_family == expected_family


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
@pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
def test_review_issue_registry_is_code_based(
    code: str,
    expected_label: str,
    expected_kind: str,
    expected_default: str | None,
    expected_supported: list[str],
    volunteer_model: str,
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


@pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
def test_item_removal_issue_requires_structured_review_issue_code(volunteer_model: str):
    without_code = resolver.resolve(_frame("remove", raw_utterance="删掉高收费"), HAS_PLAN)
    assert without_code.action_family == "remove_units"
    assert without_code.review_issue_override is False
    assert "volunteer_ids" in without_code.missing_inputs

    with_code = resolver.resolve(
        _frame("remove", review_issue_code="high_tuition", raw_utterance="删掉高收费"),
        HAS_PLAN,
    )
    assert with_code.action_family == "remove_units"
    assert with_code.missing_inputs == []
    assert with_code.action.review_issue.code == "high_tuition"

    query_with_code = resolver.resolve(
        _frame("query", review_issue_code="high_tuition", raw_utterance="处理高收费"),
        HAS_PLAN,
    )
    assert query_with_code.action_family == "review_plan"
    assert query_with_code.review_issue_override is True


@pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
def test_sort_field_must_be_structured(volunteer_model: str):
    text_only = resolver.resolve(_frame("reorder", raw_utterance="按院校层次排"), HAS_PLAN)
    assert text_only.action_family == "regenerate_order"

    structured = resolver.resolve(_frame("reorder", sort_field="schoolRank"), HAS_PLAN)
    assert structured.action_family == "sort_ordered_plan"


@pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
def test_unit_position_must_be_structured(volunteer_model: str):
    missing = resolver.resolve(_frame("move", raw_utterance="把第3个专业组移到第5位"), HAS_PLAN)
    assert missing.action_family == "move_unit"
    assert "volunteer_id" in missing.missing_inputs

    structured = resolver.resolve(
        _frame("move", unit_refs=[], source_position=3, position=5),
        HAS_PLAN,
    )
    assert structured.action_family == "move_ordered_unit"
    assert structured.missing_inputs == []
