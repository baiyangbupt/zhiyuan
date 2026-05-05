"""查询类 handler。

覆盖 action_family: query_state, query_draft, query_ordered, query_candidates。
只读 handler，不涉及 apply 副作用。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
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


def _clean_plan_item_for_user(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.replace("(unknown)", "")
    return re.sub(r"@(\d+)", r"第\1位", text).strip()


def _build_status_overview_summary(facts: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    current_total = int(facts.get("current_total") or 0)
    target_total = int(facts.get("target_total") or 0)
    risk_count = int(facts.get("risk_count") or 0)
    warn_count = int(facts.get("warn_count") or 0)
    tier_text = _tier_counts_text(facts.get("tier_counts"))
    gap_hint = str(facts.get("count_gap_hint") or "").strip()
    reminder_text = _compact_list_text(facts.get("main_reminders"))
    pending_count = int(facts.get("pending_action_count") or 0)
    pending_text = _compact_list_text(facts.get("pending_action_summaries"))
    top_items = facts.get("top_items") or []
    intent_relation = facts.get("intent_relation") or {}

    lines: list[str] = []
    if current_total >= target_total and target_total > 0:
        lines.append(f"方案已经有了，当前已填满 {current_total}/{target_total} 个志愿。")
    elif current_total > 0:
        lines.append(f"方案已经有了，目前有 {current_total}/{target_total or current_total} 个志愿。")
    else:
        lines.append("当前还没有正式志愿。")
    if tier_text:
        lines.append(f"- 梯度分布：{tier_text}。")
    if risk_count > 0 or warn_count > 0:
        lines.append(f"- 审查提醒：风险 {risk_count} 项，提醒 {warn_count} 项。")
    else:
        lines.append("- 审查结果：暂时没有明显风险。")
    if gap_hint:
        lines.append(f"- 数量缺口：{gap_hint}")
    if reminder_text:
        lines.append(f"- 需要关注：{reminder_text}。")
    if pending_count > 0 and pending_text:
        lines.append(f"- 待处理建议：{pending_count} 项，主要是{pending_text}。")

    if top_items:
        item_lines = []
        for item in top_items[:5]:
            if isinstance(item, str):
                item_lines.append(_clean_plan_item_for_user(item))
            elif isinstance(item, dict):
                brief = item.get("brief") or item.get("text") or ""
                if brief:
                    item_lines.append(_clean_plan_item_for_user(brief))
        if item_lines:
            lines.append(f"- 前排示例：{'；'.join(item_lines[:3])}。")

    if intent_relation:
        relation_summary = intent_relation.get("summary") or ""
        coverage = intent_relation.get("coverage") or ""
        aligned_examples = intent_relation.get("aligned_examples") or ""
        conflict_examples = intent_relation.get("conflict_examples") or ""
        if relation_summary:
            lines.append(f"- 当前偏好：{relation_summary.removeprefix('当前偏好/要求：')}")
        if coverage:
            lines.append(f"- 承接情况：{coverage.removeprefix('承接情况：')}")
        if aligned_examples:
            lines.append(f"- 贴近偏好的例子：{_clean_plan_item_for_user(aligned_examples.removeprefix('贴近偏好：'))}")
        if conflict_examples:
            lines.append(f"- 需要关注的冲突：{_clean_plan_item_for_user(conflict_examples.removeprefix('需关注冲突：'))}")

    reply_focus = ["current_state", "count_target", "risk_warning"]
    if tier_text:
        reply_focus.append("tier_distribution")
    if top_items:
        reply_focus.append("sample_items")
    if intent_relation:
        reply_focus.append("intent_match")
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
    if current_total > 0:
        lines.append("你可以继续看审查详情，或者告诉我想按地域、专业、稳妥程度怎么调。")
    return "\n".join(line for line in lines if line), reply_focus, next_step_hints


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
        workspace_refresh_targets=[],
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
