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
    "tests/unit/models/test_semantic_router.py",
    "tests/unit/test_semantic_frame_evaluator.py",
    "tests/unit/test_semantic_frame_probe.py",
    "tests/unit/test_dialog_quality_gate.py",
    "tests/unit/test_dialog_regression_runner.py",
    "tests/unit/test_dialog_case_evaluation_report.py",
    "tests/unit/test_model_provider_benchmark.py",
    "tests/unit/test_mainline_dialog_scenarios.py",
    "tests/integration/test_dialog_style_coverage.py",
    "tests/regression/test_pending_protocol.py",
    "tests/regression/test_execution_preview.py",
    "tests/regression/test_normalize_action.py",
    "tests/regression/test_determine_stage.py",
    "tests/regression/test_execution_apply.py",
    "tests/unit/test_action_resolver.py",
    "tests/unit/test_plan_orchestration_tool.py",
    "tests/unit/test_plan_execution_tool.py",
    "tests/unit/test_plan_query_tool.py",
    "tests/unit/test_major_intent_fast_router.py",
    "tests/unit/test_plan_query_fast_router.py",
    "tests/unit/test_fast_route_arbitrator.py",
    "tests/unit/test_chat_service_history_persistence.py",
    "tests/unit/test_ws_compat.py",
]

PINNED_LIVE_CASE_FILES = [
    "dialog_regression_301_agent_smoke_cases.json",
    "dialog_regression_302_agent_cases.json",
    "dialog_regression_302_explore_intent_cases.json",
    "dialog_regression_302_readonly_real_session_cases.json",
    "dialog_regression_302_effect_perf_cases.json",
    "dialog_regression_303_effect_perf_cases.json",
    "dialog_regression_303_open_quality_cases.json",
    "dialog_regression_303_realistic_user_cases.json",
    "dialog_regression_303_dialogue_derived_cases.json",
    "dialog_regression_mainline_cases.json",
    "dialog_regression_full_journey_cases.json",
    "dialog_regression_plan_correctness_cases.json",
    "dialog_regression_plan_cases.json",
    "dialog_regression_robust_cases.json",
    "dialog_regression_advanced_cases.json",
    "dialog_regression_lifecycle_cases.json",
    "dialog_regression_enriched_cases.json",
    "dialog_regression_score_tier_cases.json",
    "dialog_regression_science_cases.json",
    "dialog_regression_special_cases.json",
    "dialog_regression_comprehensive_cases.json",
    "dialog_regression_310_review_repair_cases.json",
    "dialog_regression_310_production_abstracted_cases.json",
]

MODEL_PROVIDER_CASE_FILES = [
    "model_provider_benchmark_e2e_cases.json",
    "model_provider_303_quality_readonly_cases.json",
    "model_provider_303_open_quality_realistic_cases.json",
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


def _case_file_names() -> list[str]:
    discovered = {path.name for path in EXAMPLES.glob("dialog_regression_*_cases.json")}
    pinned = [name for name in PINNED_LIVE_CASE_FILES if (EXAMPLES / name).exists()]
    missing_pinned = [name for name in PINNED_LIVE_CASE_FILES if name not in discovered]
    if missing_pinned:
        raise FileNotFoundError(f"missing pinned dialog regression case files: {missing_pinned}")
    extra = sorted(discovered - set(pinned))
    return [*pinned, *extra]


def _metrics_path(metrics_dir: Path, stem: str, suffix: str) -> Path:
    return metrics_dir / f"{stem}_{suffix}"


def _existing_local_pytest_targets() -> list[str]:
    """Return local pytest targets that exist in this checkout."""
    return [target for target in LOCAL_PYTEST_TARGETS if (ROOT / target).exists()]


def build_gate_plan(
    *,
    metrics_dir: Path = DEFAULT_METRICS_DIR,
    agent_url: str | None = None,
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
            description="Run local unit/integration/regression tests for routing, pending protocol, preview/apply, style and semantic shadow.",
        )
    )

    ws_args = ["--url", agent_url] if agent_url else []
    for case_name in _case_file_names():
        case_path = f"examples/{case_name}"
        stem = Path(case_name).stem
        metrics_output = _metrics_path(metrics_dir, stem, "live.json")
        report_output = _metrics_path(metrics_dir, stem, "report.md")
        clear_arg = "--clear-history-per-case" if case_name == "dialog_regression_303_dialogue_derived_cases.json" else "--clear-history"
        commands.append(
            GateCommand(
                name=f"live-{stem}",
                category="live",
                command=[
                    py,
                    "examples/dialog_regression_runner.py",
                    "--cases",
                    case_path,
                    clear_arg,
                    "--keep-response-text",
                    "--assert-plan-style",
                    "--response-timeout",
                    "180",
                    "--metrics-output",
                    str(metrics_output),
                    *ws_args,
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
                description=f"Evaluate SemanticIntentFrame shadow expectations for {case_path}.",
                output=str(semantic_output),
                depends_on=[f"live-{stem}"],
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
        rendered = " ".join(command.command)
        lines.append(
            f"| {command.category} | {command.name} | {command.output or '-'} | `{rendered}` |"
        )
    return "\n".join(lines) + "\n"


def _write_plan(path: str | None, commands: list[GateCommand], *, markdown: bool) -> None:
    if markdown:
        text = _render_markdown(commands)
    else:
        text = json.dumps({"commands": [command.as_dict() for command in commands]}, ensure_ascii=False, indent=2) + "\n"
    if path:
        Path(path).write_text(text, encoding="utf-8")
    else:
        print(text, end="")


def _run_commands(commands: list[GateCommand], *, stop_on_failure: bool) -> int:
    exit_code = 0
    for command in commands:
        print(f"[gate] running {command.name}: {' '.join(command.command)}", flush=True)
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
        choices=["local", "live", "report", "model", "all"],
        default=None,
        help="command category to include; repeatable. Default dry-run includes all, execute defaults to local.",
    )
    parser.add_argument("--metrics-dir", default=str(DEFAULT_METRICS_DIR), help="where live/report/model outputs are written")
    parser.add_argument("--agent-url", help="override WebSocket URL for live dialog runner")
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
