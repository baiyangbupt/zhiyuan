"""Major intent extraction tool."""

import json
import logging

from pydantic_ai import Agent, RunContext

from app.agent.context import RequestContext
from app.config import ExtractConfig, LLMConfig
from app.data.major_data import (
    associate_category_line_map,
    associate_major_line_map,
    associate_major_lines,
    associate_major_mappings,
    associate_subcategory_line_map,
    bachelor_category_line_map,
    bachelor_major_line_map,
    bachelor_major_lines,
    bachelor_major_mappings,
    bachelor_subcategory_line_map,
    prefix_to_associate_major,
    prefix_to_bachelor_major,
)
from app.data.major_utils import filter_major_hierarchy_by_prefix
from app.data.message_utils import format_messages, trim_last_n_messages
from app.llm.client import LLMClient
from app.schemas.major_intent import MajorIntentResult, NegativeMajorIntentResult
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


def _build_system_message_bachelor(chat_history: list[dict], major_data_str: str) -> str:
    """Build system message for bachelor major extraction."""
    chat_history_str = format_messages(chat_history)

    system_message = f"""
# 【任务背景】
你是一个专业的高考专业实体抽取工具，需要从学生的对话中，识别出学生的正面意向专业或专业类。

# 【对话历史】
{chat_history_str}

# 【任务规则】
1.从【对话历史】中抽取学生明确表达的所有正面意向专业，去重后存入allkeys。抽取时需要满足以下条件：
- 正面意向包括学生自己感兴趣、可以考虑、可以接受、想学、喜欢等正面态度，也包括增加、添加、补充、排序靠前、放前面等志愿修改动作。"不确定"、"不知道"、"再想想"、"再看看"等中性表达不能作为正面意向。
- 若学生明确对规划师或系统推荐的专业表达了正向意愿，则将其进行抽取；否则忽略推荐的专业，不需要进行抽取。例如"上面推荐的都感兴趣"，则需要将推荐的专业抽取出来。
- 一个专业不能既是正面意向又是负面意向，若无法判断则跳过不进行处理。若学生对某专业的态度发生变化，按照学生最后一次对该专业表达的态度进行抽取。
- 在整个过程中，时刻记住必须抽取学生最后一次明确表达正面意向的专业，其他意向的专业都不要，一旦发现识别错误立刻纠正结果。
2.将allkeys中学生的正面意向专业，从【专业层级结构】给定的选项中匹配专业层级。其中，无缩进的行是第一级专业门类；缩进2个空格的行是所有第二级专业类；缩进4个空格的行是每个专业类下对应的所有三级具体专业。匹配时需要满足以下条件：
- **重要**：如果学生表述的专业词汇恰好是某个一级专业门类名称（在【专业层级结构】中无缩进的行，如"医学"、"法学"、"工学"、"文学"、"理学"、"农学"等），且学生没有指定更具体的专业类或专业，则将该门类名称存入level1。例如，学生说"我喜欢医学"，在层级结构中找到无缩进的"医学"行，应存入level1，而不是匹配到"医学影像学"等具体专业。
- 如果学生表述的专业词汇能匹配到第二级专业类（缩进2空格的行），将匹配到的专业名称存入level2。
- 如果无法匹配到一级门类或二级专业类，再尝试匹配第三级具体专业（缩进4空格的行），将匹配到的专业名称存入level3。
- 同一个专业词语只能匹配为一个层级，不能同时出现在多个层级中。优先匹配最高适用层级：先尝试level1（无缩进），再level2（2空格缩进），最后level3（4空格缩进）。
- 如果学生表述某专业时含"类"、"方向"、"领域"、"这种"、"这些"等泛化词描述，或明确说"xx类"，或根据语义描述是指专业类，则将其匹配为二级专业类。
- 若是简写的专业名称，需要匹配到完整名称。例如"公管类"应该匹配为"公共管理类"；"新传类"应该匹配为"新闻传播学类"等。
- 不存在或者匹配不到的专业不做处理。
- 如果学生对某专业类下的所有专业表达了正面态度，不管有没有具体表达接受哪些三级专业，只需要将该专业类存入level2，其对应的三级专业都不用存入level3中。例如，学生可以接受教育学类，那么只将教育学类存入level2，但是教育学类下的教育学、家庭教育、学前教育等所有具体专业都不要存入level3。
- 如果学生只对某个专业类下的若干专业表达了正面态度，只需要将该三级专业存入level3，其对应的二级专业类不能存入level2中。例如，在计算机类中，学生考虑学习软件工程和网络空间安全专业，那么只将软件工程、网络空间安全存入level3，但是其对应的二级计算机类不要存入level2。
- 同理，如果学生说的是某个一级门类（如"医学"），但没有进一步说明具体哪个专业类，则只存入level1，不要展开到level2或level3。
3.输出结果之前，请再次思考并检查是否有遗漏或者错误匹配的情况，并进行改正。

# 特殊案例
1.在匹配专业层级的时候，如果出现以下相似表述的二级专业类和三级专业，只能匹配和保留其中一个专业，需要根据上下文语义进行区分：
"计算机类"和"计算机科学与工程"、"历史学类"和"历史学"、"自动化类"和"自动化"、"经济学类"和"经济学"、"财政学类"和"财政学"、"金融学类"和"金融学"、
"法学类"和"法学"、"社会学类"和"社会学"、"马克思主义理论类"和"马克思主义理论"、"教育学类"和"教育学"、"数学类"和"数学与应用数学"、"物理学类"和"物理学"、
"化学类"和"化学"、"地理科学类"和"地理科学"、"大气科学类"和"大气科学"、"海洋科学类"和"海洋科学"、"地球物理学类"和"地球物理学"、"地质学类"和"地质学"、
"生物科学类"和"生物科学"、"心理学类"和"心理学"、"统计学类"和"统计学"、"能源动力类"和"能源与动力工程"、"交通运输类"和"交通运输"、"航空航天类"和"航空航天工程"、
"农业工程类"和"农业工程"、"环境科学与工程类"和"环境科学与工程"、"生物医学工程类"和"生物医学工程"、"食品科学与工程类"和"食品科学与工程"、"建筑类"和"建筑学"、
"生物工程类"和"生物工程"、"交叉工程类"和"交叉工程"、"动物医学类"和"动物医学"、"林学类"和"林学"、"基础医学类"和"基础医学"、"临床医学类"和"临床医学"、
"中医学类"和"中医学"、"药学类"和"药学"、"中药学类"和"中药学"、"护理学类"和"护理学"、"管理科学与工程类"和"管理科学"、"工商管理类"和"工商管理"、
"农业经济管理类"和"农林经济管理"、"物流管理与工程类"和"物流管理"、"工业工程类"和"工业工程"、"电子商务类"和"电子商务"、"旅游管理类"和"旅游管理"、
2.如果识别出与"政治学、经济学与哲学"相关表述，需将其识别为整体，并匹配到三级具体专业。
3.根据输入"像教育学这类的专业，我学前教育就不要了。可以留教育学、小学教育和家庭教育。"可抽取出正面意向专业"教育学"、"小学教育"、"家庭教育"并存入level3，但存在负面专业"学前教育"，因此不能将"教育学类"存入level2。
4.根据输入"之前对护理学之类的专业不感兴趣，后来想想还是勉强可以接受的。"判断出学生最后的态度"可以接受"，从而抽取"护理学类"为学生的正面意向专业并存入level2。
5.根据输入"我还喜欢医学和法学"，"医学"和"法学"分别是一级专业门类，应存入level1。
6.根据输入"我喜欢医学"，在【专业层级结构】中找到无缩进的"医学"行，确认这是一级门类，应存入level1，而不是匹配到"医学影像学"、"医学检验技术"等具体专业。

# 【专业层级结构】
以下是所有可能的专业选项，按照层级结构展示（缩进表示层级关系，无缩进=一级门类，2空格缩进=二级专业类，4空格缩进=三级具体专业）:
```
{major_data_str}
```

# 【返回格式】
以JSON格式返回结果
{{
  "allkeys":["词汇1", "词汇2", "词汇3"],
  "level1": ["一级门类1", "一级门类2"],
  "level2": ["二级专业1", "二级专业2", "二级专业3"],
  "level3": ["三级专业1", "三级专业2", "三级专业3"]
}}

如果无法确定学生的专业正面意向，请返回空数组:
{{
  "allkeys":["词汇1", "词汇2", "词汇3"],
  "level1": [],
  "level2": [],
  "level3": []
}}
"""
    return system_message


def _build_system_message_associate(chat_history: list[dict], major_data_str: str) -> str:
    """Build system message for associate major extraction (similar to bachelor but with associate-specific examples)."""
    chat_history_str = format_messages(chat_history)
    # Using similar template as bachelor, with associate-specific special cases
    system_message = f"""
# 【任务背景】
你是一个专业的高考专业实体抽取工具，需要从学生的对话中，识别出学生的正面意向专业或专业类。

# 【对话历史】
{chat_history_str}

# 【任务规则】
1.从【对话历史】中抽取学生明确表达的所有正面意向专业，去重后存入allkeys。抽取时需要满足以下条件：
- 正面意向包括学生自己感兴趣、可以考虑、可以接受、想学、喜欢等正面态度，也包括增加、添加、补充、排序靠前、放前面等志愿修改动作。"不确定"、"不知道"、"再想想"、"再看看"等中性表达不能作为正面意向。
- 若学生明确对规划师或系统推荐的专业表达了正向意愿，则将其进行抽取；否则忽略推荐的专业，不需要进行抽取。例如"上面推荐的都感兴趣"，则需要将推荐的专业抽取出来。
- 一个专业不能既是正面意向又是负面意向，若无法判断则跳过不进行处理。若学生对某专业的态度发生变化，按照学生最后一次对该专业表达的态度进行抽取。
- 在整个过程中，时刻记住必须抽取学生最后一次明确表达正面意向的专业，其他意向的专业都不要，一旦发现识别错误立刻纠正结果。
2.将allkeys中学生的正面意向专业，从【专业层级结构】给定的选项中匹配专业层级。其中，无缩进的行是第一级专业门类；缩进2个空格的行是所有第二级专业类；缩进4个空格的行是每个专业类下对应的所有三级具体专业。匹配时需要满足以下条件：
- 如果学生表述的专业词汇恰好是某个一级专业门类名称（如"医学"、"法学"、"工学"、"文学"等），且学生没有指定更具体的专业类或专业，则将该门类名称存入level1。
- 如果学生表述的专业词汇能匹配到第二级专业类，将匹配到的专业名称存入level2。
- 如果无法匹配到一级门类或二级专业类，再尝试匹配第三级具体专业，将匹配到的专业名称存入level3。
- 同一个专业词语只能匹配为一个层级，不能同时出现在多个层级中。优先匹配最高适用层级：先尝试level1，再level2，最后level3。
- 如果学生表述某专业时含"类"、"方向"、"领域"、"这种"、"这些"等泛化词描述，或明确说"xx类"，或根据语义描述是指专业类，则将其匹配为二级专业类。
- 若是简写的专业名称，需要匹配到完整名称。例如"财会类"应该匹配为"财务会计类"；"公管类"应该匹配为"公共管理类"；"农林牧渔类"应该匹配为"农业类"、"林业类"、"渔业类"、"畜牧业类"等。
- 不存在或者匹配不到的专业不做处理。
- 如果学生对某专业类下的所有专业表达了正面态度，不管有没有具体表达接受哪些三级专业，只需要将该专业类存入level2，其对应的三级专业都不用存入level3中。
- 如果学生只对某个专业类下的若干专业表达了正面态度，只需要将该三级专业存入level3，其对应的二级专业类不能存入level2中。
- 同理，如果学生说的是某个一级门类（如"医学"），但没有进一步说明具体哪个专业类，则只存入level1，不要展开到level2或level3。
3.输出结果之前，请再次思考并检查是否有遗漏或者错误匹配的情况，并进行改正。

# 【专业层级结构】
以下是所有可能的专业选项，按照层级结构展示（缩进表示层级关系，无缩进=一级门类，2空格缩进=二级专业类，4空格缩进=三级具体专业）:
```
{major_data_str}
```

# 【返回格式】
以JSON格式返回结果
{{
  "allkeys":["词汇1", "词汇2", "词汇3"],
  "level1": ["一级门类1", "一级门类2"],
  "level2": ["二级专业1", "二级专业2", "二级专业3"],
  "level3": ["三级专业1", "三级专业2", "三级专业3"]
}}

如果无法确定学生的专业正面意向，请返回空数组:
{{
  "allkeys":["词汇1", "词汇2", "词汇3"],
  "level1": [],
  "level2": [],
  "level3": []
}}
"""
    return system_message

def _build_negative_system_message_bachelor(chat_history: list[dict], major_data_str: str) -> str:
    """Build system message for bachelor negative major extraction."""
    chat_history_str = format_messages(chat_history)
    # Similar to positive extraction but focuses on negative intent
    system_message = f"""
# 【任务背景】
你是一个专业的高考专业实体抽取工具，需要从学生的对话中，识别出学生的负面意向专业或专业类。

# 【对话历史】
{chat_history_str}

# 【任务规则】
1.从【对话历史】中抽取学生明确表达的所有负面意向专业，去重后存入allkeys。抽取时需要满足以下条件：
- 负面意向包括学生自己不感兴趣、不考虑、不接受、不想学、不喜欢等负面态度，也包括删除、减少、去掉、排序靠后、放后面等志愿修改动作。"不确定"、"不知道"、"再想想"、"再看看"等中性表达不能作为负面意向态度。
- 若学生明确对规划师或系统推荐的专业表达了负向意愿，则将其进行抽取；否则忽略推荐的专业，不需要进行抽取。
- 一个专业不能既是正面意向又是负面意向，若无法判断则跳过不进行处理。若学生对某专业的态度发生变化，按照学生最后一次对该专业表达的态度进行抽取。
- 在整个过程中，时刻记住必须抽取学生最后一次明确表达负面意向的专业，其他意向的专业都不要，一旦发现识别错误立刻纠正结果。
2.将allkeys中学生的负面意向专业，从【专业层级结构】给定的选项中匹配专业层级。其中，无缩进的行是第一级专业门类；缩进2个空格的行是所有第二级专业类；缩进4个空格的行是每个专业类下对应的所有三级具体专业。匹配时需要满足以下条件：
- 如果学生表述的专业词汇恰好是某个一级专业门类名称（如"医学"、"法学"、"工学"、"文学"等），且学生没有指定更具体的专业类或专业，则将该门类名称存入level1。
- 优先匹配第二级专业类，将匹配到的专业名称存入level2；若无法匹配再尝试匹配第三级具体专业，将匹配到的专业名称存入level3。第二级专业都以"类"字结尾。
- 如果学生对某专业门类表达了负面态度，只存入level1，不要展开到level2或level3。
- 如果学生对某专业类表达了负面态度，不管有没有具体表达不接受哪些三级专业，只需要将该专业类存入level2，其对应的三级专业都不用存入level3中。
- 如果学生只对某个专业类下的若干专业表达了负面态度，只需要将该三级专业存入level3，其对应的二级专业类不能存入level2中。
3.输出结果之前，请再次思考并检查是否有遗漏或者错误匹配的情况，并进行改正。

# 【专业层级结构】
以下是所有可能的专业选项，按照层级结构展示（缩进表示层级关系，无缩进=一级门类，2空格缩进=二级专业类，4空格缩进=三级具体专业）:
```
{major_data_str}
```

# 【返回格式】
以JSON格式返回结果
{{
  "allkeys":["词汇1", "词汇2", "词汇3"],
  "level1": ["一级门类1", "一级门类2"],
  "level2": ["二级专业1", "二级专业2", "二级专业3"],
  "level3": ["三级专业1", "三级专业2", "三级专业3"]
}}

如果无法确定学生的专业负面意向，请返回空数组:
{{
  "allkeys":["词汇1", "词汇2", "词汇3"],
  "level1": [],
  "level2": [],
  "level3": []
}}
"""
    return system_message


def _build_negative_system_message_associate(chat_history: list[dict], major_data_str: str) -> str:
    """Build system message for associate negative major extraction."""
    # For associate majors, the negative extraction logic is the same as bachelor
    # The main difference is in the major data structure, not the extraction rules
    return _build_negative_system_message_bachelor(chat_history, major_data_str)


async def _extract_intent_common(
    ctx: RunContext[RequestContext],
    is_negative: bool,
) -> str:
    """Common extraction logic for positive and negative intent.

    Args:
        ctx: Run context with chat history and batch info
        is_negative: True for negative intent extraction, False for positive

    Returns:
        JSON string with extraction results
    """
    chat_history = ctx.deps.chat_history
    batch = ctx.deps.batch
    intent_type = "negative" if is_negative else "positive"
    func_name = f"extract_{'negative_' if is_negative else ''}major_intent"

    logger.info(
        "%s called: chat_history_len=%d, batch=%s",
        func_name,
        len(chat_history) if chat_history else 0,
        batch,
    )

    if not chat_history:
        logger.warning("%s: chat_history is empty, returning empty result", func_name)
        return json.dumps({"allkeys": [], "level2": [], "level3": []}, ensure_ascii=False)

    # Determine major type (bachelor or associate)
    is_bachelor = batch is None or batch == "" or batch == "01"

    if is_bachelor:
        # Bachelor
        major_lines = bachelor_major_lines
        category_line_map = bachelor_category_line_map
        subcategory_line_map = bachelor_subcategory_line_map
        major_line_map = bachelor_major_line_map
        prefix_index = prefix_to_bachelor_major
        mappings = bachelor_major_mappings
        build_message_func = _build_negative_system_message_bachelor if is_negative else _build_system_message_bachelor
        output_schema = NegativeMajorIntentResult if is_negative else MajorIntentResult
        logger.info("%s: using bachelor majors", func_name)
    else:
        # Associate
        major_lines = associate_major_lines
        category_line_map = associate_category_line_map
        subcategory_line_map = associate_subcategory_line_map
        major_line_map = associate_major_line_map
        prefix_index = prefix_to_associate_major
        mappings = associate_major_mappings
        build_message_func = _build_negative_system_message_associate if is_negative else _build_system_message_associate
        output_schema = NegativeMajorIntentResult if is_negative else MajorIntentResult
        logger.info("%s: using associate majors", func_name)

    # Filter major hierarchy by prefix
    filtered_hierarchy = filter_major_hierarchy_by_prefix(
        chat_history,
        prefix_index,
        major_lines,
        category_line_map,
        subcategory_line_map,
        major_line_map,
        mappings['level2_to_level1'],
        mappings['level3_to_level2'],
    )
    logger.info("%s: filtered hierarchy length=%d", func_name, len(filtered_hierarchy))

    # Trim to last N messages
    config = _get_extract_config()
    trimmed_history = trim_last_n_messages(chat_history, config.last_n_messages)
    logger.info(
        "%s: trimmed chat_history from %d to %d messages",
        func_name, len(chat_history), len(trimmed_history),
    )

    # Build extraction prompt
    system_message = build_message_func(trimmed_history, filtered_hierarchy)
    logger.debug("%s: system_message length=%d", func_name, len(system_message))

    # Create temporary agent for extraction
    llm_client = _get_extraction_client()
    logger.info("%s: calling LLM for extraction...", func_name)

    extraction_agent = Agent(
        model=llm_client.model,
        output_type=str,
        instructions=system_message,
    )

    prompt = f"请提取{'负面' if is_negative else ''}专业意向"

    try:
        result = await extraction_agent.run(prompt, model_settings={"temperature": 0})
        result_data = parse_extraction_json(result.output, output_schema).model_dump()
        logger.info(
            "%s: LLM extraction complete - allkeys=%s, level1=%s, level2=%s, level3=%s",
            func_name,
            result_data["allkeys"],
            result_data.get("level1", []),
            result_data["level2"],
            result_data["level3"],
        )
        result_json = json.dumps(result_data, ensure_ascii=False)

        return result_json
    except Exception:
        logger.exception("%s: LLM extraction failed", func_name)
        raise


async def extract_major_intent(
    ctx: RunContext[RequestContext],
    **kwargs,
) -> str:
    """从对话历史中提取学生的专业意向。

    根据当前对话历史，识别学生提到的专业名称，区分大类（level2）和具体专业（level3）。

    Returns:
        JSON string with extraction results containing allkeys, level2, and level3
    """
    return await _extract_intent_common(ctx, is_negative=False)


async def extract_negative_major_intent(
    ctx: RunContext[RequestContext],
    **kwargs,
) -> str:
    """从对话历史中提取学生的负面专业意向。

    识别学生明确表示不感兴趣、不考虑的专业。

    Returns:
        JSON string with extraction results containing allkeys, level2, and level3
    """
    return await _extract_intent_common(ctx, is_negative=True)
