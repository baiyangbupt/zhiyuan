"""Semantic plan-action classification.

This module classifies a user turn into a structured Plan action family.  It is
not a text shortcut and does not execute tools.  Runtime callers may consume the
result only when confidence is high; otherwise the full agent remains the
source of truth.
"""

from __future__ import annotations

import json
import logging
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_ai import Agent

from app.agent.context import PlanningSummary, RequestContext
from app.config import LLMConfig
from app.llm.client import LLMClient
from app.tools.extraction_json import parse_extraction_json

logger = logging.getLogger(__name__)

PlanSemanticAction = Literal[
    "none",
    "query_state",
    "review_plan",
    "analyze_adjustment",
    "preview_fix_proposal",
]
PendingSemanticAction = Literal[
    "none",
    "confirm_pending",
    "reject_pending",
    "ask_pending_impact",
]


class PlanSemanticActionDecision(BaseModel):
    actionFamily: PlanSemanticAction = "none"
    confidence: float = 0.0
    reason: str = ""
    targetStrategies: list[str] = Field(default_factory=list)

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, value: object) -> float:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"high", "高", "高置信"}:
                return 0.9
            if normalized in {"medium", "中", "中等", "中置信"}:
                return 0.65
            if normalized in {"low", "低", "低置信"}:
                return 0.35
        return float(value or 0.0)


class PendingSemanticActionDecision(BaseModel):
    action: PendingSemanticAction = "none"
    confidence: float = 0.0
    reason: str = ""

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, value: object) -> float:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"high", "高", "高置信"}:
                return 0.9
            if normalized in {"medium", "中", "中等", "中置信"}:
                return 0.65
            if normalized in {"low", "低", "低置信"}:
                return 0.35
        return float(value or 0.0)


_plan_action_llm_client: LLMClient | None = None
_plan_action_agent: Agent[None, str] | None = None
_pending_action_agent: Agent[None, str] | None = None


def _get_plan_action_llm_client() -> LLMClient:
    global _plan_action_llm_client
    if _plan_action_llm_client is None:
        _plan_action_llm_client = LLMClient(LLMConfig())
    return _plan_action_llm_client


def _get_plan_action_agent() -> Agent[None, str]:
    global _plan_action_agent
    if _plan_action_agent is None:
        _plan_action_agent = Agent(
            model=_get_plan_action_llm_client().model,
            output_type=str,
            instructions=(
                "你是高考志愿方案对话的结构化动作判定器，只输出 JSON。"
                "任务是判断当前用户在方案层到底需要哪类动作，不负责回复用户，也不执行方案。"
                "不要依据固定关键词或模板做判断，要基于用户语义、上下文和副作用边界判断。"
                "actionFamily 只能是 none、query_state、review_plan、analyze_adjustment、preview_fix_proposal。"
                "query_state 表示用户只想查看当前方案概况、数量、分布或状态。"
                "review_plan 表示用户想重新审查风险、查看审查结论或校验审查是否准确。"
                "analyze_adjustment 表示用户想理解问题、比较处理方向、知道为什么不能处理或怎么取舍，"
                "但还没有要求系统生成一版可确认的调整内容。"
                "preview_fix_proposal 表示用户希望系统把可执行的方案处理建议整理成调整预览，"
                "用于后续确认执行；典型语义包括想看会怎么动、先看调整预览、让系统处理当前审查建议、"
                "补稳/补安全垫/调稳并需要给出可确认方案。"
                "如果用户只是说看不懂、分一下、解释为什么、告诉我怎么调，通常是 analyze_adjustment。"
                "如果用户语义同时包含查看问题和生成处理预览，且目标是当前方案调整，优先 preview_fix_proposal。"
                "高副作用的真正执行不在这里决定；这里最多决定是否生成预览。"
                "targetStrategies 可选填后端修复策略线索，例如 sort_by_probability、adjust_major_group_inner_safety、"
                "fill_probability_gap、rebalance_tier_ratio、replace_risk_items、remove_risk_items。"
                "只有很确定时 confidence >= 0.8；不确定时 actionFamily=none 或 confidence < 0.8。"
                "输出 JSON：actionFamily, confidence, reason, targetStrategies。"
            ),
            model_settings=_get_plan_action_llm_client().model_settings,
        )
    return _plan_action_agent


def _get_pending_action_agent() -> Agent[None, str]:
    global _pending_action_agent
    if _pending_action_agent is None:
        _pending_action_agent = Agent(
            model=_get_plan_action_llm_client().model,
            output_type=str,
            instructions=(
                "你是高考志愿对话的待处理内容判定器，只输出 JSON。"
                "任务是判断当前用户回复与当前 active pending 内容的关系，不负责回复用户，也不执行动作。"
                "不要依据固定关键词、固定短语或模板做判断，要基于用户语义、当前待处理内容和上下文一致性判断。"
                "action 只能是 none、confirm_pending、reject_pending、ask_pending_impact。"
                "confirm_pending 表示用户清楚地接受当前等待采纳/确认的内容，并希望继续执行或正式采用。"
                "reject_pending 表示用户不想采用当前等待处理的内容、否定当前预览，或明确要求先不处理。"
                "ask_pending_impact 表示用户没有确认或拒绝，只是在追问这条内容的影响、范围、命中项、当前方案关系或后果。"
                "none 表示用户在开启新问题、表达不清、转到别的主题，或无法判断是否针对当前待处理内容。"
                "如果用户的回复可能与当前待处理内容不一致、可能是在确认别的内容，必须 action=none 或低置信。"
                "只有很确定时 confidence >= 0.85；不确定时 confidence < 0.85。"
                "输出 JSON：action, confidence, reason。"
            ),
            model_settings=_get_plan_action_llm_client().model_settings,
        )
    return _pending_action_agent


def _planning_summary_payload(summary: PlanningSummary | None) -> dict[str, object]:
    if summary is None:
        return {}
    return {
        "phase": summary.phase,
        "version": summary.version,
        "draftTotal": summary.draft_total,
        "orderedTotal": summary.ordered_total,
        "orderedTargetTotal": summary.ordered_target_total,
        "reviewRiskCount": summary.review_risk_count,
        "reviewWarnCount": summary.review_warn_count,
        "riskSummaries": summary.risk_summaries,
        "pendingActionCount": summary.pending_action_count,
        "tierCounts": summary.tier_counts,
    }


def _pending_state_payload(pending_state: dict[str, object] | None) -> dict[str, object]:
    if not isinstance(pending_state, dict):
        return {}
    execution_payload = pending_state.get("executionPayload")
    if not isinstance(execution_payload, dict):
        execution_payload = {}
    return {
        "kind": pending_state.get("kind") or "",
        "status": pending_state.get("status") or "",
        "actionFamily": pending_state.get("actionFamily") or "",
        "summary": pending_state.get("summary") or "",
        "userGoal": pending_state.get("userGoal") or "",
        "proposalTitle": execution_payload.get("proposalTitle") or "",
        "proposalSummary": execution_payload.get("proposalSummary") or "",
        "intentMode": execution_payload.get("intentMode") or "",
        "constraintIntentType": execution_payload.get("constraintIntentType") or "",
    }


def _normalize_plan_semantic_action_decision(decision: PlanSemanticActionDecision) -> PlanSemanticActionDecision:
    action_family = str(decision.actionFamily or "none").strip()
    allowed = {"none", "query_state", "review_plan", "analyze_adjustment", "preview_fix_proposal"}
    if action_family not in allowed:
        action_family = "none"
    confidence = max(0.0, min(1.0, float(decision.confidence or 0.0)))
    return PlanSemanticActionDecision(
        actionFamily=action_family,  # type: ignore[arg-type]
        confidence=confidence,
        reason=str(decision.reason or "").strip(),
        targetStrategies=[
            str(item or "").strip()
            for item in decision.targetStrategies
            if str(item or "").strip()
        ],
    )


def _normalize_pending_semantic_action_decision(
    decision: PendingSemanticActionDecision,
) -> PendingSemanticActionDecision:
    action = str(decision.action or "none").strip()
    allowed = {"none", "confirm_pending", "reject_pending", "ask_pending_impact"}
    if action not in allowed:
        action = "none"
    confidence = max(0.0, min(1.0, float(decision.confidence or 0.0)))
    return PendingSemanticActionDecision(
        action=action,  # type: ignore[arg-type]
        confidence=confidence,
        reason=str(decision.reason or "").strip(),
    )


async def classify_plan_semantic_action(
    latest_utterance: str,
    *,
    request_context: RequestContext,
    recent_plan_context: dict[str, object] | None = None,
) -> PlanSemanticActionDecision:
    prompt = json.dumps(
        {
            "latestUserText": latest_utterance,
            "planningSummary": _planning_summary_payload(getattr(request_context, "planning_summary", None)),
            "activePending": bool(getattr(getattr(request_context, "conversation_phase", None), "pending", None)),
            "recentPlanContext": recent_plan_context or {},
            "decisionQuestion": "当前用户是否在方案层要求查看、审查、分析调整，还是生成可确认的处理预览？",
        },
        ensure_ascii=False,
    )
    result = await _get_plan_action_agent().run(prompt)
    return _normalize_plan_semantic_action_decision(
        parse_extraction_json(result.output, PlanSemanticActionDecision)
    )


async def classify_pending_confirmation_action(
    latest_utterance: str,
    *,
    pending_state: dict[str, object] | None,
    request_context: RequestContext,
) -> PendingSemanticActionDecision:
    prompt = json.dumps(
        {
            "latestUserText": latest_utterance,
            "pendingState": _pending_state_payload(pending_state),
            "planningSummary": _planning_summary_payload(getattr(request_context, "planning_summary", None)),
            "decisionQuestion": "当前用户回复是在确认、拒绝、追问当前待处理内容，还是开启了其他话题？",
        },
        ensure_ascii=False,
    )
    result = await _get_pending_action_agent().run(prompt)
    return _normalize_pending_semantic_action_decision(
        parse_extraction_json(result.output, PendingSemanticActionDecision)
    )
