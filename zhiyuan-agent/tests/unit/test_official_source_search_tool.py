from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.context import RequestContext
from app.tools.official_source_search_tool import (
    _build_query,
    _build_query_candidates,
    _extract_results,
    _filter_official_results,
    search_official_admission_sources,
)


@pytest.mark.asyncio
async def test_official_source_search_reports_missing_api_key(monkeypatch):
    monkeypatch.setenv("BOCHA_API_KEY", "")

    result = await search_official_admission_sources(
        SimpleNamespace(deps=RequestContext(userid="u1", sessionid="s1")),
        query="专项计划资格",
        source_scope="province_policy",
        province="山东",
    )
    payload = json.loads(result)

    assert payload["reply_strategy"] == "continue_model"
    assert payload["result_kind"] == "official_source_search"
    assert payload["status"] == "missing_api_key"
    assert payload["results"] == []


@pytest.mark.asyncio
async def test_official_source_search_query_builder_keeps_school_context(monkeypatch):
    monkeypatch.setenv("BOCHA_API_KEY", "")

    result = await search_official_admission_sources(
        SimpleNamespace(deps=RequestContext(userid="u1", sessionid="s1")),
        query="转专业",
        source_scope="school_brochure",
        school_name="北京工业大学",
        year=2026,
    )
    payload = json.loads(result)

    assert payload["status"] == "missing_api_key"
    assert payload["query"] == "转专业"


def test_extract_results_reads_bocha_data_envelope():
    results = _extract_results(
        {
            "code": 200,
            "data": {
                "webPages": {
                    "value": [
                        {
                            "name": "山东省教育招生考试院官网",
                            "url": "https://www.sdzk.cn/Default.aspx/NewsInfo.aspx?NewsID=6355",
                            "siteName": "山东省教育招生考试院官网",
                        }
                    ]
                }
            },
        }
    )

    assert results == [
        {
            "title": "山东省教育招生考试院官网",
            "url": "https://www.sdzk.cn/Default.aspx/NewsInfo.aspx?NewsID=6355",
            "site_name": "山东省教育招生考试院官网",
            "snippet": "",
            "summary": "",
            "date_published": "",
        }
    ]


def test_filter_official_results_rejects_third_party_policy_pages():
    results = [
        {
            "title": "山东省教育招生考试院官网",
            "url": "https://www.sdzk.cn/Default.aspx/NewsInfo.aspx?NewsID=6355",
            "site_name": "山东省教育招生考试院官网",
            "snippet": "",
            "summary": "",
            "date_published": "",
        },
        {
            "title": "山东专科院校",
            "url": "https://www.cd-hk.net/html1/demo.html",
            "site_name": "www.cd-hk.net",
            "snippet": "山东 专项 考试院",
            "summary": "",
            "date_published": "",
        },
    ]

    filtered = _filter_official_results(results, source_scope="province_policy", province="山东", school_name="")

    assert [item["url"] for item in filtered] == ["https://www.sdzk.cn/Default.aspx/NewsInfo.aspx?NewsID=6355"]


def test_filter_official_results_rejects_third_party_pages_with_official_title():
    results = [
        {
            "title": "山东教育招生考试院登录入口https://www.sdzk.cn- 济南本地宝",
            "url": "https://m.jn.bendibao.com/edu/80061.shtm",
            "site_name": "济南本地宝",
            "snippet": "山东教育招生考试院官网入口",
            "summary": "",
            "date_published": "",
        },
        {
            "title": "山东省教育招生考试院官网",
            "url": "https://www.sdzk.cn/Default.aspx/NewsInfo.aspx?NewsID=6355",
            "site_name": "山东省教育招生考试院官网",
            "snippet": "",
            "summary": "",
            "date_published": "",
        },
    ]

    filtered = _filter_official_results(results, source_scope="province_policy", province="山东", school_name="")

    assert [item["url"] for item in filtered] == ["https://www.sdzk.cn/Default.aspx/NewsInfo.aspx?NewsID=6355"]


def test_province_official_domain_hint_is_placed_first_for_bocha_site_search():
    query = _build_query(
        "专项计划资格",
        source_scope="province_policy",
        province="山东",
        school_name="",
        year=2026,
    )

    assert query.startswith("site:sdzk.cn ")


def test_school_official_domain_is_placed_first_for_bocha_site_search():
    query = _build_query(
        "北京工业大学 招生章程 2025",
        source_scope="school_brochure",
        province="",
        school_name="北京工业大学",
        year=0,
        official_domain="admissions.bjut.edu.cn",
    )

    assert query.startswith("site:admissions.bjut.edu.cn ")


def test_known_school_query_candidates_include_official_domain_fallback():
    queries = _build_query_candidates(
        "北京工业大学 招生章程 转专业",
        source_scope="school_brochure",
        province="",
        school_name="北京工业大学",
        year=2026,
    )

    assert not queries[0].startswith("site:")
    assert any(query.startswith("site:admissions.bjut.edu.cn ") for query in queries[1:])


def test_province_policy_query_candidates_include_non_site_fallback():
    queries = _build_query_candidates(
        "专项计划资格",
        source_scope="province_policy",
        province="山东",
        school_name="",
        year=2026,
    )

    assert queries[0].startswith("site:sdzk.cn ")
    assert any(query.startswith("山东省教育招生考试院 ") for query in queries[1:])
    assert all("site:sdzk.cn" not in query for query in queries[1:])


@pytest.mark.asyncio
async def test_official_source_search_tries_fallback_when_primary_is_empty(monkeypatch):
    monkeypatch.setenv("BOCHA_API_KEY", "sk-test")
    raw_second = {
        "data": {
            "webPages": {
                "value": [
                    {
                        "name": "山东省教育招生考试院官网",
                        "url": "https://www.sdzk.cn/Default.aspx/NewsInfo.aspx?NewsID=6355",
                        "siteName": "山东省教育招生考试院官网",
                        "snippet": "山东 专项计划 资格",
                    },
                    {
                        "name": "山东专项入口",
                        "url": "https://example.com/demo.html",
                        "siteName": "第三方页面",
                        "snippet": "山东省教育招生考试院 专项",
                    },
                ]
            }
        }
    }
    request_mock = AsyncMock(side_effect=[(200, {"data": {"webPages": {"value": []}}}), (200, raw_second)])

    with patch("app.tools.official_source_search_tool._request_bocha_search", new=request_mock):
        result = await search_official_admission_sources(
            SimpleNamespace(deps=RequestContext(userid="u1", sessionid="s1")),
            query="专项计划资格",
            source_scope="province_policy",
            province="山东",
            year=2026,
            count=3,
        )

    payload = json.loads(result)
    assert payload["status"] == "ok"
    assert len(payload["attempted_queries"]) == 2
    assert payload["attempted_queries"][0].startswith("site:sdzk.cn ")
    assert payload["query"] == payload["attempted_queries"][1]
    assert [item["url"] for item in payload["results"]] == [
        "https://www.sdzk.cn/Default.aspx/NewsInfo.aspx?NewsID=6355"
    ]
