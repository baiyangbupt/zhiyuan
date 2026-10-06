from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

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


def test_server_registers_exactly_the_readonly_tools() -> None:
    server = build_server()

    assert set(server.tools) == READONLY_TOOL_NAMES
    # `planning.get_working_plan` 是 `admission.get_current_plan` 的新名，
    # 两名并存一个发布周期（计划的兼容要求）。写操作类工具一个都不在。
    assert "planning.get_working_plan" in READONLY_TOOL_NAMES
    assert not any(name.endswith("apply") or name.startswith("plan.") for name in server.tools)


@pytest.mark.asyncio
async def test_sdk_server_exposes_the_same_tools_with_structured_output_schema() -> None:
    sdk_server = build_sdk_server(ReadonlyDomainTools(trusted_context(), backend=None))
    list_handler = sdk_server.request_handlers[next(
        key for key in sdk_server.request_handlers if key.__name__ == "ListToolsRequest"
    )]

    listed = await list_handler(None)
    tools = listed.root.tools

    assert {tool.name for tool in tools} == READONLY_TOOL_NAMES
    assert all(tool.outputSchema and "status" in tool.outputSchema["required"] for tool in tools)


@pytest.mark.asyncio
async def test_every_listed_tool_declares_read_only_hint() -> None:
    """`readOnlyHint` 是"能不能被调用"的开关，不只是元数据。

    真实二进制对未声明只读的 MCP 工具一律要求审批；生产配置是
    approvalPolicy=never，无处可批，于是调用直接失败：
    `MCP tool call requires approval, but approval policy is never`。
    同时这条注解是**对外的安全承诺**——它一旦放宽而工具仍可写，就等于给写操作
    开了免审批的口子。它与 `test_readonly_context_cannot_call_write_capability`
    是一对：那条证明写不了，这条证明没声称能写。
    """
    sdk_server = build_sdk_server(ReadonlyDomainTools(trusted_context(), backend=None))
    list_handler = sdk_server.request_handlers[next(
        key for key in sdk_server.request_handlers if key.__name__ == "ListToolsRequest"
    )]

    tools = (await list_handler(None)).root.tools

    assert tools
    assert all(
        tool.annotations is not None and tool.annotations.readOnlyHint is True
        for tool in tools
    )
    assert "plan_apply" not in READONLY_TOOL_NAMES


def test_production_stdio_loop_lists_read_only_hint(tmp_path) -> None:
    """盯**生产**那条路，不盯测试专用的 SDK server。

    上面那条验的是 `build_sdk_server`，而线上跑的是 `serve()` 里的手写
    stdio 循环——两者曾各写一份清单，于是 `readOnlyHint` 只加在了 SDK 那份上，
    单测全绿而线上所有域内调用被拒。这条测试起真实子进程、读真实报文。
    """
    script = Path(__file__).resolve().parents[2] / "app" / "mcp_server" / "server.py"
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]
    completed = subprocess.run(
        [sys.executable, str(script), "--binding-registry", str(tmp_path / "bindings.sqlite3")],
        input="\n".join(json.dumps(item) for item in requests) + "\n",
        capture_output=True, text=True, timeout=30,
    )

    listed: list[dict] = []
    for line in completed.stdout.splitlines():
        payload = json.loads(line)
        tools = (payload.get("result") or {}).get("tools")
        if tools:
            listed = tools

    assert {tool["name"] for tool in listed} == READONLY_TOOL_NAMES
    missing = [tool["name"] for tool in listed if (tool.get("annotations") or {}).get("readOnlyHint") is not True]
    assert missing == []


def test_production_stdio_loop_answers_every_request_with_an_id(tmp_path) -> None:
    """带 id 的请求**必须**有应答，未识别的方法也要回错。

    沉默不是优雅降级：真实 MCP 客户端握手后会探测 `resources/list`、
    `resources/templates/list`，收不到应答就一直等，整个 server 停在未连接状态
    （实测 `mcpServerStatus/list` 超时，且链路上没有任何日志）。
    """
    script = Path(__file__).resolve().parents[2] / "app" / "mcp_server" / "server.py"
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}},
        {"jsonrpc": "2.0", "id": 2, "method": "resources/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "resources/templates/list", "params": {}},
        {"jsonrpc": "2.0", "id": 4, "method": "totally/unknown", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},  # 通知无 id，不该有应答
    ]
    completed = subprocess.run(
        [sys.executable, str(script), "--binding-registry", str(tmp_path / "bindings.sqlite3")],
        input="\n".join(json.dumps(item) for item in requests) + "\n",
        capture_output=True, text=True, timeout=30,
    )

    answered = {json.loads(line)["id"]: json.loads(line) for line in completed.stdout.splitlines()}

    assert set(answered) == {1, 2, 3, 4}
    assert answered[2]["result"] == {"resources": []}
    assert answered[3]["result"] == {"resourceTemplates": []}
    assert answered[4]["error"]["code"] == -32601


@pytest.mark.asyncio
async def test_working_plan_alias_uses_the_same_implementation() -> None:
    """新名与旧名必须落到同一个方法上。

    保留两套语义会让"到底哪份是草案"变成一个靠文档回答的问题，
    而两个工具在模型看来是不同的东西——它会以为自己有两个选择。
    """
    calls = []

    class Backend:
        async def get_current_plan(self, **kwargs):
            calls.append(kwargs)
            return {"code": 0, "data": {"items": []}}

    tools = ReadonlyDomainTools(trusted_context(), backend=Backend())
    old_name = await tools.call("admission.get_current_plan", {})
    new_name = await tools.call("planning.get_working_plan", {})

    # 断言的是"两个名字落到同一个实现、给出同一结果"，
    # 而不是某个具体状态——状态取决于替身返回什么，与别名无关。
    assert len(calls) == 2
    assert old_name == new_name


def test_standard_envelope_keeps_state_version_and_evidence() -> None:
    result = ok(
        {"items": []},
        kind="catalog",
        state_version=42,
        evidence=[{"evidenceId": "ev-1"}],
        entities=[{"entityId": "school-1"}],
        limitations=["数据覆盖有限"],
    )

    assert result == {
        "schemaVersion": 1,
        "kind": "catalog",
        "status": "ok",
        "data": {"items": []},
        "evidenceRefs": [{"evidenceId": "ev-1"}],
        "resolvedEntities": [{"entityId": "school-1"}],
        "limitations": ["数据覆盖有限"],
        "nextCursor": None,
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
async def test_major_search_survives_an_empty_entity_resolution() -> None:
    """"计算机"这种俗称解析不出唯一实体时，检索仍必须能跑。

    `resolve` 的"没有唯一实体"是以 **None** 回来的（Java `resultType=empty` →
    `data=null`）。这里曾经直接 `resolved.get(...)`，于是最常见的输入
    （方向统称、俗称）会让工具抛 `AttributeError: 'NoneType' object has no
    attribute 'get'`，再被包成 `backend_unavailable`——用户读到的结论是
    "后端不可用"，而后端是好的。
    """
    calls = []

    class Backend:
        async def resolve(self, **kwargs):
            calls.append(("resolve", kwargs))
            return None

        async def search_majors(self, **kwargs):
            calls.append(("search", kwargs))
            # 形状取自 InternalClientBackend.search_majors：它已经 `_data()` 取过
            # 一层，所以这里回来的是**列表**，不是 `{resultType, data}` 信封。
            return [{"majorId": "574", "majorName": "计算机科学与技术"}]

    tools = ReadonlyDomainTools(trusted_context(), backend=Backend())
    result = await tools.call("catalog.search_majors", {"query": "计算机"})

    assert result["status"] == "ok"
    assert [call[0] for call in calls] == ["resolve", "search"]
    assert result["data"][0]["majorName"] == "计算机科学与技术"


@pytest.mark.asyncio
async def test_school_search_with_a_name_goes_to_name_search_not_filters(monkeypatch) -> None:
    """带名字的检索必须按名字查，不能只拿筛选项去列一遍。

    以前 `query` 在这里被静默丢掉，`query="北京大学"` 返回的是与该名字无关的
    一批学校——模型得自己发现并绕道；不谨慎的模型会把那份列表当答案念出来。
    """
    from app.util import internal_client

    calls = []

    async def by_name(school_name):
        calls.append(("by_name", school_name))
        return [{"schoolId": "1", "schoolName": "北京大学"}]

    async def advanced(**kwargs):
        calls.append(("advanced", kwargs))
        return [{"schoolId": "15536480217090560", "schoolName": "赣州起元职业学院"}]

    monkeypatch.setattr(internal_client, "search_schools_by_name", by_name)
    monkeypatch.setattr(internal_client, "catalog_list_schools", advanced)

    backend = InternalClientBackend.__new__(InternalClientBackend)
    named = await backend.search_schools(query="北京大学")
    filtered = await backend.search_schools(province="北京")

    assert named[0]["schoolName"] == "北京大学"
    assert filtered[0]["schoolName"] == "赣州起元职业学院"
    assert calls == [
        ("by_name", "北京大学"),
        ("advanced", {"province": "北京", "city": None, "school_type": None, "ownership": None, "education_level": None}),
    ]


@pytest.mark.asyncio
def test_internal_client_backend_carries_the_snapshot_version() -> None:
    """适配器必须带 `current_state_version`（2026-09-24 真栈 E2E 抓到的"5 个工具全挂"）。

    它原来只挂在 `ReadonlyDomainTools` 上 ✗，而适配器的 `check_eligibility` / `compare` /
    `get_charter` / `get_enrollment_plan` / `list_admission_units` 都用它给信封盖版本戳 →
    那 5 个工具全部 `backend_unavailable: 'InternalClientBackend' object has no attribute
    'current_state_version'`，而**推荐路径的入口正好在其中**（模型实测：需要录取率的调用全失败）。
    """
    from app.mcp_server.tools_readonly import InternalClientBackend

    backend = InternalClientBackend(tenant_id=1, chat_session_id=2, current_state_version=7)

    assert backend.current_state_version == 7


@pytest.mark.asyncio
async def test_readonly_context_cannot_call_write_capability() -> None:
    tools = ReadonlyDomainTools(trusted_context(), backend=None)

    result = await tools.call("plan.propose_changes", {"action": "remove"})

    assert result["status"] == "capability_denied"
    # 只读实例的拒绝话术要说清"这台实例的写路径没活着"，别让模型接着试。
    assert "只读" in json.dumps(result, ensure_ascii=False)


@pytest.mark.asyncio
async def test_write_mode_refusal_points_at_the_proposal_path() -> None:
    """写实例上写工具**仍不可调**，但拒绝话术要指向合法出口（提案）。

    依据是 P2 任务书 §一 那句："写操作路径的工具面要明确到模型能据以判断'这个动作
    我能不能做'，而不是让它试出来"。新链路的写路径是提案 → 确认 → 执行，
    所以写实例上模型该听到的是"怎么写才行"，而不是"你不能写"。
    """
    tools = ReadonlyDomainTools(trusted_context(), backend=None, mode="write")

    result = await tools.call("plan_apply", {"action": "apply"})

    assert result["status"] == "capability_denied"
    assert "proposalRequest" in json.dumps(result, ensure_ascii=False)


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
    assert result["evidenceRefs"][0]["evidenceId"] == "ev-1"
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
    assert result["evidenceRefs"] == []


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
    assert result["evidenceRefs"] == []


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
    assert error("capability_denied", "只读模式", kind="catalog", state_version=42) == {
        "schemaVersion": 1,
        "kind": "catalog",
        "status": "capability_denied",
        "data": {"message": "只读模式"},
        "evidenceRefs": [],
        "resolvedEntities": [],
        "limitations": [],
        "nextCursor": None,
        "stateVersion": 42,
    }


@pytest.mark.asyncio
async def test_internal_backend_keeps_tenant_and_session_server_owned(monkeypatch) -> None:
    calls = []

    async def get_working_plan(thread_id, tenant_id):
        calls.append((thread_id, tenant_id))
        return {"code": 0, "data": {"items": []}}

    monkeypatch.setattr("app.util.internal_client.get_working_plan", get_working_plan)
    backend = InternalClientBackend(tenant_id=7, chat_session_id=101)

    result = await backend.get_current_plan(sessionId=999, userId=888)

    assert result == {"items": []}
    # 模型传进来的 sessionId/userId 一律不采信：租户与会话都取自**可信 binding**。
    # tenant 也在这里断言，因为路径里的 tenant 曾经是硬编码的 1——那会让
    # tenant 非 1 的会话安静地读到别人的志愿表。
    assert calls == [(101, 7)]


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
    # 这条 fixture 的 backend **没有**返回 evidence（它只回 data）。
    # 以前这里断言的是自铸出来的那条；自铸删掉之后，"没有证据"才是正确结果——
    # 权威只能由签发方声明，替身不发就说明这条路没有证据。
    assert result["evidenceRefs"] == []
    assert "admission_evidence_missing" in result["limitations"]


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


@pytest.mark.asyncio
async def test_compare_requires_a_complete_scope() -> None:
    """口径缺项必须**拒绝**，不许拿"最近一年/默认省份"凑。

    跨年、跨批次的数字并排放进一张表，读者会默认它们可比——那是这张表最危险的错误。
    """
    backend = InternalClientBackend.__new__(InternalClientBackend)
    backend.tenant_id = "1"
    backend.chat_session_id = "900001"
    backend.thread_id = "thr"
    backend.current_state_version = 0
    tools = ReadonlyDomainTools(trusted_context(), backend=backend)

    result = await tools.call(
        "admission.compare",
        {"entities": [{"schoolId": "1"}, {"schoolId": "2"}], "areaId": "330000"},
    )

    assert result["status"] == "needs_clarification"
    assert set(result["data"]["missingFields"]) == {"batch", "year", "subjectType"}


@pytest.mark.asyncio
async def test_compare_marks_another_year_as_a_scope_mismatch(monkeypatch) -> None:
    """请求年份没有数据时取最新一年，但**口径标记成不一致** → 整列不可比。

    悄悄拿另一年的数字顶上，才是真正危险的做法：表里有数，读者不会知道
    那一列其实不是他要的那一年。
    """
    from app.util import internal_client

    async def score_line(**kwargs):
        return {
            "code": 0,
            "data": [{"year": 2024, "name": "北京大学", "minScore": "690", "enrollNum": "30"}],
            "evidence": [{"evidenceId": "ev-1"}],
        }

    calls: list[dict] = []

    async def compare_candidates(tenant_id, entities, dimensions):
        calls.append({"entities": entities, "dimensions": dimensions})
        return {
            "code": 0,
            "data": {
                "entities": entities,
                "dimensions": dimensions,
                "cells": [],
                "unavailableDimensions": ["finalScore", "planNum"],
                "limitations": ["comparison_scope_mismatch"],
            },
        }

    monkeypatch.setattr(internal_client, "query_school_major_score_line", score_line)
    monkeypatch.setattr(internal_client, "compare_candidates", compare_candidates)

    backend = InternalClientBackend.__new__(InternalClientBackend)
    backend.tenant_id = "1"
    backend.chat_session_id = "900001"
    backend.thread_id = "thr"
    backend.current_state_version = 0
    tools = ReadonlyDomainTools(trusted_context(), backend=backend)

    result = await tools.call(
        "admission.compare",
        {
            "entities": [{"schoolId": "1"}, {"schoolId": "2"}],
            "areaId": "330000",
            "batch": "01",
            "year": 2025,
            "subjectType": "N",
        },
    )

    assert result["status"] == "ok"
    assert calls[0]["entities"][0]["admissionYear"] == 2024
    assert "comparison_scope_mismatch" in result["data"]["limitations"]
    # 信封保留的是**证据对象**，不是 id 字符串：下游要按 scope/dataVersion 判它能不能用。
    assert [item["evidenceId"] for item in result["evidenceRefs"]] == ["ev-1"]


@pytest.mark.asyncio
async def test_preview_candidates_uses_trusted_identity_and_declares_sample(monkeypatch) -> None:
    """候选预览只读纵切的三条合同：**受信身份、20 条硬上限、样例边界**。

    - 模型塞进来的 tenantId/sessionId 必须被丢掉——否则它能把任何会话的候选
      装进自己的回合（身份只能来自受信 binding）；
    - 一次最多 20 条，全量留在服务器，`returned_items_are_sample` 是给模型的
      **边界声明**：不能拿这一页概括分布；
    - `state_mutation=False`：预览不改任何状态（Java 侧的版本号实证在真栈 E2E）。
    """
    from app.util import internal_client

    calls: list[dict] = []

    async def preview_candidates(tenant_id, chat_session_id, *, filters=None, page=1, page_size=20):
        calls.append(
            {
                "tenant_id": tenant_id,
                "chat_session_id": chat_session_id,
                "filters": filters,
                "page": page,
                "page_size": page_size,
            }
        )
        return {
            "code": 0,
            "msg": "success",
            "data": {
                "items": [
                    {"entityId": "v1", "volunteerId": "v1", "tier": "冲", "finalScore": 600.5},
                ],
                "total": 25,
                "page": page,
                "pageSize": page_size,
                "profileVersion": 7,
                "dataVersion": "dv-1",
                "limitations": ["filter_unsupported:schoolTags"],
            },
        }

    monkeypatch.setattr(internal_client, "preview_candidates", preview_candidates)

    backend = InternalClientBackend.__new__(InternalClientBackend)
    backend.tenant_id = "1"
    backend.chat_session_id = "900047"
    backend.thread_id = "thr"
    backend.current_state_version = 0
    tools = ReadonlyDomainTools(trusted_context(), backend=backend)

    result = await tools.call(
        "recommendation.preview_candidates",
        {
            # 别名（tier→tiers、school_tags→schoolTags）要归一，不能到不了上游。
            "filters": {"tier": "冲", "school_tags": ["985"]},
            "page": 1,
            "pageSize": 100,
            # 冒充身份：必须被 `_trusted_arguments` 丢掉。
            "tenantId": "999",
            "sessionId": "888",
        },
    )

    assert result["kind"] == "candidate"
    assert result["status"] == "ok"
    assert calls == [
        {
            "tenant_id": "1",
            "chat_session_id": "900047",
            "filters": {"tiers": ["冲"], "schoolTags": ["985"]},
            "page": 1,
            "page_size": 20,
        }
    ]
    assert result["data"]["total"] == 25
    assert result["data"]["returned_total"] == 1
    assert result["data"]["returned_items_are_sample"] is True
    assert result["data"]["state_mutation"] is False
    assert result["data"]["profile_version"] == 7
    assert result["data"]["data_version"] == "dv-1"
    # 上游的"过滤维度不支持"要如实带出去（data 与外层 limitations 都要有），不能吞。
    assert "filter_unsupported:schoolTags" in result["data"]["limitations"]
    assert "filter_unsupported:schoolTags" in result["limitations"]


def test_gateway_collects_evidence_from_the_mcp_text_result() -> None:
    """工具证据藏在 MCP 结果的 **JSON 字符串**里。

    形状取自真实 rollout 里 codex 发来的 item：
        item["result"] = {"content": [{"type": "text", "text": "<我们的信封 JSON>"}]}
    以前 `_collect_records` 只遍历 dict/list、不解析字符串，于是工具签发的证据
    **永远进不了账本**：模型一引用就 `evidence_not_found`，整轮 fail closed。
    """
    from app.gateway.service import _collect_records

    envelope = {
        "schemaVersion": 1,
        "kind": "comparison",
        "status": "ok",
        "data": {"cells": []},
        "evidenceRefs": [{"evidenceId": "ev-1", "dataVersion": "v1"}],
    }
    item = {
        "type": "mcpToolCall",
        "id": "call_1",
        "result": {"content": [{"type": "text", "text": json.dumps(envelope)}]},
    }

    records = _collect_records([item], "evidenceLedger", "evidence", "evidenceRefs")

    assert [record["evidenceId"] for record in records] == ["ev-1"]


def test_gateway_collects_evidence_from_every_tool_result_not_just_the_last() -> None:
    """两条工具结果各带一条证据时，**两条都要进账本**。

    这里曾经只进一条。原因不是"遍历不到"，而是 `visited` 用 `id()` 去重、
    而解析 JSON 字符串会临时造出对象：临时对象被回收后 `id()` 被复用，
    第二条证据的包裹体就被误判成"已经遍历过"而整条跳过。
    实测表现：账本里有 1 条、模型引用的恰好是被丢的那条 → `evidence_not_found`。
    """
    from app.gateway.service import _collect_records

    def item(call_id: str, evidence_id: str) -> dict:
        envelope = {"status": "ok", "data": {}, "evidence": [{"evidenceId": evidence_id}]}
        return {
            "type": "item/completed",
            "item": {
                "type": "McpToolCall",
                "id": call_id,
                "tool": "catalog.list_batches",
                "result": {"content": [{"type": "text", "text": json.dumps(envelope)}]},
            },
        }

    records = _collect_records(
        [item("call_1", "ev-1"), item("call_2", "ev-2")],
        "evidenceLedger",
        "evidence",
        "evidenceRefs",
    )

    assert sorted(record["evidenceId"] for record in records) == ["ev-1", "ev-2"]


@pytest.mark.asyncio
async def test_admission_units_are_flattened_into_usable_rows(monkeypatch) -> None:
    """四层嵌套要摊平成行：模型要的是 (年份, 科类, 批次, 单元编号) 这个四元组。

    层名由**位置**决定——上游在这四层里用的是同一组字段名（value/label/children），
    按字段名认层是认不出来的。
    """
    from app.util import internal_client

    async def filter_list(school_id, area_id):
        return {
            "code": 0,
            "data": [
                {"value": "2025", "label": "2025", "children": [
                    {"value": "N", "label": "综合", "children": [
                        {"value": "17", "label": "第一段", "children": [
                            {"value": "9701372467122640", "label": "北京大学", "code": "1103"},
                        ]},
                    ]},
                ]},
            ],
        }

    monkeypatch.setattr(internal_client, "get_plan_major_filter_list", filter_list)
    backend = InternalClientBackend.__new__(InternalClientBackend)
    backend.tenant_id, backend.chat_session_id, backend.thread_id = "1", "1", "thr"
    backend.current_state_version = 0
    tools = ReadonlyDomainTools(trusted_context(), backend=backend)

    result = await tools.call("catalog.list_admission_units", {"schoolId": "1", "areaId": "330000"})

    assert result["status"] == "ok"
    assert result["data"]["units"] == [
        {
            "year": "2025", "yearLabel": "2025",
            # 科类：**value 拿来查（N/WL/LS）、label 拿来跟用户说（综合/物理/历史）**。
            # 只带 label 的话，江苏传"物理"会查空；只带 value 的话，模型会念代码。
            "subjectType": "N", "subjectLabel": "综合",
            "batch": "17", "batchLabel": "第一段",
            "schoolUnitId": "9701372467122640", "schoolUnitCode": "1103",
            "schoolLabel": "北京大学",
        }
    ]


@pytest.mark.asyncio
async def test_enrollment_plan_requires_a_unit_id() -> None:
    """没有 unit id 就必须拒绝并指出从哪来——它会一路传到上游才报错，
    而那个报错（"招生单位编号不能为空"）在链路上看不出该找谁要。"""
    backend = InternalClientBackend.__new__(InternalClientBackend)
    backend.tenant_id, backend.chat_session_id, backend.thread_id = "1", "1", "thr"
    backend.current_state_version = 0
    tools = ReadonlyDomainTools(trusted_context(), backend=backend)

    result = await tools.call("admission.get_enrollment_plan", {"schoolId": "1"})

    assert result["status"] == "needs_clarification"
    # 六项一起报：上游缺项时**返回空而不是报错**，逐项挤牙膏会让模型连查几年都"0 行"。
    assert result["data"]["missingFields"] == [
        "areaId", "batch", "schoolUnitId", "subjectType", "year",
    ]
    assert "catalog.list_admission_units" in str(result)


@pytest.mark.asyncio
async def test_upstream_error_keeps_code_and_message() -> None:
    """上游的错误码与原文必须带进信封。

    只给一个 `upstream_error` 的话，模型看不出缺的是哪个参数——实测它连调三次
    都因为同一个必填项失败，而失败信息里没有任何可行动的东西。原文里那句
    `admission_source_school_required` 才是它自我纠正的依据。
    """
    from app.util import internal_client

    async def plan(payload, **kwargs):
        return {"code": 400, "msg": "admission_source_school_required", "data": None}

    monkeypatch_target = internal_client.get_enrollment_plan
    internal_client.get_enrollment_plan = plan  # type: ignore[assignment]
    try:
        backend = InternalClientBackend.__new__(InternalClientBackend)
        backend.tenant_id, backend.chat_session_id, backend.thread_id = "1", "1", "thr"
        backend.current_state_version = 0
        tools = ReadonlyDomainTools(trusted_context(), backend=backend)

        result = await tools.call(
            "admission.get_enrollment_plan",
            {
                "schoolUnitId": "9701372467122640",
                "schoolId": "1",
                "areaId": "330000",
                "year": 2025,
                "subjectType": "N",
                "batch": "17",
            },
        )

        assert result["status"] == "upstream_error"
        assert "upstream_code:400" in result["limitations"]
        assert any("admission_source_school_required" in item for item in result["limitations"])
    finally:
        internal_client.get_enrollment_plan = monkeypatch_target  # type: ignore[assignment]


@pytest.mark.asyncio
async def test_eligibility_passes_the_major_in_level3(monkeypatch) -> None:
    """选科资格的三级专业 id 必须落在 **level3** —— 这条曾经是 fail-open。

    Java 侧 `PlanValidationService` 只读 `majors["level3"]`。id 被塞进 level2 时，
    那边的循环一次都不执行、直接 `return true`：**对任何专业都说"选科要求都满足"**。
    这比 fail-closed 更糟——用户会据此填报。
    """
    from app.util import internal_client

    calls: list[dict] = []

    async def avail(tenant_id, session_id, majors):
        calls.append(majors)
        return {"code": 0, "data": False}

    monkeypatch.setattr(internal_client, "check_major_subject_availability", avail)
    backend = InternalClientBackend.__new__(InternalClientBackend)
    backend.tenant_id, backend.chat_session_id, backend.thread_id = "1", "1", "thr"
    backend.current_state_version = 0
    tools = ReadonlyDomainTools(trusted_context(), backend=backend)

    result = await tools.call("admission.check_eligibility", {"majorId": "473"})

    assert calls == [{"level1": [], "level2": [], "level3": ["473"]}]
    # "不合格"必须**说得出**：布尔以前被当成"后端没返回结构化数据"，
    # 于是模型只收到 insufficient_data——合格与否都读不到。
    assert result["status"] == "ok"
    assert result["data"] == {"eligible": False, "checked": "subject_requirement"}


@pytest.mark.asyncio
async def test_eligibility_refuses_without_a_major() -> None:
    """没有专业就没有"资格"可言——问清楚，而不是回一个"合格"。"""
    backend = InternalClientBackend.__new__(InternalClientBackend)
    backend.tenant_id, backend.chat_session_id, backend.thread_id = "1", "1", "thr"
    backend.current_state_version = 0
    tools = ReadonlyDomainTools(trusted_context(), backend=backend)

    result = await tools.call("admission.check_eligibility", {})

    assert result["status"] == "needs_clarification"
    assert result["data"]["missingFields"] == ["majorId"]


@pytest.mark.asyncio
async def test_history_does_not_require_a_major(monkeypatch) -> None:
    """历史分数**不要求** majorId —— 不传才是"有分数"的那条口径。

    上游按 `majorId` 是否非空分流：非空 → 专业级表（该省分数多为 0）；
    空 → 院校/**专业组**级表（投档线在这里）。以前在 major 模式下强制要求
    majorId，等于把唯一能返回数据的查法挡在门外——模型收到
    `needs_clarification: majorId`，而它问的那条本来查得到（北大浙江第一段 707 分/位次 2）。
    """
    from app.util import internal_client

    calls: list[dict] = []

    async def score_line(**kwargs):
        calls.append(kwargs)
        return {"code": 0, "data": [], "evidence": []}

    monkeypatch.setattr(internal_client, "query_school_major_score_line", score_line)
    backend = InternalClientBackend.__new__(InternalClientBackend)
    backend.tenant_id, backend.chat_session_id, backend.thread_id = "1", "1", "thr"
    backend.current_state_version = 0
    tools = ReadonlyDomainTools(trusted_context(), backend=backend)

    result = await tools.call(
        "admission.get_history",
        {"areaId": "330000", "batch": "17", "schoolId": "1", "year": 2024, "subjectType": "N"},
    )

    # 关键断言：**打到了后端**（而不是在入口被 majorId 挡住）。
    assert calls and calls[0]["major_id"] == ""
    assert "missing history scope" not in str(result)


async def test_unit_level_history_is_labelled_as_such(monkeypatch) -> None:
    """不传 majorId 时必须在返回里标明口径：这是院校/专业组级投档线，不是专业级。"""
    from app.util import internal_client

    async def score_line(**kwargs):
        return {
            "code": 0,
            "data": [{"year": 2024, "name": "北京大学05专业组", "minScore": "686", "minPos": "126"}],
            "evidence": [{"evidenceId": "ev-1"}],
        }

    monkeypatch.setattr(internal_client, "query_school_major_score_line", score_line)
    backend = InternalClientBackend.__new__(InternalClientBackend)
    backend.tenant_id, backend.chat_session_id, backend.thread_id = "1", "1", "thr"
    backend.current_state_version = 0
    tools = ReadonlyDomainTools(trusted_context(), backend=backend)

    result = await tools.call(
        "admission.get_history",
        {"areaId": "320000", "batch": "01", "schoolId": "1", "year": 2025, "subjectType": "WL"},
    )

    assert result["status"] == "ok"
    assert "caliber_unit_level_not_major" in result["limitations"]


@pytest.mark.asyncio
async def test_charter_picks_the_year_and_converts_html(monkeypatch) -> None:
    """章程：按年份选题、正文转纯文本、截断要标出来。

    正文是 HTML（实测 95KB、去标签 5581 字），直接给模型既费预算又把
    `&nbsp;` 抄进回答。上限之外还要留痕：截断了必须能看出来。
    """
    from app.util import internal_client

    async def news_page(school_id, current=1, size=20):
        return {
            "code": 0,
            "data": {
                "records": [
                    {"id": 2, "title": "北京大学2026年本科招生章程"},
                    {"id": 1, "title": "北京大学2025年本科招生章程"},
                ]
            },
        }

    asked: list[Any] = []

    async def news_detail(news_id, **kwargs):
        asked.append(news_id)
        return {
            "code": 0,
            "data": {
                "id": news_id,
                "schoolId": 1,
                "schoolName": "北京大学",
                "title": "北京大学2025年本科招生章程",
                "displayTime": "2025-05-29 16:14:00",
                "content": "<p>第一章&nbsp;总则</p><p>第一条 为深入贯彻…</p>",
            },
            "evidence": [{"evidenceId": "ev-charter"}],
        }

    monkeypatch.setattr(internal_client, "get_school_news", news_page)
    monkeypatch.setattr(internal_client, "get_school_news_detail", news_detail)
    backend = InternalClientBackend.__new__(InternalClientBackend)
    backend.tenant_id, backend.chat_session_id, backend.thread_id = "1", "1", "thr"
    backend.current_state_version = 0
    tools = ReadonlyDomainTools(trusted_context(), backend=backend)

    result = await tools.call("admission.get_charter", {"schoolId": "1", "year": "2025"})

    assert asked == [1]  # 按标题里的年份选到了 2025 那条
    assert result["status"] == "ok"
    assert result["data"]["contentText"] == "第一章 总则\n第一条 为深入贯彻…"
    assert [item["evidenceId"] for item in result["evidenceRefs"]] == ["ev-charter"]
    assert "platform_copy_check_school_site" in result["limitations"]


@pytest.mark.asyncio
async def test_charter_says_not_in_catalog_rather_than_not_exists(monkeypatch) -> None:
    """平台没收录 ≠ 该校没有章程 —— 措辞不能把两件事说成一件。"""
    from app.util import internal_client

    async def news_page(school_id, current=1, size=20):
        return {"code": 0, "data": {"records": []}}

    monkeypatch.setattr(internal_client, "get_school_news", news_page)
    backend = InternalClientBackend.__new__(InternalClientBackend)
    backend.tenant_id, backend.chat_session_id, backend.thread_id = "1", "1", "thr"
    backend.current_state_version = 0
    tools = ReadonlyDomainTools(trusted_context(), backend=backend)

    result = await tools.call("admission.get_charter", {"schoolId": "999999"})

    assert result["status"] == "empty"
    assert result["limitations"] == ["charter_not_in_platform_catalog"]


def test_every_capability_has_a_progress_label() -> None:
    """每个能调用的工具都要有进度标签——**新增工具漏加标签是个真实踩过的坑**。

    没有标签时 `adapt_codex_item` 会把工具名掩成 `domain`（"未知工具只给统一占位"）：
    用户看不到正在做什么，**验收脚本也断言不了用了哪个工具**（实测：
    `admission.get_charter` 漏标签，评估器只能看到 `domain`）。
    """
    from app.gateway.ui_events import TOOL_LABELS
    from app.mcp_server.tools_readonly import CAPABILITIES

    assert set(CAPABILITIES) <= set(TOOL_LABELS), sorted(set(CAPABILITIES) - set(TOOL_LABELS))


def test_authoritative_evidence_must_carry_a_java_signed_id() -> None:
    """设计文档 5.1：`authoritative` 只能由 Java 盖（P1b-2 步骤 4 的防回归护栏）。

    自铸证据是个"看起来能跑"的失败模式——链路全绿，只是"权威"变成了自称。
    这里构造的正是那个形状：id 是 `admission-unit:…`（Agent 自铸的旧写法），
    却贴着 `sourceLevel=authoritative`。
    """
    from app.mcp_server import response

    with pytest.raises(ValueError, match="self-minted"):
        response.ok(
            {"items": []},
            kind="history",
            state_version=1,
            evidence=[
                {
                    "evidenceId": "admission-unit:x:unknown",
                    "sourceLevel": "authoritative",
                    "dataVersion": "unknown",
                }
            ],
        )


def test_java_signed_evidence_passes_the_guard() -> None:
    """对照：真 Java 形状（`ev_` 前缀）必须原样通过——护栏不能把正常的也拦掉。"""
    from app.mcp_server import response

    signed = {
        "evidenceId": "ev_01M32Y0A8Q0X7V6T5S4R3P2N1M",
        "sourceLevel": "authoritative",
        "dataVersion": "fc7bd2c8d3cd6dad653afc03d4c7b40a",
        "sourceSystem": "gaotu.batchList",
    }

    result = response.ok({"items": []}, kind="history", state_version=1, evidence=[signed])

    assert result["evidenceRefs"] == [signed]
