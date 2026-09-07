from __future__ import annotations

import pytest

from app.gateway.contracts import ConversationTurnSnapshot, EvidenceRef, TurnOutput
from app.gateway.output_validation import OutputContractError, validate_turn_output


def _snapshot(version: int = 42) -> ConversationTurnSnapshot:
    return ConversationTurnSnapshot(
        snapshot_version=version,
        session_id="session-1",
        planning_stage="candidate_exploration",
    )


def _fact_output(*evidence_ids: str) -> TurnOutput:
    return TurnOutput(
        response_type="fact",
        message="招生事实",
        evidence_refs=[
            EvidenceRef(
                evidence_id=evidence_id,
                source_level="authoritative",
                data_version="2026.09.07",
            )
            for evidence_id in evidence_ids
        ],
    )


def test_output_validator_rejects_unknown_evidence() -> None:
    with pytest.raises(OutputContractError, match="evidence_not_found"):
        validate_turn_output(
            turn_output=_fact_output("ev-missing"),
            current_snapshot=_snapshot(),
            evidence_ledger={"ev-known": {"evidenceId": "ev-known"}},
            artifacts={},
        )


def test_output_validator_rejects_cross_session_evidence() -> None:
    with pytest.raises(OutputContractError, match="evidence_scope_violation"):
        validate_turn_output(
            turn_output=_fact_output("ev-other"),
            current_snapshot=_snapshot(),
            evidence_ledger={
                "ev-other": {
                    "evidenceId": "ev-other",
                    "sessionId": "session-other",
                    "threadId": "thread-1",
                }
            },
            artifacts={},
            thread_id="thread-1",
        )


def test_output_validator_rejects_artifact_from_old_snapshot() -> None:
    output = TurnOutput.model_validate(
        {
            "responseType": "recommendation",
            "message": "候选",
            "artifactRefs": [
                {"artifactId": "artifact-1", "artifactType": "candidate", "stateVersion": 41}
            ],
            "evidenceRefs": [],
        }
    )

    with pytest.raises(OutputContractError, match="stale_state"):
        validate_turn_output(
            turn_output=output,
            current_snapshot=_snapshot(42),
            evidence_ledger={},
            artifacts={"artifact-1": {"artifactId": "artifact-1", "stateVersion": 41}},
        )


def test_output_validator_returns_normalized_output_when_refs_are_valid() -> None:
    output = validate_turn_output(
        turn_output=_fact_output("ev-known"),
        current_snapshot=_snapshot(),
        evidence_ledger={
            "ev-known": {
                "evidenceId": "ev-known",
                "sessionId": "session-1",
                "stateVersion": 42,
            }
        },
        artifacts={},
        thread_id="thread-1",
    )

    assert output.response_type == "fact"
    assert output.evidence_refs[0].evidence_id == "ev-known"
