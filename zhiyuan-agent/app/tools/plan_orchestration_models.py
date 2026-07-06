from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class PlanContextInputs(BaseModel):
    batch: str = "01"
    phase: str = ""
    target_count: int = 0
    working_count: int = 0
    draft_count: int = 0
    ordered_count: int = 0
    risk_count: int = 0
    warn_count: int = 0
    positive_majors: list[str] = Field(default_factory=list)
    negative_majors: list[str] = Field(default_factory=list)
    positive_schools: list[str] = Field(default_factory=list)
    negative_schools: list[str] = Field(default_factory=list)
    positive_regions: list[str] = Field(default_factory=list)
    negative_regions: list[str] = Field(default_factory=list)
    career_types: list[str] = Field(default_factory=list)
    relation_lines: list[str] = Field(default_factory=list)
    review_issues: list[dict[str, Any]] = Field(default_factory=list)
    review_issue_summary_lines: list[str] = Field(default_factory=list)
    summary: str = ""

    @model_validator(mode="after")
    def _sync_working_count_alias(self) -> "PlanContextInputs":
        if self.working_count <= 0 and self.draft_count > 0:
            self.working_count = self.draft_count
        elif self.draft_count <= 0 and self.working_count > 0:
            self.draft_count = self.working_count
        return self


class PlanReviewIssueTarget(BaseModel):
    code: str
    scope_mode: Literal["full_issue", "narrowed_issue", "explicit_items"] = "full_issue"
    scope_fingerprint: str = ""
    label: str = ""
    scope_kind: str = ""
    default_action_family: str = ""
    narrowed_refs: list[str] = Field(default_factory=list)
    narrowed_filters: dict[str, Any] = Field(default_factory=dict)


class PlanAtomicAction(BaseModel):
    action_type: str
    volunteer_ids: list[str] = Field(default_factory=list)
    unit_ids: list[str] = Field(default_factory=list)
    source_major_names: list[str] = Field(default_factory=list)
    source_position: int | None = None
    position_scope: Literal["single", "after"] = "single"
    target_position: int | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    review_issue_target: PlanReviewIssueTarget | None = None

    @field_validator("review_issue_target", mode="before")
    @classmethod
    def _normalize_review_issue_target(cls, value: Any) -> Any:
        if isinstance(value, str):
            normalized = str(value or "").strip()
            return {"code": normalized} if normalized else None
        return value

    @model_validator(mode="before")
    @classmethod
    def _normalize_position_scope_alias(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        if "position_scope" not in value and "positionScope" in value:
            normalized = dict(value)
            normalized["position_scope"] = normalized.get("positionScope")
            return normalized
        return value


class PlanEntityResolution(BaseModel):
    """Entity evidence for a user-facing plan goal.

    This is not an executable scope. It records how the system understood a
    school/major/region/risk mention so preview cards can disclose ambiguity
    before any mutation is applied.
    """

    raw_text: str
    entity_type: Literal["major", "school", "region", "career", "tag", "risk", "program_type"]
    canonical_name: str = ""
    canonical_level: str = ""
    matched_plan_items: list[dict[str, Any]] = Field(default_factory=list)
    matched_candidate_items: list[dict[str, Any]] = Field(default_factory=list)
    ambiguity: Literal[
        "none",
        "specific_vs_category",
        "catalog_vs_admission_plan",
        "multiple_match",
        "unknown",
    ] = "none"
    user_visible_note: str = ""


class PlanDecisionReference(BaseModel):
    """Decision signal used when comparing plan alternatives.

    These references are explanatory evidence for preview and dry-run decisions.
    They do not grant execution permission and must not bypass confirmation.
    """

    source: Literal[
        "explicit_user_goal",
        "confirmed_intent",
        "system_recommendation",
        "current_plan",
        "candidate_pool",
        "review_rule",
        "dry_run",
    ]
    dimension: str
    label: str = ""
    value: Any = None
    weight_hint: Literal["hard", "high", "medium", "low", "context"] = "context"
    applies_to: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)


PlanGoalTypeValue = Literal[
    "query_state",
    "only_keep_scope",
    "must_include_scope",
    "exclude_scope",
    "tuition_budget_scope",
    "prefer_scope",
    "rebalance_structure",
    "reduce_risk",
    "mixed_adjustment",
    "clarify",
]

ConstraintIntentTypeValue = Literal["default", "only_keep", "must_have"]

_CONSTRAINT_TO_PLAN_GOAL: dict[str, PlanGoalTypeValue] = {
    "only_keep": "only_keep_scope",
    "must_have": "must_include_scope",
}

_SCOPE_REQUIRED_GOAL_TYPES = {
    "only_keep_scope",
    "must_include_scope",
    "exclude_scope",
    "prefer_scope",
}


def resolve_plan_goal_type(
    plan_goal_type: str | None,
    constraint_intent_type: str | None = None,
) -> PlanGoalTypeValue | None:
    """Normalize the high-level plan goal type from structured inputs only."""
    normalized_goal = str(plan_goal_type or "").strip()
    if normalized_goal:
        return normalized_goal  # type: ignore[return-value]
    normalized_constraint = str(constraint_intent_type or "").strip()
    return _CONSTRAINT_TO_PLAN_GOAL.get(normalized_constraint)


def plan_goal_requires_scope(goal_type: str | None) -> bool:
    return str(goal_type or "").strip() in _SCOPE_REQUIRED_GOAL_TYPES


class PlanGoal(BaseModel):
    """Structured user goal above action_family.

    PlanGoal describes what the user wants to accomplish. Direct tools use it
    to build user-visible proposal and pending metadata.
    """

    goal_type: PlanGoalTypeValue
    user_original_text: str = ""
    target_scopes: list[dict[str, Any]] = Field(default_factory=list)
    negative_scopes: list[dict[str, Any]] = Field(default_factory=list)
    structure_targets: list[dict[str, Any]] = Field(default_factory=list)
    quality_guards: list[dict[str, Any]] = Field(default_factory=list)
    max_tuition_per_year: int | None = None
    entity_resolutions: list[PlanEntityResolution] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"
    needs_clarification: bool = False
    clarification_questions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _clarification_required_for_clarify_goal(self) -> "PlanGoal":
        if self.goal_type == "clarify":
            self.needs_clarification = True
        return self

    @property
    def has_entity_ambiguity(self) -> bool:
        return any(item.ambiguity != "none" for item in self.entity_resolutions)

    @property
    def user_visible_entity_notes(self) -> list[str]:
        notes: list[str] = []
        for item in self.entity_resolutions:
            note = str(item.user_visible_note or "").strip()
            if note and note not in notes:
                notes.append(note)
        return notes


def build_plan_goal_intent_updates(plan_goal: PlanGoal | None) -> list[dict[str, Any]]:
    """Return pending intent update metadata derived from a confirmed PlanGoal.

    This only builds preview/confirmation metadata. It does not write intent
    state and it deliberately returns nothing when the goal still needs
    clarification.
    """
    if plan_goal is None or plan_goal.needs_clarification:
        return []
    if plan_goal.goal_type == "only_keep_scope":
        return [
            {
                "intentMode": "constraint",
                "constraintIntentType": "only_keep",
                "targetScopes": plan_goal.target_scopes,
            }
        ]
    if plan_goal.goal_type == "must_include_scope":
        return [
            {
                "intentMode": "constraint",
                "constraintIntentType": "must_have",
                "targetScopes": plan_goal.target_scopes,
            }
        ]
    if plan_goal.goal_type == "exclude_scope":
        return [
            {
                "intentMode": "constraint",
                "constraintIntentType": "default",
                "negativeScopes": plan_goal.negative_scopes,
            }
        ]
    if plan_goal.goal_type == "prefer_scope":
        return [
            {
                "intentMode": "preference",
                "targetScopes": plan_goal.target_scopes,
            }
        ]
    return []


CompositeFeasibility = Literal["ready", "preview_only", "blocked", "needs_clarification"]


class CompositePlanProposal(BaseModel):
    """Preview container for a multi-step plan goal.

    A composite proposal groups the user's high-level goal, pending intent
    updates, plan actions and user-visible caveats into one confirmation unit.
    It is not an apply API and does not bypass pending confirmation gates.
    """

    proposal_id: str = ""
    source_version: int = 0
    goal: PlanGoal | None = None
    entity_resolutions: list[PlanEntityResolution] = Field(default_factory=list)
    intent_updates: list[dict[str, Any]] = Field(default_factory=list)
    plan_actions: list[PlanAtomicAction] = Field(default_factory=list)
    decision_references: list[PlanDecisionReference] = Field(default_factory=list)
    dry_run_result: dict[str, Any] = Field(default_factory=dict)
    feasibility: CompositeFeasibility = "preview_only"
    impact_summary: list[str] = Field(default_factory=list)
    tradeoffs: list[str] = Field(default_factory=list)
    requires_confirmation: bool = True
    post_apply_validation_plan: list[str] = Field(default_factory=list)

    @field_validator("feasibility", mode="before")
    @classmethod
    def _normalize_feasibility(cls, value: Any) -> Any:
        text = str(value or "").strip().lower()
        aliases = {
            "": "preview_only",
            "preview": "preview_only",
            "needs_clarify": "needs_clarification",
            "clarify": "needs_clarification",
            "cannot_satisfy": "blocked",
        }
        return aliases.get(text, value)

    @model_validator(mode="after")
    def _sync_goal_metadata(self) -> "CompositePlanProposal":
        if self.goal is not None:
            if not self.entity_resolutions:
                self.entity_resolutions = list(self.goal.entity_resolutions)
            if self.goal.needs_clarification:
                self.feasibility = "needs_clarification"
                self.requires_confirmation = False
        if self.feasibility in {"blocked", "needs_clarification"}:
            self.requires_confirmation = False
        return self

    @property
    def has_plan_mutation(self) -> bool:
        return bool(self.plan_actions)
