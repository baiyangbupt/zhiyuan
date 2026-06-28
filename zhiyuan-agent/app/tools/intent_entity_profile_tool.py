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
from app.domain.career_slots import CAREER_ALIAS_MAP, normalize_career_slots, to_career_labels
from app.domain.intent_polarity import negative_constraint_reversal_clauses, parse_constraint_polarity_operation
from app.domain.major_entity_resolver import resolve_major_mentions_from_text
from app.domain.region_entity_resolver import resolve_region_entity, resolve_region_mentions_from_text
from app.domain.school_entity_resolver import compact_school_text, resolve_school_mention_spans_from_text
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


def _append_unique(values: list[str], value: str) -> None:
    text = str(value or "").strip()
    if text and text not in values:
        values.append(text)


def _career_profile_label(value: str) -> str:
    slots = normalize_career_slots([value])
    labels = to_career_labels(slots)
    return labels[0] if labels else ""


def _is_career_profile_alias(value: str) -> bool:
    return bool(_career_profile_label(value))


_SCHOOL_NATURE_ALIASES = {
    "公办": "公办",
    "公立": "公办",
    "公办院校": "公办",
    "公办学校": "公办",
    "公办大学": "公办",
    "公立院校": "公办",
    "公立学校": "公办",
    "公立大学": "公办",
    "民办": "民办",
    "私立": "民办",
    "民办院校": "民办",
    "民办学校": "民办",
    "民办大学": "民办",
    "私立院校": "民办",
    "私立学校": "民办",
    "私立大学": "民办",
}

_ADJUSTMENT_CONSTRAINT_VALUE = "专业调剂"
_ADJUSTMENT_ALIASES = {
    "调剂",
    "专业调剂",
    "服从调剂",
    "不服从调剂",
}

_SPECIAL_LIMIT_ALIASES = {
    "高收费": "高收费",
    "高学费": "高收费",
    "高费": "高收费",
    "高高学费": "高收费",
    "稿费": "高收费",
    "学费高": "高收费",
    "中外合作": "中外合作",
    "中外合作办学": "中外合作",
    "合作办学": "中外合作",
    "国际项目": "中外合作",
}


def _compact_profile_text(value: Any) -> str:
    return "".join(str(value or "").split())


def _normalize_school_nature_value(value: Any) -> str:
    compact = _compact_profile_text(value)
    if compact in _SCHOOL_NATURE_ALIASES:
        return _SCHOOL_NATURE_ALIASES[compact]
    if "公办" in compact or "公立" in compact:
        return "公办"
    if "民办" in compact or "私立" in compact:
        return "民办"
    return ""


def _normalize_adjustment_constraint_value(value: Any) -> str:
    compact = _compact_profile_text(value)
    if compact in _ADJUSTMENT_ALIASES:
        return _ADJUSTMENT_CONSTRAINT_VALUE
    if "调剂" in compact and not any(token in compact for token in ("调剂风险", "调剂概率")):
        return _ADJUSTMENT_CONSTRAINT_VALUE
    return ""


def _normalize_region_profile_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    resolved = resolve_region_entity(text)
    best = resolved.best
    return str(best.canonical_name or "").strip() if best else text


def _normalize_special_limit_value(value: Any) -> str:
    compact = _compact_profile_text(value)
    if not compact:
        return ""
    if compact in _SPECIAL_LIMIT_ALIASES:
        return _SPECIAL_LIMIT_ALIASES[compact]
    if "中外合作" in compact or "合作办学" in compact or "国际项目" in compact:
        return "中外合作"
    if any(token in compact for token in ("高收费", "高学费", "高费", "学费高")):
        return "高收费"
    return ""


def _utterance_has_negative_adjustment_constraint(utterance: str) -> bool:
    compact = _compact_profile_text(utterance)
    if "调剂" not in compact:
        return False
    negative_markers = (
        "不要调剂",
        "不接受调剂",
        "不服从调剂",
        "别调剂",
        "不能调剂",
        "拒绝调剂",
        "调剂不要",
        "调剂不接受",
    )
    return any(marker in compact for marker in negative_markers)


def _school_nature_strength_from_text(value: str, utterance: str) -> tuple[str, bool] | None:
    """Infer school-nature polarity from the current utterance when available."""
    nature = _normalize_school_nature_value(value)
    compact = _compact_profile_text(utterance)
    if not nature or not compact or nature not in compact:
        return None
    polarity_operation = parse_constraint_polarity_operation(utterance)
    if polarity_operation is not None and polarity_operation.operation == "remove_negative_constraint":
        return polarity_operation.replacement_strength, False
    if nature == "公办":
        negative_markers = (
            "不要公办",
            "不接受公办",
            "排除公办",
            "避开公办",
            "公办别要",
        )
        hard_positive_markers = (
            "只要公办",
            "只看公办",
            "只考虑公办",
            "仅限公办",
            "必须公办",
            "公办必须",
            "保底要公办",
        )
        positive_markers = (
            "加点公办",
            "增加公办",
            "补点公办",
            "优先公办",
            "公办优先",
            "公办可以",
            "公办院校可以考虑",
            "公办也可以",
            "考虑公办",
            "要公办",
        )
        if any(marker in compact for marker in negative_markers):
            return "exclude_hard", True
        if any(marker in compact for marker in hard_positive_markers):
            return "must_have", False
        if any(marker in compact for marker in positive_markers):
            return "preferred", False
        return "preferred", False
    negative_markers = (
        "不要民办",
        "不接受民办",
        "排除民办",
        "避开民办",
        "民办不要",
        "民办别要",
        "民办少点",
        "少点民办",
        "全是民办",
        "都是民办",
    )
    positive_markers = (
        "接受民办",
        "民办可以",
        "民办也可以",
        "民办能接受",
        "可以考虑民办",
    )
    if any(marker in compact for marker in positive_markers):
        return "acceptable", False
    if any(marker in compact for marker in negative_markers):
        return "exclude_hard", True
    return "exclude_soft", True


def _school_nature_mentions_from_utterance(utterance: str) -> list[tuple[str, str, bool]]:
    compact = _compact_profile_text(utterance)
    mentions: list[tuple[str, str, bool]] = []
    for nature in ("公办", "民办"):
        if nature not in compact and not (nature == "公办" and "公立" in compact) and not (nature == "民办" and "私立" in compact):
            continue
        strength = _school_nature_strength_from_text(nature, utterance)
        if not strength:
            continue
        mentions.append((nature, strength[0], strength[1]))
    return mentions


def _region_reversal_values_from_utterance(
    utterance: str,
    *,
    excluded_compact_spans: list[tuple[int, int]] | None = None,
) -> list[str]:
    compact = compact_school_text(utterance)
    excluded_compact_spans = excluded_compact_spans or []
    values: list[str] = []
    seen_spans: set[tuple[int, int, str]] = set()
    for mention in resolve_region_mentions_from_text(utterance):
        entity = str(mention.canonical_name or "").strip()
        raw_text = str(getattr(mention, "raw_text", "") or entity).strip()
        compact_mention = compact_school_text(raw_text) or compact_school_text(entity)
        start = compact.find(compact_mention) if compact_mention else -1
        end = start + len(compact_mention) if start >= 0 else -1
        if start >= 0:
            search_start = 0
            while True:
                candidate_start = compact.find(compact_mention, search_start)
                if candidate_start < 0:
                    break
                candidate_end = candidate_start + len(compact_mention)
                search_start = candidate_start + 1
                span_key = (candidate_start, candidate_end, entity)
                if span_key in seen_spans:
                    continue
                seen_spans.add(span_key)
                if any(candidate_start >= used_start and candidate_end <= used_end for used_start, used_end in excluded_compact_spans):
                    continue
                if entity and entity not in values:
                    values.append(entity)
            continue
        if start >= 0 and any(start >= used_start and end <= used_end for used_start, used_end in excluded_compact_spans):
            continue
        if entity and entity not in values:
            values.append(entity)
    return values


def _career_reversal_values_from_utterance(utterance: str) -> list[str]:
    compact = _compact_profile_text(utterance)
    values: list[str] = []
    for alias in sorted(CAREER_ALIAS_MAP, key=lambda value: len(_compact_profile_text(value)), reverse=True):
        compact_alias = _compact_profile_text(alias)
        if not compact_alias or compact_alias not in compact:
            continue
        label = _career_profile_label(alias)
        if label and label not in values:
            values.append(label)
    return values


def _special_limit_reversal_values_from_utterance(utterance: str) -> list[str]:
    compact = _compact_profile_text(utterance)
    values: list[str] = []
    for alias, canonical in sorted(_SPECIAL_LIMIT_ALIASES.items(), key=lambda item: len(_compact_profile_text(item[0])), reverse=True):
        compact_alias = _compact_profile_text(alias)
        if compact_alias and compact_alias in compact and canonical not in values:
            values.append(canonical)
    return values


def _negative_constraint_reversal_targets(utterance: str, batch: str = "01") -> dict[str, list[str]]:
    operation = parse_constraint_polarity_operation(utterance)
    if operation is None or operation.operation != "remove_negative_constraint":
        return {}
    reversal_clauses = negative_constraint_reversal_clauses(utterance)
    if not reversal_clauses:
        return {}
    targets: dict[str, list[str]] = {
        "major": [],
        "school": [],
        "region": [],
        "career": [],
        "budget": [],
    }

    def append(kind: str, value: str) -> None:
        text = str(value or "").strip()
        if not text:
            return
        bucket = targets.setdefault(kind, [])
        if text not in bucket:
            bucket.append(text)

    for clause in reversal_clauses:
        for mention in resolve_major_mentions_from_text(clause, batch):
            entity = str(mention.canonical_name or "").strip()
            append("major", entity)
        school_name_spans = resolve_school_mention_spans_from_text(clause, batch)
        for value, _start, _end in school_name_spans:
            append("school", value)
        compact_clause = _compact_profile_text(clause)
        for value in ("公办", "民办"):
            if any(alias in compact_clause for alias, canonical in _SCHOOL_NATURE_ALIASES.items() if canonical == value):
                append("school", value)
        for value in _region_reversal_values_from_utterance(
            clause,
            excluded_compact_spans=[(start, end) for _name, start, end in school_name_spans],
        ):
            append("region", value)
        for value in _career_reversal_values_from_utterance(clause):
            append("career", value)
        for value in _special_limit_reversal_values_from_utterance(clause):
            append("budget", value)
    return {key: values for key, values in targets.items() if values}


class IntentEntityProfileResult(BaseModel):
    entityType: str = ""
    majorValues: list[str] = Field(default_factory=list)
    regionValues: list[str] = Field(default_factory=list)
    schools: list[str] = Field(default_factory=list)
    careerValues: list[str] = Field(default_factory=list)
    tuitionBudget: dict[str, Any] = Field(default_factory=dict)
    physicalConstraints: dict[str, list[str]] = Field(default_factory=dict)
    preferenceStrength: dict[str, list[str]] = Field(default_factory=dict)
    entityPolaritySpans: list[dict[str, Any]] = Field(default_factory=list)
    contextResolution: dict[str, Any] = Field(default_factory=dict)
    admissionPath: str | None = None
    confidence: float = 0.0
    reason: str = ""

    @field_validator("majorValues", "regionValues", "schools", "careerValues", mode="before")
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

    @field_validator("tuitionBudget", mode="before")
    @classmethod
    def _coerce_tuition_budget(cls, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        result: dict[str, Any] = {}
        for source_key, target_key in (
            ("minTuitionPerYear", "minTuitionPerYear"),
            ("min_tuition_per_year", "minTuitionPerYear"),
            ("maxTuitionPerYear", "maxTuitionPerYear"),
            ("max_tuition_per_year", "maxTuitionPerYear"),
        ):
            raw_value = value.get(source_key)
            if raw_value in (None, ""):
                continue
            try:
                amount = int(raw_value)
            except (TypeError, ValueError):
                continue
            if amount > 0:
                result[target_key] = amount
        return result

    @field_validator("physicalConstraints", mode="before")
    @classmethod
    def _coerce_physical_constraints(cls, value: Any) -> dict[str, list[str]]:
        if not isinstance(value, dict):
            return {}
        result: dict[str, list[str]] = {}
        for source_key, target_key in (
            ("specialLimits", "specialLimits"),
            ("special_limits", "specialLimits"),
        ):
            values = _normalize_text_list(value.get(source_key))
            if values:
                result[target_key] = values
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

    @field_validator("contextResolution", mode="before")
    @classmethod
    def _coerce_context_resolution(cls, value: Any) -> dict[str, Any]:
        return dict(value) if isinstance(value, dict) else {}

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
                "preferenceStrength 是语义强度层，不是简单布尔偏好；不要把它压成 legacy constraintIntentType。"
                "只有明确只保留/必须有/必须避开才进入 constraint/contract 语义。"
                "不要输出 legacy constraintIntentType，也不要把旧字段改名当作新字段。"
            ),
            "schemaRules": [
                "entityType 取 major、school、region、career、budget、mixed、none。",
                "majorValues 只放专业/专业类/专业门类；regionValues 只放地域词；schools 只放院校实体；careerValues 只放发展方向或职业路径，例如体制内/考公导向、稳定就业导向、深造发展导向、市场化就业导向。",
                "tuitionBudget 只放明确的年学费预算，字段为 maxTuitionPerYear/minTuitionPerYear，单位必须是元/年；例如“两万以内”输出 {\"maxTuitionPerYear\":20000}。",
                "physicalConstraints.specialLimits 只放非数值费用或招生项目限制，例如高收费、中外合作；例如“不接受高学费/高收费/高高学费/稿费(ASR误写高费)”输出 {\"specialLimits\":[\"高收费\"]}。",
                "公办/民办是院校性质，不要放入 physicalConstraints.specialLimits；应作为 value 出现在 preferenceStrength 和 entityPolaritySpans 中，entityType=school。比如“优先公办/加点公办”是正向 school，“不要民办/民办少点/全是民办”是负向 school。",
                "只有用户表达“以后推荐/后续参考/也记上/作为筛选条件”等未来偏好时，才把学费预算作为 intent profile；如果用户要求当前方案里删除、替换、处理超预算志愿，不要在这里伪造成普通偏好。",
                "用户说“不要排除/别排除/不排除/取消排除/撤销排除 + 实体”时，不是新增负向排除；应理解为撤回负向约束、恢复可考虑。当前 schema 用 positive/acceptable 表达该实体，不要输出 exclude_hard 或 negative polarity。",
                "context.recentEntityContext 表示上一轮只读工具里的结构化实体候选，不代表本轮自动采纳。",
                "兼容字段 context.recentMajorContext 只表示上一轮只读工具里的结构化专业候选，不代表本轮自动采纳。",
                "latestUserText 明确用“那两个/这几个/这些/它们/这几所/这些城市/这些方向”等指代并表达加入、记下、也可以、都可以、都加到意向时，才把 context 中被指代的实体并入对应 values 和 preferenceStrength。",
                "latestUserText 是否定、排除、别加、不要、只是问问、先比较、先看看时，不要把 context 中实体并入正向偏好。",
                "如果 latestUserText 同时给出新的地域、学校、专业、发展方向或排除条件，保留本轮新实体，并按指代语义合并 context 中被明确引用的实体。",
                "preferenceStrength 必须是“强度 -> 实体列表”的对象，禁止输出“实体 -> 强度列表”。",
                "正确示例：{\"primary\":[\"网络与新媒体\"],\"acceptable\":[\"跨境电子商务\"]}；错误示例：{\"网络与新媒体\":[\"primary\"]}。",
                "preferenceStrength key 只能用 primary、preferred、acceptable、must_have、only_keep、exclude_soft、exclude_hard。",
                "primary 只表示明确优先、首选、重点或最想要。",
                "preferred 表示普通偏好、感兴趣、加到意向、加入后续参考。",
                "acceptable 表示也可以、也可以考虑、也能接受、作为备选可以。",
                "must_have 表示至少要有。",
                "only_keep 表示只保留、只考虑、只看这些。",
                "exclude_soft 表示轻度不优先、尽量避开。",
                "exclude_hard 表示明确不要、必须避开、排除。",
                "“加到意向/加意向/记到意向”本身不是 primary，除非同一句还明确说优先、首选、重点。",
                "“也可以考虑/也可以/也能接受”本身不是 preferred，必须归到 acceptable。",
                "“只考虑/只保留/只看这些”必须归到 only_keep。",
                "“必须有/至少保留”必须归到 must_have。",
                "“不要/别要/必须避开/排除”必须归到 exclude_hard。",
                "entityPolaritySpans 每项包含 entity、entityType、polarity、strength；entityType 可为 major、school、region、career、budget；polarity 只能是 positive 或 negative。",
                "physicalConstraints.specialLimits 对应 entityPolaritySpans 时，entityType 使用 budget，polarity 使用 negative，strength 使用 exclude_hard；但公办/民办不属于 physicalConstraints。",
                "entityPolaritySpans 中的 entity 应使用规范实体名；例如“跨境电商”写成“跨境电子商务”，“口腔”写成“口腔医学”。",
                "体制内、考公、考编、公务员、事业单位、稳定就业、求稳、读研、深造、市场化就业是 career 发展方向，不是 major 专业；禁止放入 majorValues。",
                "如果使用了 context.recentEntityContext，contextResolution.used 必须为 true，并填 source=recentEntityContext、entityType、values 和 confidence；兼容使用 recentMajorContext 时 source 可填 recentMajorContext。",
                "如果没有使用 context 里的实体候选，contextResolution.used 必须为 false，并简述原因。",
                "admissionPath 只在强基、综评、专项等特殊路径明确出现时填写，例如强基填 strongbase。",
                "不要把地域词误识别为专业，例如“城市优先长三角”里的实体是 region，不是城市管理专业。",
                "示例：latestUserText='那如果我不接受稿费呢高高学费'，应理解为不接受高学费/高收费，输出 entityType=budget、physicalConstraints.specialLimits=['高收费']、preferenceStrength.exclude_hard=['高收费']。",
            ],
            "returnJson": {
                "entityType": "major|school|region|career|budget|mixed|none",
                "majorValues": [],
                "regionValues": [],
                "schools": [],
                "careerValues": [],
                "tuitionBudget": {"maxTuitionPerYear": None, "minTuitionPerYear": None},
                "physicalConstraints": {"specialLimits": []},
                "preferenceStrength": {},
                "entityPolaritySpans": [],
                "contextResolution": {
                    "used": False,
                    "source": "",
                    "entityType": "",
                    "values": [],
                    "confidence": 0.0,
                    "reason": "",
                },
                "admissionPath": None,
                "confidence": 0.0,
                "reason": "",
            },
        },
        ensure_ascii=False,
    )


def _normalize_entity_profile(
    result: IntentEntityProfileResult,
    *,
    latest_utterance: str = "",
) -> IntentEntityProfileResult:
    major_values: list[str] = []
    region_values: list[str] = []
    school_values: list[str] = []
    career_values: list[str] = []
    for value in result.regionValues:
        _append_unique(region_values, _normalize_region_profile_value(value))
    for value in result.careerValues:
        _append_unique(career_values, _career_profile_label(value) or value)
    for value in result.schools:
        _append_unique(school_values, _normalize_school_nature_value(value) or value)
    career_alias_values: dict[str, str] = {}
    for value in result.majorValues:
        school_nature = _normalize_school_nature_value(value)
        if school_nature:
            _append_unique(school_values, school_nature)
            continue
        if _normalize_adjustment_constraint_value(value):
            continue
        label = _career_profile_label(value)
        if label:
            career_alias_values[value] = label
            _append_unique(career_values, label)
        else:
            _append_unique(major_values, value)

    negative_reversal_targets = _negative_constraint_reversal_targets(latest_utterance)
    negative_reversal_sets = {
        key: set(values)
        for key, values in negative_reversal_targets.items()
    }
    reversal_strength = "acceptable"
    polarity_operation = parse_constraint_polarity_operation(latest_utterance)
    if polarity_operation is not None and polarity_operation.operation == "remove_negative_constraint":
        reversal_strength = polarity_operation.replacement_strength or "acceptable"
    for value in negative_reversal_targets.get("major", []):
        _append_unique(major_values, value)
    for value in negative_reversal_targets.get("region", []):
        _append_unique(region_values, value)
    for value in negative_reversal_targets.get("school", []):
        _append_unique(school_values, _normalize_school_nature_value(value) or value)
    for value in negative_reversal_targets.get("career", []):
        _append_unique(career_values, _career_profile_label(value) or value)
    preference_strength: dict[str, list[str]] = {}

    def add_preference(strength: str, value: str) -> None:
        strength_text = str(strength or "").strip()
        value_text = str(value or "").strip()
        if not strength_text or not value_text:
            return
        bucket = preference_strength.setdefault(strength_text, [])
        if value_text not in bucket:
            bucket.append(value_text)

    def remove_preference(strength: str, value: str) -> None:
        strength_text = str(strength or "").strip()
        value_text = str(value or "").strip()
        if not strength_text or not value_text:
            return
        values = preference_strength.get(strength_text)
        if not values:
            return
        preference_strength[strength_text] = [item for item in values if item != value_text]
        if not preference_strength[strength_text]:
            preference_strength.pop(strength_text, None)

    for strength, raw_values in result.preferenceStrength.items():
        strength_text = str(strength or "").strip()
        for value in raw_values:
            normalized_region = _normalize_region_profile_value(value)
            school_nature = _normalize_school_nature_value(value)
            if school_nature:
                _append_unique(school_values, school_nature)
                override = _school_nature_strength_from_text(school_nature, latest_utterance)
                target_strength = override[0] if override else strength_text
                add_preference(target_strength, school_nature)
                continue
            adjustment_constraint = _normalize_adjustment_constraint_value(value)
            if adjustment_constraint:
                continue
            special_limit = _normalize_special_limit_value(value)
            if special_limit:
                if special_limit in negative_reversal_sets.get("budget", set()):
                    continue
                add_preference(strength_text, special_limit)
                continue
            if normalized_region in negative_reversal_sets.get("region", set()):
                _append_unique(region_values, normalized_region)
                add_preference(reversal_strength, normalized_region)
                continue
            add_preference(strength_text, career_alias_values.get(value) or _career_profile_label(value) or value)

    entity_polarity_spans: list[dict[str, Any]] = []
    physical_constraints = result.physicalConstraints if isinstance(result.physicalConstraints, dict) else {}
    special_limits: list[str] = []
    physical_school_natures: list[str] = []
    for value in _normalize_text_list(physical_constraints.get("specialLimits")):
        school_nature = _normalize_school_nature_value(value)
        if school_nature:
            _append_unique(physical_school_natures, school_nature)
            _append_unique(school_values, school_nature)
            override = _school_nature_strength_from_text(school_nature, latest_utterance)
            if override:
                add_preference(override[0], school_nature)
            elif school_nature == "民办":
                add_preference("exclude_hard", school_nature)
            else:
                add_preference("preferred", school_nature)
            continue
        adjustment_constraint = _normalize_adjustment_constraint_value(value)
        if adjustment_constraint:
            if adjustment_constraint in negative_reversal_sets.get("budget", set()):
                continue
            _append_unique(special_limits, adjustment_constraint)
            add_preference("exclude_hard", adjustment_constraint)
            continue
        special_limit = _normalize_special_limit_value(value) or str(value or "").strip()
        if special_limit in negative_reversal_sets.get("budget", set()):
            continue
        _append_unique(special_limits, special_limit)
        add_preference("exclude_hard", special_limit)
    physical_constraints = {"specialLimits": special_limits} if special_limits else {}
    for span in result.entityPolaritySpans:
        normalized_span = dict(span)
        entity = str(normalized_span.get("entity") or "").strip()
        entity_type_text = str(normalized_span.get("entityType") or "").strip()
        school_nature = _normalize_school_nature_value(entity)
        if school_nature:
            normalized_span["entity"] = school_nature
            normalized_span["entityType"] = "school"
            entity = school_nature
            entity_type_text = "school"
            _append_unique(school_values, school_nature)
            override = _school_nature_strength_from_text(school_nature, latest_utterance)
            if override:
                normalized_span["strength"] = override[0]
                normalized_span["polarity"] = "negative" if override[1] else "positive"
                add_preference(override[0], school_nature)
        elif entity_type_text == "major" and _is_career_profile_alias(entity):
            normalized_span["entityType"] = "career"
            normalized_span["entity"] = career_alias_values.get(entity) or _career_profile_label(entity) or entity
            entity = str(normalized_span["entity"])
            entity_type_text = "career"
            _append_unique(career_values, entity)
        elif entity_type_text == "career" and _is_career_profile_alias(entity):
            normalized_span["entity"] = _career_profile_label(entity) or entity
            entity = str(normalized_span["entity"])
            _append_unique(career_values, entity)
        elif entity_type_text == "region":
            normalized_entity = _normalize_region_profile_value(entity)
            normalized_span["entity"] = normalized_entity
            entity = normalized_entity
            _append_unique(region_values, normalized_entity)
        elif entity_type_text == "major" and _normalize_adjustment_constraint_value(entity):
            continue
        elif entity_type_text == "budget":
            special_limit = _normalize_special_limit_value(entity) or _normalize_adjustment_constraint_value(entity) or entity
            normalized_span["entity"] = special_limit
            entity = special_limit
            if entity in negative_reversal_sets.get("budget", set()):
                remove_preference("exclude_soft", entity)
                remove_preference("exclude_hard", entity)
                continue
        if entity_type_text in {"major", "school", "region", "career"} and entity in negative_reversal_sets.get(entity_type_text, set()):
            normalized_span["polarity"] = "positive"
            normalized_span["strength"] = reversal_strength
            remove_preference("exclude_soft", entity)
            remove_preference("exclude_hard", entity)
            add_preference(reversal_strength, entity)
        entity_polarity_spans.append(normalized_span)
    covered_reversal_entities = {
        (
            str(span.get("entityType") or "").strip(),
            str(span.get("entity") or "").strip(),
        )
        for span in entity_polarity_spans
    }
    for entity_type_text, values in negative_reversal_targets.items():
        if entity_type_text == "budget":
            for value in values:
                remove_preference("exclude_soft", value)
                remove_preference("exclude_hard", value)
            continue
        for value in values:
            remove_preference("exclude_soft", value)
            remove_preference("exclude_hard", value)
            add_preference(reversal_strength, value)
            if (entity_type_text, value) in covered_reversal_entities:
                continue
            entity_polarity_spans.append(
                {
                    "entity": value,
                    "entityType": entity_type_text,
                    "polarity": "positive",
                    "strength": reversal_strength,
                }
            )
            covered_reversal_entities.add((entity_type_text, value))
    covered_school_nature_entities = {
        str(span.get("entity") or "").strip()
        for span in entity_polarity_spans
        if str(span.get("entityType") or "").strip() == "school"
    }
    for value in physical_school_natures:
        if value in covered_school_nature_entities:
            continue
        override = _school_nature_strength_from_text(value, latest_utterance)
        strength, negative = override if override else ("exclude_hard", True) if value == "民办" else ("preferred", False)
        entity_polarity_spans.append(
            {
                "entity": value,
                "entityType": "school",
                "polarity": "negative" if negative else "positive",
                "strength": strength,
            }
        )
        add_preference(strength, value)
    covered_school_nature_entities = {
        str(span.get("entity") or "").strip()
        for span in entity_polarity_spans
        if str(span.get("entityType") or "").strip() == "school"
    }
    for value, strength, negative in _school_nature_mentions_from_utterance(latest_utterance):
        _append_unique(school_values, value)
        add_preference(strength, value)
        if value in covered_school_nature_entities:
            continue
        entity_polarity_spans.append(
            {
                "entity": value,
                "entityType": "school",
                "polarity": "negative" if negative else "positive",
                "strength": strength,
            }
        )
        covered_school_nature_entities.add(value)
    covered_budget_entities = {
        str(span.get("entity") or "").strip()
        for span in entity_polarity_spans
        if str(span.get("entityType") or "").strip() == "budget"
    }
    for value in special_limits:
        if value in covered_budget_entities:
            continue
        entity_polarity_spans.append(
            {
                "entity": value,
                "entityType": "budget",
                "polarity": "negative",
                "strength": "exclude_hard",
            }
        )
    if _utterance_has_negative_adjustment_constraint(latest_utterance):
        _append_unique(special_limits, _ADJUSTMENT_CONSTRAINT_VALUE)
        physical_constraints = {"specialLimits": special_limits} if special_limits else {}
        add_preference("exclude_hard", _ADJUSTMENT_CONSTRAINT_VALUE)
        if _ADJUSTMENT_CONSTRAINT_VALUE not in covered_budget_entities:
            entity_polarity_spans.append(
                {
                    "entity": _ADJUSTMENT_CONSTRAINT_VALUE,
                    "entityType": "budget",
                    "polarity": "negative",
                    "strength": "exclude_hard",
                }
            )

    entity_type = str(result.entityType or "").strip()
    tuition_budget = result.tuitionBudget if isinstance(result.tuitionBudget, dict) else {}
    has_tuition_budget = bool(tuition_budget)
    has_physical_constraints = bool(physical_constraints)
    if entity_type not in {"major", "school", "region", "career", "budget", "mixed", "none"} or entity_type == "none":
        if major_values and (region_values or school_values or career_values or has_tuition_budget or has_physical_constraints):
            entity_type = "mixed"
        elif major_values:
            entity_type = "major"
        elif region_values:
            entity_type = "region"
        elif school_values:
            entity_type = "school"
        elif career_values:
            entity_type = "career"
        elif has_tuition_budget or has_physical_constraints:
            entity_type = "budget"
        else:
            entity_type = "none"
    if entity_type == "budget" and not (has_tuition_budget or has_physical_constraints):
        if school_values and not any((major_values, region_values, career_values)):
            entity_type = "school"
        elif any((major_values, region_values, school_values, career_values)):
            entity_type = "mixed"
        else:
            entity_type = "none"
    if entity_type == "major" and career_values and not major_values:
        entity_type = "career"
    if (has_tuition_budget or has_physical_constraints) and not any((major_values, region_values, school_values, career_values)):
        entity_type = "budget"
    if entity_type != "none":
        non_empty_kinds = sum(
            bool(values)
            for values in (major_values, region_values, school_values, career_values)
        ) + (1 if has_tuition_budget or has_physical_constraints else 0)
        if non_empty_kinds > 1:
            entity_type = "mixed"
    confidence = max(0.0, min(1.0, float(result.confidence or 0.0)))
    return IntentEntityProfileResult(
        entityType=entity_type,
        majorValues=major_values,
        regionValues=region_values,
        schools=school_values,
        careerValues=career_values,
        tuitionBudget=tuition_budget,
        physicalConstraints=physical_constraints,
        preferenceStrength=preference_strength,
        entityPolaritySpans=entity_polarity_spans,
        contextResolution=result.contextResolution,
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
    normalized = _normalize_entity_profile(parsed, latest_utterance=text)
    logger.info(
        "extract_intent_entity_profile: entity_type=%s majors=%s regions=%s schools=%s careers=%s tuition_budget=%s admission_path=%s confidence=%s",
        normalized.entityType,
        normalized.majorValues,
        normalized.regionValues,
        normalized.schools,
        normalized.careerValues,
        normalized.tuitionBudget,
        normalized.admissionPath,
        normalized.confidence,
    )
    return normalized
