from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from app.gateway.contracts import ConversationTurnSnapshot, TurnOutput


class OutputContractError(ValueError):
    """Raised when model output cannot be proven safe for the current turn."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def _field(value: Any, *names: str) -> Any:
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
    else:
        for name in names:
            if hasattr(value, name):
                return getattr(value, name)
    return None


def _as_output(value: TurnOutput | Mapping[str, Any]) -> TurnOutput:
    if isinstance(value, TurnOutput):
        return value
    try:
        return TurnOutput.model_validate(value)
    except ValidationError as exc:
        raise OutputContractError("schema_invalid", str(exc)) from exc


def _as_snapshot(value: ConversationTurnSnapshot | Mapping[str, Any]) -> ConversationTurnSnapshot:
    if isinstance(value, ConversationTurnSnapshot):
        return value
    try:
        return ConversationTurnSnapshot.model_validate(value)
    except ValidationError as exc:
        raise OutputContractError("snapshot_invalid", str(exc)) from exc


def validate_turn_output(
    *,
    turn_output: TurnOutput | Mapping[str, Any],
    current_snapshot: ConversationTurnSnapshot | Mapping[str, Any],
    evidence_ledger: Mapping[str, Any],
    artifacts: Mapping[str, Any],
    thread_id: str | None = None,
    tenant_id: str | None = None,
    allow_proposal: bool = False,
) -> TurnOutput:
    """Validate every backend reference before output reaches a user.

    The model can only reference records already issued by the current
    Gateway turn.  Optional scope fields are checked when present in a ledger
    entry; absence is not treated as proof of a different scope.
    """
    output = _as_output(turn_output)
    snapshot = _as_snapshot(current_snapshot)

    if output.proposal_ref and not allow_proposal:
        raise OutputContractError("proposal_forbidden", "proposal output is disabled in readonly mode")

    for reference in output.evidence_refs:
        evidence_id = reference.evidence_id
        entry = evidence_ledger.get(evidence_id)
        if entry is None:
            raise OutputContractError("evidence_not_found", evidence_id)
        entry_session = _field(entry, "sessionId", "session_id")
        if entry_session not in (None, "", snapshot.session_id):
            raise OutputContractError("evidence_scope_violation", evidence_id)
        entry_thread = _field(entry, "threadId", "thread_id")
        if thread_id and entry_thread not in (None, "", thread_id):
            raise OutputContractError("evidence_scope_violation", evidence_id)
        entry_tenant = _field(entry, "tenantId", "tenant_id")
        if tenant_id and entry_tenant not in (None, "", tenant_id):
            raise OutputContractError("evidence_scope_violation", evidence_id)
        entry_state = _field(entry, "stateVersion", "state_version")
        if entry_state not in (None, ""):
            try:
                parsed_state = int(entry_state)
            except (TypeError, ValueError) as exc:
                raise OutputContractError("evidence_invalid", evidence_id) from exc
            if parsed_state != snapshot.snapshot_version:
                raise OutputContractError("stale_state", evidence_id)
        entry_version = _field(entry, "dataVersion", "data_version")
        if entry_version not in (None, "") and str(entry_version) != reference.data_version:
            raise OutputContractError("evidence_mismatch", evidence_id)

    for reference in output.artifact_refs:
        artifact_id = reference.artifact_id
        entry = artifacts.get(artifact_id)
        if entry is None:
            raise OutputContractError("artifact_not_found", artifact_id)
        entry_state = _field(entry, "stateVersion", "state_version")
        if entry_state not in (None, ""):
            try:
                parsed_state = int(entry_state)
            except (TypeError, ValueError) as exc:
                raise OutputContractError("artifact_invalid", artifact_id) from exc
            if parsed_state != snapshot.snapshot_version:
                raise OutputContractError("stale_state", artifact_id)
        if reference.state_version != snapshot.snapshot_version:
            raise OutputContractError("stale_state", artifact_id)
        entry_session = _field(entry, "sessionId", "session_id")
        if entry_session not in (None, "", snapshot.session_id):
            raise OutputContractError("artifact_scope_violation", artifact_id)
        entry_thread = _field(entry, "threadId", "thread_id")
        if thread_id and entry_thread not in (None, "", thread_id):
            raise OutputContractError("artifact_scope_violation", artifact_id)

    return output
