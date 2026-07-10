from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Callable

from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart

from app.agent.base_agent import ProgressCallback
from app.agent.context import (
    PlanningSummary,
    RequestContext,
    ScoreDetail,
    resolve_pending_confirmation,
)
from app.zhiyuan_agent.agent import ZhiyuanAgent
from app.zhiyuan_agent.sandbox import DEFAULT_WARM_PATHS, build_request_sandbox
from app.zhiyuan_agent.tools import confirm_pending as zhiyuan_agent_confirm_pending
from app.models.conversation_phase import ConversationPhase, PendingConfirmation
from app.agent.usage_tracker import UsageTracker
from app.config import HistoryConfig
from app.data.history_store import ChatHistoryStore
from app.data.major_aliases import CATEGORY_PREFERRED_MAJOR_ALIASES
from app.data.message_utils import pydantic_ai_messages_to_dicts
from app.domain.major_entity_resolver import compact_major_text, resolve_major_entity, resolve_major_mentions_from_text
from app.domain import proposal_compiler
from app.domain.region_entity_resolver import normalize_region_names, resolve_region_entity
from app.domain.school_entity_resolver import resolve_school_entity
from app.domain.career_slots import normalize_career_slots, to_career_labels
from app.llm.client import LLMClient
from app.schemas.user_profile import UserProfile
from app.services.profile_manager import _normalize_batch
from app.schemas.ws import WSResponse
from app.sync.state_sync import PlanningStateSync
from app.tools.explore_followup_tool import handle_interest_analysis_action_result
from app.domain.fix_proposal_formatter import _format_fix_proposal_apply_result, _fix_proposal_facts
from app.tools.plan_orchestration_models import (
    CompositePlanProposal,
    PlanGoal,
)
from app.tools.intent_state_tool import (
    ANALYSIS_STAGE_CONFIRMED,
    apply_selected_intents as _apply_selected_intents,
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
    generate_user_goal_planning_fix_proposals,
    get_last_pending_confirmation,
    get_message_by_id,
    get_pending_confirmation,
    get_planning_state,
    get_planning_workspace_state,
    get_user_init_profile,
    get_user_score_detail,
    save_pending_confirmation,
    update_session_tuition_range,
    update_message,
)
from app.util.structured_log import log_event

logger = logging.getLogger(__name__)

_PLAN_PENDING_KINDS = {"plan_mutation", "plan_generation"}
_SUPPORTED_PENDING_KINDS = {"intent_change", *_PLAN_PENDING_KINDS}


def _is_plan_pending_kind(kind: str | None) -> bool:
    return str(kind or "").strip() in _PLAN_PENDING_KINDS


def _pending_type_from_kind(kind: str | None, *, has_active_pending: bool = True) -> str:
    normalized = str(kind or "").strip()
    if normalized == "intent_change":
        return "intent"
    if _is_plan_pending_kind(normalized):
        return "plan"
    if not has_active_pending:
        return "none"
    return "unknown"


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    with contextlib.suppress(TypeError, ValueError):
        return float(raw)
    logger.warning("Invalid %s=%r; using default %.1f", name, raw, default)
    return default


_ZHIYUAN_AGENT_DIRECT_TIMEOUT_SECONDS = max(
    0.0,
    _env_float("ZHIYUAN_AGENT_DIRECT_TIMEOUT_SECONDS", 30.0),
)

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
_USER_REPLY_FORCED_CHOICE_MARKERS = (
    "你现在必须决定",
    "你必须决定",
    "必须做出选择",
    "必须做一个选择",
    "必须选一个",
    "没有第三个选项",
    "你选哪个",
    "请选一个",
    "请明确回复",
    "回复 A 或 B",
    "回复A或B",
)
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
_UNBACKED_PLAN_CONFIRMATION_REPLY = (
    "这轮还没有生成可确认的调整预览，所以不会改动当前方案。"
    "如果你要继续调整，请再发一次具体要求，我会重新定位影响范围并列出调整预览；"
    "只有你点“确认执行”或直接确认当前有效预览后才会执行。"
)
_NO_TOOL_NO_ACTION_BOUNDARY_REPLY = (
    "可以，先按这次思路保留和讨论；这轮不会改动当前方案，也不会写入后续报考参考里的偏好或要求，更不会开始任何方案调整。"
    "下一步如果要正式采用新的想法或调整方案，我会先把要采用的内容或调整预览列清楚，你确认前不会执行。"
)
_ROUTE_OBSERVABILITY_MODEL_NAME = "route-observability"
_INTENT_PREVIEW_TOOL_NAMES = {
    "preview_intent_change",
}
_INTENT_INTEREST_ANALYSIS_TOOL_NAMES = {
    "explore_topic",
}
_READONLY_DIRECT_TOOL_NAMES = {
    "read_state",
    "query_plan",
    "review_plan",
    "explore_topic",
    "compare_entities",
    "answer_policy",
}
_USER_REPLY_ENGLISH_WORD_REPLACEMENTS = (
    (re.compile(r"\s*\bmostly\b\s*", re.IGNORECASE), "基本上"),
    (re.compile(r"\s*\bincreasingly\b\s*", re.IGNORECASE), "越来越"),
    (re.compile(r"\s*\bbaseline\b\s*", re.IGNORECASE), "基准"),
)

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


def _append_turn_observability_messages(
    messages: list[Any],
    turn_event: dict[str, Any] | None,
    *,
    request_context: RequestContext | None = None,
    session_id: str = "",
    user_id: str = "",
    prompt_length: int = 0,
) -> list[Any]:
    return _append_route_observability_message(messages, turn_event)


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


def _iter_route_observability_events(messages: list[Any] | None) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for message in messages or []:
        if not isinstance(message, ModelResponse):
            continue
        for part in getattr(message, "parts", []) or []:
            if not isinstance(part, TextPart):
                continue
            data = _parse_tool_return_json(part.content)
            if isinstance(data, dict) and data.get("type") == "routeObservability":
                events.append(data)
    return events


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


_SUPPORTED_WORKSPACE_ACTION_TARGETS = proposal_compiler.SUPPORTED_WORKSPACE_ACTION_TARGETS


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


def _build_pending_apply_workspace_refresh_response(
    session_id: str,
    target: str,
    *,
    pending_kind: str | None = None,
    action_family: str | None = None,
) -> WSResponse:
    extra_payload: dict[str, Any] | None = None
    if (
        str(target or "").strip() == "review"
        and str(pending_kind or "").strip() == "plan_generation"
        and str(action_family or "").strip() == "regenerate_order"
    ):
        extra_payload = {
            "title": "需要重新审查方案",
            "content": "方案排序已更新，原审查结果可能不再完全准确。请重新审查后再看最新风险和提醒。",
            "actionText": "重新审查",
        }
    return _build_silent_workspace_refresh_response(
        session_id,
        target,
        extra_payload=extra_payload,
    )


def _extract_extra_data_value(response: dict[str, Any] | None, key: str) -> dict[str, Any] | None:
    data = (response or {}).get("data")
    if not isinstance(data, dict):
        return None
    value = data.get(key)
    if value is None:
        value = data.get("dataValue")
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            parsed = None
        value = parsed
    if not isinstance(value, dict):
        return None
    result = dict(value)
    data_version = _as_int(data.get("dataVersion") or data.get("version"))
    if data_version > 0:
        result.setdefault("_extraDataVersion", data_version)
        result.setdefault("dataVersion", data_version)
    return result


async def _load_pending_confirmation_state(session_id: str) -> dict[str, Any] | None:
    try:
        response = await get_last_pending_confirmation(session_id)
    except Exception:
        logger.warning("Failed to load latest pending confirmation state: session_id=%s", session_id, exc_info=True)
        response = None
    state = _extract_extra_data_value(response, "pendingConfirmation")
    if state:
        return state
    try:
        response = await get_pending_confirmation(session_id)
    except Exception:
        logger.warning("Failed to load pending confirmation state: session_id=%s", session_id, exc_info=True)
        return None
    return _extract_extra_data_value(response, "pendingConfirmation")


async def _load_pending_confirmation_state_at_version(
    session_id: str,
    version: int,
) -> dict[str, Any] | None:
    try:
        response = await get_pending_confirmation(session_id, version=version)
    except Exception:
        logger.warning(
            "Failed to load pending confirmation state at version: session_id=%s version=%s",
            session_id,
            version,
            exc_info=True,
        )
        return None
    return _extract_extra_data_value(response, "pendingConfirmation")


def _pending_extra_data_version(state: dict[str, Any] | None) -> int:
    if not isinstance(state, dict):
        return 0
    return _as_int(
        state.get("_extraDataVersion")
        or state.get("dataVersion")
        or state.get("sourceBackendVersion")
        or state.get("source_backend_version")
        or state.get("planningVersion")
        or state.get("planning_version")
    )


def _pending_confirmation_from_state(state: dict[str, Any] | None) -> PendingConfirmation | None:
    """Build runtime pending projection from backend pendingConfirmation state."""
    if not isinstance(state, dict):
        return None
    if str(state.get("status") or "").strip() != "active":
        return None
    kind = str(state.get("kind") or "").strip()
    action_family = str(state.get("actionFamily") or "").strip()
    if kind not in _SUPPORTED_PENDING_KINDS or not action_family:
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
    if _is_plan_pending_kind(kind):
        if action_family == "apply_fix_proposal":
            payload = dict(execution_payload)
        else:
            payload = proposal_compiler.ensure_structured_plan_payload(
                execution_payload,
                action_family=action_family,
            )
            if not proposal_compiler.is_structured_plan_payload(payload):
                return None
        pending = PendingConfirmation(
            kind=kind,
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


def _intent_summary_from_pending_state(state: dict[str, Any] | None) -> str:
    if not isinstance(state, dict) or str(state.get("kind") or "").strip() != "intent_change":
        return ""
    summary = str(state.get("summary") or "").strip()
    if summary:
        return summary
    execution_payload = state.get("executionPayload")
    if not isinstance(execution_payload, dict):
        return ""
    intent_mode = str(execution_payload.get("intentMode") or "preference").strip() or "preference"
    constraint_intent_type = str(
        execution_payload.get("constraintIntentType")
        or execution_payload.get("constraint_intent_type")
        or "default"
    ).strip() or "default"
    merged = execution_payload.get("merged")
    if isinstance(merged, dict) and merged:
        return _summarize_intent_values(
            merged,
            intent_mode=intent_mode,
            constraint_intent_type=constraint_intent_type,
        )
    selected_data = execution_payload.get("selectedData")
    if isinstance(selected_data, dict):
        selected = [item for item in (selected_data.get("selected") or []) if isinstance(item, dict)]
        if selected:
            try:
                merged = merge_selected_values(selected)
            except Exception:
                merged = {}
            if merged:
                return _summarize_intent_values(
                    merged,
                    intent_mode=intent_mode,
                    constraint_intent_type=constraint_intent_type,
                )
    return ""


def _recent_intent_summary_for_no_plan_guard(
    pending_state: dict[str, Any] | None,
    recent_intent_analysis: dict[str, Any] | None,
) -> str:
    pending_summary = _intent_summary_from_pending_state(pending_state)
    if pending_summary and str((pending_state or {}).get("status") or "").strip() in {"active", "applied"}:
        return pending_summary
    if not isinstance(recent_intent_analysis, dict):
        return ""
    return _intent_card_primary_reply_from_preview_payload(recent_intent_analysis).split("：", 1)[-1].split("。", 1)[0].strip()


async def _save_pending_confirmation_state(session_id: str, state: dict[str, Any]) -> None:
    try:
        await save_pending_confirmation(session_id, state, version=_pending_extra_data_version(state))
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


def _positive_int_from_structured_value(value: Any) -> int:
    raw_values = value if isinstance(value, list) else [value] if value is not None else []
    for raw_value in raw_values:
        try:
            amount = int(raw_value)
        except (TypeError, ValueError):
            continue
        if amount > 0:
            return amount
    return 0


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
    tuition_budget = merged.get("tuition_budget") if isinstance(merged.get("tuition_budget"), dict) else {}
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
        to_career_labels(career_intents.get("positive")) or _as_text_list(career_intents.get("positive")),
    )
    add(
        _soft_negative_label("排除方向", intent_mode=intent_mode),
        to_career_labels(career_intents.get("negative")) or _as_text_list(career_intents.get("negative")),
    )
    min_tuition = _positive_int_from_structured_value(
        tuition_budget.get("min_tuition_per_year") or tuition_budget.get("minTuitionPerYear")
    )
    max_tuition = _positive_int_from_structured_value(
        tuition_budget.get("max_tuition_per_year") or tuition_budget.get("maxTuitionPerYear")
    )
    tuition_parts: list[str] = []
    if min_tuition > 0:
        tuition_parts.append(f"每年不低于 {min_tuition} 元")
    if max_tuition > 0:
        tuition_parts.append(f"每年不超过 {max_tuition} 元")
    if tuition_parts:
        parts.append(f"学费预算：{'，'.join(tuition_parts)}")
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


_PRIMARY_INTENT_REQUIREMENT_LABELS = {
    "偏好专业": ("专业要求", "要"),
    "偏好专业类": ("专业要求", "要"),
    "偏好专业门类": ("专业要求", "要"),
    "优先专业": ("专业要求", "要"),
    "可以考虑专业": ("专业要求", "要"),
    "排除专业": ("专业要求", "不要"),
    "排除专业类": ("专业要求", "不要"),
    "排除专业门类": ("专业要求", "不要"),
    "偏好院校": ("院校要求", "要"),
    "排除院校": ("院校要求", "不要"),
    "偏好地域": ("地域要求", "要"),
    "排除地域": ("地域要求", "不要"),
    "发展方向": ("发展方向要求", "要"),
    "排除方向": ("发展方向要求", "不要"),
}


def _rewrite_mixed_intent_summary_for_primary(summary: str) -> tuple[str, bool]:
    parts = [part.strip() for part in str(summary or "").split("；") if part.strip()]
    if not parts:
        return "", False
    grouped: dict[str, dict[str, list[str]]] = {}
    unmatched: list[str] = []
    for part in parts:
        if "：" not in part:
            unmatched.append(part)
            continue
        label, values_text = part.split("：", 1)
        target = _PRIMARY_INTENT_REQUIREMENT_LABELS.get(label.strip())
        if not target:
            unmatched.append(part)
            continue
        group_label, polarity_label = target
        values = [item.strip() for item in re.split(r"[、，,]", values_text) if item.strip()]
        if not values:
            unmatched.append(part)
            continue
        bucket = grouped.setdefault(group_label, {"要": [], "不要": []})
        for value in values:
            if value not in bucket[polarity_label]:
                bucket[polarity_label].append(value)
    rewritten: list[str] = []
    changed = False
    for group_label, values_by_polarity in grouped.items():
        positive = values_by_polarity.get("要") or []
        negative = values_by_polarity.get("不要") or []
        if positive and negative:
            rewritten.append(f"{group_label}：要：{'、'.join(positive)}；不要：{'、'.join(negative)}")
            changed = True
        else:
            for label, values in (("要", positive), ("不要", negative)):
                if values:
                    rewritten.append(f"{group_label}：{label}：{'、'.join(values)}")
    if not changed:
        return summary, False
    return "；".join(rewritten + unmatched), True


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
    summary_text, summary_rewritten = _rewrite_mixed_intent_summary_for_primary(summary_text)
    if summary_text:
        title = "已列出这次报考要求预览" if summary_rewritten or intent_mode == "constraint" else "已列出这次报考想法预览"
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
        ("只保留发展方向：", "career_intents", "positive"),
        ("至少保留发展方向：", "career_intents", "positive"),
        ("发展方向：", "career_intents", "positive"),
        ("排除方向：", "career_intents", "negative"),
        ("不优先发展方向：", "career_intents", "negative"),
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
    if _is_plan_pending_kind(kind):
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


def _semantic_intent_decision_suggests_readonly(decision: dict[str, Any] | None) -> bool:
    if not isinstance(decision, dict):
        return False
    return (
        str(decision.get("decision") or "").strip() in {"analysis_only", "mixed_answer_then_ask"}
        and float(decision.get("confidence") or 0.0) >= 0.7
    )


def _semantic_intent_decision_requires_readonly(decision: dict[str, Any] | None) -> bool:
    if not _semantic_intent_decision_suggests_readonly(decision):
        return False
    if isinstance(decision, dict) and decision.get("honored") is False:
        return False
    return True


def _normalize_admission_path(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    compact = re.sub(r"\s+", "", text).lower()
    if compact in {"strongbase", "strong_base", "strong-base"} or "强基" in text:
        return "strongbase"
    if compact in {"comprehensive", "comprehensive_evaluation", "综合评价", "综评"} or "综评" in text or "综合评价" in text:
        return "comprehensive_evaluation"
    if "专项" in text:
        return "special_program"
    return text


def _admission_path_display(value: Any) -> str:
    normalized = _normalize_admission_path(value)
    if normalized == "strongbase":
        return "强基路径"
    if normalized == "comprehensive_evaluation":
        return "综评路径"
    if normalized == "special_program":
        return "专项路径"
    return normalized


def _intent_preview_payload_entity_kinds(payload: dict[str, Any] | None) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    items = payload.get("items")
    if not isinstance(items, list):
        items = []
    merged = _merge_intent_preview_item_values([item for item in items if isinstance(item, dict)])
    kinds: set[str] = set()
    if isinstance(merged.get("major_intents"), dict) and merged.get("major_intents"):
        kinds.add("major")
    if isinstance(merged.get("school_intents"), dict) and merged.get("school_intents"):
        kinds.add("school")
    if isinstance(merged.get("city_intents"), dict) and merged.get("city_intents"):
        kinds.add("region")
    if isinstance(merged.get("career_intents"), dict) and merged.get("career_intents"):
        kinds.add("career")
    if _normalize_admission_path(payload.get("admissionPath") or payload.get("admission_path")):
        kinds.add("admission_path")
    return kinds


def _semantic_intent_decision_entity_kinds(decision: dict[str, Any] | None) -> set[str]:
    if not _semantic_decision_requests_intent_preview(decision):
        return set()
    kinds: set[str] = set()
    for span in decision.get("entityPolaritySpans") or []:
        if not isinstance(span, dict):
            continue
        entity_type = str(span.get("entityType") or "").strip()
        if entity_type in {"major", "school", "region", "career"}:
            kinds.add(entity_type)
        elif entity_type in {"admissionPath", "admission_path", "path"}:
            kinds.add("admission_path")
    if _normalize_admission_path(decision.get("admissionPath") or decision.get("admission_path")):
        kinds.add("admission_path")
    return kinds


def _intent_preview_payload_mismatches_semantic_decision(
    payload: dict[str, Any] | None,
    decision: dict[str, Any] | None,
) -> bool:
    decision_kinds = _semantic_intent_decision_entity_kinds(decision)
    if not decision_kinds:
        return False
    payload_kinds = _intent_preview_payload_entity_kinds(payload)
    return not decision_kinds.issubset(payload_kinds)


def _intent_preview_payload_from_semantic_decision(
    session_id: str,
    decision: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not _semantic_decision_requests_intent_preview(decision):
        return None
    constraint_intent_type = str(decision.get("constraintIntentType") or "default").strip() or "default"
    intent_mode = "constraint" if constraint_intent_type in {"only_keep", "must_have"} else "preference"
    major_values: list[str] = []
    school_values: list[str] = []
    region_values: list[str] = []
    career_values: list[str] = []
    negative_major_values: list[str] = []
    negative_school_values: list[str] = []
    negative_region_values: list[str] = []
    negative_career_values: list[str] = []

    for span in decision.get("entityPolaritySpans") or []:
        if not isinstance(span, dict):
            continue
        entity = str(span.get("entity") or "").strip()
        if not entity:
            continue
        entity_type = str(span.get("entityType") or "").strip()
        polarity = str(span.get("polarity") or "").strip()
        strength = str(span.get("strength") or "").strip()
        negative = polarity == "negative" or strength in {"exclude_soft", "exclude_hard"}
        if entity_type == "major":
            (negative_major_values if negative else major_values).append(entity)
        elif entity_type == "school":
            (negative_school_values if negative else school_values).append(entity)
        elif entity_type == "region":
            (negative_region_values if negative else region_values).append(entity)
        elif entity_type == "career":
            (negative_career_values if negative else career_values).append(entity)

    def _dedupe(values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            if value and value not in result:
                result.append(value)
        return result

    major_values = _dedupe(major_values)
    school_values = _dedupe(_normalize_school_intent_names(_dedupe(school_values)))
    region_values = _dedupe(region_values)
    career_values = _dedupe(career_values)
    negative_major_values = _dedupe(negative_major_values)
    negative_school_values = _dedupe(_normalize_school_intent_names(_dedupe(negative_school_values)))
    negative_region_values = _dedupe(negative_region_values)
    negative_career_values = _dedupe(negative_career_values)

    items: list[dict[str, Any]] = []
    if major_values:
        items.append({"content": f"偏好专业：{'、'.join(major_values)}", "selected": True, "value": {"major_intents": {"level3": major_values}}})
    if negative_major_values:
        items.append({"content": f"排除专业：{'、'.join(negative_major_values)}", "selected": True, "value": {"major_intents": {"negative_level3": negative_major_values}}})
    if school_values:
        items.append({"content": f"偏好院校：{'、'.join(school_values)}", "selected": True, "value": {"school_intents": {"colleges": school_values}}})
    if negative_school_values:
        items.append({"content": f"排除院校：{'、'.join(negative_school_values)}", "selected": True, "value": {"school_intents": {"negative_colleges": negative_school_values}}})
    if region_values:
        items.append({"content": f"偏好地域：{'、'.join(region_values)}", "selected": True, "value": {"city_intents": {"area": region_values}}})
    if negative_region_values:
        items.append({"content": f"排除地域：{'、'.join(negative_region_values)}", "selected": True, "value": {"city_intents": {"negative_area": negative_region_values}}})
    if career_values:
        items.append({"content": f"发展方向：{'、'.join(career_values)}", "selected": True, "value": {"career_intents": {"positive": career_values}}})
    if negative_career_values:
        items.append({"content": f"排除方向：{'、'.join(negative_career_values)}", "selected": True, "value": {"career_intents": {"negative": negative_career_values}}})
    admission_path = _normalize_admission_path(decision.get("admissionPath") or decision.get("admission_path"))
    if not items and not admission_path:
        return None
    summary_parts: list[str] = []
    if items:
        try:
            merged = merge_selected_values([item["value"] for item in items if isinstance(item.get("value"), dict)])
        except Exception:
            merged = {}
        summary = _summarize_intent_values(
            merged,
            intent_mode=intent_mode,
            constraint_intent_type=constraint_intent_type,
        )
        if summary:
            summary_parts.append(summary)
    path_display = _admission_path_display(admission_path)
    if path_display:
        summary_parts.append(path_display)
    return {
        "status": "ready",
        "sessionId": session_id,
        "title": "确认这条报考想法",
        "intentMode": intent_mode,
        "constraintIntentType": constraint_intent_type,
        "analysisStage": "confirmed",
        "items": items,
        "existingItems": [],
        "admissionPath": admission_path,
        "message": "；".join(summary_parts),
    }


def _align_intent_preview_payload_with_semantic_decision(
    *,
    session_id: str,
    payload: dict[str, Any] | None,
    semantic_decision: dict[str, Any] | None,
    observability: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not _intent_preview_payload_mismatches_semantic_decision(payload, semantic_decision):
        return payload
    semantic_payload = _intent_preview_payload_from_semantic_decision(
        session_id,
        semantic_decision,
    )
    if semantic_payload is None:
        return payload
    if isinstance(observability, dict):
        observability["latestIntentPreviewPayload"] = semantic_payload
        observability["intentPreviewPayloadSource"] = "semantic_side_effect_decision"
    return semantic_payload


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
    paths = [
        ("major_intents", "level3"),
        ("major_intents", "level2"),
        ("major_intents", "level1"),
        ("school_intents", "colleges"),
        ("city_intents", "province"),
        ("city_intents", "city"),
        ("city_intents", "area"),
        ("career_intents", "positive"),
    ]
    return _intent_payload_has_any_value(payload, paths)


def _intent_payload_has_negative_value(payload: dict[str, Any] | None) -> bool:
    paths = [
        ("major_intents", "negative_level3"),
        ("major_intents", "negative_level2"),
        ("major_intents", "negative_level1"),
        ("major_intents", "negative"),
        ("school_intents", "negative_colleges"),
        ("city_intents", "negative_province"),
        ("city_intents", "negative_city"),
        ("city_intents", "negative_area"),
        ("career_intents", "negative"),
        ("physical_constraints", "special_limits"),
        ("physicalConstraints", "specialLimits"),
    ]
    return _intent_payload_has_any_value(payload, paths)


def _intent_preview_missing_required_constraint_scope(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    try:
        preview = parse_intent_analysis_payload(
            json.dumps(_normalize_intent_preview_payload_for_parse(payload), ensure_ascii=False)
        )
    except Exception:
        return False
    raw_constraint_type = str(getattr(preview, "constraintIntentType", "") or "").strip()
    if raw_constraint_type not in {"only_keep", "must_have"}:
        return False
    selected_values = [
        item.value
        for item in preview.items
        if item.selected and isinstance(item.value, dict) and item.value
    ]
    if not selected_values and preview.status != "existing_only":
        return True
    if not selected_values:
        selected_values = [
            item.value
            for item in preview.existingItems
            if isinstance(item.value, dict) and item.value
        ]
    try:
        merged = merge_selected_values(selected_values)
    except Exception:
        return True
    return not _intent_payload_has_positive_value(merged)


def _intent_preview_incomplete_constraint_reply(payload: dict[str, Any] | None) -> str:
    constraint_type = ""
    if isinstance(payload, dict):
        constraint_type = str(payload.get("constraintIntentType") or payload.get("constraint_intent_type") or "").strip()
    if constraint_type == "must_have":
        return "我理解你是想让方案里至少保留某个方向，但这次没有稳定识别出具体要保留的专业、院校或地域。请直接补充要保留的范围，我再给你列出可采纳内容。"
    return "我理解你是想把后续范围收紧，但这次没有稳定识别出具体要保留的专业、院校或地域。请直接补充要保留的范围，我再给你列出可采纳内容。"


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
    compiled_sink_metadata: dict[str, Any] | None = None,
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
    compiled_proposal_id = ""
    if isinstance(compiled_sink_metadata, dict):
        compiled_proposal_id = str(compiled_sink_metadata.get("compiledProposalId") or "").strip()
    if compiled_proposal_id:
        state["compiledProposalId"] = compiled_proposal_id
        state["compilerSink"] = {
            "compiledProposalId": compiled_proposal_id,
            "sinkType": str(compiled_sink_metadata.get("sinkType") or "intent").strip() or "intent",
        }
        state["executionPayload"]["compiledProposalId"] = compiled_proposal_id
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


def _scope_payload(entity_type: str, values: list[str], *, scope_level: str | None = None) -> dict[str, Any] | None:
    deduped = list(dict.fromkeys(str(value or "").strip() for value in values if str(value or "").strip()))
    if not deduped:
        return None
    payload: dict[str, Any] = {"entity_type": entity_type, "values": deduped}
    if scope_level:
        payload["scope_level"] = scope_level
    return payload


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
    region_province_scope = _scope_payload(
        "region",
        normalize_region_names(city_intents.get("province"), expected_level="province"),
        scope_level="province",
    )
    region_city_scope = _scope_payload(
        "region",
        normalize_region_names(city_intents.get("city"), expected_level="city"),
        scope_level="city",
    )
    region_area_scope = _scope_payload(
        "region",
        normalize_region_names(city_intents.get("area"), expected_level="area"),
        scope_level="area",
    )
    for scope in (major_scope, school_scope, region_province_scope, region_city_scope, region_area_scope):
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
    region_province_scope = _scope_payload(
        "region",
        normalize_region_names(city_intents.get("negative_province"), expected_level="province"),
        scope_level="province",
    )
    region_city_scope = _scope_payload(
        "region",
        normalize_region_names(city_intents.get("negative_city"), expected_level="city"),
        scope_level="city",
    )
    region_area_scope = _scope_payload(
        "region",
        normalize_region_names(city_intents.get("negative_area"), expected_level="area"),
        scope_level="area",
    )
    for scope in (major_scope, school_scope, region_province_scope, region_city_scope, region_area_scope):
        if scope is not None:
            scopes.append(scope)
    return scopes


def _constraint_goal_type(constraint_intent_type: str) -> str:
    return proposal_compiler.structured_goal_type_from_constraint_intent_type(constraint_intent_type)


@dataclass
class _UserGoalFixConfirmationAttempt:
    fallback_to_intent: bool = False
    blocked_by_compiled_contract: bool = False
    fallback_mechanism_line: str = ""
    fallback_detail_lines: list[str] = field(default_factory=list)


@dataclass
class _UserGoalFixCandidate:
    proposal: dict[str, Any]
    source_version_guard: int
    user_goal_request: dict[str, Any]
    intent_payload: dict[str, Any] | None
    summary: str


@dataclass
class _IntentPreviewCandidate:
    payload: dict[str, Any]
    preview: Any
    selected_values: list[dict[str, Any]]
    merged: dict[str, Any]
    intent_mode: str
    constraint_intent_type: str
    existing_merged: dict[str, Any]
    selected_display_summary: str
    existing_summary: str
    summary: str


@dataclass
class _RuntimeCompiledPendingResult:
    card: WSResponse | None = None
    primary_reply: str = ""
    source: str = ""
    plan_includes_intent_update: bool = False
    workspace_refresh_targets: list[str] = field(default_factory=list)
    blocked_reasons: list[str] = field(default_factory=list)


def _compiled_workspace_refresh_targets(
    compiled: dict[str, Any] | None,
    *,
    fallback_targets: list[str] | None = None,
) -> list[str]:
    if not isinstance(compiled, dict):
        return _dedupe_workspace_targets(fallback_targets or [])
    raw_targets = compiled.get("workspaceRefreshTargets") or compiled.get("workspace_refresh_targets")
    if not isinstance(raw_targets, list) or not raw_targets:
        execution_payload = compiled.get("executionPayload")
        if isinstance(execution_payload, dict):
            target = str(execution_payload.get("targetView") or "").strip()
            raw_targets = [target] if target else []
        else:
            raw_targets = []
    targets = _dedupe_workspace_targets(str(target) for target in raw_targets)
    if targets:
        return targets
    return _dedupe_workspace_targets(fallback_targets or [])


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


async def _constraint_user_goal_fix_candidate_from_preview(
    session_id: str,
    *,
    selected_data: dict[str, Any],
    merged: dict[str, Any],
    batch: str,
    summary: str,
    constraint_intent_type: str = "default",
    attempt: _UserGoalFixConfirmationAttempt | None = None,
) -> _UserGoalFixCandidate | None:
    composite_proposal = _build_constraint_composite_proposal_payload(
        {},
        merged=merged,
        selected_data=selected_data,
        constraint_intent_type=constraint_intent_type,
        batch=batch,
        summary=summary,
    )
    if not isinstance(composite_proposal, dict):
        return None
    planning_version = _as_int(composite_proposal.get("source_version"))
    if planning_version <= 0:
        try:
            state_resp = await get_planning_state(session_id)
            planning_version = _as_int(((state_resp or {}).get("data") or {}).get("version"))
        except Exception:
            logger.warning("Failed to load planning state for user-goal proposal: session_id=%s", session_id, exc_info=True)
            planning_version = 0
    if planning_version <= 0:
        return None
    user_goal_request = proposal_compiler.build_structured_user_goal_fix_proposal_request(
        composite_proposal.get("goal") if isinstance(composite_proposal.get("goal"), dict) else {},
        planning_version,
        context={"source": "chat_service_constraint_confirmation"},
        evidence_source="confirmed_intent",
    )
    if not user_goal_request:
        return None
    try:
        proposal_result = await generate_user_goal_planning_fix_proposals(1, session_id, user_goal_request)
    except Exception:
        logger.warning(
            "Failed to generate user-goal plan proposal: session_id=%s summary=%s",
            session_id,
            summary,
            exc_info=True,
        )
        return None
    if proposal_result.get("code") != 0:
        return None
    data = proposal_result.get("data")
    if not isinstance(data, dict):
        return None
    selection = proposal_compiler.select_user_goal_fix_proposal(
        data,
        goal_type=_constraint_goal_type(constraint_intent_type),
        fallback_source_version_guard=planning_version,
    )
    if not isinstance(selection.proposal, dict):
        if attempt is not None:
            attempt.fallback_to_intent = selection.fallback_proposal is not None
            attempt.fallback_mechanism_line, attempt.fallback_detail_lines = _constraint_plan_confirmation_fallback(
                selection.fallback_proposal,
                constraint_intent_type=constraint_intent_type,
            )
        return None
    return _UserGoalFixCandidate(
        proposal=selection.proposal,
        source_version_guard=selection.source_version_guard,
        user_goal_request=user_goal_request,
        intent_payload=selected_data,
        summary=summary,
    )


async def _create_pending_fix_confirmation_result_from_user_goal_candidate(
    session_id: str,
    candidate: _UserGoalFixCandidate,
    *,
    attempt: _UserGoalFixConfirmationAttempt | None = None,
) -> _RuntimeCompiledPendingResult:
    compiled = proposal_compiler.compile_user_goal_fix_proposal(
        session_id=session_id,
        proposal=candidate.proposal,
        source_version_guard=candidate.source_version_guard,
        user_goal_request=candidate.user_goal_request,
        intent_payload=candidate.intent_payload,
        summary=candidate.summary,
    )
    contract_ok, contract_reasons = proposal_compiler.fix_proposal_sink_contract(compiled)
    if not contract_ok:
        if attempt is not None:
            attempt.blocked_by_compiled_contract = True
        logger.info(
            "Block user-goal fix pending before sink: session_id=%s reasons=%s proposal_id=%s",
            session_id,
            contract_reasons,
            proposal_compiler.proposal_id(candidate.proposal),
        )
        return _RuntimeCompiledPendingResult(
            source="user_goal_fix_proposal",
            blocked_reasons=["compiled_fix_sink_blocked", *contract_reasons],
        )
    compiled_sink_metadata = {
        "compiledProposalId": compiled["compiledProposalId"],
        "sinkType": "fix_proposal",
    }
    card = await _create_pending_fix_proposal_confirmation_response(
        session_id,
        candidate.proposal,
        source_version_guard=candidate.source_version_guard,
        proposal_source="user_goal",
        user_goal_request=candidate.user_goal_request,
        intent_payload=candidate.intent_payload,
        compiled_sink_metadata=compiled_sink_metadata,
    )
    if card is None:
        return _RuntimeCompiledPendingResult(
            source="user_goal_fix_proposal",
            blocked_reasons=["compiled_fix_pending_sink_returned_empty"],
        )
    return _RuntimeCompiledPendingResult(
        card=card,
        source="user_goal_fix_proposal",
        workspace_refresh_targets=_compiled_workspace_refresh_targets(
            compiled,
            fallback_targets=["ordered"],
        ),
    )


def _merge_existing_intent_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    try:
        preview = parse_intent_analysis_payload(json.dumps(payload, ensure_ascii=False))
    except Exception:
        return {}
    return _merge_intent_preview_item_values(list(preview.existingItems))


async def _create_pending_intent_confirmation_response(
    session_id: str,
    *,
    selected_data: dict[str, Any],
    merged: dict[str, Any],
    intent_mode: str,
    batch: str,
    fallback_mechanism_line: str = "",
    fallback_detail_lines: list[str] | None = None,
    summary_override: str = "",
    existing_summary: str = "",
    impact_payload: dict[str, Any] | None = None,
    compiled_sink_metadata: dict[str, Any] | None = None,
) -> ChatServiceResponseEnvelope:
    compiled_proposal_id = ""
    if isinstance(compiled_sink_metadata, dict):
        compiled_proposal_id = str(compiled_sink_metadata.get("compiledProposalId") or "").strip()
    if not compiled_proposal_id:
        logger.warning(
            "Block intent pending sink without compiled proposal: session_id=%s intent_mode=%s",
            session_id,
            intent_mode,
        )
        return ChatServiceResponseEnvelope(primary="", followups=[])
    replaced_pending = await _load_pending_confirmation_state(session_id)
    raw_constraint_intent_type = selected_data.get("constraintIntentType") or selected_data.get("constraint_intent_type")
    selected_values = [
        item
        for item in (selected_data.get("selected") if isinstance(selected_data, dict) else []) or []
        if isinstance(item, dict) and item
    ]
    intent_resolution = proposal_compiler.resolve_intent_select_input(
        selected_values=selected_values,
        merged=merged,
        intent_mode=intent_mode,
        raw_constraint_intent_type=str(raw_constraint_intent_type or "default"),
    )
    if not intent_resolution.allowed:
        logger.info(
            "Skip pending intent confirmation before sink with invalid compiled input: session_id=%s constraint=%s reasons=%s merged=%s",
            session_id,
            raw_constraint_intent_type,
            intent_resolution.blocking_reasons,
            merged,
        )
        return ChatServiceResponseEnvelope(primary="", followups=[])
    intent_mode = intent_resolution.intent_mode
    constraint_intent_type = intent_resolution.constraint_intent_type
    mode_text = "要求" if intent_mode == "constraint" else "偏好"
    summary = str(summary_override or "").strip() or _display_summary_from_intent_payload(selected_data) or _summarize_intent_values(
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
        compiled_sink_metadata=compiled_sink_metadata,
    )
    await _save_pending_confirmation_state(session_id, pending_state)
    card_content = _format_intent_card_content(summary, existing_summary=existing_summary)
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
            impact_payload if isinstance(impact_payload, dict) else {
                **merged,
                "constraintIntentType": constraint_intent_type,
            },
            intent_mode=intent_mode,
            fallback_mechanism_line=fallback_mechanism_line,
            fallback_detail_lines=fallback_detail_lines,
        ),
    }
    return ChatServiceResponseEnvelope(
        primary=_intent_card_primary_reply(summary, intent_mode=intent_mode, existing_summary=existing_summary),
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
    subject_list: list[str] = []
    for item in raw_data.get("subjectList", []) or []:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
        else:
            name = str(item or "").strip()
        if name:
            subject_list.append(name)
    sex_raw = raw_data.get("sex")
    sex_name = sex_raw.get("name", "") if isinstance(sex_raw, dict) else str(sex_raw or "")
    return ScoreDetail(
        province=province_name,
        total_score=int(raw_data.get("totalScore") or raw_data.get("total_score") or 0),
        subject_list=subject_list,
        sex=sex_name,
        volunteer_model=str(raw_data.get("volunteerModel") or raw_data.get("volunteer_model") or "major"),
    )


def _coerce_score_detail(raw_score_detail: Any) -> ScoreDetail | None:
    if isinstance(raw_score_detail, ScoreDetail):
        return raw_score_detail
    if not isinstance(raw_score_detail, dict) or not raw_score_detail:
        return None
    raw_data = raw_score_detail.get("userScoreDetail")
    nested_data = raw_score_detail.get("data")
    if not isinstance(raw_data, dict) and isinstance(nested_data, dict):
        raw_data = nested_data.get("userScoreDetail")
    if not isinstance(raw_data, dict):
        raw_data = raw_score_detail
    return _parse_score_detail_from_backend(raw_data)


async def _create_pending_intent_confirmation_result_from_preview_payload(
    session_id: str,
    payload: dict[str, Any] | None,
) -> _RuntimeCompiledPendingResult:
    """Create a unified pending card from structured intent preview output."""
    candidate = _intent_preview_candidate_from_payload(session_id, payload)
    if candidate is None:
        return _RuntimeCompiledPendingResult(
            source="intent_preview_payload",
            blocked_reasons=["missing_intent_preview_candidate"],
        )
    batch = await _resolve_session_batch(session_id)
    selected_data = _selected_data_from_intent_preview_candidate(candidate, batch=batch)
    plan_attempt = _UserGoalFixConfirmationAttempt()
    plan_selected_data = _selected_data_with_existing_positive_context(
        selected_data,
        candidate.existing_merged,
    )
    if candidate.intent_mode == "constraint":
        fix_candidate = await _constraint_user_goal_fix_candidate_from_preview(
            session_id,
            selected_data=plan_selected_data,
            merged=candidate.merged,
            batch=batch,
            summary=candidate.summary,
            constraint_intent_type=candidate.constraint_intent_type,
            attempt=plan_attempt,
        )
        if fix_candidate is not None:
            fix_result = await _create_pending_fix_confirmation_result_from_user_goal_candidate(
                session_id,
                fix_candidate,
                attempt=plan_attempt,
            )
            if fix_result.card is not None:
                return fix_result
        if plan_attempt.blocked_by_compiled_contract:
            return _RuntimeCompiledPendingResult(
                source="intent_preview_payload",
                blocked_reasons=["compiled_plan_fix_blocked"],
            )
    compiled = proposal_compiler.compile_intent_preview_proposal(
        session_id=session_id,
        selected_data=selected_data,
        merged=candidate.merged,
        intent_mode=candidate.intent_mode,
        batch=batch,
        summary=candidate.summary,
        constraint_intent_type=candidate.constraint_intent_type,
    )
    compiled_sink_metadata = proposal_compiler.intent_sink_metadata_or_none(
        compiled,
        session_id=session_id,
        source="intent_preview_payload",
    )
    if compiled_sink_metadata is None:
        return _RuntimeCompiledPendingResult(
            source="intent_preview_payload",
            blocked_reasons=["compiled_intent_sink_blocked"],
        )
    intent_response = await _create_pending_intent_confirmation_response(
        session_id,
        selected_data=selected_data,
        merged=candidate.merged,
        intent_mode=candidate.intent_mode,
        batch=batch,
        fallback_mechanism_line=plan_attempt.fallback_mechanism_line,
        fallback_detail_lines=plan_attempt.fallback_detail_lines,
        summary_override=candidate.summary,
        existing_summary=candidate.existing_summary,
        impact_payload=candidate.payload,
        compiled_sink_metadata=compiled_sink_metadata,
    )
    for followup in intent_response.followups:
        if isinstance(followup, WSResponse) and followup.type == "pendingConfirmationCard":
            return _RuntimeCompiledPendingResult(
                card=followup,
                source="intent_preview_payload",
            )
    return _RuntimeCompiledPendingResult(
        source="intent_preview_payload",
        blocked_reasons=["intent_pending_sink_returned_empty"],
    )


def _intent_preview_candidate_from_payload(
    session_id: str,
    payload: dict[str, Any] | None,
) -> _IntentPreviewCandidate | None:
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
    raw_constraint_intent_type = getattr(preview, "constraintIntentType", "default")
    intent_resolution = proposal_compiler.resolve_intent_preview_input(
        selected_values=selected_values,
        merged=merged,
        intent_mode=intent_mode,
        raw_constraint_intent_type=str(raw_constraint_intent_type or "default"),
    )
    if not intent_resolution.allowed:
        logger.info(
            "Skip intent preview card before compiled input: session_id=%s constraint=%s reasons=%s merged=%s",
            session_id,
            raw_constraint_intent_type,
            intent_resolution.blocking_reasons,
            merged,
        )
        return None
    constraint_intent_type = intent_resolution.constraint_intent_type
    intent_mode = intent_resolution.intent_mode
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
    admission_path_display = _admission_path_display(
        payload.get("admissionPath") or payload.get("admission_path")
    )
    if admission_path_display and admission_path_display not in summary:
        summary = f"{summary}；{admission_path_display}" if summary else admission_path_display
    return _IntentPreviewCandidate(
        payload=payload,
        preview=preview,
        selected_values=selected_values,
        merged=merged,
        intent_mode=intent_mode,
        constraint_intent_type=constraint_intent_type,
        existing_merged=existing_merged,
        selected_display_summary=selected_display_summary,
        existing_summary=existing_summary,
        summary=summary,
    )


def _selected_data_from_intent_preview_candidate(
    candidate: _IntentPreviewCandidate,
    *,
    batch: str,
) -> dict[str, Any]:
    selected_data = {
        "selected": candidate.selected_values,
        "intentMode": candidate.intent_mode,
        "constraintIntentType": candidate.constraint_intent_type,
        "batch": batch,
    }
    if candidate.selected_display_summary:
        selected_data["displaySummary"] = candidate.selected_display_summary
    admission_path = _normalize_admission_path(
        candidate.payload.get("admissionPath") or candidate.payload.get("admission_path")
    )
    if admission_path:
        selected_data["admissionPath"] = admission_path
    return selected_data


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


def _tool_calls_are_readonly_explore_or_compare(messages: list[Any] | None) -> bool:
    tool_names = [str(part.tool_name or "").strip() for part in _iter_tool_call_parts(messages)]
    if not tool_names:
        return False
    readonly_tools = {"explore_topic", "compare_entities", "answer_policy"}
    return all(name in readonly_tools for name in tool_names)


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


def _score_detail_ready_for_generate_plan(score_detail: ScoreDetail | None) -> bool:
    if score_detail is None:
        return False
    return bool(
        str(getattr(score_detail, "province", "") or "").strip()
        and _as_int(getattr(score_detail, "total_score", 0)) > 0
        and [item for item in getattr(score_detail, "subject_list", []) or [] if str(item or "").strip()]
    )


async def _load_session_score_detail_for_generation(session_id: str) -> ScoreDetail | None:
    try:
        score_response = await get_user_score_detail(session_id)
    except Exception:
        logger.warning(
            "Failed to load score detail before generate-plan pending sink: session_id=%s",
            session_id,
            exc_info=True,
        )
        return None
    if not isinstance(score_response, dict) or score_response.get("code") != 0:
        return None
    raw_data = score_response.get("data", {}).get("userScoreDetail", {})
    if not isinstance(raw_data, dict) or not raw_data:
        return None
    return _parse_score_detail_from_backend(raw_data)


def _build_fix_proposal_pending_state(
    session_id: str,
    proposal: dict[str, Any],
    *,
    source_version_guard: int,
    proposal_source: str = "review_check",
    user_goal_request: dict[str, Any] | None = None,
    intent_payload: dict[str, Any] | None = None,
    replaced_pending: dict[str, Any] | None = None,
    compiled_sink_metadata: dict[str, Any] | None = None,
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
    compiled_proposal_id = ""
    if isinstance(compiled_sink_metadata, dict):
        compiled_proposal_id = str(compiled_sink_metadata.get("compiledProposalId") or "").strip()
    if compiled_proposal_id:
        state["compiledProposalId"] = compiled_proposal_id
        state["compilerSink"] = {
            "compiledProposalId": compiled_proposal_id,
            "sinkType": str(compiled_sink_metadata.get("sinkType") or "fix_proposal").strip() or "fix_proposal",
        }
        state["executionPayload"]["compiledProposalId"] = compiled_proposal_id
    if replaced_pending and replaced_pending.get("pendingId"):
        state["replacesPendingId"] = replaced_pending.get("pendingId")
    return state


def _normalize_fix_proposal_user_text(text: str) -> str:
    normalized = str(text or "").replace("修复建议", "处理建议").replace("修复", "处理").strip()
    replacements = (
        ("处理高收费志愿", "高收费志愿"),
        ("处理高收费", "高收费志愿"),
        ("处理中外合作办学项目", "中外合作项目"),
        ("处理中外合作", "中外合作项目"),
        ("处理非意向托底专业", "非意向兜底专业"),
        ("处理非意向托底", "非意向兜底专业"),
        ("处理数量校验", "补足志愿数量"),
        ("处理录取率梯度断层", "补齐录取率梯度"),
        ("处理录取率倒挂", "调整录取率顺序"),
        ("处理兜底专业不足", "补兜底专业"),
        ("处理组内安全垫不足", "补兜底专业"),
        ("数量校验", "志愿数量"),
        ("冲稳保配比暂时无法自动处理", "冲稳保结构暂时还调不齐"),
        ("录取率梯度断层暂时无法自动处理", "录取率梯度暂时还补不齐"),
        ("暂时无法自动补齐", "暂时还补不齐"),
        ("暂时无法自动处理", "暂时还不能直接处理"),
    )
    for source, target in replacements:
        normalized = normalized.replace(source, target)
    return normalized


def _clean_fix_proposal_title(value: Any) -> str:
    title = _clean_review_fallback_text(value)
    title = re.sub(r"(?:需要你先取舍或放宽条件|需要你先决定取舍或放宽条件)$", "", title).strip()
    title = re.sub(r"(?:暂时还?不能直接处理|暂时还?补不齐|暂时无法自动处理|暂时无法自动补齐)$", "", title).strip()
    title = re.sub(r"(?:暂时|当前)$", "", title).strip()
    if title in {"补足志愿数量", "志愿数量"}:
        return "志愿数量"
    if title in {"补兜底专业", "兜底专业", "兜底"}:
        return "兜底专业"
    return title


def _fix_proposal_action_details(proposal: dict[str, Any], limit: int = 2) -> list[str]:
    details: list[str] = []
    seen: set[str] = set()
    for action in proposal.get("actions") or []:
        if not isinstance(action, dict):
            continue
        detail = _normalize_user_facing_terms(
            _normalize_fix_proposal_user_text(str(action.get("detail") or "").strip())
        )
        if not detail or "->" not in detail:
            continue
        compact = _compact_plan_reply_text(detail)
        if compact in seen:
            continue
        details.append(detail)
        seen.add(compact)
        if len(details) >= limit:
            break
    return details


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
    action_details = _fix_proposal_action_details(proposal)
    if action_details:
        lines.append(f"- 替换预览：{'；'.join(action_details)}")
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
    compiled_sink_metadata: dict[str, Any] | None = None,
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
        compiled_sink_metadata=compiled_sink_metadata,
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


_LOW_PRIORITY_LOG_ACTION_FAMILIES = {
    "query_state",
    "query_ordered",
    "query_candidates",
}


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


def _enforce_single_pending_confirmation_followup(followups: list[WSResponse]) -> list[WSResponse]:
    pending_indexes = [
        index
        for index, item in enumerate(followups)
        if isinstance(item, WSResponse) and item.type == "pendingConfirmationCard"
    ]
    if len(pending_indexes) <= 1:
        return followups
    keep_index = pending_indexes[-1]
    return [
        item
        for index, item in enumerate(followups)
        if index == keep_index or index not in pending_indexes
    ]


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


def _record_observability_duration(
    request_context: RequestContext,
    key: str,
    duration_ms: int,
) -> None:
    observability = getattr(request_context, "agent_observability", None)
    if not isinstance(observability, dict):
        return
    value = max(0, int(duration_ms))
    current = observability.get(key)
    if isinstance(current, (int, float)):
        observability[key] = int(current) + value
    else:
        observability[key] = value


def _increment_observability_counter(
    request_context: RequestContext,
    key: str,
) -> None:
    observability = getattr(request_context, "agent_observability", None)
    if not isinstance(observability, dict):
        return
    current = observability.get(key)
    observability[key] = int(current) + 1 if isinstance(current, (int, float)) else 1


def _observability_timing_fields(request_context: RequestContext) -> dict[str, Any]:
    observability = getattr(request_context, "agent_observability", None)
    fields: dict[str, Any] = {}
    if not isinstance(observability, dict):
        observability = {}
    timing_keys = (
        "intentEntityProfileDurationMs",
        "intentSideEffectDurationMs",
    )
    fields.update(
        {
            key: int(observability[key])
            for key in timing_keys
            if isinstance(observability.get(key), (int, float))
        }
    )
    return fields


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


def _latest_readonly_plan_query_reply(messages: list[Any] | None) -> str | None:
    for part in reversed(_iter_tool_return_parts(messages)):
        if part.tool_name != "query_plan":
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
        if part.tool_name != "answer_policy":
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


def _turn_has_readonly_explore_result(messages: list[Any] | None) -> bool:
    return bool(_latest_readonly_explore_reply(messages))


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

        returned_data = returned.get("data") if isinstance(returned.get("data"), dict) else {}
        returned_result = returned_data.get("result") if isinstance(returned_data.get("result"), dict) else {}
        action_family = str(
            args.get("action_family")
            or returned.get("action_family")
            or returned_data.get("action_family")
            or returned_result.get("action_family")
            or ""
        ).strip()
        stage = str(args.get("current_stage") or returned.get("stage") or "").strip()
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


def _latest_confirm_pending_tool_result(
    tool_calls: list[ToolCallPart],
    tool_returns: list[ToolReturnPart],
) -> dict[str, Any]:
    returns_by_call_id: dict[str, dict[str, Any]] = {}
    for part in tool_returns:
        call_id = str(part.tool_call_id or "")
        if not call_id:
            continue
        data = _parse_tool_return_json(part.content)
        if data:
            returns_by_call_id[call_id] = data
    for part in reversed(tool_calls):
        if str(part.tool_name or "") != "confirm_pending":
            continue
        result = returns_by_call_id.get(str(part.tool_call_id or ""))
        return result if isinstance(result, dict) else {}
    return {}


def _direct_confirm_routing_path(confirm_result: dict[str, Any]) -> str:
    data = confirm_result.get("data") if isinstance(confirm_result.get("data"), dict) else {}
    if str(data.get("action") or "").strip() != "confirm":
        return "zhiyuan_agent_direct"
    kind = str(data.get("kind") or "").strip()
    if _is_plan_pending_kind(kind):
        return "direct_pending_plan_confirm"
    if kind == "intent_change":
        return "direct_pending_intent_confirm"
    return "zhiyuan_agent_direct"


def _direct_confirm_workspace_refresh_targets(confirm_result: dict[str, Any]) -> list[str]:
    data = confirm_result.get("data") if isinstance(confirm_result.get("data"), dict) else {}
    if str(data.get("action") or "").strip() != "confirm" or data.get("applied") is not True:
        return []
    kind = str(data.get("kind") or "").strip()
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    if kind in {"plan_mutation", "plan_generation"}:
        return ["ordered", "review"]
    if kind == "intent_change" and result.get("plan_regenerated") is True:
        return ["ordered", "review"]
    return []


def _tool_calls_include_plan_chain(messages: list[Any] | None) -> bool:
    plan_tool_names = {
        "query_plan",
        "review_plan",
    }
    return any(part.tool_name in plan_tool_names for part in _iter_tool_call_parts(messages))


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
        ("我先帮你把思路记下来", "我先把这个思路作为当前对话参考"),
        ("我先帮你把这个思路记下来", "我先把这个思路作为当前对话参考"),
        ("我先把思路记下来", "我先把这个思路作为当前对话参考"),
        ("我先把这个思路记下来", "我先把这个思路作为当前对话参考"),
        ("把思路记下来", "把这个思路作为当前对话参考"),
        ("帮你把思路记下来", "把这个思路作为当前对话参考"),
        ("记下来，不会自动修改你的方案", "作为当前对话参考，不会改动当前方案"),
        ("不会自动修改你的方案", "不会改动当前方案"),
        ("先记下来", "先作为当前结论参考"),
        ("我先记下来", "我先按当前结论理解"),
        ("我会先记下来", "我会先按当前结论理解"),
        ("确认采纳前都不会生效", "如果要正式采用，我会先列出要采用的内容或调整预览；确认前不会执行"),
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
        compact_normalized = _compact_plan_reply_text(normalized)
        explicit_unadopted_impact = any(
            marker in compact_normalized
            for marker in (
                "影响当前方案",
                "需要替换",
                "需要补充",
                "需要移除",
                "需要删除",
            )
        )
        boundary_prefix = "采纳/确认前不会生效，" if explicit_unadopted_impact else ""
        normalized = (
            normalized.rstrip()
            + "\n\n如果后面要正式更新想法、报考条件或方案，可以直接说清楚要采用的内容；"
            f"{boundary_prefix}我会先列明具体影响或调整预览，再让你决定是否采用。"
        )
    return _normalize_user_facing_terms(normalized)


def _reply_discusses_changeable_intent_or_plan(reply: str) -> bool:
    compact = _compact_plan_reply_text(reply)
    if not compact:
        return False
    has_changeable_subject = any(marker in compact for marker in ("偏好", "排除项", "方案内容", "当前方案", "志愿"))
    has_changeable_action = any(marker in compact for marker in ("可以改", "可以调整", "随时都可以调整", "随时可以调整", "增删", "替换", "调整顺序", "重新生成"))
    return has_changeable_subject and has_changeable_action


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
    return proposal_compiler.runtime_reply_claims_intent_recorded_without_pending(reply)


def _recorded_intent_claim_without_pending_reply(reply: str) -> str:
    subject = ""
    for pattern in (
        r"[“\"]([^”\"\n]{1,80})[”\"]",
        r"把([^。！？\n]{1,80}?)(?:作为后续|写入|记下来)",
    ):
        match = re.search(pattern, reply or "")
        if match:
            subject = str(match.group(1) or "").strip(" ，,。")
            if subject:
                break
    subject_prefix = f"这次关于“{subject}”的想法" if subject else "这次想法"
    return (
        f"{subject_prefix}还没有写入后续报考参考，也没有生成可采纳内容。"
        "如果要正式采用，我会先列清楚要采用的内容或调整预览；"
        "你确认或点“采纳”前，不会写入后续报考参考，也不会改动当前方案。"
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
            "避开的地域",
            "避开的地区",
            "避开地域",
            "避开地区",
            "不优先考虑",
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
            "如果你确认",
            "你确认后",
            "确认采纳",
            "确认这个",
            "按上面执行",
            "你确认要这样记",
            "确认要这样记",
        )
    )
    has_unbacked_confirm_effect = (
        any(marker in compact for marker in ("确认后", "如果你确认", "你确认", "确认要这样记"))
        and any(
            marker in compact
            for marker in (
                "后续参考",
                "偏好",
                "排除",
                "过滤",
                "优先保留",
                "记入",
                "记录",
                "避开",
                "不优先",
                "地域",
                "地区",
                "城市",
                "省份",
            )
        )
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


def _line_looks_like_unbacked_intent_confirmation(compact: str) -> bool:
    if "确认" not in compact:
        return False
    return any(
        marker in compact
        for marker in (
            "后续报考参考",
            "后续参考",
            "推荐口径",
            "生成或调整方案",
            "作为后续",
            "作为偏好",
            "作为要求",
            "偏好",
            "排除",
            "过滤",
            "优先保留",
            "记入",
            "记录",
            "避开",
            "不优先",
            "地域",
            "地区",
            "城市",
            "省份",
        )
    )


def _remove_unbacked_intent_confirmation_copy(reply: str) -> str:
    if not isinstance(reply, str) or not reply.strip():
        return reply

    normalized_lines: list[str] = []
    for raw_line in reply.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            if normalized_lines and normalized_lines[-1] != "":
                normalized_lines.append("")
            continue
        sentence_parts = re.findall(r"[^。！？.!?]+[。！？.!?]?", raw_line)
        if len(sentence_parts) <= 1:
            compact = re.sub(r"\s+", "", stripped)
            if _line_looks_like_unbacked_intent_confirmation(compact):
                continue
        if not sentence_parts:
            normalized_lines.append(raw_line.rstrip())
            continue
        kept_parts = []
        for part in sentence_parts:
            compact_part = re.sub(r"\s+", "", part)
            if _line_looks_like_unbacked_intent_confirmation(compact_part):
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
        stripped = _remove_unbacked_intent_confirmation_copy(reply).strip()
        if stripped and not _reply_looks_like_unbacked_intent_preview(stripped):
            return _normalize_user_facing_terms(
                stripped.rstrip()
                + "\n\n补充说明：这轮还没有列出可采纳的内容，也不会写入后续参考或改动方案；"
                "如果要正式采用，我会先把要采用的内容列出来，点“采纳”后才会生效。"
            )
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


def _intent_side_effect_decision_focus_summary(decision: dict[str, Any] | None) -> str:
    if not isinstance(decision, dict):
        return ""
    preference_strength = decision.get("preferenceStrength")
    if not isinstance(preference_strength, dict):
        preference_strength = {}
    spans = decision.get("entityPolaritySpans")
    if not isinstance(spans, list):
        spans = []

    positive_values: list[str] = []
    negative_values: list[str] = []

    def add(target: list[str], value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in target:
            target.append(text)

    for strength in ("primary", "preferred", "acceptable", "must_have", "only_keep"):
        for value in _as_text_list(preference_strength.get(strength)):
            add(positive_values, value)
    for strength in ("exclude_soft", "exclude_hard"):
        for value in _as_text_list(preference_strength.get(strength)):
            add(negative_values, value)

    for span in spans:
        if not isinstance(span, dict):
            continue
        entity = str(span.get("entity") or "").strip()
        if not entity:
            continue
        strength = str(span.get("strength") or "").strip()
        polarity = str(span.get("polarity") or "").strip()
        if polarity == "negative" or strength in {"exclude_soft", "exclude_hard"}:
            add(negative_values, entity)
        elif polarity == "positive" or strength in {"primary", "preferred", "acceptable", "must_have", "only_keep"}:
            add(positive_values, entity)

    parts: list[str] = []
    if positive_values:
        parts.append(f"偏好方向：{'、'.join(positive_values[:6])}")
    if negative_values:
        parts.append(f"不优先方向：{'、'.join(negative_values[:6])}")
    return "；".join(parts)


def _append_downgraded_intent_focus_summary(reply: str, decision: dict[str, Any] | None) -> str:
    summary = _intent_side_effect_decision_focus_summary(decision)
    if not summary or not isinstance(reply, str) or not reply.strip():
        return reply
    compact_reply = _compact_plan_reply_text(reply)
    summary_terms = [
        term
        for term in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", summary)
        if len(term) >= 2
    ]
    if summary_terms and all(term in compact_reply for term in summary_terms):
        return reply
    return _normalize_user_facing_terms(f"{reply.rstrip()}\n\n这次识别到的方向：{summary}。")


def _append_pending_intent_boundary(reply: str, *, has_pending_intent: bool) -> str:
    """Keep pending intent analysis visibly non-mutating across follow-up turns."""
    if not has_pending_intent or not isinstance(reply, str) or not reply.strip():
        return reply
    compact = _compact_plan_reply_text(reply)
    if any(marker in compact for marker in ("尚未确认", "待确认内容", "确认前不会写入后续参考")):
        return reply
    if any(marker in compact for marker in ("已正式生效", "已经生效")):
        return reply
    normalized = reply
    for source, target in (
        ("已经记录到后续参考", "仍在等待采纳"),
        ("已记录到后续参考", "仍在等待采纳"),
        ("已经写入后续报考参考", "仍在等待采纳"),
        ("已写入后续报考参考", "仍在等待采纳"),
        ("已经记下来", "仍在等待采纳"),
        ("已记下来", "仍在等待采纳"),
        ("已记录", "待采纳"),
        ("已经记录", "待采纳"),
        ("已加入", "待采纳"),
        ("已经加入", "待采纳"),
    ):
        normalized = normalized.replace(source, target)
    return (
        normalized.rstrip()
        + "\n\n补充说明：这次内容还没有采纳，点“采纳”前不会写入后续报考参考，采纳/确认前不会生效；"
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


def _prompt_looks_like_candidate_pool_query(content: str | None) -> bool:
    compact = re.sub(r"\s+", "", str(content or "").strip())
    if not compact:
        return False
    return (
        any(marker in compact for marker in ("候选", "候选列表", "候选里", "当前能选", "能选的结果"))
        and any(marker in compact for marker in ("看", "查", "刷新", "结果", "有没有", "多不多", "机会"))
    )


def _candidate_pool_missing_info_reply(
    content: str | None,
    missing_inputs: list[str] | None = None,
) -> str:
    focus_clause = "按你说的筛选方向"
    missing = {str(item or "").strip() for item in (missing_inputs or []) if str(item or "").strip()}
    need_score = bool({"score", "rank", "score_or_rank", "rank_or_score"} & missing) or not missing
    need_text = "高考分数和全省位次" if need_score else "省份、分数/位次、选科等基础信息"
    return (
        f"当前还不能{focus_clause}刷新候选列表或展示候选结果，因为候选池还没有生成，"
        f"并且缺少{need_text}。"
        f"你补充{need_text}后，我再{focus_clause}刷新候选结果。"
        "这轮不会加入方案，也不会改动当前方案。"
    )


def _conditional_candidate_readonly_boundary_reply(
    content: str | None,
    *,
    reason_code: str,
    missing_inputs: list[str] | None = None,
) -> str:
    focus_clause = "这类候选"
    missing = {str(item or "").strip() for item in (missing_inputs or []) if str(item or "").strip()}

    if reason_code == "selection_scope":
        return (
            "这轮先按候选可行性查看处理，暂时还没有定位到要加入方案的具体候选，"
            "所以不会加入方案，也不会改动当前方案。"
            "你可以补充学校、专业、地域等筛选范围，或先在候选列表里点选目标；"
            "我再按新的范围帮你确认是否值得加入。"
        )
    if reason_code == "missing_inputs":
        need_score = bool({"score", "rank", "score_or_rank", "rank_or_score"} & missing) or not missing
        need_text = "高考分数、全省位次和选科等基础信息" if need_score else "省份、分数/位次、选科等基础信息"
        return (
            f"这轮先按候选可行性查看处理，但当前还不能判断{focus_clause}是否适合加入方案，"
            f"因为还缺少{need_text}。"
            f"你补充{need_text}后，我再继续看这类候选值不值得加入。"
            "这轮不会加入方案，也不会改动当前方案。"
        )
    return (
        f"这轮先按候选可行性查看处理，当前候选里暂时没有稳定命中适合直接加入方案的{focus_clause}，"
        "所以不会加入方案，也不会改动当前方案。"
        "你可以继续补充筛选范围，或先看看当前候选结果后再决定要不要加入。"
    )


def _build_pending_readonly_impact_reply(pending_state: dict[str, Any]) -> str:
    kind = str((pending_state or {}).get("kind") or "").strip()
    action_family = str((pending_state or {}).get("actionFamily") or "").strip()
    summary = str((pending_state or {}).get("summary") or "").strip()
    execution_payload = pending_state.get("executionPayload") if isinstance(pending_state, dict) else None
    intent_payload = execution_payload.get("intentPayload") if isinstance(execution_payload, dict) else None
    intent_summary = _summarize_selected_intent_payload(intent_payload) if isinstance(intent_payload, dict) else ""

    if _is_plan_pending_kind(kind):
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


def _post_apply_evidence_workspace_targets(
    evidence_plan: dict[str, Any] | None,
    fallback_targets: list[str] | None = None,
) -> list[str]:
    raw_targets = []
    if isinstance(evidence_plan, dict):
        raw_targets = evidence_plan.get("workspaceRefreshTargets") or evidence_plan.get("workspace_refresh_targets") or []
    if not isinstance(raw_targets, list):
        raw_targets = []
    targets = _dedupe_workspace_targets([str(target) for target in raw_targets])
    if targets:
        return targets
    return _dedupe_workspace_targets([str(target) for target in (fallback_targets or [])])


def _workspace_targets_from_followups(followups: list[WSResponse]) -> set[str]:
    targets: set[str] = set()
    for item in followups:
        content = getattr(item, "content", None)
        if not isinstance(content, str):
            continue
        try:
            payload = json.loads(content)
        except Exception:
            continue
        if isinstance(payload, dict):
            target = str(payload.get("targetView") or "").strip()
            if target:
                targets.add(target)
    return targets


def _pending_apply_turn_event(
    *,
    session_id: str,
    user_id: str,
    scene: str,
    routing_path: str,
    pending_type: str,
    action_family: str | None,
    started_at: float,
    status: str,
    error_type: str | None = None,
    post_apply_evidence_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    route_decision = {
        "source": "proposal_compiler",
        "matched": True,
        "route": (
            "apply_pending_then_readonly"
            if post_apply_evidence_plan is not None
            else "apply_pending_then_new_request"
            if action_family == "apply_pending_then_new_request"
            else "apply_existing_pending"
        ),
    }
    if post_apply_evidence_plan is not None:
        route_decision["postApplyEvidencePlan"] = post_apply_evidence_plan
    return {
        "sessionId": session_id,
        "userId": user_id,
        "scene": scene,
        "routingPath": routing_path,
        "routeDecision": route_decision,
        "pendingType": pending_type,
        "actionFamily": action_family,
        "toolCallCount": 0,
        "totalDurationMs": int((time.monotonic() - started_at) * 1000),
        "postProcessingApplied": ["post_apply_evidence_plan"] if post_apply_evidence_plan is not None else [],
        "status": status,
        "errorType": error_type,
    }


def _post_apply_evidence_target_issues(evidence_plan: dict[str, Any] | None) -> list[str]:
    if not isinstance(evidence_plan, dict):
        return []
    issues: list[str] = []
    for item in evidence_plan.get("targetIssues") or evidence_plan.get("target_issues") or []:
        value = str(item or "").strip()
        if value and value not in issues:
            issues.append(value)
    return issues


async def _load_post_apply_planning_summary(session_id: str) -> PlanningSummary | None:
    try:
        response = await get_planning_workspace_state(session_id)
    except Exception:
        logger.warning("Failed to fetch post-apply planning workspace: session_id=%s", session_id, exc_info=True)
        return None
    if not isinstance(response, dict) or response.get("code") != 0:
        return None
    try:
        return PlanningSummary.from_backend_state(response.get("data", {}))
    except Exception:
        logger.warning("Failed to parse post-apply planning workspace: session_id=%s", session_id, exc_info=True)
        return None


def _build_pending_apply_then_readonly_evidence_reply(
    pending_state: dict[str, Any],
    evidence_plan: dict[str, Any] | None,
    planning: PlanningSummary | None,
) -> str | None:
    if planning is None:
        return None
    kind = str((pending_state or {}).get("kind") or "").strip()
    if not _is_plan_pending_kind(kind):
        return None

    target_issues = _post_apply_evidence_target_issues(evidence_plan)
    if not target_issues:
        target_issues = ["current_plan_state"]

    total = planning.ordered_total or planning.working_total
    target = (
        planning.ordered_target_total
        or planning.working_target_total
        or max(planning.ordered_total, planning.working_total, total)
    )
    lines = ["已先执行这项待确认调整。基于执行后刷新到的当前方案："]
    missing: list[str] = []

    if any(issue in target_issues for issue in ("remaining_count", "current_plan_state", "post_apply_state")):
        if total > 0:
            if target > 0:
                lines.append(f"- 当前方案 {total} 个志愿（目标 {target} 个）。")
            else:
                lines.append(f"- 当前方案 {total} 个志愿。")
        else:
            missing.append("志愿数量")

    if "tier_distribution" in target_issues:
        tier = planning.tier_counts or {}
        chong = _as_int(tier.get("冲"))
        wen = _as_int(tier.get("稳"))
        bao = _as_int(tier.get("保"))
        if chong or wen or bao:
            lines.append(f"- 梯度分布：冲 {chong} 个、稳 {wen} 个、保 {bao} 个。")
        else:
            missing.append("梯度分布")

    if "risk_review" in target_issues:
        risk_count = _as_int(planning.review_risk_count)
        warn_count = _as_int(planning.review_warn_count)
        if risk_count or warn_count:
            lines.append(f"- 审查结果：风险 {risk_count} 项、提醒 {warn_count} 项。")
            if planning.risk_summaries:
                lines.append(f"- 需要留意：{'、'.join(planning.risk_summaries[:2])}。")
        elif total > 0:
            lines.append("- 审查结果：暂时没有明显风险。")
        else:
            missing.append("风险审查")

    if len(lines) == 1:
        return None
    if missing:
        lines.append(f"其中{'、'.join(missing)}暂时没有从刷新后的工作台读到，建议打开当前方案继续核对。")
    return "\n".join(lines)


def _append_pending_apply_then_readonly_result(
    reply: str,
    pending_state: dict[str, Any],
    evidence_plan: dict[str, Any] | None = None,
    planning: PlanningSummary | None = None,
) -> str:
    evidence_reply = _build_pending_apply_then_readonly_evidence_reply(
        pending_state,
        evidence_plan,
        planning,
    )
    if evidence_reply:
        base = str(reply or "").strip()
        if not base:
            return evidence_reply
        if evidence_reply in base:
            return base
        return f"{base}\n\n{evidence_reply}"
    return _append_pending_apply_then_readonly_followup(reply, pending_state, evidence_plan)


def _append_pending_apply_then_readonly_followup(
    reply: str,
    pending_state: dict[str, Any],
    evidence_plan: dict[str, Any] | None = None,
) -> str:
    kind = str((pending_state or {}).get("kind") or "").strip()
    target_issues = []
    if isinstance(evidence_plan, dict):
        target_issues = [str(item).strip() for item in (evidence_plan.get("targetIssues") or []) if str(item).strip()]
    issue_names = {
        "remaining_count": "剩余数量",
        "tier_distribution": "梯度分布",
        "risk_review": "风险变化",
        "current_plan_state": "当前方案状态",
        "post_apply_state": "生效后的状态",
    }
    issue_text = "、".join(issue_names.get(issue, issue) for issue in target_issues if issue_names.get(issue, issue))
    if kind == "intent_change":
        followup = (
            "已先采纳这项报考参考。关于采纳后对当前方案的具体影响，"
            "需要基于新的报考参考重新检查当前方案；这轮不会直接给出未经检查的数量、梯度或风险结论。"
        )
    elif _is_plan_pending_kind(kind):
        followup = (
            "已先执行这项待确认调整。关于执行后还剩多少、梯度是否稳定或风险是否变化，"
            "需要基于刷新后的新方案继续检查；这轮不会直接给出未经检查的数量、梯度或风险结论。"
        )
    else:
        followup = (
            "已先采纳这项待确认内容。关于生效后的具体结果，需要基于最新状态继续检查；"
            "这轮不会直接给出未经检查的结论。"
        )
    if issue_text:
        followup = f"{followup}后续检查范围：{issue_text}。"
    base = str(reply or "").strip()
    if not base:
        return followup
    if followup in base:
        return base
    return f"{base}\n\n{followup}"


def _build_pending_conflict_new_request_reply(pending_state: dict[str, Any]) -> str:
    kind = str((pending_state or {}).get("kind") or "").strip()
    summary = str((pending_state or {}).get("summary") or "").strip()
    if _is_plan_pending_kind(kind):
        lines = [
            "当前已经有一项方案调整正在等待确认。",
        ]
        lines.append(f"待确认调整：{summary}。" if summary else "这项调整确认前不会改动当前方案。")
        lines.extend(
            [
                "这轮新诉求不会直接覆盖它，也不会再生成第二张待确认卡。",
                "你可以先确认执行、取消这项调整，或明确说要放弃当前待确认内容后重新提新的调整。",
            ]
        )
        return "\n".join(lines)
    if kind == "intent_change":
        lines = [
            "当前已经有一项想法或报考条件正在等待采纳。",
        ]
        lines.append(f"待采纳内容：{summary}。" if summary else "这项内容采纳前不会写入后续报考参考。")
        lines.extend(
            [
                "这轮新诉求不会直接覆盖它，也不会再生成第二张待采纳卡。",
                "你可以先点“采纳”、取消这项内容，或明确说要放弃当前待采纳内容后重新整理新的条件。",
            ]
        )
        return "\n".join(lines)
    return (
        "当前已经有一项内容正在等待确认。这轮新诉求不会直接覆盖它，也不会再生成第二张待确认卡。"
        "请先确认、取消，或明确说要放弃当前待确认内容后重新整理。"
    )


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
        if kind in _SUPPORTED_PENDING_KINDS:
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
        if card_kind in _SUPPORTED_PENDING_KINDS:
            if card_kind == pending_kind or (_is_plan_pending_kind(card_kind) and _is_plan_pending_kind(pending_kind)):
                return "matched", None, assistant_summary
            return "conflict", "assistant_confirmation_type_conflict", assistant_summary

    assistant_kind = _assistant_confirmation_kind_from_text(latest_text)
    if assistant_kind is None:
        return "unknown", None, assistant_summary
    if assistant_kind == pending_kind or (_is_plan_pending_kind(assistant_kind) and _is_plan_pending_kind(pending_kind)):
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


def _latest_turn_looks_readonly(messages: list[Any] | None) -> bool:
    if _latest_turn_is_readonly_interruption_fallback(messages):
        return True
    tool_names = _latest_turn_tool_names(messages)
    if not tool_names:
        return False
    if any(name in _INTENT_PREVIEW_TOOL_NAMES for name in tool_names):
        return False
    for name in tool_names:
        if name not in _READONLY_DIRECT_TOOL_NAMES:
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


def _readonly_closure_ack_reply() -> str:
    return "先按刚才的分析结论理解。这轮没有待确认的偏好或方案动作，也不会改动方案；后面想继续看具体学校、专业或方案调整，随时告诉我。"


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


def _normalize_confirmation_only_text(content: str, *, strip_fullwidth_question: bool = False) -> str:
    normalized = re.sub(r"\s+", "", (content or "").strip())
    punctuation = "。.!！?？" if strip_fullwidth_question else "。.!！?"
    normalized = normalized.strip(punctuation)
    return normalized


_PENDING_SHORT_CONFIRM_TEXTS = {
    "确认",
    "确认采纳",
    "确认执行",
    "采纳",
    "执行",
    "行采纳",
    "行确认",
    "可以采纳",
    "可以确认",
    "就这个",
    "就这样",
    "按这个",
    "按这个执行",
    "同意",
}

_PENDING_SHORT_CANCEL_TEXTS = {
    "取消",
    "取消这次",
    "取消这个",
    "先不采纳",
    "先不采纳了",
    "暂不采纳",
    "暂不采纳了",
    "不采纳",
    "不采纳了",
    "别采纳",
    "先别采纳",
    "不要采纳",
    "不要确认",
    "别确认",
    "不用确认",
    "不要确认先别采纳",
    "不要确认，先别采纳",
    "先不执行",
    "先不执行了",
    "暂不执行",
    "暂不执行了",
    "不执行",
    "不执行了",
    "放弃",
    "放弃这次",
    "放弃这个",
    "算了",
    "算了吧",
    "先算了",
    "先算了吧",
}

_NO_PENDING_SHORT_CONFIRM_TEXTS = {
    "确认",
    "确认采纳",
    "确认执行",
    "采纳",
    "执行",
    "可以采纳",
    "可以确认",
    "嗯可以",
}

_NO_PENDING_SHORT_CANCEL_TEXTS = {
    "取消",
    "取消这次",
    "取消这个",
    "先不采纳",
    "先不采纳了",
    "暂不采纳",
    "暂不采纳了",
    "不采纳",
    "不采纳了",
    "别采纳",
    "先别采纳",
    "不要采纳",
    "不要确认",
    "别确认",
    "不用确认",
    "先不执行",
    "先不执行了",
    "暂不执行",
    "暂不执行了",
    "不执行",
    "不执行了",
}


def _pending_short_text_action(content: str) -> str:
    normalized = _normalize_confirmation_only_text(content, strip_fullwidth_question=True)
    if normalized in _PENDING_SHORT_CANCEL_TEXTS:
        return "cancel"
    if normalized in _PENDING_SHORT_CONFIRM_TEXTS:
        return "confirm"
    return ""


def _no_pending_short_text_action(content: str) -> str:
    normalized = _normalize_confirmation_only_text(content, strip_fullwidth_question=True)
    if normalized in _NO_PENDING_SHORT_CANCEL_TEXTS:
        return "cancel"
    if normalized in _NO_PENDING_SHORT_CONFIRM_TEXTS:
        return "confirm"
    return ""


def _is_readonly_closure_ack(content: str) -> bool:
    normalized = _normalize_confirmation_only_text(content, strip_fullwidth_question=True)
    if not normalized:
        return False
    return normalized in _READONLY_CLOSURE_ACK_PHRASES


def _no_pending_confirmation_guard_reply() -> str:
    return (
        "我这边没有上一轮待确认，也没有待执行的方案调整或报考想法。"
        "下一步可以直接说想审查方案、生成调整预览、调整排序，或说明要保留/避开的方向；"
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
    turn_event: dict[str, Any] | None = None,
    request_context: RequestContext | None = None,
    user_id: str = "",
) -> None:
    new_messages = [
        ModelRequest(parts=[UserPromptPart(content=content)]),
        ModelResponse(parts=[TextPart(content=reply)], model_name=model_name),
    ]
    try:
        history_to_save = list(history or [])
        saved_messages = _append_turn_observability_messages(
            new_messages,
            turn_event,
            request_context=request_context,
            session_id=session_id,
            user_id=user_id,
            prompt_length=len(content or ""),
        )
        history_to_save.extend(saved_messages)
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
    if any(marker in reply for marker in _USER_REPLY_FORCED_CHOICE_MARKERS):
        cleaned_lines: list[str] = []
        for line in reply.splitlines():
            if not any(marker in line for marker in _USER_REPLY_FORCED_CHOICE_MARKERS):
                cleaned_lines.append(line)
                continue
            sentence_parts = re.findall(r"[^。！？.!?\n]+[。！？.!?]?", line)
            kept = [
                part
                for part in sentence_parts
                if not any(marker in part for marker in _USER_REPLY_FORCED_CHOICE_MARKERS)
            ]
            cleaned_line = "".join(kept).strip()
            if cleaned_line:
                cleaned_lines.append(cleaned_line)
        reply = "\n".join(cleaned_lines)
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


def _prompt_explicitly_readonly(content: str | None) -> bool:
    compact = re.sub(r"\s+", "", str(content or "").strip())
    if not compact:
        return False
    return any(marker in compact for marker in _READONLY_USER_PROMPT_MARKERS)


def _prompt_is_score_batch_risk_policy_question(content: str | None) -> bool:
    compact = re.sub(r"\s+", "", str(content or "").strip())
    if not compact:
        return False
    has_score_boundary = any(
        marker in compact
        for marker in (
            "本科线",
            "批次线",
            "压线",
            "刚过线",
            "刚压",
            "过线不多",
            "只高一点",
        )
    )
    has_risk_request = any(
        marker in compact
        for marker in (
            "别给我画大饼",
            "不要画大饼",
            "画大饼",
            "保底",
            "兜底",
            "保本科",
            "滑档",
            "风险",
        )
    )
    return has_score_boundary and has_risk_request


def _prompt_is_major_group_keep_safest_policy_question(content: str | None) -> bool:
    compact = re.sub(r"\s+", "", str(content or "").strip())
    if not compact:
        return False
    has_group_anchor = any(marker in compact for marker in ("专业组", "组内", "这一组", "这个组"))
    has_keep_safest = any(marker in compact for marker in ("只保留", "保留")) and any(
        marker in compact for marker in ("最稳", "更稳", "稳的专业", "安全垫")
    )
    has_question = any(marker in compact for marker in ("行不行", "可不可以", "能不能", "是否", "要不要"))
    explicit_apply = any(marker in compact for marker in ("直接执行", "确认执行", "现在就改", "直接改", "就这么改"))
    return has_group_anchor and has_keep_safest and has_question and not explicit_apply


def _prompt_requires_readonly_policy_answer(content: str | None) -> bool:
    return _prompt_is_score_batch_risk_policy_question(content) or _prompt_is_major_group_keep_safest_policy_question(content)


def _build_score_batch_risk_policy_reply() -> str:
    return (
        "如果分数刚压本科线，不能按“能上本科”乐观处理，要按压线风险来做预案。"
        "建议把目标拆成三层：第一层少量冲本科批里过线要求低、招生计划稳定的机会；第二层重点放稳妥保本科，优先看往年位次、录取最低分和计划变化，不只看分数；"
        "第三层准备兜底方案，包括能接受的民办本科、中外合作或高质量专科，避免只押一个本科批结果导致滑档。"
        "保底位要留足安全垫，专业也要现实一些，不能只放热门专业。下一步需要核对所在省当年本科线、一分一段位次、批次规则和当前方案里的冲稳保比例，再决定本科和专科兜底怎么配。"
    )


def _build_major_group_keep_safest_policy_reply() -> str:
    return (
        "专业组里只保留最稳的专业，可以作为降低组内风险的思路，但不能直接当成长期就业偏好。"
        "在院校专业组模式下，要先看这个专业组的投档规则、组内专业录取率、计划数、专业备注和是否服从调剂；"
        "如果只保留最稳的专业，可能降低被不想读专业分配的风险，但也可能减少组内可选空间，影响专业满足率或让这个专业组不再值得保留。"
        "更稳妥的做法是先读取具体专业组，判断哪些专业是安全垫、哪些专业风险偏高，再决定是保留一个兜底专业、删掉高风险专业，还是生成可确认的调整预览。"
        "确认前不应改动当前方案，也不应写成后续报考参考里的职业或专业偏好。"
    )


def _score_batch_policy_reply_is_sufficient(reply: str | None) -> bool:
    compact = _compact_plan_reply_text(str(reply or ""))
    if not compact:
        return False
    has_boundary = "本科线" in compact or "批次线" in compact
    has_pressure = any(marker in compact for marker in ("压线", "刚过线", "过线不多", "只高一点"))
    has_floor = any(marker in compact for marker in ("保底", "兜底", "保本科", "滑档"))
    return has_boundary and has_pressure and has_floor and "风险" in compact


def _major_group_policy_reply_is_sufficient(reply: str | None) -> bool:
    compact = _compact_plan_reply_text(str(reply or ""))
    if not compact:
        return False
    has_group = "专业组" in compact and "专业" in compact
    has_safety = any(marker in compact for marker in ("录取率", "最稳", "更稳", "安全垫", "兜底"))
    has_boundary = any(marker in compact for marker in ("风险", "调剂", "确认", "当前方案"))
    return has_group and has_safety and has_boundary


def _reply_is_readonly_policy_misroute(reply: str | None) -> bool:
    compact = _compact_plan_reply_text(str(reply or ""))
    if not compact:
        return True
    if any(
        marker in compact
        for marker in (
            "不会写入后续报考参考",
            "还没有生成可执行的调整内容",
            "没有生成可执行的调整内容",
            "还没有生成可确认的调整预览",
            "没有生成可确认的调整预览",
            "这轮还没有生成可点击的方案待采纳内容",
            "待确认内容",
            "待采纳内容",
            "稳定就业导向",
        )
    ):
        return True
    return _reply_looks_like_unbacked_intent_preview(str(reply or "")) or _reply_looks_like_unbacked_plan_action_boundary(str(reply or ""))


def _readonly_policy_fallback_reply_for_prompt(
    content: str | None,
    reply: str | None,
    tool_context_messages: list[Any] | None,
) -> str | None:
    if _prompt_is_score_batch_risk_policy_question(content):
        if _score_batch_policy_reply_is_sufficient(reply) and not _reply_is_readonly_policy_misroute(reply):
            return None
        tool_reply = _latest_readonly_tool_reply(tool_context_messages)
        if _score_batch_policy_reply_is_sufficient(tool_reply):
            return tool_reply
        return _build_score_batch_risk_policy_reply()
    if _prompt_is_major_group_keep_safest_policy_question(content):
        if _major_group_policy_reply_is_sufficient(reply) and not _reply_is_readonly_policy_misroute(reply):
            return None
        return _build_major_group_keep_safest_policy_reply()
    return None


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


def _needs_plan_first_guard_reply(
    content: str | None,
    resolution: proposal_compiler.NeedsPlanFirstResolution | None = None,
) -> str:
    if resolution is not None and resolution.primary_reply:
        return resolution.primary_reply
    compact = re.sub(r"\s+", "", str(content or "").strip())
    if "民办" in compact or "公办" in compact:
        focus = "公办/民办这类要求"
    elif "中外合作" in compact:
        focus = "中外合作这类要求"
    elif any(marker in compact for marker in ("保底", "稳", "冲", "风险", "太冲")):
        focus = "冲稳保或风险这类要求"
    else:
        focus = "这类方案范围要求"
    return (
        "当前还没有生成正式方案，所以没法判断或调整“刚才/当前方案”里的具体志愿。"
        f"这轮不会把{focus}写成新的报考要求，也不会改动当前方案。"
        "也就是说，这轮不会改动方案。"
        "你可以先让我生成一版方案；有了正式方案后，我再按这条要求检查或调整。"
    )


def _planning_summary_for_boundary_guard(
    planning_summary: PlanningSummary | dict[str, Any] | None,
) -> PlanningSummary | dict[str, Any] | None:
    # Only a successfully parsed backend planning summary can prove "no plan".
    # Sandbox may contain a local has_plan=false placeholder when backend state
    # is unavailable, and that must not trigger the no-plan guard.
    return planning_summary


def _no_formal_plan_review_boundary_reply(
    content: str | None,
    *,
    pending_state: dict[str, Any] | None = None,
) -> str:
    compact = re.sub(r"\s+", "", str(content or "").strip())
    path_parts: list[str] = []
    if "强基" in compact:
        path_parts.append("强基")
    if "普通批" in compact:
        path_parts.append("普通批")
    if "提前批" in compact:
        path_parts.append("提前批")
    path_text = "、".join(path_parts) if path_parts else "这条路径"
    pending_note = ""
    if isinstance(pending_state, dict) and str(pending_state.get("status") or "").strip() == "active":
        summary = str(pending_state.get("summary") or "").strip()
        if summary:
            pending_note = f"当前还有一项待采纳内容：{summary}；点采纳前不会生效。"
        else:
            pending_note = "当前还有一项待采纳内容；点采纳前不会生效。"
    return (
        f"现在还没有正式的{path_text}志愿方案，所以不能按“这版方案”做正式方案审查，"
        "这轮也不会自动生成或改动普通批方案。"
        f"{pending_note}"
        "就当前思路看，可以把强基作为额外冲刺路径，同时另做普通批方案承接；"
        "等正式方案生成后，再检查冲稳保、专业接受度和风险会更准确。"
    )


_READONLY_INTERRUPTION_TOOL_NAMES = {
    *_READONLY_DIRECT_TOOL_NAMES,
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
    if "explore_topic" in tool_names and "地域" in compact:
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
        ("硬性要求", "明确要求"),
        ("硬要求", "明确要求"),
        ("硬约束", "明确要求"),
        ("报考偏好", "报考要求"),
        ("软偏好", "优先考虑的方向"),
        ("软意向", "优先考虑的方向"),
        ("约束", "要求"),
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
        ("系统能直接处理的是", "可以先看调整预览的是"),
        ("系统能直接处理的", "可以先看调整预览的"),
        ("系统能直接处理", "可以先看调整预览"),
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
        ("可执行的调整预览", "可确认的调整预览"),
        ("可执行的处理预览", "可确认的处理预览"),
        ("可执行的替换预览", "可确认的替换预览"),
        ("可执行的移除预览", "可确认的移除预览"),
        ("可执行的补充预览", "可确认的补充预览"),
        ("可执行预览", "调整预览"),
        ("可执行的处理内容", "可确认的处理内容"),
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
        ("处理高收费志愿", "高收费志愿"),
        ("处理高收费", "高收费志愿"),
        ("处理中外合作办学项目", "中外合作项目"),
        ("处理中外合作", "中外合作项目"),
        ("处理非意向托底专业", "非意向兜底专业"),
        ("处理非意向托底", "非意向兜底专业"),
        ("处理数量校验", "补足志愿数量"),
        ("处理录取率梯度断层", "补齐录取率梯度"),
        ("处理录取率倒挂", "调整录取率顺序"),
        ("处理兜底专业不足", "补兜底专业"),
        ("处理组内安全垫不足", "补兜底专业"),
        ("数量校验", "志愿数量"),
        ("冲稳保配比暂时无法自动处理", "冲稳保结构暂时还调不齐"),
        ("录取率梯度断层暂时无法自动处理", "录取率梯度暂时还补不齐"),
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
        ("系统阻塞", "需要你先确认是否接受这类调整或放宽报考条件"),
        ("被系统阻塞", "需要你先确认是否接受这类调整或放宽报考条件"),
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
        ("blocked", "需要你先确认是否接受这类调整或放宽报考条件"),
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
    normalized = normalized.replace("所以 需要你先决定是否接受调整范围变化 了", "所以需要你先确认是否接受这类调整")
    normalized = normalized.replace("需要你先决定是否接受调整范围变化 了", "需要你先确认是否接受这类调整")
    normalized = normalized.replace("需要你先决定是否接受调整范围变化", "需要你先确认是否接受这类调整或放宽报考条件")
    normalized = normalized.replace("需要你先决定原因", "需要你先决定")
    normalized = normalized.replace("暂被阻塞", "暂时不能直接处理")
    normalized = normalized.replace("被阻塞", "暂时不能直接处理")
    normalized = re.sub(r"\bready\b", "可以先看调整预览", normalized)
    normalized = normalized.replace("暂时还不可以先看调整预览", "暂时需要你先取舍或放宽条件")
    normalized = normalized.replace("直接处理方向", "处理方向")
    normalized = normalized.replace("直接处理建议", "处理建议")
    normalized = normalized.replace("可以直接处理的有", "可以先看调整预览的有")
    normalized = normalized.replace("可以立即处理的有", "可以先看调整预览的有")
    normalized = normalized.replace("能直接处理的有", "可以先看调整预览的有")
    normalized = normalized.replace("能直接处理的", "可以先看调整预览的")
    normalized = normalized.replace("能直接处理", "可以先看调整预览")
    normalized = normalized.replace("可以直接处理", "可以先列出调整预览")
    normalized = normalized.replace("可以立即处理", "可以先列出调整预览")
    normalized = normalized.replace("能自动的", "可以先看调整预览的")
    normalized = normalized.replace("能自动", "可以先看调整预览")
    normalized = normalized.replace("暂时自动不了", "需要你先取舍或放宽条件")
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
    normalized = re.sub(
        r"当前还缺少足够条件处理(?:帮你)?(?:保底|补保底|补几个保底志愿|补充保区候选)",
        "当前还缺少合适的保底志愿",
        normalized,
    )
    normalized = normalized.replace("当前还缺少足够条件处理冲区志愿", "当前还缺少足够合适的志愿来调整冲稳保结构")
    normalized = re.sub(
        r"当前还缺少足够条件处理([^，。！？\n]{1,24})",
        r"当前还缺少足够条件来处理\1",
        normalized,
    )
    normalized = normalized.replace("当前还缺少足够条件处理", "当前还缺少足够条件来处理")
    normalized = re.sub(
        r"可执行的([^，。！？\n]{0,12}?)(?:调整|处理|替换|移除|补充)?方案",
        lambda match: f"可确认的{match.group(1)}调整预览",
        normalized,
    )
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
    normalized = normalized.replace("暂时还不可以先看调整预览", "暂时需要你先取舍或放宽条件")
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


def _reply_is_internal_plan_error(reply: str) -> bool:
    if not isinstance(reply, str):
        return False
    compact = _compact_plan_reply_text(reply)
    return compact in {"会话不存在", "sessionnotfound", "chat session not found"} or bool(
        re.fullmatch(r"(?:错误|异常)[:：]?.{0,30}", compact)
    )


def _compact_plan_reply_text(reply: str) -> str:
    return re.sub(r'[\s"“”‘’`\'「」『』【】\[\]（）()<>《》:：,，。.!！？?、]+', "", str(reply or ""))


def _reply_has_plan_confirmation_request(reply: str) -> bool:
    return proposal_compiler.runtime_reply_has_plan_confirmation_request(reply)


def _remove_unbacked_plan_confirmation_copy(reply: str) -> str:
    return proposal_compiler.strip_unbacked_plan_confirmation_copy(reply)


def _guard_unbacked_plan_confirmation_reply(reply: str, tool_context_messages: list[Any] | None = None) -> str:
    """Replace unsupported Plan confirmation copy with an explicit no-card boundary."""
    source = proposal_compiler.compile_runtime_reply_guard_source(
        reply=reply,
        guard_context="plan_confirmation",
    )
    if not source.matched:
        return reply
    stripped = source.stripped_reply.strip()
    if not stripped or _reply_has_plan_confirmation_request(stripped):
        readonly_reply = _latest_readonly_tool_reply(tool_context_messages)
        if readonly_reply:
            return f"{readonly_reply}\n\n{_UNBACKED_PLAN_CONFIRMATION_REPLY}"
        return _UNBACKED_PLAN_CONFIRMATION_REPLY
    return f"{stripped}\n\n{_UNBACKED_PLAN_CONFIRMATION_REPLY}"


def _normalize_unbacked_no_tool_action_boundary(reply: str) -> str:
    """Use a neutral no-change boundary when no executable action was created.

    `_UNBACKED_PLAN_CONFIRMATION_REPLY` is appropriate while the service is
    still trying to route a missing Plan preview. If all structured boundary paths end
    with no tools, no pending card, and no preview, surfacing that text reads as
    an execution failure even when the user only set a discussion boundary.
    """
    source = proposal_compiler.compile_runtime_reply_guard_source(
        reply=reply,
        guard_context="no_tool_action_boundary",
    )
    if not source.matched:
        return reply
    return _NO_TOOL_NO_ACTION_BOUNDARY_REPLY


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


def _review_fallback_target_issue_labels(facts: dict[str, Any]) -> list[str]:
    labels = {
        "high_tuition": "高收费",
        "cooperative_program": "中外合作",
        "admission_limit": "限报条件",
        "special_enrollment": "特殊招生",
        "probability_inversion": "录取率倒挂",
        "probability_gap": "录取率梯度断层",
        "major_group_safety_intent_alignment": "非意向托底专业",
        "group_inner_safety_guard": "组内安全垫",
        "safety_guard": "保底安全垫",
        "edge_score": "边缘分风险",
        "count_validation": "志愿数量",
    }
    result: list[str] = []
    issue_codes = facts.get("target_issue_codes") or facts.get("targetIssueCodes") or []
    for code in issue_codes:
        label = labels.get(str(code or "").strip())
        if label and label not in result:
            result.append(label)
    return result


def _build_target_issue_review_fallback_lines(facts: dict[str, Any]) -> list[str]:
    explicit_target_issue_codes = facts.get("target_issue_codes") or facts.get("targetIssueCodes") or []
    if not explicit_target_issue_codes:
        return []

    issue_labels = _review_fallback_target_issue_labels(facts)
    examples = _review_fallback_examples_text(facts.get("issue_hit_plan_examples"), limit=3)
    problems = _review_fallback_problem_text(facts.get("main_problems"), limit=3)
    fix_facts = facts.get("fix_proposals") if isinstance(facts.get("fix_proposals"), dict) else {}
    ready_lines, needs_decision_lines = _review_fallback_fix_proposal_lines(fix_facts, limit=2)

    if not issue_labels and not examples and not problems:
        return []

    label_text = "、".join(issue_labels) if issue_labels else "这类问题"
    lines = [f"我按你关注的{label_text}看了一下：", ""]
    if examples:
        lines.append(f"- 当前方案里有命中项：{examples}。")
    elif problems:
        lines.append(f"- 当前看到的问题：{problems}。")
    else:
        lines.append("- 当前审查里暂时没有看到明确命中的志愿。")

    if ready_lines:
        lines.extend(["", "可以先看调整预览的："])
        for item in ready_lines[:2]:
            lines.append(f"- {item}。")
    if needs_decision_lines:
        lines.extend(["", "需要先取舍的："])
        for item in needs_decision_lines[:2]:
            lines.append(f"- {item}。")

    lines.extend([
        "",
        "如果要正式调整，我会先列出预览，确认前不会改动当前方案。",
    ])
    return lines


def _review_fallback_fix_proposal_lines(fix_facts: dict[str, Any], *, limit: int = 3) -> tuple[list[str], list[str]]:
    ready: list[str] = []
    needs_decision: list[str] = []
    proposals = fix_facts.get("proposals") if isinstance(fix_facts.get("proposals"), list) else []
    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        title = _clean_fix_proposal_title(proposal.get("title")) or "处理方向"
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
        title = _clean_fix_proposal_title(proposal.get("title")) or "这条提醒"
        reason = _review_fallback_proposal_reason(proposal)
        next_step = _review_fallback_proposal_next_step(proposal)
        lines.append(f"{index}. **{title}**")
        lines.append(f"- 为什么现在不直接改：{reason}。")
        lines.append(f"- 你可以怎么调：{next_step}。")
        lines.append("")

    lines.append("你可以先选最想处理的一类，我会先列出调整预览，确认前不会改动当前方案。")
    return lines


def _build_review_result_fallback_lines(facts: dict[str, Any]) -> list[str]:
    targeted_lines = _build_target_issue_review_fallback_lines(facts)
    if targeted_lines:
        return targeted_lines

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
    requested_focus = {
        str(item or "").strip()
        for item in (facts.get("requested_reply_focus") or [])
        if str(item or "").strip()
    }
    if "shortage_boundary" in requested_focus:
        return _build_shortage_boundary_fallback_lines(facts)

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


def _build_shortage_boundary_fallback_lines(facts: dict[str, Any]) -> list[str]:
    lines = ["我看了当前方案和可补机会，先说结论：", ""]
    supply = facts.get("candidate_supply") if isinstance(facts.get("candidate_supply"), dict) else {}
    tier_counts = supply.get("tier_counts") or supply.get("tierCounts") or facts.get("tier_counts")
    tier_text = _format_status_tier_counts(tier_counts)
    missing_tiers = [
        str(item or "").strip()
        for item in (
            supply.get("missing_supply_tiers")
            or supply.get("missingSupplyTiers")
            or []
        )
        if str(item or "").strip()
    ]
    total = _as_int(supply.get("total") or supply.get("candidate_total") or supply.get("candidateTotal"))

    if tier_text:
        lines.append(f"- 当前可选范围里的冲稳保供给大致是：{tier_text}。")
    if total > 0:
        lines.append(f"- 当前可用于规划的候选志愿约 {total} 个。")
    if missing_tiers:
        lines.append(f"- 主要缺口在 {'、'.join(missing_tiers)} 区间，说明不是简单把比例调一下就能补上。")

    fix_facts = facts.get("fix_proposals") if isinstance(facts.get("fix_proposals"), dict) else {}
    ready_lines, needs_decision_lines = _shortage_boundary_fix_proposal_lines(fix_facts)
    if ready_lines:
        lines.extend(["", "可以先看预览的方向："])
        for item in ready_lines[:2]:
            lines.append(f"- {item}。")
    if needs_decision_lines:
        lines.extend(["", "暂时补不上的原因："])
        for item in needs_decision_lines[:2]:
            lines.append(f"- {item}。")

    if not tier_text and total <= 0 and not missing_tiers and not ready_lines and not needs_decision_lines:
        problems = _review_fallback_problem_text(facts.get("main_problems"), limit=2)
        if problems:
            lines.append(f"- 当前主要卡在：{problems}。")
        else:
            lines.append("- 这轮先拿到的是能不能补齐的边界判断，还没有形成可以直接执行的完整调整清单。")

    lines.extend([
        "",
        "如果你想继续处理，可以先放宽地域、专业或院校层次范围后再让我重新审查；需要改方案时，我会先列出预览，确认前不会改动当前方案。",
    ])
    return lines


def _shortage_boundary_fix_proposal_lines(fix_facts: dict[str, Any]) -> tuple[list[str], list[str]]:
    ready: list[str] = []
    needs_decision: list[str] = []
    proposals = fix_facts.get("proposals") if isinstance(fix_facts.get("proposals"), list) else []
    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        strategy = str(proposal.get("strategy") or "").strip()
        strategy_label = _FIX_PROPOSAL_STRATEGY_TEXT.get(strategy, "")
        if strategy == "fill_probability_gap":
            strategy_label = "补一段更合适的录取概率区间"
        if not strategy_label:
            strategy_label = "这个方向"
        status = str(proposal.get("status") or "").strip()
        detail = ""
        if status == "ready":
            action_summaries = [
                _clean_review_fallback_text(item)
                for item in (proposal.get("action_summaries") or proposal.get("actionSummaries") or [])[:1]
                if _clean_review_fallback_text(item)
            ]
            detail = action_summaries[0] if action_summaries else _clean_review_fallback_text(proposal.get("summary"))
        else:
            detail = _review_fallback_proposal_reason(proposal)
        line = strategy_label
        if detail and _compact_plan_reply_text(detail) != _compact_plan_reply_text(strategy_label):
            line += f"：{detail}"
        target = ready if status == "ready" else needs_decision
        if line not in target:
            target.append(line)
    return ready[:2], needs_decision[:2]


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
        lines.extend(["我看了能不能直接补齐或调整，当前还没有足够合适的调整预览。"])

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
    if compact.count("当前候选志愿里") >= 3 or compact.count("建议你先") >= 4:
        return True
    facts = result.get("facts") if isinstance(result.get("facts"), dict) else {}
    explicit_target_issue_codes = facts.get("target_issue_codes") or facts.get("targetIssueCodes") or []
    if explicit_target_issue_codes:
        return False
    risk_count = _as_int(facts.get("risk_count"))
    warn_count = _as_int(facts.get("warn_count"))
    main_problems = [
        _clean_review_fallback_text(item)
        for item in (facts.get("main_problems") or [])
        if _clean_review_fallback_text(item)
    ]
    if risk_count + warn_count > 1:
        has_review_count = bool(re.search(r"风险\s*\d+\s*项", reply) and re.search(r"提醒\s*\d+\s*项", reply))
        mentioned_problem_count = 0
        for problem in main_problems[:4]:
            problem_compact = _compact_plan_reply_text(problem)
            if problem_compact and problem_compact in compact:
                mentioned_problem_count += 1
        if not has_review_count and main_problems and mentioned_problem_count < min(2, len(main_problems)):
            return True
    return False


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
    wants_reason = any(marker in compact for marker in ("为什么", "原因", "处理不了", "不能处理", "没法处理", "怎么处理", "怎么调", "怎么改"))
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
    if str(result.get("action_family") or "").strip() == "review_plan" and result_kind == "error":
        summary = _clean_review_fallback_text(result.get("summary"))
        lines = [
            "这轮没有拿到完整的方案审查结果，当前方案不会因为这次回复发生变化。",
        ]
        if summary and "调整预览" not in summary:
            lines.append(summary)
        lines.append("你可以稍后重新审查，或直接说想重点看哪类风险，我再按当前方案重新检查。")
        return _sanitize_reply_for_user(_normalize_user_facing_terms("\n".join(lines)))
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
    plan_query_lines = _build_plan_query_fallback_lines(result, summary=summary)
    if plan_query_lines is not None:
        return _sanitize_reply_for_user(_normalize_user_facing_terms("\n".join(plan_query_lines)))

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


def _plan_query_projection_mode(facts: dict[str, Any]) -> str:
    dsl = facts.get("plan_query_dsl") if isinstance(facts.get("plan_query_dsl"), dict) else {}
    projection = dsl.get("projection") if isinstance(dsl.get("projection"), dict) else {}
    return str(projection.get("mode") or "").strip()


def _plan_query_focus(facts: dict[str, Any], result: dict[str, Any]) -> set[str]:
    focus: list[Any] = []
    if isinstance(result.get("reply_focus"), list):
        focus.extend(result.get("reply_focus") or [])
    requested = facts.get("requested_reply_focus") if isinstance(facts.get("requested_reply_focus"), list) else []
    focus.extend(requested)
    mode = _plan_query_projection_mode(facts)
    if mode:
        focus.append(mode)
    return {str(item or "").strip() for item in focus if str(item or "").strip()}


def _format_query_filter_values(values: Any) -> str:
    if values is None:
        return ""
    if isinstance(values, list):
        cleaned = [str(item or "").strip() for item in values if str(item or "").strip()]
    else:
        text = str(values or "").strip()
        cleaned = [text] if text else []
    if not cleaned:
        return ""
    return "、".join(dict.fromkeys(cleaned))


def _plan_query_filter_summary(facts: dict[str, Any]) -> str:
    filters: dict[str, Any] = {}
    query_filters = facts.get("query_filters")
    if isinstance(query_filters, dict):
        filters.update(query_filters)
    dsl = facts.get("plan_query_dsl") if isinstance(facts.get("plan_query_dsl"), dict) else {}
    dsl_filters = dsl.get("filters") if isinstance(dsl.get("filters"), dict) else {}
    for key, value in dsl_filters.items():
        filters.setdefault(key, value)

    parts: list[str] = []
    tier_text = _format_query_filter_values(filters.get("tiers") or filters.get("tier"))
    if tier_text:
        parts.append(f"档位：{tier_text}")
    province_text = _format_query_filter_values(filters.get("province_names") or filters.get("province_keyword"))
    if province_text:
        parts.append(f"省份：{province_text}")
    city_text = _format_query_filter_values(filters.get("city_names") or filters.get("city_keyword"))
    if city_text:
        parts.append(f"城市：{city_text}")
    school_text = _format_query_filter_values(filters.get("school_keywords") or filters.get("school_keyword"))
    if school_text:
        parts.append(f"院校关键词：{school_text}")
    major_text = _format_query_filter_values(filters.get("major_keywords") or filters.get("major_keyword"))
    if major_text:
        parts.append(f"专业关键词：{major_text}")
    school_tag_text = _format_query_filter_values(filters.get("school_tags"))
    if school_tag_text:
        parts.append(f"院校标签：{school_tag_text}")
    major_tag_text = _format_query_filter_values(filters.get("major_tags"))
    if major_tag_text:
        parts.append(f"专业标签：{major_tag_text}")
    min_tuition = filters.get("min_tuition_per_year")
    if min_tuition:
        parts.append(f"学费：不低于{min_tuition}元/年")
    max_tuition = filters.get("max_tuition_per_year")
    if max_tuition:
        parts.append(f"学费：不超过{max_tuition}元/年")
    return "；".join(parts)


def _summary_indicates_no_query_result(summary: str) -> bool:
    text = str(summary or "")
    return any(marker in text for marker in ("命中数量：0", "没有候选结果", "暂时没有命中", "没有命中符合"))


def _build_plan_query_fallback_lines(result: dict[str, Any], *, summary: str) -> list[str] | None:
    facts = result.get("facts") if isinstance(result.get("facts"), dict) else {}
    focus = _plan_query_focus(facts, result)
    if not focus:
        return None
    result_kind = str(result.get("result_kind") or "").strip()
    if result_kind == "status_overview" and "count_summary" in focus:
        current_total = int(facts.get("current_total") or 0)
        target_total = int(facts.get("target_total") or 0)
        tier_text = _format_status_tier_counts(facts.get("tier_counts"))
        if current_total <= 0:
            return ["当前还没有生成正式方案。"]
        target = target_total or current_total
        lines = [f"当前方案一共有 {current_total}/{target} 个志愿。"]
        if tier_text:
            lines.append(f"冲稳保分布：{tier_text}。")
        gap_hint = str(facts.get("count_gap_hint") or "").strip()
        if gap_hint:
            lines.append(gap_hint)
        return lines
    if result_kind in {"ordered_snapshot", "candidate_snapshot"} and (
        focus & {"school_list_query", "school_presence_query", "plan_slice_query", "candidate_slice_query", "plan_filter_query", "tuition", "safety_check"}
    ):
        lines = [summary]
        filter_summary = _plan_query_filter_summary(facts)
        if filter_summary:
            if _summary_indicates_no_query_result(summary):
                lines.append(f"我这次按这些条件查：{filter_summary}，暂时没有命中结果。")
            elif result_kind == "candidate_snapshot" or "school_list_query" in focus or "school_presence_query" in focus:
                lines.append(f"查询条件：{filter_summary}。")
        if "safety_check" in focus:
            facts_tier = str(facts.get("tier") or "").strip()
            matched_count = int(facts.get("matched_count") or 0)
            if facts_tier and matched_count > 0:
                lines.append(f"这次判断基于当前命中的 {matched_count} 条{facts_tier}档结果；是否足够安全仍以录取率梯度和审查结果一起看。")
        return lines
    return None


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


def _replace_text_reply(messages: list[Any] | None, old_reply: str, new_reply: str) -> None:
    if old_reply == new_reply:
        return
    for message in messages or []:
        if not isinstance(message, ModelResponse):
            continue
        for part in getattr(message, "parts", []) or []:
            if isinstance(part, TextPart) and part.content == old_reply:
                part.content = new_reply


@dataclass
class _StructuredPlanRerouteResult:
    reply: str
    messages: list[Any]
    route_decision: dict[str, Any]
    pending_result: _RuntimeCompiledPendingResult | None = None
    workspace_refresh_targets: list[str] = field(default_factory=list)


def _reply_looks_like_unbacked_plan_action_boundary(reply: str) -> bool:
    return proposal_compiler.runtime_reply_looks_like_unbacked_plan_action_boundary(reply)


def _latest_direct_confirm_pending_payload(
    messages: list[Any] | None,
) -> tuple[dict[str, Any], str] | None:
    for part in reversed(_iter_tool_return_parts(messages)):
        tool_name = str(part.tool_name or "").strip()
        payload = _parse_tool_return_json(part.content)
        if not isinstance(payload, dict):
            continue
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        if str(payload.get("next_step") or "").strip() != "confirm":
            continue
        if not data.get("pending_created"):
            continue
        pending_id = str(data.get("pending_id") or data.get("pendingId") or "").strip()
        if not pending_id:
            continue
        return payload, tool_name
    return None


def _pending_id_from_tool_payload(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    return str(data.get("pending_id") or data.get("pendingId") or "").strip()


def _pending_version_from_tool_payload(payload: dict[str, Any] | None) -> int | None:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    for value in (
        data.get("pending_version"),
        data.get("pendingVersion"),
        data.get("source_backend_version"),
        data.get("sourceBackendVersion"),
    ):
        version = _as_int(value)
        if version >= 0 and value is not None:
            return version
    return None


def _pending_state_from_sandbox(
    request_context: RequestContext,
    *,
    pending_id: str,
) -> dict[str, Any] | None:
    sandbox = getattr(request_context, "sandbox", None)
    if sandbox is None:
        return None
    pending_file = sandbox.peek("pending.json")
    if not isinstance(pending_file, dict):
        return None
    raw = pending_file.get("raw")
    if not isinstance(raw, dict):
        return None
    if str(raw.get("status") or "").strip() != "active":
        return None
    raw_pending_id = str(raw.get("pendingId") or raw.get("pending_id") or "").strip()
    if pending_id and raw_pending_id and raw_pending_id != pending_id:
        return None
    return raw


def _clean_structured_pending_card_text(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"[\s。；;，,]*(?:采纳/)?确认前不会生效[。.!！]*", "", cleaned).strip()
    cleaned = re.sub(r"[\s。；;，,]*点[“\"]?采纳[”\"]?前不会生效[。.!！]*", "", cleaned).strip()
    cleaned = re.sub(r"[\s。；;，,]*确认后我会执行这次方案调整[。.!！]*", "", cleaned).strip()
    return cleaned


def _build_structured_intent_pending_card(
    session_id: str,
    pending_state: dict[str, Any],
    *,
    fallback_summary: str = "",
) -> WSResponse | None:
    if not isinstance(pending_state, dict):
        return None
    pending_id = str(pending_state.get("pendingId") or pending_state.get("pending_id") or "").strip()
    if not pending_id:
        return None
    if str(pending_state.get("kind") or "").strip() != "intent_change":
        return None
    execution_payload = pending_state.get("executionPayload")
    if not isinstance(execution_payload, dict):
        execution_payload = {}
    selected_data = execution_payload.get("selectedData")
    if not isinstance(selected_data, dict):
        selected_data = {}
    intent_mode = str(
        execution_payload.get("intentMode")
        or selected_data.get("intentMode")
        or "constraint"
    ).strip() or "constraint"
    if intent_mode != "constraint":
        intent_mode = "constraint"
    constraint_intent_type = str(
        execution_payload.get("constraintIntentType")
        or execution_payload.get("constraint_intent_type")
        or selected_data.get("constraintIntentType")
        or selected_data.get("constraint_intent_type")
        or "default"
    ).strip() or "default"
    summary = _clean_structured_pending_card_text(
        str(pending_state.get("summary") or fallback_summary or "").strip()
    )
    if not summary:
        merged = execution_payload.get("merged")
        if isinstance(merged, dict):
            summary = _clean_structured_pending_card_text(
                _summarize_intent_values(
                    merged,
                    intent_mode=intent_mode,
                    constraint_intent_type=constraint_intent_type,
                )
            )
    if not summary:
        summary = "本次选择的报考要求。"
    impact_payload = execution_payload.get("merged") if isinstance(execution_payload.get("merged"), dict) else {}
    if constraint_intent_type:
        impact_payload = {
            **impact_payload,
            "constraintIntentType": constraint_intent_type,
        }
    payload = {
        "type": "pendingConfirmationCard",
        "pendingId": pending_id,
        "kind": "intent_change",
        "actionFamily": str(pending_state.get("actionFamily") or "apply_selected_intents").strip()
        or "apply_selected_intents",
        "intentMode": "constraint",
        "title": "采纳这次报考条件",
        "summary": summary,
        "content": _format_intent_card_content(summary),
        "constraintIntentType": constraint_intent_type,
        "clickable": True,
        "status": "active",
        "confirmText": "采纳",
        "cancelText": "暂不采纳",
        "impactTitle": "采纳后的作用",
        "impact": _format_intent_card_impact(
            impact_payload,
            intent_mode=intent_mode,
        ),
    }
    return WSResponse(
        type="pendingConfirmationCard",
        session_id=session_id,
        content=json.dumps(payload, ensure_ascii=False),
    )


def _build_structured_plan_pending_card(
    session_id: str,
    pending_state: dict[str, Any],
    *,
    fallback_summary: str = "",
) -> WSResponse | None:
    if not isinstance(pending_state, dict):
        return None
    pending_id = str(pending_state.get("pendingId") or pending_state.get("pending_id") or "").strip()
    if not pending_id:
        return None
    kind = str(pending_state.get("kind") or "").strip()
    if not _is_plan_pending_kind(kind):
        return None
    action_family = str(pending_state.get("actionFamily") or pending_state.get("action_family") or "").strip()
    summary = _clean_structured_pending_card_text(
        str(pending_state.get("summary") or fallback_summary or "").strip()
    )
    affected_scope = _clean_structured_pending_card_text(
        str(pending_state.get("affectedScope") or pending_state.get("affected_scope") or "").strip()
    )
    content = summary or affected_scope or "确认后会执行本次方案调整。"
    if affected_scope and affected_scope not in content:
        content = f"{content}\n\n影响范围：{affected_scope}"
    title_by_action = {
        "add_units": "确认加入方案",
        "remove_units": "确认移出志愿",
        "remove_ordered_unit": "确认移出志愿",
        "replace_units": "确认替换志愿",
        "move_unit": "确认移动志愿",
        "move_ordered_unit": "确认移动志愿",
        "sort_ordered_plan": "确认方案排序",
        "regenerate_order": "确认重排方案",
        "generate_plan": "确认生成方案",
    }
    payload = {
        "type": "pendingConfirmationCard",
        "pendingId": pending_id,
        "kind": kind,
        "actionFamily": action_family,
        "title": title_by_action.get(action_family) or "请确认本次方案调整",
        "summary": summary or "确认后会执行本次方案调整。",
        "content": content,
        "impactTitle": "确认说明",
        "impact": "确认前不会改动当前方案；点“确认执行”后才会按这次预览处理。",
        "clickable": True,
        "status": "active",
        "confirmText": "确认执行",
        "cancelText": "暂不执行",
    }
    return WSResponse(
        type="pendingConfirmationCard",
        session_id=session_id,
        content=json.dumps(payload, ensure_ascii=False),
    )


def _build_structured_pending_card(
    session_id: str,
    pending_state: dict[str, Any],
    *,
    fallback_summary: str = "",
) -> WSResponse | None:
    kind = str((pending_state or {}).get("kind") or "").strip()
    if kind == "intent_change":
        return _build_structured_intent_pending_card(
            session_id,
            pending_state,
            fallback_summary=fallback_summary,
        )
    if _is_plan_pending_kind(kind):
        return _build_structured_plan_pending_card(
            session_id,
            pending_state,
            fallback_summary=fallback_summary,
        )
    return None


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
        self.zhiyuan_agent: ZhiyuanAgent = ZhiyuanAgent(llm_client)
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

    async def _maybe_handle_no_plan_boundary_guard(
        self,
        *,
        session_id: str,
        user_id: str,
        content: str,
        history: list[Any] | None,
        request_context: RequestContext,
        planning_summary: PlanningSummary | dict[str, Any] | None,
        pending_state: dict[str, Any] | None,
        recent_intent_summary: str,
        turn_started_at: float,
    ) -> str | None:
        boundary_summary = _planning_summary_for_boundary_guard(planning_summary)
        no_formal_plan_review = proposal_compiler.resolve_no_formal_plan_review_boundary(
            content,
            planning_summary=boundary_summary,
        )
        if no_formal_plan_review.side_effect == "readonly":
            reply = _no_formal_plan_review_boundary_reply(content, pending_state=pending_state)
            turn_event = {
                "sessionId": session_id,
                "userId": user_id,
                "scene": "plan",
                "routingPath": "no_formal_plan_review_boundary",
                "routeDecision": {
                    "source": "proposal_compiler",
                    "matched": True,
                    "route": no_formal_plan_review.side_effect,
                    "sideEffect": no_formal_plan_review.side_effect,
                    "referenceResolution": no_formal_plan_review.reference_resolution,
                    "replyFocus": list(no_formal_plan_review.reply_focus),
                    "blockingReasons": list(no_formal_plan_review.blocking_reasons),
                },
                "pendingType": None,
                "actionFamily": None,
                "totalDurationMs": int((time.monotonic() - turn_started_at) * 1000),
                "status": "success",
                "errorType": None,
            }
            await _save_direct_guard_history(
                self.history_store,
                session_id,
                history,
                content,
                reply,
                model_name="no-formal-plan-review-boundary",
                turn_event=turn_event,
                request_context=request_context,
                user_id=user_id,
            )
            _log_conversation_turn_event(**turn_event)
            return reply

        needs_plan_first_resolution = proposal_compiler.resolve_needs_plan_first_guard(
            content,
            planning_summary=boundary_summary,
            recent_intent_summary=recent_intent_summary,
        )
        if needs_plan_first_resolution.side_effect != "needs_plan_first":
            return None
        reply = _needs_plan_first_guard_reply(content, needs_plan_first_resolution)
        turn_event = {
            "sessionId": session_id,
            "userId": user_id,
            "scene": "plan",
            "routingPath": "needs_plan_first_guard",
            "routeDecision": {
                "source": "proposal_compiler",
                "matched": True,
                "route": needs_plan_first_resolution.side_effect,
                "referenceResolution": needs_plan_first_resolution.reference_resolution,
                "targetIssues": list(needs_plan_first_resolution.target_issues),
                "displayPayload": dict(needs_plan_first_resolution.display_payload),
                "replyPlan": dict(needs_plan_first_resolution.reply_plan),
                "blockingReasons": list(needs_plan_first_resolution.blocking_reasons),
            },
            "pendingType": None,
            "actionFamily": None,
            "totalDurationMs": int((time.monotonic() - turn_started_at) * 1000),
            "status": "success",
            "errorType": None,
        }
        await _save_direct_guard_history(
            self.history_store,
            session_id,
            history,
            content,
            reply,
            model_name="needs-plan-first-guard",
            turn_event=turn_event,
            request_context=request_context,
            user_id=user_id,
        )
        _log_conversation_turn_event(**turn_event)
        return reply

    async def _pending_state_for_direct_card(
        self,
        *,
        session_id: str,
        request_context: RequestContext,
        pending_id: str,
        pending_version: int | None = None,
    ) -> dict[str, Any] | None:
        if pending_version is not None:
            pending_state = await _load_pending_confirmation_state_at_version(session_id, pending_version)
            if isinstance(pending_state, dict):
                if str(pending_state.get("status") or "").strip() == "active":
                    loaded_pending_id = str(
                        pending_state.get("pendingId") or pending_state.get("pending_id") or ""
                    ).strip()
                    if not pending_id or not loaded_pending_id or pending_id == loaded_pending_id:
                        return pending_state
        pending_state = _pending_state_from_sandbox(request_context, pending_id=pending_id)
        if isinstance(pending_state, dict):
            return pending_state
        pending_state = await _load_pending_confirmation_state(session_id)
        if not isinstance(pending_state, dict):
            return None
        if str(pending_state.get("status") or "").strip() != "active":
            return None
        loaded_pending_id = str(pending_state.get("pendingId") or pending_state.get("pending_id") or "").strip()
        if pending_id and loaded_pending_id and pending_id != loaded_pending_id:
            return None
        return pending_state

    async def _handle_zhiyuan_agent_direct_pending_short_text(
        self,
        *,
        session_id: str,
        user_id: str,
        content: str,
        history: list[Any] | None,
        request_context: RequestContext,
        turn_started_at: float,
        action: str,
    ) -> str | ChatServiceResponseEnvelope | None:
        active_pending = resolve_pending_confirmation(request_context)
        normalized_action = str(action or "").strip()
        if normalized_action not in {"confirm", "cancel"}:
            return None

        result_text = await zhiyuan_agent_confirm_pending(
            SimpleNamespace(deps=request_context),
            action=normalized_action,
        )
        result = _parse_tool_return_json(result_text) or {}
        result_data = result.get("data") if isinstance(result.get("data"), dict) else {}
        reply = str(result.get("message") or "").strip()
        if not reply:
            reply = "已处理本次待确认内容。" if normalized_action == "confirm" else "已取消本次待确认内容。"
        reply = _sanitize_reply_for_user(reply)

        has_active_pending = active_pending is not None and result_data.get("active") is not False
        pending_kind = str(result_data.get("kind") or getattr(active_pending, "kind", "") or "").strip()
        action_family = str(
            result_data.get("action_family")
            or getattr(active_pending, "action_family", "")
            or ""
        ).strip()
        pending_type = _pending_type_from_kind(pending_kind, has_active_pending=has_active_pending)
        if normalized_action == "confirm":
            routing_path = "direct_no_pending_short_text_confirm" if pending_type == "none" else _direct_confirm_routing_path(result)
        else:
            routing_path = (
                "direct_no_pending_short_text_cancel"
                if pending_type == "none"
                else f"pending_{pending_type}_short_text_confirm"
                if pending_type != "unknown"
                else "pending_short_text_confirm"
            )
        workspace_refresh_targets = _direct_confirm_workspace_refresh_targets(result)

        tool_call_id = f"direct-short-text-{action_family or pending_type}-{normalized_action}"
        new_messages = [
            ModelRequest(parts=[UserPromptPart(content=content)]),
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="confirm_pending",
                        args={"action": normalized_action},
                        tool_call_id=tool_call_id,
                    )
                ],
                model_name="zhiyuan-agent-direct-short-text",
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="confirm_pending",
                        content=result_text,
                        tool_call_id=tool_call_id,
                    )
                ]
            ),
            ModelResponse(parts=[TextPart(content=reply)], model_name="zhiyuan-agent-direct-short-text"),
        ]
        total_duration_ms = int((time.monotonic() - turn_started_at) * 1000)
        turn_event = {
            "sessionId": session_id,
            "userId": user_id,
            "scene": pending_type if pending_type in {"plan", "intent", "none"} else "unknown",
            "routingPath": routing_path,
            "routeDecision": {
                "source": "zhiyuan_agent",
                "matched": True,
                "route": "direct_confirm_pending_short_text",
                "firstToolNames": ["confirm_pending"],
                "confirmToolName": "confirm_pending",
                "agentRun": {
                    "promptLength": len(content or ""),
                    "historyLength": 0,
                    "completed": True,
                    "requests": 0,
                    "toolCalls": 1,
                    "firstToolNames": ["confirm_pending"],
                    "toolNameCounts": {"confirm_pending": 1},
                    "directShortTextBridge": True,
                    "hadActivePending": has_active_pending,
                },
            },
            "pendingType": pending_type if pending_type in {"plan", "intent", "none"} else None,
            "actionFamily": action_family or None,
            "modelProvider": _llm_config_value(self.llm_client, "provider"),
            "modelName": _llm_config_value(self.llm_client, "model_name"),
            "llmRequests": 0,
            "inputTokens": None,
            "outputTokens": None,
            "totalTokens": None,
            "toolCallCount": 1,
            "totalDurationMs": total_duration_ms,
            "directAgentDurationMs": 0,
            **_observability_timing_fields(request_context),
            "toolCalls": _summarize_tool_calls_for_observability(
                _iter_tool_call_parts(new_messages),
                _iter_tool_return_parts(new_messages),
            ),
            "postProcessingApplied": [
                "zhiyuan_agent_direct",
                "direct_pending_short_text_bridge" if has_active_pending else "direct_no_pending_short_text_bridge",
            ],
            "status": "success",
            "errorType": None,
        }
        _log_conversation_turn_event(**turn_event)
        try:
            history_to_save = list(history or [])
            history_to_save.extend(
                _append_turn_observability_messages(
                    new_messages,
                    turn_event,
                    request_context=request_context,
                    session_id=session_id,
                    user_id=user_id,
                    prompt_length=len(content or ""),
                )
            )
            await self.history_store.save(session_id, history_to_save)
        except Exception:
            logger.exception("Failed to save ZhiyuanAgent direct short-text pending history: session_id=%s", session_id)

        if workspace_refresh_targets:
            return ChatServiceResponseEnvelope(
                primary=reply,
                followups=[
                    _build_pending_apply_workspace_refresh_response(
                        session_id,
                        target,
                        pending_kind=pending_kind,
                        action_family=action_family,
                    )
                    for target in _dedupe_workspace_targets(workspace_refresh_targets)
                ],
            )
        return reply

    async def _maybe_handle_zhiyuan_agent_direct_route(
        self,
        *,
        session_id: str,
        user_id: str,
        content: str,
        history: list[Any] | None,
        request_context: RequestContext,
        message_history: list[Any] | None,
        turn_started_at: float,
        on_progress: ProgressCallback | None,
    ) -> str | ChatServiceResponseEnvelope:
        direct_started_at = time.monotonic()
        active_pending = resolve_pending_confirmation(request_context)
        short_pending_action = (
            _pending_short_text_action(content)
            if active_pending
            else _no_pending_short_text_action(content)
        )
        if short_pending_action:
            short_pending_reply = await self._handle_zhiyuan_agent_direct_pending_short_text(
                session_id=session_id,
                user_id=user_id,
                content=content,
                history=history,
                request_context=request_context,
                turn_started_at=turn_started_at,
                action=short_pending_action,
            )
            if short_pending_reply is not None:
                return short_pending_reply
        try:
            run_coro = self.zhiyuan_agent.run_with_message_deltas(
                user_prompt=content,
                message_history=message_history,
                deps=request_context,
                on_progress=on_progress,
            )
            if _ZHIYUAN_AGENT_DIRECT_TIMEOUT_SECONDS > 0:
                reply, new_messages, all_messages, usage = await asyncio.wait_for(
                    run_coro,
                    timeout=_ZHIYUAN_AGENT_DIRECT_TIMEOUT_SECONDS,
                )
            else:
                reply, new_messages, all_messages, usage = await run_coro
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            total_duration_ms = int((time.monotonic() - turn_started_at) * 1000)
            safe_reply = "这轮处理没有完成，请稍后重试。没有明确确认前，不会改动报考条件或方案。"
            new_messages = [
                ModelRequest(parts=[UserPromptPart(content=content)]),
                ModelResponse(parts=[TextPart(content=safe_reply)], model_name="zhiyuan-agent-direct-error"),
            ]
            turn_event = {
                "sessionId": session_id,
                "userId": user_id,
                "scene": "unknown",
                "routingPath": "zhiyuan_agent_direct",
                "routeDecision": {
                    "source": "zhiyuan_agent",
                    "matched": True,
                    "route": "direct",
                    "error": type(exc).__name__,
                },
                "pendingType": None,
                "actionFamily": None,
                "modelProvider": _llm_config_value(self.llm_client, "provider"),
                "modelName": _llm_config_value(self.llm_client, "model_name"),
                "totalDurationMs": total_duration_ms,
                "directAgentDurationMs": int((time.monotonic() - direct_started_at) * 1000),
                **_observability_timing_fields(request_context),
                "toolCalls": [],
                "postProcessingApplied": ["zhiyuan_agent_direct"],
                "status": "error",
                "errorType": type(exc).__name__,
            }
            _log_conversation_turn_event(**turn_event)
            try:
                history_to_save = list(history or [])
                history_to_save.extend(
                    _append_turn_observability_messages(
                        new_messages,
                        turn_event,
                        request_context=request_context,
                        session_id=session_id,
                        user_id=user_id,
                        prompt_length=len(content or ""),
                    )
                )
                await self.history_store.save(session_id, history_to_save)
            except Exception:
                logger.exception("Failed to save ZhiyuanAgent direct error history: session_id=%s", session_id)
            logger.warning(
                "ZhiyuanAgent direct route failed: session_id=%s error=%s",
                session_id,
                type(exc).__name__,
                exc_info=not isinstance(exc, asyncio.TimeoutError),
            )
            return safe_reply

        tracker = self._usage_trackers.get(session_id)
        if tracker is None:
            tracker = UsageTracker(session_id=session_id)
            self._usage_trackers[session_id] = tracker
        tracker.record(usage)

        pending_card: WSResponse | None = None
        pending_state: dict[str, Any] | None = None
        pending_payload_info = _latest_direct_confirm_pending_payload(new_messages)
        pending_tool_name = ""
        if pending_payload_info is not None:
            pending_payload, pending_tool_name = pending_payload_info
            pending_id = _pending_id_from_tool_payload(pending_payload)
            pending_version = _pending_version_from_tool_payload(pending_payload)
            pending_state = await self._pending_state_for_direct_card(
                session_id=session_id,
                request_context=request_context,
                pending_id=pending_id,
                pending_version=pending_version,
            )
            if isinstance(pending_state, dict):
                pending_card = _build_structured_pending_card(
                    session_id,
                    pending_state,
                    fallback_summary=str(pending_payload.get("message") or ""),
                )

        final_reply = str(reply or "").strip()
        if pending_card is not None:
            primary_from_card = _pending_confirmation_primary_reply_from_card(pending_card)
            use_card_primary = final_reply in {"", "已完成处理。", "已完成处理"}
            if primary_from_card and use_card_primary:
                if final_reply:
                    _replace_text_reply(new_messages, final_reply, primary_from_card)
                    _replace_text_reply(all_messages, final_reply, primary_from_card)
                final_reply = primary_from_card
        final_reply = _sanitize_reply_for_user(final_reply or "已完成处理。")

        tool_calls = _iter_tool_call_parts(new_messages)
        tool_returns = _iter_tool_return_parts(new_messages)
        observed_tool_calls = _summarize_tool_calls_for_observability(tool_calls, tool_returns)
        confirm_pending_result = _latest_confirm_pending_tool_result(tool_calls, tool_returns)
        direct_routing_path = _direct_confirm_routing_path(confirm_pending_result)
        direct_workspace_refresh_targets = _direct_confirm_workspace_refresh_targets(confirm_pending_result)
        post_processing_applied = ["zhiyuan_agent_direct"]
        if pending_card is None and not direct_workspace_refresh_targets:
            guarded_reply = _sanitize_reply_for_user(_guard_unbacked_plan_confirmation_reply(final_reply, new_messages))
            if guarded_reply != final_reply:
                raw_reply = str(reply or "").strip()
                _replace_text_reply(new_messages, raw_reply, guarded_reply)
                _replace_text_reply(all_messages, raw_reply, guarded_reply)
                _replace_text_reply(new_messages, final_reply, guarded_reply)
                _replace_text_reply(all_messages, final_reply, guarded_reply)
                final_reply = guarded_reply
                post_processing_applied.append("unbacked_plan_confirmation_reply_guard")
        pending_kind = str((pending_state or {}).get("kind") or "").strip()
        if not pending_kind and isinstance(confirm_pending_result.get("data"), dict):
            pending_kind = str(confirm_pending_result["data"].get("kind") or "").strip()
        action_family = str((pending_state or {}).get("actionFamily") or "").strip() or None
        if not action_family and isinstance(confirm_pending_result.get("data"), dict):
            action_family = str(confirm_pending_result["data"].get("action_family") or "").strip() or None
        scene = _pending_type_from_kind(pending_kind)
        total_duration_ms = int((time.monotonic() - turn_started_at) * 1000)
        turn_event = {
            "sessionId": session_id,
            "userId": user_id,
            "scene": scene,
            "routingPath": direct_routing_path,
            "routeDecision": {
                "source": "zhiyuan_agent",
                "matched": True,
                "route": "direct_confirm_pending" if direct_routing_path != "zhiyuan_agent_direct" else "direct",
                "firstToolNames": [part.tool_name for part in tool_calls[:1]],
                "confirmToolName": pending_tool_name or None,
                "agentRun": dict(getattr(request_context, "agent_observability", {}) or {}),
            },
            "pendingType": scene if scene in {"plan", "intent"} else None,
            "actionFamily": action_family,
            "modelProvider": _llm_config_value(self.llm_client, "provider"),
            "modelName": _llm_config_value(self.llm_client, "model_name"),
            "llmRequests": getattr(usage, "requests", None),
            "inputTokens": getattr(usage, "input_tokens", None),
            "outputTokens": getattr(usage, "output_tokens", None),
            "totalTokens": getattr(usage, "total_tokens", None),
            "toolCallCount": getattr(usage, "tool_calls", None),
            "totalDurationMs": total_duration_ms,
            "directAgentDurationMs": int((time.monotonic() - direct_started_at) * 1000),
            **_observability_timing_fields(request_context),
            "toolCalls": observed_tool_calls,
            "postProcessingApplied": post_processing_applied,
            "status": "success",
            "errorType": None,
        }
        _log_conversation_turn_event(**turn_event)
        try:
            history_to_save = list(history or [])
            history_to_save.extend(
                _append_turn_observability_messages(
                    list(new_messages),
                    turn_event,
                    request_context=request_context,
                    session_id=session_id,
                    user_id=user_id,
                    prompt_length=len(content or ""),
                )
            )
            await self.history_store.save(session_id, history_to_save)
        except Exception:
            logger.exception("Failed to save ZhiyuanAgent direct history: session_id=%s", session_id)

        if pending_card is not None:
            return ChatServiceResponseEnvelope(
                primary=final_reply,
                followups=[pending_card],
            )
        if direct_workspace_refresh_targets:
            return ChatServiceResponseEnvelope(
                primary=final_reply,
                followups=[
                    _build_silent_workspace_refresh_response(session_id, target)
                    for target in _dedupe_workspace_targets(direct_workspace_refresh_targets)
                ],
            )
        return final_reply

    async def handle_message(
        self, session_id: str, user_id: str, content: str,
        batch: str | None = None,
        score_detail: dict | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> str | WSResponse | ChatServiceResponseEnvelope:
        """处理一条用户消息，返回 Agent 回复（str 或 WSResponse）。"""
        turn_started_at = time.monotonic()
        context_progress_sent = False

        async def _safe_result(awaitable: Any) -> Any:
            try:
                return await awaitable
            except Exception as exc:
                return exc

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

        history_task = asyncio.create_task(_safe_result(self.history_store.load(session_id)))
        pending_state_task = asyncio.create_task(_safe_result(_load_pending_confirmation_state(session_id)))
        try:
            history, backend_pending_state = await asyncio.gather(
                history_task,
                pending_state_task,
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
        parsed_score_detail = _coerce_score_detail(score_detail)
        parsed_init_profile = None
        parsed_planning_summary = None
        planning_data: dict[str, Any] | None = None
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
        if conversation_phase.pending is not None and _is_plan_pending_kind(conversation_phase.pending.kind):
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
            current_user_text=content,
            batch=batch,
            score_detail=parsed_score_detail,
            init_profile=parsed_init_profile,
            planning_summary=parsed_planning_summary,
            sandbox=build_request_sandbox(
                session_id=session_id,
                batch=batch,
                score_detail=parsed_score_detail,
                init_profile=parsed_init_profile,
                planning_state=planning_data if isinstance(planning_data, dict) else None,
                planning_summary=parsed_planning_summary,
                pending_state=backend_pending_state if isinstance(backend_pending_state, dict) else None,
                pending=backend_pending,
            ),
            conversation_phase=conversation_phase,
            progress_callback=on_progress,
            allow_explore_inner_llm=False,
            enable_intent_side_effect_arbitration=True,
            recent_intent_analysis=recent_intent_analysis,
            stale_pending_notice=stale_pending_notice,
        )
        active_pending = resolve_pending_confirmation(request_context)
        if request_context.sandbox is not None:
            await request_context.sandbox.warm(DEFAULT_WARM_PATHS)
        if active_pending is None:
            no_plan_boundary_reply = await self._maybe_handle_no_plan_boundary_guard(
                session_id=session_id,
                user_id=user_id,
                content=content,
                history=history if isinstance(history, list) else None,
                request_context=request_context,
                planning_summary=parsed_planning_summary,
                pending_state=backend_pending_state if isinstance(backend_pending_state, dict) else None,
                recent_intent_summary=_recent_intent_summary_for_no_plan_guard(
                    backend_pending_state if isinstance(backend_pending_state, dict) else None,
                    recent_intent_analysis if isinstance(recent_intent_analysis, dict) else None,
                ),
                turn_started_at=turn_started_at,
            )
            if no_plan_boundary_reply is not None:
                await finish_context_progress()
                return no_plan_boundary_reply
        zhiyuan_agent_direct_reply = await self._maybe_handle_zhiyuan_agent_direct_route(
            session_id=session_id,
            user_id=user_id,
            content=content,
            history=history if isinstance(history, list) else None,
            request_context=request_context,
            message_history=runtime_history.model_history,
            turn_started_at=turn_started_at,
            on_progress=on_progress,
        )
        await finish_context_progress()
        return zhiyuan_agent_direct_reply

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
                pending_result = await _create_pending_intent_confirmation_result_from_preview_payload(
                    session_id,
                    followup_result.analysisPayload,
                )
                pending_card = pending_result.card
                if pending_card is not None:
                    primary_text = (
                        _pending_confirmation_primary_reply_from_card(pending_card)
                        or _intent_card_primary_reply_from_preview_payload(followup_result.analysisPayload)
                    )
                    followups = [
                        _build_silent_workspace_refresh_response(session_id, target)
                        for target in pending_result.workspace_refresh_targets
                    ]
                    followups.append(pending_card)
                    return ChatServiceResponseEnvelope(
                        primary=primary_text,
                        followups=followups,
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
        raw_constraint_intent_type = selected_data.get("constraintIntentType") or selected_data.get("constraint_intent_type")
        intent_resolution = proposal_compiler.resolve_intent_select_input(
            selected_values=[item for item in selected_values if isinstance(item, dict) and item],
            merged=merged,
            intent_mode=intent_mode,
            raw_constraint_intent_type=str(raw_constraint_intent_type or "default"),
        )
        if not intent_resolution.allowed:
            logger.info(
                "Skip compiled intent select before compiled input: session_id=%s constraint=%s reasons=%s merged=%s",
                session_id,
                raw_constraint_intent_type,
                intent_resolution.blocking_reasons,
                merged,
            )
            return ChatServiceResponseEnvelope(primary="", followups=[])
        intent_mode = intent_resolution.intent_mode
        constraint_intent_type = intent_resolution.constraint_intent_type
        summary = _display_summary_from_intent_payload(selected_data) or _summarize_intent_values(
            merged,
            intent_mode=intent_mode,
            constraint_intent_type=constraint_intent_type,
        )
        if not summary:
            summary = "本次选择的要求内容。" if intent_mode == "constraint" else "本次选择的偏好内容。"
        compiled = proposal_compiler.compile_intent_select_proposal(
            session_id=session_id,
            selected_data=selected_data,
            merged=merged,
            intent_mode=intent_mode,
            batch=batch or "01",
            constraint_intent_type=constraint_intent_type,
            summary=summary,
        )
        compiled_sink_metadata = proposal_compiler.intent_sink_metadata_or_none(
            compiled,
            session_id=session_id,
            source="intent_select",
        )
        if compiled_sink_metadata is None:
            return "这次待采纳内容缺少校验信息，请重新选择后再试。"
        return await _create_pending_intent_confirmation_response(
            session_id=session_id,
            selected_data=selected_data,
            merged=merged,
            intent_mode=intent_mode,
            batch=batch or "01",
            compiled_sink_metadata=compiled_sink_metadata,
        )

    async def _handle_structured_pending_confirmation(
        self,
        *,
        session_id: str,
        user_id: str,
        pending_state: dict[str, Any],
        pending_id: str,
        message_id: Any,
        confirmation_entry: str,
        user_prompt_content: str | None,
        confirmation_history: list[Any] | None,
        turn_started_at: float,
        post_apply_intent: str,
        post_apply_evidence_plan: dict[str, Any] | None,
        emit_pending_event: Callable[..., None],
    ) -> str | ChatServiceResponseEnvelope | None:
        execution_payload = pending_state.get("executionPayload")
        if not isinstance(execution_payload, dict):
            return None
        action_family = str(pending_state.get("actionFamily") or "").strip()
        tool_name = str(execution_payload.get("toolName") or "").strip()
        active_pending = _pending_confirmation_from_state(pending_state)
        if active_pending is None:
            return None
        if _is_plan_pending_kind(active_pending.kind):
            if action_family == "apply_fix_proposal" or tool_name == "apply_planning_fix_proposal":
                return None

        workspace_data: dict[str, Any] | None = None
        parsed_planning_summary: PlanningSummary | None = None
        try:
            workspace_response = await get_planning_workspace_state(session_id)
        except Exception:
            logger.warning(
                "Failed to fetch workspace before structured pending confirmation: session_id=%s",
                session_id,
                exc_info=True,
            )
            workspace_response = None
        if isinstance(workspace_response, dict) and workspace_response.get("code") == 0:
            raw_workspace = workspace_response.get("data")
            if isinstance(raw_workspace, dict):
                workspace_data = raw_workspace
                parsed_planning_summary = PlanningSummary.from_backend_state(workspace_data)

        conversation_phase = ConversationPhase.from_pending_confirmation(
            active_pending,
            planning_summary=parsed_planning_summary,
        )
        request_context = RequestContext(
            userid=user_id,
            sessionid=session_id,
            chat_history=[],
            current_user_text=str(user_prompt_content or ""),
            batch=str(execution_payload.get("batch") or "01"),
            planning_summary=parsed_planning_summary,
            sandbox=build_request_sandbox(
                session_id=session_id,
                batch=str(execution_payload.get("batch") or "01"),
                planning_state=workspace_data,
                planning_summary=parsed_planning_summary,
                pending_state=pending_state,
                pending=active_pending,
            ),
            conversation_phase=conversation_phase,
            allow_explore_inner_llm=False,
            confirmed_via_card=confirmation_entry == "card",
            confirmed_via_pending=True,
            confirmation_entry=confirmation_entry,
        )

        result_text = await zhiyuan_agent_confirm_pending(
            SimpleNamespace(deps=request_context),
            action="confirm",
        )
        result = _parse_tool_return_json(result_text) or {}
        result_data = result.get("data") if isinstance(result.get("data"), dict) else {}
        apply_result = result_data.get("result") if isinstance(result_data.get("result"), dict) else {}
        applied = bool(result_data.get("applied"))
        reply = str(result.get("message") or "").strip() or (
            "已执行这次方案调整。" if applied else "这次方案调整没有执行成功，请重新生成预览后再确认。"
        )
        if post_apply_intent == "apply_pending_then_readonly" and applied:
            post_apply_planning_summary = await _load_post_apply_planning_summary(session_id)
            reply = _append_pending_apply_then_readonly_result(
                reply,
                pending_state,
                post_apply_evidence_plan,
                post_apply_planning_summary,
            )
        reply = _sanitize_reply_for_user(reply)

        await _mark_pending_confirmation_message_status(
            session_id,
            message_id,
            pending_id=pending_id,
            status="applied" if applied else "expired",
        )

        result_code = (
            "applied"
            if applied
            else str(apply_result.get("reason") or result_data.get("error") or "structured_pending_apply_failed")
        )
        emit_pending_event(
            result="applied" if applied else "failed",
            result_code=result_code,
        )

        pending_type = "intent" if active_pending.kind == "intent_change" else "plan"
        scene = pending_type
        tool_call_id = f"{confirmation_entry}-{action_family or pending_type}-structured-confirm"
        new_messages = [
            ModelRequest(parts=[UserPromptPart(content=user_prompt_content or "[待确认内容]")]),
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="confirm_pending",
                        args={"action": "confirm"},
                        tool_call_id=tool_call_id,
                    )
                ],
                model_name=f"pending-confirmation-{confirmation_entry}",
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="confirm_pending",
                        content=result_text,
                        tool_call_id=tool_call_id,
                    )
                ]
            ),
            ModelResponse(parts=[TextPart(content=reply)], model_name=f"pending-confirmation-{confirmation_entry}"),
        ]
        turn_event = _pending_apply_turn_event(
            session_id=session_id,
            user_id=user_id,
            scene=scene,
            routing_path=(
                f"pending_{pending_type}_structured_short_text_confirm"
                if confirmation_entry == "short_text"
                else f"{pending_type}_structured_confirmation_card_confirm"
            ),
            pending_type=pending_type,
            action_family=action_family,
            started_at=turn_started_at,
            status="success" if applied else "error",
            error_type=None if applied else result_code,
            post_apply_evidence_plan=post_apply_evidence_plan if applied else None,
        )
        try:
            history = confirmation_history if confirmation_history is not None else await self.history_store.load(session_id) or []
            history_to_save = list(history)
            history_to_save.extend(
                _append_turn_observability_messages(
                    new_messages,
                    turn_event,
                    request_context=request_context,
                    session_id=session_id,
                    user_id=user_id,
                    prompt_length=len(user_prompt_content or ""),
                )
            )
            await self.history_store.save(session_id, history_to_save)
        except Exception:
            logger.exception("Failed to save structured pending confirmation history: session_id=%s", session_id)

        _log_conversation_turn_event(**turn_event)

        followups: list[WSResponse] = []
        if applied:
            if active_pending.kind == "intent_change":
                fallback_targets = ["ordered", "review"]
            elif action_family in {"add_units", "replace_units"}:
                fallback_targets = ["ordered", "candidate", "review"]
            else:
                fallback_targets = ["ordered", "review"]
            for target in _post_apply_evidence_workspace_targets(
                post_apply_evidence_plan,
                fallback_targets,
            ):
                followups.append(
                    _build_pending_apply_workspace_refresh_response(
                        session_id,
                        target,
                        pending_kind=active_pending.kind,
                        action_family=action_family,
                    )
                )
        if followups:
            return ChatServiceResponseEnvelope(primary=reply, followups=followups)
        return reply

    async def handle_pending_confirmation(
        self,
        session_id: str,
        user_id: str,
        content: str,
        *,
        confirmation_entry: str = "card",
        user_prompt_content: str | None = None,
        post_apply_intent: str | None = None,
        post_apply_evidence_plan: dict[str, Any] | None = None,
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
        post_apply_intent = str(post_apply_intent or "").strip()
        post_apply_evidence_plan = (
            dict(post_apply_evidence_plan)
            if post_apply_intent == "apply_pending_then_readonly" and isinstance(post_apply_evidence_plan, dict)
            else None
        )
        pending_state = await _load_pending_confirmation_state(session_id)
        turn_started_at = time.monotonic()
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

        if active_kind not in _SUPPORTED_PENDING_KINDS:
            return "这类待采纳内容暂时还不能在这里处理，请刷新后重试。"

        structured_pending_reply = await self._handle_structured_pending_confirmation(
            session_id=session_id,
            user_id=user_id,
            pending_state=pending_state,
            pending_id=pending_id,
            message_id=message_id,
            confirmation_entry=confirmation_entry,
            user_prompt_content=user_prompt_content,
            confirmation_history=confirmation_history,
            turn_started_at=turn_started_at,
            post_apply_intent=post_apply_intent,
            post_apply_evidence_plan=post_apply_evidence_plan,
            emit_pending_event=emit_pending_event,
        )
        if structured_pending_reply is not None:
            return structured_pending_reply
        if active_kind == "intent_change":
            return "这次待采纳内容缺少可执行内容，请重新生成。"

        if not _is_plan_pending_kind(active_kind):
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
                refreshed_proposal = proposal_compiler.select_ready_fix_proposal(
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
            if post_apply_intent == "apply_pending_then_readonly":
                post_apply_planning_summary = await _load_post_apply_planning_summary(session_id)
                reply = _append_pending_apply_then_readonly_result(
                    reply,
                    pending_state,
                    post_apply_evidence_plan,
                    post_apply_planning_summary,
                )
            applied_state = dict(pending_state)
            applied_state["status"] = "applied"
            applied_state["updatedAt"] = datetime.now(timezone.utc).isoformat()
            applied_state["resultCode"] = "applied"
            applied_state["resultData"] = result_data
            if post_apply_evidence_plan is not None:
                applied_state["postApplyEvidencePlan"] = post_apply_evidence_plan
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
            turn_event = _pending_apply_turn_event(
                session_id=session_id,
                user_id=user_id,
                scene="plan",
                routing_path="pending_plan_short_text_confirm" if confirmation_entry == "short_text" else "plan_confirmation_card_confirm",
                pending_type="plan",
                action_family=action_family,
                started_at=started_at,
                status="success",
                post_apply_evidence_plan=post_apply_evidence_plan,
            )
            try:
                history = confirmation_history if confirmation_history is not None else await self.history_store.load(session_id) or []
                history_to_save = list(history)
                history_to_save.extend(_append_route_observability_message(new_messages, turn_event))
                await self.history_store.save(session_id, history_to_save)
            except Exception:
                logger.exception("Failed to save pending fix proposal confirmation history: session_id=%s", session_id)

            _log_conversation_turn_event(**turn_event)
            emit_pending_event(result="applied", result_code="applied")
            followups = []
            for target in _post_apply_evidence_workspace_targets(post_apply_evidence_plan, ["ordered"]):
                if target == "ordered":
                    followups.append(
                        _build_silent_workspace_refresh_response(
                            session_id,
                            "ordered",
                            extra_payload={
                                "title": "方案已更新",
                                "content": "已按这条处理建议刷新方案，可以查看调整后的排序方案。",
                                "actionText": "查看方案",
                            },
                        )
                    )
                else:
                    followups.append(_build_silent_workspace_refresh_response(session_id, target))
            if proposal_source == "user_goal":
                already = _workspace_targets_from_followups(followups)
                if "candidate" not in already:
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
                if "review" not in already:
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

        await _mark_pending_confirmation_failed(
            session_id,
            pending_state,
            message_id,
            pending_id=pending_id,
            result_code="missing_structured_plan_payload",
        )
        emit_pending_event(result="failed", result_code="missing_structured_plan_payload")
        return "这次方案调整缺少可执行内容，请重新生成预览。"
