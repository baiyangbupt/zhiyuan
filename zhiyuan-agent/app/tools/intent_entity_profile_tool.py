"""3.2.0 intent entity profile extraction node.

This node is used by model-node benchmark and future 3.2.0 hard-cut work. It
emits the target profile schema directly instead of adapting legacy intent
extractor fields into the new schema.
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

_intent_entity_profile_client: LLMClient | None = None


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


class IntentEntityProfileResult(BaseModel):
    entityType: str = ""
    majorValues: list[str] = Field(default_factory=list)
    regionValues: list[str] = Field(default_factory=list)
    schools: list[str] = Field(default_factory=list)
    preferenceStrength: dict[str, list[str]] = Field(default_factory=dict)
    entityPolaritySpans: list[dict[str, Any]] = Field(default_factory=list)
    admissionPath: str | None = None
    confidence: float = 0.0
    reason: str = ""

    @field_validator("majorValues", "regionValues", "schools", mode="before")
    @classmethod
    def _coerce_list_fields(cls, value: Any) -> list[str]:
        return _normalize_text_list(value)

    @field_validator("preferenceStrength", mode="before")
    @classmethod
    def _coerce_preference_strength(cls, value: Any) -> dict[str, list[str]]:
        if not isinstance(value, dict):
            return {}
        result: dict[str, list[str]] = {}
        for key, raw_values in value.items():
            text = str(key or "").strip()
            if not text:
                continue
            values = _normalize_text_list(raw_values)
            if values:
                result[text] = values
        return result

    @field_validator("entityPolaritySpans", mode="before")
    @classmethod
    def _coerce_entity_polarity_spans(cls, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        result: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, dict):
                result.append(dict(item))
        return result

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, value: Any) -> float:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"high", "高", "高置信"}:
                return 0.9
            if normalized in {"medium", "中", "中等", "中置信"}:
                return 0.65
            if normalized in {"low", "低", "低置信"}:
                return 0.35
        return float(value or 0.0)

    @field_validator("admissionPath", mode="before")
    @classmethod
    def _coerce_optional_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, list):
            values = _normalize_text_list(value)
            return values[0] if values else None
        text = str(value or "").strip()
        return text or None


def _get_intent_entity_profile_client() -> LLMClient:
    global _intent_entity_profile_client
    if _intent_entity_profile_client is None:
        _intent_entity_profile_client = LLMClient(LLMConfig())
    return _intent_entity_profile_client


def _build_prompt(latest_utterance: str, context: dict[str, Any] | None = None) -> str:
    return json.dumps(
        {
            "latestUserText": latest_utterance,
            "context": context or {},
            "task": (
                "抽取高考志愿对话里的实体、极性、强度和特殊录取路径，输出 3.2.0 profile schema。"
                "不要输出 legacy constraintIntentType，也不要把旧字段改名当作新字段。"
            ),
            "schemaRules": [
                "entityType 取 major、school、region、mixed、none。",
                "majorValues 只放专业/专业类/专业门类；regionValues 只放地域词；schools 只放院校实体。",
                "preferenceStrength 必须是“强度 -> 实体列表”的对象，禁止输出“实体 -> 强度列表”。",
                "正确示例：{\"primary\":[\"网络与新媒体\"],\"acceptable\":[\"跨境电子商务\"]}；错误示例：{\"网络与新媒体\":[\"primary\"]}。",
                "preferenceStrength key 只能用 primary、preferred、acceptable、must_have、only_keep、exclude_soft、exclude_hard。",
                "primary 只表示明确优先、首选、重点或最想要；preferred 表示普通偏好、感兴趣、加到意向或加入后续参考；acceptable 表示也可以、也可以考虑、也能接受、作为备选可以；must_have 表示至少要有；only_keep 表示只保留；exclude_hard 表示明确不要/排除。",
                "“加到意向/加意向/记到意向”本身不是 primary，除非同一句还明确说优先、首选、重点。",
                "“也可以考虑/也可以/也能接受”本身不是 preferred，必须归到 acceptable。",
                "entityPolaritySpans 每项包含 entity、entityType、polarity、strength；polarity 只能是 positive 或 negative。",
                "entityPolaritySpans 中的 entity 应使用规范实体名；例如“跨境电商”写成“跨境电子商务”，“口腔”写成“口腔医学”。",
                "admissionPath 只在强基、综评、专项等特殊路径明确出现时填写，例如强基填 strongbase。",
                "不要把地域词误识别为专业，例如“城市优先长三角”里的实体是 region，不是城市管理专业。",
            ],
            "returnJson": {
                "entityType": "major|school|region|mixed|none",
                "majorValues": [],
                "regionValues": [],
                "schools": [],
                "preferenceStrength": {},
                "entityPolaritySpans": [],
                "admissionPath": None,
                "confidence": 0.0,
                "reason": "",
            },
        },
        ensure_ascii=False,
    )


def _normalize_entity_profile(result: IntentEntityProfileResult) -> IntentEntityProfileResult:
    entity_type = str(result.entityType or "").strip()
    if entity_type not in {"major", "school", "region", "mixed", "none"}:
        if result.majorValues and (result.regionValues or result.schools):
            entity_type = "mixed"
        elif result.majorValues:
            entity_type = "major"
        elif result.regionValues:
            entity_type = "region"
        elif result.schools:
            entity_type = "school"
        else:
            entity_type = "none"
    confidence = max(0.0, min(1.0, float(result.confidence or 0.0)))
    return IntentEntityProfileResult(
        entityType=entity_type,
        majorValues=result.majorValues,
        regionValues=result.regionValues,
        schools=result.schools,
        preferenceStrength=result.preferenceStrength,
        entityPolaritySpans=result.entityPolaritySpans,
        admissionPath=str(result.admissionPath or "").strip() or None,
        confidence=confidence,
        reason=result.reason,
    )


async def extract_intent_entity_profile(
    latest_utterance: str,
    *,
    context: dict[str, Any] | None = None,
) -> IntentEntityProfileResult:
    text = str(latest_utterance or "").strip()
    if not text:
        return IntentEntityProfileResult(entityType="none")
    agent = Agent(
        model=_get_intent_entity_profile_client().model,
        output_type=str,
        instructions=_build_prompt(text, context),
    )
    result = await agent.run("请按 3.2.0 profile schema 抽取实体意向", model_settings={"temperature": 0})
    parsed = parse_extraction_json(result.output, IntentEntityProfileResult)
    normalized = _normalize_entity_profile(parsed)
    logger.info(
        "extract_intent_entity_profile: entity_type=%s majors=%s regions=%s schools=%s admission_path=%s confidence=%s",
        normalized.entityType,
        normalized.majorValues,
        normalized.regionValues,
        normalized.schools,
        normalized.admissionPath,
        normalized.confidence,
    )
    return normalized
