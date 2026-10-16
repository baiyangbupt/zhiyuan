from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.gateway.contracts import ConversationTurnSnapshot, TurnOutput
from app.gateway.artifact_store import SqliteArtifactStore
from app.gateway.output_validation import OutputContractError, validate_turn_output
from app.gateway.service import GatewayService
from app.harness.binding import ThreadBinding


def _reference():
    return {"artifactId": "mcp_art_fabricated", "artifactType": "candidate", "stateVersion": 42}


def _record():
    return {**_reference(), "tenantId": "tenant-1", "sessionId": "session-1"}


def _snapshot():
    return ConversationTurnSnapshot(snapshotVersion=42, sessionId="session-1")


def _output():
    return {"responseType": "recommendation", "message": "候选", "artifactRefs": [_reference()]}


def test_model_text_cannot_register_a_fabricated_artifact():
    gateway = GatewayService(
        mode="codex_readonly", codex=None, legacy=None, message_store=None,
        binding_loader=lambda **kwargs: None, snapshot_loader=lambda **kwargs: None,
    )
    turn = {"events": [{"item": {"type": "agentMessage", "text": json.dumps({"artifacts": [_record()]})}}]}
    _, artifacts = gateway._evidence_inputs(turn, _snapshot(), tenant_id="tenant-1", session_id="session-1")
    assert artifacts == {}


@pytest.mark.parametrize("tenant", ["tenant-other", None, ""])
def test_artifact_validator_rejects_missing_or_foreign_tenant(tenant):
    record = {**_record(), "tenantId": tenant}
    with pytest.raises(OutputContractError, match="artifact_scope_violation"):
        validate_turn_output(
            turn_output=_output(), current_snapshot=_snapshot(), evidence_ledger={},
            artifacts={record["artifactId"]: record}, tenant_id="tenant-1", strict_scope=True,
        )


def test_artifact_type_must_match_the_issued_record():
    record = {**_record(), "artifactType": "comparison"}
    with pytest.raises(OutputContractError, match="artifact_mismatch"):
        validate_turn_output(
            turn_output=_output(), current_snapshot=_snapshot(), evidence_ledger={},
            artifacts={record["artifactId"]: record}, tenant_id="tenant-1", strict_scope=True,
        )


def test_reference_version_must_match_the_record_even_inside_rebase_interval():
    record = {**_record(), "stateVersion": 43}
    with pytest.raises(OutputContractError, match="artifact_mismatch"):
        validate_turn_output(
            turn_output=_output(), current_snapshot=_snapshot(), evidence_ledger={},
            artifacts={record["artifactId"]: record}, tenant_id="tenant-1", strict_scope=True,
            artifact_version_ceiling=43,
        )


class MessageStore:
    def __init__(self):
        self.answers = []

    async def save_user_message(self, chat_session_id, content):
        return 1

    async def save_agent_message(self, chat_session_id, content, ws_type="reply"):
        self.answers.append(content)
        return 2


class Harness:
    def __init__(self, output, events=None):
        self.output = output
        self.events = events or []

    async def create_thread(self, **kwargs):
        return {"thread": {"id": "thread-after-restart"}}

    async def inject_items(self, thread_id, items):
        return {}

    async def start_turn(self, thread_id, input_items, output_schema=None):
        return {"output": self.output, "events": self.events}


def _gateway(store, output, events=None):
    def binding(**kwargs):
        return ThreadBinding(
            tenant_id="tenant-1", session_id="session-1", user_id="user-1",
            thread_id=kwargs["thread_id"], allowed_capabilities=frozenset({"admission_read"}),
            snapshot_version=42,
        )

    return GatewayService(
        mode="codex_readonly", codex=Harness(output, events), legacy=None,
        message_store=MessageStore(), binding_loader=binding,
        snapshot_loader=lambda **kwargs: {"version": 42, "sessionId": "session-1"},
        artifact_store=store,
    )


async def _turn(gateway, turn_id):
    return await gateway.handle_turn(
        tenant_id="tenant-1", session_id="session-1", user_id="user-1",
        turn_id=turn_id, content="继续比较",
    )


def _issue(store, tenant="tenant-1", session="session-1", arguments=None):
    return store.issue(
        tenant_id=tenant, session_id=session, thread_id="thread-before-restart",
        artifact_type="candidate", state_version=42, tool_name="recommendation.preview_candidates",
        arguments=arguments or {}, payload={"items": [{"schoolId": "school-1"}]},
    )


def _citation(record):
    return {
        "responseType": "recommendation", "message": "候选已核验",
        "artifactRefs": [{key: record[key] for key in ("artifactId", "artifactType", "stateVersion")}],
    }


@pytest.mark.asyncio
async def test_tool_free_citations_survive_gateway_and_store_recreation(tmp_path):
    path = str(tmp_path / "shared.sqlite3")
    record = _issue(SqliteArtifactStore(path))
    first = _gateway(SqliteArtifactStore(path), _citation(record))
    assert (await _turn(first, "turn-1")).get("error") is None
    assert (await _turn(first, "turn-2")).get("error") is None
    restarted = _gateway(SqliteArtifactStore(path), _citation(record))
    result = await _turn(restarted, "turn-3")
    assert result.get("error") is None, result
    assert result["output"]["artifactRefs"][0]["artifactId"] == record["artifactId"]
    assert len(restarted.message_store.answers) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("record_scope", [("tenant-other", "session-1"), ("tenant-1", "session-other"), None])
async def test_real_gateway_rejects_unissued_or_foreign_citations_even_with_complete_model_stamps(tmp_path, record_scope):
    store = SqliteArtifactStore(str(tmp_path / "shared.sqlite3"))
    record = _issue(store, *record_scope) if record_scope else _record()
    events = [{"item": {"type": "agentMessage", "text": json.dumps({"artifacts": [{**record, **_record(), "artifactId": record["artifactId"]}]})}}]
    gateway = _gateway(store, _citation(record), events)
    result = await _turn(gateway, "turn-1")
    assert str(result.get("error", "")).startswith("artifact_not_found:"), result
    assert result.get("output") is None
    assert gateway.message_store.answers == []


@pytest.mark.asyncio
async def test_real_gateway_fails_closed_on_store_failure_without_leaking_path(tmp_path):
    import sqlite3

    path = str(tmp_path / "private.sqlite3")
    store = SqliteArtifactStore(path)
    record = _issue(store)
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE codex_artifact_issuance")
    gateway = _gateway(store, _citation(record))
    result = await _turn(gateway, "turn-1")
    assert str(result.get("error", "")).startswith("artifact_store_unavailable:"), result
    assert path not in str(result)
    assert gateway.message_store.answers == []


class RepairHarness(Harness):
    def __init__(self, outputs, before_repair=None):
        self.outputs = list(outputs)
        self.before_repair = before_repair
        self.calls = 0

    async def start_turn_and_collect(self, *args, **kwargs):
        self.calls += 1
        if self.calls == 2 and self.before_repair is not None:
            self.before_repair()
        return SimpleNamespace(
            status="completed", output=self.outputs.pop(0), events=[], payload={},
            turn_id=str(self.calls),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("error_mode", ["proposal", "admission"])
@pytest.mark.parametrize("issued", [True, False])
async def test_non_artifact_repairs_reload_only_genuinely_issued_new_references(tmp_path, error_mode, issued):
    store = SqliteArtifactStore(str(tmp_path / "shared.sqlite3"))
    first = _issue(store)
    replacement = _issue(store, arguments={"sample": 2}) if issued else _record()
    initial = _citation(first)
    if error_mode == "proposal":
        initial["conversationAction"] = {"actionType": "confirm_proposal", "proposalRef": "obsolete"}
    else:
        initial["evidenceRefs"] = [{
            "evidenceId": "mode-conflict", "sourceLevel": "authoritative", "dataVersion": "2026.09.07",
            "admissionMode": "major_group",
        }]
    gateway = _gateway(store, initial)
    gateway.codex = RepairHarness([initial, _citation(replacement)])
    result = await _turn(gateway, "repair-turn")
    if issued:
        assert result.get("error") is None, result
        assert result["output"]["artifactRefs"][0]["artifactId"] == replacement["artifactId"]
        assert result["recovery"]["outputRepaired"] is True
    else:
        assert result.get("output") is None
        assert gateway.message_store.answers == []
    assert gateway.codex.calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["expiry", "unavailable"])
async def test_non_artifact_repair_revalidates_even_unchanged_ids(tmp_path, failure):
    import sqlite3

    clock = [100.0]
    path = str(tmp_path / "shared.sqlite3")
    store = SqliteArtifactStore(path, ttl_seconds=10, clock=lambda: clock[0])
    record = _issue(store)
    initial = {**_citation(record), "conversationAction": {"actionType": "confirm_proposal", "proposalRef": "obsolete"}}

    def fail_store():
        if failure == "expiry":
            clock[0] = 110
        else:
            with sqlite3.connect(path) as connection:
                connection.execute("DROP TABLE codex_artifact_issuance")

    gateway = _gateway(store, initial)
    gateway.codex = RepairHarness([initial, _citation(record)], before_repair=fail_store)
    result = await _turn(gateway, "repair-turn")
    expected = "artifact_store_unavailable:" if failure == "unavailable" else "proposal_reference_mismatch:"
    assert str(result.get("error", "")).startswith(expected), result
    assert result.get("output") is None
    assert gateway.message_store.answers == []


@pytest.mark.asyncio
async def test_priority_repair_can_switch_to_another_issued_reference(tmp_path):
    store = SqliteArtifactStore(str(tmp_path / "shared.sqlite3"))
    first = _issue(store)
    replacement = _issue(store, arguments={"sample": 2})
    initial = {**_citation(first), "proposalRequest": {
        "goalType": "prioritize_within_tier", "userOriginalText": "北京上海优先", "confidence": "high",
        "sourceVersionGuard": 42, "priorityRules": [
            {"domain": "region", "key": "city", "values": ["北京"]},
            {"domain": "region", "key": "city", "values": ["上海"]},
        ],
    }}
    gateway = _gateway(store, initial)
    gateway.codex = RepairHarness([_citation(replacement)])
    output, repaired = await gateway._repair_priority_rule_count(
        "thread-after-restart", TurnOutput.model_validate(initial), {"output": initial, "events": []},
        snapshot=_snapshot(), evidence_ledger={}, artifacts={first["artifactId"]: first}, tenant_id="tenant-1",
    )
    assert repaired is True
    assert output.artifact_refs[0].artifact_id == replacement["artifactId"]
