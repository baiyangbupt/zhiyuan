import importlib.util
import asyncio
import json
import sqlite3
from pathlib import Path

import pytest


RUNNER_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_regression_runner.py"
SPEC = importlib.util.spec_from_file_location("dialog_regression_runner", RUNNER_PATH)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def test_plan_reply_style_accepts_markdown_sections_and_lists():
    text = (
        "**审查结论**\n\n"
        "当前方案可用，风险0项，提醒3项。\n\n"
        "1. 冲稳保分布为8:18:19。\n"
        "2. 需要关注高收费和中外合作办学。"
    )

    assert runner._check_plan_reply_style(text) == []


def test_plan_reply_style_rejects_forced_choice_answer():
    text = "**方案审查结论**\n\n1. 风险0项\n2. 提醒4项\n\n你现在必须决定：选哪个？"

    violations = runner._check_plan_reply_style(text)

    assert any("你现在必须决定" in item for item in violations)
    assert any("选哪个" in item for item in violations)


def test_plan_reply_style_rejects_internal_compensation_preview_wording():
    violations = runner._check_plan_reply_style("这是补偿预览结果。")

    assert any("补偿预览" in item for item in violations)


def test_plan_reply_style_rejects_ab_forced_reply():
    violations = runner._check_plan_reply_style("请明确回复 A 或 B。")

    assert any("请明确回复" in item for item in violations)
    assert any("回复 A 或 B" in item for item in violations)


def test_plan_reply_style_rejects_dangling_exact_line():
    violations = runner._check_plan_reply_style("方案已经有了。\n\n你。")

    assert any("dangling line" in item for item in violations)


def test_apply_session_offset_maps_numeric_case_sessions_without_mutating_original():
    cases = [
        {"name": "case-a", "sessionId": "5736", "prompts": ["确认"]},
        {"name": "case-b", "sessionId": 5740, "prompts": ["看看方案"]},
    ]

    adjusted = runner._apply_session_offset(cases, 200000)

    assert adjusted[0]["sessionId"] == "205736"
    assert adjusted[0]["baseSessionId"] == "5736"
    assert adjusted[1]["sessionId"] == "205740"
    assert adjusted[1]["baseSessionId"] == "5740"
    assert cases[0]["sessionId"] == "5736"
    assert "baseSessionId" not in cases[0]


def test_apply_session_offset_rejects_non_numeric_session_id():
    cases = [{"name": "case-a", "sessionId": "session-5736", "prompts": ["确认"]}]

    with pytest.raises(ValueError, match="numeric sessionId"):
        runner._apply_session_offset(cases, 200000)


def test_expand_case_payload_applies_defaults_without_losing_case_fields():
    cases = runner._expand_case_payload(
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
                            "assertNotContains": ["草稿"],
                            "qualityFocus": ["rich_decision_basis"],
                        }
                    ],
                }
            ],
        }
    )

    assert cases[0]["flow"] == ["explore", "plan"]
    assert cases[0]["coverage"] == ["release_3_0_3", "dialogue_derived", "plan_status"]
    assert cases[0]["assertPlanStyle"] is True
    step = cases[0]["prompts"][0]
    assert step["prompt"] == "这方案咋样"
    assert step["assertNotContains"] == ["payload", "草稿"]
    assert step["forbiddenPatterns"] == ["内部字段"]
    assert step["qualityFocus"] == ["user_language", "rich_decision_basis"]
    assert step["warnElapsedSeconds"] == 30


def test_case_session_ids_deduplicates_in_order():
    cases = [
        {"name": "case-a", "sessionId": "17", "prompts": ["看看方案"]},
        {"name": "case-b", "sessionId": 16, "prompts": ["移动"]},
        {"name": "case-c", "sessionId": "17", "prompts": ["确认"]},
    ]

    assert runner._case_session_ids(cases) == ["17", "16"]


def test_clear_history_deletes_only_requested_sessions(tmp_path):
    db_path = tmp_path / "history.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE chat_session_history (
                session_id TEXT PRIMARY KEY,
                history_json TEXT NOT NULL,
                schema_version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.executemany(
            "INSERT INTO chat_session_history(session_id, history_json, created_at, updated_at) VALUES (?, ?, ?, ?)",
            [
                ("16", "[]", "now", "now"),
                ("17", "[]", "now", "now"),
                ("18", "[]", "now", "now"),
            ],
        )
        conn.commit()

    deleted = runner._clear_history(db_path, ["17", "16"])

    assert deleted == 2
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT session_id FROM chat_session_history ORDER BY session_id").fetchall()
    assert [row[0] for row in rows] == ["18"]


def test_clear_history_missing_db_is_noop(tmp_path):
    assert runner._clear_history(tmp_path / "missing.db", ["17"]) == 0


def test_run_cases_supports_per_case_history_clear(monkeypatch, tmp_path):
    db_path = tmp_path / "history.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE chat_session_history (
                session_id TEXT PRIMARY KEY,
                history_json TEXT NOT NULL,
                schema_version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO chat_session_history(session_id, history_json, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("17", "[]", "now", "now"),
        )
        conn.commit()

    async def fake_ask_once(*args, **kwargs):
        return ([{"type": "text", "content": "方案已经有了。"}], [], {"firstMessageMs": 1, "finalMessageMs": 1})

    monkeypatch.setattr(runner, "_ask_once", fake_ask_once)

    asyncio.run(
        runner._run_cases(
            "ws://test",
            "user",
            [{"name": "case-a", "sessionId": "17", "prompts": [{"prompt": "看看方案", "assertContains": ["方案"]}]}],
            history_db=str(db_path),
            clear_history_per_case=True,
        )
    )

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT session_id FROM chat_session_history").fetchall()
    assert rows == []


def test_latest_turn_messages_returns_latest_matching_prompt():
    history = [
        {"parts": [{"part_kind": "user-prompt", "content": "看看方案"}]},
        {"parts": [{"part_kind": "text", "content": "旧回复"}]},
        {"parts": [{"part_kind": "user-prompt", "content": "看看方案"}]},
        {"parts": [{"part_kind": "text", "content": "新回复"}]},
    ]

    turn = runner._latest_turn_messages(history, "看看方案")

    assert len(turn) == 2
    assert turn[0]["parts"][0]["content"] == "看看方案"
    assert turn[1]["parts"][0]["content"] == "新回复"


def test_summarize_turn_observability_extracts_tool_action_and_result():
    plan_payload = {
        "stage": "preview",
        "action_family": "move_ordered_unit",
        "user_goal": "把第4个专业组移到第2位",
    }
    turn_messages = [
        {"parts": [{"part_kind": "user-prompt", "content": "把第4个专业组移到第2位"}]},
        {
            "parts": [
                {
                    "part_kind": "tool-call",
                    "tool_name": "execute_plan_action",
                    "tool_call_id": "functions.execute_plan_action:1",
                    "args": {"plan_payload": json.dumps(plan_payload, ensure_ascii=False)},
                }
            ]
        },
        {
            "parts": [
                {
                    "part_kind": "tool-return",
                    "tool_name": "execute_plan_action",
                    "tool_call_id": "functions.execute_plan_action:1",
                    "content": json.dumps(
                        {
                            "applied": False,
                            "action_family": "move_ordered_unit",
                            "stage": "preview",
                            "result_kind": "preview_only",
                        },
                        ensure_ascii=False,
                    ),
                }
            ]
        },
    ]

    observed = runner._summarize_turn_observability(turn_messages)

    assert observed["historyMessages"] == 3
    assert observed["toolCallCount"] == 1
    assert observed["toolReturnCount"] == 1
    assert observed["actionFamilies"] == ["move_ordered_unit"]
    assert observed["resultKinds"] == ["preview_only"]
    assert observed["toolCalls"][0]["name"] == "execute_plan_action"
    assert observed["toolCalls"][0]["actionFamily"] == "move_ordered_unit"
    assert observed["toolCalls"][0]["stage"] == "preview"
    assert observed["toolCalls"][0]["resultKind"] == "preview_only"
    assert observed["toolCalls"][0]["applied"] is False


def test_summarize_turn_observability_infers_routing_path_from_fast_route_history():
    turn_messages = [
        {"parts": [{"part_kind": "user-prompt", "content": "按院校层次排序"}]},
        {
            "model_name": "plan-fast-route",
            "parts": [
                {
                    "part_kind": "tool-call",
                    "tool_name": "plan_next_action",
                    "tool_call_id": "fast-plan-next-sort_ordered_plan",
                    "args": {"action_family": "sort_ordered_plan"},
                }
            ],
        },
        {
            "parts": [
                {
                    "part_kind": "tool-return",
                    "tool_name": "plan_next_action",
                    "tool_call_id": "fast-plan-next-sort_ordered_plan",
                    "content": json.dumps(
                        {
                            "action_family": "sort_ordered_plan",
                            "stage": "preview",
                        },
                        ensure_ascii=False,
                    ),
                }
            ]
        },
    ]

    observed = runner._summarize_turn_observability(turn_messages)

    assert observed["routingPath"] == "plan_fast_route"
    assert observed["actionFamilies"] == ["sort_ordered_plan"]


def test_summarize_turn_observability_infers_readonly_closure_ack_route_from_model_name():
    turn_messages = [
        {"parts": [{"part_kind": "user-prompt", "content": "嗯那就这样"}]},
        {
            "model_name": "direct-readonly-closure-ack",
            "parts": [
                {
                    "part_kind": "text",
                    "content": "好的，先按刚才的专业对比结论作为参考。",
                }
            ],
        },
    ]

    observed = runner._summarize_turn_observability(turn_messages)

    assert observed["routingPath"] == "readonly_closure_ack"
    assert observed["toolCallCount"] == 0


def test_summarize_turn_observability_extracts_semantic_router_shadow():
    shadow = {
        "status": "success",
        "durationMs": 321,
        "frame": {
            "taskLayer": "explore",
            "verb": "compare",
            "topic": "major",
            "sideEffect": "readonly",
            "confidence": 0.91,
        },
    }
    turn_messages = [
        {"parts": [{"part_kind": "user-prompt", "content": "财管会计审计怎么排优先级"}]},
        {
            "model_name": "major-compare-fast-route",
            "parts": [{"part_kind": "text", "content": "专业对比回复"}],
        },
        {
            "model_name": "semantic-router-shadow",
            "parts": [
                {
                    "part_kind": "text",
                    "content": json.dumps(
                        {"type": "semanticRouterShadow", "semanticRouterShadow": shadow},
                        ensure_ascii=False,
                    ),
                }
            ],
        },
    ]

    observed = runner._summarize_turn_observability(turn_messages)

    assert observed["routingPath"] == "major_compare_fast_route"
    assert observed["semanticRouterShadow"]["status"] == "success"
    assert observed["semanticRouterShadow"]["frame"]["taskLayer"] == "explore"


def test_summarize_turn_observability_does_not_infer_route_from_plain_tool_name():
    turn_messages = [
        {
            "model_name": "test-model",
            "parts": [
                {
                    "part_kind": "tool-call",
                    "tool_name": "query_volunteer_plan",
                    "tool_call_id": "functions.query_volunteer_plan:1",
                    "args": {"query": "看看方案"},
                }
            ],
        }
    ]

    observed = runner._summarize_turn_observability(turn_messages)

    assert "routingPath" not in observed
    assert observed["toolCalls"][0]["name"] == "query_volunteer_plan"


def test_summarize_turn_observability_counts_plain_text_tool_returns():
    turn_messages = [
        {
            "parts": [
                {
                    "part_kind": "tool-call",
                    "tool_name": "compare_majors",
                    "tool_call_id": "fast-compare-majors",
                    "args": {"major_name1": "法学", "major_name2": "财政学"},
                }
            ]
        },
        {
            "parts": [
                {
                    "part_kind": "tool-return",
                    "tool_name": "compare_majors",
                    "tool_call_id": "fast-compare-majors",
                    "content": "法学和财政学的对比文本",
                }
            ]
        },
    ]

    observed = runner._summarize_turn_observability(turn_messages)

    assert observed["toolCallCount"] == 1
    assert observed["toolReturnCount"] == 1
    assert observed["toolCalls"][0]["name"] == "compare_majors"


def test_summarize_turn_observability_extracts_fast_route_arbitration():
    route_decision = {
        "source": "plan_fast_route",
        "arbitration": {
            "source": "fast_route_arbitrator",
            "selectedPath": "plan_query_fast_route",
            "semanticArbitrationNeeded": True,
            "semanticArbitrationReason": "close_fast_route_candidates",
            "semanticArbitrationCandidatePaths": [
                "plan_query_fast_route",
                "major_intent_fast_route",
            ],
        },
    }
    turn_messages = [
        {
            "parts": [
                {
                    "part_kind": "text",
                    "content": json.dumps(
                        {
                            "event": "conversation_turn_event",
                            "routingPath": "plan_query_fast_route",
                            "routeDecision": route_decision,
                        },
                        ensure_ascii=False,
                    ),
                }
            ]
        }
    ]

    observed = runner._summarize_turn_observability(turn_messages)

    assert observed["routingPath"] == "plan_query_fast_route"
    assert observed["routeDecision"] == route_decision
    assert observed["fastRouteArbitration"]["semanticArbitrationNeeded"] is True
    assert observed["fastRouteArbitration"]["semanticArbitrationCandidatePaths"] == [
        "plan_query_fast_route",
        "major_intent_fast_route",
    ]


def test_followup_summary_extracts_targets_and_refresh_flags():
    followups = [
        {"content": {"targetView": "ordered", "refresh": True}},
        {"content": {"targetView": "review", "refresh": False}},
        {"content": {"targetView": "ordered", "refresh": True}},
    ]

    targets, refreshes = runner._followup_summary(followups)

    assert targets == ["ordered", "review"]
    assert refreshes == [True, False, True]


def test_content_assertions_reject_followups_when_disallowed():
    violations = runner._check_content_assertions(
        "当前没有上一轮待确认的方案动作。",
        [{"type": "planningWorkspaceAction", "content": {"targetView": "ordered", "refresh": True}}],
        {"prompt": "确认", "assertNoFollowups": True},
        "case-a",
        "17",
    )

    assert any("assertNoFollowups FAILED" in item for item in violations)


def test_content_assertions_support_thinking_messages():
    violations = runner._check_content_assertions(
        "会把第2个志愿移动到第4位。需要你确认后才会执行。",
        [],
        {
            "prompt": "把第2个志愿移到第4位",
            "assertThinkingContains": ["正在读取当前方案并整理这次请求", "正在生成这次调整的影响预览"],
            "assertThinkingNotContains": ["payload"],
        },
        "case-progress",
        "17",
        thinking_text="正在读取当前方案并整理这次请求...\n正在生成这次调整的影响预览...",
    )

    assert violations == []


def test_content_assertions_report_missing_thinking_message():
    violations = runner._check_content_assertions(
        "会把第2个志愿移动到第4位。需要你确认后才会执行。",
        [],
        {"prompt": "把第2个志愿移到第4位", "assertThinkingContains": ["正在生成这次调整的影响预览"]},
        "case-progress",
        "17",
        thinking_text="正在读取当前方案并整理这次请求...",
    )

    assert any("assertThinkingContains FAILED" in item for item in violations)


def test_case_metrics_can_store_response_text_when_enabled():
    record = {
        "case": "case-a",
        "sessionId": "17",
        "prompt": "看看现在的方案",
        "elapsedMs": 1234,
        "primaryMessages": 2,
        "thinkingMessages": 1,
        "followupMessages": 0,
        "responseText": "方案已经有了。",
        "thinkingText": "正在读取当前方案并整理这次请求...",
    }

    assert record["responseText"].startswith("方案已经有了")
    assert record["thinkingText"].startswith("正在读取")


def test_performance_assertions_support_warning_and_hard_budget():
    failures, warnings = runner._check_performance_assertions(
        45000,
        {"prompt": "看看方案", "warnElapsedMs": 30000, "maxElapsedSeconds": 40},
        "case-a",
        "17",
    )

    assert any("latency warning" in item for item in warnings)
    assert any("maxElapsed FAILED" in item for item in failures)


def test_metrics_summary_reports_latency_distribution_and_slowest_steps():
    summary = runner._build_metrics_summary(
        [
            {"case": "a", "sessionId": "17", "prompt": "p1", "elapsedMs": 1000},
            {"case": "b", "sessionId": "17", "prompt": "p2", "elapsedMs": 3000},
            {"case": "c", "sessionId": "16", "prompt": "p3", "elapsedMs": 2000},
            {"case": "d", "sessionId": "16", "prompt": "p4", "elapsedMs": 500, "error": "Timeout"},
        ]
    )

    assert summary["steps"] == 4
    assert summary["successfulSteps"] == 3
    assert summary["failedSteps"] == 1
    assert summary["elapsed"]["medianMs"] == 2000
    assert summary["slowest"][0]["case"] == "b"
