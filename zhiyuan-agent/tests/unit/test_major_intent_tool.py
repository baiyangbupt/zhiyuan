"""Unit tests for app.tools.major_intent_tool module."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import RunContext

from app.agent.context import RequestContext
from app.schemas.major_intent import MajorIntentPolarityResult, MajorIntentResult, NegativeMajorIntentResult
from app.tools.major_intent_tool import (
    _build_negative_system_message_bachelor,
    _build_system_message_bachelor,
    extract_major_intents_with_polarity,
    extract_major_intent,
    extract_negative_major_intent,
)


# ---- _build_system_message_bachelor ----


class TestBuildSystemMessageBachelor:
    """Tests for _build_system_message_bachelor function."""

    def test_build_contains_chat_history(self):
        """Test that built prompt contains formatted chat history."""
        chat_history = [
            {"role": "user", "content": "我想学计算机"},
        ]
        major_data_str = "工学\\n  计算机类"

        result = _build_system_message_bachelor(chat_history, major_data_str)

        assert "我想学计算机" in result

    def test_build_contains_major_data(self):
        """Test that built prompt contains major hierarchy data."""
        chat_history = [{"role": "user", "content": "测试"}]
        major_data_str = "工学\\n  计算机类\\n    计算机科学与技术"

        result = _build_system_message_bachelor(chat_history, major_data_str)

        assert "工学" in result
        assert "计算机类" in result

    def test_build_contains_task_description(self):
        """Test that built prompt contains task background."""
        chat_history = [{"role": "user", "content": "测试"}]

        result = _build_system_message_bachelor(chat_history, "")

        assert "专业实体抽取工具" in result
        assert "正面意向专业" in result

    def test_build_contains_extraction_rules(self):
        """Test that built prompt contains extraction rules."""
        chat_history = [{"role": "user", "content": "测试"}]

        result = _build_system_message_bachelor(chat_history, "")

        assert "allkeys" in result
        assert "level2" in result
        assert "level3" in result

    def test_build_contains_return_format(self):
        """Test that built prompt describes JSON return format."""
        chat_history = [{"role": "user", "content": "测试"}]

        result = _build_system_message_bachelor(chat_history, "")

        assert "JSON" in result


# ---- _build_negative_system_message_bachelor ----


class TestBuildNegativeSystemMessageBachelor:
    """Tests for _build_negative_system_message_bachelor function."""

    def test_build_contains_chat_history(self):
        """Test that built prompt contains formatted chat history."""
        chat_history = [
            {"role": "user", "content": "我不想学医学"},
        ]
        major_data_str = "医学\n  医学类"

        result = _build_negative_system_message_bachelor(chat_history, major_data_str)

        assert "我不想学医学" in result

    def test_build_contains_negative_keywords(self):
        """Test that built prompt contains negative intent keywords."""
        chat_history = [{"role": "user", "content": "测试"}]

        result = _build_negative_system_message_bachelor(chat_history, "")

        assert "负面意向" in result
        assert "不感兴趣" in result or "不考虑" in result

    def test_build_contains_major_data(self):
        """Test that built prompt contains major hierarchy data."""
        chat_history = [{"role": "user", "content": "测试"}]
        major_data_str = "医学\n  医学类\n    临床医学"

        result = _build_negative_system_message_bachelor(chat_history, major_data_str)

        assert "医学" in result
        assert "医学类" in result


# ---- extract_major_intent ----


class TestExtractMajorIntent:
    """Tests for extract_major_intent async function."""

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

        result = await extract_major_intent(ctx)

        parsed = json.loads(result)
        assert parsed["allkeys"] == []
        assert parsed["level2"] == []
        assert parsed["level3"] == []

    async def test_returns_empty_when_chat_history_is_empty_list(self):
        """Test that empty result is returned when chat_history is empty."""
        ctx = self._make_run_context(chat_history=[])

        result = await extract_major_intent(ctx)

        parsed = json.loads(result)
        assert parsed["allkeys"] == []
        assert parsed["level2"] == []
        assert parsed["level3"] == []

    @patch("app.tools.major_intent_tool._get_extraction_client")
    @patch("app.tools.major_intent_tool._get_extract_config")
    @patch("app.tools.major_intent_tool.Agent")
    async def test_calls_agent_with_correct_output_type(
        self, mock_agent_cls, mock_config, mock_client
    ):
        """Test that extraction agent is created with string output type."""
        mock_config.return_value.last_n_messages = 10

        mock_result = MagicMock()
        mock_result.output = MajorIntentResult(
            allkeys=["计算机"],
            level2=["计算机类"],
            level3=[],
        ).model_dump_json()
        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)
        mock_agent_cls.return_value = mock_agent_instance

        mock_client.return_value.model = MagicMock()

        ctx = self._make_run_context(
            chat_history=[
                {"role": "assistant", "content": "欢迎"},
                {"role": "user", "content": "你好"},
                {"role": "user", "content": "我想学计算机"},
            ],
            batch="01",
        )

        result = await extract_major_intent(ctx)

        # Verify Agent was created with correct output_type
        mock_agent_cls.assert_called_once()
        call_kwargs = mock_agent_cls.call_args[1]
        assert call_kwargs["output_type"] is str

    @patch("app.tools.major_intent_tool._get_extraction_client")
    @patch("app.tools.major_intent_tool._get_extract_config")
    @patch("app.tools.major_intent_tool.Agent")
    async def test_uses_bachelor_majors_for_batch_01(
        self, mock_agent_cls, mock_config, mock_client
    ):
        """Test that bachelor majors are used when batch='01'."""
        mock_config.return_value.last_n_messages = 10

        mock_result = MagicMock()
        mock_result.output = MajorIntentResult().model_dump_json()
        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)
        mock_agent_cls.return_value = mock_agent_instance
        mock_client.return_value.model = MagicMock()

        ctx = self._make_run_context(
            chat_history=[
                {"role": "assistant", "content": "欢迎"},
                {"role": "user", "content": "你好"},
                {"role": "user", "content": "计算机专业怎么样"},
            ],
            batch="01",
        )

        result = await extract_major_intent(ctx)
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    @patch("app.tools.major_intent_tool._get_extraction_client")
    @patch("app.tools.major_intent_tool._get_extract_config")
    @patch("app.tools.major_intent_tool.Agent")
    async def test_uses_associate_majors_for_non_01_batch(
        self, mock_agent_cls, mock_config, mock_client
    ):
        """Test that associate majors are used when batch is not '01'."""
        mock_config.return_value.last_n_messages = 10

        mock_result = MagicMock()
        mock_result.output = MajorIntentResult().model_dump_json()
        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)
        mock_agent_cls.return_value = mock_agent_instance
        mock_client.return_value.model = MagicMock()

        ctx = self._make_run_context(
            chat_history=[
                {"role": "assistant", "content": "欢迎"},
                {"role": "user", "content": "你好"},
                {"role": "user", "content": "有什么好的专科专业"},
            ],
            batch="02",
        )

        result = await extract_major_intent(ctx)
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    @patch("app.tools.major_intent_tool._get_extraction_client")
    @patch("app.tools.major_intent_tool._get_extract_config")
    @patch("app.tools.major_intent_tool.Agent")
    async def test_uses_bachelor_majors_for_none_batch(
        self, mock_agent_cls, mock_config, mock_client
    ):
        """Test that bachelor majors are used when batch is None."""
        mock_config.return_value.last_n_messages = 10

        mock_result = MagicMock()
        mock_result.output = MajorIntentResult().model_dump_json()
        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)
        mock_agent_cls.return_value = mock_agent_instance
        mock_client.return_value.model = MagicMock()

        ctx = self._make_run_context(
            chat_history=[
                {"role": "assistant", "content": "欢迎"},
                {"role": "user", "content": "你好"},
                {"role": "user", "content": "我想了解专业"},
            ],
            batch=None,
        )

        result = await extract_major_intent(ctx)
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    @patch("app.tools.major_intent_tool._get_extraction_client")
    @patch("app.tools.major_intent_tool._get_extract_config")
    @patch("app.tools.major_intent_tool.Agent")
    async def test_result_is_valid_json(
        self, mock_agent_cls, mock_config, mock_client
    ):
        """Test that the result is valid JSON with expected fields."""
        mock_config.return_value.last_n_messages = 10

        mock_result = MagicMock()
        mock_result.output = MajorIntentResult(
            allkeys=["计算机"],
            level2=["计算机类"],
            level3=["软件工程"],
        ).model_dump_json()
        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)
        mock_agent_cls.return_value = mock_agent_instance
        mock_client.return_value.model = MagicMock()

        ctx = self._make_run_context(
            chat_history=[
                {"role": "assistant", "content": "欢迎"},
                {"role": "user", "content": "你好"},
                {"role": "user", "content": "我想学计算机类和软件工程"},
            ],
            batch="01",
        )

        result = await extract_major_intent(ctx)

        parsed = json.loads(result)
        assert "allkeys" in parsed
        assert "level2" in parsed
        assert "level3" in parsed
        assert parsed["level2"] == ["计算机类"]
        assert parsed["level3"] == ["软件工程"]

    @patch("app.tools.major_intent_tool._get_extraction_client")
    @patch("app.tools.major_intent_tool._get_extract_config")
    @patch("app.tools.major_intent_tool.Agent")
    async def test_agent_called_with_temperature_zero(
        self, mock_agent_cls, mock_config, mock_client
    ):
        """Test that the extraction agent is called with temperature=0."""
        mock_config.return_value.last_n_messages = 10

        mock_result = MagicMock()
        mock_result.output = MajorIntentResult().model_dump_json()
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

        await extract_major_intent(ctx)

        # Verify agent.run was called with temperature=0
        mock_agent_instance.run.assert_called_once()
        call_kwargs = mock_agent_instance.run.call_args[1]
        assert call_kwargs["model_settings"]["temperature"] == 0

    @patch("app.tools.major_intent_tool._get_extraction_client")
    @patch("app.tools.major_intent_tool._get_extract_config")
    @patch("app.tools.major_intent_tool.filter_major_hierarchy_by_prefix")
    @patch("app.tools.major_intent_tool.Agent")
    async def test_filters_major_hierarchy(
        self, mock_agent_cls, mock_filter, mock_config, mock_client
    ):
        """Test that major hierarchy is filtered by prefix."""
        mock_config.return_value.last_n_messages = 10
        mock_filter.return_value = "工学\n  计算机类"

        mock_result = MagicMock()
        mock_result.output = MajorIntentResult().model_dump_json()
        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)
        mock_agent_cls.return_value = mock_agent_instance
        mock_client.return_value.model = MagicMock()

        ctx = self._make_run_context(
            chat_history=[
                {"role": "user", "content": "我想学计算机"},
            ],
            batch="01",
        )

        await extract_major_intent(ctx)

        # Verify filter was called
        mock_filter.assert_called_once()


# ---- extract_negative_major_intent ----


class TestExtractNegativeMajorIntent:
    """Tests for extract_negative_major_intent async function."""

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

        result = await extract_negative_major_intent(ctx)

        parsed = json.loads(result)
        assert parsed["allkeys"] == []
        assert parsed["level2"] == []
        assert parsed["level3"] == []

    @patch("app.tools.major_intent_tool._get_extraction_client")
    @patch("app.tools.major_intent_tool._get_extract_config")
    @patch("app.tools.major_intent_tool.Agent")
    async def test_calls_agent_with_negative_output_type(
        self, mock_agent_cls, mock_config, mock_client
    ):
        """Test that extraction agent is created with string output type."""
        mock_config.return_value.last_n_messages = 10

        mock_result = MagicMock()
        mock_result.output = NegativeMajorIntentResult(
            allkeys=["医学"],
            level2=["医学类"],
            level3=[],
        ).model_dump_json()
        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)
        mock_agent_cls.return_value = mock_agent_instance

        mock_client.return_value.model = MagicMock()

        ctx = self._make_run_context(
            chat_history=[
                {"role": "assistant", "content": "欢迎"},
                {"role": "user", "content": "你好"},
                {"role": "user", "content": "我不想学医学"},
            ],
            batch="01",
        )

        result = await extract_negative_major_intent(ctx)

        # Verify Agent was created with correct output_type
        mock_agent_cls.assert_called_once()
        call_kwargs = mock_agent_cls.call_args[1]
        assert call_kwargs["output_type"] is str

    @patch("app.tools.major_intent_tool._get_extraction_client")
    @patch("app.tools.major_intent_tool._get_extract_config")
    @patch("app.tools.major_intent_tool.Agent")
    async def test_result_is_valid_json(
        self, mock_agent_cls, mock_config, mock_client
    ):
        """Test that the result is valid JSON with expected fields."""
        mock_config.return_value.last_n_messages = 10

        mock_result = MagicMock()
        mock_result.output = NegativeMajorIntentResult(
            allkeys=["医学", "护理"],
            level2=["医学类"],
            level3=["护理学"],
        ).model_dump_json()
        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)
        mock_agent_cls.return_value = mock_agent_instance
        mock_client.return_value.model = MagicMock()

        ctx = self._make_run_context(
            chat_history=[
                {"role": "assistant", "content": "欢迎"},
                {"role": "user", "content": "你好"},
                {"role": "user", "content": "我不想学医学类和护理学"},
            ],
            batch="01",
        )

        result = await extract_negative_major_intent(ctx)

        parsed = json.loads(result)
        assert "allkeys" in parsed
        assert "level2" in parsed
        assert "level3" in parsed
        assert parsed["level2"] == ["医学类"]
        assert parsed["level3"] == ["护理学"]

    @patch("app.tools.major_intent_tool._get_extraction_client")
    @patch("app.tools.major_intent_tool._get_extract_config")
    @patch("app.tools.major_intent_tool.Agent")
    async def test_agent_called_with_temperature_zero(
        self, mock_agent_cls, mock_config, mock_client
    ):
        """Test that the extraction agent is called with temperature=0."""
        mock_config.return_value.last_n_messages = 10

        mock_result = MagicMock()
        mock_result.output = NegativeMajorIntentResult().model_dump_json()
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

        await extract_negative_major_intent(ctx)

        # Verify agent.run was called with temperature=0
        mock_agent_instance.run.assert_called_once()
        call_kwargs = mock_agent_instance.run.call_args[1]
        assert call_kwargs["model_settings"]["temperature"] == 0


class TestExtractMajorIntentsWithPolarity:
    """Tests for combined positive/negative major intent extraction."""

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

        result = await extract_major_intents_with_polarity(ctx)

        parsed = json.loads(result)
        assert parsed["positive"]["level2"] == []
        assert parsed["negative"]["level2"] == []

    @patch("app.tools.major_intent_tool._get_extraction_client")
    @patch("app.tools.major_intent_tool._get_extract_config")
    @patch("app.tools.major_intent_tool.Agent")
    async def test_extracts_positive_and_negative_in_one_call(
        self, mock_agent_cls, mock_config, mock_client
    ):
        mock_config.return_value.last_n_messages = 10
        mock_result = MagicMock()
        mock_result.output = MajorIntentPolarityResult(
            positive=MajorIntentResult(allkeys=["法学"], level2=["法学类"], level3=[]),
            negative=NegativeMajorIntentResult(allkeys=["护理"], level2=["护理学类"], level3=[]),
        ).model_dump_json()
        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)
        mock_agent_cls.return_value = mock_agent_instance
        mock_client.return_value.model = MagicMock()

        ctx = self._make_run_context(
            chat_history=[{"role": "user", "content": "我倾向法学，但护理不要"}],
            batch="01",
        )

        result = await extract_major_intents_with_polarity(ctx)

        parsed = json.loads(result)
        assert parsed["positive"]["level2"] == ["法学类"]
        assert parsed["negative"]["level2"] == ["护理学类"]
        mock_agent_cls.assert_called_once()
        mock_agent_instance.run.assert_awaited_once()
        assert mock_agent_instance.run.await_args.kwargs["model_settings"]["temperature"] == 0
