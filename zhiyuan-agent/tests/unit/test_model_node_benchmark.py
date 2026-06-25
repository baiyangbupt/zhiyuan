import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


BENCHMARK_PATH = Path(__file__).resolve().parents[2] / "examples" / "model_node_benchmark.py"
SPEC = importlib.util.spec_from_file_location("model_node_benchmark", BENCHMARK_PATH)
assert SPEC and SPEC.loader
benchmark = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)


def test_model_node_benchmark_passes_exact_and_contains_assertions():
    case = {
        "caseId": "case-a",
        "node": "turn_side_effect",
        "expected": {
            "taskLayer": "plan",
            "sideEffect": "plan_preview",
            "targetIssue": ["tuition", "cooperative_program"],
        },
        "actual": {
            "taskLayer": "plan",
            "sideEffect": "plan_preview",
            "targetIssue": ["cooperative_program", "tuition"],
        },
        "assert": {
            "exact": ["taskLayer", "sideEffect"],
            "contains": {"targetIssue": ["tuition"]},
        },
    }

    record = benchmark._evaluate_case(case)

    assert record["passed"] is True
    assert record["actual"] == case["actual"]
    assert record["failures"] == []


def test_model_node_benchmark_reports_field_mismatch_and_forbidden_value():
    case = {
        "caseId": "case-a",
        "node": "plan_semantic_action",
        "expected": {"actionFamily": "none"},
        "actual": {"actionFamily": "preview_fix_proposal", "replyFocus": ["unavailable_guidance"]},
        "assert": {
            "exact": ["actionFamily"],
            "notContains": {"replyFocus": ["unavailable_guidance"]},
        },
    }

    record = benchmark._evaluate_case(case)

    assert record["passed"] is False
    assert record["failures"][0]["field"] == "actionFamily"
    assert record["failures"][1]["type"] == "notContains"


def test_model_node_benchmark_reports_schema_gap_without_hiding_raw_actual():
    case = {
        "caseId": "preference-strength-gap",
        "node": "intent_side_effect",
        "expected": {
            "decision": "intent_preview",
            "preferenceStrength": {
                "primary": ["网络与新媒体"],
                "acceptable": ["跨境电子商务"],
            },
        },
        "actual": {
            "decision": "intent_preview",
            "constraintIntentType": "default",
        },
        "assert": {
            "exact": ["decision"],
            "contains": {
                "preferenceStrength.primary": ["网络与新媒体"],
                "preferenceStrength.acceptable": ["跨境电子商务"],
            },
        },
    }

    record = benchmark._evaluate_case(case)

    assert record["passed"] is False
    assert record["rawActual"] == {"decision": "intent_preview", "constraintIntentType": "default"}
    assert record["profileActual"]["legacy"] == {"constraintIntentType": "default"}
    assert record["schemaGaps"] == [
        {"field": "preferenceStrength.primary", "reason": "missing_profile_field"},
        {"field": "preferenceStrength.acceptable", "reason": "missing_profile_field"},
    ]
    assert record["legacyOnlyFields"] == [
        {
            "legacyField": "constraintIntentType",
            "missingField": "preferenceStrength.primary",
            "reason": "legacy_field_does_not_satisfy_3_2_schema",
        },
        {
            "legacyField": "constraintIntentType",
            "missingField": "preferenceStrength.acceptable",
            "reason": "legacy_field_does_not_satisfy_3_2_schema",
        },
    ]
    assert [failure["field"] for failure in record["failures"]] == [
        "preferenceStrength.primary",
        "preferenceStrength.acceptable",
    ]


def test_model_node_benchmark_contains_supports_structured_object_arrays():
    case = {
        "caseId": "mixed-polarity",
        "node": "intent_entity_extraction",
        "expected": {
            "entityPolaritySpans": [
                {"entity": "生物医学工程", "entityType": "major", "polarity": "positive"},
                {"entity": "临床医学", "entityType": "major", "polarity": "negative"},
            ]
        },
        "actual": {
            "entityPolaritySpans": [
                {
                    "entity": "生物医学工程",
                    "entityType": "major",
                    "polarity": "positive",
                    "strength": "primary",
                },
                {
                    "entity": "临床医学",
                    "entityType": "major",
                    "polarity": "negative",
                    "strength": "exclude_hard",
                },
            ]
        },
        "assert": {
            "contains": {
                "entityPolaritySpans": [
                    {"entity": "生物医学工程", "entityType": "major", "polarity": "positive"},
                    {"entity": "临床医学", "entityType": "major", "polarity": "negative"},
                ]
            }
        },
    }

    record = benchmark._evaluate_case(case)

    assert record["passed"] is True
    assert record["failures"] == []


def test_model_node_benchmark_flags_mixed_polarity_regression():
    case = {
        "caseId": "mixed-polarity-regression",
        "node": "intent_entity_extraction",
        "expected": {
            "entityPolaritySpans": [
                {"entity": "生物医学工程", "entityType": "major", "polarity": "positive"},
                {"entity": "临床医学", "entityType": "major", "polarity": "negative"},
            ]
        },
        "actual": {
            "entityPolaritySpans": [
                {"entity": "生物医学工程", "entityType": "major", "polarity": "negative"},
                {"entity": "临床医学", "entityType": "major", "polarity": "negative"},
            ]
        },
        "assert": {
            "contains": {
                "entityPolaritySpans": [
                    {"entity": "生物医学工程", "entityType": "major", "polarity": "positive"},
                    {"entity": "临床医学", "entityType": "major", "polarity": "negative"},
                ]
            }
        },
    }

    record = benchmark._evaluate_case(case)

    assert record["passed"] is False
    assert record["failures"][0]["field"] == "entityPolaritySpans"
    assert record["failures"][0]["missing"] == [
        {"entity": "生物医学工程", "entityType": "major", "polarity": "positive"}
    ]


def test_model_node_benchmark_guard_cases_report_expected_failures():
    report = benchmark.build_report(
        [
            {
                "caseId": "no-pending-confirm",
                "node": "turn_side_effect",
                "actual": {"sideEffect": "apply_existing_pending"},
                "expected": {"sideEffect": "readonly"},
                "assert": {"exact": ["sideEffect"]},
                "metricsTags": ["no_pending_guard_accuracy"],
            },
            {
                "caseId": "readonly-query-while-pending",
                "node": "turn_side_effect",
                "actual": {"sideEffect": "apply_existing_pending", "pendingType": "applied"},
                "expected": {"sideEffect": "readonly_while_pending", "pendingType": "unchanged_existing_pending"},
                "assert": {"exact": ["sideEffect", "pendingType"]},
                "metricsTags": ["readonly_while_pending_accuracy"],
            },
            {
                "caseId": "no-plan-reference",
                "node": "turn_side_effect",
                "actual": {"sideEffect": "intent_pending", "referenceResolution": "guessed"},
                "expected": {"sideEffect": "needs_plan_first", "referenceResolution": "no_referent"},
                "assert": {"exact": ["sideEffect", "referenceResolution"]},
                "metricsTags": ["needs_plan_first_accuracy"],
            },
        ]
    )

    assert report["summary"]["failed"] == 3
    assert report["summary"]["fieldFailures"] == {
        "sideEffect": 3,
        "pendingType": 1,
        "referenceResolution": 1,
    }


def test_model_node_benchmark_summary_counts_legacy_only_schema_fields():
    report = benchmark.build_report(
        [
            {
                "caseId": "legacy-only-preference-strength",
                "node": "intent_side_effect",
                "expected": {
                    "decision": "intent_preview",
                    "preferenceStrength": {"primary": ["计算机类"]},
                },
                "actual": {
                    "decision": "intent_preview",
                    "constraintIntentType": "default",
                },
                "assert": {
                    "exact": ["decision"],
                    "contains": {"preferenceStrength.primary": ["计算机类"]},
                },
            }
        ]
    )

    assert report["summary"]["schemaGaps"] == {"preferenceStrength.primary": 1}
    assert report["summary"]["legacyOnlyFields"] == {"preferenceStrength.primary": 1}


def test_model_node_benchmark_not_contains_does_not_create_schema_gap():
    case = {
        "caseId": "not-contains-missing-field",
        "node": "intent_side_effect",
        "expected": {"decision": "intent_preview"},
        "actual": {
            "decision": "intent_preview",
            "constraintIntentType": "default",
            "preferenceStrength": {"primary": ["计算机类"]},
        },
        "assert": {
            "exact": ["decision"],
            "contains": {"preferenceStrength.primary": ["计算机类"]},
            "notContains": {
                "preferenceStrength.must_have": ["计算机类"],
                "preferenceStrength.only_keep": ["计算机类"],
            },
        },
    }

    record = benchmark._evaluate_case(case)

    assert record["passed"] is True
    assert record["schemaGaps"] == []
    assert record["legacyOnlyFields"] == []


def test_model_node_benchmark_summary_groups_by_node_and_tag():
    records = [
        {
            "caseId": "a",
            "node": "turn_side_effect",
            "actualSource": "fixture",
            "metricsTags": ["sideEffect_accuracy"],
            "passed": True,
            "failures": [],
            "latencyMs": 100,
        },
        {
            "caseId": "b",
            "node": "turn_side_effect",
            "actualSource": "provider_env",
            "metricsTags": ["sideEffect_accuracy"],
            "passed": False,
            "failures": [{"type": "exact", "field": "sideEffect"}],
            "latencyMs": 300,
        },
    ]

    summary = benchmark._build_summary(records)

    assert summary["rawTotal"] == 2
    assert summary["total"] == 1
    assert summary["passRate"] == 1.0
    assert summary["byNode"]["turn_side_effect"] == {"total": 1, "passed": 1, "failed": 0}
    assert summary["byTag"]["sideEffect_accuracy"] == {"total": 1, "passed": 1, "failed": 0}
    assert summary["fieldFailures"] == {}
    assert summary["schemaGaps"] == {}
    assert summary["legacyOnlyFields"] == {}
    assert summary["providerEnvExcluded"] == 1
    assert summary["providerEnvExcludedByReason"] == {"provider_env": 1}
    assert summary["latency"]["medianMs"] == 100


def test_model_node_benchmark_loads_array_or_wrapped_cases(tmp_path):
    array_path = tmp_path / "array.json"
    wrapped_path = tmp_path / "wrapped.json"
    array_path.write_text(json.dumps([{"caseId": "a"}]), encoding="utf-8")
    wrapped_path.write_text(json.dumps({"cases": [{"caseId": "b"}]}), encoding="utf-8")

    assert benchmark._load_cases(str(array_path))[0]["caseId"] == "a"
    assert benchmark._load_cases(str(wrapped_path))[0]["caseId"] == "b"


def test_model_node_benchmark_filters_cases_by_nodes():
    cases = [
        {"caseId": "a", "node": "intent_side_effect"},
        {"caseId": "b", "node": "plan_semantic_action"},
        {"caseId": "c", "node": "local_plan_action_dsl"},
    ]

    selected = benchmark._filter_cases_by_nodes(cases, "intent_side_effect, local_plan_action_dsl")

    assert [case["caseId"] for case in selected] == ["a", "c"]


def test_model_node_benchmark_excludes_provider_env_errors_from_quality_matrix():
    report = benchmark.build_report(
        [
            {
                "caseId": "provider-missing-key",
                "node": "intent_side_effect",
                "actualSource": "provider_env",
                "liveError": {"type": "missing_api_key", "message": "missing API key env var: LLM_API_KEY"},
                "expected": {"decision": "intent_preview"},
                "assert": {"exact": ["decision"]},
            },
            {
                "caseId": "quality-case",
                "node": "intent_side_effect",
                "actual": {"decision": "intent_preview"},
                "expected": {"decision": "intent_preview"},
                "assert": {"exact": ["decision"]},
            },
        ]
    )

    assert report["summary"]["rawTotal"] == 2
    assert report["summary"]["total"] == 1
    assert report["summary"]["passed"] == 1
    assert report["summary"]["providerEnvExcluded"] == 1
    assert report["summary"]["providerEnvExcludedByReason"] == {"missing_api_key": 1}
    assert report["failureExamples"] == []


@pytest.mark.asyncio
async def test_model_node_benchmark_excludes_provider_connection_errors_from_quality_matrix():
    with patch(
        "app.tools.intent_entity_profile_tool.extract_intent_entity_profile",
        new=AsyncMock(side_effect=RuntimeError("Connection error.")),
    ):
        report = await benchmark.build_report_async(
            [
                {
                    "caseId": "provider-connection-error",
                    "node": "intent_entity_extraction",
                    "prompt": "城市优先长三角",
                    "expected": {"entityType": "region"},
                    "assert": {"exact": ["entityType"]},
                }
            ],
            actual_source="live-node",
        )

    record = report["records"][0]
    assert record["actualSource"] == "provider_env"
    assert record["qualityExcluded"] is True
    assert record["liveError"]["type"] == "provider_connection_error"
    assert record["schemaGaps"] == []
    assert record["legacyOnlyFields"] == []
    assert report["summary"]["total"] == 0
    assert report["summary"]["providerEnvExcluded"] == 1
    assert report["summary"]["providerEnvExcludedByReason"] == {"provider_connection_error": 1}
    assert report["failureExamples"] == []


def test_model_node_benchmark_repeat_cases_drops_recorded_actual():
    repeated = benchmark._repeat_cases(
        [
            {
                "caseId": "case-a",
                "node": "intent_side_effect",
                "actual": {"decision": "intent_preview"},
            }
        ],
        2,
    )

    assert [case["caseId"] for case in repeated] == ["case-a#r1", "case-a#r2"]
    assert [case["baseCaseId"] for case in repeated] == ["case-a", "case-a"]
    assert [case["repeatIndex"] for case in repeated] == [1, 2]
    assert all("actual" not in case for case in repeated)


def test_model_node_benchmark_stability_summary_groups_repeated_cases():
    report = benchmark.build_report(
        [
            {
                "caseId": "case-a#r1",
                "baseCaseId": "case-a",
                "repeatIndex": 1,
                "node": "intent_side_effect",
                "actual": {"decision": "intent_preview"},
                "expected": {"decision": "intent_preview"},
                "assert": {"exact": ["decision"]},
            },
            {
                "caseId": "case-a#r2",
                "baseCaseId": "case-a",
                "repeatIndex": 2,
                "node": "intent_side_effect",
                "actual": {"decision": "intent_preview"},
                "expected": {"decision": "intent_preview"},
                "assert": {"exact": ["decision"]},
            },
            {
                "caseId": "case-b#r1",
                "baseCaseId": "case-b",
                "repeatIndex": 1,
                "node": "intent_side_effect",
                "actual": {"decision": "analysis_only"},
                "expected": {"decision": "intent_preview"},
                "assert": {"exact": ["decision"]},
            },
            {
                "caseId": "case-b#r2",
                "baseCaseId": "case-b",
                "repeatIndex": 2,
                "node": "intent_side_effect",
                "actual": {"decision": "intent_preview"},
                "expected": {"decision": "intent_preview"},
                "assert": {"exact": ["decision"]},
            },
        ]
    )

    assert report["summary"]["stability"] == {
        "caseGroups": 2,
        "stablePassedGroups": 1,
        "stablePassRate": 0.5,
    }


@pytest.mark.asyncio
async def test_model_node_benchmark_live_node_turn_side_effect_uses_turn_decision_tool():
    fake_result = MagicMock()
    fake_result.model_dump.return_value = {
        "taskLayer": "plan",
        "sideEffect": "readonly_while_pending",
        "scopeAnchor": "current_plan",
        "scenario": "plan_query",
    }

    with patch(
        "app.tools.turn_decision_tool.classify_turn_decision",
        new=AsyncMock(return_value=fake_result),
    ) as classify_mock:
        report = await benchmark.build_report_async(
            [
                {
                    "caseId": "turn-side-effect",
                    "node": "turn_side_effect",
                    "prompt": "先不确认，当前方案里有没有护理或者中医学",
                    "input": {
                        "planningStateProfile": {
                            "formalPlanPresent": True,
                            "pendingExists": True,
                        }
                    },
                    "expected": {
                        "taskLayer": "plan",
                        "sideEffect": "readonly_while_pending",
                        "scopeAnchor": "current_plan",
                        "scenario": "plan_query",
                    },
                    "assert": {
                        "exact": ["taskLayer", "sideEffect", "scopeAnchor", "scenario"],
                    },
                }
            ],
            actual_source="live-node",
        )

    record = report["records"][0]
    assert record["passed"] is True
    assert record["actualSource"] == "live_node"
    classify_mock.assert_awaited_once_with(
        "先不确认，当前方案里有没有护理或者中医学",
        payload={"planningStateProfile": {"formalPlanPresent": True, "pendingExists": True}},
    )


@pytest.mark.asyncio
async def test_model_node_benchmark_live_node_intent_entity_profile_uses_320_schema():
    fake_result = MagicMock()
    fake_result.model_dump.return_value = {
        "entityType": "region",
        "regionValues": ["长三角"],
        "majorValues": [],
        "preferenceStrength": {"primary": ["长三角"]},
    }

    with patch(
        "app.tools.intent_entity_profile_tool.extract_intent_entity_profile",
        new=AsyncMock(return_value=fake_result),
    ) as extract_mock:
        report = await benchmark.build_report_async(
            [
                {
                    "caseId": "entity-profile",
                    "node": "intent_entity_extraction",
                    "prompt": "城市优先长三角",
                    "expected": {
                        "entityType": "region",
                        "regionValues": ["长三角"],
                        "preferenceStrength": {"primary": ["长三角"]},
                    },
                    "assert": {
                        "exact": ["entityType"],
                        "contains": {
                            "regionValues": ["长三角"],
                            "preferenceStrength.primary": ["长三角"],
                        },
                    },
                }
            ],
            actual_source="live-node",
        )

    record = report["records"][0]
    assert record["passed"] is True
    assert record["actualSource"] == "live_node"
    assert record["legacyOnlyFields"] == []
    extract_mock.assert_awaited_once_with("城市优先长三角", context={})


@pytest.mark.asyncio
async def test_model_node_benchmark_live_node_reply_focus_binding_uses_reply_profile_tool():
    fake_result = MagicMock()
    fake_result.model_dump.return_value = {
        "answerFocusFirst": True,
        "targetIssue": ["cooperative_program", "tuition_budget"],
        "sideEffectBoundary": "readonly_no_apply",
    }

    with patch(
        "app.tools.reply_profile_tool.classify_reply_focus_binding",
        new=AsyncMock(return_value=fake_result),
    ) as classify_mock:
        report = await benchmark.build_report_async(
            [
                {
                    "caseId": "reply-focus",
                    "node": "reply_focus_binding",
                    "prompt": "方案里中外合作是不是有点多，家里预算一般，帮我用大白话看下风险，先别动",
                    "expected": {
                        "answerFocusFirst": True,
                        "targetIssue": ["cooperative_program", "tuition_budget"],
                        "sideEffectBoundary": "readonly_no_apply",
                    },
                    "assert": {
                        "exact": ["answerFocusFirst", "sideEffectBoundary"],
                        "contains": {"targetIssue": ["cooperative_program", "tuition_budget"]},
                    },
                }
            ],
            actual_source="live-node",
        )

    record = report["records"][0]
    assert record["passed"] is True
    assert record["actualSource"] == "live_node"
    classify_mock.assert_awaited_once_with(
        "方案里中外合作是不是有点多，家里预算一般，帮我用大白话看下风险，先别动",
        payload={},
    )


@pytest.mark.asyncio
async def test_model_node_benchmark_live_node_reply_generation_grounding_uses_reply_profile_tool():
    fake_result = MagicMock()
    fake_result.model_dump.return_value = {
        "mustGroundFormula": True,
        "missingInfo": ["province", "art_formula"],
        "forbidPreciseScore": True,
    }

    with patch(
        "app.tools.reply_profile_tool.classify_reply_generation_grounding",
        new=AsyncMock(return_value=fake_result),
    ) as classify_mock:
        report = await benchmark.build_report_async(
            [
                {
                    "caseId": "reply-grounding",
                    "node": "reply_generation_grounding",
                    "prompt": "我美术生文化课580联考250综合多少能上啥",
                    "expected": {
                        "mustGroundFormula": True,
                        "missingInfo": ["province", "art_formula"],
                        "forbidPreciseScore": True,
                    },
                    "assert": {
                        "exact": ["mustGroundFormula", "forbidPreciseScore"],
                        "contains": {"missingInfo": ["province", "art_formula"]},
                    },
                }
            ],
            actual_source="live-node",
        )

    record = report["records"][0]
    assert record["passed"] is True
    assert record["actualSource"] == "live_node"
    classify_mock.assert_awaited_once_with("我美术生文化课580联考250综合多少能上啥", payload={})


@pytest.mark.asyncio
async def test_model_node_benchmark_live_node_candidate_filter_adapter_projects_profile_fields():
    with patch(
        "app.tools.candidate_filter_extraction_tool.extract_candidate_query_filters_async",
        new=AsyncMock(
            return_value={
                "should_query_candidate": True,
                "confidence": 0.9,
                "ambiguities": [],
                "filters": {
                    "tiers": ["保"],
                    "province_names": [],
                    "city_names": [],
                    "school_keywords": [],
                    "major_keywords": [],
                    "school_tags": [],
                    "major_tags": [],
                },
                "raw": {"tiers": ["保"]},
            }
        ),
    ) as extract_mock:
        report = await benchmark.build_report_async(
            [
                {
                    "caseId": "candidate-filter",
                    "node": "candidate_filter_extraction",
                    "prompt": "保底最后几个是什么学校 录取率多少",
                    "expected": {
                        "scope": "tier_segment",
                        "tier": "保底",
                        "slice": "tail",
                        "fields": ["school", "admissionProbability"],
                    },
                    "assert": {
                        "exact": ["scope", "tier", "slice"],
                        "contains": {"fields": ["school", "admissionProbability"]},
                    },
                }
            ],
            actual_source="live-node",
        )

    record = report["records"][0]
    assert record["passed"] is True
    assert record["actualSource"] == "live_node"
    assert record["rawActual"]["shouldQueryCandidate"] is True
    extract_mock.assert_awaited_once_with("保底最后几个是什么学校 录取率多少", batch="01")


@pytest.mark.asyncio
async def test_model_node_benchmark_live_node_unsupported_reports_structured_error():
    report = await benchmark.build_report_async(
        [
            {
                "caseId": "unsupported",
                "node": "unknown_node",
                "prompt": "测试",
                "expected": {"x": "y"},
                "assert": {"exact": ["x"]},
            }
        ],
        actual_source="live-node",
    )

    record = report["records"][0]
    assert record["actualSource"] == "live_node_error"
    assert record["liveError"]["type"] == "unsupported_live_node"
    assert record["passed"] is False
    assert report["summary"]["fieldFailures"] == {"unsupported_live_node": 1}
