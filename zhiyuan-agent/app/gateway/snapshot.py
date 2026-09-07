from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.gateway.contracts import ConversationTurnSnapshot, StatePatch


def _first(mapping: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return default


def _nested(mapping: Mapping[str, Any], *path: str) -> Any:
    current: Any = mapping
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def build_snapshot(workspace: Mapping[str, Any]) -> ConversationTurnSnapshot:
    """Project backend workspace state into a bounded model-facing snapshot."""
    if not isinstance(workspace, Mapping):
        raise ValueError("workspace payload must be an object")
    session_id = _first(workspace, "sessionId", "session_id")
    if session_id in (None, ""):
        raise ValueError("workspace sessionId is required")

    summary = workspace.get("studentSummary") or {}
    profile = workspace.get("profileState") or {}
    constraints = workspace.get("constraintState") or {}
    explicit = profile.get("explicitProfile") or {}
    hard = constraints.get("hardConstraints") or {}
    soft = constraints.get("softPreferences") or {}

    score_context = {
        key: value
        for key, value in {
            "province": _first(summary, "provinceName", "province"),
            "examYear": _first(summary, "examYear", "year"),
            "score": _first(summary, "score"),
            "rank": _first(summary, "rank", "position"),
            "batch": _first(summary, "batchName", "batch"),
            "subjects": _first(summary, "subjects", default=[]),
        }.items()
        if value not in (None, "")
    }
    confirmed_constraints = {
        key: value
        for key, value in {
            "hard": hard,
            "excludedMajors": _first(explicit, "negativeMajors", default=[]),
            "excludedSchools": _first(explicit, "negativeSchools", default=[]),
            "excludedRegions": _first(explicit, "negativeRegions", default=[]),
            "exclusions": _first(
                explicit,
                "unacceptableMajors",
                "excludedMajors",
                "negativeMajors",
                default=[],
            ),
        }.items()
        if value not in (None, {}, [])
    }
    preferences = {
        key: value
        for key, value in {
            "major": _first(explicit, "majorPreferences", "positiveMajors", default={}),
            "school": _first(explicit, "schoolPreferences", "positiveSchools", default={}),
            "region": _first(explicit, "regionPreferences", "positiveRegions", default={}),
            "soft": soft,
        }.items()
        if value not in (None, {}, [])
    }

    missing = list(workspace.get("missingFacts") or [])
    if "score" not in score_context and "score" not in missing:
        missing.append("score")
    if "rank" not in score_context and "rank" not in missing:
        missing.append("rank")

    allowed = list(workspace.get("allowedCapabilities") or [])
    if not allowed:
        allowed = ["catalog_read", "admission_read"]
    allowed = [capability for capability in allowed if capability not in {"plan_apply", "write", "shell"}]

    return ConversationTurnSnapshot(
        snapshot_version=int(_first(workspace, "version", "snapshotVersion", default=0) or 0),
        session_id=str(session_id),
        planning_stage=str(_first(workspace, "phase", "planningStage", default="")),
        score_context=score_context,
        confirmed_constraints=confirmed_constraints,
        preferences=preferences,
        active_proposal=workspace.get("activeProposal"),
        missing_facts=missing,
        allowed_capabilities=allowed,
        evidence=list(workspace.get("evidence") or []),
    )


def diff_snapshots(
    before: ConversationTurnSnapshot, after: ConversationTurnSnapshot
) -> StatePatch:
    if after.snapshot_version != before.snapshot_version + 1:
        raise ValueError("snapshot versions must be adjacent")
    before_payload = before.model_dump(by_alias=True)
    after_payload = after.model_dump(by_alias=True)
    allowed = {
        "scoreContext",
        "confirmedConstraints",
        "preferences",
        "planningStage",
        "activeProposal",
        "missingFacts",
        "allowedCapabilities",
    }
    changes = [
        {"path": path, "oldValue": before_payload[path], "newValue": after_payload[path]}
        for path in allowed
        if before_payload[path] != after_payload[path]
    ]
    invalidations: list[dict[str, Any]] = []
    before_stale = set(before.missing_facts)
    after_stale = set(after.missing_facts)
    for fact in sorted(after_stale - before_stale):
        invalidations.append({"path": "missingFacts", "fact": fact})
    return StatePatch(
        base_version=before.snapshot_version,
        target_version=after.snapshot_version,
        changes=changes,
        invalidations=invalidations,
    )
