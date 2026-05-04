"""Pydantic AI message history serialization helpers."""

from __future__ import annotations

from typing import Any

from pydantic_ai.messages import ModelMessagesTypeAdapter


def serialize_history(messages: list[Any]) -> str:
    """Serialize pydantic-ai message history to JSON."""
    return ModelMessagesTypeAdapter.dump_json(messages).decode("utf-8")


def deserialize_history(payload: str) -> list[Any]:
    """Deserialize JSON payload to pydantic-ai message history."""
    if not payload.strip():
        return []
    return ModelMessagesTypeAdapter.validate_json(payload)
