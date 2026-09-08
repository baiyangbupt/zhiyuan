from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, cast

from app.harness.client import AppServerClient
from app.harness.turn_result import CodexTurnResult, TurnStatus


class CodexAppServerHarness:
    def __init__(
        self,
        command: list[str],
        *,
        request_timeout: float = 30.0,
        skill_root: str | None = None,
    ) -> None:
        self.client = AppServerClient(command, request_timeout=request_timeout)
        self.skill_root = skill_root

    async def start(self) -> None:
        await self.client.start()
        await self.client.initialize(client_name="zhiyuan_gateway", client_version="0.1.0")

    def set_server_request_handler(self, handler: Any) -> None:
        self.client.server_request_handler = handler

    async def create_thread(
        self,
        *,
        base_instructions: str = "",
        developer_instructions: str = "",
        skill_root: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "baseInstructions": base_instructions,
            "developerInstructions": developer_instructions,
        }
        resolved_skill_root = skill_root or self.skill_root
        if resolved_skill_root:
            params["cwd"] = resolved_skill_root
        return await self.client.request("thread/start", params)

    async def resume_thread(self, thread_id: str) -> dict[str, Any]:
        return await self.client.request("thread/resume", {"threadId": thread_id})

    async def inject_items(self, thread_id: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        return await self.client.request(
            "thread/inject_items", {"threadId": thread_id, "items": items}
        )

    async def start_turn(
        self,
        thread_id: str,
        input_items: list[dict[str, Any]],
        output_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"threadId": thread_id, "input": input_items}
        if output_schema is not None:
            params["outputSchema"] = output_schema
        return await self.client.request("turn/start", params)

    async def start_turn_and_collect(
        self,
        thread_id: str,
        input_items: list[dict[str, Any]],
        output_schema: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> CodexTurnResult:
        """Start a turn and wait for its terminal App Server notification."""
        effective_timeout = timeout if timeout is not None else self.client.request_timeout
        started = await self.start_turn(thread_id, input_items, output_schema)
        turn_payload = started.get("turn") if isinstance(started, dict) else None
        turn_payload = turn_payload if isinstance(turn_payload, dict) else {}
        turn_id = str(turn_payload.get("id") or started.get("turnId") or "") or None
        initial_status = str(turn_payload.get("status") or "").lower()
        events: list[dict[str, Any]] = []

        if initial_status in {"completed", "failed", "interrupted"}:
            return CodexTurnResult(
                status=cast(TurnStatus, initial_status),
                turn_id=turn_id,
                output=_extract_output(started),
                payload=started,
            )
        if not turn_id:
            return CodexTurnResult(
                status="failed",
                error_code="turn_id_missing",
            )

        loop = asyncio.get_running_loop()
        deadline = loop.time() + effective_timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                try:
                    await self.interrupt_turn(thread_id, turn_id)
                except Exception:
                    pass
                return CodexTurnResult(
                    status="timed_out",
                    turn_id=turn_id,
                    events=events,
                    error_code="turn_timeout",
                    payload={"turnId": turn_id},
                )
            try:
                notification = await self.client.wait_for_notification(
                    lambda item: _matches_turn(item, thread_id, turn_id),
                    timeout=remaining,
                )
            except asyncio.TimeoutError:
                try:
                    await self.interrupt_turn(thread_id, turn_id)
                except Exception:
                    pass
                return CodexTurnResult(
                    status="timed_out",
                    turn_id=turn_id,
                    events=events,
                    error_code="turn_timeout",
                    payload={"turnId": turn_id},
                )

            event = _notification_to_event(notification)
            events.append(event)
            terminal_status = _terminal_status(event)
            if terminal_status is None:
                continue
            return CodexTurnResult(
                status=terminal_status,
                turn_id=turn_id,
                output=_extract_output(event),
                events=events,
                error_code=_extract_error(event),
                payload=event,
            )

    async def steer_turn(
        self, thread_id: str, turn_id: str, input_items: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return await self.client.request(
            "turn/steer",
            {"threadId": thread_id, "expectedTurnId": turn_id, "input": input_items},
        )

    async def interrupt_turn(self, thread_id: str, turn_id: str) -> dict[str, Any]:
        return await self.client.request(
            "turn/interrupt", {"threadId": thread_id, "turnId": turn_id}
        )

    async def next_event(self) -> dict[str, Any]:
        return await self.client.next_notification()

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        while True:
            yield await self.next_event()

    async def close(self) -> None:
        await self.client.close()


def _matches_turn(notification: dict[str, Any], thread_id: str, turn_id: str) -> bool:
    params = notification.get("params") or {}
    return (
        str(params.get("threadId") or params.get("thread_id") or "") == thread_id
        and str(params.get("turnId") or params.get("turn_id") or "") == turn_id
    )


def _notification_to_event(notification: dict[str, Any]) -> dict[str, Any]:
    params = notification.get("params") or {}
    event = dict(params) if isinstance(params, dict) else {}
    event.setdefault("type", notification.get("method"))
    return event


def _terminal_status(event: dict[str, Any]) -> str | None:
    event_type = str(event.get("type") or "").lower()
    if event_type in {"turn/completed", "turn.completed"}:
        return "completed"
    if event_type in {"turn/failed", "turn.failed"}:
        return "failed"
    if event_type in {"turn/interrupted", "turn.interrupted"}:
        return "interrupted"
    if event_type in {"item/completed", "item.completed"}:
        item = event.get("item")
        if isinstance(item, dict) and str(item.get("type") or "").lower() in {
            "agentmessage",
            "agent_message",
            "assistantmessage",
        }:
            return "completed"
    return None


def _extract_output(payload: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("output", "structuredOutput", "structured_output"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            parsed = _parse_json_object(value)
            if parsed is not None:
                return parsed
    item = payload.get("item")
    if isinstance(item, dict):
        extracted = _extract_output(item)
        if extracted is not None:
            return extracted
        for key in ("text", "content"):
            value = item.get(key)
            if isinstance(value, str):
                parsed = _parse_json_object(value)
                if parsed is not None:
                    return parsed
    turn = payload.get("turn")
    if isinstance(turn, dict):
        return _extract_output(turn)
    return None


def _parse_json_object(value: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _extract_error(payload: dict[str, Any]) -> str | None:
    value = payload.get("errorCode") or payload.get("error_code") or payload.get("error")
    if isinstance(value, dict):
        value = value.get("code") or value.get("message")
    return str(value) if value else None
