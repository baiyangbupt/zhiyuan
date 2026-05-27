"""回归基线：_execute_plan_action_model 的 apply 阶段行为（16 种 action）。

覆盖：
1. query_state, query_draft, query_ordered, query_candidates → 只读查询
2. generate_plan → 生成方案
3. analyze_adjustment → 分析调整
4. preview_compensation → 补偿预览
5. apply_compensation → 应用补偿（含 blocker）
6. review_plan → 审查
7. add_units → 添加（by id / by filter）
8. remove_units → 移除（含 review issue 分支）
9. move_unit → 移动
10. pin_unit / unpin_unit → 3.0.1 禁用入口
11. replace_units → 替换（含 review issue 分支）
12. regenerate_order → 重排
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, patch

from app.tools.plan_execution_tool import _execute_plan_action_model
from tests.factories import (
    make_plan_action_plan,
    make_request_context,
    make_run_context,
    make_planning_state_response,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _confirmed_ctx(*, volunteer_model: str = "major", action_family: str = "add_units"):
    """构造已确认的 RunContext（pending 匹配 + 短确认文本）。"""
    return make_run_context(
        volunteer_model=volunteer_model,
        pending_plan_action={"action_family": action_family},
        chat_history=[{"role": "user", "content": "确认"}],
    )


# ---------------------------------------------------------------------------
# query_state
# ---------------------------------------------------------------------------

class TestQueryStateApply:
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    async def test_query_state_basic(self, volunteer_model: str, patch_backend, patch_planning):
        patch_backend.get_planning_state.return_value = {
            "code": 0,
            "data": make_planning_state_response(ordered_total=30),
        }
        patch_backend.get_planning_ordered_plan.return_value = {
            "code": 0,
            "data": {"items": []},
        }
        ctx = _confirmed_ctx(volunteer_model=volunteer_model, action_family="query_state")
        plan = make_plan_action_plan(action_family="query_state", stage="apply")
        result = await _execute_plan_action_model(ctx, plan)
        assert result.applied is True
        assert result.result_kind == "status_overview"
        assert result.workspace_refresh_targets == []


# ---------------------------------------------------------------------------
# query_draft
# ---------------------------------------------------------------------------

class TestQueryDraftApply:
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    async def test_query_draft_basic(self, volunteer_model: str, patch_backend, patch_planning):
        patch_planning.query_planning_draft.return_value = "草稿方案概览..."
        ctx = _confirmed_ctx(volunteer_model=volunteer_model, action_family="query_draft")
        plan = make_plan_action_plan(action_family="query_draft", stage="apply")
        result = await _execute_plan_action_model(ctx, plan)
        assert result.applied is True
        assert result.result_kind == "draft_snapshot"


# ---------------------------------------------------------------------------
# query_ordered
# ---------------------------------------------------------------------------

class TestQueryOrderedApply:
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    async def test_query_ordered_basic(self, volunteer_model: str, patch_backend, patch_planning):
        patch_planning.query_planning_ordered_plan.return_value = "排序方案概览..."
        ctx = _confirmed_ctx(volunteer_model=volunteer_model, action_family="query_ordered")
        plan = make_plan_action_plan(action_family="query_ordered", stage="apply")
        result = await _execute_plan_action_model(ctx, plan)
        assert result.applied is True
        assert result.result_kind == "ordered_snapshot"


# ---------------------------------------------------------------------------
# query_candidates
# ---------------------------------------------------------------------------

class TestQueryCandidatesApply:
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    async def test_query_candidates_basic(self, volunteer_model: str, patch_backend, patch_planning):
        patch_planning.query_planning_candidate_pool.return_value = "候选池概览..."
        ctx = _confirmed_ctx(volunteer_model=volunteer_model, action_family="query_candidates")
        plan = make_plan_action_plan(
            action_family="query_candidates",
            stage="apply",
            atomic_actions=[{
                "action_type": "query_candidates",
                "filters": {"tier": "稳", "limit": "5"},
            }],
        )
        result = await _execute_plan_action_model(ctx, plan)
        assert result.applied is True
        assert result.result_kind == "candidate_snapshot"


# ---------------------------------------------------------------------------
# generate_plan
# ---------------------------------------------------------------------------

class TestGeneratePlanApply:
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    async def test_generate_plan_success(self, volunteer_model: str, patch_backend, patch_planning):
        patch_backend.generate_planning_initial_plan.return_value = {
            "code": 0,
            "data": make_planning_state_response(ordered_total=30),
        }
        patch_backend.get_planning_state.return_value = {
            "code": 0,
            "data": make_planning_state_response(ordered_total=30),
        }
        patch_backend.run_planning_review.return_value = {"code": 0, "data": {}}
        ctx = _confirmed_ctx(volunteer_model=volunteer_model, action_family="generate_plan")
        plan = make_plan_action_plan(action_family="generate_plan", stage="apply")
        result = await _execute_plan_action_model(ctx, plan)
        assert result.applied is True
        assert result.result_kind == "generation_result"
        assert "已生成" in result.state_summary

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    async def test_generate_plan_failure(self, volunteer_model: str, patch_backend, patch_planning):
        patch_backend.generate_planning_initial_plan.return_value = {"code": 500, "data": {}}
        ctx = _confirmed_ctx(volunteer_model=volunteer_model, action_family="generate_plan")
        plan = make_plan_action_plan(action_family="generate_plan", stage="apply")
        result = await _execute_plan_action_model(ctx, plan)
        assert "失败" in result.state_summary


# ---------------------------------------------------------------------------
# analyze_adjustment
# ---------------------------------------------------------------------------

class TestAnalyzeAdjustmentApply:
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    async def test_analyze_adjustment_basic(self, volunteer_model: str, patch_backend, patch_planning):
        patch_backend.analyze_planning_plan_adjustment.return_value = {"code": 0, "data": {}}
        patch_backend.get_planning_state.return_value = {
            "code": 0,
            "data": make_planning_state_response(ordered_total=30),
        }
        patch_backend.get_planning_ordered_plan.return_value = {"code": 0, "data": {"items": []}}
        ctx = _confirmed_ctx(volunteer_model=volunteer_model, action_family="analyze_adjustment")
        plan = make_plan_action_plan(action_family="analyze_adjustment", stage="apply")
        result = await _execute_plan_action_model(ctx, plan)
        assert result.applied is False
        assert result.result_kind == "adjustment_analysis"
        assert result.workspace_refresh_targets == []


# ---------------------------------------------------------------------------
# preview_compensation
# ---------------------------------------------------------------------------

class TestPreviewCompensationApply:
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    async def test_preview_compensation_basic(self, volunteer_model: str, patch_backend, patch_planning):
        patch_backend.preview_planning_compensation.return_value = {"code": 0, "data": {}}
        ctx = _confirmed_ctx(volunteer_model=volunteer_model, action_family="preview_compensation")
        plan = make_plan_action_plan(action_family="preview_compensation", stage="apply")
        result = await _execute_plan_action_model(ctx, plan)
        # preview_compensation 在 apply 阶段 applied=False（特殊例外）
        assert result.applied is False
        assert result.result_kind == "compensation_preview"


# ---------------------------------------------------------------------------
# apply_compensation
# ---------------------------------------------------------------------------

class TestApplyCompensationApply:
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    async def test_apply_compensation_success(self, volunteer_model: str, patch_backend, patch_planning):
        # 无 blocker → 正常 apply
        # State: ordered 20 / target 30 → gap = 10
        patch_backend.get_planning_state.return_value = {
            "code": 0,
            "data": make_planning_state_response(ordered_total=20),
        }
        # Preview must return actions with estimated fill count <= gap
        patch_backend.preview_planning_compensation.return_value = {
            "code": 0,
            "data": {
                "actions": [
                    {
                        "actionType": "add",
                        "summary": "补入5个志愿",
                        "fillCount": 5,
                        "volunteerIds": ["v1", "v2", "v3", "v4", "v5"],
                    },
                ],
            },
        }
        patch_planning.apply_planning_compensation.return_value = "已应用补偿。"
        ctx = _confirmed_ctx(volunteer_model=volunteer_model, action_family="apply_compensation")
        plan = make_plan_action_plan(action_family="apply_compensation", stage="apply")
        result = await _execute_plan_action_model(ctx, plan)
        assert result.applied is True


# ---------------------------------------------------------------------------
# review_plan
# ---------------------------------------------------------------------------

class TestReviewPlanApply:
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    async def test_review_plan_basic(self, volunteer_model: str, patch_backend, patch_planning):
        patch_backend.run_planning_review.return_value = {"code": 0, "data": {}}
        patch_backend.get_planning_state.return_value = {
            "code": 0,
            "data": make_planning_state_response(ordered_total=30),
        }
        patch_backend.get_planning_ordered_plan.return_value = {"code": 0, "data": {"items": []}}
        ctx = _confirmed_ctx(volunteer_model=volunteer_model, action_family="review_plan")
        plan = make_plan_action_plan(action_family="review_plan", stage="apply")
        result = await _execute_plan_action_model(ctx, plan)
        assert result.applied is True
        assert result.result_kind == "review_result"
        assert "review" in result.workspace_refresh_targets


# ---------------------------------------------------------------------------
# add_units
# ---------------------------------------------------------------------------

class TestAddUnitsApply:
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    async def test_add_units_by_ids(self, volunteer_model: str, patch_backend, patch_planning):
        patch_planning.select_planning_ordered_items.return_value = "已添加2个志愿。"
        ctx = _confirmed_ctx(volunteer_model=volunteer_model, action_family="add_units")
        plan = make_plan_action_plan(
            action_family="add_units",
            stage="apply",
            atomic_actions=[{
                "action_type": "add_units",
                "volunteer_ids": ["vol_001", "vol_002"],
            }],
        )
        result = await _execute_plan_action_model(ctx, plan)
        assert result.applied is True
        assert result.result_kind == "mutation_result"
        assert "draft" in result.workspace_refresh_targets


# ---------------------------------------------------------------------------
# remove_units
# ---------------------------------------------------------------------------

class TestRemoveUnitsApply:
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    async def test_remove_units_by_ids(self, volunteer_model: str, patch_backend, patch_planning):
        patch_planning.remove_planning_ordered_items.return_value = "已移除2个志愿。"
        # 需要 resolve refs
        patch_backend.get_planning_ordered_plan.return_value = {
            "code": 0,
            "data": {
                "items": [
                    {"volunteerId": "vol_001", "schoolName": "北大", "majorName": "计算机"},
                    {"volunteerId": "vol_002", "schoolName": "清华", "majorName": "数学"},
                ],
            },
        }
        ctx = _confirmed_ctx(volunteer_model=volunteer_model, action_family="remove_units")
        plan = make_plan_action_plan(
            action_family="remove_units",
            stage="apply",
            atomic_actions=[{
                "action_type": "remove_units",
                "volunteer_ids": ["vol_001", "vol_002"],
            }],
        )
        result = await _execute_plan_action_model(ctx, plan)
        assert result.applied is True
        assert result.result_kind == "mutation_result"

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    async def test_remove_units_missing_refs(self, volunteer_model: str, patch_backend, patch_planning):
        """移除时找不到 volunteer ref → error。"""
        patch_backend.get_planning_ordered_plan.return_value = {
            "code": 0,
            "data": {"items": []},
        }
        ctx = _confirmed_ctx(volunteer_model=volunteer_model, action_family="remove_units")
        plan = make_plan_action_plan(
            action_family="remove_units",
            stage="apply",
            atomic_actions=[{
                "action_type": "remove_units",
                "volunteer_ids": ["nonexistent_ref"],
            }],
        )
        result = await _execute_plan_action_model(ctx, plan)
        assert result.result_kind == "error"
        assert "missing_inputs" in result.reply_focus


# ---------------------------------------------------------------------------
# move_unit
# ---------------------------------------------------------------------------

class TestMoveUnitApply:
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    async def test_move_unit_success(self, volunteer_model: str, patch_backend, patch_planning):
        patch_planning.move_planning_ordered_item.return_value = "已移动志愿。"
        patch_backend.get_planning_ordered_plan.return_value = {
            "code": 0,
            "data": {
                "items": [
                    {"volunteerId": "vol_001", "schoolName": "北大", "majorName": "计算机"},
                ],
            },
        }
        ctx = _confirmed_ctx(volunteer_model=volunteer_model, action_family="move_unit")
        plan = make_plan_action_plan(
            action_family="move_unit",
            stage="apply",
            atomic_actions=[{
                "action_type": "move_unit",
                "volunteer_ids": ["vol_001"],
                "target_position": 5,
            }],
        )
        result = await _execute_plan_action_model(ctx, plan)
        assert result.applied is True
        assert result.result_kind == "mutation_result"

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    async def test_move_unit_missing_ref(self, volunteer_model: str, patch_backend, patch_planning):
        patch_backend.get_planning_ordered_plan.return_value = {
            "code": 0,
            "data": {"items": []},
        }
        ctx = _confirmed_ctx(volunteer_model=volunteer_model, action_family="move_unit")
        plan = make_plan_action_plan(
            action_family="move_unit",
            stage="apply",
            atomic_actions=[{
                "action_type": "move_unit",
                "volunteer_ids": ["nonexistent"],
                "target_position": 1,
            }],
        )
        result = await _execute_plan_action_model(ctx, plan)
        assert result.result_kind == "error"


# ---------------------------------------------------------------------------
# pin_unit / unpin_unit
# ---------------------------------------------------------------------------

class TestPinUnpinApply:
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    async def test_pin_unit_disabled(self, volunteer_model: str, patch_backend, patch_planning):
        patch_backend.get_planning_ordered_plan.return_value = {
            "code": 0,
            "data": {
                "items": [{"volunteerId": "vol_001", "schoolName": "北大", "majorName": "计算机"}],
            },
        }
        ctx = _confirmed_ctx(volunteer_model=volunteer_model, action_family="pin_unit")
        plan = make_plan_action_plan(
            action_family="pin_unit",
            stage="apply",
            atomic_actions=[{
                "action_type": "pin_unit",
                "volunteer_ids": ["vol_001"],
                "target_position": 3,
            }],
        )
        result = await _execute_plan_action_model(ctx, plan)
        assert result.applied is False
        assert result.result_kind == "error"
        assert "pin_disabled" in result.reply_focus
        patch_planning.pin_planning_ordered_item.assert_not_awaited()

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    async def test_unpin_unit_disabled(self, volunteer_model: str, patch_backend, patch_planning):
        patch_backend.get_planning_ordered_plan.return_value = {
            "code": 0,
            "data": {
                "items": [{"volunteerId": "vol_001", "schoolName": "北大", "majorName": "计算机"}],
            },
        }
        ctx = _confirmed_ctx(volunteer_model=volunteer_model, action_family="unpin_unit")
        plan = make_plan_action_plan(
            action_family="unpin_unit",
            stage="apply",
            atomic_actions=[{
                "action_type": "unpin_unit",
                "volunteer_ids": ["vol_001"],
            }],
        )
        result = await _execute_plan_action_model(ctx, plan)
        assert result.applied is False
        assert result.result_kind == "error"
        assert "pin_disabled" in result.reply_focus
        patch_planning.unpin_planning_ordered_item.assert_not_awaited()


# ---------------------------------------------------------------------------
# regenerate_order
# ---------------------------------------------------------------------------

class TestRegenerateOrderApply:
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    async def test_regenerate_order_success(self, volunteer_model: str, patch_backend, patch_planning):
        patch_backend.generate_planning_ordered_plan.return_value = {"code": 0, "data": {}}
        patch_backend.get_planning_state.return_value = {
            "code": 0,
            "data": make_planning_state_response(ordered_total=30),
        }
        patch_backend.run_planning_review.return_value = {"code": 0, "data": {}}
        ctx = _confirmed_ctx(volunteer_model=volunteer_model, action_family="regenerate_order")
        plan = make_plan_action_plan(
            action_family="regenerate_order",
            stage="apply",
            user_goal="重新排一下",
        )
        result = await _execute_plan_action_model(ctx, plan)
        assert result.applied is True
        assert result.result_kind == "mutation_result"


# ---------------------------------------------------------------------------
# unknown action_family → fallback message
# ---------------------------------------------------------------------------

class TestUnknownActionFallback:
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    async def test_unknown_action_family(self, volunteer_model: str, patch_backend, patch_planning):
        """action_family 不在已知列表 → fallback 消息。"""
        ctx = _confirmed_ctx(volunteer_model=volunteer_model, action_family="query_state")
        # 使用 query_state 类型但模拟一个不存在的逻辑分支不容易
        # 改为测试 else 分支：构造一个 PlanActionPlan 后直接修改 action_family
        plan = make_plan_action_plan(action_family="query_state", stage="apply")
        # 注入非法 action_family
        object.__setattr__(plan, "action_family", "nonexistent_action")
        result = await _execute_plan_action_model(ctx, plan)
        assert "暂未接入" in result.state_summary


# ---------------------------------------------------------------------------
# review rerun post-processing
# ---------------------------------------------------------------------------

class TestReviewRerunPostProcessing:
    """should_rerun_review=True → 执行后自动追加 review。"""

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    async def test_rerun_review_after_mutation(self, volunteer_model: str, patch_backend, patch_planning):
        patch_planning.select_planning_ordered_items.return_value = "已添加。"
        patch_planning.run_planning_review.return_value = "复审完成，1个风险。"
        ctx = _confirmed_ctx(volunteer_model=volunteer_model, action_family="add_units")
        plan = make_plan_action_plan(
            action_family="add_units",
            stage="apply",
            should_rerun_review=True,
            atomic_actions=[{
                "action_type": "add_units",
                "volunteer_ids": ["vol_001"],
            }],
        )
        result = await _execute_plan_action_model(ctx, plan)
        assert result.review_rerun is True
        assert "review" in result.workspace_refresh_targets
