"""Tests for ChatService persistence and model-first dialog entry."""

from __future__ import annotations

import asyncio
import json
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
    _classify_turn_decision_cached,
    _pending_confirmation_primary_reply_from_card,
    _load_pending_confirmation_state,
    _save_pending_confirmation_state,
    build_runtime_history,
    _normalize_pending_intent_reply,
    _pending_confirmation_from_state,
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
    _blocked_intent_preview_for_plan_route_reply,
    _guard_unbacked_plan_confirmation_reply,
    _constraint_user_goal_fix_candidate_from_preview,
    _enforce_single_pending_confirmation_followup,
)
from app.tools.intent_state_tool import IntentSideEffectDecision
from app.tools.intent_state_tool import apply_selected_intents
from app.tools.intent_response_tool import IntentStateUpdateResult, render_intent_state_update


def test_pending_confirmation_loads_latest_version_and_saves_same_version():
    latest_response = {
        "code": 0,
        "data": {
            "chatSessionId": 9904301,
            "dataKey": "pendingConfirmation",
            "dataType": "JSON_OBJECT",
            "dataVersion": 248,
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
        assert state["_extraDataVersion"] == 248
        applied_state = dict(state)
        applied_state["status"] = "applied"
        asyncio.run(_save_pending_confirmation_state("9904301", applied_state))

    save_mock.assert_awaited_once()
    assert save_mock.await_args.args[:2] == ("9904301", applied_state)
    assert save_mock.await_args.kwargs["version"] == 248


def test_pending_confirmation_load_falls_back_to_version_zero():
    pending = {
        "type": "pendingConfirmation",
        "pendingId": "pending-v0",
        "kind": "intent_change",
        "status": "active",
        "actionFamily": "apply_selected_intents",
        "executionPayload": {"merged": {"school_intents": {"negative_school_nature": ["民办"]}}},
    }

    with patch("app.service.get_last_pending_confirmation", AsyncMock(return_value={"code": 0, "data": {}})), \
            patch(
                "app.service.get_pending_confirmation",
                AsyncMock(return_value={"code": 0, "data": {"pendingConfirmation": pending}}),
            ):
        state = asyncio.run(_load_pending_confirmation_state("9904302"))

    assert state == pending



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


def test_blocked_intent_preview_for_plan_route_reply_preserves_structured_focus():
    reply = _blocked_intent_preview_for_plan_route_reply(
        _runtime_turn_decision(
            task_layer="plan",
            side_effect="plan_preview",
            scope_anchor="current_plan",
            scenario="atomic_mutation",
            confidence=0.95,
        ),
        {
            "intentMode": "constraint",
            "constraintIntentType": "only_keep",
            "items": [
                {
                    "content": "把江苏记成明确要满足的省份要求",
                    "selected": True,
                    "value": {"city_intents": {"province": ["江苏"]}},
                }
            ],
        },
    )

    assert "江苏" in reply
    assert "只保留" in reply
    assert "没有形成可执行的调整内容" in reply
    assert "不会创建长期意向卡" in reply
    assert "不会改动当前方案" in reply


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
                    tool_name="analyze_current_major_interest",
                    content="只读专业影响分析。",
                    tool_call_id="major-interest-call",
                )
            ]
        )
    ]

    from app.service import _tool_returns_interest_stage_intent_analysis

    assert _tool_returns_interest_stage_intent_analysis(messages) is True


def test_runtime_local_plan_action_compiler_binds_tier_metric_rank_and_target_scope():
    source = proposal_compiler.compile_runtime_local_plan_action_source(
        content="帮我把保底区里录取率最高的那个调到保底的第一位",
        action_family="move_ordered_unit",
        tier="保底",
        sort_field="admissionRatio",
        rank="highest",
        target_ordinal=1,
        planning_version=12,
    )

    assert source.matched is True
    assert source.route == "local_plan_action"
    payload = source.plan_payload
    assert payload is not None
    assert payload["stage"] == "preview"
    assert payload["action_family"] == "move_ordered_unit"
    assert payload["planning_version"] == 12
    action = payload["atomic_actions"][0]
    assert action["action_type"] == "move_ordered_unit"
    assert action["filters"] == {"tier": "保", "sortBy": "admissionRatio", "rank": "highest", "targetOrdinal": 1}
    assert payload["reply_focus"] == ["local_plan_action", "tier_local_reorder"]
    assert source.plan_action_dsl["scopeAnchor"] == "current_plan.tier_segment"
    assert source.plan_action_dsl["targetPosition"] == {
        "tier": "保",
        "ordinalScope": "within_tier",
        "targetOrdinal": 1,
    }


def test_runtime_local_plan_action_compiler_covers_same_action_family_variants():
    steady = proposal_compiler.compile_runtime_local_plan_action_source(
        content="把稳档里推荐系数最高的专业组放到稳档第一位",
        action_family="move_ordered_unit",
        tier="稳档",
        sort_field="finalScore",
        rank="highest",
        target_ordinal=1,
        planning_version=3,
    )
    rush = proposal_compiler.compile_runtime_local_plan_action_source(
        content="把冲档院校层次最靠前的那个移到冲档第二位",
        action_family="move_ordered_unit",
        tier="冲档",
        sort_field="schoolRank",
        rank="best",
        target_ordinal=2,
        planning_version=4,
    )
    safe_tail = proposal_compiler.compile_runtime_local_plan_action_source(
        content="把保底录取率最低的放到保底最后",
        action_family="move_ordered_unit",
        tier="保底",
        sort_field="admissionRatio",
        rank="lowest",
        target_rank="last",
        planning_version=5,
    )

    assert steady.matched is True
    assert steady.plan_payload["atomic_actions"][0]["filters"] == {
        "tier": "稳",
        "sortBy": "finalScore",
        "rank": "highest",
        "targetOrdinal": 1,
    }
    assert rush.matched is True
    assert rush.plan_payload["atomic_actions"][0]["filters"] == {
        "tier": "冲",
        "sortBy": "schoolRank",
        "rank": "best",
        "targetOrdinal": 2,
    }
    assert safe_tail.matched is True
    assert safe_tail.plan_payload["atomic_actions"][0]["filters"] == {
        "tier": "保",
        "sortBy": "admissionRatio",
        "rank": "lowest",
        "targetRank": "last",
    }


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


def test_chat_service_needs_plan_first_guard_blocks_no_plan_current_plan_reference(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()
    fake_agent = _FakeAgent(["不应该调用模型"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
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
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "session-needs-plan-first-no-plan",
                "user-1",
                "刚那个方案民办能少点不",
            )
        )

    assert isinstance(reply, str)
    assert "当前还没有生成正式方案" in reply
    assert "不会把公办/民办这类要求写成新的报考要求" in reply
    assert "不会改动方案" in reply
    assert pending_state == {}
    save_pending_mock.assert_not_awaited()
    assert fake_agent.calls == []
    saved_history = asyncio.run(store.load("session-needs-plan-first-no-plan"))
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
    assert route_events[-1]["routeDecision"]["route"] == "needs_plan_first"
    assert route_events[-1]["routeDecision"]["referenceResolution"] == "no_referent"


def test_chat_service_needs_plan_first_guard_runs_before_zhiyuan_direct(
    tmp_path,
    mock_llm_client,
):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()
    fake_agent = _FakeAgent(["不应该调用旧模型"])
    direct_agent = SimpleNamespace(run_with_message_deltas=AsyncMock())

    with patch("app.service.ChatAgent", return_value=fake_agent), \
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
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        service._zhiyuan_agent_direct_enabled = True
        service.zhiyuan_agent_poc = direct_agent
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


def test_chat_service_needs_plan_first_guard_preserves_career_direction_focus(
    tmp_path,
    mock_llm_client,
):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()
    fake_agent = _FakeAgent(["不应该调用模型"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
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
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "session-needs-plan-first-career-focus",
                "user-1",
                "当前方案对体制内稳定就业方向承接得怎么样，先不要改方案",
            )
        )

    assert isinstance(reply, str)
    assert "当前还没有生成正式方案" in reply
    assert "体制内/考公导向" in reply
    assert "稳定就业导向" in reply
    assert "承接" in reply
    assert "不会改动当前方案" in reply
    assert pending_state == {}
    save_pending_mock.assert_not_awaited()
    assert fake_agent.calls == []
    saved_history = asyncio.run(store.load("session-needs-plan-first-career-focus"))
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
    route_decision = route_events[-1]["routeDecision"]
    assert route_events[-1]["routingPath"] == "needs_plan_first_guard"
    assert route_decision["targetIssues"] == ["career_direction_support"]
    assert route_decision["displayPayload"]["focusLabel"] == "体制内/考公导向、稳定就业导向的方案承接"
    assert route_decision["replyPlan"]["focus"] == ["career_direction_support"]


def test_chat_service_needs_plan_first_guard_preserves_applied_intent_conflict_focus(
    tmp_path,
    mock_llm_client,
):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store(
        {
            "pendingId": "applied-intent-conflict-focus",
            "kind": "intent_change",
            "status": "applied",
            "actionFamily": "apply_selected_intents",
            "summary": "偏好专业类：财经类；排除专业：护理学、中西医结合类",
            "executionPayload": {
                "selectedData": {
                    "selected": [
                        {
                            "major_intents": {
                                "level2": ["财经类"],
                                "negative_level3": ["护理学"],
                                "negative_level2": ["中西医结合类"],
                            }
                        }
                    ]
                },
                "merged": {
                    "major_intents": {
                        "level2": ["财经类"],
                        "negative_level3": ["护理学"],
                        "negative_level2": ["中西医结合类"],
                    }
                },
                "intentMode": "preference",
                "batch": "01",
            },
        }
    )
    fake_agent = _FakeAgent(["不应该调用模型"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
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
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "session-needs-plan-first-intent-conflict-focus",
                "user-1",
                "现在方案里哪些和这些要求冲突",
            )
        )

    assert isinstance(reply, str)
    assert "当前还没有生成正式方案" in reply
    assert "财经类" in reply
    assert "护理学" in reply
    assert "中西医结合类" in reply
    assert "逐项判断哪些志愿冲突或不符合" in reply
    assert "冲稳保或风险" not in reply
    assert pending_state["value"]["status"] == "applied"
    save_pending_mock.assert_not_awaited()
    assert fake_agent.calls == []
    saved_history = asyncio.run(store.load("session-needs-plan-first-intent-conflict-focus"))
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
    route_decision = route_events[-1]["routeDecision"]
    assert route_decision["targetIssues"] == ["intent_conflict_check_without_referent"]
    assert route_decision["displayPayload"]["recentIntentSummary"] == "偏好专业类：财经类；排除专业：护理学、中西医结合类"
    assert route_decision["replyPlan"]["focus"] == ["intent_conflict_check_without_referent"]


def test_chat_service_needs_plan_first_guard_blocks_no_plan_mutation_before_direct_agent(
    tmp_path,
    mock_llm_client,
):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()
    fake_agent = _FakeAgent(["不应该调用模型"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
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
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "session-needs-plan-first-no-plan-mutation",
                "user-1",
                "把会计审计相关替换成新媒体或跨境电商相关",
            )
        )

    assert isinstance(reply, str)
    assert "当前还没有生成正式方案" in reply
    assert "不会改动方案" in reply
    assert pending_state == {}
    save_pending_mock.assert_not_awaited()
    assert fake_agent.calls == []


def test_chat_service_needs_plan_first_guard_blocks_no_plan_school_major_add_without_legacy_atomic(
    tmp_path,
    mock_llm_client,
):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()
    fake_agent = _FakeAgent(["不应该调用模型"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
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
            patch("app.service.classify_turn_decision", AsyncMock(return_value=_runtime_turn_decision())), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "session-needs-plan-first-school-major-add",
                "user-1",
                "把广西师大统计加进来",
            )
        )

    primary = reply.primary if isinstance(reply, ChatServiceResponseEnvelope) else reply
    assert isinstance(primary, str)
    assert "当前还没有生成正式方案" in primary
    assert "加入当前方案的候选志愿" in primary
    assert "不会把加入当前方案的候选志愿写成新的报考要求" in primary
    assert pending_state == {}
    save_pending_mock.assert_not_awaited()
    assert fake_agent.calls == []
    saved_history = asyncio.run(store.load("session-needs-plan-first-school-major-add"))
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
    route_decision = route_events[-1]["routeDecision"]
    assert route_events[-1]["routingPath"] == "needs_plan_first_guard"
    assert route_decision["source"] == "proposal_compiler"
    assert route_decision["targetIssues"] == ["plan_add_without_referent"]


def test_chat_service_needs_plan_first_guard_does_not_block_future_reference(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()
    fake_agent = _FakeAgent(["我会先把这个作为后续参考列出来让你采纳。"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
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
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "session-needs-plan-first-future-reference",
                "user-1",
                "以后少推荐民办，优先公办",
            )
        )

    assert isinstance(reply, str)
    assert "当前还没有生成正式方案" not in reply
    assert pending_state == {}
    assert len(fake_agent.calls) == 1


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
        "blocked，暂不能自动处理，也无法生成确认卡片。preview_only"
    )

    assert "系统阻塞" not in normalized
    assert "阻塞原因" not in normalized
    assert "系统暂不支持" not in normalized
    assert "自动确认" not in normalized
    assert "专业组数量" not in normalized
    assert "暂不允许" not in normalized
    assert "blocked" not in normalized
    assert "暂不能自动处理" not in normalized
    assert "无法生成确认" not in normalized
    assert "preview_only" not in normalized
    assert "需要注意" in normalized
    assert "需要你先决定是否接受调整范围变化" in normalized
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
    def __init__(self, payload: dict, tool_name: str = "preview_current_region_intent_confirmation"):
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

    async def save(_session_id, data_value, version=0):
        state["value"] = dict(data_value)
        return {"code": 0, "data": {"pendingConfirmation": state["value"]}}

    async def get(_session_id, version=0):
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
                "firstToolNames": ["compare_majors"],
                "toolNameCounts": {"compare_majors": 1},
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
                        "toolNames": ["compare_majors"],
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
                "firstToolNames": ["preview_current_major_intent_confirmation", "preview_plan_action"],
                "toolNameCounts": {
                    "preview_current_major_intent_confirmation": 1,
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
                        "toolNames": ["preview_current_major_intent_confirmation", "preview_plan_action"],
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
                "firstToolNames": ["analyze_current_region_interest"],
                "toolNameCounts": {"analyze_current_region_interest": 1},
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
                        "toolNames": ["analyze_current_region_interest"],
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


def test_chat_service_logs_interrupted_full_agent_observability(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))

    with patch("app.service.ChatAgent", return_value=_CancellingAgent()), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service._log_conversation_turn_event") as log_mock:
        service = ChatService(mock_llm_client, store)
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(service.handle_message("session-timeout-obs", "user-1", "医学护理这些别碰，财会还能接受，先看看影响"))

    event = log_mock.call_args.kwargs
    assert event["routingPath"] == "full_agent"
    assert event["status"] == "cancelled"
    assert event["errorType"] == "CancelledError"
    assert event["routeDecision"]["fallbackReason"] == "agent_run_interrupted"
    assert event["routeDecision"]["agentRun"]["failedNode"] == "ModelRequestNode"


def test_chat_service_returns_safe_fallback_when_model_run_is_interrupted(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))

    with patch("app.service.ChatAgent", return_value=_InterruptedAgent()), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={
                "code": 0,
                "data": {
                    "phase": "reviewed",
                    "orderedPlanState": {
                        "summary": {
                            "total": 94,
                            "targetCount": 96,
                            "tierCounts": {"冲": 66, "稳": 28, "保": 0},
                        }
                    },
                    "draftPlanState": {"summary": {"total": 94, "targetCount": 96}},
                    "reviewState": {"summary": {"riskCount": 3, "warnCount": 5}},
                },
            })):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-interrupted-fallback", "user-1", "这版是不是太冲了"))

    assert "模型服务中断" in reply
    assert "不会" not in reply or "不改动" in reply
    assert "冲 66" in reply
    assert "稳 28" in reply
    assert "保 0" in reply


def test_chat_service_does_not_replace_active_pending_when_model_interrupts_after_plan_preview(
    tmp_path,
    mock_llm_client,
):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store(
        {
            "pendingId": "old-region-pending",
            "kind": "intent_change",
            "status": "active",
            "actionFamily": "apply_selected_intents",
            "summary": "排除地域：天津",
            "executionPayload": {
                "selectedData": {"selected": [{"city_intents": {"negative_province": ["天津"]}}]},
                "merged": {"city_intents": {"negative_province": ["天津"]}},
                "intentMode": "constraint",
                "batch": "01",
            },
        }
    )

    with patch("app.service.ChatAgent", return_value=_InterruptedAgent()), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "session-interrupted-plan-preview",
                "user-1",
                "把太贵的那几个先去掉看看",
            )
        )

    assert isinstance(reply, str)
    assert "模型服务中断" in reply
    assert "先不改动你的方案或偏好" in reply
    assert pending_state["value"]["pendingId"] == "old-region-pending"
    save_pending_mock.assert_not_awaited()


def test_chat_service_recovers_intent_preview_card_when_model_interrupts_after_tool_preview(
    tmp_path,
    mock_llm_client,
):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    preview_payload = {
        "status": "ready",
        "sessionId": "session-interrupted-intent-preview",
        "title": "采纳这次报考条件",
        "intentMode": "constraint",
        "constraintIntentType": "default",
        "analysisStage": "confirmed",
        "items": [
            {
                "id": "major-negative-english",
                "label": "排除专业：英语",
                "selected": True,
                "value": {"major_intents": {"negative_level3": ["英语"]}},
            }
        ],
        "existingItems": [],
        "impactText": "",
        "impactAnalysis": {
            "current_plan_conflicts": [
                {"label": "英语", "count": 2},
            ],
        },
    }
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.ChatAgent", return_value=_InterruptedIntentPreviewToolAgent(preview_payload)), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "session-interrupted-intent-preview",
                "user-1",
                "不要英语相关专业，当前方案里有的话也删掉",
            )
        )

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert reply.primary
    card = _assert_pending_card_envelope(reply, "", "apply_selected_intents", kind="intent_change")
    assert card["title"] == "采纳这次报考条件"
    assert "英语" in card["summary"]
    assert pending_state["value"]["kind"] == "intent_change"
    assert pending_state["value"]["status"] == "active"
    assert pending_state["value"]["executionPayload"]["selectedData"]["selected"] == [
        {"major_intents": {"negative_level3": ["英语"]}}
    ]
    saved = asyncio.run(store.load("session-interrupted-intent-preview"))
    assert any(
        isinstance(message, ModelResponse)
        and message.model_name == "agent-interruption-intent-preview-result"
        for message in saved
    )


def test_chat_service_interrupted_readonly_compare_fallback_preserves_context(
    tmp_path,
    mock_llm_client,
):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))

    with patch("app.service.ChatAgent", return_value=_InterruptedReadonlyToolAgent()), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "session-interrupted-readonly-compare",
                "user-1",
                "新媒体和跨电哪个更适合数学不太好的，先说说",
            )
        )

    assert "模型服务中断" in reply
    assert "没有改动你的方案" in reply
    assert "没有把偏好写入后续参考" in reply
    assert "网络与新媒体" in reply
    assert "跨境电子商务" in reply

    saved = asyncio.run(store.load("session-interrupted-readonly-compare"))
    assert any(
        isinstance(message, ModelResponse)
        and message.model_name == "agent-interruption-readonly-fallback"
        for message in saved
    )


def test_chat_service_interrupted_region_fallback_does_not_parse_city_as_major(
    tmp_path,
    mock_llm_client,
):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))

    with patch("app.service.ChatAgent", return_value=_InterruptedRegionReadonlyToolAgent()), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "session-interrupted-readonly-region",
                "user-1",
                "广东江苏这种城市机会是不是更好",
            )
        )

    assert "模型服务中断" in reply
    assert "没有改动你的方案" in reply
    assert "没有把偏好写入后续参考" in reply
    assert "广东江苏这种城市机会是不是更好" in reply
    assert "城市管理" not in reply


def test_chat_service_short_ack_after_readonly_interruption_does_not_call_agent(
    tmp_path,
    mock_llm_client,
):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    history = [
        ModelRequest(parts=[UserPromptPart(content="新媒体和跨电哪个更适合数学不太好的，先说说")]),
        ModelResponse(
            parts=[
                TextPart(
                    content=(
                        "这轮模型服务中断了，我没有改动你的方案，也没有把偏好写入后续参考。"
                        "你刚才问的是 网络与新媒体 和 跨境电子商务 的比较，这次没能完整生成分析结论；"
                        "你可以继续围绕刚才的问题追问，我会按只读分析处理。"
                    )
                )
            ],
            model_name="agent-interruption-readonly-fallback",
        ),
    ]
    asyncio.run(store.save("session-readonly-interrupted-short-ack", history))
    fake_agent = _FakeAgent(["不应该调用模型"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service._log_conversation_turn_event") as log_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "session-readonly-interrupted-short-ack",
                "user-1",
                "嗯那就这样",
            )
        )

    assert "先按刚才的分析结论理解" in reply
    assert "没有待确认的偏好或方案动作" in reply
    assert fake_agent.calls == []
    assert log_mock.call_args.kwargs["routingPath"] == "readonly_closure_ack"


def test_chat_service_still_raises_plain_agent_bug(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))

    with patch("app.service.ChatAgent", return_value=_BuggyAgent()), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        with pytest.raises(RuntimeError, match="plain bug"):
            asyncio.run(service.handle_message("session-plain-bug", "user-1", "测试"))


def test_chat_service_persists_and_recovers_history(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgent(["第一轮回复", "第二轮回复"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={
                "code": 0,
                "data": {
                    "phase": "reviewed",
                    "version": 2,
                    "draftPlanState": {"summary": {"total": 6}},
                    "orderedPlanState": {"summary": {"total": 5}},
                    "reviewState": {
                        "status": "completed",
                        "summary": {"total": 2, "warnCount": 1, "riskCount": 1},
                        "checks": [{"passed": False, "summary": "保区占比过低"}],
                    },
                },
            })):
        service1 = ChatService(mock_llm_client, store)
        reply1 = asyncio.run(service1.handle_message("session-1", "user-1", "你好"))

        assert reply1 == "第一轮回复"
        restored_after_first = asyncio.run(store.load("session-1"))
        assert restored_after_first is not None
        assert len(restored_after_first) == 3
        assert getattr(restored_after_first[1], "model_name", "") == "route-observability"
        route_payload = json.loads(restored_after_first[1].parts[0].content)
        assert route_payload["event"] == "conversation_turn_event"
        assert route_payload["routingPath"] == "full_agent"
        assert route_payload["routeDecision"]["toolTrial"]["hasToolCalls"] is False
        assert route_payload["routeDecision"]["agentRun"]["completed"] is True
        assert route_payload["routeDecision"]["agentRun"]["nodeTimings"][0]["node"] == "ModelRequestNode"
        assert restored_after_first[-1].parts[0].content == "第一轮回复"

        service2 = ChatService(mock_llm_client, store)
        service2.agent = fake_agent
        reply2 = asyncio.run(service2.handle_message("session-1", "user-1", "继续"))

        assert reply2 == "第二轮回复"
        assert fake_agent.calls[0]["message_history"] is None
        assert fake_agent.calls[0]["chat_history"] == [{"role": "user", "content": "你好"}]
        assert fake_agent.calls[0]["planning_summary"] is not None
        assert fake_agent.calls[0]["planning_summary"].phase == "reviewed"
        assert fake_agent.calls[0]["allow_explore_inner_llm"] is False
        assert fake_agent.calls[1]["message_history"] is not None
        assert len(fake_agent.calls[1]["message_history"]) == 2
        assert fake_agent.calls[1]["chat_history"] == [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "第一轮回复"},
            {"role": "user", "content": "继续"},
        ]


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


def test_build_runtime_history_compacts_intent_preview_tool_returns_even_when_short():
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
                    tool_name="preview_current_major_intent_confirmation",
                    args={},
                    tool_call_id="intent-preview",
                )
            ],
            model_name="test",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="preview_current_major_intent_confirmation",
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
                            "routingPath": "full_agent",
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


def test_chat_service_passes_runtime_history_but_persists_full_history(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    initial_history = []
    for index in range(18):
        initial_history.extend(
            [
                ModelRequest(parts=[UserPromptPart(content=f"历史问题 {index}")]),
                ModelResponse(parts=[TextPart(content=f"历史回答 {index}")], model_name="test"),
            ]
        )
    asyncio.run(store.save("session-runtime-history", initial_history))
    fake_agent = _FakeAgent(["短上下文回复"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        service.history_config.runtime_max_messages = 5
        reply = asyncio.run(service.handle_message("session-runtime-history", "user-1", "看看方案"))

    assert reply == "短上下文回复"
    assert len(fake_agent.calls) == 1
    assert fake_agent.calls[0]["message_history"] is not None
    assert len(fake_agent.calls[0]["message_history"]) == 5
    assert len(fake_agent.calls[0]["chat_history"]) <= 6
    stored = asyncio.run(store.load("session-runtime-history"))
    assert stored is not None
    assert len(stored) == len(initial_history) + 3
    assert any(
        isinstance(part, UserPromptPart) and part.content == "历史问题 0"
        for message in stored
        for part in getattr(message, "parts", [])
    )


def test_chat_service_uses_main_agent_as_single_dialog_entry(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgent(["intent popup by agent"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-2", "user-2", "不想去浙江"))

    assert reply == "intent popup by agent"
    assert len(fake_agent.calls) == 1
    assert fake_agent.calls[0]["user_prompt"] == "不想去浙江"


def test_chat_service_converts_structured_intent_preview_to_pending_confirmation_card(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    preview_payload = {
        "status": "ready",
        "sessionId": "990501",
        "title": "待确认偏好",
        "intentMode": "preference",
        "analysisStage": "confirmed",
        "items": [
            {
                "content": "偏好城市：北京",
                "value": {"city_intents": {"city": ["北京"]}},
                "selected": True,
            }
        ],
        "existingItems": [],
        "message": "待确认内容：偏好城市北京。",
    }
    fake_agent = _FakeIntentPreviewAgent(preview_payload)
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store(
        {
            "pendingId": "old-region-pending",
            "kind": "intent_change",
            "status": "active",
            "actionFamily": "apply_selected_intents",
            "summary": "排除地域：天津",
            "executionPayload": {
                "selectedData": {"selected": [{"city_intents": {"negative_province": ["天津"]}}]},
                "merged": {"city_intents": {"negative_province": ["天津"]}},
                "intentMode": "constraint",
                "batch": "01",
            },
        }
    )
    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "02"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message("990501", "user-1", "北京优先")
        )

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert reply.primary
    assert len(reply.followups) == 1
    card_payload = json.loads(reply.followups[0].content)
    assert card_payload["type"] == "pendingConfirmationCard"
    assert card_payload["kind"] == "intent_change"
    assert card_payload["actionFamily"] == "apply_selected_intents"
    assert "偏好地域：北京" in card_payload["summary"]
    assert pending_state["value"]["kind"] == "intent_change"
    assert pending_state["value"]["status"] == "active"
    assert pending_state["value"]["executionPayload"]["selectedData"]["selected"] == [
        {"city_intents": {"city": ["北京"]}}
    ]
    assert pending_state["value"]["executionPayload"]["batch"] == "02"
    assert pending_state["value"]["executionPayload"]["selectedData"]["batch"] == "02"


def test_chat_service_does_not_recover_only_keep_goal_when_agent_skips_tools(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgent([
        "我先把你要采用的内容列出来，点“采纳”前不会生效。\n\n"
        "你当前方案里没有临床医学。是否先确认把“临床医学”作为优先专业方向？"
    ])
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()
    backend_preview = _user_goal_fix_proposal_response(
        proposal_id="ug-only-keep-no-tool-1",
        strategy="only_keep_scope",
        source_version=24,
        title="只保留临床医学",
        summary="当前方案会围绕临床医学调整。",
        action_summaries=["移出不符合条件的志愿"],
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={
                "code": 0,
                "data": {
                    "phase": "ordered",
                    "version": 24,
                    "draftPlanState": {"summary": {"total": 45}},
                    "orderedPlanState": {"summary": {"total": 45}},
                    "reviewState": {"summary": {"warnCount": 0, "riskCount": 0}, "checks": []},
                },
            })), \
            patch("app.service.generate_user_goal_planning_fix_proposals", AsyncMock(return_value=backend_preview)) as proposal_mock, \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message("9905012-no-tool", "user-1", "我只想学临床医学，其他专业先不要")
        )

    assert isinstance(reply, str)
    assert "临床医学" in reply
    assert "是否先确认" not in reply
    assert "还没有生成可执行的调整内容" in reply
    assert pending_state == {}
    proposal_mock.assert_not_awaited()
    save_pending_mock.assert_not_awaited()


def test_chat_service_falls_back_to_intent_card_when_only_keep_plan_proposal_blocked(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgent(["这轮还没有生成可执行的调整内容，所以不会改动当前方案。"])
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()
    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={
                "code": 0,
                "data": {
                    "phase": "profile_ready",
                    "version": 673,
                    "draftPlanState": {"summary": {"total": 94}},
                    "orderedPlanState": {"summary": {"total": 94}},
                    "reviewState": {"summary": {"warnCount": 5, "riskCount": 3}, "checks": []},
                },
            })), \
            patch("app.service.generate_user_goal_planning_fix_proposals", AsyncMock()) as proposal_mock, \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message("9903101", "user-1", "我只想学临床医学，其他专业先不要")
    )

    assert isinstance(reply, str)
    assert "不会改动当前方案" in reply
    assert "不会写入后续报考参考" in reply
    assert pending_state == {}
    proposal_mock.assert_not_awaited()
    save_pending_mock.assert_not_awaited()


def test_chat_service_blocks_existing_only_intent_preview_when_turn_decision_missing_with_current_plan(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    existing_payload = {
        "status": "existing_only",
        "sessionId": "9905018",
        "title": "已在报考参考里",
        "intentMode": "constraint",
        "constraintIntentType": "only_keep",
        "analysisStage": "confirmed",
        "items": [],
        "existingItems": [
            {
                "content": "只保留专业：临床医学",
                "value": {"major_intents": {"level3": ["临床医学"]}},
                "selected": True,
            }
        ],
        "message": "这个想法当前已经在报考参考里，本轮不用重复采纳。",
    }
    fake_agent = _FakeIntentPreviewAgent(
        existing_payload,
        tool_name="preview_current_major_intent_confirmation",
    )
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch(
                "app.service.get_planning_workspace_state",
                AsyncMock(
                    return_value={
                        "code": 0,
                        "data": {
                            "version": 32,
                            "phase": "working",
                            "draftPlanState": {"summary": {"total": 45}},
                        },
                    }
                ),
            ), \
            patch("app.service.generate_user_goal_planning_fix_proposals", AsyncMock()) as proposal_mock, \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message("9905018", "user-1", "我只想学临床医学，其他专业先不要")
        )

    assert isinstance(reply, str)
    assert "结构化路由校验" in reply
    assert "不会创建待采纳意向卡" in reply
    _assert_no_pending_cards(reply)
    assert pending_state == {}
    proposal_mock.assert_not_awaited()
    save_pending_mock.assert_not_awaited()


def test_chat_service_existing_only_without_plan_explains_no_current_plan_to_adjust(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    existing_payload = {
        "status": "existing_only",
        "sessionId": "9905019",
        "title": "已在报考参考里",
        "intentMode": "constraint",
        "constraintIntentType": "only_keep",
        "analysisStage": "confirmed",
        "items": [],
        "existingItems": [
            {
                "content": "只保留专业：临床医学",
                "value": {"major_intents": {"level3": ["临床医学"]}},
                "selected": False,
            }
        ],
        "message": "这个想法当前已经在报考参考里，本轮不用重复采纳。",
    }
    fake_agent = _FakeIntentPreviewAgent(
        existing_payload,
        tool_name="preview_current_major_intent_confirmation",
    )
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch(
                "app.service.get_planning_workspace_state",
                AsyncMock(
                    return_value={
                        "code": 0,
                        "data": {
                            "version": 33,
                            "phase": "profile_ready",
                            "draftPlanState": {"summary": {"total": 0}},
                            "orderedPlanState": {"summary": {"total": 0}},
                            "candidatePoolState": {"summary": {"unitTotal": 0}},
                        },
                    }
                ),
            ), \
            patch("app.service.generate_user_goal_planning_fix_proposals", AsyncMock()) as proposal_mock, \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message("9905019", "user-1", "我只想学临床医学，其他专业先不要")
        )

    assert isinstance(reply, str)
    assert "已经记录过" in reply
    assert "当前记录：只保留专业：临床医学" in reply
    assert "还没有可调整的方案或候选结果" in reply
    assert "有方案后" in reply
    assert "有多匹配" not in reply
    assert pending_state == {}
    proposal_mock.assert_not_awaited()


def test_chat_service_blocks_intent_pending_when_turn_decision_missing_after_empty_preview(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgentWithToolCalls(
        "我这次还没准确整理出可调整的报考意向。你可以再明确说一下想保留、排除或更偏好的专业、院校、地域。",
        [
            ToolCallPart(
                tool_name="preview_current_intent_confirmation",
                args={},
                tool_call_id="budget-empty-intent",
            ),
        ],
        [
            ToolReturnPart(
                tool_name="preview_current_intent_confirmation",
                content=json.dumps({"status": "empty"}, ensure_ascii=False),
                tool_call_id="budget-empty-intent",
            ),
        ],
    )
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()
    backend_preview = _user_goal_fix_proposal_response(
        proposal_id="ug-budget-empty-intent",
        strategy="tuition_budget_scope",
        source_version=43,
        title="控制学费上限",
        summary="当前方案有学费偏高的志愿，已列出调整预览。",
        action_summaries=["处理学费偏高的志愿"],
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={
                "code": 0,
                "data": {
                    "phase": "reviewed",
                    "version": 43,
                    "draftPlanState": {"summary": {"total": 45}},
                    "orderedPlanState": {"summary": {"total": 45}},
                    "reviewState": {"summary": {"warnCount": 0, "riskCount": 0}, "checks": []},
                },
            })), \
            patch("app.service.generate_user_goal_planning_fix_proposals", AsyncMock(return_value=backend_preview)) as proposal_mock, \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message("tuition-budget-empty-intent-session", "user-1", "预算上限20000元")
        )

    assert isinstance(reply, str)
    assert "结构化路由校验" in reply
    assert "不会创建待采纳意向卡" in reply
    assert "调整预览" not in reply
    _assert_no_pending_cards(reply)
    assert pending_state == {}
    proposal_mock.assert_not_awaited()
    save_pending_mock.assert_not_awaited()


def test_chat_service_blocks_wrong_full_agent_intent_preview_when_turn_decision_missing(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    wrong_intent_payload = {
        "status": "ready",
        "sessionId": "tuition-budget-wrong-major-intent",
        "title": "好的，我先把这次你提到的要求整理一下。",
        "intentMode": "constraint",
        "constraintIntentType": "default",
        "analysisStage": "confirmed",
        "items": [
            {
                "content": "把中外合作办学记成明确不考虑的专业门类要求。",
                "value": {"major_intents": {"negative_level1": ["中外合作办学"]}},
                "selected": True,
            }
        ],
        "existingItems": [],
        "impactText": "",
        "impactAnalysis": {},
        "message": "",
    }
    fake_agent = _FakeAgentWithToolCalls(
        "已列出这次报考条件预览：排除专业门类：中外合作办学。\n\n点“采纳”前不会生效。",
        [
            ToolCallPart(
                tool_name="preview_current_major_intent_confirmation",
                args={
                    "major_intents": {"negative_level1": ["中外合作办学"]},
                    "intent_mode": "constraint",
                    "constraint_intent_type": "default",
                },
                tool_call_id="wrong-major-intent-budget",
            )
        ],
        [
            ToolReturnPart(
                tool_name="preview_current_major_intent_confirmation",
                content=json.dumps(wrong_intent_payload, ensure_ascii=False),
                tool_call_id="wrong-major-intent-budget",
            )
        ],
    )
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()
    backend_preview = _user_goal_fix_proposal_response(
        proposal_id="ug-budget-from-wrong-major-intent",
        strategy="tuition_budget_scope",
        source_version=47,
        title="控制学费上限",
        summary="当前方案有学费偏高的志愿，已列出调整预览。",
        action_summaries=["处理学费偏高的志愿"],
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={
                "code": 0,
                "data": {
                    "phase": "reviewed",
                    "version": 47,
                    "draftPlanState": {"summary": {"total": 45}},
                    "orderedPlanState": {"summary": {"total": 45}},
                    "reviewState": {"summary": {"warnCount": 0, "riskCount": 0}, "checks": []},
                },
            })), \
            patch("app.service.generate_user_goal_planning_fix_proposals", AsyncMock(return_value=backend_preview)) as proposal_mock, \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "tuition-budget-wrong-major-intent",
                "user-1",
                "太贵的学校别放了，学费最好控制在两万以内",
            )
        )

    assert isinstance(reply, str)
    assert "结构化路由校验" in reply
    assert "不会创建待采纳意向卡" in reply
    assert "排除专业门类" not in reply
    _assert_no_pending_cards(reply)
    assert pending_state == {}
    proposal_mock.assert_not_awaited()
    save_pending_mock.assert_not_awaited()


def test_chat_service_does_not_recover_toolless_exclude_goal_boundary_to_user_goal_proposal(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgent(["这轮还没有生成可执行的调整内容，所以不会改动当前方案。"])
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()
    backend_preview = _user_goal_fix_proposal_response(
        proposal_id="ug-toolless-exclude-english",
        strategy="exclude_scope",
        source_version=35,
        title="避开英语相关专业",
        summary="当前方案里有英语相关志愿，已生成替换或移出预览。",
        action_summaries=["移出或替换英语相关志愿"],
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={
                "code": 0,
                "data": {
                    "phase": "reviewed",
                    "version": 35,
                    "orderedPlanState": {"summary": {"total": 45}},
                    "reviewState": {"summary": {"warnCount": 0, "riskCount": 0}, "checks": []},
                },
            })), \
            patch("app.service.generate_user_goal_planning_fix_proposals", AsyncMock(return_value=backend_preview)) as proposal_mock, \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message("toolless-exclude-session", "user-1", "不要英语相关专业，当前方案里有的话也删掉")
    )

    assert isinstance(reply, str)
    assert "不会改动当前方案" in reply
    assert "不会写入后续报考参考" in reply
    assert pending_state == {}
    proposal_mock.assert_not_awaited()
    save_pending_mock.assert_not_awaited()


def test_chat_service_does_not_recover_toolless_only_keep_without_plan_to_intent_card(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgent(["这轮还没有生成可执行的调整内容，所以不会改动当前方案。"])
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={
                "code": 0,
                "data": {
                    "phase": "profile_ready",
                    "version": 0,
                    "orderedPlanState": {"summary": {"total": 0}},
                    "reviewState": {"summary": {"warnCount": 0, "riskCount": 0}, "checks": []},
                },
            })), \
            patch("app.service.generate_user_goal_planning_fix_proposals", AsyncMock()) as proposal_mock, \
            patch("app.service.classify_turn_decision", AsyncMock(return_value=_pending_conflict_turn_decision())), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message("toolless-no-plan-only-keep-session", "user-1", "不考虑工科，只考虑医学类")
        )

    assert isinstance(reply, str)
    assert "不会改动当前方案" in reply
    assert "不会写入后续报考参考" in reply
    assert pending_state == {}
    proposal_mock.assert_not_awaited()
    save_pending_mock.assert_not_awaited()


def test_chat_service_only_keep_region_preview_without_positive_scope_does_not_become_exclude_card(
    tmp_path,
    mock_llm_client,
):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    preview_payload = {
        "status": "ready",
        "sessionId": "9905015-missing-positive",
        "title": "待采纳报考条件",
        "intentMode": "constraint",
        "constraintIntentType": "only_keep",
        "analysisStage": "confirmed",
        "items": [
            {
                "content": "排除地域：北方",
                "value": {"city_intents": {"negative_area": ["北方"]}},
                "selected": True,
            }
        ],
        "existingItems": [],
        "message": "准备采纳：排除地域：北方",
    }
    fake_agent = _FakeIntentPreviewAgent(
        preview_payload,
        tool_name="preview_current_region_intent_confirmation",
    )
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message("9905015-missing-positive", "user-1", "孩子就想去南方，北方先别考虑")
        )

    assert isinstance(reply, str)
    assert "要保留的范围" in reply
    assert "排除地域：北方" not in reply
    assert pending_state.get("value") is None
    save_pending_mock.assert_not_awaited()


def test_chat_service_negative_only_region_constraint_creates_intent_pending_card(
    tmp_path,
    mock_llm_client,
):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    preview_payload = {
        "status": "ready",
        "sessionId": "5749",
        "title": "待确认地域要求",
        "intentMode": "constraint",
        "constraintIntentType": "default",
        "analysisStage": "confirmed",
        "items": [
            {
                "content": "把东北记成明确不考虑的地域要求，后面看候选和方案时都会按这个要求来。",
                "value": {"city_intents": {"negative_area": ["东北"]}},
                "selected": True,
            },
            {
                "content": "把西北记成明确不考虑的地域要求，后面看候选和方案时都会按这个要求来。",
                "value": {"city_intents": {"negative_area": ["西北"]}},
                "selected": True,
            },
        ],
        "existingItems": [],
    }
    fake_agent = _FakeIntentPreviewAgent(
        preview_payload,
        tool_name="preview_current_region_intent_confirmation",
    )
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()
    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message("5749", "user-1", "东北西北都不要，必须避开")
        )

    assert isinstance(reply, ChatServiceResponseEnvelope)
    card_payload = _assert_pending_card_envelope(
        reply,
        "",
        "apply_selected_intents",
        kind="intent_change",
    )
    assert "东北" in reply.primary
    assert "西北" in reply.primary
    assert "东北" in card_payload["summary"]
    assert "西北" in card_payload["summary"]
    assert card_payload["constraintIntentType"] == "default"
    pending = pending_state["value"]
    assert pending["kind"] == "intent_change"
    assert pending["executionPayload"]["selectedData"]["selected"] == [
        {"city_intents": {"negative_area": ["东北"]}},
        {"city_intents": {"negative_area": ["西北"]}},
    ]


def test_chat_service_intent_preview_card_drops_duplicate_primary_text(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    preview_payload = {
        "status": "ready",
        "sessionId": "9905011",
        "title": "待确认专业偏好",
        "intentMode": "preference",
        "analysisStage": "confirmed",
        "items": [
            {
                "content": "不优先专业：秘书学",
                "value": {"major_intents": {"negative_level3": ["秘书学"]}},
                "selected": True,
            }
        ],
        "impactAnalysis": {
            "intentMode": "preference",
            "currentPlanFit": ["现在这份方案里，和你这个想法不太一致的有：江苏第二师范学院第101组-秘书学（冲/江苏）"],
        },
    }
    fake_agent = _FakeAgentWithToolCalls(
        (
            "点击采纳后生效\n\n"
            "不优先专业：秘书学\n\n"
            "影响\n\n"
            "现在这份方案里，和你这个想法不太一致的有：江苏第二师范学院第101组-秘书学（冲/江苏）"
        ),
        [
            ToolCallPart(
                tool_name="preview_current_major_intent_confirmation",
                args={"major_intents": {"negative_level3": ["秘书学"]}, "intent_mode": "preference"},
                tool_call_id="intent-preview-duplicate-primary",
            )
        ],
        [
            ToolReturnPart(
                tool_name="preview_current_major_intent_confirmation",
                content=json.dumps(preview_payload, ensure_ascii=False),
                tool_call_id="intent-preview-duplicate-primary",
            )
        ],
    )
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("9905011", "user-1", "不太想学秘书"))

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert reply.primary
    assert len(reply.followups) == 1
    card_payload = json.loads(reply.followups[0].content)
    assert card_payload["type"] == "pendingConfirmationCard"
    assert card_payload["summary"] == "不优先专业：秘书学"
    assert "不优先专业：秘书学" in card_payload["content"]
    assert "适当靠后" in card_payload["impact"]
    assert "江苏第二师范学院第101组-秘书学" in card_payload["impact"]
    assert pending_state["value"]["summary"] == "不优先专业：秘书学"
    saved_history = asyncio.run(store.load("9905011"))
    saved_text = next(part.content for part in saved_history[-1].parts if isinstance(part, TextPart))
    assert saved_text == ""


def test_chat_service_intent_pending_card_summarizes_all_major_levels_and_existing_items(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    preview_payload = {
        "status": "ready",
        "sessionId": "990502",
        "title": "待确认偏好",
        "intentMode": "preference",
        "analysisStage": "confirmed",
        "items": [
            {
                "content": "偏好专业类：经济学",
                "value": {"major_intents": {"level2": ["经济学"]}},
                "selected": True,
            },
            {
                "content": "排除专业门类：医学",
                "value": {"major_intents": {"negative_level1": ["医学"]}},
                "selected": True,
            },
        ],
        "existingItems": [
            {
                "content": "当前已有参考偏好专业：法学",
                "value": {"major_intents": {"level3": ["法学", "财政学"]}},
                "selected": True,
            },
            {
                "content": "当前已有参考排除专业：护理学",
                "value": {"major_intents": {"negative_level3": ["护理学"]}},
                "selected": True,
            },
        ],
        "message": "待确认内容：偏好专业类经济学，排除医学。",
    }
    fake_agent = _FakeIntentPreviewAgent(
        preview_payload,
        tool_name="preview_current_major_intent_confirmation",
    )
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store(
        {
            "pendingId": "old-region-pending",
            "kind": "intent_change",
            "status": "active",
            "actionFamily": "apply_selected_intents",
            "summary": "排除地域：天津",
            "executionPayload": {
                "selectedData": {"selected": [{"city_intents": {"negative_province": ["天津"]}}]},
                "merged": {"city_intents": {"negative_province": ["天津"]}},
                "intentMode": "constraint",
                "batch": "01",
            },
        }
    )
    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message("990502", "user-1", "我倾向法学和财政学，但护理不要")
        )

    assert isinstance(reply, ChatServiceResponseEnvelope)
    card_payload = json.loads(reply.followups[0].content)
    assert card_payload["summary"] == "偏好专业类：经济学；不优先专业门类：医学"
    assert "点击采纳后生效" not in card_payload["content"]
    assert "- 偏好专业类：经济学" in card_payload["content"]
    assert "- 不优先专业门类：医学" in card_payload["content"]
    assert "当前已有参考：" in card_payload["content"]
    assert "- 偏好专业：法学、财政学" in card_payload["content"]
    assert "- 不优先专业：护理学" in card_payload["content"]
    assert pending_state["value"]["summary"] == "偏好专业类：经济学；不优先专业门类：医学"
    assert pending_state["value"]["executionPayload"]["merged"] == {
        "major_intents": {"level2": ["经济学"], "negative_level1": ["医学"]}
    }


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
        ModelResponse(parts=[ToolCallPart(tool_name="preview_current_major_intent_confirmation", args={}, tool_call_id="intent-1")]),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="preview_current_major_intent_confirmation",
                    content=json.dumps(first_payload, ensure_ascii=False),
                    tool_call_id="intent-1",
                )
            ]
        ),
        ModelRequest(parts=[UserPromptPart(content="会计也行")]),
        ModelResponse(parts=[ToolCallPart(tool_name="preview_current_major_intent_confirmation", args={}, tool_call_id="intent-2")]),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="preview_current_major_intent_confirmation",
                    content=json.dumps(latest_payload, ensure_ascii=False),
                    tool_call_id="intent-2",
                )
            ]
        ),
    ]

    assert _extract_recent_intent_analysis_payload(history) == latest_payload


def test_chat_service_injects_recent_intent_payload_into_request_context(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    recent_payload = {
        "status": "existing_only",
        "sessionId": "session-recent-intent",
        "items": [],
        "existingItems": [
            {"content": "当前已有参考偏好具体专业：会计学", "value": {"major_intents": {"level3": ["会计学"]}}},
        ],
    }
    asyncio.run(
        store.save(
            "session-recent-intent",
            [
                ModelRequest(parts=[UserPromptPart(content="我倾向会计学")]),
                ModelResponse(parts=[ToolCallPart(tool_name="preview_current_major_intent_confirmation", args={}, tool_call_id="intent-existing")]),
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name="preview_current_major_intent_confirmation",
                            content=json.dumps(recent_payload, ensure_ascii=False),
                            tool_call_id="intent-existing",
                        )
                    ]
                ),
                ModelResponse(parts=[TextPart(content="这个想法当前已经在后续报考参考里。")]),
            ],
        )
    )
    fake_agent = _FakeAgent(["我会结合当前方案看这个偏好。"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-recent-intent", "user-57", "看看这个偏好会影响当前方案吗"))

    assert reply == "我会结合当前方案看这个偏好。"
    assert fake_agent.calls[0]["chat_history"][-1] == {"role": "user", "content": "看看这个偏好会影响当前方案吗"}
    assert fake_agent.calls[0]["recent_intent_analysis"] == recent_payload


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


def test_chat_service_emits_initial_progress_when_full_agent_is_silent(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeSlowAgent("先看大方向可以。", delay_seconds=0.03)

    async def _run():
        with patch("app.service.ChatAgent", return_value=fake_agent), \
                patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
                patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
                patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
            service = ChatService(mock_llm_client, store)
            service._INITIAL_PROGRESS_DELAY_SECONDS = 0.01
            hints: list[str] = []

            async def on_progress(hint: str) -> None:
                hints.append(hint)

            reply = await service.handle_message(
                "session-slow-initial-progress",
                "user-1",
                "今天先看大方向",
                on_progress=on_progress,
            )
            return reply, hints

    reply, hints = asyncio.run(_run())

    assert reply == "先看大方向可以。"
    assert hints == ["正在理解你的问题，并结合当前信息整理回答..."]


def test_chat_service_emits_context_progress_when_context_loading_is_slow(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeSlowAgent("先看大方向可以。", delay_seconds=0.03)

    async def slow_score_detail(_session_id):
        await asyncio.sleep(0.03)
        return {"code": 1}

    async def _run():
        with patch("app.service.ChatAgent", return_value=fake_agent), \
                patch("app.service.get_user_score_detail", AsyncMock(side_effect=slow_score_detail)), \
                patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
                patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
            service = ChatService(mock_llm_client, store)
            service._EARLY_CONTEXT_PROGRESS_DELAY_SECONDS = 0.005
            service._INITIAL_PROGRESS_DELAY_SECONDS = 0.005
            hints: list[str] = []

            async def on_progress(hint: str) -> None:
                hints.append(hint)

            reply = await service.handle_message(
                "session-slow-context-progress",
                "user-1",
                "今天先看大方向",
                on_progress=on_progress,
            )
            return reply, hints

    reply, hints = asyncio.run(_run())

    assert reply == "先看大方向可以。"
    assert hints[:2] == [
        "正在读取当前会话信息...",
        "正在理解你的问题，并结合当前信息整理回答...",
    ]


def test_chat_service_emits_context_progress_when_pending_state_loading_is_slow(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeSlowAgent("先看大方向可以。", delay_seconds=0.03)

    async def slow_pending_state(_session_id):
        await asyncio.sleep(0.03)
        return None

    async def _run():
        with patch("app.service.ChatAgent", return_value=fake_agent), \
                patch("app.service._load_pending_confirmation_state", AsyncMock(side_effect=slow_pending_state)), \
                patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
                patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
                patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
            service = ChatService(mock_llm_client, store)
            service._EARLY_CONTEXT_PROGRESS_DELAY_SECONDS = 0.005
            service._INITIAL_PROGRESS_DELAY_SECONDS = 0.005
            hints: list[str] = []

            async def on_progress(hint: str) -> None:
                hints.append(hint)

            reply = await service.handle_message(
                "session-slow-pending-progress",
                "user-1",
                "今天先看大方向",
                on_progress=on_progress,
            )
            return reply, hints

    reply, hints = asyncio.run(_run())

    assert reply == "先看大方向可以。"
    assert hints[:2] == [
        "正在读取当前会话信息...",
        "正在理解你的问题，并结合当前信息整理回答...",
    ]


def test_chat_service_does_not_duplicate_initial_progress_after_tool_progress(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeSlowAgent(
        "专业对比结果。",
        delay_seconds=0.03,
        emit_tool_progress=True,
    )

    async def _run():
        with patch("app.service.ChatAgent", return_value=fake_agent), \
                patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
                patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
                patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
            service = ChatService(mock_llm_client, store)
            service._INITIAL_PROGRESS_DELAY_SECONDS = 0.01
            hints: list[str] = []

            async def on_progress(hint: str) -> None:
                hints.append(hint)

            await service.handle_message(
                "session-tool-progress-no-dup",
                "user-1",
                "汉语言和历史哪个更稳一点",
                on_progress=on_progress,
            )
            return hints

    hints = asyncio.run(_run())

    assert hints == ["正在对比这几个专业的差异..."]


def test_chat_service_emits_long_running_progress_for_slow_full_agent(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeSlowAgent("这轮分析完成。", delay_seconds=0.05)

    async def _run():
        with patch("app.service.ChatAgent", return_value=fake_agent), \
                patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
                patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
                patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
            service = ChatService(mock_llm_client, store)
            service._INITIAL_PROGRESS_DELAY_SECONDS = 0.005
            service._LONG_PROGRESS_MODEL_WAIT_HINTS = (
                (0.02, "还在分析你的问题，正在整理可用信息，请稍等..."),
            )
            service._LONG_PROGRESS_TOOL_HINTS = ()
            service._MIN_PROGRESS_INTERVAL_SECONDS = 0.005
            hints: list[str] = []

            async def on_progress(hint: str) -> None:
                hints.append(hint)

            await service.handle_message(
                "session-slow-long-progress",
                "user-1",
                "帮我看看这版方案对考公的支撑",
                on_progress=on_progress,
            )
            return hints

    hints = asyncio.run(_run())

    assert hints == [
        "正在理解你的问题，并结合当前信息整理回答...",
        "还在分析你的问题，正在整理可用信息，请稍等...",
    ]


def test_chat_service_uses_tool_long_progress_after_tool_progress(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeSlowAgent(
        "专业对比结果。",
        delay_seconds=0.05,
        emit_tool_progress=True,
    )

    async def _run():
        with patch("app.service.ChatAgent", return_value=fake_agent), \
                patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
                patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
                patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
            service = ChatService(mock_llm_client, store)
            service._INITIAL_PROGRESS_DELAY_SECONDS = 0.005
            service._LONG_PROGRESS_MODEL_WAIT_HINTS = (
                (0.02, "还在分析你的问题，正在整理可用信息，请稍等..."),
            )
            service._LONG_PROGRESS_TOOL_HINTS = (
                (0.02, "还在处理，这轮需要结合当前信息整理结论，请稍等..."),
            )
            service._MIN_PROGRESS_INTERVAL_SECONDS = 0.005
            hints: list[str] = []

            async def on_progress(hint: str) -> None:
                hints.append(hint)

            await service.handle_message(
                "session-slow-tool-long-progress",
                "user-1",
                "汉语言和历史哪个更稳一点",
                on_progress=on_progress,
            )
            return hints

    hints = asyncio.run(_run())

    assert hints == [
        "正在对比这几个专业的差异...",
        "还在处理，这轮需要结合当前信息整理结论，请稍等...",
    ]


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


def test_chat_service_appends_workspace_refresh_after_review_tool_call(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgentWithToolCalls(
        "已完成当前方案审查。",
        [ToolCallPart(tool_name="run_planning_review", args={})],
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-review-1", "user-review-1", "帮我审查一下"))

    assert reply == "已完成当前方案审查。"


def test_chat_service_does_not_append_workspace_refresh_for_non_review_planning_query(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgentWithToolCalls(
        "这是当前方案的完整状态概览。",
        [ToolCallPart(tool_name="query_planning_plan_overview", args={})],
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-review-2", "user-review-2", "方案有了么"))

    assert reply == "这是当前方案的完整状态概览。"


def test_chat_service_requires_card_click_for_pending_intent_on_short_confirm(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    asyncio.run(store.save("session-intent-direct-confirm", []))
    fake_agent = _FakeAgent(["我会重新确认你想采纳哪条想法，再列出来让你采纳。"])
    intent_result = json.dumps(
        {
            "action": "confirm",
            "sessionId": "session-intent-direct-confirm",
            "intentMode": "preference",
            "applied": True,
            "messageCode": "preference_applied",
            "message": "好的，我记下来了。接下来如果你愿意，我可以继续帮你看看现在这份方案哪些地方比较贴近你的想法、哪些地方还可以再优化。",
        },
        ensure_ascii=False,
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service._apply_selected_intents", AsyncMock(return_value=intent_result)) as update_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-intent-direct-confirm", "user-1", "确认"))

    _assert_no_pending_confirmation_guard(reply)
    update_mock.assert_not_awaited()
    assert fake_agent.calls == []


def test_chat_service_does_not_apply_pending_intent_directly_for_plan_specific_confirm_phrase(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgent(["模型继续处理"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service._apply_selected_intents", AsyncMock()) as update_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-intent-direct-confirm-2", "user-1", "确认生成"))

    _assert_no_pending_confirmation_guard(reply)
    update_mock.assert_not_awaited()
    assert fake_agent.calls == []


def test_chat_service_does_not_apply_stale_pending_intent_after_readonly_plan_query(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    asyncio.run(
        store.save(
            "session-intent-stale-after-readonly",
            [
                ModelRequest(parts=[UserPromptPart(content="想重点看看北京的法学")]),
                ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="preview_current_major_intent_confirmation",
                            args={"intent_mode": "preference"},
                            tool_call_id="intent-preview-1",
                        )
                    ],
                    model_name="test-model",
                ),
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name="preview_current_major_intent_confirmation",
                            content="我先把北京法学整理成待确认偏好。",
                            tool_call_id="intent-preview-1",
                        )
                    ]
                ),
                ModelResponse(parts=[TextPart(content="我先整理成待确认偏好，确认前不会生效。")], model_name="test-model"),
                ModelRequest(parts=[UserPromptPart(content="当前方案里青岛城市学院相关机会是不是很多，先查一下不要改")]),
                ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="query_volunteer_plan",
                            args={"query": "青岛城市学院", "scope": "plan"},
                            tool_call_id="query-plan-1",
                        )
                    ],
                    model_name="test-model",
                ),
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name="query_volunteer_plan",
                            content="当前方案里命中了 2 条和青岛城市学院相关的志愿。",
                            tool_call_id="query-plan-1",
                        )
                    ]
                ),
                ModelResponse(parts=[TextPart(content="当前方案里确实有 2 条相关机会，这轮只是查询，没有改方案。")], model_name="test-model"),
            ],
        )
    )
    fake_agent = _FakeAgent(["我会重新确认你要采纳的想法，再列出来让你采纳。"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service._apply_selected_intents", AsyncMock()) as update_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-intent-stale-after-readonly", "user-1", "确认"))

    _assert_no_pending_confirmation_guard(reply)
    update_mock.assert_not_awaited()
    assert fake_agent.calls == []


def test_chat_service_requires_card_click_for_pending_intent_when_latest_turn_is_intent_preview(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    asyncio.run(
        store.save(
            "session-intent-latest-preview",
            [
                ModelRequest(parts=[UserPromptPart(content="想重点看看北京的法学")]),
                ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="preview_current_major_intent_confirmation",
                            args={"intent_mode": "preference"},
                            tool_call_id="intent-preview-2",
                        )
                    ],
                    model_name="test-model",
                ),
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name="preview_current_major_intent_confirmation",
                            content="我先把北京法学整理成待确认偏好。",
                            tool_call_id="intent-preview-2",
                        )
                    ]
                ),
                ModelResponse(parts=[TextPart(content="我先整理成待确认偏好，确认前不会生效。")], model_name="test-model"),
            ],
        )
    )
    fake_agent = _FakeAgent(["不应该调用模型"])
    intent_result = json.dumps(
        {
            "action": "confirm",
            "sessionId": "session-intent-latest-preview",
            "intentMode": "preference",
            "applied": True,
            "messageCode": "preference_applied",
            "message": "好的，我记下来了。",
        },
        ensure_ascii=False,
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service._apply_selected_intents", AsyncMock(return_value=intent_result)) as update_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-intent-latest-preview", "user-1", "确认"))

    _assert_no_pending_confirmation_guard(reply)
    update_mock.assert_not_awaited()
    assert fake_agent.calls == []


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
    assert "还没有生成可执行的调整内容" in guarded
    assert "确认当前有效预览后才会执行" in guarded


def test_chat_service_guards_toolless_plan_confirm_copy_without_card(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_reply = (
        "已在当前方案里定位到**“汉语言文学”相关的 17 条志愿**。\n\n"
        "**确认后会执行以下操作：**\n"
        "1. 将上述 17 条汉语言文学志愿从当前方案中移除\n"
        "2. 把“排除汉语言文学”写入后续报考参考\n\n"
        "点击确认后生效，你确认要删除吗？"
    )
    fake_agent = _FakeAgent([fake_reply])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_pending_confirmation", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-toolless-plan-confirm-copy", "user-1", "删掉方案里面的汉语言文学"))

    assert isinstance(reply, str)
    assert "汉语言文学" in reply
    assert "点击确认后生效" not in reply
    assert "你确认要删除吗" not in reply
    assert "还没有生成可执行的调整内容" in reply
    saved_history = asyncio.run(store.load("session-toolless-plan-confirm-copy"))
    assert saved_history is not None
    saved_text = next(part.content for part in saved_history[-1].parts if isinstance(part, TextPart))
    assert saved_text == reply


def test_chat_service_guards_toolless_add_volunteer_confirm_copy_without_card(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_reply = (
        "已为你整理好把武汉大学-计算机科学与技术加入当前方案的调整内容。\n\n"
        "这次会把该志愿加入方案，并保持其他志愿顺序不变。确认加入方案吗？"
    )
    fake_agent = _FakeAgent([fake_reply])
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.save_pending_confirmation", save_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "session-toolless-add-volunteer-confirm-copy",
                "user-1",
                "把武汉大学计算机科学与技术加到方案里",
            )
        )

    assert isinstance(reply, str)
    assert "武汉大学" in reply
    assert "确认加入方案吗" not in reply
    assert "确认后" not in reply
    assert "还没有生成可执行的调整内容" in reply
    assert pending_state == {}
    save_pending_mock.assert_not_awaited()
    saved_history = asyncio.run(store.load("session-toolless-add-volunteer-confirm-copy"))
    assert saved_history is not None
    saved_text = next(part.content for part in saved_history[-1].parts if isinstance(part, TextPart))
    assert saved_text == reply


def test_chat_service_preserves_readonly_explore_analysis_when_plan_confirm_copy_is_unbacked(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_reply = (
        "先看方向分析：当前方案已经有一些体制内承接，但专业结构还可以更聚焦。\n\n"
        "如果你确认，我会执行调整并把相关志愿往前排。"
    )
    fake_agent = _FakeAgentWithToolCalls(
        fake_reply,
        [
            ToolCallPart(
                tool_name="analyze_current_career_direction",
                args={"career_directions": ["system_public_service"]},
                tool_call_id="career-direction-call",
            )
        ],
        [
            ToolReturnPart(
                tool_name="analyze_current_career_direction",
                content="这轮只做分析，不会改动你的方案。",
                tool_call_id="career-direction-call",
            )
        ],
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_pending_confirmation", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-readonly-explore-plan-copy", "user-1", "先看怎么更偏体制内，不要直接改"))

    assert "先看方向分析" in reply
    assert "体制内承接" in reply
    assert "执行调整" not in reply
    assert "还没有生成可执行的调整内容" not in reply
    assert "不会改动当前方案" in reply
    saved_history = asyncio.run(store.load("session-readonly-explore-plan-copy"))
    assert saved_history is not None
    saved_text = next(part.content for part in saved_history[-1].parts if isinstance(part, TextPart))
    assert saved_text == reply


def test_chat_service_sanitizes_internal_terms_before_reply_and_history_save(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_reply = (
        "从分析结果来看，当前有三类替换方向，但系统能直接执行的只有中外合作办学这一项。"
        "另外两类目前被系统阻塞了，阻塞原因：替换会改变专业组数量，系统暂不支持自动确认。"
        "这条属于硬要求，需要生成确认卡片，状态是 preview_only。"
    )
    fake_agent = _FakeAgent([fake_reply])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_pending_confirmation", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-internal-terms-sanitize", "user-1", "怎么替换"))

    assert isinstance(reply, str)
    forbidden_terms = ("系统阻塞", "阻塞原因", "系统暂不支持", "自动确认", "硬要求", "确认卡片", "preview_only")
    for term in forbidden_terms:
        assert term not in reply
    assert "当前不建议直接确认" in reply
    assert "需要注意" in reply
    assert "待采纳内容" in reply

    saved_history = asyncio.run(store.load("session-internal-terms-sanitize"))
    assert saved_history is not None
    saved_text = next(part.content for part in saved_history[-1].parts if isinstance(part, TextPart))
    assert saved_text == reply
    for term in forbidden_terms:
        assert term not in saved_text


def test_chat_service_falls_back_to_readonly_explore_tool_result_when_model_confirmation_copy_has_no_analysis(
    tmp_path,
    mock_llm_client,
):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_reply = "如果你确认，我会执行调整并把相关志愿往前排。"
    fake_agent = _FakeAgentWithToolCalls(
        fake_reply,
        [
            ToolCallPart(
                tool_name="analyze_current_career_direction",
                args={"career_directions": ["system_public_service"]},
                tool_call_id="career-direction-call",
            )
        ],
        [
            ToolReturnPart(
                tool_name="analyze_current_career_direction",
                content="当前方案对体制内方向有一定承接，可以重点看法学、财政学和汉语言文学。",
                tool_call_id="career-direction-call",
            )
        ],
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_pending_confirmation", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-readonly-explore-tool-fallback", "user-1", "先看怎么更偏体制内，不要直接改"))

    assert "当前方案对体制内方向有一定承接" in reply
    assert "执行调整" not in reply
    assert "不会改动当前方案" in reply


def test_chat_service_preserves_readonly_policy_reply_when_plan_confirm_copy_is_unbacked(
    tmp_path,
    mock_llm_client,
):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    bad_reply = (
        "孩子还没参与时，建议先把方案风险、专业兴趣和家庭底线分开确认。"
        "后面可以让孩子逐条看专业方向、地域和费用，最后再定最终填报口径。"
        "如果你确认，我会按这个流程更新方案。"
    )
    fake_agent = _FakeAgentWithToolCalls(
        bad_reply,
        [
            ToolCallPart(
                tool_name="answer_admission_policy_question",
                args={"question": "孩子本人还没参与，后面怎么补确认"},
                tool_call_id="policy-readonly-call",
            )
        ],
        [
            ToolReturnPart(
                tool_name="answer_admission_policy_question",
                content=json.dumps(
                    {
                        "result_kind": "admission_policy_consultation",
                        "reply": "孩子还没参与时，建议先让孩子看专业方向、地域、费用和风险承受度，再把家庭意见和孩子意见合在一起定最终方案。",
                    },
                    ensure_ascii=False,
                ),
                tool_call_id="policy-readonly-call",
            )
        ],
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_pending_confirmation", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-readonly-policy-plan-copy", "user-1", "孩子本人还没参与，后面怎么补确认"))

    assert isinstance(reply, str)
    assert "孩子还没参与" in reply
    assert "专业方向" in reply
    assert "确认，我会按这个流程更新方案" not in reply
    assert "这轮还没有生成可执行的调整内容" not in reply


def test_chat_service_recovers_batch_line_risk_policy_reply_from_boundary_only_misroute(
    tmp_path,
    mock_llm_client,
):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgent([
        "这轮不会改动当前方案，也不会写入后续报考参考里的偏好或要求。"
    ])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_pending_confirmation", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "session-batch-line-risk-policy",
                "user-1",
                "分数刚压本科线，别给我画大饼",
            )
        )

    assert isinstance(reply, str)
    assert "本科线" in reply
    assert "压线" in reply
    assert "风险" in reply
    assert "保本科" in reply or "保底" in reply or "兜底" in reply
    assert "民办" in reply
    assert "专科" in reply
    assert "不会写入后续报考参考" not in reply
    assert fake_agent.calls


def test_chat_service_downgrades_major_group_keep_safest_from_career_intent_preview(
    tmp_path,
    mock_llm_client,
):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    intent_payload = {
        "status": "ready",
        "sessionId": "session-major-group-keep-safest",
        "title": "待确认发展方向",
        "intentMode": "preference",
        "analysisStage": "confirmed",
        "items": [
            {
                "content": "发展方向：稳定就业导向",
                "value": {"career_intents": {"positive": ["stable_employment"]}},
                "selected": True,
            }
        ],
        "existingItems": [],
    }
    fake_agent = _FakeAgentWithToolCalls(
        "我已整理成待采纳内容：发展方向：稳定就业导向。点击采纳后会写入后续报考参考。",
        [
            ToolCallPart(
                tool_name="preview_current_career_intent_confirmation",
                args={"career_intents": {"positive": ["stable_employment"]}},
                tool_call_id="career-intent-preview-for-major-group",
            )
        ],
        [
            ToolReturnPart(
                tool_name="preview_current_career_intent_confirmation",
                content=json.dumps(intent_payload, ensure_ascii=False),
                tool_call_id="career-intent-preview-for-major-group",
            )
        ],
    )
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "session-major-group-keep-safest",
                "user-1",
                "专业组里只保留最稳的专业行不行",
            )
        )

    assert isinstance(reply, str)
    assert "专业组" in reply
    assert "专业" in reply
    assert "最稳" in reply or "更稳" in reply or "安全垫" in reply
    assert "风险" in reply
    assert "调剂" in reply
    assert "稳定就业导向" not in reply
    assert "写入后续报考参考" not in reply
    assert pending_state == {}
    save_pending_mock.assert_not_awaited()


def test_chat_service_preserves_interest_stage_intent_tool_reply_when_unbacked_plan_copy_has_no_analysis(
    tmp_path,
    mock_llm_client,
):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgentWithToolCalls(
        "如果你确认，我会把医学护理都从方案里移出。",
        [
            ToolCallPart(
                tool_name="preview_current_major_intent_confirmation",
                args={"analysis_stage": "interest"},
                tool_call_id="major-interest-stage-call",
            )
        ],
        [
            ToolReturnPart(
                tool_name="preview_current_major_intent_confirmation",
                content=json.dumps(
                    {
                        "analysisStage": "interest",
                        "reply_strategy": "continue_model",
                        "message": "中医一般也属于医学相关方向，但和护理、临床医学的培养目标不一样；如果你是想避开护理和临床，需要单独说明中医是否也要避开。",
                    },
                    ensure_ascii=False,
                ),
                tool_call_id="major-interest-stage-call",
            )
        ],
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_pending_confirmation", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-interest-stage-major-boundary", "user-1", "医学护理都别碰，但中医到底算不算"))

    assert isinstance(reply, str)
    assert "中医" in reply
    assert "护理" in reply
    assert "临床医学" in reply
    assert "移出" not in reply
    assert "这轮还没有生成可执行的调整内容" not in reply
    assert "不会改动当前方案" in reply


def test_chat_service_no_pending_confirmation_flows_to_agent(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgent(["我会重新确认你想处理哪部分内容。"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_pending_confirmation", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})) as score_mock, \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})) as profile_mock, \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})) as workspace_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-no-pending-confirm", "user-1", "确认"))

    _assert_no_pending_confirmation_guard(reply)
    assert fake_agent.calls == []
    score_mock.assert_awaited_once()
    profile_mock.assert_awaited_once()
    workspace_mock.assert_awaited_once()
    saved_history = asyncio.run(store.load("session-no-pending-confirm"))
    assert saved_history is not None
    assert len(saved_history) >= 2


def test_chat_service_blocks_colloquial_plan_confirmation_without_pending_action(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgent(["继续生成补充预览。"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_pending_confirmation", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})) as score_mock, \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})) as profile_mock, \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})) as workspace_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-no-pending-colloquial-confirm", "user-1", "嗯可以"))

    _assert_no_pending_confirmation_guard(reply)
    assert fake_agent.calls == []
    score_mock.assert_awaited_once()
    profile_mock.assert_awaited_once()
    workspace_mock.assert_awaited_once()


def test_chat_service_routes_colloquial_review_followup_to_agent_without_pending_action(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    asyncio.run(
        store.save(
            "session-review-followup-no-pending",
            [
                ModelRequest(parts=[UserPromptPart(content="方案怎么处理")]),
                ModelResponse(
                    parts=[
                        TextPart(
                            content=(
                                "据当前方案审查结果，有 3 项处理建议，其中能直接预览的是：\n\n"
                                "1. 补充本省保底志愿（可预览）\n"
                                "如果你希望先处理本省保底不足的问题，我可以生成补充预览，确认后再加入方案。你确认要看吗？\n\n"
                                "先说明一下：我还没有拿到可执行的调整预览，所以这一步不会因为你回复“确认”就直接改方案。"
                            )
                        )
                    ],
                    model_name="test-model",
                ),
            ],
        )
    )
    fake_agent = _FakeAgent(["我先继续定位本省保底可补入的志愿，并给你一版调整预览。"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_pending_confirmation", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})) as score_mock, \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})) as profile_mock, \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})) as workspace_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-review-followup-no-pending", "user-1", "可以"))

    _assert_no_pending_confirmation_guard(reply)
    assert fake_agent.calls == []
    score_mock.assert_awaited_once()
    profile_mock.assert_awaited_once()
    workspace_mock.assert_awaited_once()


def test_chat_service_routes_no_pending_intent_confirmation_to_intent_guard(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgent(["不应该调用模型"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_pending_confirmation", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})) as score_mock, \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})) as profile_mock, \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})) as workspace_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-no-pending-intent-confirm", "user-1", "确认这个偏好"))

    _assert_no_pending_confirmation_guard(reply)
    assert fake_agent.calls == []
    score_mock.assert_awaited_once()
    profile_mock.assert_awaited_once()
    workspace_mock.assert_awaited_once()


def test_chat_service_short_ack_after_readonly_turn_does_not_call_agent(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    history = [
        ModelRequest(parts=[UserPromptPart(content="新媒体和跨电哪个更适合数学不太好的，先说说")]),
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="analyze_current_major_interest",
                    args={},
                    tool_call_id="major-compare-via-interest",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="analyze_current_major_interest",
                    content=json.dumps(
                        {
                            "reply_strategy": "continue_model",
                            "analysis_kind": "major_compare",
                            "message": "专业对比事实。",
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="major-compare-via-interest",
                )
            ]
        ),
        ModelResponse(parts=[TextPart(content="先按专业对比给你分析，不会记录偏好。")], model_name="test-model"),
    ]
    asyncio.run(store.save("session-readonly-short-ack", history))
    fake_agent = _FakeAgent(["不应该调用模型"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service._log_conversation_turn_event") as log_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-readonly-short-ack", "user-1", "嗯那就这样"))

    assert "先按刚才的分析结论理解" in reply
    assert "没有待确认的偏好或方案动作" in reply
    assert "不会改动方案" in reply
    assert fake_agent.calls == []
    assert log_mock.call_args.kwargs["routingPath"] == "readonly_closure_ack"


def test_chat_service_requires_card_click_for_intent_text_confirmation_when_intent_cache_exists(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgent(["不应该调用模型"])
    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service._apply_selected_intents", AsyncMock()) as update_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-intent-pending-confirm", "user-1", "确认"))

    _assert_no_pending_confirmation_guard(reply)
    update_mock.assert_not_awaited()
    assert fake_agent.calls == []


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


def test_chat_service_ignores_historical_intent_preview_for_query_state_workspace_refresh(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    history = [
        ModelRequest(parts=[UserPromptPart(content="我想学网络与新媒体")]),
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="preview_current_major_intent_confirmation",
                    args={},
                    tool_call_id="intent-call-1",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="preview_current_major_intent_confirmation",
                    content="{}",
                    tool_call_id="intent-call-1",
                )
            ]
        ),
        ModelResponse(parts=[TextPart(content="我先整理一下这个偏好。")], model_name="test-model"),
    ]
    asyncio.run(store.save("session-plan-state-old-intent", history))
    fake_agent = _FakeAgentWithToolCalls(
        "这是当前方案状态。",
        [
            ToolCallPart(
                tool_name="query_plan",
                args={"scope": "summary"},
            )
        ],
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-plan-state-old-intent", "user-1", "现在方案怎么样"))

    assert reply == "这是当前方案状态。"


def test_chat_service_keeps_natural_markdown_but_removes_forced_choice(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgentWithToolCalls(
        "**方案已经有了！**\n\n- 30个志愿已生成\n- 当前可以继续审查风险\n\n你现在必须决定：选哪个？",
        [
            ToolCallPart(
                tool_name="query_plan",
                args={"scope": "summary"},
            )
        ],
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-plan-style-1", "user-1", "方案有了么"))

    assert "**方案已经有了！**" in reply
    assert "- 30个志愿已生成" in reply
    assert "选哪个" not in reply
    assert "必须决定" not in reply
    saved_history = asyncio.run(store.load("session-plan-style-1"))
    assert saved_history is not None
    saved_text = next(part.content for part in saved_history[-1].parts if isinstance(part, TextPart))
    assert saved_text == reply


def test_chat_service_allows_query_volunteer_plan_natural_headings(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgentWithToolCalls(
        "候选池里没有计算机相关志愿了。\n\n**可能的原因**\n\n当前筛选条件较窄。\n\n**建议**\n\n可以考虑其他方向。",
        [
            ToolCallPart(
                tool_name="query_volunteer_plan",
                args={"query": "候选里看看计算机", "scope": "candidate"},
            )
        ],
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-plan-query-style", "user-1", "候选里看看计算机"))

    assert "**可能的原因**" in reply
    assert "**建议**" in reply
    assert "当前筛选条件较窄" in reply


def test_chat_service_basic_plan_status_uses_current_planning_summary(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgent(["历史里旧冲突：广西师范大学生物科学还在。"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch(
                "app.service.get_planning_workspace_state",
                AsyncMock(
                    return_value={
                        "code": 0,
                        "data": {
                            "phase": "reviewed",
                            "draftPlanState": {"summary": {"unitTotal": 45, "targetUnitCount": 45}},
                            "orderedPlanState": {"summary": {"unitTotal": 45, "targetUnitCount": 45}},
                            "reviewState": {
                                "summary": {"riskCount": 0, "warnCount": 4},
                                "checks": [
                                    {"passed": False, "summary": "当前排序存在录取概率倒挂"},
                                    {"passed": False, "summary": "当前录取概率梯度存在断层"},
                                ],
                            },
                        },
                    }
                ),
            ):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-basic-plan-status", "user-1", "方案有了么"))

    assert reply == "历史里旧冲突：广西师范大学生物科学还在。"
    assert len(fake_agent.calls) == 1
    assert fake_agent.calls[0]["planning_summary"] is not None
    assert fake_agent.calls[0]["planning_summary"].ordered_total == 45
    assert fake_agent.calls[0]["planning_summary"].review_warn_count == 4


def test_chat_service_normalizes_plan_gap_question_even_without_tool_call(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgent(["问题的本质：意向组合太窄。 解决方案。\n\n要补满更合理的志愿，你有两条路。 方案A：扩大专业范围（推荐）。"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-plan-gap-style", "user-1", "还差的几个怎么补"))

    assert "方案A：扩大专业范围" in reply
    assert "问题的本质：意向组合太窄" in reply


def test_chat_service_preserves_plan_choice_menu_even_without_tool_call(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgent(["**最终答复**\n\n方案A：接受当前方案。方案B：重新生成。你选A还是B？"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-plan-style-2", "user-1", "方案有了么"))

    assert "选A还是B" in reply
    assert "方案A：接受当前方案" in reply


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


def test_chat_service_propagates_wsresponse_from_main_agent(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    ws_reply = WSResponse(
        type="intentConfirmPopup",
        session_id="session-3",
        content=json.dumps({"title": "确认卡"}, ensure_ascii=False),
    )
    fake_agent = _FakeAgent([ws_reply])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-3", "user-3", "我更想去北京"))

    assert isinstance(reply, WSResponse)
    assert reply.type == "intentConfirmPopup"
    assert len(fake_agent.calls) == 1


def test_chat_service_plan_status_message_keeps_main_agent_entry_and_planning_summary(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgent(["这是当前方案状态摘要"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={
                "code": 0,
                "data": {
                    "phase": "reviewed",
                    "version": 9,
                    "draftPlanState": {"summary": {"unitTotal": 30, "total": 60}},
                    "orderedPlanState": {"summary": {"unitTotal": 28, "total": 56}},
                    "reviewState": {
                        "summary": {"warnCount": 2, "riskCount": 1},
                        "checks": [{"passed": False, "summary": "梯度有断层"}],
                    },
                },
            })):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-plan-1", "user-1", "现在方案怎么样"))

    assert reply == "这是当前方案状态摘要"
    assert len(fake_agent.calls) == 1
    assert fake_agent.calls[0]["user_prompt"] == "现在方案怎么样"
    assert fake_agent.calls[0]["planning_summary"] is not None
    assert fake_agent.calls[0]["planning_summary"].phase == "reviewed"
    assert fake_agent.calls[0]["planning_summary"].draft_total == 30
    assert fake_agent.calls[0]["planning_summary"].ordered_total == 28
    assert fake_agent.calls[0]["planning_summary"].review_warn_count == 2
    assert fake_agent.calls[0]["planning_summary"].review_risk_count == 1


def test_chat_service_plan_adjustment_message_preserves_history_context(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgent(["先看当前问题", "这是优化建议"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={
                "code": 0,
                "data": {
                    "phase": "reviewed",
                    "version": 10,
                    "draftPlanState": {"summary": {"total": 30}},
                    "orderedPlanState": {"summary": {"total": 30}},
                    "reviewState": {"summary": {"warnCount": 1, "riskCount": 0}, "checks": []},
                },
            })):
        service = ChatService(mock_llm_client, store)
        first_reply = asyncio.run(service.handle_message("session-plan-2", "user-2", "现在方案怎么样"))
        second_reply = asyncio.run(service.handle_message("session-plan-2", "user-2", "怎么优化"))

    assert first_reply == "先看当前问题"
    assert second_reply == "这是优化建议"
    assert len(fake_agent.calls) == 2
    assert fake_agent.calls[1]["user_prompt"] == "怎么优化"
    assert fake_agent.calls[1]["chat_history"] == [
        {"role": "user", "content": "现在方案怎么样"},
        {"role": "assistant", "content": "先看当前问题"},
        {"role": "user", "content": "怎么优化"},
    ]
    assert fake_agent.calls[1]["planning_summary"] is not None
    assert fake_agent.calls[1]["planning_summary"].review_warn_count == 1


def test_chat_service_plan_regenerate_message_still_uses_main_agent_single_entry(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgent(["这会整体更新当前排序结果，建议先确认。"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={
                "code": 0,
                "data": {
                    "phase": "ordered",
                    "version": 12,
                    "draftPlanState": {"summary": {"total": 30}},
                    "orderedPlanState": {"summary": {"total": 30}},
                    "reviewState": {"summary": {"warnCount": 0, "riskCount": 0}, "checks": []},
                },
            })):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-plan-3", "user-3", "帮我重排一下"))

    assert reply == "这会整体更新当前排序结果，建议先确认。"
    assert len(fake_agent.calls) == 1
    assert fake_agent.calls[0]["user_prompt"] == "帮我重排一下"
    assert fake_agent.calls[0]["planning_summary"] is not None
    assert fake_agent.calls[0]["planning_summary"].phase == "ordered"


def test_chat_service_plan_status_then_review_preserves_dialog_history(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgent(["这是当前方案摘要", "这是当前风险分析"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={
                "code": 0,
                "data": {
                    "phase": "reviewed",
                    "version": 13,
                    "draftPlanState": {"summary": {"total": 30}},
                    "orderedPlanState": {"summary": {"total": 30}},
                    "reviewState": {
                        "summary": {"warnCount": 2, "riskCount": 1},
                        "checks": [{"passed": False, "summary": "保区占比过低"}],
                    },
                },
            })):
        service = ChatService(mock_llm_client, store)
        first_reply = asyncio.run(service.handle_message("session-plan-4", "user-4", "现在方案怎么样"))
        second_reply = asyncio.run(service.handle_message("session-plan-4", "user-4", "哪里还不合理"))

    assert first_reply == "这是当前方案摘要"
    assert second_reply == "这是当前风险分析"
    assert fake_agent.calls[1]["chat_history"] == [
        {"role": "user", "content": "现在方案怎么样"},
        {"role": "assistant", "content": "这是当前方案摘要"},
        {"role": "user", "content": "哪里还不合理"},
    ]
    assert fake_agent.calls[1]["planning_summary"] is not None
    assert fake_agent.calls[1]["planning_summary"].review_warn_count == 2
    assert fake_agent.calls[1]["planning_summary"].review_risk_count == 1


def test_chat_service_basic_plan_status_then_followup_reload_latest_planning_summary(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgent(["第一次状态", "第二次状态"])
    planning_responses = [
        {
            "code": 0,
            "data": {
                "phase": "ordered",
                "version": 21,
                "draftPlanState": {"summary": {"total": 30}},
                "orderedPlanState": {"summary": {"total": 28}},
                "reviewState": {"summary": {"warnCount": 1, "riskCount": 0}, "checks": []},
            },
        },
        {
            "code": 0,
            "data": {
                "phase": "reviewed",
                "version": 22,
                "draftPlanState": {"summary": {"total": 30}},
                "orderedPlanState": {"summary": {"total": 30}},
                "reviewState": {"summary": {"warnCount": 2, "riskCount": 1}, "checks": []},
            },
        },
    ]

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(side_effect=planning_responses)) as planning_mock:
        service = ChatService(mock_llm_client, store)
        first_reply = asyncio.run(service.handle_message("session-plan-repeat-1", "user-1", "方案有了么"))
        second_reply = asyncio.run(service.handle_message("session-plan-repeat-1", "user-1", "现在方案怎么样"))

    assert first_reply == "第一次状态"
    assert second_reply == "第二次状态"
    assert planning_mock.await_count == 2
    assert len(fake_agent.calls) == 2
    assert fake_agent.calls[0]["planning_summary"] is not None
    assert fake_agent.calls[0]["planning_summary"].version == 21
    assert fake_agent.calls[0]["planning_summary"].ordered_total == 28
    assert fake_agent.calls[1]["planning_summary"] is not None
    assert fake_agent.calls[1]["planning_summary"].version == 22
    assert fake_agent.calls[1]["planning_summary"].ordered_total == 30
    assert fake_agent.calls[1]["planning_summary"].review_warn_count == 2
    assert fake_agent.calls[1]["planning_summary"].review_risk_count == 1
    assert fake_agent.calls[1]["chat_history"] == [
        {"role": "user", "content": "方案有了么"},
        {"role": "assistant", "content": first_reply},
        {"role": "user", "content": "现在方案怎么样"},
    ]


def test_chat_service_compensation_preview_then_apply_confirm_keeps_single_entry(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgent(["这是补偿预览", "这会直接补改当前方案，请先确认。"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={
                "code": 0,
                "data": {
                    "phase": "reviewed",
                    "version": 14,
                    "draftPlanState": {"summary": {"total": 30}},
                    "orderedPlanState": {"summary": {"total": 30}},
                    "reviewState": {"summary": {"warnCount": 1, "riskCount": 0}, "checks": []},
                },
            })):
        service = ChatService(mock_llm_client, store)
        first_reply = asyncio.run(service.handle_message("session-plan-5", "user-5", "直接看完整的补偿预览"))
        second_reply = asyncio.run(service.handle_message("session-plan-5", "user-5", "那直接应用吧"))

    assert first_reply == "这是补齐建议"
    assert second_reply == "这会直接补改当前方案，请先确认。"
    assert fake_agent.calls[1]["chat_history"] == [
        {"role": "user", "content": "直接看完整的补偿预览"},
        {"role": "assistant", "content": "这是补齐建议"},
        {"role": "user", "content": "那直接应用吧"},
    ]
    assert fake_agent.calls[1]["planning_summary"] is not None
    assert fake_agent.calls[1]["planning_summary"].review_warn_count == 1


def test_chat_service_reorder_request_then_user_confirmation_preserves_turn_history(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgent(["这会整体更新当前排序结果，建议先确认。", "我会重新生成可确认的排序预览。"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={
                "code": 0,
                "data": {
                    "phase": "ordered",
                    "version": 15,
                    "draftPlanState": {"summary": {"total": 30}},
                    "orderedPlanState": {"summary": {"total": 30}},
                    "reviewState": {"summary": {"warnCount": 0, "riskCount": 0}, "checks": []},
                },
            })):
        service = ChatService(mock_llm_client, store)
        first_reply = asyncio.run(service.handle_message("session-plan-6", "user-6", "帮我重排一下"))
        second_reply = asyncio.run(service.handle_message("session-plan-6", "user-6", "确认"))

    assert first_reply == "这会整体更新当前排序结果，建议先确认。"
    _assert_no_pending_confirmation_guard(second_reply)
    assert len(fake_agent.calls) == 1


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


def test_chat_service_normalizes_toolless_intent_reply_profile_jargon_in_history(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    bad_reply = (
        '我来确认一下，你是想把"网络与新媒体"作为新的专业意向加入画像，'
        "还是想先看看当前方案里有没有相关专业、以及怎么调整方案来纳入这个方向？"
    )
    fake_agent = _FakeAgent([bad_reply])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={
                "code": 0,
                "data": {
                    "phase": "ordered",
                    "version": 2,
                    "draftPlanState": {"summary": {"total": 45}},
                    "orderedPlanState": {"summary": {"total": 45}},
                    "reviewState": {"summary": {"warnCount": 0, "riskCount": 0}, "checks": []},
                },
            })):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-57-toolless-intent", "user-57", "想学网络与新媒体"))

    assert "画像" not in reply
    assert "记成后续报考参考" in reply
    assert fake_agent.calls[0]["user_prompt"] == "想学网络与新媒体"
    saved_history = asyncio.run(store.load("session-57-toolless-intent"))
    saved_text = next(part.content for part in saved_history[-1].parts if isinstance(part, TextPart))
    assert saved_text == reply
    assert "画像" not in saved_text


def test_chat_service_normalizes_premature_recorded_wording_after_intent_preview_tool(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgentWithToolCalls(
        "好的，我记下了你对跨境电商的兴趣。候选库里有一个相关机会。",
        [
            ToolCallPart(
                tool_name="preview_current_major_intent_confirmation",
                args={"major_intents": {"add": ["跨境电商"]}},
                tool_call_id="intent-preview-call-1",
            )
        ],
        [
            ToolReturnPart(
                tool_name="preview_current_major_intent_confirmation",
                content='{"status":"ready","items":[{"content":"将跨境电子商务更新为偏好方向。"}]}',
                tool_call_id="intent-preview-call-1",
            )
        ],
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-intent-preview-style", "user-57", "想学跨境电商"))

    assert isinstance(reply, str)
    primary = reply
    assert "我记下了" not in primary
    assert "采纳" in primary
    assert "后续参考" in primary
    saved_history = asyncio.run(store.load("session-intent-preview-style"))
    saved_text = next(part.content for part in saved_history[-1].parts if isinstance(part, TextPart))
    assert saved_text == primary


def test_chat_service_does_not_refresh_candidate_workspace_after_intent_preview_tool(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgentWithToolCalls(
        "我先把你不想学审计这件事整理成待确认要求。",
        [
            ToolCallPart(
                tool_name="preview_current_major_intent_confirmation",
                args={"major_intents": {"remove": ["审计"]}},
                tool_call_id="intent-preview-call-2",
            )
        ],
        [
            ToolReturnPart(
                tool_name="preview_current_major_intent_confirmation",
                content='{"status":"ready","items":[{"content":"将审计学设为排除方向。"}]}',
                tool_call_id="intent-preview-call-2",
            )
        ],
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-intent-preview-refresh", "user-57", "不想学审计"))

    assert isinstance(reply, str)
    assert "我先把你不想学审计这件事整理成待采纳报考条件。" in reply
    assert "这次内容还没有采纳" in reply
    assert "点“采纳”前不会写入后续报考参考" in reply


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


def test_chat_service_normalizes_unbacked_intent_preview_without_tool_call(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgent([
        (
            "中医确实属于医学门类。\n\n"
            "**待确认内容**\n"
            "- 排除专业门类：医学\n\n"
            "**下一步**\n"
            "- 回复“确认”就按上面执行；"
        )
    ])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-unbacked-intent-preview", "user-57", "医学护理都别碰，但中医到底算不算"))

    assert isinstance(reply, str)
    assert "待确认内容" not in reply
    assert "回复“确认”就按上面执行" not in reply
    assert "还没有列出可采纳的内容" in reply


def test_chat_service_keeps_general_preference_change_policy_answer(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgent([
        (
            "孩子改主意后，之前偏好可以调整。只要孩子想法变了，直接告诉我新的方向，"
            "我会先整理成待采纳内容；采纳后再调整推荐口径和候选志愿。"
        )
    ])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-general-change-policy", "user-57", "如果孩子改主意了，之前偏好还能改吗"))

    assert isinstance(reply, str)
    assert "之前偏好可以调整" in reply
    assert "采纳后再调整推荐口径和候选志愿" in reply
    assert "这轮我还没有生成可点击的待采纳内容" not in reply


def test_chat_service_does_not_recover_unbacked_major_intent_confirmation_to_pending_card(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    bad_reply = (
        "我先把你对会计、审计的偏好，以及对土木、建筑方向的排除意向整理一下，确认后再作为后续参考：\n"
        "- 倾向：会计学、审计学\n"
        "- 排除：土木类、建筑类\n"
        "如果你确认，后续推荐和方案生成时我会优先保留财会方向，并过滤掉土木、建筑相关专业。你确认要这样记吗？"
    )
    fake_agent = _FakeAgent([bad_reply])
    recovered_payload = {
        "status": "ready",
        "sessionId": "990503",
        "title": "待确认要求",
        "intentMode": "constraint",
        "analysisStage": "confirmed",
        "items": [
            {
                "content": "偏好专业：会计学、审计学",
                "value": {"major_intents": {"level3": ["会计学", "审计学"]}},
                "selected": True,
            },
            {
                "content": "排除专业类：土木类、建筑类",
                "value": {"major_intents": {"negative_level2": ["土木类", "建筑类"]}},
                "selected": True,
            },
        ],
        "existingItems": [],
    }
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()
    recover_mock = AsyncMock(return_value=json.dumps(recovered_payload, ensure_ascii=False))

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.analyze_volunteer_intent_change", recover_mock), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message("990503", "user-57", "会计审计这类还行，土木建筑那种别碰")
        )

    assert isinstance(reply, str)
    assert "你确认要这样记吗" not in reply
    assert "还没有列出可采纳的内容" in reply
    assert pending_state == {}
    recover_mock.assert_not_awaited()
    saved_history = asyncio.run(store.load("990503"))
    saved_text = next(part.content for part in saved_history[-1].parts if isinstance(part, TextPart))
    assert saved_text == reply
    assert "你确认要这样记吗" not in saved_text


def test_chat_service_does_not_recover_unbacked_region_intent_confirmation_to_pending_card(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    bad_reply = (
        "我先把这次地域想法整理一下，确认后再作为后续参考：\n"
        "- 倾向：南方\n"
        "- 排除：北方\n"
        "如果你确认，后续看候选和方案时我会优先考虑南方，并先不考虑北方。你确认要这样记吗？"
    )
    fake_agent = _FakeAgent([bad_reply])
    recovered_payload = {
        "status": "ready",
        "sessionId": "990504",
        "title": "待确认地域要求",
        "intentMode": "constraint",
        "analysisStage": "confirmed",
        "items": [
            {
                "content": "将南方更新为偏好地域，后续专家推荐会更优先考虑它。",
                "value": {"city_intents": {"province": ["浙江", "上海", "江苏", "广东"]}},
                "selected": True,
            },
            {
                "content": "把北方记成明确不考虑的地区，后面看候选和方案时都会按这个要求来。",
                "value": {"city_intents": {"negative_province": ["北京", "天津", "河北", "山东"]}},
                "selected": True,
            },
        ],
        "existingItems": [],
    }
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()
    recover_mock = AsyncMock(return_value=json.dumps(recovered_payload, ensure_ascii=False))

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.analyze_volunteer_intent_change", recover_mock), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message("990504", "user-57", "孩子就想去南方，北方先别考虑")
        )

    assert isinstance(reply, str)
    assert "你确认要这样记吗" not in reply
    assert "还没有列出可采纳的内容" in reply
    assert pending_state == {}
    recover_mock.assert_not_awaited()
    saved_history = asyncio.run(store.load("990504"))
    saved_text = next(part.content for part in saved_history[-1].parts if isinstance(part, TextPart))
    assert saved_text == reply
    assert "你确认要这样记吗" not in saved_text


def test_chat_service_does_not_recover_claimed_region_card_without_tool_and_drops_mixed_history(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    bad_reply = (
        "我已经注意到你不想去内蒙古。刚才已经为你生成了排除内蒙古的待采纳内容，"
        "需要点击采纳后才会生效。同时，你之前也说了不想去天津，当前方案里还有天津师范大学需要留意。"
    )
    fake_agent = _FakeAgent([bad_reply])
    recovered_payload = {
        "status": "ready",
        "sessionId": "990505",
        "title": "待确认地域要求",
        "intentMode": "constraint",
        "analysisStage": "confirmed",
        "items": [
            {
                "content": "把内蒙古记成明确不考虑的地区，后面看候选和方案时都会按这个要求来。",
                "value": {"city_intents": {"negative_province": ["内蒙古"]}},
                "selected": True,
            },
        ],
        "existingItems": [],
    }
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()
    recover_mock = AsyncMock(return_value=json.dumps(recovered_payload, ensure_ascii=False))

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.analyze_volunteer_intent_change", recover_mock), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("990505", "user-57", "不想去内蒙"))

    assert isinstance(reply, str)
    assert pending_state == {}
    recover_mock.assert_not_awaited()
    saved_history = asyncio.run(store.load("990505"))
    saved_text = next(part.content for part in saved_history[-1].parts if isinstance(part, TextPart))
    assert saved_text == reply
    assert "天津" not in saved_text
    assert "已经为你生成了排除内蒙古的待采纳内容" not in saved_text


def test_chat_service_does_not_recover_region_intent_before_unbacked_plan_confirmation_guard(
    tmp_path,
    mock_llm_client,
):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    bad_reply = (
        "我理解你现在不想优先考虑安徽。"
        "如果你确认，我会把安徽作为后续调整方案时需要避开的地域，"
        "并重新定位影响范围。"
    )
    fake_agent = _FakeAgent([bad_reply])
    recovered_payload = {
        "status": "ready",
        "sessionId": "990506",
        "title": "待确认地域想法",
        "intentMode": "preference",
        "analysisStage": "confirmed",
        "items": [
            {
                "content": "不优先省份：安徽",
                "value": {"city_intents": {"negative_province": ["安徽"]}},
                "selected": True,
            },
        ],
        "existingItems": [
            {
                "content": "偏好地域：上海、安徽、山东、江苏、江西",
                "value": {"city_intents": {"province": ["上海", "安徽", "山东", "江苏", "江西"]}},
                "selected": True,
            },
        ],
    }
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()
    recover_mock = AsyncMock(return_value=json.dumps(recovered_payload, ensure_ascii=False))

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.analyze_volunteer_intent_change", recover_mock), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("990506", "user-57", "不想去安徽"))

    assert isinstance(reply, str)
    assert "安徽" in reply
    assert "还没有列出可采纳的内容" in reply
    assert pending_state == {}
    recover_mock.assert_not_awaited()


def test_chat_service_does_not_recover_region_intent_from_no_executable_boundary_without_tools(
    tmp_path,
    mock_llm_client,
):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgent(["这轮还没有生成可执行的调整内容，所以不会改动当前方案。"])
    recovered_payload = {
        "status": "ready",
        "sessionId": "990506-boundary",
        "title": "待确认地域想法",
        "intentMode": "preference",
        "analysisStage": "confirmed",
        "items": [
            {
                "content": "不优先省份：安徽",
                "value": {"city_intents": {"negative_province": ["安徽"]}},
                "selected": True,
            },
        ],
        "existingItems": [
            {
                "content": "偏好地域：上海、安徽、山东、江苏、江西",
                "value": {"city_intents": {"province": ["上海", "安徽", "山东", "江苏", "江西"]}},
                "selected": True,
            },
        ],
    }
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()
    recover_mock = AsyncMock(return_value=json.dumps(recovered_payload, ensure_ascii=False))

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.analyze_volunteer_intent_change", recover_mock), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("990506-boundary", "user-57", "不想去安徽"))

    assert isinstance(reply, str)
    assert "不会写入后续报考参考" in reply
    assert "你确认前不会执行" in reply
    assert pending_state == {}
    recover_mock.assert_not_awaited()


def test_chat_service_does_not_recover_semantic_intent_preview_without_tool_call(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgentWithToolCalls(
        "好的，我先把你要采用的意向列出来，点“采纳”前不会生效。\n\n准备采用的内容：只保留专业方向：临床医学",
        [],
        observability={
            "intentSideEffectDecision": {
                "decision": "intent_preview",
                "confidence": 0.95,
                "constraintIntentType": "only_keep",
                "reason": "test semantic intent preview",
            }
        },
    )
    recovered_payload = {
        "status": "ready",
        "sessionId": "990510",
        "title": "待采纳报考条件",
        "intentMode": "constraint",
        "constraintIntentType": "only_keep",
        "analysisStage": "confirmed",
        "items": [
            {
                "content": "只保留专业：临床医学",
                "value": {"major_intents": {"level3": ["临床医学"]}},
                "selected": True,
            },
        ],
        "existingItems": [],
    }
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store(
        {
            "type": "pendingConfirmation",
            "pendingId": "old-intent-pending",
            "sessionId": "990510",
            "kind": "intent_change",
            "status": "active",
            "actionFamily": "apply_selected_intents",
            "summary": "排除专业门类：医学",
            "executionPayload": {
                "toolName": "apply_selected_intents",
                "merged": {"major_intents": {"negative_level1": ["医学"]}},
                "selectedData": {
                    "selected": [{"major_intents": {"negative_level1": ["医学"]}}],
                    "intentMode": "constraint",
                    "batch": "01",
                },
                "intentMode": "constraint",
                "batch": "01",
            },
        }
    )
    recover_mock = AsyncMock(return_value=json.dumps(recovered_payload, ensure_ascii=False))

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.analyze_volunteer_intent_change", recover_mock), \
            patch("app.service.classify_turn_decision", AsyncMock(return_value=_pending_conflict_turn_decision())), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("990510", "user-57", "我只想学临床医学，其他专业先不要"))

    assert isinstance(reply, str)
    assert "待采纳内容：排除专业门类：医学" in reply
    assert "不会直接覆盖" in reply
    assert "不会再生成第二张待采纳卡" in reply
    assert pending_state["value"]["pendingId"] == "old-intent-pending"
    assert pending_state["value"]["executionPayload"]["selectedData"]["selected"] == [
        {"major_intents": {"negative_level1": ["医学"]}},
    ]
    save_pending_mock.assert_not_awaited()
    recover_mock.assert_not_awaited()
    assert fake_agent.calls == []


def test_chat_service_semantic_readonly_suppresses_confirmable_interest_card_when_not_honored(
    tmp_path,
    mock_llm_client,
):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    interest_payload = {
        "status": "ready",
        "sessionId": "semantic-readonly-interest-session",
        "title": "专业方向分析",
        "intentMode": "preference",
        "analysisStage": "confirmed",
        "message": "小语种还能选，但要重点看学校层次、语种方向和就业城市。",
        "items": [
            {
                "content": "偏好专业：小语种",
                "selected": True,
                "value": {"major_intents": {"level3": ["小语种"]}},
            },
            {
                "content": "偏好专业类：外国语言文学类",
                "selected": True,
                "value": {"major_intents": {"level2": ["外国语言文学类"]}},
            },
        ],
        "existingItems": [],
    }
    fake_agent = _FakeAgentWithToolCalls(
        "小语种不是不能选，关键看语种、学校层次和就业城市。这轮我先帮你判断适不适合，不会直接写成报考想法。",
        [
            ToolCallPart(
                tool_name="analyze_current_major_interest",
                args={"intent_mode": "preference"},
                tool_call_id="readonly-interest-confirmable",
            )
        ],
        [
            ToolReturnPart(
                tool_name="analyze_current_major_interest",
                content=json.dumps(interest_payload, ensure_ascii=False),
                tool_call_id="readonly-interest-confirmable",
            )
        ],
        observability={
            "intentSideEffectDecision": {
                "decision": "analysis_only",
                "confidence": 0.95,
                "honored": False,
                "reason": "用户是在问专业适配和就业，不是在更新偏好",
            }
        },
    )
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "semantic-readonly-interest-session",
                "user-57",
                "小语种现在还能选吗，怕就业不好",
            )
        )

    assert isinstance(reply, str)
    assert "小语种" in reply
    assert "采纳" not in reply
    assert pending_state == {}
    save_pending_mock.assert_not_awaited()


def test_chat_service_semantic_readonly_uses_analysis_reply_when_preview_tool_fires(
    tmp_path,
    mock_llm_client,
):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    analysis_payload = {
        "status": "ready",
        "analysisStage": "interest",
        "message": "数学、物理方向适合先做基础学科适配分析，这轮只分析培养路径和风险，不写入报考参考。",
    }
    preview_payload = {
        "status": "ready",
        "sessionId": "semantic-readonly-preview-fired-session",
        "title": "确认这条要求",
        "intentMode": "preference",
        "analysisStage": "confirmed",
        "items": [
            {
                "content": "偏好专业：数学类、物理学类",
                "selected": True,
                "value": {"major_intents": {"level2": ["数学类", "物理学类"]}},
            },
        ],
        "message": "准备采纳的方向：数学类、物理学类。采纳后后续推荐会以这两个方向为重点参考。",
    }
    fake_agent = _FakeAgentWithToolCalls(
        "很好，我先把你的这个方向偏好列出来，采纳后后续推荐会以这两个方向为重点参考。",
        [
            ToolCallPart(
                tool_name="analyze_current_major_interest",
                args={},
                tool_call_id="major-analysis-readonly",
            ),
            ToolCallPart(
                tool_name="preview_current_major_intent_confirmation",
                args={},
                tool_call_id="major-preview-should-downgrade",
            ),
        ],
        [
            ToolReturnPart(
                tool_name="analyze_current_major_interest",
                content=json.dumps(analysis_payload, ensure_ascii=False),
                tool_call_id="major-analysis-readonly",
            ),
            ToolReturnPart(
                tool_name="preview_current_major_intent_confirmation",
                content=json.dumps(preview_payload, ensure_ascii=False),
                tool_call_id="major-preview-should-downgrade",
            ),
        ],
        observability={
            "intentSideEffectDecision": {
                "decision": "analysis_only",
                "confidence": 0.9,
                "honored": True,
                "reason": "用户描述学科强项和基础学科兴趣，没有明确要求写入后续参考。",
            },
            "latestIntentPreviewPayload": preview_payload,
        },
    )
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "semantic-readonly-preview-fired-session",
                "user-57",
                "数学物理是我强项想搞基础学科",
            )
        )

    assert isinstance(reply, str)
    assert "适合先做基础学科适配分析" in reply
    assert "采纳后" not in reply
    assert "准备采纳" not in reply
    assert pending_state == {}
    save_pending_mock.assert_not_awaited()


def test_classify_turn_decision_cached_times_out_and_records_observability(monkeypatch):
    async def _slow_turn_decision(*_args, **_kwargs):
        await asyncio.sleep(1)
        return _runtime_turn_decision()

    request_context = RequestContext(sessionid="turn-timeout-session", userid="user-1")
    monkeypatch.setattr("app.service._TURN_DECISION_TIMEOUT_SECONDS", 0.001)
    monkeypatch.setattr("app.service.classify_turn_decision", _slow_turn_decision)

    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(
            _classify_turn_decision_cached(
                "电力，铁道，航空职业技术学院，在海南招生的有哪几个学校呢",
                request_context=request_context,
                payload={"planningStateProfile": {"candidatePoolPresent": True}},
            )
        )

    assert request_context.agent_observability["turnDecisionTimeoutCount"] == 1
    assert request_context.agent_observability["turnDecisionDurationMs"] >= 0


def test_chat_service_downgraded_intent_reply_preserves_positive_focus_from_semantic_decision(
    tmp_path,
    mock_llm_client,
):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgentWithToolCalls(
        (
            "**先看影响**\n"
            "- 先按这个方向看影响和边界：避开 文学、历史学等方向；这轮只做分析，不会直接写入排除条件或改动方案。\n\n"
            "**下一步**\n"
            "- 如果要把这些想法作为后续参考，我可以先列出来让你采纳；采纳前不会生效。"
        ),
        [],
        observability={
            "intentSideEffectDecision": {
                "decision": "analysis_only",
                "confidence": 0.9,
                "preferenceStrength": {
                    "preferred": ["计算机类", "人工智能"],
                    "exclude_soft": ["文学", "历史学"],
                },
                "entityPolaritySpans": [
                    {"entity": "计算机", "entityType": "major", "polarity": "positive", "strength": "preferred"},
                    {"entity": "人工智能", "entityType": "major", "polarity": "positive", "strength": "preferred"},
                    {"entity": "文科", "entityType": "major_category", "polarity": "negative", "strength": "exclude_soft"},
                ],
                "reason": "用户在描述兴趣画像，先做分析。",
            }
        },
    )
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01", "totalScore": 660, "province": {"name": "浙江"}, "subjectList": [{"name": "物理"}, {"name": "化学"}, {"name": "生物"}]}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "runtime-turn-decision-overrides-analysis-side-effect",
                "user-57",
                "专业方向偏计算机和人工智能 不想学文科",
            )
        )

    assert isinstance(reply, str)
    assert "计算机" in reply
    assert "人工智能" in reply
    assert "文学" in reply
    assert "历史" in reply
    assert pending_state == {}
    save_pending_mock.assert_not_awaited()


def test_chat_service_replaces_no_tool_plan_boundary_with_consultative_no_change_reply(
    tmp_path,
    mock_llm_client,
):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgent(["这轮还没有生成可执行的调整内容，所以不会改动当前方案。"])
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "semantic-readonly-no-tool-boundary-session",
                "user-57",
                "我只想先保存这个思路，不要自动改",
            )
        )

    assert isinstance(reply, str)
    assert "不会改动当前方案" in reply
    assert "不会写入后续报考参考" in reply
    assert "这轮还没有生成可执行的调整内容" not in reply
    assert pending_state == {}
    save_pending_mock.assert_not_awaited()


def test_chat_service_preview_intent_not_downgraded_when_semantic_decision_not_honored(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    preview_payload = {
        "status": "ready",
        "sessionId": "99051021",
        "title": "确认这条要求",
        "intentMode": "constraint",
        "constraintIntentType": "default",
        "analysisStage": "confirmed",
        "items": [
            {
                "content": "偏好专业：会计学、审计学",
                "selected": True,
                "value": {"major_intents": {"level3": ["会计学", "审计学"]}},
            },
            {
                "content": "排除专业：土木工程、建筑学",
                "selected": True,
                "value": {"major_intents": {"negative_level3": ["土木工程", "建筑学"]}},
            },
        ],
        "existingItems": [],
        "reply_strategy": "preview_wait_confirm",
        "message": "**点击采纳后生效**\n- 偏好专业：会计学、审计学\n- 排除专业：土木工程、建筑学",
    }
    fake_agent = _FakeAgentWithToolCalls(
        "**点击采纳后生效**\n- 偏好专业：会计学、审计学\n- 排除专业：土木工程、建筑学",
        [
            ToolCallPart(
                tool_name="preview_current_major_intent_confirmation",
                args={"intent_mode": "constraint"},
                tool_call_id="major-preview-not-downgraded",
            )
        ],
        [
            ToolReturnPart(
                tool_name="preview_current_major_intent_confirmation",
                content=json.dumps(preview_payload, ensure_ascii=False),
                tool_call_id="major-preview-not-downgraded",
            )
        ],
        observability={
            "intentSideEffectDecision": {
                "decision": "mixed_answer_then_ask",
                "confidence": 0.85,
                "honored": False,
                "reason": "用户表达口语化，但有明确专业实体和排除对象。",
            },
            "latestIntentPreviewPayload": preview_payload,
        },
    )
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("99051021", "user-57", "会计审计这类还行，土木建筑那种别碰"))

    assert isinstance(reply, ChatServiceResponseEnvelope)
    card_payloads = [json.loads(item.content) for item in reply.followups if item.type == "pendingConfirmationCard"]
    assert len(card_payloads) == 1
    assert card_payloads[0]["kind"] == "intent_change"
    assert "会计学" in card_payloads[0]["content"]
    assert "审计学" in card_payloads[0]["content"]
    assert "土木工程" in card_payloads[0]["content"]
    assert "建筑学" in card_payloads[0]["content"]
    assert pending_state["value"]["kind"] == "intent_change"
    save_pending_mock.assert_awaited()


def test_chat_service_rebuilds_mismatched_preview_from_semantic_intent_decision(
    tmp_path,
    mock_llm_client,
):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    wrong_preview_payload = {
        "status": "ready",
        "sessionId": "65501205",
        "title": "确认这条要求",
        "intentMode": "constraint",
        "constraintIntentType": "must_have",
        "analysisStage": "confirmed",
        "items": [
            {
                "content": "至少保留专业：数学与应用数学",
                "selected": True,
                "value": {"major_intents": {"level3": ["数学与应用数学"]}},
            },
            {
                "content": "至少保留专业：物理学",
                "selected": True,
                "value": {"major_intents": {"level3": ["物理学"]}},
            },
        ],
    }
    fake_agent = _FakeAgentWithToolCalls(
        "已列出这次报考想法预览：至少保留专业：数学与应用数学、物理学。",
        [
            ToolCallPart(
                tool_name="preview_current_major_intent_confirmation",
                args={},
                tool_call_id="wrong-major-preview",
            )
        ],
        [
            ToolReturnPart(
                tool_name="preview_current_major_intent_confirmation",
                content=json.dumps(wrong_preview_payload, ensure_ascii=False),
                tool_call_id="wrong-major-preview",
            )
        ],
        observability={
            "intentSideEffectDecision": {
                "decision": "intent_preview",
                "confidence": 0.95,
                "constraintIntentType": "must_have",
                "preferenceStrength": {
                    "preferred": ["清华大学", "北京大学", "复旦大学"],
                    "must_have": ["强基计划"],
                },
                "entityPolaritySpans": [
                    {"entity": "清华大学", "entityType": "school", "polarity": "positive", "strength": "preferred"},
                    {"entity": "北京大学", "entityType": "school", "polarity": "positive", "strength": "preferred"},
                    {"entity": "复旦大学", "entityType": "school", "polarity": "positive", "strength": "preferred"},
                    {"entity": "强基计划", "entityType": "admissionPath", "polarity": "positive", "strength": "must_have"},
                ],
                "admissionPath": "强基计划",
                "reason": "用户要求把这些学校的强基加进意向。",
            },
            "latestIntentPreviewPayload": wrong_preview_payload,
        },
    )
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "65501205",
                "user-57",
                "清华北大复旦的强基都加进意向",
            )
        )

    card_payload = _assert_pending_card_envelope(reply, "", "apply_selected_intents", kind="intent_change")
    assert "清华大学" in card_payload["content"]
    assert "北京大学" in card_payload["content"]
    assert "复旦大学" in card_payload["content"]
    assert "数学与应用数学" not in card_payload["content"]
    selected_data = pending_state["value"]["executionPayload"]["selectedData"]
    assert {"school_intents": {"colleges": ["清华大学", "北京大学", "复旦大学"]}} in selected_data["selected"]
    assert selected_data["admissionPath"] == "strongbase"
    assert "强基" in pending_state["value"]["summary"]
    save_pending_mock.assert_awaited()


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


def test_chat_service_does_not_recover_prepared_direction_text_without_tool_call(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    bad_reply = (
        "我先把你要采用的内容列出来，点\"采纳\"前不会生效：\n\n"
        "**准备采纳的方向**\n"
        "- 只保留：医学类（一级门类）\n"
        "- 排除范围：工科（一级门类）\n\n"
        "**采纳后的影响**\n"
        "- 后续推荐、方案检查和方案调整会以医学类为优先方向"
    )
    fake_agent = _FakeAgent([bad_reply])
    recovered_payload = {
        "status": "ready",
        "sessionId": "9905102",
        "title": "待采纳报考条件",
        "intentMode": "constraint",
        "constraintIntentType": "only_keep",
        "analysisStage": "confirmed",
        "items": [
            {
                "content": "只保留专业门类：医学",
                "value": {"major_intents": {"level1": ["医学"]}},
                "selected": True,
            },
            {
                "content": "排除专业门类：工学",
                "value": {"major_intents": {"negative_level1": ["工学"]}},
                "selected": True,
            },
        ],
        "existingItems": [],
    }
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()
    recover_mock = AsyncMock(return_value=json.dumps(recovered_payload, ensure_ascii=False))

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.analyze_volunteer_intent_change", recover_mock), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("9905102", "user-57", "不考虑工科，只考虑医学类"))

    assert isinstance(reply, str)
    assert "准备采纳的方向" not in reply
    assert "还没有列出可采纳的内容" in reply
    assert pending_state == {}
    recover_mock.assert_not_awaited()
    save_pending_mock.assert_not_awaited()


def test_chat_service_does_not_recover_intent_preview_after_readonly_plan_query_misroute(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgentWithToolCalls(
        "我已经查过当前方案和候选里的相关机会，但这轮查询没有稳定收敛。",
        [
            ToolCallPart(
                tool_name="query_volunteer_plan",
                args={"scope": "candidate", "query": "不去上海，看看候选"},
                tool_call_id="query-candidate-1",
            )
        ],
        [
            ToolReturnPart(
                tool_name="query_volunteer_plan",
                content=json.dumps(
                    {
                        "scope": "candidate",
                        "summary": "候选查询结果",
                    },
                    ensure_ascii=False,
                ),
                tool_call_id="query-candidate-1",
            )
        ],
    )
    recovered_payload = {
        "status": "ready",
        "sessionId": "990511",
        "title": "待采纳报考条件",
        "intentMode": "constraint",
        "constraintIntentType": "default",
        "analysisStage": "confirmed",
        "items": [
            {
                "content": "排除省份：上海",
                "value": {"city_intents": {"negative_province": ["上海"]}},
                "selected": True,
            },
        ],
        "existingItems": [],
    }
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()
    recover_mock = AsyncMock(return_value=json.dumps(recovered_payload, ensure_ascii=False))

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.analyze_volunteer_intent_change", recover_mock), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("990511", "user-57", "不去上海，看看候选"))

    assert isinstance(reply, str)
    assert "查询没有稳定收敛" in reply
    assert pending_state == {}
    recover_mock.assert_not_awaited()
    save_pending_mock.assert_not_awaited()


def test_chat_service_does_not_recover_intent_after_successful_candidate_query(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgentWithToolCalls(
        "候选里计算机类机会不少，例如计算机科学与技术、数据科学与大数据技术。你可以继续按地域或稳保筛选。",
        [
            ToolCallPart(
                tool_name="query_volunteer_plan",
                args={"scope": "candidate", "query": "帮我看看候选里有哪些计算机类的机会"},
                tool_call_id="query-candidate-success-1",
            )
        ],
        [
            ToolReturnPart(
                tool_name="query_volunteer_plan",
                content=json.dumps(
                    {
                        "scope": "candidate",
                        "summary": "候选里有计算机类机会。",
                    },
                    ensure_ascii=False,
                ),
                tool_call_id="query-candidate-success-1",
            )
        ],
    )
    recovered_payload = {
        "status": "ready",
        "sessionId": "990512",
        "title": "待采纳报考想法",
        "intentMode": "preference",
        "analysisStage": "confirmed",
        "items": [
            {
                "content": "偏好专业类：计算机类",
                "value": {"major_intents": {"level2": ["计算机类"]}},
                "selected": True,
            },
        ],
        "existingItems": [],
    }
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()
    recover_mock = AsyncMock(return_value=json.dumps(recovered_payload, ensure_ascii=False))

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.analyze_volunteer_intent_change", recover_mock), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("990512", "user-57", "帮我看看候选里有哪些计算机类的机会"))

    assert isinstance(reply, str)
    assert "计算机类" in reply
    assert pending_state == {}
    recover_mock.assert_not_awaited()
    save_pending_mock.assert_not_awaited()


def test_chat_service_uses_readonly_plan_query_result_when_guarding_fake_plan_confirm_copy(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    bad_reply = (
        "青城这块确实不少。"
        "如果你确认要我执行，我可以把青岛城市学院相关志愿移出方案。"
    )
    query_reply = (
        "按当前方案里的院校简称“青城”匹配到青岛城市学院；原先可能冲突的地域条件没有参与这次院校命中。\n"
        "当前方案里共命中了 7 条符合“院校:青城、青岛城市学院”的志愿。"
    )
    fake_agent = _FakeAgentWithToolCalls(
        bad_reply,
        [
            ToolCallPart(
                tool_name="query_volunteer_plan",
                args={"query": "青城那个是不是放多了，能查下", "scope": "plan"},
                tool_call_id="readonly-query-1",
            ),
        ],
        [
            ToolReturnPart(
                tool_name="query_volunteer_plan",
                content=query_reply,
                tool_call_id="readonly-query-1",
            ),
        ],
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("990508", "user-57", "青城那个是不是放多了，能查下"))

    assert isinstance(reply, str)
    assert "青城" in reply
    assert "这轮还没有生成可点击的方案待采纳内容" not in reply
    assert "确认要我执行" not in reply
    saved_history = asyncio.run(store.load("990508"))
    saved_text = next(part.content for part in saved_history[-1].parts if isinstance(part, TextPart))
    assert saved_text == reply


def test_chat_service_compacts_raw_readonly_plan_query_reply(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    raw_reply = (
        "当前方案里共命中了 7 条符合“专业:中外合作办学、国际班、学分互认”的志愿。"
        "下面仅展示前 5 条示例："
        "华南农业大学(专业组209)-会计学(国际班，与爱尔兰都柏林大学、澳大利亚蒙纳士大学、英国奥斯特大学、英国邓迪大学、英国兰卡斯特大学2+2学分互认项目，在国内学习期间除学费外须另需缴纳36000元/学年培养费)（冲，录取率1%）；"
        "华南农业大学(专业组209)-金融学(国际班，与爱尔兰都柏林大学、澳大利亚蒙纳士大学、英国奥斯特大学、英国邓迪大学、英国兰卡斯特大学2+2学分互认项目，在国内学习期间除学费外须另需缴纳36000元/学年培养费)（冲，录取率2%）；"
        "华南农业大学(专业组209)-风景园林(国际班，与澳大利亚纽卡斯尔大学3+2学分互认项目，在国内学习期间除学费外须另需缴纳36000元/学年培养费)（冲，录取率6%）；"
        "河北金融学院(专业组210)-会计学(中外合作办学)（稳，录取率54%）；"
        "广东技术师范大学(专业组246)-会计学(国际班)（稳，录取率56%）"
    )
    fake_agent = _FakeAgentWithToolCalls(
        raw_reply,
        [
            ToolCallPart(
                tool_name="query_volunteer_plan",
                args={"query": "当前方案里有哪些中外合作", "scope": "plan"},
                tool_call_id="readonly-query-raw-1",
            ),
        ],
        [
            ToolReturnPart(
                tool_name="query_volunteer_plan",
                content=raw_reply,
                tool_call_id="readonly-query-raw-1",
            ),
        ],
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("990509", "user-57", "当前方案里有哪些中外合作"))

    assert isinstance(reply, str)
    assert "当前方案里有 7 条" in reply
    assert "比较典型的有：" in reply
    assert reply.count("- ") == 3
    assert "下面仅展示前 5 条示例" not in reply
    saved_history = asyncio.run(store.load("990509"))
    saved_text = next(part.content for part in saved_history[-1].parts if isinstance(part, TextPart))
    assert saved_text == reply


def test_chat_service_appends_pending_intent_boundary_on_followup_analysis(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgent(["这个偏好会影响当前方案，需要替换土木并补充会计审计机会。"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-intent-followup-boundary", "user-57", "先不确认，看看影响"))

    assert isinstance(reply, str)
    assert "这次内容还没有采纳" not in reply
    assert "采纳/确认前不会生效" in reply


def test_chat_service_does_not_append_pending_intent_boundary_to_existing_only_preview(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgentWithToolCalls(
        "这个想法当前已经在后续报考参考里。本轮不会重复新增。",
        [
            ToolCallPart(
                tool_name="preview_current_major_intent_confirmation",
                args={"intent_mode": "constraint"},
                tool_call_id="existing-only-intent-preview",
            )
        ],
        [
            ToolReturnPart(
                tool_name="preview_current_major_intent_confirmation",
                content=json.dumps(
                    {
                        "status": "existing_only",
                        "sessionId": "session-existing-only-intent-preview",
                        "intentMode": "constraint",
                        "items": [],
                        "existingItems": [{"content": "当前已有参考排除具体专业：护理学"}],
                    },
                    ensure_ascii=False,
                ),
                tool_call_id="existing-only-intent-preview",
            )
        ],
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-existing-only-intent-preview", "user-57", "护理不要"))

    assert isinstance(reply, str)
    assert "当前已经在后续报考参考" in reply or "当前已经在报考参考" in reply
    assert "待确认内容" not in reply
    assert "点击采纳前不会写入后续报考参考" not in reply


def test_chat_service_does_not_append_pending_boundary_to_interest_stage_intent_analysis(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgentWithToolCalls(
        (
            "**先看影响**\n"
            "- 先按这个方向看影响和边界。\n\n"
            "**当前情况**\n"
            "- 医学、护理需要避开，财会可以作为可接受方向先看影响。"
        ),
        [
            ToolCallPart(
                tool_name="preview_current_major_intent_confirmation",
                args={"intent_mode": "constraint"},
                tool_call_id="interest-intent-preview",
            )
        ],
        [
            ToolReturnPart(
                tool_name="preview_current_major_intent_confirmation",
                content=json.dumps(
                    {
                        "status": "ready",
                        "sessionId": "session-interest-stage-intent-analysis",
                        "intentMode": "constraint",
                        "analysisStage": "interest",
                        "items": [
                            {
                                "content": "把医学记成明确不考虑的内容。",
                                "value": {"major_intents": {"negative_level1": ["医学"]}},
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                tool_call_id="interest-intent-preview",
            )
        ],
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "session-interest-stage-intent-analysis",
                "user-57",
                "医学护理这些别碰，财会还能接受，先看看影响",
            )
        )

    assert isinstance(reply, str)
    assert "医学、护理" in reply
    assert "待确认内容" not in reply
    assert "尚未确认" not in reply
    assert "点击采纳前不会写入后续报考参考" not in reply


def test_chat_service_does_not_append_pending_intent_boundary_to_unrelated_readonly_question(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgent(["建筑学对美术基础要求更高，城乡规划相对宽松，但也需要图纸表达能力。"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-intent-unrelated-readonly", "user-57", "建筑城乡规划要不要美术基础"))

    assert isinstance(reply, str)
    assert "建筑学对美术基础要求更高" in reply
    assert "尚未确认" not in reply
    assert "点击采纳前不会写入后续报考参考" not in reply


def test_chat_service_does_not_append_stale_pending_boundary_to_readonly_major_interest(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgentWithToolCalls(
        (
            "**排除医学与护理的影响**\n"
            "医学和护理会收窄候选范围。\n\n"
            "**接受财会方向的影响**\n"
            "财会可以作为后续可接受方向先看。"
        ),
        [
            ToolCallPart(
                tool_name="analyze_current_major_interest",
                args={"intent_mode": "preference"},
                tool_call_id="major-interest-readonly",
            )
        ],
        [
            ToolReturnPart(
                tool_name="analyze_current_major_interest",
                content="只读专业影响分析",
                tool_call_id="major-interest-readonly",
            )
        ],
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "session-stale-pending-readonly-major-interest",
                "user-57",
                "医学护理这些别碰，财会还能接受，先看看影响",
            )
        )

    assert isinstance(reply, str)
    assert "收窄候选范围" not in reply
    assert "不会改小基础可选范围" in reply
    assert "后续推荐、方案检查和方案调整参考" in reply
    assert "待确认内容" not in reply
    assert "尚未确认" not in reply
    assert "点击采纳前不会写入后续报考参考" not in reply


def test_chat_service_handle_intent_select_constraint_returns_pending_confirmation_card(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    selected_payload = {
        "message_id": 2001,
        "selected": [{"city_intents": {"negative_province": ["北京"]}}],
    }
    message_content = {
        "intentMode": "constraint",
        "clickable": True,
        "clicked": False,
        "items": [{"value": {"city_intents": {"negative_province": ["北京"]}}}],
    }

    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()
    with patch("app.service.ChatAgent"), \
            patch(
                "app.service.get_user_score_detail",
                AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}}),
            ), \
            patch(
                "app.service.get_message_by_id",
                AsyncMock(return_value={"data": {"content": json.dumps(message_content, ensure_ascii=False)}}),
            ), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch("app.service._apply_selected_intents", AsyncMock()) as apply_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_intent_select(
                "31",
                "user-31",
                json.dumps(selected_payload, ensure_ascii=False),
            )
        )

    card_payload = _assert_pending_card_envelope(
        reply,
        "",
        "apply_selected_intents",
        kind="intent_change",
    )
    assert card_payload["kind"] == "intent_change"
    assert card_payload["confirmText"] == "采纳"
    assert pending_state["value"]["pendingId"] == card_payload["pendingId"]
    assert pending_state["value"]["kind"] == "intent_change"
    assert pending_state["value"]["executionPayload"]["intentMode"] == "constraint"
    apply_mock.assert_not_awaited()


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
            patch("app.service.get_pending_confirmation", get_pending_mock):
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
            patch("app.service.get_pending_confirmation", get_pending_mock):
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
            patch("app.service.get_pending_confirmation", get_pending_mock):
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
            patch("app.service.get_pending_confirmation", get_pending_mock):
        pending_result = asyncio.run(_create_pending_intent_confirmation_result_from_preview_payload("34-gap", preview_payload))
        card = pending_result.card

    assert card is None
    assert pending_result.blocked_reasons == ["compiled_plan_fix_blocked"]
    assert pending_state == {}


def test_chat_service_handle_intent_select_preference_returns_pending_confirmation_card(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    selected_payload = {
        "message_id": 2002,
        "selected": [{"city_intents": {"negative_province": ["北京"]}}],
    }
    message_content = {
        "intentMode": "preference",
        "clickable": True,
        "clicked": False,
        "items": [{"value": {"city_intents": {"negative_province": ["北京"]}}}],
    }

    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()
    with patch("app.service.ChatAgent"), \
            patch(
                "app.service.get_user_score_detail",
                AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}}),
            ), \
            patch(
                "app.service.get_message_by_id",
                AsyncMock(return_value={"data": {"content": json.dumps(message_content, ensure_ascii=False)}}),
            ), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch("app.service._apply_selected_intents", AsyncMock()) as apply_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_intent_select(
                "32",
                "user-32",
                json.dumps(selected_payload, ensure_ascii=False),
            )
        )

    card_payload = _assert_pending_card_envelope(
        reply,
        "",
        "apply_selected_intents",
        kind="intent_change",
    )
    assert card_payload["kind"] == "intent_change"
    assert card_payload["summary"] == "不优先地域：北京"
    assert "适当靠后" in card_payload["impact"]
    assert "直接删除当前方案" not in card_payload["impact"]
    assert pending_state["value"]["executionPayload"]["intentMode"] == "preference"
    assert pending_state["value"]["summary"] == "不优先地域：北京"
    compiled_id = pending_state["value"]["compiledProposalId"]
    assert compiled_id.startswith("intent-select:32:")
    assert pending_state["value"]["compilerSink"] == {
        "compiledProposalId": compiled_id,
        "sinkType": "intent",
    }
    assert pending_state["value"]["executionPayload"]["compiledProposalId"] == compiled_id
    apply_mock.assert_not_awaited()


def test_chat_service_handle_intent_select_compiled_path_creates_same_pending_card(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    selected_payload = {
        "message_id": 2002,
        "selected": [{"city_intents": {"negative_province": ["北京"]}}],
    }
    message_content = {
        "intentMode": "preference",
        "clickable": True,
        "clicked": False,
        "items": [{"value": {"city_intents": {"negative_province": ["北京"]}}}],
    }
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.ChatAgent"), \
            patch(
                "app.service.get_user_score_detail",
                AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}}),
            ), \
            patch(
                "app.service.get_message_by_id",
                AsyncMock(return_value={"data": {"content": json.dumps(message_content, ensure_ascii=False)}}),
            ), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch("app.domain.proposal_compiler.compile_intent_select_proposal", wraps=proposal_compiler.compile_intent_select_proposal) as compiled_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_intent_select(
                "32",
                "user-32",
                json.dumps(selected_payload, ensure_ascii=False),
            )
        )

    card_payload = _assert_pending_card_envelope(reply, "", "apply_selected_intents", kind="intent_change")
    assert card_payload["summary"] == "不优先地域：北京"
    assert pending_state["value"]["summary"] == "不优先地域：北京"
    assert pending_state["value"]["executionPayload"]["intentMode"] == "preference"
    compiled_id = pending_state["value"]["compiledProposalId"]
    assert compiled_id.startswith("intent-select:32:")
    assert pending_state["value"]["compilerSink"] == {
        "compiledProposalId": compiled_id,
        "sinkType": "intent",
    }
    assert pending_state["value"]["executionPayload"]["compiledProposalId"] == compiled_id
    compiled_mock.assert_called_once()


def test_chat_service_handle_intent_select_preference_returns_primary_reply(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    selected_payload = {
        "message_id": 2002,
        "selected": [{"city_intents": {"negative_province": ["北京"]}}],
    }
    message_content = {
        "intentMode": "preference",
        "clickable": True,
        "clicked": False,
        "items": [{"value": {"city_intents": {"negative_province": ["北京"]}}}],
    }
    followup_result = {
        "actionType": "prefer_confirm",
        "analysisPayload": {
            "status": "ready",
            "sessionId": "32",
            "title": "待确认地域偏好",
            "intentMode": "preference",
            "analysisStage": "confirmed",
            "items": [
                {
                    "content": "偏好地域：北京",
                    "selected": True,
                    "value": {"city_intents": {"province": ["北京"]}},
                }
            ],
        },
    }
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()
    with patch("app.service.ChatAgent"), \
            patch(
                "app.service.get_user_score_detail",
                AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}}),
            ), \
            patch(
                "app.service.get_message_by_id",
                AsyncMock(return_value={"data": {"content": json.dumps(message_content, ensure_ascii=False)}}),
            ), \
            patch("app.service.handle_interest_analysis_action_result", AsyncMock(return_value=json.dumps(followup_result, ensure_ascii=False))), \
            patch("app.service.parse_explore_followup_result", return_value=SimpleNamespace(**followup_result)), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch("app.service.generate_user_goal_planning_fix_proposals", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_intent_select(
                "32",
                "user-32",
                json.dumps(selected_payload, ensure_ascii=False),
            )
        )

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert reply.primary
    assert "北京" in reply.primary
    assert "采纳" in reply.primary
    assert len(reply.followups) == 1


def test_chat_service_interest_prefer_confirm_returns_pending_confirmation_card(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    selected_payload = {
        "action": "interestAction",
        "actionType": "prefer_confirm",
        "message_id": 3001,
    }
    structured_result = {
        "actionType": "prefer_confirm",
        "sessionId": "36",
        "intentMode": "preference",
        "handled": True,
        "messageCode": "intent_analysis",
        "analysisPayload": {
            "status": "ready",
            "sessionId": "36",
            "title": "待确认地域偏好",
            "intentMode": "preference",
            "analysisStage": "confirmed",
            "items": [
                {
                    "content": "偏好地域：北京",
                    "value": {"city_intents": {"province": ["北京"]}},
                    "selected": True,
                }
            ],
            "existingItems": [],
        },
        "delegatedText": "待确认内容：偏好地域北京。点“采纳”前不会生效。",
    }
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()
    with patch("app.service.ChatAgent"), \
            patch(
                "app.service.get_user_score_detail",
                AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}}),
            ), \
            patch(
                "app.service.handle_interest_analysis_action_result",
                new=AsyncMock(return_value=json.dumps(structured_result, ensure_ascii=False)),
            ) as followup_mock, \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_intent_select(
                "36",
                "user-36",
                json.dumps(selected_payload, ensure_ascii=False),
            )
        )

    card_payload = _assert_pending_card_envelope(
        reply,
        "",
        "apply_selected_intents",
        kind="intent_change",
    )
    assert card_payload["summary"] == "偏好地域：北京"
    assert pending_state["value"]["kind"] == "intent_change"
    assert pending_state["value"]["executionPayload"]["selectedData"]["selected"] == [
        {"city_intents": {"province": ["北京"]}}
    ]
    compiled_id = pending_state["value"]["compiledProposalId"]
    assert compiled_id.startswith("intent-preview:36:")
    assert pending_state["value"]["compilerSink"] == {
        "compiledProposalId": compiled_id,
        "sinkType": "intent",
    }
    assert pending_state["value"]["executionPayload"]["compiledProposalId"] == compiled_id
    followup_mock.assert_awaited_once_with(
        session_id="36",
        batch="01",
        action_type="prefer_confirm",
    )


def test_chat_service_interest_prefer_confirm_compiled_preview_traces_pending(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    selected_payload = {
        "action": "interestAction",
        "actionType": "prefer_confirm",
        "message_id": 3001,
    }
    structured_result = {
        "actionType": "prefer_confirm",
        "sessionId": "36",
        "intentMode": "preference",
        "handled": True,
        "messageCode": "intent_analysis",
        "analysisPayload": {
            "status": "ready",
            "sessionId": "36",
            "title": "待确认地域偏好",
            "intentMode": "preference",
            "analysisStage": "confirmed",
            "items": [
                {
                    "content": "偏好地域：北京",
                    "value": {"city_intents": {"province": ["北京"]}},
                    "selected": True,
                }
            ],
            "existingItems": [],
        },
        "delegatedText": "待确认内容：偏好地域北京。点“采纳”前不会生效。",
    }
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.ChatAgent"), \
            patch(
                "app.service.get_user_score_detail",
                AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}}),
            ), \
            patch(
                "app.service.handle_interest_analysis_action_result",
                new=AsyncMock(return_value=json.dumps(structured_result, ensure_ascii=False)),
            ), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch("app.domain.proposal_compiler.compile_intent_preview_proposal", wraps=proposal_compiler.compile_intent_preview_proposal) as compiled_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_intent_select(
                "36",
                "user-36",
                json.dumps(selected_payload, ensure_ascii=False),
            )
        )

    card_payload = _assert_pending_card_envelope(
        reply,
        "",
        "apply_selected_intents",
        kind="intent_change",
    )
    assert card_payload["summary"] == "偏好地域：北京"
    compiled_id = pending_state["value"]["compiledProposalId"]
    assert compiled_id.startswith("intent-preview:36:")
    assert pending_state["value"]["compilerSink"] == {
        "compiledProposalId": compiled_id,
        "sinkType": "intent",
    }
    assert pending_state["value"]["executionPayload"]["compiledProposalId"] == compiled_id
    compiled_mock.assert_called_once()


def test_chat_service_interest_constrain_confirm_fallback_uses_compiled_intent_preview(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    selected_payload = {
        "action": "interestAction",
        "actionType": "constrain_confirm",
        "message_id": 3002,
    }
    structured_result = {
        "actionType": "constrain_confirm",
        "sessionId": "36",
        "intentMode": "constraint",
        "handled": True,
        "messageCode": "intent_analysis",
        "analysisPayload": {
            "status": "ready",
            "sessionId": "36",
            "title": "待确认专业要求",
            "intentMode": "constraint",
            "constraintIntentType": "only_keep",
            "analysisStage": "confirmed",
            "items": [
                {
                    "content": "只保留专业：临床医学",
                    "value": {"major_intents": {"level3": ["临床医学"]}},
                    "selected": True,
                }
            ],
            "existingItems": [],
        },
        "delegatedText": "待确认内容：只保留临床医学。",
    }
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.ChatAgent"), \
            patch(
                "app.service.get_user_score_detail",
                AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}}),
            ), \
            patch(
                "app.service.handle_interest_analysis_action_result",
                new=AsyncMock(return_value=json.dumps(structured_result, ensure_ascii=False)),
            ), \
            patch(
                "app.service.generate_user_goal_planning_fix_proposals",
                AsyncMock(return_value={"code": 0, "data": {"proposalSource": "user_goal", "proposals": []}}),
            ), \
            patch("app.service.get_planning_state", AsyncMock(return_value=_planning_state_response(12))), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch("app.domain.proposal_compiler.compile_intent_preview_proposal", wraps=proposal_compiler.compile_intent_preview_proposal) as compiled_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_intent_select(
                "36",
                "user-36",
                json.dumps(selected_payload, ensure_ascii=False),
            )
        )

    card_payload = _assert_pending_card_envelope(
        reply,
        "",
        "apply_selected_intents",
        kind="intent_change",
    )
    assert card_payload["summary"] == "只保留专业：临床医学"
    compiled_id = pending_state["value"]["compiledProposalId"]
    assert compiled_id.startswith("intent-preview:36:")
    assert pending_state["value"]["compilerSink"] == {
        "compiledProposalId": compiled_id,
        "sinkType": "intent",
    }
    assert pending_state["value"]["executionPayload"]["compiledProposalId"] == compiled_id
    compiled_mock.assert_called_once()


def test_chat_service_interest_prefer_confirm_constraint_payload_uses_compiled_intent_preview(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    selected_payload = {
        "action": "interestAction",
        "actionType": "prefer_confirm",
        "message_id": 3003,
    }
    structured_result = {
        "actionType": "prefer_confirm",
        "sessionId": "36",
        "intentMode": "constraint",
        "handled": True,
        "messageCode": "intent_analysis",
        "analysisPayload": {
            "status": "ready",
            "sessionId": "36",
            "title": "待确认专业要求",
            "intentMode": "constraint",
            "constraintIntentType": "only_keep",
            "analysisStage": "confirmed",
            "items": [
                {
                    "content": "只保留专业：临床医学",
                    "value": {"major_intents": {"level3": ["临床医学"]}},
                    "selected": True,
                }
            ],
            "existingItems": [],
        },
        "delegatedText": "待确认内容：只保留临床医学。",
    }
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.ChatAgent"), \
            patch(
                "app.service.get_user_score_detail",
                AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}}),
            ), \
            patch(
                "app.service.handle_interest_analysis_action_result",
                new=AsyncMock(return_value=json.dumps(structured_result, ensure_ascii=False)),
            ), \
            patch(
                "app.service.generate_user_goal_planning_fix_proposals",
                AsyncMock(return_value={"code": 0, "data": {"proposalSource": "user_goal", "proposals": []}}),
            ), \
            patch("app.service.get_planning_state", AsyncMock(return_value=_planning_state_response(12))), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch("app.domain.proposal_compiler.compile_intent_preview_proposal", wraps=proposal_compiler.compile_intent_preview_proposal) as compiled_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_intent_select(
                "36",
                "user-36",
                json.dumps(selected_payload, ensure_ascii=False),
            )
        )

    card_payload = _assert_pending_card_envelope(
        reply,
        "",
        "apply_selected_intents",
        kind="intent_change",
    )
    assert card_payload["summary"] == "只保留专业：临床医学"
    compiled_id = pending_state["value"]["compiledProposalId"]
    assert compiled_id.startswith("intent-preview:36:")
    assert pending_state["value"]["compilerSink"] == {
        "compiledProposalId": compiled_id,
        "sinkType": "intent",
    }
    assert pending_state["value"]["executionPayload"]["compiledProposalId"] == compiled_id
    compiled_mock.assert_called_once()


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


@pytest.mark.skip(reason="legacy PlanQuery profile route removed; 4.0 direct query_plan owns this path")
@pytest.mark.skip(reason="legacy PlanQuery profile route removed; 4.0 direct query_plan owns this path")
def test_turn_decision_allows_candidate_pool_readonly_query_with_empty_scenario():
    decision = SimpleNamespace(
        taskLayer="plan",
        sideEffect="readonly",
        scopeAnchor="candidate_pool",
        scenario="",
        confidence=0.95,
    )

    assert _turn_decision_allows_plan_query_profile(decision, pending_exists=False) is True


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


def test_chat_service_does_not_leak_historical_workspace_refresh_when_current_turn_has_no_tools(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    history = [
        ModelRequest(parts=[UserPromptPart(content="帮我审查一下")]),
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="review_plan",
                    args={"focus": "all"},
                    tool_call_id="old-review-call",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="review_plan",
                    content=json.dumps(
                        {
                            "applied": True,
                            "action_family": "review_plan",
                            "stage": "review",
                            "result_kind": "review_result",
                            "summary": "旧审查结果。",
                            "workspace_refresh_targets": ["review"],
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="old-review-call",
                )
            ]
        ),
        ModelResponse(parts=[TextPart(content="旧审查已完成。")], model_name="test-model"),
    ]
    asyncio.run(store.save("no-tool-export-session", history))
    fake_agent = _FakeAgent([
        "专业+大学模式导出是一条学校+专业志愿一行，不按学校聚合。"
    ])
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "no-tool-export-session",
                "user-1",
                "专业模式导出是不是一条志愿一行？",
            )
        )

    assert isinstance(reply, str)
    assert "一行" in reply
    assert pending_state == {}
    save_pending_mock.assert_not_awaited()


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


def test_chat_service_applies_fix_proposal_pending_on_card_confirm(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store(
        {
            "type": "pendingConfirmation",
            "pendingId": "fix-proposal-pending-1",
            "sessionId": "fix-apply-session",
            "kind": "plan_mutation",
            "status": "active",
            "actionFamily": "apply_fix_proposal",
            "summary": "替换高风险志愿",
            "executionPayload": {
                "toolName": "apply_planning_fix_proposal",
                "proposalId": "fp_ready_1",
                "sourceVersionGuard": 18,
                "regenerateOrderedPlan": True,
                "rerunReview": True,
            },
            "sourceBackendVersion": 18,
        }
    )
    apply_result = {
        "code": 0,
        "data": {
            "status": "applied",
            "repairReport": {
                "strategy": "replace_risk_items",
                "proposalTitle": "替换高风险志愿",
                "proposalSummary": "当前方案里有高风险项需要替换。",
                "proposalImpact": "预计移出 2 条、补入 2 条。",
                "dryRunMessage": "移出 2 条，补入 2 条。",
                "addedVolunteerCount": 2,
                "removedVolunteerCount": 2,
                "postValidationPassed": True,
                "messages": ["已完成替换。"],
            },
        },
    }

    with patch("app.service.ChatAgent"), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch("app.service.apply_planning_fix_proposal", AsyncMock(return_value=apply_result)) as apply_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_pending_confirmation(
                "fix-apply-session",
                "user-1",
                json.dumps(
                    {
                        "action": "confirm",
                        "kind": "plan_mutation",
                        "pendingId": "fix-proposal-pending-1",
                    },
                    ensure_ascii=False,
                ),
            )
        )

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert "已更新方案，并刷新当前方案状态" in reply.primary
    assert "替换高风险志愿" in reply.primary
    assert "修复建议" not in reply.primary
    assert "修复类型" not in reply.primary
    assert "复验结果" not in reply.primary
    apply_mock.assert_awaited_once_with(
        1,
        "fix-apply-session",
        proposal_id="fp_ready_1",
        source_version_guard=18,
        regenerate_ordered_plan=True,
        rerun_review=True,
        proposal_source="review_check",
        user_goal_request=None,
    )
    assert pending_state["value"]["status"] == "applied"
    assert pending_state["value"]["resultCode"] == "applied"
    workspace_payloads = [json.loads(item.content) for item in reply.followups]
    assert [payload["targetView"] for payload in workspace_payloads] == ["ordered"]
    assert workspace_payloads[0]["refresh"] is True
    assert workspace_payloads[0]["silent"] is True
    saved = asyncio.run(store.load("fix-apply-session"))
    tool_names = [
        part.tool_name
        for message in saved
        for part in getattr(message, "parts", [])
        if isinstance(part, (ToolCallPart, ToolReturnPart))
    ]
    assert "apply_planning_fix_proposal" in tool_names


def test_chat_service_user_goal_fix_proposal_confirm_rebuilds_after_intent_apply(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    user_goal_request = {
        "proposalSource": "user_goal",
        "goalType": "only_keep_scope",
        "userOriginalText": "只保留临床医学",
        "confidence": "high",
        "sourceVersionGuard": 18,
        "targetScopes": [
            {
                "scopeType": "major",
                "entityType": "major",
                "name": "临床医学",
                "normalizedName": "临床医学",
                "rawText": "临床医学",
                "resolutionStatus": "resolved",
            }
        ],
        "negativeScopes": [],
        "context": {"source": "chat_service_constraint_confirmation"},
    }
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store(
        {
            "type": "pendingConfirmation",
            "pendingId": "user-goal-fix-pending-1",
            "sessionId": "user-goal-apply-session",
            "kind": "plan_mutation",
            "status": "active",
            "actionFamily": "apply_fix_proposal",
            "summary": "只保留临床医学",
            "executionPayload": {
                "toolName": "apply_planning_fix_proposal",
                "proposalId": "ug-old-18",
                "proposalSource": "user_goal",
                "sourceVersionGuard": 18,
                "strategy": "only_keep_scope",
                "userGoalRequest": user_goal_request,
                "intentPayload": {
                    "selected": [{"major_intents": {"level3": ["临床医学"]}}],
                    "intentMode": "constraint",
                    "constraintIntentType": "only_keep",
                    "batch": "01",
                },
                "regenerateOrderedPlan": True,
                "rerunReview": True,
            },
            "sourceBackendVersion": 18,
        }
    )
    intent_result = {
        "action": "apply_selected",
        "sessionId": "user-goal-apply-session",
        "intentMode": "constraint",
        "applied": True,
        "messageCode": "constraint_applied",
        "message": "已采纳这次报考条件。",
    }
    apply_result = {
        "code": 0,
        "data": {
            "status": "applied",
            "repairReport": {
                "strategy": "only_keep_scope",
                "proposalTitle": "只保留临床医学",
                "proposalSummary": "当前方案已按这条条件同步调整。",
                "dryRunMessage": "移出不符合条件的志愿。",
                "removedVolunteerCount": 2,
                "addedVolunteerCount": 0,
                "postValidationPassed": True,
            },
        },
    }
    refreshed_preview = _user_goal_fix_proposal_response(
        proposal_id="ug-refreshed-19",
        strategy="only_keep_scope",
        source_version=19,
        title="只保留临床医学",
        summary="当前方案已按最新状态重新生成可执行调整。",
    )

    with patch("app.service.ChatAgent"), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch("app.service._apply_selected_intents", new=AsyncMock(return_value=json.dumps(intent_result, ensure_ascii=False))) as intent_mock, \
            patch("app.service.get_planning_state", AsyncMock(return_value=_planning_state_response(19))) as state_mock, \
            patch("app.service.generate_user_goal_planning_fix_proposals", AsyncMock(return_value=refreshed_preview)) as proposal_mock, \
            patch("app.service.apply_planning_fix_proposal", AsyncMock(return_value=apply_result)) as apply_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_pending_confirmation(
                "user-goal-apply-session",
                "user-1",
                json.dumps(
                    {
                        "action": "confirm",
                        "kind": "plan_mutation",
                        "pendingId": "user-goal-fix-pending-1",
                    },
                    ensure_ascii=False,
                ),
            )
        )

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert "已更新方案，并刷新当前方案状态" in reply.primary
    assert "后续报考参考已同步更新" in reply.primary
    intent_mock.assert_awaited_once()
    selected_data = intent_mock.await_args.kwargs["selected_data"]
    assert selected_data["constraintIntentType"] == "only_keep"
    assert selected_data["selected"] == [{"major_intents": {"level3": ["临床医学"]}}]
    state_mock.assert_awaited_once_with("user-goal-apply-session")
    proposal_mock.assert_awaited_once()
    refreshed_req = proposal_mock.await_args.args[2]
    assert refreshed_req["goalType"] == "only_keep_scope"
    assert refreshed_req["sourceVersionGuard"] == 19
    apply_mock.assert_awaited_once()
    apply_kwargs = apply_mock.await_args.kwargs
    assert apply_kwargs["proposal_id"] == "ug-refreshed-19"
    assert apply_kwargs["source_version_guard"] == 19
    assert apply_kwargs["proposal_source"] == "user_goal"
    assert apply_kwargs["user_goal_request"]["sourceVersionGuard"] == 19
    assert pending_state["value"]["status"] == "applied"
    saved = asyncio.run(store.load("user-goal-apply-session"))
    tool_calls = [
        part
        for message in saved
        for part in getattr(message, "parts", [])
        if isinstance(part, ToolCallPart) and part.tool_name == "apply_planning_fix_proposal"
    ]
    assert tool_calls
    assert tool_calls[-1].args["proposal_id"] == "ug-refreshed-19"
    assert tool_calls[-1].args["proposal_source"] == "user_goal"


def test_chat_service_repeated_only_keep_pending_long_text_does_not_auto_apply(
    tmp_path,
    mock_llm_client,
):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store(
        {
            "type": "pendingConfirmation",
            "pendingId": "only-keep-medical-pending",
            "sessionId": "only-keep-confirm-session",
            "kind": "intent_change",
            "status": "active",
            "actionFamily": "apply_selected_intents",
            "summary": "只保留专业门类：医学",
            "constraintIntentType": "only_keep",
            "executionPayload": {
                "toolName": "apply_selected_intents",
                "selectedData": {
                    "selected": [{"major_intents": {"level1": ["医学"]}}],
                    "intentMode": "constraint",
                    "constraintIntentType": "only_keep",
                    "batch": "01",
                },
                "merged": {"major_intents": {"level1": ["医学"]}},
                "intentMode": "constraint",
                "constraintIntentType": "only_keep",
                "batch": "01",
            },
        }
    )
    fake_agent = _FakeAgent(["不应该调用模型"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch("app.service.classify_turn_decision", AsyncMock(return_value=_pending_conflict_turn_decision())), \
            patch("app.service._apply_selected_intents", new=AsyncMock()) as intent_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "only-keep-confirm-session",
                "user-1",
                "这个方案还是不行，只要医学",
            )
        )

    assert isinstance(reply, str)
    assert "待采纳内容：只保留专业门类：医学" in reply
    assert "不会直接覆盖" in reply
    assert "不会再生成第二张待采纳卡" in reply
    assert pending_state["value"]["status"] == "active"
    intent_mock.assert_not_awaited()
    assert fake_agent.calls == []


def test_chat_service_active_only_keep_pending_blocks_plain_negative_remove_preview(
    tmp_path,
    mock_llm_client,
):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store(
        {
            "type": "pendingConfirmation",
            "pendingId": "only-keep-medical-pending",
            "sessionId": "only-keep-guard-session",
            "kind": "intent_change",
            "status": "active",
            "actionFamily": "apply_selected_intents",
            "summary": "只保留专业门类：医学",
            "constraintIntentType": "only_keep",
            "executionPayload": {
                "toolName": "apply_selected_intents",
                "selectedData": {
                    "selected": [{"major_intents": {"level1": ["医学"]}}],
                    "intentMode": "constraint",
                    "constraintIntentType": "only_keep",
                    "batch": "01",
                },
                "merged": {"major_intents": {"level1": ["医学"]}},
                "intentMode": "constraint",
                "constraintIntentType": "only_keep",
                "batch": "01",
            },
        }
    )
    fake_agent = _FakeAgent(["不应该调用模型"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch("app.service.classify_turn_decision", AsyncMock(return_value=_pending_conflict_turn_decision())):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "only-keep-guard-session",
                "user-1",
                "这个方案还是不行，只要医学",
            )
        )

    assert isinstance(reply, str)
    assert "待采纳内容：只保留专业门类：医学" in reply
    assert "不会直接覆盖" in reply
    assert "不会再生成第二张待采纳卡" in reply
    assert "确认后移出这些非医学方向" not in reply
    assert pending_state["value"]["pendingId"] == "only-keep-medical-pending"
    assert pending_state["value"]["kind"] == "intent_change"
    assert pending_state["value"]["status"] == "active"
    assert fake_agent.calls == []


def test_chat_service_user_goal_tuition_budget_confirm_updates_tuition_range(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    user_goal_request = {
        "proposalSource": "user_goal",
        "goalType": "tuition_budget_scope",
        "userOriginalText": "学费最好控制在两万以内",
        "confidence": "high",
        "sourceVersionGuard": 18,
        "targetScopes": [],
        "negativeScopes": [],
        "context": {"source": "structured_goal", "maxTuitionPerYear": 20000},
    }
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store(
        {
            "type": "pendingConfirmation",
            "pendingId": "user-goal-tuition-pending-1",
            "sessionId": "user-goal-tuition-apply-session",
            "kind": "plan_mutation",
            "status": "active",
            "actionFamily": "apply_fix_proposal",
            "summary": "控制学费上限",
            "executionPayload": {
                "toolName": "apply_planning_fix_proposal",
                "proposalId": "ug-budget-old-18",
                "proposalSource": "user_goal",
                "sourceVersionGuard": 18,
                "strategy": "tuition_budget_scope",
                "userGoalRequest": user_goal_request,
                "regenerateOrderedPlan": True,
                "rerunReview": True,
            },
            "sourceBackendVersion": 18,
        }
    )
    apply_result = {
        "code": 0,
        "data": {
            "status": "applied",
            "repairReport": {
                "strategy": "tuition_budget_scope",
                "proposalTitle": "控制学费上限",
                "proposalSummary": "已按预算上限调整当前方案。",
                "dryRunMessage": "移出 2 条，补入 2 条。",
                "removedVolunteerCount": 2,
                "addedVolunteerCount": 2,
                "postValidationPassed": True,
            },
        },
    }
    refreshed_preview = _user_goal_fix_proposal_response(
        proposal_id="ug-budget-refreshed-19",
        strategy="tuition_budget_scope",
        source_version=19,
        title="控制学费上限",
        summary="已按最新状态重新生成预算调整预览。",
    )

    with patch("app.service.ChatAgent"), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch("app.service.get_planning_state", AsyncMock(return_value=_planning_state_response(19))) as state_mock, \
            patch("app.service.generate_user_goal_planning_fix_proposals", AsyncMock(return_value=refreshed_preview)) as proposal_mock, \
            patch("app.service.apply_planning_fix_proposal", AsyncMock(return_value=apply_result)) as apply_mock, \
            patch("app.service.update_session_tuition_range", AsyncMock(return_value={"code": 0, "data": True})) as tuition_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_pending_confirmation(
                "user-goal-tuition-apply-session",
                "user-1",
                json.dumps(
                    {
                        "action": "confirm",
                        "kind": "plan_mutation",
                        "pendingId": "user-goal-tuition-pending-1",
                    },
                    ensure_ascii=False,
                ),
            )
        )

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert "已更新方案，并刷新当前方案状态" in reply.primary
    assert "每年不超过 20000 元" in reply.primary
    state_mock.assert_not_awaited()
    proposal_mock.assert_not_awaited()
    apply_mock.assert_awaited_once()
    apply_kwargs = apply_mock.await_args.kwargs
    assert apply_kwargs["proposal_id"] == "ug-budget-old-18"
    assert apply_kwargs["source_version_guard"] == 18
    assert apply_kwargs["proposal_source"] == "user_goal"
    assert apply_kwargs["user_goal_request"]["context"]["maxTuitionPerYear"] == 20000
    tuition_mock.assert_awaited_once_with(
        "user-goal-tuition-apply-session",
        min_tuition=0,
        max_tuition=20000,
    )
    workspace_payloads = [json.loads(item.content) for item in reply.followups]
    assert [payload["targetView"] for payload in workspace_payloads] == ["ordered", "candidate", "review"]
    assert pending_state["value"]["status"] == "applied"


def test_chat_service_answers_profile_change_state_query_from_structured_replan_state(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    dsl = {
        "type": "ProfileChangeReplan",
        "scopeAnchor": "current_profile",
        "sideEffect": "profile_change_replan",
        "profileMode": "current_student_update",
        "proposedProfile": {"score": 620, "province": "湖北", "subjects": ["物理", "化学", "生物"], "subjectCombo": "物化生"},
        "proposedProfileSummary": "620分、湖北、物化生",
        "currentProfile": {"score": 548, "province": "湖南", "subjects": ["历史", "生物", "政治"]},
        "currentProfileSummary": "548分、湖南、历史、生物、政治",
        "requiredAction": ["confirm_profile_update", "recalculate_candidate_pool", "regenerate_plan"],
        "stalePlanPolicy": {"formalPlan": "preserve_as_old_until_recalculated"},
        "sourceVersionGuard": 31,
    }
    history = [
        ModelRequest(parts=[UserPromptPart(content="那基于620湖北物化生重来")]),
        ModelResponse(
            parts=[
                TextPart(
                    content=json.dumps(
                        {
                            "type": "routeObservability",
                            "event": "conversation_turn_event",
                            "routingPath": "semantic_profile_change_replan",
                            "routeDecision": {"profileChangeReplanDsl": dsl},
                        },
                        ensure_ascii=False,
                    )
                )
            ],
            model_name="route-observability",
        ),
        ModelResponse(parts=[TextPart(content="可以按 620分、湖北、物化生 重新规划。")], model_name="semantic-profile-change-replan"),
    ]
    asyncio.run(store.save("profile-change-state-query-session", history))
    pending_state = {
        "type": "pendingConfirmation",
        "pendingId": "school-pending-1",
        "kind": "intent_change",
        "status": "active",
        "summary": "偏好院校：华中科技大学",
        "actionFamily": "apply_selected_intents",
    }

    with patch("app.service.ChatAgent", return_value=_FakeAgent(["不应该进入完整 Agent"])), \
            patch("app.service._load_pending_confirmation_state", AsyncMock(return_value=pending_state)), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={
                "code": 0,
                "data": {"userScoreDetail": {"totalScore": 548, "province": "湖南", "subjectList": ["历史", "生物", "政治"]}},
            })), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={
                "code": 0,
                "data": {
                    "phase": "reviewed",
                    "version": 31,
                    "orderedPlanState": {"summary": {"total": 45}},
                    "reviewState": {"summary": {"warnCount": 1, "riskCount": 0}, "checks": []},
                },
            })), \
            patch(
                "app.service.classify_turn_decision",
                AsyncMock(return_value=_runtime_turn_decision(
                    task_layer="plan",
                    side_effect="readonly_while_pending",
                    scope_anchor="current_profile",
                    scenario="profile_change_state_query",
                    confidence=0.95,
                )),
            ) as turn_decision_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "profile-change-state-query-session",
                "user-1",
                "现在方案是按620湖北算的吧",
            )
        )

    assert isinstance(reply, str)
    assert "还不能说当前正式方案已经按 620分、湖北、物化生 重算" in reply
    assert "当前方案仍按 548分、湖南、历史、生物、政治 保留" in reply
    assert "华中科技大学" in reply
    turn_decision_mock.assert_awaited_once()
    saved = asyncio.run(store.load("profile-change-state-query-session"))
    latest_event = _route_observability_events(saved)[-1]
    assert latest_event["routingPath"] == "profile_change_replan_state_query"
    assert latest_event["routeDecision"]["source"] == "turn_decision+proposal_compiler"
    assert latest_event["routeDecision"]["turnDecision"]["scenario"] == "profile_change_state_query"


def test_chat_service_merges_profile_replan_correction_from_structured_state(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    previous_dsl = {
        "type": "ProfileChangeReplan",
        "scopeAnchor": "current_profile",
        "sideEffect": "profile_change_replan",
        "profileMode": "current_student_update",
        "proposedProfile": {"score": 630, "province": "湖北", "subjectCombo": "物化生"},
        "proposedProfileSummary": "630分、湖北、物化生",
        "currentProfile": {"score": 548, "province": "湖南", "subjects": ["历史", "生物", "政治"]},
        "currentProfileSummary": "548分、湖南、历史、生物、政治",
        "requiredAction": ["confirm_profile_update", "recalculate_candidate_pool", "regenerate_plan"],
        "stalePlanPolicy": {"formalPlan": "preserve_as_old_until_recalculated"},
        "sourceVersionGuard": 31,
    }
    history = [
        ModelRequest(parts=[UserPromptPart(content="那基于630湖北物化生重来")]),
        ModelResponse(
            parts=[
                TextPart(
                    content=json.dumps(
                        {
                            "type": "routeObservability",
                            "event": "conversation_turn_event",
                            "routingPath": "turn_decision_profile_change_replan",
                            "routeDecision": {"profileChangeReplanDsl": previous_dsl},
                        },
                        ensure_ascii=False,
                    )
                )
            ],
            model_name="route-observability",
        ),
        ModelResponse(parts=[TextPart(content="可以按 630分、湖北、物化生 重新规划。")], model_name="turn-decision-profile-change-replan"),
    ]
    asyncio.run(store.save("profile-replan-merge-session", history))

    with patch("app.service.ChatAgent", return_value=_FakeAgent(["不应该进入完整 Agent"])), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={
                "code": 0,
                "data": {"userScoreDetail": {"totalScore": 548, "province": "湖南", "subjectList": ["历史", "生物", "政治"]}},
            })), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={
                "code": 0,
                "data": {
                    "phase": "reviewed",
                    "version": 31,
                    "orderedPlanState": {"summary": {"total": 45}},
                    "reviewState": {"summary": {"warnCount": 1, "riskCount": 0}, "checks": []},
                },
            })), \
            patch(
                "app.service.classify_turn_decision",
                AsyncMock(return_value=_runtime_turn_decision(
                    task_layer="plan",
                    side_effect="profile_change_replan",
                    scope_anchor="current_profile",
                    scenario="profile_update_replan",
                    profile_scenario="current_student_update",
                    proposed_profile={"score": 620},
                    confidence=0.95,
                )),
            ) as turn_decision_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "profile-replan-merge-session",
                "user-1",
                "分数也说错了应该是620不是630",
            )
        )

    assert isinstance(reply, str)
    assert "620分、湖北、物化生" in reply
    turn_decision_mock.assert_awaited_once()
    saved = asyncio.run(store.load("profile-replan-merge-session"))
    latest_event = _route_observability_events(saved)[-1]
    dsl = latest_event["routeDecision"]["profileChangeReplanDsl"]
    assert dsl["proposedProfile"] == {"score": 620, "province": "湖北", "subjectCombo": "物化生"}
    assert set(dsl["mergedFromPreviousProposedProfileFields"]) == {"province", "subjectCombo"}
    assert dsl["missingProfileFields"] == []


def test_chat_service_does_not_recover_unbacked_intent_preview_even_with_active_intent_pending(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    previous_pending = {
        "type": "pendingConfirmation",
        "pendingId": "old-medical-pending",
        "sessionId": "active-pending-unbacked-intent-session",
        "kind": "intent_change",
        "status": "active",
        "actionFamily": "apply_selected_intents",
        "summary": "只保留专业门类：医学；排除专业门类：工学",
        "executionPayload": {
            "toolName": "apply_selected_intents",
            "selectedData": {
                "selected": [
                    {"major_intents": {"level1": ["医学"]}},
                    {"major_intents": {"negative_level1": ["工学"]}},
                ],
                "intentMode": "constraint",
                "constraintIntentType": "only_keep",
            },
        },
    }
    bad_reply = (
        "明白了，你的意思是只保留医学类方向。\n\n"
        "**准备采纳的内容：**\n"
        "- 只保留：医学门类\n"
        "- 排除：除医学外的所有专业门类\n\n"
        "请确认是否采纳这条报考条件？"
    )
    fake_agent = _FakeAgent([bad_reply])
    recovered_payload = {
        "status": "ready",
        "sessionId": "active-pending-unbacked-intent-session",
        "title": "待确认要求",
        "intentMode": "constraint",
        "constraintIntentType": "only_keep",
        "analysisStage": "confirmed",
        "items": [
            {
                "content": "把医学记成明确要满足的专业门类要求，后面看候选和方案时会按这个范围来。",
                "value": {"major_intents": {"level1": ["医学"]}},
                "selected": True,
            }
        ],
        "existingItems": [],
    }
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store(previous_pending)
    recover_mock = AsyncMock(return_value=json.dumps(recovered_payload, ensure_ascii=False))

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.analyze_volunteer_intent_change", recover_mock), \
            patch("app.service.classify_turn_decision", AsyncMock(return_value=_pending_conflict_turn_decision())), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "active-pending-unbacked-intent-session",
                "user-1",
                "这个方案还是不行，只要医学",
            )
        )

    assert isinstance(reply, str)
    assert "准备采纳的内容" not in reply
    assert "待采纳内容：只保留专业门类：医学；排除专业门类：工学" in reply
    assert "不会直接覆盖" in reply
    assert "不会再生成第二张待采纳卡" in reply
    assert pending_state["value"] == previous_pending
    recover_mock.assert_not_awaited()
    save_pending_mock.assert_not_awaited()
    assert fake_agent.calls == []


def test_chat_service_handle_intent_select_followup_consumes_structured_result(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    selected_payload = {
        "message_id": 3001,
        "actionType": "candidate_query",
    }
    structured_result = {
        "actionType": "candidate_query",
        "sessionId": "34",
        "intentMode": "preference",
        "handled": True,
        "messageCode": "custom_followup_code_without_text_coupling",
        "message": "结构化 follow-up 成功",
        "candidateFilters": {"provinceNames": ["北京"]},
        "filteredTotal": 12,
        "baseTotal": 300,
    }

    with patch("app.service.ChatAgent"), \
            patch(
                "app.service.get_user_score_detail",
                AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}}),
            ), \
            patch(
                "app.service.handle_interest_analysis_action_result",
                new=AsyncMock(return_value=json.dumps(structured_result, ensure_ascii=False)),
            ) as followup_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_intent_select(
                "34",
                "user-34",
                json.dumps(selected_payload, ensure_ascii=False),
            )
        )

    assert reply == "结构化 follow-up 成功"
    followup_mock.assert_awaited_once_with(
        session_id="34",
        batch="01",
        action_type="candidate_query",
    )
