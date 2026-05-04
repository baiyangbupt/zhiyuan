"""City intent extraction tools.

Extracts student location preferences (province/city/area) from chat history,
supporting both positive and negative intent extraction.
"""

import json
import logging
from typing import Any

from pydantic_ai import Agent, RunContext

from app.agent.context import RequestContext
from app.config import ExtractConfig, LLMConfig
from app.data.city_data import province_city_hierarchy_text
from app.data.message_utils import format_messages, trim_last_n_messages
from app.llm.client import LLMClient
from app.schemas.city_intent import CityIntentResult, NegativeCityIntentResult
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


def _format_student_info(score_detail: Any | None) -> str:
    """Format student information for prompt context."""
    if not score_detail:
        return "暂无学生信息"

    # Handle both dict and object
    if isinstance(score_detail, dict):
        sex_name = score_detail.get('sex', {}).get('name', '未知') if isinstance(score_detail.get('sex'), dict) else score_detail.get('sex', '未知')
        province_name = score_detail.get('province', {}).get('name', '未知') if isinstance(score_detail.get('province'), dict) else score_detail.get('province', '未知')
    else:
        sex_name = getattr(score_detail, "sex", "未知")
        province_name = getattr(score_detail, "province", "未知")

    return f"学生性别：{sex_name}，学生所在省份：{province_name}"


def _build_positive_system_message(chat_history_str: str, student_info: str) -> str:
    """Construct system message for positive city intent extraction.

    Includes the 26 special case rules for regional groupings.
    """
    return f"""\
# 【任务背景】
你是一个专业的省份和城市实体提取工具，需要根据学生与规划师的对话，提取学生对报考地域的意向，需要提取其正面省份或城市的意向。

# 【学生信息】
{student_info}

# 【对话历史】
{chat_history_str}

# 抽取任务和规则
1.从【对话历史】中抽取学生明确表达的所有正面意向省份或城市。抽取时需要满足以下条件：
- 正面意向包括学生自己感兴趣、考虑、接受、想去、喜欢等正面态度，也包括增加、添加、补充、排序靠前、放前面等志愿修改动作。"不确定"、"不知道"、"再想想"、"再看看"等中性表达不能作为正面意向态度。
- 若学生明确对规划师或系统推荐的省份或者城市表达了正向意愿，则将其进行抽取；否则忽略推荐的省份和城市，不需要进行抽取。例如"上面推荐的都感兴趣"，则需要将推荐的省份或城市抽取出来。
- 绝对不能抽取出学校名称中涉及到的省份或城市。例如，不能从'江西财经'抽取江西、不能从'重庆师范'抽取重庆等。
- 一个省份或城市不能既是正面意向又是负面意向，若无法判断则跳过不进行处理。若学生对某省份或城市的态度发生变化，按照学生最后一次对该地域表达的态度进行抽取。
- 在整个过程中，时刻记住必须抽取学生最后一次明确表达正面意向的省份或城市，其他意向都不要，一旦发现识别错误立刻纠正结果。
2.将学生的正面意向省份或城市，必须从【省市层级结构】给定的选项中匹配实体名称，不能返回其他词汇或符号。其中，无缩进的行是所有省份实体，缩进2个空格的行是省份对应的城市实体。匹配时需要满足以下条件：
- 若表述精确到省份级别时，将匹配到的省份实体放入province；若表述精确到城市级别时，将匹配到的城市实体放入city。
- 如果用户明确表达了对某省份的若干城市是正面意向，那么只把城市实体放入city，其对应省份实体不用放入province。
- 如果用户只明确表达了对某省份是正面意向，但没说明具体城市，则只将省份实体放入province。
- province和city中返回的值必须是【省市层级结构】给定的实体，不能返回其他词汇、符号、拼音等。
3.输出结果之前，请再次思考并检查是否有遗漏或者错误匹配的情况，并进行改正。

# 特殊案例
1.如果抽取到学生对北京、天津、上海、重庆这些地方是正面意向，必须将其放入province，不是放入city。
2.如果抽取到学生对京津冀、北京周边、环京地区是正面意向，则需要把'北京','天津','河北'放入province中。
3.如果抽取到学生对东北、东三省地区是正面意向，则需要把'黑龙江','吉林','辽宁'放入province中。
4.如果抽取到学生对江浙沪、长三角、江浙地区、江南等地区是正面意向，则需要把'江苏','浙江','上海'放入province中。
5.如果抽取到学生对北上广地区是正面意向，则需要把'北京','上海'放入province中，将'广州'放入city中。
6.如果抽取到学生对一线城市、北上广深地区是正面意向，则需要把'北京','上海'放入province中，将'广州','深圳'放入city中。
7.如果抽取到学生对南方地区是正面意向，则需要把'浙江','上海','湖南','湖北','江西','福建','云南','贵州','四川','重庆','广东','广西','海南','江苏','安徽'放入province中。
8.如果抽取到学生对北方地区是正面意向，则需要把'黑龙江','吉林','辽宁','内蒙古','新疆','西藏','青海','甘肃','宁夏','陕西','山西','山东','河北','北京','天津'放入province中。
9.如果抽取到学生对偏远地区是正面意向，则需要把'新疆','西藏','宁夏','甘肃','青海','内蒙古'放入province中。
10.如果抽取到学生对西南地区是正面意向，则需要把'云南','贵州','四川','重庆','西藏'放入province中。
11.如果抽取到学生对西北地区是正面意向，则需要把'陕西','新疆','宁夏','甘肃','青海'放入province中。
12.如果抽取到学生对华北地区是正面意向，则需要把'河北','山西','北京','天津','内蒙古'放入province中。
13.如果抽取到学生对华东地区是正面意向，则需要把'安徽','江苏','浙江','上海','福建','山东'放入province中。
14.如果抽取到学生对华中地区是正面意向，则需要把'河南','湖南','湖北','江西'放入province中。
15.如果抽取到学生对华南地区是正面意向，则需要把'海南','广东','广西','福建'放入province中。
16.如果抽取到学生对东南地区是正面意向，则需要把'江苏','浙江','上海','广东','福建'放入province中。
17.如果抽取到学生对中南地区是正面意向，则需要把'河南','湖南','湖北','广东','广西','海南'放入province中。
18.如果抽取到学生对本省周边或附近是正面意向，则需要把学生所在省份、以及与该省份接壤的其他省份或直辖市放入province中。
19.如果抽取到学生对某省份周边或附近是正面意向，则需要把该省份以及与其接壤的其他省份或直辖市放入province中。
20.如果学生明确表达对某省份若干城市是正面意向，只保留城市名称。例如学生只接受陕西西安，那么只把'西安'放入city，'陕西'不用放入province。
21.如果学生明确表达对新一线城市是正面意向，则需要把'天津','重庆'放入province，把'合肥','杭州','南京','长沙','西安','武汉','成都','苏州','东莞','青岛','郑州','宁波','佛山'放入city。
22.如果学生明确表达对二线城市是正面意向，则需要把'石家庄','太原','呼和浩特','沈阳','大连','长春','哈尔滨','福州','厦门','南昌','济南','南宁','海口','贵阳','昆明','兰州','西宁','银川','乌鲁木齐'放入city中。
23.如果学生明确表达对三线城市是正面意向，则需要把'唐山','秦皇岛','包头','丹东','锦州','吉林','牡丹江','无锡','徐州','扬州','温州','金华','蚌埠','安庆','泉州','九江','赣州','烟台','济宁','洛阳','平顶山','宜昌','襄阳','岳阳','常德','韶关','湛江','惠州','桂林','北海','三亚','泸州','南充','遵义','大理'放入city中。
24.如果学生明确表达对发达省份是正面意向，则需要把'北京','上海','广东','江苏','浙江','山东','四川'放入province中。
25.如果学生明确表达对发达城市是正面意向，则需要把'北京','上海','重庆'放入province中，把'深圳','广州','杭州','成都','南京','武汉','苏州'放入city中。
26.如果学生明确表达对不发达、欠发达地区是正面意向，则需要把'新疆','西藏','宁夏','甘肃','青海','内蒙古','云南','贵州','广西'放入province中。

# 【省市层级结构】
以下是所有可能的省份、城市选项，按照层级结构展示（缩进表示层级关系）:
```
{province_city_hierarchy_text}
```

# 【返回格式】
以JSON格式返回结果
{{
    "province":["省份1","省份2","省份3"],
    "city":["城市1","城市2","城市3"],
    "area":[]
}}

如果无法确定正面省份或城市，请对应返回空值:
{{
    "province":[],
    "city":[],
    "area":[]
}}
"""


def _build_negative_system_message(chat_history_str: str, student_info: str) -> str:
    """Construct system message for negative city intent extraction.

    Includes the 26 special case rules for regional groupings (negative version).
    """
    return f"""\
# 【任务背景】
你是一个专业的省份和城市实体提取工具，需要根据学生与规划师的对话，提取学生对报考地域的意向，需要提取其负面省份或城市的意向。

# 【学生信息】
{student_info}

# 【对话历史】
{chat_history_str}

# 抽取任务和规则
1.从【对话历史】中抽取学生明确表达的所有负面意向省份或城市。抽取时需要满足以下条件：
- 负面意向包括学生自己不感兴趣、不考虑、不接受、不想去、不喜欢等负面态度，也包括删除、减少、去掉、排序靠后、放后面等志愿修改动作。"不确定"、"不知道"、"再想想"、"再看看"等中性表达不能作为负面意向态度。
- 若学生明确对规划师或系统推荐的省份或者城市表达了负向意愿，则将其进行抽取；否则忽略推荐的省份和城市，不需要进行抽取。例如"上面推荐的都不喜欢"，则需要将推荐的省份或城市抽取出来。
- 绝对不能抽取出学校名称中涉及到的省份或城市。例如，不能从'江西财经'抽取江西、不能从'重庆师范'抽取重庆等。
- 一个省份或城市不能既是正面意向又是负面意向，若无法判断则跳过不进行处理。若学生对某省份或城市的态度发生变化，按照学生最后一次对该地域表达的态度进行抽取。
- 在整个过程中，时刻记住必须抽取学生最后一次明确表达负面意向的省份或城市，其他意向都不要，一旦发现识别错误立刻纠正结果。
2.将学生的负面意向省份或城市，必须从【省市层级结构】给定的选项中匹配实体名称，不能返回其他词汇或符号。其中，无缩进的行是所有省份实体，缩进2个空格的行是省份对应的城市实体。匹配时需要满足以下条件：
- 若表述精确到省份级别时，将匹配到的省份实体放入province；若表述精确到城市级别时，将匹配到的城市实体放入city。
- 如果用户明确表达了对某省份的若干城市是负面意向，那么只把城市实体放入city，其对应省份实体不用放入province。
- 如果用户只明确表达了对某省份是负面意向，但没说明具体城市，则只将省份实体放入province。
- province和city中返回的值必须是【省市层级结构】给定的实体，不能返回其他词汇、符号、拼音等。
3.输出结果之前，请再次思考并检查是否有遗漏或者错误匹配的情况，并进行改正。

# 特殊案例
1.如果抽取到学生对北京、天津、上海、重庆这些地方是负面意向，必须将其放入province，不是放入city。
2.如果抽取到学生对京津冀、北京周边、环京地区是负面意向，则需要把'北京','天津','河北'放入province中。
3.如果抽取到学生对东北、东三省地区是负面意向，则需要把'黑龙江','吉林','辽宁'放入province中。
4.如果抽取到学生对江浙沪、长三角、江浙地区、江南等地区是负面意向，则需要把'江苏','浙江','上海'放入province中。
5.如果抽取到学生对北上广地区是负面意向，则需要把'北京','上海'放入province中，将'广州'放入city中。
6.如果抽取到学生对一线城市、北上广深地区是负面意向，则需要把'北京','上海'放入province中，将'广州','深圳'放入city中。
7.如果抽取到学生对南方地区是负面意向，则需要把'浙江','上海','湖南','湖北','江西','福建','云南','贵州','四川','重庆','广东','广西','海南','江苏','安徽'放入province中。
8.如果抽取到学生对北方地区是负面意向，则需要把'黑龙江','吉林','辽宁','内蒙古','新疆','西藏','青海','甘肃','宁夏','陕西','山西','山东','河北','北京','天津'放入province中。
9.如果抽取到学生对偏远地区是负面意向，则需要把'新疆','西藏','宁夏','甘肃','青海','内蒙古'放入province中。
10.如果抽取到学生对西南地区是负面意向，则需要把'云南','贵州','四川','重庆','西藏'放入province中。
11.如果抽取到学生对西北地区是负面意向，则需要把'陕西','新疆','宁夏','甘肃','青海'放入province中。
12.如果抽取到学生对华北地区是负面意向，则需要把'河北','山西','北京','天津','内蒙古'放入province中。
13.如果抽取到学生对华东地区是负面意向，则需要把'安徽','江苏','浙江','上海','福建','山东'放入province中。
14.如果抽取到学生对华中地区是负面意向，则需要把'河南','湖南','湖北','江西'放入province中。
15.如果抽取到学生对华南地区是负面意向，则需要把'海南','广东','广西','福建'放入province中。
16.如果抽取到学生对东南地区是负面意向，则需要把'江苏','浙江','上海','广东','福建'放入province中。
17.如果抽取到学生对中南地区是负面意向，则需要把'河南','湖南','湖北','广东','广西','海南'放入province中。
18.如果抽取到学生对本省周边或附近是负面意向，则需要把学生所在省份、以及与该省份接壤的其他省份或直辖市放入province中。
19.如果抽取到学生对某省份周边或附近是负面意向，则需要把该省份以及与其接壤的其他省份或直辖市放入province中。
20.如果学生明确表达对某省份若干城市是负面意向，只保留城市名称。例如学生不喜欢广东东莞，那么只把'东莞'放入city，'广东'不用放入province。
21.如果学生明确表达对新一线城市是负面意向，则需要把'天津','重庆'放入province，把'合肥','杭州','南京','长沙','西安','武汉','成都','苏州','东莞','青岛','郑州','宁波','佛山'放入city。
22.如果学生明确表达对二线城市是负面意向，则需要把'石家庄','太原','呼和浩特','沈阳','大连','长春','哈尔滨','福州','厦门','南昌','济南','南宁','海口','贵阳','昆明','兰州','西宁','银川','乌鲁木齐'放入city中。
23.如果学生明确表达对三线城市是负面意向，则需要把'唐山','秦皇岛','包头','丹东','锦州','吉林','牡丹江','无锡','徐州','扬州','温州','金华','蚌埠','安庆','泉州','九江','赣州','烟台','济宁','洛阳','平顶山','宜昌','襄阳','岳阳','常德','韶关','湛江','惠州','桂林','北海','三亚','泸州','南充','遵义','大理'放入city中。
24.如果学生明确表达对发达省份是负面意向，则需要把'北京','上海','广东','江苏','浙江','山东','四川'放入province中。
25.如果学生明确表达对发达城市是负面意向，则需要把'北京','上海','重庆'放入province中，把'深圳','广州','杭州','成都','南京','武汉','苏州'放入city中。
26.如果学生明确表达对不发达、欠发达地区是负面意向，则需要把'新疆','西藏','宁夏','甘肃','青海','内蒙古','云南','贵州','广西'放入province中。

# 【省市层级结构】
以下是所有可能的省份、城市选项，按照层级结构展示（缩进表示层级关系）:
```
{province_city_hierarchy_text}
```

# 【返回格式】
以JSON格式返回结果
{{
    "province":["省份1","省份2","省份3"],
    "city":["城市1","城市2","城市3"]
}}

如果无法确定负面省份或城市，请对应返回空值:
{{
    "province":[],
    "city":[]
}}
"""


async def extract_city_intent(
    ctx: RunContext[RequestContext],
    **kwargs,
) -> str:
    """从对话历史中提取学生对报考地域的正面意向。

    根据当前对话历史，识别学生提到的省份和城市，提取正面意向。

    Returns:
        JSON string with province, city, area fields
    """
    chat_history = ctx.deps.chat_history
    score_detail = ctx.deps.score_detail

    logger.info(
        "extract_city_intent called: chat_history_len=%d, has_score_detail=%s",
        len(chat_history) if chat_history else 0,
        score_detail is not None,
    )

    if not chat_history:
        logger.warning("extract_city_intent: chat_history is empty, returning empty result")
        return json.dumps({"province": [], "city": [], "area": []}, ensure_ascii=False)

    # Format student info
    student_info = _format_student_info(score_detail)
    logger.info("extract_city_intent: student_info=%s", student_info)

    # Trim to last N messages
    config = _get_extract_config()
    trimmed_history = trim_last_n_messages(chat_history, config.last_n_messages)
    logger.info(
        "extract_city_intent: trimmed chat_history from %d to %d messages (last_n=%d)",
        len(chat_history), len(trimmed_history), config.last_n_messages,
    )

    # Format chat history
    chat_history_str = format_messages(trimmed_history)

    # Build extraction prompt
    system_message = _build_positive_system_message(chat_history_str, student_info)
    logger.debug("extract_city_intent: system_message length=%d", len(system_message))

    # Create temporary agent for extraction
    llm_client = _get_extraction_client()
    logger.info("extract_city_intent: calling LLM for extraction...")

    extraction_agent = Agent(
        model=llm_client.model,
        output_type=str,
        instructions=system_message,
    )

    try:
        result = await extraction_agent.run("请提取地域意向", model_settings={"temperature": 0})
        result_data = parse_extraction_json(result.output, CityIntentResult).model_dump()
        logger.info(
            "extract_city_intent: LLM extraction complete - province=%s, city=%s, area=%s",
            result_data["province"],
            result_data["city"],
            result_data["area"],
        )
        result_json = json.dumps(result_data, ensure_ascii=False)

        return result_json
    except Exception:
        logger.exception("extract_city_intent: LLM extraction failed")
        raise


async def extract_negative_city_intent(
    ctx: RunContext[RequestContext],
    **kwargs,
) -> str:
    """从对话历史中提取学生对报考地域的负面意向。

    根据当前对话历史，识别学生提到的省份和城市，提取负面意向。

    Returns:
        JSON string with province, city fields
    """
    chat_history = ctx.deps.chat_history
    score_detail = ctx.deps.score_detail

    logger.info(
        "extract_negative_city_intent called: chat_history_len=%d, has_score_detail=%s",
        len(chat_history) if chat_history else 0,
        score_detail is not None,
    )

    if not chat_history:
        logger.warning("extract_negative_city_intent: chat_history is empty, returning empty result")
        return json.dumps({"province": [], "city": []}, ensure_ascii=False)

    # Format student info
    student_info = _format_student_info(score_detail)
    logger.info("extract_negative_city_intent: student_info=%s", student_info)

    # Trim to last N messages
    config = _get_extract_config()
    trimmed_history = trim_last_n_messages(chat_history, config.last_n_messages)
    logger.info(
        "extract_negative_city_intent: trimmed chat_history from %d to %d messages (last_n=%d)",
        len(chat_history), len(trimmed_history), config.last_n_messages,
    )

    # Format chat history
    chat_history_str = format_messages(trimmed_history)

    # Build extraction prompt
    system_message = _build_negative_system_message(chat_history_str, student_info)
    logger.debug("extract_negative_city_intent: system_message length=%d", len(system_message))

    # Create temporary agent for extraction
    llm_client = _get_extraction_client()
    logger.info("extract_negative_city_intent: calling LLM for extraction...")

    extraction_agent = Agent(
        model=llm_client.model,
        output_type=str,
        instructions=system_message,
    )

    try:
        result = await extraction_agent.run("请提取负面地域意向", model_settings={"temperature": 0})
        result_data = parse_extraction_json(result.output, NegativeCityIntentResult).model_dump()
        logger.info(
            "extract_negative_city_intent: LLM extraction complete - province=%s, city=%s",
            result_data["province"],
            result_data["city"],
        )
        result_json = json.dumps(result_data, ensure_ascii=False)

        return result_json
    except Exception:
        logger.exception("extract_negative_city_intent: LLM extraction failed")
        raise
