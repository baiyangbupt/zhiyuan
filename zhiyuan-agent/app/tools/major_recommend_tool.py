"""Major recommendation tool.

Gets personalized major recommendations based on student profile and generates
an LLM-powered summary.
"""

import logging

from pydantic_ai import Agent, RunContext

from app.agent.context import RequestContext
from app.config import LLMConfig
from app.data.student_info_mappings import build_studentinfo_async
from app.llm.client import LLMClient
from app.util.internal_client import get_majors_recommend
from app.util.rank_client import rank_client

logger = logging.getLogger(__name__)

_llm_client: LLMClient | None = None


def _get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient(LLMConfig())
    return _llm_client


async def get_major_recommendations(
    ctx: RunContext[RequestContext],
) -> str:
    """基于学生画像获取个性化专业推荐，并生成总结分析。

    Returns:
        专业推荐总结文本
    """
    session_id = ctx.deps.sessionid
    logger.info("get_major_recommendations called: session_id=%s", session_id)

    try:
        result = await get_majors_recommend(1, session_id)
        logger.info("get_majors_recommend result: %s", result)

        if not result:
            return "暂时没有找到合适的专业推荐"

        major_list = result.get("majorList", [])
        if not major_list:
            return "暂时没有找到合适的专业推荐"

        # Get sex name from score_detail
        sex_name = "学生"
        if ctx.deps.score_detail and ctx.deps.score_detail.sex:
            sex_name = ctx.deps.score_detail.sex

        return await _summarize_recommendations(major_list, sex_name)

    except Exception:
        logger.exception("获取专业推荐失败")
        return "获取专业推荐时发生错误，请稍后重试。"


async def _summarize_recommendations(
    major_list: list[dict],
    sex_name: str,
) -> str:
    """Generate an LLM-powered summary of major recommendations."""
    major_info_lines = []
    for item in major_list:
        major = item.get("major", "未知专业")
        gender_index = item.get("gender_index", 0)
        satisfy_index = item.get("satisfy_index", 0)
        salary_avg = item.get("salary_avg", 0)
        hot_index = item.get("hot_index", 0)
        major_info_lines.append(
            f"{major}的性别指数：{gender_index}，专业满意度指数：{satisfy_index}，"
            f"平均薪酬指数：{salary_avg}，专业热度指数：{hot_index}。"
        )

    major_info_text = "\n".join(major_info_lines)

    prompt = (
        f"你是专业的高考志愿规划师，请根据以下专业推荐的维度及得分，对推荐结果做总结。"
        f"请只用文字形式进行分条叙述，不能使用给出的具体得分。\n"
        f"性别指数：衡量某个专业（类）中{sex_name}性别比例的偏向程度，"
        f"用于反映该专业（类）的性别分布特征。\n"
        f"专业满意度指数：反映学生对所学专业（类）的整体满意程度，"
        f"由毕业生对本专业（类）的办学条件、教学质量、就业情况以及综合情况进行实名打分计算得到。\n"
        f"平均薪酬指数：衡量该专业（类）毕业生在毕业一定年限后的平均月薪水平，"
        f"反映专业（类）的经济回报。\n"
        f"专业热度指数：衡量某个专业（类）在报考学生中的受欢迎程度或报考热度，"
        f"反映社会认知和趋势。\n\n"
        f"专业推荐结果如下：\n{major_info_text}"
    )

    summary_agent = Agent(
        model=_get_llm_client().model,
        output_type=str,
        instructions="你是一个专业的高考志愿规划师，擅长根据各项指标对专业推荐结果做总结。",
    )
    result = await summary_agent.run(prompt, model_settings={"temperature": 0})
    result_text = result.output
    result_text += (
        "\n\n[数据来源]\n- 数据源：高校毕业生就业调查数据、招生报考统计"
        "\n- 计算方法：多维指标加权推荐模型"
    )
    return result_text


async def get_major_recommendations_adhoc(
    ctx: RunContext[RequestContext],
    province: str,
    total_score: int,
    subjects: list[str],
    sex: str,
    strength_subjects: list[str],
) -> str:
    """为指定学生信息（非当前用户）推荐适合的专业类。

    当用户咨询他人的专业推荐时使用此工具。
    调用前必须确保已收集到省份、总分、选科、性别和优势学科信息。

    Args:
        province: 省份名称，如"河北"
        total_score: 高考总分
        subjects: 选科列表，如["物理","化学","生物"]
        sex: 性别，"男"或"女"
        strength_subjects: 优势学科列表（擅长的科目），如["数学","物理","化学"]
    """
    logger.info(
        "get_major_recommendations_adhoc called: province=%s, score=%s, subjects=%s, sex=%s, strength=%s",
        province, total_score, subjects, sex, strength_subjects,
    )

    try:
        studentinfo = await build_studentinfo_async(
            province, total_score, subjects, sex,
            strength_subjects=strength_subjects,
        )
        result = await rank_client.recommend_submajor(studentinfo, top_n=8)
        logger.info("recommend_submajor adhoc result: %s", result)

        if not result or "error" in result:
            return "暂时没有找到合适的专业推荐，请检查输入信息是否正确。"

        major_list = result.get("reconmandlist", [])
        if not major_list:
            return "暂时没有找到合适的专业推荐"

        return await _summarize_recommendations(major_list, sex)

    except ValueError as e:
        return f"输入信息有误：{e}"
    except Exception:
        logger.exception("adhoc 专业推荐失败")
        return "获取专业推荐时发生错误，请稍后重试。"
