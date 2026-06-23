"""Plan query tool.

查询语义拆分：
- 默认先查当前方案（ordered plan，空时退到 working plan）
- 用户明确表达“还有什么可选 / 候选里 / 还能报”时，主查候选机会
- 若默认方案查询未命中，再补查候选机会，并明确区分“当前方案”与“候选机会”
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Literal

from pydantic_ai import RunContext

from app.agent.context import RequestContext
from app.domain.major_entity_resolver import resolve_major_mentions_from_text
from app.domain.school_entity_resolver import school_alias_variants
from app.tools.candidate_filter_extraction_tool import (
    extract_candidate_query_filters_async,
    normalize_candidate_query_filters_async,
)
from app.util.internal_client import (
    get_planning_state,
    get_working_plan,
    get_planning_ordered_plan,
    query_planning_candidate_pool,
)

logger = logging.getLogger(__name__)

_DEFAULT_TENANT_ID = 1
_PLAN_SCOPE = "plan"
_CANDIDATE_SCOPE = "candidate"
_PLAN_THEN_CANDIDATE_SCOPE = "plan_then_candidate"
_AUTO_SCOPE = "auto"
_MATCH_MODE_AND = "and"
_MATCH_MODE_OR = "or"
PlanQueryScope = Literal["auto", "plan", "candidate", "plan_then_candidate"]
PlanQueryMatchMode = Literal["and", "or"]

_PLAN_HINTS = (
    "当前方案",
    "方案里",
    "排序方案",
    "草稿里",
    "已选",
    "现在这版方案",
    "当前这版方案",
)
_CANDIDATE_HINTS = (
    "候选里",
    "候选中",
    "还有什么",
    "还有哪些",
    "还能报",
    "还能选",
    "可选",
    "可以考虑",
    "别的机会",
    "其他机会",
    "别的学校",
    "其他学校",
)
_STOP_PATTERNS = (
    r"^(帮我|麻烦|请)",
    r"(看一下|看下|看看|瞅瞅|查一下|查下|查查)",
    r"(当前|现在|这个|这版|这套)",
    r"(方案里|排序方案里|草稿里|候选里)",
    r"(有没有|有无|还有什么|还有哪些|都有什么|都有哪些)",
    r"(推荐一下|推荐下|推荐)",
    r"(相关的|有关的)",
    r"[？?。！!，,\s]+",
)
_GENERIC_QUERY_SUFFIXES = (
    "相关专业",
    "相关方向",
    "相关院校",
    "相关学校",
    "相关志愿",
    "相关机会",
    "专业方向",
    "专业",
    "方向",
    "院校",
    "学校",
    "志愿",
    "机会",
)
_PROVINCES = (
    "北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江",
    "上海", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南",
    "湖北", "湖南", "广东", "广西", "海南", "重庆", "四川", "贵州",
    "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆",
)
_PLAN_ACTION_QUERY_HINTS = (
    "补几个",
    "补几",
    "补满",
    "补齐",
    "还差",
    "缺的志愿",
    "缺几个",
    "加几个",
    "加入方案",
    "放进方案",
)
_TUITION_PER_YEAR_RE = re.compile(r"(?:学费[:：]?\s*)?(\d{4,6})\s*(?:元|/年)")
_NUMERIC_FILTER_KEYS = ("min_tuition_per_year", "max_tuition_per_year")


def _compact_text(value: str) -> str:
    return re.sub(r"[\s\-_/（）()【】\[\]<>《》,，。:：;；]+", "", str(value or ""))


def _normalize_text_list(values: Any) -> list[str]:
    if not values:
        return []
    if isinstance(values, str):
        text = values.strip()
        return [text] if text else []

    normalized: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _school_name_variants(name: str) -> list[str]:
    raw = str(name or "").strip()
    if not raw:
        return []
    variants = [raw]
    stripped_group = re.sub(
        r"(?:第?\d{1,3}组.*|[A-Za-z0-9]{1,3}专业组.*|\d{1,3}专业组.*)$",
        "",
        raw,
    ).strip()
    if stripped_group and stripped_group not in variants:
        variants.append(stripped_group)
    stripped_paren = re.sub(r"[（(].*?[)）]", "", stripped_group or raw).strip()
    if stripped_paren and stripped_paren not in variants:
        variants.append(stripped_paren)
    for alias in school_alias_variants(stripped_paren or stripped_group or raw):
        if alias and alias not in variants:
            variants.append(alias)
    city_college_alias = _city_college_short_alias(stripped_paren or stripped_group or raw)
    if city_college_alias and city_college_alias not in variants:
        variants.append(city_college_alias)
    return variants


def _city_college_short_alias(name: str) -> str:
    base = re.sub(r"[（(].*?[)）]", "", str(name or "")).strip()
    match = re.match(r"^(.+?)城市学院$", base)
    if not match:
        return ""
    prefix = match.group(1).strip()
    return f"{prefix[0]}城" if prefix else ""


def _looks_like_plan_action_query(query: str) -> bool:
    return any(hint in (query or "") for hint in _PLAN_ACTION_QUERY_HINTS)


def _normalize_query_text(query: str) -> str:
    normalized = (query or "").strip()
    for pattern in _STOP_PATTERNS:
        normalized = re.sub(pattern, "", normalized)
    return normalized.strip()


def _resolve_query_scope(query: str) -> str:
    normalized = (query or "").strip()
    if not normalized:
        return _PLAN_SCOPE
    if any(keyword in normalized for keyword in _CANDIDATE_HINTS):
        return _CANDIDATE_SCOPE
    if any(keyword in normalized for keyword in _PLAN_HINTS):
        return _PLAN_SCOPE
    return _PLAN_THEN_CANDIDATE_SCOPE


def _build_query_keywords(query: str) -> list[str]:
    base = _normalize_query_text(query) or (query or "").strip()
    if not base:
        return []

    keywords: list[str] = []

    def _append(value: str) -> None:
        text = str(value or "").strip()
        if text and text not in keywords:
            keywords.append(text)

    _append(base)
    current = base
    while True:
        next_value = current
        for suffix in _GENERIC_QUERY_SUFFIXES:
            if next_value.endswith(suffix) and len(next_value) > len(suffix):
                next_value = next_value[: -len(suffix)].strip()
                break
        if next_value == current:
            break
        _append(next_value)
        current = next_value

    return keywords


def _normalize_scope(scope: str | None) -> str:
    normalized = (scope or "").strip().lower().replace("-", "_")
    if normalized in {"", _AUTO_SCOPE}:
        return _AUTO_SCOPE
    if normalized in {_PLAN_SCOPE, _CANDIDATE_SCOPE, _PLAN_THEN_CANDIDATE_SCOPE}:
        return normalized
    return _AUTO_SCOPE


def _normalize_match_mode(match_mode: str | None) -> str:
    normalized = (match_mode or "").strip().lower()
    if normalized == _MATCH_MODE_OR:
        return _MATCH_MODE_OR
    return _MATCH_MODE_AND


def _latest_user_message(ctx: RunContext[RequestContext]) -> str:
    for item in reversed(getattr(ctx.deps, "chat_history", None) or []):
        if item.get("role") == "user":
            return str(item.get("content") or "").strip()
    return ""


def _candidate_filter_source_text(ctx: RunContext[RequestContext], query: str) -> str:
    parts = [str(query or "").strip(), _latest_user_message(ctx)]
    merged: list[str] = []
    for part in parts:
        if part and part not in merged:
            merged.append(part)
    return " ".join(merged)


def _append_query_observability(
    ctx: RunContext[RequestContext],
    *,
    session_id: str,
    requested_scope: str,
    resolved_scope: str,
    has_structured_filters: bool,
    filter_keys: list[str],
    timings: list[dict[str, Any]],
    total_duration_ms: int,
    status: str,
) -> None:
    observability = getattr(getattr(ctx, "deps", None), "agent_observability", None)
    if not isinstance(observability, dict):
        return
    observability.setdefault("toolInternalTimings", []).append(
        {
            "tool": "query_volunteer_plan",
            "sessionId": session_id,
            "requestedScope": requested_scope,
            "resolvedScope": resolved_scope,
            "status": status,
            "durationMs": total_duration_ms,
            "hasStructuredFilters": has_structured_filters,
            "filterKeys": filter_keys,
            "steps": timings,
        }
    )


def _filter_keys(filters: dict[str, Any]) -> list[str]:
    return [key for key, values in filters.items() if values]


def _normalize_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = int(value)
        return numeric if numeric > 0 else None
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"\d{4,6}", text)
    if not match:
        return None
    numeric = int(match.group(0))
    return numeric if numeric > 0 else None


def _plan_item_tuition_per_year(item: dict[str, Any]) -> int | None:
    raw_value = item.get("tuitionPerYear")
    parsed = _normalize_optional_int(raw_value)
    if parsed is not None:
        return parsed
    text_sources: list[str] = [
        str(item.get("majorName") or ""),
        *(str(value or "") for value in (item.get("majorPlanTags") or [])),
        *(str(value or "") for value in (item.get("reasonCodes") or [])),
    ]
    for text in text_sources:
        match = _TUITION_PER_YEAR_RE.search(text)
        if match:
            return _normalize_optional_int(match.group(1))
    return None


def _matches_tuition_range(
    item: dict[str, Any],
    *,
    min_tuition: int | None,
    max_tuition: int | None,
) -> bool:
    if min_tuition is None and max_tuition is None:
        return True
    tuition = _plan_item_tuition_per_year(item)
    if tuition is None:
        return False
    if min_tuition is not None and tuition < min_tuition:
        return False
    if max_tuition is not None and tuition > max_tuition:
        return False
    return True


def _has_tuition_range_filter(filters: dict[str, Any]) -> bool:
    return (
        _normalize_optional_int(filters.get("min_tuition_per_year")) is not None
        or _normalize_optional_int(filters.get("max_tuition_per_year")) is not None
    )


async def _timed_async_step(
    timings: list[dict[str, Any]],
    name: str,
    func: Any,
    *args: Any,
    **kwargs: Any,
) -> Any:
    started_at = time.perf_counter()
    try:
        return await func(*args, **kwargs)
    finally:
        timings.append(
            {
                "step": name,
                "durationMs": int((time.perf_counter() - started_at) * 1000),
            }
        )


def _infer_query_focus(query: str, normalized_query: str) -> str:
    text = f"{query} {normalized_query}"
    if any(keyword in text for keyword in ("大学", "学院", "学校", "专业组")):
        return "school"
    if any(province in text for province in _PROVINCES):
        return "province"
    return "major"


def _match_text(haystacks: list[str], keyword: str) -> bool:
    if not keyword:
        return False
    return any(keyword in item for item in haystacks if item)


def _matches_query(item: dict[str, Any], keyword: str) -> bool:
    if not keyword:
        return False
    school_variants = _school_name_variants(str(item.get("schoolName") or ""))
    major_name = str(item.get("majorName") or "")
    haystacks: list[str] = [
        *school_variants,
        major_name,
        str(item.get("provinceName") or ""),
        str(item.get("cityName") or ""),
        str(item.get("tier") or ""),
    ]
    haystacks.extend(str(tag) for tag in item.get("schoolRankTags") or [])
    haystacks.extend(str(tag) for tag in item.get("schoolBasicTags") or [])
    haystacks.extend(str(tag) for tag in item.get("majorRankTags") or [])
    haystacks.extend(str(tag) for tag in item.get("majorPlanTags") or [])
    if _match_text(haystacks, keyword):
        return True

    compact_keyword = _compact_text(keyword)
    if not compact_keyword:
        return False
    if any(compact_keyword in _compact_text(item) for item in haystacks if item):
        return True
    school_compacts = [
        _compact_text(school_name)
        for school_name in school_variants
        if len(_compact_text(school_name)) >= 3
    ]
    if any(compact_school and compact_school in compact_keyword for compact_school in school_compacts):
        return True

    combined_texts = [
        f"{school_name}-{major_name}"
        for school_name in school_variants
        if school_name and major_name
    ]
    return any(compact_keyword in _compact_text(text) for text in combined_texts)


def _matches_any_query_keyword(item: dict[str, Any], keywords: list[str]) -> bool:
    return any(_matches_query(item, keyword) for keyword in keywords if keyword)


def _match_plan_items_by_query(
    items: list[dict[str, Any]],
    query_keywords: list[str],
) -> tuple[list[dict[str, Any]], str]:
    matched = [item for item in items if _matches_any_query_keyword(item, query_keywords)]
    if matched:
        return matched, ""

    alias_matched, alias_names, alias_sources = _school_alias_matches_from_query(items, query_keywords)
    if not alias_matched:
        return [], ""

    source_keywords = "、".join(alias_sources[:3])
    target_names = "、".join(alias_names[:3])
    return alias_matched, f"按当前方案里的院校简称“{source_keywords}”匹配到{target_names}。"


def _school_alias_matches_from_query(
    items: list[dict[str, Any]],
    query_keywords: list[str],
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    query_compacts = [
        _compact_text(keyword)
        for keyword in query_keywords
        if _compact_text(keyword)
    ]
    if not query_compacts:
        return [], [], []

    matched: list[dict[str, Any]] = []
    matched_names: list[str] = []
    matched_sources: list[str] = []
    for item in items:
        school_name = str(item.get("schoolName") or "").strip()
        if not school_name:
            continue
        variants = _school_name_variants(school_name)
        if len(variants) <= 1:
            continue
        for alias in variants[1:]:
            compact_alias = _compact_text(alias)
            if len(compact_alias) < 2:
                continue
            if not any(compact_alias in compact_query for compact_query in query_compacts):
                continue
            if item not in matched:
                matched.append(item)
            canonical = variants[0] if variants and variants[0] else school_name
            if canonical not in matched_names:
                matched_names.append(canonical)
            if alias not in matched_sources:
                matched_sources.append(alias)
            break
    return matched, matched_names, matched_sources


def _has_structured_filters(filters: dict[str, Any]) -> bool:
    return any(filters.get(key) for key in (
        "tiers",
        "province_names",
        "city_names",
        "school_keywords",
        "major_keywords",
        "school_tags",
        "major_tags",
        "min_tuition_per_year",
        "max_tuition_per_year",
    ))


def _match_values(haystacks: list[str], needles: list[str]) -> bool:
    if not haystacks or not needles:
        return False
    for needle in needles:
        if _match_text(haystacks, needle):
            return True
        compact_needle = _compact_text(needle)
        if compact_needle and any(compact_needle in _compact_text(value) for value in haystacks if value):
            return True
    return False


def _matches_structured_filters(
    item: dict[str, Any],
    filters: dict[str, Any],
    *,
    match_mode: str,
) -> bool:
    school_values = _school_name_variants(str(item.get("schoolName") or ""))
    major_values = [
        str(item.get("majorName") or ""),
        str(item.get("majorCategory") or ""),
        str(item.get("majorDiscipline") or ""),
    ]
    province_values = [str(item.get("provinceName") or "")]
    city_values = [str(item.get("cityName") or "")]
    school_tag_values = [
        str(item.get("schoolNature") or ""),
        str(item.get("schoolCategory") or ""),
        str(item.get("schoolLevel") or ""),
        *(str(tag) for tag in item.get("schoolRankTags") or []),
        *(str(tag) for tag in item.get("schoolBasicTags") or []),
        *(str(tag) for tag in item.get("schoolPopupTags") or []),
    ]
    major_tag_values = [
        str(item.get("majorDiscipline") or ""),
        str(item.get("majorCategory") or ""),
        *(str(tag) for tag in item.get("majorRankTags") or []),
        *(str(tag) for tag in item.get("majorPlanTags") or []),
    ]
    tier_values = [
        str(item.get("tier") or ""),
        str(item.get("subTier") or ""),
        str(item.get("majorTier") or ""),
    ]

    checks: list[bool] = []
    if filters.get("province_names"):
        checks.append(_match_values(province_values, filters["province_names"]))
    if filters.get("city_names"):
        checks.append(_match_values(city_values, filters["city_names"]))
    if filters.get("school_keywords"):
        checks.append(_match_values(school_values, filters["school_keywords"]))
    if filters.get("major_keywords"):
        checks.append(_match_values(major_values, filters["major_keywords"]))
    if filters.get("school_tags"):
        checks.append(_match_values(school_tag_values, filters["school_tags"]))
    if filters.get("major_tags"):
        checks.append(_match_values(major_tag_values, filters["major_tags"]))
    if filters.get("tiers"):
        checks.append(_match_values(tier_values, filters["tiers"]))
    min_tuition = _normalize_optional_int(filters.get("min_tuition_per_year"))
    max_tuition = _normalize_optional_int(filters.get("max_tuition_per_year"))
    if min_tuition is not None or max_tuition is not None:
        checks.append(_matches_tuition_range(item, min_tuition=min_tuition, max_tuition=max_tuition))

    if not checks:
        return False
    if match_mode == _MATCH_MODE_OR:
        return any(checks)
    return all(checks)


def _is_empty_value(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _merge_plan_item(plan_item: dict[str, Any], candidate_item: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(candidate_item or {})
    for key, value in (plan_item or {}).items():
        if not _is_empty_value(value):
            merged[key] = value
        elif key not in merged:
            merged[key] = value
    return merged or dict(plan_item or {})


def _describe_structured_filters(filters: dict[str, Any], fallback_query: str) -> str:
    parts: list[str] = []
    if filters.get("school_keywords"):
        parts.append("院校:" + "、".join(filters["school_keywords"]))
    if filters.get("major_keywords"):
        parts.append("专业:" + "、".join(filters["major_keywords"]))
    if filters.get("province_names"):
        parts.append("省份:" + "、".join(filters["province_names"]))
    if filters.get("city_names"):
        parts.append("城市:" + "、".join(filters["city_names"]))
    if filters.get("school_tags"):
        parts.append("院校标签:" + "、".join(filters["school_tags"]))
    if filters.get("major_tags"):
        parts.append("专业标签:" + "、".join(filters["major_tags"]))
    if filters.get("tiers"):
        parts.append("层级:" + "、".join(filters["tiers"]))
    min_tuition = _normalize_optional_int(filters.get("min_tuition_per_year"))
    max_tuition = _normalize_optional_int(filters.get("max_tuition_per_year"))
    if min_tuition is not None:
        parts.append(f"学费不少于{min_tuition}元/年")
    if max_tuition is not None:
        parts.append(f"学费不超过{max_tuition}元/年")
    if parts:
        return "；".join(parts)
    return fallback_query or "当前筛选条件"


def _format_ratio(value: Any) -> str:
    if value is None:
        return "-"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "-"
    if numeric < 0:
        return "-"
    return f"{int(numeric)}%" if numeric.is_integer() else f"{numeric:.1f}%"


def _candidate_ratio_value(item: dict[str, Any]) -> Any:
    if item.get("admissionRatio") is not None:
        return item.get("admissionRatio")
    if item.get("schoolEnrollRatio") is not None:
        return item.get("schoolEnrollRatio")
    return item.get("enrollRatio")


def _format_tuition(value: Any) -> str | None:
    if value is None:
        return None
    try:
        amount = int(float(value))
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    return f"学费{amount}元/年"


def _append_unique(parts: list[str], value: Any) -> None:
    text = str(value or "").strip()
    if text and text not in parts:
        parts.append(text)


def _build_plan_item_snippet(item: dict[str, Any]) -> str:
    school_name = item.get("schoolName") or "未知院校"
    major_name = item.get("majorName") or "未知专业"
    tier = item.get("tier") or "未知"
    ratio = _format_ratio(item.get("admissionRatio"))
    return f"{school_name}-{major_name}（{tier}，录取率{ratio}）"


def _build_candidate_item_snippet(item: dict[str, Any]) -> str:
    school_name = item.get("schoolName") or "未知院校"
    major_name = item.get("majorName") or "未知专业"
    tier = item.get("tier") or "未知"
    ratio = _format_ratio(_candidate_ratio_value(item))
    detail_parts = [tier]
    if ratio != "-":
        detail_parts.append(f"录取率{ratio}")
    _append_unique(detail_parts, item.get("provinceName"))
    _append_unique(detail_parts, item.get("cityName"))
    _append_unique(detail_parts, item.get("schoolNature"))
    tuition = _format_tuition(item.get("tuitionPerYear"))
    if tuition:
        detail_parts.append(tuition)
    return f"{school_name}-{major_name}（{'，'.join(detail_parts)}）"


def _extract_plan_items(response: dict[str, Any]) -> list[dict[str, Any]]:
    return (response.get("data") or {}).get("items") or []


async def _normalize_local_query_filters_async(
    *,
    batch: str,
    tiers: list[str] | None = None,
    province_names: list[str] | None = None,
    city_names: list[str] | None = None,
    school_keywords: list[str] | None = None,
    major_keywords: list[str] | None = None,
    school_tags: list[str] | None = None,
    major_tags: list[str] | None = None,
    min_tuition_per_year: int | None = None,
    max_tuition_per_year: int | None = None,
) -> dict[str, Any]:
    normalized = await normalize_candidate_query_filters_async(
        {
            "tiers": tiers,
            "province_names": province_names,
            "city_names": city_names,
            "school_keywords": school_keywords,
            "major_keywords": major_keywords,
            "school_tags": school_tags,
            "major_tags": major_tags,
        },
        batch=batch,
    )
    normalized["min_tuition_per_year"] = _normalize_optional_int(min_tuition_per_year)
    normalized["max_tuition_per_year"] = _normalize_optional_int(max_tuition_per_year)
    return normalized


def _merge_structured_filters(
    primary: dict[str, Any],
    supplemental: dict[str, Any],
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for key in (
        "tiers",
        "province_names",
        "city_names",
        "school_keywords",
        "major_keywords",
        "school_tags",
        "major_tags",
    ):
        values: list[str] = []
        for value in [*(primary.get(key) or []), *(supplemental.get(key) or [])]:
            text = str(value or "").strip()
            if text and text not in values:
                values.append(text)
        merged[key] = values
    for key in _NUMERIC_FILTER_KEYS:
        merged[key] = _normalize_optional_int(primary.get(key)) or _normalize_optional_int(supplemental.get(key))
    return merged


def _merge_filter_lists(base: list[str], extra: list[str]) -> list[str]:
    merged: list[str] = []
    for value in [*(base or []), *(extra or [])]:
        text = str(value or "").strip()
        if text and text not in merged:
            merged.append(text)
    return merged


def _supplement_major_keywords_from_mentions(
    filters: dict[str, list[str]],
    text: str,
    *,
    batch: str,
) -> dict[str, list[str]]:
    """Use the shared catalog resolver to fill major aliases omitted by LLM extraction.

    This is not a route shortcut. It only reconciles already selected candidate
    query filters so short forms such as “会计审计” or “计科” do not lose one of
    the mentioned majors.
    """
    if not filters.get("major_keywords"):
        return filters

    mentions = resolve_major_mentions_from_text(text, batch)
    if not mentions:
        return filters

    additions: list[str] = []
    for mention in mentions:
        if mention.level not in {"level2", "level3"}:
            continue
        name = str(mention.canonical_name or "").strip()
        if name and name not in additions:
            additions.append(name)
    if not additions:
        return filters

    updated = dict(filters)
    updated["major_keywords"] = _merge_filter_lists(filters.get("major_keywords") or [], additions)
    return updated


def _drop_major_keywords_shadowed_by_school_tags(
    filters: dict[str, list[str]],
    supplemental_filters: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Avoid turning an institution-type query into a stricter major query.

    The main model may pass values such as 师范 as a major keyword even when
    the shared extractor has identified the same phrase as a school tag from
    wording like 师范类院校/师范类机会. Keeping both becomes an AND filter and can
    hide valid school-category opportunities. This only reconciles structured
    fields after extraction; it is not a route or keyword fast path.
    """
    school_tags = {str(tag or "").strip() for tag in supplemental_filters.get("school_tags") or [] if str(tag or "").strip()}
    if not school_tags or not filters.get("major_keywords"):
        return filters

    cleaned = dict(filters)
    cleaned["major_keywords"] = [
        keyword
        for keyword in filters.get("major_keywords") or []
        if str(keyword or "").strip() not in school_tags
    ]
    return cleaned


async def _extract_query_filters_for_candidate_scope(
    query: str,
    *,
    batch: str,
) -> dict[str, list[str]]:
    if not str(query or "").strip():
        return {}
    try:
        extracted = await extract_candidate_query_filters_async(query, batch=batch)
    except Exception:
        logger.warning("candidate query filter extraction failed: query=%s", query, exc_info=True)
        return {}
    filters = extracted.get("filters") or {}
    if not extracted.get("should_query_candidate") and not _has_structured_filters(filters):
        return {}
    return filters


def _format_plan_result(title: str, items: list[dict[str, Any]], display_keyword: str, query_keywords: list[str]) -> str:
    if not items:
        return f"{title}里还没有可查询的志愿。"
    if display_keyword:
        matched, alias_note = _match_plan_items_by_query(items, query_keywords)
        if matched:
            examples = matched[:5]
            snippets = "；".join(_build_plan_item_snippet(item) for item in examples)
            prefix = f"{alias_note}\n" if alias_note else ""
            return prefix + (
                f"{title}里共命中了 {len(matched)} 条和“{display_keyword}”相关的志愿。"
                f"下面仅展示前 {len(examples)} 条示例：{snippets}"
            )
        return f"{title}里暂时没有命中“{display_keyword}”的志愿。"
    snippets = "；".join(_build_plan_item_snippet(item) for item in items[:5])
    return f"{title}前几项是：{snippets}"


async def _query_candidate_opportunities(
    session_id: str,
    query: str,
    lookup_keyword: str,
) -> dict[str, Any]:
    focus = _infer_query_focus(query, lookup_keyword)
    request_kwargs: dict[str, Any] = {
        "page": 1,
        "page_size": 20,
        "sort_field": "finalScore",
        "sort_order": "desc",
    }
    if lookup_keyword:
        if focus == "school":
            request_kwargs["school_keywords"] = [lookup_keyword]
        elif focus == "province":
            request_kwargs["province_names"] = [lookup_keyword]
        else:
            request_kwargs["major_keywords"] = [lookup_keyword]
    return await query_planning_candidate_pool(
        _DEFAULT_TENANT_ID,
        session_id,
        **request_kwargs,
    )


async def _query_candidate_opportunities_with_filters(
    session_id: str,
    filters: dict[str, list[str]],
) -> dict[str, Any]:
    logger.info("query candidate opportunities with filters: session_id=%s filters=%s", session_id, filters)
    return await query_planning_candidate_pool(
        _DEFAULT_TENANT_ID,
        session_id,
        tiers=filters.get("tiers"),
        province_names=filters.get("province_names"),
        city_names=filters.get("city_names"),
        school_keywords=filters.get("school_keywords"),
        major_keywords=filters.get("major_keywords"),
        school_tags=filters.get("school_tags"),
        major_tags=filters.get("major_tags"),
        page=1,
        page_size=20,
        sort_field="finalScore",
        sort_order="desc",
    )


def _format_candidate_result(response: dict[str, Any], keyword: str) -> str:
    data = response.get("data") or {}
    items = data.get("items") or []
    total = data.get("total") or 0
    if not items:
        return (
            f"候选里暂时没有筛到和“{keyword}”相关的机会。"
            "这表示当前候选池按这个条件没有命中，不是系统延迟或查询失败。"
        )
    examples = items[:5]
    snippets = "；".join(_build_candidate_item_snippet(item) for item in examples)
    return (
        f"候选里共命中了 {total} 条和“{keyword}”相关的机会。"
        f"下面仅展示前 {len(examples)} 条示例：{snippets}"
    )


async def _load_current_plan(session_id: str) -> tuple[str, list[dict[str, Any]]]:
    ordered_result = await get_planning_ordered_plan(session_id)
    ordered_items = _extract_plan_items(ordered_result)
    if ordered_result.get("code") == 0 and ordered_items:
        return "当前方案", ordered_items

    working_result = await get_working_plan(session_id)
    working_items = _extract_plan_items(working_result)
    if working_result.get("code") == 0 and working_items:
        return "当前已加入方案", working_items

    return "当前方案", []


async def _enrich_plan_items_with_candidate_metadata(
    session_id: str,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not items:
        return items
    try:
        planning_state_resp = await get_planning_state(session_id)
        planning_state = (planning_state_resp or {}).get("data") or {}
        candidate_items = ((planning_state.get("candidatePoolState") or {}).get("items")) or []
        candidate_by_id = {
            item.get("volunteerId"): item
            for item in candidate_items
            if item.get("volunteerId")
        }
        return [
            _merge_plan_item(item, candidate_by_id.get(item.get("volunteerId")))
            for item in items
        ]
    except Exception:
        logger.warning("Failed to enrich plan items with candidate metadata: session_id=%s", session_id, exc_info=True)
        return items


def _format_structured_plan_result(
    title: str,
    items: list[dict[str, Any]],
    description: str,
    filters: dict[str, list[str]],
    *,
    match_mode: str,
) -> str:
    if not items:
        return f"{title}里还没有可查询的志愿。"
    matched = [item for item in items if _matches_structured_filters(item, filters, match_mode=match_mode)]
    alias_note = ""
    if not matched:
        alias_filters, alias_names, alias_source_keywords = _school_alias_fallback_filters(filters, items)
        if alias_filters:
            fallback_matched = [
                item for item in items if _matches_structured_filters(item, alias_filters, match_mode=match_mode)
            ]
            if fallback_matched:
                matched = fallback_matched
                description = _describe_structured_filters(alias_filters, description)
                source_keywords = "、".join(alias_source_keywords)
                target_names = "、".join(alias_names[:3])
                alias_note = (
                    f"按当前方案里的院校简称“{source_keywords}”匹配到{target_names}；"
                    "原先可能冲突的地域条件没有参与这次院校命中。"
                )
    if matched:
        examples = matched[:5]
        snippets = "；".join(_build_plan_item_snippet(item) for item in examples)
        prefix = f"{alias_note}\n" if alias_note else ""
        return prefix + (
            f"{title}里共命中了 {len(matched)} 条符合“{description}”的志愿。"
            f"下面仅展示前 {len(examples)} 条示例：{snippets}"
        )
    return f"{title}里暂时没有命中符合“{description}”的志愿。"


def _school_alias_fallback_filters(
    filters: dict[str, list[str]],
    items: list[dict[str, Any]],
) -> tuple[dict[str, list[str]] | None, list[str], list[str]]:
    school_keywords = [str(item or "").strip() for item in filters.get("school_keywords") or [] if str(item or "").strip()]
    location_keywords = [
        str(item or "").strip()
        for item in [*(filters.get("province_names") or []), *(filters.get("city_names") or [])]
        if str(item or "").strip()
    ]
    source_keywords = _merge_filter_lists(school_keywords, location_keywords)
    if not source_keywords:
        return None, [], []

    matched_names: list[str] = []
    matched_sources: list[str] = []
    keyword_compacts = {keyword: _compact_text(keyword) for keyword in source_keywords}
    for item in items:
        school_name = str(item.get("schoolName") or "").strip()
        if not school_name:
            continue
        variants = _school_name_variants(school_name)
        if len(variants) <= 1:
            continue
        alias_compacts = {_compact_text(alias) for alias in variants[1:] if _compact_text(alias)}
        if not alias_compacts:
            continue
        matched_keywords = [
            keyword
            for keyword, compact in keyword_compacts.items()
            if compact and compact in alias_compacts
        ]
        if matched_keywords:
            canonical = variants[0] if variants and variants[0] else school_name
            if canonical not in matched_names:
                matched_names.append(canonical)
            for keyword in matched_keywords:
                if keyword not in matched_sources:
                    matched_sources.append(keyword)

    if not matched_names:
        return None, [], []

    fallback = dict(filters)
    fallback["province_names"] = []
    fallback["city_names"] = []
    fallback["school_keywords"] = _merge_filter_lists(matched_sources or school_keywords, matched_names)
    return fallback, matched_names, matched_sources or school_keywords


def _format_structured_candidate_result(response: dict[str, Any], description: str) -> str:
    data = response.get("data") or {}
    items = data.get("items") or []
    total = data.get("total") or 0
    if not items:
        return (
            f"候选里暂时没有筛到符合“{description}”的机会。"
            "这表示当前候选池按这个条件没有命中，不是系统延迟或查询失败。"
            "如果你想继续看，可以把条件放宽一点，比如去掉稳/保限制、扩大到同一专业类，或者让我回到当前方案里找相近项。"
        )
    examples = items[:5]
    snippets = "；".join(_build_candidate_item_snippet(item) for item in examples)
    return (
        f"候选里共命中了 {total} 条符合“{description}”的机会。"
        f"下面仅展示前 {len(examples)} 条示例：{snippets}"
    )


async def query_volunteer_plan(
    ctx: RunContext[RequestContext],
    query: str = "",
    scope: PlanQueryScope = _AUTO_SCOPE,
    tiers: list[str] | None = None,
    province_names: list[str] | None = None,
    city_names: list[str] | None = None,
    school_keywords: list[str] | None = None,
    major_keywords: list[str] | None = None,
    school_tags: list[str] | None = None,
    major_tags: list[str] | None = None,
    min_tuition_per_year: int | None = None,
    max_tuition_per_year: int | None = None,
    match_mode: PlanQueryMatchMode = _MATCH_MODE_AND,
) -> str:
    """围绕当前方案与候选机会进行局部命中查询。

    只适合回答“当前方案里有没有某学校/专业/地域”“候选里还有没有某方向机会”。
    用户用院校简称、专业简称、模糊代称或口语化局部查看时（如“青城那个是不是放多了，能查下”
    “会计审计还有吗”“北京那几个多不多”），也应把原始 query 传给本工具；工具会结合当前方案真实名称、
    候选筛选和别名变体做局部命中查询。不要把这类局部查看改成整体 `query_state` 概览，也不要自行猜测简称含义。
    不适合回答“还差几个怎么补、补几个更稳的、怎么补满、加入方案”这类会改变方案或规划补齐动作的问题；
    这类问题应走 Plan 主链路规划 preview_fix_proposal/add_units，并在用户确认后执行。
    也不适合在移动/删除前作为“定位 ID”的前置步骤；`move_unit/remove_units/add_units`
    的 `volunteer_ids` 可以直接填写用户原始学校+专业引用，执行层会解析真实 ID 并处理歧义。

    当 `scope=auto` 时，兼容旧行为，仍会根据 query 做启发式判断。
    更推荐由模型显式传入：
    - `plan`
    - `candidate`
    - `plan_then_candidate`
    - 以及结构化 filters，如 `province_names / school_keywords / major_keywords / school_tags / major_tags`。
      `min_tuition_per_year / max_tuition_per_year` 当前用于本地 current plan 查询；候选池学费过滤需要后端
      contract 支持后再打开。
    """
    session_id = ctx.deps.sessionid
    batch = getattr(ctx.deps, "batch", None) or "01"
    requested_scope = str(scope or _AUTO_SCOPE)
    timings: list[dict[str, Any]] = []
    tool_started_at = time.perf_counter()
    normalized_scope = _AUTO_SCOPE
    has_structured_filters = False
    structured_filters: dict[str, list[str]] = {}
    logger.info("query_volunteer_plan called: session_id=%s, query=%s, scope=%s", session_id, query, scope)

    if _looks_like_plan_action_query(query):
        _append_query_observability(
            ctx,
            session_id=session_id,
            requested_scope=requested_scope,
            resolved_scope="plan_action_rejected",
            has_structured_filters=False,
            filter_keys=[],
            timings=timings,
            total_duration_ms=int((time.perf_counter() - tool_started_at) * 1000),
            status="rejected_plan_action_query",
        )
        return "这是补齐或调整当前方案的动作诉求，不是局部查询；应先走方案动作预览，用户确认后再执行。"

    structured_filters = await _timed_async_step(
        timings,
        "normalize_explicit_filters",
        _normalize_local_query_filters_async,
        batch=batch,
        tiers=tiers,
        province_names=province_names,
        city_names=city_names,
        school_keywords=school_keywords,
        major_keywords=major_keywords,
        school_tags=school_tags,
        major_tags=major_tags,
        min_tuition_per_year=min_tuition_per_year,
        max_tuition_per_year=max_tuition_per_year,
    )
    has_structured_filters = _has_structured_filters(structured_filters)
    normalized_match_mode = _normalize_match_mode(match_mode)

    query_keywords = _build_query_keywords(query)
    display_keyword = query_keywords[0] if query_keywords else ((query or "").strip())
    lookup_keyword = query_keywords[-1] if query_keywords else display_keyword
    normalized_scope = _normalize_scope(scope)
    if normalized_scope == _AUTO_SCOPE:
        normalized_scope = _resolve_query_scope(query)
    if normalized_scope in {_CANDIDATE_SCOPE, _PLAN_THEN_CANDIDATE_SCOPE}:
        candidate_filter_text = _candidate_filter_source_text(ctx, query)
        extracted_filters = await _timed_async_step(
            timings,
            "extract_candidate_filters",
            _extract_query_filters_for_candidate_scope,
            candidate_filter_text,
            batch=batch,
        )
        if extracted_filters:
            structured_filters = _merge_structured_filters(structured_filters, extracted_filters)
            structured_filters = _drop_major_keywords_shadowed_by_school_tags(structured_filters, extracted_filters)
            has_structured_filters = _has_structured_filters(structured_filters)
        structured_filters = _supplement_major_keywords_from_mentions(
            structured_filters,
            candidate_filter_text,
            batch=batch,
        )
        has_structured_filters = _has_structured_filters(structured_filters)
    if normalized_scope == _CANDIDATE_SCOPE and _has_tuition_range_filter(structured_filters):
        _append_query_observability(
            ctx,
            session_id=session_id,
            requested_scope=requested_scope,
            resolved_scope=normalized_scope,
            has_structured_filters=has_structured_filters,
            filter_keys=_filter_keys(structured_filters),
            timings=timings,
            total_duration_ms=int((time.perf_counter() - tool_started_at) * 1000),
            status="unsupported_candidate_tuition_range_filter",
        )
        return "候选池暂时不能按学费区间做精确筛选；这类学费范围查询目前可以先在当前方案里看命中数量和示例。"
    filter_description = _describe_structured_filters(structured_filters, (query or "").strip())

    try:
        if has_structured_filters:
            if normalized_scope == _CANDIDATE_SCOPE:
                candidate_result = await _timed_async_step(
                    timings,
                    "query_candidate_with_filters",
                    _query_candidate_opportunities_with_filters,
                    session_id,
                    structured_filters,
                )
                status = "candidate_query_failed" if candidate_result.get("code") != 0 else "success"
                _append_query_observability(
                    ctx,
                    session_id=session_id,
                    requested_scope=requested_scope,
                    resolved_scope=normalized_scope,
                    has_structured_filters=has_structured_filters,
                    filter_keys=_filter_keys(structured_filters),
                    timings=timings,
                    total_duration_ms=int((time.perf_counter() - tool_started_at) * 1000),
                    status=status,
                )
                if candidate_result.get("code") != 0:
                    return "查询候选机会失败，请稍后重试。"
                return _format_structured_candidate_result(candidate_result, filter_description)

            plan_title, plan_items = await _timed_async_step(
                timings,
                "load_current_plan",
                _load_current_plan,
                session_id,
            )
            plan_items = await _timed_async_step(
                timings,
                "enrich_plan_items_with_candidate_metadata",
                _enrich_plan_items_with_candidate_metadata,
                session_id,
                plan_items,
            )
            plan_text = _format_structured_plan_result(
                plan_title,
                plan_items,
                filter_description,
                structured_filters,
                match_mode=normalized_match_mode,
            )
            if normalized_scope == _PLAN_SCOPE:
                _append_query_observability(
                    ctx,
                    session_id=session_id,
                    requested_scope=requested_scope,
                    resolved_scope=normalized_scope,
                    has_structured_filters=has_structured_filters,
                    filter_keys=_filter_keys(structured_filters),
                    timings=timings,
                    total_duration_ms=int((time.perf_counter() - tool_started_at) * 1000),
                    status="success",
                )
                return plan_text

            matched_plan_items = [
                item
                for item in plan_items
                if _matches_structured_filters(item, structured_filters, match_mode=normalized_match_mode)
            ]
            if matched_plan_items:
                _append_query_observability(
                    ctx,
                    session_id=session_id,
                    requested_scope=requested_scope,
                    resolved_scope=normalized_scope,
                    has_structured_filters=has_structured_filters,
                    filter_keys=_filter_keys(structured_filters),
                    timings=timings,
                    total_duration_ms=int((time.perf_counter() - tool_started_at) * 1000),
                    status="success_plan_hit",
                )
                return plan_text

            candidate_result = await _timed_async_step(
                timings,
                "query_candidate_with_filters",
                _query_candidate_opportunities_with_filters,
                session_id,
                structured_filters,
            )
            if candidate_result.get("code") != 0:
                _append_query_observability(
                    ctx,
                    session_id=session_id,
                    requested_scope=requested_scope,
                    resolved_scope=normalized_scope,
                    has_structured_filters=has_structured_filters,
                    filter_keys=_filter_keys(structured_filters),
                    timings=timings,
                    total_duration_ms=int((time.perf_counter() - tool_started_at) * 1000),
                    status="candidate_query_failed_after_plan_miss",
                )
                return plan_text
            candidate_text = _format_structured_candidate_result(candidate_result, filter_description)
            _append_query_observability(
                ctx,
                session_id=session_id,
                requested_scope=requested_scope,
                resolved_scope=normalized_scope,
                has_structured_filters=has_structured_filters,
                filter_keys=_filter_keys(structured_filters),
                timings=timings,
                total_duration_ms=int((time.perf_counter() - tool_started_at) * 1000),
                status="success_plan_miss_candidate_checked",
            )
            return (
                f"{plan_text}\n"
                f"{candidate_text}\n"
                "如果你想继续，我可以再基于这组条件帮你只看更稳的、录取率更高的，或者继续判断是否值得纳入当前方案。"
            )

        if normalized_scope == _CANDIDATE_SCOPE:
            candidate_result = await _timed_async_step(
                timings,
                "query_candidate_keyword",
                _query_candidate_opportunities,
                session_id,
                query,
                lookup_keyword,
            )
            status = "candidate_query_failed" if candidate_result.get("code") != 0 else "success"
            _append_query_observability(
                ctx,
                session_id=session_id,
                requested_scope=requested_scope,
                resolved_scope=normalized_scope,
                has_structured_filters=has_structured_filters,
                filter_keys=_filter_keys(structured_filters),
                timings=timings,
                total_duration_ms=int((time.perf_counter() - tool_started_at) * 1000),
                status=status,
            )
            if candidate_result.get("code") != 0:
                return "查询候选机会失败，请稍后重试。"
            return _format_candidate_result(candidate_result, display_keyword)

        plan_title, plan_items = await _timed_async_step(
            timings,
            "load_current_plan",
            _load_current_plan,
            session_id,
        )
        plan_text = _format_plan_result(plan_title, plan_items, display_keyword, query_keywords)

        if normalized_scope == _PLAN_SCOPE:
            _append_query_observability(
                ctx,
                session_id=session_id,
                requested_scope=requested_scope,
                resolved_scope=normalized_scope,
                has_structured_filters=has_structured_filters,
                filter_keys=_filter_keys(structured_filters),
                timings=timings,
                total_duration_ms=int((time.perf_counter() - tool_started_at) * 1000),
                status="success",
            )
            return plan_text

        matched_plan_items, _ = _match_plan_items_by_query(plan_items, query_keywords)
        if matched_plan_items:
            _append_query_observability(
                ctx,
                session_id=session_id,
                requested_scope=requested_scope,
                resolved_scope=normalized_scope,
                has_structured_filters=has_structured_filters,
                filter_keys=_filter_keys(structured_filters),
                timings=timings,
                total_duration_ms=int((time.perf_counter() - tool_started_at) * 1000),
                status="success_plan_hit",
            )
            return plan_text

        candidate_result = await _timed_async_step(
            timings,
            "query_candidate_keyword",
            _query_candidate_opportunities,
            session_id,
            query,
            lookup_keyword,
        )
        if candidate_result.get("code") != 0:
            _append_query_observability(
                ctx,
                session_id=session_id,
                requested_scope=requested_scope,
                resolved_scope=normalized_scope,
                has_structured_filters=has_structured_filters,
                filter_keys=_filter_keys(structured_filters),
                timings=timings,
                total_duration_ms=int((time.perf_counter() - tool_started_at) * 1000),
                status="candidate_query_failed_after_plan_miss",
            )
            return plan_text
        candidate_text = _format_candidate_result(candidate_result, display_keyword)
        _append_query_observability(
            ctx,
            session_id=session_id,
            requested_scope=requested_scope,
            resolved_scope=normalized_scope,
            has_structured_filters=has_structured_filters,
            filter_keys=_filter_keys(structured_filters),
            timings=timings,
            total_duration_ms=int((time.perf_counter() - tool_started_at) * 1000),
            status="success_plan_miss_candidate_checked",
        )
        return (
            f"{plan_text}\n"
            f"{candidate_text}\n"
            "如果你想继续，我可以再帮你只看这些候选里更稳的、录取率更高的，或者直接看看是否值得纳入当前方案。"
        )
    except Exception:
        logger.exception("query_volunteer_plan failed: session_id=%s", session_id)
        _append_query_observability(
            ctx,
            session_id=session_id,
            requested_scope=requested_scope,
            resolved_scope=normalized_scope,
            has_structured_filters=has_structured_filters,
            filter_keys=_filter_keys(structured_filters),
            timings=timings,
            total_duration_ms=int((time.perf_counter() - tool_started_at) * 1000),
            status="error",
        )
        return "查询当前方案时发生错误，请稍后重试。"
