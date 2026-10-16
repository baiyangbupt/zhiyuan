"""A5：事件流的原子性、重放与请求幂等。

**必须打真实 Redis。** 内存 mock 证明不了原子性——那正是这里唯一要证的东西：
计数器自增与写流之间不能有缝。缺 `CODEX_TEST_REDIS_URL` 时整文件 skip，
并且不把它记为通过。
"""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any

import pytest

from app.gateway.event_store import (
    ACCEPTED,
    CONFLICT,
    DUPLICATE,
    EventTooLarge,
    RedisEventStore,
)
from app.gateway.ui_events import SessionKey


REDIS_URL = os.environ.get("CODEX_TEST_REDIS_URL", "")

pytestmark = pytest.mark.skipif(
    not REDIS_URL,
    reason="CODEX_TEST_REDIS_URL is required; skipping is not a pass",
)


def _key() -> SessionKey:
    # 每次跑用独立租户：测试之间不共享状态，也不需要 flush 整个库。
    return SessionKey(tenant_id=f"test-{uuid.uuid4().hex[:8]}", session_id="42")


def _event(**overrides: Any) -> dict[str, Any]:
    event = {
        "type": "tool.progress",
        "sessionId": "42",
        "turnId": "ui-turn-1",
        "payload": {"itemId": "i", "tool": "domain", "status": "started", "label": "正在处理查询"},
    }
    event.update(overrides)
    return event


@pytest.fixture
async def store():
    instance = RedisEventStore(
        REDIS_URL, ttl_seconds=120, max_events=2000, max_event_bytes=16 * 1024
    )
    yield instance
    await instance.close()


async def test_concurrent_appends_get_dense_unique_sequences(store) -> None:
    """200 个并发追加：编号必须连续且唯一。

    这不是性能测试。它要证的是"编号分配与事件写入之间没有缝"——
    一旦拆成两个 await，并发下必然出现跳号或重号。
    """
    key = _key()

    appended = await asyncio.gather(*(store.append(key, _event()) for _ in range(200)))
    sequences = sorted(event.sequence for event in appended)

    assert sequences == list(range(1, 201))
    replayed = await store.replay(key, appended[0].stream_epoch, 0)
    assert replayed is not None
    assert [event.sequence for event in replayed] == list(range(1, 201))


async def test_two_tenants_sharing_a_session_id_do_not_mix(store) -> None:
    """同 sessionId 不同租户是两个人，事件流不能串。"""
    # tenant 名每次唯一：键有 TTL，用固定名重跑会读到上一轮的残留。
    suffix = uuid.uuid4().hex[:8]
    tenant_a = SessionKey(tenant_id=f"tenant-a-{suffix}", session_id="42")
    tenant_b = SessionKey(tenant_id=f"tenant-b-{suffix}", session_id="42")

    await store.append(tenant_a, _event(payload={"label": "A"}))
    await store.append(tenant_a, _event(payload={"label": "B"}))
    await store.append(tenant_b, _event(payload={"label": "C"}))
    epoch_a = (await store.append(tenant_a, _event())).stream_epoch

    # 用 A 的代际去读 B：代际不同 → 明确要 resync，而不是返回 B 的事件。
    assert await store.replay(tenant_b, epoch_a, after=0) is None
    assert await store.watermark(tenant_a) == 3
    assert await store.watermark(tenant_b) == 1


async def test_replay_returns_only_events_after_cursor(store) -> None:
    key = _key()

    first = await store.append(key, _event())
    for _ in range(4):
        await store.append(key, _event())

    tail = await store.replay(key, first.stream_epoch, after=2)

    assert tail is not None
    assert [event.sequence for event in tail] == [3, 4, 5]


async def test_replay_requires_resync_when_generation_changed(store) -> None:
    key = _key()
    await store.append(key, _event())

    assert await store.replay(key, "epoch-from-another-life", after=1) is None


async def test_current_epoch_matches_the_one_events_carry(store) -> None:
    """重连补发要按**当前**代际读，而服务端手上没有客户端游标——读法归存储。

    没有它，调用方只能"先摸一条事件出来取代际"：空流时摸不到，于是重连
    在"还没有任何事件"的会话上要么猜、要么跳过补发。
    """
    key = _key()
    assert await store.current_epoch(key) is None  # 还没有任何事件

    appended = await store.append(key, _event())
    epoch = await store.current_epoch(key)

    assert epoch == appended.stream_epoch
    # 拿到代际就能直接重放：这正是重连那条路径要的两步。
    assert await store.replay(key, epoch, after=0) is not None


async def test_replay_requires_resync_when_cursor_is_ahead(store) -> None:
    """cursor 超前说明客户端记的是另一条时间线，不能让它无限等。"""
    key = _key()
    appended = await store.append(key, _event())

    assert await store.replay(key, appended.stream_epoch, after=999) is None


async def test_replay_requires_resync_when_window_was_trimmed(store) -> None:
    """流被 MAXLEN 裁过之后，补齐会留下一个看不见的洞——必须 resync。"""
    key = _key()
    for _ in range(5):
        await store.append(key, _event())
    stream = f"conv:{{{key.tenant_id}:{key.session_id}}}:stream"
    # 裁到只剩最近 2 条（序列 4、5），模拟保留窗口滑走。
    await store._redis.xtrim(stream, maxlen=2, approximate=False)
    epoch = (await store.append(key, _event())).stream_epoch  # 序列 6

    # 流里最早是 4，而客户端只要 1 之后的 → 中间有洞 → resync。
    assert await store.replay(key, epoch, after=0) is None
    # 从 4 之后要则完全落在窗口内，可以补齐。
    tail = await store.replay(key, epoch, after=4)
    assert tail is not None
    assert [event.sequence for event in tail] == [5, 6]


async def test_replay_survives_a_new_store_instance(store) -> None:
    """"进程重启"= 换一个客户端对象；数据必须还在 Redis 里，不在进程内存里。"""
    key = _key()
    appended = await store.append(key, _event(turnId="ui-turn-restart"))

    from app.gateway.event_store import RedisEventStore as Store

    second = Store(REDIS_URL, ttl_seconds=120)
    try:
        replayed = await second.replay(key, appended.stream_epoch, after=0)
    finally:
        await second.close()

    assert replayed is not None
    assert [event.turn_id for event in replayed] == ["ui-turn-restart"]


async def test_admit_distinguishes_duplicate_from_conflict(store) -> None:
    key = _key()

    assert await store.admit(key, "req-1", "digest-a") == ACCEPTED
    assert await store.admit(key, "req-1", "digest-a") == DUPLICATE
    # 同 id 不同内容不是"重发"，是客户端把两个请求搞混了。
    assert await store.admit(key, "req-1", "digest-b") == CONFLICT
    assert await store.admit(key, "req-2", "digest-a") == ACCEPTED


async def test_finish_request_persists_the_result_reference(store) -> None:
    key = _key()
    await store.admit(key, "req-1", "digest-a")

    assert await store.request_result(key, "req-1") is None
    await store.finish_request(key, "req-1", "operation-7")
    assert await store.request_result(key, "req-1") == "operation-7"


async def test_request_reservation_lives_as_long_as_its_recoverable_result(store) -> None:
    key = _key()
    await store.admit(key, "req-1", "digest-a")
    request_key = f"conv:{{{key.tenant_id}:{key.session_id}}}:req:req-1"
    await store._redis.pexpire(request_key, 1000)
    await store.finish_request(key, "req-1", "operation-7")
    assert await store._redis.pttl(request_key) > 100_000
    assert await store.admit(key, "req-1", "digest-a") == DUPLICATE


async def test_expired_reservation_does_not_create_a_free_standing_result(store) -> None:
    key = _key()
    await store.finish_request(key, "never-admitted", "operation-7")
    assert await store.request_result(key, "never-admitted") is None


async def test_runtime_busy_retry_and_receipt_recovery_use_the_real_store(store) -> None:
    from app.gateway.session_runtime import BUSY, SessionRuntime

    runtime = SessionRuntime(store=store)
    key = _key()
    gate = asyncio.Event()
    calls = []

    async def work():
        calls.append("retry")
        return {"reply": "done"}

    assert await runtime.submit(key, client_request_id="first", ui_turn_id="first", work=gate.wait) == ACCEPTED
    first_task = runtime._tasks[key]
    assert await runtime.submit(key, client_request_id="retry", ui_turn_id="original", request_digest="content", work=work) == BUSY
    gate.set()
    await first_task
    assert await runtime.submit(key, client_request_id="retry", ui_turn_id="original", request_digest="content", work=work) == ACCEPTED
    await runtime._tasks[key]
    second_store = RedisEventStore(REDIS_URL, ttl_seconds=120)
    try:
        restarted = SessionRuntime(store=second_store)
        assert await restarted.submit(key, client_request_id="retry", ui_turn_id="new", request_digest="content", work=work) == DUPLICATE
        assert await restarted.request_status(key, "retry") == {"status": "completed", "turnId": "original"}
    finally:
        await second_store.close()
    assert calls == ["retry"]


async def test_unknown_event_type_is_rejected_before_it_reaches_the_stream(store) -> None:
    key = _key()

    with pytest.raises(ValueError, match="unknown_ui_event_type"):
        await store.append(key, _event(type="totally.made.up"))

    assert await store.watermark(key) == 0


async def test_oversized_event_is_refused_instead_of_truncated(store) -> None:
    """超限必须换 Artifact 引用。截断后的 JSON 既不是原事件也解析不了。"""
    key = _key()

    with pytest.raises(EventTooLarge):
        await store.append(key, _event(payload={"blob": "x" * (16 * 1024)}))

    assert await store.watermark(key) == 0


async def test_event_store_refuses_to_start_without_a_url() -> None:
    from app.gateway.event_store import EventStoreUnavailable

    with pytest.raises(EventStoreUnavailable):
        RedisEventStore("")


async def test_session_key_with_braces_is_refused(store) -> None:
    """花括号会改变 Redis 槽的解析，进而让"同会话同槽"这个前提失效。"""
    with pytest.raises(ValueError, match="must_not_contain_braces"):
        await store.append(SessionKey(tenant_id="t{", session_id="42"), _event())


async def test_watermark_and_replay_handoff_loses_and_duplicates_nothing(store) -> None:
    """A3/A7 恢复合同里最脆的一段：截水位之后、发重放之前又有事件写进来。

    store 本身**不加锁**（锁在 A3 的会话运行时里），它保证的是另一件事：
    编号稠密且单调。订阅方据此就能算出"我手上没有哪几条"——
    按 sequence 去重，既不丢也不重复渲染，不需要和写入方额外协调。
    """
    key = _key()
    first = await store.append(key, _event(turnId="ui-turn-1"))
    await store.append(key, _event(turnId="ui-turn-2"))

    high_water = await store.watermark(key)  # 订阅方准备切换的瞬间
    await store.append(key, _event(turnId="ui-turn-3"))  # 切换窗口内到达
    await store.append(key, _event(turnId="ui-turn-4"))

    replayed = await store.replay(key, first.stream_epoch, after=0)

    assert high_water == 2
    assert replayed is not None
    assert [event.sequence for event in replayed] == [1, 2, 3, 4]
    # 水位之后的两条既在重放里、也可能随后从订阅里再来一次：编号让去重可判。
    beyond_water = [event for event in replayed if event.sequence > high_water]
    assert [event.turn_id for event in beyond_water] == ["ui-turn-3", "ui-turn-4"]
