#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import time


def send(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}
    if method == "initialized":
        continue
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": request_id, "result": {"userAgent": "fake"}})
    elif method == "thread/start":
        send({"jsonrpc": "2.0", "method": "thread/started", "params": {"threadId": "thr_test"}})
        send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"thread": {"id": "thr_test", "ephemeral": True}, "received": params},
            }
        )
    elif method == "thread/resume":
        send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"thread": {"id": params.get("threadId", "thr_test")}},
            }
        )
    elif method == "thread/inject_items":
        send({"jsonrpc": "2.0", "id": request_id, "result": {}})
    elif method == "turn/start":
        send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"turn": {"id": "turn_test", "status": "inProgress"}, "received": params},
            }
        )
        send(
            {
                "jsonrpc": "2.0",
                "method": "item/agentMessage/delta",
                "params": {"threadId": params.get("threadId"), "turnId": "turn_test", "delta": "已收到"},
            }
        )
        send(
            {
                "jsonrpc": "2.0",
                "method": "turn/completed",
                "params": {"threadId": params.get("threadId"), "turn": {"id": "turn_test", "status": "completed"}},
            }
        )
    elif method in {"turn/steer", "turn/interrupt"}:
        send({"jsonrpc": "2.0", "id": request_id, "result": {}})
    elif method == "test/echo":
        send({"jsonrpc": "2.0", "id": request_id, "result": params})
    elif method == "test/error":
        send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32000, "message": "requested failure"},
            }
        )
    elif method == "test/hang":
        time.sleep(10)
    elif method == "test/exit":
        send({"jsonrpc": "2.0", "id": request_id, "result": {}})
        raise SystemExit(0)
    else:
        send({"jsonrpc": "2.0", "id": request_id, "result": {}})
