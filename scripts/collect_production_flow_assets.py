#!/usr/bin/env python3
"""Collect read-only production dialogue and volunteer-plan assets.

The script intentionally does not call any write endpoint. It uses SSH to run
local curl/ls/tar commands on the production host and stores the resulting
messages, planning workspace/state snapshots, and volunteer plan JSON files in
the local workspace for offline verification.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_HOST = os.getenv("ZHIYUAN_PRODUCTION_ASSET_HOST", "")
DEFAULT_BASE_URL = os.getenv("ZHIYUAN_PRODUCTION_ASSET_BASE_URL", "http://127.0.0.1:8090")
DEFAULT_DATA_DIR = os.getenv("ZHIYUAN_PRODUCTION_ASSET_DATA_DIR", "/apps/volunnter-tmpdata")
DEFAULT_TENANT_ID = os.getenv("ZHIYUAN_PRODUCTION_ASSET_TENANT_ID", "1")


def _run_ssh(host: str, command: str, *, timeout: int = 30) -> str:
    proc = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host, command],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ssh command failed rc={proc.returncode}: {proc.stderr.strip()}")
    return proc.stdout


def _run_ssh_bytes(host: str, command: str, *, timeout: int = 120) -> bytes:
    proc = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host, command],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ssh command failed rc={proc.returncode}: {proc.stderr.decode('utf-8', 'ignore').strip()}")
    return proc.stdout


def _json_from_ssh(host: str, url: str) -> dict[str, Any]:
    raw = _run_ssh(host, f"curl -s --max-time 15 {json.dumps(url)}", timeout=25)
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"non-json response for {url}: {raw[:200]}") from exc
    return value if isinstance(value, dict) else {"data": value}


def _message_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.replace("\n", " ").strip()
    if isinstance(value, dict):
        for key in ("content", "text", "message", "title", "summary"):
            if value.get(key):
                return _message_text(value.get(key))
        return json.dumps(value, ensure_ascii=False)[:200]
    return str(value).replace("\n", " ").strip()


def _summarize_messages(response: dict[str, Any]) -> dict[str, Any]:
    rows = response.get("data")
    messages = rows if isinstance(rows, list) else []
    user_prompts: list[str] = []
    recent_messages: list[dict[str, Any]] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        text = _message_text(item.get("content"))
        sender = str(item.get("messageFrom") or item.get("sender") or "").strip()
        if sender in {"1", "USER", "user", "student", "STUDENT"} and text:
            user_prompts.append(text[:500])
        recent_messages.append(
            {
                "id": item.get("id"),
                "messageFrom": item.get("messageFrom"),
                "contentType": item.get("contentType"),
                "contentPreview": text[:300],
                "createTime": item.get("createTime") or item.get("create_time"),
            }
        )
    return {
        "messageCount": len(messages),
        "userPrompts": user_prompts,
        "recentMessages": recent_messages[-12:],
    }


def _summarize_workspace(response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    ordered = data.get("orderedPlanState") if isinstance(data.get("orderedPlanState"), dict) else {}
    candidate = data.get("candidatePoolState") if isinstance(data.get("candidatePoolState"), dict) else {}
    review = data.get("reviewState") if isinstance(data.get("reviewState"), dict) else {}
    return {
        "phase": data.get("phase"),
        "version": data.get("version"),
        "volunteerModel": data.get("volunteerModel"),
        "orderedSummary": ordered.get("summary"),
        "candidateSummary": candidate.get("summary"),
        "reviewSummary": review.get("summary"),
    }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def collect_session(
    *,
    host: str,
    base_url: str,
    tenant_id: str,
    data_dir: str,
    session_id: str,
    output_dir: Path,
) -> dict[str, Any]:
    session_dir = output_dir / "sessions" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    messages = _json_from_ssh(
        host,
        f"{base_url.rstrip('/')}/gaotu-assistant-bot/inner/chat/{tenant_id}/message/list-all?chatSessionId={session_id}",
    )
    workspace = _json_from_ssh(
        host,
        f"{base_url.rstrip('/')}/gaotu-assistant-bot/inner/planning/{tenant_id}/session/workspace-state?chatSessionId={session_id}",
    )
    state = _json_from_ssh(
        host,
        f"{base_url.rstrip('/')}/gaotu-assistant-bot/inner/planning/{tenant_id}/session/state?chatSessionId={session_id}",
    )
    file_listing = _run_ssh(
        host,
        f"ls -lh {json.dumps(data_dir)}/session_volunteer_{session_id}*.json 2>/dev/null || true",
    )

    _write_json(session_dir / "messages.json", messages)
    _write_json(session_dir / "workspace-state.json", workspace)
    _write_json(session_dir / "planning-state.json", state)
    (session_dir / "plan-files.txt").write_text(file_listing, encoding="utf-8")

    tar_bytes = _run_ssh_bytes(
        host,
        (
            f"cd {json.dumps(data_dir)} && "
            f"tar -czf - session_volunteer_{session_id}.json "
            f"session_volunteer_{session_id}_temp.json "
            f"session_volunteer_{session_id}_final.json 2>/dev/null || true"
        ),
        timeout=180,
    )
    tar_path = session_dir / "volunteer-files.tar.gz"
    tar_path.write_bytes(tar_bytes)

    summary = {
        "sessionId": session_id,
        "messages": _summarize_messages(messages),
        "workspace": _summarize_workspace(workspace),
        "planFiles": file_listing.strip().splitlines(),
        "archive": str(tar_path.relative_to(output_dir)),
        "archiveBytes": tar_path.stat().st_size,
    }
    _write_json(session_dir / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect read-only production dialogue/plan assets.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    parser.add_argument("--sessions", nargs="+", required=True)
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args()
    if not str(args.host or "").strip():
        raise SystemExit("missing --host or ZHIYUAN_PRODUCTION_ASSET_HOST")

    output_dir = Path(args.output_dir or f"assets/production-flow-verification-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    output_dir.mkdir(parents=True, exist_ok=True)

    summaries = []
    for session_id in args.sessions:
        summaries.append(
            collect_session(
                host=args.host,
                base_url=args.base_url,
                tenant_id=args.tenant_id,
                data_dir=args.data_dir,
                session_id=str(session_id),
                output_dir=output_dir,
            )
        )
    manifest = {
        "collectedAt": datetime.now().isoformat(timespec="seconds"),
        "host": args.host,
        "baseUrl": args.base_url,
        "dataDir": args.data_dir,
        "sessions": summaries,
    }
    _write_json(output_dir / "manifest.json", manifest)
    print(json.dumps({"outputDir": str(output_dir), "sessions": [s["sessionId"] for s in summaries]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
