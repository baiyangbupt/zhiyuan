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
from app.domain.major_entity_resolver import major_alias_variants_for_name
from app.domain.school_entity_resolver import school_alias_variants
from app.domain.school_major_ref_resolver import resolve_school_major_ref
from app.sync.state_sync import PlanningStateSync
from app.tools.plan_orchestration_models import (
    PlanActionPlan,
    PlanAtomicAction,
    PlanExecutionResult,
    PlanReviewIssueTarget,
    normalize_plan_action_payload,
)
from app.tools.review_issue_registry import build_review_issue_scopes
from app.tools.planning_workflow_tool import (
    _build_compensation_preview_facts,
    _build_plan_adjustment_facts,
    _build_plan_intent_relation_lines,
    _build_plan_status_overview_facts,
    _build_review_result_facts,
    analyze_planning_plan_adjustment,
    merge_planning_state_with_user_profile,
    move_planning_ordered_item,
    preview_planning_compensation,
    query_planning_candidate_pool,
    query_planning_draft,
    query_planning_ordered_plan,
    query_planning_plan_overview,
    remove_planning_ordered_items,
    run_planning_review,
    select_planning_ordered_items,
)
from app.util.internal_client import (
    apply_planning_compensation as _apply_planning_compensation_request,
    analyze_planning_plan_adjustment as _analyze_planning_plan_adjustment_request,
    generate_planning_candidate_pool as _generate_planning_candidate_pool_request,
    generate_planning_initial_plan as _generate_planning_initial_plan_request,
    generate_planning_ordered_plan as _generate_planning_ordered_plan_request,
    get_planning_draft as _get_planning_draft_request,
    get_planning_ordered_plan as _get_planning_ordered_plan_request,
    get_planning_state as _get_planning_state_request,
    get_user_profile as _get_user_profile_request,
    preview_planning_compensation as _preview_planning_compensation_request,
    query_planning_candidate_pool as _query_planning_candidate_pool_request,
    run_planning_review as _run_planning_review_request,
    select_planning_draft_items as _select_planning_draft_items_request,
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
    "apply_compensation",
}
_READONLY_HANDLER_ACTION_FAMILIES = {
    "query_state",
    "query_draft",
    "query_ordered",
    "query_candidates",
    "analyze_adjustment",
    "preview_compensation",
    "review_plan",
}
_RECENT_PLAN_EXECUTION_TTL_SECONDS = 180.0
_RECENT_PLAN_EXECUTION_RESULTS: dict[tuple[str, str], dict[str, Any]] = {}


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


def _latest_user_text(ctx: RunContext[RequestContext]) -> str:
    for message in reversed(ctx.deps.chat_history or []):
        if isinstance(message, dict) and message.get("role") == "user":
            return str(message.get("content") or "").strip()
    return ""


def _contains_natural_ref_text(refs: list[str]) -> bool:
    return any(any(ord(char) > 127 for char in str(ref or "")) for ref in refs)


def _infer_school_major_refs_from_text(ctx: RunContext[RequestContext], text: str) -> list[str]:
    resolution = resolve_school_major_ref(text, getattr(ctx.deps, "batch", None) or "01")
    if not resolution.can_query or resolution.ambiguous:
        return []
    school = resolution.school_keywords[0]
    major = resolution.major_keywords[0]
    return [f"{school} {major}"] if school and major else []


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


def clear_recent_plan_execution_result(session_id: str, user_prompt: str | None = None) -> None:
    _prune_recent_plan_execution_results()
    if user_prompt is None:
        session_key = str(session_id or "").strip()
        for key in list(_RECENT_PLAN_EXECUTION_RESULTS.keys()):
            if key[0] == session_key:
                _RECENT_PLAN_EXECUTION_RESULTS.pop(key, None)
        return
    key = (str(session_id or "").strip(), _normalize_prompt_key(user_prompt))
    _RECENT_PLAN_EXECUTION_RESULTS.pop(key, None)


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


def _first_atomic_action(plan_model: PlanActionPlan) -> Any | None:
    return plan_model.atomic_actions[0] if plan_model.atomic_actions else None


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
        raw_units = ordered_state.get("units") or []
        units = raw_units if isinstance(raw_units, list) else []
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


def _unit_kind_label(unit: dict[str, Any] | None) -> str:
    unit = unit or {}
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


def _unit_position_semantics(unit: dict[str, Any] | None) -> str:
    return "unit_position_not_item_position" if _unit_kind_label(unit) == "专业组" else "ordered_item_position"


def _unit_position_explanation(unit: dict[str, Any] | None) -> str:
    if _unit_kind_label(unit) == "专业组":
        return (
            "位置说明：这里的“第几个”按专业组顺序计算，不是按单条志愿位置计算；"
            "执行后该组内专业会保持连续。"
        )
    return "位置说明：这里的“第几个”按当前方案展示顺序计算，确认后会影响方案顺序和导出顺序。"


async def _build_move_ordered_unit_preview_summary(
    ctx: RunContext[RequestContext],
    plan_model: PlanActionPlan,
) -> tuple[str | None, dict[str, Any]]:
    action = _first_atomic_action(plan_model)
    target_position = getattr(action, "target_position", None)
    if target_position is None:
        return None, {}
    try:
        state_resp = await _get_planning_state_request(ctx.deps.sessionid)
        state = (state_resp or {}).get("data") or {}
        ordered_state = state.get("orderedPlanState") or {}
        raw_units = ordered_state.get("units") or []
        units = raw_units if isinstance(raw_units, list) else []
        unit_ids = _extract_unit_ids(plan_model)
        position_refs = _extract_unit_source_positions(plan_model)
        source_position = position_refs[0] if position_refs else None
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
            return (
                "会移动当前方案排序区里的指定项，目标是移动到新的方案位置。"
                "这里的“第几个”按当前方案展示顺序计算，确认后会影响方案顺序和导出顺序。",
                {"position_semantics": "ordered_unit_position"},
            )

        label = _unit_kind_label(source_unit)
        unit_name = _unit_display_name(source_unit)
        major_count = _unit_major_count(source_unit)
        count_text = f"，组内共 {major_count} 个专业" if label == "专业组" and major_count > 0 else ""
        source_text = f"第 {source_position} 个{label}" if source_position else f"当前定位到的{label}"
        target_text = f"第 {int(target_position)} 个{label}位置"
        explanation = _unit_position_explanation(source_unit)
        summary = (
            "预览如下：\n\n"
            f"- 源{label}：{source_text} — {unit_name}{count_text}\n"
            f"- 目标位置：{target_text}\n"
            f"- 移动方式：{'整组移动，组内专业顺序保持不变' if label == '专业组' else '移动该志愿，其他志愿按顺序衔接'}\n\n"
            f"{explanation}"
        )
        return summary, {
            "source_unit_id": source_unit_id,
            "source_unit_name": unit_name,
            "source_unit_position": source_position,
            "target_unit_position": int(target_position),
            "source_unit_major_count": major_count,
            "unit_kind": label,
            "position_semantics": _unit_position_semantics(source_unit),
        }
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
        raw_units = ordered_state.get("units") or []
        units = raw_units if isinstance(raw_units, list) else []
        unit_ids = _extract_unit_ids(plan_model)
        position_refs = _extract_unit_source_positions(plan_model)
        source_position = position_refs[0] if position_refs else None
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
            return (
                "会从当前方案排序区中删除指定项。"
                "这里的“第几个”按当前方案展示顺序计算，确认后会影响方案顺序和导出顺序。",
                {"position_semantics": "ordered_unit_position"},
            )

        label = _unit_kind_label(source_unit)
        unit_name = _unit_display_name(source_unit)
        major_count = _unit_major_count(source_unit)
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
    pending_action_family = (
        pending.action_family
        if pending is not None and pending.kind == "plan_mutation"
        else ""
    )
    latest_user_text = _latest_user_text(ctx)
    if pending_action_family == plan_model.action_family and _is_short_plan_confirmation(latest_user_text):
        return True
    return False


def _has_filter_selection_scope(filters: dict[str, Any]) -> bool:
    for key, value in (filters or {}).items():
        if key == "limit":
            continue
        if key in {"school_tags", "major_tags"} and str(value or "").strip() == "[]":
            continue
        if str(value or "").strip():
            return True
    return False


def _execution_missing_inputs(plan_model: PlanActionPlan) -> list[str]:
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


def _execution_missing_inputs_message(plan_model: PlanActionPlan, missing_inputs: list[str]) -> str:
    missing = {str(item or "").strip() for item in missing_inputs if str(item or "").strip()}
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


def _derive_candidate_major_keywords(
    major_keyword: str | None,
    major_tags: list[str] | None,
) -> list[str]:
    explicit_keywords = _normalize_keywords(major_keyword)
    if explicit_keywords:
        return explicit_keywords
    return [str(item or "").strip() for item in (major_tags or []) if str(item or "").strip()]


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


def _build_move_unit_preview_summary_from_items(
    items: list[dict[str, Any]],
    volunteer_ids: list[str],
    target_position: int | None,
) -> tuple[str | None, dict[str, Any]]:
    if target_position is None or not volunteer_ids:
        return None, {}
    item_by_id = {str(item.get("volunteerId") or "").strip(): item for item in items if str(item.get("volunteerId") or "").strip()}
    source_item = item_by_id.get(str(volunteer_ids[0] or "").strip())
    if not source_item:
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
    }


def _build_resolved_apply_payload(
    plan_model: PlanActionPlan,
    *,
    volunteer_ids: list[str] | None = None,
    unit_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Keep preview-resolved execution targets stable for the confirm turn."""
    if not plan_model.atomic_actions:
        return {}
    resolved_actions: list[dict[str, Any]] = []
    for index, action in enumerate(plan_model.atomic_actions):
        action_data = action.model_dump()
        if index == 0:
            if volunteer_ids is not None:
                action_data["volunteer_ids"] = [str(item) for item in volunteer_ids if str(item or "").strip()]
            if unit_ids is not None:
                action_data["unit_ids"] = [str(item) for item in unit_ids if str(item or "").strip()]
        resolved_actions.append(action_data)
    return {"atomic_actions": resolved_actions} if resolved_actions else {}


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
        ordered_items = ((planning_state.get("draftPlanState") or {}).get("items") or [])
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
        return resolved_ids, ordered_items, review_issue_target, None
    effective_ids = _resolve_review_issue_scope_ids(issue, ordered_items, resolved_ids, review_issue_target)
    return effective_ids or resolved_ids, ordered_items, review_issue_target, issue


def _structural_review_issue_guidance(issue: dict[str, Any]) -> tuple[str, list[str]]:
    label = str(issue.get("label") or issue.get("code") or "当前问题").strip()
    default_action_family = str(issue.get("default_action_family") or "").strip()
    if default_action_family == "preview_compensation":
        return (
            f"{label}属于结构性问题，不适合直接按样例删志愿。更合适的是先看补齐/补稳建议，再决定是否应用。",
            ["如果用户想继续处理，先预览补齐建议，再确认是否执行。"],
        )
    return (
        f"{label}属于结构性问题，受影响条目主要用于定位上下文，不应直接当作删除清单。更合适的是先看调整建议。",
            ["如果用户想继续处理，先查看调整建议，再决定是否执行局部改动。"],
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
    draft_state = (planning_state or {}).get("draftPlanState") or {}
    ordered_items = ordered_state.get("items") or []
    draft_items = draft_state.get("items") or []
    plan_items = ordered_items or draft_items
    plan_summary = (ordered_state.get("summary") or {}) if ordered_items else (draft_state.get("summary") or {})
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
        for loader in (_get_planning_ordered_plan_request, _get_planning_draft_request):
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
            major_keywords=_derive_candidate_major_keywords(major_keyword, major_tags),
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
        before_draft_total = 0
        try:
            before_state_result = await _get_planning_state_request(session_id)
            before_state = before_state_result.get("data") or {} if before_state_result.get("code") == 0 else {}
            before_ordered_total = _summary_total(((before_state.get("orderedPlanState") or {}).get("summary") or {}))
            before_draft_total = _summary_total(((before_state.get("draftPlanState") or {}).get("summary") or {}))
        except Exception:
            logger.warning("failed to read planning totals before selecting candidates: session_id=%s", session_id, exc_info=True)

        select_result = await _select_planning_draft_items_request(
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
        draft_summary = ((latest_state.get("draftPlanState") or {}).get("summary") or {})
        current_total = _summary_total(ordered_summary)
        draft_total = _summary_total(draft_summary)
        target_total = ordered_summary.get("targetUnitCount") or ordered_summary.get("targetCount") or 0
        review_summary = ((latest_state.get("reviewState") or {}).get("summary") or {})
        ordered_increase = max(0, current_total - before_ordered_total) if before_ordered_total else 0
        draft_increase = max(0, draft_total - before_draft_total) if before_draft_total else 0
        if ordered_increase > 0:
            lead_text = f"已按你的要求加入 {ordered_increase} 个候选志愿，并同步更新当前方案。"
        elif draft_increase > 0:
            lead_text = (
                f"已把 {draft_increase} 个候选志愿加入方案，但当前排序方案数量仍是 "
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


def _infer_ordered_sort_field(plan_model: PlanActionPlan) -> str:
    atomic = plan_model.atomic_actions[0] if plan_model.atomic_actions else None
    if atomic:
        for key in ("sort_field", "sortField", "field"):
            raw_value = str((atomic.filters or {}).get(key) or "").strip()
            if raw_value in _SORT_FIELD_ALIASES:
                return _SORT_FIELD_ALIASES[raw_value]
    return "admissionRatio"


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
        and plan_model.action_family not in {"review_plan", "preview_compensation"}
    ):
        review_summary = await run_planning_review(ctx)
        review_rerun = True
        if "review_result" not in reply_focus:
            reply_focus.append("review_rerun")
        if not next_step_hints:
            next_step_hints.append("如果用户继续追问风险，可以结合复审结果继续解释。")
        if "review" not in workspace_targets:
            workspace_targets.append("review")

    summary = result.state_summary or result.summary
    if review_summary and review_summary != summary and "direct_review_reply" not in reply_focus:
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

    if plan_model.action_family in {"pin_unit", "unpin_unit"}:
        return PlanExecutionResult(
            applied=False,
            action_family=plan_model.action_family,
            stage=plan_model.stage,
            result_kind="error",
            context_summary=plan_model.context_summary,
            summary=(
                "新版工作台暂不提供固定/锁定志愿入口，我不会通过对话单独改这个状态。"
                "如果你想稳定某条志愿的位置，可以告诉我把它移动到第几位，或先按录取率、院校层次、推荐系数排序后再微调。"
            ),
            reply_focus=["unsupported_action", "pin_disabled"],
            next_step_hints=["引导用户使用移动到指定位置或方案排序，不要继续执行 pin/unpin。"],
        )

    missing_inputs = list(plan_model.missing_inputs or [])
    for item in _execution_missing_inputs(plan_model):
        if item not in missing_inputs:
            missing_inputs.append(item)
    if missing_inputs:
        return PlanExecutionResult(
            applied=False,
            action_family=plan_model.action_family,
            stage=plan_model.stage,
            result_kind="error",
            context_summary=plan_model.context_summary,
            summary=_execution_missing_inputs_message(plan_model, missing_inputs),
            reply_focus=["missing_inputs"],
            reply_strategy="direct_blocking",
            next_step_hints=["先补齐缺失输入，再继续执行当前方案动作。"],
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
                preview_summary = resolved_summary
                preview_facts = resolved_facts
        elif plan_model.action_family == "remove_ordered_unit":
            resolved_summary, resolved_facts = await _build_remove_ordered_unit_preview_summary(ctx, plan_model)
            if resolved_summary:
                preview_summary = resolved_summary
                preview_facts = resolved_facts
        elif plan_model.action_family in {"remove_units", "move_unit", "replace_units"}:
            atomic = plan_model.atomic_actions[0] if plan_model.atomic_actions else None
            refs = list(atomic.volunteer_ids or []) if atomic else []
            resolved_ids, _ = await _resolve_ordered_volunteer_refs(ctx, refs)
            if resolved_ids:
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
            and str(review_issue.get("scope_kind") or "").strip() == "item_removal"
            and review_issue_target is not None
            and atomic is not None
            and not _has_filter_selection_scope(atomic.filters)
        ):
            unit_count = _count_ordered_units_for_ids(ordered_items, effective_ids)
            issue_label = str(review_issue.get("label") or review_issue.get("code") or "问题项").strip()
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
        if refs or review_issue_target is not None:
            resolved_ids, missing_refs = await _resolve_ordered_volunteer_refs(ctx, refs)
            resolved_apply_payload = _build_resolved_apply_payload(plan_model, volunteer_ids=resolved_ids) if resolved_ids else {}
            expanded_ids, ordered_items, _, review_issue = await _resolve_review_issue_action_scope(
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
            if review_issue and expanded_ids:
                unit_count = _count_ordered_units_for_ids(ordered_items, expanded_ids)
                issue_label = str(review_issue.get("label") or review_issue.get("code") or "问题项").strip()
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
            )
            if resolved_summary:
                plan_model = plan_model.model_copy(
                    update={
                        "preview_summary": resolved_summary,
                        "facts": {
                            **(getattr(plan_model, "facts", {}) or {}),
                            **resolved_facts,
                            "resolved_apply_payload": _build_resolved_apply_payload(
                                plan_model,
                                volunteer_ids=resolved_ids,
                            ),
                        },
                    }
                )

    if plan_model.stage == "preview" and plan_model.action_family == "add_units":
        atomic = plan_model.atomic_actions[0] if plan_model.atomic_actions else None
        refs = list(atomic.volunteer_ids or []) if atomic else []
        if not refs:
            inferred_refs = _infer_school_major_refs_from_text(ctx, plan_model.user_goal)
            if inferred_refs:
                action_data = atomic.model_dump() if atomic is not None else {"action_type": "add_units"}
                action_data["volunteer_ids"] = inferred_refs
                action_data.setdefault("reason", plan_model.user_goal)
                plan_model = plan_model.model_copy(
                    update={"atomic_actions": [PlanAtomicAction(**action_data)]}
                )
                atomic = plan_model.atomic_actions[0]
                refs = inferred_refs
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
        preview_summary = plan_model.preview_summary or "当前阶段仅分析或预览，不执行实际改动。"
        preview_facts: dict[str, Any] = {}
        if plan_model.stage == "preview" and plan_model.action_family == "move_ordered_unit":
            resolved_summary, resolved_facts = await _build_move_ordered_unit_preview_summary(ctx, plan_model)
            if resolved_summary:
                preview_summary = resolved_summary
                preview_facts = resolved_facts
        elif plan_model.stage == "preview" and plan_model.action_family == "remove_ordered_unit":
            resolved_summary, resolved_facts = await _build_remove_ordered_unit_preview_summary(ctx, plan_model)
            if resolved_summary:
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
    """执行受控 PlanActionPlan。"""
    started_at = time.monotonic()
    logger.info("execute_plan_action: session_id=%s", ctx.deps.sessionid)
    try:
        data, repaired_payload = _load_plan_payload(plan_payload)
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
    if result_data.get("next_step_hints"):
        result_data["next_step_hints"] = [
            f"[LLM_INTERNAL] {hint}" for hint in result_data["next_step_hints"]
        ]
    _remember_recent_plan_execution_result(ctx, result_data)
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
