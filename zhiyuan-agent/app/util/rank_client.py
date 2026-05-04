"""排名服务 HTTP 客户端，直接调用 rank-service 的无状态接口。

用于 adhoc 场景（为他人咨询），绕过 Java 后端的 session 绑定。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import aiohttp
from loguru import logger

from app.config import RankServiceConfig


class RankClient:
    """rank-service HTTP 客户端。"""

    def __init__(self) -> None:
        config = RankServiceConfig()
        self.base_url = config.url.rstrip("/")

    async def recommend_submajor(
        self,
        studentinfo: Dict[str, Any],
        top_n: int = 8,
    ) -> Dict[str, Any]:
        """调用 rank-service 的专业类推荐接口。

        Args:
            studentinfo: 学生信息字典
            top_n: 返回推荐数量

        Returns:
            推荐结果，包含 reconmandlist 等字段
        """
        url = f"{self.base_url}/gaokao-volunteer-rank/recommend_submajor"
        payload = {"studentinfo": studentinfo, "topN": top_n}
        return await self._post(url, payload, "专业类推荐")

    async def query_weight(
        self,
        studentinfo: Dict[str, Any],
        queryinfo: Dict[str, Any],
        profileinfo: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """调用 rank-service 的权重查询接口（专业/学校对比）。

        Args:
            studentinfo: 学生信息字典
            queryinfo: 查询信息，包含 type 和 querylist
            profileinfo: 画像信息，可为空时使用默认值

        Returns:
            权重查询结果
        """
        if profileinfo is None:
            profileinfo = {
                "schoolList": [],
                "majorList": [],
                "cityList": [],
            }
        url = f"{self.base_url}/gaokao-volunteer-rank/query_weight"
        payload = {
            "studentinfo": studentinfo,
            "queryinfo": queryinfo,
            "profileinfo": profileinfo,
        }
        return await self._post(url, payload, "权重查询")

    async def _post(
        self,
        url: str,
        payload: Dict[str, Any],
        desc: str,
    ) -> Dict[str, Any]:
        """发送 POST 请求到 rank-service。"""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=payload, headers=headers
                ) as response:
                    result = await response.json()
                    if response.status != 200:
                        logger.error("rank-service %s失败: %s, %s", desc, response.status, result)
                    return result
        except Exception as e:
            logger.error("rank-service %s异常: %s", desc, e)
            return {"error": str(e)}


# 全局实例
rank_client = RankClient()
