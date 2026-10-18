from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.gateway.conversation_actions import _actual_changes, execute_conversation_action
from app.gateway.service import GatewayService
from app.gateway.ui_events import SessionKey
from app.server import _run_native_turn


def snapshot():
    return {
        "snapshotVersion": 7,
        "sessionId": "s1",
        "activeProposal": {
            "proposalRef": "pending-1",
            "pendingId": "pending-1",
            "sourceVersion": 7,
            "revision": 3,
        },
    }


def test_constraint_apply_receipt_reports_count_and_shortage():
    """约束类命令没有逐条 added/removed：回执要给出总数前后与缺口。

    2026-10-18 真栈：学费清理把 51 组换成 36 组，`actualChanges` 仍是 `{}`，
    卡上只能显示"已生效"，用户看不到缩水。这里钉住合成回执。
    """
    changes = _actual_changes({
        "commandType": "apply_constraint_and_regenerate",
        "targetCountBefore": 51,
        "targetCountAfter": 36,
        "postconditionReport": {
            "countMode": "unit",
            "countBefore": 51,
            "actualCount": 36,
            "targetCount": 45,
            "shortage": 15,
        },
    })

    assert changes == [{
        "type": "constraint",
        "countMode": "unit",
        "targetCountBefore": 51,
        "targetCountAfter": 36,
        "actualCount": 36,
        "requiredCount": 45,
        "shortage": 15,
    }]


def test_scope_constraint_receipt_keeps_zero_shortage():
    """only_keep/exclude 的收缩是预期结果：回执照常报前后数量，但 shortage=0。"""
    changes = _actual_changes({
        "commandType": "apply_constraint_and_regenerate",
        "targetCountBefore": 132,
        "targetCountAfter": 12,
        "postconditionReport": {"countMode": "unit", "shortage": 0},
    })

    assert changes[0]["type"] == "constraint"
    assert changes[0]["targetCountBefore"] == 132
    assert changes[0]["targetCountAfter"] == 12
    assert changes[0]["shortage"] == 0


@pytest.mark.asyncio
async def test_confirm_bridges_to_pending_resolve():
    calls = []

    async def resolver(*args, **kwargs):
        calls.append((args, kwargs))
        return {"code": 0, "data": {"status": "applied", "stateVersion": 8, "actualChanges": [{"target": "school-3"}]}}

    result = await execute_conversation_action(
        tenant_id="tenant-7",
        session_id="s1",
        action={"actionType": "confirm_proposal", "proposalRef": "pending-1", "expectedSourceVersion": 7},
        snapshot=snapshot(),
        resolver=resolver,
    )

    assert result.action_status == "applied"
    assert result.new_state_version == 8
    assert calls[0][1]["tenant_id"] == "tenant-7"
    assert calls[0][1]["pending_id"] == "pending-1"
    assert calls[0][1]["expected_revision"] == 3
    assert calls[0][1]["action"] == "confirm"
    assert len(calls[0][1]["claim_token"]) == 32


@pytest.mark.asyncio
async def test_confirm_claim_is_reported_as_applying_until_command_completes():
    """claim 的 `applying` **不是终态**：P2 之后它会继续走 execute，结果以 execute 为准。"""

    async def resolver(*args, **kwargs):
        return {"code": 0, "data": {"status": "applying", "revision": 4}}

    async def executor(*args, **kwargs):
        return {"code": 0, "data": {"status": "applied", "stateVersion": 9}}

    result = await execute_conversation_action(
        tenant_id="tenant-7",
        session_id="s1",
        action={"actionType": "confirm_proposal", "proposalRef": "pending-1"},
        snapshot=snapshot_with_pending(),
        resolver=resolver,
        executor=executor,
    )
    assert result.action_status == "applied"
    assert result.new_state_version == 9


@pytest.mark.asyncio
async def test_expected_source_version_fails_closed_when_snapshot_omits_source_version():
    current = snapshot()
    current["activeProposal"].pop("sourceVersion")
    async def resolver(*args, **kwargs):
        raise AssertionError("must not call backend")

    result = await execute_conversation_action(
        tenant_id="tenant-7",
        session_id="s1",
        action={"actionType": "cancel_proposal", "proposalRef": "pending-1", "expectedSourceVersion": 7},
        snapshot=current,
        resolver=resolver,
    )
    assert result.action_status == "stale_state"
    assert result.code == "proposal_version_missing"


@pytest.mark.asyncio
async def test_source_version_can_be_read_from_pending_data():
    current = snapshot()
    current["activeProposal"].pop("sourceVersion")
    current["activeProposal"]["data"] = {"sourceBackendVersion": 7}
    async def resolver(*args, **kwargs):
        return {"status": "cancelled", "data": {"revision": 4}}

    result = await execute_conversation_action(
        tenant_id="tenant-7",
        session_id="s1",
        action={"actionType": "cancel_proposal", "proposalRef": "pending-1", "expectedSourceVersion": 7},
        snapshot=current,
        resolver=resolver,
    )
    assert result.action_status == "cancelled"


@pytest.mark.asyncio
async def test_cancel_maps_backend_conflict_to_stale_state():
    async def resolver(*args, **kwargs):
        return {"status": "stale_state", "code": "STALE"}

    result = await execute_conversation_action(
        tenant_id="tenant-7",
        session_id="s1",
        action={"actionType": "cancel_proposal", "proposalRef": "pending-1", "expectedSourceVersion": 7},
        snapshot=snapshot(),
        resolver=resolver,
    )
    assert result.action_status == "stale_state"


@pytest.mark.asyncio
async def test_non_executable_action_does_not_call_backend():
    async def resolver(*args, **kwargs):
        raise AssertionError("must not call backend")

    result = await execute_conversation_action(
        tenant_id="tenant-7",
        session_id="s1",
        action={"actionType": "create_proposal"},
        snapshot=snapshot(),
        resolver=resolver,
    )
    assert result.action_status == "not_executable"


@pytest.mark.asyncio
async def test_execute_action_and_refresh_replaces_cached_snapshot():
    refreshed = {"snapshotVersion": 8, "sessionId": "s1", "activeProposal": None}

    async def snapshot_loader(**kwargs):
        return refreshed

    gateway = GatewayService(
        mode="codex_readonly",
        codex=None,
        legacy=None,
        message_store=None,
        binding_loader=lambda **kwargs: None,
        snapshot_loader=snapshot_loader,
    )
    resolver = AsyncMock(return_value={"code": 0, "data": {"status": "applied", "stateVersion": 8}})
    with patch(
        "app.gateway.conversation_actions.resolve_pending_confirmation",
        new=resolver,
    ):
        result = await gateway.execute_action_and_refresh(
            tenant_id="t1",
            session_id="s1",
            action={"actionType": "confirm_proposal", "proposalRef": "pending-1"},
            snapshot=snapshot(),
        )
    assert result["actionResult"]["actionStatus"] == "applied"
    assert result["snapshotVersion"] == 8
    assert gateway._snapshots[SessionKey(tenant_id="t1", session_id="s1")].snapshot_version == 8
    assert resolver.await_args.kwargs["tenant_id"] == "t1"


@pytest.mark.asyncio
async def test_a_failed_snapshot_refresh_does_not_lose_the_applied_result():
    """写入已落地、重读快照那一步失败：**终局照原样带回** ✓✓。

    任务书的不变量：只要 execute 回了终局（applied/cancelled/failed ✓），
    `conversationAction.result` 就必须进事件流（可丢帧、不可丢流 ✓）。
    重读是**顺带**刷新缓存 ✓——它把异常抛出去 ✗ 的话，调用方只会回一条通用
    `gateway_failure` ✗、`actionResult` 随之丢失 ✗ → 结果事件永远发不出去 ✗，
    而库里那次写入**是成功的** ✓：页面上卡停在"待确认" ✗（用户只能反复点 ✓✗）。
    """

    async def snapshot_loader(**kwargs):
        raise RuntimeError("java read failed")

    gateway = GatewayService(
        mode="codex_readonly",
        codex=None,
        legacy=None,
        message_store=None,
        binding_loader=lambda **kwargs: None,
        snapshot_loader=snapshot_loader,
    )
    resolver = AsyncMock(return_value={"code": 0, "data": {"status": "applied", "stateVersion": 8}})
    with patch(
        "app.gateway.conversation_actions.resolve_pending_confirmation",
        new=resolver,
    ):
        result = await gateway.execute_action_and_refresh(
            tenant_id="t1",
            session_id="s1",
            action={"actionType": "confirm_proposal", "proposalRef": "pending-1"},
            snapshot=snapshot(),
        )

    assert result["actionResult"]["actionStatus"] == "applied"  # 终局没被吞掉 ✓
    assert "snapshotVersion" not in result  # 没读到就没有版本号 ✓
    # 缓存不写坏值 ✓：这次读失败不进缓存 ✓（下一轮会自己重读 ✓）。
    assert SessionKey(tenant_id="t1", session_id="s1") not in gateway._snapshots


@pytest.mark.asyncio
async def test_action_path_executes_on_the_authoritative_snapshot_not_the_stale_cache():
    """缓存 stale、Java 已更新时，确认必须按**权威**快照执行 ✓✓。

    缓存优先的 `get_current_snapshot` 在这条路上会拿到旧快照 ✗（用户刚补录成绩、
    或在另一条线写了工作区 ✓）→ `expectedSourceVersion` 对不上 → 一张本该能点的卡
    被误判 `stale_state` ✓✗。本用例模拟该时序：先用旧快照把缓存养起来，再让 Java
    侧推进版本，最后走真实 `_run_native_turn`——修前它红在 `stale_state` 上（执行器
    根本不会被调用）。
    """
    stale = snapshot()  # sourceVersion 7：上一轮缓存里的那份
    fresh = {
        **snapshot(),
        "snapshotVersion": 8,
        "activeProposal": {**snapshot()["activeProposal"], "sourceVersion": 8},
    }

    class _Loader:
        def __init__(self):
            self.current = stale

        async def __call__(self, **kwargs):
            return self.current

    loader = _Loader()
    gateway = GatewayService(
        mode="codex_write",
        codex=None,
        legacy=None,
        message_store=None,
        binding_loader=lambda **kwargs: None,
        snapshot_loader=loader,
    )
    cached = await gateway.get_current_snapshot(tenant_id="t1", session_id="s1")
    assert cached.snapshot_version == 7  # 缓存里钉着旧的那份 ✓
    loader.current = fresh  # —— Java 侧状态已推进（补录/写工作区）

    resolver = AsyncMock(return_value={"code": 0, "data": {"status": "applied", "stateVersion": 9}})
    msg = SimpleNamespace(
        session_id="s1",
        conversation_action={
            "actionType": "confirm_proposal",
            "proposalRef": "pending-1",
            # 用户手里那张卡是新版本：拿旧快照比对就会被误判 stale_state ✗
            "expectedSourceVersion": 8,
        },
    )
    with patch("app.gateway.conversation_actions.resolve_pending_confirmation", new=resolver):
        result = await _run_native_turn(gateway, msg, "t1", "turn-1", None)

    assert result["actionResult"]["actionStatus"] == "applied", result
    resolver.assert_awaited_once()
    # 重读回来的权威快照要写进缓存 ✓（authoritative 语义：版本合法回退也照收 ✓）
    assert gateway._snapshots[SessionKey(tenant_id="t1", session_id="s1")].snapshot_version == 8


@pytest.mark.asyncio
@pytest.mark.parametrize(("response", "expected_status"), [
    ({"code": 0, "data": {"status": "cancelled"}}, "cancelled"),
    ({"code": 0, "data": {"status": "expired"}}, "expired"),
    ({"code": 0, "data": {"status": "stale_state"}}, "stale_state"),
    ({"code": 0, "data": {"status": "active"}}, "failed"),
    ({"code": 0, "data": {}}, "failed"),
    ({"code": 0, "data": {"status": "unknown"}}, "failed"),
    ({"code": 40001, "data": {"status": "applied"}}, "failed"),
])
async def test_resolve_requires_explicit_execution_status(response, expected_status):
    result = await execute_conversation_action(
        tenant_id="t1", session_id="s1",
        action={"actionType": "cancel_proposal", "proposalRef": "pending-1"},
        snapshot=snapshot(), resolver=AsyncMock(return_value=response),
    )
    assert result.action_status == expected_status


@pytest.mark.asyncio
async def test_zero_source_version_is_not_treated_as_missing():
    current = snapshot()
    current["activeProposal"]["sourceVersion"] = 0
    current["activeProposal"]["data"] = {"sourceBackendVersion": 7}
    resolver = AsyncMock(return_value={"code": 0, "data": {"status": "cancelled"}})
    result = await execute_conversation_action(
        tenant_id="t1", session_id="s1",
        action={"actionType": "cancel_proposal", "proposalRef": "pending-1", "expectedSourceVersion": 0},
        snapshot=current, resolver=resolver,
    )
    assert result.action_status == "cancelled"
    resolver.assert_awaited_once()


# ── P2：confirm → claim → execute 两段式（四类异常各一条 + 对照）──────────────────
#
# 反例要求（任务书四）："重复确认"要给出**双写为零**的证据——这里是替身层面的证据
# （execute 只被调一次）；真实栈的落库计数在 P2 报告第二节（那一步要真 Java）。


def snapshot_with_pending(data: dict | None = None) -> dict:
    """带 pending data 的快照（Java 把 pending 的 dataValue 原样放在 activeProposal.data）。"""
    current = snapshot()
    current["activeProposal"]["data"] = {
        "operationId": "op-9",
        "proposalId": "proposal-9",
        "proposalSource": "user_goal",
        **(data or {}),
    }
    return current


@pytest.mark.asyncio
async def test_confirm_runs_claim_then_execute_with_the_same_claim_token():
    """对照（正常路径）：claim 与 execute 用**同一个** claim token，形状是扁平的。

    任务书把"claimToken 复用"点名为最容易错的一点：新生成一个 → Java 拒。
    同时断言 proposalApply 是**扁平**形状（不照抄 legacy 的 executionPayload 包装层）。
    """
    claim_tokens = []
    execute_calls = []

    async def resolver(*args, **kwargs):
        claim_tokens.append(kwargs.get("claim_token"))
        return {"code": 0, "data": {"status": "applying", "revision": 4}}

    async def executor(*args, **kwargs):
        execute_calls.append(kwargs)
        return {"code": 0, "data": {"status": "applied", "stateVersion": 9}}

    result = await execute_conversation_action(
        tenant_id="tenant-7", session_id="s1",
        action={"actionType": "confirm_proposal", "proposalRef": "pending-1", "expectedSourceVersion": 7},
        snapshot=snapshot_with_pending(),
        resolver=resolver, executor=executor,
    )

    assert result.action_status == "applied"
    assert execute_calls, "claim 之后必须走 execute"
    call = execute_calls[0]
    assert call["claim_token"] == claim_tokens[0], "claim token 必须复用"
    assert call["operation_id"] == "op-9", "operationId 用 Java 产出的那个"
    assert call["pending_id"] == "pending-1"
    assert call["command_type"] == "apply_plan_change_proposal"
    assert call["expected_plan_version"] == 7
    assert "executionPayload" not in call["proposal_apply"], "不许照抄 legacy 的包装层"
    assert call["proposal_apply"]["proposalId"] == "proposal-9"
    # Java **要求**这两个开关为 true（"plan change apply requires regenerateOrderedPlan
    # and rerunReview"）——曾经按"保守取 false"写，真栈上被 40001 直接拒 ✗（2026-09-24 实测）。
    assert call["proposal_apply"]["regenerateOrderedPlan"] is True
    assert call["proposal_apply"]["rerunReview"] is True


async def _claim_then_execute(monkeypatch, goal: dict | None, *, snapshot_extra: dict | None = None):
    """跑一遍 confirm→execute，把 execute 收到的 kwargs 带回来（scope 映射四条共用）。"""
    execute_calls = []

    async def resolver(session_id, **kwargs):
        if kwargs.get("action") in {"complete", "fail"}:
            return {"code": 0, "data": {"status": "applied"}}
        return {"code": 0, "data": {"status": "applying", "revision": 4}}

    async def executor(*args, **kwargs):
        execute_calls.append(kwargs)
        return {"code": 0, "data": {"status": "applied", "stateVersion": 9}}

    current = snapshot_with_pending({"userGoalRequest": goal} if goal is not None else None)
    current.update(snapshot_extra or {})
    result = await execute_conversation_action(
        tenant_id="tenant-7", session_id="s1",
        action={"actionType": "confirm_proposal", "proposalRef": "pending-1"},
        snapshot=current, resolver=resolver, executor=executor,
    )
    return result, execute_calls


@pytest.mark.asyncio
async def test_scope_goal_routes_to_the_constraint_command() -> None:
    """范围类目标（加学校）走 `apply_constraint_and_regenerate` + `constraintUpdate` ✓。

    依据：`apply_plan_change_proposal` 的 user-goal 分支只认计数/排序两种 ✗——范围类会被
    40001 `unsupported plan change goalType` 拒 ✓（2026-09-24 真栈实测）；
    legacy 链一直用 constraint 那条 ✓（`app/zhiyuan_agent/tools.py` 的参照 ✓）。
    """
    result, calls = await _claim_then_execute(None, {
        "goalType": "must_include_scope",
        "targetScopes": [{"scopeType": "school", "name": "浙江大学"}],
        "negativeScopes": [],
    })

    assert result.action_status == "applied"
    call = calls[0]
    assert call["command_type"] == "apply_constraint_and_regenerate"
    assert call["constraint_update"] == {
        "intentMode": "constraint",
        "schoolPreferences": {"positive": ["浙江大学"], "negative": []},
    }
    assert call["regenerate_ordered_plan"] is True
    assert "proposal_apply" not in call, "约束那条命令不吃 proposalApply"


@pytest.mark.asyncio
async def test_scope_goal_carries_every_kind_of_scope() -> None:
    """三类范围各进各的束：school→schoolPreferences、major→majorPreferences、region 同理 ✓；
    负向进 negative ✓（删学校/去城市就是这一类 ✓）。"""
    # 目录查询**打桩** ✓：否则测试会去打本机目录 ✗（跑得快慢取决于环境 ✓，
    # 而且是"测试打到真服务"这种最不该有的耦合 ✗）。
    await _stub_catalog({"北京": "110000"})
    _, calls = await _claim_then_execute(None, {
        "goalType": "exclude_scope",
        "targetScopes": [{"scopeType": "major", "name": "临床医学"}],
        "negativeScopes": [{"scopeType": "province", "name": "北京"},
                           {"scopeType": "school", "name": "甲大学"}],
    })

    assert calls[0]["constraint_update"] == {
        "intentMode": "constraint",
        "majorPreferences": {"positive": ["临床医学"], "negative": []},
        "regionPreferences": {"positive": [], "negative": ["北京"]},
        # 区域**同时**带权威 ID ✓（与名字同序、同正负 ✓）——其余三类不带 ID ✓（区域先行 ✓）。
        "regionPreferenceIds": {"positive": [], "negative": ["110000"]},
        "schoolPreferences": {"positive": [], "negative": ["甲大学"]},
    }


@pytest.mark.asyncio
async def test_tuition_scope_carries_the_bounds() -> None:
    """学费类目标走同一命令，但参数是上下限（legacy 那条路亦然 ✓）。"""
    _, calls = await _claim_then_execute(None, {
        "goalType": "tuition_budget_scope",
        "context": {"maxTuitionPerYear": 8000},
    })

    assert calls[0]["command_type"] == "apply_constraint_and_regenerate"
    assert calls[0]["max_tuition_per_year"] == 8000
    assert "constraint_update" not in calls[0]


@pytest.mark.asyncio
async def test_unmappable_goal_scope_refuses_to_execute() -> None:
    """不认识的 `scopeType` → **拒绝执行** ✓：静默丢掉一条排除（用户看不见地在方案里
    留着他要去掉的学校）比整轮失败糟得多。"""
    result, calls = await _claim_then_execute(None, {
        "goalType": "exclude_scope",
        "negativeScopes": [{"scopeType": "galaxy", "name": "银河系"}],
    })

    assert result.action_status == "failed"
    assert result.code == "unmappable_goal_scope"
    assert calls == []


@pytest.mark.asyncio
async def test_counting_goal_still_uses_the_plan_change_command() -> None:
    """对照：计数/排序类**行为不变** ✓（原路径 + 扁平 proposalApply ✓）。"""
    _, calls = await _claim_then_execute(None, {"goalType": "fill_to_count", "targetCount": 80})

    assert calls[0]["command_type"] == "apply_plan_change_proposal"
    assert calls[0]["proposal_apply"]["proposalId"] == "proposal-9"


@pytest.mark.asyncio
async def test_stale_revision_on_claim_refuses_and_never_executes():
    """异常 1（陈旧 revision）：claim 被判 stale → 拒绝执行、如实回话。"""
    async def resolver(*args, **kwargs):
        return {"code": 0, "data": {"status": "stale_state"}}

    async def executor(*args, **kwargs):
        raise AssertionError("stale 时不许执行")

    result = await execute_conversation_action(
        tenant_id="tenant-7", session_id="s1",
        action={"actionType": "confirm_proposal", "proposalRef": "pending-1"},
        snapshot=snapshot_with_pending(), resolver=resolver, executor=executor,
    )
    assert result.action_status == "stale_state"


@pytest.mark.asyncio
async def test_duplicate_confirm_executes_only_once():
    """异常 2（重复确认）：第二次确认**不得双写**。

    真实栈的防线是 Java 的幂等键（operationId）；这里量网关侧的行为——
    第二次 resolve 不再是 applying（pending 已不 active），于是**不再执行**。
    """
    resolve_results = [
        {"code": 0, "data": {"status": "applying", "revision": 4}},
        {"code": 0, "data": {"status": "stale_state"}},
    ]
    executions = []

    async def resolver(*args, **kwargs):
        # 回写（complete/fail）与 claim 分开应答：回写是链路最后一段，
        # 不属于"第几次确认"的计数。
        if kwargs.get("action") in {"complete", "fail"}:
            return {"code": 0, "data": {"status": "applied"}}
        return resolve_results.pop(0)

    async def executor(*args, **kwargs):
        executions.append(kwargs["operation_id"])
        return {"code": 0, "data": {"status": "applied", "stateVersion": 9}}

    first = await execute_conversation_action(
        tenant_id="tenant-7", session_id="s1",
        action={"actionType": "confirm_proposal", "proposalRef": "pending-1"},
        snapshot=snapshot_with_pending(), resolver=resolver, executor=executor,
    )
    second = await execute_conversation_action(
        tenant_id="tenant-7", session_id="s1",
        action={"actionType": "confirm_proposal", "proposalRef": "pending-1"},
        snapshot=snapshot_with_pending(), resolver=resolver, executor=executor,
    )

    assert first.action_status == "applied"
    assert second.action_status == "stale_state"
    assert executions == ["op-9"], f"只许执行一次，实际 {executions}"


@pytest.mark.asyncio
async def test_expired_proposal_is_refused_without_executing():
    """异常 3（过期 Proposal）：拒绝，并把"要重新生成"这句如实带回来。"""
    async def resolver(*args, **kwargs):
        return {"code": 0, "data": {"status": "expired"}, "msg": "该预览已过期，请重新生成"}

    async def executor(*args, **kwargs):
        raise AssertionError("过期时不许执行")

    result = await execute_conversation_action(
        tenant_id="tenant-7", session_id="s1",
        action={"actionType": "confirm_proposal", "proposalRef": "pending-1"},
        snapshot=snapshot_with_pending(), resolver=resolver, executor=executor,
    )
    assert result.action_status == "expired"
    assert "重新生成" in (result.message or "")


@pytest.mark.asyncio
async def test_execute_failure_is_reported_as_failed_not_completed():
    """异常 4（执行失败）：状态落 failed，**不许报 completed**（P2b 只降不升同理）。"""
    async def resolver(*args, **kwargs):
        return {"code": 0, "data": {"status": "applying", "revision": 4}}

    async def executor(*args, **kwargs):
        return {"code": 500, "data": {"status": "failed"}, "msg": "backend exploded"}

    result = await execute_conversation_action(
        tenant_id="tenant-7", session_id="s1",
        action={"actionType": "confirm_proposal", "proposalRef": "pending-1"},
        snapshot=snapshot_with_pending(), resolver=resolver, executor=executor,
    )
    assert result.action_status == "failed"
    assert result.action_status != "applied"


@pytest.mark.asyncio
async def test_missing_operation_id_refuses_to_execute():
    """operationId 只能来自 Java 编译产出：pending 里没有 → **拒绝执行**，不自铸幂等键。"""
    async def resolver(*args, **kwargs):
        return {"code": 0, "data": {"status": "applying", "revision": 4}}

    async def executor(*args, **kwargs):
        raise AssertionError("没有 operationId 时不许执行")

    current = snapshot_with_pending()
    current["activeProposal"]["data"].pop("operationId")
    result = await execute_conversation_action(
        tenant_id="tenant-7", session_id="s1",
        action={"actionType": "confirm_proposal", "proposalRef": "pending-1"},
        snapshot=current, resolver=resolver, executor=executor,
    )
    assert result.action_status == "failed"
    assert result.code == "operation_id_missing"


@pytest.mark.asyncio
async def test_constraint_apply_status_comes_from_postcondition_report() -> None:
    """约束路的成败读 `postconditionReport.satisfied`——这条响应里**没有** `status` ✓。

    真栈形态（2026-09-25）：`apply_constraint_and_regenerate` 的响应只有
    `commandType/completedSteps/operationId/pendingId/planningState/replayed/resultPlanVersion/sourcePlanVersion`
    ✗，既无 `status` 也无 `postconditionReport`（那次是 null）→ 网关兜底判 `failed` ✗，
    于是"成功报不出来、失败也不是判出来的" ✓。Java 侧本轮补上满足度报告（不满足还抛 40905 回滚）✓。
    """
    async def resolver(session_id, **kwargs):
        if kwargs.get("action") in {"complete", "fail"}:
            return {"code": 0, "data": {"status": "applied"}}
        return {"code": 0, "data": {"status": "applying", "revision": 4}}

    async def executor(*args, **kwargs):
        return {
            "code": 0,
            "data": {
                "completedSteps": [
                    "constraint_updated",
                    "ordered_plan_regenerated",
                    "postcondition_verified",
                ],
                "postconditionReport": {"satisfied": True, "actualCount": 12, "targetCount": 45},
            },
        }

    result = await execute_conversation_action(
        tenant_id="tenant-7", session_id="s1",
        action={"actionType": "confirm_proposal", "proposalRef": "pending-1"},
        snapshot=snapshot_with_pending({"userGoalRequest": {
            "goalType": "only_keep_scope",
            "targetScopes": [{"scopeType": "major", "name": "临床医学"}],
            "negativeScopes": [],
        }}),
        resolver=resolver, executor=executor,
    )

    assert result.action_status == "applied"


@pytest.mark.asyncio
async def test_constraint_apply_reports_failed_when_postcondition_unsatisfied() -> None:
    """对照：满足度报告说没满足 ⇒ `failed` ✓（不许读成成功）。"""
    async def resolver(session_id, **kwargs):
        if kwargs.get("action") in {"complete", "fail"}:
            return {"code": 0, "data": {"status": "applied"}}
        return {"code": 0, "data": {"status": "applying", "revision": 4}}

    async def executor(*args, **kwargs):
        return {
            "code": 0,
            "data": {
                "postconditionReport": {"satisfied": False, "actualCount": 26, "targetCount": 45},
            },
        }

    result = await execute_conversation_action(
        tenant_id="tenant-7", session_id="s1",
        action={"actionType": "confirm_proposal", "proposalRef": "pending-1"},
        snapshot=snapshot_with_pending({"userGoalRequest": {
            "goalType": "only_keep_scope",
            "targetScopes": [{"scopeType": "major", "name": "临床医学"}],
            "negativeScopes": [],
        }}),
        resolver=resolver, executor=executor,
    )

    assert result.action_status == "failed"


@pytest.mark.asyncio
async def test_constraint_apply_without_any_signal_stays_failed() -> None:
    """兜底不变：既没有 `status` 也没有满足度报告时，**仍是 `failed`** ✓（严格默认 ✓）。"""
    async def resolver(session_id, **kwargs):
        if kwargs.get("action") in {"complete", "fail"}:
            return {"code": 0, "data": {"status": "applied"}}
        return {"code": 0, "data": {"status": "applying", "revision": 4}}

    async def executor(*args, **kwargs):
        return {"code": 0, "data": {"completedSteps": ["constraint_updated"]}}

    result = await execute_conversation_action(
        tenant_id="tenant-7", session_id="s1",
        action={"actionType": "confirm_proposal", "proposalRef": "pending-1"},
        snapshot=snapshot_with_pending({"userGoalRequest": {
            "goalType": "only_keep_scope",
            "targetScopes": [{"scopeType": "major", "name": "临床医学"}],
            "negativeScopes": [],
        }}),
        resolver=resolver, executor=executor,
    )

    assert result.action_status == "failed"


@pytest.mark.asyncio
async def test_scope_type_with_scope_suffix_maps_to_the_same_bundle() -> None:
    """真载荷的 `scopeType` 带 `_scope` 后缀 ✗——照原值查表会**整条被拒** ✓。

    真栈实测（2026-09-25，会话 9781936）：模型/Java 给的是
    `{"scopeType": "major_scope", "entityType": "major", "name": "临床医学"}` ✗，
    而映射表的键是 `major` ✓（单测里手写的也是 `major` ✓）。后果是确认被
    `unmappable_goal_scope` 拒掉：fail-closed ✓、方案没被改动 ✓，但功能等于不可用 ✗。
    """
    _, calls = await _claim_then_execute(None, {
        "goalType": "only_keep_scope",
        "targetScopes": [{
            "rawText": "严格只保留临床医学",
            "resolutionStatus": "pending_clarification",
            "scopeType": "major_scope",
            "entityType": "major",
            "name": "临床医学",
        }],
        "negativeScopes": [],
    })

    assert calls[0]["constraint_update"] == {
        "intentMode": "constraint",
        "majorPreferences": {"positive": ["临床医学"], "negative": []},
    }


@pytest.mark.asyncio
async def test_scope_type_falls_back_to_entity_type() -> None:
    """没有 `scopeType` 时回退 `entityType` ✓（真载荷两个字段都在，但别只认一个 ✓）。"""
    _, calls = await _claim_then_execute(None, {
        "goalType": "must_include_scope",
        "targetScopes": [{"entityType": "school", "name": "浙江大学"}],
        "negativeScopes": [],
    })

    assert calls[0]["constraint_update"]["schoolPreferences"] == {
        "positive": ["浙江大学"], "negative": []}


@pytest.mark.asyncio
async def test_scope_suffix_normalizes_without_entity_type() -> None:
    """只有 `scopeType: "major_scope"`（没有 `entityType`）时也认得出来 ✓。

    真载荷两字段都在 ✓，所以上一条用例**不足以**区分"后缀归一化"与"entityType 回退" ✗——
    这条把两者分开：没有 `entityType` 时只剩后缀归一化这一条路 ✓。
    """
    _, calls = await _claim_then_execute(None, {
        "goalType": "only_keep_scope",
        "targetScopes": [{"scopeType": "province_scope", "name": "北京"}],
        "negativeScopes": [],
    })

    assert calls[0]["constraint_update"]["regionPreferences"] == {
        "positive": ["北京"], "negative": []}


async def _stub_catalog(mapping: dict[str, str], monkeypatch=None) -> None:
    """把目录查询打桩成"只有这张表里的名字解析得出 ID" ✓（按省/市两个入口分别兜 ✓）。"""
    from app.util import internal_client as _client

    async def fake_lookup(name: str):
        code = mapping.get(str(name))
        if not code:
            return {"resultType": "empty", "data": None}
        key = "cityCode" if len(code) > 6 else "provinceCode"
        return {"resultType": "exact", "data": {key: code, "cityName" if key == "cityCode" else "provinceName": name}}

    _client.catalog_lookup_city = fake_lookup
    _client.catalog_lookup_province = fake_lookup


@pytest.mark.asyncio
async def test_region_scope_sends_authoritative_id_alongside_name() -> None:
    """区域范围**同时**下发权威 ID ✓（区域先行：省/市 ID 最稳 ✓），名字留着兜底 ✓。

    "北京"按目录是**省级**（`provinceCode=110000` ✓）——直辖市这一支本来就该按省级落 ✓，
    与候选池里的 `provinceId`（同为 `110000` ✓）正好对上 ✓。
    """
    await _stub_catalog({"北京": "110000"})
    _, calls = await _claim_then_execute(None, {
        "goalType": "only_keep_scope",
        "targetScopes": [{"scopeType": "city_scope", "name": "北京"}],
        "negativeScopes": [],
    })

    assert calls[0]["constraint_update"]["regionPreferences"] == {
        "positive": ["北京"], "negative": []}
    assert calls[0]["constraint_update"]["regionPreferenceIds"] == {
        "positive": ["110000"], "negative": []}


@pytest.mark.asyncio
async def test_region_scope_without_resolved_id_still_sends_name() -> None:
    """解析不出 ID **不阻断** ✓：照旧只发名字 ✓（匹配按名字兜底 ✓），也不发空的 ID 束 ✓。"""
    await _stub_catalog({})
    _, calls = await _claim_then_execute(None, {
        "goalType": "only_keep_scope",
        "targetScopes": [{"scopeType": "city_scope", "name": "银河系"}],
        "negativeScopes": [],
    })

    assert calls[0]["constraint_update"]["regionPreferences"] == {
        "positive": ["银河系"], "negative": []}
    assert "regionPreferenceIds" not in calls[0]["constraint_update"]


async def _stub_major_catalog(mapping: dict[str, str], *, result_type: str = "exact",
                              capture: list | None = None) -> None:
    """专业目录打桩 ✓：只有表里有的名字才解析得出 `majorId` ✓。

    `result_type` 可切 `multi` ✓——真栈上"临床医学"不带层次就是 `multi` ✗（本科/专科各一条 ✓），
    那时**必须不取 ID** ✗，否则会把另一条层次的 ID 下发出去 ✗。
    """
    from app.util import internal_client as _client

    async def fake_lookup(name: str, education_level: str | None = None):
        if capture is not None:
            capture.append((str(name), education_level))
        major_id = mapping.get(str(name))
        if not major_id:
            return {"resultType": "empty", "data": None}
        if result_type != "exact":
            return {"resultType": result_type, "data": [{"majorId": major_id, "majorName": name}]}
        return {"resultType": "exact", "data": {"majorId": major_id, "majorName": name}}

    _client.catalog_lookup_major = fake_lookup


@pytest.mark.asyncio
async def test_major_scope_sends_authoritative_id_alongside_name() -> None:
    """专业范围**同时**下发权威 `majorId` ✓（"专业按 ID"，区域先行 ✓），名字留着兜底 ✓。

    真栈词汇表核对（2026-09-26）：池里的真 `majorId` 与目录 `/catalog/lookup/major`
    **同一套** ✓（临床医学 `774` ✓），所以两边能直接比 ✓。
    """
    await _stub_major_catalog({"临床医学": "774"})
    _, calls = await _claim_then_execute(None, {
        "goalType": "only_keep_scope",
        "targetScopes": [{"scopeType": "major_scope", "entityType": "major", "name": "临床医学"}],
        "negativeScopes": [],
    })

    assert calls[0]["constraint_update"]["majorPreferences"] == {
        "positive": ["临床医学"], "negative": []}
    assert calls[0]["constraint_update"]["majorPreferenceIds"] == {
        "positive": ["774"], "negative": []}


@pytest.mark.asyncio
async def test_major_scope_skips_id_when_catalog_result_is_ambiguous() -> None:
    """目录返回 `multi` ✗（本科/专科同名各一条 ✓）→ **不取 ID** ✓，只发名字 ✓。

    这条是"下发 ID"的**安全阀** ✓：给了错层次的 ID，会让合规志愿整批被判掉 ✗，
    比"没有 ID、按名字兜底"糟得多 ✓（区域那条同规矩：只认 `exact` ✓）。
    """
    await _stub_major_catalog({"临床医学": "774"}, result_type="multi")
    _, calls = await _claim_then_execute(None, {
        "goalType": "only_keep_scope",
        "targetScopes": [{"scopeType": "major", "name": "临床医学"}],
        "negativeScopes": [],
    })

    assert calls[0]["constraint_update"]["majorPreferences"] == {
        "positive": ["临床医学"], "negative": []}
    assert "majorPreferenceIds" not in calls[0]["constraint_update"]


@pytest.mark.asyncio
async def test_major_scope_passes_session_education_level_to_catalog() -> None:
    """学历层次从**会话批次**取 ✓（"本科批(批次线436分)" → "本科" ✓），只用于目录去歧义 ✓。

    真栈实测：带"本科"后，"临床医学"的查询结果就是 `exact` ✓（不带是 `multi` ✗）。
    拿不到层次就不给 ✓——那是"这次拿不到权威身份"，不是错误 ✓。
    """
    capture: list = []
    await _stub_major_catalog({"临床医学": "774"}, capture=capture)
    _, calls = await _claim_then_execute(None, {
        "goalType": "only_keep_scope",
        "targetScopes": [{"scopeType": "major", "name": "临床医学"}],
        "negativeScopes": [],
    }, snapshot_extra={"scoreContext": {"batch": "本科批(批次线436分)"}})

    assert capture == [("临床医学", "本科")]
    assert calls[0]["constraint_update"]["majorPreferenceIds"] == {
        "positive": ["774"], "negative": []}


@pytest.mark.asyncio
async def test_exclude_scope_sends_major_id_on_the_negative_side() -> None:
    """排除侧同理 ✓：ID 与名字**同正负** ✓（排除错一个专业，用户是看不见的 ✗）。"""
    await _stub_major_catalog({"临床医学": "774"})
    _, calls = await _claim_then_execute(None, {
        "goalType": "exclude_scope",
        "targetScopes": [],
        "negativeScopes": [{"scopeType": "major", "name": "临床医学"}],
    })

    assert calls[0]["constraint_update"]["majorPreferenceIds"] == {
        "positive": [], "negative": ["774"]}


@pytest.mark.asyncio
async def test_exclude_scope_with_same_name_candidates_is_refused() -> None:
    """排除类遇到**同名多候选**就**拒绝执行** ✓（fail-closed ✓），且理由**指名** ✓。

    <p>真栈形态（2026-09-26 ✓）：目录里"临床医学"本科（`774` ✓）/专科（`520101K` ✓）各一条 ✓。
    包含类解析不到精确项时按名字兜底是**安全的** ✓（用户能在方案里看见选了什么 ✓）；
    排除类按名字排会排掉用户**看不见**的东西 ✗——报告点名"最糟的失败形态" ✓。
    网关不能对用户说话 ✓（能说话的是模型 ✓），所以这一支给的是**可转述的失败** ✓。
    """
    from app.util import internal_client as _client

    async def fake_lookup(name: str, education_level: str | None = None):
        return {
            "resultType": "multi",
            "data": [
                {"majorId": "774", "majorName": "临床医学", "educationLevel": "本科"},
                {"majorId": "520101K", "majorName": "临床医学", "educationLevel": "专科"},
            ],
        }

    _client.catalog_lookup_major = fake_lookup
    result, calls = await _claim_then_execute(None, {
        "goalType": "exclude_scope",
        "targetScopes": [],
        "negativeScopes": [{"scopeType": "major", "name": "临床医学"}],
    })

    assert result.action_status == "failed"
    assert result.code == "exclude_scope_ambiguous"
    assert calls == [], "拒绝执行＝一步都不许走（执行器一次都不该被调）"
    assert "临床医学" in (result.message or "") and "本科" in (result.message or ""), \
        "理由要能直接转述给用户（带上候选清单）"


@pytest.mark.asyncio
async def test_include_scope_with_same_name_candidates_still_proceeds_by_name() -> None:
    """对照 ✓：**包含类**遇到同名多候选**照常执行** ✓（按名字兜底 ✓）——别把安全的那半也拦了 ✗。"""
    await _stub_major_catalog({"临床医学": "774"}, result_type="multi")
    _, calls = await _claim_then_execute(None, {
        "goalType": "only_keep_scope",
        "targetScopes": [{"scopeType": "major", "name": "临床医学"}],
        "negativeScopes": [],
    })

    assert calls[0]["constraint_update"]["majorPreferences"] == {
        "positive": ["临床医学"], "negative": []}


# ── 补录成绩（score_update 动作族）：确认 → update_score_detail ─────────────────────
#
# 这一族的执行输入是 **Java prepare 落进 pending 的 `scoreUpdateRequest` 草稿** ✓：
# 网关只**透传** ✓（合并 → 校验（110）→ 落 userScoreDetail → 规划状态 +1 置 stale 全在
# Java 执行体里，与表单补录同一条核心 ✓）。本节钉三条纪律：
#   ① 路由：生产者的三个标记（kind / actionFamily / proposalSource）任一命中都走
#      `update_score_detail` ✓，**不**走提案那条（apply_plan_change_proposal ✗）；
#   ② fail-closed："是补录但草稿丢了"必须**拒绝执行** ✗——自造草稿等于在用户看不见的
#      地方写成绩 ✓；同理 operationId 丢了不许自铸幂等键 ✓；
#   ③ 结果版本：补录的响应**没有 `stateVersion`** ✗，结论在 `resultPlanVersion` /
#      `planningState.version` 上 ✓（不回退的话 applied 会带着 None 回来 ✓）。


def score_update_snapshot() -> dict:
    """带 score_update pending 的快照（Java `fillActiveProposal` 的扁平暴露形状 ✓）。"""
    current = snapshot()
    current["activeProposal"].update({
        "kind": "score_update",
        "actionFamily": "update_score_detail",
    })
    current["activeProposal"]["data"] = {
        "operationId": "op-score-1",
        "proposalSource": "score_update",
        "sourceVersion": 7,
        "scoreUpdateRequest": {
            "sourceVersionGuard": 7,
            "province": {"code": "330000", "name": "浙江省"},
            "totalScore": 641,
            "totalScorePos": 3100,
            "subjectScoreList": [{"subject": "语文", "score": 118}],
        },
    }
    return current


async def _confirm_score_update(snapshot_payload: dict, *, execute_response: dict):
    """跑一遍 score_update 的 confirm→claim→execute，返回 (结果, execute 收到的 kwargs)。"""
    execute_calls = []
    claim_tokens = []

    async def resolver(session_id=None, *args, **kwargs):
        if kwargs.get("action") in {"complete", "fail"}:
            return {"code": 0, "data": {"status": "applied"}}
        claim_tokens.append(kwargs.get("claim_token"))
        return {"code": 0, "data": {"status": "applying", "revision": 4}}

    async def executor(*args, **kwargs):
        execute_calls.append(kwargs)
        return execute_response

    result = await execute_conversation_action(
        tenant_id="tenant-7", session_id="s1",
        action={"actionType": "confirm_proposal", "proposalRef": "pending-1", "expectedSourceVersion": 7},
        snapshot=snapshot_payload, resolver=resolver, executor=executor,
    )
    return result, execute_calls, claim_tokens


@pytest.mark.asyncio
async def test_score_update_confirm_routes_to_the_update_score_detail_command():
    """补录确认走 `update_score_detail`，草稿**原样**进 execute，claim token 复用 ✓。"""
    result, calls, claim_tokens = await _confirm_score_update(
        score_update_snapshot(),
        execute_response={
            "code": 0,
            "data": {
                "status": "applied",
                "resultPlanVersion": 8,
                "planningState": {"version": 8},
            },
        },
    )

    assert result.action_status == "applied"
    # 补录响应没有 `stateVersion`：版本结论在 `resultPlanVersion` 上 ✓
    assert result.new_state_version == 8
    call = calls[0]
    assert call["command_type"] == "update_score_detail"
    assert call["score_update"]["totalScore"] == 641, "草稿原样透传（网关不合并、不改写）"
    assert call["score_update"]["subjectScoreList"] == [{"subject": "语文", "score": 118}]
    # 计划版本取 prepare 时的 planning version（Java 先拿它与 planning state.version 比对）
    assert call["expected_plan_version"] == 7
    assert call["claim_token"] == claim_tokens[0], "claim token 必须复用"
    assert "proposal_apply" not in call, "补录不吃提案载荷"
    assert "constraint_update" not in call


@pytest.mark.asyncio
@pytest.mark.parametrize("marker", ["kind", "actionFamily", "proposalSource"])
async def test_score_update_detection_accepts_each_producer_marker(marker: str) -> None:
    """三个生产者标记**任一**命中即识别 ✓（Java `fillActiveProposal` 三个都扁平暴露 ✓）。"""
    current = score_update_snapshot()
    if marker == "kind":
        current["activeProposal"].pop("actionFamily")
        current["activeProposal"]["data"].pop("proposalSource")
    elif marker == "actionFamily":
        current["activeProposal"].pop("kind")
        current["activeProposal"]["data"].pop("proposalSource")
    else:
        current["activeProposal"].pop("kind")
        current["activeProposal"].pop("actionFamily")

    _, calls, _ = await _confirm_score_update(
        current, execute_response={"code": 0, "data": {"status": "applied", "resultPlanVersion": 8}}
    )
    assert calls[0]["command_type"] == "update_score_detail"


@pytest.mark.asyncio
async def test_score_update_version_falls_back_to_planning_state_version():
    """`resultPlanVersion` 缺失时退到 `planningState.version` ✓（别把 applied 带着 None 交出去）。"""
    result, _, _ = await _confirm_score_update(
        score_update_snapshot(),
        execute_response={"code": 0, "data": {"status": "applied", "planningState": {"version": 9}}},
    )
    assert result.action_status == "applied"
    assert result.new_state_version == 9


@pytest.mark.asyncio
@pytest.mark.parametrize(("removed_key", "expected_code"), [
    ("operationId", "operation_id_missing"),
    ("scoreUpdateRequest", "score_update_payload_missing"),
])
async def test_score_update_refuses_to_execute_when_the_pending_is_incomplete(
    removed_key: str, expected_code: str
):
    """pending 不完整就**拒绝执行、一步都不走** ✓✗：
    - operationId 丢了：自铸一个 → Java 的幂等键认不出同一操作（"重复确认不双写"的依据没了 ✗）；
    - 草稿丢了：网关自造成绩 → 在用户看不见的地方写库 ✗（"是补录但缺件" ≠ "不是补录"）。
    """
    current = score_update_snapshot()
    current["activeProposal"]["data"].pop(removed_key)

    async def resolver(session_id=None, *args, **kwargs):
        return {"code": 0, "data": {"status": "applying", "revision": 4}}

    async def executor(*args, **kwargs):
        raise AssertionError("pending 不完整时执行器一次都不该被调")

    result = await execute_conversation_action(
        tenant_id="tenant-7", session_id="s1",
        action={"actionType": "confirm_proposal", "proposalRef": "pending-1"},
        snapshot=current, resolver=resolver, executor=executor,
    )
    assert result.action_status == "failed"
    assert result.code == expected_code
    assert "拒绝执行" in (result.message or ""), "失败理由要能转述给用户"


@pytest.mark.asyncio
async def test_score_update_failure_carries_the_business_code_and_message():
    """失败可视化的一半：Java 的业务码（84009 / 110 / 40904 …）与消息要**带出**卡面 ✓✗
    （只有"未生效"三个字的话，用户只能反复点同一个确认 ✗）。"""
    result, _, _ = await _confirm_score_update(
        score_update_snapshot(),
        execute_response={"code": 84009, "msg": "上游策略校验未通过"},
    )
    assert result.action_status == "failed"
    assert result.code == "84009"
    assert result.message == "上游策略校验未通过"


@pytest.mark.asyncio
async def test_a_plain_proposal_pending_still_routes_to_the_plan_change_command():
    """对照 ✓：普通提案待确认里**没有** score_update 标记时照旧走提案路 ✓
    （补录分支是 else 的另一半，别把整族都吞了 ✗）。"""
    _, calls = await _claim_then_execute(None, {"goalType": "fill_to_count", "targetCount": 80})
    assert calls[0]["command_type"] == "apply_plan_change_proposal"
