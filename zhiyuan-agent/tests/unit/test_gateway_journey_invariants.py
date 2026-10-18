from __future__ import annotations

import pytest

from app.gateway.contracts import ConversationTurnSnapshot, TurnOutput
from app.gateway.output_validation import OutputContractError, validate_turn_output
from app.gateway.service import GatewayService, _session_key
from app.gateway.snapshot import build_snapshot
from app.util import internal_client


def snapshot(*, journey=None, active_proposal=None) -> ConversationTurnSnapshot:
    return ConversationTurnSnapshot(
        snapshotVersion=87,
        sessionId="s1",
        journey=journey,
        activeProposal=active_proposal,
    )


def validate(output: TurnOutput, *, current_snapshot: ConversationTurnSnapshot):
    return validate_turn_output(
        turn_output=output,
        current_snapshot=current_snapshot,
        evidence_ledger={},
        artifacts={},
    )


def test_applying_rejects_write_draft_with_fixed_code() -> None:
    output = TurnOutput(
        responseType="text",
        message="我再改一下",
        scoreUpdateRequest={"sourceVersionGuard": 87},
    )

    with pytest.raises(OutputContractError) as error:
        validate(output, current_snapshot=snapshot(journey={"pendingStatus": "applying"}))

    assert error.value.code == "pending_applying"


def test_applying_check_runs_before_confirm_reference_check() -> None:
    output = TurnOutput(
        responseType="text",
        message="确认",
        conversationAction={"actionType": "confirm_proposal", "proposalRef": "p-old"},
    )

    with pytest.raises(OutputContractError) as error:
        validate(output, current_snapshot=snapshot(journey={"pendingStatus": "applying"}))

    # 没有 activeProposal 时旧检查会报 proposal_reference_mismatch；必须先报“正在生效”。
    assert error.value.code == "pending_applying"


def test_applying_allows_readonly_text() -> None:
    output = TurnOutput(responseType="text", message="我先看看当前方案")

    result = validate(
        output, current_snapshot=snapshot(journey={"pendingStatus": "applying"})
    )

    assert result.response_type == "text"


def test_without_journey_confirm_still_uses_reference_check() -> None:
    output = TurnOutput(
        responseType="text",
        message="确认",
        conversationAction={"actionType": "confirm_proposal", "proposalRef": "p-old"},
    )

    with pytest.raises(OutputContractError) as error:
        validate(output, current_snapshot=snapshot(journey=None))

    assert error.value.code == "proposal_reference_mismatch"


def test_non_applying_journey_does_not_block_write_draft() -> None:
    output = TurnOutput(
        responseType="text",
        message="补录成绩",
        scoreUpdateRequest={"sourceVersionGuard": 87},
    )

    result = validate(
        output, current_snapshot=snapshot(journey={"pendingStatus": "active"})
    )

    assert result.score_update_request is not None


def _gateway(loader) -> GatewayService:
    return GatewayService(
        mode="codex_readonly",
        codex=object(),
        legacy=None,
        message_store=object(),
        binding_loader=lambda **kwargs: None,
        snapshot_loader=loader,
    )


def _applying_snapshot() -> ConversationTurnSnapshot:
    return build_snapshot(
        {
            "sessionId": "42",
            "version": 87,
            "journey": {"pendingStatus": "applying", "hasPlan": True},
        }
    )


async def test_applying_reconcile_applied_refreshes_snapshot(monkeypatch) -> None:
    calls: list[dict] = []

    async def fake_reconcile(*args, **kwargs):
        calls.append(kwargs)
        return {"outcome": "applied", "pendingStatus": "applied"}

    loaded: list[int] = []

    def loader(**kwargs):
        loaded.append(1)
        return {
            "sessionId": "42",
            "version": 88,
            "journey": {"pendingStatus": None, "hasPlan": True},
        }

    monkeypatch.setattr(internal_client, "reconcile_pending_confirmation", fake_reconcile)
    gateway = _gateway(loader)
    key = _session_key("1", "42")
    snapshot = _applying_snapshot()
    gateway._store_snapshot(key, snapshot, authoritative=True)

    result = await gateway._reconcile_applying_snapshot(key, "1", "42", snapshot)

    assert calls
    assert loaded
    assert result.snapshot_version == 88
    assert result.journey is not None and result.journey["pendingStatus"] is None


async def test_applying_reconcile_still_applying_keeps_snapshot(monkeypatch) -> None:
    async def fake_reconcile(*args, **kwargs):
        return {"outcome": "still_applying"}

    def loader(**kwargs):
        raise AssertionError("still_applying 不应刷新快照")

    monkeypatch.setattr(internal_client, "reconcile_pending_confirmation", fake_reconcile)
    gateway = _gateway(loader)
    key = _session_key("1", "42")
    snapshot = _applying_snapshot()

    result = await gateway._reconcile_applying_snapshot(key, "1", "42", snapshot)

    assert result is snapshot


async def test_applying_reconcile_failure_is_fail_safe(monkeypatch) -> None:
    async def fake_reconcile(*args, **kwargs):
        raise RuntimeError("java unavailable")

    def loader(**kwargs):
        raise AssertionError("对账失败不应刷新快照")

    monkeypatch.setattr(internal_client, "reconcile_pending_confirmation", fake_reconcile)
    gateway = _gateway(loader)
    key = _session_key("1", "42")
    snapshot = _applying_snapshot()

    result = await gateway._reconcile_applying_snapshot(key, "1", "42", snapshot)

    assert result is snapshot
