from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _text(item: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def adapt_codex_item(item: Mapping[str, Any]) -> dict[str, Any] | None:
    """Convert Codex notifications into the stable, user-visible event set."""
    if not isinstance(item, Mapping):
        return None
    item_type = str(item.get("type") or "")
    if item_type in {"item/agentMessage/delta", "agentMessage/delta", "assistant.delta"}:
        return {"type": "assistant.delta", "content": _text(item, "delta", "text", "content")}
    if item_type in {"turn/completed", "item/agentMessage/completed", "assistant.completed"}:
        return {"type": "assistant.completed", "content": _text(item, "message", "text", "content")}
    if item_type in {"mcpToolCall", "item/mcpToolCall", "mcp_tool_call"}:
        status = _text(item, "status") or "completed"
        return {"type": "planning.status", "status": status}
    if item_type in {"evidence.updated", "evidenceUpdated"}:
        evidence_ids = item.get("evidenceIds") or item.get("evidence_ids") or []
        safe_ids = [value for value in evidence_ids if isinstance(value, str)]
        return {"type": "evidence.updated", "evidenceIds": safe_ids}
    if item_type in {"recommendation.card", "recommendationCard"}:
        artifact_id = _text(item, "artifactId", "artifact_id")
        return {"type": "recommendation.card", "artifactId": artifact_id} if artifact_id else None
    return None
