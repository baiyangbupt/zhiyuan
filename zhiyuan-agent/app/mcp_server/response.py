from __future__ import annotations

from typing import Any, Iterable


def ok(
    data: Any,
    *,
    state_version: int,
    evidence: Iterable[Any] = (),
    entities: Iterable[Any] = (),
    limitations: Iterable[str] = (),
    admission_mode: str | None = None,
    data_version: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "ok",
        "data": data,
        "resolvedEntities": list(entities),
        "evidence": list(evidence),
        "limitations": list(limitations),
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
    state_version: int,
    limitations: Iterable[str] = (),
    missing_fields: Iterable[str] = (),
    admission_mode: str | None = None,
    data_version: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": status,
        "data": {"message": message},
        "resolvedEntities": [],
        "evidence": [],
        "limitations": list(limitations),
        "stateVersion": state_version,
    }
    missing = list(missing_fields)
    if missing:
        result["data"]["missingFields"] = missing
    if admission_mode is not None:
        result["admissionMode"] = admission_mode
    if data_version is not None:
        result["dataVersion"] = data_version
    return result
