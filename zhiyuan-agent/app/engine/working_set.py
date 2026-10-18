from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.gateway.contracts import ConversationTurnSnapshot, TurnOutput
from app.gateway.intent_draft import build_change_set
import json


def project_proposal(value: dict[str, Any] | None) -> dict[str, Any] | None:
    """Expose a stable read-only proposal projection to Codex."""
    if not isinstance(value, dict):
        return None
    proposal_id = value.get("proposalRef") or value.get("proposalId") or value.get("pendingId")
    if not proposal_id:
        return None
    return {
        "proposalRef": str(proposal_id),
        "status": str(value.get("status") or "pending_confirmation"),
        "requiresConfirmation": bool(value.get("requiresConfirmation", True)),
        "sourceVersion": value.get("sourceVersion") or value.get("source_version"),
        "summary": value.get("summary") or value.get("title") or "",
        "actionFamily": value.get("actionFamily") or value.get("action_family") or "",
        "changes": value.get("changes") or value.get("operations") or [],
        "blockingReason": value.get("blockingReason") or value.get("blocking_reason"),
    }


def _bounded(values: list[dict[str, Any]], limit: int = 24) -> list[dict[str, Any]]:
    return values[-limit:]


def _merge_entities(
    current: list[dict[str, Any]], incoming: list[dict[str, Any]], limit: int = 24
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for value in current + incoming:
        identifier = value.get("entityId")
        if identifier:
            merged.pop(str(identifier), None)
            merged[str(identifier)] = value
    return list(merged.values())[-limit:]


@dataclass(slots=True)
class ConversationWorkingSet:
    """Model-facing projection of authoritative conversation state.

    This is not a second business database and does not infer user intent. It
    only keeps bounded, validated objects that make cross-turn references
    resolvable after a new snapshot or a context compaction.
    """

    snapshot_version: int
    session_id: str
    snapshot: dict[str, Any]
    candidate_entities: list[dict[str, Any]] = field(default_factory=list)
    evidence_refs: list[dict[str, Any]] = field(default_factory=list)
    admission_facts: list[dict[str, Any]] = field(default_factory=list)
    artifact_refs: list[dict[str, Any]] = field(default_factory=list)
    confirmed_constraints: dict[str, Any] = field(default_factory=dict)
    active_proposal: dict[str, Any] | None = None
    last_response_type: str | None = None
    last_turn_id: str | None = None
    # Batch B：有界任务记录（只一页；不是第二份方案/pending）。
    # 当前是进程内工作集；跨重启持久化另接 Redis/Java 会话元数据。
    task_draft: dict[str, Any] | None = None
    candidate_scope_version: int = 0
    candidate_scope_stage: str = ""
    candidate_source_turn_id: str | None = None
    # J1：人工审查只看内容指纹，不代表 Java 规则审查已新鲜。
    last_manual_review_digest: str | None = None
    last_manual_review_version: int | None = None

    @classmethod
    def from_snapshot(cls, snapshot: ConversationTurnSnapshot) -> "ConversationWorkingSet":
        return cls(
            snapshot_version=snapshot.snapshot_version,
            session_id=snapshot.session_id,
            snapshot=snapshot.model_dump(by_alias=True),
            confirmed_constraints=dict(snapshot.confirmed_constraints),
            active_proposal=project_proposal(snapshot.active_proposal),
            evidence_refs=[item.model_dump(by_alias=True) for item in snapshot.evidence],
            admission_facts=[item.model_dump(by_alias=True) for item in snapshot.admission_facts],
            candidate_scope_version=snapshot.snapshot_version,
            candidate_scope_stage=snapshot.planning_stage,
        )

    def reconcile_snapshot(self, snapshot: ConversationTurnSnapshot) -> None:
        """Apply a new authoritative snapshot without leaking old candidates."""
        stage_changed = snapshot.planning_stage != self.candidate_scope_stage
        mode_changed = snapshot.admission_mode != self.snapshot.get("admissionMode")
        if stage_changed or mode_changed:
            self.candidate_entities = []
            self.candidate_source_turn_id = None
        # 2026-10-17 真事故（10041984）：工作集把上一回合的旧产物引用（v1）一直
        # 摆在模型面前，模型在本回合（v5）里把它和新产物一起抄进 artifactRefs，
        # 收尾被判 stale_state。**产物引用不是对话记忆**：版本推进后旧引用已作废，
        # 不该继续出现在工作集里。按版本淘汰（只保留 >= 当前快照版本的；缺版本
        # 的保持 fail-open，交给收尾校验）。
        kept_artifacts: list[dict[str, Any]] = []
        for reference in self.artifact_refs:
            version = _reference_version(reference)
            if version is None or version >= snapshot.snapshot_version:
                kept_artifacts.append(reference)
        self.artifact_refs = kept_artifacts
        self.snapshot_version = snapshot.snapshot_version
        self.snapshot = snapshot.model_dump(by_alias=True)
        self.confirmed_constraints = dict(snapshot.confirmed_constraints)
        self.candidate_scope_version = snapshot.snapshot_version
        self.candidate_scope_stage = snapshot.planning_stage

    def apply_output(self, output: TurnOutput, turn_id: str) -> None:
        self.evidence_refs = _bounded(
            self.evidence_refs
            + [item.model_dump(by_alias=True) for item in output.evidence_refs]
        )
        self.admission_facts = _bounded(
            self.admission_facts
            + [item.model_dump(by_alias=True) for item in output.admission_facts]
        )
        self.artifact_refs = _bounded(
            self.artifact_refs
            + [item.model_dump(by_alias=True) for item in output.artifact_refs]
        )
        if output.proposal_ref:
            self.active_proposal = project_proposal({"proposalRef": output.proposal_ref})
        action_type = str(getattr(output.conversation_action, "action_type", "") or "")
        if action_type == "cancel_proposal":
            # 用户放弃当前提案：任务页也一起清掉，避免下一轮“继续”又把它捞出来。
            self.task_draft = None
        elif output.intent_draft is not None:
            change_set = build_change_set(output.intent_draft)
            if change_set.status == "blocked":
                # 未实现动作不落任务页：下一轮上下文不能再把它摆给模型。
                self.task_draft = None
            else:
                self.task_draft = {
                    "intentDraft": output.intent_draft.model_dump(by_alias=True),
                    "changeSet": change_set.model_dump(by_alias=True),
                    "turnId": str(turn_id),
                }
        self.last_response_type = output.response_type
        self.last_turn_id = str(turn_id)

    def mark_manual_review(self, digest: str | None, version: int | None) -> None:
        """记录人工审查看过的方案内容；不清 Java reviewStale、不写业务状态。"""
        if not digest:
            return
        self.last_manual_review_digest = str(digest)
        self.last_manual_review_version = version if isinstance(version, int) else None

    def has_open_task(self) -> bool:
        """有未完成、非 blocked 的任务草稿时，默认建议让位给“继续任务”。"""
        if not isinstance(self.task_draft, dict):
            return False
        change_set = self.task_draft.get("changeSet")
        if not isinstance(change_set, dict):
            return True
        return str(change_set.get("status") or "") != "blocked"

    def ingest_payload(self, payload: Any, *, turn_id: str | None = None) -> None:
        """Project stable entities and tool facts from a Codex payload."""
        for item in _walk_mappings(payload):
            entities = item.get("resolvedEntities") or item.get("resolved_entities")
            if isinstance(entities, list):
                self.candidate_entities = _bounded(
                    _merge_entities(self.candidate_entities, _stable_entities(entities))
                )
                if entities:
                    self.candidate_source_turn_id = turn_id or self.candidate_source_turn_id
            data = item.get("data")
            if isinstance(data, dict):
                candidates = data.get("candidates") or data.get("items")
                if isinstance(candidates, list):
                    self.candidate_entities = _merge_entities(
                        self.candidate_entities, _stable_entities(candidates)
                    )
                    if candidates:
                        self.candidate_source_turn_id = turn_id or self.candidate_source_turn_id
            for key, target in (
                ("evidence", "evidence_refs"),
                ("evidenceRefs", "evidence_refs"),
                ("admissionFacts", "admission_facts"),
            ):
                values = item.get(key)
                if isinstance(values, list):
                    current = getattr(self, target)
                    setattr(self, target, _bounded(current + [value for value in values if isinstance(value, dict)]))

    def as_payload(self) -> dict[str, Any]:
        return {
            "kind": "conversation_working_set",
            "snapshotVersion": self.snapshot_version,
            "sessionId": self.session_id,
            "snapshot": self.snapshot,
            "candidateEntities": self.candidate_entities,
            "candidateSet": {
                "scopeVersion": self.candidate_scope_version,
                "planningStage": self.candidate_scope_stage,
                "sourceTurnId": self.candidate_source_turn_id,
                "items": self.candidate_entities,
            },
            "evidenceRefs": self.evidence_refs,
            "admissionFacts": self.admission_facts,
            "artifactRefs": self.artifact_refs,
            "confirmedConstraints": self.confirmed_constraints,
            "activeProposal": self.active_proposal,
            "taskDraft": self.task_draft,
            "lastResponseType": self.last_response_type,
            "lastTurnId": self.last_turn_id,
            "lastManualReviewDigest": self.last_manual_review_digest,
            "lastManualReviewVersion": self.last_manual_review_version,
        }

    def as_context_text(self) -> str:
        """Render an explicit Chinese context block for model consumption."""
        candidates = self.candidate_entities
        candidate_text = "、".join(
            f"{item.get('name') or item.get('entityId')}（ID={item.get('entityId')}）"
            for item in candidates
        ) or "当前工作集未保留候选对象"
        candidate_guidance = (
            "如果用户使用‘那几个学校’‘这几个’等指代，优先从候选集合恢复对象；"
            "不要说看不到候选，也不要编造候选。\n"
            if candidates
            else "当前工作集未保留候选对象，不代表线程历史中从未出现候选；"
            "优先使用可用历史中的明确对象和可靠来源解析指代，不要编造候选或对象 ID。"
            "仅当本轮请求依赖候选且仍无法解析时，澄清缺失条件，或使用已获准的只读查询；"
            "重新查询不等于恢复上一批候选，应说明这是当前条件下的新结果。\n"
        )
        query_scope = self.confirmed_constraints.get("historyQuery")
        query_scope_text = ""
        if isinstance(query_scope, dict) and query_scope:
            query_scope_text = (
                "\n已确认历史查询参数："
                + ", ".join(f"{key}={value}" for key, value in query_scope.items())
            )
        return (
            "【志愿填报业务上下文】\n"
            "以下内容是当前会话已确认的业务状态，不是用户新问题。"
            + candidate_guidance
            + f"当前候选学校：{candidate_text}\n"
            + query_scope_text
            + "\n如需查询历史分数，仍必须向用户询问缺失的省份、科类、批次、专业等参数。\n"
            "结构化状态："
            + json.dumps(self.as_payload(), ensure_ascii=False)
        )


def _reference_version(reference: Any) -> int | None:
    """产物引用的 stateVersion（别名兼容）；缺失/非法返回 None（fail-open）。"""
    if not isinstance(reference, dict):
        return None
    raw = reference.get("stateVersion", reference.get("state_version"))
    if raw in (None, "") or isinstance(raw, bool):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _walk_mappings(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        result = [value]
        for nested in value.values():
            result.extend(_walk_mappings(nested))
        return result
    if isinstance(value, list):
        result: list[dict[str, Any]] = []
        for nested in value:
            result.extend(_walk_mappings(nested))
        return result
    return []


def _stable_entities(values: list[Any]) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        identifier = value.get("entityId") or value.get("entity_id") or value.get("id")
        if not identifier:
            continue
        entity = {"entityId": str(identifier)}
        for source, target in (
            ("entityType", "entityType"),
            ("entity_type", "entityType"),
            ("name", "name"),
            ("schoolId", "schoolId"),
            ("schoolName", "schoolName"),
            ("majorId", "majorId"),
            ("majorName", "majorName"),
        ):
            if value.get(source) not in (None, ""):
                entity[target] = value[source]
        entities.append(entity)
    return entities
