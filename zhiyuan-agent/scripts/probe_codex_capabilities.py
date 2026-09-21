#!/usr/bin/env python3
"""A1：对**运行中的** Codex App Server 二进制做能力探针。

为什么不能只看源码：本地源码里有某个能力，不等于 PATH 上的这个二进制
在配置好的 provider 组合下也接受它。两者的差距只能靠实跑填平，探针就是干这个的。

两条硬规矩：
1. **不使用默认值。** 每个 gate 只能报 `passed` / `failed` / `not_run`，
   没有"没测过但算通过"。退出码 0 只表示**本次选中的** gates 全过。
2. **不落敏感物。** 报告里不写 API key、不写提示词全文、不写线程 id。
   密钥只以环境变量名出现（`env_key`），进程退出后即失。
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.harness.codex import CodexAppServerHarness  # noqa: E402
from scripts.codex_app_server_poc import check_codex_mcp_metadata  # noqa: E402


REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO.parent / ".runtime" / "codex-capabilities.json"

# 与设计 §4 一致：app-server 客户端要声明的能力。
# 源码依据 codex-rs/codex-mcp/src/client_capabilities.rs：
# 只有 openai/form、openai/elicitation、openai/standard-form-input、
# io.modelcontextprotocol/ui 四个命名空间会被保留，其余被丢弃。
DECLARED_CAPABILITIES = {
    "experimentalApi": True,
    "extensions": {"openai/standard-form-input": {}},
}

PASSED, FAILED, NOT_RUN = "passed", "failed", "not_run"


def toml_inline(value: Any) -> str:
    """把值写成 `codex -c` 能接受的 TOML 内联表。

    坑在解析顺序上：`-c` 的值先按 TOML 解析，解析失败就用**原始字符串**顶替。
    于是 JSON 风格的 `{"k": "v"}`（与 TOML 的 `{k = "v"}` 只差一个冒号）
    不会在这里报错，而是以字符串身份进入配置，直到二进制启动时才炸：
    `invalid type: string ..., expected struct RawMcpServerConfig`。
    """
    if isinstance(value, str):
        # JSON 的字符串转义是 TOML basic string 转义的子集，可直接复用。
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(toml_inline(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{key} = {toml_inline(item)}" for key, item in value.items()) + "}"
    raise TypeError(f"unsupported TOML value: {type(value).__name__}")


def _error_detail(exc: BaseException) -> dict[str, Any]:
    """失败要带上错误正文。

    只记 `type(exc).__name__` 的话，"AppServerProtocolError" 这种结果
    等于没说——既不知道服务端拒绝的理由，也无法判断是配置问题还是真的不支持。
    """
    detail: dict[str, Any] = {"reason": type(exc).__name__}
    code = getattr(exc, "code", None)
    if code is not None:
        detail["code"] = code
    detail["detail"] = str(exc)[:300]
    return detail


def _binary_identity(binary: str) -> dict[str, Any]:
    """二进制自证身份。版本取自它自己，不从任何 Git 仓库的 HEAD 推。"""
    resolved = shutil.which(binary) or binary
    version = ""
    try:
        proc = subprocess.run(
            [resolved, "--version"], capture_output=True, text=True, timeout=30
        )
        version = (proc.stdout or proc.stderr or "").strip().splitlines()[0] if proc.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError, IndexError):
        version = ""
    return {"binaryPath": str(Path(resolved).resolve()), "binaryVersion": version}


async def _handshake(
    command: list[str],
    *,
    capabilities: dict[str, Any] | None,
    timeout: float,
) -> tuple[CodexAppServerHarness, dict[str, Any] | None, str | None]:
    harness = CodexAppServerHarness(command, request_timeout=timeout, capabilities=capabilities)
    try:
        await harness.start()
    except Exception as exc:  # 启动失败本身就是一条能力事实
        return harness, None, f"{type(exc).__name__}"
    return harness, harness.initialize_result, None


async def gate_initialize(command: list[str], timeout: float) -> tuple[str, dict[str, Any]]:
    harness, result, error = await _handshake(
        command, capabilities=DECLARED_CAPABILITIES, timeout=timeout
    )
    try:
        if error is not None:
            return FAILED, {"reason": error}
        if not isinstance(result, dict):
            return FAILED, {"reason": "initialize_result_not_object"}
        return PASSED, {"acceptedCapabilities": True}
    finally:
        await harness.close()


async def gate_thread_and_resume(
    command: list[str], timeout: float
) -> tuple[str, str, dict[str, Any]]:
    """一个 gate 覆盖 thread/start 与 thread/resume——两者共用同一个 thread 身份。"""
    detail: dict[str, Any] = {}
    thread_id: str | None = None
    harness, _, error = await _handshake(
        command, capabilities=DECLARED_CAPABILITIES, timeout=timeout
    )
    try:
        if error is not None:
            return FAILED, FAILED, {"reason": error}
        # threadSource 与 sessionStartSource 是**两个不同的字段**，名字近乎同名。
        # 前者取值含 user/subagent/...；后者取值是 startup|clear。
        # 发错字段不会被拒，只会静默记成另一个来源，所以这里显式发前者。
        thread = await harness.client.request(
            "thread/start",
            {
                "threadSource": "user",
                "approvalPolicy": "never",
                "sandbox": "read-only",
            },
        )
        thread_id = (thread.get("thread") or {}).get("id")
        if not thread_id:
            return FAILED, NOT_RUN, {"reason": "thread_start_without_id"}
        detail["threadSource"] = "user"
        # 刚建的空 thread 没有 rollout，resume 会失败——那不是"恢复能力缺失"，
        # 是"还没有东西可恢复"。inject_items 就能物化，且不必真的打一次模型。
        await harness.client.request(
            "thread/inject_items",
            {"threadId": thread_id, "items": [{"type": "text", "text": "probe-snapshot"}]},
        )
        detail["materializedWith"] = "thread/inject_items"
    except Exception as exc:
        return FAILED, NOT_RUN, _error_detail(exc)
    finally:
        await harness.close()

    # 换一条连接做 resume：进程内命中缓存不算证明持久化边界可用。
    resume_harness, _, error = await _handshake(
        command, capabilities=DECLARED_CAPABILITIES, timeout=timeout
    )
    try:
        if error is not None:
            return PASSED, FAILED, {"reason": error}
        await resume_harness.client.request("thread/resume", {"threadId": thread_id})
        return PASSED, PASSED, detail
    except Exception as exc:
        return PASSED, FAILED, _error_detail(exc)
    finally:
        await resume_harness.close()


async def gate_tool_allowlist(
    command: list[str], timeout: float, expected_server: str | None
) -> tuple[str, dict[str, Any]]:
    """有效 MCP 工具清单。没有配置 MCP 时这条无意义，报 not_run。"""
    if not expected_server:
        return NOT_RUN, {"reason": "--expect-mcp-server not provided"}
    harness, _, error = await _handshake(
        command, capabilities=DECLARED_CAPABILITIES, timeout=timeout
    )
    try:
        if error is not None:
            return FAILED, {"reason": error}
        status = await harness.client.request(
            "mcpServerStatus/list", {"detail": "full", "limit": 50}
        )
        servers: dict[str, list[str]] = {}
        for entry in status.get("data") or []:
            name = entry.get("name") or "?"
            # 真实形状：tools 是**以工具名为键的映射**，不是数组。
            # 当成数组遍历会静默得到空清单——一条"看起来跑通了"的假结果。
            raw_tools = entry.get("tools") or {}
            if isinstance(raw_tools, dict):
                servers[name] = sorted(raw_tools)
            else:
                servers[name] = sorted(
                    tool.get("name")
                    for tool in raw_tools
                    if isinstance(tool, dict) and tool.get("name")
                )
        if expected_server not in servers:
            return FAILED, {"reason": "expected_mcp_server_absent", "servers": sorted(servers)}
        return PASSED, {"servers": servers}
    except Exception as exc:
        return FAILED, _error_detail(exc)
    finally:
        await harness.close()


def _answer_from_questions(params: dict[str, Any]) -> dict[str, Any]:
    """按服务端给出的选项回一个合法答案。

    探针回包不是为了扮演用户，而是为了证明"同一个 id 的请求能被答回去，
    且回合能继续"——只观察不回答的话，验到的只有请求发出去了这一半。
    """
    answers: dict[str, Any] = {}
    for question in params.get("questions") or []:
        options = question.get("options") or []
        if options and question.get("id"):
            answers[question["id"]] = {"answers": [options[0].get("label")]}
    return {"answers": answers}


async def gate_feature_policy(
    command: list[str], timeout: float, must_be_disabled: list[str]
) -> tuple[str, dict[str, Any]]:
    """把"哪些能力必须关着"变成一条会真的说"不"的检查。

    设计 §7 要求默认禁用 shell、任意 HTTP、代码执行、文件写入，并且明说
    "仅设置 read-only sandbox/approvalPolicy 不足以证明工具不可调用"。
    所以这里读的是**运行时的实际开关状态**，不是我们的期望。
    """
    if not must_be_disabled:
        return NOT_RUN, {"reason": "--require-disabled not provided"}
    harness, _, error = await _handshake(
        command, capabilities=DECLARED_CAPABILITIES, timeout=timeout
    )
    try:
        if error is not None:
            return FAILED, {"reason": error}
        response = await harness.client.request("experimentalFeature/list", {})
        states = {
            feature["name"]: bool(feature.get("enabled"))
            for feature in (response.get("data") or [])
            if feature.get("name")
        }
        still_on = [name for name in must_be_disabled if states.get(name) is True]
        missing = [name for name in must_be_disabled if name not in states]
        detail: dict[str, Any] = {
            "checked": must_be_disabled,
            "stillEnabled": still_on,
            "unknownNames": missing,
        }
        if still_on or missing:
            detail["reason"] = "required_features_not_disabled"
            return FAILED, detail
        return PASSED, detail
    except Exception as exc:
        return FAILED, _error_detail(exc)
    finally:
        await harness.close()


async def gate_request_user_input(
    command: list[str], timeout: float, prompt: str
) -> tuple[str, dict[str, Any]]:
    """真实模型提问：只有模型自己决定提问时才会发出原生 request，因此必须真跑。"""
    seen: list[dict[str, Any]] = []
    methods: list[str] = []
    asked = asyncio.Event()

    async def handler(payload: dict[str, Any]) -> dict[str, Any] | None:
        seen.append(payload)
        methods.append(payload.get("method", "?"))
        if payload.get("method") == "item/tool/requestUserInput":
            asked.set()
            return _answer_from_questions(payload.get("params") or {})
        return None

    harness = CodexAppServerHarness(
        command, request_timeout=timeout, capabilities=DECLARED_CAPABILITIES
    )
    harness.set_server_request_handler(handler)
    try:
        await harness.start()
        thread = await harness.create_thread(
            base_instructions=prompt,
            developer_instructions="If the request is ambiguous, ask the user before answering.",
        )
        thread_id = (thread.get("thread") or {}).get("id")
        if not thread_id:
            return FAILED, {"reason": "thread_start_without_id"}
        await harness.start_turn(
            thread_id, [{"type": "text", "text": "帮我看看计算机怎么样"}]
        )
        # turn/start 立刻返回，模型还在后面跑；不等就会把"还没回话"误判成"不会提问"。
        finished = asyncio.ensure_future(
            harness.client.wait_for_notification(
                lambda n: n.get("method") == "turn/completed", timeout=timeout
            )
        )
        await asyncio.wait(
            {finished, asyncio.ensure_future(asked.wait())},
            timeout=timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if not finished.done():
            finished.cancel()
        detail: dict[str, Any] = {"requestMethods": methods}
        if "item/tool/requestUserInput" in methods:
            return PASSED, detail
        detail["reason"] = "no_native_user_input_request"
        return FAILED, detail
    except Exception as exc:
        return FAILED, _error_detail(exc)
    finally:
        await harness.close()


async def gate_elicitation(
    prefix: list[str], timeout: float, fixture: str
) -> tuple[str, dict[str, Any]]:
    """MCP form elicitation 是否真的能走到客户端。

    刻意**不靠模型恰好选择 elicitation**——那是概率，不是能力。
    改用 `mcpServer/tool/call` 直接调用一个"被调用就发 elicitation"的
    fixture MCP server，把链路本身测出来。
    """
    fixture_path = Path(fixture)
    if not fixture_path.exists():
        return NOT_RUN, {"reason": "eliciting fixture not found", "path": str(fixture_path)}

    modes: dict[str, Any] = {}
    for mode in ("legacy", "modern"):
        modes[mode] = await _probe_elicitation_mode(prefix, timeout, fixture_path, mode)
    passed = [mode for mode, item in modes.items() if item.get("status") == PASSED]
    detail: dict[str, Any] = {"modes": modes, "passedModes": passed}
    if passed:
        return PASSED, detail
    # 两种形态都没走到客户端时，要分清"能力不支持"和"夹具没测到"。
    # legacy 是可复现的真结果：服务端自己回了 decline，客户端根本没看见请求。
    # modern 没有测到——它要求先协商现代 MCP 协议版本（params._meta 里带
    # io.modelcontextprotocol/protocolVersion），本夹具没做，报"Unexpected
    # response type"是夹具的错，不是被探对象的错。
    if modes.get("modern", {}).get("status") == NOT_RUN:
        detail["reason"] = "modern_flow_untested_legacy_declined"
        return NOT_RUN, detail
    detail["reason"] = "no_elicitation_mode_reached_client"
    return FAILED, detail


async def _probe_elicitation_mode(
    prefix: list[str], timeout: float, fixture_path: Path, mode: str
) -> dict[str, Any]:
    received: list[dict[str, Any]] = []

    async def handler(payload: dict[str, Any]) -> dict[str, Any] | None:
        received.append(payload)
        if payload.get("method") == "mcpServer/elicitation/request":
            return {"action": "accept", "content": {"approved": True, "note": "probe"}}
        return None

    server_args = [str(fixture_path.resolve())]
    if mode == "modern":
        server_args.append("--modern")
    config = "mcp_servers.eliciting=" + toml_inline(
        {"command": sys.executable, "args": server_args}
    )
    harness = CodexAppServerHarness(
        [*prefix, "-c", config, "app-server", "--stdio"],
        request_timeout=timeout,
        capabilities=DECLARED_CAPABILITIES,
    )
    harness.set_server_request_handler(handler)
    try:
        await harness.start()
        thread = await harness.client.request(
            "thread/start",
            {"threadSource": "user", "approvalPolicy": "never", "sandbox": "read-only"},
        )
        thread_id = (thread.get("thread") or {}).get("id")
        if not thread_id:
            return {"status": FAILED, "reason": "thread_start_without_id"}
        result = await harness.client.request(
            "mcpServer/tool/call",
            {"threadId": thread_id, "server": "eliciting", "tool": "ask_form", "arguments": {}},
        )
        methods = [item.get("method") for item in received]
        text = ""
        for item in result.get("content") or []:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text") or ""
        outcome: dict[str, Any] = {
            "serverRequests": methods,
            "toolResult": text[:300],
        }
        if "mcpServer/elicitation/request" in methods:
            outcome["status"] = PASSED
            return outcome
        if mode == "modern":
            # 现代形态收不到并不说明运行时不支持：它要先协商现代协议版本，
            # 没协商时服务端拒收 input_required 才是正确行为。
            outcome["status"] = NOT_RUN
            outcome["reason"] = "requires_modern_mcp_protocol_negotiation"
            return outcome
        outcome["status"] = FAILED
        outcome["reason"] = "elicitation_not_forwarded_to_client"
        return outcome
    except Exception as exc:
        failed = _error_detail(exc)
        failed["status"] = NOT_RUN if mode == "modern" else FAILED
        if mode == "modern":
            failed["reason"] = "requires_modern_mcp_protocol_negotiation"
        return failed
    finally:
        await harness.close()


async def gate_trusted_mcp_metadata(
    command: list[str], mcp_server: str
) -> tuple[str, dict[str, Any]]:
    if not mcp_server:
        return NOT_RUN, {"reason": "--mcp-server not provided"}
    try:
        result = await check_codex_mcp_metadata(command, mcp_server)
    except Exception as exc:
        # 探针崩掉和被探对象不支持是两回事，但都必须是**记下来的结果**，
        # 不能让一条 gate 的异常吞掉整份报告。
        return FAILED, {"reason": type(exc).__name__, "detail": str(exc)[:200]}
    return (PASSED if result.get("mcp_metadata") == "trusted" else FAILED), result


def _provider_overrides(args: argparse.Namespace) -> list[str]:
    """把模型/provider 拼成 -c 覆盖，不写用户或仓库里的配置文件。

    密钥只以 env_key 的名字出现；值留在环境里，进程结束即失。
    """
    if not args.model or not args.model_provider:
        return []
    provider = {
        "name": args.model_provider,
        "base_url": args.provider_base_url,
        "wire_api": args.wire_api,
    }
    if args.provider_env_key:
        provider["env_key"] = args.provider_env_key
    overrides = [
        "-c",
        f"model={toml_inline(args.model)}",
        "-c",
        f"model_provider={toml_inline(args.model_provider)}",
        "-c",
        f"model_providers.{args.model_provider}={toml_inline(provider)}",
    ]
    for extra in args.config or []:
        overrides.extend(["-c", extra])
    return overrides


def _mcp_overrides(args: argparse.Namespace) -> list[str]:
    """把 --mcp-server 挂成名为 binding 的 MCP server，供工具清单 gate 枚举。"""
    if not args.mcp_server:
        return []
    server = Path(args.mcp_server).resolve()
    value = "mcp_servers.binding=" + toml_inline(
        {"command": sys.executable, "args": [str(server)]}
    )
    return ["-c", value]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bin", default=os.environ.get("CODEX_APP_SERVER_BIN", "codex"))
    parser.add_argument("--source-commit", default=os.environ.get("CODEX_SOURCE_COMMIT", ""))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--real-model",
        action="store_true",
        help="启用需要真实模型的 gates（提问）。未开启时这些 gate 报 not_run。",
    )
    parser.add_argument("--model")
    parser.add_argument("--model-provider")
    parser.add_argument("--provider-base-url", default="")
    parser.add_argument("--provider-env-key", default="")
    parser.add_argument("--wire-api", default="responses")
    parser.add_argument(
        "--config",
        action="append",
        help="额外的 -c 覆盖，可重复。用于 features.default_mode_request_user_input 之类开关。",
    )
    parser.add_argument("--mcp-server", default="")
    parser.add_argument("--expect-mcp-server", default="")
    parser.add_argument(
        "--require-disabled",
        default="",
        help="逗号分隔：这些 experimentalFeature 必须处于关闭状态，否则 featurePolicy 失败。",
    )
    parser.add_argument(
        "--eliciting-fixture",
        default=str(REPO / "tests" / "fixtures" / "mcp" / "eliciting_server.py"),
    )
    parser.add_argument("--skip", action="append", default=[])
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.mcp_server and not args.expect_mcp_server:
        args.expect_mcp_server = "binding"
    # prefix 是"二进制 + 所有 -c 覆盖"，不含子命令。
    # check_codex_mcp_metadata 需要这个形状——它自己会追加 --config 与子命令。
    prefix = [args.bin, *_provider_overrides(args), *_mcp_overrides(args)]
    command = [*prefix, "app-server", "--stdio"]
    report: dict[str, Any] = {
        "generatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "realModel": bool(args.real_model),
        "model": args.model or "",
        "modelProvider": args.model_provider or "",
        "sourceCommit": args.source_commit,
        "sourceCommitEvidence": "configured" if args.source_commit else "not_provided",
        "details": {},
    }
    report.update(_binary_identity(args.bin))

    async def run() -> None:
        skipped = set(args.skip)
        if "initialize" not in skipped:
            report["initialize"], report["details"]["initialize"] = await gate_initialize(
                command, args.timeout
            )
        else:
            report["initialize"] = NOT_RUN

        if not {"threadStart", "resume"} & skipped:
            start_status, resume_status, detail = await gate_thread_and_resume(
                command, args.timeout
            )
            report["threadStart"], report["resume"] = start_status, resume_status
            report["details"]["thread"] = detail
        else:
            report["threadStart"], report["resume"] = NOT_RUN, NOT_RUN

        if "featurePolicy" not in skipped:
            required = [name.strip() for name in args.require_disabled.split(",") if name.strip()]
            report["featurePolicy"], report["details"]["featurePolicy"] = (
                await gate_feature_policy(command, args.timeout, required)
            )
        else:
            report["featurePolicy"] = NOT_RUN

        if "toolAllowlist" not in skipped:
            report["toolAllowlist"], report["details"]["toolAllowlist"] = (
                await gate_tool_allowlist(command, args.timeout, args.expect_mcp_server)
            )
        else:
            report["toolAllowlist"] = NOT_RUN

        if "trustedMcpMetadata" not in skipped:
            report["trustedMcpMetadata"], report["details"]["trustedMcpMetadata"] = (
                await gate_trusted_mcp_metadata(prefix, args.mcp_server)
            )
        else:
            report["trustedMcpMetadata"] = NOT_RUN

        if args.real_model and "requestUserInput" not in skipped:
            report["requestUserInput"], report["details"]["requestUserInput"] = (
                await gate_request_user_input(
                    command,
                    args.timeout,
                    "You are a college application assistant. When the user's request is "
                    "ambiguous (for example a major name that maps to several programs), "
                    "use the request_user_input tool to ask one clarifying question.",
                )
            )
        else:
            report["requestUserInput"] = NOT_RUN
            report["details"]["requestUserInput"] = {
                "reason": "requires --real-model" if not args.real_model else "skipped"
            }

        if "elicitation" not in skipped:
            # elicitation 不依赖模型：由受控 fixture MCP server 触发。
            report["elicitation"], report["details"]["elicitation"] = await gate_elicitation(
                prefix, args.timeout, args.eliciting_fixture
            )
        else:
            report["elicitation"] = NOT_RUN

    asyncio.run(run())

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))

    gate_names = [
        "initialize",
        "threadStart",
        "resume",
        "requestUserInput",
        "elicitation",
        "trustedMcpMetadata",
        "toolAllowlist",
        "featurePolicy",
    ]
    failed = [name for name in gate_names if report.get(name) == FAILED]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
