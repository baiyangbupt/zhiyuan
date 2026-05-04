"""Unit tests for app.data.school_data module."""

import csv
from pathlib import Path
from unittest.mock import mock_open, patch

import pytest

from app.data.school_data import (
    SCHOOL_NAME_LIST,
    area_to_associate_schools,
    area_to_bachelor_schools,
    associate_schools,
    bachelor_schools,
    build_area_index,
    load_school_names,
)


class TestLoadSchoolNames:
    """Tests for load_school_names function."""

    def test_load_valid_csv(self, tmp_path):
        """Test loading school names from valid CSV."""
        csv_file = tmp_path / "test_schools.csv"
        csv_content = """标准院校id,标准院校名称,院校省份
1,北京大学,北京
2,清华大学,北京
3,复旦大学,上海
"""
        csv_file.write_text(csv_content, encoding="utf-8-sig")

        schools = load_school_names(str(csv_file))

        assert len(schools) == 3
        assert "北京大学" in schools
        assert "清华大学" in schools
        assert "复旦大学" in schools

    def test_load_csv_with_empty_names(self, tmp_path):
        """Test loading CSV with empty school names."""
        csv_file = tmp_path / "test_schools.csv"
        csv_content = """标准院校id,标准院校名称,院校省份
1,北京大学,北京
2,,北京
3,  ,上海
4,复旦大学,上海
"""
        csv_file.write_text(csv_content, encoding="utf-8-sig")

        schools = load_school_names(str(csv_file))

        assert len(schools) == 2
        assert "北京大学" in schools
        assert "复旦大学" in schools

    def test_load_csv_with_utf8_sig_encoding(self, tmp_path):
        """Test loading CSV with UTF-8-SIG encoding (BOM)."""
        csv_file = tmp_path / "test_schools.csv"
        csv_content = "\ufeff标准院校id,标准院校名称\n1,北京大学\n"
        csv_file.write_text(csv_content, encoding="utf-8-sig")

        schools = load_school_names(str(csv_file))

        assert len(schools) == 1
        assert schools[0] == "北京大学"


class TestBuildAreaIndex:
    """Tests for build_area_index function."""

    def test_index_by_first_character(self):
        """Test indexing schools by first character."""
        schools = ["北京大学", "北京师范大学", "南京大学"]

        index = build_area_index(schools)

        assert "北" in index
        assert len(index["北"]) == 2
        assert "北京大学" in index["北"]
        assert "北京师范大学" in index["北"]
        assert "南" in index
        assert "南京大学" in index["南"]

    def test_index_by_keywords(self):
        """Test indexing schools by keywords from SCHOOL_NAME_LIST."""
        schools = ["北京师范大学", "华东师范大学", "北京理工大学"]

        index = build_area_index(schools)

        assert "师" in index
        assert len(index["师"]) == 2
        assert "北京师范大学" in index["师"]
        assert "华东师范大学" in index["师"]
        assert "理" in index
        assert "北京理工大学" in index["理"]

    def test_school_appears_in_multiple_indices(self):
        """Test that a school can appear in multiple index entries."""
        schools = ["北京师范大学"]

        index = build_area_index(schools)

        # Should be indexed by first char '北' and keyword '师'
        assert "北京师范大学" in index["北"]
        assert "北京师范大学" in index["师"]

    def test_empty_school_list(self):
        """Test building index from empty school list."""
        index = build_area_index([])

        assert index == {}


class TestSchoolNameList:
    """Tests for SCHOOL_NAME_LIST constant."""

    def test_school_name_list_exists(self):
        """Test that SCHOOL_NAME_LIST is defined."""
        assert SCHOOL_NAME_LIST is not None
        assert isinstance(SCHOOL_NAME_LIST, list)

    def test_school_name_list_contains_common_keywords(self):
        """Test that SCHOOL_NAME_LIST contains expected keywords."""
        expected_keywords = ["医", "师", "理", "工", "农", "财", "经"]
        for keyword in expected_keywords:
            assert keyword in SCHOOL_NAME_LIST


class TestModuleLevelData:
    """Tests for module-level data initialization."""

    def test_bachelor_schools_loaded(self):
        """Test that bachelor_schools is loaded at module level."""
        assert bachelor_schools is not None
        assert isinstance(bachelor_schools, list)
        assert len(bachelor_schools) > 0

    def test_associate_schools_loaded(self):
        """Test that associate_schools is loaded at module level."""
        assert associate_schools is not None
        assert isinstance(associate_schools, list)
        assert len(associate_schools) > 0

    def test_area_to_bachelor_schools_built(self):
        """Test that area_to_bachelor_schools index is built."""
        assert area_to_bachelor_schools is not None
        assert isinstance(area_to_bachelor_schools, dict)
        assert len(area_to_bachelor_schools) > 0

    def test_area_to_associate_schools_built(self):
        """Test that area_to_associate_schools index is built."""
        assert area_to_associate_schools is not None
        assert isinstance(area_to_associate_schools, dict)
        assert len(area_to_associate_schools) > 0

    def test_bachelor_schools_contain_expected_schools(self):
        """Test that bachelor_schools contains well-known universities."""
        # These should exist in the bachelor CSV
        expected_schools = ["北京大学", "清华大学"]
        for school in expected_schools:
            assert school in bachelor_schools, f"{school} not found in bachelor_schools"

    def test_area_index_contains_first_char_keys(self):
        """Test that area indices contain first character keys."""
        # Should have entries for common first characters
        assert "北" in area_to_bachelor_schools
        assert "清" in area_to_bachelor_schools

    def test_area_index_contains_keyword_keys(self):
        """Test that area indices contain keyword keys."""
        # Should have entries for common keywords
        assert "师" in area_to_bachelor_schools  # 师范类
        assert "理" in area_to_bachelor_schools  # 理工类

