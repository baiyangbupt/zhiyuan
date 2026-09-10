from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable

from app.config import CodexAppServerConfig
from app.gateway.service import GatewayService
from app.harness.codex import CodexAppServerHarness


@dataclass(slots=True)
class GatewayRuntime:
    gateway: GatewayService
    codex: Any

    async def close(self) -> None:
        close = getattr(self.codex, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result


def build_codex_command(mode: str, config: CodexAppServerConfig) -> list[str]:
    command = [config.bin]
    if mode == "codex_readonly":
        if not config.binding_registry_path:
            raise ValueError(
                "CODEX_APP_SERVER_BINDING_REGISTRY_PATH is required for codex_readonly"
            )
        server_path = Path(__file__).resolve().parents[1] / "mcp_server" / "server.py"
        mcp_config = (
            "mcp_servers.zhiyuan_domain={"
            f"command={json.dumps(config.python_bin)},"
            f"args=[{json.dumps(str(server_path))},\"--binding-registry\",{json.dumps(config.binding_registry_path)}]"
            "}"
        )
        command.extend(["--config", mcp_config])
    return [*command, "app-server", "--stdio"]


async def build_gateway_runtime(
    gateway_config: Any,
    *,
    legacy: Any,
    message_store: Any,
    binding_loader: Callable[..., Any],
    snapshot_loader: Callable[..., Any],
    codex: Any | None = None,
    codex_config: CodexAppServerConfig | None = None,
    base_instructions: str = "",
    developer_instructions: str = "",
) -> GatewayRuntime | None:
    """Build and start the production Gateway runtime for Codex modes."""
    mode = str(getattr(gateway_config, "mode", "legacy"))
    if mode == "legacy":
        return None

    resolved_config = codex_config or CodexAppServerConfig()
    skill_root = resolved_config.skill_root or str(
        Path(__file__).resolve().parents[2] / "skills" / "codex"
    )
    if codex is None:
        if resolved_config.transport != "stdio":
            raise ValueError(f"unsupported Codex transport: {resolved_config.transport}")
        codex = CodexAppServerHarness(
            build_codex_command(mode, resolved_config),
            request_timeout=resolved_config.timeout_seconds,
            skill_root=skill_root,
            approval_policy=resolved_config.approval_policy,
            sandbox_policy=resolved_config.sandbox_policy,
        )

    if not base_instructions:
        base_instructions = _load_default_instructions(skill_root, "base_instructions.md")
    if not developer_instructions:
        developer_instructions = _load_default_instructions(
            skill_root, "developer_instructions.md"
        )

    await codex.start()
    gateway = GatewayService(
        mode=mode,
        codex=codex,
        legacy=legacy,
        message_store=message_store,
        binding_loader=binding_loader,
        snapshot_loader=snapshot_loader,
        base_instructions=base_instructions,
        developer_instructions=developer_instructions,
    )
    return GatewayRuntime(gateway=gateway, codex=codex)


def _load_default_instructions(skill_root: str, filename: str) -> str:
    path = Path(skill_root) / filename
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""
