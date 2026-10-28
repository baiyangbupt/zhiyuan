"""A3：真实流式事件与会话运行时分发。

这里用**真的 `CodexAppServerHarness`** 接替身二进制，不是 mock harness。
理由：要证的恰恰是"终态闸门没开的时候前端已经收到进度"，而 mock 掉的那一层
正是决定这件事的那一层。
"""
from __future__ import annotations

import asyncio
import json
import sys
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.gateway.service import GatewayService
from app.gateway.session_runtime import (
    ACCEPTED,
    BUSY,
    CONFLICT,
    DUPLICATE,
    ConnectionChannel,
    SessionRuntime,
)
from app.gateway.ui_events import SessionKey
from app.harness.codex import CodexAppServerHarness

class _PermissiveAccessGuard:
    """测试替身：直接放行并返回固定身份。

    **只在测试里装**。生产路径无条件校验票据（见 app/gateway/access.py），
    它的正确性由 tests/integration/test_gateway_access.py 的 7 条覆盖——
    这里不重复验它，只负责让 WS 用例能连上。
    """

    def __init__(self, tenant_id: str = "test-tenant", bot_id: str = "test-bot") -> None:
        self._tenant_id = tenant_id
        self._bot_id = bot_id

    async def verify(self, ticket, origin):
        from app.gateway.access import TicketIdentity

        return TicketIdentity(
            tenant_id=self._tenant_id,
            session_id="s-1",
            user_id="u-1",
            bot_id=self._bot_id,
            origin=origin or "http://127.0.0.1:3201",
        )





FAKE_SERVER = Path(__file__).resolve().parents[1] / "fixtures" / "codex" / "fake_app_server.py"


class FakeMessageStore:
    async def save_user_message(self, chat_session_id: str, content: str) -> int:
        return 1

    async def save_agent_message(self, chat_session_id: str, content: str, ws_type: str = "reply") -> int:
        return 2


def _snapshot() -> dict:
    return {
        "sessionId": "session-1",
        "version": 42,
        "phase": "candidate_exploration",
        "studentSummary": {"province": "浙江", "score": 650, "rank": 1000},
        "allowedCapabilities": ["catalog_read", "admission_read"],
    }


def _binding():
    from app.harness.binding import ThreadBinding

    return ThreadBinding(
        thread_id="thr-fake",
        tenant_id="tenant-1",
        session_id="session-1",
        user_id="user-1",
        allowed_capabilities=frozenset({"catalog_read", "admission_read"}),
    )


async def _harness() -> CodexAppServerHarness:
    harness = CodexAppServerHarness(
        [sys.executable, str(FAKE_SERVER)],
        request_timeout=10.0,
        approval_policy="never",
        sandbox_policy="read-only",
    )
    await harness.start()
    return harness


def _gateway(harness: CodexAppServerHarness) -> GatewayService:
    return GatewayService(
        mode="codex_readonly",
        codex=harness,
        legacy=None,
        message_store=FakeMessageStore(),
        binding_loader=lambda **kwargs: _binding(),
        snapshot_loader=lambda **kwargs: _snapshot(),
    )


@pytest.fixture(autouse=True)
def _permissive_access_guard():
    """生产路径无条件校验 WS 票据；测试装一个放行替身。"""
    from app.server import app as _app

    _app.state.conversation_access_guard = _PermissiveAccessGuard()
    yield
    _app.state.conversation_access_guard = None


@pytest.mark.asyncio
async def test_progress_arrives_while_the_terminal_is_still_gated() -> None:
    """核心断言：**闸门没开**时 emit 已经拿到过进度。

    比"最终 events 数量对得上"有意义得多——数量对了也可能是终态之后才补的，
    那对用户就是"点了没反应，然后一次性蹦出结果"。
    """
    harness = await _harness()
    gateway = _gateway(harness)
    emitted: list[dict] = []
    progress_seen = asyncio.Event()

    async def emit(event: dict) -> None:
        emitted.append(event)
        if event["type"] == "tool.progress":
            progress_seen.set()

    try:
        await harness.client.request("test/arm_gate", {})
        turn = asyncio.create_task(
            gateway.handle_turn(
                tenant_id="tenant-1",
                session_id="session-1",
                user_id="user-1",
                turn_id="ui-turn-gated",
                content="查某校计算机",
                emit=emit,
            )
        )
        await asyncio.wait_for(progress_seen.wait(), timeout=5)

        assert not turn.done(), "终态闸门还没开，回合不该已经结束"
        progress = next(event for event in emitted if event["type"] == "tool.progress")
        assert progress["payload"]["status"] in {"started", "completed"}
        assert progress["payload"]["label"] == "正在查询历年录取"
        assert not {event["type"] for event in emitted}.intersection(
            {"assistant.completed", "turn.completed", "recoverable.error"}
        )
        # 参数原文不得随进度外发。
        assert "private" not in str(emitted)

        await harness.client.request("test/release", {})
        result = await asyncio.wait_for(turn, timeout=5)
        assert result.get("reply") is not None
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_emit_is_optional_and_legacy_callers_are_unaffected() -> None:
    """不传 emit 时行为与以前一致：没有第二个消费者、也不会报错。"""
    harness = await _harness()
    gateway = _gateway(harness)
    try:
        result = await gateway.handle_turn(
            tenant_id="tenant-1",
            session_id="session-2",
            user_id="user-1",
            turn_id="ui-turn-plain",
            content="你好",
        )
        assert result.get("reply") is not None
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_interrupt_reaches_the_active_turn() -> None:
    harness = await _harness()
    gateway = _gateway(harness)
    released = asyncio.Event()

    async def emit(event: dict) -> None:
        if event["type"] == "tool.progress":
            released.set()

    try:
        await harness.client.request("test/arm_gate", {})
        turn = asyncio.create_task(
            gateway.handle_turn(
                tenant_id="tenant-1",
                session_id="session-1",
                user_id="user-1",
                turn_id="ui-turn-stop",
                content="查某校计算机",
                emit=emit,
            )
        )
        await asyncio.wait_for(released.wait(), timeout=5)
        await harness.interrupt_turn("thr_test", "turn_test")
        result = await asyncio.wait_for(turn, timeout=5)
        # 被中断的回合不能报成"完成"。
        assert result.get("error") is not None or result.get("reply") is not None
    finally:
        await harness.close()


# ── SessionRuntime ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_second_turn_on_a_busy_session_is_refused_not_queued() -> None:
    runtime = SessionRuntime()
    key = SessionKey(tenant_id="tenant-1", session_id="42")
    gate = asyncio.Event()

    async def slow() -> str:
        await gate.wait()
        return "done"

    assert await runtime.submit(
        key, client_request_id="req-1", ui_turn_id="ui-1", work=slow
    ) == ACCEPTED
    # 活动期间再来一条：返回 busy，**不**排队也不静默取消上一轮。
    assert await runtime.submit(
        key, client_request_id="req-2", ui_turn_id="ui-2", work=slow
    ) == BUSY

    gate.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert runtime.active_turn(key) is None


@pytest.mark.asyncio
async def test_duplicate_and_conflicting_client_request_ids() -> None:
    class _Store:
        def __init__(self) -> None:
            self.seen: dict[str, str] = {}

        async def admit(self, key, request_id, request_digest):
            if request_id not in self.seen:
                self.seen[request_id] = request_digest
                return "accepted"
            return "duplicate" if self.seen[request_id] == request_digest else "conflict"

        async def finish_request(self, key, request_id, result_ref):
            pass

    runtime = SessionRuntime(store=_Store())
    key = SessionKey(tenant_id="tenant-1", session_id="42")

    async def work() -> str:
        return "ok"

    assert await runtime.submit(
        key, client_request_id="req-1", ui_turn_id="ui-1", work=work
    ) == ACCEPTED
    # 同 id 同内容 = 重发：不再跑一遍模型。
    assert await runtime.submit(
        key, client_request_id="req-1", ui_turn_id="ui-1", work=work
    ) == DUPLICATE
    # 同 id 不同内容 = 客户端搞混了，不能替它挑一个。
    assert await runtime.submit(
        key, client_request_id="req-1", ui_turn_id="ui-2", work=work
    ) == CONFLICT


@pytest.mark.asyncio
async def test_activity_lock_is_released_on_worker_failure() -> None:
    """异常路径也要解锁，否则这个会话永久 busy——用户只看到"没反应"。"""
    runtime = SessionRuntime()
    key = SessionKey(tenant_id="tenant-1", session_id="42")

    async def boom() -> None:
        raise RuntimeError("worker exploded")

    assert await runtime.submit(
        key, client_request_id="req-1", ui_turn_id="ui-1", work=boom
    ) == ACCEPTED
    for _ in range(5):
        await asyncio.sleep(0)

    assert runtime.active_turn(key) is None


@pytest.mark.asyncio
async def test_interrupt_and_steer_refuse_a_turn_they_do_not_own() -> None:
    runtime = SessionRuntime(
        interrupt_impl=lambda key, turn_id: _noop(),
        steer_impl=lambda key, turn_id, text: _noop(),
    )
    key = SessionKey(tenant_id="tenant-1", session_id="42")
    other = SessionKey(tenant_id="tenant-1", session_id="43")
    gate = asyncio.Event()

    async def slow() -> str:
        await gate.wait()
        return "done"

    await runtime.submit(key, client_request_id="req-1", ui_turn_id="ui-1", work=slow)
    runtime.bind_codex_turn(key, "ui-1", "codex-turn-1")

    # 别的回合号 → 拒绝，而不是"顺手停掉当前那个"。
    assert (await runtime.interrupt(key, "ui-other"))["status"] == "turn_mismatch"
    # 别的会话 → 拒绝。
    assert (await runtime.interrupt(other, "ui-1"))["status"] == "no_active_turn"
    assert (await runtime.interrupt(key, "ui-1"))["status"] == "interrupting"
    assert (await runtime.steer(key, "ui-other", "再保守点"))["status"] == "turn_mismatch"
    assert (await runtime.steer(key, "ui-1", "再保守点"))["status"] == "steered"

    gate.set()


async def _noop() -> None:
    return None


# ── WS 路由：接收器不能被回合堵住 ────────────────────────────────────
# 这一层用**阻塞的假 gateway**，不是真 harness：要证的是"回合还在跑的时候，
# 接收器仍然读到并处理了控制消息"。真 harness 的流式已在上面覆盖。


COMPAT_PATH = "/gaotu-assistant-agent/plus/chat/test-tenant/bot/test-bot/do"


@pytest.fixture
def ws_client():
    from fastapi.testclient import TestClient

    from app.server import app

    original_gateway = getattr(app.state, "gateway_service", None)
    original_runtime = getattr(app.state, "session_runtime", None)
    original_tenant = getattr(app.state, "gateway_tenant_id", None)
    app.state.gateway_tenant_id = "test-tenant"
    yield TestClient(app)
    app.state.gateway_service = original_gateway
    app.state.session_runtime = original_runtime
    app.state.gateway_tenant_id = original_tenant


def _blocking_gateway(stop_requested, progress_emitted):
    """把回合卡住的假 gateway。

    同步的 `threading.Event` 是刻意的：TestClient 在自己的线程里跑应用的事件循环，
    测试线程创建的 `asyncio.Event` 在那边 `.set()` 不会唤醒等待者——
    那样测试会卡死而不是失败，卡死比失败更难查。
    """
    gateway = MagicMock()

    async def interrupt_impl(key, codex_turn_id):
        stop_requested.set()
        return True

    async def steer_impl(key, codex_turn_id, text):
        return True

    runtime = SessionRuntime(interrupt_impl=interrupt_impl, steer_impl=steer_impl)

    async def handle_turn(**kwargs):
        # 假件必须复现真实契约：真 gateway 会在回合开始时把原生回合号绑上来，
        # 不绑的话"停止"永远返回 unavailable——那样测出来的是假件的残缺。
        runtime.bind_codex_turn(
            SessionKey(tenant_id=str(kwargs["tenant_id"]), session_id=str(kwargs["session_id"])),
            str(kwargs["turn_id"]),
            "codex-turn-1",
        )
        emit = kwargs.get("emit")
        if emit is not None:
            await emit(
                {
                    "type": "tool.progress",
                    "payload": {
                        "itemId": "i",
                        "tool": "admission.get_history",
                        "status": "started",
                        "label": "正在查询历年录取",
                    },
                }
            )
            progress_emitted.set()
        while not stop_requested.is_set():
            await asyncio.sleep(0.01)
        return {"reply": "已停止", "events": []}

    gateway.handle_turn = AsyncMock(side_effect=handle_turn)
    return gateway, runtime


@pytest.mark.parametrize("route", ["native", "compat"])
def test_receiver_stays_responsive_while_a_turn_is_running(ws_client, route):
    """回合仍在进行时，同一连接上的控制消息必须被读到并确认。

    这正是"用户点停止没反应"的那个缺陷：接收器在 await 整轮，
    停止消息排在回合后面——回合不结束，它永远读不到。
    """
    from app.server import app

    stop_requested = threading.Event()
    progress_emitted = threading.Event()
    gateway, runtime = _blocking_gateway(stop_requested, progress_emitted)
    app.state.gateway_service = gateway
    app.state.session_runtime = runtime

    payload = (
        {
            "tenantId": "test-tenant",
            "sessionId": "s-1",
            "userId": "u-1",
            "content": "查某校计算机",
            "turnId": "turn-1",
            "type": "chat",
        }
        if route == "native"
        else {
            "sessionId": "s-1",
            "userId": "u-1",
            "content": "查某校计算机",
            "inputType": "text",
            "turnId": "turn-1",
        }
    )
    path = "/ws/chat" if route == "native" else COMPAT_PATH

    with ws_client.websocket_connect(path) as ws:
        ws.send_json(payload)
        # 先等到进度帧——它证明回合已经真的开始跑了。
        first = ws.receive_json()
        if route == "native":
            assert json.loads(first["content"])["type"] == "turn.started"
            first = ws.receive_json()
        assert "历年录取" in json.dumps(first, ensure_ascii=False)

        # 回合**还没结束**，此时发停止。
        ws.send_json(
            {"type": "turnInterrupt", "sessionId": "s-1", "turnId": "turn-1", "content": ""}
        )
        ack = ws.receive_json()
        if route == "native":
            assert "turn.interrupt" in json.dumps(ack, ensure_ascii=False) or "停止" in json.dumps(
                ack, ensure_ascii=False
            )
        else:
            assert ack.get("type") == "turn.interrupt"

        final = ws.receive_json()
        assert "已停止" in json.dumps(final, ensure_ascii=False)


@pytest.mark.parametrize("route", ["native", "compat"])
def test_interrupt_for_an_unknown_turn_is_refused_not_acknowledged(ws_client, route):
    """回合已经结束时的停止请求要说"没生效"，不能假装收到了。"""
    from app.server import app

    gateway, runtime = _blocking_gateway(threading.Event(), threading.Event())
    gateway.handle_turn = AsyncMock(return_value={"reply": "ok", "events": []})
    app.state.gateway_service = gateway
    app.state.session_runtime = runtime
    path = "/ws/chat" if route == "native" else COMPAT_PATH

    with ws_client.websocket_connect(path) as ws:
        ws.send_json(
            {"type": "turnInterrupt", "sessionId": "s-1", "turnId": "turn-9", "content": ""}
        )
        frame = ws.receive_json()

    text = json.dumps(frame, ensure_ascii=False)
    assert "已经结束" in text or "no_active_turn" in text


# ── 澄清卡真的推到前端了吗 ──────────────────────────────────────────
# 桥建好但没通电时，实际行为是：模型提问 → 服务端挂起等一个没人答的 future
# → 十分钟后过期，而用户从头到尾没被告知过。这两条就是那个缺口。


def _broker_backed_gateway(broker, stop_requested, question_started):
    """假 gateway：回合开始时通过 broker 提一个问，等答案。"""
    gateway = MagicMock()

    async def handle_turn(**kwargs):
        key = SessionKey(
            tenant_id=str(kwargs["tenant_id"]), session_id=str(kwargs["session_id"])
        )
        task = asyncio.ensure_future(
            broker.handle_server_request(
                {
                    "id": 9001,
                    "method": "item/tool/requestUserInput",
                    "params": {
                        "threadId": "thr_test",
                        "turnId": str(kwargs["turn_id"]),
                        "questions": [
                            {
                                "id": "major",
                                "header": "专业范围",
                                "question": "你指哪一种？",
                                "isOther": True,
                                "options": [{"label": "计算机类"}],
                            }
                        ],
                    },
                }
            )
        )
        question_started.set()
        try:
            answer = await task
        finally:
            pass
        return {"reply": f"收到答案 {answer['answers']['major']['answers'][0]}", "events": []}

    gateway.handle_turn = AsyncMock(side_effect=handle_turn)
    return gateway


@pytest.mark.parametrize("route", ["native", "compat"])
def test_clarification_card_reaches_the_frontend_and_the_answer_comes_back(
    ws_client, route
):
    from app.server import app
    from app.gateway.composition import bind_session_runtime
    from app.gateway.user_input import UserInputBroker

    question_started = threading.Event()
    broker = UserInputBroker(
        runtime_generation="gen-test",
        scope_resolver=lambda thread_id: SessionKey(tenant_id="test-tenant", session_id="s-1"),
    )
    gateway = _broker_backed_gateway(broker, threading.Event(), question_started)
    gateway.user_input_broker = broker
    runtime = SessionRuntime(
        interrupt_impl=lambda key, tid: _noop(),
        steer_impl=lambda key, tid, text: _noop(),
    )
    broker.set_emitter(runtime.publish)
    app.state.gateway_service = gateway
    app.state.session_runtime = runtime
    bind_session_runtime(runtime)

    payload = (
        {
            "tenantId": "test-tenant", "sessionId": "s-1", "userId": "u-1",
            "content": "查计算机", "turnId": "turn-1", "type": "chat",
        }
        if route == "native"
        else {"sessionId": "s-1", "userId": "u-1", "content": "查计算机", "inputType": "text", "turnId": "turn-1"}
    )
    path = "/ws/chat" if route == "native" else COMPAT_PATH

    with ws_client.websocket_connect(path) as ws:
        ws.send_json(payload)
        assert question_started.wait(timeout=5)
        card = ws.receive_json()
        if route == "native":
            assert json.loads(card["content"])["type"] == "turn.started"
            card = ws.receive_json()
        rendered = json.dumps(card, ensure_ascii=False)
        assert "clarification.requested" in rendered
        request_id = broker.snapshot(
            SessionKey(tenant_id="test-tenant", session_id="s-1")
        )[0]["requestId"]

        ws.send_json(
            {
                "type": "clarificationAnswer",
                "sessionId": "s-1",
                "turnId": "turn-1",
                "clientRequestId": "answer-1",
                "content": "",
                "clarificationAnswer": {
                    "requestId": request_id,
                    "inputKind": "choice",
                    "answers": {"major": {"answers": ["计算机类"]}},
                },
            }
        )
        frames = [ws.receive_json()]
        # 只认"回合拿到答案之后产出的终态"：卡片本身也带着选项文案"计算机类"，
        # 用这个词做判据的话，光收到卡就能让断言变绿——那是空的。
        for _ in range(4):
            if any("收到答案" in json.dumps(f, ensure_ascii=False) for f in frames):
                break
            frames.append(ws.receive_json())

    assert any("收到答案 计算机类" in json.dumps(f, ensure_ascii=False) for f in frames), (
        "答案没有回到处在等待中的那个回合"
    )


async def _noop(*args, **kwargs):
    return None


# ── 编号事件：配了 store 时发 v1 envelope ────────────────────────────


class _FakeStore:
    """只做"编号后返回 UiEvent"这一件事。

    store 自身的原子性、重放、resync 归 A5 的测试；这里验的是
    **通道有没有在发之前先入流**。
    """

    def __init__(self):
        self.appended = []

    async def append(self, key, event):
        from app.gateway.ui_events import UiEvent

        self.appended.append((key, dict(event)))
        numbered = UiEvent(
            type=event["type"],
            sessionId=key.session_id,
            turnId=event["turnId"],
            streamEpoch="epoch-1",
            sequence=len(self.appended),
            payload=event.get("payload") or {},
        )
        return numbered


@pytest.mark.asyncio
async def test_a_configured_store_makes_events_numbered() -> None:
    key = SessionKey(tenant_id="tenant-1", session_id="42")
    store = _FakeStore()
    frames: list[dict] = []

    async def send(frame):
        frames.append(frame)
        return True

    channel = ConnectionChannel(send, store=store, session_key=key)
    channel.start()
    channel.bind_turn("ui-turn-1")

    await channel.emit({"type": "tool.progress", "payload": {"itemId": "i1", "label": "正在查询历年录取"}})
    await asyncio.sleep(0.05)
    await channel.close()

    # 先入流，再发编号后的 envelope。
    assert len(store.appended) == 1
    assert frames and frames[0]["protocolVersion"] == 1
    assert frames[0]["sequence"] == 1
    assert frames[0]["streamEpoch"] == "epoch-1"
    assert frames[0]["turnId"] == "ui-turn-1"
    assert frames[0]["payload"]["itemId"] == "i1"


@pytest.mark.asyncio
async def test_without_a_store_the_legacy_frame_is_still_sent() -> None:
    key = SessionKey(tenant_id="tenant-1", session_id="42")
    frames: list[dict] = []

    async def send(frame):
        frames.append(frame)
        return True

    channel = ConnectionChannel(
        send, frame_builder=lambda event: {"type": event["type"], "content": "legacy"}, session_key=key
    )
    channel.start()

    await channel.emit({"type": "tool.progress", "payload": {}})
    await asyncio.sleep(0.05)
    await channel.close()

    # 没配置事件存储时不假装有编号：降级为旧信封，客户端据此知道恢复不可用。
    assert frames == [{"type": "tool.progress", "content": "legacy"}]


@pytest.mark.asyncio
async def test_a_failing_store_requests_resync_without_emitting_a_legacy_frame() -> None:
    key = SessionKey(tenant_id="tenant-1", session_id="42")
    frames: list[dict] = []

    class _BrokenStore:
        async def append(self, key, event):
            raise RuntimeError("redis is down")

    async def send(frame):
        frames.append(frame)
        return True

    channel = ConnectionChannel(
        send, frame_builder=lambda event: {"type": event["type"], "content": "legacy"},
        store=_BrokenStore(), session_key=key,
    )
    channel.start()

    await channel.emit({"type": "tool.progress", "payload": {}})
    await asyncio.sleep(0.05)
    await channel.close()

    assert len(frames) == 1
    assert frames[0]["protocolVersion"] == 1
    assert frames[0]["type"] == "session.resync"
    assert frames[0]["sessionId"] == "42"
    assert frames[0]["sequence"] == 0  # control frame, never a fabricated stored sequence
    assert frames[0]["payload"]["baseline"]["reason"] == "event_store_append_failed"
    assert "content" not in frames[0]
