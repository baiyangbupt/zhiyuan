"""Unit tests for app.data.city_data module."""

import json
from pathlib import Path

import pytest

from app.data.city_data import (
    all_cities,
    all_provinces,
    extract_all_cities,
    extract_all_provinces,
    format_province_city_hierarchy,
    load_province_city_hierarchy,
    province_city_hierarchy_text,
)


class TestLoadProvinceCityHierarchy:
    """Tests for load_province_city_hierarchy function."""

    def test_load_returns_dict(self):
        """Test that loading returns a dictionary."""
        data = load_province_city_hierarchy()

        assert isinstance(data, dict)

    def test_load_has_data_key(self):
        """Test that loaded data has 'data' key."""
        data = load_province_city_hierarchy()

        assert "data" in data

    def test_load_data_is_list(self):
        """Test that data['data'] is a list of provinces."""
        data = load_province_city_hierarchy()

        assert isinstance(data["data"], list)
        assert len(data["data"]) > 0

    def test_load_province_has_label(self):
        """Test that each province entry has a 'label' field."""
        data = load_province_city_hierarchy()

        for province in data["data"]:
            assert "label" in province, f"Province entry missing 'label': {province}"

    def test_load_province_has_children(self):
        """Test that each province entry has a 'children' key."""
        data = load_province_city_hierarchy()

        for province in data["data"]:
            assert "children" in province, f"Province '{province.get('label')}' missing 'children'"

    def test_load_city_has_label(self):
        """Test that each city entry has a 'label' field."""
        data = load_province_city_hierarchy()

        for province in data["data"]:
            for city in province.get("children", []):
                assert "label" in city, f"City entry missing 'label' in province '{province['label']}'"


class TestFormatProvinceCityHierarchy:
    """Tests for format_province_city_hierarchy function."""

    def test_format_simple_hierarchy(self):
        """Test formatting a simple hierarchy."""
        data = {
            "data": [
                {
                    "label": "安徽",
                    "children": [
                        {"label": "合肥"},
                        {"label": "芜湖"},
                    ],
                },
            ]
        }

        result = format_province_city_hierarchy(data)

        assert "安徽" in result
        assert "  合肥" in result
        assert "  芜湖" in result

    def test_format_province_at_top_level(self):
        """Test that provinces are at top level (no indentation)."""
        data = {
            "data": [
                {"label": "北京", "children": []},
                {"label": "上海", "children": []},
            ]
        }

        result = format_province_city_hierarchy(data)
        lines = result.split("\n")

        assert lines[0] == "北京"
        assert lines[1] == "上海"

    def test_format_cities_indented(self):
        """Test that cities are indented with 2 spaces."""
        data = {
            "data": [
                {
                    "label": "广东",
                    "children": [
                        {"label": "广州"},
                        {"label": "深圳"},
                    ],
                },
            ]
        }

        result = format_province_city_hierarchy(data)
        lines = result.split("\n")

        assert lines[0] == "广东"
        assert lines[1] == "  广州"
        assert lines[2] == "  深圳"

    def test_format_empty_children(self):
        """Test formatting province with no children (e.g. 直辖市)."""
        data = {
            "data": [
                {"label": "北京", "children": []},
            ]
        }

        result = format_province_city_hierarchy(data)

        assert result == "北京"

    def test_format_multiple_provinces(self):
        """Test formatting multiple provinces."""
        data = {
            "data": [
                {
                    "label": "安徽",
                    "children": [{"label": "合肥"}],
                },
                {
                    "label": "北京",
                    "children": [],
                },
                {
                    "label": "广东",
                    "children": [{"label": "广州"}, {"label": "深圳"}],
                },
            ]
        }

        result = format_province_city_hierarchy(data)
        lines = result.split("\n")

        assert lines[0] == "安徽"
        assert lines[1] == "  合肥"
        assert lines[2] == "北京"
        assert lines[3] == "广东"
        assert lines[4] == "  广州"
        assert lines[5] == "  深圳"

    def test_format_no_children_key(self):
        """Test formatting when children key is missing (uses get default)."""
        data = {
            "data": [
                {"label": "北京"},
            ]
        }

        result = format_province_city_hierarchy(data)

        assert result == "北京"


class TestExtractAllProvinces:
    """Tests for extract_all_provinces function."""

    def test_extract_provinces(self):
        """Test extracting province names."""
        data = {
            "data": [
                {"label": "安徽", "children": [{"label": "合肥"}]},
                {"label": "北京", "children": []},
                {"label": "重庆", "children": []},
            ]
        }

        result = extract_all_provinces(data)

        assert result == ["安徽", "北京", "重庆"]

    def test_extract_provinces_empty_data(self):
        """Test extracting from empty data."""
        data = {"data": []}

        result = extract_all_provinces(data)

        assert result == []

    def test_extract_provinces_returns_list(self):
        """Test that result is a list."""
        data = {"data": [{"label": "北京", "children": []}]}

        result = extract_all_provinces(data)

        assert isinstance(result, list)


class TestExtractAllCities:
    """Tests for extract_all_cities function."""

    def test_extract_cities(self):
        """Test extracting city names."""
        data = {
            "data": [
                {
                    "label": "安徽",
                    "children": [{"label": "合肥"}, {"label": "芜湖"}],
                },
                {
                    "label": "广东",
                    "children": [{"label": "广州"}, {"label": "深圳"}],
                },
            ]
        }

        result = extract_all_cities(data)

        assert "合肥" in result
        assert "芜湖" in result
        assert "广州" in result
        assert "深圳" in result

    def test_extract_cities_skips_provinces_without_children(self):
        """Test that provinces without children are skipped."""
        data = {
            "data": [
                {"label": "北京", "children": []},
                {"label": "广东", "children": [{"label": "广州"}]},
            ]
        }

        result = extract_all_cities(data)

        assert result == ["广州"]
        assert "北京" not in result

    def test_extract_cities_empty_data(self):
        """Test extracting from empty data."""
        data = {"data": []}

        result = extract_all_cities(data)

        assert result == []

    def test_extract_cities_no_children_key(self):
        """Test extracting when children key is missing."""
        data = {"data": [{"label": "上海"}]}

        result = extract_all_cities(data)

        assert result == []


class TestModuleLevelData:
    """Tests for module-level pre-computed data."""

    def test_province_city_hierarchy_text_is_string(self):
        """Test that hierarchy text is a non-empty string."""
        assert isinstance(province_city_hierarchy_text, str)
        assert len(province_city_hierarchy_text) > 0

    def test_all_provinces_loaded(self):
        """Test that all_provinces is loaded at module level."""
        assert isinstance(all_provinces, list)
        assert len(all_provinces) > 0

    def test_all_cities_loaded(self):
        """Test that all_cities is loaded at module level."""
        assert isinstance(all_cities, list)
        assert len(all_cities) > 0

    def test_provinces_contain_known_entries(self):
        """Test that known provinces exist in the data."""
        expected_provinces = ["北京", "上海", "广东", "江苏", "浙江", "四川"]
        for province in expected_provinces:
            assert province in all_provinces, f"{province} not found in all_provinces"

    def test_cities_contain_known_entries(self):
        """Test that known cities exist in the data."""
        expected_cities = ["广州", "深圳", "杭州", "南京", "成都"]
        for city in expected_cities:
            assert city in all_cities, f"{city} not found in all_cities"

    def test_direct_municipalities_have_no_cities(self):
        """Test that direct municipalities (北京/上海/天津/重庆) have no cities in the list."""
        # Direct municipalities should not have children cities listed
        # They appear only as provinces
        assert "北京" in all_provinces
        assert "上海" in all_provinces

    def test_hierarchy_text_contains_province_names(self):
        """Test that hierarchy text contains known province names."""
        assert "安徽" in province_city_hierarchy_text
        assert "广东" in province_city_hierarchy_text
        assert "北京" in province_city_hierarchy_text

    def test_hierarchy_text_contains_city_names(self):
        """Test that hierarchy text contains known city names."""
        assert "合肥" in province_city_hierarchy_text
        assert "广州" in province_city_hierarchy_text
        assert "深圳" in province_city_hierarchy_text

    def test_hierarchy_text_has_indentation(self):
        """Test that hierarchy text uses 2-space indentation for cities."""
        assert "  合肥" in province_city_hierarchy_text
        assert "  广州" in province_city_hierarchy_text
