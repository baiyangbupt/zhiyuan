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
        # Java 签发的证据把会话放在 `scope.chatSessionId`（生产者的键名），
        # 而这里以前只认 `sessionId`/`session_id` → 取不到 → strict_scope 判它
        # session 不符 → **任何真实签发的证据都被拒收**。表现是
        # `evidence_scope_violation`，而证据本身完全合规。键名要在**消费侧**
        # 对齐生产者，不是反过来要求生产者改名。
        entry_session = _scoped_field(
            entry, "sessionId", "session_id", "chatSessionId", "chat_session_id"
        )
        # **两边都按字符串比**：Java 给的是数字（`"chatSessionId": 900021`），
        # 快照里是字符串。只转一边的话，`900021 != "900021"` 会把一条完全合规的
        # 证据判成越权——fail closed，而且看不出哪里不对。
        session_matches = entry_session not in (None, "") and str(entry_session) == str(
            snapshot.session_id
        )
        if (strict_scope and entry_session in (None, "")) or not session_matches:
            raise OutputContractError("evidence_scope_violation", evidence_id)
        # 证据**不校验 thread**：thread 是运行身份，会随进程重启改变。
        # 一个易失的标识符不能承载安全语义——一次 Gateway 重启就会让所有在世会话的
        # 证据全部作废，而隔离边界本来是 (tenantId, chatSessionId)。
        # 这不是放松：这里的检查在改成"证据由 Java 真实签发"之后会真的开始拒绝，
        # 而它拒绝的理由（thread 变了）与安全无关。artifact 那侧的 thread 检查保留。
        # 同上：Java 给的是数字（`"tenantId": 1`），我们手上是字符串（"1"）。
        # 用字符串比，避免"值一样、类型不同"被判成越权。
        entry_tenant = _scoped_field(entry, "tenantId", "tenant_id")
        tenant_matches = entry_tenant in (None, "") or str(entry_tenant) == str(tenant_id)
        if (strict_scope and tenant_id and entry_tenant in (None, "")) or not tenant_matches:
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
        # 与证据同一处置：值一样、类型不同不能算越权。
        artifact_session_matches = entry_session not in (None, "") and str(entry_session) == str(
            snapshot.session_id
        )
        if (strict_scope and entry_session in (None, "")) or not artifact_session_matches:
            raise OutputContractError("artifact_scope_violation", artifact_id)
        entry_thread = _scoped_field(entry, "threadId", "thread_id")
        if (strict_scope and thread_id and entry_thread in (None, "")) or (thread_id and entry_thread not in (None, "", thread_id)):
            raise OutputContractError("artifact_scope_violation", artifact_id)

    return output


# 根身份三件套：租户 / 会话 / 来源系统。它们决定这条证据**属于谁、属于哪条链**，
# 任何一条对不上都意味着"这根本是另一条证据顶着同一个 ID"，必须 fail closed。
# 而 `paramsDigest` / `dataVersion` 是**内容标识**——模型转述证据时恰恰抄不到
# `paramsDigest`（见 `merge_evidence` 的 docstring），拿内容标识判身份冲突，
# 等于把"转述不完整"升级成"整轮对话失败"（2026-10-07 线上事故的形态）。
_ROOT_IDENTITY_FIELDS = ("tenantId", "sessionId", "sourceSystem")


def _root_identity_conflict(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    """同 ID 的两份记录，**根身份**是否真的冲突。

    判据是「**双方都非空且不同**」：一侧缺这个字段只说明这一侧没有这个信息
    （模型转述抄丢了、或该来源本来就不带），**无信息 ≠ 冲突**。把"缺"当冲突，
    就是 2026-10-07 那次事故：补录成绩确认之后的下一轮，模型引用了批次线证据
    （转述里没有 `sourceSystem`），整轮以 `evidence_identity_conflict` 失败
    （`recoverable=False`，用户只看到"当前对话引擎暂时不可用"），
    而两边指的其实是**同一条**证据。
    """
    for name in _ROOT_IDENTITY_FIELDS:
        left_value = left.get(name)
        right_value = right.get(name)
        if left_value in (None, "") or right_value in (None, ""):
            continue
        if str(left_value) != str(right_value):
            return True
    return False


def merge_evidence(snapshot_records: list, turn_records: list) -> dict:
    """把快照证据与本回合证据并成一个账本。

    **两个来源都要。** 只从本回合事件建账本的话，快照里那些权威证据虽然被
    摆到了模型面前（fillEvidence），模型一引用却立刻 `evidence_not_found`——
    断链 4 就是这个形状：证据看得见、够不着。

    **同 ID 的合并语义：信快照，不信转述**（2026-10-07 修）。

    为什么以前会抛、现在不抛 ✓✗：以前同 ID 只要"稳定身份五元组"不一致就报错，
    但本回合那一份**不是**另一条证据——它是模型在自己终态正文里**转述**的证据，
    被 `_collect_records` 从 AgentMessage 里挖出来当成"本回合证据"（实测转述形状：
    只抄 `evidenceId`/`sourceLevel`/`dataVersion` 与一个查询参数 `scope`，
    `sourceSystem`/`paramsDigest` 全丢）。"转述不完整"被判成"身份冲突"，
    后果是**整轮硬失败**：用户补录成绩确认之后，只要模型引用一条快照里的证据，
    下一轮就变成"当前对话引擎暂时不可用"（日志：`codex turn failed …
    error=evidence_identity_conflict recoverable=False`）。那不是冲突，是残缺。

    所以现在的规则是：
    · 快照记录**先入账本、且不被本回合记录覆盖**——快照是 Java 台账的逐字投影，
      权威；让残缺的转述覆盖原件，等于把账本降级成模型自述（P1b-3："证据以
      snapshot 为准"）。校验与核验随后拿**快照那份**去对，模型引用的内容对不上
      快照（如 dataVersion 被改写）依旧会 `evidence_mismatch` fail closed——
      放宽的只是"**残缺**"，不是"**说错**"。
    · 只有**根身份**（租户/会话/来源系统）双方都非空且不同才报
      `evidence_identity_conflict`：那不是转述，是另一条证据顶着同一个 ID。
    · `paramsDigest`/`dataVersion` 的出入不再算冲突：同一 ID 在同一条台账里
      不会换内容（Java 每次签发都是新 ID），有出入只可能是转述残缺 → 取快照那份。
    · `observedAt` 从来不在身份里——观测时间不同不等于证据内容不同，把它算进去
      会让正常的重复观测变成冲突。
    """
    merged: dict = {}
    for record in snapshot_records or []:
        if not isinstance(record, dict):
            continue
        key = record.get("evidenceId") or record.get("evidence_id")
        if not key:
            continue
        previous = merged.get(key)
        if previous is not None and _root_identity_conflict(previous, record):
            raise ValueError("evidence_identity_conflict")
        merged[key] = record
    for record in turn_records or []:
        if not isinstance(record, dict):
            continue
        key = record.get("evidenceId") or record.get("evidence_id")
        if not key:
            continue
        previous = merged.get(key)
        if previous is None:
            # 本回合**新签发**的证据：账本里原本没有，照收（不能只认快照——
            # 那样本回合工具签发的证据模型一引用就是 `evidence_not_found`）。
            merged[key] = record
            continue
        if _root_identity_conflict(previous, record):
            # 真冲突：转述最多是**残缺**，不会变成另一条链上的证据。到这一步
            # 只能整轮拒收（fail closed），不给"最后一个覆盖"留下可乘之机。
            raise ValueError("evidence_identity_conflict")
        # 同 ID、根身份不冲突 = 对快照记录的转述：快照留着，转述不覆盖、不报错。
        # （"为什么不再抛"的完整理由见上面 docstring。）
    return merged


def _scoped_field(value: Any, *names: str) -> Any:
    direct = _field(value, *names)
    if direct not in (None, ""):
        return direct
    scope = _field(value, "scope")
    return _field(scope, *names)
