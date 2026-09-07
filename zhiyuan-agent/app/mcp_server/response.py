from __future__ import annotations

from typing import Any, Iterable


def ok(
    data: Any,
    *,
    state_version: int,
    evidence: Iterable[Any] = (),
    entities: Iterable[Any] = (),
    limitations: Iterable[str] = (),
) -> dict[str, Any]:
    return {
        "status": "ok",
        "data": data,
        "resolvedEntities": list(entities),
        "evidence": list(evidence),
        "limitations": list(limitations),
        "stateVersion": state_version,
    }


def error(status: str, message: str, *, state_version: int) -> dict[str, Any]:
    return {
        "status": status,
        "data": {"message": message},
        "resolvedEntities": [],
        "evidence": [],
        "limitations": [],
        "stateVersion": state_version,
    }
