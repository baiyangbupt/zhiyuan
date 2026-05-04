"""测试 RequestContext 在 tool 中的访问。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import RunContext
from pydantic_graph import End

from app.agent.base_agent import BaseAgent
from app.agent.context import RequestContext


# ---- 测试工具函数 ----

# 用于记录 tool 调用时的上下文
captured_context: RequestContext | None = None


async def tool_with_context(
    ctx: RunContext[RequestContext],
    query: str,
) -> str:
    """测试工具：捕获并验证 RequestContext。"""
    global captured_context
    captured_context = ctx.deps
    return f"User {ctx.deps.userid} queried: {query}"


# ---- fixtures ----


@pytest.fixture
def mock_client():
    """创建 mock LLMClient。"""
    client = MagicMock()
    client.model = MagicMock()
    client.model_settings = MagicMock()
    return client


@pytest.fixture
def request_context():
    """创建测试用的 RequestContext。"""
    return RequestContext(userid="test_user_123", sessionid="test_session_456")


def _make_agent_run_with_deps(nodes: list, final_output: str = "test output"):
    """构造模拟的 agent.iter() 异步上下文管理器。"""
    end_node = End(data=None)
    all_nodes = list(nodes) + [end_node]

    agent_run = AsyncMock()
    agent_run.next_node = all_nodes[0]
    agent_run.all_messages = MagicMock(return_value=[])

    call_idx = 0

    async def _next(current):  # noqa: ARG001
        nonlocal call_idx
        call_idx += 1
        return all_nodes[call_idx]

    agent_run.next = _next
    agent_run.result = MagicMock()
    agent_run.result.output = final_output

    ctx_mgr = AsyncMock()
    ctx_mgr.__aenter__ = AsyncMock(return_value=agent_run)
    ctx_mgr.__aexit__ = AsyncMock(return_value=False)
    return ctx_mgr, agent_run


# ---- 测试用例 ----


async def test_base_agent_accepts_deps_type(mock_client, mocker):
    """测试 BaseAgent 接受 deps_type 参数。"""
    mock_agent_cls = mocker.patch("app.agent.base_agent.Agent")

    agent = BaseAgent(
        llm_client=mock_client,
        instructions="test",
        output_type=str,
        deps_type=RequestContext,
    )

    # 验证 Agent 构造时传入了 deps_type
    call_kwargs = mock_agent_cls.call_args[1]
    assert call_kwargs["deps_type"] is RequestContext


async def test_run_passes_deps_to_agent_iter(mock_client, request_context, mocker):
    """测试 run() 方法将 deps 传递给 agent.iter()。"""
    mocker.patch("app.agent.base_agent.Agent")

    agent = BaseAgent(
        llm_client=mock_client,
        instructions="test",
        output_type=str,
        deps_type=RequestContext,
    )

    ctx_mgr, _ = _make_agent_run_with_deps([], final_output="ok")
    agent.agent.iter = MagicMock(return_value=ctx_mgr)

    await agent.run("test prompt", deps=request_context)

    # 验证 agent.iter 被调用时传入了 deps
    agent.agent.iter.assert_called_once_with(
        "test prompt", message_history=None, deps=request_context
    )


async def test_run_with_history_passes_deps(mock_client, request_context, mocker):
    """测试 run_with_history() 方法将 deps 传递给 agent.iter()。"""
    mocker.patch("app.agent.base_agent.Agent")

    agent = BaseAgent(
        llm_client=mock_client,
        instructions="test",
        output_type=str,
        deps_type=RequestContext,
    )

    history = [{"role": "user", "content": "previous message"}]
    ctx_mgr, _ = _make_agent_run_with_deps([], final_output="ok")
    agent.agent.iter = MagicMock(return_value=ctx_mgr)

    await agent.run_with_history("test prompt", message_history=history, deps=request_context)

    # 验证 agent.iter 被调用时传入了 deps 和 message_history
    agent.agent.iter.assert_called_once_with(
        "test prompt", message_history=history, deps=request_context
    )


async def test_tool_can_access_request_context(mock_client, request_context, mocker):
    """测试 tool 函数能够访问 RequestContext 中的 userid 和 sessionid。"""
    global captured_context
    captured_context = None

    mocker.patch("app.agent.base_agent.Agent")

    agent = BaseAgent(
        llm_client=mock_client,
        instructions="test",
        output_type=str,
        tools=[tool_with_context],
        deps_type=RequestContext,
    )

    # 模拟 agent 运行并调用 tool
    ctx_mgr, _ = _make_agent_run_with_deps([], final_output="ok")
    agent.agent.iter = MagicMock(return_value=ctx_mgr)

    # 手动调用 tool 来验证上下文访问
    mock_run_context = MagicMock(spec=RunContext)
    mock_run_context.deps = request_context

    result = await tool_with_context(mock_run_context, "test query")

    # 验证 tool 能够访问 userid 和 sessionid
    assert captured_context is not None
    assert captured_context.userid == "test_user_123"
    assert captured_context.sessionid == "test_session_456"
    assert result == "User test_user_123 queried: test query"


async def test_request_context_with_different_values(mock_client, mocker):
    """测试不同的 userid 和 sessionid 值。"""
    global captured_context
    captured_context = None

    mocker.patch("app.agent.base_agent.Agent")

    agent = BaseAgent(
        llm_client=mock_client,
        instructions="test",
        output_type=str,
        tools=[tool_with_context],
        deps_type=RequestContext,
    )

    # 创建不同的上下文
    context1 = RequestContext(userid="user_aaa", sessionid="session_111")
    context2 = RequestContext(userid="user_bbb", sessionid="session_222")

    # 测试第一个上下文
    mock_run_context1 = MagicMock(spec=RunContext)
    mock_run_context1.deps = context1
    await tool_with_context(mock_run_context1, "query1")
    assert captured_context.userid == "user_aaa"
    assert captured_context.sessionid == "session_111"

    # 测试第二个上下文
    mock_run_context2 = MagicMock(spec=RunContext)
    mock_run_context2.deps = context2
    await tool_with_context(mock_run_context2, "query2")
    assert captured_context.userid == "user_bbb"
    assert captured_context.sessionid == "session_222"


async def test_multiple_tools_share_same_context(mock_client, request_context, mocker):
    """测试多个 tool 共享同一个 RequestContext。"""
    call_log: list[tuple[str, str]] = []

    async def tool1(ctx: RunContext[RequestContext], param: str) -> str:
        call_log.append(("tool1", ctx.deps.userid, ctx.deps.sessionid))
        return f"tool1: {param}"

    async def tool2(ctx: RunContext[RequestContext], param: str) -> str:
        call_log.append(("tool2", ctx.deps.userid, ctx.deps.sessionid))
        return f"tool2: {param}"

    mocker.patch("app.agent.base_agent.Agent")

    agent = BaseAgent(
        llm_client=mock_client,
        instructions="test",
        output_type=str,
        tools=[tool1, tool2],
        deps_type=RequestContext,
    )

    # 模拟调用两个 tool
    mock_run_context = MagicMock(spec=RunContext)
    mock_run_context.deps = request_context

    await tool1(mock_run_context, "param1")
    await tool2(mock_run_context, "param2")

    # 验证两个 tool 都访问到了相同的上下文
    assert len(call_log) == 2
    assert call_log[0] == ("tool1", "test_user_123", "test_session_456")
    assert call_log[1] == ("tool2", "test_user_123", "test_session_456")
