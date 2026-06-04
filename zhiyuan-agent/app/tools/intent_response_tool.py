"""Intent response models and text rendering helpers."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from app.domain.career_slots import to_career_labels
from app.domain.major_entity_resolver import build_major_relation_notes


class IntentPreviewItem(BaseModel):
    content: str
    value: dict[str, Any] | None = None
    selected: bool = True


class IntentAnalysisPayload(BaseModel):
    status: str
    sessionId: str
    title: str = ""
    intentMode: str = "preference"
    analysisStage: str = "confirmed"
    editFlag: str | None = None
    items: list[IntentPreviewItem] = Field(default_factory=list)
    existingItems: list[IntentPreviewItem] = Field(default_factory=list)
    impactText: str = ""
    impactAnalysis: dict[str, Any] | None = None
    message: str = ""


class IntentStateUpdateResult(BaseModel):
    action: str
    sessionId: str
    intentMode: str = "preference"
    applied: bool = False
    messageCode: str = ""
    message: str = ""
    merged: dict[str, Any] = Field(default_factory=dict)
    candidateFilters: dict[str, Any] | None = None
    filteredTotal: int | None = None
    baseTotal: int | None = None
    recommendationRefresh: dict[str, Any] | None = None


class ExploreFollowupResult(BaseModel):
    actionType: str
    sessionId: str
    intentMode: str = "preference"
    handled: bool = False
    messageCode: str = ""
    message: str = ""
    candidateFilters: dict[str, Any] | None = None
    filteredTotal: int | None = None
    baseTotal: int | None = None
    analysisPayload: dict[str, Any] | None = None
    delegatedText: str = ""


def serialize_intent_analysis_payload(payload: IntentAnalysisPayload) -> str:
    return payload.model_dump_json(ensure_ascii=False)


def parse_intent_analysis_payload(payload_text: str) -> IntentAnalysisPayload:
    return IntentAnalysisPayload.model_validate_json(payload_text)


def serialize_intent_state_update_result(result: IntentStateUpdateResult) -> str:
    if not result.message:
        result.message = render_intent_state_update(result)
    return result.model_dump_json(ensure_ascii=False)


def parse_intent_state_update_result(result_text: str) -> IntentStateUpdateResult:
    return IntentStateUpdateResult.model_validate_json(result_text)


def serialize_explore_followup_result(result: ExploreFollowupResult) -> str:
    if not result.message:
        result.message = render_explore_followup_result(result)
    return result.model_dump_json(ensure_ascii=False)


def parse_explore_followup_result(result_text: str) -> ExploreFollowupResult:
    return ExploreFollowupResult.model_validate_json(result_text)


def _unique_text_values(values: Any) -> list[str]:
    raw_values = values if isinstance(values, list) else [values] if values else []
    result: list[str] = []
    seen: set[str] = set()
    for value in raw_values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        result.append(text)
        seen.add(text)
    return result


def _collect_major_summary_values(major_intents: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for key in keys:
        for value in _unique_text_values(major_intents.get(key)):
            if value in seen:
                continue
            result.append(value)
            seen.add(value)
    return result


def _format_confirmed_intent_summary(merged: dict[str, Any]) -> list[str]:
    summary: list[str] = []
    major_intents = merged.get("major_intents") or {}
    if isinstance(major_intents, dict):
        positive = _collect_major_summary_values(major_intents, ("level3", "level2", "level1"))
        negative = _collect_major_summary_values(
            major_intents,
            ("negative_level3", "negative_level2", "negative_level1"),
        )
        if positive:
            summary.append(f"偏好专业：{'、'.join(positive)}")
        if negative:
            summary.append(f"排除专业：{'、'.join(negative)}")

    school_intents = merged.get("school_intents") or {}
    if isinstance(school_intents, dict):
        preferred_schools = _unique_text_values(school_intents.get("colleges"))
        negative_schools = _unique_text_values(school_intents.get("negative_colleges"))
        if preferred_schools:
            summary.append(f"偏好院校：{'、'.join(preferred_schools)}")
        if negative_schools:
            summary.append(f"排除院校：{'、'.join(negative_schools)}")

    city_intents = merged.get("city_intents") or {}
    if isinstance(city_intents, dict):
        preferred_regions = _unique_text_values(city_intents.get("province")) + _unique_text_values(city_intents.get("city"))
        negative_regions = _unique_text_values(city_intents.get("negative_province")) + _unique_text_values(city_intents.get("negative_city"))
        if preferred_regions:
            summary.append(f"偏好地域：{'、'.join(dict.fromkeys(preferred_regions))}")
        if negative_regions:
            summary.append(f"排除地域：{'、'.join(dict.fromkeys(negative_regions))}")

    career_intents = merged.get("career_intents") or {}
    if isinstance(career_intents, dict):
        preferred_careers = _unique_text_values(to_career_labels(career_intents.get("positive")))
        negative_careers = _unique_text_values(to_career_labels(career_intents.get("negative")))
        if preferred_careers:
            summary.append(f"偏好发展方向：{'、'.join(preferred_careers)}")
        if negative_careers:
            summary.append(f"排除发展方向：{'、'.join(negative_careers)}")
    return summary


def _format_intent_state_update_with_summary(
    *,
    base: str,
    result: IntentStateUpdateResult,
    next_step: str,
    usage_text: str | None = None,
) -> str:
    lines = [base]
    summary = _format_confirmed_intent_summary(result.merged)
    if summary:
        lines.append(f"- 本次确认内容：{'；'.join(summary)}。")
    if usage_text:
        lines.append(f"- 后续使用：{usage_text}")
    lines.append(f"- 下一步：{next_step}")
    return "\n".join(lines)


def render_intent_state_update(result: IntentStateUpdateResult) -> str:
    if result.message:
        return result.message

    code = result.messageCode
    if code == "constraint_applied":
        base = "已确认，这次内容会作为后续报考参考。"
        if result.baseTotal is not None and result.filteredTotal is not None:
            usage_text = f"按这条要求看，候选大约还有 {result.filteredTotal} 个，整体候选大约是 {result.baseTotal} 个。"
        elif result.filteredTotal is not None:
            usage_text = f"按这条要求看，候选大约还有 {result.filteredTotal} 个。"
        else:
            usage_text = "后续查看候选和方案时会作为参考，不会直接改动当前方案顺序。"
        return _format_intent_state_update_with_summary(
            base=base,
            result=result,
            usage_text=usage_text,
            next_step="可以继续查看候选机会，或者让我检查当前方案里有没有不符合这条要求的地方。",
        )
    if code == "preference_applied":
        return _format_intent_state_update_with_summary(
            base="已确认，这个偏好会作为后续报考参考。",
            result=result,
            usage_text="后续查看候选和方案时会作为参考，不会直接改动当前方案顺序。",
            next_step="可以继续让我看看现在这份方案哪些地方比较贴近你的想法、哪些地方还可以再优化。",
        )
    if code == "reject_success":
        return "已取消本次意向调整。你可以重新说明想保留、排除或更偏好的方向，或者继续其他咨询。"
    if code == "no_pending":
        return "当前没有待确认的意向调整。"
    if code == "confirm_required":
        return "这一步我先停在待确认状态。请点击确认卡片采纳后，我再正式生效。"
    if code == "empty_update":
        return "没有可执行的意向更新内容。"
    if code == "apply_failed":
        return "应用意向调整时发生错误，请稍后重试。"
    if code == "reject_failed":
        return "取消意向调整时发生错误，请稍后重试。"
    if code == "select_empty":
        return "你这次没有采纳任何意向调整。"
    if code == "message_not_clickable":
        return "该消息不可再点击。"
    if code == "message_already_clicked":
        return "该方案已经被处理过，请问还有其他需求吗？"
    if code == "interest_action_failed":
        return "处理这一步时发生错误，请稍后重试。"
    return ""


def render_explore_followup_result(result: ExploreFollowupResult) -> str:
    if result.message:
        return result.message
    if result.delegatedText:
        return result.delegatedText

    code = result.messageCode
    if code == "cache_missing":
        return "这条想法的上下文已经失效了，你可以重新说一下想看的方向。"
    if code == "candidate_not_filterable":
        return "这个方向更适合作为后续分析和推荐的参考，暂时没法直接在候选区筛出一批固定结果。你要是愿意，我可以继续结合现在这份方案帮你分析。"
    if code == "candidate_query":
        if result.baseTotal is not None and result.filteredTotal is not None:
            return f"我先按这个方向帮你圈了一下候选结果，现在大约能看到 {result.filteredTotal} 个结果，整体候选大约是 {result.baseTotal} 个。你可以直接去候选区继续看。"
        if result.filteredTotal is not None:
            return f"我先按这个方向帮你圈了一下候选结果，现在大约能看到 {result.filteredTotal} 个结果。你可以直接去候选区继续看。"
        return "我先按这个方向帮你圈了一下候选结果，你可以直接去候选区继续看。"
    if code == "unsupported_action":
        return "暂不支持这个兴趣分析动作。"
    if code == "interest_action_failed":
        return "处理这一步时发生错误，请稍后重试。"
    return ""


def format_text_sections(*sections: tuple[str, list[str] | None] | tuple[str, str | None]) -> str:
    blocks: list[str] = []
    for title, content in sections:
        if not content:
            continue
        display_title = f"**{title}**"
        if isinstance(content, list):
            lines = [line for line in content if line]
            if not lines:
                continue
            blocks.append(f"{display_title}\n" + "\n".join(f"- {line}" for line in lines))
        else:
            text = str(content).strip()
            if not text:
                continue
            blocks.append(f"{display_title}\n{text}")
    return "\n\n".join(blocks)


def _has_specific_impact_text(impact_text: str | None) -> bool:
    text = str(impact_text or "").strip()
    if not text:
        return False
    generic_markers = (
        "我先帮你看看",
        "我也会顺手看看",
        "下一步更适合先看看",
        "下一步更适合继续看看",
        "这个要求和你现在的方案是否有冲突",
        "现在这份方案里有没有贴近这个方向",
        "方案外还有没有更贴近这个方向的机会",
        "继续看看这份方案和你的想法有多匹配",
        "直接让我给你调整建议",
    )
    meaningful_lines = []
    for line in text.splitlines():
        stripped = line.strip().lstrip("-").strip()
        if not stripped:
            continue
        if stripped.startswith("**") and stripped.endswith("**"):
            continue
        if any(marker in stripped for marker in generic_markers):
            continue
        meaningful_lines.append(stripped)
    return bool(meaningful_lines)


def _strip_duplicated_interest_impact_heading(impact_text: str | None) -> str:
    text = str(impact_text or "").strip()
    if not text:
        return ""
    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and lines[0].strip().startswith("**") and lines[0].strip().endswith("**"):
        lines.pop(0)
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and lines[0].strip() == "**初步判断**":
        lines.pop(0)
    cleaned: list[str] = []
    skip_next_blank = False
    for line in lines:
        stripped = line.strip()
        if stripped in {"**先帮你看一眼**", "**初步判断**"}:
            skip_next_blank = True
            continue
        if skip_next_blank and not stripped:
            continue
        skip_next_blank = False
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def _collect_focus_terms_from_items(
    items: list[dict[str, Any]] | None,
    existing_items: list[dict[str, Any]] | None = None,
) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    def add_value(value: Any) -> None:
        if isinstance(value, dict):
            for nested in value.values():
                add_value(nested)
            return
        if isinstance(value, list):
            for nested in value:
                add_value(nested)
            return
        text = str(value or "").strip()
        if text and text not in seen:
            result.append(text)
            seen.add(text)

    for item in (items or []) + (existing_items or []):
        value = item.get("value")
        if isinstance(value, dict):
            add_value(value)
    return result


def _analysis_section_items(
    impact_analysis: dict[str, Any] | None,
    keys: tuple[str, ...],
    *,
    focus_terms: list[str] | None = None,
) -> list[str]:
    if not isinstance(impact_analysis, dict):
        return []
    result: list[str] = []
    seen: set[str] = set()
    terms = [term for term in (focus_terms or []) if term]
    for key in keys:
        values = impact_analysis.get(key)
        raw_items = values if isinstance(values, list) else [values] if values else []
        for item in raw_items:
            text = str(item or "").strip().lstrip("-").strip()
            if not text or text in seen:
                continue
            if terms and not any(term in text for term in terms) and not re.search(r"\d+\s*个", text):
                continue
            result.append(text)
            seen.add(text)
    return result


def _filter_interest_impact_text(impact_text: str | None, focus_terms: list[str]) -> str:
    text = str(impact_text or "").strip()
    if not text:
        return ""
    terms = [term for term in focus_terms if term]
    lines: list[str] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        stripped = raw_line.strip().lstrip("-").strip()
        if not stripped:
            continue
        if stripped.startswith("**") and stripped.endswith("**"):
            continue
        if stripped.endswith(("：", ":")):
            continue
        if terms and not any(term in stripped for term in terms) and not re.search(r"\d+\s*个", stripped):
            continue
        if stripped in seen:
            continue
        lines.append(f"- {stripped}")
        seen.add(stripped)
    return "\n".join(lines)


def _fallback_intent_impact_text(intent_mode: str) -> str:
    if intent_mode == "constraint":
        return "这些内容只有点击采纳后才会生效。点击采纳前不会写入偏好，也不会改动当前方案；点击采纳后，我再用它们收紧候选和检查方案。"
    return "这些内容只有点击采纳后才会生效。点击采纳前不会写入后续参考；点击采纳后，我再把它们作为后续看方案和给建议时的参考。"


def _format_values(values: Any) -> str:
    if isinstance(values, list):
        return "、".join(str(value) for value in values if str(value).strip())
    if values is None:
        return ""
    return str(values).strip()


def _sanitize_user_facing_intent_text(text: str) -> str:
    replacements = {
        "当前已有参考": "当前已记录的报考参考",
        "专业（level1）": "专业门类",
        "专业（level2）": "专业类",
        "专业（level3）": "具体专业",
        "排除专业（level1）": "排除专业门类",
        "排除专业（level2）": "排除专业类",
        "排除专业（level3）": "排除具体专业",
        "level1": "专业门类",
        "level2": "专业类",
        "level3": "具体专业",
    }
    sanitized = str(text or "").strip()
    for source, target in replacements.items():
        sanitized = sanitized.replace(source, target)
    return sanitized


def _render_major_intent_item(major_intents: dict[str, Any]) -> str | None:
    labels = {
        "level1": "偏好专业门类",
        "level2": "偏好专业类",
        "level3": "偏好专业",
        "negative_level1": "排除专业门类",
        "negative_level2": "排除专业类",
        "negative_level3": "排除专业",
    }
    for key, label in labels.items():
        values = _format_values(major_intents.get(key))
        if values:
            return f"{label}：{values}"
    return None


def _render_intent_preview_item(item: dict[str, Any]) -> str:
    value = item.get("value")
    if isinstance(value, dict):
        major_text = _render_major_intent_item(value.get("major_intents") or {})
        if major_text:
            return major_text
        school_intents = value.get("school_intents") or {}
        if school := _format_values(school_intents.get("colleges")):
            return f"偏好院校：{school}"
        if school := _format_values(school_intents.get("negative_colleges")):
            return f"排除院校：{school}"
        city_intents = value.get("city_intents") or {}
        city_labels = {
            "province": "偏好省份",
            "city": "偏好城市",
            "negative_province": "排除省份",
            "negative_city": "排除城市",
        }
        for key, label in city_labels.items():
            if city := _format_values(city_intents.get(key)):
                return f"{label}：{city}"
        career_intents = value.get("career_intents") or {}
        if career := _format_values(career_intents.get("positive")):
            return f"偏好发展方向：{career}"
        if career := _format_values(career_intents.get("negative")):
            return f"排除发展方向：{career}"
    return _sanitize_user_facing_intent_text(str(item.get("content") or "").strip())


def _collect_major_intent_values(items: list[dict[str, Any]] | None) -> dict[str, list[str]]:
    collected = {
        "level1": [],
        "level2": [],
        "level3": [],
        "negative_level1": [],
        "negative_level2": [],
        "negative_level3": [],
    }
    for item in items or []:
        value = item.get("value")
        if not isinstance(value, dict):
            continue
        major_intents = value.get("major_intents")
        if not isinstance(major_intents, dict):
            continue
        for key in collected:
            raw_values = major_intents.get(key)
            values = raw_values if isinstance(raw_values, list) else [raw_values] if raw_values else []
            for value_item in values:
                text = str(value_item or "").strip()
                if text and text not in collected[key]:
                    collected[key].append(text)
    return collected


def _collect_region_intent_values(items: list[dict[str, Any]] | None) -> dict[str, list[str]]:
    collected = {
        "province": [],
        "city": [],
        "negative_province": [],
        "negative_city": [],
    }
    for item in items or []:
        value = item.get("value")
        if not isinstance(value, dict):
            continue
        city_intents = value.get("city_intents")
        if not isinstance(city_intents, dict):
            continue
        for key in collected:
            raw_values = city_intents.get(key)
            values = raw_values if isinstance(raw_values, list) else [raw_values] if raw_values else []
            for value_item in values:
                text = str(value_item or "").strip()
                if text and text not in collected[key]:
                    collected[key].append(text)
    return collected


def _major_boundary_notes(items: list[dict[str, Any]] | None) -> list[str]:
    major_values = _collect_major_intent_values(items)
    return build_major_relation_notes(major_values)


def _merge_major_values(major_values: dict[str, list[str]], keys: tuple[str, ...]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for key in keys:
        for value in major_values.get(key) or []:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            merged.append(text)
            seen.add(text)
    return merged


def _merge_region_values(region_values: dict[str, list[str]], keys: tuple[str, ...]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for key in keys:
        for value in region_values.get(key) or []:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            merged.append(text)
            seen.add(text)
    return merged


def _short_join(values: list[str], limit: int = 4) -> str:
    visible = values[:limit]
    suffix = f"等{len(values)}项" if len(values) > limit else ""
    return "、".join(visible) + suffix


def _interest_stage_title_lines(title: str, items: list[dict[str, Any]] | None) -> list[str]:
    major_values = _collect_major_intent_values(items)
    positive = _merge_major_values(major_values, ("level3", "level2", "level1"))
    negative = _merge_major_values(major_values, ("negative_level3", "negative_level2", "negative_level1"))
    if positive and negative:
        return [
            f"先按这个方向看影响和边界：避开 {_short_join(negative)}，同时把 {_short_join(positive)} 作为可接受方向；这轮只做分析，不会直接写入偏好或改动方案。"
        ]
    if negative:
        return [
            f"先按这个方向看影响和边界：避开 {_short_join(negative)}；这轮只做分析，不会直接写入排除条件或改动方案。"
        ]
    if positive:
        return [
            f"先按这个方向看影响和边界：关注 {_short_join(positive)} 对后续候选和方案承接有什么影响；这轮只做分析，不会直接写入偏好或改动方案。"
        ]
    region_values = _collect_region_intent_values(items)
    positive_regions = _merge_region_values(region_values, ("province", "city"))
    negative_regions = _merge_region_values(region_values, ("negative_province", "negative_city"))
    if positive_regions and negative_regions:
        return [
            f"先按地域取舍看影响和边界：优先关注 {_short_join(positive_regions)}，同时降低 {_short_join(negative_regions)} 的优先级；这轮只做分析，不会直接写入偏好或改动方案。"
        ]
    if negative_regions:
        return [
            f"先按地域取舍看影响和边界：暂不优先考虑 {_short_join(negative_regions)}；这轮只做分析，不会直接写入排除条件或改动方案。"
        ]
    if positive_regions:
        return [
            f"先按地域取舍看影响和边界：优先关注 {_short_join(positive_regions)} 对后续候选和方案承接有什么影响；这轮只做分析，不会直接写入偏好或改动方案。"
        ]
    return [title.replace("我先结合你现在的情况做个初步分析。", "先按这个方向看影响和边界。")]


def _major_interest_impact_lines(items: list[dict[str, Any]] | None) -> list[str]:
    major_values = _collect_major_intent_values(items)
    positive = _merge_major_values(major_values, ("level3", "level2", "level1"))
    negative = _merge_major_values(major_values, ("negative_level3", "negative_level2", "negative_level1"))
    positive_broad = _merge_major_values(major_values, ("level2", "level1"))
    negative_broad = _merge_major_values(major_values, ("negative_level2", "negative_level1"))

    lines: list[str] = []
    if negative:
        lines.append(
            f"排除 {_short_join(negative)} 后，后续查看候选和方案时会优先检查这些方向是否需要避开；如果当前方案里已有相关志愿，需要单独判断是否替换或移除。"
        )
    if positive:
        lines.append(
            f"保留 {_short_join(positive)} 后，可以把它作为补位和优化方案的参考方向，重点看它在冲、稳、保各层有没有足够承接。"
        )
    if positive and negative:
        lines.append(
            "这类组合的实际意义是先明确“不要什么”，再用可接受方向补足候选和方案结构；确认前它只是分析口径，不会改变后续推荐。"
        )
    if negative_broad:
        lines.append(
            f"{_short_join(negative_broad)} 属于较宽的专业范围，真正作为硬性排除前，建议再确认是否要连同相关下级专业一起避开。"
        )
    if positive_broad:
        lines.append(
            f"{_short_join(positive_broad)} 覆盖面相对更宽，后续如果要精细调整，最好再落到具体专业或学校专业组。"
        )
    return lines


def _region_interest_impact_lines(items: list[dict[str, Any]] | None) -> list[str]:
    region_values = _collect_region_intent_values(items)
    positive = _merge_region_values(region_values, ("province", "city"))
    negative = _merge_region_values(region_values, ("negative_province", "negative_city"))
    lines: list[str] = []
    if negative:
        lines.append(
            f"如果后续降低 {_short_join(negative)} 的优先级，优点是更尊重孩子的就读体验和家庭距离顾虑；代价是可选院校和保底空间可能变少。"
        )
        lines.append(
            "如果分数段比较紧，建议不要一刀切，可以先区分省会/核心城市、院校层次和专业匹配度，再决定哪些必须排除、哪些只是靠后考虑。"
        )
    if positive:
        lines.append(
            f"如果后续优先关注 {_short_join(positive)}，可以提升地域接受度，但也要同步看这些地区在冲、稳、保各层是否有足够候选。"
        )
    if positive and negative:
        lines.append(
            "地域偏好适合先做软排序：优先可接受地区，把不太想去的地区靠后；只有孩子明确不能接受时，再作为硬性排除。"
        )
    return lines


def render_intent_analysis_text(
    *,
    title: str,
    impact_text: str,
    analysis_stage: str,
    intent_mode: str,
    items: list[dict[str, Any]] | None = None,
    existing_items: list[dict[str, Any]] | None = None,
    impact_analysis: dict[str, Any] | None = None,
) -> str:
    boundary_notes = _major_boundary_notes(items)
    if analysis_stage != "interest":
        resolved_impact = impact_text if _has_specific_impact_text(impact_text) else _fallback_intent_impact_text(intent_mode)
        if boundary_notes:
            resolved_impact = "\n".join(f"- {note}" for note in boundary_notes) + f"\n{resolved_impact}"
        if intent_mode == "constraint":
            next_steps = [
                "如果理解正确，请点击卡片采纳；如果只想保留或排除其中一部分，也可以直接说明要调整的范围。",
            ]
        else:
            next_steps = [
                "如果理解正确，请点击卡片采纳；如果还想改一下偏好范围，也可以直接补充说明。",
            ]
        return format_text_sections(
            ("点击采纳后生效", [_render_intent_preview_item(item) for item in (items or [])]),
            ("当前已记录的报考参考", [_render_intent_preview_item(item) for item in (existing_items or [])]),
            ("影响说明", resolved_impact),
            ("下一步", next_steps),
        )

    focus_terms = _collect_focus_terms_from_items(items, existing_items)
    structured_impact_items = _analysis_section_items(
        impact_analysis,
        ("currentPlanFit", "currentPlanConflict", "candidateOpportunity"),
        focus_terms=focus_terms,
    )
    resolved_impact = "\n".join(f"- {item}" for item in structured_impact_items) if structured_impact_items else impact_text
    if boundary_notes:
        resolved_impact = "\n".join(f"- {note}" for note in boundary_notes) + (f"\n{resolved_impact}" if resolved_impact else "")
    resolved_impact = _strip_duplicated_interest_impact_heading(resolved_impact)
    resolved_impact = _filter_interest_impact_text(resolved_impact, focus_terms)
    major_impact_lines = _major_interest_impact_lines(items)
    region_impact_lines = _region_interest_impact_lines(items)
    if region_impact_lines and not major_impact_lines:
        resolved_impact = ""
    impact_lines = major_impact_lines + region_impact_lines
    sections: list[tuple[str, list[str] | None] | tuple[str, str | None]] = [
        ("初步判断", _interest_stage_title_lines(title, items)),
        ("影响边界", impact_lines),
        ("当前情况", resolved_impact),
    ]
    if items:
        sections.append(("这次识别到的参考范围", [_render_intent_preview_item(item) for item in items]))
    if existing_items:
        sections.append(("当前已记录的报考参考", [item.get("content", "") for item in existing_items]))

    if items:
        next_steps = [
            "如果要把这些想法作为后续参考，我可以先整理成确认卡片；点击采纳前不会生效。",
        ]
    else:
        next_steps = [
            "如果你想继续深入，我可以顺着这个方向再分析它和当前方案、候选机会的关系。",
        ]
    sections.append(("下一步", next_steps))
    return format_text_sections(*sections)


def render_intent_analysis_payload(payload_text: str) -> str:
    payload = parse_intent_analysis_payload(payload_text)
    if payload.status == "empty":
        return payload.message
    if payload.status == "existing_only":
        if payload.analysisStage == "interest":
            return render_intent_analysis_text(
                title=payload.title,
                impact_text=payload.impactText,
            analysis_stage=payload.analysisStage,
            intent_mode=payload.intentMode,
            existing_items=[item.model_dump() for item in payload.existingItems],
            impact_analysis=payload.impactAnalysis,
        )
        all_existing_text = "这个想法当前已经在报考参考里。本轮不会重复新增；如果你愿意，我可以继续帮你看看现在这份方案和它有多匹配。"
        if payload.existingItems:
            details = "\n".join(f"- {_sanitize_user_facing_intent_text(item.content)}" for item in payload.existingItems)
            all_existing_text += "\n" + details
        return all_existing_text
    return render_intent_analysis_text(
        title=payload.title,
        impact_text=payload.impactText,
        analysis_stage=payload.analysisStage,
        intent_mode=payload.intentMode,
        items=[item.model_dump() for item in payload.items],
        existing_items=[item.model_dump() for item in payload.existingItems],
        impact_analysis=payload.impactAnalysis,
    )
