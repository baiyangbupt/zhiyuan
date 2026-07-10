import argparse
import importlib.util
import json
from pathlib import Path

import pytest


PROBE_PATH = Path(__file__).resolve().parents[2] / "examples" / "semantic_frame_probe.py"
SPEC = importlib.util.spec_from_file_location("semantic_frame_probe", PROBE_PATH)
assert SPEC and SPEC.loader
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def _write_case_file(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "defaults": {
                    "coverage": ["release_3_0_3", "dialogue_derived"],
                    "assertPlanStyle": True,
                },
                "cases": [
                    {
                        "name": "score-case",
                        "sessionId": "880601",
                        "flow": ["explore"],
                        "coverage": ["score_profile"],
                        "prompts": [{"prompt": "成绩波动咋看"}],
                    },
                    {
                        "name": "plan-case",
                        "sessionId": "17",
                        "flow": ["plan"],
                        "coverage": ["plan_operations", "sort_ordered_plan"],
                        "prompts": [{"prompt": "按录取率排一下"}],
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_flatten_case_prompts_preserves_metadata(tmp_path):
    case_file = tmp_path / "cases.json"
    _write_case_file(case_file)

    rows = probe._flatten_case_prompts(probe._load_cases(str(case_file)))

    assert [row["case"] for row in rows] == ["score-case", "plan-case"]
    assert rows[0]["stepIndex"] == 1
    assert rows[0]["flow"] == ["explore"]
    assert "score_profile" in rows[0]["coverage"]
    assert rows[1]["sessionId"] == "17"


def test_limit_rows_filters_by_coverage(tmp_path):
    case_file = tmp_path / "cases.json"
    _write_case_file(case_file)
    rows = probe._flatten_case_prompts(probe._load_cases(str(case_file)))

    filtered = probe._limit_rows(rows, coverage=["score_profile"])

    assert len(filtered) == 1
    assert filtered[0]["case"] == "score-case"


@pytest.mark.asyncio
async def test_run_probe_outputs_runner_compatible_records(tmp_path, monkeypatch):
    case_file = tmp_path / "cases.json"
    _write_case_file(case_file)

    class _Observation:
        def event_payload(self):
            return {
                "status": "success",
                "frame": {
                    "taskLayer": "explore",
                    "topic": "score",
                    "verb": "analyze",
                    "sideEffect": "readonly",
                    "confidence": 0.9,
                },
            }

    class _Router:
        async def route_shadow(self, prompt, *, request_context, active_pending):
            return _Observation()

    monkeypatch.setattr(probe, "_build_router", lambda **kwargs: _Router())

    payload = await probe.run_probe(
        cases_path=str(case_file),
        coverage=["score_profile"],
        timeout_seconds=3,
    )

    assert payload["probe"]["timeoutSeconds"] == 3
    assert len(payload["records"]) == 1
    record = payload["records"][0]
    assert record["case"] == "score-case"
    assert record["turnObservability"]["semanticFrameObservation"]["status"] == "success"


@pytest.mark.asyncio
async def test_run_probe_marks_disabled_timeout_mode(tmp_path, monkeypatch):
    case_file = tmp_path / "cases.json"
    _write_case_file(case_file)

    class _Observation:
        def event_payload(self):
            return {"status": "success", "durationMs": 123}

    class _Router:
        async def route_shadow(self, prompt, *, request_context, active_pending):
            return _Observation()

    monkeypatch.setattr(probe, "_build_router", lambda **kwargs: _Router())

    payload = await probe.run_probe(
        cases_path=str(case_file),
        limit=1,
        timeout_seconds=0,
    )

    assert payload["probe"]["timeoutSeconds"] == 0
    assert payload["probe"]["timeoutMode"] == "disabled"


def test_parse_bool_accepts_explicit_values():
    assert probe._parse_bool("true") is True
    assert probe._parse_bool("0") is False
    assert probe._parse_bool(None) is None

    with pytest.raises(argparse.ArgumentTypeError):
        probe._parse_bool("maybe")
