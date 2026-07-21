#!/usr/bin/env python3
"""Build and optionally run the Agent dialog quality regression gate.

The default mode is dry-run.  This script is meant to make the release gate
explicit and repeatable without accidentally calling live LLM services.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
DEFAULT_METRICS_DIR = Path("/private/tmp/zhiyuan-agent-dialog-quality-gate")

LOCAL_PYTEST_TARGETS = [
    "tests/unit/test_release_410_m0_contract.py",
    "tests/unit/test_release_410_plan_change_contract.py",
    "tests/unit/models/test_semantic_router.py",
    "tests/unit/test_semantic_frame_evaluator.py",
    "tests/unit/test_semantic_frame_probe.py",
    "tests/unit/test_dialog_quality_gate.py",
    "tests/unit/test_dialog_regression_runner.py",
    "tests/unit/test_dialog_case_evaluation_report.py",
    "tests/unit/test_model_provider_benchmark.py",
    "tests/unit/test_mainline_dialog_scenarios.py",
    "tests/unit/test_action_resolver.py",
    "tests/unit/test_chat_service_history_persistence.py",
    "tests/unit/test_ws_compat.py",
]

PINNED_LIVE_CASE_FILES = [
    "dialog_regression_400_agent_smoke_cases.json",
    "dialog_regression_400_plan_operation_cases.json",
    "dialog_regression_400_explore_intent_cases.json",
    "dialog_regression_400_readonly_real_session_cases.json",
    "dialog_regression_400_core_effect_perf_cases.json",
    "dialog_regression_400_effect_perf_cases.json",
    "dialog_regression_400_open_quality_cases.json",
    "dialog_regression_400_quality_realistic_user_cases.json",
    "dialog_regression_400_dialogue_derived_cases.json",
    "dialog_regression_400_career_direction_cases.json",
    "dialog_regression_400_review_repair_cases.json",
    "dialog_regression_400_production_abstracted_cases.json",
    "dialog_regression_400_requirement_plan_action_cases.json",
]

FINAL_ACTION_CASE_FILES = [
    "dialog_regression_400_direct_confirm_execution_cases.json",
    "dialog_regression_400_g1_g32_direct_cases.json",
    "dialog_regression_400_realistic_user_cases.json",
    "dialog_regression_400_v143_constraint_apply_cases.json",
    "dialog_regression_400_v150_candidate_view_cases.json",
    "dialog_regression_400_v151_attribute_final_action_cases.json",
    "dialog_regression_400_v153_major_final_action_cases.json",
    "dialog_regression_400_v154_tag_final_action_cases.json",
    "dialog_regression_400_v155_realistic_final_action_cases.json",
    "dialog_regression_400_v156_realistic_broadened_final_action_cases.json",
    "dialog_regression_400_v157_realistic_cancel_combo_cases.json",
    "dialog_regression_400_v158_pending_combo_negation_cases.json",
    "dialog_regression_400_v173_action_expansion_final_cases.json",
    "dialog_regression_400_v179_pending_replace_review_quality_cases.json",
    "dialog_regression_400_v183_realistic_followup_quality_cases.json",
    "dialog_regression_400_v211_region_area_final_cases.json",
    "dialog_regression_400_v212_region_area_expanded_final_cases.json",
    "dialog_regression_400_v213_region_area_quality_final_cases.json",
    "dialog_regression_400_v216_region_remote_final_cases.json",
    "dialog_regression_400_fill_to_count_cases.json",
    "dialog_regression_400_coverage_preserve_cases.json",
    "dialog_regression_400_priority_rules_cases.json",
    "dialog_regression_400_tier_minimum_cases.json",
    "dialog_regression_400_tier_quota_cases.json",
]

M2_FINAL_ACTION_CASE_FILES = [
    "dialog_regression_410_m2_tier_allocation_cases.json",
]

MODEL_PROVIDER_CASE_FILES = [
    "model_provider_benchmark_e2e_cases.json",
    "model_provider_400_quality_readonly_cases.json",
    "model_provider_400_open_quality_realistic_cases.json",
]


@dataclass
class GateCommand:
    name: str
    category: str
    command: list[str]
    description: str
    output: str | None = None
    depends_on: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "command": self.command,
            "description": self.description,
            "output": self.output,
            "dependsOn": self.depends_on,
        }


def _python() -> str:
    local = ROOT / ".venv" / "bin" / "python"
    return str(local) if local.exists() else sys.executable


def _required_existing_case_files(case_files: list[str], *, label: str) -> list[str]:
    existing = [name for name in case_files if (EXAMPLES / name).exists()]
    missing = [name for name in case_files if not (EXAMPLES / name).exists()]
    if missing:
        raise FileNotFoundError(f"missing {label} dialog regression case files: {missing}")
    return existing


def _case_file_names() -> list[str]:
    return _required_existing_case_files(PINNED_LIVE_CASE_FILES, label="pinned live")


def _final_action_case_file_names() -> list[str]:
    return _required_existing_case_files(FINAL_ACTION_CASE_FILES, label="final-action")


def _m2_final_action_case_file_names() -> list[str]:
    return _required_existing_case_files(M2_FINAL_ACTION_CASE_FILES, label="M2 final-action")


def _metrics_path(metrics_dir: Path, stem: str, suffix: str) -> Path:
    return metrics_dir / f"{stem}_{suffix}"


def _case_uses_backend_clone(case_name: str) -> bool:
    case_path = EXAMPLES / case_name
    if not case_path.exists():
        return False
    text = case_path.read_text(encoding="utf-8")
    return "cloneBackendStateFromSessionId" in text or "cloneBackendScoreFromSessionId" in text


def _existing_local_pytest_targets() -> list[str]:
    """Return local pytest targets that exist in this checkout."""
    return [target for target in LOCAL_PYTEST_TARGETS if (ROOT / target).exists()]


def _build_final_action_commands(
    case_names: list[str],
    *,
    category: str,
    name_prefix: str,
    metrics_suffix: str,
    metrics_dir: Path,
    py: str,
    ws_args: list[str],
    internal_service_args: list[str],
    backend_db_args: list[str],
) -> list[GateCommand]:
    commands: list[GateCommand] = []
    for case_name in case_names:
        case_path = f"examples/{case_name}"
        stem = Path(case_name).stem
        metrics_output = _metrics_path(metrics_dir, stem, metrics_suffix)
        commands.append(
            GateCommand(
                name=f"{name_prefix}-{stem}",
                category=category,
                command=[
                    py,
                    "examples/dialog_regression_runner.py",
                    "--cases",
                    case_path,
                    "--clear-history-per-case",
                    "--clear-backend-pending-per-case",
                    "--clear-backend-planning-intent-per-case",
                    "--clone-backend-chat-session",
                    "--keep-response-text",
                    "--assert-plan-style",
                    "--response-timeout",
                    "180",
                    "--metrics-output",
                    str(metrics_output),
                    *ws_args,
                    *internal_service_args,
                    *backend_db_args,
                ],
                description=f"Run clone-backed {category} WebSocket regression cases from {case_path}.",
                output=str(metrics_output),
            )
        )
    return commands


def build_gate_plan(
    *,
    metrics_dir: Path = DEFAULT_METRICS_DIR,
    agent_url: str | None = None,
    internal_service_url: str | None = None,
    backend_db_password: str | None = None,
    provider_config: str = "examples/model_provider_benchmark.providers.example.json",
    provider_names: list[str] | None = None,
) -> list[GateCommand]:
    py = _python()
    commands: list[GateCommand] = []
    commands.append(
        GateCommand(
            name="local-pytest-regression",
            category="local",
            command=[py, "-m", "pytest", *_existing_local_pytest_targets(), "-q"],
            description="Run local unit/integration/regression tests for routing, pending protocol, preview/apply, style and semantic frame observation.",
        )
    )

    ws_args = ["--url", agent_url] if agent_url else []
    internal_service_args = ["--internal-service-url", internal_service_url] if internal_service_url else []
    backend_db_args = ["--backend-db-password", backend_db_password] if backend_db_password else []
    for case_name in _case_file_names():
        case_path = f"examples/{case_name}"
        stem = Path(case_name).stem
        metrics_output = _metrics_path(metrics_dir, stem, "live.json")
        report_output = _metrics_path(metrics_dir, stem, "report.md")
        clone_args = ["--clone-backend-chat-session", *backend_db_args] if _case_uses_backend_clone(case_name) else []
        commands.append(
            GateCommand(
                name=f"live-{stem}",
                category="live",
                command=[
                    py,
                    "examples/dialog_regression_runner.py",
                    "--cases",
                    case_path,
                    "--clear-history-per-case",
                    "--clear-backend-pending-per-case",
                    "--clear-backend-planning-intent-per-case",
                    "--keep-response-text",
                    "--assert-plan-style",
                    "--response-timeout",
                    "180",
                    "--metrics-output",
                    str(metrics_output),
                    *ws_args,
                    *internal_service_args,
                    *clone_args,
                ],
                description=f"Run WebSocket dialog regression cases from {case_path}.",
                output=str(metrics_output),
            )
        )
        commands.append(
            GateCommand(
                name=f"report-{stem}",
                category="report",
                command=[
                    py,
                    "examples/dialog_case_evaluation_report.py",
                    "--current",
                    str(metrics_output),
                    "--case-definitions",
                    case_path,
                    "--markdown-detail",
                    "--output",
                    str(report_output),
                ],
                description=f"Build case-level quality report for {case_path}.",
                output=str(report_output),
                depends_on=[f"live-{stem}"],
            )
        )
        semantic_output = _metrics_path(metrics_dir, stem, "semantic-frame.json")
        commands.append(
            GateCommand(
                name=f"semantic-frame-{stem}",
                category="report",
                command=[
                    py,
                    "examples/semantic_frame_evaluator.py",
                    "--case-definitions",
                    case_path,
                    "--current",
                    str(metrics_output),
                    "--output",
                    str(semantic_output),
                ],
                description=f"Evaluate SemanticIntentFrame observation expectations for {case_path}.",
                output=str(semantic_output),
                depends_on=[f"live-{stem}"],
            )
        )

    commands.extend(
        _build_final_action_commands(
            _final_action_case_file_names(),
            category="final-action",
            name_prefix="final-action",
            metrics_suffix="final-action-live.json",
            metrics_dir=metrics_dir,
            py=py,
            ws_args=ws_args,
            internal_service_args=internal_service_args,
            backend_db_args=backend_db_args,
        )
    )
    commands.extend(
        _build_final_action_commands(
            _m2_final_action_case_file_names(),
            category="m2-final-action",
            name_prefix="m2-final-action",
            metrics_suffix="m2-final-action-live.json",
            metrics_dir=metrics_dir,
            py=py,
            ws_args=ws_args,
            internal_service_args=internal_service_args,
            backend_db_args=backend_db_args,
        )
    )

    provider_args: list[str] = []
    for provider in provider_names or []:
        provider_args.extend(["--provider", provider])
    for case_name in MODEL_PROVIDER_CASE_FILES:
        case_path = f"examples/{case_name}"
        stem = Path(case_name).stem
        output = _metrics_path(metrics_dir, stem, "model-provider.json")
        commands.append(
            GateCommand(
                name=f"model-provider-{stem}",
                category="model",
                command=[
                    py,
                    "examples/model_provider_benchmark.py",
                    "--config",
                    provider_config,
                    "--agent-only",
                    "--cases",
                    case_path,
                    "--keep-response-text",
                    "--clear-history",
                    "--output",
                    str(output),
                    *provider_args,
                ],
                description=f"Run multi-model agent benchmark for {case_path}; provider config must reference env vars, not raw keys.",
                output=str(output),
            )
        )
    return commands


def _filter_commands(commands: list[GateCommand], modes: set[str]) -> list[GateCommand]:
    if "all" in modes:
        return commands
    return [command for command in commands if command.category in modes]


_SENSITIVE_COMMAND_OPTIONS = {"--backend-db-password"}


def _command_for_display(command: list[str]) -> list[str]:
    rendered: list[str] = []
    redact_next = False
    for part in command:
        if redact_next:
            rendered.append("<redacted>")
            redact_next = False
            continue
        rendered.append(part)
        if part in _SENSITIVE_COMMAND_OPTIONS:
            redact_next = True
    return rendered


def _command_dict_for_display(command: GateCommand) -> dict[str, Any]:
    payload = command.as_dict()
    payload["command"] = _command_for_display(command.command)
    return payload


def _render_markdown(commands: list[GateCommand]) -> str:
    lines = [
        "# Agent Dialog Quality Gate",
        "",
        f"- generatedAt: {time.strftime('%Y-%m-%dT%H:%M:%S%z')}",
        f"- commands: {len(commands)}",
        "",
        "| Category | Name | Output | Command |",
        "| --- | --- | --- | --- |",
    ]
    for command in commands:
        rendered = " ".join(_command_for_display(command.command))
        lines.append(
            f"| {command.category} | {command.name} | {command.output or '-'} | `{rendered}` |"
        )
    return "\n".join(lines) + "\n"


def _write_plan(path: str | None, commands: list[GateCommand], *, markdown: bool) -> None:
    if markdown:
        text = _render_markdown(commands)
    else:
        text = json.dumps(
            {"commands": [_command_dict_for_display(command) for command in commands]},
            ensure_ascii=False,
            indent=2,
        ) + "\n"
    if path:
        Path(path).write_text(text, encoding="utf-8")
    else:
        print(text, end="")


def _run_commands(commands: list[GateCommand], *, stop_on_failure: bool) -> int:
    exit_code = 0
    for command in commands:
        print(f"[gate] running {command.name}: {' '.join(_command_for_display(command.command))}", flush=True)
        result = subprocess.run(command.command, cwd=ROOT, text=True)
        if result.returncode != 0:
            exit_code = result.returncode
            print(f"[gate] failed {command.name}: exit={result.returncode}", flush=True)
            if stop_on_failure:
                return exit_code
    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser(description="Build or run the Agent dialog quality gate.")
    parser.add_argument("--execute", action="store_true", help="run selected commands; default only prints the plan")
    parser.add_argument(
        "--mode",
        action="append",
        choices=["local", "live", "final-action", "m2-final-action", "report", "model", "all"],
        default=None,
        help="command category to include; repeatable. Default dry-run includes all, execute defaults to local.",
    )
    parser.add_argument("--metrics-dir", default=str(DEFAULT_METRICS_DIR), help="where live/report/model outputs are written")
    parser.add_argument("--agent-url", help="override WebSocket URL for live dialog runner")
    parser.add_argument("--internal-service-url", help="backend base URL passed to clone-backed final-action runners")
    parser.add_argument("--backend-db-password", help="database password passed to clone-backed final-action runners")
    parser.add_argument("--provider-config", default="examples/model_provider_benchmark.providers.example.json")
    parser.add_argument("--provider", action="append", default=[], help="provider name passed to model_provider_benchmark")
    parser.add_argument("--output", help="write the dry-run plan to this path")
    parser.add_argument("--markdown", action="store_true", help="render dry-run plan as markdown")
    parser.add_argument("--no-stop-on-failure", action="store_true", help="continue executing after a command fails")
    args = parser.parse_args()

    metrics_dir = Path(args.metrics_dir)
    commands = build_gate_plan(
        metrics_dir=metrics_dir,
        agent_url=args.agent_url,
        internal_service_url=args.internal_service_url,
        backend_db_password=args.backend_db_password,
        provider_config=args.provider_config,
        provider_names=list(args.provider or []),
    )
    default_modes = {"local"} if args.execute else {"all"}
    selected = _filter_commands(commands, set(args.mode or default_modes))

    if not args.execute:
        _write_plan(args.output, selected, markdown=args.markdown)
        return

    metrics_dir.mkdir(parents=True, exist_ok=True)
    raise SystemExit(_run_commands(selected, stop_on_failure=not args.no_stop_on_failure))


if __name__ == "__main__":
    main()
