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
         patch("app.services.profile_manager.save_user_profile", new_callable=AsyncMock) as mock_save, \
         patch("app.services.profile_manager.update_planning_explicit_profile", new_callable=AsyncMock) as mock_update_explicit:

        mock_get.return_value = {"data": {"dataValue": {}}}

        manager = ProfileManager(chat_session_id=123)
        await manager.update_school_intent('{"colleges": ["北京大学"], "negative_colleges": []}')

        mock_save.assert_called_once()
        mock_update_explicit.assert_awaited_once_with(
            123,
            school_preferences={"positive": ["北京大学"], "negative": []},
        )


@pytest.mark.asyncio
async def test_update_major_intent():
    with patch("app.services.profile_manager.get_user_profile", new_callable=AsyncMock) as mock_get, \
         patch("app.services.profile_manager.save_user_profile", new_callable=AsyncMock) as mock_save, \
         patch("app.services.profile_manager.update_planning_explicit_profile", new_callable=AsyncMock) as mock_update_explicit:

        mock_get.return_value = {"data": {"dataValue": {}}}

        manager = ProfileManager(chat_session_id=123)
        await manager.update_major_intent('{"level3": ["计算机科学与技术"]}')

        mock_save.assert_called_once()
        mock_update_explicit.assert_awaited_once_with(
            123,
            major_preferences={"positive": ["计算机科学与技术"], "negative": []},
        )


@pytest.mark.asyncio
async def test_update_city_intent():
    with patch("app.services.profile_manager.get_user_profile", new_callable=AsyncMock) as mock_get, \
         patch("app.services.profile_manager.save_user_profile", new_callable=AsyncMock) as mock_save, \
         patch("app.services.profile_manager.update_planning_explicit_profile", new_callable=AsyncMock) as mock_update_explicit:

        mock_get.return_value = {"data": {"dataValue": {}}}

        manager = ProfileManager(chat_session_id=123)
        await manager.update_city_intent(
            '{"province": ["北京市"]}',
            '{"province": []}'
        )

        mock_save.assert_called_once()
        mock_update_explicit.assert_awaited_once_with(
            123,
            region_preferences={"positive": ["北京市"], "negative": []},
        )


@pytest.mark.asyncio
async def test_update_major_intent_negative_removes_conflicting_positive_and_syncs_planning():
    with patch("app.services.profile_manager.get_user_profile", new_callable=AsyncMock) as mock_get, \
         patch("app.services.profile_manager.save_user_profile", new_callable=AsyncMock) as mock_save, \
         patch("app.services.profile_manager.update_planning_explicit_profile", new_callable=AsyncMock) as mock_update_explicit:

        mock_get.return_value = {
            "code": 0,
            "data": {
                "userprofile": {
                    "major_intent": {
                        "level2": ["财政学类", "法学类"],
                        "level2_emotion": ["Strong", "Strong"],
                    },
                    "negative_major_intent": {
                        "level2": ["社会学类"],
                        "level2_emotion": ["Strong"],
                    },
                }
            },
        }

        manager = ProfileManager(chat_session_id=130)
        await manager.update_major_intent('{"negative_level2": ["法学类"]}')

    saved_profile = mock_save.await_args.args[1]
    assert saved_profile["major_intent"]["level2"] == ["财政学类"]
    assert saved_profile["negative_major_intent"]["level2"] == ["社会学类", "法学类"]
    mock_update_explicit.assert_awaited_once_with(
        130,
        major_preferences={
            "positive": ["财政学类"],
            "negative": ["社会学类", "法学类"],
        },
    )


@pytest.mark.asyncio
async def test_update_major_intent_positive_reinclude_cleans_negative_parent_and_children():
    with patch("app.services.profile_manager.get_user_profile", new_callable=AsyncMock) as mock_get, \
         patch("app.services.profile_manager.save_user_profile", new_callable=AsyncMock) as mock_save, \
         patch("app.services.profile_manager.update_planning_explicit_profile", new_callable=AsyncMock) as mock_update_explicit:

        mock_get.return_value = {
            "code": 0,
            "data": {
                "userprofile": {
                    "major_intent": {
                        "level2": ["工商管理类"],
                        "level2_emotion": ["Strong"],
                    },
                    "negative_major_intent": {
                        "level3": ["会计学", "工商管理类"],
                        "level3_emotion": ["Strong", "Strong"],
                    },
                }
            },
        }

        manager = ProfileManager(chat_session_id=130)
        await manager.update_major_intent('{"level2": ["工商管理类"]}')

    saved_profile = mock_save.await_args.args[1]
    assert saved_profile["major_intent"]["level2"] == ["工商管理类"]
    assert saved_profile["negative_major_intent"]["level2"] == []
    assert saved_profile["negative_major_intent"]["level3"] == []
    mock_update_explicit.assert_awaited_once_with(
        130,
        major_preferences={
            "positive": ["工商管理类"],
            "negative": [],
        },
    )
