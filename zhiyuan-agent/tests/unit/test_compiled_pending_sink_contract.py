import importlib.util
import sys
from pathlib import Path


CONTRACT_PATH = Path(__file__).resolve().parents[2] / "examples" / "compiled_pending_sink_contract.py"
SPEC = importlib.util.spec_from_file_location("compiled_pending_sink_contract", CONTRACT_PATH)
assert SPEC and SPEC.loader
contract = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = contract
SPEC.loader.exec_module(contract)


def test_compiled_pending_sink_contract_fixture_passes():
    cases = contract._load_cases(
        str(Path(__file__).resolve().parents[2] / "examples" / "compiled_pending_sink_contract_320_cases.json")
    )

    report = contract.build_report(cases)

    assert report["summary"]["total"] == 6
    assert report["summary"]["passed"] == 6
    assert report["summary"]["bySinkType"] == {
        "intent": 2,
        "plan": 1,
        "fix_proposal": 2,
        "none": 1,
    }
    assert report["summary"]["blockingReasons"] == {
        "no_pending_requested": 1,
        "missing_compiled_proposal_id": 1,
        "fix_proposal_requires_actions": 1,
    }


def test_compiled_pending_sink_contract_rejects_legacy_shape_without_compiled_id():
    result = contract._build_sink_request(
        {
            "pendingType": "plan_mutation",
            "executionPayload": {
                "kind": "pending_plan_mutation",
                "actionFamilies": ["remove_units"],
            },
        }
    )

    assert result["sinkType"] == "plan"
    assert result["allowed"] is False
    assert "missing_compiled_proposal_id" in result["blockingReasons"]
    assert "plan_sink_requires_plan_confirmation_candidate" in result["blockingReasons"]


def test_compiled_pending_sink_contract_rejects_plan_without_candidate():
    result = contract._build_sink_request(
        {
            "compiledProposalId": "cp-plan-legacy",
            "pendingType": "plan_mutation",
            "executionPayload": {
                "kind": "pending_plan_mutation",
                "actionFamilies": ["remove_units"],
            },
        }
    )

    assert result["sinkType"] == "plan"
    assert result["allowed"] is False
    assert result["blockingReasons"] == ["plan_sink_requires_plan_confirmation_candidate"]


def test_compiled_pending_sink_contract_rejects_fix_without_dry_run():
    result = contract._build_sink_request(
        {
            "compiledProposalId": "cp-fix",
            "pendingType": "plan_mutation",
            "executionPayload": {
                "kind": "pending_plan_mutation",
                "actionFamilies": ["apply_fix_proposal"],
            },
            "proposalCandidates": [
                {
                    "id": "fix-1",
                    "type": "java_fix_proposal_reference",
                    "actions": [{"type": "replace"}],
                    "sourceVersionGuard": 1,
                }
            ],
        }
    )

    assert result["sinkType"] == "fix_proposal"
    assert result["allowed"] is False
    assert "fix_proposal_requires_dry_run_observation" in result["blockingReasons"]
