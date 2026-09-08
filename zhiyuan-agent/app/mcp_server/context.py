from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from app.harness.binding import ThreadBinding
from app.util import internal_client


class TrustedContextError(RuntimeError):
    """Raised when a MCP request cannot be mapped to a valid gateway binding."""


@dataclass(frozen=True)
class TrustedToolContext:
    """Compatibility view of a binding with model-controlled identity removed."""

    thread_id: str
    tenant_id: str
    session_id: str
    user_id: str
    admission_mode: str
    allowed_capabilities: frozenset[str]
    model_identity_override: str = ""

    @classmethod
    def from_binding(cls, binding: ThreadBinding) -> "TrustedToolContext":
        context = binding.context()
        return cls(
            thread_id=context.thread_id,
            tenant_id=context.tenant_id,
            session_id=context.session_id,
            user_id=context.user_id,
            admission_mode=context.admission_mode,
            allowed_capabilities=context.allowed_capabilities,
        )

    def with_model_arguments(self, payload: object) -> "TrustedToolContext":
        if not isinstance(payload, dict):
            raise TrustedContextError("invalid_model_payload")
        identity_keys = {"threadId", "tenantId", "sessionId", "userId"}
        return replace(
            self,
            model_identity_override="ignored" if identity_keys.intersection(payload) else "",
        )


class ThreadBindingRegistry:
    """Small local registry shared only by the Gateway and its stdio MCP child."""

    def __init__(self, path: str) -> None:
        if not path:
            raise ValueError("CODEX_APP_SERVER_BINDING_REGISTRY_PATH is required")
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def store(self, binding: ThreadBinding, *, expires_at: str) -> None:
        payload = json.dumps(sorted(binding.allowed_capabilities), ensure_ascii=False)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO codex_thread_binding_registry
                    (thread_id, tenant_id, session_id, user_id, capabilities, admission_mode, handle, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    binding.thread_id,
                    binding.tenant_id,
                    binding.session_id,
                    binding.user_id,
                    payload,
                    binding.admission_mode,
                    binding.opaque_handle or "",
                    expires_at,
                ),
            )

    async def resolve(self, *, thread_id: str, capability: str) -> ThreadBinding:
        row = self._load(thread_id)
        if row is None:
            raise TrustedContextError("binding_not_found")
        if _is_expired(row[7]):
            raise TrustedContextError("binding_expired")
        try:
            response = await internal_client.resolve_codex_thread_binding(
                int(row[1]),
                {
                    "chatSessionId": int(row[2]),
                    "threadId": thread_id,
                    "handle": row[6],
                    "capability": capability,
                },
            )
        except (TypeError, ValueError) as exc:
            raise TrustedContextError("binding_identity_invalid") from exc
        data = (response or {}).get("data") or {}
        if (response or {}).get("code") not in (None, 0) or not data:
            raise TrustedContextError("binding_resolution_failed")
        return ThreadBinding(
            thread_id=str(data.get("threadId") or thread_id),
            tenant_id=str(row[1]),
            session_id=str(data.get("chatSessionId") or row[2]),
            user_id=str(data.get("userId") or row[3]),
            allowed_capabilities=frozenset(data.get("allowedCapabilities") or json.loads(row[4])),
            admission_mode=row[5],
            opaque_handle=row[6],
        )

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS codex_thread_binding_registry (
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
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def _load(self, thread_id: str) -> tuple[str, ...] | None:
        with self._connect() as connection:
            return connection.execute(
                """
                SELECT thread_id, tenant_id, session_id, user_id, capabilities,
                       admission_mode, handle, expires_at
                FROM codex_thread_binding_registry WHERE thread_id = ?
                """,
                (thread_id,),
            ).fetchone()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)


def extract_trusted_thread_id(server: object) -> str:
    request_context = getattr(server, "request_context")
    metadata = getattr(request_context, "meta", None) or {}
    return extract_trusted_thread_id_from_metadata(metadata)


def extract_trusted_thread_id_from_metadata(metadata: object) -> str:
    thread_id = metadata.get("threadId") if isinstance(metadata, dict) else None
    if not isinstance(thread_id, str) or not thread_id:
        raise TrustedContextError("thread_metadata_missing")
    return thread_id


def _is_expired(value: str) -> bool:
    try:
        expiry = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return True
    return expiry <= datetime.now(timezone.utc)
