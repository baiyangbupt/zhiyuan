from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.util import internal_client


@pytest.mark.asyncio
async def test_get_pending_prefers_dedicated_resource(monkeypatch):
    get_mock = AsyncMock(
        return_value={
            "code": 0,
            "data": {
                "pendingId": "p-1",
                "revision": 3,
                "status": "active",
                "dataValue": {"pendingId": "p-1", "status": "active"},
            },
        }
    )
    legacy_mock = AsyncMock()
    monkeypatch.setattr(internal_client.http_client, "get", get_mock)
    monkeypatch.setattr(internal_client, "get_last_extra_data", legacy_mock)

    response = await internal_client.get_last_pending_confirmation("101")

    assert response["data"]["revision"] == 3
    legacy_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_pending_uses_provided_tenant_in_endpoint(monkeypatch):
    get_mock = AsyncMock(return_value={"code": 0, "data": None})
    monkeypatch.setattr(internal_client.http_client, "get", get_mock)

    await internal_client.get_last_pending_confirmation("101", tenant_id="tenant-7")

    assert get_mock.await_args.kwargs["endpoint"] == (
        "/gaotu-assistant-bot/inner/chat/tenant-7/session/pending"
    )


@pytest.mark.asyncio
async def test_get_pending_does_not_read_legacy_when_resource_is_absent(monkeypatch):
    resource_response = {"code": 0, "data": None}
    monkeypatch.setattr(
        internal_client.http_client,
        "get",
        AsyncMock(return_value=resource_response),
    )
    legacy_mock = AsyncMock()
    monkeypatch.setattr(internal_client, "get_last_extra_data", legacy_mock)

    response = await internal_client.get_last_pending_confirmation("101")

    assert response == resource_response
    legacy_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_active_save_reads_current_revision_and_uses_pending_upsert(monkeypatch):
    get_mock = AsyncMock(
        return_value={
            "code": 0,
            "data": {"pendingId": "old-p", "revision": 7, "status": "cancelled", "dataValue": {}},
        }
    )
    post_mock = AsyncMock(return_value={"code": 0, "data": {"revision": 8}})
    monkeypatch.setattr(internal_client.http_client, "get", get_mock)
    monkeypatch.setattr(internal_client.http_client, "post", post_mock)
    state = {
        "pendingId": "new-p",
        "kind": "plan_mutation",
        "actionFamily": "remove_units",
        "status": "active",
    }

    await internal_client.save_pending_confirmation("101", state)

    payload = post_mock.await_args.kwargs["json_data"]
    assert post_mock.await_args.kwargs["endpoint"].endswith("/session/pending")
    assert payload["expectedRevision"] == 7
    assert "version" not in payload


@pytest.mark.asyncio
async def test_save_pending_uses_provided_tenant_in_endpoint(monkeypatch):
    monkeypatch.setattr(
        internal_client.http_client,
        "get",
        AsyncMock(return_value={"code": 0, "data": None}),
    )
    post_mock = AsyncMock(return_value={"code": 0, "data": {"revision": 1}})
    monkeypatch.setattr(internal_client.http_client, "post", post_mock)

    await internal_client.save_pending_confirmation(
        "101",
        {
            "pendingId": "pending-1",
            "kind": "plan_mutation",
            "actionFamily": "remove_units",
            "status": "active",
        },
        tenant_id="tenant-7",
    )

    assert post_mock.await_args.kwargs["endpoint"] == (
        "/gaotu-assistant-bot/inner/chat/tenant-7/session/pending"
    )


@pytest.mark.asyncio
async def test_resolve_pending_uses_provided_tenant_in_endpoint(monkeypatch):
    post_mock = AsyncMock(return_value={"code": 0, "data": {"status": "applied"}})
    monkeypatch.setattr(internal_client.http_client, "post", post_mock)

    await internal_client.resolve_pending_confirmation(
        "101",
        tenant_id="tenant-7",
        pending_id="pending-1",
        expected_revision=3,
        action="confirm",
    )

    assert post_mock.await_args.kwargs["endpoint"] == (
        "/gaotu-assistant-bot/inner/chat/tenant-7/session/pending/resolve"
    )


@pytest.mark.asyncio
async def test_claim_materializes_legacy_snapshot_before_cas(monkeypatch):
    materialize_mock = AsyncMock(
        return_value={
            "code": 0,
            "data": {
                "pendingId": "legacy-p",
                "revision": 1,
                "status": "active",
                "dataValue": {"pendingId": "legacy-p", "status": "active"},
            },
        }
    )
    resolve_mock = AsyncMock(return_value={"code": 0})
    monkeypatch.setattr(internal_client, "save_pending_confirmation", materialize_mock)
    monkeypatch.setattr(internal_client, "resolve_pending_confirmation", resolve_mock)

    await internal_client.claim_pending_confirmation(
        "101",
        {
            "pendingId": "legacy-p",
            "kind": "intent_change",
            "actionFamily": "apply_selected_intents",
            "status": "active",
        },
    )

    materialize_mock.assert_awaited_once()
    assert resolve_mock.await_args.kwargs["expected_revision"] == 1
    assert resolve_mock.await_args.kwargs["action"] == "confirm"
    assert resolve_mock.await_args.kwargs["claim_token"]


@pytest.mark.asyncio
async def test_terminal_save_returns_current_claim_token(monkeypatch):
    post_mock = AsyncMock(return_value={"code": 0})
    monkeypatch.setattr(internal_client.http_client, "post", post_mock)

    await internal_client.save_pending_confirmation(
        "101",
        {
            "pendingId": "p-1",
            "status": "applied",
            "_pendingRevision": 8,
            "_pendingClaimToken": "claim-owner",
            "resultCode": "applied",
        },
    )

    payload = post_mock.await_args.kwargs["json_data"]
    assert payload["action"] == "complete"
    assert payload["claimToken"] == "claim-owner"


@pytest.mark.asyncio
async def test_pending_planning_command_sends_idempotency_and_version_guards(monkeypatch):
    post_mock = AsyncMock(return_value={"code": 0})
    monkeypatch.setattr(internal_client.http_client, "post", post_mock)

    await internal_client.execute_pending_planning_command(
        1,
        "101",
        operation_id="operation-1",
        pending_id="p-1",
        claim_token="claim-owner",
        expected_plan_version=12,
        command_type="replace_units",
        unit_ids=["u-old"],
        volunteer_ids=["v-new"],
        regenerate_ordered_plan=True,
    )

    assert "pending-command/execute?chatSessionId=101" in post_mock.await_args.kwargs["endpoint"]
    payload = post_mock.await_args.kwargs["json_data"]
    assert payload["operationId"] == "operation-1"
    assert payload["pendingId"] == "p-1"
    assert payload["claimToken"] == "claim-owner"
    assert payload["expectedPlanVersion"] == 12
    assert payload["unitIds"] == ["u-old"]
    assert payload["volunteerIds"] == ["v-new"]


@pytest.mark.asyncio
async def test_score_update_preview_and_prepare_hit_their_own_endpoints(monkeypatch):
    """补录两条端点各就各位 ✓：preview 只读（不带 requestId）、prepare 带 requestId
    （Java 按它做幂等重放 ✓——同一回合重试必须落回同一个 pending ✓）。"""
    post_mock = AsyncMock(return_value={"code": 0})
    monkeypatch.setattr(internal_client.http_client, "post", post_mock)

    await internal_client.preview_score_update(1, "101", {"totalScore": 641})
    preview_call = post_mock.await_args
    assert "session/score-update/preview?chatSessionId=101" in preview_call.kwargs["endpoint"]
    assert preview_call.kwargs["json_data"] == {"totalScore": 641}

    await internal_client.prepare_score_update(
        1, "101", request_id="1:101:turn-9", payload={"totalScore": 641}
    )
    prepare_call = post_mock.await_args
    assert (
        "session/score-update/prepare?chatSessionId=101&requestId=1:101:turn-9"
        in prepare_call.kwargs["endpoint"]
    )


@pytest.mark.asyncio
async def test_pending_planning_command_carries_the_score_update_draft(monkeypatch):
    """`update_score_detail` 的执行输入是 pending 里的草稿 ✓（Java 执行体按它合并/校验/落库）：
    透传键名 `scoreUpdate` 与 Java 的 `PendingPlanningCommandReq` 逐字一致 ✓。"""
    post_mock = AsyncMock(return_value={"code": 0})
    monkeypatch.setattr(internal_client.http_client, "post", post_mock)

    draft = {"totalScore": 641, "subjectScoreList": [{"subject": "chinese", "score": 118}]}
    await internal_client.execute_pending_planning_command(
        1,
        "101",
        operation_id="op-score-1",
        pending_id="p-1",
        claim_token="claim-owner",
        expected_plan_version=12,
        command_type="update_score_detail",
        score_update=draft,
    )

    payload = post_mock.await_args.kwargs["json_data"]
    assert payload["commandType"] == "update_score_detail"
    assert payload["scoreUpdate"] == draft
    assert "proposalApply" not in payload
