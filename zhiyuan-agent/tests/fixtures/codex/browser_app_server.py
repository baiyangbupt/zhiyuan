#!/usr/bin/env python3
"""合同栈用的**带闸门**假 Codex app-server（Task C4 ②）。

与 `fake_app_server.py` 的关系 ✓：**协议形状照抄它** ✓（jsonrpc 2.0 ✓、item 嵌在 `params` 里 ✓、
delta 用 `item/agentMessage/delta` ✓），但**它是独立实现** ✓——那个文件是脚本、import 即读 stdin ✗，
而 C4 要的是"**经控制服务**放行" ✓（它那边是 `test/release` 走 stdio ✓）。改它又会波及
一堆集成测试 ✗，所以另起一份 ✓。

它只做流式用例需要的那点事 ✓：

1. `turn/start` → 回 result ✓ → 发一条 delta ✓ → 发一条 MCP 工具进度 ✓ → **就停住不发终态** ✗✓；
2. 之后**轮询控制服务** `GET /gates/{turnId}` ✓，`released` 为真才发 `agentMessage` + `turn/completed` ✓；
3. `turn/interrupt` → 发**真中断**的终态 ✓（`status: interrupted` ✓，绝不发假的 completed ✗）；
4. 回合号优先用客户端给的 ✓（任务书："客户端测试注入固定下一次 turnId（仅测试构建）" ✓）——
   否则 `data-turn-id` 那类断言无从谈起 ✓。

控制服务不可达时**大声失败** ✗（不许默默把终态发了 ✓）：那会把"没放行"测成"放行了" ✗。
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any

CONTROL_BASE = os.environ.get("CODEX_BROWSER_CONTROL_BASE", "http://127.0.0.1:18293")
RUN_ID = os.environ.get("CODEX_BROWSER_RUN_ID", "browser-run")
# 闸门等待上限 ✓：到点仍没放行就**大声失败** ✗（把"卡住"和"通过"分开 ✓）。
RELEASE_TIMEOUT_SECONDS = float(os.environ.get("CODEX_BROWSER_RELEASE_TIMEOUT", "60"))
# 进度里报的工具名 ✓：UI 会把它映成"历年录取"这类字样 ✓（C4 的流式用例就断言这个 ✓）。
PROGRESS_TOOL = os.environ.get("CODEX_BROWSER_PROGRESS_TOOL", "admission.get_history")

_threads: set[str] = set()
_turn_counter = 0
# 终态**只发一次** ✓（中断与放行可能同时到 ✓）：两个集合都在锁里改 ✓。
_finished_turns: set[str] = set()
_state_lock = threading.Lock()
# stdout 会被主线程与等待线程同时写 ✗——不加锁会写出半行 JSON ✗✗（读方直接解析失败 ✓）。
_send_lock = threading.Lock()


def send(payload: dict) -> None:
    with _send_lock:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def _finish_once(thread_id: str, turn_id: str, *, interrupted: bool) -> None:
    """终态**最多一条** ✓——中断先到就不再补"放行后的答案" ✓✓。"""
    with _state_lock:
        if turn_id in _finished_turns:
            return
        _finished_turns.add(turn_id)
    _emit_final(thread_id, turn_id, interrupted=interrupted)


def _control(method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(f"{CONTROL_BASE}{path}", data=data, method=method)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8") or "{}")


def _wait_for_release(turn_id: str) -> bool:
    """轮询控制服务 ✓。返回 False = **超时**（调用方要按"没放行"处理 ✓）。"""
    deadline = time.time() + RELEASE_TIMEOUT_SECONDS
    while time.time() < deadline:
        status, payload = _control("GET", f"/gates/{turn_id}")
        if status == 200 and payload.get("released"):
            return True
        time.sleep(0.05)
    return False


def _emit_progress(thread_id: str, turn_id: str) -> None:
    send({
        "jsonrpc": "2.0",
        "method": "item/started",
        "params": {
            "threadId": thread_id, "turnId": turn_id,
            "item": {"id": f"progress-{turn_id}", "type": "mcpToolCall", "server": "zhiyuan_domain",
                     "tool": PROGRESS_TOOL, "status": "inProgress",
                     "arguments": {"prompt": "查询测试学校近三年录取位次"}},
        },
    })


def _emit_final(thread_id: str, turn_id: str, *, interrupted: bool) -> None:
    if interrupted:
        send({"jsonrpc": "2.0", "method": "turn/completed",
              "params": {"threadId": thread_id, "turn": {"id": turn_id, "status": "interrupted"}}})
        return
    text = json.dumps({"responseType": "text", "message": "闸门放行后的答案",
                       "executionStatus": "completed"}, ensure_ascii=False)
    send({"jsonrpc": "2.0", "method": "item/completed",
          "params": {"threadId": thread_id, "turnId": turn_id,
                     "item": {"id": f"msg-{turn_id}", "type": "agentMessage", "text": text}}})
    send({"jsonrpc": "2.0", "method": "turn/completed",
          "params": {"threadId": thread_id, "turn": {"id": turn_id, "status": "completed"}}})


def _gated_finish(thread_id: str, turn_id: str) -> None:
    if not _wait_for_release(turn_id):
        # 超时 = **没放行** ✗：绝不能顺手把终态发了 ✓（否则"卡住"会被测成"通过" ✗）。
        send({"jsonrpc": "2.0", "method": "test/release_timeout",
              "params": {"turnId": turn_id, "waitedSeconds": RELEASE_TIMEOUT_SECONDS}})
        return
    _finish_once(thread_id, turn_id, interrupted=False)


def handle(message: dict) -> None:
    global _turn_counter
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    if method == "thread/start":
        thread_id = str(params.get("threadId") or f"thr_{len(_threads) + 1}")
        _threads.add(thread_id)
        send({"jsonrpc": "2.0", "id": request_id, "result": {"thread": {"id": thread_id}}})
        return
    if method == "thread/resume":
        thread_id = str(params.get("threadId") or "thr_1")
        if thread_id not in _threads:
            send({"jsonrpc": "2.0", "id": request_id,
                  "error": {"code": -32600, "message": f"thread not found: {thread_id}"}})
            return
        send({"jsonrpc": "2.0", "id": request_id, "result": {"thread": {"id": thread_id}}})
        return
    if method == "turn/start":
        _turn_counter += 1
        thread_id = str(params.get("threadId") or "thr_1")
        _threads.add(thread_id)
        # 客户端（测试构建 ✓）给了回合号就用它 ✓——没有才自己编 ✓。
        turn_id = str(params.get("turnId") or params.get("clientTurnId") or f"turn_{_turn_counter}")
        # 先在控制服务**登记**这个闸门 ✓（reset 才能按 runId 清到它 ✓）。
        _control("POST", "/gates", {"runId": RUN_ID, "turnId": turn_id})
        send({"jsonrpc": "2.0", "id": request_id,
              "result": {"turn": {"id": turn_id, "status": "inProgress"}, "received": params}})
        send({"jsonrpc": "2.0", "method": "item/agentMessage/delta",
              "params": {"threadId": thread_id, "turnId": turn_id, "delta": "已收到"}})
        _emit_progress(thread_id, turn_id)
        # **等待必须在后台** ✓：主循环还要继续读 stdin ✓——否则 `turn/interrupt` 永远到不了 ✗
        #（这是测试当场抓出来的真缺陷 ✓，不是测试挑剔 ✓）。
        threading.Thread(target=_gated_finish, args=(thread_id, turn_id), daemon=True).start()
        return
    if method == "turn/interrupt":
        thread_id = str(params.get("threadId") or "thr_1")
        turn_id = str(params.get("turnId") or f"turn_{_turn_counter}")
        send({"jsonrpc": "2.0", "id": request_id, "result": {}})
        _finish_once(thread_id, turn_id, interrupted=True)
        return
    if request_id is not None:
        send({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"method not found: {method}"}})


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if message.get("method") is None:
            continue  # 对 server→client 请求的应答 ✓：合同栈不需要 ✓
        handle(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
