import importlib.util
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
