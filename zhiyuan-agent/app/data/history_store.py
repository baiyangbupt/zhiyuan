"""SQLite-backed chat history storage."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.data.history_codec import deserialize_history, serialize_history


SCHEMA_VERSION = 1


@dataclass(slots=True)
class ChatHistoryStore:
    """Persist pydantic-ai message history in SQLite."""

    db_path: str
    _path: Path = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._path = Path(self.db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    async def load(self, session_id: str) -> list[Any] | None:
        """Load a session's full message history."""
        payload = self._load_payload(session_id)
        if payload is None:
            return None
        return deserialize_history(payload)

    async def save(self, session_id: str, history: list[Any]) -> None:
        """Persist a session's full message history snapshot."""
        payload = serialize_history(history)
        self._save_payload(session_id, payload)

    async def delete(self, session_id: str) -> None:
        """Delete a session's saved history."""
        self._delete_payload(session_id)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_session_history (
                    session_id TEXT PRIMARY KEY,
                    history_json TEXT NOT NULL,
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _load_payload(self, session_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT history_json
                FROM chat_session_history
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return str(row["history_json"])

    def _save_payload(self, session_id: str, payload: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE chat_session_history
                SET history_json = ?,
                    schema_version = ?,
                    updated_at = ?
                WHERE session_id = ?
                """,
                (payload, SCHEMA_VERSION, now, session_id),
            )
            if cursor.rowcount == 0:
                conn.execute(
                    """
                    INSERT INTO chat_session_history (
                        session_id, history_json, schema_version, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (session_id, payload, SCHEMA_VERSION, now, now),
                )
            conn.commit()

    def _delete_payload(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM chat_session_history WHERE session_id = ?",
                (session_id,),
            )
            conn.commit()
