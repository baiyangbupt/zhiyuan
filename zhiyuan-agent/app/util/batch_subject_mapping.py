"""Batch and subject code mapping utilities.

Loads province-year-specific batch codes, subject type codes from CSV data.
The CSV format matches the gaotu zhiyuan system's batch_data table.
"""

import csv
import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 科目类型编码 → 中文名
SUBJECT_CODE_TO_TITLE: dict[str, str] = {
    "N": "综合",
    "W": "文科",
    "L": "理科",
    "WL": "物理",
    "LS": "历史",
}

# 选科科目 → 位置编码（用于 subjects 字段）
SUBJECT_POSITION_CODE: dict[str, str] = {"1":{
    "物": "01",
    "史": "02",
    "政": "03",
    "地": "04",
    "化": "05",
    "生": "06",
    "技": "07",
}, "2":{
    "物理": "01",
    "历史": "02",
    "政治": "03",
    "地理": "04",
    "化学": "05",
    "生物": "06",
    "技术": "07",
}}


@lru_cache(maxsize=1)
def _load_batch_subject_data() -> tuple[
    dict[str, dict[str, dict[str, list[str]]]],  # area_year_batches
    dict[str, dict[str, list[str]]],               # area_year_subjects
]:
    """Load batch and subject mapping from CSV.

    Returns:
        (area_year_batches, area_year_subjects)
        area_year_batches: {area_id: {year: {batch_nick: [batch_codes]}}}
          e.g. {"430000": {"2024": {"本科": ["01"], "专科": ["24"]}}}
        area_year_subjects: {area_id: {year: [subject_codes]}}
          e.g. {"430000": {"2024": ["WL", "LS"]}}
    """
    csv_path = Path(__file__).parent.parent.parent / "data" / "option" / "batch_subject_mapping_data.csv"

    area_year_batches: dict[str, dict[str, dict[str, set[str]]]] = {}
    area_year_subjects: dict[str, dict[str, set[str]]] = {}

    batch_nicks = ["本科", "专科", "特招", "一段", "二段"]

    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            area_id = row.get("area_id", "").strip()
            subject = row.get("subject", "").strip()
            batch_code = row.get("batch", "").strip()
            batch_title = row.get("batch_title", "").strip()
            year = row.get("year", "").strip()

            if not area_id or not year:
                continue

            # 归一化批次名称到 本科/专科/特招/一段/二段
            batch_nick = None
            for nick in batch_nicks:
                if nick in batch_title:
                    batch_nick = nick
                    break
            if not batch_nick:
                continue

            # area_year_batches
            area_year_batches.setdefault(area_id, {}).setdefault(year, {}).setdefault(batch_nick, set()).add(batch_code)

            # area_year_subjects
            area_year_subjects.setdefault(area_id, {}).setdefault(year, set()).add(subject)

    # Convert sets to lists
    result_batches: dict[str, dict[str, dict[str, list[str]]]] = {}
    for a, years in area_year_batches.items():
        result_batches[a] = {}
        for y, nicks in years.items():
            result_batches[a][y] = {nick: sorted(codes) for nick, codes in nicks.items()}

    result_subjects: dict[str, dict[str, list[str]]] = {}
    for a, years in area_year_subjects.items():
        result_subjects[a] = {y: sorted(codes) for y, codes in years.items()}

    return result_batches, result_subjects


def get_area_subject_codes(area_id: str, year: str = "2024") -> list[str]:
    """获取某省份某年支持的科目类型编码列表。

    Returns:
        e.g. ["WL", "LS"] for 湖南新高考, ["W", "L"] for 安徽传统高考
    """
    batches, subjects = _load_batch_subject_data()
    return subjects.get(area_id, {}).get(year, [])


def get_area_batch_codes(area_id: str, year: str = "2024") -> dict[str, list[str]]:
    """获取某省份某年的批次映射。

    Returns:
        e.g. {"本科": ["01"], "专科": ["24"]} for 湖南
    """
    batches, _ = _load_batch_subject_data()
    return batches.get(area_id, {}).get(year, {})


def resolve_subject_type(area_id: str, subject_list: list[str], year: str = "2025") -> str:
    """根据省份和选科列表，解析出 gaotu API 需要的 subject_type 编码。

    规则：
    - 先查该省该年支持哪些科目类型 (N/W/L/WL/LS)
    - 如果只有 N（综合），直接返回 N
    - 新高考省份 (WL/LS)：物理相关→WL，历史相关→LS
    - 传统省份 (W/L)：文科→W，理科→L
    """
    area_subjects = get_area_subject_codes(area_id, year)
    if not area_subjects:
        logger.warning("No subject data for area_id=%s year=%s", area_id, year)
        return "WL"  # fallback

    # 综合省份
    if "N" in area_subjects:
        return "N"

    subject_str = ",".join(subject_list).lower() if subject_list else ""

    # 新高考省份 (WL=物理, LS=历史)
    if "WL" in area_subjects:
        if any(k in subject_str for k in ("物", "理")):
            return "WL"
        if any(k in subject_str for k in ("历", "史", "文")):
            return "LS"
        return "WL"  # 默认物理

    # 传统高考省份 (W=文科, L=理科)
    if "L" in area_subjects:
        if any(k in subject_str for k in ("文", "史")):
            return "W"
        return "L"

    return area_subjects[0]  # fallback to first available


def resolve_batch_codes(area_id: str, batch_nick: str = "本科", year: str = "2025") -> list[str]:
    """获取某省份某年某批次类别的所有具体批次编码。

    Args:
        area_id: 省份编码
        batch_nick: 归一化批次名，如 "本科"/"专科"/"特招"/"一段"/"二段"
        year: 年份

    Returns:
        批次编码列表，如 ["01"] 或 ["02", "07"]（有一本二本的省份）
    """
    area_batches = get_area_batch_codes(area_id, year)
    if not area_batches:
        logger.warning("No batch data for area_id=%s year=%s", area_id, year)
        return ["01"]  # fallback

    # 直接匹配
    if batch_nick in area_batches:
        return area_batches[batch_nick]

    # 一段/二段 ↔ 本科/专科 互转
    if batch_nick == "一段" and "本科" in area_batches:
        return area_batches["本科"]
    if batch_nick == "二段" and "专科" in area_batches:
        return area_batches["专科"]
    if batch_nick == "本科" and "一段" in area_batches:
        return area_batches["一段"]
    if batch_nick == "专科" and "二段" in area_batches:
        return area_batches["二段"]

    # fallback: 返回第一个批次
    first_key = next(iter(area_batches), None)
    if first_key:
        return area_batches[first_key]
    return ["01"]


def encode_subjects(subject_list: list[str]) -> str:
    """将选科列表编码为 gaotu API 需要的 subjects 字符串。

    如 ["物理", "化学", "生物"] → "010506"
    如 ["物", "化", "生"] → "010506"
    """
    codes = []
    for subj in subject_list:
        # 处理单字和双字两种情况(简称和全称), 防止“生物”被“物”命中导致的歧义
        if len(subj) == 1:
            for key, code in SUBJECT_POSITION_CODE['1'].items():
                if key == subj:
                    if code not in codes:
                        codes.append(code)
                    break
        else:
            for key, code in SUBJECT_POSITION_CODE['2'].items():
                if key == subj:
                    if code not in codes:
                        codes.append(code)
                    break
    codes.sort()
    return "".join(codes)
