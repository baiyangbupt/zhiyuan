from __future__ import annotations

import asyncio

import pytest

from app.harness.binding import ThreadBinding
from app.mcp_server.response import error, ok
from app.mcp_server.server import READONLY_TOOL_NAMES, build_sdk_server, build_server
from app.mcp_server.tools_readonly import InternalClientBackend, ReadonlyDomainTools


def trusted_context(
    admission_mode: str = "major", snapshot_version: int | None = None
) -> ThreadBinding:
    return ThreadBinding(
        thread_id="thr_test",
        tenant_id="tenant-1",
        session_id="101",
        user_id="202",
        allowed_capabilities=frozenset(
            {"catalog_read", "catalog.search_schools", "admission_read"}
        ),
        admission_mode=admission_mode,
        snapshot_version=snapshot_version,
    )


def test_server_registers_exactly_eight_readonly_tools() -> None:
    server = build_server()

    assert set(server.tools) == READONLY_TOOL_NAMES
    assert not any(name.endswith("apply") or name.startswith("plan.") for name in server.tools)


@pytest.mark.asyncio
async def test_sdk_server_exposes_same_eight_tools_with_structured_output_schema() -> None:
    sdk_server = build_sdk_server(ReadonlyDomainTools(trusted_context(), backend=None))
    list_handler = sdk_server.request_handlers[next(
        key for key in sdk_server.request_handlers if key.__name__ == "ListToolsRequest"
    )]

    listed = await list_handler(None)
    tools = listed.root.tools

    assert {tool.name for tool in tools} == READONLY_TOOL_NAMES
    assert all(tool.outputSchema and "status" in tool.outputSchema["required"] for tool in tools)


def test_standard_envelope_keeps_state_version_and_evidence() -> None:
    result = ok(
        {"items": []},
        state_version=42,
        evidence=[{"evidenceId": "ev-1"}],
        entities=[{"entityId": "school-1"}],
        limitations=["数据覆盖有限"],
    )

    assert result == {
        "status": "ok",
        "data": {"items": []},
        "resolvedEntities": [{"entityId": "school-1"}],
        "evidence": [{"evidenceId": "ev-1"}],
        "limitations": ["数据覆盖有限"],
        "stateVersion": 42,
    }


@pytest.mark.asyncio
async def test_catalog_tool_requires_entity_resolution_for_free_text(monkeypatch) -> None:
    calls = []

    class Backend:
        async def resolve(self, **kwargs):
            calls.append(("resolve", kwargs))
            return {"status": "needs_clarification", "data": {"candidates": []}}

        async def search_schools(self, **kwargs):
            calls.append(("search", kwargs))
            return {"items": []}

    tools = ReadonlyDomainTools(trusted_context(), backend=Backend())
    result = await tools.call("catalog.search_schools", {"query": "华师大"})

    assert result["status"] == "needs_clarification"
    assert calls[0][0] == "resolve"
    assert all(call[0] != "search" for call in calls)


@pytest.mark.asyncio
async def test_readonly_context_cannot_call_write_capability() -> None:
    tools = ReadonlyDomainTools(trusted_context(), backend=None)

    result = await tools.call("plan.propose_changes", {"action": "remove"})

    assert result["status"] == "capability_denied"


@pytest.mark.asyncio
async def test_same_arguments_are_deduplicated_and_backend_failure_retries_once() -> None:
    class Backend:
        count = 0

        async def resolve(self, **kwargs):
            return {"status": "ok", "data": {"entityId": "school-1"}}

        async def search_schools(self, **kwargs):
            self.count += 1
            if self.count == 1:
                raise RuntimeError("temporary")
            return {"items": [{"school": "A"}]}

    backend = Backend()
    tools = ReadonlyDomainTools(trusted_context(), backend=backend)
    first = await tools.call("catalog.search_schools", {"query": "school-1"})
    second = await tools.call("catalog.search_schools", {"query": "school-1"})

    assert first["status"] == "ok"
    assert second["status"] == "ok"
    assert backend.count == 2


@pytest.mark.asyncio
async def test_stale_state_is_rejected_before_backend_call() -> None:
    class Backend:
        async def resolve(self, **kwargs):
            raise AssertionError("must not call backend")

    tools = ReadonlyDomainTools(trusted_context(), backend=Backend(), current_state_version=43)

    result = await tools.call(
        "entity.resolve",
        {"query": "浙江大学", "stateVersion": 42},
    )

    assert result["status"] == "stale_state"


@pytest.mark.asyncio
async def test_invalid_state_version_fails_closed() -> None:
    tools = ReadonlyDomainTools(trusted_context(), backend=None)

    result = await tools.call("entity.resolve", {"query": "浙江大学", "stateVersion": "bad"})

    assert result["status"] == "invalid_state_version"


@pytest.mark.asyncio
async def test_backend_timeout_retries_once_then_returns_recoverable_error() -> None:
    class Backend:
        async def resolve(self, **kwargs):
            await asyncio.sleep(0.05)
            raise RuntimeError("still unavailable")

    binding = ThreadBinding(
        thread_id="thr_test",
        tenant_id="tenant-1",
        session_id="101",
        user_id="202",
        allowed_capabilities=frozenset({"catalog_read"}),
    )
    tools = ReadonlyDomainTools(binding, backend=Backend(), backend_timeout=0.01)

    result = await tools.call("entity.resolve", {"query": "浙江大学"})

    assert result["status"] == "backend_unavailable"


@pytest.mark.asyncio
async def test_backend_ok_result_is_projected_into_standard_envelope() -> None:
    class Backend:
        async def resolve(self, **kwargs):
            return {
                "status": "ok",
                "data": {"entityId": "school-1", "name": "浙江大学"},
                "resolvedEntities": [{"entityId": "school-1", "entityType": "school"}],
                "evidence": [{"evidenceId": "ev-1", "threadId": "thr_test", "dataVersion": "2026"}],
                "limitations": ["仅展示本科批"],
            }

    tools = ReadonlyDomainTools(
        ThreadBinding(
            thread_id="thr_test",
            tenant_id="tenant-1",
            session_id="101",
            user_id="202",
            allowed_capabilities=frozenset({"catalog_read"}),
        ),
        backend=Backend(),
    )

    result = await tools.call("entity.resolve", {"query": "浙江大学"})

    assert result["status"] == "ok"
    assert result["data"] == {"entityId": "school-1", "name": "浙江大学"}
    assert result["resolvedEntities"] == [{"entityId": "school-1", "entityType": "school"}]
    assert result["evidence"][0]["evidenceId"] == "ev-1"
    assert result["limitations"] == ["仅展示本科批"]


@pytest.mark.asyncio
async def test_cross_thread_evidence_is_rejected() -> None:
    class Backend:
        async def resolve(self, **kwargs):
            return {
                "data": {"entityId": "school-1"},
                "evidence": [{"evidenceId": "ev-other", "threadId": "thr-other", "dataVersion": "2026"}],
            }

    tools = ReadonlyDomainTools(trusted_context(), backend=Backend())

    result = await tools.call("entity.resolve", {"query": "浙江大学"})

    assert result["status"] == "evidence_scope_violation"
    assert result["evidence"] == []


@pytest.mark.asyncio
async def test_history_requires_explicit_scope_instead_of_zero_defaults() -> None:
    calls = []

    class Backend:
        async def get_history(self, **kwargs):
            calls.append(kwargs)
            return {"rows": []}

    tools = ReadonlyDomainTools(
        ThreadBinding(
            thread_id="thr_test",
            tenant_id="tenant-1",
            session_id="101",
            user_id="202",
            allowed_capabilities=frozenset({"admission_read"}),
        ),
        backend=Backend(),
    )

    result = await tools.call("admission.get_history", {})

    assert result["status"] == "needs_clarification"
    assert calls == []


@pytest.mark.asyncio
async def test_call_budget_rejects_new_calls_but_keeps_deduplication() -> None:
    class Backend:
        async def resolve(self, **kwargs):
            return {"data": {"entityId": kwargs["query"]}}

    tools = ReadonlyDomainTools(trusted_context(), backend=Backend(), max_calls=1)

    first = await tools.call("entity.resolve", {"query": "浙江大学"})
    duplicate = await tools.call("entity.resolve", {"query": "浙江大学"})
    second = await tools.call("entity.resolve", {"query": "复旦大学"})

    assert first["status"] == "ok"
    assert duplicate == first
    assert second["status"] == "call_budget_exceeded"


@pytest.mark.asyncio
async def test_production_mcp_runner_uses_authoritative_snapshot_version(monkeypatch) -> None:
    from app.mcp_server import server as mcp_server

    class Registry:
        async def resolve(self, *, thread_id, capability):
            assert thread_id == "thr_test"
            return trusted_context(snapshot_version=77)

    class Backend:
        async def resolve(self, **kwargs):
            return {"data": {"entityId": kwargs["query"]}}

    async def snapshot(*args, **kwargs):
        return {"data": {"snapshotVersion": 77}}

    monkeypatch.setattr(mcp_server.internal_client, "get_conversation_turn_snapshot", snapshot)
    monkeypatch.setattr(mcp_server, "InternalClientBackend", lambda **kwargs: Backend())
    result = await mcp_server._call_domain_tool(
        "entity.resolve",
        {"query": "浙江大学"},
        metadata={"threadId": "thr_test"},
        binding_registry=Registry(),
        fallback_tool_runner=ReadonlyDomainTools(trusted_context(), backend=Backend()),
    )

    assert result["status"] == "ok"
    assert result["stateVersion"] == 77


@pytest.mark.asyncio
async def test_production_mcp_runner_rejects_a_snapshot_changed_after_turn_start(monkeypatch) -> None:
    from app.mcp_server import server as mcp_server

    class Registry:
        async def resolve(self, *, thread_id, capability):
            return trusted_context(snapshot_version=77)

    async def snapshot(*args, **kwargs):
        return {"data": {"snapshotVersion": 78}}

    monkeypatch.setattr(mcp_server.internal_client, "get_conversation_turn_snapshot", snapshot)
    monkeypatch.setattr(
        mcp_server,
        "ReadonlyDomainTools",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("must not construct a domain runner for stale state")
        ),
    )
    result = await mcp_server._call_domain_tool(
        "entity.resolve",
        {"query": "浙江大学"},
        metadata={"threadId": "thr_test"},
        binding_registry=Registry(),
    )

    assert result["status"] == "stale_state"
    assert result["stateVersion"] == 78
    assert result["evidence"] == []


@pytest.mark.asyncio
async def test_production_mcp_runner_rejects_legacy_binding_without_snapshot_version(monkeypatch) -> None:
    from app.mcp_server import server as mcp_server

    class Registry:
        async def resolve(self, *, thread_id, capability):
            return trusted_context()

    async def snapshot(*args, **kwargs):
        raise AssertionError("must not query the snapshot for an unbound turn")

    monkeypatch.setattr(mcp_server.internal_client, "get_conversation_turn_snapshot", snapshot)
    result = await mcp_server._call_domain_tool(
        "entity.resolve",
        {"query": "浙江大学"},
        metadata={"threadId": "thr_test"},
        binding_registry=Registry(),
    )

    assert result["status"] == "state_version_unavailable"


@pytest.mark.asyncio
async def test_production_mcp_runner_fails_closed_when_snapshot_version_unavailable(monkeypatch) -> None:
    from app.mcp_server import server as mcp_server

    class Registry:
        async def resolve(self, *, thread_id, capability):
            return trusted_context(snapshot_version=77)

    async def broken_snapshot(*args, **kwargs):
        raise RuntimeError("snapshot backend down")

    monkeypatch.setattr(mcp_server.internal_client, "get_conversation_turn_snapshot", broken_snapshot)
    result = await mcp_server._call_domain_tool(
        "entity.resolve",
        {"query": "浙江大学"},
        metadata={"threadId": "thr_test"},
        binding_registry=Registry(),
        fallback_tool_runner=None,
    )

    assert result["status"] == "state_version_unavailable"


def test_error_envelope_has_no_backend_data_or_evidence() -> None:
    assert error("capability_denied", "只读模式", state_version=42) == {
        "status": "capability_denied",
        "data": {"message": "只读模式"},
        "resolvedEntities": [],
        "evidence": [],
        "limitations": [],
        "stateVersion": 42,
    }


@pytest.mark.asyncio
async def test_internal_backend_keeps_tenant_and_session_server_owned(monkeypatch) -> None:
    calls = []

    async def get_working_plan(thread_id):
        calls.append(thread_id)
        return {"code": 0, "data": {"items": []}}

    monkeypatch.setattr("app.util.internal_client.get_working_plan", get_working_plan)
    backend = InternalClientBackend(tenant_id=7, chat_session_id=101)

    result = await backend.get_current_plan(sessionId=999, userId=888)

    assert result == {"items": []}
    assert calls == [101]


@pytest.mark.asyncio
async def test_major_group_history_returns_group_rate_and_nested_major_details() -> None:
    class Backend:
        async def get_history(self, **kwargs):
            return {
                "dataVersion": "v17",
                "algorithmVersion": "rate-v3",
                "admissionFacts": [
                    {
                        "admissionMode": "major_group",
                        "admissionUnitId": "unit-1",
                        "schoolId": "s1",
                        "groupCode": "101",
                        "unitAdmissionRate": 45,
                        "riskTier": "冲",
                        "majorItems": [
                            {"majorId": "m-1", "majorAdmissionRate": 85}
                        ],
                    }
                ],
            }

    tools = ReadonlyDomainTools(trusted_context("major_group"), backend=Backend())
    result = await tools.call(
        "admission.get_history",
        {
            "admissionMode": "major_group",
            "areaId": "31",
            "batch": "本科批",
            "schoolId": "s1",
            "groupCode": "101",
            "year": 2026,
            "subjectType": "物理类",
            "stateVersion": 42,
        },
    )

    assert result["status"] == "ok"
    fact = result["data"]["admissionFacts"][0]
    assert result["data"]["admissionMode"] == "major_group"
    assert fact["unitAdmissionRate"] == 45
    assert fact["riskTier"] == "冲"
    assert fact["majorItems"][0]["majorAdmissionRate"] == 85
    assert result["evidence"][0]["admissionMode"] == "major_group"


@pytest.mark.asyncio
async def test_mode_mismatch_is_rejected_without_backend_call() -> None:
    class Backend:
        calls = 0

        async def get_current_plan(self, **kwargs):
            self.calls += 1
            return {}

    backend = Backend()
    tools = ReadonlyDomainTools(trusted_context("major"), backend=backend)

    result = await tools.call(
        "admission.get_current_plan", {"admissionMode": "major_group"}
    )

    assert result["status"] == "admission_mode_mismatch"
    assert backend.calls == 0


@pytest.mark.asyncio
async def test_missing_group_detail_is_insufficient_data_not_zero_rate() -> None:
    class Backend:
        async def check_eligibility(self, **kwargs):
            return {
                "dataVersion": "v17",
                "admissionFacts": [
                    {
                        "admissionMode": "major_group",
                        "admissionUnitId": "unit-1",
                        "schoolId": "s1",
                        "groupCode": "101",
                        "unitAdmissionRate": 70,
                        "riskTier": "保",
                        "majorItems": [],
                    }
                ],
            }

    tools = ReadonlyDomainTools(trusted_context("major_group"), backend=Backend())
    result = await tools.call(
        "admission.check_eligibility",
        {"admissionMode": "major_group", "groupCode": "101"},
    )

    assert result["status"] == "insufficient_data"
    assert "majorDetailAvailable=false" in result["limitations"]
    assert "admissionFacts" in result["data"]
