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
from app.domain.school_entity_resolver import compact_school_text, school_name_set_for_batch
from app.handlers.registry import register_handler
from app.tools.plan_orchestration_models import PlanActionPlan, PlanExecutionResult
from app.tools.candidate_filter_extraction_tool import (
    extract_candidate_query_filters_async,
    normalize_candidate_query_filters_async,
)
from app.tools.planning_workflow_tool import (
    _build_plan_status_overview_facts,
    merge_planning_state_with_user_profile,
    query_planning_candidate_pool,
    query_planning_draft,
    query_planning_ordered_plan,
)
from app.tools.plan_query_tool import _enrich_plan_items_with_candidate_metadata, query_volunteer_plan
from app.util.internal_client import (
    get_planning_draft as _get_planning_draft_request,
    get_planning_ordered_plan as _get_planning_ordered_plan_request,
    get_planning_state as _get_planning_state_request,
    get_user_profile as _get_user_profile_request,
)

from app.handlers.shared import summary_total

logger = logging.getLogger(__name__)

_CANDIDATE_QUERY_FAILED_TEXT = "查询候选池失败，请稍后重试。"


def _school_mentions_from_text(text: str, batch: str | None) -> list[str]:
    compact_text = compact_school_text(text)
    if not compact_text:
        return []
    names: list[str] = []
    for school_name in school_name_set_for_batch(batch):
        compact_name = compact_school_text(school_name)
        if compact_name and compact_name in compact_text:
            names.append(school_name)
    names.sort(key=lambda value: len(compact_school_text(value)), reverse=True)
    return list(dict.fromkeys(names))


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


def _parse_filter_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item or "").strip() for item in value if str(item or "").strip()]
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except Exception:
        return [part.strip() for part in text.replace("，", ",").split(",") if part.strip()]
    if isinstance(parsed, list):
        return [str(item or "").strip() for item in parsed if str(item or "").strip()]
    return [text]


def _latest_user_message(ctx: RunContext[RequestContext]) -> str:
    for item in reversed(getattr(ctx.deps, "chat_history", None) or []):
        if item.get("role") == "user":
            return str(item.get("content") or "").strip()
    return ""


def _candidate_query_source_text(
    ctx: RunContext[RequestContext],
    plan: PlanActionPlan,
    atomic: Any | None,
) -> str:
    parts = [
        getattr(plan, "user_goal", "") or "",
        getattr(atomic, "reason", "") if atomic is not None else "",
        _latest_user_message(ctx),
    ]
    return " ".join(str(part or "").strip() for part in parts if str(part or "").strip())


def _merge_filter_lists(base: list[str], extra: list[str]) -> list[str]:
    merged: list[str] = []
    for value in [*base, *extra]:
        text = str(value or "").strip()
        if text and text not in merged:
            merged.append(text)
    return merged


def _filter_payload_from_atomic_filters(filters: dict[str, Any]) -> dict[str, Any]:
    return {
        "tiers": [filters.get("tier")] if filters.get("tier") else [],
        "province_names": [filters.get("province_keyword")] if filters.get("province_keyword") else [],
        "city_names": [filters.get("city_keyword")] if filters.get("city_keyword") else [],
        "school_keywords": [filters.get("school_keyword")] if filters.get("school_keyword") else [],
        "major_keywords": [filters.get("major_keyword")] if filters.get("major_keyword") else [],
        "school_tags": _parse_filter_list(filters.get("school_tags")),
        "major_tags": _parse_filter_list(filters.get("major_tags")),
    }


async def _build_candidate_query_filters(
    ctx: RunContext[RequestContext],
    plan: PlanActionPlan,
    atomic: Any | None,
) -> dict[str, list[str]]:
    batch = getattr(ctx.deps, "batch", None) or "01"
    atomic_filters = dict(atomic.filters if atomic else {})
    normalized = await normalize_candidate_query_filters_async(
        _filter_payload_from_atomic_filters(atomic_filters),
        batch=batch,
    )
    source_text = _candidate_query_source_text(ctx, plan, atomic)
    try:
        extracted = await extract_candidate_query_filters_async(source_text, batch=batch)
    except Exception:
        logger.warning("candidate query filter extraction failed in query_candidates", exc_info=True)
        extracted = {}
    extracted_filters = (extracted or {}).get("filters") or {}
    return {
        key: _merge_filter_lists(normalized.get(key) or [], extracted_filters.get(key) or [])
        for key in (
            "tiers",
            "province_names",
            "city_names",
            "school_keywords",
            "major_keywords",
            "school_tags",
            "major_tags",
        )
    }


def _candidate_query_failed(state_summary: str) -> bool:
    text = str(state_summary or "").strip()
    return text == _CANDIDATE_QUERY_FAILED_TEXT or text.startswith("查询候选池失败")


def _has_school_nature_metadata(items: list[dict[str, Any]] | None) -> bool:
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if any(
            item.get(key)
            for key in (
                "schoolNature",
                "school_nature",
                "schoolType",
                "school_type",
                "schoolTags",
                "school_tags",
                "schoolTag",
                "tags",
            )
        ):
            return True
    return False


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
    school_nature_distribution = facts.get("school_nature_distribution") or {}

    lines: list[str] = []
    if current_total >= target_total and target_total > 0:
        lines.append(f"方案已经有了，当前已填满 {current_total}/{target_total} 个志愿。")
    elif current_total > 0:
        lines.append(f"方案已经有了，目前有 {current_total}/{target_total or current_total} 个志愿。")
    else:
        lines.append("当前还没有正式志愿。")
    if tier_text:
        lines.append(f"- 梯度分布：{tier_text}。")
    if isinstance(school_nature_distribution, dict):
        nature_counts = school_nature_distribution.get("counts") or {}
        public_count = int(nature_counts.get("公办") or 0)
        private_count = int(nature_counts.get("民办") or 0)
        unknown_count = int(nature_counts.get("未知") or 0)
        known_total = int(school_nature_distribution.get("known_total") or 0)
        ratio = school_nature_distribution.get("public_ratio_percent")
        if known_total > 0:
            ratio_text = f"，已知院校性质里公办占比约 {ratio}%" if ratio is not None else ""
            unknown_text = f"，另有 {unknown_count} 个暂未标明性质" if unknown_count > 0 else ""
            lines.append(f"- 院校性质：公办 {public_count} 个，民办 {private_count} 个{ratio_text}{unknown_text}。")
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
    if (
        isinstance(school_nature_distribution, dict)
        and int(school_nature_distribution.get("known_total") or 0) > 0
    ):
        reply_focus.append("school_nature_distribution")
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
    school_keywords = _school_mentions_from_text(plan.user_goal, getattr(ctx.deps, "batch", None) or "01")[:3]
    if school_keywords:
        state_summary = await query_volunteer_plan(
            ctx,
            plan.user_goal,
            scope="plan",
            school_keywords=school_keywords,
            match_mode="and",
        )
        return PlanExecutionResult(
            applied=True,
            action_family="query_state",
            stage=plan.stage,
            result_kind="status_overview",
            workspace_refresh_targets=[],
            context_summary=plan.context_summary,
            state_summary=state_summary,
            summary=state_summary,
            reply_focus=["local_plan_query", "current_state"],
            reply_strategy="direct_reply",
            facts={
                "query_redirect": "local_plan_query",
                "query_filters": {"school_keywords": school_keywords},
            },
        )

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
            ordered_items = ordered_state.get("items") or []
            if ordered_items and not _has_school_nature_metadata(ordered_items):
                ordered_state = dict(ordered_state)
                ordered_state["items"] = await _enrich_plan_items_with_candidate_metadata(session_id, ordered_items)
    elif draft_total > 0:
        draft_result = await _get_planning_draft_request(session_id)
        if draft_result.get("code") == 0:
            draft_state = draft_result.get("data") or {}
            draft_items = draft_state.get("items") or []
            if draft_items and not _has_school_nature_metadata(draft_items):
                draft_state = dict(draft_state)
                draft_state["items"] = await _enrich_plan_items_with_candidate_metadata(session_id, draft_items)

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
    filters = dict(atomic.filters if atomic else {})
    query_filters = await _build_candidate_query_filters(ctx, plan, atomic)

    state_summary = await query_planning_candidate_pool(
        ctx,
        tiers=query_filters.get("tiers") or None,
        province_names=query_filters.get("province_names") or None,
        city_names=query_filters.get("city_names") or None,
        school_keywords=query_filters.get("school_keywords") or None,
        major_keywords=query_filters.get("major_keywords") or None,
        school_tags=query_filters.get("school_tags") or None,
        major_tags=query_filters.get("major_tags") or None,
        page=1,
        page_size=int(filters.get("limit") or 5),
    )
    if _candidate_query_failed(state_summary):
        user_summary = "候选池这次没有查成功，暂时不能据此判断还有哪些可选机会。请稍后重试，或先在页面候选区查看当前筛选结果。"
        return PlanExecutionResult(
            applied=False,
            action_family="query_candidates",
            stage=plan.stage,
            result_kind="error",
            workspace_refresh_targets=[],
            context_summary=plan.context_summary,
            state_summary=user_summary,
            summary=user_summary,
            reply_focus=["candidate_query_failed"],
            reply_strategy="direct_blocking",
            next_step_hints=["候选查询失败时不要编造候选列表，也不要继续提示确认执行方案修改。"],
            facts={
                "raw_error": state_summary,
                "query_filters": query_filters,
            },
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
