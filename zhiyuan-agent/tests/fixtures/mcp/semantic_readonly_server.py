#!/usr/bin/env python3
"""Deterministic read-only MCP server for real Codex semantic smoke tests."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


TRACE_PATH = os.environ.get("ZHIYUAN_SEMANTIC_MCP_TRACE", "")


def send(request_id: object, result: dict) -> None:
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def record(name: str, arguments: dict) -> None:
    if not TRACE_PATH:
        return
    path = Path(TRACE_PATH)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"name": name, "arguments": arguments}, ensure_ascii=False) + "\n")


def tool_list() -> list[dict]:
    return [
        {
            "name": "catalog.search_schools",
            "description": "只读查询学校候选。",
            "inputSchema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            "name": "admission.get_history",
            "description": "只读查询某学校某专业的历史录取分数。缺少范围参数时必须先澄清。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "schoolId": {"type": "string"},
                    "majorId": {"type": "string"},
                    "areaId": {"type": "string"},
                    "batch": {"type": "string"},
                    "year": {"type": "integer"},
                    "subjectType": {"type": "string"},
                },
                "required": ["schoolId", "majorId", "areaId", "batch", "year", "subjectType"],
                "additionalProperties": False,
            },
        },
    ]


def call_tool(name: str, arguments: dict) -> dict:
    record(name, arguments)
    if name == "catalog.search_schools":
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "status": "ok",
                            "resolvedEntities": [
                                {"entityId": "school-1", "entityType": "school", "name": "甲大学"},
                                {"entityId": "school-2", "entityType": "school", "name": "乙大学"},
                            ],
                            "dataVersion": "semantic-fixture-1",
                        },
                        ensure_ascii=False,
                    ),
                }
            ],
            "isError": False,
        }
    if name == "admission.get_history":
        required = ("schoolId", "majorId", "areaId", "batch", "year", "subjectType")
        missing = [key for key in required if arguments.get(key) in (None, "")]
        payload = {
            "status": "needs_clarification" if missing else "ok",
            "data": {"missing": missing}
            if missing
            else {
                "history": [
                    {
                        "schoolId": arguments["schoolId"],
                        "majorId": arguments["majorId"],
                        "year": arguments["year"],
                        "minimumScore": 612 if arguments["schoolId"] == "school-1" else 598,
                    }
                ],
                "dataVersion": "semantic-fixture-1",
            },
            "limitations": ["semantic_fixture_only"],
        }
        return {
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
            "isError": False,
        }
    return {"content": [{"type": "text", "text": "unknown tool"}], "isError": True}


for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    request_id = request.get("id")
    params = request.get("params") or {}
    if method == "initialize":
        send(
            request_id,
            {
                "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "zhiyuan-semantic-fixture", "version": "0.1.0"},
            },
        )
    elif method == "notifications/initialized":
        continue
    elif method == "tools/list":
        send(request_id, {"tools": tool_list()})
    elif method == "tools/call":
        send(request_id, call_tool(str(params.get("name") or ""), params.get("arguments") or {}))
    elif request_id is not None:
        send(request_id, {})
