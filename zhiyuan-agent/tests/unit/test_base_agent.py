"""BaseAgent 单元测试 — 12 个用例。"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import RunUsage
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
    call_kwargs = mock_agent.call_args[1]
    assert call_kwargs["toolsets"] == []
    assert "运行时可调用工具" in mock_skills_toolset.call_args.kwargs["instruction_template"]


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
    call_kwargs = mock_agent.call_args[1]
    assert call_kwargs["toolsets"] == [mock_toolset]
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
