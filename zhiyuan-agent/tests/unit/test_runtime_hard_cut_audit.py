import re
from pathlib import Path


SERVICE_TEXT = (Path(__file__).resolve().parents[2] / "app" / "service.py").read_text(
    encoding="utf-8"
)
PLAN_SEMANTIC_ACTION_TOOL_TEXT = (
    Path(__file__).resolve().parents[2] / "app" / "tools" / "plan_semantic_action_tool.py"
).read_text(encoding="utf-8")
PROPOSAL_COMPILER_TEXT = (
    Path(__file__).resolve().parents[2] / "app" / "domain" / "proposal_compiler.py"
).read_text(encoding="utf-8")


FORBIDDEN_RUNTIME_SNIPPETS = [
    "classify_pending_confirmation_action",
    "classify_plan_recovery_action",
    "classify_composite_goal_action",
    "_fetch_fix_proposal_confirmation_source",
    "_create_pending_plan_confirmation_from_candidate",
    "_create_pending_fix_confirmation_from_review_proposal",
    "_create_pending_intent_confirmation_from_preview_payload",
    "_create_pending_fix_confirmation_from_user_goal_candidate",
    "_recover_explicit_intent_pending_from_prompt",
    "recovered_pending_intent_card",
    "recovered_intent_card",
    "explicitIntentRecovery",
    "_plan_recovery_has_context",
    "_plan_recovery_decision_to_tool_args",
    "_build_recovered_plan_action_messages",
    "_PlanActionRecoveryResult",
    "plan_action_recovery",
    "turn_decision_review_repair_preview_bridge",
    "_build_pending_apply_then_readonly_boundary_reply",
    "pending_apply_then_readonly_boundary",
    "pending-apply-then-readonly-boundary",
    "_prompt_requests_direct_plan_remove",
    "_prompt_requests_tuition_budget_mutation",
    "_mismatched_intent_preview_reply",
    "_strip_workspace_targets_for_readonly_prompt",
    "_semantic_plan_display_payload",
    "_plan_result_has_fix_proposal_options",
    "_line_looks_like_unbacked_plan_confirmation",
    "_reply_looks_like_unbacked_plan_confirmation",
    "_UNBACKED_CONFIRM_SENTENCE_RE",
]


def test_service_runtime_does_not_reintroduce_recovery_classifiers_or_legacy_wrappers():
    present = [snippet for snippet in FORBIDDEN_RUNTIME_SNIPPETS if snippet in SERVICE_TEXT]

    assert present == []


def test_plan_semantic_action_tool_does_not_keep_deleted_recovery_nodes():
    deleted_tool_snippets = [
        "classify_plan_recovery_action",
        "classify_composite_goal_action",
        "_get_plan_recovery_action_agent",
        "_get_composite_goal_agent",
        "PlanRecoveryActionDecision",
        "CompositeGoalDecision",
    ]

    assert [snippet for snippet in deleted_tool_snippets if snippet in PLAN_SEMANTIC_ACTION_TOOL_TEXT] == []


def test_service_runtime_does_not_call_legacy_fix_proposal_selector():
    assert re.search(r"\bselect_fix_proposal_candidate\s*\(", SERVICE_TEXT) is None
    assert "compile_runtime_review_fix_source" in SERVICE_TEXT


def test_current_plan_intent_preview_mutation_compilation_stays_in_proposal_compiler():
    assert "_maybe_create_current_plan_remove_preview_from_intent_payload" not in SERVICE_TEXT
    assert "compile_runtime_current_plan_mutation_from_intent_preview_source" in SERVICE_TEXT
    helper_match = re.search(
        r"async def _maybe_create_current_plan_mutation_preview_from_intent_payload[\s\S]+?"
        r"\n    async def _maybe_handle_semantic_plan_action",
        SERVICE_TEXT,
    )
    assert helper_match is not None
    helper_text = helper_match.group(0)
    forbidden_helper_snippets = [
        "major_intents = candidate.merged.get",
        '"action_family": "remove_units"',
        '"atomic_actions"',
        '"negative_level3"',
    ]
    assert [snippet for snippet in forbidden_helper_snippets if snippet in helper_text] == []


def test_intent_preview_turn_decision_arbitration_stays_in_proposal_compiler():
    assert "compile_runtime_intent_preview_turn_decision_arbitration_source" in SERVICE_TEXT
    assert "_full_agent_intent_preview_overrides_turn_decision_block" not in SERVICE_TEXT
    helper_match = re.search(
        r"def _compile_full_agent_intent_preview_turn_decision_arbitration[\s\S]+?"
        r"\n\ndef _intent_preview_payload_from_semantic_decision",
        SERVICE_TEXT,
    )
    assert helper_match is not None
    helper_text = helper_match.group(0)
    assert "compile_runtime_intent_preview_turn_decision_arbitration_source" in helper_text
    forbidden_helper_snippets = [
        "task_layer not in",
        "side_effect not in",
        "scope_anchor not in",
        "scenario in",
        "current_plan_atomic_mutation",
        "_prompt",
    ]
    assert [snippet for snippet in forbidden_helper_snippets if snippet in helper_text] == []


def test_workspace_presentation_resolution_stays_in_proposal_compiler():
    assert "compile_runtime_workspace_presentation_source" in SERVICE_TEXT
    compiler_match = re.search(
        r"def compile_runtime_workspace_presentation_source[\s\S]+?"
        r"\n\n_CURRENT_PLAN_REFERENCE_MARKERS",
        PROPOSAL_COMPILER_TEXT,
    )
    assert compiler_match is not None
    compiler_text = compiler_match.group(0)
    assert "compile_runtime_readonly_workspace_evidence_plan_source" in compiler_text
    helper_match = re.search(
        r"def _current_turn_workspace_refresh_targets[\s\S]+?"
        r"\n\ndef _tool_calls_include_plan_execution",
        SERVICE_TEXT,
    )
    assert helper_match is not None
    helper_text = helper_match.group(0)
    assert SERVICE_TEXT.count("compile_runtime_workspace_presentation_source") >= 3
    assert helper_text.count("compile_runtime_workspace_presentation_source") >= 2
    forbidden_helper_snippets = [
        "apply_pending_then_readonly",
        "apply_pending_then_readonly_query",
        "prior_result_kind not in",
        "execute_plan_action_targets",
        "mutating_tool_names",
        "review_result",
        "adjustment_analysis",
        "fix_proposal_preview",
        "risk_count",
        "warn_count",
    ]
    assert [snippet for snippet in forbidden_helper_snippets if snippet in helper_text] == []


def test_semantic_plan_display_resolution_stays_in_proposal_compiler():
    assert "compile_runtime_semantic_plan_display_source" in SERVICE_TEXT
    assert "_semantic_plan_display_payload" not in SERVICE_TEXT
    assert "_plan_result_has_fix_proposal_options" not in SERVICE_TEXT
    compiler_match = re.search(
        r"def compile_runtime_semantic_plan_display_source[\s\S]+?"
        r"\n\n_CURRENT_PLAN_REFERENCE_MARKERS",
        PROPOSAL_COMPILER_TEXT,
    )
    assert compiler_match is not None
    compiler_text = compiler_match.group(0)
    assert "display_payload" in compiler_text
    assert "reply_plan" in compiler_text


def test_reply_guard_resolution_stays_in_proposal_compiler():
    assert "compile_runtime_reply_guard_source" in SERVICE_TEXT
    assert "compile_runtime_reply_guard_source" in PROPOSAL_COMPILER_TEXT
    compiler_match = re.search(
        r"def compile_runtime_reply_guard_source[\s\S]+?"
        r"\n\n_CURRENT_PLAN_REFERENCE_MARKERS",
        PROPOSAL_COMPILER_TEXT,
    )
    assert compiler_match is not None
    compiler_text = compiler_match.group(0)
    assert "unbacked_plan_confirmation_reply_guard" in compiler_text
    assert "recorded_intent_without_pending_reply_guard" in compiler_text
    assert "no_tool_action_boundary_reply_guard" in compiler_text

    service_helper_match = re.search(
        r"def _guard_unbacked_plan_confirmation_reply[\s\S]+?"
        r"\n\ndef _guard_plan_preview_reply_without_card",
        SERVICE_TEXT,
    )
    assert service_helper_match is not None
    service_helper_text = service_helper_match.group(0)
    assert "compile_runtime_reply_guard_source" in service_helper_text
    forbidden_service_helper_snippets = [
        "确认后会执行",
        "点击确认后生效",
        "确认要删除吗",
        "后续报考参考",
        "专业组",
        "候选",
    ]
    assert [snippet for snippet in forbidden_service_helper_snippets if snippet in service_helper_text] == []
