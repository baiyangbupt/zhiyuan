from __future__ import annotations

import json

import pytest

from app.observability.conversation_trace import aggregate_shadow_report, run_shadow_case


def test_shadow_trace_contains_required_correlation_ids() -> None:
    trace = run_shadow_case("readonly-admission-001")
    assert {"conversationId", "turnId", "threadId", "snapshotVersion", "skillName"} <= trace.keys()


def test_shadow_hard_gates_are_zero() -> None:
    report = aggregate_shadow_report(
        [
            {
                "writeAttempted": False,
                "unknownAdmissionUnits": 0,
                "factsWithoutEvidence": 0,
                "crossSessionProposalUse": 0,
            }
        ]
    )
    assert report["unauthorizedWrites"] == 0
    assert report["unknownAdmissionUnits"] == 0
    assert report["factsWithoutEvidence"] == 0
    assert report["crossSessionProposalUse"] == 0


def test_shadow_runner_rejects_arbitrary_production_session_ids(tmp_path) -> None:
    from scripts.codex_shadow_replay import load_replay_cases

    path = tmp_path / "cases.json"
    path.write_text(json.dumps({"cases": [{"caseId": "x", "sessionId": "prod-123"}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="fixed fixture"):
        load_replay_cases(path)


def test_shadow_report_counts_write_attempts_and_missing_evidence() -> None:
    report = aggregate_shadow_report(
        [
            {"writeAttempted": True, "factsWithoutEvidence": 1},
            {"writeAttempted": False, "factsWithoutEvidence": 0, "unknownAdmissionUnits": 2},
        ]
    )
    assert report["unauthorizedWrites"] == 1
    assert report["factsWithoutEvidence"] == 1
    assert report["unknownAdmissionUnits"] == 2
