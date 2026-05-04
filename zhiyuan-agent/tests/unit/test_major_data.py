"""Unit tests for app.data.major_data module."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import mock_open, patch

import pytest

from app.data.major_data import (
    build_line_number_mappings,
    build_major_mappings,
    build_prefix_index,
    flatten_hierarchy_to_lines,
    load_major_hierarchy,
)


# ---- load_major_hierarchy ----


class TestLoadMajorHierarchy:
    """Tests for load_major_hierarchy function."""

    def test_load_valid_json(self, tmp_path: Path):
        """Test loading a valid major hierarchy JSON file."""
        json_data = {
            "code": 0,
            "data": [
                {
                    "id": "1",
                    "label": "哲学",
                    "parentId": "0",
                    "children": [
                        {
                            "id": "2",
                            "label": "哲学类",
                            "parentId": "1",
                            "children": [
                                {
                                    "id": "233",
                                    "label": "哲学",
                                    "majorCode": "010101",
                                    "parentId": "2",
                                }
                            ],
                        }
                    ],
                }
            ],
        }
        json_file = tmp_path / "test_major.json"
        json_file.write_text(json.dumps(json_data, ensure_ascii=False))

        result = load_major_hierarchy(json_file)

        assert result["code"] == 0
        assert len(result["data"]) == 1
        assert result["data"][0]["label"] == "哲学"

    def test_load_file_not_found(self, tmp_path: Path):
        """Test that FileNotFoundError is raised when file doesn't exist."""
        non_existent = tmp_path / "non_existent.json"

        with pytest.raises(FileNotFoundError, match="Major data file not found"):
            load_major_hierarchy(non_existent)

    def test_load_invalid_json(self, tmp_path: Path):
        """Test that ValueError is raised for invalid JSON."""
        json_file = tmp_path / "invalid.json"
        json_file.write_text("{invalid json")

        with pytest.raises(ValueError, match="Failed to parse JSON file"):
            load_major_hierarchy(json_file)

    def test_load_missing_data_key(self, tmp_path: Path):
        """Test that ValueError is raised when 'data' key is missing."""
        json_data = {"code": 0}
        json_file = tmp_path / "no_data.json"
        json_file.write_text(json.dumps(json_data))

        with pytest.raises(ValueError, match="missing 'data' key"):
            load_major_hierarchy(json_file)

    def test_load_data_not_list(self, tmp_path: Path):
        """Test that ValueError is raised when 'data' is not a list."""
        json_data = {"code": 0, "data": "not a list"}
        json_file = tmp_path / "bad_data.json"
        json_file.write_text(json.dumps(json_data))

        with pytest.raises(ValueError, match="'data' must be a list"):
            load_major_hierarchy(json_file)

    def test_load_not_dict(self, tmp_path: Path):
        """Test that ValueError is raised when JSON root is not a dict."""
        json_file = tmp_path / "list_root.json"
        json_file.write_text("[]")

        with pytest.raises(ValueError, match="expected dict"):
            load_major_hierarchy(json_file)


# ---- build_prefix_index ----


class TestBuildPrefixIndex:
    """Tests for build_prefix_index function."""

    def test_build_index_for_level2_and_level3(self):
        """Test that prefix index is built for both level2 and level3."""
        hierarchy = {
            "data": [
                {
                    "label": "哲学",
                    "children": [
                        {
                            "label": "哲学类",
                            "children": [
                                {"label": "哲学"},
                                {"label": "逻辑学"},
                            ],
                        }
                    ],
                }
            ]
        }

        result = build_prefix_index(hierarchy)

        assert "哲学" in result
        assert "哲学类" in result["哲学"]
        assert "哲学" in result["哲学"]
        assert "逻辑" in result
        assert "逻辑学" in result["逻辑"]

    def test_build_index_deduplicates(self):
        """Test that duplicate majors in same prefix are not duplicated."""
        hierarchy = {
            "data": [
                {
                    "label": "工学",
                    "children": [
                        {
                            "label": "计算机类",
                            "children": [
                                {"label": "计算机科学与技术"},
                            ],
                        },
                        {
                            "label": "软件工程类",
                            "children": [
                                {"label": "计算机应用"},
                            ],
                        },
                    ],
                }
            ]
        }

        result = build_prefix_index(hierarchy)

        # All three start with "计算"
        assert "计算" in result
        assert len(result["计算"]) == 3
        assert "计算机类" in result["计算"]
        assert "计算机科学与技术" in result["计算"]
        assert "计算机应用" in result["计算"]

    def test_build_index_ignores_short_labels(self):
        """Test that labels shorter than 2 characters are ignored."""
        hierarchy = {
            "data": [
                {
                    "label": "A",
                    "children": [
                        {
                            "label": "B",
                            "children": [{"label": "C"}],
                        }
                    ],
                }
            ]
        }

        result = build_prefix_index(hierarchy)

        assert len(result) == 0

    def test_build_index_empty_hierarchy(self):
        """Test building index from empty hierarchy."""
        hierarchy = {"data": []}

        result = build_prefix_index(hierarchy)

        assert result == {}

    def test_build_index_no_children(self):
        """Test building index when categories have no children."""
        hierarchy = {
            "data": [
                {"label": "哲学", "children": []}
            ]
        }

        result = build_prefix_index(hierarchy)

        assert result == {}


# ---- build_line_number_mappings ----


class TestBuildLineNumberMappings:
    """Tests for build_line_number_mappings function."""

    def test_build_mappings_simple_hierarchy(self):
        """Test building line number mappings for a simple hierarchy."""
        hierarchy = {
            "data": [
                {
                    "label": "哲学",
                    "children": [
                        {
                            "label": "哲学类",
                            "children": [
                                {"label": "哲学"},
                            ],
                        }
                    ],
                }
            ]
        }

        category_map, subcategory_map, major_map = build_line_number_mappings(hierarchy)

        # Line 0: 哲学 (category)
        # Line 1: 哲学类 (subcategory)
        # Line 2: 哲学 (major)
        assert "哲学" in category_map
        assert 0 in category_map["哲学"]
        assert "哲学类" in subcategory_map
        assert 1 in subcategory_map["哲学类"]
        assert "哲学" in major_map
        assert 2 in major_map["哲学"]

    def test_build_mappings_cascading_line_numbers(self):
        """Test that parent line maps include child line numbers."""
        hierarchy = {
            "data": [
                {
                    "label": "工学",
                    "children": [
                        {
                            "label": "计算机类",
                            "children": [
                                {"label": "计算机科学与技术"},
                                {"label": "软件工程"},
                            ],
                        }
                    ],
                }
            ]
        }

        category_map, subcategory_map, major_map = build_line_number_mappings(hierarchy)

        # Category should include all descendant lines
        assert len(category_map["工学"]) == 4  # category + subcategory + 2 majors
        # Subcategory should include its line and child major lines
        assert len(subcategory_map["计算机类"]) == 3  # subcategory + 2 majors

    def test_build_mappings_multiple_categories(self):
        """Test building mappings with multiple categories."""
        hierarchy = {
            "data": [
                {
                    "label": "哲学",
                    "children": [
                        {
                            "label": "哲学类",
                            "children": [{"label": "哲学"}],
                        }
                    ],
                },
                {
                    "label": "经济学",
                    "children": [
                        {
                            "label": "经济学类",
                            "children": [{"label": "经济学"}],
                        }
                    ],
                },
            ]
        }

        category_map, subcategory_map, major_map = build_line_number_mappings(hierarchy)

        assert "哲学" in category_map
        assert "经济学" in category_map
        assert category_map["哲学"][0] < category_map["经济学"][0]

    def test_build_mappings_empty_hierarchy(self):
        """Test building mappings from empty hierarchy."""
        hierarchy = {"data": []}

        category_map, subcategory_map, major_map = build_line_number_mappings(hierarchy)

        assert category_map == {}
        assert subcategory_map == {}
        assert major_map == {}


# ---- flatten_hierarchy_to_lines ----


class TestFlattenHierarchyToLines:
    """Tests for flatten_hierarchy_to_lines function."""

    def test_flatten_simple_hierarchy(self):
        """Test flattening a simple hierarchy."""
        hierarchy = {
            "data": [
                {
                    "label": "哲学",
                    "children": [
                        {
                            "label": "哲学类",
                            "children": [
                                {"label": "哲学"},
                            ],
                        }
                    ],
                }
            ]
        }

        result = flatten_hierarchy_to_lines(hierarchy)

        assert len(result) == 3
        assert result[0] == "哲学"
        assert result[1] == "  哲学类"
        assert result[2] == "    哲学"

    def test_flatten_preserves_indentation(self):
        """Test that indentation correctly represents hierarchy levels."""
        hierarchy = {
            "data": [
                {
                    "label": "工学",
                    "children": [
                        {
                            "label": "计算机类",
                            "children": [
                                {"label": "计算机科学与技术"},
                                {"label": "软件工程"},
                            ],
                        }
                    ],
                }
            ]
        }

        result = flatten_hierarchy_to_lines(hierarchy)

        assert result[0] == "工学"
        assert result[1].startswith("  ")
        assert result[2].startswith("    ")
        assert result[3].startswith("    ")

    def test_flatten_empty_hierarchy(self):
        """Test flattening empty hierarchy."""
        hierarchy = {"data": []}

        result = flatten_hierarchy_to_lines(hierarchy)

        assert result == []


# ---- build_major_mappings ----


class TestBuildMajorMappings:
    """Tests for build_major_mappings function."""

    def test_build_mappings_simple(self):
        """Test building major mappings."""
        hierarchy = {
            "data": [
                {
                    "label": "哲学",
                    "children": [
                        {
                            "label": "哲学类",
                            "children": [
                                {"label": "哲学"},
                                {"label": "逻辑学"},
                            ],
                        }
                    ],
                }
            ]
        }

        result = build_major_mappings(hierarchy)

        assert "level2_to_level1" in result
        assert "level3_to_level2" in result
        assert result["level2_to_level1"]["哲学类"] == "哲学"
        assert result["level3_to_level2"]["哲学"] == "哲学类"
        assert result["level3_to_level2"]["逻辑学"] == "哲学类"

    def test_build_mappings_multiple_categories(self):
        """Test building mappings with multiple categories."""
        hierarchy = {
            "data": [
                {
                    "label": "哲学",
                    "children": [
                        {
                            "label": "哲学类",
                            "children": [{"label": "哲学"}],
                        }
                    ],
                },
                {
                    "label": "经济学",
                    "children": [
                        {
                            "label": "经济学类",
                            "children": [{"label": "经济学"}],
                        }
                    ],
                },
            ]
        }

        result = build_major_mappings(hierarchy)

        assert result["level2_to_level1"]["哲学类"] == "哲学"
        assert result["level2_to_level1"]["经济学类"] == "经济学"
        assert result["level3_to_level2"]["哲学"] == "哲学类"
        assert result["level3_to_level2"]["经济学"] == "经济学类"

    def test_build_mappings_empty_hierarchy(self):
        """Test building mappings from empty hierarchy."""
        hierarchy = {"data": []}

        result = build_major_mappings(hierarchy)

        assert result["level2_to_level1"] == {}
        assert result["level3_to_level2"] == {}
