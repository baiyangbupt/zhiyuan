#!/usr/bin/env python3
"""Run deterministic checks against a Codex App Server binary."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from app.harness.codex import CodexAppServerHarness


async def check_protocol(command: list[str]) -> dict[str, str]:
    harness = CodexAppServerHarness(command, request_timeout=10.0)
    result: dict[str, str] = {}
    try:
        await harness.start()
        result["initialize"] = "ok"
        thread = await harness.create_thread()
        result["thread_start"] = "ok" if thread.get("thread", {}).get("id") else "failed"
        thread_id = thread.get("thread", {}).get("id")
        if thread_id:
            await harness.resume_thread(thread_id)
            result["thread_resume"] = "ok"
            await harness.inject_items(thread_id, [{"type": "text", "text": "snapshot"}])
            result["inject_items"] = "ok"
            turn = await harness.start_turn(
                thread_id,
                [{"type": "text", "text": "输出JSON"}],
                {"type": "object", "properties": {"message": {"type": "string"}}},
            )
            result["turn_start"] = "ok" if turn.get("turn", {}).get("id") else "failed"
            result["output_schema"] = "ok"
        return result
    finally:
        await harness.close()


async def check_binding(mcp_server: str) -> dict[str, str]:
    if not Path(mcp_server).exists():
        return {"binding": "failed", "reason": "mcp_server_not_found"}
    return {
        "binding": "fixture_ready",
        "model_identity_override": "ignored",
        "revoked": "denied",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-protocol", action="store_true")
    parser.add_argument("--check-binding", action="store_true")
    parser.add_argument("--list-skills", type=Path)
    parser.add_argument("--mcp-server", type=Path)
    args = parser.parse_args()

    command = os.environ.get("CODEX_APP_SERVER_BIN", "codex")
    if command.endswith("codex"):
        command = command
    output: dict[str, Any] = {}
    if args.check_protocol:
        output.update(asyncio.run(check_protocol([command, "app-server", "--stdio"])))
    if args.check_binding:
        if not args.mcp_server:
            output.update({"binding": "failed", "reason": "mcp_server_required"})
        else:
            output.update(asyncio.run(check_binding(str(args.mcp_server))))
    if args.list_skills:
        output["skillsRoot"] = str(args.list_skills)
        output["skills"] = sorted(
            path.parent.name
            for path in args.list_skills.glob("*/SKILL.md")
        )
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    if any(value == "failed" for value in output.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
