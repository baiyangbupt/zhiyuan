"""Profile manager service for incremental user profile updates."""

import json
from typing import Any
from loguru import logger

from app.domain.major_entity_resolver import (
    canonicalize_major_intent_payload,
    major_parent_mappings_for_batch,
)
from app.schemas.user_profile import UserProfile, SchoolIntent, MajorIntent, CityIntent
from app.util.internal_client import get_user_profile, save_user_profile, update_planning_explicit_profile
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


def _replace_with_emotion(
    new_values: list[str] | None,
    new_emotions: list[str] | None = None,
    default_emotion: str = "Strong",
) -> tuple[list[str], list[str]]:
    """Replace a value/emotion list while preserving order and de-duplicating."""
    values = _normalize_string_list(new_values)
    emotions = _normalize_string_list(new_emotions)
    if not values:
        return [], []
    if not emotions:
        emotions = [default_emotion] * len(values)
    if len(emotions) < len(values):
        emotions = [*emotions, *([default_emotion] * (len(values) - len(emotions)))]

    result_values: list[str] = []
    result_emotions: list[str] = []
    seen: set[str] = set()
    for value, emotion in zip(values, emotions):
        if value in seen:
            continue
        seen.add(value)
        result_values.append(value)
        result_emotions.append(emotion or default_emotion)
    return result_values, result_emotions


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


def _remove_conflicting_values(
    existing_values: list[str] | None,
    existing_emotions: list[str] | None,
    values_to_remove: list[str] | None,
    default_emotion: str = "Strong",
) -> tuple[list[str], list[str]]:
    existing_values = _normalize_string_list(existing_values)
    existing_emotions = _normalize_string_list(existing_emotions)
    values_to_remove = _normalize_string_list(values_to_remove)
    if not existing_values:
        return [], []
    existing_emotions = existing_emotions or [default_emotion] * len(existing_values)
    remove_set = set(values_to_remove)
    kept_values: list[str] = []
    kept_emotions: list[str] = []
    for value, emotion in zip(existing_values, existing_emotions):
        if value not in remove_set:
            kept_values.append(value)
            kept_emotions.append(emotion)
    return kept_values, kept_emotions


def _unique_texts(*groups: Any) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for value in _normalize_string_list(group):
            if value not in seen:
                values.append(value)
                seen.add(value)
    return values


_MAJOR_PROFILE_KEYS = (
    "level1",
    "level2",
    "level3",
    "negative_level1",
    "negative_level2",
    "negative_level3",
)


def _major_payload_from_profile(major: MajorIntent) -> dict[str, list[str]]:
    return {
        key: _normalize_string_list(getattr(major, key, []))
        for key in _MAJOR_PROFILE_KEYS
    }


def _assign_major_payload_to_profile(major: MajorIntent, payload: dict[str, Any] | None) -> None:
    payload = payload or {}
    for key in _MAJOR_PROFILE_KEYS:
        values = _normalize_string_list(payload.get(key))
        setattr(major, key, values)
        setattr(major, f"{key}_emotion", ["Strong"] * len(values))


def _normalize_major_profile_by_catalog(major: MajorIntent, batch: str) -> None:
    payload = canonicalize_major_intent_payload(_major_payload_from_profile(major), "", batch) or {}
    _assign_major_payload_to_profile(major, payload)


def _filter_major_values(
    values: list[str] | None,
    emotions: list[str] | None,
    should_remove,
) -> tuple[list[str], list[str]]:
    normalized_values = _normalize_string_list(values)
    normalized_emotions = _normalize_string_list(emotions) or ["Strong"] * len(normalized_values)
    kept_values: list[str] = []
    kept_emotions: list[str] = []
    for index, value in enumerate(normalized_values):
        emotion = normalized_emotions[index] if index < len(normalized_emotions) else "Strong"
        if should_remove(value):
            continue
        kept_values.append(value)
        kept_emotions.append(emotion)
    return kept_values, kept_emotions


def _resolve_major_hierarchy_conflicts(
    major: MajorIntent,
    new_payload: dict[str, Any] | None,
    batch: str,
) -> None:
    """Resolve positive/negative conflicts with official major hierarchy."""

    if not new_payload:
        return
    _normalize_major_profile_by_catalog(major, batch)
    mappings = major_parent_mappings_for_batch(batch)
    level3_to_level2 = mappings.get("level3_to_level2", {})
    level2_to_level1 = mappings.get("level2_to_level1", {})

    new_level1 = set(_normalize_string_list(new_payload.get("level1")))
    new_level2 = set(_normalize_string_list(new_payload.get("level2")))
    new_level3 = set(_normalize_string_list(new_payload.get("level3")))
    new_neg_level1 = set(_normalize_string_list(new_payload.get("negative_level1")))
    new_neg_level2 = set(_normalize_string_list(new_payload.get("negative_level2")))
    new_neg_level3 = set(_normalize_string_list(new_payload.get("negative_level3")))

    def level2_parent(value: str) -> str | None:
        return level2_to_level1.get(value)

    def level3_parent2(value: str) -> str | None:
        return level3_to_level2.get(value)

    def level3_parent1(value: str) -> str | None:
        parent2 = level3_parent2(value)
        return level2_to_level1.get(parent2 or "")

    new_level2_parents = {level2_parent(item) for item in new_level2}
    new_level3_parent2 = {level3_parent2(item) for item in new_level3}
    new_level3_parent1 = {level3_parent1(item) for item in new_level3}

    if new_level1 or new_level2 or new_level3:
        major.negative_level1, major.negative_level1_emotion = _filter_major_values(
            major.negative_level1,
            major.negative_level1_emotion,
            lambda value: value in new_level1 or value in new_level2_parents or value in new_level3_parent1,
        )
        major.negative_level2, major.negative_level2_emotion = _filter_major_values(
            major.negative_level2,
            major.negative_level2_emotion,
            lambda value: value in new_level2 or value in new_level3_parent2 or level2_parent(value) in new_level1,
        )
        major.negative_level3, major.negative_level3_emotion = _filter_major_values(
            major.negative_level3,
            major.negative_level3_emotion,
            lambda value: value in new_level3 or level3_parent2(value) in new_level2 or level3_parent1(value) in new_level1,
        )

    if new_neg_level1 or new_neg_level2 or new_neg_level3:
        major.level1, major.level1_emotion = _filter_major_values(
            major.level1,
            major.level1_emotion,
            lambda value: value in new_neg_level1,
        )
        major.level2, major.level2_emotion = _filter_major_values(
            major.level2,
            major.level2_emotion,
            lambda value: value in new_neg_level2 or level2_parent(value) in new_neg_level1,
        )
        major.level3, major.level3_emotion = _filter_major_values(
            major.level3,
            major.level3_emotion,
            lambda value: value in new_neg_level3
            or level3_parent2(value) in new_neg_level2
            or level3_parent1(value) in new_neg_level1,
        )


def _major_explicit_values(level1: Any, level2: Any, level3: Any) -> list[str]:
    return _unique_texts(level3, level2, level1)


def _is_success_response(response: Any) -> bool:
    if not isinstance(response, dict):
        return True
    if response.get("success") is False:
        return False
    if "code" in response:
        return response.get("code") in {0, "0"}
    return True


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

            if response and response.get("code", 0) == 0:
                data = response.get("data", {})
                # 新版返回 userprofile，历史接口/测试样本可能返回 dataValue。
                profile_data = data.get("userprofile") or data.get("dataValue")

                if not profile_data:
                    logger.warning("用户画像数据为空，返回默认空画像")
                    return UserProfile()

                logger.info(f"解析用户画像数据: {profile_data}")
                profile = UserProfile.from_backend_format(profile_data)
                _normalize_major_profile_by_catalog(profile.major, self.batch)
                return profile
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
            result = canonicalize_major_intent_payload(result, "", self.batch) or {}

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

            if new_neg:
                profile.school.colleges, profile.school.colleges_emotion = _remove_conflicting_values(
                    profile.school.colleges,
                    profile.school.colleges_emotion,
                    new_neg,
                )

            await self._save_profile(profile, sync_school=True)
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

            if new_neg_level1:
                profile.major.level1, profile.major.level1_emotion = _remove_conflicting_values(
                    profile.major.level1,
                    profile.major.level1_emotion,
                    new_neg_level1,
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

            if new_neg_level2:
                profile.major.level2, profile.major.level2_emotion = _remove_conflicting_values(
                    profile.major.level2,
                    profile.major.level2_emotion,
                    new_neg_level2,
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

            if new_neg_level3:
                profile.major.level3, profile.major.level3_emotion = _remove_conflicting_values(
                    profile.major.level3,
                    profile.major.level3_emotion,
                    new_neg_level3,
                )

            _resolve_major_hierarchy_conflicts(profile.major, result, self.batch)
            await self._save_profile(profile, sync_major=True)
        except Exception as e:
            logger.error(f"Failed to update major intent: {e}")
            raise

    async def replace_major_positive_intent(self, extraction_result: str) -> None:
        """Replace positive major intent with an exclusive selected scope.

        This is used for confirmed ``only_keep`` constraints. It deliberately
        does not merge with old positive major preferences; otherwise historical
        soft preferences continue to affect recommendation and review after the
        user has explicitly limited the scope.
        """
        try:
            result = json.loads(extraction_result)
            new_level1 = _normalize_string_list(result.get("level1", []))
            new_level2 = _normalize_string_list(result.get("level2", []))
            new_level3 = _normalize_string_list(result.get("level3", []))
            if not any([new_level1, new_level2, new_level3]):
                logger.info("No positive major intent data to replace, skipping")
                return

            profile = await self.get_current_profile()
            profile.major.level1, profile.major.level1_emotion = _replace_with_emotion(new_level1)
            profile.major.level2, profile.major.level2_emotion = _replace_with_emotion(new_level2)
            profile.major.level3, profile.major.level3_emotion = _replace_with_emotion(new_level3)

            all_positive = [*new_level1, *new_level2, *new_level3]
            if all_positive:
                profile.major.negative_level1, profile.major.negative_level1_emotion = _remove_conflicting_values(
                    profile.major.negative_level1,
                    profile.major.negative_level1_emotion,
                    all_positive,
                )
                profile.major.negative_level2, profile.major.negative_level2_emotion = _remove_conflicting_values(
                    profile.major.negative_level2,
                    profile.major.negative_level2_emotion,
                    all_positive,
                )
                profile.major.negative_level3, profile.major.negative_level3_emotion = _remove_conflicting_values(
                    profile.major.negative_level3,
                    profile.major.negative_level3_emotion,
                    all_positive,
                )

            _resolve_major_hierarchy_conflicts(profile.major, result, self.batch)
            await self._save_profile(profile, sync_major=True)
        except Exception as e:
            logger.error(f"Failed to replace major positive intent: {e}")
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

            if neg_province:
                profile.city.province, profile.city.province_emotion = _remove_conflicting_values(
                    profile.city.province,
                    profile.city.province_emotion,
                    neg_province,
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

            if neg_city:
                profile.city.city, profile.city.city_emotion = _remove_conflicting_values(
                    profile.city.city,
                    profile.city.city_emotion,
                    neg_city,
                )

            await self._save_profile(profile, sync_region=True)
        except Exception:
            logger.exception("Failed to update city intent")
            raise

    async def _save_profile(
        self,
        profile: UserProfile,
        *,
        sync_major: bool = False,
        sync_school: bool = False,
        sync_region: bool = False,
        sync_strength: bool = False,
    ) -> None:
        """Save profile to backend with code enrichment."""
        profile_dict = profile.to_backend_format()
        enriched = await add_codes_to_profile_async(profile_dict, self.batch)
        save_resp = await save_user_profile(self.chat_session_id, enriched)
        if not _is_success_response(save_resp):
            raise RuntimeError(f"save user profile failed: {save_resp}")
        explicit_payload: dict[str, Any] = {}
        if sync_major:
            explicit_payload["major_preferences"] = {
                "positive": _major_explicit_values(
                    profile.major.level1,
                    profile.major.level2,
                    profile.major.level3,
                ),
                "negative": _major_explicit_values(
                    profile.major.negative_level1,
                    profile.major.negative_level2,
                    profile.major.negative_level3,
                ),
            }
        if sync_school:
            explicit_payload["school_preferences"] = {
                "positive": _unique_texts(profile.school.colleges),
                "negative": _unique_texts(profile.school.negative_colleges),
            }
        if sync_region:
            explicit_payload["region_preferences"] = {
                "positive": _unique_texts(profile.city.province, profile.city.city),
                "negative": _unique_texts(profile.city.negative_province, profile.city.negative_city),
            }
        if sync_strength:
            explicit_payload["strength_subjects"] = _unique_texts(profile.strength_subjects)
        if explicit_payload:
            planning_resp = await update_planning_explicit_profile(self.chat_session_id, **explicit_payload)
            if not _is_success_response(planning_resp):
                raise RuntimeError(f"sync planning explicit profile failed: {planning_resp}")
        logger.info(f"Profile saved for session {self.chat_session_id}")
