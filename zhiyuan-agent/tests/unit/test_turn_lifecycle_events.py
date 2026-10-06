"""回合生命周期事件的生产者：`turn.started` / `turn.phase` / `clarification.resolved` ✓✓。

这三条在**白名单里一直存在** ✓、前端 reducer 也在等它们 ✓
（`conversationSession.mjs:48-52,70-71,81-90` ✓），但全仓**没有任何生产者** ✗：
- `turn.started` 缺席 → 回合排序用的 `startedAt` 永远为空 ✓（排序退化成字典序 ✓）；
- `turn.phase` 缺席 → 阶段提示永远不显示 ✓；
- `clarification.resolved` 被发成**老信封** ✗ → 前端把空 content 解析成 `null` 丢掉 ✓ →
  卡答完了还停在"待你作答" ✓。

所以这些用例盯的是"**有人发**"与"**发的是 V1 形状**"两件事 ✓，而不是 UI 长相 ✓。
"""
from types import SimpleNamespace

import pytest
from fastapi import WebSocketDisconnect

from app.gateway.service import _progress_emitter
from app.gateway.session_runtime import ACCEPTED
from app.server import _handle_control_message, _native_gateway_loop


class _Channel:
    """通道替身：按 `uses_v1` 决定走事件还是落帧 ✓（与真实通道同一判据 ✓）。"""

    def __init__(self, *, uses_v1: bool = True) -> None:
        self.uses_v1 = uses_v1
        self.events: list[dict] = []
        self.frames: list[object] = []
        self.sessions: list = []
        self.turns: list[str] = []

    def bind_session(self, key) -> None:
        self.sessions.append(key)

    def bind_turn(self, turn_id: str) -> None:
        self.turns.append(turn_id)

    async def emit(self, event: dict) -> None:
        self.events.append(event)

    async def emit_frame(self, frame) -> None:
        self.frames.append(frame)


class _InlineRuntime:
    """接住回合就**当场跑掉**的工作替身 ✓。

    真实运行时把 work 放到后台任务 ✓，但"工作被接受才跑"这一判据相同 ✓：就地 await
    才能让断言在接收器返回前看到事件 ✓（不用 sleep / 反复轮询 ✓）。
    `publish` 返回 False 时事件退回本连接 ✓（`_session_emitter` ✓）——返回 True 的那条
    分支由单独的用例覆盖 ✓。
    """

    def __init__(self, *, publish: bool = False) -> None:
        self.submitted: list[tuple] = []
        self.published: list[dict] = []
        self._publish = publish

    def attach_connection(self, key, channel) -> None:
        self.attached = (key, channel)

    async def submit(self, key, *, client_request_id, ui_turn_id, work):
        self.submitted.append((key, client_request_id, ui_turn_id))
        await work()
        return ACCEPTED

    async def publish(self, key, event: dict) -> bool:
        self.published.append(event)
        return self._publish


class _Gateway:
    """网关替身：回合中途**一定**发一条工具进度 ✓——顺序断言只有真发一条才测得出来 ✓。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def handle_turn(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        await kwargs["emit"](
            {
                "type": "tool.progress",
                "payload": {
                    "itemId": "i1",
                    "tool": "admission.get_history",
                    "status": "started",
                    "label": "正在查询历年录取",
                },
            }
        )
        return {"reply": "答案"}


class _Socket:
    """把预设消息依次吐出来的假连接：消息发完就抛 `WebSocketDisconnect` ✓——
    接收器的出口只有这一个 ✓（真实断开与"没有下一条"在循环看来是同一件事 ✓）。"""

    def __init__(self, *messages, broker=None) -> None:
        self._messages = list(messages)
        self.sent: list[str] = []
        self.app = SimpleNamespace(
            state=SimpleNamespace(
                gateway_tenant_id="tenant-1",
                gateway_service=SimpleNamespace(user_input_broker=broker),
            )
        )

    async def receive_json(self):
        if not self._messages:
            raise WebSocketDisconnect()
        return self._messages.pop(0)

    async def send_text(self, text: str) -> None:
        self.sent.append(text)


class _Broker:
    """澄清桥替身：只回答"收到了什么" ✓——桥自身的语义由它自己的用例管 ✓。"""

    def __init__(self, *, status: str = "answered") -> None:
        self.calls: list[tuple] = []
        self._status = status

    async def answer(self, key, request_id, answer):
        self.calls.append((key, request_id, answer))
        return {"status": self._status}


def _tool_notification(item_id: str, tool: str) -> dict:
    """原生形状照实录制取 ✓（与 `test_ui_events.py` 同一份 ✓）——自造形状会让适配器
    测起来全绿、接真机就哑 ✓。
    """
    return {
        "method": "item/started",
        "params": {
            "threadId": "t",
            "turnId": "c",
            "item": {
                "id": item_id,
                "type": "mcpToolCall",
                "server": "zhiyuan_domain",
                "tool": tool,
                "status": "inProgress",
                "arguments": {"private": "do-not-display"},
            },
        },
    }


def _clarification_raw() -> dict:
    return {
        "type": "clarificationAnswer",
        "sessionId": "900047",
        "turnId": "ui-turn-1",
        "clarificationAnswer": {"requestId": "ui-question-1", "inputKind": "choice"},
    }


@pytest.mark.asyncio
async def test_an_accepted_turn_is_announced_before_anything_else_in_it() -> None:
    """`turn.started` 要在**同回合第一条进度之前**入流 ✓✓：顺序是事件流的合同 ✓，
    前端 reducer 按 `sequence` 排回合 ✓（`conversationSession.mjs:211-212` ✓）——
    晚发的 `turn.started` 会把回合排到它自己的进度后面 ✓。
    时钟只进 payload 作诊断 ✓（排序不看它 ✓），所以按"毫秒整数"断言 ✓。
    """
    channel = _Channel()
    runtime = _InlineRuntime()
    ws = _Socket(
        {
            "type": "chat",
            "sessionId": "900047",
            "tenantId": "tenant-1",
            "userId": "u1",
            "turnId": "ui-turn-1",
            "clientRequestId": "req-1",
            "content": "你好",
        }
    )

    await _native_gateway_loop(ws, _Gateway(), runtime, channel)

    assert [event["type"] for event in channel.events] == [
        "turn.started",  # 先于本回合任何进度 ✓
        "tool.progress",
        "assistant.completed",
        "turn.completed",
    ]
    started = channel.events[0]["payload"]
    assert set(started) == {"startedAt"}
    assert isinstance(started["startedAt"], int) and started["startedAt"] > 0
    # 回合号是**业务**回合号 ✓（envelope 的必填字段 ✓），不是原生 turnId ✓。
    assert channel.turns == ["ui-turn-1"]
    assert runtime.submitted and runtime.submitted[0][2] == "ui-turn-1"


@pytest.mark.asyncio
async def test_the_first_tool_progress_announces_the_phase_once() -> None:
    """`turn.phase` 要在**首次**工具进度到达时补一条 ✓✓（白名单里一直有它 ✓、
    reducer 也在等它 ✓，此前全仓无人发 ✗）。阶段就是"正在调工具/取数" ✓，
    标签借第一个工具自己的 ✓（`TOOL_LABELS` 是"只解释正在发生的操作" ✓）。
    **只发一次**：重查轮复用同一个 emitter ✓，重复播报会把阶段提示刷成"反复开始" ✗✓。
    """
    events: list[dict] = []

    async def emit(event: dict) -> None:
        events.append(event)

    callback = _progress_emitter(emit, "ui-turn-1")
    await callback(_tool_notification("i1", "admission.get_history"))
    await callback(_tool_notification("i2", "catalog.search_schools"))

    assert [event["type"] for event in events] == [
        "turn.phase",
        "tool.progress",
        "tool.progress",
    ]
    assert events[0]["payload"] == {
        "phase": "querying",
        "status": "started",
        "label": "正在查询历年录取",
    }


@pytest.mark.asyncio
async def test_an_answered_clarification_is_announced_as_a_v1_event() -> None:
    """收敛要在**用户点完**当场发生 ✓✓：旧代码发的是老信封帧 ✗（没有 `requestId` ✗、
    不是 V1 ✗）→ 前端把空 content 解析成 `null` 丢掉 ✓（`conversationEvents.mjs:57-80` ✓）
    → reducer 的 resolved 分支永远不触发 ✓✗，卡停在"待你作答" ✓。
    回合号取客户端带回的**业务回合号** ✓（`conversationProtocol.mjs:22-40` ✓）——
    不先绑上，envelope 的 turnId 可能是空的 ✓，reducer 按 turnId 找不到回合 ✓ → 同样丢 ✓。
    """
    channel = _Channel()
    runtime = _InlineRuntime()
    broker = _Broker()

    handled = await _handle_control_message(
        _Socket(broker=broker), _clarification_raw(), runtime, "tenant-1", channel
    )

    assert handled is True
    assert channel.turns == ["ui-turn-1"]
    # payload 就两个键 ✓（白名单 `conversationEvents.mjs:32` 只放这两个 ✓）。
    assert channel.events == [
        {
            "type": "clarification.resolved",
            "payload": {"requestId": "ui-question-1", "status": "answered"},
        }
    ]
    assert channel.frames == []  # 老信封那条老路不再吞掉这张卡的收敛 ✓
    assert broker.calls[0][1] == "ui-question-1"


@pytest.mark.asyncio
async def test_the_resolution_goes_to_the_sessions_current_connection() -> None:
    """收敛走**会话当前连接** ✓✓（`_session_emitter` ✓，与终态同一条路 ✓）：
    用户回答这张卡时常常是刚刷新的页面 ✓（F10 同款场景 ✓）——发到"当初那条连接"
    就是永远收不到 ✗。
    """
    channel = _Channel()
    runtime = _InlineRuntime(publish=True)

    await _handle_control_message(
        _Socket(broker=_Broker()), _clarification_raw(), runtime, "tenant-1", channel
    )

    assert [event["type"] for event in runtime.published] == ["clarification.resolved"]
    assert channel.events == []


@pytest.mark.asyncio
async def test_the_old_envelope_lane_still_gets_its_frame() -> None:
    """compat 老 UI 解析不了 V1 事件 ✓：它那条路保持原帧 ✓（回归防线 ✓）——
    "顺手把两条路都改成 V1" 会让老客户端上这张卡**永远不收敛** ✗。
    """
    channel = _Channel(uses_v1=False)
    runtime = _InlineRuntime()

    await _handle_control_message(
        _Socket(broker=_Broker()), _clarification_raw(), runtime, "tenant-1", channel
    )

    assert channel.events == []
    assert channel.frames == [{"type": "clarification.resolved", "content": "", "end": False}]
