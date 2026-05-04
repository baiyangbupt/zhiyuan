"""typed_actions 模型单元测试。"""

import pytest
from pydantic import TypeAdapter, ValidationError

from app.models.typed_actions import (
    ACTION_TYPE_TO_FAMILY,
    AddUnitsAction,
    AnalyzeAdjustmentAction,
    ApplyCompensationAction,
    GeneratePlanAction,
    MoveUnitAction,
    PinUnitAction,
    PlanAction,
    PreviewCompensationAction,
    QueryCandidatesAction,
    QueryDraftAction,
    QueryOrderedAction,
    QueryStateAction,
    RegenerateOrderAction,
    RemoveUnitsAction,
    ReplaceUnitsAction,
    ReviewIssueRef,
    ReviewPlanAction,
    SelectionFilters,
    UnpinUnitAction,
)


# ---------------------------------------------------------------------------
# ReviewIssueRef
# ---------------------------------------------------------------------------

class TestReviewIssueRef:
    """ReviewIssueRef 基本行为。"""

    def test_defaults(self):
        ref = ReviewIssueRef(code="high_tuition")
        assert ref.code == "high_tuition"
        assert ref.scope_mode == "full_issue"
        assert ref.label == ""
        assert ref.narrowed_refs == []

    def test_narrowed_scope(self):
        ref = ReviewIssueRef(
            code="cooperative_program",
            scope_mode="narrowed_issue",
            label="中外合作",
            narrowed_refs=["@3", "@7"],
        )
        assert ref.scope_mode == "narrowed_issue"
        assert len(ref.narrowed_refs) == 2


# ---------------------------------------------------------------------------
# SelectionFilters
# ---------------------------------------------------------------------------

class TestSelectionFilters:
    """SelectionFilters 筛选条件。"""

    def test_defaults(self):
        f = SelectionFilters()
        assert f.province == ""
        assert f.school_tags == []
        assert f.major_tags == []
        assert f.school_keyword == ""
        assert f.major_keyword == ""
        assert f.tier == ""
        assert f.limit == 5

    def test_has_filters_false_when_empty(self):
        assert not SelectionFilters().has_filters

    @pytest.mark.parametrize("field,value", [
        ("province", "北京"),
        ("school_tags", ["985"]),
        ("major_tags", ["工学"]),
        ("school_keyword", "大学"),
        ("major_keyword", "计算机"),
        ("tier", "冲"),
    ])
    def test_has_filters_true(self, field, value):
        f = SelectionFilters(**{field: value})
        assert f.has_filters

    def test_to_atomic_filters_empty(self):
        """空筛选条件 → 空 dict。"""
        assert SelectionFilters().to_atomic_filters() == {}

    def test_to_atomic_filters_full(self):
        f = SelectionFilters(
            province="北京",
            school_tags=["985", "211"],
            major_tags=["工学"],
            school_keyword="工业",
            major_keyword="计算机",
            tier="稳",
            limit=10,
        )
        result = f.to_atomic_filters()
        assert result["province_keyword"] == "北京"
        assert result["school_tags"] == ["985", "211"]
        assert result["major_tags"] == ["工学"]
        assert result["school_keyword"] == "工业"
        assert result["major_keyword"] == "计算机"
        assert result["tier"] == "稳"
        assert result["limit"] == 10

    def test_to_atomic_filters_default_limit_not_included(self):
        """默认 limit=5 不出现在 atomic filters 中。"""
        f = SelectionFilters(province="上海")
        result = f.to_atomic_filters()
        assert "limit" not in result
        assert result["province_keyword"] == "上海"

    def test_tier_validation(self):
        with pytest.raises(ValidationError):
            SelectionFilters(tier="超冲")


# ---------------------------------------------------------------------------
# 各类型化动作
# ---------------------------------------------------------------------------

class TestQueryActions:
    """查询类动作。"""

    def test_query_state(self):
        a = QueryStateAction(reason="查看方案状态")
        assert a.action_type == "query_state"
        assert a.reason == "查看方案状态"

    def test_query_draft(self):
        a = QueryDraftAction()
        assert a.action_type == "query_draft"

    def test_query_ordered(self):
        a = QueryOrderedAction(volunteer_refs=["@1", "@5"])
        assert a.action_type == "query_ordered"
        assert a.volunteer_refs == ["@1", "@5"]

    def test_query_candidates(self):
        a = QueryCandidatesAction(
            filters=SelectionFilters(province="北京", tier="冲"),
        )
        assert a.action_type == "query_candidates"
        assert a.filters.province == "北京"


class TestGenerateAnalyzeActions:
    """生成/分析类动作。"""

    def test_generate_plan(self):
        a = GeneratePlanAction(force_regenerate=True)
        assert a.action_type == "generate_plan"
        assert a.force_regenerate is True

    def test_generate_plan_default(self):
        a = GeneratePlanAction()
        assert a.force_regenerate is False

    def test_analyze_adjustment(self):
        a = AnalyzeAdjustmentAction(reason="用户要求分析")
        assert a.action_type == "analyze_adjustment"

    def test_review_plan(self):
        a = ReviewPlanAction()
        assert a.action_type == "review_plan"


class TestCompensationActions:
    """补偿类动作。"""

    def test_preview_compensation(self):
        a = PreviewCompensationAction()
        assert a.action_type == "preview_compensation"

    def test_apply_compensation(self):
        a = ApplyCompensationAction(reason="用户确认补偿")
        assert a.action_type == "apply_compensation"


class TestMutationActions:
    """志愿增删改类动作。"""

    def test_add_units_by_ids(self):
        a = AddUnitsAction(volunteer_ids=["v1", "v2"])
        assert a.action_type == "add_units"
        assert a.has_target
        assert a.volunteer_ids == ["v1", "v2"]

    def test_add_units_by_filters(self):
        a = AddUnitsAction(
            selection_filters=SelectionFilters(province="北京", tier="稳"),
        )
        assert a.has_target
        assert a.selection_filters.has_filters

    def test_add_units_no_target(self):
        a = AddUnitsAction()
        assert not a.has_target

    def test_remove_units_by_ids(self):
        a = RemoveUnitsAction(volunteer_ids=["v3"])
        assert a.has_target

    def test_remove_units_by_review_issue(self):
        a = RemoveUnitsAction(
            review_issue=ReviewIssueRef(code="high_tuition"),
        )
        assert a.has_target

    def test_remove_units_no_target(self):
        a = RemoveUnitsAction()
        assert not a.has_target

    def test_move_unit(self):
        a = MoveUnitAction(volunteer_id="v5", target_position=3)
        assert a.action_type == "move_unit"
        assert a.volunteer_id == "v5"
        assert a.target_position == 3

    def test_pin_unit(self):
        a = PinUnitAction(volunteer_id="v1")
        assert a.action_type == "pin_unit"

    def test_unpin_unit(self):
        a = UnpinUnitAction(volunteer_id="v2")
        assert a.action_type == "unpin_unit"

    def test_replace_units(self):
        a = ReplaceUnitsAction(
            remove_ids=["v1", "v2"],
            replacement_filters=SelectionFilters(tier="稳"),
            review_issue=ReviewIssueRef(code="high_tuition"),
        )
        assert a.action_type == "replace_units"
        assert a.has_target
        assert len(a.remove_ids) == 2

    def test_replace_units_no_target(self):
        a = ReplaceUnitsAction()
        assert not a.has_target

    def test_regenerate_order(self):
        a = RegenerateOrderAction(structural_rebalance=True)
        assert a.action_type == "regenerate_order"
        assert a.structural_rebalance is True


# ---------------------------------------------------------------------------
# Discriminated Union (PlanAction)
# ---------------------------------------------------------------------------

_plan_action_adapter = TypeAdapter(PlanAction)


class TestPlanActionUnion:
    """PlanAction 判别联合体。"""

    @pytest.mark.parametrize("action_type,expected_cls", [
        ("query_state", QueryStateAction),
        ("query_draft", QueryDraftAction),
        ("query_ordered", QueryOrderedAction),
        ("query_candidates", QueryCandidatesAction),
        ("generate_plan", GeneratePlanAction),
        ("analyze_adjustment", AnalyzeAdjustmentAction),
        ("review_plan", ReviewPlanAction),
        ("preview_compensation", PreviewCompensationAction),
        ("apply_compensation", ApplyCompensationAction),
        ("add_units", AddUnitsAction),
        ("remove_units", RemoveUnitsAction),
        ("move_unit", MoveUnitAction),
        ("pin_unit", PinUnitAction),
        ("unpin_unit", UnpinUnitAction),
        ("replace_units", ReplaceUnitsAction),
        ("regenerate_order", RegenerateOrderAction),
    ])
    def test_discriminator_dispatch(self, action_type, expected_cls):
        """action_type 字段正确分发到对应类。"""
        data = {"action_type": action_type}
        action = _plan_action_adapter.validate_python(data)
        assert isinstance(action, expected_cls)

    def test_invalid_action_type(self):
        with pytest.raises(ValidationError):
            _plan_action_adapter.validate_python({"action_type": "nonexistent"})

    def test_missing_action_type(self):
        with pytest.raises(ValidationError):
            _plan_action_adapter.validate_python({})

    def test_union_with_extra_fields(self):
        """带有额外字段的分发。"""
        data = {
            "action_type": "add_units",
            "volunteer_ids": ["v1", "v2"],
            "reason": "补入候选",
        }
        action = _plan_action_adapter.validate_python(data)
        assert isinstance(action, AddUnitsAction)
        assert action.volunteer_ids == ["v1", "v2"]
        assert action.reason == "补入候选"

    def test_json_roundtrip(self):
        """JSON 序列化/反序列化。"""
        action = AddUnitsAction(
            volunteer_ids=["v1"],
            selection_filters=SelectionFilters(province="北京"),
            reason="测试",
        )
        json_str = _plan_action_adapter.dump_json(action)
        restored = _plan_action_adapter.validate_json(json_str)
        assert isinstance(restored, AddUnitsAction)
        assert restored.volunteer_ids == ["v1"]
        assert restored.selection_filters.province == "北京"


# ---------------------------------------------------------------------------
# ACTION_TYPE_TO_FAMILY 映射
# ---------------------------------------------------------------------------

class TestActionTypeToFamily:
    """ACTION_TYPE_TO_FAMILY 映射表。"""

    def test_all_16_families_present(self):
        assert len(ACTION_TYPE_TO_FAMILY) == 16

    def test_current_1to1_mapping(self):
        """当前 action_type 与 action_family 一一对应。"""
        for action_type, family in ACTION_TYPE_TO_FAMILY.items():
            assert action_type == family, (
                f"action_type={action_type} 与 family={family} 不一致"
            )

    @pytest.mark.parametrize("action_type", [
        "query_state", "query_draft", "query_ordered", "query_candidates",
        "generate_plan", "analyze_adjustment", "review_plan",
        "preview_compensation", "apply_compensation",
        "add_units", "remove_units", "move_unit",
        "pin_unit", "unpin_unit", "replace_units",
        "regenerate_order",
    ])
    def test_all_expected_types(self, action_type):
        assert action_type in ACTION_TYPE_TO_FAMILY
