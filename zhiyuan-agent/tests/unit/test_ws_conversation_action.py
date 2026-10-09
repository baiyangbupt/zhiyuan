import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import WebSocketDisconnect

from app.gateway.access import TicketIdentity
from app.gateway.session_runtime import SessionRuntime
from app.gateway.ui_events import SessionKey, UiEvent
from app.schemas import WSMessage
from app.server import _handle_gateway_ws_loop

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
            session_id="test-session",
            user_id="test-user",
            bot_id=self._bot_id,
            origin=origin or "http://127.0.0.1:3201",
        )





def test_ws_message_accepts_structured_conversation_action_alias():
    message = WSMessage.model_validate(
        {
            "type": "pendingConfirmation",
                "sessionId": "s1",
            "content": "",
            "conversationAction": {
                "actionType": "confirm_proposal",
                "proposalRef": "pending-1",
                "expectedSourceVersion": 7,
            },
        }
    )

    assert message.conversation_action == {
        "actionType": "confirm_proposal",
        "proposalRef": "pending-1",
        "expectedSourceVersion": 7,
    }


def test_ws_message_remains_backward_compatible_without_action():
    message = WSMessage.model_validate({"sessionId": "s1", "content": "继续查询"})
    assert message.conversation_action is None


def test_ws_message_accepts_tenant_id_alias():
    message = WSMessage.model_validate(
        {"tenantId": "tenant-7", "sessionId": "s1", "content": "继续查询"}
    )

    assert message.tenant_id == "tenant-7"


@pytest.mark.parametrize("user_key", ["userId", "user_id"])
def test_ws_message_preserves_user_identity(user_key):
    message = WSMessage.model_validate({"sessionId": "s1", user_key: "u1", "content": "继续"})
    assert message.user_id == "u1"


@pytest.fixture(autouse=True)
def _permissive_access_guard():
    """生产路径无条件校验 WS 票据；测试装一个放行替身。"""
    from app.server import app as _app

    _app.state.conversation_access_guard = _PermissiveAccessGuard()
    yield
    _app.state.conversation_access_guard = None


@pytest.mark.asyncio
async def test_gateway_websocket_rejects_missing_tenant_before_calling_gateway():
    class Socket:
        def __init__(self):
            self.app = SimpleNamespace(state=SimpleNamespace(gateway_tenant_id=""))
            self.sent: list[dict] = []
            self.received = False

        async def receive_json(self):
            if self.received:
                raise WebSocketDisconnect()
            self.received = True
            return {"type": "chat", "sessionId": "s1", "userId": "u1", "content": "继续"}

        async def send_text(self, value: str):
            self.sent.append(json.loads(value))

    class Gateway:
        async def handle_turn(self, **kwargs):
            raise AssertionError("must not call gateway without tenant")

    socket = Socket()
    # 客户端断开现在被循环吞掉并正常返回（与 compat 路由一致），而不是往上抛。
    # 这条测试真正要验的是"缺 tenant 时不调用 gateway、且回了错误帧"，
    # 之前的 pytest.raises 只是用来终止循环，不是被测契约的一部分。
    await _handle_gateway_ws_loop(socket, Gateway())

    assert socket.sent[0]["type"] == "recoverable.error"
    assert "缺少 tenantId" in socket.sent[0]["content"]


@pytest.mark.asyncio
async def test_a_heartbeat_ping_is_answered_in_place_and_never_becomes_a_turn():
    """心跳必须**当场回 pong** ✓✓——native 路由原本没有这个分支 ✗，于是每 5s 一条的心跳
    被当成**一轮对话**跑 ✓：占一个回合 ✓、真调一次模型 ✓、失败了再发 `recoverable.error` ✓。
    后果不止是浪费 ✓✗：客户端收到一批"凭空出现的新回合" ✓ → 判成缺口 ✓ → 重同步
    **把在飞回合的界面丢掉** ✗（实测：一轮用例里回合块每 5s 被清一次 ✓，
    表现成"发消息后回合块不出现" ✓，两条用例因此红 ✓）。
    """

    class Socket:
        def __init__(self):
            self.app = SimpleNamespace(state=SimpleNamespace(gateway_tenant_id="1"))
            self.sent: list[dict] = []
            self.received = False

        async def receive_json(self):
            if self.received:
                raise WebSocketDisconnect()
            self.received = True
            return {
                "type": "chat", "sessionId": "s1", "userId": "u1",
                "content": "", "inputType": "ping", "timestamp": 123,
            }

        async def send_text(self, value: str):
            self.sent.append(json.loads(value))

    class Gateway:
        async def handle_turn(self, **kwargs):
            raise AssertionError("心跳**不许**变成一轮对话 ✗")

    socket = Socket()
    await _handle_gateway_ws_loop(socket, Gateway())

    assert [frame["type"] for frame in socket.sent] == ["pong"]
    assert socket.sent[0]["timestamp"] == 123  # 原样回带 ✓（前端拿它对时延 ✓）


# ─────────────────────────────────────────────────────────────────────────────
# 确认/取消那一段（detach_work ✓）的**投递**：终态必须到得了页面 ✓✓
#
# 真缺陷（2026-10-06 线上复现 ✓）：动作执行要十几秒 ✓，这中间页面重连一次（刷新 /
# 心跳判死 / 掉线 ✓）是常态 ✓——而重连**没有游标**（页面状态被清掉 ✓），服务端
# `_replay_active_turn` 见"没有在跑的回合"（动作**不挂回合** ✓）就直接返回 ✗：
# 新连接既没绑会话、也没登记成"会话当前连接" ✗ → 结果事件推给那条**已经死了**的旧连接 ✗
# → 库里已经落地的改动，页面上永远停在"待确认" ✗（用户反复点同一个确认 ✓）。
# 下面两条盯的就是"事件流里有没有" **和** "新连接收不收得到" ✓。
# ─────────────────────────────────────────────────────────────────────────────


class _MemoryEventStore:
    """内存版事件存储 ✓：只实现网关真会用到的那几个方法 ✓（接口照 `RedisEventStore` ✓）。"""

    def __init__(self) -> None:
        self.epoch = "epoch-test"
        self.sequences: dict[SessionKey, int] = {}
        self.events: list[UiEvent] = []

    async def append(self, key: SessionKey, event: dict) -> UiEvent:
        sequence = self.sequences.get(key, 0) + 1
        self.sequences[key] = sequence
        numbered = UiEvent(
            type=str(event.get("type")),
            sessionId=str(event.get("sessionId") or key.session_id),
            turnId=str(event.get("turnId") or ""),
            streamEpoch=self.epoch,
            sequence=sequence,
            payload=dict(event.get("payload") or {}),
        )
        self.events.append(numbered)
        return numbered

    async def current_epoch(self, key: SessionKey) -> str | None:
        return self.epoch if self.sequences.get(key) else None

    async def replay(self, key: SessionKey, epoch: str, after: int):
        if epoch != self.epoch:
            return None
        return [
            event
            for event in self.events
            if event.session_id == key.session_id and event.sequence > after
        ]

    async def watermark(self, key: SessionKey) -> int:
        return self.sequences.get(key, 0)

    def types(self) -> list[str]:
        return [event.type for event in self.events]

    def of_type(self, event_type: str) -> list[UiEvent]:
        return [event for event in self.events if event.type == event_type]


class _Socket:
    """可推送消息的假连接 ✓：`None` = 客户端断开（抛 `WebSocketDisconnect` ✓）。"""

    def __init__(self, store: _MemoryEventStore, runtime: SessionRuntime, session_id: str) -> None:
        self.sent: list[dict] = []
        self.app = SimpleNamespace(
            state=SimpleNamespace(
                event_store=store,
                session_runtime=runtime,
                gateway_tenant_id="1",
                gateway_service=SimpleNamespace(user_input_broker=None),
            )
        )
        self.state = SimpleNamespace(
            identity=TicketIdentity(
                tenant_id="1", session_id=session_id, user_id="u1", bot_id="b1"
            )
        )
        # 页面刷新后的重连：**没有** epoch/since ✓（这正是缺的那一格 ✓）。
        self.query_params = {"chatSessionId": session_id}
        self._inbox: asyncio.Queue = asyncio.Queue()
        self.closed = False

    def push(self, message) -> None:
        self._inbox.put_nowait(message)

    async def receive_json(self):
        message = await self._inbox.get()
        if message is None:
            raise WebSocketDisconnect()
        return message

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))

    def frames(self, frame_type: str) -> list[dict]:
        return [frame for frame in self.sent if frame.get("type") == frame_type]


class _ActionGateway:
    """确认那一段的网关替身：执行**卡在闸门上** ✓，让"执行中重连"可复现、不靠时序赌博 ✓。"""

    def __init__(self, proposal_ref: str = "pending-1") -> None:
        self.proposal_ref = proposal_ref
        self.action_started = asyncio.Event()
        self.action_release = asyncio.Event()
        self.executed: list[dict] = []

    async def get_authoritative_snapshot(self, **kwargs):
        return {"snapshotVersion": 0}

    async def execute_action_and_refresh(self, *, action, **kwargs):
        self.executed.append(dict(action))
        self.action_started.set()
        await self.action_release.wait()
        return {
            "actionResult": {
                "actionStatus": "applied",
                "proposalRef": self.proposal_ref,
                "code": "0",
                "message": "success",
            },
            "snapshotVersion": 1,
        }

    async def handle_turn(self, **kwargs):
        return {
            "reply": "我把这个要求整理成了提案，确认后生效。",
            "events": [],
            "proposalPreview": {
                "proposalRef": self.proposal_ref,
                "sourceVersion": 0,
                "status": "pending",
                "requiresConfirmation": True,
            },
        }


def _chat(session_id: str, turn_id: str = "turn-chat") -> dict:
    return {
        "type": "chat",
        "tenantId": "1",
        "sessionId": session_id,
        "userId": "u1",
        "turnId": turn_id,
        "content": "更新一下成绩：总分 610，位次 22000",
    }


def _confirm(session_id: str, proposal_ref: str, turn_id: str = "turn-confirm") -> dict:
    """与前端 `buildPendingConfirmationFrame` 同形 ✓（`conversationProtocol.mjs` ✓）。"""
    return {
        "type": "pendingConfirmation",
        "tenantId": "1",
        "sessionId": session_id,
        "userId": "u1",
        "turnId": turn_id,
        "content": "",
        "inputType": "pendingConfirmation",
        "conversationAction": {
            "actionType": "confirm_proposal",
            "proposalRef": proposal_ref,
            "expectedSourceVersion": 0,
            "intent": "explicit",
        },
        "clientRequestId": f"proposal-{proposal_ref}",
    }


async def _wait_for(predicate, *, timeout: float = 3.0, what: str) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"timeout waiting for {what}")


@pytest.mark.asyncio
async def test_a_reconnect_without_a_cursor_still_gets_the_action_result() -> None:
    """**页面在执行中重连**（无游标 ✓）→ 新连接必须收到 `conversationAction.result` ✓✓。

    修前：结果事件进了事件流 ✓、却推给那条已经断掉的旧连接 ✗——用户看到的就是
    "点了确认没反应" ✓（实测复现：`ws2 received result frames: 0` ✓）。
    修后：新连接在 `_replay_active_turn` 里被登记成"会话当前连接" ✓，`publish` 就能落到它身上 ✓。
    """
    session_id = "900047"
    store = _MemoryEventStore()
    runtime = SessionRuntime()
    gateway = _ActionGateway()
    ws1 = _Socket(store, runtime, session_id)
    ws1.push(_chat(session_id))

    task1 = asyncio.create_task(_handle_gateway_ws_loop(ws1, gateway))
    await _wait_for(
        lambda: "proposal.preview" in store.types(), what="卡片出事件流"
    )

    # 用户点确认：执行进闸门（十几秒那种）。
    ws1.push(_confirm(session_id, gateway.proposal_ref))
    await _wait_for(gateway.action_started.is_set, what="动作开始执行")

    # 页面刷新/重连：老连接断开、新连接（**无游标**）接上。
    ws1.push(None)
    ws2 = _Socket(store, runtime, session_id)
    task2 = asyncio.create_task(_handle_gateway_ws_loop(ws2, gateway))
    await asyncio.sleep(0.05)  # 让新连接的登记先落地
    assert runtime.current_channel(SessionKey(tenant_id="1", session_id=session_id)) is not None

    gateway.action_release.set()
    await _wait_for(
        lambda: ws2.frames("conversationAction.result"), what="新连接收到动作结果"
    )
    await asyncio.sleep(0.05)
    for task in (task1, task2):
        task.cancel()
    await asyncio.gather(task1, task2, return_exceptions=True)

    # ① 事件流里必须有（可丢帧、不可丢流 ✓）。
    results = store.of_type("conversationAction.result")
    assert len(results) == 1
    assert results[0].payload["actionStatus"] == "applied"
    # ② 新连接必须收得到（用户看到的"已生效"就是从这条帧来的 ✓）。
    frame = ws2.frames("conversationAction.result")[0]
    assert frame["payload"]["actionStatus"] == "applied"
    assert frame["payload"]["proposalRef"] == gateway.proposal_ref
    # ③ 回合号：结果属于**确认**那一轮 ✓，不是它后面任何一轮 ✓。
    assert results[0].turn_id == "turn-confirm"
    assert frame["turnId"] == "turn-confirm"


@pytest.mark.asyncio
async def test_the_action_result_keeps_its_own_turn_when_another_message_rebinds_the_channel() -> None:
    """确认在飞时用户又发了一条 → 结果仍记在**确认那一轮**名下 ✓✓。

    真缺陷（2026-10-06 线上会话 10041953 的流 ✓）：`bind_turn` 会在**每条消息**到达时改写 ✓，
    而结果事件是执行完才发的（十几秒后 ✓）——按"通道绑定"盖章就变成了用户**后一条**消息的回合 ✗
    （seq 93 被盖成 96943a43 ✓）。前端虽然按 `proposalRef` 找得到结果 ✓（卡不至于不翻 ✓），
    但那条回合会被标成"已终态" ✗ → 它自己的增量被 reducer 丢掉 ✓✗。
    """
    session_id = "900048"
    store = _MemoryEventStore()
    runtime = SessionRuntime()
    gateway = _ActionGateway(proposal_ref="pending-2")
    ws = _Socket(store, runtime, session_id)
    ws.push(_chat(session_id, turn_id="turn-chat"))
    task = asyncio.create_task(_handle_gateway_ws_loop(ws, gateway))
    await _wait_for(lambda: "proposal.preview" in store.types(), what="卡片出事件流")

    ws.push(_confirm(session_id, gateway.proposal_ref))
    await _wait_for(gateway.action_started.is_set, what="动作开始执行")

    # 动作还没回来，同一条连接上又来了用户的一条普通消息。
    ws.push(_chat(session_id, turn_id="turn-later"))
    await _wait_for(
        lambda: [event for event in store.events if event.turn_id == "turn-later"],
        what="后一条消息的事件入流",
    )

    gateway.action_release.set()
    await _wait_for(
        lambda: store.of_type("conversationAction.result"), what="动作结果入流"
    )
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    results = store.of_type("conversationAction.result")
    assert len(results) == 1
    assert results[0].turn_id == "turn-confirm"
    # 后一条消息自己那一轮照旧 ✓（没被结果的回合号污染 ✓）。
    assert {event.turn_id for event in store.events if event.type == "turn.started"} == {
        "turn-chat",
        "turn-confirm",
        "turn-later",
    }


# ─────────────────────────────────────────────────────────────────────────────
# 打字"确认"（模型在**文本回合**里发 `confirm_proposal`）：走真实网关回合，
# 事件流里必须出现 `conversationAction.result` ✓✓（2026-10-08 修）。
#
# 修前：校验器放行动作 → `_codex_turn` 里**没有执行分支** → 无 Java 调用、无结果、
# 无报错，模型嘴上"已提交"（会话 10041979 的谎报）。这条用例从 WS 入帧一路盯到
# 事件存储：同一份结果事件的形状与点卡路径完全一致（同一个 `_emit_turn_terminal`）。
# ─────────────────────────────────────────────────────────────────────────────


class _TurnActionCodex:
    """输出一个带 `conversationAction` 的文本回合（打字"确认"时模型的真实形状 ✓）。

    **只第一轮带动作** ✓（2026-10-09 起，确认生效后还有一轮**续接回合** ✓，见
    `server.py::_maybe_continue_after_action` ✓）：续接的输入已经明说"不要再确认
    同一张" ✓，模型照做的形状就是一条普通文本回执 ✓——替身按真实形状分轮返回 ✓，
    本用例盯的"执行恰好一次、Java 恰好被调 3 次"才不会被替身的惰性污染 ✓。
    """

    def __init__(self) -> None:
        self.turns: list[list] = []

    async def create_thread(self, **kwargs):
        return {"thread": {"id": "thr-ws-action"}}

    async def resume_thread(self, thread_id):
        return {"thread": {"id": thread_id}}

    async def inject_items(self, thread_id, items):
        return {}

    async def start_turn_and_collect(self, thread_id, input_items, output_schema=None, **kwargs):
        from dataclasses import dataclass, field

        self.turns.append(input_items)

        @dataclass
        class Collected:
            status: str
            output: dict
            events: list
            turn_id: str = "turn-1"
            payload: dict = field(default_factory=dict)

        output = {
            "responseType": "text",
            "message": "好的，我这就去确认。",
            "conversationAction": {
                "actionType": "confirm_proposal",
                "proposalRef": "pending-1",
                "expectedSourceVersion": 5,
                "intent": "explicit",
            },
        }
        if len(self.turns) > 1:
            output = {"responseType": "text", "message": "已生效，我接着往下做。"}
        return Collected(status="completed", output=output, events=[])


class _ActionSnapshotLoader:
    def __init__(self):
        self.calls = 0

    def __call__(self, **kwargs):
        self.calls += 1
        return {
            "sessionId": "900049",
            "version": 5 + (1 if self.calls > 1 else 0),
            "allowedCapabilities": ["catalog_read", "admission_read"],
            "activeProposal": {
                "proposalRef": "pending-1",
                "pendingId": "pending-1",
                "sourceVersion": 5,
                "revision": 1,
                "data": {
                    "operationId": "op-1",
                    "proposalApply": {
                        "proposalId": "P1",
                        "proposalSource": "system",
                        "sourceVersionGuard": 5,
                        "regenerateOrderedPlan": True,
                        "rerunReview": True,
                    },
                },
            },
        }


class _StoreForGateway:
    async def save_user_message(self, chat_session_id: str, content: str) -> int:
        return 1

    async def save_agent_message(self, chat_session_id: str, content: str, ws_type: str = "reply") -> int:
        return 2


@pytest.mark.asyncio
async def test_a_model_confirm_puts_a_result_event_on_the_stream(monkeypatch) -> None:
    """打字"确认"→ 真实网关回合执行 → 事件流与连接上都出现 `conversationAction.result` ✓✓。"""
    from app.gateway import conversation_actions
    from app.gateway.service import GatewayService
    from app.harness.binding import ThreadBinding

    resolve = _JavaRecorder([
        {"code": 0, "status": "applying", "data": {"revision": 2}},
        {"code": 0, "status": "completed"},
    ])
    execute = _JavaRecorder([
        {"code": 0, "status": "applied", "data": {"stateVersion": 7}},
    ])
    monkeypatch.setattr(conversation_actions, "resolve_pending_confirmation", resolve)
    monkeypatch.setattr(conversation_actions, "execute_pending_planning_command", execute)

    session_id = "900049"
    store = _MemoryEventStore()
    runtime = SessionRuntime()
    gateway = GatewayService(
        mode="codex_write",
        codex=_TurnActionCodex(),
        legacy=None,
        message_store=_StoreForGateway(),
        binding_loader=lambda **kwargs: ThreadBinding(
            thread_id="thr-ws-action",
            tenant_id="1",
            session_id=session_id,
            user_id="u1",
            allowed_capabilities=frozenset({"catalog_read", "admission_read"}),
        ),
        snapshot_loader=_ActionSnapshotLoader(),
    )
    ws = _Socket(store, runtime, session_id)
    ws.push({**_chat(session_id, turn_id="turn-type-confirm"), "content": "确认"})

    task = asyncio.create_task(_handle_gateway_ws_loop(ws, gateway))
    await _wait_for(
        lambda: store.of_type("conversationAction.result"), what="动作结果入流"
    )
    await _wait_for(
        lambda: ws.frames("conversationAction.result"), what="连接收到动作结果"
    )
    # **打字确认同样续接** ✓✓（2026-10-09）：动作终局之后还有一轮 `cont-…` 新回合 ✓，
    # 助手消息落在**新回合**名下 ✓（结果事件仍属于 `turn-type-confirm` ✓，见下面 ✓）。
    await _wait_for(
        lambda: any(
            event.turn_id.startswith("cont-") and event.type == "turn.completed"
            for event in store.events
        ),
        what="续接回合收尾",
    )
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    results = store.of_type("conversationAction.result")
    assert len(results) == 1
    assert results[0].payload["actionStatus"] == "applied"
    assert results[0].turn_id == "turn-type-confirm"
    frame = ws.frames("conversationAction.result")[0]
    assert frame["payload"]["actionStatus"] == "applied"
    assert frame["payload"]["proposalRef"] == "pending-1"
    # Java 侧真的被调到了 ✓（修前这里是 0 次——动作被静默丢弃 ✗；续接那一轮是
    # **模型**回合、不再碰 Java ✓，所以次数不变 ✓）。
    assert len(resolve.calls) == 2 and len(execute.calls) == 1
    continuation = [event for event in store.events if event.turn_id.startswith("cont-")]
    assert [event.type for event in continuation] == [
        "turn.started",
        "assistant.completed",
        "turn.completed",
    ]
    assert continuation[1].payload["message"] == "已生效，我接着往下做。"


class _JavaRecorder:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[tuple[tuple, dict]] = []

    async def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.responses.pop(0) if self.responses else {}


# ─────────────────────────────────────────────────────────────────────────────
# 确认**生效之后**的自动续接（2026-10-09 用户实测：会话 10041981 ✓）
#
# 用户实测现场 ✓：助手上一条承诺了"确认成绩后我先按方向给你几个院校专业组参考…" ✓，
# 用户点卡确认、卡翻"已生效" ✓，然后——只有一句写死的"操作已处理。" ✗，话头断了 ✓。
# 这里盯的就是点卡路径的续接：applied 之后自动起一轮**新回合** ✓，把承诺的下一步接上 ✓。
# ─────────────────────────────────────────────────────────────────────────────


class _ContinuationCodex:
    """点卡路径的替身：确认执行之后只该被叫**一次**——就是续接那一轮 ✓（普通文本 ✓）。"""

    def __init__(self, message: str = "确认好了。我接着按方向给你几个院校专业组参考。") -> None:
        self.message = message
        self.turns: list[list] = []

    async def create_thread(self, **kwargs):
        return {"thread": {"id": "thr-continuation"}}

    async def resume_thread(self, thread_id):
        return {"thread": {"id": thread_id}}

    async def inject_items(self, thread_id, items):
        return {}

    async def start_turn_and_collect(self, thread_id, input_items, output_schema=None, **kwargs):
        from dataclasses import dataclass, field

        self.turns.append(input_items)

        @dataclass
        class Collected:
            status: str
            output: dict
            events: list
            turn_id: str = "turn-1"
            payload: dict = field(default_factory=dict)

        return Collected(
            status="completed",
            output={"responseType": "text", "message": self.message},
            events=[],
        )


class _RecordingStore:
    """记下两个方向的消息（transcript 合同）：续接**不许**在用户那一侧落任何东西 ✓。"""

    def __init__(self) -> None:
        self.user_messages: list[str] = []
        self.agent_messages: list[str] = []

    async def save_user_message(self, chat_session_id: str, content: str) -> int:
        self.user_messages.append(content)
        return 1

    async def save_agent_message(self, chat_session_id: str, content: str, ws_type: str = "reply") -> int:
        self.agent_messages.append(content)
        return 2


@pytest.mark.asyncio
async def test_a_clicked_confirm_continues_the_thread_on_a_fresh_turn(monkeypatch) -> None:
    """点卡确认 applied → 自动续接**一轮新回合**（新 turnId）把话头接上 ✓✓。

    修前：`_run_action_work` 收尾只发 `reply="操作已处理。"` ✗（server.py 写死两处之一 ✓）。
    修后：终局之后 `_maybe_continue_after_action` 起一轮 `cont-…` 回合 ✓：
    `turn.started` → `assistant.completed`（续接文本）→ `turn.completed` ✓，
    而且：不伪造用户消息 ✓、助手消息落库的正是续接文本 ✓、续接恰好一轮 ✓、Java 恰好一趟 ✓。
    """
    from app.gateway import conversation_actions
    from app.gateway.service import GatewayService
    from app.harness.binding import ThreadBinding

    resolve = _JavaRecorder([
        {"code": 0, "status": "applying", "data": {"revision": 2}},
        {"code": 0, "status": "completed"},
    ])
    execute = _JavaRecorder([
        {"code": 0, "status": "applied", "data": {"stateVersion": 7}},
    ])
    monkeypatch.setattr(conversation_actions, "resolve_pending_confirmation", resolve)
    monkeypatch.setattr(conversation_actions, "execute_pending_planning_command", execute)

    session_id = "900049"
    store = _MemoryEventStore()
    runtime = SessionRuntime()
    codex = _ContinuationCodex()
    message_store = _RecordingStore()
    gateway = GatewayService(
        mode="codex_write",
        codex=codex,
        legacy=None,
        message_store=message_store,
        binding_loader=lambda **kwargs: ThreadBinding(
            thread_id="thr-continuation",
            tenant_id="1",
            session_id=session_id,
            user_id="u1",
            allowed_capabilities=frozenset({"catalog_read", "admission_read"}),
        ),
        snapshot_loader=_ActionSnapshotLoader(),
    )
    ws = _Socket(store, runtime, session_id)
    confirm = _confirm(session_id, "pending-1")
    # 点卡帧照前端合同带**当前卡片版本** ✓（`_ActionSnapshotLoader` 里 sourceVersion=5 ✓）：
    # 版本对不上会被 CAS 判 `stale_state` ✓——那是另一条用例的事，这里要的是 applied ✓。
    confirm["conversationAction"]["expectedSourceVersion"] = 5
    ws.push(confirm)

    task = asyncio.create_task(_handle_gateway_ws_loop(ws, gateway))
    await _wait_for(
        lambda: any(
            event.turn_id.startswith("cont-") and event.type == "turn.completed"
            for event in store.events
        ),
        what="续接回合收尾",
    )
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    # ① 动作结果这一格不许回退：applied 照旧进流、记在**确认那一轮**名下 ✓。
    results = store.of_type("conversationAction.result")
    assert len(results) == 1 and results[0].payload["actionStatus"] == "applied"
    assert results[0].turn_id == "turn-confirm"

    # ② 续接是一个**新回合**：started → assistant.completed（续接文本）→ completed ✓。
    continuation = [event for event in store.events if event.turn_id.startswith("cont-")]
    assert [event.type for event in continuation] == [
        "turn.started",
        "assistant.completed",
        "turn.completed",
    ]
    assert continuation[1].payload["message"] == "确认好了。我接着按方向给你几个院校专业组参考。"
    # 三条都要**到得了连接**（用户看到的就是它 ✓）——别只进流不上屏 ✓。
    for frame_type in ("turn.started", "assistant.completed", "turn.completed"):
        assert any(
            str(frame.get("turnId") or "").startswith("cont-")
            for frame in ws.frames(frame_type)
        ), f"{frame_type} 没到连接上"
    # 写死的"操作已处理。"仍属于确认那一轮 ✓（续接是**额外**一轮，不是替换 ✓）。
    assert any(
        frame.get("turnId") == "turn-confirm" for frame in ws.frames("assistant.completed")
    )

    # ③ **不伪造用户消息** ✓：用户那一侧一个字都没有；助手那一侧落的正是续接文本 ✓。
    assert message_store.user_messages == []
    assert message_store.agent_messages == ["确认好了。我接着按方向给你几个院校专业组参考。"]

    # ④ 续接恰好一轮（替身只被叫一次 ✓，喂进去的确实是续接指令 ✓）、Java 恰好一趟 ✓。
    assert len(codex.turns) == 1
    assert "已经生效" in codex.turns[0][-1]["text"]
    assert len(resolve.calls) == 2 and len(execute.calls) == 1


@pytest.mark.asyncio
async def test_a_stale_confirm_neither_executes_nor_continues(monkeypatch) -> None:
    """卡版本对不上（`stale_state`）→ **不续接** ✓✓：维持现状——用户要做的是刷新看卡 ✓，
    不是被拉去下一步 ✗（续接的触发条件只有 `applied` 一档 ✓，见 `continue_after_action` ✓）。
    """
    from app.gateway import conversation_actions
    from app.gateway.service import GatewayService
    from app.harness.binding import ThreadBinding

    resolve = _JavaRecorder([])
    execute = _JavaRecorder([])
    monkeypatch.setattr(conversation_actions, "resolve_pending_confirmation", resolve)
    monkeypatch.setattr(conversation_actions, "execute_pending_planning_command", execute)

    session_id = "900049"
    store = _MemoryEventStore()
    runtime = SessionRuntime()
    codex = _ContinuationCodex()
    message_store = _RecordingStore()
    gateway = GatewayService(
        mode="codex_write",
        codex=codex,
        legacy=None,
        message_store=message_store,
        binding_loader=lambda **kwargs: ThreadBinding(
            thread_id="thr-continuation",
            tenant_id="1",
            session_id=session_id,
            user_id="u1",
            allowed_capabilities=frozenset({"catalog_read", "admission_read"}),
        ),
        snapshot_loader=_ActionSnapshotLoader(),
    )
    ws = _Socket(store, runtime, session_id)
    confirm = _confirm(session_id, "pending-1")
    # 前端合同里的版本是 0 ✓、卡片实际是 5 ✓——这正是"用户拿着旧页面点旧卡"的形状 ✓。
    confirm["conversationAction"]["expectedSourceVersion"] = 0
    ws.push(confirm)

    task = asyncio.create_task(_handle_gateway_ws_loop(ws, gateway))
    await _wait_for(
        lambda: store.of_type("conversationAction.result"), what="动作结果入流"
    )
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    results = store.of_type("conversationAction.result")
    assert len(results) == 1
    assert results[0].payload["actionStatus"] == "stale_state"
    # 没有续接：没有新回合、没有模型回合、没有助手消息、也没有伪造的用户消息 ✓。
    assert [event for event in store.events if event.turn_id.startswith("cont-")] == []
    assert codex.turns == []
    assert message_store.agent_messages == []
    assert message_store.user_messages == []
    assert execute.calls == []


class _FailingContinuationCodex(_ContinuationCodex):
    """续接那一轮就崩的替身（进程/模型侧故障的形状 ✓）。"""

    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    async def start_turn_and_collect(self, thread_id, input_items, output_schema=None, **kwargs):
        self.attempts += 1
        self.turns.append(input_items)
        raise RuntimeError("codex app server exited")


@pytest.mark.asyncio
async def test_a_failed_continuation_is_told_once_and_never_loops(monkeypatch) -> None:
    """续接回合自己失败 → **只有一轮续接**：一条不吓人的说明（确认**已经生效** ✓），
    不重试、不循环 ✓✓。用户回一句"继续"就是一个普通用户回合 ✓（此处不需要它 ✓）。
    """
    from app.gateway import conversation_actions
    from app.gateway.service import GatewayService
    from app.harness.binding import ThreadBinding

    resolve = _JavaRecorder([
        {"code": 0, "status": "applying", "data": {"revision": 2}},
        {"code": 0, "status": "completed"},
    ])
    execute = _JavaRecorder([
        {"code": 0, "status": "applied", "data": {"stateVersion": 7}},
    ])
    monkeypatch.setattr(conversation_actions, "resolve_pending_confirmation", resolve)
    monkeypatch.setattr(conversation_actions, "execute_pending_planning_command", execute)

    session_id = "900049"
    store = _MemoryEventStore()
    runtime = SessionRuntime()
    codex = _FailingContinuationCodex()
    message_store = _RecordingStore()
    gateway = GatewayService(
        mode="codex_write",
        codex=codex,
        legacy=None,
        message_store=message_store,
        binding_loader=lambda **kwargs: ThreadBinding(
            thread_id="thr-continuation",
            tenant_id="1",
            session_id=session_id,
            user_id="u1",
            allowed_capabilities=frozenset({"catalog_read", "admission_read"}),
        ),
        snapshot_loader=_ActionSnapshotLoader(),
    )
    ws = _Socket(store, runtime, session_id)
    confirm = _confirm(session_id, "pending-1")
    confirm["conversationAction"]["expectedSourceVersion"] = 5
    ws.push(confirm)

    task = asyncio.create_task(_handle_gateway_ws_loop(ws, gateway))
    await _wait_for(
        lambda: any(
            event.turn_id.startswith("cont-") and event.type == "turn.completed"
            for event in store.events
        ),
        what="续接回合收尾（失败也要收尾 ✓）",
    )
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    # 动作结果照旧 applied ✓。
    results = store.of_type("conversationAction.result")
    assert len(results) == 1 and results[0].payload["actionStatus"] == "applied"

    # 续接那一轮：started → recoverable.error（措辞说明"确认已生效、点继续就接着做" ✓）→ completed ✓。
    continuation = [event for event in store.events if event.turn_id.startswith("cont-")]
    assert [event.type for event in continuation] == [
        "turn.started",
        "recoverable.error",
        "turn.completed",
    ]
    message = continuation[1].payload["message"]
    assert "已经生效" in message and "继续" in message
    # **不循环**：续接只起了一轮、模型只被叫了一次、没有助手消息落库 ✓。
    assert sum(1 for event in continuation if event.type == "turn.started") == 1
    assert codex.attempts == 1
    assert message_store.agent_messages == []
    assert message_store.user_messages == []
    # Java 执行恰好一趟：失败的是"自动接上"，不是确认本身 ✓。
    assert len(resolve.calls) == 2 and len(execute.calls) == 1
