import importlib.util
import json
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


def test_score_case_includes_semantic_router_shadow_from_observability():
    score = report._score_case(
        {
            "prompt": "财管会计审计怎么排优先级",
            "responseText": "这类专业可以从稳定性、考公适配和就业口径做优先级判断。",
            "elapsedMs": 900,
            "turnObservability": {
                "routingPath": "major_compare_fast_route",
                "semanticRouterShadow": {
                    "status": "success",
                    "frame": {
                        "taskLayer": "explore",
                        "verb": "compare",
                        "topic": "major",
                        "sideEffect": "readonly",
                    },
                },
            },
        }
    )

    assert score["semanticRouterShadow"]["status"] == "success"
    assert score["semanticRouterShadow"]["frame"]["taskLayer"] == "explore"
    assert score["semanticMappedRoute"] == "major_compare_fast_route"


def test_semantic_mapped_route_distinguishes_plan_preview_and_policy_explore():
    assert report._semantic_mapped_route_from_frame(
        {
            "taskLayer": "plan",
            "verb": "sort",
            "topic": "plan",
            "sideEffect": "preview",
        }
    ) == "plan_fast_route"
    assert report._semantic_mapped_route_from_frame(
        {
            "taskLayer": "explore",
            "verb": "explain",
            "topic": "policy",
            "sideEffect": "readonly",
        }
    ) == "full_agent"


def test_summarize_rows_counts_semantic_router_dimensions():
    rows = [
        {
            "score": {
                "verdict": "strong",
                "routingPath": "major_compare_fast_route",
                "expectedRoutingPath": "major_compare_fast_route",
                "semanticMappedRoute": "major_compare_fast_route",
                "semanticExpectation": {"matched": True},
                "semanticRouterShadow": {
                    "status": "success",
                    "frame": {
                        "taskLayer": "explore",
                        "verb": "compare",
                        "topic": "major",
                        "sideEffect": "readonly",
                    },
                },
            },
            "elapsedMs": 900,
        }
    ]

    summary = report._summarize_rows(rows)

    assert summary["semanticRouterSummary"]["status"] == {"success": 1}
    assert summary["semanticRouterSummary"]["taskLayer"] == {"explore": 1}
    assert summary["semanticRouterSummary"]["verb"] == {"compare": 1}
    assert summary["semanticRouterSummary"]["mappedRoute"] == {"major_compare_fast_route": 1}
    assert summary["semanticRouterSummary"]["expectedRouteComparison"] == {"match": 1}
    assert summary["semanticRouterSummary"]["currentRouteComparison"] == {"match": 1}
    assert summary["semanticRouterSummary"]["expectedFrameComparison"] == {"match": 1}


def test_score_case_marks_semantic_frame_mismatch():
    score = report._score_case(
        {
            "prompt": "一模二模差挺多，这个成绩波动填志愿咋看",
            "responseText": "先看成绩波动和志愿风险。",
            "expectedSemanticFrame": {
                "taskLayer": "explore",
                "topic": "score",
                "verb": "analyze",
                "sideEffect": "readonly",
                "minConfidence": 0.85,
            },
            "semanticRouterShadow": {
                "status": "success",
                "frame": {
                    "taskLayer": "explore",
                    "topic": "major",
                    "verb": "compare",
                    "sideEffect": "readonly",
                    "confidence": 0.72,
                },
            },
        }
    )

    assert score["semanticExpectation"]["matched"] is False
    assert "semantic_frame_mismatch" in ",".join(score["qualityViolations"])


def test_score_case_warns_without_failing_when_expected_semantic_frame_is_unverified():
    score = report._score_case(
        {
            "prompt": "一模二模差挺多，这个成绩波动填志愿咋看",
            "responseText": "先看成绩波动和志愿风险，确认位次后再决定冲稳保。",
            "expectedSemanticFrame": {
                "taskLayer": "explore",
                "topic": "score",
                "verb": "analyze",
                "sideEffect": "readonly",
                "minConfidence": 0.85,
            },
            "expectedSemanticFrameSource": "explicit",
            "semanticRouterShadow": {"status": "disabled"},
        }
    )

    assert score["semanticExpectation"]["matched"] is None
    assert score["qualityViolations"] == []
    assert "semantic_frame_unverified:disabled" in score["evaluationWarnings"]


def test_score_case_accepts_expected_semantic_frame_value_sets():
    score = report._score_case(
        {
            "prompt": "排名比分数靠谱吧，方案里要怎么看",
            "responseText": "可以用位次作为主参考，再结合分数线和录取率看方案风险。",
            "expectedSemanticFrame": {
                "taskLayer": "explore",
                "topic": "score",
                "verb": ["analyze", "explain"],
                "sideEffect": "readonly",
                "minConfidence": 0.85,
            },
            "semanticRouterShadow": {
                "status": "success",
                "frame": {
                    "taskLayer": "explore",
                    "topic": "score",
                    "verb": "explain",
                    "sideEffect": "readonly",
                    "confidence": 0.89,
                },
            },
        }
    )

    assert score["semanticExpectation"]["matched"] is True


def test_score_case_suppresses_unverified_warning_for_inferred_semantic_frame():
    score = report._score_case(
        {
            "prompt": "建筑城乡规划要不要美术基础",
            "responseText": "建筑学入学后课程有手绘训练，城乡规划相对少一些。可以继续问具体学校。",
            "expectedSemanticFrame": {
                "taskLayer": "explore",
                "topic": "major",
                "verb": "explain",
                "sideEffect": "readonly",
            },
            "expectedSemanticFrameSource": "inferred",
        }
    )

    assert "semantic_frame_unverified:missing" not in score["evaluationWarnings"]
    assert score["qualityViolations"] == []


def test_build_case_report_infers_semantic_expectation_from_score_profile_coverage():
    item = report._build_case_report(
        "score-case#1",
        None,
        {
            "case": "score-case",
            "stepIndex": 1,
            "prompt": "一模二模差挺多，这个成绩波动填志愿咋看",
            "responseText": "先看成绩波动、位次稳定性和志愿风险。",
            "coverage": ["release_3_0_3", "dialogue_derived", "score_profile"],
            "semanticRouterShadow": {
                "status": "success",
                "frame": {
                    "taskLayer": "explore",
                    "topic": "score",
                    "verb": "analyze",
                    "sideEffect": "readonly",
                    "confidence": 0.88,
                },
            },
        },
        {},
    )

    assert item["expectedSemanticFrame"]["taskLayer"] == "explore"
    assert item["expectedSemanticFrame"]["topic"] == "score"
    assert item["current"]["score"]["semanticExpectation"]["matched"] is True


def test_score_profile_semantic_expectation_takes_priority_over_risk_summary_coverage():
    item = report._build_case_report(
        "score-risk-case#1",
        None,
        {
            "case": "score-risk-case",
            "stepIndex": 1,
            "prompt": "分数刚压本科线，别给我画大饼",
            "responseText": "这类压线情况要先看位次、批次线和保底空间。",
            "coverage": ["release_3_0_3", "dialogue_derived", "score_profile", "batch_line", "risk_summary"],
            "semanticRouterShadow": {
                "status": "success",
                "frame": {
                    "taskLayer": "explore",
                    "topic": "score",
                    "verb": "analyze",
                    "sideEffect": "readonly",
                    "confidence": 0.88,
                },
            },
        },
        {},
    )

    assert item["expectedSemanticFrame"]["taskLayer"] == "explore"
    assert item["expectedSemanticFrame"]["topic"] == "score"
    assert item["current"]["score"]["semanticExpectation"]["matched"] is True


def test_special_plan_semantic_expectation_accepts_policy_query():
    item = report._build_case_report(
        "special-policy-case#1",
        None,
        {
            "case": "special-policy-case",
            "stepIndex": 1,
            "prompt": "四川那种专项批，如果没资格是不是就不能放",
            "responseText": "先按政策资格判断，没有资格就不应放进可报范围。",
            "coverage": ["release_3_0_3", "dialogue_derived", "eligibility_constraints", "special_plan", "plan_review"],
            "semanticRouterShadow": {
                "status": "success",
                "frame": {
                    "taskLayer": "explore",
                    "topic": "policy",
                    "verb": "query",
                    "sideEffect": "readonly",
                    "confidence": 0.9,
                },
            },
        },
        {},
    )

    assert item["expectedSemanticFrame"]["taskLayer"] == "explore"
    assert item["expectedSemanticFrame"]["topic"] == ["policy", "requirement"]
    assert "query" in item["expectedSemanticFrame"]["verb"]
    assert item["current"]["score"]["semanticExpectation"]["matched"] is True


def test_subject_combination_employment_semantic_expectation_accepts_career_topic():
    item = report._build_case_report(
        "subject-career-case#1",
        None,
        {
            "case": "subject-career-case",
            "stepIndex": 1,
            "prompt": "历史政治地理这个组合，就业别太窄咋选",
            "responseText": "可以从就业面、专业方向和升学路径看。",
            "coverage": [
                "release_3_0_3",
                "dialogue_derived",
                "score_profile",
                "subject_combination",
                "liberal_arts_employment",
            ],
            "semanticRouterShadow": {
                "status": "success",
                "frame": {
                    "taskLayer": "explore",
                    "topic": "career",
                    "verb": "recommend",
                    "sideEffect": "readonly",
                    "confidence": 0.85,
                },
            },
        },
        {},
    )

    assert item["expectedSemanticFrame"]["topic"] == ["score", "career", "major"]
    assert item["current"]["score"]["semanticExpectation"]["matched"] is True


def test_build_case_report_infers_intent_preview_semantic_expectation_from_coverage():
    item = report._build_case_report(
        "intent-case#1",
        None,
        {
            "case": "intent-case",
            "stepIndex": 1,
            "prompt": "会计审计还行，土木别要",
            "responseText": "确认前不会写入后续参考，我先给你看影响。",
            "coverage": [
                "release_3_0_3",
                "dialogue_derived",
                "major_preference",
                "soft_major_intent",
                "hard_major_constraint",
            ],
            "semanticRouterShadow": {
                "status": "success",
                "frame": {
                    "taskLayer": "intent",
                    "topic": "major",
                    "verb": "set_constraint",
                    "sideEffect": "preview",
                    "confidence": 0.86,
                },
            },
        },
        {},
    )

    assert item["expectedSemanticFrame"]["taskLayer"] == "intent"
    assert item["expectedSemanticFrame"]["sideEffect"] == "preview"
    assert item["current"]["score"]["semanticExpectation"]["matched"] is True


def test_build_case_report_infers_plan_operation_semantic_expectation_from_coverage():
    item = report._build_case_report(
        "operation-case#1",
        None,
        {
            "case": "operation-case",
            "stepIndex": 1,
            "prompt": "按录取率从低到高排下，先看预览",
            "responseText": "这是排序预览，确认后才会更新导出顺序。",
            "coverage": ["release_3_0_3", "dialogue_derived", "plan_operations", "sort_ordered_plan"],
            "semanticRouterShadow": {
                "status": "success",
                "frame": {
                    "taskLayer": "plan",
                    "topic": "plan",
                    "verb": "sort",
                    "sideEffect": "preview",
                    "confidence": 0.91,
                },
            },
        },
        {},
    )

    assert item["expectedSemanticFrame"]["taskLayer"] == "plan"
    assert item["expectedSemanticFrame"]["sideEffect"] == "preview"
    assert item["current"]["score"]["semanticExpectation"]["matched"] is True


def test_score_case_marks_empty_response_as_failed_verdict():
    score = report._score_case(
        {
            "prompt": "高考出分后是不是要重做一版",
            "responseText": "",
            "elapsedMs": 2100,
        }
    )

    assert score["qualityViolations"] == ["empty_response"]
    assert score["verdict"] == "fail"


def test_score_case_marks_metrics_without_response_text_as_unscored():
    score = report._score_case(
        {
            "prompt": "看看现在的方案",
            "elapsedMs": 2100,
            "turnObservability": {
                "toolCalls": [{"name": "execute_plan_action", "actionFamily": "query_state"}],
            },
        }
    )

    assert score["qualityViolations"] == []
    assert "missing_response_text:run_with_keep_response_text" in score["evaluationWarnings"]
    assert score["verdict"] == "unscored"


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


def test_score_case_does_not_apply_distribution_gate_to_empty_candidate_result():
    score = report._score_case(
        {
            "prompt": "候选里还有没有更稳一点的会计审计，别直接加",
            "responseText": (
                "候选里暂时没有筛到符合“专业:会计学、审计学”的机会。"
                "这次只是查询候选，不会直接加入方案。"
                "我已按这几个具体专业分别查过，当前候选池没有返回可用结果；"
                "下一步可以换成更宽的专业类、只看当前方案里的相近志愿。"
            ),
            "elapsedMs": 900,
        }
    )

    assert "thin_preview_distribution" not in score["qualityViolations"]
    assert score["verdict"] != "fail"


def test_score_case_does_not_apply_distribution_gate_to_empty_plan_result():
    score = report._score_case(
        {
            "prompt": "按推荐系数排一下，但别直接动",
            "responseText": (
                "当前还没有正式方案，暂时没法按推荐系数预览排序效果。"
                "你可以先让我生成一套志愿方案，生成之后再随时调整排序。"
            ),
            "elapsedMs": 900,
        }
    )

    assert "thin_preview_distribution" not in score["qualityViolations"]
    assert score["verdict"] != "fail"


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


def test_score_case_does_not_apply_distribution_gate_to_point_mutation_preview():
    score = report._score_case(
        {
            "prompt": "把青岛城市学院的国际经济与贸易改到第3位",
            "responseText": (
                "预览如下：\n"
                "- 志愿：青岛城市学院 · 国际经济与贸易\n"
                "- 当前位置：当前第 36 位\n"
                "- 目标位置：第 3 位\n"
                "需要你确认后才会执行。"
            ),
            "elapsedMs": 1200,
            "turnObservability": {
                "toolCalls": [
                    {
                        "name": "execute_plan_action",
                        "actionFamily": "move_unit",
                    }
                ]
            },
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


def test_score_case_allows_if_you_confirm_pending_preview_wording():
    score = report._score_case(
        {
            "prompt": "会计审计可以 土木别要",
            "responseText": (
                "我先把你这次的想法整理成待确认偏好。\n\n"
                "- 如果你确认，会把会计学、审计学作为后续参考。\n"
                "- 如果你确认，会把土木工程作为明确不考虑的内容。\n\n"
                "确认前不会写入后续参考，也不会直接改动当前方案。\n\n"
                "**下一步**\n- 如果确认要作为后续参考，直接回复“确认这个偏好”。"
            ),
            "elapsedMs": 900,
        }
    )

    assert "pending_intent_effective_wording" not in score["qualityViolations"]


def test_score_case_allows_if_you_want_pending_preview_wording():
    score = report._score_case(
        {
            "prompt": "新闻新媒体能不能当备选，不想太虚",
            "responseText": (
                "新闻传播类可以作为备选，但要看你能不能接受内容生产、传播运营和岗位波动。\n\n"
                "如果你想，我可以把它先记成待确认偏好，确认前不会写入后续参考。"
            ),
            "elapsedMs": 900,
        }
    )

    assert "pending_intent_effective_wording" not in score["qualityViolations"]


def test_score_case_allows_readonly_reference_boundary_wording():
    score = report._score_case(
        {
            "prompt": "嗯那就这样",
            "responseText": (
                "好的，先按刚才的专业对比结论作为参考。\n\n"
                "这轮没有待确认的偏好或方案动作，我不会改动方案。"
            ),
            "elapsedMs": 900,
        }
    )

    assert "pending_intent_effective_wording" not in score["qualityViolations"]


def test_score_case_does_not_apply_distribution_gate_to_career_short_prompt_without_plan():
    score = report._score_case(
        {
            "case": "303-open-quality-career-study-vs-employment-lazy",
            "coverage": ["career_short_prompt"],
            "prompt": "读研和稳定就业哪个更实际点，先别改偏好",
            "responseText": (
                "**分析结论**\n"
                "- 当前还没有成型排序方案，暂时不能判断稳定就业和读研在方案里的承接强弱。\n\n"
                "**方案承接**\n"
                "- 稳定就业更适合比较就业确定性、岗位稳定性和路径清晰度。\n"
                "- 深造方向更适合重点比较培养平台、升学通道和长期学习投入。\n\n"
                "**本次边界**\n"
                "- 这次只是方向分析，不会自动修改偏好或方案。"
            ),
            "elapsedMs": 900,
        }
    )

    assert "thin_preview_distribution" not in score["qualityViolations"]


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


def test_case_definitions_attach_flow_coverage_and_latency_budget(tmp_path):
    case_file = tmp_path / "cases.json"
    case_file.write_text(
        json.dumps(
            [
                {
                    "name": "case-a",
                    "sessionId": "17",
                    "flow": ["plan"],
                    "coverage": ["plan_fast_route", "sort_ordered_plan"],
                    "assertPlanStyle": True,
                    "prompts": [
                        {
                            "prompt": "按院校层次排序",
                            "warnElapsedSeconds": 3,
                            "maxElapsedSeconds": 5,
                            "assertContains": ["排序", "确认"],
                            "expectedKeyPoints": ["说明导出顺序影响", "说明审查需要重新看"],
                            "qualityFocus": ["preview_confirm_boundary"],
                        }
                    ],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    definitions = report._merge_case_definition_indexes([str(case_file)])
    merged = report._build_case_report(
        "case-a#1",
        None,
        {
            "case": "case-a",
            "stepIndex": 1,
            "prompt": "按院校层次排序",
            "responseText": "排序预览：确认后会实际改变导出顺序，审查会进入待重新审查。",
            "elapsedMs": 4200,
            "turnObservability": {
                "actionFamilies": ["sort_ordered_plan"],
                "toolCalls": [{"name": "execute_plan_action", "actionFamily": "sort_ordered_plan"}],
            },
        },
        {},
        definitions,
    )

    assert merged["flow"] == ["plan"]
    assert merged["coverage"] == ["plan_fast_route", "sort_ordered_plan"]
    assert merged["expectedRoutingPath"] is None
    assert merged["expectedActionFamily"] == "sort_ordered_plan"
    assert merged["latencyBudget"] == {"warnElapsedMs": 3000, "maxElapsedMs": 5000}
    assert merged["assertions"] == {"assertContains": ["排序", "确认"]}
    assert merged["qualityExpectations"] == {
        "expectedKeyPoints": ["说明导出顺序影响", "说明审查需要重新看"],
        "qualityFocus": ["preview_confirm_boundary"],
    }
    assert "latency_warn_exceeded" in ",".join(merged["current"]["score"]["evaluationWarnings"])
    assert "missing_route_observability" not in ",".join(merged["current"]["score"]["evaluationWarnings"])


def test_case_definitions_support_defaults_object_payload(tmp_path):
    case_file = tmp_path / "cases.json"
    case_file.write_text(
        json.dumps(
            {
                "defaults": {
                    "flow": ["explore"],
                    "coverage": ["release_3_0_3", "dialogue_derived"],
                    "assertPlanStyle": True,
                    "promptDefaults": {
                        "assertNotContains": ["payload"],
                        "forbiddenPatterns": ["内部字段"],
                        "qualityFocus": ["user_language"],
                        "warnElapsedSeconds": 30,
                    },
                },
                "cases": [
                    {
                        "name": "case-a",
                        "sessionId": "17",
                        "flow": ["plan"],
                        "coverage": ["plan_status"],
                        "prompts": [
                            {
                                "prompt": "这方案咋样",
                                "assertContainsAny": ["方案"],
                                "expectedKeyPoints": ["方案", "下一步"],
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    definitions = report._merge_case_definition_indexes([str(case_file)])

    assert definitions["case-a#1"]["flow"] == ["explore", "plan"]
    assert definitions["case-a#1"]["coverage"] == ["release_3_0_3", "dialogue_derived", "plan_status"]
    assert definitions["case-a#1"]["assertPlanStyle"] is True
    assert definitions["case-a#1"]["latencyBudget"] == {"warnElapsedMs": 30000}
    assert definitions["case-a#1"]["assertions"] == {
        "assertContainsAny": ["方案"],
        "assertNotContains": ["payload"],
    }
    assert definitions["case-a#1"]["qualityExpectations"] == {
        "expectedKeyPoints": ["方案", "下一步"],
        "qualityFocus": ["user_language"],
        "forbiddenPatterns": ["内部字段"],
    }


def test_case_definitions_infer_confirm_routes_from_prompt_and_coverage(tmp_path):
    case_file = tmp_path / "cases.json"
    case_file.write_text(
        json.dumps(
            [
                {
                    "name": "intent-confirm",
                    "sessionId": "880203",
                    "flow": ["intent", "confirm"],
                    "coverage": ["soft_major_intent", "hard_major_constraint"],
                    "prompts": [{"prompt": "确认这个偏好"}],
                },
                {
                    "name": "no-pending",
                    "sessionId": "880102",
                    "flow": ["confirm_guard"],
                    "coverage": ["major_compare", "school_major_lookup"],
                    "prompts": [
                        {
                            "prompt": "确认",
                            "coverage": ["no_pending_guard"],
                            "expectedRoutingPath": "plan_confirmation_guard_no_pending",
                            "expectedNoAction": True,
                        }
                    ],
                },
                {
                    "name": "readonly-closure",
                    "sessionId": "880103",
                    "flow": ["explore", "confirm_guard"],
                    "coverage": ["major_compare"],
                    "prompts": [
                        {
                            "prompt": "嗯那就这样",
                            "coverage": ["readonly_closure_ack", "readonly_no_pending_intent"],
                            "expectedNoAction": True,
                        }
                    ],
                },
                {
                    "name": "readonly-confirm",
                    "sessionId": "17",
                    "flow": ["explore", "plan"],
                    "coverage": ["career_explore", "readonly_no_workspace_card", "no_pending_intent"],
                    "prompts": [{"prompt": "确认"}],
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    definitions = report._merge_case_definition_indexes([str(case_file)])

    assert definitions["intent-confirm#1"]["expectedRoutingPath"] == "direct_pending_intent_confirm"
    assert definitions["intent-confirm#1"]["expectedActionFamily"] == "apply_selected_intents"
    assert definitions["no-pending#1"]["expectedRoutingPath"] == "plan_confirmation_guard_no_pending"
    assert "expectedActionFamily" not in definitions["no-pending#1"]
    assert definitions["no-pending#1"]["expectedNoAction"] is True
    assert definitions["readonly-closure#1"]["expectedRoutingPath"] == "readonly_closure_ack"
    assert "expectedActionFamily" not in definitions["readonly-closure#1"]
    assert definitions["readonly-closure#1"]["expectedNoAction"] is True
    assert definitions["readonly-confirm#1"]["expectedRoutingPath"] == "plan_confirmation_guard_no_pending"
    assert "expectedActionFamily" not in definitions["readonly-confirm#1"]


def test_score_case_treats_legacy_fast_route_mismatch_as_warning_not_quality_failure():
    score = report._score_case(
        {
            "prompt": "按院校层次排序",
            "responseText": "排序预览：确认后再执行。",
            "elapsedMs": 900,
            "expectedRoutingPath": "plan_fast_route",
            "expectedActionFamily": "sort_ordered_plan",
            "routingPath": "full_agent",
            "turnObservability": {
                "actionFamilies": ["query_state"],
                "toolCalls": [{"name": "plan_next_action", "actionFamily": "query_state"}],
            },
        }
    )

    assert "route_mismatch:plan_fast_route!=full_agent" not in score["qualityViolations"]
    assert "optimization_route_not_matched:plan_fast_route!=full_agent" in score["evaluationWarnings"]
    assert any(item.startswith("action_family_mismatch:") for item in score["qualityViolations"])
    assert score["verdict"] == "fail"


def test_score_case_flags_strict_route_mismatch():
    score = report._score_case(
        {
            "prompt": "确认",
            "responseText": "这轮没有待确认的偏好或方案动作，我不会改动方案。",
            "elapsedMs": 900,
            "expectedRoutingPath": "plan_confirmation_guard_no_pending",
            "expectedNoAction": True,
            "routingPath": "full_agent",
            "turnObservability": {"actionFamilies": [], "toolCalls": []},
        }
    )

    assert "route_mismatch:plan_confirmation_guard_no_pending!=full_agent" in score["qualityViolations"]
    assert score["verdict"] == "fail"


def test_score_case_flags_unexpected_action_when_none_expected():
    score = report._score_case(
        {
            "prompt": "嗯那就这样",
            "responseText": "这轮没有待确认的偏好或方案动作，我不会改动方案。",
            "elapsedMs": 900,
            "expectedRoutingPath": "plan_confirmation_guard_no_pending",
            "expectedNoAction": True,
            "routingPath": "plan_confirmation_guard_no_pending",
            "turnObservability": {
                "actionFamilies": ["compare_majors"],
                "toolCalls": [{"name": "compare_majors", "actionFamily": "compare_majors"}],
            },
        }
    )

    assert "unexpected_action:compare_majors" in score["qualityViolations"]
    assert score["verdict"] == "fail"


def test_score_case_treats_no_action_ack_as_complete_when_expected():
    score = report._score_case(
        {
            "prompt": "嗯那就这样",
            "responseText": (
                "好的，先按刚才的专业对比结论作为参考。\n\n"
                "这轮没有待确认的偏好或方案动作，我不会改动方案。"
            ),
            "elapsedMs": 900,
            "expectedRoutingPath": "readonly_closure_ack",
            "expectedNoAction": True,
            "routingPath": "readonly_closure_ack",
            "turnObservability": {"actionFamilies": [], "toolCalls": []},
        }
    )

    assert score["completeness"] >= 4
    assert score["verdict"] == "strong"


def test_score_case_uses_tool_name_as_action_observability_alias():
    score = report._score_case(
        {
            "prompt": "当前方案对体制内方向承接怎么样",
            "responseText": "分析结论：当前方案承接偏弱，方案内约有2个相关志愿。下一步可以继续展开。",
            "elapsedMs": 900,
            "expectedActionFamily": "analyze_current_career_direction",
            "turnObservability": {
                "toolCalls": [{"name": "analyze_current_career_direction"}],
            },
        }
    )

    assert "missing_action_observability:analyze_current_career_direction" not in score["evaluationWarnings"]
    assert not any(item.startswith("action_family_mismatch:") for item in score["qualityViolations"])
    assert score["route"] >= 4


def test_score_case_accepts_multi_major_tool_as_major_compare_observability_alias():
    score = report._score_case(
        {
            "prompt": "财管会计审计这几个怎么排优先级",
            "responseText": (
                "默认优先级：会计学 > 财务管理 > 审计学。\n\n"
                "会计学就业面最宽，企业财务、金融机构和考公岗位口径更大；"
                "财务管理偏资金运作和管理决策；审计学路径更专，偏事务所、内审和风控。\n\n"
                "如果你更看重稳定和考公，可以先会计，再财管，最后审计；愿意补充分数和就业倾向后，我可以继续细化。"
            ),
            "elapsedMs": 900,
            "expectedActionFamily": "compare_majors",
            "turnObservability": {
                "toolCalls": [{"name": "compare_major_options"}],
            },
            "qualityExpectations": {
                "expectedKeyPoints": ["财务管理", "会计", "审计", "就业路径", "排序建议"],
                "qualityFocus": ["rich_decision_basis", "actionable_next_step"],
            },
        }
    )

    assert "missing_action_observability:compare_majors" not in score["evaluationWarnings"]
    assert not any(item.startswith("missing_expected_keypoint:") for item in score["evaluationWarnings"])
    assert not any(item.startswith("action_family_mismatch:") for item in score["qualityViolations"])
    assert score["route"] >= 4


def test_score_case_does_not_require_readonly_boundary_for_pure_explore_information_question():
    score = report._score_case(
        {
            "prompt": "建筑城乡规划要不要美术基础",
            "responseText": (
                "录取门槛上，多数学校不强制要求美术基础。\n\n"
                "建筑学入学后课程里会有建筑美术、设计表达和手绘训练；"
                "城乡规划更偏总体规划、详细规划、法规和空间布局，美术压力相对低。\n\n"
                "如果完全零基础，可以优先看城乡规划，或提前补一点素描和快速表现。可以直接问我具体学校在你省的情况。"
            ),
            "elapsedMs": 900,
            "coverage": ["major_preference", "architecture_major", "skill_requirement"],
            "qualityExpectations": {
                "expectedKeyPoints": ["建筑学", "城乡规划", "美术基础", "学习要求", "下一步"],
                "qualityFocus": ["readonly_boundary", "rich_decision_basis", "actionable_next_step"],
            },
        }
    )

    assert "missing_quality_focus:readonly_boundary" not in score["evaluationWarnings"]
    assert not any(item.startswith("missing_expected_keypoint:") for item in score["evaluationWarnings"])
    assert not any(item.startswith("missing_quality_focus:rich_decision_basis") for item in score["evaluationWarnings"])


def test_score_case_still_requires_readonly_boundary_for_plan_adjacent_question():
    score = report._score_case(
        {
            "prompt": "这版方案是不是太冲了，先别动",
            "responseText": "当前方案冲区偏多，保底不足。下一步可以继续看保底补齐。",
            "elapsedMs": 900,
            "coverage": ["plan_review_strategy", "plan_analysis"],
            "qualityExpectations": {
                "qualityFocus": ["readonly_boundary", "rich_decision_basis"],
            },
        }
    )

    assert "missing_quality_focus:readonly_boundary" in score["evaluationWarnings"]
    assert score["verdict"] == "needs_review"


def test_score_case_flags_latency_budget_hard_failure():
    score = report._score_case(
        {
            "prompt": "确认",
            "responseText": "没有上一轮待确认动作。",
            "elapsedMs": 6200,
            "latencyBudget": {"maxElapsedMs": 5000},
        }
    )

    assert "latency_max_exceeded:6200>5000" in score["qualityViolations"]
    assert score["verdict"] == "fail"


def test_score_case_flags_case_specific_forbidden_patterns():
    score = report._score_case(
        {
            "prompt": "我倾向会计学和审计学，但土木工程不要",
            "responseText": "已整理你的要求，候选结果收紧后可以继续查看。",
            "elapsedMs": 900,
            "qualityExpectations": {
                "forbiddenPatterns": ["候选结果收紧"],
            },
        }
    )

    assert "forbidden_pattern:候选结果收紧" in score["qualityViolations"]
    assert score["verdict"] == "fail"


def test_score_case_marks_missing_expected_keypoints_for_review():
    score = report._score_case(
        {
            "prompt": "按院校层次排序",
            "responseText": "会按院校层次重新排序当前方案。需要你确认后才会执行。",
            "elapsedMs": 900,
            "qualityExpectations": {
                "expectedKeyPoints": ["导出顺序影响", "审查需要重新看"],
            },
        }
    )

    assert "missing_expected_keypoint:导出顺序影响" in score["evaluationWarnings"]
    assert "missing_expected_keypoint:审查需要重新看" in score["evaluationWarnings"]
    assert score["verdict"] == "needs_review"


def test_score_case_accepts_expected_keypoint_aliases():
    score = report._score_case(
        {
            "prompt": "按院校层次排序",
            "responseText": (
                "会按院校层次重新排序当前方案。\n\n"
                "排序方式：排名靠前的排在前面。\n\n"
                "执行影响：会改变导出内容，并让审查状态进入待重新审查。\n\n"
                "需要你确认后才会执行。"
            ),
            "elapsedMs": 900,
            "turnObservability": {
                "actionFamilies": ["sort_ordered_plan"],
                "toolCalls": [{"name": "execute_plan_action", "actionFamily": "sort_ordered_plan"}],
            },
            "qualityExpectations": {
                "expectedKeyPoints": ["说明导出顺序影响", "说明审查需要重新看"],
            },
        }
    )

    assert not any(item.startswith("missing_expected_keypoint:") for item in score["evaluationWarnings"])
    assert "forbidden_pattern" not in ",".join(score["qualityViolations"])


def test_score_case_accepts_expected_keypoint_groups():
    score = report._score_case(
        {
            "prompt": "候选里还有没有更稳一点的会计审计，别直接加",
            "responseText": (
                "候选里暂时没有筛到符合“专业:会计学、审计学”的机会。"
                "我已按这几个具体专业分别查过，当前候选池没有返回可用结果；"
                "下一步可以换成更宽的专业类，或只看当前方案里的相近志愿。"
            ),
            "elapsedMs": 900,
            "qualityExpectations": {
                "expectedKeyPointGroups": [
                    {"label": "命中或空结果说明", "any": ["共命中", "暂时没有筛到", "没有返回可用结果"]},
                    {"label": "示例或替代查看方式", "any": ["示例", "更宽的专业类", "当前方案里的相近志愿"]},
                ]
            },
        }
    )

    assert not any(item.startswith("missing_expected_keypoint_group:") for item in score["evaluationWarnings"])


def test_score_case_applies_quality_focus_warnings():
    score = report._score_case(
        {
            "prompt": "这方案咋样",
            "responseText": "方案有风险，可以继续看。",
            "elapsedMs": 900,
            "qualityExpectations": {
                "qualityFocus": [
                    "readonly_boundary",
                    "rich_decision_basis",
                    "multi_distribution",
                    "actionable_next_step",
                ],
                "minTextLengthWarn": 80,
            },
        }
    )

    assert "missing_quality_focus:readonly_boundary" in score["evaluationWarnings"]
    assert any(item.startswith("missing_quality_focus:rich_decision_basis") for item in score["evaluationWarnings"])
    assert "text_too_short:12<80" in score["evaluationWarnings"]
    assert score["verdict"] == "needs_review"


def test_score_case_passes_quality_focus_when_reply_is_rich_and_bounded():
    score = report._score_case(
        {
            "prompt": "这版是不是太冲了，先别动",
            "responseText": (
                "**分析结论**\n"
                "- 当前方案冲区偏多，保底数量有缺口。\n\n"
                "**关键依据**\n"
                "- 冲稳保：冲66 / 稳28 / 保0。\n"
                "- 学校层次：公办和民办都有，前排以冲区为主。\n"
                "- 代表样本：前排有青岛城市学院相关志愿。\n\n"
                "**本次边界**\n"
                "- 这次只是分析，不会改动当前方案。\n\n"
                "**下一步**\n"
                "- 可以继续看保底补齐，或让我先给调稳预览。"
            ),
            "elapsedMs": 900,
            "qualityExpectations": {
                "qualityFocus": [
                    "readonly_boundary",
                    "rich_decision_basis",
                    "multi_distribution",
                    "actionable_next_step",
                    "user_language",
                ],
                "minTextLengthWarn": 120,
            },
        }
    )

    assert not any(item.startswith("missing_quality_focus:") for item in score["evaluationWarnings"])
    assert not any(item.startswith("text_too_short:") for item in score["evaluationWarnings"])
    assert score["verdict"] == "strong"


def test_score_case_quality_focus_flags_system_language():
    score = report._score_case(
        {
            "prompt": "法学和财政学哪个更适合",
            "responseText": "当前没有个性化量化评分，先按系统分数之外的维度看。下一步可以继续。",
            "elapsedMs": 900,
            "qualityExpectations": {
                "qualityFocus": ["user_language"],
            },
        }
    )

    assert "missing_quality_focus:user_language" in score["evaluationWarnings"]
    assert score["verdict"] == "needs_review"


def test_score_case_quality_focus_flags_unnecessary_english_mixed_wording():
    score = report._score_case(
        {
            "prompt": "体制内稳定就业承接怎么样",
            "responseText": "学历门槛 increasingly 要硕士，baseline 是本科。下一步可以继续看方案。",
            "elapsedMs": 900,
            "qualityExpectations": {
                "qualityFocus": ["user_language"],
            },
        }
    )

    assert "missing_quality_focus:user_language" in score["evaluationWarnings"]
    assert score["verdict"] == "needs_review"


def test_expected_keypoint_next_step_accepts_user_friendly_followup_wording():
    score = report._score_case(
        {
            "prompt": "大城市就业和考编哪个更现实",
            "responseText": "可以告诉我你的省份、分数和选科，我再继续判断哪条路更现实。",
            "elapsedMs": 900,
            "qualityExpectations": {
                "expectedKeyPoints": ["下一步"],
                "qualityFocus": ["actionable_next_step"],
            },
        }
    )

    assert not any(item.startswith("missing_expected_keypoint:下一步") for item in score["evaluationWarnings"])
    assert not any(item == "missing_quality_focus:actionable_next_step" for item in score["evaluationWarnings"])


def test_summarize_reports_groups_quality_by_scenario_and_coverage():
    reports = [
        {
            "case": "case-a",
            "flow": ["plan"],
            "coverage": ["plan_fast_route"],
            "current": {
                "reply": "方案概况：区间分布：冲3 / 稳4 / 保3。学校层次：公办。代表样本：A大学。下一步可以审查。",
                "elapsedMs": 1200,
                "score": {
                    "verdict": "strong",
                    "correctness": 5,
                    "completeness": 5,
                    "naturalness": 4,
                    "actionability": 5,
                    "latency": 5,
                    "structure": 4,
                    "route": 4,
                    "distributionCoverage": ["tier_distribution", "school_level", "representative_samples"],
                    "qualityViolations": [],
                    "evaluationWarnings": [],
                    "routingPath": "plan_fast_route",
                    "actionFamilies": ["query_state"],
                    "toolNames": ["execute_plan_action"],
                },
            },
            "baseline": {"score": {"verdict": "needs_review"}},
            "candidates": [
                {
                    "name": "candidate-a",
                    "provider": "provider-a",
                    "model": "model-a",
                    "elapsedMs": 1500,
                    "score": {
                        "verdict": "needs_review",
                        "correctness": 4,
                        "completeness": 3,
                        "naturalness": 4,
                        "actionability": 4,
                        "latency": 5,
                        "structure": 3,
                        "route": 4,
                        "distributionCoverage": ["tier_distribution"],
                        "qualityViolations": [],
                        "evaluationWarnings": ["missing_case_metadata"],
                    },
                }
            ],
        }
    ]

    summary = report._summarize_reports(reports)

    assert summary["totalCases"] == 1
    assert summary["current"]["verdicts"] == {"strong": 1}
    assert summary["scenarioSummary"]["plan"]["verdicts"] == {"strong": 1}
    assert summary["coverageSummary"]["plan_fast_route"]["count"] == 1
    assert summary["candidateSummary"]["provider-a/model-a"]["verdicts"] == {"needs_review": 1}
    assert summary["baselineComparison"] == {"improved": 1, "same": 0, "regressed": 0, "incomparable": 0}
    assert summary["acceptance"]["passedHardGates"] is True


def test_render_markdown_detail_includes_full_reply_and_review_checklist():
    report_item = {
        "case": "case-a",
        "stepIndex": 1,
        "flow": ["plan"],
        "coverage": ["plan_fast_route", "preview_confirm_boundary"],
        "prompt": "把A大学的法学改到第3位",
        "sessionId": "17",
        "expectedRoutingPath": "plan_fast_route",
        "expectedActionFamily": "move_unit",
        "latencyBudget": {"warnElapsedMs": 3000},
        "assertions": {"assertContains": ["确认"]},
        "qualityExpectations": {"expectedKeyPoints": ["说明位置变化"]},
        "current": {
            "reply": (
                "已定位到 A大学-法学，当前在第8位，会移动到第3位。\n\n"
                "执行后会改变方案顺序和导出顺序，并让审查状态进入待重新审查。\n"
                "需要你确认后才会执行。"
            ),
            "elapsedMs": 1200,
            "firstMessageMs": 100,
            "finalMessageMs": 300,
            "score": {
                "verdict": "strong",
                "correctness": 5,
                "completeness": 5,
                "naturalness": 4,
                "actionability": 5,
                "structure": 4,
                "latency": 5,
                "route": 5,
                "distributionCoverage": ["quantity_space"],
                "qualityViolations": [],
                "evaluationWarnings": [],
                "routingPath": "plan_fast_route",
                "actionFamilies": ["move_unit"],
                "toolNames": ["execute_plan_action"],
            },
        },
        "baseline": {"reply": "会移动。", "score": {"verdict": "needs_review"}},
        "candidates": [],
    }
    summary = report._summarize_reports([report_item])

    markdown = report._render_markdown_detail([report_item], summary)

    assert "## Case Details" in markdown
    assert "把A大学的法学改到第3位" in markdown
    assert "已定位到 A大学-法学" in markdown
    assert "| 正确性 | 5 |" in markdown
    assert "人工复核清单" in markdown
    assert "expectedKeyPoints" in markdown


def test_full_agent_tool_trial_issue_detects_repeated_slow_tools():
    item = report._build_case_report(
        "slow-plan#1",
        None,
        {
            "case": "slow-plan",
            "stepIndex": 1,
            "prompt": "帮我审查后顺便调稳一点，先看看怎么动",
            "responseText": "还在整理方案审查和调整建议。",
            "elapsedMs": 62_000,
            "firstMessageMs": 15_000,
            "coverage": ["plan_review", "move_ordered_unit"],
            "expectedRoutingPath": "plan_fast_route",
            "turnObservability": {
                "routingPath": "full_agent",
                "toolCallCount": 4,
                "routeDecision": {
                    "route": "plan",
                    "toolTrial": {
                        "toolNames": [
                            "query_volunteer_plan",
                            "plan_next_action",
                            "query_volunteer_plan",
                            "execute_plan_action",
                        ],
                        "toolNameCounts": {
                            "query_volunteer_plan": 2,
                            "plan_next_action": 1,
                            "execute_plan_action": 1,
                        },
                        "repeatedToolNames": ["query_volunteer_plan"],
                        "hasRepeatedToolCalls": True,
                        "hasToolCalls": True,
                    },
                },
            },
        },
        {},
    )

    issue = item["current"]["fullAgentToolTrialIssue"]
    summary = report._summarize_reports([item])

    assert issue["caseId"] == "slow-plan#1"
    assert issue["actualRoutingPath"] == "full_agent"
    assert issue["repeatedToolNames"] == ["query_volunteer_plan"]
    assert "repeated_tool_calls" in issue["issueTypes"]
    assert "very_slow_full_agent" in issue["issueTypes"]
    assert "missing_progress_for_long_task" in issue["issueTypes"]
    assert "expected_route_mismatch_full_agent" in issue["issueTypes"]
    assert summary["fullAgentToolTrialIssues"]["count"] == 1
    assert summary["fullAgentToolTrialIssues"]["slowOrTimeoutCount"] == 1
    assert summary["fullAgentToolTrialIssues"]["missingProgressCount"] == 1
    assert summary["fullAgentToolTrialIssues"]["byRepeatedTool"] == {"query_volunteer_plan": 1}


def test_full_agent_tool_trial_issue_reports_interrupted_agent_node():
    item = report._build_case_report(
        "timeout-intent#1",
        None,
        {
            "case": "timeout-intent",
            "stepIndex": 1,
            "prompt": "医学护理这些别碰，财会还能接受，先看看影响",
            "responseText": "这次分析耗时有点长，我先暂停在这里。",
            "elapsedMs": 180_000,
            "firstMessageMs": 3_000,
            "turnObservability": {
                "routingPath": "full_agent",
                "routeDecision": {
                    "fallbackReason": "agent_run_interrupted",
                    "agentRun": {
                        "failedNode": "ModelRequestNode",
                        "failedNodeElapsedMs": 180000,
                        "nodeTimings": [
                            {
                                "index": 1,
                                "node": "ModelRequestNode",
                                "durationMs": 180000,
                                "status": "interrupted",
                            }
                        ],
                    },
                },
            },
        },
        {},
    )

    issue = item["current"]["fullAgentToolTrialIssue"]

    assert issue["agentRun"]["failedNode"] == "ModelRequestNode"
    assert "agent_run_interrupted" in issue["issueTypes"]
    assert "first_model_request_or_final_generation_interrupted" in issue["issueTypes"]
    assert "very_slow_full_agent" in issue["issueTypes"]


def test_full_agent_tool_trial_issue_reports_slow_successful_agent_node():
    item = report._build_case_report(
        "slow-model#1",
        None,
        {
            "case": "slow-model",
            "stepIndex": 1,
            "prompt": "孩子不想当老师，师范是不是都别要",
            "responseText": "可以先区分师范类和非师范就业方向。",
            "elapsedMs": 95_000,
            "firstMessageMs": 3_000,
            "turnObservability": {
                "routingPath": "full_agent",
                "routeDecision": {
                    "agentRun": {
                        "completed": True,
                        "firstToolCallAtMs": None,
                        "nodeTimings": [
                            {
                                "index": 1,
                                "node": "ModelRequestNode",
                                "durationMs": 94_000,
                                "status": "success",
                            }
                        ],
                    },
                    "toolTrial": {
                        "toolNames": [],
                        "toolNameCounts": {},
                        "repeatedToolNames": [],
                        "hasToolCalls": False,
                    },
                },
            },
        },
        {},
    )

    issue = item["current"]["fullAgentToolTrialIssue"]

    assert issue["slowestAgentNode"]["node"] == "ModelRequestNode"
    assert "slow_agent_node" in issue["issueTypes"]
    assert "very_slow_agent_node" in issue["issueTypes"]
    assert "slow_before_first_tool_or_final_generation" in issue["issueTypes"]


def test_full_agent_tool_trial_issue_synthesizes_tool_sequence_from_observability():
    record = {
        "case": "tool-sequence",
        "stepIndex": 1,
        "prompt": "当前方案对考公有什么支撑和短板",
        "responseText": "当前方案对考公方向承接一般。",
        "elapsedMs": 12_000,
        "thinkingText": "正在读取方案并整理职业方向承接...",
        "turnObservability": {
            "routingPath": "full_agent",
            "toolCalls": [
                {"name": "analyze_current_career_direction"},
                {"name": "query_volunteer_plan"},
                {"name": "query_volunteer_plan"},
            ],
        },
    }

    issue = report._build_full_agent_tool_trial_issue(record)

    assert issue is not None
    assert issue["toolNames"] == [
        "analyze_current_career_direction",
        "query_volunteer_plan",
        "query_volunteer_plan",
    ]
    assert issue["repeatedToolNames"] == ["query_volunteer_plan"]
    assert "missing_progress_for_long_task" not in issue["issueTypes"]


def test_tool_trial_issue_detects_observed_tool_chain_without_routing_path():
    record = {
        "case": "remove-expensive-preview",
        "stepIndex": 1,
        "prompt": "把太贵的那几个先去掉看看",
        "responseText": "我先列出高收费项，请你确认范围后再处理。",
        "elapsedMs": 103_000,
        "thinkingText": "正在读取方案并处理你的请求...",
        "turnObservability": {
            "toolCalls": [
                {"name": "plan_next_action", "actionFamily": "remove_units", "stage": "preview"},
                {
                    "name": "execute_plan_action",
                    "actionFamily": "remove_units",
                    "stage": "preview",
                    "resultKind": "error",
                    "success": False,
                },
                {"name": "query_volunteer_plan"},
                {"name": "query_volunteer_plan"},
            ],
        },
    }

    issue = report._build_full_agent_tool_trial_issue(record)

    assert issue is not None
    assert issue["actualRoutingPath"] is None
    assert issue["repeatedToolNames"] == ["query_volunteer_plan"]
    assert "tool_result_error" in issue["issueTypes"]
    assert "repeated_tool_calls" in issue["issueTypes"]
    assert "many_tool_calls" in issue["issueTypes"]
    assert "very_slow_tool_chain" in issue["issueTypes"]


def test_markdown_summary_renders_full_agent_issue_table():
    item = report._build_case_report(
        "slow-plan#1",
        None,
        {
            "case": "slow-plan",
            "stepIndex": 1,
            "prompt": "就按别太冒险的思路把这版调稳点",
            "responseText": "我先看当前方案。",
            "elapsedMs": 31_000,
            "turnObservability": {
                "routingPath": "full_agent",
                "toolCalls": [
                    {"name": "plan_next_action"},
                    {"name": "execute_plan_action"},
                    {"name": "execute_plan_action"},
                ],
            },
        },
        {},
    )
    summary = report._summarize_reports([item])

    markdown = "\n".join(report._render_markdown_summary(summary))

    assert "## Full Agent Tool Trial Issues" in markdown
    assert "slow-plan#1" in markdown
    assert "execute_plan_action" in markdown
