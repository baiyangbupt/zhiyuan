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
from app.mcp_server.tools_readonly import CAPABILITIES, InternalClientBackend, ReadonlyDomainTools

try:
    from mcp.server import Server as SdkServer
    from mcp.server.models import InitializationOptions
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool
except ImportError:  # pragma: no cover - exercised only before dependency installation
    SdkServer = None  # type: ignore[assignment,misc]
    InitializationOptions = Any  # type: ignore[assignment,misc]
    stdio_server = None  # type: ignore[assignment]
    Tool = Any  # type: ignore[assignment,misc]

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
    "admission.get_history": _input_schema(
        "areaId", "batch", "schoolId", "year", "subjectType"
    ),
    "admission.check_eligibility": _input_schema(),
}

TOOL_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "status",
        "data",
        "resolvedEntities",
        "evidence",
        "limitations",
        "stateVersion",
    ],
    "properties": {
        "status": {"type": "string"},
        "data": {},
        "resolvedEntities": {"type": "array", "items": {}},
        "evidence": {"type": "array", "items": {}},
        "limitations": {"type": "array", "items": {"type": "string"}},
        "stateVersion": {"type": "integer"},
        "admissionMode": {"type": "string", "enum": ["major", "major_group"]},
        "dataVersion": {"type": "string"},
    },
    "additionalProperties": False,
}


class DomainMcpServer:
    def __init__(self, tools: ReadonlyDomainTools | None = None) -> None:
        self.tools = {name: None for name in READONLY_TOOL_NAMES}
        self.tool_runner = tools


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
                name=name,
                description="Zhiyuan authoritative read-only domain query",
                inputSchema=TOOL_INPUT_SCHEMAS[name],
                outputSchema=TOOL_OUTPUT_SCHEMA,
            )
            for name in sorted(READONLY_TOOL_NAMES)
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
                return error("tool_not_found", name, state_version=0)
            binding = await binding_registry.resolve(
                thread_id=thread_id,
                capability=capability,
            )
        except TrustedContextError as exc:
            return error(str(exc), "trusted binding is unavailable", state_version=0)
        active_tool_runner = ReadonlyDomainTools(
            binding,
            backend=InternalClientBackend(
                tenant_id=binding.tenant_id,
                chat_session_id=binding.session_id,
            ),
        )
    if active_tool_runner is None:
        return error("binding_unconfigured", "trusted binding is unavailable", state_version=0)
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
            result = {
                "tools": [
                    {
                        "name": name,
                        "description": "Zhiyuan authoritative read-only domain query",
                        "inputSchema": TOOL_INPUT_SCHEMAS[name],
                    }
                    for name in sorted(READONLY_TOOL_NAMES)
                ]
            }
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
        if request_id is not None and result is not None:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}, ensure_ascii=False) + "\n")
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
