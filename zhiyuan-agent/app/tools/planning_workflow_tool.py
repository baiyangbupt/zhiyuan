"""Planning workflow tools.

按需读取 backend 的 planning review / compensation 结果，避免将完整状态长期注入主 prompt。
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic_ai import RunContext

from app.agent.context import PlanningSummary, RequestContext
from app.domain.career_slots import CAREER_LABEL_MAP
from app.tools.explore_direction_tool import _item_matches_direction_slot
from app.util.internal_client import (
    analyze_planning_plan_adjustment as _analyze_planning_plan_adjustment_request,
    apply_planning_compensation as _apply_planning_compensation_request,
    ban_planning_draft_items as _ban_planning_draft_items_request,
    generate_planning_candidate_pool as _generate_planning_candidate_pool_request,
    generate_planning_initial_plan as _generate_planning_initial_plan_request,
    generate_planning_ordered_plan as _generate_planning_ordered_plan_request,
    query_planning_candidate_pool as _query_planning_candidate_pool_request,
    get_planning_state as _get_planning_state_request,
    get_user_profile as _get_user_profile_request,
    get_planning_draft as _get_planning_draft_request,
    get_planning_ordered_plan as _get_planning_ordered_plan_request,
    lock_planning_draft_items as _lock_planning_draft_items_request,
    move_planning_ordered_item as _move_planning_ordered_item_request,
    pin_planning_ordered_item as _pin_planning_ordered_item_request,
    preview_planning_compensation as _preview_planning_compensation_request,
    remove_planning_draft_items as _remove_planning_draft_items_request,
    run_planning_review as _run_planning_review_request,
    select_planning_draft_items as _select_planning_draft_items_request,
    unpin_planning_ordered_item as _unpin_planning_ordered_item_request,
)

logger = logging.getLogger(__name__)
_DEFAULT_TENANT_ID = 1
_CAREER_LABEL_TO_SLOT = {label: slot for slot, label in CAREER_LABEL_MAP.items()}
_MAJOR_MATCH_FIELDS = {"majorName", "majorCategory", "majorDiscipline"}


def _collect_non_passed_summaries(checks: list[dict[str, Any]], limit: int = 3) -> list[str]:
    summaries: list[str] = []
    for check in checks:
        if check.get("passed") is True:
            continue
        summary = check.get("summary")
        if summary:
            summaries.append(summary)
        if len(summaries) >= limit:
            break
    return summaries


def _collect_action_summaries(actions: list[dict[str, Any]], limit: int = 3) -> list[str]:
    summaries: list[str] = []
    for action in actions[:limit]:
        summary = action.get("summary")
        if summary:
            summaries.append(summary)
    return summaries


def _sum_volunteer_ids(actions: list[dict[str, Any]]) -> int:
    total = 0
    for action in actions:
        total += len(action.get("volunteerIds") or [])
    return total


def _sum_compensation_fill_count(actions: list[dict[str, Any]]) -> int:
    total = 0
    for action in actions:
        unit_ids = action.get("unitIds") or []
        if unit_ids:
            total += len(unit_ids)
            continue
        total += len(action.get("volunteerIds") or [])
    return total


def _format_tier_counts(tier_counts: dict[str, Any]) -> str:
    sprint = tier_counts.get("冲")
    if sprint is None:
        sprint = tier_counts.get("sprint") or 0
    safe = tier_counts.get("稳")
    if safe is None:
        safe = tier_counts.get("safe") or 0
    protect = tier_counts.get("保")
    if protect is None:
        protect = tier_counts.get("protect") or 0
    return f"冲{sprint} / 稳{safe} / 保{protect}"


def _format_total_with_target(current: int, target: int) -> str:
    if target and target > 0:
        return f"{current}/{target}"
    return str(current)


def _build_count_gap_hint(current: int, target: int, unit_label: str = "志愿") -> str | None:
    if target and target > 0 and current < target:
        return f"当前{unit_label}数量不足，还差 {target - current} 个。"
    return None


def _format_ratio(value: Any) -> str | None:
    if value is None:
        return None
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        return None
    if ratio.is_integer():
        return f"{int(ratio)}%"
    return f"{ratio:.1f}%"


def _item_admission_ratio(item: dict[str, Any]) -> Any:
    return (
        item.get("admissionRatio")
        if item.get("admissionRatio") is not None
        else item.get("enrollRatio")
    )


def _format_plan_items(items: list[dict[str, Any]], include_position: bool = False, limit: int = 5) -> str | None:
    snippets: list[str] = []
    for item in items[:limit]:
        school_name = item.get("schoolName") or "未知院校"
        major_name = item.get("majorName") or _first_major_name(item) or "未知专业"
        tier = item.get("tier") or "unknown"
        suffix_parts = [f"{school_name}-{major_name}", f"({tier})"]
        ratio_text = _format_ratio(_item_admission_ratio(item))
        if ratio_text:
            suffix_parts.append(f"录取率{ratio_text}")
        if include_position and item.get("position") is not None:
            suffix_parts.append(f"@{item.get('position')}")
        if item.get("pinned") is True:
            suffix_parts.append("[固定]")
        if item.get("locked") is True:
            suffix_parts.append("[锁定]")
        snippets.append("".join(suffix_parts))
    if not snippets:
        return None
    return "；".join(snippets)


def _format_candidate_items(items: list[dict[str, Any]], limit: int = 5) -> str | None:
    snippets: list[str] = []
    for item in items[:limit]:
        school_name = item.get("schoolName") or "未知院校"
        major_name = item.get("majorName") or _first_major_name(item) or "未知专业"
        tier = item.get("tier") or "unknown"
        volunteer_id = item.get("volunteerId") or "unknown"
        score = item.get("finalScore")
        province_name = item.get("provinceName") or ""
        tail = f" 分值{score}" if score is not None else ""
        snippets.append(f"{school_name}-{major_name}({tier}/{province_name}) id={volunteer_id}{tail}")
    if not snippets:
        return None
    return "；".join(snippets)


def _volunteer_item_id(item: dict[str, Any]) -> str:
    return str(
        item.get("volunteerId")
        or item.get("id")
        or item.get("planSchoolDataId")
        or ""
    ).strip()


def _relation_plan_unit_id(item: dict[str, Any]) -> str:
    volunteer_id = str(item.get("volunteerId") or "").strip()
    if volunteer_id:
        separator = volunteer_id.find("_")
        if separator > 0:
            return volunteer_id[:separator]
        return volunteer_id

    return str(
        item.get("unitId")
        or item.get("planSchoolDataId")
        or item.get("schoolName")
        or ""
    ).strip()


def _format_plan_item_names(items: list[dict[str, Any]], limit: int = 5) -> str | None:
    snippets: list[str] = []
    for item in items[:limit]:
        school_name = item.get("schoolName") or "未知院校"
        major_name = item.get("majorName") or _first_major_name(item) or "未知专业"
        tier = item.get("tier") or "unknown"
        ratio_text = _format_ratio(_item_admission_ratio(item))
        ratio_suffix = f"，录取率{ratio_text}" if ratio_text else ""
        snippets.append(f"{school_name}-{major_name}（{tier}{ratio_suffix}）")
    if not snippets:
        return None
    suffix = f"等{len(items)}个" if len(items) > limit else ""
    return "；".join(snippets) + suffix


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


def _normalize_major_match_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return re.split(r"[（(]", text, maxsplit=1)[0].strip()


@lru_cache(maxsize=1)
def _load_major_taxonomy_descendants() -> tuple[dict[str, frozenset[str]], dict[str, frozenset[str]]]:
    data_dir = Path(__file__).resolve().parents[2] / "data" / "option"
    category_to_majors: dict[str, set[str]] = {}
    discipline_to_terms: dict[str, set[str]] = {}

    for filename in ("major_bachelor.json", "major_associate.json"):
        path = data_dir / filename
        if not path.exists():
            continue
        try:
            with path.open(encoding="utf-8") as fh:
                payload = json.load(fh)
        except Exception:
            logger.warning("failed to load major taxonomy file: %s", path, exc_info=True)
            continue

        for discipline in payload.get("data") or []:
            discipline_name = str(discipline.get("label") or "").strip()
            if not discipline_name:
                continue
            discipline_terms = discipline_to_terms.setdefault(discipline_name, set())
            for category in discipline.get("children") or []:
                category_name = str(category.get("label") or "").strip()
                if not category_name:
                    continue
                discipline_terms.add(category_name)
                category_terms = category_to_majors.setdefault(category_name, set())
                for major in category.get("children") or []:
                    major_name = _normalize_major_match_text(major.get("label"))
                    if not major_name:
                        continue
                    category_terms.add(major_name)
                    discipline_terms.add(major_name)

    return (
        {key: frozenset(values) for key, values in category_to_majors.items()},
        {key: frozenset(values) for key, values in discipline_to_terms.items()},
    )


def _prefer_specific_legacy_major_values(intent_payload: Any) -> list[str]:
    payload = intent_payload or {}
    if not isinstance(payload, dict):
        return []
    for key in ("level3", "level2", "level1"):
        values = _normalize_text_list(payload.get(key))
        if values:
            return values
    return []


def merge_planning_state_with_user_profile(
    planning_state: dict[str, Any] | None,
    user_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    if not planning_state:
        return {}
    if not user_profile:
        return planning_state

    merged = copy.deepcopy(planning_state)
    profile_state = merged.setdefault("profileState", {})
    explicit = profile_state.setdefault("explicitProfile", {})

    major_intent = user_profile.get("major_intent")
    if major_intent is not None:
        explicit["positiveMajors"] = _prefer_specific_legacy_major_values(major_intent)

    negative_major_intent = user_profile.get("negative_major_intent")
    if negative_major_intent is not None:
        explicit["negativeMajors"] = _prefer_specific_legacy_major_values(negative_major_intent)

    college_info = user_profile.get("college_info")
    if college_info is not None:
        explicit["positiveSchools"] = _normalize_text_list((college_info or {}).get("values"))

    negative_college_info = user_profile.get("negative_college_info")
    if negative_college_info is not None:
        explicit["negativeSchools"] = _normalize_text_list((negative_college_info or {}).get("values"))

    city_info = user_profile.get("city_info")
    if city_info is not None:
        explicit["positiveRegions"] = _normalize_text_list((city_info or {}).get("province"))

    negative_city_info = user_profile.get("negative_city_info")
    if negative_city_info is not None:
        explicit["negativeRegions"] = _normalize_text_list((negative_city_info or {}).get("province"))

    strength_subject_info = user_profile.get("strength_subject_info")
    if strength_subject_info is not None:
        explicit["strengthSubjects"] = _normalize_text_list((strength_subject_info or {}).get("values"))

    return merged


async def _get_planning_state_with_latest_profile(session_id: str) -> dict[str, Any]:
    state_result, profile_result = await asyncio.gather(
        _get_planning_state_request(session_id),
        _get_user_profile_request(session_id),
        return_exceptions=True,
    )

    planning_state: dict[str, Any] = {}
    if not isinstance(state_result, Exception) and state_result.get("code") == 0:
        planning_state = state_result.get("data") or {}
    elif isinstance(state_result, Exception):
        logger.warning(
            "get_planning_state_with_latest_profile planning_state fetch failed: session_id=%s",
            session_id,
            exc_info=state_result,
        )

    user_profile: dict[str, Any] | None = None
    if not isinstance(profile_result, Exception) and profile_result.get("code") == 0:
        user_profile = profile_result.get("data", {}).get("userprofile") or {}
    elif isinstance(profile_result, Exception):
        logger.warning(
            "get_planning_state_with_latest_profile user_profile fetch failed: session_id=%s",
            session_id,
            exc_info=profile_result,
        )

    return merge_planning_state_with_user_profile(planning_state, user_profile)


def _extract_plan_intent_state(planning_state: dict[str, Any] | None) -> dict[str, list[str]]:
    profile_state = (planning_state or {}).get("profileState") or {}
    explicit = profile_state.get("explicitProfile") or {}
    latent = profile_state.get("latentProfile") or {}
    future_development = (latent.get("futureDevelopment") or {}).get("careerTypes") or []
    return {
        "positiveMajors": _normalize_text_list(explicit.get("positiveMajors")),
        "negativeMajors": _normalize_text_list(explicit.get("negativeMajors")),
        "positiveSchools": _normalize_text_list(explicit.get("positiveSchools")),
        "negativeSchools": _normalize_text_list(explicit.get("negativeSchools")),
        "positiveRegions": _normalize_text_list(explicit.get("positiveRegions")),
        "negativeRegions": _normalize_text_list(explicit.get("negativeRegions")),
        "careerTypes": _normalize_text_list(future_development),
    }


def _normalize_career_labels(values: list[str]) -> list[str]:
    labels: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        label = CAREER_LABEL_MAP.get(text, text)
        if label not in labels:
            labels.append(label)
    return labels


_ITEM_TEXT_KEYS = {
    "schoolName",
    "school_name",
    "collegeName",
    "college_name",
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
    "provinceName",
    "province_name",
    "cityName",
    "city_name",
    "areaName",
    "area_name",
    "schoolCategory",
    "school_category",
    "name",
}

_ITEM_LIST_KEYS = {
    "schoolTags",
    "majorTags",
    "reasonCodes",
    "schoolRankTags",
    "schoolBasicTags",
    "majorRankTags",
    "majorPlanTags",
    "rankTagList",
    "basicTagList",
    "planTagList",
}

_FIELD_ALIASES = {
    "majorName": ("majorName", "major_name", "majorItemName", "major_item_name", "name"),
    "majorCategory": ("majorCategory", "major_category", "majorCategoryName", "major_category_name", "subCategoryName", "sub_category_name"),
    "majorDiscipline": ("majorDiscipline", "major_discipline", "categoryName", "category_name"),
    "schoolName": ("schoolName", "school_name", "collegeName", "college_name"),
    "provinceName": ("provinceName", "province_name"),
    "cityName": ("cityName", "city_name"),
    "areaName": ("areaName", "area_name"),
}


def _append_item_text(values: list[str], value: Any) -> None:
    if value is None:
        return
    if isinstance(value, str):
        text = value.strip()
        if text:
            values.append(text)
        return
    if isinstance(value, (int, float)):
        values.append(str(value))
        return
    if isinstance(value, list):
        for item in value:
            _append_item_text(values, item)


def _iter_item_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_item_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_item_dicts(child)


def _collect_item_texts(item: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for current in _iter_item_dicts(item):
        for key, value in current.items():
            if key in _ITEM_TEXT_KEYS or key in _ITEM_LIST_KEYS:
                _append_item_text(texts, value)
    return texts


def _collect_field_texts(item: dict[str, Any], fields: tuple[str, ...]) -> list[str]:
    keys: set[str] = set()
    for field in fields:
        keys.update(_FIELD_ALIASES.get(field, (field,)))
    values: list[str] = []
    for current in _iter_item_dicts(item):
        for key in keys:
            if key in current:
                _append_item_text(values, current.get(key))
    return values


def _first_item_value(item: dict[str, Any], keys: tuple[str, ...], *, recursive: bool = False) -> str:
    dicts = _iter_item_dicts(item) if recursive else (item,)
    for current in dicts:
        for key in keys:
            value = current.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _first_major_name(item: dict[str, Any]) -> str:
    return _first_item_value(
        item,
        ("majorName", "major_name", "majorItemName", "major_item_name", "name"),
        recursive=True,
    )


def _item_texts(item: dict[str, Any]) -> list[str]:
    return _collect_item_texts(item)


def _item_matches_major_taxonomy_keyword(item: dict[str, Any], keyword: str) -> bool:
    major_name = _normalize_major_match_text(_first_major_name(item))
    if not major_name:
        return False
    category_to_majors, discipline_to_terms = _load_major_taxonomy_descendants()
    return (
        major_name in category_to_majors.get(keyword, ())
        or major_name in discipline_to_terms.get(keyword, ())
    )


def _item_matches_keyword(item: dict[str, Any], keywords: list[str], *, fields: tuple[str, ...] | None = None) -> list[str]:
    matched: list[str] = []
    values: list[str] = []
    major_match_allowed = bool(fields and any(field in _MAJOR_MATCH_FIELDS for field in fields))
    if fields:
        values = _collect_field_texts(item, fields)
    else:
        values = _item_texts(item)
    for keyword in keywords:
        text = str(keyword or "").strip()
        if not text:
            continue
        if any(text in value for value in values) and text not in matched:
            matched.append(text)
            continue
        if major_match_allowed and _item_matches_major_taxonomy_keyword(item, text) and text not in matched:
            matched.append(text)
    return matched


def _item_matches_career_labels(item: dict[str, Any], labels: list[str]) -> list[str]:
    matched: list[str] = []
    for label in _normalize_career_labels(labels):
        slot = _CAREER_LABEL_TO_SLOT.get(label)
        if slot and _item_matches_direction_slot(item, slot):
            matched.append(label)
    return matched


def _format_plan_item_brief(item: dict[str, Any], include_position: bool = False) -> str:
    school_name = item.get("schoolName") or "未知院校"
    major_name = item.get("majorName") or _first_major_name(item) or "未知专业"
    tier = item.get("tier") or "unknown"
    parts = [f"{school_name}-{major_name}", f"({tier})"]
    ratio_text = _format_ratio(_item_admission_ratio(item))
    if ratio_text:
        parts.append(f"录取率{ratio_text}")
    if include_position and item.get("position") is not None:
        parts.append(f"@{item.get('position')}")
    return "".join(parts)


def _ratio_values(items: list[dict[str, Any]]) -> list[float]:
    values: list[float] = []
    for item in items:
        ratio = _item_admission_ratio(item)
        if ratio is None:
            continue
        try:
            values.append(float(ratio))
        except (TypeError, ValueError):
            continue
    return values


def _format_tier_ratio_distribution(items: list[dict[str, Any]], tier: str) -> str | None:
    tier_items = [item for item in items if item.get("tier") == tier]
    values = _ratio_values(tier_items)
    if not values:
        return None
    below_45 = sum(1 for value in values if value < 45)
    return f"{tier}档录取率范围 {_format_ratio(min(values))}-{_format_ratio(max(values))}，45%以下 {below_45}/{len(values)}个"


def _review_failed_summaries(review_checks: list[dict[str, Any]]) -> list[str]:
    return [
        str(check.get("summary") or "").strip()
        for check in review_checks
        if isinstance(check, dict) and check.get("passed") is False and str(check.get("summary") or "").strip()
    ]


def _has_probability_gradient_warning(failed_checks: list[str]) -> bool:
    return any(("录取概率" in text or "梯度" in text or "倒挂" in text) for text in failed_checks)


def _build_plan_intent_relation_facts(
    planning_state: dict[str, Any] | None,
    plan_items: list[dict[str, Any]] | None,
    *,
    plan_summary: dict[str, Any] | None = None,
    include_position: bool = False,
) -> dict[str, Any]:
    lines = _build_plan_intent_relation_lines(
        planning_state,
        plan_items,
        plan_summary=plan_summary,
        include_position=include_position,
    )
    return {
        "lines": lines,
        "summary": lines[0].removeprefix("- ").strip() if lines else "",
        "coverage": lines[1].removeprefix("- ").strip() if len(lines) > 1 else "",
        "aligned_examples": lines[2].removeprefix("- ").strip() if len(lines) > 2 else "",
        "conflict_examples": lines[3].removeprefix("- ").strip() if len(lines) > 3 else "",
    }


def _pick_relation_plan_items(
    planning_state: dict[str, Any] | None,
    *,
    ordered_state: dict[str, Any] | None = None,
    draft_state: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if ordered_state and ordered_state.get("items"):
        return list(ordered_state.get("items") or [])
    if draft_state and draft_state.get("items"):
        return list(draft_state.get("items") or [])
    return list(
        ((planning_state or {}).get("orderedPlanState") or {}).get("items")
        or (((planning_state or {}).get("draftPlanState") or {}).get("items") or [])
    )


def _pick_relation_plan_summary(
    planning_state: dict[str, Any] | None,
    *,
    ordered_state: dict[str, Any] | None = None,
    draft_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if ordered_state and ordered_state.get("summary"):
        return ordered_state.get("summary") or {}
    if draft_state and draft_state.get("summary"):
        return draft_state.get("summary") or {}
    ordered_summary = ((planning_state or {}).get("orderedPlanState") or {}).get("summary") or {}
    if ordered_summary:
        return ordered_summary
    return (((planning_state or {}).get("draftPlanState") or {}).get("summary") or {})


def _collect_issue_hit_plan_examples(
    checks: list[dict[str, Any]],
    plan_items: list[dict[str, Any]] | None,
    *,
    limit_checks: int = 3,
    per_check: int = 2,
) -> list[dict[str, Any]]:
    item_by_id = {
        str(item.get("volunteerId") or "").strip(): item
        for item in (plan_items or [])
        if str(item.get("volunteerId") or "").strip()
    }
    examples: list[dict[str, Any]] = []
    for check in checks:
        if check.get("passed") is True:
            continue
        summary = str(check.get("summary") or "").strip()
        affected_ids = [
            str(volunteer_id or "").strip()
            for volunteer_id in (check.get("affectedVolunteerIds") or [])
            if str(volunteer_id or "").strip()
        ]
        if not summary or not affected_ids:
            continue
        affected_items: list[str] = []
        seen_ids: set[str] = set()
        for volunteer_id in affected_ids:
            if volunteer_id in seen_ids:
                continue
            item = item_by_id.get(volunteer_id)
            if not item:
                continue
            seen_ids.add(volunteer_id)
            affected_items.append(_format_plan_item_brief(item, include_position=True))
            if len(affected_items) >= per_check:
                break
        if not affected_items:
            continue
        examples.append(
            {
                "code": str(check.get("code") or "").strip(),
                "summary": summary,
                "affected_count": len({volunteer_id for volunteer_id in affected_ids}),
                "items": affected_items,
            }
        )
        if len(examples) >= limit_checks:
            break
    return examples


def _build_review_result_facts(
    review_state: dict[str, Any],
    planning_state: dict[str, Any] | None = None,
    *,
    ordered_state: dict[str, Any] | None = None,
    draft_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary = review_state.get("summary") or {}
    checks = review_state.get("checks") or []
    compensation_preview = review_state.get("compensationPreview") or {}
    preview_actions = compensation_preview.get("actions") or []
    plan_items = _pick_relation_plan_items(
        planning_state,
        ordered_state=ordered_state,
        draft_state=draft_state,
    )
    plan_summary = _pick_relation_plan_summary(
        planning_state,
        ordered_state=ordered_state,
        draft_state=draft_state,
    )
    return {
        "risk_count": int(summary.get("riskCount") or 0),
        "warn_count": int(summary.get("warnCount") or 0),
        "passed_count": int(summary.get("passedCount") or 0),
        "main_problems": _collect_non_passed_summaries(checks),
        "issue_hit_plan_examples": _collect_issue_hit_plan_examples(checks, plan_items),
        "compensation_action_count": len(preview_actions),
        "compensation_summaries": _collect_action_summaries(preview_actions),
        "intent_relation": _build_plan_intent_relation_facts(
            planning_state,
            plan_items,
            plan_summary=plan_summary,
            include_position=True,
        ),
    }


def _build_compensation_preview_facts(preview: dict[str, Any]) -> dict[str, Any]:
    actions = preview.get("actions") or []
    return {
        "action_count": len(actions),
        "action_summaries": _collect_action_summaries(actions),
        "estimated_fill_count": _sum_compensation_fill_count(actions),
        "estimated_volunteer_count": _sum_volunteer_ids(actions),
    }


def _is_plan_adjustment_suggestion_actionable(suggestion: dict[str, Any] | None, suggestion_type: str) -> bool:
    data = suggestion or {}
    normalized_type = str(suggestion_type or "").strip()
    if normalized_type == "add":
        return bool(data.get("candidateVolunteerIds") or data.get("candidateUnitIds"))
    if normalized_type == "reorder":
        return bool(data.get("orderedVolunteerIds") or data.get("orderedUnitIds"))
    if normalized_type == "replace":
        return bool(
            data.get("replacementPairs")
            or (data.get("removeVolunteerIds") and data.get("candidateVolunteerIds"))
            or (data.get("removeUnitIds") and data.get("candidateUnitIds"))
        )
    if normalized_type == "remove":
        return bool(data.get("removeVolunteerIds") or data.get("removeUnitIds"))
    return False


def _build_plan_adjustment_facts(
    adjustment_state: dict[str, Any],
    planning_state: dict[str, Any] | None = None,
    *,
    ordered_state: dict[str, Any] | None = None,
    draft_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    analysis = adjustment_state.get("analysis") or {}
    suggestions = adjustment_state.get("suggestions") or {}
    rules = analysis.get("rules") or []
    hit_rules = [rule for rule in rules if rule.get("hit") is True]
    add_suggestions = suggestions.get("addSuggestions") or []
    reorder_suggestions = suggestions.get("reorderSuggestions") or []
    replace_suggestions = suggestions.get("replaceSuggestions") or []
    remove_suggestions = suggestions.get("removeSuggestions") or []
    actionable_counts = {
        "add": sum(1 for item in add_suggestions if _is_plan_adjustment_suggestion_actionable(item, "add")),
        "reorder": sum(1 for item in reorder_suggestions if _is_plan_adjustment_suggestion_actionable(item, "reorder")),
        "replace": sum(1 for item in replace_suggestions if _is_plan_adjustment_suggestion_actionable(item, "replace")),
        "remove": sum(1 for item in remove_suggestions if _is_plan_adjustment_suggestion_actionable(item, "remove")),
    }
    plan_items = _pick_relation_plan_items(
        planning_state,
        ordered_state=ordered_state,
        draft_state=draft_state,
    )
    plan_summary = _pick_relation_plan_summary(
        planning_state,
        ordered_state=ordered_state,
        draft_state=draft_state,
    )
    review_checks = (((planning_state or {}).get("reviewState") or {}).get("checks") or [])
    return {
        "summary_text": analysis.get("summaryText") or "",
        "hit_rules": [
            {
                "summary": rule.get("summary") or rule.get("ruleCode") or "结构问题",
                "suggestion_types": rule.get("suggestionTypes") or [],
            }
            for rule in hit_rules[:5]
        ],
        "suggestion_counts": {
            "add": len(add_suggestions),
            "reorder": len(reorder_suggestions),
            "replace": len(replace_suggestions),
            "remove": len(remove_suggestions),
        },
        "actionable_suggestion_counts": actionable_counts,
        "has_actionable_suggestions": any(actionable_counts.values()),
        "example_suggestions": [
            {
                "title": suggestion.get("title") or "调整建议",
                "description": suggestion.get("description") or "",
            }
            for suggestion in (add_suggestions + reorder_suggestions + replace_suggestions + remove_suggestions)[:5]
        ],
        "review_issue_hit_plan_examples": _collect_issue_hit_plan_examples(review_checks, plan_items),
        "intent_relation": _build_plan_intent_relation_facts(
            planning_state,
            plan_items,
            plan_summary=plan_summary,
            include_position=True,
        ),
    }


def _build_plan_status_overview_facts(
    planning_state: dict[str, Any],
    ordered_state: dict[str, Any] | None = None,
    draft_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary = PlanningSummary.from_backend_state(planning_state)
    if summary is None:
        return {}

    active_plan_state = ordered_state or draft_state or {}
    active_summary = active_plan_state.get("summary") or {}
    active_items = active_plan_state.get("items") or []
    tier_counts = active_summary.get("unitTierCounts") or active_summary.get("tierCounts") or {}
    current_total = summary.ordered_total if summary.ordered_total > 0 else summary.draft_total
    target_total = summary.ordered_target_total if summary.ordered_total > 0 else summary.draft_target_total
    return {
        "phase": summary.phase,
        "has_ordered_plan": bool(summary.ordered_total > 0),
        "ordered_total": summary.ordered_total,
        "ordered_target_total": summary.ordered_target_total,
        "draft_total": summary.draft_total,
        "draft_target_total": summary.draft_target_total,
        "current_total": current_total,
        "target_total": target_total,
        "count_gap_hint": _build_count_gap_hint(current_total, target_total),
        "tier_counts": tier_counts,
        "gradient_ok": bool(active_summary.get("gradientOk")) if ordered_state else None,
        "safety_ok": bool(active_summary.get("safetyOk")) if ordered_state else None,
        "risk_count": summary.review_risk_count,
        "warn_count": summary.review_warn_count,
        "main_reminders": summary.risk_summaries,
        "top_items": [
            _format_plan_item_brief(item, include_position=bool(ordered_state))
            for item in active_items[:5]
        ],
        "pending_action_count": summary.pending_action_count,
        "pending_action_summaries": summary.pending_action_summaries,
        "intent_relation": _build_plan_intent_relation_facts(
            planning_state,
            active_items,
            plan_summary=active_summary,
            include_position=bool(ordered_state),
        ),
    }


async def _load_visible_plan_states(
    session_id: str,
    planning_state: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    summary = PlanningSummary.from_backend_state(planning_state or {})
    if summary is None:
        return None, None

    ordered_state: dict[str, Any] | None = None
    draft_state: dict[str, Any] | None = None
    if summary.ordered_total > 0:
        ordered_result = await _get_planning_ordered_plan_request(session_id)
        if ordered_result.get("code") == 0:
            ordered_state = ordered_result.get("data") or {}
    elif summary.draft_total > 0:
        draft_result = await _get_planning_draft_request(session_id)
        if draft_result.get("code") == 0:
            draft_state = draft_result.get("data") or {}
    return ordered_state, draft_state


def _build_plan_intent_relation_lines(
    planning_state: dict[str, Any] | None,
    plan_items: list[dict[str, Any]] | None,
    *,
    plan_summary: dict[str, Any] | None = None,
    include_position: bool = False,
) -> list[str]:
    intent_state = _extract_plan_intent_state(planning_state)
    positive_majors = intent_state["positiveMajors"]
    negative_majors = intent_state["negativeMajors"]
    positive_schools = intent_state["positiveSchools"]
    negative_schools = intent_state["negativeSchools"]
    positive_regions = intent_state["positiveRegions"]
    negative_regions = intent_state["negativeRegions"]
    career_types = _normalize_career_labels(intent_state["careerTypes"])

    summary_parts: list[str] = []
    if positive_majors:
        summary_parts.append(f"偏好专业={','.join(positive_majors[:3])}")
    if negative_majors:
        summary_parts.append(f"排除专业={','.join(negative_majors[:3])}")
    if positive_schools:
        summary_parts.append(f"偏好院校={','.join(positive_schools[:3])}")
    if negative_schools:
        summary_parts.append(f"排除院校={','.join(negative_schools[:3])}")
    if positive_regions:
        summary_parts.append(f"偏好地域={','.join(positive_regions[:3])}")
    if negative_regions:
        summary_parts.append(f"排除地域={','.join(negative_regions[:3])}")
    if career_types:
        summary_parts.append(f"发展方向={','.join(career_types[:2])}")

    if not summary_parts:
        return []

    lines = [f"- 当前偏好/要求：{'；'.join(summary_parts)}"]
    items = plan_items or []
    if not items:
        lines.append("- 承接情况：当前还没有可分析的方案条目。")
        return lines

    aligned_examples: list[str] = []
    conflict_examples: list[str] = []
    aligned_count = 0
    conflict_count = 0
    aggregate_by_unit = False
    if plan_summary:
        unit_total = int(plan_summary.get("unitTotal") or 0)
        total = int(plan_summary.get("total") or 0)
        aggregate_by_unit = (0 < unit_total < len(items)) or (0 < total < len(items))
    aligned_units: set[str] = set()
    conflict_units: set[str] = set()
    aligned_example_units: set[str] = set()
    conflict_example_units: set[str] = set()
    for index, item in enumerate(items):
        positive_reasons: list[str] = []
        negative_reasons: list[str] = []
        unit_id = _relation_plan_unit_id(item) or f"row:{index}"

        matched_positive_major = _item_matches_keyword(item, positive_majors, fields=("majorName", "majorCategory", "majorDiscipline"))
        matched_negative_major = _item_matches_keyword(item, negative_majors, fields=("majorName", "majorCategory", "majorDiscipline"))
        matched_positive_school = _item_matches_keyword(item, positive_schools, fields=("schoolName",))
        matched_negative_school = _item_matches_keyword(item, negative_schools, fields=("schoolName",))
        matched_positive_region = _item_matches_keyword(item, positive_regions, fields=("provinceName", "cityName", "areaName"))
        matched_negative_region = _item_matches_keyword(item, negative_regions, fields=("provinceName", "cityName", "areaName"))
        matched_career = _item_matches_career_labels(item, career_types)

        if matched_positive_major:
            positive_reasons.append(f"匹配偏好专业:{'、'.join(matched_positive_major[:2])}")
        if matched_positive_school:
            positive_reasons.append(f"匹配偏好院校:{'、'.join(matched_positive_school[:2])}")
        if matched_positive_region:
            positive_reasons.append(f"匹配偏好地域:{'、'.join(matched_positive_region[:2])}")
        if matched_career:
            positive_reasons.append(f"匹配发展方向:{'、'.join(matched_career[:2])}")

        if matched_negative_major:
            negative_reasons.append(f"命中排除专业:{'、'.join(matched_negative_major[:2])}")
        if matched_negative_school:
            negative_reasons.append(f"命中排除院校:{'、'.join(matched_negative_school[:2])}")
        if matched_negative_region:
            negative_reasons.append(f"命中排除地域:{'、'.join(matched_negative_region[:2])}")

        if positive_reasons:
            if not aggregate_by_unit or unit_id not in aligned_units:
                aligned_count += 1
                if aggregate_by_unit:
                    aligned_units.add(unit_id)
            if len(aligned_examples) < 2 and (not aggregate_by_unit or unit_id not in aligned_example_units):
                aligned_examples.append(f"{_format_plan_item_brief(item, include_position=include_position)}（{'；'.join(positive_reasons)}）")
                if aggregate_by_unit:
                    aligned_example_units.add(unit_id)
        if negative_reasons:
            if not aggregate_by_unit or unit_id not in conflict_units:
                conflict_count += 1
                if aggregate_by_unit:
                    conflict_units.add(unit_id)
            if len(conflict_examples) < 2 and (not aggregate_by_unit or unit_id not in conflict_example_units):
                conflict_examples.append(f"{_format_plan_item_brief(item, include_position=include_position)}（{'；'.join(negative_reasons)}）")
                if aggregate_by_unit:
                    conflict_example_units.add(unit_id)

    lines.append(f"- 承接情况：当前方案里较贴近的有{aligned_count}个，明显冲突的有{conflict_count}个。")
    if aligned_examples:
        lines.append(f"- 贴近偏好：{'；'.join(aligned_examples)}")
    if conflict_examples:
        lines.append(f"- 需关注冲突：{'；'.join(conflict_examples)}")
    return lines


def _format_review_result(
    review_state: dict[str, Any],
    planning_state: dict[str, Any] | None = None,
    *,
    ordered_state: dict[str, Any] | None = None,
    draft_state: dict[str, Any] | None = None,
) -> str:
    summary = review_state.get("summary") or {}
    checks = review_state.get("checks") or []
    compensation_preview = review_state.get("compensationPreview") or {}

    lines = ["已完成当前方案审查。"]
    lines.append(
        f"- 审查结果：风险{summary.get('riskCount') or 0}项，提醒{summary.get('warnCount') or 0}项，通过{summary.get('passedCount') or 0}项"
    )

    risk_summaries = _collect_non_passed_summaries(checks)
    if risk_summaries:
        lines.append(f"- 主要问题：{'；'.join(risk_summaries)}")

    relation_lines = _build_plan_intent_relation_lines(
        planning_state,
        _pick_relation_plan_items(
            planning_state,
            ordered_state=ordered_state,
            draft_state=draft_state,
        ),
        plan_summary=_pick_relation_plan_summary(
            planning_state,
            ordered_state=ordered_state,
            draft_state=draft_state,
        ),
        include_position=True,
    )
    lines.extend(relation_lines)

    preview_actions = compensation_preview.get("actions") or []
    if preview_actions:
        lines.append(
            f"- 可用补偿：{len(preview_actions)}项，主要为{'；'.join(_collect_action_summaries(preview_actions))}"
        )

    lines.append("如果你想继续处理，我可以先预览补偿建议，再确认是否应用。")
    return "\n".join(lines)


def _format_compensation_preview(preview: dict[str, Any]) -> str:
    actions = preview.get("actions") or []
    if not actions:
        return "已预览补偿建议。当前没有可安全自动补偿的候选，建议先检查现有排序或手动补充志愿。"

    lines = ["已生成补偿预览。"]
    lines.append(f"- 待执行动作：{len(actions)}项")
    lines.append(f"- 主要补偿：{'；'.join(_collect_action_summaries(actions))}")
    lines.append(f"- 预计补入候选：{_sum_compensation_fill_count(actions)}个")
    lines.append("如果你明确确认执行，我可以继续应用这些补偿，并在执行后重新审查。")
    return "\n".join(lines)


def _format_plan_adjustment_result(
    adjustment_state: dict[str, Any],
    planning_state: dict[str, Any] | None = None,
    *,
    ordered_state: dict[str, Any] | None = None,
    draft_state: dict[str, Any] | None = None,
) -> str:
    analysis = adjustment_state.get("analysis") or {}
    suggestions = adjustment_state.get("suggestions") or {}
    rules = analysis.get("rules") or []
    hit_rules = [rule for rule in rules if rule.get("hit") is True]

    add_suggestions = suggestions.get("addSuggestions") or []
    reorder_suggestions = suggestions.get("reorderSuggestions") or []
    replace_suggestions = suggestions.get("replaceSuggestions") or []
    remove_suggestions = suggestions.get("removeSuggestions") or []

    lines = ["我先从当前方案里帮你看了一遍可优化的地方。"]
    summary_text = analysis.get("summaryText")
    if summary_text:
        lines.append(f"- 总体判断：{summary_text}")

    if hit_rules:
        rule_snippets: list[str] = []
        for rule in hit_rules[:3]:
            summary = rule.get("summary") or rule.get("ruleCode") or "结构问题"
            suggestion_types = rule.get("suggestionTypes") or []
            if suggestion_types:
                summary = f"{summary}（建议：{' / '.join(suggestion_types)}）"
            rule_snippets.append(summary)
        lines.append(f"- 主要问题：{'；'.join(rule_snippets)}")
    else:
        lines.append("- 主要问题：当前没发现需要立刻处理的结构性问题。")

    suggestion_parts: list[str] = []
    if add_suggestions:
        suggestion_parts.append(f"补充建议 {len(add_suggestions)} 条")
    if reorder_suggestions:
        suggestion_parts.append(f"顺序调整 {len(reorder_suggestions)} 条")
    if replace_suggestions:
        suggestion_parts.append(f"替换建议 {len(replace_suggestions)} 条")
    if remove_suggestions:
        suggestion_parts.append(f"移除建议 {len(remove_suggestions)} 条")
    if suggestion_parts:
        lines.append(f"- 建议概览：{'，'.join(suggestion_parts)}")

    example_suggestions: list[str] = []
    for suggestion in (add_suggestions + reorder_suggestions + replace_suggestions + remove_suggestions)[:3]:
        title = suggestion.get("title") or "调整建议"
        description = suggestion.get("description") or ""
        example_suggestions.append(f"{title}：{description}" if description else title)
    if example_suggestions:
        lines.append(f"- 具体建议：{'；'.join(example_suggestions)}")

    relation_lines = _build_plan_intent_relation_lines(
        planning_state,
        _pick_relation_plan_items(
            planning_state,
            ordered_state=ordered_state,
            draft_state=draft_state,
        ),
        plan_summary=_pick_relation_plan_summary(
            planning_state,
            ordered_state=ordered_state,
            draft_state=draft_state,
        ),
        include_position=True,
    )
    lines.extend(relation_lines)

    if suggestion_parts:
        lines.append("如果你想继续，我可以按某一类建议继续细化，例如只看补哪些更稳、哪些需要调顺序，或者先挑一条建议展开。")
    else:
        lines.append("如果你担心某一块，比如保底、梯度或者顺序，我也可以只针对那一部分继续细看。")
    return "\n".join(lines)


def _format_apply_result(
    planning_state: dict[str, Any],
    *,
    ordered_state: dict[str, Any] | None = None,
    draft_state: dict[str, Any] | None = None,
) -> str:
    summary = PlanningSummary.from_backend_state(planning_state)
    if summary is None:
        return "已应用补偿，但未拿到最新规划摘要，建议立即再执行一次审查确认结果。"

    lines = ["已应用补偿并刷新当前方案。"]
    lines.append(f"- 当前阶段：{summary.phase}")
    lines.append(f"- 已加入方案数：{_format_total_with_target(summary.draft_total, summary.draft_target_total)}")
    lines.append(f"- 当前方案数：{_format_total_with_target(summary.ordered_total, summary.ordered_target_total)}")
    count_gap_hint = _build_count_gap_hint(summary.ordered_total, summary.ordered_target_total)
    if count_gap_hint:
        lines.append(f"- 数量检查：{count_gap_hint}")
    lines.append(f"- 当前风险：{summary.review_risk_count}项，提醒{summary.review_warn_count}项")
    if summary.pending_action_count > 0:
        lines.append(
            f"- 剩余待处理建议：{summary.pending_action_count}项，主要为{'；'.join(summary.pending_action_summaries)}"
        )
    else:
        lines.append("- 当前待处理建议：0项")
    lines.extend(
        _build_plan_intent_relation_lines(
            planning_state,
            _pick_relation_plan_items(
                planning_state,
                ordered_state=ordered_state,
                draft_state=draft_state,
            ),
            plan_summary=_pick_relation_plan_summary(
                planning_state,
                ordered_state=ordered_state,
                draft_state=draft_state,
            ),
            include_position=True,
        )
    )
    return "\n".join(lines)


def _format_state_result(
    planning_state: dict[str, Any],
    *,
    ordered_state: dict[str, Any] | None = None,
    draft_state: dict[str, Any] | None = None,
) -> str:
    summary = PlanningSummary.from_backend_state(planning_state)
    if summary is None:
        return "当前未获取到规划状态，可能还没有初始化方案。"

    stale_flags = planning_state.get("staleFlags") or {}
    stale_parts: list[str] = []
    if stale_flags.get("candidatePool"):
        stale_parts.append("候选池待刷新")
    if stale_flags.get("orderedPlan"):
        stale_parts.append("排序待刷新")
    if stale_flags.get("review"):
        stale_parts.append("审查结果待刷新")

    lines = ["当前规划状态概览："]
    lines.append(f"- 当前阶段：{summary.phase}")
    lines.append(f"- 状态版本：{summary.version}")
    lines.append(f"- 已加入方案数：{_format_total_with_target(summary.draft_total, summary.draft_target_total)}")
    lines.append(f"- 当前方案数：{_format_total_with_target(summary.ordered_total, summary.ordered_target_total)}")
    count_gap_hint = _build_count_gap_hint(summary.ordered_total, summary.ordered_target_total)
    if count_gap_hint:
        lines.append(f"- 数量检查：{count_gap_hint}")
    lines.append(f"- 风险与提醒：风险{summary.review_risk_count}项，提醒{summary.review_warn_count}项")
    if summary.risk_summaries:
        lines.append(f"- 当前主要风险：{'；'.join(summary.risk_summaries)}")
    if summary.pending_action_count > 0:
        lines.append(
            f"- 当前待处理建议：{summary.pending_action_count}项，主要为{'；'.join(summary.pending_action_summaries)}"
        )
    lines.extend(
        _build_plan_intent_relation_lines(
            planning_state,
            _pick_relation_plan_items(
                planning_state,
                ordered_state=ordered_state,
                draft_state=draft_state,
            ),
            plan_summary=_pick_relation_plan_summary(
                planning_state,
                ordered_state=ordered_state,
                draft_state=draft_state,
            ),
            include_position=True,
        )
    )
    if stale_parts:
        lines.append(f"- 待刷新状态：{'；'.join(stale_parts)}")
    return "\n".join(lines)


def _format_draft_result(draft_state: dict[str, Any]) -> str:
    summary = draft_state.get("summary") or {}
    items = draft_state.get("items") or []
    unit_total = summary.get("unitTotal") or summary.get("total") or 0
    target_total = summary.get("targetUnitCount") or summary.get("targetCount") or 0
    tier_counts = summary.get("unitTierCounts") or summary.get("tierCounts") or {}
    lines = ["已加入方案概况："]
    lines.append(f"- 已加入方案数：{_format_total_with_target(unit_total, target_total)}")
    lines.append(f"- 区间分布：{_format_tier_counts(tier_counts)}")
    count_gap_hint = _build_count_gap_hint(unit_total, target_total)
    if count_gap_hint:
        lines.append(f"- 数量检查：{count_gap_hint}")
    lines.append(f"- 已禁用志愿数：{len(draft_state.get('bannedVolunteerIds') or [])}")
    item_text = _format_plan_items(items, include_position=False)
    if item_text:
        lines.append(f"- 方案示例：{item_text}")
    return "\n".join(lines)


def _format_draft_state_with_prefix(prefix: str, planning_state: dict[str, Any]) -> str:
    draft_state = (planning_state.get("draftPlanState") or {}) if planning_state else {}
    if not draft_state:
        return prefix
    return prefix + "\n" + _format_draft_result(draft_state)


def _format_ordered_result(ordered_state: dict[str, Any], planning_state: dict[str, Any] | None = None) -> str:
    summary = ordered_state.get("summary") or {}
    items = ordered_state.get("items") or []
    review_state = ((planning_state or {}).get("reviewState") or {}) if planning_state else {}
    review_summary = review_state.get("summary") or {}
    review_checks = review_state.get("checks") or []
    unit_total = summary.get("unitTotal") or summary.get("total") or 0
    target_total = summary.get("targetUnitCount") or summary.get("targetCount") or 0
    tier_counts = summary.get("unitTierCounts") or summary.get("tierCounts") or {}
    failed_checks = _review_failed_summaries(review_checks)
    gradient_ok = bool(summary.get("gradientOk")) and not _has_probability_gradient_warning(failed_checks)
    lines = ["方案志愿概况："]
    lines.append(f"- 排序总数：{_format_total_with_target(unit_total, target_total)}")
    lines.append(f"- 区间分布：{_format_tier_counts(tier_counts)}")
    lines.append(f"- 录取率梯度是否达标：{'是' if gradient_ok else '否'}")
    lines.append(f"- 保底是否达标：{'是' if summary.get('safetyOk') else '否'}")
    for tier in ("冲", "稳", "保"):
        distribution = _format_tier_ratio_distribution(items, tier)
        if distribution:
            lines.append(f"- {distribution}")
    if review_summary:
        lines.append(
            f"- 复审结果：风险{review_summary.get('riskCount') or 0}项，提醒{review_summary.get('warnCount') or 0}项"
        )
        if failed_checks:
            lines.append(f"- 主要提醒：{'；'.join(failed_checks[:3])}")
    count_gap_hint = _build_count_gap_hint(unit_total, target_total)
    if count_gap_hint:
        lines.append(f"- 数量检查：{count_gap_hint}")
    item_text = _format_plan_items(items, include_position=True)
    if item_text:
        lines.append(f"- 排序前列：{item_text}")
    return "\n".join(lines)


def _format_plan_status_overview(
    planning_state: dict[str, Any],
    ordered_state: dict[str, Any] | None = None,
    draft_state: dict[str, Any] | None = None,
) -> str:
    summary = PlanningSummary.from_backend_state(planning_state)
    if summary is None:
        return "当前还没有读取到明确的方案状态。"

    lines = ["方案完整状态："]
    lines.append(f"- 当前阶段：{summary.phase}")

    if summary.ordered_total > 0:
        lines.append(
            f"- 当前已有排序方案：{_format_total_with_target(summary.ordered_total, summary.ordered_target_total)}个志愿"
        )
    elif summary.draft_total > 0:
        lines.append(
            f"- 当前已有草稿方案：{_format_total_with_target(summary.draft_total, summary.draft_target_total)}个志愿，尚未形成最终排序"
        )
    else:
        lines.append("- 当前还没有形成方案")

    active_current_total = summary.ordered_total if summary.ordered_total > 0 else summary.draft_total
    active_target_total = summary.ordered_target_total if summary.ordered_total > 0 else summary.draft_target_total
    count_gap_hint = _build_count_gap_hint(active_current_total, active_target_total)
    if count_gap_hint:
        lines.append(f"- 数量检查：{count_gap_hint}")

    active_plan_state = ordered_state or draft_state or {}
    active_summary = active_plan_state.get("summary") or {}
    tier_counts = active_summary.get("unitTierCounts") or active_summary.get("tierCounts") or {}
    if tier_counts:
        lines.append(f"- 冲稳保分布：{_format_tier_counts(tier_counts)}")

    if ordered_state:
        review_checks = (((planning_state or {}).get("reviewState") or {}).get("checks") or [])
        failed_checks = _review_failed_summaries(review_checks)
        gradient_ok = bool(active_summary.get("gradientOk")) and not _has_probability_gradient_warning(failed_checks)
        lines.append(f"- 录取率梯度是否达标：{'是' if gradient_ok else '否'}")
        lines.append(f"- 保底是否达标：{'是' if active_summary.get('safetyOk') else '否'}")
        for tier in ("冲", "稳", "保"):
            distribution = _format_tier_ratio_distribution(active_plan_state.get("items") or [], tier)
            if distribution:
                lines.append(f"- {distribution}")

    lines.append(f"- 风险与提醒：风险{summary.review_risk_count}项，提醒{summary.review_warn_count}项")

    if summary.risk_summaries:
        lines.append(f"- 当前主要提醒：{'；'.join(summary.risk_summaries)}")

    item_text = _format_plan_items(active_plan_state.get("items") or [], include_position=bool(ordered_state), limit=5)
    if item_text:
        prefix = "方案前列" if ordered_state else "草稿前列"
        lines.append(f"- {prefix}：{item_text}")

    if summary.pending_action_count > 0:
        lines.append(
            f"- 当前待处理建议：{summary.pending_action_count}项，主要为{'；'.join(summary.pending_action_summaries)}"
        )

    lines.extend(
        _build_plan_intent_relation_lines(
            planning_state,
            active_plan_state.get("items") or [],
            plan_summary=active_summary,
            include_position=bool(ordered_state),
        )
    )

    return "\n".join(lines)


def _format_candidate_pool_result(query_result: dict[str, Any]) -> str:
    items = query_result.get("items") or []
    total = query_result.get("total") or 0
    page = query_result.get("page") or 1
    page_size = query_result.get("pageSize") or len(items)

    lines = ["候选志愿查询结果："]
    lines.append(f"- 命中数量：{total}")
    lines.append(f"- 当前页：第{page}页，每页{page_size}条")
    item_text = _format_candidate_items(items)
    if item_text:
        lines.append(f"- 候选示例：{item_text}")
    else:
        lines.append("- 当前筛选条件下没有候选结果。")
    return "\n".join(lines)


async def _rerun_review_and_fetch_state(session_id: str) -> dict[str, Any] | None:
    try:
        await _run_planning_review_request(_DEFAULT_TENANT_ID, session_id)
    except Exception:
        logger.warning(
            "rerun review after planning mutation failed: session_id=%s",
            session_id,
            exc_info=True,
        )
    try:
        return await _get_planning_state_with_latest_profile(session_id)
    except Exception:
        logger.warning(
            "fetch planning state after mutation failed: session_id=%s",
            session_id,
            exc_info=True,
        )
    return None


async def query_planning_state(ctx: RunContext[RequestContext]) -> str:
    """读取当前会话的统一规划状态，并返回紧凑状态说明。"""
    session_id = ctx.deps.sessionid
    logger.info("query_planning_state called: session_id=%s", session_id)

    planning_state = await _get_planning_state_with_latest_profile(session_id)
    if not planning_state:
        return "获取当前规划状态失败，请稍后重试。"
    ordered_state, draft_state = await _load_visible_plan_states(session_id, planning_state)
    return _format_state_result(
        planning_state,
        ordered_state=ordered_state,
        draft_state=draft_state,
    )


async def query_planning_plan_overview(ctx: RunContext[RequestContext]) -> str:
    """读取当前方案状态，并补充排序/草稿前列内容，供“方案有了么”类问法使用。"""
    session_id = ctx.deps.sessionid
    logger.info("query_planning_plan_overview called: session_id=%s", session_id)

    planning_state = await _get_planning_state_with_latest_profile(session_id)
    if not planning_state:
        return "获取当前方案状态失败，请稍后重试。"
    summary = PlanningSummary.from_backend_state(planning_state)
    if summary is None:
        return "当前还没有读取到明确的方案状态。"

    ordered_state, draft_state = await _load_visible_plan_states(session_id, planning_state)

    return _format_plan_status_overview(
        planning_state,
        ordered_state=ordered_state,
        draft_state=draft_state,
    )


async def query_planning_draft(ctx: RunContext[RequestContext]) -> str:
    """读取当前会话的草稿方案摘要。"""
    session_id = ctx.deps.sessionid
    logger.info("query_planning_draft called: session_id=%s", session_id)

    result = await _get_planning_draft_request(session_id)
    if result.get("code") != 0:
        return "获取草稿方案失败，请稍后重试。"
    return _format_draft_result(result.get("data") or {})


async def query_planning_candidate_pool(
    ctx: RunContext[RequestContext],
    tiers: list[str] | None = None,
    province_names: list[str] | None = None,
    city_names: list[str] | None = None,
    school_keywords: list[str] | None = None,
    major_keywords: list[str] | None = None,
    school_tags: list[str] | None = None,
    major_tags: list[str] | None = None,
    sort_field: str = "finalScore",
    sort_order: str = "desc",
    page: int = 1,
    page_size: int = 10,
) -> str:
    """按条件查询当前候选池，返回可继续加入方案的 volunteerId 列表摘要。"""
    session_id = ctx.deps.sessionid
    logger.info(
        "query_planning_candidate_pool called: session_id=%s tiers=%s provinces=%s cities=%s school_keywords=%s major_keywords=%s school_tags=%s major_tags=%s sort=%s/%s page=%s page_size=%s",
        session_id,
        tiers,
        province_names,
        city_names,
        school_keywords,
        major_keywords,
        school_tags,
        major_tags,
        sort_field,
        sort_order,
        page,
        page_size,
    )

    result = await _query_planning_candidate_pool_request(
        _DEFAULT_TENANT_ID,
        session_id,
        tiers=tiers,
        province_names=province_names,
        city_names=city_names,
        school_keywords=school_keywords,
        major_keywords=major_keywords,
        school_tags=school_tags,
        major_tags=major_tags,
        sort_field=sort_field,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
    )
    if result.get("code") != 0:
        return "查询候选池失败，请稍后重试。"
    return _format_candidate_pool_result(result.get("data") or {})


async def select_planning_draft_items(
    ctx: RunContext[RequestContext],
    volunteer_ids: list[str],
    source: str = "user_agent",
) -> str:
    """将候选项加入当前方案选择。"""
    session_id = ctx.deps.sessionid
    logger.info(
        "select_planning_draft_items called: session_id=%s volunteer_ids=%s source=%s",
        session_id,
        volunteer_ids,
        source,
    )

    result = await _select_planning_draft_items_request(
        _DEFAULT_TENANT_ID,
        session_id,
        volunteer_ids,
        source=source,
    )
    if result.get("code") != 0:
        return "加入方案失败，请稍后重试。"
    return _format_draft_state_with_prefix(
        f"已加入{len(volunteer_ids)}个志愿到方案。",
        result.get("data") or {},
    )


async def select_planning_ordered_items(
    ctx: RunContext[RequestContext],
    volunteer_ids: list[str],
    source: str = "user_agent",
    regroup_by_tier: bool = True,
) -> str:
    """将候选项加入当前方案，并同步刷新排序结果。"""
    session_id = ctx.deps.sessionid
    logger.info(
        "select_planning_ordered_items called: session_id=%s volunteer_ids=%s source=%s regroup=%s",
        session_id,
        volunteer_ids,
        source,
        regroup_by_tier,
    )

    select_result = await _select_planning_draft_items_request(
        _DEFAULT_TENANT_ID,
        session_id,
        volunteer_ids,
        source=source,
    )
    if select_result.get("code") != 0:
        return "加入当前方案失败，请稍后重试。"

    ordered_result = await _generate_planning_ordered_plan_request(
        _DEFAULT_TENANT_ID,
        session_id,
        force_regenerate=True,
        regroup_by_tier=regroup_by_tier,
    )
    if ordered_result.get("code") != 0:
        return "已加入方案，但刷新当前方案排序失败，请稍后重试。"

    refreshed_state = await _rerun_review_and_fetch_state(session_id)
    ordered_state = ((refreshed_state or {}).get("orderedPlanState") or {}) or ((ordered_result.get("data") or {}).get("orderedPlanState") or {})
    return (
        f"已把{len(volunteer_ids)}个志愿加入当前方案，并同步刷新排序结果。\n"
        + _format_ordered_result(ordered_state)
    )


async def remove_planning_draft_items(
    ctx: RunContext[RequestContext],
    volunteer_ids: list[str],
) -> str:
    """将指定志愿移出当前方案选择。"""
    session_id = ctx.deps.sessionid
    logger.info(
        "remove_planning_draft_items called: session_id=%s volunteer_ids=%s",
        session_id,
        volunteer_ids,
    )

    result = await _remove_planning_draft_items_request(session_id, volunteer_ids)
    if result.get("code") != 0:
        return "移出方案失败，请稍后重试。"
    return _format_draft_state_with_prefix(
        f"已从方案移出{len(volunteer_ids)}个志愿。",
        result.get("data") or {},
    )


async def remove_planning_ordered_items(
    ctx: RunContext[RequestContext],
    volunteer_ids: list[str],
    regroup_by_tier: bool = True,
) -> str:
    """将指定志愿从当前方案移除，并同步刷新排序结果。"""
    session_id = ctx.deps.sessionid
    logger.info(
        "remove_planning_ordered_items called: session_id=%s volunteer_ids=%s regroup=%s",
        session_id,
        volunteer_ids,
        regroup_by_tier,
    )

    before_items: list[dict[str, Any]] = []
    try:
        before_result = await _get_planning_ordered_plan_request(session_id)
        if before_result.get("code") == 0:
            before_items = ((before_result.get("data") or {}).get("items") or [])
    except Exception:
        logger.warning("fetch ordered plan before removal failed: session_id=%s", session_id, exc_info=True)

    remove_result = await _remove_planning_draft_items_request(session_id, volunteer_ids)
    if remove_result.get("code") != 0:
        return "从当前方案移除志愿失败，请稍后重试。"

    ordered_result = await _generate_planning_ordered_plan_request(
        _DEFAULT_TENANT_ID,
        session_id,
        force_regenerate=True,
        regroup_by_tier=regroup_by_tier,
    )
    if ordered_result.get("code") != 0:
        return "已从草稿移除对应志愿，但刷新排序方案失败，请稍后重试。"

    refreshed_state = await _rerun_review_and_fetch_state(session_id)
    ordered_state = ((refreshed_state or {}).get("orderedPlanState") or {}) or ((ordered_result.get("data") or {}).get("orderedPlanState") or {})
    after_items = ordered_state.get("items") or []
    requested_id_set = {str(value) for value in volunteer_ids}
    after_id_set = {_volunteer_item_id(item) for item in after_items if _volunteer_item_id(item)}
    lingering_ids = [volunteer_id for volunteer_id in volunteer_ids if str(volunteer_id) in after_id_set]
    ban_fallback_used = False

    if lingering_ids:
        logger.info(
            "remove_planning_ordered_items fallback to ban: session_id=%s lingering_ids=%s",
            session_id,
            lingering_ids,
        )
        ban_result = await _ban_planning_draft_items_request(session_id, lingering_ids)
        if ban_result.get("code") == 0:
            ban_fallback_used = True
            ordered_result = await _generate_planning_ordered_plan_request(
                _DEFAULT_TENANT_ID,
                session_id,
                force_regenerate=True,
                regroup_by_tier=regroup_by_tier,
            )
            if ordered_result.get("code") != 0:
                return "已禁用仍残留的目标志愿，但刷新排序方案失败，请稍后重试。"
            refreshed_state = await _rerun_review_and_fetch_state(session_id)
            ordered_state = ((refreshed_state or {}).get("orderedPlanState") or {}) or ((ordered_result.get("data") or {}).get("orderedPlanState") or {})
            after_items = ordered_state.get("items") or []
            after_id_set = {_volunteer_item_id(item) for item in after_items if _volunteer_item_id(item)}
        else:
            logger.warning(
                "ban fallback after ordered removal failed: session_id=%s lingering_ids=%s",
                session_id,
                lingering_ids,
            )

    removed_items = [
        item for item in before_items
        if _volunteer_item_id(item) in requested_id_set and _volunteer_item_id(item) not in after_id_set
    ]
    lingering_items = [
        item for item in before_items
        if _volunteer_item_id(item) in requested_id_set and _volunteer_item_id(item) in after_id_set
    ]
    before_id_set = {_volunteer_item_id(item) for item in before_items if _volunteer_item_id(item)}
    added_items = [
        item for item in after_items
        if before_id_set and _volunteer_item_id(item) and _volunteer_item_id(item) not in before_id_set
    ]
    removed_count = len(requested_id_set) - len({item_id for item_id in after_id_set if item_id in requested_id_set})

    if lingering_items:
        lines = [f"已尝试移出{len(requested_id_set)}个志愿，但仍有{len(lingering_items)}个志愿保留在当前方案中。"]
    else:
        lines = [f"已从当前方案移出{removed_count}个志愿，并同步刷新排序方案。"]
        if ban_fallback_used:
            lines.append("检测到常规移除后仍有目标残留，已自动禁用这些目标，避免后续刷新再次带回。")

    removed_text = _format_plan_item_names(removed_items)
    if removed_text:
        lines.append(f"移出的志愿：{removed_text}")
    lingering_text = _format_plan_item_names(lingering_items)
    if lingering_text:
        lines.append(f"仍保留的志愿：{lingering_text}")
    added_text = _format_plan_item_names(added_items)
    if added_text:
        lines.append(f"重新补入/排序后的新增志愿：{added_text}")
    elif not lingering_items and len(after_items) >= len(before_items):
        lines.append("排序方案已重新补齐，但本次返回数据里没有展开新增志愿明细。")
    lines.append(_format_ordered_result(ordered_state, refreshed_state))
    return "\n".join(lines)


async def lock_planning_draft_items(
    ctx: RunContext[RequestContext],
    volunteer_ids: list[str],
    locked: bool = True,
) -> str:
    """兼容旧接口：新版工作台不再提供用户侧锁定入口。"""
    session_id = ctx.deps.sessionid
    logger.info(
        "lock_planning_draft_items called: session_id=%s volunteer_ids=%s locked=%s",
        session_id,
        volunteer_ids,
        locked,
    )

    return "新版工作台暂不提供固定/锁定志愿入口。可以改用移动到指定位置或方案排序。"


async def ban_planning_draft_items(
    ctx: RunContext[RequestContext],
    volunteer_ids: list[str],
) -> str:
    """禁用候选项并从草稿中移除。"""
    session_id = ctx.deps.sessionid
    logger.info(
        "ban_planning_draft_items called: session_id=%s volunteer_ids=%s",
        session_id,
        volunteer_ids,
    )

    result = await _ban_planning_draft_items_request(session_id, volunteer_ids)
    if result.get("code") != 0:
        return "禁用候选项失败，请稍后重试。"
    return _format_draft_state_with_prefix(
        f"已禁用{len(volunteer_ids)}个候选志愿，并同步更新草稿。",
        result.get("data") or {},
    )


async def query_planning_ordered_plan(ctx: RunContext[RequestContext]) -> str:
    """读取当前会话的排序方案摘要。"""
    session_id = ctx.deps.sessionid
    logger.info("query_planning_ordered_plan called: session_id=%s", session_id)

    result = await _get_planning_ordered_plan_request(session_id)
    if result.get("code") != 0:
        return "获取排序方案失败，请稍后重试。"
    return _format_ordered_result(result.get("data") or {})


async def generate_planning_ordered_plan(
    ctx: RunContext[RequestContext],
    user_confirmed: bool = False,
    force_regenerate: bool = False,
    regroup_by_tier: bool = True,
) -> str:
    """在用户确认后生成或重排当前排序方案。"""
    session_id = ctx.deps.sessionid
    logger.info(
        "generate_planning_ordered_plan called: session_id=%s confirmed=%s force=%s regroup=%s",
        session_id,
        user_confirmed,
        force_regenerate,
        regroup_by_tier,
    )

    if not user_confirmed:
        return "这是会直接重排当前方案的操作。请先在对话中获得用户明确确认，再调用该工具。"

    result = await _generate_planning_ordered_plan_request(
        _DEFAULT_TENANT_ID,
        session_id,
        force_regenerate=force_regenerate,
        regroup_by_tier=regroup_by_tier,
    )
    if result.get("code") != 0:
        return "生成排序方案失败，请稍后重试。"
    refreshed_state = await _rerun_review_and_fetch_state(session_id)
    ordered_state = ((refreshed_state or {}).get("orderedPlanState") or {}) or ((result.get("data") or {}).get("orderedPlanState") or {})
    return "已生成最新排序方案。\n" + _format_ordered_result(ordered_state)


async def generate_planning_initial_plan(
    ctx: RunContext[RequestContext],
    user_confirmed: bool = False,
    force_regenerate: bool = True,
    regroup_by_tier: bool = True,
    overwrite_existing_draft: bool = False,
) -> str:
    """按当前画像、约束和候选视图生成一版方案。"""
    session_id = ctx.deps.sessionid
    planning = getattr(ctx.deps, "planning_summary", None)
    has_existing_plan = bool(
        planning
        and ((planning.draft_total or 0) > 0 or (planning.ordered_total or 0) > 0)
    )
    logger.info(
        "generate_planning_initial_plan called: session_id=%s confirmed=%s force=%s regroup=%s overwrite=%s existing=%s",
        session_id,
        user_confirmed,
        force_regenerate,
        regroup_by_tier,
        overwrite_existing_draft,
        has_existing_plan,
    )

    if has_existing_plan and not user_confirmed:
        return "当前已经有方案。若要按当前条件重新出一版方案并覆盖现有内容，请先在对话中明确确认。"

    pool_result = await _generate_planning_candidate_pool_request(
        _DEFAULT_TENANT_ID, session_id, True,
    )
    pool_code = pool_result.get("code") if isinstance(pool_result, dict) else -1
    if pool_code != 0:
        pool_msg = (pool_result or {}).get("msg") or "候选池生成失败"
        logger.warning(
            "generate_planning_initial_plan: candidate pool failed, session_id=%s, code=%s, msg=%s",
            session_id, pool_code, pool_msg,
        )
        if pool_code == 404:
            return "生成方案失败：会话数据不完整，缺少成绩信息或基础会话记录。请先补全成绩和基础信息后再试。"
        return f"生成方案失败：候选池生成异常（{pool_msg}），请稍后重试。"

    result = await _generate_planning_initial_plan_request(
        _DEFAULT_TENANT_ID,
        session_id,
        force_regenerate=force_regenerate,
        regroup_by_tier=regroup_by_tier,
        overwrite_existing_draft=overwrite_existing_draft or has_existing_plan,
    )
    if result.get("code") != 0:
        err = result.get("msg") or result.get("error") or "未知错误"
        logger.warning("generate_planning_initial_plan failed: session_id=%s code=%s msg=%s", session_id, result.get("code"), err)
        return f"生成方案失败（{err}），请稍后重试。"
    planning_state = await _rerun_review_and_fetch_state(session_id) or (result.get("data") or {})
    ordered_state = planning_state.get("orderedPlanState") or {}
    return "已按当前条件生成一版方案。\n" + _format_ordered_result(ordered_state)


async def move_planning_ordered_item(
    ctx: RunContext[RequestContext],
    volunteer_id: str,
    target_position: int,
) -> str:
    """移动指定志愿在排序方案中的位置。"""
    session_id = ctx.deps.sessionid
    logger.info(
        "move_planning_ordered_item called: session_id=%s volunteer_id=%s target_position=%s",
        session_id,
        volunteer_id,
        target_position,
    )

    result = await _move_planning_ordered_item_request(session_id, volunteer_id, target_position)
    if result.get("code") != 0:
        return "移动排序项失败，请稍后重试。"
    refreshed_state = await _rerun_review_and_fetch_state(session_id)
    ordered_state = ((refreshed_state or {}).get("orderedPlanState") or {}) or ((result.get("data") or {}).get("orderedPlanState") or {})
    return f"已将志愿移动到第{target_position}位。\n" + _format_ordered_result(ordered_state)


async def pin_planning_ordered_item(
    ctx: RunContext[RequestContext],
    volunteer_id: str,
    target_position: int,
) -> str:
    """固定指定志愿在排序方案中的位置。"""
    session_id = ctx.deps.sessionid
    logger.info(
        "pin_planning_ordered_item called: session_id=%s volunteer_id=%s target_position=%s",
        session_id,
        volunteer_id,
        target_position,
    )

    result = await _pin_planning_ordered_item_request(session_id, volunteer_id, target_position)
    if result.get("code") != 0:
        return "固定排序项失败，请稍后重试。"
    refreshed_state = await _rerun_review_and_fetch_state(session_id)
    ordered_state = ((refreshed_state or {}).get("orderedPlanState") or {}) or ((result.get("data") or {}).get("orderedPlanState") or {})
    return f"已将志愿固定在第{target_position}位。\n" + _format_ordered_result(ordered_state)


async def unpin_planning_ordered_item(
    ctx: RunContext[RequestContext],
    volunteer_id: str,
) -> str:
    """取消固定指定志愿。"""
    session_id = ctx.deps.sessionid
    logger.info(
        "unpin_planning_ordered_item called: session_id=%s volunteer_id=%s",
        session_id,
        volunteer_id,
    )

    result = await _unpin_planning_ordered_item_request(session_id, volunteer_id)
    if result.get("code") != 0:
        return "取消固定排序项失败，请稍后重试。"
    refreshed_state = await _rerun_review_and_fetch_state(session_id)
    ordered_state = ((refreshed_state or {}).get("orderedPlanState") or {}) or ((result.get("data") or {}).get("orderedPlanState") or {})
    return "已取消该志愿的位置标记。\n" + _format_ordered_result(ordered_state)


async def run_planning_review(ctx: RunContext[RequestContext]) -> str:
    """执行当前会话方案审查，返回简洁的风险摘要与下一步建议。"""
    session_id = ctx.deps.sessionid
    logger.info("run_planning_review called: session_id=%s", session_id)

    result = await _run_planning_review_request(_DEFAULT_TENANT_ID, session_id)
    if result.get("code") != 0:
        return "执行方案审查失败，请稍后重试。"
    planning_state = await _get_planning_state_with_latest_profile(session_id)
    ordered_state, draft_state = await _load_visible_plan_states(session_id, planning_state)
    return _format_review_result(
        result.get("data") or {},
        planning_state=planning_state,
        ordered_state=ordered_state,
        draft_state=draft_state,
    )


async def analyze_planning_plan_adjustment(ctx: RunContext[RequestContext]) -> str:
    """分析当前方案的可调整建议，但不直接改动方案。"""
    session_id = ctx.deps.sessionid
    logger.info("analyze_planning_plan_adjustment called: session_id=%s", session_id)

    result = await _analyze_planning_plan_adjustment_request(_DEFAULT_TENANT_ID, session_id)
    if result.get("code") != 0:
        return "分析当前方案的调整建议失败，请稍后重试。"
    planning_state = await _get_planning_state_with_latest_profile(session_id)
    ordered_state, draft_state = await _load_visible_plan_states(session_id, planning_state)
    return _format_plan_adjustment_result(
        result.get("data") or {},
        planning_state=planning_state,
        ordered_state=ordered_state,
        draft_state=draft_state,
    )


async def preview_planning_compensation(ctx: RunContext[RequestContext]) -> str:
    """预览当前会话的自动补偿建议，不直接改动方案。"""
    session_id = ctx.deps.sessionid
    logger.info("preview_planning_compensation called: session_id=%s", session_id)

    result = await _preview_planning_compensation_request(session_id)
    if result.get("code") != 0:
        return "预览补偿建议失败，请稍后重试。"
    return _format_compensation_preview(result.get("data") or {})


async def apply_planning_compensation(
    ctx: RunContext[RequestContext],
    user_confirmed: bool = False,
    regenerate_ordered_plan: bool = True,
    rerun_review: bool = True,
) -> str:
    """在用户明确确认后应用自动补偿，并可选择是否重排和复审。"""
    session_id = ctx.deps.sessionid
    logger.info(
        "apply_planning_compensation called: session_id=%s user_confirmed=%s regenerate=%s rerun_review=%s",
        session_id,
        user_confirmed,
        regenerate_ordered_plan,
        rerun_review,
    )

    if not user_confirmed:
        return "这是直接改动当前方案的操作。请先在对话中获得用户明确确认，再调用该工具。"

    result = await _apply_planning_compensation_request(
        _DEFAULT_TENANT_ID,
        session_id,
        regenerate_ordered_plan=regenerate_ordered_plan,
        rerun_review=rerun_review,
    )
    if result.get("code") != 0:
        return "应用补偿建议失败，请稍后重试。"
    latest_state = result.get("data") or {}
    ordered_state, draft_state = await _load_visible_plan_states(session_id, latest_state)
    return _format_apply_result(
        latest_state,
        ordered_state=ordered_state,
        draft_state=draft_state,
    )
