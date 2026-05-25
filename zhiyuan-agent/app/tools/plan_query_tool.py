"""Plan query tool.

查询语义拆分：
- 默认先查当前方案（ordered plan，空时退到 draft）
- 用户明确表达“还有什么可选 / 候选里 / 还能报”时，主查候选机会
- 若默认方案查询未命中，再补查候选机会，并明确区分“当前方案”与“候选机会”
"""

from __future__ import annotations

import logging
import re
from typing import Any, Literal

from pydantic_ai import RunContext

from app.agent.context import RequestContext
from app.util.code_enrichment import (
    _normalize_city_names_async,
    _normalize_province_names_async,
    _normalize_school_names_async,
    _normalize_school_tags_async,
    resolve_major_names_async,
)
from app.util.internal_client import (
    get_planning_state,
    get_planning_draft,
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
    stripped_group = re.sub(r"\d{2,3}专业组.*$", "", raw).strip()
    if stripped_group and stripped_group not in variants:
        variants.append(stripped_group)
    stripped_paren = re.sub(r"[（(].*?[)）]", "", stripped_group or raw).strip()
    if stripped_paren and stripped_paren not in variants:
        variants.append(stripped_paren)
    return variants


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

    combined_texts = [
        f"{school_name}-{major_name}"
        for school_name in school_variants
        if school_name and major_name
    ]
    return any(compact_keyword in _compact_text(text) for text in combined_texts)


def _matches_any_query_keyword(item: dict[str, Any], keywords: list[str]) -> bool:
    return any(_matches_query(item, keyword) for keyword in keywords if keyword)


def _has_structured_filters(filters: dict[str, list[str]]) -> bool:
    return any(filters.get(key) for key in (
        "tiers",
        "province_names",
        "city_names",
        "school_keywords",
        "major_keywords",
        "school_tags",
        "major_tags",
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
    filters: dict[str, list[str]],
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


def _describe_structured_filters(filters: dict[str, list[str]], fallback_query: str) -> str:
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
    ratio = _format_ratio(item.get("admissionRatio"))
    return f"{school_name}-{major_name}（{tier}，录取率{ratio}）"


def _extract_plan_items(response: dict[str, Any]) -> list[dict[str, Any]]:
    return (response.get("data") or {}).get("items") or []


async def _normalize_major_keywords_async(major_keywords: list[str], batch: str) -> list[str]:
    values = _normalize_text_list(major_keywords)
    if not values:
        return []
    normalized: list[str] = []
    for name in values:
        level2_values = await resolve_major_names_async([name], "level2", batch)
        level3_values = await resolve_major_names_async([name], "level3", batch)
        level2_name = level2_values[0] if level2_values else name
        level3_name = level3_values[0] if level3_values else name
        if "类" in name:
            resolved = level2_name if level2_name != name else level3_name
        else:
            resolved = level3_name if level3_name != name else level2_name
        resolved = resolved or name
        if resolved not in normalized:
            normalized.append(resolved)
    return normalized


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
) -> dict[str, list[str]]:
    return {
        "tiers": _normalize_text_list(tiers),
        "province_names": await _normalize_province_names_async(province_names),
        "city_names": await _normalize_city_names_async(city_names),
        "school_keywords": await _normalize_school_names_async(school_keywords),
        "major_keywords": await _normalize_major_keywords_async(major_keywords, batch),
        "school_tags": await _normalize_school_tags_async(school_tags),
        "major_tags": await _normalize_major_keywords_async(major_tags, batch),
    }


def _format_plan_result(title: str, items: list[dict[str, Any]], display_keyword: str, query_keywords: list[str]) -> str:
    if not items:
        return f"{title}里还没有可查询的志愿。"
    if display_keyword:
        matched = [item for item in items if _matches_any_query_keyword(item, query_keywords)]
        if matched:
            examples = matched[:5]
            snippets = "；".join(_build_plan_item_snippet(item) for item in examples)
            return (
                f"{title}里共命中了 {len(matched)} 条和“{display_keyword}”相关的志愿。"
                f"下面仅展示前 {len(examples)} 条示例：{snippets}\n"
                "下一步如果要处理这些志愿，可以告诉我保留哪几个、移动到哪里，或只看更稳/录取率更高的。"
            )
        return f"{title}里暂时没有命中“{display_keyword}”的志愿。"
    snippets = "；".join(_build_plan_item_snippet(item) for item in items[:5])
    return f"{title}前几项是：{snippets}\n如果要继续调整，可以告诉我按录取率、院校层次排序，或移动/删除具体志愿。"


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
        return f"候选里暂时没有筛到和“{keyword}”相关的机会。"
    examples = items[:5]
    snippets = "；".join(_build_candidate_item_snippet(item) for item in examples)
    return (
        f"候选里共命中了 {total} 条和“{keyword}”相关的机会。"
        f"下面仅展示前 {len(examples)} 条示例：{snippets}\n"
        "下一步可以继续缩小条件，比如只看更稳、录取率更高，或判断是否值得加入当前方案。"
    )


async def _load_current_plan(session_id: str) -> tuple[str, list[dict[str, Any]]]:
    ordered_result = await get_planning_ordered_plan(session_id)
    ordered_items = _extract_plan_items(ordered_result)
    if ordered_result.get("code") == 0 and ordered_items:
        return "当前排序方案", ordered_items

    draft_result = await get_planning_draft(session_id)
    draft_items = _extract_plan_items(draft_result)
    if draft_result.get("code") == 0 and draft_items:
        return "当前已加入方案", draft_items

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
    if matched:
        examples = matched[:5]
        snippets = "；".join(_build_plan_item_snippet(item) for item in examples)
        return (
            f"{title}里共命中了 {len(matched)} 条符合“{description}”的志愿。"
            f"下面仅展示前 {len(examples)} 条示例：{snippets}\n"
            "下一步如果要处理这些志愿，可以告诉我保留哪几个、移动到哪里，或只看更稳/录取率更高的。"
        )
    return f"{title}里暂时没有命中符合“{description}”的志愿。"


def _format_structured_candidate_result(response: dict[str, Any], description: str) -> str:
    data = response.get("data") or {}
    items = data.get("items") or []
    total = data.get("total") or 0
    if not items:
        return f"候选里暂时没有筛到符合“{description}”的机会。"
    examples = items[:5]
    snippets = "；".join(_build_candidate_item_snippet(item) for item in examples)
    return (
        f"候选里共命中了 {total} 条符合“{description}”的机会。"
        f"下面仅展示前 {len(examples)} 条示例：{snippets}\n"
        "下一步可以继续缩小条件，比如只看更稳、录取率更高，或判断是否值得加入当前方案。"
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
    match_mode: PlanQueryMatchMode = _MATCH_MODE_AND,
) -> str:
    """围绕当前方案与候选机会进行局部命中查询。

    只适合回答“当前方案里有没有某学校/专业/地域”“候选里还有没有某方向机会”。
    不适合回答“还差几个怎么补、补几个更稳的、怎么补满、加入方案”这类会改变方案或规划补齐动作的问题；
    这类问题应走 Plan 主链路规划 preview_compensation/add_units，并在用户确认后执行。
    也不适合在移动/删除前作为“定位 ID”的前置步骤；`move_unit/remove_units/add_units`
    的 `volunteer_ids` 可以直接填写用户原始学校+专业引用，执行层会解析真实 ID 并处理歧义。

    当 `scope=auto` 时，兼容旧行为，仍会根据 query 做启发式判断。
    更推荐由模型显式传入：
    - `plan`
    - `candidate`
    - `plan_then_candidate`
    - 以及结构化 filters，如 `province_names / school_keywords / major_keywords / school_tags / major_tags`
    """
    session_id = ctx.deps.sessionid
    batch = getattr(ctx.deps, "batch", None) or "01"
    logger.info("query_volunteer_plan called: session_id=%s, query=%s, scope=%s", session_id, query, scope)

    if _looks_like_plan_action_query(query):
        return "这是补齐或调整当前方案的动作诉求，不是局部查询；应先走方案动作预览，用户确认后再执行。"

    structured_filters = await _normalize_local_query_filters_async(
        batch=batch,
        tiers=tiers,
        province_names=province_names,
        city_names=city_names,
        school_keywords=school_keywords,
        major_keywords=major_keywords,
        school_tags=school_tags,
        major_tags=major_tags,
    )
    has_structured_filters = _has_structured_filters(structured_filters)
    filter_description = _describe_structured_filters(structured_filters, (query or "").strip())
    normalized_match_mode = _normalize_match_mode(match_mode)

    query_keywords = _build_query_keywords(query)
    display_keyword = query_keywords[0] if query_keywords else ((query or "").strip())
    lookup_keyword = query_keywords[-1] if query_keywords else display_keyword
    normalized_scope = _normalize_scope(scope)
    if normalized_scope == _AUTO_SCOPE:
        normalized_scope = _resolve_query_scope(query)

    try:
        if has_structured_filters:
            if normalized_scope == _CANDIDATE_SCOPE:
                candidate_result = await _query_candidate_opportunities_with_filters(session_id, structured_filters)
                if candidate_result.get("code") != 0:
                    return "查询候选机会失败，请稍后重试。"
                return _format_structured_candidate_result(candidate_result, filter_description)

            plan_title, plan_items = await _load_current_plan(session_id)
            plan_items = await _enrich_plan_items_with_candidate_metadata(session_id, plan_items)
            plan_text = _format_structured_plan_result(
                plan_title,
                plan_items,
                filter_description,
                structured_filters,
                match_mode=normalized_match_mode,
            )
            if normalized_scope == _PLAN_SCOPE:
                return plan_text

            matched_plan_items = [
                item
                for item in plan_items
                if _matches_structured_filters(item, structured_filters, match_mode=normalized_match_mode)
            ]
            if matched_plan_items:
                return plan_text

            candidate_result = await _query_candidate_opportunities_with_filters(session_id, structured_filters)
            if candidate_result.get("code") != 0:
                return plan_text
            candidate_text = _format_structured_candidate_result(candidate_result, filter_description)
            return (
                f"{plan_text}\n"
                f"{candidate_text}\n"
                "如果你想继续，我可以再基于这组条件帮你只看更稳的、录取率更高的，或者继续判断是否值得纳入当前方案。"
            )

        if normalized_scope == _CANDIDATE_SCOPE:
            candidate_result = await _query_candidate_opportunities(session_id, query, lookup_keyword)
            if candidate_result.get("code") != 0:
                return "查询候选机会失败，请稍后重试。"
            return _format_candidate_result(candidate_result, display_keyword)

        plan_title, plan_items = await _load_current_plan(session_id)
        plan_text = _format_plan_result(plan_title, plan_items, display_keyword, query_keywords)

        if normalized_scope == _PLAN_SCOPE:
            return plan_text

        matched_plan_items = [item for item in plan_items if _matches_any_query_keyword(item, query_keywords)]
        if matched_plan_items:
            return plan_text

        candidate_result = await _query_candidate_opportunities(session_id, query, lookup_keyword)
        if candidate_result.get("code") != 0:
            return plan_text
        candidate_text = _format_candidate_result(candidate_result, display_keyword)
        return (
            f"{plan_text}\n"
            f"{candidate_text}\n"
            "如果你想继续，我可以再帮你只看这些候选里更稳的、录取率更高的，或者直接看看是否值得纳入当前方案。"
        )
    except Exception:
        logger.exception("query_volunteer_plan failed: session_id=%s", session_id)
        return "查询当前方案时发生错误，请稍后重试。"
