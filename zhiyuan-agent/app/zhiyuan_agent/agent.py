"""Release 4.0 Zhiyuan Agent PoC implementation."""

from __future__ import annotations

import contextlib
import json
from typing import Any

from pydantic_ai.messages import ToolReturnPart

from app.agent.base_agent import BaseAgent
from app.agent.context import RequestContext
from app.llm.client import LLMClient
from app.zhiyuan_agent.prompt import build_zhiyuan_agent_instructions
from app.zhiyuan_agent.tools import (
    answer_policy,
    compare_entities,
    confirm_pending,
    explore_topic,
    preview_intent_change,
    preview_plan_action,
    query_plan,
    read_state,
    review_plan,
)


_TERMINAL_NEXT_STEPS = {"confirm", "clarify"}
_POC_TOOL_NAMES = {
    "read_state",
    "answer_policy",
    "compare_entities",
    "explore_topic",
    "preview_intent_change",
    "preview_plan_action",
    "query_plan",
    "review_plan",
    "confirm_pending",
}
_COMPOSABLE_READONLY_TOOLS = {
    "answer_policy",
    "compare_entities",
    "explore_topic",
    "query_plan",
    "review_plan",
}


class ZhiyuanAgent(BaseAgent[str]):
    """Compact orthogonal-tool agent used to validate the 4.0 PoC design."""

    MAX_TOOL_CALLS_PER_TURN = 3

    def __init__(self, llm_client: LLMClient):
        super().__init__(
            llm_client=llm_client,
            instructions=build_zhiyuan_agent_instructions,
            output_type=str,
            deps_type=RequestContext,
            tools=[
                read_state,
                answer_policy,
                compare_entities,
                explore_topic,
                preview_intent_change,
                preview_plan_action,
                query_plan,
                review_plan,
                confirm_pending,
            ],
        )
        self.agent.model_settings = {
            **dict(self.agent.model_settings or {}),
            "parallel_tool_calls": False,
        }

    def get_progress_hint(self, tool_name: str) -> str | None:
        return {
            "read_state": "正在读取当前状态...",
            "answer_policy": "正在核对报考规则...",
            "compare_entities": "正在整理对比资料...",
            "explore_topic": "正在做只读分析...",
            "preview_intent_change": "正在整理待确认预览...",
            "preview_plan_action": "正在整理方案调整预览...",
            "query_plan": "正在查询当前方案...",
            "review_plan": "正在审查当前方案...",
            "confirm_pending": "正在处理待确认内容...",
        }.get(tool_name)

    def should_return_directly_from_tool(
        self,
        tool_names: list[str],
        tool_returns: list[ToolReturnPart],
        deps: Any | None = None,
    ) -> bool:
        if not tool_names or not tool_returns:
            return False
        for tool_return in tool_returns:
            payload = self._parse_tool_payload(tool_return)
            if not isinstance(payload, dict):
                continue
            if self._is_terminal_tool_payload(tool_return, payload):
                if self._should_retry_incomplete_plan_action(tool_return, payload):
                    continue
                return True
        return False

    @staticmethod
    def _is_terminal_tool_payload(tool_return: ToolReturnPart, payload: dict[str, Any]) -> bool:
        next_step = str(payload.get("next_step") or "").strip()
        if next_step in _TERMINAL_NEXT_STEPS:
            return True
        tool_name = str(getattr(tool_return, "tool_name", "") or "").strip()
        return tool_name == "confirm_pending" and next_step == "respond"

    def _should_retry_incomplete_plan_action(self, tool_return: ToolReturnPart, payload: dict[str, Any]) -> bool:
        if str(getattr(tool_return, "tool_name", "") or "").strip() != "preview_plan_action":
            return False
        if str(payload.get("next_step") or "").strip() != "clarify":
            return False
        data = payload.get("data")
        if not isinstance(data, dict):
            return False
        reason = str(data.get("reason") or "").strip()
        return reason in {
            "missing_targets",
            "missing_filters",
            "review_issue_not_found",
            "review_issue_units_not_in_plan",
            "candidate_items_unavailable",
            "candidate_no_match",
            "candidate_insufficient",
            "missing_old_items",
        }

    def render_direct_tool_output(
        self,
        tool_names: list[str],
        tool_returns: list[ToolReturnPart],
        deps: Any | None = None,
    ) -> str | None:
        for index, tool_return in reversed(list(enumerate(tool_returns))):
            payload = self._parse_tool_payload(tool_return)
            if not isinstance(payload, dict):
                continue
            if not self._is_terminal_tool_payload(tool_return, payload):
                continue
            rendered = self._render_tool_payload(payload)
            if rendered:
                prefix = self._render_prior_readonly_context(tool_returns[:index])
                if prefix:
                    return f"{prefix}\n\n下面是这次待确认预览：\n\n{rendered}"
                return rendered
        return None

    def _guard_repeated_tool_calls(self, tool_names: list[str], observability: dict[str, Any]) -> str | None:
        guarded = super()._guard_repeated_tool_calls(tool_names, observability)
        if guarded:
            return guarded

        counts = observability.get("toolNameCounts")
        total = sum(int(value or 0) for value in counts.values()) if isinstance(counts, dict) else 0
        if total <= self.MAX_TOOL_CALLS_PER_TURN:
            return None

        observability["toolLoopGuarded"] = True
        observability["guardedToolName"] = "total_tool_calls"
        observability["guardedToolCount"] = total
        observability["maxToolCallsPerTurn"] = self.MAX_TOOL_CALLS_PER_TURN
        return self.render_tool_loop_guard_output("total_tool_calls", total)

    def render_tool_loop_guard_output(self, tool_name: str, count: int) -> str:
        if tool_name == "total_tool_calls":
            return (
                "这轮已经达到工具调用上限，我先停止继续尝试。"
                "请把问题再缩小一点，或直接指定要查方案、分析方向还是整理报考要求预览。"
            )
        return super().render_tool_loop_guard_output(tool_name, count)

    def render_tool_loop_guard_output_from_history(
        self,
        tool_name: str,
        count: int,
        messages: list[Any],
    ) -> str | None:
        if tool_name != "total_tool_calls":
            return super().render_tool_loop_guard_output_from_history(tool_name, count, messages)
        recent = self._find_recent_poc_tool_return(messages)
        if recent:
            return f"这轮已经达到工具调用上限，我先按已拿到的结果回答。\n\n{recent}"
        return None

    @staticmethod
    def _parse_tool_payload(tool_return: ToolReturnPart) -> dict[str, Any] | None:
        content = getattr(tool_return, "content", None)
        if not isinstance(content, str):
            return None
        with contextlib.suppress(Exception):
            payload = json.loads(content)
            if isinstance(payload, dict):
                return payload
        return None

    @staticmethod
    def _render_tool_payload(payload: dict[str, Any]) -> str | None:
        message = str(payload.get("message") or "").strip()
        if message:
            return message

        data = payload.get("data")
        if isinstance(data, dict):
            for key in ("analysis", "preview", "summary", "guidance"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
                if isinstance(value, list) and value:
                    return "\n".join(f"- {item}" for item in value if str(item).strip())
        return None

    @classmethod
    def _render_prior_readonly_context(cls, tool_returns: list[ToolReturnPart]) -> str | None:
        for tool_return in reversed(tool_returns):
            tool_name = str(getattr(tool_return, "tool_name", "") or "").strip()
            if tool_name not in _COMPOSABLE_READONLY_TOOLS:
                continue
            payload = cls._parse_tool_payload(tool_return)
            if not isinstance(payload, dict):
                continue
            if str(payload.get("next_step") or "").strip() != "respond":
                continue
            rendered = cls._render_tool_payload(payload)
            if rendered:
                return cls._trim_compound_context(rendered)
        return None

    @staticmethod
    def _trim_compound_context(text: str, *, limit: int = 600) -> str:
        compact = str(text or "").strip()
        if len(compact) <= limit:
            return compact
        return compact[:limit].rstrip() + "..."

    def _find_recent_poc_tool_return(self, messages: list[Any]) -> str | None:
        for message in reversed(messages or []):
            parts = list(getattr(message, "parts", []) or [])
            for part in reversed(parts):
                if not isinstance(part, ToolReturnPart):
                    continue
                if str(getattr(part, "tool_name", "") or "") not in _POC_TOOL_NAMES:
                    continue
                payload = self._parse_tool_payload(part)
                if not isinstance(payload, dict):
                    continue
                rendered = self._render_tool_payload(payload)
                if rendered:
                    return rendered
        return None
