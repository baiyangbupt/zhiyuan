"""Score query tools.

Provides tools for querying admission scores and score lines
for schools and majors via the gaotu API.
"""

import logging

from pydantic_ai import RunContext

from app.agent.context import RequestContext
from app.util.batch_subject_mapping import (
    encode_subjects,
    resolve_batch_codes,
    resolve_subject_type,
)
from app.util.code_enrichment import (
    get_major_codes_async,
    get_province_codes_async,
    get_school_codes_async,
    resolve_major_names_async,
    resolve_school_names_async,
)
from app.util.internal_client import (
    query_program_by_limit_num,
    query_school_major_score_line,
)

logger = logging.getLogger(__name__)


# ── 选科解析 ──────────────────────────────────────────────────────


_SUBJECT_SHORT = {
    "物": "物理", "化": "化学", "生": "生物",
    "政": "政治", "史": "历史", "地": "地理",
    "技": "技术",
}


def _parse_subjects(subjects_str: str) -> list[str]:
    """将用户输入的选科字符串解析为标准科目名列表。

    "物化生" -> ["物理", "化学", "生物"]
    "物理,化学,生物" -> ["物理", "化学", "生物"]
    "文科" -> ["文科"]
    "理科" -> ["理科"]
    """
    if not subjects_str:
        return []
    for sep in (",", "，", "、"):
        if sep in subjects_str:
            return [s.strip() for s in subjects_str.split(sep) if s.strip()]
    if all(c in _SUBJECT_SHORT for c in subjects_str):
        return [_SUBJECT_SHORT[c] for c in subjects_str]
    return [subjects_str]


# ── 工具 ──────────────────────────────────────────────────────────


async def query_admission_score(
    ctx: RunContext[RequestContext],
    school_name: str,
    score: int = 0,
    province: str = "",
    subjects: str = "",
) -> str:
    """查询某个学校在指定分数下是否能够录取，返回该学校的录取方案（冲/稳/保级别）及专业录取信息。

    可以查询当前学生自己的情况，也可以用指定的分数/省份/选科来查询。
    如果用户指定了分数、省份或选科，则使用用户指定的值；否则使用当前学生的成绩信息。

    Args:
        ctx: 运行上下文
        school_name: 学校名称，如"北京大学"、"长沙理工大学"
        score: 查询用的高考分数。如果用户指定了分数则传入（如"550分能上XX吗"传550），否则传0表示使用学生自己的分数
        province: 查询用的省份名称。如果用户指定了省份则传入（如"湖南550分"传"湖南"），否则传空字符串使用学生自己的省份
        subjects: 查询用的选科。如果用户指定了选科则传入（如"物化生"传"物化生"，"理科"传"理科"），否则传空字符串使用学生自己的选科

    Returns:
        录取方案信息文本
    """
    logger.info(
        "query_admission_score called: school_name=%s score=%s province=%s subjects=%s",
        school_name, score, province, subjects,
    )
    score_detail = ctx.deps.score_detail

    # 确定查询参数：用户指定 > 学生自己
    query_score = score if score > 0 else (score_detail.total_score if score_detail else 0)
    query_province = province or (score_detail.province if score_detail else "")
    subject_list = _parse_subjects(subjects) if subjects else (score_detail.subject_list if score_detail else [])

    if not query_score:
        return "请提供查询分数，例如\"550分能上北京大学吗"
    if not query_province:
        return "请提供查询省份，例如\"湖南550分能上北京大学吗\""

    normalized_school_names = await resolve_school_names_async([school_name])
    normalized_school_name = normalized_school_names[0] if normalized_school_names else school_name

    # 省份 → areaId
    province_codes = await get_province_codes_async([query_province])
    if not province_codes:
        return f"无法识别省份「{query_province}」，请确认省份名称。"
    area_id = province_codes[0]

    # 使用映射表解析 subject_type 和 batch codes
    subject_type = resolve_subject_type(area_id, subject_list)
    encoded_subjects = encode_subjects(subject_list)
    batch_codes = resolve_batch_codes(area_id, "本科")

    try:
        # 遍历该省所有本科批次编码查询
        all_data = []
        for batch_code in batch_codes:
            result = await query_program_by_limit_num(
                prepare_type="01",
                subject_type=subject_type,
                score=query_score,
                subjects=encoded_subjects,
                area_id=area_id,
                batch=batch_code,
                record_num_limit=30,
            )
            logger.debug("query_program_by_limit_num result: %s", result)
            if result and "error" not in result:
                data = result.get("data", [])
                if isinstance(data, dict):
                    data = data.get("data", [])
                if data:
                    all_data.extend(data)
    except Exception:
        logger.exception("查询院校录取方案失败: %s", normalized_school_name)
        return f"查询{normalized_school_name}录取方案时发生错误，请稍后重试。"

    if not all_data:
        return f"未查询到{normalized_school_name}在{query_province}{query_score}分下的录取数据。"

    # 在结果中搜索目标学校
    school_codes = await get_school_codes_async([normalized_school_name])
    target_school_id = school_codes[0] if school_codes else None

    found_entries = []
    for level_data in all_data:
        volunteer_level = level_data.get("volunteerLevel", "")
        records = level_data.get("records", [])
        for record in records:
            record_name = record.get("schoolUnitName", "")
            record_id = str(record.get("schoolId", ""))
            if record_name == normalized_school_name or (target_school_id and record_id == target_school_id):
                found_entries.append((volunteer_level, record))

    if not found_entries:
        level_summary = []
        for level_data in all_data:
            vl = level_data.get("volunteerLevel", "")
            count = len(level_data.get("records", []))
            level_summary.append(f"{vl}({count}所)")
        return (
            f"在{query_province}{query_score}分下，{normalized_school_name}未出现在录取方案中。"
            f"当前方案包含：{'、'.join(level_summary)}。"
            f"这可能意味着该校分数线远高于或远低于此分数，建议查询该校历年分数线进一步确认。"
        )

    lines = [f"以下是{normalized_school_name}在{query_province}{query_score}分下的录取参考信息：\n"]
    for volunteer_level, record in found_entries:
        school_score = record.get("schoolScore", "")
        school_pos = record.get("schoolPos", "")
        enroll_ratio = record.get("enrollRatio", "")
        enroll_advice = record.get("enrollAdvice", "")
        select_info = record.get("selectInfo", "")

        lines.append(f"- 志愿级别：{volunteer_level}")
        if school_score:
            lines.append(f"  学校录取分：{school_score}")
        if school_pos:
            lines.append(f"  学校位次：{school_pos}")
        if enroll_ratio:
            lines.append(f"  录取比例：{enroll_ratio}")
        if enroll_advice:
            lines.append(f"  录取建议：{enroll_advice}")
        if select_info:
            lines.append(f"  选科要求：{select_info}")

        sub_list = record.get("subVOList", [])
        if sub_list:
            lines.append("  近年招生专业：")
            for sub in sub_list[:10]:
                year = sub.get("year", "")
                title = sub.get("enrollMajorSubtitle", "")
                plan_num = sub.get("planNum", "")
                e_score = sub.get("enrollScore", "")
                e_pos = sub.get("enrollPos", "")
                detail = f"    {year}年 {title}"
                if plan_num:
                    detail += f" 计划招{plan_num}人"
                if e_score:
                    detail += f" 录取分{e_score}"
                if e_pos:
                    detail += f" 位次{e_pos}"
                lines.append(detail)

    result_text = "\n".join(lines)
    result_text += "\n\n[数据来源]\n- 数据源：各省考试院历年录取数据"
    return result_text


async def query_score_line(
    ctx: RunContext[RequestContext],
    school_name: str,
    major_name: str = "",
    province: str = "",
    subjects: str = "",
) -> str:
    """查询某个学校（及可选专业）的历年录取分数线，包括最低分、最高分、平均分、录取位次等。

    可以查询当前学生所在省的分数线，也可以指定省份查询。

    Args:
        ctx: 运行上下文
        school_name: 学校名称，如"北京大学"
        major_name: 专业名称（可选），如"计算机科学与技术"。不传则查学校整体分数线
        province: 查询用的省份名称。如果用户指定了省份则传入，否则传空字符串使用学生自己的省份
        subjects: 查询用的选科。如果用户指定了选科则传入，否则传空字符串使用学生自己的选科

    Returns:
        历年分数线信息文本
    """
    logger.info(
        "query_score_line called: school_name=%s major_name=%s province=%s subjects=%s",
        school_name, major_name, province, subjects,
    )
    score_detail = ctx.deps.score_detail

    query_province = province or (score_detail.province if score_detail else "")
    subject_list = _parse_subjects(subjects) if subjects else (score_detail.subject_list if score_detail else [])
    query_score = score_detail.total_score if score_detail else 0

    if not query_province:
        return "请提供查询省份，例如\"北京大学在湖南的分数线\"。"

    normalized_school_names = await resolve_school_names_async([school_name])
    normalized_school_name = normalized_school_names[0] if normalized_school_names else school_name

    # 学校名 → ID
    school_codes = await get_school_codes_async([normalized_school_name])
    if not school_codes:
        return f"无法识别学校「{school_name}」，请确认校名是否正确。"
    school_id = school_codes[0]

    # 专业名 → ID
    major_id = ""
    normalized_major_name = major_name
    if major_name:
        batch = ctx.deps.batch or "01"
        normalized_major_names = await resolve_major_names_async([major_name], "level3", batch)
        normalized_major_name = normalized_major_names[0] if normalized_major_names else major_name
        major_codes = await get_major_codes_async([normalized_major_name], "level3", batch)
        if not major_codes:
            return f"无法识别专业「{major_name}」，请确认专业名称是否正确。"
        major_id = major_codes[0]

    # 省份 → areaId
    province_codes = await get_province_codes_async([query_province])
    if not province_codes:
        return f"无法识别省份「{query_province}」，请确认省份名称。"
    area_id = province_codes[0]

    # 使用映射表解析 subject_type 和 batch codes
    subject_type = resolve_subject_type(area_id, subject_list)
    batch_codes = resolve_batch_codes(area_id, "本科")

    try:
        # 遍历该省所有本科批次编码查询
        all_data = []
        for batch_code in batch_codes:
            result = await query_school_major_score_line(
                area_id=area_id,
                batch=batch_code,
                school_id=school_id,
                major_id=major_id,
                year=2025,
                subject_type=subject_type,
            )
            logger.debug("query_school_major_score_line result: %s", result)
            if result and "error" not in result:
                data = result.get("data", [])
                if isinstance(data, dict):
                    data = data.get("data", [])
                if data:
                    all_data.extend(data)
    except Exception:
        logger.exception("查询分数线失败: school=%s, major=%s", normalized_school_name, normalized_major_name)
        target = f"{normalized_school_name}{normalized_major_name}专业" if major_name else normalized_school_name
        return f"查询{target}分数线时发生错误，请稍后重试。"

    if not all_data:
        target = f"{normalized_school_name}{normalized_major_name}专业" if major_name else normalized_school_name
        return f"未查询到{target}在{query_province}的历年录取分数线数据。"

    target = f"{normalized_school_name} - {normalized_major_name}" if major_name else normalized_school_name
    lines = [f"{target} 在{query_province}的历年录取分数线：\n"]

    for entry in all_data:
        year = entry.get("year", "")
        name = entry.get("name", "")
        batch_title = entry.get("batchTitle", entry.get("batch", ""))
        min_score = entry.get("minScore", "")
        max_score = entry.get("maxScore", "")
        avg_score = entry.get("averageScore", "")
        min_pos = entry.get("minPos", "")
        enroll_num = entry.get("enrollNum", "")
        select_info = entry.get("selectInfo", "")

        line = f"- {year}年"
        if name:
            line += f"（{name}）"
        if batch_title:
            line += f" [{batch_title}]"
        parts = []
        if min_score and min_score != "0":
            parts.append(f"最低分{min_score}")
        if max_score and max_score != "0":
            parts.append(f"最高分{max_score}")
        if avg_score and avg_score != "0":
            parts.append(f"平均分{avg_score}")
        if min_pos and min_pos != "0":
            parts.append(f"最低位次{min_pos}")
        if enroll_num and enroll_num != "0":
            parts.append(f"录取{enroll_num}人")
        if select_info:
            parts.append(f"选科要求：{select_info}")
        if parts:
            line += "：" + "，".join(parts)

        lines.append(line)

    # 与分数对比
    if query_score and all_data:
        latest = all_data[0]
        latest_min = latest.get("minScore", "")
        if latest_min and latest_min != "0":
            try:
                diff = query_score - int(latest_min)
                year = latest.get("year", "最近一年")
                if diff >= 0:
                    lines.append(f"\n当前分数({query_score}分)比{year}年最低录取分({latest_min}分)高{diff}分。")
                else:
                    lines.append(f"\n当前分数({query_score}分)比{year}年最低录取分({latest_min}分)低{abs(diff)}分。")
            except (ValueError, TypeError):
                pass

    result_text = "\n".join(lines)
    result_text += "\n\n[数据来源]\n- 数据源：各省考试院历年录取分数线"
    return result_text
