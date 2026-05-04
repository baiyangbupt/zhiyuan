"""Unit tests for ProfileManager service."""

import pytest
from unittest.mock import AsyncMock, patch
from app.services.profile_manager import ProfileManager, _merge_with_emotion, _resolve_conflicts


def test_merge_with_emotion_both_empty():
    values, emotions = _merge_with_emotion(None, None, None, None)
    assert values == []
    assert emotions == []


def test_merge_with_emotion_new_only():
    values, emotions = _merge_with_emotion(None, None, ["A", "B"], None)
    assert values == ["A", "B"]
    assert emotions == ["Strong", "Strong"]


def test_merge_with_emotion_existing_only():
    values, emotions = _merge_with_emotion(["A"], ["Strong"], None, None)
    assert values == ["A"]
    assert emotions == ["Strong"]


def test_merge_with_emotion_no_duplicates():
    values, emotions = _merge_with_emotion(
        ["A"], ["Strong"], ["B", "C"], ["Medium", "Weak"]
    )
    assert values == ["A", "B", "C"]
    assert emotions == ["Strong", "Medium", "Weak"]


def test_merge_with_emotion_with_duplicates():
    values, emotions = _merge_with_emotion(
        ["A", "B"], ["Strong", "Medium"], ["B", "C"], ["Weak", "Strong"]
    )
    assert values == ["A", "B", "C"]
    assert emotions == ["Strong", "Medium", "Strong"]


def test_resolve_conflicts():
    pos_vals, pos_emo, neg_vals, neg_emo = _resolve_conflicts(
        ["A", "B"], ["Strong", "Medium"],
        ["C", "D"], ["Weak", "Strong"],
        ["C"]
    )
    assert pos_vals == ["A", "B"]
    assert neg_vals == ["D"]
    assert neg_emo == ["Strong"]


@pytest.mark.asyncio
async def test_update_school_intent():
    with patch("app.services.profile_manager.get_user_profile", new_callable=AsyncMock) as mock_get, \
         patch("app.services.profile_manager.save_user_profile", new_callable=AsyncMock) as mock_save:

        mock_get.return_value = {"data": {"dataValue": {}}}

        manager = ProfileManager(chat_session_id=123)
        await manager.update_school_intent('{"colleges": ["北京大学"], "negative_colleges": []}')

        mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_update_major_intent():
    with patch("app.services.profile_manager.get_user_profile", new_callable=AsyncMock) as mock_get, \
         patch("app.services.profile_manager.save_user_profile", new_callable=AsyncMock) as mock_save:

        mock_get.return_value = {"data": {"dataValue": {}}}

        manager = ProfileManager(chat_session_id=123)
        await manager.update_major_intent('{"level3": ["计算机科学与技术"]}')

        mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_update_city_intent():
    with patch("app.services.profile_manager.get_user_profile", new_callable=AsyncMock) as mock_get, \
         patch("app.services.profile_manager.save_user_profile", new_callable=AsyncMock) as mock_save:

        mock_get.return_value = {"data": {"dataValue": {}}}

        manager = ProfileManager(chat_session_id=123)
        await manager.update_city_intent(
            '{"province": ["北京市"]}',
            '{"province": []}'
        )

        mock_save.assert_called_once()
