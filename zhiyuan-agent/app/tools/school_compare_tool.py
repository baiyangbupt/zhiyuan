"""School comparison tool.

Compares two schools across multiple dimensions (GDP, city level, upgrade ratio,
postgraduate ratio, school level) and generates an LLM-powered summary.
"""

import logging

from pydantic_ai import Agent, RunContext

from app.agent.context import RequestContext
from app.config import LLMConfig
from app.data.school_data import (
    area_to_associate_schools,
    area_to_bachelor_schools,
    associate_school_id_map,
    associate_school_set,
    bachelor_school_id_map,
    bachelor_school_set,
    fuzzy_match_school_name,
)
from app.data.student_info_mappings import build_studentinfo_async
from app.llm.client import LLMClient
from app.util.code_enrichment import resolve_school_names_async
from app.util.internal_client import query_school_analysis_weight
from app.util.rank_client import rank_client

logger = logging.getLogger(__name__)

_llm_client: LLMClient | None = None


def _get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient(LLMConfig())
    return _llm_client


def _allow_explore_inner_llm(request_context: RequestContext) -> bool:
    return bool(getattr(request_context, "allow_explore_inner_llm", True))


async def compare_schools(
    ctx: RunContext[RequestContext],
    school_name1: str,
    school_name2: str,
) -> str:
    """对比两个学校在省份GDP、城市等级、考研率、保研率、院校等级等维度的差异，并给出总结分析。

    Args:
        ctx: 运行上下文
        school_name1: 第一个学校名称
        school_name2: 第二个学校名称

    Returns:
        对比分析文本
    """
    logger.info("compare_schools called: %s vs %s", school_name1, school_name2)

    batch = ctx.deps.batch
    is_bachelor = batch is None or batch == "" or batch == "01"

    if is_bachelor:
        school_set = bachelor_school_set
        school_id_map = bachelor_school_id_map
        area_index = area_to_bachelor_schools
    else:
        school_set = associate_school_set
        school_id_map = associate_school_id_map
        area_index = area_to_associate_schools

    session_id = ctx.deps.sessionid

    try:
        # Resolve fuzzy names
        if school_name1 not in school_set:
            school_name1 = await _resolve_school_name(
                school_name1, school_set, area_index
            )
            logger.info("学校1匹配结果: %s", school_name1)

        if school_name2 not in school_set:
            school_name2 = await _resolve_school_name(
                school_name2, school_set, area_index
            )
            logger.info("学校2匹配结果: %s", school_name2)

        # Look up IDs
        school_id1 = school_id_map.get(school_name1)
        school_id2 = school_id_map.get(school_name2)

        if not school_id1 or not school_id2:
            missing = school_name1 if not school_id1 else school_name2
            return f"抱歉，未能找到{missing}的学校信息，无法进行对比。"

        # Query analysis weights
        weights1 = await query_school_analysis_weight(
            1,
            session_id,
            [{"school_id": school_id1, "school_name": school_name1}],
        )
        weights2 = await query_school_analysis_weight(
            1,
            session_id,
            [{"school_id": school_id2, "school_name": school_name2}],
        )

        logger.info("学校1权重数据: %s", weights1)
        logger.info("学校2权重数据: %s", weights2)

        if _allow_explore_inner_llm(ctx.deps):
            return await _summarize_comparison(
                school_name1, school_name2, weights1, weights2
            )
        return _render_school_comparison_facts(
            school_name1,
            school_name2,
            weights1,
            weights2,
        )

    except Exception:
        logger.exception("学校对比失败: %s vs %s", school_name1, school_name2)
        return f"抱歉，对比{school_name1}和{school_name2}时发生错误，请稍后重试。"


async def _resolve_school_name(
    origin_name: str,
    school_set: set[str],
    area_index: dict[str, list[str]],
) -> str:
    """Resolve a potentially fuzzy school name to a standard name."""
    normalized_candidates = await resolve_school_names_async([origin_name])
    normalized_name = normalized_candidates[0] if normalized_candidates else origin_name
    if normalized_name in school_set:
        return normalized_name

    candidates = fuzzy_match_school_name(origin_name, school_set, area_index)

    if not candidates:
        return origin_name
    if len(candidates) == 1:
        return candidates[0]

    candidate_text = "\n".join(candidates)
    matching_agent = Agent(
        model=_get_llm_client().model,
        output_type=str,
        instructions=(
            "你是一个学校名称匹配专家。根据用户提供的学校名称（可能不是标准表述），"
            "从候选列表中返回最匹配的标准学校名称。只返回学校名称本身，不要返回其他内容。"
        ),
    )
    result = await matching_agent.run(
        f"用户输入的学校名称：{origin_name}\n候选学校：\n{candidate_text}\n请返回最匹配的标准学校名称。",
        model_settings={"temperature": 0},
    )
    return result.output.strip()


def _first_weight_item(weights: dict) -> dict:
    querylist = (weights or {}).get("querylist", [])
    return querylist[0] if querylist else {}


def _numeric_weight(value) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric <= 0:
        return None
    return numeric


def _format_metric_value(value) -> str:
    numeric = _numeric_weight(value)
    if numeric is None:
        return "暂无"
    return f"{numeric:.1f}".rstrip("0").rstrip(".")


def _metric_compare_line(
    label: str,
    school_name1: str,
    school_name2: str,
    value1,
    value2,
    explanation: str,
) -> str:
    numeric1 = _numeric_weight(value1)
    numeric2 = _numeric_weight(value2)
    display = f"{school_name1} {_format_metric_value(value1)} / {school_name2} {_format_metric_value(value2)}"
    if numeric1 is None or numeric2 is None:
        return f"{label}：{display}。当前至少有一方缺少有效量化数据，适合只作定性参考。"
    if abs(numeric1 - numeric2) < 1e-6:
        return f"{label}：{display}。两者差异不明显，{explanation}"
    stronger = school_name1 if numeric1 > numeric2 else school_name2
    return f"{label}：{display}。相对看，{stronger}在这个维度更占优，{explanation}"


def _score_compare_line(school_name1: str, school_name2: str, score1, score2) -> str:
    numeric1 = _numeric_weight(score1)
    numeric2 = _numeric_weight(score2)
    display = f"{school_name1} {_format_metric_value(score1)} / {school_name2} {_format_metric_value(score2)}"
    if numeric1 is None or numeric2 is None:
        return f"综合评分：{display}。当前缺少完整个性化量化评分，不能只按分数判断哪所院校一定更适合。"
    if abs(numeric1 - numeric2) < 1e-6:
        return f"综合评分：{display}。两者综合差异不明显，建议继续看城市、专业承接、录取概率和学费成本。"
    stronger = school_name1 if numeric1 > numeric2 else school_name2
    return f"综合评分：{display}。按当前量化结果，{stronger}整体更占优，但仍要结合具体专业、录取概率和地域接受度。"


def _has_personalized_weight(q1: dict, q2: dict) -> bool:
    metric_keys = (
        "province_gdp",
        "city_level",
        "upgrade_ratio",
        "postgraduate_recommend_ratio",
        "level_score",
        "college_score",
        "college_score_new",
    )
    return any(_numeric_weight(q1.get(key)) is not None for key in metric_keys) or any(
        _numeric_weight(q2.get(key)) is not None for key in metric_keys
    )


def _render_school_comparison_facts(
    school_name1: str,
    school_name2: str,
    weights1: dict,
    weights2: dict,
) -> str:
    weights1 = weights1 or {}
    weights2 = weights2 or {}
    q1 = _first_weight_item(weights1)
    q2 = _first_weight_item(weights2)
    has_weight = _has_personalized_weight(q1, q2)

    lines: list[str] = [
        f"院校对比：{school_name1} vs {school_name2}",
    ]
    if has_weight:
        lines.append("当前有可参考的个性化量化指标，下面按城市资源、升学通道、院校层次和综合评分做对照。")
    else:
        lines.append("当前缺少完整个性化量化评分，所以先给出可用于判断的院校维度和指标空缺说明；最终建议需要结合专业、录取概率、地域和费用再判断。")

    lines.extend(
        [
            "",
            "关键指标：",
            f"- {_metric_compare_line('省份经济资源', school_name1, school_name2, q1.get('province_gdp'), q2.get('province_gdp'), '它反映所在省份的就业和实习资源基础。')}",
            f"- {_metric_compare_line('城市等级', school_name1, school_name2, q1.get('city_level'), q2.get('city_level'), '它更适合用来观察城市平台和实习机会。')}",
            f"- {_metric_compare_line('考研率', school_name1, school_name2, q1.get('upgrade_ratio'), q2.get('upgrade_ratio'), '它反映继续升学氛围，但不能替代具体专业实力。')}",
            f"- {_metric_compare_line('保研率', school_name1, school_name2, q1.get('postgraduate_recommend_ratio'), q2.get('postgraduate_recommend_ratio'), '它更适合用来观察校内升学通道。')}",
            f"- {_metric_compare_line('院校等级', school_name1, school_name2, q1.get('level_score'), q2.get('level_score'), '它反映学校整体层次和社会认可度。')}",
            f"- {_score_compare_line(school_name1, school_name2, q1.get('college_score_new') or q1.get('college_score'), q2.get('college_score_new') or q2.get('college_score'))}",
            "",
            "判断建议：",
            "- 院校对比不要只看学校名，要同时看所在城市、专业是否承接你的目标、录取概率和费用压力。",
        ]
    )

    remark1 = str(q1.get("college_remark") or "").strip()
    remark2 = str(q2.get("college_remark") or "").strip()
    if remark1:
        lines.append(f"- {school_name1}在当前个性化模型里被标记为：{remark1}。")
    if remark2:
        lines.append(f"- {school_name2}在当前个性化模型里被标记为：{remark2}。")
    if not remark1 and not remark2:
        lines.append("- 当前没有额外个性化备注，建议把院校层次、专业质量、地域接受度和录取安全一起纳入判断。")

    lines.extend(
        [
            "",
            "[数据来源]",
            "- 数据源：国家统计局GDP数据、教育部学科评估、高校官方升学数据",
            "- 计算方法：熵权法(Entropy Weight Method)多维指标综合评分",
        ]
    )
    return "\n".join(lines)


async def _summarize_comparison(
    school_name1: str,
    school_name2: str,
    weights1: dict,
    weights2: dict,
) -> str:
    """Generate an LLM-powered comparison summary."""
    querylist1 = weights1.get("querylist", [{}])
    q1 = querylist1[0] if querylist1 else {}
    querylist2 = weights2.get("querylist", [{}])
    q2 = querylist2[0] if querylist2 else {}

    province_gdp1 = q1.get("province_gdp", 0)
    city_level1 = q1.get("city_level", 0)
    upgrade_ratio1 = q1.get("upgrade_ratio", 0)
    postgraduate_recommend_ratio1 = q1.get("postgraduate_recommend_ratio", 0)
    level_score1 = q1.get("level_score", 0)
    college_score1 = q1.get("college_score", 0)
    college_score_new1 = q1.get("college_score_new", 0)
    college_remark1 = q1.get("college_remark", "")

    province_gdp2 = q2.get("province_gdp", 0)
    city_level2 = q2.get("city_level", 0)
    upgrade_ratio2 = q2.get("upgrade_ratio", 0)
    postgraduate_recommend_ratio2 = q2.get("postgraduate_recommend_ratio", 0)
    level_score2 = q2.get("level_score", 0)
    college_score2 = q2.get("college_score", 0)
    college_score_new2 = q2.get("college_score_new", 0)
    college_remark2 = q2.get("college_remark", "")

    remark1_text = (
        f"【由于{school_name1}属于学生的{college_remark1}，其最终得分调整为{college_score_new1}。】"
        if college_remark1
        else ""
    )
    remark2_text = (
        f"【由于{school_name2}属于学生的{college_remark2}，其最终得分调整为{college_score_new2}。】"
        if college_remark2
        else ""
    )

    prompt = (
        f"你是专业的高考志愿规划师，请根据以下维度及得分，对比{school_name1}、{school_name2}的优劣，"
        f"并根据院校最终得分进行总体评价。请只用文字形式进行分条叙述，不能使用给出的具体得分，仅根据得分差异进行对比。\n"
        f"省份GDP指数：衡量院校所在省份的经济发达程度。经济发达省份通常就业机会多，实习资源丰富。\n"
        f"城市等级指数：反映院校所在城市的综合实力和发展水平，通常基于城市分级体系量化而来。\n"
        f"考研率指数：衡量各院校的毕业生参加全国硕士研究生统一招生考试的比例。\n"
        f"保研率指数：衡量各院校毕业生获得推荐免试攻读硕士研究生资格的比例。\n"
        f"院校等级指数：综合反映一所高校整体办学层次、社会认可度和历史地位的量化评分。\n"
        f"{school_name1}的省份GDP指数：{province_gdp1}，城市等级指数：{city_level1}，"
        f"考研率指数：{upgrade_ratio1}，保研率指数：{postgraduate_recommend_ratio1}，院校等级指数：{level_score1}。\n"
        f"{school_name2}的省份GDP指数：{province_gdp2}，城市等级指数：{city_level2}，"
        f"考研率指数：{upgrade_ratio2}，保研率指数：{postgraduate_recommend_ratio2}，院校等级指数：{level_score2}。\n"
        f"基于上述维度，通过熵权法计算得到{school_name1}的院校得分：{college_score1}，"
        f"{school_name2}的院校得分：{college_score2}。\n"
        f"{remark1_text}\n{remark2_text}"
    )

    summary_agent = Agent(
        model=_get_llm_client().model,
        output_type=str,
        instructions="你是一个专业的高考志愿规划师，擅长根据各项指标对比分析学校优劣。",
    )
    result = await summary_agent.run(prompt, model_settings={"temperature": 0})
    result_text = result.output
    result_text += (
        "\n\n[数据来源]\n- 数据源：国家统计局GDP数据、教育部学科评估、高校官方升学数据"
        "\n- 计算方法：熵权法(Entropy Weight Method)多维指标综合评分"
    )
    return result_text


async def compare_schools_adhoc(
    ctx: RunContext[RequestContext],
    school_name1: str,
    school_name2: str,
    province: str,
    total_score: int,
    subjects: list[str],
    sex: str,
    strength_subjects: list[str],
) -> str:
    """为指定学生信息（非当前用户）对比两个学校的优劣。

    当用户以他人身份咨询学校对比时使用此工具。
    调用前必须确保已收集到省份、总分、选科、性别和优势学科信息。

    Args:
        school_name1: 第一个学校名称
        school_name2: 第二个学校名称
        province: 省份名称，如"河北"
        total_score: 高考总分
        subjects: 选科列表，如["物理","化学","生物"]
        sex: 性别，"男"或"女"
        strength_subjects: 优势学科列表（擅长的科目），如["数学","物理","化学"]
    """
    logger.info(
        "compare_schools_adhoc called: %s vs %s, province=%s, score=%s",
        school_name1, school_name2, province, total_score,
    )

    # 默认使用本科数据
    school_set = bachelor_school_set
    school_id_map = bachelor_school_id_map
    area_index = area_to_bachelor_schools

    try:
        studentinfo = await build_studentinfo_async(
            province, total_score, subjects, sex,
            strength_subjects=strength_subjects,
        )

        # Resolve fuzzy names
        if school_name1 not in school_set:
            school_name1 = await _resolve_school_name(
                school_name1, school_set, area_index
            )
        if school_name2 not in school_set:
            school_name2 = await _resolve_school_name(
                school_name2, school_set, area_index
            )

        school_id1 = school_id_map.get(school_name1)
        school_id2 = school_id_map.get(school_name2)

        if not school_id1 or not school_id2:
            missing = school_name1 if not school_id1 else school_name2
            return f"抱歉，未能找到{missing}的学校信息，无法进行对比。"

        # 直接调 rank-service query_weight
        queryinfo1 = {
            "type": "school",
            "querylist": [{"school_id": school_id1, "school_name": school_name1}],
        }
        queryinfo2 = {
            "type": "school",
            "querylist": [{"school_id": school_id2, "school_name": school_name2}],
        }

        weights1 = await rank_client.query_weight(studentinfo, queryinfo1)
        weights2 = await rank_client.query_weight(studentinfo, queryinfo2)

        logger.info("adhoc 学校1权重数据: %s", weights1)
        logger.info("adhoc 学校2权重数据: %s", weights2)

        if _allow_explore_inner_llm(ctx.deps):
            return await _summarize_comparison(
                school_name1, school_name2, weights1, weights2
            )
        return _render_school_comparison_facts(
            school_name1,
            school_name2,
            weights1,
            weights2,
        )

    except ValueError as e:
        return f"输入信息有误：{e}"
    except Exception:
        logger.exception("adhoc 学校对比失败: %s vs %s", school_name1, school_name2)
        return f"抱歉，对比{school_name1}和{school_name2}时发生错误，请稍后重试。"
