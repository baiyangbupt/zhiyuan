from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from app.gateway.service import GatewayService
from app.gateway.artifact_store import SqliteArtifactStore
from app.gateway.ui_events import SessionKey


class FakeClock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class FakeLegacyClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []
        self.on_message: Callable[[dict[str, str]], Awaitable[None]] | None = None

    async def handle_message(self, **kwargs: str) -> str:
        self.calls.append(kwargs)
        reply = f"reply-{len(self.calls)}:{kwargs['content']}"
        if self.on_message is not None:
            await self.on_message(kwargs)
        return reply


class FakeMessageStore:
    def __init__(self) -> None:
        self.users: list[tuple[str, str]] = []
        self.agents: list[tuple[str, str, str]] = []

    async def save_user_message(self, session_id: str, content: str) -> None:
        self.users.append((session_id, content))

    async def save_agent_message(self, session_id: str, content: str, kind: str) -> None:
        self.agents.append((session_id, content, kind))


def _unexpected_loader(**kwargs: Any) -> None:
    raise AssertionError("legacy cache tests must not call external loaders")


def _gateway(**cache_options: Any) -> GatewayService:
    return GatewayService(
        mode="legacy",
        codex=None,
        legacy=FakeLegacyClient(),
        message_store=FakeMessageStore(),
        binding_loader=_unexpected_loader,
        snapshot_loader=_unexpected_loader,
        **cache_options,
    )


async def _turn(
    gateway: GatewayService,
    turn_id: str = "turn-1",
    content: str = "hello",
    *,
    tenant_id: str = "tenant-1",
    session_id: str = "session-1",
) -> dict[str, Any]:
    return await gateway.handle_turn(
        tenant_id=tenant_id,
        session_id=session_id,
        user_id="user-1",
        turn_id=turn_id,
        content=content,
    )


def _key(
    turn_id: str = "turn-1",
    *,
    tenant_id: str = "tenant-1",
    session_id: str = "session-1",
) -> tuple[SessionKey, str]:
    return SessionKey(tenant_id=tenant_id, session_id=session_id), turn_id


@pytest.mark.asyncio
async def test_default_capacity_is_bounded_without_configuration() -> None:
    gateway = _gateway()

    for turn_number in range(1025):
        await _turn(gateway, str(turn_number))

    assert len(gateway._turn_cache) == 1024
    assert _key("0") not in gateway._turn_cache


@pytest.mark.asyncio
async def test_retained_response_is_identical_without_repeating_side_effects() -> None:
    gateway = _gateway(turn_cache_max_entries=2)
    first = await _turn(gateway)

    retained = await _turn(gateway)

    assert retained is first
    assert len(gateway.legacy.calls) == 1
    assert gateway.message_store.users == [("session-1", "hello")]
    assert gateway.message_store.agents == [("session-1", first["reply"], "reply")]


@pytest.mark.asyncio
async def test_retained_changed_content_is_rejected_without_replacing_response() -> None:
    gateway = _gateway(turn_cache_max_entries=2)
    first = await _turn(gateway)

    conflict = await _turn(gateway, content="changed")

    assert conflict == {
        "mode": "legacy",
        "reply": "同一回合编号对应了不同内容，请重新发起本次请求。",
        "events": [],
        "snapshotVersion": first["snapshotVersion"],
        "writeAttempted": False,
        "error": "turn_id_input_conflict",
    }
    assert await _turn(gateway) is first
    assert len(gateway.legacy.calls) == 1
    assert len(gateway.message_store.users) == 1


@pytest.mark.asyncio
async def test_capacity_is_global_fifo_and_result_digest_eviction_is_coupled() -> None:
    gateway = _gateway(turn_cache_max_entries=2)
    await _turn(gateway, "old")
    retained = await _turn(gateway, "retained", tenant_id="tenant-2")
    await _turn(gateway, "old")

    await _turn(gateway, "new", session_id="session-2")

    assert set(gateway._turn_cache) == {
        _key("retained", tenant_id="tenant-2"),
        _key("new", session_id="session-2"),
    }
    assert await _turn(gateway, "retained", tenant_id="tenant-2") is retained
    replay = await _turn(gateway, "old", "changed after eviction")
    assert "error" not in replay
    assert len(gateway.legacy.calls) == 4
    entry = gateway._turn_cache[_key("old")]
    assert entry.result is replay
    assert entry.input_digest == hashlib.sha256(b"changed after eviction").hexdigest()
    assert len(gateway._turn_cache) == 2


@pytest.mark.asyncio
async def test_default_ttl_expires_at_one_hour() -> None:
    clock = FakeClock()
    gateway = _gateway(turn_cache_clock=clock)
    first = await _turn(gateway)
    clock.advance(3599)
    assert await _turn(gateway) is first

    clock.advance(1)
    replay = await _turn(gateway, content="changed after expiry")

    assert "error" not in replay
    assert len(gateway.legacy.calls) == 2


@pytest.mark.asyncio
async def test_ttl_does_not_slide_on_hits_or_conflicts_and_removes_the_digest() -> None:
    clock = FakeClock()
    gateway = _gateway(turn_cache_ttl_seconds=10, turn_cache_clock=clock)
    first = await _turn(gateway)
    clock.advance(9)
    assert await _turn(gateway) is first
    assert (await _turn(gateway, content="changed"))["error"] == "turn_id_input_conflict"

    clock.advance(1)
    replay = await _turn(gateway, content="changed")

    assert "error" not in replay
    assert replay is not first
    assert len(gateway.legacy.calls) == 2
    entry = gateway._turn_cache[_key()]
    assert entry.result is replay
    assert entry.input_digest == hashlib.sha256(b"changed").hexdigest()
    assert entry.expires_at == clock() + 10


@pytest.mark.asyncio
async def test_cache_hit_prunes_expired_entries_from_other_sessions() -> None:
    clock = FakeClock()
    gateway = _gateway(turn_cache_ttl_seconds=10, turn_cache_clock=clock)
    await _turn(gateway, "old", session_id="old-session")
    clock.advance(5)
    retained = await _turn(gateway, "retained")

    clock.advance(5)
    assert await _turn(gateway, "retained") is retained

    assert set(gateway._turn_cache) == {_key("retained")}
    assert len(gateway.legacy.calls) == 2


@pytest.mark.asyncio
async def test_ttl_starts_at_completion_and_prunes_again_after_awaiting_client() -> None:
    clock = FakeClock()
    gateway = _gateway(turn_cache_ttl_seconds=10, turn_cache_clock=clock)
    await _turn(gateway, "old", session_id="old-session")

    async def slow_reply(message: dict[str, str]) -> None:
        clock.advance(20)

    gateway.legacy.on_message = slow_reply
    completed = await _turn(gateway, "slow")
    gateway.legacy.on_message = None

    assert set(gateway._turn_cache) == {_key("slow")}
    clock.advance(9)
    assert await _turn(gateway, "slow") is completed
    clock.advance(1)
    assert await _turn(gateway, "slow") is not completed
    assert len(gateway.legacy.calls) == 3


@pytest.mark.asyncio
async def test_tenant_and_session_remain_part_of_the_cache_key() -> None:
    gateway = _gateway(turn_cache_max_entries=3)
    first = await _turn(gateway)
    other_tenant = await _turn(gateway, content="other tenant", tenant_id="tenant-2")
    other_session = await _turn(gateway, content="other session", session_id="session-2")

    assert await _turn(gateway) is first
    assert await _turn(gateway, content="other tenant", tenant_id="tenant-2") is other_tenant
    assert await _turn(gateway, content="other session", session_id="session-2") is other_session
    assert len(gateway.legacy.calls) == 3


@pytest.mark.asyncio
async def test_eviction_preserves_locked_session_waiters_threads_and_artifacts(tmp_path) -> None:
    clock = FakeClock()
    gateway = _gateway(
        turn_cache_max_entries=1,
        turn_cache_ttl_seconds=10,
        turn_cache_clock=clock,
    )
    key = _key()[0]
    await _turn(gateway, "seed")
    lock = gateway._session_locks[key]
    snapshot = object()
    working_set = object()
    store = SqliteArtifactStore(str(tmp_path / "artifacts.sqlite3"))
    artifact = store.issue(
        tenant_id="tenant-1", session_id="session-1", thread_id="active-thread",
        artifact_type="candidate", state_version=42, tool_name="recommendation.preview_candidates",
        arguments={}, payload={"items": []},
    )
    gateway._threads[key] = "active-thread"
    gateway._snapshots[key] = snapshot
    gateway._working_sets[key] = working_set
    gateway.artifact_store = store
    started = asyncio.Event()
    release = asyncio.Event()

    async def block_first(message: dict[str, str]) -> None:
        if message["content"] == "blocked":
            started.set()
            await release.wait()

    gateway.legacy.on_message = block_first
    running = asyncio.create_task(_turn(gateway, "running", "blocked"))
    await started.wait()
    waiting = asyncio.create_task(_turn(gateway, "waiting", "queued"))
    try:
        await asyncio.sleep(0)
        clock.advance(10)
        for turn_number in range(3):
            await _turn(gateway, str(turn_number), session_id=f"other-{turn_number}")

        assert len(gateway._turn_cache) == 1
        assert gateway._session_locks[key] is lock
        assert lock.locked()
        assert gateway._threads[key] == "active-thread"
        assert gateway._snapshots[key] is snapshot
        assert gateway._working_sets[key] is working_set
        assert store.get_many(tenant_id="tenant-1", session_id="session-1", artifact_ids=[artifact["artifactId"]])
        assert not any(message["content"] == "queued" for message in gateway.legacy.calls)
        assert gateway.user_turn_watermark(tenant_id="tenant-1", session_id="session-1") == 3
    finally:
        release.set()
        await asyncio.gather(running, waiting)

    assert gateway._session_locks[key] is lock
    assert not lock.locked()
    assert gateway.legacy.calls[-1]["content"] == "queued"
    assert store.get_many(tenant_id="tenant-1", session_id="session-1", artifact_ids=[artifact["artifactId"]])


@pytest.mark.asyncio
async def test_concurrent_identical_turns_share_the_retained_response() -> None:
    gateway = _gateway(turn_cache_max_entries=1)

    first, duplicate = await asyncio.gather(_turn(gateway), _turn(gateway))

    assert duplicate is first
    assert len(gateway.legacy.calls) == 1


@pytest.mark.asyncio
async def test_failed_turn_does_not_leave_a_response_or_digest() -> None:
    gateway = _gateway(turn_cache_max_entries=1)

    async def fail_reply(message: dict[str, str]) -> None:
        raise RuntimeError("fake client failed")

    gateway.legacy.on_message = fail_reply
    with pytest.raises(RuntimeError, match="fake client failed"):
        await _turn(gateway)

    assert not gateway._turn_cache
    gateway.legacy.on_message = None
    assert "error" not in await _turn(gateway, content="retry after failure")


@pytest.mark.parametrize("capacity", [0, -1, 1.5, True])
def test_invalid_capacity_is_rejected(capacity: Any) -> None:
    with pytest.raises(ValueError, match="turn_cache_max_entries"):
        _gateway(turn_cache_max_entries=capacity)


@pytest.mark.parametrize("ttl", [0, -1, float("inf"), float("-inf"), float("nan")])
def test_invalid_ttl_is_rejected(ttl: float) -> None:
    with pytest.raises(ValueError, match="turn_cache_ttl_seconds"):
        _gateway(turn_cache_ttl_seconds=ttl)
