#!/usr/bin/env python3
"""Inspect persisted pydantic-ai chat history in SQLite."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path("./data/chat_history.db")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect persisted pydantic-ai chat history by session id."
    )
    parser.add_argument("session_id", help="Session ID to inspect")
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help="Path to SQLite database file",
    )
    parser.add_argument(
        "--full-json",
        action="store_true",
        help="Print full history_json payload",
    )
    return parser


def _preview_value(value: Any, limit: int = 160) -> str:
    if value is None:
        return "None"
    if isinstance(value, str):
        compact = value.replace("\n", " ")
        return compact[:limit] + ("..." if len(compact) > limit else "")
    return json.dumps(value, ensure_ascii=False)[:limit]


def main() -> int:
    args = _build_parser().parse_args()
    db_path = Path(args.db_path).expanduser().resolve()

    print(f"DB_PATH={db_path}")
    if not db_path.exists():
        print("DB_NOT_FOUND")
        return 1

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT session_id, schema_version, created_at, updated_at, history_json
            FROM chat_session_history
            WHERE session_id = ?
            """,
            (args.session_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        print("SESSION_NOT_FOUND")
        return 1

    history_json = row["history_json"]
    history = json.loads(history_json)

    print(f"SESSION_ID={row['session_id']}")
    print(f"SCHEMA_VERSION={row['schema_version']}")
    print(f"CREATED_AT={row['created_at']}")
    print(f"UPDATED_AT={row['updated_at']}")
    print(f"MESSAGE_COUNT={len(history)}")
    print(f"HISTORY_JSON_LENGTH={len(history_json)}")

    for i, message in enumerate(history):
        parts = message.get("parts") or []
        print(f"[{i}] kind={message.get('kind')} part_count={len(parts)}")
        for j, part in enumerate(parts):
            part_kind = part.get("part_kind")
            content = part.get("content")
            print(
                f"  part[{j}] part_kind={part_kind} content={_preview_value(content)}"
            )

    if args.full_json:
        print("FULL_JSON_BEGIN")
        print(json.dumps(history, ensure_ascii=False, indent=2))
        print("FULL_JSON_END")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
