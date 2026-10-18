"""Batch B3：TaskDraft 的 Redis 账本（作用域/大小/TTL/降级）。"""

from __future__ import annotations

import json

import pytest
import redis.asyncio as redis_asyncio

from app.gateway.task_ledger import RedisTaskLedger


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int | None] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.data[key] = value
        self.ttls[key] = ex
        return True

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def delete(self, key: str) -> int:
        self.data.pop(key, None)
        return 1


def _ledger(monkeypatch: pytest.MonkeyPatch, *, max_bytes: int = 16 * 1024) -> tuple[RedisTaskLedger, FakeRedis]:
    fake = FakeRedis()
    monkeypatch.setattr(
        redis_asyncio,
        "from_url",
        lambda *args, **kwargs: fake,
    )
    return RedisTaskLedger("redis://fake", max_bytes=max_bytes), fake


@pytest.mark.asyncio
async def test_task_ledger_roundtrip_is_scoped_by_tenant_and_session(monkeypatch):
    ledger, fake = _ledger(monkeypatch)
    task = {
        "intentDraft": {"sourceTurnId": "t1", "action": "add"},
        "changeSet": {"status": "needs_constraints_first", "operations": []},
        "turnId": "turn-1",
    }

    assert await ledger.save("tenant-1", "session-1", task) is True
    assert fake.ttls["conversation-task:tenant-1:session-1"] == 7 * 24 * 60 * 60
    assert await ledger.load("tenant-1", "session-1") == task
    assert await ledger.load("tenant-2", "session-1") is None
    assert await ledger.load("tenant-1", "session-2") is None

    await ledger.clear("tenant-1", "session-1")
    assert await ledger.load("tenant-1", "session-1") is None


@pytest.mark.asyncio
async def test_task_ledger_rejects_oversized_payload_without_raising(monkeypatch):
    ledger, fake = _ledger(monkeypatch, max_bytes=64)
    task = {"blob": "x" * 200}

    assert await ledger.save("tenant-1", "session-1", task) is False
    assert fake.data == {}
    assert await ledger.load("tenant-1", "session-1") is None


@pytest.mark.asyncio
async def test_task_ledger_bad_json_degrades_to_none(monkeypatch):
    ledger, fake = _ledger(monkeypatch)
    fake.data["conversation-task:tenant-1:session-1"] = "{not-json"

    assert await ledger.load("tenant-1", "session-1") is None


@pytest.mark.asyncio
async def test_task_ledger_rejects_braces_in_scope(monkeypatch):
    ledger, _ = _ledger(monkeypatch)

    with pytest.raises(ValueError):
        await ledger.save("tenant{1}", "session-1", {})
