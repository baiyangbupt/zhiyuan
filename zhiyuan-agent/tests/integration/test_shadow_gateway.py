from __future__ import annotations

import json

import pytest

from app.config import GatewayConfig
from app.gateway.service import GatewayService
from app.harness.binding import ThreadBinding


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
    assert json.loads(codex.injected[-1]["items"][0]["text"])["kind"] == "state_patch"


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


def test_gateway_mode_is_allowlisted() -> None:
    assert GatewayConfig(_env_file=None, mode="codex_shadow").mode == "codex_shadow"
    with pytest.raises(ValueError):
        GatewayConfig(_env_file=None, mode="unsafe")
