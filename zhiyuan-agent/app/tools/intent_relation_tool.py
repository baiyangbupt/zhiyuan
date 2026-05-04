"""Shared relation-analysis helpers for explore / intent flows."""

from __future__ import annotations

import logging
from typing import Any

from app.domain.career_slots import (
    CAREER_FURTHER_STUDY,
    CAREER_LABEL_MAP,
    CAREER_STABLE_EMPLOYMENT,
    CAREER_SYSTEM_PUBLIC_SERVICE,
    to_career_labels,
)
from app.util.internal_client import get_planning_state

logger = logging.getLogger(__name__)

ANALYSIS_STAGE_INTEREST = "interest"
INTENT_MODE_CONSTRAINT = "constraint"


def _contains_any_text(value: str | None, keywords: list[str]) -> bool:
    if not value:
        return False
    return any(keyword and keyword in str(value) for keyword in keywords)


def _contains_any_in_list(values: list[str] | None, keywords: list[str]) -> bool:
    if not values:
        return False
    return any(_contains_any_text(value, keywords) for value in values)


_SEARCH_TEXT_KEYS = {
    "provinceName",
    "province_name",
    "cityName",
    "city_name",
    "schoolName",
    "school_name",
    "schoolCategory",
    "school_category",
    "schoolNature",
    "school_nature",
    "schoolLevel",
    "school_level",
    "majorName",
    "major_name",
    "majorItemName",
    "major_item_name",
    "majorCategory",
    "major_category",
    "majorCategoryName",
    "major_category_name",
    "majorDiscipline",
    "major_discipline",
    "subCategoryName",
    "sub_category_name",
    "categoryName",
    "category_name",
    "name",
}

_SEARCH_LIST_KEYS = {
    "schoolRankTags",
    "schoolBasicTags",
    "schoolPopupTags",
    "majorRankTags",
    "majorPlanTags",
    "rankTagList",
    "basicTagList",
    "popTagList",
    "planTagList",
}

_NESTED_MAJOR_KEYS = {
    "majors",
    "majorItems",
    "major_items",
    "majorList",
    "major_list",
    "majorItemList",
    "major_item_list",
}

_SCHOOL_NAME_KEYS = ("schoolName", "school_name", "collegeName", "college_name")
_PROVINCE_NAME_KEYS = ("provinceName", "province_name")
_TIER_KEYS = ("tier", "level")
_MAJOR_NAME_KEYS = ("majorName", "major_name", "majorItemName", "major_item_name")
_TIER_ORDER = {"冲": 0, "sprint": 0, "稳": 1, "safe": 1, "保": 2, "protect": 2}


def _append_text(values: list[str], value: Any) -> None:
    if value is None:
        return
    if isinstance(value, str):
        if value:
            values.append(value)
        return
    if isinstance(value, (int, float)):
        values.append(str(value))
        return
    if isinstance(value, list):
        for item in value:
            _append_text(values, item)


def _iter_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_dicts(child)


def _collect_item_search_texts(item: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for current in _iter_dicts(item):
        for key, value in current.items():
            if key in _SEARCH_TEXT_KEYS or key in _SEARCH_LIST_KEYS:
                _append_text(texts, value)
    return texts


def _normalize_text_list(values: Any) -> list[str]:
    if not values:
        return []
    if isinstance(values, str):
        text = values.strip()
        return [text] if text else []
    if isinstance(values, list):
        result: list[str] = []
        for value in values:
            text = str(value or "").strip()
            if text and text not in result:
                result.append(text)
        return result
    text = str(values).strip()
    return [text] if text else []


def _field_value(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = item.get(key)
        if value:
            return str(value)
    return ""


def _major_name_from_item(item: dict[str, Any], *, allow_generic_name: bool = False) -> str:
    keys = _MAJOR_NAME_KEYS + (("name",) if allow_generic_name else ())
    return _field_value(item, keys)


def _iter_major_values(item: dict[str, Any]):
    seen: set[int] = set()

    def _yield(value: Any):
        if isinstance(value, dict):
            identity = id(value)
            if identity in seen:
                return
            seen.add(identity)
            yield value
        elif isinstance(value, str):
            yield value
        elif isinstance(value, list):
            for child in value:
                yield from _yield(child)

    if _major_name_from_item(item):
        yield item
    for current in _iter_dicts(item):
        for key in _NESTED_MAJOR_KEYS:
            if key in current:
                yield from _yield(current.get(key))


def _matched_major_names(item: dict[str, Any], values: list[str] | None) -> list[str]:
    if not values:
        return []
    matches: list[str] = []
    seen: set[str] = set()
    for major_value in _iter_major_values(item):
        if isinstance(major_value, str):
            searchable = [major_value]
            major_name = major_value
        elif isinstance(major_value, dict):
            searchable = _collect_item_search_texts(major_value)
            major_name = _major_name_from_item(major_value, allow_generic_name=True)
        else:
            continue
        if not any(target in text for target in values for text in searchable):
            continue
        display_name = major_name or next((text for text in searchable if any(target in text for target in values)), "")
        if display_name and display_name not in seen:
            matches.append(display_name)
            seen.add(display_name)
    return matches


def _first_major_name(item: dict[str, Any]) -> str:
    top_level = _major_name_from_item(item)
    if top_level:
        return top_level
    for major_value in _iter_major_values(item):
        if isinstance(major_value, str) and major_value:
            return major_value
        if isinstance(major_value, dict):
            major_name = _major_name_from_item(major_value, allow_generic_name=True)
            if major_name:
                return major_name
    return ""


def _extract_display_preferences(planning_state: dict[str, Any] | None) -> dict[str, list[str]]:
    explicit = ((planning_state or {}).get("profileState") or {}).get("explicitProfile") or {}
    return {
        "positiveMajors": _normalize_text_list(explicit.get("positiveMajors")),
        "negativeMajors": _normalize_text_list(explicit.get("negativeMajors")),
        "positiveSchools": _normalize_text_list(explicit.get("positiveSchools")),
        "negativeSchools": _normalize_text_list(explicit.get("negativeSchools")),
        "positiveRegions": _normalize_text_list(explicit.get("positiveRegions")),
        "negativeRegions": _normalize_text_list(explicit.get("negativeRegions")),
    }


def _match_preference_index(texts: list[str], preferences: list[str]) -> int | None:
    if not texts or not preferences:
        return None
    for index, preference in enumerate(preferences):
        if preference and any(preference in text for text in texts):
            return index
    return None


def _relation_example_sort_key(
    item: dict[str, Any],
    display_preferences: dict[str, list[str]],
    *,
    positive: bool,
    original_index: int,
) -> tuple[Any, ...]:
    school_name = _field_value(item, _SCHOOL_NAME_KEYS)
    province_name = _field_value(item, _PROVINCE_NAME_KEYS)
    city_name = _field_value(item, ("cityName", "city_name"))
    search_texts = _collect_item_search_texts(item)
    school_preferences = display_preferences["positiveSchools"] if positive else display_preferences["negativeSchools"]
    region_preferences = display_preferences["positiveRegions"] if positive else display_preferences["negativeRegions"]
    major_preferences = display_preferences["positiveMajors"] if positive else display_preferences["negativeMajors"]
    school_index = _match_preference_index([school_name], school_preferences)
    region_index = _match_preference_index([province_name, city_name], region_preferences)
    major_index = _match_preference_index(search_texts, major_preferences)
    tier_value = _field_value(item, _TIER_KEYS)
    tier_order = _TIER_ORDER.get(tier_value, 9)
    preferred_rank = 0 if item.get("preferred") is True else 1
    try:
        final_score = float(item.get("finalScore") or 0)
    except (TypeError, ValueError):
        final_score = 0.0
    return (
        0 if school_index is not None else 1,
        school_index if school_index is not None else 999,
        0 if region_index is not None else 1,
        region_index if region_index is not None else 999,
        0 if major_index is not None else 1,
        major_index if major_index is not None else 999,
        preferred_rank,
        tier_order,
        -final_score,
        original_index,
    )


def _sort_relation_examples(
    items: list[dict[str, Any]],
    display_preferences: dict[str, list[str]],
    *,
    positive: bool,
) -> list[dict[str, Any]]:
    if not items:
        return []
    indexed_items = list(enumerate(items))
    indexed_items.sort(
        key=lambda pair: _relation_example_sort_key(
            pair[1],
            display_preferences,
            positive=positive,
            original_index=pair[0],
        )
    )
    return [item for _, item in indexed_items]


def _is_public_service_aligned_item(item: dict[str, Any]) -> bool:
    if not item:
        return False
    school_tags = item.get("schoolRankTags") or []
    school_basic_tags = item.get("schoolBasicTags") or []
    school_popup_tags = item.get("schoolPopupTags") or []
    major_rank_tags = item.get("majorRankTags") or []
    major_plan_tags = item.get("majorPlanTags") or []

    if _contains_any_text(item.get("schoolCategory"), ["师范", "政法", "财经", "农林", "医药"]):
        return True
    if _contains_any_text(item.get("majorName"), ["法学", "汉语言", "中国语言", "思想政治", "教育", "师范", "行政管理", "公共管理", "政治学", "马克思"]):
        return True
    if _contains_any_text(item.get("majorCategory"), ["法学", "汉语言", "中国语言", "思想政治", "教育", "师范", "行政管理", "公共管理", "政治学", "马克思"]):
        return True
    if _contains_any_text(item.get("majorDiscipline"), ["法学", "汉语言", "中国语言", "思想政治", "教育", "师范", "行政管理", "公共管理", "政治学", "马克思"]):
        return True
    if _contains_any_in_list(school_tags + school_basic_tags + school_popup_tags, ["师范", "政法", "财经", "农林", "医药", "部委院校", "公安", "警校"]):
        return True
    if _contains_any_in_list(major_rank_tags + major_plan_tags, ["法学", "汉语言", "中国语言", "思想政治", "教育", "师范", "行政管理", "公共管理", "政治学", "马克思"]):
        return True
    if _contains_any_in_list(
        _collect_item_search_texts(item),
        ["法学", "汉语言", "中国语言", "思想政治", "教育", "师范", "行政管理", "公共管理", "政治学", "马克思"],
    ):
        return True
    return False


def _item_matches_career_intents(
    item: dict[str, Any],
    career_intents: dict | None,
) -> tuple[bool, bool]:
    if not career_intents:
        return False, False
    positive = career_intents.get("positive") or []
    negative = career_intents.get("negative") or []
    aligned = _is_public_service_aligned_item(item)
    return bool(positive and aligned), bool(negative and aligned)


def _item_matches_any_intent(item: dict[str, Any], values: list[str], *, negative: bool = False) -> bool:
    if not values:
        return False
    normalized_haystacks = _collect_item_search_texts(item)
    for target in values:
        if any(target in candidate_text for candidate_text in normalized_haystacks):
            return True
    return False


def _format_candidate_brief(item: dict[str, Any], intent_values: list[str] | None = None) -> str:
    school_name = _field_value(item, _SCHOOL_NAME_KEYS) or "未知院校"
    matched_major_names = _matched_major_names(item, intent_values)
    major_name = "、".join(matched_major_names[:2]) or _first_major_name(item) or "未知专业"
    tier = _field_value(item, _TIER_KEYS) or "未知"
    province_name = _field_value(item, _PROVINCE_NAME_KEYS)
    return f"{school_name}-{major_name}（{tier}{f'/{province_name}' if province_name else ''}）"


def _collect_intent_labels(
    major_intents: dict | None,
    school_intents: dict | None,
    city_intents: dict | None,
    career_intents: dict | None = None,
) -> dict[str, list[str]]:
    labels: dict[str, list[str]] = {"positive": [], "negative": []}

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
        _extend(city_intents.get("negative_province"), negative=True)
        _extend(city_intents.get("negative_city"), negative=True)
    if career_intents:
        _extend(to_career_labels(career_intents.get("positive")))
        _extend(to_career_labels(career_intents.get("negative")), negative=True)

    return labels


def build_plan_relation_analysis(
    intent_mode: str,
    analysis_stage: str = "confirmed",
    career_intents: dict | None = None,
) -> dict[str, Any]:
    fit_points: list[str] = []
    conflict_points: list[str] = []
    opportunity_points: list[str] = []
    next_action_hints: list[str] = []

    if intent_mode == INTENT_MODE_CONSTRAINT:
        fit_points.append("我先帮你看看，这个要求和你现在的方案是否有冲突，以及还有没有合适的可选机会。")
    else:
        fit_points.append("我先帮你看看，现在这份方案里有没有贴近这个方向的内容，以及还有哪些值得继续关注的机会。")

    if career_intents:
        positive = to_career_labels(career_intents.get("positive"))
        negative = to_career_labels(career_intents.get("negative"))
        if positive:
            fit_points.insert(0, f"你刚提到更看重 {'、'.join(positive)}，后面我会按这个方向帮你一起看方案。")
        if negative:
            conflict_points.insert(0, f"你刚提到不考虑 {'、'.join(negative)}，后面我会尽量避开这类方向来帮你看。")
        if positive or negative:
            opportunity_points.insert(0, "这类想法不会立刻改动候选结果，但会影响我后面怎么帮你分析和给建议。")
    else:
        opportunity_points.append("我也会顺手看看，方案外还有没有更贴近这个方向的机会。")

    if analysis_stage == ANALYSIS_STAGE_INTEREST:
        if intent_mode == INTENT_MODE_CONSTRAINT:
            next_action_hints.append("如果你确定这是硬要求，我可以继续帮你找出方案里还需要避开的地方。")
            next_action_hints.append("你也可以先去工作台候选区看看，按这个要求筛完之后还剩哪些机会。")
        else:
            next_action_hints.append("如果你愿意把它当成偏好，我可以继续帮你看现在的方案哪里比较贴近、哪里还能补强。")
            next_action_hints.append("如果你现在只是先了解，也可以继续问我这个方向适不适合你。")
    else:
        if intent_mode == INTENT_MODE_CONSTRAINT:
            next_action_hints.append("下一步更适合先看看方案里还有没有不符合这条要求的地方，再决定怎么调。")
        else:
            next_action_hints.append("下一步更适合继续看看这份方案和你的想法有多匹配，或者直接让我给你调整建议。")

    return {
        "stage": analysis_stage,
        "summaryTitle": "先帮你看一眼" if analysis_stage == ANALYSIS_STAGE_INTEREST else "结合当前方案给你的提醒",
        "currentPlanFit": fit_points,
        "currentPlanConflict": conflict_points,
        "candidateOpportunity": opportunity_points,
        "nextActionHints": next_action_hints,
    }


async def enrich_plan_relation_analysis_from_state(
    session_id: str,
    base_analysis: dict[str, Any],
    *,
    intent_mode: str,
    major_intents: dict | None,
    school_intents: dict | None,
    city_intents: dict | None,
    career_intents: dict | None = None,
) -> dict[str, Any]:
    try:
        planning_state_resp = await get_planning_state(session_id)
        if not isinstance(planning_state_resp, dict):
            return base_analysis
        planning_state = (planning_state_resp or {}).get("data") or {}
        if not isinstance(planning_state, dict):
            return base_analysis
        ordered_items = ((planning_state.get("orderedPlanState") or {}).get("items")) or []
        candidate_items = ((planning_state.get("candidatePoolState") or {}).get("items")) or []
        display_preferences = _extract_display_preferences(planning_state)
        candidate_by_id = {item.get("volunteerId"): item for item in candidate_items if item.get("volunteerId")}
        intent_labels = _collect_intent_labels(major_intents, school_intents, city_intents, career_intents)

        fit_items: list[dict[str, Any]] = []
        conflict_items: list[dict[str, Any]] = []
        ordered_volunteer_ids = {item.get("volunteerId") for item in ordered_items if item.get("volunteerId")}

        for ordered_item in ordered_items:
            match_item = candidate_by_id.get(ordered_item.get("volunteerId")) or ordered_item
            positive_match = _item_matches_any_intent(match_item, intent_labels["positive"])
            career_positive_match, career_negative_match = _item_matches_career_intents(match_item, career_intents)
            if positive_match or career_positive_match:
                fit_items.append(match_item)
            negative_match = _item_matches_any_intent(match_item, intent_labels["negative"], negative=True)
            if negative_match or career_negative_match:
                conflict_items.append(match_item)

        if fit_items:
            fit_examples = [
                _format_candidate_brief(item, intent_labels["positive"] if _item_matches_any_intent(item, intent_labels["positive"]) else None)
                for item in _sort_relation_examples(fit_items, display_preferences, positive=True)
            ]
            base_analysis["currentPlanFit"].insert(0, f"现在这份方案里，比较贴近你这个想法的有：{'、'.join(fit_examples[:5])}")
        if conflict_items:
            conflict_examples = [
                _format_candidate_brief(item, intent_labels["negative"] if _item_matches_any_intent(item, intent_labels["negative"], negative=True) else None)
                for item in _sort_relation_examples(conflict_items, display_preferences, positive=False)
            ]
            if intent_mode == INTENT_MODE_CONSTRAINT:
                base_analysis["currentPlanConflict"].insert(0, f"现在这份方案里，还需要你特别留意的有：{'、'.join(conflict_examples[:5])}")
            else:
                base_analysis["currentPlanConflict"].insert(0, f"现在这份方案里，和你这个想法不太一致的有：{'、'.join(conflict_examples[:5])}")

        opportunity_items = []
        for item in candidate_items:
            volunteer_id = item.get("volunteerId")
            if not volunteer_id or volunteer_id in ordered_volunteer_ids:
                continue
            positive_match = _item_matches_any_intent(item, intent_labels["positive"])
            career_positive_match, _ = _item_matches_career_intents(item, career_intents)
            if positive_match or career_positive_match:
                opportunity_items.append(item)
        if opportunity_items:
            sorted_opportunities = _sort_relation_examples(opportunity_items, display_preferences, positive=True)
            base_analysis["candidateOpportunity"].insert(0, f"候选里还有一些可以顺手看看、但暂时没放进方案的机会：{'、'.join(_format_candidate_brief(item, intent_labels['positive']) for item in sorted_opportunities[:3])}")
            base_analysis["candidateOpportunity"].append(f"和这个方向比较相关、但还没放进方案里的机会，大约还有 {len(opportunity_items)} 个。")
        elif candidate_items:
            base_analysis["candidateOpportunity"].append("候选里暂时没看到特别明显更合适的补位机会，可以先围绕现在这份方案继续看。")
    except Exception:
        logger.warning("Enrich plan relation analysis from planning state failed: session_id=%s", session_id, exc_info=True)
    return base_analysis


def build_impact_preview_from_analysis(analysis: dict[str, Any]) -> str:
    lines: list[str] = [f"**{analysis.get('summaryTitle', '结合当前方案给你的提醒')}**"]
    analysis_stage = analysis.get("stage")

    if analysis_stage == ANALYSIS_STAGE_INTEREST:
        section_map = (
            ("currentPlanFit", "初步判断"),
            ("currentPlanConflict", "需要补充留意"),
            ("candidateOpportunity", "可以继续展开看的方向"),
            ("nextActionHints", "如果继续了解"),
        )
    else:
        section_map = (
            ("currentPlanFit", "现在比较贴近的部分"),
            ("currentPlanConflict", "现在需要留意的部分"),
            ("candidateOpportunity", "还可以再看看的机会"),
            ("nextActionHints", "下一步建议"),
        )
    for key, title in section_map:
        items = analysis.get(key) or []
        if not items:
            continue
        lines.append(f"\n**{title}**")
        for item in items:
            lines.append(f"- {item}")
    return "\n".join(lines)
