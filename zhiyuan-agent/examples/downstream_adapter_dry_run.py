#!/usr/bin/env python3
"""Normalize Java fix-proposal dry-run responses into 3.2.0 downstream observations.

This is an offline adapter/profile tool. It does not call backend services,
create pending cards, apply proposals, or mutate planning state. It consumes
recorded/fixture Java FixProposal responses and reports whether the response
already carries the fields needed by downstreamPolicy replay and runtime
dry-run contracts.
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


def _int(value: Any) -> int:
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


def _proposal_state(data: dict[str, Any]) -> dict[str, Any]:
    if isinstance(data.get("data"), dict):
        return data.get("data") or {}
    return data


def _proposal_id(proposal: dict[str, Any]) -> str:
    return str(_get(proposal, "proposalId", "proposal_id") or "").strip()


def _proposal_status(proposal: dict[str, Any]) -> str:
    return str(_get(proposal, "status") or "").strip()


def _proposal_strategy(proposal: dict[str, Any]) -> str:
    return str(_get(proposal, "strategy") or "").strip()


def _dry_run(proposal: dict[str, Any]) -> dict[str, Any]:
    return _as_dict(_get(proposal, "dryRunResult", "dry_run_result", "dry_run"))


def _shortages(proposal: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in _as_list(_get(proposal, "candidateShortages", "candidate_shortages")) if isinstance(item, dict)]


def _actions(proposal: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in _as_list(_get(proposal, "actions")) if isinstance(item, dict)]


def _action_type(action: dict[str, Any]) -> str:
    return str(_get(action, "actionType", "action_type") or "").strip()


def _ids(action: dict[str, Any], *keys: str) -> list[str]:
    for key in keys:
        values = _list_str(action.get(key))
        if values:
            return values
    return []


def _replacement_pairs(action: dict[str, Any]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for pair in _as_list(_get(action, "replacementPairs", "replacement_pairs")):
        if not isinstance(pair, dict):
            continue
        normalized = {
            "fromUnitId": str(_get(pair, "fromUnitId", "from_unit_id") or "").strip(),
            "fromVolunteerId": str(_get(pair, "fromVolunteerId", "from_volunteer_id") or "").strip(),
            "toUnitId": str(_get(pair, "toUnitId", "to_unit_id") or "").strip(),
            "toVolunteerId": str(_get(pair, "toVolunteerId", "to_volunteer_id") or "").strip(),
        }
        if any(normalized.values()):
            result.append(normalized)
    return result


def _all_replacement_pairs(proposal: dict[str, Any]) -> list[dict[str, str]]:
    pairs: list[dict[str, str]] = []
    for action in _actions(proposal):
        pairs.extend(_replacement_pairs(action))
    return pairs


def _remove_ids(proposal: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for action in _actions(proposal):
        for item in _ids(action, "removeVolunteerIds", "remove_volunteer_ids", "volunteerIds", "volunteer_ids"):
            if item not in result:
                result.append(item)
    return result


def _candidate_ids(proposal: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for action in _actions(proposal):
        for item in _ids(action, "candidateVolunteerIds", "candidate_volunteer_ids"):
            if item not in result:
                result.append(item)
        for pair in _replacement_pairs(action):
            value = pair.get("toVolunteerId")
            if value and value not in result:
                result.append(value)
    return result


def _capacity_from(proposal: dict[str, Any]) -> dict[str, Any]:
    dry_run = _dry_run(proposal)
    shortages = _shortages(proposal)
    selected_count = _int(_get(dry_run, "addVolunteerCount", "add_volunteer_count"))
    removed_count = _int(_get(dry_run, "removeVolunteerCount", "remove_volunteer_count"))
    shortage_count = 0
    available_count = 0
    no_result_reason = None
    for shortage in shortages:
        shortage_count = max(shortage_count, _int(_get(shortage, "shortageCount", "shortage_count")))
        available_count = max(available_count, _int(_get(shortage, "availableCount", "available_count")))
        reason = str(_get(shortage, "reasonCode", "reason_code") or "").strip()
        if reason and not no_result_reason:
            no_result_reason = reason

    status = _proposal_status(proposal)
    blocking_codes = _list_str(_get(proposal, "blockingReasonCodes", "blocking_reason_codes"))
    if status == "blocked":
        capacity_status = "no_result" if selected_count == 0 else "insufficient_candidates"
        no_result_reason = no_result_reason or (blocking_codes[0] if blocking_codes else "blocked")
    elif shortage_count > 0:
        capacity_status = "insufficient_candidates"
        no_result_reason = no_result_reason or "capacity_insufficient_after_filters"
    elif selected_count > 0 or removed_count > 0:
        capacity_status = "satisfied"
    elif status == "info":
        capacity_status = "satisfied"
    else:
        capacity_status = "not_reported"

    return {
        "capacityStatus": capacity_status,
        "noResultReason": no_result_reason,
        "shortageCount": shortage_count,
        "availableCount": available_count,
        "selectedCount": selected_count,
        "removedCount": removed_count,
    }


def _must_cover_from(proposal: dict[str, Any]) -> dict[str, Any]:
    strategy = _proposal_strategy(proposal)
    target_values = _list_str(_get(proposal, "mustCoverValues", "must_cover_values", "targetValues", "target_values"))
    missing_values = _list_str(_get(proposal, "missingMustCover", "missing_must_cover"))
    if strategy == "must_include_scope":
        if _proposal_status(proposal) == "blocked":
            missing_values = missing_values or target_values or ["must_include_scope"]
        elif _int(_get(_dry_run(proposal), "addVolunteerCount", "add_volunteer_count")) > 0:
            target_values = target_values or ["must_include_scope"]
    return {
        "requiredMustCover": target_values,
        "missingMustCover": missing_values,
        "mustCoverSatisfied": not missing_values,
    }


def _proposal_observation(proposal: dict[str, Any]) -> dict[str, Any]:
    pairs = _all_replacement_pairs(proposal)
    replacement_ids = [pair.get("fromVolunteerId") for pair in pairs if pair.get("fromVolunteerId")]
    if not replacement_ids:
        replacement_ids = _remove_ids(proposal)
    candidate_ids = _candidate_ids(proposal)
    blocking_codes = _list_str(_get(proposal, "blockingReasonCodes", "blocking_reason_codes"))
    warnings = _list_str(_get(_dry_run(proposal), "warnings"))
    contract_gaps: list[str] = []
    if _proposal_status(proposal) in {"ready", "blocked"} and not _dry_run(proposal):
        contract_gaps.append("missing_dry_run_result")
    if _proposal_status(proposal) == "blocked" and not (blocking_codes or _shortages(proposal)):
        contract_gaps.append("blocked_without_reason_or_shortage")
    if _proposal_status(proposal) == "ready" and not (_actions(proposal) or candidate_ids or replacement_ids):
        contract_gaps.append("ready_without_actions")
    observation = {
        "proposalId": _proposal_id(proposal),
        "proposalSource": str(_get(proposal, "proposalSource", "proposal_source") or "").strip(),
        "status": _proposal_status(proposal),
        "strategy": _proposal_strategy(proposal),
        "requiresConfirmation": bool(_get(proposal, "requiresConfirmation", "requires_confirmation")),
        "replacementCandidateIds": replacement_ids,
        "candidateVolunteerIds": candidate_ids,
        "replacementPairs": pairs,
        "blockingReasonCodes": blocking_codes,
        "warnings": warnings,
        "contractGaps": contract_gaps,
        **_capacity_from(proposal),
        **_must_cover_from(proposal),
    }
    return observation


def _assert_exact(case: dict[str, Any], report: dict[str, Any]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    expected = _as_dict(case.get("expected"))
    for field in _as_list((_as_dict(case.get("assert"))).get("exact")):
        actual_value = _get_path(report, str(field))
        expected_value = _get_path(expected, str(field))
        if actual_value != expected_value:
            failures.append(
                {
                    "type": "exact",
                    "field": str(field),
                    "expected": expected_value,
                    "actual": actual_value,
                }
            )
    return failures


def _adapt_case(case: dict[str, Any]) -> dict[str, Any]:
    case_id = str(case.get("caseId") or "").strip()
    state = _proposal_state(_as_dict(case.get("fixProposalResponse") or case.get("proposalState")))
    proposals = [item for item in _as_list(state.get("proposals")) if isinstance(item, dict)]
    observations = [_proposal_observation(proposal) for proposal in proposals]
    status_counts: dict[str, int] = {}
    capacity_statuses: dict[str, int] = {}
    contract_gap_counts: dict[str, int] = {}
    for item in observations:
        status = str(item.get("status") or "").strip()
        capacity = str(item.get("capacityStatus") or "").strip()
        if status:
            status_counts[status] = status_counts.get(status, 0) + 1
        if capacity:
            capacity_statuses[capacity] = capacity_statuses.get(capacity, 0) + 1
        for gap in item.get("contractGaps") or []:
            contract_gap_counts[gap] = contract_gap_counts.get(gap, 0) + 1
    report = {
        "caseId": case_id,
        "proposalCount": len(observations),
        "statusCounts": status_counts,
        "capacityStatuses": capacity_statuses,
        "contractGapCounts": contract_gap_counts,
        "observations": observations,
    }
    failures = _assert_exact(case, report)
    return {**report, "passed": not failures, "failures": failures}


def build_report(cases: list[dict[str, Any]]) -> dict[str, Any]:
    records = [_adapt_case(case) for case in cases]
    passed = sum(1 for record in records if record.get("passed"))
    contract_gap_counts: dict[str, int] = {}
    capacity_statuses: dict[str, int] = {}
    for record in records:
        for key, value in _as_dict(record.get("contractGapCounts")).items():
            contract_gap_counts[str(key)] = contract_gap_counts.get(str(key), 0) + int(value or 0)
        for key, value in _as_dict(record.get("capacityStatuses")).items():
            capacity_statuses[str(key)] = capacity_statuses.get(str(key), 0) + int(value or 0)
    return {
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "summary": {
            "total": len(records),
            "passed": passed,
            "failed": len(records) - passed,
            "passRate": round(passed / len(records), 4) if records else None,
            "capacityStatuses": capacity_statuses,
            "contractGapCounts": contract_gap_counts,
        },
        "records": records,
        "failureExamples": [record for record in records if not record.get("passed")][:20],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize Java fix-proposal dry-run fixtures.")
    parser.add_argument("--cases", required=True, help="adapter fixture JSON")
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
