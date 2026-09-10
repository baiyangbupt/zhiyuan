#!/usr/bin/env python3
"""用于本地验证 /ws/chat 的最小 WebSocket 客户端。"""

from __future__ import annotations

import argparse
import asyncio
import json

import websockets


def parse_conversation_action(value: str) -> dict:
    try:
        action = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError("--conversation-action 必须是 JSON 对象") from exc
    if not isinstance(action, dict):
        raise argparse.ArgumentTypeError("--conversation-action 必须是 JSON 对象")
    return action


async def run(args: argparse.Namespace) -> None:
    action = getattr(args, "conversation_action", None)
    message = {
        "type": "pendingConfirmation" if action is not None else "chat",
        "tenantId": args.tenant_id,
        "sessionId": args.session_id,
        "userId": args.user_id,
        "content": args.message or "",
    }
    if action is not None:
        message["conversationAction"] = action
    async with websockets.connect(args.url, open_timeout=10, close_timeout=5) as socket:
        await socket.send(json.dumps(message, ensure_ascii=False))
        while True:
            raw = await asyncio.wait_for(socket.recv(), timeout=args.timeout)
            print(raw)
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if payload.get("type") in {"reply", "error", "recoverable.error"}:
                return


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="ws://127.0.0.1:8000/ws/chat")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--user-id", required=True)
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--message")
    input_group.add_argument("--conversation-action", type=parse_conversation_action)
    parser.add_argument("--timeout", type=float, default=120.0)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
