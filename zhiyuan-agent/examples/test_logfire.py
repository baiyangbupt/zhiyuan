"""测试 Logfire 集成的简单脚本。"""

from __future__ import annotations

import asyncio

from dotenv import load_dotenv
from pydantic_ai import Agent

from app.config import LLMConfig, LogfireConfig
from app.llm.client import LLMClient, configure_logfire


async def main() -> None:
    load_dotenv()

    # 显示配置信息
    llm_config = LLMConfig()
    logfire_config = LogfireConfig()

    print(f"LLM Provider: {llm_config.provider}")
    print(f"LLM Model: {llm_config.model_name}")
    print(f"Logfire Enabled: {logfire_config.enabled}")
    print(f"Logfire Token: {'***' + logfire_config.token[-8:] if logfire_config.token else 'Not set'}")
    print()

    # 配置 Logfire
    configure_logfire(logfire_config)
    print("Logfire configured successfully!")
    print()

    # 创建简单的 Agent 测试
    client = LLMClient(llm_config)
    agent = Agent(
        model=client.model,
        output_type=str,
        instructions="You are a helpful assistant. Answer briefly.",
    )

    print("Running test query...")
    result = await agent.run("What is 2+2? Answer in one sentence.")
    print(f"Result: {result.output}")
    print()
    print("✓ Test completed! Check your Logfire dashboard for traces.")


if __name__ == "__main__":
    asyncio.run(main())
