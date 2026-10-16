import asyncio
from types import SimpleNamespace

import pytest

from app.gateway.session_lifecycle import SessionLifecycle
from app.gateway.ui_events import SessionKey
from app.harness.client import AppServerClient


KEY = SessionKey("tenant-1", "session-1")
REQUEST = b'{"id":1,"method":"question","params":{}}\n'


def make_client(lifecycle):
    async def handler(payload):
        return {"answer": "ok"}

    client = AppServerClient([], server_request_handler=handler)
    client.server_request_lease_factory = lambda payload: lifecycle.acquire(KEY, "native_request")
    stream = asyncio.StreamReader()
    client.process = SimpleNamespace(stdout=stream)
    return client, stream


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_reader_acquires_before_schedule_and_releases_failed_or_prestart_cancelled_task(monkeypatch, failure):
    lifecycle = SessionLifecycle()
    client, stream = make_client(lifecycle)
    create = asyncio.create_task
    reader = create(client._read_stdout())
    scheduled = asyncio.Event()
    coroutines = []
    tasks = []

    def schedule(coroutine):
        assert lifecycle.inspect(KEY).owners == {"native_request": 1}
        coroutines.append(coroutine)
        scheduled.set()
        if failure:
            raise RuntimeError("cannot schedule")
        task = create(coroutine)
        task.cancel()
        tasks.append(task)
        return task

    monkeypatch.setattr(asyncio, "create_task", schedule)
    stream.feed_data(REQUEST)
    await scheduled.wait()
    if failure:
        with pytest.raises(RuntimeError, match="cannot schedule"):
            await reader
        assert coroutines[0].cr_frame is None
    else:
        await asyncio.gather(*tasks, return_exceptions=True)
        stream.feed_eof()
        await reader
    assert lifecycle.inspect(KEY).total == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["closed", "ended", "old_generation"])
async def test_reader_never_acquires_for_inactive_runtime(state):
    lifecycle = SessionLifecycle()
    client, stream = make_client(lifecycle)
    reader = asyncio.create_task(client._read_stdout())
    await asyncio.sleep(0)
    if state == "closed":
        client._closed = True
    elif state == "ended":
        client._ended_generation = client.runtime_generation
    else:
        client.runtime_generation = "new-generation"
    stream.feed_data(REQUEST)
    stream.feed_eof()
    await reader
    assert lifecycle.inspect(KEY) is None


@pytest.mark.asyncio
async def test_protocol_error_reply_keeps_lease_until_transport_drain():
    lifecycle = SessionLifecycle()
    client, stream = make_client(lifecycle)
    writing = asyncio.Event()
    release = asyncio.Event()
    responses = []

    async def handler(payload):
        raise ValueError("invalid answer")

    async def write(payload):
        responses.append(payload)
        writing.set()
        await release.wait()

    client.server_request_handler = handler
    client._write = write
    reader = asyncio.create_task(client._read_stdout())
    try:
        stream.feed_data(REQUEST)
        await writing.wait()
        assert responses == [{"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "invalid answer"}}]
        assert lifecycle.inspect(KEY).owners == {"native_request": 1}
        task = next(iter(client._server_request_tasks))
        release.set()
        await task
        await asyncio.sleep(0)
        assert lifecycle.inspect(KEY).total == 0
    finally:
        release.set()
        stream.feed_eof()
        await reader
