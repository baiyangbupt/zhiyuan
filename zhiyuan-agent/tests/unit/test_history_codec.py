"""Tests for pydantic-ai history serialization helpers."""

from __future__ import annotations

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from app.data.history_codec import deserialize_history, serialize_history


def test_round_trip_text_messages():
    messages = [
        ModelRequest(parts=[UserPromptPart(content="你好")], instructions="请简洁回答"),
        ModelResponse(parts=[TextPart(content="你好，有什么想了解的？")], model_name="test-model"),
    ]

    payload = serialize_history(messages)
    restored = deserialize_history(payload)

    assert len(restored) == 2
    assert restored[0].kind == "request"
    assert restored[0].parts[0].content == "你好"
    assert restored[1].kind == "response"
    assert restored[1].parts[0].content == "你好，有什么想了解的？"
    assert restored[1].model_name == "test-model"


def test_round_trip_tool_messages():
    messages = [
        ModelResponse(
            parts=[
                TextPart(content="我先调用工具。"),
                ToolCallPart(tool_name="extract_major_intent", args={"reason": "提取专业"}),
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="extract_major_intent",
                    content={"level2": ["计算机类"]},
                    tool_call_id="call_123",
                )
            ]
        ),
    ]

    payload = serialize_history(messages)
    restored = deserialize_history(payload)

    assert len(restored) == 2
    assert restored[0].parts[1].tool_name == "extract_major_intent"
    assert restored[0].parts[1].args == {"reason": "提取专业"}
    assert restored[1].parts[0].tool_name == "extract_major_intent"
    assert restored[1].parts[0].content == {"level2": ["计算机类"]}
    assert restored[1].parts[0].tool_call_id == "call_123"


def test_empty_payload_returns_empty_list():
    assert deserialize_history("") == []
