from __future__ import annotations

import sqlite3

import pytest

from app.gateway.artifact_store import SqliteArtifactStore
from app.harness.binding import ThreadBinding
from app.mcp_server.tools_readonly import ReadonlyDomainTools


class Backend:
    async def preview_candidates(self, **arguments):
        return {"items": [{"schoolId": "school-1"}]}


def _binding():
    return ThreadBinding(
        thread_id="thread-1", tenant_id="tenant-1", session_id="session-1", user_id="user-1",
        allowed_capabilities=frozenset({"admission_read"}), snapshot_version=42,
    )


@pytest.mark.asyncio
async def test_mcp_persists_before_return_and_ignores_model_scope(tmp_path):
    path = str(tmp_path / "bindings.sqlite3")
    tools = ReadonlyDomainTools(_binding(), backend=Backend(), artifact_store=SqliteArtifactStore(path))
    result = await tools.call("recommendation.preview_candidates", {"tenantId": "foreign", "sessionId": "foreign"})
    assert result["status"] == "ok"
    record = result["artifacts"][0]
    persisted = SqliteArtifactStore(path).get_many(
        tenant_id="tenant-1", session_id="session-1", artifact_ids=[record["artifactId"]],
    )
    assert persisted[record["artifactId"]] == record
    assert record["tenantId"] == "tenant-1"
    assert record["sessionId"] == "session-1"
    assert record["stateVersion"] == 42


@pytest.mark.asyncio
async def test_missing_store_never_returns_a_successful_product():
    result = await ReadonlyDomainTools(_binding(), backend=Backend()).call("recommendation.preview_candidates")
    assert result["status"] == "artifact_store_unavailable"
    assert "artifacts" not in result
    assert "items" not in result["data"]


@pytest.mark.asyncio
async def test_failed_persistence_and_cached_read_cannot_bypass_the_ledger(tmp_path):
    path = str(tmp_path / "bindings.sqlite3")
    tools = ReadonlyDomainTools(_binding(), backend=Backend(), artifact_store=SqliteArtifactStore(path))
    assert (await tools.call("recommendation.preview_candidates"))["status"] == "ok"
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE codex_artifact_issuance")
    for arguments in ({}, {"limit": 2}):
        result = await tools.call("recommendation.preview_candidates", arguments)
        assert result["status"] == "artifact_store_unavailable"
        assert "artifacts" not in result
        assert path not in str(result)


@pytest.mark.asyncio
async def test_expired_cached_artifact_is_not_returned(tmp_path):
    clock = [100.0]
    store = SqliteArtifactStore(str(tmp_path / "store.sqlite3"), clock=lambda: clock[0], ttl_seconds=10)
    tools = ReadonlyDomainTools(_binding(), backend=Backend(), artifact_store=store)
    first = await tools.call("recommendation.preview_candidates")
    clock[0] = 110
    fresh = await tools.call("recommendation.preview_candidates")
    assert fresh["status"] == "ok"
    assert fresh["artifacts"][0]["artifactId"] != first["artifacts"][0]["artifactId"]


@pytest.mark.asyncio
async def test_production_mcp_adapter_injects_the_shared_store(tmp_path, monkeypatch):
    from app.mcp_server import server
    from app.mcp_server.context import ThreadBindingRegistry

    registry = ThreadBindingRegistry(str(tmp_path / "bindings.sqlite3"))
    store = SqliteArtifactStore(str(registry.path))

    async def resolve(**kwargs):
        return _binding()

    async def version(binding):
        return 42

    monkeypatch.setattr(registry, "resolve", resolve)
    monkeypatch.setattr(server, "_read_snapshot_version", version)
    monkeypatch.setattr(server, "InternalClientBackend", lambda **kwargs: Backend())
    result = await server._call_domain_tool(
        "recommendation.preview_candidates", {}, metadata={"threadId": "thread-1"},
        binding_registry=registry, artifact_store=store,
    )
    assert result["status"] == "ok"
    assert store.get_many(
        tenant_id="tenant-1", session_id="session-1", artifact_ids=[result["artifacts"][0]["artifactId"]],
    )
