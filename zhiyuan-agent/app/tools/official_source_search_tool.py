"""Official-source web search tool."""

from __future__ import annotations

import json
from typing import Any, Literal
from urllib.parse import urlparse

import aiohttp
from pydantic_ai import RunContext

from app.agent.context import RequestContext
from app.config import BochaSearchConfig


SearchSourceScope = Literal[
    "general_official",
    "province_policy",
    "school_brochure",
    "school_admissions_notice",
]

SearchFreshness = Literal[
    "noLimit",
    "oneDay",
    "oneWeek",
    "oneMonth",
    "oneYear",
]


_PROVINCE_OFFICIAL_DOMAINS: dict[str, tuple[str, ...]] = {
    "山东": ("sdzk.cn",),
}

_SCHOOL_ADMISSION_DOMAINS: dict[str, tuple[str, ...]] = {
    "北京工业大学": ("admissions.bjut.edu.cn",),
}


def _province_official_domains(province: str) -> tuple[str, ...]:
    return _PROVINCE_OFFICIAL_DOMAINS.get(str(province or "").strip(), ())


def _school_official_domains(school_name: str) -> tuple[str, ...]:
    return _SCHOOL_ADMISSION_DOMAINS.get(str(school_name or "").strip(), ())


def _build_query(
    query: str,
    *,
    source_scope: SearchSourceScope,
    province: str,
    school_name: str,
    year: int,
    official_domain: str = "",
) -> str:
    clean_domain = official_domain.strip().removeprefix("https://").removeprefix("http://").strip("/")
    if not clean_domain and source_scope == "province_policy":
        domains = _province_official_domains(province)
        if domains:
            clean_domain = domains[0]
    parts = []
    if clean_domain:
        parts.append(f"site:{clean_domain}")
    parts.append(str(query or "").strip())
    if year:
        parts.append(str(year))
    if source_scope == "general_official":
        parts.extend(["教育部", "阳光高考", "官方"])
    elif source_scope == "province_policy":
        if province:
            parts.append(province)
        parts.extend(["考试院", "官方"])
    elif source_scope in {"school_brochure", "school_admissions_notice"}:
        if school_name:
            parts.append(school_name)
            parts.append(f"{school_name}本科招生网")
        if source_scope == "school_brochure":
            parts.extend(["招生章程", "招生简章", "招生网"])
        else:
            parts.extend(["招生办", "通知", "招生网"])
    deduped: list[str] = []
    for part in parts:
        text = str(part or "").strip()
        if text and text not in deduped:
            deduped.append(text)
    return " ".join(deduped)


def _build_query_candidates(
    query: str,
    *,
    source_scope: SearchSourceScope,
    province: str,
    school_name: str,
    year: int,
    official_domain: str = "",
) -> list[str]:
    primary = _build_query(
        query,
        source_scope=source_scope,
        province=province,
        school_name=school_name,
        year=year,
        official_domain=official_domain,
    )
    candidates = [primary]
    if source_scope == "province_policy" and _province_official_domains(province):
        fallback = _build_query(
            f"{province}省教育招生考试院 {query}",
            source_scope=source_scope,
            province=province,
            school_name=school_name,
            year=year,
            official_domain="",
        ).replace(f"site:{_province_official_domains(province)[0]} ", "", 1)
        candidates.append(fallback)
    elif source_scope in {"school_brochure", "school_admissions_notice"} and not official_domain:
        for domain in _school_official_domains(school_name):
            candidates.append(
                _build_query(
                    query,
                    source_scope=source_scope,
                    province=province,
                    school_name=school_name,
                    year=year,
                    official_domain=domain,
                )
            )
    elif source_scope == "general_official":
        candidates.append(
            _build_query(
                query,
                source_scope=source_scope,
                province=province,
                school_name=school_name,
                year=year,
                official_domain="gaokao.chsi.com.cn",
            )
        )
        candidates.append(
            _build_query(
                query,
                source_scope=source_scope,
                province=province,
                school_name=school_name,
                year=year,
                official_domain="moe.gov.cn",
            )
        )

    deduped: list[str] = []
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text and text not in deduped:
            deduped.append(text)
    return deduped


def _normalize_result_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": str(item.get("name") or item.get("title") or "").strip(),
        "url": str(item.get("url") or "").strip(),
        "site_name": str(item.get("siteName") or item.get("site_name") or "").strip(),
        "snippet": str(item.get("snippet") or "").strip(),
        "summary": str(item.get("summary") or "").strip(),
        "date_published": str(item.get("datePublished") or item.get("date_published") or "").strip(),
    }


def _extract_results(data: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(data.get("data"), dict):
        data = data["data"]
    web_pages = data.get("webPages") or {}
    raw_items = web_pages.get("value") if isinstance(web_pages, dict) else None
    if raw_items is None:
        raw_items = data.get("value") or data.get("results") or []
    if not isinstance(raw_items, list):
        return []
    results: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        item = _normalize_result_item(raw)
        if item["url"] or item["title"]:
            results.append(item)
    return results


def _domain_from_url(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def _domain_matches(domain: str, expected: str) -> bool:
    clean_domain = domain.lower().strip()
    clean_expected = expected.lower().strip()
    return clean_domain == clean_expected or clean_domain.endswith(f".{clean_expected}")


def _is_official_exam_site_name(site_name: str) -> bool:
    return (
        "教育招生考试院" in site_name
        or "教育考试院" in site_name
        or "招生考试院" in site_name
    )


def _is_official_result(item: dict[str, Any], *, source_scope: SearchSourceScope, province: str, school_name: str) -> bool:
    title = str(item.get("title") or "")
    url = str(item.get("url") or "")
    site_name = str(item.get("site_name") or "")
    snippet = str(item.get("snippet") or "")
    summary = str(item.get("summary") or "")
    text = f"{title} {site_name} {snippet} {summary}"
    domain = _domain_from_url(url)

    if source_scope == "general_official":
        return (
            domain.endswith(".gov.cn")
            or "moe.gov.cn" in domain
            or "chsi.com.cn" in domain
            or "教育部" in site_name
            or "阳光高考" in site_name
            or _is_official_exam_site_name(site_name)
        )
    if source_scope == "province_policy":
        province_hit = not province or province in text
        province_domain_hit = any(_domain_matches(domain, expected) for expected in _province_official_domains(province))
        return province_hit and (
            domain.endswith(".gov.cn")
            or "chsi.com.cn" in domain
            or province_domain_hit
            or _is_official_exam_site_name(site_name)
        )
    if source_scope in {"school_brochure", "school_admissions_notice"}:
        if "研究生" in f"{title} {site_name}":
            return False
        school_official_site = (not school_name or school_name in site_name) and (
            "招生网" in site_name or "招生办公室" in site_name or "本科招生" in site_name
        )
        if source_scope == "school_brochure":
            brochure_hit = (
                "招生章程" in f"{title} {site_name} {snippet}"
                or "招生简章" in f"{title} {site_name} {snippet}"
                or "本科招生" in f"{title} {site_name}"
                or "admissions" in domain
            )
            return (domain.endswith(".edu.cn") or school_official_site) and brochure_hit
        return domain.endswith(".edu.cn") or school_official_site
    return False


def _filter_official_results(
    results: list[dict[str, Any]],
    *,
    source_scope: SearchSourceScope,
    province: str,
    school_name: str,
) -> list[dict[str, Any]]:
    return [
        item
        for item in results
        if _is_official_result(item, source_scope=source_scope, province=province, school_name=school_name)
    ]


async def _request_bocha_search(
    session: aiohttp.ClientSession,
    *,
    base_url: str,
    headers: dict[str, str],
    query: str,
    freshness: SearchFreshness,
    count: int,
    summary: bool,
) -> tuple[int, dict[str, Any]]:
    request_body = {
        "query": query,
        "freshness": freshness,
        "summary": bool(summary),
        "count": count,
    }
    async with session.post(base_url, headers=headers, json=request_body) as response:
        data = await response.json(content_type=None)
        return response.status, data if isinstance(data, dict) else {}


async def search_official_admission_sources(
    ctx: RunContext[RequestContext],  # noqa: ARG001 - kept for future observability/session source caching.
    query: str,
    source_scope: SearchSourceScope = "general_official",
    province: str = "",
    school_name: str = "",
    official_domain: str = "",
    year: int = 0,
    freshness: SearchFreshness = "oneYear",
    count: int = 5,
    summary: bool = True,
) -> str:
    """Search official admission-policy sources via Bocha Web Search.

    Use this after `answer_admission_policy_question` indicates that official
    source lookup is required. This tool only returns source facts and must not
    decide whether the student can apply; school/user fit needs a separate
    matching step against the user's score, subjects, physical exam, eligibility
    and budget.
    """
    config = BochaSearchConfig()
    if not config.api_key:
        return json.dumps(
            {
                "reply_strategy": "continue_model",
                "result_kind": "official_source_search",
                "status": "missing_api_key",
                "summary": "当前未配置 BOCHA_API_KEY，不能执行官方来源联网检索。",
                "source_scope": source_scope,
                "query": query,
                "results": [],
            },
            ensure_ascii=False,
        )

    normalized_count = max(1, min(int(count or 5), 10))
    query_candidates = _build_query_candidates(
        query,
        source_scope=source_scope,
        province=province,
        school_name=school_name,
        year=year,
        official_domain=official_domain,
    )
    search_query = query_candidates[0]
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }
    try:
        timeout = aiohttp.ClientTimeout(total=float(config.timeout_seconds or 10.0))
        async with aiohttp.ClientSession(timeout=timeout) as session:
            raw_results: list[dict[str, Any]] = []
            results: list[dict[str, Any]] = []
            attempted_queries: list[str] = []
            for candidate_query in query_candidates:
                attempted_queries.append(candidate_query)
                status, data = await _request_bocha_search(
                    session,
                    base_url=config.base_url,
                    headers=headers,
                    query=candidate_query,
                    freshness=freshness,
                    count=normalized_count,
                    summary=summary,
                )
                if status >= 400:
                    return json.dumps(
                        {
                            "reply_strategy": "continue_model",
                            "result_kind": "official_source_search",
                            "status": "http_error",
                            "http_status": status,
                            "summary": "官方来源检索请求失败，不能据此下最终结论。",
                            "source_scope": source_scope,
                            "query": candidate_query,
                            "attempted_queries": attempted_queries,
                            "results": [],
                        },
                        ensure_ascii=False,
                    )
                raw_results = _extract_results(data)
                results = _filter_official_results(
                    raw_results,
                    source_scope=source_scope,
                    province=province,
                    school_name=school_name,
                )
                search_query = candidate_query
                if results:
                    break
    except Exception as exc:
        return json.dumps(
            {
                "reply_strategy": "continue_model",
                "result_kind": "official_source_search",
                "status": "request_error",
                "summary": "官方来源检索暂时失败，不能据此下最终结论。",
                "error": str(exc),
                "source_scope": source_scope,
                "query": search_query,
                "results": [],
            },
            ensure_ascii=False,
        )

    return json.dumps(
        {
            "reply_strategy": "continue_model",
            "result_kind": "official_source_search",
            "status": "ok" if results else "empty",
            "source_scope": source_scope,
            "query": search_query,
            "attempted_queries": attempted_queries,
            "results": results,
            "raw_result_count": len(raw_results),
            "summary": f"已检索到 {len(results)} 条可能相关的官方来源。" if results else "没有检索到可用官方来源。",
        },
        ensure_ascii=False,
    )
