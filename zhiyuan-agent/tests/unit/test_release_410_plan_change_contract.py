from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from app.zhiyuan_agent.tools import (
    _normalize_plan_change_requirements,
    _normalize_plan_priority_rules,
    _normalize_plan_tier_quota_goal,
)


AGENT_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = AGENT_ROOT / "examples"
GOLDEN_PATH = EXAMPLES / "plan_change_spec_410_golden.json"
M2_CASE_PATH = EXAMPLES / "dialog_regression_410_m2_tier_allocation_cases.json"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


contract = _load_module(
    "plan_change_spec_410_contract_for_m2_test",
    EXAMPLES / "plan_change_spec_410_contract.py",
)
gate = _load_module(
    "dialog_quality_gate_for_m2_test",
    EXAMPLES / "dialog_quality_gate.py",
)


def test_plan_change_spec_410_m2_golden_contract_is_green():
    result = contract.run_golden(GOLDEN_PATH)

    assert result == {
        "schemaVersion": "4.1.0-m2",
        "total": 26,
        "passed": 26,
        "failures": [],
    }


def test_plan_change_spec_410_canonical_digest_is_stable_and_context_bound():
    raw = {
        "tier_quota_goal": {
            "type": "ratios",
            "update_mode": "replace",
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


def test_plan_change_spec_410_range_patch_without_context_remains_request_delta():
    compiled = contract.compile_reference(
        {
            "tier_quota_goal": {
                "type": "count_ranges",
                "update_mode": "patch",
                "sprint": {"max_count": 10},
            }
        },
        context_target_count=45,
    )

    assert compiled["normalized_spec"]["tier_quota_goal"] == {
        "type": "count_ranges",
        "update_mode": "patch",
        "sprint": {"max_count": 10},
    }
    assert compiled["summary"]["tier_result"] == {
        "type": "count_ranges",
        "update_mode": "patch",
        "request_bounds": {"sprint": {"max_count": 10}},
        "resolved": False,
    }


def test_plan_change_spec_410_range_patch_merges_only_explicit_historical_bounds():
    compiled = contract.compile_reference(
        {
            "tier_quota_goal": {
                "type": "count_ranges",
                "update_mode": "patch",
                "sprint": {"max_count": 10},
            }
        },
        context_target_count=45,
        context_tier_goal={
            "type": "count_ranges",
            "sprint": {"min_count": 5, "max_count": 12},
            "stable": {"min_count": 15, "max_count": 20},
            "protect": {"min_count": 18, "max_count": 25},
        },
    )

    tier_result = compiled["summary"]["tier_result"]
    assert tier_result["request_bounds"] == {"sprint": {"max_count": 10}}
    assert tier_result["effective_goal"] == {
        "type": "count_ranges",
        "sprint": {"min_count": 5, "max_count": 10},
        "stable": {"min_count": 15, "max_count": 20},
        "protect": {"min_count": 18, "max_count": 25},
    }
    assert tier_result["bounds"] == {
        "sprint": {"min_count": 5, "max_count": 10},
        "stable": {"min_count": 15, "max_count": 20},
        "protect": {"min_count": 18, "max_count": 25},
    }
    assert tier_result["resolved"] is True


def test_plan_change_spec_410_range_patch_blocks_cross_type_history():
    with pytest.raises(contract.ContractError) as exc_info:
        contract.compile_reference(
            {
                "tier_quota_goal": {
                    "type": "count_ranges",
                    "update_mode": "patch",
                    "sprint": {"max_count": 10},
                }
            },
            context_target_count=45,
            context_tier_goal={
                "type": "exact_counts",
                "sprint_count": 9,
                "stable_count": 17,
                "protect_count": 19,
            },
        )

    assert exc_info.value.code == "tier_patch_type_mismatch"


def test_plan_change_spec_410_ratio_weights_are_canonicalized_by_gcd():
    compiled = contract.compile_reference(
        {
            "tier_quota_goal": {
                "type": "ratios",
                "update_mode": "replace",
                "sprint_weight": 30,
                "stable_weight": 40,
                "protect_weight": 30,
            }
        },
        context_target_count=45,
    )

    tier_result = compiled["summary"]["tier_result"]
    assert tier_result["submitted_weights"] == {
        "sprint": 30,
        "stable": 40,
        "protect": 30,
    }
    assert tier_result["weights"] == {"sprint": 3, "stable": 4, "protect": 3}
    assert tier_result["counts"] == {"sprint": 14, "stable": 18, "protect": 13}


def test_plan_change_spec_410_json_schema_forbids_unknown_fields_and_discriminates_goals():
    schema = contract.PlanChangeSpec410.model_json_schema()

    assert schema["additionalProperties"] is False
    assert schema["properties"]["tier_quota_goal"]
    assert schema["properties"]["risk_structure_goal"]
    assert "soft_preferences" not in schema["properties"]


def test_plan_change_spec_410_reference_is_compatible_with_runtime_normalizers():
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


def test_release_410_m2_dialog_asset_has_exact_isolated_scenario_matrix():
    payload = json.loads(M2_CASE_PATH.read_text(encoding="utf-8"))
    cases = payload["cases"]

    assert payload["metadata"]["release"] == "4.1.0-m2"
    assert payload["metadata"]["expectedCaseCount"] == len(cases) == 8
    assert payload["metadata"]["expectedStepCount"] == sum(
        len(case["prompts"]) for case in cases
    ) == 21
    assert [case["name"] for case in cases] == [
        "410-m2-range-max-satisfied-persists-without-plan-churn",
        "410-m2-range-max-violated-rebalances-plan",
        "410-m2-range-patch-preserves-historical-bounds",
        "410-m2-cross-type-patch-blocked-without-new-pending",
        "410-m2-ratio-persists-source-and-canonical-resolution",
        "410-m2-confirmed-ratio-reresolves-for-new-target",
        "410-m2-semantic-ratio-repeat-is-no-change",
        "410-m2-range-min-total-infeasible-blocks-without-persistence",
    ]
    assert len({case["sessionId"] for case in cases}) == len(cases) == 8
    assert all(case["sessionId"] != "16" for case in cases)
    assert payload["defaults"]["cloneBackendStateFromSessionId"] == "16"
    assert payload["defaults"]["promptDefaults"]["warnElapsedSeconds"] == 60
    assert payload["defaults"]["promptDefaults"]["maxElapsedSeconds"] == 180
    assert all(case["fixtureContract"]["type"] == "formal_plan_present" for case in cases)
    assert all(
        any(step.get("expectedToolNames") == ["preview_plan_change"] for step in case["prompts"])
        for case in cases
    )


def test_quality_gate_registers_m2_without_mutating_frozen_final_action_pack(tmp_path):
    assert gate.M2_FINAL_ACTION_CASE_FILES == [M2_CASE_PATH.name]
    assert "tests/unit/test_release_410_plan_change_contract.py" in gate.LOCAL_PYTEST_TARGETS
    assert len(gate.FINAL_ACTION_CASE_FILES) == 24
    assert M2_CASE_PATH.name not in gate.FINAL_ACTION_CASE_FILES

    commands = gate.build_gate_plan(metrics_dir=tmp_path)
    frozen = gate._filter_commands(commands, {"final-action"})
    m2 = gate._filter_commands(commands, {"m2-final-action"})

    assert len(frozen) == 24
    assert len(m2) == 1
    assert m2[0].name == "m2-final-action-dialog_regression_410_m2_tier_allocation_cases"
    assert m2[0].command[m2[0].command.index("--cases") + 1] == (
        "examples/dialog_regression_410_m2_tier_allocation_cases.json"
    )
    assert "--clear-history-per-case" in m2[0].command
    assert "--clear-backend-pending-per-case" in m2[0].command
    assert "--clear-backend-planning-intent-per-case" in m2[0].command
    assert "--clone-backend-chat-session" in m2[0].command
    assert "--assert-plan-style" in m2[0].command
    assert m2[0].command[m2[0].command.index("--response-timeout") + 1] == "180"
