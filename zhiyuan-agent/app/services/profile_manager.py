"""Profile manager service for incremental user profile updates."""

import asyncio
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

    Some backend or malformed profile payloads may contain dict items like
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
    """Normalize batch payload to the backend batch code string."""
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


# ── 确认成功后落库：同源意向并集并入 userprofile（排序输入通道）───────────────────
#
# 背景（2026-10-07 评审 §五-31a）：对话确认走的只有 planningState 的硬约束，
# userprofile（`add-extra-data` / KV `userprofile`）里的意向**没有**跟着更新——
# 排序侧（`recommendation.py` 读 `major_intent.level2_code` / `level3_code` 等）
# 就成了"看不见用户意向"的通道。这里在**确认成功之后**做一次同源并集写回。
#
# 四条口径（评审定稿）：
#   同源同值：只写这次确认里出现的名字，不改名、不扩写（仅按目录归位到层级）；
#   只并集：与既存画像取并集——`add-extra-data` 是**整串覆盖**，所以先严格读回、
#           合并、再整体写回；读不回来**不写**（宁可这次不落，也不能抹掉既有画像）；
#   正负互斥：同一对象不能在 include/exclude 两侧同时存在（正压负）；
#   值带 code：写回统一过 `add_codes_to_profile_async`（`_save_profile` 内）。
_CONFIRMED_MAJOR_KEYS = (
    "level1",
    "level2",
    "level3",
    "negative_level1",
    "negative_level2",
    "negative_level3",
)
_CONFIRMED_REGION_KEYS = (
    "province",
    "city",
    "area",
    "negative_province",
    "negative_city",
    "negative_area",
)

# 模型（`UserProfile`）**不承载**、但 KV 里确实存在的族：整串覆盖写回时必须原样带回，
# 否则确认后的并集写回会把这些既有字段置空（`to_backend_format` 对它们是 None）。
# 今天只有 tag 一族（排序侧读 `tag_info.values`）。
_UNMODELED_PROFILE_KEYS = ("tag_info", "negative_tag_info")

# 同一会话的"读-改-写"要串行：`add-extra-data` 整串覆盖，两条确认并发时
# 各自读回旧值再写，后写的那条会吃掉前一条的并集。
# 键里带事件循环身份：测试里每个用例一个 loop，锁不能跨 loop 复用（asyncio 会拒）。
_MERGE_LOCKS: dict[Any, Any] = {}


def _merge_lock(session_id: Any) -> asyncio.Lock:
    try:
        loop_key: Any = id(asyncio.get_running_loop())
    except RuntimeError:  # pragma: no cover —— 非 async 上下文才可能走到
        loop_key = 0
    key = (loop_key, session_id)
    lock = _MERGE_LOCKS.get(key)
    if lock is None:
        if len(_MERGE_LOCKS) >= 2048:
            for stale_key, candidate in list(_MERGE_LOCKS.items()):
                if not candidate.locked():
                    _MERGE_LOCKS.pop(stale_key, None)
        lock = asyncio.Lock()
        _MERGE_LOCKS[key] = lock
    return lock


def _normalize_confirmed_major_payload(payload: Any, batch: str) -> dict[str, list[str]]:
    """同源专业意向：去重 + 正压负 + 按目录归位到 level1/2/3（不认得的留在原层级）。"""
    if not isinstance(payload, dict):
        return {}
    raw = {key: _unique_texts(payload.get(key)) for key in _CONFIRMED_MAJOR_KEYS}
    positive = {name for key in ("level1", "level2", "level3") for name in raw[key]}
    for key in ("negative_level1", "negative_level2", "negative_level3"):
        raw[key] = [name for name in raw[key] if name not in positive]
    if not any(raw.values()):
        return {}
    canonical = canonicalize_major_intent_payload(raw, "", batch) or {}
    normalized = {key: _unique_texts(canonical.get(key)) for key in _CONFIRMED_MAJOR_KEYS}
    # 归位（别名/层级）之后再压一次同名：两侧永远不出现同一个对象。
    positive = {name for key in ("level1", "level2", "level3") for name in normalized[key]}
    result: dict[str, list[str]] = {}
    for key in _CONFIRMED_MAJOR_KEYS:
        values = normalized[key]
        if key.startswith("negative_"):
            values = [name for name in values if name not in positive]
        if values:
            result[key] = values
    return result


def _normalize_confirmed_school_payload(payload: Any) -> dict[str, list[str]]:
    """同源学校意向：去重 + 正压负（名字照旧，不改写）。"""
    if not isinstance(payload, dict):
        return {}
    positive = _unique_texts(payload.get("colleges"))
    positive_set = set(positive)
    negative = [name for name in _unique_texts(payload.get("negative_colleges")) if name not in positive_set]
    result: dict[str, list[str]] = {}
    if positive:
        result["colleges"] = positive
    if negative:
        result["negative_colleges"] = negative
    return result


def _normalize_confirmed_region_payload(payload: Any) -> dict[str, list[str]]:
    """同源区域意向：去重 + 正压负（省/市/区由上游定层，名字照旧）。"""
    if not isinstance(payload, dict):
        return {}
    raw = {key: _unique_texts(payload.get(key)) for key in _CONFIRMED_REGION_KEYS}
    positive = {name for key in ("province", "city", "area") for name in raw[key]}
    result: dict[str, list[str]] = {}
    for key in _CONFIRMED_REGION_KEYS:
        values = raw[key]
        if key.startswith("negative_"):
            values = [name for name in values if name not in positive]
        if values:
            result[key] = values
    return result


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

    async def _read_profile_strict(self) -> tuple[UserProfile, dict[str, Any]]:
        """严格读回画像：**读不到就抛**（绝不拿空画像去覆盖写回）。

        返回 (画像模型, 原始载荷)——原始载荷用于把模型不承载的键（tag 一族）带回去
        （`add-extra-data` 是整串覆盖；`get_current_profile` 读失败时返回空画像，
        直接沿用会把既有画像整串抹掉，所以确认后的并集写回必须 fail-closed，
        评审 §五-31a："add-extra-data 整串覆盖须 merge"）。
        """
        try:
            response = await get_user_profile(self.chat_session_id)
        except Exception as exc:  # noqa: BLE001 —— 读失败统一转成"这次不写"
            raise RuntimeError(f"read user profile failed: {exc}") from exc
        if not isinstance(response, dict) or not _is_success_response(response):
            raise RuntimeError(f"read user profile failed: {response}")
        data = response.get("data") if isinstance(response.get("data"), dict) else {}
        # 首次写入时没有这一键（不是错误）：返回空画像，写回即为首次建档。
        profile_data = data.get("userprofile") or data.get("dataValue")
        if not isinstance(profile_data, dict) or not profile_data:
            return UserProfile(), {}
        profile = UserProfile.from_backend_format(profile_data)
        _normalize_major_profile_by_catalog(profile.major, self.batch)
        return profile, profile_data

    def _merge_school_payload(self, profile: UserProfile, result: dict[str, Any]) -> None:
        """并集合并学校意向（正压负），只动 school 一族。"""
        new_colleges = result.get("colleges", [])
        new_neg = result.get("negative_colleges", [])

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

    def _merge_major_payload(self, profile: UserProfile, result: dict[str, Any]) -> None:
        """并集合并专业意向（按层级正压负 + 目录层级冲突清理），只动 major 一族。"""
        new_level1 = result.get("level1", [])
        new_level2 = result.get("level2", [])
        new_level3 = result.get("level3", [])
        new_neg_level1 = result.get("negative_level1", [])
        new_neg_level2 = result.get("negative_level2", [])
        new_neg_level3 = result.get("negative_level3", [])

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

    def _merge_region_payload(
        self,
        profile: UserProfile,
        pos_data: dict[str, Any],
        neg_data: dict[str, Any],
    ) -> None:
        """并集合并区域意向（正压负），只动 city 一族。"""
        new_province = _normalize_string_list(pos_data.get("province", []))
        new_city = _normalize_string_list(pos_data.get("city", []))
        new_area = _normalize_string_list(pos_data.get("area", []))
        neg_province = _normalize_string_list(neg_data.get("province", []))
        neg_city = _normalize_string_list(neg_data.get("city", []))
        neg_area = _normalize_string_list(neg_data.get("area", []))

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

    async def merge_confirmed_intents(
        self,
        *,
        major_intents: dict[str, Any] | None = None,
        school_intents: dict[str, Any] | None = None,
        region_intents: dict[str, Any] | None = None,
    ) -> list[str]:
        """把已确认的同源意向**并集**并入画像（读-改-写一次完成）。

        与 `update_major_intent` / `update_school_intent` / `update_city_intent` 的差别：
        只做并集（确认语义：用户说过的都算）、单次严格读 + 单次写（三条族合并进同一次
        `add-extra-data`，避免中途互踩）、读失败 fail-closed（见 `_read_profile_strict`）。
        返回更新的族（"major"/"school"/"region" 的子集）。
        """
        families: list[str] = []
        if major_intents:
            families.append("major")
        if school_intents:
            families.append("school")
        if region_intents:
            families.append("region")
        if not families:
            return []

        profile, raw = await self._read_profile_strict()

        if major_intents:
            self._merge_major_payload(profile, major_intents)
        if school_intents:
            self._merge_school_payload(profile, school_intents)
        if region_intents:
            self._merge_region_payload(
                profile,
                {
                    key: region_intents.get(key, [])
                    for key in ("province", "city", "area")
                },
                {
                    key: region_intents.get(f"negative_{key}", [])
                    for key in ("province", "city", "area")
                },
            )

        await self._save_profile(
            profile,
            sync_major="major" in families,
            sync_school="school" in families,
            sync_region="region" in families,
            preserve_payload=raw,
        )
        return families

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
            self._merge_school_payload(profile, result)
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
            self._merge_major_payload(profile, result)
            await self._save_profile(profile, sync_major=True)
        except Exception as e:
            logger.error(f"Failed to update major intent: {e}")
            raise

    async def replace_major_positive_intent(self, extraction_result: str) -> None:
        """Replace positive major intent with an exclusive selected scope.

        This is used for confirmed ``only_keep`` constraints. It deliberately
        does not merge with existing positive major preferences; otherwise historical
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
            self._merge_region_payload(profile, pos_data, neg_data)
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
        preserve_payload: dict[str, Any] | None = None,
    ) -> None:
        """Save profile to backend with code enrichment."""
        profile_dict = profile.to_backend_format()
        if preserve_payload:
            # 整串覆盖写回：模型不承载的键（tag 一族）从读回的载荷原样带回，避免被置空。
            for key in _UNMODELED_PROFILE_KEYS:
                stored = preserve_payload.get(key)
                if isinstance(stored, dict) and any(_normalize_string_list(stored.get("values"))):
                    profile_dict[key] = dict(stored)
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


async def merge_confirmed_intents_into_profile(
    chat_session_id: Any,
    *,
    batch: Any = "01",
    major_intents: Any = None,
    school_intents: Any = None,
    region_intents: Any = None,
) -> dict[str, Any]:
    """确认成功后把**同源意向**并集写入 userprofile（排序输入通道）。

    调用点（评审 §五-31a 定稿）：
      - 网关约束确认成功处（`app/gateway/conversation_actions.py` 的
        `apply_constraint_and_regenerate` 成功后）；
      - 工具确认成功处（`app/zhiyuan_agent/tools.py` 的 `_apply_intent_pending` 成功后）。

    约定：**从不抛异常、从不改主链路结果**——落库失败只留日志（主动作照旧成功）；
    非数字会话 id 直接跳过（后端画像接口以数字会话为准，旁路不能因此出错）；
    载荷里没有可归位的名字就不发请求（不空写）。
    """
    try:
        session_id: int = int(str(chat_session_id).strip())
    except (TypeError, ValueError):
        logger.debug(f"confirmed intents merge skipped: invalid session id {chat_session_id!r}")
        return {"applied": False, "reason": "invalid_session_id"}

    try:
        normalized_batch = _normalize_batch(batch)
        normalized_major = _normalize_confirmed_major_payload(major_intents, normalized_batch)
        normalized_school = _normalize_confirmed_school_payload(school_intents)
        normalized_region = _normalize_confirmed_region_payload(region_intents)
        if not (normalized_major or normalized_school or normalized_region):
            return {"applied": False, "reason": "no_confirmed_intents"}

        lock = _merge_lock(session_id)
        async with lock:
            manager = ProfileManager(session_id, normalized_batch)
            updated = await manager.merge_confirmed_intents(
                major_intents=normalized_major or None,
                school_intents=normalized_school or None,
                region_intents=normalized_region or None,
            )
    except Exception as exc:  # noqa: BLE001 —— 旁路失败绝不能影响主链路结果
        # 注意：异常文本可能含 `{}`，走 loguru 的占位符形式（不要把内容拼进模板）。
        logger.exception("confirmed intents merge into userprofile failed: {}", exc)
        return {"applied": False, "reason": "merge_failed", "error": str(exc)}

    logger.info(
        "confirmed intents merged into userprofile (session={} families={})",
        session_id,
        updated,
    )
    return {"applied": True, "updated": updated}
