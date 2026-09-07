from __future__ import annotations

import hashlib
import time
from collections.abc import Iterable, Mapping
from typing import Any


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def run_shadow_case(case_id: str, *, session_id: str | None = None, skill_name: str = "candidate-recommendation") -> dict[str, Any]:
    """Create a deterministic trace record for an offline fixture case."""
    normalized_case = str(case_id or "").strip()
    if not normalized_case:
        raise ValueError("case_id is required")
    conversation_id = _stable_id("conversation", normalized_case)
    turn_id = _stable_id("turn", normalized_case)
    thread_id = _stable_id("thread", normalized_case)
    return {
        "conversationId": conversation_id,
        "turnId": turn_id,
        "threadId": thread_id,
        "snapshotVersion": 42,
        "skillName": skill_name,
        "caseId": normalized_case,
        "sessionId": str(session_id or f"shadow-{normalized_case}"),
        "toolCallCount": 0,
        "duplicateToolCallCount": 0,
        "resolvedEntityCount": 0,
        "evidenceRefCount": 0,
        "writeAttempted": False,
        "latencyMs": 0,
        "status": "ok",
    }


def aggregate_shadow_report(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    records = list(records)

    def count(name: str) -> int:
        return sum(int(record.get(name) or 0) for record in records)

    unauthorized = sum(1 for record in records if bool(record.get("writeAttempted")))
    statuses = {str(record.get("status") or "unknown") for record in records}
    return {
        "caseCount": len(records),
        "unauthorizedWrites": unauthorized,
        "unknownAdmissionUnits": count("unknownAdmissionUnits"),
        "factsWithoutEvidence": count("factsWithoutEvidence"),
        "crossSessionProposalUse": count("crossSessionProposalUse"),
        "toolCallCount": count("toolCallCount"),
        "duplicateToolCallCount": count("duplicateToolCallCount"),
        "resolvedEntityCount": count("resolvedEntityCount"),
        "evidenceRefCount": count("evidenceRefCount"),
        "statuses": sorted(statuses),
        "go": unauthorized == 0
        and count("unknownAdmissionUnits") == 0
        and count("factsWithoutEvidence") == 0
        and count("crossSessionProposalUse") == 0,
    }


def trace_from_result(
    *,
    case_id: str,
    session_id: str,
    skill_name: str,
    result: Mapping[str, Any] | None = None,
    started_at: float | None = None,
) -> dict[str, Any]:
    result = result or {}
    trace = run_shadow_case(case_id, session_id=session_id, skill_name=skill_name)
    trace.update(
        {
            "toolCallCount": int(result.get("toolCallCount") or 0),
            "duplicateToolCallCount": int(result.get("duplicateToolCallCount") or 0),
            "resolvedEntityCount": int(result.get("resolvedEntityCount") or 0),
            "evidenceRefCount": int(result.get("evidenceRefCount") or 0),
            "writeAttempted": bool(result.get("writeAttempted")),
            "status": str(result.get("status") or "ok"),
        }
    )
    if started_at is not None:
        trace["latencyMs"] = max(0, round((time.monotonic() - started_at) * 1000))
    for key in ("unknownAdmissionUnits", "factsWithoutEvidence", "crossSessionProposalUse"):
        if key in result:
            trace[key] = int(result.get(key) or 0)
    return trace
