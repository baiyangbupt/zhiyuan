#!/usr/bin/env python3
"""Build case-level evaluation reports from dialog regression outputs.

This script only consumes saved JSON outputs. It does not call models.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_payload(path: str) -> dict[str, Any]:
    data = _load_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object in {path}")
    return data


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _as_int_ms(value: Any, *, seconds: bool = False) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if seconds:
        return int(number * 1000)
    return int(number)


def _extract_text(record: dict[str, Any]) -> str:
    return _normalize_text(record.get("responseText") or record.get("text") or record.get("reply") or "")


def _extract_thinking(record: dict[str, Any]) -> str:
    thinking = record.get("thinkingText") or record.get("thinking") or ""
    if isinstance(thinking, list):
        return "\n".join(_normalize_text(item) for item in thinking if _normalize_text(item))
    return _normalize_text(thinking)


def _score_case(record: dict[str, Any]) -> dict[str, Any]:
    text = _extract_text(record)
    thinking = _extract_thinking(record)
    score = {
        "correctness": 0,
        "completeness": 0,
        "naturalness": 0,
        "actionability": 0,
        "latency": 0,
    }
    if text:
        score["naturalness"] += 1
        if "\n" in text or "。" in text:
            score["naturalness"] += 1
        if len(text) > 40:
            score["completeness"] += 1
        if len(text) > 120:
            score["completeness"] += 1
        if any(token in text for token in ("建议", "下一步", "可以", "确认", "请查看")):
            score["actionability"] += 1
        if any(token in text for token in ("方案", "候选", "审查", "排序", "移动", "意向", "查询", "专业", "志愿")):
            score["correctness"] += 1
    if record.get("turnObservability") or record.get("followupCount") is not None:
        score["correctness"] += 1
    if record.get("assertionViolations") or record.get("contentViolations"):
        score["correctness"] = max(0, score["correctness"] - 1)
    if thinking:
        score["completeness"] += 1
    if any(token in text for token in ("风险", "提醒", "边界", "结论")):
        score["completeness"] += 1
    elapsed_ms = record.get("elapsedMs")
    if isinstance(elapsed_ms, int):
        if elapsed_ms <= 3000:
            score["latency"] += 2
        elif elapsed_ms <= 10000:
            score["latency"] += 1
        elif elapsed_ms <= 30000:
            score["latency"] += 1
        if elapsed_ms > 60000:
            score["latency"] = max(0, score["latency"] - 1)
    return score


def _normalize_flat_record(record: dict[str, Any], *, step_index: int) -> dict[str, Any]:
    normalized = dict(record)
    case = _normalize_text(normalized.get("case"))
    normalized["case"] = case
    normalized["stepIndex"] = step_index
    normalized["recordKey"] = f"{case}#{step_index}"
    normalized["prompt"] = _normalize_text(normalized.get("prompt"))
    return normalized


def _flatten_runner_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    records = payload.get("records")
    if not isinstance(records, list):
        return []
    flattened: list[dict[str, Any]] = []
    case_counts: dict[str, int] = {}
    for item in records:
        if not isinstance(item, dict):
            continue
        case = _normalize_text(item.get("case"))
        case_counts[case] = case_counts.get(case, 0) + 1
        flattened.append(_normalize_flat_record(item, step_index=case_counts[case]))
    return flattened


def _flatten_provider_benchmark_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    agent_results = payload.get("agent")
    if not isinstance(agent_results, list):
        return []
    grouped: dict[tuple[str, str, str, int], dict[str, Any]] = {}
    for provider_result in agent_results:
        if not isinstance(provider_result, dict):
            continue
        provider = _normalize_text(provider_result.get("provider"))
        model = _normalize_text(provider_result.get("model"))
        provider_label = provider or model or "provider"
        for case in provider_result.get("cases") or []:
            if not isinstance(case, dict):
                continue
            case_name = _normalize_text(case.get("name") or f"session-{case.get('sessionId')}")
            for step_index, step in enumerate(case.get("steps") or [], start=1):
                if not isinstance(step, dict):
                    continue
                key = (provider, model, case_name, step_index)
                current = grouped.get(key)
                record = {
                    "case": case_name,
                    "stepIndex": step_index,
                    "recordKey": f"{case_name}#{step_index}",
                    "prompt": _normalize_text(step.get("prompt")),
                    "responseText": _normalize_text(step.get("text") or step.get("responseText")),
                    "thinkingText": _extract_thinking(step),
                    "elapsedMs": _as_int_ms(step.get("final_seconds"), seconds=True) if step.get("final_seconds") is not None else _as_int_ms(step.get("elapsedMs")),
                    "firstMessageMs": _as_int_ms(step.get("first_message_seconds"), seconds=True) if step.get("first_message_seconds") is not None else _as_int_ms(step.get("firstMessageMs")),
                    "finalMessageMs": _as_int_ms(step.get("final_seconds"), seconds=True) if step.get("final_seconds") is not None else _as_int_ms(step.get("finalMessageMs")),
                    "followupCount": step.get("followup_count") or step.get("followupCount"),
                    "followupTargets": list(step.get("followup_targets") or step.get("followupTargets") or []),
                    "followupRefreshes": list(step.get("followup_refreshes") or step.get("followupRefreshes") or []),
                    "assertionViolations": list(step.get("assertion_violations") or step.get("assertionViolations") or []),
                    "provider": provider,
                    "model": model,
                    "candidateName": provider_label,
                    "candidateKey": f"{provider_label}:{case_name}#{step_index}",
                    "run": case.get("run"),
                    "runCount": 1,
                }
                if current is None:
                    grouped[key] = record
                    continue
                current["runCount"] = int(current.get("runCount") or 1) + 1
                current_elapsed = [value for value in [current.get("elapsedMs"), record.get("elapsedMs")] if isinstance(value, int)]
                current_first = [value for value in [current.get("firstMessageMs"), record.get("firstMessageMs")] if isinstance(value, int)]
                current_final = [value for value in [current.get("finalMessageMs"), record.get("finalMessageMs")] if isinstance(value, int)]
                if current_elapsed:
                    current["elapsedMs"] = int(round(sum(current_elapsed) / len(current_elapsed)))
                if current_first:
                    current["firstMessageMs"] = int(round(sum(current_first) / len(current_first)))
                if current_final:
                    current["finalMessageMs"] = int(round(sum(current_final) / len(current_final)))
                if not current.get("responseText") and record.get("responseText"):
                    current["responseText"] = record["responseText"]
                if not current.get("thinkingText") and record.get("thinkingText"):
                    current["thinkingText"] = record["thinkingText"]
                for field in ("followupTargets", "followupRefreshes", "assertionViolations"):
                    existing = current.get(field)
                    incoming = record.get(field) or []
                    if isinstance(existing, list):
                        merged = list(existing)
                        for item in incoming:
                            if item not in merged:
                                merged.append(item)
                        current[field] = merged
                if record.get("followupCount") is not None:
                    current["followupCount"] = max(int(current.get("followupCount") or 0), int(record["followupCount"]))
    return list(grouped.values())


def _extract_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    records = _flatten_runner_records(payload)
    if records:
        return records
    records = _flatten_provider_benchmark_records(payload)
    if records:
        return records
    if isinstance(payload.get("summary"), dict):
        return [payload]
    return []


def _build_case_index(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for record in _extract_records(payload):
        key = _normalize_text(record.get("recordKey") or record.get("case"))
        if not key:
            continue
        index.setdefault(key, []).append(record)
    return index


def _candidate_rows_for_case(
    candidate_indexes: dict[str, dict[str, list[dict[str, Any]]]],
    case_key: str,
) -> dict[str, dict[str, Any]]:
    rows_by_name: dict[str, dict[str, Any]] = {}
    for group_name, index in candidate_indexes.items():
        rows = index.get(case_key) or []
        for position, row in enumerate(rows, start=1):
            candidate_name = _normalize_text(row.get("candidateName"))
            if not candidate_name:
                provider = _normalize_text(row.get("provider"))
                model = _normalize_text(row.get("model"))
                candidate_name = provider or model or group_name
            name = candidate_name
            if name in rows_by_name:
                name = f"{candidate_name}#{position}"
            rows_by_name[name] = row
    return rows_by_name


def _build_case_report(
    case_key: str,
    baseline: dict[str, Any] | None,
    current: dict[str, Any] | None,
    candidates: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    case_name, _, step_suffix = case_key.partition("#")
    report: dict[str, Any] = {
        "case": case_name or case_key,
        "stepIndex": int(step_suffix) if step_suffix.isdigit() else None,
        "prompt": _normalize_text((current or baseline or {}).get("prompt")),
        "baseline": {
            "reply": _extract_text(baseline or {}),
            "elapsedMs": (baseline or {}).get("elapsedMs"),
            "firstMessageMs": (baseline or {}).get("firstMessageMs"),
            "finalMessageMs": (baseline or {}).get("finalMessageMs"),
            "provider": (baseline or {}).get("provider"),
            "model": (baseline or {}).get("model"),
        },
        "current": {
            "reply": _extract_text(current or {}),
            "elapsedMs": (current or {}).get("elapsedMs"),
            "firstMessageMs": (current or {}).get("firstMessageMs"),
            "finalMessageMs": (current or {}).get("finalMessageMs"),
            "provider": (current or {}).get("provider"),
            "model": (current or {}).get("model"),
        },
        "candidates": [],
    }
    if baseline:
        report["baseline"]["score"] = _score_case(baseline)
    if current:
        report["current"]["score"] = _score_case(current)
    for name, candidate in candidates.items():
        report["candidates"].append(
            {
                "name": name,
                "provider": candidate.get("provider"),
                "model": candidate.get("model"),
                "reply": _extract_text(candidate),
                "elapsedMs": candidate.get("elapsedMs"),
                "firstMessageMs": candidate.get("firstMessageMs"),
                "finalMessageMs": candidate.get("finalMessageMs"),
                "score": _score_case(candidate),
            }
        )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build case-level evaluation reports.")
    parser.add_argument("--baseline", help="baseline dialog regression JSON")
    parser.add_argument("--current", help="current dialog regression JSON")
    parser.add_argument("--candidates", action="append", default=[], help="candidate JSON in name=path form")
    parser.add_argument("--output", help="write report JSON to this path")
    parser.add_argument("--markdown", action="store_true", help="render a markdown table instead of JSON")
    args = parser.parse_args()

    baseline_payload = _load_payload(args.baseline) if args.baseline else {}
    current_payload = _load_payload(args.current) if args.current else {}
    baseline_index = _build_case_index(baseline_payload)
    current_index = _build_case_index(current_payload)

    candidate_indexes: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for item in args.candidates:
        if "=" not in item:
            raise ValueError("--candidates must be in name=path form")
        name, path = item.split("=", 1)
        candidate_indexes[name] = _build_case_index(_load_payload(path))

    all_cases = sorted(set(baseline_index) | set(current_index) | {case for index in candidate_indexes.values() for case in index})
    reports = []
    for case_key in all_cases:
        baseline_rows = baseline_index.get(case_key) or []
        current_rows = current_index.get(case_key) or []
        candidate_rows = _candidate_rows_for_case(candidate_indexes, case_key)
        reports.append(
            _build_case_report(
                case_key,
                baseline_rows[0] if baseline_rows else None,
                current_rows[0] if current_rows else None,
                candidate_rows,
            )
        )

    payload = {"count": len(reports), "cases": reports}
    if args.markdown:
        lines = ["| case | baseline | current | candidates |", "|---|---|---|---|"]
        for item in reports:
            baseline = item.get("baseline", {}).get("reply", "")
            current = item.get("current", {}).get("reply", "")
            candidate_text = "; ".join(
                f"{candidate.get('name')}: {candidate.get('reply', '')}"
                for candidate in item.get("candidates", [])
            )
            lines.append(
                f"| {item.get('case', '')} | {baseline[:80]} | {current[:80]} | {candidate_text[:80]} |"
            )
        text = "\n".join(lines)
    else:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
