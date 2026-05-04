"""分析类 handler。

覆盖 action_family: analyze_adjustment, review_plan。
只读分析，不涉及方案变更副作用。
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic_ai import RunContext

from app.agent.context import RequestContext
from app.handlers.registry import register_handler
from app.handlers.query_handlers import _get_planning_state_with_latest_profile, _compact_list_text
from app.tools.plan_orchestration_models import PlanActionPlan, PlanExecutionResult
from app.tools.planning_workflow_tool import (
    _build_plan_adjustment_facts,
    _build_review_result_facts,
)
from app.util.internal_client import (
    analyze_planning_plan_adjustment as _analyze_planning_plan_adjustment_request,
    get_planning_draft as _get_planning_draft_request,
    get_planning_ordered_plan as _get_planning_ordered_plan_request,
    run_planning_review as _run_planning_review_request,
)

logger = logging.getLogger(__name__)

_DEFAULT_TENANT_ID = 1


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------


def _normalize_review_summary_for_user(summary: str) -> str:
    normalized = str(summary or "").strip()
    if "部分专业组主要依靠非意向专业托底" in normalized:
        return "部分专业组主要依靠非意向托底专业作为组内安全垫"
    if "存在专业组缺少组内安全垫专业" in normalized:
        return "部分专业组缺少组内安全垫专业"
    return normalized


def _issue_hit_plan_examples_text(items: list[dict[str, Any]] | None, *, limit: int = 2) -> str:
    snippets: list[str] = []
    for item in (items or [])[:limit]:
        if not isinstance(item, dict):
            continue
        summary = str(item.get("summary") or "").strip()
        affected_items = [
            str(name or "").strip()
            for name in (item.get("items") or [])
            if str(name or "").strip()
        ]
        if not summary or not affected_items:
            continue
        snippets.append(f"{summary}：{'；'.join(affected_items[:2])}")
    return "；".join(snippets)


def _adjustment_first_step_hint(facts: dict[str, Any]) -> str:
    for item in facts.get("review_issue_hit_plan_examples") or []:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        affected_items = [
            str(name or "").strip()
            for name in (item.get("items") or [])
            if str(name or "").strip()
        ]
        if code == "high_tuition":
            return "如果你想直接开始，我建议先把整批高收费项替换成正常收费的志愿，保持 30 个总数不变。"
        if code == "cooperative_program":
            return "如果你想直接开始，我建议先把中外合作这批志愿整批替换掉，再看结构怎么补稳。"
        if code == "major_group_safety_intent_alignment" and affected_items:
            return (
                f"如果你想先从局部开始，我建议先确认这组非意向托底是否接受：{affected_items[0]}。"
                "这类专业通常是为了让组内最低专业录取率不低于专业组整体录取率、降低退档风险而保留下来的牺牲项，直接去掉前最好先看有没有同等安全垫可以替换。"
            )
        if code == "group_inner_safety_guard" and affected_items:
            return (
                f"如果你想先从局部开始，我建议先补这组的安全垫专业：{affected_items[0]}。"
                "组内至少要保留 1 个录取率不低于专业组整体录取率的专业，才能更稳地防退档。"
            )
        if code == "probability_gap" and affected_items:
            return f"如果你想先从局部开始，我建议先围绕这段梯度断层做替换预览：{affected_items[0]}。"
    return ""


async def _fetch_ordered_or_draft(
    planning_state: dict[str, Any], session_id: str
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """根据 planning_state 按优先级获取 ordered 或 draft 详情。"""
    ordered_state: dict[str, Any] | None = None
    draft_state: dict[str, Any] | None = None

    if ((planning_state.get("orderedPlanState") or {}).get("summary") or {}).get("total"):
        ordered_result = await _get_planning_ordered_plan_request(session_id)
        if ordered_result.get("code") == 0:
            ordered_state = ordered_result.get("data") or {}
    elif ((planning_state.get("draftPlanState") or {}).get("summary") or {}).get("total"):
        draft_result = await _get_planning_draft_request(session_id)
        if draft_result.get("code") == 0:
            draft_state = draft_result.get("data") or {}

    return ordered_state, draft_state


def _build_review_summary(facts: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    risk_count = int(facts.get("risk_count") or 0)
    warn_count = int(facts.get("warn_count") or 0)
    normalized_problems = [
        _normalize_review_summary_for_user(item)
        for item in (facts.get("main_problems") or [])
    ]
    problems_text = _compact_list_text(normalized_problems)
    issue_examples_text = _issue_hit_plan_examples_text(facts.get("issue_hit_plan_examples"))
    compensation_count = int(facts.get("compensation_action_count") or 0)
    compensation_text = _compact_list_text(facts.get("compensation_summaries"))

    parts = [f"已完成方案审查，风险 {risk_count} 项，提醒 {warn_count} 项"]
    if problems_text:
        parts.append(f"主要问题是 {problems_text}")
    if issue_examples_text:
        parts.append(f"典型涉及 {issue_examples_text}")
    if compensation_count > 0 and compensation_text:
        parts.append(f"当前还有 {compensation_count} 项可补偿动作，主要是 {compensation_text}")

    reply_focus = ["review_result", "risk_warning"]
    if problems_text:
        reply_focus.append("main_problems")
    if issue_examples_text:
        reply_focus.append("issue_hit_plan_examples")
    if compensation_count > 0:
        reply_focus.append("compensation_options")

    next_step_hints: list[str] = []
    if compensation_count > 0:
        next_step_hints.append("如果用户想继续处理，可以先看看怎么补，再决定是否应用。")
    if risk_count == 0 and warn_count == 0:
        next_step_hints.append("如果用户只是确认当前是否稳定，可以明确说明目前没有明显风险或提醒。")
    return "；".join(parts) + "。", reply_focus, next_step_hints


def _build_adjustment_summary(facts: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    summary_text = str(facts.get("summary_text") or "").strip()
    suggestion_counts = facts.get("suggestion_counts") or {}
    actionable_counts = facts.get("actionable_suggestion_counts") or {}
    has_actionable_suggestions = bool(facts.get("has_actionable_suggestions"))
    rule_summaries = [
        _normalize_review_summary_for_user(item.get("summary"))
        for item in (facts.get("hit_rules") or [])
        if isinstance(item, dict) and str(item.get("summary") or "").strip()
    ]
    example_summaries = [
        str(item.get("description") or item.get("title") or "").strip()
        for item in (facts.get("example_suggestions") or [])
        if isinstance(item, dict) and str(item.get("description") or item.get("title") or "").strip()
    ]
    review_issue_hit_plan_examples_text = _issue_hit_plan_examples_text(
        facts.get("review_issue_hit_plan_examples")
    )
    first_step_hint = _adjustment_first_step_hint(facts)

    parts: list[str] = []
    if summary_text:
        parts.append(summary_text)
    elif rule_summaries:
        parts.append("；".join(rule_summaries[:2]))

    if has_actionable_suggestions:
        counts_text = (
            f"补充 {int(actionable_counts.get('add') or 0)} 条，"
            f"调序 {int(actionable_counts.get('reorder') or 0)} 条，"
            f"替换 {int(actionable_counts.get('replace') or 0)} 条，"
            f"移除 {int(actionable_counts.get('remove') or 0)} 条"
        )
        parts.append(f"当前可执行建议概览：{counts_text}")
    else:
        counts_text = (
            f"补充建议 {int(suggestion_counts.get('add') or 0)} 条，"
            f"调序建议 {int(suggestion_counts.get('reorder') or 0)} 条，"
            f"替换建议 {int(suggestion_counts.get('replace') or 0)} 条，"
            f"移除建议 {int(suggestion_counts.get('remove') or 0)} 条"
        )
        parts.append(f"当前先拿到的是分析结论，不是可直接执行的调整清单：{counts_text}")
    if example_summaries:
        parts.append(f"可以优先关注：{'；'.join(example_summaries[:2])}")
    if not example_summaries and review_issue_hit_plan_examples_text:
        parts.append(f"如果先从减法入手，可优先查看：{review_issue_hit_plan_examples_text}")
    if not has_actionable_suggestions and first_step_hint:
        parts.append(first_step_hint)

    reply_focus = ["adjustment_analysis", "suggestion_counts"]
    if summary_text or rule_summaries:
        reply_focus.append("main_issues")
    if example_summaries:
        reply_focus.append("example_suggestions")
    if not example_summaries and review_issue_hit_plan_examples_text:
        reply_focus.append("review_issue_hit_plan_examples")

    next_step_hints: list[str] = []
    if has_actionable_suggestions:
        next_step_hints.append(
            "如果用户想继续改方案，先把主要问题和建议方向讲清楚，再确认是否执行具体动作。"
        )
    else:
        next_step_hints.append(
            "如果用户要继续执行调整，不要直接承诺已能改方案；先说明当前只有分析结论，再收敛到可确认的局部替换、移除或重排。"
        )
        if first_step_hint:
            next_step_hints.append(
                "优先把用户引到当前系统已经能稳定执行的第一步动作，不要口头承诺整套更稳方案已经可直接执行。"
            )
    return "；".join(parts) + "。", reply_focus, next_step_hints


# ---------------------------------------------------------------------------
# Handler 实现
# ---------------------------------------------------------------------------


@register_handler("review_plan")
async def handle_review_plan(
    ctx: RunContext[RequestContext], plan: PlanActionPlan
) -> PlanExecutionResult:
    session_id = ctx.deps.sessionid
    review_result = await _run_planning_review_request(_DEFAULT_TENANT_ID, session_id)
    planning_state = await _get_planning_state_with_latest_profile(session_id)

    ordered_state, draft_state = await _fetch_ordered_or_draft(planning_state, session_id)

    review_state = review_result.get("data") or {} if review_result.get("code") == 0 else {}
    facts = _build_review_result_facts(
        review_state,
        planning_state=planning_state,
        ordered_state=ordered_state,
        draft_state=draft_state,
    )
    review_summary, reply_focus, next_step_hints = _build_review_summary(facts)

    return PlanExecutionResult(
        applied=True,
        action_family="review_plan",
        stage=plan.stage,
        result_kind="review_result",
        executed_actions=[{"action": "review_plan"}],
        workspace_refresh_targets=["review"],
        context_summary=plan.context_summary,
        review_summary=review_summary,
        state_summary=review_summary,
        summary=review_summary,
        reply_focus=reply_focus,
        next_step_hints=next_step_hints,
        facts=facts,
    )


@register_handler("analyze_adjustment")
async def handle_analyze_adjustment(
    ctx: RunContext[RequestContext], plan: PlanActionPlan
) -> PlanExecutionResult:
    session_id = ctx.deps.sessionid
    adjustment_result = await _analyze_planning_plan_adjustment_request(
        _DEFAULT_TENANT_ID, session_id
    )
    planning_state = await _get_planning_state_with_latest_profile(session_id)

    ordered_state, draft_state = await _fetch_ordered_or_draft(planning_state, session_id)

    adjustment_state = (
        adjustment_result.get("data") or {} if adjustment_result.get("code") == 0 else {}
    )
    facts = _build_plan_adjustment_facts(
        adjustment_state,
        planning_state=planning_state,
        ordered_state=ordered_state,
        draft_state=draft_state,
    )
    state_summary, reply_focus, next_step_hints = _build_adjustment_summary(facts)

    return PlanExecutionResult(
        applied=True,
        action_family="analyze_adjustment",
        stage=plan.stage,
        result_kind="adjustment_analysis",
        workspace_refresh_targets=["ordered", "review"],
        context_summary=plan.context_summary,
        state_summary=state_summary,
        summary=state_summary,
        reply_focus=reply_focus,
        next_step_hints=next_step_hints,
        facts=facts,
    )
