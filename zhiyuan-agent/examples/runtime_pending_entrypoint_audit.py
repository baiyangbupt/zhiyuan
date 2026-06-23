#!/usr/bin/env python3
"""Static audit for runtime pending/card creation entrypoints.

This offline audit keeps the 3.2.0 hard-cut deletion list executable. It reads a
curated entrypoint fixture and checks whether the symbols still exist in
app/service.py, then aggregates which paths must be kept, restricted, migrated,
or deleted before runtime compiler cutover.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any


DEFAULT_SERVICE_PATH = Path("app/service.py")


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


def _read_text(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def _line_number(text: str, index: int) -> int:
    return text.count("\n", 0, max(0, index)) + 1


def _find_symbol(text: str, symbol: str) -> dict[str, Any]:
    escaped = re.escape(symbol)
    patterns = [
        rf"^\s*(?:async\s+)?def\s+{escaped}\b",
        rf"\b{escaped}\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.MULTILINE)
        if match:
            return {"present": True, "line": _line_number(text, match.start())}
    return {"present": False, "line": None}


def _audit_entry(entry: dict[str, Any], service_text: str) -> dict[str, Any]:
    symbol = str(entry.get("symbol") or "").strip()
    found = _find_symbol(service_text, symbol) if symbol else {"present": False, "line": None}
    kind = str(entry.get("kind") or "").strip()
    risk = str(entry.get("risk") or "").strip()
    is_legacy = kind in {"migrate_to_candidate", "delete_after_cut"}
    is_delete = kind == "delete_after_cut"
    return {
        "id": entry.get("id"),
        "symbol": symbol,
        "kind": kind,
        "phase4Action": entry.get("phase4Action"),
        "risk": risk,
        "present": bool(found.get("present")),
        "line": found.get("line"),
        "legacyRisk": bool(is_legacy and found.get("present")),
        "deleteAfterCut": bool(is_delete and found.get("present")),
        "rationale": entry.get("rationale"),
    }


def _assert_exact(expectations: dict[str, Any], report: dict[str, Any]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    exact = _as_list(_as_dict(expectations.get("assert")).get("exact"))
    expected = _as_dict(expectations.get("expected"))
    for field in exact:
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
    return failures


def build_report(
    entries: list[dict[str, Any]],
    *,
    service_text: str,
    expectations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    records = [_audit_entry(entry, service_text) for entry in entries]
    by_kind: dict[str, int] = {}
    by_action: dict[str, int] = {}
    missing_symbols: list[str] = []
    legacy_risk_count = 0
    delete_after_cut_count = 0
    for record in records:
        kind = str(record.get("kind") or "")
        action = str(record.get("phase4Action") or "")
        by_kind[kind] = by_kind.get(kind, 0) + 1
        by_action[action] = by_action.get(action, 0) + 1
        if not record.get("present"):
            missing_symbols.append(str(record.get("symbol") or ""))
        if record.get("legacyRisk"):
            legacy_risk_count += 1
        if record.get("deleteAfterCut"):
            delete_after_cut_count += 1
    report = {
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "summary": {
            "total": len(records),
            "present": len(records) - len(missing_symbols),
            "missing": len(missing_symbols),
            "missingSymbols": missing_symbols,
            "legacyRiskCount": legacy_risk_count,
            "deleteAfterCutCount": delete_after_cut_count,
            "byKind": by_kind,
            "byPhase4Action": by_action,
        },
        "records": records,
        "legacyRiskExamples": [record for record in records if record.get("legacyRisk")][:20],
        "deleteAfterCutExamples": [record for record in records if record.get("deleteAfterCut")][:20],
    }
    failures = _assert_exact(expectations or {}, report)
    report["passed"] = not failures
    report["failures"] = failures
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit pending/card runtime entrypoints.")
    parser.add_argument("--entries", required=True, help="entrypoint fixture JSON")
    parser.add_argument("--service", default=str(DEFAULT_SERVICE_PATH), help="path to app/service.py")
    parser.add_argument("--expectations", help="optional JSON expectations")
    parser.add_argument("--output", help="write report JSON")
    args = parser.parse_args()

    report = build_report(
        _load_entries(args.entries),
        service_text=_read_text(args.service),
        expectations=_load_json(args.expectations) if args.expectations else None,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
