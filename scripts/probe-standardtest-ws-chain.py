"""P1 最短会话链（本机段）验证：取票 -> WS 101 -> 回合事件。

只打本机标准测试栈（18090 Java / 18091 Agent），Origin 用 Agent 白名单内的
http://127.0.0.1:3001。会话 900380 属用户 900001（tk=codex-local-test-token）。
"""
import asyncio
import json
import sys
import urllib.request
import urllib.error

import websockets
from websockets.exceptions import InvalidStatus

TICKET_URL = "http://127.0.0.1:18090/gaotu-assistant-bot/chat/1/conversation/ws-ticket"
WS_BASE = "ws://127.0.0.1:18091/ws/chat"
SESSION = int(sys.argv[1]) if len(sys.argv) > 1 else 900380
ORIGIN = "http://127.0.0.1:3001"
TENANT = "1"


def issue_ticket():
    body = json.dumps({"sessionId": SESSION, "botId": 1}).encode()
    req = urllib.request.Request(
        TICKET_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "tk": "codex-local-test-token",
            "pf": "WEB",
            "Origin": ORIGIN,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
        print(f"[ticket] http={resp.status} code={data.get('code')}")
        return (data.get("data") or {}).get("ticket")


async def negative_checks():
    # 1) 无票
    try:
        async with websockets.connect(
            f"{WS_BASE}?chatSessionId={SESSION}",
            additional_headers={"Origin": ORIGIN},
            open_timeout=10,
        ):
            print("[neg-1] no-ticket -> CONNECTED (!! 严重回归)")
    except InvalidStatus as e:
        print(f"[neg-1] no-ticket -> HTTP {e.response.status_code} (期望 403)")
    # 2) 错 Origin（白名单外），带票
    ticket = issue_ticket()
    try:
        async with websockets.connect(
            f"{WS_BASE}?chatSessionId={SESSION}&ticket={ticket}",
            additional_headers={"Origin": "https://evil.example.com"},
            open_timeout=10,
        ):
            print("[neg-2] wrong-origin -> CONNECTED (!! 严重回归)")
    except InvalidStatus as e:
        print(f"[neg-2] wrong-origin -> HTTP {e.response.status_code} (期望 403)")


async def positive_check():
    ticket = issue_ticket()
    url = f"{WS_BASE}?chatSessionId={SESSION}&ticket={ticket}"
    async with websockets.connect(
        url, additional_headers={"Origin": ORIGIN}, open_timeout=15
    ) as ws:
        print("[pos] WS CONNECTED (101 升级完成)")
        frame = {
            "type": "chat",
            "tenantId": TENANT,
            "sessionId": str(SESSION),
            "userId": "900001",
            "content": "你好，做一次链路连通性验证即可，请简短回复。",
        }
        await ws.send(json.dumps(frame, ensure_ascii=False))
        print("[pos] 已发送 chat 帧，等待回合事件……")

        types_seen = []
        deadline = asyncio.get_event_loop().time() + 120
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                print("[pos] 超时（120s）未收到终态")
                break
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                print("[pos] 超时（120s）未收到终态")
                break
            try:
                obj = json.loads(raw)
            except Exception:
                print(f"[pos] 非 JSON 帧: {str(raw)[:120]}")
                continue
            t = obj.get("type")
            payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
            types_seen.append(t)
            keys = ",".join(list(payload.keys())[:8])
            print(f"[pos] #{len(types_seen)} {t} keys=[{keys}]")
            if t == "assistant.completed":
                msg = payload.get("message") or obj.get("content") or ""
                print(f"[pos] assistant: {str(msg)[:200]}")
            if t == "turn.completed":
                print(f"[pos] 终态 payload: {json.dumps(payload, ensure_ascii=False)[:300]}")
                break
        print(f"[pos] 事件序列: {types_seen}")


async def main():
    await negative_checks()
    await positive_check()


if __name__ == "__main__":
    asyncio.run(main())
