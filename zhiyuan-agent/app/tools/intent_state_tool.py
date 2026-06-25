"""Intent state tools.

Core intent-state capabilities for volunteer planning.
Responsible for intent fact extraction, analysis facts, and state execution.
"""

from __future__ import annotations

import json
import logging
import re
import time
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel, Field, field_validator
from pydantic_ai import Agent
from pydantic_ai import RunContext

from app.agent.context import RequestContext, has_pending_intent_confirmation, resolve_pending_confirmation
from app.config import LLMConfig
from app.domain.career_slots import (
    CAREER_FURTHER_STUDY,
    CAREER_LABEL_MAP,
    CAREER_STABLE_EMPLOYMENT,
    CAREER_SYSTEM_PUBLIC_SERVICE,
    is_career_slot,
    to_career_label,
    to_career_labels,
)
from app.domain.major_entity_resolver import (
    append_major_mentions_to_payload,
    dedupe_major_intent_payload_across_levels,
    major_parent_mappings_for_batch,
    major_name_sets_for_batch,
    normalize_major_intent_payload_by_catalog,
    refine_major_intent_payload_by_explicit_mentions,
    resolve_major_mentions_from_text,
)
from app.domain.region_entity_resolver import (
    REGION_AREA_PROVINCES,
    compact_region_text,
    contains_concrete_region_mention,
    resolve_region_entity,
)
from app.services.profile_manager import ProfileManager, _normalize_batch
from app.tools.intent_relation_tool import (
    build_impact_preview_from_analysis as _build_impact_preview_from_analysis,
    build_plan_relation_analysis as _build_plan_relation_analysis,
    enrich_plan_relation_analysis_from_state as _enrich_plan_relation_analysis_from_state,
)
from app.tools.intent_response_tool import (
    IntentAnalysisPayload,
    IntentPreviewItem,
    IntentStateUpdateResult,
    render_intent_analysis_payload,
    render_intent_state_update,
    serialize_intent_analysis_payload,
    serialize_intent_state_update_result,
)
from app.tools.extraction_json import parse_extraction_json
from app.llm.client import LLMClient
from app.util.code_enrichment import (
    add_codes_to_profile,
    get_major_codes,
    get_major_codes_async,
    resolve_major_names_async,
)
from app.util.internal_client import (
    get_planning_state,
    mark_planning_intent_change_stale,
    get_message_by_id,
    query_planning_candidate_pool,
    save_intent_change_cache,
    update_planning_constraint_state,
    update_planning_physical_constraints,
    update_planning_latent_profile,
    update_message,
)
from app.util.structured_log import log_event

logger = logging.getLogger(__name__)

INTENT_SELECT_INPUT_TYPE = "intentSelect"
INTENT_CONFIRM_POPUP_TYPE = "intentConfirmPopup"
INTEREST_ANALYSIS_POPUP_TYPE = "interestAnalysisPopup"
INTENT_MODE_PREFERENCE = "preference"
INTENT_MODE_CONSTRAINT = "constraint"
CONSTRAINT_INTENT_DEFAULT = "default"
CONSTRAINT_INTENT_ONLY_KEEP = "only_keep"
CONSTRAINT_INTENT_MUST_HAVE = "must_have"
ANALYSIS_STAGE_INTEREST = "interest"
ANALYSIS_STAGE_CONFIRMED = "confirmed"
_intent_side_effect_llm_client: LLMClient | None = None
_intent_side_effect_agent: Agent[None, str] | None = None


class IntentSideEffectDecision(BaseModel):
    decision: str = Field(default="intent_preview")
    confidence: float = Field(default=0.0)
    constraintIntentType: str = Field(default=CONSTRAINT_INTENT_DEFAULT)
    preferenceStrength: dict[str, list[str]] = Field(default_factory=dict)
    preferenceScope: str | None = None
    entityPolaritySpans: list[dict[str, Any]] = Field(default_factory=list)
    admissionPath: str | None = None
    reason: str = ""

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
        return value

    @field_validator("preferenceStrength", mode="before")
    @classmethod
    def _coerce_preference_strength(cls, value: Any) -> dict[str, list[str]]:
        if not isinstance(value, dict):
            return {}
        result: dict[str, list[str]] = {}
        for key, raw_values in value.items():
            name = str(key or "").strip()
            if not name:
                continue
            values = _as_string_list(raw_values)
            deduped: list[str] = []
            for item in values:
                text = str(item or "").strip()
                if text and text not in deduped:
                    deduped.append(text)
            if deduped:
                result[name] = deduped
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

    @field_validator("preferenceScope", "admissionPath", mode="before")
    @classmethod
    def _coerce_optional_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, list):
            values = _as_string_list(value)
            return values[0] if values else None
        text = str(value or "").strip()
        return text or None


def _get_intent_side_effect_llm_client() -> LLMClient:
    global _intent_side_effect_llm_client
    if _intent_side_effect_llm_client is None:
        _intent_side_effect_llm_client = LLMClient(LLMConfig())
    return _intent_side_effect_llm_client


def _get_intent_side_effect_agent() -> Agent[None, str]:
    global _intent_side_effect_agent
    if _intent_side_effect_agent is None:
        _intent_side_effect_agent = Agent(
            model=_get_intent_side_effect_llm_client().model,
            output_type=str,
            instructions=(
                "你是高考志愿对话里的副作用语义仲裁器。"
                "只判断当前用户是不是在要求系统把偏好/要求写入待确认状态。"
                "不要根据“能不能、算不算、是不是、要不要”等虚词做决定；同一个虚词在不同语境下可能是分析，也可能是偏好。"
                "判断维度：1 用户期望的结果是解释边界/利弊/适配，还是让系统以后记住；"
                "2 用户是否要求改变候选、方案或后续推荐口径；"
                "3 当前结构化意向是否只是为了回答分类归属、风险边界或取舍问题；"
                "4 如果直接出现待采纳内容，用户是否会误以为系统已经替他做了结论。"
                "如果用户已经表达若干偏好/排除想法，但本轮明确要先看影响、边界、利弊、风险或承接情况，"
                "应判为 mixed_answer_then_ask 或 analysis_only；先回答影响，再自然询问是否需要记录，不能直接出待采纳内容。"
                "如果用户是在描述自己的兴趣画像、多个可选方向、职业期待或工作特征，例如高薪、稳定、少沟通、读研、体制内等，"
                "且没有明确说以后按此筛、记下来、只保留、必须有或排除当前方案，默认先判为 analysis_only 或 mixed_answer_then_ask；"
                "这类话术通常需要先做适配分析和取舍澄清，不能把所有兴趣陈述都当作写入请求。"
                "如果用户是在要求系统以后对某个具体专业、院校、地域或方向多看、多关注、优先看、后续多给机会，"
                "这属于改变后续推荐口径，应判为 intent_preview；不要因为句子里有征询语气就降级。"
                "同时给出 3.2.0 profile 字段：preferenceStrength、preferenceScope、entityPolaritySpans、admissionPath。"
                "preferenceStrength 必须是“强度 -> 实体列表”的对象，禁止输出“实体 -> 强度列表”。"
                "正确示例：{\"primary\":[\"网络与新媒体\"],\"acceptable\":[\"跨境电子商务\"]}；"
                "错误示例：{\"网络与新媒体\":[\"primary\"],\"跨境电子商务\":[\"acceptable\"]}。"
                "preferenceStrength 的 key 只能用 primary、preferred、acceptable、must_have、only_keep、exclude_soft、exclude_hard；"
                "primary 只表示用户明确说优先、首选、重点、最想要；preferred 表示普通偏好、感兴趣、加到意向或加入后续参考；"
                "acceptable 表示也可以、也可以考虑、也能接受、作为备选可以，must_have 表示方案里至少要有，"
                "only_keep 表示只保留/限定范围，exclude_hard 表示明确不要，exclude_soft 表示不太倾向。"
                "“加到意向/加意向/记到意向”本身不是 primary，除非同一句还明确说优先、首选、重点。"
                "“也可以考虑/也可以/也能接受”本身不是 preferred，必须归到 acceptable。"
                "preferenceScope 只在用户把偏好限定到冲/稳/保/保底等方案层级时填写。"
                "entityPolaritySpans 记录用户原文里的实体极性，元素包含 entity、entityType、polarity、strength；"
                "entityPolaritySpans 中的 entity 应使用规范实体名；例如“跨境电商”写成“跨境电子商务”，“口腔”写成“口腔医学”。"
                "输入里的 structuredIntents 是本轮已经抽取出的实体候选；当 decision=intent_preview 时，"
                "必须把 positiveMajors/positiveSchools/positive region/career 等正向实体保留到 preferenceStrength 中，"
                "没有更强语义时放 preferred，不要只输出抽象类型词而丢掉这些实体。"
                "如果 structuredIntents.school.positiveSchools 非空，这些具体院校名必须原样进入 preferenceStrength.preferred；"
                "不能解释为“没有更强语义支撑所以不输出”，也不能用“公办/民办”等抽象性质替代具体院校。"
                "例如 structuredIntents.school.positiveSchools=[\"合肥工业大学\",\"南京邮电大学\"] 且用户说“保底要公办不要民办”，"
                "应输出 preferenceStrength.preferred=[\"合肥工业大学\",\"南京邮电大学\"]，preferenceStrength.exclude_hard=[\"民办\"]，preferenceScope=\"保底\"。"
                "该例中禁止输出 preferenceStrength.only_keep=[\"公办\"]，也禁止 constraintIntentType=only_keep；"
                "只有用户明确说“只要公办/只保留公办/仅限公办/其他不要”时，才可把公办归为 only_keep。"
                "但“保底要公办不要民办”这类已经是在要求改变后续推荐口径，decision 必须是 intent_preview；"
                "不要因为公办是否 only_keep 存在边界就降级为 mixed_answer_then_ask 或 analysis_only。"
                "只有用户问“公办和民办怎么取舍/要不要公办/只要公办会怎样”等分析问题时，才先解释或追问。"
                "公办/民办这类院校性质可以作为 value 输出，但不要把 key 写成 schoolNature、school_type，也不要把“民办”改写成“民办高校”。"
                "admissionPath 只在强基、综评、专项等特殊录取路径明确出现时填写。"
                "不要只输出旧字段替代这些字段，不能用 constraintIntentType 代替 preferenceStrength。"
                "为了当前运行兼容，仍同时给出 constraintIntentType：only_keep 表示只保留/只要/限定在某个范围，其他不要；"
                "must_have 表示方案里至少要有这个方向，但其他方向可以保留；"
                "default 表示普通偏好或排除，不要猜测。只有用户语义明确时才输出 only_keep 或 must_have。"
                "decision 只能是 intent_preview、analysis_only、mixed_answer_then_ask。"
                "intent_preview 表示可以生成待采纳内容；analysis_only 表示只应回答分析；"
                "mixed_answer_then_ask 表示先解释边界，再自然询问是否需要记录，不能直接写待确认。"
                "输出 JSON：decision, confidence, constraintIntentType, preferenceStrength, preferenceScope, entityPolaritySpans, admissionPath, reason。"
            ),
        )
    return _intent_side_effect_agent


def _normalize_intent_side_effect_decision(decision: IntentSideEffectDecision) -> IntentSideEffectDecision:
    normalized = str(decision.decision or "").strip()
    if normalized not in {"intent_preview", "analysis_only", "mixed_answer_then_ask"}:
        normalized = "intent_preview"
    confidence = max(0.0, min(1.0, float(decision.confidence or 0.0)))
    return IntentSideEffectDecision(
        decision=normalized,
        confidence=confidence,
        constraintIntentType=_normalize_constraint_intent_type(decision.constraintIntentType),
        preferenceStrength=decision.preferenceStrength,
        preferenceScope=str(decision.preferenceScope or "").strip() or None,
        entityPolaritySpans=decision.entityPolaritySpans,
        admissionPath=str(decision.admissionPath or "").strip() or None,
        reason=decision.reason,
    )
_INTENT_CONFIRM_UTTERANCE_PHRASES = {
    "确认",
    "确定",
    "可以",
    "好",
    "好的",
    "行",
    "没问题",
    "就按这个来",
    "按这个来",
    "就这样",
    "就这样吧",
    "确认这个偏好",
    "确认偏好",
    "确认这个要求",
    "确认要求",
    "作为后续偏好",
    "作为后续参考",
    "就按这个方向来",
    "按这个方向来",
}

# ---------------------------------------------------------------------------
# Preview generation helpers
# ---------------------------------------------------------------------------

def _diff_list(existing: list[str] | None, new: list[str]) -> tuple[list[str], list[str]]:
    """Split new values into (truly_new, already_existing)."""
    existing_set = set(existing or [])
    truly_new = [v for v in new if v not in existing_set]
    already = [v for v in new if v in existing_set]
    return truly_new, already


def _build_cache_data(
    major_intents: dict | None,
    school_intents: dict | None,
    city_intents: dict | None,
    career_intents: dict | None = None,
    intent_mode: str = INTENT_MODE_PREFERENCE,
    constraint_intent_type: str | None = None,
) -> dict[str, Any]:
    """Build the cache payload from intent dicts."""
    cache: dict[str, Any] = {}
    if major_intents:
        cache["major_intents"] = major_intents
    if school_intents:
        cache["school_intents"] = school_intents
    if city_intents:
        cache["city_intents"] = city_intents
    if career_intents:
        cache["career_intents"] = career_intents
    cache["intent_mode"] = intent_mode
    normalized_constraint_type = _normalize_constraint_intent_type(constraint_intent_type)
    if normalized_constraint_type != CONSTRAINT_INTENT_DEFAULT:
        cache["constraint_intent_type"] = normalized_constraint_type
    return cache


def _collect_intent_labels(
    major_intents: dict | None,
    school_intents: dict | None,
    city_intents: dict | None,
    career_intents: dict | None = None,
) -> dict[str, list[str]]:
    labels: dict[str, list[str]] = {
        "positive": [],
        "negative": [],
    }

    def _extend(values: list[str] | None, negative: bool = False):
        if not values:
            return
        bucket = "negative" if negative else "positive"
        for value in values:
            if value and value not in labels[bucket]:
                labels[bucket].append(value)

    if major_intents:
        _extend(major_intents.get("level1"))
        _extend(major_intents.get("level2"))
        _extend(major_intents.get("level3"))
        _extend(major_intents.get("negative_level1"), negative=True)
        _extend(major_intents.get("negative_level2"), negative=True)
        _extend(major_intents.get("negative_level3"), negative=True)
    if school_intents:
        _extend(school_intents.get("colleges"))
        _extend(school_intents.get("negative_colleges"), negative=True)
    if city_intents:
        _extend(city_intents.get("province"))
        _extend(city_intents.get("city"))
        _extend(city_intents.get("area"))
        _extend(city_intents.get("negative_province"), negative=True)
        _extend(city_intents.get("negative_city"), negative=True)
        _extend(city_intents.get("negative_area"), negative=True)
    if career_intents:
        _extend(to_career_labels(career_intents.get("positive")))
        _extend(to_career_labels(career_intents.get("negative")), negative=True)

    return labels


def _merge_list(existing: list[str] | None, new: list[str]) -> list[str]:
    """Merge new values into existing list, preserving order and deduplicating."""
    result = list(existing or [])
    existing_set = set(result)
    for v in new:
        if v not in existing_set:
            result.append(v)
            existing_set.add(v)
    return result


def _normalize_constraint_intent_type(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {CONSTRAINT_INTENT_ONLY_KEEP, "only", "keep_only", "exclusive"}:
        return CONSTRAINT_INTENT_ONLY_KEEP
    if normalized in {CONSTRAINT_INTENT_MUST_HAVE, "required_presence", "at_least_one", "include_at_least_one"}:
        return CONSTRAINT_INTENT_MUST_HAVE
    return CONSTRAINT_INTENT_DEFAULT


def _has_positive_values_in_payload(merged: dict[str, Any] | None) -> bool:
    if not isinstance(merged, dict):
        return False
    return _has_positive_intents(
        merged.get("major_intents") if isinstance(merged.get("major_intents"), dict) else None,
        merged.get("school_intents") if isinstance(merged.get("school_intents"), dict) else None,
        merged.get("city_intents") if isinstance(merged.get("city_intents"), dict) else None,
        merged.get("career_intents") if isinstance(merged.get("career_intents"), dict) else None,
    )


def _normalize_constraint_type_for_payload(value: str | None, merged: dict[str, Any] | None) -> str:
    """Positive-only constraint types should not leak onto pure exclusion payloads."""
    normalized = _normalize_constraint_intent_type(value)
    if normalized in {CONSTRAINT_INTENT_ONLY_KEEP, CONSTRAINT_INTENT_MUST_HAVE} and not _has_positive_values_in_payload(merged):
        return CONSTRAINT_INTENT_DEFAULT
    return normalized


def _payload_is_negative_only_region(merged: dict[str, Any] | None) -> bool:
    if not isinstance(merged, dict):
        return False
    major = merged.get("major_intents") if isinstance(merged.get("major_intents"), dict) else None
    school = merged.get("school_intents") if isinstance(merged.get("school_intents"), dict) else None
    city = merged.get("city_intents") if isinstance(merged.get("city_intents"), dict) else None
    career = merged.get("career_intents") if isinstance(merged.get("career_intents"), dict) else None
    return bool(city) and _has_negative_intents(None, None, city, None) and not (
        _has_positive_intents(major, school, city, career)
        or _has_negative_intents(major, school, None, career)
    )


def _coerce_intent_mode_for_constraint_type(intent_mode: str, constraint_intent_type: str) -> str:
    if constraint_intent_type in {CONSTRAINT_INTENT_ONLY_KEEP, CONSTRAINT_INTENT_MUST_HAVE}:
        return INTENT_MODE_CONSTRAINT
    return intent_mode


def _constraint_type_from_semantic_decision(
    semantic_decision: IntentSideEffectDecision | None,
    *,
    merged: dict[str, Any] | None,
    allow_negative_only_region: bool = False,
) -> str:
    """Use the semantic arbiter's structured constraint type only when confident."""
    if semantic_decision is None:
        return CONSTRAINT_INTENT_DEFAULT
    if semantic_decision.decision != "intent_preview" or semantic_decision.confidence < 0.7:
        return CONSTRAINT_INTENT_DEFAULT
    normalized = _normalize_constraint_intent_type(semantic_decision.constraintIntentType)
    if (
        normalized in {CONSTRAINT_INTENT_ONLY_KEEP, CONSTRAINT_INTENT_MUST_HAVE}
        and allow_negative_only_region
        and _payload_is_negative_only_region(merged)
    ):
        return normalized
    return _normalize_constraint_type_for_payload(normalized, merged)


def _missing_positive_constraint_message(constraint_intent_type: str) -> str:
    if constraint_intent_type == CONSTRAINT_INTENT_MUST_HAVE:
        return "我理解你是想让方案里至少保留某个方向，但这次没有稳定识别出具体要保留的专业、院校或地域。请直接补充要保留的范围，我再给你列出可采纳内容。"
    return "我理解你是想把后续范围收紧，但这次没有稳定识别出具体要保留的专业、院校或地域。请直接补充要保留的范围，我再给你列出可采纳内容。"


async def _recover_positive_scope_for_positive_constraint(
    ctx: RunContext[RequestContext],
    *,
    major_intents: dict | None,
    school_intents: dict | None,
    city_intents: dict | None,
    career_intents: dict | None,
    recovery_scope: str | None,
    batch: str,
    latest_utterance: str,
) -> tuple[dict | None, dict | None, dict | None, dict | None]:
    """Recover missing positive scope for only-keep / must-have constraints.

    The tool model can occasionally pass only the negative half of a positive
    constraint, e.g. "北方先别考虑" for "只去南方". Reuse the existing semantic
    extractors once and merge only positive fields so we do not invent broad
    exclusion complements.
    """

    recovered_major, recovered_school, recovered_city, recovered_career = await _recover_intents_from_context(
        ctx,
        recovery_scope=recovery_scope,
    )
    if recovered_major:
        positive_major = _normalize_intent_payload(
            recovered_major,
            allowed_keys=_MAJOR_POSITIVE_KEYS,
        )
        if positive_major:
            major_intents = _merge_major_intent_payloads(major_intents, positive_major)
            major_intents = await _normalize_major_intent_names_for_batch(major_intents, batch)
            major_intents = _refine_major_intents_by_explicit_mentions(
                major_intents,
                latest_utterance=latest_utterance,
                batch=batch,
            )
    if recovered_school:
        positive_school = _normalize_intent_payload(
            recovered_school,
            allowed_keys=_SCHOOL_POSITIVE_KEYS,
        )
        if positive_school:
            school_intents = _merge_intent_payload_dict(school_intents, positive_school)
    if recovered_city:
        positive_city = _normalize_intent_payload(
            recovered_city,
            allowed_keys=_CITY_POSITIVE_KEYS,
        )
        if positive_city:
            city_intents = _merge_city_intent_payloads(city_intents, positive_city)
    if recovered_career:
        positive_career = _normalize_intent_payload(
            recovered_career,
            allowed_keys=_CAREER_POSITIVE_KEYS,
        )
        if positive_career:
            career_intents = _merge_intent_payload_dict(career_intents, positive_career)
    return major_intents, school_intents, city_intents, career_intents


def _latest_utterance_has_positive_scope_signal(text: str, recovery_scope: str | None) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    if not compact:
        return False
    positive_markers = (
        "只去",
        "只考虑",
        "只看",
        "只要",
        "就想去",
        "想去",
        "希望去",
        "考虑",
        "接受",
        "优先",
        "保留",
        "要",
        "放",
        "看",
    )
    if not any(marker in compact for marker in positive_markers):
        return False
    if (recovery_scope or "").strip().lower() in {"region", "city"}:
        return contains_concrete_region_mention(compact)
    return True


def _prune_generated_negative_complements_for_only_keep(
    payload: dict[str, Any] | None,
    *,
    latest_utterance: str,
    batch: str,
) -> dict[str, Any] | None:
    """Remove model-invented broad exclusions from only-keep intent payloads.

    "只要电气和气象，其他方向都不要" means the positive scope is exclusive.
    The model sometimes expands "其他方向" into every other discipline, which is
    both noisy and can contradict the positive scope. Keep only negative major
    values that are explicitly mentioned in the user utterance, such as "不考虑工科".
    """

    if not isinstance(payload, dict) or not payload:
        return payload
    if not _has_positive_major_values(payload) or not _has_negative_major_values(payload):
        return payload

    explicit_mentions: dict[str, set[str]] = {"level1": set(), "level2": set(), "level3": set()}
    for mention in resolve_major_mentions_from_text(latest_utterance, batch):
        level = str(mention.level or "")
        name = str(mention.canonical_name or "").strip()
        if level in explicit_mentions and name:
            explicit_mentions[level].add(name)
    explicit_negative_keys = {
        "negative_level1": explicit_mentions["level1"],
        "negative_level2": explicit_mentions["level2"],
        "negative_level3": explicit_mentions["level3"],
    }
    if not any(explicit_negative_keys.values()):
        return {key: value for key, value in payload.items() if not str(key).startswith("negative_")}

    pruned: dict[str, Any] = {}
    changed = False
    for key, values in payload.items():
        if key not in explicit_negative_keys:
            pruned[key] = values
            continue
        kept = [value for value in _as_string_list(values) if value in explicit_negative_keys[key]]
        if kept:
            pruned[key] = kept
        if kept != _as_string_list(values):
            changed = True
    if changed:
        logger.info(
            "Pruned generated only-keep negative major complement: latest=%s before=%s after=%s",
            latest_utterance,
            payload,
            pruned,
    )
    return pruned or None


def _preserve_only_keep_positive_major_scope(
    payload: dict[str, Any] | None,
    *,
    latest_utterance: str,
    batch: str,
) -> dict[str, Any] | None:
    """Recover explicit positive major targets before pruning only-keep complements.

    The model may understand the utterance as only-keep but pass only the
    generated "other directions" exclusions to the tool. Once semantic
    arbitration confirms only-keep, the source of truth for target majors is the
    catalog-backed entity resolver over the current utterance, not an inferred
    broad negative complement.
    """

    normalized = _normalize_intent_payload(
        payload,
        allowed_keys=_MAJOR_POSITIVE_KEYS + _MAJOR_NEGATIVE_KEYS,
    ) or {}
    explicit_positive = _only_keep_positive_major_targets_from_latest_utterance(
        latest_utterance,
        batch,
    )
    if explicit_positive:
        normalized = _merge_major_intent_payloads(normalized, explicit_positive) or normalized
    normalized = _prune_generated_negative_complements_for_only_keep(
        normalized,
        latest_utterance=latest_utterance,
        batch=batch,
    )
    normalized = _remove_positive_major_targets_excluded_by_negative_scope(
        normalized,
        batch=batch,
    )
    return normalized


def _only_keep_positive_major_targets_from_latest_utterance(
    latest_utterance: str,
    batch: str,
) -> dict[str, list[str]]:
    local_payload = _recover_polarity_major_intent_locally_from_latest_utterance(
        latest_utterance,
        batch,
    ) or {}
    local_positive = {
        key: _as_string_list(local_payload.get(key))
        for key in _MAJOR_POSITIVE_KEYS
        if _as_string_list(local_payload.get(key))
    }
    if local_positive:
        return local_positive

    local_negative = {
        key: set(_as_string_list(local_payload.get(key)))
        for key in _MAJOR_NEGATIVE_KEYS
    }
    explicit_positive: dict[str, list[str]] = {}
    for mention in resolve_major_mentions_from_text(latest_utterance, batch):
        level = str(mention.level or "")
        name = str(mention.canonical_name or "").strip()
        if level not in _MAJOR_POSITIVE_KEYS or not name:
            continue
        negative_key = f"negative_{level}"
        if name in local_negative.get(negative_key, set()):
            continue
        bucket = explicit_positive.setdefault(level, [])
        if name not in bucket:
            bucket.append(name)
    return explicit_positive


def _recover_only_keep_positive_scope_from_generated_complement(
    payload: dict[str, Any] | None,
    *,
    latest_utterance: str,
    batch: str,
) -> dict[str, Any] | None:
    """Recover only-keep targets when the extractor only returned a broad complement.

    This handles the structural failure mode where "只要 A 和 B，其他方向不要"
    becomes "exclude every discipline" with no positive target. We only recover
    when the negative side is a broad discipline-level complement and the catalog
    resolver finds explicit major targets in the latest utterance.
    """

    normalized = _normalize_intent_payload(
        payload,
        allowed_keys=_MAJOR_POSITIVE_KEYS + _MAJOR_NEGATIVE_KEYS,
    ) or {}
    if not normalized or _has_positive_major_values(normalized):
        return payload
    negative_level1 = _as_string_list(normalized.get("negative_level1"))
    if len(negative_level1) < 6:
        return payload

    explicit_positive: dict[str, list[str]] = {}
    for mention in resolve_major_mentions_from_text(latest_utterance, batch):
        level = str(mention.level or "")
        name = str(mention.canonical_name or "").strip()
        if level not in _MAJOR_POSITIVE_KEYS or not name:
            continue
        bucket = explicit_positive.setdefault(level, [])
        if name not in bucket:
            bucket.append(name)
    if not explicit_positive:
        return payload

    recovered = _merge_major_intent_payloads(normalized, explicit_positive) or normalized
    recovered = _prune_generated_negative_complements_for_only_keep(
        recovered,
        latest_utterance=latest_utterance,
        batch=batch,
    )
    if recovered != payload:
        logger.info(
            "Recovered only-keep positive major targets from broad negative complement: latest=%s before=%s after=%s",
            latest_utterance,
            payload,
            recovered,
        )
    return recovered


def _major_display_name_from_latest_utterance(
    *,
    level: str,
    name: str,
    latest_utterance: str,
    batch: str,
) -> str:
    for mention in resolve_major_mentions_from_text(latest_utterance, batch):
        if str(mention.level or "") != level:
            continue
        if str(mention.canonical_name or "").strip() != name:
            continue
        raw_text = str(getattr(mention, "raw_text", "") or "").strip()
        if raw_text and raw_text != name:
            return f"{raw_text}（{name}）"
    return name


def _positive_major_covered_by_negative_scope(
    *,
    level: str,
    name: str,
    negative_level1: set[str],
    negative_level2: set[str],
    negative_level3: set[str],
    level2_to_level1: dict[str, str],
    level3_to_level2: dict[str, str],
) -> bool:
    if level == "level1":
        if name in negative_level1:
            return True
        for level2 in negative_level2:
            if level2_to_level1.get(level2) == name:
                return True
        for level3 in negative_level3:
            parent_level2 = level3_to_level2.get(level3)
            if level2_to_level1.get(parent_level2 or "") == name:
                return True
        return False
    if level == "level2":
        if name in negative_level2:
            return True
        parent_level1 = level2_to_level1.get(name)
        if parent_level1 and parent_level1 in negative_level1:
            return True
        for level3 in negative_level3:
            if level3_to_level2.get(level3) == name:
                return True
        return False
    if level == "level3":
        if name in negative_level3:
            return True
        parent_level2 = level3_to_level2.get(name)
        parent_level1 = level2_to_level1.get(parent_level2 or "")
        return bool(
            (parent_level2 and parent_level2 in negative_level2)
            or (parent_level1 and parent_level1 in negative_level1)
        )
    return False


def _positive_major_excluded_by_negative_scope(
    *,
    level: str,
    name: str,
    negative_level1: set[str],
    negative_level2: set[str],
    negative_level3: set[str],
    level2_to_level1: dict[str, str],
    level3_to_level2: dict[str, str],
) -> bool:
    if level == "level1":
        return name in negative_level1
    if level == "level2":
        parent_level1 = level2_to_level1.get(name)
        return name in negative_level2 or bool(parent_level1 and parent_level1 in negative_level1)
    if level == "level3":
        parent_level2 = level3_to_level2.get(name)
        parent_level1 = level2_to_level1.get(parent_level2 or "")
        return bool(
            name in negative_level3
            or (parent_level2 and parent_level2 in negative_level2)
            or (parent_level1 and parent_level1 in negative_level1)
        )
    return False


def _remove_positive_major_targets_excluded_by_negative_scope(
    payload: dict[str, Any] | None,
    *,
    batch: str,
) -> dict[str, Any] | None:
    """Keep target scopes and excluded scopes structurally consistent.

    For only-keep/must-have plan goals, positive targets must not include an
    entity that is also excluded in the same structured payload. Equal or broader
    negative scopes win; narrower negative child scopes do not erase a broader
    positive target such as "只考虑医学，但护理不要".
    """

    if not isinstance(payload, dict) or not payload:
        return payload
    if not _has_positive_major_values(payload) or not _has_negative_major_values(payload):
        return payload

    mappings = major_parent_mappings_for_batch(batch)
    level2_to_level1 = mappings.get("level2_to_level1", {})
    level3_to_level2 = mappings.get("level3_to_level2", {})
    negative_level1 = set(_as_string_list(payload.get("negative_level1")))
    negative_level2 = set(_as_string_list(payload.get("negative_level2")))
    negative_level3 = set(_as_string_list(payload.get("negative_level3")))

    cleaned: dict[str, Any] = {}
    changed = False
    for key, values in payload.items():
        if key not in _MAJOR_POSITIVE_KEYS:
            cleaned[key] = values
            continue
        kept: list[str] = []
        for name in _as_string_list(values):
            if _positive_major_excluded_by_negative_scope(
                level=key,
                name=name,
                negative_level1=negative_level1,
                negative_level2=negative_level2,
                negative_level3=negative_level3,
                level2_to_level1=level2_to_level1,
                level3_to_level2=level3_to_level2,
            ):
                changed = True
                continue
            kept.append(name)
        if kept:
            cleaned[key] = kept
        elif _as_string_list(values):
            changed = True

    if changed:
        logger.info(
            "Removed positive major targets excluded by negative scopes: before=%s after=%s",
            payload,
            cleaned,
        )
    return cleaned or None


def _remove_unstated_positive_major_conflicts(
    payload: dict[str, Any] | None,
    *,
    latest_utterance: str,
    batch: str,
) -> dict[str, Any] | None:
    """Drop positive major scopes invented around an explicit exclusion.

    LLM extraction can occasionally return a positive parent category together
    with a negative child, for example "不要英语相关专业" -> positive
    "外国语言文学类" plus negative "英语". That must not become an only-keep
    action. Keep positive values only when the user explicitly mentioned that
    positive scope.
    """

    if not isinstance(payload, dict) or not payload:
        return payload
    if not _has_positive_major_values(payload) or not _has_negative_major_values(payload):
        return payload

    polarity_mentions = _recover_polarity_major_intent_locally_from_latest_utterance(latest_utterance, batch) or {}
    explicit_positive_mentions = {
        "level1": set(_as_string_list(polarity_mentions.get("level1"))),
        "level2": set(_as_string_list(polarity_mentions.get("level2"))),
        "level3": set(_as_string_list(polarity_mentions.get("level3"))),
    }
    explicit_positive_any = any(explicit_positive_mentions.values())
    mappings = major_parent_mappings_for_batch(batch)
    level2_to_level1 = mappings.get("level2_to_level1", {})
    level3_to_level2 = mappings.get("level3_to_level2", {})
    negative_level1 = set(_as_string_list(payload.get("negative_level1")))
    negative_level2 = set(_as_string_list(payload.get("negative_level2")))
    negative_level3 = set(_as_string_list(payload.get("negative_level3")))

    cleaned: dict[str, Any] = {}
    changed = False
    for key, values in payload.items():
        if key not in _MAJOR_POSITIVE_KEYS:
            cleaned[key] = values
            continue
        level = key
        explicit_positive = explicit_positive_mentions.get(level, set())
        kept: list[str] = []
        for name in _as_string_list(values):
            if not explicit_positive_any:
                changed = True
                continue
            if explicit_positive_any:
                if name in explicit_positive:
                    kept.append(name)
                else:
                    changed = True
                continue
            if _positive_major_covered_by_negative_scope(
                level=level,
                name=name,
                negative_level1=negative_level1,
                negative_level2=negative_level2,
                negative_level3=negative_level3,
                level2_to_level1=level2_to_level1,
                level3_to_level2=level3_to_level2,
            ):
                changed = True
                continue
            kept.append(name)
        if kept:
            cleaned[key] = kept
        elif _as_string_list(values):
            changed = True

    if changed:
        logger.info(
            "Removed unstated positive major conflicts from exclusion payload: latest=%s before=%s after=%s",
            latest_utterance,
            payload,
            cleaned,
        )
    return cleaned or None


def _merge_intent_payload_dict(existing: dict[str, Any] | None, current: dict[str, Any] | None) -> dict[str, Any] | None:
    merged: dict[str, list[str]] = {}
    for payload in (existing or {}, current or {}):
        for key, values in payload.items():
            normalized_values = _as_string_list(values)
            if not normalized_values:
                continue
            merged[key] = _merge_list(merged.get(key), normalized_values)
    return merged or None


def _existing_intent_item(content: str, value: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": content,
        "value": value,
        "selected": False,
    }


def _merge_list_with_emotion(
    existing_vals: list[str] | None,
    existing_emotions: list[str] | None,
    new_vals: list[str],
    default_emotion: str = "Strong",
) -> tuple[list[str], list[str]]:
    """Merge new values with emotions into existing lists."""
    vals = list(existing_vals or [])
    emotions = list(existing_emotions or [])
    # Pad emotions to match vals length
    while len(emotions) < len(vals):
        emotions.append(default_emotion)
    existing_set = set(vals)
    for v in new_vals:
        if v not in existing_set:
            vals.append(v)
            emotions.append(default_emotion)
            existing_set.add(v)
    return vals, emotions


def _build_proposed_profile(
    current_profile: Any,
    major_intents: dict | None,
    school_intents: dict | None,
    city_intents: dict | None,
    batch: str = "01",
) -> dict[str, Any]:
    """Build the proposed profile in backend format by merging changes into current profile.

    This creates a complete profile (same structure as UserProfileData in Java)
    that represents what the profile would look like after the proposed changes.
    """
    # Start from the current profile in backend format
    proposed = current_profile.to_backend_format()

    # --- Merge major intents ---
    if major_intents:
        mi = proposed["major_intent"]
        nmi = proposed["negative_major_intent"]
        for level in ("level1", "level2", "level3"):
            new_vals = major_intents.get(level, [])
            if new_vals:
                merged_v, merged_e = _merge_list_with_emotion(
                    mi.get(level), mi.get(f"{level}_emotion"), new_vals,
                )
                mi[level] = merged_v
                mi[f"{level}_emotion"] = merged_e
        for level in ("level1", "level2", "level3"):
            neg_key = f"negative_{level}"
            new_vals = major_intents.get(neg_key, [])
            if new_vals:
                merged_v, merged_e = _merge_list_with_emotion(
                    nmi.get(level), nmi.get(f"{level}_emotion"), new_vals,
                )
                nmi[level] = merged_v
                nmi[f"{level}_emotion"] = merged_e

    # --- Merge school intents ---
    if school_intents:
        ci = proposed["college_info"]
        nci = proposed["negative_college_info"]
        colleges = school_intents.get("colleges", [])
        if colleges:
            merged_v, merged_e = _merge_list_with_emotion(
                ci.get("values"), ci.get("values_emotion"), colleges,
            )
            ci["values"] = merged_v
            ci["values_emotion"] = merged_e
        neg_colleges = school_intents.get("negative_colleges", [])
        if neg_colleges:
            merged_v, merged_e = _merge_list_with_emotion(
                nci.get("values"), nci.get("values_emotion"), neg_colleges,
            )
            nci["values"] = merged_v
            nci["values_emotion"] = merged_e

    # --- Merge city intents ---
    if city_intents:
        cinfo = proposed["city_info"]
        ncinfo = proposed["negative_city_info"]
        for field in ("province", "city"):
            new_vals = city_intents.get(field, [])
            if new_vals:
                merged_v, merged_e = _merge_list_with_emotion(
                    cinfo.get(field), cinfo.get(f"{field}_emotion"), new_vals,
                )
                cinfo[field] = merged_v
                cinfo[f"{field}_emotion"] = merged_e
        # area has no emotions
        new_area = city_intents.get("area", [])
        if new_area:
            cinfo["area"] = _merge_list(cinfo.get("area"), new_area)
        for field in ("province", "city"):
            neg_key = f"negative_{field}"
            new_vals = city_intents.get(neg_key, [])
            if new_vals:
                merged_v, merged_e = _merge_list_with_emotion(
                    ncinfo.get(field), ncinfo.get(f"{field}_emotion"), new_vals,
                )
                ncinfo[field] = merged_v
                ncinfo[f"{field}_emotion"] = merged_e
        neg_area = city_intents.get("negative_area", [])
        if neg_area:
            ncinfo["area"] = _merge_list(ncinfo.get("area"), neg_area)
    logger.debug("Proposed profile before code enrichment: {}", proposed)
    return add_codes_to_profile(proposed, batch)


# ---------------------------------------------------------------------------
# Selective adoption helpers
# ---------------------------------------------------------------------------

# Mapping from intent category + sub-key to human-readable labels and wording
_MAJOR_POSITIVE_KEYS = ("level1", "level2", "level3")
_MAJOR_NEGATIVE_KEYS = ("negative_level1", "negative_level2", "negative_level3")
_SCHOOL_POSITIVE_KEYS = ("colleges",)
_SCHOOL_NEGATIVE_KEYS = ("negative_colleges",)
_CITY_POSITIVE_KEYS = ("province", "city", "area")
_CITY_NEGATIVE_KEYS = ("negative_province", "negative_city", "negative_area")
_CAREER_POSITIVE_KEYS = ("positive",)
_CAREER_NEGATIVE_KEYS = ("negative",)

_LABEL_MAP: dict[str, str] = {
    # major positive
    "major_intents.level1": "专业门类",
    "major_intents.level2": "专业类",
    "major_intents.level3": "具体专业",
    # major negative
    "major_intents.negative_level1": "排除专业门类",
    "major_intents.negative_level2": "排除专业类",
    "major_intents.negative_level3": "排除具体专业",
    # school
    "school_intents.colleges": "学校",
    "school_intents.negative_colleges": "排除学校",
    # city
    "city_intents.province": "省份",
    "city_intents.city": "城市",
    "city_intents.area": "地域",
    "city_intents.negative_province": "排除省份",
    "city_intents.negative_city": "排除城市",
    "city_intents.negative_area": "排除地域",
    "career_intents.positive": "就业导向偏好",
    "career_intents.negative": "排除就业导向",
}


def _is_negative_key(sub_key: str) -> bool:
    return sub_key.startswith("negative_")


def _label_for_intent_mode(label: str, *, intent_mode: str) -> str:
    if intent_mode == INTENT_MODE_CONSTRAINT:
        return label
    replacements = {
        "排除专业门类": "不优先专业门类",
        "排除专业类": "不优先专业类",
        "排除具体专业": "不优先具体专业",
        "排除学校": "不优先学校",
        "排除省份": "不优先省份",
        "排除城市": "不优先城市",
        "排除就业导向": "不优先就业导向",
    }
    return replacements.get(label, label)


def _plain_intent_scope_label(label: str) -> str:
    return (
        label.replace("排除", "")
        .replace("不优先", "")
        .replace("偏好", "")
        .strip()
        or "内容"
    )


def _constraint_state_section(constraint_state: dict[str, Any] | None, section: str) -> dict[str, Any]:
    if not isinstance(constraint_state, dict):
        return {}
    value = constraint_state.get(section)
    return value if isinstance(value, dict) else {}


def _constraint_state_values(
    constraint_state: dict[str, Any] | None,
    *,
    domain: str,
    polarity: str,
    intent_mode: str,
) -> list[str]:
    hard = _constraint_state_section(constraint_state, "hardConstraints")
    soft = _constraint_state_section(constraint_state, "softPreferences")
    key_map = {
        (INTENT_MODE_CONSTRAINT, "major", "positive"): "mustIncludeMajors",
        (INTENT_MODE_CONSTRAINT, "major", "negative"): "mustExcludeMajors",
        (INTENT_MODE_CONSTRAINT, "school", "positive"): "mustIncludeSchools",
        (INTENT_MODE_CONSTRAINT, "school", "negative"): "mustExcludeSchools",
        (INTENT_MODE_CONSTRAINT, "region", "positive"): "mustIncludeRegions",
        (INTENT_MODE_CONSTRAINT, "region", "negative"): "mustExcludeRegions",
        (INTENT_MODE_PREFERENCE, "major", "positive"): "preferMajors",
        (INTENT_MODE_PREFERENCE, "major", "negative"): "avoidMajors",
        (INTENT_MODE_PREFERENCE, "school", "positive"): "preferSchools",
        (INTENT_MODE_PREFERENCE, "school", "negative"): "avoidSchools",
        (INTENT_MODE_PREFERENCE, "region", "positive"): "preferRegions",
        (INTENT_MODE_PREFERENCE, "region", "negative"): "avoidRegions",
    }
    key = key_map.get((intent_mode, domain, polarity))
    if not key:
        return []
    source = hard if intent_mode == INTENT_MODE_CONSTRAINT else soft
    return _as_string_list(source.get(key))


def _major_negative_state_contains(values: list[str], *, key: str, name: str, batch: str) -> bool:
    """Hard/soft negative parent major states cover their child major names."""
    state_values = set(values)
    if name in state_values:
        return True
    mappings = major_parent_mappings_for_batch(batch)
    level2_to_level1 = mappings.get("level2_to_level1", {})
    level3_to_level2 = mappings.get("level3_to_level2", {})
    parent2 = level3_to_level2.get(name)
    parent1 = level2_to_level1.get(parent2 or "") if parent2 else level2_to_level1.get(name)
    if key == "negative_level3":
        return bool((parent2 and parent2 in state_values) or (parent1 and parent1 in state_values))
    if key == "negative_level2":
        return bool(parent1 and parent1 in state_values)
    return False


def _constraint_state_contains(
    constraint_state: dict[str, Any] | None,
    *,
    domain: str,
    polarity: str,
    intent_mode: str,
    value: str,
    key: str = "",
    batch: str = "01",
) -> bool:
    values = _constraint_state_values(
        constraint_state,
        domain=domain,
        polarity=polarity,
        intent_mode=intent_mode,
    )
    if domain == "major" and polarity == "negative":
        return _major_negative_state_contains(values, key=key, name=value, batch=batch)
    return value in set(values)


def _existing_item_content(label: str, name: str, *, intent_mode: str, polarity: str) -> str:
    if intent_mode == INTENT_MODE_CONSTRAINT:
        scope = _plain_intent_scope_label(label)
        if polarity == "negative":
            return f"当前已记录的明确排除{scope}要求：{name}"
        return f"当前已记录的明确要满足{scope}要求：{name}"
    prefix = "偏好" if polarity == "positive" else ""
    return f"当前已记录的报考参考{prefix}{label}：{name}"


def _positive_select_item_content(
    name: str,
    label: str,
    *,
    intent_mode: str,
    already: bool = False,
    has_opposite_conflict: bool = False,
) -> str:
    scope = _plain_intent_scope_label(label)
    if intent_mode == INTENT_MODE_CONSTRAINT:
        if has_opposite_conflict:
            return f"将{name}从不优先或排除范围里重新纳入，并作为明确要满足的{scope}要求。"
        if already:
            return f"将{name}从普通偏好升级为明确要满足的{scope}要求，后面看候选和方案时会按这个范围来。"
        return f"把{name}记成明确要满足的{scope}要求，后面看候选和方案时会按这个范围来。"
    if has_opposite_conflict:
        return f"将{name}从不优先或排除范围里重新纳入，后续专家推荐会更优先考虑它。"
    return f"将{name}更新为偏好{scope}，后续专家推荐会更优先考虑它。"


def _negative_select_item_content(name: str, label: str, *, intent_mode: str, already: bool = False) -> str:
    scope = _plain_intent_scope_label(label)
    if intent_mode == INTENT_MODE_CONSTRAINT:
        if already:
            return f"将{name}从不优先升级为明确不考虑的{scope}要求，后面看候选和方案时都会按这个要求来。"
        return f"把{name}记成明确不考虑的{scope}要求，后面看候选和方案时都会按这个要求来。"
    return f"将{name}设为不优先{scope}，后续专家推荐会降低它的优先级。"


def _interest_stage_item_content(value: dict[str, Any] | None, intent_mode: str) -> str | None:
    """Render analysis-only intent items without implying the preference was saved."""
    if not isinstance(value, dict):
        return None

    label_specs = (
        (
            "major_intents",
            (
                ("level1", "专业门类", "positive"),
                ("level2", "专业类", "positive"),
                ("level3", "专业", "positive"),
                ("negative_level1", "专业门类", "negative"),
                ("negative_level2", "专业类", "negative"),
                ("negative_level3", "专业", "negative"),
            ),
        ),
        (
            "school_intents",
            (
                ("colleges", "院校", "positive"),
                ("negative_colleges", "院校", "negative"),
            ),
        ),
        (
            "city_intents",
            (
                ("province", "省份", "positive"),
                ("city", "城市", "positive"),
                ("negative_province", "省份", "negative"),
                ("negative_city", "城市", "negative"),
            ),
        ),
        (
            "career_intents",
            (
                ("positive", "发展方向", "positive"),
                ("negative", "发展方向", "negative"),
            ),
        ),
    )

    for category, specs in label_specs:
        payload = value.get(category)
        if not isinstance(payload, dict):
            continue
        for key, label, polarity in specs:
            names = _as_string_list(payload.get(key))
            if category == "career_intents":
                names = to_career_labels(names)
            if not names:
                continue
            text = "、".join(names)
            if polarity == "negative":
                if intent_mode == INTENT_MODE_CONSTRAINT:
                    action = f"不考虑{text}（{label}）"
                    mode_text = "要求"
                else:
                    action = f"降低{text}（{label}）的优先级"
                    mode_text = "偏好"
            else:
                action = f"优先关注{text}（{label}）"
                mode_text = "要求" if intent_mode == INTENT_MODE_CONSTRAINT else "偏好"
            return f"可整理成待确认{mode_text}：{action}。当前只是分析口径，还不会影响后续推荐。"
    return None


def _neutralize_interest_stage_items(
    items: list[dict[str, Any]],
    *,
    intent_mode: str,
    analysis_stage: str,
) -> list[dict[str, Any]]:
    if analysis_stage != ANALYSIS_STAGE_INTEREST:
        return items
    neutralized: list[dict[str, Any]] = []
    for item in items:
        copied = dict(item)
        content = _interest_stage_item_content(copied.get("value"), intent_mode)
        if content:
            copied["content"] = content
        neutralized.append(copied)
    return neutralized


def _major_profile_has_opposite_conflict(
    major_profile: Any,
    *,
    key: str,
    name: str,
    batch: str,
) -> bool:
    mappings = major_parent_mappings_for_batch(batch)
    level3_to_level2 = mappings.get("level3_to_level2", {})
    level2_to_level1 = mappings.get("level2_to_level1", {})

    level1 = set(_as_string_list(getattr(major_profile, "level1", [])))
    level2 = set(_as_string_list(getattr(major_profile, "level2", [])))
    level3 = set(_as_string_list(getattr(major_profile, "level3", [])))
    negative_level1 = set(_as_string_list(getattr(major_profile, "negative_level1", [])))
    negative_level2 = set(_as_string_list(getattr(major_profile, "negative_level2", [])))
    negative_level3 = set(_as_string_list(getattr(major_profile, "negative_level3", [])))

    parent2 = level3_to_level2.get(name)
    parent1 = level2_to_level1.get(parent2 or "") if parent2 else level2_to_level1.get(name)

    if key == "level1":
        return (
            name in negative_level1
            or any(level2_to_level1.get(value) == name for value in negative_level2)
            or any(level2_to_level1.get(level3_to_level2.get(value) or "") == name for value in negative_level3)
        )
    if key == "level2":
        return (
            name in negative_level2
            or parent1 in negative_level1
            or any(level3_to_level2.get(value) == name for value in negative_level3)
        )
    if key == "level3":
        return name in negative_level3 or parent2 in negative_level2 or parent1 in negative_level1
    if key == "negative_level1":
        return (
            name in level1
            or any(level2_to_level1.get(value) == name for value in level2)
            or any(level2_to_level1.get(level3_to_level2.get(value) or "") == name for value in level3)
        )
    if key == "negative_level2":
        return name in level2 or any(level3_to_level2.get(value) == name for value in level3)
    if key == "negative_level3":
        return name in level3
    return False


def _build_select_items(
    current_profile: Any,
    major_intents: dict | None,
    school_intents: dict | None,
    city_intents: dict | None,
    career_intents: dict | None = None,
    *,
    intent_mode: str = INTENT_MODE_PREFERENCE,
    analysis_stage: str = ANALYSIS_STAGE_CONFIRMED,
    batch: str = "01",
    constraint_state: dict[str, Any] | None = None,
    latest_utterance: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Generate structured items for selective adoption popup.

    Returns:
        (items, existing_items)
        - items: new intents, each with content/value/selected
        - existing_items: already-in-profile intents, display-only
    """
    items: list[dict[str, Any]] = []
    existing_items: list[dict[str, Any]] = []
    major_intents = _dedupe_major_intent_payload_across_levels(major_intents)
    positive_intent_mode = (
        INTENT_MODE_CONSTRAINT
        if intent_mode == INTENT_MODE_CONSTRAINT
        and not _has_negative_intents(major_intents, school_intents, city_intents, career_intents)
        else INTENT_MODE_PREFERENCE
    )

    # --- Major intents ---
    if major_intents:
        for level in _MAJOR_POSITIVE_KEYS:
            names = major_intents.get(level, [])
            if not names:
                continue
            existing = getattr(current_profile.major, level, [])
            for name in names:
                display_name = _major_display_name_from_latest_utterance(
                    level=level,
                    name=name,
                    latest_utterance=latest_utterance,
                    batch=batch,
                )
                _, already = _diff_list(existing, [name])
                label = _LABEL_MAP[f"major_intents.{level}"]
                hard_existing = _constraint_state_contains(
                    constraint_state,
                    domain="major",
                    polarity="positive",
                    intent_mode=INTENT_MODE_CONSTRAINT,
                    value=name,
                    key=level,
                    batch=batch,
                )
                soft_existing = _constraint_state_contains(
                    constraint_state,
                    domain="major",
                    polarity="positive",
                    intent_mode=INTENT_MODE_PREFERENCE,
                    value=name,
                    key=level,
                    batch=batch,
                )
                has_opposite_conflict = _major_profile_has_opposite_conflict(
                    current_profile.major,
                    key=level,
                    name=name,
                    batch=batch,
                )
                if hard_existing and positive_intent_mode == INTENT_MODE_CONSTRAINT:
                    existing_items.append(_existing_intent_item(
                        _existing_item_content(label, display_name, intent_mode=INTENT_MODE_CONSTRAINT, polarity="positive"),
                        {"major_intents": {level: [name]}},
                    ))
                elif (already or soft_existing or hard_existing) and not has_opposite_conflict and positive_intent_mode != INTENT_MODE_CONSTRAINT:
                    existing_items.append(_existing_intent_item(
                        _existing_item_content(label, display_name, intent_mode=INTENT_MODE_PREFERENCE, polarity="positive"),
                        {"major_intents": {level: [name]}},
                    ))
                else:
                    items.append({
                        "content": _positive_select_item_content(
                            display_name,
                            label,
                            intent_mode=positive_intent_mode,
                            already=bool(already),
                            has_opposite_conflict=has_opposite_conflict,
                        ),
                        "value": {"major_intents": {level: [name]}},
                        "selected": True,
                    })

        for level in _MAJOR_NEGATIVE_KEYS:
            names = major_intents.get(level, [])
            if not names:
                continue
            existing = getattr(current_profile.major, level, [])
            for name in names:
                _, already = _diff_list(existing, [name])
                label = _label_for_intent_mode(_LABEL_MAP[f"major_intents.{level}"], intent_mode=intent_mode)
                hard_existing = _constraint_state_contains(
                    constraint_state,
                    domain="major",
                    polarity="negative",
                    intent_mode=INTENT_MODE_CONSTRAINT,
                    value=name,
                    key=level,
                    batch=batch,
                )
                soft_existing = _constraint_state_contains(
                    constraint_state,
                    domain="major",
                    polarity="negative",
                    intent_mode=INTENT_MODE_PREFERENCE,
                    value=name,
                    key=level,
                    batch=batch,
                )
                has_opposite_conflict = _major_profile_has_opposite_conflict(
                    current_profile.major,
                    key=level,
                    name=name,
                    batch=batch,
                )
                if hard_existing and intent_mode == INTENT_MODE_CONSTRAINT:
                    existing_items.append(_existing_intent_item(
                        _existing_item_content(_LABEL_MAP[f"major_intents.{level}"], name, intent_mode=INTENT_MODE_CONSTRAINT, polarity="negative"),
                        {"major_intents": {level: [name]}},
                    ))
                elif (already or soft_existing or hard_existing) and not has_opposite_conflict and intent_mode != INTENT_MODE_CONSTRAINT:
                    existing_items.append(_existing_intent_item(
                        _existing_item_content(label, name, intent_mode=INTENT_MODE_PREFERENCE, polarity="negative"),
                        {"major_intents": {level: [name]}},
                    ))
                else:
                    items.append({
                        "content": _negative_select_item_content(
                            name,
                            label,
                            intent_mode=intent_mode,
                            already=bool(already),
                        ),
                        "value": {"major_intents": {level: [name]}},
                        "selected": True,
                    })

    # --- School intents ---
    if school_intents:
        for sub_key in _SCHOOL_POSITIVE_KEYS:
            names = school_intents.get(sub_key, [])
            if not names:
                continue
            existing = getattr(current_profile.school, sub_key, [])
            for name in names:
                _, already = _diff_list(existing, [name])
                label = _LABEL_MAP[f"school_intents.{sub_key}"]
                hard_existing = _constraint_state_contains(
                    constraint_state,
                    domain="school",
                    polarity="positive",
                    intent_mode=INTENT_MODE_CONSTRAINT,
                    value=name,
                    key=sub_key,
                    batch=batch,
                )
                soft_existing = _constraint_state_contains(
                    constraint_state,
                    domain="school",
                    polarity="positive",
                    intent_mode=INTENT_MODE_PREFERENCE,
                    value=name,
                    key=sub_key,
                    batch=batch,
                )
                if hard_existing and positive_intent_mode == INTENT_MODE_CONSTRAINT:
                    existing_items.append(_existing_intent_item(
                        _existing_item_content(label, name, intent_mode=INTENT_MODE_CONSTRAINT, polarity="positive"),
                        {"school_intents": {sub_key: [name]}},
                    ))
                elif (already or soft_existing or hard_existing) and positive_intent_mode != INTENT_MODE_CONSTRAINT:
                    existing_items.append(_existing_intent_item(
                        _existing_item_content(label, name, intent_mode=INTENT_MODE_PREFERENCE, polarity="positive"),
                        {"school_intents": {sub_key: [name]}},
                    ))
                else:
                    items.append({
                        "content": _positive_select_item_content(
                            name,
                            label,
                            intent_mode=positive_intent_mode,
                            already=bool(already),
                        ),
                        "value": {"school_intents": {sub_key: [name]}},
                        "selected": True,
                    })

        for sub_key in _SCHOOL_NEGATIVE_KEYS:
            names = school_intents.get(sub_key, [])
            if not names:
                continue
            existing = getattr(current_profile.school, sub_key, [])
            for name in names:
                _, already = _diff_list(existing, [name])
                label = _label_for_intent_mode(_LABEL_MAP[f"school_intents.{sub_key}"], intent_mode=intent_mode)
                hard_existing = _constraint_state_contains(
                    constraint_state,
                    domain="school",
                    polarity="negative",
                    intent_mode=INTENT_MODE_CONSTRAINT,
                    value=name,
                    key=sub_key,
                    batch=batch,
                )
                soft_existing = _constraint_state_contains(
                    constraint_state,
                    domain="school",
                    polarity="negative",
                    intent_mode=INTENT_MODE_PREFERENCE,
                    value=name,
                    key=sub_key,
                    batch=batch,
                )
                if hard_existing and intent_mode == INTENT_MODE_CONSTRAINT:
                    existing_items.append(_existing_intent_item(
                        _existing_item_content(_LABEL_MAP[f"school_intents.{sub_key}"], name, intent_mode=INTENT_MODE_CONSTRAINT, polarity="negative"),
                        {"school_intents": {sub_key: [name]}},
                    ))
                elif (already or soft_existing or hard_existing) and intent_mode != INTENT_MODE_CONSTRAINT:
                    existing_items.append(_existing_intent_item(
                        _existing_item_content(label, name, intent_mode=INTENT_MODE_PREFERENCE, polarity="negative"),
                        {"school_intents": {sub_key: [name]}},
                    ))
                else:
                    items.append({
                        "content": _negative_select_item_content(
                            name,
                            label,
                            intent_mode=intent_mode,
                            already=bool(already),
                        ),
                        "value": {"school_intents": {sub_key: [name]}},
                        "selected": True,
                    })

    # --- City intents ---
    if city_intents:
        for sub_key in _CITY_POSITIVE_KEYS:
            names = city_intents.get(sub_key, [])
            if not names:
                continue
            existing = getattr(current_profile.city, sub_key, [])
            for name in names:
                _, already = _diff_list(existing, [name])
                label = _LABEL_MAP[f"city_intents.{sub_key}"]
                hard_existing = _constraint_state_contains(
                    constraint_state,
                    domain="region",
                    polarity="positive",
                    intent_mode=INTENT_MODE_CONSTRAINT,
                    value=name,
                    key=sub_key,
                    batch=batch,
                )
                soft_existing = _constraint_state_contains(
                    constraint_state,
                    domain="region",
                    polarity="positive",
                    intent_mode=INTENT_MODE_PREFERENCE,
                    value=name,
                    key=sub_key,
                    batch=batch,
                )
                if hard_existing and positive_intent_mode == INTENT_MODE_CONSTRAINT:
                    existing_items.append(_existing_intent_item(
                        _existing_item_content(label, name, intent_mode=INTENT_MODE_CONSTRAINT, polarity="positive"),
                        {"city_intents": {sub_key: [name]}},
                    ))
                elif (already or soft_existing or hard_existing) and positive_intent_mode != INTENT_MODE_CONSTRAINT:
                    existing_items.append(_existing_intent_item(
                        _existing_item_content(label, name, intent_mode=INTENT_MODE_PREFERENCE, polarity="positive"),
                        {"city_intents": {sub_key: [name]}},
                    ))
                else:
                    items.append({
                        "content": _positive_select_item_content(
                            name,
                            label,
                            intent_mode=positive_intent_mode,
                            already=bool(already),
                        ),
                        "value": {"city_intents": {sub_key: [name]}},
                        "selected": True,
                    })

        for sub_key in _CITY_NEGATIVE_KEYS:
            names = city_intents.get(sub_key, [])
            if not names:
                continue
            existing = getattr(current_profile.city, sub_key, [])
            for name in names:
                _, already = _diff_list(existing, [name])
                label = _label_for_intent_mode(_LABEL_MAP[f"city_intents.{sub_key}"], intent_mode=intent_mode)
                hard_existing = _constraint_state_contains(
                    constraint_state,
                    domain="region",
                    polarity="negative",
                    intent_mode=INTENT_MODE_CONSTRAINT,
                    value=name,
                    key=sub_key,
                    batch=batch,
                )
                soft_existing = _constraint_state_contains(
                    constraint_state,
                    domain="region",
                    polarity="negative",
                    intent_mode=INTENT_MODE_PREFERENCE,
                    value=name,
                    key=sub_key,
                    batch=batch,
                )
                if hard_existing and intent_mode == INTENT_MODE_CONSTRAINT:
                    existing_items.append(_existing_intent_item(
                        _existing_item_content(_LABEL_MAP[f"city_intents.{sub_key}"], name, intent_mode=INTENT_MODE_CONSTRAINT, polarity="negative"),
                        {"city_intents": {sub_key: [name]}},
                    ))
                elif (already or soft_existing or hard_existing) and intent_mode != INTENT_MODE_CONSTRAINT:
                    existing_items.append(_existing_intent_item(
                        _existing_item_content(label, name, intent_mode=INTENT_MODE_PREFERENCE, polarity="negative"),
                        {"city_intents": {sub_key: [name]}},
                    ))
                else:
                    items.append({
                        "content": _negative_select_item_content(
                            name,
                            label,
                            intent_mode=intent_mode,
                            already=bool(already),
                        ),
                        "value": {"city_intents": {sub_key: [name]}},
                        "selected": True,
                    })

    if career_intents:
        for sub_key in _CAREER_POSITIVE_KEYS:
            values = career_intents.get(sub_key, [])
            if not values:
                continue
            for value in values:
                label = to_career_label(value)
                items.append({
                    "content": f"把“{label}”记成你更看重的方向，后面我会优先按这个思路帮你看方案。",
                    "value": {"career_intents": {sub_key: [value]}},
                    "selected": True,
                })

        for sub_key in _CAREER_NEGATIVE_KEYS:
            values = career_intents.get(sub_key, [])
            if not values:
                continue
            for value in values:
                label = to_career_label(value)
                items.append({
                    "content": f"把“{label}”记成你暂时不考虑的方向，后面我会尽量避开这类建议。",
                    "value": {"career_intents": {sub_key: [value]}},
                    "selected": True,
                })

    return (
        _neutralize_interest_stage_items(
            items,
            intent_mode=intent_mode,
            analysis_stage=analysis_stage,
        ),
        existing_items,
    )


def _negative_values_overlap_positive_profile(
    current_profile: Any,
    *,
    major_intents: dict | None,
    school_intents: dict | None,
    city_intents: dict | None,
    career_intents: dict | None = None,
) -> bool:
    major_profile = getattr(current_profile, "major", None)
    school_profile = getattr(current_profile, "school", None)
    city_profile = getattr(current_profile, "city", None)

    for negative_key, positive_key in (
        ("negative_level1", "level1"),
        ("negative_level2", "level2"),
        ("negative_level3", "level3"),
    ):
        negative_values = set(_as_string_list((major_intents or {}).get(negative_key)))
        positive_values = set(_as_string_list(getattr(major_profile, positive_key, [])))
        if negative_values & positive_values:
            return True

    negative_schools = set(_as_string_list((school_intents or {}).get("negative_colleges")))
    positive_schools = set(_as_string_list(getattr(school_profile, "colleges", [])))
    if negative_schools & positive_schools:
        return True

    for negative_key, positive_key in (
        ("negative_province", "province"),
        ("negative_city", "city"),
        ("negative_area", "area"),
    ):
        negative_values = set(_as_string_list((city_intents or {}).get(negative_key)))
        positive_values = set(_as_string_list(getattr(city_profile, positive_key, [])))
        if negative_values & positive_values:
            return True

    # Career preferences are stored in planning latent profile rather than
    # UserProfile; keep them confirmable unless a later backend API exposes the
    # same positive/negative split here.
    if career_intents:
        return True
    return False


def _has_concrete_current_conflict(impact_analysis: dict[str, Any] | None) -> bool:
    if not isinstance(impact_analysis, dict):
        return False
    for raw_item in impact_analysis.get("currentPlanConflict") or []:
        text = str(raw_item or "").strip()
        if not text:
            continue
        if "暂时没有直接命中" in text:
            continue
        if "影响不大" in text:
            continue
        return True
    return False


def _negative_preference_scope_text(
    major_intents: dict | None,
    school_intents: dict | None,
    city_intents: dict | None,
    career_intents: dict | None = None,
) -> str:
    values: list[str] = []
    for payload, keys in (
        (major_intents, ("negative_level3", "negative_level2", "negative_level1")),
        (school_intents, ("negative_colleges",)),
        (city_intents, ("negative_province", "negative_city", "negative_area")),
        (career_intents, ("negative",)),
    ):
        if not isinstance(payload, dict):
            continue
        for key in keys:
            for value in _as_string_list(payload.get(key)):
                if value not in values:
                    values.append(value)
    if not values:
        return "这个方向"
    visible = "、".join(values[:3])
    return visible + (f"等{len(values)}项" if len(values) > 3 else "")


def _build_no_effect_negative_preference_message(
    current_profile: Any,
    *,
    major_intents: dict | None,
    school_intents: dict | None,
    city_intents: dict | None,
    career_intents: dict | None = None,
    intent_mode: str,
    analysis_stage: str,
    impact_analysis: dict[str, Any] | None,
) -> str | None:
    if analysis_stage != ANALYSIS_STAGE_CONFIRMED:
        return None
    if not _is_negative_only_preference(
        intent_mode=intent_mode,
        major_intents=major_intents,
        school_intents=school_intents,
        city_intents=city_intents,
        career_intents=career_intents,
    ):
        return None
    if _negative_values_overlap_positive_profile(
        current_profile,
        major_intents=major_intents,
        school_intents=school_intents,
        city_intents=city_intents,
        career_intents=career_intents,
    ):
        return None
    if _has_concrete_current_conflict(impact_analysis):
        return None
    scope_text = _negative_preference_scope_text(major_intents, school_intents, city_intents, career_intents)
    return (
        f"当前已记录的偏好和这份方案里暂时没有明显命中“{scope_text}”，"
        "这次不需要额外采纳。后续如果这是必须避开的报考条件，可以直接说明，我会再列出来让你采纳。"
    )


def merge_selected_values(selected_values: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge selected items' value dicts into unified intent structure.

    Input: list of value dicts like
        [{"major_intents": {"level3": ["X"]}}, {"school_intents": {"colleges": ["Y"]}}]
    Output:
        {"major_intents": {"level3": ["X"]}, "school_intents": {"colleges": ["Y"]}}
    """
    merged: dict[str, Any] = {}
    for val_dict in selected_values:
        for category, sub_dict in val_dict.items():
            # category is one of: major_intents, school_intents, city_intents
            if category not in merged:
                merged[category] = {}
            for sub_key, values in sub_dict.items():
                if sub_key not in merged[category]:
                    merged[category][sub_key] = []
                # Deduplicate while preserving order
                existing_set = set(merged[category][sub_key])
                for v in values:
                    if v not in existing_set:
                        merged[category][sub_key].append(v)
                        existing_set.add(v)
    return merged


# ---------------------------------------------------------------------------
# Public tool functions
# ---------------------------------------------------------------------------

_EDIT_FLAG_CN: dict[str, str] = {
    "add": "增加",
    "delete": "删除",
    "move": "移动",
    "replace": "替换",
}


def _build_preview_title(
    edit_flag: str | None,
    intent_mode: str = INTENT_MODE_PREFERENCE,
    analysis_stage: str = ANALYSIS_STAGE_CONFIRMED,
) -> str:
    """Build the intent preview title, varying wording based on the edit_flag."""
    if analysis_stage == ANALYSIS_STAGE_INTEREST:
        if intent_mode == INTENT_MODE_CONSTRAINT:
            return "你提到的这个要求，我先结合你现在的情况做个初步分析。"
        return "你提到的这个方向，我先结合你现在的情况做个初步分析。"

    if intent_mode == INTENT_MODE_CONSTRAINT:
        suffix = "你可以勾选想采纳的内容后点击【采纳】。采纳后，候选结果会按这个要求一起收紧，我也能继续帮你看现在的方案要不要调整。"
    else:
        suffix = "你可以勾选想采纳的内容后点击【采纳】。采纳后，我会按这个思路继续帮你看方案和给建议。"
    if edit_flag:
        # Strip null, translate to Chinese, join
        flags = [
            _EDIT_FLAG_CN.get(f.strip(), f.strip())
            for f in edit_flag.replace("null", "").split("|")
            if f.strip() and f.strip() != "null"
        ]
        if flags:
            flags_desc = "、".join(flags)
            return (
                f"这类{flags_desc}需要先看清楚会影响哪些志愿，不能直接替你改。"
                f"我先把相关的{('要求' if intent_mode == INTENT_MODE_CONSTRAINT else '想法')}整理出来。{suffix}"
            )
    return f"好的，我先把这次你提到的{('要求' if intent_mode == INTENT_MODE_CONSTRAINT else '想法')}整理一下。{suffix}"


def _build_popup_title(
    edit_flag: str | None,
    intent_mode: str = INTENT_MODE_PREFERENCE,
    analysis_stage: str = ANALYSIS_STAGE_CONFIRMED,
) -> str:
    """Legacy alias for older tests and protocol wording."""
    return _build_preview_title(edit_flag, intent_mode, analysis_stage)


def _latest_user_utterance(ctx: RunContext[RequestContext]) -> str:
    history = getattr(ctx.deps, "chat_history", None) or []
    for message in reversed(history):
        if message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


_READ_ONLY_FIT_QUESTION_MARKERS = (
    "适合我",
    "适不适合我",
    "我适合",
    "更适合我",
)

_EXPLICIT_INTENT_COMMIT_MARKERS = (
    "记成",
    "记为",
    "记下",
    "作为偏好",
    "作为要求",
    "作为后续参考",
    "纳入后续参考",
    "以后都按",
    "就按这个",
    "按这个方向",
)


def _is_read_only_fit_question(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or "")).strip("。！？?!")
    if not compact:
        return False
    if any(marker in compact for marker in _EXPLICIT_INTENT_COMMIT_MARKERS):
        return False
    return any(marker in compact for marker in _READ_ONLY_FIT_QUESTION_MARKERS)


def _has_negative_intents(
    major_intents: dict | None,
    school_intents: dict | None,
    city_intents: dict | None,
    career_intents: dict | None = None,
) -> bool:
    payload_has_negative = any(
        payload and any(key.startswith("negative_") and values for key, values in payload.items())
        for payload in (major_intents, school_intents, city_intents)
    )
    career_has_negative = bool(career_intents and career_intents.get("negative"))
    return payload_has_negative or career_has_negative


def _has_positive_intents(
    major_intents: dict | None,
    school_intents: dict | None,
    city_intents: dict | None,
    career_intents: dict | None = None,
) -> bool:
    payload_has_positive = any(
        payload and any(
            not key.startswith("negative_") and values
            for key, values in payload.items()
        )
        for payload in (major_intents, school_intents, city_intents)
    )
    career_has_positive = bool(career_intents and career_intents.get("positive"))
    return payload_has_positive or career_has_positive


def _is_negative_only_preference(
    *,
    intent_mode: str,
    major_intents: dict | None,
    school_intents: dict | None,
    city_intents: dict | None,
    career_intents: dict | None = None,
) -> bool:
    return (
        intent_mode == INTENT_MODE_PREFERENCE
        and _has_negative_intents(major_intents, school_intents, city_intents, career_intents)
        and not _has_positive_intents(major_intents, school_intents, city_intents, career_intents)
    )


_SOFT_NEGATIVE_PREFERENCE_MARKERS = (
    "不太想",
    "不是很想",
    "不太考虑",
    "不是很考虑",
    "不太接受",
    "不是很接受",
    "有点排斥",
    "有些排斥",
    "稍微排斥",
    "尽量不",
    "暂时不",
    "先不",
    "不优先",
    "往后放",
)


def _latest_utterance_indicates_soft_negative_preference(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    if not compact:
        return False
    return any(marker in compact for marker in _SOFT_NEGATIVE_PREFERENCE_MARKERS)


def _classify_intent_mode(
    major_intents: dict | None,
    school_intents: dict | None,
    city_intents: dict | None,
    career_intents: dict | None = None,
    *,
    edit_flag: str | None = None,
    explicit_intent_mode: str | None = None,
    latest_utterance: str = "",
) -> str:
    if explicit_intent_mode == INTENT_MODE_CONSTRAINT:
        return INTENT_MODE_CONSTRAINT
    if not _has_negative_intents(major_intents, school_intents, city_intents, career_intents):
        return INTENT_MODE_PREFERENCE
    if explicit_intent_mode == INTENT_MODE_PREFERENCE and _latest_utterance_indicates_soft_negative_preference(latest_utterance):
        return INTENT_MODE_PREFERENCE
    if (
        not _has_positive_intents(major_intents, school_intents, city_intents, career_intents)
        and _latest_utterance_indicates_soft_negative_preference(latest_utterance)
    ):
        return INTENT_MODE_PREFERENCE

    return INTENT_MODE_CONSTRAINT


def _intent_topic(
    major_intents: dict | None,
    school_intents: dict | None,
    city_intents: dict | None,
    career_intents: dict | None = None,
) -> str:
    topics: list[str] = []
    if major_intents:
        topics.append("major")
    if school_intents:
        topics.append("school")
    if city_intents:
        topics.append("region")
    if career_intents:
        topics.append("career")
    return ",".join(topics) if topics else "unknown"


async def _classify_intent_side_effect(
    *,
    latest_utterance: str,
    major_intents: dict | None,
    school_intents: dict | None,
    city_intents: dict | None,
    career_intents: dict | None,
    intent_mode: str,
) -> IntentSideEffectDecision:
    prompt = json.dumps(
        {
            "latestUserText": latest_utterance,
            "topic": _intent_topic(major_intents, school_intents, city_intents, career_intents),
            "intentMode": intent_mode,
            "structuredIntents": {
                "major": major_intents or {},
                "school": school_intents or {},
                "region": city_intents or {},
                "career": career_intents or {},
            },
            "decisionQuestion": (
                "当前是否应生成待确认偏好/要求卡片并写入待确认缓存？"
                "还是只应该回答边界、取舍或适配分析？"
            ),
        },
        ensure_ascii=False,
    )
    result = await _get_intent_side_effect_agent().run(prompt)
    return _normalize_intent_side_effect_decision(parse_extraction_json(result.output, IntentSideEffectDecision))


async def _maybe_downgrade_intent_preview_by_semantics(
    ctx: RunContext[RequestContext],
    *,
    latest_utterance: str,
    major_intents: dict | None,
    school_intents: dict | None,
    city_intents: dict | None,
    career_intents: dict | None,
    intent_mode: str,
    analysis_stage: str,
    confirm_enabled: bool,
) -> tuple[str, bool, IntentSideEffectDecision | None]:
    if analysis_stage == ANALYSIS_STAGE_INTEREST or not confirm_enabled:
        return analysis_stage, confirm_enabled, None
    if not bool(getattr(ctx.deps, "enable_intent_side_effect_arbitration", False)):
        return analysis_stage, confirm_enabled, None
    try:
        decision = await _classify_intent_side_effect(
            latest_utterance=latest_utterance,
            major_intents=major_intents,
            school_intents=school_intents,
            city_intents=city_intents,
            career_intents=career_intents,
            intent_mode=intent_mode,
        )
    except Exception:
        logger.warning(
            "Intent side-effect arbitration failed, keeping preview path: session_id=%s",
            getattr(ctx.deps, "sessionid", ""),
            exc_info=True,
        )
        return analysis_stage, confirm_enabled, None

    observability = getattr(ctx.deps, "agent_observability", None)
    if isinstance(observability, dict):
        observability["intentSideEffectDecision"] = decision.model_dump()

    if decision.decision in {"analysis_only", "mixed_answer_then_ask"} and decision.confidence >= 0.7:
        if decision.decision == "mixed_answer_then_ask":
            logger.info(
                "Intent preview downgraded to mixed answer by semantic arbitration: session_id=%s decision=%s confidence=%s reason=%s",
                getattr(ctx.deps, "sessionid", ""),
                decision.decision,
                decision.confidence,
                decision.reason,
            )
        else:
            logger.info(
                "Intent preview downgraded to interest analysis by semantic arbitration: session_id=%s decision=%s confidence=%s reason=%s",
                getattr(ctx.deps, "sessionid", ""),
                decision.decision,
                decision.confidence,
                decision.reason,
            )
        if isinstance(observability, dict) and isinstance(observability.get("intentSideEffectDecision"), dict):
            observability["intentSideEffectDecision"]["honored"] = True
        return ANALYSIS_STAGE_INTEREST, False, decision

    return analysis_stage, confirm_enabled, decision


def _should_return_abstract_region_interest_payload(
    *,
    latest_utterance: str,
    recovery_scope: str | None,
    had_explicit_intent_payload: bool,
    analysis_stage: str,
    semantic_decision: IntentSideEffectDecision | None,
) -> bool:
    if recovery_scope != "region":
        return False
    if had_explicit_intent_payload:
        return False
    if analysis_stage != ANALYSIS_STAGE_INTEREST:
        return False
    if semantic_decision is None or semantic_decision.decision not in {"analysis_only", "mixed_answer_then_ask"}:
        return False
    if semantic_decision.confidence < 0.7:
        return False
    return not contains_concrete_region_mention(latest_utterance)


def _abstract_region_interest_message() -> str:
    return (
        "你这句话是在描述地域边界，但“省外”“偏远”这类说法还不能稳定落到具体省市。"
        "我先不生成待采纳内容，也不会改动方案。\n\n"
        "可以先按这几个口径确认：哪些省份算太偏、是否排除偏远省份、"
        "省会/沿海城市是否保留机会。等范围说清楚后，我再列出来让你采纳。"
    )


def _impact_title(intent_mode: str) -> str:
    if intent_mode == INTENT_MODE_CONSTRAINT:
        return "对当前方案、候选范围与下一步分析的关联判断"
    return "对当前方案、候选机会与下一步分析的关联判断"


def _impact_title_for_stage(intent_mode: str, analysis_stage: str) -> str:
    if analysis_stage == ANALYSIS_STAGE_INTEREST:
        if intent_mode == INTENT_MODE_CONSTRAINT:
            return "这个方向与当前方案、候选范围的兴趣阶段分析"
        return "这个方向与当前方案、候选机会的兴趣阶段分析"
    return _impact_title(intent_mode)


def _build_single_turn_recovery_context(
    ctx: RunContext[RequestContext],
) -> RunContext[RequestContext]:
    """Restrict fallback extraction to the latest user utterance.

    When the current turn is an explicit intent update like "不去北京", reusing the
    full chat history causes historical profile/preferences to be re-extracted into
    this turn's preview. Fallback recovery should focus on the latest utterance only.
    """
    latest_utterance = _latest_user_utterance(ctx).strip()
    if not latest_utterance:
        return ctx

    single_turn_context = RequestContext(
        userid=getattr(ctx.deps, "userid", ""),
        sessionid=getattr(ctx.deps, "sessionid", ""),
        chat_history=[{"role": "user", "content": latest_utterance}],
        batch=getattr(ctx.deps, "batch", None),
        score_detail=getattr(ctx.deps, "score_detail", None),
        init_profile=getattr(ctx.deps, "init_profile", None),
        planning_summary=getattr(ctx.deps, "planning_summary", None),
    )
    return SimpleNamespace(deps=single_turn_context)


def _has_any_intent_payload(
    major_intents: dict | None,
    school_intents: dict | None,
    city_intents: dict | None,
    career_intents: dict | None = None,
) -> bool:
    def _has_values(payload: dict | None) -> bool:
        return bool(payload and any(values for values in payload.values()))

    return (
        _has_values(major_intents)
        or _has_values(school_intents)
        or _has_values(city_intents)
        or _has_values(career_intents)
    )


def _has_non_empty_payload(payload: dict[str, Any] | None) -> bool:
    return bool(payload and any(values for values in payload.values()))


def _drop_empty_entries(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not payload:
        return None
    cleaned = {key: value for key, value in payload.items() if value}
    return cleaned or None


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, (int, float)):
        return [str(value)]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_as_string_list(item))
        return result
    return []

def _is_intent_confirmation_utterance(value: str) -> bool:
    normalized = re.sub(r"\s+", "", str(value or "").strip())
    normalized = normalized.strip("。.!！?")
    if not normalized:
        return False
    if normalized in _INTENT_CONFIRM_UTTERANCE_PHRASES:
        return True
    return normalized.startswith(("确认", "就按", "按这个", "可以按")) and len(normalized) <= 12


def _normalize_intent_payload(
    payload: dict | None,
    *,
    allowed_keys: tuple[str, ...],
    alias_map: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    if not payload:
        return None
    alias_map = alias_map or {}
    normalized: dict[str, list[str]] = {}
    for key, value in payload.items():
        target_key = key if key in allowed_keys else alias_map.get(str(key))
        if not target_key:
            continue
        values = _as_string_list(value)
        if not values:
            continue
        bucket = normalized.setdefault(target_key, [])
        existing = set(bucket)
        for item in values:
            if item not in existing:
                bucket.append(item)
                existing.add(item)
    return normalized or None


def _dedupe_major_intent_payload_across_levels(payload: dict[str, Any] | None) -> dict[str, list[str]] | None:
    return dedupe_major_intent_payload_across_levels(payload)


def _major_mentions_by_level(text: str, batch: str) -> dict[str, set[str]]:
    mentions: dict[str, set[str]] = {"level1": set(), "level2": set(), "level3": set()}
    for mention in resolve_major_mentions_from_text(text, batch):
        level = str(mention.level or "")
        name = str(mention.canonical_name or "").strip()
        if level in mentions and name:
            mentions[level].add(name)
    return mentions


def _refine_major_intents_by_explicit_mentions(
    major_intents: dict[str, Any] | None,
    *,
    latest_utterance: str,
    batch: str,
) -> dict[str, Any] | None:
    return refine_major_intent_payload_by_explicit_mentions(
        major_intents,
        latest_utterance=latest_utterance,
        batch=batch,
    )


def _normalize_intent_inputs(
    major_intents: dict | None,
    school_intents: dict | None,
    city_intents: dict | None,
    career_intents: dict | None = None,
) -> tuple[dict | None, dict | None, dict | None, dict | None]:
    major_aliases = {
        "add": "level3",
        "include": "level3",
        "interested": "level3",
        "interest": "level3",
        "priority": "level3",
        "desired": "level3",
        "prefer": "level3",
        "preferred": "level3",
        "positive": "level3",
        "major": "level3",
        "majors": "level3",
        "values": "level3",
        "delete": "negative_level3",
        "remove": "negative_level3",
        "exclude": "negative_level3",
        "avoid": "negative_level3",
        "unwanted": "negative_level3",
        "negative": "negative_level3",
    }
    major_payload = _normalize_intent_payload(
        major_intents,
        allowed_keys=_MAJOR_POSITIVE_KEYS + _MAJOR_NEGATIVE_KEYS,
        alias_map=major_aliases,
    )
    return (
        _dedupe_major_intent_payload_across_levels(major_payload),
        _normalize_intent_payload(
            school_intents,
            allowed_keys=_SCHOOL_POSITIVE_KEYS + _SCHOOL_NEGATIVE_KEYS,
        ),
        _normalize_intent_payload(
            city_intents,
            allowed_keys=_CITY_POSITIVE_KEYS + _CITY_NEGATIVE_KEYS,
        ),
        _normalize_intent_payload(
            career_intents,
            allowed_keys=_CAREER_POSITIVE_KEYS + _CAREER_NEGATIVE_KEYS,
        ),
    )


def _restrict_intents_to_recovery_scope(
    major_intents: dict | None,
    school_intents: dict | None,
    city_intents: dict | None,
    career_intents: dict | None,
    *,
    recovery_scope: str | None,
) -> tuple[dict | None, dict | None, dict | None, dict | None]:
    """Keep theme-specific preview tools from carrying unrelated model guesses."""

    normalized_scope = str(recovery_scope or "").strip().lower()
    if normalized_scope == "major":
        return major_intents, None, None, None
    if normalized_scope in {"school", "college"}:
        return None, school_intents, city_intents, None
    if normalized_scope in {"region", "city"}:
        return None, None, city_intents, None
    if normalized_scope == "career_preference":
        return None, None, None, career_intents
    return major_intents, school_intents, city_intents, career_intents


def _merge_intents_from_preview_items(items: Any) -> tuple[dict | None, dict | None, dict | None, dict | None]:
    """Recover structured intent facts from prior preview items/existingItems."""
    merged_major: dict[str, Any] = {}
    merged_school: dict[str, Any] = {}
    merged_city: dict[str, Any] = {}
    merged_career: dict[str, Any] = {}
    if not isinstance(items, list):
        return None, None, None, None

    for item in items:
        if not isinstance(item, dict):
            continue
        value = item.get("value")
        if not isinstance(value, dict):
            continue
        major_payload, school_payload, city_payload, career_payload = _normalize_intent_inputs(
            value.get("major_intents") if isinstance(value.get("major_intents"), dict) else None,
            value.get("school_intents") if isinstance(value.get("school_intents"), dict) else None,
            value.get("city_intents") if isinstance(value.get("city_intents"), dict) else None,
            value.get("career_intents") if isinstance(value.get("career_intents"), dict) else None,
        )
        for target, payload in (
            (merged_major, major_payload),
            (merged_school, school_payload),
            (merged_city, city_payload),
            (merged_career, career_payload),
        ):
            for key, values in (payload or {}).items():
                if not values:
                    continue
                target[key] = _merge_list(target.get(key), _as_string_list(values))

    return (
        _dedupe_major_intent_payload_across_levels(merged_major),
        _drop_empty_entries(merged_school),
        _drop_empty_entries(merged_city),
        _drop_empty_entries(merged_career),
    )


def _recover_intents_from_recent_analysis(
    ctx: RunContext[RequestContext],
    recovery_scope: str | None = None,
) -> tuple[dict | None, dict | None, dict | None, dict | None]:
    recent_payload = getattr(ctx.deps, "recent_intent_analysis", None)
    if not isinstance(recent_payload, dict):
        return None, None, None, None
    items: list[Any] = []
    for key in ("items", "existingItems"):
        raw_items = recent_payload.get(key)
        if isinstance(raw_items, list):
            items.extend(raw_items)
    major, school, city, career = _merge_intents_from_preview_items(items)
    normalized_scope = (recovery_scope or "generic").strip().lower()
    if normalized_scope == "major":
        return major, None, None, None
    if normalized_scope == "school":
        return None, school, None, None
    if normalized_scope in {"region", "city"}:
        return None, None, city, None
    if normalized_scope == "career_preference":
        return None, None, None, career
    return major, school, city, career


async def _normalize_major_intent_names_for_batch(
    major_intents: dict | None,
    batch: str,
) -> dict | None:
    if not major_intents:
        return None
    normalized: dict[str, list[str]] = {}
    for key, values in major_intents.items():
        names = _as_string_list(values)
        if not names:
            continue
        if key in {"level1", "negative_level1"}:
            level = "level1"
        elif key in {"level2", "negative_level2"}:
            level = "level2"
        elif key in {"level3", "negative_level3"}:
            level = "level3"
        else:
            normalized[key] = list(dict.fromkeys(names))
            continue
        try:
            resolved_names = await resolve_major_names_async(names, level, batch)
        except Exception:
            logger.warning("Normalize major intent names failed: key=%s names=%s batch=%s", key, names, batch, exc_info=True)
            resolved_names = names
        normalized[key] = list(dict.fromkeys(resolved_names or names))
    return normalize_major_intent_payload_by_catalog(normalized, batch)


def _should_use_direction_interest_analysis(
    major_intents: dict | None,
    school_intents: dict | None,
    city_intents: dict | None,
    career_intents: dict | None,
    *,
    analysis_stage: str,
    confirm_enabled: bool,
) -> bool:
    if analysis_stage != ANALYSIS_STAGE_INTEREST or confirm_enabled:
        return False
    if major_intents or school_intents or city_intents:
        return False
    if not career_intents:
        return False
    positive = [slot for slot in (career_intents.get("positive") or []) if is_career_slot(slot)]
    negative = career_intents.get("negative") or []
    return bool(positive) and not negative


def _should_attempt_intent_recovery(
    *,
    analysis_stage: str,
    confirm_enabled: bool,
    recovery_scope: str | None,
) -> bool:
    """Recovery only fills missing params for an already-chosen intent path.

    It should not keep acting as a hidden Explore/Intent router.
    """
    if recovery_scope:
        return True
    if confirm_enabled:
        return True
    if analysis_stage != ANALYSIS_STAGE_INTEREST:
        return True
    return False


_LOCAL_MAJOR_POSITIVE_PATTERNS = (
    r"^(?:我)?(?:更)?想学(?P<target>.+)$",
    r"^(?:我)?(?:更)?想读(?P<target>.+)$",
    r"^(?:我)?(?:更)?想报(?P<target>.+)$",
    r"^(?:以后)?(?:更)?优先看(?P<target>.+)$",
    r"^(?P<target>.+?)(?:适合我吗|适不适合我|值不值得继续看|值不值得学)$",
)
_LOCAL_MAJOR_NEGATIVE_PATTERNS = (
    r"^(?:我)?(?:现在)?不想学(?P<target>.+)$",
    r"^(?:我)?(?:现在)?不学(?P<target>.+)$",
    r"^(?:我)?(?:现在)?不考虑(?P<target>.+)$",
    r"^(?:我)?(?:现在)?不要(?P<target>.+)$",
)
_LOCAL_MAJOR_CONTEXT_REFERENCE_PATTERNS = (
    r"(?:这|那)(?:两个|两类)(?:方向|专业)",
    r"(?:这|那)两条路",
)
_LOCAL_MAJOR_CONTEXT_CONFIRM_MARKERS = (
    "作为偏好",
    "都先作为偏好",
    "都可以",
    "都想看",
    "都保留",
    "都纳入",
    "都作为后续参考",
)
_LOCAL_MAJOR_COMPARE_SUFFIX_PATTERNS = (
    r"(?:哪个更适合我|哪个更适合|哪个更值得继续看|哪个更值得学|哪个更好|哪个好)$",
    r"(?:怎么选|怎么兼顾)$",
)
_LOCAL_MAJOR_CLAUSE_SPLIT_PATTERN = re.compile(
    r"[，,。；;！？?!\n]+|(?:但是|但|不过|然后|同时)|\s+(?=排除)|(?<=意向)(?=排除)"
)
_LOCAL_MAJOR_POSITIVE_MARKERS = (
    "加到意向",
    "加入意向",
    "加进意向",
    "记到意向",
    "记进意向",
    "加意向",
    "作为意向",
    "能接受",
    "可以接受",
    "还能接受",
    "可接受",
    "可以",
    "能考虑",
    "可以考虑",
    "考虑",
    "倾向",
    "偏向",
    "偏好",
    "更偏",
    "优先",
    "还行",
    "感兴趣",
    "喜欢",
    "想学",
    "想读",
    "想报",
    "保留",
    "纳入",
)
_LOCAL_MAJOR_NEGATIVE_MARKERS = (
    "别碰",
    "别要",
    "别选",
    "不要",
    "不考虑",
    "不太考虑",
    "不想学",
    "不太想学",
    "不是很想学",
    "不想读",
    "不太想读",
    "不学",
    "不接受",
    "不太接受",
    "不感兴趣",
    "排除",
    "去掉",
    "避开",
)

_LOCAL_MAJOR_READONLY_OR_CLARIFICATION_MARKERS = (
    "是不是",
    "算不算",
    "要不要",
    "能不能",
    "该不该",
    "怎么理解",
    "什么意思",
)


def _refine_major_boundary_mentions(
    payload: dict[str, list[str]] | None,
    utterance: str,
    batch: str,
) -> dict[str, list[str]] | None:
    return _normalize_intent_payload(
        payload,
        allowed_keys=_MAJOR_POSITIVE_KEYS + _MAJOR_NEGATIVE_KEYS,
    )


def _major_relation_notes_from_latest_utterance(
    major_intents: dict[str, Any] | None,
    utterance: str,
    batch: str,
) -> list[str]:
    if not major_intents or not str(utterance or "").strip():
        return []
    mappings = major_parent_mappings_for_batch(batch)
    level2_to_level1 = mappings.get("level2_to_level1", {})
    level3_to_level2 = mappings.get("level3_to_level2", {})
    negative_level1 = set(_as_string_list(major_intents.get("negative_level1")))
    negative_level2 = set(_as_string_list(major_intents.get("negative_level2")))
    negative_level3 = set(_as_string_list(major_intents.get("negative_level3")))

    notes: list[str] = []
    for mention in resolve_major_mentions_from_text(utterance, batch):
        level = mention.level
        name = mention.canonical_name
        if level == "level2":
            parent_level1 = level2_to_level1.get(name)
            if name not in negative_level2 and parent_level1 in negative_level1:
                notes.append(f"{name}属于{parent_level1}门类；如果确认排除{parent_level1}，这个专业类也会一并避开。")
        elif level == "level3":
            parent_level2 = level3_to_level2.get(name)
            parent_level1 = level2_to_level1.get(parent_level2 or "")
            if name in negative_level3:
                continue
            if parent_level2 in negative_level2:
                notes.append(f"{name}属于{parent_level2}；如果确认排除{parent_level2}，这个具体专业也会一并避开。")
            elif parent_level1 in negative_level1:
                notes.append(f"{name}属于{parent_level1}门类；如果确认排除{parent_level1}，这个具体专业也会一并避开。")

    return list(dict.fromkeys(notes))


def _recover_polarity_major_intent_locally_from_latest_utterance(
    utterance: str,
    batch: str,
) -> dict[str, list[str]] | None:
    payload: dict[str, list[str]] = {}
    for raw_clause in _LOCAL_MAJOR_CLAUSE_SPLIT_PATTERN.split(utterance):
        clause = str(raw_clause or "").strip()
        if not clause:
            continue
        if any(marker in clause for marker in _LOCAL_MAJOR_READONLY_OR_CLARIFICATION_MARKERS):
            continue
        has_negative = any(marker in clause for marker in _LOCAL_MAJOR_NEGATIVE_MARKERS)
        has_positive = any(marker in clause for marker in _LOCAL_MAJOR_POSITIVE_MARKERS)
        if has_negative == has_positive:
            continue
        mentions = resolve_major_mentions_from_text(clause, batch)
        if not mentions:
            continue
        append_major_mentions_to_payload(payload, mentions, negative=has_negative)
        _supplement_broad_major_mentions_to_payload(payload, clause, batch, negative=has_negative)
    return _refine_major_boundary_mentions(_drop_empty_entries(payload), utterance, batch)


def _supplement_broad_major_mentions_to_payload(
    payload: dict[str, list[str]],
    clause: str,
    batch: str,
    *,
    negative: bool,
) -> None:
    """Keep user-facing representative majors for broad aliases like 财会.

    The shared mention resolver intentionally collapses broad aliases to a
    category to avoid over-specific matching globally. Intent/explore replies,
    however, need the representative concrete majors so the user can understand
    what the alias means.
    """
    from app.data.major_aliases import COMMON_MAJOR_ALIAS_TABLE

    compact_clause = "".join(str(clause or "").split()).lower()
    if not compact_clause:
        return
    available = major_name_sets_for_batch(batch)
    key = "negative_level3" if negative else "level3"
    bucket = payload.setdefault(key, [])
    for alias, aliases_by_level in COMMON_MAJOR_ALIAS_TABLE.items():
        compact_alias = "".join(str(alias or "").split()).lower()
        if not compact_alias or compact_alias not in compact_clause:
            continue
        level3_candidates = [
            name
            for name in aliases_by_level.get("level3", ())
            if name in available.get("level3", set())
        ]
        if len(level3_candidates) <= 1:
            continue
        level2_key = "negative_level2" if negative else "level2"
        level2_candidates = set(aliases_by_level.get("level2", ()))
        if level2_candidates and payload.get(level2_key):
            payload[level2_key] = [
                name for name in payload[level2_key] if name not in level2_candidates
            ]
            if not payload[level2_key]:
                payload.pop(level2_key, None)
        for name in level3_candidates:
            if name not in bucket:
                bucket.append(name)


def _count_major_payload_values(payload: dict[str, Any] | None) -> int:
    if not payload:
        return 0
    return sum(len(_as_string_list(values)) for values in payload.values())


def _has_positive_major_values(payload: dict[str, Any] | None) -> bool:
    return any(_as_string_list((payload or {}).get(level)) for level in ("level1", "level2", "level3"))


def _has_negative_major_values(payload: dict[str, Any] | None) -> bool:
    return any(_as_string_list((payload or {}).get(f"negative_{level}")) for level in ("level1", "level2", "level3"))


def _should_replace_major_intents_with_local_payload(
    existing: dict[str, Any] | None,
    local_payload: dict[str, Any] | None,
) -> bool:
    if not _has_non_empty_payload(local_payload):
        return False
    if not _has_non_empty_payload(existing):
        return True

    local_has_positive = _has_positive_major_values(local_payload)
    local_has_negative = _has_negative_major_values(local_payload)
    existing_has_positive = _has_positive_major_values(existing)
    existing_has_negative = _has_negative_major_values(existing)
    if local_has_positive and not existing_has_positive:
        return True
    if local_has_negative and not existing_has_negative:
        return True

    existing_count = _count_major_payload_values(existing)
    local_count = _count_major_payload_values(local_payload)
    existing_negative_level3 = _as_string_list((existing or {}).get("negative_level3"))
    if existing_count > max(12, local_count * 4):
        return True
    if existing_negative_level3 and len(existing_negative_level3) > 10 and _as_string_list((existing or {}).get("negative_level1")):
        return True
    return False


def _merge_major_intent_payloads(
    base: dict[str, Any] | None,
    supplement: dict[str, Any] | None,
) -> dict[str, list[str]] | None:
    merged: dict[str, list[str]] = {}
    for payload in (base or {}, supplement or {}):
        for key, values in payload.items():
            normalized_values = _as_string_list(values)
            if not normalized_values:
                continue
            bucket = merged.setdefault(key, [])
            for value in normalized_values:
                if value not in bucket:
                    bucket.append(value)
    return _dedupe_major_intent_payload_across_levels(merged)


def _refine_major_intents_with_local_latest_utterance(
    major_intents: dict[str, Any] | None,
    *,
    latest_utterance: str,
    batch: str,
    recovery_scope: str | None,
) -> dict[str, Any] | None:
    if (recovery_scope or "").strip().lower() != "major":
        return major_intents
    local_payload = _recover_polarity_major_intent_locally_from_latest_utterance(latest_utterance, batch)
    if _should_replace_major_intents_with_local_payload(major_intents, local_payload):
        logger.info(
            "Major intents refined from latest utterance local recovery: existing_count=%s local=%s",
            _count_major_payload_values(major_intents),
            local_payload,
        )
        return local_payload
    merged_payload = _merge_major_intent_payloads(major_intents, local_payload)
    if merged_payload != major_intents:
        logger.info(
            "Major intents supplemented from latest utterance local recovery: existing_count=%s local=%s",
            _count_major_payload_values(major_intents),
            local_payload,
        )
    return merged_payload


def _cleanup_local_major_target(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r'^[“"《<【\[]+', "", text)
    text = re.sub(r'[”"》>\]】]+$', "", text)
    text = re.sub(r"(这个方向|这个专业|这类专业)$", "", text).strip()
    return text


async def _resolve_single_major_target_locally(target: str, batch: str) -> tuple[str, str] | None:
    cleaned = _cleanup_local_major_target(target)
    if not cleaned:
        return None
    if any(token in cleaned for token in ("和", "、", "/", "以及", "或")):
        return None

    levels = ("level2", "level3", "level1") if "类" in cleaned else ("level3", "level2", "level1")
    for level in levels:
        try:
            resolved_names = await resolve_major_names_async([cleaned], level, batch)
        except Exception:
            logger.warning("Local major target resolve failed: target=%s level=%s batch=%s", cleaned, level, batch, exc_info=True)
            continue
        if not resolved_names:
            continue
        resolved_name = resolved_names[0]
        try:
            codes = await get_major_codes_async([resolved_name], level, batch)
        except Exception:
            logger.warning("Local major target code lookup failed: target=%s resolved=%s level=%s batch=%s", cleaned, resolved_name, level, batch, exc_info=True)
            codes = get_major_codes([resolved_name], level, batch)
        if codes:
            return level, resolved_name
    return None


async def _recover_major_intent_locally_from_latest_utterance(
    ctx: RunContext[RequestContext],
    batch: str,
) -> dict[str, list[str]] | None:
    utterance = _latest_user_utterance(ctx).strip()
    if not utterance:
        return None

    polarity_payload = _recover_polarity_major_intent_locally_from_latest_utterance(utterance, batch)
    if polarity_payload:
        return polarity_payload

    for pattern in _LOCAL_MAJOR_NEGATIVE_PATTERNS:
        match = re.match(pattern, utterance)
        if not match:
            continue
        resolved = await _resolve_single_major_target_locally(match.group("target"), batch)
        if resolved is None:
            return None
        _, name = resolved
        return {"negative_level3": [name]}

    for pattern in _LOCAL_MAJOR_POSITIVE_PATTERNS:
        match = re.match(pattern, utterance)
        if not match:
            continue
        resolved = await _resolve_single_major_target_locally(match.group("target"), batch)
        if resolved is None:
            return None
        level, name = resolved
        return {level: [name]}

    return None


def _iter_prior_user_utterances(ctx: RunContext[RequestContext]) -> list[str]:
    history = list(getattr(ctx.deps, "chat_history", []) or [])
    utterances = [
        str(item.get("content", "")).strip()
        for item in history
        if isinstance(item, dict) and item.get("role") == "user" and str(item.get("content", "")).strip()
    ]
    current = _latest_user_utterance(ctx).strip()
    if utterances and current and utterances[-1] == current:
        utterances.pop()
    return utterances


def _looks_like_major_context_reference(utterance: str) -> bool:
    normalized = str(utterance or "").strip()
    if not normalized:
        return False
    return (
        any(re.search(pattern, normalized) for pattern in _LOCAL_MAJOR_CONTEXT_REFERENCE_PATTERNS)
        and any(marker in normalized for marker in _LOCAL_MAJOR_CONTEXT_CONFIRM_MARKERS)
    )


def _extract_major_targets_from_compare_utterance(utterance: str) -> list[str]:
    text = str(utterance or "").strip().strip("。！？?!")
    if not text:
        return []
    for pattern in _LOCAL_MAJOR_COMPARE_SUFFIX_PATTERNS:
        text = re.sub(pattern, "", text).strip()
    parts = [
        _cleanup_local_major_target(part)
        for part in re.split(r"(?:和|跟|、|/|以及)", text)
    ]
    parts = [part for part in parts if part]
    if len(parts) < 2:
        return []
    return parts[:4]


async def _recover_major_intent_from_recent_context(
    ctx: RunContext[RequestContext],
    batch: str,
) -> dict[str, list[str]] | None:
    current = _latest_user_utterance(ctx).strip()
    if not _looks_like_major_context_reference(current):
        return None

    for previous in reversed(_iter_prior_user_utterances(ctx)):
        targets = _extract_major_targets_from_compare_utterance(previous)
        if len(targets) < 2:
            continue

        resolved_payload: dict[str, list[str]] = {}
        for target in targets:
            resolved = await _resolve_single_major_target_locally(target, batch)
            if resolved is None:
                resolved_payload = {}
                break
            level, name = resolved
            bucket = resolved_payload.setdefault(level, [])
            if name not in bucket:
                bucket.append(name)

        if sum(len(values) for values in resolved_payload.values()) >= 2:
            return resolved_payload
    return None


def _move_region_like_school_values_to_city_intents(
    school_payload: dict[str, Any],
    city_payload: dict[str, Any],
) -> dict[str, Any]:
    """Move province/city names accidentally extracted as schools into region intents."""

    cleaned_school: dict[str, list[str]] = {}
    for school_key, negative in (("colleges", False), ("negative_colleges", True)):
        kept: list[str] = []
        for value in _as_string_list(school_payload.get(school_key)):
            resolved = resolve_region_entity(value)
            region = resolved.best
            if region and region.level in {"province", "city"}:
                target_key = f"{'negative_' if negative else ''}{region.level}"
                bucket = city_payload.setdefault(target_key, [])
                if region.canonical_name not in bucket:
                    bucket.append(region.canonical_name)
                continue
            kept.append(value)
        if kept:
            cleaned_school[school_key] = kept
    return cleaned_school


def _merge_city_intent_payloads(
    base: dict[str, Any] | None,
    supplement: dict[str, Any] | None,
) -> dict[str, list[str]] | None:
    merged: dict[str, list[str]] = {}
    for payload in (base or {}, supplement or {}):
        for key, values in payload.items():
            normalized_values = _as_string_list(values)
            if not normalized_values:
                continue
            bucket = merged.setdefault(key, [])
            for value in normalized_values:
                if value not in bucket:
                    bucket.append(value)
    return merged or None


def _drop_provinces_implied_by_area_alias(
    city_payload: dict[str, Any],
    *,
    local_area_payload: dict[str, list[str]],
    latest_utterance: str,
) -> dict[str, Any]:
    if not local_area_payload:
        return city_payload
    cleaned = {key: list(_as_string_list(value)) for key, value in city_payload.items()}
    compact_utterance = compact_region_text(latest_utterance)
    for area_key, province_key in (("area", "province"), ("negative_area", "negative_province")):
        areas = _as_string_list(local_area_payload.get(area_key))
        if not areas:
            continue
        implied = {
            province
            for area in areas
            for province in REGION_AREA_PROVINCES.get(area, ())
            if compact_region_text(province) not in compact_utterance
        }
        if implied and cleaned.get(province_key):
            cleaned[province_key] = [
                province for province in cleaned[province_key] if province not in implied
            ]
            if not cleaned[province_key]:
                cleaned.pop(province_key, None)
    return cleaned


_REGION_AREA_EXPLICIT_ALIASES: dict[str, tuple[str, ...]] = {
    "南方": ("南方", "南方地区", "南边"),
    "北方": ("北方", "北方地区", "北边"),
    "华东": ("华东", "华东地区", "江浙沪", "长三角", "江浙", "江南"),
    "华北": ("华北", "华北地区", "京津冀", "北京周边", "环京地区"),
    "华中": ("华中", "华中地区", "中南"),
    "华南": ("华南", "华南地区"),
    "东北": ("东北", "东北地区", "东三省"),
    "西南": ("西南", "西南地区"),
    "西北": ("西北", "西北地区"),
    "东南": ("东南", "东南地区"),
    "中南": ("中南", "中南地区"),
    "偏远地区": ("偏远地区", "偏远", "边远地区"),
    "北上广": ("北上广",),
    "北上广深": ("北上广深",),
}


def _region_area_explicitly_mentioned(value: str, latest_utterance: str) -> bool:
    compact_utterance = compact_region_text(latest_utterance)
    if not compact_utterance:
        return False
    compact_value = compact_region_text(value)
    if compact_value and compact_value in compact_utterance:
        return True
    aliases = _REGION_AREA_EXPLICIT_ALIASES.get(str(value or "").strip(), ())
    return any(compact_region_text(alias) in compact_utterance for alias in aliases if str(alias or "").strip())


def _explicit_region_areas_from_utterance(latest_utterance: str) -> list[str]:
    areas: list[str] = []
    for area in _REGION_AREA_EXPLICIT_ALIASES:
        if _region_area_explicitly_mentioned(area, latest_utterance) and area not in areas:
            areas.append(area)
    return areas


def _recover_explicit_region_area_from_implied_provinces(
    city_payload: dict[str, Any],
    *,
    latest_utterance: str,
) -> dict[str, Any]:
    """Recover abstract region groups when the model only passed implied provinces.

    For utterances like "只去南方，北方先别考虑", the model may put several
    southern / northern provinces into province buckets instead of using the
    area fields. Preserve the user's level of abstraction for confirmation and
    downstream goal construction, while keeping provinces that the user named
    explicitly.
    """

    if not city_payload:
        return city_payload
    explicit_areas = _explicit_region_areas_from_utterance(latest_utterance)
    if not explicit_areas:
        return city_payload

    recovered = {key: list(_as_string_list(value)) for key, value in city_payload.items()}
    for area in explicit_areas:
        implied = set(REGION_AREA_PROVINCES.get(area, ()))
        if not implied:
            continue
        for area_key, province_key in (("area", "province"), ("negative_area", "negative_province")):
            province_values = set(_as_string_list(recovered.get(province_key)))
            if not province_values.intersection(implied):
                continue
            area_bucket = recovered.setdefault(area_key, [])
            if area not in area_bucket:
                area_bucket.append(area)
            recovered = _drop_provinces_implied_by_area_alias(
                recovered,
                local_area_payload={area_key: [area]},
                latest_utterance=latest_utterance,
            )
    return recovered


def _prune_inferred_region_area_values(
    city_payload: dict[str, Any],
    *,
    latest_utterance: str,
) -> dict[str, Any]:
    if not city_payload:
        return city_payload
    cleaned = {key: list(_as_string_list(value)) for key, value in city_payload.items()}
    for key in ("area", "negative_area"):
        values = _as_string_list(cleaned.get(key))
        kept = [value for value in values if _region_area_explicitly_mentioned(value, latest_utterance)]
        if kept:
            cleaned[key] = kept
        else:
            cleaned.pop(key, None)
    return cleaned


def _normalize_region_area_values_from_extractor(
    payload: dict[str, Any] | None,
) -> dict[str, list[str]]:
    """Normalize extractor-decided region polarity without re-inferring intent.

    The model/extractor owns whether a region mention is positive or negative.
    This helper only canonicalizes abstract region groups such as 南方/北方 into
    area fields, so cards remain readable and do not list many implied provinces.
    """

    normalized: dict[str, list[str]] = {}
    for key, values in (payload or {}).items():
        for value in _as_string_list(values):
            resolved = resolve_region_entity(value)
            region = resolved.best
            target_key = key
            target_value = value
            if region and region.level == "area":
                target_key = "area" if not str(key).startswith("negative_") else "negative_area"
                target_value = region.canonical_name
            bucket = normalized.setdefault(target_key, [])
            if target_value not in bucket:
                bucket.append(target_value)
    return normalized


def _normalize_region_area_polarity_payloads(
    positive_payload: dict[str, Any],
    negative_payload: dict[str, Any],
    *,
    latest_utterance: str,
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    positive = _normalize_region_area_values_from_extractor(positive_payload)
    negative = _normalize_region_area_values_from_extractor(
        {f"negative_{key}" if not str(key).startswith("negative_") else key: value for key, value in negative_payload.items()}
    )
    positive = _recover_explicit_region_area_from_implied_provinces(
        positive,
        latest_utterance=latest_utterance,
    )
    negative = _recover_explicit_region_area_from_implied_provinces(
        negative,
        latest_utterance=latest_utterance,
    )
    positive = _prune_inferred_region_area_values(positive, latest_utterance=latest_utterance)
    negative = _prune_inferred_region_area_values(negative, latest_utterance=latest_utterance)
    area_payload = {
        "area": positive.get("area", []),
        "negative_area": negative.get("negative_area", []),
    }
    if area_payload["area"] or area_payload["negative_area"]:
        positive = _drop_provinces_implied_by_area_alias(
            positive,
            local_area_payload={"area": area_payload["area"]},
            latest_utterance=latest_utterance,
        )
        negative = _drop_provinces_implied_by_area_alias(
            negative,
            local_area_payload={"negative_area": area_payload["negative_area"]},
            latest_utterance=latest_utterance,
        )
    return positive, negative


async def _recover_intents_from_context(
    ctx: RunContext[RequestContext],
    recovery_scope: str | None = None,
) -> tuple[dict | None, dict | None, dict | None, dict | None]:
    """Best-effort recovery when the model calls intent analysis with empty params."""
    from app.tools.career_intent_tool import extract_career_intent
    from app.tools.city_intent_tool import (
        extract_city_intent,
        extract_city_intents_with_polarity,
        extract_negative_city_intent,
    )
    from app.tools.major_intent_tool import (
        extract_major_intent,
        extract_major_intents_with_polarity,
        extract_negative_major_intent,
    )
    from app.tools.school_intent_tool import extract_school_intent

    recovered_major: dict[str, Any] = {}
    recovered_school: dict[str, Any] = {}
    recovered_city: dict[str, Any] = {}
    recovered_career: dict[str, Any] = {}
    recovery_ctx = _build_single_turn_recovery_context(ctx)
    normalized_scope = (recovery_scope or "generic").strip().lower()
    batch = ctx.deps.batch or "01"
    latest_utterance = _latest_user_utterance(ctx)
    school_scope = normalized_scope in {"school", "college"}

    if normalized_scope == "career_preference":
        extracted_career = json.loads(await extract_career_intent(recovery_ctx))
        if _has_non_empty_payload(extracted_career):
            recovered_career.update(extracted_career)
        return None, None, None, _drop_empty_entries(recovered_career)

    if school_scope:
        try:
            school = json.loads(await extract_school_intent(recovery_ctx))
            if school.get("colleges"):
                recovered_school["colleges"] = school["colleges"]
            if school.get("negative_colleges"):
                recovered_school["negative_colleges"] = school["negative_colleges"]
            recovered_school = _move_region_like_school_values_to_city_intents(
                recovered_school,
                recovered_city,
            )
        except Exception:
            logger.warning("Fallback school intent extraction failed: session_id=%s", ctx.deps.sessionid, exc_info=True)

    if normalized_scope in {"generic", "region", "city"} or (
        school_scope and not recovered_school and not recovered_city and contains_concrete_region_mention(latest_utterance)
    ):
        try:
            try:
                city_polarity = json.loads(await extract_city_intents_with_polarity(recovery_ctx))
                positive_city = city_polarity.get("positive") or {}
                negative_city = city_polarity.get("negative") or {}
            except Exception:
                logger.warning(
                    "Combined city intent recovery failed, falling back to separate extractors: session_id=%s",
                    ctx.deps.sessionid,
                    exc_info=True,
                )
                positive_city = json.loads(await extract_city_intent(recovery_ctx))
                negative_city = json.loads(await extract_negative_city_intent(recovery_ctx))
            positive_city, negative_city = _normalize_region_area_polarity_payloads(
                positive_city,
                negative_city,
                latest_utterance=latest_utterance,
            )
            for key in ("province", "city", "area"):
                values = positive_city.get(key, [])
                if values:
                    recovered_city[key] = values
            for key in ("province", "city", "area"):
                values = negative_city.get(f"negative_{key}") or negative_city.get(key, [])
                if values:
                    recovered_city[f"negative_{key}"] = values
        except Exception:
            logger.warning("Fallback city intent extraction failed: session_id=%s", ctx.deps.sessionid, exc_info=True)

    if normalized_scope in {"generic", "major"}:
        try:
            local_major = await _recover_major_intent_from_recent_context(ctx, batch)
            if not local_major:
                local_major = await _recover_major_intent_locally_from_latest_utterance(ctx, batch)
            if local_major:
                recovered_major.update(local_major)
            else:
                try:
                    major_polarity = json.loads(await extract_major_intents_with_polarity(recovery_ctx))
                    positive_major = major_polarity.get("positive") or {}
                    negative_major = major_polarity.get("negative") or {}
                except Exception:
                    logger.warning(
                        "Combined major intent recovery failed, falling back to separate extractors: session_id=%s",
                        ctx.deps.sessionid,
                        exc_info=True,
                    )
                    positive_major = json.loads(await extract_major_intent(recovery_ctx))
                    negative_major = json.loads(await extract_negative_major_intent(recovery_ctx))
                for key in ("level1", "level2", "level3"):
                    values = positive_major.get(key, [])
                    if values:
                        recovered_major[key] = values
                for key in ("level1", "level2", "level3"):
                    values = negative_major.get(key, [])
                    if values:
                        recovered_major[f"negative_{key}"] = values
        except Exception:
            logger.warning("Fallback major intent extraction failed: session_id=%s", ctx.deps.sessionid, exc_info=True)

    if normalized_scope == "generic" and not recovered_school:
        try:
            school = json.loads(await extract_school_intent(recovery_ctx))
            if school.get("colleges"):
                recovered_school["colleges"] = school["colleges"]
            if school.get("negative_colleges"):
                recovered_school["negative_colleges"] = school["negative_colleges"]
            recovered_school = _move_region_like_school_values_to_city_intents(
                recovered_school,
                recovered_city,
            )
        except Exception:
            logger.warning("Fallback school intent extraction failed: session_id=%s", ctx.deps.sessionid, exc_info=True)

    if normalized_scope == "generic":
        try:
            extracted_career = json.loads(await extract_career_intent(recovery_ctx))
            if _has_non_empty_payload(extracted_career):
                recovered_career.update(extracted_career)
        except Exception:
            logger.warning("Fallback career intent extraction failed: session_id=%s", ctx.deps.sessionid, exc_info=True)

    major = recovered_major or None
    school = recovered_school or None
    city = recovered_city or None
    career = _drop_empty_entries(recovered_career)
    if not _has_any_intent_payload(major, school, city, career):
        major, school, city, career = _recover_intents_from_recent_analysis(ctx, recovery_scope=recovery_scope)
        if _has_any_intent_payload(major, school, city, career):
            logger.info(
                "Recovered intents from recent structured intent analysis: session_id=%s recovery_scope=%s",
                ctx.deps.sessionid,
                recovery_scope,
            )
    if school_scope and city:
        return None, school, city, None
    return _restrict_intents_to_recovery_scope(
        major,
        school,
        city,
        career,
        recovery_scope=recovery_scope,
    )


async def _refresh_recommendation_overlay_best_effort(session_id: str) -> bool:
    """Trigger backend recommendation overlay refresh after intent changes.

    The backend refreshes the overlay from candidate-pool query when its stale
    flag is set. This keeps current ordered plan untouched and only refreshes
    recommendation/candidate scoring data.
    """
    try:
        resp = await query_planning_candidate_pool(
            1,
            int(session_id),
            page=1,
            page_size=1,
            sort_field="finalScore",
            sort_order="desc",
        )
        success = isinstance(resp, dict) and (
            resp.get("code") in {0, "0"} or resp.get("success") is True
        )
        logger.info(
            "Intent recommendation overlay refresh triggered: session_id=%s success=%s",
            session_id,
            success,
        )
        return success
    except Exception:
        logger.warning(
            "Intent recommendation overlay refresh failed: session_id=%s",
            session_id,
            exc_info=True,
        )
        return False


async def _mark_intent_change_stale_best_effort(session_id: str, intent_mode: str) -> bool:
    try:
        resp = await mark_planning_intent_change_stale(int(session_id), intent_mode)
        success = isinstance(resp, dict) and (
            resp.get("code") in {0, "0"} or resp.get("success") is True
        )
        logger.info(
            "Intent planning stale flags marked: session_id=%s intent_mode=%s success=%s",
            session_id,
            intent_mode,
            success,
        )
        return success
    except Exception:
        logger.warning(
            "Intent planning stale flag mark failed: session_id=%s intent_mode=%s",
            session_id,
            intent_mode,
            exc_info=True,
        )
        return False


def _constraint_state_preference_payloads(
    merged: dict[str, Any],
) -> tuple[dict[str, list[str]] | None, dict[str, list[str]] | None, dict[str, list[str]] | None]:
    major_intents = merged.get("major_intents") if isinstance(merged.get("major_intents"), dict) else {}
    school_intents = merged.get("school_intents") if isinstance(merged.get("school_intents"), dict) else {}
    city_intents = merged.get("city_intents") if isinstance(merged.get("city_intents"), dict) else {}

    major_positive = _as_string_list(major_intents.get("level1")) + _as_string_list(major_intents.get("level2")) + _as_string_list(major_intents.get("level3"))
    major_negative = _as_string_list(major_intents.get("negative_level1")) + _as_string_list(major_intents.get("negative_level2")) + _as_string_list(major_intents.get("negative_level3"))
    school_positive = _as_string_list(school_intents.get("colleges"))
    school_negative = _as_string_list(school_intents.get("negative_colleges"))
    region_positive = (
        _as_string_list(city_intents.get("province"))
        + _as_string_list(city_intents.get("city"))
        + _as_string_list(city_intents.get("area"))
    )
    region_negative = (
        _as_string_list(city_intents.get("negative_province"))
        + _as_string_list(city_intents.get("negative_city"))
        + _as_string_list(city_intents.get("negative_area"))
    )

    def group(positive: list[str], negative: list[str]) -> dict[str, list[str]] | None:
        payload = {
            "positive": list(dict.fromkeys(value for value in positive if value)),
            "negative": list(dict.fromkeys(value for value in negative if value)),
        }
        return payload if payload["positive"] or payload["negative"] else None

    return (
        group(major_positive, major_negative),
        group(school_positive, school_negative),
        group(region_positive, region_negative),
    )


def _split_constraint_state_payload_by_polarity(
    merged: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split one mixed intent payload into positive and negative planning-state payloads."""

    positive: dict[str, Any] = {}
    negative: dict[str, Any] = {}

    def put(target: dict[str, Any], section: str, key: str, values: Any) -> None:
        normalized = _as_string_list(values)
        if not normalized:
            return
        bucket = target.setdefault(section, {})
        bucket[key] = normalized

    major_intents = merged.get("major_intents") if isinstance(merged.get("major_intents"), dict) else {}
    for key in ("level1", "level2", "level3"):
        put(positive, "major_intents", key, major_intents.get(key))
    for key in ("negative_level1", "negative_level2", "negative_level3"):
        put(negative, "major_intents", key, major_intents.get(key))

    school_intents = merged.get("school_intents") if isinstance(merged.get("school_intents"), dict) else {}
    put(positive, "school_intents", "colleges", school_intents.get("colleges"))
    put(negative, "school_intents", "negative_colleges", school_intents.get("negative_colleges"))

    city_intents = merged.get("city_intents") if isinstance(merged.get("city_intents"), dict) else {}
    for key in ("province", "city", "area"):
        put(positive, "city_intents", key, city_intents.get(key))
    for key in ("negative_province", "negative_city", "negative_area"):
        put(negative, "city_intents", key, city_intents.get(key))

    return positive, negative


def _physical_special_limits_from_payload(payload: dict[str, Any] | None) -> list[str]:
    if not isinstance(payload, dict):
        return []
    physical = payload.get("physical_constraints") or payload.get("physicalConstraints")
    if not isinstance(physical, dict):
        return []
    raw_values = (
        physical.get("special_limits")
        if "special_limits" in physical
        else physical.get("specialLimits")
    )
    values = _as_string_list(raw_values)
    return list(dict.fromkeys(value for value in values if value))


async def _sync_constraint_state_best_effort(
    *,
    session_id: str,
    merged: dict[str, Any],
    intent_mode: str,
) -> bool:
    payloads_by_mode: list[tuple[str, dict[str, Any]]] = []
    if (
        intent_mode == INTENT_MODE_CONSTRAINT
        and _has_positive_intents(
            merged.get("major_intents"),
            merged.get("school_intents"),
            merged.get("city_intents"),
            merged.get("career_intents"),
        )
        and _has_negative_intents(
            merged.get("major_intents"),
            merged.get("school_intents"),
            merged.get("city_intents"),
            merged.get("career_intents"),
        )
    ):
        positive_payload, negative_payload = _split_constraint_state_payload_by_polarity(merged)
        if positive_payload:
            payloads_by_mode.append((INTENT_MODE_PREFERENCE, positive_payload))
        if negative_payload:
            payloads_by_mode.append((INTENT_MODE_CONSTRAINT, negative_payload))
    else:
        payloads_by_mode.append((intent_mode, merged))

    success = True
    synced_any = False
    for sync_mode, sync_payload in payloads_by_mode:
        major_preferences, school_preferences, region_preferences = _constraint_state_preference_payloads(sync_payload)
        if not any((major_preferences, school_preferences, region_preferences)):
            continue
        synced_any = True
        try:
            resp = await update_planning_constraint_state(
                session_id,
                intent_mode=sync_mode,
                major_preferences=major_preferences,
                school_preferences=school_preferences,
                region_preferences=region_preferences,
            )
            success = success and isinstance(resp, dict) and (resp.get("code") in {0, "0"} or resp.get("success") is True)
        except Exception:
            success = False
            logger.warning(
                "Intent constraint state sync failed: session_id=%s intent_mode=%s",
                session_id,
                sync_mode,
                exc_info=True,
            )
    if not synced_any:
        success = True
    special_limits = _physical_special_limits_from_payload(merged)
    if special_limits:
        try:
            resp = await update_planning_physical_constraints(
                session_id,
                special_limits=special_limits,
            )
            success = success and isinstance(resp, dict) and (resp.get("code") in {0, "0"} or resp.get("success") is True)
        except Exception:
            success = False
            logger.warning(
                "Intent physical constraints sync failed: session_id=%s",
                session_id,
                exc_info=True,
            )
    return success


async def _apply_intents(
    *,
    session_id: str,
    batch: str,
    merged: dict[str, Any],
    intent_mode: str,
    constraint_intent_type: str = CONSTRAINT_INTENT_DEFAULT,
) -> IntentStateUpdateResult:
    constraint_intent_type = _normalize_constraint_type_for_payload(constraint_intent_type, merged)
    pm = ProfileManager(int(session_id), batch)

    major_intents = merged.get("major_intents")
    if major_intents:
        if intent_mode == INTENT_MODE_CONSTRAINT and constraint_intent_type == CONSTRAINT_INTENT_ONLY_KEEP:
            await pm.replace_major_positive_intent(json.dumps(major_intents))
        else:
            await pm.update_major_intent(json.dumps(major_intents))

    school_intents = merged.get("school_intents")
    if school_intents:
        await pm.update_school_intent(json.dumps(school_intents))

    city_intents = merged.get("city_intents")
    if city_intents:
        positive = {
            "province": city_intents.get("province", []),
            "city": city_intents.get("city", []),
            "area": city_intents.get("area", []),
        }
        negative = {
            "province": city_intents.get("negative_province", []),
            "city": city_intents.get("negative_city", []),
            "area": city_intents.get("negative_area", []),
        }
        await pm.update_city_intent(json.dumps(positive), json.dumps(negative))

    career_intents = merged.get("career_intents")
    if career_intents:
        planning_state_resp = await get_planning_state(int(session_id))
        planning_state = (planning_state_resp or {}).get("data") or {}
        latent_profile = ((planning_state.get("profileState") or {}).get("latentProfile")) or {}
        future_development = dict(latent_profile.get("futureDevelopment") or {})
        existing_career_types = list(future_development.get("careerTypes") or [])
        positive_labels = to_career_labels(career_intents.get("positive"))
        negative_labels = to_career_labels(career_intents.get("negative"))
        merged_career_types = [value for value in existing_career_types if value not in set(negative_labels)]
        for label in positive_labels:
            if label not in merged_career_types:
                merged_career_types.append(label)
        future_development["careerTypes"] = merged_career_types
        await update_planning_latent_profile(int(session_id), future_development=future_development)

    constraint_state_sync_success = await _sync_constraint_state_best_effort(
        session_id=session_id,
        merged=merged,
        intent_mode=intent_mode,
    )
    try:
        session_id_int = int(str(session_id).strip())
    except (TypeError, ValueError):
        session_id_int = None
    if session_id_int is not None:
        await save_intent_change_cache(session_id_int, {})

    if intent_mode == INTENT_MODE_CONSTRAINT:
        stale_mark_success = await _mark_intent_change_stale_best_effort(session_id, intent_mode)
        recommendation_refresh_success = await _refresh_recommendation_overlay_best_effort(session_id)
        logger.info("Constraint intents applied without regenerating candidate pool: session_id=%s", session_id)
        result = IntentStateUpdateResult(
            action="apply",
            sessionId=session_id,
            intentMode=intent_mode,
            constraintIntentType=constraint_intent_type,
            applied=True,
            messageCode="constraint_applied",
            merged=merged,
            recommendationRefresh={
                "triggered": True,
                "success": recommendation_refresh_success,
                "mode": "overlay_best_effort",
                "staleMarked": stale_mark_success,
                "constraintStateSynced": constraint_state_sync_success,
            },
        )
        result.message = render_intent_state_update(result)
        return result

    stale_mark_success = await _mark_intent_change_stale_best_effort(session_id, intent_mode)
    recommendation_refresh_success = await _refresh_recommendation_overlay_best_effort(session_id)
    logger.info("Preference intents applied: session_id=%s", session_id)
    result = IntentStateUpdateResult(
        action="apply",
        sessionId=session_id,
        intentMode=intent_mode,
        constraintIntentType=constraint_intent_type,
        applied=True,
        messageCode="preference_applied",
        merged=merged,
        recommendationRefresh={
            "triggered": True,
            "success": recommendation_refresh_success,
            "mode": "overlay_best_effort",
            "staleMarked": stale_mark_success,
            "constraintStateSynced": constraint_state_sync_success,
        },
    )
    result.message = render_intent_state_update(result)
    return result


async def analyze_volunteer_intent_change(
    ctx: RunContext[RequestContext],
    major_intents: dict | None = None,
    school_intents: dict | None = None,
    city_intents: dict | None = None,
    edit_flag: str | None = None,
    analysis_stage: str = ANALYSIS_STAGE_CONFIRMED,
    career_intents: dict | None = None,
    recovery_scope: str | None = None,
    confirm_enabled: bool = True,
    intent_mode: str | None = None,
    constraint_intent_type: str | None = None,
) -> str:
    """Analyze intent changes and return structured facts as JSON.

    This tool only prepares structured analysis data.
    It does not execute profile/planning updates.
    Do not use it for read-only fit questions like "电子信息工程适合我吗" or
    "网络与新媒体适不适合我" unless you are intentionally asking for interest-stage
    analysis with no state persistence.
    """
    session_id = ctx.deps.sessionid
    batch = ctx.deps.batch or "01"
    resolved_constraint_intent_type = _normalize_constraint_intent_type(constraint_intent_type)
    logger.info(
        "analyze_volunteer_intent_change: session_id=%s, majors=%s, schools=%s, cities=%s, edit_flag=%s, recovery_scope=%s",
        session_id, major_intents, school_intents, city_intents, edit_flag, recovery_scope,
    )

    latest_utterance = _latest_user_utterance(ctx)
    if _is_read_only_fit_question(latest_utterance):
        if analysis_stage != ANALYSIS_STAGE_INTEREST or confirm_enabled:
            logger.info(
                "analyze_volunteer_intent_change coercing fit question to read-only interest analysis: session_id=%s utterance=%s",
                session_id,
                latest_utterance,
            )
        analysis_stage = ANALYSIS_STAGE_INTEREST
        confirm_enabled = False

    major_intents, school_intents, city_intents, career_intents = _normalize_intent_inputs(
        major_intents,
        school_intents,
        city_intents,
        career_intents,
    )
    major_intents, school_intents, city_intents, career_intents = _restrict_intents_to_recovery_scope(
        major_intents,
        school_intents,
        city_intents,
        career_intents,
        recovery_scope=recovery_scope,
    )
    major_intents = _refine_major_intents_with_local_latest_utterance(
        major_intents,
        latest_utterance=latest_utterance,
        batch=batch,
        recovery_scope=recovery_scope,
    )
    major_intents = await _normalize_major_intent_names_for_batch(major_intents, batch)
    major_intents = _refine_major_intents_by_explicit_mentions(
        major_intents,
        latest_utterance=latest_utterance,
        batch=batch,
    )
    major_intents = _remove_unstated_positive_major_conflicts(
        major_intents,
        latest_utterance=latest_utterance,
        batch=batch,
    )
    if resolved_constraint_intent_type == CONSTRAINT_INTENT_ONLY_KEEP:
        major_intents = _prune_generated_negative_complements_for_only_keep(
            major_intents,
            latest_utterance=latest_utterance,
            batch=batch,
        )
    had_explicit_intent_payload = _has_any_intent_payload(major_intents, school_intents, city_intents, career_intents)

    if not had_explicit_intent_payload and _should_attempt_intent_recovery(
        analysis_stage=analysis_stage,
        confirm_enabled=confirm_enabled,
        recovery_scope=recovery_scope,
    ):
        logger.info(
            "analyze_volunteer_intent_change received no structured intents, falling back to latest-utterance recovery: session_id=%s recovery_scope=%s",
            session_id,
            recovery_scope,
        )
        major_intents, school_intents, city_intents, career_intents = await _recover_intents_from_context(
            ctx,
            recovery_scope=recovery_scope,
        )
        major_intents, school_intents, city_intents, career_intents = _normalize_intent_inputs(
            major_intents,
            school_intents,
            city_intents,
            career_intents,
        )
        major_intents, school_intents, city_intents, career_intents = _restrict_intents_to_recovery_scope(
            major_intents,
            school_intents,
            city_intents,
            career_intents,
            recovery_scope=recovery_scope,
        )
        major_intents = await _normalize_major_intent_names_for_batch(major_intents, batch)
        major_intents = _refine_major_intents_by_explicit_mentions(
            major_intents,
            latest_utterance=latest_utterance,
            batch=batch,
        )
        major_intents = _remove_unstated_positive_major_conflicts(
            major_intents,
            latest_utterance=latest_utterance,
            batch=batch,
        )
        if resolved_constraint_intent_type == CONSTRAINT_INTENT_ONLY_KEEP:
            major_intents = _prune_generated_negative_complements_for_only_keep(
                major_intents,
                latest_utterance=latest_utterance,
                batch=batch,
            )

    if not _has_any_intent_payload(major_intents, school_intents, city_intents, career_intents):
        if recovery_scope == "region" and not contains_concrete_region_mention(latest_utterance):
            return serialize_intent_analysis_payload(
                IntentAnalysisPayload(
                    status="empty",
                    sessionId=session_id,
                    title="先确认地域边界",
                    intentMode=INTENT_MODE_PREFERENCE,
                    analysisStage=ANALYSIS_STAGE_INTEREST,
                    message=_abstract_region_interest_message(),
                )
            )
        return serialize_intent_analysis_payload(
            IntentAnalysisPayload(
                status="empty",
                sessionId=session_id,
                analysisStage=analysis_stage,
                message="我这次还没准确整理出可调整的报考意向。你可以再明确说一下想保留、排除或更偏好的专业、院校、地域，或者像体制内、考公、稳定就业这类发展方向。",
            )
        )

    resolved_intent_mode = _classify_intent_mode(
        major_intents,
        school_intents,
        city_intents,
        career_intents,
        edit_flag=edit_flag,
        explicit_intent_mode=intent_mode,
        latest_utterance=latest_utterance,
    )
    analysis_stage, confirm_enabled, semantic_decision = await _maybe_downgrade_intent_preview_by_semantics(
        ctx,
        latest_utterance=latest_utterance,
        major_intents=major_intents,
        school_intents=school_intents,
        city_intents=city_intents,
        career_intents=career_intents,
        intent_mode=resolved_intent_mode,
        analysis_stage=analysis_stage,
        confirm_enabled=confirm_enabled,
    )
    if _should_return_abstract_region_interest_payload(
        latest_utterance=latest_utterance,
        recovery_scope=recovery_scope,
        had_explicit_intent_payload=had_explicit_intent_payload,
        analysis_stage=analysis_stage,
        semantic_decision=semantic_decision,
    ):
        return serialize_intent_analysis_payload(
            IntentAnalysisPayload(
                status="empty",
                sessionId=session_id,
                title="先确认地域边界",
                intentMode=resolved_intent_mode,
                analysisStage=analysis_stage,
                editFlag=edit_flag,
                message=_abstract_region_interest_message(),
            )
        )

    merged_for_constraint_type = {
        "major_intents": major_intents or {},
        "school_intents": school_intents or {},
        "city_intents": city_intents or {},
        "career_intents": career_intents or {},
    }
    resolved_constraint_intent_type = _normalize_constraint_type_for_payload(
        resolved_constraint_intent_type,
        merged_for_constraint_type,
    )
    semantic_constraint_intent_type = _constraint_type_from_semantic_decision(
        semantic_decision,
        merged=merged_for_constraint_type,
        allow_negative_only_region=(str(recovery_scope or "").strip().lower() in {"region", "city"}),
    )
    original_semantic_constraint_type = (
        _normalize_constraint_intent_type(semantic_decision.constraintIntentType)
        if semantic_decision is not None and semantic_decision.decision == "intent_preview" and semantic_decision.confidence >= 0.7
        else CONSTRAINT_INTENT_DEFAULT
    )
    if (
        resolved_constraint_intent_type == CONSTRAINT_INTENT_DEFAULT
        and semantic_constraint_intent_type == CONSTRAINT_INTENT_DEFAULT
        and semantic_decision is not None
        and semantic_decision.decision == "intent_preview"
        and semantic_decision.confidence >= 0.7
        and original_semantic_constraint_type == CONSTRAINT_INTENT_ONLY_KEEP
    ):
        recovered_major_intents = _recover_only_keep_positive_scope_from_generated_complement(
            major_intents,
            latest_utterance=latest_utterance,
            batch=batch,
        )
        if recovered_major_intents != major_intents:
            major_intents = recovered_major_intents
            merged_for_constraint_type = {
                "major_intents": major_intents or {},
                "school_intents": school_intents or {},
                "city_intents": city_intents or {},
                "career_intents": career_intents or {},
            }
            semantic_constraint_intent_type = _constraint_type_from_semantic_decision(
                semantic_decision,
                merged=merged_for_constraint_type,
            )
    if (
        resolved_constraint_intent_type == CONSTRAINT_INTENT_DEFAULT
        and semantic_constraint_intent_type == CONSTRAINT_INTENT_DEFAULT
        and original_semantic_constraint_type in {CONSTRAINT_INTENT_ONLY_KEEP, CONSTRAINT_INTENT_MUST_HAVE}
        and _has_negative_intents(major_intents, school_intents, city_intents, career_intents)
        and not _has_positive_values_in_payload(merged_for_constraint_type)
        and not _payload_is_negative_only_region(merged_for_constraint_type)
    ):
        logger.info(
            "Intent preview blocked semantic positive constraint without positive scope: session_id=%s constraint=%s utterance=%s payload=%s",
            session_id,
            original_semantic_constraint_type,
            latest_utterance,
            merged_for_constraint_type,
        )
        return serialize_intent_analysis_payload(
            IntentAnalysisPayload(
                status="empty",
                sessionId=session_id,
                title="先补充要保留的范围",
                intentMode=INTENT_MODE_CONSTRAINT,
                constraintIntentType=original_semantic_constraint_type,
                analysisStage=ANALYSIS_STAGE_INTEREST,
                editFlag=edit_flag,
                message=_missing_positive_constraint_message(original_semantic_constraint_type),
            )
        )
    if (
        resolved_constraint_intent_type == CONSTRAINT_INTENT_DEFAULT
        and semantic_constraint_intent_type != CONSTRAINT_INTENT_DEFAULT
    ):
        resolved_constraint_intent_type = semantic_constraint_intent_type
    if resolved_constraint_intent_type == CONSTRAINT_INTENT_ONLY_KEEP:
        major_intents = _preserve_only_keep_positive_major_scope(
            major_intents,
            latest_utterance=latest_utterance,
            batch=batch,
        )
        merged_for_constraint_type = {
            "major_intents": major_intents or {},
            "school_intents": school_intents or {},
            "city_intents": city_intents or {},
            "career_intents": career_intents or {},
        }
        resolved_constraint_intent_type = _normalize_constraint_type_for_payload(
            resolved_constraint_intent_type,
            merged_for_constraint_type,
        )
    if (
        semantic_constraint_intent_type in {CONSTRAINT_INTENT_ONLY_KEEP, CONSTRAINT_INTENT_MUST_HAVE}
        and not _has_positive_values_in_payload(merged_for_constraint_type)
        and _latest_utterance_has_positive_scope_signal(latest_utterance, recovery_scope)
    ):
        major_intents, school_intents, city_intents, career_intents = await _recover_positive_scope_for_positive_constraint(
            ctx,
            major_intents=major_intents,
            school_intents=school_intents,
            city_intents=city_intents,
            career_intents=career_intents,
            recovery_scope=recovery_scope,
            batch=batch,
            latest_utterance=latest_utterance,
        )
        if semantic_constraint_intent_type == CONSTRAINT_INTENT_ONLY_KEEP:
            major_intents = _preserve_only_keep_positive_major_scope(
                major_intents,
                latest_utterance=latest_utterance,
                batch=batch,
            )
        merged_for_constraint_type = {
            "major_intents": major_intents or {},
            "school_intents": school_intents or {},
            "city_intents": city_intents or {},
            "career_intents": career_intents or {},
        }
        if _has_positive_values_in_payload(merged_for_constraint_type):
            resolved_constraint_intent_type = semantic_constraint_intent_type
    if (
        resolved_constraint_intent_type == CONSTRAINT_INTENT_DEFAULT
        and semantic_constraint_intent_type in {CONSTRAINT_INTENT_ONLY_KEEP, CONSTRAINT_INTENT_MUST_HAVE}
        and _has_negative_intents(major_intents, school_intents, city_intents, career_intents)
        and not _has_positive_values_in_payload(merged_for_constraint_type)
    ):
        semantic_constraint_intent_type = CONSTRAINT_INTENT_DEFAULT
    if (
        semantic_constraint_intent_type in {CONSTRAINT_INTENT_ONLY_KEEP, CONSTRAINT_INTENT_MUST_HAVE}
        and not _has_positive_values_in_payload(merged_for_constraint_type)
    ):
        logger.info(
            "Intent preview blocked missing positive scope for positive constraint: session_id=%s constraint=%s utterance=%s payload=%s",
            session_id,
            semantic_constraint_intent_type,
            latest_utterance,
            merged_for_constraint_type,
        )
        return serialize_intent_analysis_payload(
            IntentAnalysisPayload(
                status="empty",
                sessionId=session_id,
                title="先补充要保留的范围",
                intentMode=INTENT_MODE_CONSTRAINT,
                constraintIntentType=semantic_constraint_intent_type,
                analysisStage=ANALYSIS_STAGE_INTEREST,
                editFlag=edit_flag,
                message=_missing_positive_constraint_message(semantic_constraint_intent_type),
            )
        )
    resolved_intent_mode = _coerce_intent_mode_for_constraint_type(
        resolved_intent_mode,
        resolved_constraint_intent_type,
    )

    pm = ProfileManager(int(session_id), batch)
    current_profile = await pm.get_current_profile()
    planning_summary = getattr(ctx.deps, "planning_summary", None)
    constraint_state = getattr(planning_summary, "constraint_state", None) if planning_summary is not None else None

    items_raw, existing_items_raw = _build_select_items(
        current_profile,
        major_intents,
        school_intents,
        city_intents,
        career_intents,
        intent_mode=resolved_intent_mode,
        analysis_stage=analysis_stage,
        batch=batch,
        constraint_state=constraint_state,
        latest_utterance=latest_utterance,
    )
    items = [IntentPreviewItem.model_validate(item) for item in items_raw]
    existing_items = [IntentPreviewItem.model_validate(item) for item in existing_items_raw]

    impact_text = ""
    impact_analysis: dict[str, Any] | None = None
    try:
        impact_analysis = _build_plan_relation_analysis(resolved_intent_mode, analysis_stage, career_intents)
        impact_analysis = await _enrich_plan_relation_analysis_from_state(
            session_id,
            impact_analysis,
            intent_mode=resolved_intent_mode,
            major_intents=major_intents,
            school_intents=school_intents,
            city_intents=city_intents,
            career_intents=career_intents,
        )
        impact_text = _build_impact_preview_from_analysis(impact_analysis)
    except Exception:
        logger.warning("基于当前方案状态生成关联分析失败: session_id=%s", session_id, exc_info=True)
    latest_relation_notes = _major_relation_notes_from_latest_utterance(major_intents, latest_utterance, batch)
    if latest_relation_notes:
        relation_text = "\n".join(f"- {note}" for note in latest_relation_notes)
        impact_text = f"{relation_text}\n{impact_text}" if impact_text else relation_text

    no_effect_message = _build_no_effect_negative_preference_message(
        current_profile,
        major_intents=major_intents,
        school_intents=school_intents,
        city_intents=city_intents,
        career_intents=career_intents,
        intent_mode=resolved_intent_mode,
        analysis_stage=analysis_stage,
        impact_analysis=impact_analysis,
    )
    if no_effect_message:
        return serialize_intent_analysis_payload(
            IntentAnalysisPayload(
                status="empty",
                sessionId=session_id,
                title=_build_preview_title(edit_flag, resolved_intent_mode, analysis_stage),
                intentMode=resolved_intent_mode,
                analysisStage=analysis_stage,
                editFlag=edit_flag,
                impactText=impact_text,
                impactAnalysis=impact_analysis,
                message=no_effect_message,
            )
        )

    status = "existing_only" if not items else "ready"
    logger.info(
        "Skipping legacy intent cache persistence: session_id=%s analysis_stage=%s status=%s utterance=%s",
        session_id,
        analysis_stage,
        status,
        latest_utterance,
    )

    payload = IntentAnalysisPayload(
        status=status,
        sessionId=session_id,
        title=_build_preview_title(edit_flag, resolved_intent_mode, analysis_stage),
        intentMode=resolved_intent_mode,
        constraintIntentType=resolved_constraint_intent_type,
        analysisStage=analysis_stage,
        editFlag=edit_flag,
        items=items,
        existingItems=existing_items,
        impactText=impact_text,
        impactAnalysis=impact_analysis,
    )
    payload_text = serialize_intent_analysis_payload(payload)
    if (
        analysis_stage == ANALYSIS_STAGE_CONFIRMED
        and status in {"ready", "existing_only"}
    ):
        observability = getattr(ctx.deps, "agent_observability", None)
        if isinstance(observability, dict):
            try:
                observability["latestIntentPreviewPayload"] = json.loads(payload_text)
            except Exception:
                logger.warning(
                    "Failed to cache latest intent preview payload: session_id=%s",
                    session_id,
                    exc_info=True,
                )
    return payload_text


async def apply_selected_intents(
    session_id: str,
    batch: str | None,
    selected_data: dict[str, Any],
) -> str:
    """Apply the selected intent subset and return structured execution facts.

    Args:
        session_id: chat session ID
        batch: "01" for bachelor, "02" for associate
        selected_data: {"selected": [...values...], "message_id": "..."}

    Returns:
        Serialized IntentStateUpdateResult JSON.
    """
    batch = _normalize_batch(batch)
    selected_values: list[dict[str, Any]] = selected_data.get("selected", [])
    message_id = selected_data.get("message_id")

    logger.info(
        "apply_selected_intents: session_id=%s, message_id=%s, selected_count=%d",
        session_id, message_id, len(selected_values),
    )

    # 1. Empty selection
    if not selected_values:
        return serialize_intent_state_update_result(
            IntentStateUpdateResult(
                action="apply_selected",
                sessionId=session_id,
                messageCode="select_empty",
            )
        )

    # 2. Merge selected values into unified intent structure
    merged = merge_selected_values(selected_values)

    # 3. Handle message state (clickable/clicked)
    if message_id:
        try:
            msg_resp = await get_message_by_id(message_id)
            msg_data = (msg_resp or {}).get("data", {})
            if msg_data:
                # Parse the content to check clickable/clicked
                content_raw = msg_data.get("content", "")
                try:
                    content_obj = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
                except (json.JSONDecodeError, TypeError):
                    content_obj = {}

                if isinstance(content_obj, dict):
                    if not content_obj.get("clickable", True):
                        return serialize_intent_state_update_result(
                            IntentStateUpdateResult(
                                action="apply_selected",
                                sessionId=session_id,
                                messageCode="message_not_clickable",
                            )
                        )
                    if content_obj.get("clicked", False):
                        return serialize_intent_state_update_result(
                            IntentStateUpdateResult(
                                action="apply_selected",
                                sessionId=session_id,
                                messageCode="message_already_clicked",
                            )
                        )

                    # Update message: set clickable=False, clicked=True, click_type=1
                    content_obj["clickable"] = False
                    content_obj["clicked"] = True
                    content_obj["click_type"] = 1

                    # Mark each item's selected status based on which values were selected
                    selected_set = {
                        json.dumps(sv, sort_keys=True, ensure_ascii=False)
                        for sv in selected_values
                    }
                    for item in content_obj.get("items", []):
                        item_val = item.get("value")
                        if item_val is not None:
                            item_key = json.dumps(item_val, sort_keys=True, ensure_ascii=False)
                            item["selected"] = item_key in selected_set
                        else:
                            item["selected"] = False

                    await update_message(
                        message_id=message_id,
                        chat_session_id=session_id,
                        content=content_obj,
                        message_from=0,
                        content_type="CARD",
                    )
        except Exception:
            logger.warning(
                "更新消息状态失败，继续执行意向更新: session_id=%s, message_id=%s",
                session_id, message_id, exc_info=True,
            )

    explicit_intent_mode = str(selected_data.get("intentMode") or selected_data.get("intent_mode") or "").strip()
    intent_mode = explicit_intent_mode if explicit_intent_mode in {INTENT_MODE_PREFERENCE, INTENT_MODE_CONSTRAINT} else INTENT_MODE_PREFERENCE
    constraint_intent_type = _normalize_constraint_type_for_payload(
        selected_data.get("constraintIntentType") or selected_data.get("constraint_intent_type"),
        merged,
    )
    if message_id:
        try:
            msg_resp = await get_message_by_id(message_id)
            msg_data = (msg_resp or {}).get("data", {})
            content_raw = msg_data.get("content", "")
            content_obj = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
            if isinstance(content_obj, dict):
                card_intent_mode = str(content_obj.get("intentMode") or "").strip()
                if card_intent_mode in {INTENT_MODE_PREFERENCE, INTENT_MODE_CONSTRAINT}:
                    intent_mode = card_intent_mode
                card_constraint_type = _normalize_constraint_type_for_payload(
                    content_obj.get("constraintIntentType") or content_obj.get("constraint_intent_type"),
                    merged,
                )
                if card_constraint_type != CONSTRAINT_INTENT_DEFAULT:
                    constraint_intent_type = card_constraint_type
        except Exception:
            logger.warning("读取意向确认卡片模式失败，默认按偏好处理: session_id=%s", session_id, exc_info=True)

    started_at = time.monotonic()
    try:
        result = await _apply_intents(
            session_id=session_id,
            batch=batch,
            merged=merged,
            intent_mode=intent_mode,
            constraint_intent_type=constraint_intent_type,
        )
        result.action = "apply_selected"
        log_event(
            "intent_state_event",
            sessionId=session_id,
            action="apply_selected",
            applied=bool(result.applied),
            messageCode=result.messageCode,
            intentMode=result.intentMode,
            constraintIntentType=result.constraintIntentType,
            durationMs=int((time.monotonic() - started_at) * 1000),
            status="success" if result.applied else "error",
        )
        return serialize_intent_state_update_result(result)
    except Exception:
        logger.exception("Applying selected intent changes failed: session_id=%s", session_id)
        log_event(
            "intent_state_event",
            sessionId=session_id,
            action="apply_selected",
            applied=False,
            messageCode="apply_failed",
            durationMs=int((time.monotonic() - started_at) * 1000),
            status="error",
            errorType="apply_failed",
        )
        return serialize_intent_state_update_result(
            IntentStateUpdateResult(
                action="apply_selected",
                sessionId=session_id,
                messageCode="apply_failed",
            )
        )
