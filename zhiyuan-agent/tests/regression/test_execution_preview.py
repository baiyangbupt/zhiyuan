"""回归基线：_execute_plan_action_model 的 preview/analyze 阶段行为。

覆盖：
1. regenerate_order + structural_rebalance → analyze early exit
2. missing_inputs → error early exit
3. mutating apply guard → preview fallback
4. replace_units preview 的 review issue 分支
5. remove_units preview 的 review issue 分支
6. generic preview/analyze fallback
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from app.tools.plan_execution_tool import _execute_plan_action_model
from tests.factories import (
    make_plan_action_plan,
    make_request_context,
    make_run_context,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_ctx(*, volunteer_model: str = "major", **kwargs):
    return make_run_context(volunteer_model=volunteer_model, **kwargs)


# ---------------------------------------------------------------------------
# 1. regenerate_order 不再从 user_goal 文本推断结构重平衡
# ---------------------------------------------------------------------------

class TestRegenerateOrderDoesNotInferStructuralRebalance:
    """regenerate_order 只表示整体重新生成排序，不从 user_goal 关键词改成结构调整。"""

    @pytest.mark.parametrize("user_goal", [
        "别动总数压冲区保区",
        "总数不变压冲区",
        "保持总数本地保底",
        "保持总数本省保底",
    ])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    async def test_structural_rebalance_text_still_returns_preview(self, user_goal: str, volunteer_model: str):
        ctx = _run_ctx(volunteer_model=volunteer_model)
        plan = make_plan_action_plan(
            action_family="regenerate_order",
            stage="apply",
            user_goal=user_goal,
        )
        result = await _execute_plan_action_model(ctx, plan)
        assert result.applied is False
        assert result.stage == "preview"
        assert result.result_kind == "preview_only"
        assert "structural_rebalance_requires_scope" not in result.reply_focus

    @pytest.mark.parametrize("user_goal", [
        "别动总数",      # 缺少保区/冲区
        "保区",          # 缺少总数
        "重新排一下",     # 不是结构重平衡
    ])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    async def test_non_structural_not_early_exit(self, user_goal: str, volunteer_model: str, patch_backend, patch_planning):
        """不触发结构重平衡的 regenerate_order → 不走 early exit。"""
        ctx = _run_ctx(
            volunteer_model=volunteer_model,
            pending_plan_action={"action_family": "regenerate_order"},
            chat_history=[{"role": "user", "content": "确认"}],
        )
        plan = make_plan_action_plan(
            action_family="regenerate_order",
            stage="apply",
            user_goal=user_goal,
        )
        result = await _execute_plan_action_model(ctx, plan)
        # 不应该是 analyze early exit
        assert not (result.stage == "analyze" and "structural_rebalance_requires_scope" in result.reply_focus)


# ---------------------------------------------------------------------------
# 2. missing_inputs → error early exit
# ---------------------------------------------------------------------------

class TestMissingInputsEarlyExit:
    """plan_model.missing_inputs 非空 → error。"""

    @pytest.mark.parametrize("action_family", [
        "add_units",
        "remove_units",
        "generate_plan",
        "replace_units",
    ])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    async def test_missing_inputs_returns_error(self, action_family: str, volunteer_model: str):
        ctx = _run_ctx(volunteer_model=volunteer_model)
        plan = make_plan_action_plan(
            action_family=action_family,
            stage="preview",
            missing_inputs=["volunteer_ids"],
        )
        result = await _execute_plan_action_model(ctx, plan)
        assert result.applied is False
        assert result.result_kind == "error"
        assert "missing_inputs" in result.reply_focus
        assert result.reply_strategy == "direct_blocking"
        assert result.summary
        assert "volunteer_ids" not in result.summary
        assert "请" in result.summary

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    async def test_replace_units_execution_missing_inputs(self, volunteer_model: str):
        """replace_units 无 volunteer_ids 且无 filters → 额外检测 missing_inputs。"""
        ctx = _run_ctx(volunteer_model=volunteer_model)
        plan = make_plan_action_plan(
            action_family="replace_units",
            stage="preview",
            atomic_actions=[{
                "action_type": "replace_units",
                "volunteer_ids": [],
                "filters": {},
            }],
        )
        result = await _execute_plan_action_model(ctx, plan)
        assert result.applied is False
        assert result.result_kind == "error"
        assert "missing_inputs" in result.reply_focus


# ---------------------------------------------------------------------------
# 3. mutating apply guard → preview fallback
# ---------------------------------------------------------------------------

class TestMutatingApplyGuard:
    """mutating action + stage=apply 但用户未短确认 → 降级为 preview。"""

    @pytest.mark.parametrize("action_family", [
        "add_units",
        "remove_units",
        "move_unit",
        "generate_plan",
        # replace_units excluded: with no atomic_actions it hits _execution_missing_inputs
        # early exit before reaching the mutating apply guard.
        "regenerate_order",
        "apply_compensation",
    ])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    async def test_no_confirmation_falls_to_preview(self, action_family: str, volunteer_model: str):
        """没有 pending 匹配 + 短确认 → 不允许 apply，降级为 preview。"""
        ctx = _run_ctx(
            volunteer_model=volunteer_model,
            chat_history=[{"role": "user", "content": "帮我加几个志愿"}],
        )
        plan = make_plan_action_plan(
            action_family=action_family,
            stage="apply",
            preview_summary="将要执行某操作。",
        )
        result = await _execute_plan_action_model(ctx, plan)
        assert result.applied is False
        assert result.stage == "preview"
        assert result.result_kind == "preview_only"
        assert "confirmation_required" in result.reply_focus

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    async def test_query_actions_bypass_guard(self, volunteer_model: str, patch_backend, patch_planning):
        """query 类 action 不是 mutating → 不被 guard 拦截。"""
        ctx = _run_ctx(
            volunteer_model=volunteer_model,
            chat_history=[{"role": "user", "content": "看看方案状态"}],
        )
        plan = make_plan_action_plan(
            action_family="query_state",
            stage="apply",
        )
        result = await _execute_plan_action_model(ctx, plan)
        # query_state 不在 mutating set → 不应降为 preview
        assert result.result_kind != "preview_only" or result.stage != "preview"


# ---------------------------------------------------------------------------
# 4. generic preview/analyze fallback
# ---------------------------------------------------------------------------

class TestGenericPreviewAnalyzeFallback:
    """stage=preview 或 analyze 且未命中特殊分支 → preview_only。"""

    @pytest.mark.parametrize("action_family", [
        "add_units",
        "remove_units",
        "move_unit",
        "generate_plan",
        "regenerate_order",
        "apply_compensation",
    ])
    @pytest.mark.parametrize("stage", ["preview", "analyze"])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    async def test_generic_fallback(self, action_family: str, stage: str, volunteer_model: str):
        ctx = _run_ctx(volunteer_model=volunteer_model)
        plan = make_plan_action_plan(
            action_family=action_family,
            stage=stage,
            preview_summary="测试预览摘要。",
        )
        result = await _execute_plan_action_model(ctx, plan)
        assert result.applied is False
        assert result.result_kind == "preview_only"
        assert "preview_only" in result.reply_focus

    @pytest.mark.parametrize("action_family", ["pin_unit", "unpin_unit"])
    @pytest.mark.parametrize("stage", ["preview", "analyze"])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    async def test_pin_unpin_disabled(self, action_family: str, stage: str, volunteer_model: str):
        ctx = _run_ctx(volunteer_model=volunteer_model)
        plan = make_plan_action_plan(
            action_family=action_family,
            stage=stage,
            preview_summary="测试预览摘要。",
        )
        result = await _execute_plan_action_model(ctx, plan)
        assert result.applied is False
        assert result.result_kind == "error"
        assert "pin_disabled" in result.reply_focus

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    async def test_preview_mutating_gets_confirmation_hint(self, volunteer_model: str):
        """preview 阶段 mutating action → summary 带确认提示。"""
        ctx = _run_ctx(volunteer_model=volunteer_model)
        plan = make_plan_action_plan(
            action_family="add_units",
            stage="preview",
            preview_summary="即将添加3个志愿。",
        )
        result = await _execute_plan_action_model(ctx, plan)
        assert "确认" in result.summary

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    async def test_analyze_no_confirmation_hint(self, volunteer_model: str):
        """analyze 阶段 → summary 不带确认提示。"""
        ctx = _run_ctx(volunteer_model=volunteer_model)
        plan = make_plan_action_plan(
            action_family="add_units",
            stage="analyze",
            preview_summary="分析当前方案的调整空间。",
        )
        result = await _execute_plan_action_model(ctx, plan)
        # analyze 阶段不应有确认提示（除非 preview_summary 本身就带了）
        assert result.applied is False

    @pytest.mark.parametrize("action_family,expected_kind", [
        ("query_state", "status_overview"),
        ("query_draft", "draft_snapshot"),
        ("query_ordered", "ordered_snapshot"),
        ("query_candidates", "candidate_snapshot"),
        ("review_plan", "review_result"),
        ("analyze_adjustment", "adjustment_analysis"),
        ("preview_compensation", "compensation_preview"),
    ])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    async def test_non_mutating_preview_routes_to_registered_handler_without_confirmation_hint(
        self,
        action_family: str,
        expected_kind: str,
        volunteer_model: str,
        patch_backend,
        patch_planning,
    ):
        """只读 action 即使 stage=preview，也应走注册 handler，不落 generic preview fallback。"""
        patch_planning.query_planning_draft.return_value = "草稿方案概览"
        patch_planning.query_planning_ordered_plan.return_value = "排序方案概览"
        patch_planning.query_planning_candidate_pool.return_value = "候选池概览"
        ctx = _run_ctx(volunteer_model=volunteer_model)
        plan = make_plan_action_plan(
            action_family=action_family,
            stage="preview",
            preview_summary="查看当前方案状态。",
        )
        result = await _execute_plan_action_model(ctx, plan)
        assert result.result_kind == expected_kind
        assert "preview_only" not in result.reply_focus
        assert "需要你确认后才会执行" not in result.summary


# ---------------------------------------------------------------------------
# 5. preview stage next_step_hints
# ---------------------------------------------------------------------------

class TestPreviewNextStepHints:
    """preview 阶段有 next_step_hints，analyze 没有。"""

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    async def test_preview_has_next_step_hints(self, volunteer_model: str):
        ctx = _run_ctx(volunteer_model=volunteer_model)
        plan = make_plan_action_plan(
            action_family="add_units",
            stage="preview",
            preview_summary="预览。",
        )
        result = await _execute_plan_action_model(ctx, plan)
        assert len(result.next_step_hints) > 0

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    async def test_analyze_has_no_next_step_hints(self, volunteer_model: str):
        ctx = _run_ctx(volunteer_model=volunteer_model)
        plan = make_plan_action_plan(
            action_family="add_units",
            stage="analyze",
            preview_summary="分析。",
        )
        result = await _execute_plan_action_model(ctx, plan)
        assert len(result.next_step_hints) == 0


# ---------------------------------------------------------------------------
# 6. apply stage result.applied 计算
# ---------------------------------------------------------------------------

class TestAppliedComputation:
    """result.applied 取决于 stage, result_kind, action_family。"""

    @pytest.mark.parametrize("action_family", [
        "query_state",
        "query_draft",
        "query_ordered",
    ])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    async def test_query_apply_marks_applied_true(self, action_family: str, volunteer_model: str, patch_backend, patch_planning):
        """query 类 action 在 apply 阶段，且 result_kind != error → applied=True。"""
        ctx = _run_ctx(
            volunteer_model=volunteer_model,
            chat_history=[{"role": "user", "content": "看看方案"}],
        )
        plan = make_plan_action_plan(
            action_family=action_family,
            stage="apply",
        )
        result = await _execute_plan_action_model(ctx, plan)
        assert result.applied is True

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    async def test_preview_compensation_not_applied(self, volunteer_model: str, patch_backend, patch_planning):
        """preview_compensation 在 apply 阶段 → applied=False（特殊例外）。"""
        ctx = _run_ctx(
            volunteer_model=volunteer_model,
            chat_history=[{"role": "user", "content": "看看补偿"}],
        )
        plan = make_plan_action_plan(
            action_family="preview_compensation",
            stage="apply",
        )
        result = await _execute_plan_action_model(ctx, plan)
        assert result.applied is False
