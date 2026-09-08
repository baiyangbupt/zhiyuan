from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from app.harness.client import AppServerClient, AppServerProtocolError, AppServerTimeout
from app.harness.codex import CodexAppServerHarness
from app.harness.codex import _extract_output, _terminal_status


FAKE_SERVER = Path(__file__).resolve().parents[1] / "fixtures" / "codex" / "fake_app_server.py"


@pytest.mark.asyncio
async def test_client_correlates_response_and_notification() -> None:
    client = AppServerClient([sys.executable, str(FAKE_SERVER)])
    await client.start()
    await client.initialize(client_name="zhiyuan_gateway", client_version="0.1.0")

    response = await client.request("thread/start", {"model": "test"})
    assert response["thread"]["id"] == "thr_test"
    notification = await client.next_notification()
    assert notification["method"] == "thread/started"
    assert notification["params"]["threadId"] == "thr_test"
    await client.close()


@pytest.mark.asyncio
async def test_client_surfaces_json_rpc_error() -> None:
    client = AppServerClient([sys.executable, str(FAKE_SERVER)])
    await client.start()
    await client.initialize(client_name="test", client_version="0")

    with pytest.raises(AppServerProtocolError, match="requested failure"):
        await client.request("test/error", {})
    await client.close()


@pytest.mark.asyncio
async def test_client_times_out_without_leaking_pending_request() -> None:
    client = AppServerClient([sys.executable, str(FAKE_SERVER)], request_timeout=0.02)
    await client.start()
    await client.initialize(client_name="test", client_version="0")

    with pytest.raises(AppServerTimeout):
        await client.request("test/hang", {})
    assert client.pending_request_count == 0
    await client.close()


@pytest.mark.asyncio
async def test_client_supports_concurrent_requests_without_id_collision() -> None:
    client = AppServerClient([sys.executable, str(FAKE_SERVER)])
    await client.start()
    await client.initialize(client_name="test", client_version="0")

    responses = await asyncio.gather(
        client.request("test/echo", {"value": "a"}),
        client.request("test/echo", {"value": "b"}),
    )
    assert {response["value"] for response in responses} == {"a", "b"}
    await client.close()


@pytest.mark.asyncio
async def test_client_marks_pending_requests_failed_when_process_exits() -> None:
    client = AppServerClient([sys.executable, str(FAKE_SERVER)])
    await client.start()
    await client.initialize(client_name="test", client_version="0")

    request_task = asyncio.create_task(client.request("test/hang", {}))
    await asyncio.sleep(0.02)
    await client.request("test/exit", {})
    with pytest.raises(Exception, match="app server exited"):
        await request_task
    await client.close()


@pytest.mark.asyncio
async def test_harness_waits_for_turn_completed_notification() -> None:
    harness = CodexAppServerHarness([sys.executable, str(FAKE_SERVER)])
    await harness.start()

    result = await harness.start_turn_and_collect(
        "thr_test",
        [{"type": "text", "text": "你好"}],
        {"type": "object"},
    )

    assert result.status == "completed"
    assert result.turn_id == "turn_test"
    assert result.events
    await harness.close()


def test_harness_accepts_real_agent_message_item_completion() -> None:
    event = {
        "type": "item/completed",
        "item": {
            "type": "agentMessage",
            "text": '{"responseType":"clarification","message":"请补充省份"}',
        },
    }

    assert _terminal_status(event) == "completed"
    assert _extract_output(event) == {
        "responseType": "clarification",
        "message": "请补充省份",
    }


@pytest.mark.asyncio
async def test_client_routes_concurrent_notification_waiters_without_cross_turn_blocking() -> None:
    client = AppServerClient([sys.executable, str(FAKE_SERVER)])
    first = asyncio.create_task(
        client.wait_for_notification(lambda item: item.get("params", {}).get("turnId") == "turn-a")
    )
    second = asyncio.create_task(
        client.wait_for_notification(lambda item: item.get("params", {}).get("turnId") == "turn-b")
    )
    await asyncio.sleep(0)

    client._route_notification({"method": "turn/completed", "params": {"turnId": "turn-b"}})
    client._route_notification({"method": "turn/completed", "params": {"turnId": "turn-a"}})

    second_result = await second
    first_result = await first
    assert second_result["params"]["turnId"] == "turn-b"
    assert first_result["params"]["turnId"] == "turn-a"
