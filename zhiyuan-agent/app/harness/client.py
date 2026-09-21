from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.harness.protocol import JsonRpcResponse, Notification

logger = logging.getLogger(__name__)

# 未匹配的通知最多留这么多条、这么久。超出的最旧一条被丢弃，并被计数。
# 注意：**活动等待者不会因此丢掉终态**——`_route_notification` 先匹配等待者，
# 匹配不上才进 backlog。这个上限保护的是内存，不是正确性。
NOTIFICATION_BACKLOG_MAX = 1024
NOTIFICATION_BACKLOG_TTL_SECONDS = 60.0


class AppServerProtocolError(RuntimeError):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.data = data


class AppServerTimeout(TimeoutError):
    pass


class AppServerClient:
    def __init__(
        self,
        command: list[str],
        *,
        request_timeout: float = 30.0,
        server_request_handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]] | None = None,
    ) -> None:
        self.command = command
        self.request_timeout = request_timeout
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
        self._server_request_tasks: set[asyncio.Task[None]] = set()
        self._overflow_dropped = 0

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
        )
        self._reader_task = asyncio.create_task(self._read_stdout())
        asyncio.create_task(self._read_stderr())

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
        request_id = self._next_id
        self._next_id += 1
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self._write(
                {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
            )
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

    def _route_notification(self, notification: dict[str, Any]) -> None:
        """Deliver a notification to one matching waiter or preserve it for later.

        顺序很重要：**先匹配等待者，匹配不上才进 backlog**。这个顺序保证了
        积压上限再小也不会吃掉某次运行的终态——终态到达时那个运行的等待者正在
        等着，第一步就把它领走了。
        """
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
        try:
            async for raw_line in self.process.stdout:
                line = raw_line.decode().strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("ignored non-json app-server stdout line")
                    continue
                if "id" in payload and payload.get("method"):
                    if self.server_request_handler is not None:
                        task = asyncio.create_task(self._handle_server_request(payload))
                        self._server_request_tasks.add(task)
                        task.add_done_callback(self._server_request_tasks.discard)
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
                    self._route_notification(Notification.model_validate(payload).model_dump())
        finally:
            # 进程退出的唤醒必须是**全面**的：只唤醒 _pending 的话，
            # 正在等通知的回合会一直等到自己的 deadline——而对方已经不可能再说话了。
            error = RuntimeError("app server exited")
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(error)
            for _, future in list(self._notification_waiters):
                if not future.done():
                    future.set_exception(error)
            for task in list(self._server_request_tasks):
                task.cancel()
            self._server_request_tasks.clear()

    async def _handle_server_request(self, payload: dict[str, Any]) -> None:
        assert self.server_request_handler is not None
        try:
            result = await self.server_request_handler(payload)
            response: dict[str, Any] = {"jsonrpc": "2.0", "id": payload["id"]}
            if result is None:
                response["result"] = None
            else:
                response["result"] = result
            await self._write(response)
        except Exception as exc:
            await self._write(
                {
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "error": {"code": -32000, "message": str(exc)},
                }
            )

    async def _read_stderr(self) -> None:
        if self.process is None or self.process.stderr is None:
            return
        async for raw_line in self.process.stderr:
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
