"""Deterministic evidence matching for canonical career-direction slots."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.domain.career_slots import (
    CAREER_FURTHER_STUDY,
    CAREER_MARKET_EMPLOYMENT,
    CAREER_STABLE_EMPLOYMENT,
    CAREER_SYSTEM_PUBLIC_SERVICE,
)


_CAREER_EVIDENCE: dict[str, tuple[str, ...]] = {
    CAREER_SYSTEM_PUBLIC_SERVICE: (
        "师范",
        "政法",
        "财经",
        "农林",
        "医药",
        "部委院校",
        "公安",
        "警校",
        "法学",
        "会计",
        "审计",
        "财务",
        "汉语言",
        "中国语言",
        "思想政治",
        "教育",
        "行政管理",
        "公共管理",
        "政治学",
        "马克思",
    ),
    CAREER_STABLE_EMPLOYMENT: (
        "公办",
        "师范",
        "医药",
        "政法",
        "农林",
        "教育",
        "护理",
        "医学",
        "药学",
        "法学",
        "行政管理",
    ),
    CAREER_FURTHER_STUDY: (
        "保研",
        "双一流",
        "985",
        "211",
        "国重点",
        "省重点",
        "博士点",
        "硕士点",
        "升学率",
    ),
    CAREER_MARKET_EMPLOYMENT: (
        "理工",
        "财经",
        "综合",
        "计算机",
        "软件",
        "电子",
        "信息",
        "人工智能",
        "数据",
        "自动化",
        "通信",
        "金融",
        "会计",
        "审计",
        "市场营销",
        "电子商务",
        "数字媒体",
        "就业",
        "产业",
        "校企",
        "实习",
        "互联网",
    ),
}


def matching_career_evidence(search_values: Iterable[Any], slot: str) -> list[str]:
    """Return the canonical evidence markers present in structured item text."""
    text = " ".join(str(value or "") for value in search_values if value not in (None, ""))
    if not text:
        return []
    return [marker for marker in _CAREER_EVIDENCE.get(str(slot or "").strip(), ()) if marker in text]


def matches_career_slot(search_values: Iterable[Any], slot: str) -> bool:
    return bool(matching_career_evidence(search_values, slot))
