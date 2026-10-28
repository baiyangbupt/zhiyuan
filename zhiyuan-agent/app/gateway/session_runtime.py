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
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from app.gateway.ui_events import EVENT_TYPES, SessionKey, resync_snapshot
from app.gateway.session_lifecycle import SessionLease, SessionLifecycle


logger = logging.getLogger(__name__)

ACCEPTED = "accepted"
BUSY = "busy"
DUPLICATE = "duplicate"
CONFLICT = "conflict"


def request_content_digest(*, message_type: str, user_id: str, content: Any, action: Any = None) -> str:
    canonical = json.dumps(
        {"type": message_type, "userId": user_id, "content": content, "action": action},
        sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _request_outcome(result: Any) -> str:
    if not isinstance(result, Mapping):
        return "completed"
    error = result.get("error")
    if error == "turn_interrupted":
        return "interrupted"
    if error:
        return "failed"
    output = result.get("output")
    if isinstance(output, Mapping):
        execution_status = output.get("executionStatus")
        if execution_status in {"failed", "interrupted"}:
            return execution_status
    action_result = result.get("actionResult")
    if isinstance(action_result, Mapping) and action_result.get("actionStatus") == "failed":
        return "failed"
    return "completed"


@dataclass(frozen=True, slots=True)
class DeferredRequest:
    key: SessionKey
    client_request_id: str
    ui_turn_id: str


@dataclass(slots=True)
class _PendingRequest:
    ui_turn_id: str
    request_digest: str
    task: asyncio.Task[Any]


@dataclass(slots=True)
class AdmissionGate:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


@dataclass(slots=True)
class ActiveTurn:
    key: SessionKey
    ui_turn_id: str
    codex_turn_id: str | None = None
    client_request_id: str = ""
    request_digest: str = ""


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
        self._lifecycle: SessionLifecycle | None = None
        self._connection_lease: SessionLease | None = None
        self._closed = False
        self._close_waiter: asyncio.Future[None] | None = None
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize)
        self._task: asyncio.Task[None] | None = None
        self.overflowed = False
        # Stored replay has its own bounded window; it must not fill the live queue
        # before the sender starts. Live frames collected during replay follow it.
        self._replay_frames: list[dict[str, Any]] = []
        self._replay_watermarks: dict[str, int] = {}

    def start(self) -> None:
        if self._closed:
            raise ValueError("connection already closed")
        if self._task is None:
            coroutine = self._drain()
            try:
                self._task = asyncio.create_task(coroutine)
            except BaseException:
                coroutine.close()
                raise

    def bind_session(self, key: SessionKey) -> None:
        """这条连接属于哪个会话。第一条消息到达时才知道，所以是延迟绑定。"""
        if self._session_key is not None and self._session_key != key:
            raise ValueError("connection cannot be rebound to another session")
        self._session_key = key

    def hold_connection(self, key: SessionKey, lifecycle: SessionLifecycle) -> None:
        if self._closed:
            raise ValueError("connection already closed")
        if self._lifecycle is not None and self._lifecycle is not lifecycle:
            raise ValueError("connection lifecycle mismatch")
        self.bind_session(key)
        if self._connection_lease is None:
            self._lifecycle = lifecycle
            self._connection_lease = lifecycle.acquire(key, "connection")

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
            except Exception as exc:
                # A V1 connection must not silently downgrade to the legacy
                # projection, which loses action status and cannot be replayed.
                # Exception bodies may contain the rejected event: log only type.
                event_type = event.get("type")
                logger.error("event_store_append_failed event_type=%s error_class=%s",
                             event_type if event_type in EVENT_TYPES else "unknown", type(exc).__name__)
                epoch = ""
                watermark = 0
                try:
                    epoch = str(await self._store.current_epoch(self._session_key) or "")
                    watermark = await self._store.watermark(self._session_key)
                except Exception:
                    pass
                baseline: dict[str, Any] = {"reason": "event_store_append_failed", "lastSequence": watermark}
                if event_type == "conversationAction.result":
                    source = event.get("payload")
                    if isinstance(source, Mapping):
                        baseline["actionResult"] = {
                            key: value[:128] if isinstance(value, str) else value
                            for key in ("proposalRef", "actionStatus", "newStateVersion", "workspaceVersion")
                            if isinstance((value := source.get(key)), (str, int))
                        }
                await self.emit_frame(resync_snapshot(
                    session_id=self._session_key.session_id,
                    turn_id=str(event.get("turnId") or self._turn_id),
                    stream_epoch=epoch, baseline=baseline,
                ))
                return
            await self.emit_frame(numbered.model_dump(by_alias=True))
            return
        await self.emit_frame(
            self._frame_builder(event) if self._frame_builder is not None else event
        )

    @property
    def closed(self) -> bool:
        return self._closed

    async def emit_replay_frame(self, frame: dict[str, Any]) -> None:
        """Queue the already bounded store replay ahead of concurrent live frames."""
        if self._closed or self.overflowed:
            return
        self._replay_frames.append(frame)
        epoch = frame.get("streamEpoch")
        sequence = frame.get("sequence")
        if epoch and isinstance(sequence, int) and sequence > 0:
            self._replay_watermarks[str(epoch)] = max(
                sequence, self._replay_watermarks.get(str(epoch), 0)
            )
        elif frame.get("type") == "session.resync" and epoch:
            baseline = (frame.get("payload") or {}).get("baseline") or {}
            self._replay_watermarks[str(epoch)] = int(baseline.get("lastSequence") or 0)

    async def emit_frame(self, frame: dict[str, Any]) -> None:
        """已经拼好的帧（例如终态回复）原样入队——不要再包一层。"""
        if self._closed or self.overflowed:
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
        replay = iter(self._replay_frames)
        while not self.overflowed:
            event = next(replay, None)
            if event is None:
                self._replay_frames.clear()
                event = await self._queue.get()
                epoch = str(event.get("streamEpoch") or "")
                sequence = event.get("sequence")
                if (isinstance(sequence, int) and sequence > 0
                        and sequence <= self._replay_watermarks.get(epoch, 0)):
                    continue
            try:
                delivered = await self._send(event)
            except Exception:
                self._closed = True
                return
            if not delivered:
                self._closed = True
                return

    async def close(self) -> None:
        if self._close_waiter is not None:
            await asyncio.shield(self._close_waiter)
            return
        self._close_waiter = asyncio.get_running_loop().create_future()
        self._closed = True
        try:
            if self._task is not None:
                self._task.cancel()
                await asyncio.gather(self._task, return_exceptions=True)
        finally:
            self._task = None
            self._replay_frames.clear()
            self._replay_watermarks.clear()
            if self._connection_lease is not None:
                self._connection_lease.close()
            self._close_waiter.set_result(None)


class SessionRuntime:
    def __init__(
        self,
        *,
        store: Any | None = None,
        interrupt_impl: Callable[[str, str], Awaitable[Any]] | None = None,
        steer_impl: Callable[[str, str, str], Awaitable[Any]] | None = None,
        lifecycle: SessionLifecycle | None = None,
    ) -> None:
        self._active: dict[SessionKey, ActiveTurn] = {}
        self._channels: dict[SessionKey, ConnectionChannel] = {}
        self._tasks: dict[SessionKey, asyncio.Task[Any]] = {}
        self._admission_gates: dict[SessionKey, AdmissionGate] = {}
        self._pending_requests: dict[tuple[SessionKey, str], _PendingRequest] = {}
        # 不随"某一轮/某条连接"走的活儿 ✓（见 `detach_work` ✓）：只保住引用 ✓，不参与回合互斥 ✗。
        self._detached: set[asyncio.Task[Any]] = set()
        self._store = store
        self._interrupt_impl = interrupt_impl
        self._steer_impl = steer_impl
        self.lifecycle = lifecycle or SessionLifecycle()

    def detach_work(
        self,
        key: SessionKey,
        work: Callable[[], Awaitable[Any]],
        *,
        label: str,
        client_request_id: str = "",
        ui_turn_id: str = "",
    ) -> DeferredRequest:
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
        pending = self._pending_requests.get((key, client_request_id))
        if not ui_turn_id and pending is not None:
            ui_turn_id = pending.ui_turn_id
        coroutine = self._run_request(key, client_request_id, ui_turn_id, work)
        lease = self.lifecycle.acquire(key, "action")
        try:
            task = asyncio.create_task(coroutine)
        except BaseException:
            coroutine.close()
            lease.close()
            raise
        if client_request_id:
            self._pending_requests[key, client_request_id] = _PendingRequest(
                ui_turn_id=ui_turn_id,
                request_digest=pending.request_digest if pending is not None else ui_turn_id,
                task=task,
            )
        self._detached.add(task)

        def _done(done: asyncio.Task[Any]) -> None:
            self._detached.discard(done)
            self._release_request(key, client_request_id, done)
            lease.close()
            if done.cancelled():
                return
            error = done.exception()
            if error is not None:
                logger.warning("detached %s failed for %s: %r", label, key, error)

        task.add_done_callback(_done)
        return DeferredRequest(key, client_request_id, ui_turn_id)

    def attach_connection(self, key: SessionKey, channel: ConnectionChannel) -> None:
        """记住这个会话当前该往哪条连接推事件。

        一个会话同时只留最新的一条：旧连接要么已经断了，要么马上会被前端换掉，
        往上推会让"同一张卡出现两次"。
        """
        channel.hold_connection(key, self.lifecycle)
        self._channels[key] = channel

    def detach_connection(self, key: SessionKey, channel: ConnectionChannel) -> None:
        if self._channels.get(key) is channel:
            self._channels.pop(key, None)

    async def publish(self, key: SessionKey, event: dict[str, Any]) -> bool:
        """把事件推到该会话的当前连接。没有连接时返回 False，不排队。"""
        channel = self._channels.get(key)
        if channel is None or getattr(channel, "closed", False):
            if channel is not None:
                self.detach_connection(key, channel)
            return False
        lease = self.lifecycle.acquire(key, "publish")
        try:
            await channel.emit(event)
            return True
        finally:
            lease.close()

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

    def ui_turn_for_codex(self, key: SessionKey, codex_turn_id: str) -> str | None:
        """`bind_codex_turn` 的**反向**查表：原生回合号 → 业务回合号 ✓✓。

        澄清桥要用它 ✗✓：codex 的原生请求（`item/tool/requestUserInput` /
        elicitation ✓）里只有**原生** `params.turnId` ✓（如 `turn_22` ✓），
        而事件流按**业务**号索引 ✓——不翻的话原生号直通进流 ✗ → 刷新补发
        只认业务号的事件 ✓ → 卡被滤掉、回不来 ✗（F10 自 10-06 红的真根 ✓）。

        解析不出来（没绑上 / 号对不上 ✓）返回 None ✓：调用方保持原样 ✓，
        不在这里猜——"唯一活动回合"不是"这条请求属于它"的证据 ✗。
        """
        if not codex_turn_id:
            return None
        turn = self.active_turn(key)
        if turn is None or turn.codex_turn_id != codex_turn_id:
            return None
        return turn.ui_turn_id

    @asynccontextmanager
    async def _admission_gate(self, key: SessionKey):
        lease = self.lifecycle.acquire(key, "admission")
        gate = self._admission_gates.setdefault(key, AdmissionGate())
        gate.users += 1
        try:
            async with gate.lock:
                yield
        finally:
            lease.close()
            gate.users -= 1
            if gate.users == 0:
                self._admission_gates.pop(key, None)

    async def request_status(self, key: SessionKey, client_request_id: str) -> dict[str, Any]:
        with self.lifecycle.acquire(key, "gateway_read"):
            return await self._request_status(key, client_request_id)

    async def _request_status(self, key: SessionKey, client_request_id: str) -> dict[str, Any]:
        pending = self._pending_requests.get((key, client_request_id))
        if pending is not None and not pending.task.done():
            return {"status": "running", "turnId": pending.ui_turn_id}
        if self._store is not None:
            stored = await self._store.request_result(key, client_request_id)
            if stored:
                try:
                    status = json.loads(stored)
                    if isinstance(status, dict) and status.get("status"):
                        if status["status"] == "running":
                            status["status"] = "recovery_required"
                        return status
                except (TypeError, ValueError):
                    pass
        return {"status": "recovery_required"}

    async def _save_request_status(self, key: SessionKey, request_id: str, turn_id: str, status: str) -> None:
        if self._store is not None and request_id:
            await self._store.finish_request(
                key, request_id, json.dumps({"status": status, "turnId": turn_id}),
            )

    def _release_request(self, key: SessionKey, request_id: str, task: asyncio.Task[Any] | None) -> None:
        pending = self._pending_requests.get((key, request_id))
        if pending is not None and pending.task is task:
            self._pending_requests.pop((key, request_id), None)

    async def _run_request(
        self,
        key: SessionKey,
        request_id: str,
        turn_id: str,
        work: Callable[[], Awaitable[Any]],
    ) -> Any:
        status = "completed"
        deferred = False
        task = asyncio.current_task()
        try:
            result = await work()
            deferred = isinstance(result, DeferredRequest)
            if not deferred:
                status = _request_outcome(result)
            return result
        except asyncio.CancelledError:
            status = "interrupted"
            raise
        except BaseException:
            status = "failed"
            raise
        finally:
            pending = self._pending_requests.get((key, request_id))
            try:
                if not deferred and pending is not None and pending.task is task:
                    await self._save_request_status(key, request_id, turn_id, status)
            finally:
                self._release_request(key, request_id, task)

    async def submit(
        self,
        key: SessionKey,
        *,
        client_request_id: str,
        ui_turn_id: str,
        work: Callable[[], Awaitable[Any]],
        request_digest: str | None = None,
    ) -> str:
        digest = request_digest if request_digest is not None else ui_turn_id
        async with self._admission_gate(key):
            pending = self._pending_requests.get((key, client_request_id))
            if pending is not None and not pending.task.done():
                return DUPLICATE if pending.request_digest == digest else CONFLICT
            active = self.active_turn(key)
            if active is not None:
                if client_request_id and active.client_request_id == client_request_id:
                    return DUPLICATE if active.request_digest == digest else CONFLICT
                return BUSY
            if self._store is not None and client_request_id:
                verdict = await self._store.admit(key, client_request_id, digest)
                if verdict in {DUPLICATE, CONFLICT}:
                    return verdict
                if verdict != ACCEPTED:
                    raise RuntimeError("invalid_request_admission_verdict")
                await self._save_request_status(key, client_request_id, ui_turn_id, "running")

            coroutine = self._run_request(key, client_request_id, ui_turn_id, work)
            lease = self.lifecycle.acquire(key, "turn")
            try:
                task = asyncio.create_task(coroutine)
            except BaseException:
                coroutine.close()
                lease.close()
                raise
            if client_request_id:
                self._pending_requests[key, client_request_id] = _PendingRequest(
                    ui_turn_id=ui_turn_id, request_digest=digest, task=task,
                )
            self._tasks[key] = task
            self._active[key] = ActiveTurn(
                key=key, ui_turn_id=ui_turn_id,
                client_request_id=client_request_id, request_digest=digest,
            )
            task.add_done_callback(
                lambda done, key=key, lease=lease: self._release(
                    key, done, client_request_id, lease
                )
            )
            return ACCEPTED

    def _release(
        self,
        key: SessionKey,
        done: asyncio.Task[Any],
        request_id: str = "",
        lease: SessionLease | None = None,
    ) -> None:
        self._release_request(key, request_id, done)
        if lease is not None:
            lease.close()
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
        with self.lifecycle.acquire(key, "gateway_read"):
            return await self._interrupt(key, ui_turn_id)

    async def _interrupt(self, key: SessionKey, ui_turn_id: str) -> dict[str, Any]:
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
        with self.lifecycle.acquire(key, "gateway_read"):
            return await self._steer(key, ui_turn_id, text)

    async def _steer(self, key: SessionKey, ui_turn_id: str, text: str) -> dict[str, Any]:
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
