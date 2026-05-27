import importlib.util
import asyncio
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch


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


def test_step_assertions_check_quality_fields_thinking_and_no_followups():
    text = "方案结论：冲稳保失衡，风险偏高。建议先补保底，下一步可以看审查。"
    thinking = ["正在读取当前方案并整理这次请求"]
    step = {
        "assertContainsAny": ["冲稳保", "风险"],
        "expectedKeyPoints": ["建议", "下一步"],
        "forbiddenPatterns": ["payload"],
        "assertThinkingContains": ["正在读取当前方案"],
        "assertNoFollowups": True,
        "maxElapsedSeconds": 5,
    }

    assert benchmark._check_step_assertions(
        text,
        [],
        step,
        thinking=thinking,
        final_seconds=4.9,
    ) == []


def test_step_assertions_support_expected_keypoint_groups():
    text = "这几个方向里，财会更稳，法学要看考公压力，新媒体要看表达和城市机会。可以先不记偏好。"
    step = {
        "expectedKeyPointGroups": [
            {"label": "财会方向", "any": ["财会", "会计", "审计"]},
            {"label": "边界说明", "any": ["不记偏好", "不会写入", "先不记"]},
        ]
    }

    assert benchmark._check_step_assertions(text, [], step) == []


def test_step_assertions_report_missing_keypoint_group():
    text = "法学和新媒体各有风险。"
    step = {"expectedKeyPointGroups": [{"label": "财会方向", "any": ["财会", "会计", "审计"]}]}

    assert benchmark._check_step_assertions(text, [], step) == [
        "missing expected keypoint group: 财会方向"
    ]


def test_step_assertions_report_quality_and_latency_violations():
    text = "方案情况如下 payload"
    followups = [{"content": {"targetView": "ordered"}}]
    step = {
        "expectedKeyPoints": ["下一步"],
        "forbiddenPatterns": ["payload"],
        "assertThinkingContains": ["正在读取"],
        "assertNoFollowups": True,
        "maxElapsedSeconds": 5,
    }

    violations = benchmark._check_step_assertions(
        text,
        followups,
        step,
        thinking=[],
        final_seconds=5.2,
    )

    assert "missing expected keypoint: 下一步" in violations
    assert "contains forbidden pattern: payload" in violations
    assert "missing expected thinking text: 正在读取" in violations
    assert "expected no followups, got 1" in violations
    assert "exceeded max elapsed seconds: 5.200s > 5.000s" in violations


def test_step_warnings_report_warn_elapsed_without_failing():
    warnings = benchmark._check_step_warnings(6.1, {"warnElapsedSeconds": 5})

    assert warnings == ["exceeded warn elapsed seconds: 6.100s > 5.000s"]


def test_step_quality_warnings_report_thin_reply_without_failing():
    warnings = benchmark._check_step_quality_warnings(
        "可以。",
        {"minTextLengthWarn": 20},
    )

    assert warnings == ["reply may be too thin: 3 chars < 20 chars"]


def test_agent_summary_includes_quality_gate_and_text_length_stats():
    summary = benchmark._summarize_agent(
        [
            {
                "provider": "p1",
                "model": "m1",
                "cases": [
                    {
                        "steps": [
                            {
                                "first_message_seconds": 0.1,
                                "final_seconds": 1.2,
                                "text_length": 120,
                                "assertion_violations": [],
                                "quality_warnings": [],
                            },
                            {
                                "first_message_seconds": 0.2,
                                "final_seconds": 2.4,
                                "text_length": 20,
                                "assertion_violations": ["missing expected keypoint: 风险"],
                                "quality_warnings": ["reply may be too thin"],
                            },
                        ]
                    }
                ],
            }
        ]
    )

    assert summary[0]["quality_gate_pass_rate"] == 0.5
    assert summary[0]["quality_warnings"] == 1
    assert summary[0]["text_length"]["median"] == 70.0


def test_ask_agent_once_marks_error_message_as_error():
    messages = [
        {"type": "error", "content": "系统错误", "end": True},
    ]

    class _FakeWebSocket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def send(self, payload):
            self.payload = payload

        async def recv(self):
            if messages:
                import json

                return json.dumps(messages.pop(0), ensure_ascii=False)
            raise TimeoutError

    async def _fake_wait_for(awaitable, timeout):
        return await awaitable

    with patch.object(benchmark.websockets, "connect", return_value=_FakeWebSocket()), \
            patch.object(benchmark.asyncio, "wait_for", side_effect=_fake_wait_for):
        result = asyncio.run(benchmark._ask_agent_once(
            "ws://127.0.0.1:8000/test",
            "17",
            "user",
            "看看方案",
            open_timeout=1,
            response_timeout=1,
        ))

    assert result["error"] == "系统错误"
    assert result["text"] == ""


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
