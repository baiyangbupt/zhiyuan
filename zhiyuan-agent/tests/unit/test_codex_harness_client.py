from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from app.harness.client import (
    AppServerClient,
    AppServerExited,
    AppServerProtocolError,
    AppServerTimeout,
)
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
async def test_harness_passes_thread_approval_policy() -> None:
    harness = CodexAppServerHarness(
        [sys.executable, str(FAKE_SERVER)],
        approval_policy="never",
        sandbox_policy="read-only",
    )
    await harness.start()
    result = await harness.create_thread()
    assert result["thread"]["id"] == "thr_test"
    assert result["received"]["approvalPolicy"] == "never"
    assert result["received"]["sandbox"] == "read-only"
    await harness.close()


@pytest.mark.asyncio
async def test_harness_sends_structured_turn_sandbox_policy() -> None:
    harness = CodexAppServerHarness(
        [sys.executable, str(FAKE_SERVER)],
        approval_policy="never",
        sandbox_policy="read-only",
    )
    await harness.start()
    # thread 表是进程内的：真实二进制在没 start/resume 过的 thread 上开回合会回
    # `-32600 thread not found`，替身照此建模，所以这里必须先建。
    await harness.create_thread()
    result = await harness.start_turn(
        "thr_test", [{"type": "text", "text": "你好"}], {"type": "object"}
    )
    assert result["received"]["approvalPolicy"] == "never"
    assert result["received"]["sandboxPolicy"] == {
        "type": "readOnly",
        "networkAccess": False,
    }
    await harness.close()


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
async def test_client_marks_pending_requests_failed_when_process_exits(caplog) -> None:
    client = AppServerClient([sys.executable, str(FAKE_SERVER)])
    await client.start()
    await client.initialize(client_name="test", client_version="0")

    request_task = asyncio.create_task(client.request("test/hang", {}))
    await asyncio.sleep(0.02)
    await client.request("test/exit", {})
    with pytest.raises(Exception, match="app server exited"):
        await request_task
    # 退出码要落在日志里：`AppServerExited` 只说"没了"，退出码才说"怎么没的"
    # （0=自己退、-9=被 SIGKILL、-15=被 SIGTERM、134=abort）。
    for _ in range(100):
        if "exited on its own" in caplog.text:
            break
        await asyncio.sleep(0.01)
    assert "exited on its own returncode=0" in caplog.text, caplog.text
    await client.close()


@pytest.mark.asyncio
async def test_harness_waits_for_turn_completed_notification() -> None:
    harness = CodexAppServerHarness([sys.executable, str(FAKE_SERVER)])
    await harness.start()
    await harness.create_thread()

    result = await harness.start_turn_and_collect(
        "thr_test",
        [{"type": "text", "text": "你好"}],
        {"type": "object"},
    )

    assert result.status == "completed"
    assert result.turn_id == "turn_test"
    assert result.events
    await harness.close()


def test_harness_waits_for_turn_completion_after_agent_message_item() -> None:
    event = {
        "type": "item/completed",
        "item": {
            "type": "agentMessage",
            "text": '{"responseType":"clarification","message":"请补充省份"}',
        },
    }

    assert _terminal_status(event) is None
    assert _extract_output(event) == {
        "responseType": "clarification",
        "message": "请补充省份",
    }


def test_harness_waits_even_after_final_agent_message() -> None:
    event = {
        "type": "item/completed",
        "item": {
            "type": "agentMessage",
            "phase": "final_answer",
            "text": '{"message":"测试通过"}',
        },
    }

    assert _terminal_status(event) is None


@pytest.mark.parametrize("status", ["completed", "failed", "interrupted"])
def test_nested_turn_terminal_status(status):
    from app.harness.codex import _matches_turn
    notification = {"method": "turn/completed", "params": {
        "threadId": "thread-1", "turn": {"id": "turn-1", "status": status}
    }}
    assert _matches_turn(notification, "thread-1", "turn-1")
    assert not _matches_turn(notification, "thread-1", "turn-other")
    assert _terminal_status({"type": "turn/completed", **notification["params"]}) == status


def test_turn_match_accepts_thread_scoped_mcp_notification_without_turn_id() -> None:
    from app.harness.codex import _matches_turn

    notification = {
        "method": "item/completed",
        "params": {
            "threadId": "thread-1",
            "item": {"type": "mcpToolCall", "tool": "admission.get_history"},
        },
    }

    assert _matches_turn(notification, "thread-1", "turn-1")
    assert not _matches_turn(notification, "thread-other", "turn-1")


def test_extract_output_accepts_json_markdown_fence() -> None:
    assert _extract_output({"item": {"text": "```json\n{\"message\":\"ok\"}\n```"}}) == {
        "message": "ok"
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


@pytest.mark.asyncio
async def test_a_dead_app_server_can_be_restarted() -> None:
    """退出后的进程不会自己复活，而**一条坏 thread 就能把它打死**。

    没有重拉这条路，恢复就撞在一个死进程上：新建会话也一样失败，
    整个 agent 跟着废（实测发生过）。
    """
    from app.harness.client import AppServerExited

    harness = CodexAppServerHarness([sys.executable, str(FAKE_SERVER)], request_timeout=10.0)
    await harness.start()
    try:
        assert harness.client.is_running is True

        await harness.client.request("test/exit", {})
        for _ in range(200):
            if not harness.client.is_running:
                break
            await asyncio.sleep(0.01)
        assert harness.client.is_running is False

        # 退出之后，在途/新发的请求都必须是**类型**为 AppServerExited 的失败，
        # 而不是一句要人去匹配的消息。
        with pytest.raises(AppServerExited):
            await harness.client.request("test/stats", {})

        await harness.restart()

        assert harness.client.is_running is True
        stats = await harness.client.request("test/stats", {})
        assert stats["threadStarts"] == 0
        # 握手重做过：能力声明是每次连接谈的，不重做模型就再也提不了问。
        assert harness.initialize_result is not None
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_a_long_stdout_line_is_not_mistaken_for_a_dead_process() -> None:
    """一条大通知不许被当成"进程死了"。

    实测（2026-09-21）：asyncio 默认的 64 KiB 行上限被一条 229 KiB 的通知撑爆，
    `readline()` 抛 ValueError → `_read_stdout` 的 finally 把在途请求全标成
    `AppServerExited`，而**进程还活着**。恢复路径于是关掉活进程的 stdin，它优雅退出
    （rollout 里留下 `turn_aborted/interrupted`、退出码 0）——整条链看起来就是
    "codex 自己死了"，而真凶是我们自己的读循环。
    """
    client = AppServerClient([sys.executable, str(FAKE_SERVER)], request_timeout=10.0)
    await client.start()
    await client.initialize(client_name="test", client_version="0")

    result = await client.request("test/big_notification", {"bytes": 229 * 1024})

    assert result["bytes"] == 229 * 1024
    assert client.is_running, "进程根本没死，不该被判成死的"
    await client.close()


@pytest.mark.asyncio
async def test_an_over_limit_line_says_so_instead_of_just_app_server_exited(caplog) -> None:
    """超过上限时要说清是"流读不下去"，不是"进程退出"。

    两者处置相同（都得重拉），但日志必须分得开——分不开就是上面那一课本身：
    排查时看到的只有 `AppServerExited`，而进程其实活着。
    """
    client = AppServerClient(
        [sys.executable, str(FAKE_SERVER)], request_timeout=10.0, line_limit=1024
    )
    await client.start()
    await client.initialize(client_name="test", client_version="0")

    with pytest.raises(AppServerExited, match="stdout line exceeded 1024 bytes"):
        await client.request("test/big_notification", {"bytes": 4096})

    assert "stdout line exceeded" in caplog.text
    await client.close()


@pytest.mark.asyncio
async def test_a_line_with_bad_bytes_is_dropped_not_treated_as_a_death(caplog) -> None:
    """带坏字节的一行只该被丢掉，不该把读循环带走。

    解码错误会走进 `_read_stdout` 的同一个 finally——那正是"把活着的进程判成死的"
    那条路（见 `DEFAULT_STDOUT_LINE_LIMIT` 的注释）。
    """
    client = AppServerClient([sys.executable, str(FAKE_SERVER)], request_timeout=10.0)
    await client.start()
    await client.initialize(client_name="test", client_version="0")

    result = await client.request("test/bad_bytes", {})

    assert result["ok"] is True
    assert client.is_running
    assert "ignored non-json app-server stdout line" in caplog.text
    await client.close()
