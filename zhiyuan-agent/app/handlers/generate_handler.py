"""方案生成 handler。

覆盖 action_family: generate_plan。
独立的生成逻辑。
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic_ai import RunContext

from app.agent.context import RequestContext
from app.handlers.registry import register_handler
from app.handlers.query_handlers import _get_planning_state_with_latest_profile, _build_status_overview_summary
from app.tools.plan_orchestration_models import PlanActionPlan, PlanExecutionResult
from app.tools.planning_workflow_tool import _build_plan_status_overview_facts
from app.util.planning_state_compat import get_working_plan_state
from app.util.internal_client import (
    generate_planning_candidate_pool as _generate_planning_candidate_pool_request,
    generate_planning_initial_plan as _generate_planning_initial_plan_request,
    run_planning_review as _run_planning_review_request,
)

logger = logging.getLogger(__name__)

_DEFAULT_TENANT_ID = 1


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------


async def _refresh_review_and_state(session_id: str) -> dict[str, Any] | None:
    try:
        await _run_planning_review_request(_DEFAULT_TENANT_ID, session_id)
    except Exception:
        logger.exception("refresh review failed after plan execution: session_id=%s", session_id)
    try:
        planning_state = await _get_planning_state_with_latest_profile(session_id)
        if planning_state:
            return planning_state
    except Exception:
        logger.exception("refresh planning state failed after plan execution: session_id=%s", session_id)
    return None


# ---------------------------------------------------------------------------
# Handler 实现
# ---------------------------------------------------------------------------


def _build_generation_error(
    plan: PlanActionPlan, error_code: int, error_msg: str,
    hints: list[str] | None = None,
) -> PlanExecutionResult:
    return PlanExecutionResult(
        applied=False,
        action_family="generate_plan",
        stage=plan.stage,
        result_kind="error",
        executed_actions=[],
        workspace_refresh_targets=[],
        context_summary=plan.context_summary,
        state_summary=f"方案生成失败（错误码 {error_code}）：{error_msg}",
        summary=f"方案生成失败（错误码 {error_code}）：{error_msg}",
        reply_focus=["error", "generation_failed"],
        next_step_hints=hints or [
            "方案生成服务暂时不可用，不要重复尝试生成。",
            "告知用户生成失败的事实，建议稍后再试或联系客服。",
            "可以继续帮用户做方向探索、意向整理等不依赖方案生成的工作。",
        ],
    )


@register_handler("generate_plan")
async def handle_generate_plan(
    ctx: RunContext[RequestContext], plan: PlanActionPlan
) -> PlanExecutionResult:
    session_id = ctx.deps.sessionid

    pool_result = await _generate_planning_candidate_pool_request(
        _DEFAULT_TENANT_ID, session_id, True,
    )
    pool_code = pool_result.get("code") if isinstance(pool_result, dict) else -1
    if pool_code != 0:
        pool_msg = (pool_result or {}).get("msg") or (pool_result or {}).get("error") or "候选池生成失败"
        logger.warning(
            "generate_plan: candidate pool generation failed, session_id=%s, code=%s, msg=%s",
            session_id, pool_code, pool_msg,
        )
        if pool_code == 404:
            return _build_generation_error(plan, 404, "会话数据不完整，缺少成绩信息或基础会话记录", [
                "生成方案需要先有学生的成绩信息（省份、分数、选科等）。",
                "当前会话尚未录入完整的报考基础数据，无法生成候选池和方案。",
                "引导用户先通过正常对话补全成绩和基础信息，或联系客服确认会话状态。",
                "不要重复尝试生成。",
            ])
        return _build_generation_error(plan, pool_code or -1, pool_msg)

    result = await _generate_planning_initial_plan_request(
        _DEFAULT_TENANT_ID,
        session_id,
        force_regenerate=True,
        regroup_by_tier=True,
        overwrite_existing_draft=True,
    )

    if result.get("code") != 0:
        error_msg = result.get("msg") or result.get("error") or "未知错误"
        error_code = result.get("code", -1)
        logger.warning(
            "generate_plan failed: session_id=%s, code=%s, msg=%s",
            session_id, error_code, error_msg,
        )
        return _build_generation_error(plan, error_code, error_msg)

    latest_state = await _refresh_review_and_state(session_id) or (result.get("data") or {})
    facts = _build_plan_status_overview_facts(
        latest_state,
        ordered_state=(latest_state.get("orderedPlanState") or {}),
        working_state=get_working_plan_state(latest_state),
    )
    state_summary, reply_focus, next_step_hints = _build_status_overview_summary(facts)
    state_summary = f"已生成一版方案。{state_summary}"

    return PlanExecutionResult(
        applied=True,
        action_family="generate_plan",
        stage=plan.stage,
        result_kind="generation_result",
        executed_actions=[{"action": "generate_plan"}],
        workspace_refresh_targets=["ordered", "review"],
        context_summary=plan.context_summary,
        state_summary=state_summary,
        summary=state_summary,
        reply_focus=reply_focus,
        next_step_hints=next_step_hints,
        facts=facts,
    )
