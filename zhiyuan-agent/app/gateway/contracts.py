from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.admission.facts import AdmissionFactError, canonical_admission_mode, derive_risk_tier


class _ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=lambda name: "".join(
            word.capitalize() if index else word
            for index, word in enumerate(name.split("_"))
        ),
        populate_by_name=True,
        extra="forbid",
    )


class EvidenceRef(_ContractModel):
    evidence_id: str
    source_level: Literal["authoritative", "computed", "planner_experience"]
    data_version: str
    admission_mode: Literal["major", "major_group"] | None = None
    admission_unit_id: str | None = None
    group_code: str | None = None
    algorithm_version: str | None = None
    state_version: int | None = None
    scope: dict[str, Any] = Field(default_factory=dict)
    observed_at: str | None = None
    limitations: list[str] = Field(default_factory=list)

    @field_validator("admission_mode", mode="before")
    @classmethod
    def _normalize_admission_mode(cls, value: Any) -> Any:
        if value is None:
            return value
        try:
            return canonical_admission_mode(value)
        except AdmissionFactError as exc:
            raise ValueError(exc.code) from exc


class AdmissionMajorDetail(_ContractModel):
    major_id: str
    major_name: str | None = None
    major_code: str | None = None
    major_admission_rate: float

    @field_validator("major_admission_rate")
    @classmethod
    def _validate_rate(cls, value: float) -> float:
        try:
            derive_risk_tier(value)
        except AdmissionFactError as exc:
            raise ValueError(exc.code) from exc
        return value


class AdmissionFact(_ContractModel):
    admission_unit_id: str
    admission_mode: Literal["major", "major_group"]
    school_id: str
    school_name: str | None = None
    major_id: str | None = None
    major_name: str | None = None
    group_code: str | None = None
    major_items: list[AdmissionMajorDetail] = Field(default_factory=list)
    unit_admission_rate: float
    risk_tier: Literal["冲", "稳", "保"]
    data_version: str | None = None
    algorithm_version: str | None = None
    observed_at: str | None = None
    limitations: list[str] = Field(default_factory=list)

    @field_validator("admission_mode", mode="before")
    @classmethod
    def _normalize_mode(cls, value: Any) -> Any:
        try:
            return canonical_admission_mode(value)
        except AdmissionFactError as exc:
            raise ValueError(exc.code) from exc

    @field_validator("unit_admission_rate")
    @classmethod
    def _validate_unit_rate(cls, value: float) -> float:
        try:
            derive_risk_tier(value)
        except AdmissionFactError as exc:
            raise ValueError(exc.code) from exc
        return value

    @model_validator(mode="after")
    def _validate_scope_and_tier(self) -> "AdmissionFact":
        if self.admission_mode == "major" and not self.major_id:
            raise ValueError("major_required")
        if self.admission_mode == "major_group" and not self.group_code:
            raise ValueError("group_code_required")
        try:
            expected = derive_risk_tier(self.unit_admission_rate)
        except AdmissionFactError as exc:
            raise ValueError(exc.code) from exc
        if self.risk_tier != expected:
            raise ValueError("risk_tier_mismatch")
        if self.admission_mode == "major" and len(self.major_items) > 1:
            raise ValueError("major_detail_count_invalid")
        return self


class ArtifactRef(_ContractModel):
    artifact_id: str
    artifact_type: Literal["candidate", "comparison", "plan_draft", "review"]
    state_version: int


class ConversationAction(_ContractModel):
    action_type: Literal[
        "none",
        "request_clarification",
        "continue_readonly",
        "create_proposal",
        "confirm_proposal",
        "cancel_proposal",
        "refresh_proposal",
    ] = "none"
    proposal_ref: str | None = None
    expected_source_version: int | None = None
    intent: Literal["explicit", "inferred", "not_applicable"] = "not_applicable"


class ProposalScope(_ContractModel):
    scope_type: str
    name: str
    normalized_name: str | None = None
    entity_type: str | None = None
    scope_level: str | None = None
    resolution_status: str | None = None
    raw_text: str | None = None


class ProposalRequirement(_ContractModel):
    kind: str
    domain: str
    key: str
    values: list[str]
    min_count: int = Field(default=1, ge=0)
    raw_text: str | None = None


class ProposalPriorityRule(_ContractModel):
    domain: str
    key: str
    values: list[str]
    ordering_target: str = "rank_before"
    scope: str = "within_tier"
    raw_text: str | None = None


class ProposalTierRange(_ContractModel):
    min_count: int | None = Field(default=None, ge=0)
    max_count: int | None = Field(default=None, ge=0)


class ProposalTierQuota(_ContractModel):
    type: Literal["exact_counts", "count_ranges", "ratios"]
    update_mode: str | None = None
    sprint_count: int | None = Field(default=None, ge=0)
    stable_count: int | None = Field(default=None, ge=0)
    protect_count: int | None = Field(default=None, ge=0)
    sprint: ProposalTierRange | None = None
    stable: ProposalTierRange | None = None
    protect: ProposalTierRange | None = None
    sprint_weight: int | None = Field(default=None, ge=0)
    stable_weight: int | None = Field(default=None, ge=0)
    protect_weight: int | None = Field(default=None, ge=0)


class ProposalContext(_ContractModel):
    min_tuition_per_year: int | None = Field(default=None, ge=0)
    max_tuition_per_year: int | None = Field(default=None, ge=0)


class ProposalRequest(_ContractModel):
    """Model-produced semantic draft accepted by the Java proposal compiler."""

    proposal_source: Literal["user_goal"] = "user_goal"
    goal_type: Literal[
        "only_keep_scope",
        "must_include_scope",
        "exclude_scope",
        "tuition_budget_scope",
        "fill_to_count",
        "prioritize_within_tier",
    ]
    user_original_text: str = ""
    confidence: Literal["low", "medium", "high"] = "medium"
    source_version_guard: int = Field(ge=0)
    target_count: int | None = Field(default=None, gt=0)
    persist_target_count: bool = True
    tier_quota_goal: ProposalTierQuota | None = None
    requirements: list[ProposalRequirement] = Field(default_factory=list)
    priority_rules: list[ProposalPriorityRule] = Field(default_factory=list)
    target_scopes: list[ProposalScope] = Field(default_factory=list)
    negative_scopes: list[ProposalScope] = Field(default_factory=list)
    quality_guards: list[str] = Field(default_factory=list)
    tradeoff_guards: list[str] = Field(default_factory=list)
    source_review_issue_codes: list[str] = Field(default_factory=list)
    context: ProposalContext = Field(default_factory=ProposalContext)


class TurnOutput(_ContractModel):
    response_type: Literal["text", "fact", "recommendation", "review", "clarification"]
    message: str
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    admission_facts: list[AdmissionFact] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    clarification: str | None = None
    next_step: str | None = None
    execution_status: Literal["completed", "partial", "blocked", "failed"] = "completed"
    proposal_ref: str | None = None
    proposal_request: ProposalRequest | None = None
    conversation_action: ConversationAction = Field(default_factory=ConversationAction)

    @field_validator("response_type", mode="before")
    @classmethod
    def _normalize_clarification_response_type(cls, value: Any) -> Any:
        return "clarification" if value == "needs_clarification" else value

    @model_validator(mode="after")
    def _require_backend_refs(self) -> "TurnOutput":
        if self.response_type == "fact" and not self.evidence_refs:
            raise ValueError("evidenceRefs is required for fact output")
        if self.response_type in {"recommendation", "review"} and not self.artifact_refs:
            raise ValueError("artifactRefs is required for recommendation/review output")
        return self


class StatePatch(_ContractModel):
    base_version: int
    target_version: int
    changes: list[dict[str, Any]] = Field(default_factory=list)
    invalidations: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("target_version")
    @classmethod
    def _require_adjacent_version(cls, value: int, info: Any) -> int:
        base_version = info.data.get("base_version")
        if base_version is not None and value != base_version + 1:
            raise ValueError("targetVersion must equal baseVersion + 1")
        return value

    @field_validator("changes")
    @classmethod
    def _validate_change_paths(cls, changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        allowed = {
            "scoreContext",
            "confirmedConstraints",
            "preferences",
            "planningStage",
            "activeProposal",
            "missingFacts",
            "allowedCapabilities",
            "admissionMode",
        }
        for change in changes:
            path = str(change.get("path") or "")
            if path not in allowed:
                raise ValueError(f"unsupported state path: {path}")
        return changes

    @model_validator(mode="after")
    def _mode_change_requires_invalidation(self) -> "StatePatch":
        if any(change.get("path") == "admissionMode" for change in self.changes):
            has_mode_invalidation = any(
                invalidation.get("kind") == "admission_mode"
                or invalidation.get("path") == "admissionMode"
                for invalidation in self.invalidations
            )
            if not has_mode_invalidation:
                raise ValueError("admissionMode change requires admission_mode invalidation")
        return self


class ConversationTurnSnapshot(_ContractModel):
    snapshot_version: int
    session_id: str
    admission_mode: Literal["major", "major_group"] = "major"
    planning_stage: str = ""
    score_context: dict[str, Any] = Field(default_factory=dict)
    confirmed_constraints: dict[str, Any] = Field(default_factory=dict)
    preferences: dict[str, Any] = Field(default_factory=dict)
    active_proposal: dict[str, Any] | None = None
    missing_facts: list[str] = Field(default_factory=list)
    allowed_capabilities: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    admission_facts: list[AdmissionFact] = Field(default_factory=list)

    @field_validator("admission_mode", mode="before")
    @classmethod
    def _normalize_mode(cls, value: Any) -> Any:
        try:
            return canonical_admission_mode(value)
        except AdmissionFactError as exc:
            raise ValueError(exc.code) from exc
