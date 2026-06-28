from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
import time
from typing import Any

from pydantic_ai import RunContext

from app.agent.context import RequestContext, resolve_pending_confirmation
from app.domain.major_entity_resolver import (
    canonicalize_major_intent_payload,
    major_alias_variants_for_name,
    major_name_sets_for_batch,
    major_parent_mappings_for_batch,
    resolve_major_entity,
)
from app.domain.region_entity_resolver import normalize_region_names
from app.domain.school_entity_resolver import resolve_school_entity, school_alias_variants
from app.domain.school_major_ref_resolver import resolve_school_major_ref
from app.sync.state_sync import PlanningStateSync
from app.tools.plan_orchestration_models import (
    PlanActionPlan,
    PlanAtomicAction,
    PlanExecutionResult,
    PlanReviewIssueTarget,
    normalize_plan_action_payload,
)
from app.tools.review_issue_registry import build_review_issue_scopes, get_review_issue_rule
from app.tools.planning_workflow_tool import (
    _build_plan_intent_relation_lines,
    _build_plan_status_overview_facts,
    _build_review_result_facts,
    _extract_plan_intent_state,
    _item_matches_career_labels,
    _item_matches_keyword,
    merge_planning_state_with_user_profile,
    move_planning_ordered_item,
    query_planning_candidate_pool,
    query_planning_ordered_plan,
    query_planning_plan_overview,
    remove_planning_ordered_items,
    run_planning_review,
    select_planning_ordered_items,
)
from app.util.planning_state_compat import get_working_plan_items, get_working_plan_state, get_working_plan_summary
from app.util.internal_client import (
    generate_planning_candidate_pool as _generate_planning_candidate_pool_request,
    generate_planning_initial_plan as _generate_planning_initial_plan_request,
    generate_planning_ordered_plan as _generate_planning_ordered_plan_request,
    get_planning_ordered_plan as _get_planning_ordered_plan_request,
    get_planning_state as _get_planning_state_request,
    get_user_profile as _get_user_profile_request,
    get_working_plan as _get_working_plan_request,
    query_planning_candidate_pool as _query_planning_candidate_pool_request,
    run_planning_review as _run_planning_review_request,
    select_working_plan_items as _select_working_plan_items_request,
    sort_planning_ordered_plan as _sort_planning_ordered_plan_request,
    move_planning_ordered_plan_unit as _move_planning_ordered_plan_unit_request,
    remove_planning_ordered_plan_units as _remove_planning_ordered_plan_units_request,
)
from app.util.structured_log import log_event

logger = logging.getLogger(__name__)
_DEFAULT_TENANT_ID = 1
_VOLUNTEER_ID_LIKE_RE = re.compile(r"^[A-Za-z0-9_.:\-]+$")
_TUITION_PER_YEAR_RE = re.compile(r"(?:学费[:：]?\s*)?(\d{4,6})\s*(?:元|/年)")
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
_READONLY_HANDLER_ACTION_FAMILIES = {
    "query_state",
    "query_ordered",
    "query_candidates",
    "analyze_adjustment",
    "preview_fix_proposal",
    "review_plan",
}
_RECENT_PLAN_EXECUTION_TTL_SECONDS = 180.0
_RECENT_PLAN_EXECUTION_RESULTS: dict[tuple[str, str], dict[str, Any]] = {}
_RECENT_PLAN_ACTION_PLANS: dict[tuple[str, str], dict[str, Any]] = {}
_PLAN_MAJOR_SCOPE_FILTER_KEYS = (
    "major_keyword",
    "major_tags",
    "major_level3",
    "major_level2",
    "major_level1",
    "negative_level3",
    "negative_level2",
    "negative_level1",
)
_PLAN_MAJOR_LEVEL_FILTER_KEYS = {
    "negative_level1": "major_level1",
    "negative_level2": "major_level2",
    "negative_level3": "major_level3",
}
_PROGRAM_TYPE_FILTER_KEYS = (
    "program_type",
    "program_types",
    "admission_type",
    "admission_types",
    "project_type",
    "project_types",
    "enrollment_type",
    "enrollment_types",
)
_MIN_TUITION_FILTER_KEYS = (
    "min_tuition_per_year",
    "minTuitionPerYear",
    "tuition_min_per_year",
    "tuitionMinPerYear",
)
_MAX_TUITION_FILTER_KEYS = (
    "max_tuition_per_year",
    "maxTuitionPerYear",
    "tuition_cap",
    "tuitionCap",
    "max_tuition",
    "maxTuition",
)
_PREFERENCE_FIT_FILTER_KEYS = (
    "preference_fit",
    "preferenceFit",
    "intent_relation",
    "intentRelation",
)


def _review_rerun_succeeded(review_summary: str | None) -> bool:
    """Return true unless the review helper returned its failure boundary text."""
    text = str(review_summary or "").strip()
    if not text:
        return False
    failure_markers = (
        "执行方案审查失败",
        "审查失败",
        "无法完成方案审查",
        "暂时不能审查",
    )
    return not any(marker in text for marker in failure_markers)


def _append_missing_json_closers(raw: str) -> str | None:
    """Conservatively repair a JSON object truncated after complete tokens."""
    text = str(raw or "").strip()
    if not text.startswith("{"):
        return None
    stack: list[str] = []
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            stack.append("}")
        elif char == "[":
            stack.append("]")
        elif char in {"}", "]"}:
            if not stack or stack[-1] != char:
                return None
            stack.pop()
    if in_string or not stack:
        return None
    text = re.sub(r",\s*$", "", text)
    return text + "".join(reversed(stack))


def _load_plan_payload(plan_payload: str) -> tuple[dict[str, Any], bool]:
    payload_text = str(plan_payload or "").strip()
    try:
        loaded = json.loads(payload_text)
        return normalize_plan_action_payload(loaded), False
    except Exception:
        if not (
            '"action_family"' in payload_text
            and '"stage"' in payload_text
            and '"atomic_actions"' in payload_text
        ):
            raise
    repaired_text = _append_missing_json_closers(payload_text)
    if repaired_text is None:
        raise ValueError("plan payload is not safely repairable")
    loaded = json.loads(repaired_text)
    return normalize_plan_action_payload(loaded), True


def _has_sort_field_payload(payload: dict[str, Any]) -> bool:
    for key in ("sort_field", "sortField", "field"):
        if str(payload.get(key) or "").strip():
            return True
    for action in payload.get("atomic_actions") or []:
        if not isinstance(action, dict):
            continue
        filters = action.get("filters")
        if not isinstance(filters, dict):
            continue
        for key in ("sort_field", "sortField", "field"):
            if str(filters.get(key) or "").strip():
                return True
    return False


def _merge_recent_plan_action_plan_if_compatible(
    ctx: RunContext[RequestContext],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Recover fields dropped while copying plan_next_action output.

    This does not infer from natural language. It only reuses the complete
    plan_next_action output cached for the same session and user turn when the
    current execute payload names the same action family but is less complete.
    """
    action_family = str(payload.get("action_family") or "").strip()
    if not action_family:
        return payload
    recent_plan = _recent_plan_action_plan(ctx)
    if not recent_plan:
        return payload
    if str(recent_plan.get("action_family") or "").strip() != action_family:
        return payload
    merged = copy.deepcopy(payload)
    if not merged.get("atomic_actions") and recent_plan.get("atomic_actions"):
        merged["atomic_actions"] = copy.deepcopy(recent_plan.get("atomic_actions"))
    if action_family == "sort_ordered_plan" and not _has_sort_field_payload(merged):
        if _has_sort_field_payload(recent_plan):
            merged["atomic_actions"] = copy.deepcopy(recent_plan.get("atomic_actions") or [])
    for key in (
        "requires_confirmation",
        "should_rerun_review",
        "should_refresh_workspace",
        "context_summary",
        "planning_version",
        "intent_relation",
        "missing_inputs",
        "rationale",
        "composite_proposal",
        "preview_summary",
    ):
        value = merged.get(key)
        if value in (None, "", [], {}):
            recent_value = recent_plan.get(key)
            if recent_value not in (None, "", [], {}):
                merged[key] = copy.deepcopy(recent_value)
    return normalize_plan_action_payload(merged)


def _merge_resolved_apply_payload_if_available(payload: dict[str, Any]) -> dict[str, Any]:
    """Use preview-resolved execution targets on the confirmation turn.

    Preview may resolve user-facing refs or structured scopes into stable
    volunteer/unit ids. Apply must execute those resolved ids instead of
    reinterpreting the original natural language or broad filter.
    """
    if str(payload.get("stage") or "").strip() != "apply":
        return payload
    facts = payload.get("facts")
    if not isinstance(facts, dict):
        return payload
    resolved = facts.get("resolved_apply_payload")
    if not isinstance(resolved, dict) or not resolved:
        return payload

    merged = copy.deepcopy(payload)
    for key, value in resolved.items():
        if key == "facts":
            continue
        if key == "action_family":
            resolved_family = str(value or "").strip()
            if resolved_family:
                merged["action_family"] = resolved_family
            continue
        if key == "stage":
            continue
        if value not in (None, "", [], {}):
            merged[key] = copy.deepcopy(value)
    merged["stage"] = "apply"
    return normalize_plan_action_payload(merged)


def _planning_version_from_context(ctx: RunContext[RequestContext]) -> int:
    planning_summary = getattr(ctx.deps, "planning_summary", None)
    try:
        return int(getattr(planning_summary, "version", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _facts_with_planning_version(
    facts: dict[str, Any] | None,
    ctx: RunContext[RequestContext],
) -> dict[str, Any]:
    result = dict(facts or {})
    planning_version = _planning_version_from_context(ctx)
    if planning_version > 0:
        result.setdefault("planning_version", planning_version)
    return result


def _positive_int(value: Any) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _generation_missing_inputs(ctx: RunContext[RequestContext]) -> list[str]:
    missing: list[str] = []
    score = getattr(ctx.deps, "score_detail", None)
    if score is None:
        return ["generation_profile"]
    if _positive_int(getattr(score, "total_score", 0)) <= 0:
        missing.append("generation_profile")
    if not str(getattr(score, "province", "") or "").strip():
        if "generation_profile" not in missing:
            missing.append("generation_profile")
    if not list(getattr(score, "subject_list", []) or []):
        if "generation_profile" not in missing:
            missing.append("generation_profile")
    planning_summary = getattr(ctx.deps, "planning_summary", None)
    if planning_summary is None:
        if "generation_candidate_pool" not in missing:
            missing.append("generation_candidate_pool")
        return missing
    candidate_status = str(getattr(planning_summary, "candidate_status", "") or "").strip()
    if candidate_status in {"empty", "failed"}:
        if "generation_candidate_pool" not in missing:
            missing.append("generation_candidate_pool")
        return missing
    if not (
        _positive_int(getattr(planning_summary, "candidate_available_total", 0)) > 0
        or _positive_int(getattr(planning_summary, "working_total", 0)) > 0
        or _positive_int(getattr(planning_summary, "ordered_total", 0)) > 0
    ):
        if "generation_candidate_pool" not in missing:
            missing.append("generation_candidate_pool")
    return missing


def _has_generation_prerequisite_context(ctx: RunContext[RequestContext]) -> bool:
    return not _generation_missing_inputs(ctx)


def _latest_user_text(ctx: RunContext[RequestContext]) -> str:
    for message in reversed(ctx.deps.chat_history or []):
        if isinstance(message, dict) and message.get("role") == "user":
            return str(message.get("content") or "").strip()
    return ""


def _contains_natural_ref_text(refs: list[str]) -> bool:
    return any(any(ord(char) > 127 for char in str(ref or "")) for ref in refs)


def _normalize_prompt_key(text: str | None) -> str:
    return re.sub(r"\s+", "", str(text or "").strip())


def _prune_recent_plan_execution_results(now: float | None = None) -> None:
    current = now if now is not None else time.monotonic()
    expired_keys = [
        key
        for key, payload in _RECENT_PLAN_EXECUTION_RESULTS.items()
        if current - float(payload.get("stored_at") or 0.0) > _RECENT_PLAN_EXECUTION_TTL_SECONDS
    ]
    for key in expired_keys:
        _RECENT_PLAN_EXECUTION_RESULTS.pop(key, None)
    expired_plan_keys = [
        key
        for key, payload in _RECENT_PLAN_ACTION_PLANS.items()
        if current - float(payload.get("stored_at") or 0.0) > _RECENT_PLAN_EXECUTION_TTL_SECONDS
    ]
    for key in expired_plan_keys:
        _RECENT_PLAN_ACTION_PLANS.pop(key, None)


def clear_recent_plan_execution_result(session_id: str, user_prompt: str | None = None) -> None:
    _prune_recent_plan_execution_results()
    if user_prompt is None:
        session_key = str(session_id or "").strip()
        for key in list(_RECENT_PLAN_EXECUTION_RESULTS.keys()):
            if key[0] == session_key:
                _RECENT_PLAN_EXECUTION_RESULTS.pop(key, None)
        for key in list(_RECENT_PLAN_ACTION_PLANS.keys()):
            if key[0] == session_key:
                _RECENT_PLAN_ACTION_PLANS.pop(key, None)
        return
    key = (str(session_id or "").strip(), _normalize_prompt_key(user_prompt))
    _RECENT_PLAN_EXECUTION_RESULTS.pop(key, None)
    _RECENT_PLAN_ACTION_PLANS.pop(key, None)


def consume_recent_plan_execution_result(session_id: str, user_prompt: str | None) -> dict[str, Any] | None:
    _prune_recent_plan_execution_results()
    key = (str(session_id or "").strip(), _normalize_prompt_key(user_prompt))
    payload = _RECENT_PLAN_EXECUTION_RESULTS.pop(key, None)
    if not payload:
        return None
    result = payload.get("result")
    return copy.deepcopy(result) if isinstance(result, dict) else None


def _remember_recent_plan_execution_result(ctx: RunContext[RequestContext], result: dict[str, Any]) -> None:
    session_id = str(ctx.deps.sessionid or "").strip()
    prompt_key = _normalize_prompt_key(_latest_user_text(ctx))
    if not session_id or not prompt_key:
        return
    _prune_recent_plan_execution_results()
    _RECENT_PLAN_EXECUTION_RESULTS[(session_id, prompt_key)] = {
        "stored_at": time.monotonic(),
        "result": copy.deepcopy(result),
    }


def remember_recent_plan_action_plan(ctx: RunContext[RequestContext], plan_payload: dict[str, Any]) -> None:
    """Cache the full plan_next_action output for the current user turn.

    The model sometimes calls execute_plan_action with a hand-written minimal
    payload after plan_next_action already produced the complete structured
    plan.  This cache lets execute_plan_action recover missing fields from the
    immediately preceding structured plan without inferring from user text.
    """
    session_id = str(ctx.deps.sessionid or "").strip()
    prompt_key = _normalize_prompt_key(_latest_user_text(ctx))
    if not session_id or not prompt_key:
        return
    _prune_recent_plan_execution_results()
    _RECENT_PLAN_ACTION_PLANS[(session_id, prompt_key)] = {
        "stored_at": time.monotonic(),
        "plan": copy.deepcopy(plan_payload),
    }


def _recent_plan_action_plan(ctx: RunContext[RequestContext]) -> dict[str, Any] | None:
    _prune_recent_plan_execution_results()
    session_id = str(ctx.deps.sessionid or "").strip()
    prompt_key = _normalize_prompt_key(_latest_user_text(ctx))
    payload = _RECENT_PLAN_ACTION_PLANS.get((session_id, prompt_key))
    if not payload:
        return None
    plan = payload.get("plan")
    return copy.deepcopy(plan) if isinstance(plan, dict) else None


def _first_atomic_action(plan_model: PlanActionPlan) -> Any | None:
    return plan_model.atomic_actions[0] if plan_model.atomic_actions else None


def _atomic_position_scope(atomic: Any | None) -> str:
    if atomic is None:
        return "single"
    scope = str(getattr(atomic, "position_scope", None) or getattr(atomic, "positionScope", None) or "single").strip()
    return scope if scope in {"single", "after"} else "single"


def _extract_unit_ids(plan_model: PlanActionPlan) -> list[str]:
    unit_ids: list[str] = []
    for action in plan_model.atomic_actions or []:
        raw_unit_ids = getattr(action, "unit_ids", None)
        if isinstance(raw_unit_ids, list):
            for value in raw_unit_ids:
                text = str(value or "").strip()
                if text and text not in unit_ids:
                    unit_ids.append(text)
        filters = getattr(action, "filters", None)
        if isinstance(filters, dict):
            for key in ("unit_id", "unitId"):
                text = str(filters.get(key) or "").strip()
                if text and text not in unit_ids:
                    unit_ids.append(text)
            raw_filter_unit_ids = filters.get("unit_ids") or filters.get("unitIds")
            if isinstance(raw_filter_unit_ids, list):
                for value in raw_filter_unit_ids:
                    text = str(value or "").strip()
                    if text and text not in unit_ids:
                        unit_ids.append(text)
    return unit_ids


def _extract_unit_source_positions(plan_model: PlanActionPlan) -> list[int]:
    positions: list[int] = []
    for action in plan_model.atomic_actions or []:
        raw_value = getattr(action, "source_position", None)
        if raw_value is None:
            continue
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            continue
        if value > 0 and value not in positions:
            positions.append(value)
    return positions


def _extract_unit_position_limit(plan_model: PlanActionPlan) -> int:
    for action in plan_model.atomic_actions or []:
        raw_value = getattr(action, "filters", None)
        if not isinstance(raw_value, dict):
            continue
        limit_value = raw_value.get("limit")
        if limit_value in (None, ""):
            continue
        try:
            limit = int(limit_value)
        except (TypeError, ValueError):
            continue
        if limit > 0:
            return limit
    return 0


def _ordered_visible_unit_id_for_item(item: dict[str, Any] | None) -> str:
    item = item or {}
    return str(
        item.get("unitId")
        or item.get("id")
        or item.get("volunteerId")
        or item.get("schoolName")
        or ""
    ).strip()


def _ordered_visible_units(ordered_state: dict[str, Any], volunteer_model: str = "") -> list[dict[str, Any]]:
    raw_units = ordered_state.get("units") or []
    units = [unit for unit in raw_units if isinstance(unit, dict)] if isinstance(raw_units, list) else []
    if units:
        return units
    raw_items = ordered_state.get("items") or []
    items = [item for item in raw_items if isinstance(item, dict)] if isinstance(raw_items, list) else []
    if volunteer_model == "majorGroup":
        grouped: dict[str, dict[str, Any]] = {}
        for item in items:
            unit_id = _ordered_unit_id_for_item(item)
            if not unit_id:
                continue
            unit = grouped.setdefault(
                unit_id,
                {
                    "unitId": unit_id,
                    "schoolName": item.get("schoolName") or item.get("school_name") or "",
                    "name": item.get("schoolName") or item.get("school_name") or unit_id,
                    "position": item.get("position"),
                    "majorItems": [],
                    "unitKind": "专业组",
                },
            )
            unit["majorItems"].append(item)
        return list(grouped.values())
    visible_units: list[dict[str, Any]] = []
    for item in items:
        unit_id = _ordered_visible_unit_id_for_item(item)
        if not unit_id:
            continue
        visible_units.append(
            {
                "unitId": unit_id,
                "schoolName": item.get("schoolName") or item.get("school_name") or "",
                "name": item.get("schoolName") or item.get("school_name") or "",
                "position": item.get("position"),
                "majorItems": [item],
                "unitKind": "志愿",
            }
        )
    return visible_units


async def _resolve_ordered_unit_ids(ctx: RunContext[RequestContext], plan_model: PlanActionPlan) -> list[str]:
    explicit = _extract_unit_ids(plan_model)
    if explicit:
        return explicit
    positions = _extract_unit_source_positions(plan_model)
    if not positions:
        return []
    try:
        state_resp = await _get_planning_state_request(ctx.deps.sessionid)
        state = (state_resp or {}).get("data") or {}
        ordered_state = state.get("orderedPlanState") or {}
        units = _ordered_visible_units(ordered_state, str(state.get("volunteerModel") or state.get("volunteer_model") or ""))
        action = _first_atomic_action(plan_model)
        if _atomic_position_scope(action) == "after":
            matched_units, _ = _resolve_ordered_visible_units_from_position_scope(plan_model, units)
            resolved_range = [_unit_id_from_visible_unit(unit) for unit in matched_units]
            return [unit_id for unit_id in resolved_range if unit_id]
        resolved: list[str] = []
        for position in positions:
            index = position - 1
            if index < 0 or index >= len(units):
                continue
            unit = units[index] or {}
            unit_id = str(unit.get("unitId") or unit.get("id") or "").strip()
            if not unit_id:
                major_items = unit.get("majorItems") or unit.get("items") or []
                if major_items:
                    unit_id = _ordered_unit_id_for_item(major_items[0] or {})
            if unit_id and unit_id not in resolved:
                resolved.append(unit_id)
        return resolved
    except Exception:
        logger.exception("_resolve_ordered_unit_ids failed: session_id=%s", ctx.deps.sessionid)
        return []


def _unit_display_name(unit: dict[str, Any] | None) -> str:
    unit = unit or {}
    school_name = str(unit.get("schoolName") or "").strip()
    if _unit_kind_label(unit) == "志愿":
        majors = _unit_major_items(unit)
        major_name = str((majors[0] or {}).get("majorName") or "").strip() if majors else ""
        if school_name and major_name:
            return f"{school_name} · {major_name}"
        if major_name:
            return major_name
    return str(school_name or unit.get("name") or unit.get("unitId") or "该项").strip()


def _unit_major_count(unit: dict[str, Any] | None) -> int:
    unit = unit or {}
    majors = _unit_major_items(unit)
    return len(majors) if isinstance(majors, list) else 0


def _unit_major_items(unit: dict[str, Any] | None) -> list[dict[str, Any]]:
    unit = unit or {}
    majors = unit.get("majorItems") or unit.get("items") or []
    return [item for item in majors if isinstance(item, dict)] if isinstance(majors, list) else []


def _unit_volunteer_id(unit: dict[str, Any] | None) -> str:
    majors = _unit_major_items(unit)
    if not majors:
        return ""
    return str((majors[0] or {}).get("volunteerId") or "").strip()


def _unit_kind_label(unit: dict[str, Any] | None) -> str:
    unit = unit or {}
    explicit_kind = str(unit.get("unitKind") or unit.get("unit_kind") or "").strip()
    if explicit_kind in {"志愿", "专业组"}:
        return explicit_kind
    majors = _unit_major_items(unit)
    if len(majors) > 1:
        return "专业组"
    unit_id = str(unit.get("unitId") or unit.get("id") or "").strip()
    if unit_id:
        for major in majors:
            volunteer_id = str(major.get("volunteerId") or "").strip()
            if volunteer_id.startswith(f"{unit_id}_"):
                return "专业组"
    return "志愿"


def _unit_tier_label(unit: dict[str, Any] | None) -> str:
    unit = unit or {}
    tier = str(unit.get("tier") or unit.get("bucket") or "").strip()
    if tier:
        return tier
    majors = _unit_major_items(unit)
    for major in majors:
        for key in ("tier", "bucket"):
            tier = str((major or {}).get(key) or "").strip()
            if tier:
                return tier
    return ""


def _unit_position_semantics(unit: dict[str, Any] | None) -> str:
    return "unit_position_not_item_position" if _unit_kind_label(unit) == "专业组" else "ordered_item_position"


def _unit_position_explanation(unit: dict[str, Any] | None) -> str:
    if _unit_kind_label(unit) == "专业组":
        return (
            "位置说明：这里的“第几个”按专业组顺序计算，不是按单条志愿位置计算；"
            "执行后该组内专业会保持连续。"
        )
    return "位置说明：这里的“第几个”按当前方案展示顺序计算，确认后会影响方案顺序和导出顺序。"


def _unit_id_from_visible_unit(unit: dict[str, Any] | None) -> str:
    unit = unit or {}
    unit_id = str(unit.get("unitId") or unit.get("id") or "").strip()
    if unit_id:
        return unit_id
    major_items = unit.get("majorItems") or unit.get("items") or []
    if major_items:
        return _ordered_unit_id_for_item(major_items[0] or {})
    return ""


def _resolve_ordered_visible_units_from_position_scope(
    plan_model: PlanActionPlan,
    units: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    action = _first_atomic_action(plan_model)
    position_scope = _atomic_position_scope(action)
    position_refs = _extract_unit_source_positions(plan_model)
    source_position = position_refs[0] if position_refs else None
    facts: dict[str, Any] = {
        "position_scope": position_scope,
        "source_unit_position": source_position,
    }
    if position_scope != "after":
        if source_position is not None and 0 < source_position <= len(units):
            return [units[source_position - 1] or {}], facts
        return [], facts
    if source_position is None:
        return [], facts
    if source_position < 0:
        return [], facts
    if source_position >= len(units):
        facts["position_resolution"] = "range_empty"
        return [], facts

    filters = getattr(action, "filters", None) if action is not None else None
    filters = filters if isinstance(filters, dict) else {}
    tier = str(filters.get("tier") or "").strip()
    limit = _extract_unit_position_limit(plan_model)
    matched: list[dict[str, Any]] = []
    for unit in units[source_position:]:
        if tier and _unit_tier_label(unit) != tier:
            continue
        matched.append(unit)
        if limit > 0 and len(matched) >= limit:
            break
    facts.update(
        {
            "position_resolution": "range_resolved" if matched else "range_empty",
            "position_scope_tier": tier,
            "position_scope_limit": limit,
            "position_scope_matched_count": len(matched),
        }
    )
    return matched, facts


def _resolved_payload_for_ordered_visible_units(
    plan_model: PlanActionPlan,
    units: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str], list[str]]:
    if not units:
        return {}, [], []
    if all(_unit_kind_label(unit) == "志愿" for unit in units):
        volunteer_ids = [_unit_volunteer_id(unit) for unit in units]
        volunteer_ids = [value for value in volunteer_ids if value]
        if not volunteer_ids:
            return {}, [], []
        return (
            _build_resolved_apply_payload(
                plan_model,
                volunteer_ids=volunteer_ids,
                action_family="remove_units",
            ),
            volunteer_ids,
            [],
        )
    unit_ids = [_unit_id_from_visible_unit(unit) for unit in units]
    unit_ids = [value for value in unit_ids if value]
    if not unit_ids:
        return {}, [], []
    return _build_resolved_apply_payload(plan_model, unit_ids=unit_ids), [], unit_ids


async def _build_move_ordered_unit_preview_summary(
    ctx: RunContext[RequestContext],
    plan_model: PlanActionPlan,
) -> tuple[str | None, dict[str, Any]]:
    action = _first_atomic_action(plan_model)
    target_position = getattr(action, "target_position", None)
    filters = getattr(action, "filters", None) if action is not None else None
    filters = filters if isinstance(filters, dict) else {}
    has_tier_local_selector = bool(
        filters.get("tier")
        or filters.get("target_tier")
        or filters.get("targetTier")
    )
    if target_position is None and not has_tier_local_selector:
        return None, {}
    try:
        state_resp = await _get_planning_state_request(ctx.deps.sessionid)
        state = (state_resp or {}).get("data") or {}
        ordered_state = state.get("orderedPlanState") or {}
        units = _ordered_visible_units(ordered_state, str(state.get("volunteerModel") or state.get("volunteer_model") or ""))
        selector_units = [
            {**unit, "_visible_position": index}
            for index, unit in enumerate(units, start=1)
            if isinstance(unit, dict)
        ]
        position_refs = _extract_unit_source_positions(plan_model)
        source_position = position_refs[0] if position_refs else None
        if not units:
            requested_move = (
                f"第{source_position}个移到第{int(target_position)}位"
                if source_position and target_position is not None
                else "按位置移动"
            )
            return (
                f"当前方案里还没有可移动的志愿，所以不能预览“{requested_move}”这类排序调整。"
                "需要先生成或加入志愿后，才能按位置移动。",
                {"position_semantics": "ordered_unit_position", "position_resolution": "empty_plan"},
            )
        unit_ids = _extract_unit_ids(plan_model)
        source_unit: dict[str, Any] | None = None
        source_unit_id = ""
        selector_facts: dict[str, Any] = {}

        if unit_ids:
            source_unit_id = unit_ids[0]
            for idx, unit in enumerate(units, start=1):
                candidate_id = str((unit or {}).get("unitId") or (unit or {}).get("id") or "").strip()
                if candidate_id == source_unit_id:
                    source_unit = unit
                    source_position = source_position or idx
                    break
        elif source_position is not None and 0 < source_position <= len(units):
            source_unit = units[source_position - 1] or {}
            source_unit_id = str(source_unit.get("unitId") or source_unit.get("id") or "").strip()
        elif has_tier_local_selector:
            selected_unit, selector_target_position, selector_facts, selector_message = _resolve_tier_local_move_selector(
                selector_units,
                filters,
            )
            if selected_unit is not None and selector_target_position is not None:
                source_unit = selected_unit
                source_position = _ordered_item_position_value(selected_unit)
                target_position = selector_target_position
                source_unit_id = _unit_id_from_visible_unit(selected_unit)
            elif selector_message:
                selector_facts["position_resolution"] = "tier_selector_no_match"
                return selector_message, selector_facts

        if source_unit is None:
            if source_position is not None:
                return (
                    f"当前方案只有 {len(units)} 个可排序项，找不到第 {source_position} 个，"
                    "所以这次还不能生成移动预览。你可以先补齐方案，或重新指定当前方案里已有的位置。",
                    {
                        "position_semantics": "ordered_unit_position",
                        "position_resolution": "source_position_out_of_range",
                        "ordered_unit_count": len(units),
                        "source_unit_position": source_position,
                    },
                )
            return (
                "会移动当前方案排序区里的指定项，目标是移动到新的方案位置。"
                "这里的“第几个”按当前方案展示顺序计算，确认后会影响方案顺序和导出顺序。",
                {"position_semantics": "ordered_unit_position"},
            )
        if target_position is None:
            return (
                "已定位到当前方案里的排序项，但还缺少明确的目标位置，所以这次不能生成移动预览。",
                {"position_semantics": "ordered_unit_position", "position_resolution": "missing_target_position"},
            )

        label = _unit_kind_label(source_unit)
        unit_name = _unit_display_name(source_unit)
        major_count = _unit_major_count(source_unit)
        source_volunteer_id = _unit_volunteer_id(source_unit)
        count_text = f"，组内共 {major_count} 个专业" if label == "专业组" and major_count > 0 else ""
        source_text = f"第 {source_position} 个{label}" if source_position else f"当前定位到的{label}"
        target_text = f"第 {int(target_position)} 个{label}位置"
        if source_position is not None and int(source_position) == int(target_position):
            return (
                f"{unit_name} 已经在第{int(target_position)}位，本次不需要移动。"
                "如果想调整它的位置，可以告诉我新的目标位置。",
                {
                    "source_unit_id": source_unit_id,
                    "source_unit_name": unit_name,
                    "source_unit_position": source_position,
                    "target_unit_position": int(target_position),
                    "source_unit_major_count": major_count,
                    "unit_kind": label,
                    "position_semantics": _unit_position_semantics(source_unit),
                    "position_resolution": "already_at_target",
                },
            )
        selector_reason = ""
        if has_tier_local_selector:
            tier = _normalize_tier_filter(filters.get("tier") or filters.get("target_tier") or filters.get("targetTier"))
            sort_field = _SORT_FIELD_ALIASES.get(
                str(filters.get("sort_field") or filters.get("sortField") or filters.get("sort_by") or filters.get("sortBy") or "").strip(),
                "admissionRatio",
            )
            sort_label = _SORT_FIELD_LABELS.get(sort_field, sort_field)
            rank_label = _tier_local_rank_label(sort_field, str(filters.get("rank") or filters.get("rankMode") or filters.get("select") or "").strip())
            sort_value = _item_sort_value(source_unit, sort_field)
            value_text = f"，{sort_label}{_format_sort_value(sort_value, sort_field)}" if sort_value is not None else ""
            selector_reason = f"（按{tier}档内{sort_label}{rank_label}选择{value_text}）"
        explanation = _unit_position_explanation(source_unit)
        summary = (
            "预览如下：\n\n"
            f"- 源{label}：{source_text} — {unit_name}{count_text}{selector_reason}\n"
            f"- 目标位置：第{int(target_position)}位（{target_text}）\n"
            f"- 移动方式：{'整组移动，组内专业顺序保持不变' if label == '专业组' else '移动该志愿，其他志愿按顺序衔接'}\n\n"
            f"{explanation}"
        )
        facts = {
            "source_unit_id": source_unit_id,
            "source_unit_name": unit_name,
            "source_unit_position": source_position,
            "target_unit_position": int(target_position),
            "source_unit_major_count": major_count,
            "unit_kind": label,
            "position_semantics": _unit_position_semantics(source_unit),
            "resolved_apply_payload": (
                _build_resolved_apply_payload(
                    plan_model,
                    volunteer_ids=[source_volunteer_id],
                    action_family="move_unit",
                    target_position=int(target_position),
                )
                if label == "志愿" and source_volunteer_id
                else _build_resolved_apply_payload(
                    plan_model,
                    unit_ids=[source_unit_id],
                    target_position=int(target_position),
                )
                if source_unit_id
                else {}
            ),
        }
        if has_tier_local_selector:
            sort_field = _SORT_FIELD_ALIASES.get(
                str(filters.get("sort_field") or filters.get("sortField") or filters.get("sort_by") or filters.get("sortBy") or "").strip(),
                "admissionRatio",
            )
            facts.update(selector_facts)
            facts.update(
                {
                    "selector": f"tier_local_{_normalize_tier_local_selection_mode(sort_field, str(filters.get('rank') or filters.get('rankMode') or filters.get('select') or '').strip())}_{sort_field}",
                    "tier": _normalize_tier_filter(filters.get("tier") or filters.get("target_tier") or filters.get("targetTier")),
                    "sort_field": sort_field,
                    "sort_label": _SORT_FIELD_LABELS.get(sort_field, sort_field),
                    "sort_value": _item_sort_value(source_unit, sort_field),
                }
            )
            if sort_field == "admissionRatio":
                facts["admission_ratio"] = _item_sort_value(source_unit, "admissionRatio")
        return summary, facts
    except Exception:
        logger.exception("_build_move_ordered_unit_preview_summary failed: session_id=%s", ctx.deps.sessionid)
        return None, {}


async def _build_remove_ordered_unit_preview_summary(
    ctx: RunContext[RequestContext],
    plan_model: PlanActionPlan,
) -> tuple[str | None, dict[str, Any]]:
    try:
        state_resp = await _get_planning_state_request(ctx.deps.sessionid)
        state = (state_resp or {}).get("data") or {}
        ordered_state = state.get("orderedPlanState") or {}
        units = _ordered_visible_units(ordered_state, str(state.get("volunteerModel") or state.get("volunteer_model") or ""))
        if not units:
            return (
                "当前方案里还没有可删除的志愿，所以不能按位置删除。"
                "需要先生成或加入志愿后，才能预览删除哪些内容。",
                {"position_semantics": "ordered_unit_position", "position_resolution": "empty_plan"},
            )
        unit_ids = _extract_unit_ids(plan_model)
        position_refs = _extract_unit_source_positions(plan_model)
        source_position = position_refs[0] if position_refs else None
        action = _first_atomic_action(plan_model)
        if not unit_ids and _atomic_position_scope(action) == "after":
            matched_units, range_facts = _resolve_ordered_visible_units_from_position_scope(plan_model, units)
            if source_position is None:
                return (
                    "这次还没定位到从第几位之后开始删除。请补充起始位置，我会先给你删除预览。",
                    {
                        "position_semantics": "ordered_unit_position",
                        "position_resolution": "missing_source_position",
                        "ordered_unit_count": len(units),
                        **range_facts,
                    },
                )
            if not matched_units:
                tier = str(range_facts.get("position_scope_tier") or "").strip()
                tier_text = f"且属于“{tier}”区间的" if tier else ""
                if source_position is not None and source_position >= len(units):
                    return (
                        f"当前方案只有 {len(units)} 个可排序项，第 {source_position} 位之后没有可删除的内容。",
                        {
                            "position_semantics": "ordered_unit_position",
                            "position_resolution": "range_empty",
                            "ordered_unit_count": len(units),
                            "source_unit_position": source_position,
                            **range_facts,
                        },
                    )
                return (
                    f"当前方案里第 {source_position} 位之后暂时没有匹配{tier_text}内容，所以这次不需要按这个范围删除。",
                    {
                        "position_semantics": "ordered_unit_position",
                        "position_resolution": "range_empty",
                        "ordered_unit_count": len(units),
                        "source_unit_position": source_position,
                        **range_facts,
                    },
                )

            label = _unit_kind_label(matched_units[0])
            examples = "；".join(
                f"第 {idx} 个{_unit_kind_label(unit)}：{_unit_display_name(unit)}"
                for idx, unit in [
                    (unit_index + 1, unit)
                    for unit_index, unit in enumerate(units)
                    if unit in matched_units
                ][:5]
            )
            total_major_count = sum(_unit_major_count(unit) for unit in matched_units)
            tier = str(range_facts.get("position_scope_tier") or "").strip()
            tier_text = f"、属于“{tier}”区间" if tier else ""
            limit = int(range_facts.get("position_scope_limit") or 0)
            limit_text = f"、最多 {limit} 个" if limit > 0 else ""
            resolved_payload, volunteer_ids, resolved_unit_ids = _resolved_payload_for_ordered_visible_units(plan_model, matched_units)
            if label == "专业组":
                remove_count_text = f"{total_major_count} 个专业 / {len(matched_units)} 个专业组"
                method_text = "执行后这些专业组会整体移出，后续专业组前移。"
            else:
                remove_count_text = f"{len(matched_units)} 个志愿"
                method_text = "执行后后续志愿前移。"
            summary = (
                f"会删除第 {source_position} 位之后{tier_text}{limit_text}的 {len(matched_units)} 个{label}。"
                f"本次将减少 {remove_count_text}。"
                f"命中项包括：{examples}。"
                f"{method_text}"
            )
            return summary, {
                "position_semantics": _unit_position_semantics(matched_units[0]),
                "unit_kind": label,
                "source_unit_position": source_position,
                "source_unit_major_count": total_major_count,
                "matched_unit_count": len(matched_units),
                "matched_unit_names": [_unit_display_name(unit) for unit in matched_units[:10]],
                "resolved_unit_ids": resolved_unit_ids,
                "resolved_volunteer_ids": volunteer_ids,
                "resolved_apply_payload": resolved_payload,
                **range_facts,
            }
        source_unit: dict[str, Any] | None = None
        source_unit_id = ""

        if unit_ids:
            source_unit_id = unit_ids[0]
            for idx, unit in enumerate(units, start=1):
                candidate_id = str((unit or {}).get("unitId") or (unit or {}).get("id") or "").strip()
                if candidate_id == source_unit_id:
                    source_unit = unit
                    source_position = source_position or idx
                    break
        elif source_position is not None and 0 < source_position <= len(units):
            source_unit = units[source_position - 1] or {}
            source_unit_id = str(source_unit.get("unitId") or source_unit.get("id") or "").strip()

        if source_unit is None:
            if source_position is not None:
                return (
                    f"当前方案只有 {len(units)} 个可排序项，找不到第 {source_position} 个，"
                    "所以这次还不能生成删除预览。你可以先补齐方案，或重新指定当前方案里已有的位置。",
                    {
                        "position_semantics": "ordered_unit_position",
                        "position_resolution": "source_position_out_of_range",
                        "ordered_unit_count": len(units),
                        "source_unit_position": source_position,
                    },
                )
            return (
                "会从当前方案排序区中删除指定项。"
                "这里的“第几个”按当前方案展示顺序计算，确认后会影响方案顺序和导出顺序。",
                {"position_semantics": "ordered_unit_position"},
            )

        label = _unit_kind_label(source_unit)
        unit_name = _unit_display_name(source_unit)
        major_count = _unit_major_count(source_unit)
        source_volunteer_id = _unit_volunteer_id(source_unit)
        count_text = f"，组内共 {major_count} 个专业" if label == "专业组" and major_count > 0 else ""
        source_text = f"第 {source_position} 个{label}" if source_position else f"当前定位到的{label}"
        if label == "专业组" and major_count > 0:
            removed_count_text = f"{major_count} 个专业 / 1 个专业组"
            remove_method_text = "执行后该组内专业会一并移出，后续专业组前移"
        else:
            removed_count_text = "1 个志愿"
            remove_method_text = "执行后后续志愿前移"
        explanation = _unit_position_explanation(source_unit)
        summary = (
            f"会删除{source_text}：{unit_name}{count_text}。"
            f"{explanation}"
            f"{remove_method_text}，方案数量将减少 {removed_count_text}。"
        )
        return summary, {
            "source_unit_id": source_unit_id,
            "source_unit_name": unit_name,
            "source_unit_position": source_position,
            "source_unit_major_count": major_count,
            "unit_kind": label,
            "position_semantics": _unit_position_semantics(source_unit),
            "resolved_apply_payload": (
                _build_resolved_apply_payload(
                    plan_model,
                    volunteer_ids=[source_volunteer_id],
                    action_family="remove_units",
                )
                if label == "志愿" and source_volunteer_id
                else _build_resolved_apply_payload(
                    plan_model,
                    unit_ids=[source_unit_id],
                )
                if source_unit_id
                else {}
            ),
        }
    except Exception:
        logger.exception("_build_remove_ordered_unit_preview_summary failed: session_id=%s", ctx.deps.sessionid)
        return None, {}


def _is_short_plan_confirmation(text: str) -> bool:
    normalized = "".join(str(text or "").split()).strip("。.!！?")
    if not normalized:
        return False
    if normalized in {
        "确认",
        "确认执行",
        "确定",
        "可以",
        "好的",
        "好",
        "行",
        "执行",
        "开始执行",
        "执行吧",
        "应用吧",
        "直接应用吧",
        "按这个来",
        "就按这个来",
        "按刚才的来",
        "就按刚才的来",
        "就这样",
        "就这样吧",
        "就这样执行",
        "用这个",
        "就用这个",
    }:
        return True
    return normalized.startswith(("确认", "执行")) and len(normalized) <= 8


def _allows_mutating_apply(ctx: RunContext[RequestContext], plan_model: PlanActionPlan) -> bool:
    if plan_model.stage != "apply" or plan_model.action_family not in _MUTATING_ACTION_FAMILIES:
        return True
    pending = resolve_pending_confirmation(ctx.deps)
    active_pending_family = (
        pending.action_family
        if pending is not None and pending.kind == "plan_mutation"
        else ""
    )
    if active_pending_family == plan_model.action_family and (
        bool(getattr(ctx.deps, "confirmed_via_pending", False))
        or bool(getattr(ctx.deps, "confirmed_via_card", False))
    ):
        return True
    return False


def _has_filter_selection_scope(filters: dict[str, Any]) -> bool:
    for key, value in (filters or {}).items():
        if key in {"limit", "preserve_count", "preserveCount", "require_capacity_check", "requireCapacityCheck"}:
            continue
        if key in {"school_tags", "major_tags"} and str(value or "").strip() == "[]":
            continue
        if str(value or "").strip():
            return True
    return False


def _execution_missing_inputs(ctx: RunContext[RequestContext], plan_model: PlanActionPlan) -> list[str]:
    if plan_model.action_family == "generate_plan":
        return _generation_missing_inputs(ctx)
    if plan_model.action_family == "sort_ordered_plan":
        if plan_model.stage not in {"preview", "apply"}:
            return []
        sort_field = _infer_ordered_sort_field(plan_model, default="")
        if not sort_field:
            return ["sort_field"]
        return []
    if plan_model.action_family == "add_units":
        if plan_model.stage not in {"preview", "apply"}:
            return []
        if not plan_model.atomic_actions:
            return ["selection_scope"]
        atomic = plan_model.atomic_actions[0]
        if not atomic.volunteer_ids and not _has_filter_selection_scope(atomic.filters):
            return ["selection_scope"]
        return []
    if plan_model.action_family != "replace_units":
        return []
    if plan_model.stage not in {"preview", "apply"}:
        return []
    if not plan_model.atomic_actions:
        return ["volunteer_ids", "replacement_scope"]
    atomic = plan_model.atomic_actions[0]
    missing: list[str] = []
    if not atomic.volunteer_ids and atomic.review_issue_target is None:
        missing.append("volunteer_ids")
    if not _has_filter_selection_scope(atomic.filters):
        missing.append("replacement_scope")
    return missing


def _review_issue_replacement_scope_guidance(
    issue_label: str,
    unit_count: int,
    volunteer_count: int,
) -> str:
    return (
        f"我先定位了当前方案里的{issue_label}：共 {unit_count} 个专业组，涉及 {volunteer_count} 条志愿。"
        "这类内容不建议直接整批替换，因为需要在学费、院校层次、专业方向和录取稳定性之间做取舍。"
        "可以先打开审查结果里的处理建议，看哪些能一进一出替换；"
        "如果你有明确方向，也可以直接说想换成正常收费、同专业、同层次或更稳的志愿，我再给你一版调整预览。"
    )


def _execution_missing_inputs_message(plan_model: PlanActionPlan, missing_inputs: list[str]) -> str:
    missing = {str(item or "").strip() for item in missing_inputs if str(item or "").strip()}
    if "existing_plan" in missing and plan_model.action_family in {"move_ordered_unit", "remove_ordered_unit", "move_unit", "remove_units"}:
        atomic = _first_atomic_action(plan_model)
        source_position = getattr(atomic, "source_position", None) if atomic is not None else None
        target_position = getattr(atomic, "target_position", None) if atomic is not None else None
        try:
            source_position_int = int(source_position) if source_position is not None else None
        except (TypeError, ValueError):
            source_position_int = None
        try:
            target_position_int = int(target_position) if target_position is not None else None
        except (TypeError, ValueError):
            target_position_int = None
        if plan_model.action_family in {"move_ordered_unit", "move_unit"}:
            move_scope = (
                f"第{source_position_int}个移动到第{target_position_int}位"
                if source_position_int and target_position_int
                else "这个位置移动"
            )
            return (
                f"当前还没有正式方案，找不到可移动的{f'第{source_position_int}个志愿' if source_position_int else '志愿'}，"
                f"所以不能生成“{move_scope}”的调整预览。"
                "需要先生成或加入志愿后，才能按位置移动。"
            )
        remove_scope = f"第{source_position_int}个志愿" if source_position_int else "指定志愿"
        return (
            f"当前还没有正式方案，找不到要删除的{remove_scope}，所以不能生成删除预览。"
            "需要先生成或加入志愿后，才能按位置删除。"
        )
    if plan_model.action_family == "generate_plan" and {"generation_profile", "generation_candidate_pool"}.issubset(missing):
        return (
            "要生成志愿方案，还需要先补全基础信息。"
            "请先确认省份、分数、位次、选科、批次，以及主要专业或地域想法；"
            "信息补齐并计算出候选池后，我再帮你生成方案。"
        )
    if plan_model.action_family == "generate_plan" and "generation_profile" in missing:
        return (
            "要生成志愿方案，还需要先补全基础信息。"
            "请先确认省份、分数、位次、选科、批次，以及主要专业或地域想法；"
            "信息补齐后我再帮你生成方案。"
        )
    if plan_model.action_family == "generate_plan" and "generation_candidate_pool" in missing:
        return (
            "当前还没有可用于生成方案的候选池或工作方案，不能直接列出生成方案确认卡。"
            "需要先按已确认的基础信息计算候选；如果省份、分数、选科或批次还没确认，请先补齐这些信息。"
        )
    if plan_model.action_family == "add_units" and "selection_scope" in missing:
        return (
            "这次还没定位到要加入方案的候选志愿。"
            "请补充学校、专业、地域等筛选范围，或先在候选列表里点选要加入的志愿，我会先给你确认预览。"
        )
    if plan_model.action_family == "replace_units":
        if {"volunteer_ids", "replacement_scope"}.issubset(missing):
            return (
                "这次替换还没说清楚：要替换当前方案里的哪条志愿，以及希望换成什么方向。"
                "请补充学校/专业名称和替换方向，我会先给你一版可确认的预览。"
            )
        if "volunteer_ids" in missing:
            return (
                "这次替换还没定位到当前方案里的具体志愿。"
                "请补充学校、专业组或专业名称，我会先确认目标后再给你预览。"
            )
        if "replacement_scope" in missing:
            return (
                "这次替换还缺少新志愿的筛选方向。"
                "请说明想换成哪个专业、院校或地域范围，我会先给你一版可确认的预览。"
            )
    if plan_model.action_family == "sort_ordered_plan" and "sort_field" in missing:
        return (
            "这次排序还缺少排序依据。"
            "请明确是按录取率、院校层次，还是推荐系数来排；我会先给你一版可确认的预览。"
        )
    return "这次操作还缺少必要信息，请补充清楚后我再继续。"


def _hydrate_replace_filters_from_profile(
    ctx: RunContext[RequestContext],
    plan_model: PlanActionPlan,
) -> None:
    if plan_model.action_family != "replace_units" or not plan_model.atomic_actions:
        return
    atomic = plan_model.atomic_actions[0]
    if _has_filter_selection_scope(atomic.filters):
        return
    if getattr(atomic, "review_issue_target", None) is not None:
        return
    profile = getattr(ctx.deps, "init_profile", None)
    if profile is None:
        return

    major_level2 = [value for value in getattr(profile.major, "level2", []) if str(value or "").strip()]
    if major_level2:
        atomic.filters["major_tags"] = json.dumps(major_level2, ensure_ascii=False)
    else:
        major_level3 = [value for value in getattr(profile.major, "level3", []) if str(value or "").strip()]
        if major_level3 and not str(atomic.filters.get("major_keyword") or "").strip():
            atomic.filters["major_keyword"] = str(major_level3[0]).strip()
    atomic.filters.setdefault("school_tags", "[]")
    atomic.filters.setdefault("limit", "5")


def _with_confirmation_hint(summary: str) -> str:
    text = (summary or "").strip() or "这个动作会改动当前方案。"
    if "确认" in text and ("执行" in text or "后" in text):
        return text
    return f"{text} 需要你确认后才会执行。"


def _is_downgraded_unconfirmed_apply(plan_model: PlanActionPlan) -> bool:
    return bool((getattr(plan_model, "facts", {}) or {}).get("downgraded_unconfirmed_apply"))


def _normalize_keywords(value: str | None) -> list[str]:
    if not value:
        return []
    stripped = value.strip()
    return [stripped] if stripped else []


def _parse_filter_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item or "").strip() for item in value if str(item or "").strip()]
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except Exception:
        return [part.strip() for part in text.replace("，", ",").split(",") if part.strip()]
    if isinstance(parsed, list):
        return [str(item or "").strip() for item in parsed if str(item or "").strip()]
    return [text]


def _collect_action_major_scope_payload(action: PlanAtomicAction | None) -> dict[str, list[str]] | None:
    if action is None:
        return None
    payload: dict[str, list[str]] = {}

    def extend(key: str, values: list[str]) -> None:
        bucket = payload.setdefault(key, [])
        for value in values:
            name = _major_base_name(value)
            if name and name not in bucket:
                bucket.append(name)

    extend("negative_level3", list(getattr(action, "source_major_names", []) or []))
    filters = action.filters or {}
    extend("negative_level3", _parse_filter_list(filters.get("major_keyword")))
    extend("negative_level3", _parse_filter_list(filters.get("major_tags")))
    extend("negative_level3", _parse_filter_list(filters.get("major_level3")))
    extend("negative_level2", _parse_filter_list(filters.get("major_level2")))
    extend("negative_level1", _parse_filter_list(filters.get("major_level1")))
    extend("negative_level3", _parse_filter_list(filters.get("negative_level3")))
    extend("negative_level2", _parse_filter_list(filters.get("negative_level2")))
    extend("negative_level1", _parse_filter_list(filters.get("negative_level1")))
    return {key: values for key, values in payload.items() if values} or None


def _canonical_major_scope_names(scope_payload: dict[str, list[str]] | None) -> list[str]:
    if not scope_payload:
        return []
    ordered_keys = ("negative_level3", "negative_level2", "negative_level1")
    names: list[str] = []
    for key in ordered_keys:
        for value in scope_payload.get(key, []):
            name = _major_base_name(value)
            if name and name not in names:
                names.append(name)
    return names


def _canonicalize_major_scope_action(
    action: PlanAtomicAction,
    *,
    latest_utterance: str,
    batch: str | None,
) -> PlanAtomicAction:
    scope_payload = _collect_action_major_scope_payload(action)
    canonical_payload = canonicalize_major_intent_payload(scope_payload, latest_utterance, batch)
    if not canonical_payload:
        return action

    filters = dict(action.filters or {})
    for key in _PLAN_MAJOR_SCOPE_FILTER_KEYS:
        filters.pop(key, None)
    for payload_key, filter_key in _PLAN_MAJOR_LEVEL_FILTER_KEYS.items():
        values = canonical_payload.get(payload_key) or []
        if values:
            filters[filter_key] = list(values)

    canonical_source_names = _canonical_major_scope_names(canonical_payload)
    return action.model_copy(
        update={
            "source_major_names": canonical_source_names,
            "filters": filters,
        }
    )


def _canonicalize_plan_major_scopes(
    ctx: RunContext[RequestContext],
    plan_model: PlanActionPlan,
) -> PlanActionPlan:
    if plan_model.action_family != "remove_units" or not plan_model.atomic_actions:
        return plan_model
    latest_utterance = _latest_user_text(ctx)
    batch = getattr(ctx.deps, "batch", None) or "01"
    updated_actions = [
        _canonicalize_major_scope_action(
            action,
            latest_utterance=latest_utterance,
            batch=batch,
        )
        for action in plan_model.atomic_actions
    ]
    if updated_actions == list(plan_model.atomic_actions):
        return plan_model
    return plan_model.model_copy(update={"atomic_actions": updated_actions})


def _derive_candidate_major_keywords(
    major_keyword: str | None,
    major_tags: list[str] | None,
    batch: str | None = "01",
) -> list[str]:
    explicit_keywords = _normalize_keywords(major_keyword)
    if explicit_keywords:
        return _expand_candidate_major_query_keywords(explicit_keywords, batch)
    return _expand_candidate_major_query_keywords(
        [str(item or "").strip() for item in (major_tags or []) if str(item or "").strip()],
        batch,
    )


def _children_for_major_scope(level: str, name: str, batch: str | None = "01") -> list[str]:
    if not name:
        return []
    mappings = major_parent_mappings_for_batch(_major_scope_batch(batch))
    level3_to_level2 = mappings.get("level3_to_level2", {})
    level2_to_level1 = mappings.get("level2_to_level1", {})
    if level == "level2":
        return [major for major, parent in level3_to_level2.items() if parent == name]
    if level == "level1":
        level2_children = [level2 for level2, parent in level2_to_level1.items() if parent == name]
        children: list[str] = []
        for level2 in level2_children:
            children.extend(major for major, parent in level3_to_level2.items() if parent == level2)
        return children
    return []


def _candidate_major_query_terms_for_keyword(keyword: str, batch: str | None = "01") -> list[str]:
    text = str(keyword or "").strip()
    if not text:
        return []
    try:
        resolved = resolve_major_entity(text, _major_scope_batch(batch))
    except Exception:
        return [text]

    candidates = [
        (str(candidate.level or ""), str(candidate.canonical_name or "").strip())
        for candidate in resolved.candidates
        if str(candidate.level or "") in {"level1", "level2", "level3"} and str(candidate.canonical_name or "").strip()
    ]
    unique_candidates = list(dict.fromkeys(candidates))
    if len(unique_candidates) != 1:
        return [text]

    level, name = unique_candidates[0]
    if level == "level3":
        return [name]
    children = _children_for_major_scope(level, name, batch)
    return list(dict.fromkeys([name, *children])) or [name]


def _expand_candidate_major_query_keywords(keywords: list[str], batch: str | None = "01") -> list[str]:
    expanded: list[str] = []
    for keyword in keywords:
        for term in _candidate_major_query_terms_for_keyword(keyword, batch):
            if term and term not in expanded:
                expanded.append(term)
    return expanded


def _compact_ref_text(value: Any) -> str:
    text = "".join(str(value or "").split()).lower()
    return re.sub(r"[\-_/·.。,:：，、的]+", "", text)


def _major_base_name(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return re.split(r"[（(]", text, maxsplit=1)[0].strip()


def _major_alias_variants(value: Any) -> list[str]:
    base_name = _major_base_name(value)
    if not base_name:
        return []
    variants = major_alias_variants_for_name(base_name)
    target_token = _major_target_token(base_name)
    if target_token and target_token != base_name:
        variants.append(target_token)
    return list(dict.fromkeys(variant for variant in variants if variant))


def _school_alias_variants(value: Any) -> list[str]:
    return school_alias_variants(value)


def _major_name_variants(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    variants: list[str] = [text]
    current = text
    while True:
        trimmed = re.sub(r"\s*[（(][^()（）]*[)）]\s*$", "", current).strip()
        if not trimmed or trimmed == current:
            break
        variants.append(trimmed)
        current = trimmed
    base_name = _major_base_name(text)
    if base_name and base_name not in variants:
        variants.append(base_name)
    variants.extend(_major_alias_variants(text))
    return list(dict.fromkeys(variant for variant in variants if variant))


def _school_name_variants(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    variants: list[str] = [text]
    trimmed = re.sub(r"\s*[（(][^()（）]*[)）]\s*$", "", text).strip()
    if trimmed and trimmed != text:
        variants.append(trimmed)
    variants.extend(_school_alias_variants(text))
    return list(dict.fromkeys(variant for variant in variants if variant))


def _ordered_item_labels(item: dict[str, Any]) -> list[str]:
    school_name = str(item.get("schoolName") or "").strip()
    major_name = str(item.get("majorName") or "").strip()
    school_variants = _school_name_variants(school_name)
    major_variants = _major_name_variants(major_name)
    volunteer_id = str(item.get("volunteerId") or "").strip()
    tier = str(item.get("tier") or item.get("bucket") or "").strip()
    labels = [volunteer_id]
    position = item.get("position")
    if position is not None and str(position).strip():
        position_text = str(position).strip()
        labels.extend([position_text, f"@{position_text}", f"第{position_text}位"])
    for school_variant in school_variants:
        for major_variant in major_variants:
            labels.extend(
                [
                    f"{school_variant}-{major_variant}",
                    f"{school_variant}{major_variant}",
                    f"{school_variant}的{major_variant}",
                    f"{school_variant}.{major_variant}",
                ]
            )
            if position is not None and str(position).strip():
                position_text = str(position).strip()
                labels.extend(
                    [
                        f"{school_variant}-{major_variant}@{position_text}",
                        f"{school_variant}{major_variant}@{position_text}",
                        f"{school_variant}的{major_variant}@{position_text}",
                        f"{school_variant}.{major_variant}@{position_text}",
                    ]
                )
                if tier:
                    labels.extend(
                        [
                            f"{school_variant}-{major_variant}({tier})@{position_text}",
                            f"{school_variant}{major_variant}({tier})@{position_text}",
                            f"{school_variant}的{major_variant}({tier})@{position_text}",
                            f"{school_variant}.{major_variant}({tier})@{position_text}",
                        ]
                    )
    labels.extend(str(item.get(key) or "").strip() for key in ("displayName", "name", "title"))
    return [label for label in labels if label]


def _major_target_token(value: str) -> str:
    text = _major_base_name(value)
    text = re.sub(r"(学|类)$", "", text).strip()
    return text


def _ordered_unit_id_for_item(item: dict[str, Any]) -> str:
    volunteer_id = str(item.get("volunteerId") or "").strip()
    if volunteer_id:
        separator = volunteer_id.find("_")
        if separator > 0:
            return volunteer_id[:separator]
        return volunteer_id
    return str(item.get("schoolName") or "").strip()


def _count_ordered_units_for_ids(items: list[dict[str, Any]], volunteer_ids: list[str]) -> int:
    volunteer_id_set = {str(value or "").strip() for value in volunteer_ids if str(value or "").strip()}
    unit_ids: list[str] = []
    for item in items:
        volunteer_id = str(item.get("volunteerId") or "").strip()
        if volunteer_id not in volunteer_id_set:
            continue
        unit_id = _ordered_unit_id_for_item(item)
        if unit_id and unit_id not in unit_ids:
            unit_ids.append(unit_id)
    return len(unit_ids)


def _extract_source_major_names(plan_model: PlanActionPlan) -> list[str]:
    names: list[str] = []
    for action in plan_model.atomic_actions or []:
        raw_values = getattr(action, "source_major_names", None)
        if not isinstance(raw_values, list):
            continue
        for value in raw_values:
            major_name = _major_base_name(value)
            if major_name and major_name not in names:
                names.append(major_name)
    return names


def _expand_ordered_ids_by_major_names(
    items: list[dict[str, Any]],
    base_ids: list[str],
    source_major_names: list[str],
) -> list[str]:
    if not base_ids or not source_major_names:
        return base_ids
    major_targets = {
        _major_base_name(name)
        for name in source_major_names
        if _major_base_name(name)
    }
    if not major_targets:
        return base_ids
    expanded_ids = list(base_ids)
    for item in items:
        item_major = _major_base_name(item.get("majorName"))
        if item_major not in major_targets:
            continue
        volunteer_id = str(item.get("volunteerId") or "").strip()
        if volunteer_id and volunteer_id not in expanded_ids:
            expanded_ids.append(volunteer_id)
    return expanded_ids


async def _resolve_ordered_volunteer_refs(
    ctx: RunContext[RequestContext],
    refs: list[str],
    *,
    source_major_names: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    if not refs:
        return [], []
    session_id = ctx.deps.sessionid
    try:
        result = await _get_planning_ordered_plan_request(session_id)
    except Exception:
        logger.warning("resolve ordered volunteer refs failed: session_id=%s", session_id, exc_info=True)
        if all(_VOLUNTEER_ID_LIKE_RE.match(str(ref or "").strip()) for ref in refs):
            return [str(ref).strip() for ref in refs if str(ref or "").strip()], []
        return [], refs
    if result.get("code") != 0:
        if all(_VOLUNTEER_ID_LIKE_RE.match(str(ref or "").strip()) for ref in refs):
            return [str(ref).strip() for ref in refs if str(ref or "").strip()], []
        return [], refs
    items = (result.get("data") or {}).get("items") or []
    item_by_id: dict[str, dict[str, Any]] = {}
    exact_candidates: dict[str, list[str]] = {}
    compact_candidates: dict[str, list[str]] = {}
    compact_labels: list[tuple[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        volunteer_id = str(item.get("volunteerId") or "").strip()
        if not volunteer_id:
            continue
        item_by_id[volunteer_id] = item
        for label in _ordered_item_labels(item):
            exact_candidates.setdefault(label, [])
            if volunteer_id not in exact_candidates[label]:
                exact_candidates[label].append(volunteer_id)
            compact_label = _compact_ref_text(label)
            compact_candidates.setdefault(compact_label, [])
            if volunteer_id not in compact_candidates[compact_label]:
                compact_candidates[compact_label].append(volunteer_id)
            compact_labels.append((compact_label, volunteer_id))

    resolved: list[str] = []
    missing: list[str] = []
    for ref in refs:
        text = str(ref or "").strip()
        compact_ref = _compact_ref_text(text)
        volunteer_id = None
        exact_matches = exact_candidates.get(text) or []
        if len(exact_matches) == 1:
            volunteer_id = exact_matches[0]
        if not volunteer_id:
            compact_matches = compact_candidates.get(compact_ref) or []
            if len(compact_matches) == 1:
                volunteer_id = compact_matches[0]
        if not volunteer_id and compact_ref:
            partial_matches = [
                candidate_id
                for label, candidate_id in compact_labels
                if compact_ref in label or label in compact_ref
            ]
            unique_matches = list(dict.fromkeys(partial_matches))
            if len(unique_matches) == 1:
                volunteer_id = unique_matches[0]
        if volunteer_id:
            if volunteer_id not in resolved:
                resolved.append(volunteer_id)
        else:
            missing.append(text)

    if resolved and source_major_names:
        resolved = _expand_ordered_ids_by_major_names(items, resolved, source_major_names)
    return resolved, missing


def _ordered_ref_resolution_message(missing_text: str, action_label: str) -> str:
    return (
        f"我理解你想{action_label}的是：{missing_text}。"
        "但我在当前方案里还没有唯一匹配到这条志愿。"
        f"为避免动错，请先在方案里点选要{action_label}的那条，"
        "或补充更完整的学校、专业组、专业名称后我再给你确认。"
    )


async def _load_ordered_items(ctx: RunContext[RequestContext]) -> list[dict[str, Any]]:
    session_id = ctx.deps.sessionid
    try:
        result = await _get_planning_ordered_plan_request(session_id)
    except Exception:
        logger.warning("load ordered items failed: session_id=%s", session_id, exc_info=True)
        return []
    if result.get("code") != 0:
        return []
    return [item for item in ((result.get("data") or {}).get("items") or []) if isinstance(item, dict)]


def _ordered_item_display_name(item: dict[str, Any]) -> str:
    school_name = str(item.get("schoolName") or "").strip()
    major_name = str(item.get("majorName") or "").strip()
    if school_name and major_name:
        return f"{school_name} · {major_name}"
    return school_name or major_name or str(item.get("displayName") or item.get("name") or item.get("title") or "该志愿").strip()


def _compact_match_contains(haystack: Any, needle: Any) -> bool:
    haystack_text = _compact_ref_text(haystack)
    needle_text = _compact_ref_text(needle)
    if not haystack_text or not needle_text:
        return False
    return needle_text in haystack_text or haystack_text in needle_text


def _major_scope_matches(item_major: Any, target: Any, batch: str | None = "01") -> bool:
    target_base = _major_base_name(target)
    item_base = _major_base_name(item_major)
    if not target_base or not item_base:
        return False
    target_tokens = [target_base, *major_alias_variants_for_name(target_base, batch), _major_target_token(target_base)]
    item_tokens = [item_base, *major_alias_variants_for_name(item_base, batch), _major_target_token(item_base)]
    for target_token in target_tokens:
        for item_token in item_tokens:
            if _compact_match_contains(item_token, target_token):
                return True
    return False


def _major_scope_exact_name_matches(item_major: Any, target: Any, batch: str | None = "01") -> bool:
    target_base = _major_base_name(target)
    item_base = _major_base_name(item_major)
    if not target_base or not item_base:
        return False
    if _compact_ref_text(item_base) == _compact_ref_text(target_base):
        return True
    try:
        resolved = resolve_major_entity(item_base, _major_scope_batch(batch))
    except Exception:
        resolved = None
    if resolved is not None:
        candidates = [
            candidate
            for candidate in resolved.candidates
            if candidate.level == "level3" and str(candidate.canonical_name or "").strip()
        ]
        if len(candidates) == 1 and candidates[0].canonical_name == target_base:
            return True
        if candidates:
            return False
    target_alias_tokens = {
        _compact_ref_text(value)
        for value in major_alias_variants_for_name(target_base, batch)
        if _compact_ref_text(value)
    }
    return _compact_ref_text(item_base) in target_alias_tokens


_MAJOR_SCOPE_NAME_KEYS = (
    "majorName",
    "major_name",
    "majorItemName",
    "major_item_name",
    "majorUnitName",
    "major_unit_name",
    "unitName",
    "unit_name",
)
_MAJOR_SCOPE_LEVEL2_KEYS = (
    "majorCategory",
    "major_category",
    "majorCategoryName",
    "major_category_name",
    "subCategoryName",
    "sub_category_name",
)
_MAJOR_SCOPE_LEVEL1_KEYS = (
    "majorDiscipline",
    "major_discipline",
    "majorDisciplineName",
    "major_discipline_name",
    "categoryName",
    "category_name",
)
_MAJOR_SCOPE_NESTED_KEYS = (
    "majorItems",
    "major_items",
    "majors",
    "majorList",
    "major_list",
    "majorVOList",
    "major_vo_list",
)


def _major_scope_batch(batch: str | None) -> str:
    return batch or "01"


def _major_scope_target_candidates(target: Any, batch: str | None = "01") -> list[tuple[str, str]]:
    target_base = _major_base_name(target)
    if not target_base:
        return []
    available = major_name_sets_for_batch(_major_scope_batch(batch))
    for level in ("level3", "level2", "level1"):
        if target_base in available.get(level, set()):
            return [(level, target_base)]
    try:
        resolved = resolve_major_entity(target_base, _major_scope_batch(batch))
    except Exception:
        return []
    candidates = [
        (str(candidate.level or ""), str(candidate.canonical_name or "").strip())
        for candidate in resolved.candidates
        if str(candidate.level or "") in {"level1", "level2", "level3"} and str(candidate.canonical_name or "").strip()
    ]
    unique = list(dict.fromkeys(candidates))
    return unique if len(unique) == 1 else []


def _major_scope_values(record: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
    return list(dict.fromkeys(values))


def _has_major_scope_fields(record: dict[str, Any]) -> bool:
    return any(record.get(key) for key in (_MAJOR_SCOPE_NAME_KEYS + _MAJOR_SCOPE_LEVEL2_KEYS + _MAJOR_SCOPE_LEVEL1_KEYS))


def _iter_major_scope_records(value: Any):
    if isinstance(value, str) and value.strip():
        yield {"majorName": value.strip()}
        return
    if isinstance(value, list):
        for child in value:
            yield from _iter_major_scope_records(child)
        return
    if not isinstance(value, dict):
        return
    if _has_major_scope_fields(value):
        yield value
    for key in _MAJOR_SCOPE_NESTED_KEYS:
        if key in value:
            yield from _iter_major_scope_records(value.get(key))


def _major_record_matches_scope(record: dict[str, Any], target: Any, batch: str | None = "01") -> bool:
    target_candidates = _major_scope_target_candidates(target, batch)
    name_values = _major_scope_values(record, _MAJOR_SCOPE_NAME_KEYS)
    level2_values = _major_scope_values(record, _MAJOR_SCOPE_LEVEL2_KEYS)
    level1_values = _major_scope_values(record, _MAJOR_SCOPE_LEVEL1_KEYS)
    if not target_candidates:
        return any(_major_scope_matches(name, target, batch) for name in name_values)

    mappings = major_parent_mappings_for_batch(_major_scope_batch(batch))
    level3_to_level2 = mappings.get("level3_to_level2", {})
    level2_to_level1 = mappings.get("level2_to_level1", {})

    for target_level, target_name in target_candidates:
        if target_level == "level3":
            if any(_major_scope_exact_name_matches(name, target_name, batch) for name in name_values):
                return True
            continue
        if target_level == "level2":
            if any(_major_scope_matches(category, target_name, batch) for category in level2_values):
                return True
            if any(level3_to_level2.get(_major_base_name(name)) == target_name for name in name_values):
                return True
            continue
        if target_level == "level1":
            if any(_major_scope_matches(discipline, target_name, batch) for discipline in level1_values):
                return True
            if any(level2_to_level1.get(_major_base_name(category)) == target_name for category in level2_values):
                return True
            for name in name_values:
                parent_level2 = level3_to_level2.get(_major_base_name(name))
                if parent_level2 and level2_to_level1.get(parent_level2) == target_name:
                    return True
    return False


def _matching_major_scope_records(
    item: dict[str, Any],
    targets: list[str],
    batch: str | None = "01",
) -> list[dict[str, Any]]:
    records = [record for record in _iter_major_scope_records(item) if isinstance(record, dict)]
    if not records:
        return []
    matched: list[dict[str, Any]] = []
    for record in records:
        if any(_major_record_matches_scope(record, target, batch) for target in targets):
            matched.append(record)
    return matched


def _filter_scope_values(action: PlanAtomicAction | None, *keys: str) -> list[str]:
    if action is None:
        return []
    filters = action.filters or {}
    values: list[str] = []
    for key in keys:
        values.extend(_parse_filter_list(filters.get(key)))
    return list(dict.fromkeys(value for value in values if value))


def _remove_scope_program_types(action: PlanAtomicAction | None) -> list[str]:
    return _filter_scope_values(action, *_PROGRAM_TYPE_FILTER_KEYS)


def _remove_scope_min_tuition(action: PlanAtomicAction | None) -> int | None:
    values = _filter_scope_values(action, *_MIN_TUITION_FILTER_KEYS)
    for value in values:
        try:
            parsed = int(float(str(value).strip()))
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return None


def _remove_scope_max_tuition(action: PlanAtomicAction | None) -> int | None:
    values = _filter_scope_values(action, *_MAX_TUITION_FILTER_KEYS)
    for value in values:
        try:
            parsed = int(float(str(value).strip()))
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return None


def _remove_scope_preference_fit(action: PlanAtomicAction | None) -> list[str]:
    normalized: list[str] = []
    aliases = {
        "non_intent": "unrelated",
        "not_intent": "unrelated",
        "not_aligned": "unrelated",
        "not_preferred": "unrelated",
        "unrelated": "unrelated",
        "irrelevant": "unrelated",
        "不沾边": "unrelated",
        "非意向": "unrelated",
        "不相关": "unrelated",
        "不匹配": "unrelated",
        "conflict": "conflict",
        "negative": "conflict",
        "excluded": "conflict",
        "排除": "conflict",
        "冲突": "conflict",
        "aligned": "aligned",
        "preferred": "aligned",
        "positive": "aligned",
        "意向": "aligned",
        "匹配": "aligned",
    }
    for value in _filter_scope_values(action, *_PREFERENCE_FIT_FILTER_KEYS):
        text = str(value or "").strip()
        if not text:
            continue
        mapped = aliases.get(text, aliases.get(text.lower(), ""))
        if mapped and mapped not in normalized:
            normalized.append(mapped)
    return normalized


def _remove_scope_major_names(action: PlanAtomicAction | None, batch: str | None = "01") -> list[str]:
    names_by_level = _remove_scope_major_names_by_level(action, batch)
    return list(
        dict.fromkeys(
            [
                *names_by_level.get("negative_level3", []),
                *names_by_level.get("negative_level2", []),
                *names_by_level.get("negative_level1", []),
            ]
        )
    )


def _remove_scope_major_names_by_level(action: PlanAtomicAction | None, batch: str | None = "01") -> dict[str, list[str]]:
    scope_payload = _collect_action_major_scope_payload(action)
    canonical_payload = canonicalize_major_intent_payload(scope_payload, "", batch)
    if not canonical_payload:
        return {}
    return {
        key: list(dict.fromkeys(_major_base_name(value) for value in values if _major_base_name(value)))
        for key, values in canonical_payload.items()
        if key in {"negative_level1", "negative_level2", "negative_level3"} and values
    }


def _normalize_school_scope_names(values: list[str], batch: str | None = "01") -> list[str]:
    normalized: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        try:
            resolved = resolve_school_entity(text, batch)
            name = resolved.best.canonical_name if resolved.best else text
        except Exception:
            name = text
        if name and name not in normalized:
            normalized.append(name)
    return normalized


def _remove_scope_school_names(action: PlanAtomicAction | None, batch: str | None = "01") -> list[str]:
    return _normalize_school_scope_names(_filter_scope_values(action, "school_keyword", "school_tags"), batch)


def _remove_scope_region_names(action: PlanAtomicAction | None) -> list[str]:
    names_by_level = _remove_scope_region_names_by_level(action)
    return list(dict.fromkeys([*names_by_level.get("province", []), *names_by_level.get("city", [])]))


def _remove_scope_region_names_by_level(action: PlanAtomicAction | None) -> dict[str, list[str]]:
    province_targets = normalize_region_names(
        _filter_scope_values(action, "province_keyword", "province"),
        expected_level="province",
    )
    city_targets = normalize_region_names(
        _filter_scope_values(action, "city_keyword", "city"),
        expected_level="city",
    )
    return {
        "province": list(dict.fromkeys(province_targets)),
        "city": list(dict.fromkeys(city_targets)),
    }


def _has_structured_remove_scope(action: PlanAtomicAction | None, batch: str | None = "01") -> bool:
    return bool(
        _remove_scope_major_names(action, batch)
        or _remove_scope_school_names(action, batch)
        or _remove_scope_region_names(action)
        or _remove_scope_program_types(action)
        or _remove_scope_min_tuition(action) is not None
        or _remove_scope_max_tuition(action) is not None
        or _remove_scope_preference_fit(action)
    )


def _iter_scope_text_values(value: Any):
    if value is None:
        return
    if isinstance(value, str):
        if value.strip():
            yield value.strip()
        return
    if isinstance(value, (int, float, bool)):
        yield str(value)
        return
    if isinstance(value, list):
        for child in value:
            yield from _iter_scope_text_values(child)
        return
    if isinstance(value, dict):
        for child in value.values():
            yield from _iter_scope_text_values(child)


_PROGRAM_SCOPE_TEXT_KEYS = (
    "schoolName",
    "displaySchoolName",
    "majorName",
    "unitName",
    "majorUnitName",
    "schoolNature",
    "schoolCategory",
    "schoolBatch",
    "majorPlanTags",
    "majorRankTags",
    "schoolRankTags",
    "schoolBasicTags",
    "schoolPopupTags",
    "reasonCodes",
    "riskFlags",
    "tags",
    "labels",
    "majorItems",
    "candidate",
)


def _program_type_matches_item(item: dict[str, Any], targets: list[str]) -> bool:
    if not targets:
        return True
    values: list[str] = []
    for key in _PROGRAM_SCOPE_TEXT_KEYS:
        values.extend(_iter_scope_text_values(item.get(key)) or [])
    return any(_compact_match_contains(value, target) for value in values for target in targets)


def _ordered_item_tuition_per_year(item: dict[str, Any]) -> int | None:
    return _candidate_item_tuition_per_year(item)


def _tuition_scope_matches_item(
    item: dict[str, Any],
    *,
    min_tuition: int | None,
    max_tuition: int | None,
) -> bool:
    if min_tuition is None and max_tuition is None:
        return True
    tuition = _ordered_item_tuition_per_year(item)
    if tuition is None:
        return False
    if min_tuition is not None and tuition < min_tuition:
        return False
    if max_tuition is not None and tuition > max_tuition:
        return False
    return True


def _item_matches_any_positive_intent(
    item: dict[str, Any],
    planning_state: dict[str, Any] | None,
    *,
    include_career_types: bool = True,
) -> bool:
    intent_state = _extract_plan_intent_state(planning_state)
    positive_majors = intent_state["positiveMajors"]
    positive_schools = intent_state["positiveSchools"]
    positive_regions = intent_state["positiveRegions"]
    career_types = intent_state["careerTypes"]
    if not (positive_majors or positive_schools or positive_regions or (career_types if include_career_types else [])):
        return False
    return bool(
        _item_matches_keyword(item, positive_majors, fields=("majorName", "majorCategory", "majorDiscipline"))
        or _item_matches_keyword(item, positive_schools, fields=("schoolName",))
        or _item_matches_keyword(item, positive_regions, fields=("provinceName", "cityName", "areaName"))
        or (include_career_types and _item_matches_career_labels(item, career_types))
    )


def _item_matches_any_negative_intent(
    item: dict[str, Any],
    planning_state: dict[str, Any] | None,
) -> bool:
    intent_state = _extract_plan_intent_state(planning_state)
    negative_majors = intent_state["negativeMajors"]
    negative_schools = intent_state["negativeSchools"]
    negative_regions = intent_state["negativeRegions"]
    if not (negative_majors or negative_schools or negative_regions):
        return False
    return bool(
        _item_matches_keyword(item, negative_majors, fields=("majorName", "majorCategory", "majorDiscipline"))
        or _item_matches_keyword(item, negative_schools, fields=("schoolName",))
        or _item_matches_keyword(item, negative_regions, fields=("provinceName", "cityName", "areaName"))
    )


def _preference_fit_matches_item(
    item: dict[str, Any],
    targets: list[str],
    planning_state: dict[str, Any] | None,
) -> bool:
    if not targets:
        return True
    # preference_fit represents explicit user intent fit. Career direction is a
    # weaker planning signal and must not make unrelated explicit-intent filters
    # silently keep items such as generic education/public-service-adjacent majors.
    positive_match = _item_matches_any_positive_intent(item, planning_state, include_career_types=False)
    negative_match = _item_matches_any_negative_intent(item, planning_state)
    for target in targets:
        if target == "aligned" and positive_match and not negative_match:
            return True
        if target == "unrelated" and not positive_match and not negative_match:
            return True
        if target == "conflict" and negative_match:
            return True
    return False


def _ordered_item_matches_remove_scope(
    item: dict[str, Any],
    action: PlanAtomicAction | None,
    batch: str | None = "01",
    planning_state: dict[str, Any] | None = None,
) -> bool:
    if action is None:
        return False
    major_targets = _remove_scope_major_names(action, batch)
    school_targets = _remove_scope_school_names(action, batch)
    region_targets = _remove_scope_region_names(action)
    program_type_targets = _remove_scope_program_types(action)
    min_tuition = _remove_scope_min_tuition(action)
    max_tuition = _remove_scope_max_tuition(action)
    preference_fit_targets = _remove_scope_preference_fit(action)
    tier_values = _filter_scope_values(action, "tier")
    if tier_values:
        item_tier = str(item.get("tier") or "").strip()
        if item_tier not in set(tier_values):
            return False
    if major_targets and not _matching_major_scope_records(item, major_targets, batch):
        return False
    if school_targets and not any(_compact_match_contains(item.get("schoolName"), target) for target in school_targets):
        return False
    if region_targets:
        region_fields = [
            item.get("province"),
            item.get("provinceName"),
            item.get("city"),
            item.get("cityName"),
            item.get("schoolProvince"),
            item.get("schoolCity"),
            item.get("schoolName"),
        ]
        if not any(
            _compact_match_contains(field, target)
            for target in region_targets
            for field in region_fields
            ):
            return False
    if program_type_targets and not _program_type_matches_item(item, program_type_targets):
        return False
    if not _tuition_scope_matches_item(item, min_tuition=min_tuition, max_tuition=max_tuition):
        return False
    if not _preference_fit_matches_item(item, preference_fit_targets, planning_state):
        return False
    return bool(
        major_targets
        or school_targets
        or region_targets
        or program_type_targets
        or tier_values
        or min_tuition is not None
        or max_tuition is not None
        or preference_fit_targets
    )


def _ordered_item_scope_volunteer_ids(
    item: dict[str, Any],
    action: PlanAtomicAction | None,
    batch: str | None = "01",
) -> list[str]:
    major_targets = _remove_scope_major_names(action, batch)
    records = _matching_major_scope_records(item, major_targets, batch) if major_targets else []
    ids: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        record_id = str(record.get("volunteerId") or record.get("id") or "").strip()
        if record_id and record_id not in ids:
            ids.append(record_id)
    if ids:
        return ids
    volunteer_id = str(item.get("volunteerId") or "").strip()
    if volunteer_id:
        return [volunteer_id]
    return ids


def _resolve_ordered_ids_by_remove_scope(
    items: list[dict[str, Any]],
    action: PlanAtomicAction | None,
    batch: str | None = "01",
    planning_state: dict[str, Any] | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    matched_items: list[dict[str, Any]] = []
    ids: list[str] = []
    for item in items:
        if not _ordered_item_matches_remove_scope(item, action, batch, planning_state):
            continue
        matched_ids = _ordered_item_scope_volunteer_ids(item, action, batch)
        if not matched_ids:
            continue
        matched_items.append(item)
        for volunteer_id in matched_ids:
            if volunteer_id not in ids:
                ids.append(volunteer_id)
    return ids, matched_items


def _remove_scope_label(action: PlanAtomicAction | None, batch: str | None = "01") -> str:
    parts: list[str] = []
    major_names_by_level = _remove_scope_major_names_by_level(action, batch)
    school_names = _remove_scope_school_names(action, batch)
    region_names = _remove_scope_region_names(action)
    program_types = _remove_scope_program_types(action)
    min_tuition = _remove_scope_min_tuition(action)
    max_tuition = _remove_scope_max_tuition(action)
    preference_fit = _remove_scope_preference_fit(action)
    if major_names_by_level.get("negative_level3"):
        parts.append("具体专业：" + "、".join(major_names_by_level["negative_level3"][:3]))
    if major_names_by_level.get("negative_level2"):
        parts.append("专业类：" + "、".join(major_names_by_level["negative_level2"][:3]))
    if major_names_by_level.get("negative_level1"):
        parts.append("专业门类：" + "、".join(major_names_by_level["negative_level1"][:3]))
    if school_names:
        parts.append("院校：" + "、".join(school_names[:3]))
    if region_names:
        parts.append("地域：" + "、".join(region_names[:3]))
    if program_types:
        parts.append("项目类型：" + "、".join(program_types[:3]))
    if min_tuition is not None:
        parts.append(f"学费不少于{min_tuition}元/年")
    if max_tuition is not None:
        parts.append(f"学费不超过{max_tuition}元/年")
    if "unrelated" in preference_fit:
        parts.append("与已确认意向不匹配")
    if "conflict" in preference_fit:
        parts.append("命中已排除要求")
    if "aligned" in preference_fit:
        parts.append("贴近已确认意向")
    return "；".join(parts) or "指定范围"


def _build_constraint_intent_update_from_remove_scope(
    action: PlanAtomicAction | None,
    batch: str | None = "01",
) -> dict[str, Any]:
    selected: list[dict[str, Any]] = []
    major_names_by_level = _remove_scope_major_names_by_level(action, batch)
    school_names = _remove_scope_school_names(action, batch)
    region_names_by_level = _remove_scope_region_names_by_level(action)
    program_types = _remove_scope_program_types(action)
    if major_names_by_level:
        selected.append({"major_intents": major_names_by_level})
    if school_names:
        selected.append({"school_intents": {"negative_colleges": school_names}})
    city_intents: dict[str, list[str]] = {}
    if region_names_by_level.get("province"):
        city_intents["negative_province"] = region_names_by_level["province"]
    if region_names_by_level.get("city"):
        city_intents["negative_city"] = region_names_by_level["city"]
    if city_intents:
        selected.append({"city_intents": city_intents})
    if program_types:
        selected.append({"physical_constraints": {"special_limits": [f"不接受{value}" for value in program_types]}})
    if not selected:
        return {}
    return {
        "selected": selected,
        "intentMode": "constraint",
        "summary": _remove_scope_label(action, batch),
    }


def _build_remove_units_preview_summary_from_scope(
    items: list[dict[str, Any]],
    matched_items: list[dict[str, Any]],
    volunteer_ids: list[str],
    action: PlanAtomicAction | None,
    batch: str | None = "01",
    *,
    include_intent_update: bool = False,
) -> str:
    scope_label = _remove_scope_label(action, batch)
    unit_count = _count_ordered_units_for_ids(items, volunteer_ids)
    examples = "；".join(_ordered_item_display_name(item) for item in matched_items[:5])
    example_text = f"示例：{examples}。" if examples else ""
    intent_text = (
        "同时把这条要求写入后续报考参考，用于刷新推荐系数和专家优选；"
        if include_intent_update
        else ""
    )
    return (
        f"已在当前方案里定位到“{scope_label}”相关的 {len(volunteer_ids)} 条志愿"
        f"（约 {unit_count} 个专业组）。{example_text}"
        f"确认后会把这些志愿移出当前方案，{intent_text}"
        "执行后会重新审查方案。"
    )


def _build_move_unit_preview_summary_from_items(
    items: list[dict[str, Any]],
    volunteer_ids: list[str],
    target_position: int | None,
    *,
    context_text: str = "",
) -> tuple[str | None, dict[str, Any]]:
    if target_position is None or not volunteer_ids:
        return None, {}
    item_by_id = {str(item.get("volunteerId") or "").strip(): item for item in items if str(item.get("volunteerId") or "").strip()}
    source_item = item_by_id.get(str(volunteer_ids[0] or "").strip())
    if not source_item:
        return None, {}
    target_position, target_facts = _resolve_tier_local_first_target_position(
        items,
        source_item,
        target_position,
        context_text,
    )
    if target_position is None:
        return None, {}
    current_position_raw = source_item.get("position")
    try:
        current_position = int(current_position_raw)
    except (TypeError, ValueError):
        current_position = None
    display_name = _ordered_item_display_name(source_item)
    current_text = f"当前第 {current_position} 位" if current_position is not None else "当前已在方案中"
    target_text = f"第 {int(target_position)} 位"
    if current_position == int(target_position):
        summary = f"{display_name} 已经在{target_text}，本次不需要移动。"
    else:
        summary = (
            "预览如下：\n\n"
            f"- 志愿：{display_name}\n"
            f"- 当前位置：{current_text}\n"
            f"- 目标位置：{target_text}\n"
            "- 影响：确认后会调整方案顺序，其余志愿会按顺序衔接，并需要重新关注审查状态。\n\n"
            "需要你确认后才会执行。"
        )
    return summary, {
        "source_volunteer_id": str(volunteer_ids[0]),
        "source_display_name": display_name,
        "source_position": current_position,
        "target_position": int(target_position),
        **target_facts,
    }


def _normalize_tier_filter(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text in {"保底", "保档", "保"}:
        return "保"
    if text in {"冲刺", "冲档", "冲"}:
        return "冲"
    if text in {"稳妥", "稳档", "稳"}:
        return "稳"
    return text


def _ordered_item_position_value(item: dict[str, Any]) -> int | None:
    try:
        value = int(item.get("_visible_position") or item.get("position") or item.get("rank") or item.get("order"))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _text_mentions_tier_local_first(text: str, tier: str) -> bool:
    compact = _compact_ref_text(text)
    if not compact:
        return False
    normalized_tier = _normalize_tier_filter(tier)
    tier_markers = {
        "保": ("保", "保底", "保档", "保区", "兜底"),
        "稳": ("稳", "稳妥", "稳档", "稳区"),
        "冲": ("冲", "冲刺", "冲档", "冲区"),
    }.get(normalized_tier, (normalized_tier,))
    if not any(_compact_ref_text(marker) in compact for marker in tier_markers if marker):
        return False
    return any(marker in compact for marker in ("第一位", "第1位", "第一", "置顶", "最前"))


def _resolve_tier_local_first_target_position(
    ordered_items: list[dict[str, Any]],
    source_item: dict[str, Any],
    requested_target_position: int | None,
    context_text: str,
) -> tuple[int | None, dict[str, Any]]:
    if requested_target_position != 1:
        return requested_target_position, {}
    tier = _normalize_tier_filter(source_item.get("tier") or source_item.get("bucket"))
    if not tier or not _text_mentions_tier_local_first(context_text, tier):
        return requested_target_position, {}
    tier_positions = [
        position
        for item in ordered_items
        if _normalize_tier_filter(item.get("tier") or item.get("bucket")) == tier
        for position in [_ordered_item_position_value(item)]
        if position is not None
    ]
    if not tier_positions:
        return requested_target_position, {}
    target_position = min(tier_positions)
    return target_position, {
        "selector": "tier_local_first_target_position",
        "tier": tier,
        "original_target_position": requested_target_position,
        "target_position": target_position,
    }


_TIER_LOCAL_HIGH_RANK_ALIASES = {"max", "highest", "top", "best", "最高", "最大", "靠前", "最靠前"}
_TIER_LOCAL_LOW_RANK_ALIASES = {"min", "lowest", "bottom", "worst", "最低", "最小", "靠后", "最靠后"}


def _normalize_tier_local_selection_mode(sort_field: str, rank: str) -> str:
    normalized = str(rank or "").strip().lower()
    if normalized in _TIER_LOCAL_HIGH_RANK_ALIASES:
        return "min" if sort_field == "schoolRank" else "max"
    if normalized in _TIER_LOCAL_LOW_RANK_ALIASES:
        return "max" if sort_field == "schoolRank" else "min"
    return ""


def _tier_local_rank_label(sort_field: str, rank: str) -> str:
    mode = _normalize_tier_local_selection_mode(sort_field, rank)
    if sort_field == "schoolRank":
        return "最靠前" if mode == "min" else "最靠后"
    return "最高" if mode == "max" else "最低"


def _resolve_tier_local_target_position(
    positioned: list[tuple[dict[str, Any], int | None]],
    filters: dict[str, Any],
) -> tuple[int | None, dict[str, Any], str | None]:
    positions = sorted({position for _item, position in positioned if position is not None})
    if not positions:
        return None, {}, "missing_tier_positions"

    target_ordinal_raw = (
        filters.get("targetOrdinal")
        or filters.get("target_ordinal")
        or filters.get("ordinal")
    )
    target_rank = str(
        filters.get("targetRank")
        or filters.get("target_rank")
        or filters.get("target")
        or ""
    ).strip().lower()

    if target_ordinal_raw not in (None, ""):
        try:
            target_ordinal = int(target_ordinal_raw)
        except (TypeError, ValueError):
            target_ordinal = 0
        if target_ordinal <= 0:
            return None, {"target_ordinal": target_ordinal_raw}, "invalid_target_ordinal"
        if target_ordinal > len(positions):
            return None, {"target_ordinal": target_ordinal, "tier_position_count": len(positions)}, "target_ordinal_out_of_range"
        return positions[target_ordinal - 1], {"target_ordinal": target_ordinal}, None

    if target_rank in {"last", "tail", "bottom", "最后", "末位"}:
        return positions[-1], {"target_rank": "last"}, None
    return positions[0], {"target_rank": "first", "target_ordinal": 1}, None


def _resolve_tier_local_move_selector(
    ordered_items: list[dict[str, Any]],
    filters: dict[str, Any],
) -> tuple[dict[str, Any] | None, int | None, dict[str, Any], str | None]:
    tier = _normalize_tier_filter(
        filters.get("tier") or filters.get("target_tier") or filters.get("targetTier")
    )
    sort_field = _SORT_FIELD_ALIASES.get(
        str(filters.get("sort_field") or filters.get("sortField") or filters.get("sort_by") or filters.get("sortBy") or "").strip(),
        "",
    )
    rank = str(filters.get("rank") or filters.get("rankMode") or filters.get("select") or "").strip().lower()
    selection_mode = _normalize_tier_local_selection_mode(sort_field, rank)
    if not tier or not sort_field or not selection_mode:
        return None, None, {}, None

    matched = [
        item
        for item in ordered_items
        if _normalize_tier_filter(item.get("tier") or item.get("bucket") or _unit_tier_label(item)) == tier
    ]
    if not matched:
        return None, None, {"tier": tier, "matched_count": 0}, f"当前方案里暂时没有{tier}档志愿，无法生成调序预览。"

    positioned = [
        (item, _ordered_item_position_value(item))
        for item in matched
    ]
    target_position, target_facts, target_error = _resolve_tier_local_target_position(positioned, filters)
    if target_position is None:
        facts = {"tier": tier, "matched_count": len(matched), **target_facts}
        if target_error == "target_ordinal_out_of_range":
            return None, None, facts, f"当前{tier}档只有 {target_facts.get('tier_position_count', 0)} 个可排序项，无法移动到档内第 {target_facts.get('target_ordinal')} 位。"
        return None, None, {"tier": tier, "matched_count": len(matched)}, f"当前{tier}档志愿缺少稳定位置，无法生成调序预览。"

    valued: list[tuple[dict[str, Any], float, int]] = []
    for item in matched:
        value = _item_sort_value(item, sort_field)
        if value is None:
            continue
        position = _ordered_item_position_value(item) or 10**9
        valued.append((item, value, position))
    if not valued:
        label = _SORT_FIELD_LABELS.get(sort_field, sort_field)
        return (
            None,
            None,
            {"tier": tier, "matched_count": len(matched), "sort_field": sort_field},
            f"当前{tier}档志愿缺少可比较的{label}数据，无法生成调序预览。",
        )

    if selection_mode == "max":
        selected, selected_value, _selected_position = max(valued, key=lambda row: (row[1], -row[2]))
    else:
        selected, selected_value, _selected_position = min(valued, key=lambda row: (row[1], row[2]))
    volunteer_id = str(selected.get("volunteerId") or "").strip()
    sort_label = _SORT_FIELD_LABELS.get(sort_field, sort_field)
    rank_label = _tier_local_rank_label(sort_field, rank)
    facts = {
        "selector": f"tier_local_{selection_mode}_{sort_field}",
        "tier": tier,
        "matched_count": len(matched),
        "sort_field": sort_field,
        "sort_label": sort_label,
        "rank": rank,
        "rank_label": rank_label,
        "source_volunteer_id": volunteer_id,
        "source_display_name": _ordered_item_display_name(selected),
        "source_position": _ordered_item_position_value(selected),
        "target_position": target_position,
        "sort_value": selected_value,
        **target_facts,
    }
    if sort_field == "admissionRatio":
        facts["admission_ratio"] = selected_value
    return selected, target_position, facts, None


def _build_resolved_apply_payload(
    plan_model: PlanActionPlan,
    *,
    volunteer_ids: list[str] | None = None,
    unit_ids: list[str] | None = None,
    action_family: str | None = None,
    target_position: int | None = None,
) -> dict[str, Any]:
    """Keep preview-resolved execution targets stable for the confirm turn."""
    if not plan_model.atomic_actions:
        return {}
    resolved_actions: list[dict[str, Any]] = []
    for index, action in enumerate(plan_model.atomic_actions):
        action_data = action.model_dump()
        if index == 0:
            if action_family:
                action_data["action_type"] = action_family
            if volunteer_ids is not None:
                action_data["volunteer_ids"] = [str(item) for item in volunteer_ids if str(item or "").strip()]
            if unit_ids is not None:
                action_data["unit_ids"] = [str(item) for item in unit_ids if str(item or "").strip()]
            if target_position is not None:
                action_data["target_position"] = int(target_position)
        resolved_actions.append(action_data)
    payload = {"atomic_actions": resolved_actions} if resolved_actions else {}
    if action_family:
        payload["action_family"] = action_family
    return payload


def _candidate_ref_resolution_message(missing_text: str) -> str:
    return (
        f"我理解你想加入的是：{missing_text}。但我还没有在候选里唯一匹配到这条志愿。"
        "为避免误加，请先在候选列表里点选要加入方案的志愿，"
        "或补充专业组、城市、学校全称等信息后我再给你确认。"
    )


def _candidate_ref_display_text(refs: list[str], resolved_count: int) -> str:
    natural_refs = [
        str(ref or "").strip()
        for ref in refs
        if str(ref or "").strip() and any(ord(char) > 127 for char in str(ref or ""))
    ]
    if not natural_refs:
        return ""
    display_refs = "、".join(natural_refs[:3])
    if len(natural_refs) > 3:
        display_refs += f"等 {resolved_count} 个"
    return display_refs


def _split_school_major_ref(value: Any) -> tuple[str, str]:
    text = str(value or "").strip()
    if not text:
        return "", ""
    for separator in ("的", ".", "。", "-", "－", "—", "、", ",", "，", ": ", "："):
        if separator not in text:
            continue
        left, right = text.split(separator, 1)
        left = left.strip()
        right = right.strip()
        if left and right and any(token in left for token in ("大学", "学院", "学校")):
            return left, _major_base_name(right)
    match = re.match(r"(.+?(?:大学|学院|学校)(?:[（(][^()（）]*[)）])?)(.+)", text)
    if match:
        return match.group(1).strip(), _major_base_name(match.group(2).strip())
    return "", ""


async def _candidate_state_items(ctx: RunContext[RequestContext]) -> list[dict[str, Any]]:
    session_id = ctx.deps.sessionid
    try:
        state_result = await _get_planning_state_request(session_id)
        state = state_result.get("data") or {} if state_result.get("code") == 0 else {}
        raw_items = ((state.get("candidatePoolState") or {}).get("items") or [])
        return [item for item in raw_items if isinstance(item, dict)]
    except Exception:
        logger.warning("load candidate state for ref resolution failed: session_id=%s", session_id, exc_info=True)
    return []


def _resolve_candidate_ref_from_items(text: str, items: list[dict[str, Any]]) -> str | None:
    exact_candidates: dict[str, list[str]] = {}
    compact_candidates: dict[str, list[str]] = {}
    compact_labels: list[tuple[str, str]] = []
    for item in items:
        volunteer_id = str(item.get("volunteerId") or "").strip()
        if not volunteer_id:
            continue
        for label in _ordered_item_labels(item):
            exact_candidates.setdefault(label, [])
            if volunteer_id not in exact_candidates[label]:
                exact_candidates[label].append(volunteer_id)
            compact_label = _compact_ref_text(label)
            compact_candidates.setdefault(compact_label, [])
            if volunteer_id not in compact_candidates[compact_label]:
                compact_candidates[compact_label].append(volunteer_id)
            compact_labels.append((compact_label, volunteer_id))

    exact_matches = exact_candidates.get(text) or []
    if len(exact_matches) == 1:
        return exact_matches[0]
    compact_ref = _compact_ref_text(text)
    compact_matches = compact_candidates.get(compact_ref) or []
    if len(compact_matches) == 1:
        return compact_matches[0]
    if compact_ref:
        partial_matches = [
            candidate_id
            for label, candidate_id in compact_labels
            if compact_ref in label or label in compact_ref
        ]
        unique_matches = list(dict.fromkeys(partial_matches))
        if len(unique_matches) == 1:
            return unique_matches[0]
    return None


async def _candidate_items_for_ref(
    ctx: RunContext[RequestContext],
    ref: str,
    *,
    state_items: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    session_id = ctx.deps.sessionid
    loaded_state_items = state_items if state_items is not None else await _candidate_state_items(ctx)
    school_keyword, major_keyword = _split_school_major_ref(ref)
    school_keywords = [school_keyword] if school_keyword else []
    major_keywords = [major_keyword] if major_keyword else []
    if not school_keywords and not major_keywords:
        ref_resolution = resolve_school_major_ref(ref, getattr(ctx.deps, "batch", None) or "01")
        if ref_resolution.can_query:
            school_keywords = ref_resolution.school_keywords
            major_keywords = ref_resolution.major_keywords

    if not school_keywords and not major_keywords:
        return loaded_state_items

    queried_items: list[dict[str, Any]] = []
    try:
        query_result = await _query_planning_candidate_pool_request(
            _DEFAULT_TENANT_ID,
            session_id,
            school_keywords=school_keywords,
            major_keywords=major_keywords,
            page=1,
            page_size=100,
        )
        if query_result.get("code") == 0:
            queried_items = [
                item
                for item in ((query_result.get("data") or {}).get("items") or [])
                if isinstance(item, dict)
            ]
    except Exception:
        logger.warning("query candidate pool for ref resolution failed: session_id=%s ref=%s", session_id, ref, exc_info=True)

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in [*queried_items, *loaded_state_items]:
        volunteer_id = str(item.get("volunteerId") or "").strip()
        key = volunteer_id or f"{item.get('schoolName')}::{item.get('majorName')}::{item.get('position')}"
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


async def _resolve_candidate_volunteer_refs(
    ctx: RunContext[RequestContext],
    refs: list[str],
) -> tuple[list[str], list[str]]:
    if not refs:
        return [], []
    resolved: list[str] = []
    missing: list[str] = []
    for ref in refs:
        text = str(ref or "").strip()
        if not text:
            continue
        if _VOLUNTEER_ID_LIKE_RE.match(text) and not any(token in text for token in ("大学", "学院", "学校", "专业")):
            if text not in resolved:
                resolved.append(text)
            continue

        state_items = await _candidate_state_items(ctx)
        volunteer_id = _resolve_candidate_ref_from_items(text, state_items)
        if not volunteer_id:
            items = await _candidate_items_for_ref(ctx, text, state_items=state_items)
            volunteer_id = _resolve_candidate_ref_from_items(text, items)
        if volunteer_id:
            if volunteer_id not in resolved:
                resolved.append(volunteer_id)
        else:
            missing.append(text)
    return resolved, missing


def _find_review_issue_by_code(review_issues: list[dict[str, Any]], code: str | None) -> dict[str, Any] | None:
    normalized = str(code or "").strip()
    if not normalized:
        return None
    for issue in review_issues:
        if str(issue.get("code") or "").strip() == normalized:
            return issue
    return None


async def _load_current_review_issue_scopes(
    ctx: RunContext[RequestContext],
    *,
    include_affected_ids: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    session_id = ctx.deps.sessionid
    try:
        state_result, ordered_result = await asyncio.gather(
            _get_planning_state_request(session_id),
            _get_planning_ordered_plan_request(session_id),
        )
    except Exception:
        logger.warning("load current review issue scopes failed: session_id=%s", session_id, exc_info=True)
        return [], [], {}

    planning_state = (state_result.get("data") or {}) if _internal_mutation_ok(state_result) else {}
    ordered_items = (ordered_result.get("data") or {}).get("items") or [] if ordered_result.get("code") == 0 else []
    if not ordered_items:
        ordered_items = ((planning_state.get("orderedPlanState") or {}).get("items") or [])
    if not ordered_items:
        ordered_items = get_working_plan_items(planning_state)
    review_checks = (((planning_state.get("reviewState") or {}).get("checks") or []))
    review_issues = build_review_issue_scopes(
        review_checks,
        ordered_items,
        include_affected_ids=include_affected_ids,
    )
    return review_issues, ordered_items, planning_state


def _review_issue_target_from_plan(
    plan_model: PlanActionPlan,
    review_issues: list[dict[str, Any]],
):
    atomic = plan_model.atomic_actions[0] if plan_model.atomic_actions else None
    if atomic and atomic.review_issue_target is not None:
        return atomic.review_issue_target
    return None


def _resolve_review_issue_scope_ids(
    issue: dict[str, Any] | None,
    ordered_items: list[dict[str, Any]],
    resolved_ids: list[str],
    review_issue_target: Any | None,
) -> list[str]:
    if not issue:
        return resolved_ids
    affected_ids = [
        str(volunteer_id or "").strip()
        for volunteer_id in (issue.get("affected_volunteer_ids") or [])
        if str(volunteer_id or "").strip()
    ]
    if not affected_ids:
        return resolved_ids

    scope_mode = str(getattr(review_issue_target, "scope_mode", "") or "full_issue").strip() or "full_issue"
    if scope_mode == "full_issue":
        return [
            str(item.get("volunteerId") or "").strip()
            for item in ordered_items
            if str(item.get("volunteerId") or "").strip() in set(affected_ids)
        ]

    if scope_mode == "explicit_items":
        return resolved_ids

    narrowed_filters = getattr(review_issue_target, "narrowed_filters", {}) or {}
    selected_unit_ids: set[str] = set()
    resolved_id_set = set(resolved_ids)
    for item in ordered_items:
        volunteer_id = str(item.get("volunteerId") or "").strip()
        if volunteer_id in resolved_id_set:
            selected_unit_ids.add(_ordered_unit_id_for_item(item))
            continue
        school_keyword = str(narrowed_filters.get("school_keyword") or "").strip()
        major_keyword = str(narrowed_filters.get("major_keyword") or "").strip()
        province_keyword = str(narrowed_filters.get("province_keyword") or "").strip()
        tier = str(narrowed_filters.get("tier") or "").strip()
        if school_keyword and school_keyword not in str(item.get("schoolName") or ""):
            continue
        if major_keyword and major_keyword not in str(item.get("majorName") or ""):
            continue
        if province_keyword and province_keyword not in str(item.get("provinceName") or ""):
            continue
        if tier and tier != str(item.get("tier") or ""):
            continue
        if school_keyword or major_keyword or province_keyword or tier:
            selected_unit_ids.add(_ordered_unit_id_for_item(item))
    if not selected_unit_ids:
        return resolved_ids
    return [
        str(item.get("volunteerId") or "").strip()
        for item in ordered_items
        if str(item.get("volunteerId") or "").strip() in set(affected_ids)
        and _ordered_unit_id_for_item(item) in selected_unit_ids
    ]


def _ordered_item_matches_review_issue_fallback(item: dict[str, Any], issue_code: str) -> bool:
    """Fallback only for structured review issue targets with missing affected ids."""
    normalized_code = str(issue_code or "").strip()
    if normalized_code == "cooperative_program":
        return _program_type_matches_item(item, ["中外合作", "中外合作办学", "合作办学", "国际项目"])
    if normalized_code == "high_tuition":
        tuition = _ordered_item_tuition_per_year(item)
        return tuition is not None and tuition > 20000
    return False


def _resolve_review_issue_scope_ids_from_ordered_items(
    issue: dict[str, Any] | None,
    ordered_items: list[dict[str, Any]],
    review_issue_target: Any | None,
) -> list[str]:
    if not issue or not review_issue_target:
        return []
    if not _is_item_review_issue(issue):
        return []
    issue_code = str(getattr(review_issue_target, "code", None) or issue.get("code") or "").strip()
    if not issue_code:
        return []
    if str(getattr(review_issue_target, "scope_mode", "") or "full_issue").strip() != "full_issue":
        return []
    resolved: list[str] = []
    for item in ordered_items:
        volunteer_id = str(item.get("volunteerId") or "").strip()
        if not volunteer_id or volunteer_id in resolved:
            continue
        if _ordered_item_matches_review_issue_fallback(item, issue_code):
            resolved.append(volunteer_id)
    return resolved


async def _resolve_review_issue_action_scope(
    ctx: RunContext[RequestContext],
    plan_model: PlanActionPlan,
    resolved_ids: list[str],
) -> tuple[list[str], list[dict[str, Any]], Any | None, dict[str, Any] | None]:
    review_issues, ordered_items, _ = await _load_current_review_issue_scopes(ctx)
    review_issue_target = _review_issue_target_from_plan(plan_model, review_issues)
    if review_issue_target is None:
        return resolved_ids, ordered_items, None, None
    issue = _find_review_issue_by_code(review_issues, getattr(review_issue_target, "code", None))
    if issue is None:
        try:
            await run_planning_review(ctx)
            review_issues, ordered_items, _ = await _load_current_review_issue_scopes(ctx)
            issue = _find_review_issue_by_code(review_issues, getattr(review_issue_target, "code", None))
        except Exception:
            logger.warning(
                "refresh review issue scopes failed: session_id=%s issue_code=%s",
                ctx.deps.sessionid,
                getattr(review_issue_target, "code", None),
                exc_info=True,
            )
    if issue is None:
        rule = get_review_issue_rule(getattr(review_issue_target, "code", None))
        if rule is not None:
            issue = {
                "code": rule.code,
                "label": rule.label,
                "scope_kind": rule.scope_kind,
                "default_action_family": rule.default_action_family,
                "affected_volunteer_ids": resolved_ids,
            }
        else:
            return resolved_ids, ordered_items, review_issue_target, None
    effective_ids = _resolve_review_issue_scope_ids(issue, ordered_items, resolved_ids, review_issue_target)
    if not effective_ids:
        effective_ids = _resolve_review_issue_scope_ids_from_ordered_items(
            issue,
            ordered_items,
            review_issue_target,
        )
    return effective_ids or resolved_ids, ordered_items, review_issue_target, issue


def _structural_review_issue_guidance(issue: dict[str, Any]) -> tuple[str, list[str]]:
    label = str(issue.get("label") or issue.get("code") or "当前问题").strip()
    default_action_family = str(issue.get("default_action_family") or "").strip()
    if default_action_family == "preview_fix_proposal":
        return (
            f"{label}属于结构性问题，不适合直接按样例删志愿。更合适的是先看调整预览，再决定是否应用。",
            ["如果用户想继续处理，先看后端统一修复预览，再确认是否执行。"],
        )
    return (
        f"{label}属于结构性问题，受影响条目主要用于定位上下文，不应直接当作删除清单。更合适的是先看调整建议。",
            ["如果用户想继续处理，先查看调整建议，再决定是否执行局部改动。"],
        )


def _is_item_review_issue(issue: dict[str, Any] | None) -> bool:
    return str((issue or {}).get("scope_kind") or "").strip() in {
        "item_removal",
        "item_replacement",
    }


def _is_replacement_first_review_issue(issue: dict[str, Any] | None) -> bool:
    return str((issue or {}).get("scope_kind") or "").strip() == "item_replacement"


async def _build_broad_replace_review_issue_preview(
    ctx: RunContext[RequestContext],
    plan_model: PlanActionPlan,
) -> PlanExecutionResult | None:
    if plan_model.stage not in {"analyze", "preview"} or plan_model.action_family != "replace_units":
        return None
    atomic = plan_model.atomic_actions[0] if plan_model.atomic_actions else None
    if atomic is None or _has_filter_selection_scope(atomic.filters):
        return None
    refs = list(atomic.volunteer_ids or [])
    resolved_ids, _ = await _resolve_ordered_volunteer_refs(ctx, refs)
    effective_ids, ordered_items, review_issue_target, review_issue = await _resolve_review_issue_action_scope(
        ctx,
        plan_model,
        resolved_ids,
    )
    if review_issue is None or review_issue_target is None or not _is_item_review_issue(review_issue):
        return None

    unit_count = _count_ordered_units_for_ids(ordered_items, effective_ids)
    issue_label = str(review_issue.get("label") or review_issue.get("code") or "这类问题").strip()
    if not effective_ids:
        return PlanExecutionResult(
            applied=False,
            action_family=plan_model.action_family,
            stage="analyze",
            result_kind="no_change",
            context_summary=plan_model.context_summary,
            summary=f"当前方案里没有定位到需要按{issue_label}处理的志愿，因此这次不生成替换预览，也不会改动方案。",
            reply_focus=["no_matching_review_issue_items"],
            reply_strategy="direct_reply",
            next_step_hints=[
                "明确说明当前方案没有命中该审查问题范围；不要提示用户确认替换，也不要声称已生成预览。",
            ],
            facts=_facts_with_planning_version(
                {
                    "review_issue_code": getattr(review_issue_target, "code", None),
                    "review_issue_label": issue_label,
                    "affected_unit_count": 0,
                    "affected_volunteer_count": 0,
                },
                ctx,
            ),
        )
    if _is_replacement_first_review_issue(review_issue):
        summary = _review_issue_replacement_scope_guidance(issue_label, unit_count, len(effective_ids))
        return PlanExecutionResult(
            applied=False,
            action_family=plan_model.action_family,
            stage="analyze",
            result_kind="preview_only",
            context_summary=plan_model.context_summary,
            summary=summary,
            reply_focus=["review_issue_guidance", "replacement_scope_required"],
            reply_strategy="continue_model",
            next_step_hints=[
                "面向用户说明影响范围和下一步选择，不要生成可执行确认内容。",
                "不要使用内部状态词；说明需要先看处理建议或补充替换方向。",
            ],
            facts=_facts_with_planning_version(
                {
                    "review_issue_code": getattr(review_issue_target, "code", None),
                    "review_issue_label": issue_label,
                    "affected_unit_count": unit_count,
                    "affected_volunteer_count": len(effective_ids),
                },
                ctx,
            ),
        )

    summary = (
        f"我先定位了当前方案里的{issue_label}：共 {unit_count} 个专业组，涉及 {len(effective_ids)} 条志愿。"
        "如果你确认要处理，可以先按这一批问题项生成移出预览；如果只想处理某个学校、专业组或位置，也可以直接说明范围。"
    )
    return PlanExecutionResult(
        applied=False,
        action_family=plan_model.action_family,
        stage=plan_model.stage,
        result_kind="preview_only",
        context_summary=plan_model.context_summary,
        summary=_with_confirmation_hint(summary),
        reply_focus=["preview_only", "review_issue_batch_scope"],
        next_step_hints=["只说明影响范围和确认边界；不要生成空替换预览。"],
        facts=_facts_with_planning_version(
            {
                "review_issue_code": getattr(review_issue_target, "code", None),
                "review_issue_label": issue_label,
                "affected_unit_count": unit_count,
                "affected_volunteer_count": len(effective_ids),
            },
            ctx,
        ),
    )


def _summary_total(summary: dict[str, Any] | None) -> int:
    summary = summary or {}
    return summary.get("unitTotal") or summary.get("total") or 0


def _internal_mutation_ok(result: Any) -> bool:
    """Normalize backend mutation response success flags.

    Planning endpoints do not all use the same envelope: older ones return
    `{code: 0}`, while newer ones may return `{success: true}`. An explicit
    error always wins; an unknown dict envelope is treated as success for
    backward compatibility with existing internal-client wrappers.
    """
    if not isinstance(result, dict):
        return False
    if result.get("error"):
        return False
    if "code" in result:
        try:
            return int(result.get("code") or 0) == 0
        except Exception:
            return False
    if "success" in result:
        return bool(result.get("success"))
    return True


def _append_intent_relation_summary(base_text: str, planning_state: dict[str, Any] | None) -> str:
    ordered_state = (planning_state or {}).get("orderedPlanState") or {}
    working_state = get_working_plan_state(planning_state)
    ordered_items = ordered_state.get("items") or []
    working_items = working_state.get("items") or []
    plan_items = ordered_items or working_items
    plan_summary = (ordered_state.get("summary") or {}) if ordered_items else (working_state.get("summary") or {})
    relation_lines = _build_plan_intent_relation_lines(
        planning_state,
        plan_items,
        plan_summary=plan_summary,
        include_position=True,
    )
    if not relation_lines:
        return base_text
    return base_text + " " + " ".join(line.removeprefix("- ").strip() for line in relation_lines[:2] if line)


def _replace_no_add_clarification(add_summary: str) -> str:
    text = str(add_summary)
    if (
        "没有找到可加入方案的候选志愿" not in text
        and "当前方案数量没有增加" not in text
    ):
        return ""
    clarification = (
        "说明一下：这里的总数统计的是当前工作台里的方案项数量。"
        "如果这次只是从某个专业组里移出了一个组内专业，方案项总数可能不变，"
        "但该专业志愿本身已经移出，而且这次没有补入新的候选志愿。"
    )
    if "当前方案数量没有增加" in text:
        return (
            clarification
            + "这次虽然匹配到了候选，但如果候选本来就在方案里，或者没有被后端采纳成新增项，"
            "总数也不会上涨。"
        )
    return clarification


def _candidate_selection_capacity(query_result: dict[str, Any]) -> int:
    available_count = int(query_result.get("available_count") or 0)
    if available_count > 0:
        return available_count
    total_units = int(query_result.get("total_units") or 0)
    total_entries = int(query_result.get("total_entries") or 0)
    if query_result.get("dedupe_by_unit") and total_units > 0:
        return total_units
    return total_units or total_entries


def _add_units_filter_limit(filters: dict[str, Any]) -> int:
    try:
        return max(1, min(int(filters.get("limit") or 3), 100))
    except (TypeError, ValueError):
        return 3


def _add_units_filter_summary(filters: dict[str, Any]) -> str:
    parts: list[str] = []
    tier = str(filters.get("tier") or "").strip()
    province = str(filters.get("province_keyword") or "").strip()
    school = str(filters.get("school_keyword") or "").strip()
    major = str(filters.get("major_keyword") or "").strip()
    school_tags = _parse_filter_list(filters.get("school_tags"))
    major_tags = _parse_filter_list(filters.get("major_tags"))
    if tier:
        parts.append(f"{tier}档")
    if province:
        parts.append(province)
    if school:
        parts.append(school)
    if major:
        parts.append(major)
    if school_tags:
        parts.append("、".join(school_tags[:3]))
    if major_tags:
        parts.append("、".join(major_tags[:3]))
    return "、".join(part for part in parts if part) or "当前条件"


async def _build_add_units_filter_preview(
    ctx: RunContext[RequestContext],
    plan_model: PlanActionPlan,
    filters: dict[str, Any],
) -> PlanExecutionResult:
    limit = _add_units_filter_limit(filters)
    query_result = await _query_candidate_pool_selection(
        ctx,
        tier=filters.get("tier") or None,
        province_keyword=filters.get("province_keyword") or None,
        school_keyword=filters.get("school_keyword") or None,
        major_keyword=filters.get("major_keyword") or None,
        school_tags=_parse_filter_list(filters.get("school_tags")),
        major_tags=_parse_filter_list(filters.get("major_tags")),
        limit=limit,
        exclude_current_units=True,
    )
    scope_text = _add_units_filter_summary(filters)
    if query_result.get("error"):
        return PlanExecutionResult(
            applied=False,
            action_family="add_units",
            stage=plan_model.stage,
            result_kind="error",
            context_summary=plan_model.context_summary,
            summary=f"当前还没法按“{scope_text}”确认可加入候选，因为候选池查询失败。请稍后重试，或先缩小候选范围。",
            reply_focus=["candidate_query_failed"],
            reply_strategy="direct_blocking",
            next_step_hints=["候选池查询失败；不要生成确认卡，也不要声称已找到可加入志愿。"],
            facts=_facts_with_planning_version(
                {"candidate_filter_scope": scope_text, "candidate_query_error": query_result.get("error")},
                ctx,
            ),
        )
    volunteer_ids = [
        str(item or "").strip()
        for item in (query_result.get("candidate_volunteer_ids") or [])
        if str(item or "").strip()
    ]
    facts = {
        "candidate_filter_scope": scope_text,
        "candidate_available_count": int(query_result.get("available_count") or 0),
        "candidate_total_entries": int(query_result.get("total_entries") or 0),
        "candidate_total_units": int(query_result.get("total_units") or 0),
    }
    if not volunteer_ids:
        summary = f"当前按“{scope_text}”没有找到可加入方案的候选志愿，所以这次不生成加入预览，也不会改动方案。"
        return PlanExecutionResult(
            applied=False,
            action_family="add_units",
            stage=plan_model.stage,
            result_kind="no_change",
            context_summary=plan_model.context_summary,
            state_summary=summary,
            summary=summary,
            reply_focus=["no_candidates", "needs_candidate_selection"],
            reply_strategy="direct_reply",
            next_step_hints=["当前结构化条件没有候选命中；不要生成确认卡。"],
            facts=_facts_with_planning_version(facts, ctx),
        )
    preview_summary = (
        f"已按“{scope_text}”在候选池里定位到 {len(volunteer_ids)} 个可加入方案的候选。"
        "确认后会加入当前方案，并同步刷新方案顺序和审查状态。"
    )
    facts.update(
        {
            "resolved_candidate_ids": volunteer_ids,
            "resolved_apply_payload": _build_resolved_apply_payload(
                plan_model,
                volunteer_ids=volunteer_ids,
            ),
        }
    )
    return PlanExecutionResult(
        applied=False,
        action_family="add_units",
        stage=plan_model.stage,
        result_kind="preview_only",
        context_summary=plan_model.context_summary,
        summary=_with_confirmation_hint(preview_summary),
        reply_focus=["preview_only", "confirmation_required"],
        next_step_hints=["先说明候选筛选范围和将加入数量；用户确认后再执行加入方案。"],
        facts=_facts_with_planning_version(facts, ctx),
    )


async def _preview_or_block_replace_by_candidate_capacity(
    ctx: RunContext[RequestContext],
    *,
    plan_model: PlanActionPlan,
    ordered_items: list[dict[str, Any]],
    effective_ids: list[str],
    filters: dict[str, Any],
    review_issue_target: Any = None,
    apply_message_prefix: str = "这次我先不执行替换",
    preview_message_prefix: str = "我先拦一下",
) -> PlanExecutionResult | None:
    replacement_count = _count_ordered_units_for_ids(ordered_items, effective_ids) or len(effective_ids)
    replacement_query = await _query_candidate_pool_selection(
        ctx,
        tier=filters.get("tier") or None,
        province_keyword=filters.get("province_keyword") or None,
        school_keyword=filters.get("school_keyword") or None,
        major_keyword=filters.get("major_keyword") or None,
        school_tags=_parse_filter_list(filters.get("school_tags")),
        major_tags=_parse_filter_list(filters.get("major_tags")),
        limit=replacement_count,
        exclude_current_units=True,
        replacement_issue_code=getattr(review_issue_target, "code", None),
    )
    if replacement_query.get("error"):
        return PlanExecutionResult(
            applied=False,
            action_family=plan_model.action_family,
            stage="analyze",
            result_kind="error",
            context_summary=plan_model.context_summary,
            summary="当前还没法确认这次替换，因为补入候选范围还没查清楚。请稍后重试，或先缩小补入范围。",
            reply_focus=["replacement_scope_unresolved"],
            next_step_hints=["先确认补入范围里确实有可用候选，再生成可执行的替换预览。"],
        )
    available_count = _candidate_selection_capacity(replacement_query)
    if available_count < replacement_count:
        prefix = apply_message_prefix if plan_model.stage == "apply" else preview_message_prefix
        return PlanExecutionResult(
            applied=False,
            action_family=plan_model.action_family,
            stage="analyze",
            result_kind="error",
            context_summary=plan_model.context_summary,
            summary=(
                f"{prefix}：当前按这组条件只找到 {available_count} 个可补入候选，"
                f"不足以替掉这批志愿后仍保持 {replacement_count} 个名额不减少。"
                "如果现在执行，会出现先删后补不回来。"
                "你可以放宽补入范围，或者先改成只移出再补齐，再执行替换。"
            ),
            reply_focus=["replacement_scope_insufficient"],
            next_step_hints=["先放宽补入范围，或改成先移出再补齐，再执行替换。"],
        )
    return None


def _should_preflight_replace_capacity(
    plan_model: PlanActionPlan,
    effective_ids: list[str],
    review_issue_target: Any = None,
) -> bool:
    if review_issue_target is not None:
        return True
    atomic = plan_model.atomic_actions[0] if plan_model.atomic_actions else None
    filters = getattr(atomic, "filters", {}) if atomic is not None else {}
    if not isinstance(filters, dict):
        return False
    return str(
        filters.get("preserve_count")
        or filters.get("preserveCount")
        or filters.get("require_capacity_check")
        or filters.get("requireCapacityCheck")
        or ""
    ).strip().lower() in {"1", "true", "yes", "y"}


def _candidate_item_tuition_per_year(item: dict[str, Any]) -> int | None:
    raw_value = item.get("tuitionPerYear")
    if raw_value is not None and str(raw_value).strip():
        try:
            return int(raw_value)
        except (TypeError, ValueError):
            logger.debug("invalid candidate tuitionPerYear: %s", raw_value)

    text_sources: list[str] = [
        str(item.get("majorName") or ""),
        *(str(value or "") for value in (item.get("majorPlanTags") or [])),
        *(str(value or "") for value in (item.get("reasonCodes") or [])),
    ]
    for text in text_sources:
        match = _TUITION_PER_YEAR_RE.search(text)
        if not match:
            continue
        try:
            return int(match.group(1))
        except (TypeError, ValueError):
            logger.debug("failed to parse candidate tuition from text: %s", text)
    return None


def _candidate_matches_replacement_issue_filter(item: dict[str, Any], replacement_issue_code: str | None) -> bool:
    normalized_issue_code = str(replacement_issue_code or "").strip()
    if not normalized_issue_code:
        return True
    if normalized_issue_code == "high_tuition":
        tuition_per_year = _candidate_item_tuition_per_year(item)
        return tuition_per_year is None or tuition_per_year <= 20000
    return True



async def _get_planning_state_with_latest_profile(session_id: str) -> dict[str, Any]:
    state_result, profile_result = await asyncio.gather(
        _get_planning_state_request(session_id),
        _get_user_profile_request(session_id),
        return_exceptions=True,
    )
    if isinstance(state_result, Exception):
        logger.warning("get planning state with latest profile failed: session_id=%s state_error=%s", session_id, state_result)
        return {}
    planning_state = state_result.get("data") or {} if state_result.get("code") == 0 else {}
    if isinstance(profile_result, Exception):
        logger.warning("get planning state with latest profile failed: session_id=%s profile_error=%s", session_id, profile_result)
        return planning_state
    user_profile = (((profile_result or {}).get("data") or {}).get("userprofile") or {})
    return merge_planning_state_with_user_profile(planning_state, user_profile)


async def _refresh_review_and_state(session_id: str) -> dict[str, Any] | None:
    try:
        await _run_planning_review_request(_DEFAULT_TENANT_ID, session_id)
    except Exception:
        logger.exception("refresh review failed after plan execution: session_id=%s", session_id)
    try:
        planning_state = await _get_planning_state_with_latest_profile(session_id)
        if planning_state:
            return planning_state
    except Exception:
        logger.exception("refresh planning state failed after plan execution: session_id=%s", session_id)
    return None


async def _query_candidate_pool_selection(
    ctx: RunContext[RequestContext],
    *,
    tier: str | None = None,
    province_keyword: str | None = None,
    school_keyword: str | None = None,
    major_keyword: str | None = None,
    school_tags: list[str] | None = None,
    major_tags: list[str] | None = None,
    limit: int = 3,
    exclude_current_units: bool = False,
    replacement_issue_code: str | None = None,
) -> dict[str, Any]:
    session_id = ctx.deps.sessionid
    batch = getattr(ctx.deps, "batch", None) or "01"
    desired_count = max(1, min(int(limit or 0), 100))
    page_size = max(20, min(max(desired_count * 4, desired_count), 100))
    await _generate_planning_candidate_pool_request(_DEFAULT_TENANT_ID, session_id, True)

    selected_ids: list[str] = []
    seen_unit_ids: set[str] = set()
    existing_volunteer_ids: set[str] = set()
    existing_unit_ids: set[str] = set()
    total_entries = 0
    total_units = 0
    dedupe_by_unit = False
    page = 1

    if exclude_current_units:
        for loader in (_get_planning_ordered_plan_request, _get_working_plan_request):
            try:
                result = await loader(session_id)
            except Exception:
                logger.warning("load current plan items for candidate exclusion failed: session_id=%s", session_id, exc_info=True)
                continue
            items = (result.get("data") or {}).get("items") or [] if result.get("code") == 0 else []
            for item in items:
                volunteer_id = str(item.get("volunteerId") or "").strip()
                if volunteer_id:
                    existing_volunteer_ids.add(volunteer_id)
                unit_id = _ordered_unit_id_for_item(item)
                if unit_id:
                    existing_unit_ids.add(unit_id)

    while True:
        result = await _query_planning_candidate_pool_request(
            _DEFAULT_TENANT_ID,
            session_id,
            tiers=[tier] if tier else [],
            province_names=_normalize_keywords(province_keyword),
            school_keywords=_normalize_keywords(school_keyword),
            major_keywords=_derive_candidate_major_keywords(major_keyword, major_tags, batch),
            school_tags=school_tags or [],
            major_tags=major_tags or [],
            page=page,
            page_size=page_size,
        )
        if result.get("code") != 0:
            return {
                "error": "查询候选池失败，请稍后重试。",
                "candidate_volunteer_ids": [],
                "total_entries": 0,
                "total_units": 0,
                "dedupe_by_unit": False,
            }

        data = result.get("data") or {}
        items = data.get("items") or []
        if page == 1:
            total_entries = int(data.get("total") or 0)
            total_units = int(data.get("totalUnitCount") or 0)
            dedupe_by_unit = total_units > 0 and total_units < total_entries

        for item in items:
            if not _candidate_matches_replacement_issue_filter(item, replacement_issue_code):
                continue
            volunteer_id = str(item.get("volunteerId") or "").strip()
            if not volunteer_id or volunteer_id in existing_volunteer_ids:
                continue
            unit_id = _ordered_unit_id_for_item(item)
            if exclude_current_units and unit_id and unit_id in existing_unit_ids:
                continue
            if dedupe_by_unit:
                if unit_id in seen_unit_ids:
                    continue
                seen_unit_ids.add(unit_id)
            selected_ids.append(volunteer_id)
            if len(selected_ids) >= desired_count:
                break

        if len(selected_ids) >= desired_count:
            break
        if len(items) < page_size:
            break
        page += 1

    return {
        "error": "",
        "candidate_volunteer_ids": selected_ids[:desired_count],
        "total_entries": total_entries,
        "total_units": total_units,
        "dedupe_by_unit": dedupe_by_unit,
        "available_count": len(selected_ids),
    }


async def _apply_candidate_volunteer_ids_into_plan(
    ctx: RunContext[RequestContext],
    volunteer_ids: list[str],
) -> str:
    session_id = ctx.deps.sessionid
    try:
        before_ordered_total = 0
        before_working_total = 0
        try:
            before_state_result = await _get_planning_state_request(session_id)
            before_state = before_state_result.get("data") or {} if before_state_result.get("code") == 0 else {}
            before_ordered_total = _summary_total(((before_state.get("orderedPlanState") or {}).get("summary") or {}))
            before_working_total = _summary_total(get_working_plan_summary(before_state))
        except Exception:
            logger.warning("failed to read planning totals before selecting candidates: session_id=%s", session_id, exc_info=True)

        select_result = await _select_working_plan_items_request(
            _DEFAULT_TENANT_ID,
            session_id,
            volunteer_ids,
        )
        if select_result.get("code") != 0:
            return "加入方案失败，请稍后重试。"

        ordered_result = await _generate_planning_ordered_plan_request(
            _DEFAULT_TENANT_ID,
            session_id,
            True,
            True,
        )
        if ordered_result.get("code") != 0:
            return "已加入方案，但刷新当前方案排序失败，请稍后重试。"

        latest_state = await _refresh_review_and_state(session_id) or (ordered_result.get("data") or {})
        ordered_summary = ((latest_state.get("orderedPlanState") or {}).get("summary") or {})
        working_summary = get_working_plan_summary(latest_state)
        current_total = _summary_total(ordered_summary)
        working_total = _summary_total(working_summary)
        target_total = ordered_summary.get("targetUnitCount") or ordered_summary.get("targetCount") or 0
        review_summary = ((latest_state.get("reviewState") or {}).get("summary") or {})
        ordered_increase = max(0, current_total - before_ordered_total) if before_ordered_total else 0
        working_increase = max(0, working_total - before_working_total) if before_working_total else 0
        if ordered_increase > 0:
            lead_text = f"已按你的要求加入 {ordered_increase} 个候选志愿，并同步更新当前方案。"
        elif working_increase > 0:
            lead_text = (
                f"已把 {working_increase} 个候选志愿加入方案，但当前排序方案数量仍是 "
                f"{current_total}/{target_total or current_total}，需要继续检查是否已被排序采纳。"
            )
        elif before_ordered_total:
            lead_text = (
                f"按条件匹配到 {len(volunteer_ids)} 个候选志愿，但当前方案数量没有增加，"
                "可能这些志愿已在方案中，或没有被后端接受为新增。"
            )
        else:
            lead_text = f"已按你的要求处理 {len(volunteer_ids)} 个候选志愿，并同步刷新当前方案。"
        base_text = (
            f"{lead_text} 当前方案 {current_total}/{target_total or current_total}，"
            f"风险 {review_summary.get('riskCount', 0)} 项，提醒 {review_summary.get('warnCount', 0)} 项。"
            " 你可以继续查看方案，再决定是否继续调整。"
        )
        return _append_intent_relation_summary(base_text, latest_state)
    except Exception:
        logger.exception("_apply_candidate_volunteer_ids_into_plan failed: session_id=%s", session_id)
        return "按条件选取候选志愿时发生错误，请稍后重试。"


async def _select_candidates_by_filters_into_plan(
    ctx: RunContext[RequestContext],
    *,
    tier: str | None = None,
    province_keyword: str | None = None,
    school_keyword: str | None = None,
    major_keyword: str | None = None,
    school_tags: list[str] | None = None,
    major_tags: list[str] | None = None,
    limit: int = 3,
    exclude_current_units: bool = True,
    replacement_issue_code: str | None = None,
) -> str:
    session_id = ctx.deps.sessionid
    limit = max(1, min(limit, 100))
    logger.info(
        "_select_candidates_by_filters_into_plan: session_id=%s tier=%s province=%s school=%s major=%s limit=%s",
        session_id, tier, province_keyword, school_keyword, major_keyword, limit,
    )
    try:
        query_result = await _query_candidate_pool_selection(
            ctx,
            tier=tier,
            province_keyword=province_keyword,
            school_keyword=school_keyword,
            major_keyword=major_keyword,
            school_tags=school_tags,
            major_tags=major_tags,
            limit=limit,
            exclude_current_units=exclude_current_units,
            replacement_issue_code=replacement_issue_code,
        )
        if query_result.get("error"):
            return str(query_result.get("error"))
        volunteer_ids = list(query_result.get("candidate_volunteer_ids") or [])
        if not volunteer_ids:
            return "当前条件下没有找到可加入方案的候选志愿。"
        return await _apply_candidate_volunteer_ids_into_plan(ctx, volunteer_ids)
    except Exception:
        logger.exception("_select_candidates_by_filters_into_plan failed: session_id=%s", session_id)
        return "按条件选取候选志愿时发生错误，请稍后重试。"


async def _regenerate_ordered_plan(ctx: RunContext[RequestContext]) -> str:
    session_id = ctx.deps.sessionid
    logger.info("_regenerate_ordered_plan: session_id=%s", session_id)
    try:
        result = await _generate_planning_ordered_plan_request(_DEFAULT_TENANT_ID, session_id, True, True)
        if result.get("code") != 0:
            return "重排排序失败，请稍后重试。"
        latest_state = await _refresh_review_and_state(session_id) or (result.get("data") or {})
        total_summary = ((latest_state.get("orderedPlanState") or {}).get("summary") or {})
        total = _summary_total(total_summary)
        target_total = total_summary.get("targetUnitCount") or total_summary.get("targetCount") or 0
        review_summary = ((latest_state.get("reviewState") or {}).get("summary") or {})
        base_text = (
            f"系统已重新生成当前排序方案，当前排序志愿共 {total}/{target_total or total}。"
            f" 当前风险 {review_summary.get('riskCount', 0)} 项，提醒 {review_summary.get('warnCount', 0)} 项。"
            " 你可以继续看现在的排序结果，再决定是否移动到指定位置或上下微调。"
        )
        return _append_intent_relation_summary(base_text, latest_state)
    except Exception:
        logger.exception("_regenerate_ordered_plan failed: session_id=%s", session_id)
        return "重新生成排序时发生错误，请稍后重试。"


_SORT_FIELD_ALIASES = {
    "admissionRatio": "admissionRatio",
    "admission_ratio": "admissionRatio",
    "admission_probability": "admissionRatio",
    "admissionProbability": "admissionRatio",
    "录取率": "admissionRatio",
    "schoolRank": "schoolRank",
    "school_rank": "schoolRank",
    "schoolLevel": "schoolRank",
    "school_level": "schoolRank",
    "院校层次": "schoolRank",
    "学校层次": "schoolRank",
    "院校排名": "schoolRank",
    "finalScore": "finalScore",
    "final_score": "finalScore",
    "recommendationScore": "finalScore",
    "recommendation_score": "finalScore",
    "推荐系数": "finalScore",
}

_SORT_FIELD_LABELS = {
    "admissionRatio": "录取率",
    "schoolRank": "院校层次",
    "finalScore": "推荐系数",
}

_SORT_FIELD_DIRECTIONS = {
    "admissionRatio": "升序（录取率低的冲档机会会更靠前，录取率高的保底机会会更靠后）",
    "schoolRank": "升序（院校排名/层次更靠前的机会优先）",
    "finalScore": "降序（系统综合推荐系数更高的机会优先）",
}

def _infer_ordered_sort_field(plan_model: PlanActionPlan, *, default: str = "admissionRatio") -> str:
    atomic = plan_model.atomic_actions[0] if plan_model.atomic_actions else None
    if atomic:
        for key in ("sort_field", "sortField", "field"):
            raw_value = str((atomic.filters or {}).get(key) or "").strip()
            if raw_value in _SORT_FIELD_ALIASES:
                return _SORT_FIELD_ALIASES[raw_value]
    return default


_SORT_VALUE_ALIASES: dict[str, tuple[str, ...]] = {
    "admissionRatio": (
        "admissionRatio",
        "schoolEnrollRatio",
        "enrollRatio",
        "admission_ratio",
        "school_enroll_ratio",
        "schoolEnrollRatioStr",
        "enrollRatioStr",
    ),
    "schoolRank": (
        "schoolRank",
        "schoolRanking",
        "school_rank",
        "gaotuRank",
        "rank",
    ),
    "finalScore": (
        "finalScore",
        "recommendationScore",
        "recommendScore",
        "recommend_score",
        "recommendation_score",
        "comboScore",
        "score",
    ),
}

_ORDERED_SORT_KEY_ORDER: dict[str, tuple[tuple[str, bool], ...]] = {
    "admissionRatio": (("admissionRatio", False), ("schoolRank", False), ("finalScore", True)),
    "schoolRank": (("schoolRank", False), ("admissionRatio", False), ("finalScore", True)),
    "finalScore": (("finalScore", True), ("admissionRatio", False), ("schoolRank", False)),
}


def _coerce_sort_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text in {"-", "--", "未知", "暂无", "null", "None"}:
        return None
    normalized = text.replace(",", "").replace("％", "%").replace("%", "")
    match = re.search(r"-?\d+(?:\.\d+)?", normalized)
    if not match:
        return None
    try:
        return float(match.group(0))
    except (TypeError, ValueError):
        return None


def _mapping_sort_value(item: dict[str, Any] | None, sort_field: str) -> float | None:
    if not isinstance(item, dict):
        return None
    for key in _SORT_VALUE_ALIASES.get(sort_field, (sort_field,)):
        value = _coerce_sort_number(item.get(key))
        if value is not None:
            return value
    return None


def _candidate_sort_lookup(planning_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    raw_items = ((planning_state.get("candidatePoolState") or {}).get("items") or []) if isinstance(planning_state, dict) else []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        volunteer_id = str(item.get("volunteerId") or "").strip()
        if volunteer_id and volunteer_id not in candidates:
            candidates[volunteer_id] = item
    return candidates


def _item_sort_value(
    item: dict[str, Any],
    sort_field: str,
    candidate_by_volunteer_id: dict[str, dict[str, Any]] | None = None,
) -> float | None:
    value = _mapping_sort_value(item, sort_field)
    if value is not None:
        return value
    candidate_by_volunteer_id = candidate_by_volunteer_id or {}
    volunteer_id = str(item.get("volunteerId") or "").strip()
    if volunteer_id:
        value = _mapping_sort_value(candidate_by_volunteer_id.get(volunteer_id), sort_field)
        if value is not None:
            return value

    nested_values: list[float] = []
    for nested in item.get("majorItems") or item.get("selectedMajors") or item.get("items") or []:
        if not isinstance(nested, dict):
            continue
        value = _mapping_sort_value(nested, sort_field)
        if value is None:
            nested_volunteer_id = str(nested.get("volunteerId") or "").strip()
            value = _mapping_sort_value(candidate_by_volunteer_id.get(nested_volunteer_id), sort_field)
        if value is not None:
            nested_values.append(value)
    if not nested_values:
        return None
    if sort_field == "finalScore":
        return max(nested_values)
    return min(nested_values)


def _ordered_sort_preview_items(ordered_state: dict[str, Any]) -> list[dict[str, Any]]:
    units = [item for item in (ordered_state.get("units") or []) if isinstance(item, dict)]
    if units:
        return units
    return [item for item in (ordered_state.get("items") or []) if isinstance(item, dict)]


def _sort_preview_position(item: dict[str, Any]) -> int:
    try:
        return int(item.get("position") or 0)
    except (TypeError, ValueError):
        return 0


def _sort_preview_text_key(item: dict[str, Any]) -> str:
    return str(
        item.get("unitId")
        or item.get("volunteerId")
        or item.get("schoolName")
        or item.get("majorName")
        or ""
    )


def _ordered_sort_preview_key(
    item: dict[str, Any],
    sort_field: str,
    candidate_by_volunteer_id: dict[str, dict[str, Any]],
) -> tuple[Any, ...]:
    key_parts: list[Any] = []
    for field, descending in _ORDERED_SORT_KEY_ORDER.get(sort_field, _ORDERED_SORT_KEY_ORDER["admissionRatio"]):
        value = _item_sort_value(item, field, candidate_by_volunteer_id)
        key_parts.append(value is None)
        key_parts.append((-value if descending else value) if value is not None else 0)
    key_parts.append(_sort_preview_position(item))
    key_parts.append(_sort_preview_text_key(item))
    return tuple(key_parts)


def _format_sort_value(value: float | None, sort_field: str) -> str:
    if value is None:
        return "-"
    if sort_field == "admissionRatio":
        return f"{int(value)}%" if value.is_integer() else f"{value:.1f}%"
    if value.is_integer():
        return str(int(value))
    return f"{value:.1f}"


def _format_sort_preview_item(
    item: dict[str, Any],
    sort_field: str,
    candidate_by_volunteer_id: dict[str, dict[str, Any]] | None = None,
) -> str:
    school_name = str(item.get("schoolName") or "未知院校").strip()
    major_name = str(item.get("majorName") or "").strip()
    tier = str(item.get("tier") or "未知").strip()
    position = item.get("position")
    value = _format_sort_value(_item_sort_value(item, sort_field, candidate_by_volunteer_id), sort_field)
    name = f"{school_name}-{major_name}" if major_name else school_name
    suffix = f"{tier}，{_SORT_FIELD_LABELS.get(sort_field, sort_field)}{value}"
    if position is not None:
        suffix += f"，原第{position}位"
    return f"{name}（{suffix}）"


async def _build_sort_ordered_plan_preview_summary(
    ctx: RunContext[RequestContext],
    plan_model: PlanActionPlan,
) -> tuple[str, dict[str, Any]]:
    session_id = ctx.deps.sessionid
    sort_field = _infer_ordered_sort_field(plan_model)
    sort_label = _SORT_FIELD_LABELS.get(sort_field, "录取率")
    direction = _SORT_FIELD_DIRECTIONS.get(sort_field, "按系统默认方向")
    try:
        state_resp = await _get_planning_state_request(session_id)
        planning_state = (state_resp or {}).get("data") or {}
    except Exception:
        logger.warning("build sort preview failed to load planning state: session_id=%s", session_id, exc_info=True)
        planning_state = {}

    ordered_state = (planning_state.get("orderedPlanState") or {}) if isinstance(planning_state, dict) else {}
    ordered_summary = ordered_state.get("summary") or {}
    items = _ordered_sort_preview_items(ordered_state)
    candidate_by_volunteer_id = _candidate_sort_lookup(planning_state if isinstance(planning_state, dict) else {})
    total = _summary_total(ordered_summary) or len(items)
    target_total = ordered_summary.get("targetUnitCount") or ordered_summary.get("targetCount") or total
    tier_counts = ordered_summary.get("unitTierCounts") or ordered_summary.get("tierCounts") or {}
    tier_text = ""
    if isinstance(tier_counts, dict) and tier_counts:
        tier_text = f"；当前冲稳保为：冲{tier_counts.get('冲', 0)} / 稳{tier_counts.get('稳', 0)} / 保{tier_counts.get('保', 0)}"

    sorted_items = sorted(
        items,
        key=lambda item: _ordered_sort_preview_key(item, sort_field, candidate_by_volunteer_id),
    )

    top_examples = [
        _format_sort_preview_item(item, sort_field, candidate_by_volunteer_id)
        for item in sorted_items[:5]
    ]
    example_text = "；".join(top_examples)
    if example_text:
        example_text = f"。按这个口径预览，前几项大致会变成：{example_text}"
    summary = (
        f"会按{sort_label}重新排序当前方案，排序方向是{direction}。"
        f"当前方案共 {total}/{target_total or total} 个{tier_text}{example_text}。"
        "这会实际改变方案顺序和导出顺序，并让审查状态进入待重新审查。"
    )
    return summary, {
        "sort_field": sort_field,
        "sort_label": sort_label,
        "sort_direction": direction,
        "total": total,
        "target_total": target_total or total,
        "tier_counts": tier_counts if isinstance(tier_counts, dict) else {},
        "top_examples": top_examples,
    }


async def _sort_ordered_plan(ctx: RunContext[RequestContext], plan_model: PlanActionPlan) -> tuple[bool, str]:
    session_id = ctx.deps.sessionid
    sort_field = _infer_ordered_sort_field(plan_model)
    sort_label = _SORT_FIELD_LABELS.get(sort_field, "录取率")
    logger.info("_sort_ordered_plan: session_id=%s sort_field=%s", session_id, sort_field)
    try:
        result = await _sort_planning_ordered_plan_request(_DEFAULT_TENANT_ID, session_id, sort_field)
        if not _internal_mutation_ok(result):
            return False, f"按{sort_label}排序失败，请稍后重试。"
        latest_state = await _get_planning_state_with_latest_profile(session_id) or (result.get("data") or {})
        ordered_summary = ((latest_state.get("orderedPlanState") or {}).get("summary") or {})
        total = _summary_total(ordered_summary)
        target_total = ordered_summary.get("targetUnitCount") or ordered_summary.get("targetCount") or 0
        base_text = (
            f"已按{sort_label}重新排序当前方案，当前方案共 {total}/{target_total or total} 个。"
            "排序会影响导出顺序，方案已经进入待重新审查状态，建议再点一次审查看看风险是否变化。"
        )
        return True, _append_intent_relation_summary(base_text, latest_state)
    except Exception:
        logger.exception("_sort_ordered_plan failed: session_id=%s sort_field=%s", session_id, sort_field)
        return False, f"按{sort_label}排序时发生错误，请稍后重试。"


async def _move_ordered_unit(ctx: RunContext[RequestContext], plan_model: PlanActionPlan) -> tuple[bool, str]:
    session_id = ctx.deps.sessionid
    resolve_started_at = time.monotonic()
    unit_ids = await _resolve_ordered_unit_ids(ctx, plan_model)
    resolve_duration_ms = int((time.monotonic() - resolve_started_at) * 1000)
    action = _first_atomic_action(plan_model)
    target_position = getattr(action, "target_position", None)
    if not unit_ids:
        logger.info(
            "move_ordered_unit skipped: session_id=%s reason=missing_unit_ids resolveDurationMs=%s",
            session_id,
            resolve_duration_ms,
        )
        return False, "还没有定位到要移动的专业组。请说明专业组名称或第几个专业组。"
    if target_position is None:
        logger.info(
            "move_ordered_unit skipped: session_id=%s reason=missing_target resolveDurationMs=%s unitIds=%s",
            session_id,
            resolve_duration_ms,
            unit_ids,
        )
        return False, "还没有定位到目标位置。请说明要移动到第几位。"
    try:
        backend_started_at = time.monotonic()
        result = await _move_planning_ordered_plan_unit_request(
            _DEFAULT_TENANT_ID,
            session_id,
            unit_ids[0],
            int(target_position),
        )
        backend_duration_ms = int((time.monotonic() - backend_started_at) * 1000)
        logger.info(
            "move_ordered_unit backend finished: session_id=%s unitId=%s targetPosition=%s resolveDurationMs=%s backendDurationMs=%s ok=%s",
            session_id,
            unit_ids[0],
            int(target_position),
            resolve_duration_ms,
            backend_duration_ms,
            _internal_mutation_ok(result),
        )
        if not _internal_mutation_ok(result):
            return False, "专业组移动失败，请稍后重试或改用页面操作。"
        data = (result or {}).get("data") or {}
        return True, str(data.get("message") or result.get("message") or f"已将该专业组移动到第 {target_position} 位，方案顺序已更新。")
    except Exception:
        logger.exception("_move_ordered_unit failed: session_id=%s unit_ids=%s target=%s", session_id, unit_ids, target_position)
        return False, "专业组移动失败，请稍后重试或改用页面操作。"


async def _remove_ordered_units(ctx: RunContext[RequestContext], plan_model: PlanActionPlan) -> tuple[bool, str]:
    session_id = ctx.deps.sessionid
    resolve_started_at = time.monotonic()
    unit_ids = await _resolve_ordered_unit_ids(ctx, plan_model)
    resolve_duration_ms = int((time.monotonic() - resolve_started_at) * 1000)
    if not unit_ids:
        logger.info(
            "remove_ordered_units skipped: session_id=%s reason=missing_unit_ids resolveDurationMs=%s",
            session_id,
            resolve_duration_ms,
        )
        return False, "还没有定位到要删除的专业组。请说明专业组名称或第几个专业组。"
    try:
        backend_started_at = time.monotonic()
        result = await _remove_planning_ordered_plan_units_request(
            _DEFAULT_TENANT_ID,
            session_id,
            unit_ids,
        )
        backend_duration_ms = int((time.monotonic() - backend_started_at) * 1000)
        logger.info(
            "remove_ordered_units backend finished: session_id=%s unitIds=%s resolveDurationMs=%s backendDurationMs=%s ok=%s",
            session_id,
            unit_ids,
            resolve_duration_ms,
            backend_duration_ms,
            _internal_mutation_ok(result),
        )
        if not _internal_mutation_ok(result):
            return False, "专业组删除失败，请稍后重试或改用页面操作。"
        data = (result or {}).get("data") or {}
        return True, str(data.get("message") or result.get("message") or f"已从方案中删除 {len(unit_ids)} 个专业组，方案顺序已更新。")
    except Exception:
        logger.exception("_remove_ordered_units failed: session_id=%s unit_ids=%s", session_id, unit_ids)
        return False, "专业组删除失败，请稍后重试或改用页面操作。"



async def _post_process_handler_result(
    ctx: RunContext[RequestContext],
    plan_model: PlanActionPlan,
    result: PlanExecutionResult,
) -> PlanExecutionResult:
    """对 handler 返回的结果做后处理：review rerun、intent effect、summary 组合。"""
    review_rerun = False
    review_summary = result.review_summary or ""
    reply_focus = list(result.reply_focus)
    next_step_hints = list(result.next_step_hints)
    workspace_targets = list(result.workspace_refresh_targets)

    if result.result_kind == "error" and not next_step_hints:
        next_step_hints.append("操作失败，不要重复尝试同一操作。向用户解释情况并提供替代建议。")

    if (
        result.result_kind != "error"
        and result.applied
        and plan_model.should_rerun_review
        and plan_model.action_family != "review_plan"
    ):
        review_summary = await run_planning_review(ctx)
        review_rerun = _review_rerun_succeeded(review_summary)
        if "review_result" not in reply_focus:
            reply_focus.append("review_rerun")
        if not next_step_hints:
            next_step_hints.append("如果用户继续追问风险，可以结合复审结果继续解释。")
        if review_rerun and "review" not in workspace_targets:
            workspace_targets.append("review")
        elif not review_rerun:
            workspace_targets = [target for target in workspace_targets if target != "review"]

    summary = result.state_summary or result.summary
    if review_summary and review_summary != summary:
        summary = f"{summary}\n\n复审结果：\n{review_summary}"

    intent_effect = "unchanged" if plan_model.intent_relation == "unknown" else (
        "conflicted" if plan_model.intent_relation == "conflict" else "strengthened"
    )

    return PlanExecutionResult(
        applied=result.applied,
        action_family=result.action_family,
        stage=result.stage,
        result_kind=result.result_kind,
        executed_actions=result.executed_actions,
        affected_volunteer_ids=result.affected_volunteer_ids,
        workspace_refresh_targets=workspace_targets,
        review_rerun=review_rerun,
        intent_effect=intent_effect,
        context_summary=result.context_summary,
        review_summary=review_summary,
        state_summary=result.state_summary,
        summary=summary,
        reply_focus=reply_focus,
        reply_strategy=result.reply_strategy,
        next_step_hints=next_step_hints,
        facts=result.facts,
    )


async def _dispatch_registered_handler(
    ctx: RunContext[RequestContext],
    plan_model: PlanActionPlan,
) -> PlanExecutionResult | None:
    from app.handlers import HANDLER_REGISTRY

    handler = HANDLER_REGISTRY.get(plan_model.action_family)
    if handler is None:
        return None
    result = await handler(ctx, plan_model)
    return await _post_process_handler_result(ctx, plan_model, result)


async def _execute_plan_action_model(
    ctx: RunContext[RequestContext],
    plan_model: PlanActionPlan,
) -> PlanExecutionResult:
    _hydrate_replace_filters_from_profile(ctx, plan_model)

    broad_replace_review_issue_preview = await _build_broad_replace_review_issue_preview(ctx, plan_model)
    if broad_replace_review_issue_preview is not None:
        return broad_replace_review_issue_preview

    missing_inputs = list(plan_model.missing_inputs or [])
    if not _is_downgraded_unconfirmed_apply(plan_model):
        for item in _execution_missing_inputs(ctx, plan_model):
            if item not in missing_inputs:
                missing_inputs.append(item)
    if missing_inputs and not _is_downgraded_unconfirmed_apply(plan_model):
        reply_focus = [
            str(item or "").strip()
            for item in list(plan_model.reply_focus or [])
            if str(item or "").strip()
        ]
        if "missing_inputs" not in reply_focus:
            reply_focus.append("missing_inputs")
        return PlanExecutionResult(
            applied=False,
            action_family=plan_model.action_family,
            stage=plan_model.stage,
            result_kind="error",
            context_summary=plan_model.context_summary,
            summary=_execution_missing_inputs_message(plan_model, missing_inputs),
            reply_focus=reply_focus,
            reply_strategy="direct_blocking",
            next_step_hints=["先补齐缺失输入，再继续执行当前方案动作。"],
            facts={
                "requested_reply_focus": list(plan_model.reply_focus or []),
            },
        )

    if plan_model.action_family in _READONLY_HANDLER_ACTION_FAMILIES:
        handler_result = await _dispatch_registered_handler(ctx, plan_model)
        if handler_result is not None:
            return handler_result

    if not _allows_mutating_apply(ctx, plan_model):
        preview_summary = plan_model.preview_summary
        preview_facts: dict[str, Any] = {}
        if plan_model.action_family == "move_ordered_unit":
            resolved_summary, resolved_facts = await _build_move_ordered_unit_preview_summary(ctx, plan_model)
            if resolved_summary:
                if str(resolved_facts.get("position_resolution") or "").strip() in {
                    "already_at_target",
                    "tier_selector_no_match",
                    "missing_target_position",
                }:
                    return PlanExecutionResult(
                        applied=False,
                        action_family=plan_model.action_family,
                        stage=plan_model.stage,
                        result_kind="no_change",
                        context_summary=plan_model.context_summary,
                        summary=resolved_summary,
                        state_summary=resolved_summary,
                        reply_focus=["already_at_target"] if str(resolved_facts.get("position_resolution") or "").strip() == "already_at_target" else ["no_matching_ordered_items"],
                        reply_strategy="direct_reply",
                        next_step_hints=["当前排序项已经在目标位置或缺少可移动目标；不要生成确认卡，也不要提示已移动。"],
                        facts=_facts_with_planning_version(resolved_facts, ctx),
                    )
                preview_summary = resolved_summary
                preview_facts = resolved_facts
        elif plan_model.action_family == "remove_ordered_unit":
            resolved_summary, resolved_facts = await _build_remove_ordered_unit_preview_summary(ctx, plan_model)
            if resolved_summary:
                if str(resolved_facts.get("position_resolution") or "").strip() in {"range_empty", "missing_source_position"}:
                    return PlanExecutionResult(
                        applied=False,
                        action_family=plan_model.action_family,
                        stage=plan_model.stage,
                        result_kind="no_change",
                        context_summary=plan_model.context_summary,
                        summary=resolved_summary,
                        state_summary=resolved_summary,
                        reply_focus=["no_matching_ordered_items"],
                        reply_strategy="direct_reply",
                        next_step_hints=["当前范围没有命中可删除项；不要生成确认卡，也不要提示需要确认执行。"],
                        facts=_facts_with_planning_version(resolved_facts, ctx),
                    )
                preview_summary = resolved_summary
                preview_facts = resolved_facts
        elif plan_model.action_family in {"remove_units", "move_unit", "replace_units"}:
            atomic = plan_model.atomic_actions[0] if plan_model.atomic_actions else None
            refs = list(atomic.volunteer_ids or []) if atomic else []
            resolved_ids, _ = await _resolve_ordered_volunteer_refs(ctx, refs)
            if plan_model.action_family == "move_unit" and not resolved_ids and atomic is not None:
                ordered_items = await _load_ordered_items(ctx)
                selected_item, selector_target_position, selector_facts, selector_message = _resolve_tier_local_move_selector(
                    ordered_items,
                    atomic.filters or {},
                )
                selected_id = str((selected_item or {}).get("volunteerId") or "").strip() if selected_item else ""
                if selected_id and selector_target_position is not None:
                    resolved_ids = [selected_id]
                    resolved_summary, resolved_position_facts = _build_move_unit_preview_summary_from_items(
                        ordered_items,
                        resolved_ids,
                        selector_target_position,
                        context_text=" ".join(
                            part
                            for part in (
                                str(plan_model.user_goal or "").strip(),
                                str(getattr(atomic, "reason", "") or "").strip(),
                            )
                            if part
                        ),
                    )
                    if resolved_summary:
                        preview_summary = resolved_summary
                        preview_facts.update(selector_facts)
                        preview_facts.update(resolved_position_facts)
                        preview_facts["resolved_apply_payload"] = _build_resolved_apply_payload(
                            plan_model,
                            volunteer_ids=resolved_ids,
                            target_position=selector_target_position,
                        )
                elif selector_message:
                    selector_facts["position_resolution"] = "tier_selector_no_match"
                    return PlanExecutionResult(
                        applied=False,
                        action_family=plan_model.action_family,
                        stage="preview",
                        result_kind="no_change",
                        context_summary=plan_model.context_summary,
                        summary=selector_message,
                        state_summary=selector_message,
                        reply_focus=["no_matching_ordered_items"],
                        reply_strategy="direct_reply",
                        next_step_hints=["当前方案没有命中 tier-local 调序范围；不要生成确认卡，也不要提示已移动。"],
                        facts=_facts_with_planning_version(selector_facts, ctx),
                    )
            if resolved_ids and "resolved_apply_payload" not in preview_facts:
                preview_facts["resolved_apply_payload"] = _build_resolved_apply_payload(
                    plan_model,
                    volunteer_ids=resolved_ids,
                )
        elif plan_model.action_family == "sort_ordered_plan":
            resolved_summary, resolved_facts = await _build_sort_ordered_plan_preview_summary(ctx, plan_model)
            if resolved_summary:
                preview_summary = resolved_summary
                preview_facts = resolved_facts
        return PlanExecutionResult(
            applied=False,
            action_family=plan_model.action_family,
            stage="preview",
            result_kind="preview_only",
            context_summary=plan_model.context_summary,
            summary=_with_confirmation_hint(preview_summary),
            reply_focus=(
                ["preview_only", "confirmation_required", "unit_position_preview"]
                if plan_model.action_family in {"move_ordered_unit", "remove_ordered_unit"}
                else ["preview_only", "confirmation_required"]
            ),
            next_step_hints=(
                [
                    "只复述专业组级预览事实：源专业组、目标位置、组内专业数和确认提示；"
                    "不要补充当前前 N 位概况或前 N 条志愿列表。"
                ]
                if plan_model.action_family in {"move_ordered_unit", "remove_ordered_unit"}
                else ["先向用户说明将要改动什么；用户确认后，再执行当前方案动作。"]
            ),
            facts=_facts_with_planning_version(preview_facts, ctx),
        )

    if plan_model.stage == "preview" and plan_model.action_family == "replace_units":
        atomic = plan_model.atomic_actions[0] if plan_model.atomic_actions else None
        refs = list(atomic.volunteer_ids or []) if atomic else []
        resolved_ids, missing_refs = await _resolve_ordered_volunteer_refs(ctx, refs)
        effective_ids, ordered_items, review_issue_target, review_issue = await _resolve_review_issue_action_scope(
            ctx,
            plan_model,
            resolved_ids,
        )
        if review_issue and str(review_issue.get("scope_kind") or "").strip() == "structural":
            summary, hints = _structural_review_issue_guidance(review_issue)
            return PlanExecutionResult(
                applied=False,
                action_family=plan_model.action_family,
                stage=plan_model.stage,
                result_kind="preview_only",
                context_summary=plan_model.context_summary,
                summary=summary,
                reply_focus=["preview_only", "review_issue_structural"],
                next_step_hints=hints,
                facts=_facts_with_planning_version({}, ctx),
            )
        if (
            review_issue
            and _is_item_review_issue(review_issue)
            and review_issue_target is not None
            and atomic is not None
            and not _has_filter_selection_scope(atomic.filters)
        ):
            unit_count = _count_ordered_units_for_ids(ordered_items, effective_ids)
            issue_label = str(review_issue.get("label") or review_issue.get("code") or "问题项").strip()
            if _is_replacement_first_review_issue(review_issue):
                preview_summary = (
                    f"已定位到当前方案里当前审查命中的{issue_label}："
                    f"共 {unit_count} 个专业组，涉及 {len(effective_ids)} 条志愿。"
                    "这类问题更适合先看替换预览，而不是直接整批删除。"
                    "请补充你希望换成的地域、专业、院校层次或冲稳保范围；"
                    "我会先生成可确认的替换预览，确认前不会改动方案。"
                )
                return PlanExecutionResult(
                    applied=False,
                    action_family=plan_model.action_family,
                    stage="analyze",
                    result_kind="error",
                    context_summary=plan_model.context_summary,
                    summary=preview_summary,
                    reply_focus=["replacement_scope_required", "review_issue_batch_scope"],
                    reply_strategy="direct_blocking",
                    next_step_hints=["先让用户补充替换范围；不要把替换优先风险自动改成整批删除。"],
                    facts=_facts_with_planning_version({}, ctx),
                )
            preview_summary = (
                f"已定位到当前方案里当前审查命中的{issue_label}："
                f"共 {unit_count} 个专业组，涉及 {len(effective_ids)} 条志愿。"
                "当前这句更适合按整批问题项先移出，不默认补回。"
                "如果你只想处理某个学校、专业组或位置，或者想明确换成什么范围，可以直接告诉我。"
                "确认后我会先移出这些项，并在执行后重新审查。"
            )
            return PlanExecutionResult(
                applied=False,
                action_family=plan_model.action_family,
                stage=plan_model.stage,
                result_kind="preview_only",
                context_summary=plan_model.context_summary,
                summary=_with_confirmation_hint(preview_summary),
                reply_focus=["preview_only", "review_issue_batch_scope"],
                next_step_hints=["如果用户确认执行，再按当前审查命中的整批问题项做移除。"],
                facts=_facts_with_planning_version({}, ctx),
            )
        if (missing_refs or not resolved_ids) and review_issue_target is None:
            missing_text = "、".join(missing_refs[:5]) if missing_refs else "要替换的志愿"
            return PlanExecutionResult(
                applied=False,
                action_family=plan_model.action_family,
                stage=plan_model.stage,
                result_kind="error",
                context_summary=plan_model.context_summary,
                summary=(
                    f"我理解你想替换的是：{missing_text}。"
                    "但我在当前方案里还没有唯一匹配到这条志愿。"
                    "请先明确当前方案里的具体志愿，或补充更完整的学校、专业组、专业名称后我再给你确认。"
                ),
                reply_focus=["missing_inputs", "needs_volunteer_selection"],
                reply_strategy="direct_blocking",
                next_step_hints=["先定位当前方案里对应的志愿，再生成可确认的替换预览。"],
            )
        if atomic and effective_ids and review_issue_target is not None:
            filters = atomic.filters or {}
            if _should_preflight_replace_capacity(plan_model, effective_ids, review_issue_target):
                blocked_result = await _preview_or_block_replace_by_candidate_capacity(
                    ctx,
                    plan_model=plan_model,
                    ordered_items=ordered_items,
                    effective_ids=effective_ids,
                    filters=filters,
                    review_issue_target=review_issue_target,
                    apply_message_prefix="这次我先不执行替换",
                    preview_message_prefix="我先拦一下",
                )
                if blocked_result is not None:
                    return blocked_result

    if plan_model.stage == "preview" and plan_model.action_family == "remove_units":
        atomic = plan_model.atomic_actions[0] if plan_model.atomic_actions else None
        refs = list(atomic.volunteer_ids or []) if atomic else []
        review_issue_target = getattr(atomic, "review_issue_target", None) if atomic else None
        batch = getattr(ctx.deps, "batch", None) or "01"
        if not refs and review_issue_target is None and _has_structured_remove_scope(atomic, batch):
            ordered_items = await _load_ordered_items(ctx)
            planning_state = await _get_planning_state_with_latest_profile(ctx.deps.sessionid)
            scoped_ids, matched_items = _resolve_ordered_ids_by_remove_scope(
                ordered_items,
                atomic,
                batch,
                planning_state,
            )
            scope_label = _remove_scope_label(atomic, batch)
            if not scoped_ids:
                summary = (
                    f"当前方案里暂时没有匹配“{scope_label}”的志愿，所以这次不需要从方案中移除。"
                    "如果后续也必须避开这个方向，可以继续说明，我会先列出来让你采纳，再写入后续报考参考。"
                )
                return PlanExecutionResult(
                    applied=False,
                    action_family=plan_model.action_family,
                    stage=plan_model.stage,
                    result_kind="no_change",
                    context_summary=plan_model.context_summary,
                    summary=summary,
                    state_summary=summary,
                    reply_focus=["no_matching_ordered_items"],
                    reply_strategy="direct_reply",
                    next_step_hints=["当前方案没有命中结构化移除范围；不要声称已经移除。"],
                    facts=_facts_with_planning_version(
                        {"remove_scope": scope_label, "matched_count": 0},
                        ctx,
                    ),
                )
            preview_summary = _build_remove_units_preview_summary_from_scope(
                ordered_items,
                matched_items,
                scoped_ids,
                atomic,
                batch,
                include_intent_update=bool(
                    _build_constraint_intent_update_from_remove_scope(
                        atomic,
                        getattr(ctx.deps, "batch", None) or "01",
                    ).get("selected")
                ),
            )
            return PlanExecutionResult(
                applied=False,
                action_family=plan_model.action_family,
                stage=plan_model.stage,
                result_kind="preview_only",
                context_summary=plan_model.context_summary,
                summary=_with_confirmation_hint(preview_summary),
                reply_focus=["preview_only", "confirmation_required", "constraint_plan_removal"],
                next_step_hints=[
                    "只说明当前方案命中的移除范围、确认后会移除并更新后续报考参考；不要重复生成单独意向确认卡。"
                ],
                facts=_facts_with_planning_version(
                    {
                        "resolved_apply_payload": _build_resolved_apply_payload(
                            plan_model,
                            volunteer_ids=scoped_ids,
                        ),
                        "intent_update": _build_constraint_intent_update_from_remove_scope(
                            atomic,
                            getattr(ctx.deps, "batch", None) or "01",
                        ),
                        "remove_scope": scope_label,
                        "matched_count": len(scoped_ids),
                        "matched_examples": [
                            _ordered_item_display_name(item)
                            for item in matched_items[:5]
                        ],
                    },
                    ctx,
                ),
            )
        if refs or review_issue_target is not None:
            resolved_ids, missing_refs = await _resolve_ordered_volunteer_refs(ctx, refs)
            resolved_apply_payload = _build_resolved_apply_payload(plan_model, volunteer_ids=resolved_ids) if resolved_ids else {}
            expanded_ids, ordered_items, _, review_issue = await _resolve_review_issue_action_scope(
                ctx,
                plan_model,
                resolved_ids,
            )
            if expanded_ids:
                resolved_apply_payload = _build_resolved_apply_payload(
                    plan_model,
                    volunteer_ids=expanded_ids,
                )
            if review_issue and str(review_issue.get("scope_kind") or "").strip() == "structural":
                summary, hints = _structural_review_issue_guidance(review_issue)
                return PlanExecutionResult(
                    applied=False,
                    action_family=plan_model.action_family,
                    stage=plan_model.stage,
                    result_kind="preview_only",
                    context_summary=plan_model.context_summary,
                    summary=summary,
                    reply_focus=["preview_only", "review_issue_structural"],
                    next_step_hints=hints,
                    facts=_facts_with_planning_version({}, ctx),
                )
            if review_issue and expanded_ids:
                unit_count = _count_ordered_units_for_ids(ordered_items, expanded_ids)
                issue_label = str(review_issue.get("label") or review_issue.get("code") or "问题项").strip()
                if _is_replacement_first_review_issue(review_issue) and plan_model.action_family != "remove_units":
                    preview_summary = (
                        f"已定位到当前方案里当前审查命中的{issue_label}："
                        f"共 {unit_count} 个专业组，涉及 {len(expanded_ids)} 条志愿。"
                        "这类问题默认优先做替换预览；如果你确实要直接移除整批，也可以确认这次按删除处理。"
                        "确认后我会移出这些项，并在执行后重新审查。"
                    )
                else:
                    preview_summary = (
                        f"已定位到当前方案里当前审查命中的{issue_label}："
                        f"共 {unit_count} 个专业组，涉及 {len(expanded_ids)} 条志愿。"
                        "这次确认会按整批问题项处理，不只是示例里的个别志愿。"
                        "如果你只想处理某个学校、专业组或位置，请直接告诉我。"
                        "确认后我会先移出这些项，并在执行后重新审查。"
                    )
                return PlanExecutionResult(
                    applied=False,
                    action_family=plan_model.action_family,
                    stage=plan_model.stage,
                    result_kind="preview_only",
                    context_summary=plan_model.context_summary,
                    summary=_with_confirmation_hint(preview_summary),
                    reply_focus=["preview_only", "review_issue_batch_scope"],
                    next_step_hints=["如果用户确认执行，再按当前审查命中的整批问题项做移除。"],
                    facts=_facts_with_planning_version(
                        {"resolved_apply_payload": resolved_apply_payload} if resolved_apply_payload else {},
                        ctx,
                    ),
                )
            if missing_refs or not resolved_ids:
                missing_text = "、".join(missing_refs[:5]) if missing_refs else "要移除的志愿"
                return PlanExecutionResult(
                    applied=False,
                    action_family=plan_model.action_family,
                    stage=plan_model.stage,
                    result_kind="error",
                    context_summary=plan_model.context_summary,
                    summary=_ordered_ref_resolution_message(missing_text, "移除"),
                    reply_focus=["missing_inputs", "needs_volunteer_selection"],
                    reply_strategy="direct_blocking",
                    next_step_hints=["先定位当前方案里的真实 volunteerId，再生成可确认的移除预览。"],
                )

    if plan_model.stage == "preview" and plan_model.action_family == "move_unit":
        atomic = plan_model.atomic_actions[0] if plan_model.atomic_actions else None
        refs = list(atomic.volunteer_ids or []) if atomic else []
        if refs:
            resolved_ids, missing_refs = await _resolve_ordered_volunteer_refs(ctx, refs)
            if missing_refs or not resolved_ids:
                missing_text = "、".join(missing_refs[:5]) if missing_refs else "要移动的志愿"
                return PlanExecutionResult(
                    applied=False,
                    action_family=plan_model.action_family,
                    stage=plan_model.stage,
                    result_kind="error",
                    context_summary=plan_model.context_summary,
                    summary=_ordered_ref_resolution_message(missing_text, "移动"),
                    reply_focus=["missing_inputs", "needs_volunteer_selection"],
                    reply_strategy="direct_blocking",
                    next_step_hints=["先定位当前方案里的真实 volunteerId，再生成可确认的位置调整预览。"],
                )
            ordered_items = await _load_ordered_items(ctx)
            resolved_summary, resolved_facts = _build_move_unit_preview_summary_from_items(
                ordered_items,
                resolved_ids,
                getattr(atomic, "target_position", None),
                context_text=" ".join(
                    part
                    for part in (
                        str(plan_model.user_goal or "").strip(),
                        str(getattr(atomic, "reason", "") or "").strip(),
                    )
                    if part
                ),
            )
            if resolved_summary:
                if (
                    resolved_facts.get("source_position") is not None
                    and resolved_facts.get("target_position") is not None
                    and int(resolved_facts["source_position"]) == int(resolved_facts["target_position"])
                ):
                    return PlanExecutionResult(
                        applied=False,
                        action_family=plan_model.action_family,
                        stage=plan_model.stage,
                        result_kind="no_change",
                        context_summary=plan_model.context_summary,
                        summary=resolved_summary,
                        state_summary=resolved_summary,
                        reply_focus=["already_at_target"],
                        reply_strategy="direct_reply",
                        next_step_hints=["当前志愿已经在目标位置；不要生成确认卡，也不要提示已移动。"],
                        facts=_facts_with_planning_version(resolved_facts, ctx),
                    )
                plan_model = plan_model.model_copy(
                    update={
                        "preview_summary": resolved_summary,
                        "facts": {
                            **(getattr(plan_model, "facts", {}) or {}),
                            **resolved_facts,
                            "resolved_apply_payload": _build_resolved_apply_payload(
                                plan_model,
                                volunteer_ids=resolved_ids,
                                target_position=resolved_facts.get("target_position"),
                            ),
                        },
                    }
                )
        elif atomic is not None:
            ordered_items = await _load_ordered_items(ctx)
            selected_item, selector_target_position, selector_facts, selector_message = _resolve_tier_local_move_selector(
                ordered_items,
                atomic.filters or {},
            )
            selected_id = str((selected_item or {}).get("volunteerId") or "").strip() if selected_item else ""
            if selected_id and selector_target_position is not None:
                resolved_summary, resolved_facts = _build_move_unit_preview_summary_from_items(
                    ordered_items,
                    [selected_id],
                    selector_target_position,
                    context_text=" ".join(
                        part
                        for part in (
                            str(plan_model.user_goal or "").strip(),
                            str(getattr(atomic, "reason", "") or "").strip(),
                        )
                        if part
                    ),
                )
                if resolved_summary:
                    if (
                        resolved_facts.get("source_position") is not None
                        and resolved_facts.get("target_position") is not None
                        and int(resolved_facts["source_position"]) == int(resolved_facts["target_position"])
                    ):
                        return PlanExecutionResult(
                            applied=False,
                            action_family=plan_model.action_family,
                            stage=plan_model.stage,
                            result_kind="no_change",
                            context_summary=plan_model.context_summary,
                            summary=resolved_summary,
                            state_summary=resolved_summary,
                            reply_focus=["already_at_target"],
                            reply_strategy="direct_reply",
                            next_step_hints=["当前志愿已经在目标位置；不要生成确认卡，也不要提示已移动。"],
                            facts=_facts_with_planning_version({**selector_facts, **resolved_facts}, ctx),
                        )
                    plan_model = plan_model.model_copy(
                        update={
                            "preview_summary": resolved_summary,
                            "facts": {
                                **(getattr(plan_model, "facts", {}) or {}),
                                **selector_facts,
                                **resolved_facts,
                                "resolved_apply_payload": _build_resolved_apply_payload(
                                    plan_model,
                                    volunteer_ids=[selected_id],
                                    target_position=selector_target_position,
                                ),
                            },
                        }
                    )
            elif selector_message:
                selector_facts["position_resolution"] = "tier_selector_no_match"
                return PlanExecutionResult(
                    applied=False,
                    action_family=plan_model.action_family,
                    stage=plan_model.stage,
                    result_kind="no_change",
                    context_summary=plan_model.context_summary,
                    summary=selector_message,
                    state_summary=selector_message,
                    reply_focus=["no_matching_ordered_items"],
                    reply_strategy="direct_reply",
                    next_step_hints=["当前方案没有命中 tier-local 调序范围；不要生成确认卡，也不要提示已移动。"],
                    facts=_facts_with_planning_version(selector_facts, ctx),
                )

    if plan_model.stage == "preview" and plan_model.action_family == "add_units":
        atomic = plan_model.atomic_actions[0] if plan_model.atomic_actions else None
        refs = list(atomic.volunteer_ids or []) if atomic else []
        if refs:
            existing_ids: list[str] = []
            if _contains_natural_ref_text(refs):
                existing_ids, _ = await _resolve_ordered_volunteer_refs(ctx, refs)
            resolved_ids, missing_refs = await _resolve_candidate_volunteer_refs(ctx, refs)
            existing_id_set = set(existing_ids)
            resolved_ids = [volunteer_id for volunteer_id in resolved_ids if volunteer_id not in existing_id_set]
            if existing_ids and not resolved_ids and not missing_refs:
                refs_text = "、".join(refs[:5])
                state_summary = f"{refs_text} 已经在当前方案中，无需重复加入。"
                return PlanExecutionResult(
                    applied=False,
                    action_family="add_units",
                    stage=plan_model.stage,
                    result_kind="no_change",
                    context_summary=plan_model.context_summary,
                    state_summary=state_summary,
                    summary=state_summary,
                    reply_focus=["already_in_plan"],
                    reply_strategy="direct_reply",
                    facts=_facts_with_planning_version({"requested_refs": refs, "already_in_plan_ids": existing_ids}, ctx),
                )
            if missing_refs or not resolved_ids:
                filters = atomic.filters or {}
                if _has_filter_selection_scope(filters):
                    return await _build_add_units_filter_preview(ctx, plan_model, filters)
                missing_text = "、".join(missing_refs[:5]) if missing_refs else "要加入的候选志愿"
                return PlanExecutionResult(
                    applied=False,
                    action_family="add_units",
                    stage=plan_model.stage,
                    result_kind="error",
                    context_summary=plan_model.context_summary,
                    state_summary=_candidate_ref_resolution_message(missing_text),
                    summary=_candidate_ref_resolution_message(missing_text),
                    reply_focus=["missing_inputs", "needs_candidate_selection"],
                    reply_strategy="direct_blocking",
                    next_step_hints=["先定位候选池里的真实 volunteerId，再执行加入方案。"],
                    facts=_facts_with_planning_version({"requested_refs": refs}, ctx),
                )
            display_text = _candidate_ref_display_text(refs, len(resolved_ids))
            target_text = f"：{display_text}" if display_text else ""
            preview_summary = (
                f"已在候选里定位到 {len(resolved_ids)} 个可加入方案的志愿{target_text}。"
                "确认后会加入当前方案，并同步刷新方案顺序和审查状态。"
            )
            plan_model = plan_model.model_copy(
                update={
                    "preview_summary": preview_summary,
                    "facts": {
                        **(getattr(plan_model, "facts", {}) or {}),
                        "resolved_apply_payload": _build_resolved_apply_payload(
                            plan_model,
                            volunteer_ids=resolved_ids,
                        ),
                        "resolved_candidate_ids": resolved_ids,
                    },
                }
            )

    if plan_model.stage in {"analyze", "preview"}:
        preview_summary = plan_model.preview_summary or (
            "这轮我先把影响范围和可选方向说明清楚，不会直接改动当前方案。"
        )
        preview_facts: dict[str, Any] = {}
        if plan_model.action_family == "move_ordered_unit":
            resolved_summary, resolved_facts = await _build_move_ordered_unit_preview_summary(ctx, plan_model)
            if resolved_summary:
                if str(resolved_facts.get("position_resolution") or "").strip() in {
                    "already_at_target",
                    "tier_selector_no_match",
                    "missing_target_position",
                }:
                    return PlanExecutionResult(
                        applied=False,
                        action_family=plan_model.action_family,
                        stage=plan_model.stage,
                        result_kind="no_change",
                        context_summary=plan_model.context_summary,
                        summary=resolved_summary,
                        state_summary=resolved_summary,
                        reply_focus=["already_at_target"] if str(resolved_facts.get("position_resolution") or "").strip() == "already_at_target" else ["no_matching_ordered_items"],
                        reply_strategy="direct_reply",
                        next_step_hints=["当前排序项已经在目标位置或缺少可移动目标；不要生成确认卡，也不要提示已移动。"],
                        facts=_facts_with_planning_version(resolved_facts, ctx),
                    )
                preview_summary = resolved_summary
                preview_facts = resolved_facts
        elif plan_model.action_family == "remove_ordered_unit":
            resolved_summary, resolved_facts = await _build_remove_ordered_unit_preview_summary(ctx, plan_model)
            if resolved_summary:
                if str(resolved_facts.get("position_resolution") or "").strip() in {"range_empty", "missing_source_position"}:
                    return PlanExecutionResult(
                        applied=False,
                        action_family=plan_model.action_family,
                        stage=plan_model.stage,
                        result_kind="no_change",
                        context_summary=plan_model.context_summary,
                        summary=resolved_summary,
                        state_summary=resolved_summary,
                        reply_focus=["no_matching_ordered_items"],
                        reply_strategy="direct_reply",
                        next_step_hints=["当前范围没有命中可删除项；不要生成确认卡，也不要提示需要确认执行。"],
                        facts=_facts_with_planning_version(resolved_facts, ctx),
                    )
                preview_summary = resolved_summary
                preview_facts = resolved_facts
        elif plan_model.stage == "preview" and plan_model.action_family in {"remove_units", "move_unit", "replace_units"}:
            atomic = plan_model.atomic_actions[0] if plan_model.atomic_actions else None
            refs = list(atomic.volunteer_ids or []) if atomic else []
            resolved_ids, _ = await _resolve_ordered_volunteer_refs(ctx, refs)
            if resolved_ids:
                preview_facts["resolved_apply_payload"] = _build_resolved_apply_payload(
                    plan_model,
                    volunteer_ids=resolved_ids,
                )
            preview_facts.update(getattr(plan_model, "facts", {}) or {})
        elif plan_model.stage == "preview" and plan_model.action_family == "sort_ordered_plan":
            resolved_summary, resolved_facts = await _build_sort_ordered_plan_preview_summary(ctx, plan_model)
            if resolved_summary:
                preview_summary = resolved_summary
                preview_facts = resolved_facts
        elif plan_model.stage == "preview" and plan_model.action_family == "add_units":
            preview_facts.update(getattr(plan_model, "facts", {}) or {})
        if plan_model.stage == "preview" and plan_model.action_family in _MUTATING_ACTION_FAMILIES:
            preview_summary = _with_confirmation_hint(preview_summary)
        reply_focus = ["preview_only"]
        if plan_model.action_family in {"move_ordered_unit", "remove_ordered_unit"}:
            reply_focus.append("unit_position_preview")
        if (
            plan_model.action_family == "move_unit"
            and isinstance(preview_facts.get("source_display_name"), str)
            and preview_facts.get("source_position") is not None
            and preview_facts.get("target_position") is not None
        ):
            reply_focus.append("volunteer_position_preview")
        if plan_model.action_family == "sort_ordered_plan":
            reply_focus.append("sort_preview")
        if plan_model.action_family == "add_units" and plan_model.stage == "preview":
            reply_focus.append("confirmation_required")
        if bool(getattr(plan_model, "facts", {}).get("downgraded_unconfirmed_apply")):
            reply_focus.append("confirmation_required")
        return PlanExecutionResult(
            applied=False,
            action_family=plan_model.action_family,
            stage=plan_model.stage,
            result_kind="preview_only",
            context_summary=plan_model.context_summary,
            summary=preview_summary,
            reply_focus=reply_focus,
            next_step_hints=["如果用户确认执行，再进入实际方案动作。"] if plan_model.stage == "preview" else [],
            facts=_facts_with_planning_version(preview_facts, ctx),
        )

    handler_result = await _dispatch_registered_handler(ctx, plan_model)
    if handler_result is not None:
        return handler_result

    # Fallback for unregistered action families
    fallback_msg = f"当前 action_family={plan_model.action_family} 暂未接入执行层。"
    return PlanExecutionResult(
        applied=False,
        action_family=plan_model.action_family,
        stage=plan_model.stage,
        result_kind="error",
        context_summary=plan_model.context_summary,
        state_summary=fallback_msg,
        summary=fallback_msg,
        reply_focus=["unsupported_action"],
        next_step_hints=[],
    )


async def execute_plan_action(
    ctx: RunContext[RequestContext],
    plan_payload: str,
) -> str:
    """执行受控 PlanActionPlan。

    For clear read-only plan actions the caller may pass a minimal JSON
    PlanActionPlan directly, for example:
    {"stage":"apply","action_family":"query_state","user_goal":"用户原话","requires_confirmation":false}
    {"stage":"review","action_family":"review_plan","user_goal":"用户原话","requires_confirmation":false}
    Mutating actions still require preview/confirmation and are guarded here.
    """
    started_at = time.monotonic()
    logger.info("execute_plan_action: session_id=%s", ctx.deps.sessionid)
    try:
        data, repaired_payload = _load_plan_payload(plan_payload)
        data = _merge_recent_plan_action_plan_if_compatible(ctx, data)
        data = _merge_resolved_apply_payload_if_available(data)
    except Exception:
        fallback = PlanExecutionResult(
            applied=False,
            action_family="unknown",
            stage="apply",
            result_kind="error",
            context_summary="",
            summary="这次还没有形成可确认的方案调整内容。请再说明一下要调整哪所学校或哪个专业，我会先给你一版可确认的预览。",
            reply_focus=["missing_plan_payload"],
            reply_strategy="direct_blocking",
            next_step_hints=["[LLM_INTERNAL] 先生成完整的操作计划，再执行方案动作。"],
        )
        result_data = fallback.model_dump()
        log_event(
            "plan_action_event",
            sessionId=ctx.deps.sessionid,
            actionFamily="unknown",
            stage="apply",
            applied=False,
            durationMs=int((time.monotonic() - started_at) * 1000),
            status="error",
            errorType="invalid_payload_json",
        )
        return json.dumps(result_data, ensure_ascii=False)
    if repaired_payload:
        log_event(
            "plan_action_payload_repair",
            sessionId=ctx.deps.sessionid,
            actionFamily=str(data.get("action_family") or "unknown"),
            stage=str(data.get("stage") or "unknown"),
            status="repaired",
        )
    try:
        plan_model = PlanActionPlan.model_validate(data)
    except Exception:
        fallback = PlanExecutionResult(
            applied=False,
            action_family=str(data.get("action_family") or "unknown"),
            stage=str(data.get("stage") or "apply"),
            result_kind="error",
            context_summary=str(data.get("context_summary") or ""),
            summary="这次还没有形成可确认的方案调整内容。请再说明一下要调整哪所学校或哪个专业，我会先给你一版可确认的预览。",
            reply_focus=["missing_plan_payload"],
            reply_strategy="direct_blocking",
            next_step_hints=["[LLM_INTERNAL] 先生成完整的操作计划，再执行方案动作。"],
        )
        result_data = fallback.model_dump()
        log_event(
            "plan_action_event",
            sessionId=ctx.deps.sessionid,
            actionFamily=str(data.get("action_family") or "unknown"),
            stage=str(data.get("stage") or "apply"),
            applied=False,
            durationMs=int((time.monotonic() - started_at) * 1000),
            status="error",
            errorType="invalid_plan_model",
        )
        return json.dumps(result_data, ensure_ascii=False)
    plan_model = _canonicalize_plan_major_scopes(ctx, plan_model)
    data = normalize_plan_action_payload(plan_model.model_dump())
    if plan_model.stage == "apply" and plan_model.action_family in _MUTATING_ACTION_FAMILIES and not _allows_mutating_apply(ctx, plan_model):
        plan_model = plan_model.model_copy(
            update={
                "stage": "preview",
                "facts": {
                    **(getattr(plan_model, "facts", {}) or {}),
                    "downgraded_unconfirmed_apply": True,
                },
            }
        )
        data = normalize_plan_action_payload(plan_model.model_dump())
    guard_result: PlanExecutionResult | None = None
    if plan_model.stage == "apply" and plan_model.action_family in _MUTATING_ACTION_FAMILIES:
        phase = getattr(ctx.deps, "conversation_phase", None)
        planning_summary = getattr(ctx.deps, "planning_summary", None)
        plan_version = getattr(plan_model, "planning_version", 0)
        if phase is not None:
            try:
                if int(getattr(phase, "last_backend_version", 0) or 0) <= 0 and int(plan_version or 0) > 0:
                    phase.last_backend_version = int(plan_version)
            except (TypeError, ValueError):
                pass

        sync = PlanningStateSync()
        try:
            current_turn = int(getattr(phase, "turn_count", 0) or 0) if phase is not None else 0
        except (TypeError, ValueError):
            current_turn = 0
        stale_event = sync.invalidate_if_stale(
            phase,
            current_turn=current_turn,
            planning_summary=planning_summary,
        )
        guard_event = stale_event if stale_event.is_stale else sync.pre_execute_guard(
            phase,
            planning_summary,
            plan_model.action_family,
        )
        if guard_event.is_stale:
            if guard_event.should_clear_pending and phase is not None:
                phase.clear_pending()
            summary = guard_event.message or "上一轮方案预览已失效，请重新查看当前方案后再确认。"
            guard_result = PlanExecutionResult(
                applied=False,
                action_family=plan_model.action_family,
                stage=plan_model.stage,
                result_kind="error",
                context_summary=plan_model.context_summary,
                state_summary=summary,
                summary=summary,
                reply_focus=["stale_pending", "confirmation_invalid"],
                next_step_hints=["请重新读取当前方案状态，再生成新的可确认预览。"],
                facts={
                    "stale_cause": getattr(guard_event.cause, "value", None),
                    "old_version": guard_event.old_version,
                    "new_version": guard_event.new_version,
                },
            )

    result = guard_result or await _execute_plan_action_model(ctx, plan_model)
    result_data = result.model_dump()
    cached_result_data = copy.deepcopy(result_data)
    effective_action_family = str(result_data.get("action_family") or "").strip()
    if (
        effective_action_family in _MUTATING_ACTION_FAMILIES
        and (
            str(result_data.get("stage") or "").strip() == "preview"
        )
    ):
        pending_source_payload = normalize_plan_action_payload(copy.deepcopy(data))
        result_facts = result_data.get("facts")
        if isinstance(result_facts, dict) and result_facts:
            pending_source_payload["facts"] = copy.deepcopy(result_facts)
        cached_result_data["_pending_source_payload"] = pending_source_payload
    if result_data.get("next_step_hints"):
        result_data["next_step_hints"] = [
            f"[LLM_INTERNAL] {hint}" for hint in result_data["next_step_hints"]
        ]
    _remember_recent_plan_execution_result(ctx, cached_result_data)
    log_event(
        "plan_action_event",
        sessionId=ctx.deps.sessionid,
        actionFamily=result_data.get("action_family"),
        stage=result_data.get("stage"),
        resultKind=result_data.get("result_kind"),
        applied=bool(result_data.get("applied")),
        durationMs=int((time.monotonic() - started_at) * 1000),
        status="error" if result_data.get("result_kind") == "error" else "success",
        errorType=result_data.get("result_kind") if result_data.get("result_kind") == "error" else None,
    )
    return json.dumps(result_data, ensure_ascii=False)
