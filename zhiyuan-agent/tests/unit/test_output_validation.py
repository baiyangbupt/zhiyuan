from __future__ import annotations

import pytest

from app.gateway.contracts import ConversationTurnSnapshot, EvidenceRef, TurnOutput
from app.gateway.output_validation import OutputContractError, validate_turn_output


def test_validate_output_ignores_json_schema_root_type_echo():
    output = validate_turn_output(
        turn_output={"type": "object", "responseType": "text", "message": "已完成"},
        current_snapshot={"snapshotVersion": 1, "sessionId": "s"},
        evidence_ledger={},
        artifacts={},
    )

    assert output.response_type == "text"


def test_validate_output_preserves_model_text_with_evidence():
    output = validate_turn_output(
        turn_output={
            "responseType": "text",
            "message": "查询结果",
            "evidenceRefs": [{"evidenceId": "ev-1", "sourceLevel": "authoritative", "dataVersion": "v1"}],
        },
        current_snapshot={"snapshotVersion": 1, "sessionId": "s"},
        evidence_ledger={"ev-1": {"sessionId": "s", "stateVersion": 1}},
        artifacts={},
    )

    assert output.response_type == "text"


def test_output_validation_rejects_fixture_admission_fact():
    with pytest.raises(OutputContractError, match="non_authoritative_admission_fact"):
        validate_turn_output(
            turn_output={
                "responseType": "fact",
                "message": "测试",
                "evidenceRefs": [{"evidenceId": "ev-1", "sourceLevel": "authoritative", "dataVersion": "semantic-fixture-1"}],
                "admissionFacts": [{
                    "admissionUnitId": "school-1/major-cs/2025",
                    "admissionMode": "major",
                    "schoolId": "school-1",
                    "schoolName": "甲大学",
                    "majorId": "major-cs",
                    "majorName": "计算机科学与技术",
                    "majorItems": [{"majorId": "major-cs", "majorName": "计算机科学与技术", "majorAdmissionRate": 0}],
                    "unitAdmissionRate": 0,
                    "riskTier": "稳",
                    "dataVersion": "semantic-fixture-1",
                    "limitations": ["semantic_fixture_only"],
                }],
            },
            current_snapshot={"snapshotVersion": 42, "sessionId": "s1"},
            evidence_ledger={"ev-1": {"sessionId": "s1", "stateVersion": 42}},
            artifacts={},
        )


def _snapshot(version: int = 42) -> ConversationTurnSnapshot:
    return ConversationTurnSnapshot(
        snapshot_version=version,
        session_id="session-1",
        planning_stage="candidate_exploration",
    )


def _group_snapshot(version: int = 42) -> ConversationTurnSnapshot:
    return ConversationTurnSnapshot(
        snapshot_version=version,
        session_id="session-1",
        admission_mode="major_group",
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


def test_output_validator_can_require_complete_production_scope() -> None:
    with pytest.raises(OutputContractError, match="evidence_scope_violation"):
        validate_turn_output(
            turn_output=_fact_output("ev-known"),
            current_snapshot=_snapshot(),
            evidence_ledger={"ev-known": {"evidenceId": "ev-known", "stateVersion": 42}},
            artifacts={},
            thread_id="thread-1",
            tenant_id="tenant-1",
            strict_scope=True,
        )


def test_validator_accepts_group_fact_using_group_rate_not_nested_major_rate() -> None:
    output = validate_turn_output(
        turn_output={
            "responseType": "fact",
            "message": "专业组招生事实",
            "evidenceRefs": [
                {
                    "evidenceId": "ev-unit-1",
                    "sourceLevel": "authoritative",
                    "dataVersion": "v17",
                    "admissionMode": "major_group",
                    "admissionUnitId": "unit-1",
                    "groupCode": "101",
                    "stateVersion": 42,
                }
            ],
            "admissionFacts": [
                {
                    "admissionMode": "major_group",
                    "admissionUnitId": "unit-1",
                    "schoolId": "school-1",
                    "groupCode": "101",
                    "unitAdmissionRate": 70,
                    "riskTier": "保",
                    "majorItems": [{"majorId": "m-1", "majorAdmissionRate": 40}],
                }
            ],
        },
        current_snapshot=_group_snapshot(),
        evidence_ledger={
            "ev-unit-1": {
                "evidenceId": "ev-unit-1",
                "sessionId": "session-1",
                "stateVersion": 42,
                "dataVersion": "v17",
                "admissionMode": "major_group",
                "admissionUnitId": "unit-1",
                "groupCode": "101",
            }
        },
        artifacts={},
    )

    assert output.admission_facts[0].risk_tier == "保"
    assert output.admission_facts[0].major_items[0].major_admission_rate == 40


def test_validator_rejects_admission_fact_without_matching_evidence() -> None:
    with pytest.raises(OutputContractError, match="admission_evidence_missing"):
        validate_turn_output(
            turn_output={
                "responseType": "fact",
                "message": "招生事实",
                "evidenceRefs": [
                    {
                        "evidenceId": "ev-other",
                        "sourceLevel": "authoritative",
                        "dataVersion": "v17",
                    }
                ],
                "admissionFacts": [
                    {
                        "admissionMode": "major",
                        "admissionUnitId": "unit-1",
                        "schoolId": "school-1",
                        "majorId": "m-1",
                        "unitAdmissionRate": 40,
                        "riskTier": "冲",
                    }
                ],
            },
            current_snapshot=_snapshot(),
            evidence_ledger={
                "ev-other": {
                    "evidenceId": "ev-other",
                    "sessionId": "session-1",
                    "stateVersion": 42,
                    "dataVersion": "v17",
                }
            },
            artifacts={},
        )


def test_validator_rejects_cross_mode_evidence_and_fact() -> None:
    with pytest.raises(OutputContractError, match="admission_mode_mismatch"):
        validate_turn_output(
            turn_output={
                "responseType": "fact",
                "message": "招生事实",
                "evidenceRefs": [
                    {
                        "evidenceId": "ev-unit-1",
                        "sourceLevel": "authoritative",
                        "dataVersion": "v17",
                        "admissionMode": "major",
                        "admissionUnitId": "unit-1",
                    }
                ],
                "admissionFacts": [
                    {
                        "admissionMode": "major",
                        "admissionUnitId": "unit-1",
                        "schoolId": "school-1",
                        "majorId": "m-1",
                        "unitAdmissionRate": 40,
                        "riskTier": "冲",
                    }
                ],
            },
            current_snapshot=_group_snapshot(),
            evidence_ledger={
                "ev-unit-1": {
                    "evidenceId": "ev-unit-1",
                    "sessionId": "session-1",
                    "stateVersion": 42,
                    "dataVersion": "v17",
                    "admissionMode": "major",
                    "admissionUnitId": "unit-1",
                }
            },
            artifacts={},
        )


@pytest.mark.parametrize("rate", [99.01, float("nan"), float("inf")])
def test_validator_rejects_unsupported_admission_rates(rate: float) -> None:
    with pytest.raises(OutputContractError, match="schema_invalid"):
        validate_turn_output(
            turn_output={
                "responseType": "fact",
                "message": "招生事实",
                "evidenceRefs": [
                    {
                        "evidenceId": "ev-unit-1",
                        "sourceLevel": "authoritative",
                        "dataVersion": "v17",
                    }
                ],
                "admissionFacts": [
                    {
                        "admissionMode": "major",
                        "admissionUnitId": "unit-1",
                        "schoolId": "school-1",
                        "majorId": "m-1",
                        "unitAdmissionRate": rate,
                        "riskTier": "保",
                    }
                ],
            },
            current_snapshot=_snapshot(),
            evidence_ledger={"ev-unit-1": {"dataVersion": "v17"}},
            artifacts={},
        )


def test_validator_accepts_confirm_action_for_current_active_proposal() -> None:
    snapshot = ConversationTurnSnapshot(
        snapshotVersion=42,
        sessionId="session-1",
        activeProposal={"proposalRef": "proposal-1", "sourceVersion": 42},
    )
    output = validate_turn_output(
        turn_output={
            "responseType": "clarification",
            "message": "请确认方案变更",
            "proposalRef": "proposal-1",
            "conversationAction": {
                "actionType": "confirm_proposal",
                "proposalRef": "proposal-1",
                "expectedSourceVersion": 42,
                "intent": "explicit",
            },
        },
        current_snapshot=snapshot,
        evidence_ledger={},
        artifacts={},
        allow_proposal=True,
    )

    assert output.conversation_action.action_type == "confirm_proposal"


def test_validator_rejects_confirm_action_for_stale_proposal() -> None:
    snapshot = ConversationTurnSnapshot(
        snapshotVersion=42,
        sessionId="session-1",
        activeProposal={"proposalRef": "proposal-1", "sourceVersion": 43},
    )

    with pytest.raises(OutputContractError, match="proposal_version_mismatch"):
        validate_turn_output(
            turn_output={
                "responseType": "clarification",
                "message": "确认",
                "conversationAction": {
                    "actionType": "confirm_proposal",
                    "proposalRef": "proposal-1",
                    "expectedSourceVersion": 42,
                    "intent": "explicit",
                },
            },
            current_snapshot=snapshot,
            evidence_ledger={},
            artifacts={},
            allow_proposal=True,
        )
