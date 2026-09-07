from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from app.gateway.contracts import ConversationTurnSnapshot, TurnOutput
from app.gateway.event_adapter import adapt_codex_item
from app.gateway.output_validation import OutputContractError, validate_turn_output
from app.gateway.snapshot import build_snapshot, diff_snapshots


TURN_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["responseType", "message", "artifactRefs", "evidenceRefs", "uncertainties"],
    "properties": {
        "responseType": {"type": "string"},
        "message": {"type": "string"},
        "artifactRefs": {"type": "array"},
        "evidenceRefs": {"type": "array"},
        "uncertainties": {"type": "array"},
        "clarification": {"type": ["string", "null"]},
        "proposalRef": {"type": ["string", "null"]},
    },
    "additionalProperties": False,
}


def _maybe_await(value: Any) -> Any:
    return value if inspect.isawaitable(value) else _Immediate(value)


class _Immediate:
    def __init__(self, value: Any) -> None:
        self.value = value

    def __await__(self):
        async def _return():
            return self.value

        return _return().__await__()


def _snapshot_payload(payload: Any) -> ConversationTurnSnapshot:
    if isinstance(payload, ConversationTurnSnapshot):
        return payload
    if isinstance(payload, Mapping) and "data" in payload and "sessionId" not in payload:
        payload = payload.get("data")
    return build_snapshot(payload)


def _by_id(values: Any, *keys: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(values, Mapping):
        return {str(key): value for key, value in values.items()}
    for value in values or []:
        if isinstance(value, Mapping):
            for key in keys:
                identifier = value.get(key)
                if identifier:
                    result[str(identifier)] = value
                    break
        else:
            identifier = getattr(value, keys[0], None)
            if identifier:
                result[str(identifier)] = value
    return result


class GatewayService:
    """Orchestrate one conversation turn behind a stable Gateway contract."""

    def __init__(
        self,
        *,
        mode: str,
        codex: Any,
        legacy: Any,
        message_store: Any,
        binding_loader: Callable[..., Any],
        snapshot_loader: Callable[..., Any],
        base_instructions: str = "",
        developer_instructions: str = "",
    ) -> None:
        if mode not in {"legacy", "codex_shadow", "codex_readonly"}:
            raise ValueError("unsupported gateway mode")
        self.mode = mode
        self.codex = codex
        self.legacy = legacy
        self.message_store = message_store
        self.binding_loader = binding_loader
        self.snapshot_loader = snapshot_loader
        self.base_instructions = base_instructions
        self.developer_instructions = developer_instructions
        self._threads: dict[str, str] = {}
        self._snapshots: dict[str, ConversationTurnSnapshot] = {}
        self._turn_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def handle_turn(
        self,
        *,
        tenant_id: str,
        session_id: str,
        user_id: str,
        turn_id: str,
        content: str,
    ) -> dict[str, Any]:
        cache_key = (str(session_id), str(turn_id))
        async with self._lock:
            cached = self._turn_cache.get(cache_key)
            if cached is not None:
                return cached
            result = await self._handle_uncached(
                tenant_id=tenant_id,
                session_id=session_id,
                user_id=user_id,
                turn_id=turn_id,
                content=content,
            )
            self._turn_cache[cache_key] = result
            return result

    async def _handle_uncached(
        self,
        *,
        tenant_id: str,
        session_id: str,
        user_id: str,
        turn_id: str,
        content: str,
    ) -> dict[str, Any]:
        if self.message_store is not None:
            await self.message_store.save_user_message(str(session_id), content)

        if self.mode == "legacy":
            reply = await self._legacy_reply(session_id, user_id, content)
            await self._persist_agent(session_id, reply)
            return {
                "mode": self.mode,
                "reply": reply,
                "events": [],
                "snapshotVersion": None,
                "writeAttempted": False,
            }

        try:
            binding = await _maybe_await(
                self.binding_loader(
                    tenant_id=tenant_id,
                    session_id=session_id,
                    user_id=user_id,
                    turn_id=turn_id,
                )
            )
            snapshot = _snapshot_payload(
                await _maybe_await(
                    self.snapshot_loader(
                        tenant_id=tenant_id,
                        session_id=session_id,
                        skill=None,
                    )
                )
            )
        except Exception as exc:
            return {
                "mode": self.mode,
                "reply": "当前会话状态暂时不可用，请稍后重试。",
                "events": [],
                "snapshotVersion": None,
                "writeAttempted": False,
                "error": f"context_unavailable: {type(exc).__name__}",
            }
        previous_snapshot = self._snapshots.get(str(session_id))
        state_patch = None
        if previous_snapshot is not None:
            try:
                if snapshot.snapshot_version == previous_snapshot.snapshot_version + 1:
                    state_patch = diff_snapshots(previous_snapshot, snapshot)
            except ValueError:
                state_patch = None
        self._snapshots[str(session_id)] = snapshot

        codex_task = asyncio.create_task(
            self._codex_turn(snapshot, binding, content, session_id, state_patch)
        )
        if self.mode == "codex_shadow":
            legacy_task = asyncio.create_task(self._legacy_reply(session_id, user_id, content))
            codex_result, reply = await asyncio.gather(codex_task, legacy_task, return_exceptions=True)
            if isinstance(reply, Exception):
                return {
                    "mode": self.mode,
                    "reply": "处理消息时出错，请稍后重试",
                    "events": [],
                    "snapshotVersion": snapshot.snapshot_version,
                    "statePatch": state_patch.model_dump(by_alias=True) if state_patch else None,
                    "writeAttempted": False,
                    "codexError": type(codex_result).__name__ if isinstance(codex_result, Exception) else None,
                }
            await self._persist_agent(session_id, reply)
            result: dict[str, Any] = {
                "mode": self.mode,
                "reply": reply,
                "events": [],
                "snapshotVersion": snapshot.snapshot_version,
                "statePatch": state_patch.model_dump(by_alias=True) if state_patch else None,
                "writeAttempted": False,
            }
            if isinstance(codex_result, Exception):
                result["codexError"] = str(codex_result)
            else:
                result["codex"] = codex_result
            return result

        codex_result = await codex_task
        if codex_result.get("error"):
            return {
                "mode": self.mode,
                "reply": "当前对话引擎暂时不可用，请稍后重试。",
                "events": codex_result.get("events", []),
                "snapshotVersion": snapshot.snapshot_version,
                "statePatch": state_patch.model_dump(by_alias=True) if state_patch else None,
                "writeAttempted": False,
                "error": codex_result["error"],
            }
        output = codex_result["output"]
        await self._persist_agent(session_id, output.message)
        return {
            "mode": self.mode,
            "reply": output.message,
            "events": codex_result.get("events", []),
            "snapshotVersion": snapshot.snapshot_version,
            "statePatch": state_patch.model_dump(by_alias=True) if state_patch else None,
            "writeAttempted": bool(output.proposal_ref),
            "output": output.model_dump(by_alias=True),
        }

    async def _legacy_reply(self, session_id: str, user_id: str, content: str) -> str:
        if self.legacy is None:
            raise RuntimeError("legacy service unavailable")
        reply = await self.legacy.handle_message(
            session_id=str(session_id), user_id=str(user_id), content=content
        )
        if hasattr(reply, "content"):
            return str(reply.content)
        return str(reply)

    async def _persist_agent(self, session_id: str, reply: Any) -> None:
        if self.message_store is not None:
            await self.message_store.save_agent_message(str(session_id), str(reply), "reply")

    async def _codex_turn(
        self,
        snapshot: ConversationTurnSnapshot,
        binding: Any,
        content: str,
        session_id: str,
        state_patch: Any = None,
    ) -> dict[str, Any]:
        del binding  # binding is resolved before this call; Codex never supplies identity.
        if self.codex is None:
            return {"error": "codex_unavailable", "events": []}
        try:
            thread_id = self._threads.get(str(session_id))
            if not thread_id:
                created = await self.codex.create_thread(
                    base_instructions=self.base_instructions,
                    developer_instructions=self.developer_instructions,
                )
                thread_id = str(created.get("thread", {}).get("id") or "")
                if not thread_id:
                    return {"error": "thread_not_created", "events": []}
                self._threads[str(session_id)] = thread_id
            if state_patch is not None:
                state_payload = {"kind": "state_patch", "patch": state_patch.model_dump(by_alias=True)}
            else:
                state_payload = {
                    "kind": "turn_snapshot",
                    "snapshot": snapshot.model_dump(by_alias=True),
                }
            snapshot_item = {"type": "text", "text": json.dumps(state_payload, ensure_ascii=False)}
            await self.codex.inject_items(thread_id, [snapshot_item])
            turn = await self.codex.start_turn(
                thread_id,
                [{"type": "text", "text": content}],
                TURN_OUTPUT_SCHEMA,
            )
            events: list[dict[str, Any]] = []
            for item in turn.get("events", []) if isinstance(turn, Mapping) else []:
                event = adapt_codex_item(item)
                if event is not None:
                    events.append(event)
            raw_output = turn.get("output") if isinstance(turn, Mapping) else None
            if raw_output is None and isinstance(turn, Mapping):
                raw_output = turn.get("turn", {}).get("output")
            if raw_output is None:
                raw_output = {"responseType": "text", "message": ""}
            output = TurnOutput.model_validate(raw_output)
            evidence_ledger = _by_id(
                turn.get("evidenceLedger", []) if isinstance(turn, Mapping) else [],
                "evidenceId",
                "evidence_id",
            )
            artifacts = _by_id(
                turn.get("artifacts", []) if isinstance(turn, Mapping) else [],
                "artifactId",
                "artifact_id",
            )
            validate_turn_output(
                turn_output=output,
                current_snapshot=snapshot,
                evidence_ledger=evidence_ledger,
                artifacts=artifacts,
                thread_id=thread_id,
            )
            return {"output": output, "events": events, "threadId": thread_id}
        except (OutputContractError, ValueError, KeyError) as exc:
            return {"error": str(exc), "events": []}
        except Exception as exc:
            return {"error": type(exc).__name__, "events": []}
