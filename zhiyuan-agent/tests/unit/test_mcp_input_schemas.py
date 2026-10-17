"""MCP 工具入参 schema 必须与 handler 同形。

2026-10-17 真事故（§五-65）：公共属性给**所有**工具塞了 `entities`，模型据此
对 `admission.check_eligibility` 发批量调用；handler 只认单条 `majorId`，
整批报 "majorId is required" 后退化成逐条重试 → 一个续接回合 15 次资格核验。
schema 是模型看到的契约，多给一个不存在的入参就是在教它发错调用。
"""

from __future__ import annotations

from app.mcp_server.server import TOOL_INPUT_SCHEMAS


def test_check_eligibility_schema_only_accepts_a_single_major() -> None:
    schema = TOOL_INPUT_SCHEMAS["admission.check_eligibility"]
    properties = schema["properties"]

    assert "entities" not in properties, "handler 没有批量入口，schema 不许给批量参数"
    assert schema["required"] == ["majorId"]
    assert "单个专业" in properties["majorId"]["description"]
    assert "一次只核一个" in properties["majorId"]["description"]


def test_entities_is_only_exposed_by_compare() -> None:
    """`entities` 是 compare 的专属入参；其他工具被塞上它就是契约分叉。"""
    holders = sorted(
        name
        for name, schema in TOOL_INPUT_SCHEMAS.items()
        if "entities" in (schema.get("properties") or {})
    )

    assert holders == ["admission.compare"]


def test_compare_keeps_its_batch_contract() -> None:
    schema = TOOL_INPUT_SCHEMAS["admission.compare"]

    assert schema["properties"]["entities"] == {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"schoolId": {"type": "string"}, "majorId": {"type": "string"}},
            "additionalProperties": False,
        },
    }
    assert set(schema["required"]) == {"entities", "areaId", "batch", "year", "subjectType"}
