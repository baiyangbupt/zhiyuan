"""Unit tests for app.schemas.school_intent module."""

import json

import pytest

from app.schemas.school_intent import SchoolIntentResult


class TestSchoolIntentResult:
    """Tests for SchoolIntentResult model."""

    def test_default_empty_fields(self):
        """Test that all fields default to empty lists."""
        result = SchoolIntentResult()

        assert result.allkeys == []
        assert result.newkeys == []
        assert result.colleges == []
        assert result.negative_colleges == []

    def test_with_data(self):
        """Test creating result with actual data."""
        result = SchoolIntentResult(
            allkeys=["北大", "清华"],
            newkeys=["北京大学", "清华大学"],
            colleges=["北京大学"],
            negative_colleges=["清华大学"],
        )

        assert result.allkeys == ["北大", "清华"]
        assert result.newkeys == ["北京大学", "清华大学"]
        assert result.colleges == ["北京大学"]
        assert result.negative_colleges == ["清华大学"]

    def test_json_serialization(self):
        """Test model can be serialized to JSON."""
        result = SchoolIntentResult(
            allkeys=["北大"],
            newkeys=["北京大学"],
            colleges=["北京大学"],
            negative_colleges=[],
        )

        json_str = json.dumps(result.model_dump(), ensure_ascii=False)
        parsed = json.loads(json_str)

        assert parsed["allkeys"] == ["北大"]
        assert parsed["newkeys"] == ["北京大学"]
        assert parsed["colleges"] == ["北京大学"]
        assert parsed["negative_colleges"] == []

    def test_json_deserialization(self):
        """Test model can be created from JSON dict."""
        data = {
            "allkeys": ["复旦"],
            "newkeys": ["复旦大学"],
            "colleges": ["复旦大学"],
            "negative_colleges": [],
        }

        result = SchoolIntentResult(**data)

        assert result.allkeys == ["复旦"]
        assert result.colleges == ["复旦大学"]

    def test_model_dump(self):
        """Test model_dump produces correct dict."""
        result = SchoolIntentResult(
            allkeys=["浙大"],
            newkeys=["浙江大学"],
            colleges=["浙江大学"],
            negative_colleges=[],
        )

        dumped = result.model_dump()

        assert isinstance(dumped, dict)
        assert "allkeys" in dumped
        assert "newkeys" in dumped
        assert "colleges" in dumped
        assert "negative_colleges" in dumped

    def test_partial_fields(self):
        """Test creating result with only some fields specified."""
        result = SchoolIntentResult(colleges=["北京大学"])

        assert result.allkeys == []
        assert result.newkeys == []
        assert result.colleges == ["北京大学"]
        assert result.negative_colleges == []
