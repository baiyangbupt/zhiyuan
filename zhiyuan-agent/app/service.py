from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart

from app.agent.base_agent import ProgressCallback
from app.agent.chat_agent import ChatAgent
from app.agent.context import PlanningSummary, RequestContext, ScoreDetail
from app.models.conversation_phase import ConversationPhase, PendingConfirmation
from app.agent.usage_tracker import UsageTracker
from app.data.history_store import ChatHistoryStore
from app.data.message_utils import pydantic_ai_messages_to_dicts
from app.llm.client import LLMClient
from app.schemas.user_profile import UserProfile
from app.schemas.ws import WSResponse
from app.tools.explore_followup_tool import handle_interest_analysis_action_result
from app.tools.plan_execution_tool import (
    clear_recent_plan_execution_result,
    consume_recent_plan_execution_result,
    execute_plan_action,
)
from app.tools.plan_orchestration_models import normalize_plan_action_payload
from app.tools.intent_state_tool import (
    apply_selected_intents as _apply_selected_intents,
    update_volunteer_intent_state,
)
from app.tools.intent_response_tool import (
    parse_explore_followup_result,
    parse_intent_state_update_result,
    render_explore_followup_result,
    render_intent_state_update,
)
from app.util.internal_client import (
    get_intent_change_cache,
    get_planning_state,
    get_user_init_profile,
    get_user_score_detail,
)

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
_UNBACKED_CONFIRM_SENTENCE_RE = re.compile(r"确认要我.*执行")


@dataclass
class ChatServiceResponseEnvelope:
    """服务层统一回复结构，允许主文本外再携带附加工作台动作。"""

    primary: str | WSResponse
    followups: list[WSResponse] = field(default_factory=list)


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


def _dedupe_workspace_targets(targets: list[str]) -> list[str]:
    deduped: list[str] = []
    for target in targets:
        value = str(target or "").strip()
        if not value or value in deduped:
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
    "draft": {
        "title": "查看草稿方案",
        "content": "已刷新草稿方案，可以查看本次生成或调整后的草稿内容。",
        "actionText": "打开草稿方案",
    },
}


def _build_workspace_action_response(session_id: str, target: str, *, refresh: bool = True) -> WSResponse:
    target_value = str(target or "").strip()
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
    "pin_unit",
    "unpin_unit",
    "replace_units",
    "regenerate_order",
    "apply_compensation",
}

_EXECUTE_PLAN_ACTION_VIEW_FAMILIES = {
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
        "review_plan": ["review"],
        "generate_plan": ["ordered"],
        "add_units": ["ordered"],
        "remove_units": ["ordered"],
        "move_unit": ["ordered"],
        "pin_unit": ["ordered"],
        "unpin_unit": ["ordered"],
        "replace_units": ["ordered"],
        "regenerate_order": ["ordered"],
        "apply_compensation": ["ordered"],
    }
    for part in _iter_tool_call_parts(messages):
        if part.tool_name == "run_planning_review":
            return ["review"]
        execute_action_family = _extract_execute_plan_action_family(part)
        if execute_action_family:
            return execute_plan_action_targets.get(execute_action_family, [])
        if part.tool_name in mutating_tool_names:
            return ["ordered"]
    return []


def _tool_calls_include_plan_view_targets(messages: list[Any] | None) -> list[str]:
    """Extract view-only workspace targets from query actions (no data refresh needed)."""
    view_targets: list[str] = []
    for part in _iter_tool_return_parts(messages):
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
        ("好的，我记下了你对", "我先把你对"),
        ("好的，我已经记下了你对", "我先把你对"),
        ("我记下了你对", "我先把你对"),
        ("我已经记下了你对", "我先把你对"),
        ("好的，我记下了", "我先整理一下"),
        ("好的，我已经记下了", "我先整理一下"),
        ("我已经按你的偏好记录下来", "我先把这个偏好整理出来，等你确认后再作为后续参考"),
        ("我已经记录下来", "我先把这个偏好整理出来，等你确认后再作为后续参考"),
    )
    for source, target in replacements:
        normalized = normalized.replace(source, target)
    if normalized != reply and "确认" not in normalized:
        normalized = normalized.rstrip("。") + "。如果确认要按这个方向作为后续参考，你再回复确认。"
    return normalized


_PENDING_PLAN_ACTION_FAMILIES = {
    "generate_plan",
    "add_units",
    "remove_units",
    "move_unit",
    "pin_unit",
    "unpin_unit",
    "replace_units",
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
    apply_payload["action_family"] = action_family
    apply_payload["stage"] = "apply"
    apply_payload["requires_confirmation"] = False
    apply_payload["should_refresh_workspace"] = True
    apply_payload["should_rerun_review"] = True
    return {
        "action_family": action_family,
        "user_goal": payload.get("user_goal") or "",
        "summary": summary or payload.get("preview_summary") or "",
        "plan_payload": json.dumps(apply_payload, ensure_ascii=False),
    }


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
        if any(isinstance(part, UserPromptPart) for part in getattr(message, "parts", []) or []):
            latest_pending = None
            pending_calls.clear()
            last_non_actionable_adjustment_goal = None
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
                        continue
                    if (
                        last_non_actionable_adjustment_goal
                        and _text_looks_like_adjustment_request(last_non_actionable_adjustment_goal)
                        and _text_looks_like_adjustment_request(str(candidate_pending.get("user_goal") or "").strip())
                        and str(candidate_pending.get("action_family") or "").strip() in {"generate_plan", "apply_compensation"}
                    ):
                        continue
                    latest_pending = candidate_pending
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
            if result.get("applied") is True and not is_preview_result:
                latest_pending = None
                continue
            if not is_preview_result:
                continue
            effective_action_family = _PLAN_PREVIEW_TO_APPLY_ACTION_FAMILIES.get(action_family, action_family)
            if effective_action_family not in _PENDING_PLAN_ACTION_FAMILIES:
                continue
            call_payload = pending_calls.get(str(part.tool_call_id or ""))
            if not call_payload:
                continue
            candidate_pending = _build_pending_plan_action_from_payload(
                call_payload,
                summary=result.get("summary") or call_payload.get("preview_summary") or "",
            )
            if candidate_pending is None:
                continue
            if (
                last_non_actionable_adjustment_goal
                and _text_looks_like_adjustment_request(last_non_actionable_adjustment_goal)
                and _text_looks_like_adjustment_request(str(candidate_pending.get("user_goal") or "").strip())
                and str(candidate_pending.get("action_family") or "").strip() in {"generate_plan", "apply_compensation"}
            ):
                continue
            latest_pending = candidate_pending

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


def _is_basic_plan_status_question(content: str) -> bool:
    normalized = re.sub(r"\s+", "", (content or "").strip())
    normalized = normalized.strip("。.!！?")
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
    }


def _build_basic_plan_status_reply(planning: PlanningSummary) -> str:
    total = planning.ordered_total or planning.draft_total
    target = (
        planning.ordered_target_total
        or planning.draft_target_total
        or max(planning.ordered_total, planning.draft_total, total)
    )
    if total <= 0:
        return "当前还没有正式方案。你可以直接说“生成一版方案”，我会先给你看生成预览，确认后再执行。"

    phase_text = planning.phase or "已生成"
    lines = [
        "方案已经有了。",
        "",
        f"- 当前排序志愿数：{planning.ordered_total}/{target}",
        f"- 当前草稿志愿数：{planning.draft_total}/{target}",
        f"- 当前阶段：{phase_text}",
        f"- 审查结果：风险{planning.review_risk_count}项，提醒{planning.review_warn_count}项",
    ]
    if planning.risk_summaries:
        lines.append(f"- 主要提醒：{'；'.join(planning.risk_summaries[:2])}")
    if planning.pending_action_count:
        lines.append(f"- 待处理建议：{planning.pending_action_count}项")
    lines.append("")
    lines.append("如果要看具体冲突、梯度或怎么调整，可以继续让我审查当前方案。")
    return "\n".join(lines)


async def _has_pending_intent_change(session_id: str) -> bool:
    try:
        cache_result = await get_intent_change_cache(session_id)
    except Exception:
        logger.warning("Failed to fetch intent change cache for confirmation guard: session_id=%s", session_id, exc_info=True)
        return False
    cache_data = (cache_result or {}).get("data", {}).get("planEditCache")
    return bool(cache_data)


def _direct_pending_intent_reply(result_text: str) -> str:
    try:
        result = parse_intent_state_update_result(result_text)
    except Exception:
        logger.warning("Failed to parse direct pending intent confirmation result", exc_info=True)
        return "已按你的确认应用上一轮意向调整。"
    return render_intent_state_update(result)


def _should_guard_plan_reply(content: str) -> bool:
    return any(keyword in content for keyword in _PLAN_STYLE_GUARD_PROMPT_KEYWORDS)


def _normalize_user_facing_terms(reply: str) -> str:
    """Remove internal product terms from user-facing replies."""
    if not isinstance(reply, str) or "画像" not in reply:
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
    return normalized


def _plan_reply_needs_normalization(reply: str) -> bool:
    """Only guard severe user-experience failures, not natural model formatting."""
    if any(marker in reply for marker in _PLAN_STYLE_SEVERE_MARKERS):
        return True
    return any(line.strip() in _PLAN_STYLE_DANGLING_EXACT_LINES for line in reply.splitlines())


def _normalize_plan_reply_style(reply: str) -> str:
    """Thin service guard for severe Plan reply wording; natural Markdown/lists are allowed."""
    if not reply.strip():
        return reply

    normalized_lines: list[str] = []
    for raw_line in reply.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            if normalized_lines and normalized_lines[-1] != "":
                normalized_lines.append("")
            continue
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
    return reply


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
        "review_result": "这轮审查已经执行完了，我先把核心结果直接给你：",
        "adjustment_analysis": "这轮调整分析已经执行完了，我先把核心结果直接给你：",
        "status_overview": "这轮方案状态查询已经执行完了，我先把核心结果直接给你：",
        "generation_result": "这轮方案生成已经执行完了，我先把核心结果直接给你：",
        "ordered_snapshot": "这轮排序方案查询已经执行完了，我先把核心结果直接给你：",
        "draft_snapshot": "这轮草稿方案查询已经执行完了，我先把核心结果直接给你：",
        "candidate_snapshot": "这轮候选查询已经执行完了，我先把核心结果直接给你：",
        "mutation_result": "这轮方案调整已经执行完了，我先把核心结果直接给你：",
    }
    facts = result.get("facts") if isinstance(result.get("facts"), dict) else {}
    relation = facts.get("intent_relation") if isinstance(facts.get("intent_relation"), dict) else {}
    coverage = str(relation.get("coverage") or "").strip()
    aligned_examples = str(relation.get("aligned_examples") or "").strip()
    conflict_examples = str(relation.get("conflict_examples") or "").strip()
    next_step_hints = result.get("next_step_hints") if isinstance(result.get("next_step_hints"), list) else []

    lines = [lead_map.get(result_kind, "这轮方案分析已经执行完了，我先把核心结果直接给你："), "", summary]
    if coverage:
        lines.append(f"- {coverage}")
    if aligned_examples:
        lines.append(f"- {aligned_examples}")
    if conflict_examples:
        lines.append(f"- {conflict_examples}")
    if next_step_hints:
        first_hint = str(next_step_hints[0] or "").strip()
        if first_hint:
            lines.extend(["", first_hint])
    return _normalize_user_facing_terms("\n".join(lines))


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

    def __init__(self, llm_client: LLMClient, history_store: ChatHistoryStore):
        self.llm_client = llm_client
        self.agent = ChatAgent(llm_client)
        self.history_store = history_store
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

        # 打印原始 history 内容，便于调试格式
        # if history:
        #     for i, msg in enumerate(history):
        #         logger.info("history[%d] type=%s", i, type(msg).__name__)
        #         #logger.info("history[%d] type=%s content=%s", i, type(msg).__name__, msg)

        # 从 session 历史中构建 chat_history（转为简单 dict 列表）
        chat_history = pydantic_ai_messages_to_dicts(history) if history else []
        pending_plan_action = _extract_pending_plan_action(history)
        # 加上当前用户最新输入
        chat_history.append({"role": "user", "content": content})

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
            planning_response = await get_planning_state(session_id)
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

        pending_intent_change = await _has_pending_intent_change(session_id)

        # 构建统一的 ConversationPhase
        conversation_phase = ConversationPhase.from_legacy_context(
            pending_plan_action=pending_plan_action,
            pending_intent_change=pending_intent_change,
            planning_summary=parsed_planning_summary,
        )

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
        )

        if pending_plan_action and _is_plan_action_confirmation(content):
            action_family = str(pending_plan_action.get("action_family") or "").strip()
            plan_payload = str(pending_plan_action.get("plan_payload") or "")
            tool_call_id = f"direct-{action_family or 'pending-plan'}-confirmation"
            result_text = await execute_plan_action(SimpleNamespace(deps=request_context), plan_payload)
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

        if not pending_plan_action and pending_intent_change and _is_pending_intent_confirmation(content):
            tool_call_id = "direct-pending-intent-confirmation"
            result_text = await update_volunteer_intent_state(
                SimpleNamespace(deps=request_context),
                action="confirm",
            )
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
            return reply

        if parsed_planning_summary and _is_basic_plan_status_question(content):
            reply = _build_basic_plan_status_reply(parsed_planning_summary)
            new_messages = [
                ModelRequest(parts=[UserPromptPart(content=content)]),
                ModelResponse(parts=[TextPart(content=reply)], model_name="direct-plan-status-summary"),
            ]
            try:
                history_to_save = list(history or [])
                history_to_save.extend(new_messages)
                await self.history_store.save(session_id, history_to_save)
            except Exception:
                logger.exception("Failed to save basic plan status history: session_id=%s", session_id)
            return reply

        if (
            not pending_plan_action
            and _is_plan_action_confirmation(content)
            and not pending_intent_change
        ):
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
            return reply

        reply, new_messages, all_messages, usage = await self.agent.run_with_message_deltas(
            user_prompt=content,
            message_history=history,
            deps=request_context,
            on_progress=on_progress,
        )

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
                history_to_save = list(all_messages)

            # Guard against unexpected adapter behavior returning the full history as "new".
            if history and len(history_to_save) < len(all_messages):
                history_to_save = list(all_messages)

            await self.history_store.save(session_id, history_to_save)
        except Exception:
            logger.exception("Failed to save chat history: session_id=%s", session_id)

        workspace_refresh_targets = _tool_calls_include_plan_workspace_refresh(new_messages)
        if not new_messages:
            workspace_refresh_targets = _tool_calls_include_plan_workspace_refresh(all_messages)
        if not workspace_refresh_targets and intent_preview_used_current_turn:
            workspace_refresh_targets = ["candidate"]

        workspace_view_targets = _tool_calls_include_plan_view_targets(
            new_messages if new_messages else all_messages
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
