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

DIRECT_BLOCKING_REPLY_FOCUS = {
    "needs_volunteer_selection",
    "needs_candidate_selection",
    "missing_plan_payload",
}

DIRECT_REPLY_RESULT_KINDS = {
    "no_change",
}


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
    tool_return = tool_returns[0]
    payload = parse_tool_return_payload(tool_return)
    raw_text = parse_tool_return_text(tool_return)

    explicit_strategy = _normalize_reply_strategy(payload.get("reply_strategy")) if payload else ""
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

    if payload:
        result_kind = str(payload.get("result_kind") or "").strip()
        reply_focus = _reply_focus_set(payload)
        reply = _payload_reply(payload)
        if result_kind == "error" and reply_focus & DIRECT_BLOCKING_REPLY_FOCUS and reply:
            return ToolReplyDecision(
                strategy="direct_blocking",
                reply=reply,
                reason="structured_blocking_result",
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
