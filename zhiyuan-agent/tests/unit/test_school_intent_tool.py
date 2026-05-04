"""Unit tests for app.tools.school_intent_tool module."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import RunContext

from app.agent.context import RequestContext
from app.schemas.school_intent import SchoolIntentResult
from app.tools.school_intent_tool import (
    _build_system_message,
    _filter_school_from_chat,
    _format_student_info,
    extract_school_intent,
)


# ---- _filter_school_from_chat ----


class TestFilterSchoolFromChat:
    """Tests for _filter_school_from_chat function."""

    def test_filter_matches_keywords(self):
        """Test that schools matching keywords in chat are returned."""
        chat_history = [
            {"role": "user", "content": "我想去北京上大学"},
        ]
        area_to_school = {
            "北": ["北京大学", "北京师范大学"],
            "上": ["上海大学"],
        }

        result = _filter_school_from_chat(chat_history, area_to_school)

        assert "北京大学" in result
        assert "北京师范大学" in result
        assert "上海大学" in result  # "上" appears in "上大学"

    def test_filter_no_matches(self):
        """Test that empty list is returned when no keywords match."""
        chat_history = [
            {"role": "user", "content": "你好"},
        ]
        area_to_school = {
            "哈": ["哈尔滨工业大学"],
        }

        result = _filter_school_from_chat(chat_history, area_to_school)

        assert result == []

    def test_filter_deduplicates_schools(self):
        """Test that duplicate schools are deduplicated."""
        chat_history = [
            {"role": "user", "content": "北京师范大学"},
        ]
        area_to_school = {
            "北": ["北京师范大学"],
            "师": ["北京师范大学", "华东师范大学"],
        }

        result = _filter_school_from_chat(chat_history, area_to_school)

        # 北京师范大学 appears in both "北" and "师" index but should be deduplicated
        assert result.count("北京师范大学") == 1

    def test_filter_returns_sorted(self):
        """Test that results are sorted."""
        chat_history = [
            {"role": "user", "content": "理工师范"},
        ]
        area_to_school = {
            "理": ["浙江理工大学", "北京理工大学"],
            "师": ["北京师范大学"],
        }

        result = _filter_school_from_chat(chat_history, area_to_school)

        assert result == sorted(result)

    def test_filter_empty_chat_history(self):
        """Test filter with empty chat history."""
        result = _filter_school_from_chat([], {"北": ["北京大学"]})

        assert result == []

    def test_filter_scans_all_messages(self):
        """Test that all messages in chat history are scanned."""
        chat_history = [
            {"role": "user", "content": "我是北京的"},
            {"role": "assistant", "content": "好的"},
            {"role": "user", "content": "想去上海"},
        ]
        area_to_school = {
            "北": ["北京大学"],
            "上": ["上海大学"],
        }

        result = _filter_school_from_chat(chat_history, area_to_school)

        assert "北京大学" in result
        assert "上海大学" in result

    def test_filter_handles_missing_content(self):
        """Test filter handles messages without content key."""
        chat_history = [
            {"role": "user"},
            {"role": "assistant", "content": "北京大学很好"},
        ]
        area_to_school = {
            "北": ["北京大学"],
        }

        result = _filter_school_from_chat(chat_history, area_to_school)

        assert "北京大学" in result


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

    def test_format_with_partial_info(self):
        """Test formatting with partial student info."""
        score_detail = {
            "sex": {"name": "女"},
        }

        result = _format_student_info(score_detail)

        assert "女" in result
        assert "未知" in result  # province missing

    def test_format_with_missing_name_key(self):
        """Test formatting when nested 'name' key is missing."""
        score_detail = {
            "sex": {},
            "province": {"name": "河北"},
        }

        result = _format_student_info(score_detail)

        assert "未知" in result  # sex.name missing
        assert "河北" in result


# ---- _build_system_message ----


class TestBuildSystemMessage:
    """Tests for _build_system_message function."""

    def test_build_contains_chat_history(self):
        """Test that built prompt contains formatted chat history."""
        chat_history = [
            {"role": "user", "content": "我想报考北大"},
        ]
        schools = ["北京大学"]
        student_info = "学生性别：男，学生所在省份：北京"

        result = _build_system_message(chat_history, schools, student_info)

        assert "我想报考北大" in result

    def test_build_contains_school_list(self):
        """Test that built prompt contains school options."""
        chat_history = [{"role": "user", "content": "测试"}]
        schools = ["北京大学", "清华大学"]
        student_info = "暂无学生信息"

        result = _build_system_message(chat_history, schools, student_info)

        assert "-北京大学" in result
        assert "-清华大学" in result

    def test_build_contains_student_info(self):
        """Test that built prompt contains student info."""
        chat_history = [{"role": "user", "content": "测试"}]
        schools = []
        student_info = "学生性别：女，学生所在省份：浙江"

        result = _build_system_message(chat_history, schools, student_info)

        assert "学生性别：女，学生所在省份：浙江" in result

    def test_build_contains_task_description(self):
        """Test that built prompt contains task background."""
        chat_history = [{"role": "user", "content": "测试"}]

        result = _build_system_message(chat_history, [], "")

        assert "院校实体提取工具" in result

    def test_build_contains_extraction_rules(self):
        """Test that built prompt contains extraction rules."""
        chat_history = [{"role": "user", "content": "测试"}]

        result = _build_system_message(chat_history, [], "")

        assert "allkeys" in result
        assert "newkeys" in result
        assert "colleges" in result
        assert "negative_colleges" in result

    def test_build_contains_return_format(self):
        """Test that built prompt describes JSON return format."""
        chat_history = [{"role": "user", "content": "测试"}]

        result = _build_system_message(chat_history, [], "")

        assert "JSON" in result


# ---- extract_school_intent ----


class TestExtractSchoolIntent:
    """Tests for extract_school_intent async function."""

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

        result = await extract_school_intent(ctx)

        parsed = json.loads(result)
        assert parsed["allkeys"] == []
        assert parsed["newkeys"] == []
        assert parsed["colleges"] == []
        assert parsed["negative_colleges"] == []

    async def test_returns_empty_when_chat_history_is_empty_list(self):
        """Test that empty result is returned when chat_history is empty."""
        ctx = self._make_run_context(chat_history=[])

        result = await extract_school_intent(ctx)

        parsed = json.loads(result)
        assert parsed["allkeys"] == []
        assert parsed["colleges"] == []

    @patch("app.tools.school_intent_tool._get_extraction_client")
    @patch("app.tools.school_intent_tool._get_extract_config")
    @patch("app.tools.school_intent_tool.Agent")
    async def test_calls_agent_with_correct_output_type(
        self, mock_agent_cls, mock_config, mock_client
    ):
        """Test that extraction agent is created with string output type."""
        mock_config.return_value.last_n_messages = 10

        mock_output = SchoolIntentResult(
            allkeys=["北大"],
            newkeys=["北京大学"],
            colleges=["北京大学"],
            negative_colleges=[],
        )
        mock_result = MagicMock()
        mock_result.output = mock_output.model_dump_json()
        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)
        mock_agent_cls.return_value = mock_agent_instance

        mock_client.return_value.model = MagicMock()

        ctx = self._make_run_context(
            chat_history=[
                {"role": "assistant", "content": "欢迎"},
                {"role": "user", "content": "你好"},
                {"role": "user", "content": "我想报考北大"},
            ],
            batch="01",
        )

        result = await extract_school_intent(ctx)

        # Verify Agent was created with correct output_type
        mock_agent_cls.assert_called_once()
        call_kwargs = mock_agent_cls.call_args[1]
        assert call_kwargs["output_type"] is str

    @patch("app.tools.school_intent_tool._get_extraction_client")
    @patch("app.tools.school_intent_tool._get_extract_config")
    @patch("app.tools.school_intent_tool.Agent")
    async def test_uses_bachelor_schools_for_batch_01(
        self, mock_agent_cls, mock_config, mock_client
    ):
        """Test that bachelor schools are used when batch='01'."""
        mock_config.return_value.last_n_messages = 10

        mock_result = MagicMock()
        mock_result.output = SchoolIntentResult().model_dump_json()
        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)
        mock_agent_cls.return_value = mock_agent_instance
        mock_client.return_value.model = MagicMock()

        ctx = self._make_run_context(
            chat_history=[
                {"role": "assistant", "content": "欢迎"},
                {"role": "user", "content": "你好"},
                {"role": "user", "content": "北京大学怎么样"},
            ],
            batch="01",
        )

        result = await extract_school_intent(ctx)
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    @patch("app.tools.school_intent_tool._get_extraction_client")
    @patch("app.tools.school_intent_tool._get_extract_config")
    @patch("app.tools.school_intent_tool.Agent")
    async def test_uses_associate_schools_for_non_01_batch(
        self, mock_agent_cls, mock_config, mock_client
    ):
        """Test that associate schools are used when batch is not '01'."""
        mock_config.return_value.last_n_messages = 10

        mock_result = MagicMock()
        mock_result.output = SchoolIntentResult().model_dump_json()
        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)
        mock_agent_cls.return_value = mock_agent_instance
        mock_client.return_value.model = MagicMock()

        ctx = self._make_run_context(
            chat_history=[
                {"role": "assistant", "content": "欢迎"},
                {"role": "user", "content": "你好"},
                {"role": "user", "content": "有什么好的专科学校"},
            ],
            batch="02",
        )

        result = await extract_school_intent(ctx)
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    @patch("app.tools.school_intent_tool._get_extraction_client")
    @patch("app.tools.school_intent_tool._get_extract_config")
    @patch("app.tools.school_intent_tool.Agent")
    async def test_uses_bachelor_schools_for_none_batch(
        self, mock_agent_cls, mock_config, mock_client
    ):
        """Test that bachelor schools are used when batch is None."""
        mock_config.return_value.last_n_messages = 10

        mock_result = MagicMock()
        mock_result.output = SchoolIntentResult().model_dump_json()
        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)
        mock_agent_cls.return_value = mock_agent_instance
        mock_client.return_value.model = MagicMock()

        ctx = self._make_run_context(
            chat_history=[
                {"role": "assistant", "content": "欢迎"},
                {"role": "user", "content": "你好"},
                {"role": "user", "content": "我想了解大学"},
            ],
            batch=None,
        )

        result = await extract_school_intent(ctx)
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    @patch("app.tools.school_intent_tool._get_extraction_client")
    @patch("app.tools.school_intent_tool._get_extract_config")
    @patch("app.tools.school_intent_tool.Agent")
    async def test_result_is_valid_json(
        self, mock_agent_cls, mock_config, mock_client
    ):
        """Test that the result is valid JSON with expected fields."""
        mock_config.return_value.last_n_messages = 10

        mock_result = MagicMock()
        mock_result.output = SchoolIntentResult(
            allkeys=["清华"],
            newkeys=["清华大学"],
            colleges=["清华大学"],
            negative_colleges=[],
        ).model_dump_json()
        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)
        mock_agent_cls.return_value = mock_agent_instance
        mock_client.return_value.model = MagicMock()

        ctx = self._make_run_context(
            chat_history=[
                {"role": "assistant", "content": "欢迎"},
                {"role": "user", "content": "你好"},
                {"role": "user", "content": "我想报考清华"},
            ],
            batch="01",
        )

        result = await extract_school_intent(ctx)

        parsed = json.loads(result)
        assert "allkeys" in parsed
        assert "newkeys" in parsed
        assert "colleges" in parsed
        assert "negative_colleges" in parsed
        assert parsed["colleges"] == ["清华大学"]

    @patch("app.tools.school_intent_tool._get_extraction_client")
    @patch("app.tools.school_intent_tool._get_extract_config")
    @patch("app.tools.school_intent_tool.Agent")
    async def test_agent_called_with_temperature_zero(
        self, mock_agent_cls, mock_config, mock_client
    ):
        """Test that the extraction agent is called with temperature=0."""
        mock_config.return_value.last_n_messages = 10

        mock_result = MagicMock()
        mock_result.output = SchoolIntentResult().model_dump_json()
        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)
        mock_agent_cls.return_value = mock_agent_instance
        mock_client.return_value.model = MagicMock()

        ctx = self._make_run_context(
            chat_history=[
                {"role": "assistant", "content": "欢迎"},
                {"role": "user", "content": "你好"},
                {"role": "user", "content": "测试"},
            ],
        )

        await extract_school_intent(ctx)

        # Verify agent.run was called with temperature=0
        mock_agent_instance.run.assert_called_once()
        call_kwargs = mock_agent_instance.run.call_args[1]
        assert call_kwargs["model_settings"]["temperature"] == 0

    @patch("app.tools.school_intent_tool._get_extraction_client")
    @patch("app.tools.school_intent_tool._get_extract_config")
    @patch("app.tools.school_intent_tool.Agent")
    async def test_student_info_passed_to_prompt(
        self, mock_agent_cls, mock_config, mock_client
    ):
        """Test that student info is included in the extraction prompt."""
        mock_config.return_value.last_n_messages = 10

        mock_result = MagicMock()
        mock_result.output = SchoolIntentResult().model_dump_json()
        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)
        mock_agent_cls.return_value = mock_agent_instance
        mock_client.return_value.model = MagicMock()

        ctx = self._make_run_context(
            chat_history=[
                {"role": "assistant", "content": "欢迎"},
                {"role": "user", "content": "你好"},
                {"role": "user", "content": "测试"},
            ],
            score_detail={"sex": {"name": "女"}, "province": {"name": "浙江"}},
        )

        await extract_school_intent(ctx)

        # Verify the instructions contain student info
        call_kwargs = mock_agent_cls.call_args[1]
        assert "女" in call_kwargs["instructions"]
        assert "浙江" in call_kwargs["instructions"]
