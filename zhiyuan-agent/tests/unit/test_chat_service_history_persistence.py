"""Tests for ChatService persistence and model-first dialog entry."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart

from app.data.history_store import ChatHistoryStore
from app.schemas.ws import WSResponse
from app.service import (
    ChatService,
    ChatServiceResponseEnvelope,
    _append_plan_preview_confirmation_boundary,
    _build_plan_timeout_fallback_reply,
    _extract_pending_plan_action,
    _normalize_pending_intent_reply,
    _normalize_plan_reply_style,
    _normalize_user_facing_terms,
    _select_conversation_action_family,
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


class _FakeAgent:
    def __init__(self, replies: list[str | WSResponse]):
        self.calls: list[dict] = []
        self._replies = replies

    async def run_with_message_deltas(self, user_prompt, message_history=None, deps=None, on_progress=None):
        self.calls.append(
            {
                "user_prompt": user_prompt,
                "message_history": message_history,
                "chat_history": deps.chat_history if deps else None,
                "planning_summary": deps.planning_summary if deps else None,
                "pending_plan_action": deps.pending_plan_action if deps else None,
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


@pytest.fixture
def mock_llm_client():
    client = MagicMock()
    client.model = MagicMock()
    client.model_settings = {}
    return client


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
        assert len(restored_after_first) == 2

        service2 = ChatService(mock_llm_client, store)
        service2.agent = fake_agent
        reply2 = asyncio.run(service2.handle_message("session-1", "user-1", "继续"))

        assert reply2 == "第二轮回复"
        assert fake_agent.calls[0]["message_history"] is None
        assert fake_agent.calls[0]["chat_history"] == [{"role": "user", "content": "你好"}]
        assert fake_agent.calls[0]["planning_summary"] is not None
        assert fake_agent.calls[0]["planning_summary"].phase == "reviewed"
        assert fake_agent.calls[1]["message_history"] is not None
        assert len(fake_agent.calls[1]["message_history"]) == 2
        assert fake_agent.calls[1]["chat_history"] == [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "第一轮回复"},
            {"role": "user", "content": "继续"},
        ]


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


def test_extract_pending_plan_action_maps_compensation_preview_to_apply_payload():
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
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="compensation-preview-call",
                )
            ]
        ),
    ]

    pending = _extract_pending_plan_action(messages)

    assert pending is not None
    assert pending["action_family"] == "apply_compensation"
    assert pending["summary"] == "当前可先看的补齐建议共有 1 项动作，预计补入 2 个志愿。"
    apply_payload = json.loads(pending["plan_payload"])
    assert apply_payload["action_family"] == "apply_compensation"
    assert apply_payload["stage"] == "apply"
    assert apply_payload["should_rerun_review"] is True


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
                "filters": {},
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
                "filters": {},
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


def test_chat_service_directly_applies_pending_compensation_on_confirm(tmp_path, mock_llm_client):
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
    fake_agent = _FakeAgent(["不应该调用模型"])
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

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert reply.primary == "系统已完成当前可安全补齐的志愿补入。"
    assert [json.loads(item.content)["targetView"] for item in reply.followups] == ["ordered"]
    execute_mock.assert_awaited_once()
    applied_payload = json.loads(execute_mock.await_args.args[1])
    assert applied_payload["action_family"] == "apply_compensation"
    assert fake_agent.calls == []


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

    fake_agent = _FakeAgent(["不应该调用模型"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.execute_plan_action", AsyncMock()) as execute_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-compensation-empty-confirm", "user-1", "确认"))

    assert reply == "我这边没有上一轮待确认的方案动作。你可以直接说想生成方案、审查方案或怎么调整，我会先说明影响，确认后再执行。"
    execute_mock.assert_not_awaited()
    assert fake_agent.calls == []


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

    assert "不会因为你回复“确认”就直接改方案" in bounded
    assert "还没有拿到可执行的调整预览" in bounded


def test_chat_service_directly_applies_pending_replace_on_confirm(tmp_path, mock_llm_client):
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
    fake_agent = _FakeAgent(["不应该调用模型"])
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

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert reply.primary == "已替换广西师范大学006专业组-生物科学，并补入新的保底志愿。"
    assert [json.loads(item.content)["targetView"] for item in reply.followups] == ["ordered"]
    execute_mock.assert_awaited_once()
    applied_payload = json.loads(execute_mock.await_args.args[1])
    assert applied_payload["action_family"] == "replace_units"
    assert applied_payload["stage"] == "apply"
    assert fake_agent.calls == []


def test_chat_service_directly_applies_pending_replace_on_confirm_even_with_stale_intent_cache(tmp_path, mock_llm_client):
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
    fake_agent = _FakeAgent(["不应该调用模型"])
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

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert reply.primary == "已替换广西师范大学006专业组-生物科学，并补入新的保底志愿。"
    assert [json.loads(item.content)["targetView"] for item in reply.followups] == ["ordered"]
    execute_mock.assert_awaited_once()
    assert fake_agent.calls == []


def test_chat_service_directly_applies_pending_intent_on_short_confirm(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    asyncio.run(store.save("session-intent-direct-confirm", []))
    fake_agent = _FakeAgent(["不应该调用模型"])
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
            patch("app.service.update_volunteer_intent_state", AsyncMock(return_value=intent_result)) as update_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-intent-direct-confirm", "user-1", "确认"))

    assert reply == "好的，我记下来了。接下来如果你愿意，我可以继续帮你看看现在这份方案哪些地方比较贴近你的想法、哪些地方还可以再优化。"
    update_mock.assert_awaited_once()
    assert update_mock.await_args.kwargs["action"] == "confirm"
    assert fake_agent.calls == []


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

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert reply.primary == "我先把这个偏好整理成待确认参考，你确认后我再正式生效。"
    assert "还没有拿到可执行的调整预览" not in reply.primary


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
            patch("app.service.update_volunteer_intent_state", AsyncMock()) as update_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-intent-direct-confirm-2", "user-1", "确认生成"))

    assert reply == "模型继续处理"
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


def test_extract_pending_plan_action_clears_after_intervening_user_turn():
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
        ModelRequest(parts=[UserPromptPart(content="先不用，帮我看看哪里不合理")]),
        ModelResponse(parts=[TextPart(content="当前还没有正式方案。")], model_name="test-model"),
    ]

    assert _extract_pending_plan_action(messages) is None


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


def test_plan_preview_confirmation_boundary_replaces_false_compensation_failure_with_pending_preview():
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

    assert "补齐建议预览已生成" in bounded
    assert "预计补入 2 个志愿" in bounded
    assert "如果你确认要应用" in bounded
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


def test_chat_service_injects_pending_plan_action_from_history_for_non_confirm_turn(tmp_path, mock_llm_client):
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
    pending = fake_agent.calls[0]["pending_plan_action"]
    assert pending["action_family"] == "regenerate_order"
    assert json.loads(pending["plan_payload"])["stage"] == "apply"


def test_chat_service_directly_applies_pending_regenerate_order_on_confirm(tmp_path, mock_llm_client):
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
    execution_result = json.dumps(
        {
            "applied": True,
            "action_family": "regenerate_order",
            "stage": "apply",
            "result_kind": "mutation_result",
            "summary": "已完成重排并复审。",
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
        reply = asyncio.run(service.handle_message("session-pending-plan-direct", "user-1", "确认"))

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert reply.primary == "已完成重排并复审。"
    targets = [json.loads(item.content)["targetView"] for item in reply.followups]
    assert targets == ["ordered"]
    execute_mock.assert_awaited_once()
    assert fake_agent.calls == []
    saved_history = asyncio.run(store.load("session-pending-plan-direct"))
    assert saved_history is not None
    assert any(
        isinstance(part, TextPart) and part.content == reply.primary
        for message in saved_history
        for part in getattr(message, "parts", [])
    )


def test_chat_service_blocks_plan_confirmation_without_pending_action(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgent(["不应该调用模型"])

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-no-pending-confirm", "user-1", "确认"))

    assert reply == "我这边没有上一轮待确认的方案动作。你可以直接说想生成方案、审查方案或怎么调整，我会先说明影响，确认后再执行。"
    assert fake_agent.calls == []
    saved_history = asyncio.run(store.load("session-no-pending-confirm"))
    assert saved_history is not None
    assert len(saved_history) == 2


def test_chat_service_does_not_block_intent_confirmation_when_intent_cache_exists(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgent(["不应该调用模型"])
    intent_result = json.dumps(
        {
            "action": "confirm",
            "sessionId": "session-intent-pending-confirm",
            "intentMode": "preference",
            "applied": True,
            "messageCode": "preference_applied",
            "message": "已按你的确认更新偏好。",
        },
        ensure_ascii=False,
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch(
                "app.service.get_intent_change_cache",
                AsyncMock(return_value={"code": 0, "data": {"planEditCache": {"career_intents": {"positive": ["stable_employment"]}}}}),
            ) as intent_cache_mock, \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.update_volunteer_intent_state", AsyncMock(return_value=intent_result)) as update_mock:
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-intent-pending-confirm", "user-1", "确认"))

    assert reply == "已按你的确认更新偏好。"
    update_mock.assert_awaited_once()
    assert fake_agent.calls == []
    intent_cache_mock.assert_awaited_once()


def test_chat_service_directly_applies_plan_next_action_pending_confirmation(tmp_path, mock_llm_client):
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
    execution_result = json.dumps(
        {
            "applied": True,
            "action_family": "regenerate_order",
            "stage": "apply",
            "result_kind": "mutation_result",
            "summary": "已完成重排并复审。",
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
        reply = asyncio.run(service.handle_message("session-pending-plan-next-direct", "user-1", "确认"))

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert reply.primary == "已完成重排并复审。"
    execute_mock.assert_awaited_once()
    assert fake_agent.calls == []


def test_chat_service_appends_workspace_refresh_after_execute_plan_action_review(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    fake_agent = _FakeAgentWithToolCalls(
        "已完成当前方案审查。",
        [
            ToolCallPart(
                tool_name="execute_plan_action",
                args={"plan_payload": json.dumps({"stage": "review", "action_family": "review_plan"}, ensure_ascii=False)},
            )
        ],
    )

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(service.handle_message("session-plan-review-new", "user-1", "帮我审查一下"))

    assert reply == "已完成当前方案审查。"


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
    targets = [json.loads(item.content)["targetView"] for item in reply.followups]
    assert targets == ["ordered"]


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

    assert reply == "我先帮你规划一版基础方案。\n\n如果你确认要这样做，我再执行；现在还不会改动方案。"
    saved_history = asyncio.run(store.load("session-plan-next-preview-boundary"))
    assert saved_history is not None
    saved_text = next(part.content for part in saved_history[-1].parts if isinstance(part, TextPart))
    assert saved_text == reply


def test_chat_service_confirms_plan_next_action_preview_without_execute(tmp_path, mock_llm_client):
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

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})), \
            patch("app.service.execute_plan_action", AsyncMock(return_value=execution_result)) as execute_mock:
        service = ChatService(mock_llm_client, store)
        preview_reply = asyncio.run(service.handle_message("session-plan-next-sort-preview", "user-1", "按院校层次排序"))
        confirm_reply = asyncio.run(service.handle_message("session-plan-next-sort-preview", "user-1", "确认"))

    assert preview_reply == "会按院校层次重新排序当前方案。\n\n如果你确认要这样做，我再执行；现在还不会改动方案。"
    assert isinstance(confirm_reply, ChatServiceResponseEnvelope)
    assert confirm_reply.primary == "已按院校层次重新排序当前方案。"
    assert len(fake_agent.calls) == 1
    execute_mock.assert_awaited_once()
    payload = json.loads(execute_mock.await_args.args[1])
    assert payload["stage"] == "apply"
    assert payload["action_family"] == "sort_ordered_plan"
    assert payload["should_rerun_review"] is True


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
    assert "选哪个" in normalized
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
    fake_agent = _FakeAgent(["这会整体更新当前排序结果，建议先确认。", "不应该调用模型"])

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
    assert second_reply == "我这边没有上一轮待确认的方案动作。你可以直接说想生成方案、审查方案或怎么调整，我会先说明影响，确认后再执行。"


def test_normalize_user_facing_terms_removes_profile_jargon():
    reply = '你是想把"网络与新媒体"作为新的专业意向加入画像，还是想先看看当前方案？'

    normalized = _normalize_user_facing_terms(reply)

    assert "画像" not in normalized
    assert "记成后续报考参考" in normalized


def test_normalize_pending_intent_reply_avoids_premature_recorded_wording():
    reply = "好的，我记下了你对跨境电商的兴趣。候选库里有一个相关机会。"

    normalized = _normalize_pending_intent_reply(reply)

    assert "我记下了" not in normalized
    assert "确认" in normalized
    assert "后续参考" in normalized


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

    assert isinstance(reply, ChatServiceResponseEnvelope)
    primary = reply.primary
    assert "我记下了" not in primary
    assert "确认" in primary
    assert "后续参考" in primary
    assert reply.followups
    saved_history = asyncio.run(store.load("session-intent-preview-style"))
    saved_text = next(part.content for part in saved_history[-1].parts if isinstance(part, TextPart))
    assert saved_text == primary


def test_chat_service_appends_candidate_workspace_refresh_after_intent_preview_tool(tmp_path, mock_llm_client):
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

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert reply.primary == "我先把你不想学审计这件事整理成待确认要求。"
    assert len(reply.followups) == 1
    followup = reply.followups[0]
    assert followup.type == "planningWorkspaceAction"
    payload = json.loads(followup.content)
    assert payload["targetView"] == "candidate"
    assert payload["refresh"] is True
    assert payload["title"] == "查看候选库关联结果"
    assert payload["actionText"] == "打开候选库"


def test_chat_service_direct_confirm_workspace_actions_have_clear_copy(tmp_path, mock_llm_client):
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

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert "录取率梯度是否达标：否" in reply.primary
    assert "当前排序存在录取概率倒挂" in reply.primary
    execute_mock.assert_awaited_once()
    assert fake_agent.calls == []
    payloads = [json.loads(item.content) for item in reply.followups]
    assert [payload["title"] for payload in payloads] == ["查看调整后的排序方案"]
    assert [payload["actionText"] for payload in payloads] == ["打开排序方案"]


def test_chat_service_dialog_replace_preview_confirm_resolves_display_refs_before_apply(tmp_path, mock_llm_client):
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

    with patch("app.service.ChatAgent", return_value=fake_agent), \
            patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
            patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})), \
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
            patch("app.tools.plan_execution_tool.run_planning_review", AsyncMock(return_value="复审完成")):
        service = ChatService(mock_llm_client, store)
        preview_reply = asyncio.run(service.handle_message("session-dialog-57-replay", "user-57", "调整下"))
        confirm_reply = asyncio.run(service.handle_message("session-dialog-57-replay", "user-57", "确认"))

    assert preview_reply == "我先给你看替换预览，确认后再执行。"
    assert isinstance(confirm_reply, ChatServiceResponseEnvelope)
    assert "已移出旧志愿" in confirm_reply.primary
    assert "已补入新候选" in confirm_reply.primary
    assert "复审完成" in confirm_reply.primary
    assert [json.loads(item.content)["targetView"] for item in confirm_reply.followups] == ["ordered"]
    remove_mock.assert_awaited_once()
    add_mock.assert_awaited_once()
    assert fake_agent.calls[0] == {"user_prompt": "调整下", "pending_plan_action": None}
    assert len(fake_agent.calls) == 1


def test_chat_service_handle_intent_select_constraint_end_to_end_returns_workspace_action(tmp_path, mock_llm_client):
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

    with patch("app.service.ChatAgent"), \
            patch(
                "app.service.get_user_score_detail",
                AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}}),
            ), \
            patch(
                "app.tools.intent_state_tool.get_message_by_id",
                new=AsyncMock(return_value={"data": {"content": json.dumps(message_content, ensure_ascii=False)}}),
            ), \
            patch("app.tools.intent_state_tool.update_message", new=AsyncMock()), \
            patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()), \
            patch(
                "app.tools.intent_state_tool.query_planning_candidate_pool",
                new=AsyncMock(return_value={"data": {"total": 88}}),
            ), \
            patch(
                "app.tools.intent_state_tool.get_planning_state",
                new=AsyncMock(return_value={"data": {"candidatePoolState": {"summary": {"total": 3200}}}}),
            ), \
            patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls:
        mock_pm = mock_pm_cls.return_value
        mock_pm.update_city_intent = AsyncMock()
        mock_pm.update_major_intent = AsyncMock()
        mock_pm.update_school_intent = AsyncMock()

        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_intent_select(
                "31",
                "user-31",
                json.dumps(selected_payload, ensure_ascii=False),
            )
        )

    assert isinstance(reply, WSResponse)
    assert reply.type == "planningWorkspaceAction"
    payload = json.loads(reply.content)
    assert payload["targetView"] == "candidate"
    assert payload["refresh"] is True
    assert payload["candidateFilters"]["negativeProvinceNames"] == ["北京"]


def test_chat_service_handle_intent_select_uses_structured_candidate_filters(tmp_path, mock_llm_client):
    db_path = tmp_path / "history.db"
    store = ChatHistoryStore(str(db_path))
    selected_payload = {
        "message_id": 2003,
        "selected": [{"city_intents": {"province": ["北京"]}}],
    }
    structured_result = {
        "action": "apply_selected",
        "sessionId": "33",
        "intentMode": "constraint",
        "applied": True,
        "messageCode": "custom_constraint_code_without_text_coupling",
        "message": "结构化执行成功",
        "merged": {"city_intents": {"province": ["北京"]}},
        "candidateFilters": {"provinceNames": ["北京"]},
    }

    with patch("app.service.ChatAgent"), \
            patch(
                "app.service.get_user_score_detail",
                AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}}),
            ), \
            patch(
                "app.service._apply_selected_intents",
                new=AsyncMock(return_value=json.dumps(structured_result, ensure_ascii=False)),
            ):
        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_intent_select(
                "33",
                "user-33",
                json.dumps(selected_payload, ensure_ascii=False),
            )
        )

    assert isinstance(reply, WSResponse)
    assert reply.type == "planningWorkspaceAction"
    payload = json.loads(reply.content)
    assert payload["targetView"] == "candidate"
    assert payload["candidateFilters"] == {"provinceNames": ["北京"]}


def test_chat_service_handle_intent_select_preference_end_to_end_returns_analysis_text(tmp_path, mock_llm_client):
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

    with patch("app.service.ChatAgent"), \
            patch(
                "app.service.get_user_score_detail",
                AsyncMock(return_value={"code": 0, "data": {"userScoreDetail": {"batch": "01"}}}),
            ), \
            patch(
                "app.tools.intent_state_tool.get_message_by_id",
                new=AsyncMock(return_value={"data": {"content": json.dumps(message_content, ensure_ascii=False)}}),
            ), \
            patch("app.tools.intent_state_tool.update_message", new=AsyncMock()), \
            patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()), \
            patch("app.tools.intent_state_tool.query_planning_candidate_pool", new=AsyncMock()) as query_mock, \
            patch("app.tools.intent_state_tool.get_planning_state", new=AsyncMock()) as state_mock, \
            patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls:
        mock_pm = mock_pm_cls.return_value
        mock_pm.update_city_intent = AsyncMock()
        mock_pm.update_major_intent = AsyncMock()
        mock_pm.update_school_intent = AsyncMock()

        service = ChatService(mock_llm_client, store)
        reply = asyncio.run(
            service.handle_intent_select(
                "32",
                "user-32",
                json.dumps(selected_payload, ensure_ascii=False),
            )
        )

    assert isinstance(reply, str)
    assert "记下来了" in reply
    query_mock.assert_not_awaited()
    state_mock.assert_not_awaited()


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
