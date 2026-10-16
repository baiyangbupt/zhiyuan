import asyncio
from dataclasses import FrozenInstanceError, replace

import pytest

from app.gateway.session_lifecycle import SessionLifecycle
from app.gateway.session_reclaim import (
    PendingPresence, SessionReclaimPreflight, classify_pending_response,
)
from app.gateway.ui_events import SessionKey


KEY = SessionKey("1", "101")


def pending_response(initial_status="active", **changes):
    data = {
        "chatSessionId": 101,
        "pendingId": "pending-1",
        "revision": 2,
        "kind": "planning_command",
        "actionFamily": "planning_command",
        "status": initial_status,
        "claimToken": None,
    }
    data.update(changes)
    return {"code": 0, "msg": "success", "data": data}


def test_explicit_successful_null_is_absent_and_observation_is_immutable():
    observation = classify_pending_response(KEY, {"code": 0, "data": None})
    assert observation.presence is PendingPresence.ABSENT
    with pytest.raises(FrozenInstanceError):
        observation.presence = PendingPresence.PRESENT


@pytest.mark.parametrize("status", ["active", "applying"])
def test_live_pending_is_present_even_with_expired_claim(status):
    response = pending_response(status, claimExpireTime=1, claimToken="expired")
    assert classify_pending_response(KEY, response).presence is PendingPresence.PRESENT


@pytest.mark.parametrize("status", ["applied", "cancelled", "expired"])
def test_only_known_terminal_pending_is_absent(status):
    assert classify_pending_response(KEY, pending_response(status)).presence is PendingPresence.ABSENT


@pytest.mark.parametrize("response", [
    None, [], "", {}, {"data": None}, {"code": 0},
    {"code": False, "data": None}, {"code": "0", "data": None},
    {"code": 0.0, "data": None}, {"code": 1, "data": None},
    {"code": 0, "data": None, "error": "unavailable"},
    {"code": 0, "data": None, "errors": ["unavailable"]},
    {"code": 0, "data": None, "success": False},
    {"code": 0, "data": None, "success": 0},
    {"code": 0, "data": None, "failed": True},
    {"code": 0, "data": {}}, {"code": 0, "data": []},
    {"code": 0, "data": False}, {"code": 0, "data": "null"},
])
def test_incomplete_or_failed_envelope_cannot_prove_absence(response):
    assert classify_pending_response(KEY, response).presence is PendingPresence.UNKNOWN


@pytest.mark.parametrize("changes", [
    {"chatSessionId": None}, {"chatSessionId": 102}, {"chatSessionId": True},
    {"chatSessionId": 101.0}, {"tenantId": "2"}, {"tenantId": True},
    {"pendingId": None}, {"pendingId": " "}, {"pendingId": 123},
    {"revision": 0}, {"revision": -1}, {"revision": True},
    {"revision": "2"}, {"revision": 2.0},
    {"status": None}, {"status": "failed"}, {"status": "future_state"},
    {"status": []},
])
def test_untrusted_identity_or_malformed_pending_fails_closed(changes):
    response = pending_response("expired", **changes)
    assert classify_pending_response(KEY, response).presence is PendingPresence.UNKNOWN


@pytest.mark.parametrize("field", ["chatSessionId", "pendingId", "revision", "status"])
def test_missing_pending_fields_are_not_terminal(field):
    response = pending_response("applied")
    del response["data"][field]
    assert classify_pending_response(KEY, response).presence is PendingPresence.UNKNOWN


def test_serialized_long_ids_match_without_retaining_pending_payload():
    response = pending_response("applied", chatSessionId="101", tenantId="1")
    response["data"]["studentProfile"] = "private-student-data"
    observation = classify_pending_response(KEY, response)
    assert observation.presence is PendingPresence.ABSENT
    assert "private-student-data" not in repr(observation)
    assert "pending-1" not in repr(observation)


class PreflightFixture:
    def __init__(self):
        self.now = 10.0
        self.lifecycle = SessionLifecycle(clock=lambda: self.now)
        self.route = False
        self.calls = []
        self.response = {"code": 0, "data": None}
        self.started = asyncio.Event()
        self.resume = asyncio.Event()
        self.pause = False
        self.error = None
        self.preflight = SessionReclaimPreflight(
            self.lifecycle, self.load, self.route_retained, clock=lambda: self.now,
        )

    def make_idle(self, key=KEY):
        self.lifecycle.acquire(key, "turn").close()
        self.now += 20.0
        return self.lifecycle.inspect(key)

    def route_retained(self, key):
        return self.route

    async def load(self, *, tenant_id, session_id):
        self.calls.append((tenant_id, session_id))
        self.started.set()
        if self.pause:
            await self.resume.wait()
        if self.error:
            raise self.error
        return self.response

    async def check(self, key=KEY, *, idle_seconds=10.0, timeout_seconds=1.0):
        return await self.preflight.check(
            key, idle_seconds=idle_seconds, timeout_seconds=timeout_seconds,
        )


async def test_fresh_absence_is_only_diagnostic_and_does_not_refresh_idle():
    fixture = PreflightFixture()
    stamp = fixture.make_idle()
    result = await fixture.check()
    assert result.status == "candidate"
    assert result.reason == "candidate"
    assert result.stamp == stamp
    assert result.pending.presence is PendingPresence.ABSENT
    assert fixture.lifecycle.inspect(KEY) == stamp
    assert fixture.calls == [("1", "101")]
    with pytest.raises(FrozenInstanceError):
        result.status = "blocked"
    fixture.response = pending_response("applying")
    second = await fixture.check()
    assert second.status == "blocked"
    assert second.reason == "pending_present"
    assert fixture.calls == [("1", "101"), ("1", "101")]
    assert fixture.lifecycle.inspect(KEY) == stamp


@pytest.mark.parametrize("condition,reason", [
    ("missing", "no_entry"), ("active", "owners_active"),
    ("recent", "not_idle_enough"), ("retained", "route_retained"),
    ("unknown_runtime", "runtime_unknown"),
])
async def test_ineligible_sessions_never_query_or_create_ownership(condition, reason):
    fixture = PreflightFixture()
    if condition != "missing":
        fixture.make_idle()
    if condition == "active":
        lease = fixture.lifecycle.acquire(KEY, "connection")
    elif condition == "recent":
        fixture.now = 11.0
    elif condition == "retained":
        fixture.route = True
    elif condition == "unknown_runtime":
        fixture.route = None
    before = fixture.lifecycle.inspect(KEY)
    result = await fixture.check()
    assert result.status == "blocked"
    assert result.reason == reason
    assert result.pending is None
    assert not fixture.calls
    assert fixture.lifecycle.inspect(KEY) == before
    if condition == "active":
        lease.close()


@pytest.mark.parametrize("return_to_idle", [False, True])
async def test_activity_during_query_invalidates_even_if_owners_return_to_zero(return_to_idle):
    fixture = PreflightFixture()
    fixture.make_idle()
    fixture.pause = True
    check_task = asyncio.create_task(fixture.check())
    try:
        await fixture.started.wait()
        lease = fixture.lifecycle.acquire(KEY, "native_request")
        assert fixture.lifecycle.inspect(KEY).total == 1
        if return_to_idle:
            lease.close()
        fixture.resume.set()
        result = await check_task
        assert result.status == "blocked"
        assert result.reason == "session_changed"
    finally:
        fixture.resume.set()
        await check_task
        lease.close()


@pytest.mark.parametrize("changes", [
    {"generation": "new-entry"}, {"revision": 999},
    {"owners": {"action": 1}}, {"idle_since": 9.0},
    {"key": SessionKey("2", "101")},
])
async def test_every_stamp_component_is_rechecked(monkeypatch, changes):
    fixture = PreflightFixture()
    stamp = fixture.make_idle()
    fixture.pause = True
    check_task = asyncio.create_task(fixture.check())
    await fixture.started.wait()
    monkeypatch.setattr(fixture.lifecycle, "inspect", lambda key: replace(stamp, **changes))
    fixture.resume.set()
    result = await check_task
    assert result.status == "blocked"
    assert result.reason == "session_changed"


@pytest.mark.parametrize("route,reason", [(True, "route_retained"), (None, "runtime_unknown")])
async def test_route_is_rechecked_after_query(route, reason):
    fixture = PreflightFixture()
    fixture.make_idle()
    fixture.pause = True
    check_task = asyncio.create_task(fixture.check())
    await fixture.started.wait()
    fixture.route = route
    fixture.resume.set()
    result = await check_task
    assert result.status == "blocked"
    assert result.reason == reason


async def test_reservation_blocks_duplicate_queries_but_not_other_tenants_or_real_activity():
    fixture = PreflightFixture()
    fixture.make_idle()
    other_key = SessionKey("2", KEY.session_id)
    fixture.make_idle(other_key)
    fixture.pause = True
    first = asyncio.create_task(fixture.check())
    await fixture.started.wait()
    second = await fixture.check()
    assert second.reason == "check_in_progress"
    assert second.status == "blocked"
    assert fixture.calls == [("1", "101")]
    fixture.pause = False
    other_result = await fixture.check(other_key)
    assert other_result.status == "candidate"
    assert fixture.calls == [("1", "101"), ("2", "101")]
    with fixture.lifecycle.acquire(KEY, "admission"):
        assert fixture.lifecycle.inspect(KEY).total == 1
    fixture.resume.set()
    assert (await first).reason == "session_changed"
    fixture.now += 20.0
    assert (await fixture.check()).status == "candidate"


@pytest.mark.parametrize("response,presence,reason", [
    (pending_response("active"), PendingPresence.PRESENT, "pending_present"),
    (pending_response("applying"), PendingPresence.PRESENT, "pending_present"),
    ({"error": "unavailable", "data": None}, PendingPresence.UNKNOWN, "pending_unknown"),
    ({"code": 0}, PendingPresence.UNKNOWN, "pending_unknown"),
])
async def test_pending_present_or_unknown_is_not_a_candidate(response, presence, reason):
    fixture = PreflightFixture()
    fixture.make_idle()
    fixture.response = response
    result = await fixture.check()
    assert result.status == "blocked"
    assert result.reason == reason
    assert result.pending.presence is presence


@pytest.mark.parametrize("failure", ["cancel", "timeout", "exception"])
async def test_query_failure_cleans_reservation_without_revising_idle(failure):
    fixture = PreflightFixture()
    stamp = fixture.make_idle()
    fixture.pause = failure != "exception"
    fixture.error = RuntimeError("private backend details") if failure == "exception" else None
    check_task = asyncio.create_task(fixture.check(timeout_seconds=0.01 if failure == "timeout" else 1.0))
    await fixture.started.wait()
    if failure == "cancel":
        check_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await check_task
    else:
        result = await check_task
        assert result.status == "blocked"
        assert result.pending.presence is PendingPresence.UNKNOWN
        assert result.pending.reason == ("query_timeout" if failure == "timeout" else "query_failed")
        assert "private backend details" not in repr(result)
    assert fixture.lifecycle.inspect(KEY) == stamp
    fixture.pause = False
    fixture.error = None
    assert (await fixture.check()).status == "candidate"


@pytest.mark.parametrize("invalid", [0, -1, True, None, "1", float("inf"), float("nan")])
@pytest.mark.parametrize("field", ["idle_seconds", "timeout_seconds"])
async def test_policy_durations_must_be_explicit_positive_finite_numbers(invalid, field):
    fixture = PreflightFixture()
    stamp = fixture.make_idle()
    with pytest.raises(ValueError):
        await fixture.check(**{field: invalid})
    assert not fixture.calls
    assert fixture.lifecycle.inspect(KEY) == stamp
