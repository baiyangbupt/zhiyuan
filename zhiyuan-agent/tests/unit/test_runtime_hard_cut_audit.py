import re
from pathlib import Path


SERVICE_TEXT = (Path(__file__).resolve().parents[2] / "app" / "service.py").read_text(
    encoding="utf-8"
)
PLAN_SEMANTIC_ACTION_TOOL_PATH = Path(__file__).resolve().parents[2] / "app" / "tools" / "plan_semantic_action_tool.py"
PLAN_EXECUTION_TOOL_PATH = Path(__file__).resolve().parents[2] / "app" / "tools" / "plan_execution_tool.py"
PLAN_ACTION_EXECUTION_PATH = Path(__file__).resolve().parents[2] / "app" / "domain" / "plan_action_execution.py"
HANDLERS_PATH = Path(__file__).resolve().parents[2] / "app" / "handlers"
PROPOSAL_COMPILER_TEXT = (
    Path(__file__).resolve().parents[2] / "app" / "domain" / "proposal_compiler.py"
).read_text(encoding="utf-8")
INTENT_STATE_TOOL_TEXT = (
    Path(__file__).resolve().parents[2] / "app" / "tools" / "intent_state_tool.py"
).read_text(encoding="utf-8")
INTERNAL_CLIENT_TEXT = (
    Path(__file__).resolve().parents[2] / "app" / "util" / "internal_client.py"
).read_text(encoding="utf-8")
DIALOG_REGRESSION_RUNNER_TEXT = (
    Path(__file__).resolve().parents[2] / "examples" / "dialog_regression_runner.py"
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
    "_maybe_create_current_plan_mutation_preview_from_intent_payload",
    "turn_decision_intent_preview_plan_mutation",
    "classify_plan_semantic_action",
    "build_timeout_fallback_from_recent_plan_execution",
    "build_interruption_fallback_from_recent_plan_execution",
    "consume_recent_plan_execution_result",
    "clear_recent_plan_execution_result",
    "_clear_legacy_plan_edit_cache_best_effort",
    "save_intent_change_cache",
    "planEditCache",
]


def test_service_runtime_does_not_reintroduce_recovery_classifiers_or_legacy_wrappers():
    present = [snippet for snippet in FORBIDDEN_RUNTIME_SNIPPETS if snippet in SERVICE_TEXT]

    assert present == []


def test_plan_semantic_action_tool_is_removed():
    assert not PLAN_SEMANTIC_ACTION_TOOL_PATH.exists()


def test_legacy_plan_execution_tool_file_is_removed():
    assert not PLAN_EXECUTION_TOOL_PATH.exists()


def test_legacy_plan_action_execution_dispatch_is_removed():
    assert not PLAN_ACTION_EXECUTION_PATH.exists()
    assert not list(HANDLERS_PATH.glob("*.py"))
    assert "plan_action_execution" not in SERVICE_TEXT
    assert "app.handlers" not in SERVICE_TEXT


def test_service_runtime_does_not_parse_legacy_execute_plan_action_results():
    assert "execute_plan_action" not in SERVICE_TEXT


def test_legacy_plan_edit_cache_is_not_used_by_runtime_or_regression_runner():
    for text in (INTENT_STATE_TOOL_TEXT, INTERNAL_CLIENT_TEXT, DIALOG_REGRESSION_RUNNER_TEXT):
        assert "save_intent_change_cache" not in text
        assert "planEditCache" not in text


def test_regression_runner_does_not_reintroduce_legacy_plan_tool_observability():
    forbidden = [
        "execute_plan_action",
        "plan_next_action",
        "collect_plan_context_inputs",
        "plan_fast_route",
        "plan_query_fast_route",
        "major_intent_fast_route",
        "major_compare_fast_route",
        "fastRouteArbitration",
    ]

    assert [snippet for snippet in forbidden if snippet in DIALOG_REGRESSION_RUNNER_TEXT] == []


def test_service_runtime_does_not_call_legacy_fix_proposal_selector():
    assert re.search(r"\bselect_fix_proposal_candidate\s*\(", SERVICE_TEXT) is None
    assert "compile_runtime_review_fix_source" not in SERVICE_TEXT
    assert "_create_runtime_compiled_review_fix_pending" not in SERVICE_TEXT


def test_current_plan_intent_preview_mutation_bridge_is_removed():
    assert "_maybe_create_current_plan_remove_preview_from_intent_payload" not in SERVICE_TEXT
    assert "_maybe_create_current_plan_mutation_preview_from_intent_payload" not in SERVICE_TEXT
    assert "compile_runtime_current_plan_mutation_from_intent_preview_source" not in SERVICE_TEXT
    assert "app.tools.plan_execution_tool" not in SERVICE_TEXT


def test_legacy_execute_preview_no_longer_feeds_plan_pending_sink():
    assert "_extract_plan_confirmation_candidate(tool_context_messages)" not in SERVICE_TEXT
    assert "await _create_runtime_compiled_plan_pending(" not in SERVICE_TEXT
    assert "compiled_plan_pending_card" not in SERVICE_TEXT
    assert "plan_confirmation_candidate: dict" not in SERVICE_TEXT
    assert "structured_plan_reroute" not in SERVICE_TEXT
    assert "compiled_plan_includes_intent_update" not in SERVICE_TEXT
    assert "structuredReroute" not in SERVICE_TEXT
    assert "_runtime_plan_compiled_proposal_from_candidate(" not in SERVICE_TEXT.replace(
        "def _runtime_plan_compiled_proposal_from_candidate(",
        "",
    )


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


def test_legacy_workspace_presentation_compiler_is_removed():
    assert "compile_runtime_workspace_presentation_source" not in PROPOSAL_COMPILER_TEXT
    assert "RuntimeWorkspacePresentationSource" not in PROPOSAL_COMPILER_TEXT
    assert "RuntimeReadonlyWorkspaceEvidencePlanSource" not in PROPOSAL_COMPILER_TEXT
    assert "compile_runtime_readonly_workspace_evidence_plan_source" not in PROPOSAL_COMPILER_TEXT
    assert "current_execute_plan_action_result" not in PROPOSAL_COMPILER_TEXT
    assert "EXECUTE_PLAN_ACTION_REFRESH_FAMILIES" not in PROPOSAL_COMPILER_TEXT
    assert "EXECUTE_PLAN_ACTION_VIEW_FAMILIES" not in PROPOSAL_COMPILER_TEXT
    assert "EXPLANATION_ONLY_PLAN_RESULTS" not in PROPOSAL_COMPILER_TEXT
    assert "compile_runtime_workspace_presentation_source" not in SERVICE_TEXT
    assert "def _current_turn_workspace_refresh_targets" not in SERVICE_TEXT
    assert "def _current_turn_workspace_view_targets" not in SERVICE_TEXT
    forbidden_service_snippets = [
        "_execute_plan_action_results(",
        "_latest_plan_mutation_attempt_result(",
        "execute_plan_action_targets",
        "mutating_tool_names",
    ]
    assert [snippet for snippet in forbidden_service_snippets if snippet in SERVICE_TEXT] == []


def test_legacy_semantic_plan_display_compiler_is_removed():
    assert "compile_runtime_semantic_plan_display_source" not in SERVICE_TEXT
    assert "compile_runtime_semantic_plan_display_source" not in PROPOSAL_COMPILER_TEXT
    assert "RuntimeSemanticPlanDisplaySource" not in PROPOSAL_COMPILER_TEXT
    assert "_semantic_plan_display_payload" not in SERVICE_TEXT
    assert "_plan_result_has_fix_proposal_options" not in SERVICE_TEXT
    assert "_plan_result_has_fix_proposal_options" not in PROPOSAL_COMPILER_TEXT


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
        r"\n\ndef _normalize_unbacked_no_tool_action_boundary",
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
