from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.gateway.contracts import (
    ArtifactRef,
    ConversationTurnSnapshot,
    EvidenceRef,
    StatePatch,
    TurnOutput,
)


def test_recommendation_output_requires_backend_refs() -> None:
    with pytest.raises(ValidationError, match="artifactRefs"):
        TurnOutput.model_validate(
            {
                "responseType": "recommendation",
                "message": "候选已生成",
                "artifactRefs": [],
                "evidenceRefs": [],
            }
        )


def test_fact_output_requires_evidence_refs() -> None:
    with pytest.raises(ValidationError, match="evidenceRefs"):
        TurnOutput.model_validate(
            {
                "responseType": "fact",
                "message": "这是招生事实",
                "artifactRefs": [],
                "evidenceRefs": [],
            }
        )


def test_state_patch_rejects_non_adjacent_versions() -> None:
    with pytest.raises(ValidationError, match="targetVersion"):
        StatePatch(
            baseVersion=41,
            targetVersion=43,
            changes=[],
            invalidations=[],
        )


def test_state_patch_rejects_unknown_change_path() -> None:
    with pytest.raises(ValidationError, match="unsupported state path"):
        StatePatch(
            baseVersion=41,
            targetVersion=42,
            changes=[{"path": "workingPlanState", "oldValue": {}, "newValue": {}}],
            invalidations=[],
        )


def test_contracts_accept_backend_camel_case_payloads_and_forbid_unknown_fields() -> None:
    evidence = EvidenceRef.model_validate(
        {
            "evidenceId": "ev-1",
            "sourceLevel": "authoritative",
            "dataVersion": "2026.09.07",
            "limitations": [],
        }
    )
    artifact = ArtifactRef.model_validate(
        {
            "artifactId": "artifact-1",
            "artifactType": "candidate",
            "stateVersion": 42,
        }
    )
    output = TurnOutput.model_validate(
        {
            "responseType": "recommendation",
            "message": "候选已生成",
            "artifactRefs": [artifact.model_dump(by_alias=True)],
            "evidenceRefs": [evidence.model_dump(by_alias=True)],
            "uncertainties": [],
        }
    )

    assert output.model_dump(by_alias=True)["artifactRefs"][0]["artifactId"] == "artifact-1"
    with pytest.raises(ValidationError, match="extraField"):
        EvidenceRef.model_validate(
            {
                "evidenceId": "ev-1",
                "sourceLevel": "authoritative",
                "dataVersion": "2026.09.07",
                "extraField": True,
            }
        )


def test_snapshot_serializes_with_stable_empty_collections() -> None:
    snapshot = ConversationTurnSnapshot(
        snapshot_version=42,
        session_id="session-1",
        planning_stage="candidate_exploration",
    )

    payload = snapshot.model_dump(by_alias=True)

    assert payload["snapshotVersion"] == 42
    assert payload["sessionId"] == "session-1"
    assert payload["missingFacts"] == []
    assert payload["allowedCapabilities"] == []
    assert payload["evidence"] == []


def test_snapshot_requires_canonical_admission_mode() -> None:
    snapshot = ConversationTurnSnapshot.model_validate(
        {
            "snapshotVersion": 3,
            "sessionId": "s1",
            "admissionMode": "major_group",
        }
    )

    assert snapshot.admission_mode == "major_group"


def test_state_patch_mode_change_requires_invalidation() -> None:
    patch = StatePatch.model_validate(
        {
            "baseVersion": 3,
            "targetVersion": 4,
            "changes": [{"path": "admissionMode", "value": "major_group"}],
            "invalidations": [{"kind": "admission_mode", "reason": "mode_changed"}],
        }
    )

    assert patch.changes[0]["value"] == "major_group"


def test_group_evidence_contains_group_scope_and_state_version() -> None:
    evidence = EvidenceRef.model_validate(
        {
            "evidenceId": "ev-1",
            "sourceLevel": "authoritative",
            "dataVersion": "v17",
            "admissionMode": "major_group",
            "admissionUnitId": "unit-1",
            "groupCode": "101",
            "stateVersion": 4,
        }
    )

    assert evidence.admission_mode == "major_group"
    assert evidence.admission_unit_id == "unit-1"
