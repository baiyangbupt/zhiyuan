#!/usr/bin/env python3
"""最小 app-server 替身：只回放协议形状，不实现任何 Codex 语义。

它存在的理由是让上层能在**不启动真实二进制**的前提下测协议路径。
因此这里每加一个形状，都必须与真实二进制实际发出的形状一致——
形状从真实录制里抄，不从调用方的期望里编。
"""
from __future__ import annotations

import json
import sys
import time

# 服务端→客户端请求的 id 空间与客户端→服务端请求刻意错开，
# 这样测试能一眼看出"回包用错了 id"这种错误。
_server_request_seq = {"n": 9000}
_pending_server_requests: dict[int, dict] = {}
_counters: dict[str, int] = {"turnStarts": 0, "threadStarts": 0}
_gate: dict[str, object] = {
    "armed": False,
    "open": True,
    "turn_id": "turn_test",
    "thread_id": "thr_test",
}
# 恢复失败的两个形状，抄自真实二进制实测（codex-cli 0.155.1，2026-09-21）：
#   no_rollout   → -32600 "no rollout found for thread id <id>"（thread 没有 rollout）
#   incompatible → -32000，**不是** -32600：用它来钉住"只有认得出的那种才重建"
_resume: dict[str, object] = {"mode": "ok"}
# 进程内的 thread 表。真实二进制只在**本进程** start/resume 过的 thread 上跑回合：
# `turn_processor.rs` 的 `load_thread()` 查 `thread_manager.get_thread()`，查不到回
# `-32600 thread not found: <id>`（codex-rs 源码，2026-09-21 核对）。
# 替身过去对任何 id 都放行，于是"把死进程的 threadId 交给新进程"在替身上永远是绿的
# ——而那正是重拉之后每轮都失败的成因。
_threads: set[str] = set()
# 这些方法都要求 thread 在本进程里加载过；其余方法（thread/start、thread/resume…）
# 正是让它进入进程表的入口，不受这条约束。
_THREAD_SCOPED_METHODS = {"thread/inject_items", "turn/start", "turn/steer", "turn/interrupt"}


def _guard_unknown_thread(method: str, request_id: object, params: dict) -> bool:
    """thread 不在本进程里就回 `-32600 thread not found`。返回 True = 已回错，跳过。"""
    if method not in _THREAD_SCOPED_METHODS:
        return False
    thread_id = str(params.get("threadId") or "")
    if thread_id in _threads:
        return False
    send(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32600, "message": f"thread not found: {thread_id}"},
        }
    )
    return True


def send(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def send_server_request(method: str, params: dict) -> int:
    """发出一个带 id 的 server→client 请求，并记住它等待回包。"""
    _server_request_seq["n"] += 1
    request_id = _server_request_seq["n"]
    _pending_server_requests[request_id] = {"method": method}
    send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
    return request_id


def emit_agent_message(thread_id: str, turn_id: str) -> None:
    """发一条带结构化输出的 agentMessage。

    终态里没有输出时上层会去"修复输出"（再开一轮模型），测试就会卡在那里——
    所以替身也必须给出合法输出，否则测的不是闸门而是修复路径。
    """
    text = json.dumps(
        {"responseType": "text", "message": "闸门放行后的答案", "executionStatus": "completed"},
        ensure_ascii=False,
    )
    send(
        {
            "jsonrpc": "2.0",
            "method": "item/completed",
            "params": {
                "threadId": thread_id,
                "turnId": turn_id,
                "item": {"id": "msg_gated", "type": "agentMessage", "text": text},
            },
        }
    )


def emit_nested_mcp_item(*, item_id: str, tool: str, arguments: dict) -> None:
    """item/started 与 item/completed：item 嵌在 params 里，不是顶层字段。"""
    base = {"threadId": "thr_test", "turnId": "turn_test"}
    send(
        {
            "jsonrpc": "2.0",
            "method": "item/started",
            "params": {
                **base,
                "item": {
                    "id": item_id,
                    "type": "mcpToolCall",
                    "server": "zhiyuan_domain",
                    "tool": tool,
                    "status": "inProgress",
                    "arguments": arguments,
                },
            },
        }
    )
    send(
        {
            "jsonrpc": "2.0",
            "method": "item/completed",
            "params": {
                **base,
                "item": {
                    "id": item_id,
                    "type": "mcpToolCall",
                    "server": "zhiyuan_domain",
                    "tool": tool,
                    "status": "completed",
                    "result": {"content": [{"type": "text", "text": "{}"}]},
                },
            },
        }
    )


QUESTIONS = [
    {
        "id": "major",
        "header": "专业范围",
        "question": "你指哪一种？",
        "isOther": True,
        "isSecret": False,
        "options": [
            {"label": "计算机类", "description": "包含多个专业"},
            {"label": "计算机科学与技术", "description": "具体本科专业"},
        ],
    }
]

# 与真实二进制一致的 elicitation 形状：mode/requestedSchema 在 params 顶层。
ELICITATION_SCHEMA = {
    "type": "object",
    "properties": {"confirm": {"type": "boolean", "title": "确认"}},
    "required": ["confirm"],
}


for line in sys.stdin:
    try:
        message = json.loads(line)
    except json.JSONDecodeError:
        continue
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}
    if _guard_unknown_thread(str(method), request_id, params):
        continue

    # 客户端对我们先前发出的 server→client 请求的应答。
    # 回包没有 method，只有 id + result/error。
    if method is None and request_id in _pending_server_requests:
        record = _pending_server_requests.pop(request_id)
        send(
            {
                "jsonrpc": "2.0",
                "method": "test/server_request_answered",
                "params": {
                    "requestId": request_id,
                    "method": record["method"],
                    "result": message.get("result"),
                    "error": message.get("error"),
                },
            }
        )
        continue

    if method == "initialized":
        continue
    if method == "initialize":
        # 回显参数，使测试能断言"客户端到底声明了什么能力"。
        send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"userAgent": "fake", "received": params},
            }
        )
    elif method == "thread/start":
        _counters["threadStarts"] += 1
        _threads.add("thr_test")
        send({"jsonrpc": "2.0", "method": "thread/started", "params": {"threadId": "thr_test"}})
        send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"thread": {"id": "thr_test", "ephemeral": True}, "received": params},
            }
        )
    elif method == "thread/resume":
        thread_id = params.get("threadId", "thr_test")
        mode = str(_resume["mode"])
        if mode == "no_rollout":
            send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32600,
                        "message": f"no rollout found for thread id {thread_id}",
                    },
                }
            )
        elif mode == "incompatible":
            send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32000, "message": "thread cannot be resumed"},
                }
            )
        else:
            _threads.add(thread_id)
            send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"thread": {"id": thread_id}},
                }
            )
    elif method == "thread/inject_items":
        send({"jsonrpc": "2.0", "id": request_id, "result": {}})
    elif method == "turn/start":
        _counters["turnStarts"] += 1
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
        if _gate["armed"]:
            # 预置闸门：发出工具进度后**不发终态**，等 test/release 或 turn/interrupt。
            _gate["open"] = False
            _gate["turn_id"] = "turn_test"
            _gate["thread_id"] = str(params.get("threadId") or "thr_test")
            emit_nested_mcp_item(
                item_id="gated-item",
                tool=str(params.get("tool") or "admission.get_history"),
                arguments={"private": "do-not-display"},
            )
        else:
            send(
                {
                    "jsonrpc": "2.0",
                    "method": "turn/completed",
                    "params": {"threadId": params.get("threadId"), "turn": {"id": "turn_test", "status": "completed"}},
                }
            )
    elif method == "test/stats":
        send({"jsonrpc": "2.0", "id": request_id, "result": dict(_counters)})
    elif method == "test/arm_resume":
        _resume["mode"] = str(params.get("mode") or "ok")
        send({"jsonrpc": "2.0", "id": request_id, "result": {"mode": _resume["mode"]}})
    elif method == "test/arm_gate":
        _gate["armed"] = True
        send({"jsonrpc": "2.0", "id": request_id, "result": {"armed": True}})
    elif method == "test/gated_turn":
        # 闸门：发出进度后**保持回合活动**，直到收到 test/release。
        # 这样测试才能在终态之前断言"前端已经看到了东西"——
        # 比最终 events 数量有意义得多。
        _gate["open"] = False
        _gate["turn_id"] = str(params.get("turnId") or "turn_test")
        _gate["thread_id"] = str(params.get("threadId") or "thr_test")
        send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"turn": {"id": _gate["turn_id"], "status": "inProgress"}, "received": params},
            }
        )
        emit_nested_mcp_item(
            item_id="gated-item",
            tool=str(params.get("tool") or "admission.get_history"),
            arguments={"private": "do-not-display"},
        )
    elif method == "test/release":
        _gate["open"] = True
        send({"jsonrpc": "2.0", "id": request_id, "result": {"released": True}})
        emit_agent_message(str(_gate["thread_id"]), str(_gate["turn_id"]))
        send(
            {
                "jsonrpc": "2.0",
                "method": "turn/completed",
                "params": {
                    "threadId": _gate["thread_id"],
                    "turn": {"id": _gate["turn_id"], "status": "completed"},
                },
            }
        )
    elif method in {"turn/steer", "turn/interrupt"}:
        # 被中断时也要给出终态，否则等待方会一直等到自己的超时。
        if method == "turn/interrupt" and not _gate["open"]:
            _gate["open"] = True
            send(
                {
                    "jsonrpc": "2.0",
                    "method": "turn/completed",
                    "params": {
                        "threadId": _gate["thread_id"],
                        "turn": {"id": _gate["turn_id"], "status": "interrupted"},
                    },
                }
            )
        send({"jsonrpc": "2.0", "id": request_id, "result": {}})
    elif method == "test/big_notification":
        # 大通知：真实二进制在工具结果、历史页很大时会发这种（实测 2026-09-21：
        # 一次"神秘死亡"对应的 rollout 记录是 229 KiB）。它撑爆过 asyncio 默认的
        # 64 KiB 行上限，而后果是**把活着的进程判成死的**。
        size = int(params.get("bytes") or 70000)
        send(
            {
                "jsonrpc": "2.0",
                "method": "item/agentMessage/delta",
                "params": {"threadId": "thr_test", "turnId": "turn_test", "delta": "x" * size},
            }
        )
        send({"jsonrpc": "2.0", "id": request_id, "result": {"bytes": size}})
    elif method == "test/bad_bytes":
        # 坏字节行：真实二进制不该发，但"不该发"不是协议约束。它以前会带走整个读循环。
        # 坏字节**且**不是 JSON：换掉坏字节之后它仍然读不成 JSON，
        # 于是走"忽略这一行"的分支（而不是被解码异常带走整个读循环）。
        sys.stdout.buffer.write(b'\xff\xfe not-json \xff\n')
        sys.stdout.buffer.flush()
        send({"jsonrpc": "2.0", "id": request_id, "result": {"ok": True}})
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
    elif method == "test/exit_pending":
        # 不回应答直接退出：用于验证挂起请求不会永远悬着。
        raise SystemExit(0)
    elif method == "test/request_user_input":
        send_server_request(
            "item/tool/requestUserInput",
            {
                "threadId": params.get("threadId", "thr_test"),
                "turnId": params.get("turnId", "turn_test"),
                "itemId": "call_1",
                "questions": QUESTIONS,
                "isBlocking": False,
                "autoResolutionMs": None,
            },
        )
        send({"jsonrpc": "2.0", "id": request_id, "result": {"sent": True}})
    elif method == "test/elicitation":
        send_server_request(
            "mcpServer/elicitation/request",
            {
                "threadId": params.get("threadId", "thr_test"),
                "turnId": params.get("turnId", "turn_test"),
                "serverName": "zhiyuan_domain",
                "mode": "form",
                "message": "请确认",
                "requestedSchema": ELICITATION_SCHEMA,
            },
        )
        send({"jsonrpc": "2.0", "id": request_id, "result": {"sent": True}})
    elif method == "test/nested_mcp_item":
        emit_nested_mcp_item(
            item_id=str(params.get("itemId") or "item_1"),
            tool=str(params.get("tool") or "admission.get_history"),
            arguments=params.get("arguments") or {"private": "do-not-display"},
        )
        send({"jsonrpc": "2.0", "id": request_id, "result": {}})
    else:
        send({"jsonrpc": "2.0", "id": request_id, "result": {}})
