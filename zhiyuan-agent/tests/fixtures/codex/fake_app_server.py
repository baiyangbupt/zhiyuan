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
