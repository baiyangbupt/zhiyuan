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
async def test_write_mode_appends_the_write_instance_rules() -> None:
    """写实例的附加规则必须进 developer instructions；只读实例**不许**有它。

    依据（2026-09-24 真栈实测）：技能文本里"写请求只说明需用户确认"那半是按只读阶段写的，
    在写实例上它挡住了唯一的写入口——两轮 plan 类用例都没出 `proposalRequest` ✗。
    实例级规则由网关自己拼（只有它知道模式），所以这里量"拼没拼上、会不会拼错模式"。
    """
    from app.gateway.composition import build_gateway_runtime

    async def build(mode: str) -> str:
        fake_codex = MagicMock()
        fake_codex.start = AsyncMock()
        fake_codex.close = AsyncMock()
        runtime = await build_gateway_runtime(
            MagicMock(mode=mode),
            legacy=MagicMock(),
            message_store=MagicMock(),
            binding_loader=MagicMock(),
            snapshot_loader=MagicMock(),
            codex=fake_codex,
        )
        instructions = runtime.gateway.developer_instructions
        await runtime.close()
        return instructions

    marker = "写实例附加规则"
    assert marker in await build("codex_write"), "写实例没带上附加规则"
    assert marker not in await build("codex_readonly"), "只读实例不该带写规则"


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


def test_readonly_command_emits_toml_parseable_config() -> None:
    """`-c` 的值必须是合法 TOML 内联表；这条是**防回归**，不是修 bug。

    现行实现用 `command=`（TOML）而不是 `"command":`（JSON）。两者只差一个
    冒号，且 JSON 风格**不会在 Python 侧报错**——`-c` 解析失败时退回成字面
    字符串，直到真实二进制加载配置才以
    `invalid type: string ..., expected struct RawMcpServerConfig` 退出。
    也就是说子串断言（如上面那条）对此完全无感，只有真解析才拦得住。
    """
    tomli = pytest.importorskip("tomli")
    from app.config import CodexAppServerConfig
    from app.gateway.composition import build_codex_command

    config = CodexAppServerConfig(
        _env_file=None,
        binding_registry_path="/tmp/bindings.sqlite3",
        python_bin="/usr/bin/python3",
    )
    command = build_codex_command("codex_readonly", config)
    value = command[command.index("--config") + 1]

    parsed = tomli.loads(value)
    server = parsed["mcp_servers"]["zhiyuan_domain"]
    assert server["command"] == "/usr/bin/python3"
    assert server["args"][1] == "--binding-registry"
    assert server["args"][2] == "/tmp/bindings.sqlite3"


@pytest.mark.asyncio
async def test_readonly_command_starts_real_app_server(tmp_path) -> None:
    """真实二进制必须能带着这份配置起来。

    上面那条只证明"值能被 TOML 解析"，不证明二进制接受这份配置；
    这条补上后半个问题：进程起不来时 `start()` 会抛 RuntimeError。
    """
    import os
    from pathlib import Path

    from app.config import CodexAppServerConfig
    from app.gateway.composition import build_codex_command
    from app.harness.codex import CodexAppServerHarness

    binary = os.environ.get("CODEX_APP_SERVER_BIN")
    if not binary or not Path(binary).exists():
        pytest.skip("fixed Codex App Server binary is not installed")

    config = CodexAppServerConfig(
        _env_file=None,
        bin=binary,
        binding_registry_path=str(tmp_path / "bindings.sqlite3"),
    )
    harness = CodexAppServerHarness(
        build_codex_command("codex_readonly", config), request_timeout=20.0
    )
    try:
        await harness.start()
    finally:
        await harness.close()


def test_native_user_input_requires_both_the_switch_and_the_declaration() -> None:
    """A1 探针的结论必须能落到启动参数上。

    少任一件，`item/tool/requestUserInput` 就不会发出，而**链路上不会报错**——
    它只是永远不提问。所以这两件要一起验。
    """
    from app.config import CodexAppServerConfig
    from app.gateway.composition import (
        NATIVE_USER_INPUT_CAPABILITIES,
        build_codex_command,
    )

    structured = CodexAppServerConfig(
        _env_file=None, binding_registry_path="/tmp/b.sqlite3", user_input_mode="structured_final"
    )
    native = CodexAppServerConfig(
        _env_file=None, binding_registry_path="/tmp/b.sqlite3", user_input_mode="native"
    )

    structured_command = build_codex_command("codex_readonly", structured)
    native_command = build_codex_command("codex_readonly", native)

    # 默认（保守）不带开关：原生那条路是 A1 实证过的、有前提的。
    assert "features.default_mode_request_user_input=true" not in structured_command
    assert "tools.experimental_request_user_input.enabled=true" not in structured_command

    # native 模式两个开关都要在。
    assert "features.default_mode_request_user_input=true" in native_command
    assert "tools.experimental_request_user_input.enabled=true" in native_command
    assert NATIVE_USER_INPUT_CAPABILITIES["extensions"] == {"openai/standard-form-input": {}}


def test_readonly_command_passes_internal_service_env_to_the_mcp_server() -> None:
    """MCP server 是 codex 的子进程，**不自动继承**本进程的环境变量。

    不透传 `INTERNAL_SERVICE_URL` 时，`internal_client` 会落到它的默认地址——
    而那个默认是**生产**。实测症状：本地栈静默地去生产解析绑定，失败信息只有
    `binding_resolution_failed`，完全看不出它打到了哪里。
    """
    from app.config import CodexAppServerConfig
    from app.gateway.composition import MCP_ENV_VARS, build_codex_command

    config = CodexAppServerConfig(
        _env_file=None, binding_registry_path="/tmp/b.sqlite3", python_bin="/usr/bin/python3"
    )
    command = build_codex_command("codex_readonly", config)
    value = command[command.index("--config") + 1]

    assert "env_vars=" in value
    for name in MCP_ENV_VARS:
        assert name in value, f"{name} 没有透传给 MCP server"
    # 2026-09-24 起 `MCP_MODE` 也在这张表里：不声明就等于 MCP 侧永远拿不到模式开关
    # （启动脚本一直在传，而它不在表里 → 谁也没发现）。
    assert "MCP_MODE" in MCP_ENV_VARS


def test_mode_mismatch_between_gateway_and_mcp_is_logged(caplog, monkeypatch) -> None:
    """两个开关配错时**不会报错**，所以必须主动叫一声。

    写实例配只读 MCP：模型拿不到写路径，而拒绝话术会说"本实例只读"，
    排查时会先怀疑模型 ✗；反过来只读实例配写 MCP 与部署前提相反 ✗。
    """
    from app.gateway.composition import _warn_on_mode_mismatch

    monkeypatch.setenv("MCP_MODE", "readonly")
    with caplog.at_level("WARNING"):
        _warn_on_mode_mismatch("codex_write")
    assert "MCP_MODE" in caplog.text

    caplog.clear()
    monkeypatch.setenv("MCP_MODE", "write")
    with caplog.at_level("WARNING"):
        _warn_on_mode_mismatch("codex_write")
    assert caplog.text == ""
