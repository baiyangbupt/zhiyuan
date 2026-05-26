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


def test_score_case_flags_thin_preview_without_distribution_coverage():
    score = report._score_case(
        {
            "prompt": "看看当前方案里法学相关的机会",
            "responseText": "下面仅展示前 1 条示例：某大学-法学。下一步可以继续看。",
            "elapsedMs": 900,
        }
    )

    assert "thin_preview_distribution" in score["qualityViolations"]
    assert score["verdict"] == "fail"
    assert score["completeness"] < 4


def test_score_case_does_not_treat_confirm_guard_as_preview():
    score = report._score_case(
        {
            "prompt": "确认",
            "responseText": "上一轮只是职业方向和当前方案承接分析，没有待执行的方案动作。按这个方向看看方案怎么调时，我会先给预览再等你确认。",
            "elapsedMs": 900,
        }
    )

    assert "thin_preview_distribution" not in score["qualityViolations"]
    assert score["verdict"] != "fail"


def test_score_case_rewards_rich_preview_distribution_coverage():
    score = report._score_case(
        {
            "prompt": "看看当前方案",
            "responseText": (
                "方案志愿概况：\n"
                "- 区间分布：冲3 / 稳4 / 保3\n"
                "- 学校层次：公办、民办；专业热度：热门、计划数偏少\n"
                "- 代表样本：冲区代表 A大学-法学；稳区代表 B大学-财政学\n"
                "- 下一步可以继续按录取率或院校层次排序。"
            ),
            "elapsedMs": 1200,
        }
    )

    assert "thin_preview_distribution" not in score["qualityViolations"]
    assert set(score["distributionCoverage"]) >= {"tier_distribution", "school_level", "major_heat", "representative_samples"}
    assert score["verdict"] == "strong"


def test_score_case_flags_internal_user_visible_terms():
    score = report._score_case(
        {
            "prompt": "确认这个偏好",
            "responseText": "待确认偏好专业（level3）：法学。确认后写入 pending_intent_change。",
            "elapsedMs": 800,
        }
    )

    assert any(item.startswith("internal_terms:") for item in score["qualityViolations"])
    assert score["verdict"] == "fail"


def test_score_case_flags_pending_preview_worded_like_effective():
    score = report._score_case(
        {
            "prompt": "我倾向法学和财政学，但护理不要",
            "responseText": (
                "我已经把这次提到的想法整理成待确认内容了。\n\n"
                "- 把法学作为后续优先参考的专业方向。\n"
                "- 把护理学记成明确不考虑的内容，后面看候选和方案时都会按这个要求来。\n\n"
                "确认前不会正式生效，也不会直接改动当前方案。"
            ),
            "elapsedMs": 900,
        }
    )

    assert "pending_intent_effective_wording" in score["qualityViolations"]
    assert score["verdict"] == "fail"


def test_score_case_allows_conditional_pending_preview_wording():
    score = report._score_case(
        {
            "prompt": "我倾向法学和财政学，但护理不要",
            "responseText": (
                "我已经把这次提到的想法整理成待确认内容了。\n\n"
                "- 确认后，将把法学作为后续优先参考的专业方向。\n"
                "- 确认后，将把护理学作为明确不考虑的内容，后续查看候选和方案时会按这个要求作为参考。\n\n"
                "确认前不会正式生效，也不会直接改动当前方案。"
            ),
            "elapsedMs": 900,
        }
    )

    assert "pending_intent_effective_wording" not in score["qualityViolations"]


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
