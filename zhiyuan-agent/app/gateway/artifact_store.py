from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import sqlite3
import time
from collections.abc import Callable, Iterable, Mapping
from contextlib import closing
from pathlib import Path
from typing import Any


class ArtifactStoreError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


_MAX_JSON_NESTING = 64


def _canonical(value: Any) -> str:
    # json.dumps recursion behaviour varies across Python versions. Bound the
    # accepted JSON shape explicitly rather than relying on RecursionError.
    # Iterators keep the validator stack proportional to depth, not row count.
    stack = [iter((value,))]
    while stack:
        try:
            item = next(stack[-1])
        except StopIteration:
            stack.pop()
            continue
        if isinstance(item, (Mapping, list, tuple)):
            if len(stack) > _MAX_JSON_NESTING:
                raise ValueError("artifact_json_too_deep")
            stack.append(iter(item.values() if isinstance(item, Mapping) else item))
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


_IDENTITY_FIELDS = (
    "tenantId", "sessionId", "artifactType", "stateVersion", "toolName", "paramsDigest", "payloadDigest",
)
_ROW_COLUMNS = "artifact_id, tenant_id, session_id, identity_digest, record_json, record_digest, expires_at"


class SqliteArtifactStore:
    def __init__(
        self, path: str, *, ttl_seconds: float = 86400,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not path or path == ":memory:":
            raise ValueError("artifact store requires a persistent path")
        if isinstance(ttl_seconds, bool) or not math.isfinite(ttl_seconds) or ttl_seconds <= 0:
            raise ValueError("artifact ttl must be positive and finite")
        self.path = Path(path).expanduser().resolve()
        self._ttl = float(ttl_seconds)
        self._clock = clock
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(descriptor)
            os.chmod(self.path, 0o600)
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS codex_artifact_issuance (
                    artifact_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, session_id TEXT NOT NULL,
                    identity_digest TEXT NOT NULL, record_json TEXT NOT NULL,
                    record_digest TEXT NOT NULL, expires_at REAL NOT NULL)"""
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_artifact_identity ON codex_artifact_issuance (identity_digest, expires_at)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_artifact_expiry ON codex_artifact_issuance (expires_at)"
                )
        except (OSError, sqlite3.Error):
            raise ArtifactStoreError("artifact_store_unavailable") from None

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.path), timeout=0.2)

    def _now(self) -> float:
        now = self._clock()
        if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now):
            raise ArtifactStoreError("artifact_store_unavailable")
        return float(now)

    @staticmethod
    def _validate_identity(record: Mapping[str, Any]) -> None:
        if record.get("artifactType") not in {"candidate", "comparison"}:
            raise ArtifactStoreError("artifact_invalid")
        version = record.get("stateVersion")
        if isinstance(version, bool) or not isinstance(version, int) or version < 0:
            raise ArtifactStoreError("artifact_invalid")
        for field in ("tenantId", "sessionId", "threadId", "toolName"):
            value = record.get(field)
            if not isinstance(value, str) or not value.strip() or len(value.encode("utf-8")) > 1024:
                raise ArtifactStoreError("artifact_invalid")

    def _decode(self, row: tuple[Any, ...]) -> dict[str, Any]:
        try:
            artifact_id, tenant, session, identity_digest, serialized, checksum, expiry = row
            if (
                not isinstance(serialized, str) or len(serialized.encode("utf-8")) > 16384
                or _digest(serialized) != checksum
            ):
                raise ValueError
            record = json.loads(serialized)
            self._validate_identity(record)
            identity = {field: record[field] for field in _IDENTITY_FIELDS}
            actual_identity = _digest(_canonical(identity))
            expected_id = "mcp_art_" + _digest(actual_identity + ":" + record["issuanceId"])
            issued = record["issuedAt"]
            expires = record["expiresAt"]
            if (
                actual_identity != identity_digest
                or expected_id != artifact_id or record["artifactId"] != artifact_id
                or record["tenantId"] != tenant or record["sessionId"] != session
                or isinstance(issued, bool) or not isinstance(issued, (int, float))
                or isinstance(expires, bool) or not isinstance(expires, (int, float))
                or not math.isfinite(issued) or not math.isfinite(expires)
                or expires != expiry or expires <= issued
            ):
                raise ValueError
            return record
        except (KeyError, TypeError, ValueError, AttributeError, RecursionError):
            raise ArtifactStoreError("artifact_invalid") from None

    def issue(
        self, *, tenant_id: str, session_id: str, thread_id: str,
        artifact_type: str, state_version: int, tool_name: str,
        arguments: Mapping[str, Any], payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        try:
            identity = {
                "tenantId": tenant_id, "sessionId": session_id, "artifactType": artifact_type,
                "stateVersion": state_version, "toolName": tool_name,
                "paramsDigest": _digest(_canonical(arguments)), "payloadDigest": _digest(_canonical(payload)),
            }
            self._validate_identity({**identity, "threadId": thread_id})
            identity_digest = _digest(_canonical(identity))
            now = self._now()
            expires = now + self._ttl
            if not math.isfinite(expires) or expires <= now:
                raise ArtifactStoreError("artifact_invalid")
            with closing(self._connect()) as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "DELETE FROM codex_artifact_issuance WHERE artifact_id IN "
                    "(SELECT artifact_id FROM codex_artifact_issuance WHERE expires_at <= ? ORDER BY expires_at LIMIT 128)",
                    (now,),
                )
                existing = connection.execute(
                    f"SELECT {_ROW_COLUMNS} FROM codex_artifact_issuance WHERE identity_digest = ? AND expires_at > ? LIMIT 1",
                    (identity_digest, now),
                ).fetchone()
                if existing is not None:
                    record = self._decode(existing)
                    if any(record[field] != identity[field] for field in _IDENTITY_FIELDS):
                        raise ArtifactStoreError("artifact_identity_conflict")
                    return record
                issuance_id = secrets.token_hex(16)
                artifact_id = "mcp_art_" + _digest(identity_digest + ":" + issuance_id)
                record = {
                    **identity, "artifactId": artifact_id, "threadId": thread_id,
                    "issuedAt": now, "expiresAt": expires, "issuanceId": issuance_id,
                }
                serialized = _canonical(record)
                if len(serialized.encode("utf-8")) > 16384:
                    raise ArtifactStoreError("artifact_invalid")
                connection.execute(
                    f"INSERT INTO codex_artifact_issuance ({_ROW_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (artifact_id, tenant_id, session_id, identity_digest, serialized, _digest(serialized), expires),
                )
                return record
        except sqlite3.Error:
            raise ArtifactStoreError("artifact_store_unavailable") from None
        except (TypeError, ValueError, UnicodeError, RecursionError):
            raise ArtifactStoreError("artifact_invalid") from None

    def get_many(
        self, *, tenant_id: str, session_id: str, artifact_ids: Iterable[str],
    ) -> dict[str, dict[str, Any]]:
        identifiers = list(dict.fromkeys(artifact_ids))
        if len(identifiers) > 128 or any(not isinstance(item, str) or len(item) > 256 for item in identifiers):
            raise ArtifactStoreError("artifact_invalid")
        if not identifiers:
            return {}
        now = self._now()
        placeholders = ",".join("?" for _ in identifiers)
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    f"SELECT {_ROW_COLUMNS} FROM codex_artifact_issuance WHERE tenant_id = ? AND session_id = ? "
                    f"AND expires_at > ? AND artifact_id IN ({placeholders})",
                    (str(tenant_id), str(session_id), now, *identifiers),
                ).fetchall()
            return {row[0]: self._decode(row) for row in rows}
        except sqlite3.Error:
            raise ArtifactStoreError("artifact_store_unavailable") from None
