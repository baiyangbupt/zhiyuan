"""Static mappings and studentinfo builder for rank-service endpoints.

Provides ``build_studentinfo()`` which constructs the ``studentinfo`` dict
expected by the rank-service ``recommend_submajor`` and ``query_weight``
endpoints.
"""

from __future__ import annotations

from app.util.batch_subject_mapping import SUBJECT_CODE_TO_TITLE, resolve_subject_type
from app.util.code_enrichment import get_province_codes_async

# ---------------------------------------------------------------------------
# 省份名称 → 行政区划代码
# ---------------------------------------------------------------------------
PROVINCE_NAME_TO_CODE: dict[str, str] = {
    "北京": "110000",
    "天津": "120000",
    "河北": "130000",
    "山西": "140000",
    "内蒙古": "150000",
    "辽宁": "210000",
    "吉林": "220000",
    "黑龙江": "230000",
    "上海": "310000",
    "江苏": "320000",
    "浙江": "330000",
    "安徽": "340000",
    "福建": "350000",
    "江西": "360000",
    "山东": "370000",
    "河南": "410000",
    "湖北": "420000",
    "湖南": "430000",
    "广东": "440000",
    "广西": "450000",
    "海南": "460000",
    "重庆": "500000",
    "四川": "510000",
    "贵州": "520000",
    "云南": "530000",
    "西藏": "540000",
    "陕西": "610000",
    "甘肃": "620000",
    "青海": "630000",
    "宁夏": "640000",
    "新疆": "650000",
}

# ---------------------------------------------------------------------------
# 选科名称 → 科目代码 (subjectList 中的 value 字段)
# ---------------------------------------------------------------------------
SUBJECT_NAME_TO_VALUE: dict[str, str] = {
    "物理": "01",
    "化学": "02",
    "生物": "03",
    "政治": "04",
    "历史": "05",
    "地理": "06",
    "技术": "07",  # 浙江特有
}

# ---------------------------------------------------------------------------
# 优势学科名称 → 科目代码 (strengthSubjectList 中的 subject 字段)
# 包含语数外三门主科和选考科目
# ---------------------------------------------------------------------------
STRENGTH_SUBJECT_NAME_TO_CODE: dict[str, str] = {
    "语文": "09",
    "数学": "10",
    "英语": "11",
    "物理": "01",
    "化学": "02",
    "生物": "03",
    "政治": "04",
    "历史": "05",
    "地理": "06",
}


def _build_subject_type(province_code: str, subjects: list[str]) -> dict[str, str]:
    """Build province-aware subject type for rank-service studentinfo.

    Note:
    - ``studentinfo.subjectType`` should share the same province-sensitive
      resolution logic as gaotu query-side subject type.
    - ``studentinfo.subjectList[].value`` still follows rank-service's own
      field schema and is intentionally not unified with gaotu's ``subjects``
      encoded string.
    """
    code = resolve_subject_type(province_code, subjects)
    return {"code": code, "desc": SUBJECT_CODE_TO_TITLE.get(code, subjects[0] if subjects else "")}


def build_studentinfo(
    province: str,
    total_score: int,
    subjects: list[str],
    sex: str,
    strength_subjects: list[str],
    batch_level: str = "01",
) -> dict:
    """Construct the ``studentinfo`` dict consumed by rank-service.

    Args:
        province: Province name, e.g. "河北".
        total_score: Total gaokao score.
        subjects: Elective subjects, e.g. ``["物理", "化学", "生物"]``.
            The first element should be the primary subject (物理 or 历史).
        sex: "男" or "女".
        strength_subjects: Strongest subjects, e.g. ``["数学", "物理", "化学"]``.
        batch_level: Batch level -- "01" for 本科 (default), "02" for 专科.

    Returns:
        A dict matching the ``studentinfo`` schema expected by
        ``recommend_submajor`` and ``query_weight``.

    Raises:
        ValueError: If *province* is not found in ``PROVINCE_NAME_TO_CODE``.
    """
    # Province lookup
    province_code = PROVINCE_NAME_TO_CODE.get(province)
    if province_code is None:
        raise ValueError(
            f"Unknown province '{province}'. "
            f"Valid options: {', '.join(sorted(PROVINCE_NAME_TO_CODE))}"
        )

    # Sex
    sex_code = "male" if sex == "男" else "female"
    sex_name = sex

    subject_type = _build_subject_type(province_code, subjects)

    # Subject list -- isFirst=1 for the first subject (物理 or 历史), 0 for rest
    subject_list: list[dict] = []
    for idx, subj in enumerate(subjects):
        value = SUBJECT_NAME_TO_VALUE.get(subj, "")
        is_first = 1 if idx == 0 else 0
        subject_list.append({
            "name": subj,
            "value": value,
            "isFirst": is_first,
        })

    # Strength subject list
    strength_subject_list: list[dict] = []
    for subj in strength_subjects:
        code = STRENGTH_SUBJECT_NAME_TO_CODE.get(subj, "")
        strength_subject_list.append({
            "subject": code,
            "subjectName": subj,
        })

    return {
        "batch": {"level": batch_level},
        "sex": {"code": sex_code, "name": sex_name},
        "province": {"code": province_code, "name": province},
        "subjectList": subject_list,
        "subjectType": subject_type,
        "strengthSubjectList": strength_subject_list,
        "totalScore": total_score,
        "filterType": "2",
    }


async def build_studentinfo_async(
    province: str,
    total_score: int,
    subjects: list[str],
    sex: str,
    strength_subjects: list[str],
    batch_level: str = "01",
) -> dict:
    """Async variant of ``build_studentinfo``.

    Province code resolution first reuses the existing local mapping via
    ``get_province_codes_async`` and only falls back to backend catalog
    lookup when local mapping misses.
    """
    province_code_list = await get_province_codes_async([province])
    province_code = province_code_list[0] if province_code_list else None
    if province_code is None:
        raise ValueError(
            f"Unknown province '{province}'. "
            f"Valid options: {', '.join(sorted(PROVINCE_NAME_TO_CODE))}"
        )

    sex_code = "male" if sex == "男" else "female"
    sex_name = sex

    subject_type = _build_subject_type(province_code, subjects)

    subject_list: list[dict] = []
    for idx, subj in enumerate(subjects):
        value = SUBJECT_NAME_TO_VALUE.get(subj, "")
        is_first = 1 if idx == 0 else 0
        subject_list.append({
            "name": subj,
            "value": value,
            "isFirst": is_first,
        })

    strength_subject_list: list[dict] = []
    for subj in strength_subjects:
        code = STRENGTH_SUBJECT_NAME_TO_CODE.get(subj, "")
        strength_subject_list.append({
            "subject": code,
            "subjectName": subj,
        })

    return {
        "batch": {"level": batch_level},
        "sex": {"code": sex_code, "name": sex_name},
        "province": {"code": province_code, "name": province},
        "subjectList": subject_list,
        "subjectType": subject_type,
        "strengthSubjectList": strength_subject_list,
        "totalScore": total_score,
        "filterType": "2",
    }
