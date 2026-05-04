#!/usr/bin/env python3
"""WebSocket 客户端测试脚本。"""

import asyncio
import json
import sys

try:
    import websockets
except ImportError:
    print("请先安装 websockets: pip install websockets")
    sys.exit(1)


async def test_chat():
    uri = "ws://localhost:8009/ws/chat"
    session_id = "test-session-001"

    async with websockets.connect(uri) as ws:
        print(f"已连接到 {uri}")

        # 第一轮对话
        msg1 = {
            "type": "chat",
            "session_id": session_id,
            "user_id": "test-user",
            "content": "你好，我想咨询志愿填报",
        }
        await ws.send(json.dumps(msg1))
        print(f"\n发送: {msg1['content']}")

        resp1 = await ws.recv()
        data1 = json.loads(resp1)
        print(f"收到: {data1['content']}\n")

        # 第二轮对话
        msg2 = {
            "type": "chat",
            "session_id": session_id,
            "user_id": "test-user",
            "content": "我考了620分，理科，在山东省",
        }
        await ws.send(json.dumps(msg2))
        print(f"发送: {msg2['content']}")

        resp2 = await ws.recv()
        data2 = json.loads(resp2)
        print(f"收到: {data2['content']}\n")


if __name__ == "__main__":
    asyncio.run(test_chat())
