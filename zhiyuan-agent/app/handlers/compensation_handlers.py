"""补偿类 handler。

覆盖 action_family: preview_compensation, apply_compensation。
有 apply 但逻辑相对独立。
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic_ai import RunContext

from app.agent.context import RequestContext
from app.handlers.registry import register_handler
from app.handlers.query_handlers import _get_planning_state_with_latest_profile, _compact_list_text
from app.handlers.shared import summary_total, summary_target_total
from app.tools.plan_orchestration_models import PlanActionPlan, PlanExecutionResult
from app.tools.planning_workflow_tool import (
    _build_compensation_preview_facts,
    _build_plan_intent_relation_lines,
)
from app.util.internal_client import (
    apply_planning_compensation as _apply_planning_compensation_request,
    get_planning_state as _get_planning_state_request,
    preview_planning_compensation as _preview_planning_compensation_request,
    run_planning_review as _run_planning_review_request,
)

logger = logging.getLogger(__name__)

_DEFAULT_TENANT_ID = 1


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------


def _build_compensation_summary(facts: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    action_count = int(facts.get("action_count") or 0)
    estimated_count = int(facts.get("estimated_fill_count") or facts.get("estimated_volunteer_count") or 0)
    action_text = _compact_list_text(facts.get("action_summaries"))
    parts = [f"当前可先看的补齐建议共有 {action_count} 项动作，预计补入 {estimated_count} 个志愿"]
    if action_text:
        parts.append(f"主要补偿方向是 {action_text}")
    reply_focus = ["compensation_preview"]
    next_step_hints = ["这是预览结果；只有用户确认后，才适合继续执行补偿。"]
    return "；".join(parts) + "。", reply_focus, next_step_hints


def _planning_version_from_context(ctx: RunContext[RequestContext]) -> int:
    planning_summary = getattr(ctx.deps, "planning_summary", None)
    try:
        return int(getattr(planning_summary, "version", 0) or 0)
    except (TypeError, ValueError):
        return 0


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


def _append_intent_relation_summary(base_text: str, planning_state: dict[str, Any] | None) -> str:
    ordered_state = (planning_state or {}).get("orderedPlanState") or {}
    draft_state = (planning_state or {}).get("draftPlanState") or {}
    ordered_items = ordered_state.get("items") or []
    draft_items = draft_state.get("items") or []
    plan_items = ordered_items or draft_items
    plan_summary = (ordered_state.get("summary") or {}) if ordered_items else (draft_state.get("summary") or {})
    relation_lines = _build_plan_intent_relation_lines(
        planning_state,
        plan_items,
        plan_summary=plan_summary,
        include_position=True,
    )
    if not relation_lines:
        return base_text
    return base_text + " " + " ".join(line.removeprefix("- ").strip() for line in relation_lines[:2] if line)


async def _compensation_apply_blocker(ctx: RunContext[RequestContext]) -> str | None:
    session_id = ctx.deps.sessionid
    try:
        state_result = await _get_planning_state_request(session_id)
        planning_state = state_result.get("data") or {} if state_result.get("code") == 0 else {}
        draft_summary = ((planning_state.get("draftPlanState") or {}).get("summary") or {})
        ordered_summary = ((planning_state.get("orderedPlanState") or {}).get("summary") or {})
        current_total = max(summary_total(draft_summary), summary_total(ordered_summary))
        target_total = (
            summary_target_total(ordered_summary)
            or summary_target_total(draft_summary)
            or ((planning_state.get("candidatePoolState") or {}).get("requiredCount") or 0)
        )
        if not target_total:
            return None

        preview_result = await _preview_planning_compensation_request(session_id)
        preview_state = preview_result.get("data") or {} if preview_result.get("code") == 0 else {}
        facts = _build_compensation_preview_facts(preview_state)
        estimated_count = int(facts.get("estimated_fill_count") or facts.get("estimated_volunteer_count") or 0)
        if estimated_count <= 0:
            if current_total > target_total:
                return (
                    f"当前方案已经超过目标数量 {current_total}/{target_total}，而且这轮补位预览也没有可安全补入的候选志愿。"
                    "建议先精简超量志愿、做替换，或者调整筛选范围后再看新的补位预览。"
                )
            return (
                "当前没有可安全补入的候选志愿。"
                "建议改用替换、重排，或者调整筛选范围后再看新的补位预览。"
            )
        if current_total < target_total and current_total + estimated_count <= target_total:
            return None
        gap = max(target_total - current_total, 0)
        if gap > 0:
            return (
                f"当前方案距离目标数量还差 {gap} 个，但这条补齐建议预计会再补入 {estimated_count} 个志愿，"
                "直接应用会超过目标数量。建议改为先预览更小范围的补位，或改用替换来腾位置。"
            )
        return (
            f"当前方案已经达到目标数量 {current_total}/{target_total}。"
            f"这条补齐建议预计再补入 {estimated_count} 个志愿，直接应用会超过目标数量。"
            "建议改为先替换冲突/高风险志愿，或重新生成排序来处理梯度断层。"
        )
    except Exception:
        logger.warning("compensation apply precheck failed: session_id=%s", session_id, exc_info=True)
        return None


async def _apply_compensation_to_plan(ctx: RunContext[RequestContext]) -> str:
    session_id = ctx.deps.sessionid
    logger.info("_apply_compensation_to_plan: session_id=%s", session_id)
    try:
        result = await _apply_planning_compensation_request(_DEFAULT_TENANT_ID, session_id, True, True)
        if result.get("code") != 0:
            return "应用补偿失败，请稍后重试。"
        draft_summary = (
            result.get("data", {})
            .get("draftPlanState", {})
            .get("summary", {})
        )
        draft_total = summary_total(draft_summary)
        latest_state = await _refresh_review_and_state(session_id) or (result.get("data") or {})
        base_text = (
            f"系统已完成当前可安全补偿的志愿补入，当前已加入方案共 {draft_total} 条，并已同步刷新当前方案。"
            "你可以继续看结果，再决定是否继续重排。"
        )
        return _append_intent_relation_summary(base_text, latest_state)
    except Exception:
        logger.exception("_apply_compensation_to_plan failed: session_id=%s", session_id)
        return "应用补偿建议时发生错误，请稍后重试。"


# ---------------------------------------------------------------------------
# Handler 实现
# ---------------------------------------------------------------------------


@register_handler("preview_compensation")
async def handle_preview_compensation(
    ctx: RunContext[RequestContext], plan: PlanActionPlan
) -> PlanExecutionResult:
    session_id = ctx.deps.sessionid
    preview_result = await _preview_planning_compensation_request(session_id)
    preview_state = preview_result.get("data") or {} if preview_result.get("code") == 0 else {}
    facts = _build_compensation_preview_facts(preview_state)
    planning_version = _planning_version_from_context(ctx)
    if planning_version > 0:
        facts["planning_version"] = planning_version
    state_summary, reply_focus, next_step_hints = _build_compensation_summary(facts)

    return PlanExecutionResult(
        applied=False,
        action_family="preview_compensation",
        stage=plan.stage,
        result_kind="compensation_preview",
        executed_actions=[],
        workspace_refresh_targets=[],
        context_summary=plan.context_summary,
        state_summary=state_summary,
        summary=state_summary,
        reply_focus=reply_focus,
        next_step_hints=next_step_hints,
        facts=facts,
    )


@register_handler("apply_compensation")
async def handle_apply_compensation(
    ctx: RunContext[RequestContext], plan: PlanActionPlan
) -> PlanExecutionResult:
    blocker = await _compensation_apply_blocker(ctx)
    if blocker:
        return PlanExecutionResult(
            applied=False,
            action_family="apply_compensation",
            stage=plan.stage,
            result_kind="error",
            executed_actions=[],
            workspace_refresh_targets=[],
            context_summary=plan.context_summary,
            state_summary=blocker,
            summary=blocker,
            reply_focus=["blocked_over_target", "compensation_apply_blocked"],
            next_step_hints=["先说明不能直接超量补齐，再建议改用替换、重排或先移出冲突志愿。"],
        )

    state_summary = await _apply_compensation_to_plan(ctx)
    return PlanExecutionResult(
        applied=True,
        action_family="apply_compensation",
        stage=plan.stage,
        result_kind="mutation_result",
        executed_actions=[{"action": "apply_compensation"}],
        workspace_refresh_targets=["draft", "ordered", "review"],
        context_summary=plan.context_summary,
        state_summary=state_summary,
        summary=state_summary,
        reply_focus=["mutation_result", "plan_update", "compensation_applied"],
        next_step_hints=["优先说明补齐后方案是否更接近目标数量，再决定是否建议继续重排。"],
    )
