from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.harness.codex import CodexAppServerHarness


FAKE_SERVER = Path(__file__).resolve().parents[1] / "fixtures" / "codex" / "fake_app_server.py"


@pytest.mark.asyncio
async def test_codex_harness_lifecycle_and_streaming_events() -> None:
    harness = CodexAppServerHarness([sys.executable, str(FAKE_SERVER)])
    await harness.start()
    thread = await harness.create_thread(
        base_instructions="facts first",
        developer_instructions="planner mode",
    )
    assert thread["thread"]["id"] == "thr_test"
    started_event = await harness.next_event()
    assert started_event["method"] == "thread/started"

    await harness.inject_items("thr_test", [{"type": "text", "text": "state"}])
    turn = await harness.start_turn(
        "thr_test",
        [{"type": "text", "text": "查招生计划"}],
        {"type": "object", "properties": {"message": {"type": "string"}}},
    )
    assert turn["turn"]["id"] == "turn_test"
    event = await harness.next_event()
    assert event["method"] == "item/agentMessage/delta"

    await harness.steer_turn("thr_test", "turn_test", [{"type": "text", "text": "补充"}])
    await harness.interrupt_turn("thr_test", "turn_test")
    resumed = await harness.resume_thread("thr_test")
    assert resumed["thread"]["id"] == "thr_test"
    await harness.close()
