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
from app.sync.state_sync import PlanningStateSync
from app.tools.plan_orchestration_models import (
    PlanActionPlan,
    PlanExecutionResult,
    PlanReviewIssueTarget,
    normalize_plan_action_payload,
)
from app.tools.plan_orchestration_tool import _goal_requests_structural_rebalance
from app.tools.review_issue_registry import build_review_issue_scopes, match_review_issue_code_from_goal
from app.tools.planning_workflow_tool import (
    _build_compensation_preview_facts,
    _build_plan_adjustment_facts,
    _build_plan_intent_relation_lines,
    _build_plan_status_overview_facts,
    _build_review_result_facts,
    analyze_planning_plan_adjustment,
    merge_planning_state_with_user_profile,
    move_planning_ordered_item,
    pin_planning_ordered_item,
    preview_planning_compensation,
    query_planning_candidate_pool,
    query_planning_draft,
    query_planning_ordered_plan,
    query_planning_plan_overview,
    remove_planning_ordered_items,
    run_planning_review,
    select_planning_ordered_items,
    unpin_planning_ordered_item,
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
    "pin_unit",
    "unpin_unit",
    "replace_units",
    "remove_ordered_unit",
    "sort_ordered_plan",
    "regenerate_order",
    "apply_compensation",
}
_RECENT_PLAN_EXECUTION_TTL_SECONDS = 180.0
_RECENT_PLAN_EXECUTION_RESULTS: dict[tuple[str, str], dict[str, Any]] = {}


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


_UNIT_POSITION_RE = re.compile(r"第\s*(\d+)\s*(?:个)?(?:专业组|组)")


def _extract_unit_position_refs(plan_model: PlanActionPlan) -> list[int]:
    texts = [plan_model.user_goal, plan_model.preview_summary]
    texts.extend(getattr(action, "reason", "") for action in plan_model.atomic_actions or [])
    positions: list[int] = []
    for text in texts:
        for match in _UNIT_POSITION_RE.finditer(str(text or "")):
            value = int(match.group(1))
            if value > 0 and value not in positions:
                positions.append(value)
    return positions


async def _resolve_ordered_unit_ids(ctx: RunContext[RequestContext], plan_model: PlanActionPlan) -> list[str]:
    explicit = _extract_unit_ids(plan_model)
    if explicit:
        return explicit
    positions = _extract_unit_position_refs(plan_model)
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
    return str(unit.get("schoolName") or unit.get("name") or unit.get("unitId") or "该专业组").strip()


def _unit_major_count(unit: dict[str, Any] | None) -> int:
    unit = unit or {}
    majors = unit.get("majorItems") or unit.get("items") or []
    return len(majors) if isinstance(majors, list) else 0


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
        position_refs = _extract_unit_position_refs(plan_model)
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
            return None, {}

        unit_name = _unit_display_name(source_unit)
        major_count = _unit_major_count(source_unit)
        count_text = f"，组内共 {major_count} 个专业" if major_count > 0 else ""
        source_text = f"第 {source_position} 个专业组" if source_position else "当前定位到的专业组"
        target_text = f"第 {int(target_position)} 个专业组位置"
        summary = _format_preview_sections(
            ("定位结果", [f"会整体移动{source_text}：{unit_name}{count_text}，目标是移动到{target_text}。"]),
            ("位置口径", ["这里的“第几个”按专业组顺序计算，不是按单条志愿位置计算。"]),
            ("执行影响", ["该组内专业会保持连续，组内专业顺序不变。"]),
        )
        return summary, {
            "source_unit_id": source_unit_id,
            "source_unit_name": unit_name,
            "source_unit_position": source_position,
            "target_unit_position": int(target_position),
            "source_unit_major_count": major_count,
            "position_semantics": "unit_position_not_item_position",
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
        position_refs = _extract_unit_position_refs(plan_model)
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
            return None, {}

        unit_name = _unit_display_name(source_unit)
        major_count = _unit_major_count(source_unit)
        count_text = f"，组内共 {major_count} 个专业" if major_count > 0 else ""
        source_text = f"第 {source_position} 个专业组" if source_position else "当前定位到的专业组"
        removed_count_text = f"{major_count} 个专业 / 1 个专业组" if major_count > 0 else "1 个专业组"
        summary = _format_preview_sections(
            ("定位结果", [f"会整体删除{source_text}：{unit_name}{count_text}。"]),
            ("位置口径", ["这里的“第几个”按专业组顺序计算，不是按单条志愿位置计算。"]),
            ("执行影响", [f"该组内专业会一并移出，后续专业组前移，方案数量将减少 {removed_count_text}。"]),
        )
        return summary, {
            "source_unit_id": source_unit_id,
            "source_unit_name": unit_name,
            "source_unit_position": source_position,
            "source_unit_major_count": major_count,
            "position_semantics": "unit_position_not_item_position",
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


def _format_preview_sections(*sections: tuple[str, list[str] | None] | tuple[str, str | None]) -> str:
    blocks: list[str] = []
    for title, content in sections:
        if not content:
            continue
        display_title = f"**{title}**"
        if isinstance(content, list):
            lines = [str(line or "").strip() for line in content if str(line or "").strip()]
            if not lines:
                continue
            blocks.append(f"{display_title}\n" + "\n".join(f"- {line}" for line in lines))
        else:
            text = str(content or "").strip()
            if not text:
                continue
            blocks.append(f"{display_title}\n{text}")
    return "\n\n".join(blocks)


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
    return f"{text}\n\n需要你确认后才会执行。"


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


def _goal_requests_replacement(text: str | None) -> bool:
    compact = str(text or "").strip()
    return any(token in compact for token in ("换成", "替换成", "补回", "补上", "补入", "保持", "补齐", "凑满"))


def _major_base_name(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return re.split(r"[（(]", text, maxsplit=1)[0].strip()


_MAJOR_ALIAS_BY_BASE_NAME = {
    "计算机科学与技术": ["计科", "计算机"],
    "软件工程": ["软件"],
    "通信工程": ["通信"],
    "统计学": ["统计"],
    "汉语言文学": ["汉语言", "中文"],
    "会计学": ["会计"],
    "财务管理": ["财管"],
    "工商管理": ["工商"],
    "临床医学": ["临床"],
    "口腔医学": ["口腔"],
    "中医学": ["中医"],
    "针灸推拿学": ["针推", "针灸推拿"],
    "土木工程": ["土木"],
    "电气工程及其自动化": ["电气"],
    "数据科学与大数据技术": ["大数据"],
    "电子信息工程": ["电子信息"],
    "机械设计制造及其自动化": ["机械"],
}


_SCHOOL_SUFFIX_ALIAS_RULES = [
    ("师范大学", "师大"),
    ("工业大学", "工大"),
    ("农业大学", "农大"),
    ("医科大学", "医大"),
    ("财经大学", "财大"),
    ("外国语大学", "外大"),
    ("科技大学", "科大"),
    ("交通大学", "交大"),
    ("邮电大学", "邮电"),
    ("理工大学", "理工"),
    ("工程学院", "工程"),
]


_SCHOOL_PREFIX_SHORT_NAMES = {
    "北京": "北",
    "上海": "上",
    "南京": "南",
    "武汉": "武",
    "湖北": "湖",
    "湖南": "湖",
    "广西": "桂",
    "广东": "粤",
    "山东": "鲁",
    "山西": "晋",
    "河北": "冀",
    "河南": "豫",
    "四川": "川",
    "重庆": "渝",
    "天津": "津",
    "浙江": "浙",
    "江苏": "苏",
    "安徽": "皖",
    "福建": "闽",
    "江西": "赣",
    "陕西": "陕",
    "辽宁": "辽",
    "吉林": "吉",
    "黑龙江": "黑",
    "云南": "云",
    "贵州": "贵",
    "甘肃": "甘",
    "青海": "青",
    "宁夏": "宁",
    "新疆": "新",
    "内蒙古": "蒙",
    "西藏": "藏",
    "海南": "琼",
}


def _major_alias_variants(value: Any) -> list[str]:
    base_name = _major_base_name(value)
    if not base_name:
        return []
    variants = list(_MAJOR_ALIAS_BY_BASE_NAME.get(base_name, []))
    target_token = _major_target_token(base_name)
    if target_token and target_token != base_name:
        variants.append(target_token)
    return list(dict.fromkeys(variant for variant in variants if variant))


def _school_alias_variants(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    base_name = re.sub(r"\s*[（(][^()（）]*[)）]\s*$", "", text).strip()
    base_name = re.sub(r"\s*(?:第?\d+组|[A-Za-z0-9]+专业组|第?\d+专业组|专业组)\s*$", "", base_name).strip()
    if not base_name:
        return []

    aliases: list[str] = []
    for suffix, suffix_alias in _SCHOOL_SUFFIX_ALIAS_RULES:
        if not base_name.endswith(suffix):
            continue
        prefix = base_name[: -len(suffix)].strip()
        if not prefix:
            continue
        aliases.append(f"{prefix}{suffix_alias}")
        short_prefix = _SCHOOL_PREFIX_SHORT_NAMES.get(prefix)
        if short_prefix:
            aliases.append(f"{short_prefix}{suffix_alias[:1]}")
    return list(dict.fromkeys(alias for alias in aliases if alias and alias != base_name))


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


def _contains_school_scope(text: str) -> bool:
    compact = str(text or "").strip()
    return any(token in compact for token in ("大学", "学院", "学校", "专业组", "校区"))


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


def _extract_requested_major_targets_from_refs(items: list[dict[str, Any]]) -> list[str]:
    targets: list[str] = []
    for item in items:
        major_name = _major_base_name(item.get("majorName"))
        if major_name and major_name not in targets:
            targets.append(major_name)
    return targets


def _should_expand_replace_refs_by_major_targets(user_goal: str, major_targets: list[str]) -> bool:
    if not user_goal or not major_targets:
        return False
    if _contains_school_scope(user_goal):
        return False
    compact_goal = _compact_ref_text(user_goal)
    normalized_targets = [
        _compact_ref_text(_major_target_token(target))
        for target in major_targets
        if _major_target_token(target)
    ]
    if not normalized_targets:
        return False
    return all(target in compact_goal for target in normalized_targets)


async def _resolve_ordered_volunteer_refs(
    ctx: RunContext[RequestContext],
    refs: list[str],
    *,
    broad_goal_text: str | None = None,
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

    if resolved:
        requested_items = [item_by_id[volunteer_id] for volunteer_id in resolved if volunteer_id in item_by_id]
        major_targets = _extract_requested_major_targets_from_refs(requested_items)
        goal_text = broad_goal_text or _latest_user_text(ctx)
        if _should_expand_replace_refs_by_major_targets(goal_text, major_targets):
            expanded_ids = list(resolved)
            for item in items:
                item_major = _major_base_name(item.get("majorName"))
                if item_major and item_major in major_targets:
                    volunteer_id = str(item.get("volunteerId") or "").strip()
                    if volunteer_id and volunteer_id not in expanded_ids:
                        expanded_ids.append(volunteer_id)
            resolved = expanded_ids
    return resolved, missing


async def _load_ordered_items_by_id(ctx: RunContext[RequestContext]) -> dict[str, dict[str, Any]]:
    try:
        result = await _get_planning_ordered_plan_request(ctx.deps.sessionid)
    except Exception:
        logger.warning("load ordered items for display failed: session_id=%s", ctx.deps.sessionid, exc_info=True)
        return {}
    if result.get("code") != 0:
        return {}
    items = (result.get("data") or {}).get("items") or []
    item_by_id: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        volunteer_id = str(item.get("volunteerId") or "").strip()
        if volunteer_id:
            item_by_id[volunteer_id] = item
    return item_by_id


async def _load_ordered_plan_count_context(ctx: RunContext[RequestContext]) -> dict[str, int]:
    try:
        result = await _get_planning_ordered_plan_request(ctx.deps.sessionid)
    except Exception:
        logger.warning("load ordered plan count context failed: session_id=%s", ctx.deps.sessionid, exc_info=True)
        return {}
    if result.get("code") != 0:
        return {}
    data = result.get("data") or {}
    summary = data.get("summary") or {}
    items = data.get("items") or []
    current_total = _summary_total(summary)
    if not current_total and not summary:
        current_total = len(items)
    target_total = summary.get("targetUnitCount") or summary.get("targetCount") or 0
    context: dict[str, int] = {}
    if summary or items or target_total:
        context["current_total"] = int(current_total)
    if target_total:
        context["target_total"] = int(target_total)
    return context


def _item_display_name(item: dict[str, Any] | None, fallback: str = "这条志愿") -> str:
    item = item or {}
    school_name = str(item.get("schoolName") or "").strip()
    major_name = str(item.get("majorName") or "").strip()
    source_parts = [part for part in (school_name, _major_base_name(major_name) or major_name) if part]
    return "-".join(source_parts) if source_parts else fallback


def _append_preview_impact(summary: str, impact: str) -> str:
    summary = (summary or "").strip()
    impact = (impact or "").strip()
    if not summary or not impact or impact in summary:
        return summary
    return f"{summary}\n\n{impact}"


def _format_action_preview(
    *,
    result_line: str,
    impact_lines: list[str] | None = None,
    extra_sections: list[tuple[str, list[str]]] | None = None,
) -> str:
    sections: list[tuple[str, list[str] | None]] = [("定位结果", [result_line])]
    sections.extend(extra_sections or [])
    if impact_lines:
        sections.append(("执行影响", impact_lines))
    return _format_preview_sections(*sections)


async def _build_move_unit_preview_summary(
    ctx: RunContext[RequestContext],
    plan_model: PlanActionPlan,
    resolved_ids: list[str],
) -> tuple[str, dict[str, Any]]:
    atomic = _first_atomic_action(plan_model)
    target_position = getattr(atomic, "target_position", None) if atomic is not None else None
    target_text = f"第{int(target_position)}位" if target_position is not None else "指定位置"
    item_by_id = await _load_ordered_items_by_id(ctx)
    item = item_by_id.get(resolved_ids[0]) if resolved_ids else None
    if item:
        current_position = item.get("position")
        source_text = _item_display_name(item)
        position_text = f"当前在第{int(current_position)}位，" if current_position is not None else ""
        result_line = f"已定位到 {source_text}，{position_text}会移动到{target_text}。"
    else:
        result_line = f"已定位到当前方案中的指定志愿，会移动到{target_text}。"
    summary = _format_action_preview(
        result_line=result_line,
        impact_lines=["执行后会改变方案顺序和导出顺序。", "审查状态会进入待重新审查。"],
    )
    facts = {
        "resolved_apply_payload": _build_resolved_apply_payload(
            plan_model,
            volunteer_ids=resolved_ids,
        )
    }
    return summary, facts


async def _build_remove_units_preview_summary(
    ctx: RunContext[RequestContext],
    plan_model: PlanActionPlan,
    resolved_ids: list[str],
) -> tuple[str, dict[str, Any]]:
    item_by_id = await _load_ordered_items_by_id(ctx)
    labels = [
        _item_display_name(item_by_id.get(volunteer_id))
        for volunteer_id in resolved_ids[:3]
        if volunteer_id
    ]
    if not labels:
        result_line = "已定位到当前方案中的指定志愿，会从当前方案中移出。"
    elif len(resolved_ids) == 1:
        result_line = f"已定位到当前方案里的 {labels[0]}，会从当前方案中移出。"
    else:
        extra_text = f"等 {len(resolved_ids)} 条志愿" if len(resolved_ids) > len(labels) else f"{len(resolved_ids)} 条志愿"
        result_line = f"已定位到当前方案里的 {'、'.join(labels)}，会从当前方案中移出，共 {extra_text}。"
    summary = _format_action_preview(
        result_line=result_line,
        impact_lines=["执行后会减少方案数量。", "会影响导出顺序。", "审查状态会进入待重新审查。"],
    )
    facts = {
        "resolved_apply_payload": _build_resolved_apply_payload(
            plan_model,
            volunteer_ids=resolved_ids,
        )
    }
    return summary, facts


async def _load_candidate_items_by_id(
    ctx: RunContext[RequestContext],
    refs: list[str],
) -> dict[str, dict[str, Any]]:
    items_by_id: dict[str, dict[str, Any]] = {}
    for ref in refs:
        for item in await _candidate_items_for_ref(ctx, ref):
            if not isinstance(item, dict):
                continue
            volunteer_id = str(item.get("volunteerId") or "").strip()
            if volunteer_id and volunteer_id not in items_by_id:
                items_by_id[volunteer_id] = item
    return items_by_id


async def _build_add_units_preview_summary(
    ctx: RunContext[RequestContext],
    plan_model: PlanActionPlan,
    refs: list[str],
    resolved_ids: list[str],
) -> tuple[str, dict[str, Any]]:
    item_by_id = await _load_candidate_items_by_id(ctx, refs)
    count_context = await _load_ordered_plan_count_context(ctx)
    labels = [
        _item_display_name(item_by_id.get(volunteer_id), fallback="这条候选志愿")
        for volunteer_id in resolved_ids[:3]
        if volunteer_id
    ]
    if not labels:
        result_line = "已在候选里定位到指定志愿，会加入当前方案。"
    elif len(resolved_ids) == 1:
        result_line = f"已在候选里定位到 {labels[0]}，会加入当前方案。"
    else:
        extra_text = f"等 {len(resolved_ids)} 条候选志愿" if len(resolved_ids) > len(labels) else f"{len(resolved_ids)} 条候选志愿"
        result_line = f"已在候选里定位到 {'、'.join(labels)}，会加入当前方案，共 {extra_text}。"
    has_current_total = "current_total" in count_context
    current_total = count_context.get("current_total", 0)
    target_total = count_context.get("target_total")
    add_count = len(resolved_ids)
    count_lines: list[str] = []
    if has_current_total and add_count:
        expected_total = current_total + add_count
        if target_total:
            count_lines.append(f"当前方案已有 {current_total}/{target_total} 个志愿，本次预计增加 {add_count} 个，约 {expected_total}/{target_total}。")
        else:
            count_lines.append(f"当前方案已有 {current_total} 个志愿，本次预计增加 {add_count} 个。")
    extra_sections = [("数量变化", count_lines)] if count_lines else []
    summary = _format_action_preview(
        result_line=result_line,
        extra_sections=extra_sections,
        impact_lines=["执行后会更新方案数量和导出内容。", "审查状态会进入待重新审查。"],
    )
    facts = {
        "resolved_apply_payload": _build_resolved_apply_payload(
            plan_model,
            volunteer_ids=resolved_ids,
        )
    }
    if has_current_total:
        facts["current_ordered_total"] = current_total
        facts["expected_ordered_total"] = current_total + add_count
    if target_total:
        facts["target_total"] = target_total
    if add_count:
        facts["add_count"] = add_count
    return summary, facts


def _ordered_ref_resolution_message(missing_text: str, action_label: str) -> str:
    return (
        f"我还没有定位到这些志愿在当前方案里的真实编号：{missing_text}。"
        f"为避免误删或误重排，请先在方案里点选要{action_label}的志愿，"
        "或让我先按当前方案重新定位后再给你确认。"
    )


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
        f"我还没有在候选里唯一定位到这些志愿：{missing_text}。"
        "为避免误加，请先在候选列表里点选要加入方案的志愿，"
        "或补充专业组、城市、学校全称等信息后我再给你确认。"
    )


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


async def _candidate_items_for_ref(ctx: RunContext[RequestContext], ref: str) -> list[dict[str, Any]]:
    session_id = ctx.deps.sessionid
    state_items: list[dict[str, Any]] = []
    try:
        state_result = await _get_planning_state_request(session_id)
        state = state_result.get("data") or {} if state_result.get("code") == 0 else {}
        raw_items = ((state.get("candidatePoolState") or {}).get("items") or [])
        state_items = [item for item in raw_items if isinstance(item, dict)]
    except Exception:
        logger.warning("load candidate state for ref resolution failed: session_id=%s", session_id, exc_info=True)

    school_keyword, major_keyword = _split_school_major_ref(ref)
    if not school_keyword and not major_keyword:
        return state_items

    queried_items: list[dict[str, Any]] = []
    try:
        query_result = await _query_planning_candidate_pool_request(
            _DEFAULT_TENANT_ID,
            session_id,
            school_keywords=[school_keyword] if school_keyword else [],
            major_keywords=[major_keyword] if major_keyword else [],
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
    for item in [*queried_items, *state_items]:
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

        items = await _candidate_items_for_ref(ctx, text)
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

        volunteer_id = None
        exact_matches = exact_candidates.get(text) or []
        if len(exact_matches) == 1:
            volunteer_id = exact_matches[0]
        compact_ref = _compact_ref_text(text)
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
    issue_code = match_review_issue_code_from_goal(plan_model.user_goal, review_issues)
    if not issue_code:
        return None
    scope_mode = "narrowed_issue" if _contains_school_scope(plan_model.user_goal) else "full_issue"
    return PlanReviewIssueTarget(code=issue_code, scope_mode=scope_mode)


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
    goal_text = str(plan_model.user_goal or "").strip()
    if any(token in goal_text for token in ("保底", "更稳", "压下来", "压冲区", "补北京", "本地保底")):
        return True
    return False


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
    "admissionRatio": "录取率低的排在前面",
    "schoolRank": "排名靠前的排在前面",
    "finalScore": "推荐系数高的排在前面",
}


def _infer_ordered_sort_field(plan_model: PlanActionPlan) -> str:
    atomic = plan_model.atomic_actions[0] if plan_model.atomic_actions else None
    raw_values = []
    if atomic:
        raw_values.extend([
            atomic.filters.get("sort_field"),
            atomic.filters.get("sortField"),
            atomic.filters.get("field"),
            atomic.reason,
        ])
    raw_values.extend([plan_model.user_goal, plan_model.preview_summary])
    joined = " ".join(str(value or "") for value in raw_values)
    for alias, field in _SORT_FIELD_ALIASES.items():
        if alias and alias in joined:
            return field
    return "admissionRatio"


def _enrich_sort_preview_summary(plan_model: PlanActionPlan, summary: str) -> str:
    sort_field = _infer_ordered_sort_field(plan_model)
    label = _SORT_FIELD_LABELS.get(sort_field, "录取率")
    direction = _SORT_FIELD_DIRECTIONS.get(sort_field, "录取率低的排在前面")
    summary = (summary or "").strip()
    action_summary = f"会按{label}重新排序当前方案。"
    if summary and "重新排序当前方案" not in summary:
        action_summary = summary
    return _format_preview_sections(
        ("排序动作", [action_summary]),
        ("排序方式", [f"{direction}。"]),
        ("执行影响", ["会实际改变方案顺序和导出顺序。", "审查状态会进入待重新审查。"]),
    )


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


async def _move_ordered_unit(ctx: RunContext[RequestContext], plan_model: PlanActionPlan) -> tuple[bool, str, list[str]]:
    session_id = ctx.deps.sessionid
    started_at = time.monotonic()
    resolve_started_at = time.monotonic()
    unit_ids = await _resolve_ordered_unit_ids(ctx, plan_model)
    resolve_duration_ms = int((time.monotonic() - resolve_started_at) * 1000)
    action = _first_atomic_action(plan_model)
    target_position = getattr(action, "target_position", None)
    if not unit_ids:
        log_event(
            "plan_ordered_unit_mutation_timing",
            sessionId=session_id,
            actionFamily="move_ordered_unit",
            status="blocked",
            reason="missing_unit_ids",
            resolveUnitDurationMs=resolve_duration_ms,
            mutationRequestDurationMs=0,
            totalDurationMs=int((time.monotonic() - started_at) * 1000),
        )
        return False, "还没有定位到要移动的专业组。请说明专业组名称或第几个专业组。", unit_ids
    if target_position is None:
        log_event(
            "plan_ordered_unit_mutation_timing",
            sessionId=session_id,
            actionFamily="move_ordered_unit",
            status="blocked",
            reason="missing_target_position",
            unitIds=unit_ids,
            resolveUnitDurationMs=resolve_duration_ms,
            mutationRequestDurationMs=0,
            totalDurationMs=int((time.monotonic() - started_at) * 1000),
        )
        return False, "还没有定位到目标位置。请说明要移动到第几位。", unit_ids
    try:
        mutation_started_at = time.monotonic()
        result = await _move_planning_ordered_plan_unit_request(
            _DEFAULT_TENANT_ID,
            session_id,
            unit_ids[0],
            int(target_position),
        )
        mutation_duration_ms = int((time.monotonic() - mutation_started_at) * 1000)
        if not _internal_mutation_ok(result):
            log_event(
                "plan_ordered_unit_mutation_timing",
                sessionId=session_id,
                actionFamily="move_ordered_unit",
                status="error",
                reason="backend_mutation_failed",
                unitIds=unit_ids,
                targetPosition=int(target_position),
                resolveUnitDurationMs=resolve_duration_ms,
                mutationRequestDurationMs=mutation_duration_ms,
                totalDurationMs=int((time.monotonic() - started_at) * 1000),
            )
            return False, "专业组移动失败，请稍后重试或改用页面操作。", unit_ids
        data = (result or {}).get("data") or {}
        log_event(
            "plan_ordered_unit_mutation_timing",
            sessionId=session_id,
            actionFamily="move_ordered_unit",
            status="success",
            unitIds=unit_ids,
            targetPosition=int(target_position),
            responseVersion=data.get("version"),
            resolveUnitDurationMs=resolve_duration_ms,
            mutationRequestDurationMs=mutation_duration_ms,
            totalDurationMs=int((time.monotonic() - started_at) * 1000),
        )
        return True, str(data.get("message") or result.get("message") or f"已将该专业组移动到第 {target_position} 位，方案顺序已更新。"), unit_ids
    except Exception:
        log_event(
            "plan_ordered_unit_mutation_timing",
            sessionId=session_id,
            actionFamily="move_ordered_unit",
            status="error",
            reason="exception",
            unitIds=unit_ids,
            targetPosition=target_position,
            resolveUnitDurationMs=resolve_duration_ms,
            mutationRequestDurationMs=None,
            totalDurationMs=int((time.monotonic() - started_at) * 1000),
        )
        logger.exception("_move_ordered_unit failed: session_id=%s unit_ids=%s target=%s", session_id, unit_ids, target_position)
        return False, "专业组移动失败，请稍后重试或改用页面操作。", unit_ids


async def _remove_ordered_units(ctx: RunContext[RequestContext], plan_model: PlanActionPlan) -> tuple[bool, str, list[str]]:
    session_id = ctx.deps.sessionid
    started_at = time.monotonic()
    resolve_started_at = time.monotonic()
    unit_ids = await _resolve_ordered_unit_ids(ctx, plan_model)
    resolve_duration_ms = int((time.monotonic() - resolve_started_at) * 1000)
    if not unit_ids:
        log_event(
            "plan_ordered_unit_mutation_timing",
            sessionId=session_id,
            actionFamily="remove_ordered_unit",
            status="blocked",
            reason="missing_unit_ids",
            resolveUnitDurationMs=resolve_duration_ms,
            mutationRequestDurationMs=0,
            totalDurationMs=int((time.monotonic() - started_at) * 1000),
        )
        return False, "还没有定位到要删除的专业组。请说明专业组名称或第几个专业组。", unit_ids
    try:
        mutation_started_at = time.monotonic()
        result = await _remove_planning_ordered_plan_units_request(
            _DEFAULT_TENANT_ID,
            session_id,
            unit_ids,
        )
        mutation_duration_ms = int((time.monotonic() - mutation_started_at) * 1000)
        if not _internal_mutation_ok(result):
            log_event(
                "plan_ordered_unit_mutation_timing",
                sessionId=session_id,
                actionFamily="remove_ordered_unit",
                status="error",
                reason="backend_mutation_failed",
                unitIds=unit_ids,
                resolveUnitDurationMs=resolve_duration_ms,
                mutationRequestDurationMs=mutation_duration_ms,
                totalDurationMs=int((time.monotonic() - started_at) * 1000),
            )
            return False, "专业组删除失败，请稍后重试或改用页面操作。", unit_ids
        data = (result or {}).get("data") or {}
        log_event(
            "plan_ordered_unit_mutation_timing",
            sessionId=session_id,
            actionFamily="remove_ordered_unit",
            status="success",
            unitIds=unit_ids,
            responseVersion=data.get("version"),
            resolveUnitDurationMs=resolve_duration_ms,
            mutationRequestDurationMs=mutation_duration_ms,
            totalDurationMs=int((time.monotonic() - started_at) * 1000),
        )
        return True, str(data.get("message") or result.get("message") or f"已从方案中删除 {len(unit_ids)} 个专业组，方案顺序已更新。"), unit_ids
    except Exception:
        log_event(
            "plan_ordered_unit_mutation_timing",
            sessionId=session_id,
            actionFamily="remove_ordered_unit",
            status="error",
            reason="exception",
            unitIds=unit_ids,
            resolveUnitDurationMs=resolve_duration_ms,
            mutationRequestDurationMs=None,
            totalDurationMs=int((time.monotonic() - started_at) * 1000),
        )
        logger.exception("_remove_ordered_units failed: session_id=%s unit_ids=%s", session_id, unit_ids)
        return False, "专业组删除失败，请稍后重试或改用页面操作。", unit_ids



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
        next_step_hints=next_step_hints,
        facts=result.facts,
    )


async def _execute_plan_action_model(
    ctx: RunContext[RequestContext],
    plan_model: PlanActionPlan,
) -> PlanExecutionResult:
    if plan_model.action_family == "regenerate_order" and _goal_requests_structural_rebalance(plan_model.user_goal):
        return PlanExecutionResult(
            applied=False,
            action_family=plan_model.action_family,
            stage="analyze",
            result_kind="preview_only",
            context_summary=plan_model.context_summary,
            summary=(
                "这类请求不是单纯重排，而是带了明确结构目标：要在总数不变的前提下提高保区、压低冲区。"
                "当前还需要先定位准备替换的那批冲区志愿，再生成可确认的结构调整预览。"
            ),
            reply_focus=["preview_only", "structural_rebalance_requires_scope"],
            next_step_hints=["先明确要替换的冲区范围，再生成可确认的结构调整预览。"],
            facts=_facts_with_planning_version({}, ctx),
        )
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
        if "existing_plan" in missing_inputs:
            missing_text = (
                "当前还没有可审查或可调整的方案。你可以先生成一版基础方案，"
                "等方案出来后我再帮你审查风险、替换冲突项或调整顺序。"
            )
            next_hints = ["先生成一版基础方案，再继续审查或调整。"]
        else:
            missing_text = f"这一步还缺少必要信息：{', '.join(missing_inputs)}。请先补充清楚后再继续。"
            next_hints = ["先补齐缺失输入，再继续执行当前方案动作。"]
        return PlanExecutionResult(
            applied=False,
            action_family=plan_model.action_family,
            stage=plan_model.stage,
            result_kind="error",
            context_summary=plan_model.context_summary,
            summary=missing_text,
            reply_focus=["missing_inputs"],
            next_step_hints=next_hints,
        )

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
            and not _goal_requests_replacement(plan_model.user_goal)
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
                    f"我还没有定位到这些志愿在当前方案里的真实编号：{missing_text}。"
                    "请先明确当前方案里的具体志愿，或让我先重新定位后再给你确认。"
                ),
                reply_focus=["missing_inputs", "needs_volunteer_selection"],
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
                    next_step_hints=["先定位当前方案里的真实 volunteerId，再生成可确认的移除预览。"],
                )
            preview_summary, preview_facts = await _build_remove_units_preview_summary(ctx, plan_model, resolved_ids)
            return PlanExecutionResult(
                applied=False,
                action_family=plan_model.action_family,
                stage=plan_model.stage,
                result_kind="preview_only",
                context_summary=plan_model.context_summary,
                summary=_with_confirmation_hint(preview_summary),
                reply_focus=["preview_only", "confirmation_required"],
                next_step_hints=["先向用户说明已定位到哪条志愿；用户确认后，再执行移出方案动作。"],
                facts=_facts_with_planning_version(preview_facts, ctx),
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
                    next_step_hints=["先定位当前方案里的真实 volunteerId，再生成可确认的位置调整预览。"],
                )
            preview_summary, preview_facts = await _build_move_unit_preview_summary(ctx, plan_model, resolved_ids)
            return PlanExecutionResult(
                applied=False,
                action_family=plan_model.action_family,
                stage=plan_model.stage,
                result_kind="preview_only",
                context_summary=plan_model.context_summary,
                summary=_with_confirmation_hint(preview_summary),
                reply_focus=["preview_only", "confirmation_required"],
                next_step_hints=["先向用户说明已定位到哪条志愿和目标位置；用户确认后，再执行移动方案动作。"],
                facts=_facts_with_planning_version(preview_facts, ctx),
            )

    if plan_model.stage == "preview" and plan_model.action_family == "add_units":
        atomic = plan_model.atomic_actions[0] if plan_model.atomic_actions else None
        refs = list(atomic.volunteer_ids or []) if atomic else []
        if refs:
            existing_ids: list[str] = []
            if any(any(ord(char) > 127 for char in str(ref or "")) for ref in refs):
                existing_ids, _ = await _resolve_ordered_volunteer_refs(ctx, refs)
            resolved_ids, missing_refs = await _resolve_candidate_volunteer_refs(ctx, refs)
            resolved_ids = [volunteer_id for volunteer_id in resolved_ids if volunteer_id not in set(existing_ids)]
            if existing_ids and not resolved_ids and not missing_refs:
                refs_text = "、".join(refs[:5])
                return PlanExecutionResult(
                    applied=False,
                    action_family=plan_model.action_family,
                    stage=plan_model.stage,
                    result_kind="no_change",
                    context_summary=plan_model.context_summary,
                    summary=f"{refs_text} 已经在当前方案中，无需重复加入。",
                    reply_focus=["already_in_plan"],
                    next_step_hints=["告诉用户目标已经在方案中，不要说已新增。可提示继续排序或调整。"],
                    facts=_facts_with_planning_version({}, ctx),
                )
            if missing_refs or not resolved_ids:
                missing_text = "、".join(missing_refs[:5]) if missing_refs else "要加入的候选志愿"
                return PlanExecutionResult(
                    applied=False,
                    action_family=plan_model.action_family,
                    stage=plan_model.stage,
                    result_kind="error",
                    context_summary=plan_model.context_summary,
                    summary=_candidate_ref_resolution_message(missing_text),
                    reply_focus=["missing_inputs", "needs_candidate_selection"],
                    next_step_hints=["先定位候选池里的真实 volunteerId，再生成可确认的加入预览。"],
                    facts=_facts_with_planning_version({}, ctx),
                )
            preview_summary, preview_facts = await _build_add_units_preview_summary(ctx, plan_model, refs, resolved_ids)
            return PlanExecutionResult(
                applied=False,
                action_family=plan_model.action_family,
                stage=plan_model.stage,
                result_kind="preview_only",
                context_summary=plan_model.context_summary,
                summary=_with_confirmation_hint(preview_summary),
                reply_focus=["preview_only", "confirmation_required"],
                next_step_hints=["先向用户说明将要加入哪些候选；用户确认后，再执行加入方案动作。"],
                facts=_facts_with_planning_version(preview_facts, ctx),
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
        elif plan_model.stage == "preview" and plan_model.action_family == "sort_ordered_plan":
            preview_summary = _enrich_sort_preview_summary(plan_model, preview_summary)
        if plan_model.stage == "preview" and plan_model.action_family in _MUTATING_ACTION_FAMILIES:
            preview_summary = _with_confirmation_hint(preview_summary)
        return PlanExecutionResult(
            applied=False,
            action_family=plan_model.action_family,
            stage=plan_model.stage,
            result_kind="preview_only",
            context_summary=plan_model.context_summary,
            summary=preview_summary,
            reply_focus=["preview_only"],
            next_step_hints=["如果用户确认执行，再进入实际方案动作。"] if plan_model.stage == "preview" else [],
            facts=_facts_with_planning_version(preview_facts, ctx),
        )

    if plan_model.action_family == "sort_ordered_plan":
        success, state_summary = await _sort_ordered_plan(ctx, plan_model)
        sort_field = _infer_ordered_sort_field(plan_model)
        return PlanExecutionResult(
            applied=success,
            action_family=plan_model.action_family,
            stage=plan_model.stage,
            result_kind="mutation_result" if success else "error",
            executed_actions=[{"action": "sort_ordered_plan", "sortField": sort_field}] if success else [],
            workspace_refresh_targets=["ordered", "review"] if success else [],
            context_summary=plan_model.context_summary,
            state_summary=state_summary,
            summary=state_summary,
            reply_focus=["mutation_result", "plan_update", "sort_ordered_plan"] if success else ["mutation_failed", "sort_ordered_plan"],
            next_step_hints=["说明排序已改变当前方案顺序，并提醒审查状态需要重新确认。"] if success else ["说明这次排序没有执行成功，不要提示方案已经刷新。"],
        )

    if plan_model.action_family == "move_ordered_unit":
        success, state_summary, unit_ids = await _move_ordered_unit(ctx, plan_model)
        log_event(
            "plan_ordered_unit_post_apply_timing",
            sessionId=ctx.deps.sessionid,
            actionFamily=plan_model.action_family,
            status="success" if success else "error",
            unitIds=unit_ids,
            postResolveDurationMs=0,
            reusedPreMutationUnitIds=True,
        )
        return PlanExecutionResult(
            applied=success,
            action_family=plan_model.action_family,
            stage=plan_model.stage,
            result_kind="mutation_result" if success else "error",
            executed_actions=[{"action": "move_ordered_unit", "unitIds": unit_ids}] if success else [],
            workspace_refresh_targets=["ordered", "review"] if success else [],
            context_summary=plan_model.context_summary,
            state_summary=state_summary,
            summary=state_summary,
            reply_focus=["mutation_result", "plan_update", "unit_level_operation"] if success else ["mutation_failed", "unit_level_operation"],
            next_step_hints=["说明专业组已整体移动，并提醒审查状态需要重新确认。"] if success else ["说明这次专业组移动没有执行成功，不要提示方案已经刷新。"],
        )

    if plan_model.action_family == "remove_ordered_unit":
        success, state_summary, unit_ids = await _remove_ordered_units(ctx, plan_model)
        log_event(
            "plan_ordered_unit_post_apply_timing",
            sessionId=ctx.deps.sessionid,
            actionFamily=plan_model.action_family,
            status="success" if success else "error",
            unitIds=unit_ids,
            postResolveDurationMs=0,
            reusedPreMutationUnitIds=True,
        )
        return PlanExecutionResult(
            applied=success,
            action_family=plan_model.action_family,
            stage=plan_model.stage,
            result_kind="mutation_result" if success else "error",
            executed_actions=[{"action": "remove_ordered_unit", "unitIds": unit_ids}] if success else [],
            workspace_refresh_targets=["ordered", "review"] if success else [],
            context_summary=plan_model.context_summary,
            state_summary=state_summary,
            summary=state_summary,
            reply_focus=["mutation_result", "plan_update", "unit_level_operation"] if success else ["mutation_failed", "unit_level_operation"],
            next_step_hints=["说明专业组已从方案移出，并提醒审查状态需要重新确认。"] if success else ["说明这次专业组删除没有执行成功，不要提示方案已经刷新。"],
        )

    # Handler registry dispatch
    from app.handlers import HANDLER_REGISTRY
    _handler = HANDLER_REGISTRY.get(plan_model.action_family)
    if _handler is not None:
        _result = await _handler(ctx, plan_model)
        return await _post_process_handler_result(ctx, plan_model, _result)

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
        data = normalize_plan_action_payload(json.loads(plan_payload))
    except Exception:
        fallback = PlanExecutionResult(
            applied=False,
            action_family="unknown",
            stage="apply",
            result_kind="error",
            context_summary="",
            summary="方案操作数据格式有误，请重新生成操作计划后重试。",
            reply_focus=["missing_plan_payload"],
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
    try:
        plan_model = PlanActionPlan.model_validate(data)
    except Exception:
        fallback = PlanExecutionResult(
            applied=False,
            action_family=str(data.get("action_family") or "unknown"),
            stage=str(data.get("stage") or "apply"),
            result_kind="error",
            context_summary=str(data.get("context_summary") or ""),
            summary="方案操作信息不完整，请先确认操作目标后重试。",
            reply_focus=["missing_plan_payload"],
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
