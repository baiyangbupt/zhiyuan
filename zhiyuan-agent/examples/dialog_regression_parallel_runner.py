#!/usr/bin/env python3
"""Run dialog regression cases in parallel.

This wrapper fans out individual regression cases to separate
dialog_regression_runner.py processes so large suites can finish faster
without changing the existing runner semantics.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PYTHON = str(ROOT / ".venv" / "bin" / "python") if (ROOT / ".venv" / "bin" / "python").exists() else sys.executable
DEFAULT_URL = os.environ.get("ZHIYUAN_REGRESSION_AGENT_URL") or os.environ.get("AGENT_DIALOG_E2E_URL") or "ws://127.0.0.1:18291/gaotu-assistant-agent/plus/chat/1/bot/test/do"
DEFAULT_INTERNAL_URL = os.environ.get("ZHIYUAN_REGRESSION_BACKEND_URL") or os.environ.get("INTERNAL_SERVICE_URL") or "http://127.0.0.1:18290"
DEFAULT_OUTPUT_DIR = Path("/private/tmp/zhiyuan-agent-parallel-regression")
DEFAULT_BACKEND_DB_HOST = os.environ.get("ZHIYUAN_REGRESSION_DB_HOST") or "127.0.0.1"
DEFAULT_BACKEND_DB_PORT = os.environ.get("ZHIYUAN_REGRESSION_DB_PORT") or "3306"
DEFAULT_BACKEND_DB_USER = os.environ.get("ZHIYUAN_REGRESSION_DB_USER") or "root"
DEFAULT_BACKEND_DB_NAME = os.environ.get("ZHIYUAN_REGRESSION_DB_NAME") or "sales_bot"
DEFAULT_BACKEND_DB_PASSWORD = os.environ.get("ZHIYUAN_REGRESSION_DB_PASSWORD") or os.environ.get("MYSQL_PWD") or ""
DEFAULT_BACKEND_VOLUNTEER_DATA_DIR = (
    os.environ.get("ZHIYUAN_REGRESSION_VOLUNTEER_DATA_DIR")
    or str(ROOT.parent / "zhiyuan-server" / "data" / "tmp")
)


def _load_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_cases(path: str) -> list[dict[str, Any]]:
    payload = _load_json(path)
    return _expand_case_payload(payload)


def _expand_case_payload(data: Any) -> list[dict[str, Any]]:
    report_path = ROOT / "examples" / "dialog_case_evaluation_report.py"
    spec = importlib.util.spec_from_file_location("dialog_case_evaluation_report_for_parallel", report_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load dialog_case_evaluation_report from {report_path}")
    report = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(report)
    return report._expand_case_payload(data)


def _case_name(path: str) -> str:
    return Path(path).stem


@dataclass
class JobResult:
    case_file: str
    case_name: str
    rc: int
    metrics: Path
    log: Path


def _existing_run_artifacts(output_dir: Path) -> list[Path]:
    if not output_dir.exists():
        return []
    artifacts: list[Path] = []
    artifacts.extend(output_dir.glob("*.metrics.json"))
    artifacts.extend(output_dir.glob("*.log"))
    for name in ("parallel-summary.json", "root-cause-report.json"):
        path = output_dir / name
        if path.exists():
            artifacts.append(path)
    case_dir = output_dir / "_cases"
    if case_dir.exists():
        artifacts.extend(case_dir.glob("*.json"))
    return sorted(set(artifacts))


def _ensure_output_dir_ready(output_dir: Path, *, reuse_output_dir: bool) -> None:
    artifacts = _existing_run_artifacts(output_dir)
    if artifacts and not reuse_output_dir:
        sample = ", ".join(str(path) for path in artifacts[:5])
        if len(artifacts) > 5:
            sample += f", ... ({len(artifacts)} total)"
        raise ValueError(
            f"--output-dir already contains regression artifacts: {sample}. "
            "Use a fresh directory or pass --reuse-output-dir explicitly."
        )
    output_dir.mkdir(parents=True, exist_ok=True)


def _run_one(
    *,
    case_file: str,
    case_name: str,
    case_payload: dict[str, Any],
    output_dir: Path,
    url: str,
    internal_url: str,
    history_db: str | None,
    base_offset: int,
    clear_history_per_case: bool,
    clear_backend_pending_per_case: bool,
    clear_backend_planning_intent_per_case: bool,
    keep_response_text: bool,
    assert_plan_style: bool,
    ignore_thinking_assertions: bool = False,
    response_timeout: int,
    open_timeout: int,
    clone_backend_chat_session: bool = False,
    backend_db_host: str = DEFAULT_BACKEND_DB_HOST,
    backend_db_port: str = DEFAULT_BACKEND_DB_PORT,
    backend_db_user: str = DEFAULT_BACKEND_DB_USER,
    backend_db_password: str = DEFAULT_BACKEND_DB_PASSWORD,
    backend_db_name: str = DEFAULT_BACKEND_DB_NAME,
    backend_volunteer_data_dir: str = DEFAULT_BACKEND_VOLUNTEER_DATA_DIR,
) -> JobResult:
    stem = _case_name(case_file)
    case_dir = output_dir / "_cases"
    case_dir.mkdir(parents=True, exist_ok=True)
    temp_case_path = case_dir / f"{stem}__{case_name}.json"
    temp_case_path.write_text(json.dumps([case_payload], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    metrics = output_dir / f"{stem}__{case_name}.metrics.json"
    log = output_dir / f"{stem}__{case_name}.log"
    cmd = [
        PYTHON,
        "examples/dialog_regression_runner.py",
        "--url",
        url,
        "--cases",
        str(temp_case_path),
        "--metrics-output",
        str(metrics),
        "--open-timeout",
        str(open_timeout),
        "--response-timeout",
        str(response_timeout),
        "--session-offset",
        str(base_offset),
        "--internal-service-url",
        internal_url,
    ]
    if history_db:
        cmd.extend(["--history-db", history_db])
    if clear_history_per_case:
        cmd.append("--clear-history-per-case")
    if clear_backend_pending_per_case:
        cmd.append("--clear-backend-pending-per-case")
    if clear_backend_planning_intent_per_case:
        cmd.append("--clear-backend-planning-intent-per-case")
    if keep_response_text:
        cmd.append("--keep-response-text")
    if ignore_thinking_assertions:
        cmd.append("--ignore-thinking-assertions")
    if assert_plan_style:
        cmd.append("--assert-plan-style")
    if clone_backend_chat_session:
        cmd.append("--clone-backend-chat-session")
        cmd.extend(["--backend-db-host", backend_db_host])
        cmd.extend(["--backend-db-port", backend_db_port])
        cmd.extend(["--backend-db-user", backend_db_user])
        cmd.extend(["--backend-db-password", backend_db_password])
        cmd.extend(["--backend-db-name", backend_db_name])
        cmd.extend(["--backend-volunteer-data-dir", backend_volunteer_data_dir])

    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=ROOT)
    log.write_text(proc.stdout or "", encoding="utf-8")
    return JobResult(case_file=case_file, case_name=case_name, rc=proc.returncode, metrics=metrics, log=log)


def _collect_summary(results: list[JobResult], output_dir: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for item in results:
        if not item.metrics.exists():
            failures.append({"caseFile": item.case_file, "caseName": item.case_name, "rc": item.rc, "reason": "missing_metrics"})
            continue
        try:
            payload = json.loads(item.metrics.read_text(encoding="utf-8"))
        except Exception as exc:
            failures.append({"caseFile": item.case_file, "caseName": item.case_name, "rc": item.rc, "reason": f"metrics_parse_error:{exc}"})
            continue
        records.append(
            {
                "caseFile": item.case_file,
                "caseName": item.case_name,
                "rc": item.rc,
                "metrics": payload,
                "metricsPath": str(item.metrics),
                "logPath": str(item.log),
            }
        )
        if item.rc != 0:
            failures.append({"caseFile": item.case_file, "caseName": item.case_name, "rc": item.rc, "metricsPath": str(item.metrics), "logPath": str(item.log)})

    summary = {
        "outputDir": str(output_dir),
        "records": records,
        "failures": failures,
        "total": len(results),
        "passed": sum(1 for item in results if item.rc == 0),
        "failed": sum(1 for item in results if item.rc != 0),
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run dialog regression case files in parallel.")
    parser.add_argument("--cases", nargs="+", required=True, help="case json files to run")
    parser.add_argument("--parallelism", type=int, default=3, help="number of case-file jobs to run concurrently")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--internal-service-url", default=DEFAULT_INTERNAL_URL)
    parser.add_argument("--history-db", help="Agent SQLite history db to pass through to each child runner")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--session-offset-base", type=int, default=3000000, help="base offset used to derive per-job session offsets")
    parser.add_argument("--open-timeout", type=int, default=5)
    parser.add_argument("--response-timeout", type=int, default=180)
    parser.add_argument("--keep-response-text", action="store_true")
    parser.add_argument("--assert-plan-style", action="store_true")
    parser.add_argument(
        "--ignore-thinking-assertions",
        action="store_true",
        help="forward --ignore-thinking-assertions to each dialog_regression_runner child",
    )
    parser.add_argument("--clear-history-per-case", action="store_true")
    parser.add_argument("--clear-backend-pending-per-case", action="store_true")
    parser.add_argument("--clear-backend-planning-intent-per-case", action="store_true")
    parser.add_argument(
        "--clone-backend-chat-session",
        action="store_true",
        help="when a case clones backend extra-data, also clone assistant_chat_session row through MySQL",
    )
    parser.add_argument("--backend-db-host", default=DEFAULT_BACKEND_DB_HOST)
    parser.add_argument("--backend-db-port", default=DEFAULT_BACKEND_DB_PORT)
    parser.add_argument("--backend-db-user", default=DEFAULT_BACKEND_DB_USER)
    parser.add_argument("--backend-db-password", default=DEFAULT_BACKEND_DB_PASSWORD)
    parser.add_argument("--backend-db-name", default=DEFAULT_BACKEND_DB_NAME)
    parser.add_argument(
        "--backend-volunteer-data-dir",
        default=DEFAULT_BACKEND_VOLUNTEER_DATA_DIR,
        help="local zhiyuan-server data/tmp directory used with --clone-backend-chat-session",
    )
    parser.add_argument("--reuse-output-dir", action="store_true", help="allow writing into a directory with previous regression artifacts")
    args = parser.parse_args()

    case_files = [str(Path(case_file)) for case_file in args.cases]
    output_dir = Path(args.output_dir)
    try:
        _ensure_output_dir_ready(output_dir, reuse_output_dir=args.reuse_output_dir)
    except ValueError as exc:
        parser.error(str(exc))

    jobs: list[tuple[str, str, dict[str, Any], int]] = []
    for case_file in case_files:
        for case in _load_cases(case_file):
            case_name = str(case.get("name") or "").strip()
            if not case_name:
                continue
            jobs.append((case_file, case_name, case, args.session_offset_base + len(jobs) * 100000))

    results: list[JobResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.parallelism)) as executor:
        futures = []
        for case_file, case_name, case_payload, offset in jobs:
            futures.append(
                executor.submit(
                    _run_one,
                    case_file=case_file,
                    case_name=case_name,
                    case_payload=case_payload,
                    output_dir=output_dir,
                    url=args.url,
                    internal_url=args.internal_service_url,
                    history_db=args.history_db,
                    base_offset=offset,
                    clear_history_per_case=args.clear_history_per_case,
                    clear_backend_pending_per_case=args.clear_backend_pending_per_case,
                    clear_backend_planning_intent_per_case=args.clear_backend_planning_intent_per_case,
                    keep_response_text=args.keep_response_text,
                    assert_plan_style=args.assert_plan_style,
                    ignore_thinking_assertions=args.ignore_thinking_assertions,
                    response_timeout=args.response_timeout,
                    open_timeout=args.open_timeout,
                    clone_backend_chat_session=args.clone_backend_chat_session,
                    backend_db_host=args.backend_db_host,
                    backend_db_port=args.backend_db_port,
                    backend_db_user=args.backend_db_user,
                    backend_db_password=args.backend_db_password,
                    backend_db_name=args.backend_db_name,
                    backend_volunteer_data_dir=args.backend_volunteer_data_dir,
                )
            )
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    summary = _collect_summary(results, output_dir)
    summary_path = output_dir / "parallel-summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    raise SystemExit(0 if summary["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
