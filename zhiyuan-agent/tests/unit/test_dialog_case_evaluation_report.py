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
    assert merged["expectedRoutingPath"] == "plan_fast_route"
    assert merged["expectedActionFamily"] == "sort_ordered_plan"
    assert merged["latencyBudget"] == {"warnElapsedMs": 3000, "maxElapsedMs": 5000}
    assert merged["assertions"] == {"assertContains": ["排序", "确认"]}
    assert merged["qualityExpectations"] == {
        "expectedKeyPoints": ["说明导出顺序影响", "说明审查需要重新看"],
        "qualityFocus": ["preview_confirm_boundary"],
    }
    assert "latency_warn_exceeded" in ",".join(merged["current"]["score"]["evaluationWarnings"])
    assert "missing_route_observability" in ",".join(merged["current"]["score"]["evaluationWarnings"])


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
                            "prompt": "嗯那就这样",
                            "coverage": ["no_pending_guard"],
                            "expectedRoutingPath": "plan_confirmation_guard_no_pending",
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
    assert definitions["intent-confirm#1"]["expectedActionFamily"] == "update_volunteer_intent_state"
    assert definitions["no-pending#1"]["expectedRoutingPath"] == "plan_confirmation_guard_no_pending"
    assert "expectedActionFamily" not in definitions["no-pending#1"]
    assert definitions["no-pending#1"]["expectedNoAction"] is True
    assert definitions["readonly-confirm#1"]["expectedRoutingPath"] == "plan_confirmation_guard_no_pending"
    assert "expectedActionFamily" not in definitions["readonly-confirm#1"]


def test_score_case_flags_route_and_action_family_mismatch():
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

    assert "route_mismatch:plan_fast_route!=full_agent" in score["qualityViolations"]
    assert any(item.startswith("action_family_mismatch:") for item in score["qualityViolations"])
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
            "expectedRoutingPath": "plan_confirmation_guard_no_pending",
            "expectedNoAction": True,
            "routingPath": "plan_confirmation_guard_no_pending",
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
