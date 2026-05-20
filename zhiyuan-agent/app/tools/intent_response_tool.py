"""Intent response models and text rendering helpers."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


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
        ("当前判断", impact_text),
    ]
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
