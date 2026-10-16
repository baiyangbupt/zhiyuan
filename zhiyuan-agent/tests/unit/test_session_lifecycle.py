from dataclasses import FrozenInstanceError

import pytest

from app.gateway.session_lifecycle import SessionLifecycle
from app.gateway.ui_events import SessionKey


KEY = SessionKey("tenant-1", "session-1")


def test_owners_overlap_and_only_last_release_starts_idle_clock():
    now = [10.0]
    lifecycle = SessionLifecycle(clock=lambda: now[0])
    assert lifecycle.inspect(KEY) is None
    first = lifecycle.acquire(KEY, "turn")
    second = lifecycle.acquire(KEY, "action")
    snapshot = lifecycle.inspect(KEY)
    assert snapshot.total == 2
    assert dict(snapshot.owners) == {"turn": 1, "action": 1}
    assert snapshot.idle_since is None
    first.close()
    assert lifecycle.inspect(KEY).idle_since is None
    now[0] = 20.0
    second.close()
    idle = lifecycle.inspect(KEY)
    assert idle.total == 0
    assert idle.idle_since == 20.0
    assert idle.revision == 4
    now[0] = 30.0
    second.close()
    assert lifecycle.inspect(KEY) == idle
    with lifecycle.acquire(KEY, "gateway_read"):
        assert lifecycle.inspect(KEY).generation == snapshot.generation
        assert lifecycle.inspect(KEY).idle_since is None
    assert lifecycle.inspect(KEY).idle_since == 30.0


def test_snapshot_is_immutable_and_does_not_expose_live_owner_map():
    lifecycle = SessionLifecycle()
    lease = lifecycle.acquire(KEY, "connection")
    snapshot = lifecycle.inspect(KEY)
    with pytest.raises(FrozenInstanceError):
        snapshot.revision = 999
    with pytest.raises(TypeError):
        snapshot.owners["connection"] = 999
    lease.close()
    assert snapshot.total == 1
    assert snapshot.owners["connection"] == 1
    assert lifecycle.inspect(KEY).total == 0


def test_tenant_and_registry_isolation_and_exception_cleanup():
    lifecycle = SessionLifecycle()
    other = SessionKey("tenant-2", KEY.session_id)
    with lifecycle.acquire(KEY, "admission"):
        with pytest.raises(RuntimeError):
            with lifecycle.acquire(other, "native_request"):
                raise RuntimeError("failed")
        assert lifecycle.inspect(KEY).total == 1
        assert lifecycle.inspect(other).total == 0
        assert lifecycle.inspect(KEY).generation != lifecycle.inspect(other).generation
    assert SessionLifecycle().inspect(KEY) is None


@pytest.mark.parametrize("kind", ["unknown", "", None])
def test_invalid_owner_does_not_create_metadata(kind):
    lifecycle = SessionLifecycle()
    with pytest.raises(ValueError):
        lifecycle.acquire(KEY, kind)
    assert lifecycle.inspect(KEY) is None
