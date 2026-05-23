"""Major comparison tool.

Compares two majors across multiple dimensions (gender index, satisfaction,
salary, popularity) and generates an LLM-powered summary.
"""

import logging

from pydantic_ai import Agent, RunContext

from app.agent.context import RequestContext
from app.config import LLMConfig
from app.data.major_data import (
    associate_level3_id_map,
    associate_level3_labels,
    bachelor_level3_id_map,
    bachelor_level3_labels,
    prefix_to_associate_major,
    prefix_to_bachelor_major,
)
from app.data.major_utils import fuzzy_match_major_name
from app.data.student_info_mappings import build_studentinfo_async
from app.llm.client import LLMClient
from app.util.code_enrichment import resolve_major_names_async
from app.util.internal_client import query_volunteer_analysis_weight
from app.util.rank_client import rank_client

logger = logging.getLogger(__name__)

_llm_client: LLMClient | None = None


def _get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient(LLMConfig())
    return _llm_client


async def compare_majors(
    ctx: RunContext[RequestContext],
    major_name1: str,
    major_name2: str,
) -> str:
    """对比两个专业在性别指数、满意度、薪酬、热度等维度的差异，并给出总结分析。

    Args:
        ctx: 运行上下文
        major_name1: 第一个专业名称
        major_name2: 第二个专业名称

    Returns:
        对比分析文本
    """
    logger.info("compare_majors called: %s vs %s", major_name1, major_name2)

    batch = ctx.deps.batch
    is_bachelor = batch is None or batch == "" or batch == "01"

    if is_bachelor:
        level3_labels = bachelor_level3_labels
        level3_id_map = bachelor_level3_id_map
        prefix_index = prefix_to_bachelor_major
    else:
        level3_labels = associate_level3_labels
        level3_id_map = associate_level3_id_map
        prefix_index = prefix_to_associate_major

    session_id = ctx.deps.sessionid

    try:
        # Resolve fuzzy names
        if major_name1 not in level3_labels:
            major_name1 = await _resolve_major_name(
                major_name1, level3_labels, prefix_index, "01" if is_bachelor else "02"
            )
            logger.info("专业1匹配结果: %s", major_name1)

        if major_name2 not in level3_labels:
            major_name2 = await _resolve_major_name(
                major_name2, level3_labels, prefix_index, "01" if is_bachelor else "02"
            )
            logger.info("专业2匹配结果: %s", major_name2)

        # Look up IDs
        major_code1 = level3_id_map.get(major_name1)
        major_code2 = level3_id_map.get(major_name2)

        if not major_code1 or not major_code2:
            missing = major_name1 if not major_code1 else major_name2
            return f"抱歉，未能找到{missing}的专业信息，无法进行对比。"

        # Query analysis weights
        weights1 = await query_volunteer_analysis_weight(
            1,
            session_id,
            [{"major_id": major_code1, "major_level": 3, "major_name": major_name1}],
        )
        weights2 = await query_volunteer_analysis_weight(
            1,
            session_id,
            [{"major_id": major_code2, "major_level": 3, "major_name": major_name2}],
        )

        logger.info("专业1权重数据: %s", weights1)
        logger.info("专业2权重数据: %s", weights2)

        if not _has_major_weight_data(weights1) or not _has_major_weight_data(weights2):
            return _build_missing_weight_data_comparison(major_name1, major_name2)

        # Generate comparison summary
        return await _summarize_comparison(
            major_name1, major_name2, weights1, weights2
        )

    except Exception:
        logger.exception("专业对比失败: %s vs %s", major_name1, major_name2)
        return f"抱歉，对比{major_name1}和{major_name2}时发生错误，请稍后重试。"


def _has_major_weight_data(weights: dict) -> bool:
    querylist = weights.get("querylist")
    if not isinstance(querylist, list) or not querylist:
        return False
    first = querylist[0]
    if not isinstance(first, dict):
        return False
    return any(
        key in first
        for key in (
            "gender_index",
            "satisfy_index",
            "salary_avg",
            "hot_index",
            "major_score",
            "major_score_new",
        )
    )


def _build_missing_weight_data_comparison(major_name1: str, major_name2: str) -> str:
    return (
        f"暂时没有拿到当前会话可用的个性化量化权重数据，所以不能按系统评分判断{major_name1}和{major_name2}谁更高。"
        "这轮请只做通用维度比较：就业路径、考公/国企岗位覆盖、证书或升学门槛、起薪稳定性、长期上限和试错成本；"
        "如果用户补充分数、选科、地域和性别信息，可以再做个性化对比。"
    )


async def _resolve_major_name(
    origin_name: str,
    level3_labels: set[str],
    prefix_index: dict[str, list[str]],
    batch: str = "01",
) -> str:
    """Resolve a potentially fuzzy major name to a standard name."""
    normalized_candidates = await resolve_major_names_async([origin_name], "level3", batch)
    normalized_name = normalized_candidates[0] if normalized_candidates else origin_name
    if normalized_name in level3_labels:
        return normalized_name

    candidates = fuzzy_match_major_name(origin_name, level3_labels, prefix_index)

    if not candidates:
        return origin_name
    if len(candidates) == 1:
        return candidates[0]

    # Use LLM to pick the best match
    candidate_text = "\n".join(candidates)
    matching_agent = Agent(
        model=_get_llm_client().model,
        output_type=str,
        instructions=(
            "你是一个专业名称匹配专家。根据用户提供的专业名称（可能不是标准表述），"
            "从候选列表中返回最匹配的标准专业名称。只返回专业名称本身，不要返回其他内容。"
        ),
    )
    result = await matching_agent.run(
        f"用户输入的专业名称：{origin_name}\n候选专业：\n{candidate_text}\n请返回最匹配的标准专业名称。",
        model_settings={"temperature": 0},
    )
    return result.output.strip()


async def _summarize_comparison(
    major_name1: str,
    major_name2: str,
    weights1: dict,
    weights2: dict,
) -> str:
    """Generate an LLM-powered comparison summary."""
    gender_flag = weights1.get("gender_flag", "男生")

    querylist1 = weights1.get("querylist", [{}])
    q1 = querylist1[0] if querylist1 else {}
    querylist2 = weights2.get("querylist", [{}])
    q2 = querylist2[0] if querylist2 else {}

    gender_index1 = q1.get("gender_index", 0)
    satisfy_index1 = q1.get("satisfy_index", 0)
    salary_avg1 = q1.get("salary_avg", 0)
    hot_index1 = q1.get("hot_index", 0)
    major_score1 = q1.get("major_score", 0)
    major_score_new1 = q1.get("major_score_new", 0)
    major_remark1 = q1.get("major_remark", "")

    gender_index2 = q2.get("gender_index", 0)
    satisfy_index2 = q2.get("satisfy_index", 0)
    salary_avg2 = q2.get("salary_avg", 0)
    hot_index2 = q2.get("hot_index", 0)
    major_score2 = q2.get("major_score", 0)
    major_score_new2 = q2.get("major_score_new", 0)
    major_remark2 = q2.get("major_remark", "")

    remark1_text = (
        f"【由于{major_name1}属于学生的{major_remark1}，其最终得分调整为{major_score_new1}。】"
        if major_remark1
        else ""
    )
    remark2_text = (
        f"【由于{major_name2}属于学生的{major_remark2}，其最终得分调整为{major_score_new2}。】"
        if major_remark2
        else ""
    )

    prompt = (
        f"你是专业的高考志愿规划师，请根据以下维度及得分，对比{major_name1}、{major_name2}的优劣，"
        f"并根据专业（类）最终得分进行总结评价。请只用文字形式进行分条叙述，不能使用给出的具体得分，仅根据得分差异进行对比。\n"
        f"性别指数：衡量某个专业（类）中{gender_flag}比例的偏向程度，用于反映该专业（类）的性别分布特征。\n"
        f"专业满意度指数：反映学生对所学专业（类）的整体满意程度，由毕业生对本专业（类）的办学条件、教学质量、就业情况以及综合情况进行实名打分计算得到。\n"
        f"平均薪酬指数：衡量该专业（类）毕业生在毕业一定年限后的平均月薪水平，反映专业（类）的经济回报。\n"
        f"专业热度指数：衡量某个专业（类）在报考学生中的受欢迎程度或报考热度，反映社会认知和趋势。\n"
        f"{major_name1}的性别指数：{gender_index1}，专业满意度指数：{satisfy_index1}，"
        f"平均薪酬指数：{salary_avg1}，专业热度指数：{hot_index1}。\n"
        f"{major_name2}的性别指数：{gender_index2}，专业满意度指数：{satisfy_index2}，"
        f"平均薪酬指数：{salary_avg2}，专业热度指数：{hot_index2}。\n"
        f"基于上述维度，通过熵权法计算得到{major_name1}的得分：{major_score1}，"
        f"{major_name2}的得分：{major_score2}。\n"
        f"{remark1_text}\n{remark2_text}"
    )

    summary_agent = Agent(
        model=_get_llm_client().model,
        output_type=str,
        instructions="你是一个专业的高考志愿规划师，擅长根据各项指标对比分析专业优劣。",
    )
    result = await summary_agent.run(prompt, model_settings={"temperature": 0})
    result_text = result.output
    result_text += (
        "\n\n[数据来源]\n- 数据源：高校毕业生就业调查数据、招生报考统计"
        "\n- 计算方法：熵权法(Entropy Weight Method)多维指标综合评分"
    )
    return result_text


async def compare_majors_adhoc(
    ctx: RunContext[RequestContext],
    major_name1: str,
    major_name2: str,
    province: str,
    total_score: int,
    subjects: list[str],
    sex: str,
    strength_subjects: list[str],
) -> str:
    """为指定学生信息（非当前用户）对比两个专业的优劣。

    当用户以他人身份咨询专业对比时使用此工具。
    调用前必须确保已收集到省份、总分、选科、性别和优势学科信息。

    Args:
        major_name1: 第一个专业名称
        major_name2: 第二个专业名称
        province: 省份名称，如"河北"
        total_score: 高考总分
        subjects: 选科列表，如["物理","化学","生物"]
        sex: 性别，"男"或"女"
        strength_subjects: 优势学科列表（擅长的科目），如["数学","物理","化学"]
    """
    logger.info(
        "compare_majors_adhoc called: %s vs %s, province=%s, score=%s",
        major_name1, major_name2, province, total_score,
    )

    # 默认使用本科数据
    level3_labels = bachelor_level3_labels
    level3_id_map = bachelor_level3_id_map
    prefix_index = prefix_to_bachelor_major

    try:
        studentinfo = await build_studentinfo_async(
            province, total_score, subjects, sex,
            strength_subjects=strength_subjects,
        )

        # Resolve fuzzy names
        if major_name1 not in level3_labels:
            major_name1 = await _resolve_major_name(
                major_name1, level3_labels, prefix_index, "01"
            )
        if major_name2 not in level3_labels:
            major_name2 = await _resolve_major_name(
                major_name2, level3_labels, prefix_index, "01"
            )

        major_code1 = level3_id_map.get(major_name1)
        major_code2 = level3_id_map.get(major_name2)

        if not major_code1 or not major_code2:
            missing = major_name1 if not major_code1 else major_name2
            return f"抱歉，未能找到{missing}的专业信息，无法进行对比。"

        # 直接调 rank-service query_weight
        queryinfo1 = {
            "type": "major",
            "querylist": [{"major_id": major_code1, "major_level": 3, "major_name": major_name1}],
        }
        queryinfo2 = {
            "type": "major",
            "querylist": [{"major_id": major_code2, "major_level": 3, "major_name": major_name2}],
        }

        weights1 = await rank_client.query_weight(studentinfo, queryinfo1)
        weights2 = await rank_client.query_weight(studentinfo, queryinfo2)

        logger.info("adhoc 专业1权重数据: %s", weights1)
        logger.info("adhoc 专业2权重数据: %s", weights2)

        if not _has_major_weight_data(weights1) or not _has_major_weight_data(weights2):
            return _build_missing_weight_data_comparison(major_name1, major_name2)

        return await _summarize_comparison(
            major_name1, major_name2, weights1, weights2
        )

    except ValueError as e:
        return f"输入信息有误：{e}"
    except Exception:
        logger.exception("adhoc 专业对比失败: %s vs %s", major_name1, major_name2)
        return f"抱歉，对比{major_name1}和{major_name2}时发生错误，请稍后重试。"
