"""BaseAgent 单元测试 — 12 个用例。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import CallToolsNode, RunUsage
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_graph import End

from app.agent.base_agent import BaseAgent


# ---- helpers ----

def _make_mock_client() -> MagicMock:
    client = MagicMock()
    client.model = MagicMock()
    client.model_settings = MagicMock()
    return client


def _make_agent_run(nodes: list, final_output: Any = "test output"):
    """构造模拟的 agent.iter() 异步上下文管理器。"""
    end_node = End(data=None)
    all_nodes = list(nodes) + [end_node]

    agent_run = AsyncMock()
    agent_run.next_node = all_nodes[0]

    call_idx = 0

    async def _next(current):  # noqa: ARG001
        nonlocal call_idx
        call_idx += 1
        return all_nodes[call_idx]

    agent_run.next = _next
    agent_run.result = MagicMock()
    agent_run.result.output = final_output
    agent_run.usage = MagicMock(return_value=RunUsage())
    agent_run.all_messages = MagicMock(return_value=[])

    ctx_mgr = AsyncMock()
    ctx_mgr.__aenter__ = AsyncMock(return_value=agent_run)
    ctx_mgr.__aexit__ = AsyncMock(return_value=False)
    return ctx_mgr, agent_run


@pytest.fixture
def client():
    return _make_mock_client()


# ---- 1. 无 tools/skills 构造 ----

def test_init_no_tools_no_skills(client, mocker):
    mock_agent = mocker.patch("app.agent.base_agent.Agent")
    agent = BaseAgent(llm_client=client, instructions="test", output_type=str)

    assert agent.skills_toolset is None
    mock_agent.assert_called_once()
    call_kwargs = mock_agent.call_args[1]
    assert call_kwargs["tools"] == []
    assert call_kwargs["toolsets"] == []


# ---- 2. tools 传入 ----

def test_init_with_tools(client, mocker):
    mocker.patch("app.agent.base_agent.Agent")
    tool1 = MagicMock()
    agent = BaseAgent(
        llm_client=client, instructions="test", tools=[tool1]
    )
    assert agent.skills_toolset is None


# ---- 3. skill_dirs 传入 ----

def test_init_with_skill_dirs(client, mocker):
    mock_toolset = MagicMock()
    mock_skills_toolset = mocker.patch("app.agent.base_agent.SkillsToolset", return_value=mock_toolset)
    mock_agent = mocker.patch("app.agent.base_agent.Agent")

    agent = BaseAgent(
        llm_client=client, instructions="test", skill_dirs=["./skills"]
    )
    assert agent.skills_toolset is mock_toolset
    assert mock_agent.call_args.kwargs["toolsets"] == []
    instruction_template = mock_skills_toolset.call_args.kwargs["instruction_template"]
    assert "运行时可调用工具" in instruction_template
    assert "load_skill" not in instruction_template


def test_init_with_skill_dirs_can_hide_skill_tools(client, mocker):
    mock_toolset = MagicMock()
    mocker.patch("app.agent.base_agent.SkillsToolset", return_value=mock_toolset)
    mock_agent = mocker.patch("app.agent.base_agent.Agent")

    agent = BaseAgent(
        llm_client=client,
        instructions="test",
        skill_dirs=["./skills"],
        expose_skill_tools=False,
    )

    assert agent.skills_toolset is mock_toolset
    assert mock_agent.call_args.kwargs["toolsets"] == []


def test_init_with_skill_dirs_can_expose_skill_tools(client, mocker):
    mock_toolset = MagicMock()
    mock_skills_toolset = mocker.patch("app.agent.base_agent.SkillsToolset", return_value=mock_toolset)
    mock_agent = mocker.patch("app.agent.base_agent.Agent")

    agent = BaseAgent(
        llm_client=client,
        instructions="test",
        skill_dirs=["./skills"],
        expose_skill_tools=True,
    )

    assert agent.skills_toolset is mock_toolset
    assert mock_agent.call_args.kwargs["toolsets"] == [mock_toolset]
    assert mock_skills_toolset.call_args.kwargs["instruction_template"] is None


# ---- 4. SkillsToolset 不可用 ----

def test_init_skills_toolset_unavailable(client, mocker):
    mocker.patch("app.agent.base_agent.SkillsToolset", None)
    mocker.patch("app.agent.base_agent.Agent")

    agent = BaseAgent(
        llm_client=client, instructions="test", skill_dirs=["./skills"]
    )
    assert agent.skills_toolset is None


# ---- 5. run 单节点 ----

async def test_run_single_node(client, mocker):
    mocker.patch("app.agent.base_agent.Agent")
    agent = BaseAgent(llm_client=client, instructions="test")

    node1 = MagicMock()
    ctx_mgr, _ = _make_agent_run([node1], final_output="hello")
    agent.agent.iter = MagicMock(return_value=ctx_mgr)

    result = await agent.run("hi")
    assert result == "hello"


# ---- 6. run 多节点 ----

async def test_run_multi_nodes(client, mocker):
    mocker.patch("app.agent.base_agent.Agent")
    agent = BaseAgent(llm_client=client, instructions="test")

    nodes = [MagicMock(), MagicMock(), MagicMock()]
    ctx_mgr, _ = _make_agent_run(nodes, final_output="done")
    agent.agent.iter = MagicMock(return_value=ctx_mgr)

    on_node_spy = mocker.patch.object(agent, "on_node", new_callable=AsyncMock)
    result = await agent.run("hi")

    assert result == "done"
    assert on_node_spy.call_count == 3


async def test_run_records_agent_node_observability(client, mocker):
    mocker.patch("app.agent.base_agent.Agent")
    agent = BaseAgent(llm_client=client, instructions="test")

    nodes = [MagicMock(), MagicMock()]
    ctx_mgr, _ = _make_agent_run(nodes, final_output="done")
    agent.agent.iter = MagicMock(return_value=ctx_mgr)
    deps = SimpleNamespace(agent_observability={})

    await agent.run("hi", deps=deps)

    observability = deps.agent_observability
    assert observability["completed"] is True
    assert observability["promptLength"] == 2
    assert observability["historyLength"] == 0
    assert observability["requests"] == 0
    assert observability["toolCalls"] == 0
    assert len(observability["nodeTimings"]) == 2
    assert observability["nodeTimings"][0]["status"] == "success"
    assert "durationMs" in observability["nodeTimings"][0]


async def test_run_deduplicates_identical_progress_hints_in_same_tool_node(client, mocker):
    mocker.patch("app.agent.base_agent.Agent")

    class HintAgent(BaseAgent[str]):
        def get_progress_hint(self, tool_name: str) -> str | None:
            return "正在查这个专业的学习内容和就业情况..." if tool_name == "get_major_introduction" else None

    agent = HintAgent(llm_client=client, instructions="test")
    node = CallToolsNode(
        model_response=ModelResponse(
            parts=[
                ToolCallPart(tool_name="get_major_introduction", args={"major_name": "建筑学"}, tool_call_id="call-1"),
                ToolCallPart(tool_name="get_major_introduction", args={"major_name": "城乡规划"}, tool_call_id="call-2"),
            ]
        )
    )
    ctx_mgr, _ = _make_agent_run([node], final_output="done")
    agent.agent.iter = MagicMock(return_value=ctx_mgr)
    progress: list[str] = []

    async def on_progress(message: str) -> None:
        progress.append(message)

    await agent.run_with_message_deltas("建筑城乡规划要不要美术基础", on_progress=on_progress)

    assert progress == ["正在查这个专业的学习内容和就业情况..."]


async def test_run_can_return_directly_after_user_facing_tool_result():
    async def direct_preview_tool() -> str:
        return "我先整理成待确认内容，确认前不会生效。"

    class DirectPreviewAgent(BaseAgent[str]):
        def should_return_directly_from_tool(self, tool_names, tool_returns, deps=None) -> bool:
            return tool_names == ["direct_preview_tool"]

    client = SimpleNamespace(model=TestModel(call_tools=["direct_preview_tool"]), model_settings={})
    agent = DirectPreviewAgent(llm_client=client, instructions="test", tools=[direct_preview_tool])

    reply, new_messages, all_messages, usage = await agent.run_with_message_deltas("先看看影响")

    assert reply == "我先整理成待确认内容，确认前不会生效。"
    assert usage.requests == 1
    assert usage.tool_calls == 1
    assert any(
        isinstance(part, ToolReturnPart) and part.content == "我先整理成待确认内容，确认前不会生效。"
        for message in new_messages
        for part in getattr(message, "parts", [])
    )
    assert isinstance(all_messages[-1], ModelResponse)
    assert getattr(all_messages[-1], "model_name", "") == "direct-tool-result"
    assert isinstance(all_messages[-1].parts[0], TextPart)
    assert all_messages[-1].parts[0].content == reply


def test_sanitize_model_output_strips_provider_reasoning_markup():
    assert (
        BaseAgent._sanitize_model_output("用户问的是专项政策，我已经调用工具。</think>\n可以先按三步判断专项资格。")
        == "可以先按三步判断专项资格。"
    )
    assert BaseAgent._sanitize_model_output("<think>内部推理</think>\n这是给用户看的回答。") == "这是给用户看的回答。"
    assert BaseAgent._sanitize_model_output("<think>内部推理未闭合") == ""


async def test_run_stops_repeated_query_tool_loop_generically():
    async def query_volunteer_plan() -> str:
        return "当前方案里命中了 1 条相关机会。"

    async def looping_model(messages, agent_info):  # noqa: ARG001
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="query_volunteer_plan",
                    args={},
                    tool_call_id=f"query-call-{len(messages)}",
                )
            ]
        )

    class QueryLoopGuardAgent(BaseAgent[str]):
        def __init__(self):
            super().__init__(
                llm_client=SimpleNamespace(model=FunctionModel(looping_model), model_settings={}),
                instructions="test",
                tools=[query_volunteer_plan],
            )

    deps = SimpleNamespace(agent_observability={})
    agent = QueryLoopGuardAgent()

    reply, new_messages, all_messages, usage = await agent.run_with_message_deltas("候选里还有没有更稳一点的会计审计", deps=deps)

    assert "没有稳定收敛" in reply
    assert deps.agent_observability["toolLoopGuarded"] is True
    assert deps.agent_observability["guardedToolName"] == "query_volunteer_plan"
    assert usage.tool_calls == 2
    assert isinstance(all_messages[-1], ModelResponse)
    assert getattr(all_messages[-1], "model_name", "") == "tool-loop-guard"
    assert new_messages[-1].parts[0].content == reply


def test_record_exception_observability_keeps_provider_error_details(client, mocker):
    mocker.patch("app.agent.base_agent.Agent")
    agent = BaseAgent(llm_client=client, instructions="test")
    response = SimpleNamespace(status_code=429, text='{"error":"rate limited"}')
    exc = RuntimeError("provider error")
    exc.status_code = 503
    exc.code = "server_busy"
    exc.body = {"message": "System is too busy now"}
    exc.response = response
    observability: dict[str, Any] = {}

    agent._record_exception_observability(observability, exc)

    assert observability["errorType"] == "RuntimeError"
    assert observability["errorStatusCode"] == "429"
    assert observability["errorCode"] == "server_busy"
    assert observability["errorResponseText"] == '{"error":"rate limited"}'
    assert "System is too busy now" in observability["errorBody"]
    assert observability["errorMessage"] == "provider error"


# ---- 7. on_node 钩子默认不报错 ----

async def test_on_node_hook_default(client, mocker):
    mocker.patch("app.agent.base_agent.Agent")
    agent = BaseAgent(llm_client=client, instructions="test")
    await agent.on_node(MagicMock(), MagicMock())  # 不抛异常


# ---- 8. on_complete 钩子默认不报错 ----

async def test_on_complete_hook_default(client, mocker):
    mocker.patch("app.agent.base_agent.Agent")
    agent = BaseAgent(llm_client=client, instructions="test")
    await agent.on_complete(MagicMock())  # 不抛异常


# ---- 9. 子类覆写钩子 ----

async def test_subclass_override_hooks(client, mocker):
    mocker.patch("app.agent.base_agent.Agent")

    log: list[tuple] = []

    class TestAgent(BaseAgent[str]):
        async def on_node(self, node: Any, agent_run: Any) -> None:
            log.append(("node", node))

        async def on_complete(self, agent_run: Any) -> None:
            log.append(("complete",))

    agent = TestAgent(llm_client=client, instructions="test")
    node1 = MagicMock()
    ctx_mgr, _ = _make_agent_run([node1])
    agent.agent.iter = MagicMock(return_value=ctx_mgr)

    await agent.run("hi")
    assert len(log) == 2
    assert log[0][0] == "node"
    assert log[1][0] == "complete"


# ---- 10. message_history 传递 ----

async def test_message_history_passed(client, mocker):
    mocker.patch("app.agent.base_agent.Agent")
    agent = BaseAgent(llm_client=client, instructions="test")

    history = [{"role": "user", "content": "之前的对话"}]
    ctx_mgr, _ = _make_agent_run([], final_output="ok")
    agent.agent.iter = MagicMock(return_value=ctx_mgr)

    await agent.run("继续", message_history=history)
    passed_history = agent.agent.iter.call_args.kwargs["message_history"]
    assert len(passed_history) == 1
    assert passed_history[0].parts[0].content == "之前的对话"


# ---- 11. output_type 传递 ----

def test_output_type_passed(client, mocker):
    mock_agent = mocker.patch("app.agent.base_agent.Agent")
    BaseAgent(llm_client=client, instructions="test", output_type=dict)

    call_kwargs = mock_agent.call_args[1]
    assert call_kwargs["output_type"] is dict


# ---- 12. skills instructions 注入 ----

def test_skills_instructions_injected(client, mocker):
    mock_toolset = MagicMock()
    mocker.patch("app.agent.base_agent.SkillsToolset", return_value=mock_toolset)
    mock_agent_cls = mocker.patch("app.agent.base_agent.Agent")
    mock_agent_instance = mock_agent_cls.return_value

    BaseAgent(llm_client=client, instructions="test", skill_dirs=["./skills"])

    # @agent.instructions 装饰器应该被调用
    mock_agent_instance.instructions.assert_called_once()
