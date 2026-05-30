"""Shared candidate query filter extraction.

This module is an input parser for one-turn candidate-pool queries. It does
not update long-term user intent and does not route directly to a reply path.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic_ai import Agent

from app.config import LLMConfig
from app.llm.client import LLMClient
from app.schemas.candidate_filter import CandidateFilterExtractionResult
from app.tools.extraction_json import parse_extraction_json
from app.util.code_enrichment import (
    _extract_catalog_values,
    _get_filter_tag_tree,
    _normalize_city_names_async,
    _normalize_province_names_async,
    _normalize_school_names_async,
    _normalize_school_tags_async,
    resolve_major_names_async,
)

logger = logging.getLogger(__name__)

_extraction_client: LLMClient | None = None
_VALID_TIERS = {"冲", "稳", "保"}
_TAG_VALUE_SUFFIXES = ("类院校", "类学校", "院校", "学校", "方向", "专业", "类")


def _get_extraction_client() -> LLMClient:
    global _extraction_client
    if _extraction_client is None:
        _extraction_client = LLMClient(LLMConfig())
    return _extraction_client


def _normalize_text_list(values: Any) -> list[str]:
    if not values:
        return []
    if isinstance(values, str):
        text = values.strip()
        return [text] if text else []
    normalized: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _merge_unique(base: list[str], extra: list[str]) -> list[str]:
    merged: list[str] = []
    for value in [*base, *extra]:
        text = str(value or "").strip()
        if text and text not in merged:
            merged.append(text)
    return merged


def _candidate_tag_value_variants(value: str) -> list[str]:
    """Build conservative variants for filter-tag values.

    This is value normalization after LLM extraction, not a route keyword
    shortcut. It only removes common category suffixes so values can match the
    catalog tag vocabulary, for example 师范类 -> 师范.
    """
    text = str(value or "").strip()
    if not text:
        return []
    variants = [text]
    changed = True
    while changed:
        changed = False
        current = variants[-1]
        for suffix in _TAG_VALUE_SUFFIXES:
            if current.endswith(suffix) and len(current) > len(suffix):
                stripped = current[: -len(suffix)].strip()
                if stripped and stripped not in variants:
                    variants.append(stripped)
                changed = True
                break
    return variants


def _filter_values_by_allowed_catalog(values: list[str], allowed_values: set[str]) -> list[str]:
    normalized: list[str] = []
    for value in _normalize_text_list(values):
        for variant in _candidate_tag_value_variants(value):
            if variant in allowed_values and variant not in normalized:
                normalized.append(variant)
                break
    return normalized


def _normalize_school_tag_values_by_catalog(values: list[str], allowed_values: set[str]) -> list[str]:
    normalized: list[str] = []
    for value in _normalize_text_list(values):
        matched = None
        for variant in _candidate_tag_value_variants(value):
            if variant in allowed_values:
                matched = variant
                break
        target = matched or value
        if target and target not in normalized:
            normalized.append(target)
    return normalized


def _extract_major_level2_category_names(tree: dict[str, Any]) -> list[str]:
    data = tree.get("data") if isinstance(tree, dict) else None
    major = data.get("major") if isinstance(data, dict) else None
    categories = major.get("category") if isinstance(major, dict) else None
    if not isinstance(categories, list):
        return []
    values: list[str] = []
    for node in categories:
        if not isinstance(node, dict):
            continue
        children = node.get("children")
        if not isinstance(children, list):
            continue
        for child in children:
            if not isinstance(child, dict):
                continue
            sub_category_name = child.get("subCategoryName")
            if isinstance(sub_category_name, str) and sub_category_name.strip():
                values.append(sub_category_name.strip())
    return values


async def _normalize_candidate_school_tags_async(school_tags: list[str]) -> list[str]:
    raw_tags = _normalize_text_list(school_tags)
    if not raw_tags:
        return []
    try:
        tree = await _get_filter_tag_tree()
        allowed_tags = set(
            _extract_catalog_values(tree, "school", "category")
            + _extract_catalog_values(tree, "school", "nature")
            + _extract_catalog_values(tree, "school", "feature")
            + _extract_catalog_values(tree, "school", "level")
        )
        if not allowed_tags:
            return await _normalize_school_tags_async(raw_tags)
        return _normalize_school_tag_values_by_catalog(raw_tags, allowed_tags)
    except Exception:
        logger.warning("Catalog candidate school tag normalization failed", exc_info=True)
        return await _normalize_school_tags_async(raw_tags)


async def _normalize_major_tags_async(major_tags: list[str], batch: str) -> list[str]:
    raw_tags = _normalize_text_list(major_tags)
    if not raw_tags:
        return []

    resolved_level1 = await resolve_major_names_async(raw_tags, "level1", batch)
    try:
        tree = await _get_filter_tag_tree()
        allowed_tags = set(
            _extract_catalog_values(tree, "major", "discipline")
            + _extract_catalog_values(tree, "admission", "type")
            + _extract_catalog_values(tree, "constraint", "limit")
        )
        if not allowed_tags:
            return list(dict.fromkeys(resolved_level1))
        allowed_major_keywords = set(_extract_major_level2_category_names(tree))
        normalized = _filter_values_by_allowed_catalog([*resolved_level1, *raw_tags], allowed_tags)
        # Values that are actually major categories should be carried by
        # major_keywords, not major_tags. Dropping them here prevents an extra
        # AND tag filter from hiding valid candidates.
        normalized = [tag for tag in normalized if tag not in allowed_major_keywords]
        if normalized:
            return list(dict.fromkeys(normalized))
        return []
    except Exception:
        logger.warning("Catalog major tag normalization failed", exc_info=True)
        return list(dict.fromkeys(resolved_level1))


def _major_values_from_result(result: CandidateFilterExtractionResult) -> tuple[list[str], list[str]]:
    """Map extracted major hierarchy into candidate-pool runtime fields.

    Candidate pool keeps the historical naming:
    - majorKeywords: concrete major names and major categories
    - majorTags: discipline/admission/constraint tags
    """
    major_keywords = _normalize_text_list(result.majorKeywords)
    major_tags = _normalize_text_list(result.majorTags)
    return major_keywords, major_tags


async def normalize_candidate_query_filters_async(
    filters: dict[str, Any],
    *,
    batch: str | None,
) -> dict[str, list[str]]:
    """Normalize candidate query filters with catalog-backed helpers."""
    batch_value = batch or "01"
    tiers = [tier for tier in _normalize_text_list(filters.get("tiers")) if tier in _VALID_TIERS]
    major_keywords = _normalize_text_list(filters.get("major_keywords"))
    major_tags = _normalize_text_list(filters.get("major_tags"))
    normalized_major_keywords: list[str] = []
    if major_keywords:
        level2_values = await resolve_major_names_async(major_keywords, "level2", batch_value)
        level3_values = await resolve_major_names_async(major_keywords, "level3", batch_value)
        for raw, level2, level3 in zip(major_keywords, level2_values, level3_values):
            resolved = level2 if raw.endswith("类") and level2 else level3 or level2 or raw
            if resolved and resolved not in normalized_major_keywords:
                normalized_major_keywords.append(resolved)

    return {
        "tiers": tiers,
        "province_names": await _normalize_province_names_async(filters.get("province_names")),
        "city_names": await _normalize_city_names_async(filters.get("city_names")),
        "school_keywords": await _normalize_school_names_async(filters.get("school_keywords")),
        "major_keywords": normalized_major_keywords,
        "school_tags": await _normalize_candidate_school_tags_async(filters.get("school_tags")),
        "major_tags": await _normalize_major_tags_async(major_tags, batch_value),
    }


def _build_extraction_prompt(query_text: str) -> str:
    return f"""
# 【任务】
你是高考志愿候选池查询条件抽取器。请只根据用户这一次的查询诉求，抽取用于“候选志愿池查询”的筛选条件。

# 【用户输入】
{query_text}

# 【抽取边界】
1. 只抽取本轮候选查询要用的条件，不更新长期偏好，不生成回复。
2. 如果用户是在说“候选里还有没有、还能不能选、先查一下、别直接加、不要改方案”等机会查询，shouldQueryCandidate=true。
3. 如果用户是在要求直接移动、删除、加入、排序、审查方案，且不是候选机会查询，shouldQueryCandidate=false。
4. “更稳/稳一点/稳妥”映射 tiers=["稳"]；“保底/兜底/保险”映射 tiers=["保"]；“冲一冲/冲档”映射 tiers=["冲"]。
5. 专业、专业类、专业简称要尽量还原为候选池可查的专业名称或专业大类，例如“财会/会计/审计”应抽取相应专业或专业大类，“计科”应抽取计算机相关具体专业或专业类。
6. “师范类机会/财经类学校/医药类院校”等如果表达的是院校类型，放入 schoolTags；如果表达的是专业方向，放入 majorKeywords 或 majorTags。
7. 省份放 provinceNames，城市放 cityNames；院校全称或简称解析后的目标院校放 schoolKeywords。
8. 不确定时不要编造，可把不确定点写入 ambiguities，confidence 降低。

# 【返回格式】
只返回 JSON，不要解释：
{{
  "shouldQueryCandidate": true,
  "tiers": [],
  "provinceNames": [],
  "cityNames": [],
  "schoolKeywords": [],
  "majorKeywords": [],
  "schoolTags": [],
  "majorTags": [],
  "confidence": 0.0,
  "ambiguities": []
}}
"""


async def extract_candidate_query_filters_async(
    query_text: str,
    *,
    batch: str | None,
) -> dict[str, Any]:
    """Extract and normalize one-turn candidate-pool filters."""
    text = str(query_text or "").strip()
    if not text:
        return {
            "should_query_candidate": False,
            "confidence": 0.0,
            "ambiguities": [],
            "filters": {
                "tiers": [],
                "province_names": [],
                "city_names": [],
                "school_keywords": [],
                "major_keywords": [],
                "school_tags": [],
                "major_tags": [],
            },
        }

    logger.info("extract_candidate_query_filters_async called: text=%s", text)
    extraction_agent = Agent(
        model=_get_extraction_client().model,
        output_type=str,
        instructions=_build_extraction_prompt(text),
    )
    result = await extraction_agent.run("请抽取候选池查询条件", model_settings={"temperature": 0})
    parsed = parse_extraction_json(result.output, CandidateFilterExtractionResult)
    major_keywords, major_tags = _major_values_from_result(parsed)
    raw_filters = {
        "tiers": parsed.tiers,
        "province_names": parsed.provinceNames,
        "city_names": parsed.cityNames,
        "school_keywords": parsed.schoolKeywords,
        "major_keywords": major_keywords,
        "school_tags": parsed.schoolTags,
        "major_tags": major_tags,
    }
    normalized_filters = await normalize_candidate_query_filters_async(raw_filters, batch=batch)
    logger.info(
        "extract_candidate_query_filters_async result: should_query_candidate=%s confidence=%s raw_filters=%s normalized_filters=%s ambiguities=%s",
        parsed.shouldQueryCandidate,
        parsed.confidence,
        raw_filters,
        normalized_filters,
        parsed.ambiguities,
    )
    return {
        "should_query_candidate": parsed.shouldQueryCandidate,
        "confidence": parsed.confidence,
        "ambiguities": parsed.ambiguities,
        "filters": normalized_filters,
        "raw": json.loads(parsed.model_dump_json()),
    }
