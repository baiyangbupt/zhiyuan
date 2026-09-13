from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


TurnStatus = Literal["completed", "failed", "interrupted", "timed_out"]


@dataclass(slots=True)
class CodexTurnResult:
    status: TurnStatus
    turn_id: str | None = None
    output: dict[str, Any] | None = None
    output_extraction: dict[str, Any] = field(
        default_factory=lambda: {"source": "missing", "candidateCount": None}
    )
    events: list[dict[str, Any]] = field(default_factory=list)
    error_code: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
