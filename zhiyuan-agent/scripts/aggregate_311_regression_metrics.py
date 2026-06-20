#!/usr/bin/env python3
"""Aggregate 3.1.1 three-round dialogue regression metrics from /private/tmp.

This is an analysis helper only. It reads metrics/log files and emits a compact
JSON summary for documentation.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


OUTPUT_ROOT = Path("/private/tmp")


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _is_permission_run(data: dict[str, Any], log_path: Path | None) -> bool:
    text = ""
    failures = data.get("failures") or []
    if failures:
        text += json.dumps(failures, ensure_ascii=False)
    if log_path and log_path.exists():
        try:
            text += "\n" + log_path.read_text(encoding="utf-8", errors="ignore")[-12000:]
        except Exception:
            pass
    return "PermissionError" in text and "Operation not permitted" in text


def _valid_metrics(data: dict[str, Any], log_path: Path | None) -> bool:
    summary = data.get("summary")
    if not isinstance(summary, dict):
        return False
    elapsed = summary.get("elapsed") or {}
    if not isinstance(elapsed, dict) or not elapsed.get("count"):
        return False
    records = data.get("records")
    if not isinstance(records, list) or not records:
        return False
    if _is_permission_run(data, log_path):
        return False
    return True


def _stem_round(path: Path, run_id: str) -> tuple[str, int] | None:
    pattern = re.compile(rf"^zhiyuan_311_3round_{re.escape(run_id)}_(.+)_r([0-9]+)\.json$")
    match = pattern.match(path.name)
    if not match:
        return None
    if match.group(1) == "run_status":
        return None
    return match.group(1), int(match.group(2))


def _classify_failure(case: str, message: str) -> str:
    haystack = f"{case}\n{message}"
    if "source original session_volunteer file missing" in haystack or "source_missing" in haystack:
        return "fixture_data"
    if (
        "assertContains FAILED" in haystack
        or "assertContainsAny FAILED" in haystack
        or "expectedKeywords" in haystack
        or "missing keywords" in haystack
        or "关键词" in haystack
    ):
        return "test_contract"
    if "pendingConfirmationCard" in haystack or "no pending" in haystack or "没有上一轮正在等待" in haystack:
        return "protocol_pending"
    if "analysis_only" in haystack and "pending" in haystack:
        return "protocol_router_renderer"
    if "排除专业类" in haystack or "negative" in haystack:
        return "model_semantic_polarity"
    if "timeout" in haystack.lower() or "response-timeout" in haystack:
        return "performance_timeout"
    return "unclassified"


def _failure_message(failure: Any) -> str:
    if isinstance(failure, dict):
        parts = []
        for key in ("message", "error", "reason", "assertion", "details"):
            value = failure.get(key)
            if value:
                parts.append(str(value))
        return " | ".join(parts) or json.dumps(failure, ensure_ascii=False)[:800]
    return str(failure)


def _failure_case(failure: Any, message: str) -> str:
    if isinstance(failure, dict):
        value = failure.get("case") or failure.get("caseName")
        if value:
            return str(value)
    match = re.match(r"(.+?) session=", message)
    if match:
        return match.group(1)
    return "unknown"


def _warning_case(warning: Any) -> str:
    text = str(warning)
    match = re.match(r"(.+?) session=", text)
    if match:
        return match.group(1)
    return "unknown"


def _warning_source_session(warning: Any) -> str | None:
    text = str(warning)
    match = re.search(r'"sourceSession":\s*"?(?P<session>[0-9]+)"?', text)
    if match:
        return match.group("session")
    return None


def _records(data: dict[str, Any]) -> list[dict[str, Any]]:
    records = data.get("records")
    return records if isinstance(records, list) else []


def _record_case(record: dict[str, Any]) -> str:
    return str(record.get("case") or record.get("caseName") or "")


def _record_step(record: dict[str, Any]) -> str:
    prompt = str(record.get("prompt") or "")
    step = record.get("stepIndex")
    return f"{_record_case(record)}#{step}: {prompt}"


def _record_elapsed(record: dict[str, Any]) -> int:
    value = record.get("elapsedMs")
    return int(value) if isinstance(value, (int, float)) else 0


def _record_tool_count(record: dict[str, Any]) -> int:
    obs = record.get("turnObservability")
    if isinstance(obs, dict):
        value = obs.get("toolCallCount")
        if isinstance(value, (int, float)):
            return int(value)
        calls = obs.get("toolCalls")
        if isinstance(calls, list):
            return len(calls)
    return 0


def _record_requests(record: dict[str, Any]) -> int:
    obs = record.get("turnObservability")
    if isinstance(obs, dict):
        agent = obs.get("agentRun")
        if isinstance(agent, dict):
            value = agent.get("requests")
            if isinstance(value, (int, float)):
                return int(value)
    return 0


def _percentile(values: list[int], pct: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = math.ceil((pct / 100.0) * len(ordered)) - 1
    index = max(0, min(index, len(ordered) - 1))
    return ordered[index]


def aggregate(run_id: str) -> dict[str, Any]:
    by_file: dict[str, dict[str, Any]] = {}
    all_slow: list[dict[str, Any]] = []
    all_tool_heavy: list[dict[str, Any]] = []
    failure_counter: Counter[str] = Counter()
    unstable_cases: dict[str, Counter[str]] = defaultdict(Counter)
    fixture_warnings: Counter[str] = Counter()

    for path in sorted(OUTPUT_ROOT.glob(f"zhiyuan_311_3round_{run_id}_*_r*.json")):
        parsed = _stem_round(path, run_id)
        if not parsed:
            continue
        stem, round_index = parsed
        log_path = OUTPUT_ROOT / f"zhiyuan_311_3round_{run_id}_logs" / f"{stem}_r{round_index}.log"
        data = _load_json(path)
        if not data or not _valid_metrics(data, log_path):
            continue
        summary = data.get("summary") or {}
        records = _records(data)
        file_item = by_file.setdefault(
            stem,
            {
                "rounds": {},
                "totals": {
                    "steps": 0,
                    "successfulSteps": 0,
                    "failedSteps": 0,
                    "elapsedMs": [],
                },
                "failureClasses": Counter(),
            },
        )
        elapsed = summary.get("elapsed") or {}
        file_item["rounds"][str(round_index)] = {
            "steps": summary.get("steps"),
            "successfulSteps": summary.get("successfulSteps"),
            "failedSteps": summary.get("failedSteps"),
            "medianMs": elapsed.get("medianMs"),
            "p95Ms": elapsed.get("p95Ms"),
            "maxMs": elapsed.get("maxMs"),
            "metrics": str(path),
            "log": str(log_path),
        }
        file_item["totals"]["steps"] += int(summary.get("steps") or 0)
        file_item["totals"]["successfulSteps"] += int(summary.get("successfulSteps") or 0)
        file_item["totals"]["failedSteps"] += int(summary.get("failedSteps") or 0)

        for record in records:
            elapsed_ms = _record_elapsed(record)
            if elapsed_ms:
                file_item["totals"]["elapsedMs"].append(elapsed_ms)
                all_slow.append(
                    {
                        "file": stem,
                        "round": round_index,
                        "caseStep": _record_step(record),
                        "elapsedMs": elapsed_ms,
                        "toolCalls": _record_tool_count(record),
                        "requests": _record_requests(record),
                    }
                )
            tool_count = _record_tool_count(record)
            if tool_count >= 5:
                all_tool_heavy.append(
                    {
                        "file": stem,
                        "round": round_index,
                        "caseStep": _record_step(record),
                        "elapsedMs": elapsed_ms,
                        "toolCalls": tool_count,
                        "requests": _record_requests(record),
                    }
                )

        log_tail = ""
        if log_path.exists():
            try:
                log_text = log_path.read_text(encoding="utf-8", errors="ignore")
                log_tail = log_text[-50000:]
                for match in re.finditer(r"sourceSession\": \"?([0-9]+)\"?.{0,600}?source original session_volunteer file missing", log_text):
                    fixture_warnings[match.group(1)] += 1
            except Exception:
                pass

        for warning in data.get("warnings") or []:
            text = str(warning)
            if "source original session_volunteer file missing" in text or "source_missing" in text:
                source_session = _warning_source_session(warning)
                if source_session:
                    fixture_warnings[source_session] += 1
                warning_case = _warning_case(warning)
                unstable_cases[warning_case]["fixture_warning"] += 1

        for failure in data.get("failures") or []:
            message = _failure_message(failure)
            case = _failure_case(failure, message)
            klass = _classify_failure(case, message)
            failure_counter[klass] += 1
            unstable_cases[case][klass] += 1
            file_item["failureClasses"][klass] += 1

    compact_files: dict[str, Any] = {}
    for stem, item in sorted(by_file.items()):
        totals = item["totals"]
        elapsed_values = totals.pop("elapsedMs")
        steps = totals["steps"]
        compact_files[stem] = {
            "rounds": item["rounds"],
            "aggregate": {
                "roundCount": len(item["rounds"]),
                "steps": steps,
                "successfulSteps": totals["successfulSteps"],
                "failedSteps": totals["failedSteps"],
                "passRate": round(totals["successfulSteps"] / steps, 4) if steps else None,
                "medianMs": _percentile(elapsed_values, 50),
                "p95Ms": _percentile(elapsed_values, 95),
                "maxMs": max(elapsed_values) if elapsed_values else None,
                "failureClasses": dict(item["failureClasses"]),
            },
        }

    return {
        "runId": run_id,
        "files": compact_files,
        "failureClasses": dict(failure_counter),
        "unstableCases": {case: dict(counter) for case, counter in sorted(unstable_cases.items())},
        "fixtureMissingSessionsTop": fixture_warnings.most_common(30),
        "slowestSteps": sorted(all_slow, key=lambda item: item["elapsedMs"], reverse=True)[:40],
        "toolHeavySteps": sorted(all_tool_heavy, key=lambda item: (item["toolCalls"], item["elapsedMs"]), reverse=True)[:40],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    result = aggregate(args.run_id)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
