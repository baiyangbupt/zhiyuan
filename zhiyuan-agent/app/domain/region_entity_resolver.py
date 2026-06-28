"""Reusable region entity resolution backed by the province/city catalog."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.domain.entity_resolution import EntityResolutionCandidate, EntityResolutionResult


_REGION_SUFFIXES = (
    "维吾尔自治区",
    "壮族自治区",
    "回族自治区",
    "自治区",
    "特别行政区",
    "省",
    "市",
)

_PROVINCE_ALIASES = {
    "内蒙": "内蒙古",
    "广西壮族": "广西",
    "新疆维吾尔": "新疆",
    "宁夏回族": "宁夏",
}

_AREA_ALIASES = {
    "长三角": "长三角",
    "长三角地区": "长三角",
    "珠三角": "珠三角",
    "珠三角地区": "珠三角",
    "江浙沪": "长三角",
    "华东": "华东",
    "华东地区": "华东",
    "华北": "华北",
    "华北地区": "华北",
    "华中": "华中",
    "华中地区": "华中",
    "华南": "华南",
    "华南地区": "华南",
    "东北": "东北",
    "东北地区": "东北",
    "东三省": "东北",
    "西北": "西北",
    "西北地区": "西北",
    "西南": "西南",
    "西南地区": "西南",
    "东南": "东南",
    "东南地区": "东南",
    "中南": "中南",
    "中南地区": "中南",
    "南方": "南方",
    "南方地区": "南方",
    "南边": "南方",
    "北方": "北方",
    "北方地区": "北方",
    "北边": "北方",
}

REGION_AREA_PROVINCES = {
    "南方": (
        "浙江",
        "上海",
        "湖南",
        "湖北",
        "江西",
        "福建",
        "云南",
        "贵州",
        "四川",
        "重庆",
        "广东",
        "广西",
        "海南",
        "江苏",
        "安徽",
    ),
    "北方": (
        "黑龙江",
        "吉林",
        "辽宁",
        "内蒙古",
        "新疆",
        "西藏",
        "青海",
        "甘肃",
        "宁夏",
        "陕西",
        "山西",
        "山东",
        "河北",
        "北京",
        "天津",
    ),
}


def compact_region_text(value: Any) -> str:
    return "".join(str(value or "").split()).lower()


def _strip_region_suffix(value: Any) -> str:
    text = str(value or "").strip()
    for suffix in _REGION_SUFFIXES:
        if text.endswith(suffix):
            return text[: -len(suffix)].strip()
    return text


@lru_cache(maxsize=1)
def _province_city_name_sets() -> tuple[set[str], set[str]]:
    json_path = Path(__file__).resolve().parent.parent.parent / "data" / "option" / "province_city.json"
    data = json.load(open(json_path, encoding="utf-8"))
    provinces: set[str] = set()
    cities: set[str] = set()
    for province in data.get("data", []):
        province_name = str(province.get("label") or "").strip()
        if province_name:
            provinces.add(province_name)
        for city in province.get("children", []) or []:
            city_name = str(city.get("label") or "").strip()
            if city_name:
                cities.add(city_name)
    return provinces, cities


def _candidate(
    *,
    raw_text: str,
    canonical_name: str,
    level: str,
    source: str,
    confidence: str = "high",
) -> EntityResolutionCandidate:
    return EntityResolutionCandidate(
        entity_type="region",
        raw_text=raw_text,
        canonical_name=canonical_name,
        level=level,
        source=source,  # type: ignore[arg-type]
        confidence=confidence,  # type: ignore[arg-type]
    )


def resolve_region_entity(text: Any, expected_level: str | None = None) -> EntityResolutionResult:
    """Resolve a province/city expression to catalog names.

    The resolver is intentionally conservative: ambiguous province/city names
    return multiple candidates and callers must avoid mutating state from them.
    """

    raw_text = str(text or "").strip()
    compact = compact_region_text(raw_text)
    if not compact:
        return EntityResolutionResult(raw_text=raw_text, entity_type="region")

    provinces, cities = _province_city_name_sets()
    candidates: list[EntityResolutionCandidate] = []
    seen: set[tuple[str, str]] = set()

    def append(level: str, name: str, source: str, confidence: str = "high") -> None:
        if expected_level and level != expected_level:
            return
        if (level, name) in seen:
            return
        candidates.append(
            _candidate(
                raw_text=raw_text,
                canonical_name=name,
                level=level,
                source=source,
                confidence=confidence,
            )
        )
        seen.add((level, name))

    alias = _PROVINCE_ALIASES.get(_strip_region_suffix(raw_text), "")
    if alias and alias in provinces:
        append("province", alias, "alias")

    area_alias = _AREA_ALIASES.get(_strip_region_suffix(raw_text), "")
    if area_alias:
        append("area", area_alias, "alias")

    stripped = _strip_region_suffix(raw_text)
    for province in provinces:
        if compact_region_text(province) == compact or compact_region_text(province) == compact_region_text(stripped):
            append("province", province, "exact")
    for city in cities:
        if compact_region_text(city) == compact or compact_region_text(city) == compact_region_text(stripped):
            append("city", city, "exact")

    return EntityResolutionResult(
        raw_text=raw_text,
        entity_type="region",
        candidates=tuple(candidates),
        ambiguous=len({(candidate.level, candidate.canonical_name) for candidate in candidates}) > 1,
    )


def normalize_region_name(text: Any, expected_level: str | None = None) -> str:
    result = resolve_region_entity(text, expected_level=expected_level)
    return result.best.canonical_name if result.best else str(text or "").strip()


def normalize_region_names(values: Any, expected_level: str | None = None) -> list[str]:
    raw_values = values if isinstance(values, list) else [values] if values else []
    normalized: list[str] = []
    for value in raw_values:
        text = str(value or "").strip()
        if not text:
            continue
        name = normalize_region_name(text, expected_level=expected_level)
        if name and name not in normalized:
            normalized.append(name)
    return normalized


def resolve_region_mentions_from_text(text: Any, expected_level: str | None = None) -> list[EntityResolutionCandidate]:
    """Find concrete province/city mentions in free text using the region catalog."""

    raw_text = str(text or "").strip()
    compact = compact_region_text(raw_text)
    if not compact:
        return []
    provinces, cities = _province_city_name_sets()
    raw_matches: list[tuple[int, int, EntityResolutionCandidate]] = []

    def append(raw_name: str, canonical_name: str, level: str, source: str) -> None:
        if expected_level and level != expected_level:
            return
        variants = {
            compact_region_text(raw_name),
            compact_region_text(_strip_region_suffix(raw_name)),
        }
        for variant in variants:
            if not variant:
                continue
            search_start = 0
            while True:
                start = compact.find(variant, search_start)
                if start < 0:
                    break
                raw_matches.append(
                    (
                        start,
                        len(variant),
                        _candidate(
                            raw_text=raw_name,
                            canonical_name=canonical_name,
                            level=level,
                            source=source,
                        ),
                    )
                )
                search_start = start + 1

    for alias, canonical_name in _PROVINCE_ALIASES.items():
        if canonical_name in provinces:
            append(alias, canonical_name, "province", "alias")
    for alias, canonical_name in _AREA_ALIASES.items():
        append(alias, canonical_name, "area", "alias")
    for province in provinces:
        append(province, province, "province", "exact")
    for city in cities:
        append(city, city, "city", "exact")

    raw_matches.sort(key=lambda item: (item[0], -item[1], item[2].level or "", item[2].canonical_name))
    result: list[EntityResolutionCandidate] = []
    seen: set[tuple[str, str]] = set()
    occupied: list[tuple[int, int]] = []
    for start, length, candidate in raw_matches:
        end = start + length
        if any(not (end <= used_start or start >= used_end) for used_start, used_end in occupied):
            continue
        key = (candidate.level or "", candidate.canonical_name)
        if key in seen:
            continue
        seen.add(key)
        occupied.append((start, end))
        result.append(candidate)
    return result


def contains_concrete_region_mention(text: Any) -> bool:
    """Return whether free text names a concrete province/city from the catalog."""

    compact = compact_region_text(text)
    if not compact:
        return False
    provinces, cities = _province_city_name_sets()
    aliases = set(_PROVINCE_ALIASES)
    area_aliases = set(_AREA_ALIASES)
    for name in provinces | cities | aliases | area_aliases:
        raw_name = str(name or "").strip()
        if not raw_name:
            continue
        variants = {compact_region_text(raw_name), compact_region_text(_strip_region_suffix(raw_name))}
        if any(variant and variant in compact for variant in variants):
            return True
    return False
