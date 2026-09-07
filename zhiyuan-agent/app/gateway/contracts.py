from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
    limitations: list[str] = Field(default_factory=list)


class ArtifactRef(_ContractModel):
    artifact_id: str
    artifact_type: Literal["candidate", "comparison", "plan_draft", "review"]
    state_version: int


class TurnOutput(_ContractModel):
    response_type: Literal["text", "fact", "recommendation", "review", "clarification"]
    message: str
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    clarification: str | None = None
    proposal_ref: str | None = None

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
        }
        for change in changes:
            path = str(change.get("path") or "")
            if path not in allowed:
                raise ValueError(f"unsupported state path: {path}")
        return changes


class ConversationTurnSnapshot(_ContractModel):
    snapshot_version: int
    session_id: str
    planning_stage: str = ""
    score_context: dict[str, Any] = Field(default_factory=dict)
    confirmed_constraints: dict[str, Any] = Field(default_factory=dict)
    preferences: dict[str, Any] = Field(default_factory=dict)
    active_proposal: dict[str, Any] | None = None
    missing_facts: list[str] = Field(default_factory=list)
    allowed_capabilities: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
