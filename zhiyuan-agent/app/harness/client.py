from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.harness.protocol import JsonRpcResponse, Notification

logger = logging.getLogger(__name__)


class AppServerProtocolError(RuntimeError):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.data = data


class AppServerTimeout(TimeoutError):
    pass


class AppServerClient:
    def __init__(self, command: list[str], *, request_timeout: float = 30.0) -> None:
        self.command = command
        self.request_timeout = request_timeout
        self.process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._pending: dict[int | str, asyncio.Future[dict[str, Any]]] = {}
        self._notifications: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._next_id = 0
        self._closed = False

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

    async def initialize(self, *, client_name: str, client_version: str) -> dict[str, Any]:
        result = await self.request(
            "initialize",
            {"clientInfo": {"name": client_name, "version": client_version}},
        )
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
        return await self._notifications.get()

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
                if "id" in payload and ("result" in payload or "error" in payload):
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
                    await self._notifications.put(Notification.model_validate(payload).model_dump())
        finally:
            error = RuntimeError("app server exited")
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(error)

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
