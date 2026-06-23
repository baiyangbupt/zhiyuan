#!/usr/bin/env python3
"""Readonly shadow diff for old runtime observations vs 3.2.0 compiler output.

This tool is offline by default. It does not start WebSocket services, create
pending cards, apply mutations, or write backend state. It only compares
recorded old-path observations with deterministic CompiledProposal records.
"""

from __future__ import annotations

import argparse
import importlib.util
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


def _load_records(path: str, key: str) -> list[dict[str, Any]]:
    payload = _load_json(path)
    records = payload.get(key) if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ValueError(f"record file must be a JSON array or {{'{key}': [...]}}")
    return [record for record in records if isinstance(record, dict)]


def _load_compiler_module() -> Any:
    module_path = Path(__file__).resolve().with_name("proposal_compiler_golden.py")
    spec = importlib.util.spec_from_file_location("proposal_compiler_golden", module_path)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot load compiler module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _compiler_records(cases: list[dict[str, Any]], compiler_report: str | None = None) -> list[dict[str, Any]]:
    if compiler_report:
        return _load_records(compiler_report, "records")
    compiler = _load_compiler_module()
    report = compiler.build_report(cases)
    return [record for record in report.get("records", []) if isinstance(record, dict)]


def _case_index(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        case_id = str(item.get("caseId") or "").strip()
        if case_id:
            result[case_id] = item
    return result


def _runtime_payload(observation: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(observation, dict):
        return {}
    for key in ("runtime", "observed", "actual"):
        value = observation.get(key)
        if isinstance(value, dict):
            return value
    return observation


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        raw_values = value
    else:
        raw_values = [value]
    result: list[str] = []
    for item in raw_values:
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


def _choice_values(value: Any) -> set[str]:
    text = str(value or "").strip()
    if not text:
        return {""}
    if "_or_" in text:
        return {part for part in text.split("_or_") if part}
    return {text}


def _matches_expected(expected: Any, actual: Any) -> bool:
    expected_text = str(expected or "").strip()
    actual_text = str(actual or "").strip()
    if expected_text == actual_text:
        return True
    expected_values = _choice_values(expected)
    if actual_text in expected_values:
        return True
    if expected_values == {"none", "plan_mutation"} and actual_text == "none_or_plan_mutation":
        return True
    return False


def _pending_from_cards(runtime: dict[str, Any]) -> str:
    cards = runtime.get("pendingCards")
    if not isinstance(cards, list):
        cards = runtime.get("pendingConfirmationCards")
    if not isinstance(cards, list):
        return ""
    normalized_cards = [card for card in cards if isinstance(card, dict)]
    if len(normalized_cards) > 1:
        return "multiple"
    if not normalized_cards:
        return "none"
    kind = str(normalized_cards[0].get("kind") or "").strip()
    if kind in {"intent_change", "plan_mutation"}:
        return kind
    return kind or "unknown_pending"


def _observed_pending_type(runtime: dict[str, Any]) -> str:
    value = str(runtime.get("pendingType") or "").strip()
    if value:
        return value
    from_cards = _pending_from_cards(runtime)
    if from_cards:
        return from_cards
    if runtime.get("createdPending") is True:
        return "unknown_pending"
    return "none"


def _observed_side_effect(runtime: dict[str, Any], pending_type: str) -> str:
    value = str(runtime.get("sideEffect") or "").strip()
    if value:
        return value
    if pending_type == "intent_change":
        return "intent_pending"
    if pending_type == "plan_mutation":
        return "plan_preview"
    if pending_type == "multiple":
        return "multiple_pending"
    if runtime.get("applyExistingPending") is True:
        return "apply_existing_pending"
    return "readonly"


def _observed_execution_kind(runtime: dict[str, Any], pending_type: str) -> str:
    value = str(_get_path(runtime, "executionPayload.kind") or runtime.get("executionKind") or "").strip()
    if value:
        return value
    action_family = str(runtime.get("actionFamily") or "").strip()
    if action_family == "apply_fix_proposal":
        return "pending_plan_mutation"
    if pending_type == "intent_change":
        return "pending_intent_change"
    if pending_type == "plan_mutation":
        return "pending_plan_mutation"
    return ""


def _observed_presentation(runtime: dict[str, Any], pending_type: str) -> str:
    value = str(
        _get_path(runtime, "displayPayload.presentation")
        or runtime.get("displayPresentation")
        or runtime.get("presentation")
        or ""
    ).strip()
    if value:
        return value
    if pending_type in {"intent_change", "plan_mutation"}:
        return "confirmation_card"
    if pending_type == "multiple":
        return "multiple_cards"
    return "readonly_answer"


def _normalize_runtime(observation: dict[str, Any] | None) -> dict[str, Any]:
    runtime = _runtime_payload(observation)
    pending_type = _observed_pending_type(runtime)
    post_apply_evidence_plan = runtime.get("postApplyEvidencePlan")
    if not isinstance(post_apply_evidence_plan, dict):
        post_apply_evidence_plan = _get_path(runtime, "turnObservability.postApplyEvidencePlan")
    if not isinstance(post_apply_evidence_plan, dict):
        post_apply_evidence_plan = {}
    return {
        "actualSource": (observation or {}).get("actualSource") or (observation or {}).get("source") or "observed",
        "sideEffect": _observed_side_effect(runtime, pending_type),
        "outputType": str(runtime.get("outputType") or "").strip(),
        "pendingType": pending_type,
        "executionKind": _observed_execution_kind(runtime, pending_type),
        "presentation": _observed_presentation(runtime, pending_type),
        "replyFocus": _as_list(
            runtime.get("replyFocus")
            or _get_path(runtime, "replyPlan.focus")
            or runtime.get("targetIssue")
        ),
        "workspaceRefreshTargets": _as_list(runtime.get("workspaceRefreshTargets")),
        "postApplyEvidencePlan": post_apply_evidence_plan,
        "shadowSideEffectViolation": bool(
            runtime.get("shadowWritesState")
            or runtime.get("shadowCreatedPending")
            or runtime.get("shadowApplied")
        ),
        "raw": runtime,
    }


def _normalize_compiled(record: dict[str, Any]) -> dict[str, Any]:
    evidence_contract = record.get("evidenceContract")
    if not isinstance(evidence_contract, dict):
        evidence_contract = {}
    return {
        "sideEffect": str(record.get("sideEffect") or "").strip(),
        "outputType": str(record.get("outputType") or "").strip(),
        "pendingType": str(record.get("pendingType") or "none").strip() or "none",
        "executionKind": str(_get_path(record, "executionPayload.kind") or "").strip(),
        "presentation": str(_get_path(record, "displayPayload.presentation") or "").strip(),
        "replyFocus": _as_list(_get_path(record, "replyPlan.focus")),
        "workspaceRefreshTargets": _as_list(record.get("workspaceRefreshTargets")),
        "evidenceContract": evidence_contract,
        "blockingReasons": record.get("blockingReasons") or [],
        "raw": record,
    }


def _add_diff(diffs: list[dict[str, Any]], severity: str, diff_type: str, field: str, expected: Any, actual: Any) -> None:
    diffs.append(
        {
            "severity": severity,
            "type": diff_type,
            "field": field,
            "expected": expected,
            "actual": actual,
        }
    )


def _compare_case(
    case: dict[str, Any],
    compiled_record: dict[str, Any] | None,
    observation: dict[str, Any] | None,
) -> dict[str, Any]:
    case_id = str(case.get("caseId") or "").strip()
    diffs: list[dict[str, Any]] = []
    if compiled_record is None:
        _add_diff(diffs, "blocking", "missing_compiled_record", "compiled", "record", None)
        compiled = {}
    else:
        compiled = _normalize_compiled(compiled_record)
    if observation is None:
        _add_diff(diffs, "info", "missing_observation", "observation", "recorded_runtime", None)
        observed = {}
    else:
        observed = _normalize_runtime(observation)

    if observed.get("shadowSideEffectViolation"):
        _add_diff(diffs, "blocking", "shadow_side_effect_violation", "shadow", "readonly", "state_write_or_apply")

    compiled_pending = compiled.get("pendingType") or "none"
    observed_pending = observed.get("pendingType") or "none"
    if observed and observed_pending == "multiple":
        _add_diff(diffs, "blocking", "multiple_pending_cards", "pendingType", compiled_pending, observed_pending)
    elif observed and not _matches_expected(compiled_pending, observed_pending):
        compiled_creates_pending = compiled_pending not in {"none", "unchanged", "unchanged_existing_pending"}
        observed_creates_pending = observed_pending not in {"none", "unchanged", "unchanged_existing_pending"}
        if not compiled_creates_pending and observed_creates_pending:
            diff_type = "unexpected_pending_creation"
            severity = "blocking"
        elif compiled_creates_pending and not observed_creates_pending:
            diff_type = "missing_pending"
            severity = "blocking"
        else:
            diff_type = "pending_type_mismatch"
            severity = "major"
        _add_diff(diffs, severity, diff_type, "pendingType", compiled_pending, observed_pending)

    for field in ("sideEffect", "outputType"):
        expected_value = compiled.get(field)
        actual_value = observed.get(field)
        if observed and expected_value and actual_value and not _matches_expected(expected_value, actual_value):
            _add_diff(diffs, "major", f"{field}_mismatch", field, expected_value, actual_value)

    expected_kind = compiled.get("executionKind")
    actual_kind = observed.get("executionKind")
    if observed and expected_kind and actual_kind and expected_kind != actual_kind:
        _add_diff(diffs, "major", "execution_kind_mismatch", "executionKind", expected_kind, actual_kind)

    expected_presentation = compiled.get("presentation")
    actual_presentation = observed.get("presentation")
    if observed and expected_presentation and actual_presentation and expected_presentation != actual_presentation:
        _add_diff(diffs, "major", "presentation_mismatch", "presentation", expected_presentation, actual_presentation)

    expected_focus = set(compiled.get("replyFocus") or [])
    actual_focus = set(observed.get("replyFocus") or [])
    if observed and expected_focus and actual_focus and not expected_focus.issubset(actual_focus):
        _add_diff(diffs, "major", "reply_focus_missing", "replyFocus", sorted(expected_focus), sorted(actual_focus))

    expected_targets = set(compiled.get("workspaceRefreshTargets") or [])
    actual_targets = set(observed.get("workspaceRefreshTargets") or [])
    if observed and expected_targets != actual_targets:
        if expected_targets and not actual_targets:
            diff_type = "missing_workspace_refresh"
        elif actual_targets and not expected_targets:
            diff_type = "unexpected_workspace_refresh"
        else:
            diff_type = "workspace_refresh_mismatch"
        _add_diff(diffs, "major", diff_type, "workspaceRefreshTargets", sorted(expected_targets), sorted(actual_targets))

    expected_evidence = compiled.get("evidenceContract") if isinstance(compiled.get("evidenceContract"), dict) else {}
    observed_evidence = (
        observed.get("postApplyEvidencePlan") if isinstance(observed.get("postApplyEvidencePlan"), dict) else {}
    )
    expects_apply_then_readonly = compiled.get("executionKind") == "apply_existing_pending_then_readonly"
    observed_apply_then_readonly = observed.get("executionKind") == "apply_existing_pending_then_readonly"
    if observed and expects_apply_then_readonly and not observed_evidence:
        _add_diff(
            diffs,
            "major",
            "missing_post_apply_evidence_plan",
            "postApplyEvidencePlan",
            "required",
            None,
        )
    if observed and observed_apply_then_readonly and observed_evidence:
        expected_inputs = set(_as_list(expected_evidence.get("requiredInputs")))
        actual_inputs = set(_as_list(observed_evidence.get("requiredInputs")))
        if expected_inputs and not expected_inputs.issubset(actual_inputs):
            _add_diff(
                diffs,
                "major",
                "post_apply_required_inputs_missing",
                "postApplyEvidencePlan.requiredInputs",
                sorted(expected_inputs),
                sorted(actual_inputs),
            )
        expected_steps = set(_as_list(expected_evidence.get("steps")))
        observed_steps = observed_evidence.get("steps")
        actual_steps: set[str] = set()
        if isinstance(observed_steps, list):
            for step in observed_steps:
                if isinstance(step, dict):
                    text = str(step.get("step") or step.get("name") or "").strip()
                else:
                    text = str(step or "").strip()
                if text:
                    actual_steps.add(text)
        if expected_steps and not expected_steps.intersection(actual_steps):
            _add_diff(
                diffs,
                "major",
                "post_apply_evidence_steps_mismatch",
                "postApplyEvidencePlan.steps",
                sorted(expected_steps),
                sorted(actual_steps),
            )

    max_severity = "none"
    for severity in ("blocking", "major", "minor", "info"):
        if any(diff["severity"] == severity for diff in diffs):
            max_severity = severity
            break

    return {
        "caseId": case_id,
        "source": case.get("source"),
        "priority": case.get("priority"),
        "tags": case.get("tags") or [],
        "observedSource": observed.get("actualSource") if observed else None,
        "maxSeverity": max_severity,
        "diffCount": len(diffs),
        "compiled": compiled,
        "observed": observed,
        "diffs": diffs,
    }


def _bump(counter: dict[str, int], key: Any) -> None:
    text = str(key or "").strip()
    if text:
        counter[text] = counter.get(text, 0) + 1


def build_report(
    cases: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    compiler_records: list[dict[str, Any]],
) -> dict[str, Any]:
    observed_by_case = _case_index(observations)
    compiled_by_case = _case_index(compiler_records)
    records = [
        _compare_case(case, compiled_by_case.get(str(case.get("caseId") or "")), observed_by_case.get(str(case.get("caseId") or "")))
        for case in cases
    ]
    by_severity = {"blocking": 0, "major": 0, "minor": 0, "info": 0, "none": 0}
    by_diff_type: dict[str, int] = {}
    by_case_tag: dict[str, dict[str, int]] = {}
    for record in records:
        _bump(by_severity, record.get("maxSeverity") or "none")
        for diff in record.get("diffs") or []:
            _bump(by_diff_type, diff.get("type"))
        has_blocking_or_major = record.get("maxSeverity") in {"blocking", "major"}
        for tag in record.get("tags") or []:
            tag_text = str(tag or "").strip()
            if not tag_text:
                continue
            by_case_tag.setdefault(tag_text, {"total": 0, "blockingOrMajor": 0})
            by_case_tag[tag_text]["total"] += 1
            if has_blocking_or_major:
                by_case_tag[tag_text]["blockingOrMajor"] += 1
    total = len(records)
    clean = sum(1 for record in records if record.get("maxSeverity") == "none")
    return {
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "summary": {
            "total": total,
            "observed": sum(1 for record in records if record.get("observedSource")),
            "clean": clean,
            "cleanRate": round(clean / total, 4) if total else None,
            "blocking": by_severity["blocking"],
            "major": by_severity["major"],
            "minor": by_severity["minor"],
            "info": by_severity["info"],
            "byDiffType": by_diff_type,
            "byTag": by_case_tag,
        },
        "records": records,
        "blockingExamples": [record for record in records if record.get("maxSeverity") == "blocking"][:20],
        "majorExamples": [record for record in records if record.get("maxSeverity") == "major"][:20],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Readonly shadow diff between old runtime observations and compiler output.")
    parser.add_argument("--cases", required=True, help="profile golden case JSON")
    parser.add_argument("--observations", required=True, help="old-path observations JSON")
    parser.add_argument("--compiler-report", help="optional proposal_compiler_golden report")
    parser.add_argument("--output", help="write JSON report")
    args = parser.parse_args()

    cases = _load_cases(args.cases)
    observations = _load_records(args.observations, "observations")
    report = build_report(
        cases,
        observations,
        _compiler_records(cases, compiler_report=args.compiler_report),
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
