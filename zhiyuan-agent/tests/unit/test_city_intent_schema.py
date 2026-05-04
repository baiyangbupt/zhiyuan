"""Unit tests for app.schemas.city_intent module."""

import json

import pytest

from app.schemas.city_intent import CityIntentResult, NegativeCityIntentResult


class TestCityIntentResult:
    """Tests for CityIntentResult model."""

    def test_default_empty_fields(self):
        """Test that all fields default to empty lists."""
        result = CityIntentResult()

        assert result.province == []
        assert result.city == []
        assert result.area == []

    def test_with_data(self):
        """Test creating result with actual data."""
        result = CityIntentResult(
            province=["北京", "上海"],
            city=["广州", "深圳"],
            area=["华东地区"],
        )

        assert result.province == ["北京", "上海"]
        assert result.city == ["广州", "深圳"]
        assert result.area == ["华东地区"]

    def test_json_serialization(self):
        """Test model can be serialized to JSON."""
        result = CityIntentResult(
            province=["江苏", "浙江"],
            city=["南京"],
            area=[],
        )

        json_str = json.dumps(result.model_dump(), ensure_ascii=False)
        parsed = json.loads(json_str)

        assert parsed["province"] == ["江苏", "浙江"]
        assert parsed["city"] == ["南京"]
        assert parsed["area"] == []

    def test_json_deserialization(self):
        """Test model can be created from JSON dict."""
        data = {
            "province": ["四川"],
            "city": ["成都"],
            "area": [],
        }

        result = CityIntentResult(**data)

        assert result.province == ["四川"]
        assert result.city == ["成都"]
        assert result.area == []

    def test_model_dump(self):
        """Test model_dump produces correct dict."""
        result = CityIntentResult(
            province=["广东"],
            city=["深圳"],
            area=[],
        )

        dumped = result.model_dump()

        assert isinstance(dumped, dict)
        assert "province" in dumped
        assert "city" in dumped
        assert "area" in dumped

    def test_partial_fields(self):
        """Test creating result with only some fields specified."""
        result = CityIntentResult(province=["北京"])

        assert result.province == ["北京"]
        assert result.city == []
        assert result.area == []

    def test_all_fields_populated(self):
        """Test creating result with all fields populated."""
        result = CityIntentResult(
            province=["北京", "天津", "河北"],
            city=["广州", "深圳", "杭州"],
            area=["京津冀"],
        )

        assert len(result.province) == 3
        assert len(result.city) == 3
        assert len(result.area) == 1

    def test_model_dump_ensure_ascii_false(self):
        """Test that Chinese characters are preserved in JSON output."""
        result = CityIntentResult(
            province=["北京"],
            city=["广州"],
            area=[],
        )

        json_str = json.dumps(result.model_dump(), ensure_ascii=False)

        assert "北京" in json_str
        assert "广州" in json_str


class TestNegativeCityIntentResult:
    """Tests for NegativeCityIntentResult model."""

    def test_default_empty_fields(self):
        """Test that all fields default to empty lists."""
        result = NegativeCityIntentResult()

        assert result.province == []
        assert result.city == []

    def test_no_area_field(self):
        """Test that NegativeCityIntentResult does not have an area field."""
        result = NegativeCityIntentResult()

        assert not hasattr(result, "area") or "area" not in result.model_fields

    def test_with_data(self):
        """Test creating result with actual data."""
        result = NegativeCityIntentResult(
            province=["新疆", "西藏"],
            city=["乌鲁木齐"],
        )

        assert result.province == ["新疆", "西藏"]
        assert result.city == ["乌鲁木齐"]

    def test_json_serialization(self):
        """Test model can be serialized to JSON."""
        result = NegativeCityIntentResult(
            province=["甘肃"],
            city=["兰州"],
        )

        json_str = json.dumps(result.model_dump(), ensure_ascii=False)
        parsed = json.loads(json_str)

        assert parsed["province"] == ["甘肃"]
        assert parsed["city"] == ["兰州"]
        assert "area" not in parsed

    def test_json_deserialization(self):
        """Test model can be created from JSON dict."""
        data = {
            "province": ["宁夏"],
            "city": ["银川"],
        }

        result = NegativeCityIntentResult(**data)

        assert result.province == ["宁夏"]
        assert result.city == ["银川"]

    def test_model_dump(self):
        """Test model_dump produces correct dict with only province and city."""
        result = NegativeCityIntentResult(
            province=["内蒙古"],
            city=["呼和浩特"],
        )

        dumped = result.model_dump()

        assert isinstance(dumped, dict)
        assert "province" in dumped
        assert "city" in dumped
        assert "area" not in dumped

    def test_partial_fields(self):
        """Test creating result with only province specified."""
        result = NegativeCityIntentResult(province=["青海"])

        assert result.province == ["青海"]
        assert result.city == []

    def test_model_dump_ensure_ascii_false(self):
        """Test that Chinese characters are preserved in JSON output."""
        result = NegativeCityIntentResult(
            province=["西藏"],
            city=["拉萨"],
        )

        json_str = json.dumps(result.model_dump(), ensure_ascii=False)

        assert "西藏" in json_str
        assert "拉萨" in json_str
        assert "area" not in json_str
