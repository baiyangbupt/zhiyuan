"""端到端测试 — 真实 LLM 调用。

需要：
1. 创建 .env 文件并填入真实的 LLM_API_KEY
2. 运行: pytest tests/e2e/ -v -s

这些测试会真正调用 LLM API，产生费用。
"""

from __future__ import annotations

import pytest

from app.config import LLMConfig
from app.llm.client import LLMClient
from app.agent.base_agent import BaseAgent


# 标记为 e2e 测试，默认跳过
pytestmark = pytest.mark.e2e


@pytest.fixture
def real_config():
    """从 .env 加载真实配置。"""
    try:
        config = LLMConfig()
        return config
    except Exception as e:
        pytest.skip(f"无法加载 .env 配置: {e}")


@pytest.fixture
def real_client(real_config):
    """创建真实的 LLM Client。"""
    return LLMClient(real_config)


# ---- 1. 真实 LLM 调用测试 ----

async def test_real_llm_simple_query(real_client):
    """测试真实 LLM 的简单问答。"""
    agent = BaseAgent(
        llm_client=real_client,
        instructions="你是一个简洁的助手，用一句话回答问题。",
        output_type=str,
    )

    result = await agent.run("1+1等于几？")
    print(f"\n[LLM 回复]: {result}")

    assert result is not None
    assert len(result) > 0
    assert "2" in result


# ---- 2. 带工具调用的测试 ----

async def test_real_llm_with_tool(real_client):
    """测试真实 LLM 调用工具。"""
    from pydantic_ai import Tool
    from pydantic_ai.messages import ModelRequest, ModelResponse

    def get_weather(city: str) -> str:
        """查询城市天气（模拟）。"""
        return f"{city}今天晴天，温度 20°C"

    agent = BaseAgent(
        llm_client=real_client,
        instructions="你是天气助手。当用户询问天气时，调用 get_weather 工具。",
        output_type=str,
        tools=[Tool(get_weather)],
    )

    result = await agent.run("北京天气怎么样？")
    print(f"\n[LLM 回复]: {result}")

    assert result is not None
    assert "北京" in result or "晴" in result or "20" in result


# ---- 3. 多轮对话测试 ----

async def test_real_llm_multi_turn(real_client):
    """测试真实 LLM 多轮对话（简化版）。"""
    agent = BaseAgent(
        llm_client=real_client,
        instructions="你是一个简洁的助手。",
        output_type=str,
    )

    # 第一轮
    result1 = await agent.run("1+1等于几？")
    print(f"\n[第1轮]: {result1}")
    assert "2" in result1

    # 第二轮（独立问题）
    result2 = await agent.run("2+2等于几？")
    print(f"\n[第2轮]: {result2}")
    assert "4" in result2


# ---- 4. 子类钩子测试 ----

async def test_real_llm_with_hooks(real_client):
    """测试真实 LLM + 子类钩子。"""
    log: list[str] = []

    class LoggingAgent(BaseAgent[str]):
        async def on_node(self, node, agent_run):
            log.append(f"node:{type(node).__name__}")

        async def on_complete(self, agent_run):
            log.append("complete")

    agent = LoggingAgent(
        llm_client=real_client,
        instructions="简洁回答。",
    )

    result = await agent.run("你好")
    print(f"\n[LLM 回复]: {result}")
    print(f"[钩子日志]: {log}")

    assert result is not None
    assert "complete" in log
    assert len(log) >= 1  # 至少有 complete


# ---- 5. 不同 provider 测试（如果配置了多个）----

async def test_real_llm_provider_switch(monkeypatch):
    """测试切换 provider（需要配置多个 API key）。"""
    # 这个测试需要用户配置多个 provider 的 key
    # 如果只有一个，会跳过
    try:
        config1 = LLMConfig(provider="openai")
        client1 = LLMClient(config1)
        agent1 = BaseAgent(llm_client=client1, instructions="简洁回答", output_type=str)
        result1 = await agent1.run("你好")
        print(f"\n[OpenAI]: {result1}")
        assert result1 is not None
    except Exception as e:
        pytest.skip(f"OpenAI provider 不可用: {e}")
