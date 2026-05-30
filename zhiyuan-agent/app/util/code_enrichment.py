"""Code enrichment utilities for converting names to IDs/codes."""

import asyncio
import json
from functools import lru_cache
from pathlib import Path
from typing import Any
from loguru import logger

from app.data.major_aliases import resolve_deterministic_major_alias
from app.util.internal_client import (
    catalog_lookup_city,
    catalog_lookup_major,
    catalog_lookup_major_category,
    catalog_lookup_major_discipline,
    catalog_lookup_province,
    catalog_lookup_school,
    catalog_tree_filter_tags,
)


_catalog_school_item_cache: dict[str, dict[str, Any] | None] = {}
_catalog_major_item_cache: dict[tuple[str, str, str], dict[str, Any] | None] = {}
_catalog_province_item_cache: dict[str, dict[str, Any] | None] = {}
_catalog_city_item_cache: dict[str, dict[str, Any] | None] = {}
_catalog_filter_tag_tree_cache: dict[str, Any] | None = None


def _normalize_string_list(values: Any) -> list[str]:
    if not values:
        return []

    if isinstance(values, str):
        text = values.strip()
        return [text] if text else []

    if isinstance(values, dict):
        values = [values]

    normalized: list[str] = []
    for item in values:
        if isinstance(item, str):
            text = item.strip()
            if text:
                normalized.append(text)
            continue
        if isinstance(item, dict):
            text = item.get("value") or item.get("label") or item.get("name")
            if isinstance(text, str) and text.strip():
                normalized.append(text.strip())
    return normalized


def _batch_to_education_level(batch: str) -> str:
    return "专科" if batch == "02" else "本科"


def _extract_catalog_item(response: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(response, dict):
        return None
    if response.get("resultType") == "empty":
        return None
    data = response.get("data")
    if isinstance(data, list):
        return data[0] if data else None
    if isinstance(data, dict):
        return data
    return None


def _extract_catalog_values(response: dict[str, Any], *path: str) -> list[str]:
    data = response.get("data") if isinstance(response, dict) else None
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return []
        current = current.get(key)
    if not isinstance(current, list):
        return []
    return [item for item in current if isinstance(item, str) and item.strip()]


async def _lookup_cached_catalog_item(
    cache: dict[Any, dict[str, Any] | None],
    key: Any,
    fetcher,
    log_message: str,
) -> dict[str, Any] | None:
    if key in cache:
        return cache[key]
    try:
        cache[key] = _extract_catalog_item(await fetcher())
    except Exception:
        logger.warning(log_message, exc_info=True)
        cache[key] = None
    return cache[key]


async def _lookup_missing_values(
    names: list[str],
    fallback_by_name: dict[str, str],
    lookup_one,
) -> dict[str, str | None]:
    missing_names = [name for name in dict.fromkeys(names) if not fallback_by_name.get(name)]
    if not missing_names:
        return {}
    results = await asyncio.gather(*(lookup_one(name) for name in missing_names))
    return {name: value for name, value in results}


async def _get_filter_tag_tree() -> dict[str, Any]:
    global _catalog_filter_tag_tree_cache
    if _catalog_filter_tag_tree_cache is None:
        _catalog_filter_tag_tree_cache = await catalog_tree_filter_tags()
    return _catalog_filter_tag_tree_cache


@lru_cache(maxsize=2)
def _load_major_name_to_code_map(batch: str) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Load major name to code mappings for level1, level2 and level3."""
    if batch == "02":
        json_path = Path(__file__).parent.parent.parent / "data" / "option" / "major_associate.json"
    else:
        json_path = Path(__file__).parent.parent.parent / "data" / "option" / "major_bachelor.json"

    data = json.load(open(json_path, encoding="utf-8"))
    level1_map = {}
    level2_map = {}
    level3_map = {}

    for level1 in data["data"]:
        level1_map[level1["label"]] = level1["id"]
        for level2 in level1.get("children", []):
            level2_map[level2["label"]] = level2["id"]
            for level3 in level2.get("children", []):
                level3_map[level3["label"]] = level3["id"]

    return level1_map, level2_map, level3_map


def _compact_major_alias_text(value: str) -> str:
    return "".join(str(value or "").split()).replace("电子商务", "电商")


def _resolve_local_major_name_alias(name: str, level: str, local_map: dict[str, str]) -> str | None:
    if name in local_map:
        return name
    deterministic_alias = resolve_deterministic_major_alias(name, level, local_map.keys())
    if deterministic_alias:
        return deterministic_alias
    if f"{name}学" in local_map:
        return f"{name}学"
    compact_name = _compact_major_alias_text(name)
    if not compact_name:
        return None
    for standard_name in local_map:
        if _compact_major_alias_text(standard_name) == compact_name:
            return standard_name
    return None


@lru_cache(maxsize=1)
def _load_school_name_to_id_map() -> dict[str, str]:
    """Load school name to ID mapping."""
    import csv
    csv_path = Path(__file__).parent.parent.parent / "data" / "option" / "school_bachelor.csv"
    school_map = {}
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("标准院校名称", "").strip()
            school_id = row.get("标准院校id", "").strip()
            if name and school_id:
                school_map[name] = school_id
    return school_map


@lru_cache(maxsize=1)
def _load_province_city_maps() -> tuple[dict[str, str], dict[str, str]]:
    """Load province and city name to ID mappings."""
    json_path = Path(__file__).parent.parent.parent / "data" / "option" / "province_city.json"
    data = json.load(open(json_path, encoding="utf-8"))

    province_map = {}
    city_map = {}

    for province in data["data"]:
        province_map[province["label"]] = province["id"]
        for city in province.get("children", []):
            city_map[city["label"]] = city["id"]

    return province_map, city_map


def get_major_codes(major_names: list[str], level: str, batch: str) -> list[str]:
    """Convert major names to codes."""
    major_names = _normalize_string_list(major_names)
    if not major_names:
        return []

    level1_map, level2_map, level3_map = _load_major_name_to_code_map(batch)
    if level == "level1":
        code_map = level1_map
    elif level == "level2":
        code_map = level2_map
    else:
        code_map = level3_map

    codes = []
    for name in major_names:
        if name in code_map:
            codes.append(code_map[name])
        else:
            logger.warning(f"Major name '{name}' not found in {level} for batch {batch}")
    return codes


async def get_major_codes_async(major_names: list[str], level: str, batch: str) -> list[str]:
    major_names = _normalize_string_list(major_names)
    if not major_names:
        return []

    education_level = _batch_to_education_level(batch)
    fallback_codes = get_major_codes(major_names, level, batch)
    fallback_by_name = {name: code for name, code in zip(major_names, fallback_codes)}
    async def lookup_one(name: str) -> tuple[str, str | None]:
        if level == "level1":
            item = await _lookup_cached_catalog_item(
                _catalog_major_item_cache,
                (level, education_level, name),
                lambda: catalog_lookup_major_discipline(name, education_level),
                f"Catalog major lookup failed for '{name}' level={level} batch={batch}",
            )
            return name, item.get("categoryId") if item else None
        if level == "level2":
            item = await _lookup_cached_catalog_item(
                _catalog_major_item_cache,
                (level, education_level, name),
                lambda: catalog_lookup_major_category(name, education_level),
                f"Catalog major lookup failed for '{name}' level={level} batch={batch}",
            )
            return name, item.get("subCategoryId") if item else None
        item = await _lookup_cached_catalog_item(
            _catalog_major_item_cache,
            (level, education_level, name),
            lambda: catalog_lookup_major(name, education_level),
            f"Catalog major lookup failed for '{name}' level={level} batch={batch}",
        )
        return name, item.get("majorId") if item else None

    lookup_results = await _lookup_missing_values(major_names, fallback_by_name, lookup_one)
    codes: list[str] = []
    for name in major_names:
        code = fallback_by_name.get(name) or lookup_results.get(name)
        if code:
            codes.append(code)
        else:
            logger.warning(f"Major name '{name}' not found in {level} for batch {batch}")
    return codes


def get_school_codes(school_names: list[str]) -> list[str]:
    """Convert school names to IDs."""
    school_names = _normalize_string_list(school_names)
    if not school_names:
        return []

    school_map = _load_school_name_to_id_map()
    codes = []
    for name in school_names:
        if name in school_map:
            codes.append(school_map[name])
        else:
            logger.warning(f"School name '{name}' not found")
    return codes


async def get_school_codes_async(school_names: list[str]) -> list[str]:
    school_names = _normalize_string_list(school_names)
    if not school_names:
        return []

    fallback_codes = get_school_codes(school_names)
    fallback_by_name = {name: code for name, code in zip(school_names, fallback_codes)}
    async def lookup_one(name: str) -> tuple[str, str | None]:
        item = await _lookup_cached_catalog_item(
            _catalog_school_item_cache,
            name,
            lambda: catalog_lookup_school(name),
            f"Catalog school lookup failed for '{name}'",
        )
        return name, item.get("schoolId") if item else None

    lookup_results = await _lookup_missing_values(school_names, fallback_by_name, lookup_one)
    codes: list[str] = []
    for name in school_names:
        code = fallback_by_name.get(name) or lookup_results.get(name)
        if code:
            codes.append(code)
        else:
            logger.warning(f"School name '{name}' not found")
    return codes


def get_province_codes(province_names: list[str]) -> list[str]:
    """Convert province names to codes."""
    province_names = _normalize_string_list(province_names)
    if not province_names:
        return []

    province_map, _ = _load_province_city_maps()
    codes = []
    for name in province_names:
        if name in province_map:
            codes.append(province_map[name])
        else:
            logger.warning(f"Province name '{name}' not found")
    return codes


async def get_province_codes_async(province_names: list[str]) -> list[str]:
    province_names = _normalize_string_list(province_names)
    if not province_names:
        return []

    fallback_codes = get_province_codes(province_names)
    fallback_by_name = {name: code for name, code in zip(province_names, fallback_codes)}
    async def lookup_one(name: str) -> tuple[str, str | None]:
        item = await _lookup_cached_catalog_item(
            _catalog_province_item_cache,
            name,
            lambda: catalog_lookup_province(name),
            f"Catalog province lookup failed for '{name}'",
        )
        return name, item.get("provinceCode") if item else None

    lookup_results = await _lookup_missing_values(province_names, fallback_by_name, lookup_one)
    codes: list[str] = []
    for name in province_names:
        code = fallback_by_name.get(name) or lookup_results.get(name)
        if code:
            codes.append(code)
        else:
            logger.warning(f"Province name '{name}' not found")
    return codes


def get_city_codes(city_names: list[str]) -> list[str]:
    """Convert city names to codes."""
    city_names = _normalize_string_list(city_names)
    if not city_names:
        return []

    _, city_map = _load_province_city_maps()
    codes = []
    for name in city_names:
        if name in city_map:
            codes.append(city_map[name])
        else:
            logger.warning(f"City name '{name}' not found")
    return codes


async def get_city_codes_async(city_names: list[str]) -> list[str]:
    city_names = _normalize_string_list(city_names)
    if not city_names:
        return []

    fallback_codes = get_city_codes(city_names)
    fallback_by_name = {name: code for name, code in zip(city_names, fallback_codes)}
    async def lookup_one(name: str) -> tuple[str, str | None]:
        item = await _lookup_cached_catalog_item(
            _catalog_city_item_cache,
            name,
            lambda: catalog_lookup_city(name),
            f"Catalog city lookup failed for '{name}'",
        )
        return name, item.get("cityCode") if item else None

    lookup_results = await _lookup_missing_values(city_names, fallback_by_name, lookup_one)
    codes: list[str] = []
    for name in city_names:
        code = fallback_by_name.get(name) or lookup_results.get(name)
        if code:
            codes.append(code)
        else:
            logger.warning(f"City name '{name}' not found")
    return codes


async def _normalize_major_names_async(major_names: list[str], level: str, batch: str) -> list[str]:
    major_names = _normalize_string_list(major_names)
    if not major_names:
        return []
    education_level = _batch_to_education_level(batch)
    level1_map, level2_map, level3_map = _load_major_name_to_code_map(batch)
    local_map = level1_map if level == "level1" else level2_map if level == "level2" else level3_map
    fallback_by_name = {
        name: standard_name
        for name in major_names
        if (standard_name := _resolve_local_major_name_alias(name, level, local_map))
    }

    async def lookup_one(name: str) -> tuple[str, str | None]:
        if level == "level1":
            item = await _lookup_cached_catalog_item(
                _catalog_major_item_cache,
                (level, education_level, name),
                lambda: catalog_lookup_major_discipline(name, education_level),
                f"Catalog major normalization failed for '{name}' level={level} batch={batch}",
            )
            return name, item.get("categoryName") if item else None
        if level == "level2":
            item = await _lookup_cached_catalog_item(
                _catalog_major_item_cache,
                (level, education_level, name),
                lambda: catalog_lookup_major_category(name, education_level),
                f"Catalog major normalization failed for '{name}' level={level} batch={batch}",
            )
            return name, item.get("subCategoryName") if item else None
        item = await _lookup_cached_catalog_item(
            _catalog_major_item_cache,
            (level, education_level, name),
            lambda: catalog_lookup_major(name, education_level),
            f"Catalog major normalization failed for '{name}' level={level} batch={batch}",
        )
        return name, item.get("majorName") if item else None

    lookup_results = await _lookup_missing_values(major_names, fallback_by_name, lookup_one)
    normalized = [(fallback_by_name.get(name) or lookup_results.get(name) or name) for name in major_names]
    return list(dict.fromkeys(normalized))


async def resolve_major_names_async(major_names: list[str], level: str, batch: str) -> list[str]:
    """Resolve input major names to standardized names with local-first fallback."""
    return await _normalize_major_names_async(major_names, level, batch)


async def _normalize_school_names_async(school_names: list[str]) -> list[str]:
    school_names = _normalize_string_list(school_names)
    if not school_names:
        return []
    school_map = _load_school_name_to_id_map()
    fallback_by_name = {name: name for name in school_names if name in school_map}

    async def lookup_one(name: str) -> tuple[str, str | None]:
        item = await _lookup_cached_catalog_item(
            _catalog_school_item_cache,
            name,
            lambda: catalog_lookup_school(name),
            f"Catalog school normalization failed for '{name}'",
        )
        return name, item.get("schoolName") if item else None

    lookup_results = await _lookup_missing_values(school_names, fallback_by_name, lookup_one)
    normalized = [(fallback_by_name.get(name) or lookup_results.get(name) or name) for name in school_names]
    return list(dict.fromkeys(normalized))


async def resolve_school_names_async(school_names: list[str]) -> list[str]:
    """Resolve input school names to standardized names with local-first fallback."""
    return await _normalize_school_names_async(school_names)


async def _normalize_province_names_async(province_names: list[str]) -> list[str]:
    province_names = _normalize_string_list(province_names)
    if not province_names:
        return []
    province_map, _ = _load_province_city_maps()
    fallback_by_name = {name: name for name in province_names if name in province_map}

    async def lookup_one(name: str) -> tuple[str, str | None]:
        item = await _lookup_cached_catalog_item(
            _catalog_province_item_cache,
            name,
            lambda: catalog_lookup_province(name),
            f"Catalog province normalization failed for '{name}'",
        )
        return name, item.get("provinceName") if item else None

    lookup_results = await _lookup_missing_values(province_names, fallback_by_name, lookup_one)
    normalized = [(fallback_by_name.get(name) or lookup_results.get(name) or name) for name in province_names]
    return list(dict.fromkeys(normalized))


async def _normalize_city_names_async(city_names: list[str]) -> list[str]:
    city_names = _normalize_string_list(city_names)
    if not city_names:
        return []
    _, city_map = _load_province_city_maps()
    fallback_by_name = {name: name for name in city_names if name in city_map}

    async def lookup_one(name: str) -> tuple[str, str | None]:
        item = await _lookup_cached_catalog_item(
            _catalog_city_item_cache,
            name,
            lambda: catalog_lookup_city(name),
            f"Catalog city normalization failed for '{name}'",
        )
        return name, item.get("cityName") if item else None

    lookup_results = await _lookup_missing_values(city_names, fallback_by_name, lookup_one)
    normalized = [(fallback_by_name.get(name) or lookup_results.get(name) or name) for name in city_names]
    return list(dict.fromkeys(normalized))


async def _normalize_school_tags_async(school_tags: list[str]) -> list[str]:
    school_tags = _normalize_string_list(school_tags)
    if not school_tags:
        return []
    try:
        tree = await _get_filter_tag_tree()
        allowed = set(
            _extract_catalog_values(tree, "school", "category")
            + _extract_catalog_values(tree, "school", "nature")
            + _extract_catalog_values(tree, "school", "feature")
            + _extract_catalog_values(tree, "school", "level")
        )
        normalized = [tag for tag in school_tags if tag in allowed]
        if normalized:
            return list(dict.fromkeys(normalized))
    except Exception:
        logger.warning("Catalog school tag normalization failed", exc_info=True)
    return list(dict.fromkeys(school_tags))


async def normalize_candidate_filters_async(candidate_filters: dict[str, Any], batch: str) -> dict[str, Any]:
    normalized = dict(candidate_filters or {})
    normalized["provinceNames"] = await _normalize_province_names_async(normalized.get("provinceNames"))
    normalized["negativeProvinceNames"] = await _normalize_province_names_async(normalized.get("negativeProvinceNames"))
    normalized["cityNames"] = await _normalize_city_names_async(normalized.get("cityNames"))
    normalized["negativeCityNames"] = await _normalize_city_names_async(normalized.get("negativeCityNames"))
    normalized["schoolKeywords"] = await _normalize_school_names_async(normalized.get("schoolKeywords"))
    normalized["negativeSchoolKeywords"] = await _normalize_school_names_async(normalized.get("negativeSchoolKeywords"))
    normalized["schoolTags"] = await _normalize_school_tags_async(normalized.get("schoolTags"))
    normalized["negativeSchoolTags"] = await _normalize_school_tags_async(normalized.get("negativeSchoolTags"))
    normalized["majorKeywords"] = await _normalize_major_names_async(normalized.get("majorKeywords"), "level2", batch)
    normalized["negativeMajorKeywords"] = await _normalize_major_names_async(normalized.get("negativeMajorKeywords"), "level2", batch)
    normalized["majorTags"] = await _normalize_major_names_async(normalized.get("majorTags"), "level1", batch)
    normalized["negativeMajorTags"] = await _normalize_major_names_async(normalized.get("negativeMajorTags"), "level1", batch)
    return normalized


def add_codes_to_profile(user_profile: dict[str, Any], batch: str) -> dict[str, Any]:
    """Enrich user profile with code fields (old format)."""
    enriched = user_profile.copy()

    # Enrich major codes
    if "major_intent" in enriched:
        major = enriched["major_intent"]
        major["level1"] = _normalize_string_list(major.get("level1"))
        major["level2"] = _normalize_string_list(major.get("level2"))
        major["level3"] = _normalize_string_list(major.get("level3"))
        if major.get("level1"):
            major["level1_code"] = get_major_codes(major["level1"], "level1", batch)
        if major.get("level2"):
            major["level2_code"] = get_major_codes(major["level2"], "level2", batch)
        if major.get("level3"):
            major["level3_code"] = get_major_codes(major["level3"], "level3", batch)

    if "negative_major_intent" in enriched:
        neg_major = enriched["negative_major_intent"]
        neg_major["level1"] = _normalize_string_list(neg_major.get("level1"))
        neg_major["level2"] = _normalize_string_list(neg_major.get("level2"))
        neg_major["level3"] = _normalize_string_list(neg_major.get("level3"))
        if neg_major.get("level1"):
            neg_major["level1_code"] = get_major_codes(neg_major["level1"], "level1", batch)
        if neg_major.get("level2"):
            neg_major["level2_code"] = get_major_codes(neg_major["level2"], "level2", batch)
        if neg_major.get("level3"):
            neg_major["level3_code"] = get_major_codes(neg_major["level3"], "level3", batch)

    # Enrich school codes
    if "college_info" in enriched:
        college = enriched["college_info"]
        college["values"] = _normalize_string_list(college.get("values"))
        if college.get("values"):
            college["values_code"] = get_school_codes(college["values"])

    if "negative_college_info" in enriched:
        neg_college = enriched["negative_college_info"]
        neg_college["values"] = _normalize_string_list(neg_college.get("values"))
        if neg_college.get("values"):
            neg_college["values_code"] = get_school_codes(neg_college["values"])

    # Enrich city codes
    if "city_info" in enriched:
        city = enriched["city_info"]
        city["province"] = _normalize_string_list(city.get("province"))
        city["city"] = _normalize_string_list(city.get("city"))
        if city.get("province"):
            city["province_code"] = get_province_codes(city["province"])
        if city.get("city"):
            city["city_code"] = get_city_codes(city["city"])

    if "negative_city_info" in enriched:
        neg_city = enriched["negative_city_info"]
        neg_city["province"] = _normalize_string_list(neg_city.get("province"))
        neg_city["city"] = _normalize_string_list(neg_city.get("city"))
        if neg_city.get("province"):
            neg_city["province_code"] = get_province_codes(neg_city["province"])
        if neg_city.get("city"):
            neg_city["city_code"] = get_city_codes(neg_city["city"])

    logger.debug("Enriched user profile with codes: {}", enriched)
    return enriched


async def add_codes_to_profile_async(user_profile: dict[str, Any], batch: str) -> dict[str, Any]:
    enriched = user_profile.copy()

    if "major_intent" in enriched:
        major = enriched["major_intent"]
        major["level1"] = _normalize_string_list(major.get("level1"))
        major["level2"] = _normalize_string_list(major.get("level2"))
        major["level3"] = _normalize_string_list(major.get("level3"))
        if major.get("level1"):
            major["level1_code"] = await get_major_codes_async(major["level1"], "level1", batch)
        if major.get("level2"):
            major["level2_code"] = await get_major_codes_async(major["level2"], "level2", batch)
        if major.get("level3"):
            major["level3_code"] = await get_major_codes_async(major["level3"], "level3", batch)

    if "negative_major_intent" in enriched:
        neg_major = enriched["negative_major_intent"]
        neg_major["level1"] = _normalize_string_list(neg_major.get("level1"))
        neg_major["level2"] = _normalize_string_list(neg_major.get("level2"))
        neg_major["level3"] = _normalize_string_list(neg_major.get("level3"))
        if neg_major.get("level1"):
            neg_major["level1_code"] = await get_major_codes_async(neg_major["level1"], "level1", batch)
        if neg_major.get("level2"):
            neg_major["level2_code"] = await get_major_codes_async(neg_major["level2"], "level2", batch)
        if neg_major.get("level3"):
            neg_major["level3_code"] = await get_major_codes_async(neg_major["level3"], "level3", batch)

    if "college_info" in enriched:
        college = enriched["college_info"]
        college["values"] = _normalize_string_list(college.get("values"))
        if college.get("values"):
            college["values_code"] = await get_school_codes_async(college["values"])

    if "negative_college_info" in enriched:
        neg_college = enriched["negative_college_info"]
        neg_college["values"] = _normalize_string_list(neg_college.get("values"))
        if neg_college.get("values"):
            neg_college["values_code"] = await get_school_codes_async(neg_college["values"])

    if "city_info" in enriched:
        city = enriched["city_info"]
        city["province"] = _normalize_string_list(city.get("province"))
        city["city"] = _normalize_string_list(city.get("city"))
        if city.get("province"):
            city["province_code"] = await get_province_codes_async(city["province"])
        if city.get("city"):
            city["city_code"] = await get_city_codes_async(city["city"])

    if "negative_city_info" in enriched:
        neg_city = enriched["negative_city_info"]
        neg_city["province"] = _normalize_string_list(neg_city.get("province"))
        neg_city["city"] = _normalize_string_list(neg_city.get("city"))
        if neg_city.get("province"):
            neg_city["province_code"] = await get_province_codes_async(neg_city["province"])
        if neg_city.get("city"):
            neg_city["city_code"] = await get_city_codes_async(neg_city["city"])

    logger.debug("Enriched user profile with codes via catalog/local fallback: {}", enriched)
    return enriched
