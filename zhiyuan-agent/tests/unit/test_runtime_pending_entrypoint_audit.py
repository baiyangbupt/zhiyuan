import importlib.util
import sys
from pathlib import Path


AUDIT_PATH = Path(__file__).resolve().parents[2] / "examples" / "runtime_pending_entrypoint_audit.py"
SPEC = importlib.util.spec_from_file_location("runtime_pending_entrypoint_audit", AUDIT_PATH)
assert SPEC and SPEC.loader
audit = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = audit
SPEC.loader.exec_module(audit)


def test_runtime_pending_entrypoint_audit_matches_320_baseline():
    examples = Path(__file__).resolve().parents[2] / "examples"
    service_path = Path(__file__).resolve().parents[2] / "app" / "service.py"
    entries = audit._load_entries(str(examples / "runtime_pending_entrypoints_320.json"))
    expectations = audit._load_json(str(examples / "runtime_pending_entrypoints_320_expectations.json"))

    report = audit.build_report(
        entries,
        service_text=service_path.read_text(encoding="utf-8"),
        expectations=expectations,
    )

    assert report["passed"] is True
    for field, expected in expectations["expected"]["summary"].items():
        assert report["summary"][field] == expected


def test_runtime_pending_entrypoint_audit_fails_when_symbol_is_missing():
    entries = [
        {
            "id": "missing-entry",
            "symbol": "_missing_pending_symbol",
            "kind": "delete_after_cut",
            "phase4Action": "delete_legacy_path",
            "risk": "high",
        }
    ]
    expectations = {
        "expected": {"summary": {"total": 1, "missing": 0}},
        "assert": {"exact": ["summary.total", "summary.missing"]},
    }

    report = audit.build_report(entries, service_text="", expectations=expectations)

    assert report["passed"] is False
    assert report["summary"]["missing"] == 1
    assert report["summary"]["missingSymbols"] == ["_missing_pending_symbol"]
    assert report["failures"] == [
        {"type": "exact", "field": "summary.missing", "expected": 0, "actual": 1}
    ]
