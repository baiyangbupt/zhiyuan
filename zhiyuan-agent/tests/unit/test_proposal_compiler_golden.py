import importlib.util
import sys
from pathlib import Path


COMPILER_PATH = Path(__file__).resolve().parents[2] / "examples" / "proposal_compiler_golden.py"
SPEC = importlib.util.spec_from_file_location("proposal_compiler_golden", COMPILER_PATH)
assert SPEC and SPEC.loader
compiler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compiler
SPEC.loader.exec_module(compiler)


def _base_case(**overrides):
    case = {
        "caseId": "case",
        "tags": [],
        "planningStateProfile": {
            "formalPlanPresent": True,
            "pendingExists": False,
        },
        "expectedTurnDecision": {
            "taskLayer": "plan",
            "sideEffect": "plan_preview",
            "scopeAnchor": "current_plan",
            "targetIssue": ["major_scope"],
            "replyMode": ["confirmable_preview"],
            "missingInfo": [],
        },
        "expectedEvidencePlan": {
            "requiredInputs": ["formal_ordered_plan"],
            "noResultReason": None,
        },
        "expectedProposal": {
            "type": "plan_mutation",
            "pendingType": "plan_mutation",
            "actionFamilies": ["remove_units"],
            "requiresConfirmation": True,
        },
        "expectedPending": {
            "type": "pendingConfirmationCard",
            "required": True,
            "targetView": "ordered",
        },
        "replyQualityAssertions": {
            "mustAnswer": ["确认前不会执行"],
            "mustMentionAny": ["删除", "确认"],
            "mustNotMention": ["fix_proposal"],
        },
        "forbiddenDecisions": [],
    }
    case.update(overrides)
    return case


def test_compiler_keeps_plan_preview_as_pending_when_formal_plan_exists():
    record = compiler._evaluate_case(_base_case())

    assert record["passed"] is True
    assert record["pendingType"] == "plan_mutation"
    assert record["requiresConfirmation"] is True
    assert record["executionPayload"] == {
        "kind": "pending_plan_mutation",
        "scopeAnchor": "current_plan",
        "actionFamilies": ["remove_units"],
        "targetView": "ordered",
        "requiresConfirmation": True,
        "applyPolicy": "java_proposal_after_confirm",
    }
    assert record["displayPayload"]["presentation"] == "confirmation_card"
    assert record["replyPlan"]["focus"] == ["major_scope"]
    assert record["workspaceRefreshTargets"] == ["ordered"]


def test_compiler_blocks_plan_mutation_without_formal_plan():
    case = _base_case(
        planningStateProfile={"formalPlanPresent": False, "pendingExists": False},
        expectedPending={"required": False},
    )

    record = compiler._evaluate_case(case)

    assert record["pendingType"] == "none"
    assert record["requiresConfirmation"] is False
    assert record["executionPayload"] is None
    assert record["displayPayload"]["presentation"] == "clarification"
    assert "plan_mutation_requires_formal_plan" in record["blockingReasons"]


def test_compiler_does_not_apply_confirm_without_pending():
    case = _base_case(
        planningStateProfile={"formalPlanPresent": False, "pendingExists": False},
        expectedTurnDecision={
            "taskLayer": "pending",
            "sideEffect": "readonly",
            "scopeAnchor": "general",
            "missingInfo": [],
        },
        expectedProposal={"type": "readonly", "pendingType": "none", "requiresConfirmation": False},
        expectedPending={"required": False},
    )

    record = compiler._evaluate_case(case)

    assert record["passed"] is True
    assert record["pendingType"] == "none"
    assert record["requiresConfirmation"] is False
    assert record["executionPayload"] is None


def test_compiler_keeps_readonly_while_pending_unchanged():
    case = _base_case(
        planningStateProfile={"formalPlanPresent": True, "pendingExists": True},
        expectedTurnDecision={
            "taskLayer": "plan",
            "sideEffect": "readonly_while_pending",
            "scopeAnchor": "current_plan",
            "missingInfo": [],
        },
        expectedProposal={
            "type": "readonly",
            "pendingType": "unchanged_existing_pending",
            "requiresConfirmation": False,
        },
        expectedPending={"required": False},
    )

    record = compiler._evaluate_case(case)

    assert record["pendingType"] == "unchanged_existing_pending"
    assert record["requiresConfirmation"] is False
    assert record["executionPayload"] is None
    assert record["replyPlan"]["pendingReminder"] is True
    assert record["displayPayload"]["presentation"] == "readonly_answer"
    assert record["workspaceRefreshTargets"] == []


def test_compiler_treats_plan_mutation_or_none_as_unsupported_clarification():
    case = _base_case(
        planningStateProfile={"formalPlanPresent": True, "pendingExists": False},
        expectedTurnDecision={
            "taskLayer": "plan",
            "sideEffect": "plan_preview_or_clarification",
            "scopeAnchor": "current_plan",
            "scenario": "atomic_mutation",
            "missingInfo": [],
        },
        expectedProposal={
            "type": "plan_mutation_or_unsupported",
            "pendingType": "plan_mutation_or_none",
            "actionFamilies": ["pin_or_lock_unit"],
            "requiresConfirmation": True,
        },
        expectedPending={
            "type": "pendingConfirmationCard_or_none",
            "required": False,
            "targetView": "ordered",
        },
    )

    record = compiler._evaluate_case(case)

    assert record["passed"] is True
    assert record["pendingType"] == "plan_mutation_or_none"
    assert record["displayPayload"]["presentation"] == "conditional_options"
    assert record["workspaceRefreshTargets"] == []


def test_compiler_allows_negative_only_intent_pending():
    case = _base_case(
        tags=["negative_only"],
        planningStateProfile={"formalPlanPresent": False, "pendingExists": False},
        expectedTurnDecision={
            "taskLayer": "intent",
            "sideEffect": "intent_pending",
            "scopeAnchor": "future_reference",
            "targetIssue": ["region_exclusion"],
            "replyMode": ["confirmable_intent"],
            "missingInfo": [],
        },
        expectedProposal={
            "type": "intent_change",
            "pendingType": "intent_change",
            "negativeRegions": ["东北", "西北"],
            "requiresConfirmation": True,
        },
        expectedPending={"required": True},
    )

    record = compiler._evaluate_case(case)

    assert record["passed"] is True
    assert record["pendingType"] == "intent_change"
    assert record["executionPayload"]["kind"] == "pending_intent_change"
    assert record["intentPayload"]["negativeRegions"] == ["东北", "西北"]
    assert record["intentPayload"]["targetIssue"] == ["region_exclusion"]


def test_compiler_preserves_preference_strength_in_intent_payload():
    case = _base_case(
        planningStateProfile={"formalPlanPresent": False, "pendingExists": False},
        expectedTurnDecision={
            "taskLayer": "intent",
            "sideEffect": "intent_pending",
            "scopeAnchor": "future_reference",
            "targetIssue": ["major_preference", "major_exclusion"],
            "replyMode": ["confirmable_intent"],
            "missingInfo": [],
        },
        expectedProposal={
            "type": "intent_change",
            "pendingType": "intent_change",
            "preferenceStrength": {
                "primary": ["会计学", "审计学"],
                "exclude_hard": ["土木工程"],
            },
            "requiresConfirmation": True,
        },
        expectedPending={"required": True},
    )

    record = compiler._evaluate_case(case)

    assert record["passed"] is True
    assert record["intentPayload"]["preferenceStrength"] == {
        "primary": ["会计学", "审计学"],
        "exclude_hard": ["土木工程"],
    }
    assert record["displayPayload"]["presentation"] == "confirmation_card"


def test_compiler_builds_downstream_policy_from_preference_strength():
    case = _base_case(
        planningStateProfile={"formalPlanPresent": False, "pendingExists": False},
        expectedTurnDecision={
            "taskLayer": "intent",
            "sideEffect": "intent_pending",
            "scopeAnchor": "future_reference",
            "targetIssue": ["major_preference"],
            "replyMode": ["confirmable_intent"],
            "missingInfo": [],
        },
        expectedProposal={
            "type": "intent_change",
            "pendingType": "intent_change",
            "preferenceStrength": {
                "primary": ["网络与新媒体"],
                "acceptable": ["跨境电子商务"],
            },
            "requiresConfirmation": True,
        },
        expectedPending={"required": True},
    )

    record = compiler._evaluate_case(case)

    policy = record["downstreamPolicy"]
    assert policy["scope"] == "future_reference"
    assert policy["candidateSelection"]["rankBoost"] == [
        {"strength": "primary", "values": ["网络与新媒体"], "weight": 3},
        {"strength": "preferred", "values": [], "weight": 2},
        {"strength": "acceptable", "values": ["跨境电子商务"], "weight": 1},
    ]
    assert policy["replacementPolicy"]["fillPriority"] == [
        {
            "strength": "primary",
            "values": ["网络与新媒体"],
            "policy": "prefer_for_selection_and_replacement",
        },
        {
            "strength": "acceptable",
            "values": ["跨境电子商务"],
            "policy": "fallback_when_primary_or_preferred_insufficient_or_gradient_needed",
        },
    ]
    assert policy["replacementPolicy"]["replaceFirst"] == []


def test_compiler_downstream_policy_keeps_scope_and_hard_exclude_priority():
    case = _base_case(
        planningStateProfile={"formalPlanPresent": True, "pendingExists": False},
        expectedTurnDecision={
            "taskLayer": "intent",
            "sideEffect": "intent_pending",
            "scopeAnchor": "future_reference",
            "targetIssue": ["college_type", "tier_scope"],
            "replyMode": ["confirmable_intent"],
            "missingInfo": [],
        },
        expectedProposal={
            "type": "intent_change",
            "pendingType": "intent_change",
            "preferenceScope": "保底",
            "preferenceStrength": {
                "preferred": ["合肥工业大学", "南京邮电大学"],
                "exclude_hard": ["民办"],
            },
            "requiresConfirmation": True,
        },
        expectedPending={"required": True},
    )

    record = compiler._evaluate_case(case)

    policy = record["downstreamPolicy"]
    assert policy["scope"] == "保底"
    assert policy["candidateSelection"]["hardExclude"] == ["民办"]
    assert policy["replacementPolicy"]["replaceFirst"] == [
        {
            "reason": "exclude_hard_violation",
            "values": ["民办"],
            "policy": "remove_or_replace_before_ranking",
        }
    ]
    assert policy["replacementPolicy"]["protectFromReplacement"] == [
        {
            "strength": "preferred",
            "values": ["合肥工业大学", "南京邮电大学"],
            "policy": "do_not_replace_for_weaker_preference_without_conflict",
        }
    ]


def test_compiler_downstream_policy_distinguishes_only_keep_and_must_have():
    only_keep_case = _base_case(
        planningStateProfile={"formalPlanPresent": False, "pendingExists": False},
        expectedTurnDecision={
            "taskLayer": "intent",
            "sideEffect": "intent_pending",
            "scopeAnchor": "future_reference",
            "targetIssue": ["region_preference"],
            "replyMode": ["confirmable_intent"],
            "missingInfo": [],
        },
        expectedProposal={
            "type": "intent_change",
            "pendingType": "intent_change",
            "preferenceStrength": {"only_keep": ["长三角"]},
            "requiresConfirmation": True,
        },
        expectedPending={"required": True},
    )
    must_have_case = _base_case(
        planningStateProfile={"formalPlanPresent": False, "pendingExists": False},
        expectedTurnDecision={
            "taskLayer": "intent",
            "sideEffect": "intent_pending",
            "scopeAnchor": "future_reference",
            "targetIssue": ["school_type"],
            "replyMode": ["confirmable_intent"],
            "missingInfo": [],
        },
        expectedProposal={
            "type": "intent_change",
            "pendingType": "intent_change",
            "preferenceStrength": {"must_have": ["公办"]},
            "requiresConfirmation": True,
        },
        expectedPending={"required": True},
    )

    only_keep_record = compiler._evaluate_case(only_keep_case)
    must_have_record = compiler._evaluate_case(must_have_case)

    assert only_keep_record["downstreamPolicy"]["replacementPolicy"]["replaceFirst"] == [
        {
            "reason": "outside_only_keep_scope",
            "keepValues": ["长三角"],
            "policy": "remove_or_replace_out_of_scope_items",
        }
    ]
    assert only_keep_record["downstreamPolicy"]["candidateSelection"]["mustCover"] == []
    assert must_have_record["downstreamPolicy"]["replacementPolicy"]["replaceFirst"] == []
    assert must_have_record["downstreamPolicy"]["candidateSelection"]["mustCover"] == ["公办"]
    assert must_have_record["downstreamPolicy"]["replacementPolicy"]["fillPriority"] == [
        {
            "strength": "must_have",
            "values": ["公办"],
            "policy": "cover_at_least_one_without_dropping_unrelated_items",
        }
    ]


def test_compiler_downstream_policy_preserves_admission_path_entities():
    case = _base_case(
        planningStateProfile={"formalPlanPresent": False, "pendingExists": False},
        expectedTurnDecision={
            "taskLayer": "intent",
            "sideEffect": "intent_pending",
            "scopeAnchor": "special_path",
            "targetIssue": ["strongbase_school"],
            "replyMode": ["confirmable_intent", "path_boundary"],
            "missingInfo": [],
        },
        expectedProposal={
            "type": "intent_change",
            "pendingType": "intent_change",
            "admissionPath": "strongbase",
            "schools": ["清华大学", "北京大学", "复旦大学"],
            "requiresConfirmation": True,
        },
        expectedPending={"required": True},
    )

    record = compiler._evaluate_case(case)

    assert record["downstreamPolicy"]["scope"] == "special_path"
    assert record["downstreamPolicy"]["admissionPath"] == "strongbase"
    assert record["downstreamPolicy"]["pathEntities"] == {
        "schools": ["清华大学", "北京大学", "复旦大学"]
    }


def test_compiler_preserves_entity_polarity_spans_in_intent_payload():
    case = _base_case(
        planningStateProfile={"formalPlanPresent": False, "pendingExists": False},
        expectedTurnDecision={
            "taskLayer": "intent",
            "sideEffect": "intent_pending",
            "scopeAnchor": "future_reference",
            "targetIssue": ["major_preference", "major_exclusion"],
            "replyMode": ["confirmable_intent"],
            "missingInfo": [],
        },
        expectedProposal={
            "type": "intent_change",
            "pendingType": "intent_change",
            "preferenceStrength": {
                "primary": ["生物医学工程", "智能医学工程"],
                "exclude_hard": ["临床医学", "口腔医学"],
            },
            "entityPolaritySpans": [
                {"entity": "生物医学工程", "entityType": "major", "polarity": "positive"},
                {"entity": "智能医学工程", "entityType": "major", "polarity": "positive"},
                {"entity": "临床医学", "entityType": "major", "polarity": "negative"},
                {"entity": "口腔医学", "entityType": "major", "polarity": "negative"},
            ],
            "requiresConfirmation": True,
        },
        expectedPending={"required": True},
    )

    record = compiler._evaluate_case(case)

    assert record["passed"] is True
    assert record["intentPayload"]["entityPolaritySpans"] == [
        {"entity": "生物医学工程", "entityType": "major", "polarity": "positive"},
        {"entity": "智能医学工程", "entityType": "major", "polarity": "positive"},
        {"entity": "临床医学", "entityType": "major", "polarity": "negative"},
        {"entity": "口腔医学", "entityType": "major", "polarity": "negative"},
    ]


def test_compiler_rejects_invalid_entity_polarity_span():
    case = _base_case(
        planningStateProfile={"formalPlanPresent": False, "pendingExists": False},
        expectedTurnDecision={
            "taskLayer": "intent",
            "sideEffect": "intent_pending",
            "scopeAnchor": "future_reference",
            "targetIssue": ["major_preference"],
            "replyMode": ["confirmable_intent"],
            "missingInfo": [],
        },
        expectedProposal={
            "type": "intent_change",
            "pendingType": "intent_change",
            "entityPolaritySpans": [{"entity": "临床医学", "polarity": "avoid"}],
            "requiresConfirmation": True,
        },
        expectedPending={"required": True},
    )

    record = compiler._evaluate_case(case)

    assert "entity_polarity_span_0_invalid_polarity" in record["blockingReasons"]


def test_compiler_needs_plan_first_carries_missing_info_and_no_execution():
    case = _base_case(
        planningStateProfile={"formalPlanPresent": False, "pendingExists": False},
        expectedTurnDecision={
            "taskLayer": "plan",
            "sideEffect": "needs_plan_first",
            "scopeAnchor": "current_plan",
            "targetIssue": ["college_type"],
            "replyMode": ["state_explanation", "offer_generate_or_intent"],
            "missingInfo": ["formal_plan"],
        },
        expectedEvidencePlan={"noResultReason": "no_formal_plan"},
        expectedProposal={"type": "readonly", "pendingType": "none", "requiresConfirmation": False},
        expectedPending={"type": "none", "required": False, "targetView": None},
    )

    record = compiler._evaluate_case(case)

    assert record["passed"] is True
    assert record["pendingType"] == "none"
    assert record["executionPayload"] is None
    assert record["replyPlan"]["missingInfo"] == ["formal_plan"]
    assert record["replyPlan"]["noResultReason"] == "no_formal_plan"


def test_compiler_pending_conflict_requires_user_choice_without_dual_pending():
    case = _base_case(
        planningStateProfile={"formalPlanPresent": False, "pendingExists": True},
        expectedTurnDecision={
            "taskLayer": "plan",
            "sideEffect": "conflict_with_existing_pending",
            "scopeAnchor": "current_plan",
            "targetIssue": ["risk_tier", "delete_unit"],
            "replyMode": ["clarify_or_replace_pending"],
            "missingInfo": ["formal_plan"],
        },
        expectedProposal={
            "type": "clarification",
            "pendingType": "unchanged_or_replace_pending_after_choice",
            "requiresConfirmation": False,
        },
        expectedPending={"required": False},
    )

    record = compiler._evaluate_case(case)

    assert record["pendingType"] == "unchanged_or_replace_after_user_choice"
    assert record["requiresConfirmation"] is False
    assert record["executionPayload"]["kind"] == "pending_conflict_resolution"
    assert record["executionPayload"]["newPendingType"] == "none_until_user_choice"
    assert record["replyPlan"]["pendingConflict"] is True


def test_compiler_apply_then_readonly_has_apply_stage_without_new_pending():
    case = _base_case(
        planningStateProfile={"formalPlanPresent": True, "pendingExists": True},
        expectedTurnDecision={
            "taskLayer": "mixed",
            "sideEffect": "apply_pending_then_readonly",
            "scopeAnchor": "current_plan",
            "targetIssue": ["pending_apply", "plan_count", "tier_gradient"],
            "replyMode": ["apply_then_answer"],
            "missingInfo": [],
        },
        expectedProposal={
            "type": "apply_then_readonly",
            "pendingType": "none",
            "actionFamilies": ["apply_existing_pending", "query_state", "review_plan"],
            "requiresConfirmation": False,
        },
        expectedPending={
            "type": "none",
            "required": False,
            "targetView": "ordered",
            "workspaceRefreshTargets": ["ordered", "review"],
        },
    )

    record = compiler._evaluate_case(case)

    assert record["passed"] is True
    assert record["pendingType"] == "none"
    assert record["executionPayload"]["applyExistingPending"] is True
    assert record["executionPayload"]["newPendingType"] == "none"
    assert record["executionPayload"]["targetView"] == "ordered"
    assert record["workspaceRefreshTargets"] == ["ordered", "review"]


def test_compiler_preserves_pin_or_lock_plan_action_dsl():
    case = _base_case(
        expectedTurnDecision={
            "taskLayer": "plan",
            "sideEffect": "plan_preview_or_clarification",
            "scopeAnchor": "current_plan",
            "targetIssue": ["pin_or_lock_unit"],
            "replyMode": ["preview_or_unsupported"],
            "missingInfo": [],
        },
        expectedProposal={
            "type": "plan_mutation_or_unsupported",
            "pendingType": "plan_mutation_or_none",
            "actionFamilies": ["pin_or_lock_unit"],
            "requiresConfirmation": True,
            "planActionDsl": {
                "action": "pin_or_lock_unit",
                "scopeAnchor": "current_plan",
                "selectors": [
                    {"tier": "冲", "ordinal": 1},
                    {"tier": "冲", "ordinal": 2},
                ],
                "preservePosition": True,
            },
        },
        expectedPending={"type": "pendingConfirmationCard_or_none", "required": False, "targetView": "ordered"},
    )

    record = compiler._evaluate_case(case)

    assert record["planActionDsl"]["action"] == "pin_or_lock_unit"
    assert record["planActionDsl"]["selectors"] == [
        {"tier": "冲", "ordinal": 1},
        {"tier": "冲", "ordinal": 2},
    ]
    assert record["planActionDsl"]["preservePosition"] is True
    assert not any(reason.startswith("pin_or_lock") for reason in record["blockingReasons"])


def test_compiler_requires_selectors_for_pin_or_lock_plan_action_dsl():
    case = _base_case(
        expectedTurnDecision={
            "taskLayer": "plan",
            "sideEffect": "plan_preview_or_clarification",
            "scopeAnchor": "current_plan",
            "targetIssue": ["pin_or_lock_unit"],
            "replyMode": ["preview_or_unsupported"],
            "missingInfo": [],
        },
        expectedProposal={
            "type": "plan_mutation_or_unsupported",
            "pendingType": "plan_mutation_or_none",
            "actionFamilies": ["pin_or_lock_unit"],
            "requiresConfirmation": True,
            "planActionDsl": {
                "action": "pin_or_lock_unit",
                "scopeAnchor": "current_plan",
            },
        },
        expectedPending={"required": False},
    )

    record = compiler._evaluate_case(case)

    assert "pin_or_lock_requires_selectors" in record["blockingReasons"]


def test_compiler_preserves_tier_local_reorder_plan_action_dsl():
    case = _base_case(
        expectedTurnDecision={
            "taskLayer": "plan",
            "sideEffect": "plan_preview",
            "scopeAnchor": "current_plan.tier_segment",
            "targetIssue": ["tier_local_reorder"],
            "replyMode": ["confirmable_preview"],
            "missingInfo": [],
        },
        expectedProposal={
            "type": "plan_mutation",
            "pendingType": "plan_mutation",
            "actionFamilies": ["move_ordered_unit"],
            "requiresConfirmation": True,
            "planActionDsl": {
                "action": "move_ordered_unit",
                "scopeAnchor": "current_plan.tier_segment",
                "targetTier": "保底",
                "ordinalScope": "within_tier",
                "selector": {"tier": "保底", "sortBy": "admission_probability", "rank": "max"},
                "targetPosition": {"tier": "保底", "ordinal": 1},
            },
        },
        expectedPending={"type": "pendingConfirmationCard", "required": True, "targetView": "ordered"},
    )

    record = compiler._evaluate_case(case)

    assert record["passed"] is True
    assert record["planActionDsl"]["scopeAnchor"] == "current_plan.tier_segment"
    assert record["planActionDsl"]["targetTier"] == "保底"
    assert record["planActionDsl"]["ordinalScope"] == "within_tier"
    assert record["planActionDsl"]["targetPosition"] == {"tier": "保底", "ordinal": 1}


def test_compiler_rejects_tier_local_reorder_without_target_tier():
    case = _base_case(
        expectedTurnDecision={
            "taskLayer": "plan",
            "sideEffect": "plan_preview",
            "scopeAnchor": "current_plan.tier_segment",
            "targetIssue": ["tier_local_reorder"],
            "replyMode": ["confirmable_preview"],
            "missingInfo": [],
        },
        expectedProposal={
            "type": "plan_mutation",
            "pendingType": "plan_mutation",
            "actionFamilies": ["move_ordered_unit"],
            "requiresConfirmation": True,
            "planActionDsl": {
                "action": "move_ordered_unit",
                "scopeAnchor": "current_plan.tier_segment",
                "ordinalScope": "within_tier",
            },
        },
        expectedPending={"required": True, "targetView": "ordered"},
    )

    record = compiler._evaluate_case(case)

    assert "tier_local_ordinal_requires_target_tier" in record["blockingReasons"]


def test_compiler_carries_evidence_contract_tool_budget():
    case = _base_case(
        expectedEvidencePlan={
            "requiredInputs": ["formal_ordered_plan", "review_issues"],
            "steps": ["review_plan", "read_fix_proposal_candidates_if_available"],
            "toolBudget": {"maxToolCalls": 5, "batchPreferred": True},
            "noResultReason": None,
        },
    )

    record = compiler._evaluate_case(case)

    assert record["evidenceContract"] == {
        "requiredInputs": ["formal_ordered_plan", "review_issues"],
        "steps": ["review_plan", "read_fix_proposal_candidates_if_available"],
        "toolBudget": {"maxToolCalls": 5, "batchPreferred": True},
        "noResultReason": None,
    }


def test_compiler_selects_ready_java_fix_proposal_reference():
    case = _base_case(
        expectedTurnDecision={
            "taskLayer": "plan",
            "sideEffect": "plan_preview",
            "scopeAnchor": "current_plan",
            "targetIssue": ["tuition", "cooperative_program"],
            "replyMode": ["confirmable_preview"],
            "missingInfo": [],
        },
        expectedProposal={
            "type": "plan_mutation",
            "pendingType": "plan_mutation",
            "actionFamilies": ["apply_fix_proposal"],
            "requiresConfirmation": True,
            "proposalCandidates": [
                {
                    "id": "fix-1",
                    "type": "java_fix_proposal_reference",
                    "executionAuthority": "java_fix_proposal",
                    "ready": True,
                    "actions": [{"type": "replace"}],
                    "sourceVersionGuard": 8,
                    "dryRunObservation": {"capacityStatus": "satisfied"},
                }
            ],
        },
        expectedPending={"type": "pendingConfirmationCard", "required": True, "targetView": "review"},
    )

    record = compiler._evaluate_case(case)

    assert record["passed"] is True
    assert record["candidateArbitration"]["decision"] == "select"
    assert record["candidateArbitration"]["selectedCandidateIds"] == ["fix-1"]
    assert record["executionPayload"]["kind"] == "pending_plan_mutation"
    assert record["proposalCandidates"][0]["executionAuthority"] == "java_fix_proposal"


def test_compiler_blocks_java_fix_proposal_ready_without_actions():
    case = _base_case(
        expectedTurnDecision={
            "taskLayer": "plan",
            "sideEffect": "plan_preview",
            "scopeAnchor": "current_plan",
            "targetIssue": ["tuition"],
            "replyMode": ["diagnostic"],
            "missingInfo": [],
        },
        expectedProposal={
            "type": "plan_mutation",
            "pendingType": "plan_mutation",
            "actionFamilies": ["apply_fix_proposal"],
            "requiresConfirmation": True,
            "proposalCandidates": [
                {
                    "id": "fix-gap",
                    "type": "java_fix_proposal_reference",
                    "executionAuthority": "java_fix_proposal",
                    "ready": True,
                    "actions": [],
                    "sourceVersionGuard": 8,
                    "dryRunObservation": {"capacityStatus": "satisfied"},
                }
            ],
        },
        expectedPending={"type": "none", "required": False, "targetView": "review"},
    )

    record = compiler._evaluate_case(case)

    assert record["pendingType"] == "none"
    assert record["requiresConfirmation"] is False
    assert record["executionPayload"] is None
    assert record["displayPayload"]["presentation"] == "diagnostic"
    assert "java_fix_proposal_ready_without_actions" in record["blockingReasons"]
    assert record["candidateArbitration"]["blockedCandidateIds"] == ["fix-gap"]


def test_compiler_merges_intent_update_and_java_fix_proposal_candidate():
    case = _base_case(
        expectedTurnDecision={
            "taskLayer": "mixed",
            "sideEffect": "composite_pending",
            "scopeAnchor": "current_plan",
            "targetIssue": ["tuition", "future_reference"],
            "replyMode": ["confirmable_preview"],
            "missingInfo": [],
        },
        expectedProposal={
            "type": "composite",
            "pendingType": "plan_mutation",
            "actionFamilies": ["apply_selected_intents", "apply_fix_proposal"],
            "requiresConfirmation": True,
            "preferenceStrength": {"exclude_hard": ["高收费"]},
            "proposalCandidates": [
                {
                    "id": "intent-1",
                    "type": "intent_update_candidate",
                    "executionAuthority": "intent_state",
                    "mergeGroup": "tuition-composite",
                },
                {
                    "id": "fix-1",
                    "type": "java_fix_proposal_reference",
                    "executionAuthority": "java_fix_proposal",
                    "ready": True,
                    "actions": [{"type": "replace"}],
                    "sourceVersionGuard": 9,
                    "dryRunObservation": {"capacityStatus": "satisfied"},
                    "mergeGroup": "tuition-composite",
                },
            ],
        },
        expectedPending={"type": "pendingConfirmationCard", "required": True, "targetView": "review"},
    )

    record = compiler._evaluate_case(case)

    assert record["passed"] is True
    assert record["candidateArbitration"]["decision"] == "merge"
    assert record["candidateArbitration"]["mergedCandidateIds"] == ["intent-1", "fix-1"]
    assert record["pendingType"] == "plan_mutation"
    assert record["intentPayload"]["preferenceStrength"] == {"exclude_hard": ["高收费"]}


def test_compiler_blocks_rank_only_policy_from_creating_repair_mutation():
    case = _base_case(
        expectedTurnDecision={
            "taskLayer": "mixed",
            "sideEffect": "plan_preview",
            "scopeAnchor": "current_plan",
            "targetIssue": ["major_preference", "review_issue"],
            "replyMode": ["diagnostic"],
            "missingInfo": [],
        },
        expectedProposal={
            "type": "plan_mutation",
            "pendingType": "plan_mutation",
            "actionFamilies": ["apply_fix_proposal"],
            "requiresConfirmation": True,
            "proposalCandidates": [
                {
                    "id": "rank-1",
                    "type": "rank_only_policy_candidate",
                    "executionAuthority": "readonly_evidence",
                    "createsPending": False,
                }
            ],
        },
        expectedPending={"type": "none", "required": False, "targetView": "review"},
    )

    record = compiler._evaluate_case(case)

    assert record["pendingType"] == "none"
    assert "rank_only_policy_cannot_create_mutation" in record["blockingReasons"]
    assert record["candidateArbitration"]["blockedCandidateIds"] == ["rank-1"]
