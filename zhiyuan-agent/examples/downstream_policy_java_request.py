#!/usr/bin/env python3
"""Compile 3.2.0 downstreamPolicy into Java UserGoalFixProposalReq fixtures.

This is an offline contract tool. It does not call backend services, create
pending cards, apply proposals, or mutate state. It defines which
downstreamPolicy parts can enter the existing Java user-goal proposal path and
which parts remain rank-only or adapter gaps.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any


SUPPORTED_SCOPE_TYPES = {"major", "school", "region", "tag", "risk", "program_type"}


def _load_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_cases(path: str) -> list[dict[str, Any]]:
    payload = _load_json(path)
    cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(cases, list):
        raise ValueError("case file must be a JSON array or {'cases': [...]}")
    return [case for case in cases if isinstance(case, dict)]


def _load_records(path: str | None, key: str = "records") -> list[dict[str, Any]]:
    if not path:
        return []
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


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_str(value: Any) -> list[str]:
    result: list[str] = []
    for item in _as_list(value):
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _numeric(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _positive_int(value: Any) -> int:
    number = int(_numeric(value))
    return number if number > 0 else 0


def _get(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data:
            return data.get(key)
    return None


def _get_path(data: Any, path: str) -> Any:
    current = data
    for part in str(path or "").split("."):
        if not part:
            continue
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _scope_type(value: Any, default: str = "major") -> str:
    text = str(value or default).strip().lower()
    aliases = {
        "province": "region",
        "city": "region",
        "area": "region",
        "major_keyword": "major",
        "school_keyword": "school",
        "review_issue": "risk",
        "project_type": "program_type",
        "admission_path": "program_type",
        "admission_type": "program_type",
    }
    return aliases.get(text, text)


def _scope_level(policy: dict[str, Any], scope_type: str) -> str:
    raw = str(policy.get("scopeLevel") or policy.get("scope_level") or "").strip().lower()
    if raw in {"province", "city", "area"}:
        return raw
    scope = str(policy.get("scope") or "").strip()
    if scope_type == "region" and scope in {"南方", "北方", "长三角", "珠三角"}:
        return "area"
    return ""


def _scope_payload(value: str, *, scope_type: str, scope_level: str = "", evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "scopeType": scope_type,
        "entityType": scope_type,
        "name": value,
        "normalizedName": value,
        "rawText": value,
        "resolutionStatus": "resolved",
        "evidence": {"source": "downstreamPolicy", **(evidence or {})},
    }
    if scope_level:
        payload["scopeLevel"] = scope_level
        payload["evidence"]["scopeLevel"] = scope_level
    return payload


def _scopes(values: list[str], *, policy: dict[str, Any], scope_type: str, evidence: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    scope_level = _scope_level(policy, scope_type)
    return [
        _scope_payload(value, scope_type=scope_type, scope_level=scope_level, evidence=evidence)
        for value in values
    ]


def _tuition_cap(policy: dict[str, Any]) -> int:
    selection = _as_dict(policy.get("candidateSelection"))
    for source in (selection, policy, _as_dict(selection.get("tuitionBudget")), _as_dict(policy.get("tuitionBudget"))):
        for key in ("maxTuitionPerYear", "tuitionCap", "maxTuition", "budgetCap", "maxPerYear"):
            value = _positive_int(source.get(key))
            if value:
                return value
    return 0


def _policy_from_case(case: dict[str, Any], compiled_by_case: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], str, str]:
    inline_policy = case.get("downstreamPolicy") if isinstance(case.get("downstreamPolicy"), dict) else {}
    if inline_policy:
        return inline_policy, "inline", str(case.get("compiledCaseId") or case.get("caseId") or "").strip()
    compiled_case_id = str(case.get("compiledCaseId") or case.get("caseId") or "").strip()
    compiled = compiled_by_case.get(compiled_case_id) or {}
    compiled_policy = compiled.get("downstreamPolicy") if isinstance(compiled.get("downstreamPolicy"), dict) else {}
    if compiled_policy:
        return compiled_policy, "compiler", compiled_case_id
    return {}, "missing", compiled_case_id


def _build_request(case: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any] | None:
    selection = _as_dict(policy.get("candidateSelection"))
    scope_type = _scope_type(case.get("scopeType") or policy.get("scopeType") or policy.get("entityType"))
    scope_level = _scope_level(policy, scope_type)
    planning_version = _positive_int(case.get("planningVersion") or case.get("sourceVersionGuard") or 1)
    user_text = str(case.get("userOriginalText") or case.get("prompt") or case.get("caseId") or "").strip()
    only_keep = _list_str(selection.get("onlyKeep"))
    must_cover = _list_str(selection.get("mustCover"))
    hard_exclude = _list_str(selection.get("hardExclude"))
    tuition_cap = _tuition_cap(policy)
    admission_path = str(policy.get("admissionPath") or "").strip()

    if only_keep:
        return {
            "proposalSource": "user_goal",
            "goalType": "only_keep_scope",
            "userOriginalText": user_text,
            "confidence": "high",
            "sourceVersionGuard": planning_version,
            "targetScopes": _scopes(only_keep, policy=policy, scope_type=scope_type),
            "negativeScopes": [],
            "qualityGuards": [],
            "tradeoffGuards": [],
            "context": {"source": "downstream_policy_java_request", "policyStrength": "only_keep"},
        }
    if must_cover:
        return {
            "proposalSource": "user_goal",
            "goalType": "must_include_scope",
            "userOriginalText": user_text,
            "confidence": "high",
            "sourceVersionGuard": planning_version,
            "targetScopes": _scopes(must_cover, policy=policy, scope_type=scope_type),
            "negativeScopes": [],
            "qualityGuards": [],
            "tradeoffGuards": [],
            "context": {"source": "downstream_policy_java_request", "policyStrength": "must_have"},
        }
    if hard_exclude:
        return {
            "proposalSource": "user_goal",
            "goalType": "exclude_scope",
            "userOriginalText": user_text,
            "confidence": "high",
            "sourceVersionGuard": planning_version,
            "targetScopes": [],
            "negativeScopes": _scopes(hard_exclude, policy=policy, scope_type=scope_type),
            "qualityGuards": [],
            "tradeoffGuards": [],
            "context": {"source": "downstream_policy_java_request", "policyStrength": "exclude_hard"},
        }
    if tuition_cap:
        return {
            "proposalSource": "user_goal",
            "goalType": "tuition_budget_scope",
            "userOriginalText": user_text,
            "confidence": "high",
            "sourceVersionGuard": planning_version,
            "targetScopes": [],
            "negativeScopes": [],
            "qualityGuards": [],
            "tradeoffGuards": [],
            "context": {"source": "downstream_policy_java_request", "maxTuitionPerYear": tuition_cap},
        }
    if admission_path:
        return {
            "proposalSource": "user_goal",
            "goalType": "only_keep_scope",
            "userOriginalText": user_text,
            "confidence": "medium",
            "sourceVersionGuard": planning_version,
            "targetScopes": _scopes(
                [admission_path],
                policy=policy,
                scope_type="program_type",
                evidence={"admissionPath": admission_path},
            ),
            "negativeScopes": [],
            "qualityGuards": [],
            "tradeoffGuards": [],
            "context": {
                "source": "downstream_policy_java_request",
                "policyStrength": "admission_path",
                "admissionPath": admission_path,
                "mappingRisk": "program_type_text_match_only",
            },
        }
    return None


def _adapter_gaps(case: dict[str, Any], policy: dict[str, Any], request: dict[str, Any] | None) -> list[str]:
    selection = _as_dict(policy.get("candidateSelection"))
    gaps: list[str] = []
    if not policy:
        return ["missing_downstream_policy"]
    scope_type = _scope_type(case.get("scopeType") or policy.get("scopeType") or policy.get("entityType"))
    if scope_type not in SUPPORTED_SCOPE_TYPES:
        gaps.append("unsupported_scope_type:" + scope_type)
    rank_only_values: list[str] = []
    for boost in _as_list(selection.get("rankBoost")):
        if not isinstance(boost, dict):
            continue
        if _list_str(boost.get("values")):
            strength = str(boost.get("strength") or "rank_boost").strip()
            rank_only_values.append(strength or "rank_boost")
    if rank_only_values and request is None:
        gaps.append("rank_only_policy:" + ",".join(dict.fromkeys(rank_only_values)))
    if _list_str(selection.get("softAvoid")) and request is None:
        gaps.append("soft_avoid_rank_only")
    if str(policy.get("admissionPath") or "").strip() and request is not None:
        context = _as_dict(request.get("context"))
        if context.get("mappingRisk"):
            gaps.append(str(context.get("mappingRisk")))
    if request is None and not gaps:
        gaps.append("no_java_user_goal_strategy")
    return gaps


def _request_ready(request: dict[str, Any] | None, gaps: list[str]) -> bool:
    if request is None:
        return False
    blocking_prefixes = ("unsupported_scope_type:",)
    return not any(gap.startswith(blocking_prefixes) for gap in gaps)


def _assert_exact(case: dict[str, Any], record: dict[str, Any]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    expected = _as_dict(case.get("expected"))
    for field in _as_list((_as_dict(case.get("assert"))).get("exact")):
        expected_value = _get_path(expected, str(field))
        actual_value = _get_path(record, str(field))
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


def _compile_case(case: dict[str, Any], compiled_by_case: dict[str, dict[str, Any]]) -> dict[str, Any]:
    case_id = str(case.get("caseId") or "").strip()
    policy, policy_source, compiled_case_id = _policy_from_case(case, compiled_by_case)
    request = _build_request(case, policy) if policy else None
    gaps = _adapter_gaps(case, policy, request)
    record = {
        "caseId": case_id,
        "compiledCaseId": compiled_case_id,
        "policySource": policy_source,
        "requestReady": _request_ready(request, gaps),
        "javaRequest": request,
        "adapterGaps": gaps,
    }
    failures = _assert_exact(case, record)
    return {**record, "passed": not failures, "failures": failures}


def build_report(cases: list[dict[str, Any]], compiler_records: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    compiled_by_case = _case_index(compiler_records or [])
    records = [_compile_case(case, compiled_by_case) for case in cases]
    passed = sum(1 for record in records if record.get("passed"))
    gap_counts: dict[str, int] = {}
    ready_count = 0
    for record in records:
        if record.get("requestReady"):
            ready_count += 1
        for gap in record.get("adapterGaps") or []:
            gap_counts[str(gap)] = gap_counts.get(str(gap), 0) + 1
    return {
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "summary": {
            "total": len(records),
            "passed": passed,
            "failed": len(records) - passed,
            "passRate": round(passed / len(records), 4) if records else None,
            "requestReady": ready_count,
            "requestNotReady": len(records) - ready_count,
            "adapterGapCounts": gap_counts,
        },
        "records": records,
        "failureExamples": [record for record in records if not record.get("passed")][:20],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile downstreamPolicy into Java user-goal request fixtures.")
    parser.add_argument("--cases", required=True, help="request mapping cases JSON")
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
