from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_codex_shadow_composition_constructs_gateway_runtime() -> None:
    from app.gateway.composition import build_gateway_runtime

    fake_codex = MagicMock()
    fake_codex.start = AsyncMock()
    fake_codex.close = AsyncMock()
    fake_config = MagicMock(mode="codex_shadow")
    fake_config.codex = MagicMock()

    runtime = await build_gateway_runtime(
        fake_config,
        legacy=MagicMock(),
        message_store=MagicMock(),
        binding_loader=MagicMock(),
        snapshot_loader=MagicMock(),
        codex=fake_codex,
    )

    assert runtime.gateway is not None
    assert runtime.gateway.mode == "codex_shadow"
    fake_codex.start.assert_awaited_once()
    assert runtime.gateway.base_instructions
    assert runtime.gateway.developer_instructions
    await runtime.close()
    fake_codex.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_legacy_composition_skips_codex_start() -> None:
    from app.gateway.composition import build_gateway_runtime

    fake_codex = MagicMock()
    fake_codex.start = AsyncMock()
    fake_codex.close = AsyncMock()
    fake_config = MagicMock(mode="legacy")

    runtime = await build_gateway_runtime(
        fake_config,
        legacy=MagicMock(),
        message_store=MagicMock(),
        binding_loader=MagicMock(),
        snapshot_loader=MagicMock(),
        codex=fake_codex,
    )

    assert runtime is None
    fake_codex.start.assert_not_awaited()


def test_readonly_command_requires_local_binding_registry() -> None:
    from app.config import CodexAppServerConfig
    from app.gateway.composition import build_codex_command

    config = CodexAppServerConfig(_env_file=None, binding_registry_path="/tmp/bindings.sqlite3")
    command = build_codex_command("codex_readonly", config)

    assert command[-2:] == ["app-server", "--stdio"]
    assert "mcp_servers.zhiyuan_domain" in command[2]
    assert "--binding-registry" in command[2]


def test_readonly_command_fails_closed_without_local_binding_registry() -> None:
    from app.config import CodexAppServerConfig
    from app.gateway.composition import build_codex_command

    with pytest.raises(ValueError, match="BINDING_REGISTRY_PATH"):
        build_codex_command("codex_readonly", CodexAppServerConfig(_env_file=None))
