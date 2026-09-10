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
        approval_policy: str | None = None,
        sandbox_policy: str | dict[str, Any] | None = None,
    ) -> None:
        self.client = AppServerClient(command, request_timeout=request_timeout)
        self.skill_root = skill_root
        self.approval_policy = approval_policy
        self.sandbox_policy = sandbox_policy

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
        approval_policy: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "baseInstructions": base_instructions,
            "developerInstructions": developer_instructions,
        }
        resolved_skill_root = skill_root or self.skill_root
        if resolved_skill_root:
            params["cwd"] = resolved_skill_root
        effective_approval_policy = approval_policy if approval_policy is not None else self.approval_policy
        if effective_approval_policy is not None:
            params["approvalPolicy"] = effective_approval_policy
        sandbox_mode = _sandbox_mode(self.sandbox_policy)
        if sandbox_mode is not None:
            params["sandbox"] = sandbox_mode
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
        *,
        approval_policy: str | None = None,
        sandbox_policy: str | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"threadId": thread_id, "input": input_items}
        if output_schema is not None:
            params["outputSchema"] = output_schema
        effective_approval_policy = approval_policy if approval_policy is not None else self.approval_policy
        effective_sandbox_policy = sandbox_policy if sandbox_policy is not None else self.sandbox_policy
        if effective_approval_policy is not None:
            params["approvalPolicy"] = effective_approval_policy
        if effective_sandbox_policy is not None:
            params["sandboxPolicy"] = _sandbox_policy(effective_sandbox_policy)
        return await self.client.request("turn/start", params)

    async def start_turn_and_collect(
        self,
        thread_id: str,
        input_items: list[dict[str, Any]],
        output_schema: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
        approval_policy: str | None = None,
        sandbox_policy: str | dict[str, Any] | None = None,
    ) -> CodexTurnResult:
        """Start a turn and wait for its terminal App Server notification."""
        effective_timeout = timeout if timeout is not None else self.client.request_timeout
        started = await self.start_turn(
            thread_id,
            input_items,
            output_schema,
            approval_policy=approval_policy,
            sandbox_policy=sandbox_policy,
        )
        turn_payload = started.get("turn") if isinstance(started, dict) else None
        turn_payload = turn_payload if isinstance(turn_payload, dict) else {}
        turn_id = str(turn_payload.get("id") or started.get("turnId") or "") or None
        initial_status = str(turn_payload.get("status") or "").lower()
        events: list[dict[str, Any]] = []
        final_output = None

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
            item = event.get("item") or {}
            if event.get("type") == "item/completed" and item.get("type") == "agentMessage":
                final_output = _extract_output(event)
            terminal_status = _terminal_status(event)
            if terminal_status is None:
                continue
            return CodexTurnResult(
                status=terminal_status,
                turn_id=turn_id,
                output=(_extract_output(event) or final_output) if terminal_status == "completed" else None,
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
    turn = params.get("turn") or {}
    notification_thread_id = str(params.get("threadId") or params.get("thread_id") or "")
    notification_turn_id = str(
        params.get("turnId") or params.get("turn_id") or turn.get("id") or ""
    )
    return notification_thread_id == thread_id and (
        not notification_turn_id or notification_turn_id == turn_id
    )


def _sandbox_policy(value: str | dict[str, Any]) -> dict[str, Any]:
    """Convert the legacy config spelling into the v2 turn policy object."""
    if isinstance(value, dict):
        return dict(value)
    mapping = {
        "read-only": {"type": "readOnly", "networkAccess": False},
        "workspace-write": {"type": "workspaceWrite", "networkAccess": False},
        "danger-full-access": {"type": "dangerFullAccess"},
    }
    try:
        return mapping[value]
    except KeyError as exc:
        raise ValueError(f"unsupported sandbox policy: {value}") from exc


def _sandbox_mode(value: str | dict[str, Any] | None) -> str | None:
    """Return the thread/start SandboxMode counterpart for a turn policy."""
    if value is None:
        return None
    if isinstance(value, str):
        if value not in {"read-only", "workspace-write", "danger-full-access"}:
            raise ValueError(f"unsupported sandbox policy: {value}")
        return value
    type_name = str(value.get("type") or "")
    mapping = {
        "readOnly": "read-only",
        "workspaceWrite": "workspace-write",
        "dangerFullAccess": "danger-full-access",
    }
    try:
        return mapping[type_name]
    except KeyError as exc:
        raise ValueError(f"unsupported sandbox policy type: {type_name}") from exc


def _notification_to_event(notification: dict[str, Any]) -> dict[str, Any]:
    params = notification.get("params") or {}
    event = dict(params) if isinstance(params, dict) else {}
    event.setdefault("type", notification.get("method"))
    return event


def _terminal_status(event: dict[str, Any]) -> str | None:
    event_type = str(event.get("type") or "").lower()
    if event_type in {"turn/completed", "turn.completed"}:
        status = str((event.get("turn") or {}).get("status") or "completed").lower()
        return status if status in {"completed", "failed", "interrupted"} else None
    if event_type in {"turn/failed", "turn.failed"}:
        return "failed"
    if event_type in {"turn/interrupted", "turn.interrupted"}:
        return "interrupted"
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
            if isinstance(value, list):
                for content in value:
                    if not isinstance(content, dict):
                        continue
                    text = content.get("text")
                    if isinstance(text, str):
                        parsed = _parse_json_object(text)
                        if parsed is not None:
                            return parsed
                    structured = content.get("structuredContent") or content.get("structured_content")
                    if isinstance(structured, dict):
                        return structured
    turn = payload.get("turn")
    if isinstance(turn, dict):
        return _extract_output(turn)
    return None


def _parse_json_object(value: str) -> dict[str, Any] | None:
    value = value.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        value = "\n".join(lines).strip()
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _extract_error(payload: dict[str, Any]) -> str | None:
    value = payload.get("errorCode") or payload.get("error_code") or payload.get("error")
    if not value and isinstance(payload.get("turn"), dict):
        return _extract_error(payload["turn"])
    if isinstance(value, dict):
        value = value.get("code") or value.get("message")
    return str(value) if value else None
