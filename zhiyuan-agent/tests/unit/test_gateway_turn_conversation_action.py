"""模型在**文本回合**里发出的 confirm/cancel：必须真的执行，结果必须进回合结果。

修前的形状（2026-10-08，会话 10041979 的谎报就是它 ∨✓）：`output_validation.py`
只对 `conversationAction` 做 ref/版本核对 ✓，而 `_codex_turn` 里**没有任何执行分支** ✗
——无 Java 调用 ✓、无结果事件 ✓、无报错 ✓，模型嘴上说"已提交" ✓。

这里钉四件事：
① 执行走**点卡路径同一执行器**（`execute_action_and_refresh` ✓）：Java 调用形状 =
   `pending/resolve(confirm)` → `pending-command/execute` → `pending/resolve(complete)` ✓，
   `claim_token` 三段复用 ✓（新生成一个 Java 会拒 ✓）；
② 结果按与 `proposalRequest` 对称的方式挂进回合结果（`actionResult` 键 ✓）——
   `server.py::_emit_turn_terminal` 一见它发 `conversationAction.result` ✓；
③ 失败/冲突**不抛**：回合照常收尾，结果带失败码 ✓（模型据此如实转述，不许说"已生效"）；
④ 执行器抛异常也翻成 failed 结果 ✓——"静默丢弃"正是修前的老毛病，换成"整轮崩溃"
   同样把它藏起来 ✗；没有执行器的动作类型保持原行为（不执行、不产结果事件）✓。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from app.gateway import conversation_actions
from app.gateway.service import GatewayService
from app.harness.binding import ThreadBinding
from app.server import _run_native_turn


class _MessageStore:
    async def save_user_message(self, chat_session_id: str, content: str) -> int:
        return 1

    async def save_agent_message(self, chat_session_id: str, content: str, ws_type: str = "reply") -> int:
        return 2


class _CodexHarness:
    """输出恒为该用例给定的结构化回合输出；只记录喂进去的输入。"""

    def __init__(self, output: dict[str, Any]) -> None:
        self.output = output
        self.turns: list[list[Any]] = []

    async def create_thread(self, **kwargs):
        return {"thread": {"id": "thr-action"}}

    async def resume_thread(self, thread_id: str):
        return {"thread": {"id": thread_id}}

    async def inject_items(self, thread_id: str, items: list[dict]):
        return {}

    async def start_turn(self, *args, **kwargs):
        raise AssertionError("start_turn 不该被用到（collect 那条路在 ✓）")

    async def start_turn_and_collect(self, thread_id, input_items, output_schema=None, **kwargs):
        self.turns.append(input_items)

        @dataclass
        class Collected:
            status: str
            output: dict
            events: list
            turn_id: str = "turn-1"
            payload: dict = field(default_factory=dict)

        return Collected(status="completed", output=self.output, events=[])


class _SnapshotLoader:
    """权威快照来源：第 1 次是回合开头那份（v5），之后是"执行前后端已前进"的 v6。"""

    def __init__(self, workspace: dict[str, Any]) -> None:
        self.workspace = workspace
        self.calls = 0

    def __call__(self, **kwargs) -> dict[str, Any]:
        self.calls += 1
        version = int(self.workspace["version"]) + (1 if self.calls > 1 else 0)
        return {**self.workspace, "version": version}


class _Recorder:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[tuple, dict]] = []

    async def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.responses.pop(0) if self.responses else {}


@pytest.fixture(autouse=True)
def _isolate_internal_client(monkeypatch):
    """默认把两个 Java 端点换成"没人调用"的替身：用例各自按需覆盖 ✓。"""

    async def _unexpected(*args, **kwargs):
        raise AssertionError("本用例不该打 Java")

    monkeypatch.setattr(conversation_actions, "resolve_pending_confirmation", _unexpected)
    monkeypatch.setattr(conversation_actions, "execute_pending_planning_command", _unexpected)


def _workspace(version: int = 5) -> dict[str, Any]:
    return {
        "sessionId": "session-1",
        "version": version,
        "phase": "candidate_exploration",
        "studentSummary": {"provinceName": "浙江", "score": 650, "rank": 12000},
        "allowedCapabilities": ["catalog_read", "admission_read"],
        "activeProposal": {
            "proposalRef": "pending-1",
            "pendingId": "pending-1",
            "sourceVersion": version,
            "revision": 1,
            "kind": "plan_change",
            "data": {
                "operationId": "op-1",
                "proposalApply": {
                    "proposalId": "P1",
                    "proposalSource": "system",
                    "sourceVersionGuard": version,
                    "regenerateOrderedPlan": True,
                    "rerunReview": True,
                },
            },
        },
    }


def _output(action: dict[str, Any], *, message: str = "好的，我这就去确认。") -> dict[str, Any]:
    return {
        "responseType": "text",
        "message": message,
        "conversationAction": action,
    }


def _gateway(
    codex: _CodexHarness,
    workspace: dict[str, Any],
    task_ledger: Any | None = None,
) -> tuple[GatewayService, _SnapshotLoader]:
    loader = _SnapshotLoader(workspace)
    gateway = GatewayService(
        mode="codex_write",
        codex=codex,
        legacy=None,
        message_store=_MessageStore(),
        binding_loader=lambda **kwargs: ThreadBinding(
            thread_id="thr-action",
            tenant_id="tenant-1",
            session_id="session-1",
            user_id="user-1",
            allowed_capabilities=frozenset({"catalog_read", "admission_read"}),
        ),
        snapshot_loader=loader,
        task_ledger=task_ledger,
    )
    return gateway, loader


async def _turn(gateway: GatewayService, turn_id: str = "ui-1") -> dict[str, Any]:
    return await gateway.handle_turn(
        tenant_id="tenant-1",
        session_id="session-1",
        user_id="user-1",
        turn_id=turn_id,
        content="确认",
    )


@pytest.mark.asyncio
async def test_confirm_from_the_model_runs_the_card_path_and_lands_in_the_turn_result(monkeypatch):
    """① 打字"确认" → 执行链走完（claim→execute→complete），结果挂进回合结果 ✓。"""
    resolver = _Recorder([
        {"code": 0, "status": "applying", "data": {"revision": 2, "transitionApplied": True}},
        {"code": 0, "status": "completed"},
    ])
    executor = _Recorder([
        {"code": 0, "status": "applied", "data": {"stateVersion": 7, "actualChanges": [{"op": "keep"}]}},
    ])
    monkeypatch.setattr(conversation_actions, "resolve_pending_confirmation", resolver)
    monkeypatch.setattr(conversation_actions, "execute_pending_planning_command", executor)

    codex = _CodexHarness(_output({
        "actionType": "confirm_proposal",
        "proposalRef": "pending-1",
        "expectedSourceVersion": 5,
        "intent": "explicit",
    }))
    gateway, loader = _gateway(codex, _workspace())

    result = await _turn(gateway)

    assert result.get("error") is None, result
    # 结果按与 proposalRequest 对称的方式挂进回合结果 ✓（`_emit_turn_terminal` 据此发
    # `conversationAction.result` ✓；这里断言的就是那个键 ✓）。
    assert result["actionResult"]["actionStatus"] == "applied"
    assert result["actionResult"]["newStateVersion"] == 7
    # 执行成功后卡片对齐**执行后**的版本 ✓（与点卡路径 `execute_action_and_refresh` 一致 ✓）。
    assert result["snapshotVersion"] == 6

    # Java 调用形状：pending/resolve(confirm) ✓。
    assert len(resolver.calls) == 2 and len(executor.calls) == 1
    _, first = resolver.calls[0]
    assert first["tenant_id"] == "tenant-1" and first["pending_id"] == "pending-1"
    assert first["action"] == "confirm" and first["expected_revision"] == 1
    assert first["claim_token"], "confirm 必须带 claim token（Java 的 active→applying 要求 ✓）"
    # 第二段：pending-command/execute ✓，且复用**同一个** claim token ✓（新生成一个 Java 会拒 ✓）。
    _, execute_kwargs = executor.calls[0]
    assert execute_kwargs["command_type"] == "apply_plan_change_proposal"
    assert execute_kwargs["operation_id"] == "op-1", "幂等键必须来自 Java 的 pending（不许自铸）"
    assert execute_kwargs["expected_plan_version"] == 5
    assert execute_kwargs["claim_token"] == first["claim_token"]
    # 第三段：结果回写 pending（不回写会永远停在 applying ✓，重复确认看起来没事、其实没落地 ✗）。
    _, report = resolver.calls[1]
    assert report["action"] == "complete" and report["claim_token"] == first["claim_token"]
    assert loader.calls >= 3, "执行前要重读权威快照、执行后要刷新 ✓"


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["card", "text"])
@pytest.mark.parametrize("business_code", [0, 84009])
async def test_score_updates_share_the_same_execution_and_failure_contract(monkeypatch, entry, business_code):
    workspace = _workspace()
    workspace["activeProposal"].update(kind="score_update", actionFamily="update_score_detail")
    workspace["activeProposal"]["data"] = {
        "operationId": "op-score-1",
        "proposalSource": "score_update",
        "sourceVersion": 5,
        "scoreUpdateRequest": {"totalScore": 478, "totalScorePos": 131069},
    }
    action = {
        "actionType": "confirm_proposal", "proposalRef": "pending-1",
        "expectedSourceVersion": 5, "intent": "explicit",
    }
    resolver = _Recorder([
        {"code": 0, "data": {"status": "applying", "revision": 2, "transitionApplied": True}},
        {"code": 0, "data": {"status": "applied" if business_code == 0 else "expired"}},
    ])
    executor = _Recorder([
        {"code": 0, "data": {"status": "applied", "resultPlanVersion": 7}}
        if business_code == 0 else {"code": 84009, "msg": "当前策略已失效，请刷新页面"},
    ])
    monkeypatch.setattr(conversation_actions, "resolve_pending_confirmation", resolver)
    monkeypatch.setattr(conversation_actions, "execute_pending_planning_command", executor)
    gateway, _ = _gateway(_CodexHarness(_output(action)), workspace)

    if entry == "text":
        result = await _turn(gateway)
    else:
        async def emit(event):
            return None

        result = await _run_native_turn(
            gateway,
            SimpleNamespace(session_id="session-1", user_id="user-1", content="", conversation_action=action),
            "tenant-1", "ui-card", emit,
        )

    assert len(executor.calls) == 1
    execution = executor.calls[0][1]
    assert execution["command_type"] == "update_score_detail"
    assert execution["score_update"] == {"totalScore": 478, "totalScorePos": 131069}
    assert execution["operation_id"] == "op-score-1"
    assert execution["claim_token"] == resolver.calls[0][1]["claim_token"]
    assert result["actionResult"]["actionStatus"] == ("applied" if business_code == 0 else "failed")
    assert result["actionResult"]["code"] == str(business_code)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("java_response", "expected_status", "expected_code"),
    [
        # 冲突：Java 认得出这张卡已经不是当前那张（CAS 语义）→ stale_state ✓。
        ({"code": 0, "status": "conflict", "data": {"revision": 3}}, "stale_state", "0"),
        # 业务拒绝（RepairProposalApplyPolicy 的 400「当前调整预览不可应用」形状 ✓）。
        ({"code": 400, "msg": "当前调整预览不可应用"}, "failed", "400"),
    ],
)
async def test_a_rejected_confirm_reports_a_failure_code_instead_of_being_dropped(
    monkeypatch, java_response, expected_status, expected_code
):
    """② 失败/冲突**不抛**：回合照常收尾，结果带失败码（模型据此如实转述 ✓）。"""
    resolver = _Recorder([java_response])
    executor = _Recorder([])
    monkeypatch.setattr(conversation_actions, "resolve_pending_confirmation", resolver)
    monkeypatch.setattr(conversation_actions, "execute_pending_planning_command", executor)

    codex = _CodexHarness(_output({
        "actionType": "confirm_proposal",
        "proposalRef": "pending-1",
        "expectedSourceVersion": 5,
        "intent": "explicit",
    }))
    gateway, _ = _gateway(codex, _workspace())

    result = await _turn(gateway)

    assert result.get("error") is None, "执行失败是**结果**，不是整轮崩溃 ✗"
    assert result["actionResult"]["actionStatus"] == expected_status
    assert result["actionResult"]["code"] == expected_code
    assert result["actionResult"]["proposalRef"] == "pending-1"
    assert executor.calls == [], "claim 都没拿到，不许走到第二段执行 ✗"


@pytest.mark.asyncio
async def test_an_executor_crash_becomes_a_failed_result_not_a_broken_turn(monkeypatch):
    """③ 执行器抛异常 → failed 结果（有码有措辞）✓——不静默、也不整轮崩溃 ✓。"""
    resolver = _Recorder([{"code": 0, "status": "applying", "data": {"revision": 2, "transitionApplied": True}}])

    async def _boom(*args, **kwargs):
        raise RuntimeError("java down")

    monkeypatch.setattr(conversation_actions, "resolve_pending_confirmation", resolver)
    monkeypatch.setattr(conversation_actions, "execute_pending_planning_command", _boom)

    codex = _CodexHarness(_output({
        "actionType": "confirm_proposal",
        "proposalRef": "pending-1",
        "expectedSourceVersion": 5,
        "intent": "explicit",
    }))
    gateway, _ = _gateway(codex, _workspace())

    result = await _turn(gateway)

    assert result.get("error") is None
    assert result["actionResult"]["actionStatus"] == "failed"
    assert result["actionResult"]["code"] == "action_execution_exception"
    assert "未生效" in result["actionResult"]["message"]


@pytest.mark.asyncio
async def test_action_types_without_an_executor_are_rejected_as_contract_errors():
    """④ 无执行器的 create/refresh 不能静默变成“已生成”的正文承诺。"""
    codex = _CodexHarness(_output({
        "actionType": "refresh_proposal",
        "proposalRef": "pending-1",
        "intent": "explicit",
    }))
    gateway, _ = _gateway(codex, _workspace())

    result = await _turn(gateway)

    assert "conversation_action_not_executable" in str(result.get("error") or "")
    assert result.get("actionResult") is None, "没有执行器就**不许**凭空产一条结果事件 ✗"


@pytest.mark.asyncio
async def test_add_units_confirm_uses_frozen_command_and_skips_proposal_apply(monkeypatch):
    """点名加入：网关只发 5 个字段，不构造 proposalApply/canonical；
    回执 actualChanges/reviewState 透传到 conversationAction.result。"""
    resolver = _Recorder([
        {"code": 0, "status": "applying", "data": {"revision": 2, "transitionApplied": True}},
        {"code": 0, "status": "completed"},
    ])
    executor = _Recorder([
        {
            "code": 0,
            "status": "applied",
            "data": {
                "stateVersion": 7,
                "addedVolunteerIds": ["v2"],
                "addedVolunteerCount": 1,
                "addedUnitCount": 1,
                "removedVolunteerCount": 0,
                "targetCountBefore": 1,
                "targetCountAfter": 2,
                "reviewState": {"summary": {"passedCount": 10, "warnCount": 4, "riskCount": 0}},
            },
        },
    ])
    monkeypatch.setattr(conversation_actions, "resolve_pending_confirmation", resolver)
    monkeypatch.setattr(conversation_actions, "execute_pending_planning_command", executor)

    workspace = _workspace()
    workspace["activeProposal"] = {
        "proposalRef": "pending-1",
        "pendingId": "pending-1",
        "sourceVersion": 5,
        "revision": 1,
        "kind": "plan_action",
        "data": {
            "operationId": "op-1",
            "commandType": "add_units",
            "sourceVersion": 5,
        },
    }
    codex = _CodexHarness(_output({
        "actionType": "confirm_proposal",
        "proposalRef": "pending-1",
        "expectedSourceVersion": 5,
        "intent": "explicit",
    }))
    gateway, _ = _gateway(codex, workspace)

    result = await _turn(gateway)

    assert result.get("error") is None, result
    assert result["actionResult"]["actionStatus"] == "applied"
    assert result["actionResult"]["actualChanges"] == [{
        "type": "add",
        "volunteerIds": ["v2"],
        "addedCount": 1,
        "addedUnitCount": 1,
        "removedCount": 0,
        "targetCountBefore": 1,
        "targetCountAfter": 2,
    }]
    assert result["actionResult"]["reviewState"]["summary"]["warnCount"] == 4
    _, execute_kwargs = executor.calls[0]
    assert execute_kwargs["command_type"] == "add_units"
    assert execute_kwargs["expected_plan_version"] == 5
    assert "proposal_apply" not in execute_kwargs
    assert "volunteer_ids" not in execute_kwargs


@pytest.mark.asyncio
async def test_replace_units_confirm_uses_frozen_command_and_skips_proposal_apply(monkeypatch):
    """等量替换：网关同样只发 5 个字段，换入/换出集合由 Java 从 frozenCommand 读取。"""
    resolver = _Recorder([
        {"code": 0, "status": "applying", "data": {"revision": 2, "transitionApplied": True}},
        {"code": 0, "status": "completed"},
    ])
    executor = _Recorder([
        {
            "code": 0,
            "status": "applied",
            "data": {
                "stateVersion": 7,
                "commandType": "replace_units",
                "addedVolunteerIds": ["v3"],
                "addedVolunteerCount": 1,
                "addedUnitCount": 1,
                "removedVolunteerIds": ["v2"],
                "removedUnitIds": ["u2"],
                "removedVolunteerCount": 1,
                "targetCountBefore": 2,
                "targetCountAfter": 2,
                "reviewState": {"summary": {"passedCount": 10, "warnCount": 4, "riskCount": 0}},
            },
        },
    ])
    monkeypatch.setattr(conversation_actions, "resolve_pending_confirmation", resolver)
    monkeypatch.setattr(conversation_actions, "execute_pending_planning_command", executor)

    workspace = _workspace()
    workspace["activeProposal"] = {
        "proposalRef": "pending-2",
        "pendingId": "pending-2",
        "sourceVersion": 5,
        "revision": 1,
        "kind": "plan_action",
        "data": {
            "operationId": "op-2",
            "commandType": "replace_units",
            "sourceVersion": 5,
        },
    }
    codex = _CodexHarness(_output({
        "actionType": "confirm_proposal",
        "proposalRef": "pending-2",
        "expectedSourceVersion": 5,
        "intent": "explicit",
    }))
    gateway, _ = _gateway(codex, workspace)

    result = await _turn(gateway)

    assert result.get("error") is None, result
    assert result["actionResult"]["actionStatus"] == "applied"
    change = result["actionResult"]["actualChanges"][0]
    assert change["type"] == "replace"
    assert change["volunteerIds"] == ["v3"]
    assert change["removedVolunteerIds"] == ["v2"]
    assert change["removedUnitIds"] == ["u2"]
    assert change["removedCount"] == 1
    assert change["targetCountBefore"] == 2
    assert change["targetCountAfter"] == 2
    _, execute_kwargs = executor.calls[0]
    assert execute_kwargs["command_type"] == "replace_units"
    assert execute_kwargs["expected_plan_version"] == 5
    assert "proposal_apply" not in execute_kwargs
    assert "volunteer_ids" not in execute_kwargs
    assert "unit_ids" not in execute_kwargs


@pytest.mark.asyncio
async def test_remove_units_confirm_uses_frozen_command_and_reports_removed(monkeypatch):
    resolver = _Recorder([
        {"code": 0, "status": "applying", "data": {"revision": 2, "transitionApplied": True}},
        {"code": 0, "status": "completed"},
    ])
    executor = _Recorder([
        {
            "code": 0,
            "status": "applied",
            "data": {
                "stateVersion": 7,
                "commandType": "remove_units",
                "addedVolunteerCount": 0,
                "addedUnitCount": 0,
                "removedVolunteerIds": ["v2"],
                "removedUnitIds": ["u2"],
                "removedVolunteerCount": 1,
                "targetCountBefore": 2,
                "targetCountAfter": 1,
            },
        },
    ])
    monkeypatch.setattr(conversation_actions, "resolve_pending_confirmation", resolver)
    monkeypatch.setattr(conversation_actions, "execute_pending_planning_command", executor)

    workspace = _workspace()
    workspace["activeProposal"] = {
        "proposalRef": "pending-3",
        "pendingId": "pending-3",
        "sourceVersion": 5,
        "revision": 1,
        "kind": "plan_action",
        "data": {
            "operationId": "op-3",
            "commandType": "remove_units",
            "sourceVersion": 5,
        },
    }
    codex = _CodexHarness(_output({
        "actionType": "confirm_proposal",
        "proposalRef": "pending-3",
        "expectedSourceVersion": 5,
        "intent": "explicit",
    }))
    gateway, _ = _gateway(codex, workspace)

    result = await _turn(gateway)

    assert result.get("error") is None, result
    assert result["actionResult"]["actionStatus"] == "applied"
    change = result["actionResult"]["actualChanges"][0]
    assert change["type"] == "remove"
    assert change["removedVolunteerIds"] == ["v2"]
    assert change["removedUnitIds"] == ["u2"]
    assert change["removedCount"] == 1
    assert change["targetCountBefore"] == 2
    assert change["targetCountAfter"] == 1
    _, execute_kwargs = executor.calls[0]
    assert execute_kwargs["command_type"] == "remove_units"
    assert "proposal_apply" not in execute_kwargs
    assert "volunteer_ids" not in execute_kwargs
    assert "unit_ids" not in execute_kwargs


@pytest.mark.asyncio
async def test_move_units_confirm_uses_frozen_command_and_reports_positions(monkeypatch):
    resolver = _Recorder([
        {"code": 0, "status": "applying", "data": {"revision": 2, "transitionApplied": True}},
        {"code": 0, "status": "completed"},
    ])
    executor = _Recorder([
        {
            "code": 0,
            "status": "applied",
            "data": {
                "stateVersion": 7,
                "commandType": "move_units",
                "movedVolunteerIds": ["v2"],
                "movedUnitIds": [],
                "fromPosition": 2,
                "toPosition": 1,
                "targetCountBefore": 2,
                "targetCountAfter": 2,
            },
        },
    ])
    monkeypatch.setattr(conversation_actions, "resolve_pending_confirmation", resolver)
    monkeypatch.setattr(conversation_actions, "execute_pending_planning_command", executor)

    workspace = _workspace()
    workspace["activeProposal"] = {
        "proposalRef": "pending-4",
        "pendingId": "pending-4",
        "sourceVersion": 5,
        "revision": 1,
        "kind": "plan_action",
        "data": {
            "operationId": "op-4",
            "commandType": "move_units",
            "sourceVersion": 5,
        },
    }
    codex = _CodexHarness(_output({
        "actionType": "confirm_proposal",
        "proposalRef": "pending-4",
        "expectedSourceVersion": 5,
        "intent": "explicit",
    }))
    gateway, _ = _gateway(codex, workspace)

    result = await _turn(gateway)

    assert result.get("error") is None, result
    assert result["actionResult"]["actionStatus"] == "applied"
    change = result["actionResult"]["actualChanges"][0]
    assert change["type"] == "move"
    assert change["movedVolunteerIds"] == ["v2"]
    assert change["fromPosition"] == 2
    assert change["toPosition"] == 1
    receipt = result["actionResult"]["receipt"]
    assert result["actionResult"]["origin"] == "user"
    assert result["actionResult"]["actionType"] == "move_units"
    assert result["actionResult"]["scope"] == "plan"
    assert receipt["operationId"] == "op-4"
    assert receipt["reorderedCount"] == 1
    assert receipt["before"] == 2
    assert receipt["after"] == 2
    assert "summary" not in receipt, "回执摘要不重复审查摘要"
    _, execute_kwargs = executor.calls[0]
    assert execute_kwargs["command_type"] == "move_units"
    assert "proposal_apply" not in execute_kwargs
    assert "volunteer_ids" not in execute_kwargs


@pytest.mark.asyncio
async def test_confirm_cannot_be_combined_with_a_new_proposal_draft():
    """确认 + 新条件 = 纠正，不是原卡确认；契约层直接拒绝同轮 confirm+新草稿。"""
    output = _output({
        "actionType": "confirm_proposal",
        "proposalRef": "pending-1",
        "expectedSourceVersion": 5,
        "intent": "explicit",
    })
    output["proposalRequest"] = {
        "goalType": "fill_to_count",
        "userOriginalText": "确认，但补到 50",
        "confidence": "high",
        "sourceVersionGuard": 5,
        "targetCount": 50,
    }
    codex = _CodexHarness(output)
    gateway, _ = _gateway(codex, _workspace())

    result = await _turn(gateway)

    assert str(result.get("error", "")).startswith(
        "confirmation_conflicts_with_new_intent"
    ), result


def _composite_intent_draft() -> dict:
    return {
        "sourceTurnId": "t-composite",
        "userText": "加 A，学费三万内",
        "goalFamily": "plan_mutation",
        "action": "add",
        "targets": [{"schoolName": "A大学", "majorName": "计算机"}],
        "scopes": [
            {"scopeType": "tuition", "name": "30000", "strength": "must"}
        ],
        "validity": "unknown",
        "intentConfidence": 0.8,
    }


@pytest.mark.asyncio
async def test_composite_intent_drops_the_partial_add_proposal_but_keeps_the_text():
    """复合草稿同轮带提案：**丢弃提案、保留正文**，不把整轮判失败。

    2026-10-18 真栈：模型在 `unresolved` 非空时仍附带 add 提案 → 整轮被拒，
    用户只看到“引擎暂不可用”，正文里的澄清说明反而丢了。守卫的目的只是
    “不许先执行子动作”，不是“让整轮失败”。
    """
    output = _output({"actionType": "none", "intent": "not_applicable"})
    output["intentDraft"] = _composite_intent_draft()
    output["proposalRequest"] = {
        "goalType": "add_units",
        "userOriginalText": "加 A",
        "confidence": "high",
        "sourceVersionGuard": 5,
        "exactTargets": [{"schoolName": "A大学", "majorName": "计算机"}],
    }
    codex = _CodexHarness(output)
    gateway, _ = _gateway(codex, _workspace())

    result = await _turn(gateway)

    assert result.get("error") is None, result
    out = result["output"]
    proposal = out.get("proposalRequest") if isinstance(out, dict) else out.proposal_request
    proposal_ref = out.get("proposalRef") if isinstance(out, dict) else out.proposal_ref
    limitations = out.get("limitations") if isinstance(out, dict) else out.limitations
    assert proposal is None
    assert proposal_ref is None
    assert any("附带的提案已取消" in item for item in limitations)
    message = out.get("message") if isinstance(out, dict) else out.message
    assert "本轮没有生成可确认的卡片" in message


@pytest.mark.asyncio
async def test_composite_intent_without_partial_proposal_is_allowed_as_text():
    output = _output({"actionType": "none", "intent": "not_applicable"})
    output["intentDraft"] = _composite_intent_draft()
    codex = _CodexHarness(output)
    gateway, _ = _gateway(codex, _workspace())

    result = await _turn(gateway)

    assert result.get("error") is None, result


@pytest.mark.asyncio
async def test_confirm_old_card_cannot_carry_a_new_intent_draft():
    """确认旧卡 + 新要求（即使没有 proposalRequest）也必须重新预览。"""
    output = _output({
        "actionType": "confirm_proposal",
        "proposalRef": "pending-1",
        "expectedSourceVersion": 5,
        "intent": "explicit",
    })
    output["intentDraft"] = _composite_intent_draft()
    codex = _CodexHarness(output)
    gateway, _ = _gateway(codex, _workspace())

    result = await _turn(gateway)

    assert str(result.get("error", "")).startswith(
        "confirmation_conflicts_with_new_intent"
    ), result


class _FakeTaskLedger:
    def __init__(self) -> None:
        self.data: dict[tuple[str, str], dict] = {}

    async def load(self, tenant_id: str, session_id: str):
        return self.data.get((tenant_id, session_id))

    async def save(self, tenant_id: str, session_id: str, task: dict) -> bool:
        self.data[(tenant_id, session_id)] = task
        return True

    async def clear(self, tenant_id: str, session_id: str) -> None:
        self.data.pop((tenant_id, session_id), None)


@pytest.mark.asyncio
async def test_task_draft_is_saved_and_reloaded_across_turns():
    ledger = _FakeTaskLedger()
    first_output = _output({"actionType": "none", "intent": "not_applicable"})
    first_output["intentDraft"] = _composite_intent_draft()
    first = _CodexHarness(first_output)
    gateway, _ = _gateway(first, _workspace(), task_ledger=ledger)

    result = await _turn(gateway, "ui-1")

    assert result.get("error") is None, result
    saved = ledger.data[("tenant-1", "session-1")]
    assert saved["changeSet"]["status"] == "needs_constraints_first"
    assert result["workingSet"]["taskDraft"]["turnId"] == "ui-1"

    second = _CodexHarness(_output({"actionType": "none", "intent": "not_applicable"}))
    gateway2, _ = _gateway(second, _workspace(), task_ledger=ledger)
    result2 = await _turn(gateway2, "ui-2")

    assert result2.get("error") is None, result2
    assert result2["workingSet"]["taskDraft"]["changeSet"]["status"] == (
        "needs_constraints_first"
    )
    assert result2["workingSet"]["taskDraft"]["turnId"] == "ui-1"


@pytest.mark.asyncio
async def test_cancel_proposal_clears_persisted_task_draft():
    ledger = _FakeTaskLedger()
    first_output = _output({"actionType": "none", "intent": "not_applicable"})
    first_output["intentDraft"] = _composite_intent_draft()
    gateway, _ = _gateway(_CodexHarness(first_output), _workspace(), task_ledger=ledger)
    await _turn(gateway, "ui-1")
    assert ("tenant-1", "session-1") in ledger.data

    cancel_output = _output({
        "actionType": "cancel_proposal",
        "proposalRef": "pending-1",
        "intent": "explicit",
    })
    gateway2, _ = _gateway(_CodexHarness(cancel_output), _workspace(), task_ledger=ledger)
    await _turn(gateway2, "ui-2")

    assert ("tenant-1", "session-1") not in ledger.data
