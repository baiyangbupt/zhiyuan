import importlib.util
import sqlite3
import sys
from pathlib import Path


BENCHMARK_PATH = Path(__file__).resolve().parents[2] / "examples" / "model_provider_benchmark.py"
SPEC = importlib.util.spec_from_file_location("model_provider_benchmark", BENCHMARK_PATH)
assert SPEC and SPEC.loader
benchmark = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)


def test_step_assertions_use_full_text_and_followups():
    text = "前面是一段较长说明。" * 80 + "最后给出审查结论：方案整体可用。"
    followups = [{"content": {"targetView": "review", "refresh": True}}]
    step = {
        "assertContains": ["审查结论"],
        "assertFollowupTarget": "review",
        "assertFollowupRefresh": True,
        "assertFollowupCount": 1,
    }

    assert benchmark._check_step_assertions(text, followups, step) == []


def test_step_assertions_report_missing_followup_count():
    violations = benchmark._check_step_assertions(
        "方案有冲稳保说明",
        [],
        {"assertFollowupCount": 1},
    )

    assert violations == ["expected 1 followups, got 0"]


def test_followup_extractors_ignore_non_workspace_messages():
    followups = [
        {"type": "text", "content": "done"},
        {"type": "planningWorkspaceAction", "content": {"targetView": "ordered", "refresh": True}},
        {"type": "planningWorkspaceAction", "content": {"targetView": "review", "refresh": False}},
    ]

    assert benchmark._followup_targets(followups) == ["ordered", "review"]
    assert benchmark._followup_refreshes(followups) == [True, False]


def test_default_cases_are_end_to_end_benchmark_cases():
    assert benchmark.DEFAULT_CASES == "examples/model_provider_benchmark_e2e_cases.json"


def test_start_agent_uses_configured_host(monkeypatch):
    provider = benchmark.ProviderConfig(
        name="provider-a",
        provider="openai_compatible",
        model="model-a",
        base_url="https://example.com/v1",
        api_key_env="TEST_MODEL_PROVIDER_KEY",
    )
    monkeypatch.setenv("TEST_MODEL_PROVIDER_KEY", "sk-test")
    captured = {}

    class DummyProcess:
        pass

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return DummyProcess()

    monkeypatch.setattr(benchmark.subprocess, "Popen", fake_popen)

    process, log_path = benchmark._start_agent(provider, "127.0.0.1", 8000)

    assert isinstance(process, DummyProcess)
    assert log_path is None
    assert captured["cmd"][captured["cmd"].index("--host") + 1] == "127.0.0.1"
    assert captured["cmd"][captured["cmd"].index("--port") + 1] == "8000"


def test_check_step_assertions_can_keep_text_independently():
    text = "方案整体可用，建议先看审查风险。"
    followups = []
    step = {"assertContains": ["方案"], "assertContainsAny": ["建议", "下一步"]}

    assert benchmark._check_step_assertions(text, followups, step) == []


def test_case_session_ids_deduplicate_in_order():
    cases = [
        {"name": "a", "sessionId": "17"},
        {"name": "b", "sessionId": 16},
        {"name": "c", "sessionId": "17"},
    ]

    assert benchmark._case_session_ids(cases) == ["17", "16"]


def test_clear_history_deletes_requested_sessions(tmp_path):
    db_path = tmp_path / "history.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE chat_session_history (
                session_id TEXT PRIMARY KEY,
                history_json TEXT NOT NULL
            )
            """
        )
        conn.executemany(
            "INSERT INTO chat_session_history(session_id, history_json) VALUES (?, ?)",
            [("16", "[]"), ("17", "[]"), ("18", "[]")],
        )
        conn.commit()

    deleted = benchmark._clear_history(db_path, ["17", "16"])

    assert deleted == 2
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT session_id FROM chat_session_history ORDER BY session_id").fetchall()
    assert [row[0] for row in rows] == ["18"]
