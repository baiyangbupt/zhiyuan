"""Unit tests for code enrichment utilities."""

import pytest
from unittest.mock import patch, MagicMock
from app.util.code_enrichment import (
    get_major_codes,
    get_major_codes_async,
    get_school_codes,
    get_school_codes_async,
    get_province_codes,
    get_province_codes_async,
    get_city_codes,
    get_city_codes_async,
    add_codes_to_profile,
    add_codes_to_profile_async,
    normalize_candidate_filters_async,
    resolve_major_names_async,
    resolve_school_names_async,
)


@pytest.fixture
def mock_major_data():
    """Mock data where id and majorCode differ to verify we use id."""
    return {
        "data": [
            {
                "label": "工学",
                "id": "7",
                "children": [
                    {
                        "label": "计算机类",
                        "id": "39",
                        "children": [
                            {"label": "计算机科学与技术", "id": "574", "majorCode": "080901"},
                            {"label": "软件工程", "id": "575", "majorCode": "080902"},
                        ]
                    }
                ]
            },
            {
                "label": "哲学",
                "id": "1",
                "children": [
                    {
                        "label": "哲学类",
                        "id": "2",
                        "children": [
                            {"label": "哲学", "id": "233", "majorCode": "010101"},
                        ]
                    }
                ]
            }
        ]
    }


@pytest.fixture
def mock_school_data():
    return [
        {"标准院校名称": "北京大学", "标准院校id": "10001"},
        {"标准院校名称": "清华大学", "标准院校id": "10003"},
    ]


@pytest.fixture
def mock_province_city_data():
    return {
        "data": [
            {
                "label": "北京市",
                "id": "110000",
                "children": [
                    {"label": "北京市", "id": "110100"}
                ]
            }
        ]
    }


def test_get_major_codes_empty():
    codes = get_major_codes([], "level2", "01")
    assert codes == []


def test_get_school_codes_empty():
    codes = get_school_codes([])
    assert codes == []


def test_get_province_codes_empty():
    codes = get_province_codes([])
    assert codes == []


def test_get_city_codes_empty():
    codes = get_city_codes([])
    assert codes == []


def test_add_codes_to_profile():
    profile = {
        "major_intent": {
            "level2": ["计算机类"],
            "level3": ["计算机科学与技术"],
        },
        "college_info": {
            "values": ["北京大学"],
        },
        "city_info": {
            "province": ["北京市"],
            "city": ["北京市"],
        },
    }

    enriched = add_codes_to_profile(profile, "01")
    assert "level2_code" in enriched["major_intent"]
    assert "values_code" in enriched["college_info"]
    assert "province_code" in enriched["city_info"]


# ── 专业 ID 一致性测试 ───────────────────────────────────────────


def _patch_major_json(mock_major_data):
    """Patch json.load in code_enrichment to return mock data with distinct id/majorCode."""
    import json
    from unittest.mock import mock_open

    m = mock_open(read_data=json.dumps(mock_major_data))

    return patch("builtins.open", m), patch(
        "json.load", return_value=mock_major_data
    )


def test_level3_returns_id_not_major_code(mock_major_data):
    """get_major_codes for level3 must return the 'id' field, NOT 'majorCode'.

    The backend's getMajorProfileById looks up by id.
    e.g. 计算机科学与技术 should return "574" (id), not "080901" (majorCode).
    """
    from app.util.code_enrichment import _load_major_name_to_code_map

    # Clear lru_cache so our mock data is loaded
    _load_major_name_to_code_map.cache_clear()

    p_open, p_json = _patch_major_json(mock_major_data)
    with p_open, p_json:
        codes = get_major_codes(["计算机科学与技术"], "level3", "01")

    _load_major_name_to_code_map.cache_clear()

    assert codes == ["574"], (
        f"Expected id '574' but got '{codes}'. "
        "level3 must use 'id' field, not 'majorCode'."
    )


def test_level3_multiple_majors_use_id(mock_major_data):
    """Multiple level3 majors should all return id, not majorCode."""
    from app.util.code_enrichment import _load_major_name_to_code_map

    _load_major_name_to_code_map.cache_clear()

    p_open, p_json = _patch_major_json(mock_major_data)
    with p_open, p_json:
        codes = get_major_codes(
            ["计算机科学与技术", "软件工程", "哲学"], "level3", "01"
        )

    _load_major_name_to_code_map.cache_clear()

    assert codes == ["574", "575", "233"], (
        f"Expected ['574', '575', '233'] but got {codes}. "
        "All level3 should return id, not majorCode."
    )


def test_level1_and_level2_use_id(mock_major_data):
    """level1 and level2 should also use the 'id' field."""
    from app.util.code_enrichment import _load_major_name_to_code_map

    _load_major_name_to_code_map.cache_clear()

    p_open, p_json = _patch_major_json(mock_major_data)
    with p_open, p_json:
        l1_codes = get_major_codes(["工学"], "level1", "01")
        l2_codes = get_major_codes(["计算机类"], "level2", "01")

    _load_major_name_to_code_map.cache_clear()

    assert l1_codes == ["7"]
    assert l2_codes == ["39"]


def test_level3_consistency_with_major_data():
    """Verify code_enrichment level3 codes match major_data id_map (integration check).

    Uses real data files — no mocking.
    """
    from app.data.major_data import bachelor_level3_id_map

    sample_majors = ["计算机科学与技术", "软件工程", "哲学", "临床医学"]
    codes = get_major_codes(sample_majors, "level3", "01")

    for name, code in zip(sample_majors, codes):
        expected = bachelor_level3_id_map.get(name)
        assert code == expected, (
            f"Mismatch for '{name}': code_enrichment returned '{code}', "
            f"major_data id_map has '{expected}'"
        )


async def test_async_code_enrichment_prefers_local_mapping():
    with (
        patch("app.util.code_enrichment._load_major_name_to_code_map", return_value=({"工学": "7"}, {}, {})),
        patch("app.util.code_enrichment.catalog_lookup_major_discipline") as lookup_mock,
    ):
        codes = await get_major_codes_async(["工学"], "level1", "01")

    assert codes == ["7"]
    lookup_mock.assert_not_called()


async def test_async_major_code_falls_back_to_catalog_when_local_missing():
    with (
        patch("app.util.code_enrichment._load_major_name_to_code_map", return_value=({}, {}, {})),
        patch(
            "app.util.code_enrichment.catalog_lookup_major_category",
            return_value={"resultType": "exact", "data": {"subCategoryId": "39", "subCategoryName": "计算机类"}},
        ) as lookup_mock,
    ):
        codes = await get_major_codes_async(["计算机类"], "level2", "01")

    assert codes == ["39"]
    lookup_mock.assert_called_once()


async def test_async_major_code_catalog_lookup_is_deduplicated_for_duplicate_names():
    from app.util import code_enrichment as module

    module._catalog_major_item_cache.clear()
    with (
        patch("app.util.code_enrichment._load_major_name_to_code_map", return_value=({}, {}, {})),
        patch(
            "app.util.code_enrichment.catalog_lookup_major_category",
            return_value={"resultType": "exact", "data": {"subCategoryId": "39", "subCategoryName": "计算机类"}},
        ) as lookup_mock,
    ):
        codes = await get_major_codes_async(["计算机类", "计算机类"], "level2", "01")

    assert codes == ["39", "39"]
    lookup_mock.assert_called_once()


async def test_async_school_province_city_codes_can_use_catalog():
    with (
        patch("app.util.code_enrichment._load_school_name_to_id_map", return_value={}),
        patch("app.util.code_enrichment._load_province_city_maps", return_value=({}, {})),
        patch(
            "app.util.code_enrichment.catalog_lookup_school",
            return_value={"resultType": "exact", "data": {"schoolId": "10001", "schoolName": "北京大学"}},
        ),
        patch(
            "app.util.code_enrichment.catalog_lookup_province",
            return_value={"resultType": "exact", "data": {"provinceCode": "110000", "provinceName": "北京"}},
        ),
        patch(
            "app.util.code_enrichment.catalog_lookup_city",
            return_value={"resultType": "exact", "data": {"cityCode": "110100", "cityName": "北京"}},
        ),
    ):
        school_codes = await get_school_codes_async(["北京大学"])
        province_codes = await get_province_codes_async(["北京"])
        city_codes = await get_city_codes_async(["北京"])

    assert school_codes == ["10001"]
    assert province_codes == ["110000"]
    assert city_codes == ["110100"]


async def test_async_school_code_catalog_lookup_is_cached_across_calls():
    from app.util import code_enrichment as module

    module._catalog_school_item_cache.clear()
    with (
        patch("app.util.code_enrichment._load_school_name_to_id_map", return_value={}),
        patch(
            "app.util.code_enrichment.catalog_lookup_school",
            return_value={"resultType": "exact", "data": {"schoolId": "10001", "schoolName": "北京大学"}},
        ) as lookup_mock,
    ):
        assert await get_school_codes_async(["北京大学"]) == ["10001"]
        assert await get_school_codes_async(["北京大学"]) == ["10001"]

    lookup_mock.assert_called_once()


async def test_resolve_major_names_async_uses_catalog_standard_name():
    with (
        patch("app.util.code_enrichment._load_major_name_to_code_map", return_value=({}, {}, {})),
        patch(
            "app.util.code_enrichment.catalog_lookup_major",
            return_value={"resultType": "exact", "data": {"majorId": "574", "majorName": "计算机科学与技术"}},
        ),
    ):
        names = await resolve_major_names_async(["计科"], "level3", "01")

    assert names == ["计算机科学与技术"]


async def test_resolve_major_names_async_uses_local_compact_alias_before_catalog():
    with (
        patch(
            "app.util.code_enrichment._load_major_name_to_code_map",
            return_value=({}, {}, {"跨境电子商务": "120803T"}),
        ),
        patch("app.util.code_enrichment.catalog_lookup_major") as lookup_mock,
    ):
        names = await resolve_major_names_async(["跨境电商"], "level3", "01")

    assert names == ["跨境电子商务"]
    lookup_mock.assert_not_called()


async def test_resolve_major_names_async_uses_local_xue_suffix_alias_before_catalog():
    with (
        patch(
            "app.util.code_enrichment._load_major_name_to_code_map",
            return_value=({}, {}, {"审计学": "846"}),
        ),
        patch("app.util.code_enrichment.catalog_lookup_major") as lookup_mock,
    ):
        names = await resolve_major_names_async(["审计"], "level3", "01")

    assert names == ["审计学"]
    lookup_mock.assert_not_called()


async def test_resolve_school_names_async_uses_catalog_standard_name():
    with (
        patch("app.util.code_enrichment._load_school_name_to_id_map", return_value={}),
        patch(
            "app.util.code_enrichment.catalog_lookup_school",
            return_value={"resultType": "exact", "data": {"schoolId": "10001", "schoolName": "北京大学"}},
        ),
    ):
        names = await resolve_school_names_async(["北大"])

    assert names == ["北京大学"]


async def test_add_codes_to_profile_async_uses_catalog_fallback():
    profile = {
        "major_intent": {"level1": ["工学"], "level2": ["计算机类"], "level3": ["计算机科学与技术"]},
        "college_info": {"values": ["北京大学"]},
        "city_info": {"province": ["北京"], "city": ["北京"]},
    }

    with (
        patch("app.util.code_enrichment._load_major_name_to_code_map", return_value=({}, {}, {})),
        patch("app.util.code_enrichment._load_school_name_to_id_map", return_value={}),
        patch("app.util.code_enrichment._load_province_city_maps", return_value=({}, {})),
        patch(
            "app.util.code_enrichment.catalog_lookup_major_discipline",
            return_value={"resultType": "exact", "data": {"categoryId": "7", "categoryName": "工学"}},
        ),
        patch(
            "app.util.code_enrichment.catalog_lookup_major_category",
            return_value={"resultType": "exact", "data": {"subCategoryId": "39", "subCategoryName": "计算机类"}},
        ),
        patch(
            "app.util.code_enrichment.catalog_lookup_major",
            return_value={"resultType": "exact", "data": {"majorId": "574", "majorName": "计算机科学与技术"}},
        ),
        patch(
            "app.util.code_enrichment.catalog_lookup_school",
            return_value={"resultType": "exact", "data": {"schoolId": "10001", "schoolName": "北京大学"}},
        ),
        patch(
            "app.util.code_enrichment.catalog_lookup_province",
            return_value={"resultType": "exact", "data": {"provinceCode": "110000", "provinceName": "北京"}},
        ),
        patch(
            "app.util.code_enrichment.catalog_lookup_city",
            return_value={"resultType": "exact", "data": {"cityCode": "110100", "cityName": "北京"}},
        ),
    ):
        enriched = await add_codes_to_profile_async(profile, "01")

    assert enriched["major_intent"]["level1_code"] == ["7"]
    assert enriched["major_intent"]["level2_code"] == ["39"]
    assert enriched["major_intent"]["level3_code"] == ["574"]
    assert enriched["college_info"]["values_code"] == ["10001"]
    assert enriched["city_info"]["province_code"] == ["110000"]
    assert enriched["city_info"]["city_code"] == ["110100"]


async def test_normalize_candidate_filters_async_uses_catalog_for_unknown_values():
    from app.util import code_enrichment as module

    module._catalog_filter_tag_tree_cache = None
    filters = {
        "provinceNames": ["北京市"],
        "negativeProvinceNames": [],
        "cityNames": ["北京市"],
        "negativeCityNames": [],
        "schoolKeywords": ["北京大学(校本部)"],
        "negativeSchoolKeywords": [],
        "majorKeywords": ["计算机大类"],
        "negativeMajorKeywords": [],
        "majorTags": ["工科"],
        "negativeMajorTags": [],
    }
    with (
        patch("app.util.code_enrichment._load_major_name_to_code_map", return_value=({}, {}, {})),
        patch("app.util.code_enrichment._load_school_name_to_id_map", return_value={}),
        patch("app.util.code_enrichment._load_province_city_maps", return_value=({}, {})),
        patch(
            "app.util.code_enrichment.catalog_lookup_province",
            return_value={"resultType": "exact", "data": {"provinceName": "北京"}},
        ),
        patch(
            "app.util.code_enrichment.catalog_lookup_city",
            return_value={"resultType": "exact", "data": {"cityName": "北京"}},
        ),
        patch(
            "app.util.code_enrichment.catalog_lookup_school",
            return_value={"resultType": "exact", "data": {"schoolName": "北京大学"}},
        ),
        patch(
            "app.util.code_enrichment.catalog_lookup_major_category",
            return_value={"resultType": "exact", "data": {"subCategoryName": "计算机类"}},
        ),
        patch(
            "app.util.code_enrichment.catalog_lookup_major_discipline",
            return_value={"resultType": "exact", "data": {"categoryName": "工学"}},
        ),
        patch(
            "app.util.code_enrichment.catalog_tree_filter_tags",
            return_value={"resultType": "exact", "data": {"school": {"category": ["理工"], "nature": ["公办"], "feature": [], "level": ["双一流"]}}},
        ),
    ):
        normalized = await normalize_candidate_filters_async(filters, "01")

    assert normalized["provinceNames"] == ["北京"]
    assert normalized["cityNames"] == ["北京"]
    assert normalized["schoolKeywords"] == ["北京大学"]
    assert normalized["majorKeywords"] == ["计算机类"]
    assert normalized["majorTags"] == ["工学"]


async def test_normalize_candidate_filters_async_filters_school_tags_by_catalog_tree():
    from app.util import code_enrichment as module

    module._catalog_filter_tag_tree_cache = None
    filters = {
        "schoolTags": ["公办", "不存在标签"],
        "negativeSchoolTags": ["双一流", "未知标签"],
    }
    with patch(
        "app.util.code_enrichment.catalog_tree_filter_tags",
        return_value={
            "resultType": "exact",
            "data": {
                "school": {
                    "category": ["理工"],
                    "nature": ["公办"],
                    "feature": ["教育部直属"],
                    "level": ["双一流"],
                }
            },
        },
    ):
        normalized = await normalize_candidate_filters_async(filters, "01")

    assert normalized["schoolTags"] == ["公办"]
    assert normalized["negativeSchoolTags"] == ["双一流"]


async def test_normalize_candidate_filters_async_reuses_cached_filter_tag_tree():
    from app.util import code_enrichment as module

    module._catalog_filter_tag_tree_cache = None
    filters = {
        "schoolTags": ["公办"],
        "negativeSchoolTags": ["双一流"],
    }
    with patch(
        "app.util.code_enrichment.catalog_tree_filter_tags",
        return_value={
            "resultType": "exact",
            "data": {
                "school": {
                    "category": [],
                    "nature": ["公办"],
                    "feature": [],
                    "level": ["双一流"],
                }
            },
        },
    ) as tree_mock:
        first = await normalize_candidate_filters_async(filters, "01")
        second = await normalize_candidate_filters_async(filters, "01")

    assert first["schoolTags"] == ["公办"]
    assert second["negativeSchoolTags"] == ["双一流"]
    tree_mock.assert_called_once()
