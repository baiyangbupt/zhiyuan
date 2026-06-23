#!/usr/bin/env python3
"""Offline contract for compiler-only pending sink requests.

This is not runtime code. It validates that a CompiledProposal can be converted
into exactly one pending sink request, and that legacy/recovery-shaped payloads
are rejected before reaching service.py sink functions.
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


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _list_str(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value is None:
        return []
    return [str(value)]


def _compiled(case: dict[str, Any]) -> dict[str, Any]:
    value = case.get("compiledProposal")
    return value if isinstance(value, dict) else {}


def _expected(case: dict[str, Any]) -> dict[str, Any]:
    value = case.get("expected")
    return value if isinstance(value, dict) else {}


def _assertions(case: dict[str, Any]) -> dict[str, Any]:
    value = case.get("assert")
    return value if isinstance(value, dict) else {}


def _get_path(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _build_sink_request(compiled: dict[str, Any]) -> dict[str, Any]:
    blocking_reasons: list[str] = []
    compiled_id = str(compiled.get("compiledProposalId") or compiled.get("id") or "").strip()
    if not compiled_id:
        blocking_reasons.append("missing_compiled_proposal_id")

    pending_type = str(compiled.get("pendingType") or "none").strip() or "none"
    execution_payload = _as_dict(compiled.get("executionPayload"))
    execution_kind = str(execution_payload.get("kind") or "").strip()
    intent_payload = _as_dict(compiled.get("intentPayload"))
    display_payload = _as_dict(compiled.get("displayPayload"))
    candidates = _as_list(compiled.get("proposalCandidates"))
    if pending_type == "none":
        return {
            "sinkType": "none",
            "allowed": False,
            "blockingReasons": blocking_reasons + ["no_pending_requested"],
        }

    sink_type = "unsupported"
    action_family = ""
    payload: dict[str, Any] = {}
    if pending_type == "intent_change":
        sink_type = "intent"
        action_family = "apply_selected_intents"
        if execution_kind != "pending_intent_change":
            blocking_reasons.append("intent_pending_requires_pending_intent_change_execution")
        if not intent_payload:
            blocking_reasons.append("intent_pending_requires_intent_payload")
        payload = {
            "compiledProposalId": compiled_id,
            "intentPayload": intent_payload,
            "displayPayload": display_payload,
        }
    elif pending_type == "plan_mutation":
        if execution_kind != "pending_plan_mutation":
            blocking_reasons.append("plan_pending_requires_pending_plan_mutation_execution")
        candidate_types = {
            str(candidate.get("type") or "").strip()
            for candidate in candidates
            if isinstance(candidate, dict)
        }
        if "java_fix_proposal_reference" in candidate_types:
            sink_type = "fix_proposal"
            action_family = "apply_fix_proposal"
            java_refs = [
                candidate for candidate in candidates
                if isinstance(candidate, dict)
                and str(candidate.get("type") or "").strip() == "java_fix_proposal_reference"
            ]
            java_ref = java_refs[0] if java_refs else {}
            source_version_guard = _as_int(
                java_ref.get("sourceVersionGuard") or java_ref.get("source_version_guard")
            )
            if source_version_guard <= 0:
                blocking_reasons.append("fix_proposal_requires_source_version_guard")
            if not _as_list(java_ref.get("actions")) and not bool(java_ref.get("hasActions")):
                blocking_reasons.append("fix_proposal_requires_actions")
            if not _as_dict(java_ref.get("dryRunObservation") or java_ref.get("dryRun")):
                blocking_reasons.append("fix_proposal_requires_dry_run_observation")
            payload = {
                "compiledProposalId": compiled_id,
                "proposalId": str(java_ref.get("proposalId") or java_ref.get("proposal_id") or java_ref.get("id") or ""),
                "sourceVersionGuard": source_version_guard,
                "intentPayload": intent_payload or None,
                "displayPayload": display_payload,
            }
        else:
            sink_type = "plan"
            action_family = str(execution_payload.get("actionFamily") or "").strip()
            action_families = _list_str(execution_payload.get("actionFamilies"))
            if not action_family and action_families:
                action_family = action_families[0]
            if not action_family:
                blocking_reasons.append("plan_pending_requires_action_family")
            plan_candidates = [
                candidate for candidate in candidates
                if isinstance(candidate, dict)
                and str(candidate.get("type") or "").strip() == "plan_confirmation_candidate"
            ]
            if not plan_candidates:
                blocking_reasons.append("plan_sink_requires_plan_confirmation_candidate")
            else:
                plan_candidate = plan_candidates[0]
                candidate_action_family = str(plan_candidate.get("actionFamily") or "").strip()
                if candidate_action_family and action_family and candidate_action_family != action_family:
                    blocking_reasons.append("plan_candidate_action_family_mismatch")
                plan_payload = _as_dict(plan_candidate.get("planPayload"))
                if not plan_payload:
                    blocking_reasons.append("plan_candidate_requires_plan_payload")
                elif str(plan_payload.get("action_family") or plan_payload.get("actionFamily") or "").strip() not in {"", action_family}:
                    blocking_reasons.append("plan_candidate_action_family_mismatch")
                if plan_payload and str(plan_payload.get("stage") or "").strip() != "apply":
                    blocking_reasons.append("plan_candidate_requires_apply_stage")
                requires_confirmation = (
                    plan_payload.get("requires_confirmation")
                    if "requires_confirmation" in plan_payload
                    else plan_payload.get("requiresConfirmation")
                )
                if requires_confirmation is True:
                    blocking_reasons.append("plan_candidate_apply_payload_must_not_require_confirmation")
            payload = {
                "compiledProposalId": compiled_id,
                "executionPayload": execution_payload,
                "intentPayload": intent_payload or None,
                "displayPayload": display_payload,
            }
    else:
        blocking_reasons.append(f"unsupported_pending_type:{pending_type}")

    return {
        "sinkType": sink_type,
        "allowed": not blocking_reasons,
        "actionFamily": action_family,
        "payload": payload,
        "blockingReasons": blocking_reasons,
    }


def _evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    result = _build_sink_request(_compiled(case))
    failures: list[dict[str, Any]] = []
    expected = _expected(case)
    for field in _list_str(_assertions(case).get("exact")):
        actual_value = _get_path(result, field)
        expected_value = _get_path(expected, field)
        if actual_value != expected_value:
            failures.append(
                {
                    "type": "exact",
                    "field": field,
                    "expected": expected_value,
                    "actual": actual_value,
                }
            )
    for value in _list_str(_assertions(case).get("containsBlockingReasons")):
        if value not in result.get("blockingReasons", []):
            failures.append({"type": "missing_blocking_reason", "expected": value})
    return {
        "caseId": case.get("caseId"),
        **result,
        "passed": not failures,
        "failures": failures,
    }


def _bump(group: dict[str, int], key: str) -> None:
    group[key] = group.get(key, 0) + 1


def build_report(cases: list[dict[str, Any]]) -> dict[str, Any]:
    records = [_evaluate_case(case) for case in cases]
    by_sink_type: dict[str, int] = {}
    blocking_reasons: dict[str, int] = {}
    for record in records:
        _bump(by_sink_type, str(record.get("sinkType") or "unknown"))
        for reason in record.get("blockingReasons") or []:
            _bump(blocking_reasons, str(reason))
    total = len(records)
    passed = sum(1 for record in records if record.get("passed"))
    return {
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "passRate": round(passed / total, 4) if total else None,
            "bySinkType": by_sink_type,
            "blockingReasons": blocking_reasons,
        },
        "records": records,
        "failureExamples": [record for record in records if not record.get("passed")][:20],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate compiler-only pending sink contract.")
    parser.add_argument("--cases", required=True, help="contract case JSON")
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
