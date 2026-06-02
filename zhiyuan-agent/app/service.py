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
from app.llm.client import LLMClient
from app.schemas.user_profile import UserProfile
from app.schemas.ws import WSResponse
from app.sync.state_sync import PlanningStateSync
from app.tools.explore_followup_tool import handle_interest_analysis_action_result
from app.tools.plan_execution_tool import (
    clear_recent_plan_execution_result,
    consume_recent_plan_execution_result,
    execute_plan_action,
)
from app.tools.plan_orchestration_models import normalize_plan_action_payload
from app.tools.intent_state_tool import (
    apply_selected_intents as _apply_selected_intents,
    merge_selected_values,
    update_volunteer_intent_state,
)
from app.tools.intent_response_tool import (
    parse_explore_followup_result,
    parse_intent_state_update_result,
    render_explore_followup_result,
    render_intent_state_update,
)
from app.util.internal_client import (
    get_message_by_id,
    get_pending_confirmation,
    get_intent_change_cache,
    get_planning_workspace_state,
    get_user_init_profile,
    get_user_score_detail,
    save_pending_confirmation,
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
)
_READONLY_MUTATION_GUARD_REPLY = (
    "我按“先看、先查、不直接改”的方式处理了这轮请求，当前不会加入、删除、移动或重排方案。"
    "如果你想把某个候选真正加入方案，可以再明确说“加入方案”或指定要调整的位置，我会先给出可确认的调整预览。"
)
_UNBACKED_CONFIRM_SENTENCE_RE = re.compile(r"确认要我.*执行")
_ROUTE_OBSERVABILITY_MODEL_NAME = "route-observability"
_INTENT_PREVIEW_TOOL_NAMES = {
    "analyze_volunteer_intent_change",
    "preview_current_intent_confirmation",
    "preview_current_major_intent_confirmation",
    "preview_current_school_intent_confirmation",
    "preview_current_region_intent_confirmation",
    "preview_current_career_intent_confirmation",
}


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _log_conversation_turn_event(**fields: Any) -> None:
    log_event("conversation_turn_event", **fields)


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
        "content": "已为你刷新候选库，可以查看跟刚才偏好或排除要求相关的候选机会。",
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
    if replaced_pending and replaced_pending.get("pendingId"):
        state["replacesPendingId"] = replaced_pending.get("pendingId")
    return state


def _summarize_intent_values(merged: dict[str, Any]) -> str:
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

    add("偏好专业", major_intents.get("level3") or major_intents.get("level2") or major_intents.get("level1"))
    add("排除专业", major_intents.get("negative_level3") or major_intents.get("negative_level2") or major_intents.get("negative_level1"))
    add("偏好院校", school_intents.get("colleges"))
    add("排除院校", school_intents.get("negative_colleges"))
    add("偏好地域", (city_intents.get("province") or []) + (city_intents.get("city") or []))
    add("排除地域", (city_intents.get("negative_province") or []) + (city_intents.get("negative_city") or []))
    add("发展方向", career_intents.get("positive"))
    add("排除方向", career_intents.get("negative"))
    return "；".join(parts)


def _build_intent_pending_state(
    session_id: str,
    *,
    selected_data: dict[str, Any],
    merged: dict[str, Any],
    intent_mode: str,
    batch: str,
    summary: str,
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
            "batch": batch,
        },
        "createdAt": now,
        "updatedAt": now,
    }
    if replaced_pending and replaced_pending.get("pendingId"):
        state["replacesPendingId"] = replaced_pending.get("pendingId")
    return state


async def _create_pending_intent_confirmation_response(
    session_id: str,
    *,
    selected_data: dict[str, Any],
    merged: dict[str, Any],
    intent_mode: str,
    batch: str,
) -> ChatServiceResponseEnvelope:
    replaced_pending = await _load_pending_confirmation_state(session_id)
    summary = _summarize_intent_values(merged)
    mode_text = "要求" if intent_mode == "constraint" else "偏好"
    if not summary:
        summary = f"本次选择的{mode_text}内容。"
    pending_state = _build_intent_pending_state(
        session_id,
        selected_data=selected_data,
        merged=merged,
        intent_mode=intent_mode,
        batch=batch,
        summary=summary,
        replaced_pending=replaced_pending if isinstance(replaced_pending, dict) else None,
    )
    await _save_pending_confirmation_state(session_id, pending_state)
    payload = {
        "type": "pendingConfirmationCard",
        "pendingId": pending_state["pendingId"],
        "kind": "intent_change",
        "actionFamily": "apply_selected_intents",
        "title": f"确认采纳这次{mode_text}",
        "summary": summary,
        "content": summary,
        "impactTitle": "确认说明",
        "impact": "点击采纳前不会写入后续报考参考；采纳后会按这次内容继续看候选和方案。",
        "clickable": True,
        "status": "active",
        "confirmText": "采纳",
        "cancelText": "暂不采纳",
    }
    primary = f"我已把这次{mode_text}整理好了。请点击确认卡片采纳；点击前不会生效。"
    return ChatServiceResponseEnvelope(
        primary=primary,
        followups=[
            WSResponse(
                type="pendingConfirmationCard",
                session_id=session_id,
                content=json.dumps(payload, ensure_ascii=False),
            )
        ],
    )


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
    title_by_action = {
        "add_units": "确认加入方案",
        "remove_units": "确认移出志愿",
        "move_unit": "确认移动志愿",
        "move_ordered_unit": "确认移动专业组",
        "remove_ordered_unit": "确认移出专业组",
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
        "content": summary or "确认后会执行本次方案调整。",
        "impactTitle": "确认说明",
        "impact": "点击确认前不会改动当前方案；如果继续对话但不点击卡片，本次调整不会执行。",
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


def _tool_returns_intent_existing_only(messages: list[Any] | None) -> bool:
    for part in _iter_tool_return_parts(messages):
        if part.tool_name not in _INTENT_PREVIEW_TOOL_NAMES:
            continue
        data = _parse_tool_return_json(part.content)
        if str((data or {}).get("status") or "").strip() == "existing_only":
            return True
        text = str(getattr(part, "content", "") or "")
        if "当前已经在后续报考参考" in text and "本轮不会重复新增" in text:
            return True
    return False


def _tool_returns_interest_stage_intent_analysis(messages: list[Any] | None) -> bool:
    for part in _iter_tool_return_parts(messages):
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
        ("我已经按你的偏好记录下来", "我先把这个偏好整理出来，等你点击卡片采纳后再作为后续参考"),
        ("我已经记录下来", "我先把这个偏好整理出来，等你点击卡片采纳后再作为后续参考"),
    )
    for source, target in replacements:
        normalized = normalized.replace(source, target)
    if normalized != reply and "确认" not in normalized:
        normalized = normalized.rstrip("。") + "。如果要按这个方向作为后续参考，请点击卡片采纳。"
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


def _reply_is_existing_only_intent_notice(reply: str) -> bool:
    return "当前已经在后续报考参考" in str(reply or "") and "本轮不会重复新增" in str(reply or "")


def _reply_looks_like_unbacked_intent_preview(reply: str) -> bool:
    compact = _compact_plan_reply_text(reply)
    if not compact:
        return False
    if "待确认内容" not in compact:
        return False
    return any(marker in compact for marker in ("回复确认", "直接回复确认", "确认后", "确认就", "确认这个", "按上面执行"))


def _normalize_unbacked_intent_preview_reply(reply: str) -> str:
    """Avoid fake pending intent previews when the model did not call preview tools."""
    if not _reply_looks_like_unbacked_intent_preview(reply):
        return reply
    normalized = re.sub(r"\*\*待确认内容\*\*", "**这轮先按咨询结论理解**", reply)
    normalized = re.sub(r"(?m)^我先把.*整理成待确认(?:偏好|要求|内容)[：:]?\s*$", "我先把这轮结论说明清楚：", normalized)
    replacements = (
        ("回复\"确认\"就按上面执行；", "如果你想把这个作为后续要求，再明确告诉我“把这个要求记下来”；"),
        ("回复“确认”就按上面执行；", "如果你想把这个作为后续要求，再明确告诉我“把这个要求记下来”；"),
        ("直接回复“确认”", "明确告诉我“把这个要求记下来”"),
        ("直接回复\"确认\"", "明确告诉我“把这个要求记下来”"),
        ("确认后，", "如果后续正式记成要求，"),
    )
    for source, target in replacements:
        normalized = normalized.replace(source, target)
    if "没有正式进入待确认状态" not in normalized:
        normalized = (
            normalized.rstrip()
            + "\n\n补充说明：这轮没有正式进入待确认状态，也不会写入后续参考或改动方案；"
            "如果要正式采用，请明确说“把这个要求记下来”。"
        )
    return normalized


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
        + "\n\n补充说明：这条**待确认内容**目前仍是**尚未确认**状态，确认前不会写入后续参考；"
        "如果要正式采用，请点击上方卡片采纳。"
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


def _no_pending_intent_confirmation_guard_reply() -> str:
    return "我这边没有找到上一轮仍在等待确认的偏好调整。你可以直接说想保留、排除或重点关注的方向，我会先整理成待确认内容。"


def _pending_requires_card_click_reply(kind: str | None = None) -> str:
    if kind == "plan_mutation":
        return "这次方案调整还在待确认状态。请点击上方卡片里的确认按钮后，我再执行；只在对话里回复确认不会直接改动方案。"
    if kind == "intent_change":
        return "这次偏好或要求还在待确认状态。请点击上方卡片里的采纳按钮后，我再更新后续报考参考；只在对话里回复确认不会直接生效。"
    return "这次更新还在待确认状态。请点击上方卡片里的确认按钮后，我再执行；只在对话里回复确认不会直接生效。"


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


def _is_plan_action_confirmation(content: str) -> bool:
    normalized = re.sub(r"\s+", "", (content or "").strip())
    normalized = normalized.strip("。.!！?")
    if not normalized:
        return False
    if normalized in _PLAN_ACTION_CONFIRM_PHRASES:
        return True
    return normalized.startswith(("确认", "执行")) and len(normalized) <= 8


def _is_pending_intent_confirmation(content: str) -> bool:
    normalized = re.sub(r"\s+", "", (content or "").strip())
    normalized = normalized.strip("。.!！?")
    if not normalized:
        return False
    return normalized in _INTENT_CONFIRM_PHRASES


def _is_readonly_closure_ack(content: str) -> bool:
    normalized = re.sub(r"\s+", "", (content or "").strip())
    normalized = normalized.strip("。.!！?？")
    if not normalized:
        return False
    return normalized in _READONLY_CLOSURE_ACK_PHRASES


def _is_explicit_pending_intent_confirmation(content: str) -> bool:
    normalized = re.sub(r"\s+", "", (content or "").strip())
    normalized = normalized.strip("。.!！?")
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


def _sanitize_reply_for_user(reply: str) -> str:
    """清理回复中不应暴露给用户的内部标记。"""
    import re
    # 移除 [LLM_INTERNAL] 开头的整行
    reply = re.sub(r'\n?\[LLM_INTERNAL\][^\n]*', '', reply)
    # 移除行内的 [LLM_INTERNAL] 标记
    reply = re.sub(r'\[LLM_INTERNAL\]\s*', '', reply)
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


def _build_agent_interruption_fallback_reply(
    content: str,
    planning: PlanningSummary | None,
    agent_observability: dict[str, Any] | None = None,
) -> str | None:
    """Return a safe user-facing reply when the model run is interrupted.

    This is intentionally conservative: it only uses already loaded planning
    summary facts and never claims that a tool action was completed.
    """
    if not isinstance(agent_observability, dict) or not agent_observability.get("failedNode"):
        return None

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
    )
    normalized = reply
    for source, target in replacements:
        normalized = normalized.replace(source, target)
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
    if action_family in {"move_ordered_unit", "remove_ordered_unit"}:
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
        if "确认" in compact and compact.strip("*#：:？?") in {"确认替换吗", "确认执行吗", "确认修改吗", "确认改动吗"}:
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
            if "确认" in compact_part and any(keyword in compact_part for keyword in ("即可执行", "就执行", "立即执行", "执行替换", "执行修改", "执行改动")):
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
    return "\n".join(normalized_lines) if normalized_lines else reply


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
                _build_workspace_action_response(session_id, target)
                for target in workspace_refresh_targets
            ],
        )
    return ChatServiceResponseEnvelope(primary=reply)


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
                        province_name = raw_data.get("province", {}).get("name", "")
                        total_score = raw_data.get("totalScore", 0)
                        subject_list = [
                            item.get("name", "")
                            for item in raw_data.get("subjectList", [])
                        ]
                        sex_name = raw_data.get("sex", {}).get("name", "")
                        volunteer_model = raw_data.get("volunteerModel", "major")
                        parsed_score_detail = ScoreDetail(
                            province=province_name,
                            total_score=total_score,
                            subject_list=subject_list,
                            sex=sex_name,
                            volunteer_model=volunteer_model,
                        )
                        logger.info(
                            "Fetched score_detail: province=%s total_score=%d subjects=%s sex=%s",
                            province_name, total_score, subject_list, sex_name,
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
        )
        active_pending = resolve_pending_confirmation(request_context)
        active_pending_kind = str(getattr(active_pending, "kind", "") or "").strip()
        active_plan_payload_text = resolve_pending_plan_payload_text(request_context)
        turn_started_at = time.monotonic()

        if active_pending_kind == "plan_mutation" and _is_plan_action_confirmation(content):
            action_family = str(getattr(active_pending, "action_family", "") or "").strip()
            reply = _pending_requires_card_click_reply("plan_mutation")
            new_messages = [
                ModelRequest(parts=[UserPromptPart(content=content)]),
                ModelResponse(parts=[TextPart(content=reply)], model_name="pending-plan-card-required"),
            ]
            try:
                history_to_save = list(history or [])
                history_to_save.extend(new_messages)
                await self.history_store.save(session_id, history_to_save)
            except Exception:
                logger.exception("Failed to save pending plan card-required guard history: session_id=%s", session_id)
            _log_conversation_turn_event(
                sessionId=session_id,
                userId=user_id,
                scene="plan",
                routingPath="pending_plan_card_required",
                pendingType="plan",
                actionFamily=action_family or None,
                totalDurationMs=int((time.monotonic() - turn_started_at) * 1000),
                status="blocked",
                errorType="card_confirmation_required",
            )
            return reply

        if active_pending_kind == "intent_change" and _is_pending_intent_confirmation(content):
            reply = _pending_requires_card_click_reply("intent_change")
            new_messages = [
                ModelRequest(parts=[UserPromptPart(content=content)]),
                ModelResponse(parts=[TextPart(content=reply)], model_name="pending-intent-card-required"),
            ]
            try:
                history_to_save = list(history or [])
                history_to_save.extend(new_messages)
                await self.history_store.save(session_id, history_to_save)
            except Exception:
                logger.exception("Failed to save pending intent card-required guard history: session_id=%s", session_id)
            _log_conversation_turn_event(
                sessionId=session_id,
                userId=user_id,
                scene="intent",
                routingPath="pending_intent_card_required",
                pendingType="intent",
                actionFamily=None,
                totalDurationMs=int((time.monotonic() - turn_started_at) * 1000),
                status="blocked",
                errorType="card_confirmation_required",
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
            fallback_reply = _build_agent_interruption_fallback_reply(
                content,
                parsed_planning_summary,
                request_context.agent_observability,
            )
            if fallback_reply and not isinstance(exc, asyncio.CancelledError):
                fallback_messages = [
                    ModelRequest(parts=[UserPromptPart(content=content)]),
                    ModelResponse(parts=[TextPart(content=fallback_reply)], model_name="agent-interruption-fallback"),
                ]
                with contextlib.suppress(Exception, asyncio.CancelledError):
                    await self.history_store.save(session_id, list(history or []) + fallback_messages)
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

        plan_chain_used = _tool_calls_include_plan_chain(new_messages)
        if not new_messages:
            plan_chain_used = _tool_calls_include_plan_chain(all_messages)

        intent_preview_used_current_turn = _tool_calls_include_intent_preview(new_messages)
        intent_preview_used = intent_preview_used_current_turn
        if not new_messages:
            intent_preview_used = _tool_calls_include_intent_preview(all_messages)
        intent_existing_only = _tool_returns_intent_existing_only(new_messages)
        if not new_messages:
            intent_existing_only = _tool_returns_intent_existing_only(all_messages)
        intent_side_effect_decision = request_context.agent_observability.get("intentSideEffectDecision")
        intent_interest_stage_result = _tool_returns_interest_stage_intent_analysis(new_messages)
        if not new_messages:
            intent_interest_stage_result = _tool_returns_interest_stage_intent_analysis(all_messages)
        intent_preview_downgraded = (
            intent_interest_stage_result
            or (
                isinstance(intent_side_effect_decision, dict)
                and str(intent_side_effect_decision.get("decision") or "").strip() in {"analysis_only", "mixed_answer_then_ask"}
                and float(intent_side_effect_decision.get("confidence") or 0.0) >= 0.7
            )
        )
        if intent_preview_downgraded and getattr(request_context, "conversation_phase", None) is not None:
            request_context.conversation_phase.clear_pending()
            request_context.pending_intent_change = False
            active_pending_kind = ""
        readonly_prompt = _prompt_explicitly_readonly(content)
        readonly_mutation_preview_guarded = False
        if readonly_prompt and _tool_returns_mutating_plan_preview(new_messages):
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
            bounded_reply = _append_plan_preview_confirmation_boundary(reply, new_messages)
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

        if isinstance(reply, str):
            user_facing_reply = _normalize_user_facing_terms(reply)
            if user_facing_reply != reply:
                _replace_text_reply(new_messages, reply, user_facing_reply)
                _replace_text_reply(all_messages, reply, user_facing_reply)
                reply = user_facing_reply

        latest_turn_readonly = _latest_turn_looks_readonly(new_messages if new_messages else all_messages)
        has_pending_intent_context = (intent_preview_used and not intent_preview_downgraded) or (
            active_pending_kind == "intent_change"
            and not latest_turn_readonly
            and not plan_chain_used
            and not _is_plan_action_confirmation(content)
            and _is_pending_intent_followup_turn(content, reply)
        )
        if isinstance(reply, str) and _reply_is_existing_only_intent_notice(reply):
            has_pending_intent_context = False
        if isinstance(reply, str) and not intent_preview_used and not has_pending_intent_context:
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

        if isinstance(reply, str) and has_pending_intent_context and not intent_existing_only:
            bounded_intent_reply = _append_pending_intent_boundary(
                reply,
                has_pending_intent=has_pending_intent_context,
            )
            if bounded_intent_reply != reply:
                _replace_text_reply(new_messages, reply, bounded_intent_reply)
                _replace_text_reply(all_messages, reply, bounded_intent_reply)
                reply = bounded_intent_reply

        workspace_refresh_targets = _tool_calls_include_plan_workspace_refresh(new_messages)
        if not new_messages:
            workspace_refresh_targets = _tool_calls_include_plan_workspace_refresh(all_messages)
        workspace_refresh_targets = _strip_workspace_targets_for_readonly_prompt(workspace_refresh_targets, content)
        # Intent preview only prepares a pending preference/constraint. Do not
        # refresh the workspace until the user confirms or explicitly selects
        # the intent card; otherwise the UI looks as if an unconfirmed intent
        # has already changed candidate results.

        workspace_view_targets = _tool_calls_include_plan_view_targets(
            new_messages if new_messages else all_messages
        )
        workspace_view_targets = _strip_workspace_targets_for_readonly_prompt(workspace_view_targets, content)
        tool_messages = new_messages if new_messages else all_messages
        tool_calls = _iter_tool_call_parts(tool_messages)
        tool_returns = _iter_tool_return_parts(tool_messages)
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
                _build_workspace_action_response(session_id, target)
                for target in workspace_refresh_targets
            )
        if workspace_view_targets:
            already = set(workspace_refresh_targets)
            for target in workspace_view_targets:
                if target not in already:
                    followups.append(
                        _build_workspace_action_response(session_id, target, refresh=False)
                    )
        pending_confirmation_action = _extract_pending_plan_action(new_messages)
        if pending_confirmation_action:
            followups.append(
                await _create_pending_plan_confirmation_response(session_id, pending_confirmation_action)
            )
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
                        batch = raw_data.get("batch", "01")
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
        pending_state = await _load_pending_confirmation_state(session_id)
        active_pending_id = str((pending_state or {}).get("pendingId") or "").strip()
        active_status = str((pending_state or {}).get("status") or "").strip()
        if not pending_id:
            return "这张确认卡片缺少校验信息，请重新生成预览后再确认。"
        if not pending_state or active_status != "active" or active_pending_id != pending_id:
            return "这张确认卡片已经失效。请按最新卡片操作，或重新说明想怎么调整。"
        if kind and kind != str(pending_state.get("kind") or ""):
            return "这张确认卡片和当前待确认操作不一致，请按最新卡片操作。"

        if action in {"cancel", "reject"}:
            cancelled_state = dict(pending_state)
            cancelled_state["status"] = "cancelled"
            cancelled_state["updatedAt"] = datetime.now(timezone.utc).isoformat()
            await _save_pending_confirmation_state(session_id, cancelled_state)
            return "已取消本次待确认操作。你可以继续说明想怎么调整，我会重新给出预览。"
        if action not in {"confirm", "accept", "apply"}:
            return "这张确认卡片的操作类型不完整，请刷新后重试。"
        active_kind = str(pending_state.get("kind") or "").strip()
        if active_kind == "intent_change":
            execution_payload = pending_state.get("executionPayload")
            if not isinstance(execution_payload, dict):
                return "这张确认卡片缺少可执行内容，请重新生成。"
            selected_data = execution_payload.get("selectedData")
            if not isinstance(selected_data, dict):
                return "这张确认卡片缺少可执行内容，请重新生成。"
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
            if state_result and state_result.intentMode == "constraint":
                followups: list[WSResponse] = []
                if state_result.candidateFilters:
                    followups.append(
                        _build_workspace_action_response(
                            session_id,
                            "candidate",
                            extra_payload={"candidateFilters": state_result.candidateFilters},
                        )
                    )
                followups.append(
                    _build_workspace_action_response(
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
            return reply
        if active_kind != "plan_mutation":
            return "这类确认卡片暂时还不能在这里处理，请刷新后重试。"

        execution_payload = pending_state.get("executionPayload")
        if not isinstance(execution_payload, dict):
            return "这张方案调整卡片缺少可执行内容，请重新生成预览。"
        action_family = str(pending_state.get("actionFamily") or "").strip()
        plan_payload = execution_payload.get("planPayload")
        if not isinstance(plan_payload, str) or not plan_payload.strip():
            return "这张方案调整卡片缺少可执行内容，请重新生成预览。"
        pending_plan_action = {
            "action_family": action_family,
            "summary": pending_state.get("summary") or "",
            "user_goal": pending_state.get("userGoal") or "",
            "plan_payload": plan_payload,
        }
        history = await self.history_store.load(session_id) or []

        parsed_score_detail = None
        parsed_init_profile = None
        parsed_planning_summary = None
        batch = None
        try:
            score_response = await get_user_score_detail(session_id)
            if score_response.get("code") == 0:
                raw_data = score_response.get("data", {}).get("userScoreDetail", {})
                if raw_data:
                    parsed_score_detail = ScoreDetail.from_api_response(raw_data)
                    batch = raw_data.get("batch") or batch
        except Exception:
            logger.warning("Failed to fetch score detail for pending confirmation: session_id=%s", session_id, exc_info=True)
        try:
            profile_response = await get_user_init_profile(session_id)
            if profile_response.get("code") == 0:
                raw_profile = profile_response.get("data", {})
                if raw_profile:
                    parsed_init_profile = UserProfile.from_api_response(raw_profile)
        except Exception:
            logger.warning("Failed to fetch init profile for pending confirmation: session_id=%s", session_id, exc_info=True)
        try:
            workspace_response = await get_planning_workspace_state(int(session_id))
            if workspace_response.get("code") == 0:
                parsed_planning_summary = PlanningSummary.from_workspace_response(workspace_response)
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
        )

        started_at = time.monotonic()
        result_text = await execute_plan_action(SimpleNamespace(deps=request_context), plan_payload)
        result = _parse_tool_return_json(result_text) or {}
        reply = _pending_plan_card_applied_reply(action_family, result)
        applied_state = dict(pending_state)
        applied_state["status"] = "applied"
        applied_state["updatedAt"] = datetime.now(timezone.utc).isoformat()
        applied_state["resultKind"] = result.get("result_kind")
        await _save_pending_confirmation_state(session_id, applied_state)

        new_messages = [
            ModelRequest(parts=[UserPromptPart(content="[确认卡片]")]),
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="execute_plan_action",
                        args={"plan_payload": plan_payload},
                        tool_call_id=f"card-{action_family or 'plan'}-confirmation",
                    )
                ],
                model_name="pending-confirmation-card",
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="execute_plan_action",
                        content=result_text,
                        tool_call_id=f"card-{action_family or 'plan'}-confirmation",
                    )
                ]
            ),
            ModelResponse(parts=[TextPart(content=reply)], model_name="pending-confirmation-card"),
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
            routingPath="pending_plan_card_confirm",
            pendingType="plan",
            actionFamily=action_family or result.get("action_family"),
            totalDurationMs=int((time.monotonic() - started_at) * 1000),
            status="success" if tool_success else "error",
            errorType=result.get("result_kind") if result.get("result_kind") == "error" else None,
        )
        workspace_refresh_targets = _dedupe_workspace_targets(
            [str(target) for target in (result.get("workspace_refresh_targets") or [])]
        )
        if workspace_refresh_targets:
            return ChatServiceResponseEnvelope(
                primary=reply,
                followups=[
                    _build_workspace_action_response(session_id, target)
                    for target in workspace_refresh_targets
                ],
            )
        return reply
