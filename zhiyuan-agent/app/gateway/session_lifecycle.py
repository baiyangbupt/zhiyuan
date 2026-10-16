"""Single-event-loop session ownership; deliberately does not evict state."""
from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from uuid import uuid4

from app.gateway.ui_events import SessionKey


OWNER_KINDS = frozenset({
    "admission", "turn", "connection", "gateway_read", "action",
    "continuation", "native_request", "publish",
})


@dataclass(frozen=True, slots=True)
class SessionOwnershipSnapshot:
    key: SessionKey
    generation: str
    revision: int
    owners: Mapping[str, int]
    idle_since: float | None

    @property
    def total(self) -> int:
        return sum(self.owners.values())


@dataclass(slots=True)
class _Entry:
    key: SessionKey
    generation: str = field(default_factory=lambda: uuid4().hex)
    revision: int = 0
    owners: dict[object, str] = field(default_factory=dict)
    idle_since: float | None = None


class SessionLease:
    def __init__(self, registry: SessionLifecycle, entry: _Entry, token: object) -> None:
        self._registry = registry
        self._entry = entry
        self._generation = entry.generation
        self._token = token
        self._closed = False

    def close(self) -> None:
        if not self._closed:
            self._registry._release(self._entry, self._generation, self._token)
            self._closed = True

    def __enter__(self) -> SessionLease:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


class SessionLifecycle:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._entries: dict[SessionKey, _Entry] = {}

    def acquire(self, key: SessionKey, owner_kind: str) -> SessionLease:
        if not isinstance(key, SessionKey):
            raise TypeError("session ownership requires SessionKey")
        if owner_kind not in OWNER_KINDS:
            raise ValueError("unsupported session owner kind")
        entry = self._entries.get(key)
        if entry is None:
            entry = self._entries[key] = _Entry(key)
        token = object()
        entry.owners[token] = owner_kind
        entry.revision += 1
        entry.idle_since = None
        return SessionLease(self, entry, token)

    def inspect(self, key: SessionKey) -> SessionOwnershipSnapshot | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        return SessionOwnershipSnapshot(
            key=key, generation=entry.generation, revision=entry.revision,
            owners=MappingProxyType(dict(Counter(entry.owners.values()))),
            idle_since=entry.idle_since,
        )

    def _release(self, entry: _Entry, generation: str, token: object) -> None:
        if self._entries.get(entry.key) is not entry or entry.generation != generation:
            return
        if token not in entry.owners:
            return
        del entry.owners[token]
        entry.revision += 1
        if not entry.owners:
            entry.idle_since = self._clock()
