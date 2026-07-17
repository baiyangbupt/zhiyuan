import importlib.util
import json
import sys
from pathlib import Path


REPORT_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_regression_parallel_report.py"
SPEC = importlib.util.spec_from_file_location("dialog_regression_parallel_report", REPORT_PATH)
assert SPEC and SPEC.loader
parallel_report = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = parallel_report
SPEC.loader.exec_module(parallel_report)


def _write_metrics(tmp_path: Path, stem: str, payload: dict) -> Path:
    path = tmp_path / f"dialog_cases__{stem}.metrics.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def test_parallel_report_infers_root_causes_from_metrics_records(tmp_path):
    no_plan_failure = (
        "case-a session=1 prompt=调整后现在方案怎么样: "
        "assertContains FAILED — expected '冲' not found in response"
    )
    selector_failure = (
        "case-b session=2 prompt=按推荐系数重新排: "
        "assertFollowupType FAILED — expected type='pendingConfirmationCard' not in followups"
    )
    thinking_failure = (
        "case-c session=3 prompt=先别动: "
        "assertThinkingContainsAny FAILED — none of ['正在整理当前方案'] found in thinking messages"
    )
    _write_metrics(
        tmp_path,
        "case-a",
        {
            "records": [
                {
                    "stepIndex": 1,
                    "prompt": "调整后现在方案怎么样",
                    "responseText": "当前还没有生成正式方案，所以没法判断当前方案。",
                    "turnObservability": {
                        "routingPath": "needs_plan_first_guard",
                        "routeDecision": {"blockingReasons": ["missing_formal_plan"]},
                    },
                    "contentViolations": [no_plan_failure],
                }
            ],
            "summary": {"steps": 1, "failedSteps": 1, "elapsed": {"maxMs": 2000}},
            "failures": [no_plan_failure],
        },
    )
    _write_metrics(
        tmp_path,
        "case-b",
        {
            "records": [
                {
                    "stepIndex": 1,
                    "prompt": "按推荐系数重新排",
                    "responseText": "这轮信息还不够完整，不会改动方案。",
                    "turnObservability": {
                        "routingPath": "full_agent",
                        "actionFamilies": ["sort_ordered_plan"],
                        "resultKinds": ["error"],
                    },
                    "contentViolations": [selector_failure],
                }
            ],
            "summary": {"steps": 1, "failedSteps": 1, "elapsed": {"maxMs": 3000}},
            "failures": [selector_failure],
        },
    )
    _write_metrics(
        tmp_path,
        "case-c",
        {
            "records": [
                {
                    "stepIndex": 1,
                    "prompt": "先别动",
                    "responseText": "我先按只读方式回答，不改方案。",
                    "contentViolations": [thinking_failure],
                }
            ],
            "summary": {"steps": 1, "failedSteps": 1, "elapsed": {"maxMs": 1000}},
            "failures": [thinking_failure],
        },
    )

    report = parallel_report.build_report(tmp_path, [])

    assert report["failureRootCauses"] == {
        "assertion_noise_thinking": 1,
        "fixture_mismatch_no_formal_plan": 1,
        "selector_gap_no_executable_preview": 1,
    }
    assert report["failures"][0]["inferredRootCause"] == "fixture_mismatch_no_formal_plan"
    assert report["failures"][1]["inferredRootCause"] == "selector_gap_no_executable_preview"
    assert report["failures"][2]["inferredRootCause"] == "assertion_noise_thinking"
    assert report["records"][0]["rootCauses"][0]["routingPath"] == "needs_plan_first_guard"


def test_parallel_report_classifies_environment_failures(tmp_path):
    failure = "case-env session=1 prompt=看看方案: Operation not permitted"
    _write_metrics(
        tmp_path,
        "case-env",
        {
            "records": [
                {
                    "stepIndex": 1,
                    "prompt": "看看方案",
                    "responseText": "",
                    "failureReason": "environment",
                    "error": "backend state clone had failures: Operation not permitted",
                }
            ],
            "summary": {"steps": 1, "failedSteps": 1, "elapsed": {"maxMs": 20}},
            "failures": [failure],
        },
    )

    report = parallel_report.build_report(tmp_path, [])

    assert report["failureCategories"] == {"environment": 1}
    assert report["failureRootCauses"] == {"environment_setup": 1}
    assert report["failures"][0]["inferredRootCause"] == "environment_setup"


def test_parallel_report_promotes_structured_runtime_error_from_old_green_summary(tmp_path):
    _write_metrics(
        tmp_path,
        "case-timeout",
        {
            "records": [
                {
                    "stepIndex": 1,
                    "prompt": "上海的有哪些",
                    "responseText": "这轮处理没有完成，请稍后重试。",
                    "turnObservability": {
                        "routingPath": "zhiyuan_agent_direct",
                        "routeDecision": {"route": "direct", "error": "TimeoutError"},
                    },
                }
            ],
            "summary": {"steps": 1, "failedSteps": 0, "elapsed": {"maxMs": 30000}},
            "failures": [],
        },
    )

    report = parallel_report.build_report(tmp_path, [])

    assert report["failedCaseFiles"] == {"dialog_cases.json": 1}
    assert report["failedRecordCount"] == 1
    assert report["records"][0]["failedSteps"] == 1
    assert report["failureRootCauses"] == {"runtime_timeout": 1}


def test_parallel_report_classifies_no_plan_local_lookup_expectation_as_fixture_mismatch(tmp_path):
    failure = (
        "case-abbrev session=17 prompt=青城那个是不是放多了: "
        "assertContains FAILED — expected '青岛城市' not found in response"
    )
    _write_metrics(
        tmp_path,
        "case-abbrev",
        {
            "records": [
                {
                    "stepIndex": 1,
                    "prompt": "青城那个是不是放多了",
                    "responseText": "你还没有正式方案，所以不存在\"放多了\"的问题。",
                    "turnObservability": {"routingPath": "full_agent"},
                    "contentViolations": [failure],
                }
            ],
            "summary": {"steps": 1, "failedSteps": 1, "elapsed": {"maxMs": 12000}},
            "failures": [failure],
        },
    )

    report = parallel_report.build_report(tmp_path, [])

    assert report["failureRootCauses"] == {"fixture_mismatch_no_formal_plan": 1}
    assert report["failures"][0]["inferredRootCause"] == "fixture_mismatch_no_formal_plan"
