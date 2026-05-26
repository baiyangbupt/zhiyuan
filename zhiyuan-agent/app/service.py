from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
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
from app.domain.career_slots import to_career_label
from app.llm.client import LLMClient
from app.resolver.action_resolver_shadow import action_resolver_shadow_from_plan_fast_decision
from app.resolver.career_direction_fast_router import resolve_career_direction_fast_route
from app.resolver.major_compare_fast_router import resolve_major_compare_fast_route
from app.resolver.major_compare_reply_renderer import (
    is_missing_weight_major_compare_result,
    render_missing_weight_major_compare_reply,
)
from app.resolver.major_intent_fast_router import resolve_major_intent_fast_route
from app.resolver.plan_fast_router import resolve_plan_fast_route
from app.resolver.plan_query_fast_router import resolve_plan_query_fast_route
from app.schemas.tool_inputs import MajorIntentPreviewInput
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
from app.tools.plan_orchestration_tool import _plan_next_action_model
from app.tools.intent_state_tool import (
    apply_selected_intents as _apply_selected_intents,
    update_volunteer_intent_state,
)
from app.tools.intent_preview_tool import analyze_current_career_direction
from app.tools.intent_preview_tool import preview_current_major_intent_confirmation
from app.tools.intent_relation_tool import (
    build_impact_preview_from_analysis as _build_impact_preview_from_analysis,
    build_plan_relation_analysis as _build_plan_relation_analysis,
    enrich_plan_relation_analysis_from_state as _enrich_plan_relation_analysis_from_state,
)
from app.tools.major_compare_tool import compare_majors
from app.tools.plan_query_tool import query_volunteer_plan
from app.tools.intent_response_tool import (
    parse_explore_followup_result,
    parse_intent_state_update_result,
    render_explore_followup_result,
    render_intent_state_update,
)
from app.util.internal_client import (
    get_intent_change_cache,
    get_planning_workspace_state,
    get_user_init_profile,
    get_user_score_detail,
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
_PLAN_MUTATION_PROMPT_KEYWORDS = (
    "删除",
    "删掉",
    "去掉",
    "移到",
    "移动",
    "往前挪",
    "往后挪",
    "排序",
    "重排",
    "加入",
    "加进来",
    "加进去",
    "换成",
    "替换",
    "补齐",
    "补几个",
)
_UNBACKED_CONFIRM_SENTENCE_RE = re.compile(r"确认要我.*执行")


def _safe_result_field(result_text: str, field: str) -> Any:
    try:
        parsed = json.loads(result_text)
        if isinstance(parsed, dict):
            return parsed.get(field)
    except Exception:
        return None
    return None


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _log_conversation_turn_event(**fields: Any) -> None:
    log_event("conversation_turn_event", **fields)


async def _safe_emit_progress(on_progress: ProgressCallback | None, hint: str) -> None:
    if not on_progress or not hint:
        return
    try:
        await on_progress(hint)
    except Exception:
        logger.debug("on_progress callback failed: hint=%s", hint, exc_info=True)


def _plan_fast_route_execute_progress_hint(action_family: str | None, stage: str | None) -> str:
    family = str(action_family or "").strip()
    normalized_stage = str(stage or "").strip()
    if family == "query_state":
        return "正在整理当前方案的数量、梯度和风险..."
    mutation_families = {
        "sort_ordered_plan",
        "move_unit",
        "move_ordered_unit",
        "remove_units",
        "remove_ordered_unit",
        "add_units",
        "replace_units",
    }
    if family in mutation_families:
        if normalized_stage == "preview":
            return "正在生成这次调整的影响预览..."
        return "正在按你的确认更新方案..."
    if family in {"run_review", "review_plan"}:
        return "正在检查当前方案的风险点..."
    if family in {"generate_plan", "regenerate_order", "apply_compensation"}:
        if normalized_stage == "preview":
            return "正在整理这次方案调整的确认信息..."
        return "正在生成并整理方案结果..."
    return "正在整理方案结果..."


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


def _compact_runtime_message(message: Any, max_tool_return_chars: int) -> tuple[Any, int]:
    if not isinstance(message, ModelRequest) or max_tool_return_chars <= 0:
        return message, 0

    changed = False
    dropped = 0
    compacted_parts: list[Any] = []
    for part in getattr(message, "parts", []) or []:
        if isinstance(part, ToolReturnPart) and isinstance(part.content, str) and len(part.content) > max_tool_return_chars:
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
    history = list(full_history or [])
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
        "content": "已为你刷新候选库，可以查看跟刚才偏好或排除要求相关的候选机会。",
        "actionText": "打开候选库",
    },
    "ordered": {
        "title": "查看调整后的排序方案",
        "content": "已刷新排序方案，可以查看本次调整后的志愿列表和位置变化。",
        "actionText": "打开排序方案",
    },
    "review": {
        "title": "查看方案审查结果",
        "content": "已刷新方案审查，可以查看梯度、保底和风险项是否达标。",
        "actionText": "打开审查结果",
    },
}


def _build_workspace_action_response(session_id: str, target: str, *, refresh: bool = True) -> WSResponse:
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
            },
            ensure_ascii=False,
        ),
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

    The persisted chat history already contains full tool args/results. This
    summary keeps only route/action/result fields needed by effect/perf
    benchmark analysis and deliberately avoids user payload expansion.
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
        "pin_planning_ordered_item",
        "unpin_planning_ordered_item",
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


def _tool_calls_include_plan_chain(messages: list[Any] | None) -> bool:
    plan_tool_names = {
        "collect_plan_context_inputs",
        "plan_next_action",
        "execute_plan_action",
        "query_volunteer_plan",
    }
    return any(part.tool_name in plan_tool_names for part in _iter_tool_call_parts(messages))


def _tool_calls_include_intent_preview(messages: list[Any] | None) -> bool:
    intent_preview_tool_names = {
        "analyze_volunteer_intent_change",
        "preview_current_intent_confirmation",
        "preview_current_major_intent_confirmation",
        "preview_current_school_intent_confirmation",
        "preview_current_region_intent_confirmation",
        "preview_current_career_intent_confirmation",
    }
    return any(part.tool_name in intent_preview_tool_names for part in _iter_tool_call_parts(messages))


def _normalize_pending_intent_reply(reply: str) -> str:
    if not isinstance(reply, str):
        return reply
    normalized = reply
    replacements = (
        ("这个想法我这边已经记下并在参考了。", "这个想法我先整理成待确认内容。"),
        ("当前已记录偏好", "待确认偏好"),
        ("当前已记录排除", "待确认排除"),
        ("当前已记录", "待确认"),
        ("已记录偏好", "待确认偏好"),
        ("已记录排除", "待确认排除"),
        ("已记录", "待确认"),
        ("已经记下并在参考", "先整理成待确认内容"),
        ("已经记下", "先整理成待确认内容"),
        ("好的，我记下了你对", "我先把你对"),
        ("好的，我已经记下了你对", "我先把你对"),
        ("我记下了你对", "我先把你对"),
        ("我已经记下了你对", "我先把你对"),
        ("好的，我记下了", "我先整理一下"),
        ("好的，我已经记下了", "我先整理一下"),
        ("我已经按你的偏好记录下来", "我先把这个偏好整理出来，等你确认后再作为后续参考"),
        ("我已经记录下来", "我先把这个偏好整理出来，等你确认后再作为后续参考"),
        ("确认前不会正式生效", "确认前不会写入后续参考"),
        ("确认后才会正式记入后续参考", "确认后会写入后续参考"),
        ("你确认后我再正式生效", "你确认后我再写入后续参考"),
        ("我再正式生效", "我再写入后续参考"),
    )
    for source, target in replacements:
        normalized = normalized.replace(source, target)
    normalized = re.sub(r"[（(]\s*level[123]\s*[）)]", "", normalized)
    if normalized != reply and "确认" not in normalized:
        normalized = normalized.rstrip("。") + "。如果确认要按这个方向作为后续参考，你再回复确认。"
    if "确认前不会写入后续参考" not in normalized and "待确认" in normalized and "确认" in normalized:
        normalized = normalized.rstrip()
        if normalized:
            normalized = normalized.rstrip("。") + "。"
        normalized += "确认前不会写入后续参考，也不会直接改动当前方案。"
    if (
        "下一步" not in normalized
        and "待确认" in normalized
        and ("后续参考" in normalized or "确认后" in normalized)
    ):
        normalized = normalized.rstrip()
        if normalized:
            normalized += "\n\n"
        normalized += "**下一步**\n- 如果确认要作为后续参考，直接回复“确认这个偏好”或“确认这个要求”。"
    return normalized


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


def _text_clears_pending_plan_action(text: str | None) -> bool:
    compact = re.sub(r"\s+", "", str(text or "").strip())
    if not compact:
        return False
    return any(
        token in compact
        for token in (
            "先不要改方案",
            "不要改方案",
            "别改方案",
            "不改方案",
            "先不改",
            "先不要调整",
            "不要调整",
            "不调整",
            "先不执行",
            "不要执行",
            "不执行",
            "只分析",
            "先只分析",
            "只看分析",
            "只看看",
            "只看一下",
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


def _extract_pending_intent_confirmation_from_history(messages: list[Any] | None) -> PendingConfirmation | None:
    """Recover pending intent preview payload from Agent history.

    The normal source of truth is backend ``planEditCache``. This history-based
    recovery only covers local/offline degradation where the preview response was
    saved but the backend cache could not be written or read.
    """
    latest_pending: PendingConfirmation | None = None
    user_turns_since_pending = 0
    current_user_turn = 0
    preview_tools = {
        "preview_current_intent_confirmation",
        "preview_current_major_intent_confirmation",
        "preview_current_school_intent_confirmation",
        "preview_current_region_intent_confirmation",
        "preview_current_career_intent_confirmation",
    }

    for message in messages or []:
        if isinstance(message, ModelRequest):
            for part in getattr(message, "parts", []) or []:
                if not isinstance(part, ToolReturnPart) or part.tool_name != "update_volunteer_intent_state":
                    continue
                result = _parse_tool_return_json(part.content)
                if not result:
                    continue
                if result.get("applied") is True or result.get("messageCode") == "reject_success":
                    latest_pending = None
                    user_turns_since_pending = 0

        if isinstance(message, ModelRequest):
            user_prompt_parts = [
                part for part in getattr(message, "parts", []) or []
                if isinstance(part, UserPromptPart)
            ]
            if user_prompt_parts:
                current_user_turn += 1
                user_text = "\n".join(str(part.content or "") for part in user_prompt_parts)
                if latest_pending is not None and _text_clears_pending_plan_action(user_text):
                    latest_pending = None
                    user_turns_since_pending = 0
                elif latest_pending is not None:
                    user_turns_since_pending += 1
                    if user_turns_since_pending > 3:
                        latest_pending = None
                        user_turns_since_pending = 0
                continue

        if not isinstance(message, ModelResponse):
            continue
        for part in getattr(message, "parts", []) or []:
            if not isinstance(part, ToolCallPart) or part.tool_name not in preview_tools:
                continue
            args = _parse_tool_call_args(part.args)
            cache_data = {
                key: args.get(key) or {}
                for key in ("major_intents", "school_intents", "city_intents", "career_intents")
                if isinstance(args.get(key), dict) and args.get(key)
            }
            if not cache_data:
                continue
            cache_data["intent_mode"] = str(args.get("intent_mode") or "preference").strip() or "preference"
            pending = PendingConfirmation.from_legacy_intent_change(cache_data)
            if pending is None:
                continue
            if current_user_turn > 0:
                pending = pending.model_copy(update={"created_turn": current_user_turn})
            latest_pending = pending
            user_turns_since_pending = 0

    return latest_pending


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
            user_text = "\n".join(str(part.content or "") for part in user_prompt_parts)
            pending_calls.clear()
            last_non_actionable_adjustment_goal = None
            if latest_pending is not None and _text_clears_pending_plan_action(user_text):
                latest_pending = None
                user_turns_since_pending = 0
            elif latest_pending is not None:
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
            is_preview_result = result_kind in {"preview_only", "compensation_preview"}
            call_id = str(part.tool_call_id or "")
            call_payload = pending_calls.get(call_id) or {}
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
            if not is_preview_result and call_stage == "preview":
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
    "嗯可以",
    "可以的",
    "好",
    "好的",
    "嗯好",
    "嗯好的",
    "好呀",
    "行",
    "嗯行",
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
    "嗯可以",
    "可以的",
    "好",
    "好的",
    "嗯好",
    "嗯好的",
    "好呀",
    "行",
    "嗯行",
    "没问题",
    "就按这个来",
    "按这个来",
    "就这样",
    "就这样吧",
    "确认这个偏好",
    "确认偏好",
    "确认这个要求",
    "确认要求",
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


_PENDING_INTENT_IMPACT_TOKENS = (
    "影响",
    "匹配",
    "承接",
    "冲突",
    "符合",
    "不符合",
    "当前方案",
    "现在方案",
    "现有方案",
    "候选",
    "还剩",
    "结果",
)

_PENDING_INTENT_REFERENCE_TOKENS = (
    "这个",
    "这条",
    "这些",
    "刚才",
    "上面",
    "偏好",
    "要求",
    "想法",
)

_PENDING_INTENT_MUTATION_TOKENS = (
    "直接改",
    "帮我改",
    "调整方案",
    "改方案",
    "加入方案",
    "加进方案",
    "加入志愿",
    "删除",
    "删掉",
    "去掉",
    "移动",
    "移到",
    "排序",
    "重排",
    "生成",
    "执行",
    "审查",
)


def _is_pending_intent_impact_question(content: str) -> bool:
    normalized = re.sub(r"\s+", "", (content or "").strip())
    normalized = normalized.strip("。.!！?？")
    if not normalized or _is_pending_intent_confirmation(normalized):
        return False
    if any(token in normalized for token in _PENDING_INTENT_MUTATION_TOKENS):
        return False
    return (
        any(token in normalized for token in _PENDING_INTENT_IMPACT_TOKENS)
        and any(token in normalized for token in _PENDING_INTENT_REFERENCE_TOKENS)
    )


def _message_text(message: Any) -> str:
    texts = [
        str(getattr(part, "content", "") or "")
        for part in getattr(message, "parts", []) or []
        if isinstance(part, TextPart) and str(getattr(part, "content", "") or "").strip()
    ]
    return "\n".join(texts)


def _infer_readonly_context_from_text(text: str) -> str | None:
    compact = re.sub(r"\s+", "", str(text or ""))
    if not compact:
        return None
    if (
        "方案承接" in compact
        or ("当前方案对" in compact and "承接" in compact)
    ) and any(token in compact for token in ("职业方向", "体制内", "考公", "稳定就业", "读研", "就业导向")):
        return "career_direction"
    if (
        "专业对比" in compact
        or "这轮先按通用维度看" in compact
        or ("选择建议" in compact and "就业路径" in compact and "门槛" in compact)
    ):
        return "major_compare"
    if (
        "当前排序方案里共命中" in compact
        or "候选里共命中" in compact
        or ("下面仅展示前" in compact and any(token in compact for token in ("志愿", "机会")))
    ):
        return "plan_query"
    return None


def _last_readonly_context_kind(messages: list[Any] | None) -> str | None:
    for message in reversed(messages or []):
        if not isinstance(message, ModelResponse):
            continue
        for part in getattr(message, "parts", []) or []:
            if not isinstance(part, ToolCallPart):
                continue
            if part.tool_name == "analyze_current_career_direction":
                return "career_direction"
            if part.tool_name in {"compare_majors", "compare_majors_adhoc"}:
                return "major_compare"
            if part.tool_name == "query_volunteer_plan":
                return "plan_query"
        inferred = _infer_readonly_context_from_text(_message_text(message))
        if inferred:
            return inferred
    return None


def _build_no_pending_confirmation_guard_reply(messages: list[Any] | None) -> str:
    context_kind = _last_readonly_context_kind(messages)
    if context_kind == "career_direction":
        return (
            "上一轮只是职业方向和当前方案承接分析，没有待执行的方案动作。\n\n"
            "下一步可以这样继续：\n"
            "- 继续分析：说“展开体制内方向”或“展开读研方向”。\n"
            "- 想调整方案：说“按这个方向看看方案怎么调”，我会先说明会影响哪些志愿和风险点，再给预览，等你确认后执行。\n"
            "- 只想看方案：说“看看当前方案”或“审查当前方案”。\n"
            "- 不确定怎么继续：直接说“帮我看下一步”，我会先分析，不会直接改方案。"
        )
    if context_kind == "major_compare":
        return (
            "上一轮只是专业对比分析，没有待确认的偏好或方案动作。\n\n"
            "下一步可以这样继续：\n"
            "- 想沉淀偏好：直接说“把这个记成偏好”。\n"
            "- 想看方案影响：直接说想看哪个专业方向和当前方案的匹配情况。"
        )
    if context_kind == "plan_query":
        return (
            "上一轮只是查询当前方案或候选结果，没有待执行的方案动作。\n\n"
            "边界提醒：这次不会执行移动、删除、加入或排序，也不会改动当前方案。\n\n"
            "下一步可以这样继续：\n"
            "- 处理当前方案：说要移动、删除或按哪个维度排序。\n"
            "- 处理候选志愿：说要加入哪所学校或哪个专业，我会先给确认预览。"
        )
    return (
        "我这边没有上一轮待确认的方案动作。\n\n"
        "你可以直接说想做哪一步：\n"
        "- 生成或查看方案。\n"
        "- 审查当前方案。\n"
        "- 按专业、院校、地域或录取率调整方案。\n\n"
        "涉及改动时，我会先说明影响，确认后再执行。"
    )


def _sanitize_reply_for_user(reply: str) -> str:
    """清理回复中不应暴露给用户的内部标记。"""
    import re
    # 移除 [LLM_INTERNAL] 开头的整行
    reply = re.sub(r'\n?\[LLM_INTERNAL\][^\n]*', '', reply)
    # 移除行内的 [LLM_INTERNAL] 标记
    reply = re.sub(r'\[LLM_INTERNAL\]\s*', '', reply)
    # 移除旧方案引用里给模型/工具看的 @位置 标记，用户侧用自然序号和工作台定位。
    reply = re.sub(r'@\d+\b', '', reply)
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


def _is_plan_mutation_request(content: str) -> bool:
    normalized = re.sub(r"\s+", "", (content or "").strip())
    if not normalized:
        return False
    return any(keyword in normalized for keyword in _PLAN_MUTATION_PROMPT_KEYWORDS)


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


async def _load_pending_intent_confirmation(
    session_id: str,
    history: list[Any] | None = None,
) -> PendingConfirmation | None:
    try:
        cache_result = await get_intent_change_cache(session_id)
    except Exception:
        logger.warning("Failed to load intent change cache for phase bootstrap: session_id=%s", session_id, exc_info=True)
        cache_result = {}
    raw_data = (cache_result or {}).get("data")
    cache_data = raw_data.get("planEditCache") if isinstance(raw_data, dict) else None
    if cache_data:
        return PendingConfirmation.from_legacy_intent_change(cache_data)
    return _extract_pending_intent_confirmation_from_history(history)


def _direct_pending_intent_reply(result_text: str) -> str:
    try:
        result = parse_intent_state_update_result(result_text)
    except Exception:
        logger.warning("Failed to parse direct pending intent confirmation result", exc_info=True)
        return "已按你的确认应用上一轮意向调整。"
    return render_intent_state_update(result)


def _append_unique_text(items: list[str], text: str) -> None:
    value = str(text or "").strip()
    if value and value not in items:
        items.append(value)


def _pending_intent_item_lines(cache_data: dict[str, Any]) -> list[str]:
    if not isinstance(cache_data, dict):
        return []

    intent_mode = str(cache_data.get("intent_mode") or "preference").strip()
    strict_constraint = intent_mode == "constraint"
    lines: list[str] = []

    major_intents = cache_data.get("major_intents") if isinstance(cache_data.get("major_intents"), dict) else {}
    for key in ("level1", "level2", "level3"):
        for name in major_intents.get(key) or []:
            _append_unique_text(lines, f"确认后，将把{name}作为后续优先参考的专业方向")
    for key in ("negative_level1", "negative_level2", "negative_level3"):
        for name in major_intents.get(key) or []:
            if strict_constraint:
                _append_unique_text(lines, f"确认后，将把{name}作为明确不考虑的内容")
            else:
                _append_unique_text(lines, f"确认后，会尽量降低{name}的优先级")

    school_intents = cache_data.get("school_intents") if isinstance(cache_data.get("school_intents"), dict) else {}
    for name in school_intents.get("colleges") or []:
        _append_unique_text(lines, f"确认后，将把{name}作为后续优先参考的院校")
    for name in school_intents.get("negative_colleges") or []:
        if strict_constraint:
            _append_unique_text(lines, f"确认后，将把{name}作为明确不考虑的院校")
        else:
            _append_unique_text(lines, f"确认后，会尽量降低{name}的优先级")

    city_intents = cache_data.get("city_intents") if isinstance(cache_data.get("city_intents"), dict) else {}
    for key in ("province", "city"):
        for name in city_intents.get(key) or []:
            _append_unique_text(lines, f"确认后，将把{name}作为后续优先参考的地域")
    for key in ("negative_province", "negative_city"):
        for name in city_intents.get(key) or []:
            if strict_constraint:
                _append_unique_text(lines, f"确认后，将把{name}作为明确不考虑的地域")
            else:
                _append_unique_text(lines, f"确认后，会尽量降低{name}的优先级")

    career_intents = cache_data.get("career_intents") if isinstance(cache_data.get("career_intents"), dict) else {}
    for value in career_intents.get("positive") or []:
        _append_unique_text(lines, f"确认后，将把{to_career_label(str(value))}作为后续优先参考的发展方向")
    for value in career_intents.get("negative") or []:
        label = to_career_label(str(value))
        if strict_constraint:
            _append_unique_text(lines, f"确认后，将把{label}作为明确不考虑的发展方向")
        else:
            _append_unique_text(lines, f"确认后，会尽量降低{label}的优先级")

    return lines


def _build_pending_intent_timeout_reply(cache_data: dict[str, Any]) -> str | None:
    item_lines = _pending_intent_item_lines(cache_data)
    if not item_lines:
        return None

    intent_mode = str(cache_data.get("intent_mode") or "preference").strip()
    confirm_phrase = "确认这个要求" if intent_mode == "constraint" else "确认这个偏好"
    lines = [
        "我已经把这次提到的想法整理成待确认内容了，先把关键内容给你：",
        "",
        "**待确认内容**",
    ]
    lines.extend(f"- {line}" for line in item_lines[:8])
    if len(item_lines) > 8:
        lines.append(f"- 还有 {len(item_lines) - 8} 项相近内容")
    lines.extend([
        "",
        "**下一步**",
        f"如果确认要作为后续参考，直接回复“{confirm_phrase}”。确认前不会写入后续参考，也不会直接改动当前方案。",
    ])
    return _sanitize_reply_for_user(_normalize_user_facing_terms("\n".join(lines)))


async def _build_pending_intent_impact_reply(
    session_id: str,
    pending: PendingConfirmation,
) -> str | None:
    cache_data = pending.execution_payload if isinstance(pending.execution_payload, dict) else {}
    if not cache_data:
        return None
    item_lines = _pending_intent_item_lines(cache_data)
    if not item_lines:
        return None

    intent_mode = str(cache_data.get("intent_mode") or "preference").strip()
    major_intents = cache_data.get("major_intents") if isinstance(cache_data.get("major_intents"), dict) else None
    school_intents = cache_data.get("school_intents") if isinstance(cache_data.get("school_intents"), dict) else None
    city_intents = cache_data.get("city_intents") if isinstance(cache_data.get("city_intents"), dict) else None
    career_intents = cache_data.get("career_intents") if isinstance(cache_data.get("career_intents"), dict) else None

    analysis = _build_plan_relation_analysis(
        intent_mode,
        career_intents=career_intents,
    )
    analysis = await _enrich_plan_relation_analysis_from_state(
        session_id,
        analysis,
        intent_mode=intent_mode,
        major_intents=major_intents,
        school_intents=school_intents,
        city_intents=city_intents,
        career_intents=career_intents,
    )
    impact_text = _build_impact_preview_from_analysis(analysis)
    confirm_phrase = "确认这个要求" if intent_mode == "constraint" else "确认这个偏好"
    lines = [
        "可以，我先按这条尚未确认的想法看影响；确认前不会写入后续参考，也不会改动当前方案。",
        "",
        impact_text,
        "",
        "**待确认内容**",
    ]
    lines.extend(f"- {line}" for line in item_lines[:8])
    if len(item_lines) > 8:
        lines.append(f"- 还有 {len(item_lines) - 8} 项相近内容")
    lines.extend(
        [
            "",
            "**下一步**",
            f"如果要写入后续参考，直接回复“{confirm_phrase}”。如果只是继续了解，也可以继续问它和当前方案、候选机会的关系。",
        ]
    )
    return _sanitize_reply_for_user(_normalize_user_facing_terms("\n".join(lines)))


async def build_timeout_fallback_from_pending_intent_preview(
    session_id: str,
    user_prompt: str | None = None,
) -> ChatServiceResponseEnvelope | None:
    """Build a user-facing fallback when intent preview finished but final LLM timed out."""
    try:
        cache_result = await get_intent_change_cache(session_id)
    except Exception:
        logger.warning(
            "Failed to load pending intent cache for timeout fallback: session_id=%s prompt=%s",
            session_id,
            user_prompt,
            exc_info=True,
        )
        return None

    raw_data = (cache_result or {}).get("data")
    cache_data = raw_data.get("planEditCache") if isinstance(raw_data, dict) else None
    if not isinstance(cache_data, dict) or not cache_data:
        return None

    reply = _build_pending_intent_timeout_reply(cache_data)
    if not reply:
        return None
    return ChatServiceResponseEnvelope(primary=reply)


def _should_guard_plan_reply(content: str) -> bool:
    return any(keyword in content for keyword in _PLAN_STYLE_GUARD_PROMPT_KEYWORDS)


def _normalize_user_facing_terms(reply: str) -> str:
    """Remove internal product terms from user-facing replies."""
    if not isinstance(reply, str):
        return reply
    if "画像" not in reply and "level" not in reply:
        return reply
    replacements = (
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
    normalized = re.sub(r"[（(]\s*level[123]\s*[）)]", "", normalized)
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
    if _reply_conflicts_with_pending_plan_action(reply):
        return _build_pending_plan_preview_reply(pending_action)
    if action_family == "sort_ordered_plan":
        reply = _enrich_pending_sort_preview_summary(pending_action, reply)
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


def _pending_sort_label_and_direction(pending_action: dict[str, Any]) -> tuple[str, str]:
    raw_values: list[str] = [
        str(pending_action.get("summary") or ""),
        str(pending_action.get("user_goal") or ""),
    ]
    payload_text = str(pending_action.get("plan_payload") or "").strip()
    if payload_text:
        try:
            payload = json.loads(payload_text)
        except (TypeError, ValueError):
            payload = {}
        if isinstance(payload, dict):
            raw_values.extend([
                str(payload.get("preview_summary") or ""),
                str(payload.get("user_goal") or ""),
            ])
            for action in payload.get("atomic_actions") or []:
                if not isinstance(action, dict):
                    continue
                filters = action.get("filters") if isinstance(action.get("filters"), dict) else {}
                raw_values.extend([
                    str(filters.get("sort_field") or ""),
                    str(filters.get("sortField") or ""),
                    str(filters.get("field") or ""),
                    str(action.get("reason") or ""),
                ])
    joined = " ".join(raw_values)
    if any(token in joined for token in ("schoolRank", "school_rank", "schoolLevel", "school_level", "院校层次", "学校层次", "院校排名", "好学校")):
        return "院校层次", "排名靠前的排在前面"
    if any(token in joined for token in ("finalScore", "final_score", "recommendationScore", "recommendation_score", "推荐系数")):
        return "推荐系数", "推荐系数高的排在前面"
    return "录取率", "录取率低的排在前面"


def _enrich_pending_sort_preview_summary(pending_action: dict[str, Any], summary: str) -> str:
    label, direction = _pending_sort_label_and_direction(pending_action)
    summary = (summary or "").strip()
    action_summary = f"会按{label}重新排序当前方案。"
    if summary and "重新排序当前方案" not in summary:
        action_summary = summary
    compact_summary = _compact_plan_reply_text(summary)
    if "排序方式" in compact_summary and "执行影响" in compact_summary:
        return summary
    sections = [
        action_summary,
        f"排序方式：\n- {direction}。",
        "执行影响：\n- 会实际改变方案顺序和导出顺序。\n- 审查状态会进入待重新审查。",
    ]
    return "\n\n".join(section.strip() for section in sections if section.strip())


def _build_pending_plan_preview_reply(pending_action: dict[str, Any]) -> str:
    action_family = str(pending_action.get("action_family") or "")
    summary = str(pending_action.get("summary") or "").strip()
    summary = summary.replace("补偿", "补齐")
    if action_family == "sort_ordered_plan":
        summary = _enrich_pending_sort_preview_summary(pending_action, summary)
    if action_family == "apply_compensation":
        title = "补齐建议预览已生成。"
        boundary = "如果你确认要应用这条补齐建议，我再执行；现在还不会改动方案。"
    else:
        title = "调整预览已生成。"
        boundary = "如果你确认要这样做，我再执行；现在还不会改动方案。"
    body = f"\n\n{summary}" if summary else ""
    return f"{title}{body}\n\n{boundary}"


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


def _direct_pending_plan_action_reply(action_family: str, result: dict[str, Any]) -> str:
    default_reply = "已按你的确认执行上一轮方案调整。"
    if action_family == "apply_compensation":
        default_reply = "已按你的确认应用补齐建议，并刷新当前方案。"
    reply = str(result.get("summary") or default_reply)
    if action_family == "apply_compensation":
        reply = reply.replace("补偿", "补齐")
    return _append_confirmed_plan_action_next_step(action_family, reply)


_CONFIRMED_PLAN_ACTION_NEXT_STEPS = {
    "sort_ordered_plan": "方案顺序和导出顺序已同步更新。\n- 审查状态：待重新审查。\n- 下一步：可以到方案区查看排序结果，必要时再点“审查”。",
    "move_ordered_unit": "方案顺序和导出顺序已同步更新。\n- 审查状态：待重新审查。\n- 下一步：可以到方案区查看移动结果，必要时再点“审查”。",
    "move_unit": "方案顺序和导出顺序已同步更新。\n- 审查状态：待重新审查。\n- 下一步：可以到方案区查看移动结果，必要时再点“审查”。",
    "remove_ordered_unit": "方案数量和导出内容已同步更新。\n- 审查状态：待重新审查。\n- 下一步：可以到方案区查看删除结果，必要时再点“审查”。",
    "remove_units": "方案数量和导出内容已同步更新。\n- 审查状态：待重新审查。\n- 下一步：可以到方案区查看删除结果，必要时再点“审查”。",
    "add_units": "方案数量和导出内容已同步更新。\n- 审查状态：待重新审查。\n- 下一步：可以到方案区查看加入结果，必要时再点“审查”。",
    "replace_units": "方案内容和导出内容已同步更新。\n- 审查状态：待重新审查。\n- 下一步：可以到方案区查看替换结果，必要时再点“审查”。",
}


def _append_confirmed_plan_action_next_step(action_family: str, reply: str) -> str:
    reply = str(reply or "").strip()
    hint = _CONFIRMED_PLAN_ACTION_NEXT_STEPS.get(action_family)
    if not reply or not hint:
        return reply
    if any(keyword in reply for keyword in ("待重新审查", "重新审查", "审查状态", "复审", "复查", "导出顺序", "导出内容")):
        return reply
    return f"{reply}\n\n{hint}"


def _direct_plan_fast_route_reply(result: dict[str, Any]) -> str:
    reply = str(
        result.get("summary")
        or result.get("state_summary")
        or result.get("review_summary")
        or ""
    ).strip()
    if not reply:
        return "我已经完成这一步处理。"
    return reply.replace("补偿", "补齐")


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
    if (
        _is_plan_mutation_request(user_prompt)
        and str(result.get("action_family") or "").strip() == "query_state"
        and str(result.get("result_kind") or "").strip() == "status_overview"
    ):
        logger.info(
            "Skip query_state timeout fallback for mutating prompt: session_id=%s prompt=%s",
            session_id,
            user_prompt,
        )
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

        # 打印原始 history 内容，便于调试格式
        # if history:
        #     for i, msg in enumerate(history):
        #         logger.info("history[%d] type=%s", i, type(msg).__name__)
        #         #logger.info("history[%d] type=%s content=%s", i, type(msg).__name__, msg)

        pending_plan_action = _extract_pending_plan_action(history)
        pending_intent_confirmation: PendingConfirmation | None = None
        runtime_history = build_runtime_history(
            history,
            latest_user_content=content,
            pending_plan_action=pending_plan_action,
            config=self.history_config,
        )
        chat_history = runtime_history.chat_history
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

        if not pending_plan_action:
            pending_intent_confirmation = await _load_pending_intent_confirmation(session_id, history)
            if pending_intent_confirmation and _is_pending_intent_impact_question(content):
                turn_started_at = time.monotonic()
                await _safe_emit_progress(on_progress, "正在结合这条待确认想法查看当前方案影响...")
                tool_started_at = time.monotonic()
                reply = await _build_pending_intent_impact_reply(session_id, pending_intent_confirmation)
                tool_duration_ms = int((time.monotonic() - tool_started_at) * 1000)
                if reply:
                    new_messages = [
                        ModelRequest(parts=[UserPromptPart(content=content)]),
                        ModelResponse(parts=[TextPart(content=reply)], model_name="pending-intent-impact-fast-route"),
                    ]
                    try:
                        history_to_save = list(history or [])
                        history_to_save.extend(new_messages)
                        await self.history_store.save(session_id, history_to_save)
                    except Exception:
                        logger.exception("Failed to save early pending intent impact history: session_id=%s", session_id)
                    _log_conversation_turn_event(
                        sessionId=session_id,
                        userId=user_id,
                        scene="intent",
                        routingPath="pending_intent_impact_fast_route",
                        routeDecision={
                            "source": "direct_pending",
                            "matched": True,
                            "confidence": "high",
                            "route": "intent",
                            "reason": "pending_intent_impact_question",
                        },
                        pendingType="intent",
                        actionFamily="preview_intent_impact",
                        resultKind="intent_impact_preview",
                        llmRequests=0,
                        inputTokens=0,
                        outputTokens=0,
                        totalTokens=0,
                        totalDurationMs=int((time.monotonic() - turn_started_at) * 1000),
                        toolDurationMs=tool_duration_ms,
                        toolCalls=[
                            {
                                "name": "enrich_plan_relation_analysis_from_state",
                                "durationMs": tool_duration_ms,
                                "success": True,
                            }
                        ],
                        status="success",
                        errorType=None,
                    )
                    return reply

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

        if pending_intent_confirmation is None:
            pending_intent_confirmation = await _load_pending_intent_confirmation(session_id, history)
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
        )
        active_pending = resolve_pending_confirmation(request_context)
        active_pending_kind = str(getattr(active_pending, "kind", "") or "").strip()
        active_plan_payload_text = resolve_pending_plan_payload_text(request_context)
        turn_started_at = time.monotonic()

        if active_pending_kind == "plan_mutation" and _is_plan_action_confirmation(content):
            action_family = str(getattr(active_pending, "action_family", "") or "").strip()
            plan_payload = active_plan_payload_text
            tool_call_id = f"direct-{action_family or 'pending-plan'}-confirmation"
            await _safe_emit_progress(on_progress, "正在按你的确认更新方案，完成后会刷新工作台...")
            tool_started_at = time.monotonic()
            result_text = await execute_plan_action(SimpleNamespace(deps=request_context), plan_payload)
            tool_duration_ms = int((time.monotonic() - tool_started_at) * 1000)
            result = _parse_tool_return_json(result_text) or {}
            reply = _direct_pending_plan_action_reply(action_family, result)
            new_messages = [
                ModelRequest(parts=[UserPromptPart(content=content)]),
                ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="execute_plan_action",
                            args={"plan_payload": plan_payload},
                            tool_call_id=tool_call_id,
                        )
                    ],
                    model_name="direct-pending-plan-confirmation",
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
                ModelResponse(parts=[TextPart(content=reply)], model_name="direct-pending-plan-confirmation"),
            ]
            try:
                history_to_save = list(history or [])
                history_to_save.extend(new_messages)
                await self.history_store.save(session_id, history_to_save)
            except Exception:
                logger.exception("Failed to save direct pending plan confirmation history: session_id=%s", session_id)
            _log_conversation_turn_event(
                sessionId=session_id,
                userId=user_id,
                scene="plan",
                routingPath="direct_pending_plan_confirm",
                routeDecision={
                    "source": "direct_pending",
                    "matched": True,
                    "confidence": "high",
                    "route": "plan",
                    "reason": "plan_pending_confirmation",
                },
                pendingType="plan",
                actionFamily=action_family or result.get("action_family"),
                resultKind=result.get("result_kind"),
                llmRequests=0,
                inputTokens=0,
                outputTokens=0,
                totalTokens=0,
                totalDurationMs=int((time.monotonic() - turn_started_at) * 1000),
                toolDurationMs=tool_duration_ms,
                toolCalls=[
                    {
                        "name": "execute_plan_action",
                        "durationMs": tool_duration_ms,
                        "success": bool(result) and result.get("result_kind") != "error",
                        "actionFamily": action_family or result.get("action_family"),
                    }
                ],
                status="success" if result.get("result_kind") != "error" else "error",
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

        if active_pending_kind == "intent_change" and _is_pending_intent_confirmation(content):
            tool_call_id = "direct-pending-intent-confirmation"
            await _safe_emit_progress(on_progress, "正在按你的确认更新后续参考偏好...")
            tool_started_at = time.monotonic()
            result_text = await update_volunteer_intent_state(
                SimpleNamespace(deps=request_context),
                action="confirm",
            )
            tool_duration_ms = int((time.monotonic() - tool_started_at) * 1000)
            reply = _normalize_user_facing_terms(_direct_pending_intent_reply(result_text))
            new_messages = [
                ModelRequest(parts=[UserPromptPart(content=content)]),
                ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="update_volunteer_intent_state",
                            args={"action": "confirm"},
                            tool_call_id=tool_call_id,
                        )
                    ],
                    model_name="direct-pending-intent-confirmation",
                ),
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name="update_volunteer_intent_state",
                            content=result_text,
                            tool_call_id=tool_call_id,
                        )
                    ]
                ),
                ModelResponse(parts=[TextPart(content=reply)], model_name="direct-pending-intent-confirmation"),
            ]
            try:
                history_to_save = list(history or [])
                history_to_save.extend(new_messages)
                await self.history_store.save(session_id, history_to_save)
            except Exception:
                logger.exception("Failed to save direct pending intent confirmation history: session_id=%s", session_id)
            message_code = _safe_result_field(result_text, "messageCode")
            _log_conversation_turn_event(
                sessionId=session_id,
                userId=user_id,
                scene="intent",
                routingPath="direct_pending_intent_confirm",
                routeDecision={
                    "source": "direct_pending",
                    "matched": True,
                    "confidence": "high",
                    "route": "intent",
                    "reason": "intent_pending_confirmation",
                },
                pendingType="intent",
                actionFamily=None,
                resultKind=None,
                llmRequests=0,
                inputTokens=0,
                outputTokens=0,
                totalTokens=0,
                totalDurationMs=int((time.monotonic() - turn_started_at) * 1000),
                toolDurationMs=tool_duration_ms,
                toolCalls=[
                    {
                        "name": "update_volunteer_intent_state",
                        "durationMs": tool_duration_ms,
                        "success": bool(_safe_result_field(result_text, "applied")),
                        "action": "confirm",
                        "messageCode": message_code,
                    }
                ],
                status="success" if message_code not in {"apply_failed", "confirm_required", "no_pending"} else "error",
                errorType=message_code if message_code in {"apply_failed", "confirm_required", "no_pending"} else None,
            )
            return reply

        if active_pending_kind == "intent_change" and _is_pending_intent_impact_question(content):
            await _safe_emit_progress(on_progress, "正在结合这条待确认想法查看当前方案影响...")
            tool_started_at = time.monotonic()
            reply = await _build_pending_intent_impact_reply(session_id, active_pending)
            tool_duration_ms = int((time.monotonic() - tool_started_at) * 1000)
            if reply:
                new_messages = [
                    ModelRequest(parts=[UserPromptPart(content=content)]),
                    ModelResponse(parts=[TextPart(content=reply)], model_name="pending-intent-impact-fast-route"),
                ]
                try:
                    history_to_save = list(history or [])
                    history_to_save.extend(new_messages)
                    await self.history_store.save(session_id, history_to_save)
                except Exception:
                    logger.exception("Failed to save pending intent impact history: session_id=%s", session_id)
                _log_conversation_turn_event(
                    sessionId=session_id,
                    userId=user_id,
                    scene="intent",
                    routingPath="pending_intent_impact_fast_route",
                    routeDecision={
                        "source": "direct_pending",
                        "matched": True,
                        "confidence": "high",
                        "route": "intent",
                        "reason": "pending_intent_impact_question",
                    },
                    pendingType="intent",
                    actionFamily="preview_intent_impact",
                    resultKind="intent_impact_preview",
                    llmRequests=0,
                    inputTokens=0,
                    outputTokens=0,
                    totalTokens=0,
                    totalDurationMs=int((time.monotonic() - turn_started_at) * 1000),
                    toolDurationMs=tool_duration_ms,
                    toolCalls=[
                        {
                            "name": "enrich_plan_relation_analysis_from_state",
                            "durationMs": tool_duration_ms,
                            "success": True,
                        }
                    ],
                    status="success",
                    errorType=None,
                )
                return reply

        if active_pending is None and _is_plan_action_confirmation(content):
            reply = _build_no_pending_confirmation_guard_reply(history)
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
                routeDecision={
                    "source": "direct_guard",
                    "matched": True,
                    "confidence": "high",
                    "route": "plan",
                    "reason": "no_pending_confirmation_guard",
                },
                pendingType=None,
                actionFamily=None,
                resultKind=None,
                llmRequests=0,
                inputTokens=0,
                outputTokens=0,
                totalTokens=0,
                totalDurationMs=int((time.monotonic() - turn_started_at) * 1000),
                status="success",
                errorType=None,
            )
            return reply

        fast_decision = (
            resolve_plan_fast_route(content)
            if request_context.planning_summary is not None
            else None
        )
        if fast_decision is not None and fast_decision.matched:
            route_decision = fast_decision.route_decision()
            try:
                shadow = action_resolver_shadow_from_plan_fast_decision(
                    text=content,
                    decision=fast_decision,
                    planning_summary=request_context.planning_summary,
                    phase=request_context.conversation_phase,
                )
                if shadow is not None:
                    log_event(
                        "action_resolver_shadow_event",
                        sessionId=session_id,
                        userId=user_id,
                        source="plan_fast_route",
                        routeDecision=route_decision,
                        actualActionFamily=shadow.get("actualActionFamily"),
                        shadowActionFamily=shadow.get("shadowActionFamily"),
                        shadowStage=shadow.get("shadowStage"),
                        actionFamilyMatch=shadow.get("actionFamilyMatch"),
                        missingInputs=shadow.get("missingInputs"),
                        normalizationApplied=shadow.get("normalizationApplied"),
                        totalDurationMs=int((time.monotonic() - turn_started_at) * 1000),
                    )
            except Exception:
                logger.warning(
                    "ActionResolver shadow failed for plan fast route: session_id=%s action_family=%s",
                    session_id,
                    fast_decision.action_family,
                    exc_info=True,
                )
            plan_next_call_id = f"fast-plan-next-{fast_decision.action_family}"
            execute_call_id = f"fast-execute-{fast_decision.action_family}"
            try:
                await _safe_emit_progress(on_progress, "正在读取当前方案并整理这次请求...")
                plan_next_started_at = time.monotonic()
                plan_model = await _plan_next_action_model(
                    SimpleNamespace(deps=request_context),
                    user_goal=fast_decision.user_goal or content,
                    action_family=fast_decision.action_family,  # type: ignore[arg-type]
                    volunteer_ids=fast_decision.volunteer_ids,
                    unit_ids=fast_decision.unit_ids,
                    target_position=fast_decision.target_position,
                    sort_field=fast_decision.filters.get("sort_field"),
                    user_confirmed=False,
                )
                plan_next_duration_ms = int((time.monotonic() - plan_next_started_at) * 1000)
                plan_payload = json.dumps(plan_model.model_dump(), ensure_ascii=False)
                await _safe_emit_progress(
                    on_progress,
                    _plan_fast_route_execute_progress_hint(fast_decision.action_family, plan_model.stage),
                )
                execute_started_at = time.monotonic()
                result_text = await execute_plan_action(SimpleNamespace(deps=request_context), plan_payload)
                execute_duration_ms = int((time.monotonic() - execute_started_at) * 1000)
                result = _parse_tool_return_json(result_text) or {}
                reply = _direct_plan_fast_route_reply(result)
                if isinstance(reply, str):
                    reply = _sanitize_reply_for_user(_normalize_user_facing_terms(reply))

                new_messages = [
                    ModelRequest(parts=[UserPromptPart(content=content)]),
                    ModelResponse(
                        parts=[
                            ToolCallPart(
                                tool_name="plan_next_action",
                                args={
                                    "user_goal": fast_decision.user_goal or content,
                                    "action_family": fast_decision.action_family,
                                    "volunteer_ids": fast_decision.volunteer_ids,
                                    "unit_ids": fast_decision.unit_ids,
                                    "target_position": fast_decision.target_position,
                                    "sort_field": fast_decision.filters.get("sort_field"),
                                    "user_confirmed": False,
                                },
                                tool_call_id=plan_next_call_id,
                            )
                        ],
                        model_name="plan-fast-route",
                    ),
                    ModelRequest(
                        parts=[
                            ToolReturnPart(
                                tool_name="plan_next_action",
                                content=plan_payload,
                                tool_call_id=plan_next_call_id,
                            )
                        ]
                    ),
                    ModelResponse(
                        parts=[
                            ToolCallPart(
                                tool_name="execute_plan_action",
                                args={"plan_payload": plan_payload},
                                tool_call_id=execute_call_id,
                            )
                        ],
                        model_name="plan-fast-route",
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
                    ModelResponse(parts=[TextPart(content=reply)], model_name="plan-fast-route"),
                ]
                try:
                    history_to_save = list(history or [])
                    history_to_save.extend(new_messages)
                    await self.history_store.save(session_id, history_to_save)
                except Exception:
                    logger.exception("Failed to save plan fast route history: session_id=%s", session_id)
                _log_conversation_turn_event(
                    sessionId=session_id,
                    userId=user_id,
                    scene="plan",
                    routingPath="plan_fast_route",
                    routeDecision=route_decision,
                    pendingType=None,
                    actionFamily=result.get("action_family") or fast_decision.action_family,
                    resultKind=result.get("result_kind"),
                    modelProvider=_llm_config_value(self.llm_client, "provider"),
                    modelName=_llm_config_value(self.llm_client, "model_name"),
                    llmRequests=0,
                    inputTokens=0,
                    outputTokens=0,
                    totalTokens=0,
                    toolCallCount=2,
                    totalDurationMs=int((time.monotonic() - turn_started_at) * 1000),
                    llmDurationMs=0,
                    toolDurationMs=plan_next_duration_ms + execute_duration_ms,
                    toolCalls=[
                        {
                            "name": "plan_next_action",
                            "durationMs": plan_next_duration_ms,
                            "success": True,
                            "actionFamily": fast_decision.action_family,
                            "stage": plan_model.stage,
                        },
                        {
                            "name": "execute_plan_action",
                            "durationMs": execute_duration_ms,
                            "success": bool(result) and result.get("result_kind") != "error",
                            "actionFamily": result.get("action_family") or fast_decision.action_family,
                            "stage": result.get("stage"),
                            "resultKind": result.get("result_kind"),
                            "applied": bool(result.get("applied")),
                        },
                    ],
                    postProcessingApplied=[],
                    status="success" if result.get("result_kind") != "error" else "error",
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
            except Exception:
                logger.exception(
                    "Plan fast route failed; falling back to full agent: session_id=%s action_family=%s",
                    session_id,
                    fast_decision.action_family,
                )

        plan_query_decision = resolve_plan_query_fast_route(content, batch=request_context.batch)
        if plan_query_decision.matched:
            route_decision = plan_query_decision.route_decision()
            tool_call_id = "fast-query-volunteer-plan"
            tool_started_at = time.monotonic()
            tool_args = plan_query_decision.tool_args()
            try:
                await _safe_emit_progress(on_progress, "正在查当前方案和候选里的相关结果...")
                tool_result_text = await query_volunteer_plan(
                    SimpleNamespace(deps=request_context),
                    **tool_args,
                )
                tool_duration_ms = int((time.monotonic() - tool_started_at) * 1000)
                reply = _sanitize_reply_for_user(_normalize_user_facing_terms(str(tool_result_text or "").strip()))

                new_messages = [
                    ModelRequest(parts=[UserPromptPart(content=content)]),
                    ModelResponse(
                        parts=[
                            ToolCallPart(
                                tool_name="query_volunteer_plan",
                                args=tool_args,
                                tool_call_id=tool_call_id,
                            )
                        ],
                        model_name="plan-query-fast-route",
                    ),
                    ModelRequest(
                        parts=[
                            ToolReturnPart(
                                tool_name="query_volunteer_plan",
                                content=tool_result_text,
                                tool_call_id=tool_call_id,
                            )
                        ]
                    ),
                    ModelResponse(parts=[TextPart(content=reply)], model_name="plan-query-fast-route"),
                ]
                try:
                    history_to_save = list(history or [])
                    history_to_save.extend(new_messages)
                    await self.history_store.save(session_id, history_to_save)
                except Exception:
                    logger.exception("Failed to save plan query fast route history: session_id=%s", session_id)
                _log_conversation_turn_event(
                    sessionId=session_id,
                    userId=user_id,
                    scene="plan",
                    routingPath="plan_query_fast_route",
                    routeDecision=route_decision,
                    pendingType=None,
                    actionFamily="query_volunteer_plan",
                    resultKind="plan_local_query",
                    modelProvider=_llm_config_value(self.llm_client, "provider"),
                    modelName=_llm_config_value(self.llm_client, "model_name"),
                    llmRequests=0,
                    inputTokens=0,
                    outputTokens=0,
                    totalTokens=0,
                    toolCallCount=1,
                    totalDurationMs=int((time.monotonic() - turn_started_at) * 1000),
                    llmDurationMs=0,
                    toolDurationMs=tool_duration_ms,
                    toolCalls=[
                        {
                            "name": "query_volunteer_plan",
                            "durationMs": tool_duration_ms,
                            "success": True,
                            "scope": plan_query_decision.scope,
                        }
                    ],
                    postProcessingApplied=[],
                    status="success",
                    errorType=None,
                )
                return reply
            except Exception:
                logger.exception(
                    "Plan query fast route failed; falling back to full agent: session_id=%s args=%s",
                    session_id,
                    tool_args,
                )

        major_intent_decision = resolve_major_intent_fast_route(content, batch=request_context.batch)
        if major_intent_decision.matched:
            route_decision = major_intent_decision.route_decision()
            tool_call_id = "fast-preview-major-intent"
            tool_started_at = time.monotonic()
            try:
                await _safe_emit_progress(on_progress, "正在整理这个专业想法的影响，等你确认后才会记入偏好...")
                major_intents = MajorIntentPreviewInput.model_validate(major_intent_decision.major_intents)
                tool_result_text = await preview_current_major_intent_confirmation(
                    SimpleNamespace(deps=request_context),
                    major_intents=major_intents,
                    intent_mode=major_intent_decision.intent_mode,  # type: ignore[arg-type]
                )
                tool_duration_ms = int((time.monotonic() - tool_started_at) * 1000)
                reply = _normalize_pending_intent_reply(str(tool_result_text or "").strip())
                reply = _sanitize_reply_for_user(_normalize_user_facing_terms(reply))

                new_messages = [
                    ModelRequest(parts=[UserPromptPart(content=content)]),
                    ModelResponse(
                        parts=[
                            ToolCallPart(
                                tool_name="preview_current_major_intent_confirmation",
                                args={
                                    "major_intents": major_intent_decision.major_intents,
                                    "intent_mode": major_intent_decision.intent_mode,
                                },
                                tool_call_id=tool_call_id,
                            )
                        ],
                        model_name="major-intent-fast-route",
                    ),
                    ModelRequest(
                        parts=[
                            ToolReturnPart(
                                tool_name="preview_current_major_intent_confirmation",
                                content=tool_result_text,
                                tool_call_id=tool_call_id,
                            )
                        ]
                    ),
                    ModelResponse(parts=[TextPart(content=reply)], model_name="major-intent-fast-route"),
                ]
                try:
                    history_to_save = list(history or [])
                    history_to_save.extend(new_messages)
                    await self.history_store.save(session_id, history_to_save)
                except Exception:
                    logger.exception("Failed to save major intent fast route history: session_id=%s", session_id)
                _log_conversation_turn_event(
                    sessionId=session_id,
                    userId=user_id,
                    scene="intent",
                    routingPath="major_intent_fast_route",
                    routeDecision=route_decision,
                    pendingType=None,
                    actionFamily="preview_major_intent",
                    resultKind="intent_preview",
                    modelProvider=_llm_config_value(self.llm_client, "provider"),
                    modelName=_llm_config_value(self.llm_client, "model_name"),
                    llmRequests=0,
                    inputTokens=0,
                    outputTokens=0,
                    totalTokens=0,
                    toolCallCount=1,
                    totalDurationMs=int((time.monotonic() - turn_started_at) * 1000),
                    llmDurationMs=0,
                    toolDurationMs=tool_duration_ms,
                    toolCalls=[
                        {
                            "name": "preview_current_major_intent_confirmation",
                            "durationMs": tool_duration_ms,
                            "success": True,
                            "intentMode": major_intent_decision.intent_mode,
                            "majorIntents": major_intent_decision.major_intents,
                        }
                    ],
                    postProcessingApplied=[],
                    status="success",
                    errorType=None,
                )
                return reply
            except Exception:
                logger.exception(
                    "Major intent fast route failed; falling back to full agent: session_id=%s major_intents=%s",
                    session_id,
                    major_intent_decision.major_intents,
                )

        major_compare_decision = resolve_major_compare_fast_route(content, batch=request_context.batch)
        if major_compare_decision.matched:
            route_decision = major_compare_decision.route_decision()
            tool_call_id = "fast-compare-majors"
            tool_started_at = time.monotonic()
            try:
                await _safe_emit_progress(on_progress, "正在对比这几个专业的差异...")
                tool_result_text = await compare_majors(
                    SimpleNamespace(deps=request_context),
                    major_compare_decision.major_name1,
                    major_compare_decision.major_name2,
                )
                tool_duration_ms = int((time.monotonic() - tool_started_at) * 1000)
                used_missing_weight_renderer = False
                if is_missing_weight_major_compare_result(tool_result_text):
                    reply = render_missing_weight_major_compare_reply(
                        major_name1=major_compare_decision.major_name1,
                        major_name2=major_compare_decision.major_name2,
                        request_context=request_context,
                    )
                    used_missing_weight_renderer = True
                else:
                    reply = tool_result_text
                reply = _sanitize_reply_for_user(_normalize_user_facing_terms(str(reply or "").strip()))

                new_messages = [
                    ModelRequest(parts=[UserPromptPart(content=content)]),
                    ModelResponse(
                        parts=[
                            ToolCallPart(
                                tool_name="compare_majors",
                                args={
                                    "major_name1": major_compare_decision.major_name1,
                                    "major_name2": major_compare_decision.major_name2,
                                },
                                tool_call_id=tool_call_id,
                            )
                        ],
                        model_name="major-compare-fast-route",
                    ),
                    ModelRequest(
                        parts=[
                            ToolReturnPart(
                                tool_name="compare_majors",
                                content=tool_result_text,
                                tool_call_id=tool_call_id,
                            )
                        ]
                    ),
                    ModelResponse(parts=[TextPart(content=reply)], model_name="major-compare-fast-route"),
                ]
                try:
                    history_to_save = list(history or [])
                    history_to_save.extend(new_messages)
                    await self.history_store.save(session_id, history_to_save)
                except Exception:
                    logger.exception("Failed to save major compare fast route history: session_id=%s", session_id)
                _log_conversation_turn_event(
                    sessionId=session_id,
                    userId=user_id,
                    scene="explore",
                    routingPath="major_compare_fast_route",
                    routeDecision=route_decision,
                    pendingType=None,
                    actionFamily="compare_majors",
                    resultKind="missing_weight_fallback" if is_missing_weight_major_compare_result(tool_result_text) else "major_compare",
                    modelProvider=_llm_config_value(self.llm_client, "provider"),
                    modelName=_llm_config_value(self.llm_client, "model_name"),
                    llmRequests=0,
                    inputTokens=None,
                    outputTokens=None,
                    totalTokens=None,
                    toolCallCount=1,
                    totalDurationMs=int((time.monotonic() - turn_started_at) * 1000),
                    llmDurationMs=0,
                    toolDurationMs=tool_duration_ms,
                    toolCalls=[
                        {
                            "name": "compare_majors",
                            "durationMs": tool_duration_ms,
                            "success": True,
                            "majorNames": [
                                major_compare_decision.major_name1,
                                major_compare_decision.major_name2,
                            ],
                        }
                    ],
                    postProcessingApplied=["missing_weight_major_compare_renderer"] if used_missing_weight_renderer else [],
                    status="success",
                    errorType=None,
                )
                return reply
            except Exception:
                logger.exception(
                    "Major compare fast route failed; falling back to full agent: session_id=%s majors=%s/%s",
                    session_id,
                    major_compare_decision.major_name1,
                    major_compare_decision.major_name2,
                )

        career_direction_decision = resolve_career_direction_fast_route(content)
        if career_direction_decision.matched:
            route_decision = career_direction_decision.route_decision()
            tool_call_id = "fast-analyze-current-career-direction"
            tool_started_at = time.monotonic()
            try:
                await _safe_emit_progress(on_progress, "正在看这条方向和当前方案的承接情况...")
                tool_result_text = await analyze_current_career_direction(SimpleNamespace(deps=request_context))
                tool_duration_ms = int((time.monotonic() - tool_started_at) * 1000)
                reply = _sanitize_reply_for_user(_normalize_user_facing_terms(str(tool_result_text or "").strip()))

                new_messages = [
                    ModelRequest(parts=[UserPromptPart(content=content)]),
                    ModelResponse(
                        parts=[
                            ToolCallPart(
                                tool_name="analyze_current_career_direction",
                                args={
                                    "direction_slots": list(career_direction_decision.direction_slots),
                                },
                                tool_call_id=tool_call_id,
                            )
                        ],
                        model_name="career-direction-fast-route",
                    ),
                    ModelRequest(
                        parts=[
                            ToolReturnPart(
                                tool_name="analyze_current_career_direction",
                                content=tool_result_text,
                                tool_call_id=tool_call_id,
                            )
                        ]
                    ),
                    ModelResponse(parts=[TextPart(content=reply)], model_name="career-direction-fast-route"),
                ]
                try:
                    history_to_save = list(history or [])
                    history_to_save.extend(new_messages)
                    await self.history_store.save(session_id, history_to_save)
                except Exception:
                    logger.exception("Failed to save career direction fast route history: session_id=%s", session_id)
                _log_conversation_turn_event(
                    sessionId=session_id,
                    userId=user_id,
                    scene="explore",
                    routingPath="career_direction_fast_route",
                    routeDecision=route_decision,
                    pendingType=None,
                    actionFamily="analyze_current_career_direction",
                    resultKind="career_direction_analysis",
                    modelProvider=_llm_config_value(self.llm_client, "provider"),
                    modelName=_llm_config_value(self.llm_client, "model_name"),
                    llmRequests=0,
                    inputTokens=None,
                    outputTokens=None,
                    totalTokens=None,
                    toolCallCount=1,
                    totalDurationMs=int((time.monotonic() - turn_started_at) * 1000),
                    llmDurationMs=0,
                    toolDurationMs=tool_duration_ms,
                    toolCalls=[
                        {
                            "name": "analyze_current_career_direction",
                            "durationMs": tool_duration_ms,
                            "success": True,
                            "directionSlots": list(career_direction_decision.direction_slots),
                        }
                    ],
                    postProcessingApplied=[],
                    status="success",
                    errorType=None,
                )
                return reply
            except Exception:
                logger.exception(
                    "Career direction fast route failed; falling back to full agent: session_id=%s direction_slots=%s",
                    session_id,
                    career_direction_decision.direction_slots,
                )

        llm_started_at = time.monotonic()
        reply, new_messages, all_messages, usage = await self.agent.run_with_message_deltas(
            user_prompt=content,
            message_history=runtime_history.model_history,
            deps=request_context,
            on_progress=on_progress,
        )
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
        if (
            (plan_chain_used or _should_guard_plan_reply(content))
            and isinstance(reply, str)
            and _plan_reply_needs_normalization(reply)
        ):
            normalized_reply = _normalize_plan_reply_style(reply)
            _replace_text_reply(new_messages, reply, normalized_reply)
            _replace_text_reply(all_messages, reply, normalized_reply)
            reply = normalized_reply

        if plan_chain_used and isinstance(reply, str):
            bounded_reply = _append_plan_preview_confirmation_boundary(reply, new_messages)
            if bounded_reply != reply:
                _replace_text_reply(new_messages, reply, bounded_reply)
                _replace_text_reply(all_messages, reply, bounded_reply)
                reply = bounded_reply

        if intent_preview_used and isinstance(reply, str):
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

        # ── 保存历史 ──────────────────────────────────────────────
        try:
            history_to_save = list(history or [])
            if history_to_save and new_messages:
                history_to_save.extend(new_messages)
            elif new_messages:
                history_to_save = list(new_messages)
            else:
                runtime_len = len(runtime_history.model_history or [])
                inferred_new_messages = list(all_messages[runtime_len:]) if len(all_messages) >= runtime_len else []
                if history_to_save and inferred_new_messages:
                    history_to_save.extend(inferred_new_messages)
                elif inferred_new_messages:
                    history_to_save = inferred_new_messages
                elif not history_to_save:
                    history_to_save = list(all_messages)

            await self.history_store.save(session_id, history_to_save)
        except Exception:
            logger.exception("Failed to save chat history: session_id=%s", session_id)

        workspace_refresh_targets = _tool_calls_include_plan_workspace_refresh(new_messages)
        if not new_messages:
            workspace_refresh_targets = _tool_calls_include_plan_workspace_refresh(all_messages)

        workspace_view_targets = _tool_calls_include_plan_view_targets(
            new_messages if new_messages else all_messages
        )
        tool_messages = new_messages if new_messages else all_messages
        tool_calls = _iter_tool_call_parts(tool_messages)
        tool_returns = _iter_tool_return_parts(tool_messages)
        called_tool_names = [part.tool_name for part in tool_calls]
        observed_tool_calls = _summarize_tool_calls_for_observability(tool_calls, tool_returns)
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
        _log_conversation_turn_event(
            sessionId=session_id,
            userId=user_id,
            scene=scene,
            routingPath="full_agent",
            routeDecision={
                "source": "full_agent",
                "matched": True,
                "confidence": "model",
                "route": scene,
                "fallbackReason": "no_direct_route",
            },
            pendingType=pending_type,
            actionFamily=action_family,
            modelProvider=_llm_config_value(self.llm_client, "provider"),
            modelName=_llm_config_value(self.llm_client, "model_name"),
            llmRequests=getattr(usage, "requests", None),
            inputTokens=getattr(usage, "input_tokens", None),
            outputTokens=getattr(usage, "output_tokens", None),
            totalTokens=getattr(usage, "total_tokens", None),
            toolCallCount=getattr(usage, "tool_calls", None),
            totalDurationMs=int((time.monotonic() - turn_started_at) * 1000),
            llmDurationMs=llm_duration_ms,
            toolDurationMs=None,
            toolCalls=observed_tool_calls,
            postProcessingApplied=[],
            status="success",
            errorType=None,
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

        result_json = await _apply_selected_intents(
            session_id=session_id,
            batch=batch,
            selected_data=selected_data,
        )
        try:
            state_result = parse_intent_state_update_result(result_json)
            result = render_intent_state_update(state_result)
        except Exception:
            logger.warning("Failed to parse intent selection result: session_id=%s", session_id, exc_info=True)
            state_result = None
            result = "处理这一步时发生错误，请稍后重试。"

        if state_result and state_result.intentMode == "constraint" and state_result.candidateFilters:
            return WSResponse(
                type="planningWorkspaceAction",
                session_id=session_id,
                content=json.dumps(
                    {
                        "targetView": "candidate",
                        "refresh": True,
                        "candidateFilters": state_result.candidateFilters,
                    },
                    ensure_ascii=False,
                ),
            )

        return result
