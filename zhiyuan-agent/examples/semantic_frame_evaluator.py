#!/usr/bin/env python3
"""Evaluate SemanticIntentFrame shadow output against case expectations.

This is an offline report tool.  It does not start services, call LLMs, mutate
sessions, or change routing behavior.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any


REPORT_PATH = Path(__file__).with_name("dialog_case_evaluation_report.py")
SPEC = importlib.util.spec_from_file_location("dialog_case_evaluation_report_for_semantic_frame", REPORT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load dialog_case_evaluation_report from {REPORT_PATH}")
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _load_json(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {"records": value}


def _case_rows(
    *,
    case_definition_paths: list[str],
    current_path: str | None = None,
) -> list[dict[str, Any]]:
    definitions = report._merge_case_definition_indexes(case_definition_paths)
    current_index = report._build_case_index(_load_json(current_path)) if current_path else {}
    keys = sorted(set(definitions) | set(current_index))
    rows: list[dict[str, Any]] = []
    for key in keys:
        current_rows = current_index.get(key) or []
        item = report._build_case_report(
            key,
            None,
            current_rows[0] if current_rows else None,
            {},
            definitions,
        )
        expected = item.get("expectedSemanticFrame") or {}
        score = item.get("current", {}).get("score") if isinstance(item.get("current"), dict) else {}
        semantic_expectation = score.get("semanticExpectation") if isinstance(score, dict) else {}
        shadow = score.get("semanticRouterShadow") if isinstance(score, dict) else {}
        rows.append(
            {
                "case": item.get("case"),
                "stepIndex": item.get("stepIndex"),
                "recordKey": key,
                "prompt": item.get("prompt"),
                "flow": item.get("flow") or [],
                "coverage": item.get("coverage") or [],
                "expectedSemanticFrame": expected,
                "semanticRouterShadow": shadow if isinstance(shadow, dict) else {},
                "semanticExpectation": semantic_expectation if isinstance(semantic_expectation, dict) else {},
            }
        )
    return rows


def _increment(counter: dict[str, int], key: Any) -> None:
    text = _normalize_text(key)
    if text:
        counter[text] = counter.get(text, 0) + 1


def _frame_values(value: Any) -> list[str]:
    items = value if isinstance(value, list) else [value]
    return [_normalize_text(item) for item in items if _normalize_text(item)]


def _expected_frame_distribution(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    distribution: dict[str, dict[str, int]] = {
        "taskLayer": {},
        "topic": {},
        "verb": {},
        "sideEffect": {},
    }
    for row in rows:
        expected = row.get("expectedSemanticFrame") if isinstance(row.get("expectedSemanticFrame"), dict) else {}
        for field in distribution:
            for value in _frame_values(expected.get(field)):
                _increment(distribution[field], value)
    return distribution


def _semantic_status(row: dict[str, Any]) -> str:
    expected = row.get("expectedSemanticFrame") if isinstance(row.get("expectedSemanticFrame"), dict) else {}
    if not expected:
        return "missing_expected"
    semantic_expectation = row.get("semanticExpectation") if isinstance(row.get("semanticExpectation"), dict) else {}
    matched = semantic_expectation.get("matched")
    if matched is True:
        return "match"
    if matched is False:
        return "mismatch"
    status = _normalize_text(semantic_expectation.get("status")) if semantic_expectation else ""
    if status:
        return f"unverified:{status}"
    return "expected_only"


def _group_summary(rows: list[dict[str, Any]], field: str) -> dict[str, dict[str, int]]:
    grouped: dict[str, dict[str, int]] = {}
    for row in rows:
        values = row.get(field)
        keys = values if isinstance(values, list) and values else ["unclassified"]
        for key in keys:
            text = _normalize_text(key) or "unclassified"
            grouped.setdefault(text, {})
            _increment(grouped[text], _semantic_status(row))
    return dict(sorted(grouped.items()))


def _examples(rows: list[dict[str, Any]], *, status_prefix: str, limit: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        status = _semantic_status(row)
        if not status.startswith(status_prefix):
            continue
        semantic_expectation = row.get("semanticExpectation") if isinstance(row.get("semanticExpectation"), dict) else {}
        result.append(
            {
                "recordKey": row.get("recordKey"),
                "prompt": row.get("prompt"),
                "status": status,
                "expected": row.get("expectedSemanticFrame") or {},
                "actual": (row.get("semanticRouterShadow") or {}).get("frame") or {},
                "mismatches": semantic_expectation.get("mismatches") or [],
            }
        )
        if len(result) >= limit:
            break
    return result


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return int(round(ordered[lower] * (1 - weight) + ordered[upper] * weight))


def _latency_summary(values: list[int]) -> dict[str, int | None]:
    return {
        "count": len(values),
        "medianMs": _percentile(values, 0.5),
        "p95Ms": _percentile(values, 0.95),
        "maxMs": max(values) if values else None,
    }


def _duration_ms(row: dict[str, Any]) -> int | None:
    shadow = row.get("semanticRouterShadow")
    if not isinstance(shadow, dict):
        return None
    value = shadow.get("durationMs")
    return value if isinstance(value, int) else None


def _latency_breakdown(rows: list[dict[str, Any]]) -> dict[str, dict[str, int | None]]:
    all_values: list[int] = []
    by_status: dict[str, list[int]] = {}
    for row in rows:
        value = _duration_ms(row)
        if value is None:
            continue
        all_values.append(value)
        by_status.setdefault(_semantic_status(row), []).append(value)
    return {
        "all": _latency_summary(all_values),
        "byStatus": {
            status: _latency_summary(values)
            for status, values in sorted(by_status.items())
        },
    }


def build_report(
    *,
    case_definition_paths: list[str],
    current_path: str | None = None,
    sample_limit: int = 10,
) -> dict[str, Any]:
    rows = _case_rows(case_definition_paths=case_definition_paths, current_path=current_path)
    status_counts: dict[str, int] = {}
    for row in rows:
        _increment(status_counts, _semantic_status(row))
    total = len(rows)
    expected_total = total - status_counts.get("missing_expected", 0)
    matched = status_counts.get("match", 0)
    comparable = matched + status_counts.get("mismatch", 0)
    return {
        "total": total,
        "expectedTotal": expected_total,
        "comparableTotal": comparable,
        "matchRate": round(matched / comparable, 4) if comparable else None,
        "status": status_counts,
        "latency": _latency_breakdown(rows),
        "expectedFrameDistribution": _expected_frame_distribution(rows),
        "byFlow": _group_summary(rows, "flow"),
        "byCoverage": _group_summary(rows, "coverage"),
        "mismatchExamples": _examples(rows, status_prefix="mismatch", limit=sample_limit),
        "unverifiedExamples": _examples(rows, status_prefix="unverified", limit=sample_limit),
        "missingExpectedExamples": _examples(rows, status_prefix="missing_expected", limit=sample_limit),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate SemanticIntentFrame shadow coverage and match quality.")
    parser.add_argument("--case-definitions", action="append", required=True, help="case definition JSON; can be repeated")
    parser.add_argument("--current", help="optional dialog regression metrics/report JSON containing semanticRouterShadow")
    parser.add_argument("--sample-limit", type=int, default=10)
    parser.add_argument("--output", help="write JSON report to this path")
    args = parser.parse_args()

    payload = build_report(
        case_definition_paths=args.case_definitions,
        current_path=args.current,
        sample_limit=args.sample_limit,
    )
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
