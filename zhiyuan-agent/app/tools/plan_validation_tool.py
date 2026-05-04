"""Plan validation tools.

Public tools for validating major subject availability and plan parameter
availability against the student's profile.
"""

from __future__ import annotations

import logging

from pydantic_ai import RunContext

from app.agent.context import RequestContext
from app.util.code_enrichment import (
    get_city_codes_async,
    get_major_codes_async,
    get_province_codes_async,
    get_school_codes_async,
    resolve_major_names_async,
    resolve_school_names_async,
)
from app.util.internal_client import (
    check_major_subject_availability,
    check_plan_param_availability,
)

logger = logging.getLogger(__name__)


def _get_batch(ctx: RunContext[RequestContext]) -> str:
    """Return batch code: '01' for bachelor (default), '02' for associate."""
    return ctx.deps.batch or "01"


async def validate_major_subjects(
    ctx: RunContext[RequestContext],
    major_names: list[str],
) -> str:
    """校验专业列表与学生选科的兼容性。

    在添加专业意向前调用，确保学生的选科组合可以报考目标专业。

    Args:
        ctx: 运行上下文
        major_names: 待校验的专业名称列表（三级专业名），如["计算机科学与技术", "临床医学"]

    Returns:
        校验结果文本（通过或不通过及原因）
    """
    session_id = ctx.deps.sessionid
    batch = _get_batch(ctx)
    logger.info(
        "validate_major_subjects: session_id=%s, majors=%s", session_id, major_names,
    )

    if not major_names:
        return "未提供需要校验的专业名称。"

    try:
        normalized_major_names = await resolve_major_names_async(major_names, "level3", batch)
        codes = await get_major_codes_async(normalized_major_names, "level3", batch)
        if not codes:
            return f"未找到以下专业的编码：{'、'.join(major_names)}，请确认专业名称是否正确。"

        majors_param = {"level1": [], "level2": [], "level3": codes}
        result = await check_major_subject_availability(1, session_id, majors_param)

        if result.get("data"):
            return f"选科校验通过：{'、'.join(normalized_major_names)} 与当前选科兼容，可以填报。"
        else:
            return (
                f"选科校验不通过：由于 {'、'.join(normalized_major_names)} 的选科限制，"
                "当前选科无法填报这些专业，建议更换其他专业。"
            )
    except Exception:
        logger.exception("选科校验失败: session_id=%s", session_id)
        return "选科校验时发生错误，请稍后重试。"


async def validate_plan_params(
    ctx: RunContext[RequestContext],
    major_names: list[str] | None = None,
    school_names: list[str] | None = None,
    province_names: list[str] | None = None,
    city_names: list[str] | None = None,
) -> str:
    """校验方案参数（专业+学校+地域）是否在学生分数范围内可行。

    在调整方案意向前调用，确保新增的意向在学生分数条件下有可行的志愿组合。

    Args:
        ctx: 运行上下文
        major_names: 专业名称列表（可选）
        school_names: 学校名称列表（可选）
        province_names: 省份名称列表（可选）
        city_names: 城市名称列表（可选）

    Returns:
        校验结果文本
    """
    session_id = ctx.deps.sessionid
    batch = _get_batch(ctx)
    logger.info(
        "validate_plan_params: session_id=%s, majors=%s, schools=%s, provinces=%s, cities=%s",
        session_id, major_names, school_names, province_names, city_names,
    )

    if not any([major_names, school_names, province_names, city_names]):
        return "未提供需要校验的参数。"

    try:
        # Convert names to codes
        majors_param = None
        normalized_major_names = major_names or []
        if major_names:
            normalized_major_names = await resolve_major_names_async(major_names, "level3", batch)
            codes = await get_major_codes_async(normalized_major_names, "level3", batch)
            if codes:
                majors_param = {"level1": [], "level2": [], "level3": codes}

        normalized_school_names = school_names or []
        if school_names:
            normalized_school_names = await resolve_school_names_async(school_names)
        schools_param = await get_school_codes_async(normalized_school_names) if school_names else None
        locations_param = None
        if province_names or city_names:
            locations_param = {
                "province": await get_province_codes_async(province_names) if province_names else [],
                "city": await get_city_codes_async(city_names) if city_names else [],
            }

        result = await check_plan_param_availability(
            1, session_id, majors_param, schools_param, locations_param,
        )

        if result.get("data"):
            items = []
            if major_names:
                items.append(f"专业：{'、'.join(normalized_major_names)}")
            if school_names:
                items.append(f"学校：{'、'.join(normalized_school_names)}")
            if province_names:
                items.append(f"省份：{'、'.join(province_names)}")
            if city_names:
                items.append(f"城市：{'、'.join(city_names)}")
            return f"参数校验通过：{'; '.join(items)} 在当前分数条件下可行。"
        else:
            return (
                "参数校验不通过：根据当前分数等信息，"
                "您的意向不在方案的考虑范围内，建议调整意向。"
            )
    except Exception:
        logger.exception("参数校验失败: session_id=%s", session_id)
        return "参数校验时发生错误，请稍后重试。"
