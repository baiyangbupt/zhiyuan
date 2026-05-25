"""Intent response models and text rendering helpers."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.domain.career_slots import to_career_label


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


def _normalize_text_values(values: Any, *, career_label: bool = False) -> list[str]:
    if values is None:
        return []
    raw_values = values if isinstance(values, list) else [values]
    normalized: list[str] = []
    for value in raw_values:
        if isinstance(value, dict):
            text = value.get("label") or value.get("name") or value.get("value") or value.get("text") or ""
        else:
            text = value
        text = str(text or "").strip()
        if not text:
            continue
        if career_label:
            text = to_career_label(text)
        if text not in normalized:
            normalized.append(text)
    return normalized


def _extend_summary(summary: dict[str, list[str]], key: str, values: Any, *, career_label: bool = False) -> None:
    for value in _normalize_text_values(values, career_label=career_label):
        if value not in summary[key]:
            summary[key].append(value)


def _summarize_confirmed_intents(merged: dict[str, Any]) -> str:
    if not isinstance(merged, dict) or not merged:
        return ""
    summary: dict[str, list[str]] = {
        "偏好方向": [],
        "排除方向": [],
        "偏好院校": [],
        "排除院校": [],
        "偏好地域": [],
        "排除地域": [],
        "发展方向": [],
        "排除发展方向": [],
    }
    major_intents = merged.get("major_intents") if isinstance(merged.get("major_intents"), dict) else {}
    for key in ("level1", "level2", "level3"):
        _extend_summary(summary, "偏好方向", major_intents.get(key))
    for key in ("negative_level1", "negative_level2", "negative_level3"):
        _extend_summary(summary, "排除方向", major_intents.get(key))

    school_intents = merged.get("school_intents") if isinstance(merged.get("school_intents"), dict) else {}
    _extend_summary(summary, "偏好院校", school_intents.get("colleges"))
    _extend_summary(summary, "排除院校", school_intents.get("negative_colleges"))

    city_intents = merged.get("city_intents") if isinstance(merged.get("city_intents"), dict) else {}
    for key in ("province", "city", "area"):
        _extend_summary(summary, "偏好地域", city_intents.get(key))
    for key in ("negative_province", "negative_city", "negative_area"):
        _extend_summary(summary, "排除地域", city_intents.get(key))

    career_intents = merged.get("career_intents") if isinstance(merged.get("career_intents"), dict) else {}
    _extend_summary(summary, "发展方向", career_intents.get("positive"), career_label=True)
    _extend_summary(summary, "排除发展方向", career_intents.get("negative"), career_label=True)

    parts = [
        f"{label}：{'、'.join(values[:5])}{'等' + str(len(values)) + '项' if len(values) > 5 else ''}"
        for label, values in summary.items()
        if values
    ]
    return f"本次确认内容：{'；'.join(parts)}。" if parts else ""


def render_intent_state_update(result: IntentStateUpdateResult) -> str:
    if result.message:
        return result.message

    code = result.messageCode
    confirmed_summary = _summarize_confirmed_intents(result.merged)
    if code == "constraint_applied":
        summary_text = f"{confirmed_summary}" if confirmed_summary else ""
        if result.baseTotal is not None and result.filteredTotal is not None:
            return f"已按你的确认把这条要求记录为后续筛选和方案调整参考。{summary_text}候选展示会按这条要求更新，候选结果现在大约能看到 {result.filteredTotal} 个，整体候选大约是 {result.baseTotal} 个。要是你愿意，我也可以继续帮你看看这份方案里还有没有不符合这条要求的地方。"
        if result.filteredTotal is not None:
            return f"已按你的确认把这条要求记录为后续筛选和方案调整参考。{summary_text}候选展示会按这条要求更新，候选结果现在大约还有 {result.filteredTotal} 个。要是你愿意，我也可以继续帮你看看这份方案里还有没有不符合这条要求的地方。"
        return f"已按你的确认把这条要求记录为后续筛选和方案调整参考。{summary_text}候选展示会按这条要求更新，你现在可以去看候选结果。要是你愿意，我也可以继续帮你看看这份方案里还有没有不符合这条要求的地方。"
    if code == "preference_applied":
        summary_text = f"{confirmed_summary}" if confirmed_summary else ""
        return f"好的，已经按你的确认记下来了，并作为后续筛选和方案调整参考。{summary_text}接下来如果你愿意，我可以继续帮你看看现在这份方案哪些地方比较贴近你的想法、哪些地方还可以再优化。"
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


_GENERIC_IMPACT_LINES = (
    "我先帮你看看，现在这份方案里有没有贴近这个方向的内容，以及还有哪些值得继续关注的机会。",
    "我先帮你看看，这个要求和你现在的方案是否有冲突，以及还有没有合适的可选机会。",
    "我也会顺手看看，方案外还有没有更贴近这个方向的机会。",
    "下一步更适合继续看看这份方案和你的想法有多匹配，或者直接让我给你调整建议。",
    "下一步更适合先看看方案里还有没有不符合这条要求的地方，再决定怎么调。",
)


def _is_generic_impact_line(line: str) -> bool:
    cleaned = str(line or "").strip().lstrip("-").strip()
    return cleaned in _GENERIC_IMPACT_LINES


def _clean_generic_impact_block(text: str) -> str:
    """Remove placeholder intent impact sections with no concrete plan/candidate facts."""
    lines = str(text or "").splitlines()
    if not lines:
        return ""

    cleaned: list[str] = []
    pending_root_heading: str | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith("**") and stripped.endswith("**"):
            section: list[str] = []
            next_index = index + 1
            while next_index < len(lines):
                next_line = lines[next_index]
                next_stripped = next_line.strip()
                if next_stripped.startswith("**") and next_stripped.endswith("**"):
                    break
                section.append(next_line)
                next_index += 1

            concrete = [
                item
                for item in section
                if item.strip() and not _is_generic_impact_line(item)
            ]
            if concrete:
                cleaned.append(line)
                cleaned.extend(concrete)
            elif index == 0:
                pending_root_heading = line
            index = next_index
            continue

        if stripped and not _is_generic_impact_line(line):
            cleaned.append(line)
        elif not stripped and cleaned and cleaned[-1].strip():
            cleaned.append(line)
        index += 1

    while cleaned and not cleaned[0].strip():
        cleaned.pop(0)
    while cleaned and not cleaned[-1].strip():
        cleaned.pop()
    if pending_root_heading and cleaned:
        cleaned.insert(0, "")
        cleaned.insert(0, pending_root_heading)
    return "\n".join(cleaned)


def render_intent_analysis_text(
    *,
    title: str,
    impact_text: str,
    analysis_stage: str,
    intent_mode: str,
    items: list[dict[str, Any]] | None = None,
    existing_items: list[dict[str, Any]] | None = None,
) -> str:
    sections: list[tuple[str, list[str] | None] | tuple[str, str | None]] = [
        ("分析结论", [title]),
    ]
    impact_block = str(impact_text or "").strip()
    impact_block = _clean_generic_impact_block(impact_block)
    leading_blocks: list[str] = []
    if impact_block:
        if impact_block.startswith("**"):
            leading_blocks.append(impact_block)
        else:
            sections.append(("当前判断", impact_block))
    if items:
        sections.append(("这次识别到的可采纳内容", [item.get("content", "") for item in items]))
    if existing_items:
        sections.append(("当前已经在参考的内容", [item.get("content", "") for item in existing_items]))

    if analysis_stage == "interest":
        next_steps = [
            "如果你想继续深入，我可以顺着这个方向再分析它和当前方案、候选机会的关系。",
        ]
    elif intent_mode == "constraint":
        next_steps = [
            "如果你确认要按这个要求执行，直接回复“确认这个要求”或更明确地说要保留/排除哪些内容，我再正式生效。",
        ]
    else:
        next_steps = [
            "如果你确认要把这些记成后续偏好，直接回复“确认这个偏好”或明确说保留哪些内容，我再正式生效。",
        ]
    sections.append(("下一步", next_steps))
    rendered = format_text_sections(*sections)
    if not leading_blocks:
        return rendered
    blocks = rendered.split("\n\n")
    return "\n\n".join([blocks[0], *leading_blocks, *blocks[1:]])


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
            details = "\n".join(f"- {item.content}" for item in payload.existingItems)
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
