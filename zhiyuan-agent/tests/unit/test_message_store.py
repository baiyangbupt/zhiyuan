"""Tests for backend render message persistence wrapper."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from app.data.message_store import MessageStore


@pytest.mark.asyncio
async def test_save_user_message_uses_text():
    with patch(
        "app.data.message_store.save_message",
        new=AsyncMock(return_value={"data": {"id": 123}}),
    ) as save_message_mock:
        store = MessageStore()

        message_id = await store.save_user_message("session-1", "你好")

        assert message_id == 123
        save_message_mock.assert_awaited_once_with(
            chat_session_id="session-1",
            content="你好",
            message_from=1,
            content_type="TEXT",
        )


@pytest.mark.asyncio
async def test_save_agent_card_message_wraps_payload():
    with patch(
        "app.data.message_store.save_message",
        new=AsyncMock(return_value={"data": {"id": 456}}),
    ) as save_message_mock:
        store = MessageStore()

        message_id = await store.save_agent_message("session-1", "点击获取志愿方案", ws_type="card")

        assert message_id == 456
        save_message_mock.assert_awaited_once_with(
            chat_session_id="session-1",
            content={"type": "card", "title": "点击获取志愿方案"},
            message_from=0,
            content_type="CARD",
        )


@pytest.mark.asyncio
async def test_save_agent_planning_workspace_action_message_keeps_payload():
    with patch(
        "app.data.message_store.save_message",
        new=AsyncMock(return_value={"data": {"id": 789}}),
    ) as save_message_mock:
        store = MessageStore()

        message_id = await store.save_agent_message(
            "session-1",
            '{"title":"意向已更新","targetView":"draft","actionText":"查看草稿区","refresh":true}',
            ws_type="planningWorkspaceAction",
        )

        assert message_id == 789
        save_message_mock.assert_awaited_once_with(
            chat_session_id="session-1",
            content={
                "type": "planningWorkspaceAction",
                "title": "意向已更新",
                "targetView": "draft",
                "actionText": "查看草稿区",
                "refresh": True,
            },
            message_from=0,
            content_type="CARD",
        )


@pytest.mark.asyncio
async def test_save_agent_intent_detect_popup_message_keeps_payload():
    with patch(
        "app.data.message_store.save_message",
        new=AsyncMock(return_value={"data": {"id": 790}}),
    ) as save_message_mock:
        store = MessageStore()

        message_id = await store.save_agent_message(
            "session-1",
            '{"title":"报考意向调整确认","items":[{"content":"偏好计算机","selected":true}]}',
            ws_type="intentDetectSelectPopup",
        )

        assert message_id == 790
        save_message_mock.assert_awaited_once_with(
            chat_session_id="session-1",
            content={
                "type": "intentDetectSelectPopup",
                "title": "报考意向调整确认",
                "items": [{"content": "偏好计算机", "selected": True}],
            },
            message_from=0,
            content_type="CARD",
        )
