from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "export_shadow_baseline.py"
SPEC = importlib.util.spec_from_file_location("export_shadow_baseline", SCRIPT_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

RUNNER_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_regression_runner.py"
RUNNER_SPEC = importlib.util.spec_from_file_location("dialog_regression_runner", RUNNER_PATH)
assert RUNNER_SPEC and RUNNER_SPEC.loader
runner = importlib.util.module_from_spec(RUNNER_SPEC)
RUNNER_SPEC.loader.exec_module(runner)


def test_baseline_manifest_requires_versions_and_cases() -> None:
    manifest = module.load_manifest(
        Path(__file__).resolve().parents[2]
        / "tests"
        / "fixtures"
        / "shadow"
        / "baseline_manifest.json"
    )

    assert manifest["datasetVersion"]
    assert manifest["cases"]
    assert len(manifest["cases"]) >= 12
    assert all(
        {"caseId", "sessionId", "input", "expectedMode", "datasetVersion", "writeAllowed"}
        <= set(case)
        for case in manifest["cases"]
    )
    assert all(case["writeAllowed"] is False for case in manifest["cases"])


def test_baseline_manifest_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        '{"datasetVersion":"test","cases":['
        '{"caseId":"same","sessionId":"1","input":"a","expectedMode":"readonly",'
        '"datasetVersion":"test","writeAllowed":false},'
        '{"caseId":"same","sessionId":"2","input":"b","expectedMode":"readonly",'
        '"datasetVersion":"test","writeAllowed":false}]}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate caseId"):
        module.load_manifest(manifest_path)


def test_export_results_writes_one_json_object_per_line(tmp_path: Path) -> None:
    output_path = tmp_path / "results.jsonl"
    records = [
        {
            "caseId": "case-1",
            "toolCalls": [],
            "resolvedEntities": [],
            "responseType": "text",
            "latencyMs": 1,
            "writeAttempted": False,
            "error": None,
        }
    ]

    module.write_jsonl(records, output_path)

    lines = output_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert module.json.loads(lines[0]) == records[0]


def test_case_input_normalizer_supports_manifest_single_input() -> None:
    assert module.case_inputs(
        {"input": "查一下浙大", "prompts": ["ignored"]}
    ) == ["查一下浙大"]


def test_case_input_normalizer_supports_legacy_prompt_list() -> None:
    assert module.case_inputs(
        {"prompts": ["第一轮", {"prompt": "第二轮"}]}
    ) == ["第一轮", "第二轮"]


def test_runner_jsonl_export_writes_one_record_per_line(tmp_path: Path) -> None:
    output_path = tmp_path / "runner.jsonl"
    runner._write_jsonl_records([{"case": "one", "elapsedMs": 3}], output_path)

    assert output_path.read_text(encoding="utf-8").splitlines() == [
        '{"case": "one", "elapsedMs": 3}'
    ]
