from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from pydantic_ai import RunContext

from app.agent.context import RequestContext
from app.tools.plan_orchestration_models import PlanContextInputs
from app.tools.review_issue_registry import build_review_issue_scopes, summarize_review_issue_scope
from app.tools.planning_workflow_tool import (
    _build_plan_intent_relation_lines,
    _extract_plan_intent_state,
    _normalize_career_labels,
    merge_planning_state_with_user_profile,
)
from app.util.internal_client import get_planning_state, get_user_profile

logger = logging.getLogger(__name__)


def _summary_total(summary: dict[str, Any] | None) -> int:
    summary = summary or {}
    return summary.get("unitTotal") or summary.get("total") or 0


def _summary_target(summary: dict[str, Any] | None, fallback: int = 0) -> int:
    summary = summary or {}
    return summary.get("targetUnitCount") or summary.get("targetCount") or fallback


async def _collect_plan_context_inputs_model(
    ctx: RunContext[RequestContext],
) -> PlanContextInputs:
    session_id = ctx.deps.sessionid
    logger.info("collect_plan_context_inputs: session_id=%s", session_id)
    planning_result, profile_result = await asyncio.gather(
        get_planning_state(session_id),
        get_user_profile(session_id),
        return_exceptions=True,
    )
    if isinstance(planning_result, Exception):
        logger.warning("collect_plan_context_inputs planning_state fetch failed: session_id=%s error=%s", session_id, planning_result)
        planning_state = {}
    else:
        planning_state = planning_result.get("data") if isinstance(planning_result, dict) and planning_result.get("code") == 0 else {}
    if isinstance(profile_result, Exception):
        logger.warning("collect_plan_context_inputs user_profile fetch failed: session_id=%s error=%s", session_id, profile_result)
        user_profile = {}
    else:
        user_profile = (((profile_result or {}).get("data") or {}).get("userprofile") or {})
    planning_state = merge_planning_state_with_user_profile(planning_state, user_profile)

    draft_summary = ((planning_state.get("draftPlanState") or {}).get("summary") or {})
    ordered_summary = ((planning_state.get("orderedPlanState") or {}).get("summary") or {})
    review_summary = ((planning_state.get("reviewState") or {}).get("summary") or {})
    review_checks = ((planning_state.get("reviewState") or {}).get("checks") or [])
    candidate_required = ((planning_state.get("candidatePoolState") or {}).get("requiredCount") or 0)

    ordered_items = ((planning_state.get("orderedPlanState") or {}).get("items") or [])
    draft_items = ((planning_state.get("draftPlanState") or {}).get("items") or [])
    plan_items = ordered_items or draft_items
    plan_summary = ordered_summary if ordered_items else draft_summary
    intent_state = _extract_plan_intent_state(planning_state)
    relation_lines = _build_plan_intent_relation_lines(
        planning_state,
        plan_items,
        plan_summary=plan_summary,
        include_position=True,
    )
    review_issues = build_review_issue_scopes(review_checks, plan_items)
    review_issue_summary_lines = [
        summarize_review_issue_scope(issue)
        for issue in review_issues[:5]
    ]

    model = PlanContextInputs(
        phase=str(planning_state.get("phase") or ""),
        target_count=_summary_target(ordered_summary, fallback=candidate_required),
        draft_count=_summary_total(draft_summary),
        ordered_count=_summary_total(ordered_summary),
        risk_count=int(review_summary.get("riskCount") or 0),
        warn_count=int(review_summary.get("warnCount") or 0),
        positive_majors=intent_state["positiveMajors"],
        negative_majors=intent_state["negativeMajors"],
        positive_schools=intent_state["positiveSchools"],
        negative_schools=intent_state["negativeSchools"],
        positive_regions=intent_state["positiveRegions"],
        negative_regions=intent_state["negativeRegions"],
        career_types=_normalize_career_labels(intent_state["careerTypes"]),
        relation_lines=relation_lines,
        review_issues=review_issues,
        review_issue_summary_lines=review_issue_summary_lines,
    )

    summary_parts = []
    if model.ordered_count > 0:
        summary_parts.append(f"已有 {model.ordered_count} 个志愿（目标 {model.target_count or model.ordered_count} 个）")
    elif model.draft_count > 0:
        summary_parts.append(f"已加入方案 {model.draft_count} 个志愿（目标 {model.target_count or model.draft_count} 个），尚未生成正式顺序")
    else:
        summary_parts.append("尚未生成方案")
    if model.risk_count > 0 or model.warn_count > 0:
        summary_parts.append(f"审查发现风险 {model.risk_count} 项、提醒 {model.warn_count} 项")
    if model.positive_regions:
        summary_parts.append(f"偏好地区：{'、'.join(model.positive_regions[:3])}")
    if model.negative_regions:
        summary_parts.append(f"排除地区：{'、'.join(model.negative_regions[:3])}")
    if model.positive_majors:
        summary_parts.append(f"偏好专业：{'、'.join(model.positive_majors[:3])}")
    if model.negative_majors:
        summary_parts.append(f"排除专业：{'、'.join(model.negative_majors[:3])}")
    if model.positive_schools:
        summary_parts.append(f"偏好院校：{'、'.join(model.positive_schools[:3])}")
    if model.negative_schools:
        summary_parts.append(f"排除院校：{'、'.join(model.negative_schools[:3])}")
    if model.career_types:
        summary_parts.append(f"发展方向：{'、'.join(model.career_types[:2])}")
    if relation_lines:
        summary_parts.append(relation_lines[0].removeprefix("- ").strip())
    if len(relation_lines) > 1:
        summary_parts.append(relation_lines[1].removeprefix("- ").strip())
    if review_issue_summary_lines:
        summary_parts.append(f"审查问题：{'、'.join(review_issue_summary_lines[:3])}")
    model.summary = "；".join(summary_parts)
    return model


async def collect_plan_context_inputs(
    ctx: RunContext[RequestContext],
) -> str:
    """读取 Plan 编排需要的现有画像与方案状态输入摘要。"""
    model = await _collect_plan_context_inputs_model(ctx)
    return json.dumps(model.model_dump(), ensure_ascii=False)
