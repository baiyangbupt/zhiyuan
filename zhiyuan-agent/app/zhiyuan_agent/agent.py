"""Release 4.0 Zhiyuan Agent direct-chain implementation."""

from __future__ import annotations

import contextlib
import json
import re
from dataclasses import replace
from typing import Any

from pydantic_ai import ModelRequestContext, ModelRetry, RunContext, Tool
from pydantic_ai.capabilities import Hooks
from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.tools import ToolDefinition

from app.agent.base_agent import BaseAgent
from app.agent.context import RequestContext, resolve_pending_confirmation
from app.llm.client import LLMClient
from app.zhiyuan_agent.prompt import build_zhiyuan_agent_instructions
from app.zhiyuan_agent.tools import (
    PendingResolution,
    PlanChangeSpec,
    acknowledge_readonly,
    answer_policy,
    compare_entities,
    clarify_request,
    confirm_pending,
    discover_options,
    explore_topic,
    preview_intent_change,
    preview_plan_change,
    preview_plan_action,
    query_plan,
    read_state,
    respond_casual,
    review_plan,
)


_TERMINAL_NEXT_STEPS = {"confirm", "clarify"}
_TERMINAL_RESPOND_TOOL_NAMES = {
    "acknowledge_readonly",
    "clarify_request",
    "confirm_pending",
    "discover_options",
    "review_plan",
    "respond_casual",
    "preview_plan_change",
}
_DIRECT_TOOL_NAMES = {
    "acknowledge_readonly",
    "clarify_request",
    "read_state",
    "answer_policy",
    "compare_entities",
    "discover_options",
    "explore_topic",
    "preview_intent_change",
    "preview_plan_change",
    "preview_plan_action",
    "query_plan",
    "review_plan",
    "respond_casual",
    "confirm_pending",
}
_COMPOSABLE_READONLY_TOOLS = {
    "answer_policy",
    "compare_entities",
    "discover_options",
    "explore_topic",
    "query_plan",
    "review_plan",
}

_FIRST_TOOL_RETRY_FLAG = "firstModelToolCallRetryRequired"


def _is_casual_only_user_text(value: Any) -> bool:
    compact = re.sub(r"[\s，。！？,.!?、~～]+", "", str(value or "")).strip().lower()
    if compact in {"你好", "您好", "嗨", "hello", "hi", "谢谢", "感谢", "你是谁", "你能做什么"}:
        return True
    return compact.startswith(("你好呀", "您好呀", "嗨呀")) and len(compact) <= 6


def _first_tool_requirement_active(ctx: RunContext[RequestContext]) -> bool:
    observability = getattr(ctx.deps, "agent_observability", None)
    retry_required = isinstance(observability, dict) and observability.get(_FIRST_TOOL_RETRY_FLAG) is True
    return ctx.run_step == 1 or retry_required


async def _require_first_model_tool_call(
    ctx: RunContext[RequestContext],
    request_context: ModelRequestContext,
) -> ModelRequestContext:
    if not _first_tool_requirement_active(ctx):
        return request_context
    parameters = request_context.model_request_parameters
    if not parameters.function_tools:
        return request_context
    observability = getattr(ctx.deps, "agent_observability", None)
    if isinstance(observability, dict):
        observability["firstModelToolCallRequired"] = True
    return replace(
        request_context,
        model_request_parameters=replace(parameters, allow_text_output=False),
    )


async def _reject_first_model_text_response(
    ctx: RunContext[RequestContext],
    *,
    request_context: ModelRequestContext,  # noqa: ARG001
    response: ModelResponse,
) -> ModelResponse:
    if not _first_tool_requirement_active(ctx):
        return response
    tool_names = [part.tool_name for part in response.parts if isinstance(part, ToolCallPart)]
    observability = getattr(ctx.deps, "agent_observability", None)
    if len(tool_names) == 1:
        if tool_names[0] == "respond_casual" and not _is_casual_only_user_text(
            getattr(ctx.deps, "current_user_text", "")
        ):
            if isinstance(observability, dict):
                observability[_FIRST_TOOL_RETRY_FLAG] = True
                observability["businessPromptCasualToolRejected"] = True
            response.parts = []
            raise ModelRetry(
                "respond_casual is only valid for a greeting or social message. This user message contains a "
                "business request or stage decision. Choose the matching business tool; if the user wants to "
                "save an unspecified idea without automatic changes, call "
                "clarify_request(kind='missing_intent_content')."
            )
        if isinstance(observability, dict):
            observability[_FIRST_TOOL_RETRY_FLAG] = False
            observability["firstModelToolCallSatisfied"] = True
        return response
    if isinstance(observability, dict):
        observability[_FIRST_TOOL_RETRY_FLAG] = True
        if tool_names:
            observability["firstModelMultipleToolCallsRejected"] = True
            observability["firstModelRejectedToolNames"] = list(tool_names)
            # The rejected calls were never executed; keep them out of persisted
            # history and runner call counts while retaining names in observability.
            response.parts = []
        else:
            observability["firstModelTextRejected"] = True
    raise ModelRetry(
        "The first response must call exactly one available tool. Use clarify_request for a genuinely "
        "ambiguous request, acknowledge_readonly only to close a prior readonly discussion, or "
        "respond_casual only for greetings; do not emit multiple tool calls or describe a pending change in text."
    )


_FIRST_TOOL_REQUIRED_HOOKS = Hooks(
    before_model_request=_require_first_model_tool_call,
    after_model_request=_reject_first_model_text_response,
)


async def _prepare_preview_intent_change_tool(
    ctx: RunContext[RequestContext],
    tool_def: ToolDefinition,
) -> ToolDefinition:
    """Require the pending relationship before a model calls an intent preview."""
    if resolve_pending_confirmation(ctx.deps) is None:
        return tool_def
    schema = dict(tool_def.parameters_json_schema)
    properties = dict(schema.get("properties") or {})
    pending_resolution = dict(properties.get("pending_resolution") or {})
    pending_resolution.pop("default", None)
    pending_resolution["description"] = (
        "Required because this turn started with an active pending item. Choose "
        "replace_active_pending, append_to_active_pending, or hold_new_request."
    )
    properties["pending_resolution"] = pending_resolution
    required = list(schema.get("required") or [])
    if "pending_resolution" not in required:
        required.append("pending_resolution")
    schema["properties"] = properties
    schema["required"] = required
    return replace(tool_def, parameters_json_schema=schema)


_PREVIEW_INTENT_CHANGE_TOOL = Tool(
    preview_intent_change,
    prepare=_prepare_preview_intent_change_tool,
)


async def _preview_plan_change_with_structured_retry(
    ctx: RunContext[RequestContext],
    spec: PlanChangeSpec,
    pending_resolution: PendingResolution = "none",
    raw_user_text: str = "",
) -> str:
    """Preview a structural plan change and enforce exact Proposal selection."""
    result = await preview_plan_change(
        ctx,
        spec=spec,
        pending_resolution=pending_resolution,
        raw_user_text=raw_user_text,
    )
    try:
        payload = json.loads(result)
    except (TypeError, ValueError):
        return result
    data = payload.get("data") if isinstance(payload, dict) else None
    if (
        isinstance(data, dict)
        and payload.get("next_step") == "continue"
        and data.get("reason") == "review_repair_requires_exact_selection"
    ):
        retry_payload = {
            "reason": "review_repair_requires_exact_selection",
            "instruction": (
                "Re-call preview_plan_change now with the same objective and exactly one directly matching "
                "status=ready review_check proposal's review_issue_code and strategy. Select semantically from "
                "the structured options, never by list order. If no unique direct match exists, do not call a "
                "different tool and do not claim that a preview was created."
            ),
            "required_tool": "preview_plan_change",
            "required_fields": data.get("retry_required_fields") or [],
            "objective": data.get("objective"),
            "proposal_options": data.get("proposal_options") or [],
            "excluded_cross_goal_options": data.get("excluded_cross_goal_options") or [],
            "selection_rule": data.get("selection_rule"),
        }
        raise ModelRetry(json.dumps(retry_payload, ensure_ascii=False, separators=(",", ":")))
    return result


_PREVIEW_PLAN_CHANGE_TOOL = Tool(
    _preview_plan_change_with_structured_retry,
    name="preview_plan_change",
    description=preview_plan_change.__doc__,
    prepare=_prepare_preview_intent_change_tool,
    max_retries=1,
)


class ZhiyuanAgent(BaseAgent[str]):
    """Compact orthogonal-tool agent for the 4.0 direct chain."""

    MAX_TOOL_CALLS_PER_TURN = 3

    def __init__(self, llm_client: LLMClient):
        super().__init__(
            llm_client=llm_client,
            instructions=build_zhiyuan_agent_instructions,
            output_type=str,
            deps_type=RequestContext,
            capabilities=[_FIRST_TOOL_REQUIRED_HOOKS],
            tools=[
                acknowledge_readonly,
                clarify_request,
                respond_casual,
                read_state,
                answer_policy,
                compare_entities,
                discover_options,
                explore_topic,
                _PREVIEW_INTENT_CHANGE_TOOL,
                _PREVIEW_PLAN_CHANGE_TOOL,
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
            "acknowledge_readonly": "正在确认本轮只读边界...",
            "read_state": "正在读取当前状态...",
            "answer_policy": "正在核对报考规则...",
            "compare_entities": "正在整理对比资料...",
            "discover_options": "正在查询院校和专业选项...",
            "explore_topic": "正在做只读分析...",
            "preview_intent_change": "正在整理待确认预览...",
            "preview_plan_change": "正在计算方案目标预览...",
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
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        if (
            tool_name == "preview_intent_change"
            and next_step == "respond"
            and str(data.get("reason") or "").strip() == "reference_only_semantic_requirements"
        ):
            return True
        return tool_name in _TERMINAL_RESPOND_TOOL_NAMES and next_step == "respond"

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
                    header = self._compound_result_header(tool_return, payload)
                    return f"{prefix}\n\n{header}\n\n{rendered}"
                return rendered
        return None

    @staticmethod
    def _compound_result_header(tool_return: ToolReturnPart, payload: dict[str, Any]) -> str:
        tool_name = str(getattr(tool_return, "tool_name", "") or "").strip()
        next_step = str(payload.get("next_step") or "").strip()
        if tool_name in {"preview_intent_change", "preview_plan_action"} and next_step == "confirm":
            return "下面是这次待确认预览："
        if tool_name == "review_plan":
            return "继续看审查结果："
        if tool_name == "confirm_pending":
            return "继续看处理结果："
        return "继续看结果："

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
        recent = self._find_recent_direct_tool_return(messages)
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

    def _find_recent_direct_tool_return(self, messages: list[Any]) -> str | None:
        for message in reversed(messages or []):
            parts = list(getattr(message, "parts", []) or [])
            for part in reversed(parts):
                if not isinstance(part, ToolReturnPart):
                    continue
                if str(getattr(part, "tool_name", "") or "") not in _DIRECT_TOOL_NAMES:
                    continue
                payload = self._parse_tool_payload(part)
                if not isinstance(payload, dict):
                    continue
                rendered = self._render_tool_payload(payload)
                if rendered:
                    return rendered
        return None
