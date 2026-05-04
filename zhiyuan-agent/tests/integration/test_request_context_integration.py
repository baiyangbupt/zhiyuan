"""集成测试：验证 RequestContext 在真实 Agent 运行中的传递。"""

from __future__ import annotations

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel

from app.agent.base_agent import BaseAgent
from app.agent.context import RequestContext
from app.llm.client import LLMClient


# 用于记录 tool 调用
tool_calls: list[dict] = []


async def save_user_preference(
    ctx: RunContext[RequestContext],
    preference_key: str,
    preference_value: str,
) -> str:
    """模拟保存用户偏好的工具。"""
    tool_calls.append({
        "tool": "save_user_preference",
        "userid": ctx.deps.userid,
        "sessionid": ctx.deps.sessionid,
        "key": preference_key,
        "value": preference_value,
    })
    return f"Saved {preference_key}={preference_value} for user {ctx.deps.userid}"


async def get_user_history(
    ctx: RunContext[RequestContext],
) -> str:
    """模拟获取用户历史的工具。"""
    tool_calls.append({
        "tool": "get_user_history",
        "userid": ctx.deps.userid,
        "sessionid": ctx.deps.sessionid,
    })
    return f"History for user {ctx.deps.userid} in session {ctx.deps.sessionid}"


@pytest.fixture
def test_llm_client():
    """创建使用 TestModel 的 LLMClient。"""
    client = LLMClient.__new__(LLMClient)
    # 使用 Pydantic AI 的 TestModel
    client.model = TestModel()
    client.model_settings = {}
    return client


@pytest.fixture(autouse=True)
def reset_tool_calls():
    """每个测试前重置 tool_calls。"""
    global tool_calls
    tool_calls = []


async def test_request_context_in_real_agent_run(test_llm_client):
    """测试在真实 Agent 运行中 RequestContext 的传递。"""
    agent = BaseAgent(
        llm_client=test_llm_client,
        instructions="You are a helpful assistant.",
        output_type=str,
        tools=[save_user_preference, get_user_history],
        deps_type=RequestContext,
    )

    # 创建请求上下文
    context = RequestContext(userid="user_999", sessionid="session_abc")

    # 配置 TestModel 的响应
    test_llm_client.model.agent_model_function_tools_responses = [
        # 第一次调用 save_user_preference
        {
            "tool_name": "save_user_preference",
            "args": {"preference_key": "city", "preference_value": "Beijing"},
        },
        # 第二次调用 get_user_history
        {
            "tool_name": "get_user_history",
            "args": {},
        },
    ]

    # 运行 agent
    result = await agent.run(
        user_prompt="Save my city preference as Beijing and get my history",
        deps=context,
    )

    # 验证 tool 调用记录（这是关键验证点）
    assert len(tool_calls) == 2

    # 验证第一个 tool 调用能访问到正确的 userid 和 sessionid
    assert tool_calls[0]["tool"] == "save_user_preference"
    assert tool_calls[0]["userid"] == "user_999"
    assert tool_calls[0]["sessionid"] == "session_abc"
    # 注意：TestModel 可能不会完全按照我们的配置传递参数，但这不影响上下文传递的验证

    # 验证第二个 tool 调用能访问到正确的 userid 和 sessionid
    assert tool_calls[1]["tool"] == "get_user_history"
    assert tool_calls[1]["userid"] == "user_999"
    assert tool_calls[1]["sessionid"] == "session_abc"

    # 验证结果包含 tool 返回的信息
    assert "user_999" in result
    assert "session_abc" in result


async def test_request_context_with_message_history(test_llm_client):
    """测试带历史消息的 RequestContext 传递。"""
    agent = BaseAgent(
        llm_client=test_llm_client,
        instructions="You are a helpful assistant.",
        output_type=str,
        tools=[get_user_history],
        deps_type=RequestContext,
    )

    context = RequestContext(userid="user_777", sessionid="session_xyz")

    # 模拟历史消息
    history = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
    ]

    # 配置 TestModel 响应
    test_llm_client.model.agent_model_function_tools_responses = [
        {
            "tool_name": "get_user_history",
            "args": {},
        },
    ]

    # 运行 agent
    result, all_messages = await agent.run_with_history(
        user_prompt="Show me my history",
        message_history=history,
        deps=context,
    )

    # 验证 tool 调用能访问到正确的上下文
    assert len(tool_calls) == 1
    assert tool_calls[0]["userid"] == "user_777"
    assert tool_calls[0]["sessionid"] == "session_xyz"

    # 验证结果包含用户信息
    assert "user_777" in result
    assert "session_xyz" in result


async def test_different_contexts_for_different_requests(test_llm_client):
    """测试不同请求使用不同的 RequestContext。"""
    agent = BaseAgent(
        llm_client=test_llm_client,
        instructions="You are a helpful assistant.",
        output_type=str,
        tools=[save_user_preference],
        deps_type=RequestContext,
    )

    # 第一个请求
    context1 = RequestContext(userid="user_aaa", sessionid="session_111")
    test_llm_client.model.agent_model_function_tools_responses = [
        {
            "tool_name": "save_user_preference",
            "args": {"preference_key": "color", "preference_value": "red"},
        },
    ]
    result1 = await agent.run("Save color as red", deps=context1)

    # 第二个请求
    context2 = RequestContext(userid="user_bbb", sessionid="session_222")
    test_llm_client.model.agent_model_function_tools_responses = [
        {
            "tool_name": "save_user_preference",
            "args": {"preference_key": "color", "preference_value": "blue"},
        },
    ]
    result2 = await agent.run("Save color as blue", deps=context2)

    # 验证两次调用使用了不同的上下文
    assert len(tool_calls) == 2
    assert tool_calls[0]["userid"] == "user_aaa"
    assert tool_calls[0]["sessionid"] == "session_111"
    assert tool_calls[1]["userid"] == "user_bbb"
    assert tool_calls[1]["sessionid"] == "session_222"

    # 验证结果包含对应的用户信息
    assert "user_aaa" in result1
    assert "user_bbb" in result2
