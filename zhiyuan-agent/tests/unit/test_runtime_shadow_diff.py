import importlib.util
import sys
from pathlib import Path


SHADOW_DIFF_PATH = Path(__file__).resolve().parents[2] / "examples" / "runtime_shadow_diff.py"
SPEC = importlib.util.spec_from_file_location("runtime_shadow_diff", SHADOW_DIFF_PATH)
assert SPEC and SPEC.loader
shadow_diff = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = shadow_diff
SPEC.loader.exec_module(shadow_diff)


def _case(case_id="case-a", **overrides):
    case = {
        "caseId": case_id,
        "source": "unit",
        "priority": "P0",
        "tags": ["pending_protocol"],
    }
    case.update(overrides)
    return case


def _compiled(case_id="case-a", **overrides):
    record = {
        "caseId": case_id,
        "sideEffect": "plan_preview",
        "outputType": "plan_mutation",
        "pendingType": "plan_mutation",
        "executionPayload": {"kind": "pending_plan_mutation"},
        "displayPayload": {"presentation": "confirmation_card"},
        "replyPlan": {"focus": ["major_scope"]},
        "workspaceRefreshTargets": ["ordered"],
        "blockingReasons": [],
    }
    record.update(overrides)
    return record


def _observation(case_id="case-a", **runtime):
    base = {
        "sideEffect": "plan_preview",
        "outputType": "plan_mutation",
        "pendingType": "plan_mutation",
        "executionPayload": {"kind": "pending_plan_mutation"},
        "displayPayload": {"presentation": "confirmation_card"},
        "replyFocus": ["major_scope"],
        "workspaceRefreshTargets": ["ordered"],
    }
    base.update(runtime)
    return {"caseId": case_id, "actualSource": "recorded_runtime", "runtime": base}


def test_shadow_diff_clean_when_old_observation_matches_compiler():
    report = shadow_diff.build_report([_case()], [_observation()], [_compiled()])

    assert report["summary"]["total"] == 1
    assert report["summary"]["clean"] == 1
    assert report["records"][0]["diffs"] == []


def test_shadow_diff_accepts_latency_profile_diagnostic_observation():
    compiled = _compiled(
        case_id="G12-latency-decomposition-profile",
        sideEffect="readonly_or_plan_preview",
        outputType="latency_profile",
        pendingType="none_or_plan_mutation",
        executionPayload=None,
        displayPayload={"presentation": "diagnostic"},
        replyPlan={"focus": ["tuition"]},
        workspaceRefreshTargets=["review"],
    )
    observation = _observation(
        case_id="G12-latency-decomposition-profile",
        sideEffect="readonly",
        outputType="latency_profile",
        pendingType="none",
        executionPayload=None,
        displayPayload={"presentation": "diagnostic"},
        replyFocus=["tuition"],
        workspaceRefreshTargets=["review"],
        diagnosticPayload={
            "profileType": "latency_profile",
            "decompose": ["model_planning", "tool_calls", "final_reply_generation"],
            "toolCallCount": 1,
        },
    )

    report = shadow_diff.build_report(
        [_case("G12-latency-decomposition-profile")],
        [observation],
        [compiled],
    )

    assert report["summary"]["clean"] == 1
    assert report["records"][0]["diffs"] == []


def test_shadow_diff_flags_unexpected_pending_creation():
    compiled = _compiled(
        pendingType="none",
        sideEffect="readonly",
        outputType="readonly",
        executionPayload=None,
        displayPayload={"presentation": "readonly_answer"},
        workspaceRefreshTargets=[],
    )

    report = shadow_diff.build_report([_case()], [_observation()], [compiled])

    record = report["records"][0]
    assert record["maxSeverity"] == "blocking"
    assert record["diffs"][0]["type"] == "unexpected_pending_creation"
    assert report["summary"]["byDiffType"]["unexpected_pending_creation"] == 1


def test_shadow_diff_flags_missing_pending():
    observation = _observation(
        pendingType="none",
        sideEffect="readonly",
        outputType="readonly",
        executionPayload={},
        displayPayload={"presentation": "readonly_answer"},
        workspaceRefreshTargets=[],
    )

    report = shadow_diff.build_report([_case()], [observation], [_compiled()])

    record = report["records"][0]
    assert record["maxSeverity"] == "blocking"
    assert record["diffs"][0]["type"] == "missing_pending"


def test_shadow_diff_flags_multiple_pending_cards():
    observation = {
        "caseId": "case-a",
        "runtime": {
            "pendingCards": [
                {"kind": "intent_change"},
                {"kind": "plan_mutation"},
            ]
        },
    }

    report = shadow_diff.build_report([_case()], [observation], [_compiled()])

    assert report["records"][0]["maxSeverity"] == "blocking"
    assert report["records"][0]["diffs"][0]["type"] == "multiple_pending_cards"


def test_shadow_diff_flags_shadow_side_effect_violation():
    observation = _observation(shadowWritesState=True)

    report = shadow_diff.build_report([_case()], [observation], [_compiled()])

    assert report["records"][0]["maxSeverity"] == "blocking"
    assert report["records"][0]["diffs"][0]["type"] == "shadow_side_effect_violation"


def test_shadow_diff_missing_observation_is_info_only():
    report = shadow_diff.build_report([_case()], [], [_compiled()])

    record = report["records"][0]
    assert record["maxSeverity"] == "info"
    assert record["diffs"][0]["type"] == "missing_observation"


def test_shadow_diff_reports_reply_focus_and_workspace_mismatch():
    observation = _observation(replyFocus=["other_issue"], workspaceRefreshTargets=["candidate"])

    report = shadow_diff.build_report([_case()], [observation], [_compiled()])

    diff_types = {diff["type"] for diff in report["records"][0]["diffs"]}
    assert "reply_focus_missing" in diff_types
    assert "workspace_refresh_mismatch" in diff_types


def test_shadow_diff_keeps_optional_enum_text_as_match():
    compiled = _compiled(
        sideEffect="readonly_or_plan_preview",
        outputType="readonly_or_plan_mutation",
        pendingType="none_or_plan_mutation",
        executionPayload={"kind": "conditional_plan_mutation"},
        displayPayload={"presentation": "conditional_options"},
        workspaceRefreshTargets=["review"],
    )
    observation = _observation(
        sideEffect="readonly_or_plan_preview",
        outputType="readonly_or_plan_mutation",
        pendingType="none_or_plan_mutation",
        executionPayload={"kind": "conditional_plan_mutation"},
        displayPayload={"presentation": "conditional_options"},
        workspaceRefreshTargets=["review"],
    )

    report = shadow_diff.build_report([_case()], [observation], [compiled])

    assert report["records"][0]["diffs"] == []


def test_shadow_diff_compares_post_apply_evidence_plan():
    compiled = _compiled(
        sideEffect="apply_pending_then_readonly",
        outputType="apply_then_readonly",
        pendingType="none",
        executionPayload={"kind": "apply_existing_pending_then_readonly"},
        displayPayload={"presentation": "readonly_answer"},
        workspaceRefreshTargets=["ordered", "review"],
        evidenceContract={
            "requiredInputs": ["active_pending", "formal_ordered_plan_after_apply"],
            "steps": ["apply_existing_pending", "read_latest_plan_summary", "review_tier_gradient"],
        },
    )
    observation = _observation(
        sideEffect="apply_existing_pending",
        outputType="apply_then_readonly",
        pendingType="none",
        executionPayload={"kind": "apply_existing_pending_then_readonly"},
        displayPayload={"presentation": "readonly_answer"},
        workspaceRefreshTargets=["ordered", "review"],
        postApplyEvidencePlan={
            "requiredInputs": ["active_pending", "formal_ordered_plan_after_apply"],
            "steps": [
                {"step": "apply_existing_pending"},
                {"step": "read_latest_plan_summary"},
                {"step": "review_tier_gradient"},
            ],
        },
    )

    report = shadow_diff.build_report([_case()], [observation], [compiled])

    diff_types = {diff["type"] for diff in report["records"][0]["diffs"]}
    assert "missing_post_apply_evidence_plan" not in diff_types
    assert "post_apply_required_inputs_missing" not in diff_types
    assert "post_apply_evidence_steps_mismatch" not in diff_types


def test_shadow_diff_flags_missing_post_apply_evidence_plan():
    compiled = _compiled(
        sideEffect="apply_pending_then_readonly",
        outputType="apply_then_readonly",
        pendingType="none",
        executionPayload={"kind": "apply_existing_pending_then_readonly"},
        displayPayload={"presentation": "readonly_answer"},
        workspaceRefreshTargets=["ordered"],
        evidenceContract={
            "requiredInputs": ["active_pending", "formal_ordered_plan_after_apply"],
            "steps": ["apply_existing_pending", "read_latest_plan_summary"],
        },
    )
    observation = _observation(
        sideEffect="apply_existing_pending",
        outputType="apply_then_readonly",
        pendingType="none",
        executionPayload={"kind": "apply_existing_pending_then_readonly"},
        displayPayload={"presentation": "readonly_answer"},
        workspaceRefreshTargets=["ordered"],
    )

    report = shadow_diff.build_report([_case()], [observation], [compiled])

    diff_types = {diff["type"] for diff in report["records"][0]["diffs"]}
    assert "missing_post_apply_evidence_plan" in diff_types


def test_shadow_diff_does_not_require_post_apply_evidence_for_apply_then_new_request():
    compiled = _compiled(
        sideEffect="apply_pending_then_new_request",
        outputType="composite",
        pendingType="plan_mutation_or_clarification",
        executionPayload={"kind": "apply_existing_pending_then_followup"},
        displayPayload={"presentation": "conditional_options"},
        workspaceRefreshTargets=["candidate"],
    )
    observation = _observation(
        sideEffect="apply_pending_then_new_request",
        outputType="apply_then_readonly",
        pendingType="none",
        executionPayload={"kind": "apply_existing_pending_then_followup"},
        displayPayload={"presentation": "readonly_answer"},
        workspaceRefreshTargets=["candidate"],
    )

    report = shadow_diff.build_report([_case()], [observation], [compiled])

    diff_types = {diff["type"] for diff in report["records"][0]["diffs"]}
    assert "missing_post_apply_evidence_plan" not in diff_types
