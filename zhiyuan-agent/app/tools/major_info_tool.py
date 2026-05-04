"""Major introduction tool.

Retrieves detailed information about a specific major or major category.
"""

import logging
from typing import Any

from pydantic_ai import RunContext

from app.agent.context import RequestContext
from app.data.major_data import (
    associate_level2_id_map,
    associate_level2_labels,
    associate_level3_id_map,
    associate_level3_labels,
    bachelor_level2_id_map,
    bachelor_level2_labels,
    bachelor_level3_id_map,
    bachelor_level3_labels,
)
from app.util.internal_client import (
    get_major_category_profile,
    get_major_profile,
    get_planning_draft,
    get_planning_ordered_plan,
    query_planning_candidate_pool,
)

logger = logging.getLogger(__name__)
_DEFAULT_TENANT_ID = 1


async def get_major_introduction(
    ctx: RunContext[RequestContext],
    major_name: str,
) -> str:
    """获取专业或专业类的详细介绍，包括培养目标、知识体系、课程、就业方向及个性化分析。

    Args:
        ctx: 运行上下文
        major_name: 专业名称，如"软件工程"或"计算机类"

    Returns:
        专业介绍文本
    """
    # Strip trailing "专业"
    if major_name.endswith("专业"):
        major_name = major_name[:-2]

    logger.info("get_major_introduction called: major_name=%s", major_name)

    # Select data based on batch (bachelor vs associate)
    batch = ctx.deps.batch
    is_bachelor = batch is None or batch == "" or batch == "01"

    if is_bachelor:
        level3_labels = bachelor_level3_labels
        level3_id_map = bachelor_level3_id_map
        level2_labels = bachelor_level2_labels
        level2_id_map = bachelor_level2_id_map
    else:
        level3_labels = associate_level3_labels
        level3_id_map = associate_level3_id_map
        level2_labels = associate_level2_labels
        level2_id_map = associate_level2_id_map

    session_id = ctx.deps.sessionid

    # Check level3 (specific major)
    if major_name in level3_labels:
        try:
            major_info = await get_major_profile(major_name)
            train_demand = major_info.get("trainDemand", "")
            knowledge = major_info.get("knowledge", "")
            course = major_info.get("course", "")
            job_orientation = major_info.get("jobOrientation", "")

            analysis_result = ""
            major_id = level3_id_map.get(major_name)
            if major_id:
                analysis_result = await _get_analysis_summary(
                    session_id, major_id, 3, major_name
                )

            return (
                f"{major_name}专业的培养目标：{train_demand}\n"
                f"{major_name}专业的知识体系：{knowledge}\n"
                f"{major_name}专业的课程体系：{course}\n"
                f"{major_name}专业的就业方向：{job_orientation}"
                f"{analysis_result}"
                "\n\n[数据来源]\n- 数据源：教育部专业目录、高校官方培养方案"
            )
        except Exception:
            logger.exception("获取专业信息失败: %s", major_name)
            return f"获取{major_name}专业信息时发生错误，请稍后重试。"

    # Check level2 (major category)
    if major_name in level2_labels:
        try:
            major_info = await get_major_category_profile(major_name)
            overview = major_info.get("majorOverview", "")
            study_courses = major_info.get("studyCourses", "")
            employment_direction = major_info.get("employmentDirection", "")

            analysis_result = ""
            major_id = level2_id_map.get(major_name)
            if major_id:
                analysis_result = await _get_analysis_summary(
                    session_id, major_id, 2, major_name
                )

            return (
                f"{major_name}的专业介绍：{overview}\n"
                f"{major_name}的学习课程：{study_courses}\n"
                f"{major_name}的就业方向：{employment_direction}"
                f"{analysis_result}"
                "\n\n[数据来源]\n- 数据源：教育部专业目录、高校官方培养方案"
            )
        except Exception:
            logger.exception("获取专业类信息失败: %s", major_name)
            return f"获取{major_name}专业类信息时发生错误，请稍后重试。"

    # Not found
    return f"关于{major_name}，暂未找到匹配的标准专业，你可以根据自身知识进行回答。"


def _extract_plan_items(response: dict[str, Any]) -> list[dict[str, Any]]:
    return (response.get("data") or {}).get("items") or []


def _format_ratio(value: Any) -> str:
    if value is None:
        return "-"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "-"
    if numeric < 0:
        return "-"
    return f"{int(numeric)}%" if numeric.is_integer() else f"{numeric:.1f}%"


def _matches_major_item(
    item: dict[str, Any],
    major_id: str,
    level: int,
    major_name: str,
) -> bool:
    item_major_name = str(item.get("majorName") or "")
    if major_name and major_name in item_major_name:
        return True

    if not major_id:
        return False

    item_major_id = str(item.get("majorId") or "")
    item_level2_id = str(item.get("majorSubCategoryId") or "")
    item_level1_id = str(item.get("majorCategoryId") or "")
    target_id = str(major_id)

    if level == 3:
        return item_major_id == target_id
    if level == 2:
        return item_level2_id == target_id
    if level == 1:
        return item_level1_id == target_id
    return False


def _build_plan_snippet(item: dict[str, Any]) -> str:
    school_name = item.get("schoolName") or "未知院校"
    major_name = item.get("majorName") or "未知专业"
    tier = item.get("tier") or "未知"
    ratio = _format_ratio(item.get("admissionRatio"))
    return f"{school_name} - {major_name}（{tier}档，录取率{ratio}）"


def _build_candidate_snippet(item: dict[str, Any]) -> str:
    school_name = item.get("schoolName") or "未知院校"
    major_name = item.get("majorName") or "未知专业"
    tier = item.get("tier") or "未知"
    ratio = _format_ratio(item.get("admissionRatio"))
    return f"{school_name} - {major_name}（{tier}档，录取率{ratio}）"


async def _load_current_plan(session_id: str) -> tuple[str, list[dict[str, Any]]]:
    ordered_result = await get_planning_ordered_plan(session_id)
    ordered_items = _extract_plan_items(ordered_result)
    if ordered_result.get("code") == 0 and ordered_items:
        return "当前排序方案", ordered_items

    draft_result = await get_planning_draft(session_id)
    draft_items = _extract_plan_items(draft_result)
    if draft_result.get("code") == 0 and draft_items:
        return "当前草稿方案", draft_items

    return "当前方案", []


async def _query_major_candidates(
    session_id: str,
    major_id: str,
    level: int,
    major_name: str,
) -> dict[str, Any]:
    request_kwargs: dict[str, Any] = {
        "page": 1,
        "page_size": 20,
        "sort_field": "finalScore",
        "sort_order": "desc",
    }

    if level == 2:
        request_kwargs["major_tags"] = [major_name]
    else:
        request_kwargs["major_keywords"] = [major_name]

    result = await query_planning_candidate_pool(
        _DEFAULT_TENANT_ID,
        session_id,
        **request_kwargs,
    )

    # 兼容标签过滤未命中但名称检索可命中的情况。
    items = (result.get("data") or {}).get("items") or []
    if items or level != 2:
        return result

    return await query_planning_candidate_pool(
        _DEFAULT_TENANT_ID,
        session_id,
        page=1,
        page_size=20,
        sort_field="finalScore",
        sort_order="desc",
        major_keywords=[major_name],
    )


async def _get_analysis_summary(
    session_id: str, major_id: str, level: int, major_name: str
) -> str:
    """Build V2 analysis summary from current plan and candidate pool."""
    try:
        plan_title, plan_items = await _load_current_plan(session_id)
        matched_plan_items = [
            item for item in plan_items if _matches_major_item(item, major_id, level, major_name)
        ]

        candidate_result = await _query_major_candidates(session_id, major_id, level, major_name)
        candidate_data = candidate_result.get("data") or {}
        candidate_items = candidate_data.get("items") or []
        candidate_total = candidate_data.get("total") or 0

        lines: list[str] = ["\n\n该专业针对当前用户的分析结果："]

        if matched_plan_items:
            lines.append(f"- {plan_title}中命中 {len(matched_plan_items)} 个相关志愿：")
            for item in matched_plan_items[:3]:
                lines.append(f"  - {_build_plan_snippet(item)}")
        else:
            lines.append(f"- {plan_title}里暂时没有命中“{major_name}”相关志愿。")

        if candidate_result.get("code") == 0 and candidate_items:
            lines.append(f"- 当前候选里还有 {candidate_total} 个相关机会，示例：")
            for item in candidate_items[:3]:
                lines.append(f"  - {_build_candidate_snippet(item)}")
        elif candidate_result.get("code") == 0:
            lines.append(f"- 当前候选里暂时没有筛到“{major_name}”相关机会。")
        else:
            lines.append("- 当前候选机会暂时查询失败。")

        return "\n".join(lines)
    except Exception:
        logger.exception("构建专业分析摘要失败: %s", major_name)
    return ""
