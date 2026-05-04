"""School intent extraction tool."""

import json
import logging
from typing import Any

from pydantic_ai import Agent, RunContext

from app.agent.context import RequestContext
from app.config import ExtractConfig, LLMConfig
from app.data.message_utils import format_messages, trim_last_n_messages
from app.data.school_data import area_to_bachelor_schools, area_to_associate_schools
from app.llm.client import LLMClient
from app.schemas.school_intent import SchoolIntentResult
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


def _filter_school_from_chat(chat_history: list[dict], area_to_school: dict[str, list[str]]) -> list[str]:
    """Pre-filter schools from chat history using keyword matching."""
    chat_content = '\n'.join([msg.get('content', '') for msg in chat_history])
    school_set: set[str] = set()
    for key, schools in area_to_school.items():
        if key in chat_content:
            school_set.update(schools)
    return sorted(school_set)


def _format_student_info(score_detail: Any | None) -> str:
    """Format student information."""
    if not score_detail:
        return "暂无学生信息"

    # Handle both dict and object
    if isinstance(score_detail, dict):
        sex_name = score_detail.get('sex', {}).get('name', '未知') if isinstance(score_detail.get('sex'), dict) else score_detail.get('sex', '未知')
        province_name = score_detail.get('province', {}).get('name', '未知') if isinstance(score_detail.get('province'), dict) else score_detail.get('province', '未知')
    else:
        sex_name = getattr(score_detail, 'sex', '未知')
        province_name = getattr(score_detail, 'province', '未知')

    return f"学生性别：{sex_name}，学生所在省份：{province_name}"


def _build_system_message(chat_history: list[dict], schools: list[str], student_info: str) -> str:
    """Build system message for school intent extraction."""
    chat_history_str = format_messages(chat_history)
    school_data_str = '\n'.join(['-' + school for school in schools])

    system_message = f"""
# 【任务背景】
你是一个院校实体提取工具，需要根据学生与规划师的对话，提取学生对报考院校的意向，需要提取其正面院校意向和负面院校意向。

# 【学生信息】
{student_info}

# 【对话历史】
{chat_history_str}

# 【抽取规则】
1.从【对话历史】中抽取全称或缩写格式的院校词汇，将原始词汇去重后存入allkeys。抽取时需要满足以下条件：
- 若allkeys中的数量超过10，请重新抽取，直到抽取数量不超过10个为止。
- 如果学生对规划师或系统推荐的院校表达了意向，才能将这些院校抽取出来；否则忽略规划师或系统推荐的院校名称，不进行抽取。
2.校验allkeys中的院校词汇，抽取出的院校词汇格式必须满足以下条件：
- 包含全称格式，例如"XX大学"、"XX大学XX学院"、"XX学院"等。
- 包含缩写格式，例如"XX大"、"XX理工"、"XX师大"等。如"北大"、"南京理工"、"北师大"等。
- 所有不符合上述格式的停用词，一律从allkeys中删除。不符合格式的停用词如下：
（1）不得抽取如"医学类"、"师范类"、"理工类"、"985"、"211"、"双一流"、"军校"、"专科"、"本科"等类型词汇。
（2）不得抽取省份、城市、地区，如"河北"、"西安"、"江南"、"华南"、"北方"、"南方"、"沿海"、"周边"等纯地域性词汇。
（3）不得抽取如"那所学校"、"这些学校"、"推荐的大学"、"好学校"、"重点大学"等指代或泛称。
3.将allkeys中的院校词语，结合模型本身实体消歧能力并从【院校选项】给定的选项中匹配实体名称，最后放入newkeys中。匹配时需要满足以下条件：
- 每个院校词汇只能匹配最相关的一个院校实体名称，不能匹配多个结果。
- 匹配院校实体时必须从【院校选项】给定的选项中匹配，不能自己创造院校名称。如果找不到高度匹配的选项就匹配'NULL'。
4.根据【对话历史】，必须从newkeys中识别学生明确表达意向的所有院校，识别规则如下：
- 识别学生明确表达的所有正面意向院校，去重后存入colleges。正面意向主要包括感兴趣、考虑、接受、想去、喜欢等正面态度，也包括增加、添加、补充、排序靠前、放前面等志愿修改动作。
- 识别学生明确表达的所有负面意向院校，去重后存入negative_colleges。负面意向主要包括不感兴趣、不考虑、不接受、不想去、不喜欢等负面态度，也包括删除、减少、去掉、排序靠后、放后面等志愿修改动作。
- 若学生明确对规划师或系统推荐的院校表达了意愿，则将其进行抽取。例如"上面推荐的都感兴趣"或"上面推荐的都不喜欢"，则需要将推荐的院校抽取出来。
- 一个院校不能既是正面意向又是负面意向，若无法判断则跳过不进行处理。若学生对某院校的态度发生变化，按照学生最后一次对该院校表达的态度进行识别。
- "不确定"、"不知道"、"再想想"、"再看看"等中性表达不能作为意向态度。
- 如果匹配不到，返回空列表，不要存入'NULL'。
5.输出结果之前，请再次思考并检查是否有遗漏或者错误匹配的情况，并进行改正。

# 特殊案例
一、抽取全称或缩写格式的院校词汇时，错误示例（禁止抽取）如下：
1. "对师范类院校感兴趣" → 不得抽取"师范类院校"，且不能存入allkeys。
2. "我想去西安" → 不得抽取"西安"；"不想去江南" → 不得抽取"江南"，且不能存入allkeys。
3. "推荐的学校都可以" → 不得抽取"推荐的学校"，且不能存入allkeys。
二、抽取全称或缩写格式的院校词汇时，正确示例如下：
1. "我对华东师范大学挺感兴趣的" → 可抽取"华东师范大学"存入allkeys。
2. "浙大是不是在杭州？" → 可抽取"浙大"存入allkeys。
3. "北师大听起来不错" → 可抽取"北师大"存入allkeys。
三、院校名称可能存在潜在的歧义冲突，需要精确识别目标院校实体。常见情况如下：
1. 对话中提到的院校简称，要根据语境分别还原为全称。如'南大'、'北语'、'北师大'应该分别匹配'南京大学'、'北京语言大学'、'北京师范大学'。
2. 对话中提到的'农大'、'林大'、'师大'等类似简称在不同省份存在不同匹配结果，要结合对话上下文中的地理位置、学生信息等判断院校所在省份并进一步实体匹配。如推断省份为黑龙江，则'农大'应该匹配'东北农业大学'。
3. 可能有单个院校的不同分院或者专科院校需要加以区分，如贵州中医药大学与贵州中医药大学时珍学院、哈尔滨工业大学与哈尔滨工业大学(深圳)等。
4. 可能有相同前缀，但是存在'学院'、'大学'区别的院校，如贵州师范大学(公办)与贵州师范学院(民办)。
5. 对话中可能把学院说成学校，其实它们是一个含义。如'上海海关学校'应该匹配'上海海关学院'。
6. 对话中可能存在用口语'什么'来连接记不清的院校名称。如'北师大香港什么浸会'应该匹配'北师香港浸会大学'。
7. 对话数据是语音转换而来，有的院校名称可能会出现文字错误，可以尝试自行修正或者通过拼音匹配。如'南京孝庄学院'应该匹配'南京晓庄学院';'上海剑桥学院'应该匹配'上海建桥学院'。
8. 禁止匹配专业或类型类词汇，如"医学类"、"师范类"、"理工类"、"985"、"211"、"双一流"、"军校"、"专科"、"本科"等。例如"对师范类院校感兴趣"中的"师范类院校"无法匹配。
9. 禁止匹配省份、城市、地区等纯地域性词汇，如"河北"、"西安"、"江南"、"华南"、"北方"、"南方"、"沿海"、"周边"等。例如"我想去西安"中的"西安"无法匹配；"不想去江南"中的"江南"无法匹配。
10. 禁止匹配模糊指代或泛称，如"那所学校"、"推荐的大学"、"好学校"、"重点大学"等未明确命名的表达。例如"推荐的学校都可以"中的"推荐的学校"无法匹配。

# 【院校选项】
```
{school_data_str}
```

# 【返回格式】
以JSON格式返回结果
{{
    "allkeys":["院校词汇1", "院校词汇2", "院校词汇3"],
    "newkeys":["院校实体1", "院校实体2", "院校实体3"],
    "colleges":["院校实体1", "院校实体3"],
    "negative_colleges":["院校实体2"]
}}

如果无法确定学生的院校意向，请返回空数组:
{{
    "allkeys":["院校词汇1", "院校词汇2", "院校词汇3"],
    "newkeys":["院校实体1", "院校实体2", "院校实体3"],
    "colleges":[],
    "negative_colleges":[]
}}
"""
    return system_message


async def extract_school_intent(
    ctx: RunContext[RequestContext],
    **kwargs,
) -> str:
    """从对话历史中提取学生的院校意向。

    根据当前对话历史，识别学生提到的院校名称，区分正面意向和负面意向。

    Returns:
        JSON string with extraction results
    """
    chat_history = ctx.deps.chat_history
    batch = ctx.deps.batch
    score_detail = ctx.deps.score_detail

    logger.info(
        "extract_school_intent called: chat_history_len=%d, batch=%s, has_score_detail=%s",
        len(chat_history) if chat_history else 0,
        batch,
        score_detail is not None,
    )

    if not chat_history:
        logger.warning("extract_school_intent: chat_history is empty, returning empty result")
        return json.dumps({"allkeys": [], "newkeys": [], "colleges": [], "negative_colleges": []}, ensure_ascii=False)

    # Format student info
    student_info = _format_student_info(score_detail)
    logger.info("extract_school_intent: student_info=%s", student_info)

    # Determine school type and filter schools
    if batch is None or batch == "" or batch == "01":
        filtered_school_list = _filter_school_from_chat(chat_history, area_to_bachelor_schools)
        logger.info("extract_school_intent: using bachelor schools, filtered %d candidates", len(filtered_school_list))
    else:
        filtered_school_list = _filter_school_from_chat(chat_history, area_to_associate_schools)
        logger.info("extract_school_intent: using associate schools, filtered %d candidates", len(filtered_school_list))

    # Trim to last N messages
    config = _get_extract_config()
    trimmed_history = trim_last_n_messages(chat_history, config.last_n_messages)
    logger.info(
        "extract_school_intent: trimmed chat_history from %d to %d messages (last_n=%d)",
        len(chat_history), len(trimmed_history), config.last_n_messages,
    )

    # Build extraction prompt
    system_message = _build_system_message(trimmed_history, filtered_school_list, student_info)
    logger.debug("extract_school_intent: system_message length=%d", len(system_message))

    # Create temporary agent for extraction
    llm_client = _get_extraction_client()
    logger.info("extract_school_intent: calling LLM for extraction...")

    extraction_agent = Agent(
        model=llm_client.model,
        output_type=str,
        instructions=system_message,
    )

    try:
        result = await extraction_agent.run("请提取院校意向", model_settings={"temperature": 0})
        result_data = parse_extraction_json(result.output, SchoolIntentResult).model_dump()
        logger.info(
            "extract_school_intent: LLM extraction complete - allkeys=%s, newkeys=%s, colleges=%s, negative_colleges=%s",
            result_data["allkeys"],
            result_data["newkeys"],
            result_data["colleges"],
            result_data["negative_colleges"],
        )
        result_json = json.dumps(result_data, ensure_ascii=False)

        return result_json
    except Exception:
        logger.exception("extract_school_intent: LLM extraction failed")
        raise
