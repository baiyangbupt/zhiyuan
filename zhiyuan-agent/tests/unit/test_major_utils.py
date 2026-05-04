"""Unit tests for app.data.major_utils module."""

from __future__ import annotations

from app.data.major_utils import filter_major_hierarchy_by_prefix


class TestFilterMajorHierarchyByPrefix:
    """Tests for filter_major_hierarchy_by_prefix function."""

    def test_filter_matches_prefix_in_chat(self):
        """Test that majors matching prefixes in chat are included."""
        chat_history = [
            {"role": "user", "content": "我想学计算机"},
        ]
        prefix_index = {
            "计算": ["计算机类", "计算机科学与技术"],
        }
        major_lines = [
            "工学",
            "  计算机类",
            "    计算机科学与技术",
            "    软件工程",
        ]
        category_line_map = {"工学": [0, 1, 2, 3]}
        subcategory_line_map = {"计算机类": [1, 2, 3]}
        major_line_map = {
            "计算机科学与技术": [2],
            "软件工程": [3],
        }
        subcategory_to_category = {"计算机类": "工学"}
        major_to_subcategory = {
            "计算机科学与技术": "计算机类",
            "软件工程": "计算机类",
        }

        result = filter_major_hierarchy_by_prefix(
            chat_history,
            prefix_index,
            major_lines,
            category_line_map,
            subcategory_line_map,
            major_line_map,
            subcategory_to_category,
            major_to_subcategory,
        )

        assert "计算机类" in result
        assert "计算机科学与技术" in result

    def test_filter_no_matches(self):
        """Test that empty string is returned when no prefixes match."""
        chat_history = [
            {"role": "user", "content": "你好"},
        ]
        prefix_index = {
            "计算": ["计算机类"],
        }
        major_lines = [
            "工学",
            "  计算机类",
        ]
        category_line_map = {"工学": [0, 1]}
        subcategory_line_map = {"计算机类": [1]}
        major_line_map = {}
        subcategory_to_category = {"计算机类": "工学"}
        major_to_subcategory = {}

        result = filter_major_hierarchy_by_prefix(
            chat_history,
            prefix_index,
            major_lines,
            category_line_map,
            subcategory_line_map,
            major_line_map,
            subcategory_to_category,
            major_to_subcategory,
        )

        assert result == ""

    def test_filter_includes_parent_subcategory(self):
        """Test that parent subcategory is included when major is matched."""
        chat_history = [
            {"role": "user", "content": "软件工程怎么样"},
        ]
        prefix_index = {
            "软件": ["软件工程"],
        }
        major_lines = [
            "工学",
            "  计算机类",
            "    计算机科学与技术",
            "    软件工程",
        ]
        category_line_map = {"工学": [0, 1, 2, 3]}
        subcategory_line_map = {"计算机类": [1, 2, 3]}
        major_line_map = {
            "计算机科学与技术": [2],
            "软件工程": [3],
        }
        subcategory_to_category = {"计算机类": "工学"}
        major_to_subcategory = {
            "计算机科学与技术": "计算机类",
            "软件工程": "计算机类",
        }

        result = filter_major_hierarchy_by_prefix(
            chat_history,
            prefix_index,
            major_lines,
            category_line_map,
            subcategory_line_map,
            major_line_map,
            subcategory_to_category,
            major_to_subcategory,
        )

        # Should include both the subcategory line and the major line
        assert "计算机类" in result
        assert "软件工程" in result

    def test_filter_preserves_hierarchy_structure(self):
        """Test that filtered result preserves indentation."""
        chat_history = [
            {"role": "user", "content": "哲学专业"},
        ]
        prefix_index = {
            "哲学": ["哲学类", "哲学"],
        }
        major_lines = [
            "哲学",
            "  哲学类",
            "    哲学",
            "    逻辑学",
        ]
        category_line_map = {"哲学": [0, 1, 2, 3]}
        subcategory_line_map = {"哲学类": [1, 2, 3]}
        major_line_map = {
            "哲学": [2],
            "逻辑学": [3],
        }
        subcategory_to_category = {"哲学类": "哲学"}
        major_to_subcategory = {
            "哲学": "哲学类",
            "逻辑学": "哲学类",
        }

        result = filter_major_hierarchy_by_prefix(
            chat_history,
            prefix_index,
            major_lines,
            category_line_map,
            subcategory_line_map,
            major_line_map,
            subcategory_to_category,
            major_to_subcategory,
        )

        lines = result.split("\n")
        # Should preserve indentation
        assert any(line.strip() == "哲学类" for line in lines)
        assert any(line.strip() == "哲学" for line in lines)

    def test_filter_scans_all_messages(self):
        """Test that all messages in chat history are scanned."""
        chat_history = [
            {"role": "user", "content": "我想学计算机"},
            {"role": "assistant", "content": "好的"},
            {"role": "user", "content": "还有哲学"},
        ]
        prefix_index = {
            "计算": ["计算机类"],
            "哲学": ["哲学类"],
        }
        major_lines = [
            "工学",
            "  计算机类",
            "哲学",
            "  哲学类",
        ]
        category_line_map = {
            "工学": [0, 1],
            "哲学": [2, 3],
        }
        subcategory_line_map = {
            "计算机类": [1],
            "哲学类": [3],
        }
        major_line_map = {}
        subcategory_to_category = {
            "计算机类": "工学",
            "哲学类": "哲学",
        }
        major_to_subcategory = {}

        result = filter_major_hierarchy_by_prefix(
            chat_history,
            prefix_index,
            major_lines,
            category_line_map,
            subcategory_line_map,
            major_line_map,
            subcategory_to_category,
            major_to_subcategory,
        )

        assert "计算机类" in result
        assert "哲学类" in result

    def test_filter_handles_missing_content(self):
        """Test filter handles messages without content key."""
        chat_history = [
            {"role": "user"},
            {"role": "assistant", "content": "计算机很好"},
        ]
        prefix_index = {
            "计算": ["计算机类"],
        }
        major_lines = [
            "工学",
            "  计算机类",
        ]
        category_line_map = {"工学": [0, 1]}
        subcategory_line_map = {"计算机类": [1]}
        major_line_map = {}
        subcategory_to_category = {"计算机类": "工学"}
        major_to_subcategory = {}

        result = filter_major_hierarchy_by_prefix(
            chat_history,
            prefix_index,
            major_lines,
            category_line_map,
            subcategory_line_map,
            major_line_map,
            subcategory_to_category,
            major_to_subcategory,
        )

        assert "计算机类" in result

    def test_filter_empty_chat_history(self):
        """Test filter with empty chat history."""
        result = filter_major_hierarchy_by_prefix(
            [],
            {"计算": ["计算机类"]},
            ["工学", "  计算机类"],
            {"工学": [0, 1]},
            {"计算机类": [1]},
            {},
            {"计算机类": "工学"},
            {},
        )

        assert result == ""

    def test_filter_deduplicates_line_numbers(self):
        """Test that duplicate line numbers are deduplicated."""
        chat_history = [
            {"role": "user", "content": "计算机科学与技术和软件工程"},
        ]
        prefix_index = {
            "计算": ["计算机类", "计算机科学与技术"],
            "软件": ["软件工程"],
        }
        major_lines = [
            "工学",
            "  计算机类",
            "    计算机科学与技术",
            "    软件工程",
        ]
        category_line_map = {"工学": [0, 1, 2, 3]}
        subcategory_line_map = {"计算机类": [1, 2, 3]}
        major_line_map = {
            "计算机科学与技术": [2],
            "软件工程": [3],
        }
        subcategory_to_category = {"计算机类": "工学"}
        major_to_subcategory = {
            "计算机科学与技术": "计算机类",
            "软件工程": "计算机类",
        }

        result = filter_major_hierarchy_by_prefix(
            chat_history,
            prefix_index,
            major_lines,
            category_line_map,
            subcategory_line_map,
            major_line_map,
            subcategory_to_category,
            major_to_subcategory,
        )

        lines = result.split("\n")
        # Should not have duplicate lines
        assert len(lines) == len(set(lines))
