import importlib.util
import sys
from pathlib import Path


AUDIT_PATH = Path(__file__).resolve().parents[2] / "examples" / "runtime_pending_sink_call_audit.py"
SPEC = importlib.util.spec_from_file_location("runtime_pending_sink_call_audit", AUDIT_PATH)
assert SPEC and SPEC.loader
audit = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = audit
SPEC.loader.exec_module(audit)


def test_runtime_pending_sink_call_audit_matches_320_baseline():
    root = Path(__file__).resolve().parents[2]
    examples = root / "examples"
    entries = audit._load_entries(str(examples / "runtime_pending_sink_calls_320.json"))
    expectations = audit._load_json(str(examples / "runtime_pending_sink_calls_320_expectations.json"))

    report = audit.build_report(
        entries,
        service_text=(root / "app" / "service.py").read_text(encoding="utf-8"),
        expectations=expectations,
    )

    assert report["passed"] is True
    for field, expected in expectations["expected"]["summary"].items():
        assert report["summary"][field] == expected
    assert report["unexpectedCalls"] == []
    assert report["missingCalls"] == []


def test_runtime_pending_sink_call_audit_flags_unexpected_call_site():
    entries = [
        {
            "id": "known",
            "target": "_save_pending_confirmation_state",
            "caller": "known",
            "kind": "status_update_keep",
            "phase4Action": "keep",
        }
    ]
    service_text = """
async def known():
    await _save_pending_confirmation_state("s", {})

async def unexpected():
    await _save_pending_confirmation_state("s", {})
"""
    expectations = {
        "expected": {"summary": {"unexpected": 0}},
        "assert": {"exact": ["summary.unexpected"]},
    }

    report = audit.build_report(entries, service_text=service_text, expectations=expectations)

    assert report["passed"] is False
    assert report["summary"]["unexpected"] == 1
    assert report["unexpectedCalls"] == [
        {
            "target": "_save_pending_confirmation_state",
            "caller": "unexpected",
            "line": 6,
            "occurrence": 1,
        }
    ]
