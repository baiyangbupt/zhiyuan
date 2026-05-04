"""Profile manager service for incremental user profile updates."""

import json
from typing import Any
from loguru import logger

from app.schemas.user_profile import UserProfile, SchoolIntent, MajorIntent, CityIntent
from app.util.internal_client import get_user_profile, save_user_profile
from app.util.code_enrichment import add_codes_to_profile_async


def _normalize_string_list(values: Any) -> list[str]:
    """Normalize backend/raw list values to a plain string list.

    Some legacy or malformed profile payloads may contain dict items like
    {"value": "北京"} or {"label": "北京"} which are not hashable.
    """
    if not values:
        return []

    if isinstance(values, str):
        text = values.strip()
        return [text] if text else []

    if isinstance(values, dict):
        values = [values]

    normalized: list[str] = []
    for item in values:
        if isinstance(item, str):
            text = item.strip()
            if text:
                normalized.append(text)
            continue
        if isinstance(item, dict):
            text = item.get("value") or item.get("label") or item.get("name")
            if isinstance(text, str) and text.strip():
                normalized.append(text.strip())
    return normalized


def _normalize_batch(batch: Any) -> str:
    """Normalize batch payload to the legacy batch code string."""
    if not batch:
        return "01"
    if isinstance(batch, str):
        text = batch.strip()
        return text or "01"
    if isinstance(batch, dict):
        code = batch.get("code")
        if isinstance(code, str) and code.strip():
            return code.strip()
    code = getattr(batch, "code", None)
    if isinstance(code, str) and code.strip():
        return code.strip()
    return "01"


def _merge_with_emotion(
    existing_values: list[str] | None,
    existing_emotions: list[str] | None,
    new_values: list[str] | None,
    new_emotions: list[str] | None,
    default_emotion: str = "Strong",
) -> tuple[list[str], list[str]]:
    """Merge value and emotion arrays with conflict resolution."""
    existing_values = _normalize_string_list(existing_values)
    new_values = _normalize_string_list(new_values)
    existing_emotions = _normalize_string_list(existing_emotions)
    new_emotions = _normalize_string_list(new_emotions)

    if not existing_values:
        if not new_values:
            return [], []
        new_emotions = new_emotions or [default_emotion] * len(new_values)
        return new_values, new_emotions

    if not new_values:
        existing_emotions = existing_emotions or [default_emotion] * len(existing_values)
        return existing_values, existing_emotions

    # Ensure emotion arrays match value arrays
    existing_emotions = existing_emotions or [default_emotion] * len(existing_values)
    new_emotions = new_emotions or [default_emotion] * len(new_values)

    # Start with existing values
    merged_values = list(existing_values)
    merged_emotions = list(existing_emotions)
    existing_set = set(existing_values)

    # Add new values not in existing
    for val, emo in zip(new_values, new_emotions):
        if val not in existing_set:
            merged_values.append(val)
            merged_emotions.append(emo)

    return merged_values, merged_emotions


def _resolve_conflicts(
    positive_values: list[str],
    positive_emotions: list[str],
    negative_values: list[str],
    negative_emotions: list[str],
    new_positive: list[str],
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Remove items from opposite list if they appear in new positive."""
    positive_values = _normalize_string_list(positive_values)
    positive_emotions = _normalize_string_list(positive_emotions)
    negative_values = _normalize_string_list(negative_values)
    negative_emotions = _normalize_string_list(negative_emotions)
    new_positive = _normalize_string_list(new_positive)

    new_positive_set = set(new_positive)

    # Remove from negative if in new positive
    filtered_neg_values = []
    filtered_neg_emotions = []
    for val, emo in zip(negative_values, negative_emotions):
        if val not in new_positive_set:
            filtered_neg_values.append(val)
            filtered_neg_emotions.append(emo)

    return positive_values, positive_emotions, filtered_neg_values, filtered_neg_emotions


class ProfileManager:
    """Manages incremental updates to user profile."""

    def __init__(self, chat_session_id: int, batch: Any = "01"):
        self.chat_session_id = chat_session_id
        self.batch = _normalize_batch(batch)

    async def get_current_profile(self) -> UserProfile:
        """Fetch current profile from backend."""
        try:
            response = await get_user_profile(self.chat_session_id)
            logger.info(f"获取用户画像响应: {response}")

            if response and response.get("code") == 0:
                data = response.get("data", {})
                # 后端返回格式: {"data": {"userprofile": {...}}}
                profile_data = data.get("userprofile")

                if not profile_data:
                    logger.warning("用户画像数据为空，返回默认空画像")
                    return UserProfile()

                logger.info(f"解析用户画像数据: {profile_data}")
                return UserProfile.from_backend_format(profile_data)
            else:
                logger.warning(f"获取用户画像失败: {response}")
                return UserProfile()

        except Exception as e:
            logger.error(f"获取用户画像异常: {e}", exc_info=True)
            return UserProfile()

    async def update_school_intent(self, extraction_result: str) -> None:
        """Update school intent from extraction result.

        Expected JSON format:
        {
            "colleges": ["北京大学", "清华大学"],
            "negative_colleges": ["复旦大学"]
        }
        """
        try:
            result = json.loads(extraction_result)

            # Check if there's any valid data to update
            new_colleges = result.get("colleges", [])
            new_neg = result.get("negative_colleges", [])
            if not new_colleges and not new_neg:
                logger.info("No valid school intent data to update, skipping")
                return

            profile = await self.get_current_profile()

            # Merge positive colleges
            if new_colleges:
                profile.school.colleges, profile.school.colleges_emotion = _merge_with_emotion(
                    profile.school.colleges,
                    profile.school.colleges_emotion,
                    new_colleges,
                    None,
                )

            # Merge negative colleges
            if new_neg:
                profile.school.negative_colleges, profile.school.negative_colleges_emotion = _merge_with_emotion(
                    profile.school.negative_colleges,
                    profile.school.negative_colleges_emotion,
                    new_neg,
                    None,
                )

            # Resolve conflicts only if we have new positive data
            if new_colleges:
                (
                    profile.school.colleges,
                    profile.school.colleges_emotion,
                    profile.school.negative_colleges,
                    profile.school.negative_colleges_emotion,
                ) = _resolve_conflicts(
                    profile.school.colleges,
                    profile.school.colleges_emotion,
                    profile.school.negative_colleges,
                    profile.school.negative_colleges_emotion,
                    new_colleges,
                )

            await self._save_profile(profile)
        except Exception as e:
            logger.error(f"Failed to update school intent: {e}")
            raise

    async def update_major_intent(self, extraction_result: str) -> None:
        """Update major intent from extraction result.

        Expected JSON format:
        {
            "level1": ["医学", "法学"],
            "level2": ["工学"],
            "level3": ["计算机科学与技术", "软件工程"],
            "negative_level1": ["农学"],
            "negative_level2": ["医学"],
            "negative_level3": ["临床医学"]
        }
        """
        try:
            result = json.loads(extraction_result)

            # Check if there's any valid data to update
            new_level1 = result.get("level1", [])
            new_level2 = result.get("level2", [])
            new_level3 = result.get("level3", [])
            new_neg_level1 = result.get("negative_level1", [])
            new_neg_level2 = result.get("negative_level2", [])
            new_neg_level3 = result.get("negative_level3", [])

            if not any([new_level1, new_level2, new_level3, new_neg_level1, new_neg_level2, new_neg_level3]):
                logger.info("No valid major intent data to update, skipping")
                return

            profile = await self.get_current_profile()

            # Merge level1
            if new_level1:
                profile.major.level1, profile.major.level1_emotion = _merge_with_emotion(
                    profile.major.level1,
                    profile.major.level1_emotion,
                    new_level1,
                    None,
                )

            # Merge level2
            if new_level2:
                profile.major.level2, profile.major.level2_emotion = _merge_with_emotion(
                    profile.major.level2,
                    profile.major.level2_emotion,
                    new_level2,
                    None,
                )

            # Merge level3
            if new_level3:
                profile.major.level3, profile.major.level3_emotion = _merge_with_emotion(
                    profile.major.level3,
                    profile.major.level3_emotion,
                    new_level3,
                    None,
                )

            # Merge negative level1
            if new_neg_level1:
                profile.major.negative_level1, profile.major.negative_level1_emotion = _merge_with_emotion(
                    profile.major.negative_level1,
                    profile.major.negative_level1_emotion,
                    new_neg_level1,
                    None,
                )

            # Merge negative level2
            if new_neg_level2:
                profile.major.negative_level2, profile.major.negative_level2_emotion = _merge_with_emotion(
                    profile.major.negative_level2,
                    profile.major.negative_level2_emotion,
                    new_neg_level2,
                    None,
                )

            # Merge negative level3
            if new_neg_level3:
                profile.major.negative_level3, profile.major.negative_level3_emotion = _merge_with_emotion(
                    profile.major.negative_level3,
                    profile.major.negative_level3_emotion,
                    new_neg_level3,
                    None,
                )

            # Resolve conflicts for level1 only if we have new positive data
            if new_level1:
                (
                    profile.major.level1,
                    profile.major.level1_emotion,
                    profile.major.negative_level1,
                    profile.major.negative_level1_emotion,
                ) = _resolve_conflicts(
                    profile.major.level1,
                    profile.major.level1_emotion,
                    profile.major.negative_level1,
                    profile.major.negative_level1_emotion,
                    new_level1,
                )

            # Resolve conflicts for level2 only if we have new positive data
            if new_level2:
                (
                    profile.major.level2,
                    profile.major.level2_emotion,
                    profile.major.negative_level2,
                    profile.major.negative_level2_emotion,
                ) = _resolve_conflicts(
                    profile.major.level2,
                    profile.major.level2_emotion,
                    profile.major.negative_level2,
                    profile.major.negative_level2_emotion,
                    new_level2,
                )

            # Resolve conflicts for level3 only if we have new positive data
            if new_level3:
                (
                    profile.major.level3,
                    profile.major.level3_emotion,
                    profile.major.negative_level3,
                    profile.major.negative_level3_emotion,
                ) = _resolve_conflicts(
                    profile.major.level3,
                    profile.major.level3_emotion,
                    profile.major.negative_level3,
                    profile.major.negative_level3_emotion,
                    new_level3,
                )

            await self._save_profile(profile)
        except Exception as e:
            logger.error(f"Failed to update major intent: {e}")
            raise

    async def update_city_intent(self, positive_result: str, negative_result: str) -> None:
        """Update city intent from positive and negative extraction results.

        Expected JSON format for positive_result:
        {
            "province": ["北京市", "上海市"],
            "city": ["深圳市"],
            "area": ["华北", "华东"]
        }

        Expected JSON format for negative_result:
        {
            "province": ["西藏自治区"],
            "city": ["拉萨市"],
            "area": ["西北"]
        }
        """
        try:
            pos_data = json.loads(positive_result)
            neg_data = json.loads(negative_result)

            # Check if there's any valid data to update
            new_province = _normalize_string_list(pos_data.get("province", []))
            new_city = _normalize_string_list(pos_data.get("city", []))
            new_area = _normalize_string_list(pos_data.get("area", []))
            neg_province = _normalize_string_list(neg_data.get("province", []))
            neg_city = _normalize_string_list(neg_data.get("city", []))
            neg_area = _normalize_string_list(neg_data.get("area", []))

            if not any([new_province, new_city, new_area, neg_province, neg_city, neg_area]):
                logger.info("No valid city intent data to update, skipping")
                return

            profile = await self.get_current_profile()

            # Merge positive province
            if new_province:
                profile.city.province, profile.city.province_emotion = _merge_with_emotion(
                    profile.city.province,
                    profile.city.province_emotion,
                    new_province,
                    None,
                )

            # Merge positive city
            if new_city:
                profile.city.city, profile.city.city_emotion = _merge_with_emotion(
                    profile.city.city,
                    profile.city.city_emotion,
                    new_city,
                    None,
                )

            # Merge area (no emotion)
            if new_area:
                existing_area = set(_normalize_string_list(profile.city.area))
                profile.city.area = list(existing_area | set(_normalize_string_list(new_area)))

            # Merge negative province
            if neg_province:
                profile.city.negative_province, profile.city.negative_province_emotion = _merge_with_emotion(
                    profile.city.negative_province,
                    profile.city.negative_province_emotion,
                    neg_province,
                    None,
                )

            # Merge negative city
            if neg_city:
                profile.city.negative_city, profile.city.negative_city_emotion = _merge_with_emotion(
                    profile.city.negative_city,
                    profile.city.negative_city_emotion,
                    neg_city,
                    None,
                )

            # Merge negative area (no emotion)
            if neg_area:
                existing_neg_area = set(_normalize_string_list(profile.city.negative_area))
                profile.city.negative_area = list(existing_neg_area | set(_normalize_string_list(neg_area)))

            # Resolve conflicts for province only if we have new positive data
            if new_province:
                (
                    profile.city.province,
                    profile.city.province_emotion,
                    profile.city.negative_province,
                    profile.city.negative_province_emotion,
                ) = _resolve_conflicts(
                    profile.city.province,
                    profile.city.province_emotion,
                    profile.city.negative_province,
                    profile.city.negative_province_emotion,
                    new_province,
                )

            # Resolve conflicts for city only if we have new positive data
            if new_city:
                (
                    profile.city.city,
                    profile.city.city_emotion,
                    profile.city.negative_city,
                    profile.city.negative_city_emotion,
                ) = _resolve_conflicts(
                    profile.city.city,
                    profile.city.city_emotion,
                    profile.city.negative_city,
                    profile.city.negative_city_emotion,
                    new_city,
                )

            await self._save_profile(profile)
        except Exception:
            logger.exception("Failed to update city intent")
            raise

    async def _save_profile(self, profile: UserProfile) -> None:
        """Save profile to backend with code enrichment."""
        profile_dict = profile.to_backend_format()
        enriched = await add_codes_to_profile_async(profile_dict, self.batch)
        await save_user_profile(self.chat_session_id, enriched)
        logger.info(f"Profile saved for session {self.chat_session_id}")
