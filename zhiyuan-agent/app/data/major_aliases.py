"""Common major alias table.

This table is intentionally conservative:
- single-target aliases can be used for deterministic normalization;
- multi-target aliases are only for candidate recall before model extraction.
"""

from __future__ import annotations

from collections.abc import Iterable


COMMON_MAJOR_ALIAS_TABLE: dict[str, dict[str, tuple[str, ...]]] = {
    "计科": {
        "level2": ("计算机类",),
        "level3": ("计算机科学与技术",),
    },
    "计算机": {
        "level2": ("计算机类",),
        "level3": ("计算机科学与技术",),
    },
    "软工": {
        "level2": ("计算机类",),
        "level3": ("软件工程",),
    },
    "软件": {
        "level2": ("计算机类",),
        "level3": ("软件工程",),
    },
    "ai": {
        "level2": ("电子信息类",),
        "level3": ("人工智能",),
    },
    "大数据": {
        "level2": ("计算机类", "管理科学与工程类"),
        "level3": ("数据科学与大数据技术", "大数据管理与应用"),
    },
    "电气自动化": {
        "level2": ("电气类",),
        "level3": ("电气工程及其自动化",),
    },
    "电信": {
        "level2": ("电子信息类",),
        "level3": ("电子信息工程", "通信工程"),
    },
    "通信": {
        "level2": ("电子信息类",),
        "level3": ("通信工程",),
    },
    "统计": {
        "level2": ("统计学类",),
        "level3": ("统计学",),
    },
    "土木": {
        "level2": ("土木类",),
        "level3": ("土木工程",),
    },
    "土木建筑": {
        "level2": ("土木类", "建筑类"),
        "level3": ("土木工程", "建筑学"),
    },
    "财会": {
        "level2": ("工商管理类",),
        "level3": ("会计学", "财务管理", "审计学"),
    },
    "财管": {
        "level2": ("工商管理类",),
        "level3": ("财务管理",),
    },
    "会计": {
        "level2": ("工商管理类",),
        "level3": ("会计学",),
    },
    "财务": {
        "level2": ("工商管理类",),
        "level3": ("财务管理",),
    },
    "审计": {
        "level2": ("工商管理类",),
        "level3": ("审计学",),
    },
    "新传": {
        "level2": ("新闻传播学类",),
        "level3": ("网络与新媒体", "新闻学", "传播学"),
    },
    "跨电": {
        "level2": ("电子商务类",),
        "level3": ("跨境电子商务",),
    },
    "国贸": {
        "level2": ("经济与贸易类",),
        "level3": ("国际经济与贸易",),
    },
    "中文": {
        "level2": ("中国语言文学类",),
        "level3": ("汉语言文学",),
    },
    "汉语言": {
        "level2": ("中国语言文学类",),
        "level3": ("汉语言文学",),
    },
    "新媒体": {
        "level2": ("新闻传播学类",),
        "level3": ("网络与新媒体",),
    },
    "临床": {
        "level2": ("临床医学类",),
        "level3": ("临床医学",),
    },
    "口腔": {
        "level2": ("口腔医学类",),
        "level3": ("口腔医学",),
    },
    "护理": {
        "level2": ("护理学类",),
        "level3": ("护理学",),
    },
    "中医": {
        "level2": ("中医学类",),
        "level3": ("中医学",),
    },
    "针推": {
        "level2": ("中医学类",),
        "level3": ("针灸推拿学",),
    },
    "针灸推拿": {
        "level2": ("中医学类",),
        "level3": ("针灸推拿学",),
    },
    "电气": {
        "level2": ("电气类",),
        "level3": ("电气工程及其自动化",),
    },
    "电子信息": {
        "level2": ("电子信息类",),
        "level3": ("电子信息工程",),
    },
    "机械": {
        "level2": ("机械类",),
        "level3": ("机械设计制造及其自动化",),
    },
    "师范": {
        "level2": ("教育学类",),
    },
    "老师": {
        "level2": ("教育学类",),
    },
    "教师": {
        "level2": ("教育学类",),
    },
}

# These aliases are usually spoken as broad category directions rather than a
# single concrete major. Keep the list explicit so concrete aliases such as
# "土木" and "会计" are not broadened by suffix heuristics.
CATEGORY_PREFERRED_MAJOR_ALIASES = frozenset(
    {
        "计算机",
        "电子信息",
    }
)


def _compact_alias_text(value: str | None) -> str:
    return "".join(str(value or "").split()).lower()


def resolve_deterministic_major_alias(
    alias: str,
    level: str,
    available_names: Iterable[str],
) -> str | None:
    """Resolve an exact alias only when it maps to exactly one available name."""

    compact_alias = _compact_alias_text(alias)
    if not compact_alias:
        return None

    aliases_by_level = COMMON_MAJOR_ALIAS_TABLE.get(compact_alias)
    if not aliases_by_level:
        return None

    candidates = aliases_by_level.get(level) or ()
    if len(candidates) != 1:
        return None

    candidate = candidates[0]
    available = set(available_names)
    return candidate if candidate in available else None


def resolve_major_alias_candidates_for_text(
    text: str,
    levels: Iterable[str] = ("level2", "level3"),
) -> list[str]:
    """Expand aliases mentioned in free-form text to major candidate names."""

    compact_text = _compact_alias_text(text)
    if not compact_text:
        return []

    ordered: list[str] = []
    seen: set[str] = set()
    for alias, aliases_by_level in COMMON_MAJOR_ALIAS_TABLE.items():
        if alias not in compact_text:
            continue
        for level in levels:
            for name in aliases_by_level.get(level, ()):
                if name not in seen:
                    ordered.append(name)
                    seen.add(name)
    return ordered
