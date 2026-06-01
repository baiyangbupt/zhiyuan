from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


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
    phase: str = ""
    target_count: int = 0
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
    "apply_compensation",
}


def normalize_plan_action_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    normalized = dict(payload or {})
    action_family = str(normalized.get("action_family") or "").strip()
    current_stage = str(normalized.get("current_stage") or normalized.get("stage") or "").strip()
    has_user_confirmed = "user_confirmed" in normalized
    user_confirmed = bool(normalized.get("user_confirmed"))
    if current_stage in {"analyze", "preview", "apply", "review"}:
        stage = current_stage
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
    filters = raw_filters if isinstance(raw_filters, dict) else {}
    reason = str(normalized.get("reason") or normalized.get("user_goal") or "").strip()
    target_position = normalized.get("target_position")
    source_position = normalized.get("source_position")
    review_issue_target = normalized.get("review_issue_target")
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
            "target_position": target_position,
            "filters": filters,
            "reason": reason,
            "review_issue_target": review_issue_target,
        }
    ]
    return normalized


class PlanActionPlan(BaseModel):
    stage: Literal["analyze", "preview", "apply", "review"]
    action_family: Literal[
        "query_state",
        "query_draft",
        "query_ordered",
        "query_candidates",
        "generate_plan",
        "analyze_adjustment",
        "preview_compensation",
        "add_units",
        "remove_units",
        "move_unit",
        "move_ordered_unit",
        "pin_unit",
        "unpin_unit",
        "replace_units",
        "remove_ordered_unit",
        "sort_ordered_plan",
        "regenerate_order",
        "apply_compensation",
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
    atomic_actions: list[PlanAtomicAction] = Field(default_factory=list)
    preview_summary: str = ""

    @field_validator("intent_relation", mode="before")
    @classmethod
    def _normalize_intent_relation(cls, value: Any) -> Any:
        text = str(value or "").strip().lower()
        if not text:
            return "unknown"
        return _INTENT_RELATION_ALIASES.get(text, value)


class PlanExecutionResult(BaseModel):
    applied: bool
    action_family: str
    stage: str
    result_kind: Literal[
        "status_overview",
        "draft_snapshot",
        "ordered_snapshot",
        "candidate_snapshot",
        "generation_result",
        "adjustment_analysis",
        "compensation_preview",
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
