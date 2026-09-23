"""A7：Thread 恢复与跨回合上下文。

用**真的 `CodexAppServerHarness` 接替身二进制**，不是 mock harness：被测的正是
"resume 失败长什么样、失败之后我们走哪条分支"，把 harness 换成替身对象，等于把
被测的那一层也换成期望。恢复失败的两种形状抄自真实二进制实测（见
`app/gateway/thread_recovery.py` 模块头的记录），替身只回放形状，不发明形状。

这一组用例要钉住的五件事：
1. 两个租户的 sessionId 相同，**不是**同一个用户；
2. Gateway 重启后沿用原 thread（不是新建）；
3. rollout 丢了才允许重建，且重建不动业务状态；
4. 认不出的 resume 失败、以及绑定查询失败，都**不许**落到重建分支；
5. **原生 runtime 重拉之后，死进程的 threadId 一律作废**——不作用废的话，
   下一轮拿旧 id 去 `turn/start`，新进程回 `-32600 thread not found`，
   而那不是 `AppServerExited`、不触发恢复，于是每轮秒失败（实测症状）。
"""
from __future__ import annotations

import asyncio
import os
import uuid
import sys
from pathlib import Path

import pytest

from app.gateway.service import GatewayService
from app.gateway.ui_events import SessionKey
from app.harness.binding import ThreadBinding
from app.harness.codex import CodexAppServerHarness

FAKE_SERVER = Path(__file__).resolve().parents[1] / "fixtures" / "codex" / "fake_app_server.py"


class _RecordingHarness(CodexAppServerHarness):
    """真 harness + 记下 resume 调用。

    只覆写一个方法，JSON-RPC 那条路仍旧是真的——分类逻辑要看的正是
    真实客户端把错误抛成什么样。
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.resumed: list[str] = []

    async def resume_thread(self, thread_id: str) -> dict:
        self.resumed.append(thread_id)
        return await super().resume_thread(thread_id)


class _Backend:
    """替身后端：一张 (tenant, session) → 绑定的表，外加可控故障。"""

    def __init__(
        self,
        bindings: dict[tuple[str, str], str] | None = None,
        error: Exception | None = None,
        payload: dict | None = None,
    ):
        self.bindings = bindings or {}
        self.error = error
        # 原样返回的响应：用来造"后端给了一条不属于本会话的绑定"这种数据问题。
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    async def current(self, tenant_id: str, session_id: str):
        self.calls.append((str(tenant_id), str(session_id)))
        if self.error is not None:
            raise self.error
        if self.payload is not None:
            return self.payload
        thread_id = self.bindings.get((str(tenant_id), str(session_id)))
        if thread_id is None:
            return {"code": 0, "data": None}
        return {
            "code": 0,
            "data": {
                "tenantId": str(tenant_id),
                "chatSessionId": str(session_id),
                "userId": "7",
                "threadId": thread_id,
                "allowedCapabilities": ["catalog_read"],
            },
        }


class FakeMessageStore:
    async def save_user_message(self, chat_session_id: str, content: str) -> int:
        return 1

    async def save_agent_message(self, chat_session_id: str, content: str, ws_type: str = "reply") -> int:
        return 2


def _snapshot(version: int = 42) -> dict:
    return {
        "sessionId": "42",
        "version": version,
        "phase": "candidate_exploration",
        "studentSummary": {"province": "浙江", "score": 650, "rank": 1000},
        "allowedCapabilities": ["catalog_read", "admission_read"],
    }


def _binding(thread_id: str, *, tenant_id: str, session_id: str) -> ThreadBinding:
    return ThreadBinding(
        thread_id=thread_id,
        tenant_id=tenant_id,
        session_id=session_id,
        user_id="7",
        allowed_capabilities=frozenset({"catalog_read", "admission_read"}),
    )


async def _harness() -> _RecordingHarness:
    harness = _RecordingHarness(
        [sys.executable, str(FAKE_SERVER)],
        request_timeout=10.0,
        approval_policy="never",
        sandbox_policy="read-only",
    )
    await harness.start()
    return harness


def _gateway(harness: CodexAppServerHarness, backend: _Backend | None) -> GatewayService:
    async def binding_loader(**kwargs):
        return _binding(
            kwargs["thread_id"],
            tenant_id=str(kwargs["tenant_id"]),
            session_id=str(kwargs["session_id"]),
        )

    return GatewayService(
        mode="codex_readonly",
        codex=harness,
        legacy=None,
        message_store=FakeMessageStore(),
        binding_loader=binding_loader,
        snapshot_loader=lambda **kwargs: _snapshot(),
        current_binding_loader=backend.current if backend is not None else None,
    )


async def _turn(gateway: GatewayService, *, tenant_id: str, session_id: str, turn_id: str = "ui-1"):
    return await gateway.handle_turn(
        tenant_id=tenant_id,
        session_id=session_id,
        user_id="7",
        turn_id=turn_id,
        content="查某校计算机",
    )


@pytest.mark.asyncio
async def test_two_tenants_with_the_same_session_id_do_not_share_a_thread() -> None:
    """两个租户的 sessionId 相同，**不是**同一个用户。

    重建前这里的键是裸 sessionId：租户 2 会命中租户 1 的 thread，把别人的
    上下文当成自己的。所以这条断言的是"两个键"和"两个 thread"，
    不是"没报错"。
    """
    harness = await _harness()
    backend = _Backend({("1", "42"): "thr-tenant-one"})
    gateway = _gateway(harness, backend)
    try:
        await _turn(gateway, tenant_id="1", session_id="42", turn_id="ui-1")
        await _turn(gateway, tenant_id="2", session_id="42", turn_id="ui-2")

        assert set(gateway._threads) == {
            SessionKey(tenant_id="1", session_id="42"),
            SessionKey(tenant_id="2", session_id="42"),
        }
        # 租户 1 用绑定里的 thread；租户 2 没有绑定，拿到的是新建的那个。
        assert gateway._threads[SessionKey(tenant_id="1", session_id="42")] == "thr-tenant-one"
        assert gateway._threads[SessionKey(tenant_id="2", session_id="42")] == "thr_test"
        assert harness.resumed == ["thr-tenant-one"]
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_a_restart_resumes_the_bound_thread_instead_of_rebuilding() -> None:
    """重启 = 进程内 `_threads` 表没了。找回 thread 靠后端绑定，不靠新建。

    断言 resume 打到了**原来那个** thread，且没有新建——新建会让用户
    得到"记得你的资料、不记得你刚说过什么"的对话，而链路上不报任何错。
    """
    harness = await _harness()
    backend = _Backend({("1", "42"): "thr-survived-restart"})
    restarted = _gateway(harness, backend)
    try:
        result = await _turn(restarted, tenant_id="1", session_id="42")

        assert harness.resumed == ["thr-survived-restart"]
        stats = await harness.client.request("test/stats", {})
        assert stats["threadStarts"] == 0, "恢复成功的路径不许新建 thread"
        # 身份从这个 thread 反查回来，仍然带租户——恢复不能把租户信息丢掉。
        assert restarted.scope_for_thread("thr-survived-restart") == SessionKey(
            tenant_id="1", session_id="42"
        )
        assert result.get("reply") is not None
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_a_runtime_restart_drops_the_threads_of_the_dead_process() -> None:
    """进程死掉又重拉之后，缓存里的 threadId 属于**死进程**，不许继续用。

    替身按真实二进制建模：`turn/start` 只认本进程 start/resume 过的 thread
    （`thread_manager.get_thread` 查不到 → `-32600 thread not found`）。
    所以这条用例在"重拉不换 threadId"的实现上会红在第三轮，而不是只在日志里
    留一句看不懂的错。
    """
    harness = await _harness()
    gateway = _gateway(harness, None)  # 没有后端绑定：恢复只能重建
    key = SessionKey(tenant_id="1", session_id="42")
    try:
        first = await _turn(gateway, tenant_id="1", session_id="42")
        assert first.get("reply") is not None
        assert gateway._threads[key] == "thr_test"

        # 直接 kill：要的就是"进程不在了"这个状态。test/exit 是进程自己退出，
        # 唤醒路径相同，但少验了"进程已经死了"。
        assert harness.client.process is not None
        harness.client.process.kill()
        await harness.client.process.wait()

        # 死进程那一轮**如实失败**（不许假装成功），但 runtime 会被重拉。
        dead = await _turn(gateway, tenant_id="1", session_id="42", turn_id="ui-2")
        assert dead["error"] == "app_server_exited"
        assert dead["recoverable"] is True
        assert key not in gateway._threads, "死进程的 threadId 不许留在缓存里"

        # 下一轮在新进程里重新拿 thread（无绑定 → 重建），能正常跑完。
        recovered = await _turn(gateway, tenant_id="1", session_id="42", turn_id="ui-3")
        assert recovered.get("reply") is not None, recovered
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_after_a_runtime_restart_the_bound_thread_is_resumed_not_rebuilt() -> None:
    """重拉换掉的是**进程**，不是 thread：有绑定的会话下一轮 resume 回来。

    与上一条的区别在断言方向：上一条测"旧 id 不许复用"，这条测"恢复仍然优先
    resume"——重拉之后如果改成一律新建，用户会发现它忘了刚说过的话，
    而链路上一切正常。
    """
    harness = await _harness()
    backend = _Backend({("1", "42"): "thr_test"})
    gateway = _gateway(harness, backend)
    try:
        await _turn(gateway, tenant_id="1", session_id="42")
        assert harness.client.process is not None
        harness.client.process.kill()
        await harness.client.process.wait()

        dead = await _turn(gateway, tenant_id="1", session_id="42", turn_id="ui-2")
        assert dead["error"] == "app_server_exited"

        resumed = await _turn(gateway, tenant_id="1", session_id="42", turn_id="ui-3")
        assert resumed.get("reply") is not None, resumed
        assert harness.resumed == ["thr_test", "thr_test"], "重拉之后要 resume，不是新建"
        stats = await harness.client.request("test/stats", {})
        assert stats["threadStarts"] == 0
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_a_lost_rollout_rebuilds_the_thread_and_business_state_survives() -> None:
    """rollout 丢了（真实二进制返回 -32600 "no rollout found"）才允许重建。

    重建换掉的是**模型的上下文**，不是业务状态：业务状态在 Java，本回合仍然
    按 Java 的快照跑。所以这里同时断言"新建了一个 thread"和"快照版本还是
    后端给的那个"。
    """
    harness = await _harness()
    backend = _Backend({("1", "42"): "thr-rollout-lost"})
    gateway = _gateway(harness, backend)
    try:
        await harness.client.request("test/arm_resume", {"mode": "no_rollout"})
        await harness.client.request("test/arm_gate", {})
        progress_seen = asyncio.Event()

        async def emit(event: dict) -> None:
            if event["type"] == "tool.progress":
                progress_seen.set()

        turn_task = asyncio.create_task(
            gateway.handle_turn(
                tenant_id="1",
                session_id="42",
                user_id="7",
                turn_id="ui-1",
                content="查某校计算机",
                emit=emit,
            )
        )
        # 闸门放行前就把话说死：新建必须发生在**跑回合之前**，否则断言可能在
        # 一个还没恢复完的状态上通过。
        await asyncio.wait_for(progress_seen.wait(), timeout=5)
        stats_at_gate = await harness.client.request("test/stats", {})
        assert stats_at_gate["threadStarts"] == 1
        await harness.client.request("test/release", {})
        turn = await asyncio.wait_for(turn_task, timeout=5)

        assert harness.resumed == ["thr-rollout-lost"]
        stats = await harness.client.request("test/stats", {})
        assert stats["threadStarts"] == 1, "resume 不通时才新建"
        thread_id = gateway._threads[SessionKey(tenant_id="1", session_id="42")]
        assert thread_id != "thr-rollout-lost"
        # 业务状态没有被"恢复"这件事动过：快照版本仍是 Java 给的那份。
        assert turn.get("snapshotVersion") == 42
        assert turn.get("workingSet") is not None
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_an_unrecognised_resume_failure_is_recoverable_and_rebuilds_nothing() -> None:
    """认不出的 resume 失败（这里 -32000）**不许**落到重建分支。

    把权限/配置/不兼容当成"thread 没了"，等于用一次静默的身份替换盖掉一次
    真实故障：用户看不出区别，运维也看不出。
    """
    harness = await _harness()
    backend = _Backend({("1", "42"): "thr-existing"})
    gateway = _gateway(harness, backend)
    try:
        await harness.client.request("test/arm_resume", {"mode": "incompatible"})
        result = await _turn(gateway, tenant_id="1", session_id="42")

        assert result["error"] == "thread_resume_failed"
        assert result["recoverable"] is True
        stats = await harness.client.request("test/stats", {})
        assert stats["threadStarts"] == 0, "认不出的失败一律不许新建"
        assert SessionKey(tenant_id="1", session_id="42") not in gateway._threads
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_a_lookup_failure_is_recoverable_and_rebuilds_nothing() -> None:
    """绑定查询失败 ≠ 没有绑定。前者不许新建。

    把后端故障当成"没有绑定"，会把一次故障变成一次上下文丢失——而且丢得
    没有任何痕迹。
    """
    harness = await _harness()
    backend = _Backend(error=RuntimeError("backend down"))
    gateway = _gateway(harness, backend)
    try:
        result = await _turn(gateway, tenant_id="1", session_id="42")

        assert result["error"] == "binding_lookup_failed"
        assert result["recoverable"] is True
        stats = await harness.client.request("test/stats", {})
        assert stats["threadStarts"] == 0
        assert backend.calls == [("1", "42")]
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_a_binding_for_another_session_is_not_silently_rebuilt() -> None:
    """后端按 (租户, 会话) 查出来的东西不属于这个会话时，报错而不是重建。

    这是数据问题，重建会把它掩盖成一个"看起来正常"的新 thread。
    """
    harness = await _harness()
    backend = _Backend(
        payload={
            "code": 0,
            "data": {
                "tenantId": "1",
                "chatSessionId": "999",
                "userId": "7",
                "threadId": "thr-someone-else",
                "allowedCapabilities": ["catalog_read"],
            },
        }
    )
    gateway = _gateway(harness, backend)
    try:
        result = await _turn(gateway, tenant_id="1", session_id="42")

        assert result["error"] == "binding_ownership_mismatch"
        stats = await harness.client.request("test/stats", {})
        assert stats["threadStarts"] == 0
        assert harness.resumed == []
    finally:
        await harness.close()


# ── 跨层：事件窗口失效时，原生卡不跟着失效 ──────────────────────────
# 卡活在 JSON-RPC 请求里（A4 的桥），事件活在流里（A5 的存储）。两者是
# 两条命：流要求 resync 时，用户手上那张卡**必须还是能点的**——否则
# 就是"重连后卡还在，一点就报错"。
REDIS_URL = os.environ.get("CODEX_TEST_REDIS_URL", "")


@pytest.mark.skipif(
    not REDIS_URL, reason="CODEX_TEST_REDIS_URL is required; skipping is not a pass"
)
@pytest.mark.asyncio
async def test_a_native_card_survives_a_replay_window_that_is_gone() -> None:
    from app.gateway.event_store import RedisEventStore
    from app.gateway.user_input import UserInputBroker
    from app.harness.client import AppServerClient

    key = SessionKey(tenant_id=f"a7-{uuid.uuid4().hex[:8]}", session_id="42")
    store = RedisEventStore(REDIS_URL, ttl_seconds=60, max_events=2, max_event_bytes=16 * 1024)
    broker = UserInputBroker(runtime_generation="gen-a7", scope_resolver=lambda _: key)
    client = AppServerClient([sys.executable, str(FAKE_SERVER)], request_timeout=10.0)
    client.server_request_handler = broker.handle_server_request
    await client.start()
    await client.initialize(client_name="zhiyuan-gateway", client_version="1")
    try:
        await client.request("test/request_user_input", {"threadId": "thr_test"})
        card = None
        for _ in range(200):
            cards = broker.snapshot(key)
            if cards:
                card = cards[0]
                break
            await asyncio.sleep(0.01)
        assert card is not None, "澄清卡始终没有出现"

        progress = {
            "type": "tool.progress",
            "sessionId": "42",
            "turnId": "ui-turn-1",
            "payload": {"itemId": "i", "tool": "domain", "status": "started", "label": "正在查询"},
        }
        first = await store.append(key, progress)
        # 一直写到窗口真的被裁掉开头为止。`MAXLEN ~` 是近似裁剪：它按整节点丢，
        # 所以条数少的时候**不会**裁。写死"发 4 条就该裁"的话，这条用例会在
        # 一个根本没进入它要测的状态下通过。
        windowed_out = False
        for index in range(200):
            await store.append(key, {**progress, "turnId": f"ui-turn-{index + 2}"})
            if await store.replay(key, first.stream_epoch, after=0) is None:
                windowed_out = True
                break
        assert windowed_out, "窗口始终没被裁剪，这条用例没测到它要测的东西"
        # 但卡不活在流里——它必须还在。
        assert [item["requestId"] for item in broker.snapshot(key)] == [card["requestId"]]

        # 而且还能答得回去：这才是"卡还在"的可证伪版本。
        outcome = await broker.answer(
            key,
            card["requestId"],
            {"inputKind": "choice", "answers": {"major": {"answers": ["计算机类"]}}},
        )
        assert outcome["status"] == "accepted"
    finally:
        await client.close()
        await store.close()
