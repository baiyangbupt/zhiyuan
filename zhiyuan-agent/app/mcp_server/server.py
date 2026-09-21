from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.mcp_server.context import (
    ThreadBindingRegistry,
    TrustedContextError,
    extract_trusted_thread_id,
    extract_trusted_thread_id_from_metadata,
)
from app.mcp_server.response import error
from app.mcp_server.tools_readonly import (
    CAPABILITIES,
    InternalClientBackend,
    ReadonlyDomainTools,
    _kind_for,
)
from app.util import internal_client

try:
    from mcp.server import Server as SdkServer
    from mcp.server.models import InitializationOptions
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, ToolAnnotations
except ImportError:  # pragma: no cover - exercised only before dependency installation
    SdkServer = None  # type: ignore[assignment,misc]
    InitializationOptions = Any  # type: ignore[assignment,misc]
    stdio_server = None  # type: ignore[assignment]
    Tool = Any  # type: ignore[assignment,misc]
    ToolAnnotations = Any  # type: ignore[assignment,misc]

READONLY_TOOL_NAMES = frozenset(CAPABILITIES)
MCP_PROTOCOL_VERSION = "2024-11-05"

_COMMON_INPUT_PROPERTIES: dict[str, Any] = {
    "query": {"type": "string", "description": "用户提供的院校或专业名称"},
    "entityType": {"type": "string", "enum": ["school", "major"]},
    "name": {"type": "string"},
    "schoolId": {"type": "string"},
    "majorId": {"type": "string"},
    "groupCode": {"type": "string"},
    "admissionMode": {"type": "string", "enum": ["major", "major_group", "majorGroup"]},
    "province": {"type": "string"},
    "city": {"type": "string"},
    "schoolType": {"type": "string"},
    "ownership": {"type": "string"},
    "educationLevel": {"type": "string"},
    "areaId": {"type": "string"},
    "batch": {"type": "string"},
    "year": {"type": "integer"},
    "subjectType": {"type": "string"},
    "stateVersion": {"type": "integer"},
}


def _input_schema(*required: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": dict(_COMMON_INPUT_PROPERTIES),
        "required": list(required),
        "additionalProperties": False,
    }


TOOL_INPUT_SCHEMAS: dict[str, dict[str, Any]] = {
    "entity.resolve": _input_schema("query"),
    "catalog.search_schools": _input_schema(),
    "catalog.get_school": _input_schema(),
    "catalog.search_majors": _input_schema(),
    "catalog.get_major": _input_schema(),
    "admission.get_current_plan": _input_schema(),
    # 新名与旧名共用同一份 schema：它们是同一个工具，形状不该有两份。
    "planning.get_working_plan": _input_schema(),
    "admission.get_history": _input_schema(
        "areaId", "batch", "schoolId", "year", "subjectType"
    ),
    "admission.check_eligibility": _input_schema(),
}

TOOL_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "schemaVersion",
        "kind",
        "status",
        "data",
        "evidenceRefs",
        "resolvedEntities",
        "limitations",
        "nextCursor",
        "stateVersion",
    ],
    "properties": {
        "schemaVersion": {"type": "integer", "enum": [1]},
        # `kind` 决定 `data` 的形状。六种数据混用会让"这是历史分数还是录取概率"
        # 变成一个靠字段猜的问题，而猜错的方向是把过去当未来。
        "kind": {
            "type": "string",
            "enum": ["catalog", "history", "probability", "enrollment", "policy", "eligibility", "workingPlan"],
        },
        "status": {"type": "string"},
        "data": {},
        # 证据**本体**（Java 签发），不是指向证据的编号：下游账本要用它做跨回合核验。
        "evidenceRefs": {"type": "array", "items": {}},
        "resolvedEntities": {"type": "array", "items": {}},
        "limitations": {"type": "array", "items": {"type": "string"}},
        "nextCursor": {"type": ["string", "null"]},
        "stateVersion": {"type": "integer"},
        "admissionMode": {"type": "string", "enum": ["major", "major_group"]},
        "dataVersion": {"type": "string"},
        "code": {"type": "string"},
    },
    "additionalProperties": False,
}


class DomainMcpServer:
    def __init__(self, tools: ReadonlyDomainTools | None = None) -> None:
        self.tools = {name: None for name in READONLY_TOOL_NAMES}
        self.tool_runner = tools


def tool_listing() -> list[dict[str, Any]]:
    """工具清单的**唯一来源**：生产 stdio 循环与 SDK server 都从这里取。

    以前这里写了两遍，于是它们分叉了：`readOnlyHint` 只加在 SDK 那份上，
    而生产走的是手写循环，线上工具因此没有只读注解——真实二进制对未声明只读的
    MCP 工具一律要求审批，而生产策略是 approvalPolicy=never，无处可批，
    结果每个域内调用都以 `MCP tool call requires approval, but approval
    policy is never` 失败。两份清单从同一处生成，这个分叉就不可能再发生。

    注解同时是安全承诺，必须与 `READONLY_TOOL_NAMES` 严格一致。
    """
    annotations = {"readOnlyHint": True}
    return [
        {
            "name": name,
            "description": "Zhiyuan authoritative read-only domain query",
            "inputSchema": TOOL_INPUT_SCHEMAS[name],
            "annotations": dict(annotations),
        }
        for name in sorted(READONLY_TOOL_NAMES)
    ]


def build_server() -> DomainMcpServer:
    return DomainMcpServer()


def build_sdk_server(
    tool_runner: ReadonlyDomainTools | None = None,
    *,
    binding_registry: ThreadBindingRegistry | None = None,
) -> Any:
    """Build the production MCP SDK server around the governed tool runner.

    The SDK owns JSON-RPC framing and schema validation.  Domain authorization,
    state checks, retries and evidence scoping remain in ``ReadonlyDomainTools``.
    """
    if SdkServer is None:  # pragma: no cover - dependency is declared and installed in CI
        raise RuntimeError("mcp SDK is not installed")

    server = SdkServer(
        "zhiyuan-domain-readonly",
        version="0.1.0",
        instructions="Read-only Zhiyuan catalog and admission facts; all writes are denied.",
    )

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name=entry["name"],
                description=entry["description"],
                inputSchema=entry["inputSchema"],
                outputSchema=TOOL_OUTPUT_SCHEMA,
                annotations=ToolAnnotations(**entry["annotations"]),
            )
            for entry in tool_listing()
        ]

    @server.call_tool(validate_input=True)
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        metadata = getattr(server.request_context, "meta", None) or {}
        return await _call_domain_tool(
            name,
            arguments or {},
            metadata=metadata,
            binding_registry=binding_registry,
            fallback_tool_runner=tool_runner,
        )

    return server


async def _call_domain_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    metadata: object,
    binding_registry: ThreadBindingRegistry | None,
    fallback_tool_runner: ReadonlyDomainTools | None = None,
) -> dict[str, Any]:
    active_tool_runner = fallback_tool_runner
    if binding_registry is not None:
        try:
            thread_id = extract_trusted_thread_id_from_metadata(metadata)
            capability = CAPABILITIES.get(name)
            if capability is None:
                return error("tool_not_found", name, kind=_kind_for(name), state_version=0)
            binding = await binding_registry.resolve(
                thread_id=thread_id,
                capability=capability,
            )
        except TrustedContextError as exc:
            return error(str(exc), "trusted binding is unavailable", kind=_kind_for(name), state_version=0)
        try:
            expected_state_version = binding.snapshot_version
            if expected_state_version is None:
                raise ValueError("binding snapshot version is missing")
            expected_state_version = int(expected_state_version)
            if expected_state_version < 0:
                raise ValueError("negative binding snapshot version")
        except (TypeError, ValueError, AttributeError) as exc:
            return error("state_version_unavailable", str(exc), kind=_kind_for(name), state_version=0)
        try:
            snapshot_response = await internal_client.get_conversation_turn_snapshot(
                binding.tenant_id,
                binding.session_id,
            )
            snapshot_data = (snapshot_response or {}).get("data") or {}
            raw_version = snapshot_data.get("snapshotVersion", snapshot_data.get("version"))
            state_version = int(raw_version)
            if state_version < 0:
                raise ValueError("negative snapshot version")
        except (TypeError, ValueError, AttributeError, KeyError, RuntimeError) as exc:
            return error("state_version_unavailable", str(exc), kind=_kind_for(name), state_version=0)
        if state_version != expected_state_version:
            return error(
                "stale_state",
                "the authoritative snapshot changed during this turn",
                kind=_kind_for(name),
                state_version=state_version,
            )
        active_tool_runner = ReadonlyDomainTools(
            binding,
            backend=InternalClientBackend(
                tenant_id=binding.tenant_id,
                chat_session_id=binding.session_id,
                thread_id=binding.thread_id,
            ),
            current_state_version=state_version,
        )
    if active_tool_runner is None:
        return error("binding_unconfigured", "trusted binding is unavailable", kind=_kind_for(name), state_version=0)
    return await active_tool_runner.call(name, arguments)


def serve(binding_registry_path: str) -> None:
    """Run a minimal JSON-RPC stdio MCP server compatible with Codex App Server.

    The installed MCP SDK's stdio transport does not consume stdin in this
    deployment environment.  We retain its schema builder for tests while the
    production transport uses the small, protocol-specific loop below.
    """
    registry = ThreadBindingRegistry(binding_registry_path)
    for raw_line in sys.stdin:
        try:
            request = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        method = request.get("method")
        request_id = request.get("id")
        params = request.get("params") or {}
        result: dict[str, Any] | None = None
        if method == "initialize":
            result = {
                "protocolVersion": params.get("protocolVersion", MCP_PROTOCOL_VERSION),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "zhiyuan-domain-readonly", "version": "0.1.0"},
                "instructions": "Read-only Zhiyuan catalog and admission facts; all writes are denied.",
            }
        elif method == "tools/list":
            result = {"tools": tool_listing()}
        elif method == "tools/call":
            outcome = asyncio.run(
                _call_domain_tool(
                    str(params.get("name") or ""),
                    dict(params.get("arguments") or {}),
                    metadata=params.get("_meta") or {},
                    binding_registry=registry,
                )
            )
            result = {
                "content": [{"type": "text", "text": json.dumps(outcome, ensure_ascii=False)}],
                "isError": False,
            }
        elif method == "resources/list":
            # 我们不暴露 resource，但**必须回答**：真实 MCP 客户端在握手后会
            # 逐一探测 resources/list 与 resources/templates/list，收不到应答就
            # 一直等，整个 server 卡在未连接状态（实测 mcpServerStatus/list 超时）。
            result = {"resources": []}
        elif method == "resources/templates/list":
            result = {"resourceTemplates": []}
        elif method == "prompts/list":
            result = {"prompts": []}
        if request_id is None:
            continue
        if result is None:
            # 兜底：任何**未识别但带 id** 的请求都要明确回错。
            # 沉默不是"优雅降级"，是让对方永久挂起——握手失败点上没有任何日志。
            response: dict[str, Any] = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": f"method not found: {method}"},
            }
        else:
            response = {"jsonrpc": "2.0", "id": request_id, "result": result}
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--binding-registry", default="")
    args = parser.parse_args()
    if args.self_check:
        print(json.dumps({"tools": sorted(READONLY_TOOL_NAMES), "write_tools": 0}, ensure_ascii=False))
        return
    if not args.binding_registry:
        parser.error("--binding-registry is required for MCP serving")
    serve(args.binding_registry)


if __name__ == "__main__":
    main()
