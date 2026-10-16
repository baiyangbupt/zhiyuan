"""Read-only reclamation diagnostics; candidates never authorize deletion."""
from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

from app.gateway.session_lifecycle import SessionLifecycle, SessionOwnershipSnapshot
from app.gateway.ui_events import SessionKey


class PendingPresence(str, Enum):
    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PendingObservation:
    key: SessionKey
    presence: PendingPresence
    reason: str


def _identity_matches(value: Any, expected: str) -> bool:
    return type(value) in (str, int) and str(value) == expected


def classify_pending_response(key: SessionKey, response: Any) -> PendingObservation:
    """Classify an envelope from the strict pending loader, never a snapshot."""
    if (
        not isinstance(response, dict)
        or type(response.get("code")) is not int
        or response["code"] != 0
        or "data" not in response
        or "error" in response
        or "errors" in response
        or ("success" in response and response["success"] is not True)
        or ("failed" in response and response["failed"] is not False)
    ):
        return PendingObservation(key, PendingPresence.UNKNOWN, "invalid_response")
    data = response["data"]
    if data is None:
        return PendingObservation(key, PendingPresence.ABSENT, "pending_absent")
    if not isinstance(data, dict):
        return PendingObservation(key, PendingPresence.UNKNOWN, "invalid_pending")
    if (
        not _identity_matches(data.get("chatSessionId"), key.session_id)
        or ("tenantId" in data and not _identity_matches(data["tenantId"], key.tenant_id))
    ):
        return PendingObservation(key, PendingPresence.UNKNOWN, "identity_mismatch")
    if (
        not isinstance(data.get("pendingId"), str)
        or not data["pendingId"].strip()
        or type(data.get("revision")) is not int
        or data["revision"] <= 0
    ):
        return PendingObservation(key, PendingPresence.UNKNOWN, "invalid_pending")
    status = data.get("status")
    if isinstance(status, str):
        if status in {"active", "applying"}:
            return PendingObservation(key, PendingPresence.PRESENT, "pending_present")
        if status in {"applied", "cancelled", "expired"}:
            return PendingObservation(key, PendingPresence.ABSENT, "pending_terminal")
    return PendingObservation(key, PendingPresence.UNKNOWN, "unknown_status")


@dataclass(frozen=True, slots=True)
class ReclaimPreflightResult:
    key: SessionKey
    status: Literal["candidate", "blocked"]
    reason: str
    stamp: SessionOwnershipSnapshot | None = None
    pending: PendingObservation | None = None


def _positive_duration(value: float) -> None:
    try:
        valid = type(value) in (int, float) and value > 0 and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("preflight durations must be positive finite numbers")


class SessionReclaimPreflight:
    """Single-loop diagnostics only; a candidate is not a deletion permit."""

    def __init__(
        self,
        lifecycle: SessionLifecycle,
        pending_loader: Callable[..., Awaitable[Any]],
        route_retained: Callable[[SessionKey], bool | None],
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._lifecycle = lifecycle
        self._pending_loader = pending_loader
        self._route_retained = route_retained
        self._clock = clock
        self._inflight: set[SessionKey] = set()

    def _route_blocker(self, key: SessionKey) -> str | None:
        try:
            retained = self._route_retained(key)
        except Exception:
            return "runtime_unknown"
        if type(retained) is not bool:
            return "runtime_unknown"
        return "route_retained" if retained else None

    async def check(
        self, key: SessionKey, *, idle_seconds: float, timeout_seconds: float,
    ) -> ReclaimPreflightResult:
        _positive_duration(idle_seconds)
        _positive_duration(timeout_seconds)
        if not isinstance(key, SessionKey):
            raise TypeError("session preflight requires SessionKey")
        if key in self._inflight:
            return ReclaimPreflightResult(key, "blocked", "check_in_progress")
        stamp = self._lifecycle.inspect(key)
        if stamp is None:
            return ReclaimPreflightResult(key, "blocked", "no_entry")
        if stamp.total:
            return ReclaimPreflightResult(key, "blocked", "owners_active", stamp)
        if stamp.idle_since is None or self._clock() - stamp.idle_since < idle_seconds:
            return ReclaimPreflightResult(key, "blocked", "not_idle_enough", stamp)
        blocker = self._route_blocker(key)
        if blocker:
            return ReclaimPreflightResult(key, "blocked", blocker, stamp)
        self._inflight.add(key)
        try:
            try:
                response = await asyncio.wait_for(
                    self._pending_loader(tenant_id=key.tenant_id, session_id=key.session_id),
                    timeout=timeout_seconds,
                )
                pending = classify_pending_response(key, response)
            except asyncio.TimeoutError:
                pending = PendingObservation(key, PendingPresence.UNKNOWN, "query_timeout")
            except Exception:
                pending = PendingObservation(key, PendingPresence.UNKNOWN, "query_failed")
            blocker = self._route_blocker(key)
            if self._lifecycle.inspect(key) != stamp:
                return ReclaimPreflightResult(key, "blocked", "session_changed", stamp, pending)
            if blocker:
                return ReclaimPreflightResult(key, "blocked", blocker, stamp, pending)
            if pending.presence is PendingPresence.PRESENT:
                return ReclaimPreflightResult(key, "blocked", "pending_present", stamp, pending)
            if pending.presence is PendingPresence.UNKNOWN:
                return ReclaimPreflightResult(key, "blocked", "pending_unknown", stamp, pending)
            return ReclaimPreflightResult(key, "candidate", "candidate", stamp, pending)
        finally:
            self._inflight.discard(key)
