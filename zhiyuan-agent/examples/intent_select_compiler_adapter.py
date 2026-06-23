#!/usr/bin/env python3
"""Offline adapter for handle_intent_select -> CompiledProposal.

This does not change runtime behavior. It captures the contract needed to move
ChatService.handle_intent_select from direct pending creation to a compiler-only
intent sink path.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any


def _load_cases(path: str) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(cases, list):
        raise ValueError("case file must be a JSON array or {'cases': [...]}")
    return [case for case in cases if isinstance(case, dict)]


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _list_str(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value is None:
        return []
    return [str(value)]


def _unique(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _selected_values(selected_data: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in _as_list(selected_data.get("selected")) if isinstance(item, dict) and item]


def _merge_selected_values(selected_values: list[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for selected in selected_values:
        for key, value in selected.items():
            if isinstance(value, dict):
                target = merged.setdefault(key, {})
                if not isinstance(target, dict):
                    continue
                for sub_key, sub_value in value.items():
                    existing = target.setdefault(sub_key, [])
                    if not isinstance(existing, list):
                        existing = []
                    target[sub_key] = _unique(existing + _list_str(sub_value))
            elif isinstance(value, list):
                existing = merged.setdefault(key, [])
                if isinstance(existing, list):
                    merged[key] = _unique(existing + value)
            else:
                merged[key] = value
    return merged


def _contains_any(merged: dict[str, Any], keys: set[str]) -> bool:
    for category in merged.values():
        if isinstance(category, dict):
            for key, value in category.items():
                if key in keys and _list_str(value):
                    return True
    return False


def _normalize_constraint_type(selected_data: dict[str, Any], intent_mode: str) -> str:
    raw = str(
        selected_data.get("constraintIntentType")
        or selected_data.get("constraint_intent_type")
        or "default"
    ).strip() or "default"
    if intent_mode != "constraint":
        return "default"
    if raw in {"only_keep", "must_have", "exclude_hard", "default"}:
        return raw
    return "default"


def _summarize(merged: dict[str, Any], *, intent_mode: str, constraint_type: str) -> str:
    labels: list[str] = []
    for category in ("major_intents", "school_intents", "city_intents", "career_intents"):
        values = _as_dict(merged.get(category))
        for key in ("level3", "level2", "school_names", "cities", "provinces", "careers", "negative"):
            labels.extend(_list_str(values.get(key)))
    prefix = "采纳报考要求" if intent_mode == "constraint" else "采纳报考想法"
    if constraint_type == "only_keep":
        prefix = "限定范围"
    elif constraint_type == "must_have":
        prefix = "必须覆盖"
    elif constraint_type == "exclude_hard":
        prefix = "排除范围"
    if not labels:
        return prefix
    return f"{prefix}：" + "、".join(_unique(labels)[:6])


def build_compiled_proposal(case: dict[str, Any]) -> dict[str, Any]:
    selected_data = _as_dict(case.get("selectedData"))
    selected_values = _selected_values(selected_data)
    blocking_reasons: list[str] = []
    if not selected_values:
        blocking_reasons.append("intent_select_requires_selected_values")
    merged = _merge_selected_values(selected_values)
    intent_mode = str(case.get("intentMode") or selected_data.get("intentMode") or "preference").strip()
    if intent_mode not in {"preference", "constraint"}:
        intent_mode = "preference"
    constraint_type = _normalize_constraint_type(selected_data, intent_mode)
    if intent_mode == "constraint" and constraint_type in {"only_keep", "must_have"}:
        if not _contains_any(merged, {"level3", "level2", "school_names", "cities", "provinces"}):
            blocking_reasons.append("constraint_intent_requires_scope")
    batch = str(case.get("batch") or selected_data.get("batch") or "01").strip() or "01"
    compiled_id = str(case.get("compiledProposalId") or f"intent-select-{case.get('caseId') or 'case'}").strip()
    if not compiled_id:
        blocking_reasons.append("missing_compiled_proposal_id")
    summary = str(selected_data.get("displaySummary") or "").strip() or _summarize(
        merged,
        intent_mode=intent_mode,
        constraint_type=constraint_type,
    )
    intent_payload = {
        "selectedData": selected_data,
        "merged": merged,
        "intentMode": intent_mode,
        "constraintIntentType": constraint_type,
        "batch": batch,
        "summary": summary,
        "scopeAnchor": "future_reference",
    }
    return {
        "caseId": case.get("caseId"),
        "compiledProposalId": compiled_id,
        "sideEffect": "intent_pending" if not blocking_reasons else "diagnostic",
        "outputType": "intent_change" if not blocking_reasons else "diagnostic",
        "pendingType": "intent_change" if not blocking_reasons else "none",
        "requiresConfirmation": not blocking_reasons,
        "executionPayload": (
            {
                "kind": "pending_intent_change",
                "actionFamilies": ["apply_selected_intents"],
                "requiresConfirmation": True,
                "targetView": None,
            }
            if not blocking_reasons
            else None
        ),
        "intentPayload": intent_payload if not blocking_reasons else None,
        "displayPayload": {
            "presentation": "confirmation_card" if not blocking_reasons else "diagnostic",
            "pendingCardType": "pendingConfirmationCard" if not blocking_reasons else "none",
            "summary": summary,
        },
        "replyPlan": {
            "mode": ["confirmable_intent"] if not blocking_reasons else ["diagnostic"],
            "focus": ["intent_select"],
            "blockingReasons": blocking_reasons,
        },
        "blockingReasons": blocking_reasons,
    }


def _get_path(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    compiled = build_compiled_proposal(case)
    failures: list[dict[str, Any]] = []
    expected = _as_dict(case.get("expected"))
    assertions = _as_dict(case.get("assert"))
    for field in _list_str(assertions.get("exact")):
        actual = _get_path(compiled, field)
        expected_value = _get_path(expected, field)
        if actual != expected_value:
            failures.append({"type": "exact", "field": field, "expected": expected_value, "actual": actual})
    for reason in _list_str(assertions.get("containsBlockingReasons")):
        if reason not in compiled.get("blockingReasons", []):
            failures.append({"type": "missing_blocking_reason", "expected": reason})
    return {
        **compiled,
        "passed": not failures,
        "failures": failures,
    }


def build_report(cases: list[dict[str, Any]]) -> dict[str, Any]:
    records = [_evaluate_case(case) for case in cases]
    total = len(records)
    passed = sum(1 for record in records if record.get("passed"))
    by_pending_type: dict[str, int] = {}
    blocking_reasons: dict[str, int] = {}
    for record in records:
        pending_type = str(record.get("pendingType") or "unknown")
        by_pending_type[pending_type] = by_pending_type.get(pending_type, 0) + 1
        for reason in record.get("blockingReasons") or []:
            blocking_reasons[reason] = blocking_reasons.get(reason, 0) + 1
    return {
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "passRate": round(passed / total, 4) if total else None,
            "byPendingType": by_pending_type,
            "blockingReasons": blocking_reasons,
        },
        "records": records,
        "failureExamples": [record for record in records if not record.get("passed")][:20],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate intent select compiled proposal adapter.")
    parser.add_argument("--cases", required=True, help="case JSON")
    parser.add_argument("--output", help="write report JSON")
    args = parser.parse_args()

    report = build_report(_load_cases(args.cases))
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
