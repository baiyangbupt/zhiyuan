"""School recommendation tool.

Gets personalized school and major recommendations based on student profile.
"""

import logging

from pydantic_ai import RunContext

from app.agent.context import RequestContext
from app.util.internal_client import get_school_majors_recommend

logger = logging.getLogger(__name__)


async def get_school_recommendations(
    ctx: RunContext[RequestContext],
) -> str:
    """基于学生画像获取个性化学校和专业推荐。

    Returns:
        学校专业推荐文本
    """
    session_id = ctx.deps.sessionid
    logger.info("get_school_recommendations called: session_id=%s", session_id)

    try:
        result = await get_school_majors_recommend(1, session_id)
        logger.info("get_school_majors_recommend result: %s", result)

        if not result or "schoolList" not in result:
            return "暂时没有找到合适的学校和专业推荐"

        school_list = result["schoolList"]
        if not school_list:
            return "暂时没有找到合适的学校和专业推荐"

        output_lines = ["根据您的条件，为您推荐以下学校和专业：\n"]

        for i, school in enumerate(school_list, 1):
            school_name = school.get("schoolName", "未知学校")
            major_list = school.get("majorList", [])

            output_lines.append(f"{i}. **{school_name}**")

            if major_list:
                for major_info in major_list:
                    if "(" in major_info and ")" in major_info:
                        start_idx = major_info.rfind("(")
                        end_idx = major_info.rfind(")")
                        if start_idx < end_idx:
                            majors = major_info[start_idx + 1 : end_idx]
                            output_lines.append(f"   推荐专业：{majors}")
                        else:
                            output_lines.append(f"   推荐专业：{major_info}")
                    else:
                        output_lines.append(f"   推荐专业：{major_info}")
            else:
                output_lines.append("   暂无专业信息")

            output_lines.append("")

        output_lines.append("以上是根据您的情况推荐的学校和专业，请尽快查看。")

        result_text = "\n".join(output_lines)
        result_text += "\n\n[数据来源]\n- 数据源：高校招生计划及历年录取数据"
        return result_text

    except Exception:
        logger.exception("获取学校专业推荐失败")
        return "获取学校专业推荐时发生错误，请稍后重试。"
