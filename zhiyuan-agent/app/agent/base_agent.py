from __future__ import annotations

import logging
import contextlib
import json
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any, Generic, TypeVar

from pydantic_ai import Agent, CallToolsNode, RunContext, RunUsage, ToolCallPart
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolReturnPart, UserPromptPart
from pydantic_ai.toolsets import AbstractToolset
from pydantic_graph import End

from app.llm.client import LLMClient

try:
    from pydantic_ai_skills import SkillsToolset
except ImportError:
    SkillsToolset = None  # type: ignore[assignment,misc]

T = TypeVar("T")

logger = logging.getLogger(__name__)

# 进度回调类型：接收工具名，返回 awaitable
ProgressCallback = Callable[[str], Awaitable[None]]

DepsT = TypeVar("DepsT")

_TOOL_REPEAT_LIMITS = {
    "query_volunteer_plan": 2,
    "query_score_line": 3,
    "query_admission_score": 3,
    "search_official_admission_sources": 2,
    "get_school_introduction": 2,
    "analyze_current_interest": 2,
    "analyze_current_interest_profile": 2,
    "analyze_current_school_interest": 2,
    "analyze_current_major_interest": 2,
    "analyze_current_region_interest": 2,
    "analyze_current_career_direction": 2,
}

_READONLY_EXPLORE_REPEAT_GUARD_TOOL_NAMES = {
    "analyze_current_interest",
    "analyze_current_interest_profile",
    "analyze_current_school_interest",
    "analyze_current_major_interest",
    "analyze_current_region_interest",
    "analyze_current_career_direction",
}

_READONLY_EVIDENCE_REPEAT_GUARD_TOOL_NAMES = {
    "query_score_line",
    "query_admission_score",
    "search_official_admission_sources",
    "get_school_introduction",
}

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_THINK_OPEN_RE = re.compile(r"<think>.*", re.DOTALL | re.IGNORECASE)

_SKILL_SUMMARY_INSTRUCTION_TEMPLATE = """\
以下是系统内置的业务技能边界摘要，仅用于帮助你理解任务分工；它们不是运行时可调用工具。
真正可调用能力以当前已注册的业务工具为准。能由专用业务工具承接的问题，直接调用对应工具，不要尝试加载技能说明。

<available_skill_boundaries>
{skills_list}
</available_skill_boundaries>
"""


def _bounded_levenshtein_distance(left: str, right: str, *, max_distance: int) -> int:
    """Return edit distance up to max_distance + 1 for tight typo checks."""
    if left == right:
        return 0
    if abs(len(left) - len(right)) > max_distance:
        return max_distance + 1
    if len(left) > len(right):
        left, right = right, left

    previous = list(range(len(left) + 1))
    for right_index, right_char in enumerate(right, start=1):
        current = [right_index]
        row_min = current[0]
        for left_index, left_char in enumerate(left, start=1):
            cost = 0 if left_char == right_char else 1
            value = min(
                previous[left_index] + 1,
                current[left_index - 1] + 1,
                previous[left_index - 1] + cost,
            )
            current.append(value)
            row_min = min(row_min, value)
        if row_min > max_distance:
            return max_distance + 1
        previous = current
    return previous[-1]


class BaseAgent(Generic[T]):
    """While 循环 Agent 基类，支持 tools + skills。"""

    def __init__(
        self,
        llm_client: LLMClient,
        instructions: str,
        output_type: Any = str,
        tools: list[Any] | None = None,
        skill_dirs: list[str] | None = None,
        deps_type: type[Any] | None = None,
        expose_skill_tools: bool = False,
    ):
        self.llm_client = llm_client
        self.skills_toolset: AbstractToolset | None = None
        self._registered_tool_names = self._collect_registered_tool_names(tools or [])

        toolsets: list[AbstractToolset] = []
        if skill_dirs and SkillsToolset is not None:
            self.skills_toolset = SkillsToolset(
                directories=skill_dirs,
                instruction_template=None if expose_skill_tools else _SKILL_SUMMARY_INSTRUCTION_TEMPLATE,
            )
            if expose_skill_tools:
                toolsets.append(self.skills_toolset)

        self.agent = Agent(
            model=llm_client.model,
            output_type=output_type,
            instructions=instructions,
            tools=tools or [],
            toolsets=toolsets,
            model_settings=llm_client.model_settings,
            deps_type=deps_type,
        )

        # 注入技能列表到 system prompt。主对话可以只保留技能边界摘要，
        # 不暴露 load_skill 等技能管理工具，避免和业务工具形成重复调度。
        if self.skills_toolset is not None:
            _toolset = self.skills_toolset

            @self.agent.instructions
            async def add_skills_instructions(ctx: RunContext) -> str | None:  # noqa: ARG001
                return await _toolset.get_instructions(ctx)

    async def run(
        self,
        user_prompt: str,
        message_history: list[Any] | None = None,
        deps: Any | None = None,
    ) -> T:
        """执行 agent，手动迭代每个节点直到结束。"""
        output, _ = await self.run_with_history(user_prompt, message_history, deps)
        return output

    async def on_node(self, node: Any, agent_run: Any) -> None:
        """钩子：每个节点执行前调用，子类可覆写。"""

    async def on_complete(self, agent_run: Any) -> None:
        """钩子：运行结束后调用，子类可覆写。"""

    def get_progress_hint(self, tool_name: str) -> str | None:
        """将工具名映射为用户可见的中文提示。子类可覆写。返回 None 表示不推送。"""
        return None

    def get_progress_hint_for_tool_call(self, tool_call: ToolCallPart) -> str | None:
        """Return a progress hint for one concrete tool call.

        Subclasses can inspect structured tool arguments here. The fallback keeps
        the historical tool-name-only behavior.
        """
        return self.get_progress_hint(tool_call.tool_name)

    def should_return_directly_from_tool(
        self,
        tool_names: list[str],
        tool_returns: list[ToolReturnPart],
        deps: Any | None = None,
    ) -> bool:
        """Whether this agent can use a tool's rendered text as final output."""
        return False

    def render_direct_tool_output(
        self,
        tool_names: list[str],
        tool_returns: list[ToolReturnPart],
        deps: Any | None = None,
    ) -> str | None:
        """Render the final output for direct tool-return paths."""
        if len(tool_returns) != 1:
            return None
        content = tool_returns[0].content
        if not isinstance(content, str):
            return None
        text = content.strip()
        return text or None

    async def run_with_history(
        self,
        user_prompt: str,
        message_history: list[Any] | None = None,
        deps: Any | None = None,
    ) -> tuple[T, list[Any]]:
        """执行 agent 并返回 (output, all_messages)。"""
        output, _, all_messages, _usage = await self.run_with_message_deltas(
            user_prompt=user_prompt,
            message_history=message_history,
            deps=deps,
        )
        return output, all_messages

    async def run_with_message_deltas(
        self,
        user_prompt: str,
        message_history: list[Any] | None = None,
        deps: Any | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> tuple[T, list[Any], list[Any], RunUsage]:
        """执行 agent 并返回 (output, new_messages, all_messages, usage)。"""
        logger.info("Agent starting: prompt_len=%d history_len=%d",
                   len(user_prompt), len(message_history) if message_history else 0)

        normalized_history = self._normalize_message_history(message_history)
        run_started_at = time.monotonic()
        observability = self._init_observability(deps, user_prompt, normalized_history)

        async with self.agent.iter(
            user_prompt, message_history=normalized_history, deps=deps
        ) as agent_run:
            node = agent_run.next_node
            node_count = 0
            while not isinstance(node, End):
                node_count += 1
                node_name = type(node).__name__
                node_started_at = time.monotonic()
                logger.debug("Agent processing node #%d: %s", node_count, node_name)
                observability["currentNode"] = node_name
                observability["currentNodeIndex"] = node_count
                await self.on_node(node, agent_run)

                # 工具调用前推送进度提示
                tool_names: list[str] = []
                if isinstance(node, CallToolsNode):
                    self._normalize_tool_call_names(node.model_response.parts, observability)
                if on_progress and isinstance(node, CallToolsNode):
                    sent_hints: set[str] = set()
                    for part in node.model_response.parts:
                        if isinstance(part, ToolCallPart):
                            tool_names.append(part.tool_name)
                            hint = self.get_progress_hint_for_tool_call(part)
                            if hint and hint not in sent_hints:
                                sent_hints.add(hint)
                                try:
                                    await on_progress(hint)
                                except Exception:
                                    logger.debug("on_progress callback failed for %s", part.tool_name)
                elif isinstance(node, CallToolsNode):
                    tool_names = [
                        part.tool_name
                        for part in node.model_response.parts
                        if isinstance(part, ToolCallPart)
                    ]

                if tool_names and observability.get("firstToolCallAtMs") is None:
                    observability["firstToolCallAtMs"] = int((node_started_at - run_started_at) * 1000)
                    observability["firstToolNames"] = list(tool_names)

                repeat_guard_output = self._guard_repeated_tool_calls(tool_names, observability)
                if repeat_guard_output:
                    usage = agent_run.usage()
                    if hasattr(usage, "__await__"):
                        usage = await usage
                    partial_messages = await self._resolve_messages(agent_run.all_messages())
                    guarded_tool_name = str(observability.get("guardedToolName") or tool_names[0])
                    guarded_tool_count = int(observability.get("guardedToolCount") or 0)
                    recent_tool_output = self.render_tool_loop_guard_output_from_history(
                        guarded_tool_name,
                        guarded_tool_count,
                        partial_messages,
                    )
                    if recent_tool_output:
                        repeat_guard_output = recent_tool_output
                        observability["guardUsedRecentToolReturn"] = True
                        observability["guardRecentToolReturnLength"] = len(recent_tool_output)
                    output = repeat_guard_output
                    observability["completed"] = True
                    observability["toolLoopGuarded"] = True
                    observability["totalDurationMs"] = int((time.monotonic() - run_started_at) * 1000)
                    observability["requests"] = usage.requests
                    observability["toolCalls"] = usage.tool_calls

                    guard_response = ModelResponse(
                        parts=[TextPart(content=repeat_guard_output)],
                        model_name="tool-loop-guard",
                    )
                    all_messages = self._drop_trailing_tool_call_response(
                        list(partial_messages),
                        tool_names,
                    )
                    all_messages.append(guard_response)
                    history_len = len(normalized_history or [])
                    new_messages = list(all_messages[history_len:])
                    logger.warning(
                        "Agent stopped repeated tool loop: tool_names=%s nodes=%d output_len=%d",
                        tool_names,
                        node_count,
                        len(repeat_guard_output),
                    )
                    return output, new_messages, all_messages, usage

                try:
                    node = await agent_run.next(node)
                except BaseException as exc:
                    duration_ms = int((time.monotonic() - node_started_at) * 1000)
                    self._record_node_observability(
                        observability,
                        node_name=node_name,
                        node_index=node_count,
                        duration_ms=duration_ms,
                        tool_names=tool_names,
                        status="interrupted",
                    )
                    observability["completed"] = False
                    observability["failedNode"] = node_name
                    observability["failedNodeIndex"] = node_count
                    observability["failedNodeElapsedMs"] = duration_ms
                    self._record_exception_observability(observability, exc)
                    observability["totalDurationMs"] = int((time.monotonic() - run_started_at) * 1000)
                    raise

                direct_tool_returns = self._extract_tool_returns_from_next_node(node)
                self._record_node_observability(
                    observability,
                    node_name=node_name,
                    node_index=node_count,
                    duration_ms=int((time.monotonic() - node_started_at) * 1000),
                    tool_names=tool_names,
                    status="success",
                )
                if (
                    tool_names
                    and direct_tool_returns
                    and self.should_return_directly_from_tool(tool_names, direct_tool_returns, deps)
                ):
                    direct_output = self.render_direct_tool_output(tool_names, direct_tool_returns, deps)
                    if direct_output:
                        output = self._sanitize_model_output(direct_output)
                        usage = agent_run.usage()
                        if hasattr(usage, "__await__"):
                            usage = await usage
                        observability["completed"] = True
                        observability["directToolReturn"] = True
                        observability["totalDurationMs"] = int((time.monotonic() - run_started_at) * 1000)
                        observability["requests"] = usage.requests
                        observability["toolCalls"] = usage.tool_calls

                        partial_messages = await self._resolve_messages(agent_run.all_messages())
                        tool_request = getattr(node, "request", None)
                        direct_response = ModelResponse(
                            parts=[TextPart(content=output)],
                            model_name="direct-tool-result",
                        )
                        all_messages = list(partial_messages)
                        if isinstance(tool_request, ModelRequest):
                            all_messages.append(tool_request)
                        all_messages.append(direct_response)
                        history_len = len(normalized_history or [])
                        new_messages = list(all_messages[history_len:])
                        logger.info(
                            "Agent completed via direct tool return: nodes=%d output_len=%d messages=%d",
                            node_count,
                            len(str(output)),
                            len(all_messages),
                        )
                        return output, new_messages, all_messages, usage
            await self.on_complete(agent_run)

            output = self._sanitize_model_output(agent_run.result.output)
            usage = agent_run.usage()
            if hasattr(usage, "__await__"):
                usage = await usage
            observability["completed"] = True
            observability["totalDurationMs"] = int((time.monotonic() - run_started_at) * 1000)
            observability["requests"] = usage.requests
            observability["toolCalls"] = usage.tool_calls

            logger.info(
                "Agent usage: requests=%d input_tokens=%d output_tokens=%d "
                "total_tokens=%d tool_calls=%d",
                usage.requests, usage.input_tokens, usage.output_tokens,
                usage.total_tokens, usage.tool_calls,
            )

            all_messages = await self._resolve_messages(agent_run.all_messages())
            new_messages: list[Any] | None = None
            if hasattr(agent_run.result, "new_messages"):
                new_messages = await self._resolve_messages(agent_run.result.new_messages())
            elif hasattr(agent_run, "new_messages"):
                new_messages = await self._resolve_messages(agent_run.new_messages())

            if new_messages is None:
                new_messages = all_messages
            logger.info("Agent completed: nodes=%d output_len=%d messages=%d",
                       node_count, len(str(output)), len(all_messages))
            return output, new_messages, all_messages, usage

    @staticmethod
    def _sanitize_model_output(output: Any) -> Any:
        """Strip provider reasoning markup that must never reach users."""
        if not isinstance(output, str):
            return output
        text = output.strip()
        if not text:
            return text
        text = _THINK_BLOCK_RE.sub("", text)
        if "</think>" in text.lower():
            marker_index = text.lower().rfind("</think>")
            text = text[marker_index + len("</think>") :]
        text = _THINK_OPEN_RE.sub("", text)
        return text.strip()

    def _extract_tool_returns_from_next_node(self, node: Any) -> list[ToolReturnPart]:
        request = getattr(node, "request", None)
        if not isinstance(request, ModelRequest):
            return []
        return [part for part in request.parts if isinstance(part, ToolReturnPart)]

    def _init_observability(
        self,
        deps: Any | None,
        user_prompt: str,
        normalized_history: list[Any] | None,
    ) -> dict[str, Any]:
        observability: dict[str, Any]
        if deps is not None and isinstance(getattr(deps, "agent_observability", None), dict):
            observability = getattr(deps, "agent_observability")
            observability.clear()
        else:
            observability = {}
            if deps is not None:
                with contextlib.suppress(Exception):
                    setattr(deps, "agent_observability", observability)
        observability.update(
            {
                "promptLength": len(user_prompt or ""),
                "historyLength": len(normalized_history or []),
                "nodeTimings": [],
                "firstToolCallAtMs": None,
                "completed": False,
            }
        )
        return observability

    def _record_node_observability(
        self,
        observability: dict[str, Any],
        *,
        node_name: str,
        node_index: int,
        duration_ms: int,
        tool_names: list[str],
        status: str,
    ) -> None:
        item: dict[str, Any] = {
            "index": node_index,
            "node": node_name,
            "durationMs": duration_ms,
            "status": status,
        }
        if tool_names:
            item["toolNames"] = list(tool_names)
        observability.setdefault("nodeTimings", []).append(item)

    def _record_exception_observability(
        self,
        observability: dict[str, Any],
        exc: BaseException,
    ) -> None:
        observability["errorType"] = type(exc).__name__
        for attr_name, target_key in (
            ("status_code", "errorStatusCode"),
            ("code", "errorCode"),
            ("type", "errorProviderType"),
        ):
            value = getattr(exc, attr_name, None)
            if value is not None:
                observability[target_key] = str(value)
        response = getattr(exc, "response", None)
        response_status = getattr(response, "status_code", None)
        if response_status is not None:
            observability["errorStatusCode"] = str(response_status)
        response_text = getattr(response, "text", None)
        if response_text:
            observability["errorResponseText"] = self._compact_error_text(str(response_text))
        body = getattr(exc, "body", None)
        if body is not None:
            observability["errorBody"] = self._compact_error_text(str(body))
        message = str(exc).strip()
        if message:
            observability["errorMessage"] = self._compact_error_text(message)

    @staticmethod
    def _compact_error_text(text: str, *, limit: int = 500) -> str:
        compact = " ".join(str(text or "").split())
        if len(compact) <= limit:
            return compact
        return compact[: limit - 3] + "..."

    def _guard_repeated_tool_calls(self, tool_names: list[str], observability: dict[str, Any]) -> str | None:
        if not tool_names:
            return None
        counts = observability.setdefault("toolNameCounts", {})
        if not isinstance(counts, dict):
            counts = {}
            observability["toolNameCounts"] = counts
        for tool_name in tool_names:
            if not tool_name:
                continue
            current_count = int(counts.get(tool_name) or 0) + 1
            counts[tool_name] = current_count
            limit = _TOOL_REPEAT_LIMITS.get(tool_name)
            if limit is not None and current_count > limit:
                observability["toolLoopGuarded"] = True
                observability["guardedToolName"] = tool_name
                observability["guardedToolCount"] = current_count
                return self.render_tool_loop_guard_output(tool_name, current_count)
        return None

    @staticmethod
    def _collect_registered_tool_names(tools: list[Any]) -> set[str]:
        names: set[str] = set()
        for tool in tools:
            name = getattr(tool, "__name__", None) or getattr(tool, "name", None)
            if not name:
                function = getattr(tool, "function", None)
                name = getattr(function, "__name__", None) or getattr(function, "name", None)
            if name:
                names.add(str(name))
        return names

    def _normalize_tool_call_names(self, parts: list[Any], observability: dict[str, Any]) -> None:
        """Correct obvious model-side typos in tool names before execution.

        This is not user-language routing. It only applies when the model emits
        an invalid function name that is within a tiny edit distance of exactly
        one registered tool in the same leading family.
        """
        if not self._registered_tool_names:
            return

        normalized: list[dict[str, str]] = []
        for part in parts:
            if not isinstance(part, ToolCallPart):
                continue
            raw_name = str(part.tool_name or "").strip()
            corrected_name = self._resolve_near_registered_tool_name(raw_name)
            if not corrected_name:
                continue
            part.tool_name = corrected_name
            normalized.append({"from": raw_name, "to": corrected_name})
            logger.warning("Corrected model tool name typo: %s -> %s", raw_name, corrected_name)

        if normalized:
            existing = observability.setdefault("normalizedToolNames", [])
            if isinstance(existing, list):
                existing.extend(normalized)

    def _resolve_near_registered_tool_name(self, raw_name: str) -> str | None:
        if not raw_name or raw_name in self._registered_tool_names:
            return None
        raw_family = raw_name.split("_", 1)[0]
        if not raw_family:
            return None
        matches = [
            candidate
            for candidate in self._registered_tool_names
            if candidate.split("_", 1)[0] == raw_family
            and abs(len(candidate) - len(raw_name)) <= 2
            and _bounded_levenshtein_distance(raw_name, candidate, max_distance=2) <= 2
        ]
        if len(matches) != 1:
            return None
        return matches[0]

    def render_tool_loop_guard_output(self, tool_name: str, count: int) -> str:
        if tool_name == "query_volunteer_plan":
            return (
                "我已经查过当前方案和候选里的相关机会，但这轮没有得到可直接引用的稳定结果，先不继续重复查询。"
                "这轮不会改动方案；你可以换一个更具体的条件，比如学校全称、专业、城市、冲稳保层级，或者让我基于当前候选先做整体梳理。"
            )
        if tool_name == "query_score_line":
            return (
                "这轮已经查过多组录取分数线，但没有得到可直接引用的稳定结果，我先停止继续逐条查分。"
                "这轮不会改动方案，也不会写入偏好；你可以指定一两所学校继续查，或让我先按已查到的信息做概括判断。"
            )
        if tool_name == "search_official_admission_sources":
            return (
                "这轮已经检索过官方来源，但没有得到可直接引用的稳定结果，我先停止重复检索。"
                "这轮不会改动方案，也不会写入偏好；你可以指定学校、省份或政策条款继续核验。"
            )
        if tool_name == "query_admission_score":
            return (
                "这轮已经查过多组录取机会，但没有得到可直接引用的稳定结果，我先停止继续逐条查。"
                "这轮不会改动方案，也不会写入偏好；你可以指定学校或专业继续查，或让我先按已查到的信息做概括判断。"
            )
        if tool_name == "get_school_introduction":
            return (
                "这轮已经查过院校基础信息，但没有得到可直接引用的稳定结果，我先停止重复查询。"
                "这轮不会改动方案，也不会写入偏好；你可以指定一所学校继续深挖。"
            )
        if tool_name in _READONLY_EXPLORE_REPEAT_GUARD_TOOL_NAMES:
            return (
                "这轮只读分析已经完成过一次，但没有得到更稳定的新结论，我先停止重复分析。"
                "这轮不会改动方案，也不会写入偏好；你可以换一个更具体的问题继续。"
            )
        return "这轮工具调用没有得到可直接引用的稳定结果，我先停止重复查询。你可以换一个更具体的问题继续。"

    def render_tool_loop_guard_output_from_history(
        self,
        tool_name: str,
        count: int,
        messages: list[Any],
    ) -> str | None:
        if (
            tool_name != "query_volunteer_plan"
            and tool_name not in _READONLY_EXPLORE_REPEAT_GUARD_TOOL_NAMES
            and tool_name not in _READONLY_EVIDENCE_REPEAT_GUARD_TOOL_NAMES
        ):
            return None
        recent_output = self._find_recent_tool_return_content(tool_name, messages)
        if not recent_output:
            return None
        if tool_name in _READONLY_EXPLORE_REPEAT_GUARD_TOOL_NAMES:
            return (
                "我已经完成一次只读分析，先按最近一次分析结果回答；这轮不会改动方案，也不会写入偏好。\n\n"
                f"{recent_output}"
            )
        if tool_name in _READONLY_EVIDENCE_REPEAT_GUARD_TOOL_NAMES:
            return (
                "我已经拿到一轮只读取证结果，先按最近一次结果回答；这轮不会改动方案，也不会写入偏好。\n\n"
                f"{recent_output}"
            )
        return (
            "我已经查到当前方案里的相关信息，先按最近一次查询结果回答；这轮不会改动方案。\n\n"
            f"{recent_output}"
        )

    def _find_recent_tool_return_content(self, tool_name: str, messages: list[Any]) -> str | None:
        for message in reversed(messages or []):
            parts = list(getattr(message, "parts", []) or [])
            for part in reversed(parts):
                if not isinstance(part, ToolReturnPart):
                    continue
                if str(getattr(part, "tool_name", "") or "") != tool_name:
                    continue
                content = part.content
                if not isinstance(content, str):
                    continue
                text = content.strip()
                if self._is_usable_tool_loop_guard_content(tool_name, text):
                    return self._tool_return_user_text(tool_name, text)
        return None

    @staticmethod
    def _is_usable_tool_loop_guard_content(tool_name: str, text: str) -> bool:
        if not text:
            return False
        failure_markers = (
            "查询失败",
            "查询出错",
            "暂时无法查询",
            "接口返回异常",
            "系统繁忙",
            "分析失败",
            "暂时无法分析",
        )
        return not any(marker in text for marker in failure_markers)

    @staticmethod
    def _tool_return_user_text(tool_name: str, text: str) -> str:
        if tool_name == "search_official_admission_sources":
            return BaseAgent._official_source_search_user_text(text)
        if tool_name not in _READONLY_EXPLORE_REPEAT_GUARD_TOOL_NAMES:
            return text
        stripped = text.strip()
        if not (stripped.startswith("{") and stripped.endswith("}")):
            return stripped
        with contextlib.suppress(Exception):
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                for key in ("message", "summary", "reply", "state_summary"):
                    value = str(parsed.get(key) or "").strip()
                    if value:
                        return value
        return stripped

    @staticmethod
    def _official_source_search_user_text(text: str) -> str:
        stripped = text.strip()
        if not (stripped.startswith("{") and stripped.endswith("}")):
            return stripped
        with contextlib.suppress(Exception):
            parsed = json.loads(stripped)
            if isinstance(parsed, dict) and parsed.get("result_kind") == "official_source_search":
                return BaseAgent._render_official_source_search_summary(parsed)
        return stripped

    @staticmethod
    def _render_official_source_search_summary(payload: dict[str, Any]) -> str:
        summary = str(payload.get("summary") or "").strip()
        status = str(payload.get("status") or "").strip()
        query = str(payload.get("query") or "").strip()
        results = payload.get("results")
        if not isinstance(results, list):
            results = []

        lines: list[str] = []
        if summary:
            lines.append(summary)
        elif status:
            lines.append("已完成一轮官方来源检索。")
        if query:
            lines.append(f"检索词：{query}")

        rendered_results: list[str] = []
        for index, raw_item in enumerate(results[:5], start=1):
            if not isinstance(raw_item, dict):
                continue
            title = str(raw_item.get("title") or "").strip()
            site_name = str(raw_item.get("site_name") or "").strip()
            url = str(raw_item.get("url") or "").strip()
            detail = str(raw_item.get("summary") or raw_item.get("snippet") or "").strip()
            heading_parts = [part for part in (title, site_name) if part]
            heading = " / ".join(heading_parts) or url
            if not heading:
                continue
            line = f"{index}. {heading}"
            if url:
                line += f"\n   {url}"
            if detail:
                line += f"\n   要点：{BaseAgent._compact_error_text(detail, limit=180)}"
            rendered_results.append(line)

        if rendered_results:
            lines.append("可参考的官方来源：")
            lines.extend(rendered_results)
        elif status and status != "ok":
            lines.append("这轮没有可直接引用的官方来源，不能据此下最终结论。")

        return "\n".join(lines).strip() or "已完成一轮官方来源检索；这轮不会改动方案，也不会写入偏好。"

    def _drop_trailing_tool_call_response(self, messages: list[Any], tool_names: list[str]) -> list[Any]:
        if not messages:
            return messages
        last = messages[-1]
        if not isinstance(last, ModelResponse):
            return messages
        parts = list(getattr(last, "parts", []) or [])
        if not parts or not all(isinstance(part, ToolCallPart) for part in parts):
            return messages
        current_tool_names = {name for name in tool_names if name}
        response_tool_names = {part.tool_name for part in parts if isinstance(part, ToolCallPart)}
        if current_tool_names and response_tool_names and response_tool_names <= current_tool_names:
            return messages[:-1]
        return messages

    async def _resolve_messages(self, messages_result: Any) -> list[Any]:
        """Resolve a pydantic-ai message accessor that may return awaitables."""
        if hasattr(messages_result, "__await__"):
            return await messages_result
        return messages_result

    def _normalize_message_history(self, message_history: list[Any] | None) -> list[Any] | None:
        """Accept legacy {role, content} history and pass ModelMessage objects to pydantic-ai."""
        if not message_history:
            return message_history

        normalized: list[Any] = []
        changed = False
        for message in message_history:
            if not isinstance(message, dict):
                normalized.append(message)
                continue

            role = str(message.get("role") or "").strip().lower()
            content = message.get("content")
            if not isinstance(content, str):
                normalized.append(message)
                continue

            changed = True
            if role == "assistant":
                normalized.append(ModelResponse(parts=[TextPart(content=content)]))
            else:
                normalized.append(ModelRequest(parts=[UserPromptPart(content=content)]))

        return normalized if changed else message_history
