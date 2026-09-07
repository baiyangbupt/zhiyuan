"""内部服务 HTTP 客户端，封装了 aiohttp 请求操作。

从 gaotu_zy_agent_plus 迁移，适配 pydantic-settings 配置管理。
"""

from __future__ import annotations

import random
import uuid
from typing import Any, Dict, List, Optional, Union

import aiohttp
from loguru import logger

from app.config import InternalServiceConfig


class HttpClient:
    """HTTP 客户端，封装了 aiohttp 请求操作。"""

    def __init__(self) -> None:
        config = InternalServiceConfig()
        # 支持逗号分隔的多个地址
        self.base_urls = [url.strip() for url in config.url.split(",")]
        self.default_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _get_random_base_url(self) -> str:
        """随机选择一个基础 URL。"""
        return random.choice(self.base_urls)

    async def get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        error_msg: str = "请求失败",
    ) -> Dict[str, Any]:
        """发送 GET 请求。

        Args:
            endpoint: API 端点路径（不包含 base_url）
            params: 查询参数
            headers: 请求头（如果提供，将与默认请求头合并）
            error_msg: 错误信息前缀

        Returns:
            服务器返回的 JSON 响应。
        """
        base_url = self._get_random_base_url()
        url = f"{base_url}{endpoint}"
        merged_headers = {**self.default_headers}
        if headers:
            merged_headers.update(headers)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, params=params, headers=merged_headers
                ) as response:
                    result = await response.json()
                    if response.status != 200:
                        logger.error(f"{error_msg}: {response.status}, {result}")
                    return result
        except Exception as e:
            logger.error(f"{error_msg}异常: {e}")
            return {"error": str(e), "success": False, "data": {}}

    async def post(
        self,
        endpoint: str,
        json_data: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
        error_msg: str = "请求失败",
    ) -> Dict[str, Any]:
        """发送 POST 请求。

        Args:
            endpoint: API 端点路径（不包含 base_url）
            json_data: 请求体数据，将被序列化为 JSON
            headers: 请求头（如果提供，将与默认请求头合并）
            error_msg: 错误信息前缀

        Returns:
            服务器返回的 JSON 响应。
        """
        base_url = self._get_random_base_url()
        url = f"{base_url}{endpoint}"
        merged_headers = {**self.default_headers}
        if headers:
            merged_headers.update(headers)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=json_data, headers=merged_headers
                ) as response:
                    result = await response.json()
                    if response.status != 200:
                        logger.error(f"{error_msg}: {response.status}, {result}")
                    return result
        except Exception as e:
            logger.error(f"{error_msg}异常: {e}")
            return {"error": str(e), "success": False}

    async def delete(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        error_msg: str = "请求失败",
    ) -> Dict[str, Any]:
        """发送 DELETE 请求。"""
        base_url = self._get_random_base_url()
        url = f"{base_url}{endpoint}"
        merged_headers = {**self.default_headers}
        if headers:
            merged_headers.update(headers)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.delete(
                    url, params=params, headers=merged_headers
                ) as response:
                    result = await response.json()
                    if response.status != 200:
                        logger.error(f"{error_msg}: {response.status}, {result}")
                    return result
        except Exception as e:
            logger.error(f"{error_msg}异常: {e}")
            return {"error": str(e), "success": False}

    async def put(
        self,
        endpoint: str,
        json_data: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
        error_msg: str = "请求失败",
    ) -> Dict[str, Any]:
        """发送 PUT 请求。

        Args:
            endpoint: API 端点路径（不包含 base_url）
            json_data: 请求体数据，将被序列化为 JSON
            headers: 请求头（如果提供，将与默认请求头合并）
            error_msg: 错误信息前缀

        Returns:
            服务器返回的 JSON 响应。
        """
        base_url = self._get_random_base_url()
        url = f"{base_url}{endpoint}"
        merged_headers = {**self.default_headers}
        if headers:
            merged_headers.update(headers)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.put(
                    url, json=json_data, headers=merged_headers
                ) as response:
                    result = await response.json()
                    if response.status != 200:
                        logger.error(f"{error_msg}: {response.status}, {result}")
                    return result
        except Exception as e:
            logger.error(f"{error_msg}异常: {e}")
            return {"error": str(e), "success": False}

    async def patch(
        self,
        endpoint: str,
        json_data: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
        error_msg: str = "请求失败",
    ) -> Dict[str, Any]:
        """发送 PATCH 请求。"""
        base_url = self._get_random_base_url()
        url = f"{base_url}{endpoint}"
        merged_headers = {**self.default_headers}
        if headers:
            merged_headers.update(headers)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.patch(
                    url, json=json_data, headers=merged_headers
                ) as response:
                    result = await response.json()
                    if response.status != 200:
                        logger.error(f"{error_msg}: {response.status}, {result}")
                    return result
        except Exception as e:
            logger.error(f"{error_msg}异常: {e}")
            return {"error": str(e), "success": False}


# ── 全局 HTTP 客户端实例 ──────────────────────────────────────────
http_client = HttpClient()


async def register_codex_thread_binding(
    tenant_id: Union[str, int], binding: Dict[str, Any]
) -> Dict[str, Any]:
    """Register a gateway-owned Codex thread binding with the backend."""
    return await http_client.post(
        endpoint=f"/gaotu-assistant-bot/inner/codex/{tenant_id}/thread-binding",
        json_data=dict(binding),
        error_msg="注册 Codex thread binding 失败",
    )


async def revoke_codex_thread_binding(
    tenant_id: Union[str, int], thread_id: Union[str, int]
) -> Dict[str, Any]:
    """Revoke the binding for a Codex thread."""
    return await http_client.delete(
        endpoint=f"/gaotu-assistant-bot/inner/codex/{tenant_id}/thread-binding",
        params={"threadId": thread_id},
        error_msg="撤销 Codex thread binding 失败",
    )


async def resolve_codex_thread_binding(
    tenant_id: Union[str, int], binding: Dict[str, Any]
) -> Dict[str, Any]:
    """Resolve a trusted server-side context for a Codex thread."""
    return await http_client.post(
        endpoint=f"/gaotu-assistant-bot/inner/codex/{tenant_id}/thread-binding/resolve",
        json_data=dict(binding),
        error_msg="解析 Codex thread binding 失败",
    )


def _pending_resource_data(response: Dict[str, Any] | None) -> Dict[str, Any]:
    data = (response or {}).get("data")
    return data if isinstance(data, dict) else {}


def _pending_revision(data_value: Dict[str, Any] | None) -> int:
    if not isinstance(data_value, dict):
        return 0
    for key in ("_pendingRevision", "revision"):
        try:
            value = int(data_value.get(key) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return value
    return 0


def _pending_claim_token(data_value: Dict[str, Any] | None) -> str:
    if not isinstance(data_value, dict):
        return ""
    return str(data_value.get("_pendingClaimToken") or data_value.get("claimToken") or "").strip()


async def _get_pending_resource(chat_session_id: Union[str, int]) -> Dict[str, Any]:
    return await http_client.get(
        endpoint="/gaotu-assistant-bot/inner/chat/1/session/pending",
        params={"chatSessionId": chat_session_id},
        error_msg="获取待确认资源失败",
    )


# ── 消息相关 ──────────────────────────────────────────────────────


async def get_all_messages(thread_id: str) -> Dict[str, Any]:
    """异步获取聊天会话的所有消息。

    Args:
        thread_id: 会话 ID

    Returns:
        服务器返回的 JSON 响应数据，包含所有消息。
    """
    return await http_client.get(
        endpoint="/gaotu-assistant-bot/inner/chat/1/message/list-all",
        params={"chatSessionId": thread_id},
        error_msg="获取消息失败",
    )


async def create_chat_session(
    tenant_id: Union[str, int],
    create_session_req: Dict[str, Any],
    *,
    tk: str,
    pf: str,
) -> Dict[str, Any]:
    """Create a real chat session through the backend public API.

    Args:
        tenant_id: tenant id in the public chat route
        create_session_req: raw CreateSessionReq payload
        tk: authenticated login token
        pf: platform enum name expected by backend, e.g. ``WEB`` / ``APP``
    """
    return await http_client.post(
        endpoint=f"/gaotu-assistant-bot/chat/{tenant_id}/session/create",
        json_data=create_session_req,
        headers={
            "tk": str(tk or "").strip(),
            "pf": str(pf or "").strip(),
        },
        error_msg="创建真实会话失败",
    )


async def update_session_tuition_range(
    thread_id: Union[str, int],
    *,
    min_tuition: int = 0,
    max_tuition: int,
) -> Dict[str, Any]:
    """Update the session tuition range used by candidate filtering."""
    return await http_client.post(
        endpoint=f"/gaotu-assistant-bot/inner/chat/1/session/update-tuition-range?chatSessionId={thread_id}",
        json_data={"min": int(min_tuition or 0), "max": int(max_tuition)},
        error_msg="更新会话学费区间失败",
    )


async def catalog_lookup_school(name: str) -> Dict[str, Any]:
    return await http_client.get(
        endpoint="/gaotu-assistant-bot/inner/catalog/lookup/school",
        params={"name": name},
        error_msg="catalog 查询学校失败",
    )


async def catalog_lookup_major(name: str, education_level: Optional[str] = None) -> Dict[str, Any]:
    params: Dict[str, Any] = {"name": name}
    if education_level:
        params["educationLevel"] = education_level
    return await http_client.get(
        endpoint="/gaotu-assistant-bot/inner/catalog/lookup/major",
        params=params,
        error_msg="catalog 查询专业失败",
    )


async def catalog_lookup_major_category(name: str, education_level: Optional[str] = None) -> Dict[str, Any]:
    params: Dict[str, Any] = {"name": name}
    if education_level:
        params["educationLevel"] = education_level
    return await http_client.get(
        endpoint="/gaotu-assistant-bot/inner/catalog/lookup/major-category",
        params=params,
        error_msg="catalog 查询专业大类失败",
    )


async def catalog_lookup_major_discipline(name: str, education_level: Optional[str] = None) -> Dict[str, Any]:
    params: Dict[str, Any] = {"name": name}
    if education_level:
        params["educationLevel"] = education_level
    return await http_client.get(
        endpoint="/gaotu-assistant-bot/inner/catalog/lookup/major-discipline",
        params=params,
        error_msg="catalog 查询专业门类失败",
    )


async def catalog_lookup_province(name: str) -> Dict[str, Any]:
    return await http_client.get(
        endpoint="/gaotu-assistant-bot/inner/catalog/lookup/province",
        params={"name": name},
        error_msg="catalog 查询省份失败",
    )


async def catalog_lookup_city(name: str) -> Dict[str, Any]:
    return await http_client.get(
        endpoint="/gaotu-assistant-bot/inner/catalog/lookup/city",
        params={"name": name},
        error_msg="catalog 查询城市失败",
    )


async def catalog_search_major(keyword: str, education_level: Optional[str] = None) -> Dict[str, Any]:
    params: Dict[str, Any] = {"keyword": keyword}
    if education_level:
        params["educationLevel"] = education_level
    return await http_client.get(
        endpoint="/gaotu-assistant-bot/inner/catalog/search/major",
        params=params,
        error_msg="catalog 搜索专业失败",
    )


async def catalog_list_schools(
    *,
    province: Optional[str] = None,
    city: Optional[str] = None,
    school_type: Optional[str] = None,
    ownership: Optional[str] = None,
    education_level: Optional[str] = None,
) -> Any:
    params = {
        key: value
        for key, value in {
            "province": province,
            "city": city,
            "schoolType": school_type,
            "ownership": ownership,
            "educationLevel": education_level,
        }.items()
        if value
    }
    return await http_client.get(
        endpoint="/gaotu-assistant-bot/inner/school/search/advanced",
        params=params,
        error_msg="catalog 查询学校列表失败",
    )


async def catalog_tree_filter_tags() -> Dict[str, Any]:
    return await http_client.get(
        endpoint="/gaotu-assistant-bot/inner/catalog/tree/filter-tags",
        error_msg="catalog 查询筛选标签树失败",
    )


async def get_message_by_id(message_id: Union[str, int]) -> Dict[str, Any]:
    """异步根据 ID 获取消息信息。"""
    params = {"messageId": message_id}
    return await http_client.get(
        endpoint="/gaotu-assistant-bot/inner/chat/1/message/get-by-id",
        params=params,
        error_msg="根据 ID 获取消息失败",
    )


async def save_message(
    chat_session_id: Union[str, int],
    content: Union[str, Dict[str, Any]],
    message_from: str,
    content_type: str = "TEXT",
    meeting_id: int = 1,
) -> Dict[str, Any]:
    """异步保存聊天消息。"""
    payload = {
        "chatSessionId": chat_session_id,
        "content": content,
        "contentType": content_type,
        "meetingId": meeting_id,
        "messageFrom": message_from,
    }
    return await http_client.post(
        endpoint="/gaotu-assistant-bot/inner/chat/1/message/save",
        json_data=payload,
        error_msg="保存消息失败",
    )


async def update_message(
    message_id: Union[str, int],
    chat_session_id: Union[str, int],
    content: Union[str, Dict[str, Any]],
    message_from: str,
    content_type: str = "TEXT",
    meeting_id: int = 1,
) -> Dict[str, Any]:
    """异步更新聊天消息。"""
    payload = {
        "id": message_id,
        "chatSessionId": chat_session_id,
        "content": content,
        "contentType": content_type,
        "meetingId": meeting_id,
        "messageFrom": message_from,
    }
    return await http_client.post(
        endpoint="/gaotu-assistant-bot/inner/chat/1/message/save",
        json_data=payload,
        error_msg="更新消息失败",
    )


# ── 会话相关 ──────────────────────────────────────────────────────


async def create_session(
    bot_id: int, form_id: int, member_id: int
) -> Dict[str, Any]:
    """异步创建聊天会话。"""
    payload = {"botId": bot_id, "formId": form_id, "memberId": member_id}
    return await http_client.post(
        endpoint="/gaotu-assistant-bot/inner/chat/1/session/create",
        json_data=payload,
        error_msg="创建会话失败",
    )


# ── Extra Data 通用读写 ──────────────────────────────────────────


async def get_last_extra_data(
    chat_session_id: Union[str, int], key: str
) -> Dict[str, Any]:
    """异步获取指定 key 的最新版本额外数据。"""
    params = {"chatSessionId": chat_session_id, "key": key}
    return await http_client.get(
        endpoint="/gaotu-assistant-bot/inner/chat/1/session/get-extra-data-last-version",
        params=params,
        error_msg="获取额外数据失败",
    )


async def get_extra_data(
    chat_session_id: Union[str, int],
    key_list: Union[List[str], str],
    version: int = 0,
) -> Dict[str, Any]:
    """异步获取额外数据。

    Args:
        chat_session_id: 会话 ID
        key_list: 数据键列表，可以是字符串列表或以逗号分隔的字符串
        version: 数据版本号
    """
    if isinstance(key_list, list):
        key_list_str = ",".join(key_list)
    else:
        key_list_str = key_list

    params = {
        "chatSessionId": chat_session_id,
        "keyList": key_list_str,
        "version": version,
    }
    return await http_client.get(
        endpoint="/gaotu-assistant-bot/inner/chat/1/session/get-extra-data",
        params=params,
        error_msg="获取额外数据失败",
    )


# ── 消息分析进度 ──────────────────────────────────────────────────


async def get_message_analyze_progress(
    chat_session_id: str,
) -> Dict[str, Any]:
    return await get_extra_data(chat_session_id, "messageAnalyzeProgress")


async def save_message_analyze_progress(
    chat_session_id: str, data_value: Dict[str, Any]
) -> Dict[str, Any]:
    payload = {
        "chatSessionId": chat_session_id,
        "dataKey": "messageAnalyzeProgress",
        "dataType": "JSON_OBJECT",
        "dataValue": data_value,
        "version": 0,
    }
    return await http_client.post(
        endpoint="/gaotu-assistant-bot/inner/chat/1/session/add-extra-data",
        json_data=payload,
        error_msg="存储消息分析进度失败",
    )


# ── 用户画像 ──────────────────────────────────────────────────────


async def save_user_profile(
    chat_session_id: int,
    data_value: Dict[str, Any],
    version: int = 0,
) -> Dict[str, Any]:
    """异步存储用户画像数据。"""
    payload = {
        "chatSessionId": chat_session_id,
        "dataKey": "userprofile",
        "dataType": "JSON_OBJECT",
        "dataValue": data_value,
        "version": version,
    }
    logger.info("存储用户画像: {}", payload)
    return await http_client.post(
        endpoint="/gaotu-assistant-bot/inner/chat/1/session/add-extra-data",
        json_data=payload,
        error_msg="存储用户画像失败",
    )


async def get_user_profile(
    chat_session_id: Union[str, int], version: int = 0
) -> Dict[str, Any]:
    """异步获取用户画像数据。"""
    return await get_extra_data(chat_session_id, "userprofile", version)


async def get_user_init_profile(thread_id: Union[str, int]) -> Dict[str, Any]:
    """获取用户的初始画像。"""
    return await get_extra_data(thread_id, "userInitProfile")


async def get_user_score_detail(thread_id: Union[str, int]) -> Dict[str, Any]:
    """获取用户的成绩详情。"""
    return await get_extra_data(thread_id, "userScoreDetail")


async def get_planning_state(thread_id: Union[str, int]) -> Dict[str, Any]:
    """获取统一 planningState。"""
    return await http_client.get(
        endpoint="/gaotu-assistant-bot/inner/planning/1/session/state",
        params={"chatSessionId": thread_id},
        error_msg="获取 planningState 失败",
    )


async def get_planning_workspace_state(thread_id: Union[str, int]) -> Dict[str, Any]:
    """获取工作台轻量 planningState。"""
    return await http_client.get(
        endpoint="/gaotu-assistant-bot/inner/planning/1/session/workspace-state",
        params={"chatSessionId": thread_id},
        error_msg="获取 planning workspaceState 失败",
    )


async def update_planning_explicit_profile(
    thread_id: Union[str, int],
    major_preferences: Optional[Dict[str, list[str]]] = None,
    school_preferences: Optional[Dict[str, list[str]]] = None,
    region_preferences: Optional[Dict[str, list[str]]] = None,
    strength_subjects: Optional[list[str]] = None,
) -> Dict[str, Any]:
    """更新 planning 显式画像。"""
    payload: Dict[str, Any] = {}
    if major_preferences is not None:
        payload["majorPreferences"] = major_preferences
    if school_preferences is not None:
        payload["schoolPreferences"] = school_preferences
    if region_preferences is not None:
        payload["regionPreferences"] = region_preferences
    if strength_subjects is not None:
        payload["strengthSubjects"] = strength_subjects
    return await http_client.patch(
        endpoint=f"/gaotu-assistant-bot/inner/planning/1/session/profile/explicit?chatSessionId={thread_id}",
        json_data=payload,
        error_msg="更新 planning 显式画像失败",
    )


async def update_planning_constraint_state(
    thread_id: Union[str, int],
    intent_mode: str = "preference",
    major_preferences: Optional[Dict[str, list[str]]] = None,
    school_preferences: Optional[Dict[str, list[str]]] = None,
    region_preferences: Optional[Dict[str, list[str]]] = None,
) -> Dict[str, Any]:
    """更新 planning 软偏好/硬约束状态。"""
    payload: Dict[str, Any] = {"intentMode": intent_mode or "preference"}
    if major_preferences is not None:
        payload["majorPreferences"] = major_preferences
    if school_preferences is not None:
        payload["schoolPreferences"] = school_preferences
    if region_preferences is not None:
        payload["regionPreferences"] = region_preferences
    return await http_client.patch(
        endpoint=f"/gaotu-assistant-bot/inner/planning/1/session/constraints?chatSessionId={thread_id}",
        json_data=payload,
        error_msg="更新 planning 约束状态失败",
    )


async def update_planning_physical_constraints(
    thread_id: Union[str, int],
    special_limits: Optional[list[str]] = None,
) -> Dict[str, Any]:
    """更新 planning 身体/特殊限制状态。"""
    payload: Dict[str, Any] = {}
    if special_limits is not None:
        payload["specialLimits"] = special_limits
    return await http_client.patch(
        endpoint=f"/gaotu-assistant-bot/inner/planning/1/session/profile/physical?chatSessionId={thread_id}",
        json_data=payload,
        error_msg="更新 planning 特殊限制失败",
    )


async def update_planning_latent_profile(
    thread_id: Union[str, int],
    future_development: Optional[Dict[str, Any]] = None,
    interest_personality: Optional[Dict[str, Any]] = None,
    family_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """更新 planning latent profile。"""
    payload: Dict[str, Any] = {}
    if future_development is not None:
        payload["futureDevelopment"] = future_development
    if interest_personality is not None:
        payload["interestPersonality"] = interest_personality
    if family_context is not None:
        payload["familyContext"] = family_context
    return await http_client.patch(
        endpoint=f"/gaotu-assistant-bot/inner/planning/1/session/profile/latent?chatSessionId={thread_id}",
        json_data=payload,
        error_msg="更新 planning latent profile 失败",
    )


async def mark_planning_intent_change_stale(
    thread_id: Union[str, int],
    intent_mode: str = "preference",
) -> Dict[str, Any]:
    """标记意向采纳后的 planning stale flags。"""
    return await http_client.post(
        endpoint=f"/gaotu-assistant-bot/inner/planning/1/session/intent-change/stale?chatSessionId={thread_id}",
        json_data={"intentMode": intent_mode or "preference"},
        error_msg="标记 planning 意向变更过期失败",
    )


async def list_planning_review_rules(tenant_id: Union[str, int] = 1) -> Dict[str, Any]:
    """获取后端权威审查规则元数据。"""
    return await http_client.get(
        endpoint=f"/gaotu-assistant-bot/inner/planning/{tenant_id}/review/rules",
        error_msg="获取规划审查规则失败",
    )


async def generate_planning_fix_proposals(
    tenant_id: Union[str, int],
    chat_session_id: Union[str, int],
) -> Dict[str, Any]:
    """生成后端统一风险修复建议。"""
    return await http_client.post(
        endpoint=(
            f"/gaotu-assistant-bot/inner/planning/{tenant_id}/session/fix-proposals/generate"
            f"?chatSessionId={chat_session_id}"
        ),
        json_data={},
        error_msg="生成规划修复建议失败",
    )


async def generate_user_goal_planning_fix_proposals(
    tenant_id: Union[str, int],
    chat_session_id: Union[str, int],
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """按结构化用户复合目标生成后端方案调整提案。"""
    return await http_client.post(
        endpoint=(
            f"/gaotu-assistant-bot/inner/planning/{tenant_id}/session/fix-proposals/user-goal/generate"
            f"?chatSessionId={chat_session_id}"
        ),
        json_data=payload or {},
        error_msg="生成用户目标方案调整预览失败",
    )


async def apply_planning_fix_proposal(
    tenant_id: Union[str, int],
    chat_session_id: Union[str, int],
    proposal_id: str,
    source_version_guard: int,
    regenerate_ordered_plan: bool = True,
    rerun_review: bool = True,
    proposal_source: str = "review_check",
    user_goal_request: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """应用后端统一方案处理建议。"""
    payload: Dict[str, Any] = {
        "proposalId": proposal_id,
        "proposalSource": proposal_source or "review_check",
        "sourceVersionGuard": source_version_guard,
        "regenerateOrderedPlan": regenerate_ordered_plan,
        "rerunReview": rerun_review,
    }
    if user_goal_request:
        payload["userGoalRequest"] = user_goal_request
    return await http_client.post(
        endpoint=(
            f"/gaotu-assistant-bot/inner/planning/{tenant_id}/session/fix-proposals/apply"
            f"?chatSessionId={chat_session_id}"
        ),
        json_data=payload,
        error_msg="应用规划修复建议失败",
    )


async def get_working_plan(thread_id: Union[str, int]) -> Dict[str, Any]:
    """获取当前统一规划方案。"""
    return await http_client.get(
        endpoint="/gaotu-assistant-bot/inner/planning/1/session/working-plan",
        params={"chatSessionId": thread_id},
        error_msg="获取方案失败",
    )


async def get_planning_ordered_plan(thread_id: Union[str, int]) -> Dict[str, Any]:
    """获取当前统一规划排序方案。"""
    return await http_client.get(
        endpoint="/gaotu-assistant-bot/inner/planning/1/session/ordered-plan",
        params={"chatSessionId": thread_id},
        error_msg="获取排序方案失败",
    )


async def move_planning_ordered_item(
    thread_id: Union[str, int],
    volunteer_id: str,
    target_position: int,
) -> Dict[str, Any]:
    """移动统一规划排序项。"""
    return await http_client.post(
        endpoint=f"/gaotu-assistant-bot/inner/planning/1/session/ordered-plan/move?chatSessionId={thread_id}",
        json_data={
            "volunteerId": volunteer_id,
            "targetPosition": target_position,
        },
        error_msg="移动排序项失败",
    )


async def remove_working_plan_items(
    thread_id: Union[str, int],
    volunteer_ids: list[str],
) -> Dict[str, Any]:
    """将志愿移出统一规划方案。"""
    return await http_client.post(
        endpoint=f"/gaotu-assistant-bot/inner/planning/1/session/working-plan/remove?chatSessionId={thread_id}",
        json_data={"volunteerIds": volunteer_ids},
        error_msg="移出方案失败",
    )


async def ban_working_plan_items(
    thread_id: Union[str, int],
    volunteer_ids: list[str],
) -> Dict[str, Any]:
    """禁用统一规划候选项并同步移出方案。"""
    return await http_client.post(
        endpoint=f"/gaotu-assistant-bot/inner/planning/1/session/working-plan/ban?chatSessionId={thread_id}",
        json_data={"volunteerIds": volunteer_ids},
        error_msg="禁用方案候选失败",
    )


# ── 对话状态 ──────────────────────────────────────────────────────


async def save_chat_profile(
    chat_session_id: int,
    data_value: Dict[str, Any],
    version: int = 0,
) -> Dict[str, Any]:
    """异步存储对话状态数据。"""
    payload = {
        "chatSessionId": chat_session_id,
        "dataKey": "chatprofile",
        "dataType": "JSON_OBJECT",
        "dataValue": data_value,
        "version": version,
    }
    logger.info("存储对话数据: {}", payload)
    return await http_client.post(
        endpoint="/gaotu-assistant-bot/inner/chat/1/session/add-extra-data",
        json_data=payload,
        error_msg="存储对话数据失败",
    )


async def get_last_chat_profile_version(
    chat_session_id: Union[str, int],
) -> int:
    """异步获取对话信息最新版本号。"""
    result = await get_last_extra_data(chat_session_id, "chatprofile")
    return result.get("data", {}).get("dataVersion", 0)


async def get_chat_profile(
    chat_session_id: Union[str, int], version: int = 0
) -> Dict[str, Any]:
    """异步获取对话信息数据。"""
    return await get_extra_data(chat_session_id, "chatprofile", version)


async def get_session_situation(
    chat_session_id: Union[str, int],
) -> Dict[str, Any]:
    """异步获取会话情况。"""
    return await get_extra_data(chat_session_id, "sessionSituation")


# ── 推荐相关 ──────────────────────────────────────────────────────


async def get_last_school_recommend_version(
    chat_session_id: Union[str, int],
) -> int:
    """获取学校推荐最新版本号。"""
    result = await get_last_extra_data(chat_session_id, "schoolRecommend")
    logger.info("获取学校推荐数据: {}", result)
    return result.get("data", {}).get("dataVersion", 0)


async def get_last_major_recommend_version(
    chat_session_id: Union[str, int],
) -> int:
    """获取专业推荐最新版本号。"""
    result = await get_last_extra_data(chat_session_id, "majorRecommend")
    logger.info("获取专业推荐数据: {}", result)
    return result.get("data", {}).get("dataVersion", 0)


async def get_last_baike_recommend_version(
    chat_session_id: Union[str, int],
) -> int:
    """获取推荐百科最新版本号。"""
    result = await get_last_extra_data(chat_session_id, "baikeRecommend")
    logger.info("获取对话百科版本: {}", result)
    return result.get("data", {}).get("dataVersion", 0)

async def get_major_profile_by_name(major_name: str) -> Dict[str, Any]:
    """
    根据专业名称获取专业相关信息

    Args:
        major_name: 专业名称，例如 "软件工程"

    Returns:
        Dict[str, Any]: 服务器返回的JSON响应数据，包含专业相关信息
    """
    params = {
        "name": major_name
    }

    logger.info("获取专业信息: {}", major_name)

    return await http_client.get(
        endpoint="/gaotu-assistant-bot/inner/major/getMajorProfileByName",
        params=params,
        error_msg="获取专业信息失败"
    )

async def get_major_category_profile_by_name(category_name: str) -> Dict[str, Any]:
    """
    根据专业类名获取专业类信息

    Args:
        category_name: 专业类名，例如 "哲学类"

    Returns:
        Dict[str, Any]: 服务器返回的JSON响应数据，包含专业类相关信息
    """
    params = {
        "categoryName": category_name
    }

    logger.info("获取专业类信息: {}", category_name)

    return await http_client.get(
        endpoint="/gaotu-assistant-bot/inner/major-category/getMajorCategoryProfileByName",
        params=params,
        error_msg="获取专业类信息失败"
    )


async def get_major_recommend(
    chat_session_id: Union[str, int], version: int = 0
) -> Dict[str, Any]:
    """异步获取专业推荐数据。"""
    return await get_extra_data(chat_session_id, "majorRecommend", version)


async def get_majors_recommend(
    tenant_id: Union[str, int],
    chat_session_id: Union[str, int],
) -> Dict[str, Any]:
    """异步获取专业推荐。"""
    params = {"tenantId": tenant_id, "chatSessionId": chat_session_id}
    logger.info("获取专业推荐 - 租户ID: {}, 会话ID: {}", tenant_id, chat_session_id)
    return await http_client.get(
        endpoint="/gaotu-assistant-bot/inner/recommend/majors",
        params=params,
        error_msg="获取专业推荐失败",
    )


async def get_school_majors_recommend(
    tenant_id: Union[str, int],
    chat_session_id: Union[str, int],
    use_truncated_logic: bool = True,
) -> Dict[str, Any]:
    """异步获取学校专业推荐。"""
    params = {
        "tenantId": tenant_id,
        "chatSessionId": chat_session_id,
        "useTruncatedLogic": str(use_truncated_logic).lower(),
    }
    logger.info(
        "获取学校专业推荐 - 租户ID: {}, 会话ID: {}, 使用截断逻辑: {}",
        tenant_id,
        chat_session_id,
        use_truncated_logic,
    )
    return await http_client.get(
        endpoint="/gaotu-assistant-bot/inner/recommend/schoolMajors",
        params=params,
        error_msg="获取学校专业推荐失败",
    )


# ── 待确认卡片 ────────────────────────────────────────────────────


async def save_pending_confirmation(
    chat_session_id: Union[str, int],
    data_value: Dict[str, Any],
) -> Dict[str, Any]:
    """Create/replace or finalize the dedicated pending resource."""
    status = str(data_value.get("status") or "active").strip().lower()
    pending_id = str(data_value.get("pendingId") or data_value.get("pending_id") or "").strip()
    expected_revision = _pending_revision(data_value)
    current_response: Dict[str, Any] = {}
    if expected_revision <= 0:
        current_response = await _get_pending_resource(chat_session_id)
        current = _pending_resource_data(current_response)
        current_pending_id = str(current.get("pendingId") or "").strip()
        current_revision = _pending_revision(current)
        if current_pending_id == pending_id or status == "active":
            expected_revision = current_revision

    if status != "active":
        action_by_status = {
            "applying": "confirm",
            "applied": "complete",
            "cancelled": "cancel",
            "expired": "expire",
            "failed": "fail",
        }
        action = action_by_status.get(status)
        if not action:
            return {"code": 40001, "msg": f"unsupported pending status: {status}"}
        return await resolve_pending_confirmation(
            chat_session_id,
            pending_id=pending_id,
            expected_revision=expected_revision,
            action=action,
            claim_token=_pending_claim_token(data_value),
            result_code=str(data_value.get("resultCode") or "").strip(),
            data_value=data_value,
        )

    payload = {
        "chatSessionId": chat_session_id,
        "pendingId": pending_id,
        "expectedRevision": expected_revision,
        "kind": data_value.get("kind"),
        "actionFamily": data_value.get("actionFamily") or data_value.get("action_family"),
        "dataValue": data_value,
    }
    logger.info("存储待确认卡片状态: {}", payload)
    return await http_client.post(
        endpoint="/gaotu-assistant-bot/inner/chat/1/session/pending",
        json_data=payload,
        error_msg="存储待确认卡片状态失败",
    )


async def resolve_pending_confirmation(
    chat_session_id: Union[str, int],
    *,
    pending_id: str,
    expected_revision: int,
    action: str,
    claim_token: str = "",
    result_code: str = "",
    data_value: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "chatSessionId": chat_session_id,
        "pendingId": pending_id,
        "expectedRevision": expected_revision,
        "action": action,
    }
    if result_code:
        payload["resultCode"] = result_code
    if claim_token:
        payload["claimToken"] = claim_token
    if data_value:
        payload["dataValue"] = data_value
    return await http_client.post(
        endpoint="/gaotu-assistant-bot/inner/chat/1/session/pending/resolve",
        json_data=payload,
        error_msg="迁移待确认状态失败",
    )


async def claim_pending_confirmation(
    chat_session_id: Union[str, int],
    data_value: Dict[str, Any],
) -> Dict[str, Any]:
    """Atomically claim execution rights for one active pending snapshot."""
    pending_id = str(data_value.get("pendingId") or data_value.get("pending_id") or "").strip()
    revision = _pending_revision(data_value)
    claim_token = str(uuid.uuid4())
    if revision <= 0:
        materialized = await save_pending_confirmation(chat_session_id, {**data_value, "status": "active"})
        if materialized.get("code") != 0:
            return materialized
        current = _pending_resource_data(materialized)
        revision = _pending_revision(current)
    return await resolve_pending_confirmation(
        chat_session_id,
        pending_id=pending_id,
        expected_revision=revision,
        action="confirm",
        claim_token=claim_token,
    )


async def get_last_pending_confirmation(
    chat_session_id: Union[str, int],
) -> Dict[str, Any]:
    """Fetch the dedicated pending resource."""
    return await _get_pending_resource(chat_session_id)


# ── 方案参数校验 ──────────────────────────────────────────────────


async def check_plan_param_availability(
    tenant_id: Union[str, int],
    chat_session_id: str,
    majors: Optional[Dict[str, List[str]]] = None,
    schools: Optional[List[str]] = None,
    locations: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, Any]:
    """异步检查全量方案参数的可用性。"""
    payload = {
        "chatSessionId": chat_session_id,
        "majors": majors or {"level1": [], "level2": [], "level3": []},
        "schools": schools or [],
        "locations": locations or {"province": [], "city": []},
    }
    logger.info("检查方案参数可用性: {}", payload)
    return await http_client.post(
        endpoint=f"/gaotu-assistant-bot/inner/chat/{tenant_id}/plan/param/avail",
        json_data=payload,
        error_msg="检查方案参数可用性失败",
    )


async def check_major_subject_availability(
    tenant_id: Union[str, int],
    chat_session_id: str,
    majors: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, Any]:
    """异步根据学生选课判断能否填报相关专业。"""
    payload = {
        "chatSessionId": chat_session_id,
        "majors": majors or {"level1": [], "level2": [], "level3": []},
    }
    logger.info("检查专业选课可用性: {}", payload)
    return await http_client.post(
        endpoint=f"/gaotu-assistant-bot/inner/chat/{tenant_id}/plan/major/subject/avail",
        json_data=payload,
        error_msg="检查专业选课可用性失败",
    )


# ── 用户填报方案摘要 ──────────────────────────────────────────────


async def get_user_program_major3_summary(
    thread_id: str,
) -> Dict[str, Any]:
    """获取用户填报方案中 level3 专业的总结。"""
    return await get_extra_data(thread_id, "userProgram3MajorSummary")


async def get_user_program_area_summary(thread_id: str) -> Dict[str, Any]:
    """获取用户填报方案中地区的总结。"""
    return await get_extra_data(thread_id, "userProgramAreaSummary")


# ── 专业 / 学校信息查询 ──────────────────────────────────────────


async def get_major_profile(
    major_name: Optional[str] = None,
    major_id: Optional[Union[str, int]] = None,
) -> Dict[str, Any]:
    """根据专业 ID 或名称获取专业相关信息（优先使用 ID）。"""
    if major_id is None and not major_name:
        raise ValueError("获取专业信息至少需要提供 major_id 或 major_name")

    params: Dict[str, Any] = {}
    if major_id is not None:
        params["id"] = major_id
    if major_name:
        params["name"] = major_name

    logger.info("获取专业信息: id={}, name={}", major_id, major_name)
    return await http_client.get(
        endpoint="/gaotu-assistant-bot/inner/major/getMajorProfile",
        params=params,
        error_msg="获取专业信息失败",
    )


async def get_major_category_profile(
        category_name: Optional[str] = None,
    category_id: Optional[Union[str, int]] = None
) -> Dict[str, Any]:
    """根据专业类 ID 或名称获取专业类信息（优先使用 ID）。"""
    if category_id is None and not category_name:
        raise ValueError("获取专业类信息至少需要提供 category_id 或 category_name")

    params: Dict[str, Any] = {}
    if category_id is not None:
        params["id"] = category_id
    if category_name:
        params["name"] = category_name

    logger.info("获取专业类信息: id={}, name={}", category_id, category_name)
    return await http_client.get(
        endpoint="/gaotu-assistant-bot/inner/major-category/getMajorCategoryProfile",
        params=params,
        error_msg="获取专业类信息失败",
    )


async def get_school_profile_by_name(school_name: str) -> Dict[str, Any]:
    """根据学校名称获取学校相关信息。"""
    params = {"name": school_name}
    logger.info("获取学校信息: {}", school_name)
    return await http_client.get(
        endpoint="/gaotu-assistant-bot/inner/school/getSchoolProfileByName",
        params=params,
        error_msg="获取学校信息失败",
    )


# ── 志愿分析 ──────────────────────────────────────────────────────


async def query_volunteer_analysis_weight(
    tenant_id: Union[str, int],
    chat_session_id: Union[str, int],
    querylist: List[Dict[str, Any]],
    query_type: str = "major",
) -> Dict[str, Any]:
    """异步查询志愿分析权重。"""
    payload = {"querylist": querylist, "type": query_type}
    logger.info(
        "查询志愿分析权重 - 租户ID: {}, 会话ID: {}, 查询类型: {}",
        tenant_id,
        chat_session_id,
        query_type,
    )
    return await http_client.post(
        endpoint=(
            f"/gaotu-assistant-bot/inner/volunteer-analysis/query-weight"
            f"?tenantId={tenant_id}&chatSessionId={chat_session_id}"
        ),
        json_data=payload,
        error_msg="查询志愿分析权重失败",
    )


async def query_school_analysis_weight(
    tenant_id: Union[str, int],
    chat_session_id: Union[str, int],
    school_list: List[Dict[str, str]],
) -> Dict[str, Any]:
    """异步查询学校分析权重。"""
    payload = {"querylist": school_list, "type": "school"}
    logger.info(
        "查询学校分析权重 - 租户ID: {}, 会话ID: {}",
        tenant_id,
        chat_session_id,
    )
    return await http_client.post(
        endpoint=(
            f"/gaotu-assistant-bot/inner/volunteer-analysis/query-weight"
            f"?tenantId={tenant_id}&chatSessionId={chat_session_id}"
        ),
        json_data=payload,
        error_msg="查询学校分析权重失败",
    )


async def analyze_majors(
    tenant_id: Union[str, int],
    chat_session_id: Union[str, int],
    major_item_list: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """异步分析专业志愿。"""
    payload = {"majorItemList": major_item_list}
    logger.info(
        "分析专业志愿 - 租户ID: {}, 会话ID: {}",
        tenant_id,
        chat_session_id,
    )
    return await http_client.post(
        endpoint=(
            f"/gaotu-assistant-bot/inner/volunteer-analysis/majors"
            f"?tenantId={tenant_id}&chatSessionId={chat_session_id}"
        ),
        json_data=payload,
        error_msg="分析专业志愿失败",
    )


async def analyze_schools(
    tenant_id: Union[str, int],
    chat_session_id: Union[str, int],
    school_item_list: List[Dict[str, str]],
) -> Dict[str, Any]:
    """异步分析学校志愿。"""
    payload = {"schoolItemList": school_item_list}
    logger.info(
        "分析学校志愿 - 租户ID: {}, 会话ID: {}",
        tenant_id,
        chat_session_id,
    )
    return await http_client.post(
        endpoint=(
            f"/gaotu-assistant-bot/inner/volunteer-analysis/schools"
            f"?tenantId={tenant_id}&chatSessionId={chat_session_id}"
        ),
        json_data=payload,
        error_msg="分析学校志愿失败",
    )


async def submit_volunteer(
    chat_session_id: Union[str, int],
) -> Dict[str, Any]:
    """异步提交志愿。"""
    logger.info("提交志愿 - 会话ID: {}", chat_session_id)
    return await http_client.post(
        endpoint=f"/gaotu-assistant-bot/inner/chat/1/volunteer/submit?chatSessionId={chat_session_id}",
        json_data={},
        error_msg="提交志愿失败",
    )


async def simulate_plan_diff(
    tenant_id: Union[str, int],
    chat_session_id: Union[str, int],
    proposed_profile: Dict[str, Any],
) -> Dict[str, Any]:
    """模拟画像变更对志愿方案的影响。

    将拟修改后的完整画像发送给后端，后端在内存中重新走推荐流水线，
    与当前缓存方案做 diff，返回影响摘要。

    Args:
        tenant_id: 租户ID
        chat_session_id: 会话ID
        proposed_profile: 拟修改后的完整画像（backend format）

    Returns:
        diff 结果，包含 before/after tier 统计、promoted（新进入水位线优选）/demoted（移出水位线优选）学校列表
    """
    payload = {"proposedProfile": proposed_profile}
    logger.info(
        "模拟方案对比 - 租户ID: {}, 会话ID: {}",
        tenant_id,
        chat_session_id,
    )
    return await http_client.post(
        endpoint=(
            f"/gaotu-assistant-bot/inner/recommend/simulate-diff"
            f"?tenantId={tenant_id}&chatSessionId={chat_session_id}"
        ),
        json_data=payload,
        error_msg="模拟方案对比失败",
    )


# ── planning workspace actions ───────────────────────────────────


async def generate_planning_candidate_pool(
    tenant_id: Union[str, int],
    chat_session_id: Union[str, int],
    force_regenerate: bool = True,
) -> Dict[str, Any]:
    return await http_client.post(
        endpoint=(
            f"/gaotu-assistant-bot/inner/planning/{tenant_id}/session/candidate-pool/generate"
            f"?chatSessionId={chat_session_id}"
        ),
        json_data={"forceRegenerate": force_regenerate},
        error_msg="生成候选池失败",
    )


async def execute_pending_planning_command(
    tenant_id: Union[str, int],
    chat_session_id: Union[str, int],
    *,
    operation_id: str,
    pending_id: str,
    claim_token: str,
    expected_plan_version: int,
    command_type: str,
    constraint_update: Optional[Dict[str, Any]] = None,
    min_tuition_per_year: Optional[int] = None,
    max_tuition_per_year: Optional[int] = None,
    regenerate_ordered_plan: bool = False,
    unit_ids: Optional[List[str]] = None,
    volunteer_ids: Optional[List[str]] = None,
    proposal_apply: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "operationId": operation_id,
        "pendingId": pending_id,
        "claimToken": claim_token,
        "expectedPlanVersion": expected_plan_version,
        "commandType": command_type,
        "regenerateOrderedPlan": regenerate_ordered_plan,
        "unitIds": unit_ids or [],
        "volunteerIds": volunteer_ids or [],
    }
    if constraint_update:
        payload["constraintUpdate"] = constraint_update
    if min_tuition_per_year is not None:
        payload["minTuitionPerYear"] = min_tuition_per_year
    if max_tuition_per_year is not None:
        payload["maxTuitionPerYear"] = max_tuition_per_year
    if proposal_apply:
        payload["proposalApply"] = proposal_apply
    return await http_client.post(
        endpoint=(
            f"/gaotu-assistant-bot/inner/planning/{tenant_id}/session/pending-command/execute"
            f"?chatSessionId={chat_session_id}"
        ),
        json_data=payload,
        error_msg="执行幂等待确认规划命令失败",
    )


async def query_planning_candidate_pool(
    tenant_id: Union[str, int],
    chat_session_id: Union[str, int],
    *,
    tiers: Optional[List[str]] = None,
    province_names: Optional[List[str]] = None,
    negative_province_names: Optional[List[str]] = None,
    city_names: Optional[List[str]] = None,
    negative_city_names: Optional[List[str]] = None,
    school_keywords: Optional[List[str]] = None,
    negative_school_keywords: Optional[List[str]] = None,
    major_keywords: Optional[List[str]] = None,
    negative_major_keywords: Optional[List[str]] = None,
    school_tags: Optional[List[str]] = None,
    negative_school_tags: Optional[List[str]] = None,
    major_tags: Optional[List[str]] = None,
    negative_major_tags: Optional[List[str]] = None,
    page: int = 1,
    page_size: int = 20,
    sort_field: str = "finalScore",
    sort_order: str = "desc",
) -> Dict[str, Any]:
    payload = {
        "filters": {
            "tiers": tiers or [],
            "provinceNames": province_names or [],
            "negativeProvinceNames": negative_province_names or [],
            "cityNames": city_names or [],
            "negativeCityNames": negative_city_names or [],
            "schoolKeywords": school_keywords or [],
            "negativeSchoolKeywords": negative_school_keywords or [],
            "majorKeywords": major_keywords or [],
            "negativeMajorKeywords": negative_major_keywords or [],
            "schoolTags": school_tags or [],
            "negativeSchoolTags": negative_school_tags or [],
            "majorTags": major_tags or [],
            "negativeMajorTags": negative_major_tags or [],
        },
        "sort": {
            "field": sort_field,
            "order": sort_order,
        },
        "page": page,
        "pageSize": page_size,
    }
    return await http_client.post(
        endpoint=(
            f"/gaotu-assistant-bot/inner/planning/{tenant_id}/session/candidate-pool/query"
            f"?chatSessionId={chat_session_id}"
        ),
        json_data=payload,
        error_msg="查询候选池失败",
    )


async def select_working_plan_items(
    tenant_id: Union[str, int],
    chat_session_id: Union[str, int],
    volunteer_ids: List[str],
    source: str = "agent_planning_action",
) -> Dict[str, Any]:
    return await http_client.post(
        endpoint=(
            f"/gaotu-assistant-bot/inner/planning/{tenant_id}/session/working-plan/select"
            f"?chatSessionId={chat_session_id}"
        ),
        json_data={"volunteerIds": volunteer_ids, "source": source},
        error_msg="加入方案失败",
    )


async def generate_planning_ordered_plan(
    tenant_id: Union[str, int],
    chat_session_id: Union[str, int],
    force_regenerate: bool = True,
    regroup_by_tier: bool = True,
) -> Dict[str, Any]:
    """生成或刷新统一规划排序方案。"""
    return await http_client.post(
        endpoint=(
            f"/gaotu-assistant-bot/inner/planning/{tenant_id}/session/ordered-plan/generate"
            f"?chatSessionId={chat_session_id}"
        ),
        json_data={
            "forceRegenerate": force_regenerate,
            "regroupByTier": regroup_by_tier,
        },
        error_msg="重排排序失败",
    )


async def sort_planning_ordered_plan(
    tenant_id: Union[str, int],
    chat_session_id: Union[str, int],
    sort_field: str,
) -> Dict[str, Any]:
    return await http_client.post(
        endpoint=(
            f"/gaotu-assistant-bot/inner/planning/{tenant_id}/session/ordered-plan/sort"
            f"?chatSessionId={chat_session_id}"
        ),
        json_data={"sortField": sort_field},
        error_msg="方案排序失败",
    )


async def move_planning_ordered_plan_unit(
    tenant_id: Union[str, int],
    chat_session_id: Union[str, int],
    unit_id: str,
    target_position: int,
) -> Dict[str, Any]:
    return await http_client.post(
        endpoint=(
            f"/gaotu-assistant-bot/inner/planning/{tenant_id}/session/ordered-plan/unit/move"
            f"?chatSessionId={chat_session_id}"
        ),
        json_data={"unitId": unit_id, "targetPosition": target_position},
        error_msg="专业组移动失败",
    )


async def remove_planning_ordered_plan_units(
    tenant_id: Union[str, int],
    chat_session_id: Union[str, int],
    unit_ids: list[str],
) -> Dict[str, Any]:
    return await http_client.post(
        endpoint=(
            f"/gaotu-assistant-bot/inner/planning/{tenant_id}/session/ordered-plan/unit/remove"
            f"?chatSessionId={chat_session_id}"
        ),
        json_data={"unitIds": unit_ids},
        error_msg="专业组删除失败",
    )


async def generate_planning_initial_plan(
    tenant_id: Union[str, int],
    chat_session_id: Union[str, int],
    force_regenerate: bool = True,
    regroup_by_tier: bool = True,
    overwrite_existing_draft: bool = False,
) -> Dict[str, Any]:
    return await http_client.post(
        endpoint=(
            f"/gaotu-assistant-bot/inner/planning/{tenant_id}/session/initial-plan/generate"
            f"?chatSessionId={chat_session_id}"
        ),
        json_data={
            "forceRegenerate": force_regenerate,
            "regroupByTier": regroup_by_tier,
            "overwriteExistingDraft": overwrite_existing_draft,
        },
        error_msg="生成初始方案失败",
    )


async def run_planning_review(
    tenant_id: Union[str, int],
    chat_session_id: Union[str, int],
) -> Dict[str, Any]:
    """执行统一规划方案审查。"""
    return await http_client.post(
        endpoint=(
            f"/gaotu-assistant-bot/inner/planning/{tenant_id}/session/review/run"
            f"?chatSessionId={chat_session_id}"
        ),
        json_data={},
        error_msg="执行审查失败",
    )


# ── 录取分数查询 ──────────────────────────────────────────────────


async def query_program_by_limit_num(
    prepare_type: str,
    subject_type: str,
    score: int,
    subjects: str,
    area_id: str,
    batch: str,
    record_num_limit: int = 10,
) -> Dict[str, Any]:
    """按分数查询院校专业录取方案（冲/稳/保）。

    Args:
        prepare_type: 准备类型
        subject_type: 科目类型
        score: 学生分数
        subjects: 选科组合
        area_id: 地区ID
        batch: 批次
        record_num_limit: 返回记录数限制

    Returns:
        包含 volunteerLevel + records 的列表
    """
    payload = {
        "prepareType": prepare_type,
        "subjectType": subject_type,
        "score": score,
        "subjects": subjects,
        "areaId": area_id,
        "batch": batch,
        "recordNumLimit": record_num_limit,
    }
    logger.info("查询院校录取方案: score={}, area_id={}, batch={}, prepareType={}, subjectType={}, subjects={}", score, area_id, batch, prepare_type, subject_type, subjects)
    return await http_client.post(
        endpoint="/gaotu-assistant-bot/inner/gaotu/program/query-by-limit-num",
        json_data=payload,
        error_msg="查询院校录取方案失败",
    )


async def query_school_major_score_line(
    area_id: str,
    batch: str,
    school_id: str,
    major_id: str = "",
    year: int = 2025,
    subject_type: str = "",
) -> Dict[str, Any]:
    """查询院校专业历年录取分数线。

    Args:
        area_id: 地区ID
        batch: 批次
        school_id: 学校ID
        major_id: 专业ID（可选，不传则查学校整体分数线）
        year: 年份（可选，0表示查多年）
        subject_type: 科目类型

    Returns:
        历年分数线列表，每项包含 year/minScore/maxScore/minPos/enrollNum 等
    """
    payload = {
        "areaId": area_id,
        "batch": batch,
        "schoolId": school_id,
        "majorId": major_id,
        "year": year,
        "subjectType": subject_type,
    }
    logger.info("查询分数线: school_id={}, major_id={}, area_id={}, batch={}, year={}, subject_type={}", school_id, major_id, area_id, batch, year, subject_type)
    return await http_client.post(
        endpoint="/gaotu-assistant-bot/inner/gaotu/score-line/query",
        json_data=payload,
        error_msg="查询分数线失败",
    )
