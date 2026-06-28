"""Reusable school entity resolution backed by the official school catalog."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from app.data.school_data import (
    associate_school_set,
    bachelor_school_set,
)
from app.domain.entity_resolution import EntityResolutionCandidate, EntityResolutionResult


_SCHOOL_SUFFIX_ALIAS_RULES = (
    ("师范大学", "师大"),
    ("工业大学", "工大"),
    ("农业大学", "农大"),
    ("医科大学", "医大"),
    ("财经大学", "财大"),
    ("外国语大学", "外大"),
    ("科技大学", "科大"),
    ("交通大学", "交大"),
    ("邮电大学", "邮电"),
    ("理工大学", "理工"),
    ("工程学院", "工程"),
)

_SCHOOL_PREFIX_SHORT_NAMES = {
    "北京": "北",
    "上海": "上",
    "南京": "南",
    "武汉": "武",
    "湖北": "湖",
    "湖南": "湖",
    "广西": "桂",
    "广东": "粤",
    "山东": "鲁",
    "山西": "晋",
    "河北": "冀",
    "河南": "豫",
    "四川": "川",
    "重庆": "渝",
    "天津": "津",
    "浙江": "浙",
    "江苏": "苏",
    "安徽": "皖",
    "福建": "闽",
    "江西": "赣",
    "陕西": "陕",
    "辽宁": "辽",
    "吉林": "吉",
    "黑龙江": "黑",
    "云南": "云",
    "贵州": "贵",
    "甘肃": "甘",
    "青海": "青",
    "宁夏": "宁",
    "新疆": "新",
    "内蒙古": "蒙",
    "西藏": "藏",
    "海南": "琼",
}


def compact_school_text(value: Any) -> str:
    return re.sub(r"[\s\-_/·.。,:：，、的]+", "", str(value or "")).lower()


def school_name_set_for_batch(batch: str | None = "01") -> set[str]:
    return associate_school_set if batch and batch != "01" else bachelor_school_set


def _strip_school_group_suffix(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s*[（(][^()（）]*[)）]\s*$", "", text).strip()
    text = re.sub(r"\s*(?:第?\d+组|[A-Za-z0-9]+专业组|第?\d+专业组|专业组)\s*$", "", text).strip()
    return text


def school_alias_variants(value: Any) -> list[str]:
    base_name = _strip_school_group_suffix(str(value or ""))
    if not base_name:
        return []

    aliases: list[str] = []
    for suffix, suffix_alias in _SCHOOL_SUFFIX_ALIAS_RULES:
        if not base_name.endswith(suffix):
            continue
        prefix = base_name[: -len(suffix)].strip()
        if not prefix:
            continue
        aliases.append(f"{prefix}{suffix_alias}")
        short_prefix = _SCHOOL_PREFIX_SHORT_NAMES.get(prefix)
        if short_prefix:
            aliases.append(f"{short_prefix}{suffix_alias[:1]}")
    return list(dict.fromkeys(alias for alias in aliases if alias and alias != base_name))


@lru_cache(maxsize=2)
def school_alias_index_for_batch(batch: str | None = "01") -> dict[str, tuple[str, ...]]:
    raw: dict[str, list[str]] = {}
    for school_name in school_name_set_for_batch(batch):
        for alias in school_alias_variants(school_name):
            raw.setdefault(compact_school_text(alias), []).append(school_name)
    return {
        alias: tuple(dict.fromkeys(names))
        for alias, names in raw.items()
    }


def resolve_school_mention_spans_from_text(text: str, batch: str | None = "01") -> list[tuple[str, int, int]]:
    compact = compact_school_text(text)
    if not compact:
        return []
    raw_matches: list[tuple[int, int, str]] = []

    def add_match(raw_token: str, canonical_name: str) -> None:
        compact_token = compact_school_text(raw_token)
        if not compact_token:
            return
        start = compact.find(compact_token)
        if start < 0:
            return
        raw_matches.append((start, len(compact_token), canonical_name))

    for school_name in school_name_set_for_batch(batch):
        add_match(school_name, school_name)
    for alias, canonical_names in school_alias_index_for_batch(batch).items():
        if not alias or alias not in compact:
            continue
        for canonical_name in canonical_names:
            add_match(alias, canonical_name)

    raw_matches.sort(key=lambda item: (item[0], -item[1], item[2]))
    matches: list[tuple[str, int, int]] = []
    occupied: list[tuple[int, int]] = []
    for start, length, school_name in raw_matches:
        end = start + length
        if any(not (end <= used_start or start >= used_end) for used_start, used_end in occupied):
            continue
        if school_name not in {name for name, _, _ in matches}:
            matches.append((school_name, start, end))
        occupied.append((start, end))
    return matches


def resolve_school_mentions_from_text(text: str, batch: str | None = "01") -> list[str]:
    return [name for name, _, _ in resolve_school_mention_spans_from_text(text, batch)]


def _candidate(
    *,
    raw_text: str,
    canonical_name: str,
    source: str,
    confidence: str = "high",
) -> EntityResolutionCandidate:
    return EntityResolutionCandidate(
        entity_type="school",
        raw_text=raw_text,
        canonical_name=canonical_name,
        source=source,  # type: ignore[arg-type]
        confidence=confidence,  # type: ignore[arg-type]
    )


def resolve_school_entity(text: str, batch: str | None = "01") -> EntityResolutionResult:
    raw_text = str(text or "").strip()
    compact = compact_school_text(raw_text)
    if not compact:
        return EntityResolutionResult(raw_text=raw_text, entity_type="school")

    school_names = school_name_set_for_batch(batch)
    candidates: list[EntityResolutionCandidate] = []
    seen: set[str] = set()

    def append(name: str, source: str, confidence: str = "high") -> None:
        if name not in school_names or name in seen:
            return
        candidates.append(
            _candidate(
                raw_text=raw_text,
                canonical_name=name,
                source=source,
                confidence=confidence,
            )
        )
        seen.add(name)

    for name in school_names:
        if compact_school_text(name) == compact:
            append(name, "exact")

    for name in school_alias_index_for_batch(batch).get(compact, ()):
        append(name, "auto_alias")

    if not candidates:
        for name in school_names:
            compact_name = compact_school_text(name)
            if compact in compact_name or compact_name in compact:
                append(name, "catalog", "medium")
                if len(candidates) >= 10:
                    break

    return EntityResolutionResult(
        raw_text=raw_text,
        entity_type="school",
        candidates=tuple(candidates),
        ambiguous=len(candidates) > 1,
    )
