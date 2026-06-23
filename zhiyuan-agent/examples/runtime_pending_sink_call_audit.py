#!/usr/bin/env python3
"""Static audit for pending sink call sites.

This audit complements runtime_pending_entrypoint_audit.py. Entrypoint audit
tracks which symbols still exist; this file tracks who calls the low-level
pending/card sinks, so the 3.2.0 cut can restrict sink calls to compiler output
and apply/status guards.
"""

from __future__ import annotations

import argparse
import ast
import json
import time
from pathlib import Path
from typing import Any


DEFAULT_SERVICE_PATH = Path("app/service.py")
TARGET_SINKS = {
    "_create_pending_intent_confirmation_response",
    "_create_pending_plan_confirmation_response",
    "_create_pending_fix_proposal_confirmation_response",
    "_save_pending_confirmation_state",
}


def _load_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_entries(path: str) -> list[dict[str, Any]]:
    payload = _load_json(path)
    entries = payload.get("entries") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        raise ValueError("entry file must be a JSON array or {'entries': [...]}")
    return [entry for entry in entries if isinstance(entry, dict)]


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


class _CallVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.stack: list[str] = []
        self.calls: list[dict[str, Any]] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_Call(self, node: ast.Call) -> Any:
        target = ""
        if isinstance(node.func, ast.Name):
            target = node.func.id
        elif isinstance(node.func, ast.Attribute):
            target = node.func.attr
        if target in TARGET_SINKS:
            self.calls.append(
                {
                    "target": target,
                    "caller": ".".join(self.stack),
                    "line": node.lineno,
                }
            )
        self.generic_visit(node)


def _extract_calls(service_text: str) -> list[dict[str, Any]]:
    tree = ast.parse(service_text)
    visitor = _CallVisitor()
    visitor.visit(tree)
    counts: dict[str, int] = {}
    calls: list[dict[str, Any]] = []
    for call in visitor.calls:
        base_key = _call_key(call, include_occurrence=False)
        counts[base_key] = counts.get(base_key, 0) + 1
        calls.append({**call, "occurrence": counts[base_key]})
    return calls


def _call_key(call: dict[str, Any], *, include_occurrence: bool = True) -> str:
    key = f"{call.get('target')}::{call.get('caller')}"
    if include_occurrence:
        key += f"::{call.get('occurrence') or 1}"
    return key


def _entry_key(entry: dict[str, Any]) -> str:
    return f"{entry.get('target')}::{entry.get('caller')}::{entry.get('occurrence') or 1}"


def build_report(
    expected_entries: list[dict[str, Any]],
    *,
    service_text: str,
    expectations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    actual_calls = _extract_calls(service_text)
    actual_by_key = {_call_key(call): call for call in actual_calls}
    expected_by_key = {_entry_key(entry): entry for entry in expected_entries}

    records: list[dict[str, Any]] = []
    for entry in expected_entries:
        key = _entry_key(entry)
        actual = actual_by_key.get(key)
        kind = str(entry.get("kind") or "").strip()
        action = str(entry.get("phase4Action") or "").strip()
        present = actual is not None
        records.append(
            {
                "id": entry.get("id"),
                "target": entry.get("target"),
                "caller": entry.get("caller"),
                "occurrence": entry.get("occurrence") or 1,
                "kind": kind,
                "phase4Action": action,
                "risk": entry.get("risk"),
                "present": present,
                "line": actual.get("line") if actual else None,
                "legacyDirectCreate": bool(present and kind == "legacy_direct_create"),
                "compilerOnlySink": bool(present and kind == "compiler_sink_call"),
                "compilerEntryCall": bool(present and kind == "compiler_entry_call"),
                "statusKeep": bool(present and kind == "status_update_keep"),
                "rationale": entry.get("rationale"),
            }
        )

    unexpected = [
        call
        for call in actual_calls
        if _call_key(call) not in expected_by_key
    ]
    missing = [
        record
        for record in records
        if not record.get("present")
    ]
    by_kind: dict[str, int] = {}
    by_action: dict[str, int] = {}
    legacy_by_action: dict[str, int] = {}
    for record in records:
        kind = str(record.get("kind") or "")
        action = str(record.get("phase4Action") or "")
        by_kind[kind] = by_kind.get(kind, 0) + 1
        by_action[action] = by_action.get(action, 0) + 1
        if record.get("legacyDirectCreate"):
            legacy_by_action[action] = legacy_by_action.get(action, 0) + 1

    summary = {
        "expected": len(records),
        "actual": len(actual_calls),
        "present": len(records) - len(missing),
        "missing": len(missing),
        "unexpected": len(unexpected),
        "legacyDirectCreateCount": sum(1 for record in records if record.get("legacyDirectCreate")),
        "compilerOnlySinkCallCount": sum(1 for record in records if record.get("compilerOnlySink")),
        "compilerEntryCallCount": sum(1 for record in records if record.get("compilerEntryCall")),
        "statusUpdateKeepCount": sum(1 for record in records if record.get("statusKeep")),
        "byKind": by_kind,
        "byPhase4Action": by_action,
        "legacyDirectCreateByPhase4Action": legacy_by_action,
    }
    report = {
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "summary": summary,
        "records": records,
        "missingCalls": missing,
        "unexpectedCalls": unexpected,
        "legacyDirectCreateExamples": [
            record for record in records if record.get("legacyDirectCreate")
        ][:20],
    }
    failures: list[dict[str, Any]] = []
    expected = _as_dict((expectations or {}).get("expected"))
    for field in _as_list(_as_dict((expectations or {}).get("assert")).get("exact")):
        current: Any = report
        expected_current: Any = expected
        for part in str(field).split("."):
            if not isinstance(current, dict) or not isinstance(expected_current, dict):
                current = None
                expected_current = None
                break
            current = current.get(part)
            expected_current = expected_current.get(part)
        if current != expected_current:
            failures.append({"type": "exact", "field": field, "expected": expected_current, "actual": current})
    report["passed"] = not failures
    report["failures"] = failures
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit pending sink call sites.")
    parser.add_argument("--entries", required=True, help="expected sink call fixture JSON")
    parser.add_argument("--service", default=str(DEFAULT_SERVICE_PATH), help="path to app/service.py")
    parser.add_argument("--expectations", help="optional JSON expectations")
    parser.add_argument("--output", help="write report JSON")
    args = parser.parse_args()

    report = build_report(
        _load_entries(args.entries),
        service_text=Path(args.service).read_text(encoding="utf-8"),
        expectations=_load_json(args.expectations) if args.expectations else None,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
