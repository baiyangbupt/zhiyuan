from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

from app.zhiyuan_agent.tools import (
    _normalize_plan_change_requirements,
    _normalize_plan_priority_rules,
    _normalize_plan_tier_quota_goal,
)


AGENT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = AGENT_ROOT.parent
EXAMPLES = AGENT_ROOT / "examples"
MANIFEST_PATH = EXAMPLES / "release_410_m0_baseline_manifest.json"
GOLDEN_PATH = EXAMPLES / "plan_change_spec_410_golden.json"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


contract = _load_module("plan_change_spec_410_contract_for_test", EXAMPLES / "plan_change_spec_410_contract.py")
gate = _load_module("dialog_quality_gate_410_baseline", EXAMPLES / "dialog_quality_gate.py")
report = _load_module("dialog_case_report_410_baseline", EXAMPLES / "dialog_case_evaluation_report.py")


def _case_step_count(case_path: Path) -> int:
    payload = json.loads(case_path.read_text(encoding="utf-8"))
    cases = report._expand_case_payload(payload)
    return sum(len(case.get("prompts") or []) for case in cases)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_plan_change_spec_410_golden_contract_is_green():
    result = contract.run_golden(GOLDEN_PATH)

    assert result == {
        "schemaVersion": "4.1.0-m0",
        "total": 19,
        "passed": 19,
        "failures": [],
    }


def test_plan_change_spec_410_canonical_digest_is_stable_and_context_bound():
    raw = {
        "tier_quota_goal": {
            "type": "ratios",
            "sprint_weight": 3,
            "stable_weight": 4,
            "protect_weight": 3,
        },
        "requirements": [
            {
                "kind": "include",
                "domain": "region",
                "key": "province",
                "values": ["山东", " 山东 ", "广东"],
                "min_count": 2,
            }
        ],
    }

    first = contract.compile_reference(raw, context_target_count=45)
    second = contract.compile_reference(raw, context_target_count=45)
    changed_context = contract.compile_reference(raw, context_target_count=48)

    assert first == second
    assert first["canonical_digest"] != changed_context["canonical_digest"]
    assert first["normalized_spec"]["requirements"][0]["values"] == ["山东", "广东"]
    assert first["summary"]["tier_result"]["counts"] == {
        "sprint": 14,
        "stable": 18,
        "protect": 13,
    }


def test_plan_change_spec_410_json_schema_forbids_unknown_fields_and_discriminates_goals():
    schema = contract.PlanChangeSpec410.model_json_schema()

    assert schema["additionalProperties"] is False
    assert schema["properties"]["tier_quota_goal"]
    assert schema["properties"]["risk_structure_goal"]
    assert "soft_preferences" not in schema["properties"]


def test_plan_change_spec_410_reference_is_compatible_with_400_normalizers():
    raw = {
        "tier_quota_goal": {
            "type": "exact_counts",
            "sprint_count": 9,
            "stable_count": 17,
            "protect_count": 19,
        },
        "requirements": [
            {"kind": "exclude", "domain": "school", "key": "school_nature", "values": ["民办"]},
            {
                "kind": "include",
                "domain": "region",
                "key": "province",
                "values": ["山东"],
                "min_count": 2,
            },
        ],
        "priority_rules": [
            {"domain": "region", "key": "province", "values": ["山东"]}
        ],
    }

    compiled = contract.compile_reference(raw, context_target_count=45)
    quota, quota_errors = _normalize_plan_tier_quota_goal(raw["tier_quota_goal"])
    requirements, requirement_errors = _normalize_plan_change_requirements(raw["requirements"])
    priorities, priority_errors = _normalize_plan_priority_rules(raw["priority_rules"])

    assert quota_errors == requirement_errors == priority_errors == []
    assert quota == {
        "type": "exact_counts",
        "sprintCount": 9,
        "stableCount": 17,
        "protectCount": 19,
    }
    assert compiled["summary"]["tier_result"]["counts"] == {
        "sprint": quota["sprintCount"],
        "stable": quota["stableCount"],
        "protect": quota["protectCount"],
    }
    assert [item["kind"] for item in requirements] == ["exclude", "include"]
    assert priorities[0]["orderingTarget"] == "rank_before"
    assert priorities[0]["scope"] == "within_tier"


def test_release_410_m0_manifest_matches_quality_gate_and_case_steps():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    final_files = manifest["finalActionGate"]["caseFiles"]
    live_files = manifest["liveGate"]["caseFiles"]

    assert list(final_files) == gate.FINAL_ACTION_CASE_FILES
    assert list(live_files) == gate.PINNED_LIVE_CASE_FILES
    assert len(final_files) == manifest["finalActionGate"]["expectedFileCount"] == 24
    assert len(live_files) == manifest["liveGate"]["expectedFileCount"] == 13

    for name, expected_steps in {**final_files, **live_files}.items():
        assert _case_step_count(EXAMPLES / name) == expected_steps, name

    assert sum(final_files.values()) == manifest["finalActionGate"]["expectedStepCount"] == 178
    assert sum(live_files.values()) == manifest["liveGate"]["expectedStepCount"] == 231


def test_release_410_m0_large_fixture_manifest_uses_tracked_sources_without_copying():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    for fixture in manifest["trackedLargeFixtureSources"]:
        path = (AGENT_ROOT / fixture["path"]).resolve()
        assert path.is_relative_to(REPO_ROOT)
        assert path.is_file()
        assert path.stat().st_size == fixture["bytes"]
        assert _sha256(path) == fixture["sha256"]

    assert not (AGENT_ROOT / "tests" / "fixtures" / "session_volunteer_16.json").exists()

    for artifact in manifest["m0ContractArtifacts"]:
        assert (AGENT_ROOT / artifact).resolve().is_file(), artifact
