import importlib.util
import sys
from pathlib import Path


ADAPTER_PATH = Path(__file__).resolve().parents[2] / "examples" / "downstream_adapter_dry_run.py"
SPEC = importlib.util.spec_from_file_location("downstream_adapter_dry_run", ADAPTER_PATH)
assert SPEC and SPEC.loader
adapter = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = adapter
SPEC.loader.exec_module(adapter)


def test_adapter_maps_ready_replacement_to_satisfied_capacity():
    case = {
        "caseId": "ready",
        "fixProposalResponse": {
            "data": {
                "proposals": [
                    {
                        "proposalId": "fp1",
                        "proposalSource": "user_goal",
                        "status": "ready",
                        "strategy": "only_keep_scope",
                        "requiresConfirmation": True,
                        "actions": [
                            {
                                "actionType": "replace_volunteers",
                                "removeVolunteerIds": ["p1"],
                                "candidateVolunteerIds": ["c1"],
                                "replacementPairs": [{"fromVolunteerId": "p1", "toVolunteerId": "c1"}],
                            }
                        ],
                        "dryRunResult": {"removeVolunteerCount": 1, "addVolunteerCount": 1},
                    }
                ]
            }
        },
    }

    report = adapter.build_report([case])

    assert report["summary"]["passed"] == 1
    observation = report["records"][0]["observations"][0]
    assert observation["capacityStatus"] == "satisfied"
    assert observation["replacementCandidateIds"] == ["p1"]
    assert observation["candidateVolunteerIds"] == ["c1"]
    assert observation["contractGaps"] == []


def test_adapter_maps_blocked_shortage_to_no_result_reason():
    case = {
        "caseId": "blocked",
        "fixProposalResponse": {
            "proposals": [
                {
                    "proposalId": "fp1",
                    "status": "blocked",
                    "strategy": "fill_probability_gap",
                    "blockingReasonCodes": ["probability_gap_candidate_insufficient"],
                    "candidateShortages": [
                        {
                            "reasonCode": "probability_gap_candidate_insufficient",
                            "shortageCount": 2,
                            "availableCount": 0,
                        }
                    ],
                    "dryRunResult": {"status": "blocked"},
                }
            ]
        },
    }

    report = adapter.build_report([case])

    observation = report["records"][0]["observations"][0]
    assert observation["capacityStatus"] == "no_result"
    assert observation["noResultReason"] == "probability_gap_candidate_insufficient"
    assert observation["shortageCount"] == 2
    assert observation["blockingReasonCodes"] == ["probability_gap_candidate_insufficient"]


def test_adapter_marks_must_cover_missing_for_blocked_must_include():
    case = {
        "caseId": "must-include-blocked",
        "fixProposalResponse": {
            "proposals": [
                {
                    "proposalId": "fp1",
                    "status": "blocked",
                    "strategy": "must_include_scope",
                    "targetValues": ["法学"],
                    "blockingReasonCodes": ["user_goal_target_not_found"],
                    "candidateShortages": [
                        {"reasonCode": "user_goal_target_not_found", "shortageCount": 1}
                    ],
                    "dryRunResult": {"status": "blocked"},
                }
            ]
        },
    }

    report = adapter.build_report([case])

    observation = report["records"][0]["observations"][0]
    assert observation["requiredMustCover"] == ["法学"]
    assert observation["missingMustCover"] == ["法学"]
    assert observation["mustCoverSatisfied"] is False


def test_adapter_reports_ready_without_actions_contract_gap():
    case = {
        "caseId": "gap",
        "fixProposalResponse": {
            "proposals": [
                {
                    "proposalId": "fp1",
                    "status": "ready",
                    "strategy": "exclude_scope",
                    "dryRunResult": {"status": "ready"},
                }
            ]
        },
    }

    report = adapter.build_report([case])

    assert report["summary"]["contractGapCounts"] == {"ready_without_actions": 1}
    assert report["records"][0]["observations"][0]["contractGaps"] == ["ready_without_actions"]
