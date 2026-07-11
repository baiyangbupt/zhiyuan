import importlib.util
import asyncio
import json
import sqlite3
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest


RUNNER_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_regression_runner.py"
SPEC = importlib.util.spec_from_file_location("dialog_regression_runner", RUNNER_PATH)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def test_runner_defaults_use_isolated_320_debug_ports(monkeypatch):
    for name in (
        "ZHIYUAN_REGRESSION_AGENT_URL",
        "AGENT_DIALOG_E2E_URL",
        "ZHIYUAN_REGRESSION_BACKEND_URL",
        "INTERNAL_SERVICE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    spec = importlib.util.spec_from_file_location("dialog_regression_runner_default_ports", RUNNER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.DEFAULT_URL == "ws://127.0.0.1:18291/gaotu-assistant-agent/plus/chat/1/bot/test/do"
    assert module.DEFAULT_INTERNAL_SERVICE_URL == "http://127.0.0.1:18290"


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


def test_apply_session_offset_clones_formal_plan_fixture_from_base_session():
    cases = [
        {
            "name": "case-formal-plan",
            "sessionId": "26",
            "fixtureContract": {
                "type": "formal_plan_present",
                "requiredState": ["orderedPlan"],
            },
            "prompts": ["帮我把保底区里录取率最高的那个调到保底的第一位"],
        }
    ]

    adjusted = runner._apply_session_offset(cases, 22400000)

    assert adjusted[0]["sessionId"] == "22400026"
    assert adjusted[0]["baseSessionId"] == "26"
    assert adjusted[0]["cloneBackendStateFromSessionId"] == "26"
    assert "cloneBackendStateFromSessionId" not in cases[0]


def test_apply_session_offset_can_clone_backend_state_for_offset_cases():
    cases = [
        {
            "name": "quality-case-without-fixture-contract",
            "sessionId": "17",
            "prompts": ["这方案咋样"],
        }
    ]

    adjusted = runner._apply_session_offset(
        cases,
        10000000,
        clone_backend_state_from_offset=True,
    )

    assert adjusted[0]["sessionId"] == "10000017"
    assert adjusted[0]["baseSessionId"] == "17"
    assert adjusted[0]["cloneBackendStateFromSessionId"] == "17"
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


def test_backend_state_clone_keys_include_pending_only_for_active_pending_fixture():
    active_pending_case = {
        "fixtureContract": {
            "type": "pending_exists",
            "requiredState": ["activePending", "orderedPlan"],
        }
    }
    normal_case = {
        "fixtureContract": {
            "type": "formal_plan_present",
            "requiredState": ["orderedPlan"],
        }
    }

    assert runner._backend_state_clone_keys_for_case(active_pending_case) == (
        "planningState",
        "userprofile",
        "userScoreDetail",
        "pendingConfirmation",
    )
    assert runner._backend_state_clone_keys_for_case(normal_case) == (
        "planningState",
        "userprofile",
        "userScoreDetail",
    )


def test_clone_results_have_active_pending_requires_non_empty_active_source():
    assert runner._clone_results_have_active_pending(
        [{"key": "pendingConfirmation", "ok": True, "sourcePendingStatus": "active"}]
    )
    assert not runner._clone_results_have_active_pending(
        [{"key": "pendingConfirmation", "ok": True, "skipped": "source_empty"}]
    )


def test_run_cases_can_clone_score_from_separate_backend_source(monkeypatch, tmp_path, capsys):
    clone_calls = []
    ask_calls = []

    async def fake_ask_once(*args, **kwargs):
        ask_calls.append((args, kwargs))
        return ([{"type": "text", "content": "当前还没有生成方案。"}], [], {"firstMessageMs": 1, "finalMessageMs": 1})

    def fake_clone_backend_session_state(base_url, *, source_session_id, target_session_id, keys):
        clone_calls.append((base_url, source_session_id, target_session_id, keys))
        return [
            {
                "sourceSession": source_session_id,
                "targetSession": target_session_id,
                "key": key,
                "ok": True,
            }
            for key in keys
        ]

    monkeypatch.setattr(runner, "_ask_once", fake_ask_once)
    monkeypatch.setattr(runner, "_clone_backend_session_state", fake_clone_backend_session_state)

    asyncio.run(
        runner._run_cases(
            "ws://test",
            "user",
            [
                {
                    "name": "case-no-plan-with-score",
                    "sessionId": "9904232",
                    "cloneBackendStateFromSessionId": "55001413",
                    "cloneBackendScoreFromSessionId": "26",
                    "fixtureContract": {
                        "type": "empty_plan",
                        "requiredState": ["profileReady"],
                    },
                    "prompts": [{"prompt": "方案里有没有民办的"}],
                }
            ],
            history_db=str(tmp_path / "missing.db"),
            internal_service_url="http://backend.test",
        )
    )

    assert ask_calls
    assert clone_calls == [
        ("http://backend.test", "55001413", "9904232", ("planningState", "userprofile", "userScoreDetail")),
        ("http://backend.test", "26", "9904232", ("userScoreDetail",)),
    ]
    output = capsys.readouterr().out
    assert "clonedCaseBackendState=" in output
    assert "clonedCaseBackendScoreState=" in output
    assert not runner._clone_results_have_active_pending(
        [{"key": "pendingConfirmation", "ok": True, "sourcePendingStatus": "applied"}]
    )


def test_backend_extra_data_assertions_compare_after_with_before():
    before = {
        "version": 12,
        "orderedPlanState": {"units": ["u1", "u2", "u3"]},
        "constraintState": {"hardConstraints": {"mustExcludeSchools": []}},
    }
    after = {
        "version": 13,
        "orderedPlanState": {"units": ["u1", "u3"]},
        "constraintState": {"hardConstraints": {"mustExcludeSchools": ["院校性质:民办"]}},
    }

    assert runner._check_single_backend_assertion(
        {"path": "version", "greaterThanBefore": True},
        actual_root=after,
        before_root=before,
    )[0]
    assert runner._check_single_backend_assertion(
        {"path": "orderedPlanState.units", "lengthChangedBy": -1},
        actual_root=after,
        before_root=before,
    )[0]
    assert runner._check_single_backend_assertion(
        {"path": "constraintState.hardConstraints.mustExcludeSchools", "contains": "院校性质:民办"},
        actual_root=after,
        before_root=before,
    )[0]


def test_backend_extra_data_assertions_support_nested_numeric_field_max():
    state = {
        "orderedPlanState": {
            "units": [
                {"majorItems": [{"majorName": "软件工程", "tuitionPerYear": 18000}]},
                {"majorItems": [{"majorName": "计算机", "tuitionPerYear": 20000}]},
            ]
        }
    }

    assert runner._check_single_backend_assertion(
        {
            "path": "orderedPlanState.units",
            "maxNumericFieldLessThanOrEqual": {"field": "tuitionPerYear", "value": 20000},
        },
        actual_root=state,
        before_root=None,
    )[0]
    passed, failures = runner._check_single_backend_assertion(
        {
            "path": "orderedPlanState.units",
            "maxNumericFieldLessThanOrEqual": {"field": "tuitionPerYear", "value": 10000},
        },
        actual_root=state,
        before_root=None,
    )
    assert not passed
    assert any("tuitionPerYear<=10000" in item for item in failures)


def test_run_cases_supports_backend_extra_data_assertions(monkeypatch, tmp_path):
    metrics_path = tmp_path / "metrics.json"
    backend_state = {
        "planningState": {
            "version": 3,
            "orderedPlanState": {"units": ["u1", "u2", "u3"]},
        },
        "pendingConfirmation": {"status": "active"},
    }

    async def fake_ask_once(*args, **kwargs):
        backend_state["planningState"] = {
            "version": 4,
            "orderedPlanState": {"units": ["u1", "u3"]},
        }
        backend_state["pendingConfirmation"] = {"status": "applied"}
        return ([{"type": "text", "content": "已移出1个志愿组。"}], [], {"firstMessageMs": 1, "finalMessageMs": 1})

    def fake_get_backend_assertion_data(base_url, session_id, key, *, timeout_seconds=5):
        assert base_url == "http://backend.test"
        assert session_id == "9904301"
        return deepcopy(backend_state.get(key, {}))

    monkeypatch.setattr(runner, "_ask_once", fake_ask_once)
    monkeypatch.setattr(runner, "_get_backend_assertion_data", fake_get_backend_assertion_data)

    asyncio.run(
        runner._run_cases(
            "ws://test",
            "user",
            [
                {
                    "name": "case-backend-assert",
                    "sessionId": "9904301",
                    "prompts": [
                        {
                            "prompt": "确认执行",
                            "assertBackendExtraData": [
                                {"key": "pendingConfirmation", "path": "status", "equals": "applied"},
                                {"key": "planningState", "path": "version", "greaterThanBefore": True},
                                {"key": "planningState", "path": "orderedPlanState.units", "lengthChangedBy": -1},
                            ],
                        }
                    ],
                }
            ],
            history_db=str(tmp_path / "missing.db"),
            metrics_output=str(metrics_path),
            internal_service_url="http://backend.test",
        )
    )

    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert payload["summary"]["failedSteps"] == 0
    assert payload["records"][0]["backendAssertions"] == [
        {"key": "pendingConfirmation", "path": "status", "passed": True},
        {"key": "planningState", "path": "version", "passed": True},
        {"key": "planningState", "path": "orderedPlanState.units", "passed": True},
    ]


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


def test_runtime_observation_preserves_unsupported_local_action_route():
    observation = runner._build_runtime_observation(
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


def test_runtime_observation_uses_route_display_payload_for_conditional_options():
    observation = runner._build_runtime_observation(
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
                "routingPath": "zhiyuan_agent_direct",
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


def test_clone_backend_chat_session_row_retries_mysql_deadlock(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if len(calls) == 1:
            return subprocess.CompletedProcess(
                cmd,
                1,
                stdout="",
                stderr="ERROR 1213 (40001): Deadlock found when trying to get lock",
            )
        return subprocess.CompletedProcess(cmd, 0, stdout="1\n", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)

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
    assert result["attempts"] == 2
    assert len(calls) == 2


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


def test_clone_backend_volunteer_data_files_skips_same_session(tmp_path):
    (tmp_path / "session_volunteer_17.json").write_text('{"detailList":[]}', encoding="utf-8")

    result = runner._clone_backend_volunteer_data_files(
        source_session_id="17",
        target_session_id="17",
        data_dir=tmp_path,
    )

    assert result["ok"] is True
    assert result["skipped"] == "same_session"
    assert result["copiedFiles"] == 0


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


def test_clear_backend_pending_state_clears_latest_version(monkeypatch):
    requests_seen = []

    class FakeResponse:
        status = 200

        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")

    def fake_urlopen(req, timeout=5):
        if isinstance(req, str):
            return FakeResponse({"code": 0, "data": {"dataVersion": 248}})
        body = json.loads(req.data.decode("utf-8"))
        requests_seen.append(body)
        return FakeResponse({"code": 0, "data": body})

    monkeypatch.setattr(runner.request, "urlopen", fake_urlopen)

    results = runner._clear_backend_pending_state("http://backend.test", ["9904301"])

    pending_versions = [
        item["version"]
        for item in requests_seen
        if item["dataKey"] == "pendingConfirmation"
    ]
    assert pending_versions == [0, 248]
    assert all(item["ok"] for item in results)


def test_run_cases_keeps_cloned_active_backend_pending(monkeypatch, tmp_path, capsys):
    clear_calls = []
    clone_calls = []

    async def fake_ask_once(*args, **kwargs):
        return ([{"type": "text", "content": "方案已经有了。"}], [], {"firstMessageMs": 1, "finalMessageMs": 1})

    def fake_clear_backend_pending_state(base_url, session_ids):
        clear_calls.append((base_url, session_ids))
        return [{"session": session_ids[0], "key": "pendingConfirmation", "ok": True}]

    def fake_clone_backend_session_state(base_url, *, source_session_id, target_session_id, keys):
        clone_calls.append((base_url, source_session_id, target_session_id, keys))
        return [
            {
                "sourceSession": source_session_id,
                "targetSession": target_session_id,
                "key": "pendingConfirmation",
                "ok": True,
                "sourcePendingStatus": "active",
                "sourcePendingKind": "plan_mutation",
            }
        ]

    monkeypatch.setattr(runner, "_ask_once", fake_ask_once)
    monkeypatch.setattr(runner, "_clear_backend_pending_state", fake_clear_backend_pending_state)
    monkeypatch.setattr(runner, "_clone_backend_session_state", fake_clone_backend_session_state)

    asyncio.run(
        runner._run_cases(
            "ws://test",
            "user",
            [
                {
                    "name": "case-pending",
                    "sessionId": "9903235",
                    "cloneBackendStateFromSessionId": "35",
                    "fixtureContract": {
                        "type": "pending_exists",
                        "requiredState": ["activePending", "orderedPlan"],
                    },
                    "prompts": [{"prompt": "看看方案", "assertContains": ["方案"]}],
                }
            ],
            history_db=str(tmp_path / "missing.db"),
            clear_backend_pending_per_case=True,
            internal_service_url="http://backend.test",
        )
    )

    assert clear_calls == []
    assert clone_calls == [
        (
            "http://backend.test",
            "35",
            "9903235",
            ("planningState", "userprofile", "userScoreDetail", "pendingConfirmation"),
        )
    ]
    output = capsys.readouterr().out
    assert "skippedCaseBackendPendingClear=" in output
    assert "cloned_source_active_pending" in output


def test_run_cases_fails_fast_when_backend_clone_fails(monkeypatch, tmp_path):
    metrics_path = tmp_path / "metrics.json"
    ask_calls = []

    async def fake_ask_once(*args, **kwargs):
        ask_calls.append(args)
        return ([{"type": "text", "content": "不应该进入 websocket"}], [], {"firstMessageMs": 1, "finalMessageMs": 1})

    def fake_clone_backend_session_state(base_url, *, source_session_id, target_session_id, keys):
        assert base_url == "http://backend.test"
        assert source_session_id == "35"
        assert target_session_id == "9903235"
        assert keys == ("planningState", "userprofile", "userScoreDetail")
        return [
            {
                "sourceSession": source_session_id,
                "targetSession": target_session_id,
                "key": "planningState",
                "ok": False,
                "error": "HTTPError: HTTP Error 404",
            }
        ]

    monkeypatch.setattr(runner, "_ask_once", fake_ask_once)
    monkeypatch.setattr(runner, "_clone_backend_session_state", fake_clone_backend_session_state)

    with pytest.raises(SystemExit) as exc_info:
        asyncio.run(
            runner._run_cases(
                "ws://test",
                "user",
                [
                    {
                        "name": "case-clone",
                        "sessionId": "9903235",
                        "cloneBackendStateFromSessionId": "35",
                        "fixtureContract": {"type": "pending_exists", "requiredState": ["orderedPlan"]},
                        "prompts": [{"prompt": "看看方案"}],
                    }
                ],
                history_db=str(tmp_path / "missing.db"),
                metrics_output=str(metrics_path),
                internal_service_url="http://backend.test",
            )
        )

    assert exc_info.value.code == 1
    assert ask_calls == []
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert payload["summary"]["failedByReason"] == {"environment": 1}
    record = payload["records"][0]
    assert record["failureReason"] == "environment"
    assert record["fixtureType"] == "pending_exists"
    assert "backend state clone had failures" in record["error"]


def test_run_cases_fails_fast_when_backend_chat_session_clone_fails(monkeypatch, tmp_path):
    metrics_path = tmp_path / "metrics.json"
    ask_calls = []

    async def fake_ask_once(*args, **kwargs):
        ask_calls.append(args)
        return ([{"type": "text", "content": "不应该进入 websocket"}], [], {"firstMessageMs": 1, "finalMessageMs": 1})

    def fake_clone_backend_chat_session_row(**kwargs):
        return {
            "sourceSession": kwargs["source_session_id"],
            "targetSession": kwargs["target_session_id"],
            "table": "assistant_chat_session",
            "ok": False,
            "error": "ERROR 1045 access denied",
        }

    def fake_clone_backend_volunteer_data_files(**kwargs):
        return {"ok": True, "copiedFiles": 2}

    def fake_clone_backend_session_state(base_url, *, source_session_id, target_session_id, keys):
        return [{"sourceSession": source_session_id, "targetSession": target_session_id, "key": key, "ok": True} for key in keys]

    monkeypatch.setattr(runner, "_ask_once", fake_ask_once)
    monkeypatch.setattr(runner, "_clone_backend_chat_session_row", fake_clone_backend_chat_session_row)
    monkeypatch.setattr(runner, "_clone_backend_volunteer_data_files", fake_clone_backend_volunteer_data_files)
    monkeypatch.setattr(runner, "_clone_backend_session_state", fake_clone_backend_session_state)

    with pytest.raises(SystemExit) as exc_info:
        asyncio.run(
            runner._run_cases(
                "ws://test",
                "user",
                [
                    {
                        "name": "case-chat-clone",
                        "sessionId": "9903235",
                        "cloneBackendStateFromSessionId": "35",
                        "fixtureContract": {"type": "formal_plan_present"},
                        "prompts": [{"prompt": "确认"}],
                    }
                ],
                history_db=str(tmp_path / "missing.db"),
                metrics_output=str(metrics_path),
                internal_service_url="http://backend.test",
                clone_backend_chat_session=True,
            )
        )

    assert exc_info.value.code == 1
    assert ask_calls == []
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert payload["summary"]["failedByReason"] == {"environment": 1}
    record = payload["records"][0]
    assert record["failureReason"] == "environment"
    assert "backend chat session clone failed" in record["error"]


def test_run_cases_fails_fast_when_backend_volunteer_clone_fails(monkeypatch, tmp_path):
    metrics_path = tmp_path / "metrics.json"
    ask_calls = []

    async def fake_ask_once(*args, **kwargs):
        ask_calls.append(args)
        return ([{"type": "text", "content": "不应该进入 websocket"}], [], {"firstMessageMs": 1, "finalMessageMs": 1})

    def fake_clone_backend_chat_session_row(**kwargs):
        return {
            "sourceSession": kwargs["source_session_id"],
            "targetSession": kwargs["target_session_id"],
            "table": "assistant_chat_session",
            "ok": True,
            "insertedRows": 1,
        }

    def fake_clone_backend_volunteer_data_files(**kwargs):
        return {"ok": False, "error": "required original session_volunteer file is missing"}

    def fake_clone_backend_session_state(base_url, *, source_session_id, target_session_id, keys):
        return [{"sourceSession": source_session_id, "targetSession": target_session_id, "key": key, "ok": True} for key in keys]

    monkeypatch.setattr(runner, "_ask_once", fake_ask_once)
    monkeypatch.setattr(runner, "_clone_backend_chat_session_row", fake_clone_backend_chat_session_row)
    monkeypatch.setattr(runner, "_clone_backend_volunteer_data_files", fake_clone_backend_volunteer_data_files)
    monkeypatch.setattr(runner, "_clone_backend_session_state", fake_clone_backend_session_state)

    with pytest.raises(SystemExit) as exc_info:
        asyncio.run(
            runner._run_cases(
                "ws://test",
                "user",
                [
                    {
                        "name": "case-volunteer-clone",
                        "sessionId": "9903235",
                        "cloneBackendStateFromSessionId": "35",
                        "fixtureContract": {"type": "formal_plan_present"},
                        "flow": ["final_action"],
                        "prompts": [{"prompt": "确认"}],
                    }
                ],
                history_db=str(tmp_path / "missing.db"),
                metrics_output=str(metrics_path),
                internal_service_url="http://backend.test",
                clone_backend_chat_session=True,
            )
        )

    assert exc_info.value.code == 1
    assert ask_calls == []
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert payload["summary"]["failedByReason"] == {"environment": 1}
    record = payload["records"][0]
    assert record["failureReason"] == "environment"
    assert "backend volunteer data clone failed" in record["error"]


def test_run_cases_allows_missing_volunteer_clone_for_non_final_action_case(monkeypatch, tmp_path):
    metrics_path = tmp_path / "metrics.json"
    ask_calls = []

    async def fake_ask_once(*args, **kwargs):
        ask_calls.append(args)
        return ([{"type": "text", "content": "已记录这次要求。"}], [], {"firstMessageMs": 1, "finalMessageMs": 1})

    def fake_clone_backend_chat_session_row(**kwargs):
        return {
            "sourceSession": kwargs["source_session_id"],
            "targetSession": kwargs["target_session_id"],
            "table": "assistant_chat_session",
            "ok": True,
            "insertedRows": 1,
        }

    def fake_clone_backend_volunteer_data_files(**kwargs):
        return {"ok": False, "error": "required original session_volunteer file is missing"}

    def fake_clone_backend_session_state(base_url, *, source_session_id, target_session_id, keys):
        return [{"sourceSession": source_session_id, "targetSession": target_session_id, "key": key, "ok": True} for key in keys]

    monkeypatch.setattr(runner, "_ask_once", fake_ask_once)
    monkeypatch.setattr(runner, "_clone_backend_chat_session_row", fake_clone_backend_chat_session_row)
    monkeypatch.setattr(runner, "_clone_backend_volunteer_data_files", fake_clone_backend_volunteer_data_files)
    monkeypatch.setattr(runner, "_clone_backend_session_state", fake_clone_backend_session_state)

    asyncio.run(
        runner._run_cases(
            "ws://test",
            "user",
            [
                {
                    "name": "case-observation-clone",
                    "sessionId": "9903235",
                    "cloneBackendStateFromSessionId": "35",
                    "prompts": [{"prompt": "法学可以重点看看"}],
                }
            ],
            history_db=str(tmp_path / "missing.db"),
            metrics_output=str(metrics_path),
            internal_service_url="http://backend.test",
            clone_backend_chat_session=True,
        )
    )

    assert len(ask_calls) == 1
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert payload["summary"]["successfulSteps"] == 1
    assert payload["warnings"]
    assert "backend volunteer data clone failed" in payload["warnings"][0]


def test_run_cases_writes_runtime_observation_output(monkeypatch, tmp_path):
    observation_path = tmp_path / "runtime-observation.json"
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
            runtime_observation_output=str(observation_path),
        )
    )

    observation_payload = json.loads(observation_path.read_text(encoding="utf-8"))
    assert observation_payload["summary"]["observations"] == 1
    observation = observation_payload["observations"][0]
    assert observation["caseId"] == "G1-exclude-current-plan-english-major"
    assert observation["runtime"]["pendingType"] == "plan_mutation"
    metrics_payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert metrics_payload["records"][0]["runtimeObservationCaseId"] == "G1-exclude-current-plan-english-major"
    assert metrics_payload["runtimeObservationSummary"]["byPendingType"] == {"plan_mutation": 1}


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
    turn_messages = [
        {"parts": [{"part_kind": "user-prompt", "content": "把第4个专业组移到第2位"}]},
        {
            "parts": [
                {
                    "part_kind": "tool-call",
                    "tool_name": "preview_plan_action",
                    "tool_call_id": "functions.preview_plan_action:1",
                    "args": {
                        "action_family": "move_ordered_unit",
                        "current_stage": "preview",
                    },
                }
            ]
        },
        {
            "parts": [
                {
                    "part_kind": "tool-return",
                    "tool_name": "preview_plan_action",
                    "tool_call_id": "functions.preview_plan_action:1",
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
    assert observed["toolCalls"][0]["name"] == "preview_plan_action"
    assert observed["toolCalls"][0]["actionFamily"] == "move_ordered_unit"
    assert observed["toolCalls"][0]["stage"] == "preview"
    assert observed["toolCalls"][0]["resultKind"] == "preview_only"
    assert observed["toolCalls"][0]["applied"] is False


def test_summarize_turn_observability_infers_routing_path_from_direct_pending_history():
    turn_messages = [
        {"parts": [{"part_kind": "user-prompt", "content": "确认执行"}]},
        {
            "model_name": "direct-pending-plan-confirmation",
            "parts": [
                {
                    "part_kind": "tool-call",
                    "tool_name": "confirm_pending",
                    "tool_call_id": "direct-pending-plan-confirmation:1",
                    "args": {"action_family": "remove_units"},
                }
            ],
        },
        {
            "parts": [
                {
                    "part_kind": "tool-return",
                    "tool_name": "confirm_pending",
                    "tool_call_id": "direct-pending-plan-confirmation:1",
                    "content": json.dumps(
                        {
                            "action_family": "remove_units",
                            "stage": "apply",
                        },
                        ensure_ascii=False,
                    ),
                }
            ]
        },
    ]

    observed = runner._summarize_turn_observability(turn_messages)

    assert observed["routingPath"] == "direct_pending_plan_confirm"
    assert observed["actionFamilies"] == ["remove_units"]


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


def test_summarize_turn_observability_extracts_semantic_frame_observation():
    observation = {
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
            "model_name": "route-observability",
            "parts": [
                {
                    "part_kind": "text",
                    "content": json.dumps(
                        {
                            "event": "conversation_turn_event",
                            "routingPath": "zhiyuan_agent_direct",
                        },
                        ensure_ascii=False,
                    ),
                }
            ],
        },
        {
            "model_name": "semantic-frame-observation",
            "parts": [
                {
                    "part_kind": "text",
                    "content": json.dumps(
                        {"type": "semanticFrameObservation", "semanticFrameObservation": observation},
                        ensure_ascii=False,
                    ),
                }
            ],
        },
    ]

    observed = runner._summarize_turn_observability(turn_messages)

    assert observed["routingPath"] == "zhiyuan_agent_direct"
    assert observed["semanticFrameObservation"]["status"] == "success"
    assert observed["semanticFrameObservation"]["frame"]["taskLayer"] == "explore"


def test_summarize_turn_observability_does_not_infer_route_from_plain_tool_name():
    turn_messages = [
        {
            "model_name": "test-model",
            "parts": [
                {
                    "part_kind": "tool-call",
                    "tool_name": "query_plan",
                    "tool_call_id": "functions.query_plan:1",
                    "args": {"query": "看看方案"},
                }
            ],
        }
    ]

    observed = runner._summarize_turn_observability(turn_messages)

    assert "routingPath" not in observed
    assert observed["toolCalls"][0]["name"] == "query_plan"


def test_summarize_turn_observability_counts_plain_text_tool_returns():
    turn_messages = [
        {
            "parts": [
                {
                    "part_kind": "tool-call",
                    "tool_name": "compare_entities",
                    "tool_call_id": "functions.compare_entities:1",
                    "args": {"entity_type": "major", "names": ["法学", "财政学"]},
                }
            ]
        },
        {
            "parts": [
                {
                    "part_kind": "tool-return",
                    "tool_name": "compare_entities",
                    "tool_call_id": "functions.compare_entities:1",
                    "content": "法学和财政学的对比文本",
                }
            ]
        },
    ]

    observed = runner._summarize_turn_observability(turn_messages)

    assert observed["toolCallCount"] == 1
    assert observed["toolReturnCount"] == 1
    assert observed["toolCalls"][0]["name"] == "compare_entities"


def test_summarize_turn_observability_extracts_route_decision():
    route_decision = {
        "source": "zhiyuan_agent",
        "matched": True,
        "route": "direct",
        "firstToolNames": ["query_plan"],
    }
    turn_messages = [
        {
            "parts": [
                {
                    "part_kind": "text",
                    "content": json.dumps(
                        {
                            "event": "conversation_turn_event",
                            "routingPath": "zhiyuan_agent_direct",
                            "routeDecision": route_decision,
                        },
                        ensure_ascii=False,
                    ),
                }
            ]
        }
    ]

    observed = runner._summarize_turn_observability(turn_messages)

    assert observed["routingPath"] == "zhiyuan_agent_direct"
    assert observed["routeDecision"] == route_decision
    assert set(observed) >= {"routingPath", "routeDecision"}


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
                            "routingPath": "zhiyuan_agent_direct",
                            "routeDecision": {"route": "review_plan"},
                            "totalDurationMs": 28000,
                            "llmDurationMs": 4200,
                            "toolDurationMs": 900,
                            "classificationDurationMs": 12000,
                            "preSemanticRouteDurationMs": 14000,
                            "historyLoadDurationMs": 110,
                            "pendingLoadDurationMs": 70,
                            "initialStateLoadDurationMs": 130,
                            "runtimeHistoryBuildDurationMs": 40,
                            "backendContextLoadDurationMs": 850,
                            "requestContextBuildDurationMs": 30,
                            "guardPipelineDurationMs": 7900,
                            "turnDecisionDurationMs": 5100,
                            "turnDecisionCacheHitCount": 1,
                            "intentEntityProfileDurationMs": 1700,
                            "intentSideEffectDurationMs": 900,
                            "unattributedDurationMs": 10900,
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
        "classificationDurationMs": 12000,
        "preSemanticRouteDurationMs": 14000,
        "historyLoadDurationMs": 110,
        "pendingLoadDurationMs": 70,
        "initialStateLoadDurationMs": 130,
        "runtimeHistoryBuildDurationMs": 40,
        "backendContextLoadDurationMs": 850,
        "requestContextBuildDurationMs": 30,
        "guardPipelineDurationMs": 7900,
        "turnDecisionDurationMs": 5100,
        "turnDecisionCacheHitCount": 1,
        "intentEntityProfileDurationMs": 1700,
        "intentSideEffectDurationMs": 900,
        "unattributedDurationMs": 10900,
        "toolCallCount": 1,
    }


def test_summarize_turn_observability_extracts_action_family_from_route_event_tool_calls():
    turn_messages = [
        {"parts": [{"part_kind": "user-prompt", "content": "把高收费的换成正常收费的看看"}]},
        {
            "model_name": "route-observability",
            "parts": [
                {
                    "part_kind": "text",
                    "content": json.dumps(
                        {
                            "type": "routeObservability",
                            "event": "conversation_turn_event",
                            "routingPath": "zhiyuan_agent_direct",
                            "actionFamily": "replace_units",
                            "toolCalls": [
                                {
                                    "name": "preview_plan_action",
                                    "actionFamily": "replace_units",
                                    "stage": "preview",
                                    "resultKind": "preview_only",
                                },
                            ],
                        },
                        ensure_ascii=False,
                    ),
                }
            ],
        },
    ]

    observed = runner._summarize_turn_observability(turn_messages)

    assert observed["routingPath"] == "zhiyuan_agent_direct"
    assert observed["actionFamilies"] == ["replace_units"]
    assert observed["resultKinds"] == ["preview_only"]


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


def test_runtime_observation_extracts_plan_pending_card_and_workspace_target():
    record = {
        "case": "case-a",
        "stepIndex": 1,
        "sessionId": "17",
        "prompt": "把第4个专业组移到第2位",
        "elapsedMs": 1200,
        "turnObservability": {
            "routingPath": "zhiyuan_agent_direct",
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

    observation = runner._build_runtime_observation(
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


def test_runtime_observation_builds_latency_profile_diagnostic():
    observation = runner._build_runtime_observation(
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
                "routingPath": "zhiyuan_agent_direct",
                "toolCallCount": 1,
                "toolReturnCount": 1,
                "actionFamilies": ["review_plan"],
                "resultKinds": ["review_result"],
                "routeDecision": {
                    "route": "review_plan",
                    "totalDurationMs": 28000,
                    "llmDurationMs": 4200,
                    "toolDurationMs": 900,
                    "classificationDurationMs": 12000,
                    "preSemanticRouteDurationMs": 14000,
                    "historyLoadDurationMs": 110,
                    "pendingLoadDurationMs": 70,
                    "initialStateLoadDurationMs": 130,
                    "runtimeHistoryBuildDurationMs": 40,
                    "backendContextLoadDurationMs": 850,
                    "requestContextBuildDurationMs": 30,
                    "guardPipelineDurationMs": 7900,
                    "turnDecisionDurationMs": 5100,
                    "turnDecisionCacheHitCount": 1,
                    "intentEntityProfileDurationMs": 1700,
                    "intentSideEffectDurationMs": 900,
                    "unattributedDurationMs": 10900,
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
    assert runtime["diagnosticPayload"]["classificationDurationMs"] == 12000
    assert runtime["diagnosticPayload"]["preSemanticRouteDurationMs"] == 14000
    assert runtime["diagnosticPayload"]["historyLoadDurationMs"] == 110
    assert runtime["diagnosticPayload"]["pendingLoadDurationMs"] == 70
    assert runtime["diagnosticPayload"]["initialStateLoadDurationMs"] == 130
    assert runtime["diagnosticPayload"]["runtimeHistoryBuildDurationMs"] == 40
    assert runtime["diagnosticPayload"]["backendContextLoadDurationMs"] == 850
    assert runtime["diagnosticPayload"]["requestContextBuildDurationMs"] == 30
    assert runtime["diagnosticPayload"]["guardPipelineDurationMs"] == 7900
    assert runtime["diagnosticPayload"]["turnDecisionDurationMs"] == 5100
    assert runtime["diagnosticPayload"]["turnDecisionCacheHitCount"] == 1
    assert runtime["diagnosticPayload"]["intentEntityProfileDurationMs"] == 1700
    assert runtime["diagnosticPayload"]["intentSideEffectDurationMs"] == 900
    assert runtime["diagnosticPayload"]["unattributedDurationMs"] == 10900
    assert runtime["evidenceContract"]["toolBudget"] == {"maxToolCalls": 8, "batchPreferred": True}


def test_runtime_observation_detects_multiple_pending_cards():
    record = {"case": "case-a", "stepIndex": 1, "sessionId": "17", "prompt": "改一下"}
    followups = [
        {"type": "pendingConfirmationCard", "content": {"kind": "intent_change"}},
        {"type": "pendingConfirmationCard", "content": {"kind": "plan_mutation"}},
    ]

    observation = runner._build_runtime_observation(
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


def test_runtime_observation_marks_readonly_while_pending_from_case_profile():
    observation = runner._build_runtime_observation(
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
            "turnObservability": {"routingPath": "zhiyuan_agent_direct"},
        },
        [],
        2,
    )

    assert observation["caseId"] == "G3-readonly-query-while-intent-pending"
    runtime = observation["runtime"]
    assert runtime["sideEffect"] == "readonly_while_pending"
    assert runtime["outputType"] == "readonly"
    assert runtime["pendingType"] == "unchanged_existing_pending"


def test_runtime_observation_does_not_treat_readonly_tool_applied_as_pending_apply():
    observation = runner._build_runtime_observation(
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
                        "name": "query_plan",
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


def test_runtime_observation_marks_needs_plan_first_route():
    observation = runner._build_runtime_observation(
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


def test_runtime_observation_marks_direct_pending_route_as_apply_existing_pending():
    observation = runner._build_runtime_observation(
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


def test_runtime_observation_preserves_post_apply_evidence_plan():
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
    observation = runner._build_runtime_observation(
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


def test_runtime_observation_preserves_apply_then_new_request_route():
    observation = runner._build_runtime_observation(
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


def test_runtime_observation_marks_intent_apply_message_code_as_apply_existing_pending():
    observation = runner._build_runtime_observation(
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


def test_runtime_observation_requires_explicit_step_case_id_for_multi_step_cases():
    observation = runner._build_runtime_observation(
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


def test_content_assertions_can_ignore_thinking_messages():
    violations = runner._check_content_assertions(
        "会把第2个志愿移动到第4位。需要你确认后才会执行。",
        [],
        {
            "prompt": "把第2个志愿移到第4位",
            "assertContains": ["第2个志愿"],
            "assertThinkingContains": ["正在生成这次调整的影响预览"],
        },
        "case-progress",
        "17",
        thinking_text="正在读取当前方案并整理这次请求...",
        ignore_thinking_assertions=True,
    )

    assert violations == []


def test_tool_assertions_can_require_exact_tool_sequence():
    violations = runner._check_tool_assertions(
        {
            "routingPath": "zhiyuan_agent_direct",
            "actionFamilies": ["query_ordered"],
            "resultKinds": ["ordered_snapshot"],
            "toolCalls": [
                {"name": "compare_entities"},
            ]
        },
        {
            "prompt": "财管会计审计怎么排",
            "expectedRoutingPath": "zhiyuan_agent_direct",
            "assertActionFamiliesContain": ["query_ordered"],
            "assertResultKindsContain": ["ordered_snapshot"],
            "expectedToolNames": ["compare_entities"],
            "expectedToolCounts": {"compare_entities": 1},
            "assertToolNamesNotContain": ["compare_entities_legacy"],
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
                {"name": "explore_topic"},
                {"name": "explore_topic"},
            ]
        },
        {
            "prompt": "建筑城乡规划要不要美术基础",
            "expectedRoutingPath": "zhiyuan_agent_direct",
            "assertActionFamiliesContain": ["query_ordered"],
            "assertResultKindsContain": ["ordered_snapshot"],
            "expectedToolNames": ["compare_entities"],
            "assertToolNamesNotContain": ["explore_topic"],
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


def test_tool_assertions_accept_any_expected_routing_path():
    violations = runner._check_tool_assertions(
        {
            "routingPath": "zhiyuan_agent_direct",
            "actionFamilies": ["query_ordered"],
            "resultKinds": ["ordered_snapshot"],
            "toolCalls": [{"name": "query_plan"}],
        },
        {
            "prompt": "两万以上的都算贵",
            "expectedRoutingPathAny": ["zhiyuan_agent_direct"],
            "assertActionFamiliesContain": ["query_ordered"],
            "assertResultKindsContain": ["ordered_snapshot"],
        },
        "case-tools",
        "9903235",
    )

    assert violations == []


def test_tool_assertions_accept_any_expected_result_kind():
    violations = runner._check_tool_assertions(
        {
            "routingPath": "zhiyuan_agent_direct",
            "actionFamilies": ["remove_units"],
            "resultKinds": ["no_change"],
            "toolCalls": [{"name": "preview_plan_action"}],
        },
        {
            "prompt": "两万以上且不贴合意向的删掉",
            "assertActionFamiliesContain": ["remove_units"],
            "assertResultKindsContainAny": ["preview_only", "no_change"],
        },
        "case-tools",
        "9903235",
    )

    assert violations == []


def test_tool_assertions_report_any_expected_result_kind_mismatch():
    violations = runner._check_tool_assertions(
        {
            "routingPath": "zhiyuan_agent_direct",
            "actionFamilies": ["remove_units"],
            "resultKinds": ["error"],
            "toolCalls": [{"name": "preview_plan_action"}],
        },
        {
            "prompt": "两万以上且不贴合意向的删掉",
            "assertResultKindsContainAny": ["preview_only", "no_change"],
        },
        "case-tools",
        "9903235",
    )

    assert any("assertResultKindsContainAny FAILED" in item for item in violations)


def test_tool_assertions_report_any_expected_routing_path_mismatch():
    violations = runner._check_tool_assertions(
        {"routingPath": "full_agent", "toolCalls": []},
        {
            "prompt": "两万以上的都算贵",
            "expectedRoutingPathAny": ["zhiyuan_agent_direct"],
        },
        "case-tools",
        "9903235",
    )

    assert any("expectedRoutingPathAny FAILED" in item for item in violations)


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
