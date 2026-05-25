from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Generic, TypeVar

from pydantic_ai import Agent, CallToolsNode, RunContext, RunUsage, ToolCallPart
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
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

_SKILL_SUMMARY_INSTRUCTION_TEMPLATE = """\
以下是系统内置的业务技能边界摘要，仅用于帮助你理解任务分工；它们不是运行时可调用工具。
真正可调用能力以当前已注册的业务工具为准。能由专用业务工具承接的问题，直接调用对应工具，不要尝试加载技能说明。

<available_skill_boundaries>
{skills_list}
</available_skill_boundaries>
"""


class BaseAgent(Generic[T]):
    """While 循环 Agent 基类，支持 tools + skills。"""

    def __init__(
        self,
        llm_client: LLMClient,
        instructions: str,
        output_type: Any = str,
        tools: list[Any] | None = None,
        skill_dirs: list[str] | None = None,
        expose_skill_tools: bool = False,
        deps_type: type[Any] | None = None,
    ):
        self.llm_client = llm_client
        self.skills_toolset: AbstractToolset | None = None

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

        # 注入技能列表到 system prompt
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

        async with self.agent.iter(
            user_prompt, message_history=normalized_history, deps=deps
        ) as agent_run:
            node = agent_run.next_node
            node_count = 0
            while not isinstance(node, End):
                node_count += 1
                logger.debug("Agent processing node #%d: %s", node_count, type(node).__name__)
                await self.on_node(node, agent_run)

                # 工具调用前推送进度提示
                if on_progress and isinstance(node, CallToolsNode):
                    for part in node.model_response.parts:
                        if isinstance(part, ToolCallPart):
                            hint = self.get_progress_hint(part.tool_name)
                            if hint:
                                try:
                                    await on_progress(hint)
                                except Exception:
                                    logger.debug("on_progress callback failed for %s", part.tool_name)

                node = await agent_run.next(node)
            await self.on_complete(agent_run)

            output = agent_run.result.output
            usage = agent_run.usage()
            if hasattr(usage, "__await__"):
                usage = await usage

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
