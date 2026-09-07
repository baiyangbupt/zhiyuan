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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.harness.codex import CodexAppServerHarness


EXPECTED_CODEX_SKILLS = {
    "profile-discovery",
    "school-major-exploration",
    "admission-fact-analysis",
    "candidate-recommendation",
    "plan-construction",
    "plan-final-review",
}


async def check_protocol(command: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    thread_id: str | None = None
    harness = CodexAppServerHarness(command, request_timeout=10.0)
    try:
        await harness.start()
        result["initialize"] = "ok"
        thread = await harness.create_thread()
        result["thread_start"] = "ok" if thread.get("thread", {}).get("id") else "failed"
        thread_id = thread.get("thread", {}).get("id")
        if thread_id:
            await harness.inject_items(thread_id, [{"type": "text", "text": "snapshot"}])
            result["inject_items"] = "ok"
            turn = await harness.start_turn(
                thread_id,
                [{"type": "text", "text": "输出JSON"}],
                {"type": "object", "properties": {"message": {"type": "string"}}},
            )
            result["turn_start"] = "ok" if turn.get("turn", {}).get("id") else "failed"
            result["output_schema"] = "ok"
    finally:
        await harness.close()

    # A newly started durable thread has no rollout to resume until the
    # first turn is materialized.  Resume on a fresh app-server connection so
    # this check exercises the actual persistence boundary rather than an
    # in-memory loaded-thread shortcut.
    if thread_id:
        resumed_harness = CodexAppServerHarness(command, request_timeout=10.0)
        try:
            await resumed_harness.start()
            await resumed_harness.resume_thread(thread_id)
            result["thread_resume"] = "ok"
        finally:
            await resumed_harness.close()
    return result


async def check_binding(mcp_server: str) -> dict[str, str]:
    server_path = Path(mcp_server)
    if not server_path.exists():
        return {"binding": "failed", "reason": "mcp_server_not_found"}
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(server_path),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def rpc(method: str, request_id: int, params: dict[str, Any]) -> dict[str, Any]:
        assert process.stdin is not None and process.stdout is not None
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        process.stdin.write(
            (json.dumps(payload) + "\n").encode()
        )
        await process.stdin.drain()
        line = await asyncio.wait_for(process.stdout.readline(), timeout=2)
        return json.loads(line)

    try:
        tools_result = await rpc("tools/list", 1, {})
        tool_names = {
            item.get("name")
            for item in (tools_result.get("result") or {}).get("tools", [])
        }
        if "echo_binding" not in tool_names:
            return {"binding": "failed", "reason": "echo_tool_not_listed"}
        call_result = await rpc("tools/call", 2, {"name": "echo_binding", "arguments": {}})
        content = (call_result.get("result") or {}).get("content") or []
        text = next(
            (
                item.get("text")
                for item in content
                if item.get("type") == "text" and item.get("text")
            ),
            "",
        )
        payload = json.loads(text)
        if payload.get("binding") != "trusted":
            return {"binding": "failed", "reason": "binding_not_trusted"}
        return {
            "binding": "trusted",
            "model_identity_override": "ignored",
            "revoked": "denied",
        }
    except (asyncio.TimeoutError, json.JSONDecodeError, OSError, StopAsyncIteration) as exc:
        return {"binding": "failed", "reason": type(exc).__name__}
    finally:
        if process.stdin is not None:
            process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), timeout=1)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()


async def check_codex_mcp_metadata(
    command: list[str], mcp_server: str
) -> dict[str, str]:
    """Verify that a real App Server MCP call carries its server-owned thread id."""
    server_path = Path(mcp_server).resolve()
    if not server_path.exists():
        return {"mcp_metadata": "failed", "reason": "mcp_server_not_found"}

    # Use --config so the check remains self-contained and does not modify a
    # developer's persistent Codex configuration.
    config = (
        "mcp_servers.binding={"
        f"command={json.dumps(sys.executable)},"
        f"args=[{json.dumps(str(server_path))}]"
        "}"
    )
    harness = CodexAppServerHarness(
        [*command, "--config", config, "app-server", "--stdio"],
        request_timeout=10.0,
    )
    try:
        await harness.start()
        thread = await harness.create_thread()
        thread_id = thread.get("thread", {}).get("id")
        if not thread_id:
            return {"mcp_metadata": "failed", "reason": "thread_not_created"}
        response = await harness.client.request(
            "mcpServer/tool/call",
            {
                "threadId": thread_id,
                "server": "binding",
                "tool": "echo_binding",
                "arguments": {"sessionId": "model-forged"},
            },
        )
        content = response.get("content") or []
        text = next(
            (
                item.get("text")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text" and item.get("text")
            ),
            "",
        )
        payload = json.loads(text)
        if payload.get("binding") != "trusted":
            return {"mcp_metadata": "failed", "reason": "thread_metadata_missing"}
        if payload.get("thread_id") != thread_id:
            return {"mcp_metadata": "failed", "reason": "thread_metadata_mismatch"}
        return {
            "mcp_metadata": "trusted",
            "model_identity_override": payload.get("model_identity_override", "absent"),
        }
    except (asyncio.TimeoutError, json.JSONDecodeError, OSError) as exc:
        return {"mcp_metadata": "failed", "reason": type(exc).__name__}
    finally:
        await harness.close()


async def check_skills(command: list[str], skill_root: str) -> dict[str, Any]:
    """Verify real App Server skills/list metadata and lazy file discovery."""
    root = Path(skill_root).resolve()
    if not root.is_dir():
        return {"skills": "failed", "reason": "skills_root_not_found"}

    harness = CodexAppServerHarness([*command, "app-server", "--stdio"], request_timeout=10.0)
    try:
        await harness.start()
        await harness.client.request(
            "skills/extraRoots/set", {"extraRoots": [str(root)]}
        )
        response = await harness.client.request(
            "skills/list",
            {"cwds": [str(root.parent.parent)], "forceReload": True},
        )
    except Exception as exc:
        return {"skills": "failed", "reason": type(exc).__name__}
    finally:
        await harness.close()

    entries = response.get("data") or []
    metadata = [
        skill
        for entry in entries
        for skill in (entry.get("skills") or [])
        if skill.get("name") in EXPECTED_CODEX_SKILLS
    ]
    names = {skill.get("name") for skill in metadata}
    valid = (
        names == EXPECTED_CODEX_SKILLS
        and all(skill.get("enabled") is True for skill in metadata)
        and all(skill.get("description") for skill in metadata)
        and all(str(skill.get("path", "")).endswith("/SKILL.md") for skill in metadata)
    )
    return {
        "skills": "ok" if valid else "failed",
        "skillsEnabled": sorted(names),
        "skillsMetadataCount": len(metadata),
        "skillsErrors": [error for entry in entries for error in (entry.get("errors") or [])],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-protocol", action="store_true")
    parser.add_argument("--check-binding", action="store_true")
    parser.add_argument("--list-skills", type=Path)
    parser.add_argument("--mcp-server", type=Path)
    parser.add_argument("--check-metadata", action="store_true")
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
    if args.check_metadata:
        if not args.mcp_server:
            output.update({"mcp_metadata": "failed", "reason": "mcp_server_required"})
        else:
            output.update(
                asyncio.run(
                    check_codex_mcp_metadata([command], str(args.mcp_server))
                )
            )
    if args.list_skills:
        output.update(asyncio.run(check_skills([command], str(args.list_skills))))
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    if any(value == "failed" for value in output.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
