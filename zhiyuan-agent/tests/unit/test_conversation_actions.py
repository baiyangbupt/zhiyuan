import pytest
from unittest.mock import AsyncMock, patch

from app.gateway.conversation_actions import execute_conversation_action
from app.gateway.service import GatewayService
from app.gateway.ui_events import SessionKey


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


async def _claim_then_execute(monkeypatch, goal: dict | None):
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
