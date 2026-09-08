import asyncio

import pytest

from app.harness.client import AppServerClient


@pytest.mark.asyncio
async def test_server_request_handler_returns_json_rpc_result() -> None:
    received: list[dict] = []

    async def handler(request: dict) -> dict:
        received.append(request)
        return {"action": "accept", "content": None}

    client = AppServerClient([], server_request_handler=handler)
    sent: list[dict] = []

    async def write(payload: dict) -> None:
        sent.append(payload)

    client._write = write  # type: ignore[method-assign]
    await client._handle_server_request(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "mcpServer/elicitation/request",
            "params": {"serverName": "semantic_readonly"},
        }
    )

    assert received[0]["id"] == 7
    assert sent == [
        {
            "jsonrpc": "2.0",
            "id": 7,
            "result": {"action": "accept", "content": None},
        }
    ]
