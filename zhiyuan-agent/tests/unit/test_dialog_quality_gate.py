import importlib.util
import json
import sys
from pathlib import Path

import pytest


GATE_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_quality_gate.py"
SPEC = importlib.util.spec_from_file_location("dialog_quality_gate", GATE_PATH)
assert SPEC and SPEC.loader
gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)


def test_gate_plan_covers_release_and_current_dialog_cases(tmp_path):
    commands = gate.build_gate_plan(metrics_dir=tmp_path)
    live_case_args = [
        command.command[command.command.index("--cases") + 1]
        for command in commands
        if command.category == "live"
    ]

    assert "examples/dialog_regression_400_agent_smoke_cases.json" in live_case_args
    assert "examples/dialog_regression_400_plan_operation_cases.json" in live_case_args
    assert "examples/dialog_regression_400_explore_intent_cases.json" in live_case_args
    assert "examples/dialog_regression_400_readonly_real_session_cases.json" in live_case_args
    assert "examples/dialog_regression_400_core_effect_perf_cases.json" in live_case_args
    assert "examples/dialog_regression_400_effect_perf_cases.json" in live_case_args
    assert "examples/dialog_regression_400_open_quality_cases.json" in live_case_args
    assert "examples/dialog_regression_400_quality_realistic_user_cases.json" in live_case_args
    assert "examples/dialog_regression_400_dialogue_derived_cases.json" in live_case_args
    assert "examples/dialog_regression_400_career_direction_cases.json" in live_case_args
    assert "examples/dialog_regression_400_review_repair_cases.json" in live_case_args
    assert "examples/dialog_regression_400_production_abstracted_cases.json" in live_case_args
    assert "examples/dialog_regression_400_requirement_plan_action_cases.json" in live_case_args
    assert all(Path(case).name.startswith("dialog_regression_400_") for case in live_case_args)
    assert len(live_case_args) == len(gate.PINNED_LIVE_CASE_FILES)


def test_gate_plan_covers_400_review_repair_live_report_and_semantic(tmp_path):
    commands = gate.build_gate_plan(metrics_dir=tmp_path)
    expected_stem = "dialog_regression_400_review_repair_cases"
    command_by_name = {command.name: command for command in commands}

    live = command_by_name[f"live-{expected_stem}"]
    report = command_by_name[f"report-{expected_stem}"]
    semantic = command_by_name[f"semantic-frame-{expected_stem}"]

    assert live.command[live.command.index("--cases") + 1] == f"examples/{expected_stem}.json"
    assert "--keep-response-text" in live.command
    assert "--assert-plan-style" in live.command
    assert report.depends_on == [f"live-{expected_stem}"]
    assert semantic.depends_on == [f"live-{expected_stem}"]


def test_dialogue_derived_gate_uses_per_case_history_clear(tmp_path):
    commands = gate.build_gate_plan(metrics_dir=tmp_path)
    command = next(
        item
        for item in commands
        if item.name == "live-dialog_regression_400_dialogue_derived_cases"
    )

    assert "--clear-history-per-case" in command.command
    assert "--clear-backend-pending-per-case" in command.command
    assert "--clear-backend-planning-intent-per-case" in command.command
    assert "--keep-response-text" in command.command
    assert "--assert-plan-style" in command.command


def test_live_gate_passes_backend_args_for_clone_backed_cases_only(tmp_path):
    commands = gate.build_gate_plan(
        metrics_dir=tmp_path,
        agent_url="ws://127.0.0.1:8042/chat",
        internal_service_url="http://127.0.0.1:8080",
        backend_db_password="pw",
    )
    command_by_name = {command.name: command for command in commands}

    smoke = command_by_name["live-dialog_regression_400_agent_smoke_cases"]
    review = command_by_name["live-dialog_regression_400_review_repair_cases"]
    requirement = command_by_name["live-dialog_regression_400_requirement_plan_action_cases"]

    assert "--clear-history-per-case" in smoke.command
    assert "--clear-backend-pending-per-case" in smoke.command
    assert "--clear-backend-planning-intent-per-case" in smoke.command
    assert "--internal-service-url" in smoke.command
    assert "http://127.0.0.1:8080" in smoke.command
    assert "--clone-backend-chat-session" in smoke.command
    assert "--backend-db-password" in smoke.command
    assert "pw" in smoke.command

    for command in (review, requirement):
        assert "--internal-service-url" in command.command
        assert "http://127.0.0.1:8080" in command.command
        assert "--clone-backend-chat-session" in command.command
        assert "--backend-db-password" in command.command
        assert "pw" in command.command


def test_gate_plan_adds_clone_backed_final_action_pack(tmp_path):
    commands = gate.build_gate_plan(
        metrics_dir=tmp_path,
        agent_url="ws://127.0.0.1:8000/chat",
        internal_service_url="http://127.0.0.1:8080",
        backend_db_password="pw",
    )
    final_action_commands = [command for command in commands if command.category == "final-action"]
    final_action_case_args = [
        command.command[command.command.index("--cases") + 1]
        for command in final_action_commands
    ]

    assert len(final_action_commands) == len(gate.FINAL_ACTION_CASE_FILES)
    assert "examples/dialog_regression_400_direct_confirm_execution_cases.json" in final_action_case_args
    assert "examples/dialog_regression_400_g1_g32_direct_cases.json" in final_action_case_args
    assert "examples/dialog_regression_400_v216_region_remote_final_cases.json" in final_action_case_args
    for command in final_action_commands:
        assert command.name.startswith("final-action-dialog_regression_400_")
        assert "--clone-backend-chat-session" in command.command
        assert "--clear-history-per-case" in command.command
        assert "--clear-backend-pending-per-case" in command.command
        assert "--clear-backend-planning-intent-per-case" in command.command
        assert "--keep-response-text" in command.command
        assert "--assert-plan-style" in command.command
        assert "--url" in command.command
        assert "ws://127.0.0.1:8000/chat" in command.command
        assert "--internal-service-url" in command.command
        assert "http://127.0.0.1:8080" in command.command
        assert "--backend-db-password" in command.command
        assert "pw" in command.command
        assert str(tmp_path) in str(command.output)


def test_final_action_formal_plan_cases_do_not_use_empty_session_17_fixture():
    violations = []
    for case_file_name in gate.FINAL_ACTION_CASE_FILES:
        payload = json.loads((gate.EXAMPLES / case_file_name).read_text(encoding="utf-8"))
        defaults = payload.get("defaults", {}) if isinstance(payload, dict) else {}
        cases = payload.get("cases", []) if isinstance(payload, dict) else payload
        for case in cases:
            contract = case.get("fixtureContract", defaults.get("fixtureContract", {}))
            if not isinstance(contract, dict) or contract.get("type") != "formal_plan_present":
                continue
            source_session = case.get(
                "cloneBackendStateFromSessionId",
                defaults.get(
                    "cloneBackendStateFromSessionId",
                    case.get(
                        "sourceSessionId",
                        defaults.get("sourceSessionId", case.get("sessionId")),
                    ),
                ),
            )
            if str(source_session or "") == "17":
                violations.append(f"{case_file_name}:{case.get('name')}")

    assert violations == []


def test_pinned_live_cases_do_not_target_shared_source_sessions():
    violations = []
    for case_file_name in gate.PINNED_LIVE_CASE_FILES:
        payload = json.loads((gate.EXAMPLES / case_file_name).read_text(encoding="utf-8"))
        cases = payload.get("cases", []) if isinstance(payload, dict) else payload
        for case in cases:
            if str(case.get("sessionId") or "") in {"16", "17"}:
                violations.append(f"{case_file_name}:{case.get('name')}")

    assert violations == []


def test_final_action_ordered_plan_mutations_require_formal_plan_fixture():
    violations = []
    mutation_assertions = {
        "lengthLessThanBefore",
        "lengthGreaterThanBefore",
        "changedFromBefore",
        "maxNumericFieldLessThanOrEqual",
    }
    for case_file_name in gate.FINAL_ACTION_CASE_FILES:
        payload = json.loads((gate.EXAMPLES / case_file_name).read_text(encoding="utf-8"))
        defaults = payload.get("defaults", {}) if isinstance(payload, dict) else {}
        cases = payload.get("cases", []) if isinstance(payload, dict) else payload
        for case in cases:
            mutates_ordered_plan = any(
                assertion.get("key") == "planningState"
                and "orderedPlanState" in str(assertion.get("path") or "")
                and bool(mutation_assertions & assertion.keys())
                for step in case.get("prompts", [])
                for assertion in step.get("assertBackendExtraData", [])
            )
            if not mutates_ordered_plan:
                continue
            contract = case.get("fixtureContract", defaults.get("fixtureContract", {}))
            if not isinstance(contract, dict) or contract.get("type") != "formal_plan_present":
                violations.append(f"{case_file_name}:{case.get('name')}")

    assert violations == []


def test_final_action_ordered_plan_pruning_cannot_pass_with_empty_plan():
    violations = []
    for case_file_name in gate.FINAL_ACTION_CASE_FILES:
        payload = json.loads((gate.EXAMPLES / case_file_name).read_text(encoding="utf-8"))
        cases = payload.get("cases", []) if isinstance(payload, dict) else payload
        for case in cases:
            for step in case.get("prompts", []):
                for assertion in step.get("assertBackendExtraData", []):
                    is_ordered_pruning = (
                        assertion.get("key") == "planningState"
                        and "orderedPlanState" in str(assertion.get("path") or "")
                        and (
                            assertion.get("lengthLessThanBefore") is True
                            or "maxNumericFieldLessThanOrEqual" in assertion
                        )
                    )
                    if is_ordered_pruning and int(assertion.get("minLength") or 0) < 1:
                        violations.append(
                            f"{case_file_name}:{case.get('name')}:{assertion.get('path')}"
                        )

    assert violations == []


def test_final_action_explicit_clone_sources_have_volunteer_fixture():
    violations = []
    volunteer_dir = gate.ROOT.parent / "zhiyuan-server" / "data" / "tmp"
    for case_file_name in gate.FINAL_ACTION_CASE_FILES:
        payload = json.loads((gate.EXAMPLES / case_file_name).read_text(encoding="utf-8"))
        defaults = payload.get("defaults", {}) if isinstance(payload, dict) else {}
        cases = payload.get("cases", []) if isinstance(payload, dict) else payload
        for case in cases:
            source_session = case.get(
                "cloneBackendStateFromSessionId",
                defaults.get("cloneBackendStateFromSessionId"),
            )
            if not source_session:
                continue
            source_file = volunteer_dir / f"session_volunteer_{source_session}.json"
            if not source_file.exists():
                violations.append(f"{case_file_name}:{case.get('name')}:{source_session}")

    assert violations == []


def test_gate_plan_adds_quality_report_for_each_live_case(tmp_path):
    commands = gate.build_gate_plan(metrics_dir=tmp_path)
    live_names = {command.name.replace("live-", "") for command in commands if command.category == "live"}
    report_names = {
        command.name.replace("report-", "")
        for command in commands
        if command.category == "report" and command.name.startswith("report-")
    }

    assert live_names
    assert live_names == report_names


def test_gate_plan_adds_semantic_frame_report_for_each_live_case(tmp_path):
    commands = gate.build_gate_plan(metrics_dir=tmp_path)
    live_names = {command.name.replace("live-", "") for command in commands if command.category == "live"}
    semantic_names = {
        command.name.replace("semantic-frame-", "")
        for command in commands
        if command.category == "report" and command.name.startswith("semantic-frame-")
    }
    sample = next(
        command
        for command in commands
        if command.name == "semantic-frame-dialog_regression_400_dialogue_derived_cases"
    )

    assert live_names == semantic_names
    assert "examples/semantic_frame_evaluator.py" in sample.command
    assert sample.depends_on == ["live-dialog_regression_400_dialogue_derived_cases"]


def test_gate_plan_covers_model_provider_quality_sets(tmp_path):
    commands = gate.build_gate_plan(
        metrics_dir=tmp_path,
        provider_config="providers.local.json",
        provider_names=["kimi", "deepseek"],
    )
    model_commands = [command for command in commands if command.category == "model"]
    model_case_args = [
        command.command[command.command.index("--cases") + 1]
        for command in model_commands
    ]

    assert "examples/model_provider_benchmark_e2e_cases.json" in model_case_args
    assert "examples/model_provider_400_quality_readonly_cases.json" in model_case_args
    assert "examples/model_provider_400_open_quality_realistic_cases.json" in model_case_args
    for command in model_commands:
        assert "--provider" in command.command
        assert "kimi" in command.command
        assert "deepseek" in command.command
        assert "providers.local.json" in command.command


def test_execute_defaults_to_local_only(tmp_path, monkeypatch):
    captured = {}

    def fake_run_commands(commands, *, stop_on_failure):
        captured["categories"] = [command.category for command in commands]
        captured["stop"] = stop_on_failure
        return 0

    monkeypatch.setattr(gate, "_run_commands", fake_run_commands)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "dialog_quality_gate.py",
            "--execute",
            "--metrics-dir",
            str(tmp_path),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        gate.main()

    assert exc.value.code == 0
    assert captured["categories"] == ["local"]
    assert captured["stop"] is True


def test_local_gate_filters_removed_pytest_targets(tmp_path):
    commands = gate.build_gate_plan(metrics_dir=tmp_path)
    local = next(command for command in commands if command.name == "local-pytest-regression")

    assert "tests/unit/test_dialog_quality_gate.py" in local.command
    assert "tests/unit/models/test_semantic_router.py" not in local.command
    assert all(
        (gate.ROOT / target).exists()
        for target in local.command
        if target.startswith("tests/")
    )
