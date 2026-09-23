from __future__ import annotations

import json

import pytest

from app.config import GatewayConfig
from app.gateway.service import GatewayService
from app.harness.binding import ThreadBinding
from app.harness.turn_result import CodexTurnResult
from app.engine.semantic_eval import SemanticExpectation, evaluate_trace


class FakeMessageStore:
    def __init__(self) -> None:
        self.users: list[tuple[str, str]] = []
        self.agents: list[tuple[str, str]] = []

    async def save_user_message(self, chat_session_id: str, content: str) -> int:
        self.users.append((chat_session_id, content))
        return len(self.users)

    async def save_agent_message(self, chat_session_id: str, content: str, ws_type: str = "reply") -> int:
        self.agents.append((chat_session_id, content))
        return len(self.agents)


class FakeLegacyService:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def handle_message(self, *, session_id: str, user_id: str, content: str, on_progress=None) -> str:
        self.calls.append({"session_id": session_id, "user_id": user_id, "content": content})
        return "旧链路答案"


class FakeCodexHarness:
    def __init__(self) -> None:
        self.created = 0
        self.injected: list[dict] = []
        self.turns: list[dict] = []

    async def create_thread(self, **kwargs):
        self.created += 1
        return {"thread": {"id": "thr-shadow"}}

    async def resume_thread(self, thread_id: str):
        return {"thread": {"id": thread_id}}

    async def inject_items(self, thread_id: str, items: list[dict]):
        self.injected.append({"thread_id": thread_id, "items": items})
        return {}

    async def start_turn(self, thread_id: str, input_items: list[dict], output_schema=None):
        self.turns.append({"thread_id": thread_id, "input": input_items, "schema": output_schema})
        return {
            "turn": {"id": "turn-shadow"},
            "output": {"responseType": "text", "message": "Codex dry-run"},
        }


def _working_set_payload(text: str) -> dict:
    return json.loads(text.split("结构化状态：", 1)[1])


def _snapshot() -> dict:
    return {
        "sessionId": "session-1",
        "version": 42,
        "phase": "candidate_exploration",
        "studentSummary": {"province": "浙江", "score": 650, "rank": 1000},
        "allowedCapabilities": ["catalog_read", "admission_read"],
    }


def _binding() -> ThreadBinding:
    return ThreadBinding(
        thread_id="thr-shadow",
        tenant_id="tenant-1",
        session_id="session-1",
        user_id="user-1",
        allowed_capabilities=frozenset({"catalog_read", "admission_read"}),
    )


async def _build_gateway(store, legacy, codex):
    return GatewayService(
        mode="codex_shadow",
        codex=codex,
        legacy=legacy,
        message_store=store,
        binding_loader=lambda **kwargs: _binding(),
        snapshot_loader=lambda **kwargs: _snapshot(),
    )


async def test_shadow_persists_legacy_chain_and_deduplicates_turn() -> None:
    store = FakeMessageStore()
    legacy = FakeLegacyService()
    codex = FakeCodexHarness()
    gateway = await _build_gateway(store, legacy, codex)

    first = await gateway.handle_turn(
        tenant_id="tenant-1", session_id="session-1", user_id="user-1", turn_id="turn-1", content="推荐计算机"
    )
    second = await gateway.handle_turn(
        tenant_id="tenant-1", session_id="session-1", user_id="user-1", turn_id="turn-1", content="推荐计算机"
    )

    assert first == second
    assert first["mode"] == "codex_shadow"
    assert first["reply"] == "旧链路答案"
    assert len(store.users) == 1
    assert len(store.agents) == 1
    assert len(legacy.calls) == 1
    assert len(codex.turns) == 1
    assert first["writeAttempted"] is False


async def test_gateway_rejects_same_turn_id_with_different_content() -> None:
    store = FakeMessageStore()
    legacy = FakeLegacyService()
    gateway = await _build_gateway(store, legacy, FakeCodexHarness())

    await gateway.handle_turn(
        tenant_id="tenant-1", session_id="session-1", user_id="user-1", turn_id="turn-1", content="第一条"
    )
    result = await gateway.handle_turn(
        tenant_id="tenant-1", session_id="session-1", user_id="user-1", turn_id="turn-1", content="第二条"
    )

    assert result["error"] == "turn_id_input_conflict"
    assert len(legacy.calls) == 1


async def test_gateway_binds_the_snapshot_version_for_the_codex_turn() -> None:
    captured = {}

    def binding_loader(**kwargs):
        captured.update(kwargs)
        return _binding()

    gateway = GatewayService(
        mode="codex_readonly",
        codex=FakeCodexHarness(),
        legacy=FakeLegacyService(),
        message_store=FakeMessageStore(),
        binding_loader=binding_loader,
        snapshot_loader=lambda **kwargs: _snapshot(),
    )

    await gateway.handle_turn(
        tenant_id="tenant-1",
        session_id="session-1",
        user_id="user-1",
        turn_id="turn-bound-snapshot",
        content="推荐计算机",
    )

    assert captured["snapshot_version"] == 42


async def test_gateway_injects_adjacent_snapshot_as_state_patch() -> None:
    store = FakeMessageStore()
    legacy = FakeLegacyService()
    codex = FakeCodexHarness()
    snapshots = [_snapshot(), {**_snapshot(), "version": 43, "phase": "plan_review"}]

    async def snapshot_loader(**kwargs):
        return snapshots.pop(0)

    gateway = GatewayService(
        mode="codex_shadow",
        codex=codex,
        legacy=legacy,
        message_store=store,
        binding_loader=lambda **kwargs: _binding(),
        snapshot_loader=snapshot_loader,
    )

    first = await gateway.handle_turn(
        tenant_id="tenant-1", session_id="session-1", user_id="user-1", turn_id="turn-1", content="先看候选"
    )
    second = await gateway.handle_turn(
        tenant_id="tenant-1", session_id="session-1", user_id="user-1", turn_id="turn-2", content="再审查方案"
    )

    assert first["statePatch"] is None
    assert second["statePatch"]["baseVersion"] == 42
    assert second["statePatch"]["targetVersion"] == 43
    assert codex.injected == []
    assert json.loads(codex.turns[-1]["input"][0]["text"])["kind"] == "state_patch"
    working_set = _working_set_payload(codex.turns[-1]["input"][1]["text"])
    assert working_set["kind"] == "conversation_working_set"
    assert working_set["snapshotVersion"] == 43
    assert working_set["lastResponseType"] == "text"


async def test_readonly_gateway_does_not_persist_unvalidated_codex_output() -> None:
    store = FakeMessageStore()
    legacy = FakeLegacyService()

    class InvalidOutputHarness(FakeCodexHarness):
        async def start_turn(self, thread_id: str, input_items: list[dict], output_schema=None):
            self.turns.append({"thread_id": thread_id, "input": input_items, "schema": output_schema})
            return {
                "turn": {"id": "turn-invalid"},
                "output": {
                    "responseType": "fact",
                    "message": "未经证实的事实",
                    "evidenceRefs": [{"evidenceId": "ev-missing", "sourceLevel": "authoritative", "dataVersion": "2026"}],
                },
            }

    gateway = GatewayService(
        mode="codex_readonly",
        codex=InvalidOutputHarness(),
        legacy=legacy,
        message_store=store,
        binding_loader=lambda **kwargs: _binding(),
        snapshot_loader=lambda **kwargs: _snapshot(),
    )

    result = await gateway.handle_turn(
        tenant_id="tenant-1", session_id="session-1", user_id="user-1", turn_id="turn-invalid", content="给我事实"
    )

    assert result["error"].startswith("evidence_not_found")
    assert len(store.users) == 1
    assert len(store.agents) == 0


async def test_readonly_gateway_asks_codex_to_repair_missing_structured_output_once() -> None:
    store = FakeMessageStore()
    legacy = FakeLegacyService()

    class RepairingHarness(FakeCodexHarness):
        async def start_turn_and_collect(self, thread_id, input_items, output_schema=None):
            self.turns.append({"thread_id": thread_id, "input": input_items, "schema": output_schema})
            if len(self.turns) == 1:
                return CodexTurnResult(status="completed", output=None)
            return CodexTurnResult(
                status="completed",
                output={"responseType": "text", "message": "已按契约修复输出"},
            )

    codex = RepairingHarness()
    gateway = GatewayService(
        mode="codex_readonly",
        codex=codex,
        legacy=legacy,
        message_store=store,
        binding_loader=lambda **kwargs: _binding(),
        snapshot_loader=lambda **kwargs: _snapshot(),
    )

    result = await gateway.handle_turn(
        tenant_id="tenant-1",
        session_id="session-1",
        user_id="user-1",
        turn_id="turn-repair",
        content="继续查询",
    )

    assert result["reply"] == "已按契约修复输出"
    assert result["recovery"] == {"outputRepaired": True}
    assert len(codex.turns) == 2
    assert len(codex.turns[1]["input"]) == 1
    assert "不要调用新工具" in codex.turns[1]["input"][0]["text"]
    assert store.agents == [("session-1", "已按契约修复输出")]


async def test_readonly_gateway_rejects_cross_tenant_evidence() -> None:
    store = FakeMessageStore()
    legacy = FakeLegacyService()

    class CrossTenantHarness(FakeCodexHarness):
        async def start_turn(self, thread_id: str, input_items: list[dict], output_schema=None):
            self.turns.append({"thread_id": thread_id, "input": input_items, "schema": output_schema})
            return {
                "turn": {"id": "turn-cross-tenant"},
                "output": {
                    "responseType": "fact",
                    "message": "跨租户事实",
                    "evidenceRefs": [
                        {
                            "evidenceId": "ev-cross-tenant",
                            "sourceLevel": "authoritative",
                            "dataVersion": "2026",
                        }
                    ],
                },
                "evidenceLedger": [
                    {
                        "evidenceId": "ev-cross-tenant",
                        "tenantId": "other-tenant",
                        "stateVersion": 42,
                        "dataVersion": "2026",
                    }
                ],
            }

    gateway = GatewayService(
        mode="codex_readonly",
        codex=CrossTenantHarness(),
        legacy=legacy,
        message_store=store,
        binding_loader=lambda **kwargs: _binding(),
        snapshot_loader=lambda **kwargs: _snapshot(),
    )

    result = await gateway.handle_turn(
        tenant_id="tenant-1",
        session_id="session-1",
        user_id="user-1",
        turn_id="turn-cross-tenant",
        content="查询事实",
    )

    assert result["error"].startswith("evidence_scope_violation")
    assert len(store.agents) == 0


async def test_readonly_gateway_preserves_candidates_for_followup_fact_query() -> None:
    store = FakeMessageStore()
    legacy = FakeLegacyService()

    class TwoTurnReadonlyHarness(FakeCodexHarness):
        def __init__(self) -> None:
            super().__init__()
            self.call_count = 0

        async def start_turn(self, thread_id: str, input_items: list[dict], output_schema=None):
            self.turns.append({"thread_id": thread_id, "input": input_items, "schema": output_schema})
            self.call_count += 1
            if self.call_count == 1:
                return {
                    "turn": {"id": "turn-1"},
                    "output": {"responseType": "text", "message": "已找到候选学校"},
                    "events": [
                        {
                            "type": "mcpToolCall",
                            "result": {
                                "resolvedEntities": [
                                    {"entityId": "school-1", "entityType": "school", "name": "甲大学"},
                                    {"entityId": "school-2", "entityType": "school", "name": "乙大学"},
                                ]
                            },
                        }
                    ],
                }
            return {
                "turn": {"id": "turn-2"},
                "output": {
                    "responseType": "fact",
                    "message": "已查询候选学校的历史分数",
                    "evidenceRefs": [
                        {
                            "evidenceId": "ev-history",
                            "sourceLevel": "authoritative",
                            "dataVersion": "2026",
                            "stateVersion": 42,
                        }
                    ],
                },
                "evidenceLedger": [
                    {
                        "evidenceId": "ev-history",
                        "stateVersion": 42,
                        "dataVersion": "2026",
                        "sessionId": "session-1",
                        "threadId": "thr-shadow",
                        "tenantId": "tenant-1",
                    }
                ],
            }

    codex = TwoTurnReadonlyHarness()
    gateway = GatewayService(
        mode="codex_readonly",
        codex=codex,
        legacy=legacy,
        message_store=store,
        binding_loader=lambda **kwargs: _binding(),
        snapshot_loader=lambda **kwargs: _snapshot(),
    )

    first = await gateway.handle_turn(
        tenant_id="tenant-1", session_id="session-1", user_id="user-1", turn_id="turn-1", content="找几所学校"
    )
    second = await gateway.handle_turn(
        tenant_id="tenant-1", session_id="session-1", user_id="user-1", turn_id="turn-2", content="查那几个学校去年的分数"
    )

    assert first["reply"] == "已找到候选学校"
    assert second["reply"] == "已查询候选学校的历史分数"
    assert codex.injected == []
    turn_working_set = _working_set_payload(codex.turns[-1]["input"][1]["text"])
    assert [item["entityId"] for item in turn_working_set["candidateSet"]["items"]] == [
        "school-1",
        "school-2",
    ]
    assert second["output"]["evidenceRefs"][0]["evidenceId"] == "ev-history"
    assert second["trace"]["responseType"] == "fact"
    assert second["trace"]["evidenceIds"] == ["ev-history"]
    assert second["trace"]["entityIds"] == ["school-1", "school-2"]
    evaluation = evaluate_trace(
        SemanticExpectation(
            case_id="followup-history",
            required_entity_ids={"school-1", "school-2"},
            response_type="fact",
            evidence_required=True,
        ),
        second["trace"],
    )
    assert evaluation["passed"] is True


async def test_readonly_gateway_collects_evidence_from_nested_mcp_event() -> None:
    store = FakeMessageStore()

    class NestedEvidenceHarness(FakeCodexHarness):
        async def start_turn(self, thread_id: str, input_items: list[dict], output_schema=None):
            return {
                "turn": {"id": "turn-evidence"},
                "output": {
                    "responseType": "fact",
                    "message": "已查到权威事实",
                    "evidenceRefs": [
                        {
                            "evidenceId": "ev-nested",
                            "sourceLevel": "authoritative",
                            "dataVersion": "2026",
                            "stateVersion": 42,
                        }
                    ],
                },
                "events": [
                    {
                        "type": "mcpToolCall",
                        "result": {
                            "evidence": [
                                {
                                    "evidenceId": "ev-nested",
                                    "tenantId": "tenant-1",
                                    "sessionId": "session-1",
                                    "threadId": "thr-shadow",
                                    "stateVersion": 42,
                                    "dataVersion": "2026",
                                }
                            ]
                        },
                    }
                ],
            }

    gateway = GatewayService(
        mode="codex_readonly",
        codex=NestedEvidenceHarness(),
        legacy=FakeLegacyService(),
        message_store=store,
        binding_loader=lambda **kwargs: _binding(),
        snapshot_loader=lambda **kwargs: _snapshot(),
    )
    result = await gateway.handle_turn(
        tenant_id="tenant-1",
        session_id="session-1",
        user_id="user-1",
        turn_id="turn-evidence",
        content="查询事实",
    )

    assert result["reply"] == "已查到权威事实"
    assert result["output"]["evidenceRefs"][0]["evidenceId"] == "ev-nested"


async def test_gateway_sends_model_proposal_request_to_java_preview(monkeypatch) -> None:
    from app.util import internal_client

    async def preview(tenant_id, session_id, payload):
        assert tenant_id == "tenant-1"
        assert session_id == "session-1"
        assert payload["goalType"] == "exclude_scope"
        assert payload["sourceVersionGuard"] == 42
        return {"code": 0, "data": {"proposals": [{"proposalId": "proposal-1", "status": "ready"}]}}

    monkeypatch.setattr(internal_client, "generate_user_goal_planning_fix_proposals", preview)

    class ProposalHarness(FakeCodexHarness):
        async def start_turn(self, thread_id: str, input_items: list[dict], output_schema=None):
            return {
                "turn": {"id": "turn-proposal"},
                "output": {
                    "responseType": "text",
                    "message": "我先生成方案预览",
                    "proposalRequest": {
                        "goalType": "exclude_scope",
                        "userOriginalText": "排除北京",
                        "confidence": "high",
                        "sourceVersionGuard": 42,
                        "negativeScopes": [{"scopeType": "province", "name": "北京"}],
                    },
                },
            }

    gateway = GatewayService(
        mode="codex_readonly",
        codex=ProposalHarness(),
        legacy=FakeLegacyService(),
        message_store=FakeMessageStore(),
        binding_loader=lambda **kwargs: _binding(),
        snapshot_loader=lambda **kwargs: _snapshot(),
    )
    result = await gateway.handle_turn(
        tenant_id="tenant-1",
        session_id="session-1",
        user_id="user-1",
        turn_id="turn-proposal",
        content="排除北京",
    )

    assert result["reply"] == "我先生成方案预览"
    assert result["proposalPreview"] == {"proposalId": "proposal-1", "status": "ready"}


async def test_write_mode_prepares_a_pending_instead_of_a_plain_preview(monkeypatch) -> None:
    """P2：写模式下走 `prepare`（物化 pending + Java 落下 operationId），**不再**走只出预览的 `generate`。

    对照：把 `generate` 换成"被调到就炸"，确保写模式不会走错端点；
    返回形状按 `PrepareResultDTO`（预览在 `result` 里）——解析两种形状都要认。
    """
    from app.util import internal_client

    seen = {}

    async def prepare(tenant_id, session_id, *, request_id, payload):
        seen["request_id"] = request_id
        assert tenant_id == "tenant-1" and session_id == "session-1"
        assert payload["goalType"] == "exclude_scope"
        return {
            "code": 0,
            "data": {
                "status": "prepared",
                "requestId": request_id,
                "pendingId": "pending-1",
                "operationId": "op-1",
                "result": {"proposals": [{"proposalId": "proposal-1", "status": "ready"}]},
            },
        }

    async def generate_should_not_be_called(*args, **kwargs):
        raise AssertionError("写模式不许走只出预览的 generate")

    monkeypatch.setattr(internal_client, "prepare_user_goal_planning_fix_proposals", prepare)
    monkeypatch.setattr(internal_client, "generate_user_goal_planning_fix_proposals", generate_should_not_be_called)

    class ProposalHarness(FakeCodexHarness):
        async def start_turn(self, thread_id: str, input_items: list[dict], output_schema=None):
            return {
                "turn": {"id": "turn-proposal"},
                "output": {
                    "responseType": "text",
                    "message": "我先生成方案预览",
                    "proposalRequest": {
                        "goalType": "exclude_scope",
                        "userOriginalText": "排除北京",
                        "confidence": "high",
                        "sourceVersionGuard": 42,
                        "negativeScopes": [{"scopeType": "province", "name": "北京"}],
                    },
                },
            }

    gateway = GatewayService(
        mode="codex_write",
        codex=ProposalHarness(),
        legacy=FakeLegacyService(),
        message_store=FakeMessageStore(),
        binding_loader=lambda **kwargs: _binding(),
        snapshot_loader=lambda **kwargs: _snapshot(),
    )
    result = await gateway.handle_turn(
        tenant_id="tenant-1",
        session_id="session-1",
        user_id="user-1",
        turn_id="turn-proposal",
        content="排除北京",
    )

    assert result["reply"] == "我先生成方案预览"
    assert result["proposalPreview"] == {"proposalId": "proposal-1", "status": "ready"}
    assert seen["request_id"] == "tenant-1:session-1:turn-proposal", "幂等键是 租户:会话:回合"


def test_gateway_mode_is_allowlisted() -> None:
    assert GatewayConfig(_env_file=None, mode="codex_shadow").mode == "codex_shadow"
    with pytest.raises(ValueError):
        GatewayConfig(_env_file=None, mode="unsafe")


class CollectingCodexHarness:
    """只实现 readonly 回合路径需要的接口，便于精确构造一次回合。"""

    def __init__(self, output: dict, events: list[dict]) -> None:
        self.output = output
        self.events = events
        self.turn_inputs: list[list[dict]] = []

    async def create_thread(self, **kwargs):
        return {"thread": {"id": "thr-collected"}}

    async def resume_thread(self, thread_id: str):
        return {"thread": {"id": thread_id}}

    async def inject_items(self, thread_id: str, items: list[dict]):
        return {}

    async def start_turn_and_collect(self, thread_id, input_items, output_schema=None):
        self.turn_inputs.append(input_items)
        return CodexTurnResult(
            status="completed",
            turn_id="turn-collected",
            output=self.output,
            events=self.events,
        )


async def test_tool_success_never_upgrades_a_partial_execution_status() -> None:
    """P2 成因 4 的服务级回归。

    只测 `synthesize_execution_status` 不够：原缺陷的观测面正是"冒烟拿到的是
    覆盖前的值"，绿灯与修好之间没有关系。这条从 `handle_turn` 进，断言出口。
    """
    harness = CollectingCodexHarness(
        output={
            "responseType": "text",
            "message": "只查到部分年份；写入未执行",
            "executionStatus": "partial",
        },
        events=[
            {
                "method": "item/completed",
                "params": {
                    "item": {
                        "type": "mcpToolCall",
                        "id": "call_1",
                        "server": "zhiyuan_domain",
                        "tool": "entity.resolve",
                        "status": "completed",
                        "arguments": {"query": "计算机"},
                        "result": {"content": []},
                    }
                },
            }
        ],
    )
    gateway = GatewayService(
        mode="codex_readonly",
        codex=harness,
        legacy=FakeLegacyService(),
        message_store=FakeMessageStore(),
        binding_loader=lambda **kwargs: _binding(),
        snapshot_loader=lambda **kwargs: _snapshot(),
    )

    result = await gateway.handle_turn(
        tenant_id="tenant-1",
        session_id="session-1",
        user_id="user-1",
        turn_id="turn-partial",
        content="查计算机，并把它写进我的方案",
    )

    assert result["output"]["executionStatus"] == "partial"
    assert result["trace"]["batchReport"]["status"] == "completed"
    assert result["trace"]["executionStatus"] == "partial"


async def test_tool_failure_still_downgrades_a_completed_execution_status() -> None:
    """只降不升不等于不许降：工具失败必须把 completed 拉下来。"""
    harness = CollectingCodexHarness(
        output={"responseType": "text", "message": "查询完成", "executionStatus": "completed"},
        events=[
            {
                "method": "item/completed",
                "params": {
                    "item": {
                        "type": "mcpToolCall",
                        "id": "call_2",
                        "server": "zhiyuan_domain",
                        "tool": "entity.resolve",
                        "status": "failed",
                        "arguments": {"query": "计算机"},
                        "error": {"message": "backend unavailable"},
                    }
                },
            }
        ],
    )
    gateway = GatewayService(
        mode="codex_readonly",
        codex=harness,
        legacy=FakeLegacyService(),
        message_store=FakeMessageStore(),
        binding_loader=lambda **kwargs: _binding(),
        snapshot_loader=lambda **kwargs: _snapshot(),
    )

    result = await gateway.handle_turn(
        tenant_id="tenant-1",
        session_id="session-1",
        user_id="user-1",
        turn_id="turn-downgraded",
        content="查计算机",
    )

    assert result["output"]["executionStatus"] in {"partial", "failed"}


@pytest.mark.asyncio
async def test_evidence_follows_the_snapshot_not_the_process_memory() -> None:
    """P1b-3 验收 4：证据以 **snapshot** 为准，进程内存只做交集。

    第一轮模型通过工具拿到一条 ev-stale，于是它进了进程内存；第二轮 Java 的
    快照里**只有** ev-valid——那是 Java 已经判定 ev-stale 不再 `valid`（stale /
    expired / unknown）。这一轮注入给模型的 workingSet 里必须没有 ev-stale，
    而 ev-valid 必须还在。

    对照是硬要求（任务书原话）：没有它，"整个 evidence_refs 被清空了"也能让
    "ev-stale 不在了"成立——通过和坏掉长得一模一样。
    """

    class EvidenceThenStale(FakeCodexHarness):
        async def start_turn(self, thread_id: str, input_items: list[dict], output_schema=None):
            self.turns.append({"thread_id": thread_id, "input": input_items, "schema": output_schema})
            return {
                "turn": {"id": f"turn-{len(self.turns)}"},
                "output": {
                    "responseType": "fact",
                    "message": "已拿到一条权威事实",
                    "evidenceRefs": [
                        {
                            "evidenceId": "ev-stale",
                            "sourceLevel": "authoritative",
                            "dataVersion": "2026-batch-1",
                        }
                    ],
                },
                "events": [
                    {
                        "type": "mcpToolCall",
                        "result": {
                            "evidence": [
                                {
                                    "evidenceId": "ev-stale",
                                    "tenantId": "tenant-1",
                                    "sessionId": "session-1",
                                    "threadId": "thr-shadow",
                                    "dataVersion": "2026-batch-1",
                                }
                            ]
                        },
                    }
                ],
            }

    def snapshot_with(evidence_ids: list[str]) -> dict:
        return {
            "sessionId": "session-1",
            "version": 42,
            "phase": "candidate_exploration",
            "studentSummary": {"province": "浙江", "score": 650, "rank": 1000},
            "allowedCapabilities": ["catalog_read", "admission_read"],
            "evidence": [
                {
                    "evidenceId": evidence_id,
                    "sourceLevel": "authoritative",
                    "dataVersion": "2026-batch-1",
                }
                for evidence_id in evidence_ids
            ],
        }

    # 第二轮的快照里没有 ev-stale——Java 已经把它判掉了。
    snapshots = [snapshot_with(["ev-valid"]), snapshot_with(["ev-valid"])]
    calls = {"n": 0}

    async def snapshot_loader(**kwargs):
        payload = snapshots[min(calls["n"], len(snapshots) - 1)]
        calls["n"] += 1
        return payload

    codex = EvidenceThenStale()
    gateway = GatewayService(
        mode="codex_readonly",
        codex=codex,
        legacy=FakeLegacyService(),
        message_store=FakeMessageStore(),
        binding_loader=lambda **kwargs: _binding(),
        snapshot_loader=snapshot_loader,
    )

    await gateway.handle_turn(
        tenant_id="tenant-1",
        session_id="session-1",
        user_id="user-1",
        turn_id="turn-1",
        content="查询事实",
    )
    await gateway.handle_turn(
        tenant_id="tenant-1",
        session_id="session-1",
        user_id="user-1",
        turn_id="turn-2",
        content="再问一句",
    )

    payload = _working_set_payload(codex.turns[-1]["input"][1]["text"])
    ids = [item["evidenceId"] for item in payload["evidenceRefs"]]

    assert "ev-stale" not in ids, "Java 判成 stale 的证据不许留在进程内存里"
    assert "ev-valid" in ids, "对照：snapshot 里还有的那条必须留下"
