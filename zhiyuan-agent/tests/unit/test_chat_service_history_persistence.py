"""Tests for ChatService persistence and model-first dialog entry."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart

import app.service as service_module
from app.config import HistoryConfig
from app.data.history_store import ChatHistoryStore
from app.schemas.ws import WSResponse
from app.service import (
    ChatService,
    ChatServiceResponseEnvelope,
    _append_plan_preview_confirmation_boundary,
    _build_plan_timeout_fallback_reply,
    _create_pending_intent_confirmation_from_preview_payload,
    build_runtime_history,
    build_timeout_fallback_from_recent_plan_execution,
    _extract_pending_plan_action,
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
    _normalize_user_facing_terms,
    _sanitize_reply_for_user,
    _summarize_intent_values,
    _is_pending_readonly_impact_question,
    _build_pending_readonly_impact_reply,
    _build_pending_plan_action_from_payload,
    _selected_data_with_existing_positive_context,
    _select_conversation_action_family,
    _extract_recent_intent_analysis_payload,
    _guard_unbacked_plan_confirmation_reply,
    _tool_calls_include_plan_workspace_refresh,
)
from app.tools.intent_response_tool import IntentStateUpdateResult, render_intent_state_update

# Service no longer imports the legacy planEditCache reader. Many history tests
# still patch this old target to assert it is not read, so keep a test-only
# placeholder instead of reintroducing the runtime dependency.
if not hasattr(service_module, "get_intent_change_cache"):
    service_module.get_intent_change_cache = AsyncMock()


def _semantic_pending(action: str, confidence: float = 0.95, reason: str = "test"):
    return MagicMock(action=action, confidence=confidence, reason=reason)


def _semantic_plan(action_family: str, confidence: float = 0.95, reason: str = "test"):
    return MagicMock(
        actionFamily=action_family,
        confidence=confidence,
        reason=reason,
        targetStrategies=[],
    )


def _tool_return(action_family: str) -> ToolReturnPart:
    return ToolReturnPart(
        tool_name="execute_plan_action",
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


def test_build_pending_plan_action_rejects_unresolved_position_preview():
    pending = _build_pending_plan_action_from_payload(
        {
            "applied": False,
            "action_family": "move_ordered_unit",
            "stage": "analyze",
            "result_kind": "preview_only",
            "summary": "当前方案里还没有可移动的志愿。",
            "facts": {"position_resolution": "empty_plan"},
            "atomic_actions": [
                {
                    "action_type": "move_ordered_unit",
                    "source_positions": [8],
                    "target_position": 12,
                }
            ],
        }
    )

    assert pending is None


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


def test_pending_readonly_impact_question_detects_non_confirming_followup():
    assert _is_pending_readonly_impact_question("先不确认，看看这个偏好会影响当前方案吗") is True
    assert _is_pending_readonly_impact_question("确认") is False


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
    assert "不会移出" in reply
    assert "会计学" in reply
    assert "土木工程" in reply


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
    assert "blocked" not in normalized
    assert "暂不能自动处理" not in normalized
    assert "无法生成确认" not in normalized
    assert "preview_only" not in normalized
    assert "需要注意" in normalized
    assert "需要你先决定是否接受调整范围变化" in normalized
    assert "建议你先查看具体影响，或调整筛选范围后再试" in normalized


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
    assert "可选范围" in normalized
    assert "当前暂时缺少合适的补位选择" in normalized
    assert "不能一次性处理完" in normalized
    assert "需要你先取舍或手动调整" in normalized


def test_sanitize_reply_for_user_does_not_duplicate_confirmation_boundary():
    reply = _sanitize_reply_for_user(
        "可以调整当前方案。\n\n"
        "如果要正式更新想法、报考条件或方案，我会先列出要采用的内容或调整预览；采纳/确认前不会生效。"
    )

    assert reply.count("采纳/确认前不会生效") == 1


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
                "pending_plan_action": deps.pending_plan_action if deps else None,
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


def test_chat_service_recovers_plan_preview_card_when_model_interrupts_after_tool_preview(
    tmp_path,
    mock_llm_client,
):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    source_payload = {
        "stage": "preview",
        "action_family": "remove_units",
        "user_goal": "把太贵的那几个先去掉看看",
        "requires_confirmation": True,
        "missing_inputs": [],
        "atomic_actions": [
            {
                "action_type": "remove_units",
                "review_issue_target": {
                    "code": "high_tuition",
                    "scope_mode": "full_issue",
                    "label": "高收费",
                    "scope_kind": "item_removal",
                    "default_action_family": "remove_units",
                },
            }
        ],
        "preview_summary": "会按当前审查命中的整批高收费项执行移除。",
    }
    recent_result = {
        "applied": False,
        "action_family": "remove_units",
        "stage": "preview",
        "result_kind": "preview_only",
        "summary": "已定位到当前方案里当前审查命中的高收费项：共 3 个专业组，涉及 8 条志愿。确认后我会先移出这些项，并在执行后重新审查。",
        "_pending_source_payload": source_payload,
    }
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
            patch("app.service.consume_recent_plan_execution_result", return_value=recent_result), \
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

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert reply.primary == ""
    card = _assert_pending_card_envelope(reply, "", "remove_units")
    assert card["title"] == "确认移出志愿"
    assert "高收费项" in card["content"]
    saved_payload = json.loads(pending_state["value"]["executionPayload"]["planPayload"])
    assert saved_payload["stage"] == "apply"
    assert saved_payload["action_family"] == "remove_units"
    assert saved_payload["atomic_actions"][0]["review_issue_target"]["code"] == "high_tuition"


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
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"code": 1})), \
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
                    "pendingActions": [{"summary": "补充保区志愿"}],
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
                        tool_name="execute_plan_action",
                        args={"plan_payload": "{}"},
                        tool_call_id="tool-long",
                    )
                ],
                model_name="test",
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="execute_plan_action",
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
        pending_plan_action=None,
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
                        tool_name="execute_plan_action",
                        args={
                            "plan_payload": json.dumps(
                                {
                                    "stage": "preview",
                                    "action_family": "sort_ordered_plan",
                                    "user_goal": "按院校层次排序",
                                    "missing_inputs": [],
                                    "atomic_actions": [],
                                },
                                ensure_ascii=False,
                            )
                        },
                        tool_call_id="pending-sort-call",
                    )
                ],
                model_name="test",
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="execute_plan_action",
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
        pending_plan_action={"action_family": "sort_ordered_plan"},
        config=config,
    )

    assert runtime.has_pending is True
    assert runtime.runtime_len > config.runtime_max_messages
    assert any(
        isinstance(part, ToolCallPart)
        and part.tool_name == "execute_plan_action"
        and part.tool_call_id == "pending-sort-call"
        for message in runtime.model_history or []
        for part in getattr(message, "parts", [])
    )
    assert any(
        isinstance(part, ToolReturnPart)
        and part.tool_name == "execute_plan_action"
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
    clear_legacy_cache_mock = AsyncMock(return_value={"code": 0})

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "02"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.save_intent_change_cache", clear_legacy_cache_mock), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message("990501", "user-1", "北京优先")
        )

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert reply.primary == ""
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
    clear_legacy_cache_mock.assert_awaited_once_with(990501, {})


def test_chat_service_only_keep_major_preview_removes_non_matching_plan_items(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    preview_payload = {
        "status": "ready",
        "sessionId": "9905012",
        "title": "待采纳报考条件",
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
        "message": "准备采纳：只保留专业：临床医学",
    }
    fake_agent = _FakeIntentPreviewAgent(
        preview_payload,
        tool_name="preview_current_major_intent_confirmation",
    )
    workspace_state = {
        "code": 0,
        "data": {
            "orderedPlanState": {
                "items": [
                    {
                        "volunteerId": "keep-clinical",
                        "schoolName": "A大学",
                        "majorName": "临床医学",
                    },
                    {
                        "volunteerId": "remove-nursing",
                        "schoolName": "B大学",
                        "majorName": "护理学",
                    },
                ]
            }
        },
    }
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()
    captured_plan_payload: dict = {}

    async def fake_execute_plan_action(_ctx, plan_payload):
        captured_plan_payload.update(json.loads(plan_payload))
        return json.dumps(
            {
                "applied": False,
                "action_family": "remove_units",
                "stage": "preview",
                "result_kind": "preview_only",
                "summary": captured_plan_payload.get("preview_summary"),
                "facts": {
                    "matched_count": 1,
                    "resolved_apply_payload": {
                        "action_family": "remove_units",
                        "atomic_actions": captured_plan_payload.get("atomic_actions", []),
                    },
                },
            },
            ensure_ascii=False,
        )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value=workspace_state)), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.execute_plan_action", AsyncMock(side_effect=fake_execute_plan_action)), \
            patch("app.service.save_intent_change_cache", AsyncMock(return_value={"code": 0})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message("9905012", "user-1", "仅保留临床医学")
        )

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert len(reply.followups) == 1
    card_payload = json.loads(reply.followups[0].content)
    assert card_payload["kind"] == "plan_mutation"
    assert card_payload["actionFamily"] == "remove_units"
    assert "只保留" in card_payload["content"]
    assert captured_plan_payload["atomic_actions"][0]["volunteer_ids"] == ["remove-nursing"]
    assert "keep-clinical" not in captured_plan_payload["atomic_actions"][0]["volunteer_ids"]
    pending = pending_state["value"]
    assert pending["kind"] == "plan_mutation"
    execution_payload = pending["executionPayload"]
    pending_plan_payload = json.loads(execution_payload["planPayload"])
    atomic_actions = pending_plan_payload["atomic_actions"]
    assert atomic_actions[0]["volunteer_ids"] == ["remove-nursing"]
    assert "keep-clinical" not in atomic_actions[0]["volunteer_ids"]
    assert execution_payload["intentPayload"]["constraintIntentType"] == "only_keep"
    composite = pending["compositeProposal"]
    assert composite["goal"]["goal_type"] == "only_keep_scope"
    assert composite["goal"]["target_scopes"] == [
        {"entity_type": "major", "values": ["临床医学"]}
    ]
    assert composite["intent_updates"][0]["constraintIntentType"] == "only_keep"
    assert composite["plan_actions"][0]["action_type"] == "remove_units"
    assert composite["plan_actions"][0]["volunteer_ids"] == ["remove-nursing"]
    assert pending_plan_payload["composite_proposal"]["goal"]["goal_type"] == "only_keep_scope"


def test_chat_service_must_have_major_preview_adds_when_missing_from_plan(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    preview_payload = {
        "status": "ready",
        "sessionId": "9905013",
        "title": "待采纳报考条件",
        "intentMode": "constraint",
        "constraintIntentType": "must_have",
        "analysisStage": "confirmed",
        "items": [
            {
                "content": "至少保留专业：临床医学",
                "value": {"major_intents": {"level3": ["临床医学"]}},
                "selected": True,
            }
        ],
        "existingItems": [],
        "message": "至少保留专业：临床医学",
    }
    fake_agent = _FakeIntentPreviewAgent(
        preview_payload,
        tool_name="preview_current_major_intent_confirmation",
    )
    workspace_state = {
        "code": 0,
        "data": {
            "orderedPlanState": {
                "items": [
                    {
                        "volunteerId": "nursing-1",
                        "schoolName": "B大学",
                        "majorName": "护理学",
                    },
                ]
            }
        },
    }
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()
    captured_plan_payload: dict = {}

    async def fake_execute_plan_action(_ctx, plan_payload):
        captured_plan_payload.update(json.loads(plan_payload))
        return json.dumps(
            {
                "applied": False,
                "action_family": "add_units",
                "stage": "preview",
                "result_kind": "preview_only",
                "summary": captured_plan_payload.get("preview_summary"),
                "facts": {
                    "resolved_apply_payload": {
                        "action_family": "add_units",
                        "atomic_actions": captured_plan_payload.get("atomic_actions", []),
                    },
                },
            },
            ensure_ascii=False,
        )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value=workspace_state)), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.execute_plan_action", AsyncMock(side_effect=fake_execute_plan_action)), \
            patch("app.service.save_intent_change_cache", AsyncMock(return_value={"code": 0})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message("9905013", "user-1", "必须有临床医学")
        )

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert len(reply.followups) == 1
    card_payload = json.loads(reply.followups[0].content)
    assert card_payload["kind"] == "plan_mutation"
    assert card_payload["actionFamily"] == "add_units"
    assert "至少" in card_payload["content"]
    atomic = captured_plan_payload["atomic_actions"][0]
    assert atomic["action_type"] == "add_units"
    assert atomic["filters"]["major_keyword"] == "临床医学"
    pending_plan_payload = json.loads(pending_state["value"]["executionPayload"]["planPayload"])
    assert pending_plan_payload["atomic_actions"][0]["filters"]["major_keyword"] == "临床医学"
    assert pending_state["value"]["executionPayload"]["intentPayload"]["constraintIntentType"] == "must_have"
    composite = pending_state["value"]["compositeProposal"]
    assert composite["goal"]["goal_type"] == "must_include_scope"
    assert composite["goal"]["target_scopes"] == [
        {"entity_type": "major", "values": ["临床医学"]}
    ]
    assert composite["intent_updates"][0]["constraintIntentType"] == "must_have"
    assert composite["plan_actions"][0]["action_type"] == "add_units"
    assert composite["plan_actions"][0]["filters"]["major_keyword"] == "临床医学"
    assert pending_plan_payload["composite_proposal"]["goal"]["goal_type"] == "must_include_scope"


def test_chat_service_must_have_major_keeps_intent_only_when_plan_already_has_scope(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    preview_payload = {
        "status": "ready",
        "sessionId": "9905014",
        "title": "待采纳报考条件",
        "intentMode": "constraint",
        "constraintIntentType": "must_have",
        "analysisStage": "confirmed",
        "items": [
            {
                "content": "至少保留专业：临床医学",
                "value": {"major_intents": {"level3": ["临床医学"]}},
                "selected": True,
            }
        ],
        "existingItems": [],
        "message": "至少保留专业：临床医学",
    }
    fake_agent = _FakeIntentPreviewAgent(
        preview_payload,
        tool_name="preview_current_major_intent_confirmation",
    )
    workspace_state = {
        "code": 0,
        "data": {
            "orderedPlanState": {
                "items": [
                    {
                        "volunteerId": "clinical-1",
                        "schoolName": "A大学",
                        "majorName": "临床医学",
                    },
                ]
            }
        },
    }
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()
    execute_mock = AsyncMock()

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value=workspace_state)), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.execute_plan_action", execute_mock), \
            patch("app.service.save_intent_change_cache", AsyncMock(return_value={"code": 0})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message("9905014", "user-1", "必须有临床医学")
        )

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert len(reply.followups) == 1
    card_payload = json.loads(reply.followups[0].content)
    assert card_payload["kind"] == "intent_change"
    assert card_payload["actionFamily"] == "apply_selected_intents"
    assert card_payload["constraintIntentType"] == "must_have"
    assert pending_state["value"]["kind"] == "intent_change"
    assert pending_state["value"]["constraintIntentType"] == "must_have"
    execute_mock.assert_not_awaited()


def test_chat_service_only_keep_region_area_preview_keeps_area_scope_metadata(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    preview_payload = {
        "status": "ready",
        "sessionId": "9905015",
        "title": "待采纳报考条件",
        "intentMode": "constraint",
        "constraintIntentType": "only_keep",
        "analysisStage": "confirmed",
        "items": [
            {
                "content": "只保留地域：南方",
                "value": {"city_intents": {"area": ["南方"]}},
                "selected": True,
            }
        ],
        "existingItems": [],
        "message": "准备采纳：只保留地域：南方",
    }
    fake_agent = _FakeIntentPreviewAgent(
        preview_payload,
        tool_name="preview_current_region_intent_confirmation",
    )
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()
    execute_mock = AsyncMock()

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.execute_plan_action", execute_mock), \
            patch("app.service.save_intent_change_cache", AsyncMock(return_value={"code": 0})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message("9905015", "user-1", "只保留南方")
        )

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert len(reply.followups) == 1
    card_payload = json.loads(reply.followups[0].content)
    assert card_payload["kind"] == "intent_change"
    assert card_payload["actionFamily"] == "apply_selected_intents"
    assert "南方" in card_payload["content"]
    composite = pending_state["value"]["compositeProposal"]
    assert composite["goal"]["goal_type"] == "only_keep_scope"
    assert composite["goal"]["target_scopes"] == [
        {"entity_type": "region", "values": ["南方"]}
    ]
    assert composite["intent_updates"][0]["targetScopes"] == [
        {"entity_type": "region", "values": ["南方"]}
    ]
    assert pending_state["value"]["executionPayload"]["selectedData"]["selected"] == [
        {"city_intents": {"area": ["南方"]}}
    ]
    execute_mock.assert_not_awaited()


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
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch("app.service.save_intent_change_cache", AsyncMock(return_value={"code": 0})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("9905011", "user-1", "不太想学秘书"))

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert reply.primary == ""
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
    clear_legacy_cache_mock = AsyncMock(return_value={"code": 0})

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.save_intent_change_cache", clear_legacy_cache_mock), \
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
    clear_legacy_cache_mock.assert_awaited_once_with(990502, {})


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
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})):
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
    ):
        self.calls: list[dict] = []
        self._reply = reply
        self._tool_parts = tool_parts
        self._tool_return_parts = tool_return_parts or []

    async def run_with_message_deltas(self, user_prompt, message_history=None, deps=None, on_progress=None):
        self.calls.append({"user_prompt": user_prompt})
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
        self.calls.append({"user_prompt": user_prompt, "pending_plan_action": deps.pending_plan_action if deps else None})
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


def test_extract_pending_plan_action_from_preview_tool_result():
    preview_payload = {
        "stage": "preview",
        "action_family": "regenerate_order",
        "user_goal": "整体重排当前方案",
        "requires_confirmation": True,
        "should_rerun_review": False,
        "missing_inputs": [],
        "atomic_actions": [],
        "preview_summary": "会整体重排当前方案。",
    }
    messages = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args={"plan_payload": json.dumps(preview_payload, ensure_ascii=False)},
                    tool_call_id="preview-call-1",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": False,
                            "action_family": "regenerate_order",
                            "stage": "preview",
                            "result_kind": "preview_only",
                            "summary": "会整体重排当前方案。",
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="preview-call-1",
                )
            ]
        ),
    ]

    pending = _extract_pending_plan_action(messages)

    assert pending is not None
    assert pending["action_family"] == "regenerate_order"
    assert pending["user_goal"] == "整体重排当前方案"
    apply_payload = json.loads(pending["plan_payload"])
    assert apply_payload["stage"] == "apply"
    assert apply_payload["requires_confirmation"] is False
    assert apply_payload["should_rerun_review"] is True


def test_extract_pending_plan_action_keeps_source_version_and_turn():
    preview_payload = {
        "stage": "preview",
        "action_family": "regenerate_order",
        "user_goal": "整体重排当前方案",
        "requires_confirmation": True,
        "should_rerun_review": False,
        "missing_inputs": [],
        "atomic_actions": [],
        "preview_summary": "会整体重排当前方案。",
    }
    messages = [
        ModelRequest(parts=[UserPromptPart(content="把方案重排一下")]),
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args={"plan_payload": json.dumps(preview_payload, ensure_ascii=False)},
                    tool_call_id="preview-call-version",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": False,
                            "action_family": "regenerate_order",
                            "stage": "preview",
                            "result_kind": "preview_only",
                            "summary": "会整体重排当前方案。",
                            "facts": {
                                "planning_version": 7,
                            },
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="preview-call-version",
                )
            ]
        ),
    ]

    pending = _extract_pending_plan_action(messages)

    assert pending is not None
    assert pending["created_turn"] == 1
    assert pending["source_backend_version"] == 7
    assert pending["planning_version"] == 7
    apply_payload = json.loads(pending["plan_payload"])
    assert apply_payload["planning_version"] == 7


def test_extract_pending_plan_action_normalizes_flat_execute_preview_payload():
    preview_payload = {
        "stage": "preview",
        "action_family": "remove_units",
        "user_goal": "先处理高收费",
        "requires_confirmation": True,
        "should_rerun_review": False,
        "should_refresh_workspace": False,
        "volunteer_ids": ["@14", "@24"],
    }
    messages = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args={"plan_payload": json.dumps(preview_payload, ensure_ascii=False)},
                    tool_call_id="preview-call-flat-remove",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": False,
                            "action_family": "remove_units",
                            "stage": "preview",
                            "result_kind": "preview_only",
                            "summary": "已定位到当前方案里当前审查命中的高收费项：共 13 个专业组，涉及 44 条志愿。",
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="preview-call-flat-remove",
                )
            ]
        ),
    ]

    pending = _extract_pending_plan_action(messages)

    assert pending is not None
    assert pending["action_family"] == "remove_units"
    apply_payload = json.loads(pending["plan_payload"])
    assert apply_payload["stage"] == "apply"
    assert apply_payload["atomic_actions"][0]["action_type"] == "remove_units"
    assert apply_payload["atomic_actions"][0]["volunteer_ids"] == ["@14", "@24"]
    assert apply_payload["requires_confirmation"] is False
    assert pending["summary"].startswith("已定位到当前方案里当前审查命中的高收费项")


def test_extract_pending_plan_action_normalizes_flat_review_issue_preview_payload():
    preview_payload = {
        "stage": "preview",
        "action_family": "remove_units",
        "user_goal": "把太贵的那几个先去掉看看",
        "requires_confirmation": True,
        "should_rerun_review": False,
        "should_refresh_workspace": False,
        "review_issue_code": "high_tuition",
        "review_issue_scope_mode": "full_issue",
    }
    messages = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args={"plan_payload": json.dumps(preview_payload, ensure_ascii=False)},
                    tool_call_id="preview-call-flat-review-issue",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": False,
                            "action_family": "remove_units",
                            "stage": "preview",
                            "result_kind": "preview_only",
                            "summary": "已定位到当前方案里当前审查命中的高收费：共 13 个专业组，涉及 44 条志愿。",
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="preview-call-flat-review-issue",
                )
            ]
        ),
    ]

    pending = _extract_pending_plan_action(messages)

    assert pending is not None
    assert pending["action_family"] == "remove_units"
    apply_payload = json.loads(pending["plan_payload"])
    assert apply_payload["stage"] == "apply"
    atomic = apply_payload["atomic_actions"][0]
    assert atomic["action_type"] == "remove_units"
    assert atomic["review_issue_target"]["code"] == "high_tuition"
    assert atomic["review_issue_target"]["scope_mode"] == "full_issue"


def test_extract_pending_plan_action_preserves_preview_resolved_apply_payload():
    preview_payload = {
        "stage": "preview",
        "action_family": "remove_units",
        "user_goal": "把河南农大建筑去掉",
        "requires_confirmation": True,
        "should_rerun_review": False,
        "should_refresh_workspace": False,
        "missing_inputs": [],
        "atomic_actions": [
            {
                "action_type": "remove_units",
                "volunteer_ids": ["河南农大建筑"],
                "filters": {},
                "reason": "把河南农大建筑去掉",
            }
        ],
        "preview_summary": "确认要从当前方案中删除河南农业大学-建筑学吗？",
    }
    messages = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args={"plan_payload": json.dumps(preview_payload, ensure_ascii=False)},
                    tool_call_id="preview-call-resolved-remove",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": False,
                            "action_family": "remove_units",
                            "stage": "preview",
                            "result_kind": "preview_only",
                            "summary": "确认要从当前方案中删除河南农业大学-建筑学吗？",
                            "facts": {
                                "resolved_apply_payload": {
                                    "atomic_actions": [
                                        {
                                            "action_type": "remove_units",
                                            "volunteer_ids": ["hnny-arch-4"],
                                            "filters": {},
                                            "reason": "把河南农大建筑去掉",
                                        }
                                    ]
                                }
                            },
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="preview-call-resolved-remove",
                )
            ]
        ),
    ]

    pending = _extract_pending_plan_action(messages)

    assert pending is not None
    apply_payload = json.loads(pending["plan_payload"])
    assert apply_payload["stage"] == "apply"
    assert apply_payload["atomic_actions"][0]["volunteer_ids"] == ["hnny-arch-4"]


def test_extract_pending_plan_action_allows_resolved_action_family_for_major_mode_position_remove():
    preview_payload = {
        "stage": "preview",
        "action_family": "remove_ordered_unit",
        "user_goal": "把第一个志愿删掉",
        "requires_confirmation": True,
        "missing_inputs": [],
        "atomic_actions": [
            {
                "action_type": "remove_ordered_unit",
                "unit_ids": [],
                "source_position": 1,
                "filters": {},
                "reason": "把第一个志愿删掉",
            }
        ],
        "preview_summary": "会删除第 1 个志愿：浙江工商大学 · 法学。",
    }
    messages = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args={"plan_payload": json.dumps(preview_payload, ensure_ascii=False)},
                    tool_call_id="preview-call-major-position-remove",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": False,
                            "action_family": "remove_ordered_unit",
                            "stage": "preview",
                            "result_kind": "preview_only",
                            "summary": "会删除第 1 个志愿：浙江工商大学 · 法学。",
                            "facts": {
                                "unit_kind": "志愿",
                                "resolved_apply_payload": {
                                    "action_family": "remove_units",
                                    "atomic_actions": [
                                        {
                                            "action_type": "remove_units",
                                            "volunteer_ids": ["v1"],
                                            "unit_ids": [],
                                            "source_position": 1,
                                            "filters": {},
                                            "reason": "把第一个志愿删掉",
                                        }
                                    ],
                                },
                            },
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="preview-call-major-position-remove",
                )
            ]
        ),
    ]

    pending = _extract_pending_plan_action(messages)

    assert pending is not None
    assert pending["action_family"] == "remove_units"
    apply_payload = json.loads(pending["plan_payload"])
    assert apply_payload["action_family"] == "remove_units"
    assert apply_payload["atomic_actions"][0]["action_type"] == "remove_units"
    assert apply_payload["atomic_actions"][0]["volunteer_ids"] == ["v1"]


def test_extract_pending_plan_action_from_plan_next_action_preview_result():
    preview_plan = {
        "stage": "preview",
        "action_family": "regenerate_order",
        "user_goal": "整体重排当前方案",
        "requires_confirmation": True,
        "should_rerun_review": False,
        "missing_inputs": [],
        "atomic_actions": [],
        "preview_summary": "会整体重排当前方案。",
    }
    messages = [
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="plan_next_action",
                    content=json.dumps(preview_plan, ensure_ascii=False),
                    tool_call_id="plan-next-preview-1",
                )
            ]
        ),
    ]

    pending = _extract_pending_plan_action(messages)

    assert pending is not None
    assert pending["action_family"] == "regenerate_order"
    assert pending["user_goal"] == "整体重排当前方案"
    assert pending["summary"] == "会整体重排当前方案。"
    apply_payload = json.loads(pending["plan_payload"])
    assert apply_payload["stage"] == "apply"
    assert apply_payload["requires_confirmation"] is False
    assert apply_payload["should_rerun_review"] is True
    assert apply_payload["should_refresh_workspace"] is True


def test_extract_pending_plan_action_clears_plan_next_preview_after_execute_error():
    preview_plan = {
        "stage": "preview",
        "action_family": "move_unit",
        "user_goal": "把青岛城市学院新媒体移到第3位",
        "requires_confirmation": True,
        "missing_inputs": [],
        "atomic_actions": [
            {
                "action_type": "move_unit",
                "volunteer_ids": ["青岛城市学院新媒体"],
                "target_position": 3,
                "filters": {},
            }
        ],
        "preview_summary": "会移动这条志愿。",
    }
    messages = [
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="plan_next_action",
                    content=json.dumps(preview_plan, ensure_ascii=False),
                    tool_call_id="plan-next-preview-before-error",
                )
            ]
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": False,
                            "action_family": "move_unit",
                            "stage": "preview",
                            "result_kind": "error",
                            "summary": "我在当前方案里还没有唯一匹配到这条志愿。",
                            "reply_focus": ["missing_inputs", "needs_volunteer_selection"],
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="execute-preview-error-clears-pending",
                )
            ]
        ),
    ]

    assert _extract_pending_plan_action(messages) is None


def test_plan_preview_confirmation_boundary_does_not_append_after_execute_error_clears_pending():
    reply = "我理解你想移动的是：青岛城市学院新媒体。但我在当前方案里还没有唯一匹配到这条志愿。"
    preview_plan = {
        "stage": "preview",
        "action_family": "move_unit",
        "user_goal": "把青岛城市学院新媒体移到第3位",
        "requires_confirmation": True,
        "missing_inputs": [],
        "atomic_actions": [
            {
                "action_type": "move_unit",
                "volunteer_ids": ["青岛城市学院新媒体"],
                "target_position": 3,
                "filters": {},
            }
        ],
        "preview_summary": "会移动这条志愿。",
    }
    messages = [
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="plan_next_action",
                    content=json.dumps(preview_plan, ensure_ascii=False),
                    tool_call_id="plan-next-preview-before-boundary-error",
                )
            ]
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": False,
                            "action_family": "move_unit",
                            "stage": "preview",
                            "result_kind": "error",
                            "summary": reply,
                            "reply_focus": ["missing_inputs", "needs_volunteer_selection"],
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="execute-preview-error-boundary",
                )
            ]
        ),
    ]

    assert _append_plan_preview_confirmation_boundary(reply, messages) == reply


def test_extract_pending_plan_action_reads_execute_tool_call_args_json_string():
    preview_payload = {
        "stage": "preview",
        "action_family": "add_units",
        "user_goal": "补入网络与新媒体",
        "requires_confirmation": True,
        "missing_inputs": [],
        "atomic_actions": [{"action_type": "add_units", "volunteer_ids": ["v1"]}],
        "preview_summary": "会补入网络与新媒体。",
    }
    messages = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args=json.dumps({"plan_payload": json.dumps(preview_payload, ensure_ascii=False)}, ensure_ascii=False),
                    tool_call_id="preview-call-json-args",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": False,
                            "action_family": "add_units",
                            "stage": "preview",
                            "result_kind": "preview_only",
                            "summary": "会补入网络与新媒体。",
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="preview-call-json-args",
                )
            ]
        ),
    ]

    pending = _extract_pending_plan_action(messages)

    assert pending is not None
    assert pending["action_family"] == "add_units"


def test_extract_pending_plan_action_ignores_incomplete_replace_preview_payload():
    preview_payload = {
        "stage": "preview",
        "action_family": "replace_units",
        "user_goal": "替换生物科学",
        "requires_confirmation": True,
        "school_keyword": "广西师范大学",
        "major_keyword": "生物科学",
    }
    messages = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args=json.dumps({"plan_payload": json.dumps(preview_payload, ensure_ascii=False)}, ensure_ascii=False),
                    tool_call_id="incomplete-replace-preview",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": False,
                            "action_family": "replace_units",
                            "stage": "preview",
                            "result_kind": "preview_only",
                            "summary": "当前阶段仅分析或预览，不执行实际改动。",
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="incomplete-replace-preview",
                )
            ]
        ),
    ]

    assert _extract_pending_plan_action(messages) is None


def test_extract_pending_plan_action_ignores_replace_preview_error_result():
    preview_payload = {
        "stage": "preview",
        "action_family": "replace_units",
        "user_goal": "替换生物科学",
        "requires_confirmation": True,
        "missing_inputs": [],
        "atomic_actions": [
            {
                "action_type": "replace_units",
                "volunteer_ids": ["广西师范大学 生物科学"],
                "filters": {
                    "major_tags": json.dumps(["计算机类", "电子信息类"], ensure_ascii=False),
                    "limit": "3",
                },
            }
        ],
        "preview_summary": "会先移出指定志愿，再按新的筛选条件补入候选。",
    }
    messages = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args={"plan_payload": json.dumps(preview_payload, ensure_ascii=False)},
                    tool_call_id="replace-preview-error",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": False,
                            "action_family": "replace_units",
                            "stage": "preview",
                            "result_kind": "error",
                            "summary": "我还没有定位到这些志愿在当前方案里的真实编号：广西师范大学 生物科学。",
                            "reply_focus": ["missing_inputs", "needs_volunteer_selection"],
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="replace-preview-error",
                )
            ]
        ),
    ]

    assert _extract_pending_plan_action(messages) is None


def test_execute_plan_action_error_return_does_not_infer_workspace_refresh():
    messages = [
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": False,
                            "action_family": "remove_units",
                            "stage": "apply",
                            "result_kind": "error",
                            "summary": "我还没有定位到这些志愿在当前方案里的真实编号：河南农大建筑。",
                            "workspace_refresh_targets": ["ordered"],
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="remove-error-refresh",
                )
            ]
        )
    ]

    assert _tool_calls_include_plan_workspace_refresh(messages) == []


def test_extract_pending_plan_action_ignores_legacy_compensation_preview():
    preview_payload = {
        "stage": "apply",
        "action_family": "preview_compensation",
        "user_goal": "补充梯度断层区间的候选",
        "requires_confirmation": False,
        "missing_inputs": [],
        "atomic_actions": [],
        "preview_summary": "",
    }
    messages = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args={"plan_payload": json.dumps(preview_payload, ensure_ascii=False)},
                    tool_call_id="compensation-preview-call",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": False,
                            "action_family": "preview_compensation",
                            "stage": "apply",
                            "result_kind": "compensation_preview",
                            "summary": "当前可先看的补齐建议共有 1 项动作，预计补入 2 个志愿。",
                            "facts": {
                                "action_count": 1,
                                "estimated_fill_count": 2,
                                "legacy_add_action_count": 1,
                                "legacy_add_estimated_fill_count": 2,
                            },
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="compensation-preview-call",
                )
            ]
        ),
    ]

    assert _extract_pending_plan_action(messages) is None


def test_extract_pending_plan_action_ignores_compensation_preview_without_legacy_add_action():
    preview_payload = {
        "stage": "apply",
        "action_family": "preview_compensation",
        "user_goal": "把高收费的换掉",
        "requires_confirmation": False,
        "missing_inputs": [],
        "atomic_actions": [],
    }
    messages = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args={"plan_payload": json.dumps(preview_payload, ensure_ascii=False)},
                    tool_call_id="compensation-preview-replace-only-call",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": False,
                            "action_family": "preview_compensation",
                            "stage": "apply",
                            "result_kind": "compensation_preview",
                            "summary": "当前可先看的补齐建议共有 1 项动作，预计补入 1 个志愿。",
                            "facts": {
                                "action_count": 1,
                                "estimated_fill_count": 1,
                                "legacy_add_action_count": 0,
                                "legacy_add_estimated_fill_count": 0,
                            },
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="compensation-preview-replace-only-call",
                )
            ]
        ),
    ]

    assert _extract_pending_plan_action(messages) is None


def test_extract_pending_plan_action_ignores_compensation_preview_without_actionable_suggestions():
    preview_payload = {
        "stage": "apply",
        "action_family": "preview_compensation",
        "user_goal": "帮我补几个更稳的",
        "requires_confirmation": False,
        "missing_inputs": [],
        "atomic_actions": [],
    }
    messages = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args={"plan_payload": json.dumps(preview_payload, ensure_ascii=False)},
                    tool_call_id="compensation-preview-empty-call",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": False,
                            "action_family": "preview_compensation",
                            "stage": "apply",
                            "result_kind": "compensation_preview",
                            "summary": "当前可先看的补齐建议共有 0 项动作，预计补入 0 个志愿。",
                            "facts": {"action_count": 0, "estimated_fill_count": 0},
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="compensation-preview-empty-call",
                )
            ]
        ),
    ]

    assert _extract_pending_plan_action(messages) is None


def test_extract_pending_plan_action_empty_compensation_clears_earlier_add_preview_in_same_turn():
    add_payload = {
        "stage": "preview",
        "action_family": "add_units",
        "user_goal": "现在还差几个怎么补",
        "requires_confirmation": True,
        "missing_inputs": [],
        "atomic_actions": [
            {
                "action_type": "add_units",
                "volunteer_ids": [],
                "filters": {"tier": "保", "province_keyword": "北京", "limit": "5"},
                "reason": "按保底方向补入",
            }
        ],
        "preview_summary": "会按北京保底方向补入 5 个候选。",
    }
    compensation_payload = {
        "stage": "apply",
        "action_family": "preview_compensation",
        "user_goal": "现在还差几个怎么补",
        "requires_confirmation": False,
        "missing_inputs": [],
        "atomic_actions": [],
    }
    messages = [
        ModelRequest(parts=[UserPromptPart(content="现在还差几个怎么补")]),
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args={"plan_payload": json.dumps(add_payload, ensure_ascii=False)},
                    tool_call_id="add-preview-before-empty-compensation",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": False,
                            "action_family": "add_units",
                            "stage": "preview",
                            "result_kind": "preview_only",
                            "summary": "会按北京保底方向补入 5 个候选。需要你确认后才会执行。",
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="add-preview-before-empty-compensation",
                )
            ]
        ),
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args={"plan_payload": json.dumps(compensation_payload, ensure_ascii=False)},
                    tool_call_id="empty-compensation-after-add-preview",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": False,
                            "action_family": "preview_compensation",
                            "stage": "apply",
                            "result_kind": "compensation_preview",
                            "summary": "当前可先看的补齐建议共有 0 项动作，预计补入 0 个志愿。",
                            "facts": {"action_count": 0, "estimated_fill_count": 0},
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="empty-compensation-after-add-preview",
                )
            ]
        ),
        ModelResponse(parts=[TextPart(content="当前更适合先选 A/B/C 的调整方向。")], model_name="test-model"),
    ]

    assert _extract_pending_plan_action(messages) is None


def test_extract_pending_plan_action_ignores_adjustment_analysis_without_actionable_suggestions():
    payload = {
        "stage": "apply",
        "action_family": "analyze_adjustment",
        "user_goal": "按更稳的思路帮我弄一版",
        "requires_confirmation": False,
        "missing_inputs": [],
        "atomic_actions": [],
    }
    messages = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args={"plan_payload": json.dumps(payload, ensure_ascii=False)},
                    tool_call_id="adjustment-analysis-empty-call",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": True,
                            "action_family": "analyze_adjustment",
                            "stage": "apply",
                            "result_kind": "adjustment_analysis",
                            "summary": "当前先拿到的是分析结论，不是可直接执行的调整清单。",
                            "facts": {
                                "suggestion_counts": {"add": 1, "reorder": 0, "replace": 0, "remove": 0},
                                "actionable_suggestion_counts": {"add": 0, "reorder": 0, "replace": 0, "remove": 0},
                                "has_actionable_suggestions": False,
                            },
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="adjustment-analysis-empty-call",
                )
            ]
        ),
    ]

    assert _extract_pending_plan_action(messages) is None


def test_extract_pending_plan_action_blocks_followup_preview_after_non_actionable_adjustment_analysis():
    adjustment_payload = {
        "stage": "apply",
        "action_family": "analyze_adjustment",
        "user_goal": "按更稳的思路帮我弄一版",
        "requires_confirmation": False,
        "missing_inputs": [],
        "atomic_actions": [],
    }
    generate_preview_payload = {
        "stage": "preview",
        "action_family": "generate_plan",
        "user_goal": "重新生成一版更稳的方案",
        "requires_confirmation": True,
        "missing_inputs": [],
        "atomic_actions": [],
        "preview_summary": "会基于当前报考参考信息、约束和候选范围生成一版方案，并在执行后自动复审。",
    }
    messages = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args={"plan_payload": json.dumps(adjustment_payload, ensure_ascii=False)},
                    tool_call_id="adjustment-analysis-call",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": True,
                            "action_family": "analyze_adjustment",
                            "stage": "apply",
                            "result_kind": "adjustment_analysis",
                            "summary": "当前先拿到的是分析结论，不是可直接执行的调整清单。",
                            "facts": {
                                "suggestion_counts": {"add": 1, "reorder": 0, "replace": 0, "remove": 0},
                                "actionable_suggestion_counts": {"add": 0, "reorder": 0, "replace": 0, "remove": 0},
                                "has_actionable_suggestions": False,
                            },
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="adjustment-analysis-call",
                )
            ]
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="plan_next_action",
                    content=json.dumps(generate_preview_payload, ensure_ascii=False),
                    tool_call_id="generate-preview-after-adjustment",
                )
            ]
        ),
    ]

    assert _extract_pending_plan_action(messages) is None


def test_extract_pending_plan_action_clears_adjustment_block_after_new_user_turn():
    adjustment_payload = {
        "stage": "apply",
        "action_family": "analyze_adjustment",
        "user_goal": "按更稳的思路帮我弄一版",
        "requires_confirmation": False,
        "missing_inputs": [],
        "atomic_actions": [],
    }
    replace_preview_payload = {
        "stage": "preview",
        "action_family": "replace_units",
        "user_goal": "把贵的换成正常收费的，别少名额",
        "requires_confirmation": True,
        "missing_inputs": [],
        "atomic_actions": [
                {
                    "action_type": "replace_units",
                    "volunteer_ids": [],
                    "filters": {"tuition_keyword": "正常收费"},
                    "review_issue_target": {"code": "high_tuition"},
                }
        ],
        "preview_summary": "会按当前审查命中的整批高收费项执行替换，保持30个志愿总数不变，并在执行后重新审查整体结构。",
    }
    messages = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args={"plan_payload": json.dumps(adjustment_payload, ensure_ascii=False)},
                    tool_call_id="adjustment-analysis-call-reset",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": True,
                            "action_family": "analyze_adjustment",
                            "stage": "apply",
                            "result_kind": "adjustment_analysis",
                            "summary": "当前先拿到的是分析结论，不是可直接执行的调整清单。",
                            "facts": {
                                "suggestion_counts": {"add": 1, "reorder": 0, "replace": 0, "remove": 0},
                                "actionable_suggestion_counts": {"add": 0, "reorder": 0, "replace": 0, "remove": 0},
                                "has_actionable_suggestions": False,
                            },
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="adjustment-analysis-call-reset",
                )
            ]
        ),
        ModelRequest(parts=[UserPromptPart(content="把贵的换成正常收费的，别少名额")]),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="plan_next_action",
                    content=json.dumps(replace_preview_payload, ensure_ascii=False),
                    tool_call_id="replace-preview-after-reset",
                )
            ]
        ),
    ]

    pending = _extract_pending_plan_action(messages)

    assert pending is not None
    assert pending["action_family"] == "replace_units"


def test_extract_pending_plan_action_allows_followup_replace_preview_after_non_actionable_adjustment_analysis():
    adjustment_payload = {
        "stage": "apply",
        "action_family": "analyze_adjustment",
        "user_goal": "按更稳的思路帮我弄一版",
        "requires_confirmation": False,
        "missing_inputs": [],
        "atomic_actions": [],
    }
    replace_preview_payload = {
        "stage": "preview",
        "action_family": "replace_units",
        "user_goal": "按更稳的思路，先去掉高收费专业，再补入更稳的保底志愿",
        "requires_confirmation": True,
        "missing_inputs": [],
        "atomic_actions": [
                {
                    "action_type": "replace_units",
                    "volunteer_ids": [],
                    "filters": {"major_keyword": "保底", "tuition_keyword": "正常收费"},
                    "review_issue_target": {"code": "high_tuition"},
                }
        ],
        "preview_summary": "会按当前审查命中的整批高收费项执行替换，保持30个志愿总数不变，并在执行后重新审查整体结构。",
    }
    messages = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args={"plan_payload": json.dumps(adjustment_payload, ensure_ascii=False)},
                    tool_call_id="adjustment-analysis-call-2",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": True,
                            "action_family": "analyze_adjustment",
                            "stage": "apply",
                            "result_kind": "adjustment_analysis",
                            "summary": "当前先拿到的是分析结论，不是可直接执行的调整清单。",
                            "facts": {
                                "suggestion_counts": {"add": 0, "reorder": 0, "replace": 0, "remove": 0},
                                "actionable_suggestion_counts": {"add": 0, "reorder": 0, "replace": 0, "remove": 0},
                                "has_actionable_suggestions": False,
                            },
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="adjustment-analysis-call-2",
                )
            ]
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="plan_next_action",
                    content=json.dumps(replace_preview_payload, ensure_ascii=False),
                    tool_call_id="replace-preview-after-adjustment",
                )
            ]
        ),
    ]

    pending = _extract_pending_plan_action(messages)

    assert pending is not None
    assert pending["action_family"] == "replace_units"


def test_chat_service_requires_card_click_for_pending_compensation_on_text_confirm(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    preview_payload = {
        "stage": "apply",
        "action_family": "preview_compensation",
        "user_goal": "补充梯度断层区间的候选",
        "requires_confirmation": False,
        "missing_inputs": [],
        "atomic_actions": [],
    }
    awaitable_save = store.save(
        "session-compensation-direct-confirm",
        [
            ModelRequest(parts=[UserPromptPart(content="补充梯度断层区间的候选")]),
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="execute_plan_action",
                        args={"plan_payload": json.dumps(preview_payload, ensure_ascii=False)},
                        tool_call_id="compensation-preview-direct",
                    )
                ],
                model_name="test-model",
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="execute_plan_action",
                        content=json.dumps(
                            {
                                "applied": False,
                                "action_family": "preview_compensation",
                                "stage": "apply",
                                "result_kind": "compensation_preview",
                                "summary": "当前可先看的补齐建议共有 1 项动作，预计补入 2 个志愿。",
                            },
                            ensure_ascii=False,
                        ),
                        tool_call_id="compensation-preview-direct",
                    )
                ]
            ),
            ModelResponse(parts=[TextPart(content="补齐建议预览已生成。回复确认即可应用。")], model_name="test-model"),
        ],
    )
    asyncio.run(awaitable_save)
    fake_agent = _FakeAgent(["我会重新确认你想补充哪类志愿，再给你一版可确认的预览。"])
    execution_result = json.dumps(
        {
            "applied": True,
            "action_family": "apply_compensation",
            "stage": "apply",
            "result_kind": "mutation_result",
            "summary": "系统已完成当前可安全补偿的志愿补入。",
            "workspace_refresh_targets": ["ordered"],
        },
        ensure_ascii=False,
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.execute_plan_action", AsyncMock(return_value=execution_result)) as execute_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-compensation-direct-confirm", "user-1", "确认"))

    assert reply == "我会重新确认你想补充哪类志愿，再给你一版可确认的预览。"
    execute_mock.assert_not_awaited()
    assert len(fake_agent.calls) == 1


def test_chat_service_does_not_directly_apply_empty_compensation_preview_on_confirm(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    preview_payload = {
        "stage": "apply",
        "action_family": "preview_compensation",
        "user_goal": "帮我补几个更稳的",
        "requires_confirmation": False,
        "missing_inputs": [],
        "atomic_actions": [],
    }
    asyncio.run(
        store.save(
            "session-compensation-empty-confirm",
            [
                ModelRequest(parts=[UserPromptPart(content="帮我补几个更稳的")]),
                ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="execute_plan_action",
                            args={"plan_payload": json.dumps(preview_payload, ensure_ascii=False)},
                            tool_call_id="compensation-preview-empty-direct",
                        )
                    ],
                    model_name="test-model",
                ),
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name="execute_plan_action",
                            content=json.dumps(
                                {
                                    "applied": False,
                                    "action_family": "preview_compensation",
                                    "stage": "apply",
                                    "result_kind": "compensation_preview",
                                    "summary": "当前可先看的补齐建议共有 0 项动作，预计补入 0 个志愿。",
                                    "facts": {"action_count": 0, "estimated_fill_count": 0},
                                },
                                ensure_ascii=False,
                            ),
                            tool_call_id="compensation-preview-empty-direct",
                        )
                    ]
                ),
                ModelResponse(parts=[TextPart(content="这一步其实需要改成替换，不是直接补。")], model_name="test-model"),
            ],
        )
    )

    fake_agent = _FakeAgent(["这轮不会直接补入志愿，我会先重新判断是否还有可补空间。"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.execute_plan_action", AsyncMock()) as execute_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-compensation-empty-confirm", "user-1", "确认"))

    assert reply == "这轮不会直接补入志愿，我会先重新判断是否还有可补空间。"
    execute_mock.assert_not_awaited()
    assert len(fake_agent.calls) == 1


def test_plan_preview_confirmation_boundary_removes_unbacked_empty_compensation_confirmation_copy():
    preview_payload = {
        "stage": "apply",
        "action_family": "preview_compensation",
        "user_goal": "帮我补几个更稳的",
        "requires_confirmation": False,
        "missing_inputs": [],
        "atomic_actions": [],
    }
    reply = (
        "当前已经是 30/30 满额。\n\n"
        "如果你确认要这样做，我再执行；现在还不会改动方案。"
    )
    messages = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args={"plan_payload": json.dumps(preview_payload, ensure_ascii=False)},
                    tool_call_id="compensation-preview-empty-boundary",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": False,
                            "action_family": "preview_compensation",
                            "stage": "apply",
                            "result_kind": "compensation_preview",
                            "summary": "当前可先看的补齐建议共有 0 项动作，预计补入 0 个志愿。",
                            "facts": {"action_count": 0, "estimated_fill_count": 0},
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="compensation-preview-empty-boundary",
                )
            ]
        ),
    ]

    bounded = _append_plan_preview_confirmation_boundary(reply, messages)

    assert "当前已经是 30/30 满额" in bounded
    assert "这次没有形成可执行的调整预览" in bounded
    assert "方案不会因为这轮回复而改变" in bounded


def test_chat_service_requires_card_click_for_pending_replace_on_text_confirm(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    preview_plan = {
        "stage": "preview",
        "action_family": "replace_units",
        "user_goal": "替换广西师范大学的生物科学",
        "missing_inputs": [],
        "atomic_actions": [
            {
                "action_type": "replace_units",
                "volunteer_ids": ["广西师范大学006专业组-生物科学"],
                "filters": {"major_tags": json.dumps(["电子信息类"], ensure_ascii=False), "limit": "1"},
                "reason": "替换冲突志愿",
            }
        ],
        "preview_summary": "会替换广西师范大学006专业组-生物科学，并补入更合适的保底志愿。",
    }
    asyncio.run(
        store.save(
            "session-replace-direct-confirm",
            [
                ModelRequest(parts=[UserPromptPart(content="把广西师范大学的生物科学换掉")]),
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name="plan_next_action",
                            content=json.dumps(preview_plan, ensure_ascii=False),
                            tool_call_id="replace-preview-direct",
                        )
                    ]
                ),
                ModelResponse(parts=[TextPart(content="替换预览已生成。回复确认即可替换。")], model_name="test-model"),
            ],
        )
    )
    fake_agent = _FakeAgent(["我会重新确认这次替换范围，再给你一版新的调整预览。"])
    execution_result = json.dumps(
        {
            "applied": True,
            "action_family": "replace_units",
            "stage": "apply",
            "result_kind": "mutation_result",
            "summary": "已替换广西师范大学006专业组-生物科学，并补入新的保底志愿。",
            "workspace_refresh_targets": ["ordered"],
        },
        ensure_ascii=False,
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.execute_plan_action", AsyncMock(return_value=execution_result)) as execute_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-replace-direct-confirm", "user-1", "确认"))

    assert reply == fake_agent._replies[0]
    execute_mock.assert_not_awaited()
    assert len(fake_agent.calls) == 1


def test_chat_service_requires_card_click_for_pending_replace_even_with_stale_intent_cache(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    preview_plan = {
        "stage": "preview",
        "action_family": "replace_units",
        "user_goal": "替换广西师范大学的生物科学",
        "missing_inputs": [],
        "atomic_actions": [
            {
                "action_type": "replace_units",
                "volunteer_ids": ["广西师范大学006专业组-生物科学"],
                "filters": {"major_tags": json.dumps(["电子信息类"], ensure_ascii=False), "limit": "1"},
                "reason": "替换冲突志愿",
            }
        ],
        "preview_summary": "会替换广西师范大学006专业组-生物科学，并补入更合适的保底志愿。",
    }
    asyncio.run(
        store.save(
            "session-replace-direct-confirm-stale-intent",
            [
                ModelRequest(parts=[UserPromptPart(content="把广西师范大学的生物科学换掉")]),
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name="plan_next_action",
                            content=json.dumps(preview_plan, ensure_ascii=False),
                            tool_call_id="replace-preview-direct-stale-intent",
                        )
                    ]
                ),
                ModelResponse(parts=[TextPart(content="替换预览已生成。回复确认即可替换。")], model_name="test-model"),
            ],
        )
    )
    fake_agent = _FakeAgent(["我会重新确认这次替换范围，再给你一版新的调整预览。"])
    execution_result = json.dumps(
        {
            "applied": True,
            "action_family": "replace_units",
            "stage": "apply",
            "result_kind": "mutation_result",
            "summary": "已替换广西师范大学006专业组-生物科学，并补入新的保底志愿。",
            "workspace_refresh_targets": ["ordered"],
        },
        ensure_ascii=False,
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch(
                "app.service.get_intent_change_cache",
                AsyncMock(return_value={"data": {"planEditCache": {"major_intents": {"level3": ["网络与新媒体"]}}}}),
            ), \
            patch("app.service.execute_plan_action", AsyncMock(return_value=execution_result)) as execute_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-replace-direct-confirm-stale-intent", "user-1", "确认"))

    assert reply == fake_agent._replies[0]
    execute_mock.assert_not_awaited()
    assert len(fake_agent.calls) == 1


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
            patch(
                "app.service.get_intent_change_cache",
                AsyncMock(return_value={"data": {"planEditCache": {"city_intents": {"province": ["江苏", "浙江"]}}}}),
            ), \
            patch("app.service._apply_selected_intents", AsyncMock(return_value=intent_result)) as update_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-intent-direct-confirm", "user-1", "确认"))

    assert reply == fake_agent._replies[0]
    update_mock.assert_not_awaited()
    assert len(fake_agent.calls) == 1


def test_chat_service_does_not_append_plan_preview_boundary_for_intent_turn_with_stale_plan_history(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    asyncio.run(
        store.save(
            "session-stale-plan-history",
            [
                ModelRequest(parts=[UserPromptPart(content="当前方案怎么调")]),
                ModelResponse(
                    parts=[ToolCallPart(tool_name="collect_plan_context_inputs", args={})],
                    model_name="test-model",
                ),
                ModelResponse(parts=[TextPart(content="这是之前的方案分析。")], model_name="test-model"),
            ],
        )
    )
    fake_agent = _FakeAgentWithToolCalls(
        "我先把这个偏好整理成待确认参考，你确认后我再正式生效。",
        [ToolCallPart(tool_name="preview_current_major_intent_confirmation", args={"intent_mode": "preference"})],
        [
            ToolReturnPart(
                tool_name="preview_current_major_intent_confirmation",
                content="我先把这个偏好整理成待确认参考。",
                tool_call_id=None,
            )
        ],
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-stale-plan-history", "user-1", "想学跨境电商"))

    assert isinstance(reply, str)
    assert "点“采纳”前不会生效" in reply
    assert "点“采纳”前" in reply
    assert "你确认后我再正式生效" not in reply
    assert "还没有拿到可执行的调整预览" not in reply


def test_chat_service_does_not_apply_pending_intent_directly_for_plan_specific_confirm_phrase(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgent(["模型继续处理"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch(
                "app.service.get_intent_change_cache",
                AsyncMock(return_value={"data": {"planEditCache": {"city_intents": {"province": ["江苏", "浙江"]}}}}),
            ), \
            patch("app.service._apply_selected_intents", AsyncMock()) as update_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-intent-direct-confirm-2", "user-1", "确认生成"))

    assert reply == "模型继续处理"
    update_mock.assert_not_awaited()
    assert len(fake_agent.calls) == 1


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
            patch(
                "app.service.get_intent_change_cache",
                AsyncMock(return_value={"data": {"planEditCache": {"major_intents": {"level3": ["法学"]}}}}),
            ), \
            patch("app.service._apply_selected_intents", AsyncMock()) as update_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-intent-stale-after-readonly", "user-1", "确认"))

    assert reply == fake_agent._replies[0]
    update_mock.assert_not_awaited()
    assert len(fake_agent.calls) == 1


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
            patch(
                "app.service.get_intent_change_cache",
                AsyncMock(return_value={"data": {"planEditCache": {"major_intents": {"level3": ["法学"]}}}}),
            ), \
            patch("app.service._apply_selected_intents", AsyncMock(return_value=intent_result)) as update_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-intent-latest-preview", "user-1", "确认"))

    assert reply == fake_agent._replies[0]
    update_mock.assert_not_awaited()
    assert len(fake_agent.calls) == 1


def test_extract_pending_plan_action_ignores_plan_next_action_with_missing_inputs():
    preview_plan = {
        "stage": "preview",
        "action_family": "replace_units",
        "user_goal": "换掉这几个",
        "missing_inputs": ["volunteer_ids"],
        "preview_summary": "缺少要替换的志愿。",
    }
    messages = [
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="plan_next_action",
                    content=json.dumps(preview_plan, ensure_ascii=False),
                    tool_call_id="plan-next-preview-2",
                )
            ]
        ),
    ]

    assert _extract_pending_plan_action(messages) is None


def test_extract_pending_plan_action_expires_after_multiple_intervening_user_turns():
    preview_plan = {
        "stage": "preview",
        "action_family": "generate_plan",
        "user_goal": "生成一版基础方案",
        "missing_inputs": [],
        "preview_summary": "会生成一版基础方案。",
    }
    messages = [
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="plan_next_action",
                    content=json.dumps(preview_plan, ensure_ascii=False),
                    tool_call_id="plan-next-preview-clear-1",
                )
            ]
        ),
        ModelResponse(parts=[TextPart(content="如果确认，我再执行。")], model_name="test-model"),
        ModelRequest(parts=[UserPromptPart(content="帮我看看哪里不合理")]),
        ModelResponse(parts=[TextPart(content="当前还没有正式方案。")], model_name="test-model"),
        ModelRequest(parts=[UserPromptPart(content="再看看候选")]),
        ModelResponse(parts=[TextPart(content="候选里有一些稳妥选择。")], model_name="test-model"),
        ModelRequest(parts=[UserPromptPart(content="还有别的吗")]),
        ModelResponse(parts=[TextPart(content="可以继续补保底。")], model_name="test-model"),
        ModelRequest(parts=[UserPromptPart(content="先说原因")]),
        ModelResponse(parts=[TextPart(content="主要是保底不足。")], model_name="test-model"),
    ]

    assert _extract_pending_plan_action(messages) is None


def test_extract_pending_plan_action_preserves_after_explanatory_user_turn():
    preview_payload = {
        "stage": "preview",
        "action_family": "move_ordered_unit",
        "user_goal": "把第3个专业组移到第5位",
        "missing_inputs": [],
        "atomic_actions": [],
        "preview_summary": "会把第3个专业组整体移到第5位。",
    }
    messages = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args={"plan_payload": json.dumps(preview_payload, ensure_ascii=False)},
                    tool_call_id="move-unit-preview-keep-1",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": False,
                            "action_family": "move_ordered_unit",
                            "result_kind": "preview_only",
                            "summary": "会把第3个专业组整体移到第5位。",
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="move-unit-preview-keep-1",
                )
            ]
        ),
        ModelResponse(parts=[TextPart(content="如果确认，我再执行。")], model_name="test-model"),
        ModelRequest(parts=[UserPromptPart(content="先再解释一下影响")]),
        ModelResponse(parts=[TextPart(content="这只会移动专业组顺序，组内专业不变。")], model_name="test-model"),
    ]

    pending = _extract_pending_plan_action(messages)

    assert pending is not None
    assert pending["action_family"] == "move_ordered_unit"
    assert json.loads(pending["plan_payload"])["stage"] == "apply"


def test_extract_pending_plan_action_clears_after_apply_result():
    preview_payload = {
        "stage": "preview",
        "action_family": "regenerate_order",
        "missing_inputs": [],
        "atomic_actions": [],
    }
    messages = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args={"plan_payload": json.dumps(preview_payload, ensure_ascii=False)},
                    tool_call_id="preview-call-2",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": False,
                            "action_family": "regenerate_order",
                            "result_kind": "preview_only",
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="preview-call-2",
                )
            ]
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": True,
                            "action_family": "regenerate_order",
                            "result_kind": "mutation_result",
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="apply-call-2",
                )
            ]
        ),
    ]

    assert _extract_pending_plan_action(messages) is None


def test_extract_pending_plan_action_keeps_preview_after_readonly_query_result():
    preview_payload = {
        "stage": "preview",
        "action_family": "move_ordered_unit",
        "user_goal": "把第3个专业组移到第5位",
        "missing_inputs": [],
        "atomic_actions": [
            {
                "action_type": "move_ordered_unit",
                "target_position": 5,
                "filters": {},
            }
        ],
        "preview_summary": "会整体移动指定专业组，组内专业顺序保持不变。",
    }
    messages = [
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="plan_next_action",
                    content=json.dumps(preview_payload, ensure_ascii=False),
                    tool_call_id="move-unit-plan-next",
                )
            ]
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": True,
                            "action_family": "query_state",
                            "result_kind": "status_overview",
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="query-state-after-preview",
                )
            ]
        ),
    ]

    pending = _extract_pending_plan_action(messages)

    assert pending is not None
    assert pending["action_family"] == "move_ordered_unit"
    payload = json.loads(pending["plan_payload"])
    assert payload["stage"] == "apply"
    assert payload["atomic_actions"][0]["target_position"] == 5


def test_plan_preview_confirmation_boundary_corrects_confirm_copy_without_pending_payload():
    reply = "我先给你看替换建议。回复“确认”即可执行替换。"
    messages = [
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="plan_next_action",
                    content=json.dumps(
                        {
                            "stage": "analyze",
                            "action_family": "replace_units",
                            "user_goal": "替换生物科学",
                            "missing_inputs": ["volunteer_ids"],
                            "preview_summary": "缺少要替换的志愿。",
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="missing-replace-preview",
                )
            ]
        ),
    ]

    bounded = _append_plan_preview_confirmation_boundary(reply, messages)

    assert "还没有拿到可执行的调整预览" in bounded
    assert "不会因为你回复“确认”就直接改方案" in bounded
    assert "即可执行替换" not in bounded


def test_plan_preview_confirmation_boundary_ignores_intent_confirm_copy_on_query_state():
    reply = (
        "如果你确认把考公作为后续参考，回复“确认”后，我就把这个方向记成偏好。"
    )
    messages = [
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="plan_next_action",
                    content=json.dumps(
                        {
                            "stage": "apply",
                            "action_family": "query_state",
                            "user_goal": "这版支撑考公吗",
                            "summary": "当前只是查询方案状态。",
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="query-state-with-intent-confirm-copy",
                )
            ]
        ),
    ]

    bounded = _append_plan_preview_confirmation_boundary(reply, messages)

    assert bounded == reply
    assert "还没有拿到可执行的调整预览" not in bounded


def test_plan_preview_confirmation_boundary_removes_unbacked_replace_confirm_section():
    reply = (
        "好的，找到了广西师范大学的生物科学志愿。\n\n"
        "**确认替换吗？**\n\n"
        "如果确认，我会把生物科学换成电子信息类专业，保持在保档位置。\n\n"
        "回复\"确认\"即可执行替换。"
    )
    messages = [
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="plan_next_action",
                    content=json.dumps(
                        {
                            "stage": "analyze",
                            "action_family": "replace_units",
                            "user_goal": "替换生物科学",
                            "missing_inputs": ["replacement_scope"],
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="replace-analyze-only",
                )
            ]
        ),
    ]

    bounded = _append_plan_preview_confirmation_boundary(reply, messages)

    assert "找到了广西师范大学的生物科学志愿" in bounded
    assert "确认替换吗" not in bounded
    assert "我会把生物科学换成" not in bounded
    assert "即可执行替换" not in bounded
    assert "还没有拿到可执行的调整预览" in bounded


def test_extract_pending_plan_action_rejects_replace_preview_without_replacement_scope():
    payload = {
        "stage": "preview",
        "action_family": "replace_units",
        "user_goal": "高收费的换掉",
        "missing_inputs": [],
        "review_issue_code": "high_tuition",
        "review_issue_scope_mode": "full_issue",
        "atomic_actions": [
            {
                "action_type": "replace_units",
                "volunteer_ids": [],
                "filters": {},
                "review_issue_target": {
                    "code": "high_tuition",
                    "scope_mode": "full_issue",
                    "scope_kind": "item_replacement",
                },
            }
        ],
        "preview_summary": "当前阶段仅分析或预览，不执行实际改动。",
    }
    messages = [
        ModelRequest(parts=[UserPromptPart(content="高收费的换掉")]),
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args={"plan_payload": json.dumps(payload, ensure_ascii=False)},
                    tool_call_id="empty-replace-preview",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": False,
                            "action_family": "replace_units",
                            "stage": "preview",
                            "result_kind": "preview_only",
                            "summary": "当前阶段仅分析或预览，不执行实际改动。",
                            "facts": {},
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="empty-replace-preview",
                )
            ]
        ),
    ]

    assert _extract_pending_plan_action(messages) is None


def test_extract_pending_plan_action_rejects_replace_preview_with_only_protection_flags():
    payload = {
        "stage": "preview",
        "action_family": "replace_units",
        "user_goal": "高收费的换掉",
        "missing_inputs": [],
        "atomic_actions": [
            {
                "action_type": "replace_units",
                "volunteer_ids": ["u-cost-1"],
                "filters": {
                    "limit": "5",
                    "school_tags": "[]",
                    "major_tags": "[]",
                    "preserve_count": True,
                    "requireCapacityCheck": True,
                },
                "reason": "替换高收费",
            }
        ],
        "preview_summary": "会把高收费志愿替换掉。",
    }
    messages = [
        ModelRequest(parts=[UserPromptPart(content="高收费的换掉")]),
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args={"plan_payload": json.dumps(payload, ensure_ascii=False)},
                    tool_call_id="protected-replace-preview",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": False,
                            "action_family": "replace_units",
                            "stage": "preview",
                            "result_kind": "preview_only",
                            "summary": "会把高收费志愿替换掉。需要你确认后才会执行。",
                            "facts": {},
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="protected-replace-preview",
                )
            ]
        ),
    ]

    assert _extract_pending_plan_action(messages) is None


def test_extract_pending_plan_action_keeps_replace_preview_with_replacement_scope():
    payload = {
        "stage": "preview",
        "action_family": "replace_units",
        "user_goal": "把高收费换成正常收费的计算机",
        "missing_inputs": [],
        "atomic_actions": [
            {
                "action_type": "replace_units",
                "volunteer_ids": ["u-cost-1"],
                "filters": {"major_keyword": "计算机", "limit": "1"},
                "reason": "换成正常收费的计算机",
            }
        ],
        "preview_summary": "会把高收费志愿换成正常收费的计算机方向。",
    }
    messages = [
        ModelRequest(parts=[UserPromptPart(content="把高收费换成正常收费的计算机")]),
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args={"plan_payload": json.dumps(payload, ensure_ascii=False)},
                    tool_call_id="scoped-replace-preview",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": False,
                            "action_family": "replace_units",
                            "stage": "preview",
                            "result_kind": "preview_only",
                            "summary": "会把高收费志愿换成正常收费的计算机方向。需要你确认后才会执行。",
                            "facts": {},
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="scoped-replace-preview",
                )
            ]
        ),
    ]

    pending = _extract_pending_plan_action(messages)
    assert pending is not None
    assert pending["action_family"] == "replace_units"
    saved_payload = json.loads(pending["plan_payload"])
    assert saved_payload["atomic_actions"][0]["filters"]["major_keyword"] == "计算机"


def test_plan_preview_confirmation_boundary_removes_immediate_execute_copy_without_payload():
    reply = (
        "具体替换方案如下：\n\n"
        "**\n\n"
        "请回复\"确认替换为电子信息工程\"或\"确认替换为信息安全\"，我立即执行。"
    )
    messages = [
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": False,
                            "action_family": "replace_units",
                            "stage": "preview",
                            "result_kind": "error",
                            "summary": "缺少必要输入：volunteer_ids",
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="replace-error-no-payload",
                )
            ]
        ),
    ]

    bounded = _append_plan_preview_confirmation_boundary(reply, messages)

    assert "具体替换方案如下" in bounded
    assert "立即执行" not in bounded
    assert "\"确认替换为电子信息工程\"" not in bounded
    assert "\n**\n" not in bounded
    assert "还没有拿到可执行的调整预览" in bounded


def test_plan_preview_confirmation_boundary_keeps_confirm_copy_with_pending_payload():
    preview_plan = {
        "stage": "preview",
        "action_family": "replace_units",
        "user_goal": "替换生物科学",
        "missing_inputs": [],
        "atomic_actions": [
            {
                "action_type": "replace_units",
                "volunteer_ids": ["广西师范大学006专业组-生物科学"],
                "filters": {"major_keyword": "电子信息", "limit": "1"},
            }
        ],
        "preview_summary": "会替换广西师范大学的生物科学。",
    }
    reply = "我先给你看替换预览。回复“确认”即可执行替换。"
    messages = [
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="plan_next_action",
                    content=json.dumps(preview_plan, ensure_ascii=False),
                    tool_call_id="replace-preview-ready",
                )
            ]
        ),
    ]

    assert _append_plan_preview_confirmation_boundary(reply, messages) == reply


def test_plan_preview_confirmation_boundary_replaces_false_compensation_failure_with_no_preview_boundary():
    preview_payload = {
        "stage": "apply",
        "action_family": "preview_compensation",
        "user_goal": "补充梯度断层区间的候选",
        "requires_confirmation": False,
        "missing_inputs": [],
        "atomic_actions": [],
    }
    messages = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args={"plan_payload": json.dumps(preview_payload, ensure_ascii=False)},
                    tool_call_id="compensation-preview-false-failure",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": False,
                            "action_family": "preview_compensation",
                            "stage": "apply",
                            "result_kind": "compensation_preview",
                            "summary": "当前可先看的补偿建议共有 1 项动作，预计补入 2 个志愿。",
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="compensation-preview-false-failure",
                )
            ]
        ),
    ]
    reply = "系统在补偿环节遇到了一些技术问题，一直无法进入可执行的确认状态。"

    bounded = _append_plan_preview_confirmation_boundary(reply, messages)

    assert bounded == (
        "这次没有形成可执行的调整预览，方案不会因为这轮回复而改变。"
        "如果还需要处理这类问题，可以重新说明要调整的目标，我会按最新方案重新给出预览。"
    )
    assert "预计补入 2 个志愿" not in bounded
    assert "如果你确认要应用" not in bounded
    assert "技术问题" not in bounded


def test_plan_preview_confirmation_boundary_corrects_confirm_copy_after_adjustment_analysis_only():
    reply = "当前方案已分析完毕。确认要我直接执行这版调整吗？"
    messages = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args={
                        "plan_payload": json.dumps(
                            {
                                "stage": "apply",
                                "action_family": "analyze_adjustment",
                                "user_goal": "按更稳的思路帮我弄一版",
                            },
                            ensure_ascii=False,
                        )
                    },
                    tool_call_id="adjustment-analysis-only",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": True,
                            "action_family": "analyze_adjustment",
                            "stage": "apply",
                            "result_kind": "adjustment_analysis",
                            "summary": "当前先拿到的是分析结论，不是可直接执行的调整清单。",
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="adjustment-analysis-only",
                )
            ]
        ),
    ]

    bounded = _append_plan_preview_confirmation_boundary(reply, messages)

    assert "还没有拿到可执行的调整预览" in bounded
    assert "不会因为你回复“确认”就直接改方案" in bounded


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


def test_chat_service_does_not_inject_pending_plan_action_from_history(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    preview_payload = {
        "stage": "preview",
        "action_family": "regenerate_order",
        "user_goal": "整体重排当前方案",
        "missing_inputs": [],
        "atomic_actions": [],
        "preview_summary": "会整体重排当前方案。",
    }
    history = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args={"plan_payload": json.dumps(preview_payload, ensure_ascii=False)},
                    tool_call_id="preview-call-3",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": False,
                            "action_family": "regenerate_order",
                            "result_kind": "preview_only",
                            "summary": "会整体重排当前方案。",
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="preview-call-3",
                )
            ]
        ),
    ]
    asyncio.run(store.save("session-pending-plan", history))
    fake_agent = _FakeAgent(["开始执行重排。"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-pending-plan", "user-1", "先再解释一下"))

    assert reply == "开始执行重排。"
    assert fake_agent.calls[0]["pending_plan_action"] is None


def test_chat_service_uses_backend_pending_plan_before_history_preview(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    history_payload = {
        "stage": "preview",
        "action_family": "regenerate_order",
        "preview_summary": "旧历史里的整体重排。",
    }
    history = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args={"plan_payload": json.dumps(history_payload, ensure_ascii=False)},
                    tool_call_id="history-preview",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": False,
                            "action_family": "regenerate_order",
                            "result_kind": "preview_only",
                            "summary": "旧历史里的整体重排。",
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="history-preview",
                )
            ]
        ),
    ]
    asyncio.run(store.save("session-backend-pending-plan-priority", history))
    backend_plan_payload = {
        "stage": "apply",
        "action_family": "remove_units",
        "atomic_actions": [{"action_type": "remove_units", "volunteer_ids": ["v-law"]}],
        "composite_proposal": {"goal": {"goal_type": "exclude_scope"}},
    }
    pending_state = {
        "type": "pendingConfirmation",
        "pendingId": "backend-plan-pending-1",
        "kind": "plan_mutation",
        "status": "active",
        "actionFamily": "remove_units",
        "summary": "移出法学",
        "executionPayload": {
            "toolName": "execute_plan_action",
            "planPayload": json.dumps(backend_plan_payload, ensure_ascii=False),
        },
        "compositeProposal": {"goal": {"goal_type": "exclude_scope"}},
    }
    fake_agent = _FakeAgent(["先解释这个调整。"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_pending_confirmation", AsyncMock(return_value={"code": 0, "data": {"pendingConfirmation": pending_state}})), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "session-backend-pending-plan-priority",
                "user-1",
                "先解释一下",
            )
        )

    assert reply == "先解释这个调整。"
    pending = fake_agent.calls[0]["pending_plan_action"]
    assert pending["action_family"] == "remove_units"
    assert pending["summary"] == "移出法学"
    injected_payload = json.loads(pending["plan_payload"])
    assert injected_payload["action_family"] == "remove_units"
    assert injected_payload["atomic_actions"][0]["volunteer_ids"] == ["v-law"]
    assert pending["composite_proposal"] == {"goal": {"goal_type": "exclude_scope"}}


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
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"code": 1})), \
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
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"code": 1})), \
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
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"code": 1})), \
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
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-readonly-explore-tool-fallback", "user-1", "先看怎么更偏体制内，不要直接改"))

    assert "当前方案对体制内方向有一定承接" in reply
    assert "执行调整" not in reply
    assert "不会改动当前方案" in reply


def test_chat_service_expires_backend_pending_when_plan_preview_version_is_stale(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    preview_payload = {
        "stage": "preview",
        "action_family": "remove_units",
        "user_goal": "删掉方案里的汉语言文学",
        "missing_inputs": [],
        "planning_version": 7,
        "atomic_actions": [
            {
                "action_type": "remove_units",
                "source_major_names": ["汉语言文学"],
            }
        ],
        "preview_summary": "会移出当前方案里的汉语言文学志愿。",
    }
    history = [
        ModelRequest(parts=[UserPromptPart(content="删掉方案里面的汉语言文学")]),
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args={"plan_payload": json.dumps(preview_payload, ensure_ascii=False)},
                    tool_call_id="remove-preview-stale",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": False,
                            "action_family": "remove_units",
                            "stage": "preview",
                            "result_kind": "preview_only",
                            "summary": "会移出当前方案里的汉语言文学志愿。",
                            "facts": {"planning_version": 7},
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="remove-preview-stale",
                )
            ]
        ),
    ]
    asyncio.run(store.save("session-stale-plan-pending", history))
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store(
        {
            "type": "pendingConfirmation",
            "pendingId": "stale-plan-pending-1",
            "sessionId": "session-stale-plan-pending",
            "kind": "plan_mutation",
            "status": "active",
            "actionFamily": "remove_units",
            "sourceBackendVersion": 7,
            "executionPayload": {"toolName": "execute_plan_action", "planPayload": "{}"},
        }
    )
    fake_agent = _FakeAgent(["我会重新列出待采纳内容。"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch(
                "app.service.get_planning_workspace_state",
                AsyncMock(
                    return_value={
                        "code": 0,
                        "data": {
                            "phase": "ordered",
                            "version": 8,
                            "orderedPlanState": {
                                "summary": {"total": 96, "targetCount": 96},
                                "items": [],
                            },
                            "reviewState": {"summary": {"riskCount": 0, "warnCount": 0}},
                        },
                    }
                ),
            ):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "session-stale-plan-pending",
                "user-1",
                "删掉方案里面的汉语言文学",
            )
        )

    assert reply == "我会重新列出待采纳内容。"
    assert pending_state["value"]["status"] == "expired"
    assert pending_state["value"]["expiredReason"] == "version_mismatch"
    assert fake_agent.calls[0]["pending_plan_action"] is None
    assert "上一轮" in fake_agent.calls[0]["stale_pending_notice"]
    assert "失效" in fake_agent.calls[0]["stale_pending_notice"]
    saved = asyncio.run(store.load("session-stale-plan-pending"))
    assert saved is not None


def test_chat_service_requires_card_click_for_pending_regenerate_order_on_text_confirm(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    preview_payload = {
        "stage": "preview",
        "action_family": "regenerate_order",
        "user_goal": "整体重排当前方案",
        "missing_inputs": [],
        "atomic_actions": [],
        "preview_summary": "会整体重排当前方案。",
    }
    history = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args={"plan_payload": json.dumps(preview_payload, ensure_ascii=False)},
                    tool_call_id="preview-call-direct-1",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": False,
                            "action_family": "regenerate_order",
                            "result_kind": "preview_only",
                            "summary": "会整体重排当前方案。",
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="preview-call-direct-1",
                )
            ]
        ),
    ]
    asyncio.run(store.save("session-pending-plan-direct", history))
    fake_agent = _FakeAgent(["不应该调用模型"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.execute_plan_action", AsyncMock()) as execute_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-pending-plan-direct", "user-1", "确认"))

    assert reply == fake_agent._replies[0]
    execute_mock.assert_not_awaited()
    assert len(fake_agent.calls) == 1
    saved_history = asyncio.run(store.load("session-pending-plan-direct"))
    assert saved_history is not None
    assert any(
        isinstance(part, TextPart) and part.content == reply
        for message in saved_history
        for part in getattr(message, "parts", [])
    )


def test_chat_service_requires_card_click_for_pending_after_explanatory_turn(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    preview_payload = {
        "stage": "preview",
        "action_family": "move_ordered_unit",
        "user_goal": "把第3个专业组移到第5位",
        "missing_inputs": [],
        "atomic_actions": [],
        "preview_summary": "会把第3个专业组整体移到第5位。",
    }
    history = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args={"plan_payload": json.dumps(preview_payload, ensure_ascii=False)},
                    tool_call_id="preview-call-direct-keep-1",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": False,
                            "action_family": "move_ordered_unit",
                            "result_kind": "preview_only",
                            "summary": "会把第3个专业组整体移到第5位。",
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="preview-call-direct-keep-1",
                )
            ]
        ),
        ModelResponse(parts=[TextPart(content="如果确认，我再执行。")], model_name="test-model"),
        ModelRequest(parts=[UserPromptPart(content="先再解释一下影响")]),
        ModelResponse(parts=[TextPart(content="这只会移动专业组顺序，组内专业不变。")], model_name="test-model"),
    ]
    asyncio.run(store.save("session-pending-plan-direct-keep", history))
    fake_agent = _FakeAgent(["不应该调用模型"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.execute_plan_action", AsyncMock()) as execute_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-pending-plan-direct-keep", "user-1", "确认"))

    assert reply == fake_agent._replies[0]
    execute_mock.assert_not_awaited()
    assert len(fake_agent.calls) == 1


def test_chat_service_requires_card_click_for_plan_pending_after_readonly_turn(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    preview_payload = {
        "stage": "preview",
        "action_family": "sort_ordered_plan",
        "user_goal": "按院校层次排序",
        "missing_inputs": [],
        "atomic_actions": [],
        "sort_field": "school_rank",
        "preview_summary": "会按院校层次重新排序当前方案。",
    }
    history = [
        ModelRequest(parts=[UserPromptPart(content="按院校层次排序")]),
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="plan_next_action",
                    args={"action_family": "sort_ordered_plan"},
                    tool_call_id="sort-preview-call",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="plan_next_action",
                    content=json.dumps(preview_payload, ensure_ascii=False),
                    tool_call_id="sort-preview-call",
                )
            ]
        ),
        ModelResponse(parts=[TextPart(content="排序预览已生成，确认后执行。")], model_name="test-model"),
        ModelRequest(parts=[UserPromptPart(content="当前方案对体制内稳定就业方向承接得怎么样，先不要改方案")]),
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="analyze_current_career_direction",
                    args={"career_directions": ["system_public_service", "stable_employment"]},
                    tool_call_id="career-readonly-call",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="analyze_current_career_direction",
                    content=json.dumps({"summary": "只读分析，不改方案。"}, ensure_ascii=False),
                    tool_call_id="career-readonly-call",
                )
            ]
        ),
        ModelResponse(parts=[TextPart(content="这轮只做分析，不会改动你的方案。")], model_name="test-model"),
    ]
    asyncio.run(store.save("session-stale-plan-pending-after-readonly", history))
    fake_agent = _FakeAgent(["不应该调用模型"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.execute_plan_action", AsyncMock()) as execute_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-stale-plan-pending-after-readonly", "user-1", "确认"))

    assert reply == fake_agent._replies[0]
    execute_mock.assert_not_awaited()
    assert len(fake_agent.calls) == 1


def test_chat_service_no_pending_confirmation_flows_to_agent(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgent(["我会重新确认你想处理哪部分内容。"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_pending_confirmation", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})) as score_mock, \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})) as profile_mock, \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"code": 1})) as intent_cache_mock, \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})) as workspace_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-no-pending-confirm", "user-1", "确认"))

    assert reply == "我会重新确认你想处理哪部分内容。"
    assert len(fake_agent.calls) == 1
    score_mock.assert_awaited_once()
    profile_mock.assert_awaited_once()
    intent_cache_mock.assert_not_awaited()
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
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"code": 1})) as intent_cache_mock, \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})) as workspace_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-no-pending-colloquial-confirm", "user-1", "嗯可以"))

    assert reply == "继续生成补充预览。"
    assert fake_agent.calls[0]["user_prompt"] == "嗯可以"
    score_mock.assert_awaited_once()
    profile_mock.assert_awaited_once()
    intent_cache_mock.assert_not_awaited()
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
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"code": 1})) as intent_cache_mock, \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})) as workspace_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-review-followup-no-pending", "user-1", "可以"))

    assert reply == "我先继续定位本省保底可补入的志愿，并给你一版调整预览。"
    assert fake_agent.calls[0]["user_prompt"] == "可以"
    score_mock.assert_awaited_once()
    profile_mock.assert_awaited_once()
    intent_cache_mock.assert_not_awaited()
    workspace_mock.assert_awaited_once()


def test_chat_service_routes_review_preview_confirmation_to_agent_without_pending_action(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    asyncio.run(
        store.save(
            "session-review-preview-confirm-no-pending",
            [
                ModelRequest(parts=[UserPromptPart(content="方案怎么处理")]),
                ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="execute_plan_action",
                            args={
                                "plan_payload": json.dumps(
                                    {"stage": "review", "action_family": "review_plan"},
                                    ensure_ascii=False,
                                )
                            },
                            tool_call_id="review-followup-1",
                        )
                    ],
                    model_name="test-model",
                ),
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name="execute_plan_action",
                            content=json.dumps(
                                {
                                    "applied": True,
                                    "action_family": "review_plan",
                                    "stage": "review",
                                    "result_kind": "review_result",
                                    "summary": "已完成当前方案审查。",
                                    "facts": {
                                        "fix_proposals": {
                                            "source_version_guard": 18,
                                            "proposals": [
                                                {
                                                    "proposal_id": "fp-home-protect-1",
                                                    "status": "ready",
                                                    "title": "补充本省保底志愿",
                                                }
                                            ],
                                        }
                                    },
                                },
                                ensure_ascii=False,
                            ),
                            tool_call_id="review-followup-1",
                        )
                    ]
                ),
                ModelResponse(
                    parts=[
                        TextPart(
                            content=(
                                "如果你希望先处理本省保底不足的问题，我可以生成补充预览，确认后再加入方案。\n\n"
                                "先说明一下：我还没有拿到可执行的调整预览，所以这一步不会因为你回复“确认”就直接改方案。"
                            )
                        )
                    ],
                    model_name="test-model",
                ),
            ],
        )
    )
    fake_agent = _FakeAgent(["我先继续生成本省保底的调整预览。"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_pending_confirmation", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})) as score_mock, \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})) as profile_mock, \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"code": 1})) as intent_cache_mock, \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})) as workspace_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-review-preview-confirm-no-pending", "user-1", "确认"))

    assert reply == "我先继续生成本省保底的调整预览。"
    assert fake_agent.calls[0]["user_prompt"] == "确认"
    score_mock.assert_awaited_once()
    profile_mock.assert_awaited_once()
    intent_cache_mock.assert_not_awaited()
    workspace_mock.assert_awaited_once()


def test_chat_service_routes_no_pending_intent_confirmation_to_intent_guard(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgent(["不应该调用模型"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_pending_confirmation", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})) as score_mock, \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})) as profile_mock, \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"code": 1})) as intent_cache_mock, \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})) as workspace_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-no-pending-intent-confirm", "user-1", "确认这个偏好"))

    assert reply == "不应该调用模型"
    assert len(fake_agent.calls) == 1
    score_mock.assert_awaited_once()
    profile_mock.assert_awaited_once()
    intent_cache_mock.assert_not_awaited()
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
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"code": 1})), \
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
            patch(
                "app.service.get_intent_change_cache",
                AsyncMock(return_value={"code": 0, "data": {"planEditCache": {"career_intents": {"positive": ["stable_employment"]}}}}),
            ) as intent_cache_mock, \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service._apply_selected_intents", AsyncMock()) as update_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-intent-pending-confirm", "user-1", "确认"))

    assert reply == fake_agent._replies[0]
    update_mock.assert_not_awaited()
    assert len(fake_agent.calls) == 1
    intent_cache_mock.assert_not_awaited()


def test_chat_service_applies_active_pending_confirmation_intent_on_short_text(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgent(["不应该调用模型"])
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store(
        {
            "type": "pendingConfirmation",
            "pendingId": "pending-intent-main",
            "sessionId": "990502",
            "kind": "intent_change",
            "status": "active",
            "actionFamily": "apply_selected_intents",
            "summary": "偏好地域：北京",
            "executionPayload": {
                "toolName": "apply_selected_intents",
                "merged": {"city_intents": {"province": ["北京"]}},
                "selectedData": {
                    "selected": [{"city_intents": {"province": ["北京"]}}],
                    "intentMode": "preference",
                    "batch": "01",
                },
                "intentMode": "preference",
                "batch": "01",
            },
        }
    )
    intent_result = json.dumps(
        {
            "action": "apply_selected",
            "sessionId": "990502",
            "intentMode": "preference",
            "applied": True,
            "messageCode": "preference_applied",
            "message": "",
        },
        ensure_ascii=False,
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": {}}})) as cache_mock, \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.classify_pending_confirmation_action", AsyncMock(return_value=_semantic_pending("confirm_pending"))), \
            patch("app.service._apply_selected_intents", AsyncMock(return_value=intent_result)) as update_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("990502", "user-1", "确认"))

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert "已采纳" in reply.primary
    assert "后续推荐和专家优选会更贴近这个方向" in reply.primary
    assert len(reply.followups) == 1
    workspace_payload = json.loads(reply.followups[0].content)
    assert workspace_payload["targetView"] == "candidate"
    assert workspace_payload["preserveView"] is True
    assert workspace_payload["silent"] is True
    assert pending_state["value"]["pendingId"] == "pending-intent-main"
    assert pending_state["value"]["status"] == "applied"
    cache_mock.assert_not_awaited()
    update_mock.assert_awaited_once()
    assert update_mock.await_args.kwargs["selected_data"]["selected"] == [
        {"city_intents": {"province": ["北京"]}}
    ]
    assert fake_agent.calls == []


def test_chat_service_requires_card_click_for_plan_next_action_pending_text_confirmation(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    preview_plan = {
        "stage": "preview",
        "action_family": "regenerate_order",
        "user_goal": "整体重排当前方案",
        "requires_confirmation": True,
        "missing_inputs": [],
        "atomic_actions": [],
        "preview_summary": "会整体重排当前方案。",
    }
    history = [
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="plan_next_action",
                    content=json.dumps(preview_plan, ensure_ascii=False),
                    tool_call_id="plan-next-preview-direct-1",
                )
            ]
        ),
        ModelResponse(parts=[TextPart(content="确认重新排序吗？")], model_name="test-model"),
    ]
    asyncio.run(store.save("session-pending-plan-next-direct", history))
    fake_agent = _FakeAgent(["不应该调用模型"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.execute_plan_action", AsyncMock()) as execute_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-pending-plan-next-direct", "user-1", "确认"))

    assert reply == fake_agent._replies[0]
    execute_mock.assert_not_awaited()
    assert len(fake_agent.calls) == 1


def test_chat_service_appends_workspace_refresh_after_execute_plan_action_review(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgentWithToolCalls(
        "已完成当前方案审查。",
        [
            ToolCallPart(
                tool_name="execute_plan_action",
                args={"plan_payload": json.dumps({"stage": "review", "action_family": "review_plan"}, ensure_ascii=False)},
                tool_call_id="review-refresh-call",
            )
        ],
        [
            ToolReturnPart(
                tool_name="execute_plan_action",
                content=json.dumps(
                    {
                        "applied": True,
                        "action_family": "review_plan",
                        "stage": "review",
                        "result_kind": "review_result",
                        "workspace_refresh_targets": ["review"],
                    },
                    ensure_ascii=False,
                ),
                tool_call_id="review-refresh-call",
            )
        ],
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-plan-review-new", "user-1", "帮我审查一下"))

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert reply.primary == "已完成当前方案审查。"
    payload = json.loads(reply.followups[0].content)
    assert payload["targetView"] == "review"
    assert payload["refresh"] is True
    assert payload["silent"] is True


def test_chat_service_appends_workspace_refresh_after_execute_plan_action_mutation(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgentWithToolCalls(
        "已加入2个志愿。",
        [
            ToolCallPart(
                tool_name="execute_plan_action",
                args={"plan_payload": json.dumps({"stage": "apply", "action_family": "add_units"}, ensure_ascii=False)},
            )
        ],
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-plan-add-new", "user-1", "把这两个加进去"))

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert reply.primary == "已加入2个志愿。"
    payload = json.loads(reply.followups[0].content)
    assert payload["targetView"] == "ordered"
    assert payload["preserveView"] is True
    assert payload["silent"] is True


def test_chat_service_appends_workspace_refresh_after_execute_plan_action_generate_plan(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgentWithToolCalls(
        "已生成一版方案。",
        [
            ToolCallPart(
                tool_name="execute_plan_action",
                args={"plan_payload": json.dumps({"stage": "apply", "action_family": "generate_plan"}, ensure_ascii=False)},
            )
        ],
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-plan-generate-new", "user-1", "直接生成一版方案"))

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert reply.primary == "已生成一版方案。"
    payload = json.loads(reply.followups[0].content)
    assert payload["targetView"] == "ordered"
    assert payload["preserveView"] is True
    assert payload["silent"] is True


def test_chat_service_uses_execute_plan_result_workspace_refresh_targets(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgentWithToolCalls(
        "已完成重排并复审。",
        [
            ToolCallPart(
                tool_name="execute_plan_action",
                args={"plan_payload": json.dumps({"stage": "apply", "action_family": "regenerate_order"}, ensure_ascii=False)},
                tool_call_id="plan-call-1",
            )
        ],
        [
            ToolReturnPart(
                tool_name="execute_plan_action",
                content=json.dumps(
                    {
                        "applied": True,
                        "action_family": "regenerate_order",
                        "workspace_refresh_targets": ["ordered"],
                    },
                    ensure_ascii=False,
                ),
                tool_call_id="plan-call-1",
            )
        ],
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-plan-regenerate-refresh", "user-1", "帮我重排一下"))

    assert isinstance(reply, ChatServiceResponseEnvelope)
    payloads = [json.loads(item.content) for item in reply.followups]
    assert [payload["targetView"] for payload in payloads] == ["ordered"]
    assert payloads[0]["preserveView"] is True
    assert payloads[0]["silent"] is True


def test_chat_service_ignores_read_only_execute_plan_result_workspace_targets(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgentWithToolCalls(
        "这是当前方案状态。",
        [
            ToolCallPart(
                tool_name="execute_plan_action",
                args={"plan_payload": json.dumps({"stage": "apply", "action_family": "query_state"}, ensure_ascii=False)},
                tool_call_id="plan-call-2",
            )
        ],
        [
            ToolReturnPart(
                tool_name="execute_plan_action",
                content=json.dumps(
                    {
                        "applied": True,
                        "action_family": "query_state",
                        "workspace_refresh_targets": ["ordered"],
                    },
                    ensure_ascii=False,
                ),
                tool_call_id="plan-call-2",
            )
        ],
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-plan-query-refresh", "user-1", "方案有了么"))

    assert reply == "这是当前方案状态。"


def test_chat_service_does_not_append_workspace_refresh_after_execute_plan_action_analysis(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgentWithToolCalls(
        "当前方案可以先补强保区。",
        [
            ToolCallPart(
                tool_name="execute_plan_action",
                args={"plan_payload": json.dumps({"stage": "apply", "action_family": "analyze_adjustment"}, ensure_ascii=False)},
            )
        ],
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-plan-analysis-new", "user-1", "看看现在方案怎么优化"))

    assert reply == "当前方案可以先补强保区。"


def test_chat_service_does_not_append_workspace_refresh_after_execute_plan_action_query_state(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgentWithToolCalls(
        "这是当前方案状态。",
        [
            ToolCallPart(
                tool_name="execute_plan_action",
                args={"plan_payload": json.dumps({"stage": "apply", "action_family": "query_state"}, ensure_ascii=False)},
            )
        ],
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-plan-state-new", "user-1", "方案有了么"))

    assert reply == "这是当前方案状态。"


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


def test_timeout_fallback_uses_query_state_status_overview():
    with patch(
        "app.service.consume_recent_plan_execution_result",
        return_value={
            "result_kind": "status_overview",
            "action_family": "query_state",
            "summary": "方案已经有了，目前有 45/45 个志愿。",
            "facts": {
                "current_total": 45,
                "target_total": 45,
                "tier_counts": {"冲": 18, "稳": 13, "保": 14},
                "risk_count": 0,
                "warn_count": 0,
            },
        },
    ):
        fallback = build_timeout_fallback_from_recent_plan_execution("s1", "看看方案")

    assert fallback is not None
    assert fallback.primary
    assert "45/45" in fallback.primary
    assert "冲18 / 稳13 / 保14" in fallback.primary


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
                tool_name="execute_plan_action",
                args={"plan_payload": json.dumps({"stage": "apply", "action_family": "query_state"}, ensure_ascii=False)},
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
                tool_name="execute_plan_action",
                args={"plan_payload": json.dumps({"stage": "apply", "action_family": "query_state"}, ensure_ascii=False)},
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


def test_chat_service_allows_plan_next_action_markdown_sections(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgentWithToolCalls(
        "目前还不能补，因为 **当前还没有生成正式方案**。\n\n- **草稿志愿**：0个\n\n## 建议\n\n1. **直接生成一版完整方案**",
        [
            ToolCallPart(
                tool_name="plan_next_action",
                args={
                    "user_goal": "帮我补几个更稳的",
                    "action_family": "add_units",
                },
            )
        ],
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-plan-style-next-action", "user-1", "帮我补几个更稳的"))

    assert "**当前还没有生成正式方案**" in reply
    assert "## 建议" in reply
    assert "你想走哪条路" not in reply
    saved_history = asyncio.run(store.load("session-plan-style-next-action"))
    assert saved_history is not None
    saved_text = next(part.content for part in saved_history[-1].parts if isinstance(part, TextPart))
    assert saved_text == reply


def test_chat_service_appends_confirmation_boundary_for_plan_next_action_preview_without_execute(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    preview_plan = {
        "stage": "preview",
        "action_family": "generate_plan",
        "user_goal": "生成一版基础方案",
        "missing_inputs": [],
        "preview_summary": "会基于当前报考参考信息生成一版方案。",
    }
    fake_agent = _FakeAgentWithToolCalls(
        "我先帮你规划一版基础方案。",
        [
            ToolCallPart(
                tool_name="plan_next_action",
                args={
                    "user_goal": "生成一版基础方案",
                    "action_family": "generate_plan",
                },
                tool_call_id="plan-preview-call-1",
            )
        ],
        [
            ToolReturnPart(
                tool_name="plan_next_action",
                content=json.dumps(preview_plan, ensure_ascii=False),
                tool_call_id="plan-preview-call-1",
            )
        ],
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-plan-next-preview-boundary", "user-1", "帮我补几个更稳的"))

    _assert_pending_card_envelope(reply, "", "generate_plan")
    saved_history = asyncio.run(store.load("session-plan-next-preview-boundary"))
    assert saved_history is not None
    saved_text = next(part.content for part in saved_history[-1].parts if isinstance(part, TextPart))
    assert saved_text == ""


def test_chat_service_appends_unit_position_note_for_ordered_unit_preview(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    preview_plan = {
        "stage": "preview",
        "action_family": "move_ordered_unit",
        "user_goal": "把第4个专业组移到第2位",
        "requires_confirmation": True,
        "missing_inputs": [],
        "atomic_actions": [
            {
                "action_type": "move_ordered_unit",
                "unit_ids": ["第4个专业组"],
                "target_position": 2,
            }
        ],
        "preview_summary": "会整体移动指定专业组。",
    }
    fake_agent = _FakeAgentWithToolCalls(
        "预览如下：第4个志愿组会移动到第2位，组内专业顺序保持不变。确认后执行。",
        [
            ToolCallPart(
                tool_name="execute_plan_action",
                args={"plan_payload": json.dumps(preview_plan, ensure_ascii=False)},
                tool_call_id="ordered-unit-preview-note",
            )
        ],
        [
            ToolReturnPart(
                tool_name="execute_plan_action",
                content=json.dumps(
                    {
                        "applied": False,
                        "action_family": "move_ordered_unit",
                        "stage": "preview",
                        "result_kind": "preview_only",
                        "summary": "会整体移动指定专业组。",
                    },
                    ensure_ascii=False,
                ),
                tool_call_id="ordered-unit-preview-note",
            )
        ],
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-ordered-unit-preview-note", "user-1", "把第4个专业组移到第2位"))

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert reply.primary == ""
    card_payload = _assert_pending_card_envelope(reply, "", "move_ordered_unit")
    assert "不是按单条志愿位置计算" in card_payload["content"]
    assert "组内专业会保持连续" in card_payload["content"]
    assert "志愿组" not in card_payload["content"]
    assert "专业组" in card_payload["content"]


def test_chat_service_applies_plan_next_action_pending_on_short_text_confirm(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    preview_plan = {
        "stage": "preview",
        "action_family": "sort_ordered_plan",
        "user_goal": "按院校层次排序",
        "requires_confirmation": True,
        "missing_inputs": [],
        "atomic_actions": [
            {
                "action_type": "sort_ordered_plan",
                "filters": {"sort_field": "schoolRank"},
            }
        ],
        "preview_summary": "会按院校层次重新排序当前方案。",
    }
    fake_agent = _FakeAgentWithToolCalls(
        "会按院校层次重新排序当前方案。",
        [
            ToolCallPart(
                tool_name="plan_next_action",
                args={"user_goal": "按院校层次排序", "action_family": "sort_ordered_plan"},
                tool_call_id="sort-preview-plan-next-only",
            )
        ],
        [
            ToolReturnPart(
                tool_name="plan_next_action",
                content=json.dumps(preview_plan, ensure_ascii=False),
                tool_call_id="sort-preview-plan-next-only",
            )
        ],
    )
    execution_result = json.dumps(
        {
            "applied": True,
            "action_family": "sort_ordered_plan",
            "stage": "apply",
            "result_kind": "mutation_result",
            "summary": "已按院校层次重新排序当前方案。",
            "workspace_refresh_targets": ["ordered"],
        },
        ensure_ascii=False,
    )
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch("app.service.classify_pending_confirmation_action", AsyncMock(return_value=_semantic_pending("confirm_pending"))), \
            patch("app.service.execute_plan_action", AsyncMock(return_value=execution_result)) as execute_mock:
        service = ChatService(mock_llm_client, store)
        preview_reply = asyncio.run(service.handle_message("session-plan-next-sort-preview", "user-1", "按院校层次排序"))
        confirm_reply = asyncio.run(service.handle_message("session-plan-next-sort-preview", "user-1", "确认"))

    card_payload = _assert_pending_card_envelope(preview_reply, "", "sort_ordered_plan")
    assert pending_state["value"]["pendingId"] == card_payload["pendingId"]
    assert pending_state["value"]["status"] == "applied"
    assert pending_state["value"]["executionPayload"]["planPayload"]
    assert isinstance(confirm_reply, ChatServiceResponseEnvelope)
    assert confirm_reply.primary == "已按院校层次重新排序当前方案。"
    assert len(fake_agent.calls) == 1
    execute_mock.assert_awaited_once()
    assert getattr(execute_mock.await_args.args[0].deps, "confirmed_via_pending", False) is True
    assert getattr(execute_mock.await_args.args[0].deps, "confirmation_entry", "") == "short_text"


def test_chat_service_applies_plan_pending_from_confirmation_card(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    preview_plan = {
        "stage": "preview",
        "action_family": "sort_ordered_plan",
        "user_goal": "按院校层次排序",
        "requires_confirmation": True,
        "missing_inputs": [],
        "atomic_actions": [
            {
                "action_type": "sort_ordered_plan",
                "filters": {"sort_field": "schoolRank"},
            }
        ],
        "preview_summary": "会按院校层次重新排序当前方案。",
    }
    execution_result = json.dumps(
        {
            "applied": True,
            "action_family": "sort_ordered_plan",
            "stage": "apply",
            "result_kind": "mutation_result",
            "summary": "已按院校层次重新排序当前方案。",
            "workspace_refresh_targets": ["ordered"],
        },
        ensure_ascii=False,
    )
    plan_payload = json.dumps(
        {
            **preview_plan,
            "stage": "apply",
            "requires_confirmation": False,
            "should_refresh_workspace": True,
        },
        ensure_ascii=False,
    )
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store(
        {
            "type": "pendingConfirmation",
            "pendingId": "pending-plan-1",
            "sessionId": "session-plan-card-confirm",
            "kind": "plan_mutation",
            "status": "active",
            "actionFamily": "sort_ordered_plan",
            "summary": "会按院校层次重新排序当前方案。",
            "executionPayload": {
                "toolName": "execute_plan_action",
                "planPayload": plan_payload,
            },
        }
    )

    with patch("app.service.ChatAgent", return_value=_FakeAgent(["不应该调用模型"])), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch("app.service.classify_pending_confirmation_action", AsyncMock(return_value=_semantic_pending("confirm_pending"))), \
            patch("app.service.execute_plan_action", AsyncMock(return_value=execution_result)) as execute_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_pending_confirmation(
                "session-plan-card-confirm",
                "user-1",
                json.dumps(
                    {"action": "confirm", "kind": "plan_mutation", "pendingId": "pending-plan-1"},
                    ensure_ascii=False,
                ),
            )
        )

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert reply.primary == "已按院校层次重新排序当前方案。"
    payloads = [json.loads(item.content) for item in reply.followups]
    assert [payload["targetView"] for payload in payloads] == ["ordered"]
    assert payloads[0]["preserveView"] is True
    assert payloads[0]["silent"] is True
    execute_mock.assert_awaited_once()
    assert getattr(execute_mock.await_args.args[0].deps, "confirmed_via_card", False) is True
    payload = json.loads(execute_mock.await_args.args[1])
    assert payload["stage"] == "apply"
    assert payload["action_family"] == "sort_ordered_plan"
    assert pending_state["value"]["status"] == "applied"


def test_chat_service_applies_active_plan_pending_on_short_text_confirm(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    execution_result = json.dumps(
        {
            "applied": True,
            "action_family": "sort_ordered_plan",
            "stage": "apply",
            "result_kind": "mutation_result",
            "summary": "已按院校层次重新排序当前方案。",
            "workspace_refresh_targets": ["ordered"],
        },
        ensure_ascii=False,
    )
    plan_payload = json.dumps(
        {
            "stage": "apply",
            "action_family": "sort_ordered_plan",
            "user_goal": "按院校层次排序",
            "requires_confirmation": False,
            "missing_inputs": [],
            "should_refresh_workspace": True,
        },
        ensure_ascii=False,
    )
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store(
        {
            "type": "pendingConfirmation",
            "pendingId": "pending-plan-short-text",
            "sessionId": "session-plan-short-text-confirm",
            "kind": "plan_mutation",
            "status": "active",
            "actionFamily": "sort_ordered_plan",
            "summary": "会按院校层次重新排序当前方案。",
            "executionPayload": {
                "toolName": "execute_plan_action",
                "planPayload": plan_payload,
            },
        }
    )
    fake_agent = _FakeAgent(["不应该调用模型"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch("app.service.classify_pending_confirmation_action", AsyncMock(return_value=_semantic_pending("confirm_pending"))), \
            patch("app.service.execute_plan_action", AsyncMock(return_value=execution_result)) as execute_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-plan-short-text-confirm", "user-1", "确认"))

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert reply.primary == "已按院校层次重新排序当前方案。"
    payloads = [json.loads(item.content) for item in reply.followups]
    assert [payload["targetView"] for payload in payloads] == ["ordered"]
    assert payloads[0]["preserveView"] is True
    assert payloads[0]["silent"] is True
    execute_mock.assert_awaited_once()
    deps = execute_mock.await_args.args[0].deps
    assert getattr(deps, "confirmed_via_pending", False) is True
    assert getattr(deps, "confirmed_via_card", False) is False
    assert getattr(deps, "confirmation_entry", "") == "short_text"
    assert pending_state["value"]["status"] == "applied"
    assert fake_agent.calls == []


def test_chat_service_logs_pending_event_for_short_text_confirm(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    execution_result = json.dumps(
        {
            "applied": True,
            "action_family": "sort_ordered_plan",
            "stage": "apply",
            "result_kind": "mutation_result",
            "summary": "已按院校层次重新排序当前方案。",
            "workspace_refresh_targets": [],
        },
        ensure_ascii=False,
    )
    plan_payload = json.dumps(
        {
            "stage": "apply",
            "action_family": "sort_ordered_plan",
            "user_goal": "按院校层次排序",
            "requires_confirmation": False,
        },
        ensure_ascii=False,
    )
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store(
        {
            "type": "pendingConfirmation",
            "pendingId": "pending-plan-short-text-event",
            "sessionId": "session-plan-short-text-event",
            "kind": "plan_mutation",
            "status": "active",
            "actionFamily": "sort_ordered_plan",
            "summary": "会按院校层次重新排序当前方案。",
            "sourceBackendVersion": 7,
            "executionPayload": {
                "toolName": "execute_plan_action",
                "planPayload": plan_payload,
            },
        }
    )

    with patch("app.service.ChatAgent", return_value=_FakeAgent(["不应该调用模型"])), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch("app.service.classify_pending_confirmation_action", AsyncMock(return_value=_semantic_pending("confirm_pending"))), \
            patch("app.service.execute_plan_action", AsyncMock(return_value=execution_result)), \
            patch("app.service.log_event") as log_event_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-plan-short-text-event", "user-1", "确认"))

    assert isinstance(reply, str)
    assert reply == "已按院校层次重新排序当前方案。"
    assert pending_state["value"]["status"] == "applied"
    pending_events = [
        call.kwargs
        for call in log_event_mock.call_args_list
        if call.args and call.args[0] == "pending_confirmation_event"
    ]
    assert pending_events
    event = pending_events[-1]
    assert event["eventType"] == "pending_confirmation_apply"
    assert event["pendingId"] == "pending-plan-short-text-event"
    assert event["kind"] == "plan_mutation"
    assert event["actionFamily"] == "sort_ordered_plan"
    assert event["confirmationEntry"] == "short_text"
    assert event["pendingSummary"] == "会按院校层次重新排序当前方案。"
    assert event["consistencyStatus"] == "unknown"
    assert event["blockedReason"] is None
    assert event["sourceBackendVersion"] == 7
    assert event["result"] == "applied"


def test_chat_service_blocks_short_text_confirm_when_latest_assistant_confirmation_type_conflicts(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    history = [
        ModelRequest(parts=[UserPromptPart(content="不太想去北京")]),
        ModelResponse(
            parts=[TextPart(content="确认采纳这次偏好\n\n不优先地域：北京")],
            model_name="assistant",
        ),
    ]
    asyncio.run(store.save("session-plan-short-text-conflict", history))
    plan_payload = json.dumps(
        {
            "stage": "apply",
            "action_family": "sort_ordered_plan",
            "user_goal": "按院校层次排序",
            "requires_confirmation": False,
        },
        ensure_ascii=False,
    )
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store(
        {
            "type": "pendingConfirmation",
            "pendingId": "pending-plan-short-text-conflict",
            "sessionId": "session-plan-short-text-conflict",
            "kind": "plan_mutation",
            "status": "active",
            "actionFamily": "sort_ordered_plan",
            "summary": "会按院校层次重新排序当前方案。",
            "executionPayload": {
                "toolName": "execute_plan_action",
                "planPayload": plan_payload,
            },
        }
    )

    with patch("app.service.ChatAgent", return_value=_FakeAgent(["不应该调用模型"])), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch("app.service.classify_pending_confirmation_action", AsyncMock(return_value=_semantic_pending("confirm_pending"))), \
            patch("app.service.execute_plan_action", AsyncMock()) as execute_mock, \
            patch("app.service.log_event") as log_event_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-plan-short-text-conflict", "user-1", "确认"))

    assert reply == "为避免确认错内容，请点最新内容里的“采纳”，或重新说明要确认的内容，我会重新列出待采纳内容。"
    execute_mock.assert_not_awaited()
    assert pending_state["value"]["status"] == "active"
    pending_events = [
        call.kwargs
        for call in log_event_mock.call_args_list
        if call.args and call.args[0] == "pending_confirmation_event"
    ]
    assert pending_events
    event = pending_events[-1]
    assert event["pendingId"] == "pending-plan-short-text-conflict"
    assert event["confirmationEntry"] == "short_text"
    assert event["consistencyStatus"] == "conflict"
    assert event["blockedReason"] == "assistant_confirmation_type_conflict"
    assert event["result"] == "blocked"


def test_chat_service_keeps_short_text_blocked_after_previous_consistency_block(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    history = [
        ModelRequest(parts=[UserPromptPart(content="确认")]),
        ModelResponse(
            parts=[TextPart(content="为避免确认错内容，请点最新内容里的“采纳”，或重新说明要确认的内容，我会重新列出待采纳内容。")],
            model_name="pending-confirmation-consistency-blocked:pending-plan-short-text-reblocked",
        ),
    ]
    asyncio.run(store.save("session-plan-short-text-reblocked", history))
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store(
        {
            "type": "pendingConfirmation",
            "pendingId": "pending-plan-short-text-reblocked",
            "sessionId": "session-plan-short-text-reblocked",
            "kind": "plan_mutation",
            "status": "active",
            "actionFamily": "sort_ordered_plan",
            "summary": "会按院校层次重新排序当前方案。",
            "executionPayload": {
                "toolName": "execute_plan_action",
                "planPayload": json.dumps(
                    {
                        "stage": "apply",
                        "action_family": "sort_ordered_plan",
                        "requires_confirmation": False,
                    },
                    ensure_ascii=False,
                ),
            },
        }
    )

    with patch("app.service.ChatAgent", return_value=_FakeAgent(["不应该调用模型"])), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch("app.service.classify_pending_confirmation_action", AsyncMock(return_value=_semantic_pending("confirm_pending"))), \
            patch("app.service.execute_plan_action", AsyncMock()) as execute_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-plan-short-text-reblocked", "user-1", "确认"))

    assert reply == "为避免确认错内容，请点最新内容里的“采纳”，或重新说明要确认的内容，我会重新列出待采纳内容。"
    execute_mock.assert_not_awaited()
    assert pending_state["value"]["status"] == "active"


def test_chat_service_does_not_reblock_new_pending_after_old_consistency_block(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    history = [
        ModelRequest(parts=[UserPromptPart(content="确认")]),
        ModelResponse(
            parts=[TextPart(content="为避免确认错内容，请点最新内容里的“采纳”，或重新说明要确认的内容，我会重新列出待采纳内容。")],
            model_name="pending-confirmation-consistency-blocked:old-pending",
        ),
    ]
    asyncio.run(store.save("session-plan-short-text-new-after-block", history))
    execution_result = json.dumps(
        {
            "applied": True,
            "action_family": "sort_ordered_plan",
            "stage": "apply",
            "result_kind": "mutation_result",
            "summary": "已按院校层次重新排序当前方案。",
            "workspace_refresh_targets": [],
        },
        ensure_ascii=False,
    )
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store(
        {
            "type": "pendingConfirmation",
            "pendingId": "new-pending",
            "sessionId": "session-plan-short-text-new-after-block",
            "kind": "plan_mutation",
            "status": "active",
            "actionFamily": "sort_ordered_plan",
            "summary": "会按院校层次重新排序当前方案。",
            "executionPayload": {
                "toolName": "execute_plan_action",
                "planPayload": json.dumps(
                    {
                        "stage": "apply",
                        "action_family": "sort_ordered_plan",
                        "requires_confirmation": False,
                    },
                    ensure_ascii=False,
                ),
            },
        }
    )

    with patch("app.service.ChatAgent", return_value=_FakeAgent(["不应该调用模型"])), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch("app.service.classify_pending_confirmation_action", AsyncMock(return_value=_semantic_pending("confirm_pending"))), \
            patch("app.service.execute_plan_action", AsyncMock(return_value=execution_result)) as execute_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-plan-short-text-new-after-block", "user-1", "确认"))

    assert reply == "已按院校层次重新排序当前方案。"
    execute_mock.assert_awaited_once()
    assert pending_state["value"]["status"] == "applied"


def test_chat_service_does_not_consume_plan_pending_with_explicit_intent_confirm_text(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    plan_payload = json.dumps(
        {
            "stage": "apply",
            "action_family": "sort_ordered_plan",
            "user_goal": "按院校层次排序",
            "requires_confirmation": False,
            "missing_inputs": [],
        },
        ensure_ascii=False,
    )
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store(
        {
            "type": "pendingConfirmation",
            "pendingId": "pending-plan-not-intent",
            "sessionId": "session-plan-explicit-intent-confirm",
            "kind": "plan_mutation",
            "status": "active",
            "actionFamily": "sort_ordered_plan",
            "summary": "会按院校层次重新排序当前方案。",
            "executionPayload": {
                "toolName": "execute_plan_action",
                "planPayload": plan_payload,
            },
        }
    )

    with patch("app.service.ChatAgent", return_value=_FakeAgent(["不应该调用模型"])), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch("app.service.classify_pending_confirmation_action", AsyncMock(return_value=_semantic_pending("none", confidence=0.2))), \
            patch("app.service.execute_plan_action", AsyncMock()) as execute_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-plan-explicit-intent-confirm", "user-1", "确认这个偏好"))

    assert reply == "不应该调用模型"
    execute_mock.assert_not_awaited()
    assert pending_state["value"]["status"] == "active"


def test_chat_service_rejects_replaced_pending_confirmation_card(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store(
        {
            "type": "pendingConfirmation",
            "pendingId": "new-card",
            "sessionId": "session-plan-card-replaced",
            "kind": "plan_mutation",
            "status": "active",
            "actionFamily": "sort_ordered_plan",
            "executionPayload": {"toolName": "execute_plan_action", "planPayload": "{}"},
        }
    )

    with patch("app.service.ChatAgent", return_value=_FakeAgent(["不应该调用模型"])), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch("app.service.execute_plan_action", AsyncMock()) as execute_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_pending_confirmation(
                "session-plan-card-replaced",
                "user-1",
                json.dumps(
                    {"action": "confirm", "kind": "plan_mutation", "pendingId": "old-card"},
                    ensure_ascii=False,
                ),
            )
        )

    assert reply == "这次待采纳内容已经失效。请以最新内容为准，或重新说明想怎么调整。"
    assert pending_state["value"]["pendingId"] == "new-card"
    execute_mock.assert_not_awaited()


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
                            "pendingActions": [{"summary": "补充梯度断层区间的候选"}],
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
                    "pendingActions": [{"summary": "补 2 个保底专业组"}],
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
                    "pendingActions": [{"summary": "微调 1 处相邻顺序"}],
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
    assert fake_agent.calls[1]["planning_summary"].pending_action_count == 1


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
                    "pendingActions": [],
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
                    "pendingActions": [{"summary": "补充保区志愿"}],
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
                "pendingActions": [],
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
                "pendingActions": [{"summary": "补 1 个保底志愿"}],
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
                    "pendingActions": [{"summary": "补 2 个保底专业组"}],
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
    assert fake_agent.calls[1]["planning_summary"].pending_action_count == 1


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
                    "pendingActions": [],
                },
            })):
        service = ChatService(mock_llm_client, store)
        first_reply = asyncio.run(service.handle_message("session-plan-6", "user-6", "帮我重排一下"))
        second_reply = asyncio.run(service.handle_message("session-plan-6", "user-6", "确认"))

    assert first_reply == "这会整体更新当前排序结果，建议先确认。"
    assert second_reply == "我会重新生成可确认的排序预览。"
    assert len(fake_agent.calls) == 2


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
                    "pendingActions": [],
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
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})):
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
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-general-change-policy", "user-57", "如果孩子改主意了，之前偏好还能改吗"))

    assert isinstance(reply, str)
    assert "之前偏好可以调整" in reply
    assert "采纳后再调整推荐口径和候选志愿" in reply
    assert "这轮我还没有生成可点击的待采纳内容" not in reply


def test_chat_service_recovers_unbacked_major_intent_confirmation_to_pending_card(tmp_path, mock_llm_client):
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
    clear_legacy_cache_mock = AsyncMock(return_value={"code": 0})
    recover_mock = AsyncMock(return_value=json.dumps(recovered_payload, ensure_ascii=False))

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.analyze_volunteer_intent_change", recover_mock), \
            patch("app.service.save_intent_change_cache", clear_legacy_cache_mock), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message("990503", "user-57", "会计审计这类还行，土木建筑那种别碰")
        )

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert reply.primary == ""
    assert len(reply.followups) == 1
    card_payload = json.loads(reply.followups[0].content)
    assert card_payload["type"] == "pendingConfirmationCard"
    assert card_payload["kind"] == "intent_change"
    assert card_payload["actionFamily"] == "apply_selected_intents"
    assert "" in card_payload["content"]
    assert "偏好专业：会计学、审计学" in card_payload["content"]
    assert "排除专业类：土木类、建筑类" in card_payload["content"]
    assert pending_state["value"]["kind"] == "intent_change"
    assert pending_state["value"]["status"] == "active"
    assert pending_state["value"]["summary"] == "偏好专业：会计学、审计学；排除专业类：土木类、建筑类"
    assert pending_state["value"]["executionPayload"]["selectedData"]["selected"] == [
        {"major_intents": {"level3": ["会计学", "审计学"]}},
        {"major_intents": {"negative_level2": ["土木类", "建筑类"]}},
    ]
    recover_mock.assert_awaited_once()
    clear_legacy_cache_mock.assert_awaited_once_with(990503, {})
    saved_history = asyncio.run(store.load("990503"))
    saved_text = next(part.content for part in saved_history[-1].parts if isinstance(part, TextPart))
    assert saved_text == reply.primary
    assert "你确认要这样记吗" not in saved_text


def test_chat_service_recovers_unbacked_region_intent_confirmation_to_pending_card(tmp_path, mock_llm_client):
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
    clear_legacy_cache_mock = AsyncMock(return_value={"code": 0})
    recover_mock = AsyncMock(return_value=json.dumps(recovered_payload, ensure_ascii=False))

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.analyze_volunteer_intent_change", recover_mock), \
            patch("app.service.save_intent_change_cache", clear_legacy_cache_mock), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message("990504", "user-57", "孩子就想去南方，北方先别考虑")
        )

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert reply.primary == ""
    assert len(reply.followups) == 1
    card_payload = json.loads(reply.followups[0].content)
    assert card_payload["type"] == "pendingConfirmationCard"
    assert card_payload["kind"] == "intent_change"
    assert card_payload["actionFamily"] == "apply_selected_intents"
    assert "浙江、上海、江苏、广东" in card_payload["content"]
    assert "北京、天津、河北、山东" in card_payload["content"]
    assert pending_state["value"]["kind"] == "intent_change"
    assert pending_state["value"]["status"] == "active"
    assert pending_state["value"]["executionPayload"]["selectedData"]["selected"] == [
        {"city_intents": {"province": ["浙江", "上海", "江苏", "广东"]}},
        {"city_intents": {"negative_province": ["北京", "天津", "河北", "山东"]}},
    ]
    recover_mock.assert_awaited_once()
    assert recover_mock.await_args.kwargs["recovery_scope"] == "generic"
    clear_legacy_cache_mock.assert_awaited_once_with(990504, {})
    saved_history = asyncio.run(store.load("990504"))
    saved_text = next(part.content for part in saved_history[-1].parts if isinstance(part, TextPart))
    assert saved_text == reply.primary
    assert "你确认要这样记吗" not in saved_text


def test_chat_service_recovers_claimed_region_card_without_tool_and_drops_mixed_history(tmp_path, mock_llm_client):
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
    clear_legacy_cache_mock = AsyncMock(return_value={"code": 0})
    recover_mock = AsyncMock(return_value=json.dumps(recovered_payload, ensure_ascii=False))

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.analyze_volunteer_intent_change", recover_mock), \
            patch("app.service.save_intent_change_cache", clear_legacy_cache_mock), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("990505", "user-57", "不想去内蒙"))

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert reply.primary == ""
    assert len(reply.followups) == 1
    card_payload = json.loads(reply.followups[0].content)
    assert card_payload["type"] == "pendingConfirmationCard"
    assert card_payload["kind"] == "intent_change"
    assert card_payload["actionFamily"] == "apply_selected_intents"
    assert "内蒙古" in card_payload["content"]
    assert "天津" not in card_payload["content"]
    assert pending_state["value"]["executionPayload"]["selectedData"]["selected"] == [
        {"city_intents": {"negative_province": ["内蒙古"]}},
    ]
    recover_mock.assert_awaited_once()
    assert recover_mock.await_args.kwargs["recovery_scope"] == "generic"
    saved_history = asyncio.run(store.load("990505"))
    saved_text = next(part.content for part in saved_history[-1].parts if isinstance(part, TextPart))
    assert saved_text == reply.primary
    assert "天津" not in saved_text
    assert "已经为你生成了排除内蒙古的待采纳内容" not in saved_text


def test_chat_service_recovers_recorded_intent_claim_after_plan_chain_to_pending_card(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    bad_reply = (
        "我已经把“方案里必须有临床医学”作为后续报考参考记下来。"
        "后续生成或调整方案时会优先保证这个方向。"
    )
    fake_agent = _FakeAgentWithToolCalls(
        bad_reply,
        [
            ToolCallPart(
                tool_name="plan_next_action",
                args={"action_family": "preview_compensation"},
                tool_call_id="must-have-plan-1",
            ),
            ToolCallPart(
                tool_name="execute_plan_action",
                args={"plan_payload": "{}"},
                tool_call_id="must-have-plan-2",
            ),
        ],
        [
            ToolReturnPart(
                tool_name="plan_next_action",
                content=json.dumps(
                    {"action_family": "preview_compensation", "stage": "apply"},
                    ensure_ascii=False,
                ),
                tool_call_id="must-have-plan-1",
            ),
            ToolReturnPart(
                tool_name="execute_plan_action",
                content=json.dumps(
                    {
                        "applied": False,
                        "action_family": "preview_compensation",
                        "stage": "apply",
                        "result_kind": "compensation_preview",
                        "summary": "候选里暂时没有合适补位。",
                    },
                    ensure_ascii=False,
                ),
                tool_call_id="must-have-plan-2",
            ),
        ],
    )
    recovered_payload = {
        "status": "ready",
        "sessionId": "990509",
        "title": "待采纳报考条件",
        "intentMode": "constraint",
        "constraintIntentType": "must_have",
        "analysisStage": "confirmed",
        "items": [
            {
                "content": "至少保留专业：临床医学",
                "value": {"major_intents": {"level3": ["临床医学"]}},
                "selected": True,
            },
        ],
        "existingItems": [],
    }
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()
    clear_legacy_cache_mock = AsyncMock(return_value={"code": 0})
    recover_mock = AsyncMock(return_value=json.dumps(recovered_payload, ensure_ascii=False))

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.analyze_volunteer_intent_change", recover_mock), \
            patch("app.service.save_intent_change_cache", clear_legacy_cache_mock), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("990509", "user-57", "方案里必须有临床医学，其他专业可以先保留"))

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert reply.primary == ""
    assert len(reply.followups) == 1
    card_payload = json.loads(reply.followups[0].content)
    assert card_payload["type"] == "pendingConfirmationCard"
    assert card_payload["kind"] == "intent_change"
    assert card_payload["actionFamily"] == "apply_selected_intents"
    assert card_payload["constraintIntentType"] == "must_have"
    assert "临床医学" in card_payload["content"]
    assert pending_state["value"]["kind"] == "intent_change"
    assert pending_state["value"]["status"] == "active"
    assert pending_state["value"]["executionPayload"]["selectedData"]["selected"] == [
        {"major_intents": {"level3": ["临床医学"]}},
    ]
    recover_mock.assert_awaited_once()
    clear_legacy_cache_mock.assert_awaited_once_with(990509, {})
    saved_history = asyncio.run(store.load("990509"))
    saved_text = next(part.content for part in saved_history[-1].parts if isinstance(part, TextPart))
    assert saved_text == reply.primary
    assert "已经把" not in saved_text
    assert "作为后续报考参考记下来" not in saved_text


def test_chat_service_does_not_recover_unbacked_intent_card_after_plan_review(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    review_reply = (
        "这版确实偏冲，当前冲66 / 稳28 / 保0，主要风险是保底不足。"
        "如果后续要把预算或排除方向作为参考，需要先生成待采纳内容；这轮只是帮你看风险，不会改动方案。"
    )
    fake_agent = _FakeAgentWithToolCalls(
        review_reply,
        [
            ToolCallPart(
                tool_name="plan_next_action",
                args={"action_family": "review_plan"},
                tool_call_id="plan-review-1",
            ),
            ToolCallPart(
                tool_name="execute_plan_action",
                args={"plan_payload": "{}"},
                tool_call_id="plan-review-2",
            ),
        ],
        [
            ToolReturnPart(
                tool_name="plan_next_action",
                content=json.dumps(
                    {"action_family": "review_plan", "stage": "review", "success": True},
                    ensure_ascii=False,
                ),
                tool_call_id="plan-review-1",
            ),
            ToolReturnPart(
                tool_name="execute_plan_action",
                content=json.dumps(
                    {
                        "action_family": "review_plan",
                        "stage": "review",
                        "result_kind": "review_result",
                        "applied": True,
                        "success": True,
                    },
                    ensure_ascii=False,
                ),
                tool_call_id="plan-review-2",
            ),
        ],
    )
    recover_mock = AsyncMock(return_value=json.dumps({"status": "empty", "sessionId": "990504"}, ensure_ascii=False))

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.analyze_volunteer_intent_change", recover_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("990504", "user-57", "这版是不是太冲了，能不能给我说人话"))

    assert isinstance(reply, str)
    assert reply == review_reply
    assert "冲66 / 稳28 / 保0" in reply
    assert "这轮只是帮你看风险" in reply
    recover_mock.assert_not_awaited()
    saved_history = asyncio.run(store.load("990504"))
    saved_text = next(part.content for part in saved_history[-1].parts if isinstance(part, TextPart))
    assert saved_text == review_reply


def test_chat_service_uses_readonly_plan_result_when_guarding_fake_plan_confirm_copy(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    bad_reply = (
        "我看了一下，中外合作确实要关注。"
        "如果你确认要调整，我可以把预算压力大的志愿移出方案。"
    )
    review_summary = "中外合作志愿占比偏高，家里预算一般时主要风险是学费压力和保底不足；这轮只分析，不调整方案。"
    fake_agent = _FakeAgentWithToolCalls(
        bad_reply,
        [
            ToolCallPart(
                tool_name="execute_plan_action",
                args=json.dumps({"plan_payload": "{}"}, ensure_ascii=False),
                tool_call_id="readonly-review-1",
            ),
        ],
        [
            ToolReturnPart(
                tool_name="execute_plan_action",
                content=json.dumps(
                    {
                        "action_family": "review_plan",
                        "stage": "review",
                        "result_kind": "review_result",
                        "applied": True,
                        "success": True,
                        "summary": review_summary,
                    },
                    ensure_ascii=False,
                ),
                tool_call_id="readonly-review-1",
            ),
        ],
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message("990507", "user-57", "方案里中外合作是不是有点多，家里预算一般，帮我用大白话看下风险，先别动")
        )

    assert isinstance(reply, str)
    assert "我已经帮你检查了方案" in reply
    assert "中外合作志愿占比偏高" in reply
    assert "预算一般" in reply
    assert "只分析，不调整方案" in reply
    assert "这轮还没有生成可点击的方案待采纳内容" not in reply
    assert "确认要调整" not in reply
    saved_history = asyncio.run(store.load("990507"))
    saved_text = next(part.content for part in saved_history[-1].parts if isinstance(part, TextPart))
    assert saved_text == reply


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
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("990508", "user-57", "青城那个是不是放多了，能查下"))

    assert isinstance(reply, str)
    assert "青岛城市学院" in reply
    assert "当前方案里有 7 条" in reply
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
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})):
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
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch(
                "app.service.get_intent_change_cache",
                AsyncMock(return_value={"data": {"planEditCache": {"major_intents": {"level3": ["会计学"]}}}}),
            ):
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
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})):
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
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch(
                "app.service.get_intent_change_cache",
                AsyncMock(return_value={"data": {"planEditCache": {"major_intents": {"level3": ["会计学"]}}}}),
            ):
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
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch(
                "app.service.get_intent_change_cache",
                AsyncMock(return_value={"data": {"planEditCache": {"major_intents": {"level3": ["会计学"]}}}}),
            ):
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
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch(
                "app.service.get_intent_change_cache",
                AsyncMock(return_value={"data": {"planEditCache": {"major_intents": {"level3": ["会计学"]}}}}),
            ):
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


def test_chat_service_text_confirm_workspace_actions_require_card_click(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    preview_payload = {
        "stage": "preview",
        "action_family": "remove_units",
        "user_goal": "排除会计和审计相关志愿",
        "missing_inputs": [],
        "atomic_actions": [{"action_type": "remove_units", "volunteer_ids": ["v1", "v2"]}],
        "preview_summary": "会移出会计和审计相关志愿。",
    }
    history = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args={"plan_payload": json.dumps(preview_payload, ensure_ascii=False)},
                    tool_call_id="preview-clear-copy",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": False,
                            "action_family": "remove_units",
                            "result_kind": "preview_only",
                            "summary": "会移出会计和审计相关志愿。",
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="preview-clear-copy",
                )
            ]
        ),
    ]
    asyncio.run(store.save("session-direct-copy", history))
    execution_result = json.dumps(
        {
            "applied": True,
            "action_family": "remove_units",
            "stage": "apply",
            "result_kind": "mutation_result",
            "summary": (
                "已移出不匹配志愿，并完成复审。\n"
                "- 录取率梯度是否达标：否\n"
                "- 主要提醒：当前排序存在录取概率倒挂；当前录取概率梯度存在断层"
            ),
            "workspace_refresh_targets": ["ordered"],
        },
        ensure_ascii=False,
    )
    fake_agent = _FakeAgent(["不应该调用模型"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.execute_plan_action", AsyncMock(return_value=execution_result)) as execute_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-direct-copy", "user-57", "确认"))

    assert reply == fake_agent._replies[0]
    execute_mock.assert_not_awaited()
    assert len(fake_agent.calls) == 1


def test_chat_service_dialog_replace_preview_text_confirm_requires_card_click(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    preview_payload = {
        "stage": "preview",
        "action_family": "replace_units",
        "user_goal": "替换方案中会计学和审计学专业",
        "requires_confirmation": True,
        "missing_inputs": [],
        "should_rerun_review": False,
        "atomic_actions": [
            {
                "action_type": "replace_units",
                "volunteer_ids": ["南宁学院第01组-会计学", "广东白云学院第01组-审计学"],
                "target_position": None,
                "filters": {
                    "major_tags": json.dumps(["跨境电商", "网络与新媒体"], ensure_ascii=False),
                    "limit": "1",
                },
                "reason": "排除会计审计后补入更符合意向的方向",
            }
        ],
        "preview_summary": "会先移出会计和审计，再按新方向补入候选。",
    }
    fake_agent = _FakeAgentWithMessageSequence(
        [
            (
                "我先给你看替换预览，确认后再执行。",
                [
                    ModelResponse(
                        parts=[
                            ToolCallPart(
                                tool_name="execute_plan_action",
                                args={"plan_payload": json.dumps(preview_payload, ensure_ascii=False)},
                                tool_call_id="dialog-preview-display-refs",
                            )
                        ],
                        model_name="test-model",
                    ),
                    ModelRequest(
                        parts=[
                            ToolReturnPart(
                                tool_name="execute_plan_action",
                                content=json.dumps(
                                    {
                                        "applied": False,
                                        "action_family": "replace_units",
                                        "stage": "preview",
                                        "result_kind": "preview_only",
                                        "summary": "会先移出会计和审计，再按新方向补入候选。",
                                    },
                                    ensure_ascii=False,
                                ),
                                tool_call_id="dialog-preview-display-refs",
                            )
                        ]
                    ),
                ],
            )
            ,
            (
                "已按你的确认完成替换，并刷新排序和审查结果。",
                [
                    ModelResponse(
                        parts=[
                            ToolCallPart(
                                tool_name="execute_plan_action",
                                args={"plan_payload": json.dumps({"stage": "apply", "action_family": "replace_units"}, ensure_ascii=False)},
                                tool_call_id="dialog-apply-display-refs",
                            )
                        ],
                        model_name="test-model",
                    ),
                    ModelRequest(
                        parts=[
                            ToolReturnPart(
                                tool_name="execute_plan_action",
                                content=json.dumps(
                                    {
                                        "applied": True,
                                        "action_family": "replace_units",
                                        "stage": "apply",
                                        "result_kind": "mutation_result",
                                        "summary": "已按你的确认完成替换，并刷新排序和审查结果。",
                                        "workspace_refresh_targets": ["ordered"],
                                    },
                                    ensure_ascii=False,
                                ),
                                tool_call_id="dialog-apply-display-refs",
                            )
                        ]
                    ),
                ],
            ),
        ]
    )
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch(
                "app.tools.plan_execution_tool._get_planning_ordered_plan_request",
                AsyncMock(
                    return_value={
                        "code": 0,
                        "data": {
                            "items": [
                                {
                                    "volunteerId": "v-accounting",
                                    "schoolName": "南宁学院第01组",
                                    "majorName": "会计学",
                                },
                                {
                                    "volunteerId": "v-audit",
                                    "schoolName": "广东白云学院第01组",
                                    "majorName": "审计学",
                                },
                            ]
                        },
                    }
                ),
            ), \
            patch("app.handlers.mutation_handlers.remove_planning_ordered_items", AsyncMock(return_value="已移出旧志愿")) as remove_mock, \
            patch("app.handlers.mutation_handlers._select_candidates_by_filters_into_plan", AsyncMock(return_value="已补入新候选")) as add_mock, \
            patch("app.service.classify_pending_confirmation_action", AsyncMock(return_value=_semantic_pending("confirm_pending"))), \
            patch("app.tools.plan_execution_tool.run_planning_review", AsyncMock(return_value="复审完成")):
        service = ChatService(mock_llm_client, store)
        preview_reply = asyncio.run(service.handle_message("session-dialog-57-replay", "user-57", "调整下"))
        confirm_reply = asyncio.run(service.handle_message("session-dialog-57-replay", "user-57", "确认"))

    _assert_pending_card_envelope(preview_reply, "", "replace_units")
    assert isinstance(confirm_reply, ChatServiceResponseEnvelope)
    assert "已移出旧志愿" in confirm_reply.primary
    assert "已补入新候选" in confirm_reply.primary
    assert "复审完成" in confirm_reply.primary
    remove_mock.assert_awaited_once()
    add_mock.assert_awaited_once()
    assert pending_state["value"]["status"] == "applied"
    assert fake_agent.calls[0] == {"user_prompt": "调整下", "pending_plan_action": None}
    assert len(fake_agent.calls) == 1


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
    clear_legacy_cache_mock = AsyncMock(return_value={"code": 0})

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
            patch("app.service.save_intent_change_cache", clear_legacy_cache_mock), \
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
    clear_legacy_cache_mock.assert_awaited_once_with(31, {})


def test_chat_service_pending_intent_confirmation_applies_and_prompts_plan_check(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    structured_result = {
        "action": "apply_selected",
        "sessionId": "33",
        "intentMode": "constraint",
        "applied": True,
        "messageCode": "custom_constraint_code_without_text_coupling",
        "message": "结构化执行成功",
        "merged": {"city_intents": {"province": ["北京"]}},
    }
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store(
        {
            "type": "pendingConfirmation",
            "pendingId": "intent-pending-1",
            "sessionId": "33",
            "kind": "intent_change",
            "status": "active",
            "actionFamily": "apply_selected_intents",
            "executionPayload": {
                "toolName": "apply_selected_intents",
                "selectedData": {
                    "message_id": 2003,
                    "selected": [{"city_intents": {"province": ["北京"]}}],
                },
                "intentMode": "constraint",
                "batch": "01",
            },
        }
    )
    card_message_content = {
        "type": "pendingConfirmationCard",
        "pendingId": "intent-pending-1",
        "kind": "intent_change",
        "clickable": True,
        "clicked": False,
        "status": "active",
    }

    with patch("app.service.ChatAgent"), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch(
                "app.service.get_message_by_id",
                AsyncMock(return_value={"data": {"content": json.dumps(card_message_content, ensure_ascii=False)}}),
            ) as get_message_mock, \
            patch("app.service.update_message", AsyncMock(return_value={"code": 0})) as update_message_mock, \
            patch(
                "app.service._apply_selected_intents",
                new=AsyncMock(return_value=json.dumps(structured_result, ensure_ascii=False)),
            ):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_pending_confirmation(
                "33",
                "user-33",
                json.dumps(
                    {
                        "action": "confirm",
                        "kind": "intent_change",
                        "pendingId": "intent-pending-1",
                        "message_id": 7001,
                    },
                    ensure_ascii=False,
                ),
            )
        )

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert reply.primary == "结构化执行成功"
    payload = json.loads(reply.followups[0].content)
    assert len(reply.followups) == 1
    assert payload["targetView"] == "ordered"
    assert payload["preserveView"] is True
    assert payload["silent"] is True
    assert payload["title"] == "请查看方案"
    assert payload["actionText"] == "查看方案"
    assert "candidateFilters" not in payload
    assert pending_state["value"]["status"] == "applied"
    get_message_mock.assert_awaited_once_with("7001")
    update_message_mock.assert_awaited_once()
    update_kwargs = update_message_mock.await_args.kwargs
    assert update_kwargs["message_id"] == "7001"
    assert update_kwargs["chat_session_id"] == "33"
    assert update_kwargs["content_type"] == "CARD"
    assert update_kwargs["content"]["clickable"] is False
    assert update_kwargs["content"]["clicked"] is True
    assert update_kwargs["content"]["status"] == "applied"


def test_chat_service_constraint_preview_with_plan_hit_becomes_plan_mutation_card():
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
    execution_preview = {
        "applied": False,
        "action_family": "remove_units",
        "stage": "preview",
        "result_kind": "preview_only",
        "summary": "已在当前方案里定位到“专业：经济与金融”相关的 1 条志愿。确认后会移出。",
        "facts": {
            "matched_count": 1,
            "resolved_apply_payload": {
                "action_family": "remove_units",
                "atomic_actions": [
                    {
                        "action_type": "remove_units",
                        "volunteer_ids": ["econ-finance-1"],
                        "source_major_names": ["经济与金融"],
                        "filters": {"major_level3": ["经济与金融"]},
                    }
                ],
            },
        },
    }
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch(
                "app.service.execute_plan_action",
                AsyncMock(return_value=json.dumps(execution_preview, ensure_ascii=False)),
            ) as execute_mock:
        card = asyncio.run(_create_pending_intent_confirmation_from_preview_payload("34", preview_payload))

    assert isinstance(card, WSResponse)
    payload = json.loads(card.content)
    assert payload["kind"] == "plan_mutation"
    assert payload["actionFamily"] == "remove_units"
    assert payload["confirmText"] == "确认执行"
    assert pending_state["value"]["kind"] == "plan_mutation"
    intent_payload = pending_state["value"]["executionPayload"]["intentPayload"]
    assert intent_payload["intentMode"] == "constraint"
    assert intent_payload["selected"] == [{"major_intents": {"negative_level3": ["经济与金融"]}}]
    plan_payload = json.loads(pending_state["value"]["executionPayload"]["planPayload"])
    assert plan_payload["atomic_actions"][0]["volunteer_ids"] == ["econ-finance-1"]
    composite = pending_state["value"]["compositeProposal"]
    assert composite["goal"]["goal_type"] == "exclude_scope"
    assert composite["goal"]["negative_scopes"] == [
        {"entity_type": "major", "values": ["经济与金融"]}
    ]
    assert composite["intent_updates"][0]["negativeScopes"] == [
        {"entity_type": "major", "values": ["经济与金融"]}
    ]
    assert plan_payload["composite_proposal"]["goal"]["goal_type"] == "exclude_scope"
    execute_mock.assert_awaited_once()


def test_chat_service_constraint_preview_attaches_backend_user_goal_fix_proposal():
    preview_payload = {
        "status": "ready",
        "sessionId": "34-link",
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
    execution_preview = {
        "applied": False,
        "action_family": "remove_units",
        "stage": "preview",
        "result_kind": "preview_only",
        "summary": "已在当前方案里定位到“专业：经济与金融”相关的 1 条志愿。确认后会移出。",
        "facts": {
            "planning_version": 12,
            "matched_count": 1,
            "resolved_apply_payload": {
                "action_family": "remove_units",
                "atomic_actions": [
                    {
                        "action_type": "remove_units",
                        "volunteer_ids": ["econ-finance-1"],
                        "source_major_names": ["经济与金融"],
                        "filters": {"major_level3": ["经济与金融"]},
                    }
                ],
            },
        },
    }
    backend_preview = {
        "code": 0,
        "data": {
            "proposalSource": "user_goal",
            "sourceVersionGuard": 12,
            "proposals": [
                {
                    "proposalId": "ug-exclude-1",
                    "proposalSource": "user_goal",
                    "sourceVersion": 12,
                    "sourceVersionGuard": 12,
                    "strategy": "exclude_scope",
                    "status": "preview_only",
                    "title": "避开经济与金融",
                    "summary": "当前方案有 1 条命中，可先形成替换预览。",
                    "requiresConfirmation": False,
                    "actions": [
                        {
                            "actionType": "replace_volunteers",
                            "removeVolunteerIds": ["econ-finance-1"],
                            "candidateVolunteerIds": ["law-1"],
                            "replacementPairs": [
                                {
                                    "fromVolunteerId": "econ-finance-1",
                                    "toVolunteerId": "law-1",
                                }
                            ],
                        }
                    ],
                    "dryRunResult": {"status": "preview_only"},
                }
            ],
        },
    }
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch(
                "app.service.execute_plan_action",
                AsyncMock(return_value=json.dumps(execution_preview, ensure_ascii=False)),
            ), \
            patch(
                "app.service.generate_user_goal_planning_fix_proposals",
                AsyncMock(return_value=backend_preview),
            ) as backend_preview_mock:
        card = asyncio.run(_create_pending_intent_confirmation_from_preview_payload("34-link", preview_payload))

    assert isinstance(card, WSResponse)
    payload = json.loads(card.content)
    assert payload["kind"] == "plan_mutation"
    composite = pending_state["value"]["compositeProposal"]
    assert composite["source_version"] == 12
    linked = composite["linked_fix_proposals"]
    assert len(linked) == 1
    assert linked[0]["proposal_source"] == "user_goal"
    assert linked[0]["strategy"] == "exclude_scope"
    assert linked[0]["status"] == "preview_only"
    assert linked[0]["applyable"] is False
    assert linked[0]["actions"][0]["action_type"] == "replace_volunteers"
    assert linked[0]["actions"][0]["replacement_pairs"][0]["toVolunteerId"] == "law-1"
    backend_preview_mock.assert_awaited_once()
    req = backend_preview_mock.await_args.args[2]
    assert req["goalType"] == "exclude_scope"
    assert req["sourceVersionGuard"] == 12
    assert req["negativeScopes"][0]["entityType"] == "major"
    assert req["negativeScopes"][0]["normalizedName"] == "经济与金融"


def test_chat_service_constraint_backend_preview_expands_multi_value_scope():
    preview_payload = {
        "status": "ready",
        "sessionId": "34-multi",
        "title": "确认这条要求",
        "intentMode": "constraint",
        "analysisStage": "confirmed",
        "items": [
            {
                "content": "排除专业：会计学、审计学",
                "selected": True,
                "value": {"major_intents": {"negative_level3": ["会计学", "审计学"]}},
            }
        ],
    }
    execution_preview = {
        "applied": False,
        "action_family": "remove_units",
        "stage": "preview",
        "result_kind": "preview_only",
        "summary": "已在当前方案里定位到会计和审计相关志愿。确认后会移出。",
        "facts": {
            "planning_version": 18,
            "matched_count": 2,
            "resolved_apply_payload": {
                "action_family": "remove_units",
                "atomic_actions": [
                    {
                        "action_type": "remove_units",
                        "volunteer_ids": ["accounting-1", "audit-1"],
                        "source_major_names": ["会计学", "审计学"],
                    }
                ],
            },
        },
    }
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch(
                "app.service.execute_plan_action",
                AsyncMock(return_value=json.dumps(execution_preview, ensure_ascii=False)),
            ), \
            patch(
                "app.service.generate_user_goal_planning_fix_proposals",
                AsyncMock(return_value={"code": 0, "data": {"proposalSource": "user_goal", "proposals": []}}),
            ) as backend_preview_mock:
        card = asyncio.run(_create_pending_intent_confirmation_from_preview_payload("34-multi", preview_payload))

    assert isinstance(card, WSResponse)
    assert pending_state["value"]["kind"] == "plan_mutation"
    req = backend_preview_mock.await_args.args[2]
    assert req["goalType"] == "exclude_scope"
    assert req["sourceVersionGuard"] == 18
    assert [scope["normalizedName"] for scope in req["negativeScopes"]] == ["会计学", "审计学"]


def test_chat_service_mixed_intent_plan_hit_card_keeps_positive_preference_summary():
    preview_payload = {
        "status": "ready",
        "sessionId": "37",
        "title": "确认这次报考参考",
        "intentMode": "constraint",
        "analysisStage": "confirmed",
        "items": [
            {
                "content": "偏好专业：会计学、审计学",
                "selected": True,
                "value": {"major_intents": {"level3": ["会计学", "审计学"]}},
            },
            {
                "content": "排除专业：土木工程",
                "selected": True,
                "value": {"major_intents": {"negative_level3": ["土木工程"]}},
            },
        ],
    }
    execution_preview = {
        "applied": False,
        "action_family": "remove_units",
        "stage": "preview",
        "result_kind": "preview_only",
        "summary": "已在当前方案里定位到“具体专业：土木工程”相关的 1 条志愿。确认后会移出。",
        "facts": {
            "matched_count": 1,
            "resolved_apply_payload": {
                "action_family": "remove_units",
                "atomic_actions": [
                    {
                        "action_type": "remove_units",
                        "volunteer_ids": ["civil-1"],
                        "source_major_names": ["土木工程"],
                        "filters": {"major_level3": ["土木工程"]},
                    }
                ],
            },
        },
    }
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch(
                "app.service.execute_plan_action",
                AsyncMock(return_value=json.dumps(execution_preview, ensure_ascii=False)),
            ):
        card = asyncio.run(_create_pending_intent_confirmation_from_preview_payload("37", preview_payload))

    assert isinstance(card, WSResponse)
    payload = json.loads(card.content)
    assert payload["kind"] == "plan_mutation"
    assert payload["actionFamily"] == "remove_units"
    assert "会计学" in payload["content"]
    assert "审计学" in payload["content"]
    assert "土木工程" in payload["content"]
    assert "优先方向" in payload["impact"]
    assert "避开的方向" in payload["impact"]
    intent_payload = pending_state["value"]["executionPayload"]["intentPayload"]
    assert intent_payload["intentMode"] == "constraint"
    assert intent_payload["selected"] == [
        {"major_intents": {"level3": ["会计学", "审计学"]}},
        {"major_intents": {"negative_level3": ["土木工程"]}},
    ]


def test_chat_service_negative_plan_hit_card_keeps_existing_positive_preference_summary():
    preview_payload = {
        "status": "ready",
        "sessionId": "38",
        "title": "确认这次报考参考",
        "intentMode": "constraint",
        "analysisStage": "confirmed",
        "items": [
            {
                "content": "排除专业：土木工程",
                "selected": True,
                "value": {"major_intents": {"negative_level3": ["土木工程"]}},
            },
        ],
        "existingItems": [
            {
                "content": "偏好专业：会计学、审计学",
                "selected": True,
                "value": {"major_intents": {"level3": ["会计学", "审计学"]}},
            }
        ],
    }
    execution_preview = {
        "applied": False,
        "action_family": "remove_units",
        "stage": "preview",
        "result_kind": "preview_only",
        "summary": "已在当前方案里定位到“具体专业：土木工程”相关的 1 条志愿。确认后会移出。",
        "facts": {
            "matched_count": 1,
            "resolved_apply_payload": {
                "action_family": "remove_units",
                "atomic_actions": [
                    {
                        "action_type": "remove_units",
                        "volunteer_ids": ["civil-1"],
                        "source_major_names": ["土木工程"],
                        "filters": {"major_level3": ["土木工程"]},
                    }
                ],
            },
        },
    }
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch(
                "app.service.execute_plan_action",
                AsyncMock(return_value=json.dumps(execution_preview, ensure_ascii=False)),
            ):
        card = asyncio.run(_create_pending_intent_confirmation_from_preview_payload("38", preview_payload))

    assert isinstance(card, WSResponse)
    payload = json.loads(card.content)
    assert payload["kind"] == "plan_mutation"
    assert payload["actionFamily"] == "remove_units"
    assert "会计学" in payload["content"]
    assert "审计学" in payload["content"]
    assert "土木工程" in payload["content"]
    assert "优先方向" in payload["impact"]
    assert "避开的方向" in payload["impact"]
    intent_payload = pending_state["value"]["executionPayload"]["intentPayload"]
    assert intent_payload["intentMode"] == "constraint"
    assert intent_payload["selected"] == [
        {"major_intents": {"negative_level3": ["土木工程"]}},
        {"major_intents": {"level3": ["会计学", "审计学"]}},
    ]


def test_chat_service_pending_preference_confirmation_does_not_force_plan_review(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    structured_result = {
        "action": "apply_selected",
        "sessionId": "35",
        "intentMode": "preference",
        "applied": True,
        "messageCode": "custom_preference_code_without_text_coupling",
        "message": "偏好已采纳",
        "merged": {"major_intents": {"level3": ["法学"]}},
    }
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store(
        {
            "type": "pendingConfirmation",
            "pendingId": "intent-pending-preference",
            "sessionId": "35",
            "kind": "intent_change",
            "status": "active",
            "actionFamily": "apply_selected_intents",
            "executionPayload": {
                "toolName": "apply_selected_intents",
                "selectedData": {
                    "message_id": 2004,
                    "selected": [{"major_intents": {"level3": ["法学"]}}],
                },
                "intentMode": "preference",
                "batch": "01",
            },
        }
    )

    with patch("app.service.ChatAgent"), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch(
                "app.service._apply_selected_intents",
                new=AsyncMock(return_value=json.dumps(structured_result, ensure_ascii=False)),
            ):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_pending_confirmation(
                "35",
                "user-35",
                json.dumps(
                    {"action": "confirm", "kind": "intent_change", "pendingId": "intent-pending-preference"},
                    ensure_ascii=False,
                ),
            )
        )

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert reply.primary == "偏好已采纳"
    assert len(reply.followups) == 1
    assert reply.followups[0].type == "planningWorkspaceAction"
    workspace_payload = json.loads(reply.followups[0].content)
    assert workspace_payload["targetView"] == "candidate"
    assert workspace_payload["refresh"] is True
    assert workspace_payload["preserveView"] is True
    assert workspace_payload["silent"] is True
    assert pending_state["value"]["status"] == "applied"


def test_chat_service_pending_plan_confirmation_applies_intent_payload_before_plan(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    plan_payload = {
        "stage": "apply",
        "action_family": "remove_units",
        "user_goal": "删除方案中包含汉语言文学的所有志愿",
        "requires_confirmation": False,
        "should_rerun_review": True,
        "should_refresh_workspace": True,
        "missing_inputs": [],
        "atomic_actions": [
            {
                "action_type": "remove_units",
                "volunteer_ids": ["hywx-1", "hywx-2"],
                "source_major_names": ["汉语言文学"],
                "filters": {},
            }
        ],
    }
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store(
        {
            "type": "pendingConfirmation",
            "pendingId": "plan-intent-pending-1",
            "sessionId": "36",
            "kind": "plan_mutation",
            "status": "active",
            "actionFamily": "remove_units",
            "summary": "确认后移出汉语言文学，并更新后续报考参考。",
            "executionPayload": {
                "toolName": "execute_plan_action",
                "planPayload": json.dumps(plan_payload, ensure_ascii=False),
                "intentPayload": {
                    "selected": [{"major_intents": {"negative_level3": ["汉语言文学"]}}],
                    "intentMode": "constraint",
                    "batch": "01",
                },
            },
        }
    )
    intent_result = {
        "action": "apply_selected",
        "sessionId": "36",
        "intentMode": "constraint",
        "applied": True,
        "messageCode": "constraint_applied",
        "message": "要求已采纳",
    }
    plan_result = {
        "applied": True,
        "action_family": "remove_units",
        "stage": "apply",
        "result_kind": "mutation_result",
        "summary": "已从当前方案移出2个志愿。",
        "workspace_refresh_targets": ["ordered", "candidate", "review"],
    }

    with patch("app.service.ChatAgent"), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 0, "data": {}})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 0, "data": {}})), \
            patch("app.service._apply_selected_intents", new=AsyncMock(return_value=json.dumps(intent_result, ensure_ascii=False))) as apply_mock, \
            patch("app.service.execute_plan_action", new=AsyncMock(return_value=json.dumps(plan_result, ensure_ascii=False))) as execute_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_pending_confirmation(
                "36",
                "user-36",
                json.dumps(
                    {
                        "action": "confirm",
                        "kind": "plan_mutation",
                        "pendingId": "plan-intent-pending-1",
                    },
                    ensure_ascii=False,
                ),
            )
        )

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert "已从当前方案移出2个志愿" in reply.primary
    assert "后续报考参考已同步更新" in reply.primary
    apply_mock.assert_awaited_once()
    assert apply_mock.await_args.kwargs["selected_data"]["intentMode"] == "constraint"
    assert apply_mock.await_args.kwargs["selected_data"]["selected"] == [
        {"major_intents": {"negative_level3": ["汉语言文学"]}}
    ]
    execute_mock.assert_awaited_once()
    target_views = [json.loads(item.content)["targetView"] for item in reply.followups]
    assert "ordered" in target_views
    assert "candidate" not in target_views
    assert pending_state["value"]["status"] == "applied"


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
    clear_legacy_cache_mock = AsyncMock(return_value={"code": 0})

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
            patch("app.service.save_intent_change_cache", clear_legacy_cache_mock), \
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
    apply_mock.assert_not_awaited()
    clear_legacy_cache_mock.assert_awaited_once_with(32, {})


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
    clear_legacy_cache_mock = AsyncMock(return_value={"code": 0})

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
            patch("app.service.get_pending_confirmation", get_pending_mock), \
            patch("app.service.save_intent_change_cache", clear_legacy_cache_mock):
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
    followup_mock.assert_awaited_once_with(
        session_id="36",
        batch="01",
        action_type="prefer_confirm",
    )
    clear_legacy_cache_mock.assert_awaited_once_with(36, {})


def test_chat_service_does_not_attach_workspace_card_for_readonly_candidate_query(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgentWithToolCalls(
        "候选里有一些更稳的会计审计机会，我先按学校层次、录取率和专业匹配度帮你看了下，暂时没有加入方案。",
        [
            ToolCallPart(
                tool_name="execute_plan_action",
                args={
                    "plan_payload": json.dumps(
                        {
                            "stage": "apply",
                            "action_family": "query_candidates",
                            "context_summary": "候选只读查询",
                            "preview_summary": "",
                            "missing_inputs": [],
                            "should_rerun_review": False,
                            "intent_relation": "unknown",
                            "atomic_actions": [],
                        },
                        ensure_ascii=False,
                    )
                },
                tool_call_id="candidate-query-1",
            )
        ],
        [
            ToolReturnPart(
                tool_name="execute_plan_action",
                content=json.dumps(
                    {
                        "applied": True,
                        "action_family": "query_candidates",
                        "stage": "apply",
                        "result_kind": "candidate_snapshot",
                        "summary": "候选里命中了 5 条更稳的会计审计机会。",
                        "workspace_refresh_targets": ["candidate"],
                        "reply_focus": ["candidate_snapshot"],
                    },
                    ensure_ascii=False,
                ),
                tool_call_id="candidate-query-1",
            )
        ],
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-readonly-candidate-query", "user-1", "候选里还有没有更稳一点的会计审计，别直接加"))

    assert isinstance(reply, str)
    assert "暂时没有加入方案" in reply


def test_chat_service_creates_fix_proposal_pending_card_from_preview(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    preview_result = {
        "applied": False,
        "action_family": "preview_fix_proposal",
        "stage": "apply",
        "result_kind": "fix_proposal_preview",
        "summary": "已生成当前方案的调整预览：可确认后执行 1 项。",
        "selected_proposal_id": "fp_ready_2",
        "facts": {
            "fix_proposals": {
                "source_version_guard": 18,
                "ready_count": 1,
                "blocked_count": 0,
                "preview_only_count": 0,
                "proposals": [
                    {
                        "proposal_id": "fp_ready_1",
                        "status": "ready",
                        "title": "替换高风险志愿",
                        "summary": "当前方案里有高风险项需要替换。",
                        "strategy": "replace_risk_items",
                        "action_summaries": ["替换 2 条高风险志愿"],
                        "impact": "预计移出 2 条、补入 2 条。",
                    },
                    {
                        "proposal_id": "fp_ready_2",
                        "status": "ready",
                        "title": "补充本省保底志愿",
                        "summary": "当前本省保底数量偏少。",
                        "strategy": "fill_probability_gap",
                        "action_summaries": ["补入 2 条本省保底志愿"],
                        "impact": "预计补入 2 条。",
                    }
                ],
            }
        },
        "reply_focus": ["fix_proposal_preview", "ready_fix_proposals"],
    }
    fake_agent = _FakeAgentWithToolCalls(
        "已生成调整预览，可以确认后处理。",
        [
            ToolCallPart(
                tool_name="execute_plan_action",
                args={
                    "plan_payload": json.dumps(
                        {"stage": "apply", "action_family": "preview_fix_proposal"},
                        ensure_ascii=False,
                    )
                },
                tool_call_id="fix-proposal-preview-1",
            )
        ],
        [
            ToolReturnPart(
                tool_name="execute_plan_action",
                content=json.dumps(preview_result, ensure_ascii=False),
                tool_call_id="fix-proposal-preview-1",
            )
        ],
    )
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("fix-proposal-session", "user-1", "帮我处理方案提醒"))

    assert isinstance(reply, ChatServiceResponseEnvelope)
    card_payloads = [json.loads(item.content) for item in reply.followups if item.type == "pendingConfirmationCard"]
    assert len(card_payloads) == 1
    card_payload = card_payloads[0]
    assert card_payload["kind"] == "plan_mutation"
    assert card_payload["actionFamily"] == "apply_fix_proposal"
    assert card_payload["proposalId"] == "fp_ready_2"
    assert "补充本省保底志愿" in card_payload["content"]
    assert pending_state["value"]["actionFamily"] == "apply_fix_proposal"
    assert pending_state["value"]["executionPayload"]["toolName"] == "apply_planning_fix_proposal"
    assert pending_state["value"]["executionPayload"]["proposalId"] == "fp_ready_2"
    assert pending_state["value"]["executionPayload"]["sourceVersionGuard"] == 18


def test_chat_service_does_not_create_fix_proposal_card_for_blocked_preview(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    preview_result = {
        "applied": False,
        "action_family": "preview_fix_proposal",
        "stage": "apply",
        "result_kind": "fix_proposal_preview",
        "summary": "已生成当前方案的调整预览：暂不能自动处理 1 项。",
        "facts": {
            "fix_proposals": {
                "source_version_guard": 18,
                "ready_count": 0,
                "blocked_count": 1,
                "preview_only_count": 0,
                "proposals": [
                    {
                        "proposal_id": "fp_blocked_1",
                        "status": "blocked",
                        "title": "补齐保底志愿",
                        "summary": "当前候选不足，需要先放宽条件。",
                    }
                ],
            }
        },
    }
    fake_agent = _FakeAgentWithToolCalls(
        "当前候选不足，需要先放宽地域或专业条件。",
        [
            ToolCallPart(
                tool_name="execute_plan_action",
                args={
                    "plan_payload": json.dumps(
                        {"stage": "apply", "action_family": "preview_fix_proposal"},
                        ensure_ascii=False,
                    )
                },
                tool_call_id="fix-proposal-preview-blocked",
            )
        ],
        [
            ToolReturnPart(
                tool_name="execute_plan_action",
                content=json.dumps(preview_result, ensure_ascii=False),
                tool_call_id="fix-proposal-preview-blocked",
            )
        ],
    )
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("fix-proposal-blocked-session", "user-1", "帮我处理方案提醒"))

    assert isinstance(reply, str)
    assert "当前候选不足" in reply
    assert pending_state == {}
    save_pending_mock.assert_not_awaited()


def test_chat_service_does_not_create_fix_card_or_refresh_when_user_rejects_previous_replacement(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    preview_result = {
        "applied": True,
        "action_family": "review_plan",
        "stage": "review",
        "result_kind": "review_result",
        "summary": "当前方案有高收费提醒，可以先看替换处理方案。",
        "workspace_refresh_targets": ["ordered", "review"],
        "facts": {
            "risk_count": 0,
            "warn_count": 1,
            "fix_proposals": {
                "source_version_guard": 23,
                "ready_count": 1,
                "blocked_count": 0,
                "preview_only_count": 0,
                "proposals": [
                    {
                        "proposal_id": "fp_review_ready_1",
                        "status": "ready",
                        "title": "替换高收费志愿",
                        "summary": "当前方案里有高收费或中外合作项。",
                        "strategy": "replace_risk_items",
                        "action_summaries": ["替换 3 条预算压力较大的志愿"],
                    }
                ],
            },
        },
        "reply_focus": ["review_result", "fix_proposals"],
    }
    fake_agent = _FakeAgentWithToolCalls(
        "好的，这轮先不做替换。你可以继续查看受影响的志愿，或重新说明想保留/替换的范围。",
        [
            ToolCallPart(
                tool_name="execute_plan_action",
                args={
                    "plan_payload": json.dumps(
                        {"stage": "review", "action_family": "review_plan"},
                        ensure_ascii=False,
                    )
                },
                tool_call_id="reject-review-1",
            )
        ],
        [
            ToolReturnPart(
                tool_name="execute_plan_action",
                content=json.dumps(preview_result, ensure_ascii=False),
                tool_call_id="reject-review-1",
            )
        ],
    )
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("fix-proposal-reject-session", "user-1", "上面没有要做的替换"))

    assert isinstance(reply, str)
    assert "先不做替换" in reply
    assert pending_state == {}
    save_pending_mock.assert_not_awaited()


def test_chat_service_does_not_create_fix_proposal_card_from_actionable_review_result(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    review_result = {
        "applied": True,
        "action_family": "review_plan",
        "stage": "review",
        "result_kind": "review_result",
        "summary": "当前方案有高收费和中外合作提醒，可以先看替换处理方案。",
        "facts": {
            "risk_count": 0,
            "warn_count": 1,
            "fix_proposals": {
                "proposal_source": "review_check",
                "source_version_guard": 23,
                "ready_count": 1,
                "blocked_count": 0,
                "preview_only_count": 0,
                "proposals": [
                    {
                        "proposal_id": "fp_review_ready_1",
                        "proposal_source": "review_check",
                        "status": "ready",
                        "title": "替换高收费志愿",
                        "summary": "当前方案里有高收费或中外合作项。",
                        "strategy": "replace_risk_items",
                        "action_summaries": ["替换 3 条预算压力较大的志愿"],
                        "impact": "预计移出 3 条、补入 3 条。",
                    }
                ],
            },
        },
        "reply_focus": ["review_result", "fix_proposals"],
    }
    fake_agent = _FakeAgentWithToolCalls(
        "我已经检查了方案，预算压力大的部分可以先看处理方式。",
        [
            ToolCallPart(
                tool_name="execute_plan_action",
                args={
                    "plan_payload": json.dumps(
                        {"stage": "review", "action_family": "review_plan"},
                        ensure_ascii=False,
                    )
                },
                tool_call_id="review-with-fix-1",
            )
        ],
        [
            ToolReturnPart(
                tool_name="execute_plan_action",
                content=json.dumps(review_result, ensure_ascii=False),
                tool_call_id="review-with-fix-1",
            )
        ],
    )
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "fix-proposal-review-session",
                "user-1",
                "方案里高收费或者中外合作风险大的，先看看能怎么处理，别直接动",
            )
        )

    assert isinstance(reply, str)
    assert "预算压力" in reply
    assert pending_state == {}
    save_pending_mock.assert_not_awaited()


def test_chat_service_does_not_create_fix_proposal_card_from_adjustment_analysis_ready_proposal(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    adjustment_result = {
        "applied": True,
        "action_family": "analyze_adjustment",
        "stage": "apply",
        "result_kind": "adjustment_analysis",
        "summary": "当前方案可以先看处理预览。",
        "facts": {
            "fix_proposals": {
                "proposal_source": "review_check",
                "source_version_guard": 30,
                "ready_count": 2,
                "blocked_count": 0,
                "preview_only_count": 0,
                "proposals": [
                    {
                        "proposal_id": "fp_sort_1",
                        "proposal_source": "review_check",
                        "status": "ready",
                        "title": "修复录取率倒挂",
                        "summary": "建议检查相邻专业组顺序。",
                        "strategy": "sort_by_probability",
                        "source_check_codes": ["probability_inversion"],
                    },
                    {
                        "proposal_id": "fp_safety_1",
                        "proposal_source": "review_check",
                        "status": "ready",
                        "title": "修复组内安全垫不足",
                        "summary": "建议在对应专业组内至少保留一个录取率高于组整体录取率的专业。",
                        "strategy": "adjust_major_group_inner_safety",
                        "source_check_codes": ["group_inner_safety_guard"],
                        "action_summaries": ["补入组内安全垫专业"],
                        "add_volunteer_count": 3,
                    },
                ],
            },
        },
        "reply_focus": ["adjustment_analysis", "fix_proposals"],
    }
    fake_agent = _FakeAgentWithToolCalls(
        "我看了当前方案，专业组安全垫可以作为一个处理方向，但这轮只是分析，不会改方案。",
        [
            ToolCallPart(
                tool_name="execute_plan_action",
                args={
                    "plan_payload": json.dumps(
                        {"stage": "apply", "action_family": "analyze_adjustment"},
                        ensure_ascii=False,
                    )
                },
                tool_call_id="adjust-with-fix-1",
            )
        ],
        [
            ToolReturnPart(
                tool_name="execute_plan_action",
                content=json.dumps(adjustment_result, ensure_ascii=False),
                tool_call_id="adjust-with-fix-1",
            )
        ],
    )
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "fix-proposal-adjust-session",
                "user-1",
                "专业组里面有没有录取率太悬的？能不能补一个安全一点的专业，先给我看预览",
            )
        )

    assert isinstance(reply, str)
    assert "只是分析" in reply
    assert pending_state == {}
    save_pending_mock.assert_not_awaited()


def test_chat_service_does_not_create_fix_proposal_card_for_readonly_fix_hierarchy_explanation(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    review_result = {
        "applied": True,
        "action_family": "review_plan",
        "stage": "review",
        "result_kind": "review_result",
        "summary": "当前有提醒，可以分成需要关注和可以处理两类。",
        "facts": {
            "fix_proposals": {
                "proposal_source": "review_check",
                "source_version_guard": 31,
                "ready_count": 1,
                "blocked_count": 0,
                "preview_only_count": 0,
                "proposals": [
                    {
                        "proposal_id": "fp_sort_readonly",
                        "proposal_source": "review_check",
                        "status": "ready",
                        "title": "修复录取率倒挂",
                        "summary": "建议检查相邻专业组顺序。",
                        "strategy": "sort_by_probability",
                    }
                ],
            },
        },
        "reply_focus": ["review_result", "fix_proposals"],
    }
    fake_agent = _FakeAgentWithToolCalls(
        "我帮你分一下：有些只是提醒，有些可以处理，但这轮只是解释分类，不会改方案。",
        [
            ToolCallPart(
                tool_name="execute_plan_action",
                args={
                    "plan_payload": json.dumps(
                        {"stage": "review", "action_family": "review_plan"},
                        ensure_ascii=False,
                    )
                },
                tool_call_id="review-fix-hierarchy-1",
            )
        ],
        [
            ToolReturnPart(
                tool_name="execute_plan_action",
                content=json.dumps(review_result, ensure_ascii=False),
                tool_call_id="review-fix-hierarchy-1",
            )
        ],
    )
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "fix-proposal-readonly-hierarchy-session",
                "user-1",
                "审查里那些提醒我看不懂，你帮我分一下哪些只是看看，哪些可以自动处理",
            )
        )

    assert isinstance(reply, str)
    assert "只是解释分类" in reply
    assert pending_state == {}
    save_pending_mock.assert_not_awaited()


def test_chat_service_does_not_create_fix_proposal_card_for_plain_review_result(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    review_result = {
        "applied": True,
        "action_family": "review_plan",
        "stage": "review",
        "result_kind": "review_result",
        "summary": "当前方案有高收费提醒。",
        "facts": {
            "fix_proposals": {
                "proposal_source": "review_check",
                "source_version_guard": 23,
                "ready_count": 1,
                "proposals": [
                    {
                        "proposal_id": "fp_review_ready_1",
                        "proposal_source": "review_check",
                        "status": "ready",
                        "title": "替换高收费志愿",
                        "summary": "当前方案里有高收费或中外合作项。",
                        "strategy": "replace_risk_items",
                    }
                ],
            }
        },
    }
    fake_agent = _FakeAgentWithToolCalls(
        "我已经帮你检查了方案，当前有高收费提醒。",
        [
            ToolCallPart(
                tool_name="execute_plan_action",
                args={
                    "plan_payload": json.dumps(
                        {"stage": "review", "action_family": "review_plan"},
                        ensure_ascii=False,
                    )
                },
                tool_call_id="plain-review-1",
            )
        ],
        [
            ToolReturnPart(
                tool_name="execute_plan_action",
                content=json.dumps(review_result, ensure_ascii=False),
                tool_call_id="plain-review-1",
            )
        ],
    )
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("plain-review-session", "user-1", "帮我审查一下，先不要改"))

    assert isinstance(reply, str)
    assert "高收费提醒" in reply
    assert pending_state == {}
    save_pending_mock.assert_not_awaited()


def test_chat_service_does_not_create_fix_proposal_card_for_review_user_goal_proposal(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    review_result = {
        "applied": True,
        "action_family": "review_plan",
        "stage": "review",
        "result_kind": "review_result",
        "summary": "已生成用户目标相关的只读预览。",
        "facts": {
            "fix_proposals": {
                "proposal_source": "user_goal",
                "source_version_guard": 23,
                "ready_count": 1,
                "proposals": [
                    {
                        "proposal_id": "fp_user_goal_ready_1",
                        "proposal_source": "user_goal",
                        "status": "ready",
                        "title": "只保留临床医学",
                        "summary": "用户目标预览当前只读。",
                        "strategy": "remove_non_matching_scope",
                    }
                ],
            }
        },
    }
    fake_agent = _FakeAgentWithToolCalls(
        "我先把只保留临床医学的影响给你看清楚。",
        [
            ToolCallPart(
                tool_name="execute_plan_action",
                args={
                    "plan_payload": json.dumps(
                        {"stage": "review", "action_family": "review_plan"},
                        ensure_ascii=False,
                    )
                },
                tool_call_id="review-user-goal-1",
            )
        ],
        [
            ToolReturnPart(
                tool_name="execute_plan_action",
                content=json.dumps(review_result, ensure_ascii=False),
                tool_call_id="review-user-goal-1",
            )
        ],
    )
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("review-user-goal-session", "user-1", "先看看怎么处理，只保留临床医学"))

    assert isinstance(reply, str)
    assert "临床医学" in reply
    assert pending_state == {}
    save_pending_mock.assert_not_awaited()


def test_chat_service_semantic_plan_route_synthesizes_reply_and_creates_fix_proposal_card(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    review_history = [
        ModelRequest(parts=[UserPromptPart(content="帮我审查一下")]),
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args={
                        "plan_payload": json.dumps(
                            {"stage": "review", "action_family": "review_plan"},
                            ensure_ascii=False,
                        )
                    },
                    tool_call_id="review-before-preview",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": True,
                            "action_family": "review_plan",
                            "stage": "review",
                            "result_kind": "review_result",
                            "summary": "当前有本省保底不足提醒，可以看处理预览。",
                            "facts": {
                                "fix_proposals": {
                                    "source_version_guard": 18,
                                    "ready_count": 1,
                                    "blocked_count": 0,
                                    "preview_only_count": 0,
                                    "proposals": [
                                        {
                                            "proposal_id": "fp_fill_1",
                                            "status": "ready",
                                            "title": "补充本省保底志愿",
                                            "summary": "当前本省保底数量偏少。",
                                            "strategy": "fill_probability_gap",
                                        }
                                    ],
                                }
                            },
                            "reply_focus": ["review_result", "fix_proposals"],
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="review-before-preview",
                )
            ]
        ),
        ModelResponse(parts=[TextPart(content="当前有提醒，可以先看处理预览。")], model_name="test-model"),
    ]
    asyncio.run(store.save("semantic-fix-route-session", review_history))
    preview_result = {
        "applied": False,
        "action_family": "preview_fix_proposal",
        "stage": "apply",
        "result_kind": "fix_proposal_preview",
        "summary": "已整理当前方案的处理建议：1 项可以确认后执行；处理预览没有缩小录取率梯度断层，需要先人工取舍或放宽条件。",
        "facts": {
            "fix_proposals": {
                "source_version_guard": 18,
                "ready_count": 1,
                "blocked_count": 0,
                "preview_only_count": 0,
                "proposals": [
                    {
                        "proposal_id": "fp_fill_1",
                        "status": "ready",
                        "title": "补充本省保底志愿",
                        "summary": "当前本省保底数量偏少。",
                        "strategy": "fill_probability_gap",
                        "action_summaries": ["补入 2 条本省保底志愿"],
                        "impact": "预计补入 2 条。",
                    }
                ],
            }
        },
        "reply_focus": ["fix_proposal_preview", "ready_fix_proposals"],
    }
    fake_agent = _FakeAgent(["不应该进入完整 Agent"])
    synthesis_usage = MagicMock(
        input_tokens=10,
        output_tokens=8,
        total_tokens=18,
        requests=1,
        tool_calls=0,
    )
    synthesized_reply = "我已把可以执行的补充方案列出来了：这次重点是补 2 条本省保底志愿，确认前不会改动当前方案。"
    pending_state, save_pending_mock, get_pending_mock = _pending_confirmation_store()

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={
                "code": 0,
                "data": {
                    "phase": "reviewed",
                    "version": 18,
                    "draftPlanState": {"summary": {"total": 30}},
                    "orderedPlanState": {"summary": {"total": 30}},
                    "reviewState": {"summary": {"warnCount": 1, "riskCount": 0}, "checks": []},
                },
            })), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.classify_plan_semantic_action", AsyncMock(return_value=_semantic_plan("preview_fix_proposal"))), \
            patch("app.service.execute_plan_action", AsyncMock(return_value=json.dumps(preview_result, ensure_ascii=False))) as execute_mock, \
            patch("app.service._synthesize_semantic_plan_action_reply", AsyncMock(return_value=(synthesized_reply, synthesis_usage))) as synthesize_mock, \
            patch("app.service.save_pending_confirmation", save_pending_mock), \
            patch("app.service.get_pending_confirmation", get_pending_mock):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "semantic-fix-route-session",
                "user-1",
                "专业组里面有没有录取率太悬的？能不能补一个安全一点的专业，先给我看预览",
            )
        )

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert reply.primary == synthesized_reply
    assert "人工取舍" not in reply.primary
    assert "放宽条件" not in reply.primary
    assert "处理预览没有" not in reply.primary
    assert "blocked" not in reply.primary
    assert "preview_only" not in reply.primary
    card_payloads = [json.loads(item.content) for item in reply.followups if item.type == "pendingConfirmationCard"]
    assert len(card_payloads) == 1
    assert card_payloads[0]["actionFamily"] == "apply_fix_proposal"
    assert card_payloads[0]["proposalId"] == "fp_fill_1"
    assert pending_state["value"]["executionPayload"]["proposalId"] == "fp_fill_1"
    assert fake_agent.calls == []
    synthesize_mock.assert_awaited_once()
    execute_mock.assert_awaited_once()
    payload = json.loads(execute_mock.await_args.args[1])
    assert payload["action_family"] == "preview_fix_proposal"


def test_chat_service_semantic_plan_route_low_confidence_falls_back_to_agent(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    history = [
        ModelRequest(parts=[UserPromptPart(content="帮我审查一下")]),
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args={"plan_payload": json.dumps({"stage": "review", "action_family": "review_plan"})},
                    tool_call_id="review-low-confidence",
                )
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=json.dumps(
                        {
                            "applied": True,
                            "action_family": "review_plan",
                            "stage": "review",
                            "result_kind": "review_result",
                            "summary": "当前有提醒。",
                            "facts": {"fix_proposals": {"ready_count": 1, "proposals": [{"proposal_id": "fp_1", "status": "ready"}]}},
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="review-low-confidence",
                )
            ]
        ),
        ModelResponse(parts=[TextPart(content="当前有提醒。")], model_name="test-model"),
    ]
    asyncio.run(store.save("semantic-low-confidence-session", history))
    fake_agent = _FakeAgent(["我继续帮你分析，不会直接改方案。"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={
                "code": 0,
                "data": {
                    "phase": "reviewed",
                    "version": 18,
                    "draftPlanState": {"summary": {"total": 30}},
                    "orderedPlanState": {"summary": {"total": 30}},
                    "reviewState": {"summary": {"warnCount": 1, "riskCount": 0}, "checks": []},
                },
            })), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.classify_plan_semantic_action", AsyncMock(return_value=_semantic_plan("preview_fix_proposal", confidence=0.3))), \
            patch("app.service.execute_plan_action", AsyncMock()) as execute_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("semantic-low-confidence-session", "user-1", "这个怎么看"))

    assert reply == "我继续帮你分析，不会直接改方案。"
    assert len(fake_agent.calls) == 1
    execute_mock.assert_not_awaited()


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
    assert "已按处理建议更新方案" in reply.primary
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


def test_chat_service_readonly_prompt_strips_mutating_preview_and_pending_state(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    plan_payload = {
        "stage": "preview",
        "action_family": "add_units",
        "user_goal": "候选里还有没有更稳一点的会计审计，别直接加",
        "context_summary": "阶段=ordered；方案=45/45",
        "preview_summary": "会补入 3 个更稳的会计审计候选，并同步刷新当前方案和审查结果。",
        "missing_inputs": [],
        "should_rerun_review": True,
        "intent_relation": "support",
        "atomic_actions": [
            {
                "action_type": "add_units",
                "volunteer_ids": ["v-1", "v-2", "v-3"],
                "filters": {"tier": "稳", "major_keyword": "会计 审计"},
                "reason": "候选里还有没有更稳一点的会计审计，别直接加",
            }
        ],
    }
    fake_agent = _FakeAgentWithToolCalls(
        "调整预览已生成。会补入 3 个更稳的会计审计候选。确认后执行。",
        [
            ToolCallPart(
                tool_name="execute_plan_action",
                args={"plan_payload": json.dumps(plan_payload, ensure_ascii=False)},
                tool_call_id="readonly-add-preview-1",
            )
        ],
        [
            ToolReturnPart(
                tool_name="execute_plan_action",
                content=json.dumps(
                    {
                        "applied": False,
                        "action_family": "add_units",
                        "stage": "preview",
                        "result_kind": "preview_only",
                        "summary": "会补入 3 个更稳的会计审计候选。",
                        "workspace_refresh_targets": ["ordered", "candidate"],
                        "reply_focus": ["preview_only", "confirmation_required"],
                    },
                    ensure_ascii=False,
                ),
                tool_call_id="readonly-add-preview-1",
            )
        ],
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_message(
                "session-readonly-add-preview",
                "user-1",
                "候选里还有没有更稳一点的会计审计，别直接加",
            )
        )

    assert isinstance(reply, str)
    assert "不会加入、删除、移动或重排方案" in reply
    assert "确认后执行" not in reply
    saved = asyncio.run(store.load("session-readonly-add-preview"))
    assert _extract_pending_plan_action(saved) is None
    saved_text = json.dumps([pydantic_part.content for message in saved for pydantic_part in getattr(message, "parts", []) if hasattr(pydantic_part, "content")], ensure_ascii=False)
    assert "preview_only" not in saved_text


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
