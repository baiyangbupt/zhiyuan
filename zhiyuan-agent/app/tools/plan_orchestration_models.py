from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


_INTENT_RELATION_ALIASES = {
    "support": "support",
    "supported": "support",
    "match": "support",
    "matches": "support",
    "matching": "support",
    "aligned": "support",
    "conflict": "conflict",
    "conflicted": "conflict",
    "mismatch": "conflict",
    "mismatched": "conflict",
    "mixed": "mixed",
    "partial": "mixed",
    "partially_supported": "mixed",
    "unknown": "unknown",
    "unclear": "unknown",
}


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

    PlanGoal describes what the user wants to accomplish. PlanActionPlan and
    PlanAtomicAction describe how the system can preview or execute it.
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
    It is not an apply API and does not bypass PlanActionPlan stage/confirmation
    gates.
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


_TOP_LEVEL_ATOMIC_ACTION_FAMILIES = {
    "add_units",
    "remove_units",
    "move_unit",
    "move_ordered_unit",
    "replace_units",
    "remove_ordered_unit",
    "sort_ordered_plan",
}

_MUTATING_ACTION_FAMILIES = {
    "generate_plan",
    "add_units",
    "remove_units",
    "move_unit",
    "move_ordered_unit",
    "replace_units",
    "remove_ordered_unit",
    "sort_ordered_plan",
    "regenerate_order",
}


def normalize_plan_action_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    normalized = dict(payload or {})
    action_family = str(normalized.get("action_family") or "").strip()
    current_stage = str(normalized.get("current_stage") or "").strip()
    explicit_stage = str(normalized.get("stage") or "").strip()
    effective_stage = explicit_stage if explicit_stage in {"analyze", "preview", "apply", "review"} else current_stage
    has_user_confirmed = "user_confirmed" in normalized
    user_confirmed = bool(normalized.get("user_confirmed"))
    if effective_stage in {"analyze", "preview", "apply", "review"}:
        stage = effective_stage
        if (
            stage == "apply"
            and action_family in _MUTATING_ACTION_FAMILIES
            and has_user_confirmed
            and not user_confirmed
        ):
            stage = "preview"
        normalized["stage"] = stage
    elif action_family in _MUTATING_ACTION_FAMILIES and has_user_confirmed:
        normalized["stage"] = "apply" if user_confirmed else "preview"

    if normalized.get("atomic_actions"):
        return normalized

    if action_family not in _TOP_LEVEL_ATOMIC_ACTION_FAMILIES:
        return normalized

    raw_ids = normalized.get("volunteer_ids")
    if isinstance(raw_ids, list):
        volunteer_ids = [str(item or "").strip() for item in raw_ids if str(item or "").strip()]
    else:
        single_id = str(raw_ids or "").strip()
        volunteer_ids = [single_id] if single_id else []
    raw_unit_ids = normalized.get("unit_ids")
    if isinstance(raw_unit_ids, list):
        unit_ids = [str(item or "").strip() for item in raw_unit_ids if str(item or "").strip()]
    else:
        single_unit_id = str(raw_unit_ids or "").strip()
        unit_ids = [single_unit_id] if single_unit_id else []

    raw_source_major_names = normalized.get("source_major_names") or normalized.get("sourceMajorNames")
    if isinstance(raw_source_major_names, list):
        source_major_names = [
            str(item or "").strip()
            for item in raw_source_major_names
            if str(item or "").strip()
        ]
    else:
        single_source_major_name = str(raw_source_major_names or "").strip()
        source_major_names = [single_source_major_name] if single_source_major_name else []

    raw_filters = normalized.get("filters")
    filters = dict(raw_filters) if isinstance(raw_filters, dict) else {}
    if action_family == "sort_ordered_plan":
        for key in ("sort_field", "sortField", "field"):
            raw_sort_field = str(normalized.get(key) or "").strip()
            if raw_sort_field:
                filters.setdefault("sort_field", raw_sort_field)
                break
    reason = str(normalized.get("reason") or normalized.get("user_goal") or "").strip()
    target_position = normalized.get("target_position")
    source_position = normalized.get("source_position")
    position_scope = str(
        normalized.get("position_scope")
        or normalized.get("positionScope")
        or "single"
    ).strip()
    if position_scope not in {"single", "after"}:
        position_scope = "single"
    review_issue_target = normalized.get("review_issue_target")
    if not isinstance(review_issue_target, dict):
        review_issue_code = str(normalized.get("review_issue_code") or "").strip()
        if review_issue_code:
            review_issue_target = {
                "code": review_issue_code,
                "scope_mode": str(normalized.get("review_issue_scope_mode") or "full_issue").strip() or "full_issue",
                "scope_fingerprint": str(normalized.get("review_issue_scope_fingerprint") or "").strip(),
                "label": str(normalized.get("review_issue_label") or "").strip(),
                "scope_kind": str(normalized.get("review_issue_scope_kind") or "").strip(),
                "default_action_family": str(normalized.get("review_issue_default_action_family") or "").strip(),
            }
    has_atomic_shape = (
        bool(volunteer_ids)
        or bool(unit_ids)
        or bool(source_major_names)
        or bool(filters)
        or source_position is not None
        or target_position is not None
        or isinstance(review_issue_target, dict)
    )
    if not has_atomic_shape:
        return normalized

    normalized["atomic_actions"] = [
        {
            "action_type": action_family,
            "volunteer_ids": volunteer_ids,
            "unit_ids": unit_ids,
            "source_major_names": source_major_names,
            "source_position": source_position,
            "position_scope": position_scope,
            "target_position": target_position,
            "filters": filters,
            "reason": reason,
            "review_issue_target": review_issue_target,
        }
    ]
    return normalized


class PlanActionPlan(BaseModel):
    """Current plan action envelope.

    Top-level fields describe the action currently being previewed or executed.
    High-level compound goals live in ``composite_proposal`` so the plan goal,
    pending intent updates and decision evidence have a single structured home.
    Review/repair proposal generation is owned by the backend proposal/apply
    API instead of being mirrored in this Agent DTO.
    """

    stage: Literal["analyze", "preview", "apply", "review"]
    action_family: Literal[
        "query_state",
        "query_ordered",
        "query_candidates",
        "generate_plan",
        "analyze_adjustment",
        "preview_fix_proposal",
        "add_units",
        "remove_units",
        "move_unit",
        "move_ordered_unit",
        "replace_units",
        "remove_ordered_unit",
        "sort_ordered_plan",
        "regenerate_order",
        "review_plan",
    ]
    user_goal: str = ""
    requires_confirmation: bool = True
    should_rerun_review: bool = False
    should_refresh_workspace: bool = False
    context_summary: str = ""
    planning_version: int = 0
    intent_relation: Literal["support", "conflict", "mixed", "unknown"] = "unknown"
    missing_inputs: list[str] = Field(default_factory=list)
    rationale: list[str] = Field(default_factory=list)
    target_strategies: list[str] = Field(default_factory=list)
    target_issue_codes: list[str] = Field(default_factory=list)
    reply_focus: list[str] = Field(default_factory=list)
    atomic_actions: list[PlanAtomicAction] = Field(default_factory=list)
    composite_proposal: CompositePlanProposal | None = None
    preview_summary: str = ""
    facts: dict[str, Any] = Field(default_factory=dict)

    @field_validator("intent_relation", mode="before")
    @classmethod
    def _normalize_intent_relation(cls, value: Any) -> Any:
        text = str(value or "").strip().lower()
        if not text:
            return "unknown"
        return _INTENT_RELATION_ALIASES.get(text, value)

    @field_validator("target_strategies", mode="before")
    @classmethod
    def _normalize_target_strategies(cls, value: Any) -> list[str]:
        if value is None:
            return []
        raw_values = value if isinstance(value, list) else [value]
        result: list[str] = []
        for item in raw_values:
            text = str(item or "").strip()
            if text and text not in result:
                result.append(text)
        return result

    @field_validator("target_issue_codes", mode="before")
    @classmethod
    def _normalize_target_issue_codes(cls, value: Any) -> list[str]:
        if value is None:
            return []
        raw_values = value if isinstance(value, list) else [value]
        result: list[str] = []
        for item in raw_values:
            text = str(item or "").strip()
            if text and text not in result:
                result.append(text)
        return result

    @field_validator("reply_focus", mode="before")
    @classmethod
    def _normalize_reply_focus(cls, value: Any) -> list[str]:
        if value is None:
            return []
        raw_values = value if isinstance(value, list) else [value]
        result: list[str] = []
        for item in raw_values:
            text = str(item or "").strip()
            if text and text not in result:
                result.append(text)
        return result

    @model_validator(mode="before")
    @classmethod
    def _sync_target_strategies_alias(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if (
            ("target_strategies" not in data and "targetStrategies" in data)
            or ("target_issue_codes" not in data and "targetIssueCodes" in data)
            or ("reply_focus" not in data and "replyFocus" in data)
        ):
            data = dict(data)
            if "target_strategies" not in data and "targetStrategies" in data:
                data["target_strategies"] = data.get("targetStrategies")
            if "target_issue_codes" not in data and "targetIssueCodes" in data:
                data["target_issue_codes"] = data.get("targetIssueCodes")
            if "reply_focus" not in data and "replyFocus" in data:
                data["reply_focus"] = data.get("replyFocus")
        return data


class PlanExecutionResult(BaseModel):
    applied: bool
    action_family: str
    stage: str
    result_kind: Literal[
        "status_overview",
        "ordered_snapshot",
        "candidate_snapshot",
        "generation_result",
        "adjustment_analysis",
        "fix_proposal_preview",
        "mutation_result",
        "review_result",
        "preview_only",
        "no_change",
        "error",
    ] = "status_overview"
    executed_actions: list[dict[str, Any]] = Field(default_factory=list)
    affected_volunteer_ids: list[str] = Field(default_factory=list)
    workspace_refresh_targets: list[str] = Field(default_factory=list)
    review_rerun: bool = False
    intent_effect: Literal["strengthened", "weakened", "conflicted", "unchanged"] = "unchanged"
    context_summary: str = ""
    review_summary: str = ""
    state_summary: str = ""
    summary: str = ""
    reply_focus: list[str] = Field(default_factory=list)
    reply_strategy: Literal[
        "continue_model",
        "direct_reply",
        "direct_blocking",
        "preview_wait_confirm",
    ] | None = None
    next_step_hints: list[str] = Field(default_factory=list)
    facts: dict[str, Any] = Field(default_factory=dict)
