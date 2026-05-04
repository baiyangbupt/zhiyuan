"""示例：在 tool 中访问 userid 和 sessionid。"""

from __future__ import annotations

from pydantic_ai import RunContext

from app.agent.context import RequestContext


async def example_tool_with_context(
    ctx: RunContext[RequestContext],
    query: str,
) -> str:
    """示例工具：展示如何在 tool 中访问 userid 和 sessionid。

    Args:
        ctx: 运行上下文，包含 RequestContext
        query: 查询参数（会暴露给 LLM）

    Returns:
        包含用户信息的响应
    """
    # 通过 ctx.deps 访问 userid 和 sessionid
    userid = ctx.deps.userid
    sessionid = ctx.deps.sessionid

    return f"User {userid} in session {sessionid} queried: {query}"
