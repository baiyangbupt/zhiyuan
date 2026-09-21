"""Domain MCP 的统一外层。

六种数据（历史 / 概率 / 招生计划 / 章程 / 资格 / 当前方案）共用这一个外层，
`data` 的形状由 `kind` 决定。**外层统一不等于内容可以混**：把历史分数当成
录取概率、把学校口径的率当成专业组的，都是这一层要防的事。

`evidenceRefs` 放的是 Java 签发的证据**本体**（含 ID、来源系统、参数摘要、
数据版本），不是"指向证据的某个编号"——下游账本要用它做跨回合核验，
只给一个编号等于让核验无从做起。
"""
from __future__ import annotations

from typing import Any, Iterable

SCHEMA_VERSION = 1


def ok(
    data: Any,
    *,
    kind: str,
    state_version: int,
    evidence: Iterable[Any] = (),
    entities: Iterable[Any] = (),
    limitations: Iterable[str] = (),
    admission_mode: str | None = None,
    data_version: str | None = None,
    next_cursor: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": kind,
        "status": "ok",
        "data": data,
        "evidenceRefs": list(evidence),
        "resolvedEntities": list(entities),
        "limitations": list(limitations),
        "nextCursor": next_cursor,
        "stateVersion": state_version,
    }
    if admission_mode is not None:
        result["admissionMode"] = admission_mode
    if data_version is not None:
        result["dataVersion"] = data_version
    return result


def error(
    status: str,
    message: str,
    *,
    kind: str,
    state_version: int,
    limitations: Iterable[str] = (),
    missing_fields: Iterable[str] = (),
    admission_mode: str | None = None,
    data_version: str | None = None,
    code: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": kind,
        "status": status,
        "data": {"message": message},
        "evidenceRefs": [],
        "resolvedEntities": [],
        "limitations": list(limitations),
        "nextCursor": None,
        "stateVersion": state_version,
    }
    missing = list(missing_fields)
    if missing:
        result["data"]["missingFields"] = missing
    if code is not None:
        # 机器可读的降级原因：调用方靠它选路径，靠 message 只能靠正则。
        result["code"] = code
    if admission_mode is not None:
        result["admissionMode"] = admission_mode
    if data_version is not None:
        result["dataVersion"] = data_version
    return result
