"""Integration tests for user profile persistence flow."""

import pytest
from unittest.mock import AsyncMock, patch
from app.services.profile_manager import ProfileManager
from app.schemas.user_profile import UserProfile


@pytest.mark.asyncio
async def test_school_intent_conflict_resolution():
    """Test that adding a school to positive removes it from negative."""
    with patch("app.services.profile_manager.get_user_profile", new_callable=AsyncMock) as mock_get, \
         patch("app.services.profile_manager.save_user_profile", new_callable=AsyncMock) as mock_save, \
         patch("app.services.profile_manager.update_planning_explicit_profile", new_callable=AsyncMock):

        # Existing profile has 清华大学 in negative
        mock_get.return_value = {
            "data": {
                "dataValue": {
                    "college_info": {"values": ["北京大学"], "values_emotion": ["Strong"]},
                    "negative_college_info": {"values": ["清华大学"], "values_emotion": ["Strong"]},
                    "major_intent": {},
                    "negative_major_intent": {},
                    "city_info": {},
                    "negative_city_info": {},
                }
            }
        }

        manager = ProfileManager(chat_session_id=123)
        # New extraction adds 清华大学 to positive
        await manager.update_school_intent('{"colleges": ["清华大学"], "negative_colleges": []}')

        # Verify save was called
        call_args = mock_save.call_args[0]
        saved_data = call_args[1]

        # 清华大学 should be in positive and removed from negative
        assert "清华大学" in saved_data["college_info"]["values"]
        assert "清华大学" not in saved_data["negative_college_info"]["values"]


@pytest.mark.asyncio
async def test_major_intent_incremental_update():
    """Test incremental updates preserve existing data."""
    with patch("app.services.profile_manager.get_user_profile", new_callable=AsyncMock) as mock_get, \
         patch("app.services.profile_manager.save_user_profile", new_callable=AsyncMock) as mock_save, \
         patch("app.services.profile_manager.update_planning_explicit_profile", new_callable=AsyncMock):

        mock_get.return_value = {
            "data": {
                "dataValue": {
                    "college_info": {},
                    "negative_college_info": {},
                    "major_intent": {
                        "level3": ["计算机科学与技术"],
                        "level3_emotion": ["Strong"],
                    },
                    "negative_major_intent": {},
                    "city_info": {},
                    "negative_city_info": {},
                }
            }
        }

        manager = ProfileManager(chat_session_id=123)
        await manager.update_major_intent('{"level3": ["软件工程"]}')

        call_args = mock_save.call_args[0]
        saved_data = call_args[1]

        # Both majors should be present
        assert "计算机科学与技术" in saved_data["major_intent"]["level3"]
        assert "软件工程" in saved_data["major_intent"]["level3"]


@pytest.mark.asyncio
async def test_city_intent_with_emotions():
    """Test city intent preserves emotion pairing."""
    with patch("app.services.profile_manager.get_user_profile", new_callable=AsyncMock) as mock_get, \
         patch("app.services.profile_manager.save_user_profile", new_callable=AsyncMock) as mock_save, \
         patch("app.services.profile_manager.update_planning_explicit_profile", new_callable=AsyncMock):

        mock_get.return_value = {"data": {"dataValue": {}}}

        manager = ProfileManager(chat_session_id=123)
        await manager.update_city_intent(
            '{"province": ["北京市", "上海市"]}',
            '{"province": []}'
        )

        call_args = mock_save.call_args[0]
        saved_data = call_args[1]

        # Check emotions are added
        assert len(saved_data["city_info"]["province"]) == len(saved_data["city_info"]["province_emotion"])
        assert all(e == "Strong" for e in saved_data["city_info"]["province_emotion"])


@pytest.mark.asyncio
async def test_profile_enrichment_with_codes():
    """Test that profile is enriched with codes before saving."""
    with patch("app.services.profile_manager.get_user_profile", new_callable=AsyncMock) as mock_get, \
         patch("app.services.profile_manager.save_user_profile", new_callable=AsyncMock) as mock_save, \
         patch("app.services.profile_manager.update_planning_explicit_profile", new_callable=AsyncMock):

        mock_get.return_value = {"data": {"dataValue": {}}}

        manager = ProfileManager(chat_session_id=123)
        await manager.update_school_intent('{"colleges": ["北京大学"]}')

        call_args = mock_save.call_args[0]
        saved_data = call_args[1]

        # Check that codes are added
        assert "values_code" in saved_data["college_info"]
