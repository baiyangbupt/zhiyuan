import importlib.util
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


def test_content_assertions_reject_followups_when_disallowed():
    violations = runner._check_content_assertions(
        "当前没有上一轮待确认的方案动作。",
        [{"type": "planningWorkspaceAction", "content": {"targetView": "ordered", "refresh": True}}],
        {"prompt": "确认", "assertNoFollowups": True},
        "case-a",
        "17",
    )

    assert any("assertNoFollowups FAILED" in item for item in violations)
