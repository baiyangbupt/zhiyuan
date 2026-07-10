"""Shared attribute registry for plan query and plan action selectors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


AttributeType = Literal["enum", "numeric", "tag_set"]
AttributeOperation = Literal["query", "exclude", "only_keep", "must_have"]


@dataclass(frozen=True)
class AttributeDimension:
    key: str
    label: str
    type: AttributeType
    item_fields: tuple[str, ...]
    values: tuple[str, ...] | None
    aliases: dict[str, str]
    supports: frozenset[AttributeOperation]


def _compact(value: Any) -> str:
    return "".join(str(value or "").split()).lower()


ATTRIBUTE_REGISTRY: dict[str, AttributeDimension] = {
    "school_nature": AttributeDimension(
        key="school_nature",
        label="院校性质",
        type="enum",
        item_fields=("schoolNature", "school_nature", "schoolType", "school_type", "schoolTags", "tags"),
        values=("公办", "民办"),
        aliases={
            "公立": "公办",
            "公办学校": "公办",
            "公办院校": "公办",
            "公立学校": "公办",
            "公立院校": "公办",
            "私立": "民办",
            "私立学校": "民办",
            "私立院校": "民办",
            "民办学校": "民办",
            "民办院校": "民办",
            "民办大学": "民办",
        },
        supports=frozenset({"query", "exclude", "only_keep"}),
    ),
    "tier": AttributeDimension(
        key="tier",
        label="梯度",
        type="enum",
        item_fields=("tier", "riskTier", "risk_tier"),
        values=("冲", "稳", "保"),
        aliases={"冲刺": "冲", "稳妥": "稳", "保底": "保", "兜底": "保", "保险": "保"},
        supports=frozenset({"query"}),
    ),
    "school_level": AttributeDimension(
        key="school_level",
        label="院校层次",
        type="tag_set",
        item_fields=("schoolLevel", "school_level", "schoolRankTags", "schoolTags", "tags"),
        values=("985", "211", "双一流", "一本", "二本", "本科", "专科"),
        aliases={
            "985院校": "985",
            "985学校": "985",
            "211院校": "211",
            "211学校": "211",
            "双一流院校": "双一流",
            "双一流学校": "双一流",
        },
        supports=frozenset({"query", "only_keep"}),
    ),
    "school_category": AttributeDimension(
        key="school_category",
        label="院校类型",
        type="tag_set",
        item_fields=("schoolCategory", "school_category", "schoolTags", "tags"),
        values=("综合", "理工", "师范", "财经", "医药", "农林", "政法", "语言", "艺术", "体育", "民族", "军事"),
        aliases={"工科院校": "理工", "理工类": "理工", "师范院校": "师范", "财经院校": "财经", "政法院校": "政法"},
        supports=frozenset({"query", "only_keep", "exclude"}),
    ),
    "program_type": AttributeDimension(
        key="program_type",
        label="招生类型",
        type="tag_set",
        item_fields=(
            "enrollmentType",
            "programType",
            "majorName",
            "major_name",
            "majorPlanTags",
            "schoolTags",
            "schoolBasicTags",
            "majorTags",
            "tags",
            "reasonCodes",
        ),
        values=("普通类", "中外合作", "高收费", "校企合作", "国际项目", "强基"),
        aliases={
            "合作办学": "中外合作",
            "中外合作办学": "中外合作",
            "中外合办": "中外合作",
            "国际班": "国际项目",
            "强基计划": "强基",
            "基础学科招生改革试点": "强基",
            "高学费": "高收费",
            "学费高": "高收费",
            "费用高": "高收费",
            "太贵": "高收费",
        },
        supports=frozenset({"query", "exclude", "must_have"}),
    ),
    "school_tag": AttributeDimension(
        key="school_tag",
        label="院校标签",
        type="tag_set",
        item_fields=("schoolTags", "schoolRankTags", "schoolBasicTags", "schoolPopupTags", "tags"),
        values=None,
        aliases={},
        supports=frozenset({"query", "exclude", "only_keep"}),
    ),
    "major_tag": AttributeDimension(
        key="major_tag",
        label="专业标签",
        type="tag_set",
        item_fields=("majorTags", "majorPlanTags", "majorRankTags", "tags"),
        values=None,
        aliases={
            "五年": "学制：5年",
            "五年制": "学制：5年",
            "5年": "学制：5年",
            "5年制": "学制：5年",
            "学制5年": "学制：5年",
            "四年": "学制：4年",
            "四年制": "学制：4年",
            "4年": "学制：4年",
            "4年制": "学制：4年",
            "学制4年": "学制：4年",
        },
        supports=frozenset({"query", "exclude", "only_keep"}),
    ),
    "major_category": AttributeDimension(
        key="major_category",
        label="专业门类",
        type="tag_set",
        item_fields=("majorCategory", "major_category", "majorDiscipline", "major_discipline", "majorPlanTags", "majorTags"),
        values=None,
        aliases={},
        supports=frozenset({"query", "exclude", "only_keep"}),
    ),
    "province": AttributeDimension(
        key="province",
        label="省份",
        type="enum",
        item_fields=("provinceName", "province_name", "province"),
        values=None,
        aliases={},
        supports=frozenset({"query", "exclude", "only_keep"}),
    ),
}


_FILTER_KEY_ALIASES = {
    "schoolNature": "school_nature",
    "schoolType": "school_nature",
    "school_type": "school_nature",
    "nature": "school_nature",
    "schoolLevel": "school_level",
    "schoolRankTag": "school_level",
    "school_level": "school_level",
    "schoolCategory": "school_category",
    "school_category": "school_category",
    "programType": "program_type",
    "program_type": "program_type",
    "enrollmentType": "program_type",
    "schoolTags": "school_tag",
    "school_tags": "school_tag",
    "schoolTag": "school_tag",
    "majorTags": "major_tag",
    "major_tags": "major_tag",
    "majorTag": "major_tag",
    "duration": "major_tag",
    "durations": "major_tag",
    "majorDuration": "major_tag",
    "major_duration": "major_tag",
    "studyDuration": "major_tag",
    "study_duration": "major_tag",
    "majorCategory": "major_category",
    "major_category": "major_category",
    "provinceName": "province",
    "province_names": "province",
    "provinceNames": "province",
}


def normalize_attribute_filter_key(key: str) -> str:
    text = str(key or "").strip()
    return _FILTER_KEY_ALIASES.get(text, text)


def normalize_attribute_value(key: str, value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    dimension = ATTRIBUTE_REGISTRY.get(key)
    if dimension is None:
        return text
    alias_map = {_compact(alias): canonical for alias, canonical in dimension.aliases.items()}
    compact_text = _compact(text)
    if compact_text in alias_map:
        return alias_map[compact_text]
    if dimension.values:
        for candidate in dimension.values:
            if _compact(candidate) == compact_text:
                return candidate
    return text


def normalize_attribute_filter_values(key: str, values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = normalize_attribute_value(key, value)
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def attribute_label(key: str) -> str:
    dimension = ATTRIBUTE_REGISTRY.get(key)
    return dimension.label if dimension else key


def _as_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, dict):
        return _as_values(value.get("name") or value.get("label") or value.get("value"))
    if isinstance(value, (list, tuple, set)):
        values: list[str] = []
        for item in value:
            values.extend(_as_values(item))
        return values
    text = str(value or "").strip()
    return [text] if text else []


def build_item_haystack(key: str, item: dict[str, Any]) -> list[str]:
    dimension = ATTRIBUTE_REGISTRY.get(key)
    if dimension is None:
        return []
    values: list[str] = []
    for field in dimension.item_fields:
        raw = item.get(field)
        for value in _as_values(raw):
            normalized = normalize_attribute_value(key, value)
            if normalized and normalized not in values:
                values.append(normalized)
            if value and value not in values:
                values.append(value)
    if key == "program_type":
        tuition = item.get("tuitionPerYear") or item.get("tuition_per_year") or item.get("tuition")
        try:
            if int(tuition or 0) > 20000 and "高收费" not in values:
                values.append("高收费")
        except (TypeError, ValueError):
            pass
    return values


def match_item(key: str, item: dict[str, Any], target_values: list[str]) -> bool:
    normalized_targets = normalize_attribute_filter_values(key, target_values)
    if not normalized_targets:
        return True
    haystack = [_compact(value) for value in build_item_haystack(key, item)]
    if not haystack:
        return False
    for target in normalized_targets:
        compact_target = _compact(target)
        if not compact_target:
            continue
        if any(compact_target in value or value in compact_target for value in haystack):
            return True
    return False
