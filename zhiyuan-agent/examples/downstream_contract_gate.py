#!/usr/bin/env python3
"""Aggregate 3.2.0 downstream contract reports into a single offline gate.

Inputs are reports produced by:

- downstream_policy_replay.py
- downstream_policy_java_request.py
- downstream_adapter_dry_run.py

The gate does not call models, backend services, rank, WebSocket, or apply
paths. It separates hard component failures from expected design gaps such as
rank-only policies or admission-path mapping risk.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any


def _load_json(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _merge_counts(*counts: dict[str, Any]) -> dict[str, int]:
    result: dict[str, int] = {}
    for count in counts:
        for key, value in _as_dict(count).items():
            try:
                increment = int(value or 0)
            except (TypeError, ValueError):
                increment = 0
            result[str(key)] = result.get(str(key), 0) + increment
    return result


def _component_summary(name: str, report: dict[str, Any]) -> dict[str, Any]:
    summary = _as_dict(report.get("summary"))
    total = int(summary.get("total") or 0)
    failed = int(summary.get("failed") or 0)
    return {
        "name": name,
        "present": bool(report),
        "total": total,
        "passed": int(summary.get("passed") or 0),
        "failed": failed,
        "passRate": summary.get("passRate"),
        "hardFailed": failed > 0,
    }


def _gap_examples(report: dict[str, Any], field: str, limit: int = 12) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    for record in _as_list(report.get("records")):
        values = record.get(field)
        if isinstance(values, dict):
            values = [key for key, count in values.items() if int(count or 0) > 0]
        for value in _as_list(values):
            if not value:
                continue
            examples.append({"caseId": record.get("caseId"), "gap": value})
            if len(examples) >= limit:
                return examples
    return examples


def _capacity_examples(report: dict[str, Any], limit: int = 12) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    for record in _as_list(report.get("records")):
        status = str(record.get("capacityStatus") or "").strip()
        if not status:
            statuses = _as_dict(record.get("capacityStatuses"))
            for key, count in statuses.items():
                if int(count or 0) > 0:
                    examples.append({"caseId": record.get("caseId"), "capacityStatus": key})
                    break
        elif status != "satisfied":
            examples.append(
                {
                    "caseId": record.get("caseId"),
                    "capacityStatus": status,
                    "noResultReason": record.get("noResultReason"),
                    "shortageCount": record.get("shortageCount"),
                }
            )
        if len(examples) >= limit:
            return examples
    return examples


def build_report(
    *,
    replay_report: dict[str, Any],
    java_request_report: dict[str, Any],
    adapter_dry_run_report: dict[str, Any],
) -> dict[str, Any]:
    replay_summary = _as_dict(replay_report.get("summary"))
    request_summary = _as_dict(java_request_report.get("summary"))
    adapter_summary = _as_dict(adapter_dry_run_report.get("summary"))
    components = [
        _component_summary("policyReplay", replay_report),
        _component_summary("javaRequest", java_request_report),
        _component_summary("adapterDryRun", adapter_dry_run_report),
    ]
    hard_failures = [component for component in components if component["hardFailed"]]
    adapter_gap_counts = _merge_counts(request_summary.get("adapterGapCounts"))
    contract_gap_counts = _merge_counts(adapter_summary.get("contractGapCounts"))
    capacity_statuses = _merge_counts(
        replay_summary.get("capacityStatuses"),
        adapter_summary.get("capacityStatuses"),
    )
    expected_gap_total = sum(adapter_gap_counts.values()) + sum(contract_gap_counts.values())
    return {
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "summary": {
            "gatePassed": not hard_failures,
            "componentCount": len(components),
            "hardFailureCount": len(hard_failures),
            "expectedGapCount": expected_gap_total,
            "components": components,
            "capacityStatuses": capacity_statuses,
            "adapterGapCounts": adapter_gap_counts,
            "contractGapCounts": contract_gap_counts,
            "requestReady": int(request_summary.get("requestReady") or 0),
            "requestNotReady": int(request_summary.get("requestNotReady") or 0),
            "missingMustCoverCount": int(replay_summary.get("missingMustCoverCount") or 0),
        },
        "hardFailureExamples": [
            {
                "component": component["name"],
                "failureExamples": _as_list(
                    {
                        "policyReplay": replay_report,
                        "javaRequest": java_request_report,
                        "adapterDryRun": adapter_dry_run_report,
                    }[component["name"]].get("failureExamples")
                )[:5],
            }
            for component in hard_failures
        ],
        "expectedGapExamples": {
            "adapterGaps": _gap_examples(java_request_report, "adapterGaps"),
            "contractGaps": _gap_examples(adapter_dry_run_report, "contractGapCounts"),
            "capacityDiagnostics": _capacity_examples(replay_report) + _capacity_examples(adapter_dry_run_report),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate downstream contract reports.")
    parser.add_argument("--policy-replay-report", required=True)
    parser.add_argument("--java-request-report", required=True)
    parser.add_argument("--adapter-dry-run-report", required=True)
    parser.add_argument("--output", help="write report JSON")
    args = parser.parse_args()

    report = build_report(
        replay_report=_load_json(args.policy_replay_report),
        java_request_report=_load_json(args.java_request_report),
        adapter_dry_run_report=_load_json(args.adapter_dry_run_report),
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
