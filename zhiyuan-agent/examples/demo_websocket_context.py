"""演示如何在 WebSocket 请求中使用 RequestContext。"""

from __future__ import annotations

import asyncio

from app.agent.chat_agent import ChatAgent
from app.agent.context import RequestContext
from app.config import LLMConfig
from app.llm.client import LLMClient


async def handle_websocket_request(
    userid: str,
    sessionid: str,
    user_message: str,
    message_history: list | None = None,
) -> str:
    """模拟 WebSocket 请求处理。

    Args:
        userid: 用户 ID
        sessionid: 会话 ID
        user_message: 用户消息
        message_history: 历史消息

    Returns:
        Agent 响应
    """
    # 1. 创建请求上下文
    request_context = RequestContext(userid=userid, sessionid=sessionid)

    # 2. 初始化 LLM 和 Agent
    config = LLMConfig()
    llm_client = LLMClient(config)
    chat_agent = ChatAgent(llm_client)

    # 3. 调用 agent，传入 deps 参数
    response = await chat_agent.run(
        user_prompt=user_message,
        message_history=message_history,
        deps=request_context,  # 关键：传入上下文
    )

    return response


async def main():
    """演示示例。"""
    # 模拟 WebSocket 请求
    response = await handle_websocket_request(
        userid="user123",
        sessionid="session456",
        user_message="你好，我想咨询志愿填报",
    )
    print(f"Agent 响应: {response}")


if __name__ == "__main__":
    asyncio.run(main())
