from __future__ import annotations

import pytest

from app.util import internal_client


@pytest.mark.asyncio
async def test_register_codex_thread_binding_posts_scoped_payload(monkeypatch) -> None:
    calls = []

    async def post(*, endpoint, json_data, error_msg):
        calls.append((endpoint, json_data, error_msg))
        return {"code": 0, "data": {"threadId": "thr-1", "handle": "opaque"}}

    monkeypatch.setattr(internal_client.http_client, "post", post)

    response = await internal_client.register_codex_thread_binding(
        7,
        {
            "chatSessionId": 101,
            "userId": 202,
            "threadId": "thr-1",
            "handle": "opaque",
            "allowedCapabilities": ["catalog.search_schools"],
            "expiresAt": "2030-01-01T00:00:00Z",
        },
    )

    assert response["code"] == 0
    assert calls == [
        (
            "/gaotu-assistant-bot/inner/codex/7/thread-binding",
            {
                "chatSessionId": 101,
                "userId": 202,
                "threadId": "thr-1",
                "handle": "opaque",
                "allowedCapabilities": ["catalog.search_schools"],
                "expiresAt": "2030-01-01T00:00:00Z",
            },
            "注册 Codex thread binding 失败",
        )
    ]


@pytest.mark.asyncio
async def test_revoke_codex_thread_binding_uses_delete_endpoint(monkeypatch) -> None:
    calls = []

    async def delete(*, endpoint, params, error_msg):
        calls.append((endpoint, params, error_msg))
        return {"code": 0, "data": True}

    monkeypatch.setattr(internal_client.http_client, "delete", delete)

    response = await internal_client.revoke_codex_thread_binding(7, "thr-1")

    assert response["data"] is True
    assert calls == [
        (
            "/gaotu-assistant-bot/inner/codex/7/thread-binding",
            {"threadId": "thr-1"},
            "撤销 Codex thread binding 失败",
        )
    ]


@pytest.mark.asyncio
async def test_resolve_codex_thread_binding_posts_secret_server_context(monkeypatch) -> None:
    calls = []

    async def post(*, endpoint, json_data, error_msg):
        calls.append((endpoint, json_data, error_msg))
        return {
            "code": 0,
            "data": {
                "chatSessionId": 101,
                "userId": 202,
                "threadId": "thr-1",
                "allowedCapabilities": ["catalog.search_schools"],
            },
        }

    monkeypatch.setattr(internal_client.http_client, "post", post)

    response = await internal_client.resolve_codex_thread_binding(
        7,
        {
            "chatSessionId": 101,
            "threadId": "thr-1",
            "handle": "opaque",
            "capability": "catalog.search_schools",
        },
    )

    assert response["data"]["userId"] == 202
    assert calls == [
        (
            "/gaotu-assistant-bot/inner/codex/7/thread-binding/resolve",
            {
                "chatSessionId": 101,
                "threadId": "thr-1",
                "handle": "opaque",
                "capability": "catalog.search_schools",
            },
            "解析 Codex thread binding 失败",
        )
    ]


@pytest.mark.asyncio
async def test_get_current_codex_thread_binding_uses_current_endpoint(monkeypatch) -> None:
    """恢复用的查询：只要 (租户, 会话)，**不带 handle**。

    handle 是进程重启后丢掉的那样东西，所以这条查询的凭据只能是内部调用方身份；
    把它写成带 handle 的 resolve 会让恢复在真正需要它的时候用不了。
    """
    calls = []

    async def get(*, endpoint, params, error_msg, require_success=False):
        calls.append((endpoint, params, error_msg, require_success))
        return {"code": 0, "data": {"threadId": "thr-1", "chatSessionId": 101}}

    monkeypatch.setattr(internal_client.http_client, "get", get)

    response = await internal_client.get_current_codex_thread_binding(7, 101)

    assert response["data"]["threadId"] == "thr-1"
    assert calls == [
        (
            "/gaotu-assistant-bot/inner/codex/7/thread-binding/current",
            {"chatSessionId": 101},
            "查询 Codex thread binding 失败",
            True,
        )
    ]
