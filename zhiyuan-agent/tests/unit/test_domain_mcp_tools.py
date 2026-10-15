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
async def test_recommendation_tool_signs_its_product_with_a_scoped_artifact_ref(
    monkeypatch,
) -> None:
    """推荐类工具的结果里要有**可引用的产物**，而且章（会话/线程）在签发点盖上。

    2026-10-08 事故：契约要求 recommendation/review 输出必须带 `artifactRefs`
    （`contracts.py`），而 `recommendation.preview_majors` 当时只回了一串专业方向、
    没有任何可引用的产物 id；模型在补一轮里自己编了一个
    `session:10041979:major_direction_ranking:v3`，收集器又把模型自己写的 JSON 当成了
    产物记录（它带 artifactId），而那条记录没有会话章 → `artifact_scope_violation`
    → 整轮**不可恢复**地失败（用户看到"引擎暂时不可用"）。
    id 不签发模型就只能编，而会话身份只有受信 binding 有——所以签发与盖章必须同点。
    """
    from app.util import internal_client

    async def preview_majors(chat_session_id, *, top_n=8):
        return {
            "code": 0,
            "msg": "ok",
            "data": {
                "topN": top_n,
                "items": [{"major_id": "81", "major": "口腔医学类", "score": 72.8}],
                "limitations": [],
            },
        }

    monkeypatch.setattr(internal_client, "preview_majors", preview_majors)

    backend = InternalClientBackend.__new__(InternalClientBackend)
    backend.tenant_id = "tenant-1"
    backend.chat_session_id = "101"
    backend.thread_id = "thr_test"
    backend.current_state_version = 42
    tools = ReadonlyDomainTools(trusted_context(), backend=backend, current_state_version=42)

    result = await tools.call(
        "recommendation.preview_majors",
        # 冒充身份：章上的会话只能来自受信 binding。
        {"topN": 8, "chatSessionId": "888", "sessionId": "888", "userId": "999"},
    )

    record = result["artifacts"][0]
    assert record["artifactType"] == "candidate"
    assert record["stateVersion"] == 42
    assert record["tenantId"] == "tenant-1"
    assert record["sessionId"] == "101"
    assert record["threadId"] == "thr_test"

    # 确定性：同工具同入参 → 同一个 id。补一轮里模型抄的是**首轮**那个 id，
    # 首轮事件里必须查得到同一个名字（随机 id 会让"一份产物两个名字"无声发生）。
    same = await tools.call("recommendation.preview_majors", {"topN": 8})
    other = await tools.call("recommendation.preview_majors", {"topN": 5})
    assert same["artifacts"][0]["artifactId"] == record["artifactId"]
    assert other["artifacts"][0]["artifactId"] != record["artifactId"]


@pytest.mark.asyncio
async def test_only_successful_product_shaped_results_carry_an_artifact_ref(monkeypatch) -> None:
    """产物引用不是"每个结果都贴一张"：不可用、失败、查询类都不签发。

    - `unavailable=true`（画像缺分数）时**没有产物**：发一条"指向空结果"的引用，
      正是这些工具如实标不可用要防的事（把"查不到"包装成"这就是结果"）；
    - 失败（`backend_unavailable`）没有产物：没有产物就是没有；
    - 查询类（catalog）不签发：数据是从上游读来的，不是本回合**生产**的东西；
    - 比较形状（comparison）同样签发，类型跟着 kind 走。
    """
    from app.util import internal_client

    unavailable_backend = InternalClientBackend.__new__(InternalClientBackend)
    unavailable_backend.tenant_id = "tenant-1"
    unavailable_backend.chat_session_id = "101"
    unavailable_backend.thread_id = "thr_test"
    unavailable_backend.current_state_version = 42
    tools = ReadonlyDomainTools(trusted_context(), backend=unavailable_backend)

    async def preview_majors_unavailable(chat_session_id, *, top_n=8):
        return {"code": 0, "msg": "session_score_missing", "data": None}

    monkeypatch.setattr(internal_client, "preview_majors", preview_majors_unavailable)
    unavailable = await tools.call("recommendation.preview_majors", {})
    assert unavailable["data"]["unavailable"] is True
    assert "artifacts" not in unavailable

    async def preview_majors_broken(chat_session_id, *, top_n=8):
        raise RuntimeError("rank unreachable")

    monkeypatch.setattr(internal_client, "preview_majors", preview_majors_broken)
    failed = await tools.call("recommendation.preview_majors", {"topN": 3})
    assert failed["status"] == "backend_unavailable"
    assert "artifacts" not in failed

    async def get_batch_info(*args, **kwargs):
        return {"code": 0, "msg": "ok", "data": {"batchList": [{"batch": "17", "name": "第一段"}]}}

    monkeypatch.setattr(internal_client, "get_batch_info", get_batch_info)
    catalog = await tools.call("catalog.list_batches", {"areaId": "340000"})
    assert catalog["status"] == "ok"
    assert "artifacts" not in catalog

    async def compare_candidate_pool(tenant_id, chat_session_id, entity_ids, dimensions=None):
        return {
            "code": 0,
            "msg": "ok",
            "data": {
                "entities": [{"entityId": entity_ids[0]}, {"entityId": entity_ids[1]}],
                "dimensions": [],
                "cells": [],
                "limitations": [],
            },
        }

    monkeypatch.setattr(internal_client, "compare_candidate_pool", compare_candidate_pool)
    comparison = await tools.call(
        "recommendation.compare_candidates", {"entityIds": ["v-1", "v-2"]}
    )
    assert comparison["status"] == "ok"
    assert comparison["artifacts"][0]["artifactType"] == "comparison"


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
async def test_production_mcp_runner_rebases_to_a_snapshot_moved_during_the_turn(monkeypatch) -> None:
    """2026-10-14：回合内版本前进（候选池生成）→ **有界重基**后按新版本续读。

    语义在 2026-10-14 变更（会话 10041982）：以前任何前进都返回 `stale_state`、
    余下每个读全被挡死；现在**连续两次读到同一版本**（写已落定）即按新版本继续。
    这条同时把"有界"钉死：一次落定只多读一次快照（1 次首读 + 1 次确认）。
    """
    from app.mcp_server import server as mcp_server

    reads: list[int] = []

    class Registry:
        async def resolve(self, *, thread_id, capability):
            return trusted_context(snapshot_version=77)

    async def snapshot(*args, **kwargs):
        reads.append(len(reads))
        return {"data": {"snapshotVersion": 78}}

    class Backend:
        def __init__(self, **kwargs):
            pass

        async def resolve(self, **kwargs):
            return {"data": {"entityId": kwargs["query"]}}

    monkeypatch.setattr(mcp_server.internal_client, "get_conversation_turn_snapshot", snapshot)
    monkeypatch.setattr(mcp_server, "InternalClientBackend", Backend)
    result = await mcp_server._call_domain_tool(
        "entity.resolve",
        {"query": "浙江大学"},
        metadata={"threadId": "thr_test"},
        binding_registry=Registry(),
    )

    assert result["status"] == "ok"
    # 信封的版本戳来自 ReadonlyDomainTools 的 `current_state_version`：
    # 78 证明干活的那个 runner 就是按重基后的版本构造的。
    assert result["stateVersion"] == 78, "重基后的读必须以**新版本**签发"
    assert len(reads) == 2, "重试有界：首读一次 + 落定确认一次，不允许反复读"


@pytest.mark.asyncio
async def test_production_mcp_runner_fails_closed_while_the_snapshot_keeps_moving(monkeypatch) -> None:
    """版本**还在动**（真并发写没停）→ 有界试用完仍 fail-closed，绝不拿中间版本当最新。"""
    from app.mcp_server import server as mcp_server

    reads: list[int] = []
    versions = [78, 79, 80]

    class Registry:
        async def resolve(self, *, thread_id, capability):
            return trusted_context(snapshot_version=77)

    async def snapshot(*args, **kwargs):
        reads.append(len(reads))
        return {"data": {"snapshotVersion": versions[min(len(reads) - 1, len(versions) - 1)]}}

    monkeypatch.setattr(mcp_server.internal_client, "get_conversation_turn_snapshot", snapshot)
    monkeypatch.setattr(
        mcp_server,
        "ReadonlyDomainTools",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("must not construct a domain runner while the snapshot keeps moving")
        ),
    )
    result = await mcp_server._call_domain_tool(
        "entity.resolve",
        {"query": "浙江大学"},
        metadata={"threadId": "thr_test"},
        binding_registry=Registry(),
    )

    assert result["status"] == "stale_state"
    assert result["stateVersion"] == 80
    assert result["evidenceRefs"] == []
    assert len(reads) == 3, "重试有界：1 次首读 + 至多 2 次落定尝试"


@pytest.mark.asyncio
async def test_production_mcp_runner_fails_closed_when_the_rebase_read_fails(monkeypatch) -> None:
    """重基途中读不到权威快照 → `state_version_unavailable`（不放行、也不说成 stale）。"""
    from app.mcp_server import server as mcp_server

    calls = {"count": 0}

    class Registry:
        async def resolve(self, *, thread_id, capability):
            return trusted_context(snapshot_version=77)

    async def snapshot(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] > 1:
            raise RuntimeError("snapshot backend down")
        return {"data": {"snapshotVersion": 78}}

    monkeypatch.setattr(mcp_server.internal_client, "get_conversation_turn_snapshot", snapshot)
    result = await mcp_server._call_domain_tool(
        "entity.resolve",
        {"query": "浙江大学"},
        metadata={"threadId": "thr_test"},
        binding_registry=Registry(),
        fallback_tool_runner=None,
    )

    assert result["status"] == "state_version_unavailable"
    assert calls["count"] == 2


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


def _plan_tools() -> ReadonlyDomainTools:
    """真实方案读路径：真 Backend + 受信 binding（两源 I/O 由 `_install_plan_sources` 替身）。"""
    return ReadonlyDomainTools(
        trusted_context(),
        backend=InternalClientBackend(tenant_id="tenant-1", chat_session_id="101"),
    )


def _install_plan_sources(monkeypatch, *, ordered, working):
    """装配两条方案源替身；实参是 Exception 实例时该源以异常失败。返回调用记录。"""
    calls: list[tuple] = []

    async def get_planning_ordered_plan(thread_id, tenant_id):
        calls.append(("ordered", thread_id, tenant_id))
        if isinstance(ordered, BaseException):
            raise ordered
        return ordered

    async def get_working_plan(thread_id, tenant_id):
        calls.append(("working", thread_id, tenant_id))
        if isinstance(working, BaseException):
            raise working
        return working

    monkeypatch.setattr(
        "app.util.internal_client.get_planning_ordered_plan", get_planning_ordered_plan
    )
    monkeypatch.setattr("app.util.internal_client.get_working_plan", get_working_plan)
    return calls


@pytest.mark.asyncio
async def test_internal_backend_keeps_tenant_and_session_server_owned(monkeypatch) -> None:
    calls = _install_plan_sources(
        monkeypatch,
        ordered={"code": 0, "data": {"items": [], "units": []}},
        working={"code": 0, "data": {"items": [], "units": []}},
    )
    backend = InternalClientBackend(tenant_id=7, chat_session_id=101)

    result = await backend.get_current_plan(sessionId=999, userId=888)

    # 模型传进来的 sessionId/userId 一律不采信：租户与会话都取自**可信 binding**。
    # tenant 也在这里断言，因为路径里的 tenant 曾经是硬编码的 1——那会让
    # tenant 非 1 的会话安静地读到别人的志愿表。
    # 方案读**排序方案优先**：空排序方案回落工作台方案，两条链都带受信身份。
    assert calls == [("ordered", 101, 7), ("working", 101, 7)]
    assert result["planSource"] == "workingPlan"
    assert result["plan"]["data"] == {"items": [], "units": []}


# §五-47 实拍形状：OrderedItemDTO + OrderedUnitDTO（含单元级 majorItems）。
ORDERED_PLAN_PAYLOAD: dict = {
    "items": [
        {
            "position": 1,
            "volunteerId": "u1_1",
            "tier": "冲",
            "schoolName": "浙江大学",
            "majorName": "计算机科学与技术",
            "unitId": "unit-1",
            "locked": False,
            "pinned": True,
            "pinnedPosition": 1,
            "orderedBy": "manual",
            "orderReason": "用户指定",
            "source": "candidate",
        },
        {
            "position": 2,
            "volunteerId": "u2_1",
            "tier": "稳",
            "schoolName": "浙江工业大学",
            "majorName": "软件工程",
        },
    ],
    "units": [
        {
            "position": 1,
            "unitId": "unit-1",
            "planSchoolDataId": "u1",
            "schoolId": "s1",
            "schoolUnitCode": "3301",
            "tier": "冲",
            "schoolName": "浙江大学",
            "provinceName": "浙江",
            "cityName": "杭州",
            "schoolNature": "公办",
            "admissionRatio": 45.5,
            "finalScore": 661.0,
            "schoolEnrollRatio": 0.92,
            "totalMajorCount": 1,
            "majorItems": [
                {
                    "volunteerId": "u1_1",
                    "majorId": "m-1",
                    "majorName": "计算机科学与技术",
                    "majorCode": "080901",
                    "tier": "冲",
                    "tuitionPerYear": 6900,
                    "admissionRatio": 42.0,
                    "finalScore": 663.0,
                }
            ],
        }
    ],
    "summary": {"unitTotal": 1, "total": 2},
    "generationMode": "auto",
}


@pytest.mark.asyncio
async def test_plan_read_prefers_ordered_plan_and_reveals_items_and_units(monkeypatch) -> None:
    """方案读的条目明细必须真的读得到：位置/院校/专业/校区文本/学费/录取率。"""
    calls = _install_plan_sources(
        monkeypatch,
        ordered={
            "code": 0,
            "data": ORDERED_PLAN_PAYLOAD,
            "evidence": [{"evidenceId": "ev_plan_1"}],
        },
        working=AssertionError("排序方案有内容时不该回落工作台方案"),
    )

    result = await _plan_tools().call(
        "admission.get_current_plan", {"sessionId": 999, "userId": 888}
    )

    assert result["kind"] == "orderedPlan"
    assert result["status"] == "ok"
    assert result["evidenceRefs"] == [{"evidenceId": "ev_plan_1"}]

    first_item = result["data"]["items"][0]
    assert first_item["position"] == 1
    assert first_item["volunteerId"] == "u1_1"
    assert first_item["tier"] == "冲"
    assert first_item["schoolName"] == "浙江大学"
    assert first_item["majorName"] == "计算机科学与技术"
    assert first_item["unitId"] == "unit-1"
    # 上游没给的键不出现（不补默认值）；白名单外的噪声字段不透出。
    assert "cityName" not in first_item
    assert "orderReason" not in first_item

    unit = result["data"]["units"][0]
    assert unit["unitId"] == "unit-1"
    assert unit["cityName"] == "杭州"
    assert unit["schoolName"] == "浙江大学"
    assert unit["schoolNature"] == "公办"
    assert unit["admissionRatio"] == 45.5
    assert unit["finalScore"] == 661.0
    assert unit["majorItems"][0] == {
        "volunteerId": "u1_1",
        "majorId": "m-1",
        "majorName": "计算机科学与技术",
        "majorCode": "080901",
        "tier": "冲",
        "tuitionPerYear": 6900,
        "admissionRatio": 42.0,
        "finalScore": 663.0,
    }
    # 模型塞的 sessionId/userId 一律不采信：两条链都用受信 binding 的会话与租户。
    assert calls == [("ordered", "101", "tenant-1")]
    # 方案读**不再走招生事实校验**：没有 major_required 墙。
    assert "major_required" not in result["limitations"]


@pytest.mark.asyncio
async def test_plan_read_falls_back_to_working_plan_when_ordered_plan_unavailable(
    monkeypatch,
) -> None:
    """排序方案不可用（调用失败/传输失败/上游错误码/还没生成）→ 回落工作台方案。"""
    working_payload = {
        "code": 0,
        "data": {
            "items": [
                {
                    "volunteerId": "u1_1",
                    "tier": "稳",
                    "schoolName": "浙江工业大学",
                    "majorName": "软件工程",
                    "source": "candidate",
                }
            ],
            "units": [
                {
                    "unitId": "unit-9",
                    "tier": "稳",
                    "schoolName": "浙江工业大学",
                    "majorItems": [
                        {
                            "majorId": "m-9",
                            "majorName": "软件工程",
                            "tuitionPerYear": 5300,
                            "admissionRatio": 66.0,
                            "finalScore": 601.0,
                        }
                    ],
                }
            ],
        },
    }
    unavailable_sources = [
        RuntimeError("ordered plan unreachable"),  # 调用抛异常
        {"error": "connection refused", "success": False, "data": {}},  # 传输失败形状
        {"code": 50001, "msg": "内部错误", "data": None},  # 上游错误码
        {"code": 0, "data": {"items": [], "units": []}},  # 还没生成（生成前正常态）
        {"code": 0, "data": {"items": [], "units": [], "summary": {}}},
    ]
    for ordered in unavailable_sources:
        calls = _install_plan_sources(monkeypatch, ordered=ordered, working=working_payload)

        result = await _plan_tools().call("planning.get_working_plan", {})

        assert result["kind"] == "workingPlan", ordered
        assert result["status"] == "ok", ordered
        assert [item["volunteerId"] for item in result["data"]["items"]] == ["u1_1"], ordered
        assert result["data"]["units"][0]["unitId"] == "unit-9", ordered
        assert result["data"]["units"][0]["majorItems"][0]["majorId"] == "m-9", ordered
        assert calls == [("ordered", "101", "tenant-1"), ("working", "101", "tenant-1")], ordered


@pytest.mark.asyncio
async def test_empty_plan_reads_as_a_normal_ok_result_not_a_limitation_wall(monkeypatch) -> None:
    """空方案是正常态：items:[]、无 limitation 墙，更不许造 major_required 占位码。"""
    _install_plan_sources(
        monkeypatch,
        ordered={"code": 0, "data": {"items": [], "units": []}},
        working={"code": 0, "data": {"items": [], "units": [], "summary": {"unitTotal": 0}}},
    )

    result = await _plan_tools().call("admission.get_current_plan", {})

    assert result["status"] == "ok"
    assert result["data"] == {"items": [], "units": []}
    assert result["limitations"] == []


@pytest.mark.asyncio
async def test_plan_rows_never_go_through_admission_fact_validation(monkeypatch) -> None:
    """§五-47 决定性回归：DraftItemDTO 行（无 majorId/planMajorDataId）逐行透出。

    修前这些行被当**招生事实**校验 → 每行一条 `major_required`、80 行全弃；
    修后 `validate_admission_fact` 一次都不会被方案读触发。
    """
    from app.mcp_server import tools_readonly

    validated: list[object] = []
    real_validate = tools_readonly.validate_admission_fact

    def spy(value):
        validated.append(value)
        return real_validate(value)

    monkeypatch.setattr("app.mcp_server.tools_readonly.validate_admission_fact", spy)
    draft_items = [
        {
            "volunteerId": f"v{i}",
            "tier": "冲",
            "schoolName": f"学校{i}",
            "majorName": f"专业{i}",
            "locked": False,
            "source": "candidate",
        }
        for i in range(80)
    ]
    _install_plan_sources(
        monkeypatch,
        ordered={"code": 0, "data": {"items": [], "units": []}},
        working={"code": 0, "data": {"items": draft_items, "units": []}},
    )

    result = await _plan_tools().call("admission.get_current_plan", {})

    assert validated == []
    assert len(result["data"]["items"]) == 80
    assert result["data"]["items"][0]["schoolName"] == "学校0"
    assert result["data"]["items"][79]["majorName"] == "专业79"
    assert result["limitations"] == []
    assert "major_required" not in json.dumps(result)


def test_plan_read_description_states_detail_fields_and_the_empty_is_normal_rule() -> None:
    """工具描述是模型实际读到的那句话：明细字段与"空方案是正常态"都要写死，
    两个别名必须给同一句话（同一个工具，不许两份说法分叉）。"""
    from app.mcp_server.server import TOOL_DESCRIPTIONS, tool_listing

    description = TOOL_DESCRIPTIONS["admission.get_current_plan"]
    for phrase in (
        "position",
        "schoolName",
        "majorName",
        "unitId",
        "cityName",
        "schoolNature",
        "tuitionPerYear",
        "admissionRatio",
        "学费",
        "录取率",
        "orderedPlan",
        "items:[]",
        "正常态",
    ):
        assert phrase in description, f"工具描述缺少明细口径：{phrase}"

    listed = {entry["name"]: entry for entry in tool_listing()}
    assert listed["planning.get_working_plan"]["description"] == description


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


@pytest.mark.asyncio
async def test_preview_majors_uses_trusted_identity_caps_top_n_and_maps_rank_dimensions(
    monkeypatch,
) -> None:
    """专业方向推荐只读纵切的三条合同：**受信身份、topN 硬上限 8、rank 维度原样映射**。

    - 模型塞进来的 chatSessionId/sessionId/userId 必须被丢掉——会话身份只能来自
      受信 binding（否则它能把任何会话的画像装进自己的回合）；
    - 一次最多 8 条（切片边界：拿到的只是按综合分排的 topN，不能概括全部方向）；
    - 四个维度分照 Java 实体字段名（gender_index/satisfy_index/salary_avg/hot_index）
      原样带出，`state_mutation=False`：预览不改任何状态。
    """
    from app.util import internal_client

    calls: list[dict] = []

    async def preview_majors(chat_session_id, *, top_n=8):
        calls.append({"chat_session_id": chat_session_id, "top_n": top_n})
        return {
            "code": 0,
            "msg": "ok",
            "data": {
                "chatSessionId": 900047,
                "topN": 8,
                "items": [
                    {
                        "major_id": f"m-{index}",
                        "major": f"专业方向{index}",
                        "score": 100.0 - index,
                        "gender_index": 70.0,
                        "satisfy_index": 80.0,
                        "salary_avg": 72.5,
                        "hot_index": 91.0,
                    }
                    for index in range(1, 9)
                ],
                "limitations": [],
            },
        }

    monkeypatch.setattr(internal_client, "preview_majors", preview_majors)

    backend = InternalClientBackend.__new__(InternalClientBackend)
    backend.tenant_id = "1"
    backend.chat_session_id = "900047"
    backend.thread_id = "thr"
    backend.current_state_version = 0
    tools = ReadonlyDomainTools(trusted_context(), backend=backend)

    result = await tools.call(
        "recommendation.preview_majors",
        {
            "topN": 100,
            # 冒充身份：必须被丢掉（backend 只认受信 binding 的会话）。
            "chatSessionId": "888",
            "sessionId": "888",
            "userId": "999",
        },
    )

    # 上游只按受信会话调一次；topN 100 截断成硬上限 8。
    assert calls == [{"chat_session_id": "900047", "top_n": 8}]
    assert result["kind"] == "candidate"
    assert result["status"] == "ok"
    item = result["data"]["items"][0]
    assert item["name"] == "专业方向1"
    assert item["major_id"] == "m-1"
    assert item["score"] == 99.0
    assert item["dimensions"] == {
        "gender_index": 70.0,
        "satisfy_index": 80.0,
        "salary_avg": 72.5,
        "hot_index": 91.0,
    }
    assert result["data"]["topN"] == 8
    # 条数触顶 = 可能还有更多：这是给模型的边界声明，不是"只有这 8 个方向"。
    assert result["data"]["returned_items_are_sample"] is True
    assert result["data"]["state_mutation"] is False


@pytest.mark.asyncio
async def test_preview_majors_surfaces_unavailable_reason_instead_of_faking_items(
    monkeypatch,
) -> None:
    """画像缺分数：Java 如实回 `data:null + msg=session_score_missing`（业务码 0）。

    工具要把它转成 `unavailable=true` + 原因 + limitation——**不许拿热度榜顶替、
    不许编一个空推荐列表**。`_preserve_envelope` 会丢掉 `msg`，所以原因码必须从
    **原始响应**取：不然"为什么不可用"就只剩一句空话。
    """
    from app.util import internal_client

    async def preview_majors(chat_session_id, *, top_n=8):
        return {"code": 0, "msg": "session_score_missing", "data": None}

    monkeypatch.setattr(internal_client, "preview_majors", preview_majors)

    backend = InternalClientBackend.__new__(InternalClientBackend)
    backend.tenant_id = "1"
    backend.chat_session_id = "900047"
    backend.thread_id = "thr"
    backend.current_state_version = 0
    tools = ReadonlyDomainTools(trusted_context(), backend=backend)

    result = await tools.call("recommendation.preview_majors", {})

    # "没有这份画像"不是查询失败（Java 业务码 0），但必须如实标注不可用。
    assert result["status"] == "ok"
    assert result["data"]["unavailable"] is True
    assert result["data"]["reason"] == "session_score_missing"
    assert result["data"]["items"] == []
    assert result["data"]["returned_items_are_sample"] is False
    assert result["data"]["state_mutation"] is False
    assert "major_recommend_unavailable:session_score_missing" in result["limitations"]


@pytest.mark.asyncio
async def test_preview_majors_transport_error_is_backend_unavailable_not_an_empty_list(
    monkeypatch,
) -> None:
    """传输层失败（HttpClient 的 `{"error": …, "success": False}` 形状）必须是
    `backend_unavailable`——**不是**一个空推荐列表：'查不到'与'没有'是两件事，
    把前者包成后者会让模型对用户说"没有适合你的方向"。"""
    from app.util import internal_client

    async def preview_majors(chat_session_id, *, top_n=8):
        return {"error": "connection refused", "success": False, "data": {}}

    monkeypatch.setattr(internal_client, "preview_majors", preview_majors)

    backend = InternalClientBackend.__new__(InternalClientBackend)
    backend.tenant_id = "1"
    backend.chat_session_id = "900047"
    backend.thread_id = "thr"
    backend.current_state_version = 0
    tools = ReadonlyDomainTools(trusted_context(), backend=backend)

    result = await tools.call("recommendation.preview_majors", {"topN": 3})

    assert result["status"] == "backend_unavailable"
    assert "connection refused" in result["data"]["message"]


def _compare_backend() -> InternalClientBackend:
    backend = InternalClientBackend.__new__(InternalClientBackend)
    backend.tenant_id = "1"
    backend.chat_session_id = "900047"
    backend.thread_id = "thr"
    backend.current_state_version = 0
    return backend


def _comparable_entity(entity_id: str, batch: str = "17") -> dict:
    """一份**口径齐全**的候选实体：五个口径字段全给，值来自候选池行。"""
    return {
        "entityId": entity_id,
        "schoolId": f"s-{entity_id}",
        "schoolName": f"学校{entity_id}",
        "admissionYear": 2026,
        "areaId": "330000",
        "batch": batch,
        "admissionMode": "major",
        "rateUnit": "percent",
    }


@pytest.mark.asyncio
async def test_compare_candidates_uses_trusted_identity_and_returns_read_only_envelope(
    monkeypatch,
) -> None:
    """候选比较只读纵切的四条合同：**受信身份、真实载入、只读声明、信封形状**。

    - 模型塞进来的 tenantId/sessionId/chatSessionId 必须被丢掉——否则它能把任何
      会话的候选装进自己的回合（身份只能来自受信 binding）；
    - 值由 Java 从会话候选池真实载入：工具只把 entityId 原样送去，cells 原样带出
      （模型没有机会往矩阵里塞数字）；
    - `state_mutation=False`：比较不改任何状态（Java 侧版本号实证在真栈 E2E）。
    """
    from app.util import internal_client

    calls: list[dict] = []

    async def compare_candidate_pool(tenant_id, chat_session_id, entity_ids, dimensions=None):
        calls.append(
            {
                "tenant_id": tenant_id,
                "chat_session_id": chat_session_id,
                "entity_ids": entity_ids,
                "dimensions": dimensions,
            }
        )
        return {
            "code": 0,
            "msg": "success",
            "data": {
                "entities": [
                    _comparable_entity("v1"),
                    _comparable_entity("v2"),
                ],
                "dimensions": ["finalScore", "cityName"],
                "cells": [
                    {"entityId": "v1", "dimension": "finalScore", "value": 88.5,
                     "unit": "score", "source": "candidatePool.finalScore"},
                    {"entityId": "v2", "dimension": "finalScore", "value": 90.0,
                     "unit": "score", "source": "candidatePool.finalScore"},
                    {"entityId": "v1", "dimension": "cityName", "value": "杭州",
                     "source": "candidatePool.cityName"},
                    {"entityId": "v2", "dimension": "cityName", "value": "上海",
                     "source": "candidatePool.cityName"},
                ],
                "unavailableDimensions": [],
                "limitations": [],
            },
        }

    monkeypatch.setattr(internal_client, "compare_candidate_pool", compare_candidate_pool)

    tools = ReadonlyDomainTools(trusted_context(), backend=_compare_backend())

    result = await tools.call(
        "recommendation.compare_candidates",
        {
            "entityIds": ["v1", "v2"],
            "dimensions": ["finalScore", "cityName"],
            # 冒充身份：必须被 `_trusted_arguments` 丢掉。
            "tenantId": "999",
            "sessionId": "888",
            "chatSessionId": "777",
        },
    )

    assert result["kind"] == "comparison"
    assert result["status"] == "ok"
    assert calls == [
        {
            "tenant_id": "1",
            "chat_session_id": "900047",
            "entity_ids": ["v1", "v2"],
            "dimensions": ["finalScore", "cityName"],
        }
    ]
    data = result["data"]
    assert [entity["entityId"] for entity in data["entities"]] == ["v1", "v2"]
    assert data["dimensions"] == ["finalScore", "cityName"]
    score_cell = next(
        cell
        for cell in data["cells"]
        if cell["dimension"] == "finalScore" and cell["entityId"] == "v1"
    )
    assert score_cell["value"] == 88.5
    assert score_cell["source"] == "candidatePool.finalScore"
    assert data["unavailable_dimensions"] == []
    assert data["state_mutation"] is False
    assert result["limitations"] == []


@pytest.mark.asyncio
async def test_compare_candidates_requires_two_to_five_entity_ids(monkeypatch) -> None:
    """少于 2 不是比较、多于 5 表格读不过来：非法入参在工具入口挡住，**不打后端**。"""
    from app.util import internal_client

    calls: list = []

    async def compare_candidate_pool(*args, **kwargs):
        calls.append((args, kwargs))
        return {"code": 0, "msg": "ok", "data": {}}

    monkeypatch.setattr(internal_client, "compare_candidate_pool", compare_candidate_pool)

    tools = ReadonlyDomainTools(trusted_context(), backend=_compare_backend())

    too_few = await tools.call("recommendation.compare_candidates", {"entityIds": ["v1"]})
    assert too_few["status"] == "needs_clarification"
    assert too_few["data"]["missingFields"] == ["entityIds"]

    too_many = await tools.call(
        "recommendation.compare_candidates",
        {"entityIds": ["v1", "v2", "v3", "v4", "v5", "v6"]},
    )
    assert too_many["status"] == "needs_clarification"

    none_given = await tools.call("recommendation.compare_candidates", {})
    assert none_given["status"] == "needs_clarification"

    assert calls == []


@pytest.mark.asyncio
async def test_compare_candidates_reports_unwired_dimensions_and_missing_ids(monkeypatch) -> None:
    """未接线维度与找不到的 ID 都**如实标注**，不静默丢。

    - 名单外的维度（`riskFlags`）进 `unavailable_dimensions` +
      `dimension_source_not_wired:<dim>`，且**不送到 Java**（Java 会 400，
      到了也只是一个错误码，模型看不到"这个维度不够数据"）；
    - Java 侧 `entity_not_found:v9` 的 limitations 原样带出——丢一个 ID 而返回
      N-1 列的矩阵，读者会以为表里就是他要比的那几个。
    """
    from app.util import internal_client

    async def compare_candidate_pool(tenant_id, chat_session_id, entity_ids, dimensions=None):
        assert entity_ids == ["v1", "v2", "v9"]
        assert dimensions == ["finalScore"]
        return {
            "code": 0,
            "msg": "success",
            "data": {
                "entities": [_comparable_entity("v1"), _comparable_entity("v2")],
                "dimensions": ["finalScore"],
                "cells": [
                    {"entityId": "v1", "dimension": "finalScore", "value": 88.5,
                     "unit": "score", "source": "candidatePool.finalScore"},
                    {"entityId": "v2", "dimension": "finalScore", "value": 90.0,
                     "unit": "score", "source": "candidatePool.finalScore"},
                ],
                "unavailableDimensions": [],
                "limitations": ["entity_not_found:v9"],
            },
        }

    monkeypatch.setattr(internal_client, "compare_candidate_pool", compare_candidate_pool)

    tools = ReadonlyDomainTools(trusted_context(), backend=_compare_backend())

    result = await tools.call(
        "recommendation.compare_candidates",
        {"entityIds": ["v1", "v2", "v9"], "dimensions": ["finalScore", "riskFlags"]},
    )

    assert result["status"] == "ok"
    # 未接线的维度：data 与外层 limitations 都要有，不可用名单也要含它。
    assert "dimension_source_not_wired:riskFlags" in result["limitations"]
    assert "dimension_source_not_wired:riskFlags" in result["data"]["limitations"]
    assert "riskFlags" in result["data"]["unavailable_dimensions"]
    # 找不到的 ID 逐条转述，不许吞。
    assert "entity_not_found:v9" in result["limitations"]
    assert "entity_not_found:v9" in result["data"]["limitations"]


@pytest.mark.asyncio
async def test_compare_candidates_withholds_numbers_that_violate_the_scope_contract(
    monkeypatch,
) -> None:
    """口径合同（与 Java 同一份判据）被违反时，**数字不许透给模型**——整列降级不可比。

    构造的是最危险的形状：Java 返回的两行批次不同（口径不齐）却带着 finalScore
    的值。守约检查必须把该列置空并标不可比，而不是把 88.5 与 90.0 交给模型
    去说"A 比 B 低"——那是"把不可比的数放在一起比"。
    """
    from app.util import internal_client

    async def compare_candidate_pool(tenant_id, chat_session_id, entity_ids, dimensions=None):
        return {
            "code": 0,
            "msg": "success",
            "data": {
                "entities": [
                    _comparable_entity("v1", batch="17"),
                    _comparable_entity("v2", batch="18"),
                ],
                "dimensions": ["finalScore", "cityName"],
                "cells": [
                    {"entityId": "v1", "dimension": "finalScore", "value": 88.5,
                     "unit": "score", "source": "candidatePool.finalScore"},
                    {"entityId": "v2", "dimension": "finalScore", "value": 90.0,
                     "unit": "score", "source": "candidatePool.finalScore"},
                    {"entityId": "v1", "dimension": "cityName", "value": "杭州",
                     "source": "candidatePool.cityName"},
                    {"entityId": "v2", "dimension": "cityName", "value": "上海",
                     "source": "candidatePool.cityName"},
                ],
                "unavailableDimensions": [],
                "limitations": [],
            },
        }

    monkeypatch.setattr(internal_client, "compare_candidate_pool", compare_candidate_pool)

    tools = ReadonlyDomainTools(trusted_context(), backend=_compare_backend())

    result = await tools.call(
        "recommendation.compare_candidates",
        {"entityIds": ["v1", "v2"], "dimensions": ["finalScore", "cityName"]},
    )

    assert result["status"] == "ok"
    assert "comparison_incomparable_value:finalScore" in result["limitations"]
    assert "comparison_values_withheld:finalScore" in result["limitations"]
    assert "finalScore" in result["data"]["unavailable_dimensions"]
    for cell in result["data"]["cells"]:
        if cell["dimension"] == "finalScore":
            assert cell["value"] is None
            assert cell["unavailableReason"] == "scope_mismatch"
    # 名称类维度不受口径影响，照常带出。
    city_cell = next(cell for cell in result["data"]["cells"] if cell["dimension"] == "cityName")
    assert city_cell["value"] == "杭州"


@pytest.mark.asyncio
async def test_compare_candidates_transport_error_is_backend_unavailable_not_an_empty_matrix(
    monkeypatch,
) -> None:
    """传输层失败必须是 `backend_unavailable`——**不是**一张空矩阵："查不到"与"没有"是两件事。"""
    from app.util import internal_client

    async def compare_candidate_pool(*args, **kwargs):
        return {"error": "connection refused", "success": False, "data": {}}

    monkeypatch.setattr(internal_client, "compare_candidate_pool", compare_candidate_pool)

    tools = ReadonlyDomainTools(trusted_context(), backend=_compare_backend())

    result = await tools.call(
        "recommendation.compare_candidates", {"entityIds": ["v1", "v2"]}
    )

    assert result["status"] == "backend_unavailable"
    assert "connection refused" in result["data"]["message"]


def _fit_response(**overrides) -> dict:
    """Java `explain-fit` 的可用形状：匹配点带 source、概率恒不可用。"""
    data: dict = {
        "entityId": "v1",
        "found": True,
        "schoolName": "浙江大学",
        "majorName": "计算机科学与技术",
        "tier": "冲",
        "profileVersion": 7,
        "matched": [
            {
                "dimension": "subject_requirement",
                "statement": "选科要求「物理、化学」已满足",
                "source": "candidate.mustSubjects vs userScoreDetail.subjectList",
            },
            {
                "dimension": "tuition_range",
                "statement": "学费 6000 元/年在区间（3000 元/年 – 9000 元/年）内",
                "source": "candidate.tuitionPerYear vs userScoreDetail.tuitionRange",
            },
        ],
        "risks": {
            "flags": ["保研率一般"],
            "reasonCodes": ["城市发展好"],
            "facts": [{"field": "tier", "value": "冲"}, {"field": "rankInTier", "value": "3"}],
        },
        "fitDimensions": [
            {"dimension": "subject_requirement", "status": "matched", "detail": "档案选科满足要求"},
            {"dimension": "region_preference", "status": "not_applicable", "detail": "未配置地域偏好"},
        ],
        "probability": {
            "status": "unavailable",
            "reason": "no_authoritative_probability_source",
        },
        "limitations": [],
    }
    data.update(overrides)
    return {"code": 0, "msg": "success", "data": data}


@pytest.mark.asyncio
async def test_explain_fit_uses_trusted_identity_and_declares_read_only(monkeypatch) -> None:
    """适配性解释的四条合同：**受信身份、值原样带出、概率恒不可用、只读声明**。

    - 模型塞进来的 tenantId/sessionId/chatSessionId 必须被丢掉——身份只能来自
      受信 binding（否则它能解释别人会话里的候选）；
    - matched/risks/fitDimensions 是 Java 从候选池与会话状态真实载入的，原样带出；
    - `probability` 只带 status/reason：**适配与概率分开讲**，本链路不给概率数字；
    - `state_mutation=False`：解释不改任何状态（Java 侧版本号实证在真栈 E2E）。
    """
    from app.util import internal_client

    calls: list[dict] = []

    async def explain_candidate_fit(tenant_id, chat_session_id, entity_id):
        calls.append(
            {
                "tenant_id": tenant_id,
                "chat_session_id": chat_session_id,
                "entity_id": entity_id,
            }
        )
        return _fit_response()

    monkeypatch.setattr(internal_client, "explain_candidate_fit", explain_candidate_fit)

    tools = ReadonlyDomainTools(trusted_context(), backend=_compare_backend())

    result = await tools.call(
        "recommendation.explain_fit",
        {
            "entityId": "v1",
            # 冒充身份：必须被 `_trusted_arguments` 丢掉。
            "tenantId": "999",
            "sessionId": "888",
            "chatSessionId": "777",
        },
    )

    assert result["kind"] == "candidate"
    assert result["status"] == "ok"
    assert calls == [
        {"tenant_id": "1", "chat_session_id": "900047", "entity_id": "v1"}
    ]
    data = result["data"]
    assert data["entityId"] == "v1"
    assert data["found"] is True
    assert data["schoolName"] == "浙江大学"
    assert data["tier"] == "冲"
    assert [point["source"] for point in data["matched"]] == [
        "candidate.mustSubjects vs userScoreDetail.subjectList",
        "candidate.tuitionPerYear vs userScoreDetail.tuitionRange",
    ]
    # 候选行标志逐字透传（flags/reasonCodes 不改写）。
    assert data["risks"]["flags"] == ["保研率一般"]
    assert data["risks"]["reasonCodes"] == ["城市发展好"]
    assert data["fit_dimensions"][0]["status"] == "matched"
    assert data["probability"] == {
        "status": "unavailable",
        "reason": "no_authoritative_probability_source",
    }
    assert data["state_mutation"] is False
    assert result["limitations"] == []


@pytest.mark.asyncio
async def test_explain_fit_requires_a_single_entity_id_without_calling_backend(
    monkeypatch,
) -> None:
    """entityId 缺失/空白在工具入口挡住（先 preview 拿 entityId 再解释），**不打后端**。"""
    from app.util import internal_client

    calls: list = []

    async def explain_candidate_fit(*args, **kwargs):
        calls.append((args, kwargs))
        return _fit_response()

    monkeypatch.setattr(internal_client, "explain_candidate_fit", explain_candidate_fit)

    tools = ReadonlyDomainTools(trusted_context(), backend=_compare_backend())

    missing = await tools.call("recommendation.explain_fit", {})
    assert missing["status"] == "needs_clarification"
    assert missing["data"]["missingFields"] == ["entityId"]

    blank = await tools.call("recommendation.explain_fit", {"entityId": "  "})
    assert blank["status"] == "needs_clarification"

    assert calls == []


@pytest.mark.asyncio
async def test_explain_fit_forces_probability_unavailable_and_drops_sourceless_matches(
    monkeypatch,
) -> None:
    """**概率不可用一律如实说、没有 source 的匹配点不许说**——上游给的别的形状也照样降级。

    构造最危险的两种上游形状：probability 说"可用"还带数字、matched 里混了一条
    没有 source 的"匹配"。数字不许透给模型（改成 unavailable + 如实标注），
    无来源的匹配点被丢弃并计数（不静默）。
    """
    from app.util import internal_client

    async def explain_candidate_fit(tenant_id, chat_session_id, entity_id):
        return _fit_response(
            matched=[
                {
                    "dimension": "subject_requirement",
                    "statement": "选科要求已满足",
                    "source": "candidate.mustSubjects vs userScoreDetail.subjectList",
                },
                {"dimension": "major_intent", "statement": "专业很合适", "source": ""},
            ],
            probability={"status": "available", "reason": "upstream_model", "value": 0.62},
        )

    monkeypatch.setattr(internal_client, "explain_candidate_fit", explain_candidate_fit)

    tools = ReadonlyDomainTools(trusted_context(), backend=_compare_backend())

    result = await tools.call("recommendation.explain_fit", {"entityId": "v1"})

    data = result["data"]
    assert data["probability"]["status"] == "unavailable"
    assert "value" not in data["probability"], "概率数字不许透给模型"
    assert "probability_withheld_no_authoritative_source" in result["limitations"]
    assert len(data["matched"]) == 1, "没有 source 的匹配点不存在"
    assert data["matched"][0]["source"]
    assert "matched_without_source_dropped:1" in result["limitations"]
    assert "matched_without_source_dropped:1" in data["limitations"]


@pytest.mark.asyncio
async def test_explain_fit_entity_not_found_is_a_honest_empty_result(monkeypatch) -> None:
    """找不到的 entityId 是**如实空解释**（found=false + limitation），不是错误——"查不到"要能说出口。"""
    from app.util import internal_client

    async def explain_candidate_fit(tenant_id, chat_session_id, entity_id):
        return _fit_response(
            entityId="v9",
            found=False,
            schoolName=None,
            majorName=None,
            tier=None,
            matched=[],
            risks={},
            fitDimensions=[],
            limitations=["entity_not_found:v9"],
        )

    monkeypatch.setattr(internal_client, "explain_candidate_fit", explain_candidate_fit)

    tools = ReadonlyDomainTools(trusted_context(), backend=_compare_backend())

    result = await tools.call("recommendation.explain_fit", {"entityId": "v9"})

    assert result["status"] == "ok"
    data = result["data"]
    assert data["found"] is False
    assert data["entityId"] == "v9"
    assert data["matched"] == []
    assert "entity_not_found:v9" in result["limitations"]
    assert "entity_not_found:v9" in data["limitations"]
    assert data["probability"]["status"] == "unavailable"


@pytest.mark.asyncio
async def test_explain_fit_transport_error_is_backend_unavailable_not_an_empty_explain(
    monkeypatch,
) -> None:
    """传输层失败必须是 `backend_unavailable`——**不是**一份空解释。"""
    from app.util import internal_client

    async def explain_candidate_fit(*args, **kwargs):
        return {"error": "connection refused", "success": False, "data": {}}

    monkeypatch.setattr(internal_client, "explain_candidate_fit", explain_candidate_fit)

    tools = ReadonlyDomainTools(trusted_context(), backend=_compare_backend())

    result = await tools.call("recommendation.explain_fit", {"entityId": "v1"})

    assert result["status"] == "backend_unavailable"
    assert "connection refused" in result["data"]["message"]


def test_explain_fit_description_states_readonly_probability_and_sources() -> None:
    """工具描述是模型实际读到的那句话，三件读不到就会猜的事要写死：
    **只读**、**概率不可用一律如实说**（适配与概率分开讲）、**只引用带 source 的条目**。"""
    from app.mcp_server.server import TOOL_DESCRIPTIONS, tool_listing

    description = TOOL_DESCRIPTIONS["recommendation.explain_fit"]
    for phrase in (
        "解释某个候选为什么匹配/不匹配（只读）",
        "概率不可用一律如实说",
        "只引用带 source 的条目",
        "适配与概率分开讲",
        "preview_candidates",
        "unavailable",
    ):
        assert phrase in description, f"工具描述缺少口径：{phrase}"

    listed = {entry["name"]: entry for entry in tool_listing()}
    assert listed["recommendation.explain_fit"]["description"] == description
    assert listed["recommendation.explain_fit"]["annotations"]["readOnlyHint"] is True
    schema = listed["recommendation.explain_fit"]["inputSchema"]
    # 入参只有单个 entityId：身份字段不在 schema 里（由受信 binding 注入）。
    assert set(schema["properties"]) == {"entityId"}
    assert schema["required"] == ["entityId"]
    assert schema["additionalProperties"] is False


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


@pytest.mark.asyncio
async def test_batch_options_carry_codes_levels_and_batch_evidence(monkeypatch) -> None:
    """补录批次表：`code` 是模型要填进草稿的批次码，`level` 是本专科**编码**
    （建档策略按 `provinceCode + level` 取，传"本科"这种名字会静默取不到）。

    2026-10-06 的真事故形状：模型的卡上只有分数、没有批次码——这张表就是给它补编码的。
    批次线是**观测**：证据要跟着一起出来（与 `catalog.list_batches` 同源）。
    """
    from app.util import internal_client

    calls: list[dict] = []

    async def batch_options(area_id, subject_type="", **kwargs):
        calls.append({"area_id": area_id, "subject_type": subject_type, **kwargs})
        return {
            "code": 0,
            "data": [
                {"code": "17", "name": "第一段", "level": "01", "score": 494, "pos": 184816},
                {"code": "18", "name": "第二段", "level": "02", "score": 266, "pos": 292753},
            ],
            "evidence": [{"evidenceId": "ev_batch_1", "sourceSystem": "gaotu.batchList"}],
        }

    monkeypatch.setattr(internal_client, "get_batch_options", batch_options)
    backend = InternalClientBackend.__new__(InternalClientBackend)
    backend.tenant_id, backend.chat_session_id, backend.thread_id = "1", "1", "thr"
    backend.current_state_version = 0
    tools = ReadonlyDomainTools(trusted_context(), backend=backend)

    result = await tools.call(
        "catalog.get_batch_options", {"provinceCode": "330000", "subjectType": "N"}
    )

    assert result["status"] == "ok"
    assert result["kind"] == "catalog"
    assert result["data"][0] == {
        "code": "17", "name": "第一段", "level": "01", "score": 494, "pos": 184816,
    }
    assert result["data"][1]["level"] == "02"
    assert [item["evidenceId"] for item in result["evidenceRefs"]] == ["ev_batch_1"]
    # 受信身份注入，模型塞的东西进不去（与其它工具同一条纪律）。
    assert calls[0]["area_id"] == "330000"
    assert calls[0]["subject_type"] == "N"
    assert calls[0]["tenant_id"] == "1"


@pytest.mark.asyncio
async def test_batch_options_require_a_province_code(monkeypatch) -> None:
    """省份必填：批次码是**按省份**的（浙江第一段=17、上海本科批=01），
    没有省份这张表无从查起——缺参要在工具入口说清，别让模型拿到一屏空数组。"""
    backend = InternalClientBackend.__new__(InternalClientBackend)
    backend.tenant_id, backend.chat_session_id, backend.thread_id = "1", "1", "thr"
    backend.current_state_version = 0
    tools = ReadonlyDomainTools(trusted_context(), backend=backend)

    result = await tools.call("catalog.get_batch_options", {})

    assert result["status"] == "needs_clarification"
    assert result["data"]["missingFields"] == ["provinceCode"]


@pytest.mark.asyncio
async def test_batch_options_say_that_score_does_not_filter_batches(monkeypatch) -> None:
    """`score` 是契约里的保留字段：上游批次策略只按 (省份, 科类) 出批次线。
    传了分数若不作声，模型会把"我传了 610 分"读成因果。"""
    from app.util import internal_client

    async def batch_options(area_id, subject_type="", **kwargs):
        return {"code": 0, "data": [{"code": "17", "name": "第一段", "level": "01", "score": 494}]}

    monkeypatch.setattr(internal_client, "get_batch_options", batch_options)
    backend = InternalClientBackend.__new__(InternalClientBackend)
    backend.tenant_id, backend.chat_session_id, backend.thread_id = "1", "1", "thr"
    backend.current_state_version = 0
    tools = ReadonlyDomainTools(trusted_context(), backend=backend)

    result = await tools.call(
        "catalog.get_batch_options", {"provinceCode": "330000", "score": 610}
    )

    assert result["status"] == "ok"
    assert "batch_policy_ignores_score" in result["limitations"]


@pytest.mark.asyncio
async def test_subject_options_expose_the_standard_encoding_mapping(monkeypatch) -> None:
    """科目编码表：01-07 选考 + 08/10/11 语数外（上游只回选考，主科由 Java 补全）。
    模型拿它把"语文 112"落到 `{"subject": "08"}`——只带分数的草稿会被 110 拒。"""
    from app.util import internal_client

    async def subject_options(area_id):
        return {
            "code": 0,
            "data": [
                {"code": "01", "name": "物理"},
                {"code": "05", "name": "化学"},
                {"code": "08", "name": "语文"},
                {"code": "10", "name": "数学"},
                {"code": "11", "name": "英语"},
            ],
        }

    monkeypatch.setattr(internal_client, "get_subject_options", subject_options)
    backend = InternalClientBackend.__new__(InternalClientBackend)
    backend.tenant_id, backend.chat_session_id, backend.thread_id = "1", "1", "thr"
    backend.current_state_version = 0
    tools = ReadonlyDomainTools(trusted_context(), backend=backend)

    result = await tools.call("catalog.get_subject_options", {"provinceCode": "330000"})

    assert result["status"] == "ok"
    assert result["kind"] == "catalog"
    mapping = {item["code"]: item["name"] for item in result["data"]}
    assert mapping["01"] == "物理"
    assert mapping["08"] == "语文"
    assert mapping["10"] == "数学"
    assert mapping["11"] == "英语"


@pytest.mark.asyncio
async def test_subject_options_keep_java_rejection_text(monkeypatch) -> None:
    """Java 拒绝时（110「未查询到该省份的选科策略」）原文必须带出去：
    模型要能看出"这个省查不到"并改问用户，而不是把空表当"这个省没有科目"念。"""
    from app.util import internal_client

    async def subject_options(area_id):
        return {"code": 110, "msg": "未查询到该省份的选科策略", "data": None}

    monkeypatch.setattr(internal_client, "get_subject_options", subject_options)
    backend = InternalClientBackend.__new__(InternalClientBackend)
    backend.tenant_id, backend.chat_session_id, backend.thread_id = "1", "1", "thr"
    backend.current_state_version = 0
    tools = ReadonlyDomainTools(trusted_context(), backend=backend)

    result = await tools.call("catalog.get_subject_options", {"provinceCode": "999999"})

    assert result["status"] == "upstream_error"
    assert "upstream_code:110" in result["limitations"]
    assert any("未查询到该省份的选科策略" in item for item in result["limitations"])


@pytest.mark.asyncio
async def test_score_position_returns_the_rank_interval_not_a_single_rank(monkeypatch) -> None:
    """一分一段：同分考生不可分辨，返回的是**区间**（highest~lowest）+ 同分人数。

    2026-10-07 实测读数（浙江 610）：students=1051、42829~43879。模型要能直接引
    这条区间；把它读成"42829 名"就是把区间当单点，用户会以为精确到个位。
    """
    from app.util import internal_client

    calls: list[dict] = []

    async def score_position(area_id, score, subject="N", data_level="01", year=None):
        calls.append(
            {
                "area_id": area_id,
                "score": score,
                "subject": subject,
                "data_level": data_level,
                "year": year,
            }
        )
        return {
            "code": 0,
            "msg": "ok",
            "data": {
                # 上游形状：四位小数字符串（真栈读数就是 "610.0000"）。
                "score": "610.0000",
                "students": 1051,
                "highestRank": 42829,
                "lowestRank": 43879,
                "dataLevel": "01",
                "groupTag": None,
            },
            "evidence": [{"evidenceId": "ev_pos_1", "sourceSystem": "gaotu.scorePosition"}],
        }

    monkeypatch.setattr(internal_client, "get_score_position", score_position)
    backend = InternalClientBackend.__new__(InternalClientBackend)
    backend.tenant_id, backend.chat_session_id, backend.thread_id = "1", "1", "thr"
    backend.current_state_version = 0
    tools = ReadonlyDomainTools(trusted_context(), backend=backend)

    result = await tools.call(
        "catalog.get_score_position",
        {
            "provinceCode": "330000",
            "score": 610,
            "subjectType": "N",
            "batchLevel": "01",
            "year": 2026,
            # 冒充身份：必须被 `_trusted_arguments` 丢掉。
            "tenantId": "999",
        },
    )

    assert result["status"] == "ok"
    assert result["kind"] == "catalog"
    assert result["data"] == {
        # 四位小数被收敛成给人看的形状（610.0000 → 610）。
        "score": "610",
        "same_score_count": 1051,
        "highest_rank": 42829,
        "lowest_rank": 43879,
        # 单一默认位次 = lowest_rank（最保守口径，hl-wish scoreToPos 同口径）。
        "default_rank": 43879,
        "data_level": "01",
    }
    # 参数按上游口径到达；受信身份由服务端注入。
    assert calls[0] == {
        "area_id": "330000",
        "score": "610",
        "subject": "N",
        "data_level": "01",
        "year": "2026",
    }
    assert [item["evidenceId"] for item in result["evidenceRefs"]] == ["ev_pos_1"]


@pytest.mark.asyncio
async def test_score_position_says_unavailable_when_the_province_has_no_data(monkeypatch) -> None:
    """上游没有该省的**一分一段**数据（如安徽）时如实回不可用。

    这里防的是最坏的一类"帮忙"：拿邻省的表、拿往年的表、或者按分数线性估算一个名次。
    工具要么给区间，要么说查不到——**不得估算**（口径写死在工具描述里）。
    """
    from app.util import internal_client

    calls: list[dict] = []

    async def score_position(area_id, score, subject="N", data_level="01", year=None):
        calls.append({"area_id": area_id, "score": score, "year": year})
        return {"code": 0, "msg": "ok", "data": None}

    monkeypatch.setattr(internal_client, "get_score_position", score_position)
    backend = InternalClientBackend.__new__(InternalClientBackend)
    backend.tenant_id, backend.chat_session_id, backend.thread_id = "1", "1", "thr"
    backend.current_state_version = 0
    tools = ReadonlyDomainTools(trusted_context(), backend=backend)

    result = await tools.call(
        "catalog.get_score_position", {"provinceCode": "340000", "score": 610}
    )

    assert result["status"] == "ok"
    assert result["data"] == {"score": "610", "unavailable": True}
    assert "score_position_unavailable" in result["limitations"]
    # 年份缺省**当前年**（会话里给了年份时以会话为准）。
    from datetime import datetime

    assert calls[0]["year"] == str(datetime.now().year)


@pytest.mark.asyncio
async def test_score_position_requires_the_province_and_the_score() -> None:
    """省份与分数都必填：省份决定查哪张表，分数是表里的行——缺哪一项都查不了。

    缺参要在工具入口说清（`missingFields`），别让模型拿一个空区间回去编。
    """
    backend = InternalClientBackend.__new__(InternalClientBackend)
    backend.tenant_id, backend.chat_session_id, backend.thread_id = "1", "1", "thr"
    backend.current_state_version = 0
    tools = ReadonlyDomainTools(trusted_context(), backend=backend)

    result = await tools.call("catalog.get_score_position", {})

    assert result["status"] == "needs_clarification"
    assert result["data"]["missingFields"] == ["provinceCode", "score"]


def test_score_position_tool_description_states_the_interval_rule() -> None:
    """工具描述是**模型实际读到的那句话**：同分不可分辨/区间只用于展示/
    default_rank 才是测算口径/无数据不得估算——都必须写死在那里，
    否则模型只能自己猜，而猜出来的是一个精确名次。"""
    from app.mcp_server.server import TOOL_DESCRIPTIONS, tool_listing

    description = TOOL_DESCRIPTIONS["catalog.get_score_position"]
    for phrase in (
        "一分一段",
        "同分",
        "区间",
        "不可分辨",
        "区间用于展示",
        "default_rank",
        "最保守",
        "测算",
        "不得估算",
        "禁估算",
        # 科类编码按省份口径：3+1+2 省份 WL/LS，传 N 会回空——"查不到"是参数错。
        "WL",
        "LS",
        "3+1+2",
        "不得跨省外推",
    ):
        assert phrase in description, f"工具描述缺少口径：{phrase}"

    listed = {entry["name"]: entry for entry in tool_listing()}
    assert listed["catalog.get_score_position"]["description"] == description
    # 没写描述的其余工具保持默认：这条守的是"描述面改动要显式"的机制
    # （换过见证工具：get_batch_options 这轮进了描述面）。
    assert listed["catalog.get_subject_options"]["description"] == (
        "Zhiyuan authoritative read-only domain query"
    )
    schema = listed["catalog.get_score_position"]["inputSchema"]
    assert schema["required"] == ["provinceCode", "score"]
    assert schema["additionalProperties"] is False
    # 批次 level 是这条工具的参数（01 本科 / 02 专科），与批次码是两套编码。
    assert "batchLevel" in schema["properties"]


def test_preview_majors_tool_description_states_layering_and_caliber() -> None:
    """专业方向的工具描述要写死两件模型读不到就会猜的事：**层级**（专业方向 vs
    具体志愿单元，别和 preview_candidates 混用）与**口径/边界**（只读、画像缺分数
    时不可用、维度分按 rank 口径不得改口径转述）。"""
    from app.mcp_server.server import TOOL_DESCRIPTIONS, tool_listing

    description = TOOL_DESCRIPTIONS["recommendation.preview_majors"]
    for phrase in (
        "基于会话画像的专业方向打分推荐（只读）",
        "画像缺分数时不可用",
        "分数维度按 rank 服务口径",
        "专业方向",
        "具体志愿单元",
        "preview_candidates",
        "上限 8",
    ):
        assert phrase in description, f"工具描述缺少口径：{phrase}"

    listed = {entry["name"]: entry for entry in tool_listing()}
    assert listed["recommendation.preview_majors"]["description"] == description
    schema = listed["recommendation.preview_majors"]["inputSchema"]
    # 入参只有 topN：身份字段不在 schema 里（由受信 binding 注入）。
    assert set(schema["properties"]) == {"topN"}
    assert schema["required"] == []
    assert schema["additionalProperties"] is False
    assert schema["properties"]["topN"]["maximum"] == 8


def test_batch_options_description_states_subject_translation_and_default_batch_rule() -> None:
    """批次编码表的描述要写死两件产品/实测规则：科类编码**按省份口径**（多科类
    省份可给 WL/LS，也可给选考科目码/名由 Java 翻译；实测安徽传 N 回空）与
    **过本科线默认本科批、不再追问**。"""
    from app.mcp_server.server import TOOL_DESCRIPTIONS, tool_listing

    description = TOOL_DESCRIPTIONS["catalog.get_batch_options"]
    for phrase in (
        "level",
        "本科批",
        "不再追问",
        "WL",
        "LS",
        "翻译",
        "按省份口径",
    ):
        assert phrase in description, f"工具描述缺少口径：{phrase}"

    listed = {entry["name"]: entry for entry in tool_listing()}
    assert listed["catalog.get_batch_options"]["description"] == description
    # 科类字段本身也要在 schema 里说清省份口径（模型按参数学的次数不比按描述少）。
    assert "按省份口径" in listed["catalog.get_batch_options"]["inputSchema"]["properties"]["subjectType"]["description"]
