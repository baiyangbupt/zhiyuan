from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3

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
        snapshot_version=42,
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
    assert resolved.snapshot_version == 42


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


def test_registry_migrates_legacy_rows_without_assuming_a_snapshot_version(tmp_path) -> None:
    path = tmp_path / "bindings.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE codex_thread_binding_registry (
                thread_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                capabilities TEXT NOT NULL,
                admission_mode TEXT NOT NULL,
                handle TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO codex_thread_binding_registry
                (thread_id, tenant_id, session_id, user_id, capabilities, admission_mode, handle, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "thr-legacy",
                "1",
                "2",
                "3",
                '["catalog_read"]',
                "major",
                "legacy-handle",
                (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
            ),
        )

    registry = ThreadBindingRegistry(str(path))
    with sqlite3.connect(path) as connection:
        columns = {
            column[1]
            for column in connection.execute(
                "PRAGMA table_info(codex_thread_binding_registry)"
            ).fetchall()
        }
        row = connection.execute(
            "SELECT snapshot_version FROM codex_thread_binding_registry WHERE thread_id = ?",
            ("thr-legacy",),
        ).fetchone()

    assert "snapshot_version" in columns
    assert row == (None,)
