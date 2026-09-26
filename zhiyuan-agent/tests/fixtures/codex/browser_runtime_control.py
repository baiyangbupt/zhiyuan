#!/usr/bin/env python3
"""合同栈的**运行时控制服务**（Task C4）。

它只做三件事 ✓，都是给 e2e 用的：

    GET  /identity               → {"runtimeKind": "fake", ...}
    GET  /gates/{turnId}         → {"released": bool}（假 app-server **轮询**它 ✓）
    POST /gates/{turnId}/release → 放行这一回合的终态 ✓
    POST /runs/{runId}/reset     → **只清本次 runId 的闸门** ✓

三条硬约束 ✓：

1. **只监听 loopback** ✓（`127.0.0.1` ✓）：这个口子能让模型"停"在中间 ✓，
   绝不能对外 ✓（任务书：不开放该端口到 Nginx ✓）。绑不到 127.0.0.1 就拒 ✓。
2. **项目名不代表运行时** ✗（任务书原话 ✓）：真实/假由 `/identity` 的证据判 ✓，
   所以 `runtimeKind` 必须来自**这个服务自己** ✓，不能由被测方传参覆盖 ✓。
3. **reset 只清闸门** ✓：不碰别的状态 ✗（"只清本次闸门" ✓）——它连 run 记录都不删 ✓，
   只把动作记进内存 ✓。
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Mapping
from urllib.parse import urlparse

RUNTIME_KIND_FAKE = "fake"
CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = 18293


class GateRegistry:
    """闸门状态 ✓（进程内 ✓，只在合同栈用 ✓）。

    `released` 是**一次性的** ✓：放行过就不再拦 ✓（否则同一 turnId 复用会卡住 ✓）；
    `reset` 只清**指定 runId** 的闸门 ✓，其余 run 的状态原样保留 ✓。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._gates: dict[str, dict[str, Any]] = {}
        self._actions: list[dict[str, Any]] = []

    def register(self, run_id: str, turn_id: str) -> None:
        with self._lock:
            self._gates.setdefault(turn_id, {"runId": run_id, "released": False})

    def release(self, turn_id: str) -> bool:
        with self._lock:
            gate = self._gates.get(turn_id)
            if gate is None:
                return False
            gate["released"] = True
            self._actions.append({"action": "release", "turnId": turn_id, "at": time.time()})
            return True

    def is_released(self, turn_id: str) -> bool:
        with self._lock:
            gate = self._gates.get(turn_id)
            return bool(gate and gate["released"])

    def reset_run(self, run_id: str) -> int:
        """**只清这个 run 的闸门** ✓，返回清掉的条数 ✓。"""
        with self._lock:
            doomed = [key for key, gate in self._gates.items() if gate.get("runId") == run_id]
            for key in doomed:
                self._gates.pop(key, None)
            self._actions.append({"action": "reset", "runId": run_id, "cleared": len(doomed), "at": time.time()})
            return len(doomed)

    def actions(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._actions)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {key: dict(gate) for key, gate in self._gates.items()}


def build_handler(registry: GateRegistry) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: Any) -> None:  # 静音：e2e 日志里不需要每题一行的访问日志 ✓
            return

        def _send(self, status: int, payload: Mapping[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 —— http.server 的接口名 ✓
            path = urlparse(self.path).path
            if path == "/identity":
                # 证据由服务自己给 ✓：`runtimeKind` 不接受外部覆盖 ✗。
                self._send(200, {"runtimeKind": RUNTIME_KIND_FAKE, "controlPort": CONTROL_PORT})
                return
            if path.startswith("/gates/"):
                turn_id = path[len("/gates/"):]
                self._send(200, {"turnId": turn_id, "released": registry.is_released(turn_id)})
                return
            if path == "/gates":
                self._send(200, {"gates": registry.snapshot(), "actions": registry.actions()})
                return
            self._send(404, {"error": "not_found", "path": path})

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                self._send(400, {"error": "invalid_json"})
                return
            path = urlparse(self.path).path
            if path.startswith("/gates/") and path.endswith("/release"):
                turn_id = path[len("/gates/"):-len("/release")]
                if not registry.release(turn_id):
                    self._send(404, {"error": "unknown_turn", "turnId": turn_id})
                    return
                self._send(200, {"turnId": turn_id, "released": True})
                return
            if path == "/gates":
                registry.register(str(payload.get("runId") or ""), str(payload.get("turnId") or ""))
                self._send(200, {"registered": True})
                return
            if path.startswith("/runs/") and path.endswith("/reset"):
                run_id = path[len("/runs/"):-len("/reset")]
                cleared = registry.reset_run(run_id)
                self._send(200, {"runId": run_id, "cleared": cleared})
                return
            self._send(404, {"error": "not_found", "path": path})

    return Handler


def serve(host: str = CONTROL_HOST, port: int = CONTROL_PORT) -> ThreadingHTTPServer:
    """起控制服务 ✓——**只认 loopback** ✓（传别的地址直接拒 ✗）。"""
    if host != CONTROL_HOST:
        raise ValueError("控制服务只允许监听 %s（它能把模型停在中间 ✗，绝不能对外 ✓）" % CONTROL_HOST)
    registry = GateRegistry()
    server = ThreadingHTTPServer((host, port), build_handler(registry))
    server.registry = registry  # type: ignore[attr-defined]
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Browser-runtime control service (Task C4).")
    parser.add_argument("--host", default=CONTROL_HOST)
    parser.add_argument("--port", type=int, default=CONTROL_PORT)
    args = parser.parse_args(argv)
    server = serve(args.host, args.port)
    print(json.dumps({"control": "listening", "host": args.host, "port": args.port, "runtimeKind": RUNTIME_KIND_FAKE}))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
