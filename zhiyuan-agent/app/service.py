from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart

from app.agent.base_agent import ProgressCallback
from app.agent.chat_agent import ChatAgent
from app.agent.context import (
    PlanningSummary,
    RequestContext,
    ScoreDetail,
    resolve_pending_confirmation,
    resolve_pending_plan_payload_text,
)
from app.models.conversation_phase import ConversationPhase, PendingConfirmation
from app.agent.usage_tracker import UsageTracker
from app.config import HistoryConfig
from app.data.history_store import ChatHistoryStore
from app.data.message_utils import pydantic_ai_messages_to_dicts
from app.domain.major_entity_resolver import resolve_major_mentions_from_text
from app.domain.region_entity_resolver import normalize_region_names
from app.domain.school_entity_resolver import resolve_school_entity
from app.domain.career_slots import to_career_labels
from app.llm.client import LLMClient
from app.schemas.user_profile import UserProfile
from app.services.profile_manager import _normalize_batch
from app.schemas.ws import WSResponse
from app.sync.state_sync import PlanningStateSync
from app.tools.explore_followup_tool import handle_interest_analysis_action_result
from app.tools.plan_execution_tool import (
    clear_recent_plan_execution_result,
    consume_recent_plan_execution_result,
    execute_plan_action,
)
from app.tools.candidate_filter_extraction_tool import extract_candidate_query_filters_async
from app.tools.plan_orchestration_tool import plan_next_action
from app.tools.plan_semantic_action_tool import (
    classify_composite_goal_action,
    classify_pending_confirmation_action,
    classify_plan_semantic_action,
    classify_plan_recovery_action,
    select_fix_proposal_candidate,
)
from app.tools.planning_workflow_tool import _format_fix_proposal_apply_result
from app.tools.planning_workflow_tool import _fix_proposal_facts
from app.tools.plan_orchestration_models import (
    CompositePlanProposal,
    PlanGoal,
    normalize_plan_action_payload,
)
from app.tools.plan_goal_resolution import scope_entity_type, scope_value_list
from app.tools.intent_state_tool import (
    ANALYSIS_STAGE_CONFIRMED,
    apply_selected_intents as _apply_selected_intents,
    analyze_volunteer_intent_change,
    merge_selected_values,
    _normalize_constraint_type_for_payload,
    _remove_positive_major_targets_excluded_by_negative_scope,
)
from app.tools.intent_response_tool import (
    parse_intent_analysis_payload,
    parse_explore_followup_result,
    parse_intent_state_update_result,
    render_explore_followup_result,
    render_intent_state_update,
)
from app.tools.intent_relation_tool import compact_relation_impact_lines
from app.util.internal_client import (
    apply_planning_fix_proposal,
    generate_planning_fix_proposals,
    generate_user_goal_planning_fix_proposals,
    get_message_by_id,
    get_pending_confirmation,
    get_planning_state,
    get_planning_workspace_state,
    get_user_init_profile,
    get_user_score_detail,
    save_intent_change_cache,
    save_pending_confirmation,
    update_session_tuition_range,
    update_message,
)
from app.util.structured_log import log_event

logger = logging.getLogger(__name__)

_PLAN_STYLE_SEVERE_MARKERS = (
    "你必须决定",
    "你现在必须决定",
    "必须做出选择",
    "必须做一个选择",
    "必须选一个",
    "没有第三个选项",
    "我无法继续回应",
    "我不再重复解释",
    "我不再回应",
    "最后一次说明",
    "必须停止这个循环",
    "停止这个循环",
    "完全没有意义",
    "当前这版财会类方案就是最优解",
    "当前这版财会类方案保留",
    "我现在直接帮你重新生成",
    "补偿预览",
    "不要再反复查看",
    "选哪个",
    "选 A/B/C",
    "选 A、B 或 C",
    "选 A、B、C",
)
_PLAN_STYLE_DANGLING_EXACT_LINES = {"你。", "只有。", "请。"}
_PLAN_STYLE_GUARD_PROMPT_KEYWORDS = (
    "方案",
    "志愿",
    "候选",
    "审查",
    "风险",
    "重排",
    "排序",
    "怎么调",
    "优化",
    "补偿",
    "补几个",
    "补齐",
    "补满",
    "还差",
    "怎么补",
    "更稳",
    "不合理",
    "稳不稳",
    "删掉",
    "删除",
    "去掉",
    "加进去",
    "加入",
    "往前挪",
    "往后挪",
    "换成",
)
_READONLY_USER_PROMPT_MARKERS = (
    "先别动",
    "先不要动",
    "不要动方案",
    "别动方案",
    "先不要改方案",
    "不要改方案",
    "先查一下不要改",
    "先看看不要改",
    "只分析",
    "先只分析",
    "只看",
    "只查",
    "别直接加",
    "不要直接加",
    "先别加",
    "先不要加",
    "别加入",
    "不要加入",
    "别加进",
    "不要加进",
    "先别记",
    "先不要记",
    "不要记偏好",
    "别记偏好",
    "不要记录",
    "别记录",
)
_PLAN_ACTION_NEGATIVE_ACK_MARKERS = (
    "上面没有要做",
    "上面没有要处理",
    "上面没有要替换",
    "没有要做的替换",
    "没有要处理的替换",
    "不用替换",
    "不要替换",
    "先不替换",
    "不用处理",
    "不要处理",
    "先不处理",
    "不执行",
    "先不执行",
)
_READONLY_MUTATION_GUARD_REPLY = (
    "我按“先看、先查、不直接改”的方式处理了这轮请求，当前不会加入、删除、移动或重排方案。"
    "如果你想把某个候选真正加入方案，可以再明确说“加入方案”或指定要调整的位置，我会先给出可确认的调整预览。"
)
_READONLY_ANALYSIS_NO_PLAN_PREVIEW_REPLY = (
    "这轮先按分析处理，不会改动当前方案。"
    "如果后面需要调整方案，我会先给出调整预览；确认前不会执行。"
)
_UNBACKED_CONFIRM_SENTENCE_RE = re.compile(r"确认要我.*执行")
_UNBACKED_PLAN_CONFIRMATION_REPLY = (
    "这轮还没有生成可执行的调整内容，所以不会改动当前方案。"
    "如果你要继续调整，请再发一次具体要求，我会重新定位影响范围并列出调整预览；"
    "只有你点“确认执行”或直接确认当前有效预览后才会执行。"
)
_ROUTE_OBSERVABILITY_MODEL_NAME = "route-observability"
_SEMANTIC_PLAN_ACTION_CONFIDENCE_THRESHOLD = 0.8
_SEMANTIC_PENDING_CONFIRMATION_CONFIDENCE_THRESHOLD = 0.85
_INTENT_PREVIEW_TOOL_NAMES = {
    "analyze_volunteer_intent_change",
    "preview_current_intent_confirmation",
    "preview_current_major_intent_confirmation",
    "preview_current_school_intent_confirmation",
    "preview_current_region_intent_confirmation",
    "preview_current_career_intent_confirmation",
}
_INTENT_INTEREST_ANALYSIS_TOOL_NAMES = {
    "analyze_current_interest",
    "analyze_current_interest_profile",
    "analyze_current_school_interest",
    "analyze_current_major_interest",
    "analyze_current_region_interest",
    "analyze_current_career_direction",
}
_USER_REPLY_ENGLISH_WORD_REPLACEMENTS = (
    (re.compile(r"\s*\bmostly\b\s*", re.IGNORECASE), "基本上"),
    (re.compile(r"\s*\bincreasingly\b\s*", re.IGNORECASE), "越来越"),
    (re.compile(r"\s*\bbaseline\b\s*", re.IGNORECASE), "基准"),
)

_PLAN_ACTION_REPLY_SYNTHESIS_INSTRUCTIONS = """\
你负责把已经执行完成的志愿方案工具结果，整理成用户能看懂的一段中文回复。

约束：
- 只基于输入里的结构化事实回答，不新增数字、学校、专业、风险结论。
- 不要说“工具、系统、action_family、payload、blocked、preview_only、cannot_satisfy、候选池、自动修复、自动处理、自动补齐、自动应用、系统阻塞、预览验证未通过、预览参考状态、被卡住”。
- 不要说“系统给了/系统能执行/系统没法执行/暂时动不了/卡在哪/我立刻处理/给我明确态度我就能处理”。
- 统一用“你”，不要用“您”。
- 不要照抄 summary/state_summary；它们只是事实摘要。
- 如果已有可确认的调整预览，说明“我已把可执行的处理内容列出来，确认前不会改方案”，并点出核心处理内容。
- 如果某些建议暂时不能直接处理，用用户能理解的原因说清楚，例如“没有足够相近且风险更低的可替换志愿”“需要你先决定是否接受降层次或换专业范围”。
- 没有当前轮可确认的调整预览时，不要让用户直接“确认就执行”；应表达为“我可以先列出调整预览，确认前不会改方案”。
- 回复可以结构化，但要简洁，优先用 2-4 个短要点；不要堆叠多层标题。
"""

_FIX_PROPOSAL_STRATEGY_TEXT = {
    "replace_risk_items": "替换风险项",
    "remove_risk_items": "移出风险项",
    "fill_missing_count": "补足数量",
    "sort_by_probability": "按录取率重排",
    "rebalance_tier_ratio": "调整冲稳保结构",
    "fill_probability_gap": "补梯度断层",
    "add_safety_items": "补安全垫",
    "adjust_major_group_inner_safety": "补兜底专业",
}

_FIX_PROPOSAL_STATUS_TEXT = {
    "ready": "可以先列出调整预览，确认前不会改方案",
    "preview_only": "只能先作为处理方向参考，需要你决定取舍范围",
    "blocked": "需要你先取舍或放宽条件，暂时不适合直接改方案",
    "info": "仅供参考",
}
_PROFILE_CHANGE_REPLAN_REPLY_FOCUS = "profile_change_replan"

_REVIEW_REPLY_QUALITY_MARKERS = (
    "需要你先决定取舍的方向：",
    "建议你先查看具体影响，或调整筛选范围后再试：",
    "当前候选志愿里，目标冲稳保区间候选不足；",
    "当前候选志愿里，断层中间录取率候选不足；",
    "可以先出调整预览给你看：",
    "需要你先决定取舍或放宽条件：",
    "候选供给",
    "系统预估",
    "系统不会",
    "给个明确态度",
    "可以立即处理",
)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _score_like_values_for_reply(text: str | None) -> list[int]:
    values: list[int] = []
    for match in re.finditer(r"(?<!\d)(\d{3})(?!\d)", str(text or "")):
        try:
            value = int(match.group(1))
        except ValueError:
            continue
        if 100 <= value <= 750 and value not in values:
            values.append(value)
    return values


def _profile_change_replan_has_explicit_change_value(text: str | None) -> bool:
    compact = re.sub(r"\s+", "", str(text or "").strip())
    if not compact:
        return False
    if _score_like_values_for_reply(compact):
        return True
    if re.search(r"\d{4,7}(?:位|名|位次|排名)", compact):
        return True
    if any(marker in compact for marker in ("选科改成", "改选科", "换选科", "省份改成", "批次改成", "改成专科", "改成本科")):
        return True
    return False


def _reply_focus_set(value: Any) -> set[str]:
    if isinstance(value, dict):
        values: list[Any] = []
        raw_focus = value.get("reply_focus")
        if isinstance(raw_focus, list):
            values.extend(raw_focus)
        facts = value.get("facts") if isinstance(value.get("facts"), dict) else {}
        requested_focus = facts.get("requested_reply_focus") if isinstance(facts, dict) else None
        if isinstance(requested_focus, list):
            values.extend(requested_focus)
        return {str(item or "").strip() for item in values if str(item or "").strip()}
    values = getattr(value, "replyFocus", None)
    if isinstance(values, list):
        return {str(item or "").strip() for item in values if str(item or "").strip()}
    return set()


def _requests_profile_change_replan(value: Any) -> bool:
    return _PROFILE_CHANGE_REPLAN_REPLY_FOCUS in _reply_focus_set(value)


def _semantic_current_plan_analysis_allowed(value: Any) -> bool:
    """Whether semantic quick route may answer analysis without review context.

    Generic questions such as "这版值不值得/偏专业还是学校/省外是不是多"
    need richer plan reading by the full agent.  The semantic route should only
    take first-turn analysis when the classifier explicitly marks a bounded
    shortage/unavailable-guidance scenario.
    """

    return bool(_reply_focus_set(value) & {"shortage_boundary", "unavailable_guidance"})


def _build_profile_change_replan_reply(
    user_prompt: str | None,
    *,
    request_context: RequestContext | None = None,
) -> str:
    score_values = _score_like_values_for_reply(user_prompt)
    score_text = f"{score_values[0]} 分" if score_values else "新的成绩信息"
    current_score = None
    if request_context is not None:
        score_detail = getattr(request_context, "score_detail", None)
        with contextlib.suppress(TypeError, ValueError):
            parsed = int(getattr(score_detail, "total_score", 0) or 0)
            if parsed > 0:
                current_score = parsed
    current_line = f"当前记录的是 {current_score} 分；" if current_score and score_values and current_score != score_values[0] else ""
    return _sanitize_reply_for_user(_normalize_user_facing_terms(
        "\n".join([
            f"可以按 {score_text} 重新规划，但这属于基础成绩信息变化，不能直接当作普通方案调整来改。",
            "",
            f"- {current_line}如果要采用这个新成绩，需要先确认更新分数，最好同时确认位次、批次和选科是否也有变化。",
            "- 更新后应重新计算可选志愿，再生成新的方案或调整预览；当前方案仍按原来的信息保留。",
            "- 确认前我不会改当前方案。你确认按这个新成绩重新规划后，我再继续重算候选和方案。",
        ])
    ))


def _compact_fix_proposal_for_reply_synthesis(proposal: dict[str, Any]) -> dict[str, Any]:
    def clean_text(value: Any) -> str:
        return _normalize_user_facing_terms(_normalize_fix_proposal_user_text(str(value or "").strip()))

    status = str(proposal.get("status") or "").strip()
    strategy = str(proposal.get("strategy") or "").strip()
    action_summaries = [
        clean_text(item)
        for item in (proposal.get("action_summaries") or proposal.get("actionSummaries") or [])
        if clean_text(item)
    ][:4]
    shortages: list[str] = []
    for shortage in proposal.get("candidate_shortages") or proposal.get("candidateShortages") or []:
        if not isinstance(shortage, dict):
            continue
        message = str(shortage.get("message") or "").strip()
        if message:
            shortages.append(clean_text(message))
    warnings = [
        clean_text(item)
        for item in (proposal.get("warnings") or [])
        if clean_text(item)
    ][:3]
    reason_parts = [
        str(proposal.get("blocking_reason") or proposal.get("blockingReason") or "").strip(),
        *shortages[:3],
        *warnings,
    ]
    return {
        "title": clean_text(proposal.get("title")),
        "availability": _FIX_PROPOSAL_STATUS_TEXT.get(status, "需要结合审查结果进一步判断"),
        "strategy": _FIX_PROPOSAL_STRATEGY_TEXT.get(strategy, strategy),
        "summary": clean_text(proposal.get("summary")),
        "impact": clean_text(proposal.get("impact")),
        "action_summaries": action_summaries,
        "change_counts": {
            "remove_volunteers": _as_int(proposal.get("remove_volunteer_count") or proposal.get("removeVolunteerCount")),
            "add_volunteers": _as_int(proposal.get("add_volunteer_count") or proposal.get("addVolunteerCount")),
            "remove_units": _as_int(proposal.get("remove_unit_count") or proposal.get("removeUnitCount")),
            "add_units": _as_int(proposal.get("add_unit_count") or proposal.get("addUnitCount")),
        },
        "reason": [
            clean_text(part)
            for part in reason_parts
            if clean_text(part)
        ][:4],
    }


def _compact_plan_action_result_for_reply_synthesis(result: dict[str, Any]) -> dict[str, Any]:
    facts = result.get("facts") if isinstance(result.get("facts"), dict) else {}
    fix_facts = facts.get("fix_proposals") if isinstance(facts.get("fix_proposals"), dict) else {}
    proposals = [
        _compact_fix_proposal_for_reply_synthesis(proposal)
        for proposal in (fix_facts.get("proposals") or [])[:6]
        if isinstance(proposal, dict)
    ]
    return {
        "action_family": str(result.get("action_family") or "").strip(),
        "result_kind": str(result.get("result_kind") or "").strip(),
        "summary": _normalize_user_facing_terms(_normalize_fix_proposal_user_text(str(result.get("summary") or "").strip())),
        "state_summary": _normalize_user_facing_terms(_normalize_fix_proposal_user_text(str(result.get("state_summary") or "").strip())),
        "reply_focus": result.get("reply_focus") if isinstance(result.get("reply_focus"), list) else [],
        "fix_proposals": {
            "total": _as_int(fix_facts.get("total") or len(proposals)),
            "ready_count": _as_int(fix_facts.get("ready_count")),
            "needs_user_decision_count": _as_int(fix_facts.get("blocked_count")) + _as_int(fix_facts.get("preview_only_count")),
            "proposals": proposals,
        },
    }


async def _synthesize_semantic_plan_action_reply(
    llm_client: LLMClient,
    *,
    user_prompt: str,
    result: dict[str, Any],
    recent_plan_context: dict[str, Any] | None = None,
) -> tuple[str, Any | None]:
    """Use a no-tool model pass to turn plan facts into user-facing prose."""

    synthesis_agent = Agent(
        model=llm_client.model,
        output_type=str,
        instructions=_PLAN_ACTION_REPLY_SYNTHESIS_INSTRUCTIONS,
        tools=[],
        model_settings=llm_client.model_settings,
    )
    prompt_payload = {
        "user_prompt": user_prompt,
        "recent_plan_context": recent_plan_context or {},
        "tool_result_facts": _compact_plan_action_result_for_reply_synthesis(result),
    }
    run_result = await synthesis_agent.run(
        json.dumps(prompt_payload, ensure_ascii=False, default=str),
        model_settings=llm_client.model_settings,
    )
    reply = str(getattr(run_result, "output", "") or "").strip()
    usage = None
    with contextlib.suppress(Exception):
        usage = run_result.usage()
    return _sanitize_reply_for_user(_normalize_user_facing_terms(reply)), usage


def _log_conversation_turn_event(**fields: Any) -> None:
    log_event("conversation_turn_event", **fields)


def _log_pending_confirmation_event(**fields: Any) -> None:
    log_event("pending_confirmation_event", **fields)


def _route_observability_message(turn_event: dict[str, Any] | None) -> ModelResponse | None:
    if not turn_event:
        return None
    try:
        content = json.dumps(
            {
                "type": "routeObservability",
                "event": "conversation_turn_event",
                **turn_event,
            },
            ensure_ascii=False,
        )
    except Exception:
        return None
    return ModelResponse(parts=[TextPart(content=content)], model_name=_ROUTE_OBSERVABILITY_MODEL_NAME)


def _append_route_observability_message(messages: list[Any], turn_event: dict[str, Any] | None) -> list[Any]:
    observability_message = _route_observability_message(turn_event)
    if observability_message is None:
        return messages
    result = list(messages)
    for index in range(len(result) - 1, -1, -1):
        message = result[index]
        if not isinstance(message, ModelResponse) or _is_route_observability_message(message):
            continue
        if any(isinstance(part, TextPart) for part in getattr(message, "parts", []) or []):
            result.insert(index, observability_message)
            return result
    return [*result, observability_message]


def _is_route_observability_message(message: Any) -> bool:
    if not isinstance(message, ModelResponse):
        return False
    if str(getattr(message, "model_name", "") or "") == _ROUTE_OBSERVABILITY_MODEL_NAME:
        return True
    for part in getattr(message, "parts", []) or []:
        if isinstance(part, TextPart):
            try:
                data = json.loads(part.content)
            except Exception:
                continue
            if isinstance(data, dict) and data.get("type") == "routeObservability":
                return True
    return False


def _llm_config_value(llm_client: LLMClient, field_name: str) -> str | None:
    config = getattr(llm_client, "config", None)
    value = getattr(config, field_name, None)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass
class ChatServiceResponseEnvelope:
    """服务层统一回复结构，允许主文本外再携带附加工作台动作。"""

    primary: str | WSResponse
    followups: list[WSResponse] = field(default_factory=list)


@dataclass(slots=True)
class RuntimeHistoryResult:
    """Short-lived history passed to the model; full history remains persisted."""

    model_history: list[Any] | None
    chat_history: list[dict]
    full_len: int = 0
    runtime_len: int = 0
    full_text_chars: int = 0
    runtime_text_chars: int = 0
    dropped_tool_return_count: int = 0
    has_pending: bool = False


def _iter_tool_call_parts(messages: list[Any] | None) -> list[ToolCallPart]:
    parts: list[ToolCallPart] = []
    for message in messages or []:
        if not isinstance(message, ModelResponse):
            continue
        for part in getattr(message, "parts", []) or []:
            if isinstance(part, ToolCallPart):
                parts.append(part)
    return parts


def _iter_tool_return_parts(messages: list[Any] | None) -> list[ToolReturnPart]:
    parts: list[ToolReturnPart] = []
    for message in messages or []:
        if not isinstance(message, ModelRequest):
            continue
        for part in getattr(message, "parts", []) or []:
            if isinstance(part, ToolReturnPart):
                parts.append(part)
    return parts


def _select_current_tool_context_messages(
    new_messages: list[Any] | None,
    all_messages: list[Any] | None,
    runtime_history: RuntimeHistoryView,
) -> list[Any]:
    """Pick the current-turn message slice that still contains tool calls/returns.

    Pydantic direct-tool-return runs may expose only the synthesized direct text
    in ``new_messages`` while the full current turn, including tool call/return
    parts, is only visible in ``all_messages``. Pending-card creation must inspect
    the full tool context, but it must not scan stale history from previous turns.
    """
    current = list(new_messages or [])
    if _iter_tool_return_parts(current):
        return current

    runtime_len = len(runtime_history.model_history or [])
    inferred: list[Any] = []
    if all_messages and len(all_messages) >= runtime_len:
        inferred = list(all_messages[runtime_len:])
    if _iter_tool_return_parts(inferred):
        return inferred
    return current or inferred


def _message_text_chars(messages: list[Any] | None) -> int:
    total = 0
    for message in messages or []:
        for part in getattr(message, "parts", []) or []:
            content = getattr(part, "content", None)
            if isinstance(content, str):
                total += len(content)
                continue
            args = getattr(part, "args", None)
            if isinstance(args, str):
                total += len(args)
            elif isinstance(args, dict):
                try:
                    total += len(json.dumps(args, ensure_ascii=False))
                except Exception:
                    pass
    return total


def _message_has_user_prompt(message: Any) -> bool:
    if not isinstance(message, ModelRequest):
        return False
    return any(isinstance(part, UserPromptPart) for part in getattr(message, "parts", []) or [])


def _count_user_turns(messages: list[Any] | None) -> int:
    return sum(1 for message in messages or [] if _message_has_user_prompt(message))


def _latest_user_prompt_index(messages: list[Any]) -> int | None:
    for index in range(len(messages) - 1, -1, -1):
        if _message_has_user_prompt(messages[index]):
            return index
    return None


def _compact_tool_return_content(content: Any) -> str:
    if not isinstance(content, str):
        return "[工具结果已裁剪：非文本结果]"
    try:
        parsed = json.loads(content)
    except Exception:
        return "[工具结果已裁剪：原结果过长]"
    if not isinstance(parsed, dict):
        return "[工具结果已裁剪：原结果过长]"

    keys = (
        "result_kind",
        "action_family",
        "messageCode",
        "message",
        "summary",
        "preview_summary",
        "userFacingSummary",
        "workspace_refresh_targets",
        "targetView",
        "applied",
        "success",
    )
    compacted = {key: parsed.get(key) for key in keys if parsed.get(key) is not None}
    if not compacted:
        return "[工具结果已裁剪：原结果过长]"
    compacted["_truncated"] = True
    return json.dumps(compacted, ensure_ascii=False)


def _should_compact_runtime_tool_return(part: ToolReturnPart, max_tool_return_chars: int) -> bool:
    if not isinstance(part.content, str):
        return False
    if part.tool_name in _INTENT_PREVIEW_TOOL_NAMES:
        return True
    return max_tool_return_chars > 0 and len(part.content) > max_tool_return_chars


def _compact_runtime_message(message: Any, max_tool_return_chars: int) -> tuple[Any, int]:
    if not isinstance(message, ModelRequest):
        return message, 0

    changed = False
    dropped = 0
    compacted_parts: list[Any] = []
    for part in getattr(message, "parts", []) or []:
        if isinstance(part, ToolReturnPart) and _should_compact_runtime_tool_return(part, max_tool_return_chars):
            compacted_parts.append(
                ToolReturnPart(
                    tool_name=part.tool_name,
                    content=_compact_tool_return_content(part.content),
                    tool_call_id=part.tool_call_id,
                )
            )
            changed = True
            dropped += 1
            continue
        compacted_parts.append(part)

    if not changed:
        return message, 0
    return ModelRequest(parts=compacted_parts), dropped


def build_runtime_history(
    full_history: list[Any] | None,
    *,
    latest_user_content: str,
    has_active_pending: bool | None = None,
    config: HistoryConfig | None = None,
) -> RuntimeHistoryResult:
    """Build the short history used by the live model call.

    The persisted session history stays complete. This function only limits what
    is sent to the model and to text-history consumers in RequestContext.
    """
    history = [
        message
        for message in list(full_history or [])
        if not _is_route_observability_message(message)
    ]
    cfg = config or HistoryConfig()
    max_messages = max(0, int(getattr(cfg, "runtime_max_messages", 24) or 0))
    has_pending = bool(has_active_pending)

    if not history:
        return RuntimeHistoryResult(
            model_history=None,
            chat_history=[{"role": "user", "content": latest_user_content}],
            full_len=0,
            runtime_len=0,
            full_text_chars=0,
            runtime_text_chars=0,
            dropped_tool_return_count=0,
            has_pending=has_pending,
        )

    if max_messages == 0 or len(history) <= max_messages:
        selected = history
    else:
        selected_indices = set(range(len(history) - max_messages, len(history)))
        keep_pending = bool(getattr(cfg, "runtime_keep_pending", True))
        if has_pending and keep_pending:
            current_turn_start = _latest_user_prompt_index(history)
            if current_turn_start is None:
                current_turn_start = 0
            selected_indices.update(range(current_turn_start, len(history)))
        selected = [history[index] for index in sorted(selected_indices)]

    dropped_tool_returns = 0
    compacted_history: list[Any] = []
    max_tool_return_chars = int(getattr(cfg, "runtime_drop_tool_returns_over_chars", 3000) or 0)
    for message in selected:
        compacted, dropped = _compact_runtime_message(message, max_tool_return_chars)
        compacted_history.append(compacted)
        dropped_tool_returns += dropped

    chat_history = pydantic_ai_messages_to_dicts(compacted_history)
    chat_history.append({"role": "user", "content": latest_user_content})

    return RuntimeHistoryResult(
        model_history=compacted_history,
        chat_history=chat_history,
        full_len=len(history),
        runtime_len=len(compacted_history),
        full_text_chars=_message_text_chars(history),
        runtime_text_chars=_message_text_chars(compacted_history),
        dropped_tool_return_count=dropped_tool_returns,
        has_pending=has_pending,
    )


_SUPPORTED_WORKSPACE_ACTION_TARGETS = {"candidate", "ordered", "review"}


def _dedupe_workspace_targets(targets: list[str]) -> list[str]:
    deduped: list[str] = []
    for target in targets:
        value = str(target or "").strip()
        if not value or value not in _SUPPORTED_WORKSPACE_ACTION_TARGETS or value in deduped:
            continue
        deduped.append(value)
    return deduped


_WORKSPACE_ACTION_COPY = {
    "candidate": {
        "title": "查看候选库关联结果",
        "content": "可以查看当前查询相关的候选机会；这只是可见候选视图，不会改小基础候选池。",
        "actionText": "打开候选库",
    },
    "ordered": {
        "title": "查看调整后的排序方案",
        "content": "已刷新排序方案，可以查看本次调整后的志愿列表和位置变化。",
        "actionText": "打开排序方案",
    },
    "review": {
        "title": "查看最新审查结果",
        "content": "已刷新方案审查结果，可以查看风险、提醒和处理建议。",
        "actionText": "打开审查结果",
    },
}


def _build_workspace_action_response(
    session_id: str,
    target: str,
    *,
    refresh: bool = True,
    extra_payload: dict[str, Any] | None = None,
) -> WSResponse:
    target_value = str(target or "").strip()
    if target_value not in _WORKSPACE_ACTION_COPY:
        raise ValueError(f"Unsupported workspace action target: {target_value}")
    copy = _WORKSPACE_ACTION_COPY.get(
        target_value,
        {
            "title": "查看工作台更新",
            "content": "工作台已有更新，可以打开对应区域查看最新结果。",
            "actionText": "查看更新",
        },
    )
    return WSResponse(
        type="planningWorkspaceAction",
        session_id=session_id,
        content=json.dumps(
            {
                "type": "planningWorkspaceAction",
                "targetView": target_value,
                "refresh": refresh,
                **copy,
                **(extra_payload or {}),
            },
            ensure_ascii=False,
        ),
    )


def _build_silent_workspace_refresh_response(
    session_id: str,
    target: str,
    *,
    extra_payload: dict[str, Any] | None = None,
) -> WSResponse:
    payload = {
        "silent": True,
        "preserveView": True,
        **(extra_payload or {}),
    }
    return _build_workspace_action_response(
        session_id,
        target,
        refresh=True,
        extra_payload=payload,
    )


def _extract_extra_data_value(response: dict[str, Any] | None, key: str) -> dict[str, Any] | None:
    data = (response or {}).get("data")
    if not isinstance(data, dict):
        return None
    value = data.get(key)
    if value is None:
        value = data.get("dataValue")
    return value if isinstance(value, dict) else None


async def _load_pending_confirmation_state(session_id: str) -> dict[str, Any] | None:
    try:
        response = await get_pending_confirmation(session_id)
    except Exception:
        logger.warning("Failed to load pending confirmation state: session_id=%s", session_id, exc_info=True)
        return None
    return _extract_extra_data_value(response, "pendingConfirmation")


def _pending_confirmation_from_state(state: dict[str, Any] | None) -> PendingConfirmation | None:
    """Build runtime pending projection from backend pendingConfirmation state."""
    if not isinstance(state, dict):
        return None
    if str(state.get("status") or "").strip() != "active":
        return None
    kind = str(state.get("kind") or "").strip()
    action_family = str(state.get("actionFamily") or "").strip()
    if kind not in {"intent_change", "plan_mutation"} or not action_family:
        return None
    execution_payload = state.get("executionPayload")
    if not isinstance(execution_payload, dict):
        return None
    composite_proposal = state.get("compositeProposal")
    if not isinstance(composite_proposal, dict):
        composite_proposal = {}
    source_backend_version = _as_int(
        state.get("sourceBackendVersion")
        or state.get("source_backend_version")
        or state.get("planningVersion")
        or state.get("planning_version")
    )
    if kind == "plan_mutation":
        if action_family == "apply_fix_proposal":
            payload = dict(execution_payload)
        else:
            plan_payload = execution_payload.get("planPayload")
            if not isinstance(plan_payload, str) or not plan_payload.strip():
                return None
            payload: dict[str, Any] = {}
            try:
                parsed_payload = json.loads(plan_payload)
                if isinstance(parsed_payload, dict):
                    payload = parsed_payload
            except Exception:
                payload = {}
        pending = PendingConfirmation(
            kind="plan_mutation",
            action_family=action_family,
            preview_summary=str(state.get("summary") or ""),
            execution_payload=payload,
            affected_scope=str(state.get("affectedScope") or state.get("affected_scope") or ""),
            source_backend_version=source_backend_version,
            composite_proposal=composite_proposal,
        )
        created_turn = _as_int(state.get("createdTurn") or state.get("created_turn"))
        if created_turn > 0:
            pending = pending.model_copy(update={"created_turn": created_turn})
        return pending

    intent_payload = execution_payload.get("merged")
    if not isinstance(intent_payload, dict) or not intent_payload:
        intent_payload = execution_payload.get("selectedData")
    if not isinstance(intent_payload, dict) or not intent_payload:
        return None
    pending = PendingConfirmation(
        kind="intent_change",
        action_family=action_family,
        preview_summary=str(state.get("summary") or ""),
        execution_payload=execution_payload,
        source_backend_version=source_backend_version,
        composite_proposal=composite_proposal,
    )
    created_turn = _as_int(state.get("createdTurn") or state.get("created_turn"))
    if created_turn > 0:
        pending = pending.model_copy(update={"created_turn": created_turn})
    return pending


async def _save_pending_confirmation_state(session_id: str, state: dict[str, Any]) -> None:
    try:
        await save_pending_confirmation(session_id, state)
    except Exception:
        logger.warning("Failed to save pending confirmation state: session_id=%s", session_id, exc_info=True)


async def _mark_pending_confirmation_message_status(
    session_id: str,
    message_id: Any,
    *,
    pending_id: str,
    status: str,
) -> None:
    message_id_text = str(message_id or "").strip()
    if not message_id_text:
        return
    try:
        msg_resp = await get_message_by_id(message_id_text)
        msg_data = (msg_resp or {}).get("data") or {}
        content_raw = msg_data.get("content", "")
        try:
            content_obj = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
        except (json.JSONDecodeError, TypeError):
            content_obj = {}
        if not isinstance(content_obj, dict) or content_obj.get("type") != "pendingConfirmationCard":
            return
        card_pending_id = str(content_obj.get("pendingId") or "").strip()
        if card_pending_id and pending_id and card_pending_id != pending_id:
            return
        updated = {
            **content_obj,
            "clickable": False,
            "clicked": status == "applied",
            "status": status,
        }
        if status in {"applied", "cancelled"}:
            updated["click_type"] = 1 if status == "applied" else 0
        await update_message(
            message_id=message_id_text,
            chat_session_id=session_id,
            content=updated,
            message_from=0,
            content_type="CARD",
        )
    except Exception:
        logger.warning(
            "Failed to update pending confirmation card message: session_id=%s message_id=%s status=%s",
            session_id,
            message_id_text,
            status,
            exc_info=True,
        )


async def _mark_pending_confirmation_failed(
    session_id: str,
    pending_state: dict[str, Any],
    message_id: Any,
    *,
    pending_id: str,
    result_code: str,
) -> None:
    failed_state = dict(pending_state)
    failed_state["status"] = "expired"
    failed_state["updatedAt"] = datetime.now(timezone.utc).isoformat()
    failed_state["resultCode"] = result_code
    await _save_pending_confirmation_state(session_id, failed_state)
    await _mark_pending_confirmation_message_status(
        session_id,
        message_id,
        pending_id=pending_id,
        status="expired",
    )


async def _expire_active_pending_confirmation_state(
    session_id: str,
    *,
    reason: str,
) -> None:
    pending_state = await _load_pending_confirmation_state(session_id)
    if not isinstance(pending_state, dict):
        return
    if str(pending_state.get("status") or "").strip() != "active":
        return
    expired_state = dict(pending_state)
    expired_state["status"] = "expired"
    expired_state["updatedAt"] = datetime.now(timezone.utc).isoformat()
    expired_state["expiredReason"] = reason
    await _save_pending_confirmation_state(session_id, expired_state)


async def _clear_legacy_plan_edit_cache_best_effort(session_id: str) -> None:
    try:
        session_id_int = int(str(session_id).strip())
    except (TypeError, ValueError):
        return
    try:
        await save_intent_change_cache(session_id_int, {})
    except Exception:
        logger.warning("Failed to clear legacy planEditCache: session_id=%s", session_id, exc_info=True)


def _build_plan_pending_state(
    session_id: str,
    confirmation_candidate: dict[str, Any],
    *,
    replaced_pending: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pending_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    action_family = str(confirmation_candidate.get("action_family") or "").strip()
    plan_payload = confirmation_candidate.get("plan_payload")
    payload_data: dict[str, Any] = {}
    if isinstance(plan_payload, str) and plan_payload.strip():
        try:
            parsed = json.loads(plan_payload)
            if isinstance(parsed, dict):
                payload_data = parsed
        except Exception:
            payload_data = {}
    source_backend_version = _as_int(
        confirmation_candidate.get("source_backend_version")
        or confirmation_candidate.get("planning_version")
        or payload_data.get("source_backend_version")
        or payload_data.get("planning_version")
    )
    state = {
        "type": "pendingConfirmation",
        "pendingId": pending_id,
        "sessionId": str(session_id),
        "kind": "plan_mutation",
        "status": "active",
        "actionFamily": action_family,
        "summary": str(confirmation_candidate.get("summary") or "").strip(),
        "userGoal": str(confirmation_candidate.get("user_goal") or "").strip(),
        "executionPayload": {
            "toolName": "execute_plan_action",
            "planPayload": plan_payload if isinstance(plan_payload, str) else "",
        },
        "createdAt": now,
        "updatedAt": now,
        "sourceBackendVersion": source_backend_version,
    }
    composite_proposal = payload_data.get("composite_proposal")
    if isinstance(composite_proposal, dict):
        state["compositeProposal"] = composite_proposal
    intent_update = confirmation_candidate.get("intent_update")
    if isinstance(intent_update, dict) and intent_update.get("selected"):
        state["executionPayload"]["intentPayload"] = intent_update
    if replaced_pending and replaced_pending.get("pendingId"):
        state["replacesPendingId"] = replaced_pending.get("pendingId")
    return state


def _soft_negative_label(label: str, *, intent_mode: str) -> str:
    if intent_mode == "constraint":
        return label
    replacements = {
        "排除专业": "不优先专业",
        "排除专业类": "不优先专业类",
        "排除专业门类": "不优先专业门类",
        "排除院校": "不优先院校",
        "排除地域": "不优先地域",
        "排除方向": "不优先发展方向",
    }
    return replacements.get(label, label)


def _positive_intent_label(label: str, *, constraint_intent_type: str = "default") -> str:
    if constraint_intent_type == "only_keep":
        replacements = {
            "偏好专业": "只保留专业",
            "偏好专业类": "只保留专业类",
            "偏好专业门类": "只保留专业门类",
            "偏好院校": "只保留院校",
            "偏好地域": "只保留地域",
            "发展方向": "只保留发展方向",
        }
        return replacements.get(label, label)
    if constraint_intent_type == "must_have":
        replacements = {
            "偏好专业": "至少保留专业",
            "偏好专业类": "至少保留专业类",
            "偏好专业门类": "至少保留专业门类",
            "偏好院校": "至少保留院校",
            "偏好地域": "至少保留地域",
            "发展方向": "至少保留发展方向",
        }
        return replacements.get(label, label)
    return label


def _summarize_intent_values(
    merged: dict[str, Any],
    *,
    intent_mode: str = "preference",
    constraint_intent_type: str = "default",
) -> str:
    parts: list[str] = []
    major_intents = merged.get("major_intents") if isinstance(merged.get("major_intents"), dict) else {}
    school_intents = merged.get("school_intents") if isinstance(merged.get("school_intents"), dict) else {}
    city_intents = merged.get("city_intents") if isinstance(merged.get("city_intents"), dict) else {}
    career_intents = merged.get("career_intents") if isinstance(merged.get("career_intents"), dict) else {}
    physical_constraints = (
        merged.get("physical_constraints")
        if isinstance(merged.get("physical_constraints"), dict)
        else merged.get("physicalConstraints")
        if isinstance(merged.get("physicalConstraints"), dict)
        else {}
    )

    def add(label: str, values: Any) -> None:
        raw_values = values if isinstance(values, list) else [values] if values else []
        texts = [str(value or "").strip() for value in raw_values if str(value or "").strip()]
        if texts:
            parts.append(f"{label}：{'、'.join(dict.fromkeys(texts))}")

    add(_positive_intent_label("偏好专业", constraint_intent_type=constraint_intent_type), major_intents.get("level3"))
    add(_positive_intent_label("偏好专业类", constraint_intent_type=constraint_intent_type), major_intents.get("level2"))
    add(_positive_intent_label("偏好专业门类", constraint_intent_type=constraint_intent_type), major_intents.get("level1"))
    add(_soft_negative_label("排除专业", intent_mode=intent_mode), major_intents.get("negative_level3"))
    add(_soft_negative_label("排除专业类", intent_mode=intent_mode), major_intents.get("negative_level2"))
    add(_soft_negative_label("排除专业门类", intent_mode=intent_mode), major_intents.get("negative_level1"))
    add(_positive_intent_label("偏好院校", constraint_intent_type=constraint_intent_type), school_intents.get("colleges"))
    add(_soft_negative_label("排除院校", intent_mode=intent_mode), school_intents.get("negative_colleges"))
    add(
        _positive_intent_label("偏好地域", constraint_intent_type=constraint_intent_type),
        _as_text_list(city_intents.get("province"))
        + _as_text_list(city_intents.get("city"))
        + _as_text_list(city_intents.get("area")),
    )
    add(
        _soft_negative_label("排除地域", intent_mode=intent_mode),
        _as_text_list(city_intents.get("negative_province"))
        + _as_text_list(city_intents.get("negative_city"))
        + _as_text_list(city_intents.get("negative_area")),
    )
    add(
        _positive_intent_label("发展方向", constraint_intent_type=constraint_intent_type),
        to_career_labels(career_intents.get("positive")),
    )
    add(
        _soft_negative_label("排除方向", intent_mode=intent_mode),
        to_career_labels(career_intents.get("negative")),
    )
    add("避开项目", _as_text_list(physical_constraints.get("special_limits")) + _as_text_list(physical_constraints.get("specialLimits")))
    return "；".join(parts)


def _as_text_list(values: Any) -> list[str]:
    raw_values = values if isinstance(values, list) else [values] if values else []
    return [str(value or "").strip() for value in raw_values if str(value or "").strip()]


def _normalize_school_intent_names(values: Any, batch: str | None = "01") -> list[str]:
    normalized: list[str] = []
    for value in _as_text_list(values):
        try:
            resolved = resolve_school_entity(value, batch)
            name = resolved.best.canonical_name if resolved.best else value
        except Exception:
            name = value
        if name and name not in normalized:
            normalized.append(name)
    return normalized


def _merge_intent_preview_item_values(items: list[Any]) -> dict[str, Any]:
    values: list[dict[str, Any]] = []
    for item in items:
        value = getattr(item, "value", None)
        if value is None and isinstance(item, dict):
            value = item.get("value")
        if isinstance(value, dict) and value:
            values.append(value)
    if not values:
        return {}
    try:
        return merge_selected_values(values)
    except Exception:
        return {}


def _positive_intent_payload_subset(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    subset: dict[str, Any] = {}
    for group_key, group_value in payload.items():
        if not isinstance(group_value, dict):
            continue
        positive_group = {
            key: value
            for key, value in group_value.items()
            if not str(key or "").startswith("negative_") and value
        }
        if positive_group:
            subset[group_key] = positive_group
    return subset


def _selected_data_with_existing_positive_context(
    selected_data: dict[str, Any],
    existing_merged: dict[str, Any] | None,
) -> dict[str, Any]:
    existing_positive = _positive_intent_payload_subset(existing_merged)
    if not existing_positive:
        return selected_data
    selected = [
        item
        for item in (selected_data.get("selected") if isinstance(selected_data, dict) else []) or []
        if isinstance(item, dict)
    ]
    if not selected:
        return selected_data
    try:
        selected_merged = merge_selected_values(selected)
    except Exception:
        selected_merged = {}
    if _intent_payload_has_positive_value(selected_merged):
        return selected_data
    augmented = dict(selected_data)
    augmented["selected"] = [*selected, existing_positive]
    augmented.pop("displaySummary", None)
    augmented.pop("display_summary", None)
    return augmented


def _format_intent_card_content(summary: str, *, existing_summary: str = "") -> str:
    lines: list[str] = []
    summary_parts = [part.strip() for part in str(summary or "").split("；") if part.strip()]
    if summary_parts:
        lines.extend(f"- {part}" for part in summary_parts[:3])
        if len(summary_parts) > 3:
            lines.append(f"- 另有 {len(summary_parts) - 3} 条，采纳后会一并作为后续参考")
    existing_parts = [part.strip() for part in str(existing_summary or "").split("；") if part.strip()]
    if existing_parts:
        if lines:
            lines.append("")
        lines.append("当前已有参考：")
        lines.extend(f"- {part}" for part in existing_parts[:3])
        if len(existing_parts) > 3:
            lines.append(f"- 另有 {len(existing_parts) - 3} 条，可在页面顶部“查看意向”里查看")
    return "\n".join(lines).strip() or summary


def _intent_card_primary_reply(
    summary: str,
    *,
    intent_mode: str,
    existing_summary: str = "",
) -> str:
    summary_text = str(summary or "").strip()
    existing_text = str(existing_summary or "").strip()
    if not summary_text and existing_text:
        summary_text = existing_text
    if summary_text:
        title = "已列出这次报考条件预览" if intent_mode == "constraint" else "已列出这次报考想法预览"
        reply = f"{title}：{summary_text}。"
    else:
        reply = "已列出这次待采纳内容。"
    if existing_text and existing_text != summary_text:
        reply += f"\n\n当前已有参考：{existing_text}。"
    reply += "\n\n点“采纳”前不会生效。"
    return _sanitize_reply_for_user(reply)


def _intent_summary_from_item_content(
    items: list[Any],
    *,
    intent_mode: str,
    constraint_intent_type: str,
) -> str:
    if not items:
        return ""
    merged = _merge_intent_preview_item_values(items)
    if not merged:
        return ""
    standard_summary = _summarize_intent_values(
        merged,
        intent_mode=intent_mode,
        constraint_intent_type=constraint_intent_type,
    )
    parts = [part.strip() for part in standard_summary.split("；") if part.strip()]
    if not parts:
        return ""

    def collect_content_values(category: str, key: str) -> list[str]:
        values: list[str] = []
        for item in items:
            raw_item = item.model_dump() if hasattr(item, "model_dump") else item
            if not isinstance(raw_item, dict):
                continue
            value = raw_item.get("value")
            if not isinstance(value, dict):
                continue
            group = value.get(category)
            if not isinstance(group, dict) or not group.get(key):
                continue
            structured_values = _as_text_list(group.get(key))
            content = str(raw_item.get("content") or "").strip()
            if not content:
                for structured_value in structured_values:
                    if structured_value and structured_value not in values:
                        values.append(structured_value)
                continue
            content = re.sub(r"^(把|将)", "", content)
            content = re.split(r"(记成|更新为|设为|从|作为|，|,)", content, maxsplit=1)[0].strip()
            content = re.sub(r"^当前已有参考", "", content).strip()
            content = re.sub(
                r"^(只保留专业门类|只保留专业类|只保留专业|至少保留专业门类|至少保留专业类|至少保留专业|偏好专业门类|偏好专业类|偏好专业|排除专业门类|排除专业类|排除专业|不优先专业门类|不优先专业类|不优先专业)[:：]",
                "",
                content,
            ).strip()
            content_values = [
                item.strip()
                for item in re.split(r"[、/，,]", content)
                if item.strip()
            ]
            if len(structured_values) == 1 and structured_values[0] and structured_values[0] in content:
                candidate_values = [content]
            elif (
                content_values
                and len(content_values) == len(structured_values)
                and set(content_values) == set(structured_values)
            ):
                candidate_values = content_values
            else:
                candidate_values = structured_values
            for content in candidate_values:
                if content and content not in values:
                    values.append(content)
        return values

    replacements = [
        ("只保留专业：", "major_intents", "level3"),
        ("至少保留专业：", "major_intents", "level3"),
        ("偏好专业：", "major_intents", "level3"),
        ("排除专业：", "major_intents", "negative_level3"),
        ("不优先专业：", "major_intents", "negative_level3"),
    ]
    rewritten: list[str] = []
    for part in parts:
        replacement = ""
        for prefix, category, key in replacements:
            if part.startswith(prefix):
                values = collect_content_values(category, key)
                if values:
                    replacement = f"{prefix}{'、'.join(values)}"
                break
        rewritten.append(replacement or part)
    return "；".join(rewritten)


def _display_summary_from_intent_payload(intent_payload: dict[str, Any] | None) -> str:
    if not isinstance(intent_payload, dict):
        return ""
    for key in ("displaySummary", "display_summary"):
        value = str(intent_payload.get(key) or "").strip()
        if value:
            return _sanitize_reply_for_user(value)
    return ""


def _intent_card_primary_reply_from_preview_payload(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return _intent_card_primary_reply("", intent_mode="preference", existing_summary="")
    intent_mode = str(payload.get("intentMode") or "preference").strip() or "preference"
    if intent_mode not in {"preference", "constraint"}:
        intent_mode = "preference"
    constraint_intent_type = str(
        payload.get("constraintIntentType")
        or payload.get("constraint_intent_type")
        or "default"
    ).strip() or "default"
    items = list(payload.get("items") or [])
    existing_items = list(payload.get("existingItems") or [])
    selected_summary = _intent_summary_from_item_content(
        items,
        intent_mode=intent_mode,
        constraint_intent_type=constraint_intent_type,
    ) or _summarize_intent_values(
        _merge_intent_preview_item_values(items),
        intent_mode=intent_mode,
        constraint_intent_type=constraint_intent_type,
    )
    existing_summary = _intent_summary_from_item_content(
        existing_items,
        intent_mode=intent_mode,
        constraint_intent_type=constraint_intent_type,
    ) or _summarize_intent_values(
        _merge_intent_preview_item_values(existing_items),
        intent_mode=intent_mode,
        constraint_intent_type=constraint_intent_type,
    )
    return _intent_card_primary_reply(
        selected_summary or str(payload.get("summary") or payload.get("title") or "").strip(),
        intent_mode=intent_mode,
        existing_summary=existing_summary,
    )


def _intent_card_primary_reply_from_card(card: WSResponse | None) -> str:
    if not isinstance(card, WSResponse):
        return ""
    payload = _parse_tool_return_json(str(getattr(card, "content", "") or ""))
    if not isinstance(payload, dict):
        return ""
    return _intent_card_primary_reply_from_preview_payload(payload)


def _pending_confirmation_primary_reply_from_card(card: WSResponse | None) -> str:
    if not isinstance(card, WSResponse):
        return ""
    payload = _parse_tool_return_json(str(getattr(card, "content", "") or ""))
    if not isinstance(payload, dict):
        return ""
    kind = str(payload.get("kind") or "").strip()
    summary = str(payload.get("summary") or "").strip()
    if kind == "plan_mutation":
        title = str(payload.get("title") or "调整预览").strip()
        lead = "已列出调整预览。"
        if title and not title.startswith("确认"):
            lead = f"已列出{title}。"
        lines = [lead]
        if summary:
            lines.extend(["", summary])
        lines.extend(["", "确认前不会改动当前方案；点“确认执行”后才会按这次预览处理。"])
        return _sanitize_reply_for_user("\n".join(lines))
    if kind == "intent_change":
        return _intent_card_primary_reply_from_card(card)
    return ""


def _semantic_intent_decision_requires_readonly(decision: dict[str, Any] | None) -> bool:
    if not isinstance(decision, dict):
        return False
    return (
        str(decision.get("decision") or "").strip() in {"analysis_only", "mixed_answer_then_ask"}
        and float(decision.get("confidence") or 0.0) >= 0.7
    )


def _merge_selected_intent_payload(intent_payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(intent_payload, dict):
        return {}
    selected = intent_payload.get("selected")
    if not isinstance(selected, list) or not selected:
        return {}
    try:
        return merge_selected_values([item for item in selected if isinstance(item, dict)])
    except Exception:
        logger.warning("Failed to merge selected intent payload for card content", exc_info=True)
        return {}


def _summarize_selected_intent_payload(intent_payload: dict[str, Any] | None) -> str:
    display_summary = _display_summary_from_intent_payload(intent_payload)
    if display_summary:
        return display_summary
    merged = _merge_selected_intent_payload(intent_payload)
    if not merged:
        return ""
    intent_mode = str((intent_payload or {}).get("intentMode") or "preference").strip()
    if intent_mode not in {"preference", "constraint"}:
        intent_mode = "preference"
    constraint_intent_type = str(
        (intent_payload or {}).get("constraintIntentType")
        or (intent_payload or {}).get("constraint_intent_type")
        or "default"
    ).strip() or "default"
    return _summarize_intent_values(
        merged,
        intent_mode=intent_mode,
        constraint_intent_type=constraint_intent_type,
    )


def _format_plan_card_intent_impact(intent_payload: dict[str, Any] | None) -> str:
    merged = _merge_selected_intent_payload(intent_payload)
    base = "确认前不会改动当前方案。"
    if not merged:
        return base
    intent_mode = str((intent_payload or {}).get("intentMode") or "preference").strip()
    has_positive = _intent_payload_has_positive_value(merged)
    has_negative = _intent_payload_has_negative_value(merged)
    if intent_mode == "constraint" and has_positive and has_negative:
        return f"{base}确认后会执行本次调整；优先方向会作为后续推荐参考，避开的方向会用于后续检查。"
    if intent_mode == "constraint" and has_negative:
        return f"{base}确认后会执行本次调整，并把这条避开条件作为后续参考。"
    if intent_mode == "constraint" and has_positive:
        return f"{base}确认后会执行本次调整，并把这条保留条件作为后续参考。"
    if has_positive and has_negative:
        return f"{base}确认后会执行本次调整；优先方向会作为后续推荐参考，不优先方向会适当靠后。"
    if has_positive or has_negative:
        return f"{base}确认后会执行本次调整，并同步后续报考参考。"
    return base


def _intent_payload_has_any_value(payload: dict[str, Any] | None, paths: list[tuple[str, str]]) -> bool:
    if not isinstance(payload, dict):
        return False
    for group_key, value_key in paths:
        group = payload.get(group_key)
        if not isinstance(group, dict):
            continue
        if _as_text_list(group.get(value_key)):
            return True
    items = payload.get("items")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict) or item.get("selected") is False:
                continue
            value = item.get("value")
            if isinstance(value, dict) and _intent_payload_has_any_value(value, paths):
                return True
    return False


def _intent_payload_has_positive_value(payload: dict[str, Any] | None) -> bool:
    return _intent_payload_has_any_value(
        payload,
        [
            ("major_intents", "level3"),
            ("major_intents", "level2"),
            ("major_intents", "level1"),
            ("school_intents", "colleges"),
            ("city_intents", "province"),
            ("city_intents", "city"),
            ("city_intents", "area"),
            ("career_intents", "positive"),
        ],
    )


def _intent_payload_has_negative_value(payload: dict[str, Any] | None) -> bool:
    return _intent_payload_has_any_value(
        payload,
        [
            ("major_intents", "negative_level3"),
            ("major_intents", "negative_level2"),
            ("major_intents", "negative_level1"),
            ("school_intents", "negative_colleges"),
            ("city_intents", "negative_province"),
            ("city_intents", "negative_city"),
            ("city_intents", "negative_area"),
            ("career_intents", "negative"),
            ("physical_constraints", "special_limits"),
            ("physicalConstraints", "specialLimits"),
        ],
    )


def _intent_confirmation_mechanism_line(
    intent_mode: str,
    payload: dict[str, Any] | None = None,
) -> str:
    has_positive = _intent_payload_has_positive_value(payload)
    has_negative = _intent_payload_has_negative_value(payload)
    constraint_intent_type = str((payload or {}).get("constraintIntentType") or (payload or {}).get("constraint_intent_type") or "default").strip()
    if constraint_intent_type in {"only_keep", "must_have"}:
        intent_mode = "constraint"
    if intent_mode == "constraint" and constraint_intent_type == "only_keep":
        return "采纳后只保留这个范围；方案需要改动时会先给你看预览。"
    if intent_mode == "constraint" and constraint_intent_type == "must_have":
        return "采纳后至少保留这个方向；方案需要补入时会先给你看预览。"
    if intent_mode == "constraint" and has_positive and has_negative:
        return "采纳后优先方向会排得更靠前，避开的方向会用于后续检查。"
    if intent_mode == "constraint" and has_positive:
        return "采纳后会优先满足这些方向，并用于后续检查。"
    if intent_mode == "constraint" and has_negative:
        return "采纳后会避开这些方向，并用于后续检查。"
    if intent_mode == "constraint":
        return "采纳后会作为后续推荐和方案检查依据。"
    if has_positive and has_negative:
        return "采纳后优先方向会排得更靠前，不优先方向会适当靠后。"
    if has_positive:
        return "采纳后这些方向会排得更靠前。"
    if has_negative:
        return "采纳后这些方向会适当靠后。"
    return "采纳后会作为后续推荐参考。"


def _format_intent_card_impact(
    payload: dict[str, Any] | None,
    *,
    intent_mode: str,
    fallback_mechanism_line: str = "",
    fallback_detail_lines: list[str] | None = None,
) -> str:
    analysis = payload.get("impactAnalysis") if isinstance(payload, dict) else None
    impact_lines = compact_relation_impact_lines(
        analysis if isinstance(analysis, dict) else None,
        intent_mode=intent_mode,
        limit=2,
    )
    mechanism_line = str(fallback_mechanism_line or _intent_confirmation_mechanism_line(intent_mode, payload)).strip()
    lines = [mechanism_line] if mechanism_line else []
    detail_lines = fallback_detail_lines if fallback_detail_lines else impact_lines
    lines.extend(line for line in detail_lines if line and line not in lines)
    return "\n".join(f"- {line}" for line in lines[:2])


def _build_intent_pending_state(
    session_id: str,
    *,
    selected_data: dict[str, Any],
    merged: dict[str, Any],
    intent_mode: str,
    batch: str,
    summary: str,
    constraint_intent_type: str = "default",
    replaced_pending: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pending_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    state = {
        "type": "pendingConfirmation",
        "pendingId": pending_id,
        "sessionId": str(session_id),
        "kind": "intent_change",
        "status": "active",
        "actionFamily": "apply_selected_intents",
        "summary": summary,
        "executionPayload": {
            "toolName": "apply_selected_intents",
            "selectedData": selected_data,
            "merged": merged,
            "intentMode": intent_mode,
            "constraintIntentType": constraint_intent_type,
            "batch": batch,
        },
        "createdAt": now,
        "updatedAt": now,
    }
    if replaced_pending and replaced_pending.get("pendingId"):
        state["replacesPendingId"] = replaced_pending.get("pendingId")
    if constraint_intent_type and constraint_intent_type != "default":
        state["constraintIntentType"] = constraint_intent_type
    if intent_mode == "constraint":
        composite_proposal = _build_constraint_composite_proposal_payload(
            {},
            merged=merged,
            selected_data=selected_data,
            constraint_intent_type=constraint_intent_type,
            batch=batch,
            summary=summary,
        )
        if isinstance(composite_proposal, dict):
            state["compositeProposal"] = composite_proposal
    return state


def _major_values_from_positive_intents(major_intents: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("level3", "level2", "level1"):
        for value in _as_text_list(major_intents.get(key)):
            if value and value not in values:
                values.append(value)
    return values


def _scope_payload(entity_type: str, values: list[str]) -> dict[str, Any] | None:
    deduped = list(dict.fromkeys(str(value or "").strip() for value in values if str(value or "").strip()))
    if not deduped:
        return None
    return {"entity_type": entity_type, "values": deduped}


def _positive_goal_scopes_from_intents(merged: dict[str, Any], batch: str | None = "01") -> list[dict[str, Any]]:
    raw_major_intents = merged.get("major_intents") if isinstance(merged.get("major_intents"), dict) else {}
    major_intents = _remove_positive_major_targets_excluded_by_negative_scope(
        raw_major_intents,
        batch=batch or "01",
    ) or {}
    school_intents = merged.get("school_intents") if isinstance(merged.get("school_intents"), dict) else {}
    city_intents = merged.get("city_intents") if isinstance(merged.get("city_intents"), dict) else {}
    scopes: list[dict[str, Any]] = []
    major_scope = _scope_payload("major", _major_values_from_positive_intents(major_intents))
    school_scope = _scope_payload("school", _normalize_school_intent_names(school_intents.get("colleges"), batch))
    region_scope = _scope_payload(
        "region",
        normalize_region_names(city_intents.get("province"), expected_level="province")
        + normalize_region_names(city_intents.get("city"), expected_level="city")
        + normalize_region_names(city_intents.get("area"), expected_level="area"),
    )
    for scope in (major_scope, school_scope, region_scope):
        if scope is not None:
            scopes.append(scope)
    return scopes


def _negative_goal_scopes_from_intents(merged: dict[str, Any], batch: str | None = "01") -> list[dict[str, Any]]:
    major_intents = merged.get("major_intents") if isinstance(merged.get("major_intents"), dict) else {}
    school_intents = merged.get("school_intents") if isinstance(merged.get("school_intents"), dict) else {}
    city_intents = merged.get("city_intents") if isinstance(merged.get("city_intents"), dict) else {}
    scopes: list[dict[str, Any]] = []
    major_scope = _scope_payload(
        "major",
        _as_text_list(major_intents.get("negative_level3"))
        + _as_text_list(major_intents.get("negative_level2"))
        + _as_text_list(major_intents.get("negative_level1")),
    )
    school_scope = _scope_payload("school", _normalize_school_intent_names(school_intents.get("negative_colleges"), batch))
    region_scope = _scope_payload(
        "region",
        normalize_region_names(city_intents.get("negative_province"), expected_level="province")
        + normalize_region_names(city_intents.get("negative_city"), expected_level="city")
        + normalize_region_names(city_intents.get("negative_area"), expected_level="area"),
    )
    for scope in (major_scope, school_scope, region_scope):
        if scope is not None:
            scopes.append(scope)
    return scopes


def _constraint_goal_type(constraint_intent_type: str) -> str:
    if constraint_intent_type == "only_keep":
        return "only_keep_scope"
    if constraint_intent_type == "must_have":
        return "must_include_scope"
    return "exclude_scope"


@dataclass
class _ConstraintPlanConfirmationAttempt:
    card: WSResponse | None = None
    fallback_mechanism_line: str = ""
    fallback_detail_lines: list[str] = field(default_factory=list)


def _constraint_plan_confirmation_fallback(
    proposal: dict[str, Any] | None,
    *,
    constraint_intent_type: str,
) -> tuple[str, list[str]]:
    if not isinstance(proposal, dict):
        return "", []
    status = str(proposal.get("status") or "").strip()
    summary = _normalize_user_facing_terms(
        _normalize_fix_proposal_user_text(str(proposal.get("summary") or "").strip())
    )
    impact = _normalize_user_facing_terms(
        _normalize_fix_proposal_user_text(str(proposal.get("impact") or "").strip())
    )
    blocking_reason = _normalize_user_facing_terms(
        _normalize_fix_proposal_user_text(
            str(proposal.get("blockingReason") or proposal.get("blocking_reason") or "").strip()
        )
    )
    if status == "info":
        mechanism_line = "采纳后先把这条条件记下来；当前方案已经符合这个方向，不需要立刻改动。"
        detail_lines = [summary or impact or "当前方案暂时不需要为了这条条件调整。"]
    else:
        mechanism_line = "采纳后先把这条条件记下来；当前没有可直接执行的方案调整。"
        detail_lines = [summary or blocking_reason or impact or "这次先记录条件，后续可以放宽范围后再让我重试。"]
    if constraint_intent_type == "only_keep":
        detail_lines.append("如果之后找到相关志愿，我会先给你调整预览，再由你确认。")
    elif constraint_intent_type == "must_have":
        detail_lines.append("如果之后补到相关志愿，我会先给你补入预览，再由你确认。")
    else:
        detail_lines.append("如果后面能明确要避开的范围，我会先给你调整预览，再由你确认。")
    return mechanism_line, [line for line in detail_lines if str(line or "").strip()]


def _build_constraint_composite_proposal_payload(
    plan_payload: dict[str, Any],
    *,
    merged: dict[str, Any],
    selected_data: dict[str, Any],
    constraint_intent_type: str,
    batch: str,
    summary: str,
) -> dict[str, Any] | None:
    goal_type = _constraint_goal_type(constraint_intent_type)
    target_scopes = _positive_goal_scopes_from_intents(merged, batch) if goal_type in {"only_keep_scope", "must_include_scope"} else []
    negative_scopes = _negative_goal_scopes_from_intents(merged, batch) if goal_type == "exclude_scope" else []
    if not target_scopes and not negative_scopes:
        return None

    goal = PlanGoal(
        goal_type=goal_type,  # type: ignore[arg-type]
        user_original_text=summary,
        target_scopes=target_scopes,
        negative_scopes=negative_scopes,
        confidence="high",
    )
    intent_update: dict[str, Any] = {
        "intentMode": "constraint",
        "constraintIntentType": constraint_intent_type,
    }
    if target_scopes:
        intent_update["targetScopes"] = target_scopes
    if negative_scopes:
        intent_update["negativeScopes"] = negative_scopes

    proposal = CompositePlanProposal(
        source_version=_as_int(plan_payload.get("planning_version")),
        goal=goal,
        intent_updates=[intent_update],
        plan_actions=[],
        decision_references=[],
        feasibility="ready",
        impact_summary=[str(plan_payload.get("preview_summary") or summary).strip()],
        requires_confirmation=True,
        post_apply_validation_plan=[
            "执行后重新读取当前方案",
            "执行后重新审查风险和提醒",
        ],
    )
    return proposal.model_dump()


def _user_goal_req_scopes_for_scope(
    scope: dict[str, Any],
    *,
    evidence_source: str,
) -> list[dict[str, Any]]:
    values = scope_value_list(scope)
    entity_type = scope_entity_type(scope) or "unknown"
    return [
        {
            "scopeType": entity_type,
            "entityType": entity_type,
            "name": value,
            "normalizedName": value,
            "rawText": value,
            "resolutionStatus": "resolved",
            "evidence": {
                "source": evidence_source,
                "values": values,
            },
        }
        for value in values
    ]


def _build_user_goal_fix_proposal_req(
    goal: dict[str, Any],
    planning_version: int,
    *,
    context: dict[str, Any] | None = None,
    evidence_source: str = "confirmed_intent",
) -> dict[str, Any] | None:
    if not isinstance(goal, dict) or planning_version <= 0:
        return None
    goal_type = str(goal.get("goal_type") or goal.get("goalType") or "").strip()
    if goal_type not in {"only_keep_scope", "must_include_scope", "exclude_scope", "tuition_budget_scope"}:
        return None
    normalized_context = dict(context or {})
    if goal_type == "tuition_budget_scope":
        max_tuition = _as_int(
            goal.get("max_tuition_per_year")
            or goal.get("maxTuitionPerYear")
            or normalized_context.get("maxTuitionPerYear")
        )
        if max_tuition <= 0:
            return None
        normalized_context["maxTuitionPerYear"] = max_tuition
        return {
            "proposalSource": "user_goal",
            "goalType": goal_type,
            "userOriginalText": str(goal.get("user_original_text") or goal.get("userOriginalText") or "").strip(),
            "confidence": str(goal.get("confidence") or "high").strip(),
            "sourceVersionGuard": planning_version,
            "targetScopes": [],
            "negativeScopes": [],
            "qualityGuards": [
                str(item or "").strip()
                for item in goal.get("quality_guards", [])
                if str(item or "").strip()
            ],
            "tradeoffGuards": [
                str(item or "").strip()
                for item in goal.get("structure_targets", [])
                if str(item or "").strip()
            ],
            "context": normalized_context,
        }
    target_scopes = [
        req_scope
        for item in goal.get("target_scopes", [])
        if isinstance(item, dict)
        for req_scope in _user_goal_req_scopes_for_scope(item, evidence_source=evidence_source)
    ]
    negative_scopes = [
        req_scope
        for item in goal.get("negative_scopes", [])
        if isinstance(item, dict)
        for req_scope in _user_goal_req_scopes_for_scope(item, evidence_source=evidence_source)
    ]
    if goal_type in {"only_keep_scope", "must_include_scope"} and not target_scopes:
        return None
    if goal_type == "exclude_scope" and not negative_scopes:
        return None
    return {
        "proposalSource": "user_goal",
        "goalType": goal_type,
        "userOriginalText": str(goal.get("user_original_text") or goal.get("userOriginalText") or "").strip(),
        "confidence": str(goal.get("confidence") or "high").strip(),
        "sourceVersionGuard": planning_version,
        "targetScopes": target_scopes,
        "negativeScopes": negative_scopes,
        "qualityGuards": [
            str(item or "").strip()
            for item in goal.get("quality_guards", [])
            if str(item or "").strip()
        ],
        "tradeoffGuards": [
            str(item or "").strip()
            for item in goal.get("structure_targets", [])
            if str(item or "").strip()
        ],
        "context": normalized_context,
    }


def _composite_goal_needs_clarification(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    composite = payload.get("composite_proposal") or payload.get("compositeProposal")
    if not isinstance(composite, dict):
        return False
    goal = composite.get("goal")
    if not isinstance(goal, dict):
        return False
    return goal.get("needs_clarification") is True or goal.get("needsClarification") is True


async def _maybe_create_plan_confirmation_from_constraint_preview(
    session_id: str,
    *,
    selected_data: dict[str, Any],
    merged: dict[str, Any],
    batch: str,
    summary: str,
    constraint_intent_type: str = "default",
) -> _ConstraintPlanConfirmationAttempt:
    attempt = _ConstraintPlanConfirmationAttempt()
    composite_proposal = _build_constraint_composite_proposal_payload(
        {},
        merged=merged,
        selected_data=selected_data,
        constraint_intent_type=constraint_intent_type,
        batch=batch,
        summary=summary,
    )
    if not isinstance(composite_proposal, dict):
        return attempt
    planning_version = _as_int(composite_proposal.get("source_version"))
    if planning_version <= 0:
        try:
            state_resp = await get_planning_state(session_id)
            planning_version = _as_int(((state_resp or {}).get("data") or {}).get("version"))
        except Exception:
            logger.warning("Failed to load planning state for user-goal proposal: session_id=%s", session_id, exc_info=True)
            planning_version = 0
    if planning_version <= 0:
        return attempt
    user_goal_request = _build_user_goal_fix_proposal_req(
        composite_proposal.get("goal") if isinstance(composite_proposal.get("goal"), dict) else {},
        planning_version,
        context={"source": "chat_service_constraint_confirmation"},
        evidence_source="confirmed_intent",
    )
    if not user_goal_request:
        return attempt
    try:
        proposal_result = await generate_user_goal_planning_fix_proposals(1, session_id, user_goal_request)
    except Exception:
        logger.warning(
            "Failed to generate user-goal plan proposal: session_id=%s summary=%s",
            session_id,
            summary,
            exc_info=True,
        )
        return attempt
    if proposal_result.get("code") != 0:
        return attempt
    data = proposal_result.get("data")
    if not isinstance(data, dict):
        return attempt
    source_version_guard = _as_int(data.get("sourceVersionGuard") or data.get("source_version_guard") or planning_version)
    proposal = _select_ready_fix_proposal(
        {"fix_proposals": data},
        target_strategies=[_constraint_goal_type(constraint_intent_type)],
    )
    if not isinstance(proposal, dict):
        proposals = data.get("proposals") if isinstance(data.get("proposals"), list) else []
        fallback_proposal = next((item for item in proposals if isinstance(item, dict)), None)
        attempt.fallback_mechanism_line, attempt.fallback_detail_lines = _constraint_plan_confirmation_fallback(
            fallback_proposal,
            constraint_intent_type=constraint_intent_type,
        )
        return attempt
    proposal = dict(proposal)
    proposal.setdefault("proposalSource", "user_goal")
    attempt.card = await _create_pending_fix_proposal_confirmation_response(
        session_id,
        proposal,
        source_version_guard=source_version_guard,
        proposal_source="user_goal",
        user_goal_request=user_goal_request,
        intent_payload=selected_data,
    )
    return attempt


def _structured_goal_from_composite_proposal(source: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(source, dict):
        return None
    composite = source.get("composite_proposal") or source.get("compositeProposal")
    if not isinstance(composite, dict):
        return None
    goal = composite.get("goal")
    if not isinstance(goal, dict):
        return None
    goal_type = str(goal.get("goal_type") or goal.get("goalType") or "").strip()
    if goal_type not in {"only_keep_scope", "must_include_scope", "exclude_scope", "tuition_budget_scope"}:
        return None
    if goal.get("needs_clarification") is True or goal.get("needsClarification") is True:
        return None
    if goal_type == "tuition_budget_scope":
        if _as_int(goal.get("max_tuition_per_year") or goal.get("maxTuitionPerYear")) <= 0:
            return None
        return goal
    if goal_type in {"only_keep_scope", "must_include_scope"} and not goal.get("target_scopes") and not goal.get("targetScopes"):
        return None
    if goal_type == "exclude_scope" and not goal.get("negative_scopes") and not goal.get("negativeScopes"):
        return None
    return goal


def _structured_intent_payload_from_composite_proposal(source: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(source, dict):
        return None
    override = source.get("intent_payload_override") or source.get("intentPayloadOverride")
    if isinstance(override, dict) and isinstance(override.get("selected"), list):
        return override
    composite = source.get("composite_proposal") or source.get("compositeProposal")
    if not isinstance(composite, dict):
        return None
    goal = composite.get("goal")
    if not isinstance(goal, dict):
        return None
    goal_type = str(goal.get("goal_type") or goal.get("goalType") or "").strip()
    constraint_intent_type = "default"
    if goal_type == "only_keep_scope":
        constraint_intent_type = "only_keep"
    elif goal_type == "must_include_scope":
        constraint_intent_type = "must_have"

    selected: list[dict[str, Any]] = []
    for scope in goal.get("target_scopes") or goal.get("targetScopes") or []:
        if not isinstance(scope, dict):
            continue
        item = _intent_selected_item_from_goal_scope(
            scope_type=scope_entity_type(scope) or "",
            values=scope_value_list(scope),
            negative=False,
        )
        if item:
            selected.append(item)
    for scope in goal.get("negative_scopes") or goal.get("negativeScopes") or []:
        if not isinstance(scope, dict):
            continue
        item = _intent_selected_item_from_goal_scope(
            scope_type=scope_entity_type(scope) or "",
            values=scope_value_list(scope),
            negative=True,
        )
        if item:
            selected.append(item)
    if not selected:
        return None
    return {
        "selected": selected,
        "intentMode": "constraint",
        "constraintIntentType": constraint_intent_type or "default",
    }


def _merge_existing_intent_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    try:
        preview = parse_intent_analysis_payload(json.dumps(payload, ensure_ascii=False))
    except Exception:
        return {}
    return _merge_intent_preview_item_values(list(preview.existingItems))


def _intent_selected_item_from_goal_scope(
    *,
    scope_type: str,
    values: list[str],
    negative: bool = False,
) -> dict[str, Any] | None:
    clean_values = _as_text_list(values)
    if not clean_values:
        return None
    if scope_type == "major":
        return {"major_intents": {"negative_level3" if negative else "level3": clean_values}}
    if scope_type == "school":
        return {"school_intents": {"negative_colleges" if negative else "colleges": clean_values}}
    if scope_type == "region":
        return {"city_intents": {"negative_province" if negative else "province": clean_values}}
    if scope_type == "program_type" and negative:
        return {"physical_constraints": {"special_limits": [f"不接受{value}" for value in clean_values]}}
    return None


def _constraint_intent_payload_from_goal_decision(
    *,
    scope_type: str,
    target_values: list[str],
    negative_values: list[str],
    constraint_intent_type: str,
) -> dict[str, Any] | None:
    selected: list[dict[str, Any]] = []
    target_item = _intent_selected_item_from_goal_scope(
        scope_type=scope_type,
        values=target_values,
        negative=False,
    )
    if target_item:
        selected.append(target_item)
    negative_item = _intent_selected_item_from_goal_scope(
        scope_type=scope_type,
        values=negative_values,
        negative=True,
    )
    if negative_item:
        selected.append(negative_item)
    if not selected:
        return None
    return {
        "selected": selected,
        "intentMode": "constraint",
        "constraintIntentType": constraint_intent_type or "default",
    }


async def _maybe_create_plan_confirmation_from_structured_goal(
    session_id: str,
    source: dict[str, Any] | None,
    *,
    context_source: str,
    intent_payload_override: dict[str, Any] | None = None,
) -> WSResponse | None:
    goal = _structured_goal_from_composite_proposal(source)
    if not isinstance(goal, dict):
        return None
    planning_version = _as_int(
        (source or {}).get("planning_version")
        or (source or {}).get("planningVersion")
        or (source or {}).get("source_backend_version")
        or (source or {}).get("sourceBackendVersion")
    )
    if planning_version <= 0:
        composite = (source or {}).get("composite_proposal") or (source or {}).get("compositeProposal")
        if isinstance(composite, dict):
            planning_version = _as_int(composite.get("source_version") or composite.get("sourceVersion"))
    if planning_version <= 0:
        try:
            state_resp = await get_planning_state(session_id)
            planning_version = _as_int(((state_resp or {}).get("data") or {}).get("version"))
        except Exception:
            logger.warning(
                "Failed to load planning state for structured user-goal proposal: session_id=%s",
                session_id,
                exc_info=True,
            )
            planning_version = 0
    if planning_version <= 0:
        return None
    user_goal_request = _build_user_goal_fix_proposal_req(
        goal,
        planning_version,
        context={"source": context_source},
        evidence_source="structured_plan_goal",
    )
    if not user_goal_request:
        return None
    try:
        proposal_result = await generate_user_goal_planning_fix_proposals(1, session_id, user_goal_request)
    except Exception:
        logger.warning(
            "Failed to generate structured user-goal plan proposal: session_id=%s goal_type=%s",
            session_id,
            user_goal_request.get("goalType"),
            exc_info=True,
        )
        return None
    if proposal_result.get("code") != 0:
        return None
    data = proposal_result.get("data")
    if not isinstance(data, dict):
        return None
    source_version_guard = _as_int(data.get("sourceVersionGuard") or data.get("source_version_guard") or planning_version)
    proposal = _select_ready_fix_proposal(
        {"fix_proposals": data},
        target_strategies=[str(user_goal_request.get("goalType") or "").strip()],
    )
    if not isinstance(proposal, dict):
        proposals = data.get("proposals") if isinstance(data.get("proposals"), list) else []
        fallback_proposal = next((item for item in proposals if isinstance(item, dict)), None)
        fallback_intent_payload = (
            intent_payload_override
            or _structured_intent_payload_from_composite_proposal(source)
            or {}
        )
        fallback_constraint_type = str(
            fallback_intent_payload.get("constraintIntentType")
            or fallback_intent_payload.get("constraint_intent_type")
            or "default"
        ).strip() or "default"
        fallback_mechanism_line, fallback_detail_lines = _constraint_plan_confirmation_fallback(
            fallback_proposal,
            constraint_intent_type=fallback_constraint_type,
        )
        return await _maybe_create_intent_confirmation_from_structured_goal(
            session_id,
            source,
            intent_payload_override=intent_payload_override,
            fallback_mechanism_line=fallback_mechanism_line,
            fallback_detail_lines=fallback_detail_lines,
        )
    proposal = dict(proposal)
    proposal.setdefault("proposalSource", "user_goal")
    return await _create_pending_fix_proposal_confirmation_response(
        session_id,
        proposal,
        source_version_guard=source_version_guard,
        proposal_source="user_goal",
        user_goal_request=user_goal_request,
        intent_payload=(
            intent_payload_override
            or _structured_intent_payload_from_composite_proposal(source)
        ),
    )


async def _maybe_create_intent_confirmation_from_structured_goal(
    session_id: str,
    source: dict[str, Any] | None,
    *,
    intent_payload_override: dict[str, Any] | None = None,
    fallback_mechanism_line: str = "",
    fallback_detail_lines: list[str] | None = None,
) -> WSResponse | None:
    intent_payload = (
        intent_payload_override
        or _structured_intent_payload_from_composite_proposal(source)
    )
    if not isinstance(intent_payload, dict):
        return None
    selected_values = [
        item
        for item in (intent_payload.get("selected") or [])
        if isinstance(item, dict) and item
    ]
    if not selected_values:
        return None
    try:
        merged = merge_selected_values(selected_values)
    except Exception:
        logger.warning(
            "Failed to merge structured goal intent fallback: session_id=%s",
            session_id,
            exc_info=True,
        )
        return None
    if not merged:
        return None
    intent_mode = str(intent_payload.get("intentMode") or "constraint").strip()
    if intent_mode not in {"preference", "constraint"}:
        intent_mode = "constraint"
    constraint_intent_type = _normalize_constraint_type_for_payload(
        intent_payload.get("constraintIntentType")
        or intent_payload.get("constraint_intent_type"),
        merged,
    )
    if constraint_intent_type in {"only_keep", "must_have"}:
        intent_mode = "constraint"
    selected_data = {
        **intent_payload,
        "selected": selected_values,
        "intentMode": intent_mode,
        "constraintIntentType": constraint_intent_type,
    }
    batch = await _resolve_session_batch(session_id)
    intent_response = await _create_pending_intent_confirmation_response(
        session_id,
        selected_data=selected_data,
        merged=merged,
        intent_mode=intent_mode,
        batch=batch,
        fallback_mechanism_line=fallback_mechanism_line,
        fallback_detail_lines=fallback_detail_lines,
    )
    for followup in intent_response.followups:
        if isinstance(followup, WSResponse) and followup.type == "pendingConfirmationCard":
            return followup
    return None


async def _create_pending_intent_confirmation_response(
    session_id: str,
    *,
    selected_data: dict[str, Any],
    merged: dict[str, Any],
    intent_mode: str,
    batch: str,
    fallback_mechanism_line: str = "",
    fallback_detail_lines: list[str] | None = None,
) -> ChatServiceResponseEnvelope:
    replaced_pending = await _load_pending_confirmation_state(session_id)
    mode_text = "要求" if intent_mode == "constraint" else "偏好"
    constraint_intent_type = _normalize_constraint_type_for_payload(
        selected_data.get("constraintIntentType") or selected_data.get("constraint_intent_type"),
        merged,
    )
    summary = _display_summary_from_intent_payload(selected_data) or _summarize_intent_values(
        merged,
        intent_mode=intent_mode,
        constraint_intent_type=constraint_intent_type,
    )
    if not summary:
        summary = f"本次选择的{mode_text}内容。"
    pending_state = _build_intent_pending_state(
        session_id,
        selected_data=selected_data,
        merged=merged,
        intent_mode=intent_mode,
        batch=batch,
        summary=summary,
        constraint_intent_type=constraint_intent_type,
        replaced_pending=replaced_pending if isinstance(replaced_pending, dict) else None,
    )
    await _save_pending_confirmation_state(session_id, pending_state)
    await _clear_legacy_plan_edit_cache_best_effort(session_id)
    card_content = _format_intent_card_content(summary)
    payload = {
        "type": "pendingConfirmationCard",
        "pendingId": pending_state["pendingId"],
        "kind": "intent_change",
        "actionFamily": "apply_selected_intents",
        "title": "采纳这次报考条件" if intent_mode == "constraint" else "采纳这次报考想法",
        "summary": summary,
        "content": card_content,
        "constraintIntentType": constraint_intent_type,
        "clickable": True,
        "status": "active",
        "confirmText": "采纳",
        "cancelText": "暂不采纳",
        "impactTitle": "采纳后的作用",
        "impact": _format_intent_card_impact(
            {
                **merged,
                "constraintIntentType": constraint_intent_type,
            },
            intent_mode=intent_mode,
            fallback_mechanism_line=fallback_mechanism_line,
            fallback_detail_lines=fallback_detail_lines,
        ),
    }
    return ChatServiceResponseEnvelope(
        primary=_intent_card_primary_reply(summary, intent_mode=intent_mode, existing_summary=""),
        followups=[
            WSResponse(
                type="pendingConfirmationCard",
                session_id=session_id,
                content=json.dumps(payload, ensure_ascii=False),
            )
        ],
    )


async def _resolve_session_batch(session_id: str, default: str = "01") -> str:
    try:
        score_response = await get_user_score_detail(session_id)
        if score_response.get("code") == 0:
            raw_data = score_response.get("data", {}).get("userScoreDetail", {})
            if isinstance(raw_data, dict):
                batch = _normalize_batch(raw_data.get("batch"))
                if batch:
                    return batch
    except Exception:
        logger.warning("Failed to resolve session batch: session_id=%s", session_id, exc_info=True)
    return default


def _parse_score_detail_from_backend(raw_data: dict[str, Any]) -> ScoreDetail:
    province_raw = raw_data.get("province")
    province_name = (
        province_raw.get("name", "")
        if isinstance(province_raw, dict)
        else str(province_raw or raw_data.get("provinceName") or "")
    )
    subject_list = [
        item.get("name", "")
        for item in raw_data.get("subjectList", [])
        if isinstance(item, dict) and item.get("name")
    ]
    sex_raw = raw_data.get("sex")
    sex_name = sex_raw.get("name", "") if isinstance(sex_raw, dict) else str(sex_raw or "")
    return ScoreDetail(
        province=province_name,
        total_score=int(raw_data.get("totalScore") or raw_data.get("total_score") or 0),
        subject_list=subject_list,
        sex=sex_name,
        volunteer_model=str(raw_data.get("volunteerModel") or raw_data.get("volunteer_model") or "major"),
    )


async def _create_pending_intent_confirmation_from_preview_payload(
    session_id: str,
    payload: dict[str, Any] | None,
) -> WSResponse | None:
    """Create a unified pending card from structured intent preview output."""
    if not isinstance(payload, dict):
        return None
    payload = _normalize_intent_preview_payload_for_parse(payload)
    try:
        preview = parse_intent_analysis_payload(json.dumps(payload, ensure_ascii=False))
    except Exception:
        return None
    if preview.analysisStage != "confirmed":
        return None
    if preview.status not in {"ready", "existing_only"}:
        return None
    selected_values = [
        item.value
        for item in preview.items
        if item.selected and isinstance(item.value, dict) and item.value
    ]
    if not selected_values:
        return None
    try:
        merged = merge_selected_values(selected_values)
    except Exception:
        logger.warning(
            "Failed to merge structured intent preview values: session_id=%s",
            session_id,
            exc_info=True,
        )
        return None
    if not merged:
        return None
    intent_mode = str(preview.intentMode or "preference").strip()
    if intent_mode not in {"preference", "constraint"}:
        intent_mode = "preference"
    constraint_intent_type = _normalize_constraint_type_for_payload(
        getattr(preview, "constraintIntentType", "default"),
        merged,
    )
    if constraint_intent_type in {"only_keep", "must_have"}:
        intent_mode = "constraint"
    existing_merged = _merge_intent_preview_item_values(list(preview.existingItems))
    selected_display_summary = _intent_summary_from_item_content(
        list(preview.items),
        intent_mode=intent_mode,
        constraint_intent_type=constraint_intent_type,
    )
    existing_summary = _intent_summary_from_item_content(
        list(preview.existingItems),
        intent_mode=intent_mode,
        constraint_intent_type=constraint_intent_type,
    ) or _summarize_intent_values(existing_merged, intent_mode=intent_mode)
    batch = await _resolve_session_batch(session_id)
    selected_data = {
        "selected": selected_values,
        "intentMode": intent_mode,
        "constraintIntentType": constraint_intent_type,
        "batch": batch,
    }
    replaced_pending = await _load_pending_confirmation_state(session_id)
    summary = (
        selected_display_summary
        or _summarize_intent_values(
            merged,
            intent_mode=intent_mode,
            constraint_intent_type=constraint_intent_type,
        )
        or preview.title
        or "本次点击采纳后生效的内容。"
    )
    if selected_display_summary:
        selected_data["displaySummary"] = selected_display_summary
    plan_attempt = _ConstraintPlanConfirmationAttempt()
    plan_selected_data = _selected_data_with_existing_positive_context(
        selected_data,
        existing_merged,
    )
    if intent_mode == "constraint":
        plan_attempt = await _maybe_create_plan_confirmation_from_constraint_preview(
            session_id,
            selected_data=plan_selected_data,
            merged=merged,
            batch=batch,
            summary=summary,
            constraint_intent_type=constraint_intent_type,
        )
        if plan_attempt.card is not None:
            return plan_attempt.card
    pending_state = _build_intent_pending_state(
        session_id,
        selected_data=selected_data,
        merged=merged,
        intent_mode=intent_mode,
        batch=batch,
        summary=summary,
        constraint_intent_type=constraint_intent_type,
        replaced_pending=replaced_pending if isinstance(replaced_pending, dict) else None,
    )
    await _save_pending_confirmation_state(session_id, pending_state)
    await _clear_legacy_plan_edit_cache_best_effort(session_id)
    card_content = _format_intent_card_content(summary, existing_summary=existing_summary)
    card_payload = {
        "type": "pendingConfirmationCard",
        "pendingId": pending_state["pendingId"],
        "kind": "intent_change",
        "actionFamily": "apply_selected_intents",
        "title": "采纳这次报考条件" if intent_mode == "constraint" else "采纳这次报考想法",
        "summary": summary,
        "content": card_content,
        "constraintIntentType": constraint_intent_type,
        "clickable": True,
        "status": "active",
        "confirmText": "采纳",
        "cancelText": "暂不采纳",
        "impactTitle": "采纳后的作用",
        "impact": _format_intent_card_impact(
            payload,
            intent_mode=intent_mode,
            fallback_mechanism_line=plan_attempt.fallback_mechanism_line,
            fallback_detail_lines=plan_attempt.fallback_detail_lines,
        ),
    }
    return WSResponse(
        type="pendingConfirmationCard",
        session_id=session_id,
        content=json.dumps(card_payload, ensure_ascii=False),
    )


def _normalize_intent_preview_payload_for_parse(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    for key in ("items", "existingItems"):
        items = normalized.get(key)
        if not isinstance(items, list):
            continue
        normalized_items: list[Any] = []
        for item in items:
            if not isinstance(item, dict):
                normalized_items.append(item)
                continue
            normalized_item = dict(item)
            if not str(normalized_item.get("content") or "").strip():
                label = str(normalized_item.get("label") or "").strip()
                if label:
                    normalized_item["content"] = label
            normalized_items.append(normalized_item)
        normalized[key] = normalized_items
    return normalized


async def _recover_unbacked_intent_confirmation(
    session_id: str,
    request_context: RequestContext,
    *,
    reply: str,
    force: bool = False,
) -> WSResponse | None:
    """Recover a pending intent card when the model wrote a confirm prompt but skipped the intent tool."""
    if not isinstance(reply, str) or (not force and not _reply_looks_like_unbacked_intent_preview(reply)):
        return None
    ctx = SimpleNamespace(deps=request_context)
    recovery_scope = _intent_recovery_scope_from_pending_context(request_context)
    try:
        payload_text = await analyze_volunteer_intent_change(
            ctx,
            None,
            None,
            None,
            None,
            analysis_stage=ANALYSIS_STAGE_CONFIRMED,
            recovery_scope=recovery_scope,
            confirm_enabled=True,
        )
        preview_payload = parse_intent_analysis_payload(payload_text).model_dump()
    except Exception:
        logger.warning(
            "Failed to recover unbacked intent confirmation: session_id=%s",
            session_id,
            exc_info=True,
        )
        return None
    return await _create_pending_intent_confirmation_from_preview_payload(session_id, preview_payload)


def _tool_calls_are_readonly_explore_or_compare(messages: list[Any] | None) -> bool:
    tool_names = [str(part.tool_name or "").strip() for part in _iter_tool_call_parts(messages)]
    if not tool_names:
        return False
    readonly_tools = set(_INTENT_INTEREST_ANALYSIS_TOOL_NAMES) | {
        "compare_major_options",
        "compare_majors",
        "compare_majors_adhoc",
        "compare_schools",
        "compare_schools_adhoc",
        "get_major_introduction",
        "get_major_introductions",
        "get_school_introduction",
    }
    return all(name in readonly_tools for name in tool_names)


def _reply_leaves_explicit_intent_as_future_reference(reply: str) -> bool:
    compact = _compact_plan_reply_text(reply)
    if not compact:
        return False
    if any(
        marker in compact
        for marker in (
            "先只分析不要记",
            "不要记偏好",
            "别记偏好",
            "先不要记",
            "先别记",
            "不会写入后续参考",
            "不会写入后续报考参考",
            "不生成待采纳",
            "只是分析",
            "只做分析",
        )
    ):
        return False
    has_future_reference = any(
        marker in compact
        for marker in (
            "后续推荐",
            "方案调整",
            "方案生成",
            "纳入考虑",
            "作为后续参考",
            "作为后续推荐",
            "作为优先方向",
            "直接排除",
            "可以排除",
            "优先保留",
            "过滤掉",
        )
    )
    has_confirmation_or_choice = any(
        marker in compact
        for marker in (
            "如果确定",
            "如果你确定",
            "如果确认",
            "你现在是想",
            "是否",
            "要不要",
            "想把",
            "作为优先方向",
            "还是只想了解",
        )
    )
    return has_future_reference and has_confirmation_or_choice


async def _recover_confirmable_intent_from_readonly_tool_misroute(
    session_id: str,
    request_context: RequestContext,
    *,
    reply: str,
    tool_context_messages: list[Any] | None,
) -> WSResponse | None:
    """Recover pending intent when a readonly analysis tool swallowed explicit intent.

    The recovery is triggered by the tool path and reply protocol, but entity
    extraction remains delegated to `analyze_volunteer_intent_change` over the
    latest user turn. This keeps the main path model-first without string
    enumerating user utterances.
    """

    if not isinstance(reply, str) or not _tool_calls_are_readonly_explore_or_compare(tool_context_messages):
        return None
    if not _reply_leaves_explicit_intent_as_future_reference(reply):
        return None
    return await _recover_unbacked_intent_confirmation(
        session_id,
        request_context,
        reply=reply,
        force=True,
    )


async def _recover_confirmable_intent_from_no_tool_turn(
    session_id: str,
    request_context: RequestContext,
    *,
    reply: str,
    tool_context_messages: list[Any] | None,
) -> WSResponse | None:
    """Recover explicit intent when the model answered without any tool call.

    No-tool composite recovery is allowed later for true high-side-effect plan
    goals. Ordinary "prefer A / avoid B" updates must first pass through the
    Intent preview path so the user sees a consistent adoption card and does not
    get an accidental plan mutation.
    """

    if list(_iter_tool_call_parts(tool_context_messages)):
        return None
    if not (
        _reply_leaves_explicit_intent_as_future_reference(reply)
        or _reply_looks_like_unbacked_intent_preview(reply)
        or _reply_claims_intent_recorded_without_pending(reply)
        or _reply_looks_like_plan_action_recovery_boundary(reply)
    ):
        return None
    return await _recover_unbacked_intent_confirmation(
        session_id,
        request_context,
        reply=reply,
        force=True,
    )


def _intent_recovery_scope_from_pending_context(request_context: RequestContext) -> str:
    pending = resolve_pending_confirmation(request_context)
    if pending is None or getattr(pending, "kind", None) != "intent_change":
        return "generic"
    execution_payload = getattr(pending, "execution_payload", None)
    payloads: list[dict[str, Any]] = []
    if isinstance(execution_payload, dict):
        merged = execution_payload.get("merged")
        selected_data = execution_payload.get("selectedData")
        if isinstance(merged, dict):
            payloads.append(merged)
        if isinstance(selected_data, dict):
            for selected in selected_data.get("selected") or []:
                if isinstance(selected, dict):
                    payloads.append(selected)
    summary = str(getattr(pending, "preview_summary", "") or "")
    if any("city_intents" in payload for payload in payloads) or any(marker in summary for marker in ("地域", "城市", "省份", "地区")):
        return "region"
    if any("major_intents" in payload for payload in payloads) or "专业" in summary:
        return "major"
    if any("school_intents" in payload for payload in payloads) or any(marker in summary for marker in ("院校", "学校")):
        return "school"
    if any("career_intents" in payload for payload in payloads) or any(marker in summary for marker in ("职业", "就业", "发展方向")):
        return "career_preference"
    return "generic"


async def _resolve_intent_mode_from_message(message_id: Any) -> str:
    if not message_id:
        return "preference"
    try:
        msg_resp = await get_message_by_id(message_id)
        msg_data = (msg_resp or {}).get("data", {})
        content_raw = msg_data.get("content", "")
        content_obj = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
        if isinstance(content_obj, dict):
            intent_mode = str(content_obj.get("intentMode") or "").strip()
            if intent_mode in {"preference", "constraint"}:
                return intent_mode
    except Exception:
        logger.warning("Failed to resolve intent mode from card: message_id=%s", message_id, exc_info=True)
    return "preference"


async def _create_pending_plan_confirmation_response(
    session_id: str,
    confirmation_candidate: dict[str, Any],
) -> WSResponse:
    replaced_pending = await _load_pending_confirmation_state(session_id)
    pending_state = _build_plan_pending_state(
        session_id,
        confirmation_candidate,
        replaced_pending=replaced_pending if isinstance(replaced_pending, dict) else None,
    )
    await _save_pending_confirmation_state(session_id, pending_state)

    action_family = str(confirmation_candidate.get("action_family") or "").strip()
    summary = _plan_confirmation_candidate_summary_for_user(confirmation_candidate)
    unit_kind = _plan_confirmation_unit_kind(confirmation_candidate)
    content = summary or "确认后会执行本次方案调整。"
    is_ordered_group_action = action_family in {"move_ordered_unit", "remove_ordered_unit"} and unit_kind != "志愿"
    if action_family == "move_ordered_unit" and is_ordered_group_action:
        compact_content = _compact_plan_reply_text(content)
        if "不是按单条志愿位置" not in compact_content and "按专业组顺序计算" not in compact_content:
            content = (
                content.rstrip()
                + "\n\n位置说明：这里的“第几个”按专业组顺序计算，不是按单条志愿位置计算；组内专业会保持连续。"
            )
    if action_family == "remove_ordered_unit" and is_ordered_group_action:
        compact_content = _compact_plan_reply_text(content)
        if "组内专业" not in compact_content and "后续专业组会前移" not in compact_content:
            content = content.rstrip() + "\n\n执行后该专业组内的专业会一并移出，后续专业组会前移。"
    execution_payload = pending_state.get("executionPayload")
    intent_payload = execution_payload.get("intentPayload") if isinstance(execution_payload, dict) else None
    intent_summary = _summarize_selected_intent_payload(intent_payload)
    if intent_summary and intent_summary not in content:
        intent_lines = [part.strip() for part in intent_summary.split("；") if part.strip()]
        intent_content = "\n".join(f"- {part}" for part in intent_lines)
        content = (
            content.rstrip()
            + "\n\n同时更新后续报考参考：\n"
            + intent_content
        )
    title_by_action = {
        "add_units": "确认加入方案",
        "remove_units": "确认移出志愿",
        "move_unit": "确认移动志愿",
        "move_ordered_unit": "确认移动志愿" if unit_kind == "志愿" else "确认移动专业组",
        "remove_ordered_unit": "确认移出志愿" if unit_kind == "志愿" else "确认移出专业组",
        "replace_units": "确认替换志愿",
        "sort_ordered_plan": "确认方案排序",
        "regenerate_order": "确认重排方案",
        "generate_plan": "确认生成方案",
    }
    payload = {
        "type": "pendingConfirmationCard",
        "pendingId": pending_state["pendingId"],
        "kind": "plan_mutation",
        "actionFamily": action_family,
        "title": title_by_action.get(action_family) or "请确认本次方案调整",
        "summary": summary or "确认后会执行本次方案调整。",
        "content": content,
        "impactTitle": "确认说明",
        "impact": "完成确认前不会改动当前方案；点“确认执行”最清楚，直接回复“确认/执行”也会按当前有效预览处理。",
        "clickable": True,
        "status": "active",
        "confirmText": "确认执行",
        "cancelText": "暂不执行",
    }
    if isinstance(intent_payload, dict) and intent_payload.get("selected"):
        payload["impact"] = _format_plan_card_intent_impact(intent_payload)
    return WSResponse(
        type="pendingConfirmationCard",
        session_id=session_id,
        content=json.dumps(payload, ensure_ascii=False),
    )


def _ready_fix_proposals(facts: dict[str, Any] | None) -> list[dict[str, Any]]:
    fix_proposals = facts.get("fix_proposals") if isinstance(facts, dict) else None
    proposals = fix_proposals.get("proposals") if isinstance(fix_proposals, dict) else None
    if not isinstance(proposals, list):
        return []
    source = str(
        fix_proposals.get("proposal_source")
        or fix_proposals.get("proposalSource")
        or ""
    ).strip()
    ready: list[dict[str, Any]] = []
    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        proposal_source = str(
            proposal.get("proposal_source")
            or proposal.get("proposalSource")
            or source
            or ""
        ).strip()
        if str(proposal.get("status") or "").strip() != "ready":
            continue
        proposal_id = str(proposal.get("proposal_id") or proposal.get("proposalId") or "").strip()
        if not proposal_id:
            continue
        ready.append(proposal)
    return ready


def _selected_fix_proposal_id(source: dict[str, Any] | None, facts: dict[str, Any] | None) -> str:
    candidates: list[Any] = []
    if isinstance(source, dict):
        candidates.extend(
            [
                source.get("selected_proposal_id"),
                source.get("selectedProposalId"),
                source.get("target_proposal_id"),
                source.get("targetProposalId"),
            ]
        )
    fix_proposals = facts.get("fix_proposals") if isinstance(facts, dict) else None
    if isinstance(fix_proposals, dict):
        candidates.extend(
            [
                fix_proposals.get("selected_proposal_id"),
                fix_proposals.get("selectedProposalId"),
                fix_proposals.get("target_proposal_id"),
                fix_proposals.get("targetProposalId"),
            ]
        )
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text:
            return text
    return ""


def _normalized_fix_proposal_target_strategies(
    target_strategies: set[str] | list[str] | tuple[str, ...] | None,
) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for strategy in (target_strategies or []):
        text = str(strategy or "").strip()
        if text and text not in seen:
            normalized.append(text)
            seen.add(text)
    return normalized


def _normalized_fix_proposal_target_issue_codes(
    target_issue_codes: set[str] | list[str] | tuple[str, ...] | None,
) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for code in (target_issue_codes or []):
        text = str(code or "").strip()
        if text and text not in seen:
            normalized.append(text)
            seen.add(text)
    return normalized


def _fix_proposal_source_issue_codes(proposal: dict[str, Any]) -> set[str]:
    return {
        str(code or "").strip()
        for code in (proposal.get("source_check_codes") or proposal.get("sourceCheckCodes") or [])
        if str(code or "").strip()
    }


def _fix_proposal_matches_target_strategies(
    proposal: dict[str, Any],
    target_strategies: list[str],
) -> bool:
    if not target_strategies:
        return True
    strategy = str(proposal.get("strategy") or "").strip()
    return strategy in set(target_strategies)


def _fix_proposal_matches_target_scope(
    proposal: dict[str, Any],
    target_strategies: list[str],
    target_issue_codes: list[str],
) -> bool:
    if target_strategies and not _fix_proposal_matches_target_strategies(proposal, target_strategies):
        return False
    if target_issue_codes:
        proposal_issue_codes = _fix_proposal_source_issue_codes(proposal)
        if not proposal_issue_codes or not (proposal_issue_codes & set(target_issue_codes)):
            return False
    return bool(target_strategies or target_issue_codes)


def _filter_ready_fix_proposals_by_target_strategies(
    ready: list[dict[str, Any]],
    target_strategies: list[str],
) -> list[dict[str, Any]]:
    if not target_strategies:
        return ready
    return [
        proposal
        for proposal in ready
        if _fix_proposal_matches_target_strategies(proposal, target_strategies)
    ]


def _filter_ready_fix_proposals_by_target_scope(
    ready: list[dict[str, Any]],
    target_strategies: list[str],
    target_issue_codes: list[str],
) -> list[dict[str, Any]]:
    if not target_strategies and not target_issue_codes:
        return ready
    return [
        proposal
        for proposal in ready
        if _fix_proposal_matches_target_scope(proposal, target_strategies, target_issue_codes)
    ]


def _select_ready_fix_proposal(
    facts: dict[str, Any] | None,
    *,
    selected_proposal_id: str = "",
    target_strategies: set[str] | list[str] | tuple[str, ...] | None = None,
    target_issue_codes: set[str] | list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any] | None:
    ready = _ready_fix_proposals(facts)
    if not ready:
        return None
    selected_id = str(selected_proposal_id or "").strip()
    if selected_id:
        for proposal in ready:
            proposal_id = str(proposal.get("proposal_id") or proposal.get("proposalId") or "").strip()
            if proposal_id == selected_id:
                return proposal
        return None
    normalized_strategies = _normalized_fix_proposal_target_strategies(target_strategies)
    normalized_issue_codes = _normalized_fix_proposal_target_issue_codes(target_issue_codes)
    if normalized_strategies or normalized_issue_codes:
        for target_strategy in normalized_strategies:
            for proposal in ready:
                if _fix_proposal_matches_target_scope(
                    proposal,
                    [target_strategy],
                    normalized_issue_codes,
                ):
                    return proposal
        if not normalized_strategies:
            for proposal in ready:
                if _fix_proposal_matches_target_scope(
                    proposal,
                    [],
                    normalized_issue_codes,
                ):
                    return proposal
        return None
    return ready[0]


_FIX_PROPOSAL_REPLY_HINTS_BY_STRATEGY = {
    "adjust_major_group_inner_safety": ("兜底", "更稳", "安全", "专业组", "组内"),
    "sort_by_probability": ("倒挂", "排序", "录取率", "录取概率", "重排"),
    "replace_risk_items": ("替换", "高收费", "中外合作", "学费", "预算"),
    "remove_risk_items": ("移出", "删除", "高收费", "中外合作", "限报"),
    "fill_probability_gap": ("断层", "梯度", "录取率", "录取概率"),
    "rebalance_tier_ratio": ("冲稳保", "配比", "比例", "偏冲", "保底"),
    "add_safety_items": ("保底", "兜底", "更稳", "安全"),
    "fill_missing_count": ("数量", "补足", "补齐"),
}


def _select_ready_fix_proposal_for_reply(
    facts: dict[str, Any] | None,
    *,
    reply: str,
    target_strategies: set[str] | list[str] | tuple[str, ...] | None = None,
    target_issue_codes: set[str] | list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any] | None:
    selected = _select_ready_fix_proposal(
        facts,
        target_strategies=target_strategies,
        target_issue_codes=target_issue_codes,
    )
    ready = _filter_ready_fix_proposals_by_target_scope(
        _ready_fix_proposals(facts),
        _normalized_fix_proposal_target_strategies(target_strategies),
        _normalized_fix_proposal_target_issue_codes(target_issue_codes),
    )
    if len(ready) <= 1:
        return selected
    compact_reply = _compact_plan_reply_text(reply)
    if not compact_reply:
        return selected
    best: tuple[int, int, dict[str, Any]] | None = None
    for index, proposal in enumerate(ready):
        strategy = str(proposal.get("strategy") or "").strip()
        fields = " ".join(
            str(proposal.get(key) or "")
            for key in ("title", "summary", "impact")
        )
        fields += " " + _FIX_PROPOSAL_STRATEGY_TEXT.get(strategy, "")
        hints = list(_FIX_PROPOSAL_REPLY_HINTS_BY_STRATEGY.get(strategy, ()))
        hints.extend(re.findall(r"[\u4e00-\u9fff]{2,8}", fields))
        seen: set[str] = set()
        score = 0
        for hint in hints:
            text = str(hint or "").strip()
            if len(text) < 2 or text in seen:
                continue
            seen.add(text)
            if text in compact_reply:
                score += 1
        if score <= 0:
            continue
        candidate = (score, -index, proposal)
        if best is None or candidate[:2] > best[:2]:
            best = candidate
    if best is not None:
        return best[2]
    return selected


def _compact_ready_fix_proposals_for_selection(
    facts: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for proposal in _ready_fix_proposals(facts):
        proposal_id = str(proposal.get("proposal_id") or proposal.get("proposalId") or "").strip()
        if not proposal_id:
            continue
        candidates.append(
            {
                "proposalId": proposal_id,
                "strategy": str(proposal.get("strategy") or "").strip(),
                "title": _normalize_fix_proposal_user_text(str(proposal.get("title") or "").strip()),
                "summary": _normalize_fix_proposal_user_text(str(proposal.get("summary") or "").strip()),
                "impact": _normalize_fix_proposal_user_text(str(proposal.get("impact") or "").strip()),
                "sourceCheckCodes": [
                    str(code or "").strip()
                    for code in (proposal.get("source_check_codes") or proposal.get("sourceCheckCodes") or [])
                    if str(code or "").strip()
                ],
                "actionSummaries": [
                    _normalize_fix_proposal_user_text(str(item or "").strip())
                    for item in (proposal.get("action_summaries") or proposal.get("actionSummaries") or [])
                    if str(item or "").strip()
                ][:3],
            }
        )
    return candidates[:8]


async def _select_ready_fix_proposal_for_user_goal(
    facts: dict[str, Any] | None,
    *,
    content: str,
    reply: str,
    request_context: RequestContext,
    target_strategies: set[str] | list[str] | tuple[str, ...] | None = None,
    target_issue_codes: set[str] | list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any] | None:
    normalized_strategies = _normalized_fix_proposal_target_strategies(target_strategies)
    normalized_issue_codes = _normalized_fix_proposal_target_issue_codes(target_issue_codes)
    ready = _filter_ready_fix_proposals_by_target_scope(
        _ready_fix_proposals(facts),
        normalized_strategies,
        normalized_issue_codes,
    )
    if len(ready) <= 1:
        if normalized_strategies or normalized_issue_codes:
            return _select_ready_fix_proposal(
                facts,
                target_strategies=normalized_strategies,
                target_issue_codes=normalized_issue_codes,
            )
        return _select_ready_fix_proposal(
            facts,
            target_strategies=target_strategies,
            target_issue_codes=target_issue_codes,
        )
    selected = _select_ready_fix_proposal_for_reply(
        facts,
        reply=reply,
        target_strategies=target_strategies,
        target_issue_codes=target_issue_codes,
    )
    candidates = _compact_ready_fix_proposals_for_selection(facts)
    if len(candidates) <= 1:
        return selected
    try:
        decision = await select_fix_proposal_candidate(
            latest_utterance=content,
            assistant_reply=reply,
            candidates=candidates,
            request_context=request_context,
        )
    except Exception:
        logger.warning("Fix proposal candidate arbitration failed", exc_info=True)
        return selected
    confidence = float(getattr(decision, "confidence", 0.0) or 0.0)
    proposal_id = str(getattr(decision, "proposalId", "") or "").strip()
    if proposal_id and confidence >= _SEMANTIC_PLAN_ACTION_CONFIDENCE_THRESHOLD:
        matched = _select_ready_fix_proposal(facts, selected_proposal_id=proposal_id)
        if matched is not None and (
            (not normalized_strategies and not normalized_issue_codes)
            or _fix_proposal_matches_target_scope(
                matched,
                normalized_strategies,
                normalized_issue_codes,
            )
        ):
            return matched
    if normalized_strategies or normalized_issue_codes:
        return None
    return selected


async def _select_ready_fix_proposal_by_user_goal_arbitration(
    facts: dict[str, Any] | None,
    *,
    content: str,
    reply: str,
    request_context: RequestContext,
) -> dict[str, Any] | None:
    if len(_ready_fix_proposals(facts)) <= 1:
        return None
    candidates = _compact_ready_fix_proposals_for_selection(facts)
    if len(candidates) <= 1:
        return None
    try:
        decision = await select_fix_proposal_candidate(
            latest_utterance=content,
            assistant_reply=reply,
            candidates=candidates,
            request_context=request_context,
        )
    except Exception:
        logger.warning("Fix proposal candidate arbitration failed", exc_info=True)
        return None
    confidence = float(getattr(decision, "confidence", 0.0) or 0.0)
    proposal_id = str(getattr(decision, "proposalId", "") or "").strip()
    if not proposal_id or confidence < _SEMANTIC_PLAN_ACTION_CONFIDENCE_THRESHOLD:
        return None
    return _select_ready_fix_proposal(facts, selected_proposal_id=proposal_id)


async def _user_requested_fix_proposal_preview(
    *,
    content: str,
    request_context: RequestContext,
    latest_plan_result: dict[str, Any],
) -> bool:
    facts = latest_plan_result.get("facts") if isinstance(latest_plan_result.get("facts"), dict) else {}
    if not _ready_fix_proposals(facts):
        return False
    context = _latest_plan_semantic_route_context(
        [
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="execute_plan_action",
                        content=json.dumps(latest_plan_result, ensure_ascii=False, default=str),
                        tool_call_id="current-fix-proposal-preview-request-check",
                    )
                ]
            )
        ]
    )
    if not context:
        return False
    try:
        decision = await classify_plan_semantic_action(
            content,
            request_context=request_context,
            recent_plan_context=context,
        )
    except Exception:
        logger.warning("Fix proposal preview request check failed", exc_info=True)
        return False
    action_family = str(getattr(decision, "actionFamily", "") or "").strip()
    confidence = float(getattr(decision, "confidence", 0.0) or 0.0)
    return action_family == "preview_fix_proposal" and confidence >= _SEMANTIC_PLAN_ACTION_CONFIDENCE_THRESHOLD


def _first_ready_fix_proposal(facts: dict[str, Any] | None) -> dict[str, Any] | None:
    return _select_ready_fix_proposal(facts)


def _ready_fix_proposal_id_for_strategies(
    facts: dict[str, Any] | None,
    target_strategies: set[str] | list[str] | tuple[str, ...] | None,
) -> str:
    if not [
        str(strategy or "").strip()
        for strategy in (target_strategies or [])
        if str(strategy or "").strip()
    ]:
        return ""
    proposal = _select_ready_fix_proposal(
        facts,
        target_strategies=target_strategies,
    )
    if not isinstance(proposal, dict):
        return ""
    return str(proposal.get("proposal_id") or proposal.get("proposalId") or "").strip()


def _fix_proposal_payload_has_explicit_target(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    selected_id = str(
        payload.get("selected_proposal_id")
        or payload.get("selectedProposalId")
        or payload.get("target_proposal_id")
        or payload.get("targetProposalId")
        or ""
    ).strip()
    if selected_id:
        return True
    for key in ("target_strategies", "targetStrategies", "target_issue_codes", "targetIssueCodes"):
        values = payload.get(key)
        if isinstance(values, str):
            if values.strip():
                return True
            continue
        if any(str(item or "").strip() for item in (values or [])):
            return True
    return False


def _filter_target_issue_codes_for_context(
    issue_codes: list[str],
    context: dict[str, Any] | None,
) -> list[str]:
    available: set[str] = set()
    fix_facts = (context or {}).get("fixProposals")
    proposals = fix_facts.get("proposals") if isinstance(fix_facts, dict) else []
    for proposal in proposals or []:
        if not isinstance(proposal, dict):
            continue
        for code in proposal.get("sourceCheckCodes") or proposal.get("source_check_codes") or []:
            text = str(code or "").strip()
            if text:
                available.add(text)
    if not available:
        return issue_codes
    result: list[str] = []
    for code in issue_codes:
        text = str(code or "").strip()
        if text and text in available and text not in result:
            result.append(text)
    return result


async def _infer_plan_target_issue_codes_from_context(
    *,
    content: str,
    request_context: RequestContext,
    recent_plan_context: dict[str, Any] | None,
    expected_action_family: str,
    target_strategies: list[str],
) -> list[str]:
    if not recent_plan_context:
        return []
    fix_facts = recent_plan_context.get("fixProposals")
    if not isinstance(fix_facts, dict) or not isinstance(fix_facts.get("proposals"), list):
        return []
    try:
        decision = await classify_plan_semantic_action(
            content,
            request_context=request_context,
            recent_plan_context=recent_plan_context,
        )
    except Exception:
        logger.warning("Plan target issue-code inference failed", exc_info=True)
        return []
    action_family = str(getattr(decision, "actionFamily", "") or "").strip()
    if action_family not in {expected_action_family, "preview_fix_proposal", "analyze_adjustment"}:
        return []
    confidence = float(getattr(decision, "confidence", 0.0) or 0.0)
    if confidence < _SEMANTIC_PLAN_ACTION_CONFIDENCE_THRESHOLD:
        return []
    inferred_strategies = [
        str(strategy or "").strip()
        for strategy in list(getattr(decision, "targetStrategies", []) or [])
        if str(strategy or "").strip()
    ]
    if target_strategies and inferred_strategies and not (set(target_strategies) & set(inferred_strategies)):
        return []
    issue_codes = [
        str(code or "").strip()
        for code in list(getattr(decision, "targetIssueCodes", []) or [])
        if str(code or "").strip()
    ]
    return _filter_target_issue_codes_for_context(issue_codes, recent_plan_context)


async def _infer_fix_proposal_target_strategies(
    *,
    content: str,
    request_context: RequestContext,
    latest_plan_result: dict[str, Any],
) -> list[str]:
    """Infer which ready repair proposal a preview should attach to.

    This is a semantic arbitration over already-generated backend proposals. It
    does not route user text to a new action and it does not execute anything.
    """

    strategies, _issue_codes, _has_explicit_target = await _infer_fix_proposal_target_scope(
        content=content,
        request_context=request_context,
        latest_plan_result=latest_plan_result,
    )
    return strategies


async def _infer_fix_proposal_target_scope(
    *,
    content: str,
    request_context: RequestContext,
    latest_plan_result: dict[str, Any],
) -> tuple[list[str], list[str], bool]:
    """Infer the user's repair target and whether that target was explicit.

    Non-empty strategy/issue-code lists are used to select the matching ready
    proposal. The boolean distinguishes "no explicit target" from "explicit
    target exists, but no ready proposal can satisfy it"; the latter must not
    fall back to the first unrelated ready proposal.
    """

    explicit_targets = _normalized_fix_proposal_target_strategies(
        latest_plan_result.get("target_strategies")
        or latest_plan_result.get("targetStrategies")
        or []
    )
    explicit_issue_codes = _normalized_fix_proposal_target_issue_codes(
        latest_plan_result.get("target_issue_codes")
        or latest_plan_result.get("targetIssueCodes")
        or []
    )
    if explicit_targets or explicit_issue_codes:
        return explicit_targets, explicit_issue_codes, True
    facts = latest_plan_result.get("facts") if isinstance(latest_plan_result.get("facts"), dict) else {}
    ready = _ready_fix_proposals(facts)
    if not ready:
        return [], [], False
    if _selected_fix_proposal_id(latest_plan_result, facts):
        return [], [], False
    context = _latest_plan_semantic_route_context(
        [
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="execute_plan_action",
                        content=json.dumps(latest_plan_result, ensure_ascii=False, default=str),
                        tool_call_id="current-fix-proposal-preview",
                    )
                ]
            )
        ]
    )
    if not context:
        return [], [], False
    try:
        decision = await classify_plan_semantic_action(
            content,
            request_context=request_context,
            recent_plan_context=context,
        )
    except Exception:
        logger.warning(
            "Fix proposal target strategy inference failed",
            exc_info=True,
        )
        return [], [], False
    if str(getattr(decision, "actionFamily", "") or "").strip() not in {
        "preview_fix_proposal",
        "review_plan",
        "analyze_adjustment",
    }:
        return [], [], False
    confidence = float(getattr(decision, "confidence", 0.0) or 0.0)
    if confidence < _SEMANTIC_PLAN_ACTION_CONFIDENCE_THRESHOLD:
        return [], [], False
    strategies = [
        str(strategy or "").strip()
        for strategy in list(getattr(decision, "targetStrategies", []) or [])
        if str(strategy or "").strip()
    ]
    issue_codes = [
        str(code or "").strip()
        for code in list(getattr(decision, "targetIssueCodes", []) or [])
        if str(code or "").strip()
    ]
    if not strategies and not issue_codes:
        return [], [], False
    proposal_strategies = {
        str(proposal.get("strategy") or "").strip()
        for proposal in ready
        if str(proposal.get("strategy") or "").strip()
    }
    proposal_issue_codes = {
        code
        for proposal in ready
        for code in _fix_proposal_source_issue_codes(proposal)
    }
    matched_strategies = [strategy for strategy in strategies if strategy in proposal_strategies]
    matched_issue_codes = [code for code in issue_codes if code in proposal_issue_codes]
    return matched_strategies, matched_issue_codes, True


def _build_fix_proposal_pending_state(
    session_id: str,
    proposal: dict[str, Any],
    *,
    source_version_guard: int,
    proposal_source: str = "review_check",
    user_goal_request: dict[str, Any] | None = None,
    intent_payload: dict[str, Any] | None = None,
    replaced_pending: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pending_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    proposal_id = str(proposal.get("proposal_id") or proposal.get("proposalId") or "").strip()
    title = _normalize_fix_proposal_user_text(str(proposal.get("title") or "处理方案提醒").strip())
    summary = str(proposal.get("summary") or proposal.get("impact") or title).strip()
    state = {
        "type": "pendingConfirmation",
        "pendingId": pending_id,
        "sessionId": str(session_id),
        "kind": "plan_mutation",
        "status": "active",
        "actionFamily": "apply_fix_proposal",
        "summary": summary or title,
        "userGoal": title,
        "executionPayload": {
            "toolName": "apply_planning_fix_proposal",
            "proposalId": proposal_id,
            "proposalSource": proposal_source or "review_check",
            "sourceVersionGuard": source_version_guard,
            "strategy": str(proposal.get("strategy") or "").strip(),
            "proposalTitle": title,
            "proposalSummary": summary,
            "regenerateOrderedPlan": True,
            "rerunReview": True,
        },
        "createdAt": now,
        "updatedAt": now,
        "sourceBackendVersion": source_version_guard,
    }
    if user_goal_request:
        state["executionPayload"]["userGoalRequest"] = user_goal_request
    if isinstance(intent_payload, dict) and intent_payload.get("selected"):
        state["executionPayload"]["intentPayload"] = intent_payload
    if replaced_pending and replaced_pending.get("pendingId"):
        state["replacesPendingId"] = replaced_pending.get("pendingId")
    return state


def _normalize_fix_proposal_user_text(text: str) -> str:
    return str(text or "").replace("修复建议", "处理建议").replace("修复", "处理").strip()


def _format_fix_proposal_card_content(
    proposal: dict[str, Any],
    *,
    intent_payload: dict[str, Any] | None = None,
) -> str:
    def clean(value: Any) -> str:
        return _normalize_user_facing_terms(_normalize_fix_proposal_user_text(str(value or "").strip()))

    lines: list[str] = []
    intent_summary = _summarize_selected_intent_payload(intent_payload)
    if intent_summary:
        intent_parts = [part.strip() for part in intent_summary.split("；") if part.strip()]
        if intent_parts:
            lines.append(f"- 采纳内容：{'；'.join(intent_parts[:3])}")
            if len(intent_parts) > 3:
                lines.append(f"- 另有 {len(intent_parts) - 3} 条，确认后会一并作为后续参考")
    title = clean(proposal.get("title"))
    summary = clean(proposal.get("summary"))
    impact = clean(proposal.get("impact"))
    action_summaries = [
        clean(item)
        for item in (proposal.get("action_summaries") or proposal.get("actionSummaries") or [])
        if clean(item)
    ]
    deduped_action_summaries: list[str] = []
    seen_action_summaries: set[str] = set()
    title_compact = _compact_plan_reply_text(title)
    summary_compact = _compact_plan_reply_text(summary)
    for action_summary in action_summaries:
        compact = _compact_plan_reply_text(action_summary)
        if compact and (
            compact == title_compact
            or compact == summary_compact
            or compact in title_compact
            or compact in summary_compact
        ):
            continue
        if compact in seen_action_summaries:
            continue
        seen_action_summaries.add(compact)
        deduped_action_summaries.append(action_summary)
    if title:
        lines.append(f"- 处理内容：{title}")
    if summary and summary != title:
        lines.append(f"- 对应提醒：{summary}")
    if deduped_action_summaries:
        lines.append(f"- 调整方式：{'；'.join(deduped_action_summaries[:2])}")
    if impact:
        lines.append(f"- 影响范围：{impact}")
    return "\n".join(lines).strip() or "确认后会按这条处理建议调整当前方案。"


def _fix_proposal_pending_primary_reply(proposal: dict[str, Any]) -> str:
    title = _normalize_fix_proposal_user_text(str(proposal.get("title") or "这条处理建议").strip())
    summary = _normalize_fix_proposal_user_text(str(proposal.get("summary") or "").strip()).strip("。；; ")
    lines = [f"已列出这条调整预览：{title}。"]
    if summary and summary != title:
        lines.extend(["", f"这条建议主要是：{summary}。"])
    lines.extend(
        [
            "",
            "具体调整内容在下面卡片里。确认前不会改动当前方案；点“确认执行”后，我会按这条建议处理，并重新刷新方案和审查结果。",
        ]
    )
    return _sanitize_reply_for_user("\n".join(lines))


async def _create_pending_fix_proposal_confirmation_response(
    session_id: str,
    proposal: dict[str, Any],
    *,
    source_version_guard: int,
    proposal_source: str = "review_check",
    user_goal_request: dict[str, Any] | None = None,
    intent_payload: dict[str, Any] | None = None,
) -> WSResponse | None:
    proposal_id = str(proposal.get("proposal_id") or proposal.get("proposalId") or "").strip()
    if not proposal_id or source_version_guard <= 0:
        return None
    replaced_pending = await _load_pending_confirmation_state(session_id)
    pending_state = _build_fix_proposal_pending_state(
        session_id,
        proposal,
        source_version_guard=source_version_guard,
        proposal_source=proposal_source,
        user_goal_request=user_goal_request,
        intent_payload=intent_payload,
        replaced_pending=replaced_pending if isinstance(replaced_pending, dict) else None,
    )
    await _save_pending_confirmation_state(session_id, pending_state)
    title = _normalize_user_facing_terms(
        _normalize_fix_proposal_user_text(str(proposal.get("title") or "确认处理这条方案提醒").strip())
    )
    summary = _normalize_user_facing_terms(str(pending_state.get("summary") or title))
    card_payload = {
        "type": "pendingConfirmationCard",
        "pendingId": pending_state["pendingId"],
        "kind": "plan_mutation",
        "actionFamily": "apply_fix_proposal",
        "title": "确认处理方案提醒",
        "summary": summary,
        "content": _format_fix_proposal_card_content(proposal, intent_payload=intent_payload),
        "impactTitle": "确认说明",
        "impact": (
            _format_plan_card_intent_impact(intent_payload)
            if isinstance(intent_payload, dict) and intent_payload.get("selected")
            else "确认前不会改动当前方案；确认后会按这条处理建议调整方案，并重新刷新方案和审查结果。"
        ),
        "proposalId": proposal_id,
        "strategy": str(proposal.get("strategy") or "").strip(),
        "clickable": True,
        "status": "active",
        "confirmText": "确认执行",
        "cancelText": "暂不执行",
    }
    return WSResponse(
        type="pendingConfirmationCard",
        session_id=session_id,
        content=json.dumps(card_payload, ensure_ascii=False),
    )


def _plan_confirmation_unit_kind(confirmation_candidate: dict[str, Any]) -> str:
    plan_payload = confirmation_candidate.get("plan_payload")
    if not isinstance(plan_payload, str) or not plan_payload.strip():
        return ""
    try:
        payload = json.loads(plan_payload)
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    facts = payload.get("facts") if isinstance(payload.get("facts"), dict) else {}
    unit_kind = str(facts.get("unit_kind") or facts.get("unitKind") or "").strip()
    return unit_kind if unit_kind in {"志愿", "专业组"} else ""


_EXECUTE_PLAN_ACTION_REFRESH_FAMILIES = {
    "review_plan",
    "generate_plan",
    "add_units",
    "remove_units",
    "move_unit",
    "move_ordered_unit",
    "remove_ordered_unit",
    "replace_units",
    "sort_ordered_plan",
    "regenerate_order",
}

_EXECUTE_PLAN_ACTION_VIEW_FAMILIES = {
    "query_state",
    "query_ordered",
    "query_candidates",
}
_LOW_PRIORITY_LOG_ACTION_FAMILIES = {
    "query_state",
    "query_ordered",
    "query_candidates",
}


def _extract_execute_plan_action_family(part: ToolCallPart) -> str | None:
    if part.tool_name != "execute_plan_action":
        return None
    args = _parse_tool_call_args(part.args)
    plan_payload = args.get("plan_payload")
    if not isinstance(plan_payload, str) or not plan_payload.strip():
        return None
    try:
        payload = json.loads(plan_payload)
    except Exception:
        logger.warning("Failed to parse execute_plan_action payload for workspace refresh inference", exc_info=True)
        return None
    return str(payload.get("action_family") or "").strip() or None


def _extract_execute_plan_payload(part: ToolCallPart) -> dict[str, Any] | None:
    if part.tool_name != "execute_plan_action":
        return None
    args = _parse_tool_call_args(part.args)
    plan_payload = args.get("plan_payload")
    if not isinstance(plan_payload, str) or not plan_payload.strip():
        return None
    try:
        payload = json.loads(plan_payload)
    except Exception:
        logger.warning("Failed to parse execute_plan_action payload", exc_info=True)
        return None
    return payload if isinstance(payload, dict) else None


def _parse_tool_return_json(content: Any) -> dict[str, Any] | None:
    if isinstance(content, dict):
        return content
    if isinstance(content, str) and content.strip():
        try:
            data = json.loads(content)
        except Exception:
            return None
        return data if isinstance(data, dict) else None
    return None


def _pending_card_kind(card: WSResponse | None) -> str:
    payload = _parse_tool_return_json(getattr(card, "content", "") or "") if card is not None else None
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("kind") or "").strip()


def _build_tuition_budget_no_plan_reply(max_tuition_per_year: int) -> str:
    return _sanitize_reply_for_user(
        "\n".join(
            [
                f"可以按每年不超过 {max_tuition_per_year} 元这个预算来规划，但现在还没有正式方案，这轮先不会改动方案。",
                "",
                "- 等方案生成后，我会先找出学费超过预算的志愿，再判断是保留提醒、替换，还是需要你放宽预算或重新取舍。",
                "- 如果候选里没有合适补位，会直接说明缺口，不会强行凑数。",
                "- 当前方案不会因为这轮回复而改变。",
            ]
        )
    )


def _max_tuition_from_user_goal_request(user_goal_request: dict[str, Any] | None) -> int:
    if not isinstance(user_goal_request, dict):
        return 0
    goal_type = str(user_goal_request.get("goalType") or user_goal_request.get("goal_type") or "").strip()
    if goal_type != "tuition_budget_scope":
        return 0
    context = user_goal_request.get("context")
    if not isinstance(context, dict):
        return 0
    return _as_int(context.get("maxTuitionPerYear") or context.get("max_tuition_per_year"))


def _extract_recent_intent_analysis_payload(messages: list[Any] | None) -> dict[str, Any] | None:
    """Return the latest structured Intent analysis payload from persisted history.

    The user-facing chat text intentionally omits internal selection values, but
    follow-up analysis such as "这个偏好会影响当前方案吗" still needs the exact
    prior intent facts. Persisted pydantic-ai history keeps tool returns, so we
    recover from that structured source instead of guessing from natural text.
    """
    for part in reversed(_iter_tool_return_parts(messages)):
        if part.tool_name not in _INTENT_PREVIEW_TOOL_NAMES:
            continue
        data = _parse_tool_return_json(part.content)
        if not data:
            continue
        if any(key in data for key in ("items", "existingItems", "impactAnalysis", "impactText")):
            return data
    return None


def _extract_confirmable_intent_payload_from_interest_tool(messages: list[Any] | None) -> dict[str, Any] | None:
    """Recover a structured intent preview carried by a misrouted Explore tool."""

    for part in reversed(_iter_tool_return_parts(messages)):
        if part.tool_name not in _INTENT_INTEREST_ANALYSIS_TOOL_NAMES:
            continue
        data = _parse_tool_return_json(part.content)
        if not isinstance(data, dict):
            continue
        if str(data.get("analysisStage") or "").strip() != "confirmed":
            continue
        if str(data.get("status") or "").strip() not in {"ready", "existing_only"}:
            continue
        items = data.get("items")
        if not isinstance(items, list) or not any(isinstance(item, dict) and item.get("selected") is not False for item in items):
            continue
        return data
    return None


def _extract_execute_plan_action_refresh_targets(part: ToolReturnPart) -> list[str]:
    if part.tool_name != "execute_plan_action":
        return []
    data = _parse_tool_return_json(part.content)
    if not data:
        return []
    action_family = str(data.get("action_family") or "").strip()
    if action_family not in _EXECUTE_PLAN_ACTION_REFRESH_FAMILIES:
        return []
    result_kind = str(data.get("result_kind") or "").strip()
    if data.get("applied") is not True and (action_family, result_kind) != ("review_plan", "review_result"):
        return []
    if result_kind == "error":
        return []
    targets = data.get("workspace_refresh_targets")
    if not isinstance(targets, list):
        return []
    return _dedupe_workspace_targets([str(target) for target in targets])


def _extract_execute_plan_action_view_targets(part: ToolReturnPart) -> list[str]:
    """Extract workspace targets from query (read-only) actions — these guide the
    frontend to open a panel without triggering a data re-fetch."""
    if part.tool_name != "execute_plan_action":
        return []
    data = _parse_tool_return_json(part.content)
    if not data:
        return []
    action_family = str(data.get("action_family") or "").strip()
    if action_family not in _EXECUTE_PLAN_ACTION_VIEW_FAMILIES:
        return []
    if action_family == "query_candidates":
        return []
    targets = data.get("workspace_refresh_targets")
    if not isinstance(targets, list):
        return []
    return _dedupe_workspace_targets([str(target) for target in targets])


def _select_conversation_action_family(tool_returns: list[ToolReturnPart]) -> str | None:
    """Choose the action family that best describes the completed turn.

    A plan turn may briefly read state before producing a mutation preview. For
    observability, report the last non-query plan action instead of the first
    low-signal query action.
    """
    families: list[str] = []
    for part in tool_returns:
        data = _parse_tool_return_json(part.content)
        if not data:
            continue
        action_family = str(data.get("action_family") or "").strip()
        if action_family:
            families.append(action_family)
    if not families:
        return None
    for action_family in reversed(families):
        if action_family not in _LOW_PRIORITY_LOG_ACTION_FAMILIES:
            return action_family
    return families[-1]


def _latest_readonly_plan_execution_result(messages: list[Any] | None) -> dict[str, Any] | None:
    readonly_pairs = {
        ("review_plan", "review_result"),
        ("analyze_adjustment", "adjustment_analysis"),
        ("query_state", "status_overview"),
    }
    for part in reversed(_iter_tool_return_parts(messages)):
        if part.tool_name != "execute_plan_action":
            continue
        data = _parse_tool_return_json(part.content)
        if not data:
            continue
        action_family = str(data.get("action_family") or "").strip()
        result_kind = str(data.get("result_kind") or "").strip()
        if (action_family, result_kind) in readonly_pairs:
            return data
    return None


def _latest_review_plan_result(messages: list[Any] | None) -> dict[str, Any] | None:
    for part in reversed(_iter_tool_return_parts(messages)):
        if part.tool_name != "execute_plan_action":
            continue
        data = _parse_tool_return_json(part.content)
        if not isinstance(data, dict):
            continue
        action_family = str(data.get("action_family") or "").strip()
        result_kind = str(data.get("result_kind") or "").strip()
        if action_family == "review_plan" and result_kind == "review_result":
            return data
    return None


def _latest_readonly_plan_query_reply(messages: list[Any] | None) -> str | None:
    for part in reversed(_iter_tool_return_parts(messages)):
        if part.tool_name != "query_volunteer_plan":
            continue
        data = _parse_tool_return_json(part.content)
        if data:
            for key in ("reply", "summary", "message"):
                value = str(data.get(key) or "").strip()
                if value:
                    return _sanitize_reply_for_user(_normalize_user_facing_terms(value))
            continue
        text = str(part.content or "").strip()
        if text:
            return _sanitize_reply_for_user(_normalize_user_facing_terms(text))
    return None


def _compact_readonly_plan_query_reply(reply: str | None) -> str:
    text = _sanitize_reply_for_user(_normalize_user_facing_terms(str(reply or "").strip()))
    if not text:
        return ""
    match = re.search(
        r"(?P<title>当前方案|当前排序方案|当前已加入方案|候选)里共命中了\s*"
        r"(?P<count>\d+)\s*条(?:符合[“\"](?P<condition>[^”\"]+)[”\"]|和[“\"]?(?P<keyword>[^”\"。]+)[”\"]?相关的(?:志愿|机会))",
        text,
    )
    if match:
        title = match.group("title") or "当前方案"
        count = match.group("count")
        condition = match.group("condition") or match.group("keyword") or "这个条件"
        examples_text = text.split("：", 1)[1] if "：" in text else ""
        examples = [item.strip(" ；;。") for item in re.split(r"；|;", examples_text) if item.strip()]
        scope_label = "候选里" if title == "候选" else "当前方案里"
        item_label = "机会" if title == "候选" else "志愿"
        lines = [f"我查了一下，{scope_label}有 {count} 条和“{condition}”相关的{item_label}。"]
        if examples:
            lines.append("比较典型的有：")
            for item in examples[:3]:
                lines.append(f"- {item}")
        lines.append("这类结果建议重点看学费、录取率、培养方式和是否真的能接受；如果要调整，我会先给你一版调整预览，确认前不会改方案。")
        return "\n".join(lines)
    if len(text) <= 260:
        return text
    return f"{text[:260].rstrip()}...\n\n这只是当前查询到的局部结果；如果要继续调整，我会先给你一版调整预览，确认前不会改方案。"


def _latest_readonly_explore_reply(messages: list[Any] | None) -> str | None:
    for part in reversed(_iter_tool_return_parts(messages)):
        if part.tool_name not in _INTENT_INTEREST_ANALYSIS_TOOL_NAMES and part.tool_name not in _INTENT_PREVIEW_TOOL_NAMES:
            continue
        data = _parse_tool_return_json(part.content)
        if data:
            if (
                part.tool_name in _INTENT_PREVIEW_TOOL_NAMES
                and str(data.get("analysisStage") or "").strip() != "interest"
            ):
                continue
            for key in ("message", "summary", "reply", "state_summary"):
                value = str(data.get(key) or "").strip()
                if value:
                    return _sanitize_reply_for_user(_normalize_user_facing_terms(value))
            continue
        text = str(part.content or "").strip()
        if text:
            return _sanitize_reply_for_user(_normalize_user_facing_terms(text))
    return None


def _latest_readonly_tool_reply(messages: list[Any] | None) -> str | None:
    """Return substantive read-only tool content for unbacked-confirmation guards."""
    query_reply = _latest_readonly_plan_query_reply(messages)
    if query_reply:
        return _compact_readonly_plan_query_reply(query_reply)

    explore_reply = _latest_readonly_explore_reply(messages)
    if explore_reply:
        return explore_reply

    for part in reversed(_iter_tool_return_parts(messages)):
        if part.tool_name != "answer_admission_policy_question":
            continue
        data = _parse_tool_return_json(part.content)
        if data:
            for key in ("reply", "summary", "message", "answer"):
                value = str(data.get(key) or "").strip()
                if value:
                    return _sanitize_reply_for_user(_normalize_user_facing_terms(value))
            continue
        text = str(part.content or "").strip()
        if text:
            return _sanitize_reply_for_user(_normalize_user_facing_terms(text))
    return None


def _reply_contains_readonly_plan_query_facts(reply: str) -> bool:
    compact = _compact_plan_reply_text(reply)
    if not compact:
        return False
    return any(
        marker in compact
        for marker in (
            "当前方案里共命中",
            "候选里共命中",
            "当前方案里暂时没有命中",
            "候选里暂时没有命中",
            "下面仅展示",
            "符合“",
        )
    )


def _summarize_tool_calls_for_observability(
    tool_calls: list[ToolCallPart],
    tool_returns: list[ToolReturnPart],
) -> list[dict[str, Any]]:
    """Build compact tool-call metadata for structured logs.

    Persisted history keeps full tool args/results. This summary only carries
    route/action/result fields needed by effect/perf reports.
    """
    returns_by_call_id: dict[str, dict[str, Any]] = {}
    for part in tool_returns:
        call_id = str(part.tool_call_id or "")
        if not call_id:
            continue
        data = _parse_tool_return_json(part.content)
        if data:
            returns_by_call_id[call_id] = data

    summarized: list[dict[str, Any]] = []
    for part in tool_calls:
        call_id = str(part.tool_call_id or "")
        args = _parse_tool_call_args(part.args)
        returned = returns_by_call_id.get(call_id) or {}
        item: dict[str, Any] = {"name": part.tool_name}
        if call_id:
            item["toolCallId"] = call_id

        action_family = str(args.get("action_family") or returned.get("action_family") or "").strip()
        stage = str(args.get("current_stage") or returned.get("stage") or "").strip()
        if part.tool_name == "execute_plan_action":
            raw_payload = args.get("plan_payload")
            if isinstance(raw_payload, str) and raw_payload.strip():
                try:
                    plan_payload = json.loads(raw_payload)
                except Exception:
                    plan_payload = {}
                if isinstance(plan_payload, dict):
                    action_family = action_family or str(plan_payload.get("action_family") or "").strip()
                    stage = stage or str(plan_payload.get("stage") or "").strip()

        if action_family:
            item["actionFamily"] = action_family
        if stage:
            item["stage"] = stage

        result_kind = str(returned.get("result_kind") or "").strip()
        if result_kind:
            item["resultKind"] = result_kind
        if "applied" in returned:
            item["applied"] = bool(returned.get("applied"))
        message_code = str(returned.get("messageCode") or "").strip()
        if message_code:
            item["messageCode"] = message_code
        if returned:
            item["success"] = result_kind != "error"

        summarized.append(item)
    return summarized


def _summarize_full_agent_tool_trial(tool_names: list[str]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for name in tool_names:
        if not name:
            continue
        counts[name] = counts.get(name, 0) + 1
    repeated = [name for name, count in counts.items() if count > 1]
    return {
        "toolNames": list(tool_names),
        "toolNameCounts": counts,
        "repeatedToolNames": repeated,
        "hasRepeatedToolCalls": bool(repeated),
        "hasToolCalls": bool(tool_names),
    }


def _tool_calls_include_plan_workspace_refresh(messages: list[Any] | None) -> list[str]:
    result_targets: list[str] = []
    has_execute_plan_return = False
    for part in _iter_tool_return_parts(messages):
        if part.tool_name == "execute_plan_action":
            has_execute_plan_return = True
        result_targets.extend(_extract_execute_plan_action_refresh_targets(part))
    if result_targets:
        return _dedupe_workspace_targets(result_targets)
    if has_execute_plan_return:
        return []

    mutating_tool_names = {
        "select_planning_ordered_items",
        "remove_planning_ordered_items",
        "generate_planning_ordered_plan",
        "generate_planning_initial_plan",
        "move_planning_ordered_item",
    }
    execute_plan_action_targets = {
        "review_plan": [],
        "generate_plan": ["ordered"],
        "add_units": ["ordered"],
        "remove_units": ["ordered"],
        "move_unit": ["ordered"],
        "move_ordered_unit": ["ordered", "review"],
        "remove_ordered_unit": ["ordered", "review"],
        "replace_units": ["ordered"],
        "sort_ordered_plan": ["ordered", "review"],
        "regenerate_order": ["ordered"],
    }
    for part in _iter_tool_call_parts(messages):
        if part.tool_name == "run_planning_review":
            return []
        execute_action_family = _extract_execute_plan_action_family(part)
        if execute_action_family:
            return execute_plan_action_targets.get(execute_action_family, [])
        if part.tool_name in mutating_tool_names:
            return ["ordered"]
    return []


def _tool_context_has_execute_plan_return(messages: list[Any] | None) -> bool:
    return any(part.tool_name == "execute_plan_action" for part in _iter_tool_return_parts(messages))


def _current_turn_workspace_refresh_targets(
    *,
    tool_context_messages: list[Any] | None,
    new_messages: list[Any] | None,
    all_messages: list[Any] | None,
    content: str,
) -> list[str]:
    """Extract workspace refresh only from the current turn."""

    targets = _tool_calls_include_plan_workspace_refresh(tool_context_messages)
    if not targets:
        targets = _tool_calls_include_plan_workspace_refresh(new_messages)
    targets = _strip_workspace_targets_for_readonly_prompt(targets, content)
    return _strip_workspace_targets_for_explanation_only_result(
        targets,
        tool_context_messages,
    )


def _tool_calls_include_plan_view_targets(messages: list[Any] | None) -> list[str]:
    """Extract view-only workspace targets from query actions (no data refresh needed)."""
    view_targets: list[str] = []
    suppressed_families = {"query_state", "query_ordered"}
    for part in _iter_tool_return_parts(messages):
        if part.tool_name != "execute_plan_action":
            continue
        data = _parse_tool_return_json(part.content)
        if not data:
            continue
        action_family = str(data.get("action_family") or "").strip()
        if action_family in suppressed_families:
            continue
        view_targets.extend(_extract_execute_plan_action_view_targets(part))
    return _dedupe_workspace_targets(view_targets)


def _strip_workspace_targets_for_readonly_prompt(targets: list[str], content: str) -> list[str]:
    if not _prompt_explicitly_readonly(content):
        return targets
    return []


def _latest_plan_result_is_explanation_only(messages: list[Any] | None) -> bool:
    """True for plan tool results that explain issues without changing workspace state."""

    for part in reversed(_iter_tool_return_parts(messages)):
        if part.tool_name != "execute_plan_action":
            continue
        data = _parse_tool_return_json(part.content)
        if not data:
            continue
        action_family = str(data.get("action_family") or "").strip()
        result_kind = str(data.get("result_kind") or "").strip()
        if (action_family, result_kind) in {
            ("analyze_adjustment", "adjustment_analysis"),
            ("preview_fix_proposal", "fix_proposal_preview"),
        }:
            return True
        return False
    return False


def _strip_workspace_targets_for_explanation_only_result(
    targets: list[str],
    messages: list[Any] | None,
) -> list[str]:
    if not targets:
        return targets
    if _latest_plan_result_is_explanation_only(messages):
        return []
    return targets


def _tool_calls_include_plan_execution(messages: list[Any] | None) -> bool:
    return any(part.tool_name == "execute_plan_action" for part in _iter_tool_call_parts(messages))


def _tool_returns_successful_plan_apply(messages: list[Any] | None) -> bool:
    for part in _iter_tool_return_parts(messages):
        if part.tool_name != "execute_plan_action":
            continue
        data = _parse_tool_return_json(part.content)
        if not data:
            continue
        action_family = str(data.get("action_family") or "").strip()
        if (
            data.get("applied") is True
            and str(data.get("stage") or "").strip() == "apply"
            and action_family in _PENDING_PLAN_ACTION_FAMILIES
        ):
            return True
    return False


def _tool_returns_plan_mutation_context(messages: list[Any] | None) -> bool:
    """Return true when this turn is actually about a plan mutation flow.

    Read-only plan queries may still mention confirming a pending intent. Those
    should not receive the "no executable plan preview" boundary, otherwise the
    user sees a plan-adjustment warning for a preference confirmation.
    """
    mutation_families = set(_PENDING_PLAN_ACTION_FAMILIES)
    mutation_families.update({"analyze_adjustment", "preview_fix_proposal"})
    for part in _iter_tool_return_parts(messages):
        if part.tool_name not in {"plan_next_action", "execute_plan_action"}:
            continue
        data = _parse_tool_return_json(part.content)
        if not data:
            continue
        action_family = str(data.get("action_family") or "").strip()
        if action_family in mutation_families:
            return True
    return False


def _tool_returns_mutating_plan_preview(messages: list[Any] | None) -> bool:
    return _extract_plan_confirmation_candidate(messages) is not None


def _tool_calls_include_generate_fix_proposals(messages: list[Any] | None) -> bool:
    return any(part.tool_name == "generate_planning_fix_proposals" for part in _iter_tool_call_parts(messages))


def _latest_fix_proposal_confirmation_source(
    messages: list[Any] | None,
) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    payloads_by_call_id: dict[str, dict[str, Any]] = {}
    for call in _iter_tool_call_parts(messages):
        payload = _extract_execute_plan_payload(call)
        if isinstance(payload, dict):
            payloads_by_call_id[str(call.tool_call_id or "")] = payload
    for part in _iter_tool_return_parts(messages):
        if part.tool_name != "execute_plan_action":
            continue
        data = _parse_tool_return_json(part.content)
        if not data:
            continue
        plan_payload = payloads_by_call_id.get(str(part.tool_call_id or "")) or {}
        target_strategies = _normalized_fix_proposal_target_strategies(
            plan_payload.get("target_strategies")
            or plan_payload.get("targetStrategies")
            or data.get("target_strategies")
            or data.get("targetStrategies")
            or []
        )
        target_issue_codes = _normalized_fix_proposal_target_issue_codes(
            plan_payload.get("target_issue_codes")
            or plan_payload.get("targetIssueCodes")
            or data.get("target_issue_codes")
            or data.get("targetIssueCodes")
            or []
        )
        facts = data.get("facts") if isinstance(data.get("facts"), dict) else {}
        selected_proposal_id = _selected_fix_proposal_id(data, facts)
        ready_match = _select_ready_fix_proposal(
            facts,
            selected_proposal_id=selected_proposal_id,
            target_strategies=target_strategies,
            target_issue_codes=target_issue_codes,
        )
        if ready_match is None and not (target_strategies or target_issue_codes):
            continue
        result_kind = str(data.get("result_kind") or "").strip()
        action_family = str(data.get("action_family") or "").strip()
        if action_family == "preview_fix_proposal" and result_kind == "fix_proposal_preview":
            if target_strategies and "target_strategies" not in data and "targetStrategies" not in data:
                data = dict(data)
                data["target_strategies"] = target_strategies
            if target_issue_codes and "target_issue_codes" not in data and "targetIssueCodes" not in data:
                data = dict(data)
                data["target_issue_codes"] = target_issue_codes
            if target_strategies or target_issue_codes:
                data = dict(data)
                data["target_match_empty"] = _select_ready_fix_proposal(
                    facts,
                    target_strategies=target_strategies,
                    target_issue_codes=target_issue_codes,
                ) is None
            latest = data
    return latest


def _latest_fix_proposal_preview_result(
    messages: list[Any] | None,
) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    for part in _iter_tool_return_parts(messages):
        if part.tool_name != "execute_plan_action":
            continue
        data = _parse_tool_return_json(part.content)
        if not data:
            continue
        result_kind = str(data.get("result_kind") or "").strip()
        action_family = str(data.get("action_family") or "").strip()
        if action_family == "preview_fix_proposal" and result_kind == "fix_proposal_preview":
            latest = data
    return latest


async def _fetch_fix_proposal_confirmation_source(
    session_id: str,
    *,
    user_goal: str,
) -> dict[str, Any] | None:
    try:
        result = await generate_planning_fix_proposals(1, session_id)
    except Exception:
        logger.warning(
            "Fetch fix proposals for confirmation source failed: session_id=%s",
            session_id,
            exc_info=True,
        )
        return None
    if result.get("code") != 0:
        return None
    data = result.get("data") or {}
    if not isinstance(data, dict):
        return None
    facts = _fix_proposal_facts(data)
    if _select_ready_fix_proposal({"fix_proposals": facts}) is None:
        return None
    return {
        "applied": False,
        "action_family": "preview_fix_proposal",
        "stage": "apply",
        "result_kind": "fix_proposal_preview",
        "summary": "已整理当前方案的处理建议。",
        "user_goal": user_goal,
        "facts": {"fix_proposals": facts},
        "reply_focus": ["fix_proposal_preview", "ready_fix_proposals"],
    }


def _latest_unexecuted_plan_next_payload(
    messages: list[Any] | None,
    *,
    action_family: str | None = None,
) -> dict[str, Any] | None:
    """Return latest plan_next_action payload not followed by execute_plan_action.

    The full agent occasionally calls plan_next_action and then replies from
    that planning output without executing it. For preview flows this leaves the
    user without execution-layer resolution and can produce unsafe stale cards.
    This helper detects that structured half-step without inspecting user wording.
    """

    target_family = str(action_family or "").strip()
    allowed_families = set(_PENDING_PLAN_ACTION_FAMILIES)
    allowed_families.add("preview_fix_proposal")
    latest_payload: dict[str, Any] | None = None
    latest_family = ""
    has_execute_after_latest = False
    for part in _iter_tool_return_parts(messages):
        if part.tool_name == "plan_next_action":
            data = _parse_tool_return_json(part.content)
            if not isinstance(data, dict):
                continue
            family = str(data.get("action_family") or "").strip()
            if target_family:
                if family != target_family:
                    continue
            elif family not in allowed_families:
                continue
            latest_payload = normalize_plan_action_payload(dict(data))
            latest_family = family
            has_execute_after_latest = False
            continue
        if part.tool_name == "execute_plan_action" and latest_payload is not None:
            data = _parse_tool_return_json(part.content)
            if not isinstance(data, dict):
                continue
            family = str(data.get("action_family") or "").strip()
            if family == latest_family:
                has_execute_after_latest = True
    if latest_payload is None or has_execute_after_latest:
        return None
    return latest_payload


def _latest_turn_allows_plan_followup_confirmation(messages: list[Any] | None) -> bool:
    """Whether a short confirmation should continue a structured plan follow-up.

    This covers turns such as review/analyze replies that only offered to
    generate a preview. They have no active pending action yet, so a short
    "确认/可以" must not be consumed as an apply confirmation.
    """
    turn_messages = _messages_after_index(messages, _latest_user_turn_boundary(messages))
    if _extract_plan_confirmation_candidate(turn_messages) is not None:
        return False
    for part in _iter_tool_return_parts(turn_messages):
        if part.tool_name != "execute_plan_action":
            continue
        data = _parse_tool_return_json(part.content)
        if not isinstance(data, dict):
            continue
        action_family = str(data.get("action_family") or "").strip()
        result_kind = str(data.get("result_kind") or "").strip()
        facts = data.get("facts") if isinstance(data.get("facts"), dict) else {}
        fix_facts = facts.get("fix_proposals") if isinstance(facts.get("fix_proposals"), dict) else {}
        proposals = fix_facts.get("proposals") if isinstance(fix_facts, dict) else None
        if (
            action_family == "review_plan"
            and result_kind == "review_result"
            and isinstance(proposals, list)
            and proposals
        ):
            return True
        if action_family in {"analyze_adjustment", "preview_fix_proposal"} and result_kind in {
            "adjustment_analysis",
            "fix_proposal_preview",
            "preview_only",
        }:
            return True
    return False


def _latest_plan_semantic_route_context(messages: list[Any] | None) -> dict[str, Any]:
    """Return structured plan facts for semantic routing.

    This intentionally uses only prior tool results and assistant-side state,
    never raw user wording.  The semantic classifier may use these facts to
    decide whether the next user turn asks for a repair preview.
    """
    for part in reversed(_iter_tool_return_parts(messages)):
        if part.tool_name != "execute_plan_action":
            continue
        data = _parse_tool_return_json(part.content)
        if not isinstance(data, dict):
            continue
        action_family = str(data.get("action_family") or "").strip()
        result_kind = str(data.get("result_kind") or "").strip()
        if action_family not in {"review_plan", "analyze_adjustment", "preview_fix_proposal", "query_state"}:
            continue
        facts = data.get("facts") if isinstance(data.get("facts"), dict) else {}
        fix_facts = facts.get("fix_proposals") if isinstance(facts.get("fix_proposals"), dict) else {}
        proposals = fix_facts.get("proposals") if isinstance(fix_facts.get("proposals"), list) else []
        strategy_counts: dict[str, int] = {}
        for proposal in proposals:
            if not isinstance(proposal, dict):
                continue
            strategy = str(proposal.get("strategy") or "").strip()
            if strategy:
                strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1
        proposal_summaries: list[dict[str, Any]] = []
        ordered_proposals = sorted(
            [proposal for proposal in proposals if isinstance(proposal, dict)],
            key=lambda proposal: (
                0 if str(proposal.get("status") or "").strip() == "ready" else 1,
                0 if str(proposal.get("status") or "").strip() == "preview_only" else 1,
            ),
        )
        for proposal in ordered_proposals[:8]:
            if not isinstance(proposal, dict):
                continue
            proposal_summaries.append(
                {
                    "proposalId": str(proposal.get("proposal_id") or proposal.get("proposalId") or "").strip(),
                    "status": str(proposal.get("status") or "").strip(),
                    "strategy": str(proposal.get("strategy") or "").strip(),
                    "sourceCheckCodes": [
                        str(code or "").strip()
                        for code in (proposal.get("source_check_codes") or proposal.get("sourceCheckCodes") or [])
                        if str(code or "").strip()
                    ],
                    "title": _normalize_fix_proposal_user_text(str(proposal.get("title") or "").strip()),
                    "summary": _normalize_fix_proposal_user_text(str(proposal.get("summary") or "").strip()),
                }
            )
        return {
            "lastActionFamily": action_family,
            "lastResultKind": result_kind,
            "summary": _normalize_fix_proposal_user_text(str(data.get("summary") or data.get("state_summary") or "").strip()),
            "replyFocus": data.get("reply_focus") if isinstance(data.get("reply_focus"), list) else [],
            "fixProposals": {
                "readyCount": _as_int(fix_facts.get("ready_count")),
                "blockedCount": _as_int(fix_facts.get("blocked_count")),
                "previewOnlyCount": _as_int(fix_facts.get("preview_only_count")),
                "proposalSource": str(
                    fix_facts.get("proposal_source")
                    or fix_facts.get("proposalSource")
                    or ""
                ).strip(),
                "strategyCounts": strategy_counts,
                "strategies": list(strategy_counts.keys()),
                "proposals": proposal_summaries,
            },
        }
    return {}


def _latest_review_fix_proposal_route_context(messages: list[Any] | None) -> dict[str, Any]:
    """Return the latest review/analysis context that carries fix proposals.

    A later failed atomic mutation can appear after a successful review in the
    same model turn. For repair recovery we still need the review facts; the
    failed mutation should not erase the structured review issue scope.
    """

    for part in reversed(_iter_tool_return_parts(messages)):
        if part.tool_name != "execute_plan_action":
            continue
        data = _parse_tool_return_json(part.content)
        if not isinstance(data, dict):
            continue
        action_family = str(data.get("action_family") or "").strip()
        result_kind = str(data.get("result_kind") or "").strip()
        if action_family not in {"review_plan", "analyze_adjustment", "preview_fix_proposal"}:
            continue
        if result_kind not in {"review_result", "adjustment_analysis", "fix_proposal_preview"}:
            continue
        context = _latest_plan_semantic_route_context(
            [
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name="execute_plan_action",
                            content=json.dumps(data, ensure_ascii=False, default=str),
                            tool_call_id="review-fix-proposal-route-context",
                        )
                    ]
                )
            ]
        )
        fix_facts = context.get("fixProposals") if isinstance(context, dict) else None
        if isinstance(fix_facts, dict) and (
            _as_int(fix_facts.get("readyCount")) > 0
            or _as_int(fix_facts.get("blockedCount")) > 0
            or _as_int(fix_facts.get("previewOnlyCount")) > 0
            or bool(fix_facts.get("proposals"))
        ):
            return context
    return {}


def _has_plan_semantic_route_context(
    planning_summary: PlanningSummary | None,
    recent_plan_context: dict[str, Any] | None,
) -> bool:
    if planning_summary is None:
        return False
    if (
        int(getattr(planning_summary, "ordered_total", 0) or 0) > 0
        or int(getattr(planning_summary, "working_total", 0) or 0) > 0
        or int(getattr(planning_summary, "review_risk_count", 0) or 0) > 0
        or int(getattr(planning_summary, "review_warn_count", 0) or 0) > 0
    ):
        return True
    fix_facts = (recent_plan_context or {}).get("fixProposals")
    return isinstance(fix_facts, dict) and any(
        _as_int(fix_facts.get(key)) > 0
        for key in ("readyCount", "blockedCount", "previewOnlyCount")
    )


def _semantic_preview_fix_proposal_route_allowed(
    decision: Any,
    recent_plan_context: dict[str, Any] | None,
) -> bool:
    """Allow the fixed repair-preview route only for existing review proposals."""

    if not isinstance(recent_plan_context, dict) or not recent_plan_context:
        return False
    last_action_family = str(recent_plan_context.get("lastActionFamily") or "").strip()
    last_result_kind = str(recent_plan_context.get("lastResultKind") or "").strip()
    if last_action_family not in {"review_plan", "analyze_adjustment", "preview_fix_proposal"}:
        return False
    if last_result_kind not in {"review_result", "adjustment_analysis", "fix_proposal_preview"}:
        return False
    fix_facts = recent_plan_context.get("fixProposals")
    if not isinstance(fix_facts, dict):
        return False
    proposal_count = sum(
        _as_int(fix_facts.get(key))
        for key in ("readyCount", "blockedCount", "previewOnlyCount")
    )
    proposals = fix_facts.get("proposals") if isinstance(fix_facts.get("proposals"), list) else []
    if proposal_count <= 0 and not proposals:
        return False
    requested_strategies = {
        str(strategy or "").strip()
        for strategy in getattr(decision, "targetStrategies", []) or []
        if str(strategy or "").strip()
    }
    if not requested_strategies:
        return True
    proposal_strategies = {
        str(proposal.get("strategy") or "").strip()
        for proposal in proposals
        if isinstance(proposal, dict) and str(proposal.get("strategy") or "").strip()
    }
    strategy_counts = fix_facts.get("strategyCounts") if isinstance(fix_facts.get("strategyCounts"), dict) else {}
    proposal_strategies.update(
        str(strategy or "").strip()
        for strategy in strategy_counts
        if str(strategy or "").strip()
    )
    strategies = fix_facts.get("strategies") if isinstance(fix_facts.get("strategies"), list) else []
    proposal_strategies.update(
        str(strategy or "").strip()
        for strategy in strategies
        if str(strategy or "").strip()
    )
    return not proposal_strategies or bool(requested_strategies & proposal_strategies)


def _semantic_decision_requests_fix_preview(
    decision: Any,
    *,
    require_issue_code_for_non_preview: bool,
) -> bool:
    action_family = str(getattr(decision, "actionFamily", "none") or "none").strip()
    confidence = float(getattr(decision, "confidence", 0.0) or 0.0)
    if action_family not in {"preview_fix_proposal", "review_plan", "analyze_adjustment"}:
        return False
    if confidence < _SEMANTIC_PLAN_ACTION_CONFIDENCE_THRESHOLD:
        return False
    if action_family == "preview_fix_proposal":
        return True
    target_issue_codes = [
        str(code or "").strip()
        for code in list(getattr(decision, "targetIssueCodes", []) or [])
        if str(code or "").strip()
    ]
    if target_issue_codes:
        return True
    if require_issue_code_for_non_preview:
        return False
    target_strategies = [
        str(strategy or "").strip()
        for strategy in list(getattr(decision, "targetStrategies", []) or [])
        if str(strategy or "").strip()
    ]
    return bool(target_strategies)


def _plan_context_has_fix_proposals(context: dict[str, Any] | None) -> bool:
    if not isinstance(context, dict) or not context:
        return False
    fix_facts = context.get("fixProposals")
    if not isinstance(fix_facts, dict):
        return False
    return (
        _as_int(fix_facts.get("readyCount")) > 0
        or _as_int(fix_facts.get("blockedCount")) > 0
        or _as_int(fix_facts.get("previewOnlyCount")) > 0
        or bool(fix_facts.get("proposals"))
    )


def _tool_calls_include_plan_chain(messages: list[Any] | None) -> bool:
    plan_tool_names = {
        "collect_plan_context_inputs",
        "plan_next_action",
        "execute_plan_action",
        "query_volunteer_plan",
    }
    return any(part.tool_name in plan_tool_names for part in _iter_tool_call_parts(messages))


async def _candidate_query_should_bypass_semantic_plan_action(
    content: str,
    *,
    request_context: RequestContext,
) -> bool:
    """Let read-only candidate opportunity queries stay on the local query path.

    This uses the shared LLM-backed candidate filter extractor instead of a
    phrase shortcut. The semantic plan-action shortcut is only for review and
    repair explanations; candidate opportunity lookup should be answered by
    `query_volunteer_plan(scope="candidate")` in the full agent path.
    """

    try:
        result = await extract_candidate_query_filters_async(
            content,
            batch=getattr(request_context, "batch", None),
        )
    except Exception:
        logger.warning(
            "Candidate query semantic bypass extraction failed: session_id=%s",
            getattr(request_context, "sessionid", ""),
            exc_info=True,
        )
        return False
    if not bool((result or {}).get("should_query_candidate")):
        return False
    try:
        confidence = float((result or {}).get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < 0.7:
        return False
    filters = (result or {}).get("filters") if isinstance(result, dict) else {}
    if not isinstance(filters, dict):
        return False
    return any(bool(filters.get(key)) for key in (
        "tiers",
        "province_names",
        "city_names",
        "school_keywords",
        "major_keywords",
        "school_tags",
        "major_tags",
    ))


def _tool_calls_include_intent_preview(messages: list[Any] | None) -> bool:
    return any(part.tool_name in _INTENT_PREVIEW_TOOL_NAMES for part in _iter_tool_call_parts(messages))


def _semantic_decision_requests_intent_preview(decision: dict[str, Any] | None) -> bool:
    if not isinstance(decision, dict):
        return False
    return (
        str(decision.get("decision") or "").strip() == "intent_preview"
        and float(decision.get("confidence") or 0.0) >= 0.7
    )


def _tool_calls_allow_unbacked_intent_recovery(
    messages: list[Any] | None,
    *,
    semantic_intent_preview: bool = False,
) -> bool:
    tool_names = [str(part.tool_name or "").strip() for part in _iter_tool_call_parts(messages)]
    if not tool_names:
        return True
    if all("intent" in name for name in tool_names if name):
        return True
    if semantic_intent_preview and _tool_calls_include_plan_chain(messages):
        return _extract_plan_confirmation_candidate(messages) is None
    return False


def _reply_indicates_unresolved_readonly_plan_query(reply: str | None) -> bool:
    compact = _compact_plan_reply_text(str(reply or ""))
    if not compact:
        return False
    return any(
        marker in compact
        for marker in (
            "没有稳定收敛",
            "没能稳定收敛",
            "没有拿到稳定结果",
            "没有稳定结果",
            "先不继续重复查询",
            "不继续重复查询",
            "换一个更具体的条件",
            "这轮查询没有稳定",
        )
    )


def _plan_chain_allows_intent_recovery(
    messages: list[Any] | None,
    *,
    reply: str | None = None,
) -> bool:
    """Allow structured intent recovery after a read-only Plan misroute.

    This is a guardrail for turns such as "排除某地域，再看候选": if the model
    only queried plan/candidate data and produced no confirmable preview, the
    service can ask the Intent tool to recover a pending update from the current
    utterance. The recovery itself still decides whether a real intent exists.
    """
    if not _tool_calls_include_plan_chain(messages):
        return False
    if _tool_calls_include_intent_preview(messages):
        return False
    if _extract_plan_confirmation_candidate(messages) is not None:
        return False
    if _latest_turn_has_plan_mutation_preview(messages):
        return False
    if not _latest_turn_looks_readonly(messages):
        return False
    return _reply_indicates_unresolved_readonly_plan_query(reply)


def _plan_chain_failed_without_pending_preview(messages: list[Any] | None) -> bool:
    """Detect a misrouted Plan chain that produced no actionable preview.

    This is intentionally based on structured tool results, not on user wording.
    If the main agent sent an explicit preference/constraint update through a
    Plan action and that Plan action failed before producing a pending preview,
    the service can ask the Intent tool to recover the structured intent.
    """

    if not _tool_calls_include_plan_chain(messages):
        return False
    if _extract_plan_confirmation_candidate(messages) is not None:
        return False
    for part in reversed(_iter_tool_return_parts(messages)):
        if part.tool_name != "execute_plan_action":
            continue
        data = _parse_tool_return_json(part.content)
        if not isinstance(data, dict):
            continue
        result_kind = str(data.get("result_kind") or "").strip()
        action_family = str(data.get("action_family") or "").strip()
        if result_kind == "error":
            reply_focus = {
                str(item or "").strip()
                for item in (data.get("reply_focus") or [])
                if str(item or "").strip()
            }
            if reply_focus & {
                "missing_inputs",
                "needs_candidate_selection",
                "needs_volunteer_selection",
                "replacement_scope_required",
                "replacement_scope_unresolved",
                "replacement_scope_insufficient",
                "unsupported_action",
                "stale_pending",
                "confirmation_invalid",
            }:
                return False
            if action_family in _PENDING_PLAN_ACTION_FAMILIES:
                return False
            return True
        if action_family == "preview_fix_proposal" and result_kind in {"no_change", "preview_only"}:
            facts = data.get("facts") if isinstance(data.get("facts"), dict) else {}
            fix_facts = facts.get("fix_proposals") if isinstance(facts.get("fix_proposals"), dict) else {}
            proposals = fix_facts.get("proposals") if isinstance(fix_facts, dict) else None
            if not proposals:
                return True
    return False


def _tool_returns_intent_non_pending(messages: list[Any] | None) -> bool:
    for part in _iter_tool_return_parts(messages):
        if part.tool_name not in _INTENT_PREVIEW_TOOL_NAMES:
            continue
        data = _parse_tool_return_json(part.content)
        if str((data or {}).get("status") or "").strip() in {"existing_only", "empty"}:
            return True
        text = str(getattr(part, "content", "") or "")
        if _is_existing_only_intent_notice_text(text):
            return True
    return False


def _latest_existing_only_intent_payload(messages: list[Any] | None) -> dict[str, Any] | None:
    payload = _extract_recent_intent_analysis_payload(messages)
    if not isinstance(payload, dict):
        return None
    if str(payload.get("status") or "").strip() != "existing_only":
        return None
    if str(payload.get("analysisStage") or "").strip() != ANALYSIS_STAGE_CONFIRMED:
        return None
    return payload


def _build_existing_only_no_plan_reply(payload: dict[str, Any] | None) -> str:
    merged = _merge_existing_intent_payload(payload)
    summary = _summarize_intent_values(
        merged,
        intent_mode=str((payload or {}).get("intentMode") or "constraint").strip() or "constraint",
        constraint_intent_type=str(
            (payload or {}).get("constraintIntentType")
            or (payload or {}).get("constraint_intent_type")
            or "default"
        ).strip() or "default",
    )
    lines = ["这条报考想法已经记录过，本轮不用重复采纳。"]
    if summary:
        lines.append(f"当前记录：{summary}。")
    lines.append("现在还没有可调整的方案或候选结果，所以这一步不会直接改方案。")
    lines.append("下一步可以先生成候选和方案；有方案后，我再按这条想法帮你检查哪些需要保留、替换或移出。")
    return _sanitize_reply_for_user("\n".join(lines))


def _tool_returns_interest_stage_intent_analysis(messages: list[Any] | None) -> bool:
    for part in _iter_tool_return_parts(messages):
        if part.tool_name in _INTENT_INTEREST_ANALYSIS_TOOL_NAMES:
            data = _parse_tool_return_json(part.content)
            if isinstance(data, dict):
                analysis_stage = str(data.get("analysisStage") or "").strip()
                status = str(data.get("status") or "").strip()
                if analysis_stage == ANALYSIS_STAGE_CONFIRMED and status in {"ready", "existing_only"}:
                    continue
            return True
        if part.tool_name not in _INTENT_PREVIEW_TOOL_NAMES:
            continue
        data = _parse_tool_return_json(part.content)
        if str((data or {}).get("analysisStage") or "").strip() == "interest":
            return True
    return False


def _normalize_pending_intent_reply(reply: str) -> str:
    if not isinstance(reply, str):
        return reply
    normalized = reply
    replacements = (
        ("好的，我记下了你对", "我先把你对"),
        ("好的，我已经记下了你对", "我先把你对"),
        ("我记下了你对", "我先把你对"),
        ("我已经记下了你对", "我先把你对"),
        ("好的，我记下了", "我先整理一下"),
        ("好的，我已经记下了", "我先整理一下"),
        ("我已经按你的偏好记录下来", "我先把这个想法整理出来，等你点“采纳”后再作为后续参考"),
        ("我已经记录下来", "我先把这个想法整理出来，等你点“采纳”后再作为后续参考"),
        ("我先把这个偏好整理成待确认参考，你确认后我再正式生效。", "我先把这个想法列出来，点“采纳”前不会生效。"),
    )
    for source, target in replacements:
        normalized = normalized.replace(source, target)
    if normalized != reply and "确认" not in normalized:
        normalized = normalized.rstrip("。") + "。如果要按这个方向作为后续参考，请点“采纳”。"
    return normalized


def _normalize_unbacked_recorded_wording(reply: str) -> str:
    """Avoid implying that a read-only conclusion has been saved as user intent."""
    if not isinstance(reply, str) or not reply.strip():
        return reply
    normalized = reply
    replacements = (
        ("这个判断可以先记下来", "这个判断可以先作为当前分析结论参考"),
        ("这个结论可以先记下来", "这个结论可以先作为当前分析结论参考"),
        ("这个方向可以先记下来", "这个方向可以先作为当前讨论方向参考"),
        ("先记下来", "先作为当前结论参考"),
        ("我先记下来", "我先按当前结论理解"),
        ("我会先记下来", "我会先按当前结论理解"),
    )
    for source, target in replacements:
        normalized = normalized.replace(source, target)
    normalized = re.sub(
        r"(?m)^好的，明白了。你倾向(.+?)这个方向，",
        r"好的，先按刚才的分析结论理解：\1这个方向",
        normalized,
    )
    normalized = re.sub(
        r"(?m)^好的，明白了。你更倾向(.+?)这个方向，",
        r"好的，先按刚才的分析结论理解：\1这个方向",
        normalized,
    )
    return normalized


_FALSE_APOLOGY_PREFIX_RE = re.compile(
    r"^\s*抱歉[，,]\s*刚才[^。！？!?]*(?:没有|没)[^。！？!?]*(?:回应|回答|答复)[^。！？!?]*[。！？!?]\s*(?:让我重新[^。！？!?]*[。！？!?]\s*)?",
    re.MULTILINE,
)


def _history_has_prior_assistant_reply(history: list[Any] | None) -> bool:
    for message in history or []:
        if isinstance(message, ModelResponse):
            if any(isinstance(part, TextPart) and str(part.content or "").strip() for part in message.parts):
                return True
            continue
        if isinstance(message, dict) and str(message.get("role") or "").strip().lower() == "assistant":
            if str(message.get("content") or "").strip():
                return True
    return False


def _normalize_false_apology_reply(reply: str, history: list[Any] | None) -> str:
    """Remove model-invented self-correction in clean first-turn contexts."""
    if not isinstance(reply, str) or not reply.strip() or _history_has_prior_assistant_reply(history):
        return reply
    normalized = _FALSE_APOLOGY_PREFIX_RE.sub("", reply, count=1).lstrip()
    return normalized or reply


def _normalize_general_confirmation_protocol_wording(reply: str) -> str:
    """Keep tool-less meta answers aligned with the card-confirmation protocol."""
    if not isinstance(reply, str) or not reply.strip():
        return reply
    normalized = reply
    confirmation_boundary = "我会先把要采用的内容列出来，点“采纳”前不会覆盖原来的想法，也不会自动改候选或方案"
    replacements = (
        (
            "直接告诉我就行",
            "直接告诉我，我会先把要采用的内容列出来，等你点“采纳”后再生效",
        ),
        (
            "你直接告诉我新的想法就行",
            "你可以直接告诉我新的想法，我会先把要采用的内容列出来，等你点“采纳”后再生效",
        ),
        (
            "直接告诉我新的想法就行",
            "可以直接告诉我新的想法，我会先把要采用的内容列出来，点“采纳”前不会生效",
        ),
        (
            "我就能按新的要求重新筛选",
            "点“采纳”前不会自动改候选或方案；采纳后我再按新的要求继续看候选和方案",
        ),
        (
            "我就能重新调整推荐口径和候选志愿",
            "我会先把要采用的内容列出来；采纳后再调整推荐口径和候选志愿",
        ),
        (
            "我会重新整理，不会锁定之前的偏好",
            "我会先重新列出要采用的内容；点“采纳”前不会覆盖之前的想法，也不会自动改候选或方案",
        ),
        (
            "随时可以在对话里改",
            "随时可以在对话里提出调整；我会先把要采用的内容列出来，点“采纳”前不会生效",
        ),
        (
            "在我们这里，随时能改",
            f"在我们这里，随时可以提出调整；{confirmation_boundary}",
        ),
        (
            "随时能改",
            f"随时可以提出调整；{confirmation_boundary}",
        ),
        (
            "都是可以根据新想法调整的",
            f"都可按新想法调整；{confirmation_boundary}",
        ),
        (
            "可以根据新想法调整",
            f"可按新想法调整；{confirmation_boundary}",
        ),
        (
            "调整偏好后，系统会重新筛选符合条件的院校和专业",
            "如果要正式更新这个想法，我会先列出来让你采纳；采纳后，再按新的想法重新筛选符合条件的院校和专业",
        ),
        (
            "调整后会重新匹配候选机会，已生成的方案也可以同步更新",
            "如果要正式调整，我会先列出调整内容；采纳后再重新匹配候选机会，已生成的方案也会按确认后的动作更新",
        ),
        (
            "修改偏好后可以重新生成或局部调整",
            "如果要按新偏好重新生成或局部调整方案，我会先给出确认预览",
        ),
        (
            "改了之后，重新生成或调整方案即可",
            "采纳后，再按新偏好重新生成或调整方案",
        ),
        (
            "增删、替换、调整顺序都可以",
            "增删、替换、调整顺序都可以，但都会先给确认预览，点击采纳前不会改动方案",
        ),
        (
            "可以重新生成方案",
            "可以重新生成方案，执行前也会先让你确认",
        ),
        (
            "再决定是否更新到后续推荐中",
            "再决定是否列出来让你采纳；点“采纳”前不会更新到后续推荐中",
        ),
        (
            "我先帮你整理成待确认偏好",
            "我可以先把这个想法列出来，点“采纳”前不会写入后续报考参考",
        ),
        (
            "先帮你整理成待确认偏好",
            "先把这个想法列出来，点“采纳”前不会写入后续报考参考",
        ),
        (
            "把这个偏好先记下来",
            "把这个想法列出来，点“采纳”前不会作为后续参考",
        ),
        (
            "把偏好先记下来",
            "把想法列出来，点“采纳”前不会作为后续参考",
        ),
        (
            "先保存这个思路",
            "先把这个思路列出来让你采纳",
        ),
    )
    for source, target in replacements:
        normalized = normalized.replace(source, target)
    normalized = re.sub(
        r"(?:有的话可以)?(?:直接)?告诉我[，,]?我帮你记成后续参考[。！？]?",
        "如果要正式采用，我会先把要采用的内容列出来；点“采纳”前不会生效。",
        normalized,
    )
    normalized = re.sub(
        r"我(?:先|会先|可以先)?帮你记成后续参考[。！？]?",
        "我会先把要采用的内容列出来；点“采纳”前不会生效。",
        normalized,
    )
    normalized = re.sub(
        r"我可以先整理成待确认(?:偏好|要求|意向|内容)[，,]?\s*确认后",
        "我可以先把要采用的内容列出来；点“采纳”前不会生效。采纳后",
        normalized,
    )
    normalized = re.sub(
        r"我可以把(?P<topic>[^。！？\n]{0,100}?)整理成待确认(?:偏好|要求|意向|内容)[，,]?\s*确认后(?P<verb>会|再)",
        r"我可以先把\g<topic>列出来；点“采纳”前不会生效，采纳后\g<verb>",
        normalized,
    )
    normalized = normalized.replace("我可以先整理成待确认偏好", "我可以先把这个想法列出来")
    normalized = normalized.replace("我可以先整理成待确认要求", "我可以先把这个报考条件列出来")
    normalized = normalized.replace("我可以先整理成待确认意向", "我可以先把这个想法列出来")
    normalized = normalized.replace("我可以先整理成待确认内容", "我可以先把要采用的内容列出来")
    normalized = normalized.replace("我先帮你整理成待确认偏好", "我先把这个想法列出来")
    normalized = normalized.replace("我先帮你整理成待确认要求", "我先把这个报考条件列出来")
    normalized = normalized.replace("我先帮你整理成待确认内容", "我先把要采用的内容列出来")
    normalized = normalized.replace("待确认偏好", "待采纳想法")
    normalized = normalized.replace("待确认要求", "待采纳报考条件")
    normalized = normalized.replace("待确认意向", "待采纳想法")
    normalized = re.sub(
        r"我可以整理成确认(?:偏好|要求|内容)[。；;]?\s*你确认后[，,]",
        "我可以先把要采用的内容列出来；点“采纳”前不会生效。采纳后，",
        normalized,
    )
    normalized = normalized.replace("我可以整理成确认偏好", "我可以先把这个想法列出来")
    normalized = normalized.replace("我可以整理成确认要求", "我可以先把这个报考条件列出来")
    normalized = normalized.replace("我可以整理成确认内容", "我可以先把要采用的内容列出来")
    normalized = normalized.replace("确认卡片，采纳后", "待采纳内容；采纳后")
    normalized = normalized.replace("不会生效。，采纳后", "不会生效；点击采纳后")
    normalized = normalized.replace("不会生效。，点击采纳后", "不会生效；点击采纳后")
    if any(marker in normalized for marker in ("确认卡片", "待采纳内容", "列出来让你采纳", "要采用的内容列出来")):
        consistency_replacements = (
            ("，改完立刻生效", ""),
            ("改完立刻生效", "采纳后生效"),
            ("你确认后，我会", "采纳后，我会"),
            ("确认后，我会", "采纳后，我会"),
            ("你确认后再", "采纳后再"),
            ("确认后再", "采纳后再"),
            ("确认后会", "采纳后会"),
            ("如果孩子现在就有新想法，直接告诉我，我立刻帮你调整方案。", "如果孩子现在有新想法，我会先列出要采用的内容或调整预览；点“采纳”前不会改候选或方案。"),
            ("我立刻帮你调整方案", "我会先列出调整内容，采纳后再调整方案"),
            ("立刻帮你调整方案", "先列出调整内容，采纳后再调整方案"),
            ("我直接帮你调整方案", "我会先列出调整内容，采纳后再调整方案"),
            ("直接帮你调整方案", "先列出调整内容，采纳后再调整方案"),
            ("确认前", "采纳前"),
        )
        for source, target in consistency_replacements:
            normalized = normalized.replace(source, target)
    has_confirmation_boundary = (
        "采纳/确认前不会生效" in normalized
        or "采纳前不会生效" in normalized
        or "确认前不会生效" in normalized
        or "采纳后再" in normalized
    )
    if (
        "确认卡片" not in normalized
        and not has_confirmation_boundary
        and _reply_discusses_changeable_intent_or_plan(normalized)
    ):
        normalized = (
            normalized.rstrip()
            + "\n\n如果要正式更新想法、报考条件或方案，我会先列出要采用的内容或调整预览；采纳/确认前不会生效。"
        )
    return _normalize_user_facing_terms(normalized)


def _reply_discusses_changeable_intent_or_plan(reply: str) -> bool:
    compact = _compact_plan_reply_text(reply)
    if not compact:
        return False
    has_changeable_subject = any(marker in compact for marker in ("偏好", "排除项", "方案内容", "当前方案", "志愿"))
    has_changeable_action = any(marker in compact for marker in ("可以改", "可以调整", "随时都可以调整", "随时可以调整", "增删", "替换", "调整顺序", "重新生成"))
    return has_changeable_subject and has_changeable_action


def _reply_promises_fix_proposal_preview(reply: str) -> bool:
    compact = _compact_plan_reply_text(reply)
    if not compact:
        return False
    mentions_preview = "预览" in compact
    mentions_confirmation_boundary = any(
        marker in compact
        for marker in (
            "确认前不会改",
            "确认前不会改动",
            "确认前不会生效",
            "我会先列出",
            "可以先看调整预览",
            "先列出调整预览",
            "生成预览",
        )
    )
    return mentions_preview and mentions_confirmation_boundary


def _reply_is_existing_only_intent_notice(reply: str) -> bool:
    return _is_existing_only_intent_notice_text(str(reply or ""))


def _is_existing_only_intent_notice_text(text: str) -> bool:
    normalized = str(text or "")
    compact = _compact_plan_reply_text(normalized)
    if not compact:
        return False
    has_existing_notice = any(
        marker in compact
        for marker in (
            "这个想法当前已经在报考参考里",
            "当前已经在后续报考参考",
            "已经作为后续报考参考",
            "已作为参考",
        )
    )
    has_no_duplicate_notice = any(marker in compact for marker in ("本轮不用重复采纳", "本轮不会重复新增"))
    return has_existing_notice and has_no_duplicate_notice


def _reply_claims_intent_recorded_without_pending(reply: str) -> bool:
    """Detect final-copy claims that an intent was saved without a pending card.

    This checks only the model's final reply, after tool routing already
    happened. It is a protocol guard, not user-intent routing.
    """

    compact = _compact_plan_reply_text(reply)
    if not compact:
        return False
    if any(
        marker in compact
        for marker in (
            "不会写入后续参考",
            "不会写入后续报考参考",
            "不会作为后续参考",
            "采纳前不会生效",
            "点击采纳前不会生效",
            "点采纳前不会生效",
        )
    ):
        return False
    has_record_claim = any(
        marker in compact
        for marker in (
            "作为后续报考参考记下来",
            "作为后续参考记下来",
            "已经作为后续报考参考",
            "已作为后续报考参考",
            "已经写入后续报考参考",
            "已写入后续报考参考",
            "已经记录到后续参考",
            "已记录到后续参考",
            "已经记下来",
            "已记下来",
        )
    )
    if not has_record_claim:
        return False
    return any(
        marker in compact
        for marker in (
            "后续报考参考",
            "后续参考",
            "报考条件",
            "推荐口径",
            "优先保证",
            "生成或调整方案",
        )
    )


def _reply_looks_like_unbacked_intent_preview(reply: str) -> bool:
    compact = _compact_plan_reply_text(reply)
    if not compact:
        return False
    claimed_clickable_card = _reply_claims_clickable_intent_card(reply)
    has_pending_heading = (
        "待确认内容" in compact
        or "待采纳内容" in compact
        or "整理成待确认" in compact
        or "列出要采纳" in compact
        or "准备采纳的方向" in compact
        or "准备采纳的内容" in compact
        or "准备采用的方向" in compact
        or "准备采用的内容" in compact
    )
    has_specific_intent_items = any(
        marker in reply
        for marker in (
            "倾向：",
            "倾向:",
            "- 倾向",
            "排除：",
            "排除:",
            "- 排除",
            "偏好专业",
            "排除专业",
            "偏好地域",
            "地域偏好",
            "院校偏好",
            "排除省份",
            "排除城市",
            "排除地域",
            "排除地区",
            "只保留专业",
            "只保留专业门类",
            "只保留专业类",
            "只保留：",
            "只保留:",
            "优先范围：",
            "优先范围:",
            "排除范围：",
            "排除范围:",
            "排除：",
            "排除:",
            "优先保留",
            "过滤掉",
        )
    )
    has_text_confirmation_request = any(
        marker in compact
        for marker in (
            "回复确认",
            "直接回复确认",
            "请点采纳",
            "点采纳",
            "点击采纳",
            "采纳前不会生效",
            "确认就",
            "确认是否",
            "请确认是否",
            "是否采纳",
            "确认采纳",
            "确认这个",
            "按上面执行",
            "你确认要这样记",
            "确认要这样记",
        )
    )
    has_unbacked_confirm_effect = (
        any(marker in compact for marker in ("确认后", "如果你确认", "你确认", "确认要这样记"))
        and any(marker in compact for marker in ("后续参考", "偏好", "排除", "过滤", "优先保留", "记入", "记录"))
    )
    if claimed_clickable_card:
        return True
    if has_pending_heading and not has_specific_intent_items:
        return False
    if not has_pending_heading and not has_text_confirmation_request:
        return False
    if not has_pending_heading and not has_specific_intent_items:
        return False
    return has_text_confirmation_request or has_unbacked_confirm_effect


def _reply_claims_clickable_intent_card(reply: str) -> bool:
    compact = _compact_plan_reply_text(reply)
    if not any(marker in compact for marker in ("确认卡片", "待采纳内容")):
        return False
    has_card_created_claim = any(
        marker in compact
        for marker in (
            "已经生成",
            "已生成",
            "生成了",
            "已经为你生成",
            "已为你生成",
            "已经为你整理",
            "已为你整理",
            "已经整理",
            "已整理",
            "我已把",
            "这张确认卡片",
            "已经列出",
            "已列出",
            "已经为你列出",
            "已为你列出",
            "这次待采纳内容",
        )
    )
    has_click_effect = any(
        marker in compact
        for marker in (
            "点击采纳",
            "点击卡片",
            "采纳后",
            "才会生效",
            "不会生效",
            "写入后续",
            "后续报考参考",
        )
    )
    return has_card_created_claim and has_click_effect


def _normalize_unbacked_intent_preview_reply(reply: str) -> str:
    """Avoid fake pending intent previews when the model did not call preview tools."""
    if not _reply_looks_like_unbacked_intent_preview(reply):
        return reply
    if "待确认内容" not in _compact_plan_reply_text(reply):
        return (
            "这轮我还没有列出可采纳的内容，所以不会把这些想法写入后续报考参考。"
            "如果你想正式采用，请直接说明要保留或避开的方向，"
            "我会先列清楚要采纳的内容，等你点“采纳”后再生效。"
        )
    normalized = re.sub(r"\*\*待确认内容\*\*", "**这轮先按咨询结论理解**", reply)
    normalized = re.sub(r"(?m)^我先把.*整理成待确认(?:偏好|要求|内容)[：:]?\s*$", "我先把这轮结论说明清楚：", normalized)
    replacements = (
        ("回复\"确认\"就按上面执行；", "如果你想正式采用，我会先把要采用的内容列出来；采纳前不会生效。"),
        ("回复“确认”就按上面执行；", "如果你想正式采用，我会先把要采用的内容列出来；采纳前不会生效。"),
        ("直接回复“确认”", "请点“采纳”"),
        ("直接回复\"确认\"", "请点“采纳”"),
        ("确认后，", "如果后续正式记成要求，"),
    )
    for source, target in replacements:
        normalized = normalized.replace(source, target)
    if "这轮没有生成可点击的确认卡片" not in normalized:
        normalized = (
            normalized.rstrip()
            + "\n\n补充说明：这轮还没有列出可采纳的内容，也不会写入后续参考或改动方案；"
            "如果要正式采用，我会先把要采用的内容列出来，点“采纳”后才会生效。"
        )
    return _normalize_user_facing_terms(normalized)


_DOWNGRADED_INTENT_PENDING_CLAIM_RE = re.compile(
    r"(?:我(?:先|会先|可以)?|这边)?(?:先)?(?:帮你)?把(?P<topic>[^。！？\n]{0,80}?)"
    r"(?:整理|记录)(?:成|为)?(?:一条|一个|一份)?待确认(?:偏好|要求|意向|内容)"
    r"(?:[，,]?(?:(?:你|等你|如果你)?确认后)[^。！？\n]*[。！？]?)?"
)
_DOWNGRADED_INTENT_DIRECT_CONFIRM_RE = re.compile(
    r"我可以把(?P<topic>[^。！？\n]{0,80}?)(?:整理|记)(?:成|为)(?P<target>排除条件|后续参考|偏好|要求)"
    r"[。！？]?(?:(?:你|等你|如果你)?确认后)[^。！？\n]*[。！？]?"
)


def _normalize_downgraded_intent_preview_reply(reply: str) -> str:
    """When intent arbitration downgrades to analysis-only, do not imply a card already exists."""
    if not isinstance(reply, str) or not reply.strip():
        return reply
    compact = _compact_plan_reply_text(reply)
    has_fake_pending_claim = "整理成待确认" in compact or any(
        marker in compact for marker in ("待确认偏好", "待确认要求", "待确认意向", "待确认内容")
    )
    has_no_card_effect_claim = any(
        marker in compact
        for marker in (
            "点击卡片采纳后",
            "点击采纳后",
            "确认后会",
            "确认后系统会",
            "候选池会变小",
            "不会再进入候选",
            "不再进入候选",
            "过滤掉",
            "自动过滤",
            "按这个口径来筛选",
        )
    )
    if not has_fake_pending_claim and not has_no_card_effect_claim:
        return reply

    def _replace_claim(match: re.Match[str]) -> str:
        topic = str(match.group("topic") or "这个想法").strip(" ：:，,。")
        if not topic:
            topic = "这个想法"
        return f"如果你想把{topic}作为后续参考，我可以先列出来让你采纳；采纳前不会生效。"

    normalized = _DOWNGRADED_INTENT_PENDING_CLAIM_RE.sub(_replace_claim, reply)

    def _replace_direct_confirm(match: re.Match[str]) -> str:
        topic = str(match.group("topic") or "这个想法").strip(" ：:，,。")
        target = str(match.group("target") or "后续参考").strip()
        if not topic:
            topic = "这个想法"
        return f"如果你想把{topic}作为{target}，我会先列出来让你采纳；采纳前不会生效。"

    normalized = _DOWNGRADED_INTENT_DIRECT_CONFIRM_RE.sub(_replace_direct_confirm, normalized)
    normalized = normalized.replace("点击卡片采纳后会一并过滤掉", "如果后续采纳，会把这些方向作为排除参考")
    normalized = normalized.replace("点击采纳后会一并过滤掉", "如果后续采纳，会把这些方向作为排除参考")
    normalized = normalized.replace("点击卡片采纳后会", "如果后续采纳，会")
    normalized = normalized.replace("点击采纳后会", "如果后续采纳，会")
    normalized = normalized.replace("后续生成方案时，系统会按这个口径来筛选。", "后续生成或调整方案时，会把这个口径作为推荐和检查参考；基础候选池不会因此变小。")
    normalized = normalized.replace("后续生成方案时，系统会按这个口径来筛选", "后续生成或调整方案时，会把这个口径作为推荐和检查参考；基础候选池不会因此变小")
    normalized = normalized.replace("这些方向都不会再进入候选", "后续推荐和方案检查会把这些方向作为排除参考，基础候选池不会因此变小")
    normalized = normalized.replace("会收窄候选范围", "不会改小基础候选池；会作为后续推荐、方案检查和方案调整参考")
    normalized = normalized.replace("收窄候选范围", "不会改小基础候选池；会作为后续推荐、方案检查和方案调整参考")
    normalized = normalized.replace("候选池会变小", "基础候选池不会因此变小")
    normalized = normalized.replace("不会再进入候选", "会作为排除参考")
    normalized = normalized.replace("不再进入候选", "会作为排除参考")
    normalized = normalized.replace("自动过滤后续推荐", "作为后续推荐和方案检查的排除参考")
    normalized = re.sub(
        r"自动过滤(?P<target>[^。！？\n]{1,50}?(?:相关选项|相关方向|相关志愿|选项|方向|志愿))",
        r"把\g<target>作为后续推荐、方案检查和方案调整的排除参考",
        normalized,
    )
    normalized = normalized.replace("自动过滤", "作为后续推荐、方案检查和方案调整的排除参考")
    normalized = normalized.replace("过滤掉", "作为排除参考")
    normalized = normalized.replace("你确认后我再作为后续参考去筛方案", "点击采纳后，我再作为后续参考去看候选和方案")
    normalized = normalized.replace("你确认后我再作为后续参考", "点击采纳后，我再作为后续参考")
    normalized = re.sub(
        r"你确认要把(?P<topic>[^。！？\n]{0,80}?)作为后续参考吗？采纳/确认前不会生效。",
        r"如果你想把\g<topic>作为后续参考，我会先列出来让你采纳；采纳前不会生效。",
        normalized,
    )
    normalized = re.sub(
        r"(?:要不要|需要不需要)(?:我)?先整理成[^。！？\n？?]{0,40}(?:要求|偏好|排除条件)[？?]\s*确认后[，,]",
        "如果要正式采用，我会先把要采用的内容列出来；采纳前不会生效。如果后续采纳，",
        normalized,
    )
    normalized = normalized.replace("确认后，我会", "如果后续采纳，我会")
    normalized = normalized.replace("确认后会", "如果后续采纳，会")
    normalized = normalized.replace("点击采纳后，我再作为后续参考去看候选和方案", "如果后续采纳，我再作为后续参考去看候选和方案")
    normalized = normalized.replace("点击采纳后，我再作为后续参考", "如果后续采纳，我再作为后续参考")
    normalized = normalized.replace("告诉我，我帮你记成后续参考。", "如果要正式采用，我会先把要采用的内容列出来；采纳前不会生效。")
    normalized = normalized.replace("直接告诉我，我帮你记成后续参考。", "如果要正式采用，我会先把要采用的内容列出来；采纳前不会生效。")
    normalized = normalized.replace("整理成待确认偏好", "列出来让你采纳")
    normalized = normalized.replace("整理成待确认要求", "列出来让你采纳")
    normalized = normalized.replace("整理成待确认意向", "列出来让你采纳")
    if "基础候选池" not in normalized and any(marker in normalized for marker in ("排除参考", "筛选", "过滤")):
        normalized = normalized.rstrip() + "\n\n补充说明：基础候选池不会因为偏好或要求采纳而永久变小；采纳后只是作为后续推荐、方案检查和方案调整的参考。"
    return _normalize_user_facing_terms(normalized)


def _append_pending_intent_boundary(reply: str, *, has_pending_intent: bool) -> str:
    """Keep pending intent analysis visibly non-mutating across follow-up turns."""
    if not has_pending_intent or not isinstance(reply, str) or not reply.strip():
        return reply
    compact = _compact_plan_reply_text(reply)
    if any(marker in compact for marker in ("尚未确认", "待确认内容", "确认前不会写入后续参考")):
        return reply
    if any(marker in compact for marker in ("已正式生效", "已经生效", "记下来了", "已记录")):
        return reply
    return (
        reply.rstrip()
        + "\n\n补充说明：这次内容还没有采纳，点“采纳”前不会写入后续报考参考；"
        "如果要正式采用，请点击“采纳”。"
    )


_PENDING_INTENT_FOLLOWUP_USER_TOKENS = (
    "先不确认",
    "不确认",
    "暂不确认",
    "还没确认",
    "看看影响",
    "看影响",
    "有什么影响",
    "会不会影响",
    "影响方案",
    "这个偏好",
    "这个要求",
    "这个意向",
    "刚才的偏好",
    "刚才的要求",
    "上面的偏好",
    "上面的要求",
)

_PENDING_INTENT_FOLLOWUP_REPLY_TOKENS = (
    "这个偏好",
    "这个要求",
    "这个意向",
    "该偏好",
    "该要求",
    "待确认偏好",
    "待确认要求",
    "待确认意向",
    "偏好会影响",
    "要求会影响",
    "意向会影响",
)


def _is_pending_intent_followup_turn(content: str, reply: str) -> bool:
    """Whether an existing pending intent is relevant to this read-only turn.

    A session may contain an old backend pending-intent cache while the user asks
    an unrelated Explore question. In that case appending a confirmation
    boundary is confusing. Keep the boundary only when this turn explicitly
    references the pending preference/requirement or its impact.
    """
    compact_content = _compact_plan_reply_text(content)
    compact_reply = _compact_plan_reply_text(reply)
    return any(token in compact_content for token in _PENDING_INTENT_FOLLOWUP_USER_TOKENS) or any(
        token in compact_reply for token in _PENDING_INTENT_FOLLOWUP_REPLY_TOKENS
    )


_PENDING_READONLY_IMPACT_USER_TOKENS = (
    "先不确认",
    "不确认",
    "暂不确认",
    "还没确认",
    "先别执行",
    "先不执行",
    "看看影响",
    "看影响",
    "有什么影响",
    "会不会影响",
    "影响当前方案",
    "影响方案",
    "当前方案吗",
    "当前方案么",
    "先看看",
)


def _is_pending_readonly_impact_question(content: str) -> bool:
    """Detect read-only follow-up about an active pending card, not user intent routing."""
    compact = _compact_plan_reply_text(content)
    if not compact:
        return False
    has_readonly_marker = any(token in compact for token in _PENDING_READONLY_IMPACT_USER_TOKENS)
    has_impact_marker = any(token in compact for token in ("影响", "当前方案", "候选", "承接", "匹配", "冲突"))
    return has_readonly_marker and has_impact_marker


def _build_pending_readonly_impact_reply(pending_state: dict[str, Any]) -> str:
    kind = str((pending_state or {}).get("kind") or "").strip()
    action_family = str((pending_state or {}).get("actionFamily") or "").strip()
    summary = str((pending_state or {}).get("summary") or "").strip()
    execution_payload = pending_state.get("executionPayload") if isinstance(pending_state, dict) else None
    intent_payload = execution_payload.get("intentPayload") if isinstance(execution_payload, dict) else None
    intent_summary = _summarize_selected_intent_payload(intent_payload) if isinstance(intent_payload, dict) else ""

    if kind == "plan_mutation":
        lines = [
            "当前有一项方案调整还没有执行。",
            "",
            "**对当前方案的影响**",
        ]
        lines.append(f"- {summary}" if summary else "- 完成确认前不会改动当前方案；确认后才会执行这次方案调整。")
        if intent_summary:
            lines.append(f"- 同时会更新后续报考参考：{intent_summary}。")
        lines.extend(
            [
                "",
                "**现在的状态**",
                "- 你还没有确认时，当前方案不会移出、加入、移动或重排任何志愿。",
                "- 可以继续只看影响或让我解释范围；这不会让待确认动作自动生效。",
            ]
        )
        return "\n".join(lines)

    if kind == "intent_change":
        lines = [
            "当前有一项待采纳的想法或报考条件，还没有采纳。",
            "",
            "**对当前方案的影响**",
            "- 点击采纳前不会写入后续报考参考，也不会改动当前方案。",
        ]
        if summary:
            lines.append(f"- 待采纳内容：{summary}。")
        lines.append("- 采纳后才会作为后续推荐、方案检查和方案调整的参考；基础候选池不会因此永久变小。")
        return "\n".join(lines)

    return "当前有一项待采纳内容还没有生效。完成确认前不会改动当前方案。"


def _last_user_visible_text_response(messages: list[Any] | None) -> ModelResponse | None:
    for message in reversed(messages or []):
        if not isinstance(message, ModelResponse) or _is_route_observability_message(message):
            continue
        if any(isinstance(part, TextPart) and str(part.content or "").strip() for part in getattr(message, "parts", []) or []):
            return message
    return None


def _message_text_content(message: Any) -> str:
    parts: list[str] = []
    for part in getattr(message, "parts", []) or []:
        if isinstance(part, TextPart) and isinstance(part.content, str):
            text = part.content.strip()
            if text:
                parts.append(text)
    return "\n".join(parts)


def _short_assistant_confirmation_summary(text: str, limit: int = 160) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _pending_confirmation_card_metadata_from_text(text: str) -> dict[str, Any]:
    text = str(text or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except Exception:
        return {}
    if not isinstance(data, dict) or data.get("type") != "pendingConfirmationCard":
        return {}
    return data


def _assistant_confirmation_kind_from_text(text: str) -> str | None:
    card = _pending_confirmation_card_metadata_from_text(text)
    if card:
        kind = str(card.get("kind") or "").strip()
        if kind in {"intent_change", "plan_mutation"}:
            return kind

    compact = _compact_plan_reply_text(text)
    if not compact:
        return None
    intent_title_markers = (
        "确认采纳这次偏好",
        "确认采纳这次要求",
        "确认采纳这次意向",
    )
    plan_title_markers = (
        "确认加入方案",
        "确认移出志愿",
        "确认移动志愿",
        "确认移动专业组",
        "确认移出专业组",
        "确认替换志愿",
        "确认方案排序",
        "确认重排方案",
        "确认补齐方案",
        "确认生成方案",
        "请确认本次方案调整",
    )
    has_intent_title = any(_compact_plan_reply_text(marker) in compact for marker in intent_title_markers)
    has_plan_title = any(_compact_plan_reply_text(marker) in compact for marker in plan_title_markers)
    if has_intent_title and not has_plan_title:
        return "intent_change"
    if has_plan_title and not has_intent_title:
        return "plan_mutation"
    return None


def _pending_summary_overlaps_assistant_text(pending_summary: str, assistant_text: str) -> bool:
    compact_text = _compact_plan_reply_text(assistant_text)
    if not compact_text:
        return False
    compact_summary = _compact_plan_reply_text(pending_summary)
    if compact_summary and compact_summary in compact_text:
        return True
    for part in re.split(r"[\n；;。.!！?？,，]+", str(pending_summary or "")):
        compact_part = _compact_plan_reply_text(part)
        if len(compact_part) >= 6 and compact_part in compact_text:
            return True
    return False


def _evaluate_short_text_pending_consistency(
    pending_state: dict[str, Any],
    history: list[Any] | None,
) -> tuple[str, str | None, str]:
    """Check only assistant-generated confirmation artifacts, not user intent."""
    pending_id = str(pending_state.get("pendingId") or "").strip()
    latest_response = _last_user_visible_text_response(history)
    latest_text = _message_text_content(latest_response) if latest_response is not None else ""
    assistant_summary = _short_assistant_confirmation_summary(latest_text)
    if not latest_text:
        return "unknown", None, ""
    latest_model_name = str(getattr(latest_response, "model_name", "") or "")
    blocked_prefix = "pending-confirmation-consistency-blocked"
    if latest_model_name == blocked_prefix or latest_model_name.startswith(f"{blocked_prefix}:"):
        blocked_pending_id = latest_model_name.split(":", 1)[1].strip() if ":" in latest_model_name else ""
        if not blocked_pending_id or blocked_pending_id == pending_id:
            return "conflict", "previous_consistency_blocked", assistant_summary

    pending_kind = str(pending_state.get("kind") or "").strip()
    card = _pending_confirmation_card_metadata_from_text(latest_text)
    if card:
        card_pending_id = str(card.get("pendingId") or "").strip()
        card_kind = str(card.get("kind") or "").strip()
        if card_pending_id and pending_id and card_pending_id != pending_id:
            return "conflict", "assistant_confirmation_pending_id_conflict", assistant_summary
        if card_kind in {"intent_change", "plan_mutation"}:
            if card_kind == pending_kind:
                return "matched", None, assistant_summary
            return "conflict", "assistant_confirmation_type_conflict", assistant_summary

    assistant_kind = _assistant_confirmation_kind_from_text(latest_text)
    if assistant_kind is None:
        return "unknown", None, assistant_summary
    if assistant_kind == pending_kind:
        return (
            "matched" if _pending_summary_overlaps_assistant_text(str(pending_state.get("summary") or ""), latest_text) else "unknown",
            None,
            assistant_summary,
        )
    return "conflict", "assistant_confirmation_type_conflict", assistant_summary


def _messages_after_index(messages: list[Any] | None, index: int | None) -> list[Any]:
    if not messages:
        return []
    if index is None:
        return list(messages)
    return list(messages[index + 1:])


def _latest_user_turn_boundary(messages: list[Any] | None) -> int | None:
    if not messages:
        return None
    return _latest_user_prompt_index(list(messages))


def _latest_turn_tool_names(messages: list[Any] | None) -> list[str]:
    boundary = _latest_user_turn_boundary(messages)
    return [part.tool_name for part in _iter_tool_call_parts(_messages_after_index(messages, boundary))]


def _latest_turn_has_intent_preview(messages: list[Any] | None) -> bool:
    boundary = _latest_user_turn_boundary(messages)
    return _tool_calls_include_intent_preview(_messages_after_index(messages, boundary))


def _latest_turn_has_plan_mutation_preview(messages: list[Any] | None) -> bool:
    boundary = _latest_user_turn_boundary(messages)
    turn_messages = _messages_after_index(messages, boundary)
    for part in _iter_tool_return_parts(turn_messages):
        if part.tool_name not in {"plan_next_action", "execute_plan_action"}:
            continue
        data = _parse_tool_return_json(part.content)
        if not data:
            continue
        action_family = str(data.get("action_family") or "").strip()
        effective_family = action_family
        result_kind = str(data.get("result_kind") or "").strip()
        result_stage = str(data.get("stage") or "").strip()
        if effective_family in _PENDING_PLAN_ACTION_FAMILIES and result_stage == "preview":
            return True
    return False


def _latest_turn_looks_readonly(messages: list[Any] | None) -> bool:
    if _latest_turn_is_readonly_interruption_fallback(messages):
        return True
    tool_names = _latest_turn_tool_names(messages)
    if not tool_names:
        return False
    readonly_tool_names = {
        "query_volunteer_plan",
        "collect_plan_context_inputs",
        "analyze_current_interest",
        "analyze_current_interest_profile",
        "analyze_current_school_interest",
        "analyze_current_major_interest",
        "analyze_current_region_interest",
        "analyze_current_career_direction",
        "compare_majors",
        "compare_majors_adhoc",
        "compare_major_options",
        "compare_schools",
        "compare_schools_adhoc",
        "get_major_introduction",
        "get_major_introductions",
        "get_school_introduction",
        "query_admission_score",
        "query_score_line",
        "validate_major_subjects",
        "validate_plan_params",
    }
    if any(name in _INTENT_PREVIEW_TOOL_NAMES for name in tool_names):
        return False
    if _latest_turn_has_plan_mutation_preview(messages):
        return False
    for name in tool_names:
        if name == "plan_next_action":
            continue
        if name == "execute_plan_action":
            continue
        if name not in readonly_tool_names:
            return False
    for part in _iter_tool_return_parts(_messages_after_index(messages, _latest_user_turn_boundary(messages))):
        if part.tool_name != "execute_plan_action":
            continue
        data = _parse_tool_return_json(part.content)
        action_family = str((data or {}).get("action_family") or "").strip()
        if action_family not in _EXECUTE_PLAN_ACTION_VIEW_FAMILIES and action_family not in {"analyze_adjustment", "preview_fix_proposal"}:
            return False
        if bool((data or {}).get("applied")) and action_family not in _EXECUTE_PLAN_ACTION_VIEW_FAMILIES:
            return False
    return True


def _latest_turn_is_readonly_interruption_fallback(messages: list[Any] | None) -> bool:
    boundary = _latest_user_turn_boundary(messages)
    for message in _messages_after_index(messages, boundary):
        if not isinstance(message, ModelResponse):
            continue
        if str(getattr(message, "model_name", "") or "") == "agent-interruption-readonly-fallback":
            return True
    return False


def _no_pending_intent_confirmation_guard_reply() -> str:
    return "我这边没有找到上一轮仍在等待采纳的内容。你可以直接说想保留、排除或重点关注的方向，我会先列出来让你采纳。"


def _pending_requires_card_click_reply(kind: str | None = None) -> str:
    if kind == "plan_mutation":
        return "这次方案调整还没有执行。请以最新内容为准；确认前不会改动方案。如果内容已失效，可以重新说明要调整的内容，我会重新给出预览。"
    if kind == "intent_change":
        return "这次想法或报考条件已经列出来，正在等待采纳。请以最新内容为准；采纳前不会写入后续报考参考。如果内容已失效，可以重新说明你的想法。"
    return "这次更新还没有生效。请以最新内容为准；确认前不会生效。如果内容已失效，可以重新说明要更新的内容。"


def _pending_confirmation_type_mismatch_reply(active_kind: str, requested_kind: str) -> str:
    if active_kind == "plan_mutation" and requested_kind == "intent_change":
        return "当前等待确认的是方案调整，不是想法或报考条件更新。如果要确认方案调整，可以点“确认执行”或只回复“确认”；如果要更新想法，请重新说明具体内容。"
    if active_kind == "intent_change" and requested_kind == "plan_mutation":
        return "当前等待确认的是想法或报考条件更新，不是方案调整。如果要采纳这次内容，可以点“采纳”或只回复“确认”；如果要调整方案，请重新说明具体动作。"
    return "当前等待确认的内容和这次确认的对象不一致，请点最新内容里的按钮，或重新说明要确认的内容。"


def _plan_confirmation_card_applied_reply(action_family: str, result: dict[str, Any]) -> str:
    default_reply = "已按你的确认执行上一轮方案调整。"
    return str(result.get("summary") or default_reply)


def _plan_confirmation_apply_succeeded(result: dict[str, Any]) -> bool:
    return bool(isinstance(result, dict) and result.get("applied") is True)


def _readonly_closure_ack_reply() -> str:
    return "先按刚才的分析结论理解。这轮没有待确认的偏好或方案动作，也不会改动方案；后面想继续看具体学校、专业或方案调整，随时告诉我。"


_PENDING_PLAN_ACTION_FAMILIES = {
    "generate_plan",
    "add_units",
    "remove_units",
    "move_unit",
    "move_ordered_unit",
    "remove_ordered_unit",
    "replace_units",
    "sort_ordered_plan",
    "regenerate_order",
}

_NO_EXECUTABLE_PLAN_PREVIEW_REPLY = (
    "这次没有形成可执行的调整预览，方案不会因为这轮回复而改变。"
    "如果还需要处理这类问题，可以重新说明要调整的目标，我会按最新方案重新给出预览。"
)

def _latest_non_actionable_plan_mutation_result(messages: list[Any] | None) -> dict[str, Any] | None:
    for part in reversed(_iter_tool_return_parts(messages)):
        if part.tool_name != "execute_plan_action":
            continue
        data = _parse_tool_return_json(part.content)
        if not data:
            continue
        action_family = str(data.get("action_family") or "").strip()
        if action_family not in _PENDING_PLAN_ACTION_FAMILIES:
            continue
        if _build_plan_confirmation_candidate_from_payload(data) is not None:
            continue
        result_kind = str(data.get("result_kind") or "").strip()
        if result_kind in {"preview_only", "error"}:
            return data
    return None


_PLAN_EXECUTION_RESULT_KINDS = {
    "status_overview",
    "ordered_snapshot",
    "candidate_snapshot",
    "generation_result",
    "adjustment_analysis",
    "fix_proposal_preview",
    "mutation_result",
    "review_result",
    "preview_only",
    "no_change",
    "error",
}


def _plan_execution_result_is_non_actionable(data: dict[str, Any] | None) -> bool:
    if not isinstance(data, dict) or not data:
        return False
    action_family = str(data.get("action_family") or "").strip()
    result_kind = str(data.get("result_kind") or "").strip()
    if result_kind == "adjustment_analysis":
        return not _adjustment_analysis_has_actionable_suggestions(data)
    if data.get("applied") is True:
        return False
    if result_kind in {"error", "no_change"}:
        return True
    if result_kind == "preview_only":
        return action_family not in _PENDING_PLAN_ACTION_FAMILIES
    if result_kind and result_kind not in _PLAN_EXECUTION_RESULT_KINDS:
        return True
    return False


def _latest_non_actionable_plan_result(messages: list[Any] | None) -> dict[str, Any] | None:
    for part in reversed(_iter_tool_return_parts(messages)):
        if part.tool_name != "execute_plan_action":
            continue
        data = _parse_tool_return_json(part.content)
        if _plan_execution_result_is_non_actionable(data):
            return data
    return None


def _latest_profile_change_replan_result(messages: list[Any] | None) -> dict[str, Any] | None:
    for part in reversed(_iter_tool_return_parts(messages)):
        if part.tool_name != "execute_plan_action":
            continue
        data = _parse_tool_return_json(part.content)
        if isinstance(data, dict) and _requests_profile_change_replan(data):
            return data
    return None


def _latest_empty_status_overview_result(messages: list[Any] | None) -> dict[str, Any] | None:
    for part in reversed(_iter_tool_return_parts(messages)):
        if part.tool_name != "execute_plan_action":
            continue
        data = _parse_tool_return_json(part.content)
        if not isinstance(data, dict):
            continue
        if str(data.get("action_family") or "").strip() != "query_state":
            continue
        if str(data.get("result_kind") or "").strip() != "status_overview":
            continue
        facts = data.get("facts") if isinstance(data.get("facts"), dict) else {}
        if _as_int(facts.get("current_total")) <= 0:
            return data
    return None


def _non_actionable_plan_preview_boundary(result: dict[str, Any] | None) -> str:
    if not isinstance(result, dict) or not result:
        return _NO_EXECUTABLE_PLAN_PREVIEW_REPLY
    if _requests_profile_change_replan(result):
        return _build_profile_change_replan_reply(None)
    action_family = str(result.get("action_family") or "").strip()
    result_kind = str(result.get("result_kind") or "").strip()
    reply_focus = {str(item or "").strip() for item in (result.get("reply_focus") or []) if str(item or "").strip()}
    facts = result.get("facts") if isinstance(result.get("facts"), dict) else {}
    if action_family == "preview_fix_proposal" and result_kind == "fix_proposal_preview" and facts:
        return _sanitize_reply_for_user(
            _normalize_user_facing_terms(
                "\n".join(
                    _build_fix_proposal_preview_fallback_lines(
                        facts,
                        summary=str(result.get("summary") or "").strip(),
                    )
                )
            )
        )
    position_resolution = str(facts.get("position_resolution") or "").strip()
    if action_family in {"move_ordered_unit", "move_unit"} and position_resolution in {"empty_plan", "source_position_out_of_range"}:
        return (
            "这轮只是说明当前不能按这个位置移动，不会改动方案。"
            "需要先生成或补齐方案后，再按位置生成移动预览。"
        )
    if action_family in {"remove_ordered_unit", "remove_units"} and position_resolution in {"empty_plan", "source_position_out_of_range"}:
        return (
            "这轮只是说明当前不能按这个位置删除，不会改动方案。"
            "需要先生成或补齐方案后，再按位置生成删除预览。"
        )
    if action_family in {"remove_ordered_unit", "remove_units"} and position_resolution == "range_empty":
        return (
            "这轮已经检查过这个位置范围，当前没有命中需要删除的内容，所以不会改动方案。"
            "如果你想删除别的范围，可以再说明位置、冲稳保区间或具体学校专业。"
        )
    if "needs_candidate_selection" in reply_focus:
        return (
            "这轮还没有定位到要加入方案的具体候选，不会改动方案。"
            "可以补充学校、专业、地域等范围，或先在候选里选中目标。"
        )
    if "needs_volunteer_selection" in reply_focus:
        return (
            "这轮还没有定位到当前方案里要处理的具体志愿，不会改动方案。"
            "可以补充学校、专业组或专业名称后，我再给你预览。"
        )
    if "replacement_scope_required" in reply_focus or "replacement_scope_unresolved" in reply_focus:
        return (
            "这轮还缺少替换方向，不会改动方案。"
            "你可以补充想换成的专业、院校、地域或风险层次，我再给你预览。"
        )
    if "replacement_scope_insufficient" in reply_focus:
        return (
            "当前可选范围里没有足够合适的替换项，不会改动方案。"
            "可以放宽地域、专业、院校层次或风险要求后再试。"
        )
    if "missing_inputs" in reply_focus:
        summary = str(result.get("summary") or "").strip()
        if summary:
            return "这轮信息还不够完整，不会改动方案。你可以补充缺少的信息后，我再给你预览。"
    return _NO_EXECUTABLE_PLAN_PREVIEW_REPLY


def _adjustment_analysis_has_actionable_suggestions(result: dict[str, Any]) -> bool:
    facts = result.get("facts")
    if not isinstance(facts, dict):
        return False
    actionable_counts = facts.get("actionable_suggestion_counts")
    if isinstance(actionable_counts, dict):
        return any(int(actionable_counts.get(key) or 0) > 0 for key in ("add", "reorder", "replace", "remove"))
    return bool(facts.get("has_actionable_suggestions"))


def _text_looks_like_adjustment_request(text: str | None) -> bool:
    compact = re.sub(r"\s+", "", str(text or "").strip())
    return any(
        token in compact
        for token in (
            "更稳",
            "稳一点",
            "更保守",
            "保守一点",
            "风险低一点",
            "降风险",
            "按这个思路",
            "按更稳的思路",
            "怎么调",
            "怎么优化",
            "更合理",
            "弄一版",
            "优化一下",
        )
    )


def _plan_action_has_filter_selection_scope(filters: Any) -> bool:
    if not isinstance(filters, dict):
        return False
    for key, value in filters.items():
        if key in {"limit", "preserve_count", "preserveCount", "require_capacity_check", "requireCapacityCheck"}:
            continue
        if key in {"school_tags", "major_tags"} and str(value or "").strip() == "[]":
            continue
        if str(value or "").strip():
            return True
    return False


def _replace_plan_payload_lacks_replacement_scope(payload: dict[str, Any]) -> bool:
    if str(payload.get("action_family") or "").strip() != "replace_units":
        return False
    atomic_actions = payload.get("atomic_actions")
    if not isinstance(atomic_actions, list) or not atomic_actions:
        return True
    for atomic in atomic_actions:
        if not isinstance(atomic, dict):
            continue
        if _plan_action_has_filter_selection_scope(atomic.get("filters")):
            return False
    return True


def _atomic_volunteer_ids(atomic: dict[str, Any]) -> list[str]:
    volunteer_ids = atomic.get("volunteer_ids") or atomic.get("volunteerIds")
    if isinstance(volunteer_ids, list):
        return [str(item or "").strip() for item in volunteer_ids if str(item or "").strip()]
    text = str(volunteer_ids or "").strip()
    return [text] if text else []


def _atomic_unit_ids(atomic: dict[str, Any]) -> list[str]:
    unit_ids = atomic.get("unit_ids") or atomic.get("unitIds")
    if isinstance(unit_ids, list):
        return [str(item or "").strip() for item in unit_ids if str(item or "").strip()]
    text = str(unit_ids or "").strip()
    return [text] if text else []


def _atomic_source_major_names(atomic: dict[str, Any]) -> list[str]:
    source_major_names = atomic.get("source_major_names") or atomic.get("sourceMajorNames")
    if isinstance(source_major_names, list):
        return [str(item or "").strip() for item in source_major_names if str(item or "").strip()]
    text = str(source_major_names or "").strip()
    return [text] if text else []


def _atomic_has_review_issue_target(atomic: dict[str, Any]) -> bool:
    review_issue_target = atomic.get("review_issue_target") or atomic.get("reviewIssueTarget")
    return isinstance(review_issue_target, dict) and bool(str(review_issue_target.get("code") or "").strip())


def _atomic_has_filter_scope(atomic: dict[str, Any]) -> bool:
    filters = atomic.get("filters")
    return _plan_action_has_filter_selection_scope(filters if isinstance(filters, dict) else None)


def _atomic_has_position(atomic: dict[str, Any], *keys: str) -> bool:
    return any(atomic.get(key) is not None for key in keys)


def _atomic_action_has_execution_scope(action_family: str, atomic: Any) -> bool:
    if not isinstance(atomic, dict):
        return False
    if action_family == "add_units":
        return bool(_atomic_volunteer_ids(atomic)) or _atomic_has_filter_scope(atomic)
    if action_family == "remove_units":
        return bool(_atomic_volunteer_ids(atomic)) or _atomic_has_review_issue_target(atomic) or _atomic_has_filter_scope(atomic)
    if action_family == "move_unit":
        return bool(_atomic_volunteer_ids(atomic)) and _atomic_has_position(atomic, "target_position", "targetPosition")
    if action_family == "move_ordered_unit":
        has_source = (
            bool(_atomic_unit_ids(atomic))
            or _atomic_has_position(atomic, "source_position", "sourcePosition")
        )
        return has_source and _atomic_has_position(atomic, "target_position", "targetPosition")
    if action_family == "remove_ordered_unit":
        return bool(_atomic_unit_ids(atomic)) or _atomic_has_position(atomic, "source_position", "sourcePosition")
    if action_family == "replace_units":
        has_source = (
            bool(_atomic_volunteer_ids(atomic))
            or bool(_atomic_source_major_names(atomic))
            or _atomic_has_review_issue_target(atomic)
        )
        return has_source and _atomic_has_filter_scope(atomic)
    return False


def _plan_payload_has_executable_mutation_scope(payload: dict[str, Any]) -> bool:
    action_family = str(payload.get("action_family") or "").strip()
    if action_family in {"generate_plan", "regenerate_order", "sort_ordered_plan"}:
        return True
    atomic_actions = payload.get("atomic_actions")
    if isinstance(atomic_actions, list) and any(
        _atomic_action_has_execution_scope(action_family, item)
        for item in atomic_actions
    ):
        return True
    facts = payload.get("facts") if isinstance(payload.get("facts"), dict) else {}
    resolved_payload = facts.get("resolved_apply_payload") if isinstance(facts, dict) else None
    if isinstance(resolved_payload, dict) and resolved_payload is not payload:
        resolved_with_context = dict(payload)
        resolved_with_context.update(resolved_payload)
        resolved_facts = dict(facts)
        resolved_facts.pop("resolved_apply_payload", None)
        if resolved_facts:
            resolved_with_context["facts"] = resolved_facts
        else:
            resolved_with_context.pop("facts", None)
        return _plan_payload_has_executable_mutation_scope(resolved_with_context)
    return False


def _plan_payload_lacks_position_target(payload: dict[str, Any]) -> bool:
    if str(payload.get("action_family") or "").strip() not in {"move_ordered_unit", "remove_ordered_unit"}:
        return False
    facts = payload.get("facts") if isinstance(payload.get("facts"), dict) else {}
    if str(facts.get("position_resolution") or "").strip() in {"empty_plan", "source_position_out_of_range", "range_empty", "missing_source_position"}:
        return True
    return False


def _build_plan_confirmation_candidate_from_payload(payload: dict[str, Any], summary: str | None = None) -> dict[str, Any] | None:
    payload = normalize_plan_action_payload(payload)
    if _composite_goal_needs_clarification(payload):
        return None
    preview_action_family = str(payload.get("action_family") or "").strip()
    action_family = preview_action_family
    if action_family not in _PENDING_PLAN_ACTION_FAMILIES:
        return None
    if str(payload.get("result_kind") or "").strip() == "no_change":
        return None
    if payload.get("missing_inputs"):
        return None
    if action_family == "replace_units" and not payload.get("atomic_actions"):
        return None
    if not _plan_payload_has_executable_mutation_scope(payload):
        return None
    if _replace_plan_payload_lacks_replacement_scope(payload):
        return None
    if _plan_payload_lacks_position_target(payload):
        return None
    apply_payload = dict(payload)
    facts = apply_payload.get("facts") if isinstance(apply_payload.get("facts"), dict) else {}
    source_backend_version = _as_int(
        payload.get("source_backend_version")
        or payload.get("planning_version")
        or facts.get("source_backend_version")
        or facts.get("planning_version")
    )
    resolved_payload = facts.get("resolved_apply_payload") if isinstance(facts, dict) else None
    if isinstance(resolved_payload, dict):
        apply_payload.update(resolved_payload)
    resolved_action_family = str(apply_payload.get("action_family") or "").strip()
    if resolved_action_family in _PENDING_PLAN_ACTION_FAMILIES:
        action_family = resolved_action_family
    apply_payload["action_family"] = action_family
    if not _plan_payload_has_executable_mutation_scope(apply_payload):
        return None
    apply_payload.pop("current_stage", None)
    apply_payload.pop("user_confirmed", None)
    apply_payload["stage"] = "apply"
    apply_payload["requires_confirmation"] = False
    apply_payload["should_refresh_workspace"] = True
    apply_payload["should_rerun_review"] = True
    if source_backend_version > 0:
        apply_payload["planning_version"] = source_backend_version
    pending = {
        "action_family": action_family,
        "user_goal": payload.get("user_goal") or "",
        "summary": summary or payload.get("preview_summary") or "",
        "plan_payload": json.dumps(apply_payload, ensure_ascii=False),
    }
    intent_update = facts.get("intent_update") if isinstance(facts, dict) else None
    if isinstance(intent_update, dict) and intent_update.get("selected"):
        pending["intent_update"] = intent_update
    if source_backend_version > 0:
        pending["source_backend_version"] = source_backend_version
        pending["planning_version"] = source_backend_version
    created_turn = _as_int(payload.get("created_turn"))
    if created_turn > 0:
        pending["created_turn"] = created_turn
    return pending


def _parse_tool_call_args(args: Any) -> dict[str, Any]:
    if isinstance(args, dict):
        return args
    if isinstance(args, str) and args.strip():
        try:
            parsed = json.loads(args)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _merge_plan_next_payload_for_pending_candidate(
    call_payload: dict[str, Any],
    latest_plan_next_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Keep pending execution payload as complete as the structured plan.

    The model can call ``plan_next_action`` with the full structured plan and
    then pass a thinner payload to ``execute_plan_action`` for preview. Pending
    confirmation must persist the executable structure, not the thinner copy.
    """
    if not isinstance(call_payload, dict):
        return {}
    action_family = str(call_payload.get("action_family") or "").strip()
    if not action_family:
        return dict(call_payload)
    if (
        not isinstance(latest_plan_next_payload, dict)
        or str(latest_plan_next_payload.get("action_family") or "").strip() != action_family
    ):
        return dict(call_payload)

    merged = dict(latest_plan_next_payload)
    merged.update(call_payload)
    if (
        not call_payload.get("atomic_actions")
        and latest_plan_next_payload.get("atomic_actions")
    ):
        merged["atomic_actions"] = latest_plan_next_payload.get("atomic_actions")
    return merged


def _extract_plan_confirmation_candidate(messages: list[Any] | None) -> dict[str, Any] | None:
    """Find a current-turn plan preview that can be persisted as a confirmation card."""
    pending_calls: dict[str, dict[str, Any]] = {}
    latest_plan_next_payload: dict[str, Any] | None = None
    latest_candidate: dict[str, Any] | None = None
    last_non_actionable_adjustment_goal: str | None = None
    user_turns_since_candidate = 0
    current_user_turn = 0

    for message in messages or []:
        if isinstance(message, ModelResponse):
            for part in getattr(message, "parts", []) or []:
                if not isinstance(part, ToolCallPart) or part.tool_name != "execute_plan_action":
                    continue
                args = _parse_tool_call_args(part.args)
                raw_payload = args.get("plan_payload")
                if not isinstance(raw_payload, str) or not raw_payload.strip():
                    continue
                try:
                    payload = json.loads(raw_payload)
                except Exception:
                    continue
                if not isinstance(payload, dict):
                    continue
                call_id = str(part.tool_call_id or "")
                if call_id:
                    pending_calls[call_id] = payload

        if not isinstance(message, ModelRequest):
            continue
        user_prompt_parts = [
            part for part in getattr(message, "parts", []) or []
            if isinstance(part, UserPromptPart)
        ]
        if user_prompt_parts:
            current_user_turn += 1
            pending_calls.clear()
            latest_plan_next_payload = None
            last_non_actionable_adjustment_goal = None
            if latest_candidate is not None:
                user_turns_since_candidate += 1
                if user_turns_since_candidate > 3:
                    latest_candidate = None
                    user_turns_since_candidate = 0
            continue
        for part in getattr(message, "parts", []) or []:
            if not isinstance(part, ToolReturnPart):
                continue
            result = _parse_tool_return_json(part.content)
            if not result:
                continue
            if part.tool_name == "plan_next_action":
                if result.get("stage") == "preview":
                    latest_plan_next_payload = normalize_plan_action_payload(dict(result))
                continue
            if part.tool_name != "execute_plan_action":
                continue
            action_family = str(result.get("action_family") or "").strip()
            result_kind = str(result.get("result_kind") or "").strip()
            if _plan_execution_result_is_non_actionable(result):
                call_payload = pending_calls.get(str(part.tool_call_id or "")) or {}
                if action_family in {"query_state", "query_ordered", "query_candidates"}:
                    pending_calls.clear()
                    continue
                latest_candidate = None
                user_turns_since_candidate = 0
                pending_calls.clear()
                latest_plan_next_payload = None
                if result_kind == "adjustment_analysis":
                    last_non_actionable_adjustment_goal = (
                        str(result.get("user_goal") or "").strip()
                        or str(call_payload.get("user_goal") or "").strip()
                        or last_non_actionable_adjustment_goal
                    )
                continue
            call_id = str(part.tool_call_id or "")
            call_payload = pending_calls.get(call_id) or {}
            result_stage = str(result.get("stage") or call_payload.get("stage") or "").strip()
            is_preview_result = (
                result_kind == "preview_only"
                and result_stage == "preview"
            )
            call_action_family = str(call_payload.get("action_family") or "").strip()
            effective_action_family = action_family or call_action_family
            call_stage = str(call_payload.get("stage") or "").strip()
            if not is_preview_result and (
                result.get("applied") is True
                or call_stage == "apply"
            ):
                if effective_action_family in _PENDING_PLAN_ACTION_FAMILIES:
                    latest_candidate = None
                    user_turns_since_candidate = 0
                    pending_calls.clear()
                continue
            if not is_preview_result:
                continue
            if effective_action_family not in _PENDING_PLAN_ACTION_FAMILIES:
                continue
            if not call_payload:
                continue
            pending_payload = _merge_plan_next_payload_for_pending_candidate(
                normalize_plan_action_payload(dict(call_payload)),
                latest_plan_next_payload,
            )
            result_facts = result.get("facts")
            if isinstance(result_facts, dict) and result_facts:
                pending_payload["facts"] = result_facts
                result_version = _as_int(
                    result_facts.get("source_backend_version")
                    or result_facts.get("planning_version")
                )
                if result_version > 0:
                    pending_payload["planning_version"] = result_version
            top_level_version = _as_int(result.get("source_backend_version") or result.get("planning_version"))
            if top_level_version > 0:
                pending_payload["planning_version"] = top_level_version
            candidate = _build_plan_confirmation_candidate_from_payload(
                pending_payload,
                summary=result.get("summary") or call_payload.get("preview_summary") or "",
            )
            if candidate is None:
                continue
            if (
                last_non_actionable_adjustment_goal
                and _text_looks_like_adjustment_request(last_non_actionable_adjustment_goal)
                and _text_looks_like_adjustment_request(str(candidate.get("user_goal") or "").strip())
                        and str(candidate.get("action_family") or "").strip() == "generate_plan"
            ):
                continue
            if current_user_turn > 0:
                candidate["created_turn"] = current_user_turn
            latest_candidate = candidate
            user_turns_since_candidate = 0

    return latest_candidate


def _latest_structured_goal_plan_preview(messages: list[Any] | None) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    for part in _iter_tool_return_parts(messages):
        if part.tool_name != "plan_next_action":
            continue
        result = _parse_tool_return_json(part.content)
        if not isinstance(result, dict):
            continue
        if str(result.get("stage") or "").strip() != "preview":
            continue
        if _structured_goal_from_composite_proposal(result) is None:
            continue
        latest = result
    return latest


def _latest_composite_goal_plan_preview(messages: list[Any] | None) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    for part in _iter_tool_return_parts(messages):
        if part.tool_name != "plan_next_action":
            continue
        result = _parse_tool_return_json(part.content)
        if not isinstance(result, dict):
            continue
        if str(result.get("stage") or "").strip() != "preview":
            continue
        composite = result.get("composite_proposal") or result.get("compositeProposal")
        if not isinstance(composite, dict):
            continue
        goal = composite.get("goal")
        if not isinstance(goal, dict):
            continue
        goal_type = str(goal.get("goal_type") or goal.get("goalType") or "").strip()
        if goal_type not in {"only_keep_scope", "must_include_scope", "exclude_scope", "tuition_budget_scope"}:
            continue
        latest = result
    return latest


def _composite_goal_clarification_reply(source: dict[str, Any] | None) -> str | None:
    if not isinstance(source, dict):
        return None
    composite = source.get("composite_proposal") or source.get("compositeProposal")
    if not isinstance(composite, dict):
        return None
    if str(composite.get("feasibility") or "").strip() != "needs_clarification":
        return None
    goal = composite.get("goal")
    if not isinstance(goal, dict):
        return None
    questions = [
        str(item or "").strip()
        for item in (
            goal.get("clarification_questions")
            or goal.get("clarificationQuestions")
            or []
        )
        if str(item or "").strip()
    ]
    note = questions[0] if questions else ""
    values: list[str] = []
    for scope in (goal.get("target_scopes") or goal.get("targetScopes") or goal.get("negative_scopes") or goal.get("negativeScopes") or []):
        if isinstance(scope, dict):
            values.extend(scope_value_list(scope))
    scope_text = "、".join(dict.fromkeys(value for value in values if value))
    if note:
        return (
            f"我先确认一下范围：{note}\n\n"
            "这轮不会改动当前方案。你可以补充一下具体按哪个专业层级处理，"
            "我再给你列出调整预览。"
        )
    if scope_text:
        return (
            f"我先确认一下“{scope_text}”具体按哪个范围处理。\n\n"
            "这轮不会改动当前方案。你补充清楚后，我再给你列出调整预览。"
        )
    return "这次调整范围还不够明确，这轮不会改动当前方案。你补充清楚后，我再给你列出调整预览。"


def _latest_plan_mutation_attempt_result(messages: list[Any] | None) -> dict[str, Any] | None:
    for part in reversed(_iter_tool_return_parts(messages)):
        if part.tool_name not in {"execute_plan_action", "plan_next_action"}:
            continue
        data = _parse_tool_return_json(part.content)
        if not isinstance(data, dict):
            continue
        action_family = str(data.get("action_family") or "").strip()
        if action_family in _PENDING_PLAN_ACTION_FAMILIES:
            return data
    return None


_READONLY_CLOSURE_ACK_PHRASES = {
    "嗯那就这样",
    "那就这样",
    "那先这样",
    "先这样",
    "先这样吧",
    "就这样",
    "就这样吧",
    "好先这样",
    "好的先这样",
    "行先这样",
    "嗯先这样",
    "嗯就这样",
    "先按这个吧",
    "先按刚才的吧",
}


def _pending_semantic_decision(action: str, confidence: float = 1.0, reason: str = "") -> SimpleNamespace:
    return SimpleNamespace(action=action, confidence=confidence, reason=reason)


def _normalize_confirmation_only_text(content: str, *, strip_fullwidth_question: bool = False) -> str:
    normalized = re.sub(r"\s+", "", (content or "").strip())
    punctuation = "。.!！?？" if strip_fullwidth_question else "。.!！?"
    normalized = normalized.strip(punctuation)
    return normalized


def _is_readonly_closure_ack(content: str) -> bool:
    normalized = _normalize_confirmation_only_text(content, strip_fullwidth_question=True)
    if not normalized:
        return False
    return normalized in _READONLY_CLOSURE_ACK_PHRASES


_NO_PENDING_CONFIRMATION_ACKS = {
    "确认",
    "确认执行",
    "确定",
    "可以",
    "嗯可以",
    "好可以",
    "好的",
    "好",
    "行",
    "执行",
    "执行吧",
    "开始执行",
    "应用吧",
    "按这个来",
    "就按这个来",
    "按刚才的来",
    "就按刚才的来",
    "确认这个",
    "确认这条",
    "确认这个偏好",
    "确认这个要求",
    "确认这个意向",
    "确认这个方案",
    "采纳",
    "采纳这个",
    "采纳这条",
}


def _is_no_pending_confirmation_turn(content: str) -> bool:
    normalized = _normalize_confirmation_only_text(content, strip_fullwidth_question=True)
    if not normalized or _is_readonly_closure_ack(content):
        return False
    if normalized in _NO_PENDING_CONFIRMATION_ACKS:
        return True
    return normalized.startswith(("确认", "执行", "采纳")) and len(normalized) <= 10


_DIRECT_PENDING_CONFIRM_COMMON_ACKS = {
    "确认",
    "确定",
    "可以",
    "嗯可以",
    "好可以",
    "好的",
    "好",
    "行",
    "按这个来",
    "就按这个来",
    "按刚才的来",
    "就按刚才的来",
}

_DIRECT_PLAN_PENDING_CONFIRM_ACKS = _DIRECT_PENDING_CONFIRM_COMMON_ACKS | {
    "确认执行",
    "执行",
    "执行吧",
    "开始执行",
    "应用吧",
    "确认这个",
    "确认这条",
    "确认这个方案",
}

_DIRECT_INTENT_PENDING_CONFIRM_ACKS = _DIRECT_PENDING_CONFIRM_COMMON_ACKS | {
    "采纳",
    "采纳这个",
    "采纳这条",
    "确认这个",
    "确认这条",
    "确认这个偏好",
    "确认这个要求",
    "确认这个意向",
}


def _is_direct_pending_confirmation_turn(content: str, pending_kind: str) -> bool:
    """Protocol-level short confirmation when an active pending already exists."""
    normalized = _normalize_confirmation_only_text(content, strip_fullwidth_question=True)
    if not normalized or _is_readonly_closure_ack(content):
        return False
    if _is_pending_readonly_impact_question(content) or _prompt_rejects_current_plan_action(content):
        return False
    if pending_kind == "plan_mutation":
        return normalized in _DIRECT_PLAN_PENDING_CONFIRM_ACKS
    if pending_kind == "intent_change":
        return normalized in _DIRECT_INTENT_PENDING_CONFIRM_ACKS
    return False


def _no_pending_confirmation_guard_reply() -> str:
    return (
        "我这边没有上一轮正在等待采纳或执行的内容，也没有待确认的方案调整或报考想法。"
        "你可以直接说想审查方案、生成调整预览、调整排序，或说明要保留/避开的方向；"
        "涉及正式更新时，我会先列出内容或预览，确认前不会改方案。"
    )


async def _save_direct_guard_history(
    history_store: ChatHistoryStore,
    session_id: str,
    history: list[Any] | None,
    content: str,
    reply: str,
    *,
    model_name: str,
) -> None:
    new_messages = [
        ModelRequest(parts=[UserPromptPart(content=content)]),
        ModelResponse(parts=[TextPart(content=reply)], model_name=model_name),
    ]
    try:
        history_to_save = list(history or [])
        history_to_save.extend(new_messages)
        await history_store.save(session_id, history_to_save)
    except Exception:
        logger.exception("Failed to save direct guard history: session_id=%s model=%s", session_id, model_name)


def _sanitize_reply_for_user(reply: str) -> str:
    """清理回复中不应暴露给用户的内部标记。"""
    import re
    original_reply = reply
    for pattern, replacement in _USER_REPLY_ENGLISH_WORD_REPLACEMENTS:
        reply = pattern.sub(replacement, reply)
    # 移除 [LLM_INTERNAL] 开头的整行
    reply = re.sub(r'\n?\[LLM_INTERNAL\][^\n]*', '', reply)
    # 移除行内的 [LLM_INTERNAL] 标记
    reply = re.sub(r'\[LLM_INTERNAL\]\s*', '', reply)
    # 3.0.3 确认协议下，采纳偏好/要求不会把基础候选池永久改小。
    # 旧兼容路径或模型复述里可能残留“按要求过滤后候选还剩多少”的句子，
    # 这类统计只允许出现在显式候选查询结果里，不应作为采纳确认后的后续使用说明。
    reply = re.sub(
        r'(?m)^\s*[-*]?\s*后续使用[：:][^\n]*(?:按这条要求过滤后|候选大约|整体候选)[^\n]*(?:\n|$)',
        '',
        reply,
    )
    reply = re.sub(
        r'(?m)^\s*[^\n]*(?:按这条要求过滤后)[^\n]*(?:候选大约|整体候选)[^\n]*(?:\n|$)',
        '',
        reply,
    )
    compact = _compact_plan_reply_text(reply)
    candidate_pool_semantics_claim = any(
        marker in compact
        for marker in (
            "收窄候选范围",
            "候选池会收窄",
            "候选池会大幅收窄",
            "候选池会变小",
            "这些方向都不会再进入候选",
            "不再进入候选",
            "自动过滤",
        )
    )
    if any(
        marker in compact
        for marker in (
            "偏好",
            "要求",
            "意向",
            "采纳",
            "确认",
            "后续推荐",
            "后续生成方案",
            "影响分析",
            "先看影响",
            "作为后续参考",
        )
    ) or ("影响" in compact and candidate_pool_semantics_claim):
        before_candidate_pool_semantics = reply
        reply = re.sub(
            r"(?:你的)?候选池会(?:大幅|明显|显著)?(?:收窄|变窄)",
            "基础候选池不会因此变小",
            reply,
        )
        reply = reply.replace("会收窄候选范围", "不会改小基础候选池；会作为后续推荐、方案检查和方案调整参考")
        reply = reply.replace("收窄候选范围", "不会改小基础候选池；会作为后续推荐、方案检查和方案调整参考")
        reply = reply.replace("候选池会变小", "基础候选池不会因此变小")
        reply = reply.replace("这些方向都不会再进入候选", "后续推荐和方案检查会把这些方向作为排除参考，基础候选池不会因此变小")
        reply = reply.replace("不再进入候选", "会作为排除参考")
        reply = re.sub(
            r"自动过滤(?P<target>[^。！？\n]{1,50}?(?:相关选项|相关方向|相关志愿|选项|方向|志愿))",
            r"把\g<target>作为后续推荐、方案检查和方案调整的排除参考",
            reply,
        )
        reply = reply.replace("自动过滤后续推荐", "作为后续推荐和方案检查的排除参考")
        reply = reply.replace("自动过滤", "作为后续推荐、方案检查和方案调整的排除参考")
        reply = reply.replace("偏好卡片", "待采纳内容")
        reply = reply.replace("要求卡片", "待采纳内容")
        reply = re.sub(
            r"确认后我可以把(?P<topic>[^。！？\n]{0,80}?)整理成确认卡片[，,]?(?P<tail>[^。！？\n]{0,80})[。！？]?",
            r"如果你想正式采用，我可以先把\g<topic>列出来；采纳前不会生效。",
            reply,
        )
        if any(marker in reply for marker in ("整理成确认卡片", "整理成待采纳内容", "整理成待采纳报考条件", "列出来让你采纳")):
            reply = reply.replace("确认后，后续", "采纳后，后续")
            reply = reply.replace("确认后,后续", "采纳后，后续")
            reply = reply.replace("确认后再", "采纳后再")
            reply = reply.replace("确认后会", "采纳后会")
            reply = reply.replace("确认后才会生效", "采纳后才会生效")
            reply = reply.replace("确认后才正式生效", "采纳后才正式生效")
            reply = reply.replace("要不要先确认这些方向？", "要不要我先列出来让你采纳？")
        if (
            reply != before_candidate_pool_semantics
            and "基础候选池" not in reply
            and any(marker in reply for marker in ("排除参考", "方案检查", "方案调整参考"))
        ):
            reply = (
                reply.rstrip()
                + "\n\n补充说明：基础候选池不会因为偏好或要求采纳而永久变小；"
                "采纳后只是作为后续推荐、方案检查和方案调整的参考。"
            )
    reply = _normalize_user_facing_terms(reply)
    reply = re.sub(r"([。！？])\1+", r"\1", reply)
    reply = re.sub(r"(?<=[\u4e00-\u9fff])([.!?])\1+", r"\1", reply)
    if reply != original_reply:
        reply = reply.strip()
    return reply.strip()


def _is_basic_plan_status_question(content: str) -> bool:
    normalized = re.sub(r"\s+", "", (content or "").strip())
    normalized = normalized.strip("。.!！?？")
    if not normalized:
        return False
    return normalized in {
        "方案有了么",
        "方案有了吗",
        "有方案了吗",
        "方案生成了吗",
        "方案出来了吗",
        "当前方案有了吗",
        "现在有方案了吗",
        "现在方案有了吗",
        "看看现在的方案",
        "看看方案",
        "看下方案",
        "看一下方案",
        "方案怎么样了",
        "方案情况",
        "当前方案怎么样",
        "我的方案",
    }


def _prompt_explicitly_readonly(content: str | None) -> bool:
    compact = re.sub(r"\s+", "", str(content or "").strip())
    if not compact:
        return False
    return any(marker in compact for marker in _READONLY_USER_PROMPT_MARKERS)


def _prompt_rejects_current_plan_action(content: str | None) -> bool:
    compact = re.sub(r"\s+", "", str(content or "").strip())
    if not compact:
        return False
    return any(marker in compact for marker in _PLAN_ACTION_NEGATIVE_ACK_MARKERS)


def _build_basic_plan_status_reply(planning: PlanningSummary) -> str:
    total = planning.ordered_total or planning.working_total
    target = (
        planning.ordered_target_total
        or planning.working_target_total
        or max(planning.ordered_total, planning.working_total, total)
    )
    if total <= 0:
        return (
            '当前还没有生成方案。'
            '你可以直接说“帮我生成一版方案”，'
            '我会根据你的成绩和偏好先生成一版方案给你看，确认后再生成正式顺序。'
        )

    if planning.ordered_total >= target:
        count_text = f'你的方案已经填满了 {planning.ordered_total} 个志愿'
    elif planning.ordered_total > 0:
        count_text = f'你的方案目前有 {planning.ordered_total} 个志愿（目标 {target} 个）'
    else:
        count_text = f'当前已加入方案 {planning.working_total} 个志愿（目标 {target} 个），还没有生成正式顺序'

    lines = [f'{count_text}。']

    tier = planning.tier_counts
    if tier:
        chong = tier.get('冲', 0)
        wen = tier.get('稳', 0)
        bao = tier.get('保', 0)
        if chong or wen or bao:
            lines.append(f'其中冲 {chong} 个、稳 {wen} 个、保 {bao} 个。')

    if planning.sample_schools:
        school_text = '、'.join(planning.sample_schools[:4])
        lines.append(f'涉及院校包括{school_text}等。')

    pref_parts = []
    if planning.positive_regions:
        pref_parts.append(f'地区偏好{chr(0x3001).join(planning.positive_regions[:3])}')
    if planning.positive_majors:
        pref_parts.append(f'专业偏好{chr(0x3001).join(planning.positive_majors[:3])}')
    if pref_parts:
        lines.append(f'你的{chr(0x3001).join(pref_parts)}。')

    risk_total = planning.review_risk_count + planning.review_warn_count
    if risk_total > 0 and planning.risk_summaries:
        risk_desc = '、'.join(planning.risk_summaries[:2])
        if planning.review_risk_count > 0:
            lines.append(f'\n需要留意的风险：{risk_desc}。')
        else:
            lines.append(f'\n有几点提醒：{risk_desc}。')
    elif risk_total == 0 and planning.ordered_total > 0:
        lines.append('\n审查结果良好，暂时没有明显风险。')

    lines.append('\n你可以说“帮我审查一下”看详细情况，或者告诉我想怎么调整。')
    return ''.join(lines)


_READONLY_INTERRUPTION_TOOL_NAMES = {
    "query_volunteer_plan",
    "analyze_current_interest",
    "analyze_current_interest_profile",
    "analyze_current_school_interest",
    "analyze_current_major_interest",
    "analyze_current_region_interest",
    "analyze_current_career_direction",
    "compare_majors",
    "compare_majors_adhoc",
    "compare_major_options",
    "compare_schools",
    "compare_schools_adhoc",
    "get_major_introduction",
    "get_major_introductions",
    "get_school_introduction",
    "query_admission_score",
    "query_score_line",
    "validate_major_subjects",
    "validate_plan_params",
    "answer_admission_policy_question",
    "search_official_admission_sources",
}


def _agent_observability_tool_names(agent_observability: dict[str, Any] | None) -> list[str]:
    if not isinstance(agent_observability, dict):
        return []
    ordered: list[str] = []
    seen: set[str] = set()
    raw_first = agent_observability.get("firstToolNames")
    if isinstance(raw_first, list):
        for name in raw_first:
            text = str(name or "").strip()
            if text and text not in seen:
                ordered.append(text)
                seen.add(text)
    for node in agent_observability.get("nodeTimings") or []:
        if not isinstance(node, dict):
            continue
        raw_names = node.get("toolNames")
        if not isinstance(raw_names, list):
            continue
        for name in raw_names:
            text = str(name or "").strip()
            if text and text not in seen:
                ordered.append(text)
                seen.add(text)
    raw_counts = agent_observability.get("toolNameCounts")
    if isinstance(raw_counts, dict):
        for name in raw_counts:
            text = str(name or "").strip()
            if text and text not in seen:
                ordered.append(text)
                seen.add(text)
    return ordered


def _agent_interruption_looks_readonly(
    content: str,
    agent_observability: dict[str, Any] | None,
) -> bool:
    tool_names = _agent_observability_tool_names(agent_observability)
    if tool_names:
        if any(name in _INTENT_PREVIEW_TOOL_NAMES for name in tool_names):
            return False
        if any(name in _READONLY_INTERRUPTION_TOOL_NAMES for name in tool_names):
            return True

    compact = re.sub(r"\s+", "", str(content or "").strip())
    if not compact:
        return False
    if _prompt_explicitly_readonly(content):
        return True
    return any(
        marker in compact
        for marker in (
            "哪个更适合",
            "哪个更稳",
            "哪个更实际",
            "会不会太",
            "能不能",
            "是不是",
            "怎么样",
            "怎么判断",
            "有什么影响",
            "看看影响",
            "先看看",
            "先查一下",
            "帮我看下",
            "帮我看看",
        )
    )


def _interrupted_prompt_prefers_plan_status_fallback(
    content: str,
    planning: PlanningSummary | None,
) -> bool:
    if planning is None or (planning.ordered_total <= 0 and planning.working_total <= 0):
        return False
    compact = re.sub(r"\s+", "", str(content or "").strip())
    if not compact:
        return False
    return any(marker in compact for marker in _PLAN_STYLE_GUARD_PROMPT_KEYWORDS) or any(
        marker in compact
        for marker in (
            "这版",
            "当前这版",
            "太冲",
            "冒险",
            "保底",
            "公办",
            "民办",
            "中外合作",
            "学费",
            "省外",
            "本省",
        )
    )


def _describe_interrupted_readonly_request(
    content: str,
    batch: str | None = "01",
    agent_observability: dict[str, Any] | None = None,
) -> str:
    tool_names = set(_agent_observability_tool_names(agent_observability))
    compact = str(content or "").strip()
    if "analyze_current_region_interest" in tool_names:
        return f"你刚才问的是“{compact}”" if compact else "你刚才问的是地域选择相关问题"

    major_names: list[str] = []
    seen: set[str] = set()
    for mention in resolve_major_mentions_from_text(content, batch):
        name = str(getattr(mention, "canonical_name", "") or "").strip()
        if name and name not in seen:
            major_names.append(name)
            seen.add(name)
    if len(major_names) >= 2:
        return f"你刚才问的是 {major_names[0]} 和 {major_names[1]} 的比较"
    if len(major_names) == 1:
        return f"你刚才问的是 {major_names[0]} 相关问题"
    if compact:
        return f"你刚才问的是“{compact}”"
    return "你刚才这个问题"


def _build_agent_interruption_fallback_reply(
    content: str,
    planning: PlanningSummary | None,
    agent_observability: dict[str, Any] | None = None,
    *,
    batch: str | None = "01",
) -> str | None:
    """Return a safe user-facing reply when the model run is interrupted.

    This is intentionally conservative: it only uses already loaded planning
    summary facts and never claims that a tool action was completed.
    """
    if not isinstance(agent_observability, dict) or not agent_observability.get("failedNode"):
        return None

    if (
        _agent_interruption_looks_readonly(content, agent_observability)
        and not _interrupted_prompt_prefers_plan_status_fallback(content, planning)
    ):
        subject = _describe_interrupted_readonly_request(content, batch, agent_observability)
        return (
            "这轮模型服务中断了，我没有改动你的方案，也没有把偏好写入后续参考。"
            f"{subject}，这次没能完整生成分析结论；"
            "你可以继续围绕刚才的问题追问，我会按只读分析处理。"
        )

    prefix = (
        "这轮模型服务中断了，我先不改动你的方案或偏好。"
        "为了不让你一直等，我先根据已经读取到的信息给一个安全版结论："
    )
    if planning is not None and (planning.ordered_total > 0 or planning.working_total > 0):
        status_reply = _build_basic_plan_status_reply(planning).strip()
        if status_reply:
            return f"{prefix}\n\n{status_reply}"

    return (
        "这轮模型服务中断了，我先不改动你的方案或偏好。"
        "你可以再发一次刚才的问题，我会继续按当前会话信息处理；"
        "如果涉及方案调整，我仍会先给预览，等你确认后再执行。"
    )


def _should_guard_plan_reply(content: str) -> bool:
    return any(keyword in content for keyword in _PLAN_STYLE_GUARD_PROMPT_KEYWORDS)


def _normalize_user_facing_terms(reply: str) -> str:
    """Remove internal product terms from user-facing replies."""
    if not isinstance(reply, str):
        return reply
    replacements = (
        ("待确认卡片", "待采纳内容"),
        ("采纳卡片", "待采纳内容"),
        ("方案确认卡片", "方案调整预览"),
        ("确认卡片缺少校验信息", "这次操作缺少校验信息"),
        ("这张确认卡片缺少校验信息", "这次操作缺少校验信息"),
        ("这张确认卡片已经失效", "这次待采纳内容已经失效"),
        ("这张确认卡片和当前待确认操作不一致", "这次操作和当前待采纳内容不一致"),
        ("这张确认卡片的操作类型不完整", "这次操作类型不完整"),
        ("这张确认卡片缺少可执行内容", "这次待采纳内容缺少可执行内容"),
        ("确认卡片还没有采纳", "这次内容还没有采纳"),
        ("这张确认卡片还没有采纳", "这次内容还没有采纳"),
        ("确认卡片里的“采纳”", "“采纳”"),
        ("点击卡片里的“采纳”", "点击“采纳”"),
        ("点击最新确认卡片", "点最新内容里的“采纳”"),
        ("最新确认卡片", "最新待采纳内容"),
        ("最新采纳卡片", "最新待采纳内容"),
        ("重新生成确认卡片", "重新列出待采纳内容"),
        ("生成确认卡片", "列出待采纳内容"),
        ("整理成确认卡片", "列出来让你采纳"),
        ("确认卡片", "待采纳内容"),
        ("点击卡片采纳", "点“采纳”"),
        ("点击卡片确认", "点“确认执行”"),
        ("点击卡片", "点“采纳”"),
        ("卡片采纳后", "采纳后"),
        ("卡片确认", "确认"),
        ("硬性要求", "必须满足或必须避开的报考条件"),
        ("硬要求", "必须满足或必须避开的报考条件"),
        ("硬约束", "必须满足或必须避开的报考条件"),
        ("软偏好", "优先考虑的方向"),
        ("软意向", "优先考虑的方向"),
        ("志愿组", "专业组"),
        ("加入画像", "记成后续报考参考"),
        ("纳入画像", "纳入后续报考参考"),
        ("写入画像", "记成后续报考参考"),
        ("更新画像", "更新后续报考参考"),
        ("新的画像结论", "新的报考参考结论"),
        ("画像结论", "报考参考结论"),
        ("画像系统", "报考参考信息"),
        ("当前画像", "当前报考参考信息"),
        ("已有画像", "已有报考参考信息"),
        ("用户画像", "报考参考信息"),
        ("学生画像", "学生报考参考信息"),
        ("画像", "报考参考信息"),
        ("工具识别时", "这里需要注意的是"),
        ("工具识别", "这里"),
        ("工具返回", "查询结果"),
        ("工具调用", "处理过程"),
        ("被系统标记为", "属于"),
        ("系统标记为", "归为"),
        ("系统检测到", "我看到"),
        ("系统识别到", "我看到"),
        ("系统发现", "我看到"),
        ("系统建议", "建议"),
        ("系统提示", "当前提示"),
        ("系统给不出直接处理", "这类提醒需要你先取舍后再处理"),
        ("系统给不出", "当前还不能直接给出"),
        ("核心原因不是系统做不到，而是", "核心原因是"),
        ("不是系统做不到，而是", "主要是"),
        ("不是系统搜不到，而是", "主要是"),
        ("系统现在给不了你", "当前还没有"),
        ("系统搜不到", "当前没找到"),
        ("系统做不到", "当前条件还不够"),
        ("系统同样能替换", "也可以先列出替换预览"),
        ("系统同样能", "也可以先"),
        ("系统预估", "目前看"),
        ("系统不会擅自", "不会擅自"),
        ("系统不会", "不会"),
        ("系统需要你明确取舍范围", "需要你明确取舍范围"),
        ("系统需要你", "需要你"),
        ("系统需要找到", "需要先找到"),
        ("系统暂时给不出自动替换方案", "当前还不能直接给出替换预览"),
        ("系统暂时给不出", "当前还不能直接给出"),
        ("系统给不出自动替换方案", "当前还不能直接给出替换预览"),
        ("系统都需要你", "都需要你"),
        ("系统目前都没法直接处理", "这些提醒需要你先取舍后再处理"),
        ("系统目前都无法直接处理", "这些提醒需要你先取舍后再处理"),
        ("系统目前在", "当前在"),
        ("系统目前没找到", "当前还没找到"),
        ("系统目前没有找到", "当前还没找到"),
        ("系统会尝试", "我会先尝试"),
        ("系统只能", "当前只能"),
        ("系统可以一键", "可以先"),
        ("系统可以", "可以"),
        ("系统不知道", "我还不知道"),
        ("系统想帮你", "我可以先"),
        ("系统会帮你生成", "我会先列出"),
        ("系统会帮你", "我会"),
        ("系统会生成", "我会先列出"),
        ("系统会替换", "我会先列出替换预览"),
        ("系统暂时没法一键帮你处理", "这类提醒需要你先取舍后再处理"),
        ("系统暂时没法", "当前还不能"),
        ("系统给了", "我整理出"),
        ("系统给出", "我整理出"),
        ("系统能直接执行", "可以先列出调整预览"),
        ("系统能执行", "可以先列出调整预览"),
        ("系统没法自动执行", "这类情况需要你先取舍"),
        ("系统没法执行", "这类情况需要你先取舍"),
        ("系统换不动", "当前还缺少合适的替换方案"),
        ("系统目前没法", "当前还不能"),
        ("系统没法", "当前还不能"),
        ("系统暂时补不进", "当前还缺少合适的补位选择"),
        ("系统补不进", "当前还缺少合适的补位选择"),
        ("能否自动修复", "怎么处理"),
        ("能否自动处理", "怎么处理"),
        ("能自动处理吗", "可以怎么处理"),
        ("系统尝试", "我查了一下"),
        ("系统判断", "当前判断"),
        ("系统凑不出", "当前凑不出"),
        ("系统暂时无法", "当前暂时无法"),
        ("系统无法", "当前还不能"),
        ("自动补齐", "直接补齐"),
        ("自动补足", "先看是否能补足"),
        ("自动把", "直接把"),
        ("自动调整方案", "调整预览"),
        ("自动替换方案", "替换预览"),
        ("自动执行", "确认后再执行"),
        ("自动应用", "直接执行"),
        ("自动修复", "直接处理"),
        ("自动处理", "直接处理"),
        ("可立即处理", "可以先列出调整预览"),
        ("可以直接处理", "可以先列出调整预览"),
        ("可以自动处理", "可以先列出调整预览"),
        ("哪些可以自动处理", "哪些可以先出调整预览"),
        ("已就绪，点确认就能执行", "可以先看调整预览，确认前不会改方案"),
        ("点确认就能执行", "确认前不会改方案"),
        ("点确认就执行", "确认前不会改方案"),
        ("确认就能执行", "确认前不会改方案"),
        ("确认就执行", "确认前不会改方案"),
        ("直接确认应用", "确认后再执行"),
        ("修复预览", "调整预览"),
        ("修复结果", "处理结果"),
        ("修复方向", "处理方向"),
        ("修复", "处理"),
        ("预览参考状态", "处理方向参考"),
        ("被卡住了", "需要你先决定"),
        ("被卡住", "需要你先决定"),
        ("卡住了", "需要你先决定"),
        ("卡住", "需要你先决定"),
        ("暂时动不了", "需要你先取舍或放宽条件"),
        ("没法直接一键处理", "需要你先取舍后再处理"),
        ("无法直接一键处理", "需要你先取舍后再处理"),
        ("不能直接一键处理", "需要你先取舍后再处理"),
        ("一键处理", "直接处理"),
        ("一键替换", "替换"),
        ("一键按", "按"),
        ("候选机会池子已经见底了", "当前符合条件的可选志愿已经不多"),
        ("候选机会池子", "可选志愿范围"),
        ("给我个明确态度，我立刻处理", "你确定取舍范围后，我先列出调整预览"),
        ("给我个明确态度", "你可以先确定取舍范围"),
        ("给出明确态度", "明确取舍范围"),
        ("给个明确态度", "明确取舍范围"),
        ("给一个明确态度", "明确取舍范围"),
        ("才敢动", "再处理"),
        ("我立刻处理", "我先列出调整预览"),
        ("我就能换", "我可以先列出替换预览"),
        ("我就能处理", "我可以先列出调整预览"),
        ("我就能直接处理", "我可以先列出调整预览"),
        ("我就能帮你生成", "我会先列出"),
        ("我就能出替换方案", "我可以先列出替换预览"),
        ("我就能给你生成具体的调整预览", "我可以先列出具体调整预览"),
        ("我立刻出具体方案", "我先列出具体调整预览"),
        ("我立刻出", "我先列出"),
        ("我这边能出", "我可以先列出"),
        ("给句准话", "明确取舍范围"),
        ("技术 bug", "方案本身出错"),
        ("技术难点", "需要先注意的一点"),
        ("技术问题", "处理条件还不充分"),
        ("巧妇难为无米之炊", "当前可选志愿范围不够"),
        ("无法批量处理", "不能一次性处理完"),
        ("组内安全垫专业", "兜底专业"),
        ("组内安全垫", "兜底专业"),
        ("安全垫专业", "兜底专业"),
        ("安全垫", "兜底"),
        ("暂时无法自动补强安全垫", "当前暂时缺少合适的补位选择"),
        ("暂时无法自动补强", "当前暂时缺少合适的补位选择"),
        ("放宽约束", "放宽报考条件"),
        ("补充候选", "补充可选志愿"),
        ("需要人工调整", "需要你先取舍或手动调整"),
        ("人工调整", "手动调整"),
        ("候选池", "可选范围"),
        ("候选供给", "可选志愿"),
        ("系统阻塞", "需要你先决定是否接受调整范围变化"),
        ("被系统阻塞", "需要你先决定是否接受调整范围变化"),
        ("阻塞原因", "需要注意"),
        ("无法生成确认卡片", "还不能直接执行"),
        ("不能生成确认卡片", "还不能直接执行"),
        ("无法生成确认", "还不能直接执行"),
        ("不能生成确认", "还不能直接执行"),
        ("替换预览会改变专业组数量，需要你先取舍后再处理", "替换可能会影响整组志愿的搭配，需要你先确认哪些一定不要、哪些可以接受"),
        ("调整预览会改变专业组数量，需要你先取舍后再处理", "替换可能会影响整组志愿的搭配，需要你先确认哪些一定不要、哪些可以接受"),
        ("处理预览没有为目标专业组补足组内安全垫专业，暂不允许确认应用", "当前还没找到适合补进该专业组的兜底专业，建议先看是否放宽专业或院校范围"),
        ("处理预览没有为目标专业组补足兜底专业，暂不允许确认应用", "当前还没找到适合补进该专业组的兜底专业，建议先看是否放宽专业或院校范围"),
        ("替换预览会改变专业组数量，暂不允许确认应用", "替换可能会影响整组志愿的搭配，需要你先确认是否接受这类调整"),
        ("调整预览会改变专业组数量，暂不允许确认应用", "替换可能会影响整组志愿的搭配，需要你先确认是否接受这类调整"),
        ("替换会改变专业组数量，当前不建议直接确认", "替换可能会影响整组志愿的搭配，需要你先确认是否接受这类调整"),
        ("替换会改变专业组数量", "替换可能会影响整组志愿的搭配"),
        ("替换同样会影响专业组数量", "替换同样会影响整组志愿搭配"),
        ("会影响专业组数量", "会影响整组志愿搭配"),
        ("替换后专业组数量会变", "替换后专业组搭配会变"),
        ("会改变专业组数量", "可能会影响整组志愿的搭配"),
        ("暂不允许确认应用", "需要你先看清影响后再决定"),
        ("自动确认", "直接确认"),
        ("系统暂不支持", "当前不建议"),
        ("暂不能自动处理", "建议你先查看具体影响，或调整筛选范围后再试"),
        ("暂不能直接处理", "建议你先查看具体影响，或调整筛选范围后再试"),
        ("暂时不能直接处理", "建议你先查看具体影响，或调整筛选范围后再试"),
        ("暂时不建议直接处理", "建议先看清影响后再决定"),
        ("blocked", "需要你先决定是否接受调整范围变化"),
        ("preview_only", "先作为处理方向参考"),
        ("草稿方案", "方案"),
        ("方案草稿", "方案"),
        ("草稿", "方案"),
        ("已应用修复建议", "已按处理建议更新方案"),
        ("修复建议：", "处理内容："),
        ("修复建议", "处理建议"),
        ("修复类型：", "处理方式："),
        ("应用前预览：", "处理前预览："),
        ("复验结果：本次对应问题已通过复验。", "检查结果：这次对应的问题已通过检查。"),
        ("复验结果：仍需要继续检查相关风险。", "检查结果：还需要继续关注相关风险。"),
    )
    normalized = reply
    for source, target in replacements:
        normalized = normalized.replace(source, target)
    normalized = normalized.replace("待采纳内容采纳", "采纳")
    normalized = normalized.replace("点“采纳”里的“采纳”", "点“采纳”")
    normalized = normalized.replace("点击“采纳”里的“采纳”", "点击“采纳”")
    normalized = normalized.replace("请按最新待采纳内容操作", "请以最新内容为准操作")
    normalized = normalized.replace("以最新待采纳内容为准", "以最新内容为准")
    normalized = normalized.replace("必须满足或必须避开的报考条件过滤", "按已确认的报考条件过滤")
    normalized = normalized.replace("必须满足或必须避开的报考条件命中项", "已确认报考条件命中的志愿")
    normalized = normalized.replace("对英语能力有需要确认的报考条件", "对英语能力有明确要求")
    normalized = normalized.replace("对英语能力有必须满足或必须避开的报考条件", "对英语能力有明确要求")
    normalized = re.sub(
        r"对([^，。！？\n]{1,12})有必须满足或必须避开的报考条件",
        r"对\1有明确要求",
        normalized,
    )
    normalized = normalized.replace("有必须满足或必须避开的报考条件", "有需要确认的报考条件")
    normalized = normalized.replace("报考参考信息信息", "报考参考信息")
    normalized = normalized.replace("当前当前", "当前")
    normalized = normalized.replace("不足，当前暂时", "不足，暂时")
    normalized = normalized.replace("直接直接", "直接")
    normalized = normalized.replace("所以 需要你先决定是否接受调整范围变化 了", "所以需要你先决定是否接受这类调整")
    normalized = normalized.replace("需要你先决定是否接受调整范围变化 了", "需要你先决定是否接受这类调整")
    normalized = normalized.replace("需要你先决定原因", "需要你先决定")
    normalized = normalized.replace("暂被阻塞", "暂时不能直接处理")
    normalized = normalized.replace("被阻塞", "暂时不能直接处理")
    normalized = normalized.replace("直接处理方向", "处理方向")
    normalized = normalized.replace("直接处理建议", "处理建议")
    normalized = normalized.replace("可以直接处理的有", "可以先看调整预览的有")
    normalized = normalized.replace("可以立即处理的有", "可以先看调整预览的有")
    normalized = normalized.replace("可以直接处理", "可以先列出调整预览")
    normalized = normalized.replace("可以立即处理", "可以先列出调整预览")
    normalized = normalized.replace("我可以直接帮你", "我可以帮你")
    normalized = normalized.replace("我直接帮你生成", "我先列出")
    normalized = normalized.replace("直接帮你生成", "先列出")
    normalized = normalized.replace("我直接生成", "我先列出")
    normalized = normalized.replace("直接生成一个", "先列出一个")
    normalized = normalized.replace("我可以在方案里把这些志愿整体移除", "我会先列出移除预览")
    normalized = re.sub(
        r"我可以直接帮你(?=(?:对比分析|对比|分析|解释|看一下|看下|看看|看|查一下|查))",
        "我可以帮你",
        normalized,
    )
    normalized = normalized.replace("直接执行方向", "处理方向")
    normalized = normalized.replace("直接执行，不需要你逐条挑", "确认后再执行，不需要你逐条挑")
    normalized = normalized.replace("你确认后就能直接执行", "确认后再执行")
    normalized = normalized.replace("你确认后就能执行", "确认后再执行")
    normalized = normalized.replace("确认后就能直接执行", "确认后再执行")
    normalized = normalized.replace("确认后就能执行", "确认后再执行")
    normalized = normalized.replace("需要你先取舍或放宽条件原因", "需要你先取舍或放宽条件")
    normalized = normalized.replace("当前还缺少合适的替换方案。候选", "当前还缺少合适的替换方案，候选")
    normalized = normalized.replace("没法自动替换", "不能直接替换")
    normalized = normalized.replace("没法一键帮你处理", "需要你先取舍后再处理")
    normalized = normalized.replace("没法直接帮你", "需要你先取舍后再")
    normalized = normalized.replace("当前还不能直接帮你", "需要你先取舍后再")
    normalized = normalized.replace("当前还不能一键替换", "需要你先取舍后再处理")
    normalized = normalized.replace("当前还不能一键帮你处理", "需要你先取舍后再处理")
    normalized = normalized.replace("核心原因不是处理条件还不充分，而是", "核心原因是")
    normalized = normalized.replace("不是处理条件还不充分，而是", "主要是")
    normalized = normalized.replace("不是方案本身出错，而是", "主要是")
    normalized = re.sub(
        r"需要你先取舍后再[“\"]?一键(?:替换|处理|删除|移出)[”\"]?",
        "需要你先取舍后再处理",
        normalized,
    )
    normalized = re.sub(
        r"需要你先取舍后再[“\"]?(?:替换|处理|删除|移出)[”\"]?",
        "需要你先取舍后再处理",
        normalized,
    )
    normalized = normalized.replace("暂时无法调整配比", "当前还缺少足够合适的志愿来调整配比")
    normalized = normalized.replace("暂时无法补齐录取率梯度", "当前还缺少足够合适的志愿来补齐录取率梯度")
    normalized = normalized.replace("暂时无法补齐梯度", "当前还缺少足够合适的志愿来补齐梯度")
    normalized = normalized.replace("目前当前还不能", "当前还不能")
    normalized = normalized.replace("目前当前还缺少", "当前还缺少")
    normalized = normalized.replace("目前当前", "当前")
    normalized = normalized.replace("当前还不能直接", "需要你先取舍后再")
    normalized = normalized.replace("暂时无法", "当前还不能")
    normalized = re.sub(
        r"(?:当前还不能|当前还无法)(?:一键)?(?:帮你)?(?:直接)?(?:替换|处理|删|删除|移出)",
        "需要你先取舍后再处理",
        normalized,
    )
    normalized = re.sub(
        r"当前还不能(?:自动|直接)?(?:把)?([^，。！？\n]{0,18}?)(?:调到|补足|补齐|处理)",
        r"当前还缺少足够条件处理\1",
        normalized,
    )
    normalized = normalized.replace("当前还缺少足够条件处理冲区志愿", "当前还缺少足够合适的志愿来调整冲稳保结构")
    normalized = re.sub(
        r"(?:当前还缺少合适的补位选择|当前还不能补不进)(?:更合适的)?兜底专业",
        "当前还缺少更合适的兜底专业",
        normalized,
    )
    normalized = normalized.replace("需要先人工精简", "需要你先手动精简")
    normalized = normalized.replace("人工精简", "手动精简")
    normalized = re.sub(r"(?:能不能换|能否换|能不能处理)[：:]\s*想换，但", "处理方式：", normalized)
    normalized = re.sub(r"(?:卡在哪|为什么动不了)[：:]", "需要先看清：", normalized)
    normalized = re.sub(
        r"(你(?:给|先给)我[^。！？\n]{0,20}?明确[^。！？\n]{0,20}?，?)(?:我(?:立刻|马上|就能|可以直接)[^。！？\n]{0,30}?)([。！？]?)",
        r"你可以先明确取舍范围，我会先列出调整预览\2",
        normalized,
    )
    normalized = re.sub(
        r"(?:我(?:立刻|马上|就能|可以直接)(?:帮你)?(?:处理|换|调整|执行))",
        "我先列出调整预览",
        normalized,
    )
    normalized = normalized.replace("你现在的可选范围里", "当前候选志愿里")
    normalized = normalized.replace("当前可用于规划的可选范围里", "当前候选志愿里")
    normalized = normalized.replace("可选范围里", "候选志愿里")
    normalized = re.sub(r"[✅⏳📝⚠️❗️⭐️]+", "", normalized)
    normalized = normalized.replace("您", "你")
    if any(token in normalized for token in ("方案", "志愿", "候选")):
        plan_add_replacements = (
            ("添加预览", "加入方案预览"),
            ("添加建议", "加入方案建议"),
            ("确认要添加吗", "确认加入方案吗"),
            ("确认添加吗", "确认加入方案吗"),
            ("要添加吗", "要加入方案吗"),
            ("执行添加", "执行加入方案"),
            ("执行后会将该志愿补入方案", "执行后会将该志愿加入方案"),
        )
        for source, target in plan_add_replacements:
            normalized = normalized.replace(source, target)
    return normalized


def _plan_reply_needs_normalization(reply: str) -> bool:
    """Only guard severe user-experience failures, not natural model formatting."""
    if any(marker in reply for marker in _PLAN_STYLE_SEVERE_MARKERS):
        return True
    if "专业组" in reply and re.search(r"前\s*\d+\s*位概况", reply):
        return True
    return any(line.strip() in _PLAN_STYLE_DANGLING_EXACT_LINES for line in reply.splitlines())


def _normalize_plan_reply_style(reply: str) -> str:
    """Thin service guard for severe Plan reply wording; natural Markdown/lists are allowed."""
    if not reply.strip():
        return reply

    normalized_lines: list[str] = []
    skip_unit_position_list = False
    for raw_line in reply.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            skip_unit_position_list = False
            if normalized_lines and normalized_lines[-1] != "":
                normalized_lines.append("")
            continue
        if (
            "专业组" in reply
            and re.search(r"前\s*\d+\s*位概况", stripped)
        ):
            skip_unit_position_list = True
            continue
        if skip_unit_position_list and re.match(r"^\d+[.、]\s*", stripped):
            continue
        if skip_unit_position_list and (
            "—" in stripped or "-" in stripped or "专业组" in stripped or "第" in stripped
        ):
            continue
        skip_unit_position_list = False
        if stripped in _PLAN_STYLE_DANGLING_EXACT_LINES:
            continue
        line = raw_line.replace("补偿预览", "补齐建议")
        if any(marker in line for marker in _PLAN_STYLE_SEVERE_MARKERS if marker != "补偿预览"):
            sentence_parts = re.findall(r"[^。！？.!?]+[。！？.!?]?", line)
            kept_parts = [
                part
                for part in sentence_parts
                if not any(marker in part for marker in _PLAN_STYLE_SEVERE_MARKERS if marker != "补偿预览")
            ]
            line = "".join(kept_parts).strip()
        if not line.strip():
            continue
        normalized_lines.append(line.rstrip())

    while normalized_lines and normalized_lines[0] == "":
        normalized_lines.pop(0)
    while normalized_lines and normalized_lines[-1] == "":
        normalized_lines.pop()

    if not any(line.strip() for line in normalized_lines):
        return "我先给出当前判断。你可以继续看结论、调整建议，或在确认后执行具体改动。"

    return "\n".join(normalized_lines)


def _append_plan_preview_confirmation_boundary(
    reply: str,
    new_messages: list[Any] | None,
) -> str:
    """Make current-turn Plan previews explicit when the model skipped execute_plan_action."""
    if not reply.strip():
        non_actionable_result = _latest_non_actionable_plan_result(new_messages)
        if non_actionable_result:
            return _non_actionable_plan_preview_boundary(non_actionable_result)
        return reply
    confirmation_candidate = _extract_plan_confirmation_candidate(new_messages)
    if _tool_returns_successful_plan_apply(new_messages):
        return reply
    asks_confirmation = _reply_has_plan_confirmation_request(reply)
    if not confirmation_candidate:
        non_actionable_result = _latest_non_actionable_plan_result(new_messages)
        fix_proposal_preview_result = _latest_fix_proposal_preview_result(new_messages)
        if asks_confirmation:
            if not non_actionable_result and not fix_proposal_preview_result and not _tool_returns_plan_mutation_context(new_messages):
                return reply
            reply = _remove_unbacked_plan_confirmation_copy(reply)
            boundary = _non_actionable_plan_preview_boundary(
                non_actionable_result
                or fix_proposal_preview_result
                or _latest_non_actionable_plan_mutation_result(new_messages)
            )
            stripped_reply = reply.strip()
            if not stripped_reply:
                return boundary
            return f"{stripped_reply}\n\n{boundary}"
        if non_actionable_result and any(marker in reply for marker in ("补偿环节", "技术问题", "无法进入可执行")):
            stripped = _remove_unbacked_plan_confirmation_copy(reply).strip()
            if not stripped or any(marker in stripped for marker in ("补偿环节", "技术问题", "无法进入可执行")):
                return _NO_EXECUTABLE_PLAN_PREVIEW_REPLY
            return f"{stripped}\n\n{_non_actionable_plan_preview_boundary(non_actionable_result)}"
        if non_actionable_result and _reply_is_internal_plan_error(reply):
            return _non_actionable_plan_preview_boundary(non_actionable_result)
        return reply
    action_family = str(confirmation_candidate.get("action_family") or "")
    if action_family not in _PENDING_PLAN_ACTION_FAMILIES:
        return reply
    unit_kind = _plan_confirmation_candidate_unit_kind(confirmation_candidate)
    if action_family in {"move_ordered_unit", "remove_ordered_unit"} and unit_kind != "志愿":
        compact_reply = _compact_plan_reply_text(reply)
        if "不是按单条志愿位置" not in compact_reply and "按专业组顺序计算" not in compact_reply:
            reply = (
                reply.rstrip()
                + "\n\n位置说明：这里的“第几个”按专业组顺序计算，不是按单条志愿位置计算；组内专业会保持连续。"
            )
    if _reply_conflicts_with_plan_confirmation_candidate(reply):
        return _build_plan_confirmation_preview_reply(confirmation_candidate)
    if asks_confirmation:
        return reply
    return reply.rstrip() + "\n\n如果你确认要这样做，我再执行；现在还不会改动方案。"


def _reply_is_internal_plan_error(reply: str) -> bool:
    if not isinstance(reply, str):
        return False
    compact = _compact_plan_reply_text(reply)
    return compact in {"会话不存在", "sessionnotfound", "chat session not found"} or bool(
        re.fullmatch(r"(?:错误|异常)[:：]?.{0,30}", compact)
    )


def _plan_confirmation_candidate_unit_kind(confirmation_candidate: dict[str, Any] | None) -> str:
    if not isinstance(confirmation_candidate, dict):
        return ""
    payload = confirmation_candidate.get("plan_payload")
    if not isinstance(payload, str) or not payload.strip():
        return ""
    try:
        data = json.loads(payload)
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    facts = data.get("facts") if isinstance(data.get("facts"), dict) else {}
    unit_kind = str(facts.get("unit_kind") or facts.get("unitKind") or "").strip()
    return unit_kind if unit_kind in {"志愿", "专业组"} else ""


def _plan_confirmation_candidate_is_explicit_atomic_target(
    confirmation_candidate: dict[str, Any] | None,
) -> bool:
    if not isinstance(confirmation_candidate, dict):
        return False
    action_family = str(confirmation_candidate.get("action_family") or "").strip()
    if action_family not in {"add_units", "remove_units", "replace_units"}:
        return False
    payload = confirmation_candidate.get("plan_payload")
    if not isinstance(payload, str) or not payload.strip():
        return False
    try:
        data = json.loads(payload)
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    if data.get("composite_proposal") or data.get("compositeProposal"):
        return False
    if isinstance(data.get("intent_update"), dict) or isinstance(data.get("intentUpdate"), dict):
        return False
    atomic_actions = data.get("atomic_actions") if isinstance(data.get("atomic_actions"), list) else []
    for action in atomic_actions:
        if not isinstance(action, dict):
            continue
        volunteer_ids = _as_text_list(action.get("volunteer_ids") or action.get("volunteerIds"))
        if volunteer_ids:
            return True
    return False


def _pending_state_constraint_intent_type(pending_state: dict[str, Any] | None) -> str:
    if not isinstance(pending_state, dict):
        return ""
    direct = str(
        pending_state.get("constraintIntentType")
        or pending_state.get("constraint_intent_type")
        or ""
    ).strip()
    if direct:
        return direct
    execution_payload = pending_state.get("executionPayload")
    if not isinstance(execution_payload, dict):
        return ""
    for source in (
        execution_payload,
        execution_payload.get("selectedData"),
        execution_payload.get("intentPayload"),
    ):
        if not isinstance(source, dict):
            continue
        value = str(
            source.get("constraintIntentType")
            or source.get("constraint_intent_type")
            or ""
        ).strip()
        if value:
            return value
    return ""


def _plan_confirmation_candidate_payload(
    confirmation_candidate: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(confirmation_candidate, dict):
        return {}
    payload = confirmation_candidate.get("plan_payload")
    if not isinstance(payload, str) or not payload.strip():
        return {}
    try:
        parsed = json.loads(payload)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _plan_candidate_intent_update(
    confirmation_candidate: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(confirmation_candidate, dict):
        return {}
    direct = confirmation_candidate.get("intent_update") or confirmation_candidate.get("intentUpdate")
    if isinstance(direct, dict) and direct:
        return direct
    payload = _plan_confirmation_candidate_payload(confirmation_candidate)
    if not payload:
        return {}
    for source in (
        payload,
        payload.get("facts") if isinstance(payload.get("facts"), dict) else None,
    ):
        if not isinstance(source, dict):
            continue
        value = source.get("intent_update") or source.get("intentUpdate")
        if isinstance(value, dict) and value:
            return value
    return {}


def _plan_candidate_structured_goal_type(
    confirmation_candidate: dict[str, Any] | None,
) -> str:
    payload = _plan_confirmation_candidate_payload(confirmation_candidate)
    if not payload:
        return ""
    composite = payload.get("composite_proposal") or payload.get("compositeProposal")
    if not isinstance(composite, dict):
        return ""
    goal = composite.get("goal")
    if not isinstance(goal, dict):
        return ""
    return str(goal.get("goal_type") or goal.get("goalType") or "").strip()


def _merged_selected_intent_payload(intent_payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(intent_payload, dict):
        return {}
    merged = _merge_selected_intent_payload(intent_payload)
    return merged if merged else intent_payload


def _plain_plan_candidate_conflicts_with_active_only_keep_intent(
    pending_state: dict[str, Any] | None,
    confirmation_candidate: dict[str, Any] | None,
) -> bool:
    """Prevent an active only-keep intent from being replaced by a derived removal list.

    The unified path for only-keep goals is Intent/UserGoal -> Java FixProposal.
    A plain execute_plan_action/remove_units card that only carries generated
    negative complements is a model-side expansion, not a safe replacement for
    the active pending only-keep state.
    """
    if not isinstance(pending_state, dict) or not isinstance(confirmation_candidate, dict):
        return False
    if str(pending_state.get("status") or "").strip() != "active":
        return False
    if str(pending_state.get("kind") or "").strip() != "intent_change":
        return False
    if _pending_state_constraint_intent_type(pending_state) != "only_keep":
        return False
    if _plan_candidate_structured_goal_type(confirmation_candidate) == "only_keep_scope":
        return False

    action_family = str(confirmation_candidate.get("action_family") or "").strip()
    if action_family not in {"remove_units", "replace_units", "add_units", "generate_plan"}:
        return False
    intent_update = _plan_candidate_intent_update(confirmation_candidate)
    if not intent_update:
        return False
    candidate_constraint_type = str(
        intent_update.get("constraintIntentType")
        or intent_update.get("constraint_intent_type")
        or ""
    ).strip()
    if candidate_constraint_type == "only_keep":
        return False
    merged_intent = _merged_selected_intent_payload(intent_update)
    return _intent_payload_has_negative_value(merged_intent) and not _intent_payload_has_positive_value(merged_intent)


def _compact_plan_reply_text(reply: str) -> str:
    return re.sub(r'[\s"“”‘’`\'「」『』【】\[\]（）()<>《》:：,，。.!！？?、]+', "", str(reply or ""))


def _reply_has_plan_confirmation_request(reply: str) -> bool:
    compact = _compact_plan_reply_text(reply)
    if not compact or "确认" not in compact:
        return False
    if any(marker in compact for marker in ("无法进入可执行", "没有上一轮待确认", "还没有拿到可执行", "技术问题")):
        return False
    if ("如果你确认" in compact or "你确认后" in compact) and any(
        keyword in compact
        for keyword in (
            "执行调整",
            "执行修改",
            "执行改动",
            "执行替换",
            "直接调整",
            "直接修改",
            "直接改动",
            "删除志愿",
            "移除志愿",
            "移动志愿",
            "移出",
            "重排方案",
            "调整方案",
            "改动方案",
            "更新方案",
        )
    ):
        return True
    return any(
        marker in compact
        for marker in (
            "回复确认",
            "确认即可",
            "确认后",
            "确认应用",
            "确认执行",
            "确认替换",
            "确认生成",
            "确认重排",
            "确认要",
        )
    )


def _reply_conflicts_with_plan_confirmation_candidate(reply: str) -> bool:
    compact = _compact_plan_reply_text(reply)
    return any(
        marker in compact
        for marker in (
            "无法进入可执行",
            "没有上一轮待确认",
            "还没有拿到可执行",
            "系统在补偿环节遇到",
            "技术问题",
            "现在还不会改动方案",
        )
    )


def _build_plan_confirmation_preview_reply(confirmation_candidate: dict[str, Any]) -> str:
    summary = str(confirmation_candidate.get("summary") or "").strip()
    summary = summary.replace("补偿", "补齐")
    title = "调整预览已生成。"
    boundary = "如果你确认要这样做，我再执行；现在还不会改动方案。"
    body = f"\n\n{summary}" if summary else ""
    return f"{title}{body}\n\n{boundary}"


def _plan_summary_is_low_information(summary: str) -> bool:
    compact = _compact_plan_reply_text(summary)
    if not compact:
        return True
    return any(
        marker in compact
        for marker in (
            "这轮我先把影响范围和可选方向说明清楚",
            "不会直接改动当前方案",
            "需要你确认后才会执行",
        )
    ) and not any(
        marker in compact
        for marker in ("补入", "移出", "替换", "移动", "排序", "生成", "补齐")
    )


def _fallback_plan_confirmation_candidate_summary(confirmation_candidate: dict[str, Any]) -> str:
    action_family = str(confirmation_candidate.get("action_family") or "").strip()
    user_goal = str(confirmation_candidate.get("user_goal") or "").strip()
    action_text = {
        "generate_plan": "根据当前候选和当前报考信息生成或补齐方案。",
        "add_units": "把符合条件的候选加入当前方案。",
        "remove_units": "从当前方案里移出命中的志愿。",
        "replace_units": "用更合适的候选替换当前方案里的命中项。",
        "sort_ordered_plan": "按指定规则重新排列当前方案。",
        "regenerate_order": "重新生成当前排序方案。",
        "move_unit": "移动当前方案里的指定志愿。",
        "move_ordered_unit": "移动当前排序里的指定位置。",
        "remove_ordered_unit": "移出当前排序里的指定位置。",
    }.get(action_family, "按这次要求生成一版调整预览。")
    if user_goal:
        return f"{action_text}\n\n本次要求：{user_goal}"
    return action_text


def _plan_confirmation_candidate_summary_for_user(confirmation_candidate: dict[str, Any]) -> str:
    summary = str(confirmation_candidate.get("summary") or confirmation_candidate.get("preview_summary") or "").strip()
    summary = _normalize_user_facing_terms(summary.replace("补偿", "补齐"))
    if _plan_summary_is_low_information(summary):
        return _fallback_plan_confirmation_candidate_summary(confirmation_candidate)
    return summary


def _plan_confirmation_card_primary_reply(confirmation_candidate: dict[str, Any]) -> str:
    summary = _plan_confirmation_candidate_summary_for_user(confirmation_candidate)
    if summary:
        summary = re.sub(r"(?:需要你)?确认后才会执行[。；;]?", "", summary).strip("；;。 \n")
        reply = f"已列出调整预览：{summary}。"
    else:
        reply = "已列出调整预览。"
    return _sanitize_reply_for_user(f"{reply}\n\n确认前不会改动当前方案。")


def _remove_current_turn_mutating_plan_preview(messages: list[Any] | None) -> None:
    """Rewrite mutating Plan preview returns so they cannot become stale pending state.

    This is a side-effect safety boundary for explicit read-only prompts. It does
    not route the request; it only prevents a model/tool detour from leaving a
    confirmable add/remove/move/sort preview after the user said to only inspect.
    """
    for part in _iter_tool_return_parts(messages):
        if part.tool_name not in {"plan_next_action", "execute_plan_action"}:
            continue
        data = _parse_tool_return_json(part.content)
        if not data:
            continue
        action_family = str(data.get("action_family") or "").strip()
        effective_family = action_family
        result_kind = str(data.get("result_kind") or "").strip()
        if effective_family not in _PENDING_PLAN_ACTION_FAMILIES:
            continue
        if result_kind != "preview_only" and data.get("stage") != "preview":
            continue
        data["stage"] = "apply"
        data["action_family"] = "query_candidates" if effective_family == "add_units" else "query_ordered"
        data["result_kind"] = "candidate_snapshot" if effective_family == "add_units" else "ordered_snapshot"
        data["applied"] = True
        data["requires_confirmation"] = False
        data["should_rerun_review"] = False
        data["should_refresh_workspace"] = False
        data["workspace_refresh_targets"] = []
        data["reply_focus"] = [str(data["result_kind"])]
        data["summary"] = _READONLY_MUTATION_GUARD_REPLY
        data.pop("preview_summary", None)
        part.content = json.dumps(data, ensure_ascii=False)


def _line_looks_like_unbacked_plan_confirmation(compact: str) -> bool:
    if "确认" not in compact:
        return False
    normalized = _compact_plan_reply_text(compact)
    if normalized.strip("*#：:？?") in {"确认替换吗", "确认执行吗", "确认修改吗", "确认改动吗"}:
        return True
    if "确认" in normalized and any(
        keyword in normalized
        for keyword in ("即可执行", "就执行", "立即执行", "执行替换", "执行修改", "执行改动")
    ):
        return True
    return any(
        marker in normalized
        for marker in (
            "确认后会执行",
            "确认后执行",
            "点击确认后生效",
            "确认后生效",
            "确认即可执行",
            "回复确认即可",
            "回复确认后",
            "确认要删除吗",
            "确认要移除吗",
            "确认要去掉吗",
            "确认要调整吗",
            "确认要这样",
            "确认要我",
        )
    )


def _remove_unbacked_plan_confirmation_copy(reply: str) -> str:
    """Remove apply-confirmation copy when no reusable Plan preview payload exists."""
    if not isinstance(reply, str) or not reply.strip():
        return reply

    normalized_lines: list[str] = []
    for raw_line in reply.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            if normalized_lines and normalized_lines[-1] != "":
                normalized_lines.append("")
            continue
        if stripped == "**":
            continue
        compact = re.sub(r"\s+", "", stripped)
        if _line_looks_like_unbacked_plan_confirmation(compact):
            continue
        if _UNBACKED_CONFIRM_SENTENCE_RE.search(compact):
            continue
        sentence_parts = re.findall(r"[^。！？.!?]+[。！？.!?]?", raw_line)
        if not sentence_parts:
            normalized_lines.append(raw_line.rstrip())
            continue
        kept_parts = []
        for part in sentence_parts:
            compact_part = re.sub(r"\s+", "", part)
            if _line_looks_like_unbacked_plan_confirmation(compact_part):
                continue
            if _UNBACKED_CONFIRM_SENTENCE_RE.search(compact_part):
                continue
            if (
                ("如果确认" in compact_part or "如果你确认" in compact_part or "你确认后" in compact_part)
                and any(keyword in compact_part for keyword in ("我会", "将会", "直接", "执行", "替换", "修改", "改动"))
            ):
                continue
            kept_parts.append(part)
        line = "".join(kept_parts).rstrip()
        if line.strip():
            normalized_lines.append(line)

    while normalized_lines and normalized_lines[0] == "":
        normalized_lines.pop(0)
    while normalized_lines and normalized_lines[-1] == "":
        normalized_lines.pop()
    return "\n".join(normalized_lines)


def _reply_looks_like_unbacked_plan_confirmation(reply: str) -> bool:
    """Detect model-written Plan confirmation copy that has no card payload.

    This is a protocol safety check on the final reply, not a user-intent
    router. It only fires after the model has already produced text that asks
    the user to confirm a plan mutation without a pending card.
    """
    if not isinstance(reply, str) or not _reply_has_plan_confirmation_request(reply):
        return False
    compact = _compact_plan_reply_text(reply)
    if not compact:
        return False
    if any(marker in compact for marker in ("确认卡片", "点击卡片", "没有生成可点击", "不会改动当前方案")):
        return False
    has_plan_subject = any(
        marker in compact
        for marker in (
            "方案",
            "志愿",
            "专业组",
            "候选",
            "当前方案",
        )
    )
    has_mutation_effect = any(
        marker in compact
        for marker in (
            "删除",
            "删掉",
            "去掉",
            "移除",
            "移出",
            "加入",
            "添加",
            "替换",
            "换成",
            "移动",
            "挪到",
            "排序",
            "重排",
            "调整",
            "更新",
            "执行",
            "生效",
            "写入后续报考参考",
        )
    )
    return has_plan_subject and has_mutation_effect


def _guard_unbacked_plan_confirmation_reply(reply: str) -> str:
    """Replace unsupported Plan confirmation copy with an explicit no-card boundary."""
    if not _reply_looks_like_unbacked_plan_confirmation(reply):
        return reply
    stripped = _remove_unbacked_plan_confirmation_copy(reply).strip()
    if not stripped or _reply_has_plan_confirmation_request(stripped):
        return _UNBACKED_PLAN_CONFIRMATION_REPLY
    return f"{stripped}\n\n{_UNBACKED_PLAN_CONFIRMATION_REPLY}"


def _clean_review_fallback_text(value: Any) -> str:
    text = _normalize_user_facing_terms(_normalize_fix_proposal_user_text(str(value or "").strip()))
    text = text.replace("压根找不到", "暂时没找到")
    text = text.replace("暂时无法直接处理", "暂时不能直接处理")
    text = text.replace("暂时无法自动处理", "暂时不能直接处理")
    text = text.replace("暂时不能直接处理", "需要你先取舍或放宽条件")
    text = text.replace("建议你先查看具体影响，或调整筛选范围后再试", "需要你先看影响或放宽条件")
    text = text.replace("当前候选里", "当前候选志愿里")
    text = text.replace("当前可用于规划的候选池里", "当前候选志愿里")
    text = text.replace("当前可用于规划的可选范围里", "当前候选志愿里")
    text = re.sub(r"@(\d+)", r"第\1位", text)
    return text.strip("。；;，, ：:").strip()


def _append_unique_review_part(parts: list[str], value: str, *, limit: int = 2) -> None:
    text = _clean_review_fallback_text(value)
    if not text:
        return
    text = text.replace("补入兜底专业", "补兜底专业")
    compact = _compact_plan_reply_text(text)
    for existing in parts:
        existing_compact = _compact_plan_reply_text(existing)
        if compact == existing_compact or compact in existing_compact or existing_compact in compact:
            return
    if len(parts) < limit:
        parts.append(text)


def _review_fallback_problem_text(values: Any, *, limit: int = 3) -> str:
    if not isinstance(values, list):
        return ""
    items: list[str] = []
    for value in values:
        text = _clean_review_fallback_text(value)
        if text and text not in items:
            items.append(text)
        if len(items) >= limit:
            break
    return "；".join(items)


def _review_fallback_examples_text(values: Any, *, limit: int = 2) -> str:
    if not isinstance(values, list):
        return ""
    def shorten_example(value: str) -> str:
        text = _clean_review_fallback_text(value)
        if not text:
            return ""
        text = re.sub(r"\([^()]{18,}\)", "", text)
        text = re.sub(r"（[^（）]{18,}）", "", text)
        def keep_only_tier_label(match: re.Match[str]) -> str:
            content = (match.group(1) or match.group(2) or "").strip()
            return f"({content})" if content in {"冲", "稳", "保"} else ""

        text = re.sub(r"\(([^()]{1,20})\)|（([^（）]{1,20})）", keep_only_tier_label, text)
        text = re.sub(r"\s+", "", text)
        return text[:72].rstrip("；，,。")

    lines: list[str] = []
    seen_summaries: set[str] = set()
    seen_example_signatures: set[tuple[str, ...]] = set()
    for item in values:
        if not isinstance(item, dict):
            continue
        summary = _clean_review_fallback_text(item.get("summary"))
        compact_summary = _compact_plan_reply_text(summary)
        if compact_summary and compact_summary in seen_summaries:
            continue
        if compact_summary:
            seen_summaries.add(compact_summary)
        count_text = _clean_review_fallback_text(item.get("count_text"))
        examples: list[str] = []
        for example in (item.get("items") or [])[:2]:
            text = shorten_example(example)
            if text:
                examples.append(text)
        example_signature = tuple(_compact_plan_reply_text(example) for example in examples)
        if example_signature and example_signature in seen_example_signatures:
            continue
        if example_signature:
            seen_example_signatures.add(example_signature)
        parts = [part for part in (summary, count_text) if part]
        if examples:
            parts.append("例如：" + "；".join(examples))
        if parts:
            lines.append("，".join(parts))
        if len(lines) >= limit:
            break
    return "；".join(lines)


def _review_fallback_fix_proposal_lines(fix_facts: dict[str, Any], *, limit: int = 3) -> tuple[list[str], list[str]]:
    ready: list[str] = []
    needs_decision: list[str] = []
    proposals = fix_facts.get("proposals") if isinstance(fix_facts.get("proposals"), list) else []
    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        title = _clean_review_fallback_text(proposal.get("title")) or "处理方向"
        title = re.sub(r"(需要你先取舍或放宽条件|需要你先决定取舍或放宽条件)$", "", title).strip()
        title = title or "处理方向"
        status = str(proposal.get("status") or "").strip()
        strategy = _FIX_PROPOSAL_STRATEGY_TEXT.get(str(proposal.get("strategy") or "").strip(), "")
        summary = _clean_review_fallback_text(proposal.get("summary"))
        reason = _clean_review_fallback_text(proposal.get("blocking_reason") or proposal.get("blockingReason"))
        shortages = []
        for shortage in proposal.get("candidate_shortages") or proposal.get("candidateShortages") or []:
            if not isinstance(shortage, dict):
                continue
            message = _clean_review_fallback_text(shortage.get("message"))
            if message and message not in shortages:
                shortages.append(message)
        detail_parts: list[str] = []
        if status == "ready":
            _append_unique_review_part(detail_parts, strategy)
            action_summaries = [
                _clean_review_fallback_text(item)
                for item in (proposal.get("action_summaries") or proposal.get("actionSummaries") or [])[:1]
                if _clean_review_fallback_text(item)
            ]
            for action_summary in action_summaries:
                _append_unique_review_part(detail_parts, action_summary)
            if not detail_parts:
                _append_unique_review_part(detail_parts, summary)
        else:
            for part in (reason, *shortages[:1], summary):
                _append_unique_review_part(detail_parts, part)
                if detail_parts:
                    break
        line = title
        if detail_parts:
            line += "：" + "；".join(detail_parts[:2])
        if status == "ready":
            if line not in ready:
                ready.append(line)
        elif line not in needs_decision:
            needs_decision.append(line)
        if len(ready) >= limit and len(needs_decision) >= limit:
            break
    return ready[:limit], needs_decision[:limit]


def _append_review_fix_proposal_sections(
    lines: list[str],
    ready_lines: list[str],
    needs_decision_lines: list[str],
) -> None:
    if ready_lines:
        lines.extend(["", "可以先看调整预览的："])
        for item in ready_lines[:3]:
            lines.append(f"- {item}。")
    if needs_decision_lines:
        lines.extend(["", "需要你先取舍或放宽条件的："])
        for item in needs_decision_lines[:3]:
            lines.append(f"- {item}。")


def _review_fallback_proposal_reason(proposal: dict[str, Any]) -> str:
    reason = _clean_review_fallback_text(proposal.get("blocking_reason") or proposal.get("blockingReason"))
    shortages: list[str] = []
    for shortage in proposal.get("candidate_shortages") or proposal.get("candidateShortages") or []:
        if not isinstance(shortage, dict):
            continue
        message = _clean_review_fallback_text(shortage.get("message"))
        if message and message not in shortages:
            shortages.append(message)
    summary = _clean_review_fallback_text(proposal.get("summary"))
    for part in (reason, *shortages[:1], summary):
        if part:
            return part
    return "需要你先决定取舍范围，暂时不适合直接改方案"


def _review_fallback_proposal_next_step(proposal: dict[str, Any]) -> str:
    title = _clean_review_fallback_text(proposal.get("title"))
    strategy = str(proposal.get("strategy") or "").strip()
    combined = f"{title} {_clean_review_fallback_text(proposal.get('summary'))}"
    if "高收费" in combined:
        return "先确认高收费项目是全部不要、部分保留，还是预算可以接受"
    if "中外合作" in combined:
        return "先确认中外合作项目是否接受；如果不接受，我再列替换预览"
    if "非意向" in combined or "兜底" in combined:
        return "先确认更看重学校层次还是专业匹配；如果排斥这类兜底专业，再看是否整组替换"
    if strategy in {"rebalance_tier_ratio", "fill_probability_gap", "add_safety_items"}:
        return "可以先放宽地域、专业或院校层次范围，再重新审查可补机会"
    if "数量" in combined or "超" in combined:
        return "先手动精简 1 个最不想去的志愿，再重新审查"
    return "先告诉我你能接受哪些取舍，我再列调整预览"


def _build_review_unavailable_guidance_fallback_lines(facts: dict[str, Any]) -> list[str]:
    fix_facts = facts.get("fix_proposals") if isinstance(facts.get("fix_proposals"), dict) else {}
    proposals = fix_facts.get("proposals") if isinstance(fix_facts.get("proposals"), list) else []
    blocked: list[dict[str, Any]] = [
        proposal
        for proposal in proposals
        if isinstance(proposal, dict)
        and str(proposal.get("status") or "").strip() in {"blocked", "preview_only"}
    ]
    if not blocked:
        return _build_review_result_fallback_lines(facts)

    lines = ["我看了一下，不能直接处理的点主要卡在“取舍范围还没定”或“可替换机会不够”。", ""]
    for index, proposal in enumerate(blocked[:4], start=1):
        title = _clean_review_fallback_text(proposal.get("title")) or "这条提醒"
        title = re.sub(r"(需要你先取舍或放宽条件|需要你先决定取舍或放宽条件)$", "", title).strip() or title
        reason = _review_fallback_proposal_reason(proposal)
        next_step = _review_fallback_proposal_next_step(proposal)
        lines.append(f"{index}. **{title}**")
        lines.append(f"- 为什么现在不直接改：{reason}。")
        lines.append(f"- 你可以怎么调：{next_step}。")
        lines.append("")

    lines.append("你可以先选最想处理的一类，我会先列出调整预览，确认前不会改动当前方案。")
    return lines


def _build_review_result_fallback_lines(facts: dict[str, Any]) -> list[str]:
    risk_count = _as_int(facts.get("risk_count"))
    warn_count = _as_int(facts.get("warn_count"))
    plan_total = _as_int(facts.get("plan_total"))
    target_total = _as_int(facts.get("target_total"))
    tier_text = _format_status_tier_counts(facts.get("tier_counts"))
    lines = ["我已经完成当前方案审查，先说结论：", ""]
    status_parts = [f"风险 {risk_count} 项", f"提醒 {warn_count} 项"]
    if plan_total > 0:
        target = target_total or plan_total
        status_parts.insert(0, f"方案 {plan_total}/{target} 个志愿")
    if tier_text:
        status_parts.append(f"冲稳保 {tier_text}")
    lines.append("- " + "，".join(status_parts) + "。")

    problems = _review_fallback_problem_text(facts.get("main_problems"))
    if problems:
        lines.append(f"- 主要需要留意：{problems}。")

    examples = _review_fallback_examples_text(facts.get("issue_hit_plan_examples"))
    if examples:
        lines.append(f"- 典型例子：{examples}。")

    relation = facts.get("intent_relation") if isinstance(facts.get("intent_relation"), dict) else {}
    conflict = _clean_review_fallback_text(str(relation.get("conflict_examples") or "").removeprefix("需关注冲突："))
    if conflict:
        lines.append(f"- 和已确认想法冲突的例子：{conflict}。")

    fix_facts = facts.get("fix_proposals") if isinstance(facts.get("fix_proposals"), dict) else {}
    ready_lines, needs_decision_lines = _review_fallback_fix_proposal_lines(fix_facts)
    _append_review_fix_proposal_sections(lines, ready_lines, needs_decision_lines)

    lines.extend([
        "",
        "如果你想继续处理，可以先选一类让我展开影响；需要改方案时，我会先列出预览，确认前不会改动当前方案。",
    ])
    return lines


def _build_adjustment_analysis_fallback_lines(facts: dict[str, Any]) -> list[str]:
    lines = ["我看了当前方案的优化空间和可处理方向，先说结论：", ""]
    fix_facts = facts.get("fix_proposals") if isinstance(facts.get("fix_proposals"), dict) else {}
    ready_lines, needs_decision_lines = _review_fallback_fix_proposal_lines(fix_facts)
    examples = _review_fallback_examples_text(facts.get("review_issue_hit_plan_examples"))
    problems = _review_fallback_problem_text(facts.get("main_problems"), limit=2)

    actionable_counts = facts.get("actionable_suggestion_counts") if isinstance(facts.get("actionable_suggestion_counts"), dict) else {}
    has_actionable = any(
        _as_int(actionable_counts.get(key)) > 0
        for key in ("add", "reorder", "replace", "remove")
    ) or bool(ready_lines)

    if has_actionable:
        if ready_lines:
            _append_review_fix_proposal_sections(lines, ready_lines, [])
        else:
            lines.append("- 有可继续细看的调整方向，但需要先生成预览；确认前不会改动当前方案。")
    else:
        lines.append("- 这轮先拿到的是分析结论，还没有形成可以直接执行的完整调整清单。")

    if problems:
        lines.append(f"- 主要卡点：{problems}。")
    if examples:
        lines.append(f"- 可以优先关注的例子：{examples}。")
    if needs_decision_lines:
        _append_review_fix_proposal_sections(lines, [], needs_decision_lines)

    supply = facts.get("candidate_supply") if isinstance(facts.get("candidate_supply"), dict) else {}
    total = _as_int(supply.get("total") or supply.get("candidate_total") or supply.get("candidateTotal"))
    tier_counts = supply.get("tier_counts") or supply.get("tierCounts")
    tier_text = _format_status_tier_counts(tier_counts)
    if total > 0 or tier_text:
        supply_parts = []
        if total > 0:
            supply_parts.append(f"候选志愿约 {total} 个")
        if tier_text:
            supply_parts.append(f"冲稳保供给 {tier_text}")
        lines.append(f"- 候选情况：{'，'.join(supply_parts)}。")

    lines.extend([
        "",
        "如果你想继续处理，可以先明确最想动的一类；我会先列出调整预览，确认前不会改动当前方案。",
    ])
    return lines


def _build_fix_proposal_preview_fallback_lines(
    facts: dict[str, Any],
    *,
    summary: str = "",
) -> list[str]:
    fix_facts = facts.get("fix_proposals") if isinstance(facts.get("fix_proposals"), dict) else {}
    ready_lines, needs_decision_lines = _review_fallback_fix_proposal_lines(fix_facts)
    supply = facts.get("candidate_supply") if isinstance(facts.get("candidate_supply"), dict) else {}
    missing_tiers = [
        str(item or "").strip()
        for item in (
            supply.get("missing_supply_tiers")
            or supply.get("missingSupplyTiers")
            or []
        )
        if str(item or "").strip()
    ]

    lines: list[str] = []
    if ready_lines:
        lines.extend(["我看了当前方案，下面这些方向可以先出调整预览："])
        for item in ready_lines[:3]:
            lines.append(f"- {item}。")
    else:
        lines.extend(["我看了能不能直接补齐或调整，当前还没有足够合适的可执行预览。"])

    if missing_tiers:
        lines.append(f"- 当前缺口主要在：{'、'.join(dict.fromkeys(missing_tiers))}。")
    if needs_decision_lines:
        lines.extend(["", "暂时不能直接处理的原因："])
        for item in needs_decision_lines[:4]:
            lines.append(f"- {item}。")
    elif summary:
        lines.extend(["", _clean_review_fallback_text(summary)])

    lines.extend([
        "",
        "下一步可以先放宽地域、专业、院校层次或预算等条件，再重新审查可补机会；如果你愿意明确取舍，我再按新的范围列调整预览。确认前不会改动当前方案。",
    ])
    return lines


def _review_reply_needs_structured_fallback(reply: str, result: dict[str, Any] | None) -> bool:
    if not isinstance(result, dict) or not isinstance(reply, str):
        return False
    if str(result.get("action_family") or "").strip() != "review_plan":
        return False
    if str(result.get("result_kind") or "").strip() != "review_result":
        return False
    if any(marker in reply for marker in _REVIEW_REPLY_QUALITY_MARKERS):
        return True
    compact = _compact_plan_reply_text(reply)
    return compact.count("当前候选志愿里") >= 3 or compact.count("建议你先") >= 4


def _review_reply_overclaims_admission_safety(reply: str, result: dict[str, Any] | None) -> bool:
    """审查/调整分析结果不能被表述成录取安全承诺。"""
    if not isinstance(result, dict) or not isinstance(reply, str):
        return False
    if str(result.get("result_kind") or "").strip() not in {"review_result", "adjustment_analysis"}:
        return False
    compact = _compact_plan_reply_text(reply)
    if not compact:
        return False
    if re.search(r"(?:不能|无法|不|并不|不是)(?:保证|代表|说明|等于|意味着|说)?不会滑档", compact):
        return False
    absolute_safety = (
        re.search(r"(不会|不可能|避免|杜绝)(?:出现)?滑档", compact) is not None
        or re.search(r"不会(?:导致|造成|引发|有)?滑档", compact) is not None
        or re.search(r"没有(?:会)?导致滑档", compact) is not None
        or re.search(r"(保证|确保|一定|肯定)(?:不会)?(?:录取|不滑档|稳录|安全)", compact) is not None
        or "不会退档" in compact
        or "没有滑档风险" in compact
        or "零滑档风险" in compact
        or "整体结构是安全" in compact
        or "方案结构是安全" in compact
        or "整体结构安全" in compact
        or "方案结构安全" in compact
    )
    if not absolute_safety:
        return False
    return True


def _review_reply_needs_boundary(reply: str, result: dict[str, Any] | None) -> bool:
    if not isinstance(result, dict) or not isinstance(reply, str):
        return False
    if str(result.get("action_family") or "").strip() != "review_plan":
        return False
    if str(result.get("result_kind") or "").strip() != "review_result":
        return False
    compact = _compact_plan_reply_text(reply)
    return bool(compact) and "审查" not in compact


def _adjustment_reply_needs_structured_fallback(reply: str, result: dict[str, Any] | None) -> bool:
    if not isinstance(result, dict) or not isinstance(reply, str):
        return False
    if str(result.get("action_family") or "").strip() != "analyze_adjustment":
        return False
    if str(result.get("result_kind") or "").strip() != "adjustment_analysis":
        return False
    markers = (
        "补充建议 0 条",
        "调序建议 0 条",
        "替换建议 0 条",
        "移除建议 0 条",
        "候选供给：",
        "下面列 2 条代表例子",
        "fix_proposals",
    )
    if any(marker in reply for marker in markers):
        return True
    if re.search(r"@\d+", reply):
        return True
    compact = _compact_plan_reply_text(reply)
    return len(compact) > 900 and "调整分析已完成" in reply


def _review_prompt_prefers_unavailable_guidance(user_prompt: str | None) -> bool:
    compact = _compact_plan_reply_text(str(user_prompt or ""))
    if not compact:
        return False
    wants_reason = any(marker in compact for marker in ("为什么", "原因", "处理不了", "不能处理", "没法处理", "怎么调", "怎么改"))
    repair_context = any(marker in compact for marker in ("提醒", "审查", "风险", "处理", "调整", "修复"))
    return wants_reason and repair_context


def _result_prefers_unavailable_guidance(result: dict[str, Any], *, user_prompt: str | None = None) -> bool:
    facts = result.get("facts") if isinstance(result.get("facts"), dict) else {}
    requested_focus = {
        str(item or "").strip()
        for item in (facts.get("requested_reply_focus") or result.get("requested_reply_focus") or [])
        if str(item or "").strip()
    }
    if "unavailable_guidance" in requested_focus:
        return True
    return _review_prompt_prefers_unavailable_guidance(user_prompt)


def _result_has_unavailable_fix_proposals(result: dict[str, Any]) -> bool:
    facts = result.get("facts") if isinstance(result.get("facts"), dict) else {}
    fix_facts = facts.get("fix_proposals") if isinstance(facts.get("fix_proposals"), dict) else {}
    if _as_int(fix_facts.get("blocked_count")) + _as_int(fix_facts.get("preview_only_count")) > 0:
        return True
    proposals = fix_facts.get("proposals") if isinstance(fix_facts.get("proposals"), list) else []
    return any(
        isinstance(proposal, dict)
        and str(proposal.get("status") or "").strip() in {"blocked", "preview_only"}
        for proposal in proposals
    )


def _result_needs_unavailable_guidance_fallback(result: dict[str, Any], *, user_prompt: str | None = None) -> bool:
    if str(result.get("result_kind") or "").strip() not in {"review_result", "adjustment_analysis"}:
        return False
    return _result_has_unavailable_fix_proposals(result) and _result_prefers_unavailable_guidance(
        result,
        user_prompt=user_prompt,
    )


def _build_plan_timeout_fallback_reply(result: dict[str, Any], *, user_prompt: str | None = None) -> str | None:
    result_kind = str(result.get("result_kind") or "").strip()
    if result_kind not in {
        "review_result",
        "adjustment_analysis",
        "fix_proposal_preview",
        "status_overview",
        "generation_result",
        "ordered_snapshot",
        "candidate_snapshot",
        "mutation_result",
        "no_change",
    }:
        return None

    summary = str(
        result.get("summary")
        or result.get("state_summary")
        or result.get("review_summary")
        or ""
    ).strip()
    if not summary:
        return None

    lead_map = {
        "review_result": "我已经帮你检查了方案，主要情况如下：",
        "adjustment_analysis": "调整分析已完成，结果如下：",
        "fix_proposal_preview": "我已经整理好当前方案的处理预览：",
        "status_overview": "方案情况如下：",
        "generation_result": "方案已经生成好了：",
        "ordered_snapshot": "你的方案情况如下：",
        "candidate_snapshot": "候选机会查询结果：",
        "mutation_result": "方案调整已完成：",
    }
    facts = result.get("facts") if isinstance(result.get("facts"), dict) else {}
    relation = facts.get("intent_relation") if isinstance(facts.get("intent_relation"), dict) else {}
    coverage = str(relation.get("coverage") or "").strip()
    aligned_examples = str(relation.get("aligned_examples") or "").strip()
    conflict_examples = str(relation.get("conflict_examples") or "").strip()
    next_step_hints = result.get("next_step_hints") if isinstance(result.get("next_step_hints"), list) else []

    rendered_status_overview = result_kind == "status_overview" and bool(facts)
    rendered_review_result = result_kind == "review_result" and bool(facts)
    if rendered_status_overview:
        lines = _build_status_overview_fallback_lines(facts)
    elif rendered_review_result:
        if _review_prompt_prefers_unavailable_guidance(user_prompt):
            lines = _build_review_unavailable_guidance_fallback_lines(facts)
        else:
            lines = _build_review_result_fallback_lines(facts)
    elif result_kind == "adjustment_analysis" and bool(facts):
        if _result_needs_unavailable_guidance_fallback(result, user_prompt=user_prompt):
            lines = _build_review_unavailable_guidance_fallback_lines(facts)
        else:
            lines = _build_adjustment_analysis_fallback_lines(facts)
    elif result_kind == "fix_proposal_preview" and bool(facts):
        lines = _build_fix_proposal_preview_fallback_lines(facts, summary=summary)
    else:
        lines = [lead_map.get(result_kind, "这轮方案分析已经执行完了，我先把核心结果直接给你："), "", summary]
    if coverage and not rendered_status_overview and not rendered_review_result:
        lines.append(f"- {coverage}")
    if aligned_examples and not rendered_status_overview and not rendered_review_result:
        lines.append(f"- {aligned_examples}")
    if conflict_examples and not rendered_status_overview and not rendered_review_result:
        lines.append(f"- {conflict_examples}")
    if next_step_hints:
        first_hint = str(next_step_hints[0] or "").strip()
        if first_hint and not first_hint.startswith("[LLM_INTERNAL]"):
            lines.extend(["", first_hint])
    return _sanitize_reply_for_user(_normalize_user_facing_terms("\n".join(lines)))


def _clean_status_item_for_user(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.replace("(unknown)", "")
    text = re.sub(r"@(\d+)", r"第\1位", text)
    return text


def _format_status_tier_counts(tier_counts: Any) -> str:
    if not isinstance(tier_counts, dict):
        return ""
    parts = []
    for key in ("冲", "稳", "保"):
        value = tier_counts.get(key)
        if value is None:
            continue
        parts.append(f"{key}{value}")
    return " / ".join(parts)


def _build_status_overview_fallback_lines(facts: dict[str, Any]) -> list[str]:
    current_total = int(facts.get("current_total") or 0)
    target_total = int(facts.get("target_total") or 0)
    risk_count = int(facts.get("risk_count") or 0)
    warn_count = int(facts.get("warn_count") or 0)
    tier_text = _format_status_tier_counts(facts.get("tier_counts"))
    top_items = [_clean_status_item_for_user(item) for item in (facts.get("top_items") or [])]
    top_items = [item for item in top_items if item]
    relation = facts.get("intent_relation") if isinstance(facts.get("intent_relation"), dict) else {}

    if current_total <= 0:
        return [
            "当前还没有生成正式方案。",
            "",
            "你可以直接说“帮我生成一版方案”，我会按你的成绩和偏好先生成方案，再继续做审查和调整。",
        ]

    target = target_total or current_total
    lines = [
        "我看了当前方案，核心情况如下：",
        "",
        f"- 完整度：{current_total}/{target} 个志愿。"
    ]
    if tier_text:
        lines.append(f"- 冲稳保：{tier_text}。")
    if risk_count > 0 or warn_count > 0:
        lines.append(f"- 审查：风险 {risk_count} 项，提醒 {warn_count} 项。")
    else:
        lines.append("- 审查：暂时没有明显风险。")

    coverage = str(relation.get("coverage") or "").removeprefix("承接情况：").strip()
    if coverage:
        lines.append(f"- 偏好承接：{coverage}")
    aligned_examples = _clean_status_item_for_user(
        str(relation.get("aligned_examples") or "").removeprefix("贴近偏好：")
    )
    if aligned_examples:
        lines.append(f"- 贴近偏好的例子：{aligned_examples}")
    conflict_examples = _clean_status_item_for_user(
        str(relation.get("conflict_examples") or "").removeprefix("需关注冲突：")
    )
    if conflict_examples:
        lines.append(f"- 需要关注的冲突：{conflict_examples}")
    if top_items:
        lines.append(f"- 前排示例：{'；'.join(top_items[:3])}。")

    reminders = [str(item or "").strip() for item in (facts.get("main_reminders") or []) if str(item or "").strip()]
    if reminders:
        lines.append(f"- 重点提醒：{'；'.join(reminders[:2])}。")

    lines.extend([
        "",
        "下一步可以继续看审查明细，或直接告诉我想往更稳、某个地域、某类专业方向调整。",
    ])
    return lines


def build_timeout_fallback_from_recent_plan_execution(
    session_id: str,
    user_prompt: str,
) -> ChatServiceResponseEnvelope | None:
    result = consume_recent_plan_execution_result(session_id, user_prompt)
    if not result:
        return None
    reply = _build_plan_timeout_fallback_reply(result, user_prompt=user_prompt)
    if not reply:
        return None
    workspace_refresh_targets = _dedupe_workspace_targets(
        [str(target) for target in (result.get("workspace_refresh_targets") or [])]
    )
    if workspace_refresh_targets:
        return ChatServiceResponseEnvelope(
            primary=reply,
            followups=[
                _build_silent_workspace_refresh_response(session_id, target)
                for target in workspace_refresh_targets
            ],
        )
    return ChatServiceResponseEnvelope(primary=reply)


async def build_interruption_fallback_from_recent_plan_execution(
    session_id: str,
    user_prompt: str,
) -> ChatServiceResponseEnvelope | None:
    result = consume_recent_plan_execution_result(session_id, user_prompt)
    if not result:
        return None

    pending_source_payload = result.get("_pending_source_payload")
    if isinstance(pending_source_payload, dict):
        source_payload = dict(pending_source_payload)
        facts = result.get("facts")
        if isinstance(facts, dict) and facts:
            source_payload["facts"] = facts
        confirmation_candidate = _build_plan_confirmation_candidate_from_payload(
            source_payload,
            summary=str(result.get("summary") or result.get("preview_summary") or ""),
        )
        if confirmation_candidate is not None:
            return ChatServiceResponseEnvelope(
                primary=_plan_confirmation_card_primary_reply(confirmation_candidate),
                followups=[
                    await _create_pending_plan_confirmation_response(session_id, confirmation_candidate)
                ],
            )

    reply = _build_plan_timeout_fallback_reply(result, user_prompt=user_prompt)
    if not reply:
        return None
    workspace_refresh_targets = _dedupe_workspace_targets(
        [str(target) for target in (result.get("workspace_refresh_targets") or [])]
    )
    followups = [
        _build_silent_workspace_refresh_response(session_id, target)
        for target in workspace_refresh_targets
    ]
    return ChatServiceResponseEnvelope(primary=reply, followups=followups)


def _replace_text_reply(messages: list[Any] | None, old_reply: str, new_reply: str) -> None:
    if old_reply == new_reply:
        return
    for message in messages or []:
        if not isinstance(message, ModelResponse):
            continue
        for part in getattr(message, "parts", []) or []:
            if isinstance(part, TextPart) and part.content == old_reply:
                part.content = new_reply


def _build_direct_plan_action_messages(
    user_prompt: str,
    *,
    tool_call_id: str,
    plan_payload: dict[str, Any],
    result_text: str,
    reply: str,
    model_name: str,
) -> list[Any]:
    return [
        ModelRequest(parts=[UserPromptPart(content=user_prompt)]),
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args={"plan_payload": json.dumps(plan_payload, ensure_ascii=False)},
                    tool_call_id=tool_call_id,
                )
            ],
            model_name=model_name,
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=result_text,
                    tool_call_id=tool_call_id,
                )
            ]
        ),
        ModelResponse(parts=[TextPart(content=reply)], model_name=model_name),
    ]


@dataclass
class _PlanActionRecoveryResult:
    reply: str
    messages: list[Any]
    route_decision: dict[str, Any]


def _reply_looks_like_plan_action_recovery_boundary(reply: str) -> bool:
    if not isinstance(reply, str):
        return False
    compact = _compact_plan_reply_text(reply)
    if not compact:
        return False
    return any(
        marker in compact
        for marker in (
            "还没有生成可执行的调整内容",
            "没有生成可执行的调整内容",
            "这轮还没有生成可执行",
            "这轮还没有生成可点击的方案待采纳内容",
        )
    )


def _plan_recovery_has_context(
    request_context: RequestContext,
    recent_plan_context: dict[str, Any] | None,
) -> bool:
    if getattr(request_context, "planning_summary", None) is not None:
        return True
    return bool(recent_plan_context)


def _plan_recovery_decision_to_tool_args(decision: Any, content: str) -> dict[str, Any]:
    args: dict[str, Any] = {
        "user_goal": content,
        "action_family": str(getattr(decision, "actionFamily", "none") or "none"),
        "current_stage": "preview",
    }
    list_fields = {
        "volunteerIds": "volunteer_ids",
        "unitIds": "unit_ids",
        "sourceMajorNames": "source_major_names",
        "schoolTags": "school_tags",
        "majorTags": "major_tags",
    }
    for source_key, target_key in list_fields.items():
        values = [
            str(item or "").strip()
            for item in (getattr(decision, source_key, []) or [])
            if str(item or "").strip()
        ]
        if values:
            args[target_key] = values
    scalar_fields = {
        "reviewIssueCode": "review_issue_code",
        "sourcePosition": "source_position",
        "positionScope": "position_scope",
        "targetPosition": "target_position",
        "sortField": "sort_field",
        "tier": "tier",
        "provinceKeyword": "province_keyword",
        "schoolKeyword": "school_keyword",
        "majorKeyword": "major_keyword",
    }
    for source_key, target_key in scalar_fields.items():
        value = getattr(decision, source_key, None)
        if value not in (None, ""):
            args[target_key] = value
    if bool(getattr(decision, "preserveCount", False)):
        args["preserve_count"] = True
    limit = getattr(decision, "limit", None)
    if isinstance(limit, int) and limit > 0:
        args["limit"] = limit
    return args


def _build_recovered_plan_action_messages(
    user_prompt: str,
    *,
    plan_next_args: dict[str, Any],
    plan_payload_text: str,
    result_text: str,
    reply: str,
    model_name: str,
) -> list[Any]:
    plan_call_id = f"plan-recovery-plan-{uuid.uuid4().hex[:8]}"
    execute_call_id = f"plan-recovery-exec-{uuid.uuid4().hex[:8]}"
    return [
        ModelRequest(parts=[UserPromptPart(content=user_prompt)]),
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="plan_next_action",
                    args=plan_next_args,
                    tool_call_id=plan_call_id,
                )
            ],
            model_name=model_name,
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="plan_next_action",
                    content=plan_payload_text,
                    tool_call_id=plan_call_id,
                )
            ]
        ),
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args={"plan_payload": plan_payload_text},
                    tool_call_id=execute_call_id,
                )
            ],
            model_name=model_name,
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=result_text,
                    tool_call_id=execute_call_id,
                )
            ]
        ),
        ModelResponse(parts=[TextPart(content=reply)], model_name=model_name),
    ]


class ChatService:
    """会话管理 + Agent 编排。SQLite 持久化会话历史。"""

    # 每 _LOG_INTERVAL 轮输出一次 session 累计 token 消耗摘要
    _LOG_INTERVAL = 5
    _INITIAL_PROGRESS_DELAY_SECONDS = 1.5
    _INITIAL_PROGRESS_HINT = "正在理解你的问题，并结合当前信息整理回答..."
    _EARLY_CONTEXT_PROGRESS_DELAY_SECONDS = 1.2
    _EARLY_CONTEXT_PROGRESS_HINT = "正在读取当前会话信息..."
    _LONG_PROGRESS_MODEL_WAIT_HINTS = (
        (12.0, "还在分析你的问题，正在整理可用信息，请稍等..."),
        (25.0, "这轮回答比平时慢一些，我会继续保留当前会话状态；没有明确确认前不会改动偏好或方案。"),
        (60.0, "还在整理完整结论，我会继续保留当前会话状态；如果超时，会先给你安全提示。"),
    )
    _LONG_PROGRESS_TOOL_HINTS = (
        (12.0, "还在处理，这轮需要结合当前信息整理结论，请稍等..."),
        (25.0, "这轮分析耗时较长，我会继续等待结果，并尽量给出已确认的信息和下一步建议..."),
        (60.0, "已经整理出部分分析信息，正在补全结论；我会继续保留当前会话状态。"),
    )
    _LONG_PROGRESS_HINTS = _LONG_PROGRESS_TOOL_HINTS
    _MIN_PROGRESS_INTERVAL_SECONDS = 8.0

    def __init__(self, llm_client: LLMClient, history_store: ChatHistoryStore):
        self.llm_client = llm_client
        self.agent = ChatAgent(llm_client)
        self.history_store = history_store
        self.history_config = HistoryConfig()
        self._usage_trackers: dict[str, UsageTracker] = {}

    # ── 公开接口：session 级 usage 查询 ───────────────────────────

    def get_usage_summary(self, session_id: str) -> dict | None:
        """返回指定 session 的累计 token 消耗摘要，供上层计费/监控使用。"""
        tracker = self._usage_trackers.get(session_id)
        return tracker.summary() if tracker else None

    def get_usage_tracker(self, session_id: str) -> UsageTracker | None:
        """获取指定 session 的 UsageTracker 实例。"""
        return self._usage_trackers.get(session_id)

    async def _execute_semantic_plan_payload(
        self,
        *,
        request_context: RequestContext,
        plan_payload: dict[str, Any],
    ) -> tuple[str, dict[str, Any], int]:
        started_at = time.monotonic()
        result_text = await execute_plan_action(
            SimpleNamespace(deps=request_context),
            json.dumps(plan_payload, ensure_ascii=False),
        )
        duration_ms = int((time.monotonic() - started_at) * 1000)
        return result_text, _parse_tool_return_json(result_text) or {}, duration_ms

    async def _maybe_handle_semantic_plan_action(
        self,
        *,
        session_id: str,
        user_id: str,
        content: str,
        history: list[Any] | None,
        request_context: RequestContext,
        turn_started_at: float,
        on_progress: ProgressCallback | None,
    ) -> ChatServiceResponseEnvelope | str | None:
        active_pending = resolve_pending_confirmation(request_context)
        if active_pending is not None:
            return None
        recent_plan_context = _latest_plan_semantic_route_context(history)
        if not _has_plan_semantic_route_context(
            getattr(request_context, "planning_summary", None),
            recent_plan_context,
        ):
            return None

        try:
            decision = await classify_plan_semantic_action(
                content,
                request_context=request_context,
                recent_plan_context=recent_plan_context,
            )
        except Exception:
            logger.warning(
                "Semantic plan action classification failed: session_id=%s",
                session_id,
                exc_info=True,
            )
            return None

        action_family = str(getattr(decision, "actionFamily", "none") or "none")
        confidence = float(getattr(decision, "confidence", 0.0) or 0.0)
        if action_family == "analyze_adjustment" and confidence >= _SEMANTIC_PLAN_ACTION_CONFIDENCE_THRESHOLD:
            if await _candidate_query_should_bypass_semantic_plan_action(
                content,
                request_context=request_context,
            ):
                return None
        if (
            confidence >= _SEMANTIC_PLAN_ACTION_CONFIDENCE_THRESHOLD
            and _requests_profile_change_replan(decision)
            and _profile_change_replan_has_explicit_change_value(content)
        ):
            reply = _build_profile_change_replan_reply(
                content,
                request_context=request_context,
            )
            new_messages = [
                ModelRequest(parts=[UserPromptPart(content=content)]),
                ModelResponse(parts=[TextPart(content=reply)], model_name="semantic-profile-change-replan"),
            ]
            turn_event = {
                "sessionId": session_id,
                "userId": user_id,
                "scene": "plan",
                "routingPath": "semantic_profile_change_replan",
                "routeDecision": {
                    "source": "semantic_plan_action",
                    "matched": True,
                    "confidence": confidence,
                    "route": action_family,
                    "reason": str(getattr(decision, "reason", "") or ""),
                    "replyFocus": list(getattr(decision, "replyFocus", []) or []),
                },
                "pendingType": None,
                "actionFamily": None,
                "modelProvider": _llm_config_value(self.llm_client, "provider"),
                "modelName": _llm_config_value(self.llm_client, "model_name"),
                "toolCallCount": 0,
                "totalDurationMs": int((time.monotonic() - turn_started_at) * 1000),
                "toolCalls": [],
                "postProcessingApplied": ["semantic_profile_change_replan"],
                "status": "success",
                "errorType": None,
            }
            _log_conversation_turn_event(**turn_event)
            try:
                history_to_save = list(history or [])
                history_to_save.extend(_append_route_observability_message(new_messages, turn_event))
                await self.history_store.save(session_id, history_to_save)
            except Exception:
                logger.exception("Failed to save profile change replan history: session_id=%s", session_id)
            return reply
        short_review_followup = (
            action_family == "review_plan"
            and bool(recent_plan_context)
            and len(str(content or "").strip()) <= 12
        )
        review_analysis_followup = (
            action_family == "analyze_adjustment"
            and bool(recent_plan_context)
            and isinstance(recent_plan_context.get("fixProposals"), dict)
        )
        has_existing_plan_context = _has_plan_semantic_route_context(
            getattr(request_context, "planning_summary", None),
            None,
        )
        current_plan_analysis = (
            action_family == "analyze_adjustment"
            and not recent_plan_context
            and has_existing_plan_context
            and _semantic_current_plan_analysis_allowed(decision)
        )
        if (
            action_family != "preview_fix_proposal"
            and not review_analysis_followup
            and not current_plan_analysis
            and not short_review_followup
        ) or confidence < _SEMANTIC_PLAN_ACTION_CONFIDENCE_THRESHOLD:
            return None
        needs_review_before_preview = False
        target_strategies = [
            str(strategy or "").strip()
            for strategy in list(getattr(decision, "targetStrategies", []) or [])
            if str(strategy or "").strip()
        ]
        target_issue_codes = [
            str(code or "").strip()
            for code in list(getattr(decision, "targetIssueCodes", []) or [])
            if str(code or "").strip()
        ]
        requested_reply_focus = [
            str(item or "").strip()
            for item in list(getattr(decision, "replyFocus", []) or [])
            if str(item or "").strip()
        ]
        if action_family == "preview_fix_proposal":
            preview_allowed = _semantic_preview_fix_proposal_route_allowed(
                decision,
                recent_plan_context,
            )
            if not preview_allowed:
                has_existing_plan = _has_plan_semantic_route_context(
                    getattr(request_context, "planning_summary", None),
                    None,
                )
                if recent_plan_context or not has_existing_plan:
                    return None
                needs_review_before_preview = True

        if on_progress is not None:
            with contextlib.suppress(Exception):
                if action_family == "review_plan":
                    await on_progress("正在重新检查当前方案...")
                else:
                    await on_progress("正在根据当前方案提醒整理调整预览...")

        plan_payload = {
            "stage": "review" if action_family == "review_plan" else "apply",
            "action_family": action_family,
            "user_goal": content,
            "requires_confirmation": False,
        }
        if target_strategies:
            plan_payload["target_strategies"] = target_strategies
        if target_issue_codes:
            plan_payload["target_issue_codes"] = target_issue_codes
        if requested_reply_focus:
            plan_payload["reply_focus"] = requested_reply_focus
        if getattr(request_context, "planning_summary", None) is not None:
            try:
                plan_payload["planning_version"] = int(request_context.planning_summary.version or 0)
            except (TypeError, ValueError):
                pass

        tool_duration_ms = 0
        executed_tool_results: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        needs_review_before_target_resolution = (
            action_family == "analyze_adjustment"
            and bool(target_strategies)
            and not target_issue_codes
            and not recent_plan_context
            and has_existing_plan_context
        )
        if needs_review_before_preview or needs_review_before_target_resolution:
            review_payload = {
                "stage": "review",
                "action_family": "review_plan",
                "user_goal": content,
                "requires_confirmation": False,
            }
            if target_strategies:
                review_payload["target_strategies"] = target_strategies
            if target_issue_codes:
                review_payload["target_issue_codes"] = target_issue_codes
            if requested_reply_focus:
                review_payload["reply_focus"] = requested_reply_focus
            if "planning_version" in plan_payload:
                review_payload["planning_version"] = plan_payload["planning_version"]
            review_result_text, review_result, review_duration_ms = await self._execute_semantic_plan_payload(
                request_context=request_context,
                plan_payload=review_payload,
            )
            tool_duration_ms += review_duration_ms
            executed_tool_results.append((review_result_text, review_result, review_payload))
            review_context = _latest_plan_semantic_route_context(
                [
                    ModelRequest(
                        parts=[
                            ToolReturnPart(
                                tool_name="execute_plan_action",
                                content=review_result_text,
                                tool_call_id="semantic-review-before-preview",
                            )
                        ]
                    )
                ]
            )
            if needs_review_before_preview and not _semantic_preview_fix_proposal_route_allowed(decision, review_context):
                return None
            if needs_review_before_target_resolution:
                inferred_issue_codes = await _infer_plan_target_issue_codes_from_context(
                    content=content,
                    request_context=request_context,
                    recent_plan_context=review_context,
                    expected_action_family=action_family,
                    target_strategies=target_strategies,
                )
                if inferred_issue_codes:
                    target_issue_codes = inferred_issue_codes
                    plan_payload["target_issue_codes"] = target_issue_codes
            recent_plan_context = review_context
        result_text, result, result_duration_ms = await self._execute_semantic_plan_payload(
            request_context=request_context,
            plan_payload=plan_payload,
        )
        tool_duration_ms += result_duration_ms
        executed_tool_results.append((result_text, result, plan_payload))
        llm_started_at = time.monotonic()
        synthesis_usage = None
        synthesis_applied = False
        if action_family in {"preview_fix_proposal", "analyze_adjustment", "review_plan"}:
            try:
                reply, synthesis_usage = await _synthesize_semantic_plan_action_reply(
                    self.llm_client,
                    user_prompt=content,
                    result=result,
                    recent_plan_context=recent_plan_context,
                )
                synthesis_applied = bool(reply)
            except Exception:
                logger.warning(
                    "Semantic plan action reply synthesis failed: session_id=%s",
                    session_id,
                    exc_info=True,
                )
                reply = ""
        else:
            reply = ""
        llm_duration_ms = int((time.monotonic() - llm_started_at) * 1000)
        if not reply:
            reply = _build_plan_timeout_fallback_reply(result, user_prompt=content) or str(result.get("summary") or "").strip()
            reply = _sanitize_reply_for_user(_normalize_user_facing_terms(reply or "已查看当前方案的处理建议。"))
        elif _result_needs_unavailable_guidance_fallback(result, user_prompt=content):
            reply = _build_plan_timeout_fallback_reply(result, user_prompt=content) or reply
        elif _review_reply_needs_structured_fallback(reply, result):
            reply = _build_plan_timeout_fallback_reply(result, user_prompt=content) or reply
        elif _adjustment_reply_needs_structured_fallback(reply, result):
            reply = _build_plan_timeout_fallback_reply(result, user_prompt=content) or reply
        if synthesis_usage is not None:
            tracker = self._usage_trackers.get(session_id)
            if tracker is None:
                tracker = UsageTracker(session_id=session_id)
            self._usage_trackers[session_id] = tracker
            with contextlib.suppress(Exception):
                tracker.record(synthesis_usage)
        model_name = "semantic-plan-action-synthesis" if synthesis_applied else "semantic-plan-action-fallback"
        if len(executed_tool_results) == 1:
            tool_call_id = f"semantic-{action_family}"
            new_messages = _build_direct_plan_action_messages(
                content,
                tool_call_id=tool_call_id,
                plan_payload=plan_payload,
                result_text=result_text,
                reply=reply,
                model_name=model_name,
            )
        else:
            tool_call_parts: list[ToolCallPart] = []
            tool_return_parts: list[ToolReturnPart] = []
            for index, (executed_result_text, _executed_result, executed_payload) in enumerate(executed_tool_results):
                tool_call_id = f"semantic-{str(executed_payload.get('action_family') or action_family)}-{index}"
                tool_call_parts.append(
                    ToolCallPart(
                        tool_name="execute_plan_action",
                        args={"plan_payload": json.dumps(executed_payload, ensure_ascii=False)},
                        tool_call_id=tool_call_id,
                    )
                )
                tool_return_parts.append(
                    ToolReturnPart(
                        tool_name="execute_plan_action",
                        content=executed_result_text,
                        tool_call_id=tool_call_id,
                    )
                )
            new_messages = [
                ModelRequest(parts=[UserPromptPart(content=content)]),
                ModelResponse(parts=tool_call_parts, model_name=model_name),
                ModelRequest(parts=tool_return_parts),
                ModelResponse(parts=[TextPart(content=reply)], model_name=model_name),
            ]

        pending_fix_proposal_card: WSResponse | None = None
        composite_goal_card: WSResponse | None = None
        if action_family == "preview_fix_proposal":
            composite_goal_card = await self._maybe_recover_composite_goal_after_plan_attempt(
                session_id=session_id,
                content=content,
                request_context=request_context,
                tool_context_messages=new_messages,
                allow_actionable_fix_preview=True,
            )
            composite_goal_card_kind = _pending_card_kind(composite_goal_card)
            if composite_goal_card_kind == "plan_mutation":
                pending_fix_proposal_card = composite_goal_card
                card_payload = _parse_tool_return_json(
                    getattr(composite_goal_card, "content", "") or ""
                )
                card_summary = (
                    str((card_payload or {}).get("summary") or "").strip()
                    if isinstance(card_payload, dict)
                    else ""
                )
                primary_goal_reply = "已按你的要求列出调整预览。"
                if card_summary:
                    primary_goal_reply = f"已按你的要求列出调整预览：{card_summary}。"
                primary_goal_reply += "确认前不会改动当前方案；确认后会按预览调整当前方案。"
                primary_goal_reply = _sanitize_reply_for_user(primary_goal_reply)
                _replace_text_reply(new_messages, reply, primary_goal_reply)
                reply = primary_goal_reply
            elif composite_goal_card_kind == "intent_change":
                pending_fix_proposal_card = composite_goal_card
                _replace_text_reply(new_messages, reply, "")
                reply = ""
            elif composite_goal_card_kind == "readonly_notice":
                card_payload = _parse_tool_return_json(
                    getattr(composite_goal_card, "content", "") or ""
                )
                readonly_reply = (
                    str((card_payload or {}).get("reply") or "").strip()
                    if isinstance(card_payload, dict)
                    else ""
                )
                if readonly_reply:
                    _replace_text_reply(new_messages, reply, readonly_reply)
                    reply = readonly_reply

        latest_plan_result = _latest_fix_proposal_confirmation_source(new_messages)
        if pending_fix_proposal_card is None and action_family == "preview_fix_proposal" and isinstance(latest_plan_result, dict):
            facts = latest_plan_result.get("facts") if isinstance(latest_plan_result.get("facts"), dict) else {}
            fix_facts = facts.get("fix_proposals") if isinstance(facts.get("fix_proposals"), dict) else {}
            selected_proposal_id = _selected_fix_proposal_id(latest_plan_result, facts)
            if selected_proposal_id:
                ready_proposal = _select_ready_fix_proposal(
                    facts,
                    selected_proposal_id=selected_proposal_id,
                )
            elif (target_strategies or target_issue_codes) and not _filter_ready_fix_proposals_by_target_scope(
                _ready_fix_proposals(facts),
                _normalized_fix_proposal_target_strategies(target_strategies),
                _normalized_fix_proposal_target_issue_codes(target_issue_codes),
            ):
                ready_proposal = None
                latest_plan_result["target_match_empty"] = True
            else:
                ready_proposal = await _select_ready_fix_proposal_for_user_goal(
                    facts,
                    content=content,
                    reply=reply,
                    request_context=request_context,
                    target_strategies=target_strategies,
                    target_issue_codes=target_issue_codes,
                )
            source_version_guard = _as_int(
                fix_facts.get("source_version_guard")
                or latest_plan_result.get("source_backend_version")
                or latest_plan_result.get("planning_version")
            )
            if ready_proposal is not None and source_version_guard > 0:
                pending_fix_proposal_card = await _create_pending_fix_proposal_confirmation_response(
                    session_id,
                    ready_proposal,
                    source_version_guard=source_version_guard,
                )
                primary_reply = _fix_proposal_pending_primary_reply(ready_proposal)
                if primary_reply:
                    _replace_text_reply(new_messages, reply, primary_reply)
                    reply = primary_reply

        if pending_fix_proposal_card is None:
            composite_goal_card = await self._maybe_recover_composite_goal_after_plan_attempt(
                session_id=session_id,
                content=content,
                request_context=request_context,
                tool_context_messages=new_messages,
            )
            composite_goal_card_kind = _pending_card_kind(composite_goal_card)
            if composite_goal_card_kind == "plan_mutation":
                pending_fix_proposal_card = composite_goal_card
                card_payload = _parse_tool_return_json(
                    getattr(composite_goal_card, "content", "") or ""
                )
                card_summary = (
                    str((card_payload or {}).get("summary") or "").strip()
                    if isinstance(card_payload, dict)
                    else ""
                )
                primary_goal_reply = "已按你的要求列出调整预览。"
                if card_summary:
                    primary_goal_reply = f"已按你的要求列出调整预览：{card_summary}。"
                primary_goal_reply += "确认前不会改动当前方案；确认后会按预览调整当前方案。"
                primary_goal_reply = _sanitize_reply_for_user(primary_goal_reply)
                _replace_text_reply(new_messages, reply, primary_goal_reply)
                reply = primary_goal_reply
            elif composite_goal_card_kind == "intent_change":
                pending_fix_proposal_card = composite_goal_card
                _replace_text_reply(new_messages, reply, "")
                reply = ""
            elif composite_goal_card_kind == "readonly_notice":
                card_payload = _parse_tool_return_json(
                    getattr(composite_goal_card, "content", "") or ""
                )
                readonly_reply = (
                    str((card_payload or {}).get("reply") or "").strip()
                    if isinstance(card_payload, dict)
                    else ""
                )
                if readonly_reply:
                    _replace_text_reply(new_messages, reply, readonly_reply)
                    reply = readonly_reply

        action_family_result = str(result.get("action_family") or "preview_fix_proposal")
        observed_tool_calls = _summarize_tool_calls_for_observability(
            _iter_tool_call_parts(new_messages),
            _iter_tool_return_parts(new_messages),
        )
        turn_event = {
            "sessionId": session_id,
            "userId": user_id,
            "scene": "plan",
            "routingPath": "semantic_plan_action",
            "routeDecision": {
                "source": "semantic_plan_action",
                "matched": True,
                "confidence": confidence,
                "route": action_family,
                "reason": str(getattr(decision, "reason", "") or ""),
                "targetStrategies": list(getattr(decision, "targetStrategies", []) or []),
                "recentPlanContext": recent_plan_context,
            },
            "pendingType": None,
            "actionFamily": action_family_result,
            "modelProvider": _llm_config_value(self.llm_client, "provider"),
            "modelName": _llm_config_value(self.llm_client, "model_name"),
            "llmRequests": getattr(synthesis_usage, "requests", None),
            "inputTokens": getattr(synthesis_usage, "input_tokens", None),
            "outputTokens": getattr(synthesis_usage, "output_tokens", None),
            "totalTokens": getattr(synthesis_usage, "total_tokens", None),
            "toolCallCount": len(observed_tool_calls),
            "totalDurationMs": int((time.monotonic() - turn_started_at) * 1000),
            "llmDurationMs": llm_duration_ms if synthesis_applied else None,
            "toolDurationMs": tool_duration_ms,
            "toolCalls": observed_tool_calls,
            "postProcessingApplied": [
                "semantic_plan_action",
                "llm_reply_synthesis" if synthesis_applied else "fallback_reply",
            ],
            "status": "success" if result.get("result_kind") != "error" else "error",
            "errorType": result.get("result_kind") if result.get("result_kind") == "error" else None,
        }
        _log_conversation_turn_event(**turn_event)

        try:
            history_to_save = list(history or [])
            history_to_save.extend(_append_route_observability_message(new_messages, turn_event))
            await self.history_store.save(session_id, history_to_save)
        except Exception:
            logger.exception("Failed to save semantic plan action history: session_id=%s", session_id)

        followups: list[WSResponse] = []
        if pending_fix_proposal_card is not None:
            followups.append(pending_fix_proposal_card)
        workspace_refresh_targets = _dedupe_workspace_targets(
            [str(target) for target in (result.get("workspace_refresh_targets") or [])]
        )
        workspace_refresh_targets = _strip_workspace_targets_for_readonly_prompt(
            workspace_refresh_targets,
            content,
        )
        workspace_refresh_targets = _strip_workspace_targets_for_explanation_only_result(
            workspace_refresh_targets,
            new_messages,
        )
        followups.extend(
            _build_silent_workspace_refresh_response(session_id, target)
            for target in workspace_refresh_targets
        )
        if followups:
            return ChatServiceResponseEnvelope(primary=reply, followups=followups)
        return reply

    async def _execute_recovered_plan_action(
        self,
        *,
        session_id: str,
        content: str,
        request_context: RequestContext,
        decision: Any,
    ) -> _PlanActionRecoveryResult | None:
        action_family = str(getattr(decision, "actionFamily", "none") or "none")
        confidence = float(getattr(decision, "confidence", 0.0) or 0.0)
        if action_family == "none" or confidence < 0.85:
            return None

        plan_next_args = _plan_recovery_decision_to_tool_args(decision, content)
        if on_progress := getattr(request_context, "progress_callback", None):
            with contextlib.suppress(Exception):
                await on_progress("正在重新生成这次调整的预览...")

        ctx = SimpleNamespace(deps=request_context)
        try:
            plan_payload_text = await plan_next_action(ctx, **plan_next_args)
            plan_payload = json.loads(plan_payload_text)
            result_text = await execute_plan_action(ctx, plan_payload_text)
            result = _parse_tool_return_json(result_text) or {}
        except Exception:
            logger.warning(
                "Plan action recovery execution failed: session_id=%s action_family=%s",
                session_id,
                action_family,
                exc_info=True,
            )
            return None

        reply_text = _build_plan_timeout_fallback_reply(result, user_prompt=content)
        if not reply_text:
            reply_text = str(
                result.get("reply")
                or result.get("summary")
                or plan_payload.get("preview_summary")
                or ""
            ).strip()
        if not reply_text:
            reply_text = "这次调整已完成定位，我会先给你预览，确认前不会改动当前方案。"
        reply_text = _sanitize_reply_for_user(_normalize_user_facing_terms(reply_text))
        messages = _build_recovered_plan_action_messages(
            content,
            plan_next_args=plan_next_args,
            plan_payload_text=plan_payload_text,
            result_text=result_text,
            reply=reply_text,
            model_name="plan-action-recovery",
        )
        return _PlanActionRecoveryResult(
            reply=reply_text,
            messages=messages,
            route_decision={
                "source": "plan_action_recovery",
                "matched": True,
                "confidence": confidence,
                "route": action_family,
                "reason": str(getattr(decision, "reason", "") or ""),
            },
        )

    async def _classify_plan_action_recovery(
        self,
        *,
        session_id: str,
        content: str,
        request_context: RequestContext,
        recent_plan_context: dict[str, Any] | None,
    ) -> Any | None:
        try:
            return await classify_plan_recovery_action(
                content,
                request_context=request_context,
                recent_plan_context=recent_plan_context,
            )
        except Exception:
            logger.warning(
                "Plan action recovery classification failed: session_id=%s",
                session_id,
                exc_info=True,
            )
            return None

    async def _maybe_recover_unbacked_plan_action(
        self,
        *,
        session_id: str,
        content: str,
        reply: str,
        tool_context_messages: list[Any] | None,
        request_context: RequestContext,
    ) -> _PlanActionRecoveryResult | None:
        if resolve_pending_confirmation(request_context) is not None:
            return None
        if not _reply_looks_like_plan_action_recovery_boundary(reply):
            return None
        if list(_iter_tool_call_parts(tool_context_messages)):
            return None
        recent_plan_context = _latest_plan_semantic_route_context(getattr(request_context, "chat_history", None))
        if not _plan_recovery_has_context(request_context, recent_plan_context):
            return None
        decision = await self._classify_plan_action_recovery(
            session_id=session_id,
            content=content,
            request_context=request_context,
            recent_plan_context=recent_plan_context,
        )
        if decision is None:
            return None
        return await self._execute_recovered_plan_action(
            session_id=session_id,
            content=content,
            request_context=request_context,
            decision=decision,
        )

    async def _maybe_recover_plan_action_from_intent_preview(
        self,
        *,
        session_id: str,
        content: str,
        request_context: RequestContext,
        tool_context_messages: list[Any] | None,
    ) -> _PlanActionRecoveryResult | None:
        if not _tool_calls_include_intent_preview(tool_context_messages):
            return None
        if not _tool_calls_include_plan_chain(tool_context_messages):
            return None
        if _extract_plan_confirmation_candidate(tool_context_messages) is not None:
            return None
        recent_plan_context = _latest_plan_semantic_route_context(getattr(request_context, "chat_history", None))
        if not _plan_recovery_has_context(request_context, recent_plan_context):
            return None
        decision = await self._classify_plan_action_recovery(
            session_id=session_id,
            content=content,
            request_context=request_context,
            recent_plan_context=recent_plan_context,
        )
        if decision is None:
            return None
        return await self._execute_recovered_plan_action(
            session_id=session_id,
            content=content,
            request_context=request_context,
            decision=decision,
        )

    async def _maybe_recover_fix_preview_after_review(
        self,
        *,
        session_id: str,
        content: str,
        request_context: RequestContext,
        tool_context_messages: list[Any] | None,
    ) -> _PlanActionRecoveryResult | None:
        """Recover repair preview when the model only reviewed the plan.

        This recovery is based on the structured review result from the current
        turn plus the semantic action classifier. It does not infer intent from
        fixed user phrases.
        """

        if resolve_pending_confirmation(request_context) is not None:
            return None
        if _extract_plan_confirmation_candidate(tool_context_messages) is not None:
            return None
        current_plan_context = _latest_plan_semantic_route_context(tool_context_messages)
        if not _plan_context_has_fix_proposals(current_plan_context):
            current_plan_context = _latest_review_fix_proposal_route_context(tool_context_messages)
        if not current_plan_context:
            return None
        last_action_family = str(current_plan_context.get("lastActionFamily") or "").strip()
        last_result_kind = str(current_plan_context.get("lastResultKind") or "").strip()
        if last_action_family not in {"review_plan", "analyze_adjustment"}:
            return None
        if last_result_kind not in {"review_result", "adjustment_analysis"}:
            return None
        fix_facts = current_plan_context.get("fixProposals")
        if not isinstance(fix_facts, dict) or not isinstance(fix_facts.get("proposals"), list):
            return None

        try:
            decision = await classify_plan_semantic_action(
                content,
                request_context=request_context,
                recent_plan_context=current_plan_context,
            )
        except Exception:
            logger.warning(
                "Post-review fix preview classification failed: session_id=%s",
                session_id,
                exc_info=True,
            )
            return None

        action_family = str(getattr(decision, "actionFamily", "none") or "none")
        confidence = float(getattr(decision, "confidence", 0.0) or 0.0)
        target_strategies = [
            str(strategy or "").strip()
            for strategy in list(getattr(decision, "targetStrategies", []) or [])
            if str(strategy or "").strip()
        ]
        target_issue_codes = [
            str(code or "").strip()
            for code in list(getattr(decision, "targetIssueCodes", []) or [])
            if str(code or "").strip()
        ]
        preview_requested = (
            _semantic_decision_requests_fix_preview(
                decision,
                require_issue_code_for_non_preview=True,
            )
            and _semantic_preview_fix_proposal_route_allowed(decision, current_plan_context)
        )

        if not preview_requested:
            return None

        plan_payload = {
            "stage": "apply",
            "action_family": "preview_fix_proposal",
            "user_goal": content,
            "requires_confirmation": False,
        }
        if target_strategies:
            plan_payload["target_strategies"] = target_strategies
        if target_issue_codes:
            plan_payload["target_issue_codes"] = target_issue_codes
        if getattr(request_context, "planning_summary", None) is not None:
            with contextlib.suppress(TypeError, ValueError):
                plan_payload["planning_version"] = int(request_context.planning_summary.version or 0)

        try:
            result_text = await execute_plan_action(
                SimpleNamespace(deps=request_context),
                json.dumps(plan_payload, ensure_ascii=False),
            )
            result = _parse_tool_return_json(result_text) or {}
        except Exception:
            logger.warning(
                "Post-review fix preview execution failed: session_id=%s",
                session_id,
                exc_info=True,
            )
            return None

        facts = result.get("facts") if isinstance(result.get("facts"), dict) else {}
        selected_proposal = await _select_ready_fix_proposal_for_user_goal(
            facts,
            content=content,
            reply="",
            request_context=request_context,
            target_strategies=target_strategies,
            target_issue_codes=target_issue_codes,
        )
        selected_proposal_id = ""
        if isinstance(selected_proposal, dict):
            selected_proposal_id = str(
                selected_proposal.get("proposal_id") or selected_proposal.get("proposalId") or ""
            ).strip()
        if selected_proposal_id and "selected_proposal_id" not in result and "selectedProposalId" not in result:
            result["selected_proposal_id"] = selected_proposal_id
            result_text = json.dumps(result, ensure_ascii=False, default=str)

        try:
            reply, _usage = await _synthesize_semantic_plan_action_reply(
                self.llm_client,
                user_prompt=content,
                result=result,
                recent_plan_context=current_plan_context,
            )
        except Exception:
            logger.warning(
                "Post-review fix preview reply synthesis failed: session_id=%s",
                session_id,
                exc_info=True,
            )
            reply = ""
        if not reply:
            reply = _build_plan_timeout_fallback_reply(result, user_prompt=content) or str(result.get("summary") or "").strip()
        if not reply:
            reply = "我已把可以处理的调整预览列出来，确认前不会改动当前方案。"
        reply = _sanitize_reply_for_user(_normalize_user_facing_terms(reply))
        messages = _build_direct_plan_action_messages(
            content,
            tool_call_id=f"post-review-fix-preview-{uuid.uuid4().hex[:8]}",
            plan_payload=plan_payload,
            result_text=result_text,
            reply=reply,
            model_name="post-review-fix-preview",
        )
        return _PlanActionRecoveryResult(
            reply=reply,
            messages=messages,
            route_decision={
                "source": "post_review_fix_preview",
                "matched": True,
                "confidence": confidence,
                "route": "preview_fix_proposal",
                "reason": str(getattr(decision, "reason", "") or ""),
                "targetStrategies": list(target_strategies),
                "targetIssueCodes": list(target_issue_codes),
            },
        )

    async def _maybe_complete_unexecuted_fix_preview_plan_next(
        self,
        *,
        session_id: str,
        content: str,
        request_context: RequestContext,
        tool_context_messages: list[Any] | None,
    ) -> _PlanActionRecoveryResult | None:
        if resolve_pending_confirmation(request_context) is not None:
            return None
        if _extract_plan_confirmation_candidate(tool_context_messages) is not None:
            return None
        plan_payload = _latest_unexecuted_plan_next_payload(
            tool_context_messages,
            action_family="preview_fix_proposal",
        )
        if not isinstance(plan_payload, dict):
            return None
        if str(plan_payload.get("stage") or "").strip() not in {"preview", "apply", "review"}:
            return None
        if not _fix_proposal_payload_has_explicit_target(plan_payload):
            return None
        plan_payload["stage"] = "apply"
        plan_payload["action_family"] = "preview_fix_proposal"
        plan_payload["requires_confirmation"] = False
        plan_payload.setdefault("user_goal", content)
        if getattr(request_context, "planning_summary", None) is not None and "planning_version" not in plan_payload:
            with contextlib.suppress(TypeError, ValueError):
                plan_payload["planning_version"] = int(request_context.planning_summary.version or 0)

        if on_progress := getattr(request_context, "progress_callback", None):
            with contextlib.suppress(Exception):
                await on_progress("正在把这次调整整理成预览...")

        try:
            result_text, result, _duration_ms = await self._execute_semantic_plan_payload(
                request_context=request_context,
                plan_payload=plan_payload,
            )
        except Exception:
            logger.warning(
                "Complete unexecuted fix preview failed: session_id=%s",
                session_id,
                exc_info=True,
            )
            return None
        target_strategies = [
            str(strategy or "").strip()
            for strategy in (plan_payload.get("target_strategies") or plan_payload.get("targetStrategies") or [])
            if str(strategy or "").strip()
        ]
        facts = result.get("facts") if isinstance(result.get("facts"), dict) else {}
        selected_proposal_id = _ready_fix_proposal_id_for_strategies(facts, target_strategies)
        if selected_proposal_id and "selected_proposal_id" not in result and "selectedProposalId" not in result:
            result["selected_proposal_id"] = selected_proposal_id
            result_text = json.dumps(result, ensure_ascii=False, default=str)

        try:
            reply, _usage = await _synthesize_semantic_plan_action_reply(
                self.llm_client,
                user_prompt=content,
                result=result,
                recent_plan_context=_latest_plan_semantic_route_context(tool_context_messages),
            )
        except Exception:
            logger.warning(
                "Complete unexecuted fix preview reply synthesis failed: session_id=%s",
                session_id,
                exc_info=True,
            )
            reply = ""
        if not reply:
            reply = _build_plan_timeout_fallback_reply(result, user_prompt=content) or str(result.get("summary") or "").strip()
        if not reply:
            reply = "我已把可以处理的调整预览列出来，确认前不会改动当前方案。"
        reply = _sanitize_reply_for_user(_normalize_user_facing_terms(reply))
        messages = _build_direct_plan_action_messages(
            content,
            tool_call_id=f"complete-fix-preview-{uuid.uuid4().hex[:8]}",
            plan_payload=plan_payload,
            result_text=result_text,
            reply=reply,
            model_name="complete-unexecuted-fix-preview",
        )
        return _PlanActionRecoveryResult(
            reply=reply,
            messages=messages,
            route_decision={
                "source": "complete_unexecuted_plan_next_action",
                "matched": True,
                "confidence": "structured",
                "route": "preview_fix_proposal",
            },
        )

    async def _maybe_complete_unexecuted_mutating_plan_next_preview(
        self,
        *,
        session_id: str,
        content: str,
        request_context: RequestContext,
        tool_context_messages: list[Any] | None,
    ) -> _PlanActionRecoveryResult | None:
        if resolve_pending_confirmation(request_context) is not None:
            return None
        if _extract_plan_confirmation_candidate(tool_context_messages) is not None:
            return None
        plan_payload = _latest_unexecuted_plan_next_payload(tool_context_messages)
        if not isinstance(plan_payload, dict):
            return None
        action_family = str(plan_payload.get("action_family") or "").strip()
        if action_family not in _PENDING_PLAN_ACTION_FAMILIES:
            return None
        if str(plan_payload.get("stage") or "").strip() != "preview":
            return None
        if plan_payload.get("missing_inputs"):
            return None
        if not _plan_payload_has_executable_mutation_scope(plan_payload):
            return None

        plan_payload = normalize_plan_action_payload(dict(plan_payload))
        plan_payload["stage"] = "preview"
        plan_payload.setdefault("user_goal", content)
        if getattr(request_context, "planning_summary", None) is not None and "planning_version" not in plan_payload:
            with contextlib.suppress(TypeError, ValueError):
                plan_payload["planning_version"] = int(request_context.planning_summary.version or 0)

        if on_progress := getattr(request_context, "progress_callback", None):
            with contextlib.suppress(Exception):
                await on_progress("正在把这次调整整理成预览...")

        try:
            result_text, result, _duration_ms = await self._execute_semantic_plan_payload(
                request_context=request_context,
                plan_payload=plan_payload,
            )
        except Exception:
            logger.warning(
                "Complete unexecuted plan_next preview failed: session_id=%s action_family=%s",
                session_id,
                action_family,
                exc_info=True,
            )
            return None

        reply = _build_plan_timeout_fallback_reply(result, user_prompt=content) or str(
            result.get("summary")
            or result.get("state_summary")
            or plan_payload.get("preview_summary")
            or ""
        ).strip()
        if not reply:
            reply = "已把这次调整整理成预览，确认前不会改动当前方案。"
        reply = _sanitize_reply_for_user(_normalize_user_facing_terms(reply))
        messages = _build_direct_plan_action_messages(
            content,
            tool_call_id=f"complete-plan-next-preview-{uuid.uuid4().hex[:8]}",
            plan_payload=plan_payload,
            result_text=result_text,
            reply=reply,
            model_name="complete-unexecuted-plan-next-preview",
        )
        return _PlanActionRecoveryResult(
            reply=reply,
            messages=messages,
            route_decision={
                "source": "complete_unexecuted_plan_next_preview",
                "matched": True,
                "confidence": "structured",
                "route": action_family,
            },
        )

    async def _maybe_recover_atomic_preview_from_unmatched_fix_proposal(
        self,
        *,
        session_id: str,
        content: str,
        request_context: RequestContext,
        latest_plan_result: dict[str, Any],
    ) -> _PlanActionRecoveryResult | None:
        if resolve_pending_confirmation(request_context) is not None:
            return None
        if str(latest_plan_result.get("action_family") or "").strip() != "preview_fix_proposal":
            return None
        if str(latest_plan_result.get("result_kind") or "").strip() != "fix_proposal_preview":
            return None

        synthetic_context = _latest_plan_semantic_route_context(
            [
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name="execute_plan_action",
                            content=json.dumps(latest_plan_result, ensure_ascii=False, default=str),
                            tool_call_id="unmatched-fix-proposal-preview",
                        )
                    ]
                )
            ]
        )
        decision = await self._classify_plan_action_recovery(
            session_id=session_id,
            content=content,
            request_context=request_context,
            recent_plan_context=synthetic_context,
        )
        if decision is None:
            return None
        return await self._execute_recovered_plan_action(
            session_id=session_id,
            content=content,
            request_context=request_context,
            decision=decision,
        )

    async def _maybe_recover_atomic_preview_after_agent_interruption(
        self,
        *,
        session_id: str,
        content: str,
        request_context: RequestContext,
    ) -> _PlanActionRecoveryResult | None:
        """Recover an explicit atomic plan edit when the agent times out before tools.

        This is intentionally limited to the structured recovery classifier and
        then re-enters the normal plan_next_action -> execute_plan_action path.
        It does not infer user intent from fixed wording.
        """

        if resolve_pending_confirmation(request_context) is not None:
            return None
        recent_plan_context = _latest_plan_semantic_route_context(
            getattr(request_context, "chat_history", None)
        )
        if not _plan_recovery_has_context(request_context, recent_plan_context):
            return None
        decision = await self._classify_plan_action_recovery(
            session_id=session_id,
            content=content,
            request_context=request_context,
            recent_plan_context=recent_plan_context,
        )
        if decision is None:
            return None
        return await self._execute_recovered_plan_action(
            session_id=session_id,
            content=content,
            request_context=request_context,
            decision=decision,
        )

    async def _create_interrupted_plan_action_recovery_response(
        self,
        *,
        session_id: str,
        content: str,
        history: list[Any] | None,
        turn_event: dict[str, Any],
        recovery: _PlanActionRecoveryResult,
    ) -> ChatServiceResponseEnvelope | None:
        confirmation_candidate = _extract_plan_confirmation_candidate(recovery.messages)
        if confirmation_candidate is None:
            return None
        card = await _create_pending_plan_confirmation_response(
            session_id,
            confirmation_candidate,
        )
        primary = _plan_confirmation_card_primary_reply(confirmation_candidate)
        recovery_messages = list(recovery.messages or [])
        if recovery.reply != primary:
            _replace_text_reply(recovery_messages, recovery.reply, primary)
        recovery_event = dict(turn_event)
        recovery_route_decision = dict(recovery_event.get("routeDecision") or {})
        recovery_route_decision["fallbackReason"] = "plan_action_recovery"
        recovery_route_decision["recovery"] = dict(recovery.route_decision or {})
        recovery_event["routeDecision"] = recovery_route_decision
        recovery_event["scene"] = "plan"
        recovery_event["pendingType"] = "plan"
        recovery_event["actionFamily"] = str(confirmation_candidate.get("action_family") or "").strip() or None
        recovery_event["postProcessingApplied"] = ["plan_action_recovery"]
        recovery_event["status"] = "success"
        recovery_event["errorType"] = None
        with contextlib.suppress(Exception, asyncio.CancelledError):
            await self.history_store.save(
                session_id,
                list(history or []) + _append_route_observability_message(recovery_messages, recovery_event),
            )
        return ChatServiceResponseEnvelope(primary=primary, followups=[card])

    async def _maybe_recover_promised_fix_preview_card(
        self,
        *,
        session_id: str,
        content: str,
        reply: str,
        request_context: RequestContext,
        tool_context_messages: list[Any] | None,
    ) -> tuple[WSResponse, dict[str, Any]] | None:
        if resolve_pending_confirmation(request_context) is not None:
            return None
        if _extract_plan_confirmation_candidate(tool_context_messages) is not None:
            return None
        if not _reply_promises_fix_proposal_preview(reply):
            return None
        latest_result = _latest_readonly_plan_execution_result(tool_context_messages)
        if not isinstance(latest_result, dict):
            return None
        if not await _user_requested_fix_proposal_preview(
            content=content,
            request_context=request_context,
            latest_plan_result=latest_result,
        ):
            return None
        facts = latest_result.get("facts") if isinstance(latest_result.get("facts"), dict) else {}
        target_strategies, target_issue_codes, target_scope_explicit = await _infer_fix_proposal_target_scope(
            content=content,
            request_context=request_context,
            latest_plan_result=latest_result,
        )
        if target_scope_explicit and not target_strategies and not target_issue_codes:
            return None
        ready_proposal = await _select_ready_fix_proposal_for_user_goal(
            facts,
            content=content,
            reply=reply,
            request_context=request_context,
            target_strategies=target_strategies,
            target_issue_codes=target_issue_codes,
        )
        if ready_proposal is None:
            return None
        fix_facts = facts.get("fix_proposals") if isinstance(facts.get("fix_proposals"), dict) else {}
        source_version_guard = _as_int(
            fix_facts.get("source_version_guard")
            or latest_result.get("source_backend_version")
            or latest_result.get("planning_version")
        )
        if source_version_guard <= 0:
            return None
        card = await _create_pending_fix_proposal_confirmation_response(
            session_id,
            ready_proposal,
            source_version_guard=source_version_guard,
        )
        if card is None:
            return None
        return card, ready_proposal

    async def _maybe_recover_composite_goal_after_plan_attempt(
        self,
        *,
        session_id: str,
        content: str,
        request_context: RequestContext,
        tool_context_messages: list[Any] | None,
        allow_actionable_fix_preview: bool = False,
        allow_intent_preview_mixed_path: bool = False,
    ) -> WSResponse | None:
        pending = resolve_pending_confirmation(request_context)
        if pending is not None and getattr(pending, "kind", None) != "intent_change":
            return None
        if _tool_calls_include_intent_preview(tool_context_messages) and not allow_intent_preview_mixed_path:
            return None
        if _extract_plan_confirmation_candidate(tool_context_messages) is not None:
            return None
        if not _tool_calls_include_plan_chain(tool_context_messages):
            return None
        attempted_result = (
            _latest_fix_proposal_preview_result(tool_context_messages)
            if allow_actionable_fix_preview
            else None
        )
        if not isinstance(attempted_result, dict) and allow_intent_preview_mixed_path:
            attempted_result = _latest_non_actionable_plan_result(tool_context_messages)
        if not isinstance(attempted_result, dict) and allow_intent_preview_mixed_path:
            attempted_result = _latest_review_plan_result(tool_context_messages)
        if not isinstance(attempted_result, dict):
            attempted_result = _latest_plan_mutation_attempt_result(tool_context_messages)
        if not isinstance(attempted_result, dict):
            attempted_result = _latest_non_actionable_plan_result(tool_context_messages)
        if not isinstance(attempted_result, dict):
            attempted_result = _latest_review_plan_result(tool_context_messages)
        if not isinstance(attempted_result, dict):
            return None
        attempted_action_family = str(attempted_result.get("action_family") or "").strip()
        attempted_result_kind = str(attempted_result.get("result_kind") or "").strip()
        if attempted_action_family not in {"add_units", "remove_units", "replace_units"}:
            if attempted_action_family not in {"review_plan", "analyze_adjustment", "preview_fix_proposal"}:
                return None
            if not _plan_execution_result_is_non_actionable(attempted_result):
                actionable_fix_preview_allowed = (
                    allow_actionable_fix_preview
                    and attempted_action_family == "preview_fix_proposal"
                    and attempted_result_kind == "fix_proposal_preview"
                )
                review_result_allowed = (
                    attempted_action_family == "review_plan"
                    and attempted_result_kind == "review_result"
                )
                if not actionable_fix_preview_allowed and not review_result_allowed:
                    return None
        try:
            decision = await classify_composite_goal_action(
                content,
                request_context=request_context,
                attempted_action_family=attempted_action_family,
                attempted_result=attempted_result,
            )
        except Exception:
            logger.warning(
                "Composite goal recovery classification failed: session_id=%s",
                session_id,
                exc_info=True,
            )
            return None
        if (
            allow_intent_preview_mixed_path
            and _tool_calls_include_intent_preview(tool_context_messages)
            and str(getattr(decision, "action", "") or "").strip() != "tuition_budget_scope"
        ):
            return None

        return await self._create_composite_goal_recovery_card(
            session_id=session_id,
            content=content,
            request_context=request_context,
            decision=decision,
            attempted_action_family=attempted_action_family,
            attempted_result=attempted_result,
            context_source="composite_goal_recovery_after_plan_attempt",
        )

    async def _maybe_override_plan_confirmation_with_composite_goal(
        self,
        *,
        session_id: str,
        content: str,
        request_context: RequestContext,
        plan_confirmation_candidate: dict[str, Any] | None,
    ) -> WSResponse | None:
        if not isinstance(plan_confirmation_candidate, dict):
            return None
        attempted_action_family = str(
            plan_confirmation_candidate.get("action_family") or ""
        ).strip()
        if attempted_action_family not in {"add_units", "remove_units", "replace_units"}:
            return None
        if isinstance(plan_confirmation_candidate.get("intent_update"), dict):
            intent_update = plan_confirmation_candidate.get("intent_update") or {}
            if intent_update.get("selected"):
                return None
        try:
            decision = await classify_composite_goal_action(
                content,
                request_context=request_context,
                attempted_action_family=attempted_action_family,
                attempted_result={
                    "action_family": attempted_action_family,
                    "result_kind": "preview_only",
                    "summary": str(plan_confirmation_candidate.get("summary") or "").strip(),
                    "planning_version": _as_int(
                        plan_confirmation_candidate.get("planning_version")
                        or plan_confirmation_candidate.get("source_backend_version")
                    ),
                },
            )
        except Exception:
            logger.warning(
                "Composite goal override classification failed: session_id=%s",
                session_id,
                exc_info=True,
            )
            return None

        return await self._create_composite_goal_recovery_card(
            session_id=session_id,
            content=content,
            request_context=request_context,
            decision=decision,
            attempted_action_family=attempted_action_family,
            attempted_result={
                "action_family": attempted_action_family,
                "result_kind": "preview_only",
                "summary": str(plan_confirmation_candidate.get("summary") or "").strip(),
                "planning_version": _as_int(
                    plan_confirmation_candidate.get("planning_version")
                    or plan_confirmation_candidate.get("source_backend_version")
                ),
            },
            context_source="composite_goal_override_plan_confirmation",
        )

    async def _maybe_recover_unbacked_composite_goal(
        self,
        *,
        session_id: str,
        content: str,
        reply: str,
        tool_context_messages: list[Any] | None,
        request_context: RequestContext,
        allow_empty_intent_preview: bool = False,
    ) -> WSResponse | None:
        pending = resolve_pending_confirmation(request_context)
        if pending is not None and getattr(pending, "kind", None) != "intent_change":
            return None
        if not _reply_looks_like_plan_action_recovery_boundary(reply) and not allow_empty_intent_preview:
            return None
        if _tool_calls_include_intent_preview(tool_context_messages) and not allow_empty_intent_preview:
            return None
        if _extract_plan_confirmation_candidate(tool_context_messages) is not None:
            return None
        tool_call_parts = list(_iter_tool_call_parts(tool_context_messages))
        if allow_empty_intent_preview:
            if not _tool_returns_intent_non_pending(tool_context_messages):
                return None
            if any(part.tool_name not in _INTENT_PREVIEW_TOOL_NAMES for part in tool_call_parts):
                return None
        elif tool_call_parts:
            return None
        recent_history_plan_context = _latest_plan_semantic_route_context(getattr(request_context, "chat_history", None))
        if allow_empty_intent_preview:
            if not _has_plan_semantic_route_context(
                getattr(request_context, "planning_summary", None),
                recent_history_plan_context,
            ):
                return None
        elif not _plan_recovery_has_context(
            request_context,
            recent_history_plan_context,
        ):
            return None
        try:
            decision = await classify_composite_goal_action(
                content,
                request_context=request_context,
                attempted_action_family="intent_preview_empty" if allow_empty_intent_preview else "",
                attempted_result={
                    "result_kind": "intent_preview_empty" if allow_empty_intent_preview else "unbacked_plan_boundary",
                    "summary": reply,
                },
            )
        except Exception:
            logger.warning(
                "Unbacked composite goal recovery classification failed: session_id=%s",
                session_id,
                exc_info=True,
            )
            return None

        return await self._create_composite_goal_recovery_card(
            session_id=session_id,
            content=content,
            request_context=request_context,
            decision=decision,
            attempted_action_family="user_goal",
            attempted_result={},
            context_source="composite_goal_recovery_without_plan_attempt",
        )

    async def _maybe_recover_unbacked_composite_goal_without_tools(
        self,
        *,
        session_id: str,
        content: str,
        reply: str,
        tool_context_messages: list[Any] | None,
        request_context: RequestContext,
    ) -> WSResponse | None:
        """Recover high-side-effect user goals when the full agent skipped tools.

        The main path is still explicit Intent/Plan tool use. This recovery is a
        protocol guard for model turns that verbally promise a confirmation but
        produced no active pending card. It relies on the semantic composite-goal
        classifier and then re-enters the normal Java user-goal proposal path.
        """
        if resolve_pending_confirmation(request_context) is not None:
            return None
        if _extract_plan_confirmation_candidate(tool_context_messages) is not None:
            return None
        if list(_iter_tool_call_parts(tool_context_messages)):
            return None
        if not _plan_recovery_has_context(
            request_context,
            _latest_plan_semantic_route_context(getattr(request_context, "chat_history", None)),
        ):
            return None
        try:
            decision = await classify_composite_goal_action(
                content,
                request_context=request_context,
                attempted_action_family="no_tool_turn",
                attempted_result={
                    "result_kind": "unbacked_no_tool_turn",
                    "summary": reply,
                },
            )
        except Exception:
            logger.warning(
                "No-tool composite goal recovery classification failed: session_id=%s",
                session_id,
                exc_info=True,
            )
            return None

        card = await self._create_composite_goal_recovery_card(
            session_id=session_id,
            content=content,
            request_context=request_context,
            decision=decision,
            attempted_action_family="no_tool_turn",
            attempted_result={},
            context_source="composite_goal_recovery_without_tools",
        )
        if _pending_card_kind(card) in {"plan_mutation", "intent_change", "readonly_notice"}:
            return card
        if not _reply_looks_like_plan_action_recovery_boundary(reply):
            return None
        if str(getattr(decision, "action", "") or "").strip() != "none":
            return None
        return await _recover_unbacked_intent_confirmation(
            session_id,
            request_context,
            reply=reply,
            force=True,
        )

    async def _maybe_recover_existing_intent_composite_goal(
        self,
        *,
        session_id: str,
        content: str,
        request_context: RequestContext,
        tool_context_messages: list[Any] | None,
    ) -> WSResponse | None:
        if resolve_pending_confirmation(request_context) is not None:
            return None
        if not _tool_returns_intent_non_pending(tool_context_messages):
            return None
        if _extract_plan_confirmation_candidate(tool_context_messages) is not None:
            return None
        if not _has_plan_semantic_route_context(
            getattr(request_context, "planning_summary", None),
            _latest_plan_semantic_route_context(getattr(request_context, "chat_history", None)),
        ):
            return None
        preview_payload = _latest_existing_only_intent_payload(tool_context_messages)
        if not isinstance(preview_payload, dict):
            return None
        merged_existing = _merge_existing_intent_payload(preview_payload)
        if not merged_existing:
            return None
        try:
            decision = await classify_composite_goal_action(
                content,
                request_context=request_context,
                attempted_action_family="intent_existing_only",
                attempted_result={
                    "result_kind": "intent_existing_only",
                    "summary": _summarize_intent_values(
                        merged_existing,
                        intent_mode=str(preview_payload.get("intentMode") or "constraint").strip() or "constraint",
                        constraint_intent_type=str(
                            preview_payload.get("constraintIntentType")
                            or preview_payload.get("constraint_intent_type")
                            or "default"
                        ).strip() or "default",
                    ),
                },
            )
        except Exception:
            logger.warning(
                "Existing intent composite goal classification failed: session_id=%s",
                session_id,
                exc_info=True,
            )
            return None

        card = await self._create_composite_goal_recovery_card(
            session_id=session_id,
            content=content,
            request_context=request_context,
            decision=decision,
            attempted_action_family="intent_existing_only",
            attempted_result={},
            context_source="composite_goal_recovery_from_existing_intent",
        )
        if _pending_card_kind(card) != "plan_mutation":
            return None
        return card

    async def _maybe_recover_tuition_budget_from_intent_preview(
        self,
        *,
        session_id: str,
        content: str,
        request_context: RequestContext,
        tool_context_messages: list[Any] | None,
    ) -> WSResponse | None:
        """Route budget constraints to user-goal plan proposals, not major intent.

        Tuition budget is not a major/school/region preference dimension. If the
        full agent produced a generic intent preview for such a turn, recover
        through the existing semantic composite-goal classifier and Java
        user-goal proposal path before persisting an incorrect intent card.
        """
        if resolve_pending_confirmation(request_context) is not None:
            return None
        if not _tool_calls_include_intent_preview(tool_context_messages):
            return None
        if _extract_plan_confirmation_candidate(tool_context_messages) is not None:
            return None
        if not _has_plan_semantic_route_context(
            getattr(request_context, "planning_summary", None),
            _latest_plan_semantic_route_context(getattr(request_context, "chat_history", None)),
        ):
            return None
        preview_payload = _extract_recent_intent_analysis_payload(tool_context_messages)
        if not isinstance(preview_payload, dict):
            return None
        try:
            decision = await classify_composite_goal_action(
                content,
                request_context=request_context,
                attempted_action_family="intent_preview",
                attempted_result={
                    "result_kind": "intent_preview",
                    "summary": _intent_card_primary_reply_from_preview_payload(preview_payload),
                },
            )
        except Exception:
            logger.warning(
                "Tuition budget composite recovery from intent preview failed: session_id=%s",
                session_id,
                exc_info=True,
            )
            return None
        if (
            str(getattr(decision, "action", "") or "").strip() != "tuition_budget_scope"
            or float(getattr(decision, "confidence", 0.0) or 0.0) < 0.85
            or _as_int(getattr(decision, "maxTuitionPerYear", None)) <= 0
        ):
            return None
        card = await self._create_composite_goal_recovery_card(
            session_id=session_id,
            content=content,
            request_context=request_context,
            decision=decision,
            attempted_action_family="intent_preview",
            attempted_result={"result_kind": "intent_preview"},
            context_source="tuition_budget_recovery_from_intent_preview",
        )
        if _pending_card_kind(card) != "plan_mutation":
            return None
        return card

    async def _create_composite_goal_recovery_card(
        self,
        *,
        session_id: str,
        content: str,
        request_context: RequestContext,
        decision: Any,
        attempted_action_family: str,
        attempted_result: dict[str, Any] | None,
        context_source: str,
    ) -> WSResponse | None:
        action = str(getattr(decision, "action", "none") or "none").strip()
        confidence = float(getattr(decision, "confidence", 0.0) or 0.0)
        scope_type = str(getattr(decision, "scopeType", "") or "").strip()
        if action not in {"only_keep_scope", "must_include_scope", "exclude_scope", "tuition_budget_scope"} or confidence < 0.85:
            return None
        if action == "tuition_budget_scope":
            max_tuition_per_year = _as_int(getattr(decision, "maxTuitionPerYear", None))
            if max_tuition_per_year <= 0:
                return None
            scope_type = "tuition"
        else:
            max_tuition_per_year = 0
        if action != "tuition_budget_scope" and scope_type not in {"major", "school", "region", "career", "program_type"}:
            return None
        target_values = _as_text_list(getattr(decision, "targetValues", []) or [])
        negative_values = _as_text_list(getattr(decision, "negativeValues", []) or [])
        if action in {"only_keep_scope", "must_include_scope"} and not target_values:
            return None
        if action == "exclude_scope" and not negative_values:
            return None
        if scope_type == "career":
            # Current Java user-goal proposal supports plan-scoped major/school/region
            # operations. Career-only goals remain intent-only until a concrete plan
            # action strategy exists server-side.
            return None

        constraint_intent_type = str(
            getattr(decision, "constraintIntentType", "") or ""
        ).strip()
        if action == "only_keep_scope":
            constraint_intent_type = "only_keep"
        elif action == "must_include_scope":
            constraint_intent_type = "must_have"
        elif constraint_intent_type not in {"default", "only_keep", "must_have"}:
            constraint_intent_type = "default"

        attempted_facts = (attempted_result or {}).get("facts") if isinstance((attempted_result or {}).get("facts"), dict) else {}
        attempted_fix_facts = (
            attempted_facts.get("fix_proposals")
            if isinstance(attempted_facts.get("fix_proposals"), dict)
            else {}
        )
        planning_version = _as_int(
            attempted_fix_facts.get("source_version_guard")
            or attempted_fix_facts.get("sourceVersionGuard")
            or (attempted_result or {}).get("source_version_guard")
            or (attempted_result or {}).get("sourceVersionGuard")
            or (attempted_result or {}).get("source_backend_version")
            or (attempted_result or {}).get("sourceBackendVersion")
            or (attempted_result or {}).get("planning_version")
            or (attempted_result or {}).get("planningVersion")
        )
        if getattr(request_context, "planning_summary", None) is not None:
            if planning_version <= 0:
                with contextlib.suppress(TypeError, ValueError):
                    planning_version = int(request_context.planning_summary.version or 0)
        if planning_version <= 0 and action != "tuition_budget_scope":
            intent_payload = _constraint_intent_payload_from_goal_decision(
                scope_type=scope_type,
                target_values=target_values,
                negative_values=negative_values,
                constraint_intent_type=constraint_intent_type,
            )
            if not isinstance(intent_payload, dict):
                return None
            selected_values = [
                item
                for item in intent_payload.get("selected", [])
                if isinstance(item, dict) and item
            ]
            if not selected_values:
                return None
            try:
                merged = merge_selected_values(selected_values)
            except Exception:
                logger.warning(
                    "Failed to merge composite goal intent fallback: session_id=%s",
                    session_id,
                    exc_info=True,
                )
                return None
            batch = await _resolve_session_batch(session_id)
            intent_payload["batch"] = batch
            summary = _summarize_intent_values(
                merged,
                intent_mode="constraint",
                constraint_intent_type=constraint_intent_type,
            )
            intent_response = await _create_pending_intent_confirmation_response(
                session_id,
                selected_data=intent_payload,
                merged=merged,
                intent_mode="constraint",
                batch=batch,
            )
            for followup in intent_response.followups:
                if isinstance(followup, WSResponse) and followup.type == "pendingConfirmationCard":
                    return followup
            return None
        if planning_version <= 0:
            if action == "tuition_budget_scope":
                return WSResponse(
                    type="reply",
                    session_id=session_id,
                    content=json.dumps(
                        {
                            "kind": "readonly_notice",
                            "reply": _build_tuition_budget_no_plan_reply(max_tuition_per_year),
                        },
                        ensure_ascii=False,
                    ),
                )
            return None

        goal = PlanGoal(
            goal_type=action,  # type: ignore[arg-type]
            user_original_text=content,
            target_scopes=[{"entity_type": scope_type, "values": target_values}] if target_values else [],
            negative_scopes=[{"entity_type": scope_type, "values": negative_values}] if negative_values else [],
            max_tuition_per_year=max_tuition_per_year if action == "tuition_budget_scope" else None,
            confidence="high",
        )
        intent_updates: list[dict[str, Any]] = []
        if action != "tuition_budget_scope":
            intent_update: dict[str, Any] = {
                "intentMode": "constraint",
                "constraintIntentType": constraint_intent_type,
            }
            if target_values:
                intent_update["targetScopes"] = [{"entity_type": scope_type, "values": target_values}]
            if negative_values:
                intent_update["negativeScopes"] = [{"entity_type": scope_type, "values": negative_values}]
            intent_updates.append(intent_update)
        composite = CompositePlanProposal(
            source_version=planning_version,
            goal=goal,
            intent_updates=intent_updates,
            plan_actions=[],
            decision_references=[],
            feasibility="ready",
            impact_summary=["这次会按你刚说的范围整理方案调整预览。"],
            requires_confirmation=True,
            post_apply_validation_plan=[
                "执行后重新读取当前方案",
                "执行后重新审查风险和提醒",
            ],
        ).model_dump()
        source = {
            "stage": "preview",
            "action_family": attempted_action_family,
            "user_goal": content,
            "planning_version": planning_version,
            "composite_proposal": composite,
            "result_kind": "composite_goal_recovery",
        }
        return await _maybe_create_plan_confirmation_from_structured_goal(
            session_id,
            source,
            context_source=context_source,
        )

    # ── 消息处理 ──────────────────────────────────────────────────

    async def handle_message(
        self, session_id: str, user_id: str, content: str,
        batch: str | None = None,
        score_detail: dict | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> str | WSResponse | ChatServiceResponseEnvelope:
        """处理一条用户消息，返回 Agent 回复（str 或 WSResponse）。"""
        context_progress_sent = False

        async def emit_context_progress() -> None:
            nonlocal context_progress_sent
            if context_progress_sent or on_progress is None:
                return
            context_progress_sent = True
            await on_progress(self._EARLY_CONTEXT_PROGRESS_HINT)

        async def delayed_context_progress() -> None:
            if on_progress is None:
                return
            await asyncio.sleep(self._EARLY_CONTEXT_PROGRESS_DELAY_SECONDS)
            if context_progress_sent:
                return
            await emit_context_progress()

        context_progress_task: asyncio.Task[None] | None = None
        if on_progress is not None:
            context_progress_task = asyncio.create_task(delayed_context_progress())

        async def finish_context_progress() -> None:
            if context_progress_task is not None:
                context_progress_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await context_progress_task

        history_task = asyncio.create_task(self.history_store.load(session_id))
        pending_state_task = asyncio.create_task(_load_pending_confirmation_state(session_id))
        try:
            history, backend_pending_state = await asyncio.gather(
                history_task,
                pending_state_task,
                return_exceptions=True,
            )
        except Exception:
            logger.exception("Failed to load chat history or pending state: session_id=%s", session_id)
            history = None
            backend_pending_state = None
        else:
            if isinstance(history, Exception):
                logger.exception("Failed to load chat history: session_id=%s", session_id)
                history = None
            if isinstance(backend_pending_state, Exception):
                logger.warning("Failed to load pending confirmation state: session_id=%s", session_id, exc_info=True)
                backend_pending_state = None
        if isinstance(backend_pending_state, dict) and str(backend_pending_state.get("status") or "").strip() == "active":
            await finish_context_progress()

        logger.info(
            "ChatService handling message: session_id=%s user_id=%s content_len=%d history_len=%d",
            session_id, user_id, len(content),
            len(history) if history else 0,
        )
        clear_recent_plan_execution_result(session_id, content)

        past_turn_count = _count_user_turns(history)
        current_turn = past_turn_count + 1

        # 打印原始 history 内容，便于调试格式
        # if history:
        #     for i, msg in enumerate(history):
        #         logger.info("history[%d] type=%s", i, type(msg).__name__)
        #         #logger.info("history[%d] type=%s content=%s", i, type(msg).__name__, msg)

        backend_pending = _pending_confirmation_from_state(backend_pending_state)
        runtime_history = build_runtime_history(
            history,
            latest_user_content=content,
            has_active_pending=backend_pending is not None,
            config=self.history_config,
        )
        chat_history = runtime_history.chat_history
        recent_intent_analysis = _extract_recent_intent_analysis_payload(runtime_history.model_history)
        if recent_intent_analysis is None:
            recent_intent_analysis = _extract_recent_intent_analysis_payload(history)
        logger.info(
            "Runtime history prepared: session_id=%s full_len=%d runtime_len=%d full_chars=%d runtime_chars=%d dropped_tool_returns=%d has_pending=%s",
            session_id,
            runtime_history.full_len,
            runtime_history.runtime_len,
            runtime_history.full_text_chars,
            runtime_history.runtime_text_chars,
            runtime_history.dropped_tool_return_count,
            runtime_history.has_pending,
        )

        # 获取用户成绩详情
        parsed_score_detail = None
        parsed_init_profile = None
        parsed_planning_summary = None
        score_response = None
        init_response = None
        planning_response = None
        context_load_tasks: list[asyncio.Task[Any]] = []
        if not score_detail:
            context_load_tasks.append(asyncio.create_task(get_user_score_detail(session_id)))
        context_load_tasks.extend(
            [
                asyncio.create_task(get_user_init_profile(session_id)),
                asyncio.create_task(get_planning_workspace_state(session_id)),
            ]
        )
        if context_load_tasks:
            results = await asyncio.gather(*context_load_tasks, return_exceptions=True)
            result_index = 0
            if not score_detail:
                score_response = results[result_index]
                result_index += 1
            init_response = results[result_index]
            planning_response = results[result_index + 1]

        if not score_detail:
            if isinstance(score_response, Exception):
                logger.warning("Failed to fetch user score detail: %s", score_response)
            elif isinstance(score_response, dict) and score_response.get("code") == 0:
                raw_data = score_response.get("data", {}).get("userScoreDetail", {})
                if raw_data:
                    parsed_score_detail = _parse_score_detail_from_backend(raw_data)
                    logger.info(
                        "Fetched score_detail: province=%s total_score=%d subjects=%s sex=%s",
                        parsed_score_detail.province,
                        parsed_score_detail.total_score,
                        parsed_score_detail.subject_list,
                        parsed_score_detail.sex,
                    )

        if isinstance(init_response, Exception):
            logger.warning("Failed to fetch user init profile: %s", init_response)
        elif isinstance(init_response, dict) and init_response.get("code") == 0:
            init_data = init_response.get("data", {}).get("userInitProfile", {})
            if init_data:
                parsed_init_profile = UserProfile.from_backend_format(init_data)
                logger.info(
                    "Fetched init_profile: strength_subjects=%s majors=%s neg_majors=%s provinces=%s",
                    parsed_init_profile.strength_subjects,
                    parsed_init_profile.major.level2,
                    parsed_init_profile.major.negative_level2,
                    parsed_init_profile.city.province,
                )

        if isinstance(planning_response, Exception):
            logger.warning("Failed to fetch planning state: %s", planning_response)
        elif isinstance(planning_response, dict) and planning_response.get("code") == 0:
            planning_data = planning_response.get("data", {})
            parsed_planning_summary = PlanningSummary.from_backend_state(planning_data)
            if parsed_planning_summary:
                logger.info(
                    "Fetched planning summary: phase=%s version=%s working_total=%s ordered_total=%s review_risk=%s",
                    parsed_planning_summary.phase,
                    parsed_planning_summary.version,
                    parsed_planning_summary.working_total,
                    parsed_planning_summary.ordered_total,
                    parsed_planning_summary.review_risk_count,
                )

        # 构建统一的 ConversationPhase
        conversation_phase = ConversationPhase.from_pending_confirmation(
            backend_pending,
            planning_summary=parsed_planning_summary,
            turn_count=past_turn_count,
        )
        conversation_phase.turn_count = current_turn
        stale_pending_notice = ""
        state_sync = PlanningStateSync()
        version_result = state_sync.check_version(conversation_phase, parsed_planning_summary)
        if not version_result.is_current:
            logger.info(
                "Planning version drift at turn start: session_id=%s local=%s remote=%s drift=%s",
                session_id,
                version_result.local_version,
                version_result.remote_version,
                version_result.drift,
            )
        if conversation_phase.pending is not None and conversation_phase.pending.kind == "plan_mutation":
            stale_event = state_sync.invalidate_if_stale(
                conversation_phase,
                current_turn=current_turn,
                planning_summary=parsed_planning_summary,
            )
            if stale_event.should_clear_pending:
                logger.info(
                    "Clearing stale plan pending before model run: session_id=%s cause=%s message=%s",
                    session_id,
                    getattr(stale_event.cause, "value", None),
                    stale_event.message,
                )
                stale_pending_notice = stale_event.message or "上一轮方案预览已经失效。"
                await _expire_active_pending_confirmation_state(
                    session_id,
                    reason=str(getattr(stale_event.cause, "value", None) or "stale_pending"),
                )
                conversation_phase.clear_pending()
                backend_pending_state = None
                backend_pending = None

        # 创建 RequestContext
        request_context = RequestContext(
            userid=user_id,
            sessionid=session_id,
            chat_history=chat_history,
            batch=batch,
            score_detail=parsed_score_detail,
            init_profile=parsed_init_profile,
            planning_summary=parsed_planning_summary,
            conversation_phase=conversation_phase,
            progress_callback=on_progress,
            allow_explore_inner_llm=False,
            enable_intent_side_effect_arbitration=True,
            recent_intent_analysis=recent_intent_analysis,
            stale_pending_notice=stale_pending_notice,
        )
        active_pending = resolve_pending_confirmation(request_context)
        active_pending_kind = str(getattr(active_pending, "kind", "") or "").strip()
        active_plan_payload_text = resolve_pending_plan_payload_text(request_context)
        turn_started_at = time.monotonic()

        backend_pending_id = str((backend_pending_state or {}).get("pendingId") or "").strip()
        backend_pending_kind = str((backend_pending_state or {}).get("kind") or "").strip()
        backend_pending_status = str((backend_pending_state or {}).get("status") or "").strip()
        if backend_pending_id and backend_pending_status == "active":
            if _is_direct_pending_confirmation_turn(content, backend_pending_kind):
                reply = await self.handle_pending_confirmation(
                    session_id,
                    user_id,
                    json.dumps(
                        {
                            "action": "confirm",
                            "kind": backend_pending_kind,
                            "pendingId": backend_pending_id,
                        },
                        ensure_ascii=False,
                    ),
                    confirmation_entry="short_text",
                    user_prompt_content=content,
                )
                await finish_context_progress()
                return reply
            pending_route_decision = None
            try:
                pending_route_decision = await classify_pending_confirmation_action(
                    content,
                    pending_state=backend_pending_state,
                    request_context=request_context,
                )
            except Exception:
                logger.warning(
                    "Semantic pending confirmation classification failed: session_id=%s",
                    session_id,
                    exc_info=True,
                )
            pending_route_action = str(getattr(pending_route_decision, "action", "none") or "none")
            pending_route_confidence = float(getattr(pending_route_decision, "confidence", 0.0) or 0.0)
            if pending_route_confidence >= _SEMANTIC_PENDING_CONFIRMATION_CONFIDENCE_THRESHOLD:
                if pending_route_action == "confirm_pending":
                    reply = await self.handle_pending_confirmation(
                        session_id,
                        user_id,
                        json.dumps(
                            {
                                "action": "confirm",
                                "kind": backend_pending_kind,
                                "pendingId": backend_pending_id,
                            },
                            ensure_ascii=False,
                        ),
                        confirmation_entry="short_text",
                        user_prompt_content=content,
                    )
                    await finish_context_progress()
                    return reply
                if pending_route_action == "reject_pending":
                    reply = await self.handle_pending_confirmation(
                        session_id,
                        user_id,
                        json.dumps(
                            {
                                "action": "cancel",
                                "kind": backend_pending_kind,
                                "pendingId": backend_pending_id,
                            },
                            ensure_ascii=False,
                        ),
                        confirmation_entry="short_text",
                        user_prompt_content=content,
                    )
                    await finish_context_progress()
                    return reply
            if (
                pending_route_action == "ask_pending_impact"
                and pending_route_confidence >= _SEMANTIC_PENDING_CONFIRMATION_CONFIDENCE_THRESHOLD
            ):
                if on_progress is not None:
                    with contextlib.suppress(Exception):
                        await on_progress(self._INITIAL_PROGRESS_HINT)
                reply = _build_pending_readonly_impact_reply(backend_pending_state or {})
                await _save_direct_guard_history(
                    self.history_store,
                    session_id,
                    history,
                    content,
                    reply,
                    model_name="pending-readonly-impact",
                )
                _log_conversation_turn_event(
                    sessionId=session_id,
                    userId=user_id,
                    scene="plan" if backend_pending_kind == "plan_mutation" else "intent",
                    routingPath="pending_readonly_impact",
                    pendingType="plan" if backend_pending_kind == "plan_mutation" else "intent",
                    actionFamily=str((backend_pending_state or {}).get("actionFamily") or "") or None,
                    totalDurationMs=int((time.monotonic() - turn_started_at) * 1000),
                    status="success",
                    errorType=None,
                )
                await finish_context_progress()
                return reply

        if active_pending is None and _latest_turn_looks_readonly(history) and _is_readonly_closure_ack(content):
            reply = _readonly_closure_ack_reply()
            new_messages = [
                ModelRequest(parts=[UserPromptPart(content=content)]),
                ModelResponse(parts=[TextPart(content=reply)], model_name="direct-readonly-closure-ack"),
            ]
            try:
                history_to_save = list(history or [])
                history_to_save.extend(new_messages)
                await self.history_store.save(session_id, history_to_save)
            except Exception:
                logger.exception("Failed to save readonly closure ack history: session_id=%s", session_id)
            _log_conversation_turn_event(
                sessionId=session_id,
                userId=user_id,
                scene="explore",
                routingPath="readonly_closure_ack",
                pendingType=None,
                actionFamily=None,
                totalDurationMs=int((time.monotonic() - turn_started_at) * 1000),
                status="success",
                errorType=None,
            )
            await finish_context_progress()
            return reply

        if (
            active_pending is None
            and _is_no_pending_confirmation_turn(content)
            and not _latest_turn_allows_plan_followup_confirmation(history)
        ):
            reply = _no_pending_confirmation_guard_reply()
            await _save_direct_guard_history(
                self.history_store,
                session_id,
                history,
                content,
                reply,
                model_name="no-pending-confirmation-guard",
            )
            _log_conversation_turn_event(
                sessionId=session_id,
                userId=user_id,
                scene="plan",
                routingPath="no_pending_confirmation_guard",
                pendingType=None,
                actionFamily=None,
                totalDurationMs=int((time.monotonic() - turn_started_at) * 1000),
                status="success",
                errorType=None,
            )
            await finish_context_progress()
            return reply

        semantic_plan_action_reply = await self._maybe_handle_semantic_plan_action(
            session_id=session_id,
            user_id=user_id,
            content=content,
            history=history,
            request_context=request_context,
            turn_started_at=turn_started_at,
            on_progress=on_progress,
        )
        if semantic_plan_action_reply is not None:
            await finish_context_progress()
            return semantic_plan_action_reply

        progress_sent = False
        tool_progress_sent = False
        last_progress_at: float | None = None

        async def emit_progress(hint: str, *, is_tool_progress: bool = False) -> None:
            nonlocal progress_sent, tool_progress_sent, last_progress_at
            progress_sent = True
            if is_tool_progress:
                tool_progress_sent = True
            last_progress_at = time.monotonic()
            if on_progress is not None:
                await on_progress(hint)

        async def progress_wrapper(hint: str) -> None:
            await emit_progress(hint, is_tool_progress=True)

        async def delayed_initial_progress() -> None:
            if on_progress is None:
                return
            await asyncio.sleep(self._INITIAL_PROGRESS_DELAY_SECONDS)
            if progress_sent:
                return
            await emit_progress(self._INITIAL_PROGRESS_HINT)

        progress_started_at = time.monotonic()

        async def delayed_long_progress() -> None:
            if on_progress is None:
                return
            model_wait_hints = dict(self._LONG_PROGRESS_MODEL_WAIT_HINTS)
            tool_hints = dict(self._LONG_PROGRESS_TOOL_HINTS)
            delay_points = sorted(set(model_wait_hints) | set(tool_hints))
            for delay_seconds in delay_points:
                wait_seconds = max(0.0, progress_started_at + delay_seconds - time.monotonic())
                await asyncio.sleep(wait_seconds)
                now = time.monotonic()
                if (
                    last_progress_at is not None
                    and now - last_progress_at < self._MIN_PROGRESS_INTERVAL_SECONDS
                ):
                    continue
                hint = (
                    tool_hints.get(delay_seconds)
                    if tool_progress_sent
                    else model_wait_hints.get(delay_seconds)
                )
                if not hint:
                    continue
                await emit_progress(hint)

        initial_progress_task: asyncio.Task[None] | None = None
        long_progress_task: asyncio.Task[None] | None = None
        if on_progress is not None:
            initial_progress_task = asyncio.create_task(delayed_initial_progress())
            long_progress_task = asyncio.create_task(delayed_long_progress())

        llm_started_at = time.monotonic()
        try:
            reply, new_messages, all_messages, usage = await self.agent.run_with_message_deltas(
                user_prompt=content,
                message_history=runtime_history.model_history,
                deps=request_context,
                on_progress=progress_wrapper if on_progress is not None else None,
            )
        except BaseException as exc:
            llm_duration_ms = int((time.monotonic() - llm_started_at) * 1000)
            status = "cancelled" if isinstance(exc, asyncio.CancelledError) else "error"
            turn_event = {
                "sessionId": session_id,
                "userId": user_id,
                "scene": "unknown",
                "routingPath": "full_agent",
                "routeDecision": {
                    "source": "full_agent",
                    "matched": False,
                    "confidence": "model",
                    "route": "unknown",
                    "fallbackReason": "agent_run_interrupted",
                    "agentRun": dict(getattr(request_context, "agent_observability", {}) or {}),
                },
                "pendingType": "plan" if active_pending_kind == "plan_mutation" else "intent" if active_pending_kind == "intent_change" else None,
                "actionFamily": None,
                "modelProvider": _llm_config_value(self.llm_client, "provider"),
                "modelName": _llm_config_value(self.llm_client, "model_name"),
                "llmRequests": None,
                "inputTokens": None,
                "outputTokens": None,
                "totalTokens": None,
                "toolCallCount": None,
                "totalDurationMs": int((time.monotonic() - turn_started_at) * 1000),
                "llmDurationMs": llm_duration_ms,
                "toolDurationMs": None,
                "toolCalls": [],
                "postProcessingApplied": [],
                "status": status,
                "errorType": type(exc).__name__,
            }
            _log_conversation_turn_event(**turn_event)
            with contextlib.suppress(Exception, asyncio.CancelledError):
                failed_history = list(history or [])
                failed_history.extend(
                    _append_route_observability_message(
                        [ModelRequest(parts=[UserPromptPart(content=content)])],
                        turn_event,
                    )
                )
                await self.history_store.save(session_id, failed_history)
            recent_plan_fallback = None
            if not isinstance(exc, asyncio.CancelledError):
                with contextlib.suppress(Exception):
                    recent_plan_fallback = await build_interruption_fallback_from_recent_plan_execution(
                        session_id,
                        content,
                    )
            recent_intent_payload = None
            if not isinstance(exc, asyncio.CancelledError):
                recent_intent_payload = (
                    request_context.agent_observability.get("latestIntentPreviewPayload")
                    if isinstance(request_context.agent_observability, dict)
                    else None
                )
            if isinstance(recent_intent_payload, dict):
                recovered_intent_card = None
                with contextlib.suppress(Exception):
                    recovered_intent_card = await _create_pending_intent_confirmation_from_preview_payload(
                        session_id,
                        recent_intent_payload,
                    )
                if recovered_intent_card is not None:
                    primary_text = _intent_card_primary_reply_from_preview_payload(recent_intent_payload)
                    recovery_messages = [
                        ModelRequest(parts=[UserPromptPart(content=content)]),
                        ModelResponse(
                            parts=[TextPart(content=primary_text)],
                            model_name="agent-interruption-intent-preview-recovery",
                        ),
                    ]
                    with contextlib.suppress(Exception, asyncio.CancelledError):
                        await self.history_store.save(
                            session_id,
                            list(history or []) + _append_route_observability_message(recovery_messages, turn_event),
                        )
                    if context_progress_task is not None:
                        context_progress_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await context_progress_task
                    return ChatServiceResponseEnvelope(primary=primary_text, followups=[recovered_intent_card])
            if recent_plan_fallback is not None:
                recovery_messages = [
                    ModelRequest(parts=[UserPromptPart(content=content)]),
                    ModelResponse(
                        parts=[TextPart(content=recent_plan_fallback.primary)],
                        model_name="agent-interruption-plan-preview-recovery",
                    ),
                ]
                with contextlib.suppress(Exception, asyncio.CancelledError):
                    await self.history_store.save(
                        session_id,
                        list(history or []) + _append_route_observability_message(recovery_messages, turn_event),
                    )
                if context_progress_task is not None:
                    context_progress_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await context_progress_task
                return recent_plan_fallback
            recovered_interrupted_plan_action = None
            if not isinstance(exc, asyncio.CancelledError):
                recovered_interrupted_plan_action = await self._maybe_recover_atomic_preview_after_agent_interruption(
                    session_id=session_id,
                    content=content,
                    request_context=request_context,
                )
            if recovered_interrupted_plan_action is not None:
                recovered_interrupted_response = await self._create_interrupted_plan_action_recovery_response(
                    session_id=session_id,
                    content=content,
                    history=history,
                    turn_event=turn_event,
                    recovery=recovered_interrupted_plan_action,
                )
                if recovered_interrupted_response is not None:
                    if context_progress_task is not None:
                        context_progress_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await context_progress_task
                    return recovered_interrupted_response
            fallback_reply = _build_agent_interruption_fallback_reply(
                content,
                parsed_planning_summary,
                request_context.agent_observability,
                batch=batch,
            )
            if fallback_reply and not isinstance(exc, asyncio.CancelledError):
                fallback_model_name = (
                    "agent-interruption-readonly-fallback"
                    if _agent_interruption_looks_readonly(content, request_context.agent_observability)
                    else "agent-interruption-fallback"
                )
                fallback_messages = [
                    ModelRequest(parts=[UserPromptPart(content=content)]),
                    ModelResponse(parts=[TextPart(content=fallback_reply)], model_name=fallback_model_name),
                ]
                with contextlib.suppress(Exception, asyncio.CancelledError):
                    await self.history_store.save(
                        session_id,
                        list(history or []) + _append_route_observability_message(fallback_messages, turn_event),
                    )
                if context_progress_task is not None:
                    context_progress_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await context_progress_task
                return fallback_reply
            raise
        finally:
            for progress_task in (initial_progress_task, long_progress_task):
                if progress_task is not None:
                    progress_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await progress_task
            if context_progress_task is not None:
                context_progress_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await context_progress_task
        llm_duration_ms = int((time.monotonic() - llm_started_at) * 1000)

        # ── Token usage 追踪 ──────────────────────────────────────
        tracker = self._usage_trackers.get(session_id)
        if tracker is None:
            tracker = UsageTracker(session_id=session_id)
            self._usage_trackers[session_id] = tracker
        tracker.record(usage)

        logger.info(
            "Token usage [turn]: session_id=%s input=%d output=%d total=%d requests=%d tools=%d",
            session_id, usage.input_tokens, usage.output_tokens,
            usage.total_tokens, usage.requests, usage.tool_calls,
        )
        if tracker.turn_count % self._LOG_INTERVAL == 0:
            logger.info("Token usage [session cumulative]: %s", tracker.summary())

        tool_context_messages = _select_current_tool_context_messages(
            new_messages,
            all_messages,
            runtime_history,
        )

        plan_chain_used = _tool_calls_include_plan_chain(tool_context_messages)

        intent_preview_used_current_turn = _tool_calls_include_intent_preview(tool_context_messages)
        intent_preview_used = intent_preview_used_current_turn
        intent_non_pending = _tool_returns_intent_non_pending(tool_context_messages)
        intent_side_effect_decision = request_context.agent_observability.get("intentSideEffectDecision")
        intent_interest_stage_result = _tool_returns_interest_stage_intent_analysis(tool_context_messages)
        intent_preview_downgraded = (
            intent_interest_stage_result
            or _semantic_intent_decision_requires_readonly(
                intent_side_effect_decision if isinstance(intent_side_effect_decision, dict) else None
            )
        )
        if intent_preview_downgraded and getattr(request_context, "conversation_phase", None) is not None:
            request_context.conversation_phase.clear_pending()
            active_pending_kind = ""
        readonly_prompt = _prompt_explicitly_readonly(content)
        negative_plan_ack = _prompt_rejects_current_plan_action(content)
        readonly_mutation_preview_guarded = False
        if (readonly_prompt or negative_plan_ack) and _tool_returns_mutating_plan_preview(tool_context_messages):
            _remove_current_turn_mutating_plan_preview(new_messages)
            _remove_current_turn_mutating_plan_preview(all_messages)
            if isinstance(reply, str) and _reply_has_plan_confirmation_request(reply):
                guarded_reply = _remove_unbacked_plan_confirmation_copy(reply).strip()
                if not guarded_reply or _reply_has_plan_confirmation_request(guarded_reply):
                    guarded_reply = _READONLY_MUTATION_GUARD_REPLY
                _replace_text_reply(new_messages, reply, guarded_reply)
                _replace_text_reply(all_messages, reply, guarded_reply)
                reply = guarded_reply
            readonly_mutation_preview_guarded = True
        if (
            (plan_chain_used or _should_guard_plan_reply(content))
            and isinstance(reply, str)
            and _plan_reply_needs_normalization(reply)
        ):
            normalized_reply = _normalize_plan_reply_style(reply)
            _replace_text_reply(new_messages, reply, normalized_reply)
            _replace_text_reply(all_messages, reply, normalized_reply)
            reply = normalized_reply

        if plan_chain_used and isinstance(reply, str) and not readonly_mutation_preview_guarded:
            bounded_reply = _append_plan_preview_confirmation_boundary(reply, tool_context_messages)
            if bounded_reply != reply:
                _replace_text_reply(new_messages, reply, bounded_reply)
                _replace_text_reply(all_messages, reply, bounded_reply)
                reply = bounded_reply

        if intent_preview_used and not intent_preview_downgraded and isinstance(reply, str):
            pending_intent_reply = _normalize_pending_intent_reply(reply)
            if pending_intent_reply != reply:
                _replace_text_reply(new_messages, reply, pending_intent_reply)
                _replace_text_reply(all_messages, reply, pending_intent_reply)
                reply = pending_intent_reply

        if intent_preview_downgraded and isinstance(reply, str):
            downgraded_intent_reply = _normalize_downgraded_intent_preview_reply(reply)
            if downgraded_intent_reply != reply:
                _replace_text_reply(new_messages, reply, downgraded_intent_reply)
                _replace_text_reply(all_messages, reply, downgraded_intent_reply)
                reply = downgraded_intent_reply

        if isinstance(reply, str):
            false_apology_reply = _normalize_false_apology_reply(reply, history)
            if false_apology_reply != reply:
                _replace_text_reply(new_messages, reply, false_apology_reply)
                _replace_text_reply(all_messages, reply, false_apology_reply)
                reply = false_apology_reply

        if isinstance(reply, str):
            protocol_reply = _normalize_general_confirmation_protocol_wording(reply)
            if protocol_reply != reply:
                _replace_text_reply(new_messages, reply, protocol_reply)
                _replace_text_reply(all_messages, reply, protocol_reply)
                reply = protocol_reply

        if isinstance(reply, str):
            user_facing_reply = _normalize_user_facing_terms(reply)
            if user_facing_reply != reply:
                _replace_text_reply(new_messages, reply, user_facing_reply)
                _replace_text_reply(all_messages, reply, user_facing_reply)
                reply = user_facing_reply

        latest_turn_readonly = _latest_turn_looks_readonly(tool_context_messages)
        has_pending_intent_context = (intent_preview_used and not intent_preview_downgraded) or (
            active_pending_kind == "intent_change"
            and not latest_turn_readonly
            and not plan_chain_used
            and _is_pending_intent_followup_turn(content, reply)
        )
        if isinstance(reply, str) and (_reply_is_existing_only_intent_notice(reply) or intent_non_pending):
            has_pending_intent_context = False
        semantic_intent_recovery_detected = False
        if (
            isinstance(intent_side_effect_decision, dict)
            and isinstance(reply, str)
            and not plan_chain_used
            and not intent_preview_used
            and not has_pending_intent_context
            and not readonly_prompt
            and not intent_non_pending
        ):
            semantic_intent_recovery_detected = _semantic_decision_requests_intent_preview(
                intent_side_effect_decision
            )
        semantic_intent_preview_requested = _semantic_decision_requests_intent_preview(
            intent_side_effect_decision if isinstance(intent_side_effect_decision, dict) else None
        )
        allow_unbacked_intent_recovery = _tool_calls_allow_unbacked_intent_recovery(
            tool_context_messages,
            semantic_intent_preview=semantic_intent_preview_requested,
        )
        unbacked_recorded_intent_detected = (
            isinstance(reply, str)
            and not intent_preview_used
            and not has_pending_intent_context
            and not readonly_prompt
            and _reply_claims_intent_recorded_without_pending(reply)
        )
        plan_chain_intent_recovery_detected = (
            isinstance(reply, str)
            and plan_chain_used
            and not intent_preview_used
            and not has_pending_intent_context
            and not readonly_prompt
            and not intent_non_pending
            and not active_pending_kind
            and _plan_chain_allows_intent_recovery(tool_context_messages, reply=reply)
        )
        unbacked_intent_preview_detected = (
            isinstance(reply, str)
            and not intent_preview_used
            and (not has_pending_intent_context or _reply_claims_clickable_intent_card(reply))
            and allow_unbacked_intent_recovery
            and _reply_looks_like_unbacked_intent_preview(reply)
        ) or unbacked_recorded_intent_detected or semantic_intent_recovery_detected or plan_chain_intent_recovery_detected
        active_pending_unbacked_intent_preview_detected = (
            isinstance(reply, str)
            and active_pending_kind == "intent_change"
            and not intent_preview_used
            and not plan_chain_used
            and not latest_turn_readonly
            and allow_unbacked_intent_recovery
            and _reply_looks_like_unbacked_intent_preview(reply)
        )
        if active_pending_unbacked_intent_preview_detected:
            unbacked_intent_preview_detected = True
        unbacked_intent_preview_source_reply = reply if unbacked_intent_preview_detected and isinstance(reply, str) else ""
        if isinstance(reply, str) and not intent_preview_used and not has_pending_intent_context and allow_unbacked_intent_recovery:
            unbacked_intent_reply = _normalize_unbacked_intent_preview_reply(reply)
            if unbacked_intent_reply != reply:
                _replace_text_reply(new_messages, reply, unbacked_intent_reply)
                _replace_text_reply(all_messages, reply, unbacked_intent_reply)
                reply = unbacked_intent_reply
            unbacked_recorded_reply = _normalize_unbacked_recorded_wording(reply)
            if unbacked_recorded_reply != reply:
                _replace_text_reply(new_messages, reply, unbacked_recorded_reply)
                _replace_text_reply(all_messages, reply, unbacked_recorded_reply)
                reply = unbacked_recorded_reply

        if isinstance(reply, str) and has_pending_intent_context and not intent_non_pending:
            bounded_intent_reply = _append_pending_intent_boundary(
                reply,
                has_pending_intent=has_pending_intent_context,
            )
            if bounded_intent_reply != reply:
                _replace_text_reply(new_messages, reply, bounded_intent_reply)
                _replace_text_reply(all_messages, reply, bounded_intent_reply)
                reply = bounded_intent_reply

        if isinstance(reply, str) and _reply_contains_readonly_plan_query_facts(reply):
            compact_query_reply = _compact_readonly_plan_query_reply(reply)
            if compact_query_reply and compact_query_reply != reply:
                _replace_text_reply(new_messages, reply, compact_query_reply)
                _replace_text_reply(all_messages, reply, compact_query_reply)
                reply = compact_query_reply

        workspace_refresh_targets = _current_turn_workspace_refresh_targets(
            tool_context_messages=tool_context_messages,
            new_messages=new_messages,
            all_messages=all_messages,
            content=content,
        )
        if negative_plan_ack:
            workspace_refresh_targets = []
        # Intent preview only prepares a pending preference/constraint. Do not
        # refresh the workspace until the user confirms or explicitly selects
        # the intent card; otherwise the UI looks as if an unconfirmed intent
        # has already changed candidate results.

        workspace_view_targets = _tool_calls_include_plan_view_targets(
            tool_context_messages
        )
        workspace_view_targets = _strip_workspace_targets_for_readonly_prompt(workspace_view_targets, content)
        if negative_plan_ack:
            workspace_view_targets = []
        tool_calls = _iter_tool_call_parts(tool_context_messages)
        tool_returns = _iter_tool_return_parts(tool_context_messages)
        called_tool_names = [part.tool_name for part in tool_calls]
        observed_tool_calls = _summarize_tool_calls_for_observability(tool_calls, tool_returns)
        full_agent_tool_trial = _summarize_full_agent_tool_trial(called_tool_names)
        if any(name in {"collect_plan_context_inputs", "plan_next_action", "execute_plan_action", "query_volunteer_plan"} for name in called_tool_names):
            scene = "plan"
        elif any("intent" in name for name in called_tool_names):
            scene = "intent"
        elif any(name.startswith("analyze_current_") for name in called_tool_names):
            scene = "explore"
        else:
            scene = "unknown"
        action_family = _select_conversation_action_family(tool_returns)
        recovered_pending_intent_card: WSResponse | None = None
        plan_confirmation_card: WSResponse | None = None
        plan_confirmation_candidate = _extract_plan_confirmation_candidate(tool_context_messages)
        plan_action_recovery_route: dict[str, Any] | None = None
        plan_card_includes_intent_update = False
        pending_fix_proposal_card: WSResponse | None = None
        profile_change_replan_result = _latest_profile_change_replan_result(tool_context_messages)
        if (
            profile_change_replan_result is not None
            and isinstance(reply, str)
            and _profile_change_replan_has_explicit_change_value(content)
        ):
            profile_change_reply = _build_profile_change_replan_reply(
                content,
                request_context=request_context,
            )
            _replace_text_reply(new_messages, reply, profile_change_reply)
            _replace_text_reply(all_messages, reply, profile_change_reply)
            reply = profile_change_reply
        elif (
            plan_confirmation_candidate is None
            and isinstance(reply, str)
            and _latest_empty_status_overview_result(tool_context_messages) is not None
        ):
            try:
                profile_change_decision = await classify_plan_semantic_action(
                    content,
                    request_context=request_context,
                    recent_plan_context=_latest_plan_semantic_route_context(tool_context_messages),
                )
            except Exception:
                logger.warning(
                    "Profile change replan post-query classification failed: session_id=%s",
                    session_id,
                    exc_info=True,
                )
                profile_change_decision = None
            if (
                profile_change_decision is not None
                and float(getattr(profile_change_decision, "confidence", 0.0) or 0.0)
                >= _SEMANTIC_PLAN_ACTION_CONFIDENCE_THRESHOLD
                and _requests_profile_change_replan(profile_change_decision)
                and _profile_change_replan_has_explicit_change_value(content)
            ):
                profile_change_reply = _build_profile_change_replan_reply(
                    content,
                    request_context=request_context,
                )
                _replace_text_reply(new_messages, reply, profile_change_reply)
                _replace_text_reply(all_messages, reply, profile_change_reply)
                reply = profile_change_reply
        if unbacked_intent_preview_detected and isinstance(reply, str):
            if not intent_preview_downgraded:
                recovered_pending_intent_card = await _recover_unbacked_intent_confirmation(
                    session_id,
                    request_context,
                    reply=unbacked_intent_preview_source_reply,
                    force=(
                        unbacked_recorded_intent_detected
                        or semantic_intent_recovery_detected
                        or plan_chain_intent_recovery_detected
                        or active_pending_unbacked_intent_preview_detected
                    ),
                )
            if recovered_pending_intent_card is not None:
                recovered_pending_intent_reply = _intent_card_primary_reply_from_card(recovered_pending_intent_card)
                if recovered_pending_intent_reply:
                    _replace_text_reply(new_messages, reply, recovered_pending_intent_reply)
                    _replace_text_reply(all_messages, reply, recovered_pending_intent_reply)
                    reply = recovered_pending_intent_reply
        if (
            recovered_pending_intent_card is None
            and plan_confirmation_candidate is None
            and isinstance(reply, str)
            and not plan_chain_used
            and not intent_preview_used
            and not intent_preview_downgraded
            and not readonly_prompt
            and resolve_pending_confirmation(request_context) is None
        ):
            confirmable_interest_payload = _extract_confirmable_intent_payload_from_interest_tool(
                tool_context_messages
            )
            if confirmable_interest_payload is not None:
                recovered_pending_intent_card = await _create_pending_intent_confirmation_from_preview_payload(
                    session_id,
                    confirmable_interest_payload,
                )
                if recovered_pending_intent_card is not None:
                    recovered_pending_intent_reply = _pending_confirmation_primary_reply_from_card(
                        recovered_pending_intent_card
                    )
                    if recovered_pending_intent_reply:
                        _replace_text_reply(new_messages, reply, recovered_pending_intent_reply)
                        _replace_text_reply(all_messages, reply, recovered_pending_intent_reply)
                        reply = recovered_pending_intent_reply
        if (
            recovered_pending_intent_card is None
            and plan_confirmation_candidate is None
            and isinstance(reply, str)
            and not plan_chain_used
            and not intent_preview_used
            and not intent_preview_downgraded
            and not readonly_prompt
            and resolve_pending_confirmation(request_context) is None
        ):
            recovered_pending_intent_card = await _recover_confirmable_intent_from_readonly_tool_misroute(
                session_id,
                request_context,
                reply=reply,
                tool_context_messages=tool_context_messages,
            )
            if recovered_pending_intent_card is not None:
                recovered_pending_intent_reply = _intent_card_primary_reply_from_card(
                    recovered_pending_intent_card
                )
                if recovered_pending_intent_reply:
                        _replace_text_reply(new_messages, reply, recovered_pending_intent_reply)
                        _replace_text_reply(all_messages, reply, recovered_pending_intent_reply)
                        reply = recovered_pending_intent_reply
        if (
            recovered_pending_intent_card is None
            and plan_confirmation_candidate is None
            and isinstance(reply, str)
            and not plan_chain_used
            and not intent_preview_used
            and not intent_preview_downgraded
            and not readonly_prompt
            and not _reply_looks_like_plan_action_recovery_boundary(reply)
            and resolve_pending_confirmation(request_context) is None
        ):
            recovered_pending_intent_card = await _recover_confirmable_intent_from_no_tool_turn(
                session_id,
                request_context,
                reply=reply,
                tool_context_messages=tool_context_messages,
            )
            if recovered_pending_intent_card is not None:
                recovered_pending_intent_reply = _intent_card_primary_reply_from_card(
                    recovered_pending_intent_card
                )
                if recovered_pending_intent_reply:
                    _replace_text_reply(new_messages, reply, recovered_pending_intent_reply)
                    _replace_text_reply(all_messages, reply, recovered_pending_intent_reply)
                    reply = recovered_pending_intent_reply
        composite_goal_preview = _latest_composite_goal_plan_preview(tool_context_messages)
        composite_goal_clarification_reply = _composite_goal_clarification_reply(composite_goal_preview)
        if composite_goal_clarification_reply:
            plan_confirmation_candidate = None
            if isinstance(reply, str):
                clean_clarification_reply = _sanitize_reply_for_user(
                    composite_goal_clarification_reply
                )
                _replace_text_reply(new_messages, reply, clean_clarification_reply)
                _replace_text_reply(all_messages, reply, clean_clarification_reply)
                reply = clean_clarification_reply
        if (
            recovered_pending_intent_card is None
            and plan_confirmation_candidate is None
            and pending_fix_proposal_card is None
            and isinstance(reply, str)
            and not intent_preview_used
            and not intent_preview_downgraded
            and not readonly_prompt
            and resolve_pending_confirmation(request_context) is None
            and _reply_looks_like_unbacked_plan_confirmation(reply)
        ):
            recovered_pending_intent_card = await _recover_unbacked_intent_confirmation(
                session_id,
                request_context,
                reply=reply,
                force=True,
            )
            if recovered_pending_intent_card is not None:
                recovered_pending_intent_reply = _intent_card_primary_reply_from_card(
                    recovered_pending_intent_card
                )
                if recovered_pending_intent_reply:
                    _replace_text_reply(new_messages, reply, recovered_pending_intent_reply)
                    _replace_text_reply(all_messages, reply, recovered_pending_intent_reply)
                    reply = recovered_pending_intent_reply
        if (
            recovered_pending_intent_card is None
            and plan_confirmation_candidate is None
            and isinstance(reply, str)
        ):
            guarded_reply = _guard_unbacked_plan_confirmation_reply(reply)
            if guarded_reply != reply:
                if intent_interest_stage_result and not plan_chain_used:
                    stripped_reply = _remove_unbacked_plan_confirmation_copy(reply).strip()
                    if stripped_reply and not _reply_has_plan_confirmation_request(stripped_reply):
                        guarded_reply = stripped_reply
                        compact_guarded = _compact_plan_reply_text(guarded_reply)
                        if "不会改动当前方案" not in compact_guarded and "不会直接改" not in compact_guarded:
                            guarded_reply = f"{guarded_reply.rstrip()}\n\n{_READONLY_ANALYSIS_NO_PLAN_PREVIEW_REPLY}"
                    else:
                        explore_reply = _latest_readonly_explore_reply(tool_context_messages)
                        if explore_reply:
                            compact_explore = _compact_plan_reply_text(explore_reply)
                            guarded_reply = explore_reply
                            if "不会改动当前方案" not in compact_explore and "不会直接改" not in compact_explore:
                                guarded_reply = f"{guarded_reply.rstrip()}\n\n{_READONLY_ANALYSIS_NO_PLAN_PREVIEW_REPLY}"
                        else:
                            guarded_reply = _READONLY_ANALYSIS_NO_PLAN_PREVIEW_REPLY
                else:
                    readonly_plan_result = _latest_readonly_plan_execution_result(tool_context_messages)
                    if readonly_plan_result is None:
                        readonly_plan_result = _latest_fix_proposal_preview_result(tool_context_messages)
                    if readonly_plan_result is not None:
                        guarded_reply = _build_plan_timeout_fallback_reply(
                            readonly_plan_result,
                            user_prompt=content,
                        ) or guarded_reply
                    else:
                        readonly_tool_reply = _latest_readonly_tool_reply(tool_context_messages)
                        if readonly_tool_reply:
                            stripped_reply = _remove_unbacked_plan_confirmation_copy(reply).strip()
                            if (
                                stripped_reply
                                and not _reply_has_plan_confirmation_request(stripped_reply)
                                and _reply_contains_readonly_plan_query_facts(stripped_reply)
                            ):
                                guarded_reply = stripped_reply
                            elif not stripped_reply:
                                guarded_reply = readonly_tool_reply
                            else:
                                guarded_reply = stripped_reply
                _replace_text_reply(new_messages, reply, guarded_reply)
                _replace_text_reply(all_messages, reply, guarded_reply)
                reply = guarded_reply
        if (
            plan_confirmation_candidate is None
            and isinstance(reply, str)
            and active_pending_kind in {"intent_change", "plan_mutation"}
            and _reply_looks_like_plan_action_recovery_boundary(reply)
            and not list(_iter_tool_call_parts(tool_context_messages))
            and isinstance(backend_pending_state, dict)
            and backend_pending_state
        ):
            pending_context_reply = _build_pending_readonly_impact_reply(backend_pending_state)
            if active_pending_kind == "intent_change":
                pending_context_reply = (
                    pending_context_reply.rstrip()
                    + "\n\n如果这就是你想采用的方向，请先点“采纳”；采纳后我再按这条参考检查或调整当前方案。"
                )
            _replace_text_reply(new_messages, reply, pending_context_reply)
            _replace_text_reply(all_messages, reply, pending_context_reply)
            reply = pending_context_reply
        if plan_confirmation_candidate is None and isinstance(reply, str):
            recovered_plan_action = await self._maybe_recover_unbacked_plan_action(
                session_id=session_id,
                content=content,
                reply=reply,
                tool_context_messages=tool_context_messages,
                request_context=request_context,
            )
            if recovered_plan_action is not None:
                reply = recovered_plan_action.reply
                new_messages = recovered_plan_action.messages
                all_messages = list(runtime_history.model_history or []) + list(new_messages)
                tool_context_messages = _select_current_tool_context_messages(
                    new_messages,
                    all_messages,
                    runtime_history,
                )
                plan_chain_used = _tool_calls_include_plan_chain(tool_context_messages)
                intent_preview_used_current_turn = _tool_calls_include_intent_preview(tool_context_messages)
                intent_preview_used = intent_preview_used_current_turn
                intent_non_pending = _tool_returns_intent_non_pending(tool_context_messages)
                latest_turn_readonly = _latest_turn_looks_readonly(tool_context_messages)
                has_pending_intent_context = False
                workspace_refresh_targets = _current_turn_workspace_refresh_targets(
                    tool_context_messages=tool_context_messages,
                    new_messages=new_messages,
                    all_messages=all_messages,
                    content=content,
                )
                workspace_view_targets = _tool_calls_include_plan_view_targets(tool_context_messages)
                workspace_view_targets = _strip_workspace_targets_for_readonly_prompt(workspace_view_targets, content)
                if negative_plan_ack:
                    workspace_refresh_targets = []
                    workspace_view_targets = []
                tool_calls = _iter_tool_call_parts(tool_context_messages)
                tool_returns = _iter_tool_return_parts(tool_context_messages)
                called_tool_names = [part.tool_name for part in tool_calls]
                observed_tool_calls = _summarize_tool_calls_for_observability(tool_calls, tool_returns)
                full_agent_tool_trial = _summarize_full_agent_tool_trial(called_tool_names)
                scene = "plan"
                action_family = _select_conversation_action_family(tool_returns)
                plan_confirmation_candidate = _extract_plan_confirmation_candidate(tool_context_messages)
                plan_action_recovery_route = recovered_plan_action.route_decision
        composite_goal_card: WSResponse | None = None
        if (
            plan_action_recovery_route is None
            and plan_confirmation_candidate is None
            and recovered_pending_intent_card is None
            and pending_fix_proposal_card is None
            and isinstance(reply, str)
            and not composite_goal_clarification_reply
            and not intent_preview_used_current_turn
        ):
            composite_goal_card = None
            composite_goal_card = await self._maybe_recover_unbacked_composite_goal_without_tools(
                session_id=session_id,
                content=content,
                reply=reply,
                tool_context_messages=tool_context_messages,
                request_context=request_context,
            )
            if composite_goal_card is not None:
                composite_goal_card_kind = _pending_card_kind(composite_goal_card)
                if composite_goal_card_kind == "readonly_notice":
                    card_payload = _parse_tool_return_json(
                        getattr(composite_goal_card, "content", "") or ""
                    )
                    readonly_reply = str((card_payload or {}).get("reply") or "").strip() if isinstance(card_payload, dict) else ""
                    if readonly_reply:
                        _replace_text_reply(new_messages, reply, readonly_reply)
                        _replace_text_reply(all_messages, reply, readonly_reply)
                        reply = readonly_reply
                elif composite_goal_card_kind == "intent_change":
                    recovered_pending_intent_card = composite_goal_card
                    recovered_pending_intent_reply = _intent_card_primary_reply_from_card(composite_goal_card)
                    if recovered_pending_intent_reply:
                        _replace_text_reply(new_messages, reply, recovered_pending_intent_reply)
                        _replace_text_reply(all_messages, reply, recovered_pending_intent_reply)
                        reply = recovered_pending_intent_reply
                else:
                    pending_fix_proposal_card = composite_goal_card
                    card_payload = _parse_tool_return_json(
                        getattr(composite_goal_card, "content", "") or ""
                    )
                    card_summary = (
                        str((card_payload or {}).get("summary") or "").strip()
                        if isinstance(card_payload, dict)
                        else ""
                    )
                    primary_goal_reply = "已按你的要求列出调整预览。"
                    if card_summary:
                        primary_goal_reply = f"已按你的要求列出调整预览：{card_summary}。"
                    primary_goal_reply += "确认前不会改动当前方案；确认后会同步更新后续报考参考，并按预览调整当前方案。"
                    primary_goal_reply = _sanitize_reply_for_user(primary_goal_reply)
                    _replace_text_reply(new_messages, reply, primary_goal_reply)
                    _replace_text_reply(all_messages, reply, primary_goal_reply)
                    reply = primary_goal_reply
                plan_action_recovery_route = {
                    "source": "composite_goal_recovery_without_tools",
                    "matched": True,
                    "confidence": "semantic",
                    "route": "user_goal_proposal",
                }
        if (
            composite_goal_card is None
            and recovered_pending_intent_card is None
            and pending_fix_proposal_card is None
            and plan_action_recovery_route is None
            and plan_confirmation_candidate is None
            and isinstance(reply, str)
            and not intent_preview_used_current_turn
            and not composite_goal_clarification_reply
        ):
            recovered_pending_intent_card = await _recover_confirmable_intent_from_no_tool_turn(
                session_id,
                request_context,
                reply=reply,
                tool_context_messages=tool_context_messages,
            )
            if recovered_pending_intent_card is not None:
                recovered_pending_intent_reply = _intent_card_primary_reply_from_card(
                    recovered_pending_intent_card
                )
                if recovered_pending_intent_reply:
                    _replace_text_reply(new_messages, reply, recovered_pending_intent_reply)
                    _replace_text_reply(all_messages, reply, recovered_pending_intent_reply)
                    reply = recovered_pending_intent_reply
        if (
            plan_action_recovery_route is None
            and plan_confirmation_candidate is None
            and pending_fix_proposal_card is None
            and isinstance(reply, str)
            and intent_preview_used_current_turn
            and not composite_goal_clarification_reply
        ):
            existing_intent_goal_card = await self._maybe_recover_existing_intent_composite_goal(
                session_id=session_id,
                content=content,
                request_context=request_context,
                tool_context_messages=tool_context_messages,
            )
            if existing_intent_goal_card is not None:
                pending_fix_proposal_card = existing_intent_goal_card
                plan_action_recovery_route = {
                    "source": "composite_goal_recovery_from_existing_intent",
                    "matched": True,
                    "confidence": "semantic",
                    "route": "user_goal_proposal",
                }
                card_payload = _parse_tool_return_json(
                    getattr(existing_intent_goal_card, "content", "") or ""
                )
                card_summary = (
                    str((card_payload or {}).get("summary") or "").strip()
                    if isinstance(card_payload, dict)
                    else ""
                )
                primary_goal_reply = "已按你的要求列出调整预览。"
                if card_summary:
                    primary_goal_reply = f"已按你的要求列出调整预览：{card_summary}。"
                primary_goal_reply += "确认前不会改动当前方案；确认后会同步更新后续报考参考，并按预览调整当前方案。"
                primary_goal_reply = _sanitize_reply_for_user(primary_goal_reply)
                _replace_text_reply(new_messages, reply, primary_goal_reply)
                _replace_text_reply(all_messages, reply, primary_goal_reply)
                reply = primary_goal_reply
        if (
            plan_action_recovery_route is None
            and plan_confirmation_candidate is None
            and pending_fix_proposal_card is None
            and isinstance(reply, str)
            and intent_preview_used_current_turn
            and _latest_existing_only_intent_payload(tool_context_messages) is not None
            and not _has_plan_semantic_route_context(
                getattr(request_context, "planning_summary", None),
                _latest_plan_semantic_route_context(getattr(request_context, "chat_history", None)),
            )
        ):
            no_plan_reply = _build_existing_only_no_plan_reply(
                _latest_existing_only_intent_payload(tool_context_messages)
            )
            _replace_text_reply(new_messages, reply, no_plan_reply)
            _replace_text_reply(all_messages, reply, no_plan_reply)
            reply = no_plan_reply
        if (
            plan_action_recovery_route is None
            and plan_confirmation_candidate is None
            and pending_fix_proposal_card is None
            and isinstance(reply, str)
            and not composite_goal_clarification_reply
        ):
            allow_empty_intent_composite_recovery = (
                intent_non_pending
                and not plan_chain_used
                and not has_pending_intent_context
                and not readonly_prompt
                and not active_pending_kind
            )
            composite_goal_card = await self._maybe_recover_unbacked_composite_goal(
                session_id=session_id,
                content=content,
                reply=reply,
                tool_context_messages=tool_context_messages,
                request_context=request_context,
                allow_empty_intent_preview=allow_empty_intent_composite_recovery,
            )
            if composite_goal_card is not None:
                composite_goal_card_kind = _pending_card_kind(composite_goal_card)
                if composite_goal_card_kind == "readonly_notice":
                    card_payload = _parse_tool_return_json(
                        getattr(composite_goal_card, "content", "") or ""
                    )
                    readonly_reply = str((card_payload or {}).get("reply") or "").strip() if isinstance(card_payload, dict) else ""
                    if readonly_reply:
                        _replace_text_reply(new_messages, reply, readonly_reply)
                        _replace_text_reply(all_messages, reply, readonly_reply)
                        reply = readonly_reply
                elif composite_goal_card_kind == "intent_change":
                    recovered_pending_intent_card = composite_goal_card
                else:
                    pending_fix_proposal_card = composite_goal_card
                plan_action_recovery_route = {
                    "source": "composite_goal_recovery_without_plan_attempt",
                    "matched": True,
                    "confidence": "semantic",
                    "route": "user_goal_proposal",
                }
                if composite_goal_card_kind == "readonly_notice":
                    pass
                elif composite_goal_card_kind == "intent_change":
                    recovered_pending_intent_reply = _intent_card_primary_reply_from_card(composite_goal_card)
                    if recovered_pending_intent_reply:
                        _replace_text_reply(new_messages, reply, recovered_pending_intent_reply)
                        _replace_text_reply(all_messages, reply, recovered_pending_intent_reply)
                        reply = recovered_pending_intent_reply
                else:
                    card_payload = _parse_tool_return_json(
                        getattr(composite_goal_card, "content", "") or ""
                    )
                    card_summary = (
                        str((card_payload or {}).get("summary") or "").strip()
                        if isinstance(card_payload, dict)
                        else ""
                    )
                    primary_goal_reply = "已按你的要求列出调整预览。"
                    if card_summary:
                        primary_goal_reply = f"已按你的要求列出调整预览：{card_summary}。"
                    primary_goal_reply += "确认前不会改动当前方案；确认后会同步更新后续报考参考，并按预览调整当前方案。"
                    primary_goal_reply = _sanitize_reply_for_user(primary_goal_reply)
                    _replace_text_reply(new_messages, reply, primary_goal_reply)
                    _replace_text_reply(all_messages, reply, primary_goal_reply)
                    reply = primary_goal_reply
        if (
            plan_action_recovery_route is None
            and plan_confirmation_candidate is None
            and intent_preview_used_current_turn
        ):
            recovered_plan_action = await self._maybe_recover_plan_action_from_intent_preview(
                session_id=session_id,
                content=content,
                request_context=request_context,
                tool_context_messages=tool_context_messages,
            )
            if recovered_plan_action is not None:
                reply = recovered_plan_action.reply
                new_messages = recovered_plan_action.messages
                all_messages = list(runtime_history.model_history or []) + list(new_messages)
                tool_context_messages = _select_current_tool_context_messages(
                    new_messages,
                    all_messages,
                    runtime_history,
                )
                plan_chain_used = _tool_calls_include_plan_chain(tool_context_messages)
                intent_preview_used_current_turn = _tool_calls_include_intent_preview(tool_context_messages)
                intent_preview_used = intent_preview_used_current_turn
                intent_non_pending = _tool_returns_intent_non_pending(tool_context_messages)
                latest_turn_readonly = _latest_turn_looks_readonly(tool_context_messages)
                has_pending_intent_context = False
                workspace_refresh_targets = _current_turn_workspace_refresh_targets(
                    tool_context_messages=tool_context_messages,
                    new_messages=new_messages,
                    all_messages=all_messages,
                    content=content,
                )
                workspace_view_targets = _tool_calls_include_plan_view_targets(tool_context_messages)
                workspace_view_targets = _strip_workspace_targets_for_readonly_prompt(workspace_view_targets, content)
                if negative_plan_ack:
                    workspace_refresh_targets = []
                    workspace_view_targets = []
                tool_calls = _iter_tool_call_parts(tool_context_messages)
                tool_returns = _iter_tool_return_parts(tool_context_messages)
                called_tool_names = [part.tool_name for part in tool_calls]
                observed_tool_calls = _summarize_tool_calls_for_observability(tool_calls, tool_returns)
                full_agent_tool_trial = _summarize_full_agent_tool_trial(called_tool_names)
                scene = "plan"
                action_family = _select_conversation_action_family(tool_returns)
                plan_confirmation_candidate = _extract_plan_confirmation_candidate(tool_context_messages)
                plan_action_recovery_route = recovered_plan_action.route_decision
        if (
            plan_action_recovery_route is None
            and plan_confirmation_candidate is None
        ):
            recovered_plan_action = await self._maybe_complete_unexecuted_fix_preview_plan_next(
                session_id=session_id,
                content=content,
                request_context=request_context,
                tool_context_messages=tool_context_messages,
            )
            if recovered_plan_action is not None:
                reply = recovered_plan_action.reply
                new_messages = recovered_plan_action.messages
                all_messages = list(runtime_history.model_history or []) + list(new_messages)
                tool_context_messages = _select_current_tool_context_messages(
                    new_messages,
                    all_messages,
                    runtime_history,
                )
                plan_chain_used = _tool_calls_include_plan_chain(tool_context_messages)
                intent_preview_used_current_turn = _tool_calls_include_intent_preview(tool_context_messages)
                intent_preview_used = intent_preview_used_current_turn
                intent_non_pending = _tool_returns_intent_non_pending(tool_context_messages)
                latest_turn_readonly = _latest_turn_looks_readonly(tool_context_messages)
                has_pending_intent_context = False
                workspace_refresh_targets = _current_turn_workspace_refresh_targets(
                    tool_context_messages=tool_context_messages,
                    new_messages=new_messages,
                    all_messages=all_messages,
                    content=content,
                )
                workspace_view_targets = _tool_calls_include_plan_view_targets(tool_context_messages)
                workspace_view_targets = _strip_workspace_targets_for_readonly_prompt(workspace_view_targets, content)
                if negative_plan_ack:
                    workspace_refresh_targets = []
                    workspace_view_targets = []
                tool_calls = _iter_tool_call_parts(tool_context_messages)
                tool_returns = _iter_tool_return_parts(tool_context_messages)
                called_tool_names = [part.tool_name for part in tool_calls]
                observed_tool_calls = _summarize_tool_calls_for_observability(tool_calls, tool_returns)
                full_agent_tool_trial = _summarize_full_agent_tool_trial(called_tool_names)
                scene = "plan"
                action_family = _select_conversation_action_family(tool_returns)
                plan_confirmation_candidate = _extract_plan_confirmation_candidate(tool_context_messages)
                plan_action_recovery_route = recovered_plan_action.route_decision
        if (
            plan_action_recovery_route is None
            and plan_confirmation_candidate is None
        ):
            recovered_plan_action = await self._maybe_complete_unexecuted_mutating_plan_next_preview(
                session_id=session_id,
                content=content,
                request_context=request_context,
                tool_context_messages=tool_context_messages,
            )
            if recovered_plan_action is not None:
                reply = recovered_plan_action.reply
                new_messages = recovered_plan_action.messages
                all_messages = list(runtime_history.model_history or []) + list(new_messages)
                tool_context_messages = _select_current_tool_context_messages(
                    new_messages,
                    all_messages,
                    runtime_history,
                )
                plan_chain_used = _tool_calls_include_plan_chain(tool_context_messages)
                intent_preview_used_current_turn = _tool_calls_include_intent_preview(tool_context_messages)
                intent_preview_used = intent_preview_used_current_turn
                intent_non_pending = _tool_returns_intent_non_pending(tool_context_messages)
                latest_turn_readonly = _latest_turn_looks_readonly(tool_context_messages)
                has_pending_intent_context = False
                workspace_refresh_targets = _current_turn_workspace_refresh_targets(
                    tool_context_messages=tool_context_messages,
                    new_messages=new_messages,
                    all_messages=all_messages,
                    content=content,
                )
                workspace_view_targets = _tool_calls_include_plan_view_targets(tool_context_messages)
                workspace_view_targets = _strip_workspace_targets_for_readonly_prompt(workspace_view_targets, content)
                if negative_plan_ack:
                    workspace_refresh_targets = []
                    workspace_view_targets = []
                tool_calls = _iter_tool_call_parts(tool_context_messages)
                tool_returns = _iter_tool_return_parts(tool_context_messages)
                called_tool_names = [part.tool_name for part in tool_calls]
                observed_tool_calls = _summarize_tool_calls_for_observability(tool_calls, tool_returns)
                full_agent_tool_trial = _summarize_full_agent_tool_trial(called_tool_names)
                scene = "plan"
                action_family = _select_conversation_action_family(tool_returns)
                plan_confirmation_candidate = _extract_plan_confirmation_candidate(tool_context_messages)
                plan_action_recovery_route = recovered_plan_action.route_decision
        if (
            plan_action_recovery_route is None
            and plan_confirmation_candidate is None
        ):
            recovered_plan_action = await self._maybe_recover_fix_preview_after_review(
                session_id=session_id,
                content=content,
                request_context=request_context,
                tool_context_messages=tool_context_messages,
            )
            if recovered_plan_action is not None:
                reply = recovered_plan_action.reply
                new_messages = recovered_plan_action.messages
                all_messages = list(runtime_history.model_history or []) + list(new_messages)
                tool_context_messages = _select_current_tool_context_messages(
                    new_messages,
                    all_messages,
                    runtime_history,
                )
                plan_chain_used = _tool_calls_include_plan_chain(tool_context_messages)
                intent_preview_used_current_turn = _tool_calls_include_intent_preview(tool_context_messages)
                intent_preview_used = intent_preview_used_current_turn
                intent_non_pending = _tool_returns_intent_non_pending(tool_context_messages)
                latest_turn_readonly = _latest_turn_looks_readonly(tool_context_messages)
                has_pending_intent_context = False
                workspace_refresh_targets = _current_turn_workspace_refresh_targets(
                    tool_context_messages=tool_context_messages,
                    new_messages=new_messages,
                    all_messages=all_messages,
                    content=content,
                )
                workspace_view_targets = _tool_calls_include_plan_view_targets(tool_context_messages)
                workspace_view_targets = _strip_workspace_targets_for_readonly_prompt(workspace_view_targets, content)
                if negative_plan_ack:
                    workspace_refresh_targets = []
                    workspace_view_targets = []
                tool_calls = _iter_tool_call_parts(tool_context_messages)
                tool_returns = _iter_tool_return_parts(tool_context_messages)
                called_tool_names = [part.tool_name for part in tool_calls]
                observed_tool_calls = _summarize_tool_calls_for_observability(tool_calls, tool_returns)
                full_agent_tool_trial = _summarize_full_agent_tool_trial(called_tool_names)
                scene = "plan"
                action_family = _select_conversation_action_family(tool_returns)
                plan_confirmation_candidate = _extract_plan_confirmation_candidate(tool_context_messages)
                plan_action_recovery_route = recovered_plan_action.route_decision
        if plan_confirmation_candidate is None and not composite_goal_clarification_reply:
            composite_goal_card = await self._maybe_recover_composite_goal_after_plan_attempt(
                session_id=session_id,
                content=content,
                request_context=request_context,
                tool_context_messages=tool_context_messages,
                allow_actionable_fix_preview=True,
                allow_intent_preview_mixed_path=True,
            )
            if composite_goal_card is not None:
                composite_goal_card_kind = _pending_card_kind(composite_goal_card)
                if composite_goal_card_kind == "readonly_notice":
                    card_payload = _parse_tool_return_json(
                        getattr(composite_goal_card, "content", "") or ""
                    )
                    readonly_reply = str((card_payload or {}).get("reply") or "").strip() if isinstance(card_payload, dict) else ""
                    if readonly_reply and isinstance(reply, str):
                        _replace_text_reply(new_messages, reply, readonly_reply)
                        _replace_text_reply(all_messages, reply, readonly_reply)
                        reply = readonly_reply
                elif composite_goal_card_kind == "intent_change":
                    recovered_pending_intent_card = composite_goal_card
                else:
                    pending_fix_proposal_card = composite_goal_card
                plan_action_recovery_route = {
                    "source": "composite_goal_recovery_after_plan_attempt",
                    "matched": True,
                    "confidence": "semantic",
                    "route": "user_goal_proposal",
                }
                if composite_goal_card_kind == "readonly_notice":
                    pass
                elif isinstance(reply, str) and composite_goal_card_kind == "intent_change":
                    _replace_text_reply(new_messages, reply, "")
                    _replace_text_reply(all_messages, reply, "")
                    reply = ""
                elif isinstance(reply, str):
                    card_payload = _parse_tool_return_json(
                        getattr(composite_goal_card, "content", "") or ""
                    )
                    card_summary = (
                        str((card_payload or {}).get("summary") or "").strip()
                        if isinstance(card_payload, dict)
                        else ""
                    )
                    primary_goal_reply = "已按你的要求列出调整预览。"
                    if card_summary:
                        primary_goal_reply = f"已按你的要求列出调整预览：{card_summary}。"
                    primary_goal_reply += "确认前不会改动当前方案；确认后会同步更新后续报考参考，并按预览调整当前方案。"
                    primary_goal_reply = _sanitize_reply_for_user(primary_goal_reply)
                    _replace_text_reply(new_messages, reply, primary_goal_reply)
                    _replace_text_reply(all_messages, reply, primary_goal_reply)
                    reply = primary_goal_reply
            if pending_fix_proposal_card is None and recovered_pending_intent_card is None:
                latest_plan_result = _latest_fix_proposal_confirmation_source(tool_context_messages)
                if latest_plan_result is None and _tool_calls_include_generate_fix_proposals(tool_context_messages):
                    fetched_fix_source = await _fetch_fix_proposal_confirmation_source(
                        session_id,
                        user_goal=content,
                    )
                    if isinstance(fetched_fix_source, dict) and await _user_requested_fix_proposal_preview(
                        content=content,
                        request_context=request_context,
                        latest_plan_result=fetched_fix_source,
                    ):
                        latest_plan_result = fetched_fix_source
                if latest_plan_result is None:
                    preview_result = _latest_fix_proposal_preview_result(tool_context_messages)
                    if isinstance(preview_result, dict):
                        latest_plan_result = preview_result
                if isinstance(latest_plan_result, dict):
                    facts = latest_plan_result.get("facts") if isinstance(latest_plan_result.get("facts"), dict) else {}
                    fix_facts = facts.get("fix_proposals") if isinstance(facts.get("fix_proposals"), dict) else {}
                    selected_proposal_id = _selected_fix_proposal_id(latest_plan_result, facts)
                    target_strategies: list[str] = []
                    target_issue_codes: list[str] = []
                    target_scope_explicit = False
                    if not selected_proposal_id:
                        target_strategies, target_issue_codes, target_scope_explicit = await _infer_fix_proposal_target_scope(
                            content=content,
                            request_context=request_context,
                            latest_plan_result=latest_plan_result,
                        )
                    if selected_proposal_id:
                        ready_proposal = _select_ready_fix_proposal(
                            facts,
                            selected_proposal_id=selected_proposal_id,
                        )
                    elif target_scope_explicit and not target_strategies and not target_issue_codes:
                        ready_proposal = None
                        latest_plan_result["target_match_empty"] = True
                    elif (target_strategies or target_issue_codes) and not _filter_ready_fix_proposals_by_target_scope(
                        _ready_fix_proposals(facts),
                        _normalized_fix_proposal_target_strategies(target_strategies),
                        _normalized_fix_proposal_target_issue_codes(target_issue_codes),
                    ):
                        ready_proposal = None
                        latest_plan_result["target_match_empty"] = True
                    else:
                        ready_proposal = await _select_ready_fix_proposal_for_user_goal(
                            facts,
                            content=content,
                            reply=reply,
                            request_context=request_context,
                            target_strategies=target_strategies,
                            target_issue_codes=target_issue_codes,
                        )
                        if ready_proposal is None and target_scope_explicit:
                            latest_plan_result["target_match_empty"] = True
                    if ready_proposal is not None:
                        latest_plan_result["selected_proposal_id"] = str(
                            ready_proposal.get("proposal_id") or ready_proposal.get("proposalId") or ""
                        ).strip()
                    source_version_guard = _as_int(
                        fix_facts.get("source_version_guard")
                        or latest_plan_result.get("source_backend_version")
                        or latest_plan_result.get("planning_version")
                    )
                    if ready_proposal is not None and source_version_guard > 0:
                        pending_fix_proposal_card = await _create_pending_fix_proposal_confirmation_response(
                            session_id,
                            ready_proposal,
                            source_version_guard=source_version_guard,
                        )
                        if isinstance(reply, str):
                            primary_fix_reply = _fix_proposal_pending_primary_reply(ready_proposal)
                            if primary_fix_reply:
                                _replace_text_reply(new_messages, reply, primary_fix_reply)
                                _replace_text_reply(all_messages, reply, primary_fix_reply)
                                reply = primary_fix_reply
                    elif (
                        pending_fix_proposal_card is None
                        and latest_plan_result.get("target_match_empty")
                    ):
                        recovered_atomic_action = await self._maybe_recover_atomic_preview_from_unmatched_fix_proposal(
                            session_id=session_id,
                            content=content,
                            request_context=request_context,
                            latest_plan_result=latest_plan_result,
                        )
                        if recovered_atomic_action is not None:
                            reply = recovered_atomic_action.reply
                            new_messages = recovered_atomic_action.messages
                            all_messages = list(runtime_history.model_history or []) + list(new_messages)
                            tool_context_messages = _select_current_tool_context_messages(
                                new_messages,
                                all_messages,
                                runtime_history,
                            )
                            plan_chain_used = _tool_calls_include_plan_chain(tool_context_messages)
                            intent_preview_used_current_turn = _tool_calls_include_intent_preview(tool_context_messages)
                            intent_preview_used = intent_preview_used_current_turn
                            intent_non_pending = _tool_returns_intent_non_pending(tool_context_messages)
                            latest_turn_readonly = _latest_turn_looks_readonly(tool_context_messages)
                            has_pending_intent_context = False
                            workspace_refresh_targets = _current_turn_workspace_refresh_targets(
                                tool_context_messages=tool_context_messages,
                                new_messages=new_messages,
                                all_messages=all_messages,
                                content=content,
                            )
                            workspace_view_targets = _tool_calls_include_plan_view_targets(tool_context_messages)
                            workspace_view_targets = _strip_workspace_targets_for_readonly_prompt(workspace_view_targets, content)
                            tool_calls = _iter_tool_call_parts(tool_context_messages)
                            tool_returns = _iter_tool_return_parts(tool_context_messages)
                            called_tool_names = [part.tool_name for part in tool_calls]
                            observed_tool_calls = _summarize_tool_calls_for_observability(tool_calls, tool_returns)
                            full_agent_tool_trial = _summarize_full_agent_tool_trial(called_tool_names)
                            scene = "plan"
                            action_family = _select_conversation_action_family(tool_returns)
                            plan_confirmation_candidate = _extract_plan_confirmation_candidate(tool_context_messages)
                            plan_action_recovery_route = recovered_atomic_action.route_decision
                    elif pending_fix_proposal_card is None:
                        clarification_reply = _composite_goal_clarification_reply(latest_plan_result)
                        if clarification_reply:
                            reply = _sanitize_reply_for_user(clarification_reply)
            if (
                pending_fix_proposal_card is None
                and recovered_pending_intent_card is None
                and plan_confirmation_candidate is None
                and isinstance(reply, str)
            ):
                promised_fix_card = await self._maybe_recover_promised_fix_preview_card(
                    session_id=session_id,
                    content=content,
                    reply=reply,
                    request_context=request_context,
                    tool_context_messages=tool_context_messages,
                )
                if promised_fix_card is not None:
                    pending_fix_proposal_card, ready_proposal = promised_fix_card
                    if ready_proposal is not None:
                        primary_fix_reply = _fix_proposal_pending_primary_reply(ready_proposal)
                        if primary_fix_reply:
                            _replace_text_reply(new_messages, reply, primary_fix_reply)
                            _replace_text_reply(all_messages, reply, primary_fix_reply)
                            reply = primary_fix_reply
        if (
            plan_confirmation_candidate is None
            and pending_fix_proposal_card is None
            and recovered_pending_intent_card is None
            and not composite_goal_clarification_reply
        ):
            structured_goal_preview = _latest_structured_goal_plan_preview(tool_context_messages)
            pending_fix_proposal_card = await _maybe_create_plan_confirmation_from_structured_goal(
                session_id,
                composite_goal_preview or structured_goal_preview,
                context_source="plan_next_action_composite_goal",
            )
            if pending_fix_proposal_card is not None and isinstance(reply, str):
                preview_payload = _parse_tool_return_json(
                    getattr(pending_fix_proposal_card, "content", "") or ""
                )
                primary_structured_goal_reply = ""
                if isinstance(preview_payload, dict):
                    card_summary = str(preview_payload.get("summary") or "").strip()
                    card_content = str(preview_payload.get("content") or "").strip()
                    preview_lines = ["已列出这次调整预览。"]
                    if card_summary:
                        preview_lines.extend(["", card_summary])
                    elif card_content:
                        preview_lines.extend(["", card_content])
                    preview_lines.extend(
                        [
                            "",
                            "具体调整内容在下面卡片里。确认前不会改动当前方案；点“确认执行”后，我会按这条建议处理，并重新刷新方案和审查结果。",
                        ]
                    )
                    primary_structured_goal_reply = _sanitize_reply_for_user("\n".join(preview_lines))
                    if primary_structured_goal_reply:
                        _replace_text_reply(new_messages, reply, primary_structured_goal_reply)
                        _replace_text_reply(all_messages, reply, primary_structured_goal_reply)
                        reply = primary_structured_goal_reply
        if (
            plan_confirmation_candidate
            and pending_fix_proposal_card is None
            and recovered_pending_intent_card is None
            and not composite_goal_clarification_reply
            and not _plan_confirmation_candidate_is_explicit_atomic_target(plan_confirmation_candidate)
        ):
            composite_override_card = await self._maybe_override_plan_confirmation_with_composite_goal(
                session_id=session_id,
                content=content,
                request_context=request_context,
                plan_confirmation_candidate=plan_confirmation_candidate,
            )
            if composite_override_card is not None:
                plan_confirmation_candidate = None
                composite_override_kind = _pending_card_kind(composite_override_card)
                if composite_override_kind == "readonly_notice":
                    card_payload = _parse_tool_return_json(
                        getattr(composite_override_card, "content", "") or ""
                    )
                    readonly_reply = str((card_payload or {}).get("reply") or "").strip() if isinstance(card_payload, dict) else ""
                    if readonly_reply and isinstance(reply, str):
                        _replace_text_reply(new_messages, reply, readonly_reply)
                        _replace_text_reply(all_messages, reply, readonly_reply)
                        reply = readonly_reply
                elif composite_override_kind == "intent_change":
                    recovered_pending_intent_card = composite_override_card
                    recovered_pending_intent_reply = _intent_card_primary_reply_from_card(
                        composite_override_card
                    )
                    if recovered_pending_intent_reply and isinstance(reply, str):
                        _replace_text_reply(new_messages, reply, recovered_pending_intent_reply)
                        _replace_text_reply(all_messages, reply, recovered_pending_intent_reply)
                        reply = recovered_pending_intent_reply
                else:
                    pending_fix_proposal_card = composite_override_card
                    if isinstance(reply, str):
                        card_payload = _parse_tool_return_json(
                            getattr(composite_override_card, "content", "") or ""
                        )
                        card_summary = (
                            str((card_payload or {}).get("summary") or "").strip()
                            if isinstance(card_payload, dict)
                            else ""
                        )
                        primary_goal_reply = "已按你的要求列出调整预览。"
                        if card_summary:
                            primary_goal_reply = f"已按你的要求列出调整预览：{card_summary}。"
                        primary_goal_reply += "确认前不会改动当前方案；确认后会同步更新后续报考参考，并按预览调整当前方案。"
                        primary_goal_reply = _sanitize_reply_for_user(primary_goal_reply)
                        _replace_text_reply(new_messages, reply, primary_goal_reply)
                        _replace_text_reply(all_messages, reply, primary_goal_reply)
                        reply = primary_goal_reply
                plan_action_recovery_route = {
                    "source": "composite_goal_override_plan_confirmation",
                    "matched": True,
                    "confidence": "semantic",
                    "route": "user_goal_proposal",
                }
        if (
            plan_confirmation_candidate
            and _plain_plan_candidate_conflicts_with_active_only_keep_intent(
                backend_pending_state if isinstance(backend_pending_state, dict) else None,
                plan_confirmation_candidate,
            )
        ):
            plan_confirmation_candidate = None
            pending_context_reply = _build_pending_readonly_impact_reply(
                backend_pending_state if isinstance(backend_pending_state, dict) else {}
            )
            if isinstance(reply, str):
                guarded_pending_reply = (
                    pending_context_reply.rstrip()
                    + "\n\n如果这就是你想采用的方向，请先点“采纳”；采纳后我再按这条参考检查或调整当前方案。"
                )
                guarded_pending_reply = _sanitize_reply_for_user(guarded_pending_reply)
                _replace_text_reply(new_messages, reply, guarded_pending_reply)
                _replace_text_reply(all_messages, reply, guarded_pending_reply)
                reply = guarded_pending_reply
        if plan_confirmation_candidate:
            plan_card_includes_intent_update = bool(
                isinstance(plan_confirmation_candidate.get("intent_update"), dict)
                and plan_confirmation_candidate.get("intent_update", {}).get("selected")
            )
            plan_confirmation_card = await _create_pending_plan_confirmation_response(
                session_id,
                plan_confirmation_candidate,
            )
            if isinstance(reply, str):
                primary_preview_reply = _plan_confirmation_card_primary_reply(plan_confirmation_candidate)
                _replace_text_reply(new_messages, reply, primary_preview_reply)
                _replace_text_reply(all_messages, reply, primary_preview_reply)
                reply = primary_preview_reply
        pending_intent_card: WSResponse | None = None
        if (
            pending_fix_proposal_card is None
            and plan_confirmation_card is None
            and intent_preview_used
            and not intent_preview_downgraded
            and not plan_card_includes_intent_update
        ):
            tuition_budget_card = await self._maybe_recover_tuition_budget_from_intent_preview(
                session_id=session_id,
                content=content,
                request_context=request_context,
                tool_context_messages=tool_context_messages,
            )
            if tuition_budget_card is not None:
                pending_fix_proposal_card = tuition_budget_card
                plan_action_recovery_route = {
                    "source": "tuition_budget_recovery_from_intent_preview",
                    "matched": True,
                    "confidence": "semantic",
                    "route": "user_goal_proposal",
                }
                if isinstance(reply, str):
                    card_payload = _parse_tool_return_json(
                        getattr(tuition_budget_card, "content", "") or ""
                    )
                    card_summary = (
                        str((card_payload or {}).get("summary") or "").strip()
                        if isinstance(card_payload, dict)
                        else ""
                    )
                    primary_budget_reply = "已按你的预算要求列出调整预览。"
                    if card_summary:
                        primary_budget_reply = f"已按你的预算要求列出调整预览：{card_summary}。"
                    primary_budget_reply += "确认前不会改动当前方案；确认后会按预算上限处理当前方案，并同步刷新候选参考。"
                    primary_budget_reply = _sanitize_reply_for_user(primary_budget_reply)
                    _replace_text_reply(new_messages, reply, primary_budget_reply)
                    _replace_text_reply(all_messages, reply, primary_budget_reply)
                    reply = primary_budget_reply
        if intent_preview_used and not intent_preview_downgraded and not plan_card_includes_intent_update:
            preview_payload = _extract_recent_intent_analysis_payload(tool_context_messages)
            if not preview_payload:
                preview_payload = _extract_recent_intent_analysis_payload(all_messages)
            if pending_fix_proposal_card is None:
                pending_intent_card = await _create_pending_intent_confirmation_from_preview_payload(
                    session_id,
                    preview_payload,
                )
            if pending_intent_card is not None and isinstance(reply, str):
                primary_text = _pending_confirmation_primary_reply_from_card(pending_intent_card)
                if not primary_text:
                    primary_text = _intent_card_primary_reply_from_preview_payload(preview_payload)
                _replace_text_reply(new_messages, reply, "")
                _replace_text_reply(all_messages, reply, "")
                reply = primary_text
        if isinstance(reply, str):
            final_user_reply = _sanitize_reply_for_user(reply)
            if final_user_reply != reply:
                _replace_text_reply(new_messages, reply, final_user_reply)
                _replace_text_reply(all_messages, reply, final_user_reply)
                reply = final_user_reply
            latest_review_result = _latest_readonly_plan_execution_result(tool_context_messages)
            if (
                latest_review_result is not None
                and _result_needs_unavailable_guidance_fallback(latest_review_result, user_prompt=content)
            ):
                structured_review_reply = _build_plan_timeout_fallback_reply(
                    latest_review_result,
                    user_prompt=content,
                ) or reply
                structured_review_reply = _sanitize_reply_for_user(structured_review_reply)
                if structured_review_reply != reply:
                    _replace_text_reply(new_messages, reply, structured_review_reply)
                    _replace_text_reply(all_messages, reply, structured_review_reply)
                    reply = structured_review_reply
            elif _review_reply_overclaims_admission_safety(reply, latest_review_result):
                structured_review_reply = _build_plan_timeout_fallback_reply(
                    latest_review_result,
                    user_prompt=content,
                ) or reply
                structured_review_reply = _sanitize_reply_for_user(structured_review_reply)
                if structured_review_reply != reply:
                    _replace_text_reply(new_messages, reply, structured_review_reply)
                    _replace_text_reply(all_messages, reply, structured_review_reply)
                    reply = structured_review_reply
            elif _review_reply_needs_structured_fallback(reply, latest_review_result):
                structured_review_reply = _build_plan_timeout_fallback_reply(
                    latest_review_result,
                    user_prompt=content,
                ) or reply
                structured_review_reply = _sanitize_reply_for_user(structured_review_reply)
                if structured_review_reply != reply:
                    _replace_text_reply(new_messages, reply, structured_review_reply)
                    _replace_text_reply(all_messages, reply, structured_review_reply)
                    reply = structured_review_reply
            elif _review_reply_needs_boundary(reply, latest_review_result):
                bounded_review_reply = _sanitize_reply_for_user(
                    f"已完成方案审查。\n\n{reply.lstrip()}"
                )
                if bounded_review_reply != reply:
                    _replace_text_reply(new_messages, reply, bounded_review_reply)
                    _replace_text_reply(all_messages, reply, bounded_review_reply)
                    reply = bounded_review_reply
            latest_adjustment_result = _latest_readonly_plan_execution_result(tool_context_messages)
            if _adjustment_reply_needs_structured_fallback(reply, latest_adjustment_result):
                structured_adjustment_reply = _build_plan_timeout_fallback_reply(
                    latest_adjustment_result,
                    user_prompt=content,
                ) or reply
                structured_adjustment_reply = _sanitize_reply_for_user(structured_adjustment_reply)
                if structured_adjustment_reply != reply:
                    _replace_text_reply(new_messages, reply, structured_adjustment_reply)
                    _replace_text_reply(all_messages, reply, structured_adjustment_reply)
                    reply = structured_adjustment_reply
        pending_type = "plan" if active_pending_kind == "plan_mutation" else "intent" if active_pending_kind == "intent_change" else None
        turn_event = {
            "sessionId": session_id,
            "userId": user_id,
            "scene": scene,
            "routingPath": "full_agent",
            "routeDecision": {
                "source": "full_agent",
                "matched": True,
                "confidence": "model",
                "route": scene,
                "fallbackReason": "plan_action_recovery" if plan_action_recovery_route else "no_direct_route",
                "recovery": plan_action_recovery_route,
                "toolTrial": full_agent_tool_trial,
                "agentRun": dict(getattr(request_context, "agent_observability", {}) or {}),
            },
            "pendingType": pending_type,
            "actionFamily": action_family,
            "modelProvider": _llm_config_value(self.llm_client, "provider"),
            "modelName": _llm_config_value(self.llm_client, "model_name"),
            "llmRequests": getattr(usage, "requests", None),
            "inputTokens": getattr(usage, "input_tokens", None),
            "outputTokens": getattr(usage, "output_tokens", None),
            "totalTokens": getattr(usage, "total_tokens", None),
            "toolCallCount": getattr(usage, "tool_calls", None),
            "totalDurationMs": int((time.monotonic() - turn_started_at) * 1000),
            "llmDurationMs": llm_duration_ms,
            "toolDurationMs": None,
            "toolCalls": observed_tool_calls,
            "postProcessingApplied": ["plan_action_recovery"] if plan_action_recovery_route else [],
            "status": "success",
            "errorType": None,
        }
        _log_conversation_turn_event(
            **turn_event,
        )

        # ── 保存历史 ──────────────────────────────────────────────
        try:
            history_to_save = list(history or [])
            if history_to_save and new_messages:
                history_to_save.extend(_append_route_observability_message(new_messages, turn_event))
            elif new_messages:
                history_to_save = _append_route_observability_message(list(new_messages), turn_event)
            else:
                runtime_len = len(runtime_history.model_history or [])
                inferred_new_messages = list(all_messages[runtime_len:]) if len(all_messages) >= runtime_len else []
                inferred_new_messages = _append_route_observability_message(inferred_new_messages, turn_event)
                if history_to_save and inferred_new_messages:
                    history_to_save.extend(inferred_new_messages)
                elif inferred_new_messages:
                    history_to_save = inferred_new_messages
                elif not history_to_save:
                    history_to_save = _append_route_observability_message(list(all_messages), turn_event)

            await self.history_store.save(session_id, history_to_save)
        except Exception:
            logger.exception("Failed to save chat history: session_id=%s", session_id)

        logger.debug(
            "Conversation turn event: %s",
            json.dumps(turn_event, ensure_ascii=False, default=str),
        )

        logger.info(
            "ChatService completed: session_id=%s reply=%s new_history_len=%d",
            session_id, reply, len(all_messages),
        )
        followups: list[WSResponse] = []
        if workspace_refresh_targets:
            logger.info(
                "ChatService attaching planning workspace refresh after planning action: session_id=%s targets=%s",
                session_id,
                workspace_refresh_targets,
            )
            followups.extend(
                _build_silent_workspace_refresh_response(session_id, target)
                for target in workspace_refresh_targets
            )
        if workspace_view_targets:
            already = set(workspace_refresh_targets)
            for target in workspace_view_targets:
                if target not in already:
                    followups.append(
                        _build_workspace_action_response(session_id, target, refresh=False)
                    )
        if plan_confirmation_card is not None:
            followups.append(plan_confirmation_card)
        if pending_fix_proposal_card is not None:
            followups.append(pending_fix_proposal_card)
        if pending_intent_card is not None:
            followups.append(pending_intent_card)
        elif recovered_pending_intent_card is not None:
            followups.append(recovered_pending_intent_card)
        if isinstance(reply, str):
            reply = _sanitize_reply_for_user(reply)
        if followups and isinstance(reply, str) and not reply.strip():
            pending_card = pending_intent_card or recovered_pending_intent_card
            if pending_card is not None:
                fallback_primary = _pending_confirmation_primary_reply_from_card(pending_card)
                if fallback_primary:
                    reply = fallback_primary
        if followups and not isinstance(reply, WSResponse):
            return ChatServiceResponseEnvelope(primary=reply, followups=followups)
        return reply

    async def handle_intent_select(
        self, session_id: str, user_id: str, content: str,
        batch: str | None = None,
    ) -> str | WSResponse:
        """处理意向确认选择请求，按用户勾选结果局部采纳。"""
        logger.info(
            "ChatService handling intent selection: session_id=%s content_len=%d",
            session_id, len(content),
        )
        try:
            selected_data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return "消息格式错误，请重试。"

        # Try to determine batch from score detail if not provided
        if not batch:
            try:
                score_response = await get_user_score_detail(session_id)
                if score_response.get("code") == 0:
                    raw_data = score_response.get("data", {}).get("userScoreDetail", {})
                    if raw_data:
                        batch = _normalize_batch(raw_data.get("batch", "01"))
            except Exception:
                logger.warning("Failed to fetch batch for intent selection: session_id=%s", session_id)

        action_type = (selected_data.get("actionType") or "").strip()
        if action_type:
            logger.info(
                "ChatService handling interest follow-up action: session_id=%s action_type=%s",
                session_id,
                action_type,
            )
            followup_json = await handle_interest_analysis_action_result(
                session_id=session_id,
                batch=batch or "01",
                action_type=action_type,
            )
            try:
                followup_result = parse_explore_followup_result(followup_json)
            except Exception:
                logger.warning(
                    "Failed to parse explore follow-up result: session_id=%s action_type=%s",
                    session_id,
                    action_type,
                    exc_info=True,
                )
                return "处理这一步时发生错误，请稍后重试。"
            if action_type in {"prefer_confirm", "constrain_confirm"} and followup_result.analysisPayload:
                pending_card = await _create_pending_intent_confirmation_from_preview_payload(
                    session_id,
                    followup_result.analysisPayload,
                )
                if pending_card is not None:
                    primary_text = _intent_card_primary_reply_from_preview_payload(followup_result.analysisPayload)
                    return ChatServiceResponseEnvelope(
                        primary=primary_text,
                        followups=[pending_card],
                    )
            return render_explore_followup_result(followup_result)

        selected_values = selected_data.get("selected", [])
        if not selected_values:
            return "你这次没有采纳任何意向调整。"
        try:
            merged = merge_selected_values(selected_values)
        except Exception:
            logger.warning("Failed to merge selected intents: session_id=%s", session_id, exc_info=True)
            return "处理这一步时发生错误，请稍后重试。"
        intent_mode = await _resolve_intent_mode_from_message(selected_data.get("message_id"))
        return await _create_pending_intent_confirmation_response(
            session_id=session_id,
            selected_data=selected_data,
            merged=merged,
            intent_mode=intent_mode,
            batch=batch or "01",
        )

    async def handle_pending_confirmation(
        self,
        session_id: str,
        user_id: str,
        content: str,
        *,
        confirmation_entry: str = "card",
        user_prompt_content: str | None = None,
    ) -> str | ChatServiceResponseEnvelope:
        """Handle explicit confirmation-card actions.

        This is the migration bridge before durable pending_id endpoints land:
        the card click is explicit, while the executable payload is still
        recovered from recent persisted plan preview history.
        """
        try:
            selected_data = json.loads(content) if isinstance(content, str) else {}
        except (json.JSONDecodeError, TypeError):
            return "消息格式错误，请重试。"
        if not isinstance(selected_data, dict):
            return "消息格式错误，请重试。"

        action = str(selected_data.get("action") or "").strip().lower()
        kind = str(selected_data.get("kind") or "").strip()
        pending_id = str(selected_data.get("pendingId") or selected_data.get("pending_id") or "").strip()
        message_id = selected_data.get("message_id")
        confirmation_entry = "short_text" if confirmation_entry == "short_text" else "card"
        pending_state = await _load_pending_confirmation_state(session_id)
        active_pending_id = str((pending_state or {}).get("pendingId") or "").strip()
        active_status = str((pending_state or {}).get("status") or "").strip()
        if not pending_id:
            return "这次操作缺少校验信息，请重新生成预览后再确认。"
        if not pending_state or active_status != "active" or active_pending_id != pending_id:
            await _mark_pending_confirmation_message_status(
                session_id,
                message_id,
                pending_id=pending_id,
                status="expired",
            )
            return "这次待采纳内容已经失效。请以最新内容为准，或重新说明想怎么调整。"
        if kind and kind != str(pending_state.get("kind") or ""):
            await _mark_pending_confirmation_message_status(
                session_id,
                message_id,
                pending_id=pending_id,
                status="expired",
            )
            return "这次操作和当前等待采纳的内容不一致，请以最新内容为准。"

        if action in {"cancel", "reject"}:
            cancelled_state = dict(pending_state)
            cancelled_state["status"] = "cancelled"
            cancelled_state["updatedAt"] = datetime.now(timezone.utc).isoformat()
            await _save_pending_confirmation_state(session_id, cancelled_state)
            await _mark_pending_confirmation_message_status(
                session_id,
                message_id,
                pending_id=pending_id,
                status="cancelled",
            )
            return "已取消本次待采纳内容。你可以继续说明想怎么调整，我会重新给出预览。"
        if action not in {"confirm", "accept", "apply"}:
            return "这次操作类型不完整，请刷新后重试。"
        active_kind = str(pending_state.get("kind") or "").strip()
        consistency_status = "not_checked"
        assistant_confirmation_summary = ""
        blocked_reason = None
        confirmation_history: list[Any] | None = None

        def emit_pending_event(*, result: str, result_code: str | None = None) -> None:
            _log_pending_confirmation_event(
                eventType="pending_confirmation_apply",
                sessionId=session_id,
                userId=user_id,
                pendingId=pending_id,
                kind=active_kind,
                actionFamily=str(pending_state.get("actionFamily") or "").strip() or None,
                confirmationEntry=confirmation_entry,
                pendingSummary=str(pending_state.get("summary") or "").strip(),
                assistantConfirmationSummary=assistant_confirmation_summary,
                consistencyStatus=consistency_status,
                blockedReason=blocked_reason,
                sourceBackendVersion=pending_state.get("sourceBackendVersion"),
                result=result,
                resultCode=result_code,
            )

        if confirmation_entry == "short_text":
            try:
                confirmation_history = await self.history_store.load(session_id) or []
            except Exception:
                logger.exception("Failed to load history for pending confirmation consistency check: session_id=%s", session_id)
                confirmation_history = []
            consistency_status, blocked_reason, assistant_confirmation_summary = _evaluate_short_text_pending_consistency(
                pending_state,
                confirmation_history,
            )
            if blocked_reason:
                reply = "为避免确认错内容，请点最新内容里的“采纳”，或重新说明要确认的内容，我会重新列出待采纳内容。"
                await _save_direct_guard_history(
                    self.history_store,
                    session_id,
                    confirmation_history,
                    user_prompt_content or content,
                    reply,
                    model_name=f"pending-confirmation-consistency-blocked:{pending_id}",
                )
                emit_pending_event(result="blocked", result_code=blocked_reason)
                return reply

        if active_kind == "intent_change":
            execution_payload = pending_state.get("executionPayload")
            if not isinstance(execution_payload, dict):
                return "这次待采纳内容缺少可执行内容，请重新生成。"
            selected_data = execution_payload.get("selectedData")
            if not isinstance(selected_data, dict):
                return "这次待采纳内容缺少可执行内容，请重新生成。"
            result_json = await _apply_selected_intents(
                session_id=session_id,
                batch=str(execution_payload.get("batch") or "01"),
                selected_data=selected_data,
            )
            try:
                state_result = parse_intent_state_update_result(result_json)
                reply = render_intent_state_update(state_result)
            except Exception:
                logger.warning("Failed to parse pending intent confirmation result: session_id=%s", session_id, exc_info=True)
                state_result = None
                reply = "处理这一步时发生错误，请稍后重试。"
            applied_state = dict(pending_state)
            applied_state["status"] = "applied"
            applied_state["updatedAt"] = datetime.now(timezone.utc).isoformat()
            applied_state["resultCode"] = getattr(state_result, "messageCode", None) if state_result else None
            await _save_pending_confirmation_state(session_id, applied_state)
            await _mark_pending_confirmation_message_status(
                session_id,
                message_id,
                pending_id=pending_id,
                status="applied",
            )
            emit_pending_event(
                result="applied",
                result_code=getattr(state_result, "messageCode", None) if state_result else None,
            )
            if confirmation_entry == "short_text":
                new_messages = [
                    ModelRequest(parts=[UserPromptPart(content=user_prompt_content or content)]),
                    ModelResponse(parts=[TextPart(content=reply)], model_name="pending-intent-short-text-confirm"),
                ]
                try:
                    history = confirmation_history if confirmation_history is not None else await self.history_store.load(session_id) or []
                    history_to_save = list(history)
                    history_to_save.extend(new_messages)
                    await self.history_store.save(session_id, history_to_save)
                except Exception:
                    logger.exception("Failed to save short-text pending intent confirmation history: session_id=%s", session_id)
            if state_result and state_result.intentMode == "constraint":
                followups: list[WSResponse] = []
                followups.append(
                    _build_silent_workspace_refresh_response(
                        session_id,
                        "ordered",
                        extra_payload={
                            "title": "请查看方案",
                            "content": "这次要求已采纳，当前方案可能需要重新审查或调整。",
                            "actionText": "查看方案",
                        },
                    )
                )
                followups.append(
                    _build_silent_workspace_refresh_response(
                        session_id,
                        "candidate",
                        extra_payload={
                            "preserveView": True,
                            "title": "候选推荐已更新",
                            "content": "这次报考条件已采纳，候选和推荐信息会按新的条件刷新。",
                            "actionText": "查看候选",
                        },
                    )
                )
                return ChatServiceResponseEnvelope(
                    primary=reply,
                    followups=followups,
                )
            if state_result and state_result.intentMode == "preference":
                return ChatServiceResponseEnvelope(
                    primary=reply,
                    followups=[
                        _build_silent_workspace_refresh_response(
                            session_id,
                            "candidate",
                            extra_payload={
                                "preserveView": True,
                                "title": "候选推荐已更新",
                                "content": "这次偏好已采纳，候选和推荐信息会按新的偏好刷新。",
                                "actionText": "查看候选",
                            },
                        )
                    ],
                )
            return reply
        if active_kind != "plan_mutation":
            return "这类待采纳内容暂时还不能在这里处理，请刷新后重试。"

        execution_payload = pending_state.get("executionPayload")
        if not isinstance(execution_payload, dict):
            return "这次方案调整缺少可执行内容，请重新生成预览。"
        action_family = str(pending_state.get("actionFamily") or "").strip()
        tool_name = str(execution_payload.get("toolName") or "").strip()
        if action_family == "apply_fix_proposal" or tool_name == "apply_planning_fix_proposal":
            started_at = time.monotonic()
            proposal_source = str(
                execution_payload.get("proposalSource")
                or execution_payload.get("proposal_source")
                or "review_check"
            ).strip() or "review_check"
            proposal_id = str(
                execution_payload.get("proposalId")
                or execution_payload.get("proposal_id")
                or ""
            ).strip()
            source_version_guard = _as_int(
                execution_payload.get("sourceVersionGuard")
                or execution_payload.get("source_version_guard")
                or pending_state.get("sourceBackendVersion")
                or pending_state.get("source_backend_version")
            )
            if not proposal_id or source_version_guard <= 0:
                await _mark_pending_confirmation_failed(
                    session_id,
                    pending_state,
                    message_id,
                    pending_id=pending_id,
                    result_code="missing_fix_proposal_apply_args",
                )
                emit_pending_event(result="failed", result_code="missing_fix_proposal_apply_args")
                return "这次处理建议缺少必要信息，请重新查看方案审查结果后再处理。"

            regenerate_ordered_plan = execution_payload.get("regenerateOrderedPlan")
            if regenerate_ordered_plan is None:
                regenerate_ordered_plan = execution_payload.get("regenerate_ordered_plan")
            rerun_review = execution_payload.get("rerunReview")
            if rerun_review is None:
                rerun_review = execution_payload.get("rerun_review")
            user_goal_request = execution_payload.get("userGoalRequest")
            if not isinstance(user_goal_request, dict):
                user_goal_request = None
            intent_payload = execution_payload.get("intentPayload")
            intent_apply_note = ""
            if proposal_source == "user_goal" and isinstance(intent_payload, dict) and intent_payload.get("selected"):
                effective_batch = _normalize_batch(intent_payload.get("batch") or "01")
                selected_data_for_apply = {
                    "selected": intent_payload.get("selected") or [],
                    "intentMode": str(intent_payload.get("intentMode") or "constraint").strip() or "constraint",
                    "constraintIntentType": str(
                        intent_payload.get("constraintIntentType")
                        or intent_payload.get("constraint_intent_type")
                        or "default"
                    ).strip() or "default",
                    "batch": effective_batch,
                }
                intent_result_json = await _apply_selected_intents(
                    session_id=session_id,
                    batch=effective_batch,
                    selected_data=selected_data_for_apply,
                )
                try:
                    intent_state_result = parse_intent_state_update_result(intent_result_json)
                except Exception:
                    logger.warning(
                        "Failed to parse user-goal intent confirmation result: session_id=%s",
                        session_id,
                        exc_info=True,
                    )
                    await _mark_pending_confirmation_failed(
                        session_id,
                        pending_state,
                        message_id,
                        pending_id=pending_id,
                        result_code="intent_apply_parse_failed",
                    )
                    return "这次报考条件没有写入成功，方案暂不调整。请稍后重试，或重新列出待采纳内容。"
                if not getattr(intent_state_result, "applied", False):
                    await _mark_pending_confirmation_failed(
                        session_id,
                        pending_state,
                        message_id,
                        pending_id=pending_id,
                        result_code=str(getattr(intent_state_result, "messageCode", None) or "intent_apply_failed"),
                    )
                    return "这次报考条件没有写入成功，方案暂不调整。请稍后重试，或重新列出待采纳内容。"
                intent_apply_note = "后续报考参考已同步更新。"
                try:
                    state_resp = await get_planning_state(session_id)
                    current_version = _as_int(((state_resp or {}).get("data") or {}).get("version"))
                except Exception:
                    logger.warning("Failed to reload planning state before user-goal apply: session_id=%s", session_id, exc_info=True)
                    current_version = 0
                if current_version <= 0 or not user_goal_request:
                    await _mark_pending_confirmation_failed(
                        session_id,
                        pending_state,
                        message_id,
                        pending_id=pending_id,
                        result_code="missing_user_goal_apply_args",
                    )
                    return "这次方案调整缺少必要信息，请重新生成调整预览后再确认。"
                refreshed_user_goal_request = dict(user_goal_request)
                refreshed_user_goal_request["sourceVersionGuard"] = current_version
                try:
                    proposal_result = await generate_user_goal_planning_fix_proposals(
                        1,
                        session_id,
                        refreshed_user_goal_request,
                    )
                except Exception:
                    logger.warning(
                        "Failed to refresh user-goal proposal before apply: session_id=%s",
                        session_id,
                        exc_info=True,
                    )
                    await _mark_pending_confirmation_failed(
                        session_id,
                        pending_state,
                        message_id,
                        pending_id=pending_id,
                        result_code="user_goal_proposal_refresh_exception",
                    )
                    return "当前方案已经更新，需要重新生成调整预览后再确认。"
                proposal_data = proposal_result.get("data") if isinstance(proposal_result, dict) else None
                if proposal_result.get("code") != 0 or not isinstance(proposal_data, dict):
                    await _mark_pending_confirmation_failed(
                        session_id,
                        pending_state,
                        message_id,
                        pending_id=pending_id,
                        result_code="user_goal_proposal_refresh_failed",
                    )
                    return "当前方案已经更新，需要重新生成调整预览后再确认。"
                refreshed_proposal = _select_ready_fix_proposal(
                    {"fix_proposals": proposal_data},
                    target_strategies=[str(refreshed_user_goal_request.get("goalType") or "").strip()],
                )
                if not isinstance(refreshed_proposal, dict):
                    await _mark_pending_confirmation_failed(
                        session_id,
                        pending_state,
                        message_id,
                        pending_id=pending_id,
                        result_code="user_goal_proposal_no_ready",
                    )
                    return "这次想法已写入后续报考参考，但当前方案暂时没有可直接执行的调整项。你可以重新查看方案或放宽条件后再调整。"
                proposal_id = str(
                    refreshed_proposal.get("proposalId")
                    or refreshed_proposal.get("proposal_id")
                    or ""
                ).strip()
                source_version_guard = _as_int(
                    refreshed_proposal.get("sourceVersionGuard")
                    or refreshed_proposal.get("source_version_guard")
                    or proposal_data.get("sourceVersionGuard")
                    or current_version
                )
                user_goal_request = refreshed_user_goal_request
            try:
                result_json = await apply_planning_fix_proposal(
                    1,
                    session_id,
                    proposal_id=proposal_id,
                    source_version_guard=source_version_guard,
                    regenerate_ordered_plan=regenerate_ordered_plan is not False,
                    rerun_review=rerun_review is not False,
                    proposal_source=proposal_source,
                    user_goal_request=user_goal_request,
                )
            except Exception:
                logger.warning(
                    "Failed to apply pending fix proposal: session_id=%s proposal_id=%s",
                    session_id,
                    proposal_id,
                    exc_info=True,
                )
                await _mark_pending_confirmation_failed(
                    session_id,
                    pending_state,
                    message_id,
                    pending_id=pending_id,
                    result_code="fix_proposal_apply_exception",
                )
                emit_pending_event(result="failed", result_code="fix_proposal_apply_exception")
                return "这次处理建议没有执行成功。请重新查看方案审查结果后再试。"

            result_data = result_json.get("data") if isinstance(result_json, dict) else None
            if not isinstance(result_data, dict):
                result_data = {}
            result_code = str(result_json.get("code") if isinstance(result_json, dict) else "").strip()
            applied = result_code == "0" and str(result_data.get("status") or "").strip() == "applied"
            if not applied:
                await _mark_pending_confirmation_failed(
                    session_id,
                    pending_state,
                    message_id,
                    pending_id=pending_id,
                    result_code=str(result_json.get("msg") if isinstance(result_json, dict) else "")
                    or "fix_proposal_apply_failed",
                )
                emit_pending_event(result="failed", result_code="fix_proposal_apply_failed")
                return str(
                    (result_json or {}).get("msg")
                    if isinstance(result_json, dict)
                    else ""
                ).strip() or "这次处理建议没有执行成功。请重新查看方案审查结果后再试。"

            reply = _format_fix_proposal_apply_result(result_data)
            if intent_apply_note:
                reply = f"{reply}\n\n{intent_apply_note}"
            tuition_apply_note = ""
            max_tuition_per_year = _max_tuition_from_user_goal_request(user_goal_request)
            if proposal_source == "user_goal" and max_tuition_per_year > 0:
                try:
                    tuition_result = await update_session_tuition_range(
                        session_id,
                        min_tuition=0,
                        max_tuition=max_tuition_per_year,
                    )
                except Exception:
                    logger.warning(
                        "Failed to update tuition range after user-goal apply: session_id=%s max_tuition=%s",
                        session_id,
                        max_tuition_per_year,
                        exc_info=True,
                    )
                    tuition_result = {}
                if isinstance(tuition_result, dict) and str(tuition_result.get("code")) == "0":
                    tuition_apply_note = f"后续候选筛选也会按每年不超过 {max_tuition_per_year} 元继续参考。"
                else:
                    tuition_apply_note = "这次方案调整已处理，但学费范围没有同步成功；后续候选筛选可能还需要手动刷新预算。"
            if tuition_apply_note:
                reply = f"{reply}\n\n{tuition_apply_note}"
            applied_state = dict(pending_state)
            applied_state["status"] = "applied"
            applied_state["updatedAt"] = datetime.now(timezone.utc).isoformat()
            applied_state["resultCode"] = "applied"
            applied_state["resultData"] = result_data
            await _save_pending_confirmation_state(session_id, applied_state)
            await _mark_pending_confirmation_message_status(
                session_id,
                message_id,
                pending_id=pending_id,
                status="applied",
            )

            tool_args = {
                "proposal_id": proposal_id,
                "proposal_source": proposal_source,
                "source_version_guard": source_version_guard,
                "regenerate_ordered_plan": regenerate_ordered_plan is not False,
                "rerun_review": rerun_review is not False,
            }
            if user_goal_request:
                tool_args["user_goal_request"] = user_goal_request
            result_text = json.dumps(result_json, ensure_ascii=False)
            new_messages = [
                ModelRequest(parts=[UserPromptPart(content=user_prompt_content or "[确认处理方案提醒]")]),
                ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="apply_planning_fix_proposal",
                            args=tool_args,
                            tool_call_id=f"{confirmation_entry}-apply-fix-proposal-confirmation",
                        )
                    ],
                    model_name=f"pending-confirmation-{confirmation_entry}",
                ),
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name="apply_planning_fix_proposal",
                            content=result_text,
                            tool_call_id=f"{confirmation_entry}-apply-fix-proposal-confirmation",
                        )
                    ]
                ),
                ModelResponse(parts=[TextPart(content=reply)], model_name=f"pending-confirmation-{confirmation_entry}"),
            ]
            try:
                history = confirmation_history if confirmation_history is not None else await self.history_store.load(session_id) or []
                history_to_save = list(history)
                history_to_save.extend(new_messages)
                await self.history_store.save(session_id, history_to_save)
            except Exception:
                logger.exception("Failed to save pending fix proposal confirmation history: session_id=%s", session_id)

            _log_conversation_turn_event(
                sessionId=session_id,
                userId=user_id,
                scene="plan",
                routingPath="pending_plan_short_text_confirm" if confirmation_entry == "short_text" else "plan_confirmation_card_confirm",
                pendingType="plan",
                actionFamily=action_family,
                totalDurationMs=int((time.monotonic() - started_at) * 1000),
                status="success",
                errorType=None,
            )
            emit_pending_event(result="applied", result_code="applied")
            followups = [
                _build_silent_workspace_refresh_response(
                    session_id,
                    "ordered",
                    extra_payload={
                        "title": "方案已更新",
                        "content": "已按这条处理建议刷新方案，可以查看调整后的排序方案。",
                        "actionText": "查看方案",
                    },
                )
            ]
            if proposal_source == "user_goal":
                followups.append(
                    _build_silent_workspace_refresh_response(
                        session_id,
                        "candidate",
                        extra_payload={
                            "preserveView": True,
                            "title": "候选推荐已更新",
                            "content": "这次报考条件已采纳，候选和推荐信息会按新的条件刷新。",
                            "actionText": "查看候选",
                        },
                    )
                )
                followups.append(
                    _build_silent_workspace_refresh_response(
                        session_id,
                        "review",
                        extra_payload={
                            "preserveView": True,
                            "title": "审查结果已刷新",
                            "content": "方案调整后已重新检查风险和提醒。",
                            "actionText": "查看审查",
                        },
                    )
                )
            return ChatServiceResponseEnvelope(
                primary=_sanitize_reply_for_user(reply),
                followups=followups,
            )

        plan_payload = execution_payload.get("planPayload")
        if not isinstance(plan_payload, str) or not plan_payload.strip():
            return "这次方案调整缺少可执行内容，请重新生成预览。"
        intent_payload = execution_payload.get("intentPayload")
        history_task = None
        if confirmation_history is None:
            history_task = asyncio.create_task(self.history_store.load(session_id))
        score_task = asyncio.create_task(get_user_score_detail(session_id))
        profile_task = asyncio.create_task(get_user_init_profile(session_id))
        workspace_task = asyncio.create_task(get_planning_workspace_state(session_id))

        history = confirmation_history if confirmation_history is not None else []
        if history_task is not None:
            try:
                history_result = await history_task
                history = history_result or []
            except Exception:
                logger.exception("Failed to load history for pending confirmation: session_id=%s", session_id)
                history = []

        score_response, profile_response, workspace_response = await asyncio.gather(
            score_task,
            profile_task,
            workspace_task,
            return_exceptions=True,
        )

        parsed_score_detail = None
        parsed_init_profile = None
        parsed_planning_summary = None
        batch = None
        if isinstance(score_response, Exception):
            logger.warning("Failed to fetch score detail for pending confirmation: session_id=%s", session_id, exc_info=True)
        elif isinstance(score_response, dict) and score_response.get("code") == 0:
            raw_data = score_response.get("data", {}).get("userScoreDetail", {})
            if raw_data:
                parsed_score_detail = _parse_score_detail_from_backend(raw_data)
                batch = _normalize_batch(raw_data.get("batch") or batch)
        if isinstance(profile_response, Exception):
            logger.warning("Failed to fetch init profile for pending confirmation: session_id=%s", session_id, exc_info=True)
        elif isinstance(profile_response, dict) and profile_response.get("code") == 0:
            raw_profile = profile_response.get("data", {})
            if raw_profile:
                parsed_init_profile = UserProfile.from_backend_format(raw_profile)
        if isinstance(workspace_response, Exception):
            logger.warning("Failed to fetch planning workspace for pending confirmation: session_id=%s", session_id, exc_info=True)
        elif isinstance(workspace_response, dict) and workspace_response.get("code") == 0:
            parsed_planning_summary = PlanningSummary.from_backend_state(workspace_response.get("data", {}))

        active_plan_pending = _pending_confirmation_from_state(pending_state)
        if active_plan_pending is None or active_plan_pending.kind != "plan_mutation":
            return "这次方案调整缺少可执行内容，请重新生成预览。"
        conversation_phase = ConversationPhase.from_pending_confirmation(
            active_plan_pending,
            planning_summary=parsed_planning_summary,
        )
        request_context = RequestContext(
            userid=user_id,
            sessionid=session_id,
            chat_history=[],
            batch=batch,
            score_detail=parsed_score_detail,
            init_profile=parsed_init_profile,
            planning_summary=parsed_planning_summary,
            conversation_phase=conversation_phase,
            allow_explore_inner_llm=False,
            confirmed_via_card=confirmation_entry == "card",
            confirmed_via_pending=True,
            confirmation_entry=confirmation_entry,
        )

        started_at = time.monotonic()
        intent_state_result = None
        intent_apply_note = ""
        if isinstance(intent_payload, dict) and intent_payload.get("selected"):
            effective_batch = _normalize_batch(batch or intent_payload.get("batch") or "01")
            selected_data_for_apply = {
                "selected": intent_payload.get("selected") or [],
                "intentMode": str(intent_payload.get("intentMode") or "constraint").strip() or "constraint",
                "constraintIntentType": str(
                    intent_payload.get("constraintIntentType")
                    or intent_payload.get("constraint_intent_type")
                    or "default"
                ).strip() or "default",
                "batch": effective_batch,
            }
            result_json = await _apply_selected_intents(
                session_id=session_id,
                batch=effective_batch,
                selected_data=selected_data_for_apply,
            )
            try:
                intent_state_result = parse_intent_state_update_result(result_json)
            except Exception:
                logger.warning(
                    "Failed to parse combined plan/intent confirmation result: session_id=%s",
                    session_id,
                    exc_info=True,
                )
                await _mark_pending_confirmation_failed(
                    session_id,
                    pending_state,
                    message_id,
                    pending_id=pending_id,
                    result_code="intent_apply_parse_failed",
                )
                return "这次报考条件没有写入成功，方案暂不调整。请稍后重试，或重新列出待采纳内容。"
            if not getattr(intent_state_result, "applied", False):
                await _mark_pending_confirmation_failed(
                    session_id,
                    pending_state,
                    message_id,
                    pending_id=pending_id,
                    result_code=str(getattr(intent_state_result, "messageCode", None) or "intent_apply_failed"),
                )
                return "这次报考条件没有写入成功，方案暂不调整。请稍后重试，或重新列出待采纳内容。"
            intent_apply_note = "后续报考参考已同步更新，推荐系数和专家优选会按这条要求重新考虑。"

        result_text = await execute_plan_action(SimpleNamespace(deps=request_context), plan_payload)
        result = _parse_tool_return_json(result_text) or {}
        reply = _plan_confirmation_card_applied_reply(action_family, result)
        tool_success = _plan_confirmation_apply_succeeded(result)
        if not tool_success:
            result_kind = str(result.get("result_kind") or "plan_apply_not_applied").strip() or "plan_apply_not_applied"
            await _mark_pending_confirmation_failed(
                session_id,
                pending_state,
                message_id,
                pending_id=pending_id,
                result_code=result_kind,
            )
            emit_pending_event(result="failed", result_code=result_kind)
            _log_conversation_turn_event(
                sessionId=session_id,
                userId=user_id,
                scene="plan",
                routingPath="pending_plan_short_text_confirm" if confirmation_entry == "short_text" else "plan_confirmation_card_confirm",
                pendingType="plan",
                actionFamily=action_family or result.get("action_family"),
                totalDurationMs=int((time.monotonic() - started_at) * 1000),
                status="error",
                errorType=result_kind,
            )
            return _sanitize_reply_for_user(reply or "这次调整没有执行成功，请按当前方案重新生成调整预览后再确认。")
        if intent_apply_note:
            reply = f"{reply}\n\n{intent_apply_note}"
        applied_state = dict(pending_state)
        applied_state["status"] = "applied"
        applied_state["updatedAt"] = datetime.now(timezone.utc).isoformat()
        applied_state["resultKind"] = result.get("result_kind")
        await _save_pending_confirmation_state(session_id, applied_state)
        await _mark_pending_confirmation_message_status(
            session_id,
            message_id,
            pending_id=pending_id,
            status="applied",
        )

        new_messages = [
            ModelRequest(parts=[UserPromptPart(content=user_prompt_content or "[待采纳内容]")]),
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="execute_plan_action",
                        args={"plan_payload": plan_payload},
                        tool_call_id=f"{confirmation_entry}-{action_family or 'plan'}-confirmation",
                    )
                ],
                model_name=f"pending-confirmation-{confirmation_entry}",
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="execute_plan_action",
                        content=result_text,
                        tool_call_id=f"{confirmation_entry}-{action_family or 'plan'}-confirmation",
                    )
                ]
            ),
            ModelResponse(parts=[TextPart(content=reply)], model_name=f"pending-confirmation-{confirmation_entry}"),
        ]
        try:
            history_to_save = list(history)
            history_to_save.extend(new_messages)
            await self.history_store.save(session_id, history_to_save)
        except Exception:
            logger.exception("Failed to save pending confirmation card execution history: session_id=%s", session_id)

        _log_conversation_turn_event(
            sessionId=session_id,
            userId=user_id,
            scene="plan",
            routingPath="pending_plan_short_text_confirm" if confirmation_entry == "short_text" else "plan_confirmation_card_confirm",
            pendingType="plan",
            actionFamily=action_family or result.get("action_family"),
            totalDurationMs=int((time.monotonic() - started_at) * 1000),
            status="success" if tool_success else "error",
            errorType=result.get("result_kind") if result.get("result_kind") == "error" else None,
        )
        emit_pending_event(
            result="applied" if tool_success else "failed",
            result_code=str(result.get("result_kind") or "") or None,
        )
        workspace_refresh_targets = _dedupe_workspace_targets(
            [str(target) for target in (result.get("workspace_refresh_targets") or [])]
        )
        if isinstance(intent_payload, dict) and intent_payload.get("selected"):
            workspace_refresh_targets = [target for target in workspace_refresh_targets if target != "candidate"]
        if workspace_refresh_targets:
            reply = _sanitize_reply_for_user(reply)
            return ChatServiceResponseEnvelope(
                primary=reply,
                followups=[
                    _build_silent_workspace_refresh_response(session_id, target)
                    for target in workspace_refresh_targets
                ],
            )
        return _sanitize_reply_for_user(reply)
