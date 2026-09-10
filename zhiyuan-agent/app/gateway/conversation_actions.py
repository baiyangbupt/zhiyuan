"""将模型表达的会话动作桥接到后端 Pending/CAS 接口。

本模块不解析自然语言，也不决定模型是否应该确认；它只消费已经通过
Gateway 合约校验的结构化 ConversationAction。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping
import uuid

from app.gateway.contracts import ConversationAction, ConversationTurnSnapshot
from app.util.internal_client import resolve_pending_confirmation


@dataclass(frozen=True)
class ConversationActionResult:
    action_status: str
    proposal_ref: str | None = None
    new_state_version: int | None = None
    actual_changes: list[dict[str, Any]] = field(default_factory=list)
    code: str | None = None
    message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "actionStatus": self.action_status,
            "proposalRef": self.proposal_ref,
            "newStateVersion": self.new_state_version,
            "actualChanges": self.actual_changes,
            "code": self.code,
            "message": self.message,
        }


def _data(response: Mapping[str, Any]) -> Mapping[str, Any]:
    value = response.get("data")
    return value if isinstance(value, Mapping) else {}


def _status(response: Mapping[str, Any]) -> str:
    value = str(response.get("status") or _data(response).get("status") or "").strip().lower()
    raw_code = response.get("code")
    code = str(raw_code).strip().lower() if raw_code is not None else ""
    # Java PendingConfirmation.resolve(confirm) first claims an active
    # snapshot and returns ``applying``.  That is an acknowledged in-progress
    # transition, not proof that the planning command has completed.
    if value in {"stale", "stale_state", "conflict", "version_conflict"}:
        return "stale_state"
    if value in {"expired", "binding_expired"}:
        return "expired"
    if code not in {"", "0", "200"}:
        return "failed"
    if value in {"applying", "in_progress", "processing"}:
        return "applying"
    if value in {"cancelled", "canceled"}:
        return "cancelled"
    if value in {"applied", "completed"}:
        return "applied"
    # A successful HTTP/business response alone does not prove execution.
    return "failed"


async def execute_conversation_action(
    *,
    tenant_id: str | int = 1,
    session_id: str,
    action: ConversationAction | Mapping[str, Any],
    snapshot: ConversationTurnSnapshot | Mapping[str, Any],
    resolver: Callable[..., Awaitable[Mapping[str, Any]]] | None = None,
) -> ConversationActionResult:
    """执行已校验的确认/取消动作；其它动作只返回不可执行结果。"""
    parsed_action = action if isinstance(action, ConversationAction) else ConversationAction.model_validate(action)
    parsed_snapshot = snapshot if isinstance(snapshot, ConversationTurnSnapshot) else ConversationTurnSnapshot.model_validate(snapshot)
    active = parsed_snapshot.active_proposal or {}
    proposal_ref = parsed_action.proposal_ref
    active_ref = active.get("proposalRef") or active.get("proposalId") or active.get("pendingId")
    if parsed_action.action_type not in {"confirm_proposal", "cancel_proposal"}:
        return ConversationActionResult("not_executable", proposal_ref, code="action_not_executable")
    if not proposal_ref or str(proposal_ref) != str(active_ref or ""):
        return ConversationActionResult("stale_state", proposal_ref, code="proposal_reference_mismatch")
    active_data = active.get("data") if isinstance(active.get("data"), Mapping) else {}
    source_version = next(
        (value for value in (
            active.get("sourceVersion", active.get("source_version")),
            active_data.get("sourceVersion", active_data.get("source_version")),
            active_data.get("sourceBackendVersion", active_data.get("source_backend_version")),
        ) if value is not None),
        None,
    )
    if parsed_action.expected_source_version is not None:
        if source_version is None:
            return ConversationActionResult("stale_state", proposal_ref, code="proposal_version_missing")
        try:
            if int(parsed_action.expected_source_version) != int(source_version):
                return ConversationActionResult("stale_state", proposal_ref, code="proposal_version_mismatch")
        except (TypeError, ValueError):
            return ConversationActionResult("stale_state", proposal_ref, code="proposal_version_invalid")
    pending_id = str(active.get("pendingId") or proposal_ref)
    raw_revision = (
        active.get("revision")
        or active.get("pendingRevision")
        or active_data.get("revision")
        or active_data.get("pendingRevision")
    )
    try:
        expected_revision = int(raw_revision or 0)
    except (TypeError, ValueError):
        expected_revision = 0
    if expected_revision <= 0:
        return ConversationActionResult("stale_state", proposal_ref, code="pending_revision_missing")
    resolve_action = "confirm" if parsed_action.action_type == "confirm_proposal" else "cancel"
    resolve_kwargs: dict[str, Any] = {
        "tenant_id": tenant_id,
        "pending_id": pending_id,
        "expected_revision": expected_revision,
        "action": resolve_action,
    }
    if resolve_action == "confirm":
        # Java requires a claim token for the active -> applying transition.
        # The token is deliberately generated per request and is never model
        # supplied or persisted by the Gateway.
        resolve_kwargs["claim_token"] = uuid.uuid4().hex
    response = await (resolver or resolve_pending_confirmation)(
        session_id,
        **resolve_kwargs,
    )
    data = _data(response)
    # Pending revision is a separate CAS counter, not the conversation version.
    new_version = data.get("stateVersion")
    try:
        new_version = int(new_version) if new_version is not None else None
    except (TypeError, ValueError):
        new_version = None
    changes = data.get("actualChanges", data.get("changes", []))
    return ConversationActionResult(
        _status(response), proposal_ref, new_version,
        list(changes) if isinstance(changes, list) else [],
        str(response.get("code")) if response.get("code") is not None else None,
        str(response.get("msg") or response.get("message")) if response.get("msg") or response.get("message") else None,
    )
