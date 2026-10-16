from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from typing import Any, Protocol

from app.harness.protocol import JsonRpcResponse, Notification

logger = logging.getLogger(__name__)

# 未匹配的通知最多留这么多条、这么久。超出的最旧一条被丢弃，并被计数。
# 注意：**活动等待者不会因此丢掉终态**——`_route_notification` 先匹配等待者，
# 匹配不上才进 backlog。这个上限保护的是内存，不是正确性。
NOTIFICATION_BACKLOG_MAX = 1024
NOTIFICATION_BACKLOG_TTL_SECONDS = 60.0

# stdout 单行的缓冲上限。**这不是性能参数，是正确性参数。**
# `asyncio.create_subprocess_exec` 不传 `limit` 时是 64 KiB；原生进程一条通知就能
# 超过它——实测（2026-09-21）一次"神秘死亡"对应的 rollout 记录是 **229 KiB**。
# 超限时 `readline()` 抛 `ValueError`，`_read_stdout` 的 finally 于是把在途请求全判成
# `AppServerExited`：**进程明明还活着**（`is_running` 为 True），恢复路径却以为它死了、
# 关掉它的 stdin，活进程随即优雅退出（rollout 里留下 `turn_aborted/interrupted`、
# 退出码 0）。用户看到的是"这一轮引擎不可用"，而且——没有 J7 那层重拉的时候——
# 进程从此再也读不到任何回复，**每一轮都超时，CPU 却空着**（评估器最初报的就是这个）。
# 16 MiB 比实测最大值高两个数量级；它只是个缓冲上限，不会预分配内存。
DEFAULT_STDOUT_LINE_LIMIT = 16 * 1024 * 1024


class RequestLease(Protocol):
    def close(self) -> None: ...


class AppServerProtocolError(RuntimeError):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.data = data


class AppServerTimeout(TimeoutError):
    pass


class AppServerExited(RuntimeError):
    """app-server 进程退出了，在途请求全部作废。

    它必须是一个**类型**，不能只是一句话：恢复链路要据此决定"重拉 runtime
    并重建 thread"，那是个结构性判断。靠匹配 "app server exited" 这串英文，
    上游换个措辞就会退化成"认不出的失败 → 整个会话不可用"——实测中正是这么
    发生的（而且崩掉的 runtime 不会自己复活，新会话也一起挂）。
    """


class AppServerClient:
    def __init__(
        self,
        command: list[str],
        *,
        request_timeout: float = 30.0,
        server_request_handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]] | None = None,
        server_request_lease_factory: Callable[[dict[str, Any]], RequestLease | None] | None = None,
        line_limit: int = DEFAULT_STDOUT_LINE_LIMIT,
    ) -> None:
        self.command = command
        self.request_timeout = request_timeout
        self.line_limit = line_limit
        self.process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._pending: dict[int | str, asyncio.Future[dict[str, Any]]] = {}
        self._notification_backlog: list[tuple[float, dict[str, Any]]] = []
        self._notification_waiters: list[
            tuple[Callable[[dict[str, Any]], bool], asyncio.Future[dict[str, Any]]]
        ] = []
        self._next_id = 0
        self._closed = False
        self.server_request_handler = server_request_handler
        self.server_request_lease_factory = server_request_lease_factory
        self._server_request_tasks: set[asyncio.Task[None]] = set()
        self._overflow_dropped = 0
        self.runtime_generation = secrets.token_hex(8)
        self._ended_generation: str | None = None
        self._on_runtime_started: Callable[[str], None] | None = None
        self._on_runtime_exited: Callable[[str], None] | None = None
        self._on_runtime_notification: Callable[[str, dict[str, Any]], None] | None = None
        self._notification_observers: list[
            tuple[str, Callable[[dict[str, Any]], bool], asyncio.Future[dict[str, Any]]]
        ] = []

    def set_runtime_handlers(
        self,
        *,
        on_started: Callable[[str], None] | None = None,
        on_exited: Callable[[str], None] | None = None,
        on_notification: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self._on_runtime_started = on_started
        self._on_runtime_exited = on_exited
        self._on_runtime_notification = on_notification

    @contextmanager
    def observe_notification(
        self, predicate: Callable[[dict[str, Any]], bool],
    ) -> Iterator[asyncio.Future[dict[str, Any]]]:
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        observer = self.runtime_generation, predicate, future
        self._notification_observers.append(observer)
        try:
            yield future
        finally:
            self._notification_observers.remove(observer)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()

    @property
    def protocol_overflow_count(self) -> int:
        """被丢弃的未匹配通知条数。用于让受影响的运行能**说出**自己可能缺事件。"""
        return self._overflow_dropped

    @property
    def pending_request_count(self) -> int:
        return len(self._pending)

    async def start(self) -> None:
        if self.process is not None:
            return
        self.process = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # 见 DEFAULT_STDOUT_LINE_LIMIT：默认的 64 KiB 会被一条大通知撑爆，
            # 而后果是"把活着的进程判成死的"。
            limit=self.line_limit,
        )
        self.runtime_generation = secrets.token_hex(8)
        self._ended_generation = None
        if self._on_runtime_started is not None:
            self._on_runtime_started(self.runtime_generation)
        self._reader_task = asyncio.create_task(self._read_stdout())
        asyncio.create_task(self._read_stderr())
        asyncio.create_task(self._watch_process_exit())

    async def _watch_process_exit(self) -> None:
        """进程退出时把**退出码**记下来。

        "app-server 没了"是一个结论，退出码才是它的证据。实测形状（codex 源码
        `app-server-transport/src/transport/stdio.rs`）：stdin EOF 或 SIGTERM 会启动
        关停，watchdog 最多 45 秒后 `exit(1)`；此外 0=自己退、-9=被 SIGKILL、
        -15=被 SIGTERM、134=abort。没有这一条，"它为什么没了"只能靠猜——2026-09-21
        那两次自退就是这么无从归因的（只看到 `AppServerExited`，看不到死法）。
        """
        process = self.process
        if process is None:
            return
        returncode = await process.wait()
        # 两种"不是自退"：正在关停（`_closed`），或已经换了进程（重启）。
        if self._closed or self.process is not process:
            logger.debug("app server exited on request returncode=%s", returncode)
            return
        logger.warning("app server exited on its own returncode=%s", returncode)

    async def initialize(
        self,
        *,
        client_name: str,
        client_version: str,
        capabilities: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """握手。

        `capabilities` 为 None 时不发该字段——旧调用方的报文逐字不变。
        这不是兼容性洁癖：声明 experimental 能力会改变服务端暴露的方法集，
        默认声明等于替运维做了一次他们没做过的决定。
        """
        params: dict[str, Any] = {"clientInfo": {"name": client_name, "version": client_version}}
        if capabilities is not None:
            params["capabilities"] = capabilities
        result = await self.request("initialize", params)
        await self.notify("initialized", {})
        return result

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        await self._write({"jsonrpc": "2.0", "method": method, "params": params or {}})

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.process is None or self.process.stdin is None:
            raise RuntimeError("app server is not started")
        # "从没起来"是调用方的编程错误，"起来过又死了"是运行时故障——后者
        # 恢复路径要能认出来（重拉 + 重建），所以必须是不同的类型。
        # 先查再写：进程已死时写 stdin 得到的是 `ConnectionResetError`，
        # 那是一句没有任何语义的系统错误，分类器无从下手。
        if not self.is_running:
            raise AppServerExited("app server is not running")
        request_id = self._next_id
        self._next_id += 1
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            try:
                await self._write(
                    {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
                )
            except (ConnectionResetError, BrokenPipeError) as exc:
                # 检查与写入之间进程死掉的竞态窗口。
                raise AppServerExited("app server exited") from exc
            try:
                return await asyncio.wait_for(future, timeout=self.request_timeout)
            except asyncio.TimeoutError as exc:
                raise AppServerTimeout(f"request timed out: {method}") from exc
        finally:
            self._pending.pop(request_id, None)

    async def next_notification(self) -> dict[str, Any]:
        return await self.wait_for_notification(lambda _: True)

    async def wait_for_notification(
        self,
        predicate: Callable[[dict[str, Any]], bool],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Wait for one matching notification without losing unrelated events."""
        self._expire_backlog()
        for index, (_, notification) in enumerate(self._notification_backlog):
            if predicate(notification):
                return self._notification_backlog.pop(index)[1]

        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        waiter = (predicate, future)
        self._notification_waiters.append(waiter)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            if waiter in self._notification_waiters:
                self._notification_waiters.remove(waiter)

    def _expire_backlog(self) -> None:
        cutoff = time.monotonic() - NOTIFICATION_BACKLOG_TTL_SECONDS
        self._notification_backlog = [
            entry for entry in self._notification_backlog if entry[0] >= cutoff
        ]

    def _route_notification(
        self, notification: dict[str, Any], *, runtime_generation: str | None = None,
    ) -> None:
        """Deliver a notification to one matching waiter or preserve it for later.

        顺序很重要：**先匹配等待者，匹配不上才进 backlog**。这个顺序保证了
        积压上限再小也不会吃掉某次运行的终态——终态到达时那个运行的等待者正在
        等着，第一步就把它领走了。
        """
        generation = runtime_generation if runtime_generation is not None else self.runtime_generation
        if generation != self.runtime_generation or generation == self._ended_generation:
            return
        if self._on_runtime_notification is not None:
            self._on_runtime_notification(generation, notification)
        for observer_generation, predicate, future in list(self._notification_observers):
            if observer_generation == generation and not future.done() and predicate(notification):
                future.set_result(notification)
        for predicate, future in list(self._notification_waiters):
            if future.done():
                continue
            if predicate(notification):
                future.set_result(notification)
                return
        self._expire_backlog()
        if len(self._notification_backlog) >= NOTIFICATION_BACKLOG_MAX:
            # 丢弃最旧的一条并计数：新来的可能正被某个等待者需要，旧的最不可能。
            # 丢弃不是无声的——计数会被受影响的运行读走。
            self._notification_backlog.pop(0)
            self._overflow_dropped += 1
        self._notification_backlog.append((time.monotonic(), notification))

    async def _write(self, payload: dict[str, Any]) -> None:
        if self.process is None or self.process.stdin is None:
            raise RuntimeError("app server is not started")
        self.process.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())
        await self.process.stdin.drain()

    async def _read_stdout(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        process = self.process
        generation = self.runtime_generation
        request_tasks: set[asyncio.Task[None]] = set()
        stream_broken: str | None = None
        try:
            while True:
                try:
                    raw_line = await process.stdout.readline()
                except ValueError as exc:
                    # **超长行不等于进程死了**（这个区分是本文件最贵的一课，见模块常量
                    # `DEFAULT_STDOUT_LINE_LIMIT` 的注释）：readline 撞上限时抛 ValueError，
                    # 而缓冲里的数据还在，但这行已经读不完整，流是接不回去的。
                    # 所以照实记下来，再按"这条流废了"处理（恢复路径会重拉 runtime）。
                    stream_broken = f"stdout line exceeded {self.line_limit} bytes ({exc})"
                    logger.error(
                        "app-server %s; the stream cannot be resynchronized, "
                        "treating it as unreadable (the process itself may still be alive)",
                        stream_broken,
                    )
                    break
                if not raw_line:
                    break
                if self.process is not process or not self._accepts_generation(generation):
                    break
                # `errors="replace"` 与 `_read_stderr` 一致：一行里有坏字节的解码错误
                # 也会走进同一个 finally，把活着的进程判成死的——那是同一课的另一个入口。
                # 换掉之后它退化成"非 JSON 行"，只丢这一条。
                line = raw_line.decode(errors="replace").strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("ignored non-json app-server stdout line")
                    continue
                if "id" in payload and payload.get("method"):
                    if self.server_request_handler is not None:
                        lease = None
                        admission_error = None
                        if self.server_request_lease_factory is not None:
                            try:
                                lease = self.server_request_lease_factory(payload)
                            except Exception as exc:
                                admission_error = exc
                        coroutine = self._handle_server_request(
                            payload, runtime_generation=generation,
                            admission_error=admission_error,
                        )
                        try:
                            task = asyncio.create_task(coroutine)
                        except BaseException:
                            coroutine.close()
                            if lease is not None:
                                lease.close()
                            raise
                        if lease is not None:
                            task.add_done_callback(lambda done, lease=lease: lease.close())
                        self._server_request_tasks.add(task)
                        request_tasks.add(task)
                        task.add_done_callback(self._server_request_tasks.discard)
                        task.add_done_callback(request_tasks.discard)
                    else:
                        await self._write(
                            {
                                "jsonrpc": "2.0",
                                "id": payload["id"],
                                "result": None,
                            }
                        )
                elif "id" in payload and ("result" in payload or "error" in payload):
                    response = JsonRpcResponse.model_validate(payload)
                    future = self._pending.get(response.id)
                    if future is None or future.done():
                        continue
                    if response.error is not None:
                        future.set_exception(
                            AppServerProtocolError(
                                response.error.code, response.error.message, response.error.data
                            )
                        )
                    else:
                        future.set_result(response.result or {})
                elif payload.get("method"):
                    self._route_notification(
                        Notification.model_validate(payload).model_dump(), runtime_generation=generation,
                    )
        finally:
            # 进程退出的唤醒必须是**全面**的：只唤醒 _pending 的话，
            # 正在等通知的回合会一直等到自己的 deadline——而对方已经不可能再说话了。
            # 消息里带上"为什么读不下去"：退出与"流超限"处置相同（都重拉），但日志里
            # 必须分得开——分不开就是这一课本身。
            error = AppServerExited(
                "app server exited" if stream_broken is None else f"app server {stream_broken}"
            )
            if self.process is process and self.runtime_generation == generation:
                self._ended_generation = generation
                for future in self._pending.values():
                    if not future.done():
                        future.set_exception(error)
                for _, future in list(self._notification_waiters):
                    if not future.done():
                        future.set_exception(error)
            for observer_generation, _, future in list(self._notification_observers):
                if observer_generation == generation and not future.done():
                    future.set_exception(error)
            if self._on_runtime_exited is not None:
                self._on_runtime_exited(generation)
            tasks_to_cancel = list(request_tasks)
            for task in tasks_to_cancel:
                task.cancel()
            await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
            self._server_request_tasks.difference_update(tasks_to_cancel)

    async def _handle_server_request(
        self, payload: dict[str, Any], *, runtime_generation: str | None = None,
        admission_error: Exception | None = None,
    ) -> None:
        assert self.server_request_handler is not None
        if not self._accepts_generation(runtime_generation):
            return
        try:
            if admission_error is not None:
                raise admission_error
            result = await self.server_request_handler(payload)
            if not self._accepts_generation(runtime_generation):
                return
            response: dict[str, Any] = {"jsonrpc": "2.0", "id": payload["id"]}
            if result is None:
                response["result"] = None
            else:
                response["result"] = result
            await self._write(response)
        except Exception as exc:
            if not self._accepts_generation(runtime_generation):
                return
            await self._write(
                {
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "error": {"code": -32000, "message": str(exc)},
                }
            )

    def _accepts_generation(self, runtime_generation: str | None) -> bool:
        return runtime_generation is None or (
            runtime_generation == self.runtime_generation
            and runtime_generation != self._ended_generation
            and not self._closed
        )

    async def _read_stderr(self) -> None:
        if self.process is None or self.process.stderr is None:
            return
        while True:
            try:
                raw_line = await self.process.stderr.readline()
            except ValueError:
                # stderr 不承载协议：超限只意味着"这一行看不到"，丢掉继续读。
                # （stdout 上同样的错误必须重拉——那边的 JSON-RPC 分帧废了。）
                logger.warning("app server stderr line exceeded the buffer limit; dropped")
                continue
            if not raw_line:
                return
            logger.debug("app-server: %s", raw_line.decode(errors="replace").rstrip())

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.process is not None:
            if self.process.stdin is not None:
                self.process.stdin.close()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=2)
            except (asyncio.TimeoutError, ProcessLookupError):
                self.process.kill()
                await self.process.wait()
        if self._reader_task is not None:
            self._reader_task.cancel()
            await asyncio.gather(self._reader_task, return_exceptions=True)

    @property
    def is_running(self) -> bool:
        """进程还在吗。已退出与从未启动是两种状态，但对调用方同样是"用不了"。"""
        return self.process is not None and self.process.returncode is None

    async def restart(self) -> None:
        """重拉 app-server。

        退出后的进程不会自己复活，而**一条坏 thread 就能把它打死**（实测：
        resume 某个 thread 时 codex 直接退出）。没有这个入口，恢复路径就只能
        撞在一个死进程上，整个 agent 跟着一起废——新建会话也一样失败。
        """
        await self.close()
        self._closed = False
        # 死进程留下的在途状态一律丢掉：backlog 与 pending 都是它的遗物，
        # 带着它们重拉等于把旧世界的等待者接到新进程上。
        self._notification_backlog.clear()
        for waiter in list(self._notification_waiters):
            _, future = waiter
            if not future.done():
                future.set_exception(AppServerExited("app server restarted"))
        self._notification_waiters.clear()
        self.process = None
        await self.start()
