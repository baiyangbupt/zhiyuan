"""A1：交互能力的协议级回归。

这些用例只证明**上层按既定协议形状收发**，不证明真实二进制支持这些能力——
后者只能由 `scripts/probe_codex_capabilities.py` 对真实二进制跑出来。
两类证据不能互相顶替，这也是本文件与探针分开存在的原因。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.harness.client import AppServerClient
from app.harness.codex import CodexAppServerHarness


FAKE_SERVER = Path(__file__).resolve().parents[1] / "fixtures" / "codex" / "fake_app_server.py"
FAKE_COMMAND = [sys.executable, str(FAKE_SERVER)]
CAPABILITIES = {
    "experimentalApi": True,
    "extensions": {"openai/standard-form-input": {}},
}


@pytest.mark.asyncio
async def test_initialize_sends_declared_capabilities() -> None:
    """声明的能力必须真的发出去；不发等于没声明。"""
    client = AppServerClient(FAKE_COMMAND)
    await client.start()

    result = await client.initialize(
        client_name="zhiyuan-gateway", client_version="1", capabilities=CAPABILITIES
    )

    assert result["received"]["clientInfo"] == {"name": "zhiyuan-gateway", "version": "1"}
    assert result["received"]["capabilities"] == CAPABILITIES
    await client.close()


@pytest.mark.asyncio
async def test_initialize_without_capabilities_keeps_old_shape() -> None:
    """不传 capabilities 时保持旧报文不变，老调用方不受影响。"""
    client = AppServerClient(FAKE_COMMAND)
    await client.start()

    result = await client.initialize(client_name="zhiyuan_gateway", client_version="0.1.0")

    assert "capabilities" not in result["received"]
    await client.close()


@pytest.mark.asyncio
async def test_harness_passes_capabilities_from_config() -> None:
    harness = CodexAppServerHarness(FAKE_COMMAND, capabilities=CAPABILITIES)
    await harness.start()

    assert harness.initialize_result["received"]["capabilities"] == CAPABILITIES
    await harness.close()


@pytest.mark.asyncio
async def test_harness_without_capabilities_declares_none() -> None:
    harness = CodexAppServerHarness(FAKE_COMMAND)
    await harness.start()

    assert "capabilities" not in harness.initialize_result["received"]
    await harness.close()


@pytest.mark.asyncio
async def test_server_request_is_answered_under_original_id() -> None:
    """原生提问是带 id 的双向请求，回包必须用同一个 id。"""
    answered: list[dict] = []
    client = AppServerClient(FAKE_COMMAND)
    client.server_request_handler = _answering_handler(
        answered, {"answers": {"major": {"answers": ["计算机类"]}}}
    )
    await client.start()
    await client.initialize(client_name="zhiyuan-gateway", client_version="1")

    await client.request("test/request_user_input", {})
    notification = await client.wait_for_notification(
        lambda n: n.get("method") == "test/server_request_answered", timeout=5
    )

    assert notification["params"]["method"] == "item/tool/requestUserInput"
    assert notification["params"]["requestId"] >= 9000
    assert notification["params"]["result"] == {"answers": {"major": {"answers": ["计算机类"]}}}
    assert notification["params"]["error"] is None
    assert answered[0]["params"]["questions"][0]["id"] == "major"
    await client.close()


@pytest.mark.asyncio
async def test_elicitation_request_reaches_the_same_handler() -> None:
    """MCP form 与原生提问走同一入口，但 params 形状不同（mode/schema 在顶层）。"""
    answered: list[dict] = []
    client = AppServerClient(FAKE_COMMAND)
    client.server_request_handler = _answering_handler(
        answered, {"action": "accept", "content": {"confirm": True}}
    )
    await client.start()
    await client.initialize(client_name="zhiyuan-gateway", client_version="1")

    await client.request("test/elicitation", {})
    notification = await client.wait_for_notification(
        lambda n: n.get("method") == "test/server_request_answered", timeout=5
    )

    assert notification["params"]["method"] == "mcpServer/elicitation/request"
    assert notification["params"]["result"] == {"action": "accept", "content": {"confirm": True}}
    assert answered[0]["params"]["mode"] == "form"
    assert answered[0]["params"]["requestedSchema"]["required"] == ["confirm"]
    await client.close()


@pytest.mark.asyncio
async def test_nested_mcp_item_is_observable() -> None:
    """item 嵌在 params 里；开始与结束是两个独立通知。"""
    client = AppServerClient(FAKE_COMMAND)
    await client.start()
    await client.initialize(client_name="zhiyuan-gateway", client_version="1")

    await client.request("test/nested_mcp_item", {"tool": "admission.get_history"})
    started = await client.wait_for_notification(
        lambda n: n.get("method") == "item/started", timeout=5
    )
    completed = await client.wait_for_notification(
        lambda n: n.get("method") == "item/completed", timeout=5
    )

    assert started["params"]["item"]["type"] == "mcpToolCall"
    assert started["params"]["item"]["tool"] == "admission.get_history"
    assert started["params"]["item"]["status"] == "inProgress"
    assert completed["params"]["item"]["status"] == "completed"
    await client.close()


@pytest.mark.asyncio
async def test_process_exit_fails_pending_request_instead_of_hanging() -> None:
    client = AppServerClient(FAKE_COMMAND, request_timeout=30)
    await client.start()
    await client.initialize(client_name="zhiyuan-gateway", client_version="1")

    with pytest.raises(RuntimeError, match="app server exited"):
        await client.request("test/exit_pending", {})

    assert client.pending_request_count == 0
    await client.close()


def _answering_handler(seen: list[dict], result: dict):
    async def handler(payload: dict) -> dict:
        seen.append(payload)
        return result

    return handler
