"""Unit tests for app.tools.city_intent_tool module."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import RunContext

from app.agent.context import RequestContext
from app.schemas.city_intent import CityIntentPolarityResult, CityIntentResult, NegativeCityIntentResult
from app.tools.city_intent_tool import (
    _build_negative_system_message,
    _build_positive_system_message,
    _format_student_info,
    extract_city_intents_with_polarity,
    extract_city_intent,
    extract_negative_city_intent,
)


# ---- _format_student_info ----


class TestFormatStudentInfo:
    """Tests for _format_student_info function."""

    def test_format_with_full_info(self):
        """Test formatting with complete student info."""
        score_detail = {
            "sex": {"name": "男"},
            "province": {"name": "北京"},
        }

        result = _format_student_info(score_detail)

        assert "男" in result
        assert "北京" in result

    def test_format_with_none(self):
        """Test formatting with None score_detail."""
        result = _format_student_info(None)

        assert result == "暂无学生信息"

    def test_format_with_empty_dict(self):
        """Test formatting with empty dict (falsy, treated as None)."""
        result = _format_student_info({})

        assert result == "暂无学生信息"

    def test_format_with_partial_info_missing_province(self):
        """Test formatting with partial student info (missing province)."""
        score_detail = {
            "sex": {"name": "女"},
        }

        result = _format_student_info(score_detail)

        assert "女" in result
        assert "未知" in result  # province missing

    def test_format_with_partial_info_missing_sex(self):
        """Test formatting with partial student info (missing sex)."""
        score_detail = {
            "province": {"name": "河北"},
        }

        result = _format_student_info(score_detail)

        assert "未知" in result  # sex missing
        assert "河北" in result

    def test_format_with_missing_name_key(self):
        """Test formatting when nested 'name' key is missing."""
        score_detail = {
            "sex": {},
            "province": {"name": "河北"},
        }

        result = _format_student_info(score_detail)

        assert "未知" in result  # sex.name missing
        assert "河北" in result

    def test_format_output_structure(self):
        """Test that output follows expected format string."""
        score_detail = {
            "sex": {"name": "男"},
            "province": {"name": "山东"},
        }

        result = _format_student_info(score_detail)

        assert result == "学生性别：男，学生所在省份：山东"


# ---- _build_positive_system_message ----


class TestBuildPositiveSystemMessage:
    """Tests for _build_positive_system_message function."""

    def test_contains_chat_history(self):
        """Test that built prompt contains chat history string."""
        chat_history_str = "学生: 我想去北京上学"
        student_info = "学生性别：男，学生所在省份：北京"

        result = _build_positive_system_message(chat_history_str, student_info)

        assert "我想去北京上学" in result

    def test_contains_student_info(self):
        """Test that built prompt contains student info."""
        chat_history_str = "学生: 测试"
        student_info = "学生性别：女，学生所在省份：浙江"

        result = _build_positive_system_message(chat_history_str, student_info)

        assert "学生性别：女，学生所在省份：浙江" in result

    def test_contains_task_description(self):
        """Test that built prompt contains positive task description."""
        result = _build_positive_system_message("学生: 测试", "暂无学生信息")

        assert "省份和城市实体提取工具" in result
        assert "正面" in result

    def test_contains_extraction_rules(self):
        """Test that built prompt contains extraction rules."""
        result = _build_positive_system_message("学生: 测试", "暂无学生信息")

        assert "province" in result
        assert "city" in result
        assert "area" in result

    def test_contains_province_city_hierarchy(self):
        """Test that built prompt contains province/city hierarchy data."""
        result = _build_positive_system_message("学生: 测试", "暂无学生信息")

        assert "省市层级结构" in result
        # Should contain actual province/city data
        assert "安徽" in result or "北京" in result

    def test_contains_special_cases(self):
        """Test that built prompt contains special case rules."""
        result = _build_positive_system_message("学生: 测试", "暂无学生信息")

        # Check for key special case keywords
        assert "京津冀" in result
        assert "江浙沪" in result
        assert "北上广深" in result
        assert "东北" in result
        assert "东三省" in result
        assert "一线城市" in result
        assert "新一线城市" in result

    def test_contains_return_format_with_area(self):
        """Test that positive prompt return format includes area field."""
        result = _build_positive_system_message("学生: 测试", "暂无学生信息")

        assert '"area"' in result

    def test_contains_regional_grouping_rules(self):
        """Test that built prompt contains regional grouping rules."""
        result = _build_positive_system_message("学生: 测试", "暂无学生信息")

        assert "南方" in result
        assert "北方" in result
        assert "偏远地区" in result
        assert "西南" in result
        assert "西北" in result
        assert "华北" in result
        assert "华东" in result
        assert "华中" in result
        assert "华南" in result
        assert "东南" in result
        assert "中南" in result

    def test_contains_city_tier_rules(self):
        """Test that built prompt contains city tier rules."""
        result = _build_positive_system_message("学生: 测试", "暂无学生信息")

        assert "二线城市" in result
        assert "三线城市" in result
        assert "发达省份" in result
        assert "发达城市" in result
        assert "不发达" in result


# ---- _build_negative_system_message ----


class TestBuildNegativeSystemMessage:
    """Tests for _build_negative_system_message function."""

    def test_contains_chat_history(self):
        """Test that built prompt contains chat history string."""
        chat_history_str = "学生: 我不想去东北"
        student_info = "学生性别：男，学生所在省份：广东"

        result = _build_negative_system_message(chat_history_str, student_info)

        assert "我不想去东北" in result

    def test_contains_student_info(self):
        """Test that built prompt contains student info."""
        chat_history_str = "学生: 测试"
        student_info = "学生性别：男，学生所在省份：广东"

        result = _build_negative_system_message(chat_history_str, student_info)

        assert "学生性别：男，学生所在省份：广东" in result

    def test_contains_negative_task_description(self):
        """Test that built prompt contains negative task description."""
        result = _build_negative_system_message("学生: 测试", "暂无学生信息")

        assert "省份和城市实体提取工具" in result
        assert "负面" in result

    def test_return_format_no_area(self):
        """Test that negative prompt return format does NOT include area field."""
        result = _build_negative_system_message("学生: 测试", "暂无学生信息")

        # Negative return format should only have province and city
        # The format section should not contain "area"
        # Split at 返回格式 section and check
        format_section = result.split("返回格式")[1] if "返回格式" in result else ""
        assert "area" not in format_section

    def test_contains_special_cases(self):
        """Test that negative prompt also contains special case rules."""
        result = _build_negative_system_message("学生: 测试", "暂无学生信息")

        assert "京津冀" in result
        assert "江浙沪" in result
        assert "新一线城市" in result

    def test_contains_negative_extraction_rules(self):
        """Test that negative prompt contains negative-specific rules."""
        result = _build_negative_system_message("学生: 测试", "暂无学生信息")

        assert "不感兴趣" in result
        assert "不考虑" in result
        assert "不接受" in result
        assert "不想去" in result
        assert "不喜欢" in result

    def test_contains_province_city_hierarchy(self):
        """Test that negative prompt also includes hierarchy data."""
        result = _build_negative_system_message("学生: 测试", "暂无学生信息")

        assert "省市层级结构" in result


# ---- Positive vs Negative prompt difference ----


class TestPositiveVsNegativePromptDifference:
    """Tests verifying key differences between positive and negative prompts."""

    def test_positive_has_area_negative_does_not(self):
        """Test that positive prompt has area field but negative does not."""
        positive = _build_positive_system_message("学生: 测试", "暂无")
        negative = _build_negative_system_message("学生: 测试", "暂无")

        # Positive format section should have area
        pos_format = positive.split("返回格式")[1]
        assert "area" in pos_format

        # Negative format section should NOT have area
        neg_format = negative.split("返回格式")[1]
        assert "area" not in neg_format

    def test_positive_mentions_positive_intent(self):
        """Test that positive prompt mentions positive intent keywords."""
        result = _build_positive_system_message("学生: 测试", "暂无")

        assert "正面" in result

    def test_negative_mentions_negative_intent(self):
        """Test that negative prompt mentions negative intent keywords."""
        result = _build_negative_system_message("学生: 测试", "暂无")

        assert "负面" in result


# ---- extract_city_intent ----


class TestExtractCityIntent:
    """Tests for extract_city_intent async function."""

    def _make_run_context(self, **kwargs) -> MagicMock:
        """Helper to create a mock RunContext with RequestContext deps."""
        defaults = {
            "userid": "test_user",
            "sessionid": "test_session",
            "chat_history": None,
            "batch": None,
            "score_detail": None,
        }
        defaults.update(kwargs)
        ctx = MagicMock(spec=RunContext)
        ctx.deps = RequestContext(**defaults)
        return ctx

    async def test_returns_empty_when_no_chat_history(self):
        """Test that empty result is returned when chat_history is None."""
        ctx = self._make_run_context(chat_history=None)

        result = await extract_city_intent(ctx)

        parsed = json.loads(result)
        assert parsed["province"] == []
        assert parsed["city"] == []
        assert parsed["area"] == []

    async def test_returns_empty_when_chat_history_is_empty_list(self):
        """Test that empty result is returned when chat_history is empty."""
        ctx = self._make_run_context(chat_history=[])

        result = await extract_city_intent(ctx)

        parsed = json.loads(result)
        assert parsed["province"] == []
        assert parsed["city"] == []
        assert parsed["area"] == []

    async def test_empty_result_is_valid_json(self):
        """Test that empty result is valid JSON."""
        ctx = self._make_run_context(chat_history=None)

        result = await extract_city_intent(ctx)

        parsed = json.loads(result)
        assert isinstance(parsed, dict)
        assert "province" in parsed
        assert "city" in parsed
        assert "area" in parsed

    @patch("app.tools.city_intent_tool._get_extraction_client")
    @patch("app.tools.city_intent_tool._get_extract_config")
    @patch("app.tools.city_intent_tool.Agent")
    async def test_calls_agent_with_correct_output_type(
        self, mock_agent_cls, mock_config, mock_client
    ):
        """Test that extraction agent is created with string output type."""
        mock_config.return_value.last_n_messages = 10

        mock_result = MagicMock()
        mock_result.output = CityIntentResult(
            province=["北京"],
            city=[],
            area=[],
        ).model_dump_json()
        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)
        mock_agent_cls.return_value = mock_agent_instance

        mock_client.return_value.model = MagicMock()

        ctx = self._make_run_context(
            chat_history=[
                {"role": "assistant", "content": "欢迎"},
                {"role": "user", "content": "我想去北京上学"},
            ],
        )

        await extract_city_intent(ctx)

        # Verify Agent was created with correct output_type
        mock_agent_cls.assert_called_once()
        call_kwargs = mock_agent_cls.call_args[1]
        assert call_kwargs["output_type"] is str

    @patch("app.tools.city_intent_tool._get_extraction_client")
    @patch("app.tools.city_intent_tool._get_extract_config")
    @patch("app.tools.city_intent_tool.Agent")
    async def test_result_is_valid_json(
        self, mock_agent_cls, mock_config, mock_client
    ):
        """Test that the result is valid JSON with expected fields."""
        mock_config.return_value.last_n_messages = 10

        mock_result = MagicMock()
        mock_result.output = CityIntentResult(
            province=["江苏", "浙江"],
            city=["南京", "杭州"],
            area=[],
        ).model_dump_json()
        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)
        mock_agent_cls.return_value = mock_agent_instance
        mock_client.return_value.model = MagicMock()

        ctx = self._make_run_context(
            chat_history=[
                {"role": "assistant", "content": "欢迎"},
                {"role": "user", "content": "我想去江浙沪"},
            ],
        )

        result = await extract_city_intent(ctx)

        parsed = json.loads(result)
        assert "province" in parsed
        assert "city" in parsed
        assert "area" in parsed
        assert parsed["province"] == ["江苏", "浙江"]
        assert parsed["city"] == ["南京", "杭州"]

    @patch("app.tools.city_intent_tool._get_extraction_client")
    @patch("app.tools.city_intent_tool._get_extract_config")
    @patch("app.tools.city_intent_tool.Agent")
    async def test_agent_called_with_temperature_zero(
        self, mock_agent_cls, mock_config, mock_client
    ):
        """Test that the extraction agent is called with temperature=0."""
        mock_config.return_value.last_n_messages = 10

        mock_result = MagicMock()
        mock_result.output = CityIntentResult().model_dump_json()
        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)
        mock_agent_cls.return_value = mock_agent_instance
        mock_client.return_value.model = MagicMock()

        ctx = self._make_run_context(
            chat_history=[
                {"role": "assistant", "content": "欢迎"},
                {"role": "user", "content": "测试"},
            ],
        )

        await extract_city_intent(ctx)

        # Verify agent.run was called with temperature=0
        mock_agent_instance.run.assert_called_once()
        call_kwargs = mock_agent_instance.run.call_args[1]
        assert call_kwargs["model_settings"]["temperature"] == 0

    @patch("app.tools.city_intent_tool._get_extraction_client")
    @patch("app.tools.city_intent_tool._get_extract_config")
    @patch("app.tools.city_intent_tool.Agent")
    async def test_student_info_passed_to_prompt(
        self, mock_agent_cls, mock_config, mock_client
    ):
        """Test that student info is included in the extraction prompt."""
        mock_config.return_value.last_n_messages = 10

        mock_result = MagicMock()
        mock_result.output = CityIntentResult().model_dump_json()
        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)
        mock_agent_cls.return_value = mock_agent_instance
        mock_client.return_value.model = MagicMock()

        ctx = self._make_run_context(
            chat_history=[
                {"role": "assistant", "content": "欢迎"},
                {"role": "user", "content": "测试"},
            ],
            score_detail={"sex": {"name": "女"}, "province": {"name": "浙江"}},
        )

        await extract_city_intent(ctx)

        # Verify the instructions contain student info
        call_kwargs = mock_agent_cls.call_args[1]
        assert "女" in call_kwargs["instructions"]
        assert "浙江" in call_kwargs["instructions"]

    @patch("app.tools.city_intent_tool._get_extraction_client")
    @patch("app.tools.city_intent_tool._get_extract_config")
    @patch("app.tools.city_intent_tool.Agent")
    async def test_uses_positive_system_message(
        self, mock_agent_cls, mock_config, mock_client
    ):
        """Test that positive extraction uses positive system message."""
        mock_config.return_value.last_n_messages = 10

        mock_result = MagicMock()
        mock_result.output = CityIntentResult().model_dump_json()
        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)
        mock_agent_cls.return_value = mock_agent_instance
        mock_client.return_value.model = MagicMock()

        ctx = self._make_run_context(
            chat_history=[
                {"role": "user", "content": "我想去北京上学"},
            ],
        )

        await extract_city_intent(ctx)

        call_kwargs = mock_agent_cls.call_args[1]
        instructions = call_kwargs["instructions"]
        # Positive prompt should mention positive intent
        assert "正面" in instructions
        # Should contain area in return format
        assert "area" in instructions

    @patch("app.tools.city_intent_tool._get_extraction_client")
    @patch("app.tools.city_intent_tool._get_extract_config")
    @patch("app.tools.city_intent_tool.Agent")
    async def test_exception_is_raised_on_llm_failure(
        self, mock_agent_cls, mock_config, mock_client
    ):
        """Test that exceptions from LLM are re-raised."""
        mock_config.return_value.last_n_messages = 10

        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(side_effect=RuntimeError("LLM error"))
        mock_agent_cls.return_value = mock_agent_instance
        mock_client.return_value.model = MagicMock()

        ctx = self._make_run_context(
            chat_history=[
                {"role": "user", "content": "测试"},
            ],
        )

        with pytest.raises(RuntimeError, match="LLM error"):
            await extract_city_intent(ctx)

    @patch("app.tools.city_intent_tool._get_extraction_client")
    @patch("app.tools.city_intent_tool._get_extract_config")
    @patch("app.tools.city_intent_tool.Agent")
    async def test_chat_history_trimmed(
        self, mock_agent_cls, mock_config, mock_client
    ):
        """Test that chat history is trimmed to last N messages."""
        mock_config.return_value.last_n_messages = 2  # Trim to 2 messages

        mock_result = MagicMock()
        mock_result.output = CityIntentResult().model_dump_json()
        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)
        mock_agent_cls.return_value = mock_agent_instance
        mock_client.return_value.model = MagicMock()

        ctx = self._make_run_context(
            chat_history=[
                {"role": "user", "content": "第一条消息"},
                {"role": "assistant", "content": "回复1"},
                {"role": "user", "content": "第二条消息"},
                {"role": "assistant", "content": "回复2"},
                {"role": "user", "content": "我想去北京"},
            ],
        )

        await extract_city_intent(ctx)

        # The instructions should contain the last messages, not the first ones
        call_kwargs = mock_agent_cls.call_args[1]
        instructions = call_kwargs["instructions"]
        # Last message should be in the prompt
        assert "我想去北京" in instructions
        # First message should be trimmed away
        assert "第一条消息" not in instructions

    @patch("app.tools.city_intent_tool._get_extraction_client")
    @patch("app.tools.city_intent_tool._get_extract_config")
    @patch("app.tools.city_intent_tool.Agent")
    async def test_no_score_detail_uses_default_student_info(
        self, mock_agent_cls, mock_config, mock_client
    ):
        """Test that no score_detail uses default student info."""
        mock_config.return_value.last_n_messages = 10

        mock_result = MagicMock()
        mock_result.output = CityIntentResult().model_dump_json()
        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)
        mock_agent_cls.return_value = mock_agent_instance
        mock_client.return_value.model = MagicMock()

        ctx = self._make_run_context(
            chat_history=[
                {"role": "user", "content": "测试"},
            ],
            score_detail=None,
        )

        await extract_city_intent(ctx)

        call_kwargs = mock_agent_cls.call_args[1]
        assert "暂无学生信息" in call_kwargs["instructions"]


# ---- extract_negative_city_intent ----


class TestExtractNegativeCityIntent:
    """Tests for extract_negative_city_intent async function."""

    def _make_run_context(self, **kwargs) -> MagicMock:
        """Helper to create a mock RunContext with RequestContext deps."""
        defaults = {
            "userid": "test_user",
            "sessionid": "test_session",
            "chat_history": None,
            "batch": None,
            "score_detail": None,
        }
        defaults.update(kwargs)
        ctx = MagicMock(spec=RunContext)
        ctx.deps = RequestContext(**defaults)
        return ctx

    async def test_returns_empty_when_no_chat_history(self):
        """Test that empty result is returned when chat_history is None."""
        ctx = self._make_run_context(chat_history=None)

        result = await extract_negative_city_intent(ctx)

        parsed = json.loads(result)
        assert parsed["province"] == []
        assert parsed["city"] == []
        assert "area" not in parsed

    async def test_returns_empty_when_chat_history_is_empty_list(self):
        """Test that empty result is returned when chat_history is empty."""
        ctx = self._make_run_context(chat_history=[])

        result = await extract_negative_city_intent(ctx)

        parsed = json.loads(result)
        assert parsed["province"] == []
        assert parsed["city"] == []
        assert "area" not in parsed

    async def test_empty_result_is_valid_json(self):
        """Test that empty result is valid JSON."""
        ctx = self._make_run_context(chat_history=None)

        result = await extract_negative_city_intent(ctx)

        parsed = json.loads(result)
        assert isinstance(parsed, dict)
        assert "province" in parsed
        assert "city" in parsed

    @patch("app.tools.city_intent_tool._get_extraction_client")
    @patch("app.tools.city_intent_tool._get_extract_config")
    @patch("app.tools.city_intent_tool.Agent")
    async def test_calls_agent_with_correct_output_type(
        self, mock_agent_cls, mock_config, mock_client
    ):
        """Test that extraction agent is created with string output type."""
        mock_config.return_value.last_n_messages = 10

        mock_result = MagicMock()
        mock_result.output = NegativeCityIntentResult(
            province=["新疆", "西藏"],
            city=[],
        ).model_dump_json()
        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)
        mock_agent_cls.return_value = mock_agent_instance

        mock_client.return_value.model = MagicMock()

        ctx = self._make_run_context(
            chat_history=[
                {"role": "assistant", "content": "欢迎"},
                {"role": "user", "content": "我不想去偏远地区"},
            ],
        )

        await extract_negative_city_intent(ctx)

        # Verify Agent was created with correct output_type
        mock_agent_cls.assert_called_once()
        call_kwargs = mock_agent_cls.call_args[1]
        assert call_kwargs["output_type"] is str

    @patch("app.tools.city_intent_tool._get_extraction_client")
    @patch("app.tools.city_intent_tool._get_extract_config")
    @patch("app.tools.city_intent_tool.Agent")
    async def test_result_is_valid_json(
        self, mock_agent_cls, mock_config, mock_client
    ):
        """Test that the result is valid JSON with expected fields."""
        mock_config.return_value.last_n_messages = 10

        mock_result = MagicMock()
        mock_result.output = NegativeCityIntentResult(
            province=["黑龙江", "吉林", "辽宁"],
            city=[],
        ).model_dump_json()
        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)
        mock_agent_cls.return_value = mock_agent_instance
        mock_client.return_value.model = MagicMock()

        ctx = self._make_run_context(
            chat_history=[
                {"role": "user", "content": "我不想去东北"},
            ],
        )

        result = await extract_negative_city_intent(ctx)

        parsed = json.loads(result)
        assert "province" in parsed
        assert "city" in parsed
        assert "area" not in parsed
        assert parsed["province"] == ["黑龙江", "吉林", "辽宁"]

    @patch("app.tools.city_intent_tool._get_extraction_client")
    @patch("app.tools.city_intent_tool._get_extract_config")
    @patch("app.tools.city_intent_tool.Agent")
    async def test_agent_called_with_temperature_zero(
        self, mock_agent_cls, mock_config, mock_client
    ):
        """Test that the extraction agent is called with temperature=0."""
        mock_config.return_value.last_n_messages = 10

        mock_result = MagicMock()
        mock_result.output = NegativeCityIntentResult().model_dump_json()
        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)
        mock_agent_cls.return_value = mock_agent_instance
        mock_client.return_value.model = MagicMock()

        ctx = self._make_run_context(
            chat_history=[
                {"role": "user", "content": "测试"},
            ],
        )

        await extract_negative_city_intent(ctx)

        mock_agent_instance.run.assert_called_once()
        call_kwargs = mock_agent_instance.run.call_args[1]
        assert call_kwargs["model_settings"]["temperature"] == 0

    @patch("app.tools.city_intent_tool._get_extraction_client")
    @patch("app.tools.city_intent_tool._get_extract_config")
    @patch("app.tools.city_intent_tool.Agent")
    async def test_uses_negative_system_message(
        self, mock_agent_cls, mock_config, mock_client
    ):
        """Test that negative extraction uses negative system message."""
        mock_config.return_value.last_n_messages = 10

        mock_result = MagicMock()
        mock_result.output = NegativeCityIntentResult().model_dump_json()
        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)
        mock_agent_cls.return_value = mock_agent_instance
        mock_client.return_value.model = MagicMock()

        ctx = self._make_run_context(
            chat_history=[
                {"role": "user", "content": "我不喜欢东北"},
            ],
        )

        await extract_negative_city_intent(ctx)

        call_kwargs = mock_agent_cls.call_args[1]
        instructions = call_kwargs["instructions"]
        # Negative prompt should mention negative intent
        assert "负面" in instructions
        # Should NOT contain area in the return format section
        format_section = instructions.split("返回格式")[1] if "返回格式" in instructions else ""
        assert "area" not in format_section

    @patch("app.tools.city_intent_tool._get_extraction_client")
    @patch("app.tools.city_intent_tool._get_extract_config")
    @patch("app.tools.city_intent_tool.Agent")
    async def test_student_info_passed_to_prompt(
        self, mock_agent_cls, mock_config, mock_client
    ):
        """Test that student info is included in the negative extraction prompt."""
        mock_config.return_value.last_n_messages = 10

        mock_result = MagicMock()
        mock_result.output = NegativeCityIntentResult().model_dump_json()
        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)
        mock_agent_cls.return_value = mock_agent_instance
        mock_client.return_value.model = MagicMock()

        ctx = self._make_run_context(
            chat_history=[
                {"role": "user", "content": "测试"},
            ],
            score_detail={"sex": {"name": "男"}, "province": {"name": "山东"}},
        )

        await extract_negative_city_intent(ctx)

        call_kwargs = mock_agent_cls.call_args[1]
        assert "男" in call_kwargs["instructions"]
        assert "山东" in call_kwargs["instructions"]

    @patch("app.tools.city_intent_tool._get_extraction_client")
    @patch("app.tools.city_intent_tool._get_extract_config")
    @patch("app.tools.city_intent_tool.Agent")
    async def test_exception_is_raised_on_llm_failure(
        self, mock_agent_cls, mock_config, mock_client
    ):
        """Test that exceptions from LLM are re-raised."""
        mock_config.return_value.last_n_messages = 10

        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(side_effect=RuntimeError("LLM error"))
        mock_agent_cls.return_value = mock_agent_instance
        mock_client.return_value.model = MagicMock()

        ctx = self._make_run_context(
            chat_history=[
                {"role": "user", "content": "测试"},
            ],
        )

        with pytest.raises(RuntimeError, match="LLM error"):
            await extract_negative_city_intent(ctx)

    @patch("app.tools.city_intent_tool._get_extraction_client")
    @patch("app.tools.city_intent_tool._get_extract_config")
    @patch("app.tools.city_intent_tool.Agent")
    async def test_chat_history_trimmed(
        self, mock_agent_cls, mock_config, mock_client
    ):
        """Test that chat history is trimmed to last N messages."""
        mock_config.return_value.last_n_messages = 2

        mock_result = MagicMock()
        mock_result.output = NegativeCityIntentResult().model_dump_json()
        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)
        mock_agent_cls.return_value = mock_agent_instance
        mock_client.return_value.model = MagicMock()

        ctx = self._make_run_context(
            chat_history=[
                {"role": "user", "content": "第一条消息"},
                {"role": "assistant", "content": "回复1"},
                {"role": "user", "content": "第二条消息"},
                {"role": "assistant", "content": "回复2"},
                {"role": "user", "content": "不想去东北"},
            ],
        )

        await extract_negative_city_intent(ctx)

        call_kwargs = mock_agent_cls.call_args[1]
        instructions = call_kwargs["instructions"]
        assert "不想去东北" in instructions
        assert "第一条消息" not in instructions


class TestExtractCityIntentsWithPolarity:
    """Tests for combined positive/negative city intent extraction."""

    def _make_run_context(self, **kwargs) -> MagicMock:
        defaults = {
            "userid": "test_user",
            "sessionid": "test_session",
            "chat_history": None,
            "batch": None,
            "score_detail": None,
        }
        defaults.update(kwargs)
        ctx = MagicMock(spec=RunContext)
        ctx.deps = RequestContext(**defaults)
        return ctx

    async def test_returns_empty_when_chat_history_is_empty(self):
        ctx = self._make_run_context(chat_history=[])

        result = await extract_city_intents_with_polarity(ctx)

        parsed = json.loads(result)
        assert parsed["positive"]["province"] == []
        assert parsed["negative"]["province"] == []

    @patch("app.tools.city_intent_tool._get_extraction_client")
    @patch("app.tools.city_intent_tool._get_extract_config")
    @patch("app.tools.city_intent_tool.Agent")
    async def test_extracts_positive_and_negative_in_one_call(
        self, mock_agent_cls, mock_config, mock_client
    ):
        mock_config.return_value.last_n_messages = 10
        mock_result = MagicMock()
        mock_result.output = CityIntentPolarityResult(
            positive=CityIntentResult(province=["北京"], city=[], area=[]),
            negative=NegativeCityIntentResult(province=["上海"], city=[]),
        ).model_dump_json()
        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)
        mock_agent_cls.return_value = mock_agent_instance
        mock_client.return_value.model = MagicMock()

        ctx = self._make_run_context(
            chat_history=[{"role": "user", "content": "北京可以，上海别去了"}],
            score_detail={"sex": {"name": "女"}, "province": {"name": "河北"}},
        )

        result = await extract_city_intents_with_polarity(ctx)

        parsed = json.loads(result)
        assert parsed["positive"]["province"] == ["北京"]
        assert parsed["negative"]["province"] == ["上海"]
        mock_agent_cls.assert_called_once()
        mock_agent_instance.run.assert_awaited_once()
        assert mock_agent_instance.run.await_args.kwargs["model_settings"]["temperature"] == 0


# ---- ChatAgent integration ----


class TestChatAgentCityIntentRegistration:
    """Tests for city intent tools registration in ChatAgent."""

    def test_extract_city_intent_importable(self):
        """Test that extract_city_intent is importable."""
        from app.tools.city_intent_tool import extract_city_intent

        assert callable(extract_city_intent)

    def test_extract_negative_city_intent_importable(self):
        """Test that extract_negative_city_intent is importable."""
        from app.tools.city_intent_tool import extract_negative_city_intent

        assert callable(extract_negative_city_intent)
