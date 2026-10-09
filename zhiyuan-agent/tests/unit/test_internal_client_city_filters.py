"""直辖市城市筛选：区级展开（假否定修复）的单元测试。

背景（2026-10-09 审计实测，会话 10041981）：候选池里直辖市院校的 `cityName`
存的是**区级名**（上海∈{虹口,浦东,松江,...}、北京∈{海淀,延庆,...}），而过滤
执行点是"filter 值 ⊆ 项字段"的包含匹配（Java `PlanningStateService.matchesCity` /
`CandidatePreviewService.applyFilters`）→ 按"上海"筛恒为 0（`cityNames=["上海"]`
+ 会计 total=0，而同池 `provinceNames=["上海"]` + 会计 total=8）。

本文件锁三件事：①展开函数本身的语义（直辖市展开、非直辖市原样、空值/多值不回归）；
②两条候选过滤请求（`query_planning_candidate_pool` / `preview_candidates`）的
payload 真的带上了展开值；③院校目录 `catalog_list_schools` 的直辖市城市条件
上提到 province（那里是等值匹配）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.util import internal_client

SHANGHAI_DISTRICTS = ("浦东", "虹口", "松江", "金山", "嘉定", "崇明")
BEIJING_DISTRICTS = ("海淀", "延庆", "大兴", "顺义", "通州")
TIANJIN_DISTRICTS = ("西青", "宝坻", "滨海新区")
CHONGQING_DISTRICTS = ("合川", "永川", "渝北", "巴南")


class TestExpandMunicipalityCityNames:
    def test_municipality_expands_to_districts(self):
        expanded = internal_client._expand_municipality_city_names(["上海"])

        assert expanded[0] == "上海"
        for district in SHANGHAI_DISTRICTS:
            assert district in expanded
        assert len(expanded) == 1 + 16

    def test_all_four_municipalities_are_covered(self):
        expanded = internal_client._expand_municipality_city_names(
            ["北京", "天津", "上海", "重庆"]
        )

        for district in (*BEIJING_DISTRICTS, *TIANJIN_DISTRICTS, *SHANGHAI_DISTRICTS, *CHONGQING_DISTRICTS):
            assert district in expanded
        assert len(expanded) == 4 + 16 + 16 + 16 + 38

    def test_suffix_form_and_whitespace_also_expand(self):
        expanded = internal_client._expand_municipality_city_names([" 上海市 ", "北京市"])

        assert "虹口" in expanded
        assert "海淀" in expanded

    def test_non_municipality_cities_pass_through_unchanged(self):
        assert internal_client._expand_municipality_city_names(["南京", "广州", "深圳"]) == [
            "南京",
            "广州",
            "深圳",
        ]

    def test_district_value_passes_through_unchanged(self):
        assert internal_client._expand_municipality_city_names(["浦东"]) == ["浦东"]

    def test_empty_values_do_not_regress(self):
        assert internal_client._expand_municipality_city_names(None) == []
        assert internal_client._expand_municipality_city_names([]) == []
        assert internal_client._expand_municipality_city_names(["", "  "]) == []

    def test_scalar_string_is_accepted(self):
        assert "浦东" in internal_client._expand_municipality_city_names("上海")

    def test_duplicates_are_removed_but_order_kept(self):
        expanded = internal_client._expand_municipality_city_names(["上海", "上海", "广州"])

        assert expanded == list(dict.fromkeys(["上海", *internal_client._MUNICIPALITY_DISTRICTS["上海"], "广州"]))

    def test_mixed_list_keeps_normal_cities_alongside_expansion(self):
        expanded = internal_client._expand_municipality_city_names(["上海", "广州", "深圳"])

        assert "广州" in expanded and "深圳" in expanded and "浦东" in expanded


@pytest.mark.asyncio
async def test_candidate_pool_query_expands_municipality_city_filters(monkeypatch):
    post_mock = AsyncMock(return_value={"code": 0, "data": {}})
    monkeypatch.setattr(internal_client.http_client, "post", post_mock)

    await internal_client.query_planning_candidate_pool(
        1,
        10041981,
        city_names=["上海", "广州"],
        negative_city_names=["北京"],
        major_keywords=["会计"],
    )

    filters = post_mock.await_args.kwargs["json_data"]["filters"]
    assert "浦东" in filters["cityNames"] and "虹口" in filters["cityNames"]
    assert "广州" in filters["cityNames"] and "上海" in filters["cityNames"]
    assert "海淀" in filters["negativeCityNames"]
    # 非地域过滤项一个字都不许动。
    assert filters["majorKeywords"] == ["会计"]
    assert filters["provinceNames"] == []


@pytest.mark.asyncio
async def test_candidate_pool_query_keeps_normal_cities_untouched(monkeypatch):
    post_mock = AsyncMock(return_value={"code": 0, "data": {}})
    monkeypatch.setattr(internal_client.http_client, "post", post_mock)

    await internal_client.query_planning_candidate_pool(1, 10041981, city_names=["南京"])

    filters = post_mock.await_args.kwargs["json_data"]["filters"]
    assert filters["cityNames"] == ["南京"]
    assert filters["negativeCityNames"] == []


@pytest.mark.asyncio
async def test_preview_candidates_expands_municipality_city_filters(monkeypatch):
    post_mock = AsyncMock(return_value={"code": 0, "data": {}})
    monkeypatch.setattr(internal_client.http_client, "post", post_mock)

    await internal_client.preview_candidates(
        1,
        10041981,
        filters={"cityNames": ["北京", "上海", "广州", "深圳"], "majorKeywords": ["会计"]},
        page=1,
        page_size=5,
    )

    filters = post_mock.await_args.kwargs["json_data"]["filters"]
    for district in (*BEIJING_DISTRICTS, *SHANGHAI_DISTRICTS):
        assert district in filters["cityNames"]
    assert {"广州", "深圳"} <= set(filters["cityNames"])
    assert filters["majorKeywords"] == ["会计"]


@pytest.mark.asyncio
async def test_preview_candidates_expands_snake_case_city_keys(monkeypatch):
    post_mock = AsyncMock(return_value={"code": 0, "data": {}})
    monkeypatch.setattr(internal_client.http_client, "post", post_mock)

    await internal_client.preview_candidates(
        1, 10041981, filters={"city_names": ["天津"], "negative_city_names": ["重庆"]}
    )

    filters = post_mock.await_args.kwargs["json_data"]["filters"]
    assert "西青" in filters["city_names"]
    assert "渝北" in filters["negative_city_names"]


@pytest.mark.asyncio
async def test_preview_candidates_without_city_filters_is_unchanged(monkeypatch):
    post_mock = AsyncMock(return_value={"code": 0, "data": {}})
    monkeypatch.setattr(internal_client.http_client, "post", post_mock)

    await internal_client.preview_candidates(1, 10041981, filters={"majorKeywords": ["金融"]})

    filters = post_mock.await_args.kwargs["json_data"]["filters"]
    assert filters == {"majorKeywords": ["金融"]}


@pytest.mark.asyncio
async def test_catalog_list_schools_lifts_municipality_city_to_province(monkeypatch):
    get_mock = AsyncMock(return_value={"code": 0, "data": []})
    monkeypatch.setattr(internal_client.http_client, "get", get_mock)

    await internal_client.catalog_list_schools(city="上海", education_level="本科")

    params = get_mock.await_args.kwargs["params"]
    assert params["province"] == "上海"
    assert "city" not in params


@pytest.mark.asyncio
async def test_catalog_list_schools_normalizes_same_municipality_province(monkeypatch):
    get_mock = AsyncMock(return_value={"code": 0, "data": []})
    monkeypatch.setattr(internal_client.http_client, "get", get_mock)

    await internal_client.catalog_list_schools(province="上海市", city="上海")

    params = get_mock.await_args.kwargs["params"]
    assert params["province"] == "上海"
    assert "city" not in params


@pytest.mark.asyncio
async def test_catalog_list_schools_keeps_contradictory_province_city(monkeypatch):
    get_mock = AsyncMock(return_value={"code": 0, "data": []})
    monkeypatch.setattr(internal_client.http_client, "get", get_mock)

    await internal_client.catalog_list_schools(province="江苏", city="上海")

    params = get_mock.await_args.kwargs["params"]
    assert params["province"] == "江苏"
    assert params["city"] == "上海"


@pytest.mark.asyncio
async def test_catalog_list_schools_keeps_district_city_and_normal_cities(monkeypatch):
    get_mock = AsyncMock(return_value={"code": 0, "data": []})
    monkeypatch.setattr(internal_client.http_client, "get", get_mock)

    await internal_client.catalog_list_schools(province="上海", city="浦东")
    assert get_mock.await_args.kwargs["params"] == {"province": "上海", "city": "浦东"}

    await internal_client.catalog_list_schools(city="南京")
    assert get_mock.await_args.kwargs["params"] == {"city": "南京"}
