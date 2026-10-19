"""内部服务 HTTP 客户端，封装了 aiohttp 请求操作。

从 gaotu_zy_agent_plus 迁移，适配 pydantic-settings 配置管理。
"""

from __future__ import annotations

import asyncio
import random
import uuid
from typing import Any, Dict, List, Optional, Union

import aiohttp
from loguru import logger

from app.config import InternalServiceConfig

# 同步等慢命令跑完的调用（规划命令 execute ✓）单独放宽的总超时 ✓：
# 默认 10s 实测会把**已提交**的补录成绩 execute（23.8s ✓）误报成"未生效" ✗
# （静默反向分叉 ✓——见 `HttpClient._resolve_timeout` ✓，2026-10-06 实测 ✓）。
EXECUTE_WAIT_TIMEOUT_SECONDS = 60.0
INTERNAL_SERVICE_TOKEN_HEADER = "X-Internal-Service-Token"

# 直辖市（省级行政区）→ 下辖区县：出处 = GB/T 2260 行政区划代码里四个直辖市的
# 市辖区/县（2016 年后名称；重庆含万州/涪陵等全部区县）。取值一律用**数据侧实际
# 存储的短名**（不带"区/县"后缀；天津"滨海新区"是数据里的全名，单字+县名的
# "忠县"保留全名以免与其他含"忠"的城市串味）。
#
# 为什么需要这层展开：候选池/院校目录里直辖市院校的 `cityName`（候选）与
# `city`（院校目录）存的是**区级名**——实测 2026-10-09 会话 10041981 的候选池：
# 上海院校 cityName∈{虹口,浦东,松江,金山,嘉定}、北京∈{海淀,延庆,大兴,顺义,通州}、
# 天津∈{西青,宝坻,滨海新区,静海,武清}、重庆∈{合川,永川,渝北,巴南}（cityId 为
# 3101xx/1101xx/1201xx/5001xx 区级码）。而过滤执行点是"filter 值 ⊆ 项字段"的
# **包含匹配**（Java `PlanningStateService.matchesCity` / `CandidatePreviewService
# .applyFilters`：`cityName.contains(city)`；院校目录 `SchoolManager.searchSchools`
# 是 `city` **等值**匹配），于是按"上海"筛 → 全漏（只读实测：候选预览
# cityNames=["上海"]+会计 total=0，而同池 provinceNames=["上海"]+会计 total=8、
# 展开成 16 个区名后 total=8，与省份口径逐条一致）。
#
# 已知边界：区名与外省地级市重名时无法在 cityName 这一层区分（"朝阳"既可能指
# 北京朝阳区、也可能指辽宁朝阳市），展开会一起命中——这是包含/等值过滤契约
# 本身的限制，登记在此，不在本层猜测。
_MUNICIPALITY_DISTRICTS: Dict[str, tuple] = {
    "北京": (
        "东城", "西城", "朝阳", "丰台", "石景山", "海淀",
        "门头沟", "房山", "通州", "顺义", "昌平", "大兴",
        "怀柔", "平谷", "密云", "延庆",
    ),
    "天津": (
        "和平", "河东", "河西", "南开", "河北", "红桥",
        "东丽", "西青", "津南", "北辰", "武清", "宝坻",
        "滨海新区", "宁河", "静海", "蓟州",
    ),
    "上海": (
        "黄浦", "徐汇", "长宁", "静安", "普陀", "虹口",
        "杨浦", "闵行", "宝山", "嘉定", "浦东", "金山",
        "松江", "青浦", "奉贤", "崇明",
    ),
    "重庆": (
        "渝中", "大渡口", "江北", "沙坪坝", "九龙坡", "南岸",
        "北碚", "渝北", "巴南", "万州", "涪陵", "黔江",
        "长寿", "江津", "合川", "永川", "南川", "綦江",
        "大足", "璧山", "铜梁", "潼南", "荣昌", "开州",
        "梁平", "武隆", "城口", "丰都", "垫江", "忠县",
        "云阳", "奉节", "巫山", "巫溪", "石柱", "秀山",
        "酉阳", "彭水",
    ),
}


def _strip_region_suffix(value: Any) -> str:
    """去掉省市后缀做归一的比较键（"上海市" → "上海"）。"""
    text = str(value or "").strip()
    for suffix in ("市", "省"):
        if text.endswith(suffix) and len(text) > len(suffix):
            text = text[: -len(suffix)]
    return text


def _municipality_name(value: Any) -> Optional[str]:
    """值是不是直辖市（"上海" / "上海市" → "上海"）；不是则 None。"""
    normalized = _strip_region_suffix(value)
    return normalized if normalized in _MUNICIPALITY_DISTRICTS else None


def _expand_municipality_city_names(values: Any) -> List[str]:
    """"上海" → ["上海", 16 个区名]；其余城市原样透传（保序去重）。

    直辖市名本身保留在列表里（存量若有用"上海/上海市"存 cityName 的数据也能命中），
    区名用短名，可同时覆盖"浦东"与"浦东新区"两种存量形态（包含匹配）。
    """
    if isinstance(values, str):
        values = [values]
    expanded: List[str] = []
    for raw in values or []:
        text = str(raw or "").strip()
        if not text:
            continue
        expanded.append(text)
        municipality = _municipality_name(text)
        if municipality:
            expanded.extend(_MUNICIPALITY_DISTRICTS[municipality])
    return list(dict.fromkeys(expanded))


def _expand_municipality_filter_city_names(filters: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """过滤字典里的正/负向城市项做直辖市展开；别的键原样透传。"""
    expanded = dict(filters or {})
    for key in ("cityNames", "city_names", "negativeCityNames", "negative_city_names"):
        if key in expanded:
            expanded[key] = _expand_municipality_city_names(expanded[key])
    return expanded


class HttpClient:
    """HTTP 客户端，封装了 aiohttp 请求操作。"""

    def __init__(self) -> None:
        config = InternalServiceConfig()
        # 支持逗号分隔的多个地址
        self.base_urls = [url.strip() for url in config.url.split(",")]
        self.timeout = aiohttp.ClientTimeout(total=max(0.1, float(config.timeout_seconds)))
        self.default_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        token = getattr(config, "token", None)
        if token is not None and token.get_secret_value().strip():
            self.default_headers[INTERNAL_SERVICE_TOKEN_HEADER] = token.get_secret_value()

    def _merge_headers(self, headers: Optional[Dict[str, str]]) -> Dict[str, str]:
        merged = dict(self.default_headers)
        merged.update({
            key: value for key, value in (headers or {}).items()
            if key.lower() != INTERNAL_SERVICE_TOKEN_HEADER.lower()
        })
        return merged

    def _resolve_timeout(
        self, timeout_seconds: Optional[float] = None
    ) -> aiohttp.ClientTimeout:
        """每次调用可用 `timeout_seconds` **单独放宽**总超时 ✓。

        默认值（10s ✓）是常规内部调用的护栏 ✓；但**同步等一条慢命令跑完**的调用
        （规划命令 execute ✓）必须能放宽 ✓——超时先返回**不等于服务端没执行** ✗：
        2026-10-06 实测补录成绩 execute 端到端 **23.8s** ✓（同步重拉全量志愿数据 ✓），
        客户端 10s 超时会制造"**写已提交、卡却显示未生效**"的静默反向分叉 ✗✓。
        """
        if timeout_seconds is None:
            return self.timeout
        return aiohttp.ClientTimeout(total=max(0.1, float(timeout_seconds)))

    def _get_random_base_url(self) -> str:
        """随机选择一个基础 URL。"""
        return random.choice(self.base_urls)

    async def get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        error_msg: str = "请求失败",
        *,
        require_success: bool = False,
    ) -> Dict[str, Any]:
        """发送 GET 请求。

        Args:
            endpoint: API 端点路径（不包含 base_url）
            params: 查询参数
            headers: 请求头（如果提供，将与默认请求头合并）
            error_msg: 错误信息前缀
            require_success: 非 HTTP 200 时返回失败 envelope，不信任响应体

        Returns:
            服务器返回的 JSON 响应。
        """
        base_url = self._get_random_base_url()
        url = f"{base_url}{endpoint}"
        merged_headers = self._merge_headers(headers)

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(
                    url, params=params, headers=merged_headers, allow_redirects=False
                ) as response:
                    if require_success and response.status != 200:
                        logger.error(f"{error_msg}: HTTP {response.status}")
                        return {"error": "http_status", "success": False, "status": response.status}
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
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        error_msg: str = "请求失败",
        timeout_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        """发送 POST 请求。

        Args:
            endpoint: API 端点路径（不包含 base_url）
            json_data: 请求体数据，将被序列化为 JSON
            params: 查询串参数（如果提供，将挂在 URL 上）
            headers: 请求头（如果提供，将与默认请求头合并）
            error_msg: 错误信息前缀
            timeout_seconds: **单独放宽**该次调用的总超时 ✓（默认走构造时的配置值 ✓；
                见 `_resolve_timeout` ✓——同步等慢命令（execute）的那条必须放宽 ✓）。

        Returns:
            服务器返回的 JSON 响应。
        """
        base_url = self._get_random_base_url()
        url = f"{base_url}{endpoint}"
        merged_headers = self._merge_headers(headers)

        try:
            async with aiohttp.ClientSession(timeout=self._resolve_timeout(timeout_seconds)) as session:
                async with session.post(
                    url, json=json_data, params=params, headers=merged_headers, allow_redirects=False
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
        merged_headers = self._merge_headers(headers)

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.delete(
                    url, params=params, headers=merged_headers, allow_redirects=False
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
        merged_headers = self._merge_headers(headers)

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.put(
                    url, json=json_data, headers=merged_headers, allow_redirects=False
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
        merged_headers = self._merge_headers(headers)

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.patch(
                    url, json=json_data, headers=merged_headers, allow_redirects=False
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


async def get_current_codex_thread_binding(
    tenant_id: Union[str, int], chat_session_id: Union[str, int]
) -> Dict[str, Any]:
    """查这个 (租户, 会话) 当前有效的绑定，供 Gateway 重启后恢复 thread。

    与 resolve 的区别：resolve 要 handle（证明"我就是当初注册的那个人"），
    这个查询只要内部身份 + 会话号——它的用途是**找回** thread，而 handle
    恰好是进程重启后丢掉的那样东西。所以它只对认证过的内部调用方开放。
    """
    return await http_client.get(
        endpoint=f"/gaotu-assistant-bot/inner/codex/{tenant_id}/thread-binding/current",
        params={"chatSessionId": chat_session_id},
        error_msg="查询 Codex thread binding 失败",
        require_success=True,
    )


async def verify_evidence(
    tenant_id: Union[str, int],
    chat_session_id: Union[str, int],
    evidence_ids: List[str],
    thread_id: str | None = None,
) -> Dict[str, Any]:
    """批量核验证据（P1c-2）。返回 `{evidenceId: {status, sourceSystem, paramsDigest, ...}}`。

    **失败必须抛**，这是本函数与其它封装的唯一区别，也是它存在的理由：
    `http_client.post` 是"失败也给你一个 dict"的形状（异常 → `{"error": …, "success": False}`，
    非 200 → 照样返回响应体）。对核验来说那个形状是 **fail-open**——拿不到答案时，
    它在调用方眼里长得像"没有证据需要核验"，于是校验被静默放宽。
    设计文档第六章把"Java 不可达 → 硬失败，不放行"单独列了一行，就是因为
    "依赖不可用时放宽校验"是这里最自然的手滑。
    """
    response = await http_client.post(
        endpoint="/internal/evidence/verify",
        json_data={
            "tenantId": tenant_id,
            "chatSessionId": chat_session_id,
            "threadId": thread_id,
            "evidenceIds": list(evidence_ids),
        },
        error_msg="核验证据失败",
    )
    if response.get("success") is False:
        raise RuntimeError(f"evidence verification unreachable: {response.get('error')}")
    code = response.get("code")
    if code not in (None, 0):
        raise RuntimeError(
            f"evidence verification failed: code={code} msg={response.get('msg')}"
        )
    results = ((response.get("data") or {}) or {}).get("results")
    if not isinstance(results, dict):
        raise RuntimeError("evidence verification returned an unusable payload")
    return results


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


async def _get_pending_resource(
    chat_session_id: Union[str, int],
    *,
    tenant_id: Union[str, int] = 1,
) -> Dict[str, Any]:
    return await http_client.get(
        endpoint=f"/gaotu-assistant-bot/inner/chat/{tenant_id}/session/pending",
        params={"chatSessionId": chat_session_id},
        error_msg="获取待确认资源失败",
    )


async def reconcile_pending_confirmation(
    chat_session_id: Union[str, int],
    *,
    tenant_id: Union[str, int] = 1,
) -> Dict[str, Any]:
    """J1：applying 对账。Java 只读 operation 台账 + CAS，不重发命令。"""
    return await http_client.post(
        endpoint=(
            f"/gaotu-assistant-bot/inner/chat/{tenant_id}/session/pending/reconcile"
            f"?chatSessionId={chat_session_id}"
        ),
        json_data={},
        error_msg="待确认对账失败",
    )


def _pending_long_id(value: Union[str, int]) -> str:
    if type(value) not in (str, int):
        raise ValueError("pending lookup requires positive Long identifiers")
    text = str(value)
    if (
        not text or len(text) > 19 or not text.isascii()
        or not text.isdecimal() or text.startswith("0")
        or int(text) > 9223372036854775807
    ):
        raise ValueError("pending lookup requires positive Long identifiers")
    return text


async def load_pending_for_reclaim(
    *, tenant_id: Union[str, int], session_id: Union[str, int],
) -> Dict[str, Any]:
    """Fresh, strict read of the dedicated pending resource; never a snapshot."""
    tenant = _pending_long_id(tenant_id)
    session = _pending_long_id(session_id)
    return await http_client.get(
        endpoint=f"/gaotu-assistant-bot/inner/chat/{tenant}/session/pending",
        params={"chatSessionId": session},
        error_msg="回收预检读取待确认资源失败",
        require_success=True,
    )


# ── 消息相关 ──────────────────────────────────────────────────────


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
    # 院校目录的 `city` 是**等值**匹配（Java `SchoolManager.searchSchools`），而目录里
    # 直辖市院校的 `city` 存区级名（实测 2026-10-09：city="浦东" 13 所、"上海" 0 所，
    # 而 province="上海" 44 所）→ 直辖市的城市条件上提到 `province`（两者是同一地理
    # 实体）。只在省份条件缺失或本来就是同一实体时做；相互矛盾的条件（如
    # province=江苏 + city=上海）保持原样，不把"查不到"改写成"查到别的地方"。
    municipality = _municipality_name(city)
    if municipality and (not province or _municipality_name(province) == municipality):
        province = municipality
        city = None
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


async def search_schools_by_name(school_name: str) -> Any:
    """按名字模糊查学校。

    与 `catalog_list_schools`（按省份/城市/类型筛）的区别是它有**名字条件**：
    用户说"北京大学"时，筛选题材的那条路给不出"哪些学校叫这个名"，
    返回的是一批与该名字无关的学校。
    """
    return await http_client.get(
        endpoint="/gaotu-assistant-bot/inner/school/search/name",
        params={"schoolName": school_name},
        error_msg="catalog 按名搜索学校失败",
    )


async def get_batch_info(
    area_id: Union[str, int],
    prepare_type: str = "VOLUNTEER",
    subject: str = "N",
    *,
    tenant_id: Union[str, int, None] = None,
    chat_session_id: Union[str, int, None] = None,
    thread_id: Optional[str] = None,
) -> Any:
    """取该省的批次字典（含批次码）。

    `admission.get_history` / `admission.compare` 的 `batch` 必须是**这个字典里的码**
    （浙江第一段 = 17、上海本科批 = 01），不是"本科批"这种名字：传名字上游不报错，
    它只是返回空——于是每次查询都"没有数据"，而真相是批次码不对。
    """
    params: Dict[str, Any] = {
        "areaId": area_id,
        "prepareType": prepare_type,
        "subject": subject,
    }
    params.update(_evidence_scope_params(tenant_id, chat_session_id, thread_id))
    return await http_client.get(
        endpoint="/gaotu-assistant-bot/inner/gaotu/batch/info",
        params=params,
        error_msg="catalog 查询批次字典失败",
    )


async def get_batch_options(
    area_id: Union[str, int],
    subject_type: str = "",
    *,
    tenant_id: Union[str, int, None] = None,
    chat_session_id: Union[str, int, None] = None,
    thread_id: Optional[str] = None,
) -> Any:
    """**补录成绩用**的批次编码表：`[{code, name, level, score, pos}]`。

    与 `get_batch_info`（上游 DTO 原样透传）的分工：这条是给模型**补编码**用的归一化
    形状——`code` 是补录请求 `batch.code` 的取值（浙江第一段=17、第二段=18），
    `level` 是 01 本科 / 02 专科的编码（建档策略按 `provinceCode + level` 取，
    传"本科"这种名字会静默取不到）。`subject_type` 给科类码（浙江 N、江苏 WL/LS）；
    多科类省份不给时 Java 侧会明确拒绝并列出可选科类。
    """
    params: Dict[str, Any] = {"areaId": area_id}
    if subject_type:
        params["subjectType"] = subject_type
    params.update(_evidence_scope_params(tenant_id, chat_session_id, thread_id))
    return await http_client.get(
        endpoint="/gaotu-assistant-bot/inner/gaotu/catalog/batch-options",
        params=params,
        error_msg="catalog 查询批次编码表失败",
    )


async def get_subject_options(area_id: Union[str, int]) -> Any:
    """**补录成绩用**的科目编码表：`[{code, name}]`。

    选考科目（01-07）+ 语数外（08/10/11，上游选科策略不含，由 Java 侧补全）。
    补录请求 `subjectScoreList[].subject` 只能取这里的 code——只报分数、或报科目名，
    都会在落库前被 110 拒（2026-10-06 的真事故）。
    """
    return await http_client.get(
        endpoint="/gaotu-assistant-bot/inner/gaotu/catalog/subject-options",
        params={"areaId": area_id},
        error_msg="catalog 查询科目编码表失败",
    )


async def get_score_position(
    area_id: Union[str, int],
    score: Union[str, int],
    subject: str = "N",
    data_level: str = "01",
    year: Union[str, int, None] = None,
) -> Any:
    """一分一段：分数 → **位次区间**（`{score, students, highestRank, lowestRank, dataLevel}`）。

    口径：同分考生**不可分辨**——`highestRank`~`lowestRank` 是区间（`students` 人同分），
    只能报区间，不能报单一名次。`subject` 是选科类型码（浙江 N、江苏 WL/LS），
    `data_level` 是批次 level（01 本科 / 02 专科，浙江第一段=01，可由
    `get_batch_options` 的 `level` 得到）；`year` 缺省由调用方补当前年。
    上游没有该省数据时（如安徽）Java 回 `data: null`——如实不可用，不估算。
    """
    payload: Dict[str, Any] = {
        "areaId": str(area_id),
        "subject": subject or "N",
        "dataLevel": data_level or "01",
        "score": str(score),
    }
    if year not in (None, ""):
        payload["year"] = str(year)
    return await http_client.post(
        endpoint="/gaotu-assistant-bot/inner/gaotu/catalog/score-position",
        json_data=payload,
        error_msg="catalog 查询分数位次失败",
    )


async def get_plan_major_filter_list(
    school_id: Union[str, int], area_id: Union[str, int]
) -> Any:
    """招生计划筛选条件树：年份 → 科类 → 批次 → **招生单元**。

    末层的 `value` 就是 `schoolUnitId`，`get_enrollment_plan` 反过来要求它。
    这是专业级那条链的入口，而且**免分数**。
    """
    return await http_client.get(
        endpoint="/gaotu-assistant-bot/inner/gaotu/plan/filter-list",
        params={"schoolId": school_id, "areaId": area_id},
        error_msg="招生计划筛选条件查询失败",
    )


async def get_enrollment_plan(
    payload: Dict[str, Any],
    *,
    limit: Optional[int] = None,
    tenant_id: Union[str, int, None] = None,
    chat_session_id: Union[str, int, None] = None,
    thread_id: Optional[str] = None,
) -> Any:
    """某个招生单元的招生计划（专业、计划数、学费、选考要求）。"""
    params: Dict[str, Any] = {}
    if limit is not None:
        params["limit"] = limit
    params.update(_evidence_scope_params(tenant_id, chat_session_id, thread_id))
    return await http_client.post(
        endpoint="/gaotu-assistant-bot/inner/gaotu/plan/major-data",
        json_data=dict(payload),
        params=params,
        error_msg="招生计划查询失败",
    )


async def get_school_news(
    school_id: Union[str, int], *, current: int = 1, size: int = 20
) -> Any:
    """院校资讯列表（招生章程/招生简章）。免 token、免分数，是章程那条链的索引。"""
    return await http_client.post(
        endpoint="/gaotu-assistant-bot/inner/gaotu/school/news",
        json_data={"schoolId": str(school_id), "current": current, "size": size},
        error_msg="招生章程列表查询失败",
    )


async def get_school_news_detail(
    news_id: Union[str, int],
    *,
    tenant_id: Union[str, int, None] = None,
    chat_session_id: Union[str, int, None] = None,
    thread_id: Optional[str] = None,
) -> Any:
    """招生章程正文（学校发布的招生简章全文），Java 侧按来源签发证据。"""
    params: Dict[str, Any] = {"id": news_id}
    params.update(_evidence_scope_params(tenant_id, chat_session_id, thread_id))
    return await http_client.get(
        endpoint="/gaotu-assistant-bot/inner/gaotu/school/news-info",
        params=params,
        error_msg="招生章程正文查询失败",
    )


async def compare_candidates(
    tenant_id: Union[str, int], entities: List[Dict[str, Any]], dimensions: List[str]
) -> Dict[str, Any]:
    """同口径并列。

    取数**不在这里**：各实体的值由调用方从自己的来源链路取（那里签证据）。
    这个端点只负责调用方做不到的那件事——判断这些值能不能放在一张表里比。
    """
    return await http_client.post(
        endpoint=f"/gaotu-assistant-bot/inner/planning/{tenant_id}/session/compare",
        json_data={"entities": list(entities), "dimensions": list(dimensions)},
        error_msg="同口径并列失败",
    )


async def compare_candidate_pool(
    tenant_id: Union[str, int],
    chat_session_id: Union[str, int],
    entity_ids: List[str],
    dimensions: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """按候选池 entityId 的并列（**只读**）：值由 Java 从会话候选池真实载入。

    与 `compare_candidates` 的分工：那条的值由调用方（模型链路）自己取好再传；
    这条**只给 ID**（`recommendation.preview_candidates` 返回的 `entityId` = volunteerId），
    值由 Java 从候选池的候选行里载入——模型凭记忆填数字这条路在这里被堵死。

    Java 侧走只读载入（`loadReadOnlyCandidatePool`：不 savePlanningState、不 bump 规划版本）。
    找不到的 ID 会进 `limitations` 的 `entity_not_found:<id>`，**不静默丢**。
    """
    payload: Dict[str, Any] = {
        "chatSessionId": chat_session_id,
        "entityIds": list(entity_ids),
        "dimensions": list(dimensions or []),
    }
    return await http_client.post(
        endpoint=f"/gaotu-assistant-bot/inner/planning/{tenant_id}/session/compare-candidates",
        json_data=payload,
        error_msg="候选比较失败",
    )


async def explain_candidate_fit(
    tenant_id: Union[str, int],
    chat_session_id: Union[str, int],
    entity_id: Union[str, int],
) -> Dict[str, Any]:
    """适配性解释（**只读**）：解释**某一个**候选为什么匹配/不匹配。

    与 `compare_candidate_pool` 同一分工：`entity_id`（= volunteerId，来自
    `recommendation.preview_candidates`）只用于**定位候选行**，匹配点/风险的取值
    全部由 Java 从会话候选池与会话状态真实载入——模型凭记忆复述这条路被堵死。

    Java 侧走只读载入（`loadReadOnlyCandidatePool`：不 savePlanningState、不 bump 规划版本），
    且 `probability` 恒为 `unavailable`（无权威概率源，不估算：适配与概率是两件事）。
    找不到的 ID 会进 `limitations` 的 `entity_not_found:<id>`，**不静默丢**。
    """
    payload: Dict[str, Any] = {
        "chatSessionId": chat_session_id,
        "entityId": entity_id,
    }
    return await http_client.post(
        endpoint=f"/gaotu-assistant-bot/inner/planning/{tenant_id}/session/explain-fit",
        json_data=payload,
        error_msg="适配性解释失败",
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
    # Java 侧该请求连带做 38MB planningState 同步 ✓——2026-10-16 实测整段 **20.6s** ✓，
    # 默认 10s 会在**写已提交**之后超时 ✗（成功被显示成失败的假失败 ✗），故单独放宽到 60s ✓。
    return await http_client.post(
        endpoint="/gaotu-assistant-bot/inner/chat/1/session/add-extra-data",
        json_data=payload,
        error_msg="存储用户画像失败",
        timeout_seconds=60,
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


async def get_planning_profile(thread_id: Union[str, int]) -> Dict[str, Any]:
    """获取 planning 画像（`ProfileStateDTO`：含 `latentProfile.futureDevelopment` ✓）。

    用途：career v1 的两处**agent 侧直读**——
    · 回合快照补 `careerTypes`（turn-snapshot 的投影 DTO 里没有 latentProfile ✓）；
    · 发展方向提案执行时读-改-写（Java 的 latent 更新是**整字段赋值** ✓，
      不先读回全文就写，会把 industryPreferences 等既有键抹掉 ✓）。
    """
    return await http_client.get(
        endpoint="/gaotu-assistant-bot/inner/planning/1/session/profile",
        params={"chatSessionId": thread_id},
        error_msg="获取 planning 画像失败",
    )


async def get_conversation_turn_snapshot(
    tenant_id: Union[str, int],
    chat_session_id: Union[str, int],
    skill: Optional[str] = None,
) -> Dict[str, Any]:
    """获取面向 Codex 单轮的有界事实快照。"""
    params: Dict[str, Any] = {"chatSessionId": chat_session_id}
    if skill:
        params["skill"] = skill
    return await http_client.get(
        endpoint=f"/gaotu-assistant-bot/inner/planning/{tenant_id}/session/turn-snapshot",
        params=params,
        error_msg="获取 conversation turn snapshot 失败",
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


async def prepare_user_goal_planning_fix_proposals(
    tenant_id: Union[str, int],
    chat_session_id: Union[str, int],
    *,
    request_id: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """P2：按结构化用户复合目标生成预览**并物化为待确认**（写闭环第一段）。

    与 `generate_user_goal_planning_fix_proposals` 的区别只有这一点：这个走
    `/fix-proposals/user-goal/prepare`，Java 会把预览变成 pending，并在 pending 的
    dataValue 里落下**它产出的 operationId**（写闭环的幂等键）。`requestId` 是幂等键：
    同一个 requestId 重放返回同一次结果（同一个 operationId），配不同内容会被 Java 409。
    """
    return await http_client.post(
        endpoint=(
            f"/gaotu-assistant-bot/inner/planning/{tenant_id}/session/fix-proposals/user-goal/prepare"
            f"?chatSessionId={chat_session_id}&requestId={request_id}"
        ),
        json_data=payload or {},
        error_msg="生成用户目标方案调整待确认失败",
    )


async def preview_review_fix_proposals(
    tenant_id: Union[str, int],
    chat_session_id: Union[str, int],
) -> Dict[str, Any]:
    """J5.5b：只读审查修复预览（不建 pending、不推进方案版本）。

    返回 `ReviewFixPreviewDTO`：status/sourceVersion/review/proposals。只有
    `requiresConfirmation=true` 且带 commandDigest/previewDigest 的 proposal
    才能进入确认回合的 prepare。
    """
    return await http_client.post(
        endpoint=(
            f"/gaotu-assistant-bot/inner/planning/{tenant_id}/session/fix-proposals/preview"
            f"?chatSessionId={chat_session_id}"
        ),
        json_data={},
        error_msg="生成审查修复预览失败",
    )


async def prepare_review_fix_proposal(
    tenant_id: Union[str, int],
    chat_session_id: Union[str, int],
    *,
    request_id: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """J5.5b：把**只读**的审查修复预览冻结成 pending（唯一写入口的第一段）。

    与旧 `apply_planning_fix_proposal` 的区别：apply 直连在 J5.5b 起对
    `review_check` 返回 409 `review_fix_requires_pending`；审查修复必须先走这里，
    由 Java 重新定位 proposalId 对应的唯一 command、复算 previewDigest 并落
    pending（dataValue 里带 operationId/冻结字段）。`requestId` 是幂等键：
    同一 requestId + 同内容重放返回同一个 pendingId/operationId，不生成第二份预览。
    """
    return await http_client.post(
        endpoint=(
            f"/gaotu-assistant-bot/inner/planning/{tenant_id}/session/fix-proposals/review/prepare"
            f"?chatSessionId={chat_session_id}&requestId={request_id}"
        ),
        json_data=payload or {},
        error_msg="生成审查修复待确认失败",
    )


async def preview_score_update(
    tenant_id: Union[str, int],
    chat_session_id: Union[str, int],
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """补录成绩草稿的**只读**预览（校验 + 结构化摘要，不落任何状态）。

    与 prepare 的区别只有"要不要物化成待确认"这一点（同 `user-goal` 的 generate/prepare ✓）。
    只读模式（`codex_readonly`）走这条：写路径不在这台实例上活着。
    """
    return await http_client.post(
        endpoint=(
            f"/gaotu-assistant-bot/inner/planning/{tenant_id}/session/score-update/preview"
            f"?chatSessionId={chat_session_id}"
        ),
        json_data=payload or {},
        error_msg="生成补录成绩预览失败",
    )


async def prepare_score_update(
    tenant_id: Union[str, int],
    chat_session_id: Union[str, int],
    *,
    request_id: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """补录成绩草稿的 prepare：Java 校验后**物化成待确认**（写闭环第一段）。

    与 `prepare_user_goal_planning_fix_proposals` 同一条状态机（同 requestId 重放
    → 同一个 operationId；配不同内容 → 409 ✓）：pending 的 `dataValue` 里落下 Java
    产出的 `operationId`、`sourceVersion`、`scoreUpdateRequest`（执行输入）与
    `scoreSummary`（卡片展示）。
    """
    return await http_client.post(
        endpoint=(
            f"/gaotu-assistant-bot/inner/planning/{tenant_id}/session/score-update/prepare"
            f"?chatSessionId={chat_session_id}&requestId={request_id}"
        ),
        json_data=payload or {},
        error_msg="生成补录成绩待确认失败",
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


async def get_working_plan(
    thread_id: Union[str, int], tenant_id: Union[str, int]
) -> Dict[str, Any]:
    """获取当前统一规划方案。

    `tenant_id` 是**必填**的：路径里那个 `1` 曾经是硬编码，于是 tenant 非 1
    的会话要么读到别人的方案、要么直接失败——而"读到了别人的方案"不会报错，
    它会安静地把别人的志愿表当成你的。
    """
    if tenant_id in (None, ""):
        raise ValueError("tenant_id_required")
    return await http_client.get(
        endpoint=f"/gaotu-assistant-bot/inner/planning/{tenant_id}/session/working-plan",
        params={"chatSessionId": thread_id},
        error_msg="获取方案失败",
    )


async def get_planning_ordered_plan(
    thread_id: Union[str, int], tenant_id: Union[str, int]
) -> Dict[str, Any]:
    """获取当前统一规划排序方案。tenant_id 与 working-plan 同理，不得硬编码。"""
    if tenant_id in (None, ""):
        raise ValueError("tenant_id_required")
    return await http_client.get(
        endpoint=f"/gaotu-assistant-bot/inner/planning/{tenant_id}/session/ordered-plan",
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


# ── 推荐相关 ──────────────────────────────────────────────────────


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


# ── 待确认卡片 ────────────────────────────────────────────────────


async def save_pending_confirmation(
    chat_session_id: Union[str, int],
    data_value: Dict[str, Any],
    *,
    tenant_id: Union[str, int] = 1,
) -> Dict[str, Any]:
    """Create/replace or finalize the dedicated pending resource."""
    status = str(data_value.get("status") or "active").strip().lower()
    pending_id = str(data_value.get("pendingId") or data_value.get("pending_id") or "").strip()
    expected_revision = _pending_revision(data_value)
    current_response: Dict[str, Any] = {}
    if expected_revision <= 0:
        current_response = await _get_pending_resource(chat_session_id, tenant_id=tenant_id)
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
            tenant_id=tenant_id,
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
        endpoint=f"/gaotu-assistant-bot/inner/chat/{tenant_id}/session/pending",
        json_data=payload,
        error_msg="存储待确认卡片状态失败",
    )


async def resolve_pending_confirmation(
    chat_session_id: Union[str, int],
    *,
    tenant_id: Union[str, int] = 1,
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
        endpoint=f"/gaotu-assistant-bot/inner/chat/{tenant_id}/session/pending/resolve",
        json_data=payload,
        error_msg="迁移待确认状态失败",
    )


async def claim_pending_confirmation(
    chat_session_id: Union[str, int],
    data_value: Dict[str, Any],
    *,
    tenant_id: Union[str, int] = 1,
) -> Dict[str, Any]:
    """Atomically claim execution rights for one active pending snapshot."""
    pending_id = str(data_value.get("pendingId") or data_value.get("pending_id") or "").strip()
    revision = _pending_revision(data_value)
    claim_token = str(uuid.uuid4())
    if revision <= 0:
        materialized = await save_pending_confirmation(
            chat_session_id,
            {**data_value, "status": "active"},
            tenant_id=tenant_id,
        )
        if materialized.get("code") != 0:
            return materialized
        current = _pending_resource_data(materialized)
        revision = _pending_revision(current)
    return await resolve_pending_confirmation(
        chat_session_id,
        tenant_id=tenant_id,
        pending_id=pending_id,
        expected_revision=revision,
        action="confirm",
        claim_token=claim_token,
    )


async def get_last_pending_confirmation(
    chat_session_id: Union[str, int],
    *,
    tenant_id: Union[str, int] = 1,
) -> Dict[str, Any]:
    """Fetch the dedicated pending resource."""
    return await _get_pending_resource(chat_session_id, tenant_id=tenant_id)


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
    score_update: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "operationId": operation_id,
        "pendingId": pending_id,
        "claimToken": claim_token,
        "expectedPlanVersion": expected_plan_version,
        "commandType": command_type,
    }
    # add/remove/move 新链路只发 5 个字段：命令内容以 pending 的 frozenCommand 为准，
    # 不把空 volunteerIds/命令字段发过去（Java 会允许空，但契约上应以 frozen 为准）。
    # replace_units 保留显式集合：legacy 替换仍靠 unitIds/volunteerIds；新链路网关
    # 传空列表，Java 只把非空请求字段与 frozen 比对。
    if command_type not in {"add_units", "remove_units", "move_units"}:
        payload["regenerateOrderedPlan"] = regenerate_ordered_plan
        payload["unitIds"] = unit_ids or []
        payload["volunteerIds"] = volunteer_ids or []
    if constraint_update:
        payload["constraintUpdate"] = constraint_update
    if min_tuition_per_year is not None:
        payload["minTuitionPerYear"] = min_tuition_per_year
    if max_tuition_per_year is not None:
        payload["maxTuitionPerYear"] = max_tuition_per_year
    if proposal_apply:
        payload["proposalApply"] = proposal_apply
    if score_update:
        payload["scoreUpdate"] = score_update
    # **execute 是"同步等命令跑完"** ✓（Java `PendingPlanningCommandBizService.execute` 单事务
    # 同步返回 ✓）：补录成绩这条会同步重拉全量志愿数据再落盘 ✓——2026-10-06 实测整段 **23.8s** ✓，
    # 默认 10s 会在**写已提交**之后超时 ✗（卡上误显"未生效" ✗——成功被显示成失败的静默反向分叉 ✗）。
    try:
        return await http_client.post(
            endpoint=(
                f"/gaotu-assistant-bot/inner/planning/{tenant_id}/session/pending-command/execute"
                f"?chatSessionId={chat_session_id}"
            ),
            json_data=payload,
            error_msg="执行幂等待确认规划命令失败",
            timeout_seconds=EXECUTE_WAIT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        # 超时 ≠ 未执行：命令可能已经在 Java 事务里提交。按“处理中”返回，
        # 让用户稍后重试/重连；不能把成功显示成失败，也不能再生成另一版执行。
        logger.warning(
            "pending command execute timed out (operation=%s pending=%s); outcome unknown",
            operation_id,
            pending_id,
        )
        return {
            "status": "applying",
            "code": 0,
            "data": {"message": "执行结果暂未返回，请稍后重试确认。"},
        }


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
            # 直辖市按区县展开（见 `_MUNICIPALITY_DISTRICTS`）：池里直辖市院校的
            # `cityName` 是区级名，不做这层展开时按"上海"筛恒为 0（假否定）。
            "cityNames": _expand_municipality_city_names(city_names),
            "negativeCityNames": _expand_municipality_city_names(negative_city_names),
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


async def preview_candidates(
    tenant_id: Union[str, int],
    chat_session_id: Union[str, int],
    *,
    filters: Optional[Dict[str, Any]] = None,
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    """候选预览（**只读**）：Top-N 候选 + 过滤后全量计数，不落规划状态。

    与 `query_planning_candidate_pool` 的区别是**写不写**：那条走
    `candidate-pool/query`，Java 侧会 `refreshRecommendationOverlay →
    savePlanningState`（规划版本自增）；这条走 `candidate-preview`，
    只读加载规划状态 + `recommendVolunteerList(saveToFile=false)`，
    规划版本不变——预览不该改变被预览的东西。
    """
    payload: Dict[str, Any] = {
        # 与 `query_planning_candidate_pool` 同一口径：直辖市城市项按区县展开
        # （见 `_MUNICIPALITY_DISTRICTS`），否则按"上海"预览恒返回 0 条。
        "filters": _expand_municipality_filter_city_names(filters),
        "page": page,
        "pageSize": page_size,
    }
    return await http_client.post(
        endpoint=(
            f"/gaotu-assistant-bot/inner/planning/{tenant_id}/session/candidate-preview"
            f"?chatSessionId={chat_session_id}"
        ),
        json_data=payload,
        error_msg="候选预览失败",
    )


async def preview_majors(
    chat_session_id: Union[str, int],
    *,
    top_n: int = 8,
) -> Dict[str, Any]:
    """专业方向推荐预览（**只读**）：按会话画像在 rank 服务做专业级打分，取 topN。

    与 `preview_candidates` 的分工是**层级**：这条回答"适合什么**专业方向**"
    （专业类/大类层，不落到具体志愿单元），那条给的是院校/专业组的**具体志愿单元**候选。

    返回 `{code, msg, data}`：可用时 `data={chatSessionId, topN, items[], limitations[]}`
    （items 字段照 Java 实体：`major_id/major/score/gender_index/satisfy_index/salary_avg/hot_index`）；
    无档案/无分数/画像缺 rank 必读字段时 Java 如实回 **`data=null` + 原因码在 `msg`**
    （`session_profile_missing` / `session_score_missing` / `session_profile_incomplete:…`），
    由工具层转成"不可用 + 原因"，不猜、不造数。
    """
    payload: Dict[str, Any] = {
        "chatSessionId": chat_session_id,
        "topN": top_n,
    }
    return await http_client.post(
        endpoint="/gaotu-assistant-bot/inner/gaotu/catalog/major-recommend",
        json_data=payload,
        error_msg="专业方向推荐失败",
    )


async def interpret_admission(
    tenant_id: Union[str, int],
    chat_session_id: Union[str, int],
    *,
    plan_version: int,
    admission_mode: Optional[str] = None,
    counterfactual: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """录取解读（只读）：当前方案的结构与条件情景。

    返回 `{code, msg, data}`；`data` 是 `AdmissionInterpretationRes` 原样：
    scenarios/baseLanding/safetyCoverage/dataCompletenessBand/orderAnomaly/caveats。
    **不是录取概率**：没有 likelihood/slipRisk；缺数据是 unknown/数据缺口。
    """
    payload: Dict[str, Any] = {"planVersion": plan_version}
    if admission_mode:
        payload["admissionMode"] = admission_mode
    if counterfactual:
        payload["counterfactual"] = counterfactual
    return await http_client.post(
        endpoint=(
            f"/gaotu-assistant-bot/inner/planning/{tenant_id}/session/plan/admission-interpretation"
            f"?chatSessionId={chat_session_id}"
        ),
        json_data=payload,
        error_msg="录取解读失败",
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


# ── 对话访问票据 ──────────────────────────────────────────────────


async def consume_ws_ticket(ticket: str, origin: str | None) -> Dict[str, Any] | None:
    """用票据换回身份。**只有内部可信调用方**能调这个端点。

    身份由 Java 返回，Gateway 不解析 WS 报文或 query 串里的任何身份字段——
    解析权留在服务端，浏览器只能出示票。
    """
    response = await http_client.post(
        endpoint="/gaotu-assistant-bot/inner/conversation/ws-ticket/consume",
        json_data={},
        params={"ticket": ticket},
        headers={"Origin": origin} if origin else None,
        error_msg="兑换对话票据失败",
    )
    if not isinstance(response, dict):
        return None
    # 票无效时 Java 返回 HTTP 403，HttpClient 会抛错；走到这里的都是有效响应。
    data = response.get("data")
    return data if isinstance(data, dict) else None


# ── 录取分数查询 ──────────────────────────────────────────────────


def _evidence_scope_params(
    tenant_id: Union[str, int, None],
    chat_session_id: Union[str, int, None],
    thread_id: Optional[str],
) -> Dict[str, Any]:
    """把证据签发范围拼成 Java 侧声明的 @RequestParam 查询串。

    scope 走查询串，不走 header、也不塞进 JSON body：
    - Java 侧 `GaotuClientDebugController` 已经把它声明成 `@RequestParam`，这是 Java 定的形状；
    - 走 header 要同时改两个仓库，两边发版不同步期间会静默退回「不签发」；
    - 塞进 body 会污染业务参数，而 Java 用 body 算 paramsDigest——
      scope 一旦进 body，同一查询在不同会话里会算出不同的参数摘要，台账就失去按查询聚合的能力。
    """
    params: Dict[str, Any] = {}
    if tenant_id is not None and str(tenant_id).strip():
        params["tenantId"] = tenant_id
    if chat_session_id is not None and str(chat_session_id).strip():
        params["chatSessionId"] = chat_session_id
    if thread_id is not None and str(thread_id).strip():
        params["threadId"] = thread_id
    return params


async def query_program_by_limit_num(
    prepare_type: str,
    subject_type: str,
    score: int,
    subjects: str,
    area_id: str,
    batch: str,
    record_num_limit: int = 10,
    tenant_id: Union[str, int, None] = None,
    chat_session_id: Union[str, int, None] = None,
    thread_id: Optional[str] = None,
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
        tenant_id: 证据签发范围-租户ID（可选，不传则不签发证据）
        chat_session_id: 证据签发范围-会话ID（可选）
        thread_id: 证据签发范围-线程ID（可选）

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
        params=_evidence_scope_params(tenant_id, chat_session_id, thread_id),
        error_msg="查询院校录取方案失败",
    )


async def query_school_major_score_line(
    area_id: str,
    batch: str,
    school_id: str,
    major_id: str = "",
    year: int = 2025,
    subject_type: str = "",
    group_code: str = "",
    tenant_id: Union[str, int, None] = None,
    chat_session_id: Union[str, int, None] = None,
    thread_id: Optional[str] = None,
) -> Dict[str, Any]:
    """查询院校专业历年录取分数线。

    Args:
        area_id: 地区ID
        batch: 批次
        school_id: 学校ID
        major_id: 专业ID（可选，不传则查学校整体分数线）
        year: 年份（可选，0表示查多年）
        subject_type: 科目类型
        group_code: 专业组代码（major_group 模式必填；学生调用方不得丢弃）
        tenant_id: 证据签发范围-租户ID（可选，不传则不签发证据）
        chat_session_id: 证据签发范围-会话ID（可选）
        thread_id: 证据签发范围-线程ID（可选）

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
        "groupCode": group_code,
    }
    logger.info("查询分数线: school_id={}, major_id={}, group_code={}, area_id={}, batch={}, year={}, subject_type={}", school_id, major_id, group_code, area_id, batch, year, subject_type)
    return await http_client.post(
        endpoint="/gaotu-assistant-bot/inner/gaotu/score-line/query",
        json_data=payload,
        params=_evidence_scope_params(tenant_id, chat_session_id, thread_id),
        error_msg="查询分数线失败",
    )
