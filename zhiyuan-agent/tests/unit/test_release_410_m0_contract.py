from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


AGENT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = AGENT_ROOT.parent
EXAMPLES = AGENT_ROOT / "examples"
MANIFEST_PATH = EXAMPLES / "release_410_m0_baseline_manifest.json"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gate = _load_module("dialog_quality_gate_410_baseline", EXAMPLES / "dialog_quality_gate.py")
report = _load_module("dialog_case_report_410_baseline", EXAMPLES / "dialog_case_evaluation_report.py")


def _case_step_count(case_path: Path) -> int:
    payload = json.loads(case_path.read_text(encoding="utf-8"))
    cases = report._expand_case_payload(payload)
    return sum(len(case.get("prompts") or []) for case in cases)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_release_410_m0_manifest_matches_quality_gate_and_case_steps():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    final_files = manifest["finalActionGate"]["caseFiles"]
    live_files = manifest["liveGate"]["caseFiles"]

    assert list(final_files) == gate.FINAL_ACTION_CASE_FILES
    assert list(live_files) == gate.PINNED_LIVE_CASE_FILES
    assert len(final_files) == manifest["finalActionGate"]["expectedFileCount"] == 24
    assert len(live_files) == manifest["liveGate"]["expectedFileCount"] == 13

    for name, expected_steps in {**final_files, **live_files}.items():
        assert _case_step_count(EXAMPLES / name) == expected_steps, name

    assert sum(final_files.values()) == manifest["finalActionGate"]["expectedStepCount"] == 177
    assert sum(live_files.values()) == manifest["liveGate"]["expectedStepCount"] == 231


def test_release_410_m0_large_fixture_manifest_records_retired_sources():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    for fixture in manifest["retiredLargeFixtureSources"]:
        path = (AGENT_ROOT / fixture["path"]).resolve()
        assert path.is_relative_to(REPO_ROOT)
        assert fixture["removedFromRepository"] is True
        assert fixture["bytes"] > 0
        assert len(fixture["sha256"]) == 64
        if path.exists():
            assert path.stat().st_size == fixture["bytes"]
            assert _sha256(path) == fixture["sha256"]

    assert not (AGENT_ROOT / "tests" / "fixtures" / "session_volunteer_16.json").exists()

    for artifact in manifest["m0ContractArtifacts"]:
        assert (AGENT_ROOT / artifact).resolve().is_file(), artifact
