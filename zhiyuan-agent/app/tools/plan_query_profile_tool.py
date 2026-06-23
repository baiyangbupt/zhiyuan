"""3.2.0 current-plan readonly query profile node.

This node classifies a user turn into a structured PlanQuery profile. It does
not execute tools, create pending cards, or write runtime state.
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

_plan_query_profile_client: LLMClient | None = None

QUERY_TYPE_VALUES = [
    "none",
    "readonly_plan_query",
    "readonly_plan_slice_query",
    "readonly_pending_reference_query",
]
SCOPE_ANCHOR_VALUES = ["current_plan", "pending_reference", "candidate_pool", "general"]
SIDE_EFFECT_VALUES = ["readonly", "readonly_while_pending", "none"]
DIMENSION_VALUES = ["tuition", "tier_segment", "pending_reference"]
FIELD_VALUES = ["school", "major", "admission_probability"]
PENDING_REFERENCE_TYPE_VALUES = ["major", "school", "none"]


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


class PlanQueryProfileResult(BaseModel):
    queryType: str = "none"
    scopeAnchor: str = "general"
    sideEffect: str = "none"
    dimensions: list[str] = Field(default_factory=list)
    condition: dict[str, Any] = Field(default_factory=dict)
    filters: dict[str, Any] = Field(default_factory=dict)
    projection: dict[str, Any] = Field(default_factory=dict)
    replyFocus: list[str] = Field(default_factory=list)
    pendingReferenceType: str = "none"
    confidence: float = 0.0
    reason: str = ""

    @field_validator("dimensions", "replyFocus", mode="before")
    @classmethod
    def _coerce_list_fields(cls, value: Any) -> list[str]:
        return _normalize_text_list(value)

    @field_validator("condition", "filters", "projection", mode="before")
    @classmethod
    def _coerce_dict_fields(cls, value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence_field(cls, value: Any) -> float:
        return _coerce_confidence(value)


def _get_plan_query_profile_client() -> LLMClient:
    global _plan_query_profile_client
    if _plan_query_profile_client is None:
        _plan_query_profile_client = LLMClient(LLMConfig())
    return _plan_query_profile_client


def _build_prompt(latest_utterance: str, payload: dict[str, Any] | None = None) -> str:
    payload = payload or {}
    return json.dumps(
        {
            "latestUserText": latest_utterance,
            "planningStateProfile": payload.get("planningStateProfile") or {},
            "pendingState": payload.get("pendingState") or {},
            "task": (
                "判断用户是否在只读查询当前正式方案或当前待采纳内容影响到的方案项。"
                "只输出 PlanQueryProfile JSON，不执行任何动作。"
            ),
            "allowedValues": {
                "queryType": QUERY_TYPE_VALUES,
                "scopeAnchor": SCOPE_ANCHOR_VALUES,
                "sideEffect": SIDE_EFFECT_VALUES,
                "dimensions": DIMENSION_VALUES,
                "fields": FIELD_VALUES,
                "pendingReferenceType": PENDING_REFERENCE_TYPE_VALUES,
            },
            "schemaRules": [
                "最终回答必须只包含一个 JSON object，禁止 markdown。",
                "用户要求删除、加入、替换、重排、生成方案、确认或执行时，queryType=none。",
                "只读查看方案内数量、名单、录取率、保底/稳/冲切片、费用阈值时，queryType 不能是 none。",
                "filters.limit 是 1-10 的整数；没明确数量时填 5。",
                "学费阈值必须结构化成 min_tuition_per_year 或 max_tuition_per_year，单位是元/年。",
                "同时必须输出 condition。condition 是统一查询合同，字段名对齐 Java CandidatePoolQueryReq：condition.filters.tiers/provinceNames/negativeProvinceNames/cityNames/negativeCityNames/schoolKeywords/negativeSchoolKeywords/majorKeywords/negativeMajorKeywords/schoolTags/negativeSchoolTags/majorTags/negativeMajorTags/minTuitionPerYear/maxTuitionPerYear，condition.sort.field/order，condition.page/pageSize。",
                "filters 是当前 ordered-plan 临时执行字段；condition 是后续下推 Java 的权威字段。两者表达的条件必须一致。",
                "“两万以上/超过两万/不低于两万”使用 min_tuition_per_year=20000；“两万以内/不超过两万”使用 max_tuition_per_year=20000。",
                "保底、稳档、冲档切片使用 filters.tier=保/稳/冲；最后/末尾/靠后使用 filters.slice=tail，否则 head。",
                "需要展示学校、专业或录取率时，把 school、major、admission_probability 放入 filters.include_fields 和 projection.fields。",
                "已有 pending 时，用户问“相关专业/这些学校/这个意向在当前方案里有没有”，queryType=readonly_pending_reference_query，并填写 pendingReferenceType=major 或 school；不要把待采纳内容自动生效。",
                "只问待采纳会有什么影响但没有要求查当前方案名单/数量时，queryType=none。",
            ],
            "examples": [
                {
                    "latestUserText": "两万以上的都算贵，帮我看看有几个",
                    "output": {
                        "queryType": "readonly_plan_query",
                        "scopeAnchor": "current_plan",
                        "sideEffect": "readonly",
                        "dimensions": ["tuition"],
                        "condition": {
                            "target": "ordered_plan",
                            "filters": {"minTuitionPerYear": 20000},
                            "sort": {"field": "position", "order": "asc"},
                            "page": 1,
                            "pageSize": 5,
                        },
                        "filters": {"limit": 5, "min_tuition_per_year": 20000},
                        "projection": {"mode": "count_with_examples", "limit": 5},
                        "replyFocus": ["ordered_snapshot", "local_plan_query", "plan_filter_query", "tuition"],
                        "pendingReferenceType": "none",
                    },
                },
                {
                    "latestUserText": "保底最后几个是什么学校，录取率多少",
                    "output": {
                        "queryType": "readonly_plan_slice_query",
                        "scopeAnchor": "current_plan",
                        "sideEffect": "readonly",
                        "dimensions": ["tier_segment"],
                        "condition": {
                            "target": "ordered_plan",
                            "filters": {"tiers": ["保"]},
                            "sort": {"field": "position", "order": "asc"},
                            "page": 1,
                            "pageSize": 5,
                        },
                        "filters": {
                            "limit": 5,
                            "tier": "保",
                            "slice": "tail",
                            "include_fields": ["school", "major", "admission_probability"],
                        },
                        "projection": {
                            "mode": "slice_examples",
                            "limit": 5,
                            "fields": ["school", "major", "admission_probability"],
                        },
                        "replyFocus": ["ordered_snapshot", "local_plan_query", "plan_slice_query"],
                        "pendingReferenceType": "none",
                    },
                },
                {
                    "latestUserText": "先不确认，当前方案里有没有相关专业",
                    "pendingState": {"kind": "intent_change"},
                    "output": {
                        "queryType": "readonly_pending_reference_query",
                        "scopeAnchor": "pending_reference",
                        "sideEffect": "readonly_while_pending",
                        "dimensions": ["pending_reference"],
                        "condition": {
                            "target": "ordered_plan",
                            "filters": {},
                            "sort": {"field": "position", "order": "asc"},
                            "page": 1,
                            "pageSize": 5,
                        },
                        "filters": {"limit": 5},
                        "projection": {"mode": "examples", "limit": 5},
                        "replyFocus": ["ordered_snapshot", "local_plan_query", "pending_reference_query"],
                        "pendingReferenceType": "major",
                    },
                },
            ],
            "returnJson": {
                "queryType": "none",
                "scopeAnchor": "general",
                "sideEffect": "none",
                "dimensions": [],
                "condition": {},
                "filters": {},
                "projection": {},
                "replyFocus": [],
                "pendingReferenceType": "none",
                "confidence": 0.0,
                "reason": "",
            },
        },
        ensure_ascii=False,
    )


def _normalize_plan_query_profile(result: PlanQueryProfileResult) -> PlanQueryProfileResult:
    query_type = str(result.queryType or "none").strip()
    if query_type not in set(QUERY_TYPE_VALUES):
        query_type = "none"
    scope_anchor = str(result.scopeAnchor or "general").strip()
    if scope_anchor not in set(SCOPE_ANCHOR_VALUES):
        scope_anchor = "general"
    side_effect = str(result.sideEffect or "none").strip()
    if side_effect not in set(SIDE_EFFECT_VALUES):
        side_effect = "none"
    dimensions = [item for item in result.dimensions if item in set(DIMENSION_VALUES)]
    pending_reference_type = str(result.pendingReferenceType or "none").strip()
    if pending_reference_type not in set(PENDING_REFERENCE_TYPE_VALUES):
        pending_reference_type = "none"
    return PlanQueryProfileResult(
        queryType=query_type,
        scopeAnchor=scope_anchor,
        sideEffect=side_effect,
        dimensions=dimensions,
        condition=dict(result.condition or {}),
        filters=dict(result.filters or {}),
        projection=dict(result.projection or {}),
        replyFocus=result.replyFocus,
        pendingReferenceType=pending_reference_type,
        confidence=_coerce_confidence(result.confidence),
        reason=result.reason,
    )


async def classify_plan_query_profile(
    latest_utterance: str,
    *,
    payload: dict[str, Any] | None = None,
) -> PlanQueryProfileResult:
    text = str(latest_utterance or "").strip()
    if not text:
        return PlanQueryProfileResult()
    agent = Agent(
        model=_get_plan_query_profile_client().model,
        output_type=str,
        instructions=_build_prompt(text, payload),
    )
    result = await agent.run("请输出 PlanQueryProfile JSON", model_settings={"temperature": 0})
    parsed = parse_extraction_json(result.output, PlanQueryProfileResult)
    normalized = _normalize_plan_query_profile(parsed)
    logger.info(
        "classify_plan_query_profile: query_type=%s side_effect=%s dimensions=%s confidence=%s",
        normalized.queryType,
        normalized.sideEffect,
        normalized.dimensions,
        normalized.confidence,
    )
    return normalized
