"""Unified fix-proposal preview handler.

This is the Agent-facing repair preview path. It reads Java Server
FixProposal facts only; applying a proposal must go through pending
confirmation and the backend apply API.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic_ai import RunContext

from app.agent.context import RequestContext
from app.handlers.analysis_handlers import _fix_proposal_lines
from app.handlers.registry import register_handler
from app.tools.plan_orchestration_models import PlanActionPlan, PlanExecutionResult
from app.tools.planning_workflow_tool import _fix_proposal_facts
from app.util.internal_client import generate_planning_fix_proposals as _generate_planning_fix_proposals_request

logger = logging.getLogger(__name__)

_DEFAULT_TENANT_ID = 1


def _build_fix_proposal_preview_summary(facts: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    proposals = facts.get("proposals") or []
    if not proposals:
        return (
            "已查看当前方案的可处理建议，暂时没有需要自动处理的项目。你可以继续查看审查明细，或说明想重点调整的方向。",
            ["fix_proposal_preview", "empty_fix_proposal_preview"],
            ["当前没有后端可执行修复建议；不要承诺自动补齐或自动替换。"],
        )

    ready_count = int(facts.get("ready_count") or 0)
    blocked_count = int(facts.get("blocked_count") or 0)
    preview_only_count = int(facts.get("preview_only_count") or 0)
    lines = _fix_proposal_lines({"fix_proposals": facts}, limit=3)
    summary_parts = []
    if ready_count > 0:
        summary_parts.append(f"{ready_count} 项可以先看预览后执行")
    if blocked_count > 0:
        summary_parts.append(f"{blocked_count} 项需要先人工取舍或放宽条件")
    if preview_only_count > 0:
        summary_parts.append(f"{preview_only_count} 项先作为处理方向参考")
    parts = ["已生成当前方案的处理建议：" + "，".join(summary_parts)]
    if lines:
        parts.append("重点可以先看：" + "；".join(lines[:2]))
    reply_focus = ["fix_proposal_preview"]
    if ready_count > 0:
        reply_focus.append("ready_fix_proposals")
    if blocked_count > 0:
        reply_focus.append("blocked_fix_proposals")
    if preview_only_count > 0:
        reply_focus.append("preview_only_fix_proposals")
    next_step_hints = [
        "这只是调整预览；只有已经给出明确处理动作的建议才可以进入确认执行。",
        "遇到需要人工取舍或仅供参考的建议时，只说明可放宽方向，不要承诺直接执行。",
    ]
    return "；".join(parts) + "。", reply_focus, next_step_hints


@register_handler("preview_fix_proposal")
async def handle_preview_fix_proposal(
    ctx: RunContext[RequestContext], plan: PlanActionPlan
) -> PlanExecutionResult:
    session_id = ctx.deps.sessionid
    try:
        result = await _generate_planning_fix_proposals_request(_DEFAULT_TENANT_ID, session_id)
    except Exception:
        logger.exception("generate fix proposals failed: session_id=%s", session_id)
        return PlanExecutionResult(
            applied=False,
            action_family="preview_fix_proposal",
            stage=plan.stage,
            result_kind="error",
            context_summary=plan.context_summary,
            summary="这次没有成功生成调整预览。可以先查看方案审查结果，或稍后再试。",
            reply_focus=["fix_proposal_preview_failed"],
            reply_strategy="direct_blocking",
            next_step_hints=["不要改动方案；请用户重新审查或稍后再生成调整预览。"],
        )

    if result.get("code") != 0:
        return PlanExecutionResult(
            applied=False,
            action_family="preview_fix_proposal",
            stage=plan.stage,
            result_kind="error",
            context_summary=plan.context_summary,
            summary=str(result.get("msg") or "这次没有成功生成调整预览。可以先查看方案审查结果，或稍后再试。"),
            reply_focus=["fix_proposal_preview_failed"],
            reply_strategy="direct_blocking",
            next_step_hints=["不要改动方案；请用户重新审查或稍后再生成调整预览。"],
        )

    facts = _fix_proposal_facts(result.get("data") or {})
    state_summary, reply_focus, next_step_hints = _build_fix_proposal_preview_summary(facts)
    return PlanExecutionResult(
        applied=False,
        action_family="preview_fix_proposal",
        stage=plan.stage,
        result_kind="fix_proposal_preview",
        context_summary=plan.context_summary,
        state_summary=state_summary,
        summary=state_summary,
        reply_focus=reply_focus,
        next_step_hints=next_step_hints,
        facts={"fix_proposals": facts},
    )
