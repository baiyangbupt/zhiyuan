"""Tests for the agent-plus compatible WebSocket endpoint."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart

from app.data.history_store import ChatHistoryStore
from app.schemas.ws import WSResponse
from app.service import ChatService, ChatServiceResponseEnvelope, _build_plan_timeout_fallback_reply
from app.server import _build_legacy_chat_service

class _PermissiveAccessGuard:
    """测试替身：直接放行并返回固定身份。

    **只在测试里装**。生产路径无条件校验票据（见 app/gateway/access.py），
    它的正确性由 tests/integration/test_gateway_access.py 的 7 条覆盖——
    这里不重复验它，只负责让 WS 用例能连上。
    """

    def __init__(self, tenant_id: str = "test-tenant", bot_id: str = "test-bot") -> None:
        self._tenant_id = tenant_id
        self._bot_id = bot_id

    async def verify(self, ticket, origin):
        from app.gateway.access import TicketIdentity

        return TicketIdentity(
            tenant_id=self._tenant_id,
            session_id="test-session",
            user_id="test-user",
            bot_id=self._bot_id,
            origin=origin or "http://127.0.0.1:3201",
        )




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
    from app.server import app as _app

    # 生产路径无条件校验 WS 票据；测试装一个放行替身，让 WS 用例能连上。
    _app.state.conversation_access_guard = _PermissiveAccessGuard()
    yield
    _stop_patches()


@pytest.fixture()
def client():
    from app.server import app
    return TestClient(app)


WS_PATH = "/gaotu-assistant-agent/plus/chat/test-tenant/bot/test-bot/do"


def test_codex_readonly_does_not_build_the_legacy_llm_stack():
    with patch("app.server.LLMClient") as llm_client, patch("app.server.ChatHistoryStore") as history_store:
        assert _build_legacy_chat_service("codex_readonly") is None

    llm_client.assert_not_called()
    history_store.assert_not_called()


def test_legacy_and_shadow_modes_build_the_legacy_stack():
    with patch("app.server.LLMClient") as llm_client, patch("app.server.ChatHistoryStore") as history_store, patch("app.server.ChatService") as chat_service:
        _build_legacy_chat_service("legacy")
        _build_legacy_chat_service("codex_shadow")

    assert llm_client.call_count == 2
    assert history_store.call_count == 2
    assert chat_service.call_count == 2


class _ClosedJsonWebSocket:
    async def send_json(self, data):
        raise RuntimeError('Cannot call "send" once a close message has been sent.')


class _UnexpectedJsonWebSocket:
    async def send_json(self, data):
        raise RuntimeError("unexpected websocket failure")


class _RecordingJsonWebSocket:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, data):
        self.sent.append(data)


class _PlanStatusToolAgent:
    def __init__(self):
        self.calls: list[dict] = []
        self.tool_results: list[dict] = []

    async def run_with_message_deltas(self, user_prompt, message_history=None, deps=None, on_progress=None):
        self.calls.append({"user_prompt": user_prompt, "session_id": deps.sessionid if deps else None})
        tool_result = {
            "applied": True,
            "action_family": "query_plan",
            "stage": "apply",
            "result_kind": "status_overview",
            "workspace_refresh_targets": [],
            "summary": "当前方案 45/45 个志愿，冲18 / 稳13 / 保14，风险0项，提醒2项。",
            "facts": {
                "current_total": 45,
                "target_total": 45,
                "tier_counts": {"冲": 18, "稳": 13, "保": 14},
                "risk_count": 0,
                "warn_count": 0,
                "phase": "reviewed",
                "top_items": [
                    "北京财经学院-财政学(冲)@1",
                    "天津财经大学-经济学(稳)@2",
                    "河北经贸大学-法学(保)@3",
                ],
                "intent_relation": {
                    "coverage": "承接情况：当前方案里较贴近的有27个，明显冲突的有0个。",
                    "aligned_examples": "贴近偏好：北京财经学院-财政学(冲)@1",
                },
            },
        }
        tool_result_text = json.dumps(tool_result, ensure_ascii=False)
        self.tool_results.append(tool_result)

        reply = _build_plan_timeout_fallback_reply(tool_result) or tool_result.get("summary") or ""
        new_messages = [
            ModelRequest(parts=[UserPromptPart(content=user_prompt)]),
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="query_plan",
                        args={"scope": "plan", "query_type": "status"},
                        tool_call_id="query-state-status-1",
                    )
                ],
                model_name="test-model",
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="query_plan",
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


def test_safe_send_compat_json_forwards_to_latest_connection_when_original_closed(client):
    from app.server import _compat_connections, _safe_send_compat_json

    active_ws = _RecordingJsonWebSocket()
    payload = {"type": "text", "content": "已处理", "end": True}

    async def _run():
        await _compat_connections.register("sess-reconnect", active_ws)
        try:
            return await _safe_send_compat_json(
                _ClosedJsonWebSocket(),
                "sess-reconnect",
                payload,
                context="test.reconnect",
            )
        finally:
            await _compat_connections.unregister("sess-reconnect", active_ws)

    result = asyncio.run(_run())

    assert result is True
    assert active_ws.sent == [payload]


def test_ping_pong(client):
    client.app.state.chat_service = AsyncMock()
    with client.websocket_connect(WS_PATH) as ws:
        ws.send_json({"inputType": "ping", "timestamp": 12345})
        resp = ws.receive_json()
        assert resp["type"] == "pong"
        assert resp["timestamp"] == 12345


def test_gateway_mode_compat_text_routes_to_gateway(client):
    gateway = MagicMock()
    gateway.handle_turn = AsyncMock(return_value={"reply": "Gateway 已处理", "events": []})
    client.app.state.gateway_service = gateway

    with client.websocket_connect(WS_PATH) as ws:
        ws.send_json(
            {
                "sessionId": "gateway-session",
                "userId": "gateway-user",
                "content": "帮我看看浙江大学",
                "inputType": "text",
                "turnId": "turn-1",
            }
        )
        response = ws.receive_json()

    client.app.state.gateway_service = None
    assert response == {"type": "text", "content": "Gateway 已处理", "end": True}
    gateway.handle_turn.assert_awaited_once()
    call = gateway.handle_turn.await_args.kwargs
    assert {k: call[k] for k in ("tenant_id", "session_id", "user_id", "turn_id", "content")} == {
        "tenant_id": "test-tenant",
        "session_id": "gateway-session",
        "user_id": "gateway-user",
        "turn_id": "turn-1",
        "content": "帮我看看浙江大学",
    }
    # A3 起 compat 路由也要转发中间事件，所以 `emit` 必须真的接上——
    # 只断言"参数没变"会让"忘了接线"和"接好了"看起来一样。
    assert callable(call["emit"])


def test_gateway_mode_compat_confirmation_maps_to_conversation_action(client):
    gateway = MagicMock()
    gateway.get_current_snapshot = AsyncMock(return_value=object())
    gateway.execute_action_and_refresh = AsyncMock(
        return_value={
            "actionResult": {"actionStatus": "applied"},
            "snapshotVersion": 8,
        }
    )
    client.app.state.gateway_service = gateway

    with client.websocket_connect(WS_PATH) as ws:
        ws.send_json(
            {
                "sessionId": "gateway-session",
                "userId": "gateway-user",
                "content": {"action": "confirm", "pendingId": "proposal-1", "sourceVersion": 7},
                "inputType": "pendingConfirmation",
            }
        )
        response = ws.receive_json()

    client.app.state.gateway_service = None
    assert response["type"] == "text"
    payload = json.loads(response["content"])
    assert payload["type"] == "conversationAction.result"
    gateway.execute_action_and_refresh.assert_awaited_once()
    gateway.get_current_snapshot.assert_awaited_once_with(
        tenant_id="test-tenant", session_id="gateway-session"
    )
    action = gateway.execute_action_and_refresh.await_args.kwargs["action"]
    assert action == {
        "actionType": "confirm_proposal",
        "proposalRef": "proposal-1",
        "expectedSourceVersion": 7,
        "intent": "explicit",
    }


def test_gateway_mode_compat_without_snapshot_fails_closed(client):
    gateway = MagicMock()
    gateway.get_current_snapshot = AsyncMock(return_value=None)
    gateway.execute_action_and_refresh = AsyncMock()
    client.app.state.gateway_service = gateway

    with client.websocket_connect(WS_PATH) as ws:
        ws.send_json(
            {
                "sessionId": "missing-session",
                "userId": "gateway-user",
                "content": {"action": "cancel", "pendingId": "proposal-1"},
                "inputType": "pendingConfirmation",
            }
        )
        response = ws.receive_json()

    client.app.state.gateway_service = None
    assert response["type"] == "error"
    assert "失去上下文" in response["content"]
    gateway.execute_action_and_refresh.assert_not_awaited()


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
    with patch("app.service.ZhiyuanAgent", return_value=fake_agent):
        service = ChatService(llm_client, ChatHistoryStore(str(tmp_path / "history.db")))
    client.app.state.chat_service = service

    planning_state = _planning_state_for_status_overview()

    with client.websocket_connect(WS_PATH) as ws:
        with patch("app.server.message_store") as mock_store, \
                patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})), \
                patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})), \
                patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 0, "data": planning_state})):
            mock_store.save_user_message = AsyncMock(return_value=1)
            mock_store.save_agent_message = AsyncMock(return_value=2)

            ws.send_json({
                "sessionId": "sess-structured-query-state",
                "userId": "user-structured-query-state",
                "content": "看看现在的方案",
                "inputType": "text",
            })
            resp = ws.receive_json()
            while resp.get("type") == "thinking":
                resp = ws.receive_json()

    assert resp["type"] == "text"
    assert resp["end"] is True
    content = resp["content"]
    assert "我看了当前方案，核心情况如下" in content
    assert "- 完整度：45/45 个志愿。" in content
    assert "- 冲稳保：冲18 / 稳13 / 保14。" in content
    assert "- 审查：暂时没有明显风险。" in content
    assert "贴近偏好的例子" in content
    assert "北京财经学院-财政学(冲)第1位" in content
    assert "方案前几个志愿" not in content
    assert "@1" not in content
    assert "(unknown)" not in content
    assert fake_agent.tool_results[0]["workspace_refresh_targets"] == []
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


def test_ws_compat_intent_select_constraint_returns_pending_confirmation_card_not_workspace_action(client):
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
        type="pendingConfirmationCard",
        session_id="33",
        content=json.dumps(
            {
                "type": "pendingConfirmationCard",
                "kind": "intent_change",
                "pendingId": "pending-intent-constraint-1",
                "title": "确认采纳这次要求",
                "summary": "排除北京。",
                "confirmText": "采纳",
                "cancelText": "暂不采纳",
                "clickable": True,
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

    assert resp["type"] == "pendingConfirmationCard"
    assert resp["content"]["pendingId"] == "pending-intent-constraint-1"
    assert "candidateFilters" not in resp["content"]
    assert mock_store.save_agent_message.await_args.kwargs["ws_type"] == "pendingConfirmationCard"


def test_v3_ws_intent_select_routes_to_intent_select_handler(client):
    card_payload = {
        "type": "pendingConfirmationCard",
        "kind": "intent_change",
        "pendingId": "pending-intent-v3-1",
        "title": "确认采纳这次偏好",
        "summary": "偏好北京。",
        "confirmText": "采纳",
        "cancelText": "暂不采纳",
        "clickable": True,
    }

    mock_service = AsyncMock()
    client.app.state.chat_service = mock_service
    mock_service.handle_message = AsyncMock()
    mock_service.handle_intent_select = AsyncMock(return_value=WSResponse(
        type="pendingConfirmationCard",
        session_id="33",
        content=json.dumps(card_payload, ensure_ascii=False),
    ))

    with client.websocket_connect("/ws/chat") as ws:
        with patch("app.server.message_store") as mock_store:
            mock_store.save_user_message = AsyncMock(return_value=1)
            mock_store.save_agent_message = AsyncMock(return_value=992)

            ws.send_json({
                "session_id": "33",
                "user_id": "user-intent-select",
                "content": json.dumps(
                    {
                        "action": "采纳",
                        "message_id": 3001,
                        "selected": [{"city_intents": {"province": ["北京"]}}],
                    },
                    ensure_ascii=False,
                ),
                "type": "intentSelect",
            })
            resp = ws.receive_json()

    assert resp["type"] == "pendingConfirmationCard"
    assert json.loads(resp["content"])["pendingId"] == "pending-intent-v3-1"
    mock_service.handle_intent_select.assert_awaited_once()
    mock_service.handle_message.assert_not_awaited()
    mock_store.save_user_message.assert_not_awaited()


def test_ws_compat_intent_select_can_return_pending_confirmation_card(client):
    card_payload = {
        "type": "pendingConfirmationCard",
        "kind": "intent_change",
        "pendingId": "pending-intent-compat-1",
        "title": "确认采纳这次要求",
        "summary": "排除北京。",
        "confirmText": "采纳",
        "cancelText": "暂不采纳",
        "clickable": True,
    }

    mock_service = AsyncMock()
    client.app.state.chat_service = mock_service
    mock_service.handle_message = AsyncMock()
    mock_service.handle_intent_select = AsyncMock(return_value=WSResponse(
        type="pendingConfirmationCard",
        session_id="33",
        content=json.dumps(card_payload, ensure_ascii=False),
    ))

    with client.websocket_connect(WS_PATH) as ws:
        with patch("app.server.message_store") as mock_store:
            mock_store.save_user_message = AsyncMock(return_value=1)
            mock_store.save_agent_message = AsyncMock(return_value=991)

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

    assert resp["type"] == "pendingConfirmationCard"
    assert resp["content"]["pendingId"] == "pending-intent-compat-1"
    assert resp["content"]["message_id"] == 991
    saved_kwargs = mock_store.save_agent_message.await_args.kwargs
    assert saved_kwargs["ws_type"] == "pendingConfirmationCard"
    mock_service.handle_message.assert_not_awaited()


def test_ws_compat_multi_turn_constraint_preview_card_click_then_plan_query(client):
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
        type="pendingConfirmationCard",
        session_id="34",
        content=json.dumps(
            {
                "type": "pendingConfirmationCard",
                "kind": "intent_change",
                "pendingId": "pending-intent-34",
                "title": "确认采纳这次要求",
                "summary": "排除北京。",
                "confirmText": "采纳",
                "cancelText": "暂不采纳",
                "clickable": True,
            },
            ensure_ascii=False,
        ),
    ))
    mock_service.handle_pending_confirmation = AsyncMock(return_value=ChatServiceResponseEnvelope(
        primary="已采纳这次要求，后续会避开北京。",
        followups=[
            WSResponse(
                type="planningWorkspaceAction",
                session_id="34",
                content=json.dumps(
                    {
                        "type": "planningWorkspaceAction",
                        "targetView": "ordered",
                        "refresh": True,
                        "title": "请查看方案",
                        "actionText": "查看方案",
                    },
                    ensure_ascii=False,
                ),
            )
        ],
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
            pending_card_resp = ws.receive_json()

            ws.send_json({
                "sessionId": "34",
                "userId": "user-multi-turn",
                "content": {
                    "action": "confirm",
                    "kind": "intent_change",
                    "pendingId": pending_card_resp["content"]["pendingId"],
                },
                "inputType": "pendingConfirmation",
            })
            confirm_resp = ws.receive_json()
            workspace_resp = ws.receive_json()

            ws.send_json({"sessionId": "34", "userId": "user-multi-turn", "content": "看看方案有什么建议", "inputType": "text"})
            plan_resp = ws.receive_json()

    assert preview_resp["type"] == "intentConfirmPopup"
    assert pending_card_resp["type"] == "pendingConfirmationCard"
    assert confirm_resp["type"] == "text"
    assert "已采纳" in confirm_resp["content"]
    assert workspace_resp["type"] == "planningWorkspaceAction"
    assert workspace_resp["content"]["targetView"] == "ordered"
    assert "candidateFilters" not in workspace_resp["content"]
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


def test_ws_compat_timeout_returns_generic_reply(client):
    mock_service = AsyncMock()
    mock_service.handle_message = AsyncMock(side_effect=asyncio.TimeoutError())
    mock_service.handle_intent_select = AsyncMock()
    client.app.state.chat_service = mock_service

    with client.websocket_connect(WS_PATH) as ws:
        with patch("app.server.message_store") as mock_store:
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
    assert "帮我审查一下当前方案" in resp["content"]
    assert "不会自动写入偏好或改动方案" in resp["content"]


# ── v1 入站合同（A2） ────────────────────────────────────────────────
# 老客户端不带这些字段，行为必须逐字不变；v1 客户端多带协议字段与控制消息类型。


def test_v1_chat_message_accepts_protocol_fields() -> None:
    from app.schemas.ws import WSMessage

    message = WSMessage.model_validate(
        {
            "protocolVersion": 1,
            "type": "chat",
            "sessionId": "42",
            "turnId": "ui-turn-1",
            "clientRequestId": "req-1",
            "content": "查某校计算机近三年录取",
        }
    )

    assert message.protocol_version == 1
    assert message.turn_id == "ui-turn-1"
    assert message.client_request_id == "req-1"


def test_legacy_message_without_protocol_fields_is_unchanged() -> None:
    from app.schemas.ws import WSMessage

    message = WSMessage.model_validate({"sessionId": "42", "content": "你好"})

    assert message.protocol_version is None
    assert message.turn_id == ""
    assert message.client_request_id == ""
    assert message.clarification_answer is None
    assert message.type == "chat"


@pytest.mark.parametrize("message_type", ["turnInterrupt", "sessionResume"])
def test_content_free_control_messages_reject_content(message_type: str) -> None:
    from pydantic import ValidationError

    from app.schemas.ws import WSMessage

    accepted = WSMessage.model_validate(
        {"type": message_type, "sessionId": "42", "turnId": "ui-turn-1", "content": ""}
    )
    assert accepted.type == message_type

    with pytest.raises(ValidationError, match="control_message_must_not_carry_content"):
        WSMessage.model_validate(
            {"type": message_type, "sessionId": "42", "content": "顺手带点内容"}
        )


def test_turn_steer_requires_content() -> None:
    from pydantic import ValidationError

    from app.schemas.ws import WSMessage

    steered = WSMessage.model_validate(
        {"type": "turnSteer", "sessionId": "42", "turnId": "ui-turn-1", "content": "再保守一点"}
    )
    assert steered.content == "再保守一点"

    # 空的转述等于什么都没说：明确报错，不要静默变成空操作。
    with pytest.raises(ValidationError, match="turn_steer_requires_content"):
        WSMessage.model_validate(
            {"type": "turnSteer", "sessionId": "42", "turnId": "ui-turn-1", "content": ""}
        )


def test_clarification_answer_uses_its_own_field_not_conversation_action() -> None:
    from app.schemas.ws import WSMessage

    message = WSMessage.model_validate(
        {
            "protocolVersion": 1,
            "type": "clarificationAnswer",
            "sessionId": "42",
            "turnId": "ui-turn-1",
            "clientRequestId": "answer-1",
            "content": "",
            "clarificationAnswer": {
                "requestId": "ui-question-1",
                "inputKind": "choice",
                "answers": {"major": {"answers": ["计算机科学与技术"]}},
            },
        }
    )

    assert message.clarification_answer["inputKind"] == "choice"
    assert message.clarification_answer["requestId"] == "ui-question-1"
    # conversationAction 的语义是"确认/取消一个提案"，不能被回答选择题复用。
    assert message.conversation_action is None


def test_legacy_confirmation_still_uses_chat_plus_conversation_action() -> None:
    from app.schemas.ws import WSMessage

    message = WSMessage.model_validate(
        {
            "type": "chat",
            "sessionId": "42",
            "content": "",
            "conversationAction": {"proposalRef": "proposal-1", "action": "confirm"},
        }
    )

    assert message.conversation_action == {"proposalRef": "proposal-1", "action": "confirm"}
    assert message.clarification_answer is None
