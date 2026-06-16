from __future__ import annotations

from typing import Any, Literal

from app.domain.entity_resolution import EntityResolutionCandidate, EntityResolutionResult
from app.domain.major_entity_resolver import resolve_major_entity
from app.domain.region_entity_resolver import resolve_region_entity
from app.domain.school_entity_resolver import resolve_school_entity
from app.tools.plan_orchestration_models import PlanEntityResolution, PlanGoal


def scope_entity_type(scope: dict[str, Any]) -> str:
    raw_type = str(
        scope.get("entity_type")
        or scope.get("entityType")
        or scope.get("type")
        or scope.get("kind")
        or ""
    ).strip()
    aliases = {
        "province": "region",
        "city": "region",
        "area": "region",
        "major_keyword": "major",
        "source_major": "major",
        "source_major_name": "major",
        "school_keyword": "school",
        "province_keyword": "region",
        "major_tag": "tag",
        "school_tag": "tag",
        "review_issue": "risk",
        "project_type": "program_type",
        "admission_type": "program_type",
        "enrollment_type": "program_type",
        "program": "program_type",
        "project": "program_type",
    }
    return aliases.get(raw_type, raw_type)


def scope_value_list(scope: dict[str, Any]) -> list[str]:
    raw_values = (
        scope.get("values")
        if "values" in scope
        else scope.get("value")
        if "value" in scope
        else scope.get("names")
        if "names" in scope
        else scope.get("name")
        if "name" in scope
        else scope.get("keyword")
    )
    if isinstance(raw_values, list):
        return [str(item or "").strip() for item in raw_values if str(item or "").strip()]
    value = str(raw_values or "").strip()
    return [value] if value else []


def _candidate_payload(candidate: EntityResolutionCandidate) -> dict[str, Any]:
    payload = {
        "canonical_name": candidate.canonical_name,
        "level": candidate.level or "",
        "source": candidate.source,
        "confidence": candidate.confidence,
    }
    if candidate.metadata:
        payload["metadata"] = dict(candidate.metadata)
    return payload


def _resolution_note(
    *,
    raw_text: str,
    entity_type: str,
    ambiguity: str,
    candidates: list[dict[str, Any]],
) -> str:
    if ambiguity == "none":
        return ""
    label = {
        "major": "专业",
        "school": "院校",
        "region": "地域",
        "tag": "标签",
        "risk": "审查问题",
        "program_type": "项目类型",
    }.get(entity_type, "范围")
    if ambiguity == "unknown":
        return f"我还没能把“{raw_text}”对应到明确的{label}，需要先补充更准确的名称。"
    candidate_names = [
        str(item.get("canonical_name") or "").strip()
        for item in candidates[:5]
        if str(item.get("canonical_name") or "").strip()
    ]
    suffix = f"可能对应：{'、'.join(candidate_names)}。" if candidate_names else ""
    return f"“{raw_text}”有多个可能的{label}范围，{suffix}需要先确认按哪个范围处理。"


def _entity_resolution_from_result(
    *,
    raw_text: str,
    entity_type: Literal["major", "school", "region"],
    result: EntityResolutionResult,
) -> PlanEntityResolution:
    candidates = [_candidate_payload(candidate) for candidate in result.candidates]
    if result.best is not None:
        ambiguity: Literal["none", "multiple_match", "unknown"] = "none"
        canonical_name = result.best.canonical_name
        canonical_level = result.best.level or ""
    elif result.candidates:
        ambiguity = "multiple_match"
        canonical_name = ""
        canonical_level = ""
    else:
        ambiguity = "unknown"
        canonical_name = ""
        canonical_level = ""
    return PlanEntityResolution(
        raw_text=raw_text,
        entity_type=entity_type,
        canonical_name=canonical_name,
        canonical_level=canonical_level,
        matched_candidate_items=candidates,
        ambiguity=ambiguity,
        user_visible_note=_resolution_note(
            raw_text=raw_text,
            entity_type=entity_type,
            ambiguity=ambiguity,
            candidates=candidates,
        ),
    )


def _passthrough_entity_resolution(
    *,
    raw_text: str,
    entity_type: Literal["tag", "risk", "program_type"],
) -> PlanEntityResolution:
    return PlanEntityResolution(
        raw_text=raw_text,
        entity_type=entity_type,
        canonical_name=raw_text,
        ambiguity="none",
    )


def build_goal_entity_resolutions(plan_goal: PlanGoal, batch: str | None) -> list[PlanEntityResolution]:
    resolutions: list[PlanEntityResolution] = []
    seen: set[tuple[str, str]] = set()
    for scope in [
        *plan_goal.target_scopes,
        *plan_goal.negative_scopes,
        *plan_goal.structure_targets,
        *plan_goal.quality_guards,
    ]:
        if not isinstance(scope, dict):
            continue
        entity_type = scope_entity_type(scope)
        for raw_text in scope_value_list(scope):
            key = (entity_type, raw_text)
            if key in seen:
                continue
            seen.add(key)
            if entity_type == "major":
                resolutions.append(
                    _entity_resolution_from_result(
                        raw_text=raw_text,
                        entity_type="major",
                        result=resolve_major_entity(raw_text, batch),
                    )
                )
            elif entity_type == "school":
                resolutions.append(
                    _entity_resolution_from_result(
                        raw_text=raw_text,
                        entity_type="school",
                        result=resolve_school_entity(raw_text, batch),
                    )
                )
            elif entity_type == "region":
                resolutions.append(
                    _entity_resolution_from_result(
                        raw_text=raw_text,
                        entity_type="region",
                        result=resolve_region_entity(raw_text),
                    )
                )
            elif entity_type in {"tag", "risk", "program_type"}:
                resolutions.append(
                    _passthrough_entity_resolution(
                        raw_text=raw_text,
                        entity_type=entity_type,  # type: ignore[arg-type]
                    )
                )
    return resolutions


def _canonical_resolution_value(resolution: PlanEntityResolution) -> str:
    if resolution.ambiguity != "none":
        return str(resolution.raw_text or "").strip()
    canonical_name = str(resolution.canonical_name or "").strip()
    return canonical_name or str(resolution.raw_text or "").strip()


def _canonicalize_goal_scope_values(
    scopes: list[dict[str, Any]],
    resolutions: list[PlanEntityResolution],
) -> list[dict[str, Any]]:
    resolution_by_key = {
        (resolution.entity_type, str(resolution.raw_text or "").strip()): resolution
        for resolution in resolutions
    }
    canonicalized: list[dict[str, Any]] = []
    for scope in scopes:
        if not isinstance(scope, dict):
            canonicalized.append(scope)
            continue
        entity_type = scope_entity_type(scope)
        values = scope_value_list(scope)
        if not values:
            canonicalized.append(dict(scope))
            continue
        new_values: list[str] = []
        for value in values:
            resolution = resolution_by_key.get((entity_type, value))
            canonical_value = _canonical_resolution_value(resolution) if resolution else value
            if canonical_value and canonical_value not in new_values:
                new_values.append(canonical_value)
        new_scope = dict(scope)
        if "values" in new_scope or not any(key in new_scope for key in ("value", "names", "name", "keyword")):
            new_scope["values"] = new_values
        elif "value" in new_scope and len(new_values) == 1:
            new_scope["value"] = new_values[0]
        elif "names" in new_scope:
            new_scope["names"] = new_values
        elif "name" in new_scope and len(new_values) == 1:
            new_scope["name"] = new_values[0]
        elif "keyword" in new_scope and len(new_values) == 1:
            new_scope["keyword"] = new_values[0]
        else:
            new_scope["values"] = new_values
        canonicalized.append(new_scope)
    return canonicalized


def attach_goal_entity_resolutions(plan_goal: PlanGoal, batch: str | None) -> PlanGoal:
    entity_resolutions = build_goal_entity_resolutions(plan_goal, batch)
    if not entity_resolutions:
        return plan_goal
    plan_goal.entity_resolutions = entity_resolutions
    plan_goal.target_scopes = _canonicalize_goal_scope_values(plan_goal.target_scopes, entity_resolutions)
    plan_goal.negative_scopes = _canonicalize_goal_scope_values(plan_goal.negative_scopes, entity_resolutions)
    plan_goal.structure_targets = _canonicalize_goal_scope_values(plan_goal.structure_targets, entity_resolutions)
    plan_goal.quality_guards = _canonicalize_goal_scope_values(plan_goal.quality_guards, entity_resolutions)
    blocking_notes = plan_goal.user_visible_entity_notes
    if blocking_notes:
        plan_goal.needs_clarification = True
        for note in blocking_notes:
            if note not in plan_goal.clarification_questions:
                plan_goal.clarification_questions.append(note)
    return plan_goal
