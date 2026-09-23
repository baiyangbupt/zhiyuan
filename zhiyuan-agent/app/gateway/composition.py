from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
import secrets
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

from app.config import CodexAppServerConfig
from app.gateway.service import GatewayService
from app.gateway.user_input import UserInputBroker

# A1 探针实测（.runtime/codex-capabilities.json）：原生提问在真实二进制上可用，
# 但**必须同时满足两件事**——启动时带上这两个特性开关，且 initialize 声明能力。
# 缺任一件，`item/tool/requestUserInput` 就不会发出，而链路上不会报错：
# 它只是永远不提问。
NATIVE_USER_INPUT_FLAGS = (
    "-c", "features.default_mode_request_user_input=true",
    "-c", "tools.experimental_request_user_input.enabled=true",
)

# MCP server 需要的环境变量名（值由 codex 从本进程透传，不写死在这里）。
# `MCP_MODE` 也在其中：MCP 子进程不继承本进程环境，不声明就等于永远拿不到这个开关
# （2026-09-24 实测：启动脚本一直在传 `MCP_MODE=readonly`，而它没在这张表里 →
# MCP 侧读到的是自己的默认值，谁也没发现）。
MCP_ENV_VARS = ("INTERNAL_SERVICE_URL", "INTERNAL_SERVICE_TIMEOUT_SECONDS", "MCP_MODE")

# 源码依据 codex-rs/codex-mcp/src/client_capabilities.rs：只有这四个命名空间被保留。
NATIVE_USER_INPUT_CAPABILITIES = {
    "experimentalApi": True,
    "extensions": {"openai/standard-form-input": {}},
}
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
    if mode in {"codex_readonly", "codex_write"}:
        if not config.binding_registry_path:
            raise ValueError(
                "CODEX_APP_SERVER_BINDING_REGISTRY_PATH is required for codex_readonly"
            )
        server_path = Path(__file__).resolve().parents[1] / "mcp_server" / "server.py"
        mcp_config = (
            "mcp_servers.zhiyuan_domain={"
            f"command={json.dumps(config.python_bin)},"
            f"args=[{json.dumps(str(server_path))},\"--binding-registry\",{json.dumps(config.binding_registry_path)}],"
            # MCP server 是 codex 的子进程，**不自动继承**本进程的环境变量。
            # 不透传的话 `internal_client` 会落到它的默认地址——而那个默认是
            # **生产**（https://zhiyuan.ytell.cn），于是本地栈会静默地去生产
            # 解析绑定，失败信息只说 "binding_resolution_failed"，完全看不出
            # 它打到了哪里。实测就是这么发生的。
            f"env_vars={json.dumps(MCP_ENV_VARS)}"
            "}"
        )
        command.extend(["--config", mcp_config])
    if config.user_input_mode == "native":
        # 默认不传：这是"替运维做了一次他们没做过的决定"，
        # 而那条路的开关是 A1 实证过的、有前提的。
        command.extend(NATIVE_USER_INPUT_FLAGS)
    return [*command, "app-server", "--stdio"]


async def build_gateway_runtime(
    gateway_config: Any,
    *,
    legacy: Any,
    message_store: Any,
    binding_loader: Callable[..., Any],
    snapshot_loader: Callable[..., Any],
    current_binding_loader: Callable[..., Any] | None = None,
    evidence_verifier: Callable[..., Any] | None = None,
    codex: Any | None = None,
    codex_config: CodexAppServerConfig | None = None,
    base_instructions: str = "",
    developer_instructions: str = "",
) -> GatewayRuntime | None:
    """Build and start the production Gateway runtime for Codex modes."""
    mode = str(getattr(gateway_config, "mode", "legacy"))
    if mode == "legacy":
        return None
    # 一致性告警（P2 写模式）：网关模式与 MCP 侧的模式是两个开关，配错时**不报错**
    # 是最坏的情况——写实例上模型会得到"本实例只读"的拒绝话术，反过来更像漏。
    _warn_on_mode_mismatch(mode)

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
            # 能力声明与开关必须同进同退：只开开关不声明能力，
            # 服务端不会把标准表单请求转发过来。
            capabilities=(
                NATIVE_USER_INPUT_CAPABILITIES
                if resolved_config.user_input_mode == "native"
                else None
            ),
        )

    if not base_instructions:
        base_instructions = _load_default_instructions(skill_root, "base_instructions.md")
    if not developer_instructions:
        developer_instructions = _load_default_instructions(
            skill_root, "developer_instructions.md"
        )

    await codex.start()
    # 没有这一步，原生提问会被 client 的默认分支回成 `{"result": null}`——
    # 模型的问题被静默当成"用户回答了空"，而且链路上不留任何痕迹。
    broker = UserInputBroker(runtime_generation=secrets.token_hex(8))
    codex.set_server_request_handler(broker.handle_server_request)
    gateway = GatewayService(
        mode=mode,
        codex=codex,
        legacy=legacy,
        message_store=message_store,
        binding_loader=binding_loader,
        snapshot_loader=snapshot_loader,
        base_instructions=base_instructions,
        developer_instructions=developer_instructions,
        session_runtime=None,
        current_binding_loader=current_binding_loader,
        evidence_verifier=evidence_verifier,
    )
    # scope 解析器要等 gateway 建好：它从业务绑定反查身份，是唯一可信的来源。
    broker.set_scope_resolver(gateway.scope_for_thread)
    broker.set_emitter(_publish_to_session)
    gateway.user_input_broker = broker
    return GatewayRuntime(gateway=gateway, codex=codex)


async def _publish_to_session(key: Any, event: dict) -> bool:
    """把事件推到该会话当前的 WS 连接。

    运行时要等 server.py 装配时才存在，所以这里做一次间接查表；
    查不到不是错误——用户可能还没连上，卡片会在 resync 时补出来。
    """
    runtime = _SESSION_RUNTIME.get("instance")
    if runtime is None:
        return False
    return await runtime.publish(key, event)


# 由 server.py 在 lifespan 里填入；放模块级是为了让 composition 不必知道 server。
_SESSION_RUNTIME: dict[str, Any] = {}


def bind_session_runtime(runtime: Any) -> None:
    _SESSION_RUNTIME["instance"] = runtime


def _warn_on_mode_mismatch(gateway_mode: str) -> None:
    """网关模式与 MCP 模式配错时**大声说**——两个开关，谁都不会自己纠偏。

    写实例（`codex_write`）配了只读 MCP：模型照样拿不到写路径，而写工具的拒绝话术会说
    "本实例只读"，排查时会先怀疑模型 ✗；只读实例配了写 MCP：与"写路径只在写实例上活着"
    的部署前提相反 ✗。两种都不报错，所以这里主动叫一声。
    """
    mcp_mode = os.environ.get("MCP_MODE", "readonly")
    expected = "write" if gateway_mode == "codex_write" else "readonly"
    if mcp_mode != expected:
        logger.warning(
            "gateway mode %s expects MCP_MODE=%s but got %r — the tool face and the "
            "confirmation chain disagree (check the instance's env)",
            gateway_mode,
            expected,
            mcp_mode,
        )


def _load_default_instructions(skill_root: str, filename: str) -> str:
    path = Path(skill_root) / filename
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""
