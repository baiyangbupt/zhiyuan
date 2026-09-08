#!/usr/bin/env python3
"""Replay fixed, de-identified Codex shadow fixtures without production access."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.observability.conversation_trace import aggregate_shadow_report, trace_from_result
from scripts.export_shadow_baseline import load_manifest


def _load_json(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid fixture JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"fixture must be an object: {path}")
    return payload


def load_replay_cases(path: str | Path) -> dict[str, Any]:
    payload = _load_json(path)
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("replay cases must be a non-empty list")
    for case in cases:
        if not isinstance(case, dict) or not case.get("caseId") or not str(case.get("sessionId", "")).startswith("shadow-"):
            raise ValueError("replay cases must use fixed fixture caseId/sessionId, not arbitrary production session ids")
    return payload


def _index_cases(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(case["caseId"]): case for case in payload.get("cases", []) if isinstance(case, dict)}


def replay(*, manifest_path: str | Path, golden_path: str | Path, adversarial_path: str | Path) -> list[dict[str, Any]]:
    manifest = load_manifest(manifest_path)
    golden = load_replay_cases(golden_path)
    adversarial = load_replay_cases(adversarial_path)
    allowed = {str(case["caseId"]): case for case in manifest["cases"]}
    fixtures = {**_index_cases(golden), **_index_cases(adversarial)}
    unknown = set(fixtures) - set(allowed)
    if unknown:
        raise ValueError(f"replay fixture case not in baseline manifest: {sorted(unknown)}")

    records: list[dict[str, Any]] = []
    for case_id, baseline_case in allowed.items():
        fixture = fixtures.get(case_id, {})
        result = dict(fixture.get("result") or {})
        records.append(
            trace_from_result(
                case_id=case_id,
                session_id=str(baseline_case["sessionId"]),
                skill_name=str(fixture.get("skillName") or "profile-discovery"),
                result=result,
            )
        )
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--golden", required=True, type=Path)
    parser.add_argument("--adversarial", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    records = replay(manifest_path=args.manifest, golden_path=args.golden, adversarial_path=args.adversarial)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    report = aggregate_shadow_report(records)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if not report["go"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
