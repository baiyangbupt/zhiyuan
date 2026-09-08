from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.harness.binding import ThreadBinding
from app.mcp_server.context import (
    ThreadBindingRegistry,
    TrustedContextError,
    extract_trusted_thread_id,
)


class _RequestContext:
    def __init__(self, metadata):
        self.meta = metadata


class _Server:
    def __init__(self, metadata):
        self.request_context = _RequestContext(metadata)


def test_trusted_thread_id_comes_from_mcp_metadata() -> None:
    assert extract_trusted_thread_id(_Server({"threadId": "thr-server"})) == "thr-server"
    with pytest.raises(TrustedContextError, match="thread_metadata_missing"):
        extract_trusted_thread_id(_Server({}))


@pytest.mark.asyncio
async def test_registry_resolves_backend_context_using_stored_handle(monkeypatch, tmp_path) -> None:
    registry = ThreadBindingRegistry(str(tmp_path / "bindings.sqlite3"))
    binding = ThreadBinding(
        thread_id="thr-server",
        tenant_id="1",
        session_id="2",
        user_id="3",
        allowed_capabilities=frozenset({"catalog_read"}),
        opaque_handle="opaque-handle",
    )
    registry.store(
        binding,
        expires_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
    )
    captured = {}

    async def resolve(tenant_id, payload):
        captured["tenant_id"] = tenant_id
        captured["payload"] = payload
        return {
            "code": 0,
            "data": {
                "threadId": "thr-server",
                "chatSessionId": 2,
                "userId": 3,
                "allowedCapabilities": ["catalog_read"],
            },
        }

    monkeypatch.setattr("app.mcp_server.context.internal_client.resolve_codex_thread_binding", resolve)
    resolved = await registry.resolve(thread_id="thr-server", capability="catalog_read")

    assert resolved.thread_id == "thr-server"
    assert captured == {
        "tenant_id": 1,
        "payload": {
            "chatSessionId": 2,
            "threadId": "thr-server",
            "handle": "opaque-handle",
            "capability": "catalog_read",
        },
    }


@pytest.mark.asyncio
async def test_expired_registry_binding_is_rejected_before_backend_call(tmp_path) -> None:
    registry = ThreadBindingRegistry(str(tmp_path / "bindings.sqlite3"))
    registry.store(
        ThreadBinding(
            thread_id="thr-expired",
            tenant_id="1",
            session_id="2",
            user_id="3",
            allowed_capabilities=frozenset({"catalog_read"}),
            opaque_handle="expired-handle",
        ),
        expires_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
    )

    with pytest.raises(TrustedContextError, match="binding_expired"):
        await registry.resolve(thread_id="thr-expired", capability="catalog_read")
