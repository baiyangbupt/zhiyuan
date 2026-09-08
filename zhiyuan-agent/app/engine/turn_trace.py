from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.gateway.contracts import TurnOutput
from app.engine.tool_orchestration import build_tool_batch_report, prepare_tool_invocation


@dataclass(slots=True)
class TurnTrace:
    """Observable execution facts for evaluation, not model reasoning."""

    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    entity_ids: list[str] = field(default_factory=list)
    response_type: str = ""
    message: str = ""
    clarification_requested: bool = False
    proposal_ref: str | None = None
    orchestration: list[dict[str, Any]] = field(default_factory=list)
    batch_report: dict[str, Any] = field(default_factory=dict)

    def as_payload(self) -> dict[str, Any]:
        return {
            "toolCalls": self.tool_calls,
            "evidenceIds": self.evidence_ids,
            "entityIds": self.entity_ids,
            "responseType": self.response_type,
            "message": self.message,
            "clarificationRequested": self.clarification_requested,
            "proposalRef": self.proposal_ref,
            "orchestration": self.orchestration,
            "batchReport": self.batch_report,
        }


def build_turn_trace(payload: Any, output: TurnOutput, *, entity_ids: list[str]) -> TurnTrace:
    tool_calls: list[dict[str, Any]] = []
    orchestration: list[dict[str, Any]] = []
    for item in _walk(payload):
        item_type = str(item.get("type") or "").lower()
        if "mcp" not in item_type and not any(
            key in item for key in ("toolName", "tool_name", "toolCall", "tool_call")
        ):
            continue
        name = (
            item.get("toolName")
            or item.get("tool_name")
            or item.get("tool")
            or item.get("name")
            or item.get("method")
        )
        nested = item.get("toolCall") or item.get("tool_call")
        if isinstance(nested, dict):
            name = name or nested.get("name") or nested.get("toolName")
        if isinstance(name, dict):
            name = name.get("name") or name.get("toolName") or name.get("tool")
        arguments = item.get("arguments") or item.get("args")
        if not isinstance(arguments, dict) and isinstance(nested, dict):
            arguments = nested.get("arguments") or nested.get("args")
        normalized_arguments = arguments if isinstance(arguments, dict) else {}
        preparation = prepare_tool_invocation(str(name or ""), normalized_arguments)
        tool_calls.append(
            {
                "name": str(name) if name else "",
                "status": str(item.get("status") or "completed"),
                "argumentKeys": sorted(str(key) for key in arguments) if isinstance(arguments, dict) else [],
            }
        )
        orchestration.append(
            {
                "name": preparation.tool_name,
                "invocationKey": preparation.invocation_key,
                "argumentKeys": sorted(preparation.normalized_arguments),
                "missingArguments": list(preparation.missing_arguments),
                "ready": preparation.ready,
                "duplicate": False,
            }
        )

    seen_keys: set[str] = set()
    for item in orchestration:
        key = str(item["invocationKey"])
        item["duplicate"] = key in seen_keys
        seen_keys.add(key)

    evidence_ids = [reference.evidence_id for reference in output.evidence_refs]
    return TurnTrace(
        tool_calls=_dedupe_tools(tool_calls),
        evidence_ids=list(dict.fromkeys(evidence_ids)),
        entity_ids=list(dict.fromkeys(str(value) for value in entity_ids)),
        response_type=output.response_type,
        message=output.message,
        clarification_requested=output.response_type == "clarification" or bool(output.clarification),
        proposal_ref=output.proposal_ref,
        orchestration=_dedupe_orchestration(orchestration),
        batch_report=build_tool_batch_report(payload).as_payload(),
    )


def _walk(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        result = [value]
        for nested in value.values():
            result.extend(_walk(nested))
        return result
    if isinstance(value, list):
        result: list[dict[str, Any]] = []
        for nested in value:
            result.extend(_walk(nested))
        return result
    return []


def _dedupe_tools(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    result: list[dict[str, Any]] = []
    for value in values:
        key = (value["name"], value["status"], tuple(value["argumentKeys"]))
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _dedupe_orchestration(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, bool]] = set()
    for value in values:
        key = (str(value["invocationKey"]), bool(value["duplicate"]))
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result
