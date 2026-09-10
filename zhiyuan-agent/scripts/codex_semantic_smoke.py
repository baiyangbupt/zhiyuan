#!/usr/bin/env python3
"""Run one real Codex semantic smoke turn against injected business context."""

from __future__ import annotations

import asyncio
import argparse
import json
import os
import sys
import tempfile
import time
from pydantic import ValidationError
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.gateway.service import TURN_OUTPUT_SCHEMA
from app.harness.codex import CodexAppServerHarness
from app.engine.semantic_eval import SemanticExpectation, evaluate_trace
from app.engine.turn_trace import build_turn_trace
from app.engine.tool_orchestration import render_tool_contracts
from app.gateway.contracts import TurnOutput
from app.engine.working_set import ConversationWorkingSet
from app.gateway.contracts import ConversationTurnSnapshot


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "codex"
load_dotenv(ROOT / ".env")


def reference_missing_scope_scenario() -> tuple[dict[str, object], str, SemanticExpectation]:
    return (
        {
            "kind": "conversation_working_set",
            "snapshotVersion": 42,
            "sessionId": "semantic-smoke",
            "snapshot": {
                "snapshotVersion": 42,
                "sessionId": "semantic-smoke",
                "planningStage": "candidate_exploration",
                "scoreContext": {},
                "missingFacts": ["province", "subjectType", "batch"],
                "allowedCapabilities": ["catalog_read", "admission_read"],
            },
            "candidateSet": {
                "scopeVersion": 42,
                "planningStage": "candidate_exploration",
                "sourceTurnId": "turn-1",
                "items": [
                    {"entityId": "school-1", "entityType": "school", "name": "甲大学"},
                    {"entityId": "school-2", "entityType": "school", "name": "乙大学"},
                ],
            },
        },
        "查那几个学校去年的分数",
        SemanticExpectation(
            case_id="reference-missing-history-scope",
            required_message_fragments={"甲大学", "乙大学", "school-1", "school-2"},
            response_type="clarification",
            clarification_required=True,
        ),
    )


def complete_history_scenario() -> tuple[dict[str, object], str, SemanticExpectation]:
    context, _, _ = reference_missing_scope_scenario()
    context["snapshot"]["confirmedConstraints"] = {
        "historyQuery": {
            "areaId": "330000",
            "majorId": "major-cs",
        }
    }
    return (
        context,
        "查那几个学校2025年浙江物理类本科批计算机科学与技术专业的历史最低分",
        SemanticExpectation(
            case_id="reference-complete-history",
            required_entity_ids={"school-1", "school-2"},
            required_tool_names={"admission.get_history"},
            forbidden_tool_names={"plan_apply"},
            response_type={"text", "fact"},
            evidence_required=False,
            clarification_required=False,
        ),
    )


def authoritative_history_scenario() -> tuple[dict[str, object], str, SemanticExpectation]:
    context, message, expectation = complete_history_scenario()
    expectation.case_id = "reference-authoritative-history"
    expectation.response_type = "fact"
    expectation.evidence_required = True
    return context, message, expectation


def mixed_read_write_scenario() -> tuple[dict[str, object], str, SemanticExpectation]:
    context, _, _ = reference_missing_scope_scenario()
    context["snapshot"]["confirmedConstraints"] = {
        "historyQuery": {"areaId": "330000", "majorId": "major-cs"},
        "activePlan": {"artifactId": "plan-1", "items": ["school-1", "school-2", "school-3"]},
    }
    return (
        context,
        "查那几个学校2025年浙江物理类本科批计算机科学与技术专业的历史最低分，然后把方案里的第三个删掉",
        SemanticExpectation(
            case_id="mixed-read-and-write-request",
            required_tool_names={"admission.get_history"},
            forbidden_tool_names={"plan_apply"},
            response_type="fact",
            execution_status="partial",
            limitations_required=True,
            next_step_required=True,
            clarification_required=False,
            proposal_required=True,
        ),
    )


async def run_scenario(
    scenario_factory: object,
) -> dict[str, object]:
    started_at = time.perf_counter()
    binary = os.environ.get("CODEX_APP_SERVER_BIN", "codex")
    semantic_home = ROOT.parent / ".codex-semantic-home"
    if semantic_home.is_dir():
        os.environ.setdefault("CODEX_HOME", str(semantic_home))
    fixture = ROOT / "tests" / "fixtures" / "mcp" / "semantic_readonly_server.py"
    trace_file = tempfile.NamedTemporaryFile(prefix="zhiyuan-semantic-mcp-", suffix=".jsonl", delete=False)
    trace_file.close()
    os.environ["ZHIYUAN_SEMANTIC_MCP_TRACE"] = trace_file.name
    context, user_message, expectation = scenario_factory()
    if expectation.case_id == "reference-authoritative-history":
        os.environ["ZHIYUAN_SEMANTIC_AUTHORITATIVE"] = "true"
    else:
        os.environ.pop("ZHIYUAN_SEMANTIC_AUTHORITATIVE", None)
    fixture_args = [str(fixture)]
    if expectation.case_id == "reference-authoritative-history":
        fixture_args.append("--authoritative")
    model_config = ["mcp_servers.semantic_readonly={"
        f"command={json.dumps(sys.executable)},"
        f"args=[{','.join(json.dumps(item) for item in fixture_args)}]"
        "}",
    ]

    async def accept_readonly_elicitation(request: dict[str, object]) -> dict[str, object]:
        params = request.get("params") or {}
        if params.get("serverName") != "semantic_readonly":
            raise RuntimeError("unexpected_mcp_server_request")
        if request.get("method") != "mcpServer/elicitation/request":
            raise RuntimeError("unexpected_mcp_request_method")
        return {"action": "accept", "content": None}

    harness = CodexAppServerHarness(
        [binary, *sum((["--config", item] for item in model_config), []), "app-server", "--stdio"],
        request_timeout=90.0,
        skill_root=str(SKILL_ROOT),
    )
    harness.set_server_request_handler(accept_readonly_elicitation)
    try:
        await harness.start()
        thread = await harness.create_thread(
            base_instructions=(SKILL_ROOT / "base_instructions.md").read_text(encoding="utf-8"),
            developer_instructions=(SKILL_ROOT / "developer_instructions.md").read_text(
                encoding="utf-8"
            ),
            approval_policy="never",
        )
        thread_id = str(thread.get("thread", {}).get("id") or "")
        if not thread_id:
            raise RuntimeError("thread_not_created")

        snapshot_data = context["snapshot"]
        context_snapshot = ConversationTurnSnapshot(
            snapshotVersion=42,
            sessionId="semantic-smoke",
            planningStage="candidate_exploration",
            confirmedConstraints=snapshot_data.get("confirmedConstraints") or {},
        )
        working_set = ConversationWorkingSet.from_snapshot(context_snapshot)
        working_set.candidate_entities = context["candidateSet"]["items"]
        result = await harness.start_turn_and_collect(
            thread_id,
            [
                {"type": "text", "text": working_set.as_context_text()},
                {"type": "text", "text": render_tool_contracts()},
                {"type": "text", "text": user_message},
            ],
            TURN_OUTPUT_SCHEMA,
            timeout=90.0,
        )
        payload: dict[str, object] = {
            "scenario": expectation.case_id,
            "status": result.status,
            "errorCode": result.error_code,
            "output": result.output,
            "eventTypes": [event.get("type") for event in result.events],
            "eventSummaries": [
                {
                    "type": event.get("type"),
                    "keys": sorted(str(key) for key in event),
                    "text": str(
                        event.get("text")
                        or event.get("message")
                        or event.get("delta")
                        or ""
                    )[:500],
                }
                for event in result.events
            ],
            "errors": [
                event
                for event in result.events
                if str(event.get("type") or "").lower() == "error"
            ],
            "contextCandidateIds": ["school-1", "school-2"],
        }
        mcp_calls: list[dict[str, object]] = []
        try:
            mcp_calls = [
                json.loads(line)
                for line in Path(trace_file.name).read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except OSError:
            pass
        payload["mcpCalls"] = mcp_calls
        payload["modelUsedCandidateIds"] = sorted(
            {
                str(value)
                for call in mcp_calls
                for value in (call.get("arguments") or {}).values()
                if str(value) in {"school-1", "school-2"}
            }
        )
        if not payload["modelUsedCandidateIds"]:
            payload["modelUsedCandidateIds"] = sorted(
                {
                    str(value)
                    for event in result.events
                    for value in _walk_values(event)
                    if str(value) in {"school-1", "school-2"}
                }
            )
        if result.status == "completed" and isinstance(result.output, dict):
            try:
                output = TurnOutput.model_validate(result.output)
            except ValidationError as exc:
                payload["outputValidationError"] = str(exc)
                payload["trace"] = {
                    "toolCalls": [],
                    "evidenceIds": [],
                    "entityIds": payload["modelUsedCandidateIds"],
                    "responseType": result.output.get("responseType"),
                    "message": result.output.get("message", ""),
                    "clarificationRequested": result.output.get("responseType")
                    in {"clarification", "needs_clarification"},
                    "proposalRef": result.output.get("proposalRef"),
                }
                payload["evaluation"] = evaluate_trace(expectation, payload["trace"])
                payload["elapsedMs"] = round((time.perf_counter() - started_at) * 1000, 1)
                return payload
            trace = build_turn_trace(
                {"events": [*result.events, *_recorded_mcp_events(mcp_calls)]},
                output,
                entity_ids=payload["modelUsedCandidateIds"],
            )
            payload["trace"] = trace.as_payload()
            payload["evaluation"] = evaluate_trace(expectation, trace.as_payload())
        payload["elapsedMs"] = round((time.perf_counter() - started_at) * 1000, 1)
        return payload
    finally:
        await harness.close()
        Path(trace_file.name).unlink(missing_ok=True)


def _recorded_mcp_events(calls: list[dict[str, object]]) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for call in calls:
        name = call.get("name")
        arguments = call.get("arguments")
        if isinstance(name, str) and name and isinstance(arguments, dict):
            events.append(
                {
                    "type": "mcpToolCall",
                    "toolName": name,
                    "arguments": arguments,
                    "status": "completed",
                }
            )
    return events


def _walk_values(value: object) -> list[object]:
    if isinstance(value, dict):
        result: list[object] = []
        for nested in value.values():
            result.extend(_walk_values(nested))
        return result
    if isinstance(value, list):
        result: list[object] = []
        for nested in value:
            result.extend(_walk_values(nested))
        return result
    return [value]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        choices=["reference-missing-scope", "reference-complete-history", "reference-authoritative-history", "mixed-read-write"],
        default="reference-missing-scope",
    )
    args = parser.parse_args()
    factory = (
        authoritative_history_scenario
        if args.scenario == "reference-authoritative-history"
        else complete_history_scenario
        if args.scenario == "reference-complete-history"
        else mixed_read_write_scenario
        if args.scenario == "mixed-read-write"
        else reference_missing_scope_scenario
    )
    print(json.dumps(asyncio.run(run_scenario(factory)), ensure_ascii=False))
