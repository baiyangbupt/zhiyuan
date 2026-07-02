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
    associate_major_mappings,
    bachelor_level3_id_map,
    bachelor_level3_labels,
    bachelor_major_mappings,
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


def _allow_explore_inner_llm(request_context: RequestContext) -> bool:
    return bool(getattr(request_context, "allow_explore_inner_llm", True))


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

        if _allow_explore_inner_llm(ctx.deps):
            return await _summarize_comparison(
                major_name1, major_name2, weights1, weights2
            )
        return _render_major_comparison_facts(
            major_name1,
            major_name2,
            weights1,
            weights2,
            is_bachelor=is_bachelor,
        )

    except Exception:
        logger.exception("专业对比失败: %s vs %s", major_name1, major_name2)
        return f"抱歉，对比{major_name1}和{major_name2}时发生错误，请稍后重试。"


async def compare_major_options(
    ctx: RunContext[RequestContext],
    major_names: list[str],
) -> str:
    """对三个及以上具体专业进行同组取舍分析，返回可用于排序和优先级判断的事实。

    适合回答“财管、会计、审计怎么排优先级”“法学、财政、汉语言哪个更稳”这类多专业取舍问题。
    如果只有两个专业，请优先使用 `compare_majors`。
    """
    logger.info("compare_major_options called: %s", major_names)

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

    try:
        resolved_names: list[str] = []
        for raw_name in major_names or []:
            name = str(raw_name or "").strip()
            if not name:
                continue
            if name not in level3_labels:
                name = await _resolve_major_name(name, level3_labels, prefix_index, "01" if is_bachelor else "02")
            if name and name not in resolved_names:
                resolved_names.append(name)

        if len(resolved_names) < 2:
            return "至少需要两个明确专业，才能做专业取舍对比。"

        limited_names = resolved_names[:6]
        missing = [name for name in limited_names if not level3_id_map.get(name)]
        if missing:
            return f"抱歉，未能找到{missing[0]}的专业信息，无法进行多专业对比。"

        query_items = [
            {"major_id": level3_id_map[name], "major_level": 3, "major_name": name}
            for name in limited_names
        ]
        weights = await query_volunteer_analysis_weight(1, ctx.deps.sessionid, query_items)
        logger.info("多专业权重数据: %s", weights)
        return _render_major_options_facts(
            limited_names,
            weights,
            is_bachelor=is_bachelor,
            truncated=len(resolved_names) > len(limited_names),
        )
    except Exception:
        logger.exception("多专业对比失败: %s", major_names)
        return "抱歉，做多专业对比时发生错误，请稍后重试。"


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


def _major_category_name(major_name: str, *, is_bachelor: bool) -> str:
    mappings = bachelor_major_mappings if is_bachelor else associate_major_mappings
    return str((mappings.get("level3_to_level2") or {}).get(major_name) or "")


def _first_weight_item(weights: dict) -> dict:
    querylist = weights.get("querylist", [])
    return querylist[0] if querylist else {}


def _weight_querylist(weights: dict) -> list[dict]:
    if not isinstance(weights, dict):
        return []
    querylist = weights.get("querylist")
    if isinstance(querylist, list):
        return [item if isinstance(item, dict) else {} for item in querylist]
    data = weights.get("data")
    if isinstance(data, dict) and isinstance(data.get("querylist"), list):
        return [item if isinstance(item, dict) else {} for item in data["querylist"]]
    return []


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
    major_name1: str,
    major_name2: str,
    value1,
    value2,
    explanation: str,
) -> str:
    numeric1 = _numeric_weight(value1)
    numeric2 = _numeric_weight(value2)
    display = f"{major_name1} {_format_metric_value(value1)} / {major_name2} {_format_metric_value(value2)}"
    if numeric1 is None or numeric2 is None:
        return f"{label}：{display}。当前至少有一方缺少有效量化数据，适合只作定性参考。"
    if abs(numeric1 - numeric2) < 1e-6:
        return f"{label}：{display}。两者差异不明显，{explanation}"
    stronger = major_name1 if numeric1 > numeric2 else major_name2
    return f"{label}：{display}。相对看，{stronger}在这个维度更占优，{explanation}"


def _score_compare_line(major_name1: str, major_name2: str, score1, score2) -> str:
    numeric1 = _numeric_weight(score1)
    numeric2 = _numeric_weight(score2)
    display = f"{major_name1} {_format_metric_value(score1)} / {major_name2} {_format_metric_value(score2)}"
    if numeric1 is None or numeric2 is None:
        return f"综合评分：{display}。当前缺少完整个性化量化评分，不能只按分数判断哪个一定更适合。"
    if abs(numeric1 - numeric2) < 1e-6:
        return f"综合评分：{display}。两者综合差异不明显，建议继续看职业路径、学习压力和家庭试错成本。"
    stronger = major_name1 if numeric1 > numeric2 else major_name2
    return f"综合评分：{display}。按当前量化结果，{stronger}整体更占优，但仍要结合你能否接受对应学习和就业路径。"


def _has_personalized_weight(q1: dict, q2: dict) -> bool:
    metric_keys = (
        "gender_index",
        "satisfy_index",
        "salary_avg",
        "hot_index",
        "major_score",
        "major_score_new",
    )
    return any(_numeric_weight(q1.get(key)) is not None for key in metric_keys) or any(
        _numeric_weight(q2.get(key)) is not None for key in metric_keys
    )


def _render_major_comparison_facts(
    major_name1: str,
    major_name2: str,
    weights1: dict,
    weights2: dict,
    *,
    is_bachelor: bool,
) -> str:
    weights1 = weights1 or {}
    weights2 = weights2 or {}
    gender_flag = weights1.get("gender_flag") or weights2.get("gender_flag") or "学生"
    q1 = _first_weight_item(weights1)
    q2 = _first_weight_item(weights2)
    category1 = _major_category_name(major_name1, is_bachelor=is_bachelor)
    category2 = _major_category_name(major_name2, is_bachelor=is_bachelor)
    has_weight = _has_personalized_weight(q1, q2)

    lines: list[str] = [
        f"专业对比：{major_name1}{f'（{category1}）' if category1 else ''} vs {major_name2}{f'（{category2}）' if category2 else ''}",
    ]
    if has_weight:
        lines.append(f"当前有可参考的个性化量化指标，下面按{gender_flag}相关指数、满意度、薪酬、热度和综合评分做对照。")
    else:
        lines.append("当前缺少完整个性化量化评分，所以先给出可用于判断的专业类、就业路径和指标空缺说明；最终建议需要结合分数、选科、地域和家庭诉求再判断。")

    lines.extend(
        [
            "",
            "关键指标：",
            f"- {_metric_compare_line('性别分布适配', major_name1, major_name2, q1.get('gender_index'), q2.get('gender_index'), '它反映该专业群体结构，不等同于就业歧视或绝对适合。')}",
            f"- {_metric_compare_line('专业满意度', major_name1, major_name2, q1.get('satisfy_index'), q2.get('satisfy_index'), '它更适合用来观察学习体验和毕业反馈。')}",
            f"- {_metric_compare_line('平均薪酬', major_name1, major_name2, q1.get('salary_avg'), q2.get('salary_avg'), '它反映经济回报，但不能替代就业稳定性判断。')}",
            f"- {_metric_compare_line('报考热度', major_name1, major_name2, q1.get('hot_index'), q2.get('hot_index'), '热度高通常意味着关注度高，也可能意味着竞争更明显。')}",
            f"- {_score_compare_line(major_name1, major_name2, q1.get('major_score_new') or q1.get('major_score'), q2.get('major_score_new') or q2.get('major_score'))}",
            "",
            "判断建议：",
        ]
    )
    if category1 and category2 and category1 != category2:
        lines.append(f"- {major_name1}更接近{category1}路径，{major_name2}更接近{category2}路径，比较时不要只看专业名，要看未来岗位和升学方向。")
    elif category1:
        lines.append(f"- 两个专业都在{category1}附近，差异更可能体现在具体课程、就业岗位和院校培养资源。")
    else:
        lines.append("- 两个专业的目录归属暂时不完整，建议继续结合课程、就业岗位和院校培养资源比较。")

    remark1 = str(q1.get("major_remark") or "").strip()
    remark2 = str(q2.get("major_remark") or "").strip()
    if remark1:
        lines.append(f"- {major_name1}在当前个性化模型里被标记为：{remark1}。")
    if remark2:
        lines.append(f"- {major_name2}在当前个性化模型里被标记为：{remark2}。")
    if not remark1 and not remark2:
        lines.append("- 当前没有额外个性化备注，建议把学习压力、就业稳定性、城市机会和家庭试错成本一起纳入判断。")

    lines.extend(
        [
            "",
            "[数据来源]",
            "- 数据源：高校毕业生就业调查数据、招生报考统计",
            "- 计算方法：熵权法(Entropy Weight Method)多维指标综合评分",
        ]
    )
    return "\n".join(lines)


def _render_major_options_facts(
    major_names: list[str],
    weights: dict,
    *,
    is_bachelor: bool,
    truncated: bool = False,
) -> str:
    querylist = _weight_querylist(weights or {})
    gender_flag = (weights or {}).get("gender_flag") or "学生"
    rows: list[tuple[str, dict]] = []
    for index, major_name in enumerate(major_names):
        item = querylist[index] if index < len(querylist) else {}
        rows.append((major_name, item))

    has_weight = any(_has_personalized_weight(item, {}) for _, item in rows)
    lines: list[str] = [
        "多专业取舍事实：" + "、".join(major_names),
    ]
    if truncated:
        lines.append("本次先展示前 6 个专业，避免一次对比过长。")
    if has_weight:
        lines.append(f"当前有可参考的个性化量化指标，下面按{gender_flag}相关指数、满意度、薪酬、热度和综合评分做横向对照。")
    else:
        lines.append("当前缺少完整个性化量化评分，所以先给出目录归属和可用于判断的指标空缺说明；不要把空指标解释成得分相同。")

    lines.extend(["", "专业横向对照："])
    for major_name, item in rows:
        category = _major_category_name(major_name, is_bachelor=is_bachelor)
        score = item.get("major_score_new") or item.get("major_score")
        remark = str(item.get("major_remark") or "").strip()
        row = (
            f"- {major_name}{f'（{category}）' if category else ''}："
            f"综合评分 {_format_metric_value(score)}；"
            f"满意度 {_format_metric_value(item.get('satisfy_index'))}；"
            f"平均薪酬 {_format_metric_value(item.get('salary_avg'))}；"
            f"报考热度 {_format_metric_value(item.get('hot_index'))}"
        )
        if remark:
            row += f"；个性化备注：{remark}"
        lines.append(row + "。")

    categories = [
        f"{major_name}->{_major_category_name(major_name, is_bachelor=is_bachelor)}"
        for major_name in major_names
        if _major_category_name(major_name, is_bachelor=is_bachelor)
    ]
    if categories:
        lines.append("")
        lines.append("目录归属：" + "；".join(categories) + "。")

    lines.extend(
        [
            "",
            "判断建议：",
            "- 先按用户目标拆分：求稳/考公看岗位口径和通用性，企业就业看岗位面和城市资源，读研看学科平台和课程基础。",
            "- 如果量化指标缺失，应明确说当前不能只按系统分数排序，再用就业路径、学习压力、家庭试错成本和院校培养资源做定性判断。",
            "- 如果用户要求给出优先级，可以给出默认排序，并说明在考公、企业就业、事务所、读研等不同目标下如何调整。",
            "",
            "[数据来源]",
            "- 数据源：高校毕业生就业调查数据、招生报考统计",
            "- 计算方法：熵权法(Entropy Weight Method)多维指标综合评分",
        ]
    )
    return "\n".join(lines)


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

        if _allow_explore_inner_llm(ctx.deps):
            return await _summarize_comparison(
                major_name1, major_name2, weights1, weights2
            )
        return _render_major_comparison_facts(
            major_name1,
            major_name2,
            weights1,
            weights2,
            is_bachelor=True,
        )

    except ValueError as e:
        return f"输入信息有误：{e}"
    except Exception:
        logger.exception("adhoc 专业对比失败: %s vs %s", major_name1, major_name2)
        return f"抱歉，对比{major_name1}和{major_name2}时发生错误，请稍后重试。"
