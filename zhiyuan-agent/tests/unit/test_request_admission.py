import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import WebSocketDisconnect

from app.gateway.access import TicketIdentity
from app.gateway.session_runtime import ACCEPTED, BUSY, CONFLICT, DUPLICATE, SessionRuntime
from app.gateway.ui_events import SessionKey


class RequestStore:
    def __init__(self):
        self.requests = {}
        self.results = {}

    async def admit(self, key, request_id, digest):
        await asyncio.sleep(0)
        request_key = (key, request_id)
        if request_key in self.requests:
            return DUPLICATE if self.requests[request_key] == digest else CONFLICT
        self.requests[request_key] = digest
        return ACCEPTED

    async def finish_request(self, key, request_id, result):
        self.results[key, request_id] = result

    async def request_result(self, key, request_id):
        return self.results.get((key, request_id))


async def settle(runtime, key):
    task = runtime._tasks.get(key)
    if task is not None:
        await asyncio.gather(task, return_exceptions=True)
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_busy_request_can_be_retried_after_the_active_turn_finishes():
    store = RequestStore()
    runtime = SessionRuntime(store=store)
    key = SessionKey(tenant_id="1", session_id="42")
    gate = asyncio.Event()
    work = AsyncMock()
    assert await runtime.submit(key, client_request_id="first", ui_turn_id="one", work=gate.wait) == ACCEPTED
    assert await runtime.submit(key, client_request_id="retry", ui_turn_id="two", work=work) == BUSY
    assert (key, "retry") not in store.requests
    gate.set()
    await settle(runtime, key)
    assert await runtime.submit(key, client_request_id="retry", ui_turn_id="two", work=work) == ACCEPTED
    await settle(runtime, key)
    work.assert_awaited_once()


@pytest.mark.asyncio
async def test_concurrent_admission_reserves_only_one_request_and_reclaims_gates():
    store = RequestStore()
    runtime = SessionRuntime(store=store)
    key = SessionKey(tenant_id="1", session_id="42")
    gate = asyncio.Event()
    verdicts = await asyncio.gather(*(
        runtime.submit(key, client_request_id=f"req-{index}", ui_turn_id=f"turn-{index}", work=gate.wait)
        for index in range(10)
    ))
    assert verdicts.count(ACCEPTED) == 1
    assert verdicts.count(BUSY) == 9
    assert len(store.requests) == 1
    assert not runtime._admission_gates
    gate.set()
    await settle(runtime, key)


@pytest.mark.asyncio
async def test_same_content_new_turn_is_duplicate_but_changed_content_conflicts():
    runtime = SessionRuntime(store=RequestStore())
    key = SessionKey(tenant_id="1", session_id="42")
    work = AsyncMock()
    assert await runtime.submit(key, client_request_id="req", ui_turn_id="one", request_digest="same", work=work) == ACCEPTED
    await settle(runtime, key)
    assert await runtime.submit(key, client_request_id="req", ui_turn_id="two", request_digest="same", work=work) == DUPLICATE
    assert await runtime.submit(key, client_request_id="req", ui_turn_id="one", request_digest="different", work=work) == CONFLICT
    work.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["completed", "failed", "interrupted"])
async def test_request_status_survives_runtime_reconstruction(outcome):
    store = RequestStore()
    runtime = SessionRuntime(store=store)
    key = SessionKey(tenant_id="1", session_id="42")

    async def work():
        if outcome == "failed":
            raise RuntimeError("failure")
        if outcome == "interrupted":
            raise asyncio.CancelledError()

    assert await runtime.submit(key, client_request_id="req", ui_turn_id="original", work=work) == ACCEPTED
    await settle(runtime, key)
    restarted = SessionRuntime(store=store)
    assert await restarted.request_status(key, "req") == {"status": outcome, "turnId": "original"}
    assert await restarted.submit(key, client_request_id="req", ui_turn_id="original", work=work) == DUPLICATE


@pytest.mark.asyncio
async def test_unfinished_request_after_restart_requires_recovery_not_execution():
    store = RequestStore()
    key = SessionKey(tenant_id="1", session_id="42")
    await store.admit(key, "req", "digest")
    restarted = SessionRuntime(store=store)
    work = AsyncMock()
    assert await restarted.submit(key, client_request_id="req", ui_turn_id="new", request_digest="digest", work=work) == DUPLICATE
    assert await restarted.request_status(key, "req") == {"status": "recovery_required"}
    work.assert_not_awaited()


@pytest.mark.asyncio
async def test_persisted_running_status_without_a_local_worker_requires_recovery():
    store = RequestStore()
    key = SessionKey(tenant_id="1", session_id="42")
    await store.admit(key, "req", "digest")
    await store.finish_request(key, "req", json.dumps({"status": "running", "turnId": "old"}))
    restarted = SessionRuntime(store=store)
    assert await restarted.request_status(key, "req") == {"status": "recovery_required", "turnId": "old"}


@pytest.mark.asyncio
async def test_cancelled_admission_waiter_does_not_leak_a_session_gate():
    store = RequestStore()
    gate = asyncio.Event()
    original_admit = store.admit

    async def slow_admit(*args):
        await gate.wait()
        return await original_admit(*args)

    store.admit = slow_admit
    runtime = SessionRuntime(store=store)
    key = SessionKey(tenant_id="1", session_id="42")
    first = asyncio.create_task(runtime.submit(key, client_request_id="one", ui_turn_id="one", work=AsyncMock()))
    await asyncio.sleep(0)
    waiter = asyncio.create_task(runtime.submit(key, client_request_id="two", ui_turn_id="two", work=AsyncMock()))
    await asyncio.sleep(0)
    waiter.cancel()
    await asyncio.gather(waiter, return_exceptions=True)
    gate.set()
    assert await first == ACCEPTED
    await settle(runtime, key)
    assert not runtime._admission_gates


def test_content_digest_ignores_turn_metadata_but_includes_actions_and_identity():
    from app.gateway.session_runtime import request_content_digest

    base = {"message_type": "chat", "user_id": "7", "content": "hello", "action": {"b": 2, "a": 1}}
    digest = request_content_digest(**base)
    assert digest == request_content_digest(**dict(base, action={"a": 1, "b": 2}))
    for field, value in [("message_type", "intentSelect"), ("user_id", "8"), ("content", "other"), ("action", None)]:
        assert digest != request_content_digest(**dict(base, **{field: value}))


class RequestSocket:
    def __init__(self, payload):
        self.payload = payload
        self.received = False
        self.state = SimpleNamespace(identity=TicketIdentity(tenant_id="1", session_id="42", user_id="7"))
        self.app = SimpleNamespace(state=SimpleNamespace(gateway_tenant_id="1"))

    async def receive_json(self):
        if self.received:
            raise WebSocketDisconnect()
        self.received = True
        return self.payload


class RequestChannel:
    uses_v1 = False

    def __init__(self):
        self.frames = []
        self.events = []

    def bind_session(self, key):
        pass

    def bind_turn(self, turn_id):
        pass

    async def emit_frame(self, frame):
        self.frames.append(frame)

    async def emit(self, event):
        self.events.append(event)


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["native", "compat"])
async def test_duplicate_receives_explicit_original_request_status(route):
    from app.server import _compat_gateway_loop, _native_gateway_loop

    runtime = SimpleNamespace(
        attach_connection=lambda *args: None,
        submit=AsyncMock(return_value=DUPLICATE),
        request_status=AsyncMock(return_value={"status": "completed", "turnId": "original"}),
    )
    socket = RequestSocket({"content": "hello", "clientRequestId": "req", "turnId": "retry"})
    channel = RequestChannel()
    gateway = SimpleNamespace(handle_turn=AsyncMock())
    if route == "native":
        await _native_gateway_loop(socket, gateway, runtime, channel)
    else:
        await _compat_gateway_loop(socket, gateway, "1", runtime, channel)
    assert channel.frames
    payload = json.loads(channel.frames[0]["content"])
    assert payload["code"] == "duplicate_request"
    assert payload["status"] == "completed"
    assert payload["originalTurnId"] == "original"
    assert payload["clientRequestId"] == "req"
    assert runtime.submit.call_args.kwargs.get("request_digest")
    gateway.handle_turn.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["native", "compat"])
async def test_rejected_followup_cannot_replace_accepted_work_or_its_event_turn(route, monkeypatch):
    from app.server import _compat_gateway_loop, _native_gateway_loop

    payloads = iter([
        {"content": "accepted", "clientRequestId": "first", "turnId": "original"},
        {"content": "rejected", "clientRequestId": "second", "turnId": "busy"},
    ])
    socket = RequestSocket({})

    async def receive():
        try:
            return next(payloads)
        except StopIteration:
            raise WebSocketDisconnect()

    socket.receive_json = receive
    pending = []

    async def submit(key, **kwargs):
        if pending:
            return BUSY
        pending.append(kwargs["work"])
        return ACCEPTED

    runtime = SimpleNamespace(
        attach_connection=lambda *args: None, submit=submit,
        publish=AsyncMock(return_value=False), current_channel=lambda key: None,
    )
    channel = RequestChannel()
    monkeypatch.setattr("app.server._maybe_continue_after_action", AsyncMock())
    monkeypatch.setattr("app.server._maybe_continue_after_preview", AsyncMock())
    monkeypatch.setattr("app.server._emit_turn_terminal", AsyncMock())
    if route == "native":
        runner = AsyncMock(return_value={"reply": "done"})
        monkeypatch.setattr("app.server._run_native_turn", runner)
        await _native_gateway_loop(socket, SimpleNamespace(), runtime, channel)
        await pending[0]()
        assert runner.call_args.args[1].content == "accepted"
        assert runner.call_args.args[3] == "original"
        assert channel.events[0]["turnId"] == "original"
    else:
        runner = AsyncMock(return_value={"reply": "done"})
        monkeypatch.setattr("app.server._run_compat_turn", runner)
        await _compat_gateway_loop(socket, SimpleNamespace(), "1", runtime, channel)
        await pending[0]()
        assert runner.call_args.args[5] == "original"
        assert runner.call_args.args[6] == "accepted"


@pytest.mark.asyncio
async def test_application_startup_wires_the_event_store_into_admission(monkeypatch):
    from fastapi import FastAPI
    from app.server import lifespan

    store = RequestStore()
    gateway = SimpleNamespace(interrupt_codex_turn=AsyncMock(), steer_codex_turn=AsyncMock())
    gateway_runtime = SimpleNamespace(gateway=gateway, close=AsyncMock())
    monkeypatch.setattr("app.server.configure_logfire", lambda: None)
    monkeypatch.setattr("app.server.GatewayConfig", lambda: SimpleNamespace(mode="codex_readonly"))
    monkeypatch.setattr("app.server.CodexAppServerConfig", lambda: SimpleNamespace(binding_ttl_seconds=900, binding_registry_path=""))
    monkeypatch.setattr("app.server._build_legacy_chat_service", lambda mode: None)
    monkeypatch.setattr("app.server._build_event_store", lambda: store)
    monkeypatch.setattr("app.server.build_gateway_runtime", AsyncMock(return_value=gateway_runtime))
    monkeypatch.setattr("app.server.bind_session_runtime", lambda runtime: None)
    application = FastAPI()
    async with lifespan(application):
        assert application.state.session_runtime._store is store
        assert gateway.session_runtime is application.state.session_runtime
    gateway_runtime.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_compat_progress_keeps_original_turn_after_channel_rebinding():
    from app.server import _run_compat_turn

    async def handle_turn(**kwargs):
        await kwargs["emit"]({"type": "tool.progress", "payload": {}})
        return {"reply": "done"}

    gateway = SimpleNamespace(handle_turn=handle_turn)
    channel = RequestChannel()
    channel.bind_turn("unrelated")
    await _run_compat_turn(gateway, None, "1", "42", "7", "original", "hello", channel=channel)
    assert channel.events[0].get("turnId") == "original"


@pytest.mark.asyncio
@pytest.mark.parametrize("detached", [False, True])
@pytest.mark.parametrize("result,expected", [
    ({"error": "output_schema_invalid"}, "failed"),
    ({"error": "turn_interrupted"}, "interrupted"),
    ({"output": {"executionStatus": "failed"}}, "failed"),
    ({"output": {"executionStatus": "interrupted"}}, "interrupted"),
    ({"output": {"executionStatus": "completed"}, "actionResult": {"actionStatus": "failed"}}, "failed"),
    ({"actionResult": {"actionStatus": "applied"}}, "completed"),
    ({"actionResult": {"actionStatus": "cancelled"}}, "completed"),
    ({"output": {"executionStatus": "completed"}}, "completed"),
    (None, "completed"),
])
async def test_returned_outcome_sets_the_receipt_for_normal_and_detached_work(detached, result, expected):
    store = RequestStore()
    runtime = SessionRuntime(store=store)
    key = SessionKey(tenant_id="1", session_id="42")

    async def action():
        return result

    async def work():
        if detached:
            return runtime.detach_work(
                key, action, label="test_action", client_request_id="req", ui_turn_id="original",
            )
        return await action()

    assert await runtime.submit(key, client_request_id="req", ui_turn_id="original", work=work) == ACCEPTED
    await settle(runtime, key)
    await asyncio.gather(*runtime._detached, return_exceptions=True)
    await asyncio.sleep(0)

    assert await runtime.request_status(key, "req") == {"status": expected, "turnId": "original"}
    assert await SessionRuntime(store=store).request_status(key, "req") == {"status": expected, "turnId": "original"}
    assert not runtime._pending_requests
    assert not runtime._detached


@pytest.mark.asyncio
async def test_blocked_detached_action_stays_running_without_holding_the_active_turn():
    store = RequestStore()
    runtime = SessionRuntime(store=store)
    key = SessionKey(tenant_id="1", session_id="42")
    release = asyncio.Event()

    async def action():
        await release.wait()
        return {"actionResult": {"actionStatus": "failed"}}

    async def dispatch():
        return runtime.detach_work(
            key, action, label="test_action", client_request_id="req", ui_turn_id="original",
        )

    assert await runtime.submit(key, client_request_id="req", ui_turn_id="original", request_digest="digest", work=dispatch) == ACCEPTED
    dispatcher = runtime._tasks[key]
    try:
        await settle(runtime, key)
        from app.gateway.session_runtime import DeferredRequest

        assert isinstance(dispatcher.result(), DeferredRequest)
        assert runtime.active_turn(key) is None
        assert await runtime.interrupt(key, "original") == {"status": "no_active_turn"}
        assert await runtime.request_status(key, "req") == {"status": "running", "turnId": "original"}
        assert json.loads(store.results[key, "req"]) == {"status": "running", "turnId": "original"}
        restarted = SessionRuntime(store=store)
        assert await restarted.request_status(key, "req") == {"status": "recovery_required", "turnId": "original"}
        duplicate_work = AsyncMock()
        assert await restarted.submit(key, client_request_id="req", ui_turn_id="retry", request_digest="digest", work=duplicate_work) == DUPLICATE
        duplicate_work.assert_not_awaited()
        assert await runtime.submit(key, client_request_id="req", ui_turn_id="retry", request_digest="digest", work=duplicate_work) == DUPLICATE
        assert await runtime.submit(key, client_request_id="req", ui_turn_id="retry", request_digest="changed", work=duplicate_work) == CONFLICT
        assert await runtime.submit(key, client_request_id="another", ui_turn_id="another", work=AsyncMock()) == ACCEPTED
        await settle(runtime, key)
        await runtime.cancel_all()
        assert runtime._detached
        assert await runtime.request_status(key, "req") == {"status": "running", "turnId": "original"}
    finally:
        release.set()
        await asyncio.gather(*runtime._detached, return_exceptions=True)
        await asyncio.sleep(0)

    assert await runtime.request_status(key, "req") == {"status": "failed", "turnId": "original"}
    assert await restarted.request_status(key, "req") == {"status": "failed", "turnId": "original"}
    assert not runtime._pending_requests
    assert not runtime._admission_gates
    assert not runtime._tasks
    assert not runtime._active


@pytest.mark.asyncio
async def test_detached_pending_request_is_deduplicated_without_a_store():
    runtime = SessionRuntime()
    key = SessionKey(tenant_id="1", session_id="42")
    release = asyncio.Event()

    async def dispatch():
        return runtime.detach_work(
            key, release.wait, label="test_action", client_request_id="req", ui_turn_id="original",
        )

    assert await runtime.submit(key, client_request_id="req", ui_turn_id="original", request_digest="digest", work=dispatch) == ACCEPTED
    try:
        await settle(runtime, key)
        assert await runtime.request_status(key, "req") == {"status": "running", "turnId": "original"}
        assert await runtime.submit(key, client_request_id="req", ui_turn_id="retry", request_digest="digest", work=AsyncMock()) == DUPLICATE
        assert await runtime.submit(key, client_request_id="req", ui_turn_id="retry", request_digest="changed", work=AsyncMock()) == CONFLICT
    finally:
        release.set()
        await asyncio.gather(*runtime._detached, return_exceptions=True)
        await asyncio.sleep(0)

    assert not runtime._pending_requests


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["failed", "interrupted"])
async def test_detached_raised_outcome_is_persisted_and_cleanup_is_complete(outcome):
    store = RequestStore()
    runtime = SessionRuntime(store=store)
    key = SessionKey(tenant_id="1", session_id="42")
    release = asyncio.Event()

    async def action():
        await release.wait()
        if outcome == "interrupted":
            raise asyncio.CancelledError()
        raise RuntimeError("detached action failed")

    async def dispatch():
        return runtime.detach_work(
            key, action, label="test_action", client_request_id="req", ui_turn_id="original",
        )

    await runtime.submit(key, client_request_id="req", ui_turn_id="original", work=dispatch)
    await settle(runtime, key)
    release.set()
    await asyncio.gather(*runtime._detached, return_exceptions=True)
    await asyncio.sleep(0)

    assert await SessionRuntime(store=store).request_status(key, "req") == {"status": outcome, "turnId": "original"}
    assert not runtime._pending_requests
    assert not runtime._detached


@pytest.mark.asyncio
async def test_dispatcher_does_not_overwrite_a_detached_result_that_finished_first():
    store = RequestStore()
    runtime = SessionRuntime(store=store)
    key = SessionKey(tenant_id="1", session_id="42")

    async def action():
        return {"error": "action_execution_exception"}

    async def dispatch():
        deferred = runtime.detach_work(
            key, action, label="test_action", client_request_id="req", ui_turn_id="original",
        )
        await asyncio.gather(*runtime._detached)
        assert await runtime.request_status(key, "req") == {"status": "failed", "turnId": "original"}
        return deferred

    await runtime.submit(key, client_request_id="req", ui_turn_id="original", work=dispatch)
    dispatcher = runtime._tasks[key]
    await settle(runtime, key)

    assert dispatcher.exception() is None
    assert await runtime.request_status(key, "req") == {"status": "failed", "turnId": "original"}
    assert not runtime._pending_requests


@pytest.mark.asyncio
@pytest.mark.parametrize("detached", [False, True])
async def test_receipt_persistence_failure_reclaims_local_metadata_and_requires_recovery(detached):
    store = RequestStore()
    finish_request = store.finish_request

    async def fail_terminal_write(key, request_id, result):
        if json.loads(result)["status"] != "running":
            raise RuntimeError("receipt storage unavailable")
        await finish_request(key, request_id, result)

    store.finish_request = fail_terminal_write
    runtime = SessionRuntime(store=store)
    key = SessionKey(tenant_id="1", session_id="42")

    async def work():
        if detached:
            return runtime.detach_work(
                key, AsyncMock(return_value={"reply": "done"}), label="test_action",
                client_request_id="req", ui_turn_id="original",
            )
        return {"reply": "done"}

    await runtime.submit(key, client_request_id="req", ui_turn_id="original", work=work)
    await settle(runtime, key)
    await asyncio.gather(*runtime._detached, return_exceptions=True)
    await asyncio.sleep(0)

    assert not runtime._pending_requests
    assert not runtime._detached
    assert runtime.active_turn(key) is None
    assert await runtime.request_status(key, "req") == {"status": "recovery_required", "turnId": "original"}


@pytest.mark.asyncio
async def test_cancelling_worker_before_it_starts_reclaims_pending_metadata():
    store = RequestStore()
    runtime = SessionRuntime(store=store)
    key = SessionKey(tenant_id="1", session_id="42")
    work = AsyncMock()

    await runtime.submit(key, client_request_id="req", ui_turn_id="original", work=work)
    await runtime.cancel_all()
    await asyncio.sleep(0)

    work.assert_not_awaited()
    assert not runtime._pending_requests
    assert not runtime._tasks
    assert not runtime._active
    assert (await runtime.request_status(key, "req"))["status"] != "running"


@pytest.fixture
def receipt_server(monkeypatch):
    terminal = AsyncMock()
    monkeypatch.setattr("app.server._emit_turn_terminal", terminal)
    monkeypatch.setattr("app.server._maybe_continue_after_action", AsyncMock())
    monkeypatch.setattr("app.server._maybe_continue_after_preview", AsyncMock())
    return terminal


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["native", "compat"])
@pytest.mark.parametrize("result, status", [
    ({"error": "gateway_failure"}, "failed"),
    ({"output": {"executionStatus": "failed"}}, "failed"),
    ({"error": "turn_interrupted"}, "interrupted"),
    ({"output": {"executionStatus": "interrupted"}}, "interrupted"),
    ({"actionResult": {"actionStatus": "failed"}}, "failed"),
    ({"reply": "done"}, "completed"),
])
async def test_real_gateway_workers_persist_returned_outcomes(route, result, status, receipt_server):
    from app.server import _compat_gateway_loop, _native_gateway_loop

    store = RequestStore()
    runtime = SessionRuntime(store=store)
    key = SessionKey(tenant_id="1", session_id="42")
    gateway = SimpleNamespace(handle_turn=AsyncMock(return_value=result))
    socket = RequestSocket({"content": "hello", "clientRequestId": "req", "turnId": "original"})
    channel = RequestChannel()
    try:
        if route == "native":
            await _native_gateway_loop(socket, gateway, runtime, channel)
        else:
            await _compat_gateway_loop(socket, gateway, "1", runtime, channel)
        worker = runtime._tasks[key]
        await settle(runtime, key)

        assert worker.exception() is None
        gateway.handle_turn.assert_awaited_once()
        assert gateway.handle_turn.await_args.kwargs["content"] == "hello"
        assert gateway.handle_turn.await_args.kwargs["turn_id"] == "original"
        assert await runtime.request_status(key, "req") == {"status": status, "turnId": "original"}
        assert await SessionRuntime(store=store).request_status(key, "req") == {"status": status, "turnId": "original"}
        assert runtime.active_turn(key) is None
        assert not runtime._pending_requests
        if route == "native":
            assert receipt_server.await_args.kwargs["result"] == result
        else:
            assert channel.frames[-1]["end"] is True
    finally:
        await runtime.cancel_all()


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["native", "compat"])
async def test_real_gateway_workers_persist_swallowed_exceptions_as_failed(route, receipt_server):
    from app.server import _compat_gateway_loop, _native_gateway_loop

    store = RequestStore()
    runtime = SessionRuntime(store=store)
    key = SessionKey(tenant_id="1", session_id="42")
    gateway = SimpleNamespace(handle_turn=AsyncMock(side_effect=RuntimeError("gateway unavailable")))
    socket = RequestSocket({"content": "hello", "clientRequestId": "req", "turnId": "original"})
    channel = RequestChannel()
    try:
        if route == "native":
            await _native_gateway_loop(socket, gateway, runtime, channel)
        else:
            await _compat_gateway_loop(socket, gateway, "1", runtime, channel)
        worker = runtime._tasks[key]
        await settle(runtime, key)

        assert worker.exception() is None
        gateway.handle_turn.assert_awaited_once()
        assert await SessionRuntime(store=store).request_status(key, "req") == {"status": "failed", "turnId": "original"}
        assert not runtime._pending_requests
        assert runtime.active_turn(key) is None
        if route == "native":
            assert receipt_server.await_args.kwargs["result"]["error"] == "gateway_failure"
        else:
            assert channel.frames[-1]["type"] == "error"
            assert channel.frames[-1]["end"] is True
    finally:
        await runtime.cancel_all()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome, status", [
    ("action_failed", "failed"),
    ("action_applied", "completed"),
    ("interrupted", "interrupted"),
    ("gateway_exception", "failed"),
    ("terminal_exception", "failed"),
])
async def test_real_gateway_detached_action_receipt_tracks_blocked_work(outcome, status, receipt_server):
    from app.server import _native_gateway_loop

    store = RequestStore()
    runtime = SessionRuntime(store=store)
    key = SessionKey(tenant_id="1", session_id="42")
    started = asyncio.Event()
    release = asyncio.Event()
    if outcome == "terminal_exception":
        receipt_server.side_effect = RuntimeError("terminal unavailable")

    async def execute_action(**kwargs):
        started.set()
        await release.wait()
        if outcome == "gateway_exception":
            raise RuntimeError("action unavailable")
        if outcome == "interrupted":
            return {"error": "turn_interrupted"}
        return {"actionResult": {
            "actionStatus": "failed" if outcome == "action_failed" else "applied",
            "proposalRef": "pending-1",
        }}

    gateway = SimpleNamespace(
        get_authoritative_snapshot=AsyncMock(return_value={"snapshotVersion": 0}),
        execute_action_and_refresh=AsyncMock(side_effect=execute_action),
    )
    action = {
        "actionType": "confirm_proposal", "proposalRef": "pending-1",
        "expectedSourceVersion": 0, "intent": "explicit",
    }
    socket = RequestSocket({
        "type": "pendingConfirmation", "inputType": "pendingConfirmation", "content": "",
        "conversationAction": action, "clientRequestId": "req", "turnId": "original",
    })
    channel = RequestChannel()
    try:
        await _native_gateway_loop(socket, gateway, runtime, channel)
        await settle(runtime, key)
        await asyncio.wait_for(started.wait(), timeout=1)

        gateway.execute_action_and_refresh.assert_awaited_once()
        assert gateway.execute_action_and_refresh.await_args.kwargs["action"] == action
        assert runtime.active_turn(key) is None
        assert not runtime._tasks
        assert await runtime.interrupt(key, "original") == {"status": "no_active_turn"}
        assert await runtime.request_status(key, "req") == {"status": "running", "turnId": "original"}
        assert json.loads(store.results[key, "req"]) == {"status": "running", "turnId": "original"}
        restarted = SessionRuntime(store=store)
        assert await restarted.request_status(key, "req") == {"status": "recovery_required", "turnId": "original"}
        await runtime.cancel_all()
        assert len(runtime._detached) == 1
        assert await runtime.request_status(key, "req") == {"status": "running", "turnId": "original"}
        detached = tuple(runtime._detached)
        release.set()
        await asyncio.gather(*detached)
        await asyncio.sleep(0)

        assert await runtime.request_status(key, "req") == {"status": status, "turnId": "original"}
        assert await restarted.request_status(key, "req") == {"status": status, "turnId": "original"}
        if outcome == "terminal_exception":
            assert detached[0].result() == {"error": "action_execution_exception"}
        assert not runtime._pending_requests
        assert not runtime._detached
        assert not runtime._admission_gates
    finally:
        release.set()
        await settle(runtime, key)
        await asyncio.gather(*runtime._detached, return_exceptions=True)
        await runtime.cancel_all()
