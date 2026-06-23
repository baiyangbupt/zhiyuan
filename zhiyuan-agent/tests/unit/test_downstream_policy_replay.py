import importlib.util
import sys
from pathlib import Path


REPLAY_PATH = Path(__file__).resolve().parents[2] / "examples" / "downstream_policy_replay.py"
SPEC = importlib.util.spec_from_file_location("downstream_policy_replay", REPLAY_PATH)
assert SPEC and SPEC.loader
replay = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = replay
SPEC.loader.exec_module(replay)


def _compiled(case_id="case-a", policy=None):
    return {
        "caseId": case_id,
        "downstreamPolicy": policy or {
            "scope": "future_reference",
            "admissionPath": None,
            "candidateSelection": {
                "hardFilterBeforeRanking": True,
                "onlyKeep": [],
                "hardExclude": ["民办"],
                "mustCover": [],
                "rankBoost": [
                    {"strength": "primary", "values": ["计算机类"], "weight": 3},
                    {"strength": "preferred", "values": [], "weight": 2},
                    {"strength": "acceptable", "values": ["电子信息"], "weight": 1},
                ],
                "softAvoid": [],
            },
            "replacementPolicy": {
                "replaceFirst": [
                    {
                        "reason": "exclude_hard_violation",
                        "values": ["民办"],
                        "policy": "remove_or_replace_before_ranking",
                    }
                ],
                "fillPriority": [],
                "protectFromReplacement": [
                    {
                        "strength": "primary",
                        "values": ["计算机类"],
                        "policy": "do_not_replace_for_weaker_preference_without_conflict",
                    }
                ],
            },
        },
    }


def test_replay_filters_hard_exclude_before_ranking_and_boosts_primary():
    case = {
        "caseId": "case-a",
        "selectionLimit": 2,
        "fixture": {
            "candidateItems": [
                {"volunteerId": "c1", "majorName": "计算机类", "schoolType": "公办", "baseScore": 10},
                {"volunteerId": "c2", "majorName": "电子信息", "schoolType": "公办", "baseScore": 90},
                {"volunteerId": "c3", "majorName": "会计学", "schoolType": "民办", "baseScore": 1000},
            ],
            "currentPlanItems": [],
        },
        "expected": {"selectedCandidateIds": ["c1", "c2"], "excludedCandidateIds": ["c3"]},
        "assert": {"exact": ["selectedCandidateIds", "excludedCandidateIds"]},
    }

    report = replay.build_report([case], [_compiled()])

    assert report["summary"]["passed"] == 1
    record = report["records"][0]
    assert record["selectedCandidateIds"] == ["c1", "c2"]
    assert record["excludedCandidates"][0]["reasons"] == ["hard_exclude"]


def test_replay_marks_replacement_and_protected_plan_items():
    case = {
        "caseId": "case-a",
        "fixture": {
            "candidateItems": [],
            "currentPlanItems": [
                {"volunteerId": "p1", "majorName": "会计学", "schoolType": "民办"},
                {"volunteerId": "p2", "majorName": "计算机类", "schoolType": "公办"},
            ],
        },
        "expected": {"replacementCandidateIds": ["p1"], "protectedPlanItemIds": ["p2"]},
        "assert": {"exact": ["replacementCandidateIds", "protectedPlanItemIds"]},
    }

    report = replay.build_report([case], [_compiled()])

    assert report["summary"]["passed"] == 1
    record = report["records"][0]
    assert record["replacementCandidateIds"] == ["p1"]
    assert record["protectedPlanItemIds"] == ["p2"]


def test_replay_applies_scope_to_candidates_and_plan_items():
    policy = _compiled(
        policy={
            "scope": "保底",
            "candidateSelection": {
                "onlyKeep": [],
                "hardExclude": ["民办"],
                "mustCover": [],
                "rankBoost": [],
                "softAvoid": [],
            },
            "replacementPolicy": {
                "replaceFirst": [
                    {
                        "reason": "exclude_hard_violation",
                        "values": ["民办"],
                        "policy": "remove_or_replace_before_ranking",
                    }
                ],
                "fillPriority": [],
                "protectFromReplacement": [],
            },
        }
    )
    case = {
        "caseId": "case-a",
        "selectionLimit": 3,
        "fixture": {
            "candidateItems": [
                {"volunteerId": "c1", "schoolType": "公办", "tier": "保底", "baseScore": 1},
                {"volunteerId": "c2", "schoolType": "公办", "tier": "稳", "baseScore": 100},
            ],
            "currentPlanItems": [
                {"volunteerId": "p1", "schoolType": "民办", "tier": "保底"},
                {"volunteerId": "p2", "schoolType": "民办", "tier": "稳"},
            ],
        },
        "expected": {
            "selectedCandidateIds": ["c1"],
            "excludedCandidateIds": ["c2"],
            "replacementCandidateIds": ["p1"],
        },
        "assert": {"exact": ["selectedCandidateIds", "excludedCandidateIds", "replacementCandidateIds"]},
    }

    report = replay.build_report([case], [policy])

    assert report["summary"]["passed"] == 1


def test_replay_filters_admission_path():
    policy = _compiled(
        policy={
            "scope": "special_path",
            "admissionPath": "strongbase",
            "candidateSelection": {
                "onlyKeep": [],
                "hardExclude": [],
                "mustCover": [],
                "rankBoost": [],
                "softAvoid": [],
            },
            "replacementPolicy": {"replaceFirst": [], "fillPriority": [], "protectFromReplacement": []},
        }
    )
    case = {
        "caseId": "case-a",
        "selectionLimit": 2,
        "fixture": {
            "candidateItems": [
                {"volunteerId": "c1", "admissionPath": "strongbase", "baseScore": 1},
                {"volunteerId": "c2", "admissionPath": "regular_batch", "baseScore": 100},
            ]
        },
        "expected": {"selectedCandidateIds": ["c1"], "excludedCandidateIds": ["c2"]},
        "assert": {"exact": ["selectedCandidateIds", "excludedCandidateIds"]},
    }

    report = replay.build_report([case], [policy])

    assert report["summary"]["passed"] == 1


def test_replay_reports_missing_policy_as_failure():
    report = replay.build_report([{"caseId": "missing", "fixture": {}}], [])

    assert report["summary"]["failed"] == 1
    assert report["records"][0]["failures"][0]["type"] == "missing_policy"


def test_replay_accepts_inline_policy_without_compiler_record():
    case = {
        "caseId": "inline-only-keep",
        "selectionLimit": 2,
        "downstreamPolicy": {
            "scope": "future_reference",
            "candidateSelection": {
                "onlyKeep": ["临床医学"],
                "hardExclude": [],
                "mustCover": [],
                "rankBoost": [],
                "softAvoid": [],
            },
            "replacementPolicy": {
                "replaceFirst": [
                    {
                        "reason": "outside_only_keep_scope",
                        "keepValues": ["临床医学"],
                        "policy": "remove_or_replace_out_of_scope_items",
                    }
                ],
                "fillPriority": [],
                "protectFromReplacement": [],
            },
        },
        "fixture": {
            "candidateItems": [
                {"volunteerId": "c1", "majorName": "临床医学", "baseScore": 10},
                {"volunteerId": "c2", "majorName": "口腔医学", "baseScore": 100},
            ],
            "currentPlanItems": [
                {"volunteerId": "p1", "majorName": "临床医学"},
                {"volunteerId": "p2", "majorName": "护理学"},
            ],
        },
        "expected": {
            "policySource": "inline",
            "selectedCandidateIds": ["c1"],
            "excludedCandidateIds": ["c2"],
            "replacementCandidateIds": ["p2"],
            "capacityStatus": "insufficient_candidates",
        },
        "assert": {
            "exact": [
                "policySource",
                "selectedCandidateIds",
                "excludedCandidateIds",
                "replacementCandidateIds",
                "capacityStatus",
            ]
        },
    }

    report = replay.build_report([case], [])

    assert report["summary"]["passed"] == 1
    assert report["records"][0]["policySource"] == "inline"


def test_replay_boosts_must_cover_and_reports_missing_values():
    policy = {
        "scope": "future_reference",
        "candidateSelection": {
            "onlyKeep": [],
            "hardExclude": [],
            "mustCover": ["计算机类", "法学"],
            "rankBoost": [],
            "softAvoid": [],
        },
        "replacementPolicy": {"replaceFirst": [], "fillPriority": [], "protectFromReplacement": []},
    }
    case = {
        "caseId": "must-cover",
        "selectionLimit": 1,
        "downstreamPolicy": policy,
        "fixture": {
            "candidateItems": [
                {"volunteerId": "c1", "majorName": "计算机类", "baseScore": 1},
                {"volunteerId": "c2", "majorName": "工商管理", "baseScore": 200},
            ]
        },
        "expected": {
            "selectedCandidateIds": ["c1"],
            "mustCoverSatisfied": False,
            "missingMustCover": ["法学"],
        },
        "assert": {"exact": ["selectedCandidateIds", "mustCoverSatisfied", "missingMustCover"]},
    }

    report = replay.build_report([case], [])

    assert report["summary"]["passed"] == 1
    record = report["records"][0]
    assert record["selectedCandidates"][0]["reasons"] == ["mustCover:计算机类"]
    assert report["summary"]["missingMustCoverCount"] == 1


def test_replay_penalizes_soft_avoid_without_excluding_candidate():
    policy = {
        "scope": "future_reference",
        "candidateSelection": {
            "onlyKeep": [],
            "hardExclude": [],
            "mustCover": [],
            "rankBoost": [],
            "softAvoid": ["高收费"],
            "softAvoidPenalty": 50,
        },
        "replacementPolicy": {"replaceFirst": [], "fillPriority": [], "protectFromReplacement": []},
    }
    case = {
        "caseId": "soft-avoid",
        "selectionLimit": 2,
        "downstreamPolicy": policy,
        "fixture": {
            "candidateItems": [
                {"volunteerId": "c1", "majorName": "软件工程", "tags": ["高收费"], "baseScore": 100},
                {"volunteerId": "c2", "majorName": "计算机类", "tags": ["普通收费"], "baseScore": 60},
            ]
        },
        "expected": {
            "selectedCandidateIds": ["c2", "c1"],
            "excludedCandidateIds": [],
            "capacityStatus": "satisfied",
        },
        "assert": {"exact": ["selectedCandidateIds", "excludedCandidateIds", "capacityStatus"]},
    }

    report = replay.build_report([case], [])

    assert report["summary"]["passed"] == 1
    assert report["records"][0]["selectedCandidates"][1]["reasons"] == ["softAvoid"]


def test_replay_reports_no_result_after_hard_filters():
    policy = {
        "scope": "future_reference",
        "candidateSelection": {
            "onlyKeep": [],
            "hardExclude": ["民办"],
            "mustCover": [],
            "rankBoost": [],
            "softAvoid": [],
        },
        "replacementPolicy": {"replaceFirst": [], "fillPriority": [], "protectFromReplacement": []},
    }
    case = {
        "caseId": "no-result",
        "selectionLimit": 2,
        "downstreamPolicy": policy,
        "fixture": {
            "candidateItems": [
                {"volunteerId": "c1", "schoolType": "民办", "baseScore": 1},
                {"volunteerId": "c2", "schoolType": "民办", "baseScore": 2},
            ]
        },
        "expected": {
            "selectedCandidateIds": [],
            "excludedCandidateIds": ["c1", "c2"],
            "capacityStatus": "no_result",
            "noResultReason": "all_candidates_filtered",
            "shortageCount": 2,
        },
        "assert": {
            "exact": [
                "selectedCandidateIds",
                "excludedCandidateIds",
                "capacityStatus",
                "noResultReason",
                "shortageCount",
            ]
        },
    }

    report = replay.build_report([case], [])

    assert report["summary"]["passed"] == 1
    assert report["summary"]["capacityStatuses"]["no_result"] == 1


def test_replay_applies_tuition_cap_to_candidates_and_plan_replacements():
    policy = {
        "scope": "future_reference",
        "candidateSelection": {
            "onlyKeep": [],
            "hardExclude": [],
            "mustCover": [],
            "rankBoost": [],
            "softAvoid": [],
            "maxTuitionPerYear": 30000,
        },
        "replacementPolicy": {
            "replaceFirst": [
                {
                    "reason": "tuition_cap_exceeded",
                    "maxTuitionPerYear": 30000,
                    "policy": "replace_items_over_budget_first",
                }
            ],
            "fillPriority": [],
            "protectFromReplacement": [],
        },
    }
    case = {
        "caseId": "tuition-cap",
        "selectionLimit": 2,
        "downstreamPolicy": policy,
        "fixture": {
            "candidateItems": [
                {"volunteerId": "c1", "majorName": "软件工程", "tuitionPerYear": 48000, "baseScore": 100},
                {"volunteerId": "c2", "majorName": "计算机类", "tuitionPerYear": 6500, "baseScore": 50},
            ],
            "currentPlanItems": [
                {"volunteerId": "p1", "majorName": "软件工程", "tuitionPerYear": 48000},
                {"volunteerId": "p2", "majorName": "计算机类", "tuitionPerYear": 6500},
            ],
        },
        "expected": {
            "selectedCandidateIds": ["c2"],
            "excludedCandidateIds": ["c1"],
            "replacementCandidateIds": ["p1"],
            "capacityStatus": "insufficient_candidates",
        },
        "assert": {
            "exact": [
                "selectedCandidateIds",
                "excludedCandidateIds",
                "replacementCandidateIds",
                "capacityStatus",
            ]
        },
    }

    report = replay.build_report([case], [])

    assert report["summary"]["passed"] == 1
    assert report["records"][0]["excludedCandidates"][0]["reasons"] == ["tuition_cap_exceeded"]
