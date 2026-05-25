"""Tests for the agent-plus compatible WebSocket endpoint."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart

from app.data.history_store import ChatHistoryStore
from app.schemas.ws import WSResponse
from app.service import ChatService, ChatServiceResponseEnvelope, _build_plan_timeout_fallback_reply
from app.tools.plan_execution_tool import execute_plan_action

_patches = []


def _start_patches():
    p1 = patch("app.server.LLMClient")
    p2 = patch("app.server.ChatHistoryStore")
    p3 = patch("app.server.configure_logfire")
    p4 = patch("app.server.HistoryConfig", return_value=MagicMock(db_path=":memory:"))
    mocks = [p.start() for p in (p1, p2, p3, p4)]
    _patches.extend([p1, p2, p3, p4])
    return mocks


def _stop_patches():
    for p in _patches:
        p.stop()
    _patches.clear()


@pytest.fixture(autouse=True)
def _patch_infra():
    _start_patches()
    yield
    _stop_patches()


@pytest.fixture()
def client():
    from app.server import app
    return TestClient(app)


WS_PATH = "/gaotu-assistant-agent/plus/chat/test-tenant/bot/test-bot/do"


class _ClosedJsonWebSocket:
    async def send_json(self, data):
        raise RuntimeError('Cannot call "send" once a close message has been sent.')


class _UnexpectedJsonWebSocket:
    async def send_json(self, data):
        raise RuntimeError("unexpected websocket failure")


class _PlanStatusToolAgent:
    def __init__(self):
        self.calls: list[dict] = []
        self.tool_results: list[dict] = []

    async def run_with_message_deltas(self, user_prompt, message_history=None, deps=None, on_progress=None):
        self.calls.append({"user_prompt": user_prompt, "session_id": deps.sessionid if deps else None})
        plan_payload = json.dumps(
            {
                "stage": "apply",
                "action_family": "query_state",
                "user_goal": user_prompt,
                "requires_confirmation": False,
                "context_summary": "用户通过快捷回复查看当前方案状态。",
                "intent_relation": "mixed",
            },
            ensure_ascii=False,
        )
        tool_result_text = await execute_plan_action(SimpleNamespace(deps=deps), plan_payload)
        tool_result = json.loads(tool_result_text)
        self.tool_results.append(tool_result)

        reply = _build_plan_timeout_fallback_reply(tool_result) or tool_result.get("summary") or ""
        new_messages = [
            ModelRequest(parts=[UserPromptPart(content=user_prompt)]),
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="execute_plan_action",
                        args={"plan_payload": plan_payload},
                        tool_call_id="query-state-status-1",
                    )
                ],
                model_name="test-model",
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="execute_plan_action",
                        content=tool_result_text,
                        tool_call_id="query-state-status-1",
                    )
                ]
            ),
            ModelResponse(parts=[TextPart(content=reply)], model_name="test-model"),
        ]
        usage = MagicMock(input_tokens=1, output_tokens=1, total_tokens=2, requests=1, tool_calls=1)
        return reply, new_messages, list(message_history or []) + new_messages, usage


def _planning_state_for_status_overview() -> dict:
    return {
        "phase": "reviewed",
        "version": 7,
        "candidatePoolState": {"requiredCount": 45},
        "draftPlanState": {"summary": {"total": 45, "targetCount": 45}},
        "orderedPlanState": {
            "summary": {
                "total": 45,
                "targetCount": 45,
                "unitTierCounts": {"冲": 18, "稳": 13, "保": 14},
            }
        },
        "reviewState": {
            "status": "completed",
            "summary": {"riskCount": 0, "warnCount": 0, "passedCount": 8},
            "checks": [],
        },
        "profileState": {
            "explicitProfile": {
                "positiveMajors": ["财政学类", "经济学类", "法学类"],
                "negativeMajors": ["中西医结合类", "护理学类"],
                "positiveRegions": ["北京", "天津"],
            },
            "latentProfile": {
                "futureDevelopment": {"careerTypes": []},
            },
        },
    }


def _ordered_plan_for_status_overview() -> dict:
    return {
        "summary": {
            "total": 45,
            "targetCount": 45,
            "unitTierCounts": {"冲": 18, "稳": 13, "保": 14},
        },
        "items": [
            {
                "schoolName": "北京财经学院",
                "majorName": "财政学",
                "majorCategory": "财政学类",
                "provinceName": "北京",
                "tier": "冲",
                "position": 1,
                "volunteerId": "v1",
            },
            {
                "schoolName": "天津财经大学",
                "majorName": "经济学",
                "majorCategory": "经济学类",
                "provinceName": "天津",
                "tier": "稳",
                "position": 2,
                "volunteerId": "v2",
            },
            {
                "schoolName": "河北经贸大学",
                "majorName": "法学",
                "majorCategory": "法学类",
                "provinceName": "河北",
                "tier": "保",
                "position": 3,
                "volunteerId": "v3",
            },
        ],
    }


def test_safe_send_json_returns_false_when_connection_already_closed(client):
    from app.server import _safe_send_json

    result = asyncio.run(_safe_send_json(_ClosedJsonWebSocket(), {"type": "text"}, context="test.closed"))

    assert result is False


def test_safe_send_json_reraises_unexpected_runtime_error(client):
    from app.server import _safe_send_json

    with pytest.raises(RuntimeError, match="unexpected websocket failure"):
        asyncio.run(_safe_send_json(_UnexpectedJsonWebSocket(), {"type": "text"}, context="test.unexpected"))


def test_ping_pong(client):
    client.app.state.chat_service = AsyncMock()
    with client.websocket_connect(WS_PATH) as ws:
        ws.send_json({"inputType": "ping", "timestamp": 12345})
        resp = ws.receive_json()
        assert resp["type"] == "pong"
        assert resp["timestamp"] == 12345


def test_text_message_returns_plus_format(client):
    mock_service = AsyncMock()
    mock_service.handle_message = AsyncMock(return_value="你好，我是AI助手")
    mock_service.handle_intent_select = AsyncMock()
    client.app.state.chat_service = mock_service

    with client.websocket_connect(WS_PATH) as ws:
        with patch("app.server.message_store") as mock_store:
            mock_store.save_user_message = AsyncMock(return_value=1)
            mock_store.save_agent_message = AsyncMock(return_value=2)

            ws.send_json({
                "sessionId": "sess-001",
                "userId": "user-001",
                "content": "你好",
                "inputType": "text",
            })
            resp = ws.receive_json()

    assert resp["type"] == "text"
    assert resp["content"] == "你好，我是AI助手"
    assert resp["end"] is True
    mock_service.handle_message.assert_awaited_once()


def test_intent_select_input_serializes_content(client):
    mock_service = AsyncMock()
    mock_service.handle_message = AsyncMock()
    mock_service.handle_intent_select = AsyncMock(return_value="已更新方案")
    client.app.state.chat_service = mock_service

    with client.websocket_connect(WS_PATH) as ws:
        with patch("app.server.message_store") as mock_store:
            mock_store.save_user_message = AsyncMock(return_value=1)
            mock_store.save_agent_message = AsyncMock(return_value=2)

            content_obj = {
                "action": "采纳",
                "message_id": 999,
                "selected": [{"major_intent": {"level3": ["计算机"]}}],
            }
            ws.send_json({
                "sessionId": "sess-002",
                "userId": "user-002",
                "content": content_obj,
                "inputType": "intentSelect",
            })
            resp = ws.receive_json()

    assert resp["type"] == "text"
    assert resp["content"] == "已更新方案"
    call_kwargs = mock_service.handle_intent_select.call_args.kwargs
    parsed = json.loads(call_kwargs["content"])
    assert parsed["message_id"] == 999
    mock_service.handle_message.assert_not_awaited()


def test_popup_response_has_message_id_and_object_content(client):
    popup_data = {
        "title": "报考意向调整确认",
        "items": [{"content": "新增物理", "value": {"major_intents": {}}, "selected": True}],
        "existing_items": [],
        "clickable": True,
        "clicked": False,
    }
    ws_resp = WSResponse(
        type="intentConfirmPopup",
        session_id="sess-003",
        content=json.dumps(popup_data, ensure_ascii=False),
    )

    mock_service = AsyncMock()
    mock_service.handle_message = AsyncMock(return_value=ws_resp)
    mock_service.handle_intent_select = AsyncMock()
    client.app.state.chat_service = mock_service

    with client.websocket_connect(WS_PATH) as ws:
        with patch("app.server.message_store") as mock_store:
            mock_store.save_user_message = AsyncMock(return_value=1)
            mock_store.save_agent_message = AsyncMock(return_value=777)

            ws.send_json({
                "sessionId": "sess-003",
                "userId": "user-003",
                "content": "我想学计算机",
                "inputType": "text",
            })
            resp = ws.receive_json()

    assert resp["type"] == "intentConfirmPopup"
    assert resp["content"]["message_id"] == 777
    assert resp["content"]["title"] == "报考意向调整确认"


def test_interest_analysis_popup_returns_object_content(client):
    popup_data = {
        "title": "我先帮你看一眼",
        "impact": "先结合当前情况做分析。",
        "analysisStage": "interest",
        "actions": [
            {"label": "先看看候选里有没有", "message": "先看看候选里有没有", "actionType": "candidate_query"},
        ],
        "clickable": False,
        "clicked": False,
    }
    ws_resp = WSResponse(
        type="interestAnalysisPopup",
        session_id="sess-interest",
        content=json.dumps(popup_data, ensure_ascii=False),
    )

    mock_service = AsyncMock()
    mock_service.handle_message = AsyncMock(return_value=ws_resp)
    mock_service.handle_intent_select = AsyncMock()
    client.app.state.chat_service = mock_service

    with client.websocket_connect(WS_PATH) as ws:
        with patch("app.server.message_store") as mock_store:
            mock_store.save_user_message = AsyncMock(return_value=1)
            mock_store.save_agent_message = AsyncMock(return_value=779)

            ws.send_json({
                "sessionId": "sess-interest",
                "userId": "user-interest",
                "content": "体制内适合我吗",
                "inputType": "text",
            })
            resp = ws.receive_json()

    assert resp["type"] == "interestAnalysisPopup"
    assert resp["content"]["message_id"] == 779
    assert resp["content"]["analysisStage"] == "interest"


def test_workspace_action_response_returns_object_content(client):
    action_data = {
        "type": "planningWorkspaceAction",
        "title": "意向已更新",
        "content": "可直接查看右侧草稿区。",
        "targetView": "draft",
        "actionText": "查看草稿区",
        "refresh": True,
    }
    ws_resp = WSResponse(
        type="planningWorkspaceAction",
        session_id="sess-003a",
        content=json.dumps(action_data, ensure_ascii=False),
    )

    mock_service = AsyncMock()
    mock_service.handle_message = AsyncMock(return_value=ws_resp)
    mock_service.handle_intent_select = AsyncMock()
    client.app.state.chat_service = mock_service

    with client.websocket_connect(WS_PATH) as ws:
        with patch("app.server.message_store") as mock_store:
            mock_store.save_user_message = AsyncMock(return_value=1)
            mock_store.save_agent_message = AsyncMock(return_value=778)

            ws.send_json({
                "sessionId": "sess-003a",
                "userId": "user-003a",
                "content": "看看候选",
                "inputType": "text",
            })
            resp = ws.receive_json()

    assert resp["type"] == "planningWorkspaceAction"
    assert resp["content"]["targetView"] == "draft"


def test_ws_compat_sends_multiple_workspace_followups(client):
    mock_service = AsyncMock()
    mock_service.handle_message = AsyncMock(return_value=ChatServiceResponseEnvelope(
        primary="已完成重排并复审。",
        followups=[
            WSResponse(
                type="planningWorkspaceAction",
                session_id="sess-followups",
                content=json.dumps(
                    {
                        "type": "planningWorkspaceAction",
                        "targetView": "ordered",
                        "refresh": True,
                        "title": "查看调整后的排序方案",
                        "actionText": "打开排序方案",
                    },
                    ensure_ascii=False,
                ),
            ),
            WSResponse(
                type="planningWorkspaceAction",
                session_id="sess-followups",
                content=json.dumps(
                    {
                        "type": "planningWorkspaceAction",
                        "targetView": "review",
                        "refresh": True,
                        "title": "查看方案审查结果",
                        "actionText": "打开审查结果",
                    },
                    ensure_ascii=False,
                ),
            ),
        ],
    ))
    mock_service.handle_intent_select = AsyncMock()
    client.app.state.chat_service = mock_service

    with client.websocket_connect(WS_PATH) as ws:
        with patch("app.server.message_store") as mock_store:
            mock_store.save_user_message = AsyncMock(return_value=1)
            mock_store.save_agent_message = AsyncMock(side_effect=[2, 3, 4])

            ws.send_json({
                "sessionId": "sess-followups",
                "userId": "user-followups",
                "content": "确认重排",
                "inputType": "text",
            })
            primary = ws.receive_json()
            first_followup = ws.receive_json()
            second_followup = ws.receive_json()

    assert primary["type"] == "text"
    assert primary["content"] == "已完成重排并复审。"
    assert first_followup["type"] == "planningWorkspaceAction"
    assert first_followup["content"]["targetView"] == "ordered"
    assert first_followup["content"]["title"] == "查看调整后的排序方案"
    assert first_followup["content"]["actionText"] == "打开排序方案"
    assert second_followup["type"] == "planningWorkspaceAction"
    assert second_followup["content"]["targetView"] == "review"
    assert second_followup["content"]["title"] == "查看方案审查结果"
    assert second_followup["content"]["actionText"] == "打开审查结果"


def test_ws_compat_structured_session_query_state_returns_rich_text_without_workspace_card(client, tmp_path):
    llm_client = MagicMock()
    llm_client.model = MagicMock()
    llm_client.model_settings = {}
    fake_agent = _PlanStatusToolAgent()
    with patch("app.service.ChatAgent", return_value=fake_agent):
        service = ChatService(llm_client, ChatHistoryStore(str(tmp_path / "history.db")))
    client.app.state.chat_service = service

    planning_state = _planning_state_for_status_overview()
    ordered_plan = _ordered_plan_for_status_overview()

    with client.websocket_connect(WS_PATH) as ws:
        with patch("app.server.message_store") as mock_store, \
                patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
                patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
                patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 0, "data": planning_state})), \
                patch("app.service.get_intent_change_cache", AsyncMock(return_value={"code": 0, "data": {}})), \
                patch(
                    "app.handlers.query_handlers._get_planning_state_with_latest_profile",
                    AsyncMock(return_value=planning_state),
                ), \
                patch(
                    "app.handlers.query_handlers._get_planning_ordered_plan_request",
                    AsyncMock(return_value={"code": 0, "data": ordered_plan}),
                ):
            mock_store.save_user_message = AsyncMock(return_value=1)
            mock_store.save_agent_message = AsyncMock(return_value=2)

            ws.send_json({
                "sessionId": "sess-structured-query-state",
                "userId": "user-structured-query-state",
                "content": "看看现在的方案",
                "inputType": "text",
            })
            responses = []
            resp = None
            for _ in range(4):
                item = ws.receive_json()
                responses.append(item)
                if item.get("type") == "text" and item.get("end") is True:
                    resp = item
                    break

    assert resp is not None, responses
    thinking_contents = [item.get("content") for item in responses if item.get("type") == "thinking"]
    assert "正在读取当前方案并整理这次请求..." in thinking_contents
    assert "正在整理当前方案的数量、梯度和风险..." in thinking_contents
    assert resp["type"] == "text"
    assert resp["end"] is True
    content = resp["content"]
    assert "方案已经有了" in content
    assert "45/45" in content
    assert "冲18 / 稳13 / 保14" in content
    assert "暂时没有明显风险" in content
    assert "贴近偏好的例子" in content
    assert "北京财经学院-财政学(冲)第1位" in content
    assert "方案前几个志愿" not in content
    assert "@1" not in content
    assert "(unknown)" not in content
    assert fake_agent.calls == []
    saved_types = [call.kwargs.get("ws_type") for call in mock_store.save_agent_message.await_args_list]
    assert "planningWorkspaceAction" not in saved_types


def test_ws_compat_model_driven_intent_popup_roundtrip(client):
    mock_service = AsyncMock()
    mock_service.handle_intent_select = AsyncMock()
    mock_service.handle_message = AsyncMock(return_value=WSResponse(
        type="intentConfirmPopup",
        session_id="21",
        content=json.dumps(
            {
                "title": "请确认你的要求",
                "impactTitle": "对当前方案、候选范围与下一步分析的关联判断",
                "impact": "先结合当前方案做一轮分析。",
                "intentMode": "constraint",
                "clickable": True,
                "clicked": False,
                "items": [{"content": "排除北京", "value": {"city_intents": {"negative_province": ["北京"]}}, "selected": True}],
            },
            ensure_ascii=False,
        ),
    ))
    client.app.state.chat_service = mock_service

    with client.websocket_connect(WS_PATH) as ws:
        with patch("app.server.message_store") as mock_store:
            mock_store.save_user_message = AsyncMock(return_value=1)
            mock_store.save_agent_message = AsyncMock(return_value=889)

            ws.send_json({
                "sessionId": "21",
                "userId": "user-e2e-intent",
                "content": "不想去北京",
                "inputType": "text",
            })
            resp = ws.receive_json()

    assert resp["type"] == "intentConfirmPopup"
    assert resp["content"]["message_id"] == 889
    assert resp["content"]["intentMode"] == "constraint"


def test_ws_compat_intent_select_constraint_end_to_end_returns_workspace_action(client):
    message_content = {
        "intentMode": "constraint",
        "clickable": True,
        "clicked": False,
        "items": [{"value": {"city_intents": {"negative_province": ["北京"]}}}],
    }

    mock_service = AsyncMock()
    client.app.state.chat_service = mock_service
    mock_service.handle_message = AsyncMock()
    mock_service.handle_intent_select = AsyncMock(return_value=WSResponse(
        type="planningWorkspaceAction",
        session_id="33",
        content=json.dumps(
            {
                "targetView": "candidate",
                "refresh": True,
                "candidateFilters": {"negativeProvinceNames": ["北京"]},
                "content": "还剩 96 个候选，原来共有 2800 个。",
            },
            ensure_ascii=False,
        ),
    ))

    with client.websocket_connect(WS_PATH) as ws:
        with patch("app.server.message_store") as mock_store:
            mock_store.save_user_message = AsyncMock(return_value=1)
            mock_store.save_agent_message = AsyncMock(return_value=990)

            ws.send_json({
                "sessionId": "33",
                "userId": "user-intent-select",
                "content": {
                    "action": "采纳",
                    "message_id": 3001,
                    "selected": [{"city_intents": {"negative_province": ["北京"]}}],
                },
                "inputType": "intentSelect",
            })
            resp = ws.receive_json()

    assert resp["type"] == "planningWorkspaceAction"
    assert resp["content"]["candidateFilters"]["negativeProvinceNames"] == ["北京"]


def test_ws_compat_multi_turn_constraint_preview_confirm_then_plan_query(client):
    message_content = {
        "intentMode": "constraint",
        "clickable": True,
        "clicked": False,
        "items": [{"value": {"city_intents": {"negative_province": ["北京"]}}}],
    }

    mock_service = AsyncMock()
    mock_service.handle_message = AsyncMock(side_effect=[
        WSResponse(
            type="intentConfirmPopup",
            session_id="34",
            content=json.dumps(message_content, ensure_ascii=False),
        ),
        "已分析当前方案建议",
    ])
    mock_service.handle_intent_select = AsyncMock(return_value=WSResponse(
        type="planningWorkspaceAction",
        session_id="34",
        content=json.dumps({"candidateFilters": {"negativeProvinceNames": ["北京"]}}, ensure_ascii=False),
    ))
    client.app.state.chat_service = mock_service

    with client.websocket_connect(WS_PATH) as ws:
        with patch("app.server.message_store") as mock_store:
            mock_store.save_user_message = AsyncMock(side_effect=[1, 2, 3])
            mock_store.save_agent_message = AsyncMock(side_effect=[900, 901, 902])

            ws.send_json({"sessionId": "34", "userId": "user-multi-turn", "content": "不想去北京", "inputType": "text"})
            preview_resp = ws.receive_json()

            ws.send_json({
                "sessionId": "34",
                "userId": "user-multi-turn",
                "content": {
                    "action": "采纳",
                    "message_id": preview_resp["content"]["message_id"],
                    "selected": [{"city_intents": {"negative_province": ["北京"]}}],
                },
                "inputType": "intentSelect",
            })
            confirm_resp = ws.receive_json()

            ws.send_json({"sessionId": "34", "userId": "user-multi-turn", "content": "看看方案有什么建议", "inputType": "text"})
            plan_resp = ws.receive_json()

    assert preview_resp["type"] == "intentConfirmPopup"
    assert confirm_resp["type"] == "planningWorkspaceAction"
    assert plan_resp["type"] == "text"
    assert plan_resp["content"] == "已分析当前方案建议"


def test_ws_compat_question_style_interest_query_falls_back_to_chat_response(client):
    mock_service = AsyncMock()
    mock_service.handle_message = AsyncMock(return_value="这是普通查询回复")
    mock_service.handle_intent_select = AsyncMock()
    client.app.state.chat_service = mock_service

    with client.websocket_connect(WS_PATH) as ws:
        with patch("app.server.message_store") as mock_store:
            mock_store.save_user_message = AsyncMock(return_value=1)
            mock_store.save_agent_message = AsyncMock(return_value=2)

            ws.send_json({
                "sessionId": "sess-interest-query",
                "userId": "user-interest-query",
                "content": "北京有哪些学校？",
                "inputType": "text",
            })
            resp = ws.receive_json()

    assert resp["type"] == "text"
    assert resp["content"] == "这是普通查询回复"


def test_legacy_plan_edit_maps_to_chat(client):
    mock_service = AsyncMock()
    mock_service.handle_message = AsyncMock(return_value="方案已生成")
    mock_service.handle_intent_select = AsyncMock()
    client.app.state.chat_service = mock_service

    with client.websocket_connect(WS_PATH) as ws:
        with patch("app.server.message_store") as mock_store:
            mock_store.save_user_message = AsyncMock(return_value=1)
            mock_store.save_agent_message = AsyncMock(return_value=2)

            ws.send_json({
                "sessionId": "sess-004",
                "userId": "user-004",
                "content": "采纳",
                "inputType": "planEdit",
            })
            resp = ws.receive_json()

    assert resp["type"] == "text"
    assert resp["content"] == "方案已生成"
    mock_service.handle_intent_select.assert_not_awaited()


def test_handler_exception_returns_error(client):
    mock_service = AsyncMock()
    mock_service.handle_message = AsyncMock(side_effect=RuntimeError("boom"))
    client.app.state.chat_service = mock_service

    with client.websocket_connect(WS_PATH) as ws:
        with patch("app.server.message_store") as mock_store:
            mock_store.save_user_message = AsyncMock(return_value=1)
            mock_store.save_agent_message = AsyncMock(return_value=2)

            ws.send_json({
                "sessionId": "sess-005",
                "userId": "user-005",
                "content": "测试",
                "inputType": "text",
            })
            resp = ws.receive_json()

    assert resp["type"] == "error"
    assert resp["content"] == "处理消息时出错，请稍后重试"
    assert resp["end"] is True
    mock_store.save_agent_message.assert_not_awaited()


def test_ws_compat_timeout_uses_plan_execution_fallback_and_followup(client):
    mock_service = AsyncMock()
    mock_service.handle_message = AsyncMock(side_effect=asyncio.TimeoutError())
    mock_service.handle_intent_select = AsyncMock()
    client.app.state.chat_service = mock_service

    fallback = ChatServiceResponseEnvelope(
        primary="这轮审查已经执行完了，我先把核心结果直接给你：\n\n当前方案里较贴近的有14个，明显冲突的有0个。",
        followups=[
            WSResponse(
                type="planningWorkspaceAction",
                session_id="sess-timeout",
                content=json.dumps(
                    {
                        "type": "planningWorkspaceAction",
                        "targetView": "review",
                        "refresh": True,
                        "title": "查看方案审查结果",
                        "actionText": "打开审查结果",
                    },
                    ensure_ascii=False,
                ),
            )
        ],
    )

    with client.websocket_connect(WS_PATH) as ws:
        with patch("app.server.message_store") as mock_store, patch(
            "app.server.build_timeout_fallback_from_recent_plan_execution",
            return_value=fallback,
        ) as mock_builder:
            mock_store.save_user_message = AsyncMock(return_value=1)
            mock_store.save_agent_message = AsyncMock(side_effect=[2, 3])

            ws.send_json({
                "sessionId": "sess-timeout",
                "userId": "user-timeout",
                "content": "帮我审查一下当前方案",
                "inputType": "text",
            })
            primary = ws.receive_json()
            followup = ws.receive_json()

    assert primary["type"] == "text"
    assert "当前方案里较贴近的有14个" in primary["content"]
    assert followup["type"] == "planningWorkspaceAction"
    assert followup["content"]["targetView"] == "review"
    mock_builder.assert_called_once_with("sess-timeout", "帮我审查一下当前方案")


def test_ws_compat_timeout_uses_pending_intent_fallback_after_plan_miss(client):
    mock_service = AsyncMock()
    mock_service.handle_message = AsyncMock(side_effect=asyncio.TimeoutError())
    mock_service.handle_intent_select = AsyncMock()
    client.app.state.chat_service = mock_service

    fallback = ChatServiceResponseEnvelope(
        primary="我已经把这次提到的想法整理成待确认内容了。\n\n- 把法学类作为后续优先参考的专业方向\n- 明确不考虑：护理学类\n\n如果确认要作为后续参考，直接回复“确认这个要求”。确认前不会正式生效，也不会直接改动当前方案。",
    )

    with client.websocket_connect(WS_PATH) as ws:
        with patch("app.server.message_store") as mock_store, \
                patch(
                    "app.server.build_timeout_fallback_from_recent_plan_execution",
                    return_value=None,
                ) as plan_builder, \
                patch(
                    "app.server.build_timeout_fallback_from_pending_intent_preview",
                    AsyncMock(return_value=fallback),
                ) as intent_builder:
            mock_store.save_user_message = AsyncMock(return_value=1)
            mock_store.save_agent_message = AsyncMock(return_value=2)

            ws.send_json({
                "sessionId": "sess-intent-timeout",
                "userId": "user-intent-timeout",
                "content": "我倾向法学，但护理不要",
                "inputType": "text",
            })
            resp = ws.receive_json()

    assert resp["type"] == "text"
    assert "待确认" in resp["content"]
    assert "法学类" in resp["content"]
    assert "护理学类" in resp["content"]
    assert "确认前不会正式生效" in resp["content"]
    plan_builder.assert_called_once_with("sess-intent-timeout", "我倾向法学，但护理不要")
    intent_builder.assert_awaited_once_with("sess-intent-timeout", "我倾向法学，但护理不要")


def test_ws_compat_timeout_without_plan_execution_fallback_returns_generic_reply(client):
    mock_service = AsyncMock()
    mock_service.handle_message = AsyncMock(side_effect=asyncio.TimeoutError())
    mock_service.handle_intent_select = AsyncMock()
    client.app.state.chat_service = mock_service

    with client.websocket_connect(WS_PATH) as ws:
        with patch("app.server.message_store") as mock_store, \
                patch(
                    "app.server.build_timeout_fallback_from_recent_plan_execution",
                    return_value=None,
                ) as mock_builder, \
                patch(
                    "app.server.build_timeout_fallback_from_pending_intent_preview",
                    AsyncMock(return_value=None),
                ) as intent_builder:
            mock_store.save_user_message = AsyncMock(return_value=1)
            mock_store.save_agent_message = AsyncMock(return_value=2)

            ws.send_json({
                "sessionId": "sess-timeout-none",
                "userId": "user-timeout-none",
                "content": "帮我审查一下当前方案",
                "inputType": "text",
            })
            resp = ws.receive_json()

    assert resp["type"] == "text"
    assert "这次分析耗时有点长" in resp["content"]
    mock_builder.assert_called_once_with("sess-timeout-none", "帮我审查一下当前方案")
    intent_builder.assert_awaited_once_with("sess-timeout-none", "帮我审查一下当前方案")
