"""Unit tests for app.schemas.major_intent module."""

from __future__ import annotations

from app.schemas.major_intent import MajorIntentResult, NegativeMajorIntentResult


class TestMajorIntentResult:
    """Tests for MajorIntentResult schema."""

    def test_create_with_all_fields(self):
        """Test creating MajorIntentResult with all fields."""
        result = MajorIntentResult(
            allkeys=["计算机", "软件"],
            level2=["计算机类"],
            level3=["软件工程"],
        )

        assert result.allkeys == ["计算机", "软件"]
        assert result.level2 == ["计算机类"]
        assert result.level3 == ["软件工程"]

    def test_create_with_defaults(self):
        """Test creating MajorIntentResult with default values."""
        result = MajorIntentResult()

        assert result.allkeys == []
        assert result.level2 == []
        assert result.level3 == []

    def test_create_with_partial_fields(self):
        """Test creating MajorIntentResult with partial fields."""
        result = MajorIntentResult(
            allkeys=["哲学"],
            level2=["哲学类"],
        )

        assert result.allkeys == ["哲学"]
        assert result.level2 == ["哲学类"]
        assert result.level3 == []

    def test_model_dump(self):
        """Test converting MajorIntentResult to dict."""
        result = MajorIntentResult(
            allkeys=["经济"],
            level2=["经济学类"],
            level3=["经济学"],
        )

        data = result.model_dump()

        assert data["allkeys"] == ["经济"]
        assert data["level2"] == ["经济学类"]
        assert data["level3"] == ["经济学"]

    def test_field_descriptions(self):
        """Test that field descriptions are set correctly."""
        assert MajorIntentResult.model_fields["allkeys"].description == "原始专业词汇"
        assert MajorIntentResult.model_fields["level2"].description == "二级专业（大类）"
        assert MajorIntentResult.model_fields["level3"].description == "三级专业（具体专业）"


class TestNegativeMajorIntentResult:
    """Tests for NegativeMajorIntentResult schema."""

    def test_create_with_all_fields(self):
        """Test creating NegativeMajorIntentResult with all fields."""
        result = NegativeMajorIntentResult(
            allkeys=["医学", "护理"],
            level2=["医学类"],
            level3=["护理学"],
        )

        assert result.allkeys == ["医学", "护理"]
        assert result.level2 == ["医学类"]
        assert result.level3 == ["护理学"]

    def test_create_with_defaults(self):
        """Test creating NegativeMajorIntentResult with default values."""
        result = NegativeMajorIntentResult()

        assert result.allkeys == []
        assert result.level2 == []
        assert result.level3 == []

    def test_create_with_partial_fields(self):
        """Test creating NegativeMajorIntentResult with partial fields."""
        result = NegativeMajorIntentResult(
            allkeys=["生物"],
            level3=["生物科学"],
        )

        assert result.allkeys == ["生物"]
        assert result.level2 == []
        assert result.level3 == ["生物科学"]

    def test_model_dump(self):
        """Test converting NegativeMajorIntentResult to dict."""
        result = NegativeMajorIntentResult(
            allkeys=["化学"],
            level2=["化学类"],
            level3=[],
        )

        data = result.model_dump()

        assert data["allkeys"] == ["化学"]
        assert data["level2"] == ["化学类"]
        assert data["level3"] == []

    def test_field_descriptions(self):
        """Test that field descriptions are set correctly."""
        assert NegativeMajorIntentResult.model_fields["allkeys"].description == "原始专业词汇"
        assert NegativeMajorIntentResult.model_fields["level2"].description == "负面二级专业"
        assert NegativeMajorIntentResult.model_fields["level3"].description == "负面三级专业"

    def test_separate_from_positive_result(self):
        """Test that negative and positive results are separate types."""
        positive = MajorIntentResult(allkeys=["计算机"], level2=["计算机类"])
        negative = NegativeMajorIntentResult(allkeys=["医学"], level2=["医学类"])

        assert type(positive) != type(negative)
        assert isinstance(positive, MajorIntentResult)
        assert isinstance(negative, NegativeMajorIntentResult)
