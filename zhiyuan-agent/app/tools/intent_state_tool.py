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

from pydantic_ai import RunContext

from app.agent.context import RequestContext, has_pending_intent_confirmation, resolve_pending_confirmation
from app.domain.career_slots import (
    CAREER_FURTHER_STUDY,
    CAREER_LABEL_MAP,
    CAREER_STABLE_EMPLOYMENT,
    CAREER_SYSTEM_PUBLIC_SERVICE,
    is_career_slot,
    to_career_label,
    to_career_labels,
)
from app.services.profile_manager import ProfileManager
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
from app.util.code_enrichment import (
    add_codes_to_profile,
    get_major_codes,
    get_major_codes_async,
    normalize_candidate_filters_async,
    resolve_major_names_async,
)
from app.util.internal_client import (
    get_intent_change_cache,
    get_planning_state,
    get_message_by_id,
    query_planning_candidate_pool,
    save_intent_change_cache,
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
ANALYSIS_STAGE_INTEREST = "interest"
ANALYSIS_STAGE_CONFIRMED = "confirmed"
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
        _extend(city_intents.get("negative_province"), negative=True)
        _extend(city_intents.get("negative_city"), negative=True)
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


def _merge_intent_payload_dict(existing: dict[str, Any] | None, current: dict[str, Any] | None) -> dict[str, Any] | None:
    merged: dict[str, list[str]] = {}
    for payload in (existing or {}, current or {}):
        for key, values in payload.items():
            normalized_values = _as_string_list(values)
            if not normalized_values:
                continue
            merged[key] = _merge_list(merged.get(key), normalized_values)
    return merged or None


async def _merge_cache_data_with_existing_pending(session_id: str, current_cache: dict[str, Any]) -> dict[str, Any]:
    existing_merged, _ = await _load_cached_intents(session_id)
    merged_major = _merge_intent_payload_dict(existing_merged.get("major_intents"), current_cache.get("major_intents"))
    merged_school = _merge_intent_payload_dict(existing_merged.get("school_intents"), current_cache.get("school_intents"))
    merged_city = _merge_intent_payload_dict(existing_merged.get("city_intents"), current_cache.get("city_intents"))
    merged_career = _merge_intent_payload_dict(existing_merged.get("career_intents"), current_cache.get("career_intents"))
    merged_mode = _classify_intent_mode(
        merged_major,
        merged_school,
        merged_city,
        merged_career,
        explicit_intent_mode=None,
    )
    return _build_cache_data(
        merged_major,
        merged_school,
        merged_city,
        merged_career,
        merged_mode,
    )


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
_CITY_POSITIVE_KEYS = ("province", "city")
_CITY_NEGATIVE_KEYS = ("negative_province", "negative_city")
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
    "city_intents.negative_province": "排除省份",
    "city_intents.negative_city": "排除城市",
    "career_intents.positive": "就业导向偏好",
    "career_intents.negative": "排除就业导向",
}


def _is_negative_key(sub_key: str) -> bool:
    return sub_key.startswith("negative_")


def _build_select_items(
    current_profile: Any,
    major_intents: dict | None,
    school_intents: dict | None,
    city_intents: dict | None,
    career_intents: dict | None = None,
    *,
    intent_mode: str = INTENT_MODE_PREFERENCE,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Generate structured items for selective adoption popup.

    Returns:
        (items, existing_items)
        - items: new intents, each with content/value/selected
        - existing_items: already-in-profile intents, display-only
    """
    items: list[dict[str, Any]] = []
    existing_items: list[dict[str, Any]] = []

    # --- Major intents ---
    if major_intents:
        for level in _MAJOR_POSITIVE_KEYS:
            names = major_intents.get(level, [])
            if not names:
                continue
            existing = getattr(current_profile.major, level, [])
            for name in names:
                _, already = _diff_list(existing, [name])
                label = _LABEL_MAP[f"major_intents.{level}"]
                if already:
                    existing_items.append({
                        "content": f"当前已记录偏好{label}：{name}",
                    })
                else:
                    items.append({
                        "content": f"确认后，将把{name}作为后续优先参考的专业方向。",
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
                label = _LABEL_MAP[f"major_intents.{level}"]
                if already:
                    existing_items.append({
                        "content": f"当前已记录{label}：{name}",
                    })
                else:
                    items.append({
                        "content": (
                            f"确认后，将把{name}作为后续尽量降低优先级的专业方向。"
                            if intent_mode == INTENT_MODE_PREFERENCE
                            else f"确认后，将把{name}作为明确不考虑的内容，后续查看候选和方案时会按这个要求作为参考。"
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
                if already:
                    existing_items.append({
                        "content": f"当前已记录偏好{label}：{name}",
                    })
                else:
                    items.append({
                        "content": f"确认后，将把{name}作为后续优先参考的院校。",
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
                label = _LABEL_MAP[f"school_intents.{sub_key}"]
                if already:
                    existing_items.append({
                        "content": f"当前已记录{label}：{name}",
                    })
                else:
                    items.append({
                        "content": (
                            f"确认后，将把{name}作为后续尽量降低优先级的院校。"
                            if intent_mode == INTENT_MODE_PREFERENCE
                            else f"确认后，将把{name}作为明确不考虑的院校，后续查看候选和方案时会按这个要求作为参考。"
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
                if already:
                    existing_items.append({
                        "content": f"当前已记录偏好{label}：{name}",
                    })
                else:
                    items.append({
                        "content": f"确认后，将把{name}作为后续优先参考的地域。",
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
                label = _LABEL_MAP[f"city_intents.{sub_key}"]
                if already:
                    existing_items.append({
                        "content": f"当前已记录{label}：{name}",
                    })
                else:
                    items.append({
                        "content": (
                            f"确认后，将把{name}作为你暂时不太想去的地区，后续查看方案时会尽量往后放。"
                            if intent_mode == INTENT_MODE_PREFERENCE
                            else f"确认后，将把{name}作为明确不考虑的地区，后续查看候选和方案时会按这个要求作为参考。"
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
                    "content": f"确认后，将把“{label}”作为你更看重的方向，后续我会优先按这个思路帮你看方案。",
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
                    "content": f"确认后，将把“{label}”作为你暂时不考虑的方向，后续我会尽量避开这类建议。",
                    "value": {"career_intents": {sub_key: [value]}},
                    "selected": True,
                })

    return items, existing_items


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
        suffix = "确认前不会写入后续参考，也不会直接改动当前方案。"
    else:
        suffix = "确认后我会按这个思路继续帮你看方案和给建议。"
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
                f"目前，系统暂不支持直接对志愿列表进行{flags_desc}操作。"
                f"不过，我先帮你把相关的{('要求' if intent_mode == INTENT_MODE_CONSTRAINT else '想法')}整理出来了。{suffix}"
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


def _classify_intent_mode(
    major_intents: dict | None,
    school_intents: dict | None,
    city_intents: dict | None,
    career_intents: dict | None = None,
    *,
    edit_flag: str | None = None,
    explicit_intent_mode: str | None = None,
) -> str:
    if explicit_intent_mode in {INTENT_MODE_PREFERENCE, INTENT_MODE_CONSTRAINT}:
        return explicit_intent_mode
    if not _has_negative_intents(major_intents, school_intents, city_intents, career_intents):
        return INTENT_MODE_PREFERENCE

    return INTENT_MODE_CONSTRAINT


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
    return (
        _normalize_intent_payload(
            major_intents,
            allowed_keys=_MAJOR_POSITIVE_KEYS + _MAJOR_NEGATIVE_KEYS,
            alias_map=major_aliases,
        ),
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
    return normalized or None


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


async def _recover_intents_from_context(
    ctx: RunContext[RequestContext],
    recovery_scope: str | None = None,
) -> tuple[dict | None, dict | None, dict | None, dict | None]:
    """Best-effort recovery when the model calls intent analysis with empty params."""
    from app.tools.career_intent_tool import extract_career_intent
    from app.tools.city_intent_tool import extract_city_intent, extract_negative_city_intent
    from app.tools.major_intent_tool import extract_major_intent, extract_negative_major_intent
    from app.tools.school_intent_tool import extract_school_intent

    recovered_major: dict[str, Any] = {}
    recovered_school: dict[str, Any] = {}
    recovered_city: dict[str, Any] = {}
    recovered_career: dict[str, Any] = {}
    recovery_ctx = _build_single_turn_recovery_context(ctx)
    normalized_scope = (recovery_scope or "generic").strip().lower()
    batch = ctx.deps.batch or "01"

    if normalized_scope == "career_preference":
        extracted_career = json.loads(await extract_career_intent(recovery_ctx))
        if _has_non_empty_payload(extracted_career):
            recovered_career.update(extracted_career)
        return None, None, None, _drop_empty_entries(recovered_career)

    if normalized_scope in {"generic", "region", "city"}:
        try:
            positive_city = json.loads(await extract_city_intent(recovery_ctx))
            negative_city = json.loads(await extract_negative_city_intent(recovery_ctx))
            for key in ("province", "city", "area"):
                values = positive_city.get(key, [])
                if values:
                    recovered_city[key] = values
            for key in ("province", "city", "area"):
                values = negative_city.get(key, [])
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

    if normalized_scope in {"generic", "school"}:
        try:
            school = json.loads(await extract_school_intent(recovery_ctx))
            if school.get("colleges"):
                recovered_school["colleges"] = school["colleges"]
            if school.get("negative_colleges"):
                recovered_school["negative_colleges"] = school["negative_colleges"]
        except Exception:
            logger.warning("Fallback school intent extraction failed: session_id=%s", ctx.deps.sessionid, exc_info=True)

    if normalized_scope == "generic":
        try:
            extracted_career = json.loads(await extract_career_intent(recovery_ctx))
            if _has_non_empty_payload(extracted_career):
                recovered_career.update(extracted_career)
        except Exception:
            logger.warning("Fallback career intent extraction failed: session_id=%s", ctx.deps.sessionid, exc_info=True)

    return (
        recovered_major or None,
        recovered_school or None,
        recovered_city or None,
        _drop_empty_entries(recovered_career),
    )


def _build_candidate_filters_from_intents(merged: dict[str, Any]) -> dict[str, Any]:
    city_intents = merged.get("city_intents") or {}
    school_intents = merged.get("school_intents") or {}
    major_intents = merged.get("major_intents") or {}
    major_categories = list(dict.fromkeys(major_intents.get("level2", []) or []))
    negative_major_categories = list(dict.fromkeys(major_intents.get("negative_level2", []) or []))
    # `majorKeywords` 当前兼容承接 `major.category`。
    # 对具体专业（level3）仅在没有 level2 时兜底复用，避免继续把三个层级混入同一字段。
    if not major_categories:
        major_categories = list(dict.fromkeys(major_intents.get("level3", []) or []))
    if not negative_major_categories:
        negative_major_categories = list(dict.fromkeys(major_intents.get("negative_level3", []) or []))
    return {
        "provinceNames": city_intents.get("province", []),
        "negativeProvinceNames": city_intents.get("negative_province", []),
        "cityNames": city_intents.get("city", []),
        "negativeCityNames": city_intents.get("negative_city", []),
        "schoolKeywords": school_intents.get("colleges", []),
        "negativeSchoolKeywords": school_intents.get("negative_colleges", []),
        "majorKeywords": major_categories,
        "negativeMajorKeywords": negative_major_categories,
        "schoolTags": [],
        "negativeSchoolTags": [],
        "majorTags": major_intents.get("level1", []),
        "negativeMajorTags": major_intents.get("negative_level1", []),
    }


async def _query_candidate_total(session_id: str, candidate_filters: dict[str, Any]) -> int | None:
    try:
        resp = await query_planning_candidate_pool(
            1,
            int(session_id),
            tiers=candidate_filters.get("tiers"),
            province_names=candidate_filters.get("provinceNames"),
            negative_province_names=candidate_filters.get("negativeProvinceNames"),
            city_names=candidate_filters.get("cityNames"),
            negative_city_names=candidate_filters.get("negativeCityNames"),
            school_keywords=candidate_filters.get("schoolKeywords"),
            negative_school_keywords=candidate_filters.get("negativeSchoolKeywords"),
            major_keywords=candidate_filters.get("majorKeywords"),
            negative_major_keywords=candidate_filters.get("negativeMajorKeywords"),
            school_tags=candidate_filters.get("schoolTags"),
            negative_school_tags=candidate_filters.get("negativeSchoolTags"),
            major_tags=candidate_filters.get("majorTags"),
            negative_major_tags=candidate_filters.get("negativeMajorTags"),
            page=1,
            page_size=1,
        )
        return (resp or {}).get("data", {}).get("total")
    except Exception:
        logger.warning("Query filtered candidate total failed: session_id=%s", session_id, exc_info=True)
        return None


async def _query_candidate_base_total(session_id: str) -> int | None:
    try:
        planning_state = await get_planning_state(int(session_id))
        return (((planning_state or {}).get("data") or {}).get("candidatePoolState") or {}).get("summary", {}).get("total")
    except Exception:
        logger.warning("Query candidate base total failed: session_id=%s", session_id, exc_info=True)
        return None


def _build_minimal_request_context(session_id: str, batch: str) -> RunContext[RequestContext]:
    request_context = RequestContext(
        userid="",
        sessionid=session_id,
        chat_history=[],
        batch=batch,
        score_detail=None,
        init_profile=None,
        planning_summary=None,
    )
    return SimpleNamespace(deps=request_context)


async def _load_cached_intents(session_id: str) -> tuple[dict[str, Any], str]:
    cache_result = await get_intent_change_cache(session_id)
    cache_data = (cache_result or {}).get("data", {}).get("planEditCache") or {}
    merged = {
        "major_intents": cache_data.get("major_intents") or {},
        "school_intents": cache_data.get("school_intents") or {},
        "city_intents": cache_data.get("city_intents") or {},
        "career_intents": cache_data.get("career_intents") or {},
    }
    intent_mode = cache_data.get("intent_mode") or INTENT_MODE_PREFERENCE
    return merged, intent_mode


async def _apply_intents(
    *,
    session_id: str,
    batch: str,
    merged: dict[str, Any],
    intent_mode: str,
) -> IntentStateUpdateResult:
    pm = ProfileManager(int(session_id), batch)

    major_intents = merged.get("major_intents")
    if major_intents:
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

    await save_intent_change_cache(int(session_id), {})

    if intent_mode == INTENT_MODE_CONSTRAINT:
        candidate_filters = await normalize_candidate_filters_async(
            _build_candidate_filters_from_intents(merged),
            batch,
        )
        base_total = await _query_candidate_base_total(session_id)
        filtered_total = await _query_candidate_total(session_id, candidate_filters)
        logger.info("Constraint intents applied without regenerating candidate pool: session_id=%s", session_id)
        result = IntentStateUpdateResult(
            action="apply",
            sessionId=session_id,
            intentMode=intent_mode,
            applied=True,
            messageCode="constraint_applied",
            merged=merged,
            candidateFilters=candidate_filters,
            filteredTotal=filtered_total,
            baseTotal=base_total,
        )
        result.message = render_intent_state_update(result)
        return result

    logger.info("Preference intents applied: session_id=%s", session_id)
    result = IntentStateUpdateResult(
        action="apply",
        sessionId=session_id,
        intentMode=intent_mode,
        applied=True,
        messageCode="preference_applied",
        merged=merged,
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
    persist_cache: bool | None = None,
) -> str:
    """Analyze intent changes and return structured facts as JSON.

    This tool only prepares structured analysis data and caches pending intents.
    It does not execute profile/planning updates.
    Do not use it for read-only fit questions like "电子信息工程适合我吗" or
    "网络与新媒体适不适合我" unless you are intentionally asking for interest-stage
    analysis with no state persistence.
    """
    session_id = ctx.deps.sessionid
    batch = ctx.deps.batch or "01"
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
        if persist_cache is None:
            persist_cache = False

    major_intents, school_intents, city_intents, career_intents = _normalize_intent_inputs(
        major_intents,
        school_intents,
        city_intents,
        career_intents,
    )
    major_intents = await _normalize_major_intent_names_for_batch(major_intents, batch)

    if not _has_any_intent_payload(major_intents, school_intents, city_intents, career_intents) and _should_attempt_intent_recovery(
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
        major_intents = await _normalize_major_intent_names_for_batch(major_intents, batch)

    if not _has_any_intent_payload(major_intents, school_intents, city_intents, career_intents):
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
    )

    pm = ProfileManager(int(session_id), batch)
    current_profile = await pm.get_current_profile()

    items_raw, existing_items_raw = _build_select_items(
        current_profile,
        major_intents,
        school_intents,
        city_intents,
        career_intents,
        intent_mode=resolved_intent_mode,
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

    cache_data = _build_cache_data(major_intents, school_intents, city_intents, career_intents, resolved_intent_mode)
    should_persist_cache = persist_cache if persist_cache is not None else True
    if should_persist_cache:
        cache_data = await _merge_cache_data_with_existing_pending(session_id, cache_data)
        await save_intent_change_cache(int(session_id), cache_data)
    else:
        logger.info(
            "Skipping intent change cache persistence for read-only analysis: session_id=%s analysis_stage=%s utterance=%s",
            session_id,
            analysis_stage,
            latest_utterance,
        )

    payload = IntentAnalysisPayload(
        status="existing_only" if not items else "ready",
        sessionId=session_id,
        title=_build_preview_title(edit_flag, resolved_intent_mode, analysis_stage),
        intentMode=resolved_intent_mode,
        analysisStage=analysis_stage,
        editFlag=edit_flag,
        items=items,
        existingItems=existing_items,
        impactText=impact_text,
        impactAnalysis=impact_analysis,
    )
    return serialize_intent_analysis_payload(payload)


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
    batch = batch or "01"
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

    intent_mode = INTENT_MODE_PREFERENCE
    if message_id:
        try:
            msg_resp = await get_message_by_id(message_id)
            msg_data = (msg_resp or {}).get("data", {})
            content_raw = msg_data.get("content", "")
            content_obj = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
            if isinstance(content_obj, dict):
                intent_mode = content_obj.get("intentMode") or INTENT_MODE_PREFERENCE
        except Exception:
            logger.warning("读取意向确认卡片模式失败，默认按偏好处理: session_id=%s", session_id, exc_info=True)

    try:
        result = await update_volunteer_intent_state(
            _build_minimal_request_context(session_id, batch),
            action="apply_selected",
            merged=merged,
            intent_mode=intent_mode,
        )
        return result
    except Exception:
        logger.exception("Applying selected intent changes failed: session_id=%s", session_id)
        return serialize_intent_state_update_result(
            IntentStateUpdateResult(
                action="apply_selected",
                sessionId=session_id,
                messageCode="apply_failed",
            )
        )
async def update_volunteer_intent_state(
    ctx: RunContext[RequestContext],
    action: str = "confirm",
    merged: dict[str, Any] | None = None,
    intent_mode: str | None = None,
) -> str:
    """Manage intent state updates and return structured execution facts as JSON."""
    session_id = ctx.deps.sessionid
    batch = getattr(ctx.deps, "batch", None) or "01"
    normalized_action = (action or "confirm").strip().lower()
    started_at = time.monotonic()
    logger.info("update_volunteer_intent_state: session_id=%s action=%s", session_id, normalized_action)

    try:
        if normalized_action == "reject":
            await save_intent_change_cache(int(session_id), {})
            result = IntentStateUpdateResult(
                action="reject",
                sessionId=session_id,
                applied=False,
                messageCode="reject_success",
            )
            log_event(
                "intent_state_event",
                sessionId=session_id,
                action="reject",
                applied=False,
                messageCode="reject_success",
                durationMs=int((time.monotonic() - started_at) * 1000),
                status="success",
            )
            return serialize_intent_state_update_result(result)

        resolved_merged = merged
        resolved_mode = intent_mode or INTENT_MODE_PREFERENCE
        if normalized_action == "confirm":
            latest_utterance = _latest_user_utterance(ctx)
            had_pending_before_turn = has_pending_intent_confirmation(ctx.deps)
            if (
                not had_pending_before_turn
                and not _is_intent_confirmation_utterance(latest_utterance)
            ):
                result = IntentStateUpdateResult(
                    action="confirm",
                    sessionId=session_id,
                    intentMode=resolved_mode,
                    applied=False,
                    messageCode="confirm_required",
                )
                log_event(
                    "intent_state_event",
                    sessionId=session_id,
                    action="confirm",
                    applied=False,
                    messageCode="confirm_required",
                    durationMs=int((time.monotonic() - started_at) * 1000),
                    status="error",
                )
                return serialize_intent_state_update_result(result)
            pending_confirmation = resolve_pending_confirmation(ctx.deps)
            cache_data = None
            if pending_confirmation is not None and pending_confirmation.kind == "intent_change":
                cache_data = pending_confirmation.execution_payload
            if not isinstance(cache_data, dict) or not cache_data:
                cache_result = await get_intent_change_cache(session_id)
                cache_data = (cache_result or {}).get("data", {}).get("planEditCache")
            if not cache_data:
                result = IntentStateUpdateResult(
                    action="confirm",
                    sessionId=session_id,
                    applied=False,
                    messageCode="no_pending",
                )
                log_event(
                    "intent_state_event",
                    sessionId=session_id,
                    action="confirm",
                    applied=False,
                    messageCode="no_pending",
                    durationMs=int((time.monotonic() - started_at) * 1000),
                    status="error",
                )
                return serialize_intent_state_update_result(result)
            resolved_mode = cache_data.get("intent_mode") or INTENT_MODE_PREFERENCE
            resolved_merged = {
                "major_intents": cache_data.get("major_intents") or {},
                "school_intents": cache_data.get("school_intents") or {},
                "city_intents": cache_data.get("city_intents") or {},
                "career_intents": cache_data.get("career_intents") or {},
            }

        if not resolved_merged:
            result = IntentStateUpdateResult(
                action=normalized_action,
                sessionId=session_id,
                intentMode=resolved_mode,
                applied=False,
                messageCode="empty_update",
            )
            log_event(
                "intent_state_event",
                sessionId=session_id,
                action=normalized_action,
                applied=False,
                messageCode="empty_update",
                durationMs=int((time.monotonic() - started_at) * 1000),
                status="error",
            )
            return serialize_intent_state_update_result(result)

        result = await _apply_intents(
            session_id=session_id,
            batch=batch,
            merged=resolved_merged,
            intent_mode=resolved_mode,
        )
        result.action = normalized_action
        log_event(
            "intent_state_event",
            sessionId=session_id,
            action=normalized_action,
            applied=bool(result.applied),
            messageCode=result.messageCode,
            intentMode=result.intentMode,
            durationMs=int((time.monotonic() - started_at) * 1000),
            status="success" if result.applied else "error",
        )
        return serialize_intent_state_update_result(result)
    except Exception:
        logger.exception("update_volunteer_intent_state failed: session_id=%s action=%s", session_id, normalized_action)
        message_code = "apply_failed" if normalized_action != "reject" else "reject_failed"
        log_event(
            "intent_state_event",
            sessionId=session_id,
            action=normalized_action,
            applied=False,
            messageCode=message_code,
            durationMs=int((time.monotonic() - started_at) * 1000),
            status="error",
            errorType=message_code,
        )
        return serialize_intent_state_update_result(
            IntentStateUpdateResult(
                action=normalized_action,
                sessionId=session_id,
                intentMode=intent_mode or INTENT_MODE_PREFERENCE,
                applied=False,
                messageCode=message_code,
            )
        )
