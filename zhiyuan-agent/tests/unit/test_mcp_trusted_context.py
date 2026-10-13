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


# ── 恢复兜底：本会话最近登记过的 thread（不看 TTL） ──────────────────


def _binding(thread_id: str, *, tenant_id: str = "1", session_id: str = "2") -> ThreadBinding:
    return ThreadBinding(
        thread_id=thread_id,
        tenant_id=tenant_id,
        session_id=session_id,
        user_id="3",
        allowed_capabilities=frozenset({"catalog_read"}),
        opaque_handle=f"handle-{thread_id}",
        snapshot_version=7,
    )


def test_latest_for_session_returns_the_most_recently_stored_thread(tmp_path) -> None:
    """一个会话重建过多个 thread 时，要拿**最近登记**的那个。

    老的那个即使 TTL 没过期也不该被选中——它对应的 thread 已经被替换了。
    """
    registry = ThreadBindingRegistry(str(tmp_path / "bindings.sqlite3"))
    future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()

    registry.store(_binding("thr-old"), expires_at=future)
    registry.store(_binding("thr-new"), expires_at=future)

    latest = registry.latest_for_session("1", "2")

    assert latest is not None
    assert latest["threadId"] == "thr-new"
    assert latest["tenantId"] == "1"
    assert latest["chatSessionId"] == "2"
    assert latest["allowedCapabilities"] == ["catalog_read"]


def test_latest_for_session_ignores_expiry_and_is_tenant_scoped(tmp_path) -> None:
    """恢复查询**不看 expires_at**（这正是它存在的理由），但身份边界照旧严格。

    过期的那行恰恰是我们要找的（进程重启晚过 TTL 的场景）；跨租户的绝不能命中。
    """
    registry = ThreadBindingRegistry(str(tmp_path / "bindings.sqlite3"))
    expired = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

    registry.store(_binding("thr-expired", tenant_id="1", session_id="42"), expires_at=expired)
    registry.store(_binding("thr-other-tenant", tenant_id="2", session_id="42"), expires_at=expired)

    assert registry.latest_for_session("1", "42")["threadId"] == "thr-expired"
    assert registry.latest_for_session("2", "42")["threadId"] == "thr-other-tenant"
    assert registry.latest_for_session("1", "43") is None


def test_latest_for_session_works_on_a_legacy_table_without_updated_at(tmp_path) -> None:
    """老库升级：补 updated_at 列之后，老行（NULL）仍能被兜底查询找到。"""
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
                expires_at TEXT NOT NULL,
                snapshot_version INTEGER
            )
            """
        )
        connection.execute(
            """
            INSERT INTO codex_thread_binding_registry
                (thread_id, tenant_id, session_id, user_id, capabilities, admission_mode,
                 handle, expires_at, snapshot_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "thr-legacy",
                "1",
                "42",
                "3",
                '["catalog_read"]',
                "major",
                "legacy-handle",
                (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
                1,
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

    assert "updated_at" in columns
    assert registry.latest_for_session("1", "42")["threadId"] == "thr-legacy"


def test_store_refreshes_updated_at_so_a_reused_session_prefers_the_new_thread(tmp_path) -> None:
    """重新登记（同 thread 再来一回合）会把 updated_at 推到最新：

    会话换了 thread 之后，"最近"必须跟着换——顺序错了就会回到一个已经死掉的 thread。
    """
    registry = ThreadBindingRegistry(str(tmp_path / "bindings.sqlite3"))
    future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()

    registry.store(_binding("thr-first"), expires_at=future)
    registry.store(_binding("thr-second"), expires_at=future)
    registry.store(_binding("thr-first"), expires_at=future)  # 第一本又跑了新回合

    assert registry.latest_for_session("1", "2")["threadId"] == "thr-first"
