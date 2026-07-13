"""Tests for ChatService persistence and model-first dialog entry."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart

from app.agent.context import RequestContext
from app.config import HistoryConfig
from app.data.history_store import ChatHistoryStore
from app.domain import proposal_compiler
from app.schemas.ws import WSResponse
from app.service import (
    ChatService,
    ChatServiceResponseEnvelope,
    _build_plan_timeout_fallback_reply,
    _intent_card_primary_reply_from_preview_payload,
    _create_pending_intent_confirmation_result_from_preview_payload,
    _pending_confirmation_primary_reply_from_card,
    _load_pending_confirmation_state,
    _save_pending_confirmation_state,
    build_runtime_history,
    _normalize_pending_intent_reply,
    _pending_confirmation_from_state,
    _pending_claim_expired,
    _format_intent_card_impact,
    _normalize_downgraded_intent_preview_reply,
    _normalize_false_apology_reply,
    _normalize_general_confirmation_protocol_wording,
    _normalize_plan_reply_style,
    _normalize_unbacked_recorded_wording,
    _normalize_unbacked_intent_preview_reply,
    _reply_looks_like_unbacked_intent_preview,
    _review_reply_needs_structured_fallback,
    _normalize_user_facing_terms,
    _sanitize_reply_for_user,
    _review_reply_overclaims_admission_safety,
    _summarize_intent_values,
    _build_pending_readonly_impact_reply,
    _format_fix_proposal_card_content,
    _selected_data_with_existing_positive_context,
    _select_conversation_action_family,
    _semantic_intent_decision_requires_readonly,
    _extract_recent_intent_analysis_payload,
    _guard_unbacked_plan_confirmation_reply,
    _constraint_user_goal_fix_candidate_from_preview,
    _enforce_single_pending_confirmation_followup,
    _pending_short_text_action,
    _no_pending_short_text_action,
)
from app.tools.intent_state_tool import IntentSideEffectDecision
from app.tools.intent_state_tool import apply_selected_intents
from app.tools.intent_response_tool import IntentStateUpdateResult, render_intent_state_update


def test_pending_short_text_action_detects_only_narrow_pending_actions():
    assert _pending_short_text_action("先不采纳了") == "cancel"
    assert _pending_short_text_action("暂不执行") == "cancel"
    assert _pending_short_text_action("不要确认，先别采纳") == "cancel"
    assert _pending_short_text_action("别采纳") == "cancel"
    assert _pending_short_text_action("确认执行") == "confirm"
    assert _pending_short_text_action("采纳") == "confirm"
    assert _pending_short_text_action("不要高收费的") == ""
    assert _pending_short_text_action("那就只看公办吧") == ""


def test_no_pending_short_text_action_is_narrower_than_active_pending_actions():
    assert _no_pending_short_text_action("确认") == "confirm"
    assert _no_pending_short_text_action("确认执行") == "confirm"
    assert _no_pending_short_text_action("采纳") == "confirm"
    assert _no_pending_short_text_action("嗯可以") == "confirm"
    assert _no_pending_short_text_action("取消") == "cancel"
    assert _no_pending_short_text_action("先不采纳了") == "cancel"
    assert _no_pending_short_text_action("就这样") == ""
    assert _no_pending_short_text_action("按这个") == ""
    assert _no_pending_short_text_action("不要高收费的") == ""
    assert _no_pending_short_text_action("那就只看公办吧") == ""


def test_pending_confirmation_loads_and_saves_dedicated_revision():
    latest_response = {
        "code": 0,
        "data": {
            "chatSessionId": 9904301,
            "pendingId": "pending-versioned",
            "revision": 7,
            "dataValue": json.dumps(
                {
                    "type": "pendingConfirmation",
                    "pendingId": "pending-versioned",
                    "kind": "plan_mutation",
                    "status": "active",
                    "actionFamily": "remove_units",
                    "executionPayload": {
                        "action_family": "remove_units",
                        "atomic_actions": [{"action_type": "remove_units", "unit_ids": ["u1"]}],
                    },
                    "sourceBackendVersion": 248,
                },
                ensure_ascii=False,
            ),
        },
    }
    save_mock = AsyncMock(return_value={"code": 0})

    with patch("app.service.get_last_pending_confirmation", AsyncMock(return_value=latest_response)), \
            patch("app.service.save_pending_confirmation", save_mock):
        state = asyncio.run(_load_pending_confirmation_state("9904301"))
        assert state is not None
        assert state["pendingId"] == "pending-versioned"
        assert state["_pendingRevision"] == 7
        applied_state = dict(state)
        applied_state["status"] = "applied"
        asyncio.run(_save_pending_confirmation_state("9904301", applied_state))

    save_mock.assert_awaited_once()
    assert save_mock.await_args.args[:2] == ("9904301", applied_state)
    assert save_mock.await_args.kwargs == {}


def test_pending_confirmation_loads_claim_lease_metadata():
    expires_at = int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp() * 1000)
    response = {
        "code": 0,
        "data": {
            "pendingId": "pending-lease",
            "revision": 9,
            "status": "applying",
            "claimToken": "claim-owner",
            "claimExpiresAt": expires_at,
            "dataValue": {
                "pendingId": "pending-lease",
                "kind": "plan_mutation",
                "status": "applying",
                "actionFamily": "remove_units",
                "executionPayload": {
                    "action_family": "remove_units",
                    "atomic_actions": [{"action_type": "remove_units", "unit_ids": ["u1"]}],
                },
            },
        },
    }

    with patch("app.service.get_last_pending_confirmation", AsyncMock(return_value=response)):
        state = asyncio.run(_load_pending_confirmation_state("9904301"))

    assert state["_pendingClaimToken"] == "claim-owner"
    assert state["_pendingClaimExpiresAt"] == expires_at
    assert _pending_claim_expired(state) is False


def test_pending_confirmation_empty_latest_does_not_resurrect_version_zero():
    pending = {
        "type": "pendingConfirmation",
        "pendingId": "pending-v0",
        "kind": "intent_change",
        "status": "active",
        "actionFamily": "apply_selected_intents",
        "executionPayload": {"merged": {"school_intents": {"negative_school_nature": ["民办"]}}},
    }

    with patch("app.service.get_last_pending_confirmation", AsyncMock(return_value={"code": 0, "data": {}})):
        state = asyncio.run(_load_pending_confirmation_state("9904302"))

    assert state is None


def test_pending_confirmation_latest_lookup_failure_does_not_resurrect_version_zero():
    with patch(
        "app.service.get_last_pending_confirmation",
        AsyncMock(side_effect=TimeoutError("latest lookup timed out")),
    ):
        state = asyncio.run(_load_pending_confirmation_state("9904302"))

    assert state is None



def _semantic_pending(action: str, confidence: float = 0.95, reason: str = "test"):
    return MagicMock(action=action, confidence=confidence, reason=reason)


def _semantic_plan(
    action_family: str,
    confidence: float = 0.95,
    reason: str = "test",
    target_strategies: list[str] | None = None,
    target_issue_codes: list[str] | None = None,
    reply_focus: list[str] | None = None,
    profile_scenario: str = "none",
    proposed_profile: dict | None = None,
):
    return MagicMock(
        actionFamily=action_family,
        confidence=confidence,
        reason=reason,
        replyFocus=reply_focus or [],
        targetStrategies=target_strategies or [],
        targetIssueCodes=target_issue_codes or [],
        profileScenario=profile_scenario,
        proposedProfile=proposed_profile or {},
    )


def _runtime_turn_decision(
    *,
    task_layer: str = "intent",
    side_effect: str = "intent_pending",
    scope_anchor: str = "future_reference",
    scenario: str = "intent_update",
    target_issue: list[str] | None = None,
    profile_scenario: str = "none",
    proposed_profile: dict | None = None,
    confidence: float = 0.9,
):
    return SimpleNamespace(
        taskLayer=task_layer,
        sideEffect=side_effect,
        scopeAnchor=scope_anchor,
        scenario=scenario,
        targetIssue=target_issue or [],
        profileScenario=profile_scenario,
        proposedProfile=proposed_profile or {},
        confidence=confidence,
        reason="test",
    )


def _pending_conflict_turn_decision(confidence: float = 0.95):
    return _runtime_turn_decision(
        task_layer="plan",
        side_effect="conflict_with_existing_pending",
        scope_anchor="current_plan",
        scenario="pending_conflict_new_mutation",
        confidence=confidence,
    )


def _plan_query_profile(
    *,
    query_type: str,
    scope_anchor: str | None = None,
    dimensions: list[str] | None = None,
    filters: dict | None = None,
    projection: dict | None = None,
    reply_focus: list[str] | None = None,
    pending_reference_type: str = "none",
    confidence: float = 0.9,
):
    payload = {
        "queryType": query_type,
        "scopeAnchor": scope_anchor or ("pending_reference" if query_type == "readonly_pending_reference_query" else "current_plan"),
        "sideEffect": "readonly",
        "dimensions": dimensions or [],
        "filters": filters or {},
        "projection": projection or {},
        "replyFocus": reply_focus or [],
        "pendingReferenceType": pending_reference_type,
        "confidence": confidence,
        "reason": "test",
    }
    return SimpleNamespace(**payload, model_dump=lambda: dict(payload))


def _intent_side_effect(
    decision: str,
    confidence: float = 0.95,
    reason: str = "test",
):
    return IntentSideEffectDecision(
        decision=decision,
        confidence=confidence,
        reason=reason,
    )


def test_semantic_intent_readonly_respects_explicit_entity_override():
    assert _semantic_intent_decision_requires_readonly(
        {
            "decision": "mixed_answer_then_ask",
            "confidence": 0.9,
            "honored": False,
        }
    ) is False
    assert _semantic_intent_decision_requires_readonly(
        {
            "decision": "mixed_answer_then_ask",
            "confidence": 0.9,
            "honored": True,
        }
    ) is True


def _assert_no_pending_confirmation_guard(reply: str) -> None:
    assert "没有上一轮待确认" in reply
    assert "没有待执行" in reply
    assert "确认前不会改方案" in reply


def _tool_return(action_family: str) -> ToolReturnPart:
    return ToolReturnPart(
        tool_name="runtime_action_result",
        content=json.dumps({"action_family": action_family}, ensure_ascii=False),
        tool_call_id=f"tool-{action_family}",
    )


def test_select_conversation_action_family_prefers_last_non_query_action():
    action_family = _select_conversation_action_family(
        [
            _tool_return("query_state"),
            _tool_return("remove_ordered_unit"),
        ]
    )

    assert action_family == "remove_ordered_unit"


def test_select_conversation_action_family_keeps_query_when_only_query_actions():
    action_family = _select_conversation_action_family(
        [
            _tool_return("query_state"),
            _tool_return("query_ordered"),
        ]
    )

    assert action_family == "query_ordered"


def test_format_intent_card_impact_uses_directional_preference_wording():
    positive = _format_intent_card_impact(
        {"major_intents": {"level3": ["工商管理"]}},
        intent_mode="preference",
    )
    negative = _format_intent_card_impact(
        {"major_intents": {"negative_level3": ["秘书学"]}},
        intent_mode="preference",
    )
    mixed = _format_intent_card_impact(
        {
            "major_intents": {
                "level3": ["工商管理"],
                "negative_level3": ["秘书学"],
            }
        },
        intent_mode="preference",
    )
    constraint = _format_intent_card_impact(
        {"city_intents": {"negative_province": ["江苏"]}},
        intent_mode="constraint",
    )

    assert "排得更靠前" in positive
    assert "适当靠后" not in positive
    assert "适当靠后" in negative
    assert "优先方向" in mixed
    assert "避开这些方向" in constraint

    mixed_constraint = _format_intent_card_impact(
        {
            "major_intents": {
                "level3": ["会计学"],
                "negative_level3": ["土木工程"],
            }
        },
        intent_mode="constraint",
    )
    assert "优先方向会排得更靠前" in mixed_constraint
    assert "避开的方向" in mixed_constraint

    only_keep = _format_intent_card_impact(
        {
            "constraintIntentType": "only_keep",
            "major_intents": {"level3": ["临床医学"]},
        },
        intent_mode="constraint",
    )
    must_have = _format_intent_card_impact(
        {
            "constraintIntentType": "must_have",
            "major_intents": {"level3": ["临床医学"]},
        },
        intent_mode="constraint",
    )
    assert "只保留这个范围" in only_keep
    assert "至少保留这个方向" in must_have


def test_format_intent_card_impact_treats_only_keep_as_constraint_even_if_mode_is_preference():
    reply = _format_intent_card_impact(
        {
            "intentMode": "preference",
            "constraintIntentType": "only_keep",
            "major_intents": {"level3": ["电气工程及其自动化", "大气科学"]},
        },
        intent_mode="preference",
    )

    assert "只保留这个范围" in reply
    assert "排得更靠前" not in reply


def test_format_intent_card_impact_uses_constraint_plan_fallback_when_no_preview():
    reply = _format_intent_card_impact(
        {
            "intentMode": "constraint",
            "constraintIntentType": "only_keep",
            "major_intents": {"level3": ["临床医学"]},
        },
        intent_mode="constraint",
        fallback_mechanism_line="采纳后先把这条条件记下来；当前没有可直接执行的方案调整。",
        fallback_detail_lines=["当前方案和候选池里暂时都没有找到“临床医学”相关选择。"],
    )

    assert "当前没有可直接执行的方案调整" in reply
    assert "当前方案和候选池里暂时都没有找到" in reply
    assert "只保留这个范围" not in reply


def test_summarize_intent_values_uses_constraint_specific_positive_labels():
    merged = {"major_intents": {"level3": ["临床医学"]}}

    assert _summarize_intent_values(
        merged,
        intent_mode="constraint",
        constraint_intent_type="only_keep",
    ) == "只保留专业：临床医学"
    assert _summarize_intent_values(
        merged,
        intent_mode="constraint",
        constraint_intent_type="must_have",
    ) == "至少保留专业：临床医学"
    assert _summarize_intent_values(merged, intent_mode="preference") == "偏好专业：临床医学"


def test_summarize_intent_values_uses_career_labels():
    merged = {"career_intents": {"positive": ["system_public_service"], "negative": ["stable_employment"]}}

    assert _summarize_intent_values(merged, intent_mode="preference") == "发展方向：体制内/考公导向；不优先发展方向：稳定就业导向"


def test_summarize_intent_values_keeps_literal_career_values_when_slots_are_unmapped():
    merged = {"career_intents": {"positive": ["体制内", "稳定就业"]}}

    assert _summarize_intent_values(merged, intent_mode="preference") == "发展方向：体制内/考公导向、稳定就业导向"


def test_summarize_intent_values_supports_tuition_budget():
    merged = {"tuition_budget": {"max_tuition_per_year": [20000]}}

    assert _summarize_intent_values(merged, intent_mode="preference") == "学费预算：每年不超过 20000 元"


def test_apply_selected_intents_syncs_tuition_budget_range():
    with patch("app.tools.intent_state_tool.ProfileManager") as profile_manager_mock, \
            patch("app.tools.intent_state_tool._sync_constraint_state_best_effort", AsyncMock(return_value=True)), \
            patch("app.tools.intent_state_tool._mark_intent_change_stale_best_effort", AsyncMock(return_value=True)), \
            patch("app.tools.intent_state_tool._refresh_recommendation_overlay_best_effort", AsyncMock(return_value=True)), \
            patch("app.tools.intent_state_tool.update_session_tuition_range", AsyncMock(return_value={"code": 0, "data": True})) as tuition_mock:
        profile_manager_mock.return_value.update_major_intent = AsyncMock()
        result_text = asyncio.run(
            apply_selected_intents(
                "20001",
                "01",
                {
                    "selected": [{"tuition_budget": {"max_tuition_per_year": [20000]}}],
                    "intentMode": "preference",
                },
            )
        )

    result = json.loads(result_text)
    assert result["applied"] is True
    assert result["merged"]["tuition_budget"]["max_tuition_per_year"] == [20000]
    assert "学费预算：每年不超过 20000 元" in result["message"]
    assert result["recommendationRefresh"]["tuitionBudgetSynced"]["success"] is True
    tuition_mock.assert_awaited_once_with("20001", min_tuition=0, max_tuition=20000)


def test_intent_card_primary_reply_uses_career_item_values_before_generic_title():
    reply = _intent_card_primary_reply_from_preview_payload(
        {
            "status": "ready",
            "title": "好的，我先把这次你提到的想法整理一下。你可以勾选想采纳的内容后点击【采纳】。",
            "intentMode": "preference",
            "constraintIntentType": "default",
            "analysisStage": "confirmed",
            "items": [
                {
                    "content": "把“体制内”记成你更看重的方向，后面我会优先按这个思路帮你看方案。",
                    "value": {"career_intents": {"positive": ["体制内"]}},
                    "selected": True,
                },
                {
                    "content": "把“稳定就业”记成你更看重的方向，后面我会优先按这个思路帮你看方案。",
                    "value": {"career_intents": {"positive": ["稳定就业"]}},
                    "selected": True,
                },
            ],
            "existingItems": [],
        }
    )

    assert "发展方向" in reply
    assert "体制内" in reply
    assert "稳定就业" in reply
    assert "好的，我先把这次你提到的想法整理一下" not in reply


def test_render_intent_state_update_uses_constraint_specific_summary():
    rendered = render_intent_state_update(
        IntentStateUpdateResult(
            action="apply_selected",
            sessionId="s1",
            intentMode="constraint",
            constraintIntentType="only_keep",
            applied=True,
            messageCode="constraint_applied",
            merged={"major_intents": {"level3": ["临床医学"]}},
        )
    )

    assert "本次内容：只保留专业：临床医学" in rendered
    assert "本次内容：偏好专业：临床医学" not in rendered
    assert "检查当前方案里有没有不符合这条条件" not in rendered
    assert "整理一版调整预览" in rendered


def test_pending_confirmation_from_state_preserves_composite_proposal():
    composite = {
        "goal": {
            "goal_type": "only_keep_scope",
            "target_scopes": [{"entity_type": "major", "values": ["临床医学"]}],
        },
        "intent_updates": [{"constraintIntentType": "only_keep"}],
    }
    pending_state = {
        "pendingId": "pending-composite",
        "status": "active",
        "kind": "intent_change",
        "actionFamily": "apply_selected_intents",
        "summary": "只保留临床医学",
        "executionPayload": {
            "merged": {"major_intents": {"level3": ["临床医学"]}},
            "selectedData": {"selected": [{"major_intents": {"level3": ["临床医学"]}}]},
        },
        "compositeProposal": composite,
    }

    pending = _pending_confirmation_from_state(pending_state)

    assert pending is not None
    assert pending.kind == "intent_change"
    assert pending.composite_proposal == composite


def test_pending_confirmation_from_state_accepts_plan_generation():
    pending_state = {
        "pendingId": "pending-plan-generation",
        "status": "active",
        "kind": "plan_generation",
        "actionFamily": "regenerate_order",
        "summary": "重新生成排序方案",
        "executionPayload": {
            "action_family": "regenerate_order",
            "atomic_actions": [
                {"action_type": "regenerate_order", "filters": {"review_issue_code": "probability_gap"}}
            ],
        },
        "sourceBackendVersion": 12,
    }

    pending = _pending_confirmation_from_state(pending_state)

    assert pending is not None
    assert pending.kind == "plan_generation"
    assert pending.action_family == "regenerate_order"


def test_pending_confirmation_from_state_preserves_pending_id():
    pending_state = {
        "pendingId": "pending-current-snapshot",
        "status": "active",
        "kind": "intent_change",
        "actionFamily": "apply_selected_intents",
        "executionPayload": {"merged": {"city_intents": {"negative_province": ["山东"]}}},
    }

    pending = _pending_confirmation_from_state(pending_state)

    assert pending is not None
    assert pending.pending_id == "pending-current-snapshot"


def test_unexpired_applying_pending_is_not_projected_for_second_execution():
    pending_state = {
        "pendingId": "pending-applying",
        "kind": "plan_mutation",
        "status": "applying",
        "actionFamily": "remove_units",
        "executionPayload": {
            "action_family": "remove_units",
            "atomic_actions": [{"action_type": "remove_units", "unit_ids": ["u1"]}],
        },
        "_pendingClaimExpiresAt": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
    }

    assert _pending_claim_expired(pending_state) is False
    assert _pending_confirmation_from_state(pending_state) is None


def test_expired_applying_pending_is_projected_for_lease_recovery():
    pending_state = {
        "pendingId": "pending-applying-expired",
        "kind": "plan_mutation",
        "status": "applying",
        "actionFamily": "remove_units",
        "executionPayload": {
            "action_family": "remove_units",
            "atomic_actions": [{"action_type": "remove_units", "unit_ids": ["u1"]}],
        },
        "_pendingClaimExpiresAt": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
    }

    assert _pending_claim_expired(pending_state) is True
    pending = _pending_confirmation_from_state(pending_state)
    assert pending is not None
    assert pending.pending_id == "pending-applying-expired"


@pytest.mark.parametrize(
    "pending_state",
    [
        {
            "status": "active",
            "kind": "legacy_intent",
            "pendingId": "pending-legacy-kind",
            "actionFamily": "apply_selected_intents",
            "executionPayload": {"merged": {"city_intents": {"negative_area": ["偏远地区"]}}},
        },
        {
            "status": "active",
            "kind": "plan_mutation",
            "pendingId": "pending-legacy-payload",
            "actionFamily": "remove_units",
            "executionPayload": {"planPayload": {"unitIds": ["u1"]}},
        },
        {
            "status": "failed",
            "kind": "intent_change",
            "pendingId": "pending-failed",
            "actionFamily": "apply_selected_intents",
            "executionPayload": {"merged": {"city_intents": {"negative_area": ["偏远地区"]}}},
        },
    ],
)
def test_pending_confirmation_from_state_rejects_non_executable_snapshots(pending_state):
    assert _pending_confirmation_from_state(pending_state) is None


def test_pending_confirmation_from_state_rejects_anonymous_active_pending():
    pending_state = {
        "status": "active",
        "kind": "intent_change",
        "actionFamily": "apply_selected_intents",
        "executionPayload": {"merged": {"city_intents": {"negative_province": ["山东"]}}},
    }

    assert _pending_confirmation_from_state(pending_state) is None


def test_selected_data_with_existing_positive_context_augments_negative_only_preview():
    selected_data = {
        "selected": [{"major_intents": {"negative_level3": ["土木工程"]}}],
        "intentMode": "constraint",
        "batch": "01",
    }
    existing_merged = {"major_intents": {"level3": ["会计学", "审计学"]}}

    augmented = _selected_data_with_existing_positive_context(selected_data, existing_merged)

    assert augmented["selected"] == [
        {"major_intents": {"negative_level3": ["土木工程"]}},
        {"major_intents": {"level3": ["会计学", "审计学"]}},
    ]


def test_selected_data_with_existing_positive_context_keeps_explicit_positive_preview():
    selected_data = {
        "selected": [
            {"major_intents": {"level3": ["会计学"]}},
            {"major_intents": {"negative_level3": ["土木工程"]}},
        ],
        "intentMode": "constraint",
        "batch": "01",
    }
    existing_merged = {"major_intents": {"level3": ["审计学"]}}

    augmented = _selected_data_with_existing_positive_context(selected_data, existing_merged)

    assert augmented is selected_data
    assert augmented["selected"] == [
        {"major_intents": {"level3": ["会计学"]}},
        {"major_intents": {"negative_level3": ["土木工程"]}},
    ]


def test_normalize_downgraded_intent_preview_reply_removes_fake_pending_claim():
    reply = (
        "我先把情况理清楚。\n\n"
        "**下一步**\n"
        "我先把这个要求整理成待确认偏好，你确认后我再作为后续参考去筛方案。"
        "我可以把这个要求整理成排除条件。确认后，我会在后续推荐和方案审查里帮你避开这些方向。"
        "我可以把“不考虑师范类专业”整理成一条待确认要求，涵盖教育学类。"
        "你确认要把“不考虑师范类专业”作为后续参考吗？采纳/确认前不会生效。"
        "你确认要排除教育学门类（含各类师范专业）吗？"
        "要不要我先整理成排除要求？确认后，我会在后续推荐里过滤。"
        "告诉我，我帮你记成后续参考。"
    )

    normalized = _normalize_downgraded_intent_preview_reply(reply)

    assert "整理成待确认" not in normalized
    assert "一条待确认要求" not in normalized
    assert "你确认后我再" not in normalized
    assert "确认后，我会" not in normalized
    assert "帮你记成后续参考" not in normalized
    assert "列出来让你采纳" in normalized
    assert "采纳前不会生效" in normalized
    assert "采纳前不会生效" in normalized


def test_normalize_downgraded_intent_preview_reply_removes_fake_card_and_candidate_pool_claim():
    reply = (
        "**先看影响和边界**\n\n"
        "1. 排除范围：医学门类较宽，点击采纳后会一并过滤掉临床医学、护理学等相关方向。\n"
        "2. 当前状态：后续生成方案时，系统会按这个口径来筛选。\n"
        "3. 如果后续生成方案，系统会优先推荐财会，并自动过滤医学/护理相关选项。\n"
        "4. 如果确认排除，后续推荐和方案检查会把这类专业整体作为排除参考，不再进入候选。"
    )

    normalized = _normalize_downgraded_intent_preview_reply(reply)

    assert "点击采纳后" not in normalized
    assert "过滤掉" not in normalized
    assert "自动过滤" not in normalized
    assert "不再进入候选" not in normalized
    assert "按这个口径来筛选" not in normalized
    assert "基础可选范围不会因此变小" in normalized
    assert "作为排除参考" in normalized


def test_interest_stage_detection_includes_readonly_interest_tools():
    messages = [
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="explore_topic",
                    content="只读专业影响分析。",
                    tool_call_id="major-interest-call",
                )
            ]
        )
    ]

    from app.service import _tool_returns_interest_stage_intent_analysis

    assert _tool_returns_interest_stage_intent_analysis(messages) is True


def test_build_pending_readonly_impact_reply_keeps_plan_pending_inactive():
    reply = _build_pending_readonly_impact_reply(
        {
            "kind": "plan_mutation",
            "actionFamily": "remove_units",
            "summary": "已在当前方案里定位到土木工程相关的 3 条志愿。",
            "executionPayload": {
                "intentPayload": {
                    "intentMode": "constraint",
                    "selected": [
                        {"major_intents": {"level3": ["会计学"], "negative_level3": ["土木工程"]}},
                    ],
                }
            },
        }
    )

    assert "当前方案" in reply
    assert "影响" in reply
    assert "还没有执行" in reply


def test_chat_service_needs_plan_first_guard_runs_before_zhiyuan_direct(
    tmp_path,
    mock_llm_client,
):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()
    fake_agent = _FakeAgent(["不应该调用旧模型"])
    direct_agent = SimpleNamespace(run_with_message_deltas=AsyncMock())

    with patch("app.service.ZhiyuanAgent", return_value=direct_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01", "totalScore": 620}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={
                "code": 0,
                "data": {
                    "phase": "none",
                    "version": 0,
                    "orderedPlanState": {"summary": {"total": 0}},
                    "workingPlanState": {"summary": {"total": 0}},
                    "reviewState": {"summary": {"warnCount": 0, "riskCount": 0}, "checks": []},
                },
            })), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_last_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "session-needs-plan-first-before-direct",
                "user-1",
                "希望通过生物科学和化学这样的专业保住院校层次，在方案中增加湖南的湘潭大学、长沙理工、湖南科技大学、吉首大学、湖南农业大学、延边大学的工科专业组。去掉",
            )
        )

    assert isinstance(reply, str)
    assert "当前还没有生成正式方案" in reply
    assert "生物科学" in reply
    assert "湘潭大学" in reply
    assert "不会改动方案" in reply
    assert pending_state == {}
    save_pending_mock.assert_not_awaited()
    direct_agent.run_with_message_deltas.assert_not_awaited()
    assert fake_agent.calls == []
    saved_history = asyncio.run(store.load("session-needs-plan-first-before-direct"))
    route_events = []
    for message in saved_history or []:
        for part in getattr(message, "parts", []) or []:
            if not isinstance(part, TextPart):
                continue
            try:
                data = json.loads(part.content)
            except Exception:
                continue
            if isinstance(data, dict) and data.get("type") == "routeObservability":
                route_events.append(data)
    assert route_events
    assert route_events[-1]["routingPath"] == "needs_plan_first_guard"


def test_normalize_general_confirmation_protocol_uses_card_for_confirm_preference():
    reply = (
        "如果你确认想把师范类专业从后续推荐中排除，"
        "我可以整理成确认偏好。你确认后，我会在后续方案中过滤掉纯师范方向。"
        "如果确认“不想当老师”作为硬性排除，我可以把**教育学类、师范类**整理成待确认偏好，确认后会自动过滤后续推荐。"
        "如果你确实想把英语优势作为后续筛选的参考方向，"
        "我可以先整理成待确认偏好，确认后再帮你匹配具体志愿。"
        "我可以先整理成待采纳内容，确认后再帮你检查当前方案。"
        "有的话可以直接告诉我，我帮你记成后续参考。"
    )

    normalized = _normalize_general_confirmation_protocol_wording(reply)

    assert "确认偏好" not in normalized
    assert "待确认偏好" not in normalized
    assert "你确认后" not in normalized
    assert "确认后会" not in normalized
    assert "确认后再" not in normalized
    assert "帮你记成后续参考" not in normalized
    assert "列出来" in normalized
    assert "采纳" in normalized
    assert "点“采纳”前不会生效" in normalized
    assert "采纳后，我会" in normalized
    assert "采纳后再帮你匹配具体志愿" in normalized
    assert "不会生效。，" not in normalized


def test_normalize_user_facing_terms_removes_internal_review_repair_words():
    normalized = _normalize_user_facing_terms(
        "系统阻塞。阻塞原因：替换会改变专业组数量，系统暂不支持自动确认。"
        "blocked，暂不能自动处理，也无法生成确认卡片。preview_only，ready"
    )

    assert "系统阻塞" not in normalized
    assert "阻塞原因" not in normalized
    assert "系统暂不支持" not in normalized
    assert "自动确认" not in normalized
    assert "专业组数量" not in normalized
    assert "暂不允许" not in normalized
    assert "blocked" not in normalized
    assert "ready" not in normalized
    assert "暂不能自动处理" not in normalized
    assert "无法生成确认" not in normalized
    assert "preview_only" not in normalized
    assert "需要注意" in normalized
    assert "需要你先确认是否接受这类调整或放宽报考条件" in normalized
    assert "可以先看调整预览" in normalized
    assert "建议你先查看具体影响，或调整筛选范围后再试" in normalized
    assert "替换可能会影响整组志愿的搭配" in normalized


def test_normalize_user_facing_terms_softens_review_fix_proposal_language():
    normalized = _normalize_user_facing_terms(
        "能否自动修复：系统尝试替换，但当前候选池里暂时无法自动补强安全垫，"
        "无法批量处理，需要人工调整。"
    )

    forbidden_terms = ("能否自动修复", "系统尝试", "候选池", "自动补强", "无法批量处理", "需要人工调整")
    for term in forbidden_terms:
        assert term not in normalized
    assert "怎么处理" in normalized
    assert "我查了一下替换" in normalized
    assert "候选志愿" in normalized
    assert "当前暂时缺少合适的补位选择" in normalized
    assert "不能一次性处理完" in normalized
    assert "需要你先取舍或手动调整" in normalized


def test_normalize_user_facing_terms_removes_more_review_system_copy():
    normalized = _normalize_user_facing_terms(
        "系统预估可以替换后补入同等数量的志愿，但系统不会擅自删你的志愿。"
        "这三个提醒本质上都是需要你给个明确态度才敢动。"
        "可以立即处理的有 2 项，候选供给也充足。"
        "核心原因不是系统做不到，而是需要你取舍；不是系统搜不到，而是这个组里确实没有。"
        "系统现在给不了你更好的组内替代。"
        "替换后专业组数量会变，我可以直接帮你把这类志愿移出方案。"
        "你的方案目前 3 个提醒，系统都需要你先取舍后再处理。"
        "系统目前在你的候选志愿里找不到更合适的兜底专业。"
        "替换同样会影响专业组数量，需要你给出明确态度。"
        "我就能帮你生成移除预览，也可以在方案里把这些志愿整体移除。"
        "或者我直接帮你生成一个录取率排序和补兜底的调整预览。"
    )

    forbidden_terms = (
        "系统预估",
        "系统不会",
        "给个明确态度",
        "才敢动",
        "可以立即处理",
        "候选供给",
        "系统做不到",
        "系统搜不到",
        "系统现在给不了",
        "系统都需要你",
        "系统目前在",
        "专业组数量",
        "我可以直接帮你",
        "我就能帮你生成",
        "我直接帮你生成",
        "直接帮你生成",
        "给出明确态度",
    )
    for term in forbidden_terms:
        assert term not in normalized
    assert "目前看" in normalized
    assert "不会擅自删你的志愿" in normalized
    assert "明确取舍范围" in normalized
    assert "可以先看调整预览的有 2 项" in normalized
    assert "可选志愿也充足" in normalized
    assert "核心原因是需要你取舍" in normalized
    assert "当前还没有更好的组内替代" in normalized
    assert "替换后专业组搭配会变" in normalized
    assert "我会先列出移除预览" in normalized
    assert "都需要你先取舍后再处理" in normalized
    assert "当前在你的候选志愿里找不到更合适的兜底专业" in normalized
    assert "替换同样会影响整组志愿搭配" in normalized
    assert "我会先列出移除预览" in normalized
    assert "我先列出一个录取率排序和补兜底的调整预览" in normalized


def test_sanitize_reply_for_user_softens_review_repair_overpromises():
    reply = _sanitize_reply_for_user(
        "下面这 6 项都因为候选范围不够或会改变专业组数量，系统没法自动执行。"
        "前两项是要不要保留这个专业组没定，第三项是候选机会池子已经见底了。"
        "你给我个明确态度，我立刻处理。"
    )

    forbidden_terms = (
        "系统没法",
        "自动执行",
        "候选机会池子",
        "给我个明确态度",
        "我立刻处理",
        "我就能",
    )
    for term in forbidden_terms:
        assert term not in reply
    assert "需要你先取舍" in reply
    assert "当前符合条件的可选志愿已经不多" in reply
    assert "先列出调整预览" in reply


def test_sanitize_reply_for_user_removes_forced_choice_closure_outside_plan_chain():
    reply = _sanitize_reply_for_user(
        "计算机更适合互联网软件岗。\n\n"
        "最后问你一句：你是更想稳稳进大厂写代码，还是对芯片、智能硬件也有兴趣？"
        "这决定你选哪个方向。"
    )

    assert "计算机更适合互联网软件岗" in reply
    assert "你是更想稳稳进大厂写代码" in reply
    assert "你选哪个" not in reply


def test_sanitize_reply_for_user_removes_system_subject_in_review_copy():
    reply = _sanitize_reply_for_user(
        "系统目前没法直接帮你“一键替换”，因为替换后专业组结构会变。"
        "目前系统暂时补不进更合适的兜底专业，所以需要你手动权衡。"
    )

    for term in ("系统目前", "系统暂时", "没法直接帮你", "一键替换", "补不进"):
        assert term not in reply
    assert "需要你先取舍后再处理" in reply
    assert "当前还缺少更合适的兜底专业" in reply


def test_normalize_user_facing_terms_softens_hard_requirement_replacement_in_policy_copy():
    reply = _normalize_user_facing_terms(
        "中外合作除了贵，还对英语能力有硬要求。如果英语不错可以保留。"
    )

    assert "硬要求" not in reply
    assert "必须满足或必须避开" not in reply
    assert "对英语能力有明确要求" in reply


def test_sanitize_reply_for_user_removes_last_review_repair_jargon():
    reply = _sanitize_reply_for_user(
        "我整理出的修复预览显示，系统提示可选志愿中缺少能补入的兜底专业，"
        "这不是技术 bug。系统可以一键按录取率重新排序，你确认后就能自动执行。"
        "其他的需要你给句准话，巧妇难为无米之炊。"
    )

    forbidden_terms = (
        "修复预览",
        "系统提示",
        "技术 bug",
        "系统可以一键",
        "自动执行",
        "给句准话",
        "巧妇难为无米之炊",
    )
    for term in forbidden_terms:
        assert term not in reply
    assert "调整预览" in reply
    assert "当前提示" in reply
    assert "方案本身出错" in reply
    assert "确认后再执行" in reply
    assert "明确取舍范围" in reply
    assert "当前可选志愿范围不够" in reply


def test_sanitize_reply_for_user_removes_system_subject_from_tradeoff_guidance():
    reply = _sanitize_reply_for_user(
        "系统给不出直接处理，核心原因不是技术问题，而是系统需要你明确取舍范围。"
        "系统同样能替换，你给个方向，我立刻出具体方案。"
    )

    for term in ("系统给不出", "系统需要你", "系统同样能", "我立刻出", "技术问题"):
        assert term not in reply
    assert "需要你明确取舍范围" in reply
    assert "我先列出具体调整预览" in reply


def test_sanitize_reply_for_user_removes_review_proposal_titles_and_executable_copy():
    reply = _sanitize_reply_for_user(
        "系统能直接处理的是：处理录取率倒挂、处理数量校验。"
        "处理录取率梯度断层需要你先取舍。"
        "我可以先列出可执行的调整预览，确认前不会改方案。"
        "当前还缺少足够条件处理。"
        "需要你先决定取舍范围，以便生成可执行的替换方案。"
    )

    forbidden_terms = (
        "系统能直接处理",
        "处理数量校验",
        "处理录取率倒挂",
        "处理录取率梯度断层",
        "可执行的调整预览",
        "可执行的替换方案",
        "足够条件处理",
    )
    for term in forbidden_terms:
        assert term not in reply
    assert "可以先看调整预览" in reply
    assert "补足志愿数量" in reply
    assert "调整录取率顺序" in reply
    assert "补齐录取率梯度" in reply
    assert "可确认的调整预览" in reply
    assert reply.count("可确认的调整预览") >= 2
    assert "当前还缺少足够条件来处理" in reply


def test_sanitize_reply_for_user_normalizes_review_repair_issue_titles():
    reply = _sanitize_reply_for_user(
        "能直接处理的有 2 项：处理高收费、处理中外合作。"
        "处理非意向托底暂时自动不了，需要你先取舍。"
    )

    assert "高收费志愿" in reply
    assert "中外合作项目" in reply
    assert "非意向兜底专业" in reply
    for forbidden in ("处理高收费", "处理中外合作", "处理非意向托底", "能直接处理", "暂时自动不了"):
        assert forbidden not in reply


def test_sanitize_reply_for_user_keeps_unavailable_review_title_readable():
    reply = _sanitize_reply_for_user("志愿数量暂时还不能直接处理：当前方案数量多于官方要求。")

    assert "志愿数量暂时需要你先取舍或放宽条件" in reply
    assert "暂时还不可以先看调整预览" not in reply


def test_plan_timeout_fallback_does_not_leave_dangling_unavailable_title_suffix():
    reply = _build_plan_timeout_fallback_reply(
        {
            "result_kind": "review_result",
            "action_family": "review_plan",
            "summary": "已完成方案审查。",
            "facts": {
                "risk_count": 0,
                "warn_count": 1,
                "plan_total": 97,
                "target_total": 96,
                "fix_proposals": {
                    "ready_count": 0,
                    "blocked_count": 1,
                    "proposals": [
                        {
                            "status": "blocked",
                            "title": "志愿数量暂时无法自动处理",
                            "summary": "当前方案数量多于官方要求，需要你先手动精简后再重新审查。",
                            "strategy": "fill_missing_count",
                            "source_check_codes": ["count_validation"],
                        }
                    ],
                },
            },
        }
    )

    assert reply is not None
    assert "志愿数量：" in reply
    assert "志愿数量暂时：" not in reply
    assert "当前方案数量多于官方要求" in reply


def test_sanitize_reply_for_user_removes_remaining_system_subjects_in_guidance():
    reply = _sanitize_reply_for_user(
        "你当前有 3 条提醒，系统目前都没法直接处理。"
        "系统会尝试用同层次但正常收费的专业来补位。"
        "系统只能用电子商务这类非核心意向专业来垫底。"
        "系统目前没找到更合适的替代专业。"
    )

    for term in ("系统目前", "系统会尝试", "系统只能", "系统目前没找到"):
        assert term not in reply
    assert "这些提醒需要你先取舍后再处理" in reply
    assert "我会先尝试" in reply
    assert "当前只能" in reply
    assert "当前还没找到" in reply


def test_sanitize_reply_for_user_removes_final_review_guidance_jargon():
    reply = _sanitize_reply_for_user(
        "如果你选择换掉，系统需要找到同等层次志愿来替代；但这里有个技术难点，"
        "系统暂时给不出自动替换方案。这个专业组里没有其他更贴合你意向的安全垫专业可换，"
        "所以需要你先取舍后再给出自动调整方案。"
    )

    for term in ("系统需要找到", "技术难点", "系统暂时给不出", "自动替换方案", "安全垫", "自动调整方案"):
        assert term not in reply
    assert "需要先找到" in reply
    assert "需要先注意的一点" in reply
    assert "需要你先取舍后再给出替换预览" in reply
    assert "兜底专业" in reply
    assert "调整预览" in reply


def test_review_fallback_uses_user_facing_facts_instead_of_raw_summary():
    reply = _build_plan_timeout_fallback_reply(
        {
            "result_kind": "review_result",
            "summary": "已完成方案审查，风险 1 项，提醒 7 项；已返回 8 项处理建议事实。",
            "facts": {
                "risk_count": 1,
                "warn_count": 7,
                "plan_total": 45,
                "target_total": 45,
                "tier_counts": {"冲": 20, "稳": 10, "保": 15},
                "main_problems": ["冲区占比过高", "当前候选池缺少保底候选"],
                "issue_hit_plan_examples": [
                    {
                        "summary": "当前排序存在录取概率倒挂",
                        "count_text": "共命中 5 条志愿",
                        "items": ["A大学第101组-法学(冲)@2"],
                    }
                ],
                "fix_proposals": {
                    "proposals": [
                        {
                            "title": "处理录取率倒挂",
                            "status": "ready",
                            "strategy": "sort_by_probability",
                            "summary": "建议检查相邻专业组顺序",
                        },
                        {
                            "title": "录取率梯度断层暂时无法自动处理",
                            "status": "blocked",
                            "strategy": "cannot_satisfy",
                            "summary": "当前候选池里断层中间录取率候选不足",
                        },
                    ]
                },
            },
        }
    )

    assert reply is not None
    assert "方案 45/45 个志愿" in reply
    assert "可以先看调整预览的" in reply
    assert "需要你先取舍或放宽条件的" in reply
    forbidden = ("已返回", "处理建议事实", "候选池", "自动处理", "blocked", "preview_only")
    for term in forbidden:
        assert term not in reply


def test_review_fallback_focuses_target_issue_when_structured_scope_present():
    reply = _build_plan_timeout_fallback_reply(
        {
            "result_kind": "review_result",
            "summary": "已完成方案审查，风险 3 项，提醒 5 项。",
            "facts": {
                "risk_count": 3,
                "warn_count": 5,
                "plan_total": 94,
                "target_total": 96,
                "tier_counts": {"冲": 66, "稳": 28, "保": 0},
                "target_issue_codes": ["high_tuition", "cooperative_program"],
                "main_problems": ["当前方案包含高收费志愿", "当前方案包含中外合作办学项目"],
                "issue_hit_plan_examples": [
                    {
                        "code": "high_tuition",
                        "summary": "当前方案包含高收费志愿",
                        "count_text": "共命中 76 条志愿",
                        "items": [
                            "青岛理工大学-建筑学(中外合作办学)(冲)第1位",
                            "青海民族大学-土地资源管理(中外合作办学)(冲)第2位",
                        ],
                    }
                ],
                "fix_proposals": {
                    "blocked_count": 1,
                    "proposals": [
                        {
                            "status": "blocked",
                            "title": "处理高收费",
                            "strategy": "replace_risk_items",
                            "summary": "建议结合家庭经济状况确认是否保留相关志愿",
                            "source_check_codes": ["high_tuition", "cooperative_program"],
                        },
                    ],
                },
            },
        }
    )

    assert reply is not None
    assert "高收费" in reply
    assert "中外合作" in reply
    assert "共命中 76 条志愿" in reply
    assert "青岛理工大学" in reply
    assert "确认前不会改动当前方案" in reply
    assert "冲稳保 冲66" not in reply
    assert "录取率倒挂" not in reply


def test_review_fallback_shortens_long_issue_examples():
    reply = _build_plan_timeout_fallback_reply(
        {
            "result_kind": "review_result",
            "summary": "已完成方案审查。",
            "facts": {
                "plan_total": 45,
                "target_total": 45,
                "issue_hit_plan_examples": [
                    {
                        "summary": "当前方案包含中外合作办学项目",
                        "count_text": "共命中 10 条志愿",
                        "items": [
                            "东北财经大学第202组(中外合作办学或国际项目)-工商管理(中外合作办学)(与英国萨里大学合作办学；要求考生高考外语成绩不低于105分，录取后首年强化英语学习，升入大二时要求学生英文水平必须能够适应全英文授课环境，非英语语种考生请谨慎报考)(冲)第18位"
                        ],
                    }
                ],
            },
        }
    )

    assert reply is not None
    assert "要求考生高考外语成绩不低于105分" not in reply
    assert "首年强化英语学习" not in reply
    assert "东北财经大学第202组-工商管理" in reply


def test_non_actionable_review_error_does_not_use_adjustment_preview_boundary():
    reply = _build_plan_timeout_fallback_reply(
        {
            "action_family": "review_plan",
            "result_kind": "error",
            "summary": "审查超时，请稍后重试。",
            "reply_focus": ["missing_inputs"],
        },
        user_prompt="孩子最后可能涨一点，方案要不要留冲的空间",
    )

    assert reply is not None
    assert "方案审查结果" in reply
    assert "当前方案不会因为这次回复发生变化" in reply
    assert "调整预览" not in reply
    assert "重新审查" in reply


def test_review_fallback_answers_unavailable_guidance_prompt():
    reply = _build_plan_timeout_fallback_reply(
        {
            "result_kind": "review_result",
            "summary": "已完成方案审查。",
            "facts": {
                "fix_proposals": {
                    "blocked_count": 3,
                    "proposals": [
                        {
                            "status": "blocked",
                            "title": "处理高收费",
                            "summary": "建议结合家庭经济状况确认是否保留相关志愿",
                            "strategy": "replace_risk_items",
                            "blocking_reason": "替换预览会改变专业组数量，需要你先取舍后再处理",
                        },
                        {
                            "status": "blocked",
                            "title": "处理中外合作",
                            "summary": "若不接受中外合作办学，可将相关志愿移出方案",
                            "strategy": "replace_risk_items",
                            "blocking_reason": "替换预览会改变专业组数量，需要你先取舍后再处理",
                        },
                        {
                            "status": "blocked",
                            "title": "处理非意向托底",
                            "summary": "这些专业组暂时没有可补入的兜底专业",
                            "strategy": "adjust_major_group_inner_safety",
                            "blocking_reason": "当前候选里缺少更合适的兜底专业",
                        },
                    ],
                },
            },
        },
        user_prompt="那些现在处理不了的提醒，别给我系统话，告诉我为什么处理不了以及我该怎么调",
    )

    assert reply is not None
    assert "为什么现在不直接改" in reply
    assert "你可以怎么调" in reply
    assert "先确认高收费项目" in reply
    assert "先确认中外合作项目" in reply
    assert "更看重学校层次还是专业匹配" in reply
    assert "专业组数量" not in reply
    assert "暂不允许" not in reply
    assert "系统" not in reply
    assert "方案 0/0" not in reply


def test_sanitize_reply_for_user_does_not_duplicate_confirmation_boundary():
    reply = _sanitize_reply_for_user(
        "可以调整当前方案。\n\n"
        "如果要正式更新想法、报考条件或方案，我会先列出要采用的内容或调整预览；采纳/确认前不会生效。"
    )

    assert reply.count("采纳/确认前不会生效") == 1


def test_sanitize_reply_for_user_collapses_repeated_sentence_punctuation():
    reply = _sanitize_reply_for_user(
        "已按你的要求列出调整预览。。确认前不会改动当前方案。。\n"
        "这轮可以先看替换范围!!"
    )

    assert "。。" not in reply
    assert "!!" not in reply
    assert "已按你的要求列出调整预览。确认前不会改动当前方案。" in reply
    assert "这轮可以先看替换范围!" in reply


class _FakeAgent:
    def __init__(self, replies: list[str | WSResponse]):
        self.calls: list[dict] = []
        self._replies = replies

    async def run_with_message_deltas(self, user_prompt, message_history=None, deps=None, on_progress=None):
        if deps is not None:
            deps.agent_observability.update(
                {
                    "completed": True,
                    "firstToolCallAtMs": None,
                    "nodeTimings": [
                        {
                            "index": 1,
                            "node": "ModelRequestNode",
                            "durationMs": 12,
                            "status": "success",
                        }
                    ],
                }
            )
        self.calls.append(
            {
                "user_prompt": user_prompt,
                "message_history": message_history,
                "chat_history": deps.chat_history if deps else None,
                "planning_summary": deps.planning_summary if deps else None,
                "pending_confirmation": (
                    deps.conversation_phase.pending if deps and deps.conversation_phase else None
                ),
                "allow_explore_inner_llm": deps.allow_explore_inner_llm if deps else None,
                "recent_intent_analysis": deps.recent_intent_analysis if deps else None,
                "stale_pending_notice": deps.stale_pending_notice if deps else None,
            }
        )
        reply = self._replies[len(self.calls) - 1]
        text_reply = reply.content if isinstance(reply, WSResponse) else reply
        new_messages = [
            ModelRequest(parts=[UserPromptPart(content=user_prompt)]),
            ModelResponse(parts=[TextPart(content=text_reply)], model_name="test-model"),
        ]
        all_messages = (message_history or []) + new_messages
        usage = MagicMock(
            input_tokens=1,
            output_tokens=1,
            total_tokens=2,
            requests=1,
            tool_calls=0,
        )
        return reply, new_messages, all_messages, usage


class _FakeIntentPreviewAgent:
    def __init__(self, payload: dict, tool_name: str = "preview_intent_change"):
        self.payload = payload
        self.tool_name = tool_name
        self.calls: list[dict] = []

    async def run_with_message_deltas(self, user_prompt, message_history=None, deps=None, on_progress=None):
        if deps is not None:
            deps.agent_observability.update(
                {
                    "completed": True,
                    "nodeTimings": [
                        {
                            "index": 1,
                            "node": "ModelRequestNode",
                            "durationMs": 12,
                            "status": "success",
                        },
                        {
                            "index": 2,
                            "node": "CallToolsNode",
                            "durationMs": 8,
                            "status": "success",
                            "toolNames": [self.tool_name],
                        },
                    ],
                }
            )
        self.calls.append({"user_prompt": user_prompt, "message_history": message_history})
        content = json.dumps(self.payload, ensure_ascii=False)
        new_messages = [
            ModelRequest(parts=[UserPromptPart(content=user_prompt)]),
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name=self.tool_name,
                        args={},
                        tool_call_id="intent-preview-1",
                    )
                ]
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name=self.tool_name,
                        content=content,
                        tool_call_id="intent-preview-1",
                    )
                ]
            ),
            ModelResponse(parts=[TextPart(content=content)], model_name="direct-tool-result"),
        ]
        all_messages = (message_history or []) + new_messages
        usage = MagicMock(
            input_tokens=1,
            output_tokens=1,
            total_tokens=2,
            requests=1,
            tool_calls=1,
        )
        return content, new_messages, all_messages, usage


def _assert_pending_card_envelope(
    reply,
    expected_primary: str,
    action_family: str | None = None,
    *,
    kind: str = "plan_mutation",
):
    assert isinstance(reply, ChatServiceResponseEnvelope)
    if expected_primary == "":
        if kind == "plan_mutation":
            assert reply.primary == "" or "确认前不会改动当前方案" in reply.primary
        else:
            assert reply.primary
    else:
        assert reply.primary == expected_primary
    cards = [item for item in reply.followups if item.type == "pendingConfirmationCard"]
    assert len(cards) == 1
    payload = json.loads(cards[0].content)
    assert payload["type"] == "pendingConfirmationCard"
    assert payload["kind"] == kind
    if action_family:
        assert payload["actionFamily"] == action_family
    assert payload["pendingId"]
    assert payload["clickable"] is True
    return payload


def _reply_primary(reply) -> str:
    return reply.primary if isinstance(reply, ChatServiceResponseEnvelope) else str(reply)


def _pending_card_payloads(reply) -> list[dict]:
    followups = reply.followups if isinstance(reply, ChatServiceResponseEnvelope) else []
    return [json.loads(item.content) for item in followups if item.type == "pendingConfirmationCard"]


def _assert_no_pending_cards(reply) -> None:
    assert _pending_card_payloads(reply) == []


def _route_observability_events(messages) -> list[dict]:
    events: list[dict] = []
    for message in messages or []:
        for part in getattr(message, "parts", []) or []:
            if not isinstance(part, TextPart):
                continue
            try:
                data = json.loads(part.content)
            except Exception:
                continue
            if isinstance(data, dict) and data.get("type") == "routeObservability":
                events.append(data)
    return events


def _pending_confirmation_store(initial: dict | None = None):
    state: dict[str, dict] = {}
    if initial is not None:
        state["value"] = dict(initial)

    async def save(_session_id, data_value):
        state["value"] = dict(data_value)
        return {"code": 0, "data": {"pendingConfirmation": state["value"]}}

    async def get(_session_id):
        return {"code": 0, "data": {"pendingConfirmation": state.get("value")}}

    return state, AsyncMock(side_effect=save), AsyncMock(side_effect=get)


def _planning_workspace_after_apply_response(
    *,
    ordered_total: int = 27,
    target_total: int = 30,
    chong: int = 8,
    wen: int = 12,
    bao: int = 7,
    risk_count: int = 1,
    warn_count: int = 2,
    risk_summary: str = "保底志愿略少，建议补充稳保梯度。",
) -> dict:
    return {
        "code": 0,
        "data": {
            "phase": "ordered",
            "version": 18,
            "orderedPlanState": {
                "summary": {
                    "unitTotal": ordered_total,
                    "targetUnitCount": target_total,
                    "unitTierCounts": {
                        "冲": chong,
                        "稳": wen,
                        "保": bao,
                    },
                },
                "items": [{"schoolName": "浙江工业大学"}],
            },
            "reviewState": {
                "summary": {
                    "riskCount": risk_count,
                    "warnCount": warn_count,
                },
                "checks": [
                    {
                        "passed": False,
                        "summary": risk_summary,
                    }
                ],
            },
        },
    }


def _planning_state_response(version: int = 12) -> dict:
    return {"code": 0, "data": {"version": version}}


def _user_goal_fix_proposal_response(
    *,
    proposal_id: str = "ug-ready-1",
    strategy: str = "exclude_scope",
    source_version: int = 12,
    title: str = "处理这条报考条件",
    summary: str = "当前方案中有需要同步调整的志愿。",
    action_summaries: list[str] | None = None,
) -> dict:
    return {
        "code": 0,
        "data": {
            "proposalSource": "user_goal",
            "sourceVersionGuard": source_version,
            "proposals": [
                {
                    "proposalId": proposal_id,
                    "proposalSource": "user_goal",
                    "sourceVersion": source_version,
                    "sourceVersionGuard": source_version,
                    "strategy": strategy,
                    "status": "ready",
                    "title": title,
                    "summary": summary,
                    "impact": "确认后会同步调整当前方案。",
                    "actionSummaries": action_summaries or ["调整当前方案"],
                    "requiresConfirmation": True,
                    "actions": [{"actionType": "remove_volunteers", "removeVolunteerIds": ["v-1"]}],
                    "dryRunResult": {"status": "ready"},
                }
            ],
        },
    }


class _CancellingAgent:
    async def run_with_message_deltas(self, user_prompt, message_history=None, deps=None, on_progress=None):
        deps.agent_observability.update(
            {
                "completed": False,
                "failedNode": "ModelRequestNode",
                "failedNodeElapsedMs": 180000,
                "nodeTimings": [
                    {
                        "index": 1,
                        "node": "ModelRequestNode",
                        "durationMs": 180000,
                        "status": "interrupted",
                    }
                ],
            }
        )
        raise asyncio.CancelledError()


class _InterruptedAgent:
    async def run_with_message_deltas(self, user_prompt, message_history=None, deps=None, on_progress=None):
        deps.agent_observability.update(
            {
                "completed": False,
                "failedNode": "ModelRequestNode",
                "failedNodeIndex": 2,
                "failedNodeElapsedMs": 27000,
                "errorType": "ModelAPIError",
                "nodeTimings": [
                    {
                        "index": 1,
                        "node": "UserPromptNode",
                        "durationMs": 0,
                        "status": "success",
                    },
                    {
                        "index": 2,
                        "node": "ModelRequestNode",
                        "durationMs": 27000,
                        "status": "interrupted",
                    },
                ],
            }
        )
        raise RuntimeError("model api interrupted")


class _InterruptedReadonlyToolAgent:
    async def run_with_message_deltas(self, user_prompt, message_history=None, deps=None, on_progress=None):
        deps.agent_observability.update(
            {
                "completed": False,
                "failedNode": "ModelRequestNode",
                "failedNodeIndex": 4,
                "failedNodeElapsedMs": 52000,
                "firstToolNames": ["compare_entities"],
                "toolNameCounts": {"compare_entities": 1},
                "errorType": "ModelAPIError",
                "nodeTimings": [
                    {
                        "index": 1,
                        "node": "UserPromptNode",
                        "durationMs": 0,
                        "status": "success",
                    },
                    {
                        "index": 2,
                        "node": "ModelRequestNode",
                        "durationMs": 1200,
                        "status": "success",
                    },
                    {
                        "index": 3,
                        "node": "CallToolsNode",
                        "durationMs": 20,
                        "status": "success",
                        "toolNames": ["compare_entities"],
                    },
                    {
                        "index": 4,
                        "node": "ModelRequestNode",
                        "durationMs": 52000,
                        "status": "interrupted",
                    },
                ],
            }
        )
        raise RuntimeError("model api interrupted")


class _InterruptedIntentPreviewToolAgent:
    def __init__(self, payload: dict):
        self.payload = payload

    async def run_with_message_deltas(self, user_prompt, message_history=None, deps=None, on_progress=None):
        deps.agent_observability.update(
            {
                "completed": False,
                "failedNode": "ModelRequestNode",
                "failedNodeIndex": 4,
                "failedNodeElapsedMs": 99000,
                "firstToolNames": ["preview_intent_change", "preview_plan_action"],
                "toolNameCounts": {
                    "preview_intent_change": 1,
                    "preview_plan_action": 1,
                },
                "latestIntentPreviewPayload": self.payload,
                "errorType": "ModelAPIError",
                "nodeTimings": [
                    {"index": 1, "node": "UserPromptNode", "durationMs": 0, "status": "success"},
                    {"index": 2, "node": "ModelRequestNode", "durationMs": 1000, "status": "success"},
                    {
                        "index": 3,
                        "node": "CallToolsNode",
                        "durationMs": 40,
                        "status": "success",
                        "toolNames": ["preview_intent_change", "preview_plan_action"],
                    },
                    {"index": 4, "node": "ModelRequestNode", "durationMs": 99000, "status": "interrupted"},
                ],
            }
        )
        raise RuntimeError("model api interrupted")


class _InterruptedRegionReadonlyToolAgent:
    async def run_with_message_deltas(self, user_prompt, message_history=None, deps=None, on_progress=None):
        deps.agent_observability.update(
            {
                "completed": False,
                "failedNode": "ModelRequestNode",
                "failedNodeIndex": 4,
                "failedNodeElapsedMs": 3000,
                "firstToolNames": ["explore_topic"],
                "toolNameCounts": {"explore_topic": 1},
                "errorType": "ModelAPIError",
                "nodeTimings": [
                    {
                        "index": 1,
                        "node": "UserPromptNode",
                        "durationMs": 0,
                        "status": "success",
                    },
                    {
                        "index": 2,
                        "node": "ModelRequestNode",
                        "durationMs": 1200,
                        "status": "success",
                    },
                    {
                        "index": 3,
                        "node": "CallToolsNode",
                        "durationMs": 20,
                        "status": "success",
                        "toolNames": ["explore_topic"],
                    },
                    {
                        "index": 4,
                        "node": "ModelRequestNode",
                        "durationMs": 3000,
                        "status": "interrupted",
                    },
                ],
            }
        )
        raise RuntimeError("model api interrupted")


class _BuggyAgent:
    async def run_with_message_deltas(self, user_prompt, message_history=None, deps=None, on_progress=None):
        raise RuntimeError("plain bug")


@pytest.fixture
def mock_llm_client():
    client = MagicMock()
    client.model = MagicMock()
    client.model_settings = {}
    return client


def test_build_runtime_history_trims_long_history_and_compacts_tool_returns():
    long_tool_content = json.dumps(
        {
            "result_kind": "preview_only",
            "action_family": "remove_units",
            "summary": "预览删除 2 条志愿",
            "items": ["x" * 5000],
        },
        ensure_ascii=False,
    )
    history = []
    for index in range(20):
        history.extend(
            [
                ModelRequest(parts=[UserPromptPart(content=f"旧问题 {index}")]),
                ModelResponse(parts=[TextPart(content=f"旧回答 {index}")], model_name="test"),
            ]
        )
    history.extend(
        [
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="preview_plan_action",
                        args={"action": "remove", "filters": {}},
                        tool_call_id="tool-long",
                    )
                ],
                model_name="test",
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="preview_plan_action",
                        content=long_tool_content,
                        tool_call_id="tool-long",
                    )
                ]
            ),
            ModelResponse(parts=[TextPart(content="最近回答")], model_name="test"),
        ]
    )
    config = MagicMock(runtime_max_messages=6, runtime_drop_tool_returns_over_chars=200)

    runtime = build_runtime_history(
        history,
        latest_user_content="现在方案怎么样",
        config=config,
    )

    assert runtime.full_len == len(history)
    assert runtime.runtime_len == 6
    assert runtime.model_history is not None
    assert len(runtime.model_history) == 6
    assert runtime.dropped_tool_return_count == 1
    assert runtime.runtime_text_chars < runtime.full_text_chars
    assert runtime.chat_history[-1] == {"role": "user", "content": "现在方案怎么样"}
    assert any(item["content"] == "最近回答" for item in runtime.chat_history)
    tool_returns = [
        part
        for message in runtime.model_history
        for part in getattr(message, "parts", [])
        if isinstance(part, ToolReturnPart)
    ]
    assert tool_returns
    assert "items" not in tool_returns[0].content
    assert "预览删除 2 条志愿" in tool_returns[0].content


def test_build_runtime_history_compacts_preview_intent_change_returns_even_when_short():
    payload = {
        "status": "existing_only",
        "sessionId": "session-intent-runtime-compact",
        "existingItems": [
            {"content": "当前已有参考偏好具体专业：会计学", "value": {"major_intents": {"level3": ["会计学"]}}},
        ],
        "impactText": "候选里还有一些机会。",
        "impactAnalysis": {
            "currentPlanFit": ["当前方案里有广州理工学院-会计学。"],
            "candidateOpportunity": ["候选里还有 210 个。"],
        },
        "message": "这个想法当前已经在后续报考参考里。",
    }
    history = [
        ModelRequest(parts=[UserPromptPart(content="我倾向会计学")]),
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="preview_intent_change",
                    args={},
                    tool_call_id="intent-preview",
                )
            ],
            model_name="test",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="preview_intent_change",
                    content=json.dumps(payload, ensure_ascii=False),
                    tool_call_id="intent-preview",
                )
            ]
        ),
        ModelResponse(parts=[TextPart(content="这个想法当前已经在后续报考参考里。")], model_name="test"),
    ]

    config = HistoryConfig()
    config.runtime_max_messages = 10
    config.runtime_drop_tool_returns_over_chars = 3000
    runtime = build_runtime_history(
        history,
        latest_user_content="看看这个偏好会影响当前方案吗",
        config=config,
    )

    assert runtime.dropped_tool_return_count == 1
    tool_returns = [
        part
        for message in runtime.model_history or []
        for part in getattr(message, "parts", [])
        if isinstance(part, ToolReturnPart)
    ]
    assert tool_returns
    assert "这个想法当前已经在后续报考参考里" in tool_returns[0].content
    assert "impactAnalysis" not in tool_returns[0].content
    assert "候选里还有 210 个" not in tool_returns[0].content


def test_build_runtime_history_keeps_pending_turn_outside_recent_window():
    history = []
    for index in range(12):
        history.extend(
            [
                ModelRequest(parts=[UserPromptPart(content=f"旧问题 {index}")]),
                ModelResponse(parts=[TextPart(content=f"旧回答 {index}")], model_name="test"),
            ]
        )

    history.extend(
        [
            ModelRequest(parts=[UserPromptPart(content="按院校层次排序")]),
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="preview_plan_action",
                        args={
                            "action": "sort",
                            "sort_by": "school_level",
                        },
                        tool_call_id="pending-sort-call",
                    )
                ],
                model_name="test",
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="preview_plan_action",
                        content=json.dumps(
                            {
                                "applied": False,
                                "action_family": "sort_ordered_plan",
                                "result_kind": "preview_only",
                                "summary": "将按院校层次重新排序。",
                            },
                            ensure_ascii=False,
                        ),
                        tool_call_id="pending-sort-call",
                    )
                ]
            ),
            ModelResponse(parts=[TextPart(content="确认后我再执行排序。")], model_name="test"),
        ]
    )
    for index in range(6):
        history.append(ModelResponse(parts=[TextPart(content=f"本轮补充说明 {index}")], model_name="test"))

    config = MagicMock(runtime_max_messages=3, runtime_keep_pending=True, runtime_drop_tool_returns_over_chars=3000)
    runtime = build_runtime_history(
        history,
        latest_user_content="这个排序会怎么影响冲稳保？",
        has_active_pending=True,
        config=config,
    )

    assert runtime.has_pending is True
    assert runtime.runtime_len > config.runtime_max_messages
    assert any(
        isinstance(part, ToolCallPart)
        and part.tool_name == "preview_plan_action"
        and part.tool_call_id == "pending-sort-call"
        for message in runtime.model_history or []
        for part in getattr(message, "parts", [])
    )
    assert any(
        isinstance(part, ToolReturnPart)
        and part.tool_name == "preview_plan_action"
        and part.tool_call_id == "pending-sort-call"
        for message in runtime.model_history or []
        for part in getattr(message, "parts", [])
    )
    assert runtime.chat_history[-1] == {"role": "user", "content": "这个排序会怎么影响冲稳保？"}


def test_build_runtime_history_filters_route_observability_messages():
    history = [
        ModelRequest(parts=[UserPromptPart(content="你好")]),
        ModelResponse(
            parts=[
                TextPart(
                    content=json.dumps(
                        {
                            "type": "routeObservability",
                            "event": "conversation_turn_event",
                            "routingPath": "zhiyuan_agent_direct",
                        },
                        ensure_ascii=False,
                    )
                )
            ],
            model_name="route-observability",
        ),
        ModelResponse(parts=[TextPart(content="你好，有什么想了解的？")], model_name="test"),
    ]

    runtime = build_runtime_history(
        history,
        latest_user_content="继续",
        config=HistoryConfig(runtime_max_messages=10),
    )

    assert runtime.full_len == 2
    assert runtime.runtime_len == 2
    assert all(
        getattr(message, "model_name", "") != "route-observability"
        for message in runtime.model_history or []
    )
    assert runtime.chat_history == [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好，有什么想了解的？"},
        {"role": "user", "content": "继续"},
    ]


def test_extract_recent_intent_analysis_payload_prefers_latest_structured_preview():
    first_payload = {
        "status": "ready",
        "sessionId": "s1",
        "items": [{"content": "偏好法学", "value": {"major_intents": {"level3": ["法学"]}}}],
    }
    latest_payload = {
        "status": "existing_only",
        "sessionId": "s1",
        "existingItems": [
            {"content": "当前已有参考偏好具体专业：会计学", "value": {"major_intents": {"level3": ["会计学"]}}},
        ],
    }
    history = [
        ModelRequest(parts=[UserPromptPart(content="想学法学")]),
        ModelResponse(parts=[ToolCallPart(tool_name="preview_intent_change", args={}, tool_call_id="intent-1")]),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="preview_intent_change",
                    content=json.dumps(first_payload, ensure_ascii=False),
                    tool_call_id="intent-1",
                )
            ]
        ),
        ModelRequest(parts=[UserPromptPart(content="会计也行")]),
        ModelResponse(parts=[ToolCallPart(tool_name="preview_intent_change", args={}, tool_call_id="intent-2")]),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="preview_intent_change",
                    content=json.dumps(latest_payload, ensure_ascii=False),
                    tool_call_id="intent-2",
                )
            ]
        ),
    ]

    assert _extract_recent_intent_analysis_payload(history) == latest_payload


class _FakeAgentWithToolCalls:
    def __init__(
        self,
        reply: str,
        tool_parts: list[ToolCallPart],
        tool_return_parts: list[ToolReturnPart] | None = None,
        observability: dict | None = None,
    ):
        self.calls: list[dict] = []
        self._reply = reply
        self._tool_parts = tool_parts
        self._tool_return_parts = tool_return_parts or []
        self._observability = observability or {}

    async def run_with_message_deltas(self, user_prompt, message_history=None, deps=None, on_progress=None):
        self.calls.append({"user_prompt": user_prompt})
        if deps is not None and self._observability:
            deps.agent_observability.update(self._observability)
        new_messages = [
            ModelRequest(parts=[UserPromptPart(content=user_prompt)]),
            ModelResponse(parts=self._tool_parts, model_name="test-model"),
        ]
        if self._tool_return_parts:
            new_messages.append(ModelRequest(parts=self._tool_return_parts))
        new_messages.append(ModelResponse(parts=[TextPart(content=self._reply)], model_name="test-model"))
        all_messages = (message_history or []) + new_messages
        usage = MagicMock(
            input_tokens=1,
            output_tokens=1,
            total_tokens=2,
            requests=1,
            tool_calls=len(self._tool_parts),
        )
        return self._reply, new_messages, all_messages, usage


class _FakeAgentWithMessageSequence:
    def __init__(self, message_batches: list[tuple[str, list]]):
        self.calls: list[dict] = []
        self._message_batches = message_batches

    async def run_with_message_deltas(self, user_prompt, message_history=None, deps=None, on_progress=None):
        self.calls.append({
            "user_prompt": user_prompt,
            "pending_confirmation": (
                deps.conversation_phase.pending if deps and deps.conversation_phase else None
            ),
        })
        reply, extra_messages = self._message_batches[len(self.calls) - 1]
        new_messages = [ModelRequest(parts=[UserPromptPart(content=user_prompt)])]
        new_messages.extend(extra_messages)
        new_messages.append(ModelResponse(parts=[TextPart(content=reply)], model_name="test-model"))
        all_messages = (message_history or []) + new_messages
        usage = MagicMock(
            input_tokens=1,
            output_tokens=1,
            total_tokens=2,
            requests=1,
            tool_calls=sum(
                1
                for message in extra_messages
                for part in getattr(message, "parts", [])
                if isinstance(part, ToolCallPart)
            ),
        )
        return reply, new_messages, all_messages, usage


class _FakeSlowAgent:
    def __init__(self, reply: str, *, delay_seconds: float, emit_tool_progress: bool = False):
        self.reply = reply
        self.delay_seconds = delay_seconds
        self.emit_tool_progress = emit_tool_progress

    async def run_with_message_deltas(self, user_prompt, message_history=None, deps=None, on_progress=None):
        if self.emit_tool_progress and on_progress is not None:
            await on_progress("正在对比这几个专业的差异...")
        await asyncio.sleep(self.delay_seconds)
        new_messages = [
            ModelRequest(parts=[UserPromptPart(content=user_prompt)]),
            ModelResponse(parts=[TextPart(content=self.reply)], model_name="test-model"),
        ]
        usage = MagicMock(
            input_tokens=1,
            output_tokens=1,
            total_tokens=2,
            requests=1,
            tool_calls=0,
        )
        return self.reply, new_messages, (message_history or []) + new_messages, usage


def test_chat_service_default_long_progress_hints_use_user_language():
    all_hints = [
        ChatService._EARLY_CONTEXT_PROGRESS_HINT,
        ChatService._INITIAL_PROGRESS_HINT,
        *[hint for _, hint in ChatService._LONG_PROGRESS_MODEL_WAIT_HINTS],
        *[hint for _, hint in ChatService._LONG_PROGRESS_TOOL_HINTS],
    ]

    forbidden_terms = ("工具结果", "模型", "action", "payload", "stage", "volunteerId")
    for hint in all_hints:
        for term in forbidden_terms:
            assert term not in hint


def test_sanitize_reply_for_user_replaces_unnecessary_english_mixed_words():
    reply = _sanitize_reply_for_user(
        '相当于你 mostly 在"赌一把"，baseline 可以先按本科看，门槛 increasingly 提高。'
    )

    assert "mostly" not in reply
    assert "baseline" not in reply
    assert "increasingly" not in reply
    assert '基本上在"赌一把"' in reply
    assert "基准可以先按本科看" in reply
    assert "门槛越来越提高" in reply


def test_sanitize_reply_for_user_normalizes_intent_candidate_pool_semantics():
    reply = _sanitize_reply_for_user(
        "如果确认排除，后续推荐和方案检查会把这类专业整体作为排除参考，不再进入候选。\n"
        "医学门类整体避开后，你的候选池会大幅收窄。\n"
        "如果你确认要把“排除医学/护理，倾向财会”作为后续参考，我可以整理成待采纳内容。"
        "确认后，后续推荐和方案调整就会按这个口径来。"
        "确认后才会生效。要不要先确认这些方向？"
    )

    assert "不再进入候选" not in reply
    assert "候选池会大幅收窄" not in reply
    assert "确认后，后续" not in reply
    assert "确认后才会生效" not in reply
    assert "采纳后，后续推荐" in reply
    assert "采纳后才会生效" in reply
    assert "要不要我先列出来让你采纳" in reply
    assert "基础可选范围" in reply


def test_sanitize_reply_for_user_does_not_turn_readonly_comparison_into_plan_preview():
    reply = _sanitize_reply_for_user(
        "我可以直接帮你对比分析这两个专业的差异，重点看就业、学习内容和适配度。"
    )

    assert "调整预览" not in reply
    assert "对比分析" in reply
    assert "我可以帮你对比分析" in reply


def test_unbacked_plan_confirmation_guard_blocks_toolless_fake_confirm_copy():
    reply = (
        "已在当前方案里定位到**“汉语言文学”相关的 17 条志愿**。\n\n"
        "**确认后会执行以下操作：**\n"
        "1. 将上述 17 条汉语言文学志愿从当前方案中移除\n"
        "2. 把“排除汉语言文学”写入后续报考参考\n\n"
        "点击确认后生效，你确认要删除吗？"
    )

    guarded = _guard_unbacked_plan_confirmation_reply(reply)

    assert "汉语言文学" in guarded
    assert "点击确认后生效" not in guarded
    assert "你确认要删除吗" not in guarded
    assert "确认后会执行" not in guarded
    assert "还没有生成可确认的调整预览" in guarded
    assert "确认当前有效预览后才会执行" in guarded


def test_plan_status_timeout_fallback_uses_structured_user_copy():
    reply = _build_plan_timeout_fallback_reply(
        {
            "result_kind": "status_overview",
            "summary": "已填满 45 个志愿；方案前几个志愿：北京财经学院第01组-财政学(冲)@1。",
            "facts": {
                "current_total": 45,
                "target_total": 45,
                "tier_counts": {"冲": 18, "稳": 13, "保": 14},
                "risk_count": 0,
                "warn_count": 0,
                "top_items": [
                    "北京财经学院第01组-财政学(冲)@1",
                    "天津财经大学第02组-经济学(稳)@2",
                    "河北经贸大学第03组-法学(保)@3",
                    "第四个不应展示(保)@4",
                ],
                "intent_relation": {
                    "coverage": "承接情况：当前方案里较贴近的有27个，明显冲突的有0个。",
                    "aligned_examples": "贴近偏好：北京财经学院第01组-财政学(冲)@1（匹配偏好专业:财政学类）",
                },
            },
        }
    )

    assert reply is not None
    assert "我看了当前方案，核心情况如下" in reply
    assert "- 完整度：45/45 个志愿。" in reply
    assert "- 冲稳保：冲18 / 稳13 / 保14。" in reply
    assert "- 审查：暂时没有明显风险。" in reply
    assert "北京财经学院第01组-财政学(冲)第1位" in reply
    assert "第四个不应展示" not in reply
    assert "@1" not in reply
    assert "方案前几个志愿" not in reply


def test_plan_timeout_fallback_does_not_expose_internal_hints():
    reply = _build_plan_timeout_fallback_reply(
        {
            "result_kind": "status_overview",
            "action_family": "query_state",
            "summary": "当前方案 45/45。",
            "next_step_hints": ["[LLM_INTERNAL] 如果用户关心数量是否够用，先解释缺口。"],
        }
    )

    assert reply is not None
    assert "[LLM_INTERNAL]" not in reply
    assert "如果用户关心" not in reply


def test_sanitize_reply_removes_legacy_candidate_filter_count_after_intent_apply():
    reply = _sanitize_reply_for_user(
        "已确认，这条要求会作为后续报考参考。\n"
        "- 本次确认内容：排除专业：经济与金融。\n"
        "- 后续使用：按这条要求过滤后，候选大约还有 1363 个，整体候选大约是 1439 个。\n"
        "- 下一步：可以继续查看方案。"
    )

    assert "候选大约" not in reply
    assert "整体候选" not in reply
    assert "本次确认内容：排除专业：经济与金融" in reply
    assert "下一步：可以继续查看方案" in reply


def test_normalize_user_facing_terms_removes_draft_label():
    reply = _normalize_user_facing_terms("这版方案更像是一份广撒网的草稿，冒险成分比较高。")

    assert "草稿" not in reply
    assert "方案" in reply


def test_normalize_plan_reply_style_keeps_markdown_and_removes_severe_pressure():
    reply = (
        "**审查结论**\n\n"
        "- 30个志愿已填满\n"
        "- **专业完全偏离** — 全是财会类\n"
        "- 排序有问题\n\n"
        "**你现在必须决定：**\n"
        "A. 就用这版\n"
        "B. 重新生成\n"
        "选哪个？"
    )

    normalized = _normalize_plan_reply_style(reply)

    assert "**审查结论**" in normalized
    assert "- 30个志愿已填满" in normalized
    assert "你现在必须决定" not in normalized
    assert "选哪个" not in normalized
    assert "A. 就用这版" in normalized


def test_normalize_plan_reply_style_removes_inline_severe_pressure():
    reply = "重排已经完成。现在必须做最终选择。 A. 接受这版。你选A还是B？\n你现在必须做出选择。"

    normalized = _normalize_plan_reply_style(reply)

    assert "选A还是B" in normalized
    assert "必须做出选择" not in normalized


def test_normalize_plan_reply_style_removes_reply_ab_prompt():
    reply = "方案已经有了。回复 A 或 B，我不再回应这些重复问题。"

    normalized = _normalize_plan_reply_style(reply)

    assert "回复 A 或 B" not in normalized
    assert "不再回应" not in normalized


def test_normalize_plan_reply_style_removes_reason_heading_and_dangling_please():
    reply = "方案已经有了。原因说明。分数与地域限制较强。\n\n请。"

    normalized = _normalize_plan_reply_style(reply)

    assert "请。" not in normalized
    assert "原因说明" in normalized


def test_normalize_plan_reply_style_removes_pressure_action_prompt():
    reply = (
        "最新审查结果：风险 3 项。\n\n"
        "不要再反复查看和审查了，直接选下一步行动：\n\n"
        "**A. 我推荐 2 个志愿，你确认加入**\n"
        "**B. 你说 2 个学校+专业，我校验后加**\n"
        "选 A、B 或 C，我立即执行。"
    )

    normalized = _normalize_plan_reply_style(reply)

    assert "最新审查结果" in normalized
    assert "不要再反复查看" not in normalized
    assert "选 A、B 或 C" not in normalized


def test_normalize_plan_reply_style_removes_major_group_front_position_expansion():
    reply = (
        "把第3个专业组移到第5位的预览如下：\n\n"
        "**当前第3个专业组：**\n"
        "- 安阳工学院第201组\n"
        "- 组内共 6 个专业\n\n"
        "**当前前5位概况：**\n"
        "1. 河北师范大学第201组 — 翻译（稳）\n"
        "2. 山东交通学院第201组 — 计算机科学与技术（稳）\n\n"
        "如果你确认要执行，回复“确认”。"
    )

    normalized = _normalize_plan_reply_style(reply)

    assert "当前第3个专业组" in normalized
    assert "组内共 6 个专业" in normalized
    assert "当前前5位概况" not in normalized
    assert "河北师范大学" not in normalized
    assert "如果你确认要执行" in normalized


def test_normalize_user_facing_terms_removes_profile_jargon():
    reply = '你是想把"网络与新媒体"作为新的专业意向加入画像，还是想先看看当前方案？'

    normalized = _normalize_user_facing_terms(reply)

    assert "画像" not in normalized
    assert "记成后续报考参考" in normalized


def test_normalize_user_facing_terms_removes_tool_jargon():
    reply = "工具识别时把工商管理类也纳入了；工具返回里还有候选结果。"

    normalized = _normalize_user_facing_terms(reply)

    assert "工具识别" not in normalized
    assert "工具返回" not in normalized
    assert "这里需要注意的是" in normalized
    assert "查询结果" in normalized


def test_normalize_user_facing_terms_uses_join_plan_wording_for_add_preview():
    reply = "**添加预览**\n执行后会将该志愿补入方案。确认要添加吗？"

    normalized = _normalize_user_facing_terms(reply)

    assert "添加预览" not in normalized
    assert "添加吗" not in normalized
    assert "加入方案预览" in normalized
    assert "确认加入方案吗" in normalized


def test_normalize_pending_intent_reply_avoids_premature_recorded_wording():
    reply = "好的，我记下了你对跨境电商的兴趣。候选库里有一个相关机会。"

    normalized = _normalize_pending_intent_reply(reply)

    assert "我记下了" not in normalized
    assert "点“采纳”" in normalized
    assert "后续参考" in normalized


def test_normalize_unbacked_recorded_wording_avoids_fake_saved_conclusion():
    reply = "好的，新媒体方向对数学要求更友好，这个判断可以先记下来。"

    normalized = _normalize_unbacked_recorded_wording(reply)

    assert "记下来" not in normalized
    assert "当前分析结论参考" in normalized


def test_normalize_unbacked_recorded_wording_avoids_fake_saved_thought():
    reply = "没问题，我先帮你把思路记下来，不会自动修改你的方案。你随时可以继续补充或调整，确认采纳前都不会生效。"

    normalized = _normalize_unbacked_recorded_wording(reply)

    assert "记下来" not in normalized
    assert "作为当前对话参考" in normalized
    assert "不会改动当前方案" in normalized
    assert "确认采纳前都不会生效" not in normalized
    assert "确认前不会执行" in normalized


def test_normalize_unbacked_recorded_wording_avoids_fake_preference_closure():
    reply = "好的，明白了。你倾向**网络与新媒体**这个方向，它对数学要求更低。"

    normalized = _normalize_unbacked_recorded_wording(reply)

    assert "你倾向" not in normalized
    assert "先按刚才的分析结论理解" in normalized
    assert "**网络与新媒体**这个方向" in normalized


def test_normalize_false_apology_reply_removes_first_turn_fake_self_correction():
    reply = "抱歉，刚才的分析没有直接回应您的问题。让我重新为您分析：\n\n## 数学不稳定怎么办"

    normalized = _normalize_false_apology_reply(reply, [])

    assert not normalized.startswith("抱歉")
    assert "数学不稳定怎么办" in normalized


def test_normalize_false_apology_reply_keeps_real_multi_turn_apology():
    history = [ModelResponse(parts=[TextPart(content="上一轮我答错了")], model_name="test")]
    reply = "抱歉，刚才的分析没有直接回应您的问题。让我重新为您分析：\n\n## 数学不稳定怎么办"

    normalized = _normalize_false_apology_reply(reply, history)

    assert normalized == reply


def test_normalize_general_confirmation_protocol_wording_requires_card_click():
    reply = "随时可以在对话里改。你直接告诉我新的想法就行，我会重新整理，不会锁定之前的偏好。"

    normalized = _normalize_general_confirmation_protocol_wording(reply)

    assert "随时可以在对话里改" not in normalized
    assert "不会锁定之前的偏好" not in normalized
    assert "不会自动改候选或方案" in normalized
    assert "点“采纳”前" in normalized


def test_normalize_general_confirmation_protocol_wording_covers_followup_change_variants():
    reply = "在我们这里，随时能改。之前填的内容都是可以根据新想法调整的，直接告诉我新的想法就行。"

    normalized = _normalize_general_confirmation_protocol_wording(reply)

    assert "随时能改" not in normalized
    assert "直接告诉我新的想法就行" not in normalized
    assert "列出来" in normalized
    assert "点“采纳”前" in normalized
    assert "不会自动改候选或方案" in normalized


def test_normalize_general_confirmation_protocol_wording_removes_auto_apply_conflicts():
    reply = (
        "在我们这里，随时能改，改完立刻生效。"
        "如果孩子现在就有新想法，直接告诉我，我立刻帮你调整方案。"
    )

    normalized = _normalize_general_confirmation_protocol_wording(reply)

    assert "改完立刻生效" not in normalized
    assert "立刻帮你调整方案" not in normalized
    assert "列出" in normalized
    assert "点“采纳”前不会改候选或方案" in normalized
    assert "点“采纳”前" in normalized


def test_normalize_general_confirmation_protocol_wording_adds_card_boundary_to_change_policy_reply():
    reply = (
        "可以的，之前设定的偏好随时可以调整。\n"
        "2. 修改后重新匹配：调整偏好后，系统会重新筛选符合条件的院校和专业\n"
        "3. 不影响已生成的方案：如果你已经生成了初步方案，修改偏好后可以重新生成或局部调整\n"
        "我可以先帮你分析调整后的影响，再决定是否更新到后续推荐中。"
    )

    normalized = _normalize_general_confirmation_protocol_wording(reply)

    assert "调整偏好后，系统会重新筛选" not in normalized
    assert "列出来让你采纳" in normalized
    assert "采纳后" in normalized
    assert "点“采纳”前不会更新到后续推荐中" in normalized


def test_normalize_general_confirmation_protocol_wording_appends_boundary_when_changeable_reply_lacks_card():
    reply = (
        "可以改。之前设置的偏好、排除项和方案内容，随时都可以调整，不会锁死。\n"
        "- 调整后会重新匹配候选机会，已生成的方案也可以同步更新\n"
        "- 增删、替换、调整顺序都可以"
    )

    normalized = _normalize_general_confirmation_protocol_wording(reply)

    assert "调整后会重新匹配候选机会，已生成的方案也可以同步更新" not in normalized
    assert "增删、替换、调整顺序都可以，但都会先给确认预览" in normalized
    assert "列出" in normalized
    assert "点击采纳前不会改动方案" in normalized


def test_normalize_general_confirmation_protocol_wording_no_card_boundary_uses_consultative_wording():
    reply = "可以改。你之前设置的偏好或要求，随时都能调整。已经生成方案的话，也可以替换或重新排序。"

    normalized = _normalize_general_confirmation_protocol_wording(reply)

    assert "要采用的内容" in normalized
    assert "具体影响或调整预览" in normalized
    assert "让你决定是否采用" in normalized
    assert "采纳/确认前不会生效" not in normalized


def test_normalize_unbacked_intent_preview_reply_removes_fake_confirm_boundary():
    reply = (
        "中医确实属于医学门类。\n\n"
        "我先把你刚才说的整理成待确认偏好：\n\n"
        "**待确认内容**\n"
        "- 排除专业门类：医学\n\n"
        "**下一步**\n"
        "- 回复“确认”就按上面执行；"
    )

    normalized = _normalize_unbacked_intent_preview_reply(reply)

    assert "待确认内容" not in normalized
    assert "回复“确认”就按上面执行" not in normalized
    assert "还没有列出可采纳的内容" in normalized
    assert "点“采纳”后才会生效" in normalized


def test_unbacked_intent_preview_detector_covers_adopt_wording():
    reply = (
        "我先把要采用的内容列出来，点\"采纳\"前不会生效：\n\n"
        "**待采纳内容**\n"
        "- **只保留专业门类**：医学\n\n"
        "如果你确认只保留医学类，请点\"采纳\"。"
    )

    assert _reply_looks_like_unbacked_intent_preview(reply) is True


def test_unbacked_intent_preview_detector_covers_prepared_direction_wording():
    reply = (
        "我先把你要采用的内容列出来，点\"采纳\"前不会生效：\n\n"
        "**准备采纳的方向**\n"
        "- 只保留：医学类（一级门类）\n"
        "- 排除范围：工科（一级门类）\n\n"
        "**采纳后的影响**\n"
        "- 后续推荐、方案检查和方案调整会以医学类为优先方向"
    )

    assert _reply_looks_like_unbacked_intent_preview(reply) is True


def test_normalize_unbacked_intent_preview_reply_keeps_general_card_protocol_explanation():
    reply = (
        "孩子改主意后，之前偏好可以调整。只要孩子想法变了，直接告诉我新的方向，"
        "我会先整理成待采纳内容；采纳后再调整推荐口径和候选志愿。"
    )

    normalized = _normalize_unbacked_intent_preview_reply(reply)

    assert normalized == reply


def test_normalize_unbacked_intent_preview_reply_keeps_generic_confirm_protocol_without_items():
    reply = (
        "可以改。如果你确认要更新，后续我会先整理待采纳内容，"
        "等你点击采纳后再作为后续参考。"
    )

    normalized = _normalize_unbacked_intent_preview_reply(reply)

    assert normalized == reply


def test_runtime_pending_followup_guard_keeps_only_latest_pending_card():
    workspace = WSResponse(type="planningWorkspaceAction", session_id="s1", content="{}")
    plan_card = WSResponse(
        type="pendingConfirmationCard",
        session_id="s1",
        content=json.dumps({"type": "pendingConfirmationCard", "kind": "plan_mutation", "pendingId": "p1"}, ensure_ascii=False),
    )
    intent_card = WSResponse(
        type="pendingConfirmationCard",
        session_id="s1",
        content=json.dumps({"type": "pendingConfirmationCard", "kind": "intent_change", "pendingId": "i1"}, ensure_ascii=False),
    )

    guarded = _enforce_single_pending_confirmation_followup([workspace, plan_card, intent_card])

    assert guarded == [workspace, intent_card]


def test_intent_card_primary_reply_from_preview_payload_uses_summary():
    preview_payload = {
        "status": "ready",
        "sessionId": "34",
        "title": "确认这次报考想法",
        "intentMode": "preference",
        "analysisStage": "confirmed",
        "items": [
            {
                "content": "偏好专业：会计学、审计学",
                "selected": True,
                "value": {"major_intents": {"level3": ["会计学", "审计学"]}},
            }
        ],
    }
    reply = _intent_card_primary_reply_from_preview_payload(preview_payload)

    assert reply
    assert "会计学" in reply
    assert "采纳" in reply
    assert "不会生效" in reply


def test_intent_card_primary_reply_preserves_user_facing_major_alias():
    preview_payload = {
        "status": "ready",
        "sessionId": "35",
        "title": "确认这次报考条件",
        "intentMode": "constraint",
        "constraintIntentType": "only_keep",
        "analysisStage": "confirmed",
        "items": [
            {
                "content": "把气象（大气科学）记成明确要满足的具体专业要求，后面看候选和方案时会按这个范围来。",
                "selected": True,
                "value": {"major_intents": {"level3": ["大气科学"]}},
            },
            {
                "content": "把电气（电气工程及其自动化）记成明确要满足的具体专业要求，后面看候选和方案时会按这个范围来。",
                "selected": True,
                "value": {"major_intents": {"level3": ["电气工程及其自动化"]}},
            },
        ],
    }

    reply = _intent_card_primary_reply_from_preview_payload(preview_payload)

    assert "气象" in reply
    assert "大气科学" in reply
    assert "电气" in reply
    assert "电气工程及其自动化" in reply


def test_plan_mutation_card_intent_summary_preserves_user_facing_major_alias():
    preview_payload = {
        "status": "ready",
        "sessionId": "35-plan",
        "title": "确认这次报考条件",
        "intentMode": "constraint",
        "constraintIntentType": "only_keep",
        "analysisStage": "confirmed",
        "items": [
            {
                "content": "把气象（大气科学）记成明确要满足的具体专业要求，后面看候选和方案时会按这个范围来。",
                "selected": True,
                "value": {"major_intents": {"level3": ["大气科学"]}},
            },
            {
                "content": "把电气（电气工程及其自动化）记成明确要满足的具体专业要求，后面看候选和方案时会按这个范围来。",
                "selected": True,
                "value": {"major_intents": {"level3": ["电气工程及其自动化"]}},
            },
        ],
    }
    backend_preview = _user_goal_fix_proposal_response(
        proposal_id="ug-only-keep-weather-electric",
        strategy="only_keep_scope",
        source_version=12,
        title="只保留电气和气象方向",
        summary="当前方案需要按这个范围调整。",
        action_summaries=["移出不在范围内的志愿"],
    )
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_planning_state", AsyncMock(return_value=_planning_state_response(12))), \
            patch("app.service.generate_user_goal_planning_fix_proposals", AsyncMock(return_value=backend_preview)), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_last_pending_confirmation", get_pending_mock):
        pending_result = asyncio.run(_create_pending_intent_confirmation_result_from_preview_payload("35-plan", preview_payload))
        card = pending_result.card

    assert isinstance(card, WSResponse)
    assert pending_result.source == "user_goal_fix_proposal"
    assert pending_result.workspace_refresh_targets == ["ordered"]
    assert pending_result.blocked_reasons == []
    payload = json.loads(card.content)
    assert payload["kind"] == "plan_mutation"
    assert "气象（大气科学）" in payload["content"]
    assert "电气（电气工程及其自动化）" in payload["content"]
    intent_payload = pending_state["value"]["executionPayload"]["intentPayload"]
    assert intent_payload["selected"] == [
        {"major_intents": {"level3": ["大气科学"]}},
        {"major_intents": {"level3": ["电气工程及其自动化"]}},
    ]
    assert "只保留专业" in intent_payload["displaySummary"]
    assert "气象（大气科学）" in intent_payload["displaySummary"]
    assert "电气（电气工程及其自动化）" in intent_payload["displaySummary"]
    req = pending_state["value"]["executionPayload"]["userGoalRequest"]
    assert [scope["normalizedName"] for scope in req["targetScopes"]] == ["大气科学", "电气工程及其自动化"]


def test_plan_mutation_card_drops_excluded_major_from_only_keep_target_scopes():
    preview_payload = {
        "status": "ready",
        "sessionId": "35-conflict",
        "title": "确认这次报考条件",
        "intentMode": "constraint",
        "constraintIntentType": "only_keep",
        "analysisStage": "confirmed",
        "items": [
            {
                "content": "只保留专业门类：医学",
                "selected": True,
                "value": {"major_intents": {"level1": ["医学"]}},
            },
            {
                "content": "只保留专业门类：工学",
                "selected": True,
                "value": {"major_intents": {"level1": ["工学"]}},
            },
            {
                "content": "排除专业门类：工学",
                "selected": True,
                "value": {"major_intents": {"negative_level1": ["工学"]}},
            },
        ],
    }
    backend_preview = _user_goal_fix_proposal_response(
        proposal_id="ug-only-keep-medical-no-engineering",
        strategy="only_keep_scope",
        source_version=12,
        title="只保留医学方向",
        summary="当前方案需要按这个范围调整。",
        action_summaries=["移出不在范围内的志愿"],
    )
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_planning_state", AsyncMock(return_value=_planning_state_response(12))), \
            patch("app.service.generate_user_goal_planning_fix_proposals", AsyncMock(return_value=backend_preview)) as proposal_mock, \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_last_pending_confirmation", get_pending_mock):
        pending_result = asyncio.run(_create_pending_intent_confirmation_result_from_preview_payload("35-conflict", preview_payload))
        card = pending_result.card

    assert isinstance(card, WSResponse)
    user_goal_req = proposal_mock.await_args.args[2]
    assert [scope["normalizedName"] for scope in user_goal_req["targetScopes"]] == ["医学"]
    assert [scope["normalizedName"] for scope in user_goal_req["negativeScopes"]] == []
    req = pending_state["value"]["executionPayload"]["userGoalRequest"]
    assert [scope["normalizedName"] for scope in req["targetScopes"]] == ["医学"]
    assert "工学" not in [scope["normalizedName"] for scope in req["targetScopes"]]


def test_constraint_user_goal_fix_candidate_from_preview_builds_ready_candidate():
    selected_data = {
        "selected": [{"major_intents": {"negative_level3": ["经济与金融"]}}],
        "intentMode": "constraint",
        "constraintIntentType": "default",
        "batch": "01",
        "displaySummary": "排除专业：经济与金融",
    }
    merged = {"major_intents": {"negative_level3": ["经济与金融"]}}
    backend_preview = _user_goal_fix_proposal_response(
        proposal_id="ug-exclude-econ-finance",
        strategy="exclude_scope",
        source_version=12,
        title="避开经济与金融",
        summary="当前方案中有经济与金融方向，需要同步调整。",
    )

    with patch("app.service.get_planning_state", AsyncMock(return_value=_planning_state_response(12))), \
            patch("app.service.generate_user_goal_planning_fix_proposals", AsyncMock(return_value=backend_preview)) as proposal_mock:
        candidate = asyncio.run(
            _constraint_user_goal_fix_candidate_from_preview(
                "34",
                selected_data=selected_data,
                merged=merged,
                batch="01",
                summary="排除专业：经济与金融",
                constraint_intent_type="default",
            )
        )

    assert candidate is not None
    assert candidate.proposal["proposalId"] == "ug-exclude-econ-finance"
    assert candidate.source_version_guard == 12
    assert candidate.user_goal_request["goalType"] == "exclude_scope"
    assert candidate.user_goal_request["negativeScopes"][0]["normalizedName"] == "经济与金融"
    assert candidate.intent_payload is selected_data
    proposal_mock.assert_awaited_once()


def test_constraint_user_goal_fix_candidate_from_preview_sets_fallback_for_no_ready_candidate():
    selected_data = {
        "selected": [{"major_intents": {"negative_level3": ["经济与金融"]}}],
        "intentMode": "constraint",
        "constraintIntentType": "default",
        "batch": "01",
        "displaySummary": "排除专业：经济与金融",
    }
    merged = {"major_intents": {"negative_level3": ["经济与金融"]}}
    blocked_preview = {
        "code": 0,
        "data": {
            "proposalSource": "user_goal",
            "sourceVersionGuard": 12,
            "proposals": [
                {
                    "proposalId": "ug-blocked",
                    "strategy": "exclude_scope",
                    "status": "blocked",
                    "summary": "当前没有可直接替换的候选。",
                    "blockingReason": "candidate_shortage",
                }
            ],
        },
    }
    attempt = SimpleNamespace(fallback_mechanism_line="", fallback_detail_lines=[])

    with patch("app.service.get_planning_state", AsyncMock(return_value=_planning_state_response(12))), \
            patch("app.service.generate_user_goal_planning_fix_proposals", AsyncMock(return_value=blocked_preview)):
        candidate = asyncio.run(
            _constraint_user_goal_fix_candidate_from_preview(
                "34",
                selected_data=selected_data,
                merged=merged,
                batch="01",
                summary="排除专业：经济与金融",
                constraint_intent_type="default",
                attempt=attempt,
            )
        )

    assert candidate is None
    assert attempt.fallback_mechanism_line
    assert attempt.fallback_detail_lines
    assert "没有可直接执行" in attempt.fallback_mechanism_line


def test_chat_service_constraint_preview_with_plan_hit_compiled_user_goal_fix_traces_pending():
    preview_payload = {
        "status": "ready",
        "sessionId": "34",
        "title": "确认这条要求",
        "intentMode": "constraint",
        "analysisStage": "confirmed",
        "items": [
            {
                "content": "排除专业：经济与金融",
                "selected": True,
                "value": {"major_intents": {"negative_level3": ["经济与金融"]}},
            }
        ],
    }
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()
    backend_preview = _user_goal_fix_proposal_response(
        proposal_id="ug-exclude-econ-finance",
        strategy="exclude_scope",
        source_version=12,
        title="避开经济与金融",
        summary="当前方案中有经济与金融方向，需要同步调整。",
        action_summaries=["移出经济与金融相关志愿"],
    )

    with patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_planning_state", AsyncMock(return_value=_planning_state_response(12))), \
            patch("app.service.generate_user_goal_planning_fix_proposals", AsyncMock(return_value=backend_preview)), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_last_pending_confirmation", get_pending_mock):
        pending_result = asyncio.run(_create_pending_intent_confirmation_result_from_preview_payload("34", preview_payload))
        card = pending_result.card

    assert isinstance(card, WSResponse)
    payload = json.loads(card.content)
    assert payload["kind"] == "plan_mutation"
    assert payload["actionFamily"] == "apply_fix_proposal"
    assert payload["proposalId"] == "ug-exclude-econ-finance"
    compiled_id = pending_state["value"]["compiledProposalId"]
    assert compiled_id.startswith("user-goal-fix:34:")
    assert pending_state["value"]["compilerSink"] == {
        "compiledProposalId": compiled_id,
        "sinkType": "fix_proposal",
    }
    execution_payload = pending_state["value"]["executionPayload"]
    assert execution_payload["compiledProposalId"] == compiled_id
    assert execution_payload["proposalSource"] == "user_goal"
    assert execution_payload["proposalId"] == "ug-exclude-econ-finance"
    assert execution_payload["sourceVersionGuard"] == 12


def test_chat_service_constraint_preview_ready_without_actions_blocks_compiled_fix_pending():
    preview_payload = {
        "status": "ready",
        "sessionId": "34-gap",
        "title": "确认这条要求",
        "intentMode": "constraint",
        "analysisStage": "confirmed",
        "items": [
            {
                "content": "排除专业：经济与金融",
                "selected": True,
                "value": {"major_intents": {"negative_level3": ["经济与金融"]}},
            }
        ],
    }
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()
    backend_preview = _user_goal_fix_proposal_response(
        proposal_id="ug-gap",
        strategy="exclude_scope",
        source_version=12,
        title="避开经济与金融",
        summary="当前方案中有命中项，但缺少可执行动作。",
    )
    backend_preview["data"]["proposals"][0]["actions"] = []

    with patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_planning_state", AsyncMock(return_value=_planning_state_response(12))), \
            patch("app.service.generate_user_goal_planning_fix_proposals", AsyncMock(return_value=backend_preview)), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_last_pending_confirmation", get_pending_mock):
        pending_result = asyncio.run(_create_pending_intent_confirmation_result_from_preview_payload("34-gap", preview_payload))
        card = pending_result.card

    assert card is None
    assert pending_result.blocked_reasons == ["compiled_plan_fix_blocked"]
    assert pending_state == {}


def test_select_ready_fix_proposal_requires_target_strategy_match():
    facts = {
        "fix_proposals": {
            "proposals": [
                {
                    "proposal_id": "fp_count",
                    "status": "ready",
                    "title": "处理数量校验",
                    "strategy": "fill_missing_count",
                },
                {
                    "proposal_id": "fp_gap",
                    "status": "preview_only",
                    "title": "处理录取率梯度断层",
                    "strategy": "fill_probability_gap",
                },
            ],
        }
    }

    assert (
        proposal_compiler.select_ready_fix_proposal(
            facts,
            target_strategies=["rebalance_tier_ratio", "fill_probability_gap"],
        )
        is None
    )
    assert proposal_compiler.ready_fix_proposal_id_for_strategies(
        facts,
        ["rebalance_tier_ratio", "fill_probability_gap"],
    ) == ""
    assert proposal_compiler.select_ready_fix_proposal(facts)["proposal_id"] == "fp_count"


def test_plan_query_fallback_keeps_candidate_query_filters_on_empty_result():
    reply = _build_plan_timeout_fallback_reply(
        {
            "applied": True,
            "action_family": "query_candidates",
            "stage": "apply",
            "result_kind": "candidate_snapshot",
            "summary": (
                "候选志愿查询结果：\n"
                "- 命中数量：0\n"
                "- 当前页：第1页，每页5条\n"
                "- 当前筛选条件下没有候选结果。"
            ),
            "reply_focus": ["candidate_snapshot", "local_candidate_query", "school_list_query"],
            "facts": {
                "requested_reply_focus": ["candidate_snapshot", "local_candidate_query", "school_list_query"],
                "query_filters": {
                    "province_names": ["海南"],
                    "school_keywords": ["电力", "铁道", "航空"],
                },
                "plan_query_dsl": {
                    "type": "PlanQuery",
                    "scopeAnchor": "candidate_pool",
                    "queryType": "readonly_plan_query",
                    "dimensions": ["item_list"],
                    "filters": {
                        "province_names": ["海南"],
                        "school_keywords": ["电力", "铁道", "航空"],
                    },
                    "projection": {"mode": "school_list", "limit": 5},
                },
            },
        }
    )

    assert reply is not None
    assert "海南" in reply
    assert "电力" in reply
    assert "铁道" in reply
    assert "航空" in reply
    assert "暂时没有命中结果" in reply


def test_shortage_boundary_fallback_answers_supply_gap_without_internal_labels():
    reply = _build_plan_timeout_fallback_reply(
        {
            "applied": True,
            "action_family": "analyze_adjustment",
            "stage": "apply",
            "result_kind": "adjustment_analysis",
            "summary": "已分析冲稳保补齐边界。",
            "facts": {
                "requested_reply_focus": ["shortage_boundary"],
                "candidate_supply": {
                    "total": 94,
                    "tier_counts": {"冲": 66, "稳": 28, "保": 0},
                    "missing_supply_tiers": ["保"],
                },
                "fix_proposals": {
                    "blocked_count": 2,
                    "proposals": [
                        {
                            "status": "blocked",
                            "title": "处理数量校验",
                            "strategy": "rebalance_tier_ratio",
                            "blocking_reason": "当前候选里缺少保区可用志愿，暂时无法补齐保底。",
                        },
                        {
                            "status": "blocked",
                            "title": "处理录取率梯度断层",
                            "strategy": "fill_probability_gap",
                            "candidate_shortages": [
                                {"message": "当前可用于规划的可选范围里，断层中间录取率候选不足"}
                            ],
                        },
                    ],
                },
            },
        },
        user_prompt="保底够不够，别最后滑档",
    )

    assert reply is not None
    assert "冲66 / 稳28 / 保0" in reply
    assert "保 区间" in reply
    assert "不是简单把比例调一下就能补上" in reply
    assert "处理数量校验" not in reply
    assert "处理录取率梯度断层" not in reply
    assert "系统" not in reply


def test_review_result_fallback_groups_repair_options_without_repeated_system_copy():
    reply = _build_plan_timeout_fallback_reply(
        {
            "applied": True,
            "action_family": "review_plan",
            "stage": "review",
            "result_kind": "review_result",
            "summary": "当前方案有提醒。",
            "facts": {
                "risk_count": 1,
                "warn_count": 7,
                "plan_total": 46,
                "target_total": 45,
                "tier_counts": {"冲": 19, "稳": 13, "保": 14},
                "main_problems": ["冲区占比过高", "当前排序存在录取概率倒挂", "当前录取概率梯度存在断层"],
                "issue_hit_plan_examples": [
                    {
                        "summary": "当前排序存在录取概率倒挂",
                        "count_text": "共命中 5 条志愿",
                        "items": [
                            "上海财经大学浙江学院第101组-会计学(注册会计)(保)@121",
                            "上海财经大学浙江学院第101组-会计学(保)@123",
                        ],
                    },
                    {
                        "summary": "当前排序存在录取概率倒挂",
                        "count_text": "共命中 5 条志愿",
                        "items": [
                            "上海财经大学浙江学院第101组-会计学(注册会计)(保)@121",
                            "上海财经大学浙江学院第101组-会计学(保)@123",
                        ],
                    }
                ],
                "fix_proposals": {
                    "ready_count": 1,
                    "blocked_count": 2,
                    "preview_only_count": 0,
                    "proposals": [
                        {
                            "status": "ready",
                            "title": "处理录取率倒挂",
                            "summary": "建议检查相邻专业组顺序，确认是否符合真实风险梯度",
                            "strategy": "sort_by_probability",
                            "action_summaries": ["按录取率重排"],
                        },
                        {
                            "status": "ready",
                            "title": "处理兜底专业不足",
                            "summary": "建议在对应专业组内至少保留一个录取率高于组整体录取率的专业",
                            "strategy": "adjust_major_group_inner_safety",
                            "action_summaries": ["补入兜底专业"],
                        },
                        {
                            "status": "blocked",
                            "title": "冲稳保配比暂时无法自动处理",
                            "summary": "建议你先查看具体影响，或调整筛选范围后再试",
                            "blocking_reason": "当前候选里缺少目标冲稳保区间的可用志愿，暂时无法调整配比",
                            "strategy": "rebalance_tier_ratio",
                            "candidate_shortages": [
                                {"message": "当前可用于规划的可选范围里，目标冲稳保区间候选不足"}
                            ],
                        },
                        {
                            "status": "blocked",
                            "title": "录取率梯度断层暂时无法自动处理",
                            "summary": "建议你先查看具体影响，或调整筛选范围后再试",
                            "blocking_reason": "当前候选里缺少断层区间的可用志愿，暂时无法补齐录取率梯度",
                            "strategy": "fill_probability_gap",
                            "candidate_shortages": [
                                {"message": "当前可用于规划的可选范围里，断层中间录取率候选不足"}
                            ],
                        },
                    ],
                },
            },
        }
    )

    assert reply is not None
    assert "可以先看调整预览的" in reply
    assert "需要你先取舍或放宽条件的" in reply
    assert "第121位" in reply
    assert reply.count("上海财经大学浙江学院第101组-会计学(保)第123位") == 1
    assert "补兜底专业" in reply
    assert "处理兜底专业不足" not in reply
    assert "处理录取率倒挂" not in reply
    assert "补入兜底专业" not in reply
    assert "需要你先决定取舍的方向" not in reply
    assert "建议你先查看具体影响，或调整筛选范围后再试" not in reply
    assert reply.count("当前候选志愿里") <= 2


def test_review_reply_needs_structured_fallback_for_systemish_hierarchy_copy():
    result = {
        "applied": True,
        "action_family": "review_plan",
        "stage": "review",
        "result_kind": "review_result",
    }
    reply = (
        "可以先出调整预览给你看：处理录取率倒挂；处理兜底专业不足。"
        "需要你先决定取舍或放宽条件：冲稳保配比、录取率梯度断层。"
        "候选供给也充足，系统预估可以替换，系统不会擅自删你的志愿。"
        "这几个问题需要你给个明确态度，可以立即处理的有 2 项。"
    )

    assert _review_reply_needs_structured_fallback(reply, result) is True


def test_review_reply_needs_structured_fallback_for_generic_review_too_narrow():
    result = {
        "applied": True,
        "action_family": "review_plan",
        "stage": "review",
        "result_kind": "review_result",
        "facts": {
            "risk_count": 3,
            "warn_count": 5,
            "main_problems": [
                "冲区占比过高且保区占比过低",
                "本省保底志愿数量不足",
                "当前排序存在录取概率倒挂",
            ],
        },
    }

    assert _review_reply_needs_structured_fallback(
        "方案审查完了，有3项风险、5项提醒，核心问题是录取率梯度存在断层。"
        "目前有两个处理方向：补齐录取率梯度、补足志愿数量。",
        result,
    ) is True
    assert _review_reply_needs_structured_fallback(
        "方案审查完了，风险 3 项，提醒 5 项。主要需要留意：冲区占比过高且保区占比过低；"
        "本省保底志愿数量不足；当前排序存在录取概率倒挂。",
        result,
    ) is False


def test_review_reply_overclaims_admission_safety_for_review_result():
    result = {
        "applied": True,
        "action_family": "review_plan",
        "stage": "review",
        "result_kind": "review_result",
        "facts": {"risk_count": 0, "warn_count": 2},
    }

    assert _review_reply_overclaims_admission_safety(
        "先给你个定心丸：当前方案没有风险项，不会滑档。",
        result,
    ) is True
    assert _review_reply_overclaims_admission_safety(
        "风险：0 项 —— 当前方案没有会导致滑档或明显不合理的地方，整体结构是安全的。",
        result,
    ) is True
    assert _review_reply_overclaims_admission_safety(
        "当前审查没有发现明确风险，但仍要看录取概率和当年波动。",
        result,
    ) is False
    assert _review_reply_overclaims_admission_safety(
        "当前审查没有发现明确风险，但不能保证不会滑档。",
        result,
    ) is False
    adjustment_result = {
        "applied": True,
        "action_family": "analyze_adjustment",
        "stage": "apply",
        "result_kind": "adjustment_analysis",
        "facts": {"candidate_supply": {"missing_supply_tiers": []}},
    }
    assert _review_reply_overclaims_admission_safety(
        "保底已经够了，可以保证不滑档。",
        adjustment_result,
    ) is True


def test_adjustment_analysis_fallback_hides_raw_summary_and_positions():
    reply = _build_plan_timeout_fallback_reply(
        {
            "applied": True,
            "action_family": "analyze_adjustment",
            "stage": "apply",
            "result_kind": "adjustment_analysis",
            "summary": (
                "部分专业组主要依靠非意向专业托底；当前先拿到的是分析结论，不是可直接执行的调整清单："
                "补充建议 0 条，调序建议 0 条，替换建议 0 条，移除建议 0 条；"
                "如果先从减法入手，可优先查看：当前方案包含高收费专业@18。"
            ),
            "facts": {
                "actionable_suggestion_counts": {"add": 0, "reorder": 0, "replace": 0, "remove": 0},
                "main_problems": ["部分专业组主要依靠非意向专业托底"],
                "review_issue_hit_plan_examples": [
                    {
                        "summary": "当前方案包含高收费专业",
                        "count_text": "共命中 9 条志愿",
                        "items": [
                            "东北财经大学第202组-工商管理(中外合作办学)(冲)@18",
                            "天津科技大学第203组-财务管理(中外合作办学)(冲)@19",
                        ],
                    }
                ],
                "candidate_supply": {"total": 431, "tier_counts": {"冲": 459, "稳": 238, "保": 773}},
                "fix_proposals": {
                    "blocked_count": 2,
                    "proposals": [
                        {
                            "status": "blocked",
                            "title": "处理高收费",
                            "summary": "建议结合家庭经济状况确认是否保留相关志愿",
                            "strategy": "replace_risk_items",
                            "blocking_reason": "替换预览会改变专业组数量，需要你先取舍后再处理",
                        },
                        {
                            "status": "blocked",
                            "title": "处理中外合作",
                            "summary": "若不接受中外合作办学，可将相关志愿移出方案",
                            "strategy": "replace_risk_items",
                            "blocking_reason": "替换预览会改变专业组数量，需要你先取舍后再处理",
                        },
                    ],
                },
            },
        }
    )

    assert reply is not None
    assert "这轮先拿到的是分析结论" in reply
    assert "需要你先取舍或放宽条件的" in reply
    assert "候选志愿约 431 个" in reply
    assert "补充建议 0 条" not in reply
    assert "候选供给：" not in reply
    assert "@18" not in reply


def test_fix_proposal_card_content_dedupes_action_summaries():
    content = _format_fix_proposal_card_content(
        {
            "title": "处理组内安全垫不足",
            "summary": "建议在对应专业组内至少保留一个录取率高于组整体录取率的专业",
            "action_summaries": ["补入组内安全垫专业", "补入组内安全垫专业"],
            "impact": "当前问题涉及 3 个专业组、7 条志愿",
        }
    )

    assert "组内安全垫" not in content
    assert content.count("补入兜底专业") == 1


def test_fix_proposal_card_content_includes_readable_replacement_preview_detail():
    content = _format_fix_proposal_card_content(
        {
            "title": "避开经济与金融",
            "summary": "当前方案有 1 条命中，可确认后处理。",
            "actionSummaries": ["替换经济与金融相关志愿"],
            "actions": [
                {
                    "actionType": "replace_volunteers",
                    "summary": "替换经济与金融相关志愿",
                    "detail": "预计替换 1 组。具体预览：学校A-经济与金融（稳/录取率52.0%/推荐88.0） -> 学校B-法学（稳/录取率58.0%/意图93.0/推荐84.0）。",
                    "replacementPairs": [{"fromVolunteerId": "econ-finance-1", "toVolunteerId": "law-1"}],
                }
            ],
            "impact": "确认后会移出经济与金融相关志愿。",
        }
    )

    assert "替换预览" in content
    assert "学校A-经济与金融" in content
    assert "学校B-法学" in content
    assert "->" in content
    assert "econ-finance-1 -> law-1" not in content
