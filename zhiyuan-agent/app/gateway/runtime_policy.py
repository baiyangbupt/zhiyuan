"""Fail closed on runtime drift; business agents get only domain/skill MCP access."""
from __future__ import annotations
import asyncio
from collections.abc import Mapping

DISABLED_FEATURES = (
    "shell_tool", "apps", "browser_use", "browser_use_external", "in_app_browser",
    "image_generation", "multi_agent", "multi_agent_v2", "plugins",
    "view_image", "hooks", "remote_plugin", "unified_exec",
    "computer_use", "browser_use_full_cdp_access", "goals", "sleep_tool",
    "request_permissions_tool",
)

def policy_arguments() -> list[str]:
    args = ["-c", 'web_search="disabled"']
    for name in DISABLED_FEATURES:
        args.extend(["-c", f"features.{name}=false"])
    return args

async def verify_binary(config) -> None:
    process = await asyncio.create_subprocess_exec(
        config.bin, "--version", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    expected = f"codex-cli {config.expected_version}"
    if process.returncode != 0 or stdout.decode().strip() != expected:
        raise RuntimeError(f"Codex version mismatch: expected {expected}; validate and explicitly update CODEX_APP_SERVER_EXPECTED_VERSION")

def validate_effective_policy(payload) -> None:
    config = payload.get("config") if isinstance(payload, Mapping) else None
    if not isinstance(config, Mapping):
        raise RuntimeError("Codex effective configuration unavailable")
    features = config.get("features") or {}
    if config.get("web_search") != "disabled" or any(features.get(name) is not False for name in DISABLED_FEATURES):
        raise RuntimeError("Codex business tool policy was not applied")
    if config.get("notify"):
        raise RuntimeError("Codex business runtime must not inherit notification commands")
    servers = config.get("mcp_servers") or {}
    if not isinstance(servers, Mapping) or any(
        name != "zhiyuan_domain" and (not isinstance(value, Mapping) or value.get("enabled", True) is not False)
        for name, value in servers.items()
    ):
        raise RuntimeError("Unexpected enabled MCP server in Codex business runtime")
    if "zhiyuan_domain" not in servers or servers["zhiyuan_domain"].get("enabled", True) is False:
        raise RuntimeError("Domain MCP server is unavailable")
