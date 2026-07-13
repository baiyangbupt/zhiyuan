import json
import re
from pathlib import Path


SERVICE_TEXT = (Path(__file__).resolve().parents[2] / "app" / "service.py").read_text(
    encoding="utf-8"
)
SERVER_TEXT = (Path(__file__).resolve().parents[2] / "app" / "server.py").read_text(
    encoding="utf-8"
)
WS_COMPAT_TEST_TEXT = (
    Path(__file__).resolve().parents[2] / "tests" / "unit" / "test_ws_compat.py"
).read_text(encoding="utf-8")
PLAN_SEMANTIC_ACTION_TOOL_PATH = Path(__file__).resolve().parents[2] / "app" / "tools" / "plan_semantic_action_tool.py"
PLAN_EXECUTION_TOOL_PATH = Path(__file__).resolve().parents[2] / "app" / "tools" / "plan_execution_tool.py"
INTENT_PREVIEW_TOOL_PATH = Path(__file__).resolve().parents[2] / "app" / "tools" / "intent_preview_tool.py"
PLANNING_WORKFLOW_TOOL_PATH = Path(__file__).resolve().parents[2] / "app" / "tools" / "planning_workflow_tool.py"
TURN_DECISION_TOOL_PATH = Path(__file__).resolve().parents[2] / "app" / "tools" / "turn_decision_tool.py"
INTENT_ENTITY_PROFILE_TOOL_PATH = Path(__file__).resolve().parents[2] / "app" / "tools" / "intent_entity_profile_tool.py"
PLAN_QUERY_PROFILE_TOOL_PATH = Path(__file__).resolve().parents[2] / "app" / "tools" / "plan_query_profile_tool.py"
REPLY_PROFILE_TOOL_PATH = Path(__file__).resolve().parents[2] / "app" / "tools" / "reply_profile_tool.py"
MAJOR_INFO_TOOL_PATH = Path(__file__).resolve().parents[2] / "app" / "tools" / "major_info_tool.py"
MAJOR_COMPARE_TOOL_PATH = Path(__file__).resolve().parents[2] / "app" / "tools" / "major_compare_tool.py"
MAJOR_CHAT_SKILL_PATH = Path(__file__).resolve().parents[2] / "skills" / "major_chat" / "SKILL.md"
SCHOOL_INFO_TOOL_PATH = Path(__file__).resolve().parents[2] / "app" / "tools" / "school_info_tool.py"
SCHOOL_COMPARE_TOOL_PATH = Path(__file__).resolve().parents[2] / "app" / "tools" / "school_compare_tool.py"
SCHOOL_RECOMMEND_TOOL_PATH = Path(__file__).resolve().parents[2] / "app" / "tools" / "school_recommend_tool.py"
SCHOOL_CHAT_SKILL_PATH = Path(__file__).resolve().parents[2] / "skills" / "school_chat" / "SKILL.md"
EXPLORE_FOLLOWUP_TOOL_TEXT = (
    Path(__file__).resolve().parents[2] / "app" / "tools" / "explore_followup_tool.py"
).read_text(encoding="utf-8")
ZHIYUAN_TOOLS_TEXT = (
    Path(__file__).resolve().parents[2] / "app" / "zhiyuan_agent" / "tools.py"
).read_text(encoding="utf-8")
ZHIYUAN_SANDBOX_TEXT = (
    Path(__file__).resolve().parents[2] / "app" / "zhiyuan_agent" / "sandbox.py"
).read_text(encoding="utf-8")
EXPLORE_CHAT_SKILL_TEXT = (
    Path(__file__).resolve().parents[2] / "skills" / "explore_chat" / "SKILL.md"
).read_text(encoding="utf-8")
CAREER_PATH_CHAT_SKILL_TEXT = (
    Path(__file__).resolve().parents[2] / "skills" / "career_path_chat" / "SKILL.md"
).read_text(encoding="utf-8")
PLAN_ACTION_EXECUTION_PATH = Path(__file__).resolve().parents[2] / "app" / "domain" / "plan_action_execution.py"
HANDLERS_PATH = Path(__file__).resolve().parents[2] / "app" / "handlers"
EXAMPLES_PATH = Path(__file__).resolve().parents[2] / "examples"
PROPOSAL_COMPILER_TEXT = (
    Path(__file__).resolve().parents[2] / "app" / "domain" / "proposal_compiler.py"
).read_text(encoding="utf-8")
INTENT_STATE_TOOL_TEXT = (
    Path(__file__).resolve().parents[2] / "app" / "tools" / "intent_state_tool.py"
).read_text(encoding="utf-8")
INTERNAL_CLIENT_TEXT = (
    Path(__file__).resolve().parents[2] / "app" / "util" / "internal_client.py"
).read_text(encoding="utf-8")
CONFIG_TEXT = (Path(__file__).resolve().parents[2] / "app" / "config.py").read_text(encoding="utf-8")
PENDING_BACKFILL_MIGRATION_TEXT = (
    Path(__file__).resolve().parents[3]
    / "zhiyuan-server"
    / "src"
    / "main"
    / "resources"
    / "db"
    / "migration"
    / "V11__backfill_active_pending_confirmation.sql"
).read_text(encoding="utf-8")
DIALOG_REGRESSION_RUNNER_TEXT = (
    Path(__file__).resolve().parents[2] / "examples" / "dialog_regression_runner.py"
).read_text(encoding="utf-8")
DIALOG_CASE_EVALUATION_REPORT_TEXT = (
    Path(__file__).resolve().parents[2] / "examples" / "dialog_case_evaluation_report.py"
).read_text(encoding="utf-8")
DIALOG_QUALITY_GATE_TEXT = (
    Path(__file__).resolve().parents[2] / "examples" / "dialog_quality_gate.py"
).read_text(encoding="utf-8")
E2E_EFFECT_PERF_TEXT = (
    Path(__file__).resolve().parents[2] / "tests" / "e2e" / "test_agent_dialog_effect_perf.py"
).read_text(encoding="utf-8")
MAINLINE_DIALOG_SCENARIOS_TEXT = (
    Path(__file__).resolve().parents[2] / "tests" / "unit" / "test_mainline_dialog_scenarios.py"
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


def test_legacy_chat_input_aliases_are_removed_from_ws_compat():
    assert "\"planEdit\": \"chat\"" not in SERVER_TEXT
    assert "\"intentDetect\": \"chat\"" not in SERVER_TEXT
    assert "inputType\": \"planEdit\"" not in WS_COMPAT_TEST_TEXT
    assert "inputType\": \"intentDetect\"" not in WS_COMPAT_TEST_TEXT
    assert "test_legacy_plan_edit_maps_to_chat" not in WS_COMPAT_TEST_TEXT


def test_zhiyuan_agent_direct_route_is_not_feature_flag_or_rollout_gated():
    forbidden = [
        "ZHIYUAN_AGENT_ENABLED",
        "ZHIYUAN_AGENT_ROLLOUT_PERCENT",
        "_zhiyuan_agent_direct_enabled",
        "_zhiyuan_agent_rollout_percent",
        "_should_use_zhiyuan_agent_direct",
        "_score_available_for_zhiyuan_agent_direct",
        "from app.agent.chat_agent import ChatAgent",
        "ChatAgent(",
    ]

    assert [snippet for snippet in forbidden if snippet in SERVICE_TEXT] == []


def test_zhiyuan_agent_direct_shadow_runtime_is_removed():
    forbidden = [
        "ZHIYUAN_AGENT_POC_SHADOW",
        "ZHIYUAN_AGENT_DIRECT_SHADOW",
        "_ZHIYUAN_AGENT_POC_SHADOW_TIMEOUT_SECONDS",
        "_ZHIYUAN_AGENT_DIRECT_SHADOW_TIMEOUT_SECONDS",
        "_maybe_run_zhiyuan_agent_shadow",
        "_run_zhiyuan_agent_shadow_task",
        "_append_completed_poc_shadow_observability_message",
        "_append_zhiyuan_agent_shadow_history",
        "zhiyuanAgentPocShadow",
        "zhiyuanAgentDirectShadow",
        "zhiyuan_agent_poc_shadow_event",
        "zhiyuan_agent_shadow_event",
        "expectedZhiyuanAgentPoc",
        "maxZhiyuanAgentPoc",
        "poc-shadow-wait-seconds",
        "runtime-shadow-output",
        "runtimeShadowCaseId",
        "runtimeShadowSummary",
        "_build_runtime_shadow_observation",
        "_build_runtime_shadow_summary",
    ]

    assert [snippet for snippet in forbidden if snippet in SERVICE_TEXT] == []
    for text in (DIALOG_REGRESSION_RUNNER_TEXT, DIALOG_CASE_EVALUATION_REPORT_TEXT):
        assert [snippet for snippet in forbidden if snippet in text] == []


def test_regression_runner_protocol_does_not_reintroduce_semantic_shadow_or_full_agent_timing_names():
    forbidden = [
        "semanticRouterShadow",
        "semantic-router-shadow",
        "semanticRouterSummary",
        "preFullAgentDurationMs",
        "postFullAgentDurationMs",
        "fullAgentToolTrial",
        "Full Agent Tool Trial",
    ]

    for text in (DIALOG_REGRESSION_RUNNER_TEXT, DIALOG_CASE_EVALUATION_REPORT_TEXT):
        assert [snippet for snippet in forbidden if snippet in text] == []


def test_plan_semantic_action_tool_is_removed():
    assert not PLAN_SEMANTIC_ACTION_TOOL_PATH.exists()


def test_legacy_plan_execution_tool_file_is_removed():
    assert not PLAN_EXECUTION_TOOL_PATH.exists()


def test_legacy_intent_preview_wrapper_file_is_removed():
    assert not INTENT_PREVIEW_TOOL_PATH.exists()


def test_legacy_planning_workflow_tool_file_is_removed():
    assert not PLANNING_WORKFLOW_TOOL_PATH.exists()
    assert "planning_workflow_tool" not in SERVICE_TEXT


def test_legacy_turn_decision_tool_file_is_removed():
    assert not TURN_DECISION_TOOL_PATH.exists()
    forbidden = [
        "turn_decision_tool",
        "classify_turn_decision",
        "_classify_turn_decision_cached",
        "TurnDecision",
        "turnDecision",
        "_turn_decision_",
        "TURN_DECISION_TIMEOUT_SECONDS",
        "latest_profile_change_replan_dsl",
    ]
    assert [snippet for snippet in forbidden if snippet in SERVICE_TEXT] == []


def test_legacy_model_node_profile_tools_are_removed():
    assert not INTENT_ENTITY_PROFILE_TOOL_PATH.exists()
    assert not PLAN_QUERY_PROFILE_TOOL_PATH.exists()
    assert not REPLY_PROFILE_TOOL_PATH.exists()
    forbidden = [
        "intent_entity_profile_tool",
        "plan_query_profile_tool",
        "reply_profile_tool",
        "extract_intent_entity_profile",
        "classify_plan_query_profile",
        "classify_reply_focus_binding",
        "classify_reply_generation_grounding",
        "3.2.0 profile",
    ]
    assert [snippet for snippet in forbidden if snippet in INTENT_STATE_TOOL_TEXT] == []


def test_legacy_major_topic_tools_and_skill_are_removed_from_4_0_runtime():
    assert not MAJOR_INFO_TOOL_PATH.exists()
    assert not MAJOR_COMPARE_TOOL_PATH.exists()
    assert not MAJOR_CHAT_SKILL_PATH.exists()

    forbidden = [
        "get_major_introduction",
        "get_major_introductions",
        "compare_majors",
        "compare_major_options",
        "analyze_current_major_interest",
        "analyze_current_career_direction",
        "analyze_volunteer_intent_change",
        "preview_current_intent_confirmation",
    ]
    for text in (EXPLORE_CHAT_SKILL_TEXT, CAREER_PATH_CHAT_SKILL_TEXT):
        assert [snippet for snippet in forbidden if snippet in text] == []


def test_legacy_school_topic_tools_and_skill_are_removed_from_4_0_runtime():
    assert not SCHOOL_INFO_TOOL_PATH.exists()
    assert not SCHOOL_COMPARE_TOOL_PATH.exists()
    assert not SCHOOL_RECOMMEND_TOOL_PATH.exists()
    assert not SCHOOL_CHAT_SKILL_PATH.exists()

    forbidden = [
        "get_school_introduction",
        "compare_schools",
        "compare_schools_adhoc",
        "get_school_recommendations",
        "school_compare_tool",
        "school_info_tool",
        "school_recommend_tool",
    ]
    for text in (EXPLORE_CHAT_SKILL_TEXT, CAREER_PATH_CHAT_SKILL_TEXT):
        assert [snippet for snippet in forbidden if snippet in text] == []


def test_frontend_followup_compat_bridge_does_not_reintroduce_legacy_plan_chain():
    assert "legacy explore follow-up" not in EXPLORE_FOLLOWUP_TOOL_TEXT
    assert "get_last_pending_confirmation" in EXPLORE_FOLLOWUP_TOOL_TEXT
    assert re.search(r"\bget_pending_confirmation\s*\(", EXPLORE_FOLLOWUP_TOOL_TEXT) is None
    assert "pendingConfirmation" in EXPLORE_FOLLOWUP_TOOL_TEXT


def test_pending_runtime_does_not_fall_back_from_latest_to_version_zero():
    assert "get_last_pending_confirmation" in SERVICE_TEXT
    assert "get_last_pending_confirmation" in ZHIYUAN_SANDBOX_TEXT
    service_loader = re.search(
        r"async def _load_pending_confirmation_state\([\s\S]+?\n\ndef _pending_confirmation_from_state",
        SERVICE_TEXT,
    )
    assert service_loader is not None
    assert "get_pending_confirmation" not in service_loader.group(0)
    assert "get_pending_confirmation" not in SERVICE_TEXT
    sandbox_pending = re.search(
        r'if normalized_path == "pending.json":[\s\S]+?raise ValueError',
        ZHIYUAN_SANDBOX_TEXT,
    )
    assert sandbox_pending is not None
    assert "get_pending_confirmation" not in sandbox_pending.group(0)


def test_pending_intent_add_and_replace_use_single_idempotent_backend_command():
    assert "_sync_tuition_budget_direct" not in ZHIYUAN_TOOLS_TEXT
    intent_apply = re.search(
        r"async def _apply_intent_pending\([\s\S]+?\n\ndef _first_atomic_action",
        ZHIYUAN_TOOLS_TEXT,
    )
    assert intent_apply is not None
    assert "execute_pending_planning_command" in intent_apply.group(0)
    assert "update_planning_constraint_state" not in intent_apply.group(0)
    assert "update_session_tuition_range" not in intent_apply.group(0)
    plan_apply = re.search(
        r"async def _apply_plan_pending\([\s\S]+?\n\nasync def preview_intent_change",
        ZHIYUAN_TOOLS_TEXT,
    )
    assert plan_apply is not None
    add_branch = re.search(
        r'if action_family == "add_units":[\s\S]+?if action_family == "replace_units"',
        plan_apply.group(0),
    )
    assert add_branch is not None
    assert "execute_pending_planning_command" in add_branch.group(0)
    assert "select_working_plan_items" not in add_branch.group(0)
    assert "generate_planning_ordered_plan" not in add_branch.group(0)
    replace_branch = re.search(
        r'if action_family == "replace_units":[\s\S]+?if action_family in \{"remove_units"',
        plan_apply.group(0),
    )
    assert replace_branch is not None
    assert "execute_pending_planning_command" in replace_branch.group(0)
    assert "remove_planning_ordered_plan_units" not in replace_branch.group(0)
    assert "select_working_plan_items" not in replace_branch.group(0)


def test_pending_legacy_read_is_off_by_default_and_backfill_is_latest_only():
    assert "pending_legacy_read_fallback" not in CONFIG_TEXT
    pending_reader = re.search(
        r"async def get_last_pending_confirmation[\s\S]+?\n\n# ── 方案参数校验",
        INTERNAL_CLIENT_TEXT,
    )
    assert pending_reader is not None
    assert "get_last_extra_data" not in pending_reader.group(0)
    assert "_pendingLegacySnapshot" not in pending_reader.group(0)
    assert "JOIN assistant_chat_session session" in PENDING_BACKFILL_MIGRATION_TEXT
    assert "IN ('active', 'applying')" in PENDING_BACKFILL_MIGRATION_TEXT
    assert "newer.data_version > extra.data_version" in PENDING_BACKFILL_MIGRATION_TEXT
    assert "newer.data_version = extra.data_version AND newer.id > extra.id" in PENDING_BACKFILL_MIGRATION_TEXT
    assert "NOT EXISTS" in PENDING_BACKFILL_MIGRATION_TEXT


def test_current_regression_fixtures_do_not_clone_a_session_onto_itself():
    invalid: list[str] = []
    for path in sorted(EXAMPLES_PATH.glob("dialog_regression_400*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        defaults = (
            payload.get("defaults")
            if isinstance(payload, dict) and isinstance(payload.get("defaults"), dict)
            else {}
        )
        cases = payload.get("cases") or [] if isinstance(payload, dict) else payload
        default_source = defaults.get("cloneBackendStateFromSessionId")
        for case in cases:
            if not isinstance(case, dict):
                continue
            source = case.get("cloneBackendStateFromSessionId", default_source)
            target = case.get("sessionId")
            if source not in (None, "") and str(source) == str(target):
                invalid.append(f"{path.name}:{case.get('name') or target}")

    assert invalid == []
    assert "query_plan(" in EXPLORE_FOLLOWUP_TOOL_TEXT
    forbidden = [
        "plan_next_action",
        "collect_plan_context_inputs",
        "execute_plan_action",
        "planEditCache",
        "save_intent_change_cache",
        "app.tools.plan_execution_tool",
        "app.tools.plan_orchestration_tool",
        "app.tools.plan_context_tool",
    ]
    assert [snippet for snippet in forbidden if snippet in EXPLORE_FOLLOWUP_TOOL_TEXT] == []


def test_zhiyuan_direct_production_code_does_not_reintroduce_ambiguous_legacy_names():
    forbidden = [
        "_replacement_legacy_auto_select_reason",
        "_legacy_volunteer_prefix",
        "by_legacy_prefix",
    ]
    assert [snippet for snippet in forbidden if snippet in ZHIYUAN_TOOLS_TEXT] == []
    assert [snippet for snippet in forbidden if snippet in ZHIYUAN_SANDBOX_TEXT] == []
    assert "_replacement_auto_select_reason" in ZHIYUAN_TOOLS_TEXT
    assert "_candidate_school_major_key" in ZHIYUAN_SANDBOX_TEXT


def test_legacy_runtime_pending_audit_and_compiler_adapter_assets_are_removed():
    removed = [
        "runtime_pending_entrypoint_audit.py",
        "runtime_pending_sink_call_audit.py",
        "runtime_pending_entrypoints_320.json",
        "runtime_pending_entrypoints_320_expectations.json",
        "runtime_pending_sink_calls_320.json",
        "runtime_pending_sink_calls_320_expectations.json",
        "intent_preview_compiler_adapter.py",
        "intent_preview_compiler_adapter_320_cases.json",
        "intent_select_compiler_adapter.py",
        "intent_select_compiler_adapter_320_cases.json",
        "compiled_pending_sink_contract.py",
        "compiled_pending_sink_contract_320_cases.json",
        "dialog_regression_320_prod_asset_quality_cases.json",
        "dialog_regression_320_prod_asset_micro_cases.json",
        "dialog_regression_320_prod_asset_additional_raw_cases.json",
        "dialog_regression_320_prod_raw_framework_gap_cases.json",
        "dialog_regression_320_career_region_fastpath_probe.json",
        "dialog_regression_320_prod_asset_supplemental_cases.json",
    ]
    assert [name for name in removed if (EXAMPLES_PATH / name).exists()] == []


def test_legacy_release_quality_gate_assets_are_removed_from_release_gate():
    removed = [
        "dialog_regression_301_agent_smoke_cases.json",
        "dialog_regression_302_agent_cases.json",
        "dialog_regression_302_explore_intent_cases.json",
        "dialog_regression_302_readonly_real_session_cases.json",
        "dialog_regression_302_effect_perf_cases.json",
        "dialog_regression_302_effect_perf_output.json",
        "dialog_regression_303_effect_perf_cases.json",
        "dialog_regression_303_open_quality_cases.json",
        "dialog_regression_303_realistic_user_cases.json",
        "dialog_regression_303_dialogue_derived_cases.json",
        "dialog_regression_303_career_direction_cases.json",
        "dialog_regression_303_phase2_career_output.json",
        "dialog_regression_303_phase2_major_compare_output.json",
        "dialog_regression_310_review_repair_cases.json",
        "dialog_regression_310_production_abstracted_cases.json",
        "dialog_regression_310_constraint_plan_action_cases.json",
        "dialog_regression_310_production_dialogue_candidates.json",
        "model_provider_303_quality_readonly_cases.json",
        "model_provider_303_open_quality_realistic_cases.json",
    ]

    assert [name for name in removed if (EXAMPLES_PATH / name).exists()] == []
    for text in (DIALOG_QUALITY_GATE_TEXT, E2E_EFFECT_PERF_TEXT, MAINLINE_DIALOG_SCENARIOS_TEXT):
        assert [name for name in removed if name in text] == []


def test_legacy_non_400_dialog_regression_case_files_are_removed_from_current_gate():
    legacy_files = [
        "dialog_regression_advanced_cases.json",
        "dialog_regression_comprehensive_cases.json",
        "dialog_regression_enriched_cases.json",
        "dialog_regression_full_journey_cases.json",
        "dialog_regression_lifecycle_cases.json",
        "dialog_regression_mainline_cases.json",
        "dialog_regression_plan_cases.json",
        "dialog_regression_plan_correctness_cases.json",
        "dialog_regression_robust_cases.json",
        "dialog_regression_science_cases.json",
        "dialog_regression_score_tier_cases.json",
        "dialog_regression_special_cases.json",
    ]

    assert [name for name in legacy_files if (EXAMPLES_PATH / name).exists()] == []
    for text in (DIALOG_QUALITY_GATE_TEXT, MAINLINE_DIALOG_SCENARIOS_TEXT):
        assert [name for name in legacy_files if name in text] == []
    assert 'EXAMPLES.glob("dialog_regression_*_cases.json")' not in DIALOG_QUALITY_GATE_TEXT


def test_legacy_plan_action_execution_dispatch_is_removed():
    assert not PLAN_ACTION_EXECUTION_PATH.exists()
    assert not list(HANDLERS_PATH.glob("*.py"))
    assert "plan_action_execution" not in SERVICE_TEXT
    assert "app.handlers" not in SERVICE_TEXT


def test_service_runtime_does_not_parse_legacy_execute_plan_action_results():
    assert "execute_plan_action" not in SERVICE_TEXT


def test_service_runtime_does_not_reference_legacy_full_agent_tool_names():
    forbidden = [
        "preview_current_intent_confirmation",
        "preview_current_major_intent_confirmation",
        "preview_current_school_intent_confirmation",
        "preview_current_region_intent_confirmation",
        "preview_current_career_intent_confirmation",
        "analyze_volunteer_intent_change",
        "query_volunteer_plan",
        "answer_admission_policy_question",
        "compare_majors",
        "compare_schools",
    ]

    assert [snippet for snippet in forbidden if snippet in SERVICE_TEXT] == []


def test_legacy_intent_popup_title_alias_is_removed():
    assert "_build_popup_title" not in INTENT_STATE_TOOL_TEXT


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


def test_service_runtime_does_not_reintroduce_full_agent_intent_arbitration():
    forbidden = [
        "_compile_full_agent_intent_preview_turn_decision_arbitration",
        "_full_agent_intent_preview_overrides_turn_decision_block",
        "_turn_decision_blocks_full_agent_intent_pending",
        "_full_agent_intent_pending_blocked_by_turn_decision_reply",
        "_blocked_intent_preview_for_plan_route_reply",
        "compile_runtime_intent_preview_turn_decision_arbitration_source",
        "compile_blocked_intent_preview_for_plan_route_reply_source",
        "full_agent_intent_pending_requires_turn_decision",
        "RuntimeIntentPreviewTurnDecisionArbitrationSource",
        "RuntimeBlockedIntentPreviewReplySource",
    ]

    assert [snippet for snippet in forbidden if snippet in SERVICE_TEXT] == []
    assert [snippet for snippet in forbidden if snippet in PROPOSAL_COMPILER_TEXT] == []


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


def test_legacy_proposal_compiler_32_turn_decision_compilers_are_removed():
    forbidden = [
        "PlanConfirmationCandidateResolution",
        "RuntimePlanCompiledSource",
        "RuntimeLocalPlanActionSource",
        "RuntimePlanQueryCompiledSource",
        "ProfileChangeReplanCompiledSource",
        "ProfileChangeStateQueryResolution",
        "PendingTurnResolution",
        "ApplyThenGeneratePlanCompiledSource",
        "resolve_plan_confirmation_candidate",
        "compile_runtime_plan_confirmation_source",
        "compile_apply_then_generate_plan_source",
        "resolve_pending_turn_action",
        "compile_runtime_pending_turn_decision_source",
        "compile_post_apply_readonly_evidence_plan",
        "compile_runtime_local_plan_action_source",
        "compile_runtime_plan_query_profile_source",
        "pending_turn_looks_no_active_pending_confirmation",
        "compile_profile_change_replan_source",
        "resolve_profile_change_replan_state_query",
    ]

    assert [snippet for snippet in forbidden if snippet in PROPOSAL_COMPILER_TEXT] == []


def test_legacy_semantic_plan_display_compiler_is_removed():
    assert "compile_runtime_semantic_plan_display_source" not in SERVICE_TEXT
    assert "compile_runtime_semantic_plan_display_source" not in PROPOSAL_COMPILER_TEXT
    assert "RuntimeSemanticPlanDisplaySource" not in PROPOSAL_COMPILER_TEXT
    assert "_semantic_plan_display_payload" not in SERVICE_TEXT
    assert "_plan_result_has_fix_proposal_options" not in SERVICE_TEXT
    assert "_plan_result_has_fix_proposal_options" not in PROPOSAL_COMPILER_TEXT


def test_unused_readonly_policy_copy_fallbacks_are_removed():
    forbidden = [
        "_prompt_requires_readonly_policy_answer",
        "_readonly_policy_fallback_reply_for_prompt",
        "_build_score_batch_risk_policy_reply",
        "_build_major_group_keep_safest_policy_reply",
    ]

    assert [snippet for snippet in forbidden if snippet in SERVICE_TEXT] == []


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
