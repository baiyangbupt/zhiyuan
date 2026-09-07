#!/usr/bin/env python3
"""Load and export the fixed, non-production shadow replay manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable


REQUIRED_CASE_FIELDS = {
    "caseId",
    "sessionId",
    "input",
    "expectedMode",
    "datasetVersion",
    "writeAllowed",
}


def load_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid manifest JSON: {manifest_path}") from exc

    if not isinstance(payload, dict):
        raise ValueError("manifest must be a JSON object")
    dataset_version = str(payload.get("datasetVersion") or "").strip()
    cases = payload.get("cases")
    if not dataset_version:
        raise ValueError("datasetVersion is required")
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases must be a non-empty list")

    seen: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f"case at index {index} must be an object")
        missing = REQUIRED_CASE_FIELDS - set(case)
        if missing:
            raise ValueError(f"case at index {index} missing fields: {sorted(missing)}")
        case_id = str(case["caseId"] or "").strip()
        if not case_id:
            raise ValueError(f"case at index {index} has empty caseId")
        if case_id in seen:
            raise ValueError(f"duplicate caseId: {case_id}")
        seen.add(case_id)
        if case["writeAllowed"] is not False:
            raise ValueError(f"case {case_id} must set writeAllowed=false")
        if str(case["datasetVersion"] or "").strip() != dataset_version:
            raise ValueError(f"case {case_id} datasetVersion differs from manifest")

    return payload


def write_jsonl(records: Iterable[dict[str, Any]], path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def case_inputs(case: dict[str, Any]) -> list[str]:
    if "input" in case:
        return [str(case["input"] or "")]
    prompts = case.get("prompts") or []
    normalized: list[str] = []
    for prompt in prompts:
        if isinstance(prompt, dict):
            normalized.append(str(prompt.get("prompt") or prompt.get("text") or ""))
        else:
            normalized.append(str(prompt or ""))
    return normalized


def _empty_result(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "caseId": case["caseId"],
        "toolCalls": [],
        "resolvedEntities": [],
        "responseType": "text",
        "latencyMs": 0,
        "writeAttempted": False,
        "error": None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    manifest = load_manifest(args.manifest)
    records = [_empty_result(case) for case in manifest["cases"]]
    if args.output:
        write_jsonl(records, args.output)
    else:
        for record in records:
            print(json.dumps(record, ensure_ascii=False))


if __name__ == "__main__":
    main()
