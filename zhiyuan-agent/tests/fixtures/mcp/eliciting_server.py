#!/usr/bin/env python3
"""会发出 elicitation 的 MCP stdio fixture。

它只做一件事：被 `tools/call` 时，先向客户端发一个 `elicitation/create`
服务端请求，拿到回包后再把回包内容作为工具结果返回。

形状照抄 codex 源码里的生产者（`codex-rs/rmcp-client/src/bin/test_mcp_2026_stdio_server.rs`），
不是照消费者期望编的——这个区别在 P1a 上栽过一次。
"""
from __future__ import annotations

import json
import sys

_pending: dict[str, dict] = {}
MODE = "modern" if "--modern" in sys.argv else "legacy"


def send_raw(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def send(request_id, result) -> None:
    send_raw({"jsonrpc": "2.0", "id": request_id, "result": result})


REQUESTED_SCHEMA = {
    "type": "object",
    "properties": {"approved": {"type": "boolean"}, "note": {"type": "string"}},
    "required": ["approved"],
}


def handle_tools_call(request_id, params, mode: str) -> None:
    """两种 elicitation 形态，由启动参数选择。

    - legacy：服务端**主动发** `elicitation/create` 请求，等客户端回包。
    - modern：工具结果里带 `resultType: input_required` 与 `inputRequests`，
      客户端带着 `inputResponses` 重试同一次 tools/call。
    """
    if mode == "modern":
        responses = params.get("inputResponses")
        if responses is None:
            send(
                request_id,
                {
                    "resultType": "input_required",
                    "inputRequests": {
                        "approval": {
                            "method": "elicitation/create",
                            "params": {
                                "mode": "form",
                                "message": "Approve this form?",
                                "requestedSchema": REQUESTED_SCHEMA,
                            },
                        }
                    },
                    "requestState": "fixture-state",
                },
            )
            return
        send(
            request_id,
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({"elicitation_result": responses}, ensure_ascii=False),
                    }
                ]
            },
        )
        return

    _pending["elicitation"] = {"requestId": request_id}
    send_raw(
        {
            "jsonrpc": "2.0",
            "id": "elic-1",
            "method": "elicitation/create",
            "params": {"message": "Approve this form?", "requestedSchema": REQUESTED_SCHEMA},
        }
    )


for line in sys.stdin:
    try:
        message = json.loads(line)
    except json.JSONDecodeError:
        continue
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    if method is None and request_id == "elic-1" and "elicitation" in _pending:
        call_id = _pending.pop("elicitation")["requestId"]
        send(
            call_id,
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {"elicitation_result": message.get("result")},
                            ensure_ascii=False,
                        ),
                    }
                ]
            },
        )
        continue

    if method == "initialize":
        send(
            request_id,
            {
                "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "eliciting-fixture", "version": "0.1.0"},
            },
        )
    elif method == "notifications/initialized":
        continue
    elif method == "tools/list":
        result = {
            "tools": [
                {
                    "name": "ask_form",
                    "description": "Ask the client to fill a form.",
                    "inputSchema": {"type": "object", "properties": {}},
                }
            ]
        }
        if MODE == "modern":
            # 现代（2026）工具清单必须带这三个字段，否则服务端会把它当 legacy，
            # 于是它拒绝 input_required 结果——那样测出来的是夹具的错，不是能力。
            result["resultType"] = "complete"
            result["ttlMs"] = 0
            result["cacheScope"] = "private"
        send(request_id, result)
    elif method == "tools/call":
        handle_tools_call(request_id, params, MODE)
    else:
        send(request_id, {})
