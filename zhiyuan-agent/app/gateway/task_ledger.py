"""有界 TaskDraft 的跨重启存储（Redis）。

它只存**任务元数据**（intentDraft/changeSet/剩余项），不是方案或 pending 的
真值；方案/约束/pending 仍以 Java 业务状态为准。键按 tenant+session 隔离，
TTL 7 天，单条有大小上限；Redis 不可用时降级为“无任务”，不阻塞对话。
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_TASK_TTL_SECONDS = 7 * 24 * 60 * 60
_MAX_TASK_BYTES = 16 * 1024


class RedisTaskLedger:
    def __init__(self, redis_url: str, *, ttl_seconds: int = _TASK_TTL_SECONDS,
                 max_bytes: int = _MAX_TASK_BYTES) -> None:
        if not redis_url:
            raise ValueError("task ledger redis url is not configured")
        import redis.asyncio as redis_asyncio

        self._redis = redis_asyncio.from_url(redis_url, decode_responses=True)
        self._ttl = int(ttl_seconds)
        self._max_bytes = int(max_bytes)

    @classmethod
    def from_settings(cls) -> "RedisTaskLedger | None":
        """按事件流同一个 Redis 配置创建；没配置就返回 None（显式降级）。"""
        try:
            from app.config import ConversationEventStoreConfig

            url = ConversationEventStoreConfig().redis_url
        except Exception:  # pragma: no cover - 配置异常不应阻塞启动
            return None
        return cls(url) if url else None

    @staticmethod
    def _key(tenant_id: str, session_id: str) -> str:
        tenant = str(tenant_id)
        session = str(session_id)
        if "{" in tenant or "}" in tenant or "{" in session or "}" in session:
            raise ValueError("session_key_must_not_contain_braces")
        return f"conversation-task:{tenant}:{session}"

    async def load(self, tenant_id: str, session_id: str) -> dict[str, Any] | None:
        key = self._key(tenant_id, session_id)
        try:
            raw = await self._redis.get(key)
        except Exception as exc:  # noqa: BLE001 - 任务账本失败不阻塞回合
            logger.warning("task ledger load failed (tenant=%s session=%s): %s",
                           tenant_id, session_id, type(exc).__name__)
            return None
        if not raw:
            return None
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            logger.warning("task ledger payload is unreadable (tenant=%s session=%s)",
                           tenant_id, session_id)
            return None
        return value if isinstance(value, dict) else None

    async def save(self, tenant_id: str, session_id: str, task: dict[str, Any]) -> bool:
        key = self._key(tenant_id, session_id)
        try:
            raw = json.dumps(task, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            return False
        if len(raw.encode("utf-8")) > self._max_bytes:
            logger.warning("task ledger payload too large (tenant=%s session=%s bytes=%s)",
                           tenant_id, session_id, len(raw.encode("utf-8")))
            return False
        try:
            await self._redis.set(key, raw, ex=self._ttl)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("task ledger save failed (tenant=%s session=%s): %s",
                           tenant_id, session_id, type(exc).__name__)
            return False

    async def clear(self, tenant_id: str, session_id: str) -> None:
        key = self._key(tenant_id, session_id)
        try:
            await self._redis.delete(key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("task ledger clear failed (tenant=%s session=%s): %s",
                           tenant_id, session_id, type(exc).__name__)
