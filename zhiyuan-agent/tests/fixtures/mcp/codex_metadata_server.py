#!/usr/bin/env python3
"""MCP stdio fixture that reports the server-provided thread metadata."""

from __future__ import annotations

import json
import sys


def send(request_id, result) -> None:
    payload = {"jsonrpc": "2.0", "id": request_id, "result": result}
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    request_id = request.get("id")
    params = request.get("params") or {}
    if method == "initialize":
        send(
            request_id,
            {
                "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "codex-binding-fixture", "version": "0.1.0"},
            },
        )
    elif method == "notifications/initialized":
        continue
    elif method == "tools/list":
        send(
            request_id,
            {
                "tools": [
                    {
                        "name": "echo_binding",
                        "description": "Return trusted MCP metadata.",
                        "inputSchema": {"type": "object", "properties": {}},
                    }
                ]
            },
        )
    elif method == "tools/call":
        metadata = params.get("_meta") or {}
        arguments = params.get("arguments") or {}
        send(
            request_id,
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "binding": "trusted" if metadata.get("threadId") else "failed",
                                "thread_id": metadata.get("threadId"),
                                "model_identity_override": "ignored"
                                if any(
                                    key in arguments
                                    for key in ("threadId", "sessionId", "userId", "tenantId")
                                )
                                else "absent",
                                "arguments": arguments,
                            }
                        ),
                    }
                ],
                "isError": False,
            },
        )
    elif request_id is not None:
        send(request_id, {})
