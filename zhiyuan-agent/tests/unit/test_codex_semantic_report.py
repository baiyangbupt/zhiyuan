from scripts.codex_semantic_report import build_report, classify_result, write_report


def test_classifies_environment_contract_and_semantic_results():
    assert classify_result({"status": "timed_out", "errorCode": "turn_timeout"}) == "environment_blocked"
    assert classify_result({"status": "completed", "outputValidationError": "bad"}) == "contract_failure"
    assert classify_result({"status": "completed", "evaluation": {"passed": False}}) == "semantic_failure"
    assert classify_result({"status": "completed", "evaluation": {"passed": True}}) == "passed"


def test_build_report_keeps_quality_separate_from_environment_failures():
    report = build_report([
        {"scenario": "ok", "status": "completed", "evaluation": {"passed": True}},
        {"scenario": "bad", "status": "completed", "evaluation": {"passed": False, "failures": ["missing_tools"]}},
        {"scenario": "offline", "status": "timed_out", "errorCode": "turn_timeout"},
    ])
    assert report["total"] == 3
    assert report["scenarioTotal"] == 3
    assert report["passed"] == 1
    assert report["qualityRate"] == 1 / 3
    assert report["categories"]["environment_blocked"] == 1
    assert report["failureReasons"] == {"missing_tools": 1}


def test_report_uses_last_attempt_for_scenario_quality_rate():
    report = build_report([
        {"scenario": "history", "status": "timed_out", "errorCode": "turn_timeout", "batchAttempt": 1},
        {"scenario": "history", "status": "completed", "evaluation": {"passed": True}, "batchAttempt": 2},
    ])

    assert report["total"] == 2
    assert report["scenarioTotal"] == 1
    assert report["passed"] == 1
    assert report["qualityRate"] == 1.0
    assert report["attemptQualityRate"] == 0.5
    assert report["finalCategories"] == {"passed": 1}
    assert [case["finalAttempt"] for case in report["cases"]] == [False, True]


def test_report_groups_retry_attempts_by_batch_scenario_key():
    report = build_report([
        {
            "scenario": "reference-missing-scope",
            "batchScenario": "reference-missing-scope",
            "status": "environment_blocked",
        },
        {
            "scenario": "reference-missing-history-scope",
            "batchScenario": "reference-missing-scope",
            "status": "completed",
            "evaluation": {"passed": False, "failures": ["message_reference_missing"]},
        },
    ])

    assert report["scenarioTotal"] == 1
    assert report["finalCategories"] == {"semantic_failure": 1}
    assert report["finalFailureReasons"] == {"message_reference_missing": 1}
    assert report["observability"]["attemptsByScenario"] == {"reference-missing-scope": 2}
    assert [case["scenarioKey"] for case in report["cases"]] == [
        "reference-missing-scope",
        "reference-missing-scope",
    ]


def test_build_report_exposes_latency_tools_and_evidence_coverage():
    report = build_report([
        {"status": "completed", "elapsedMs": 100, "trace": {"toolCalls": [{}], "evidenceIds": ["e1"]}, "evaluation": {"passed": True}},
        {"status": "completed", "elapsedMs": 300, "trace": {"toolCalls": [{}, {}], "evidenceIds": []}, "evaluation": {"passed": True}},
    ])
    assert report["observability"] == {
        "completed": 2,
        "evidenceCoverage": 0.5,
        "averageElapsedMs": 200.0,
        "averageToolCalls": 1.5,
        "outputRepairCount": 0,
        "attemptsByScenario": {},
    }


def test_report_exposes_recovery_and_retry_metadata():
    report = build_report([
        {
            "scenario": "history",
            "status": "completed",
            "batchAttempt": 2,
            "retryCategory": "passed",
            "recovery": {"outputRepaired": True},
            "evaluation": {"passed": True},
        }
    ])
    assert report["observability"]["outputRepairCount"] == 1
    assert report["observability"]["attemptsByScenario"] == {"history": 1}
    assert report["cases"][0]["batchAttempt"] == 2


def test_write_report_creates_missing_parent_directory(tmp_path):
    output = tmp_path / "artifacts" / "semantic.json"

    write_report(output, {"qualityRate": 1.0})

    assert output.read_text(encoding="utf-8") == '{\n  "qualityRate": 1.0\n}\n'
