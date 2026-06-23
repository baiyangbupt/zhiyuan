"""3.2.0 reply profile live-node evaluators.

These tools are benchmark-facing only. They classify reply focus and grounding
requirements into 3.2.0 profile fields without generating a user-visible reply
or touching runtime state.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field, field_validator
from pydantic_ai import Agent

from app.config import LLMConfig
from app.llm.client import LLMClient
from app.tools.extraction_json import parse_extraction_json

logger = logging.getLogger(__name__)

_reply_profile_client: LLMClient | None = None


def _normalize_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if not isinstance(value, (list, tuple, set)):
        value = [value]
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1", "是", "需要", "必须"}:
            return True
        if normalized in {"false", "no", "0", "否", "不需要"}:
            return False
    return bool(value)


def _coerce_confidence(value: Any) -> float:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"high", "高", "高置信"}:
            return 0.9
        if normalized in {"medium", "中", "中等", "中置信"}:
            return 0.65
        if normalized in {"low", "低", "低置信"}:
            return 0.35
    return max(0.0, min(1.0, float(value or 0.0)))


class ReplyFocusBindingResult(BaseModel):
    answerFocusFirst: bool = False
    targetIssue: list[str] = Field(default_factory=list)
    sideEffectBoundary: str = ""
    confidence: float = 0.0
    reason: str = ""

    @field_validator("answerFocusFirst", mode="before")
    @classmethod
    def _coerce_answer_focus_first(cls, value: Any) -> bool:
        return _coerce_bool(value)

    @field_validator("targetIssue", mode="before")
    @classmethod
    def _coerce_target_issue(cls, value: Any) -> list[str]:
        return _normalize_text_list(value)

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence_field(cls, value: Any) -> float:
        return _coerce_confidence(value)


class ReplyGroundingResult(BaseModel):
    mustGroundFormula: bool = False
    missingInfo: list[str] = Field(default_factory=list)
    forbidPreciseScore: bool = False
    confidence: float = 0.0
    reason: str = ""

    @field_validator("mustGroundFormula", "forbidPreciseScore", mode="before")
    @classmethod
    def _coerce_bool_fields(cls, value: Any) -> bool:
        return _coerce_bool(value)

    @field_validator("missingInfo", mode="before")
    @classmethod
    def _coerce_missing_info(cls, value: Any) -> list[str]:
        return _normalize_text_list(value)

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence_field(cls, value: Any) -> float:
        return _coerce_confidence(value)


def _get_reply_profile_client() -> LLMClient:
    global _reply_profile_client
    if _reply_profile_client is None:
        _reply_profile_client = LLMClient(LLMConfig())
    return _reply_profile_client


def _build_focus_prompt(latest_utterance: str, payload: dict[str, Any] | None = None) -> str:
    return json.dumps(
        {
            "latestUserText": latest_utterance,
            "context": payload or {},
            "task": "判断回复是否应优先绑定用户问点和只读边界。只输出一个 JSON object，不生成用户回复。",
            "allowedValues": {
                "targetIssue": [
                    "cooperative_program",
                    "tuition_budget",
                    "high_tuition",
                    "private_school",
                    "risk_warning",
                    "major_scope",
                    "admission_probability",
                    "formula_uncertainty",
                ],
                "sideEffectBoundary": [
                    "readonly_no_apply",
                    "can_apply_with_confirmation",
                    "mutation_pending",
                    "clarification",
                ],
            },
            "schemaRules": [
                "最终回答必须只包含一个 JSON object。",
                "answerFocusFirst=true 表示回复第一优先级应回答用户明确问点，而不是泛化审查或直接建议调整。",
                "targetIssue 必须使用 allowedValues.targetIssue 的英文 ID。",
                "sideEffectBoundary 必须使用 allowedValues.sideEffectBoundary 的英文 ID。",
                "用户说先别动、先看看、帮我看风险时，sideEffectBoundary=readonly_no_apply。",
                "预算一般 + 中外合作/高收费风险，必须同时包含 cooperative_program 和 tuition_budget。",
            ],
            "examples": [
                {
                    "latestUserText": "方案里中外合作是不是有点多，家里预算一般，帮我用大白话看下风险，先别动",
                    "output": {
                        "answerFocusFirst": True,
                        "targetIssue": ["cooperative_program", "tuition_budget"],
                        "sideEffectBoundary": "readonly_no_apply",
                    },
                }
            ],
            "returnJson": {
                "answerFocusFirst": False,
                "targetIssue": [],
                "sideEffectBoundary": "",
                "confidence": 0.0,
                "reason": "",
            },
        },
        ensure_ascii=False,
    )


def _build_grounding_prompt(latest_utterance: str, payload: dict[str, Any] | None = None) -> str:
    return json.dumps(
        {
            "latestUserText": latest_utterance,
            "context": payload or {},
            "task": "判断回复生成前需要哪些 grounding 约束。只输出一个 JSON object，不生成用户回复。",
            "allowedValues": {
                "missingInfo": [
                    "province",
                    "art_formula",
                    "score_or_rank",
                    "batch",
                    "subject_combination",
                    "major_direction",
                ]
            },
            "schemaRules": [
                "最终回答必须只包含一个 JSON object。",
                "艺考/美术综合分、文化课、联考分相关问题必须先确认省份和当地综合分公式。",
                "缺 province 或 art_formula 时，mustGroundFormula=true 且 forbidPreciseScore=true。",
                "forbidPreciseScore=true 表示不能编造精确综合分、位次或可上学校结论。",
                "missingInfo 必须使用 allowedValues.missingInfo 的英文 ID。",
            ],
            "examples": [
                {
                    "latestUserText": "我美术生文化课580联考250综合多少能上啥",
                    "output": {
                        "mustGroundFormula": True,
                        "missingInfo": ["province", "art_formula"],
                        "forbidPreciseScore": True,
                    },
                }
            ],
            "returnJson": {
                "mustGroundFormula": False,
                "missingInfo": [],
                "forbidPreciseScore": False,
                "confidence": 0.0,
                "reason": "",
            },
        },
        ensure_ascii=False,
    )


def _normalize_focus_result(result: ReplyFocusBindingResult) -> ReplyFocusBindingResult:
    confidence = _coerce_confidence(result.confidence)
    return ReplyFocusBindingResult(
        answerFocusFirst=bool(result.answerFocusFirst),
        targetIssue=result.targetIssue,
        sideEffectBoundary=str(result.sideEffectBoundary or "").strip(),
        confidence=confidence,
        reason=result.reason,
    )


def _normalize_grounding_result(result: ReplyGroundingResult) -> ReplyGroundingResult:
    confidence = _coerce_confidence(result.confidence)
    return ReplyGroundingResult(
        mustGroundFormula=bool(result.mustGroundFormula),
        missingInfo=result.missingInfo,
        forbidPreciseScore=bool(result.forbidPreciseScore),
        confidence=confidence,
        reason=result.reason,
    )


async def classify_reply_focus_binding(
    latest_utterance: str,
    *,
    payload: dict[str, Any] | None = None,
) -> ReplyFocusBindingResult:
    text = str(latest_utterance or "").strip()
    if not text:
        return ReplyFocusBindingResult()
    agent = Agent(
        model=_get_reply_profile_client().model,
        output_type=str,
        instructions=_build_focus_prompt(text, payload),
    )
    result = await agent.run("请输出 reply_focus_binding JSON", model_settings={"temperature": 0})
    parsed = parse_extraction_json(result.output, ReplyFocusBindingResult)
    normalized = _normalize_focus_result(parsed)
    logger.info(
        "classify_reply_focus_binding: focus=%s issues=%s boundary=%s confidence=%s",
        normalized.answerFocusFirst,
        normalized.targetIssue,
        normalized.sideEffectBoundary,
        normalized.confidence,
    )
    return normalized


async def classify_reply_generation_grounding(
    latest_utterance: str,
    *,
    payload: dict[str, Any] | None = None,
) -> ReplyGroundingResult:
    text = str(latest_utterance or "").strip()
    if not text:
        return ReplyGroundingResult()
    agent = Agent(
        model=_get_reply_profile_client().model,
        output_type=str,
        instructions=_build_grounding_prompt(text, payload),
    )
    result = await agent.run("请输出 reply_generation_grounding JSON", model_settings={"temperature": 0})
    parsed = parse_extraction_json(result.output, ReplyGroundingResult)
    normalized = _normalize_grounding_result(parsed)
    logger.info(
        "classify_reply_generation_grounding: formula=%s missing=%s forbid=%s confidence=%s",
        normalized.mustGroundFormula,
        normalized.missingInfo,
        normalized.forbidPreciseScore,
        normalized.confidence,
    )
    return normalized
