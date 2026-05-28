import importlib.util
import json
from pathlib import Path


EVALUATOR_PATH = Path(__file__).resolve().parents[2] / "examples" / "semantic_frame_evaluator.py"
SPEC = importlib.util.spec_from_file_location("semantic_frame_evaluator", EVALUATOR_PATH)
assert SPEC and SPEC.loader
evaluator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluator)


def _write_case_file(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "defaults": {
                    "coverage": ["release_3_0_3", "dialogue_derived"],
                    "assertPlanStyle": True,
                    "promptDefaults": {
                        "assertNotContains": ["payload", "stage", "action_family", "volunteerId", "草稿"],
                        "forbiddenPatterns": ["payload"],
                        "qualityFocus": ["user_language"],
                        "warnElapsedSeconds": 45,
                    },
                },
                "cases": [
                    {
                        "name": "score-case",
                        "sessionId": "880601",
                        "flow": ["explore"],
                        "coverage": ["score_profile"],
                        "prompts": [
                            {
                                "prompt": "一模二模差挺多，这个成绩波动填志愿咋看",
                                "assertContainsAny": ["分数", "风险"],
                                "expectedKeyPoints": ["分数波动", "下一步"],
                            }
                        ],
                    },
                    {
                        "name": "intent-case",
                        "sessionId": "17",
                        "flow": ["intent"],
                        "coverage": ["major_preference", "soft_major_intent"],
                        "prompts": [
                            {
                                "prompt": "会计审计还行，土木别要",
                                "assertContainsAny": ["会计", "土木"],
                                "expectedKeyPoints": ["确认前", "下一步"],
                            }
                        ],
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_evaluator_reports_expected_only_from_case_definitions(tmp_path):
    case_file = tmp_path / "cases.json"
    _write_case_file(case_file)

    payload = evaluator.build_report(case_definition_paths=[str(case_file)])

    assert payload["total"] == 2
    assert payload["expectedTotal"] == 2
    assert payload["comparableTotal"] == 0
    assert payload["status"] == {"expected_only": 2}
    assert payload["expectedFrameDistribution"]["taskLayer"]["explore"] == 1
    assert payload["expectedFrameDistribution"]["taskLayer"]["intent"] == 1


def test_evaluator_counts_match_and_mismatch_from_runner_output(tmp_path):
    case_file = tmp_path / "cases.json"
    current_file = tmp_path / "current.json"
    _write_case_file(case_file)
    current_file.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "case": "score-case",
                        "prompt": "一模二模差挺多，这个成绩波动填志愿咋看",
                        "responseText": "先看成绩波动和位次，再看方案风险。",
                        "turnObservability": {
                            "semanticRouterShadow": {
                                "status": "success",
                                "durationMs": 1200,
                                "frame": {
                                    "taskLayer": "explore",
                                    "topic": "score",
                                    "verb": "analyze",
                                    "sideEffect": "readonly",
                                    "confidence": 0.91,
                                },
                            }
                        },
                    },
                    {
                        "case": "intent-case",
                        "prompt": "会计审计还行，土木别要",
                        "responseText": "确认前不会写入后续参考。",
                        "turnObservability": {
                            "semanticRouterShadow": {
                                "status": "success",
                                "durationMs": 2400,
                                "frame": {
                                    "taskLayer": "explore",
                                    "topic": "major",
                                    "verb": "compare",
                                    "sideEffect": "readonly",
                                    "confidence": 0.92,
                                },
                            }
                        },
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = evaluator.build_report(
        case_definition_paths=[str(case_file)],
        current_path=str(current_file),
    )

    assert payload["status"] == {"mismatch": 1, "match": 1}
    assert payload["comparableTotal"] == 2
    assert payload["matchRate"] == 0.5
    assert payload["latency"]["all"]["medianMs"] == 1800
    assert payload["latency"]["byStatus"]["match"]["maxMs"] == 1200
    assert payload["latency"]["byStatus"]["mismatch"]["maxMs"] == 2400
    assert payload["mismatchExamples"][0]["recordKey"] == "intent-case#1"
    assert "taskLayer" in ",".join(payload["mismatchExamples"][0]["mismatches"])


def test_evaluator_reports_unverified_shadow_status(tmp_path):
    case_file = tmp_path / "cases.json"
    current_file = tmp_path / "current.json"
    _write_case_file(case_file)
    current_file.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "case": "score-case",
                        "prompt": "一模二模差挺多，这个成绩波动填志愿咋看",
                        "responseText": "先看成绩波动和位次，再看方案风险。",
                        "semanticRouterShadow": {"status": "timeout"},
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = evaluator.build_report(
        case_definition_paths=[str(case_file)],
        current_path=str(current_file),
    )

    assert payload["status"]["unverified:timeout"] == 1
    assert payload["status"]["expected_only"] == 1
    assert payload["unverifiedExamples"][0]["recordKey"] == "score-case#1"
