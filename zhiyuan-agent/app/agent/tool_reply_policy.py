from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal


ReplyStrategy = Literal[
    "continue_model",
    "direct_reply",
    "direct_blocking",
    "preview_wait_confirm",
]


INTENT_PREVIEW_TOOL_NAMES = {
    "preview_current_intent_confirmation",
    "preview_current_major_intent_confirmation",
    "preview_current_school_intent_confirmation",
    "preview_current_region_intent_confirmation",
    "preview_current_career_intent_confirmation",
}

READONLY_EXPLORE_TOOL_NAMES = {
    "analyze_current_interest",
    "analyze_current_school_interest",
    "analyze_current_major_interest",
    "analyze_current_region_interest",
    "analyze_current_career_direction",
}

DIRECT_BLOCKING_REPLY_FOCUS = {
    "needs_volunteer_selection",
    "needs_candidate_selection",
    "missing_plan_payload",
}

DIRECT_REPLY_RESULT_KINDS = {
    "no_change",
}

_QUERY_VOLUNTEER_PLAN_CONTINUE_MARKERS = (
    "不是局部查询",
    "应先走方案动作预览",
    "查询候选机会失败",
    "查询当前方案时发生错误",
)


@dataclass(frozen=True)
class ToolReplyDecision:
    strategy: ReplyStrategy = "continue_model"
    reply: str | None = None
    reason: str = ""

    @property
    def should_return_directly(self) -> bool:
        return self.strategy in {"direct_reply", "direct_blocking", "preview_wait_confirm"} and bool(
            self.reply and self.reply.strip()
        )


def decide_tool_reply(
    tool_names: list[str],
    tool_returns: list[Any],
    deps: Any | None = None,  # noqa: ARG001 - reserved for context-sensitive policies.
) -> ToolReplyDecision:
    """Decide whether a tool result is already a safe user-facing final reply.

    Default is conservative: keep model summarization. Direct return is only
    allowed for a single tool result with either an explicit reply strategy or a
    high-confidence structured result.
    """
    if len(tool_names) != 1 or len(tool_returns) != 1:
        return ToolReplyDecision()

    tool_name = str(tool_names[0] or "").strip()
    if _has_prior_synthesis_facts(deps, current_tool_names=tool_names):
        return ToolReplyDecision(reason="prior_tool_facts_need_model_synthesis")
    tool_return = tool_returns[0]
    payload = parse_tool_return_payload(tool_return)
    raw_text = parse_tool_return_text(tool_return)

    explicit_strategy = _normalize_reply_strategy(payload.get("reply_strategy")) if payload else ""
    if explicit_strategy == "continue_model":
        return ToolReplyDecision(
            strategy="continue_model",
            reason="explicit_continue_model",
        )
    if explicit_strategy in {"direct_reply", "direct_blocking", "preview_wait_confirm"}:
        reply = _payload_reply(payload) or raw_text
        return ToolReplyDecision(
            strategy=explicit_strategy,  # type: ignore[arg-type]
            reply=reply,
            reason="explicit_reply_strategy",
        )

    if tool_name in INTENT_PREVIEW_TOOL_NAMES:
        reply = _payload_reply(payload) or raw_text
        return ToolReplyDecision(
            strategy="preview_wait_confirm",
            reply=reply,
            reason="intent_preview_tool",
        )

    if tool_name == "query_volunteer_plan" and raw_text and not _query_result_should_continue(raw_text):
        return ToolReplyDecision(
            strategy="direct_reply",
            reply=raw_text,
            reason="read_only_plan_query_result",
        )

    if tool_name in READONLY_EXPLORE_TOOL_NAMES:
        reply = _readonly_explore_reply(payload, raw_text)
        if reply:
            return ToolReplyDecision(
                strategy="direct_reply",
                reply=reply,
                reason="read_only_explore_result",
            )

    if payload:
        result_kind = str(payload.get("result_kind") or "").strip()
        action_family = str(payload.get("action_family") or "").strip()
        reply_focus = _reply_focus_set(payload)
        reply = _payload_reply(payload)
        if (
            tool_name == "execute_plan_action"
            and action_family == "query_state"
            and result_kind == "status_overview"
            and reply
        ):
            return ToolReplyDecision(
                strategy="direct_reply",
                reply=reply,
                reason="structured_status_overview",
            )
        if (
            tool_name == "execute_plan_action"
            and action_family == "review_plan"
            and result_kind == "review_result"
            and "direct_review_reply" in reply_focus
            and reply
        ):
            return ToolReplyDecision(
                strategy="direct_reply",
                reply=reply,
                reason="structured_review_result",
            )
        if result_kind == "error" and reply_focus & DIRECT_BLOCKING_REPLY_FOCUS and reply:
            return ToolReplyDecision(
                strategy="direct_blocking",
                reply=reply,
                reason="structured_blocking_result",
            )
        if (
            tool_name == "execute_plan_action"
            and result_kind == "preview_only"
            and str(payload.get("action_family") or "").strip() == "sort_ordered_plan"
            and reply
        ):
            return ToolReplyDecision(
                strategy="preview_wait_confirm",
                reply=reply,
                reason="structured_sort_preview",
            )
        if (
            tool_name == "execute_plan_action"
            and result_kind == "preview_only"
            and ({"unit_position_preview", "volunteer_position_preview"} & reply_focus)
            and reply
        ):
            return ToolReplyDecision(
                strategy="preview_wait_confirm",
                reply=reply,
                reason="structured_position_preview",
            )
        if (
            tool_name == "execute_plan_action"
            and action_family == "add_units"
            and result_kind == "preview_only"
            and "confirmation_required" in reply_focus
            and reply
        ):
            return ToolReplyDecision(
                strategy="preview_wait_confirm",
                reply=reply,
                reason="structured_add_preview",
            )
        if (
            tool_name == "execute_plan_action"
            and result_kind == "compensation_preview"
            and "empty_compensation_preview" not in reply_focus
            and reply
        ):
            return ToolReplyDecision(
                strategy="preview_wait_confirm",
                reply=reply,
                reason="structured_compensation_preview",
            )
        if result_kind in DIRECT_REPLY_RESULT_KINDS and reply:
            return ToolReplyDecision(
                strategy="direct_reply",
                reply=reply,
                reason=f"structured_{result_kind}_result",
            )

    return ToolReplyDecision()


def parse_tool_return_payload(tool_return: Any) -> dict[str, Any]:
    content = getattr(tool_return, "content", None)
    if isinstance(content, dict):
        return content
    if not isinstance(content, str) or not content.strip():
        return {}
    try:
        parsed = json.loads(content)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def parse_tool_return_text(tool_return: Any) -> str | None:
    content = getattr(tool_return, "content", None)
    if isinstance(content, str):
        text = content.strip()
        return text or None
    if isinstance(content, dict):
        return _payload_reply(content)
    return None


def _payload_reply(payload: dict[str, Any]) -> str | None:
    for key in ("summary", "state_summary", "message", "reply"):
        text = str(payload.get(key) or "").strip()
        if text:
            return text
    return None


def _reply_focus_set(payload: dict[str, Any]) -> set[str]:
    reply_focus = payload.get("reply_focus") or []
    if not isinstance(reply_focus, list):
        return set()
    return {str(item or "").strip() for item in reply_focus if str(item or "").strip()}


def _normalize_reply_strategy(value: Any) -> str:
    text = str(value or "").strip()
    if text in {"direct_reply", "direct_blocking", "preview_wait_confirm", "continue_model"}:
        return text
    return ""


def _has_prior_synthesis_facts(deps: Any | None, *, current_tool_names: list[str]) -> bool:
    """Keep multi-tool analysis turns on the model synthesis path.

    Direct tool return is safe when the current tool result is the whole answer.
    It is unsafe after the same turn already collected independent Explore or
    comparison facts: the last tool can otherwise overwrite the user's primary
    question, for example a career-direction analysis followed by a plan review.
    """
    if deps is None:
        return False
    observability = getattr(deps, "agent_observability", None)
    if not isinstance(observability, dict):
        return False
    counts = observability.get("toolNameCounts")
    if not isinstance(counts, dict):
        return False
    synthesis_tools = READONLY_EXPLORE_TOOL_NAMES | {
        "compare_majors",
        "compare_majors_adhoc",
        "compare_major_options",
        "get_major_introductions",
        "get_major_introduction",
    }
    current_counts: dict[str, int] = {}
    for tool_name in current_tool_names:
        current_counts[tool_name] = current_counts.get(tool_name, 0) + 1
    for tool_name in synthesis_tools:
        prior_count = int(counts.get(tool_name) or 0) - int(current_counts.get(tool_name) or 0)
        if prior_count > 0:
            return True
    return False


def _query_result_should_continue(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return True
    return any(marker in normalized for marker in _QUERY_VOLUNTEER_PLAN_CONTINUE_MARKERS)


def _readonly_explore_reply(payload: dict[str, Any], raw_text: str | None) -> str | None:
    if payload:
        return _payload_reply(payload)
    text = str(raw_text or "").strip()
    if not text:
        return None
    if _looks_like_structured_payload_without_reply(text):
        return None
    return text


def _looks_like_structured_payload_without_reply(text: str) -> bool:
    stripped = text.strip()
    return (stripped.startswith("{") and stripped.endswith("}")) or (
        stripped.startswith("[") and stripped.endswith("]")
    )
