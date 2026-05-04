"""查询类 handler。

覆盖 action_family: query_state, query_draft, query_ordered, query_candidates。
只读 handler，不涉及 apply 副作用。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from pydantic_ai import RunContext

from app.agent.context import RequestContext
from app.handlers.registry import register_handler
from app.tools.plan_orchestration_models import PlanActionPlan, PlanExecutionResult
from app.tools.planning_workflow_tool import (
    _build_plan_status_overview_facts,
    merge_planning_state_with_user_profile,
    query_planning_candidate_pool,
    query_planning_draft,
    query_planning_ordered_plan,
)
from app.util.internal_client import (
    get_planning_draft as _get_planning_draft_request,
    get_planning_ordered_plan as _get_planning_ordered_plan_request,
    get_planning_state as _get_planning_state_request,
    get_user_profile as _get_user_profile_request,
)

from app.handlers.shared import summary_total

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------


async def _get_planning_state_with_latest_profile(session_id: str) -> dict[str, Any]:
    state_result, profile_result = await asyncio.gather(
        _get_planning_state_request(session_id),
        _get_user_profile_request(session_id),
        return_exceptions=True,
    )
    if isinstance(state_result, Exception):
        logger.warning("get planning state failed: session_id=%s error=%s", session_id, state_result)
        return {}
    planning_state = state_result.get("data") or {} if state_result.get("code") == 0 else {}
    if isinstance(profile_result, Exception):
        logger.warning("get user profile failed: session_id=%s error=%s", session_id, profile_result)
        return planning_state
    user_profile = (((profile_result or {}).get("data") or {}).get("userprofile") or {})
    return merge_planning_state_with_user_profile(planning_state, user_profile)


def _tier_counts_text(tier_counts: dict[str, Any] | None) -> str:
    tier_counts = tier_counts or {}
    parts: list[str] = []
    for key in ("冲", "稳", "保"):
        value = tier_counts.get(key)
        if value is None:
            continue
        parts.append(f"{key}{value}")
    return " / ".join(parts)


def _compact_list_text(values: list[Any] | None, limit: int = 2) -> str:
    items = [str(value).strip() for value in (values or []) if str(value).strip()]
    return "；".join(items[:limit])


def _build_status_overview_summary(facts: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    current_total = int(facts.get("current_total") or 0)
    target_total = int(facts.get("target_total") or 0)
    risk_count = int(facts.get("risk_count") or 0)
    warn_count = int(facts.get("warn_count") or 0)
    phase = str(facts.get("phase") or "unknown")
    tier_text = _tier_counts_text(facts.get("tier_counts"))
    gap_hint = str(facts.get("count_gap_hint") or "").strip()
    reminder_text = _compact_list_text(facts.get("main_reminders"))
    pending_count = int(facts.get("pending_action_count") or 0)
    pending_text = _compact_list_text(facts.get("pending_action_summaries"))

    parts = [
        f"当前方案阶段为 {phase}",
        f"志愿数量 {current_total}/{target_total or current_total}",
    ]
    if tier_text:
        parts.append(f"区间分布 {tier_text}")
    parts.append(f"风险 {risk_count} 项，提醒 {warn_count} 项")
    if gap_hint:
        parts.append(gap_hint)
    if reminder_text:
        parts.append(f"当前主要需要关注：{reminder_text}")
    if pending_count > 0 and pending_text:
        parts.append(f"待处理建议 {pending_count} 项，主要是 {pending_text}")

    reply_focus = ["current_state", "count_target", "risk_warning"]
    if tier_text:
        reply_focus.append("tier_distribution")
    if gap_hint:
        reply_focus.append("count_gap")
    if pending_count > 0:
        reply_focus.append("pending_actions")

    next_step_hints: list[str] = []
    if risk_count > 0 or warn_count > 0:
        next_step_hints.append("如果用户继续追问风险或不合理处，优先展开审查结果或调整分析。")
    if gap_hint:
        next_step_hints.append("如果用户关心数量是否够用，先解释当前目标数量与缺口。")
    if pending_count > 0:
        next_step_hints.append("如果用户想继续优化，可先解释待处理建议，再决定是否补偿或重排。")
    return "；".join(parts) + "。", reply_focus, next_step_hints


# ---------------------------------------------------------------------------
# Handler 实现
# ---------------------------------------------------------------------------


@register_handler("query_state")
async def handle_query_state(
    ctx: RunContext[RequestContext], plan: PlanActionPlan
) -> PlanExecutionResult:
    session_id = ctx.deps.sessionid
    planning_state = await _get_planning_state_with_latest_profile(session_id)

    ordered_state: dict[str, Any] | None = None
    draft_state: dict[str, Any] | None = None
    ordered_total = summary_total(
        ((planning_state.get("orderedPlanState") or {}).get("summary") or {})
    )
    draft_total = summary_total(
        ((planning_state.get("draftPlanState") or {}).get("summary") or {})
    )
    if ordered_total > 0:
        ordered_result = await _get_planning_ordered_plan_request(session_id)
        if ordered_result.get("code") == 0:
            ordered_state = ordered_result.get("data") or {}
    elif draft_total > 0:
        draft_result = await _get_planning_draft_request(session_id)
        if draft_result.get("code") == 0:
            draft_state = draft_result.get("data") or {}

    facts = _build_plan_status_overview_facts(
        planning_state,
        ordered_state=ordered_state,
        draft_state=draft_state,
    )
    state_summary, reply_focus, next_step_hints = _build_status_overview_summary(facts)

    return PlanExecutionResult(
        applied=True,
        action_family="query_state",
        stage=plan.stage,
        result_kind="status_overview",
        workspace_refresh_targets=["ordered", "review"],
        context_summary=plan.context_summary,
        state_summary=state_summary,
        summary=state_summary,
        reply_focus=reply_focus,
        next_step_hints=next_step_hints,
        facts=facts,
    )


@register_handler("query_draft")
async def handle_query_draft(
    ctx: RunContext[RequestContext], plan: PlanActionPlan
) -> PlanExecutionResult:
    state_summary = await query_planning_draft(ctx)
    return PlanExecutionResult(
        applied=True,
        action_family="query_draft",
        stage=plan.stage,
        result_kind="draft_snapshot",
        workspace_refresh_targets=["draft"],
        context_summary=plan.context_summary,
        state_summary=state_summary,
        summary=state_summary,
        reply_focus=["draft_snapshot"],
    )


@register_handler("query_ordered")
async def handle_query_ordered(
    ctx: RunContext[RequestContext], plan: PlanActionPlan
) -> PlanExecutionResult:
    state_summary = await query_planning_ordered_plan(ctx)
    return PlanExecutionResult(
        applied=True,
        action_family="query_ordered",
        stage=plan.stage,
        result_kind="ordered_snapshot",
        workspace_refresh_targets=["ordered"],
        context_summary=plan.context_summary,
        state_summary=state_summary,
        summary=state_summary,
        reply_focus=["ordered_snapshot"],
    )


@register_handler("query_candidates")
async def handle_query_candidates(
    ctx: RunContext[RequestContext], plan: PlanActionPlan
) -> PlanExecutionResult:
    atomic = plan.atomic_actions[0] if plan.atomic_actions else None
    filters = atomic.filters if atomic else {}
    state_summary = await query_planning_candidate_pool(
        ctx,
        tiers=[filters["tier"]] if filters.get("tier") else None,
        province_names=[filters["province_keyword"]] if filters.get("province_keyword") else None,
        school_keywords=[filters["school_keyword"]] if filters.get("school_keyword") else None,
        major_keywords=[filters["major_keyword"]] if filters.get("major_keyword") else None,
        school_tags=json.loads(filters["school_tags"]) if filters.get("school_tags") else None,
        major_tags=json.loads(filters["major_tags"]) if filters.get("major_tags") else None,
        page=1,
        page_size=int(filters.get("limit") or 5),
    )
    return PlanExecutionResult(
        applied=True,
        action_family="query_candidates",
        stage=plan.stage,
        result_kind="candidate_snapshot",
        workspace_refresh_targets=["candidate"],
        context_summary=plan.context_summary,
        state_summary=state_summary,
        summary=state_summary,
        reply_focus=["candidate_snapshot"],
    )
