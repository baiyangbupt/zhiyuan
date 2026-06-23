import importlib.util
import sys
from pathlib import Path


MAPPER_PATH = Path(__file__).resolve().parents[2] / "examples" / "downstream_policy_java_request.py"
SPEC = importlib.util.spec_from_file_location("downstream_policy_java_request", MAPPER_PATH)
assert SPEC and SPEC.loader
mapper = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mapper
SPEC.loader.exec_module(mapper)


def _case(policy, **extra):
    return {
        "caseId": "case-a",
        "planningVersion": 7,
        "scopeType": "major",
        "downstreamPolicy": policy,
        **extra,
    }


def test_maps_only_keep_to_java_user_goal_request():
    policy = {
        "scope": "future_reference",
        "candidateSelection": {
            "onlyKeep": ["临床医学"],
            "hardExclude": [],
            "mustCover": [],
            "rankBoost": [],
            "softAvoid": [],
        },
    }

    report = mapper.build_report([_case(policy)])

    record = report["records"][0]
    assert record["requestReady"] is True
    assert record["javaRequest"]["goalType"] == "only_keep_scope"
    assert record["javaRequest"]["targetScopes"][0]["entityType"] == "major"
    assert record["javaRequest"]["targetScopes"][0]["name"] == "临床医学"
    assert record["adapterGaps"] == []


def test_maps_hard_exclude_region_to_negative_scopes():
    policy = {
        "scope": "future_reference",
        "scopeLevel": "area",
        "candidateSelection": {
            "onlyKeep": [],
            "hardExclude": ["东北"],
            "mustCover": [],
            "rankBoost": [],
            "softAvoid": [],
        },
    }

    report = mapper.build_report([_case(policy, scopeType="region")])

    request = report["records"][0]["javaRequest"]
    assert request["goalType"] == "exclude_scope"
    assert request["targetScopes"] == []
    assert request["negativeScopes"][0]["scopeLevel"] == "area"
    assert request["negativeScopes"][0]["name"] == "东北"


def test_maps_tuition_cap_to_context_budget_request():
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
    }

    report = mapper.build_report([_case(policy)])

    request = report["records"][0]["javaRequest"]
    assert request["goalType"] == "tuition_budget_scope"
    assert request["context"]["maxTuitionPerYear"] == 30000


def test_marks_primary_and_acceptable_as_rank_only_without_java_request():
    policy = {
        "scope": "future_reference",
        "candidateSelection": {
            "onlyKeep": [],
            "hardExclude": [],
            "mustCover": [],
            "rankBoost": [
                {"strength": "primary", "values": ["网络与新媒体"], "weight": 3},
                {"strength": "acceptable", "values": ["跨境电子商务"], "weight": 1},
            ],
            "softAvoid": [],
        },
    }

    report = mapper.build_report([_case(policy)])

    record = report["records"][0]
    assert record["requestReady"] is False
    assert record["javaRequest"] is None
    assert record["adapterGaps"] == ["rank_only_policy:primary,acceptable"]


def test_maps_admission_path_as_program_type_with_mapping_risk():
    policy = {
        "scope": "special_path",
        "admissionPath": "strongbase",
        "candidateSelection": {
            "onlyKeep": [],
            "hardExclude": [],
            "mustCover": [],
            "rankBoost": [],
            "softAvoid": [],
        },
    }

    report = mapper.build_report([_case(policy)])

    record = report["records"][0]
    assert record["requestReady"] is True
    assert record["javaRequest"]["goalType"] == "only_keep_scope"
    assert record["javaRequest"]["targetScopes"][0]["entityType"] == "program_type"
    assert record["adapterGaps"] == ["program_type_text_match_only"]
