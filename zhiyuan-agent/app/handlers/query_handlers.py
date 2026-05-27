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
from app.util.display_text import brief_school_major_text, clean_plan_sample_text
from app.util.internal_client import (
    get_planning_draft as _get_planning_draft_request,
    get_planning_ordered_plan as _get_planning_ordered_plan_request,
    get_planning_state as _get_planning_state_request,
    get_user_profile as _get_user_profile_request,
)

from app.handlers.shared import summary_total

logger = logging.getLogger(__name__)
_HIGH_TUITION_THRESHOLD = 20000
_TUITION_PER_YEAR_RE = re.compile(r"(\d{4,6})\s*(?:元|/年)")
_BUDGET_RISK_GOAL_TOKENS = ("预算", "学费", "高收费", "中外合作", "费用", "贵")


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
    return clean_plan_sample_text(value)


def _looks_like_budget_risk_goal(text: str | None) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    return any(token in compact for token in _BUDGET_RISK_GOAL_TOKENS)


def _iter_text_values(value: Any):
    if value is None:
        return
    if isinstance(value, str):
        if value.strip():
            yield value.strip()
        return
    if isinstance(value, (int, float)):
        yield str(value)
        return
    if isinstance(value, dict):
        for child in value.values():
            yield from _iter_text_values(child)
        return
    if isinstance(value, list):
        for child in value:
            yield from _iter_text_values(child)


def _tuition_per_year(item: dict[str, Any]) -> int | None:
    raw_value = item.get("tuitionPerYear")
    if raw_value not in (None, ""):
        try:
            return int(float(raw_value))
        except (TypeError, ValueError):
            pass
    for text in _iter_text_values(item) or []:
        if "学费" not in text and "元" not in text:
            continue
        match = _TUITION_PER_YEAR_RE.search(text)
        if not match:
            continue
        try:
            return int(match.group(1))
        except ValueError:
            continue
    return None


def _iter_budget_item_views(item: dict[str, Any]):
    major_items = item.get("majorItems")
    if isinstance(major_items, list) and major_items:
        for major in major_items:
            if not isinstance(major, dict):
                continue
            merged = dict(item)
            merged.update(major)
            merged.setdefault("schoolName", item.get("schoolName"))
            merged.setdefault("tier", item.get("tier"))
            merged.setdefault("position", item.get("position"))
            yield merged
        return
    yield item


def _format_budget_risk_example(item: dict[str, Any]) -> str:
    school_name = str(item.get("schoolName") or "未知院校").strip()
    major_name = str(item.get("majorName") or "未知专业").strip()
    tier = str(item.get("tier") or "").strip()
    tuition = _tuition_per_year(item)
    parts = [brief_school_major_text(school_name, major_name)]
    if tier:
        parts.append(f"（{tier}）")
    if tuition is not None:
        parts.append(f"，学费约{tuition}元/年")
    return "".join(parts)


def _build_budget_risk_facts(items: list[dict[str, Any]], *, total_count: int = 0) -> dict[str, Any]:
    cooperative_unit_count = 0
    high_tuition_unit_count = 0
    examples: list[str] = []

    for item in items or []:
        if not isinstance(item, dict):
            continue
        unit_has_cooperative = False
        unit_has_high_tuition = False
        unit_examples: list[str] = []
        for view in _iter_budget_item_views(item):
            text = " ".join(_iter_text_values(view) or [])
            tuition = _tuition_per_year(view)
            is_cooperative = "中外合作" in text
            is_high_tuition = (
                "高收费" in text
                or (tuition is not None and tuition > _HIGH_TUITION_THRESHOLD)
            )
            if not is_cooperative and not is_high_tuition:
                continue
            unit_has_cooperative = unit_has_cooperative or is_cooperative
            unit_has_high_tuition = unit_has_high_tuition or is_high_tuition
            unit_examples.append(_format_budget_risk_example(view))
        if unit_has_cooperative:
            cooperative_unit_count += 1
        if unit_has_high_tuition:
            high_tuition_unit_count += 1
        for example in unit_examples:
            if example and example not in examples:
                examples.append(example)
            if len(examples) >= 3:
                break

    return {
        "total_count": total_count or len(items or []),
        "cooperative_unit_count": cooperative_unit_count,
        "high_tuition_unit_count": high_tuition_unit_count,
        "examples": examples[:3],
    }


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
    if current_total > 0:
        tier_counts = facts.get("tier_counts") if isinstance(facts.get("tier_counts"), dict) else {}
        rush_count = int(tier_counts.get("冲") or 0)
        safe_count = int(tier_counts.get("保") or 0)
        if risk_count > 0 and rush_count > safe_count:
            lines.append("先说结论：这版确实偏冲，保底明显不够。")
        elif risk_count > 0:
            lines.append("先说结论：这版有风险点，建议先看审查详情再决定怎么调。")
        elif warn_count > 0:
            lines.append("先说结论：这版整体可看，但还有提醒项需要复核。")
        else:
            lines.append("先说结论：这版暂时没有明显风险。")
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
    if current_total > 0:
        tier_counts = facts.get("tier_counts") if isinstance(facts.get("tier_counts"), dict) else {}
        rush_count = int(tier_counts.get("冲") or 0)
        safe_count = int(tier_counts.get("保") or 0)
        if rush_count > safe_count and (risk_count > 0 or safe_count == 0):
            lines.append("- 大白话：前面冲得多，后面兜底少；如果直接按这版走，最需要先补保区或压低部分冲区。")
    budget_risk = facts.get("budget_risk") if isinstance(facts.get("budget_risk"), dict) else {}
    if budget_risk:
        cooperative_count = int(budget_risk.get("cooperative_unit_count") or 0)
        high_tuition_count = int(budget_risk.get("high_tuition_unit_count") or 0)
        total_count_for_budget = int(budget_risk.get("total_count") or current_total or 0)
        if cooperative_count or high_tuition_count:
            lines.append(
                "- 预算风险："
                f"当前方案里疑似中外合作 {cooperative_count} 个、"
                f"高收费 {high_tuition_count} 个（总数 {total_count_for_budget} 个）。"
                "对预算一般的家庭，主要要确认每年学费、住宿和后续升学/转专业规则。"
            )
            examples = [
                _clean_plan_item_for_user(example)
                for example in (budget_risk.get("examples") or [])
                if str(example or "").strip()
            ]
            if examples:
                lines.append(f"- 代表样例：{'；'.join(examples[:2])}。")
        else:
            lines.append("- 预算风险：当前方案里没有明显识别到中外合作或高收费条目。")
        lines.append("- 本轮只是帮你看风险，不会改动方案。")
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
    if facts.get("budget_risk"):
        reply_focus.append("budget_risk")

    next_step_hints: list[str] = []
    if facts.get("budget_risk"):
        next_step_hints.append("如果用户继续关注预算，先解释中外合作/高收费的数量、典型条目和家庭承受边界，不要直接移除或替换。")
    if risk_count > 0 or warn_count > 0:
        next_step_hints.append("如果用户继续追问风险或不合理处，优先展开审查结果或调整分析。")
    if gap_hint:
        next_step_hints.append("如果用户关心数量是否够用，先解释当前目标数量与缺口。")
    if pending_count > 0:
        next_step_hints.append("如果用户想继续优化，可先解释待处理建议，再决定是否补偿或重排。")
    if current_total > 0:
        lines.append("下一步建议：先看审查详情；如果要调稳，可以说“先给我一版调稳预览”，我会先给影响说明，确认后再执行。")
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
    active_items = ((ordered_state or draft_state or {}).get("items") or [])
    if _looks_like_budget_risk_goal(plan.user_goal):
        facts["budget_risk"] = _build_budget_risk_facts(
            active_items,
            total_count=int(facts.get("current_total") or 0),
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
