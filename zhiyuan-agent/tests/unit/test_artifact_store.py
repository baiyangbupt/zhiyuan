from __future__ import annotations

import sqlite3
import hashlib

import pytest

from app.gateway.artifact_store import ArtifactStoreError, SqliteArtifactStore


def _issue(store, **overrides):
    arguments = dict(
        tenant_id="tenant-1", session_id="session-1", thread_id="thread-1",
        artifact_type="candidate", state_version=42,
        tool_name="recommendation.preview_candidates", arguments={"score": 600},
        payload={"data": {"items": [{"schoolId": "school-1"}]}},
    )
    return store.issue(**{**arguments, **overrides})


def _read(store, record, **overrides):
    return store.get_many(**{
        "tenant_id": "tenant-1", "session_id": "session-1",
        "artifact_ids": [record["artifactId"]], **overrides,
    })


def test_issuance_survives_store_reopen_and_binding_table_is_untouched(tmp_path):
    path = tmp_path / "bindings.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE binding_sentinel (handle TEXT)")
        connection.execute("INSERT INTO binding_sentinel VALUES ('not-an-artifact')")
    record = _issue(SqliteArtifactStore(str(path)))
    assert _read(SqliteArtifactStore(str(path)), record) == {record["artifactId"]: record}
    assert path.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT handle FROM binding_sentinel").fetchall() == [("not-an-artifact",)]


def test_retries_keep_original_issuance_and_result_changes_get_a_new_id(tmp_path):
    clock = [100.0]
    store = SqliteArtifactStore(str(tmp_path / "store.sqlite3"), clock=lambda: clock[0])
    record = _issue(store)
    clock[0] += 10
    assert _issue(store, thread_id="resumed-thread") == record
    changed = _issue(store, payload={"data": {"items": [{"schoolId": "school-2"}]}})
    assert changed["artifactId"] != record["artifactId"]
    assert changed["payloadDigest"] != record["payloadDigest"]


@pytest.mark.parametrize("scope", [{"tenant_id": "tenant-2"}, {"session_id": "session-2"}])
def test_other_scope_cannot_read_a_registered_id(tmp_path, scope):
    store = SqliteArtifactStore(str(tmp_path / "store.sqlite3"))
    record = _issue(store)
    assert _read(store, record, **scope) == {}


def test_expiry_is_closed_and_old_id_cannot_be_resurrected(tmp_path):
    clock = [100.0]
    store = SqliteArtifactStore(str(tmp_path / "store.sqlite3"), ttl_seconds=10, clock=lambda: clock[0])
    original = _issue(store)
    clock[0] = 110
    assert _read(store, original) == {}
    replacement = _issue(store)
    assert replacement["artifactId"] != original["artifactId"]
    assert _read(store, original) == {}
    assert _read(store, replacement) == {replacement["artifactId"]: replacement}


def test_cleanup_is_batched_and_never_removes_live_records(tmp_path):
    clock = [100.0]
    path = str(tmp_path / "store.sqlite3")
    store = SqliteArtifactStore(path, ttl_seconds=10, clock=lambda: clock[0])
    for index in range(130):
        _issue(store, arguments={"index": index})
    clock[0] = 110
    live = _issue(store, arguments={"index": "live"})
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM codex_artifact_issuance").fetchone()[0] == 3
    assert _read(store, live) == {live["artifactId"]: live}


def test_corrupt_records_and_sqlite_failures_never_become_authority(tmp_path):
    path = str(tmp_path / "store.sqlite3")
    store = SqliteArtifactStore(path)
    record = _issue(store)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE codex_artifact_issuance SET record_json = '{}' ")
    with pytest.raises(ArtifactStoreError, match="artifact_invalid"):
        _read(store, record)
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE codex_artifact_issuance")
    with pytest.raises(ArtifactStoreError, match="artifact_store_unavailable") as error:
        _read(store, record)
    assert path not in str(error.value)


@pytest.mark.parametrize("overrides", [
    {"tenant_id": ""}, {"session_id": ""}, {"state_version": True},
    {"state_version": -1}, {"artifact_type": "plan_draft"},
    {"payload": {"score": float("nan")}}, {"thread_id": "x" * (17 * 1024)},
])
def test_invalid_issuance_is_rejected_without_a_record(tmp_path, overrides):
    path = str(tmp_path / "store.sqlite3")
    store = SqliteArtifactStore(path)
    with pytest.raises(ArtifactStoreError):
        _issue(store, **overrides)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM codex_artifact_issuance").fetchone()[0] == 0


@pytest.mark.parametrize("ttl", [0, -1, True, float("inf"), float("nan")])
def test_invalid_retention_is_rejected(tmp_path, ttl):
    with pytest.raises(ValueError):
        SqliteArtifactStore(str(tmp_path / "store.sqlite3"), ttl_seconds=ttl)


@pytest.mark.parametrize("matching_checksum", [False, True])
def test_deeply_nested_corrupt_records_return_a_stable_error(tmp_path, matching_checksum):
    path = str(tmp_path / "store.sqlite3")
    store = SqliteArtifactStore(path)
    record = _issue(store)
    nested = "[" * 1500 + "0" + "]" * 1500
    with sqlite3.connect(path) as connection:
        if matching_checksum:
            connection.execute(
                "UPDATE codex_artifact_issuance SET record_json = ?, record_digest = ?",
                (nested, hashlib.sha256(nested.encode()).hexdigest()),
            )
        else:
            connection.execute("UPDATE codex_artifact_issuance SET record_json = ?", (nested,))
    with pytest.raises(ArtifactStoreError, match="artifact_invalid"):
        _read(store, record)


def test_additive_database_columns_do_not_break_decoding(tmp_path):
    path = str(tmp_path / "store.sqlite3")
    store = SqliteArtifactStore(path)
    record = _issue(store)
    with sqlite3.connect(path) as connection:
        connection.execute("ALTER TABLE codex_artifact_issuance ADD COLUMN future_metadata TEXT")
    assert _read(store, record) == {record["artifactId"]: record}
    assert _issue(store) == record
    assert _issue(store, arguments={"limit": 2})["artifactId"] != record["artifactId"]


def test_deeply_nested_payload_cannot_escape_the_issuance_error_boundary(tmp_path):
    store = SqliteArtifactStore(str(tmp_path / "store.sqlite3"))
    nested = {}
    for depth in range(1500):
        nested = {"nested": nested}
    with pytest.raises(ArtifactStoreError, match="artifact_invalid"):
        _issue(store, payload=nested)
