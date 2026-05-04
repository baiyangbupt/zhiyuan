"""School introduction tool.

Retrieves detailed information about a specific school.
"""

import logging

from pydantic_ai import RunContext

from app.agent.context import RequestContext
from app.util.internal_client import analyze_schools, get_school_profile_by_name

logger = logging.getLogger(__name__)


async def get_school_introduction(
    ctx: RunContext[RequestContext],
    school_name: str,
) -> str:
    """获取学校的详细介绍，包括隶属关系、排名、特色专业、升学率等信息及个性化分析。

    Args:
        ctx: 运行上下文
        school_name: 学校名称，如"北京大学"

    Returns:
        学校介绍文本
    """
    logger.info("get_school_introduction called: school_name=%s", school_name)
    session_id = ctx.deps.sessionid

    try:
        school_info = await get_school_profile_by_name(school_name)

        if "schoolId" not in school_info:
            return f"关于{school_name}，暂未找到匹配的学校信息，你可以根据自身知识进行回答。"

        authority = school_info.get("authority", "")
        historic_authorities = school_info.get("historicAuthorities", "")
        legacy_honor = school_info.get("legacyHonor", "")
        goat_major = school_info.get("goatMajor", "")
        double_first_major = school_info.get("doubleFirstMajor", "")
        gaotu_rank = school_info.get("gaotuRank", "")
        national_specialized_major = school_info.get("nationalSpecializedMajor", "")
        first_level_master = school_info.get("firstLevelMasterStation", "")
        first_level_doctor = school_info.get("firstLevelDoctorStation", "")
        upgrade_ratio = school_info.get("upgradeRatio", "")
        postgraduate_recommend_ratio = school_info.get("postgraduateRecommendRatio", "")

        # Get analysis
        school_id = str(school_info.get("schoolId", ""))
        analysis_result = ""
        if school_id:
            analysis_result = await _get_school_analysis(
                session_id, school_id, school_name
            )

        return (
            f"{school_name}的隶属关系：{authority}\n"
            f"{school_name}的历史隶属：{historic_authorities}\n"
            f"{school_name}的历任荣誉：{legacy_honor}\n"
            f"{school_name}的特色专业：{goat_major}\n"
            f"{school_name}的双一流专业：{double_first_major}\n"
            f"{school_name}的排名：{gaotu_rank}\n"
            f"{school_name}的国家特色专业：{national_specialized_major}\n"
            f"{school_name}的硕士点：{first_level_master}\n"
            f"{school_name}的博士点：{first_level_doctor}\n"
            f"{school_name}的升学率：{upgrade_ratio}\n"
            f"{school_name}的保研率：{postgraduate_recommend_ratio}"
            f"{analysis_result}"
            "\n\n[数据来源]\n- 数据源：教育部高校数据、高校官方信息"
        )
    except Exception:
        logger.exception("获取学校信息失败: %s", school_name)
        return f"获取{school_name}学校信息时发生错误，请稍后重试。"


async def _get_school_analysis(
    session_id: str, school_id: str, school_name: str
) -> str:
    """Call analyze_schools and extract summary text."""
    try:
        result = await analyze_schools(
            tenant_id=1,
            chat_session_id=session_id,
            school_item_list=[{"id": school_id, "name": school_name}],
        )
        if result:
            analyse_list = result.get("schoolAnalyseList", [])
            if analyse_list:
                summary = analyse_list[0].get("summary", "")
                if summary:
                    return f"\n\n该学校针对当前用户的分析结果：\n{summary}"
    except Exception:
        logger.exception("调用学校分析接口失败: %s", school_name)
    return ""
