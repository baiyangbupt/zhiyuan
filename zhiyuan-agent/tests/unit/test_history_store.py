"""Tests for SQLite-backed chat history store."""

from __future__ import annotations

import sqlite3

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

from app.data.history_store import ChatHistoryStore


@pytest.mark.asyncio
async def test_load_missing_session_returns_none(tmp_path):
    store = ChatHistoryStore(str(tmp_path / "history.db"))

    history = await store.load("missing-session")

    assert history is None


@pytest.mark.asyncio
async def test_save_and_load_round_trip(tmp_path):
    store = ChatHistoryStore(str(tmp_path / "history.db"))
    messages = [
        ModelRequest(parts=[UserPromptPart(content="第一轮")]),
        ModelResponse(parts=[TextPart(content="收到")], model_name="test-model"),
    ]

    await store.save("session-1", messages)
    restored = await store.load("session-1")

    assert restored is not None
    assert len(restored) == 2
    assert restored[0].parts[0].content == "第一轮"
    assert restored[1].parts[0].content == "收到"


@pytest.mark.asyncio
async def test_save_updates_existing_session(tmp_path):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))

    await store.save("session-1", [ModelRequest(parts=[UserPromptPart(content="旧消息")])])
    await store.save(
        "session-1",
        [
            ModelRequest(parts=[UserPromptPart(content="新消息")]),
            ModelResponse(parts=[TextPart(content="新回复")], model_name="test-model"),
        ],
    )

    restored = await store.load("session-1")
    assert restored is not None
    assert len(restored) == 2
    assert restored[0].parts[0].content == "新消息"

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT schema_version, created_at, updated_at FROM chat_session_history WHERE session_id = ?",
            ("session-1",),
        ).fetchone()

    assert row is not None
    assert row[0] == 1
    assert row[1]
    assert row[2]
