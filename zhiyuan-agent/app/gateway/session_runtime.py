"""会话运行时分发：每会话至多一个活动回合。

存在的理由很直接：在 WebSocket 的 `receive_json` 循环里 `await` 整个回合，
会让**收包**停摆——用户点"停止"时，那条控制消息正排在一个还没跑完的回合后面。
所以这里把回合放后台，接收器只负责分发。

三条不变量，任何实现改动都不能破坏：

1. **每会话至多一个活动推理回合。** 新回合在活动时返回 `busy`，
   不静默取消上一个——用户的诉求不能被后一句话悄悄作废。
2. **只有本会话的活动回合能被中断/转述。** 跨会话命中必须失败，
   否则一次点错就把别人的回合停了。
3. **活动锁一定释放。** 正常、异常、取消三条路径都要放，漏一条就是永久 `busy`。
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.gateway.ui_events import SessionKey


logger = logging.getLogger(__name__)

ACCEPTED = "accepted"
BUSY = "busy"
DUPLICATE = "duplicate"
CONFLICT = "conflict"


@dataclass(slots=True)
class ActiveTurn:
    key: SessionKey
    ui_turn_id: str
    codex_turn_id: str | None = None


class ConnectionChannel:
    """每连接一个**有界**发送队列 + 唯一发送器。

    它存在的理由是隔离：模型 reader 只入队就返回，慢浏览器由这里兜。
    队列满时**不阻塞 reader**，而是标记溢出并让调用方关掉这条连接——
    否则一个卡住的浏览器就能把整条模型链路拖停，而那是所有人的链路。

    唯一的发送器也保证了顺序：事件按入队顺序出去，不会两条协程交叉写同一个 socket。
    """

    def __init__(
        self,
        send: Callable[[dict[str, Any]], Awaitable[bool]],
        *,
        frame_builder: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        store: Any | None = None,
        session_key: SessionKey | None = None,
        on_overflow: Callable[[], Awaitable[None]] | None = None,
        maxsize: int = 256,
    ) -> None:
        self._send = send
        # 配置了事件存储时，事件先**入流拿编号**再发；没配置就退回旧信封。
        # 编号是断线恢复的唯一依据：没有它，客户端只能说"我少了几条"，
        # 说不出少的是哪几条，于是只能整页重来。
        self._store = store
        self._session_key = session_key
        self._turn_id = ""
        # 帧形状由**路由**决定：原生的 v3 信封与 compat 的 {type,content,end}
        # 不一样，而事件本身（进度、澄清卡）是同一份。构造放在这里，
        # 调用方就不必知道自己在哪条路由上。
        self._frame_builder = frame_builder
        self._on_overflow = on_overflow
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize)
        self._task: asyncio.Task[None] | None = None
        self.overflowed = False

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._drain())

    def bind_session(self, key: SessionKey) -> None:
        """这条连接属于哪个会话。第一条消息到达时才知道，所以是延迟绑定。"""
        self._session_key = key

    @property
    def session_key(self) -> SessionKey | None:
        """这条连接绑的会话（还没收到过消息时为 None）✓——收尾时要用它去摘连接 ✓。"""
        return self._session_key

    def bind_turn(self, ui_turn_id: str) -> None:
        """记住当前回合号：编号事件要把它写进 envelope。

        回合号是**业务**回合号，不是原生 turnId——浏览器只认这一个。
        """
        self._turn_id = str(ui_turn_id or "")

    @property
    def uses_v1(self) -> bool:
        """这条连接是否走 **V1 事件路径** ✓✓——判据就是"有没有事件存储" ✓。

        有 store ⇒ 发出去的是编号过的 V1 事件 ✓（`emit` 的路径 ✓）；
        没有 store ⇒ 只能退回老信封投影 ✗（老 UI ✓）。
        调用方据此决定"要不要发 V1 专属的事件" ✓（见 `server.py` 终态那处 ✓）——
        **给老 UI 发 V1 事件就是噪声** ✗✓。
        """
        return self._store is not None

    async def emit(self, event: dict[str, Any]) -> None:
        """把一个**事件**入队。入队即返回，**绝不 await 浏览器**。

        配了事件存储时先入流编号，再原样发编号后的 envelope；
        没配则交给本路由的帧构造器（旧信封）。
        """
        if self._store is not None and self._session_key is not None:
            try:
                numbered = await self._store.append(
                    self._session_key,
                    {
                        **event,
                        # 事件**自带的回合号优先** ✓✓：`bind_turn` 是"这条连接当前在跑哪一轮"，
                        # 它会随**后一条消息**改写 ✗——而一段活儿的收尾（确认/取消那一段 ✓，
                        # 见 `SessionRuntime.detach_work` ✓）可能落在别的消息之后 ✓：
                        # 再按 `_turn_id` 盖章就把 `conversationAction.result` 记到**别人那一轮**名下 ✗
                        # （实测：一条结果事件被盖成用户随后那条聊天消息的回合 ✓）。
                        # 前端虽然按 `proposalRef` 全量找结果 ✓（`findActionResultFor` ✓）卡不至于不翻 ✓，
                        # 但那条回合同样会被标成"已终态" ✓ → 后续增量被 reducer 丢掉 ✗✓。
                        "turnId": str(event.get("turnId") or self._turn_id),
                        "sessionId": self._session_key.session_id,
                    },
                )
            except Exception:
                # 入流出错不能让整轮**静默少事件**：退回旧信封发出去，
                # 至少用户看得到内容；恢复语义降级为"不可用"。
                await self.emit_frame(
                    self._frame_builder(event) if self._frame_builder is not None else event
                )
                return
            await self.emit_frame(numbered.model_dump(by_alias=True))
            return
        await self.emit_frame(
            self._frame_builder(event) if self._frame_builder is not None else event
        )

    async def emit_frame(self, frame: dict[str, Any]) -> None:
        """已经拼好的帧（例如终态回复）原样入队——不要再包一层。"""
        if self.overflowed:
            return
        try:
            self._queue.put_nowait(frame)
        except asyncio.QueueFull:
            await self._overflow()

    async def _overflow(self) -> None:
        self.overflowed = True
        if self._on_overflow is not None:
            await self._on_overflow()

    async def _drain(self) -> None:
        while not self.overflowed:
            event = await self._queue.get()
            try:
                delivered = await self._send(event)
            except Exception:
                return
            if not delivered:
                return

    async def close(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)
        self._task = None


class SessionRuntime:
    def __init__(
        self,
        *,
        store: Any | None = None,
        interrupt_impl: Callable[[str, str], Awaitable[Any]] | None = None,
        steer_impl: Callable[[str, str, str], Awaitable[Any]] | None = None,
    ) -> None:
        self._active: dict[SessionKey, ActiveTurn] = {}
        self._channels: dict[SessionKey, ConnectionChannel] = {}
        self._tasks: dict[SessionKey, asyncio.Task[Any]] = {}
        # 不随"某一轮/某条连接"走的活儿 ✓（见 `detach_work` ✓）：只保住引用 ✓，不参与回合互斥 ✗。
        self._detached: set[asyncio.Task[Any]] = set()
        self._store = store
        self._interrupt_impl = interrupt_impl
        self._steer_impl = steer_impl

    def detach_work(
        self, key: SessionKey, work: Callable[[], Awaitable[Any]], *, label: str
    ) -> None:
        """把一段活儿挂到**会话**上，而不是挂到"当前这一轮/这条连接"上 ✓✗。

        为什么必须有它 ✗✓（2026-09-27 真栈实测 ✓）：确认（`conversationAction`）那一段
        本来就跑在**回合**里 ✓——浏览器一点确认就整页重连（F13 那条 ✓），这一轮会被判
        `turn_interrupted` ✗ → 于是**执行早已出站**（Java 那侧照样落库 ✓、工作区从 0 前进到 3 ✓），
        而网关这一侧"发结果"的那一步**被一起带走** ✗：事件流里一条 `conversationAction.result`
        都没有 ✓，重连后卡片无从恢复 ✗——用户看到的是"点了确认，卡还停在待确认" ✓。

        事务不该被取消（任务书口径 ✓），**结果事件也不该** ✓：这段活儿与连接死没死无关 ✓，
        它发的事件照旧进事件存储 ✓（`ConnectionChannel.emit` 先入流再发帧 ✓），
        重连时由游标补发 ✓。

        与 `submit` 的分工 ✓：那个是**回合**（有互斥、有 busy 判定 ✓、可中断 ✓）；
        这个是**动作收尾**（不可中断 ✓、不占回合位 ✗）——混进 `submit` 会让"确认"被
        自己那一轮打断（就是上面那条 ✗）。
        """
        task = asyncio.create_task(work())
        self._detached.add(task)

        def _done(done: asyncio.Task[Any]) -> None:
            self._detached.discard(done)
            if done.cancelled():
                return
            error = done.exception()
            if error is not None:
                logger.warning("detached %s failed for %s: %r", label, key, error)

        task.add_done_callback(_done)

    def attach_connection(self, key: SessionKey, channel: ConnectionChannel) -> None:
        """记住这个会话当前该往哪条连接推事件。

        一个会话同时只留最新的一条：旧连接要么已经断了，要么马上会被前端换掉，
        往上推会让"同一张卡出现两次"。
        """
        self._channels[key] = channel

    def detach_connection(self, key: SessionKey, channel: ConnectionChannel) -> None:
        if self._channels.get(key) is channel:
            self._channels.pop(key, None)

    async def publish(self, key: SessionKey, event: dict[str, Any]) -> bool:
        """把事件推到该会话的当前连接。没有连接时返回 False，不排队。"""
        channel = self._channels.get(key)
        if channel is None:
            return False
        await channel.emit(event)
        return True

    def current_channel(self, key: SessionKey) -> ConnectionChannel | None:
        """该会话**当前**该往哪条连接推（没有则 None ✓）✓——**收尾那一刻**再问 ✓。

        收尾（`_emit_turn_terminal` ✓）要按它判"走 V1 事件还是老信封" ✓：入队时刻捕获的
        那条连接可能已经断了 ✗、或已被新连接顶替 ✗（判错就是"新 UI 收到老信封" ✓）。
        """
        return self._channels.get(key)

    def active_turn(self, key: SessionKey) -> ActiveTurn | None:
        turn = self._active.get(key)
        if turn is None:
            return None
        task = self._tasks.get(key)
        if task is None or task.done():
            return None
        return turn

    def bind_codex_turn(self, key: SessionKey, ui_turn_id: str, codex_turn_id: str) -> None:
        """把业务回合号与原生回合号绑上。

        `turn/steer` 要的是**原生** turnId（expectedTurnId），而浏览器只知道
        业务回合号；这层映射不放在浏览器里，否则它就能指定改哪个原生回合。
        """
        turn = self._active.get(key)
        if turn is not None and turn.ui_turn_id == ui_turn_id:
            turn.codex_turn_id = codex_turn_id

    async def submit(
        self,
        key: SessionKey,
        *,
        client_request_id: str,
        ui_turn_id: str,
        work: Callable[[], Awaitable[Any]],
    ) -> str:
        if self._store is not None and client_request_id:
            verdict = await self._store.admit(key, client_request_id, ui_turn_id)
            if verdict == "duplicate":
                # 同 id 同内容 = 重发：回"已收到"，**不**再跑一遍模型。
                return DUPLICATE
            if verdict == "conflict":
                # 同 id 不同内容 = 客户端把两个请求搞混了，不能替它挑一个。
                return CONFLICT
        if self.active_turn(key) is not None:
            return BUSY
        task = asyncio.create_task(work())
        self._tasks[key] = task
        self._active[key] = ActiveTurn(key=key, ui_turn_id=ui_turn_id)
        task.add_done_callback(lambda done, key=key: self._release(key, done))
        return ACCEPTED

    def _release(self, key: SessionKey, done: asyncio.Task[Any]) -> None:
        if self._tasks.get(key) is done:
            self._tasks.pop(key, None)
            self._active.pop(key, None)
        if done.cancelled():
            return
        # 取走异常，否则 asyncio 会在 GC 时报 "Task exception was never retrieved"，
        # 而那条日志看起来像框架问题、不像业务问题。
        error = done.exception()
        if error is not None:
            logger.warning("turn worker failed for %s: %r", key, error)

    async def interrupt(self, key: SessionKey, ui_turn_id: str) -> dict[str, Any]:
        turn = self.active_turn(key)
        if turn is None:
            return {"status": "no_active_turn"}
        if turn.ui_turn_id != ui_turn_id:
            # 跨回合的停止请求：拒绝，而不是"顺手停掉当前那个"。
            return {"status": "turn_mismatch"}
        if self._interrupt_impl is None or not turn.codex_turn_id:
            return {"status": "unavailable"}
        await self._interrupt_impl(key, turn.codex_turn_id)
        return {"status": "interrupting", "codexTurnId": turn.codex_turn_id}

    async def steer(self, key: SessionKey, ui_turn_id: str, text: str) -> dict[str, Any]:
        turn = self.active_turn(key)
        if turn is None:
            return {"status": "no_active_turn"}
        if turn.ui_turn_id != ui_turn_id:
            return {"status": "turn_mismatch"}
        if self._steer_impl is None or not turn.codex_turn_id:
            return {"status": "unavailable"}
        await self._steer_impl(key, turn.codex_turn_id, text)
        return {"status": "steered"}

    async def cancel_all(self) -> None:
        for task in list(self._tasks.values()):
            task.cancel()
        for task in list(self._tasks.values()):
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: B014 - 取消与失败都不该挡住收尾
                pass
        self._tasks.clear()
        self._active.clear()
