import argparse
import asyncio
import json

import pytest

from scripts.local_ws_client import parse_conversation_action, run


class _Socket:
    def __init__(self):
        self.sent = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def send(self, value):
        self.sent.append(json.loads(value))

    async def recv(self):
        return json.dumps({"type": "reply", "content": "ok"})


def test_local_client_sends_native_ws_envelope(monkeypatch, capsys):
    socket = _Socket()
    monkeypatch.setattr("scripts.local_ws_client.websockets.connect", lambda *args, **kwargs: socket)
    asyncio.run(run(argparse.Namespace(
        url="ws://test", tenant_id="tenant-1", session_id="s-1", user_id="u-1", message="你好",
        conversation_action=None, timeout=1,
    )))
    assert socket.sent == [{"type": "chat", "tenantId": "tenant-1", "sessionId": "s-1", "userId": "u-1", "content": "你好"}]
    assert '"type": "reply"' in capsys.readouterr().out


def test_local_client_sends_structured_conversation_action(monkeypatch):
    socket = _Socket()
    monkeypatch.setattr("scripts.local_ws_client.websockets.connect", lambda *args, **kwargs: socket)

    asyncio.run(run(argparse.Namespace(
        url="ws://test", tenant_id="tenant-1", session_id="s-1", user_id="u-1", message=None,
        conversation_action={
            "actionType": "cancel_proposal",
            "proposalRef": "pending-1",
            "expectedSourceVersion": 7,
        }, timeout=1,
    )))

    assert socket.sent == [{
        "type": "pendingConfirmation",
        "tenantId": "tenant-1",
        "sessionId": "s-1",
        "userId": "u-1",
        "content": "",
        "conversationAction": {
            "actionType": "cancel_proposal",
            "proposalRef": "pending-1",
            "expectedSourceVersion": 7,
        },
    }]


def test_conversation_action_option_rejects_non_object_json():
    with pytest.raises(argparse.ArgumentTypeError):
        parse_conversation_action("[]")
