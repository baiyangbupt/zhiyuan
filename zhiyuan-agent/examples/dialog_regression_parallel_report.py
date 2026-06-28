#!/usr/bin/env python3
"""Summarize outputs produced by dialog_regression_parallel_runner.py."""

from __future__ import annotations

import argparse
import importlib.util
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_case_names(case_files: list[str]) -> list[tuple[str, str]]:
    report_path = ROOT / "examples" / "dialog_case_evaluation_report.py"
    spec = importlib.util.spec_from_file_location("dialog_case_evaluation_report_for_parallel_summary", report_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load dialog_case_evaluation_report from {report_path}")
    report = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(report)

    result: list[tuple[str, str]] = []
    for case_file in case_files:
        path = Path(case_file)
        payload = _load_json(path)
        for case in report._expand_case_payload(payload):
            case_name = str(case.get("name") or "").strip()
            if case_name:
                result.append((path.name, case_name))
    return result


def _split_metric_filename(path: Path) -> tuple[str, str]:
    stem = path.name.removesuffix(".metrics.json")
    if "__" not in stem:
        return stem, stem
    case_file, case_name = stem.split("__", 1)
    return f"{case_file}.json", case_name


def _failure_category(message: str) -> str:
    text = str(message or "")
    if (
        "failureReason" in text
        and "environment" in text
        or "Operation not permitted" in text
        or "Connection refused" in text
        or "backend state clone had failures" in text
    ):
        return "environment"
    if "maxElapsed" in text or "latency" in text or "Timeout" in text:
        return "latency"
    if "assertFollowup" in text or "assertNoFollowups" in text:
        return "followup_protocol"
    if "assertContains" in text or "forbiddenPatterns" in text or "assertNotContains" in text:
        return "content_contract"
    if "missing_metrics" in text:
        return "runner_missing_metrics"
    return "other"


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text_contains_any(text: str, needles: list[str]) -> bool:
    return any(item in text for item in needles)


def _record_violation_messages(record: dict[str, Any]) -> list[str]:
    messages: list[str] = []
    for key in (
        "contentViolations",
        "toolViolations",
        "performanceViolations",
        "styleViolations",
        "warnings",
    ):
        messages.extend(str(item) for item in _as_list(record.get(key)))
    return messages


def _record_observability(record: dict[str, Any]) -> dict[str, Any]:
    return _as_dict(record.get("turnObservability"))


def _record_route_decision(record: dict[str, Any]) -> dict[str, Any]:
    return _as_dict(_record_observability(record).get("routeDecision"))


def _record_action_families(record: dict[str, Any]) -> list[str]:
    observability = _record_observability(record)
    families = [str(item) for item in _as_list(observability.get("actionFamilies")) if item]
    for call in _as_list(observability.get("toolCalls")):
        if isinstance(call, dict) and call.get("actionFamily"):
            families.append(str(call["actionFamily"]))
    return sorted(set(families))


def _record_result_kinds(record: dict[str, Any]) -> list[str]:
    observability = _record_observability(record)
    kinds = [str(item) for item in _as_list(observability.get("resultKinds")) if item]
    for call in _as_list(observability.get("toolCalls")):
        if isinstance(call, dict) and call.get("resultKind"):
            kinds.append(str(call["resultKind"]))
    return sorted(set(kinds))


def _record_has_failure(record: dict[str, Any]) -> bool:
    return bool(
        record.get("contentViolations")
        or record.get("toolViolations")
        or record.get("performanceViolations")
        or record.get("styleViolations")
        or record.get("failureReason")
        or record.get("error")
        or record.get("wsError")
    )


def _infer_record_root_causes(record: dict[str, Any]) -> list[str]:
    """Infer report-only root causes from runner metrics.

    These buckets are diagnostics for triage; they do not participate in
    runtime routing or assertions.
    """

    violations = "\n".join(_record_violation_messages(record))
    response = str(record.get("responseText") or "")
    prompt = str(record.get("prompt") or "")
    observability = _record_observability(record)
    route_decision = _record_route_decision(record)
    turn_decision = _as_dict(route_decision.get("turnDecision"))
    routing_path = str(observability.get("routingPath") or "")
    blocking_reasons = [str(item) for item in _as_list(route_decision.get("blockingReasons"))]
    action_families = _record_action_families(record)
    result_kinds = _record_result_kinds(record)
    fixture_type = str(record.get("fixtureType") or "").strip()
    fixture_contract = _as_dict(record.get("fixtureContract"))
    required_state = {
        str(item or "").strip()
        for item in _as_list(fixture_contract.get("requiredState"))
        if str(item or "").strip()
    }
    combined = "\n".join(
        [
            prompt,
            response,
            violations,
            routing_path,
            str(route_decision.get("route") or ""),
            str(turn_decision.get("sideEffect") or ""),
            str(turn_decision.get("scenario") or ""),
            " ".join(blocking_reasons),
            " ".join(action_families),
            " ".join(result_kinds),
        ]
    )

    causes: list[str] = []

    if record.get("failureReason") == "environment" or record.get("wsError") or _text_contains_any(
        combined + "\n" + str(record.get("error") or ""),
        [
            "Operation not permitted",
            "Connection refused",
            "backend state clone had failures",
            "WebSocketProxyException",
        ],
    ):
        causes.append("environment_setup")
        return causes

    formal_fixture_expected = fixture_type == "formal_plan_present" or bool(
        required_state & {"orderedPlan", "formalPlan"}
    )
    actual_no_plan_signal = _text_contains_any(
        combined,
        [
            "formalPlanPresent=false",
            "missing_formal_plan",
            "当前方案共 0/0",
            "当前还没有生成正式方案",
            "目前还没有正式志愿方案",
            "还没有正式方案",
            "没有生成正式方案",
        ],
    )
    if formal_fixture_expected and actual_no_plan_signal:
        causes.append("fixture_state_clone_gap")

    if "assertThinking" in violations:
        causes.append("assertion_noise_thinking")

    if record.get("performanceViolations") or _failure_category(violations) == "latency":
        causes.append("latency_longtail")

    no_formal_plan = (
        routing_path == "needs_plan_first_guard"
        or "missing_formal_plan" in blocking_reasons
        or _text_contains_any(
            response,
            [
                "当前还没有生成正式方案",
                "目前还没有正式志愿方案",
                "还没有正式方案",
                "没有生成正式方案",
            ],
        )
    )
    expects_plan_state = _text_contains_any(
        violations,
        [
            "expected '冲'",
            "expected '稳'",
            "expected '保'",
            "pendingConfirmationCard",
            "assertFollowup",
            "targetView='ordered'",
            "targetView='review'",
        ],
    )
    if no_formal_plan and expects_plan_state:
        causes.append("fixture_mismatch_no_formal_plan")

    expects_local_plan_lookup = (
        _text_contains_any(prompt, ["放多了", "多不多", "是不是多", "有没有", "相关专业是不是有多个"])
        and _text_contains_any(violations, ["assertContains", "assertContainsAny"])
        and _text_contains_any(
            violations,
            [
                "expected '青岛",
                "expected '命中",
                "expected '相关",
                "expected '示例",
                "expected '多个",
            ],
        )
    )
    if no_formal_plan and expects_local_plan_lookup:
        causes.append("fixture_mismatch_no_formal_plan")

    no_pending_guard = _text_contains_any(
        response,
        [
            "没有上一轮正在等待",
            "没有待确认",
            "没有待执行",
            "没有上一轮待确认",
        ],
    )
    if no_pending_guard and _text_contains_any(violations, ["assertFollowupTarget", "assertFollowupRefresh"]):
        causes.append("assertion_noise_old_pending_expectation")

    plan_action_families = {
        "add_units",
        "remove_units",
        "replace_units",
        "move_unit",
        "move_ordered_unit",
        "sort_ordered_plan",
        "preview_fix_proposal",
        "apply_fix_proposal",
    }
    has_plan_action = any(family in plan_action_families for family in action_families)
    no_executable_preview = (
        "error" in result_kinds
        or _text_contains_any(
            response,
            [
                "没有生成可执行",
                "没有唯一定位",
                "缺少目标位置",
                "信息还不够完整",
                "没有形成可确认的调整预览",
            ],
        )
    )
    expected_pending = _text_contains_any(
        violations,
        [
            "pendingConfirmationCard",
            "assertFollowupCount",
            "assertFollowupType",
            "assertActionFamiliesContain",
        ],
    )
    if has_plan_action and (no_executable_preview or expected_pending or record.get("toolViolations")):
        causes.append("selector_gap_no_executable_preview")

    if _text_contains_any(prompt + response + " ".join(action_families), ["审查", "风险", "安全", "便宜", "学费", "专业组"]) and (
        _text_contains_any(response, ["已完成方案审查", "没有形成可确认的调整预览"])
        or (
            "preview_fix_proposal" in action_families
            and "review_result" in result_kinds
            and expected_pending
        )
    ):
        causes.append("review_fix_focus_gap")

    if _text_contains_any(
        prompt + violations,
        ["那两个都加", "都加吧", "之前", "上面两个", "expected '计算机'", "expected '电子信息'"],
    ):
        causes.append("intent_context_merge_gap")

    if not causes and record.get("contentViolations"):
        causes.append("reply_focus_gap")

    if not causes:
        causes.append("unknown")

    deduped: list[str] = []
    for cause in causes:
        if cause not in deduped:
            deduped.append(cause)
    return deduped


def _find_record_for_message(records: list[dict[str, Any]], message: str) -> dict[str, Any] | None:
    for record in records:
        if message in _record_violation_messages(record):
            return record
    for record in records:
        prompt = str(record.get("prompt") or "")
        if prompt and prompt in message:
            return record
    return None


def build_report(output_dir: Path, case_files: list[str]) -> dict[str, Any]:
    metric_paths = sorted(output_dir.glob("*.metrics.json"))
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    slowest: list[dict[str, Any]] = []
    completed: set[tuple[str, str]] = set()
    by_file: Counter[str] = Counter()
    failed_by_file: Counter[str] = Counter()
    failed_by_category: Counter[str] = Counter()
    failed_by_root_cause: Counter[str] = Counter()
    root_cause_mentions: Counter[str] = Counter()
    examples_by_root_cause: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for path in metric_paths:
        case_file, case_name = _split_metric_filename(path)
        completed.add((case_file, case_name))
        by_file[case_file] += 1
        payload = _load_json(path)
        summary = payload.get("summary") if isinstance(payload, dict) else {}
        summary = summary if isinstance(summary, dict) else {}
        failed_steps = int(summary.get("failedSteps") or 0)
        steps = int(summary.get("steps") or 0)
        elapsed = summary.get("elapsed") if isinstance(summary.get("elapsed"), dict) else {}
        metric_records = [item for item in _as_list(payload.get("records")) if isinstance(item, dict)]
        record_root_causes: list[dict[str, Any]] = []
        for record in metric_records:
            if not _record_has_failure(record):
                continue
            causes = _infer_record_root_causes(record)
            primary_cause = causes[0]
            failed_by_root_cause[primary_cause] += 1
            root_cause_mentions.update(causes)
            record_summary = {
                "stepIndex": record.get("stepIndex"),
                "prompt": record.get("prompt"),
                "primaryRootCause": primary_cause,
                "rootCauses": causes,
                "routingPath": _record_observability(record).get("routingPath"),
                "actionFamilies": _record_action_families(record),
                "resultKinds": _record_result_kinds(record),
            }
            if record.get("fixtureType"):
                record_summary["fixtureType"] = record.get("fixtureType")
            if record.get("expectedRootCause"):
                record_summary["expectedRootCause"] = record.get("expectedRootCause")
            record_root_causes.append(record_summary)
            if len(examples_by_root_cause[primary_cause]) < 8:
                examples_by_root_cause[primary_cause].append(
                    {
                        "caseFile": case_file,
                        "caseName": case_name,
                        "stepIndex": record.get("stepIndex"),
                        "prompt": record.get("prompt"),
                        "routingPath": _record_observability(record).get("routingPath"),
                        "actionFamilies": _record_action_families(record),
                        "resultKinds": _record_result_kinds(record),
                        "metricsPath": str(path),
                    }
                )
        records.append(
            {
                "caseFile": case_file,
                "caseName": case_name,
                "steps": steps,
                "failedSteps": failed_steps,
                "elapsedMaxMs": elapsed.get("maxMs"),
                "rootCauses": record_root_causes,
                "metricsPath": str(path),
            }
        )
        if failed_steps:
            failed_by_file[case_file] += 1
        for item in payload.get("failures") or []:
            message = str(item)
            category = _failure_category(message)
            matched_record = _find_record_for_message(metric_records, message)
            root_causes = _infer_record_root_causes(matched_record) if matched_record else [category if category == "latency" else "unknown"]
            failed_by_category[category] += 1
            failures.append(
                {
                    "caseFile": case_file,
                    "caseName": case_name,
                    "category": category,
                    "inferredRootCause": root_causes[0],
                    "rootCauses": root_causes,
                    "message": message,
                    "metricsPath": str(path),
                }
            )
        for item in payload.get("warnings") or []:
            message = str(item)
            warnings.append(
                {
                    "caseFile": case_file,
                    "caseName": case_name,
                    "category": _failure_category(message),
                    "message": message,
                    "metricsPath": str(path),
                }
            )
        for item in summary.get("slowest") or []:
            if isinstance(item, dict):
                slowest.append(
                    {
                        "caseFile": case_file,
                        "caseName": case_name,
                        "prompt": item.get("prompt"),
                        "elapsedMs": item.get("elapsedMs"),
                        "metricsPath": str(path),
                    }
                )

    expected = _load_case_names(case_files) if case_files else []
    missing = [item for item in expected if item not in completed]
    missing_by_file: dict[str, int] = dict(sorted(Counter(file_name for file_name, _ in missing).items()))
    slowest_sorted = sorted(slowest, key=lambda item: int(item.get("elapsedMs") or 0), reverse=True)

    return {
        "outputDir": str(output_dir),
        "expectedCases": len(expected) if expected else None,
        "completedCases": len(completed),
        "missingCases": len(missing) if expected else None,
        "completedByFile": dict(sorted(by_file.items())),
        "missingByFile": missing_by_file,
        "failedCaseFiles": dict(sorted(failed_by_file.items())),
        "failureCategories": dict(sorted(failed_by_category.items())),
        "failureRootCauses": dict(sorted(failed_by_root_cause.items())),
        "failureRootCauseMentions": dict(sorted(root_cause_mentions.items())),
        "failureRootCauseExamples": dict(sorted(examples_by_root_cause.items())),
        "failureCount": len(failures),
        "warningCount": len(warnings),
        "slowest": slowest_sorted[:20],
        "records": records,
        "failures": failures[:80],
        "warnings": warnings[:80],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize parallel dialog regression metrics.")
    parser.add_argument("--output-dir", required=True, help="parallel runner output directory")
    parser.add_argument("--cases", nargs="*", default=[], help="case files used for the run, used to compute missing cases")
    parser.add_argument("--json-output", help="write the summary JSON to this path")
    args = parser.parse_args()

    report = build_report(Path(args.output_dir), args.cases)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.json_output:
        Path(args.json_output).write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
