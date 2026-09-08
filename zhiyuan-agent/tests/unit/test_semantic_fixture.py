import json
from pathlib import Path


def test_multiturn_semantic_fixture_contains_result_synthesis_cases() -> None:
    path = Path(__file__).parents[1] / "fixtures" / "codex_semantic" / "multiturn_cases.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload["cases"]
    assert {case["caseId"] for case in cases} == {
        "reference-followup-history",
        "missing-history-scope",
        "constraint-change-preview",
        "confirmation-before-write",
        "partial-read-result",
        "blocked-read-result",
    }
    assert all(case["turns"] for case in cases)
