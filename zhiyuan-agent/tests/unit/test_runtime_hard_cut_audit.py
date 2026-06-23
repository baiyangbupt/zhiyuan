import re
from pathlib import Path


SERVICE_TEXT = (Path(__file__).resolve().parents[2] / "app" / "service.py").read_text(
    encoding="utf-8"
)


FORBIDDEN_RUNTIME_SNIPPETS = [
    "classify_plan_recovery_action",
    "classify_composite_goal_action",
    "classify_pending_confirmation_action",
    "_fetch_fix_proposal_confirmation_source",
    "_create_pending_plan_confirmation_from_candidate",
    "_create_pending_fix_confirmation_from_review_proposal",
    "recovered_pending_intent_card",
    "_plan_recovery_has_context",
    "_plan_recovery_decision_to_tool_args",
    "_build_recovered_plan_action_messages",
    "_build_pending_apply_then_readonly_boundary_reply",
    "pending_apply_then_readonly_boundary",
    "pending-apply-then-readonly-boundary",
]


def test_service_runtime_does_not_reintroduce_recovery_classifiers_or_legacy_wrappers():
    present = [snippet for snippet in FORBIDDEN_RUNTIME_SNIPPETS if snippet in SERVICE_TEXT]

    assert present == []


def test_service_runtime_does_not_call_legacy_fix_proposal_selector():
    assert re.search(r"\bselect_fix_proposal_candidate\s*\(", SERVICE_TEXT) is None
    assert "compile_runtime_review_fix_source" in SERVICE_TEXT
