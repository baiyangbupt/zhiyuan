import pytest
from unittest.mock import AsyncMock, patch

from app.gateway.conversation_actions import execute_conversation_action
from app.gateway.service import GatewayService


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
    async def resolver(*args, **kwargs):
        return {"code": 0, "data": {"status": "applying", "revision": 4}}

    result = await execute_conversation_action(
        tenant_id="tenant-7",
        session_id="s1",
        action={"actionType": "confirm_proposal", "proposalRef": "pending-1"},
        snapshot=snapshot(),
        resolver=resolver,
    )
    assert result.action_status == "applying"
    assert result.new_state_version is None


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
    assert gateway._snapshots["s1"].snapshot_version == 8
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
