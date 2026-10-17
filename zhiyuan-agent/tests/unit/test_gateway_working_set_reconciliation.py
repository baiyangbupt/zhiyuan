from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.gateway.service import GatewayService
from app.harness.binding import ThreadBinding


class FakeMessageStore:
    async def save_user_message(self, chat_session_id: str, content: str) -> int:
        return 1

    async def save_agent_message(
        self, chat_session_id: str, content: str, ws_type: str = "reply"
    ) -> int:
        return 2


class RecordingCodex:
    def __init__(self) -> None:
        self.turns: list[list[dict[str, Any]]] = []
        self.payload: dict[str, Any] = {}

    async def create_thread(self, **kwargs: Any) -> dict[str, Any]:
        return {"thread": {"id": "thread-working-set"}}

    async def start_turn_and_collect(
        self,
        thread_id: str,
        input_items: list[dict[str, Any]],
        output_schema: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> SimpleNamespace:
        self.turns.append(input_items)
        return SimpleNamespace(
            status="completed",
            output={"responseType": "text", "message": "好的。"},
            events=[],
            turn_id=f"native-{len(self.turns)}",
            payload=self.payload,
        )


def _workspace() -> dict[str, Any]:
    return {
        "sessionId": "42",
        "version": 7,
        "phase": "candidate_exploration",
        "admissionMode": "major",
        "studentSummary": {"provinceName": "浙江", "score": 650, "rank": 1000},
        "allowedCapabilities": ["catalog_read", "admission_read"],
    }


def _fact(
    rate: int,
    risk_tier: str,
    data_version: str,
    *,
    unit_id: str = "unit-1",
) -> dict[str, Any]:
    return {
        "admissionUnitId": unit_id,
        "admissionMode": "major",
        "schoolId": "school-1",
        "majorId": "major-1",
        "unitAdmissionRate": rate,
        "riskTier": risk_tier,
        "dataVersion": data_version,
    }


def _gateway(workspace: dict[str, Any], codex: RecordingCodex) -> GatewayService:
    return GatewayService(
        mode="codex_readonly",
        codex=codex,
        legacy=None,
        message_store=FakeMessageStore(),
        snapshot_loader=lambda **kwargs: workspace,
        binding_loader=lambda **kwargs: ThreadBinding(
            thread_id=kwargs["thread_id"],
            tenant_id="1",
            session_id="42",
            user_id="7",
            allowed_capabilities=frozenset({"catalog_read", "admission_read"}),
        ),
    )


async def _turn(gateway: GatewayService, turn_id: str) -> dict[str, Any]:
    result = await gateway.handle_turn(
        tenant_id="1",
        session_id="42",
        user_id="7",
        turn_id=turn_id,
        content="继续查看",
    )
    assert result.get("error") is None, result
    return result


def _model_payload(
    codex: RecordingCodex, *, turn_index: int = 1, item_index: int = 1
) -> dict[str, Any]:
    text = codex.turns[turn_index][item_index]["text"]
    payload, _remaining = json.JSONDecoder().raw_decode(text[text.index("{") :])
    return payload


@pytest.mark.asyncio
@pytest.mark.parametrize("snapshot_version", [7, 8, 11])
@pytest.mark.parametrize("has_previous_facts", [False, True])
async def test_nonempty_snapshot_facts_replace_previous_facts_in_model_context(
    snapshot_version: int, has_previous_facts: bool
) -> None:
    workspace = _workspace()
    workspace["admissionFacts"] = (
        [
            _fact(30, "冲", "old-data"),
            _fact(45, "冲", "old-data", unit_id="unit-old-only"),
        ]
        if has_previous_facts
        else []
    )
    codex = RecordingCodex()
    gateway = _gateway(workspace, codex)
    await _turn(gateway, "first")

    workspace["version"] = snapshot_version
    workspace["admissionFacts"] = [_fact(80, "保", "fresh-data")]
    result = await _turn(gateway, "second")

    context = _model_payload(codex)
    assert len(context["admissionFacts"]) == 1
    assert context["admissionFacts"][0]["admissionUnitId"] == "unit-1"
    assert context["admissionFacts"][0]["unitAdmissionRate"] == 80
    assert context["admissionFacts"][0]["riskTier"] == "保"
    assert context["admissionFacts"][0]["dataVersion"] == "fresh-data"
    assert context["snapshot"]["admissionFacts"] == context["admissionFacts"]
    assert result["workingSet"]["admissionFacts"] == context["admissionFacts"]


@pytest.mark.asyncio
@pytest.mark.parametrize("snapshot_version", [7, 8, 11])
async def test_null_snapshot_proposal_does_not_revive_previous_proposal(
    snapshot_version: int,
) -> None:
    workspace = _workspace()
    workspace["activeProposal"] = {
        "proposalRef": "pending-old", "status": "active", "sourceVersion": 7,
    }
    codex = RecordingCodex()
    gateway = _gateway(workspace, codex)
    first = await _turn(gateway, "first")
    assert first["workingSet"]["activeProposal"]["proposalRef"] == "pending-old"

    workspace["version"] = snapshot_version
    workspace["activeProposal"] = None
    result = await _turn(gateway, "second")

    assert _model_payload(codex)["activeProposal"] is None
    assert result["workingSet"]["activeProposal"] is None
    assert _model_payload(codex, item_index=2)["taskFamily"] == "unclassified"


@pytest.mark.asyncio
async def test_removed_proposal_does_not_mask_current_missing_facts() -> None:
    workspace = _workspace()
    workspace["activeProposal"] = {"proposalRef": "pending-old", "status": "active"}
    codex = RecordingCodex()
    gateway = _gateway(workspace, codex)
    await _turn(gateway, "first")

    workspace["version"] = 8
    workspace["activeProposal"] = None
    workspace["studentSummary"] = {"provinceName": "浙江"}
    await _turn(gateway, "second")

    plan = _model_payload(codex, item_index=2)
    assert plan["taskFamily"] == "clarification"
    assert plan["blockedSteps"] == ["score", "rank"]


@pytest.mark.asyncio
async def test_new_snapshot_proposal_remains_available_for_confirmation() -> None:
    workspace = _workspace()
    workspace["activeProposal"] = {
        "proposalRef": "pending-old", "status": "active", "sourceVersion": 7,
    }
    codex = RecordingCodex()
    gateway = _gateway(workspace, codex)
    await _turn(gateway, "first")

    workspace["version"] = 8
    workspace["activeProposal"] = {
        "proposalRef": "pending-new", "status": "active", "sourceVersion": 8,
    }
    result = await _turn(gateway, "second")

    proposal = _model_payload(codex)["activeProposal"]
    assert proposal["proposalRef"] == "pending-new"
    assert proposal["sourceVersion"] == 8
    assert proposal["requiresConfirmation"] is True
    assert result["workingSet"]["activeProposal"] == proposal
    assert _model_payload(codex, item_index=2)["taskFamily"] == "confirmation"


@pytest.mark.asyncio
@pytest.mark.parametrize("facts_field_present", [False, True])
async def test_empty_snapshot_facts_preserve_previous_facts_for_compatibility(
    facts_field_present: bool,
) -> None:
    workspace = _workspace()
    workspace["admissionFacts"] = [_fact(30, "冲", "old-data")]
    codex = RecordingCodex()
    gateway = _gateway(workspace, codex)
    await _turn(gateway, "first")

    workspace["version"] = 8
    if facts_field_present:
        workspace["admissionFacts"] = []
    else:
        workspace.pop("admissionFacts")
    result = await _turn(gateway, "second")

    context = _model_payload(codex)
    assert context["snapshot"]["admissionFacts"] == []
    assert len(context["admissionFacts"]) == 1
    assert context["admissionFacts"][0]["unitAdmissionRate"] == 30
    assert context["admissionFacts"][0]["dataVersion"] == "old-data"
    assert result["workingSet"]["admissionFacts"] == context["admissionFacts"]


@pytest.mark.asyncio
async def test_fact_refresh_preserves_candidates_and_source_turn_in_model_context() -> None:
    workspace = _workspace()
    codex = RecordingCodex()
    codex.payload = {
        "resolvedEntities": [{"entityId": "school-1", "name": "甲大学"}],
    }
    gateway = _gateway(workspace, codex)
    first = await _turn(gateway, "first")
    assert first["workingSet"]["candidateSet"]["sourceTurnId"] == "first"

    workspace["version"] = 8
    workspace["admissionFacts"] = [_fact(80, "保", "fresh-data")]
    codex.payload = {}
    result = await _turn(gateway, "second")

    context = _model_payload(codex)
    assert len(context["candidateEntities"]) == 1
    assert context["candidateEntities"][0]["entityId"] == "school-1"
    assert context["candidateEntities"][0]["name"] == "甲大学"
    assert context["candidateSet"]["sourceTurnId"] == "first"
    assert context["candidateSet"]["scopeVersion"] == 8
    assert context["lastTurnId"] == "first"
    assert context["lastResponseType"] == "text"
    assert result["workingSet"]["candidateEntities"] == context["candidateEntities"]
    assert result["workingSet"]["lastTurnId"] == "second"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "snapshot_update",
    [{"phase": "plan_review"}, {"admissionMode": "major_group"}],
    ids=["stage-change", "mode-change"],
)
async def test_snapshot_scope_change_still_invalidates_previous_candidates(
    snapshot_update: dict[str, str],
) -> None:
    workspace = _workspace()
    codex = RecordingCodex()
    codex.payload = {
        "resolvedEntities": [{"entityId": "school-1", "name": "甲大学"}],
    }
    gateway = _gateway(workspace, codex)
    first = await _turn(gateway, "first")
    assert first["workingSet"]["candidateEntities"][0]["entityId"] == "school-1"

    workspace["version"] = 8
    workspace.update(snapshot_update)
    codex.payload = {}
    result = await _turn(gateway, "second")

    context = _model_payload(codex)
    assert context["candidateEntities"] == []
    assert context["candidateSet"]["sourceTurnId"] is None
    assert context["candidateSet"]["scopeVersion"] == 8
    assert result["workingSet"]["candidateEntities"] == []
