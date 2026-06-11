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
    _matching_major_scope_records,
)
from app.tools.plan_orchestration_models import normalize_plan_action_payload
from app.tools.intent_state_tool import (
    ANALYSIS_STAGE_CONFIRMED,
    apply_selected_intents as _apply_selected_intents,
    analyze_volunteer_intent_change,
    merge_selected_values,
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
    get_message_by_id,
    get_pending_confirmation,
    get_intent_change_cache,
    get_planning_workspace_state,
    get_user_init_profile,
    get_user_score_detail,
    save_intent_change_cache,
    save_pending_confirmation,
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
_READONLY_MUTATION_GUARD_REPLY = (
    "我按“先看、先查、不直接改”的方式处理了这轮请求，当前不会加入、删除、移动或重排方案。"
    "如果你想把某个候选真正加入方案，可以再明确说“加入方案”或指定要调整的位置，我会先给出可确认的调整预览。"
)
_UNBACKED_CONFIRM_SENTENCE_RE = re.compile(r"确认要我.*执行")
_UNBACKED_PLAN_CONFIRMATION_REPLY = (
    "这轮还没有生成可执行的调整内容，所以不会改动当前方案。"
    "如果你要继续调整，请再发一次具体要求，我会重新定位影响范围并列出调整预览；"
    "只有你点“确认执行”或直接确认当前有效预览后才会执行。"
)
_ROUTE_OBSERVABILITY_MODEL_NAME = "route-observability"
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
    "analyze_current_school_interest",
    "analyze_current_major_interest",
    "analyze_current_region_interest",
}
_USER_REPLY_ENGLISH_WORD_REPLACEMENTS = (
    (re.compile(r"\s*\bmostly\b\s*", re.IGNORECASE), "基本上"),
    (re.compile(r"\s*\bincreasingly\b\s*", re.IGNORECASE), "越来越"),
    (re.compile(r"\s*\bbaseline\b\s*", re.IGNORECASE), "基准"),
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
    pending_plan_action: dict[str, Any] | None = None,
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
    has_pending = bool(pending_plan_action)

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


_SUPPORTED_WORKSPACE_ACTION_TARGETS = {"candidate", "ordered"}


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
        await save_intent_change_cache(int(session_id), {})
    except Exception:
        logger.warning("Failed to clear legacy planEditCache: session_id=%s", session_id, exc_info=True)


def _build_plan_pending_state(
    session_id: str,
    pending_plan_action: dict[str, Any],
    *,
    replaced_pending: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pending_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    action_family = str(pending_plan_action.get("action_family") or "").strip()
    plan_payload = pending_plan_action.get("plan_payload")
    payload_data: dict[str, Any] = {}
    if isinstance(plan_payload, str) and plan_payload.strip():
        try:
            parsed = json.loads(plan_payload)
            if isinstance(parsed, dict):
                payload_data = parsed
        except Exception:
            payload_data = {}
    source_backend_version = _as_int(
        pending_plan_action.get("source_backend_version")
        or pending_plan_action.get("planning_version")
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
        "summary": str(pending_plan_action.get("summary") or "").strip(),
        "userGoal": str(pending_plan_action.get("user_goal") or "").strip(),
        "executionPayload": {
            "toolName": "execute_plan_action",
            "planPayload": plan_payload if isinstance(plan_payload, str) else "",
        },
        "createdAt": now,
        "updatedAt": now,
        "sourceBackendVersion": source_backend_version,
    }
    intent_update = pending_plan_action.get("intent_update")
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


def _summarize_intent_values(merged: dict[str, Any], *, intent_mode: str = "preference") -> str:
    parts: list[str] = []
    major_intents = merged.get("major_intents") if isinstance(merged.get("major_intents"), dict) else {}
    school_intents = merged.get("school_intents") if isinstance(merged.get("school_intents"), dict) else {}
    city_intents = merged.get("city_intents") if isinstance(merged.get("city_intents"), dict) else {}
    career_intents = merged.get("career_intents") if isinstance(merged.get("career_intents"), dict) else {}

    def add(label: str, values: Any) -> None:
        raw_values = values if isinstance(values, list) else [values] if values else []
        texts = [str(value or "").strip() for value in raw_values if str(value or "").strip()]
        if texts:
            parts.append(f"{label}：{'、'.join(dict.fromkeys(texts))}")

    add("偏好专业", major_intents.get("level3"))
    add("偏好专业类", major_intents.get("level2"))
    add("偏好专业门类", major_intents.get("level1"))
    add(_soft_negative_label("排除专业", intent_mode=intent_mode), major_intents.get("negative_level3"))
    add(_soft_negative_label("排除专业类", intent_mode=intent_mode), major_intents.get("negative_level2"))
    add(_soft_negative_label("排除专业门类", intent_mode=intent_mode), major_intents.get("negative_level1"))
    add("偏好院校", school_intents.get("colleges"))
    add(_soft_negative_label("排除院校", intent_mode=intent_mode), school_intents.get("negative_colleges"))
    add("偏好地域", _as_text_list(city_intents.get("province")) + _as_text_list(city_intents.get("city")))
    add(
        _soft_negative_label("排除地域", intent_mode=intent_mode),
        _as_text_list(city_intents.get("negative_province")) + _as_text_list(city_intents.get("negative_city")),
    )
    add("发展方向", career_intents.get("positive"))
    add(_soft_negative_label("排除方向", intent_mode=intent_mode), career_intents.get("negative"))
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
    merged = _merge_selected_intent_payload(intent_payload)
    if not merged:
        return ""
    intent_mode = str((intent_payload or {}).get("intentMode") or "preference").strip()
    if intent_mode not in {"preference", "constraint"}:
        intent_mode = "preference"
    return _summarize_intent_values(merged, intent_mode=intent_mode)


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
            ("career_intents", "negative"),
        ],
    )


def _intent_confirmation_mechanism_line(
    intent_mode: str,
    payload: dict[str, Any] | None = None,
) -> str:
    has_positive = _intent_payload_has_positive_value(payload)
    has_negative = _intent_payload_has_negative_value(payload)
    constraint_intent_type = str((payload or {}).get("constraintIntentType") or (payload or {}).get("constraint_intent_type") or "default").strip()
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


def _format_intent_card_impact(payload: dict[str, Any] | None, *, intent_mode: str) -> str:
    analysis = payload.get("impactAnalysis") if isinstance(payload, dict) else None
    impact_lines = compact_relation_impact_lines(
        analysis if isinstance(analysis, dict) else None,
        intent_mode=intent_mode,
        limit=2,
    )
    lines = [_intent_confirmation_mechanism_line(intent_mode, payload)]
    lines.extend(line for line in impact_lines if line and line not in lines)
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
    return state


def _build_constraint_remove_units_preview_payload(
    merged: dict[str, Any],
    *,
    summary: str,
    batch: str | None = "01",
) -> dict[str, Any] | None:
    major_intents = merged.get("major_intents") if isinstance(merged.get("major_intents"), dict) else {}
    school_intents = merged.get("school_intents") if isinstance(merged.get("school_intents"), dict) else {}
    city_intents = merged.get("city_intents") if isinstance(merged.get("city_intents"), dict) else {}

    negative_level3 = _as_text_list(major_intents.get("negative_level3"))
    negative_level2 = _as_text_list(major_intents.get("negative_level2"))
    negative_level1 = _as_text_list(major_intents.get("negative_level1"))
    negative_schools = _normalize_school_intent_names(school_intents.get("negative_colleges"), batch)
    negative_provinces = normalize_region_names(city_intents.get("negative_province"), expected_level="province")
    negative_cities = normalize_region_names(city_intents.get("negative_city"), expected_level="city")

    scope_family_count = sum(
        bool(values)
        for values in (
            negative_level3 + negative_level2 + negative_level1,
            negative_schools,
            negative_provinces + negative_cities,
        )
    )
    if scope_family_count != 1:
        return None

    filters: dict[str, Any] = {}
    source_major_names: list[str] = []
    if negative_level3 or negative_level2 or negative_level1:
        source_major_names = [*negative_level3, *negative_level2, *negative_level1]
        if negative_level3:
            filters["major_level3"] = negative_level3
        if negative_level2:
            filters["major_level2"] = negative_level2
        if negative_level1:
            filters["major_level1"] = negative_level1
    if negative_schools:
        filters["school_keyword"] = negative_schools
    if negative_provinces:
        filters["province_keyword"] = negative_provinces
    if negative_cities:
        filters["city_keyword"] = negative_cities
    if not source_major_names and not filters:
        return None

    return {
        "stage": "preview",
        "action_family": "remove_units",
        "user_goal": summary,
        "context_summary": "",
        "preview_summary": "会先检查当前方案里是否有命中这条要求的志愿。",
        "requires_confirmation": True,
        "should_rerun_review": True,
        "should_refresh_workspace": True,
        "missing_inputs": [],
        "intent_relation": "conflict",
        "atomic_actions": [
            {
                "action_type": "remove_units",
                "volunteer_ids": [],
                "source_major_names": source_major_names,
                "filters": filters,
                "reason": summary,
            }
        ],
    }


def _major_values_from_positive_intents(major_intents: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("level3", "level2", "level1"):
        for value in _as_text_list(major_intents.get(key)):
            if value and value not in values:
                values.append(value)
    return values


def _ordered_item_major_names(item: dict[str, Any]) -> list[str]:
    names: list[str] = []

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in names:
            names.append(text)

    add(item.get("majorName"))
    add(item.get("majorCategory"))
    add(item.get("majorSubCategory"))
    for major in item.get("majorItems") or item.get("majors") or []:
        if not isinstance(major, dict):
            continue
        add(major.get("majorName"))
        add(major.get("majorCategory"))
        add(major.get("majorSubCategory"))
    return names


def _ordered_item_volunteer_ids(item: dict[str, Any]) -> list[str]:
    ids: list[str] = []

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in ids:
            ids.append(text)

    add(item.get("volunteerId"))
    for major in item.get("majorItems") or item.get("majors") or []:
        if isinstance(major, dict):
            add(major.get("volunteerId"))
    return ids


def _text_scope_match(value: Any, target: str) -> bool:
    text = re.sub(r"\s+", "", str(value or ""))
    normalized_target = re.sub(r"\s+", "", str(target or ""))
    return bool(text and normalized_target and (normalized_target in text or text in normalized_target))


def _ordered_item_matches_keep_scope(
    item: dict[str, Any],
    *,
    major_targets: list[str],
    school_targets: list[str],
    region_targets: list[str],
    batch: str | None = "01",
) -> bool:
    if major_targets:
        if _matching_major_scope_records(item, major_targets, batch):
            return True
    if school_targets:
        if any(_text_scope_match(item.get("schoolName"), target) for target in school_targets):
            return True
    if region_targets:
        region_fields = [
            item.get("province"),
            item.get("provinceName"),
            item.get("city"),
            item.get("cityName"),
            item.get("schoolProvince"),
            item.get("schoolCity"),
            item.get("schoolName"),
        ]
        if any(_text_scope_match(field, target) for field in region_fields for target in region_targets):
            return True
    return False


def _positive_scope_label(merged: dict[str, Any], batch: str | None = "01") -> str:
    major_intents = merged.get("major_intents") if isinstance(merged.get("major_intents"), dict) else {}
    school_intents = merged.get("school_intents") if isinstance(merged.get("school_intents"), dict) else {}
    city_intents = merged.get("city_intents") if isinstance(merged.get("city_intents"), dict) else {}
    parts: list[str] = []
    major_targets = _major_values_from_positive_intents(major_intents)
    school_targets = _normalize_school_intent_names(school_intents.get("colleges"), batch)
    region_targets = (
        normalize_region_names(city_intents.get("province"), expected_level="province")
        + normalize_region_names(city_intents.get("city"), expected_level="city")
    )
    if major_targets:
        parts.append("专业：" + "、".join(major_targets[:3]))
    if school_targets:
        parts.append("院校：" + "、".join(school_targets[:3]))
    if region_targets:
        parts.append("地域：" + "、".join(region_targets[:3]))
    return "；".join(parts) or "指定范围"


async def _build_only_keep_remove_preview_payload(
    session_id: str,
    merged: dict[str, Any],
    *,
    summary: str,
    batch: str | None = "01",
) -> dict[str, Any] | None:
    major_intents = merged.get("major_intents") if isinstance(merged.get("major_intents"), dict) else {}
    school_intents = merged.get("school_intents") if isinstance(merged.get("school_intents"), dict) else {}
    city_intents = merged.get("city_intents") if isinstance(merged.get("city_intents"), dict) else {}
    major_targets = _major_values_from_positive_intents(major_intents)
    school_targets = _normalize_school_intent_names(school_intents.get("colleges"), batch)
    region_targets = (
        normalize_region_names(city_intents.get("province"), expected_level="province")
        + normalize_region_names(city_intents.get("city"), expected_level="city")
    )
    if not any((major_targets, school_targets, region_targets)):
        return None
    try:
        workspace_resp = await get_planning_workspace_state(session_id)
    except Exception:
        logger.warning("Failed to load workspace state for only-keep preview: session_id=%s", session_id, exc_info=True)
        return None
    workspace = (workspace_resp or {}).get("data") or {}
    ordered_state = workspace.get("orderedPlanState") or {}
    ordered_items = ordered_state.get("items") or []
    if not isinstance(ordered_items, list) or not ordered_items:
        return None
    remove_ids: list[str] = []
    keep_count = 0
    for item in ordered_items:
        if not isinstance(item, dict):
            continue
        if _ordered_item_matches_keep_scope(
            item,
            major_targets=major_targets,
            school_targets=school_targets,
            region_targets=region_targets,
            batch=batch,
        ):
            keep_count += len(_ordered_item_volunteer_ids(item)) or 1
            continue
        for volunteer_id in _ordered_item_volunteer_ids(item):
            if volunteer_id not in remove_ids:
                remove_ids.append(volunteer_id)
    if not remove_ids:
        return None
    scope_label = _positive_scope_label(merged, batch)
    preview_summary = (
        f"我理解为只保留“{scope_label}”相关志愿。当前方案里已有 {keep_count} 条相关志愿；"
        f"若执行，会移出其他方向的 {len(remove_ids)} 条志愿，并在执行后重新审查。"
    )
    return {
        "stage": "preview",
        "action_family": "remove_units",
        "user_goal": summary,
        "context_summary": "",
        "preview_summary": preview_summary,
        "requires_confirmation": True,
        "should_rerun_review": True,
        "should_refresh_workspace": True,
        "missing_inputs": [],
        "intent_relation": "only_keep",
        "atomic_actions": [
            {
                "action_type": "remove_units",
                "volunteer_ids": remove_ids,
                "reason": summary,
            }
        ],
    }


async def _build_must_have_add_preview_payload(
    session_id: str,
    merged: dict[str, Any],
    *,
    summary: str,
    batch: str | None = "01",
) -> dict[str, Any] | None:
    major_intents = merged.get("major_intents") if isinstance(merged.get("major_intents"), dict) else {}
    school_intents = merged.get("school_intents") if isinstance(merged.get("school_intents"), dict) else {}
    city_intents = merged.get("city_intents") if isinstance(merged.get("city_intents"), dict) else {}
    major_targets = _major_values_from_positive_intents(major_intents)
    school_targets = _normalize_school_intent_names(school_intents.get("colleges"), batch)
    province_targets = normalize_region_names(city_intents.get("province"), expected_level="province")
    city_targets = normalize_region_names(city_intents.get("city"), expected_level="city")
    region_targets = province_targets + city_targets
    if not any((major_targets, school_targets, region_targets)):
        return None
    try:
        workspace_resp = await get_planning_workspace_state(session_id)
    except Exception:
        logger.warning("Failed to load workspace state for must-have preview: session_id=%s", session_id, exc_info=True)
        return None
    workspace = (workspace_resp or {}).get("data") or {}
    ordered_state = workspace.get("orderedPlanState") or {}
    ordered_items = ordered_state.get("items") or []
    if isinstance(ordered_items, list):
        for item in ordered_items:
            if not isinstance(item, dict):
                continue
            if _ordered_item_matches_keep_scope(
                item,
                major_targets=major_targets,
                school_targets=school_targets,
                region_targets=region_targets,
                batch=batch,
            ):
                return None
    filters: dict[str, Any] = {
        "limit": "1",
        "school_tags": "[]",
        "major_tags": "[]",
    }
    if major_targets:
        filters["major_keyword"] = major_targets[0]
    if school_targets:
        filters["school_keyword"] = school_targets[0]
    if province_targets:
        filters["province_keyword"] = province_targets[0]
    if city_targets:
        filters["city_keyword"] = city_targets[0]
    scope_label = _positive_scope_label(merged, batch)
    return {
        "stage": "preview",
        "action_family": "add_units",
        "user_goal": summary,
        "context_summary": "",
        "preview_summary": (
            f"我理解为当前方案至少要有“{scope_label}”相关志愿。"
            "当前方案里暂时没看到这个方向；我会先找 1 个候选补入，执行前需要你确认。"
        ),
        "requires_confirmation": True,
        "should_rerun_review": True,
        "should_refresh_workspace": True,
        "missing_inputs": [],
        "intent_relation": "must_have",
        "atomic_actions": [
            {
                "action_type": "add_units",
                "volunteer_ids": [],
                "filters": filters,
                "reason": summary,
            }
        ],
    }


async def _maybe_create_plan_confirmation_from_constraint_preview(
    session_id: str,
    *,
    selected_data: dict[str, Any],
    merged: dict[str, Any],
    batch: str,
    summary: str,
    constraint_intent_type: str = "default",
) -> WSResponse | None:
    if constraint_intent_type == "must_have":
        plan_payload = await _build_must_have_add_preview_payload(
            session_id,
            merged,
            summary=summary,
            batch=batch,
        )
    elif constraint_intent_type == "only_keep":
        plan_payload = await _build_only_keep_remove_preview_payload(
            session_id,
            merged,
            summary=summary,
            batch=batch,
        )
    else:
        plan_payload = _build_constraint_remove_units_preview_payload(merged, summary=summary, batch=batch)
    if not plan_payload:
        return None
    request_context = RequestContext(
        userid="",
        sessionid=session_id,
        chat_history=[],
        batch=batch,
    )
    try:
        result_text = await execute_plan_action(
            SimpleNamespace(deps=request_context),
            json.dumps(plan_payload, ensure_ascii=False),
        )
    except Exception:
        logger.warning(
            "Failed to preview constraint plan removal: session_id=%s summary=%s",
            session_id,
            summary,
            exc_info=True,
        )
        return None
    result = _parse_tool_return_json(result_text)
    if not isinstance(result, dict):
        return None
    facts = result.get("facts") if isinstance(result.get("facts"), dict) else {}
    result_action_family = str(result.get("action_family") or plan_payload.get("action_family") or "").strip()
    if result.get("result_kind") != "preview_only":
        return None
    if result_action_family == "remove_units" and _as_int(facts.get("matched_count")) <= 0:
        return None
    result = dict(result)
    facts = dict(facts)
    facts["intent_update"] = selected_data
    result["facts"] = facts
    result["user_goal"] = plan_payload.get("user_goal") or summary
    result["preview_summary"] = result.get("summary") or summary
    pending_action = _build_pending_plan_action_from_payload(
        result,
        summary=str(result.get("summary") or summary),
    )
    if not pending_action:
        return None
    pending_action["intent_update"] = selected_data
    pending_action["summary"] = str(result.get("summary") or pending_action.get("summary") or summary)
    pending_action["user_goal"] = str(plan_payload.get("user_goal") or summary)
    return await _create_pending_plan_confirmation_response(session_id, pending_action)


async def _create_pending_intent_confirmation_response(
    session_id: str,
    *,
    selected_data: dict[str, Any],
    merged: dict[str, Any],
    intent_mode: str,
    batch: str,
) -> ChatServiceResponseEnvelope:
    replaced_pending = await _load_pending_confirmation_state(session_id)
    summary = _summarize_intent_values(merged, intent_mode=intent_mode)
    mode_text = "要求" if intent_mode == "constraint" else "偏好"
    constraint_intent_type = str(selected_data.get("constraintIntentType") or selected_data.get("constraint_intent_type") or "default").strip() or "default"
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
        ),
    }
    return ChatServiceResponseEnvelope(
        primary="",
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
    constraint_intent_type = str(getattr(preview, "constraintIntentType", "default") or "default").strip() or "default"
    existing_merged = _merge_intent_preview_item_values(list(preview.existingItems))
    existing_summary = _summarize_intent_values(existing_merged, intent_mode=intent_mode)
    batch = await _resolve_session_batch(session_id)
    selected_data = {
        "selected": selected_values,
        "intentMode": intent_mode,
        "constraintIntentType": constraint_intent_type,
        "batch": batch,
    }
    replaced_pending = await _load_pending_confirmation_state(session_id)
    summary = _summarize_intent_values(merged, intent_mode=intent_mode) or preview.title or "本次点击采纳后生效的内容。"
    if intent_mode == "constraint":
        plan_confirmation_card = await _maybe_create_plan_confirmation_from_constraint_preview(
            session_id,
            selected_data=_selected_data_with_existing_positive_context(
                selected_data,
                existing_merged,
            ),
            merged=merged,
            batch=batch,
            summary=summary,
            constraint_intent_type=constraint_intent_type,
        )
        if plan_confirmation_card is not None:
            return plan_confirmation_card
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
        "impact": _format_intent_card_impact(payload, intent_mode=intent_mode),
    }
    return WSResponse(
        type="pendingConfirmationCard",
        session_id=session_id,
        content=json.dumps(card_payload, ensure_ascii=False),
    )


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
    recovery_scope = _intent_recovery_scope_from_pending_context(request_context) if force else "generic"
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
            persist_cache=False,
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
    pending_plan_action: dict[str, Any],
) -> WSResponse:
    replaced_pending = await _load_pending_confirmation_state(session_id)
    pending_state = _build_plan_pending_state(
        session_id,
        pending_plan_action,
        replaced_pending=replaced_pending if isinstance(replaced_pending, dict) else None,
    )
    await _save_pending_confirmation_state(session_id, pending_state)

    action_family = str(pending_plan_action.get("action_family") or "").strip()
    summary = str(pending_plan_action.get("summary") or "").strip()
    unit_kind = _pending_plan_unit_kind(pending_plan_action)
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
        if "组内专业" not in compact_content:
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
        "apply_compensation": "确认补齐方案",
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


def _pending_plan_unit_kind(pending_plan_action: dict[str, Any]) -> str:
    plan_payload = pending_plan_action.get("plan_payload")
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
    "apply_compensation",
}

_EXECUTE_PLAN_ACTION_VIEW_FAMILIES = {
    "query_state",
    "query_draft",
    "query_ordered",
    "query_candidates",
}
_LOW_PRIORITY_LOG_ACTION_FAMILIES = {
    "query_state",
    "query_draft",
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


def _extract_execute_plan_action_refresh_targets(part: ToolReturnPart) -> list[str]:
    if part.tool_name != "execute_plan_action":
        return []
    data = _parse_tool_return_json(part.content)
    if not data:
        return []
    action_family = str(data.get("action_family") or "").strip()
    if action_family not in _EXECUTE_PLAN_ACTION_REFRESH_FAMILIES:
        return []
    if data.get("applied") is not True:
        return []
    if str(data.get("result_kind") or "").strip() == "error":
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
        "apply_planning_compensation",
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
        "apply_compensation": ["ordered"],
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


def _tool_calls_include_plan_view_targets(messages: list[Any] | None) -> list[str]:
    """Extract view-only workspace targets from query actions (no data refresh needed)."""
    view_targets: list[str] = []
    suppressed_families = {"query_state", "query_draft", "query_ordered"}
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
    mutation_families.update({"analyze_adjustment", "preview_compensation"})
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
    return _extract_pending_plan_action(messages) is not None


def _tool_calls_include_plan_chain(messages: list[Any] | None) -> bool:
    plan_tool_names = {
        "collect_plan_context_inputs",
        "plan_next_action",
        "execute_plan_action",
        "query_volunteer_plan",
    }
    return any(part.tool_name in plan_tool_names for part in _iter_tool_call_parts(messages))


def _tool_calls_include_intent_preview(messages: list[Any] | None) -> bool:
    return any(part.tool_name in _INTENT_PREVIEW_TOOL_NAMES for part in _iter_tool_call_parts(messages))


def _tool_calls_allow_unbacked_intent_recovery(messages: list[Any] | None) -> bool:
    tool_names = [str(part.tool_name or "").strip() for part in _iter_tool_call_parts(messages)]
    if not tool_names:
        return True
    return all("intent" in name for name in tool_names if name)


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


def _tool_returns_intent_confirm_required(messages: list[Any] | None) -> bool:
    for part in _iter_tool_return_parts(messages):
        if part.tool_name != "update_volunteer_intent_state":
            continue
        data = _parse_tool_return_json(part.content)
        if str((data or {}).get("messageCode") or "").strip() == "confirm_required":
            return True
        text = str(getattr(part, "content", "") or "")
        if "confirm_required" in text or "card_confirmation_required" in text:
            return True
    return False


def _tool_returns_interest_stage_intent_analysis(messages: list[Any] | None) -> bool:
    for part in _iter_tool_return_parts(messages):
        if part.tool_name in _INTENT_INTEREST_ANALYSIS_TOOL_NAMES:
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
    if "确认卡片" not in normalized and _reply_discusses_changeable_intent_or_plan(normalized):
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


def _reply_is_existing_only_intent_notice(reply: str) -> bool:
    return _is_existing_only_intent_notice_text(str(reply or ""))


def _is_existing_only_intent_notice_text(text: str) -> bool:
    normalized = str(text or "")
    if "本轮不会重复新增" not in normalized:
        return False
    return any(
        marker in normalized
        for marker in (
            "当前已经在后续报考参考",
            "已经作为后续报考参考",
            "已作为参考",
        )
    )


def _reply_looks_like_unbacked_intent_preview(reply: str) -> bool:
    compact = _compact_plan_reply_text(reply)
    if not compact:
        return False
    claimed_clickable_card = _reply_claims_clickable_intent_card(reply)
    has_pending_heading = "待确认内容" in compact or "整理成待确认" in compact
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
            "优先保留",
            "过滤掉",
        )
    )
    has_text_confirmation_request = any(
        marker in compact
        for marker in (
            "回复确认",
            "直接回复确认",
            "确认就",
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
    if _is_pending_plan_short_text_confirmation(content) or _is_pending_intent_short_text_confirmation(content):
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
        effective_family = _PLAN_PREVIEW_TO_APPLY_ACTION_FAMILIES.get(action_family, action_family)
        result_kind = str(data.get("result_kind") or "").strip()
        result_stage = str(data.get("stage") or "").strip()
        if effective_family in _PENDING_PLAN_ACTION_FAMILIES and (
            result_kind == "compensation_preview"
            or result_stage == "preview"
        ):
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
        if action_family not in _EXECUTE_PLAN_ACTION_VIEW_FAMILIES and action_family not in {"analyze_adjustment", "preview_compensation"}:
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


def _pending_plan_card_applied_reply(action_family: str, result: dict[str, Any]) -> str:
    default_reply = "已按你的确认执行上一轮方案调整。"
    if action_family == "apply_compensation":
        default_reply = "已按你的确认应用补齐建议，并刷新当前方案。"
    reply = str(result.get("summary") or default_reply)
    if action_family == "apply_compensation":
        reply = reply.replace("补偿", "补齐")
    return reply


def _readonly_closure_ack_reply() -> str:
    return "先按刚才的分析结论理解。这轮没有待确认的偏好或方案动作，也不会改动方案；后面想继续看具体学校、专业或方案调整，随时告诉我。"


def _no_pending_plan_confirmation_guard_reply() -> str:
    return "我这边没有上一轮待确认的方案动作。你可以直接说想生成方案、审查方案或怎么调整，我会先说明影响，确认后再执行。"


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
    "apply_compensation",
}

_PLAN_PREVIEW_TO_APPLY_ACTION_FAMILIES = {
    "preview_compensation": "apply_compensation",
}


def _preview_compensation_has_actionable_suggestions(payload: dict[str, Any], summary: str | None = None) -> bool:
    facts = payload.get("facts")
    if isinstance(facts, dict):
        try:
            action_count = int(facts.get("action_count") or 0)
        except (TypeError, ValueError):
            action_count = 0
        if action_count > 0:
            return True
    text = str(summary or payload.get("summary") or payload.get("preview_summary") or "").strip()
    if not text:
        return False
    if "0 项动作" in text or "预计补入 0 个志愿" in text:
        return False
    return "补齐建议" in text or "补偿建议" in text or "预计补入" in text


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


def _build_pending_plan_action_from_payload(payload: dict[str, Any], summary: str | None = None) -> dict[str, Any] | None:
    payload = normalize_plan_action_payload(payload)
    preview_action_family = str(payload.get("action_family") or "").strip()
    action_family = _PLAN_PREVIEW_TO_APPLY_ACTION_FAMILIES.get(preview_action_family, preview_action_family)
    if action_family not in _PENDING_PLAN_ACTION_FAMILIES:
        return None
    if payload.get("missing_inputs"):
        return None
    if preview_action_family == "preview_compensation" and not _preview_compensation_has_actionable_suggestions(payload, summary):
        return None
    if action_family == "replace_units" and not payload.get("atomic_actions"):
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


def _extract_pending_plan_action(messages: list[Any] | None) -> dict[str, Any] | None:
    """Find the latest preview-only mutating plan action that still awaits confirmation."""
    pending_calls: dict[str, dict[str, Any]] = {}
    latest_pending: dict[str, Any] | None = None
    last_non_actionable_adjustment_goal: str | None = None
    user_turns_since_pending = 0
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
            last_non_actionable_adjustment_goal = None
            if latest_pending is not None:
                user_turns_since_pending += 1
                if user_turns_since_pending > 3:
                    latest_pending = None
                    user_turns_since_pending = 0
            continue
        for part in getattr(message, "parts", []) or []:
            if not isinstance(part, ToolReturnPart):
                continue
            result = _parse_tool_return_json(part.content)
            if not result:
                continue
            if part.tool_name == "plan_next_action":
                if result.get("stage") == "preview":
                    candidate_pending = _build_pending_plan_action_from_payload(result)
                    if candidate_pending is None:
                        if str(result.get("action_family") or "").strip() == "preview_compensation":
                            latest_pending = None
                        continue
                    if (
                        last_non_actionable_adjustment_goal
                        and _text_looks_like_adjustment_request(last_non_actionable_adjustment_goal)
                        and _text_looks_like_adjustment_request(str(candidate_pending.get("user_goal") or "").strip())
                        and str(candidate_pending.get("action_family") or "").strip() in {"generate_plan", "apply_compensation"}
                    ):
                        continue
                    if current_user_turn > 0:
                        candidate_pending["created_turn"] = current_user_turn
                    latest_pending = candidate_pending
                    user_turns_since_pending = 0
                continue
            if part.tool_name != "execute_plan_action":
                continue
            action_family = str(result.get("action_family") or "").strip()
            result_kind = str(result.get("result_kind") or "").strip()
            if result_kind == "error":
                effective_error_action_family = _PLAN_PREVIEW_TO_APPLY_ACTION_FAMILIES.get(
                    action_family,
                    action_family,
                )
                if effective_error_action_family in _PENDING_PLAN_ACTION_FAMILIES:
                    latest_pending = None
                    user_turns_since_pending = 0
                    pending_calls.clear()
                continue
            if result_kind == "adjustment_analysis" and not _adjustment_analysis_has_actionable_suggestions(result):
                latest_pending = None
                call_payload = pending_calls.get(str(part.tool_call_id or "")) or {}
                pending_calls.clear()
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
                result_kind == "compensation_preview"
                or (
                    result_kind == "preview_only"
                    and result_stage == "preview"
                )
            )
            call_action_family = str(call_payload.get("action_family") or "").strip()
            effective_action_family = _PLAN_PREVIEW_TO_APPLY_ACTION_FAMILIES.get(
                action_family or call_action_family,
                action_family or call_action_family,
            )
            call_stage = str(call_payload.get("stage") or "").strip()
            if not is_preview_result and (
                result.get("applied") is True
                or call_stage == "apply"
            ):
                if effective_action_family in _PENDING_PLAN_ACTION_FAMILIES:
                    latest_pending = None
                    user_turns_since_pending = 0
                    pending_calls.clear()
                continue
            if not is_preview_result:
                continue
            if effective_action_family not in _PENDING_PLAN_ACTION_FAMILIES:
                continue
            if not call_payload:
                continue
            pending_payload = dict(call_payload)
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
            candidate_pending = _build_pending_plan_action_from_payload(
                pending_payload,
                summary=result.get("summary") or call_payload.get("preview_summary") or "",
            )
            if candidate_pending is None:
                if action_family == "preview_compensation":
                    latest_pending = None
                continue
            if (
                last_non_actionable_adjustment_goal
                and _text_looks_like_adjustment_request(last_non_actionable_adjustment_goal)
                and _text_looks_like_adjustment_request(str(candidate_pending.get("user_goal") or "").strip())
                        and str(candidate_pending.get("action_family") or "").strip() in {"generate_plan", "apply_compensation"}
            ):
                continue
            if current_user_turn > 0:
                candidate_pending["created_turn"] = current_user_turn
            latest_pending = candidate_pending
            user_turns_since_pending = 0

    return latest_pending


_PLAN_ACTION_CONFIRM_PHRASES = {
    "确认",
    "确认执行",
    "确定",
    "可以",
    "好",
    "好的",
    "行",
    "没问题",
    "执行",
    "开始执行",
    "执行吧",
    "应用吧",
    "直接应用吧",
    "就按这个来",
    "按这个来",
    "按这个执行",
    "按刚才的来",
    "就按刚才的来",
    "帮我执行",
    "就这样",
    "就这样吧",
    "就这样执行",
    "用这个",
    "就用这个",
}

_INTENT_CONFIRM_PHRASES = {
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
    "确认这个意向",
    "确认意向",
    "确认这个参考",
    "确认参考",
}


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
    if not normalized:
        return ""
    for prefix in ("嗯嗯", "嗯"):
        if not normalized.startswith(prefix) or len(normalized) <= len(prefix):
            continue
        candidate = normalized[len(prefix):]
        if (
            candidate in _PLAN_ACTION_CONFIRM_PHRASES
            or candidate in _INTENT_CONFIRM_PHRASES
            or candidate in {
                "确认这个偏好",
                "确认偏好",
                "确认这个要求",
                "确认要求",
                "确认这个意向",
                "确认意向",
                "确认这个参考",
                "确认参考",
            }
            or (candidate.startswith(("确认", "执行")) and len(candidate) <= 8)
        ):
            return candidate
    return normalized


def _is_plan_action_confirmation(content: str) -> bool:
    normalized = _normalize_confirmation_only_text(content)
    if not normalized:
        return False
    if normalized in _PLAN_ACTION_CONFIRM_PHRASES:
        return True
    return normalized.startswith(("确认", "执行")) and len(normalized) <= 8


def _is_pending_intent_confirmation(content: str) -> bool:
    normalized = _normalize_confirmation_only_text(content)
    if not normalized:
        return False
    return normalized in _INTENT_CONFIRM_PHRASES


def _is_readonly_closure_ack(content: str) -> bool:
    normalized = _normalize_confirmation_only_text(content, strip_fullwidth_question=True)
    if not normalized:
        return False
    return normalized in _READONLY_CLOSURE_ACK_PHRASES


def _is_explicit_pending_intent_confirmation(content: str) -> bool:
    normalized = _normalize_confirmation_only_text(content)
    if not normalized:
        return False
    return normalized in {
        "确认这个偏好",
        "确认偏好",
        "确认这个要求",
        "确认要求",
        "确认这个意向",
        "确认意向",
        "确认这个参考",
        "确认参考",
    }


def _is_pending_plan_short_text_confirmation(content: str) -> bool:
    normalized = _normalize_confirmation_only_text(content)
    if not normalized or _is_explicit_pending_intent_confirmation(content):
        return False
    return normalized in _PLAN_ACTION_CONFIRM_PHRASES


def _is_pending_intent_short_text_confirmation(content: str) -> bool:
    return _is_pending_intent_confirmation(content)


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


async def _early_confirmation_guard_reply(
    history_store: ChatHistoryStore,
    session_id: str,
    user_id: str,
    content: str,
    history: list[Any] | None,
) -> str | None:
    """Handle short confirmation-only turns before expensive context loading."""
    is_plan_confirm = _is_plan_action_confirmation(content)
    is_intent_confirm = _is_pending_intent_confirmation(content)
    is_explicit_intent_confirm = _is_explicit_pending_intent_confirmation(content)
    if not (is_plan_confirm or is_intent_confirm or is_explicit_intent_confirm):
        return None
    if _is_readonly_closure_ack(content) and _latest_turn_looks_readonly(history):
        return None
    started_at = time.monotonic()
    pending_state = await _load_pending_confirmation_state(session_id)
    pending_kind = str((pending_state or {}).get("kind") or "").strip()
    pending_status = str((pending_state or {}).get("status") or "").strip()
    if pending_status == "active" and pending_kind in {"plan_mutation", "intent_change"}:
        if pending_kind == "plan_mutation" and _is_pending_plan_short_text_confirmation(content):
            return None
        if pending_kind == "intent_change" and _is_pending_intent_short_text_confirmation(content):
            return None
        if pending_kind == "plan_mutation" and is_explicit_intent_confirm:
            reply = _pending_confirmation_type_mismatch_reply("plan_mutation", "intent_change")
            await _save_direct_guard_history(
                history_store,
                session_id,
                history,
                content,
                reply,
                model_name="pending-confirmation-kind-mismatch",
            )
            _log_conversation_turn_event(
                sessionId=session_id,
                userId=user_id,
                scene="plan",
                routingPath="pending_confirmation_kind_mismatch",
                pendingType="plan",
                actionFamily=str(pending_state.get("actionFamily") or "") or None,
                totalDurationMs=int((time.monotonic() - started_at) * 1000),
                status="blocked",
                errorType="pending_kind_mismatch",
            )
            return reply

    if _extract_pending_plan_action(history) is not None and is_plan_confirm:
        reply = _pending_requires_card_click_reply("plan_mutation")
        await _save_direct_guard_history(
            history_store,
            session_id,
            history,
            content,
            reply,
            model_name="pending-plan-card-required",
        )
        _log_conversation_turn_event(
            sessionId=session_id,
            userId=user_id,
            scene="plan",
            routingPath="pending_plan_card_required",
            pendingType="plan",
            actionFamily=None,
            totalDurationMs=int((time.monotonic() - started_at) * 1000),
            status="blocked",
            errorType="card_confirmation_required",
        )
        return reply

    if is_explicit_intent_confirm:
        reply = _no_pending_intent_confirmation_guard_reply()
        await _save_direct_guard_history(
            history_store,
            session_id,
            history,
            content,
            reply,
            model_name="direct-intent-confirmation-guard",
        )
        _log_conversation_turn_event(
            sessionId=session_id,
            userId=user_id,
            scene="intent",
            routingPath="intent_confirmation_guard_no_pending",
            pendingType=None,
            actionFamily=None,
            totalDurationMs=int((time.monotonic() - started_at) * 1000),
            status="success",
            errorType=None,
        )
        return reply

    if is_plan_confirm and _normalize_confirmation_only_text(content) in _PLAN_ACTION_CONFIRM_PHRASES:
        pending_intent_confirmation = await _load_pending_intent_confirmation(session_id)
        if pending_intent_confirmation and is_intent_confirm:
            reply = _pending_requires_card_click_reply("intent_change")
            await _save_direct_guard_history(
                history_store,
                session_id,
                history,
                content,
                reply,
                model_name="pending-intent-card-required",
            )
            _log_conversation_turn_event(
                sessionId=session_id,
                userId=user_id,
                scene="intent",
                routingPath="pending_intent_card_required",
                pendingType="intent",
                actionFamily=None,
                totalDurationMs=int((time.monotonic() - started_at) * 1000),
                status="blocked",
                errorType="card_confirmation_required",
            )
            return reply
        reply = _no_pending_plan_confirmation_guard_reply()
        await _save_direct_guard_history(
            history_store,
            session_id,
            history,
            content,
            reply,
            model_name="direct-plan-confirmation-guard",
        )
        _log_conversation_turn_event(
            sessionId=session_id,
            userId=user_id,
            scene="plan",
            routingPath="plan_confirmation_guard_no_pending",
            pendingType=None,
            actionFamily=None,
            totalDurationMs=int((time.monotonic() - started_at) * 1000),
            status="success",
            errorType=None,
        )
        return reply

    return None


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


def _build_basic_plan_status_reply(planning: PlanningSummary) -> str:
    total = planning.ordered_total or planning.draft_total
    target = (
        planning.ordered_target_total
        or planning.draft_target_total
        or max(planning.ordered_total, planning.draft_total, total)
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
        count_text = f'当前已加入方案 {planning.draft_total} 个志愿（目标 {target} 个），还没有生成正式顺序'

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

    if planning.pending_action_count > 0 and planning.pending_action_summaries:
        action_desc = '、'.join(planning.pending_action_summaries[:2])
        lines.append(f'还有待处理的建议：{action_desc}。')

    lines.append('\n你可以说“帮我审查一下”看详细情况，或者告诉我想怎么调整。')
    return ''.join(lines)


_READONLY_INTERRUPTION_TOOL_NAMES = {
    "query_volunteer_plan",
    "analyze_current_interest",
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
    if planning is None or (planning.ordered_total <= 0 and planning.draft_total <= 0):
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
    if planning is not None and (planning.ordered_total > 0 or planning.draft_total > 0):
        status_reply = _build_basic_plan_status_reply(planning).strip()
        if status_reply:
            return f"{prefix}\n\n{status_reply}"

    return (
        "这轮模型服务中断了，我先不改动你的方案或偏好。"
        "你可以再发一次刚才的问题，我会继续按当前会话信息处理；"
        "如果涉及方案调整，我仍会先给预览，等你确认后再执行。"
    )


async def _load_pending_intent_confirmation(session_id: str) -> PendingConfirmation | None:
    try:
        pending_result = await get_pending_confirmation(session_id)
        pending_data = (pending_result or {}).get("data", {}).get("pendingConfirmation") or {}
        if (
            isinstance(pending_data, dict)
            and pending_data.get("status") == "active"
            and pending_data.get("kind") == "intent_change"
        ):
            execution_payload = pending_data.get("executionPayload") or {}
            if isinstance(execution_payload, dict):
                merged = execution_payload.get("merged")
                selected_data = execution_payload.get("selectedData")
                intent_payload = merged if isinstance(merged, dict) and merged else selected_data
                if isinstance(intent_payload, dict) and intent_payload:
                    return PendingConfirmation(
                        kind="intent_change",
                        action_family=str(pending_data.get("actionFamily") or "apply_selected_intents"),
                        preview_summary=str(pending_data.get("summary") or ""),
                        execution_payload=execution_payload,
                    )
    except Exception:
        logger.warning("Failed to load pendingConfirmation for phase bootstrap: session_id=%s", session_id, exc_info=True)

    try:
        cache_result = await get_intent_change_cache(session_id)
    except Exception:
        logger.warning("Failed to load intent change cache for phase bootstrap: session_id=%s", session_id, exc_info=True)
        return None
    raw_data = (cache_result or {}).get("data")
    cache_data = raw_data.get("planEditCache") if isinstance(raw_data, dict) else None
    if not cache_data:
        return None
    return PendingConfirmation.from_legacy_intent_change(cache_data)


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
        ("草稿方案", "方案"),
        ("方案草稿", "方案"),
        ("草稿", "方案"),
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
    normalized = normalized.replace("报考参考信息信息", "报考参考信息")
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
        return reply
    pending_action = _extract_pending_plan_action(new_messages)
    if _tool_returns_successful_plan_apply(new_messages):
        return reply
    asks_confirmation = _reply_has_plan_confirmation_request(reply)
    if not pending_action:
        if asks_confirmation:
            if not _tool_returns_plan_mutation_context(new_messages):
                return reply
            reply = _remove_unbacked_plan_confirmation_copy(reply)
            return (
                reply.rstrip()
                + "\n\n先说明一下：我还没有拿到可执行的调整预览，所以这一步不会因为你回复“确认”就直接改方案。"
                "需要我继续定位要改的志愿和可替换范围后，再给你一版可确认的预览。"
            )
        return reply
    action_family = str(pending_action.get("action_family") or "")
    if action_family not in _PENDING_PLAN_ACTION_FAMILIES:
        return reply
    unit_kind = _pending_action_unit_kind(pending_action)
    if action_family in {"move_ordered_unit", "remove_ordered_unit"} and unit_kind != "志愿":
        compact_reply = _compact_plan_reply_text(reply)
        if "不是按单条志愿位置" not in compact_reply and "按专业组顺序计算" not in compact_reply:
            reply = (
                reply.rstrip()
                + "\n\n位置说明：这里的“第几个”按专业组顺序计算，不是按单条志愿位置计算；组内专业会保持连续。"
            )
    if _reply_conflicts_with_pending_plan_action(reply):
        return _build_pending_plan_preview_reply(pending_action)
    if asks_confirmation:
        return reply
    return reply.rstrip() + "\n\n如果你确认要这样做，我再执行；现在还不会改动方案。"


def _pending_action_unit_kind(pending_action: dict[str, Any] | None) -> str:
    if not isinstance(pending_action, dict):
        return ""
    payload = pending_action.get("plan_payload")
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


def _compact_plan_reply_text(reply: str) -> str:
    return re.sub(r'[\s"“”‘’`\'「」『』【】\[\]（）()<>《》:：,，。.!！？?、]+', "", str(reply or ""))


def _reply_has_plan_confirmation_request(reply: str) -> bool:
    compact = _compact_plan_reply_text(reply)
    if not compact or "确认" not in compact:
        return False
    if any(marker in compact for marker in ("无法进入可执行", "没有上一轮待确认", "还没有拿到可执行", "技术问题")):
        return False
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


def _reply_conflicts_with_pending_plan_action(reply: str) -> bool:
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


def _build_pending_plan_preview_reply(pending_action: dict[str, Any]) -> str:
    action_family = str(pending_action.get("action_family") or "")
    summary = str(pending_action.get("summary") or "").strip()
    summary = summary.replace("补偿", "补齐")
    if action_family == "apply_compensation":
        title = "补齐建议预览已生成。"
        boundary = "如果你确认要应用这条补齐建议，我再执行；现在还不会改动方案。"
    else:
        title = "调整预览已生成。"
        boundary = "如果你确认要这样做，我再执行；现在还不会改动方案。"
    body = f"\n\n{summary}" if summary else ""
    return f"{title}{body}\n\n{boundary}"


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
        effective_family = _PLAN_PREVIEW_TO_APPLY_ACTION_FAMILIES.get(action_family, action_family)
        result_kind = str(data.get("result_kind") or "").strip()
        if effective_family not in _PENDING_PLAN_ACTION_FAMILIES:
            continue
        if result_kind not in {"preview_only", "compensation_preview"} and data.get("stage") != "preview":
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
            if "如果确认" in compact_part and any(keyword in compact_part for keyword in ("我会", "将会", "直接", "执行", "替换", "修改", "改动")):
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


def _build_plan_timeout_fallback_reply(result: dict[str, Any]) -> str | None:
    result_kind = str(result.get("result_kind") or "").strip()
    if result_kind not in {
        "review_result",
        "adjustment_analysis",
        "status_overview",
        "generation_result",
        "ordered_snapshot",
        "draft_snapshot",
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
        "status_overview": "方案情况如下：",
        "generation_result": "方案已经生成好了：",
        "ordered_snapshot": "你的方案情况如下：",
        "draft_snapshot": "已加入方案情况如下：",
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
    if rendered_status_overview:
        lines = _build_status_overview_fallback_lines(facts)
    else:
        lines = [lead_map.get(result_kind, "这轮方案分析已经执行完了，我先把核心结果直接给你："), "", summary]
    if coverage and not rendered_status_overview:
        lines.append(f"- {coverage}")
    if aligned_examples and not rendered_status_overview:
        lines.append(f"- {aligned_examples}")
    if conflict_examples and not rendered_status_overview:
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
    reply = _build_plan_timeout_fallback_reply(result)
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
        pending_action = _build_pending_plan_action_from_payload(
            source_payload,
            summary=str(result.get("summary") or result.get("preview_summary") or ""),
        )
        if pending_action is not None:
            return ChatServiceResponseEnvelope(
                primary="",
                followups=[
                    await _create_pending_plan_confirmation_response(session_id, pending_action)
                ],
            )

    reply = _build_plan_timeout_fallback_reply(result)
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

    # ── 消息处理 ──────────────────────────────────────────────────

    async def handle_message(
        self, session_id: str, user_id: str, content: str,
        batch: str | None = None,
        score_detail: dict | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> str | WSResponse | ChatServiceResponseEnvelope:
        """处理一条用户消息，返回 Agent 回复（str 或 WSResponse）。"""
        try:
            history = await self.history_store.load(session_id)
        except Exception:
            logger.exception("Failed to load chat history: session_id=%s", session_id)
            history = None

        logger.info(
            "ChatService handling message: session_id=%s user_id=%s content_len=%d history_len=%d",
            session_id, user_id, len(content),
            len(history) if history else 0,
        )
        clear_recent_plan_execution_result(session_id, content)

        early_guard_reply = await _early_confirmation_guard_reply(
            self.history_store,
            session_id,
            user_id,
            content,
            history,
        )
        if early_guard_reply is not None:
            return early_guard_reply

        past_turn_count = _count_user_turns(history)
        current_turn = past_turn_count + 1
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
        if on_progress is not None and not _is_plan_action_confirmation(content):
            context_progress_task = asyncio.create_task(delayed_context_progress())

        # 打印原始 history 内容，便于调试格式
        # if history:
        #     for i, msg in enumerate(history):
        #         logger.info("history[%d] type=%s", i, type(msg).__name__)
        #         #logger.info("history[%d] type=%s content=%s", i, type(msg).__name__, msg)

        pending_plan_action = _extract_pending_plan_action(history)
        runtime_history = build_runtime_history(
            history,
            latest_user_content=content,
            pending_plan_action=pending_plan_action,
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
        if not score_detail:
            try:
                score_response = await get_user_score_detail(session_id)
                if score_response.get("code") == 0:
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
            except Exception as e:
                logger.warning("Failed to fetch user score detail: %s", e)

        # 获取用户初始画像（flowconfig 预填的意向数据）
        parsed_init_profile = None
        try:
            init_response = await get_user_init_profile(session_id)
            if init_response.get("code") == 0:
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
        except Exception as e:
            logger.warning("Failed to fetch user init profile: %s", e)

        # 获取 planningState 轻量摘要
        parsed_planning_summary = None
        try:
            planning_response = await get_planning_workspace_state(session_id)
            if planning_response.get("code") == 0:
                planning_data = planning_response.get("data", {})
                parsed_planning_summary = PlanningSummary.from_backend_state(planning_data)
                if parsed_planning_summary:
                    logger.info(
                        "Fetched planning summary: phase=%s version=%s draft_total=%s ordered_total=%s review_risk=%s pending_actions=%s",
                        parsed_planning_summary.phase,
                        parsed_planning_summary.version,
                        parsed_planning_summary.draft_total,
                        parsed_planning_summary.ordered_total,
                        parsed_planning_summary.review_risk_count,
                        parsed_planning_summary.pending_action_count,
                    )
        except Exception as e:
            logger.warning("Failed to fetch planning state: %s", e)

        pending_intent_confirmation = await _load_pending_intent_confirmation(session_id)
        pending_intent_change = bool(pending_intent_confirmation)

        # 构建统一的 ConversationPhase
        conversation_phase = ConversationPhase.from_legacy_context(
            pending_plan_action=pending_plan_action,
            pending_intent_confirmation=pending_intent_confirmation,
            pending_intent_change=pending_intent_change,
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
            if stale_event.should_clear_pending and not _is_plan_action_confirmation(content):
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

        if context_progress_task is not None:
            if not context_progress_task.done():
                context_progress_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await context_progress_task

        # 创建 RequestContext
        request_context = RequestContext(
            userid=user_id,
            sessionid=session_id,
            chat_history=chat_history,
            batch=batch,
            score_detail=parsed_score_detail,
            init_profile=parsed_init_profile,
            planning_summary=parsed_planning_summary,
            pending_plan_action=pending_plan_action,
            pending_intent_change=pending_intent_change,
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

        backend_pending_state = await _load_pending_confirmation_state(session_id)
        backend_pending_id = str((backend_pending_state or {}).get("pendingId") or "").strip()
        backend_pending_kind = str((backend_pending_state or {}).get("kind") or "").strip()
        backend_pending_status = str((backend_pending_state or {}).get("status") or "").strip()
        if backend_pending_id and backend_pending_status == "active":
            if backend_pending_kind == "plan_mutation" and _is_pending_plan_short_text_confirmation(content):
                return await self.handle_pending_confirmation(
                    session_id,
                    user_id,
                    json.dumps(
                        {
                            "action": "confirm",
                            "kind": "plan_mutation",
                            "pendingId": backend_pending_id,
                        },
                        ensure_ascii=False,
                    ),
                    confirmation_entry="short_text",
                    user_prompt_content=content,
                )
            if backend_pending_kind == "intent_change" and _is_pending_intent_short_text_confirmation(content):
                return await self.handle_pending_confirmation(
                    session_id,
                    user_id,
                    json.dumps(
                        {
                            "action": "confirm",
                            "kind": "intent_change",
                            "pendingId": backend_pending_id,
                        },
                        ensure_ascii=False,
                    ),
                    confirmation_entry="short_text",
                    user_prompt_content=content,
                )
            if _is_pending_readonly_impact_question(content):
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
                return reply

        if active_pending is None and _is_explicit_pending_intent_confirmation(content):
            reply = _no_pending_intent_confirmation_guard_reply()
            new_messages = [
                ModelRequest(parts=[UserPromptPart(content=content)]),
                ModelResponse(parts=[TextPart(content=reply)], model_name="direct-intent-confirmation-guard"),
            ]
            try:
                history_to_save = list(history or [])
                history_to_save.extend(new_messages)
                await self.history_store.save(session_id, history_to_save)
            except Exception:
                logger.exception("Failed to save no-pending intent confirmation guard history: session_id=%s", session_id)
            _log_conversation_turn_event(
                sessionId=session_id,
                userId=user_id,
                scene="intent",
                routingPath="intent_confirmation_guard_no_pending",
                pendingType=None,
                actionFamily=None,
                totalDurationMs=int((time.monotonic() - turn_started_at) * 1000),
                status="success",
                errorType=None,
            )
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
            return reply

        if active_pending is None and _is_plan_action_confirmation(content):
            reply = "我这边没有上一轮待确认的方案动作。你可以直接说想生成方案、审查方案或怎么调整，我会先说明影响，确认后再执行。"
            new_messages = [
                ModelRequest(parts=[UserPromptPart(content=content)]),
                ModelResponse(parts=[TextPart(content=reply)], model_name="direct-plan-confirmation-guard"),
            ]
            try:
                history_to_save = list(history or [])
                history_to_save.extend(new_messages)
                await self.history_store.save(session_id, history_to_save)
            except Exception:
                logger.exception("Failed to save no-pending plan confirmation guard history: session_id=%s", session_id)
            _log_conversation_turn_event(
                sessionId=session_id,
                userId=user_id,
                scene="plan",
                routingPath="plan_confirmation_guard_no_pending",
                pendingType=None,
                actionFamily=None,
                totalDurationMs=int((time.monotonic() - turn_started_at) * 1000),
                status="success",
                errorType=None,
            )
            return reply

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
                return recent_plan_fallback
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
                return fallback_reply
            raise
        finally:
            for progress_task in (initial_progress_task, long_progress_task):
                if progress_task is not None:
                    progress_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await progress_task
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
            or (
                isinstance(intent_side_effect_decision, dict)
                and str(intent_side_effect_decision.get("decision") or "").strip() in {"analysis_only", "mixed_answer_then_ask"}
                and float(intent_side_effect_decision.get("confidence") or 0.0) >= 0.7
                and intent_side_effect_decision.get("honored") is not False
            )
        )
        if intent_preview_downgraded and getattr(request_context, "conversation_phase", None) is not None:
            request_context.conversation_phase.clear_pending()
            request_context.pending_intent_change = False
            active_pending_kind = ""
        readonly_prompt = _prompt_explicitly_readonly(content)
        readonly_mutation_preview_guarded = False
        if readonly_prompt and _tool_returns_mutating_plan_preview(tool_context_messages):
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
            and not _is_plan_action_confirmation(content)
            and _is_pending_intent_followup_turn(content, reply)
        )
        if isinstance(reply, str) and (_reply_is_existing_only_intent_notice(reply) or intent_non_pending):
            has_pending_intent_context = False
        allow_unbacked_intent_recovery = _tool_calls_allow_unbacked_intent_recovery(
            tool_context_messages
        )
        legacy_intent_confirm_required = _tool_returns_intent_confirm_required(
            tool_context_messages
        )
        unbacked_intent_preview_detected = (
            isinstance(reply, str)
            and not intent_preview_used
            and (not has_pending_intent_context or _reply_claims_clickable_intent_card(reply))
            and allow_unbacked_intent_recovery
            and _reply_looks_like_unbacked_intent_preview(reply)
        ) or (
            isinstance(reply, str)
            and not intent_preview_used
            and allow_unbacked_intent_recovery
            and legacy_intent_confirm_required
            and not latest_turn_readonly
        )
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

        workspace_refresh_targets = _tool_calls_include_plan_workspace_refresh(tool_context_messages)
        workspace_refresh_targets = _strip_workspace_targets_for_readonly_prompt(workspace_refresh_targets, content)
        # Intent preview only prepares a pending preference/constraint. Do not
        # refresh the workspace until the user confirms or explicitly selects
        # the intent card; otherwise the UI looks as if an unconfirmed intent
        # has already changed candidate results.

        workspace_view_targets = _tool_calls_include_plan_view_targets(
            tool_context_messages
        )
        workspace_view_targets = _strip_workspace_targets_for_readonly_prompt(workspace_view_targets, content)
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
        if unbacked_intent_preview_detected and isinstance(reply, str):
            recovered_pending_intent_card = await _recover_unbacked_intent_confirmation(
                session_id,
                request_context,
                reply=unbacked_intent_preview_source_reply,
                force=legacy_intent_confirm_required,
            )
            if recovered_pending_intent_card is not None:
                _replace_text_reply(new_messages, reply, "")
                _replace_text_reply(all_messages, reply, "")
                reply = ""
        pending_plan_card: WSResponse | None = None
        pending_confirmation_action = _extract_pending_plan_action(tool_context_messages)
        plan_card_includes_intent_update = False
        if pending_confirmation_action is None and isinstance(reply, str):
            guarded_reply = _guard_unbacked_plan_confirmation_reply(reply)
            if guarded_reply != reply:
                readonly_plan_result = _latest_readonly_plan_execution_result(tool_context_messages)
                if readonly_plan_result is not None:
                    guarded_reply = _build_plan_timeout_fallback_reply(readonly_plan_result) or guarded_reply
                else:
                    readonly_query_reply = _latest_readonly_plan_query_reply(tool_context_messages)
                    if readonly_query_reply:
                        stripped_reply = _remove_unbacked_plan_confirmation_copy(reply).strip()
                        if (
                            stripped_reply
                            and not _reply_has_plan_confirmation_request(stripped_reply)
                            and _reply_contains_readonly_plan_query_facts(stripped_reply)
                        ):
                            guarded_reply = stripped_reply
                        else:
                            guarded_reply = readonly_query_reply
                _replace_text_reply(new_messages, reply, guarded_reply)
                _replace_text_reply(all_messages, reply, guarded_reply)
                reply = guarded_reply
        if pending_confirmation_action:
            plan_card_includes_intent_update = bool(
                isinstance(pending_confirmation_action.get("intent_update"), dict)
                and pending_confirmation_action.get("intent_update", {}).get("selected")
            )
            pending_plan_card = await _create_pending_plan_confirmation_response(
                session_id,
                pending_confirmation_action,
            )
            if isinstance(reply, str):
                _replace_text_reply(new_messages, reply, "")
                _replace_text_reply(all_messages, reply, "")
                reply = ""
        pending_intent_card: WSResponse | None = None
        if intent_preview_used and not intent_preview_downgraded and not plan_card_includes_intent_update:
            preview_payload = _extract_recent_intent_analysis_payload(tool_context_messages)
            if not preview_payload:
                preview_payload = _extract_recent_intent_analysis_payload(all_messages)
            pending_intent_card = await _create_pending_intent_confirmation_from_preview_payload(
                session_id,
                preview_payload,
            )
            if pending_intent_card is not None and isinstance(reply, str):
                _replace_text_reply(new_messages, reply, "")
                _replace_text_reply(all_messages, reply, "")
                reply = ""
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
                "fallbackReason": "no_direct_route",
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
            "postProcessingApplied": [],
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
        if pending_plan_card is not None:
            followups.append(pending_plan_card)
        if pending_intent_card is not None:
            followups.append(pending_intent_card)
        elif recovered_pending_intent_card is not None:
            followups.append(recovered_pending_intent_card)
        if isinstance(reply, str):
            reply = _sanitize_reply_for_user(reply)
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
                    return ChatServiceResponseEnvelope(
                        primary="",
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
        plan_payload = execution_payload.get("planPayload")
        if not isinstance(plan_payload, str) or not plan_payload.strip():
            return "这次方案调整缺少可执行内容，请重新生成预览。"
        intent_payload = execution_payload.get("intentPayload")
        pending_plan_action = {
            "action_family": action_family,
            "summary": pending_state.get("summary") or "",
            "user_goal": pending_state.get("userGoal") or "",
            "plan_payload": plan_payload,
        }
        history = confirmation_history if confirmation_history is not None else await self.history_store.load(session_id) or []

        parsed_score_detail = None
        parsed_init_profile = None
        parsed_planning_summary = None
        batch = None
        try:
            score_response = await get_user_score_detail(session_id)
            if score_response.get("code") == 0:
                raw_data = score_response.get("data", {}).get("userScoreDetail", {})
                if raw_data:
                    parsed_score_detail = _parse_score_detail_from_backend(raw_data)
                    batch = _normalize_batch(raw_data.get("batch") or batch)
        except Exception:
            logger.warning("Failed to fetch score detail for pending confirmation: session_id=%s", session_id, exc_info=True)
        try:
            profile_response = await get_user_init_profile(session_id)
            if profile_response.get("code") == 0:
                raw_profile = profile_response.get("data", {})
                if raw_profile:
                    parsed_init_profile = UserProfile.from_backend_format(raw_profile)
        except Exception:
            logger.warning("Failed to fetch init profile for pending confirmation: session_id=%s", session_id, exc_info=True)
        try:
            workspace_response = await get_planning_workspace_state(session_id)
            if workspace_response.get("code") == 0:
                parsed_planning_summary = PlanningSummary.from_backend_state(workspace_response.get("data", {}))
        except Exception:
            logger.warning("Failed to fetch planning workspace for pending confirmation: session_id=%s", session_id, exc_info=True)

        conversation_phase = ConversationPhase.from_legacy_context(
            pending_plan_action=pending_plan_action,
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
            pending_plan_action=pending_plan_action,
            pending_intent_change=False,
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
        reply = _pending_plan_card_applied_reply(action_family, result)
        if intent_apply_note and result.get("result_kind") != "error":
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

        tool_success = bool(result) and result.get("result_kind") != "error"
        _log_conversation_turn_event(
            sessionId=session_id,
            userId=user_id,
            scene="plan",
            routingPath="pending_plan_short_text_confirm" if confirmation_entry == "short_text" else "pending_plan_card_confirm",
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
