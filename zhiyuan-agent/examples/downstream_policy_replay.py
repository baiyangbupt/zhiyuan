#!/usr/bin/env python3
"""Offline replay for 3.2.0 downstreamPolicy candidate/replacement effects.

This tool is a deterministic fixture replay. It does not call Java services,
rank providers, model providers, WebSocket, or backend state. It consumes
CompiledProposal.downstreamPolicy and small plan/candidate fixtures to validate
how preference strength should affect selection and replacement order.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any


def _load_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_cases(path: str) -> list[dict[str, Any]]:
    payload = _load_json(path)
    cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(cases, list):
        raise ValueError("case file must be a JSON array or {'cases': [...]}")
    return [case for case in cases if isinstance(case, dict)]


def _load_records(path: str, key: str = "records") -> list[dict[str, Any]]:
    payload = _load_json(path)
    records = payload.get(key) if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ValueError(f"record file must be a JSON array or {{'{key}': [...]}}")
    return [record for record in records if isinstance(record, dict)]


def _case_index(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        case_id = str(record.get("caseId") or "").strip()
        if case_id:
            result[case_id] = record
    return result


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    return [value]


def _list_str(value: Any) -> list[str]:
    result: list[str] = []
    for item in _as_list(value):
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _get_path(data: Any, path: str) -> Any:
    current = data
    for part in str(path or "").split("."):
        if not part:
            continue
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _text_tokens(item: dict[str, Any]) -> list[str]:
    values: list[Any] = [
        item.get("schoolName"),
        item.get("majorName"),
        item.get("schoolType"),
        item.get("schoolLevel"),
        item.get("schoolNature"),
        item.get("majorCategory"),
        item.get("tier"),
        item.get("region"),
        item.get("province"),
        item.get("city"),
        item.get("admissionPath"),
        item.get("batchName"),
        item.get("programType"),
        item.get("feeType"),
        *_as_list(item.get("tags")),
        *_as_list(item.get("majorTags")),
        *_as_list(item.get("schoolTags")),
        *_as_list(item.get("reasonCodes")),
    ]
    return _list_str(values)


def _matches_value(item: dict[str, Any], value: str) -> bool:
    target = str(value or "").strip()
    if not target:
        return False
    return any(target in token or token in target for token in _text_tokens(item))


def _matches_any(item: dict[str, Any], values: list[str]) -> bool:
    return any(_matches_value(item, value) for value in values)


def _scope_matches(item: dict[str, Any], scope: str) -> bool:
    text = str(scope or "").strip()
    if not text or text in {"future_reference", "current_plan", "candidate_pool", "special_path"}:
        return True
    return _matches_value(item, text)


def _numeric(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _positive_number(value: Any) -> float | None:
    number = _numeric(value)
    return number if number > 0 else None


def _tuition_per_year(item: dict[str, Any]) -> float | None:
    for key in ("tuitionPerYear", "annualTuition", "tuition", "planMoney"):
        number = _positive_number(item.get(key))
        if number is not None:
            return number
    return None


def _tuition_cap_from(*sources: dict[str, Any]) -> float | None:
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in ("maxTuitionPerYear", "tuitionCap", "maxTuition", "budgetCap", "maxPerYear"):
            number = _positive_number(source.get(key))
            if number is not None:
                return number
        for nested_key in ("tuitionBudget", "budget"):
            nested = source.get(nested_key)
            if isinstance(nested, dict):
                nested_cap = _tuition_cap_from(nested)
                if nested_cap is not None:
                    return nested_cap
    return None


def _tuition_over_cap(item: dict[str, Any], cap: float | None) -> bool:
    tuition = _tuition_per_year(item)
    return tuition is not None and cap is not None and tuition > cap


def _item_id(item: dict[str, Any]) -> str:
    return str(item.get("volunteerId") or item.get("unitId") or item.get("id") or "").strip()


def _candidate_score(item: dict[str, Any], policy: dict[str, Any]) -> tuple[float, list[str]]:
    selection = policy.get("candidateSelection") if isinstance(policy.get("candidateSelection"), dict) else {}
    rank_boost = selection.get("rankBoost") if isinstance(selection.get("rankBoost"), list) else []
    must_cover = _list_str(selection.get("mustCover"))
    soft_avoid = _list_str(selection.get("softAvoid"))
    score = _numeric(item.get("baseScore"))
    reasons: list[str] = []
    for value in must_cover:
        if _matches_value(item, value):
            score += 500
            reasons.append(f"mustCover:{value}")
    for boost in rank_boost:
        if not isinstance(boost, dict):
            continue
        values = _list_str(boost.get("values"))
        if not values or not _matches_any(item, values):
            continue
        weight = _numeric(boost.get("weight"))
        score += weight * 100
        strength = str(boost.get("strength") or "preference").strip()
        reasons.append(f"rankBoost:{strength}")
    if soft_avoid and _matches_any(item, soft_avoid):
        penalty = _positive_number(selection.get("softAvoidPenalty")) or 50
        score -= penalty
        reasons.append("softAvoid")
    admission_ratio = _numeric(item.get("admissionRatio") or item.get("admissionProbability"))
    score += admission_ratio / 100
    return score, reasons


def _filter_candidates(candidates: list[dict[str, Any]], policy: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selection = policy.get("candidateSelection") if isinstance(policy.get("candidateSelection"), dict) else {}
    scope = str(policy.get("scope") or "").strip()
    only_keep = _list_str(selection.get("onlyKeep"))
    hard_exclude = _list_str(selection.get("hardExclude"))
    admission_path = str(policy.get("admissionPath") or "").strip()
    tuition_cap = _tuition_cap_from(selection, policy)
    selected: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for item in candidates:
        reasons: list[str] = []
        if not _scope_matches(item, scope):
            reasons.append("outside_scope")
        if admission_path and str(item.get("admissionPath") or "").strip() != admission_path:
            reasons.append("admission_path_mismatch")
        if only_keep and not _matches_any(item, only_keep):
            reasons.append("outside_only_keep")
        if hard_exclude and _matches_any(item, hard_exclude):
            reasons.append("hard_exclude")
        if _tuition_over_cap(item, tuition_cap):
            reasons.append("tuition_cap_exceeded")
        if reasons:
            excluded.append({"itemId": _item_id(item), "reasons": reasons, "item": item})
        else:
            selected.append(item)
    return selected, excluded


def _select_candidates(candidates: list[dict[str, Any]], policy: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for item in candidates:
        score, reasons = _candidate_score(item, policy)
        scored.append(
            {
                "itemId": _item_id(item),
                "score": round(score, 4),
                "reasons": reasons,
                "item": item,
            }
        )
    scored.sort(key=lambda record: (-_numeric(record.get("score")), str(record.get("itemId") or "")))
    return scored[: max(0, int(limit or 0))]


def _replacement_reasons(item: dict[str, Any], policy: dict[str, Any]) -> list[str]:
    replacement = policy.get("replacementPolicy") if isinstance(policy.get("replacementPolicy"), dict) else {}
    selection = policy.get("candidateSelection") if isinstance(policy.get("candidateSelection"), dict) else {}
    reasons: list[str] = []
    for rule in replacement.get("replaceFirst") or []:
        if not isinstance(rule, dict):
            continue
        values = _list_str(rule.get("values") or rule.get("keepValues"))
        reason = str(rule.get("reason") or "").strip()
        if reason in {"tuition_cap_exceeded", "budget_cap_exceeded"}:
            tuition_cap = _tuition_cap_from(rule, selection, policy)
            if _tuition_over_cap(item, tuition_cap):
                reasons.append(reason)
            continue
        if reason == "outside_only_keep_scope":
            if values and not _matches_any(item, values):
                reasons.append(reason)
        elif values and _matches_any(item, values):
            reasons.append(reason or "replace_first")
    return reasons


def _protected_reasons(item: dict[str, Any], policy: dict[str, Any]) -> list[str]:
    replacement = policy.get("replacementPolicy") if isinstance(policy.get("replacementPolicy"), dict) else {}
    reasons: list[str] = []
    for rule in replacement.get("protectFromReplacement") or []:
        if not isinstance(rule, dict):
            continue
        values = _list_str(rule.get("values"))
        if values and _matches_any(item, values):
            reasons.append("protect:" + str(rule.get("strength") or "preference"))
    return reasons


def _plan_replacements(plan_items: list[dict[str, Any]], policy: dict[str, Any]) -> list[dict[str, Any]]:
    scope = str(policy.get("scope") or "").strip()
    candidates: list[dict[str, Any]] = []
    for item in plan_items:
        if not _scope_matches(item, scope):
            continue
        reasons = _replacement_reasons(item, policy)
        protected = _protected_reasons(item, policy)
        if reasons:
            candidates.append(
                {
                    "itemId": _item_id(item),
                    "priority": 0,
                    "reasons": reasons,
                    "protected": protected,
                    "item": item,
                }
            )
        elif protected:
            candidates.append(
                {
                    "itemId": _item_id(item),
                    "priority": 9,
                    "reasons": [],
                    "protected": protected,
                    "item": item,
                }
            )
    candidates.sort(key=lambda record: (int(record.get("priority") or 0), str(record.get("itemId") or "")))
    return candidates


def _must_cover_diagnostics(selected: list[dict[str, Any]], policy: dict[str, Any]) -> dict[str, Any]:
    selection = policy.get("candidateSelection") if isinstance(policy.get("candidateSelection"), dict) else {}
    required = _list_str(selection.get("mustCover"))
    covered: list[str] = []
    missing: list[str] = []
    for value in required:
        if any(_matches_value(record.get("item") or {}, value) for record in selected):
            covered.append(value)
        else:
            missing.append(value)
    return {
        "requiredMustCover": required,
        "coveredMustCover": covered,
        "missingMustCover": missing,
        "mustCoverSatisfied": not missing,
    }


def _capacity_diagnostics(
    *,
    candidates: list[dict[str, Any]],
    filtered: list[dict[str, Any]],
    excluded: list[dict[str, Any]],
    selected: list[dict[str, Any]],
    limit: int,
) -> dict[str, Any]:
    selection_limit = max(0, int(limit or 0))
    selected_count = len(selected)
    shortage_count = max(0, selection_limit - selected_count)
    no_result_reason = None
    if selection_limit <= 0:
        capacity_status = "not_requested"
    elif selected_count >= selection_limit:
        capacity_status = "satisfied"
    elif selected_count == 0:
        capacity_status = "no_result"
        if not candidates:
            no_result_reason = "empty_candidate_pool"
        elif not filtered and excluded:
            no_result_reason = "all_candidates_filtered"
        else:
            no_result_reason = "no_candidate_selected"
    else:
        capacity_status = "insufficient_candidates"
        no_result_reason = "capacity_insufficient_after_filters"
    return {
        "selectionLimit": selection_limit,
        "candidateCount": len(candidates),
        "availableCount": len(filtered),
        "selectedCount": selected_count,
        "excludedCount": len(excluded),
        "shortageCount": shortage_count,
        "capacityStatus": capacity_status,
        "noResultReason": no_result_reason,
    }


def _assert_exact(case: dict[str, Any], replay: dict[str, Any]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
    exact = ((case.get("assert") or {}).get("exact") or [])
    for field in exact:
        expected_value = _get_path(expected, str(field))
        actual_value = _get_path(replay, str(field))
        if expected_value != actual_value:
            failures.append(
                {
                    "type": "exact",
                    "field": str(field),
                    "expected": expected_value,
                    "actual": actual_value,
                }
            )
    return failures


def _assert_contains(case: dict[str, Any], replay: dict[str, Any]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    expected_contains = ((case.get("assert") or {}).get("contains") or {})
    if not isinstance(expected_contains, dict):
        return failures
    for field, expected_values in expected_contains.items():
        actual_values = set(_list_str(_get_path(replay, str(field))))
        missing = [value for value in _list_str(expected_values) if value not in actual_values]
        if missing:
            failures.append(
                {
                    "type": "contains",
                    "field": str(field),
                    "missing": missing,
                    "actual": sorted(actual_values),
                }
            )
    return failures


def _replay_case(case: dict[str, Any], compiled_by_case: dict[str, dict[str, Any]]) -> dict[str, Any]:
    case_id = str(case.get("caseId") or "").strip()
    compiled_case_id = str(case.get("compiledCaseId") or case_id).strip()
    compiled = compiled_by_case.get(compiled_case_id) or {}
    inline_policy = case.get("downstreamPolicy") if isinstance(case.get("downstreamPolicy"), dict) else {}
    compiled_policy = compiled.get("downstreamPolicy") if isinstance(compiled.get("downstreamPolicy"), dict) else {}
    policy = inline_policy or compiled_policy
    policy_source = "inline" if inline_policy else "compiler" if compiled_policy else "missing"
    fixture = case.get("fixture") if isinstance(case.get("fixture"), dict) else {}
    candidates = [item for item in fixture.get("candidateItems") or [] if isinstance(item, dict)]
    plan_items = [item for item in fixture.get("currentPlanItems") or [] if isinstance(item, dict)]
    limit = int(case.get("selectionLimit") or 3)
    filtered, excluded = _filter_candidates(candidates, policy)
    selected = _select_candidates(filtered, policy, limit)
    replacements = _plan_replacements(plan_items, policy)
    capacity = _capacity_diagnostics(
        candidates=candidates,
        filtered=filtered,
        excluded=excluded,
        selected=selected,
        limit=limit,
    )
    must_cover = _must_cover_diagnostics(selected, policy)
    replay = {
        "caseId": case_id,
        "compiledCaseId": compiled_case_id,
        "policyPresent": bool(policy),
        "policySource": policy_source,
        "selectedCandidateIds": [record["itemId"] for record in selected],
        "selectedCandidates": selected,
        "excludedCandidateIds": [record["itemId"] for record in excluded],
        "excludedCandidates": excluded,
        "replacementCandidateIds": [record["itemId"] for record in replacements if record.get("reasons")],
        "protectedPlanItemIds": [record["itemId"] for record in replacements if record.get("protected")],
        "replacementCandidates": replacements,
        **capacity,
        **must_cover,
    }
    failures = []
    if not policy:
        failures.append({"type": "missing_policy", "field": "downstreamPolicy"})
    failures.extend(_assert_exact(case, replay))
    failures.extend(_assert_contains(case, replay))
    return {
        **replay,
        "passed": not failures,
        "failures": failures,
    }


def build_report(cases: list[dict[str, Any]], compiler_records: list[dict[str, Any]]) -> dict[str, Any]:
    compiled_by_case = _case_index(compiler_records)
    records = [_replay_case(case, compiled_by_case) for case in cases]
    total = len(records)
    passed = sum(1 for record in records if record.get("passed"))
    failure_fields: dict[str, int] = {}
    capacity_statuses: dict[str, int] = {}
    missing_must_cover_count = 0
    for record in records:
        capacity_status = str(record.get("capacityStatus") or "").strip()
        if capacity_status:
            capacity_statuses[capacity_status] = capacity_statuses.get(capacity_status, 0) + 1
        missing_must_cover_count += len(record.get("missingMustCover") or [])
        for failure in record.get("failures") or []:
            field = str(failure.get("field") or failure.get("type") or "").strip()
            if field:
                failure_fields[field] = failure_fields.get(field, 0) + 1
    return {
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "passRate": round(passed / total, 4) if total else None,
            "failureFields": failure_fields,
            "capacityStatuses": capacity_statuses,
            "missingMustCoverCount": missing_must_cover_count,
        },
        "records": records,
        "failureExamples": [record for record in records if not record.get("passed")][:20],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay downstreamPolicy against offline candidate fixtures.")
    parser.add_argument("--cases", required=True, help="downstream replay case JSON")
    parser.add_argument("--compiler-report", help="proposal_compiler_golden report JSON")
    parser.add_argument("--output", help="write report JSON")
    args = parser.parse_args()

    report = build_report(
        _load_cases(args.cases),
        _load_records(args.compiler_report, "records") if args.compiler_report else [],
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
