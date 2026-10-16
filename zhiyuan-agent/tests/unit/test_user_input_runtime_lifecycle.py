from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.gateway.ui_events import SessionKey
from app.gateway.user_input import UserInputBroker
from app.harness.client import AppServerClient, AppServerExited
from app.harness.codex import CodexAppServerHarness


FAKE_SERVER = Path(__file__).resolve().parents[1] / "fixtures" / "codex" / "fake_app_server.py"
KEY = SessionKey("tenant-1", "session-1")
TERMINAL = {
    "method": "turn/completed",
    "params": {"threadId": "thread-1", "turn": {"id": "native-turn-1", "status": "interrupted"}},
}


def matches_terminal(notification):
    return notification.get("method") == "turn/completed"


@pytest.mark.asyncio
async def test_notification_observer_does_not_consume_collector_terminal():
    client = AppServerClient([])
    with client.observe_notification(matches_terminal) as observed:
        client._route_notification(TERMINAL)
        assert await observed == TERMINAL

    assert await client.wait_for_notification(matches_terminal, timeout=1) == TERMINAL
    assert client._notification_observers == []


@pytest.mark.asyncio
async def test_observer_and_registered_collector_both_receive_terminal():
    client = AppServerClient([])
    collector = asyncio.create_task(client.wait_for_notification(matches_terminal, timeout=1))
    await asyncio.sleep(0)
    with client.observe_notification(matches_terminal) as observed:
        client._route_notification(TERMINAL)
        assert await observed == TERMINAL
        assert await collector == TERMINAL
    assert client._notification_observers == []
    assert client._notification_backlog == []


@pytest.mark.asyncio
async def test_old_reader_cannot_route_response_or_expire_new_generation():
    client = AppServerClient([])
    stream = asyncio.StreamReader()
    client.process = SimpleNamespace(stdout=stream)
    client.runtime_generation = "old-generation"
    old_reader = asyncio.create_task(client._read_stdout())
    await asyncio.sleep(0)
    client.process = SimpleNamespace(stdout=asyncio.StreamReader())
    client.runtime_generation = "new-generation"
    new_response = asyncio.get_running_loop().create_future()
    client._pending[1] = new_response
    try:
        stream.feed_data(b'{"id":1,"result":{"source":"old-process"}}\n')
        stream.feed_eof()
        await old_reader
        assert not new_response.done()
        assert client._ended_generation != "new-generation"
    finally:
        new_response.cancel()
        old_reader.cancel()
        await asyncio.gather(old_reader, return_exceptions=True)


@pytest.mark.asyncio
async def test_observer_is_released_when_its_scope_is_cancelled():
    client = AppServerClient([])
    entered = asyncio.Event()

    async def watch():
        with client.observe_notification(matches_terminal) as observed:
            entered.set()
            await observed

    watcher = asyncio.create_task(watch())
    await asyncio.wait_for(entered.wait(), timeout=1)
    watcher.cancel()
    with pytest.raises(asyncio.CancelledError):
        await watcher
    assert client._notification_observers == []


@pytest.mark.asyncio
async def test_process_start_restart_and_exit_report_distinct_generations():
    started = []
    exited = []
    client = AppServerClient([sys.executable, str(FAKE_SERVER)])
    client.set_runtime_handlers(on_started=started.append, on_exited=exited.append)
    try:
        await client.start()
        first = client.runtime_generation
        await client.restart()
        second = client.runtime_generation
        assert first != second
        assert started == [first, second]
        assert exited == [first]
    finally:
        await client.close()
    assert exited == [first, second]


@pytest.mark.asyncio
async def test_runtime_exit_wakes_non_consuming_observer():
    client = AppServerClient([sys.executable, str(FAKE_SERVER)])
    await client.start()
    try:
        with client.observe_notification(matches_terminal) as observed:
            client.process.terminate()
            with pytest.raises(AppServerExited):
                await asyncio.wait_for(observed, timeout=2)
        assert client._notification_observers == []
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_native_card_is_invalidated_by_real_client_restart_without_manual_expire():
    broker = UserInputBroker(runtime_generation="before-start", scope_resolver=lambda thread_id: KEY)
    cards = asyncio.Queue()

    async def emit(key, event):
        cards.put_nowait(event["payload"]["requestId"])

    broker.set_emitter(emit)
    client = AppServerClient([sys.executable, str(FAKE_SERVER)], server_request_handler=broker.handle_server_request)
    client.set_runtime_handlers(
        on_started=broker.start_runtime, on_exited=broker.expire_runtime,
        on_notification=broker.handle_notification,
    )
    try:
        await client.start()
        await client.request("test/request_user_input", {"threadId": "thread-1"})
        old_id = await asyncio.wait_for(cards.get(), timeout=2)
        first_generation = client.runtime_generation
        await client.restart()

        assert broker.snapshot(KEY) == []
        assert broker._pending == broker._by_rpc == {}
        assert broker.runtime_generation == client.runtime_generation != first_generation
        assert await broker.answer(KEY, old_id, {}) == {"status": "unknown_request"}

        await client.request("test/request_user_input", {"threadId": "thread-1"})
        current_id = await asyncio.wait_for(cards.get(), timeout=2)
        broker.handle_notification(first_generation, {
            "method": "serverRequest/resolved", "params": {"threadId": "thread-1", "requestId": 9001},
        })
        assert broker.snapshot(KEY)[0]["requestId"] == current_id
        client._route_notification({
            "method": "serverRequest/resolved", "params": {"threadId": "thread-1", "requestId": 9001},
        })
        assert broker.snapshot(KEY) == []
        assert broker._by_rpc == {}
    finally:
        await client.close()
    assert broker._pending == broker._by_rpc == {}
    assert client._server_request_tasks == set()


@pytest.mark.asyncio
@pytest.mark.parametrize("raise_error", [False, True])
async def test_late_handler_cannot_write_result_or_error_into_new_generation(raise_error):
    entered = asyncio.Event()
    release = asyncio.Event()

    async def handler(request):
        entered.set()
        await release.wait()
        if raise_error:
            raise RuntimeError("old request failed")
        return {"answered": True}

    client = AppServerClient([], server_request_handler=handler)
    client.runtime_generation = "old-generation"
    writes = []

    async def write(payload):
        writes.append(payload)

    client._write = write
    task = asyncio.create_task(client._handle_server_request(
        {"id": 1, "method": "synthetic/request"}, runtime_generation="old-generation",
    ))
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        client.runtime_generation = "new-generation"
        release.set()
        await task
        assert writes == []
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_queued_old_request_never_enters_broker_in_new_generation():
    handled = []

    async def handler(request):
        handled.append(request)

    client = AppServerClient([], server_request_handler=handler)
    client.runtime_generation = "new-generation"
    await client._handle_server_request({"id": 1, "method": "synthetic/request"}, runtime_generation="old-generation")
    assert handled == []


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_params", [
    {"threadId": "thread-1", "turn": {"id": "native-turn-1", "status": "interrupted"}},
    {"threadId": "thread-1", "turnId": "native-turn-1"},
    {"thread_id": "thread-1", "turn_id": "native-turn-1"},
])
async def test_interrupt_waits_for_terminal_without_stealing_it_from_collector(terminal_params):
    harness = CodexAppServerHarness([], request_timeout=1)
    interrupted = asyncio.Event()
    release = asyncio.Event()
    notification = {"method": "turn/completed", "params": terminal_params}

    async def interrupt(thread_id, turn_id):
        assert (thread_id, turn_id) == ("thread-1", "native-turn-1")
        interrupted.set()
        await release.wait()
        harness.client._route_notification(notification)
        return {}

    harness.interrupt_turn = interrupt
    task = asyncio.create_task(harness.interrupt_turn_and_wait("thread-1", "native-turn-1"))
    try:
        await asyncio.wait_for(interrupted.wait(), timeout=1)
        assert not task.done()
        release.set()
        await task
        assert await harness.client.wait_for_notification(matches_terminal, timeout=1) == notification
        assert harness.client._notification_observers == []
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_interrupt_observer_ignores_another_thread_or_turn():
    harness = CodexAppServerHarness([], request_timeout=1)
    sent = asyncio.Event()

    async def interrupt(thread_id, turn_id):
        harness.client._route_notification({
            "method": "turn/completed",
            "params": {"threadId": "other-thread", "turn": {"id": turn_id, "status": "interrupted"}},
        })
        harness.client._route_notification({
            "method": "turn/completed",
            "params": {"threadId": thread_id, "turn": {"id": "other-turn", "status": "interrupted"}},
        })
        sent.set()

    harness.interrupt_turn = interrupt
    task = asyncio.create_task(harness.interrupt_turn_and_wait("thread-1", "native-turn-1"))
    try:
        await asyncio.wait_for(sent.wait(), timeout=1)
        assert not task.done()
        harness.client._route_notification(TERMINAL)
        await task
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_interrupt_failure_and_terminal_timeout_release_observer():
    harness = CodexAppServerHarness([], request_timeout=0.01)

    async def unavailable(thread_id, turn_id):
        raise RuntimeError("interrupt unavailable")

    harness.interrupt_turn = unavailable
    with pytest.raises(RuntimeError, match="interrupt unavailable"):
        await harness.interrupt_turn_and_wait("thread-1", "native-turn-1")
    assert harness.client._notification_observers == []

    async def no_terminal(thread_id, turn_id):
        return {}

    harness.interrupt_turn = no_terminal
    with pytest.raises(asyncio.TimeoutError):
        await harness.interrupt_turn_and_wait("thread-1", "native-turn-1")
    assert harness.client._notification_observers == []
