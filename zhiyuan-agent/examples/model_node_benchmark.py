#!/usr/bin/env python3
"""Evaluate model-dependent node outputs against expected structured results.

This runner is offline by default. It does not start WebSocket services or
mutate backend state. With --actual-source live-node, it directly calls selected
model-node functions and records field-level quality, provider environment
exclusions, latency, and repeat-run stability.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from dataclasses import fields
from pathlib import Path
from typing import Any


def _load_cases(path: str) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        cases = payload.get("cases")
    else:
        cases = payload
    if not isinstance(cases, list):
        raise ValueError("case file must be a JSON array or {'cases': [...]}")
    return [case for case in cases if isinstance(case, dict)]


def _filter_cases_by_nodes(cases: list[dict[str, Any]], nodes: str | None) -> list[dict[str, Any]]:
    if not nodes:
        return cases
    allowed = {
        item.strip()
        for item in str(nodes).split(",")
        if item.strip()
    }
    if not allowed:
        return cases
    return [case for case in cases if str(case.get("node") or "").strip() in allowed]


def _get_path(data: Any, path: str) -> Any:
    current = data
    for part in str(path or "").split("."):
        if not part:
            continue
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _has_path(data: Any, path: str) -> bool:
    current = data
    for part in str(path or "").split("."):
        if not part:
            continue
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


def _normalize_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value).strip()


def _structural_match(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        for key, expected_value in expected.items():
            if key not in actual or not _structural_match(actual[key], expected_value):
                return False
        return True
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return False
        return all(_contains_value(actual, expected_item) for expected_item in expected)
    return _normalize_scalar(actual) == _normalize_scalar(expected)


def _contains_value(actual: Any, expected: Any) -> bool:
    if isinstance(actual, (list, tuple, set)):
        return any(_structural_match(item, expected) for item in actual)
    return _structural_match(actual, expected)


def _normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        raw_values = value
    else:
        raw_values = [value]
    result: list[str] = []
    for item in raw_values:
        text = _normalize_scalar(item)
        if text and text not in result:
            result.append(text)
    return result


def _model_to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dumped if isinstance(dumped, dict) else {}
    if hasattr(value, "dict"):
        dumped = value.dict()
        return dumped if isinstance(dumped, dict) else {}
    return {}


def _assert_exact(case: dict[str, Any], expected: dict[str, Any], actual: dict[str, Any]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    exact_fields = ((case.get("assert") or {}).get("exact") or [])
    for field in exact_fields:
        expected_value = _get_path(expected, str(field))
        actual_value = _get_path(actual, str(field))
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


def _assert_contains(case: dict[str, Any], actual: dict[str, Any]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    contains = ((case.get("assert") or {}).get("contains") or {})
    if not isinstance(contains, dict):
        return failures
    for field, expected_values in contains.items():
        actual_value = _get_path(actual, str(field))
        expected_items = expected_values if isinstance(expected_values, list) else [expected_values]
        missing = [
            value
            for value in expected_items
            if not _contains_value(actual_value, value)
        ]
        if missing:
            failures.append(
                {
                    "type": "contains",
                    "field": str(field),
                    "missing": missing,
                    "actual": actual_value,
                }
            )
    return failures


def _assert_not_contains(case: dict[str, Any], actual: dict[str, Any]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    not_contains = ((case.get("assert") or {}).get("notContains") or {})
    if not isinstance(not_contains, dict):
        return failures
    for field, forbidden_values in not_contains.items():
        actual_value = _get_path(actual, str(field))
        forbidden_items = forbidden_values if isinstance(forbidden_values, list) else [forbidden_values]
        found = [
            value
            for value in forbidden_items
            if _contains_value(actual_value, value)
        ]
        if found:
            failures.append(
                {
                    "type": "notContains",
                    "field": str(field),
                    "forbiddenFound": found,
                    "actual": actual_value,
                }
            )
    return failures


def _asserted_fields(case: dict[str, Any]) -> list[str]:
    assertion = case.get("assert") if isinstance(case.get("assert"), dict) else {}
    fields_to_check: list[str] = []
    for field in assertion.get("exact") or []:
        text = str(field or "").strip()
        if text and text not in fields_to_check:
            fields_to_check.append(text)
    values = assertion.get("contains")
    if isinstance(values, dict):
        for field in values:
            text = str(field or "").strip()
            if text and text not in fields_to_check:
                fields_to_check.append(text)
    return fields_to_check


def _schema_gaps(case: dict[str, Any], expected: dict[str, Any], actual: dict[str, Any]) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    for field in _asserted_fields(case):
        if _has_path(expected, field) and not _has_path(actual, field):
            gaps.append({"field": field, "reason": "missing_profile_field"})
    return gaps


_LEGACY_FIELD_REPLACEMENTS = {
    "constraintIntentType": (
        "preferenceStrength",
        "preferenceScope",
        "entityPolaritySpans",
        "admissionPath",
    ),
}


def _legacy_only_fields(case: dict[str, Any], raw_actual: dict[str, Any], actual: dict[str, Any]) -> list[dict[str, str]]:
    asserted = _asserted_fields(case)
    result: list[dict[str, str]] = []
    for legacy_field, replacement_roots in _LEGACY_FIELD_REPLACEMENTS.items():
        if legacy_field not in raw_actual:
            continue
        missing_replacements = [
            field
            for field in asserted
            if any(field == root or field.startswith(f"{root}.") for root in replacement_roots)
            and not _has_path(actual, field)
        ]
        for field in missing_replacements:
            result.append(
                {
                    "legacyField": legacy_field,
                    "missingField": field,
                    "reason": "legacy_field_does_not_satisfy_3_2_schema",
                }
            )
    return result


def _normalize_profile_actual(case: dict[str, Any], raw_actual: dict[str, Any]) -> dict[str, Any]:
    """Return a 3.2.0 profile view without inventing unsupported fields."""
    profile = dict(raw_actual)
    constraint_type = raw_actual.get("constraintIntentType")
    if constraint_type is not None:
        legacy = dict(profile.get("legacy") or {})
        legacy["constraintIntentType"] = constraint_type
        profile["legacy"] = legacy
    return profile


def _evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
    raw_actual = case.get("actual") if isinstance(case.get("actual"), dict) else {}
    actual = _normalize_profile_actual(case, raw_actual)
    failures: list[dict[str, Any]] = []
    live_error = case.get("liveError") if isinstance(case.get("liveError"), dict) else None
    actual_source = case.get("actualSource") or "fixture"
    quality_excluded = actual_source == "provider_env"
    schema_gaps = [] if quality_excluded else _schema_gaps(case, expected, actual)
    legacy_only_fields = [] if quality_excluded else _legacy_only_fields(case, raw_actual, actual)
    if quality_excluded:
        failures = []
    elif live_error:
        failures.append(
            {
                "type": "live_node_error",
                "field": live_error.get("type") or "live_node_error",
                "message": live_error.get("message") or "",
            }
        )
    elif not actual:
        failures.append({"type": "missing_actual", "field": "", "expected": expected, "actual": None})
    else:
        failures.extend(_assert_exact(case, expected, actual))
        failures.extend(_assert_contains(case, actual))
        failures.extend(_assert_not_contains(case, actual))
    latency_ms = case.get("latencyMs")
    return {
        "caseId": case.get("caseId"),
        "baseCaseId": case.get("baseCaseId"),
        "repeatIndex": case.get("repeatIndex"),
        "node": case.get("node"),
        "source": case.get("source"),
        "priority": case.get("priority"),
        "actualSource": actual_source,
        "provider": case.get("provider"),
        "model": case.get("model"),
        "latencyMs": latency_ms if isinstance(latency_ms, int) else None,
        "metricsTags": case.get("metricsTags") or [],
        "rawActual": raw_actual,
        "profileActual": actual,
        "actual": actual,
        "liveError": live_error,
        "schemaGaps": schema_gaps,
        "legacyOnlyFields": legacy_only_fields,
        "qualityExcluded": quality_excluded,
        "passed": not failures,
        "failures": failures,
    }


def _duration_summary(values: list[int]) -> dict[str, int | None]:
    if not values:
        return {"count": 0, "medianMs": None, "p95Ms": None, "maxMs": None}
    ordered = sorted(values)
    p95_index = min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95)))
    return {
        "count": len(values),
        "medianMs": int(statistics.median(values)),
        "p95Ms": ordered[p95_index],
        "maxMs": max(values),
    }


def _bump(counter: dict[str, int], key: Any) -> None:
    text = str(key or "").strip()
    if not text:
        return
    counter[text] = counter.get(text, 0) + 1


def _build_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_node: dict[str, dict[str, int]] = {}
    by_tag: dict[str, dict[str, int]] = {}
    field_failures: dict[str, int] = {}
    schema_gaps: dict[str, int] = {}
    legacy_only_fields: dict[str, int] = {}
    env_excluded_by_reason: dict[str, int] = {}
    provider_env_excluded = 0
    latencies: list[int] = []
    stability_groups: dict[str, list[bool]] = {}
    for record in records:
        if record.get("actualSource") == "provider_env":
            provider_env_excluded += 1
            live_error = record.get("liveError") if isinstance(record.get("liveError"), dict) else {}
            _bump(env_excluded_by_reason, live_error.get("type") or "provider_env")
            continue
        passed = bool(record.get("passed"))
        node = str(record.get("node") or "unknown")
        by_node.setdefault(node, {"total": 0, "passed": 0, "failed": 0})
        by_node[node]["total"] += 1
        by_node[node]["passed" if passed else "failed"] += 1
        for tag in record.get("metricsTags") or []:
            tag_text = str(tag or "").strip()
            if not tag_text:
                continue
            by_tag.setdefault(tag_text, {"total": 0, "passed": 0, "failed": 0})
            by_tag[tag_text]["total"] += 1
            by_tag[tag_text]["passed" if passed else "failed"] += 1
        for failure in record.get("failures") or []:
            _bump(field_failures, failure.get("field") or failure.get("type"))
        for gap in record.get("schemaGaps") or []:
            _bump(schema_gaps, gap.get("field"))
        for item in record.get("legacyOnlyFields") or []:
            _bump(legacy_only_fields, item.get("missingField"))
        if isinstance(record.get("latencyMs"), int):
            latencies.append(int(record["latencyMs"]))
        base_case_id = str(record.get("baseCaseId") or record.get("caseId") or "").strip()
        if base_case_id:
            stability_groups.setdefault(base_case_id, []).append(passed)
    quality_records = [record for record in records if record.get("actualSource") != "provider_env"]
    total = len(quality_records)
    passed = sum(1 for record in quality_records if record.get("passed"))
    failed = total - passed
    repeated_groups = {
        case_id: values
        for case_id, values in stability_groups.items()
        if len(values) > 1
    }
    stable_passed = sum(
        1
        for values in repeated_groups.values()
        if values and all(values)
    )
    return {
        "rawTotal": len(records),
        "total": total,
        "passed": passed,
        "failed": failed,
        "passRate": round(passed / total, 4) if total else None,
        "byNode": by_node,
        "byTag": by_tag,
        "fieldFailures": field_failures,
        "schemaGaps": schema_gaps,
        "legacyOnlyFields": legacy_only_fields,
        "providerEnvExcluded": provider_env_excluded,
        "providerEnvExcludedByReason": env_excluded_by_reason,
        "latency": _duration_summary(latencies),
        "stability": {
            "caseGroups": len(repeated_groups),
            "stablePassedGroups": stable_passed,
            "stablePassRate": round(stable_passed / len(repeated_groups), 4) if repeated_groups else None,
        },
    }


def build_report(cases: list[dict[str, Any]], *, sample_limit: int = 20) -> dict[str, Any]:
    records = [_evaluate_case(case) for case in cases]
    failures = [
        record
        for record in records
        if not record.get("passed") and not record.get("qualityExcluded")
    ]
    return {
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "summary": _build_summary(records),
        "records": records,
        "failureExamples": failures[:sample_limit],
    }


def _case_input(case: dict[str, Any]) -> dict[str, Any]:
    value = case.get("input")
    return value if isinstance(value, dict) else {}


def _case_prompt(case: dict[str, Any]) -> str:
    for key in ("prompt", "latestUserText", "latest_utterance"):
        text = str(case.get(key) or "").strip()
        if text:
            return text
    data = _case_input(case)
    return str(data.get("latestUserText") or data.get("latest_utterance") or "").strip()


def _build_planning_summary(payload: dict[str, Any]) -> Any:
    from app.agent.context import PlanningSummary

    summary_payload = payload.get("planningSummary")
    if isinstance(summary_payload, dict):
        allowed = {field.name for field in fields(PlanningSummary)}
        return PlanningSummary(**{key: value for key, value in summary_payload.items() if key in allowed})

    profile = payload.get("planningStateProfile")
    if not isinstance(profile, dict):
        return None
    formal_plan_present = bool(profile.get("formalPlanPresent"))
    working_total = int(profile.get("workingTotal") or profile.get("working_total") or (1 if formal_plan_present else 0))
    ordered_total = int(profile.get("orderedTotal") or profile.get("ordered_total") or working_total)
    return PlanningSummary(
        phase=str(profile.get("phase") or ("plan" if formal_plan_present else "")),
        version=int(profile.get("version") or 0),
        working_total=working_total,
        working_target_total=int(profile.get("workingTargetTotal") or profile.get("working_target_total") or working_total),
        ordered_total=ordered_total,
        ordered_target_total=int(profile.get("orderedTargetTotal") or profile.get("ordered_target_total") or ordered_total),
        review_warn_count=int(profile.get("reviewWarnCount") or profile.get("review_warn_count") or 0),
        review_risk_count=int(profile.get("reviewRiskCount") or profile.get("review_risk_count") or 0),
        risk_summaries=list(profile.get("riskSummaries") or profile.get("risk_summaries") or []),
        tier_counts=dict(profile.get("tierCounts") or profile.get("tier_counts") or {}),
    )


def _build_request_context(case: dict[str, Any]) -> Any:
    from app.agent.context import RequestContext
    from app.models.conversation_phase import ConversationPhase, PendingConfirmation

    payload = _case_input(case)
    planning_summary = _build_planning_summary(payload)
    pending_state = payload.get("pendingState")
    pending = None
    if isinstance(pending_state, dict):
        execution_payload = pending_state.get("executionPayload")
        pending = PendingConfirmation(
            kind="intent_change" if pending_state.get("kind") == "intent_change" else "plan_mutation",
            action_family=str(pending_state.get("actionFamily") or pending_state.get("action_family") or "unknown"),
            preview_summary=str(pending_state.get("summary") or pending_state.get("previewSummary") or ""),
            execution_payload=execution_payload if isinstance(execution_payload, dict) else {},
            affected_scope=str(pending_state.get("affectedScope") or ""),
            created_turn=int(pending_state.get("createdTurn") or 1),
            source_backend_version=int(pending_state.get("sourceBackendVersion") or 0),
        )
    elif bool((payload.get("planningStateProfile") or {}).get("pendingExists")):
        pending = PendingConfirmation(kind="plan_mutation", action_family="unknown")

    conversation_phase = ConversationPhase.from_pending_confirmation(
        pending,
        planning_summary=planning_summary,
        turn_count=int(payload.get("turnCount") or 1),
    )
    return RequestContext(
        userid=str(payload.get("userid") or "benchmark-user"),
        sessionid=str(payload.get("sessionid") or "benchmark-session"),
        chat_history=list(payload.get("historyContext") or []),
        planning_summary=planning_summary,
        conversation_phase=conversation_phase,
        allow_explore_inner_llm=False,
        enable_intent_side_effect_arbitration=True,
    )


def _live_error_type(exc: BaseException) -> str:
    text = str(exc).lower()
    if "llm_api_key" in text or "api_key" in text and ("missing" in text or "required" in text):
        return "missing_api_key"
    if "connection error" in text or "connection refused" in text or "connecterror" in text:
        return "provider_connection_error"
    if "network is unreachable" in text or "name or service not known" in text or "nodename nor servname" in text:
        return "provider_connection_error"
    if "401" in text or "unauthorized" in text or "invalid api" in text:
        return "invalid_api_key"
    if "403" in text or "insufficient balance" in text or "余额" in text:
        return "provider_unavailable"
    if "model does not exist" in text or "model_not_found" in text:
        return "model_not_found"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if isinstance(exc, NotImplementedError):
        return "unsupported_live_node"
    return "live_node_error"


def _is_provider_env_error(error_type: str) -> bool:
    return error_type in {
        "missing_api_key",
        "invalid_api_key",
        "provider_unavailable",
        "provider_connection_error",
        "model_not_found",
        "timeout",
    }


async def _run_live_node_case(case: dict[str, Any]) -> dict[str, Any]:
    node = str(case.get("node") or "").strip()
    prompt = _case_prompt(case)
    payload = _case_input(case)
    request_context = _build_request_context(case)

    if node == "intent_side_effect":
        from app.tools import intent_state_tool

        result = await intent_state_tool._classify_intent_side_effect(
            latest_utterance=prompt,
            major_intents=payload.get("majorIntents"),
            school_intents=payload.get("schoolIntents"),
            city_intents=payload.get("cityIntents") or payload.get("regionIntents"),
            career_intents=payload.get("careerIntents"),
            intent_mode=str(payload.get("intentMode") or "preference"),
        )
        return _model_to_dict(result)

    if node == "turn_side_effect":
        from app.tools import turn_decision_tool

        result = await turn_decision_tool.classify_turn_decision(
            prompt,
            payload=payload,
        )
        return _model_to_dict(result)

    if node == "intent_entity_extraction":
        from app.tools import intent_entity_profile_tool

        result = await intent_entity_profile_tool.extract_intent_entity_profile(
            prompt,
            context=payload,
        )
        return _model_to_dict(result)

    if node == "reply_focus_binding":
        from app.tools import reply_profile_tool

        result = await reply_profile_tool.classify_reply_focus_binding(
            prompt,
            payload=payload,
        )
        return _model_to_dict(result)

    if node == "reply_generation_grounding":
        from app.tools import reply_profile_tool

        result = await reply_profile_tool.classify_reply_generation_grounding(
            prompt,
            payload=payload,
        )
        return _model_to_dict(result)

    if node == "plan_query_profile":
        from app.tools import plan_query_profile_tool

        result = await plan_query_profile_tool.classify_plan_query_profile(
            prompt,
            payload=payload,
        )
        return _model_to_dict(result)

    if node == "candidate_filter_extraction":
        from app.tools import candidate_filter_extraction_tool

        result = await candidate_filter_extraction_tool.extract_candidate_query_filters_async(
            prompt,
            batch=str(payload.get("batch") or "01"),
        )
        filters = result.get("filters") if isinstance(result.get("filters"), dict) else {}
        raw = result.get("raw") if isinstance(result.get("raw"), dict) else {}
        tiers = list(filters.get("tiers") or raw.get("tiers") or [])
        return {
            "shouldQueryCandidate": bool(result.get("should_query_candidate")),
            "confidence": result.get("confidence"),
            "ambiguities": result.get("ambiguities") or [],
            "scope": "tier_segment" if tiers else "candidate_pool",
            "tier": "保底" if "保" in tiers else (tiers[0] if tiers else ""),
            "slice": "tail" if any(word in prompt for word in ("最后", "后面", "末尾")) else "",
            "fields": [
                field
                for field, keywords in {
                    "school": ("学校", "院校"),
                    "admissionProbability": ("录取率", "概率", "几率"),
                }.items()
                if any(keyword in prompt for keyword in keywords)
            ],
            "filters": filters,
            "raw": raw,
        }

    if node in {"plan_semantic_action", "local_plan_action_dsl", "proposal_selection"}:
        from app.tools import plan_semantic_action_tool

        if node == "plan_semantic_action":
            result = await plan_semantic_action_tool.classify_plan_semantic_action(
                prompt,
                request_context=request_context,
                recent_plan_context=payload.get("recentPlanContext") if isinstance(payload.get("recentPlanContext"), dict) else None,
            )
            return _model_to_dict(result)
        if node == "local_plan_action_dsl":
            result = await plan_semantic_action_tool.classify_local_plan_action_dsl(
                prompt,
                request_context=request_context,
                recent_plan_context=payload.get("recentPlanContext") if isinstance(payload.get("recentPlanContext"), dict) else None,
            )
            return _model_to_dict(result)
        result = await plan_semantic_action_tool.select_fix_proposal_candidate(
            latest_utterance=prompt,
            assistant_reply=str(payload.get("assistantReply") or ""),
            candidates=list(payload.get("candidates") or []),
            request_context=request_context,
        )
        return _model_to_dict(result)

    raise NotImplementedError(f"live-node adapter is not implemented for node: {node}")


async def _materialize_live_actual(case: dict[str, Any]) -> dict[str, Any]:
    materialized = dict(case)
    start = time.perf_counter()
    try:
        materialized["actual"] = await _run_live_node_case(case)
        materialized["actualSource"] = "live_node"
    except Exception as exc:  # noqa: BLE001 - benchmark reports tool/provider failure classes.
        error_type = _live_error_type(exc)
        materialized["actual"] = {}
        materialized["actualSource"] = "provider_env" if _is_provider_env_error(error_type) else "live_node_error"
        materialized["liveError"] = {
            "type": error_type,
            "message": str(exc),
        }
    finally:
        materialized["latencyMs"] = int((time.perf_counter() - start) * 1000)
    return materialized


def _repeat_cases(cases: list[dict[str, Any]], repeat: int) -> list[dict[str, Any]]:
    if repeat <= 1:
        return cases
    repeated: list[dict[str, Any]] = []
    for case in cases:
        case_id = str(case.get("caseId") or "").strip()
        for index in range(1, repeat + 1):
            clone = dict(case)
            clone["baseCaseId"] = case_id
            clone["repeatIndex"] = index
            clone["caseId"] = f"{case_id}#r{index}" if case_id else f"repeat-{index}"
            if "actual" in clone:
                clone.pop("actual")
            repeated.append(clone)
    return repeated


async def build_report_async(
    cases: list[dict[str, Any]],
    *,
    actual_source: str = "fixture",
    sample_limit: int = 20,
    repeat: int = 1,
) -> dict[str, Any]:
    if repeat < 1:
        raise ValueError("repeat must be greater than or equal to 1")
    materialized_cases = cases
    if actual_source == "live-node":
        materialized_cases = _repeat_cases(cases, repeat)
        materialized_cases = [await _materialize_live_actual(case) for case in materialized_cases]
    return build_report(materialized_cases, sample_limit=sample_limit)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate model-dependent node benchmark cases.")
    parser.add_argument("--cases", required=True, help="model node benchmark case JSON")
    parser.add_argument("--output", help="write JSON report to this path")
    parser.add_argument("--actual-source", choices=["fixture", "live-node"], default="fixture")
    parser.add_argument("--nodes", help="comma-separated node names to include")
    parser.add_argument("--repeat", type=int, default=1, help="repeat each case N times in live-node mode")
    parser.add_argument("--sample-limit", type=int, default=20)
    args = parser.parse_args()

    cases = _filter_cases_by_nodes(_load_cases(args.cases), args.nodes)
    report = asyncio.run(
        build_report_async(
            cases,
            actual_source=args.actual_source,
            sample_limit=args.sample_limit,
            repeat=args.repeat,
        )
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
