"""Confirmation eligibility belongs only to the latest uncanceled preview."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.messages import ModelRequest, ToolReturnPart

from app.models.conversation_phase import ConversationPhase, PendingConfirmation, PhaseState
from app.service import _compact_tool_return_content
from app.zhiyuan_agent.tools import confirm_pending, preview_plan_change
from tests.factories import make_request_context, make_run_context


def _preview_payload(proposal_id="preview-old"):
    return {
        "data": {
            "pending_created": False,
            "requires_confirmation": True,
            "review_fix_prepare_candidate": {
                "proposal_id": proposal_id,
                "proposal_source": "review_check",
                "source_version_guard": 12,
                "command_digest": f"command-{proposal_id}",
                "preview_digest": f"digest-{proposal_id}",
            },
        },
        "next_step": "confirm",
        "message": "审查修复预览",
    }


def _tool_message(tool_name, payload, *, compact=False):
    content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    if compact:
        content = _compact_tool_return_content(content)
    return ModelRequest(
        parts=[ToolReturnPart(tool_name=tool_name, content=content, tool_call_id=tool_name)]
    )


def _context(messages=None, *, dry_run=False):
    context = make_request_context(
        planning_phase="ordered", planning_ordered_total=45, planning_ordered_target_total=45
    )
    context.agent_messages = list(messages or [])
    context.dry_run_state_mutations = dry_run
    files = {
        "pending.json": {"active": False},
        "plan/summary.json": {"has_plan": True, "version": 12, "ordered_total": 45},
    }
    context.sandbox = SimpleNamespace(
        read=AsyncMock(side_effect=lambda path, **kwargs: dict(files.get(path, {}))),
        invalidate=lambda paths: None,
    )
    return make_run_context(request_context=context)


@pytest.fixture
def backend(mocker):
    writes = []

    def record_write(method):
        async def write(*args, **kwargs):
            writes.append((method, args, kwargs))
            return {"code": 409, "msg": "No mutation is allowed in this test"}

        return AsyncMock(side_effect=write)

    for method in (
        "prepare_review_fix_proposal",
        "claim_pending_confirmation",
        "execute_pending_planning_command",
        "save_pending_confirmation",
    ):
        mocker.patch(f"app.zhiyuan_agent.tools.internal_client.{method}", record_write(method))
    preview = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.preview_review_fix_proposals",
        AsyncMock(return_value={"code": 0, "data": {"sourceVersionGuard": 12, "proposals": []}}),
    )
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.get_planning_workspace_state",
        AsyncMock(return_value={"code": 0, "data": {"version": 12}}),
    )
    return SimpleNamespace(writes=writes, preview=preview)


def _assert_not_confirmable(result, backend):
    assert result["next_step"] == "respond"
    assert result["data"] == {"active": False, "action": "confirm"}
    assert backend.writes == []


@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("current_messages", [False, True])
@pytest.mark.parametrize(
    ("tool_name", "payload"),
    [
        ("preview_plan_change", {"data": {"reason": "review_repair_proposal_unavailable"}}),
        ("preview_plan_change", "unreadable preview result"),
        ("preview_plan_action", {"next_step": "confirm", "message": "替代方案操作预览"}),
        ("preview_intent_change", {"next_step": "confirm", "message": "替代偏好预览"}),
        ("confirm_pending", {"data": {"action": "cancel", "active": False}}),
        ("confirm_pending", {"data": {"action": "confirm", "applied": True}}),
    ],
)
async def test_confirmation_never_scans_past_a_later_lifecycle_result(
    backend, compact, current_messages, tool_name, payload
):
    old_preview = _tool_message("preview_plan_change", _preview_payload(), compact=compact)
    barrier = _tool_message(tool_name, payload, compact=compact)
    context = _context([old_preview])
    if current_messages:
        context.messages = [barrier]
    else:
        context.deps.agent_messages.append(barrier)

    result = json.loads(await confirm_pending(context, action="confirm"))

    _assert_not_confirmable(result, backend)


@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("action", ["cancel", "reject", "decline"])
async def test_cancel_without_pending_ends_readonly_preview_eligibility(backend, compact, action):
    old_preview = _tool_message("preview_plan_change", _preview_payload(), compact=compact)
    context = _context([old_preview])

    cancelled = json.loads(await confirm_pending(context, action=action))
    assert cancelled["data"] == {"active": False, "action": "cancel"}
    assert backend.writes == []
    next_context = _context(
        [old_preview, _tool_message("confirm_pending", cancelled, compact=compact)]
    )

    result = json.loads(await confirm_pending(next_context, action="confirm"))

    _assert_not_confirmable(result, backend)


@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("current_messages", [False, True])
async def test_latest_valid_preview_remains_confirmable_after_a_barrier(
    backend, compact, current_messages
):
    context = _context(
        [
            _tool_message("preview_plan_change", _preview_payload(), compact=compact),
            _tool_message("confirm_pending", {"data": {"action": "cancel"}}, compact=compact),
        ],
        dry_run=True,
    )
    newest = _tool_message("preview_plan_change", _preview_payload("preview-new"), compact=compact)
    if current_messages:
        context.messages = [newest]
    else:
        context.deps.agent_messages.append(newest)

    result = json.loads(await confirm_pending(context, action="confirm"))

    assert result["data"]["proposal_id"] == "preview-new"
    assert result["data"]["would_apply"] is True
    assert result["data"]["applied"] is False
    assert backend.writes == []


@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("active_pending", [False, True])
async def test_valid_confirmation_executes_once_despite_older_lifecycle_barriers(
    backend, mocker, compact, active_pending
):
    history = [
        _tool_message("preview_plan_change", _preview_payload(), compact=compact),
        _tool_message("confirm_pending", {"data": {"action": "cancel"}}, compact=compact),
    ]
    if not active_pending:
        history.append(
            _tool_message("preview_plan_change", _preview_payload("preview-new"), compact=compact)
        )
    context = _context(history)
    raw_pending = {
        "pendingId": "pending-new",
        "operationId": "operation-new",
        "kind": "plan_mutation",
        "actionFamily": "apply_plan_change_proposal",
        "proposalId": "preview-new",
        "proposalSource": "review_check",
        "sourceVersion": 12,
        "previewDigest": "digest-preview-new",
        "commandDigest": "command-preview-new",
    }
    if active_pending:
        context.deps.conversation_phase = ConversationPhase(
            state=PhaseState.PLAN_PREVIEWING,
            pending=PendingConfirmation(
                pending_id="pending-new", kind="plan_mutation",
                action_family="apply_plan_change_proposal",
            ),
        )
        context.deps.sandbox.read.return_value = {
            "active": True, "pending_id": "pending-new", "kind": "plan_mutation",
            "action_family": "apply_plan_change_proposal", "source_backend_version": 12,
            "execution_payload": {"proposal_apply": dict(raw_pending)},
            "raw": dict(raw_pending), "version": 12,
        }
        context.deps.sandbox.read.side_effect = None
    responses = {
        "prepare_review_fix_proposal": {
            "status": "prepared", "pendingId": "pending-new", "operationId": "operation-new",
        },
        "get_last_pending_confirmation": {
            "pendingId": "pending-new", "revision": 1, "status": "active",
            "dataValue": dict(raw_pending),
        },
        "claim_pending_confirmation": {
            "pendingId": "pending-new", "revision": 2, "transitionApplied": True,
            "claimToken": "claim-new", "dataValue": {**raw_pending, "status": "applying"},
        },
        "save_pending_confirmation": {"transitionApplied": True},
    }
    for method, data in responses.items():
        mocker.patch(
            f"app.zhiyuan_agent.tools.internal_client.{method}",
            AsyncMock(return_value={"code": 0, "data": data}),
        )
    applied_proposals = []

    async def execute(_tenant_id, _session_id, **kwargs):
        assert kwargs["pending_id"] == "pending-new"
        assert kwargs["operation_id"] == "operation-new"
        assert kwargs["claim_token"] == "claim-new"
        assert kwargs["expected_plan_version"] == 12
        applied_proposals.append(kwargs["proposal_apply"]["proposalId"])
        return {
            "code": 0,
            "data": {"postconditionReport": {"proposalSource": "review_check", "satisfied": True}},
        }

    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.execute_pending_planning_command",
        AsyncMock(side_effect=execute),
    )

    result = json.loads(await confirm_pending(context, action="confirm"))

    assert result["data"]["applied"] is True
    assert result["data"]["pending_id"] == "pending-new"
    assert applied_proposals == ["preview-new"]
    history.append(_tool_message("confirm_pending", result, compact=compact))
    repeated = json.loads(await confirm_pending(_context(history), action="confirm"))
    _assert_not_confirmable(repeated, backend)
    assert applied_proposals == ["preview-new"]


def _coverage_proposal(issue_code):
    return {
        "proposalId": f"proposal-{issue_code}",
        "proposalSource": "review_check",
        "sourceVersionGuard": 12,
        "status": "ready",
        "strategy": "fill_missing_count",
        "sourceCheckCodes": [issue_code],
        "commandDigest": f"command-{issue_code}",
        "previewDigest": f"preview-{issue_code}",
        "dryRunResult": {"status": "ready"},
    }


async def _coverage_preview(backend, requested_issue, source_codes):
    backend.preview.return_value["data"]["proposals"] = [
        _coverage_proposal(code) for code in source_codes
    ]
    return json.loads(
        await preview_plan_change(
            _context(),
            spec={
                "repair_goal": {
                    "review_issue_code": requested_issue,
                    "strategy": "must_include_scope",
                }
            },
        )
    )


@pytest.mark.parametrize("source_code", ["coverage:1", "coverage:10", "coverage:00", "coverage"])
async def test_explicit_coverage_index_never_selects_another_coverage(backend, source_code):
    result = await _coverage_preview(backend, "coverage:0", [source_code])

    assert result["next_step"] == "respond"
    assert result["data"]["reason"] == "review_repair_proposal_unavailable"
    assert result["data"]["matching_proposals"] == []
    assert result["data"]["pending_created"] is False
    assert result["data"]["requires_confirmation"] is False
    assert backend.writes == []


async def test_explicit_coverage_index_selects_exact_match_among_multiple_proposals(backend):
    result = await _coverage_preview(backend, "coverage:0", ["coverage:1", "coverage:0"])

    assert result["next_step"] == "confirm"
    assert result["data"]["proposal"]["proposal_id"] == "proposal-coverage:0"
    assert result["data"]["review_fix_prepare_candidate"]["proposal_id"] == "proposal-coverage:0"
    assert result["data"]["pending_created"] is False
    assert backend.writes == []


async def test_generic_coverage_keeps_multiple_ready_proposals_ambiguous(backend):
    result = await _coverage_preview(backend, "coverage", ["coverage:0", "coverage:1"])

    assert result["next_step"] == "respond"
    assert result["data"]["reason"] == "review_repair_proposal_ambiguous"
    assert {item["proposal_id"] for item in result["data"]["matching_proposals"]} == {
        "proposal-coverage:0", "proposal-coverage:1"
    }
    assert result["data"]["pending_created"] is False
    assert result["data"]["requires_confirmation"] is False
    assert backend.writes == []
