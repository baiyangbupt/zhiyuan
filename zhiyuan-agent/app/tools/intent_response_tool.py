"""Intent response models and text rendering helpers."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

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


def render_intent_state_update(result: IntentStateUpdateResult) -> str:
    if result.message:
        return result.message

    code = result.messageCode
    if code == "constraint_applied":
        if result.baseTotal is not None and result.filteredTotal is not None:
            return f"我已经按你的要求把候选结果收紧了，现在大约能看到 {result.filteredTotal} 个结果，整体候选大约是 {result.baseTotal} 个。要是你愿意，我也可以继续帮你看看这份方案里还有没有不符合这条要求的地方。"
        if result.filteredTotal is not None:
            return f"我已经按你的要求把候选结果收紧了，现在大约还有 {result.filteredTotal} 个结果。要是你愿意，我也可以继续帮你看看这份方案里还有没有不符合这条要求的地方。"
        return "我已经按你的要求把候选结果收紧了，你现在可以直接去看筛选后的结果。要是你愿意，我也可以继续帮你看看这份方案里还有没有不符合这条要求的地方。"
    if code == "preference_applied":
        return "好的，我已经按你的确认记下来了，后续会按这个方向作为报考参考。接下来如果你愿意，我可以继续帮你看看现在这份方案哪些地方比较贴近你的想法、哪些地方还可以再优化。"
    if code == "reject_success":
        return "已取消本次意向调整。你可以重新说明想保留、排除或更偏好的方向，或者继续其他咨询。"
    if code == "no_pending":
        return "当前没有待确认的意向调整。"
    if code == "confirm_required":
        return "这一步我先停在待确认状态。你明确回复“确认”或“就按这个来”后，我再正式生效。"
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


def _fallback_intent_impact_text(intent_mode: str) -> str:
    if intent_mode == "constraint":
        return "这些内容现在还只是待确认。确认前不会写入偏好，也不会改动当前方案；你确认后，我再用它们收紧候选和检查方案。"
    return "这些内容现在还只是待确认。确认前不会写入后续参考；你确认后，我再把它们作为后续看方案和给建议时的参考。"


def _format_values(values: Any) -> str:
    if isinstance(values, list):
        return "、".join(str(value) for value in values if str(value).strip())
    if values is None:
        return ""
    return str(values).strip()


def _sanitize_user_facing_intent_text(text: str) -> str:
    replacements = {
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


def _major_boundary_notes(items: list[dict[str, Any]] | None) -> list[str]:
    major_values = _collect_major_intent_values(items)
    return build_major_relation_notes(major_values)


def render_intent_analysis_text(
    *,
    title: str,
    impact_text: str,
    analysis_stage: str,
    intent_mode: str,
    items: list[dict[str, Any]] | None = None,
    existing_items: list[dict[str, Any]] | None = None,
) -> str:
    if analysis_stage != "interest":
        resolved_impact = impact_text if _has_specific_impact_text(impact_text) else _fallback_intent_impact_text(intent_mode)
        boundary_notes = _major_boundary_notes(items)
        if boundary_notes:
            resolved_impact = "\n".join(f"- {note}" for note in boundary_notes) + f"\n{resolved_impact}"
        if intent_mode == "constraint":
            next_steps = [
                "如果理解正确，直接回复“确认”；如果只想保留或排除其中一部分，也可以直接说明要调整的范围。",
            ]
        else:
            next_steps = [
                "如果理解正确，直接回复“确认”；如果还想改一下偏好范围，也可以直接补充说明。",
            ]
        return format_text_sections(
            ("待确认内容", [_render_intent_preview_item(item) for item in (items or [])]),
            ("已经在参考的内容", [_render_intent_preview_item(item) for item in (existing_items or [])]),
            ("影响说明", resolved_impact),
            ("下一步", next_steps),
        )

    sections: list[tuple[str, list[str] | None] | tuple[str, str | None]] = [
        ("初步判断", [title]),
        ("当前情况", impact_text),
    ]
    if items:
        sections.append(("这次识别到的可采纳内容", [item.get("content", "") for item in items]))
    if existing_items:
        sections.append(("当前已经在参考的内容", [item.get("content", "") for item in existing_items]))

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
            )
        all_existing_text = "这个想法我这边已经记下并在参考了。如果你愿意，我可以继续帮你看看现在这份方案和它有多匹配。"
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
    )
