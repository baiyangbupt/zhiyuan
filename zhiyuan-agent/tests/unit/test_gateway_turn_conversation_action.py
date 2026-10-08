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
from typing import Any

import pytest

from app.gateway import conversation_actions
from app.gateway.service import GatewayService
from app.harness.binding import ThreadBinding


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


def _gateway(codex: _CodexHarness, workspace: dict[str, Any]) -> tuple[GatewayService, _SnapshotLoader]:
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
        {"code": 0, "status": "applying", "data": {"revision": 2}},
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
    resolver = _Recorder([{"code": 0, "status": "applying", "data": {"revision": 2}}])

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
async def test_action_types_without_an_executor_keep_the_old_behaviour():
    """④ `refresh_proposal` 这类没有执行器的动作：不执行、不产结果事件 ✓（原行为不动 ✓）。"""
    codex = _CodexHarness(_output({
        "actionType": "refresh_proposal",
        "proposalRef": "pending-1",
        "intent": "explicit",
    }))
    gateway, _ = _gateway(codex, _workspace())

    result = await _turn(gateway)

    assert result.get("error") is None
    assert result.get("actionResult") is None, "没有执行器就**不许**凭空产一条结果事件 ✗"
