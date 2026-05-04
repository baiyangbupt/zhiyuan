"""Unit tests for app.data.message_utils module."""

import pytest

from app.data.message_utils import format_messages, trim_last_n_messages


class TestFormatMessages:
    """Tests for format_messages function."""

    def test_format_basic_messages(self):
        """Test formatting basic user and assistant messages."""
        messages = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好，有什么可以帮助你？"},
        ]

        result = format_messages(messages)

        assert "学生: 你好" in result
        assert "规划师: 你好，有什么可以帮助你？" in result

    def test_format_messages_with_delimiters(self):
        """Test that formatted output includes delimiters."""
        messages = [{"role": "user", "content": "测试"}]

        result = format_messages(messages)

        assert "=== 对话历史开始 ===" in result
        assert "=== 对话历史结束 ===" in result

    def test_format_empty_messages(self):
        """Test formatting empty message list."""
        result = format_messages([])

        assert "=== 对话历史开始 ===" in result
        assert "=== 对话历史结束 ===" in result

    def test_format_messages_with_clicked_true(self):
        """Test that clicked=True messages are displayed normally."""
        messages = [
            {"role": "assistant", "content": "推荐院校A", "clicked": True},
        ]

        result = format_messages(messages)

        assert "规划师: 推荐院校A" in result

    def test_format_messages_with_last_clicked_false(self):
        """Test that only the last clicked=False message is shown."""
        messages = [
            {"role": "assistant", "content": "第一个建议", "clicked": False},
            {"role": "user", "content": "好的"},
            {"role": "assistant", "content": "第二个建议", "clicked": False},
        ]

        result = format_messages(messages)

        # First clicked=False should be masked
        assert "规划师: [规划师提出了建议，但是用户未回应，对内容遮盖掉，避免影响输出。]" in result
        # Last clicked=False should be shown
        assert "规划师: 第二个建议" in result

    def test_format_messages_single_clicked_false(self):
        """Test single clicked=False message is shown (it's the last one)."""
        messages = [
            {"role": "assistant", "content": "唯一的建议", "clicked": False},
        ]

        result = format_messages(messages)

        assert "规划师: 唯一的建议" in result

    def test_format_messages_with_none_clicked(self):
        """Test that messages without clicked field are shown normally."""
        messages = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好"},
        ]

        result = format_messages(messages)

        assert "学生: 你好" in result
        assert "规划师: 你好" in result

    def test_format_messages_missing_role_and_content(self):
        """Test formatting messages with missing role and content."""
        messages = [
            {},
            {"role": "user"},
            {"content": "无角色消息"},
        ]

        result = format_messages(messages)

        # Should not crash, just produce empty or partial output
        assert "=== 对话历史开始 ===" in result


class TestTrimLastNMessages:
    """Tests for trim_last_n_messages function."""

    def test_trim_basic(self):
        """Test trimming messages after removing welcome messages."""
        messages = [
            {"role": "assistant", "content": "欢迎语1"},
            {"role": "user", "content": "欢迎语2"},
            {"role": "user", "content": "消息1"},
            {"role": "assistant", "content": "消息2"},
            {"role": "user", "content": "消息3"},
            {"role": "assistant", "content": "消息4"},
            {"role": "user", "content": "消息5"},
        ]

        result = trim_last_n_messages(messages, 3)

        assert len(result) == 3
        assert result[0]["content"] == "消息3"
        assert result[1]["content"] == "消息4"
        assert result[2]["content"] == "消息5"

    def test_trim_fewer_than_n_messages(self):
        """Test trimming when fewer than n messages remain."""
        messages = [
            {"role": "assistant", "content": "欢迎语1"},
            {"role": "user", "content": "欢迎语2"},
            {"role": "user", "content": "消息1"},
            {"role": "assistant", "content": "消息2"},
        ]

        result = trim_last_n_messages(messages, 10)

        assert len(result) == 2
        assert result[0]["content"] == "消息1"
        assert result[1]["content"] == "消息2"

    def test_trim_exactly_two_messages(self):
        """Test trimming when there are exactly two messages (welcome only)."""
        messages = [
            {"role": "assistant", "content": "欢迎语1"},
            {"role": "user", "content": "欢迎语2"},
        ]

        result = trim_last_n_messages(messages, 5)

        # Should return as-is since len <= 2
        assert len(result) == 2

    def test_trim_single_message(self):
        """Test trimming with single message."""
        messages = [{"role": "user", "content": "唯一消息"}]

        result = trim_last_n_messages(messages, 5)

        assert len(result) == 1
        assert result[0]["content"] == "唯一消息"

    def test_trim_empty_messages(self):
        """Test trimming empty message list."""
        result = trim_last_n_messages([], 5)

        assert result == []

    def test_trim_n_equals_remaining(self):
        """Test trimming when n equals remaining messages."""
        messages = [
            {"role": "assistant", "content": "欢迎语1"},
            {"role": "user", "content": "欢迎语2"},
            {"role": "user", "content": "消息1"},
            {"role": "assistant", "content": "消息2"},
            {"role": "user", "content": "消息3"},
        ]

        result = trim_last_n_messages(messages, 3)

        assert len(result) == 3
        assert result[0]["content"] == "消息1"

    def test_trim_does_not_modify_original(self):
        """Test that trimming does not mutate the original list."""
        messages = [
            {"role": "assistant", "content": "欢迎语1"},
            {"role": "user", "content": "欢迎语2"},
            {"role": "user", "content": "消息1"},
            {"role": "assistant", "content": "消息2"},
            {"role": "user", "content": "消息3"},
            {"role": "assistant", "content": "消息4"},
            {"role": "user", "content": "消息5"},
        ]
        original_len = len(messages)

        trim_last_n_messages(messages, 2)

        assert len(messages) == original_len
