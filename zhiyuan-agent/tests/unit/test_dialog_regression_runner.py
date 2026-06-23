import importlib.util
import asyncio
import json
import sqlite3
import subprocess
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
    text = "**方案审查结论**\n\n1. 风险0项\n2. 提醒4项\n\n你现在必须决定：你选哪个？"

    violations = runner._check_plan_reply_style(text)

    assert any("你现在必须决定" in item for item in violations)
    assert any("你选哪个" in item for item in violations)


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


def test_apply_session_offset_uses_source_session_as_backend_clone_source():
    cases = [
        {
            "name": "production-case",
            "sessionId": "2633",
            "sourceSessionId": "2633",
            "prompts": ["取消学费超过20000元的志愿"],
        }
    ]

    adjusted = runner._apply_session_offset(cases, 200000)

    assert adjusted[0]["sessionId"] == "202633"
    assert adjusted[0]["baseSessionId"] == "2633"
    assert adjusted[0]["cloneBackendStateFromSessionId"] == "2633"
    assert "cloneBackendStateFromSessionId" not in cases[0]


def test_apply_session_offset_keeps_explicit_backend_clone_source():
    cases = [
        {
            "name": "manual-clone-case",
            "sessionId": "5906",
            "sourceSessionId": "5906",
            "cloneBackendStateFromSessionId": "17",
            "prompts": ["看看方案"],
        }
    ]

    adjusted = runner._apply_session_offset(cases, 200000)

    assert adjusted[0]["sessionId"] == "205906"
    assert adjusted[0]["cloneBackendStateFromSessionId"] == "17"


def test_filter_cases_by_name_keeps_requested_cases():
    cases = [
        {"name": "case-a", "sessionId": "1", "prompts": ["a"]},
        {"name": "case-b", "sessionId": "2", "prompts": ["b"]},
    ]

    filtered = runner._filter_cases_by_name(cases, ["case-b"])

    assert filtered == [cases[1]]


def test_filter_cases_by_name_rejects_missing_case():
    cases = [{"name": "case-a", "sessionId": "1", "prompts": ["a"]}]

    with pytest.raises(ValueError, match="case-b"):
        runner._filter_cases_by_name(cases, ["case-b"])


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


def test_runtime_shadow_observation_preserves_unsupported_local_action_route():
    observation = runner._build_runtime_shadow_observation(
        {
            "name": "pin-lock",
            "sessionId": "26",
            "planningStateProfile": {"formalPlanPresent": True, "pendingExists": False},
        },
        {
            "profileCaseId": "G16-plan-local-pin-or-lock-action",
            "prompt": "帮我把方案里第1个和第2个冲档锁定 位置不要动",
        },
        {
            "case": "pin-lock",
            "stepIndex": 1,
            "sessionId": "26",
            "prompt": "帮我把方案里第1个和第2个冲档锁定 位置不要动",
            "elapsedMs": 5000,
            "turnObservability": {
                "routingPath": "direct_local_plan_action_unsupported",
                "toolCallCount": 0,
                "toolReturnCount": 0,
                "actionFamilies": [],
                "resultKinds": [],
                "routeDecision": {
                    "route": "local_plan_action_unsupported",
                    "sideEffect": "plan_preview_or_clarification",
                    "actionFamily": "pin_or_lock_unit",
                    "unsupportedAction": "pin_or_lock_unit",
                },
            },
        },
        [
            {
                "type": "planningWorkspaceAction",
                "content": {
                    "type": "planningWorkspaceAction",
                    "targetView": "ordered",
                    "refresh": True,
                },
            }
        ],
        1,
    )

    assert observation is not None
    runtime = observation["runtime"]
    assert runtime["sideEffect"] == "plan_preview_or_clarification"
    assert runtime["outputType"] == "plan_mutation_or_unsupported"
    assert runtime["pendingType"] == "none"
    assert runtime["displayPayload"]["presentation"] == "conditional_options"
    assert runtime["replyFocus"] == ["pin_or_lock_unit"]
    assert runtime["workspaceRefreshTargets"] == ["ordered"]
    assert runtime["executionPayload"]["kind"] == "conditional_plan_mutation"


def test_runtime_shadow_observation_uses_route_display_payload_for_conditional_options():
    observation = runner._build_runtime_shadow_observation(
        {
            "name": "fee-options",
            "sessionId": "130",
            "planningStateProfile": {"formalPlanPresent": True, "pendingExists": False},
        },
        {
            "profileCaseId": "G2-tuition-cooperative-how-to-handle-preview-boundary",
            "prompt": "方案里高收费或者中外合作风险大的，先看看能怎么处理，别直接动",
        },
        {
            "case": "fee-options",
            "stepIndex": 1,
            "sessionId": "130",
            "prompt": "方案里高收费或者中外合作风险大的，先看看能怎么处理，别直接动",
            "elapsedMs": 5000,
            "turnObservability": {
                "routingPath": "semantic_plan_action",
                "toolCallCount": 1,
                "toolReturnCount": 1,
                "actionFamilies": ["analyze_adjustment"],
                "resultKinds": ["adjustment_analysis"],
                "routeDecision": {
                    "route": "analyze_adjustment",
                    "displayPayload": {"presentation": "conditional_options"},
                },
            },
        },
        [],
        1,
    )

    assert observation is not None
    runtime = observation["runtime"]
    assert runtime["sideEffect"] == "readonly"
    assert runtime["outputType"] == "readonly"
    assert runtime["pendingType"] == "none"
    assert runtime["displayPayload"]["presentation"] == "conditional_options"


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


def test_clone_backend_chat_session_row_uses_mysql_insert_select(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, stdout="1\n", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    result = runner._clone_backend_chat_session_row(
        source_session_id="17",
        target_session_id="9903101",
        db_host="127.0.0.1",
        db_port="3306",
        db_user="root",
        db_password="secret",
        db_name="sales_bot",
    )

    assert result["ok"] is True
    assert result["insertedRows"] == 1
    cmd, kwargs = calls[0]
    assert cmd[:4] == ["mysql", "-h127.0.0.1", "-P3306", "-uroot"]
    assert kwargs["env"]["MYSQL_PWD"] == "secret"
    assert "INSERT INTO assistant_chat_session" in cmd[-1]
    assert "src.id = 17" in cmd[-1]
    assert "dst.id = 9903101" in cmd[-1]


def test_clone_backend_chat_session_row_rejects_non_numeric_ids():
    result = runner._clone_backend_chat_session_row(
        source_session_id="base",
        target_session_id="9903101",
        db_host="127.0.0.1",
        db_port="3306",
        db_user="root",
        db_password="",
        db_name="sales_bot",
    )

    assert result["ok"] is False
    assert "numeric" in result["error"]


def test_clone_backend_volunteer_data_files_copies_local_source_files(tmp_path):
    (tmp_path / "session_volunteer_17.json").write_text('{"detailList":[]}', encoding="utf-8")
    (tmp_path / "session_volunteer_17_temp.json").write_text('{"temp":true}', encoding="utf-8")

    result = runner._clone_backend_volunteer_data_files(
        source_session_id="17",
        target_session_id="9903101",
        data_dir=tmp_path,
    )

    assert result["ok"] is True
    assert result["copiedFiles"] == 2
    assert (tmp_path / "session_volunteer_9903101.json").read_text(encoding="utf-8") == '{"detailList":[]}'
    assert (tmp_path / "session_volunteer_9903101_temp.json").read_text(encoding="utf-8") == '{"temp":true}'


def test_clone_backend_volunteer_data_files_requires_original_source(tmp_path):
    (tmp_path / "session_volunteer_17_temp.json").write_text('{"temp":true}', encoding="utf-8")

    result = runner._clone_backend_volunteer_data_files(
        source_session_id="17",
        target_session_id="9903101",
        data_dir=tmp_path,
    )

    assert result["ok"] is False
    assert "original" in result["error"]


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


def test_run_cases_supports_per_case_backend_pending_clear(monkeypatch, tmp_path):
    calls = []

    async def fake_ask_once(*args, **kwargs):
        return ([{"type": "text", "content": "方案已经有了。"}], [], {"firstMessageMs": 1, "finalMessageMs": 1})

    def fake_clear_backend_pending_state(base_url, session_ids):
        calls.append((base_url, session_ids))
        return [{"session": session_ids[0], "key": "pendingConfirmation", "ok": True}]

    monkeypatch.setattr(runner, "_ask_once", fake_ask_once)
    monkeypatch.setattr(runner, "_clear_backend_pending_state", fake_clear_backend_pending_state)

    asyncio.run(
        runner._run_cases(
            "ws://test",
            "user",
            [{"name": "case-a", "sessionId": "17", "prompts": [{"prompt": "看看方案", "assertContains": ["方案"]}]}],
            history_db=str(tmp_path / "missing.db"),
            clear_backend_pending_per_case=True,
            internal_service_url="http://backend.test",
        )
    )

    assert calls == [("http://backend.test", ["17"])]


def test_run_cases_writes_runtime_shadow_output(monkeypatch, tmp_path):
    shadow_path = tmp_path / "runtime-shadow.json"
    metrics_path = tmp_path / "metrics.json"

    async def fake_ask_once(*args, **kwargs):
        return (
            [{"type": "text", "content": "会先生成待确认调整，不会直接执行。"}],
            [
                {
                    "type": "pendingConfirmationCard",
                    "content": {
                        "type": "pendingConfirmationCard",
                        "kind": "plan_mutation",
                        "pendingId": "pending-1",
                        "actionFamily": "apply_fix_proposal",
                        "targetView": "ordered",
                    },
                }
            ],
            {"firstMessageMs": 1, "finalMessageMs": 1},
        )

    monkeypatch.setattr(runner, "_ask_once", fake_ask_once)

    asyncio.run(
        runner._run_cases(
            "ws://test",
            "user",
            [
                {
                    "name": "case-a",
                    "sessionId": "17",
                    "caseId": "G1-exclude-current-plan-english-major",
                    "prompts": [{"prompt": "不要英语相关专业"}],
                }
            ],
            history_db=str(tmp_path / "missing.db"),
            metrics_output=str(metrics_path),
            runtime_shadow_output=str(shadow_path),
        )
    )

    shadow_payload = json.loads(shadow_path.read_text(encoding="utf-8"))
    assert shadow_payload["summary"]["observations"] == 1
    observation = shadow_payload["observations"][0]
    assert observation["caseId"] == "G1-exclude-current-plan-english-major"
    assert observation["runtime"]["pendingType"] == "plan_mutation"
    metrics_payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert metrics_payload["records"][0]["runtimeShadowCaseId"] == "G1-exclude-current-plan-english-major"
    assert metrics_payload["runtimeShadowSummary"]["byPendingType"] == {"plan_mutation": 1}


def test_run_cases_keeps_observability_when_request_fails(monkeypatch, tmp_path):
    db_path = tmp_path / "history.db"
    metrics_path = tmp_path / "metrics.json"
    prompt = "医学护理这些别碰，财会还能接受，先看看影响"
    history = [
        {"parts": [{"part_kind": "user-prompt", "content": prompt}]},
        {
            "model_name": "route-observability",
            "parts": [
                {
                    "part_kind": "text",
                    "content": json.dumps(
                        {
                            "type": "routeObservability",
                            "event": "conversation_turn_event",
                            "routingPath": "full_agent",
                            "routeDecision": {
                                "fallbackReason": "agent_run_interrupted",
                                "agentRun": {
                                    "failedNode": "ModelRequestNode",
                                    "failedNodeElapsedMs": 180000,
                                },
                            },
                        },
                        ensure_ascii=False,
                    ),
                }
            ],
        },
    ]
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
            ("17", json.dumps(history, ensure_ascii=False), "now", "now"),
        )
        conn.commit()

    async def fake_ask_once(*args, **kwargs):
        raise TimeoutError("client timed out")

    monkeypatch.setattr(runner, "_ask_once", fake_ask_once)

    try:
        asyncio.run(
            runner._run_cases(
                "ws://test",
                "user",
                [{"name": "case-a", "sessionId": "17", "prompts": [{"prompt": prompt}]}],
                history_db=str(db_path),
                metrics_output=str(metrics_path),
            )
        )
    except SystemExit as exc:
        assert exc.code == 1

    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    observability = payload["records"][0]["turnObservability"]
    assert observability["routingPath"] == "full_agent"
    assert observability["routeDecision"]["agentRun"]["failedNode"] == "ModelRequestNode"


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


def test_summarize_turn_observability_extracts_route_event_timings():
    turn_messages = [
        {"parts": [{"part_kind": "user-prompt", "content": "高收费的志愿占比多少"}]},
        {
            "model_name": "route-observability",
            "parts": [
                {
                    "part_kind": "text",
                    "content": json.dumps(
                        {
                            "type": "routeObservability",
                            "event": "conversation_turn_event",
                            "routingPath": "semantic_plan_action",
                            "routeDecision": {"route": "review_plan"},
                            "totalDurationMs": 28000,
                            "llmDurationMs": 4200,
                            "toolDurationMs": 900,
                            "toolCallCount": 1,
                        },
                        ensure_ascii=False,
                    ),
                }
            ],
        },
    ]

    observed = runner._summarize_turn_observability(turn_messages)

    assert observed["routeDecision"] == {"route": "review_plan"}
    assert observed["eventTimings"] == {
        "totalDurationMs": 28000,
        "llmDurationMs": 4200,
        "toolDurationMs": 900,
        "toolCallCount": 1,
    }


def test_followup_summary_extracts_targets_and_refresh_flags():
    followups = [
        {"content": {"targetView": "ordered", "refresh": True}},
        {"content": {"targetView": "review", "refresh": False}},
        {"content": {"targetView": "ordered", "refresh": True}},
        {
            "type": "planningWorkspaceAction",
            "content": {
                "type": "planningWorkspaceAction",
                "targetView": "ordered",
                "refresh": True,
                "silent": True,
            },
        },
        {"type": "pendingConfirmationCard", "content": {"type": "pendingConfirmationCard"}},
    ]

    targets, refreshes, types = runner._followup_summary(followups)

    assert targets == ["ordered", "review"]
    assert refreshes == [True, False, True, True]
    assert types == ["planningWorkspaceAction", "pendingConfirmationCard"]


def test_runtime_shadow_observation_extracts_plan_pending_card_and_workspace_target():
    record = {
        "case": "case-a",
        "stepIndex": 1,
        "sessionId": "17",
        "prompt": "把第4个专业组移到第2位",
        "elapsedMs": 1200,
        "turnObservability": {
            "routingPath": "plan_fast_route",
            "toolCallCount": 1,
            "toolReturnCount": 1,
            "actionFamilies": ["move_ordered_unit"],
            "resultKinds": ["preview_only"],
            "replyFocus": ["major_group_order"],
        },
    }
    followups = [
        {
            "type": "pendingConfirmationCard",
            "content": {
                "type": "pendingConfirmationCard",
                "pendingId": "pending-1",
                "kind": "plan_mutation",
                "actionFamily": "move_ordered_unit",
                "targetView": "ordered",
            },
        },
        {
            "type": "planningWorkspaceAction",
            "content": {
                "type": "planningWorkspaceAction",
                "targetView": "ordered",
                "refresh": True,
                "silent": True,
            },
        },
    ]

    observation = runner._build_runtime_shadow_observation(
        {"name": "case-a", "caseId": "G17-tier-local-reorder"},
        {"prompt": "把第4个专业组移到第2位"},
        record,
        followups,
        1,
    )

    assert observation["caseId"] == "G17-tier-local-reorder"
    runtime = observation["runtime"]
    assert runtime["sideEffect"] == "plan_preview"
    assert runtime["outputType"] == "plan_mutation"
    assert runtime["pendingType"] == "plan_mutation"
    assert runtime["executionPayload"] == {"kind": "pending_plan_mutation"}
    assert runtime["displayPayload"] == {"presentation": "confirmation_card"}
    assert runtime["pendingCards"][0]["pendingId"] == "pending-1"
    assert runtime["workspaceRefreshTargets"] == ["ordered"]
    assert runtime["replyFocus"] == ["major_group_order"]


def test_runtime_shadow_observation_builds_latency_profile_diagnostic():
    observation = runner._build_runtime_shadow_observation(
        {
            "name": "case-a",
            "planningStateProfile": {"formalPlanPresent": True, "pendingExists": False},
        },
        {
            "profileCaseId": "G12-latency-decomposition-profile",
            "prompt": "高收费的志愿占比多少 能不能换成便宜的",
            "runtimeObservationProfile": {
                "type": "latency_profile",
                "replyFocus": ["tuition"],
                "toolBudget": {"maxToolCalls": 8, "batchPreferred": True},
            },
        },
        {
            "case": "case-a",
            "stepIndex": 1,
            "sessionId": "35",
            "prompt": "高收费的志愿占比多少 能不能换成便宜的",
            "elapsedMs": 28072,
            "firstMessageMs": 1200,
            "finalMessageMs": 28072,
            "turnObservability": {
                "routingPath": "semantic_plan_action",
                "toolCallCount": 1,
                "toolReturnCount": 1,
                "actionFamilies": ["review_plan"],
                "resultKinds": ["review_result"],
                "routeDecision": {
                    "route": "review_plan",
                    "totalDurationMs": 28000,
                    "llmDurationMs": 4200,
                    "toolDurationMs": 900,
                    "agentRun": {
                        "completed": True,
                        "nodeTimings": [
                            {"node": "ModelRequestNode", "elapsedMs": 4000},
                            {"node": "CallToolsNode", "elapsedMs": 900},
                        ],
                    },
                },
            },
        },
        [
            {
                "type": "planningWorkspaceAction",
                "content": {
                    "type": "planningWorkspaceAction",
                    "targetView": "review",
                    "refresh": True,
                    "silent": True,
                },
            }
        ],
        1,
    )

    runtime = observation["runtime"]
    assert runtime["sideEffect"] == "readonly"
    assert runtime["outputType"] == "latency_profile"
    assert runtime["pendingType"] == "none"
    assert runtime["displayPayload"] == {"presentation": "diagnostic"}
    assert runtime["replyFocus"] == ["tuition"]
    assert runtime["workspaceRefreshTargets"] == ["review"]
    assert runtime["diagnosticPayload"]["decompose"] == [
        "model_planning",
        "tool_calls",
        "final_reply_generation",
    ]
    assert runtime["diagnosticPayload"]["toolCallCount"] == 1
    assert runtime["evidenceContract"]["toolBudget"] == {"maxToolCalls": 8, "batchPreferred": True}


def test_runtime_shadow_observation_detects_multiple_pending_cards():
    record = {"case": "case-a", "stepIndex": 1, "sessionId": "17", "prompt": "改一下"}
    followups = [
        {"type": "pendingConfirmationCard", "content": {"kind": "intent_change"}},
        {"type": "pendingConfirmationCard", "content": {"kind": "plan_mutation"}},
    ]

    observation = runner._build_runtime_shadow_observation(
        {"name": "case-a", "caseId": "G24-pending-stack-conflict-and-replacement"},
        {"prompt": "改一下"},
        record,
        followups,
        1,
    )

    runtime = observation["runtime"]
    assert runtime["sideEffect"] == "multiple_pending"
    assert runtime["outputType"] == "multiple_pending"
    assert runtime["pendingType"] == "multiple"
    assert runtime["displayPayload"]["presentation"] == "multiple_cards"
    assert [card["kind"] for card in runtime["pendingCards"]] == ["intent_change", "plan_mutation"]


def test_runtime_shadow_observation_marks_readonly_while_pending_from_case_profile():
    observation = runner._build_runtime_shadow_observation(
        {
            "name": "case-a",
            "planningStateProfile": {"pendingExists": True},
        },
        {
            "prompt": "先不确认，当前方案里有没有护理",
            "profileCaseId": "G3-readonly-query-while-intent-pending",
        },
        {
            "case": "case-a",
            "stepIndex": 1,
            "sessionId": "17",
            "prompt": "先不确认，当前方案里有没有护理",
            "turnObservability": {"routingPath": "plan_query_fast_route"},
        },
        [],
        2,
    )

    assert observation["caseId"] == "G3-readonly-query-while-intent-pending"
    runtime = observation["runtime"]
    assert runtime["sideEffect"] == "readonly_while_pending"
    assert runtime["outputType"] == "readonly"
    assert runtime["pendingType"] == "unchanged_existing_pending"


def test_runtime_shadow_observation_does_not_treat_readonly_tool_applied_as_pending_apply():
    observation = runner._build_runtime_shadow_observation(
        {"name": "case-a", "planningStateProfile": {"pendingExists": False}},
        {"prompt": "方案里有没有民办的", "profileCaseId": "G32-no-plan-referenced-plan-defensive-reply"},
        {
            "case": "case-a",
            "stepIndex": 1,
            "sessionId": "17",
            "prompt": "方案里有没有民办的",
            "turnObservability": {
                "routingPath": "full_agent",
                "toolCalls": [
                    {
                        "name": "execute_plan_action",
                        "actionFamily": "query_state",
                        "resultKind": "status_overview",
                        "applied": True,
                    }
                ],
                "actionFamilies": ["query_state"],
                "resultKinds": ["status_overview"],
            },
        },
        [],
        1,
    )

    runtime = observation["runtime"]
    assert runtime["sideEffect"] == "readonly"
    assert runtime["outputType"] == "readonly"
    assert runtime["pendingType"] == "none"


def test_runtime_shadow_observation_marks_needs_plan_first_route():
    observation = runner._build_runtime_shadow_observation(
        {"name": "case-a", "planningStateProfile": {"pendingExists": False}},
        {"prompt": "方案里有没有民办的", "profileCaseId": "G32-no-plan-referenced-plan-defensive-reply"},
        {
            "case": "case-a",
            "stepIndex": 1,
            "sessionId": "17",
            "prompt": "方案里有没有民办的",
            "turnObservability": {
                "routingPath": "needs_plan_first_guard",
                "routeDecision": {
                    "route": "needs_plan_first",
                    "referenceResolution": "no_referent",
                    "targetIssues": ["college_type"],
                    "blockingReasons": ["missing_formal_plan"],
                },
            },
        },
        [],
        1,
    )

    runtime = observation["runtime"]
    assert runtime["sideEffect"] == "needs_plan_first"
    assert runtime["outputType"] == "readonly"
    assert runtime["pendingType"] == "none"


def test_runtime_shadow_observation_marks_direct_pending_route_as_apply_existing_pending():
    observation = runner._build_runtime_shadow_observation(
        {"name": "case-a", "planningStateProfile": {"pendingExists": True}},
        {"prompt": "确认执行", "profileCaseId": "G27-apply-pending-then-readonly-followup"},
        {
            "case": "case-a",
            "stepIndex": 1,
            "sessionId": "17",
            "prompt": "确认执行",
            "turnObservability": {"routingPath": "direct_pending_plan_confirm"},
        },
        [],
        1,
    )

    runtime = observation["runtime"]
    assert runtime["sideEffect"] == "apply_existing_pending"
    assert runtime["outputType"] == "apply_then_readonly"
    assert runtime["pendingType"] == "none"
    assert runtime["executionPayload"] == {"kind": "apply_existing_pending_then_readonly"}


def test_runtime_shadow_observation_preserves_post_apply_evidence_plan():
    evidence_plan = {
        "trigger": "apply_pending_then_readonly",
        "requiredInputs": ["active_pending", "formal_ordered_plan_after_apply"],
        "steps": [
            {"step": "apply_existing_pending"},
            {"step": "read_latest_plan_summary"},
            {"step": "review_tier_gradient"},
        ],
        "targetIssues": ["remaining_count", "tier_distribution"],
    }
    observation = runner._build_runtime_shadow_observation(
        {"name": "case-a", "planningStateProfile": {"pendingExists": True}},
        {"prompt": "删完了再看还剩多少", "profileCaseId": "G27-apply-pending-then-readonly-followup"},
        {
            "case": "case-a",
            "stepIndex": 1,
            "sessionId": "17",
            "prompt": "删完了再看还剩多少",
            "turnObservability": {
                "routingPath": "pending_plan_short_text_confirm",
                "routeDecision": {
                    "postApplyEvidencePlan": evidence_plan,
                },
            },
        },
        [],
        1,
    )

    runtime = observation["runtime"]
    assert runtime["sideEffect"] == "apply_pending_then_readonly"
    assert runtime["postApplyEvidencePlan"] == evidence_plan
    assert runtime["turnObservability"]["postApplyEvidencePlan"] == evidence_plan


def test_runtime_shadow_observation_preserves_apply_then_new_request_route():
    observation = runner._build_runtime_shadow_observation(
        {"name": "case-a", "planningStateProfile": {"pendingExists": True}},
        {"prompt": "现在基于这些出方案", "profileCaseId": "G14-apply-pending-then-plan-request"},
        {
            "case": "case-a",
            "stepIndex": 1,
            "sessionId": "17",
            "prompt": "现在基于这些出方案",
            "turnObservability": {
                "routingPath": "pending_intent_short_text_confirm",
                "routeDecision": {
                    "route": "apply_pending_then_new_request",
                },
            },
        },
        [
            {
                "type": "pendingConfirmationCard",
                "content": {
                    "type": "pendingConfirmationCard",
                    "pendingId": "pending-generate",
                    "kind": "plan_mutation",
                    "actionFamily": "generate_plan",
                    "targetView": "ordered",
                },
            }
        ],
        1,
    )

    runtime = observation["runtime"]
    assert runtime["sideEffect"] == "apply_pending_then_new_request"
    assert runtime["outputType"] == "composite"
    assert runtime["pendingType"] == "plan_mutation"
    assert runtime["executionPayload"] == {"kind": "apply_existing_pending_then_followup"}
    assert runtime["pendingCards"][0]["actionFamily"] == "generate_plan"


def test_runtime_shadow_observation_marks_intent_apply_message_code_as_apply_existing_pending():
    observation = runner._build_runtime_shadow_observation(
        {"name": "case-a", "planningStateProfile": {"pendingExists": True}},
        {"prompt": "采纳", "profileCaseId": "G6-apply-intent-pending"},
        {
            "case": "case-a",
            "stepIndex": 1,
            "sessionId": "17",
            "prompt": "采纳",
            "turnObservability": {
                "routingPath": "full_agent",
                "toolCalls": [
                    {
                        "name": "apply_selected_intents",
                        "actionFamily": "apply_selected_intents",
                        "messageCode": "preference_applied",
                        "applied": True,
                    }
                ],
            },
        },
        [],
        1,
    )

    runtime = observation["runtime"]
    assert runtime["sideEffect"] == "apply_existing_pending"
    assert runtime["outputType"] == "apply_then_readonly"
    assert runtime["pendingType"] == "none"


def test_runtime_shadow_observation_requires_explicit_step_case_id_for_multi_step_cases():
    observation = runner._build_runtime_shadow_observation(
        {"name": "case-a", "caseId": "G1-exclude-current-plan-english-major"},
        {"prompt": "确认"},
        {"case": "case-a", "stepIndex": 2, "sessionId": "17", "prompt": "确认"},
        [],
        2,
    )

    assert observation is None


def test_streamed_pending_card_is_classified_as_followup():
    primary, followups = runner._split_primary_and_followup_messages(
        [
            {"type": "pendingConfirmationCard", "content": {"type": "pendingConfirmationCard"}, "end": True},
        ]
    )

    assert primary == []
    assert len(followups) == 1
    assert followups[0]["type"] == "pendingConfirmationCard"


def test_streamed_thinking_and_pending_card_are_split():
    primary, followups = runner._split_primary_and_followup_messages(
        [
            {"type": "thinking", "content": "正在生成这次调整的影响预览...", "end": False},
            {"type": "pendingConfirmationCard", "content": {"type": "pendingConfirmationCard"}, "end": True},
        ]
    )

    assert runner._extract_thinking(primary) == "正在生成这次调整的影响预览..."
    assert runner._extract_text(primary) == ""
    assert [item["type"] for item in followups] == ["pendingConfirmationCard"]


def test_streamed_silent_workspace_action_is_action_followup_but_not_user_text():
    primary, followups = runner._split_primary_and_followup_messages(
        [
            {"type": "thinking", "content": "正在刷新工作台...", "end": False},
            {
                "type": "planningWorkspaceAction",
                "content": {
                    "type": "planningWorkspaceAction",
                    "targetView": "ordered",
                    "refresh": True,
                    "silent": True,
                },
                "end": True,
            },
        ]
    )

    assert runner._extract_thinking(primary) == "正在刷新工作台..."
    assert len(followups) == 1
    assert followups[0]["type"] == "planningWorkspaceAction"
    assert runner._extract_followup_user_text(followups) == ""


def test_content_assertions_reject_followups_when_disallowed():
    violations = runner._check_content_assertions(
        "当前没有上一轮待确认的方案动作。",
        [{"type": "planningWorkspaceAction", "content": {"targetView": "ordered", "refresh": True}}],
        {"prompt": "确认", "assertNoFollowups": True},
        "case-a",
        "17",
    )

    assert any("assertNoFollowups FAILED" in item for item in violations)


def test_content_assertions_ignore_silent_workspace_refresh_when_followups_disallowed():
    violations = runner._check_content_assertions(
        "已将该专业组移动到第 2 位，方案顺序已更新。",
        [
            {
                "type": "planningWorkspaceAction",
                "content": {
                    "type": "planningWorkspaceAction",
                    "targetView": "ordered",
                    "refresh": True,
                    "silent": True,
                },
            }
        ],
        {"prompt": "确认", "assertNoFollowups": True},
        "case-a",
        "17",
    )

    assert violations == []


def test_content_assertions_ignore_thinking_messages_when_followups_disallowed():
    violations = runner._check_content_assertions(
        "我先看一下当前方案。",
        [{"type": "thinking", "content": "正在整理当前方案...", "end": False}],
        {"prompt": "确认", "assertNoFollowups": True},
        "case-a",
        "17",
    )

    assert violations == []


def test_content_assertions_still_reject_visible_followups_after_ignoring_thinking():
    violations = runner._check_content_assertions(
        "我先看一下当前方案。",
        [
            {"type": "thinking", "content": "正在整理当前方案...", "end": False},
            {"type": "planningWorkspaceAction", "content": {"targetView": "ordered", "refresh": True}},
        ],
        {"prompt": "确认", "assertNoFollowups": True},
        "case-a",
        "17",
    )

    assert any("assertNoFollowups FAILED" in item for item in violations)


def test_content_assertions_support_followup_type_and_count():
    violations = runner._check_content_assertions(
        "需要你确认后才会执行。",
        [{"type": "pendingConfirmationCard", "content": {"type": "pendingConfirmationCard"}}],
        {
            "prompt": "按院校层次排序",
            "assertFollowupType": "pendingConfirmationCard",
            "assertFollowupCount": 1,
        },
        "case-a",
        "17",
    )

    assert violations == []


def test_content_assertions_support_actionable_silent_workspace_refresh_assertions():
    violations = runner._check_content_assertions(
        "已采纳，后续会按这个范围看。",
        [
            {
                "type": "planningWorkspaceAction",
                "content": {
                    "type": "planningWorkspaceAction",
                    "targetView": "ordered",
                    "refresh": True,
                    "silent": True,
                },
            },
            {
                "type": "planningWorkspaceAction",
                "content": {
                    "type": "planningWorkspaceAction",
                    "targetView": "candidate",
                    "refresh": True,
                    "silent": True,
                },
            },
        ],
        {
            "prompt": "确认",
            "assertNoFollowups": True,
            "assertActionableFollowupTypes": ["planningWorkspaceAction"],
            "assertActionableFollowupTargets": ["ordered", "candidate"],
            "assertActionableFollowupCount": 2,
        },
        "case-a",
        "17",
    )

    assert violations == []


def test_content_assertions_report_missing_actionable_silent_workspace_refresh():
    violations = runner._check_content_assertions(
        "已采纳，后续会按这个范围看。",
        [],
        {
            "prompt": "确认",
            "assertActionableFollowupTypes": ["planningWorkspaceAction"],
            "assertActionableFollowupTargets": ["ordered"],
            "assertActionableFollowupCount": 1,
        },
        "case-a",
        "17",
    )

    assert any("assertActionableFollowupTypes FAILED" in item for item in violations)
    assert any("assertActionableFollowupTargets FAILED" in item for item in violations)
    assert any("assertActionableFollowupCount FAILED" in item for item in violations)


def test_content_assertions_search_user_visible_followup_text():
    violations = runner._check_content_assertions(
        "",
        [
            {
                "type": "pendingConfirmationCard",
                "content": {
                    "type": "pendingConfirmationCard",
                    "pendingId": "pending-1",
                    "actionFamily": "sort_ordered_plan",
                    "title": "确认方案排序",
                    "summary": "会按推荐系数重新排序当前方案，需要你确认后才会执行。",
                    "confirmText": "确认执行",
                },
            }
        ],
        {
            "prompt": "这版按推荐系数重新排一下",
            "assertContains": ["排序", "确认"],
            "assertContainsAny": ["推荐系数", "导出顺序"],
            "assertNotContains": ["actionFamily"],
        },
        "case-a",
        "17",
    )

    assert violations == []


def test_content_assertions_report_missing_followup_type_and_count():
    violations = runner._check_content_assertions(
        "需要你确认后才会执行。",
        [],
        {
            "prompt": "按院校层次排序",
            "assertFollowupType": "pendingConfirmationCard",
            "assertFollowupCount": 1,
        },
        "case-a",
        "17",
    )

    assert any("assertFollowupType FAILED" in item for item in violations)
    assert any("assertFollowupCount FAILED" in item for item in violations)


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


def test_tool_assertions_can_require_exact_tool_sequence():
    violations = runner._check_tool_assertions(
        {
            "routingPath": "pending_readonly_plan_query",
            "actionFamilies": ["query_ordered"],
            "resultKinds": ["ordered_snapshot"],
            "toolCalls": [
                {"name": "compare_major_options"},
            ]
        },
        {
            "prompt": "财管会计审计怎么排",
            "expectedRoutingPath": "pending_readonly_plan_query",
            "assertActionFamiliesContain": ["query_ordered"],
            "assertResultKindsContain": ["ordered_snapshot"],
            "expectedToolNames": ["compare_major_options"],
            "expectedToolCounts": {"compare_major_options": 1},
            "assertToolNamesNotContain": ["compare_majors"],
            "assertNoRepeatedToolNames": True,
        },
        "case-tools",
        "880640",
    )

    assert violations == []


def test_tool_assertions_report_repeated_or_forbidden_tools():
    violations = runner._check_tool_assertions(
        {
            "routingPath": "full_agent",
            "actionFamilies": ["query_state"],
            "resultKinds": ["status_overview"],
            "toolCalls": [
                {"name": "get_major_introduction"},
                {"name": "get_major_introduction"},
            ]
        },
        {
            "prompt": "建筑城乡规划要不要美术基础",
            "expectedRoutingPath": "pending_readonly_plan_query",
            "assertActionFamiliesContain": ["query_ordered"],
            "assertResultKindsContain": ["ordered_snapshot"],
            "expectedToolNames": ["get_major_introductions"],
            "assertToolNamesNotContain": ["get_major_introduction"],
            "maxToolCallCount": 1,
            "assertNoRepeatedToolNames": True,
        },
        "case-tools",
        "880636",
    )

    assert any("expectedToolNames FAILED" in item for item in violations)
    assert any("expectedRoutingPath FAILED" in item for item in violations)
    assert any("assertActionFamiliesContain FAILED" in item for item in violations)
    assert any("assertResultKindsContain FAILED" in item for item in violations)
    assert any("assertToolNamesNotContain FAILED" in item for item in violations)
    assert any("maxToolCallCount FAILED" in item for item in violations)
    assert any("assertNoRepeatedToolNames FAILED" in item for item in violations)


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
            {
                "case": "a",
                "sessionId": "17",
                "prompt": "p1",
                "elapsedMs": 1000,
                "fixtureType": "formal_plan_present",
                "expectedRootCause": "product_defect",
            },
            {"case": "b", "sessionId": "17", "prompt": "p2", "elapsedMs": 3000, "fixtureType": "formal_plan_present"},
            {"case": "c", "sessionId": "16", "prompt": "p3", "elapsedMs": 2000},
            {"case": "d", "sessionId": "16", "prompt": "p4", "elapsedMs": 500, "error": "Timeout"},
            {
                "case": "e",
                "sessionId": "16",
                "prompt": "p5",
                "elapsedMs": 800,
                "contentViolations": ["missing answer"],
                "expectedRootCause": "fixture_mismatch",
            },
            {
                "case": "f",
                "sessionId": "16",
                "prompt": "p6",
                "elapsedMs": 900,
                "toolViolations": ["wrong tool"],
                "performanceViolations": ["too slow"],
            },
        ]
    )

    assert summary["steps"] == 6
    assert summary["successfulSteps"] == 3
    assert summary["failedSteps"] == 3
    assert summary["failedByReason"] == {
        "request": 1,
        "content": 1,
        "tool": 1,
        "performance": 1,
    }
    assert summary["elapsed"]["medianMs"] == 2000
    assert summary["slowest"][0]["case"] == "b"
    assert summary["byFixture"] == {"formal_plan_present": 2}
    assert summary["byExpectedRootCause"] == {"product_defect": 1, "fixture_mismatch": 1}
    assert summary["failedByExpectedRootCause"] == {"fixture_mismatch": 1}


def test_fixture_and_root_cause_fields_accept_case_and_step_overrides():
    record = {}
    case = {
        "fixtureContract": {"type": "empty_plan", "requiredState": []},
        "expectedRootCause": "fixture_mismatch",
    }
    step = {"expectedRootCause": "assertion_noise"}

    runner._add_fixture_and_root_cause_fields(record, case, step)

    assert record["fixtureType"] == "empty_plan"
    assert record["fixtureContract"] == {"type": "empty_plan", "requiredState": []}
    assert record["expectedRootCause"] == "assertion_noise"


def test_metrics_summary_reports_fast_route_arbitration_distribution():
    summary = runner._build_metrics_summary(
        [
            {
                "case": "a",
                "sessionId": "17",
                "prompt": "当前方案里有没有法学",
                "elapsedMs": 1000,
                "turnObservability": {
                    "fastRouteArbitration": {
                        "selectedPath": "plan_query_fast_route",
                        "semanticArbitrationNeeded": False,
                        "semanticArbitrationCandidatePaths": ["plan_query_fast_route"],
                    }
                },
            },
            {
                "case": "b",
                "sessionId": "17",
                "prompt": "医学别碰，先看看影响",
                "elapsedMs": 2000,
                "turnObservability": {
                    "fastRouteArbitration": {
                        "selectedPath": "major_intent_fast_route",
                        "semanticArbitrationNeeded": True,
                        "semanticArbitrationReason": "intent_plan_mixed_candidates",
                        "semanticArbitrationCandidatePaths": [
                            "plan_query_fast_route",
                            "major_intent_fast_route",
                        ],
                    }
                },
            },
        ]
    )

    arbitration = summary["fastRouteArbitration"]
    assert arbitration["observed"] == 2
    assert arbitration["semanticArbitrationNeeded"] == 1
    assert arbitration["selectedPaths"] == {
        "plan_query_fast_route": 1,
        "major_intent_fast_route": 1,
    }
    assert arbitration["neededReasons"] == {"intent_plan_mixed_candidates": 1}
    assert arbitration["candidatePaths"]["plan_query_fast_route"] == 2
    assert arbitration["neededExamples"][0]["prompt"] == "医学别碰，先看看影响"
