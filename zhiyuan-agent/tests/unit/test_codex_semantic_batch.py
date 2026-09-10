from scripts.codex_semantic_batch import SCENARIOS
from scripts.codex_semantic_batch import run_batch
from scripts.codex_semantic_batch import write_jsonl
from scripts.codex_semantic_report import build_report


def test_batch_contains_all_core_scenarios():
    assert set(SCENARIOS) == {
        "reference-missing-scope",
        "reference-complete-history",
        "reference-authoritative-history",
        "mixed-read-write",
    }


def test_batch_retries_environment_failures_but_not_semantic_failures():
    import asyncio
    import scripts.codex_semantic_batch as batch

    calls = []

    async def fake_run(factory):
        calls.append(factory)
        return {"status": "timed_out", "errorCode": "turn_timeout", "scenario": "x"} if len(calls) == 1 else {
            "status": "completed", "evaluation": {"passed": True}, "scenario": "x"
        }

    original = batch.run_scenario
    batch.run_scenario = fake_run
    try:
        results = asyncio.run(run_batch(["reference-missing-scope"], retries=1))
    finally:
        batch.run_scenario = original

    assert len(results) == 2
    assert results[-1]["retryCategory"] == "passed"
    assert [row["batchScenario"] for row in results] == [
        "reference-missing-scope",
        "reference-missing-scope",
    ]


def test_batch_records_runner_exceptions_and_keeps_scenario_identity():
    import asyncio
    import scripts.codex_semantic_batch as batch

    calls = 0

    async def fake_run(factory):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("app server unavailable")
        return {"status": "completed", "evaluation": {"passed": True}, "scenario": "internal-case-id"}

    original = batch.run_scenario
    batch.run_scenario = fake_run
    try:
        results = asyncio.run(run_batch(["reference-missing-scope"], retries=1))
    finally:
        batch.run_scenario = original

    assert results[0]["status"] == "environment_blocked"
    assert results[0]["errorCode"] == "scenario_runner_exception"
    assert results[0]["retryCategory"] == "environment_blocked"
    assert [row["batchScenario"] for row in results] == [
        "reference-missing-scope",
        "reference-missing-scope",
    ]
    assert build_report(results)["scenarioTotal"] == 1
    assert build_report(results)["finalCategories"] == {"passed": 1}


def test_write_jsonl_creates_missing_parent_directory(tmp_path):
    output = tmp_path / "artifacts" / "semantic.jsonl"

    write_jsonl(output, [{"scenario": "x", "status": "completed"}])

    assert output.read_text(encoding="utf-8") == '{"scenario": "x", "status": "completed"}\n'
