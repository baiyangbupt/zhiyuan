from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from app.gateway.contracts import ConversationTurnSnapshot, TurnOutput


class OutputContractError(ValueError):
    """Raised when model output cannot be proven safe for the current turn."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def _field(value: Any, *names: str) -> Any:
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
    else:
        for name in names:
            if hasattr(value, name):
                return getattr(value, name)
    return None


def _as_output(value: TurnOutput | Mapping[str, Any]) -> TurnOutput:
    if isinstance(value, TurnOutput):
        return value
    if isinstance(value, Mapping) and value.get("type") == "object":
        value = {key: nested for key, nested in value.items() if key != "type"}
    if (
        isinstance(value, Mapping)
        and "responseType" not in value
        and value.get("type") in {"text", "fact", "recommendation", "review", "clarification"}
    ):
        value = {**value, "responseType": value["type"]}
        value.pop("type", None)
    try:
        return TurnOutput.model_validate(value)
    except ValidationError as exc:
        raise OutputContractError("schema_invalid", str(exc)) from exc


def _as_snapshot(value: ConversationTurnSnapshot | Mapping[str, Any]) -> ConversationTurnSnapshot:
    if isinstance(value, ConversationTurnSnapshot):
        return value
    try:
        return ConversationTurnSnapshot.model_validate(value)
    except ValidationError as exc:
        raise OutputContractError("snapshot_invalid", str(exc)) from exc


def validate_turn_output(
    *,
    turn_output: TurnOutput | Mapping[str, Any],
    current_snapshot: ConversationTurnSnapshot | Mapping[str, Any],
    evidence_ledger: Mapping[str, Any],
    artifacts: Mapping[str, Any],
    thread_id: str | None = None,
    tenant_id: str | None = None,
    allow_proposal: bool = False,
    strict_scope: bool = False,
) -> TurnOutput:
    """Validate every backend reference before output reaches a user.

    The model can only reference records already issued by the current
    Gateway turn.  Optional scope fields are checked when present in a ledger
    entry; absence is not treated as proof of a different scope.
    """
    if isinstance(turn_output, Mapping):
        for fact in turn_output.get("admissionFacts", turn_output.get("admission_facts", [])) or []:
            limitations = fact.get("limitations", []) if isinstance(fact, Mapping) else []
            if any("semantic_fixture_only" in str(limitation) for limitation in limitations):
                raise OutputContractError(
                    "non_authoritative_admission_fact",
                    "semantic fixture data cannot be promoted to admission facts",
                )
    output = _as_output(turn_output)
    snapshot = _as_snapshot(current_snapshot)

    for fact in output.admission_facts:
        if any("semantic_fixture_only" in limitation for limitation in fact.limitations):
            raise OutputContractError(
                "non_authoritative_admission_fact",
                "semantic fixture data cannot be promoted to admission facts",
            )

    if output.proposal_ref and not allow_proposal:
        raise OutputContractError("proposal_forbidden", "proposal output is disabled in readonly mode")
    action = output.conversation_action
    if action.action_type in {"confirm_proposal", "cancel_proposal"}:
        active = snapshot.active_proposal or {}
        active_ref = active.get("proposalRef") or active.get("proposalId") or active.get("pendingId")
        if not action.proposal_ref or str(action.proposal_ref) != str(active_ref or ""):
            raise OutputContractError("proposal_reference_mismatch", "proposal action does not match active proposal")
        source_version = active.get("sourceVersion") or active.get("source_version")
        if action.expected_source_version is not None and source_version is not None:
            if int(action.expected_source_version) != int(source_version):
                raise OutputContractError("proposal_version_mismatch", "proposal source version is stale")

    # Admission facts are only usable when the same turn carries a matching,
    # current Evidence reference for the same mode and admission unit.
    for fact in output.admission_facts:
        if fact.admission_mode != snapshot.admission_mode:
            raise OutputContractError("admission_mode_mismatch", fact.admission_unit_id)
        matching_refs = [
            reference
            for reference in output.evidence_refs
            if reference.admission_mode == fact.admission_mode
            and reference.admission_unit_id == fact.admission_unit_id
            and (fact.group_code is None or reference.group_code == fact.group_code)
        ]
        if not matching_refs:
            raise OutputContractError("admission_evidence_missing", fact.admission_unit_id)

    for reference in output.evidence_refs:
        if reference.admission_mode is not None and reference.admission_mode != snapshot.admission_mode:
            raise OutputContractError("admission_mode_mismatch", reference.evidence_id)
        evidence_id = reference.evidence_id
        entry = evidence_ledger.get(evidence_id)
        if entry is None:
            raise OutputContractError("evidence_not_found", evidence_id)
        entry_session = _scoped_field(entry, "sessionId", "session_id")
        if (strict_scope and entry_session in (None, "")) or entry_session not in (None, "", snapshot.session_id):
            raise OutputContractError("evidence_scope_violation", evidence_id)
        # 证据**不校验 thread**：thread 是运行身份，会随进程重启改变。
        # 一个易失的标识符不能承载安全语义——一次 Gateway 重启就会让所有在世会话的
        # 证据全部作废，而隔离边界本来是 (tenantId, chatSessionId)。
        # 这不是放松：这里的检查在改成"证据由 Java 真实签发"之后会真的开始拒绝，
        # 而它拒绝的理由（thread 变了）与安全无关。artifact 那侧的 thread 检查保留。
        entry_tenant = _scoped_field(entry, "tenantId", "tenant_id")
        if (strict_scope and tenant_id and entry_tenant in (None, "")) or (tenant_id and entry_tenant not in (None, "", tenant_id)):
            raise OutputContractError("evidence_scope_violation", evidence_id)
        # 招生事实的新鲜度由 dataVersion 判定，**不**由工作区版本判定。
        # 混用会把"用户改了方案"读成"录取数据过期"——两个不同的问题，处置也不同：
        # 前者重新生成方案，后者重新取数。删掉的这两行在自铸证据时代恒真，
        # 从未做过判定；换成 dataVersion 比对之后它会真的说"不"。
        # artifact 那侧的 stateVersion 检查保留：产物确实绑定工作区版本。
        entry_version = _field(entry, "dataVersion", "data_version")
        if entry_version not in (None, "") and str(entry_version) != reference.data_version:
            raise OutputContractError("evidence_mismatch", evidence_id)
        entry_mode = _field(entry, "admissionMode", "admission_mode")
        if reference.admission_mode is not None and entry_mode not in (None, "", reference.admission_mode):
            raise OutputContractError("admission_mode_mismatch", evidence_id)
        entry_unit = _field(entry, "admissionUnitId", "admission_unit_id")
        if reference.admission_unit_id is not None and entry_unit not in (None, "", reference.admission_unit_id):
            raise OutputContractError("evidence_mismatch", evidence_id)

    for reference in output.artifact_refs:
        artifact_id = reference.artifact_id
        entry = artifacts.get(artifact_id)
        if entry is None:
            raise OutputContractError("artifact_not_found", artifact_id)
        entry_state = _field(entry, "stateVersion", "state_version")
        if entry_state not in (None, ""):
            try:
                parsed_state = int(entry_state)
            except (TypeError, ValueError) as exc:
                raise OutputContractError("artifact_invalid", artifact_id) from exc
            if parsed_state != snapshot.snapshot_version:
                raise OutputContractError("stale_state", artifact_id)
        if reference.state_version != snapshot.snapshot_version:
            raise OutputContractError("stale_state", artifact_id)
        entry_session = _scoped_field(entry, "sessionId", "session_id")
        if (strict_scope and entry_session in (None, "")) or entry_session not in (None, "", snapshot.session_id):
            raise OutputContractError("artifact_scope_violation", artifact_id)
        entry_thread = _scoped_field(entry, "threadId", "thread_id")
        if (strict_scope and thread_id and entry_thread in (None, "")) or (thread_id and entry_thread not in (None, "", thread_id)):
            raise OutputContractError("artifact_scope_violation", artifact_id)

    return output


def merge_evidence(snapshot_records: list, turn_records: list) -> dict:
    """把快照证据与本回合证据并成一个账本。

    **两个来源都要。** 只从本回合事件建账本的话，快照里那些权威证据虽然被
    摆到了模型面前（fillEvidence），模型一引用却立刻 `evidence_not_found`——
    断链 4 就是这个形状：证据看得见、够不着。

    冲突规则是**不与**：同 ID 的记录必须"稳定身份"一致（租户/会话/来源系统/
    参数摘要/数据版本），否则报错而不是"最后一个覆盖"。`observedAt` 不在稳定
    身份里——观测时间不同不等于证据内容不同，把它算进去会让正常的重复观测变成冲突。
    """
    stable_fields = ("tenantId", "sessionId", "sourceSystem", "paramsDigest", "dataVersion")
    merged: dict = {}
    for record in [*(snapshot_records or []), *(turn_records or [])]:
        if not isinstance(record, dict):
            continue
        key = record.get("evidenceId") or record.get("evidence_id")
        if not key:
            continue
        stable = tuple(record.get(name) for name in stable_fields)
        previous = merged.get(key)
        if previous is not None:
            previous_stable = tuple(previous.get(name) for name in stable_fields)
            if previous_stable != stable:
                raise ValueError("evidence_identity_conflict")
        merged[key] = record
    return merged


def _scoped_field(value: Any, *names: str) -> Any:
    direct = _field(value, *names)
    if direct not in (None, ""):
        return direct
    scope = _field(value, "scope")
    return _field(scope, *names)
