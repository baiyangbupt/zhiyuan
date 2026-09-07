from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from app.harness.codex import CodexAppServerHarness
from scripts.codex_app_server_poc import (
    check_binding,
    check_codex_mcp_metadata,
    check_protocol,
)


FAKE_SERVER = Path(__file__).resolve().parents[1] / "fixtures" / "codex" / "fake_app_server.py"


@pytest.mark.asyncio
async def test_protocol_check_materializes_turn_before_resume() -> None:
    result = await check_protocol([sys.executable, str(FAKE_SERVER)])

    assert result == {
        "initialize": "ok",
        "thread_start": "ok",
        "inject_items": "ok",
        "turn_start": "ok",
        "output_schema": "ok",
        "thread_resume": "ok",
    }


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


@pytest.mark.asyncio
async def test_binding_fixture_reports_trusted_context_and_denies_revocation() -> None:
    fixture = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "mcp"
        / "echo_binding_server.py"
    )
    result = await check_binding(str(fixture))

    assert result == {
        "binding": "trusted",
        "model_identity_override": "ignored",
        "revoked": "denied",
    }


@pytest.mark.asyncio
async def test_real_codex_mcp_call_carries_server_thread_metadata(tmp_path, monkeypatch) -> None:
    binary = os.environ.get("CODEX_APP_SERVER_BIN")
    if not binary or not Path(binary).exists():
        pytest.skip("fixed Codex App Server binary is not installed")
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    result = await check_codex_mcp_metadata(
        [binary],
        str(
            Path(__file__).resolve().parents[1]
            / "fixtures"
            / "mcp"
            / "codex_metadata_server.py"
        ),
    )

    assert result["mcp_metadata"] == "trusted"
    assert result["model_identity_override"] == "ignored"
