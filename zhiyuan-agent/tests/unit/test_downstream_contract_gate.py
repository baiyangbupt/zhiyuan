import importlib.util
import sys
from pathlib import Path


GATE_PATH = Path(__file__).resolve().parents[2] / "examples" / "downstream_contract_gate.py"
SPEC = importlib.util.spec_from_file_location("downstream_contract_gate", GATE_PATH)
assert SPEC and SPEC.loader
gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)


def test_gate_passes_when_components_pass_even_with_expected_gaps():
    report = gate.build_report(
        replay_report={
            "summary": {
                "total": 2,
                "passed": 2,
                "failed": 0,
                "passRate": 1.0,
                "capacityStatuses": {"satisfied": 1, "no_result": 1},
                "missingMustCoverCount": 1,
            },
            "records": [
                {"caseId": "r1", "capacityStatus": "satisfied"},
                {"caseId": "r2", "capacityStatus": "no_result", "noResultReason": "all_candidates_filtered"},
            ],
        },
        java_request_report={
            "summary": {
                "total": 1,
                "passed": 1,
                "failed": 0,
                "passRate": 1.0,
                "requestReady": 0,
                "requestNotReady": 1,
                "adapterGapCounts": {"rank_only_policy:primary": 1},
            },
            "records": [{"caseId": "j1", "adapterGaps": ["rank_only_policy:primary"]}],
        },
        adapter_dry_run_report={
            "summary": {
                "total": 1,
                "passed": 1,
                "failed": 0,
                "passRate": 1.0,
                "capacityStatuses": {"not_reported": 1},
                "contractGapCounts": {"ready_without_actions": 1},
            },
            "records": [{"caseId": "a1", "contractGapCounts": {"ready_without_actions": 1}}],
        },
    )

    assert report["summary"]["gatePassed"] is True
    assert report["summary"]["expectedGapCount"] == 2
    assert report["summary"]["capacityStatuses"] == {
        "satisfied": 1,
        "no_result": 1,
        "not_reported": 1,
    }
    assert report["expectedGapExamples"]["adapterGaps"] == [
        {"caseId": "j1", "gap": "rank_only_policy:primary"}
    ]
    assert report["expectedGapExamples"]["contractGaps"] == [
        {"caseId": "a1", "gap": "ready_without_actions"}
    ]


def test_gate_fails_when_a_component_has_assertion_failures():
    report = gate.build_report(
        replay_report={
            "summary": {"total": 1, "passed": 0, "failed": 1, "passRate": 0.0},
            "failureExamples": [{"caseId": "bad"}],
        },
        java_request_report={"summary": {"total": 0, "passed": 0, "failed": 0}},
        adapter_dry_run_report={"summary": {"total": 0, "passed": 0, "failed": 0}},
    )

    assert report["summary"]["gatePassed"] is False
    assert report["summary"]["hardFailureCount"] == 1
    assert report["hardFailureExamples"][0]["component"] == "policyReplay"
