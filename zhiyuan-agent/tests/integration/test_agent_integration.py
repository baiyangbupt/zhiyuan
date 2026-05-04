"""集成测试 — 5 个用例。"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_graph import End

from app.config import LLMConfig
from app.llm.client import LLMClient
from app.agent.base_agent import BaseAgent


# ---- helpers (同 test_base_agent) ----

def _make_agent_run(nodes: list, final_output: Any = "test output"):
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
    agent_run.usage = MagicMock(return_value="mock_usage")

    ctx_mgr = AsyncMock()
    ctx_mgr.__aenter__ = AsyncMock(return_value=agent_run)
    ctx_mgr.__aexit__ = AsyncMock(return_value=False)
    return ctx_mgr, agent_run


# ---- 1. Config → Client → Agent 完整链路 ----

def test_config_to_client_to_agent(mocker):
    mocker.patch("app.llm.client.OpenAIChatModel", return_value=MagicMock())
    mocker.patch("app.llm.client.OpenAIProvider", return_value=MagicMock())
    mocker.patch("app.agent.base_agent.Agent")

    config = LLMConfig(provider="openai", model_name="gpt-4o", api_key="sk-test")
    client = LLMClient(config)
    agent = BaseAgent(llm_client=client, instructions="你是志愿填报助手")

    assert agent.llm_client is client
    assert agent.llm_client.config is config


# ---- 2. DemoAgent 子类 ----

def test_demo_agent_subclass(mocker):
    mocker.patch("app.llm.client.OpenAIChatModel", return_value=MagicMock())
    mocker.patch("app.llm.client.OpenAIProvider", return_value=MagicMock())
    mocker.patch("app.agent.base_agent.Agent")

    log: list[str] = []

    class DemoAgent(BaseAgent[str]):
        async def on_node(self, node: Any, agent_run: Any) -> None:
            log.append(f"node:{type(node).__name__}")

        async def on_complete(self, agent_run: Any) -> None:
            log.append("complete")

    config = LLMConfig(provider="openai", api_key="sk-test")
    client = LLMClient(config)
    agent = DemoAgent(llm_client=client, instructions="test")

    assert isinstance(agent, BaseAgent)


# ---- 3. 完整 run 流程 ----

async def test_full_run_flow(mocker):
    mocker.patch("app.llm.client.OpenAIChatModel", return_value=MagicMock())
    mocker.patch("app.llm.client.OpenAIProvider", return_value=MagicMock())
    mocker.patch("app.agent.base_agent.Agent")

    config = LLMConfig(provider="openai", api_key="sk-test")
    client = LLMClient(config)
    agent = BaseAgent(llm_client=client, instructions="test")

    node1 = MagicMock()
    ctx_mgr, _ = _make_agent_run([node1], final_output="北京大学推荐")
    agent.agent.iter = MagicMock(return_value=ctx_mgr)

    result = await agent.run("推荐一个大学")
    assert result == "北京大学推荐"


# ---- 4. 多轮对话 ----

async def test_multi_turn_conversation(mocker):
    mocker.patch("app.llm.client.OpenAIChatModel", return_value=MagicMock())
    mocker.patch("app.llm.client.OpenAIProvider", return_value=MagicMock())
    mocker.patch("app.agent.base_agent.Agent")

    config = LLMConfig(provider="openai", api_key="sk-test")
    client = LLMClient(config)
    agent = BaseAgent(llm_client=client, instructions="test")

    history = [{"role": "user", "content": "我考了650分"}]
    ctx_mgr, _ = _make_agent_run([], final_output="推荐清华")
    agent.agent.iter = MagicMock(return_value=ctx_mgr)

    result = await agent.run("推荐大学", message_history=history)
    assert result == "推荐清华"
    agent.agent.iter.assert_called_once_with("推荐大学", message_history=history, deps=None)


# ---- 5. 多 provider 切换 ----

def test_provider_switch(mocker):
    mocker.patch("app.llm.client.OpenAIChatModel", return_value=MagicMock(name="openai_model"))
    mocker.patch("app.llm.client.OpenAIProvider", return_value=MagicMock())
    mocker.patch("app.llm.client.AnthropicModel", return_value=MagicMock(name="anthropic_model"))
    mocker.patch("app.llm.client.AnthropicProvider", return_value=MagicMock())

    config_openai = LLMConfig(provider="openai", api_key="sk-test")
    client_openai = LLMClient(config_openai)

    config_anthropic = LLMConfig(provider="anthropic", api_key="sk-ant")
    client_anthropic = LLMClient(config_anthropic)

    assert client_openai.model is not client_anthropic.model
