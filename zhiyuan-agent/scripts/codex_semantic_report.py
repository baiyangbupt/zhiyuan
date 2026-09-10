#!/usr/bin/env python3
"""汇总 Codex 语义烟测 JSONL 结果；本脚本不调用模型。"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


def classify_result(record: dict[str, Any]) -> str:
    if record.get("status") in {"timed_out", "environment_blocked"}:
        return "environment_blocked"
    errors = record.get("errors") or []
    if record.get("errorCode") == "turn_timeout" or any(
        "disconnected" in json.dumps(error, ensure_ascii=False).lower()
        or "reconnect" in json.dumps(error, ensure_ascii=False).lower()
        for error in errors
    ):
        return "environment_blocked"
    if record.get("outputValidationError"):
        return "contract_failure"
    if record.get("status") != "completed":
        return "model_failure"
    evaluation = record.get("evaluation") or {}
    if not evaluation:
        return "model_failure"
    return "passed" if evaluation.get("passed") else "semantic_failure"


def _scenario_key(record: dict[str, Any], index: int) -> str:
    return str(record.get("batchScenario") or record.get("scenario") or f"__record_{index}")


def _failure_reasons(rows: Iterable[dict[str, Any]]) -> Counter[str]:
    return Counter(
        failure
        for row in rows
        for failure in (row.get("evaluation") or {}).get("failures", [])
    )


def build_report(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(records)
    categories = Counter(classify_result(row) for row in rows)
    final_indices_by_scenario: dict[str, int] = {}
    for index, row in enumerate(rows):
        final_indices_by_scenario[_scenario_key(row, index)] = index
    final_indices = set(final_indices_by_scenario.values())
    final_rows = [row for index, row in enumerate(rows) if index in final_indices]
    final_categories = Counter(classify_result(row) for row in final_rows)
    failures = _failure_reasons(rows)
    final_failures = _failure_reasons(final_rows)
    completed = [row for row in rows if row.get("status") == "completed"]
    latencies = [float(row["elapsedMs"]) for row in rows if isinstance(row.get("elapsedMs"), (int, float))]
    tool_calls = [len((row.get("trace") or {}).get("toolCalls") or []) for row in completed]
    evidence_cases = sum(bool((row.get("trace") or {}).get("evidenceIds")) for row in completed)
    recoveries = sum(
        bool((row.get("recovery") or {}).get("outputRepaired"))
        for row in rows
    )
    attempts_by_scenario: dict[str, int] = {}
    for row in rows:
        scenario = str(row.get("batchScenario") or row.get("scenario") or "")
        if not scenario:
            continue
        attempts_by_scenario[scenario] = attempts_by_scenario.get(scenario, 0) + 1
    return {
        "total": len(rows),
        "scenarioTotal": len(final_rows),
        "categories": dict(sorted(categories.items())),
        "finalCategories": dict(sorted(final_categories.items())),
        "passed": final_categories["passed"],
        "qualityRate": (
            final_categories["passed"] / len(final_rows) if final_rows else 0.0
        ),
        "attemptQualityRate": categories["passed"] / len(rows) if rows else 0.0,
        "failureReasons": dict(sorted(failures.items())),
        "finalFailureReasons": dict(sorted(final_failures.items())),
        "observability": {
            "completed": len(completed),
            "evidenceCoverage": evidence_cases / len(completed) if completed else 0.0,
            "averageElapsedMs": sum(latencies) / len(latencies) if latencies else None,
            "averageToolCalls": sum(tool_calls) / len(tool_calls) if tool_calls else None,
            "outputRepairCount": recoveries,
            "attemptsByScenario": dict(sorted(attempts_by_scenario.items())),
        },
        "cases": [
            {
                "scenario": row.get("scenario"),
                "scenarioKey": _scenario_key(row, index),
                "batchScenario": row.get("batchScenario"),
                "category": classify_result(row),
                "passed": (row.get("evaluation") or {}).get("passed"),
                "failures": (row.get("evaluation") or {}).get("failures", []),
                "elapsedMs": row.get("elapsedMs"),
                "toolCallCount": len((row.get("trace") or {}).get("toolCalls") or []),
                "evidenceCount": len((row.get("trace") or {}).get("evidenceIds") or []),
                "batchAttempt": row.get("batchAttempt"),
                "retryCategory": row.get("retryCategory"),
                "errorCode": row.get("errorCode"),
                "finalAttempt": index in final_indices,
            }
            for index, row in enumerate(rows)
        ],
    }


def load_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if isinstance(value, dict):
                records.append(value)
    return records


def write_report(output: Path, report: dict[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="烟测结果 JSONL")
    parser.add_argument("--output", type=Path, help="汇总 JSON 输出路径")
    args = parser.parse_args()
    report = build_report(load_records(args.input))
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        write_report(args.output, report)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
