"""Career direction intent extraction tool."""

from __future__ import annotations

import json
import logging

from pydantic_ai import Agent, RunContext

from app.agent.context import RequestContext
from app.config import ExtractConfig, LLMConfig
from app.domain.career_slots import (
    CAREER_FURTHER_STUDY,
    CAREER_MARKET_EMPLOYMENT,
    CAREER_STABLE_EMPLOYMENT,
    CAREER_SYSTEM_PUBLIC_SERVICE,
)
from app.data.message_utils import format_messages, trim_last_n_messages
from app.llm.client import LLMClient
from app.schemas.career_intent import CareerIntentResult
from app.tools.extraction_json import parse_extraction_json

logger = logging.getLogger(__name__)

_extract_config: ExtractConfig | None = None
_extraction_client: LLMClient | None = None


def _get_extract_config() -> ExtractConfig:
    global _extract_config
    if _extract_config is None:
        _extract_config = ExtractConfig()
    return _extract_config


def _get_extraction_client() -> LLMClient:
    global _extraction_client
    if _extraction_client is None:
        _extraction_client = LLMClient(LLMConfig())
    return _extraction_client


def _build_system_message(chat_history: list[dict]) -> str:
    chat_history_str = format_messages(chat_history)
    return f"""
# 【任务背景】
你是一个高考志愿对话里的职业发展方向意向抽取工具，需要根据学生对话，识别学生明确表达的就业/发展方向偏好或排除项。

# 【对话历史】
{chat_history_str}

# 【抽取目标】
你只能从下面 4 个方向槽位中做选择，不能创造新槽位：
- {CAREER_SYSTEM_PUBLIC_SERVICE}：体制内/考公/考编/公务员/事业单位/进编制/进体制等
- {CAREER_STABLE_EMPLOYMENT}：稳定就业/求稳/工作稳定/抗风险/先就业稳定下来等
- {CAREER_FURTHER_STUDY}：读研/保研/深造/继续升学/学术发展等
- {CAREER_MARKET_EMPLOYMENT}：企业就业/市场化就业/大城市就业/互联网或产业岗位/去企业发展等

# 【抽取规则】
1. 只抽取学生明确表达的方向态度。中性了解、泛泛讨论、信息查询，不要硬判成偏好。
2. 正向态度放入 positive，负向态度放入 negative。
3. 同一个槽位不能同时出现在 positive 和 negative；如果态度前后变化，以最后一次明确态度为准。
4. 如果学生只是问“适不适合”“值不值得考虑”“这个方向怎么样”，这属于探索阶段，不代表已经形成偏好或要求，除非对话里同时明确表达了想要/不要。
5. 不要把专业、学校、城市抽成这里的方向槽位。
6. 输出前再次检查，避免过度推断。

# 【返回格式】
只返回 JSON：
{{
  "positive": ["slot1"],
  "negative": ["slot2"]
}}

如果无法确定：
{{
  "positive": [],
  "negative": []
}}
"""


async def extract_career_intent(
    ctx: RunContext[RequestContext],
    **kwargs,
) -> str:
    """Extract explicit career-direction preference/constraint from chat history."""
    chat_history = ctx.deps.chat_history or []
    if not chat_history:
        return json.dumps({"positive": [], "negative": []}, ensure_ascii=False)

    config = _get_extract_config()
    trimmed_history = trim_last_n_messages(chat_history, config.last_n_messages)
    extraction_agent = Agent(
        model=_get_extraction_client().model,
        output_type=str,
        instructions=_build_system_message(trimmed_history),
    )

    try:
        result = await extraction_agent.run("请提取职业发展方向意向", model_settings={"temperature": 0})
        result_data = parse_extraction_json(result.output, CareerIntentResult).model_dump()
        logger.info(
            "extract_career_intent: positive=%s negative=%s",
            result_data["positive"],
            result_data["negative"],
        )
        return json.dumps(result_data, ensure_ascii=False)
    except Exception:
        logger.warning("extract_career_intent failed", exc_info=True)
        return json.dumps({"positive": [], "negative": []}, ensure_ascii=False)
