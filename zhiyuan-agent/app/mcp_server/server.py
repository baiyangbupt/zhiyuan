from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from app.harness.binding import ThreadBinding
from app.mcp_server.tools_readonly import CAPABILITIES, ReadonlyDomainTools

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
        "areaId", "batch", "schoolId", "majorId", "year", "subjectType"
    ),
    "admission.check_eligibility": _input_schema("majorId"),
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
    },
    "additionalProperties": False,
}


class DomainMcpServer:
    def __init__(self, tools: ReadonlyDomainTools | None = None) -> None:
        self.tools = {name: None for name in READONLY_TOOL_NAMES}
        self.tool_runner = tools


def build_server() -> DomainMcpServer:
    return DomainMcpServer()


def build_sdk_server(tool_runner: ReadonlyDomainTools) -> Any:
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
        return await tool_runner.call(name, arguments or {})

    return server


async def serve() -> None:
    binding = ThreadBinding(
        thread_id="stdio",
        tenant_id="stdio",
        session_id="stdio",
        user_id="stdio",
        allowed_capabilities=frozenset({"catalog_read", "admission_read"}),
    )
    tools = ReadonlyDomainTools(binding, backend=None)
    if stdio_server is None:  # pragma: no cover
        raise RuntimeError("mcp SDK is not installed")
    server = build_sdk_server(tools)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        print(json.dumps({"tools": sorted(READONLY_TOOL_NAMES), "write_tools": 0}, ensure_ascii=False))
        return
    asyncio.run(serve())


if __name__ == "__main__":
    main()
