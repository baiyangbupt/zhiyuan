import importlib.util
from pathlib import Path


REPORT_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_case_evaluation_report.py"
SPEC = importlib.util.spec_from_file_location("dialog_case_evaluation_report", REPORT_PATH)
assert SPEC and SPEC.loader
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)


def test_build_case_index_collects_flat_records_by_case_step():
    payload = {
        "records": [
            {"case": "case-a", "stepIndex": 1, "prompt": "A", "responseText": "baseline"},
            {"case": "case-a", "stepIndex": 2, "prompt": "B", "responseText": "current"},
        ]
    }

    index = report._build_case_index(payload)

    assert set(index) == {"case-a#1", "case-a#2"}
    assert report._extract_text(index["case-a#1"][0]) == "baseline"


def test_score_case_rewards_text_and_latency():
    score = report._score_case(
        {
            "responseText": "这是一个结构化回复，包含确认和下一步建议。",
            "thinkingText": "正在整理...",
            "elapsedMs": 1200,
            "turnObservability": {"toolCallCount": 1},
        }
    )

    assert score["correctness"] >= 1
    assert score["completeness"] >= 1
    assert score["naturalness"] >= 1
    assert score["actionability"] >= 1
    assert score["latency"] >= 1


def test_build_case_report_merges_baseline_current_and_candidates():
    baseline = {
        "case": "case-a",
        "stepIndex": 1,
        "prompt": "看看现在的方案",
        "responseText": "baseline reply",
        "elapsedMs": 1000,
    }
    current = {
        "case": "case-a",
        "stepIndex": 1,
        "prompt": "看看现在的方案",
        "responseText": "current reply",
        "elapsedMs": 800,
        "thinkingText": "正在读取当前方案并整理这次请求...",
    }
    candidate = {
        "case": "case-a",
        "stepIndex": 1,
        "prompt": "看看现在的方案",
        "responseText": "candidate reply",
        "elapsedMs": 600,
        "provider": "candidate-provider",
        "model": "candidate-model",
    }

    merged = report._build_case_report("case-a#1", baseline, current, {"candidate-a": candidate})

    assert merged["case"] == "case-a"
    assert merged["stepIndex"] == 1
    assert merged["baseline"]["reply"] == "baseline reply"
    assert merged["current"]["reply"] == "current reply"
    assert merged["candidates"][0]["name"] == "candidate-a"
    assert merged["candidates"][0]["reply"] == "candidate reply"
    assert merged["candidates"][0]["provider"] == "candidate-provider"


def test_provider_benchmark_records_can_be_flattened():
    payload = {
        "agent": [
            {
                "provider": "siliconflow",
                "model": "Kimi",
                "cases": [
                    {
                        "name": "case-a",
                        "run": 1,
                        "steps": [
                            {
                                "prompt": "看看现在的方案",
                                "text": "结构化回复",
                                "thinking": ["正在思考"],
                                "final_seconds": 1.23,
                                "first_message_seconds": 0.45,
                            }
                        ],
                    }
                ],
            }
        ]
    }

    records = report._extract_records(payload)

    assert len(records) == 1
    assert records[0]["case"] == "case-a"
    assert records[0]["provider"] == "siliconflow"
    assert records[0]["model"] == "Kimi"
    assert records[0]["elapsedMs"] == 1230
    assert records[0]["firstMessageMs"] == 450


def test_candidate_rows_expand_multiple_providers_from_one_benchmark_file():
    candidate_index = {
        "case-a#1": [
            {
                "case": "case-a",
                "stepIndex": 1,
                "candidateName": "provider-a",
                "responseText": "A reply",
            },
            {
                "case": "case-a",
                "stepIndex": 1,
                "candidateName": "provider-b",
                "responseText": "B reply",
            },
        ]
    }

    rows = report._candidate_rows_for_case({"models": candidate_index}, "case-a#1")

    assert set(rows) == {"provider-a", "provider-b"}
    assert rows["provider-a"]["responseText"] == "A reply"
    assert rows["provider-b"]["responseText"] == "B reply"
