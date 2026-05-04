"""可运行的演示脚本：BaseAgent + skills 集成。"""

from __future__ import annotations

import asyncio
from typing import Any

from dotenv import load_dotenv
from pydantic_ai import RunContext, Tool

from app.config import LLMConfig
from app.llm.client import LLMClient
from app.agent.base_agent import BaseAgent


# ---------- mock 工具 ----------

async def lookup_score_line(
    ctx: RunContext,  # noqa: ARG001
    university: str,
    major: str,
) -> str:
    """查询某高校某专业的历年录取分数线（模拟数据）。"""
    return (
        f"{university} - {major} 近三年录取分数线：\n"
        "2025: 理科 620 / 文科 605\n"
        "2024: 理科 615 / 文科 600\n"
        "2023: 理科 610 / 文科 598"
    )


# ---------- 带日志的 Agent ----------

class DemoAgent(BaseAgent[str]):
    async def on_node(self, node: Any, agent_run: Any) -> None:
        print(f"  [node] {type(node).__name__}: {node}")

    async def on_complete(self, agent_run: Any) -> None:
        print(f"  [done] tokens={agent_run.usage()}")


async def main() -> None:
    load_dotenv()

    # 配置 Logfire
    from app.llm.client import configure_logfire
    configure_logfire()

    config = LLMConfig()
    client = LLMClient(config)
    print(f"Provider: {config.provider}, Model: {config.model_name}")

    agent = DemoAgent(
        llm_client=client,
        instructions=(
            "你是一个高考志愿填报助手。"
            "当学生询问分数线时，调用 lookup_score_line 工具查询。"
        ),
        output_type=str,
        tools=[Tool(lookup_score_line)],
        skill_dirs=["./skills"],
    )

    result = await agent.run("请帮我查一下北京大学计算机专业的录取分数线")
    print(f"\n最终结果:\n{result}")


if __name__ == "__main__":
    asyncio.run(main())
