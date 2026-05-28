import importlib.util
import sys
from pathlib import Path

import pytest


GATE_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_quality_gate.py"
SPEC = importlib.util.spec_from_file_location("dialog_quality_gate", GATE_PATH)
assert SPEC and SPEC.loader
gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)


def test_gate_plan_covers_release_and_historical_dialog_cases(tmp_path):
    commands = gate.build_gate_plan(metrics_dir=tmp_path)
    live_case_args = [
        command.command[command.command.index("--cases") + 1]
        for command in commands
        if command.category == "live"
    ]

    assert "examples/dialog_regression_301_agent_smoke_cases.json" in live_case_args
    assert "examples/dialog_regression_302_agent_cases.json" in live_case_args
    assert "examples/dialog_regression_303_effect_perf_cases.json" in live_case_args
    assert "examples/dialog_regression_303_open_quality_cases.json" in live_case_args
    assert "examples/dialog_regression_303_realistic_user_cases.json" in live_case_args
    assert "examples/dialog_regression_303_dialogue_derived_cases.json" in live_case_args
    assert "examples/dialog_regression_plan_correctness_cases.json" in live_case_args
    assert "examples/dialog_regression_comprehensive_cases.json" in live_case_args
    assert len(live_case_args) >= 20


def test_dialogue_derived_gate_uses_per_case_history_clear(tmp_path):
    commands = gate.build_gate_plan(metrics_dir=tmp_path)
    command = next(
        item
        for item in commands
        if item.name == "live-dialog_regression_303_dialogue_derived_cases"
    )

    assert "--clear-history-per-case" in command.command
    assert "--keep-response-text" in command.command
    assert "--assert-plan-style" in command.command


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
        if command.name == "semantic-frame-dialog_regression_303_dialogue_derived_cases"
    )

    assert live_names == semantic_names
    assert "examples/semantic_frame_evaluator.py" in sample.command
    assert sample.depends_on == ["live-dialog_regression_303_dialogue_derived_cases"]


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
    assert "examples/model_provider_303_quality_readonly_cases.json" in model_case_args
    assert "examples/model_provider_303_open_quality_realistic_cases.json" in model_case_args
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
