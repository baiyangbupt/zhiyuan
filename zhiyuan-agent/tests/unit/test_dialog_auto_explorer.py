import importlib.util
import json
import sys
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_auto_explorer.py"
SPEC = importlib.util.spec_from_file_location("dialog_auto_explorer", MODULE_PATH)
assert SPEC and SPEC.loader
explorer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = explorer
SPEC.loader.exec_module(explorer)


def test_load_scenario_payload_merges_defaults(tmp_path):
    path = tmp_path / "scenarios.json"
    path.write_text(
        json.dumps(
            {
                "defaults": {"goals": ["g1"], "issueFocus": ["i1"], "maxTurns": 3},
                "scenarios": [
                    {"name": "a", "goals": ["g2"], "issueFocus": ["i2"], "seedPrompts": ["p"]}
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    scenarios = explorer._load_scenario_payload(path)

    assert scenarios[0]["name"] == "a"
    assert scenarios[0]["goals"] == ["g1", "g2"]
    assert scenarios[0]["issueFocus"] == ["i1", "i2"]
    assert scenarios[0]["maxTurns"] == 3


def test_select_scenarios_rejects_unknown_name():
    with pytest.raises(ValueError, match="unknown scenario"):
        explorer._select_scenarios([{"name": "known"}], ["missing"])


def test_extract_session_id_supports_nested_and_url_response():
    assert explorer._extract_session_id({"data": {"id": 123}}) == "123"
    assert explorer._extract_session_id({"data": {"session": {"chatSessionId": "456"}}}) == "456"
    assert explorer._extract_session_id({"data": {"webUrl": "https://x/assistant-pc/sessionDetailV2?chatSessionId=789"}}) == "789"


def test_detect_heuristic_issues_flags_errors_and_internal_leaks():
    issues = explorer._detect_heuristic_issues(
        scenario={"name": "s"},
        prompt="看看方案",
        text="系统错误，payload 里有 volunteerId",
        thinking="",
        followups=[],
        ws_error="",
        elapsed_ms=100,
    )

    codes = {item["code"] for item in issues}
    assert "internal_leak" in codes
    assert "user_visible_error" in codes


def test_detect_heuristic_issues_flags_style_and_repetition():
    previous = "方案已经有了。" * 20
    issues = explorer._detect_heuristic_issues(
        scenario={"name": "s"},
        prompt="继续",
        text=previous + "你现在必须决定",
        thinking="",
        followups=[],
        ws_error="",
        elapsed_ms=181000,
        previous_text=previous,
    )

    codes = {item["code"] for item in issues}
    assert "style_violation" in codes
    assert "slow_reply" in codes
    assert "repeated_reply" in codes


def test_should_stop_after_turn_allows_extra_turns_after_first_issue():
    assert explorer._should_stop_after_turn(
        turn_index=1,
        first_issue_turn=1,
        extra_turns_after_issue=2,
        issue_count=1,
        issue_limit=5,
    ) is False
    assert explorer._should_stop_after_turn(
        turn_index=3,
        first_issue_turn=1,
        extra_turns_after_issue=2,
        issue_count=1,
        issue_limit=5,
    ) is True


def test_build_markdown_report_includes_issue_rows():
    payload = {
        "generatedAt": "now",
        "summary": {"scenarios": 1, "turns": 1, "issues": 1},
        "scenarios": [
            {
                "name": "case-a",
                "sessionId": "115",
                "summary": {"turns": 1, "issues": 1, "severity": {"error": 1, "warning": 0}},
                "issues": [
                    {"turn": 1, "severity": "error", "code": "internal_leak", "message": "bad", "evidence": "payload"}
                ],
                "turns": [{"turn": 1, "prompt": "p", "responseText": "r"}],
            }
        ],
    }

    markdown = explorer._build_markdown_report(payload)

    assert "case-a" in markdown
    assert "internal_leak" in markdown
    assert "payload" in markdown


def test_next_prompt_from_seed_supports_string_and_dict():
    scenario = {"seedPrompts": ["p1", {"prompt": "p2"}]}
    assert explorer._next_prompt_from_seed(scenario, []) == "p1"
    assert explorer._next_prompt_from_seed(scenario, [{"turn": 1}]) == "p2"
    assert explorer._next_prompt_from_seed(scenario, [{"turn": 1}, {"turn": 2}]) is None
