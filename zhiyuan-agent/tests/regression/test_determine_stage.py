"""回归基线：_determine_stage 的全组合 truth table。

逻辑优先级：
1. current_stage 已经是 analyze/preview/apply/review → 直接透传
2. query_state / query_draft / query_ordered / query_candidates / analyze_adjustment / preview_compensation → apply
3. missing_inputs → analyze
4. review_plan → review
5. user_confirmed → apply
6. fallback → preview
"""

from __future__ import annotations

import pytest

from app.tools.plan_orchestration_tool import _determine_stage


# ---------------------------------------------------------------------------
# Priority 1: current_stage 已指定 → 直接透传
# ---------------------------------------------------------------------------

class TestCurrentStagePassthrough:
    """current_stage 已经是有效值时直接返回，忽略其他条件。"""

    @pytest.mark.parametrize("current_stage", ["analyze", "preview", "apply", "review"])
    @pytest.mark.parametrize("action_family", ["add_units", "remove_units", "generate_plan", "review_plan"])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_passthrough(self, current_stage: str, action_family: str, volunteer_model: str):
        result = _determine_stage(
            action_family,
            user_confirmed=True,
            missing_inputs=["volunteer_ids"],
            current_stage=current_stage,
        )
        assert result == current_stage


# ---------------------------------------------------------------------------
# Priority 2: 查询/分析类 action → apply
# ---------------------------------------------------------------------------

class TestQueryActionsAlwaysApply:
    """查询和分析类 action 总是返回 apply。"""

    @pytest.mark.parametrize("action_family", [
        "query_state",
        "query_draft",
        "query_ordered",
        "query_candidates",
        "analyze_adjustment",
        "preview_compensation",
    ])
    @pytest.mark.parametrize("user_confirmed", [True, False])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_query_actions_apply(self, action_family: str, user_confirmed: bool, volunteer_model: str):
        result = _determine_stage(
            action_family,
            user_confirmed=user_confirmed,
            missing_inputs=[],
            current_stage=None,
        )
        assert result == "apply"

    @pytest.mark.parametrize("action_family", [
        "query_state",
        "analyze_adjustment",
        "preview_compensation",
    ])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_query_actions_apply_even_with_missing(self, action_family: str, volunteer_model: str):
        """查询类 action 即使有 missing_inputs 也返回 apply（优先级高于 missing_inputs 检查）。"""
        result = _determine_stage(
            action_family,
            user_confirmed=False,
            missing_inputs=["some_field"],
            current_stage=None,
        )
        assert result == "apply"


# ---------------------------------------------------------------------------
# Priority 3: missing_inputs → analyze
# ---------------------------------------------------------------------------

class TestMissingInputsAnalyze:
    """有 missing_inputs 且不是查询类 action → analyze。"""

    @pytest.mark.parametrize("action_family", [
        "add_units",
        "remove_units",
        "move_unit",
        "replace_units",
        "regenerate_order",
        "generate_plan",
    ])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_missing_inputs_analyze(self, action_family: str, volunteer_model: str):
        result = _determine_stage(
            action_family,
            user_confirmed=False,
            missing_inputs=["volunteer_ids"],
            current_stage=None,
        )
        assert result == "analyze"

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_missing_inputs_overrides_confirm(self, volunteer_model: str):
        """missing_inputs 优先级高于 user_confirmed。"""
        result = _determine_stage(
            "add_units",
            user_confirmed=True,
            missing_inputs=["volunteer_ids"],
            current_stage=None,
        )
        assert result == "analyze"


# ---------------------------------------------------------------------------
# Priority 4: review_plan → review
# ---------------------------------------------------------------------------

class TestReviewPlanStage:
    """review_plan action → review。"""

    @pytest.mark.parametrize("user_confirmed", [True, False])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_review_plan(self, user_confirmed: bool, volunteer_model: str):
        result = _determine_stage(
            "review_plan",
            user_confirmed=user_confirmed,
            missing_inputs=[],
            current_stage=None,
        )
        assert result == "review"


# ---------------------------------------------------------------------------
# Priority 5: user_confirmed → apply
# ---------------------------------------------------------------------------

class TestUserConfirmedApply:
    """user_confirmed=True → apply。"""

    @pytest.mark.parametrize("action_family", [
        "add_units",
        "remove_units",
        "move_unit",
        "replace_units",
        "regenerate_order",
        "generate_plan",
    ])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_confirmed_apply(self, action_family: str, volunteer_model: str):
        result = _determine_stage(
            action_family,
            user_confirmed=True,
            missing_inputs=[],
            current_stage=None,
        )
        assert result == "apply"


# ---------------------------------------------------------------------------
# Priority 6: fallback → preview
# ---------------------------------------------------------------------------

class TestFallbackPreview:
    """无匹配条件 → preview。"""

    @pytest.mark.parametrize("action_family", [
        "add_units",
        "remove_units",
        "move_unit",
        "replace_units",
        "regenerate_order",
        "generate_plan",
    ])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_fallback_preview(self, action_family: str, volunteer_model: str):
        result = _determine_stage(
            action_family,
            user_confirmed=False,
            missing_inputs=[],
            current_stage=None,
        )
        assert result == "preview"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_none_current_stage_not_passthrough(self, volunteer_model: str):
        """current_stage=None 不触发透传。"""
        result = _determine_stage(
            "add_units",
            user_confirmed=False,
            missing_inputs=[],
            current_stage=None,
        )
        assert result == "preview"

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_empty_string_current_stage_not_passthrough(self, volunteer_model: str):
        """current_stage='' 不在 {analyze, preview, apply, review} 中 → 不透传。"""
        result = _determine_stage(
            "add_units",
            user_confirmed=False,
            missing_inputs=[],
            current_stage="",
        )
        assert result == "preview"

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_unknown_current_stage_not_passthrough(self, volunteer_model: str):
        """current_stage 为非法值时不透传。"""
        result = _determine_stage(
            "add_units",
            user_confirmed=False,
            missing_inputs=[],
            current_stage="unknown",
        )
        assert result == "preview"

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_empty_missing_inputs_list(self, volunteer_model: str):
        """空列表 missing_inputs 不触发 analyze。"""
        result = _determine_stage(
            "add_units",
            user_confirmed=False,
            missing_inputs=[],
            current_stage=None,
        )
        assert result == "preview"
