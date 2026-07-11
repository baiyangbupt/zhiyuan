"""Release 4.0 Zhiyuan Agent tools."""

from __future__ import annotations

import json
import os
import re
import uuid
import asyncio
import contextlib
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Literal, TypedDict
from urllib.parse import urlparse

import aiohttp
from pydantic_ai import RunContext

from app.agent.context import RequestContext, resolve_pending_confirmation
from app.config import BochaSearchConfig
from app.domain import proposal_compiler
from app.domain.career_slots import normalize_career_slots, to_career_label
from app.domain.entity_resolution import EntityResolutionCandidate, EntityResolutionResult
from app.domain.attribute_registry import (
    ATTRIBUTE_REGISTRY,
    attribute_label,
    match_item as match_attribute_item,
    normalize_attribute_filter_key,
    normalize_attribute_filter_values,
)
from app.domain.major_entity_resolver import (
    canonicalize_major_intent_payload,
    major_alias_variants_for_name,
    major_parent_mappings_for_batch,
    resolve_major_entity,
)
from app.domain.region_entity_resolver import REGION_AREA_PROVINCES, resolve_region_entity
from app.domain.school_entity_resolver import resolve_school_entity
from app.schemas.user_profile import UserProfile
from app.tools.review_issue_registry import normalize_review_issue_code
from app.util import internal_client
from app.util.code_enrichment import (
    add_codes_to_profile,
    get_major_codes_async,
    get_province_codes_async,
    get_school_codes_async,
)
from app.zhiyuan_agent.sandbox import _ordered_items_file_from_response, normalize_sandbox_path


NextStep = Literal["respond", "confirm", "clarify", "continue"]
StatePath = Literal["score", "profile", "plan/summary", "pending"]
TopicType = Literal["career", "major", "school", "region"]
CompareEntityType = Literal["major", "school"]
PolicyDomain = Literal[
    "score_batch",
    "eligibility",
    "tuition_budget",
    "enrollment_rules",
    "school_rule",
    "transfer_major",
    "subject_requirement",
    "physical_exam",
    "oral_exam",
    "general",
]
ReviewFocus = Literal["full_review", "risk_only", "tier_balance", "tuition", "career_fit"]
CareerSlot = Literal["system_public_service", "stable_employment", "further_study", "market_employment"]
IntentType = Literal["major", "school", "region", "career", "tuition_budget"]
ConstraintType = Literal["exclude", "only_keep", "must_have"]
PlanScope = Literal["plan", "candidates"]
PendingAction = Literal["confirm", "cancel"]
PendingResolution = Literal["none", "replace_active_pending", "append_to_active_pending", "hold_new_request"]
PlanAction = Literal["add", "remove", "move", "replace", "sort", "generate", "regenerate_order", "pin_lock"]
ReviewIssueCode = Literal[
    "high_tuition",
    "cooperative_program",
    "admission_limit",
    "special_enrollment",
    "probability_inversion",
    "probability_gap",
    "count_validation",
    "edge_score",
    "safety_guard",
    "major_group_safety_intent_alignment",
    "group_inner_safety_guard",
    "tier_gap",
    "low_safety",
    "career_mismatch",
]


class ReplacementSpec(TypedDict, total=False):
    source: str
    keep_dims: list[str]
    improve_dim: str
    improve_dims: list[str]
    exclude_markers: list[str]
    constraint_carryover: bool
    old_tiers: list[str]
    old_provinces: list[str]
    major_keywords: list[str]
    old_min_tuition: int
    old_max_tuition: int
    old_best_school_rank: int
    old_min_admission_ratio: int


_DEFAULT_PLAN_QUERY_LIMIT = 5
_ALLOWED_PLAN_ACTIONS = ["add", "remove", "move", "replace", "sort", "generate", "regenerate_order", "pin_lock"]
_PLAN_SORT_FIELDS = {
    "admission_ratio": "admissionRatio",
    "admission_probability": "admissionRatio",
    "admissionRatio": "admissionRatio",
    "admissionProbability": "admissionRatio",
    "录取率": "admissionRatio",
    "录取概率": "admissionRatio",
    "school_rank": "schoolRank",
    "schoolRank": "schoolRank",
    "school_ranking": "schoolRank",
    "院校排名": "schoolRank",
    "学校排名": "schoolRank",
    "排名": "schoolRank",
    "comprehensive": "finalScore",
    "final_score": "finalScore",
    "finalScore": "finalScore",
    "综合分": "finalScore",
    "综合排序": "finalScore",
    "推荐系数": "finalScore",
    "推荐分": "finalScore",
}
_PLAN_SORT_FIELD_LABELS = {
    "admissionRatio": "录取率",
    "schoolRank": "院校排名（排名靠前优先）",
    "finalScore": "推荐系数（综合分）",
}
_PERSIST_PREVIEW_PENDING = os.getenv("ZHIYUAN_AGENT_PERSIST_PREVIEW_PENDING", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
_SIMULATE_TIER_LABELS = {
    "sprint": "冲",
    "sprints": "冲",
    "safe": "稳",
    "safes": "稳",
    "protect": "保",
    "protects": "保",
}
_SCHOOL_INTENT_ATTRIBUTE_KEYS = (
    "school_nature",
    "school_level",
    "school_category",
    "program_type",
    "school_tag",
)
_MAJOR_INTENT_ATTRIBUTE_KEYS = (
    "major_category",
    "major_tag",
    "program_type",
)
_REGION_INTENT_ATTRIBUTE_KEYS = (
    "province",
    "city",
    "area",
)
_TUITION_BUDGET_INTENT_KEYS = (
    "max_tuition_per_year",
    "min_tuition_per_year",
)
_TUITION_BUDGET_KEY_ALIASES = {
    "maxTuitionPerYear": "max_tuition_per_year",
    "max_tuition": "max_tuition_per_year",
    "maxTuition": "max_tuition_per_year",
    "tuition_max": "max_tuition_per_year",
    "tuitionMax": "max_tuition_per_year",
    "tuition_lte": "max_tuition_per_year",
    "tuitionLte": "max_tuition_per_year",
    "fee_max": "max_tuition_per_year",
    "feeMax": "max_tuition_per_year",
    "minTuitionPerYear": "min_tuition_per_year",
    "min_tuition": "min_tuition_per_year",
    "minTuition": "min_tuition_per_year",
    "tuition_min": "min_tuition_per_year",
    "tuitionMin": "min_tuition_per_year",
    "tuition_gte": "min_tuition_per_year",
    "tuitionGte": "min_tuition_per_year",
    "fee_min": "min_tuition_per_year",
    "feeMin": "min_tuition_per_year",
}
_TUITION_BUDGET_SEMANTIC_KEYS = _TUITION_BUDGET_INTENT_KEYS + tuple(_TUITION_BUDGET_KEY_ALIASES)
_MAJOR_ENTITY_SEMANTIC_KEYS = (
    "major",
    "majors",
    "major_name",
    "major_names",
    "majorName",
    "majorNames",
    "majorList",
    "major_list",
)
_SCHOOL_ENTITY_SEMANTIC_KEYS = (
    "school",
    "schools",
    "college",
    "colleges",
)
_CROSS_DOMAIN_ATTRIBUTE_SUPPLEMENT_EXCLUDED_KEYS = frozenset({"program_type"})
_INTENT_DOMAIN_ATTRIBUTE_KEYS = {
    "school": _SCHOOL_INTENT_ATTRIBUTE_KEYS,
    "major": _MAJOR_INTENT_ATTRIBUTE_KEYS,
    "region": _REGION_INTENT_ATTRIBUTE_KEYS,
}
_INTENT_DOMAIN_SEMANTIC_KEYS = {
    "school": _SCHOOL_ENTITY_SEMANTIC_KEYS + _SCHOOL_INTENT_ATTRIBUTE_KEYS,
    "major": ("level1", "level2", "level3") + _MAJOR_ENTITY_SEMANTIC_KEYS + _MAJOR_INTENT_ATTRIBUTE_KEYS,
    "region": _REGION_INTENT_ATTRIBUTE_KEYS,
    "tuition_budget": _TUITION_BUDGET_SEMANTIC_KEYS,
}
_INTENT_DOMAIN_SECTION = {
    "school": "school_intents",
    "major": "major_intents",
    "region": "city_intents",
    "tuition_budget": "tuition_budget",
}
_INTENT_ATTRIBUTE_KEY_ALIASES = {
    "major_tag": (
        "duration",
        "durations",
        "majorDuration",
        "major_duration",
        "studyDuration",
        "study_duration",
    ),
}
_PLAN_QUERY_CONTROL_KEYS = {
    "include_fields",
    "slice",
    "sort_field",
    "sort_order",
}
_EXPLORE_FALLBACK_DIMENSIONS = {
    "major": [
        "学什么：核心课程和培养方向",
        "做什么：主要就业方向和职业路径",
        "怎么选：选科要求、录取分位段和报考注意点",
        "适配度：结合当前成绩、选科和方案结构判断",
    ],
    "school": [
        "学校定位：层次、隶属和优势学科",
        "录取难度：分数段和位次参考",
        "就业/升学：升学通道、就业去向和地域机会",
        "适配度：结合当前成绩和方案梯度判断",
    ],
    "career": [
        "发展路径：典型职业阶梯和长期空间",
        "对应专业：可进入该方向的专业类别",
        "现实因素：编制、薪资水平和地域差异",
    ],
    "region": [
        "城市机会：产业结构和就业资源",
        "院校供给：可选学校和专业集中度",
        "录取影响：地域选择对冲稳保结构的影响",
    ],
}
_COMPARE_FALLBACK_DIMENSIONS = {
    "major": ["培养方向差异", "核心课程差异", "就业方向差异", "录取和适配注意点"],
    "school": ["学校定位差异", "优势学科差异", "录取难度差异", "城市和升学就业差异"],
}


class ToolResult(TypedDict):
    data: Any
    next_step: NextStep
    message: str | None


def _json(payload: ToolResult) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _turn_started_active_pending(ctx: RunContext[RequestContext]) -> Any | None:
    return resolve_pending_confirmation(ctx.deps)


def _dry_run_state_mutations(ctx: RunContext[RequestContext]) -> bool:
    return bool(getattr(ctx.deps, "dry_run_state_mutations", False))


def _active_pending_conflict_payload(
    ctx: RunContext[RequestContext],
    *,
    requested_kind: str,
    requested_action_family: str,
    requested_text: str = "",
) -> dict[str, Any] | None:
    pending = _turn_started_active_pending(ctx)
    if pending is None:
        return None
    preview_summary = str(getattr(pending, "preview_summary", "") or "").strip()
    kind = str(getattr(pending, "kind", "") or "").strip()
    action_family = str(getattr(pending, "action_family", "") or "").strip()
    detail = f"\n待确认内容：{preview_summary}" if preview_summary else ""
    request_text = str(requested_text or "").strip()
    request_detail = f"\n这轮新诉求：{request_text}" if request_text else ""
    return {
        "data": {
            "reason": "active_pending_conflict",
            "active_pending_kind": kind,
            "active_action_family": action_family,
            "requested_kind": requested_kind,
            "requested_action_family": requested_action_family,
            "pending_created": False,
            "requires_confirmation": False,
        },
        "next_step": "clarify",
        "message": (
            f"当前已经有一项待确认操作正在等待处理。{detail}\n"
            f"{request_detail}\n"
            "这轮新诉求不会覆盖它，也不会再生成第二张待确认卡。"
            "你可以先确认、取消这项待确认内容，或明确说要放弃当前待确认内容后再重新提出新的调整。"
        ),
    }


_ALLOWED_PENDING_RESOLUTIONS = [
    "replace_active_pending",
    "append_to_active_pending",
    "hold_new_request",
]


def _normalize_pending_resolution(value: str | None) -> str:
    normalized = str(value or "none").strip()
    if normalized in {"", "none"}:
        return "none"
    if normalized in set(_ALLOWED_PENDING_RESOLUTIONS):
        return normalized
    return "none"


def _pending_resolution_required_payload(
    ctx: RunContext[RequestContext],
    *,
    requested_kind: str,
    requested_action_family: str,
    requested_text: str = "",
) -> dict[str, Any]:
    pending = _turn_started_active_pending(ctx)
    preview_summary = str(getattr(pending, "preview_summary", "") or "").strip() if pending is not None else ""
    kind = str(getattr(pending, "kind", "") or "").strip() if pending is not None else ""
    action_family = str(getattr(pending, "action_family", "") or "").strip() if pending is not None else ""
    return {
        "data": {
            "reason": "active_pending_requires_resolution",
            "active_pending_kind": kind,
            "active_action_family": action_family,
            "active_pending_summary": preview_summary,
            "requested_kind": requested_kind,
            "requested_action_family": requested_action_family,
            "current_user_text": str(requested_text or "").strip(),
            "allowed_pending_resolution": list(_ALLOWED_PENDING_RESOLUTIONS),
            "pending_created": False,
            "requires_confirmation": False,
        },
        "next_step": "continue",
        "message": (
            "当前已有一项待确认内容。请基于当前用户原话和待确认内容重新判断本轮关系，"
            "并重新调用同一个预览工具，显式传 pending_resolution："
            "replace_active_pending、append_to_active_pending 或 hold_new_request。"
        ),
    }


def _active_pending_append_unsupported_payload(
    ctx: RunContext[RequestContext],
    *,
    requested_kind: str,
    requested_action_family: str,
    requested_text: str = "",
) -> dict[str, Any]:
    pending = _turn_started_active_pending(ctx)
    return {
        "data": {
            "reason": "active_pending_append_unsupported",
            "active_pending_kind": str(getattr(pending, "kind", "") or "").strip() if pending is not None else "",
            "active_action_family": str(getattr(pending, "action_family", "") or "").strip() if pending is not None else "",
            "requested_kind": requested_kind,
            "requested_action_family": requested_action_family,
            "current_user_text": str(requested_text or "").strip(),
            "allowed_pending_resolution": ["replace_active_pending", "hold_new_request"],
            "pending_created": False,
            "requires_confirmation": False,
        },
        "next_step": "continue",
        "message": (
            "当前待确认内容不能和这次新预览自动合并。请重新判断：如果用户要放弃当前待确认项，"
            "传 pending_resolution=\"replace_active_pending\"；如果用户没有明确放弃，传 hold_new_request。"
        ),
    }


def _plan_action_requires_explicit_action_payload(
    *,
    action: Any,
    requested_text: str = "",
) -> dict[str, Any]:
    current_user_text = str(requested_text or "").strip()
    return {
        "data": {
            "reason": "plan_action_requires_explicit_action",
            "action": action,
            "allowed_actions": list(_ALLOWED_PLAN_ACTIONS),
            "current_user_text": current_user_text,
            "retry_required_fields": ["action"],
            "pending_created": False,
            "requires_confirmation": False,
        },
        "next_step": "continue" if current_user_text else "clarify",
        "message": (
            "请基于本轮用户原话重新判断方案动作，并重新调用 preview_plan_action，"
            "显式传 action。若原话确实没有说明动作，再向用户追问。"
            if current_user_text
            else "需要说明是加入、移出、移动、替换、排序、生成方案，还是锁定位置。"
        ),
    }


def _plan_action_requires_move_parameters_payload(
    *,
    reason: str,
    requested_text: str = "",
    targets: list[str] | None = None,
    filters: dict[str, Any] | None = None,
    target_position: int | None = None,
    unit_ids: list[str] | None = None,
) -> dict[str, Any]:
    current_user_text = str(requested_text or "").strip()
    if reason == "plan_action_requires_move_target_position":
        retry_required_fields = ["target_position", "filters.target_tier", "filters.target_ordinal"]
        message = (
            "已经定位到要移动的方案项，但缺少目标位置。请基于本轮用户原话重新调用 "
            "preview_plan_action，补齐 target_position，或在 filters 中补齐 target_tier 与 target_ordinal。"
            "若原话没有说明移动到哪里，再向用户追问。"
        )
        clarify_message = "已经定位到要移动的方案项，还需要说明要移动到第几位。"
    else:
        retry_required_fields = [
            "targets",
            "filters.selector_sort",
            "filters.selector_rank",
            "filters.selector_ordinal",
        ]
        message = (
            "当前移动操作没有唯一定位到要移动的方案项。请基于本轮用户原话重新调用 "
            "preview_plan_action，补齐 targets，或在 filters 中补齐 selector_sort/selector_rank/"
            "selector_ordinal。若原话没有说明按什么选择，再向用户追问。"
        )
        clarify_message = "当前范围里有多个志愿，需要说明按什么选择（如录取率最高、学费最低、最后一个等）。"
    return {
        "data": {
            "reason": reason,
            "action": "move",
            "targets": targets or [],
            "filters": filters or {},
            "target_position": target_position,
            "unit_ids": unit_ids or [],
            "current_user_text": current_user_text,
            "retry_required_fields": retry_required_fields,
            "pending_created": False,
            "requires_confirmation": False,
        },
        "next_step": "continue" if current_user_text else "clarify",
        "message": message if current_user_text else clarify_message,
    }


def _consume_structured_retry_budget(
    ctx: RunContext[RequestContext],
    key: str,
    *,
    max_retries: int = 1,
) -> bool:
    observability = getattr(ctx.deps, "agent_observability", None)
    if not isinstance(observability, dict):
        return False
    counts = observability.setdefault("structuredRetryCounts", {})
    if not isinstance(counts, dict):
        counts = {}
        observability["structuredRetryCounts"] = counts
    current_count = _as_int(counts.get(key))
    if current_count >= max_retries:
        return False
    counts[key] = current_count + 1
    return True


def _plan_action_requires_replace_targets_payload(
    *,
    requested_text: str = "",
    targets: list[str] | None = None,
    filters: dict[str, Any] | None = None,
    review_issue_code: Any = None,
    candidate_targets: list[str] | None = None,
    replacement_spec: dict[str, Any] | None = None,
    missing_targets: list[str] | None = None,
    source_reason: str = "",
) -> dict[str, Any]:
    current_user_text = str(requested_text or "").strip()
    retry_required_fields = [
        "targets",
        "filters",
        "review_issue_code",
        "filters.selector_sort",
        "filters.selector_rank",
        "filters.selector_ordinal",
        "replacement_spec",
    ]
    return {
        "data": {
            "reason": "plan_action_requires_replace_target",
            "source_reason": source_reason,
            "action": "replace",
            "targets": targets or [],
            "filters": filters or {},
            "review_issue_code": review_issue_code or "",
            "candidate_targets": candidate_targets or [],
            "replacement_spec": replacement_spec or {},
            "missing_targets": missing_targets or ["old_plan_item"],
            "current_user_text": current_user_text,
            "retry_required_fields": retry_required_fields,
            "pending_created": False,
            "requires_confirmation": False,
        },
        "next_step": "continue" if current_user_text else "clarify",
        "message": (
            "当前替换动作没有唯一定位到要移出的方案项。请基于本轮用户原话重新调用 "
            "preview_plan_action(action=\"replace\")，补齐 targets，或用 filters、review_issue_code、"
            "selector 定位旧项；如果没有显式候选，同时补齐 replacement_spec。"
            "若原话和上下文确实无法定位，再向用户追问学校、专业或第几个志愿。"
            if current_user_text
            else "替换需要先说明要移出的当前方案项，例如学校、专业或第几个志愿。"
        ),
    }


def _intent_change_requires_attribute_completion_payload(
    *,
    reason: str,
    intent_type: str,
    constraint_type: str,
    requested_text: str = "",
    normalized: dict[str, Any] | None = None,
    merged: dict[str, Any] | None = None,
    missing_attributes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    current_user_text = str(requested_text or "").strip()
    return {
        "data": {
            "reason": reason,
            "intent_type": intent_type,
            "constraint_type": constraint_type,
            "normalized": normalized or {},
            "merged": merged or {},
            "current_user_text": current_user_text,
            "missing_attributes": missing_attributes or [],
            "retry_required_fields": ["positive", "negative", "semantic_requirements"],
            "pending_created": False,
            "requires_confirmation": False,
        },
        "next_step": "continue" if current_user_text else "clarify",
        "message": (
            "请基于 semantic_requirements 重新整理 preview_intent_change 参数，补齐遗漏的明确要/不要属性或标签。"
            "同一句跨多个领域时，可以在同一次 positive/negative payload 中保留跨领域结构化字段，"
            "例如地域诉求同时带院校属性时传 negative={\"province\":[...],\"school_nature\":[...]}。"
            if current_user_text
            else "这次报考要求里有属性或标签没有补齐，请说明完整的要或不要对象。"
        ),
    }


def _intent_change_requires_semantic_requirements_payload(
    *,
    intent_type: str,
    constraint_type: str,
    requested_text: str = "",
    normalized: dict[str, Any] | None = None,
    merged: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current_user_text = str(requested_text or "").strip()
    return {
        "data": {
            "reason": "intent_change_requires_semantic_requirements",
            "intent_type": intent_type,
            "constraint_type": constraint_type,
            "normalized": normalized or {},
            "merged": merged or {},
            "current_user_text": current_user_text,
            "retry_required_fields": ["semantic_requirements", "positive", "negative"],
            "pending_created": False,
            "requires_confirmation": False,
        },
        "next_step": "continue" if current_user_text else "clarify",
        "message": (
            "请先基于本轮用户原话给出 semantic_requirements，再重新调用 preview_intent_change。"
            "如果只是参考方向，传 strength=\"reference\" 且不要强行写入 positive/negative；"
            "如果原话同时有参考方向和明确要/不要项，参考方向用 reference，明确要/不要项必须保留为 "
            "strength=\"explicit\" 或 \"confirmable\" 并补齐对应 positive/negative payload，不能整体降级为 reference。"
            if current_user_text
            else "需要先说明这次要整理成哪类报考要求或参考方向。"
        ),
    }


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, dict):
        candidates = [value.get("name"), value.get("label"), value.get("value")]
        return [str(item).strip() for item in candidates if str(item or "").strip()]
    if not isinstance(value, (list, tuple, set)):
        text = str(value or "").strip()
        return [text] if text else []
    result: list[str] = []
    for item in value:
        if isinstance(item, dict):
            names = _as_list(item)
        else:
            names = _as_list(str(item or ""))
        for name in names:
            if name and name not in result:
                result.append(name)
    return result


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _latest_user_text(ctx: RunContext[RequestContext]) -> str:
    history = getattr(ctx.deps, "chat_history", None)
    if not isinstance(history, list):
        return ""
    for message in reversed(history):
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "").strip().lower() != "user":
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return ""


def _effective_raw_user_text(ctx: RunContext[RequestContext], raw_user_text: str = "") -> str:
    explicit = str(raw_user_text or "").strip()
    if explicit:
        return explicit
    current = str(getattr(ctx.deps, "current_user_text", "") or "").strip()
    if current:
        return current
    return _latest_user_text(ctx)


def _is_success_response(response: Any) -> bool:
    if not isinstance(response, dict):
        return False
    return response.get("code") in {0, "0"} or response.get("success") is True


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_unique(bucket: list[str], value: str) -> None:
    text = str(value or "").strip()
    if text and text not in bucket:
        bucket.append(text)


def _candidate_data(candidate: EntityResolutionCandidate) -> dict[str, Any]:
    data: dict[str, Any] = {
        "name": candidate.canonical_name,
        "source": candidate.source,
        "confidence": candidate.confidence,
    }
    if candidate.level:
        data["level"] = candidate.level
    return data


def _ambiguity_data(result: EntityResolutionResult) -> dict[str, Any]:
    return {
        "raw_text": result.raw_text,
        "entity_type": result.entity_type,
        "candidates": [_candidate_data(candidate) for candidate in result.candidates[:8]],
    }


def _sandbox_unavailable(path: str) -> dict[str, Any]:
    return {
        "available": False,
        "path": path,
        "error": "sandbox_unavailable",
    }


def _response_data(response: Any) -> dict[str, Any]:
    if not isinstance(response, dict):
        return {}
    data = response.get("data")
    if isinstance(data, dict):
        return data
    return response


async def _sandbox_data(ctx: RunContext[RequestContext], path: str) -> dict[str, Any]:
    sandbox = getattr(ctx.deps, "sandbox", None)
    normalized_path = normalize_sandbox_path(path)
    if sandbox is None:
        return _sandbox_unavailable(normalized_path)
    data = await sandbox.read(normalized_path)
    return data if isinstance(data, dict) else {}


async def _score_data(ctx: RunContext[RequestContext]) -> dict[str, Any]:
    return await _sandbox_data(ctx, "score.json")


async def _profile_data(ctx: RunContext[RequestContext]) -> dict[str, Any]:
    return await _sandbox_data(ctx, "profile.json")


async def _plan_summary_data(ctx: RunContext[RequestContext]) -> dict[str, Any]:
    data = await _sandbox_data(ctx, "plan/summary.json")
    if data.get("error") == "sandbox_unavailable":
        return {
            "has_plan": False,
            "guidance": "当前状态缓存不可用，暂时无法读取方案。",
            **data,
        }
    return data


async def _pending_data(ctx: RunContext[RequestContext]) -> dict[str, Any]:
    return await _sandbox_data(ctx, "pending.json")


def _state_message(path: str, data: dict[str, Any]) -> str:
    if path == "score":
        if not data.get("available"):
            return "当前还没有拿到成绩信息。"
        subjects = "、".join(data.get("subject_list") or [])
        return f"当前成绩是{data.get('province')} {data.get('total_score')}分，选科{subjects}。"
    if path == "profile":
        return "已读取当前画像摘要。"
    if path == "plan/summary":
        if not data.get("has_plan"):
            return data.get("guidance") or "当前还没有生成正式方案。"
        total = data.get("ordered_total") or 0
        risk_count = ((data.get("review") or {}).get("risk_count") or 0)
        return f"当前正式方案有{total}个志愿，审查风险{risk_count}项。"
    if path == "pending":
        if not data.get("active"):
            return "当前没有待确认操作。"
        return f"当前待确认操作是{data.get('action_family') or data.get('kind')}。"
    return "已读取当前状态。"


def _first_text(data: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            text = "、".join(str(item).strip() for item in value if str(item or "").strip())
        else:
            text = str(value or "").strip()
        if text:
            return text
    return ""


def _compact_profile_fields(data: dict[str, Any], field_map: list[tuple[str, tuple[str, ...]]]) -> list[dict[str, str]]:
    facts: list[dict[str, str]] = []
    for label, keys in field_map:
        text = _first_text(data, *keys)
        if text:
            facts.append({"label": label, "value": text})
    return facts[:8]


def _compact_profile_raw(data: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "error",
        "schoolId",
        "majorId",
        "categoryId",
        "name",
        "schoolName",
        "majorName",
        "categoryName",
        "majorOverview",
        "trainDemand",
        "trainingTarget",
        "knowledge",
        "course",
        "studyCourses",
        "employmentDirection",
        "jobOrientation",
        "authority",
        "historicAuthorities",
        "goatMajor",
        "doubleFirstMajor",
        "nationalSpecializedMajor",
        "gaotuRank",
        "upgradeRatio",
        "postgraduateRecommendRatio",
        "provinceName",
        "cityName",
    )
    compact: dict[str, Any] = {}
    for key in keys:
        value = data.get(key)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, str):
            compact[key] = value[:300]
        elif isinstance(value, list):
            compact[key] = value[:5]
        else:
            compact[key] = value
    return compact


def _guess_topic_entity(question: str) -> str:
    text = str(question or "").strip()
    for suffix in ("适合我吗", "怎么样", "好不好", "值不值得考虑", "可以吗", "建议吗", "好吗", "专业", "学校"):
        text = text.replace(suffix, "")
    for marker in ("想了解", "了解一下", "看看", "关于", "推荐", "建议"):
        text = text.replace(marker, "")
    return text.strip(" ，。！？?、")


def _resolve_explore_major(question: str, *, batch: str | None) -> tuple[str, str]:
    guessed = _guess_topic_entity(question)
    candidates = [guessed]
    if guessed and not guessed.endswith("类"):
        candidates.append(f"{guessed}类")
    candidates.extend(value for value in _as_list(question) if value not in candidates)
    for candidate in candidates:
        result = resolve_major_entity(candidate, batch)
        if result.best is not None and not result.ambiguous:
            return result.best.canonical_name, result.best.level or ""
    return guessed, ""


def _resolve_explore_school(question: str, *, batch: str | None) -> str:
    guessed = _guess_topic_entity(question)
    result = resolve_school_entity(guessed, batch)
    if result.best is not None and not result.ambiguous:
        return result.best.canonical_name
    return guessed


async def _major_profile_facts(name: str, level: str) -> tuple[dict[str, Any], str]:
    if not name:
        return {}, "missing_entity"
    if level == "level2" or name.endswith("类"):
        response = await internal_client.get_major_category_profile(category_name=name)
    else:
        response = await internal_client.get_major_profile(major_name=name)
    data = _response_data(response)
    return data, "backend_profile" if data else "profile_unavailable"


async def _school_profile_facts(name: str) -> tuple[dict[str, Any], str]:
    if not name:
        return {}, "missing_entity"
    response = await internal_client.get_school_profile_by_name(name)
    data = _response_data(response)
    return data, "backend_profile" if data else "profile_unavailable"


def _comparison_dimensions(entity_type: str, focus: str | None = None) -> list[tuple[str, tuple[str, ...]]]:
    focus_text = str(focus or "").strip()
    if entity_type == "major":
        dimensions = [
            ("课程/知识", ("studyCourses", "course", "knowledge", "coreCourses")),
            ("就业方向", ("employmentDirection", "jobOrientation", "careerDirection")),
            ("培养目标", ("trainDemand", "trainingTarget", "majorOverview", "overview")),
            ("专业特点", ("feature", "majorFeature", "advantage")),
        ]
    else:
        dimensions = [
            ("所在地区", ("provinceName", "cityName", "address")),
            ("优势特色", ("goatMajor", "doubleFirstMajor", "nationalSpecializedMajor", "feature")),
            ("排名/层次", ("gaotuRank", "rank", "ranking", "schoolLevel")),
            ("升学通道", ("upgradeRatio", "postgraduateRecommendRatio")),
            ("隶属关系", ("authority", "historicAuthorities")),
        ]
    if not focus_text:
        return dimensions
    matched = [item for item in dimensions if focus_text in item[0] or any(focus_text in key for key in item[1])]
    if matched:
        return matched + [item for item in dimensions if item not in matched][: max(0, 4 - len(matched))]
    return dimensions


def _plan_contains_entity(items: list[dict[str, Any]], entity_type: str, name: str) -> bool:
    if not name:
        return False
    if entity_type == "school":
        return any(_matches_any_text([str(_item_value(item, "schoolName", "school_name", "collegeName") or "")], [name]) for item in items)
    return any(_matches_any_text(_item_major_names(item), [name]) for item in items)


async def _resolve_compare_entities(
    entity_type: str,
    entities: list[str],
    *,
    batch: str | None,
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    resolved: list[dict[str, str]] = []
    ambiguities: list[dict[str, Any]] = []
    for entity in entities:
        text = str(entity or "").strip()
        if not text:
            continue
        if entity_type == "major":
            result = resolve_major_entity(text, batch)
            if result.ambiguous:
                retry = resolve_major_entity(f"{text}类", batch) if not text.endswith("类") else result
                if retry.best is not None and not retry.ambiguous:
                    resolved.append({"name": retry.best.canonical_name, "level": retry.best.level or ""})
                    continue
                ambiguities.append(_ambiguity_data(result))
                continue
            if result.best is not None:
                resolved.append({"name": result.best.canonical_name, "level": result.best.level or ""})
            else:
                resolved.append({"name": text, "level": ""})
        else:
            result = resolve_school_entity(text, batch)
            if result.ambiguous:
                ambiguities.append(_ambiguity_data(result))
                continue
            resolved.append({"name": result.best.canonical_name if result.best is not None else text, "level": ""})
    unique: list[dict[str, str]] = []
    for item in resolved:
        if item["name"] and item["name"] not in [existing["name"] for existing in unique]:
            unique.append(item)
    return unique, ambiguities


async def _compare_profile_for_entity(entity_type: str, entity: dict[str, str]) -> tuple[dict[str, Any], str]:
    try:
        if entity_type == "major":
            return await _major_profile_facts(entity.get("name", ""), entity.get("level", ""))
        return await _school_profile_facts(entity.get("name", ""))
    except Exception as exc:
        return {"error": str(exc)}, "profile_error"


async def read_state(
    ctx: RunContext[RequestContext],
    path: StatePath,
) -> str:
    """Read one current-state section: score, profile, plan/summary, or pending."""
    normalized_path = str(path or "").strip().lower()
    if normalized_path in {"plan", "plan_summary", "summary"}:
        normalized_path = "plan/summary"
    if normalized_path not in {"score", "profile", "plan/summary", "pending"}:
        return _json(
            {
                "data": {
                    "path": path,
                    "allowed_paths": ["score", "profile", "plan/summary", "pending"],
                },
                "next_step": "clarify",
                "message": "需要说明要读取成绩、画像、方案摘要还是待确认信息。",
            }
        )

    data_by_path = {
        "score": _score_data,
        "profile": _profile_data,
        "plan/summary": _plan_summary_data,
        "pending": _pending_data,
    }
    data = await data_by_path[normalized_path](ctx)
    return _json(
        {
            "data": data,
            "next_step": "respond",
            "message": _state_message(normalized_path, data),
        }
    )


async def explore_topic(
    ctx: RunContext[RequestContext],
    topic_type: TopicType,
    user_question: str,
) -> str:
    """Explore a career, major, school, or region question without changing state."""
    normalized_type = str(topic_type or "").strip().lower()
    if normalized_type not in {"career", "major", "school", "region"}:
        normalized_type = "major"

    score = await _score_data(ctx)
    plan = await _plan_summary_data(ctx)
    student_bits: list[str] = []
    if score.get("available"):
        subjects = "、".join(score.get("subject_list") or [])
        student_bits.append(f"{score.get('province')}{score.get('total_score')}分")
        if subjects:
            student_bits.append(subjects)
    if plan.get("has_plan"):
        student_bits.append(f"已有{plan.get('ordered_total')}个志愿方案")

    labels = {
        "career": "发展方向",
        "major": "专业方向",
        "school": "院校选择",
        "region": "地域选择",
    }
    label = labels[normalized_type]
    question = str(user_question or "").strip()
    profile_data: dict[str, Any] = {}
    profile_source = "not_requested"
    entity_name = ""
    entity_level = ""
    profile_facts: list[dict[str, str]] = []
    try:
        if normalized_type == "major":
            entity_name, entity_level = _resolve_explore_major(question, batch=getattr(ctx.deps, "batch", None) or "01")
            profile_data, profile_source = await _major_profile_facts(entity_name, entity_level)
            profile_facts = _compact_profile_fields(
                profile_data,
                [
                    ("培养目标", ("trainDemand", "trainingTarget", "majorOverview", "overview")),
                    ("知识/课程", ("knowledge", "course", "studyCourses", "coreCourses")),
                    ("就业方向", ("jobOrientation", "employmentDirection", "careerDirection")),
                    ("专业特点", ("feature", "majorFeature", "advantage")),
                ],
            )
        elif normalized_type == "school":
            entity_name = _resolve_explore_school(question, batch=getattr(ctx.deps, "batch", None) or "01")
            profile_data, profile_source = await _school_profile_facts(entity_name)
            profile_facts = _compact_profile_fields(
                profile_data,
                [
                    ("隶属/层次", ("authority", "historicAuthorities", "schoolType", "schoolLevel")),
                    ("优势/特色", ("goatMajor", "doubleFirstMajor", "nationalSpecializedMajor", "feature")),
                    ("排名", ("gaotuRank", "rank", "ranking")),
                    ("升学", ("upgradeRatio", "postgraduateRecommendRatio")),
                    ("位置", ("provinceName", "cityName", "address")),
                ],
            )
    except Exception as exc:
        profile_source = "profile_error"
        profile_data = {"error": str(exc)}

    fallback_dimensions = [] if profile_facts else list(_EXPLORE_FALLBACK_DIMENSIONS.get(normalized_type, []))
    analysis = (
        [
            "先判断这个方向和成绩、选科、性格诉求是否匹配。",
            "再看它对当前方案结构和冲稳保分布的影响。",
            "如果要沉淀为明确报考要求，需要另行预览并确认。",
        ]
        if profile_facts
        else fallback_dimensions
    )
    message = f"关于{label}：{entity_name or question}，可以按这些维度分析。"
    if profile_facts:
        message += f" 已读取{entity_name}的资料要点。"
    elif fallback_dimensions:
        message += " 后续回答可结合通用维度和当前学生信息展开。"
    return _json(
        {
            "data": {
                "topic_type": normalized_type,
                "user_question": question,
                "entity": entity_name,
                "entity_level": entity_level,
                "student_summary": "；".join(student_bits),
                "profile_source": profile_source,
                "profile_facts": profile_facts,
                "profile_raw": _compact_profile_raw(profile_data),
                "analysis": analysis,
                "fallback_dimensions": fallback_dimensions,
                "state_mutation": False,
            },
            "next_step": "respond",
            "message": message,
        }
    )


async def compare_entities(
    ctx: RunContext[RequestContext],
    entity_type: CompareEntityType,
    entities: list[str],
    comparison_focus: str | None = None,
) -> str:
    """Compare 2-5 majors or schools with structured facts and no state mutation."""
    normalized_type = str(entity_type or "").strip().lower()
    if normalized_type not in {"major", "school"}:
        return _json(
            {
                "data": {"entity_type": entity_type, "allowed_entity_types": ["major", "school"]},
                "next_step": "clarify",
                "message": "需要说明是对比专业还是院校。",
            }
        )
    raw_entities = _as_list(entities)
    if len(raw_entities) < 2 or len(raw_entities) > 5:
        return _json(
            {
                "data": {"entity_type": normalized_type, "entities": raw_entities},
                "next_step": "clarify",
                "message": "对比需要提供2到5个明确的专业或院校名称。",
            }
        )
    resolved, ambiguities = await _resolve_compare_entities(
        normalized_type,
        raw_entities,
        batch=getattr(ctx.deps, "batch", None) or "01",
    )
    if ambiguities:
        first = ambiguities[0]
        options = "、".join(str(item.get("name") or "") for item in first.get("candidates", []) if item.get("name"))
        return _json(
            {
                "data": {
                    "entity_type": normalized_type,
                    "entities": raw_entities,
                    "resolved_entities": resolved,
                    "ambiguities": ambiguities,
                },
                "next_step": "clarify",
                "message": f"“{first.get('raw_text')}”有多个可能含义：{options}。需要先确认你指哪一个。",
            }
        )
    if len(resolved) < 2:
        return _json(
            {
                "data": {"entity_type": normalized_type, "entities": raw_entities, "resolved_entities": resolved},
                "next_step": "clarify",
                "message": "还没有定位到至少两个可对比对象，请补充完整名称。",
            }
        )

    profile_results = await asyncio.gather(
        *(_compare_profile_for_entity(normalized_type, entity) for entity in resolved)
    )
    dimensions = _comparison_dimensions(normalized_type, comparison_focus)
    rows: list[dict[str, Any]] = []
    plan_items = _items_from_plan_file(await _sandbox_data(ctx, "plan/items.json"))
    for entity, (profile, source) in zip(resolved, profile_results):
        name = entity["name"]
        row = {
            "name": name,
            "level": entity.get("level") or "",
            "profile_source": source,
            "in_current_plan": _plan_contains_entity(plan_items, normalized_type, name),
            "facts": _compact_profile_fields(profile, dimensions),
            "raw": _compact_profile_raw(profile),
        }
        rows.append(row)

    dimension_names = [label for label, _ in dimensions]
    focus_text = str(comparison_focus or "").strip()
    label = "专业" if normalized_type == "major" else "院校"
    names = "、".join(row["name"] for row in rows)
    unavailable = [row["name"] for row in rows if row["profile_source"] != "backend_profile"]
    dimensions_template = (
        [
            {"dimension": dimension, "fill_from": "llm_knowledge"}
            for dimension in _COMPARE_FALLBACK_DIMENSIONS.get(normalized_type, [])
        ]
        if any(not row.get("facts") for row in rows)
        else []
    )
    message = f"关于{names}，已整理{label}对比维度"
    if focus_text:
        message += f"（重点：{focus_text}）"
    message += "。"
    if unavailable:
        message += f" 其中{ '、'.join(unavailable) }资料未完整返回，回答时按通用对比维度补充。"
    return _json(
        {
            "data": {
                "entity_type": normalized_type,
                "entities": raw_entities,
                "resolved_entities": resolved,
                "comparison_focus": focus_text,
                "dimensions": dimension_names,
                "dimensions_template": dimensions_template,
                "rows": rows,
                "state_mutation": False,
            },
            "next_step": "respond",
            "message": message,
        }
    )


def _policy_domain_label(domain: str) -> str:
    return {
        "score_batch": "分数位次和批次线",
        "eligibility": "资格条件",
        "tuition_budget": "学费预算",
        "enrollment_rules": "录取规则",
        "school_rule": "院校招生规则",
        "transfer_major": "转专业",
        "subject_requirement": "选科要求",
        "physical_exam": "体检限制",
        "oral_exam": "英语口试",
        "general": "报考规则",
    }.get(domain, "报考规则")


def _score_context(data: dict[str, Any]) -> dict[str, Any]:
    if not data.get("available"):
        return {
            "available": False,
            "missing": ["高考省份", "总分", "选科"],
        }
    missing: list[str] = []
    if not data.get("province"):
        missing.append("高考省份")
    if not data.get("total_score"):
        missing.append("总分")
    if not data.get("subject_list"):
        missing.append("选科")
    return {
        "available": True,
        "province": data.get("province") or "",
        "total_score": data.get("total_score") or 0,
        "subject_list": data.get("subject_list") or [],
        "sex": data.get("sex") or "",
        "batch": data.get("batch") or "01",
        "missing": missing,
    }


def _policy_required_sources(domain: str, *, province: str, school_name: str, year: int | None) -> list[str]:
    year_text = f"{year}年" if year else "当年"
    province_text = province or "所在省"
    school_text = school_name or "目标院校"
    if domain == "score_batch":
        return [
            f"{province_text}省级考试院{year_text}一分一段、批次线、投档规则",
            "阳光高考或教育部公开政策说明",
        ]
    if domain in {"eligibility", "physical_exam", "oral_exam"}:
        return [
            f"{province_text}省级考试院{year_text}资格审核/体检/口试要求",
            f"{school_text}{year_text}招生章程和专业备注",
        ]
    if domain in {"school_rule", "transfer_major", "subject_requirement", "enrollment_rules"}:
        return [
            f"{school_text}{year_text}招生章程、招生简章或招生办通知",
            f"{province_text}省级考试院{year_text}录取规则",
        ]
    if domain == "tuition_budget":
        return [
            f"{school_text}{year_text}招生章程、收费说明或专业备注",
            "当前方案/候选里的学费、培养模式和录取概率",
        ]
    return ["教育部、阳光高考、省级考试院或院校招生网等官方公开来源"]


def _policy_framework(domain: str, *, school_name: str, major_name: str) -> str:
    target = " · ".join(item for item in (school_name, major_name) if item) or "目标学校/专业"
    if domain == "score_batch":
        return (
            "分数、位次和批次线不能混着用：分数受试卷难度影响，位次更接近竞争位置，批次线只说明批次边界。"
            "出分前可以用模考位次和往年一分一段做预案，出分后要按官方一分一段、招生计划和近年录取位次重算。"
        )
    if domain == "tuition_budget":
        return (
            "学费问题要按四年总成本看，不只看单年学费。民办、中外合作、校企合作、单列专业要同时核对收费、培养地点、转专业空间和家庭现金流。"
            "如果它是冲刺项，可以少量保留；保底区应保留费用可承受且专业也能接受的选择。"
        )
    if domain in {"eligibility", "physical_exam", "oral_exam", "subject_requirement"}:
        return (
            f"{target}能不能报，必须逐条核对资格、选科、体检、口试和专业备注。"
            "专项资格、体检受限、英语口试或选科限制有任一硬性不满足，都不能只按录取概率判断。"
        )
    if domain in {"school_rule", "transfer_major", "enrollment_rules"}:
        return (
            f"{target}相关规则以当年招生章程、招生简章、招生办通知和省级投档规则为准。"
            "转专业通常还要看大一成绩排名、课程成绩、接收名额、考核办法、是否允许跨学院或转入热门专业。"
        )
    return (
        "这类问题先区分通用规则、省级政策、学校章程和个人适配。"
        "涉及具体省份、学校、专业或当前学生能不能填时，需要核验官方来源和学生信息。"
    )


def _compact_policy_profile(data: dict[str, Any]) -> dict[str, Any]:
    if not data:
        return {}
    keys = (
        "schoolName",
        "name",
        "recruitmentPolicy",
        "recruitmentPolicySourceTitle",
        "recruitmentPolicySourceContent",
        "provinceName",
        "cityName",
    )
    result: dict[str, Any] = {}
    for key in keys:
        value = data.get(key)
        if value in (None, "", [], {}):
            continue
        result[key] = value[:600] if isinstance(value, str) else value
    return result


def _school_policy_facts(profile: dict[str, Any]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for label, keys in (
        ("招生政策", ("recruitmentPolicy", "admissionPolicy")),
        ("来源标题", ("recruitmentPolicySourceTitle", "policySourceTitle")),
        ("来源内容", ("recruitmentPolicySourceContent", "policySourceContent")),
    ):
        text = _first_text(profile, *keys)
        if text:
            facts.append({"label": label, "value": text[:600]})
    return facts[:6]


def _source_scope_for_policy(domain: str, *, school_name: str) -> str:
    if domain in {"school_rule", "transfer_major", "subject_requirement", "enrollment_rules"} or school_name:
        return "school_brochure"
    if domain in {"score_batch", "eligibility", "physical_exam", "oral_exam"}:
        return "province_policy"
    return "general_official"


_POLICY_PROVINCE_DOMAINS: dict[str, tuple[str, ...]] = {
    "山东": ("sdzk.cn",),
}

_POLICY_SCHOOL_DOMAINS: dict[str, tuple[str, ...]] = {
    "北京工业大学": ("admissions.bjut.edu.cn",),
}


def _policy_query_candidates(
    query: str,
    *,
    source_scope: str,
    province: str,
    school_name: str,
    year: int,
) -> list[str]:
    base_parts = [str(query or "").strip()]
    if year:
        base_parts.append(str(year))
    if source_scope == "province_policy":
        if province:
            base_parts.append(province)
        base_parts.extend(["考试院", "官方"])
    elif source_scope == "school_brochure":
        if school_name:
            base_parts.extend([school_name, f"{school_name}本科招生网"])
        base_parts.extend(["招生章程", "招生简章", "招生网"])
    else:
        base_parts.extend(["教育部", "阳光高考", "官方"])

    base = " ".join(part for part in dict.fromkeys(base_parts) if part)
    candidates = [base]
    if source_scope == "province_policy":
        for domain in _POLICY_PROVINCE_DOMAINS.get(province, ()):
            candidates.append(f"site:{domain} {base}")
    elif source_scope == "school_brochure":
        for domain in _POLICY_SCHOOL_DOMAINS.get(school_name, ()):
            candidates.append(f"site:{domain} {base}")
    else:
        candidates.extend([f"site:gaokao.chsi.com.cn {base}", f"site:moe.gov.cn {base}"])
    return [item for item in dict.fromkeys(candidates) if item]


def _policy_search_results(data: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(data.get("data"), dict):
        data = data["data"]
    web_pages = data.get("webPages") if isinstance(data.get("webPages"), dict) else {}
    raw_items = web_pages.get("value") if isinstance(web_pages, dict) else None
    if raw_items is None:
        raw_items = data.get("value") or data.get("results") or []
    if not isinstance(raw_items, list):
        return []

    results: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        item = {
            "title": str(raw.get("name") or raw.get("title") or "").strip(),
            "url": str(raw.get("url") or "").strip(),
            "site_name": str(raw.get("siteName") or raw.get("site_name") or "").strip(),
            "snippet": str(raw.get("snippet") or "").strip(),
            "summary": str(raw.get("summary") or "").strip(),
        }
        if item["title"] or item["url"]:
            results.append(item)
    return results


def _policy_domain_from_url(url: str) -> str:
    with contextlib.suppress(Exception):
        return urlparse(url).netloc.lower()
    return ""


def _policy_result_looks_official(
    item: dict[str, Any],
    *,
    source_scope: str,
    province: str,
    school_name: str,
) -> bool:
    title = str(item.get("title") or "")
    url = str(item.get("url") or "")
    site_name = str(item.get("site_name") or "")
    snippet = str(item.get("snippet") or "")
    summary = str(item.get("summary") or "")
    text = f"{title} {site_name} {snippet} {summary}"
    domain = _policy_domain_from_url(url)
    if source_scope == "general_official":
        return (
            domain.endswith(".gov.cn")
            or "moe.gov.cn" in domain
            or "chsi.com.cn" in domain
            or "教育部" in site_name
            or "阳光高考" in site_name
            or "教育考试院" in site_name
            or "招生考试院" in site_name
        )
    if source_scope == "province_policy":
        province_hit = not province or province in text
        province_domain_hit = any(
            domain == expected or domain.endswith(f".{expected}")
            for expected in _POLICY_PROVINCE_DOMAINS.get(province, ())
        )
        return province_hit and (
            domain.endswith(".gov.cn")
            or "chsi.com.cn" in domain
            or province_domain_hit
            or "教育考试院" in site_name
            or "招生考试院" in site_name
        )
    if source_scope == "school_brochure":
        if "研究生" in f"{title} {site_name}":
            return False
        school_site = (not school_name or school_name in site_name) and (
            "招生网" in site_name or "招生办公室" in site_name or "本科招生" in site_name
        )
        brochure_hit = (
            "招生章程" in text
            or "招生简章" in text
            or "本科招生" in f"{title} {site_name}"
            or "admissions" in domain
        )
        return (domain.endswith(".edu.cn") or school_site) and brochure_hit
    return False


async def _request_policy_source_search(
    *,
    query: str,
    source_scope: str,
    province: str,
    school_name: str,
    year: int,
    count: int = 3,
    summary: bool = True,
) -> dict[str, Any]:
    config = BochaSearchConfig()
    if not config.api_key:
        return {
            "status": "missing_api_key",
            "summary": "当前未配置 BOCHA_API_KEY，不能执行官方来源联网检索。",
            "source_scope": source_scope,
            "query": query,
            "results": [],
        }
    query_candidates = _policy_query_candidates(
        query,
        source_scope=source_scope,
        province=province,
        school_name=school_name,
        year=year,
    )
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }
    normalized_count = max(1, min(int(count or 3), 10))
    timeout = aiohttp.ClientTimeout(total=float(config.timeout_seconds or 10.0))
    async with aiohttp.ClientSession(timeout=timeout) as session:
        attempted_queries: list[str] = []
        raw_results: list[dict[str, Any]] = []
        official_results: list[dict[str, Any]] = []
        for candidate_query in query_candidates:
            attempted_queries.append(candidate_query)
            async with session.post(
                config.base_url,
                headers=headers,
                json={
                    "query": candidate_query,
                    "freshness": "oneYear",
                    "summary": bool(summary),
                    "count": normalized_count,
                },
            ) as response:
                data = await response.json(content_type=None)
                if response.status >= 400:
                    return {
                        "status": "http_error",
                        "http_status": response.status,
                        "query": candidate_query,
                        "attempted_queries": attempted_queries,
                        "results": [],
                    }
                items = _policy_search_results(data if isinstance(data, dict) else {})
                raw_results.extend(items)
                official_results.extend(
                    item
                    for item in items
                    if _policy_result_looks_official(
                        item,
                        source_scope=source_scope,
                        province=province,
                        school_name=school_name,
                    )
                )
                if official_results:
                    break
    results = official_results or raw_results[:normalized_count]
    return {
        "status": "ok" if results else "empty",
        "summary": f"已检索到 {len(results)} 条可能相关的官方来源。" if results else "没有检索到可直接引用的官方来源。",
        "source_scope": source_scope,
        "query": query_candidates[0] if query_candidates else query,
        "attempted_queries": attempted_queries,
        "results": results[:normalized_count],
    }


async def _offline_source_search(
    ctx: RunContext[RequestContext],
    *,
    question: str,
    domain: str,
    province: str,
    school_name: str,
    year: int | None,
) -> dict[str, Any]:
    try:
        return await _request_policy_source_search(
            query=question,
            source_scope=_source_scope_for_policy(domain, school_name=school_name),
            province=province,
            school_name=school_name,
            year=year or 0,
            count=3,
            summary=True,
        )
    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
            "results": [],
        }


async def _policy_param_availability(
    ctx: RunContext[RequestContext],
    *,
    school_name: str,
    major_name: str,
    province: str,
) -> dict[str, Any]:
    majors = {"level1": [], "level2": [], "level3": []}
    schools: list[str] = []
    locations = {"province": [], "city": []}
    if major_name:
        major_result = resolve_major_entity(major_name, getattr(ctx.deps, "batch", None) or "01")
        if major_result.best is not None and major_result.best.level in majors:
            majors[major_result.best.level].append(major_result.best.canonical_name)
        else:
            majors["level3"].append(major_name)
    if school_name:
        school_result = resolve_school_entity(school_name, getattr(ctx.deps, "batch", None) or "01")
        schools.append(school_result.best.canonical_name if school_result.best is not None else school_name)
    if province and (school_name or major_name):
        locations["province"].append(province)
    if not (any(majors.values()) or schools or any(locations.values())):
        return {"checked": False, "reason": "no_structured_target"}
    batch = getattr(ctx.deps, "batch", None) or "01"
    encoded_majors = {"level1": [], "level2": [], "level3": []}
    for level, names in majors.items():
        encoded_majors[level] = await get_major_codes_async(names, level, batch) if names else []
    encoded_schools = await get_school_codes_async(schools) if schools else []
    encoded_locations = {
        "province": await get_province_codes_async(locations["province"]) if locations["province"] else [],
        "city": [],
    }
    try:
        response = await internal_client.check_plan_param_availability(
            getattr(ctx.deps, "tenant_id", 1),
            ctx.deps.sessionid,
            majors=encoded_majors,
            schools=encoded_schools,
            locations=encoded_locations,
        )
    except Exception as exc:
        return {
            "checked": True,
            "available": None,
            "status": "error",
            "error": str(exc),
            "majors": majors,
            "schools": schools,
            "locations": locations,
            "encoded_majors": encoded_majors,
            "encoded_schools": encoded_schools,
            "encoded_locations": encoded_locations,
        }
    response_data = response.get("data") if isinstance(response, dict) else None
    available = response_data if isinstance(response_data, bool) else bool(response_data)
    return {
        "checked": True,
        "available": available,
        "status": "ok" if _is_success_response(response) or isinstance(response, dict) else "unknown",
        "raw": _response_data(response),
        "majors": majors,
        "schools": schools,
        "locations": locations,
        "encoded_majors": encoded_majors,
        "encoded_schools": encoded_schools,
        "encoded_locations": encoded_locations,
    }


async def answer_policy(
    ctx: RunContext[RequestContext],
    question: str,
    rule_domain: PolicyDomain | None = None,
    school_name: str | None = None,
    major_name: str | None = None,
    year: int | None = None,
    use_official_search: bool = False,
) -> str:
    """Answer read-only admission policy, rule, eligibility, and budget questions."""
    domain = str(rule_domain or "general").strip().lower() or "general"
    if domain not in {
        "score_batch",
        "eligibility",
        "tuition_budget",
        "enrollment_rules",
        "school_rule",
        "transfer_major",
        "subject_requirement",
        "physical_exam",
        "oral_exam",
        "general",
    }:
        domain = "general"
    question_text = str(question or "").strip()
    resolved_school = str(school_name or "").strip()
    resolved_major = str(major_name or "").strip()
    if resolved_school:
        school_result = resolve_school_entity(resolved_school, getattr(ctx.deps, "batch", None) or "01")
        if school_result.ambiguous:
            options = "、".join(
                str(item.get("name") or "") for item in _ambiguity_data(school_result).get("candidates", []) if item.get("name")
            )
            return _json(
                {
                    "data": {
                        "question": question_text,
                        "rule_domain": domain,
                        "ambiguity": _ambiguity_data(school_result),
                    },
                    "next_step": "clarify",
                    "message": f"“{resolved_school}”有多个可能院校：{options}。需要先确认你指哪一所。",
                }
            )
        if school_result.best is not None:
            resolved_school = school_result.best.canonical_name

    score = _score_context(await _score_data(ctx))
    province = str(score.get("province") or "").strip()
    school_profile: dict[str, Any] = {}
    school_profile_source = "not_requested"
    if resolved_school:
        try:
            school_profile, school_profile_source = await _school_profile_facts(resolved_school)
        except Exception as exc:
            school_profile = {"error": str(exc)}
            school_profile_source = "profile_error"

    source_search: dict[str, Any] | None = None
    if use_official_search:
        source_search = await _offline_source_search(
            ctx,
            question=question_text,
            domain=domain,
            province=province,
            school_name=resolved_school,
            year=year,
        )

    eligibility = await _policy_param_availability(
        ctx,
        school_name=resolved_school,
        major_name=resolved_major,
        province=province,
    )
    required_sources = _policy_required_sources(domain, province=province, school_name=resolved_school, year=year)
    policy_facts = [
        {
            "label": _policy_domain_label(domain),
            "value": _policy_framework(domain, school_name=resolved_school, major_name=resolved_major),
        }
    ]
    policy_facts.extend(_school_policy_facts(school_profile))
    if source_search and isinstance(source_search.get("results"), list):
        for item in source_search.get("results", [])[:3]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or item.get("name") or "").strip()
            snippet = str(item.get("snippet") or item.get("summary") or "").strip()
            if title or snippet:
                policy_facts.append({"label": title or "官方来源", "value": snippet[:400]})

    missing_fields = list(score.get("missing") or [])
    if domain in {"school_rule", "transfer_major", "subject_requirement", "enrollment_rules"} and not resolved_school:
        missing_fields.append("目标院校")
    if domain in {"subject_requirement", "physical_exam", "oral_exam"} and not resolved_major:
        missing_fields.append("目标专业或专业组")
    if domain == "tuition_budget" and not (resolved_school or resolved_major):
        missing_fields.append("目标院校或当前方案范围")
    missing_fields = list(dict.fromkeys(item for item in missing_fields if item))

    source_references: list[dict[str, Any]] = [
        {"type": "required_source", "title": item, "url": ""} for item in required_sources
    ]
    if source_search and isinstance(source_search.get("results"), list):
        for item in source_search.get("results", [])[:5]:
            if isinstance(item, dict):
                source_references.append(
                    {
                        "type": "official_search",
                        "title": str(item.get("title") or "").strip(),
                        "url": str(item.get("url") or "").strip(),
                        "site_name": str(item.get("siteName") or item.get("site_name") or "").strip(),
                    }
                )
    if school_profile.get("recruitmentPolicySourceTitle") or school_profile.get("recruitmentPolicySourceContent"):
        source_references.append(
            {
                "type": "school_profile",
                "title": school_profile.get("recruitmentPolicySourceTitle") or f"{resolved_school}招生政策资料",
                "url": "",
            }
        )

    message = f"这是{_policy_domain_label(domain)}的只读规则问题，不会改报考要求或方案。"
    if resolved_school:
        message += f" 已按{resolved_school}整理规则依据。"
    if missing_fields:
        message += f" 还需要补齐：{'、'.join(missing_fields[:5])}。"
    else:
        message += " 可以先按当前学生信息和规则框架判断。"

    return _json(
        {
            "data": {
                "question": question_text,
                "rule_domain": domain,
                "domain_label": _policy_domain_label(domain),
                "school_name": resolved_school,
                "major_name": resolved_major,
                "year": year,
                "policy_facts": policy_facts[:8],
                "student_eligibility": {
                    "score_context": score,
                    "param_availability": eligibility,
                    "missing_fields": missing_fields,
                },
                "source_references": source_references[:8],
                "source_lookup": source_search
                if source_search
                else {"status": "not_requested", "reason": "offline_first"},
                "school_profile_source": school_profile_source,
                "school_profile_raw": _compact_policy_profile(school_profile),
                "state_mutation": False,
            },
            "next_step": "respond",
            "message": message,
        }
    )


def _review_check_level(check: dict[str, Any]) -> str:
    level = str(
        check.get("level")
        or check.get("severity")
        or check.get("riskLevel")
        or check.get("risk_level")
        or ""
    ).strip().lower()
    if check.get("passed") is True:
        return "passed"
    if level in {"risk", "high", "error", "danger", "严重"}:
        return "risk"
    if level in {"warn", "warning", "medium", "提醒"}:
        return "warn"
    if level in {"info", "notice", "low", "提示"}:
        return "info"
    if check.get("passed") is False:
        return "risk"
    return level or "info"


def _review_issue_code(check: dict[str, Any]) -> str:
    return str(
        check.get("code")
        or check.get("reasonCode")
        or check.get("reason_code")
        or check.get("ruleCode")
        or check.get("rule_code")
        or check.get("checkCode")
        or check.get("check_code")
        or ""
    ).strip()


def _canonical_review_issue_code(value: Any) -> str:
    code = normalize_review_issue_code(value) or ""
    if code == "ratio_distribution":
        return "tier_gap"
    return code


def _review_issue_matches(check: dict[str, Any], requested_code: str) -> bool:
    requested = _canonical_review_issue_code(requested_code)
    if not requested:
        return False
    raw_code = _review_issue_code(check)
    if _canonical_review_issue_code(raw_code) == requested:
        return True
    searchable = " ".join(
        str(check.get(key) or "")
        for key in (
            "summary",
            "title",
            "message",
            "detail",
            "description",
            "suggestedAction",
            "suggested_action",
            "scopeKind",
            "scope_kind",
        )
    )
    return _canonical_review_issue_code(searchable) == requested


def _review_issue_summary(check: dict[str, Any]) -> str:
    return str(
        check.get("summary")
        or check.get("title")
        or check.get("message")
        or check.get("detail")
        or check.get("description")
        or ""
    ).strip()


def _review_affected_count(check: dict[str, Any]) -> int:
    for key in (
        "affectedCount",
        "affected_count",
        "affectedUnitCount",
        "affected_unit_count",
        "affectedVolunteerCount",
        "affected_volunteer_count",
    ):
        count = _as_int(check.get(key), -1)
        if count >= 0:
            return count
    for key in ("affectedUnitIds", "affected_unit_ids", "affectedVolunteerIds", "affected_volunteer_ids"):
        value = check.get(key)
        if isinstance(value, list):
            return len(value)
    examples = check.get("examples") or check.get("affectedItems")
    if isinstance(examples, list):
        return len(examples)
    return 0


def _review_issue_examples(check: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items: Any = (
        check.get("examples")
        or check.get("affectedItems")
        or check.get("affected_items")
        or check.get("hitPlanExamples")
        or check.get("hit_plan_examples")
        or []
    )
    if not isinstance(raw_items, list):
        return []
    examples: list[dict[str, Any]] = []
    for item in raw_items[:5]:
        if isinstance(item, dict):
            examples.append(
                {
                    "school": str(item.get("schoolName") or item.get("school") or "").strip(),
                    "major": str(item.get("majorName") or item.get("major") or "").strip(),
                    "position": _as_int(item.get("position") or item.get("order")),
                    "tier": str(item.get("tier") or item.get("riskTier") or "").strip(),
                    "summary": str(item.get("summary") or item.get("description") or "").strip(),
                }
            )
        else:
            text = str(item or "").strip()
            if text:
                examples.append({"summary": text})
    return [item for item in examples if any(value not in ("", 0, None) for value in item.values())]


def _review_issue_unit_ids(check: dict[str, Any]) -> list[str]:
    unit_ids: list[str] = []
    for key in ("affectedUnitIds", "affected_unit_ids", "unitIds", "unit_ids"):
        for value in _as_list(check.get(key)):
            _append_unique(unit_ids, value)
    for key in ("affectedItems", "affected_items", "examples", "hitPlanExamples", "hit_plan_examples"):
        raw_items = check.get(key)
        if not isinstance(raw_items, list):
            continue
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            unit_id = str(item.get("unitId") or item.get("unit_id") or "").strip()
            if unit_id:
                _append_unique(unit_ids, unit_id)
    return unit_ids


def _review_issue_volunteer_ids(check: dict[str, Any]) -> list[str]:
    volunteer_ids: list[str] = []
    for key in ("affectedVolunteerIds", "affected_volunteer_ids", "volunteerIds", "volunteer_ids"):
        for value in _as_list(check.get(key)):
            _append_unique(volunteer_ids, value)
    for key in ("affectedItems", "affected_items", "examples", "hitPlanExamples", "hit_plan_examples"):
        raw_items = check.get(key)
        if not isinstance(raw_items, list):
            continue
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            volunteer_id = str(item.get("volunteerId") or item.get("volunteer_id") or "").strip()
            if volunteer_id:
                _append_unique(volunteer_ids, volunteer_id)
    return volunteer_ids


def _normalize_review_issue(check: dict[str, Any]) -> dict[str, Any]:
    source_code = _review_issue_code(check)
    code = _canonical_review_issue_code(source_code) or source_code
    level = _review_check_level(check)
    issue = {
        "code": code,
        "severity": level,
        "passed": bool(check.get("passed")) if "passed" in check else level == "passed",
        "affected_count": _review_affected_count(check),
        "summary": _review_issue_summary(check),
        "suggested_action": str(check.get("suggestedAction") or check.get("suggested_action") or "").strip(),
        "scope_kind": str(check.get("scopeKind") or check.get("scope_kind") or "").strip(),
        "unit_ids": _review_issue_unit_ids(check),
        "volunteer_ids": _review_issue_volunteer_ids(check),
        "examples": _review_issue_examples(check),
    }
    if source_code and source_code != code:
        issue["source_code"] = source_code
    return issue


def _review_focus_matches(issue: dict[str, Any], focus: str) -> bool:
    if focus == "full_review":
        return True
    if focus == "risk_only":
        return issue.get("severity") == "risk"
    text = " ".join(
        str(issue.get(key) or "")
        for key in ("code", "summary", "suggested_action", "scope_kind")
    ).lower()
    if focus == "tuition":
        return any(token in text for token in ("tuition", "学费", "高收费", "费用", "中外合作", "cooperative"))
    if focus == "tier_balance":
        return any(token in text for token in ("tier", "ratio", "probability", "count", "梯度", "冲", "稳", "保", "数量"))
    if focus == "career_fit":
        return any(token in text for token in ("career", "intent", "专业", "职业", "偏好", "适配"))
    return True


def _review_focus_label(focus: str) -> str:
    return {
        "risk_only": "风险项",
        "tier_balance": "冲稳保梯度",
        "tuition": "学费、高收费/中外合作",
        "career_fit": "发展方向适配",
    }.get(str(focus or "").strip(), "当前重点")


def _review_career_labels(career_slots: list[str] | None) -> tuple[list[str], list[str]]:
    normalized = normalize_career_slots([str(value or "").strip() for value in career_slots or []])
    return normalized, [to_career_label(value) for value in normalized]


def _review_fix_proposal_message(fix_proposals: dict[str, Any], *, limit: int = 4) -> str:
    proposals = fix_proposals.get("proposals") if isinstance(fix_proposals, dict) else None
    if not isinstance(proposals, list):
        return ""
    lines: list[str] = []
    for proposal in proposals[:limit]:
        if not isinstance(proposal, dict):
            continue
        title = str(proposal.get("title") or "处理方向").strip()
        summary = str(proposal.get("summary") or "").strip()
        status = str(proposal.get("status") or "").strip()
        status_label = f"，{status}" if status else ""
        if summary:
            lines.append(f"{title}（{summary}{status_label}）")
        elif title:
            lines.append(f"{title}{status_label}")
    return "；".join(lines)


def _review_summary_counts(review_file: dict[str, Any], issues: list[dict[str, Any]]) -> dict[str, int]:
    summary = review_file.get("summary") if isinstance(review_file.get("summary"), dict) else {}
    risk_count = _as_int(review_file.get("risk_count") or summary.get("riskCount") or summary.get("risk_count"))
    warn_count = _as_int(review_file.get("warn_count") or summary.get("warnCount") or summary.get("warn_count"))
    passed_count = _as_int(summary.get("passedCount") or summary.get("passed_count"))
    if not risk_count:
        risk_count = sum(1 for issue in issues if issue.get("severity") == "risk" and not issue.get("passed"))
    if not warn_count:
        warn_count = sum(1 for issue in issues if issue.get("severity") == "warn" and not issue.get("passed"))
    if not passed_count:
        passed_count = sum(1 for issue in issues if issue.get("passed"))
    return {
        "risk_count": risk_count,
        "warn_count": warn_count,
        "passed_count": passed_count,
        "total_count": len(issues),
    }


def _tier_balance_from_plan_summary(plan_summary: dict[str, Any]) -> dict[str, Any]:
    tier_counts = plan_summary.get("tier_counts") if isinstance(plan_summary.get("tier_counts"), dict) else {}
    sprint = _as_int(tier_counts.get("冲") or tier_counts.get("sprint"))
    safe = _as_int(tier_counts.get("稳") or tier_counts.get("safe"))
    protect = _as_int(tier_counts.get("保") or tier_counts.get("protect"))
    if not (sprint or safe or protect):
        return {"available": False, "assessment": "暂时没有拿到冲稳保分布。"}
    assessment = "梯度分布可继续结合录取概率细看。"
    if protect <= 0:
        assessment = "保底区缺失，需要优先关注滑档风险。"
    elif safe <= 0:
        assessment = "稳区缺失，方案可能偏冲或偏保。"
    elif sprint > safe + protect:
        assessment = "冲区占比偏高，需要关注整体波动。"
    return {
        "available": True,
        "冲": sprint,
        "稳": safe,
        "保": protect,
        "assessment": assessment,
    }


def _normalize_fix_proposals_payload(payload: dict[str, Any]) -> dict[str, Any]:
    data = _response_data(payload)
    proposals = data.get("proposals") if isinstance(data.get("proposals"), list) else []
    normalized: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}
    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        status = str(proposal.get("status") or "").strip()
        if status:
            status_counts[status] = status_counts.get(status, 0) + 1
        actions = proposal.get("actions") if isinstance(proposal.get("actions"), list) else []
        normalized.append(
            {
                "proposal_id": str(proposal.get("proposalId") or proposal.get("proposal_id") or "").strip(),
                "title": str(proposal.get("title") or proposal.get("strategy") or "处理建议").strip(),
                "status": status,
                "strategy": str(proposal.get("strategy") or "").strip(),
                "summary": str(proposal.get("summary") or "").strip(),
                "impact": str(proposal.get("impact") or "").strip(),
                "blocking_reason": str(proposal.get("blockingReason") or proposal.get("blocking_reason") or "").strip(),
                "source_check_codes": [
                    str(code or "").strip()
                    for code in proposal.get("sourceCheckCodes", proposal.get("source_check_codes", [])) or []
                    if str(code or "").strip()
                ],
                "actions": [
                    {
                        "action_type": str(action.get("actionType") or action.get("action_type") or "").strip(),
                        "summary": str(action.get("summary") or "").strip(),
                    }
                    for action in actions[:3]
                    if isinstance(action, dict)
                ],
            }
        )
    return {
        "available": bool(data),
        "status": str(data.get("status") or "").strip(),
        "total": _as_int(data.get("total") or len(normalized)),
        "status_counts": status_counts,
        "proposals": normalized[:6],
    }


async def review_plan(
    ctx: RunContext[RequestContext],
    focus: ReviewFocus | None = None,
    career_slots: list[CareerSlot] | None = None,
    generate_fix_proposals: bool = False,
    force_refresh: bool = True,
) -> str:
    """Run or read current plan review without changing the plan.

    Use this only for read-only questions such as "审查一下方案", "有什么风险",
    "这版稳不稳", or "高收费风险大吗". If the user explicitly asks to remove,
    delete, replace, add, sort, or handle a review issue, call
    `preview_plan_action` instead and pass the related `review_issue_code`.
    """
    normalized_focus = str(focus or "full_review").strip().lower() or "full_review"
    if normalized_focus not in {"full_review", "risk_only", "tier_balance", "tuition", "career_fit"}:
        normalized_focus = "full_review"

    plan_summary = await _plan_summary_data(ctx)
    if not plan_summary.get("has_plan"):
        guidance = str(plan_summary.get("guidance") or "").strip()
        no_plan_review_message = guidance or "当前还没有正式方案，暂时不能做方案审查。"
        if "问题" not in no_plan_review_message and "处理" not in no_plan_review_message:
            no_plan_review_message += " 暂时不能判断方案里的具体问题或处理办法。"
        return _json(
            {
                "data": {
                    "focus": normalized_focus,
                    "has_plan": False,
                    "state_mutation": False,
                },
                "next_step": "respond",
                "message": no_plan_review_message,
            }
        )

    review_source = "sandbox"
    review_error = ""
    if force_refresh:
        try:
            response = await internal_client.run_planning_review(
                getattr(ctx.deps, "tenant_id", 1),
                ctx.deps.sessionid,
            )
            review_data = _response_data(response)
            if isinstance(review_data.get("reviewState"), dict):
                review_data = review_data["reviewState"]
            if review_data:
                sandbox = getattr(ctx.deps, "sandbox", None)
                if sandbox is not None:
                    sandbox.invalidate(["plan/review.json", "plan/summary.json"])
                    sandbox.prime(
                        "plan/review.json",
                        {
                            "available": True,
                            "version": _as_int(review_data.get("sourceVersion") or plan_summary.get("version")),
                            "summary": review_data.get("summary") if isinstance(review_data.get("summary"), dict) else {},
                            "checks": review_data.get("checks") if isinstance(review_data.get("checks"), list) else [],
                            "risk_count": _as_int(
                                (review_data.get("summary") or {}).get("riskCount")
                                if isinstance(review_data.get("summary"), dict)
                                else 0
                            ),
                            "warn_count": _as_int(
                                (review_data.get("summary") or {}).get("warnCount")
                                if isinstance(review_data.get("summary"), dict)
                                else 0
                            ),
                        },
                        version=_as_int(review_data.get("sourceVersion") or plan_summary.get("version")),
                    )
                review_source = "run_planning_review"
            else:
                review_error = "empty_review_response"
        except Exception as exc:
            review_error = str(exc)

    review_file = await _sandbox_data(ctx, "plan/review.json")
    checks = review_file.get("checks") if isinstance(review_file.get("checks"), list) else []
    issues = [_normalize_review_issue(check) for check in checks if isinstance(check, dict)]
    filtered_issues = [
        issue for issue in issues
        if not issue.get("passed") and _review_focus_matches(issue, normalized_focus)
    ]
    counts = _review_summary_counts(review_file, issues)
    tier_balance = _tier_balance_from_plan_summary(plan_summary)
    normalized_career_slots, career_labels = _review_career_labels(career_slots)

    fix_proposals: dict[str, Any] = {"available": False, "reason": "not_requested"}
    if generate_fix_proposals:
        try:
            fix_response = await internal_client.generate_planning_fix_proposals(
                getattr(ctx.deps, "tenant_id", 1),
                ctx.deps.sessionid,
            )
            fix_proposals = _normalize_fix_proposals_payload(fix_response)
        except Exception as exc:
            fix_proposals = {"available": False, "status": "error", "error": str(exc)}

    ordered_total = _as_int(plan_summary.get("ordered_total") or plan_summary.get("ordered_target_total"))
    plan_fact = f"当前正式方案有{ordered_total}个志愿" if ordered_total else "当前正式方案已存在"
    career_scope = ""
    if normalized_focus == "career_fit":
        if career_labels:
            career_scope = f"这轮按{'、'.join(career_labels)}看当前方案承接。"
        else:
            career_scope = "这轮按发展方向适配看当前方案承接。"
    if counts["risk_count"] or counts["warn_count"]:
        message = f"已完成方案审查，{plan_fact}，风险{counts['risk_count']}项，提醒{counts['warn_count']}项。"
        if career_scope:
            message += f" {career_scope}"
        if filtered_issues:
            main = "；".join(issue["summary"] for issue in filtered_issues[:3] if issue.get("summary"))
            if main:
                if career_scope:
                    message += f" 当前能直接看到的短板主要是：{main}。"
                else:
                    message += f" 这轮重点看到：{main}。"
    else:
        message = f"已完成方案审查，{plan_fact}，当前没有明显风险或提醒。"
        if career_scope:
            message += f" {career_scope}"
    if career_scope and not filtered_issues:
        message += " 当前通用审查没有直接暴露对应方向的明显冲突；职业方向承接还需要继续结合专业、院校和后续发展路径细看。"
    if normalized_focus != "full_review":
        message += f" 已按{_review_focus_label(normalized_focus)}聚焦过滤。"
    if generate_fix_proposals and fix_proposals.get("total"):
        message += f" 已整理{fix_proposals.get('total')}个处理方向，确认前不会改动方案。"
        proposal_message = _review_fix_proposal_message(fix_proposals)
        if proposal_message:
            message += f" 处理方向包括：{proposal_message}。"
    else:
        message += " 这只是只读审查，确认前不会改动方案。"

    return _json(
        {
            "data": {
                "focus": normalized_focus,
                "review_source": review_source,
                "review_error": review_error,
                "summary": counts,
                "has_plan": True,
                "ordered_total": ordered_total,
                "career_slots": normalized_career_slots,
                "career_labels": career_labels,
                "issues": filtered_issues[:10],
                "all_issue_count": len([issue for issue in issues if not issue.get("passed")]),
                "tier_balance": tier_balance,
                "fix_proposals": fix_proposals,
                "state_mutation": False,
                "plan_mutation": False,
            },
            "next_step": "respond",
            "message": message,
        }
    )


def _resolve_major_name(name: str, *, expected_level: str | None, batch: str | None) -> EntityResolutionResult:
    result = resolve_major_entity(name, batch)
    if expected_level:
        candidates = tuple(candidate for candidate in result.candidates if candidate.level == expected_level)
        if candidates:
            return EntityResolutionResult(
                raw_text=result.raw_text,
                entity_type=result.entity_type,
                candidates=candidates,
                ambiguous=len({candidate.canonical_name for candidate in candidates}) > 1,
            )
        if result.candidates:
            return EntityResolutionResult(raw_text=result.raw_text, entity_type=result.entity_type)
    if result.candidates or not str(name or "").endswith("类"):
        return result
    stripped = str(name or "").removesuffix("类")
    retry = resolve_major_entity(stripped, batch)
    if expected_level:
        candidates = tuple(candidate for candidate in retry.candidates if candidate.level == expected_level)
        if candidates:
            return EntityResolutionResult(
                raw_text=retry.raw_text,
                entity_type=retry.entity_type,
                candidates=candidates,
                ambiguous=len({candidate.canonical_name for candidate in candidates}) > 1,
            )
        if retry.candidates:
            return EntityResolutionResult(raw_text=retry.raw_text, entity_type=retry.entity_type)
    if retry.candidates:
        return retry
    return result


def _attribute_key_for_value(value: Any, candidate_keys: tuple[str, ...]) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    compact_text = "".join(text.split()).lower()
    for key in candidate_keys:
        dimension = ATTRIBUTE_REGISTRY.get(key)
        if dimension is None or not (dimension.values or dimension.aliases):
            continue
        normalized = normalize_attribute_filter_values(key, [text])
        if not normalized:
            continue
        normalized_value = normalized[0]
        if normalized_value != text:
            return key
        if dimension.values and any("".join(str(item).split()).lower() == compact_text for item in dimension.values):
            return key
    return ""


def _school_attribute_key_for_value(value: Any) -> str:
    return _attribute_key_for_value(value, _SCHOOL_INTENT_ATTRIBUTE_KEYS)


def _major_attribute_key_for_value(value: Any) -> str:
    return _attribute_key_for_value(value, _MAJOR_INTENT_ATTRIBUTE_KEYS)


_SEMANTIC_REFERENCE_STRENGTHS = frozenset(
    {
        "reference",
        "weak_reference",
        "soft_reference",
        "preference_reference",
        "readonly",
        "analysis",
        "explore",
        "weak",
    }
)


def _semantic_requirement_domain(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"school", "major", "region", "career", "tuition_budget"}:
        return normalized
    if normalized in {"city", "area", "province"}:
        return "region"
    if normalized in {"tuition", "budget", "fee_budget", "tuitionbudget", "fee"}:
        return "tuition_budget"
    return ""


def _semantic_requirement_side(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"positive", "include", "must_have", "only_keep", "want"}:
        return "positive"
    if normalized in {"negative", "exclude", "reject", "remove"}:
        return "negative"
    return ""


def _semantic_requirement_is_actionable(item: dict[str, Any]) -> bool:
    strength = str(
        item.get("strength")
        or item.get("requirement_strength")
        or item.get("requirementStrength")
        or item.get("status")
        or "explicit"
    ).strip().lower()
    return strength not in _SEMANTIC_REFERENCE_STRENGTHS


def _normalize_tuition_budget_key(key: Any) -> str:
    text = str(key or "").strip()
    if not text:
        return ""
    return _TUITION_BUDGET_KEY_ALIASES.get(text, text)


def _normalize_tuition_budget_values(values: Any) -> list[int]:
    result: list[int] = []
    for value in _as_list(values):
        amount = _as_int(value)
        if amount > 0 and amount not in result:
            result.append(amount)
    return result


def _canonical_semantic_requirement_key(domain: str, key: str) -> str:
    if domain == "tuition_budget":
        return _normalize_tuition_budget_key(key)
    return key


def _semantic_requirement_values(
    item: dict[str, Any],
    key: str,
    *,
    domain: str = "",
    batch: str | None = None,
) -> list[str]:
    values: list[str] = []
    for raw_key in ("values", "value", "entities", "entity_values", "entityValues", "labels"):
        values.extend(_as_list(item.get(raw_key)))
    if domain == "tuition_budget":
        return [str(value) for value in _normalize_tuition_budget_values(values)]
    if domain == "major" and key in {"level1", "level2", "level3", *_MAJOR_ENTITY_SEMANTIC_KEYS}:
        canonical_values: list[str] = []
        expected_level = key if key in {"level1", "level2", "level3"} else "level3"
        for value in values:
            result = _resolve_major_name(value, expected_level=expected_level, batch=batch)
            candidate = result.best
            if candidate is not None and not result.ambiguous:
                _append_unique(canonical_values, candidate.canonical_name)
            else:
                _append_unique(canonical_values, value)
        return canonical_values
    if domain == "region" and key in {"province", "city", "area"}:
        canonical_values = []
        for value in values:
            result = resolve_region_entity(value, expected_level=key)
            candidate = result.best
            if candidate is not None and not result.ambiguous:
                _append_unique(canonical_values, candidate.canonical_name)
            elif key != "area":
                _append_unique(canonical_values, value)
        return canonical_values
    return normalize_attribute_filter_values(key, values)


def _semantic_reference_summary(semantic_requirements: list[dict[str, Any]] | None) -> str:
    if not isinstance(semantic_requirements, list):
        return ""
    labels = {
        "major": "专业方向参考",
        "school": "院校参考",
        "region": "地域参考",
        "career": "发展方向参考",
    }
    grouped: dict[str, list[str]] = {}
    for item in semantic_requirements:
        if not isinstance(item, dict) or _semantic_requirement_is_actionable(item):
            continue
        domain = _semantic_requirement_domain(item.get("domain") or item.get("intent_type") or item.get("intentType"))
        if not domain:
            continue
        values: list[str] = []
        for raw_key in ("values", "value", "entities", "entity_values", "entityValues", "labels"):
            values.extend(_as_list(item.get(raw_key)))
        for value in values:
            _append_unique(grouped.setdefault(domain, []), value)
    parts: list[str] = []
    for domain in ("major", "school", "region", "career"):
        values = grouped.get(domain) or []
        if values:
            parts.append(f"{labels.get(domain, '参考')}：{'、'.join(values[:6])}")
    return "；".join(parts)


def _semantic_attribute_completion_candidates(
    intent_type: str,
    merged: dict[str, Any],
    *,
    semantic_requirements: list[dict[str, Any]] | None,
    batch: str | None = None,
    raw_user_text: str = "",
) -> list[dict[str, Any]]:
    if not isinstance(semantic_requirements, list):
        return []
    missing: list[dict[str, Any]] = []
    for item in semantic_requirements:
        if not isinstance(item, dict) or not _semantic_requirement_is_actionable(item):
            continue
        domain = _semantic_requirement_domain(item.get("domain") or item.get("intent_type") or item.get("intentType"))
        side = _semantic_requirement_side(item.get("side") or item.get("polarity"))
        key = str(item.get("key") or item.get("attribute_key") or item.get("attributeKey") or "").strip()
        if key.startswith("negative_"):
            key = key.removeprefix("negative_")
        key = _canonical_semantic_requirement_key(domain, key)
        if not domain or not side or not key:
            continue
        keys = _INTENT_DOMAIN_SEMANTIC_KEYS.get(domain)
        if not keys or key not in keys:
            continue
        if domain != intent_type and key in _CROSS_DOMAIN_ATTRIBUTE_SUPPLEMENT_EXCLUDED_KEYS:
            continue
        values = _semantic_requirement_values(item, key, domain=domain, batch=batch)
        check_pairs = [(key, value) for value in values]
        if domain == "major" and values:
            semantic_payload_key = f"negative_{key}" if side == "negative" else key
            refined = canonicalize_major_intent_payload(
                {semantic_payload_key: values},
                raw_user_text,
                batch,
            ) or {}
            refined_pairs: list[tuple[str, str]] = []
            for refined_key, refined_values in refined.items():
                refined_side = "negative" if str(refined_key).startswith("negative_") else "positive"
                if refined_side != side:
                    continue
                base_key = str(refined_key).removeprefix("negative_")
                if base_key in {"level1", "level2", "level3", *_MAJOR_INTENT_ATTRIBUTE_KEYS}:
                    refined_pairs.extend((base_key, value) for value in _as_list(refined_values))
            if refined_pairs:
                check_pairs = refined_pairs
        missing_values = [
            value
            for check_key, value in check_pairs
            if not _merged_contains_attribute_value(
                merged,
                domain=domain,
                side=side,
                key=check_key,
                value=value,
                batch=batch,
            )
        ]
        if not missing_values:
            continue
        missing.append(
            {
                "domain": domain,
                "side": side,
                "key": key,
                "values": missing_values,
                "target_payload_path": f"{side}.{key}",
            }
        )
    return missing


def _attribute_values_from_payload(payload: dict[str, Any] | None, keys: tuple[str, ...]) -> dict[str, list[str]]:
    if not isinstance(payload, dict):
        return {}
    result: dict[str, list[str]] = {}
    for key in keys:
        raw_keys = {
            key,
            key.replace("_", ""),
            key.removeprefix("school_"),
            key.removeprefix("major_"),
            key.removeprefix("program_"),
            *_INTENT_ATTRIBUTE_KEY_ALIASES.get(key, ()),
        }
        values: list[str] = []
        for raw_key in raw_keys:
            values.extend(_as_list(payload.get(raw_key)))
        normalized_values = normalize_attribute_filter_values(key, values)
        for value in normalized_values:
            _append_unique(result.setdefault(key, []), value)
    return result


def _structured_cross_domain_attributes_from_payloads(
    intent_type: str,
    *,
    positive: dict[str, Any] | None,
    negative: dict[str, Any] | None,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for domain, keys in _INTENT_DOMAIN_ATTRIBUTE_KEYS.items():
        if domain == intent_type:
            continue
        section = _INTENT_DOMAIN_SECTION.get(domain)
        if not section:
            continue
        positive_values = _attribute_values_from_payload(positive, keys)
        negative_values = _attribute_values_from_payload(negative, keys)
        section_payload: dict[str, list[str]] = {}
        for key, values in positive_values.items():
            if key in _CROSS_DOMAIN_ATTRIBUTE_SUPPLEMENT_EXCLUDED_KEYS:
                continue
            for value in values:
                _append_unique(section_payload.setdefault(key, []), value)
        for key, values in negative_values.items():
            if key in _CROSS_DOMAIN_ATTRIBUTE_SUPPLEMENT_EXCLUDED_KEYS:
                continue
            target_key = f"negative_{key}"
            for value in values:
                _append_unique(section_payload.setdefault(target_key, []), value)
        if section_payload:
            merged[section] = section_payload
    return merged


def _merge_merged_intents(*payloads: dict[str, Any] | None) -> dict[str, Any]:
    selected = [payload for payload in payloads if isinstance(payload, dict) and payload]
    if not selected:
        return {}
    return _merge_selected_values(selected)


def _canonicalize_merged_intents_for_constraint(
    merged: dict[str, Any],
    *,
    constraint_type: str,
) -> dict[str, Any]:
    if constraint_type != "only_keep" or not isinstance(merged, dict):
        return merged
    school_intents = merged.get("school_intents")
    if not isinstance(school_intents, dict):
        return merged
    positive_nature = set(_as_list(school_intents.get("school_nature")))
    negative_nature = _as_list(school_intents.get("negative_school_nature"))
    if not positive_nature or not negative_nature:
        return merged
    redundant_by_positive = {
        "公办": {"民办"},
        "民办": {"公办"},
    }
    redundant: set[str] = set()
    for value in positive_nature:
        redundant.update(redundant_by_positive.get(value, set()))
    if not redundant:
        return merged
    pruned_negative = [value for value in negative_nature if value not in redundant]
    if len(pruned_negative) == len(negative_nature):
        return merged
    canonical = dict(merged)
    canonical_school = dict(school_intents)
    if pruned_negative:
        canonical_school["negative_school_nature"] = pruned_negative
    else:
        canonical_school.pop("negative_school_nature", None)
    canonical["school_intents"] = canonical_school
    return canonical


def _merged_contains_attribute_value(
    merged: dict[str, Any],
    *,
    domain: str,
    side: str,
    key: str,
    value: str,
    batch: str | None = None,
) -> bool:
    section = _INTENT_DOMAIN_SECTION.get(domain)
    if not section:
        return False
    section_payload = merged.get(section) if isinstance(merged.get(section), dict) else {}
    if domain == "tuition_budget":
        candidate_key = _normalize_tuition_budget_key(key)
        expected_amount = _as_int(value)
        if not candidate_key or expected_amount <= 0:
            return False
        return expected_amount in {
            _as_int(item)
            for item in _as_list(section_payload.get(candidate_key))
            if _as_int(item) > 0
        }
    if domain == "major" and key in _MAJOR_ENTITY_SEMANTIC_KEYS:
        candidate_keys = ("level1", "level2", "level3")
    elif domain == "school" and key in _SCHOOL_ENTITY_SEMANTIC_KEYS:
        candidate_keys = ("colleges",)
    else:
        candidate_keys = (key,)
    expected = str(value or "").strip()
    if not expected:
        return False
    if domain == "major" and key in {"level1", "level2", "level3"}:
        target_key = f"negative_{key}" if side == "negative" else key
        if expected in set(_as_list(section_payload.get(target_key))):
            return True
        mappings = major_parent_mappings_for_batch(batch)
        level3_to_level2 = mappings.get("level3_to_level2", {})
        level2_to_level1 = mappings.get("level2_to_level1", {})
        if key == "level2":
            parent_level1 = level2_to_level1.get(expected)
            parent_key = "negative_level1" if side == "negative" else "level1"
            return bool(parent_level1 and parent_level1 in set(_as_list(section_payload.get(parent_key))))
        if key == "level3":
            parent_level2 = level3_to_level2.get(expected)
            parent_level1 = level2_to_level1.get(parent_level2 or "")
            parent_level2_key = "negative_level2" if side == "negative" else "level2"
            parent_level1_key = "negative_level1" if side == "negative" else "level1"
            return bool(
                (parent_level2 and parent_level2 in set(_as_list(section_payload.get(parent_level2_key))))
                or (parent_level1 and parent_level1 in set(_as_list(section_payload.get(parent_level1_key))))
            )
    for candidate_key in candidate_keys:
        target_key = f"negative_{candidate_key}" if side == "negative" else candidate_key
        if expected in set(_as_list(section_payload.get(target_key))):
            return True
    return False


def _add_display_alias(display_aliases: dict[str, str], raw_text: Any, canonical_name: Any) -> None:
    raw = str(raw_text or "").strip()
    canonical = str(canonical_name or "").strip()
    if not raw or not canonical or _compact_text(raw) == _compact_text(canonical):
        return
    display_aliases.setdefault(canonical, raw)


def _merge_display_aliases(*aliases: dict[str, str] | None) -> dict[str, str]:
    merged: dict[str, str] = {}
    for alias_map in aliases:
        if not isinstance(alias_map, dict):
            continue
        for canonical, raw in alias_map.items():
            canonical_text = str(canonical or "").strip()
            raw_text = str(raw or "").strip()
            if canonical_text and raw_text and canonical_text not in merged:
                merged[canonical_text] = raw_text
    return merged


def _major_display_aliases_from_user_text(
    merged: dict[str, Any],
    raw_user_text: str,
    *,
    batch: str | None,
) -> dict[str, str]:
    compact_user_text = _compact_text(raw_user_text)
    if not compact_user_text:
        return {}
    major_intents = merged.get("major_intents") if isinstance(merged.get("major_intents"), dict) else {}
    if not major_intents:
        return {}
    aliases: dict[str, str] = {}
    for key in ("level1", "level2", "level3", "negative_level1", "negative_level2", "negative_level3"):
        for canonical in _as_list(major_intents.get(key)):
            canonical_text = str(canonical or "").strip()
            if not canonical_text:
                continue
            if _compact_text(canonical_text) in compact_user_text:
                continue
            for alias in sorted(major_alias_variants_for_name(canonical_text, batch), key=len, reverse=True):
                compact_alias = _compact_text(alias)
                if compact_alias and compact_alias in compact_user_text:
                    _add_display_alias(aliases, alias, canonical_text)
                    break
    return aliases


def _normalize_major_payload(
    payload: dict[str, Any] | None,
    *,
    batch: str | None,
) -> tuple[dict[str, list[str]], list[dict[str, Any]], dict[str, str]]:
    normalized = {"level1": [], "level2": [], "level3": []}
    ambiguities: list[dict[str, Any]] = []
    display_aliases: dict[str, str] = {}
    if not payload:
        return normalized, ambiguities, display_aliases

    for key in _MAJOR_INTENT_ATTRIBUTE_KEYS:
        values: list[str] = []
        raw_keys = {
            key,
            key.replace("_", ""),
            key.removeprefix("major_"),
            key.removeprefix("program_"),
            *_INTENT_ATTRIBUTE_KEY_ALIASES.get(key, ()),
        }
        for raw_key in raw_keys:
            values.extend(_as_list(payload.get(raw_key)))
        normalized_values = normalize_attribute_filter_values(key, values)
        if normalized_values:
            normalized[key] = normalized_values

    for level in ("level1", "level2", "level3"):
        for name in _as_list(payload.get(level)):
            result = _resolve_major_name(name, expected_level=level, batch=batch)
            if result.ambiguous:
                ambiguities.append(_ambiguity_data(result))
                continue
            candidate = result.best
            if candidate is None:
                _append_unique(normalized[level], name)
                continue
            target_level = candidate.level if candidate.level in normalized else level
            _append_unique(normalized[target_level], candidate.canonical_name)
            _add_display_alias(display_aliases, name or candidate.raw_text, candidate.canonical_name)
    for key in ("items", "values", "names"):
        for name in _as_list(payload.get(key)):
            attribute_key = _major_attribute_key_for_value(name)
            if attribute_key:
                normalized_values = normalize_attribute_filter_values(attribute_key, [name])
                for value in normalized_values:
                    _append_unique(normalized.setdefault(attribute_key, []), value)
                continue
            result = _resolve_major_name(name, expected_level=None, batch=batch)
            if result.ambiguous:
                ambiguities.append(_ambiguity_data(result))
                continue
            candidate = result.best
            if candidate is not None and candidate.level in normalized:
                _append_unique(normalized[candidate.level], candidate.canonical_name)
                _add_display_alias(display_aliases, name or candidate.raw_text, candidate.canonical_name)
            else:
                _append_unique(normalized["level3"], name)
    for key in _MAJOR_ENTITY_SEMANTIC_KEYS:
        for name in _as_list(payload.get(key)):
            attribute_key = _major_attribute_key_for_value(name)
            if attribute_key:
                normalized_values = normalize_attribute_filter_values(attribute_key, [name])
                for value in normalized_values:
                    _append_unique(normalized.setdefault(attribute_key, []), value)
                continue
            result = _resolve_major_name(name, expected_level="level3", batch=batch)
            if result.ambiguous:
                ambiguities.append(_ambiguity_data(result))
                continue
            candidate = result.best
            if candidate is not None:
                _append_unique(normalized["level3"], candidate.canonical_name)
                _add_display_alias(display_aliases, name or candidate.raw_text, candidate.canonical_name)
            else:
                _append_unique(normalized["level3"], name)
    return normalized, ambiguities, display_aliases


def _normalize_school_payload(
    payload: dict[str, Any] | None,
    *,
    batch: str | None,
) -> tuple[dict[str, list[str]], list[dict[str, Any]], dict[str, str]]:
    normalized = {"schools": []}
    ambiguities: list[dict[str, Any]] = []
    display_aliases: dict[str, str] = {}
    if not payload:
        return normalized, ambiguities, display_aliases
    for key in _SCHOOL_INTENT_ATTRIBUTE_KEYS:
        values: list[str] = []
        for raw_key in {key, key.replace("_", ""), key.removeprefix("school_"), key.removeprefix("program_")}:
            values.extend(_as_list(payload.get(raw_key)))
        normalized_values = normalize_attribute_filter_values(key, values)
        if normalized_values:
            normalized[key] = normalized_values
    for key in (
        "schools",
        "colleges",
        "items",
        "values",
        "names",
        "school_name",
        "school_names",
        "schoolName",
        "schoolNames",
    ):
        for name in _as_list(payload.get(key)):
            attribute_key = _school_attribute_key_for_value(name)
            if attribute_key:
                normalized_values = normalize_attribute_filter_values(attribute_key, [name])
                for value in normalized_values:
                    _append_unique(normalized.setdefault(attribute_key, []), value)
                continue
            result = resolve_school_entity(name, batch)
            if result.ambiguous:
                ambiguities.append(_ambiguity_data(result))
                continue
            candidate = result.best
            canonical = candidate.canonical_name if candidate else name
            _append_unique(normalized["schools"], canonical)
            if candidate is not None:
                _add_display_alias(display_aliases, name or candidate.raw_text, candidate.canonical_name)
    return normalized, ambiguities, display_aliases


def _normalize_region_payload(payload: dict[str, Any] | None) -> tuple[dict[str, list[str]], list[dict[str, Any]], dict[str, str]]:
    normalized = {"province": [], "city": [], "area": []}
    ambiguities: list[dict[str, Any]] = []
    display_aliases: dict[str, str] = {}
    if not payload:
        return normalized, ambiguities, display_aliases

    for level in ("province", "city", "area"):
        for name in _as_list(payload.get(level)):
            result = resolve_region_entity(name, expected_level=level)
            if result.ambiguous:
                ambiguities.append(_ambiguity_data(result))
                continue
            candidate = result.best
            if candidate is None and level == "area":
                continue
            canonical = candidate.canonical_name if candidate else name
            _append_unique(normalized[level], canonical)
            if candidate is not None:
                _add_display_alias(display_aliases, name or candidate.raw_text, candidate.canonical_name)

    for key in ("area_region", "area_regions", "areaRegion", "areaRegions", "region_area", "region_areas", "regionArea", "regionAreas"):
        for name in _as_list(payload.get(key)):
            result = resolve_region_entity(name, expected_level="area")
            if result.ambiguous:
                ambiguities.append(_ambiguity_data(result))
                continue
            candidate = result.best
            if candidate is None:
                continue
            _append_unique(normalized["area"], candidate.canonical_name)
            _add_display_alias(display_aliases, name or candidate.raw_text, candidate.canonical_name)

    for key in ("region_group", "region_groups", "regions", "items", "values", "names"):
        for name in _as_list(payload.get(key)):
            result = resolve_region_entity(name)
            if result.ambiguous:
                ambiguities.append(_ambiguity_data(result))
                continue
            candidate = result.best
            if candidate is not None and candidate.level in normalized:
                _append_unique(normalized[candidate.level], candidate.canonical_name)
                _add_display_alias(display_aliases, name or candidate.raw_text, candidate.canonical_name)
            else:
                _append_unique(normalized["province"], name)
    return normalized, ambiguities, display_aliases


def _normalize_career_payload(payload: dict[str, Any] | None) -> tuple[dict[str, list[str]], list[dict[str, Any]], dict[str, str]]:
    if not payload:
        return {"slots": []}, [], {}
    values: list[str] = []
    for key in ("slots", "career", "items", "values", "names"):
        values.extend(_as_list(payload.get(key)))
    slots = normalize_career_slots(values)
    unknown = [value for value in values if value and value not in slots and not normalize_career_slots([value])]
    result = {"slots": slots}
    if unknown:
        result["unknown"] = list(dict.fromkeys(unknown))
    return result, [], {}


def _normalize_tuition_budget_payload(payload: dict[str, Any] | None) -> tuple[dict[str, list[int]], list[dict[str, Any]], dict[str, str]]:
    normalized: dict[str, list[int]] = {
        "max_tuition_per_year": [],
        "min_tuition_per_year": [],
    }
    if not isinstance(payload, dict) or not payload:
        return normalized, [], {}
    buckets: dict[str, list[int]] = {
        "max_tuition_per_year": [],
        "min_tuition_per_year": [],
    }
    for raw_key, raw_value in payload.items():
        key = _normalize_tuition_budget_key(raw_key)
        if key not in buckets:
            continue
        for amount in _normalize_tuition_budget_values(raw_value):
            if amount not in buckets[key]:
                buckets[key].append(amount)
    if buckets["max_tuition_per_year"]:
        normalized["max_tuition_per_year"] = [min(buckets["max_tuition_per_year"])]
    if buckets["min_tuition_per_year"]:
        normalized["min_tuition_per_year"] = [max(buckets["min_tuition_per_year"])]
    return normalized, [], {}


def _normalize_intent_side(
    intent_type: str,
    payload: dict[str, Any] | None,
    *,
    batch: str | None,
) -> tuple[dict[str, list[str]], list[dict[str, Any]], dict[str, str]]:
    if intent_type == "major":
        return _normalize_major_payload(payload, batch=batch)
    if intent_type == "school":
        return _normalize_school_payload(payload, batch=batch)
    if intent_type == "region":
        return _normalize_region_payload(payload)
    if intent_type == "career":
        return _normalize_career_payload(payload)
    if intent_type == "tuition_budget":
        return _normalize_tuition_budget_payload(payload)
    return {}, [], {}


def _major_text_requests_broad_scope(raw_user_text: str) -> bool:
    text = _compact_text(raw_user_text)
    return any(marker in text for marker in ("相关", "有关", "类似", "这类", "一类", "之类", "方向", "大类"))


def _refine_major_payload_by_user_text(
    normalized: dict[str, Any],
    *,
    raw_user_text: str,
    batch: str | None,
) -> dict[str, Any]:
    if not str(raw_user_text or "").strip():
        return normalized
    if _major_text_requests_broad_scope(raw_user_text):
        return normalized
    positive = normalized.get("positive") if isinstance(normalized.get("positive"), dict) else {}
    negative = normalized.get("negative") if isinstance(normalized.get("negative"), dict) else {}
    major_payload: dict[str, Any] = {}
    for level in ("level1", "level2", "level3"):
        values = _as_list(positive.get(level))
        if values:
            major_payload[level] = values
        negative_values = _as_list(negative.get(level))
        if negative_values:
            major_payload[f"negative_{level}"] = negative_values
    if not major_payload:
        return normalized
    refined = canonicalize_major_intent_payload(major_payload, raw_user_text, batch) or {}
    refined_positive = dict(positive)
    refined_negative = dict(negative)
    for level in ("level1", "level2", "level3"):
        refined_positive[level] = _as_list(refined.get(level))
        refined_negative[level] = _as_list(refined.get(f"negative_{level}"))
    return {
        "positive": refined_positive,
        "negative": refined_negative,
    }


def _preview_message(
    intent_type: str,
    normalized: dict[str, Any],
    constraint_type: str,
    display_aliases: dict[str, str] | None = None,
) -> str:
    labels = {
        "major": "专业要求",
        "school": "院校要求",
        "region": "地域要求",
        "career": "发展方向要求",
        "tuition_budget": "学费预算要求",
    }
    label = labels.get(intent_type, "报考要求")
    positive = normalized.get("positive") or {}
    negative = normalized.get("negative") or {}
    parts: list[str] = []
    for name, payload in (("要", positive), ("不要", negative)):
        values: list[str] = []
        if isinstance(payload, dict):
            for item in payload.values():
                for value in _as_list(item):
                    display = _display_intent_value(value, display_aliases)
                    if display:
                        values.append(display)
        if values:
            parts.append(f"{name}：{'、'.join(list(dict.fromkeys(values))[:6])}")
    detail = "；".join(parts) if parts else "未识别到明确实体"
    if intent_type == "career":
        detail = detail.replace("system_public_service", to_career_label("system_public_service"))
    return f"我先把这次{label}整理成待确认预览：{detail}。确认前不会生效。"


def _display_intent_value(value: Any, display_aliases: dict[str, str] | None = None) -> str:
    text = to_career_label(value) if value == "system_public_service" else str(value or "").strip()
    if not text:
        return ""
    raw = str((display_aliases or {}).get(text) or "").strip()
    if raw and _compact_text(raw) != _compact_text(text):
        return f"{raw}（{text}）"
    return text


def _intent_values_for_summary(
    payload: dict[str, Any],
    keys: tuple[str, ...],
    *,
    display_aliases: dict[str, str] | None = None,
) -> list[str]:
    values: list[str] = []
    for key in keys:
        for item in _as_list(payload.get(key)):
            text = _display_intent_value(item, display_aliases)
            if text and text not in values:
                values.append(text)
    return values


def _summary_part(label: str, positive: list[str], negative: list[str]) -> str | None:
    parts: list[str] = []
    if positive:
        parts.append(f"要：{'、'.join(positive[:6])}")
    if negative:
        parts.append(f"不要：{'、'.join(negative[:6])}")
    if not parts:
        return None
    return f"{label}：{'；'.join(parts)}"


def _display_aliases_from_merged(merged: dict[str, Any], display_aliases: dict[str, str] | None = None) -> dict[str, str]:
    embedded = merged.get("_display_aliases") if isinstance(merged, dict) else None
    return _merge_display_aliases(embedded if isinstance(embedded, dict) else None, display_aliases)


def _first_positive_amount(values: Any) -> int:
    amounts = [_as_int(value) for value in _as_list(values)]
    amounts = [value for value in amounts if value > 0]
    return amounts[0] if amounts else 0


def _tuition_budget_summary_part(payload: dict[str, Any]) -> str | None:
    min_tuition = _first_positive_amount(payload.get("min_tuition_per_year") or payload.get("minTuitionPerYear"))
    max_tuition = _first_positive_amount(payload.get("max_tuition_per_year") or payload.get("maxTuitionPerYear"))
    if min_tuition > 0 and max_tuition > 0:
        return f"学费预算：每年 {min_tuition}-{max_tuition} 元"
    if max_tuition > 0:
        return f"学费预算：每年不超过 {max_tuition} 元"
    if min_tuition > 0:
        return f"学费预算：每年不少于 {min_tuition} 元"
    return None


def _intent_summary_from_merged(merged: dict[str, Any], display_aliases: dict[str, str] | None = None) -> str:
    display_aliases = _display_aliases_from_merged(merged, display_aliases)
    major_intents = merged.get("major_intents") if isinstance(merged.get("major_intents"), dict) else {}
    school_intents = merged.get("school_intents") if isinstance(merged.get("school_intents"), dict) else {}
    city_intents = merged.get("city_intents") if isinstance(merged.get("city_intents"), dict) else {}
    career_intents = merged.get("career_intents") if isinstance(merged.get("career_intents"), dict) else {}
    tuition_budget = merged.get("tuition_budget") if isinstance(merged.get("tuition_budget"), dict) else {}
    parts = [
        _summary_part(
            "专业要求",
            _intent_values_for_summary(
                major_intents,
                ("level1", "level2", "level3") + _MAJOR_INTENT_ATTRIBUTE_KEYS,
                display_aliases=display_aliases,
            ),
            _intent_values_for_summary(
                major_intents,
                ("negative_level1", "negative_level2", "negative_level3")
                + tuple(f"negative_{key}" for key in _MAJOR_INTENT_ATTRIBUTE_KEYS),
                display_aliases=display_aliases,
            ),
        ),
        _summary_part(
            "院校要求",
            _intent_values_for_summary(
                school_intents,
                ("colleges",) + _SCHOOL_INTENT_ATTRIBUTE_KEYS,
                display_aliases=display_aliases,
            ),
            _intent_values_for_summary(
                school_intents,
                ("negative_colleges",) + tuple(f"negative_{key}" for key in _SCHOOL_INTENT_ATTRIBUTE_KEYS),
                display_aliases=display_aliases,
            ),
        ),
        _summary_part(
            "地域要求",
            _intent_values_for_summary(city_intents, ("province", "city", "area"), display_aliases=display_aliases),
            _intent_values_for_summary(
                city_intents,
                ("negative_province", "negative_city", "negative_area"),
                display_aliases=display_aliases,
            ),
        ),
        _summary_part(
            "发展方向要求",
            _intent_values_for_summary(career_intents, ("positive",), display_aliases=display_aliases),
            _intent_values_for_summary(career_intents, ("negative",), display_aliases=display_aliases),
        ),
        _tuition_budget_summary_part(tuition_budget),
    ]
    return "；".join(part for part in parts if part) or "本次报考要求"


def _preview_message_from_merged(merged: dict[str, Any], display_aliases: dict[str, str] | None = None) -> str:
    return f"我先把这次报考要求整理成待确认预览：{_intent_summary_from_merged(merged, display_aliases)}。确认前不会生效。"


def _merged_intents_have_values(merged: dict[str, Any]) -> bool:
    for section_name in ("major_intents", "school_intents", "city_intents", "career_intents", "tuition_budget"):
        section = merged.get(section_name) if isinstance(merged, dict) else None
        if not isinstance(section, dict):
            continue
        for key, value in section.items():
            if str(key or "").startswith("_"):
                continue
            if _as_list(value):
                return True
    return False


def _merged_intents_from_normalized(intent_type: str, normalized: dict[str, Any]) -> dict[str, Any]:
    positive = normalized.get("positive") if isinstance(normalized.get("positive"), dict) else {}
    negative = normalized.get("negative") if isinstance(normalized.get("negative"), dict) else {}
    if intent_type == "major":
        payload: dict[str, list[str]] = {}
        for level in ("level1", "level2", "level3"):
            values = _as_list(positive.get(level))
            if values:
                payload[level] = values
            negative_values = _as_list(negative.get(level))
            if negative_values:
                payload[f"negative_{level}"] = negative_values
        for key in _MAJOR_INTENT_ATTRIBUTE_KEYS:
            values = _as_list(positive.get(key))
            if values:
                payload[key] = values
            negative_values = _as_list(negative.get(key))
            if negative_values:
                payload[f"negative_{key}"] = negative_values
        return {"major_intents": payload} if payload else {}
    if intent_type == "school":
        schools = _as_list(positive.get("schools"))
        negative_schools = _as_list(negative.get("schools"))
        payload = {}
        if schools:
            payload["colleges"] = schools
        if negative_schools:
            payload["negative_colleges"] = negative_schools
        for key in _SCHOOL_INTENT_ATTRIBUTE_KEYS:
            values = _as_list(positive.get(key))
            if values:
                payload[key] = values
            negative_values = _as_list(negative.get(key))
            if negative_values:
                payload[f"negative_{key}"] = negative_values
        return {"school_intents": payload} if payload else {}
    if intent_type == "region":
        payload = {}
        for key in ("province", "city", "area"):
            values = _as_list(positive.get(key))
            if values:
                payload[key] = values
            negative_values = _as_list(negative.get(key))
            if negative_values:
                payload[f"negative_{key}"] = negative_values
        return {"city_intents": payload} if payload else {}
    if intent_type == "career":
        positive_slots = _as_list(positive.get("slots"))
        negative_slots = _as_list(negative.get("slots"))
        payload = {}
        if positive_slots:
            payload["positive"] = positive_slots
        if negative_slots:
            payload["negative"] = negative_slots
        return {"career_intents": payload} if payload else {}
    if intent_type == "tuition_budget":
        payload = {}
        for key in _TUITION_BUDGET_INTENT_KEYS:
            amounts = [
                _as_int(value)
                for value in (_as_list(positive.get(key)) + _as_list(negative.get(key)))
                if _as_int(value) > 0
            ]
            if not amounts:
                continue
            payload[key] = [min(amounts)] if key == "max_tuition_per_year" else [max(amounts)]
        return {"tuition_budget": payload} if payload else {}
    return {}


def _selected_values_from_merged(merged: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {section: payload}
        for section, payload in merged.items()
        if not str(section or "").startswith("_")
        and isinstance(payload, dict)
        and any(_as_list(value) for value in payload.values())
    ]


def _intent_mode_from_constraint(constraint_type: str) -> str:
    return "constraint"


def _constraint_intent_type(constraint_type: str) -> str:
    if constraint_type in {"exclude", "only_keep", "must_have"}:
        return constraint_type
    return "exclude"


def _merged_has_positive_values(merged: dict[str, Any]) -> bool:
    for section, section_payload in merged.items():
        if str(section or "").startswith("_"):
            continue
        if not isinstance(section_payload, dict):
            continue
        for key, raw_values in section_payload.items():
            if str(key or "").startswith("negative_"):
                continue
            if key == "negative":
                continue
            if _as_list(raw_values):
                return True
    return False


def _merged_has_negative_values(merged: dict[str, Any]) -> bool:
    for section, section_payload in merged.items():
        if str(section or "").startswith("_"):
            continue
        if not isinstance(section_payload, dict):
            continue
        for key, raw_values in section_payload.items():
            if str(key or "").startswith("negative_") or key == "negative":
                if _as_list(raw_values):
                    return True
    return False


def _merged_has_tuition_budget(merged: dict[str, Any]) -> bool:
    budget = merged.get("tuition_budget") if isinstance(merged.get("tuition_budget"), dict) else {}
    return _payload_has_values(budget)


def _combined_constraint_type(
    *,
    existing: str,
    current: str,
    merged: dict[str, Any],
) -> str:
    if existing == "only_keep" or current == "only_keep":
        return "only_keep"
    if _merged_has_positive_values(merged):
        return "must_have"
    if _merged_has_negative_values(merged):
        return "exclude"
    return current if current in {"exclude", "only_keep", "must_have"} else "exclude"


def _payload_has_values(payload: dict[str, Any]) -> bool:
    return any(_as_list(value) for value in payload.values())


def _item_violates_tuition_budget(item: dict[str, Any], payload: dict[str, Any]) -> bool:
    tuition = _item_tuition(item)
    if tuition <= 0:
        return False
    max_tuition = _first_positive_amount(payload.get("max_tuition_per_year") or payload.get("maxTuitionPerYear"))
    if max_tuition > 0 and tuition > max_tuition:
        return True
    min_tuition = _first_positive_amount(payload.get("min_tuition_per_year") or payload.get("minTuitionPerYear"))
    if min_tuition > 0 and tuition < min_tuition:
        return True
    return False




def _region_area_contains_province(area: Any, province: Any) -> bool:
    province_text = _compact_text(province)
    if not province_text:
        return False
    provinces = REGION_AREA_PROVINCES.get(str(area or "").strip())
    if not provinces:
        return False
    return any(_compact_text(item) == province_text for item in provinces)

def _plan_item_matches_intent_payload(item: dict[str, Any], intent_type: str, payload: dict[str, Any]) -> bool:
    if intent_type == "tuition_budget":
        return _item_violates_tuition_budget(item, payload)
    if intent_type == "major":
        values: list[str] = []
        for key in ("level1", "level2", "level3"):
            values.extend(_as_list(payload.get(key)))
        text_hit = _matches_any_text(_item_major_names(item), values) if values else False
        attribute_hit = any(
            match_attribute_item(key, item, _as_list(payload.get(key)))
            for key in _MAJOR_INTENT_ATTRIBUTE_KEYS
            if _as_list(payload.get(key))
        )
        return text_hit or attribute_hit
    if intent_type == "school":
        values = _as_list(payload.get("schools"))
        actual = str(_item_value(item, "schoolName", "school_name", "collegeName") or "").strip()
        text_hit = _matches_any_text([actual], values) if values else False
        attribute_hit = any(
            match_attribute_item(key, item, _as_list(payload.get(key)))
            for key in _SCHOOL_INTENT_ATTRIBUTE_KEYS
            if _as_list(payload.get(key))
        )
        return text_hit or attribute_hit
    if intent_type == "region":
        values = []
        values.extend(_as_list(payload.get("province")))
        values.extend(_as_list(payload.get("city")))
        actual_province = str(_item_value(item, "provinceName", "province_name", "province") or "").strip()
        actual_city = str(_item_value(item, "cityName", "city_name", "city") or "").strip()
        if values and _matches_any_text([actual_province, actual_city], values):
            return True
        for area in _as_list(payload.get("area")):
            if _region_area_contains_province(area, actual_province):
                return True
        return False
    return False


def _plan_item_matches_intent(
    item: dict[str, Any],
    intent_type: str,
    normalized: dict[str, Any],
    constraint_type: str,
) -> bool:
    negative = normalized.get("negative") if isinstance(normalized.get("negative"), dict) else {}
    positive = normalized.get("positive") if isinstance(normalized.get("positive"), dict) else {}
    if intent_type == "tuition_budget":
        payload = positive if _payload_has_values(positive) else negative
        return _item_violates_tuition_budget(item, payload)
    if constraint_type == "only_keep" and _payload_has_values(positive):
        return not _plan_item_matches_intent_payload(item, intent_type, positive)
    if constraint_type == "exclude" and _payload_has_values(negative):
        return _plan_item_matches_intent_payload(item, intent_type, negative)
    if _payload_has_values(negative):
        return _plan_item_matches_intent_payload(item, intent_type, negative)
    if _payload_has_values(positive):
        return _plan_item_matches_intent_payload(item, intent_type, positive)
    return False


async def _local_plan_impact(
    ctx: RunContext[RequestContext],
    intent_type: str,
    normalized: dict[str, Any],
    constraint_type: str,
) -> dict[str, Any]:
    plan_file = await _sandbox_data(ctx, "plan/items.json")
    items = _items_from_plan_file(plan_file)
    matched = [
        item
        for item in items
        if _plan_item_matches_intent(item, intent_type, normalized, constraint_type)
    ]
    tier_counts: dict[str, int] = {}
    for item in matched:
        tier = _normalize_tier(_item_value(item, "tier", "riskTier", "risk_tier")) or "未分层"
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
    return {
        "source": "local_plan_items",
        "available": bool(items),
        "affected_count": len(matched),
        "affected_items": [_plan_item_snippet(item) for item in matched[:8]],
        "tier_impact": {key: -value for key, value in tier_counts.items()},
    }


def _merge_list_with_emotion(
    existing_values: Any,
    existing_emotions: Any,
    new_values: list[str],
    *,
    default_emotion: str = "Strong",
) -> tuple[list[str], list[str]]:
    values = _as_list(existing_values)
    emotions = _as_list(existing_emotions)
    while len(emotions) < len(values):
        emotions.append(default_emotion)
    existing = set(values)
    for value in new_values:
        text = str(value or "").strip()
        if text and text not in existing:
            values.append(text)
            emotions.append(default_emotion)
            existing.add(text)
    return values, emotions


def _merge_profile_list(existing_values: Any, new_values: list[str]) -> list[str]:
    values = _as_list(existing_values)
    for value in new_values:
        text = str(value or "").strip()
        if text and text not in values:
            values.append(text)
    return values


def _proposed_profile_from_intent(
    current_profile: UserProfile | None,
    *,
    intent_type: str,
    normalized: dict[str, Any],
    batch: str,
) -> dict[str, Any] | None:
    if current_profile is None or intent_type in {"career", "tuition_budget"} or not hasattr(current_profile, "to_backend_format"):
        return None

    profile = deepcopy(current_profile).to_backend_format()
    merged = _merged_intents_from_normalized(intent_type, normalized)
    major_intents = merged.get("major_intents") if isinstance(merged.get("major_intents"), dict) else {}
    school_intents = merged.get("school_intents") if isinstance(merged.get("school_intents"), dict) else {}
    city_intents = merged.get("city_intents") if isinstance(merged.get("city_intents"), dict) else {}

    if any(_as_list(major_intents.get(key)) for key in _MAJOR_INTENT_ATTRIBUTE_KEYS):
        return None
    if any(_as_list(major_intents.get(f"negative_{key}")) for key in _MAJOR_INTENT_ATTRIBUTE_KEYS):
        return None
    if any(_as_list(school_intents.get(key)) for key in _SCHOOL_INTENT_ATTRIBUTE_KEYS):
        return None
    if any(_as_list(school_intents.get(f"negative_{key}")) for key in _SCHOOL_INTENT_ATTRIBUTE_KEYS):
        return None

    if major_intents:
        positive = profile.setdefault("major_intent", {})
        negative = profile.setdefault("negative_major_intent", {})
        for level in ("level1", "level2", "level3"):
            values = _as_list(major_intents.get(level))
            if values:
                positive[level], positive[f"{level}_emotion"] = _merge_list_with_emotion(
                    positive.get(level),
                    positive.get(f"{level}_emotion"),
                    values,
                )
            negative_values = _as_list(major_intents.get(f"negative_{level}"))
            if negative_values:
                negative[level], negative[f"{level}_emotion"] = _merge_list_with_emotion(
                    negative.get(level),
                    negative.get(f"{level}_emotion"),
                    negative_values,
                )

    if school_intents:
        positive = profile.setdefault("college_info", {})
        negative = profile.setdefault("negative_college_info", {})
        values = _as_list(school_intents.get("colleges"))
        if values:
            positive["values"], positive["values_emotion"] = _merge_list_with_emotion(
                positive.get("values"),
                positive.get("values_emotion"),
                values,
            )
        negative_values = _as_list(school_intents.get("negative_colleges"))
        if negative_values:
            negative["values"], negative["values_emotion"] = _merge_list_with_emotion(
                negative.get("values"),
                negative.get("values_emotion"),
                negative_values,
            )

    if city_intents:
        positive = profile.setdefault("city_info", {})
        negative = profile.setdefault("negative_city_info", {})
        for key in ("province", "city"):
            values = _as_list(city_intents.get(key))
            if values:
                positive[key], positive[f"{key}_emotion"] = _merge_list_with_emotion(
                    positive.get(key),
                    positive.get(f"{key}_emotion"),
                    values,
                )
            negative_values = _as_list(city_intents.get(f"negative_{key}"))
            if negative_values:
                negative[key], negative[f"{key}_emotion"] = _merge_list_with_emotion(
                    negative.get(key),
                    negative.get(f"{key}_emotion"),
                    negative_values,
                )
        for key in ("area",):
            values = _as_list(city_intents.get(key))
            if values:
                positive[key] = _merge_profile_list(positive.get(key), values)
            negative_values = _as_list(city_intents.get(f"negative_{key}"))
            if negative_values:
                negative[key] = _merge_profile_list(negative.get(key), negative_values)

    return add_codes_to_profile(profile, batch)


def _response_payload(response: Any) -> dict[str, Any]:
    if not isinstance(response, dict):
        return {}
    data = response.get("data")
    if isinstance(data, dict):
        return data
    return response


def _simulate_tier_counts(summary: Any) -> dict[str, int]:
    if not isinstance(summary, dict):
        return {}
    result: dict[str, int] = {}
    for source_key, label in (
        ("sprintCount", "冲"),
        ("sprintsCount", "冲"),
        ("safeCount", "稳"),
        ("safesCount", "稳"),
        ("protectCount", "保"),
        ("protectsCount", "保"),
    ):
        if source_key in summary:
            result[label] = _as_int(summary.get(source_key))
    total = _as_int(summary.get("totalCount"))
    if total:
        result["total"] = total
    return result


def _simulate_school_diff_items(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    result: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        tier = str(item.get("tier") or "").strip()
        result.append(
            {
                "school_id": str(item.get("schoolId") or item.get("school_id") or "").strip(),
                "school": str(item.get("schoolName") or item.get("school_name") or "").strip(),
                "tier": _SIMULATE_TIER_LABELS.get(tier, tier),
            }
        )
    return result


def _normalize_simulate_plan_diff(response: Any) -> dict[str, Any] | None:
    if not isinstance(response, dict):
        return None
    if response.get("error") or response.get("success") is False or response.get("code") not in (None, 0, "0"):
        return None
    payload = _response_payload(response)
    before = _simulate_tier_counts(payload.get("before"))
    after = _simulate_tier_counts(payload.get("after"))
    promoted = _simulate_school_diff_items(payload.get("promoted"))
    demoted = _simulate_school_diff_items(payload.get("demoted"))
    if not (before or after or promoted or demoted):
        return None
    tier_impact: dict[str, int] = {}
    for tier in ("冲", "稳", "保"):
        if tier in before or tier in after:
            tier_impact[tier] = _as_int(after.get(tier)) - _as_int(before.get(tier))
    return {
        "source": "simulate_plan_diff",
        "available": True,
        "affected_count": len(promoted) + len(demoted),
        "affected_items": demoted[:8],
        "tier_impact": tier_impact,
        "before_tier_counts": before,
        "after_tier_counts": after,
        "promoted": promoted[:8],
        "demoted": demoted[:8],
    }


async def _simulated_plan_impact(
    ctx: RunContext[RequestContext],
    *,
    intent_type: str,
    normalized: dict[str, Any],
) -> dict[str, Any] | None:
    proposed_profile = _proposed_profile_from_intent(
        getattr(ctx.deps, "init_profile", None),
        intent_type=intent_type,
        normalized=normalized,
        batch=getattr(ctx.deps, "batch", None) or "01",
    )
    if proposed_profile is None:
        return None
    response = await internal_client.simulate_plan_diff(
        getattr(ctx.deps, "tenant_id", 1),
        ctx.deps.sessionid,
        proposed_profile,
    )
    return _normalize_simulate_plan_diff(response)


async def _preview_plan_impact(
    ctx: RunContext[RequestContext],
    intent_type: str,
    normalized: dict[str, Any],
    constraint_type: str,
) -> dict[str, Any]:
    try:
        simulated = await _simulated_plan_impact(ctx, intent_type=intent_type, normalized=normalized)
    except Exception as exc:
        local = await _local_plan_impact(ctx, intent_type, normalized, constraint_type)
        return {
            **local,
            "fallback_reason": "simulate_plan_diff_error",
            "simulate_error": str(exc),
        }
    if simulated is not None:
        return simulated
    local = await _local_plan_impact(ctx, intent_type, normalized, constraint_type)
    return {
        **local,
        "fallback_reason": "simulate_plan_diff_unavailable",
    }


def _intent_pending_summary(intent_type: str, normalized: dict[str, Any], constraint_type: str) -> str:
    return _preview_message(intent_type, normalized, constraint_type).replace("我先把这次", "").replace("整理成待确认预览：", "：")


def _constraint_type_from_execution_payload(execution_payload: dict[str, Any]) -> str:
    selected_data = execution_payload.get("selectedData")
    if not isinstance(selected_data, dict):
        selected_data = {}
    raw = (
        execution_payload.get("constraintIntentType")
        or execution_payload.get("constraint_intent_type")
        or selected_data.get("constraintIntentType")
        or selected_data.get("constraint_intent_type")
        or "exclude"
    )
    value = str(raw or "exclude").strip() or "exclude"
    return value if value in {"exclude", "only_keep", "must_have"} else "exclude"


def _apply_to_current_plan_from_execution_payload(execution_payload: dict[str, Any]) -> bool:
    selected_data = execution_payload.get("selectedData")
    if not isinstance(selected_data, dict):
        selected_data = {}
    raw = (
        execution_payload.get("applyToCurrentPlan")
        if "applyToCurrentPlan" in execution_payload
        else execution_payload.get("apply_to_current_plan")
        if "apply_to_current_plan" in execution_payload
        else selected_data.get("applyToCurrentPlan")
        if "applyToCurrentPlan" in selected_data
        else selected_data.get("apply_to_current_plan")
    )
    if raw is None:
        return True
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in {"0", "false", "no", "off", "不", "否", "先不", "暂不"}:
        return False
    return True


def _active_intent_pending_execution_payload(ctx: RunContext[RequestContext]) -> dict[str, Any] | None:
    sandbox = getattr(ctx.deps, "sandbox", None)
    if sandbox is None:
        return None
    pending_file = sandbox.peek("pending.json")
    if not isinstance(pending_file, dict):
        return None
    raw = pending_file.get("raw")
    if not isinstance(raw, dict):
        return None
    if str(raw.get("status") or "").strip() != "active":
        return None
    if str(raw.get("kind") or "").strip() != "intent_change":
        return None
    if str(raw.get("actionFamily") or raw.get("action_family") or "").strip() != "apply_selected_intents":
        return None
    execution_payload = raw.get("executionPayload")
    return execution_payload if isinstance(execution_payload, dict) else None


def _merge_with_intent_pending_payload(
    execution_payload: dict[str, Any] | None,
    *,
    merged: dict[str, Any],
    constraint_type: str,
) -> tuple[dict[str, Any], str, bool]:
    if not isinstance(execution_payload, dict):
        return merged, constraint_type, False
    incoming_aliases = _display_aliases_from_merged(merged)
    existing_merged = execution_payload.get("merged")
    existing_aliases = _display_aliases_from_merged(existing_merged) if isinstance(existing_merged, dict) else {}
    existing_selected = _selected_values_from_pending_payload(execution_payload)
    if not existing_selected:
        return merged, constraint_type, False
    combined = _merge_selected_values(existing_selected + _selected_values_from_merged(merged))
    if not combined:
        return merged, constraint_type, False
    display_aliases = _merge_display_aliases(existing_aliases, incoming_aliases)
    if display_aliases:
        combined["_display_aliases"] = display_aliases
    existing_constraint = _constraint_type_from_execution_payload(execution_payload)
    return (
        combined,
        _combined_constraint_type(existing=existing_constraint, current=constraint_type, merged=combined),
        True,
    )


def _merge_with_active_intent_pending(
    ctx: RunContext[RequestContext],
    *,
    merged: dict[str, Any],
    constraint_type: str,
) -> tuple[dict[str, Any], str, bool]:
    return _merge_with_intent_pending_payload(
        _active_intent_pending_execution_payload(ctx),
        merged=merged,
        constraint_type=constraint_type,
    )


async def _create_intent_pending(
    ctx: RunContext[RequestContext],
    *,
    intent_type: str,
    constraint_type: str,
    normalized: dict[str, Any],
    plan_impact: dict[str, Any],
    apply_to_current_plan: bool = True,
    merged_override: dict[str, Any] | None = None,
    summary_override: str | None = None,
) -> dict[str, Any]:
    merged = merged_override if isinstance(merged_override, dict) and merged_override else _merged_intents_from_normalized(intent_type, normalized)
    selected = _selected_values_from_merged(merged)
    intent_mode = _intent_mode_from_constraint(constraint_type)
    source_version = _as_int((await _plan_summary_data(ctx)).get("version"))
    pending_id = f"pending_{uuid.uuid4().hex}"
    now = _now_iso()
    summary = str(summary_override or "").strip() or _intent_pending_summary(intent_type, normalized, constraint_type)
    pending_state = {
        "type": "pendingConfirmation",
        "pendingId": pending_id,
        "sessionId": str(ctx.deps.sessionid),
        "kind": "intent_change",
        "status": "active",
        "actionFamily": "apply_selected_intents",
        "summary": summary,
        "executionPayload": {
            "toolName": "confirm_pending",
            "selectedData": {
                "selected": selected,
                "intentMode": intent_mode,
                "constraintIntentType": _constraint_intent_type(constraint_type),
                "applyToCurrentPlan": bool(apply_to_current_plan),
                "batch": getattr(ctx.deps, "batch", None) or "01",
            },
            "merged": merged,
            "intentMode": intent_mode,
            "constraintIntentType": _constraint_intent_type(constraint_type),
            "applyToCurrentPlan": bool(apply_to_current_plan),
            "batch": getattr(ctx.deps, "batch", None) or "01",
        },
        "createdAt": now,
        "updatedAt": now,
        "sourceBackendVersion": source_version,
        "planImpact": plan_impact,
    }
    if _dry_run_state_mutations(ctx):
        sandbox = getattr(ctx.deps, "sandbox", None)
        if sandbox is not None:
            sandbox.prime(
                "pending.json",
                {
                    "active": True,
                    "pending_id": pending_id,
                    "kind": "intent_change",
                    "action_family": "apply_selected_intents",
                    "summary": summary,
                    "preview_summary": summary,
                    "execution_payload": pending_state["executionPayload"],
                    "source_backend_version": source_version,
                    "status": "active",
                    "raw": pending_state,
                    "dry_run": True,
                },
                version=source_version,
            )
        return {
            "created": True,
            "dry_run": True,
            "pending_id": pending_id,
            "pending_version": source_version,
            "state": pending_state,
            "backend_response": {},
        }
    if not _PERSIST_PREVIEW_PENDING:
        return {
            "created": False,
            "skipped": "persist_preview_pending_disabled",
            "pending_id": pending_id,
            "pending_version": source_version,
            "state": pending_state,
            "backend_response": {},
        }
    response = await internal_client.save_pending_confirmation(ctx.deps.sessionid, pending_state, version=source_version)
    if not _is_success_response(response):
        return {
            "created": False,
            "pending_id": pending_id,
            "pending_version": source_version,
            "state": pending_state,
            "backend_response": response,
        }
    sandbox = getattr(ctx.deps, "sandbox", None)
    if sandbox is not None:
        sandbox.prime(
            "pending.json",
            {
                "active": True,
                "pending_id": pending_id,
                "kind": "intent_change",
                "action_family": "apply_selected_intents",
                "summary": summary,
                "preview_summary": summary,
                "execution_payload": pending_state["executionPayload"],
                "source_backend_version": source_version,
                "status": "active",
                "raw": pending_state,
            },
            version=source_version,
        )
    return {
        "created": True,
        "pending_id": pending_id,
        "pending_version": source_version,
        "state": pending_state,
        "backend_response": response,
    }


def _compact_text(value: Any) -> str:
    return "".join(str(value or "").split()).lower()


def _item_value(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = item.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _item_major_names(item: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for value in _as_list(_item_value(item, "majorName", "major_name", "major")):
        _append_unique(names, value)
    for value in _as_list(_item_value(item, "majorCategory", "major_category", "category")):
        _append_unique(names, value)
    for value in _as_list(_item_value(item, "majorDiscipline", "major_discipline", "discipline")):
        _append_unique(names, value)
    for major_item in item.get("majorItems") or item.get("major_items") or []:
        if not isinstance(major_item, dict):
            continue
        for value in _as_list(_item_value(major_item, "majorName", "major_name", "name")):
            _append_unique(names, value)
        for value in _as_list(_item_value(major_item, "majorCategory", "major_category", "category")):
            _append_unique(names, value)
        for value in _as_list(_item_value(major_item, "majorDiscipline", "major_discipline", "discipline")):
            _append_unique(names, value)
    return names


def _item_tuition(item: dict[str, Any]) -> int:
    direct = _as_int(_item_value(item, "tuitionPerYear", "tuition_per_year", "tuition", "tuitionFee"))
    if direct > 0:
        return direct
    tag_text = " ".join(_as_list(item.get("majorPlanTags")) + _as_list(item.get("schoolTags")) + _as_list(item.get("tags")))
    digits = "".join(ch if ch.isdigit() else " " for ch in tag_text).split()
    for token in digits:
        value = _as_int(token)
        if value > 0:
            return value
    return 0


def _normalize_tier(value: Any) -> str:
    text = str(value or "").strip()
    if text in {"保底", "兜底", "保险"}:
        return "保"
    if text in {"冲刺"}:
        return "冲"
    return text


def _program_type_values_for_tuition_level(value: Any) -> list[str]:
    result: list[str] = []
    high_tokens = {
        "high",
        "expensive",
        "highfee",
        "hightuition",
        "high_tuition",
        "高",
        "高收费",
        "高学费",
        "学费高",
        "费用高",
        "太贵",
        "贵",
    }
    for item in _as_list(value):
        if _compact_text(item) in high_tokens:
            _append_unique(result, "高收费")
    return result


def _normalize_plan_query_filters(filters: dict[str, Any]) -> tuple[dict[str, Any], int]:
    normalized: dict[str, Any] = {}
    for key, value in (filters or {}).items():
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        normalized_key = {
            "schoolKeywords": "school",
            "schoolKeyword": "school",
            "school_keywords": "school",
            "school_keyword": "school",
            "schoolName": "school",
            "schoolNames": "school",
            "school_name": "school",
            "school_names": "school",
            "schools": "school",
            "collegeName": "school",
            "college_name": "school",
            "majorKeywords": "major",
            "majorKeyword": "major",
            "major_keywords": "major",
            "major_keyword": "major",
            "majorName": "major",
            "majorNames": "major",
            "major_name": "major",
            "major_names": "major",
            "majors": "major",
            "max_tuition_per_year": "tuition_max",
            "tuitionMax": "tuition_max",
            "min_tuition_per_year": "tuition_min",
            "min_tuition": "tuition_min",
            "minTuitionPerYear": "tuition_min",
            "tuitionMin": "tuition_min",
            "tuition_gte": "tuition_min",
            "tuitionGte": "tuition_min",
            "tuition_min": "tuition_min",
            "tuitionLevel": "tuition_level",
            "tuition_level": "tuition_level",
            "feeLevel": "tuition_level",
            "fee_level": "tuition_level",
            "includeFields": "include_fields",
            "fields": "include_fields",
            "projection_fields": "include_fields",
            "sortField": "sort_field",
            "sortOrder": "sort_order",
            "order": "sort_order",
            "position_slice": "slice",
            "positionGroup": "position_group",
            "unitPosition": "position_group",
            "unit_position": "position_group",
            "orderedPosition": "position_group",
            "ordered_position": "position_group",
            "pageSize": "limit",
            "page_size": "limit",
        }.get(normalized_key, normalized_key)
        normalized_key = normalize_attribute_filter_key(normalized_key)
        if normalized_key == "tier":
            values = [_normalize_tier(item) for item in normalize_attribute_filter_values("tier", _as_list(value))]
            normalized["tier"] = [item for item in values if item]
        elif normalized_key in {"school_nature", "school", "major", "province"}:
            normalized[normalized_key] = normalize_attribute_filter_values(normalized_key, _as_list(value))
        elif normalized_key == "tuition_max":
            max_value = _as_int(value)
            if max_value > 0:
                normalized[normalized_key] = max_value
        elif normalized_key == "tuition_min":
            min_value = _as_int(value)
            if min_value > 0:
                normalized[normalized_key] = min_value
        elif normalized_key == "tuition_level":
            program_type_values = _program_type_values_for_tuition_level(value)
            if program_type_values:
                merged_values = _as_list(normalized.get("program_type"))
                for item in program_type_values:
                    _append_unique(merged_values, item)
                normalized["program_type"] = merged_values
            else:
                normalized[normalized_key] = value
        elif normalized_key == "limit":
            normalized[normalized_key] = _as_int(value)
        elif normalized_key == "include_fields":
            fields = _normalize_plan_query_fields(value)
            if fields:
                normalized[normalized_key] = fields
        elif normalized_key == "slice":
            slice_mode = _normalize_plan_query_slice(value)
            if slice_mode:
                normalized[normalized_key] = slice_mode
        elif normalized_key == "sort":
            if isinstance(value, dict):
                sort_field = _normalize_plan_query_sort_field(value.get("field") or value.get("sort_field"))
                sort_order = _normalize_plan_query_sort_order(value.get("order") or value.get("sort_order"))
                if sort_field:
                    normalized["sort_field"] = sort_field
                if sort_order:
                    normalized["sort_order"] = sort_order
            else:
                sort_field = _normalize_plan_query_sort_field(value)
                if sort_field:
                    normalized["sort_field"] = sort_field
        elif normalized_key == "sort_field":
            sort_field = _normalize_plan_query_sort_field(value)
            if sort_field:
                normalized[normalized_key] = sort_field
        elif normalized_key == "sort_order":
            sort_order = _normalize_plan_query_sort_order(value)
            if sort_order:
                normalized[normalized_key] = sort_order
        elif normalized_key in ATTRIBUTE_REGISTRY:
            values = normalize_attribute_filter_values(normalized_key, _as_list(value))
            if values:
                normalized[normalized_key] = values
        else:
            normalized[normalized_key] = value
    limit = normalized.pop("limit", _DEFAULT_PLAN_QUERY_LIMIT)
    limit = max(1, min(_as_int(limit, _DEFAULT_PLAN_QUERY_LIMIT), 50))
    return normalized, limit


def _normalize_plan_query_fields(value: Any) -> list[str]:
    aliases = {
        "admission_probability": "admission_probability",
        "admission_prob": "admission_probability",
        "admission_ratio": "admission_probability",
        "admissionRatio": "admission_probability",
        "录取率": "admission_probability",
        "录取概率": "admission_probability",
        "school": "school",
        "学校": "school",
        "院校": "school",
        "major": "major",
        "专业": "major",
        "tuition": "tuition",
        "tuition_per_year": "tuition",
        "学费": "tuition",
        "position": "position",
        "位置": "position",
        "tier": "tier",
        "梯度": "tier",
    }
    fields: list[str] = []
    for item in _as_list(value):
        normalized = aliases.get(str(item or "").strip())
        if normalized and normalized not in fields:
            fields.append(normalized)
    return fields


def _normalize_plan_query_slice(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"tail", "last", "end", "末尾", "最后", "后几个", "后几条"}:
        return "tail"
    if text in {"head", "first", "top", "前面", "前几个", "前几条"}:
        return "head"
    return ""


def _normalize_plan_query_sort_field(value: Any) -> str:
    text = str(value or "").strip()
    aliases = {
        "position": "position",
        "order": "position",
        "rank": "position",
        "位置": "position",
        "顺序": "position",
        "admission_probability": "admission_probability",
        "admission_ratio": "admission_probability",
        "admissionRatio": "admission_probability",
        "admissionProbability": "admission_probability",
        "录取率": "admission_probability",
        "录取概率": "admission_probability",
        "tuition": "tuition",
        "tuition_per_year": "tuition",
        "学费": "tuition",
    }
    return aliases.get(text, "")


def _normalize_plan_action_sort_field(value: Any) -> str:
    return _PLAN_SORT_FIELDS.get(str(value or "").strip(), "")


def _plan_action_sort_field_label(value: Any) -> str:
    text = str(value or "").strip()
    return _PLAN_SORT_FIELD_LABELS.get(text, text)


def _normalize_plan_query_sort_order(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"desc", "descending", "high_to_low", "highest", "max", "降序", "从高到低"}:
        return "desc"
    if text in {"asc", "ascending", "low_to_high", "lowest", "min", "升序", "从低到高"}:
        return "asc"
    return ""


def _normalize_plan_selector_sort(value: Any) -> str:
    text = str(value or "").strip()
    return _normalize_plan_query_sort_field(text)


def _normalize_plan_selector_rank(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"max", "highest", "desc", "descending", "high_to_low", "最高", "最大", "最多", "从高到低"}:
        return "max"
    if text in {"min", "lowest", "asc", "ascending", "low_to_high", "最低", "最小", "最少", "从低到高"}:
        return "min"
    if text in {"last", "tail", "最后", "最后一个", "末位", "末尾"}:
        return "last"
    return text


def _extract_plan_query_controls(filters: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    query_filters = dict(filters or {})
    controls: dict[str, Any] = {}
    for key in _PLAN_QUERY_CONTROL_KEYS:
        value = query_filters.pop(key, None)
        if value not in (None, "", []):
            controls[key] = value
    return query_filters, controls


def _matches_any_text(target_values: list[str], query_values: list[str]) -> bool:
    if not query_values:
        return True
    targets = [_compact_text(value) for value in target_values if _compact_text(value)]
    queries = [_compact_text(value) for value in query_values if _compact_text(value)]
    if not queries:
        return True
    return any(query in target or target in query for query in queries for target in targets)


def _matches_school_abbreviation(school_name: str, query: str) -> bool:
    compact_school = _compact_text(school_name)
    compact_query = _compact_text(query)
    if not compact_school or not compact_query:
        return False
    if not (2 <= len(compact_query) <= 4):
        return False
    if len(compact_query) >= len(compact_school):
        return False
    if not all("\u4e00" <= ch <= "\u9fff" for ch in compact_query):
        return False
    if compact_school[0] != compact_query[0]:
        return False
    position = 0
    for char in compact_query:
        index = compact_school.find(char, position)
        if index < 0:
            return False
        position = index + 1
    return True


def _resolve_school_filter_values(values: list[str], *, batch: str | None) -> list[str]:
    resolved: list[str] = []
    for value in values:
        result = resolve_school_entity(value, batch)
        if result.best is not None and not result.ambiguous:
            _append_unique(resolved, result.best.canonical_name)
        _append_unique(resolved, value)
    return resolved


def _resolve_major_filter_values(values: list[str], *, batch: str | None) -> list[str]:
    resolved: list[str] = []
    for value in values:
        result = resolve_major_entity(value, batch)
        if result.best is not None and not result.ambiguous:
            _append_unique(resolved, result.best.canonical_name)
        _append_unique(resolved, value)
    return resolved


def _matches_plan_item(item: dict[str, Any], filters: dict[str, Any], *, batch: str | None) -> bool:
    school_nature = filters.get("school_nature") or []
    if school_nature:
        actual = str(_item_value(item, "schoolNature", "school_nature", "schoolType", "school_type") or "").strip()
        if actual not in school_nature:
            return False

    tiers = filters.get("tier") or []
    if tiers:
        actual_tier = _normalize_tier(_item_value(item, "tier", "riskTier", "risk_tier"))
        if actual_tier not in tiers:
            return False

    schools = filters.get("school") or []
    if schools:
        school_values = _resolve_school_filter_values(schools, batch=batch)
        actual_school = str(_item_value(item, "schoolName", "school_name", "collegeName") or "").strip()
        if not _matches_any_text([actual_school], school_values) and not any(
            _matches_school_abbreviation(actual_school, school) for school in schools
        ):
            return False

    majors = filters.get("major") or []
    if majors:
        major_values = _resolve_major_filter_values(majors, batch=batch)
        if not _matches_any_text(_item_major_names(item), major_values):
            return False

    provinces = filters.get("province") or []
    if provinces:
        actual_province = str(_item_value(item, "provinceName", "province_name", "province") or "").strip()
        if not _matches_any_text([actual_province], provinces):
            return False

    tuition_max = _as_int(filters.get("tuition_max"))
    if tuition_max > 0:
        tuition = _item_tuition(item)
        if tuition <= 0 or tuition > tuition_max:
            return False

    tuition_min = _as_int(filters.get("tuition_min"))
    if tuition_min > 0:
        tuition = _item_tuition(item)
        if tuition <= 0 or tuition < tuition_min:
            return False

    handled = {"school_nature", "tier", "school", "major", "province", "tuition_max", "tuition_min"}
    for key, value in filters.items():
        if key in handled:
            continue
        if key not in ATTRIBUTE_REGISTRY:
            return False
        if not match_attribute_item(key, item, _as_list(value)):
            return False

    return True


def _plan_item_brief(item: dict[str, Any]) -> dict[str, Any]:
    majors = _item_major_names(item)
    return {
        "position": _as_int(_item_value(item, "position", "rank", "order")),
        "school": str(_item_value(item, "schoolName", "school_name", "collegeName") or "").strip(),
        "major": majors[0] if majors else "",
        "tier": _normalize_tier(_item_value(item, "tier", "riskTier", "risk_tier")),
        "province": str(_item_value(item, "provinceName", "province_name", "province") or "").strip(),
        "school_nature": str(_item_value(item, "schoolNature", "school_nature", "schoolType", "school_type") or "").strip(),
        "tuition_per_year": _item_tuition(item),
        "admission_ratio": _as_int(_item_value(item, "admissionRatio", "admission_ratio", "admissionProbability")),
    }


def _plan_item_snippet(item: dict[str, Any], *, include_fields: list[str] | None = None) -> str:
    brief = _plan_item_brief(item)
    name = "-".join(part for part in [brief.get("school"), brief.get("major")] if part)
    if not name:
        name = "未命名志愿"
    requested_fields = set(include_fields or [])
    suffixes: list[str] = []
    if brief.get("tier"):
        suffixes.append(str(brief["tier"]))
    if brief.get("position"):
        suffixes.append(f"第{brief['position']}位")
    if "admission_probability" in requested_fields:
        ratio = _as_int(brief.get("admission_ratio"))
        suffixes.append(f"录取率{ratio}%" if ratio > 0 else "录取率未知")
    if brief.get("school_nature"):
        suffixes.append(str(brief["school_nature"]))
    if brief.get("tuition_per_year"):
        suffixes.append(f"{brief['tuition_per_year']}元/年")
    return f"{name}（{'，'.join(suffixes)}）" if suffixes else name


def _describe_filters(filters: dict[str, Any]) -> str:
    if not filters:
        return "全部方案"
    labels = {
        "tier": "梯度",
        "school": "院校",
        "major": "专业",
        "tuition_max": "学费不高于",
        "tuition_min": "学费不少于",
    }
    parts: list[str] = []
    for key, value in filters.items():
        if key in _PLAN_QUERY_CONTROL_KEYS:
            continue
        label = labels.get(key, attribute_label(key))
        if key == "tuition_max" or key == "tuition_min":
            parts.append(f"{label}{value}元/年")
        elif isinstance(value, list):
            parts.append(f"{label}={ '、'.join(value) }")
        else:
            parts.append(f"{label}={value}")
    return "；".join(parts)


def _plan_query_sort_value(item: dict[str, Any], sort_field: str) -> Any:
    brief = _plan_item_brief(item)
    if sort_field == "admission_probability":
        return _as_int(brief.get("admission_ratio"))
    if sort_field == "tuition":
        return _as_int(brief.get("tuition_per_year"))
    return _as_int(brief.get("position"))


def _select_plan_query_examples(
    items: list[dict[str, Any]],
    *,
    limit: int,
    controls: dict[str, Any],
) -> list[dict[str, Any]]:
    ordered = list(items)
    sort_field = str(controls.get("sort_field") or "").strip()
    if sort_field:
        reverse = str(controls.get("sort_order") or "").strip() == "desc"
        ordered.sort(key=lambda item: _plan_query_sort_value(item, sort_field), reverse=reverse)
    slice_mode = str(controls.get("slice") or "head").strip()
    if slice_mode == "tail":
        return ordered[-limit:]
    return ordered[:limit]


def _tier_display_label(tiers: list[str]) -> str:
    if not tiers:
        return ""
    if len(tiers) == 1:
        return {"冲": "冲档", "稳": "稳档", "保": "保底"}.get(tiers[0], tiers[0])
    return "、".join({"冲": "冲档", "稳": "稳档", "保": "保底"}.get(tier, tier) for tier in tiers)


def _plan_query_display_scope(filters: dict[str, Any], controls: dict[str, Any], count: int) -> str:
    tiers = [str(item) for item in filters.get("tier") or [] if str(item or "").strip()]
    tier_label = _tier_display_label(tiers)
    slice_mode = str(controls.get("slice") or "head").strip()
    if slice_mode == "tail":
        return f"{tier_label}末尾{count}条" if tier_label else f"末尾{count}条"
    return f"前{count}条"


def _query_requests_school_summary(raw_user_text: str, filters: dict[str, Any]) -> bool:
    text = _compact_text(raw_user_text)
    if not text:
        return False
    if not any(marker in text for marker in ("学校", "院校")):
        return False
    return bool(filters.get("tier")) and not filters.get("school") and not filters.get("major")


def _post_query_instruction(raw_user_text: str) -> dict[str, str]:
    return {
        "current_user_text": str(raw_user_text or "").strip(),
        "post_query_instruction": (
            "只读查询已经完成。请重新检查 current_user_text：如果本轮原话同时表达了替换、换成、移出、去掉、"
            "删除、排序、重排、重新调整、锁定、固定位置等当前方案动作，继续调用 preview_plan_action 生成待确认预览；"
            "如果只是查询事实，再直接回答查询结果。不要把委婉的“能不能换成/可不可以换成/帮我换成”"
            "回复成“是否需要我预览”。"
        ),
    }


def _school_summary_items(items: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in _sort_plan_items(items):
        school = str(_item_value(item, "schoolName", "school_name", "collegeName") or "").strip()
        if not school:
            continue
        if school not in summary:
            order.append(school)
            summary[school] = {
                "school": school,
                "positions": [],
                "tier": _normalize_tier(_item_value(item, "tier", "riskTier", "risk_tier")),
                "province": str(_item_value(item, "provinceName", "province_name", "province") or "").strip(),
                "school_nature": str(
                    _item_value(item, "schoolNature", "school_nature", "schoolType", "school_type") or ""
                ).strip(),
                "tuition_min": 0,
                "tuition_max": 0,
                "admission_ratio_max": 0,
            }
        entry = summary[school]
        position = _item_position(item)
        if position > 0 and position not in entry["positions"]:
            entry["positions"].append(position)
        tuition = _item_tuition(item)
        if tuition > 0:
            entry["tuition_min"] = tuition if not entry["tuition_min"] else min(entry["tuition_min"], tuition)
            entry["tuition_max"] = max(entry["tuition_max"], tuition)
        admission_ratio = _as_int(_item_value(item, "admissionRatio", "admission_ratio", "admissionProbability"))
        entry["admission_ratio_max"] = max(entry["admission_ratio_max"], admission_ratio)
    return [summary[school] for school in order[:limit]]


def _school_summary_snippet(item: dict[str, Any]) -> str:
    positions = [int(value) for value in item.get("positions") or [] if _as_int(value) > 0]
    position_text = ""
    if positions:
        position_text = f"第{min(positions)}-{max(positions)}位" if len(positions) > 1 else f"第{positions[0]}位"
    suffixes = [value for value in (position_text, item.get("school_nature")) if value]
    admission_ratio = _as_int(item.get("admission_ratio_max"))
    if admission_ratio > 0:
        suffixes.append(f"最高录取率{admission_ratio}%")
    tuition_min = _as_int(item.get("tuition_min"))
    tuition_max = _as_int(item.get("tuition_max"))
    if tuition_min and tuition_max and tuition_min != tuition_max:
        suffixes.append(f"学费{tuition_min}-{tuition_max}元/年")
    elif tuition_max:
        suffixes.append(f"学费{tuition_max}元/年")
    return f"{item.get('school')}（{'，'.join(suffixes)}）" if suffixes else str(item.get("school") or "")


def _plan_item_group_key(item: dict[str, Any], index: int) -> str:
    for value in (
        _item_unit_id(item),
        item.get("planSchoolDataId"),
        item.get("plan_school_data_id"),
        item.get("groupId"),
        item.get("group_id"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    position = _item_position(item)
    if position > 0:
        return f"position:{position}"
    volunteer_id = _item_volunteer_id(item)
    if "_" in volunteer_id:
        return f"volunteer-prefix:{volunteer_id.rsplit('_', 1)[0]}"
    school = str(_item_value(item, "schoolName", "school_name", "collegeName") or "").strip()
    tier = _normalize_tier(_item_value(item, "tier", "riskTier", "risk_tier"))
    if school or tier:
        return f"text:{school}:{tier}:{index}"
    return f"row:{index}"


def _unique_plan_item_group_count(items: list[dict[str, Any]]) -> int:
    return len({_plan_item_group_key(item, index) for index, item in enumerate(items)})


def _plan_query_count_metrics(
    *,
    plan_items: list[dict[str, Any]],
    matched_items: list[dict[str, Any]],
    declared_total: int,
) -> dict[str, Any]:
    detail_total = len(matched_items)
    total_detail = len(plan_items)
    matched_plan_total = _unique_plan_item_group_count(matched_items)
    total_plan_items = declared_total if declared_total > 0 else _unique_plan_item_group_count(plan_items)
    detail_granularity = bool(
        (total_plan_items > 0 and total_detail > total_plan_items)
        or (matched_plan_total > 0 and detail_total > matched_plan_total)
    )
    return {
        "matched_total": matched_plan_total,
        "matched_plan_item_total": matched_plan_total,
        "matched_detail_total": detail_total,
        "plan_item_total": total_plan_items,
        "plan_detail_total": total_detail,
        "detail_granularity": detail_granularity,
    }


def _items_from_plan_file(data: dict[str, Any]) -> list[dict[str, Any]]:
    items = data.get("items")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    return []


def _candidate_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    items = data.get("items")
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


_REPLACEMENT_MARKER_VALUES: dict[str, tuple[str, ...]] = {
    "admission_limit": ("限报", "限报条件", "admission_limit"),
    "special_enrollment": ("特殊招生", "特殊类型招生", "special_enrollment"),
}


def _item_structured_marker_values(item: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("reasonCodes", "reason_codes", "majorPlanTags", "major_plan_tags", "majorTags", "major_tags", "schoolTags", "school_tags", "tags"):
        for value in _as_list(item.get(key)):
            text = str(value or "").strip()
            if text:
                values.append(text)
    return values


def _item_has_structured_marker(item: dict[str, Any], marker_values: tuple[str, ...]) -> bool:
    actual = {_compact_text(value) for value in _item_structured_marker_values(item)}
    expected = {_compact_text(value) for value in marker_values if value}
    return bool(actual & expected)


def _replacement_marker_matches(item: dict[str, Any], marker: str) -> bool:
    normalized = str(marker or "").strip()
    if normalized == "high_tuition":
        return _item_tuition(item) > 20000 or match_attribute_item("program_type", item, ["高收费"])
    if normalized == "cooperative":
        return match_attribute_item("program_type", item, ["中外合作"])
    return _item_has_structured_marker(item, _REPLACEMENT_MARKER_VALUES.get(normalized, (normalized,)))


def _replacement_spec_base(old_items: list[dict[str, Any]]) -> ReplacementSpec:
    old_tiers: list[str] = []
    old_provinces: list[str] = []
    old_tuitions: list[int] = []
    old_school_ranks: list[int] = []
    old_admission_ratios: list[int] = []
    for item in old_items:
        tier = _normalize_tier(_item_value(item, "tier", "riskTier", "risk_tier"))
        if tier:
            _append_unique(old_tiers, tier)
        province = str(_item_value(item, "provinceName", "province_name", "province") or "").strip()
        if province:
            _append_unique(old_provinces, province)
        tuition = _item_tuition(item)
        if tuition > 0:
            old_tuitions.append(tuition)
        school_rank = _as_int(_item_value(item, "schoolRank", "school_rank"))
        if school_rank > 0:
            old_school_ranks.append(school_rank)
        admission_ratio = _admission_ratio(item)
        if admission_ratio > 0:
            old_admission_ratios.append(admission_ratio)
    spec: ReplacementSpec = {
        "source": "",
        "keep_dims": ["tier"],
        "improve_dim": "",
        "improve_dims": [],
        "exclude_markers": [],
        "constraint_carryover": True,
        "old_tiers": old_tiers,
        "old_provinces": old_provinces,
        "major_keywords": _replacement_major_keywords_from_old_items(old_items),
    }
    if old_tuitions:
        spec["old_min_tuition"] = min(old_tuitions)
        spec["old_max_tuition"] = max(old_tuitions)
    if old_school_ranks:
        spec["old_best_school_rank"] = min(old_school_ranks)
    if old_admission_ratios:
        spec["old_min_admission_ratio"] = min(old_admission_ratios)
    return spec


def _add_replacement_improve_dim(spec: ReplacementSpec, dim: str) -> None:
    value = str(dim or "").strip()
    if not value:
        return
    dims = spec.setdefault("improve_dims", [])
    _append_unique(dims, value)
    if not spec.get("improve_dim"):
        spec["improve_dim"] = value


def _add_replacement_marker(spec: ReplacementSpec, marker: str) -> None:
    value = str(marker or "").strip()
    value = {
        "cooperative_program": "cooperative",
        "cooperativeProgram": "cooperative",
        "high_fee": "high_tuition",
        "highFee": "high_tuition",
        "highTuition": "high_tuition",
    }.get(value, value)
    if value:
        _append_unique(spec.setdefault("exclude_markers", []), value)


def _merge_replacement_spec(spec: ReplacementSpec, source_spec: ReplacementSpec) -> None:
    if not source_spec:
        return
    if source_spec.get("source") and not spec.get("source"):
        spec["source"] = str(source_spec.get("source") or "")
    for dim in source_spec.get("keep_dims") or []:
        _append_unique(spec.setdefault("keep_dims", []), dim)
    for dim in source_spec.get("improve_dims") or []:
        _add_replacement_improve_dim(spec, dim)
    if source_spec.get("improve_dim"):
        _add_replacement_improve_dim(spec, str(source_spec.get("improve_dim") or ""))
    for marker in source_spec.get("exclude_markers") or []:
        _add_replacement_marker(spec, marker)
    for keyword in source_spec.get("major_keywords") or []:
        _append_unique(spec.setdefault("major_keywords", []), keyword)
    if "constraint_carryover" in source_spec:
        spec["constraint_carryover"] = bool(source_spec.get("constraint_carryover"))


def _replacement_spec_from_review_issue(review_issue_code: Any) -> ReplacementSpec:
    code = _canonical_review_issue_code(review_issue_code)
    spec: ReplacementSpec = {"source": f"review_issue:{code}" if code else ""}
    if code == "high_tuition":
        spec["improve_dims"] = ["tuition_decrease"]
        spec["exclude_markers"] = ["high_tuition", "cooperative"]
    elif code == "cooperative_program":
        spec["improve_dims"] = ["tuition_decrease"]
        spec["exclude_markers"] = ["cooperative"]
    elif code == "admission_limit":
        spec["exclude_markers"] = ["admission_limit"]
    elif code == "special_enrollment":
        spec["exclude_markers"] = ["special_enrollment"]
    elif code in {"probability_inversion", "probability_gap", "safety_guard", "tier_gap", "low_safety"}:
        spec["improve_dims"] = ["admission_ratio_increase"]
    return spec


def _replacement_spec_from_filters(filters: dict[str, Any] | None) -> ReplacementSpec:
    normalized_filters, _ = _normalize_plan_query_filters(filters if isinstance(filters, dict) else {})
    spec: ReplacementSpec = {"source": "filters" if normalized_filters else ""}
    if _as_int(normalized_filters.get("tuition_min")) > 0:
        spec["improve_dims"] = ["tuition_decrease"]
        spec["exclude_markers"] = ["high_tuition", "cooperative"]
    program_types = {_compact_text(value) for value in _as_list(normalized_filters.get("program_type"))}
    if "高收费" in program_types:
        _add_replacement_improve_dim(spec, "tuition_decrease")
        _add_replacement_marker(spec, "high_tuition")
        _add_replacement_marker(spec, "cooperative")
    if "中外合作" in program_types:
        _add_replacement_improve_dim(spec, "tuition_decrease")
        _add_replacement_marker(spec, "cooperative")
    return spec


def _replacement_spec_from_structured_input(value: Any) -> ReplacementSpec:
    if not isinstance(value, dict):
        return {}
    spec: ReplacementSpec = {"source": "replacement_spec"}
    for dim in _as_list(value.get("improve_dims") or value.get("improveDims")):
        _add_replacement_improve_dim(spec, str(dim or ""))
    if value.get("improve_dim") or value.get("improveDim"):
        _add_replacement_improve_dim(spec, str(value.get("improve_dim") or value.get("improveDim") or ""))
    for marker in _as_list(value.get("exclude_markers") or value.get("excludeMarkers")):
        _add_replacement_marker(spec, str(marker or ""))
    for dim in _as_list(value.get("keep_dims") or value.get("keepDims")):
        _append_unique(spec.setdefault("keep_dims", []), str(dim or "").strip())
    for keyword in _as_list(value.get("major_keywords") or value.get("majorKeywords")):
        keyword_text = str(keyword or "").strip()
        if keyword_text:
            _append_unique(spec.setdefault("major_keywords", []), keyword_text)
    if "constraint_carryover" in value or "constraintCarryover" in value:
        spec["constraint_carryover"] = bool(value.get("constraint_carryover", value.get("constraintCarryover")))
    return spec


def _replacement_spec_from_old_items(old_items: list[dict[str, Any]]) -> ReplacementSpec:
    spec: ReplacementSpec = {"source": "old_item_attributes" if old_items else ""}
    for item in old_items:
        if _replacement_marker_matches(item, "high_tuition"):
            _add_replacement_improve_dim(spec, "tuition_decrease")
            _add_replacement_marker(spec, "high_tuition")
        if _replacement_marker_matches(item, "cooperative"):
            _add_replacement_improve_dim(spec, "tuition_decrease")
            _add_replacement_marker(spec, "cooperative")
        if _replacement_marker_matches(item, "admission_limit"):
            _add_replacement_marker(spec, "admission_limit")
        if _replacement_marker_matches(item, "special_enrollment"):
            _add_replacement_marker(spec, "special_enrollment")
    return spec


def _replacement_major_keywords_from_old_items(old_items: list[dict[str, Any]]) -> list[str]:
    unit_ids = {_item_unit_id(item) for item in old_items if _item_unit_id(item)}
    if len(unit_ids) != 1:
        return []
    item = old_items[0]
    values = [
        _item_value(item, "majorCategory", "major_category"),
        _item_value(item, "majorDiscipline", "major_discipline"),
    ]
    values.extend(_item_major_names(item))
    keywords: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        text = re.split(r"[(（]", text, maxsplit=1)[0].strip()
        if text:
            _append_unique(keywords, text)
        if "建筑" in text:
            _append_unique(keywords, "建筑")
    return keywords[:2]


def _build_replacement_spec(
    *,
    review_issue_code: Any,
    explicit_spec: Any,
    filters: dict[str, Any] | None,
    old_items: list[dict[str, Any]],
) -> ReplacementSpec:
    spec = _replacement_spec_base(old_items)
    for source_spec in (
        _replacement_spec_from_review_issue(review_issue_code),
        _replacement_spec_from_structured_input(explicit_spec),
        _replacement_spec_from_filters(filters),
        _replacement_spec_from_old_items(old_items),
    ):
        _merge_replacement_spec(spec, source_spec)
    if not spec.get("source") and (spec.get("improve_dims") or spec.get("exclude_markers")):
        spec["source"] = "derived"
    return spec


def _replacement_spec_is_actionable(spec: ReplacementSpec) -> bool:
    return bool(spec.get("improve_dims") or spec.get("exclude_markers"))


def _replacement_auto_select_reason(spec: ReplacementSpec) -> str:
    markers = set(spec.get("exclude_markers") or [])
    dims = set(spec.get("improve_dims") or [])
    if "high_tuition" in markers or "tuition_decrease" in dims:
        return "high_tuition"
    if "cooperative" in markers:
        return "cooperative_program"
    if "admission_limit" in markers:
        return "admission_limit"
    if "special_enrollment" in markers:
        return "special_enrollment"
    if "admission_ratio_increase" in dims:
        return "admission_ratio"
    if "school_rank_improve" in dims:
        return "school_rank"
    return ""


def _replacement_spec_direction_summary(spec: ReplacementSpec) -> str:
    markers = set(spec.get("exclude_markers") or [])
    dims = set(spec.get("improve_dims") or [])
    parts: list[str] = []
    if "tuition_decrease" in dims or "high_tuition" in markers:
        parts.append("更便宜")
    if "cooperative" in markers:
        parts.append("非中外合作")
    if "school_rank_improve" in dims:
        parts.append("院校层次更高")
    if "admission_ratio_increase" in dims:
        parts.append("录取把握更高")
    if "province_match" in dims:
        parts.append("同省或更近")
    return "、".join(parts)


def _replacement_candidate_query(spec: ReplacementSpec, wanted: int) -> dict[str, Any]:
    dims = set(spec.get("improve_dims") or [])
    markers = set(spec.get("exclude_markers") or [])
    if "tuition_decrease" in dims:
        sort_field = "tuitionPerYear"
        sort_order = "asc"
    elif "school_rank_improve" in dims:
        sort_field = "schoolRank"
        sort_order = "asc"
    elif "admission_ratio_increase" in dims:
        sort_field = "admissionRatio"
        sort_order = "desc"
    else:
        sort_field = "finalScore"
        sort_order = "desc"
    query: dict[str, Any] = {
        "page_size": max(50, min(200, max(1, wanted) * 20)),
        "sort_field": sort_field,
        "sort_order": sort_order,
    }
    if spec.get("old_tiers"):
        query["tiers"] = spec.get("old_tiers")
    if "province_match" in dims and spec.get("old_provinces"):
        query["province_names"] = spec.get("old_provinces")
    if spec.get("major_keywords"):
        query["major_keywords"] = spec.get("major_keywords")
    negative_major_tags: list[str] = []
    negative_school_tags: list[str] = []
    if "high_tuition" in markers:
        negative_major_tags.extend(["高收费", "高学费"])
        negative_school_tags.extend(["高收费", "高学费"])
    if "cooperative" in markers:
        negative_major_tags.extend(["中外合作", "中外合作办学"])
        negative_school_tags.extend(["中外合作"])
    if "admission_limit" in markers:
        negative_major_tags.extend(["限报", "限报条件"])
    if negative_major_tags:
        query["negative_major_tags"] = negative_major_tags
    if negative_school_tags:
        query["negative_school_tags"] = negative_school_tags
    if "tuition_decrease" in dims and _as_int(spec.get("old_min_tuition")) > 0:
        query["tuition_max"] = max(0, _as_int(spec.get("old_min_tuition")) - 1)
    return query


def _candidate_matches_replacement_major_keywords(candidate: dict[str, Any], keywords: list[str]) -> bool:
    if not keywords:
        return True
    values = _item_major_names(candidate)
    values.extend(
        str(_item_value(candidate, key) or "")
        for key in ("majorCategory", "major_category", "majorDiscipline", "major_discipline")
    )
    return _matches_any_text(values, keywords)


def _constraint_scope_matches_candidate(candidate: dict[str, Any], scope: Any, *, domain: str) -> bool:
    text = str(scope or "").strip()
    if not text:
        return False
    if ":" in text:
        label, value = [part.strip() for part in text.split(":", 1)]
        key_by_label = {
            "院校性质": "school_nature",
            "办学性质": "school_nature",
            "招生类型": "program_type",
            "院校分类": "school_category",
            "院校层次": "school_level",
            "院校标签": "school_tag",
            "专业标签": "major_tag",
        }
        key = key_by_label.get(label)
        if key:
            return match_attribute_item(key, candidate, [value])
    if domain == "region":
        province = str(_item_value(candidate, "provinceName", "province_name", "province") or "").strip()
        if _matches_any_text([province], [text]):
            return True
        return _region_area_contains_province(text, province)
    if domain == "school":
        values = [
            str(_item_value(candidate, "schoolName", "school_name", "collegeName") or ""),
            str(_item_value(candidate, "schoolNature", "school_nature") or ""),
            str(_item_value(candidate, "schoolCategory", "school_category") or ""),
            str(_item_value(candidate, "schoolLevel", "school_level") or ""),
        ]
        return _matches_any_text(values, [text])
    values = _item_major_names(candidate)
    values.extend(
        str(_item_value(candidate, key) or "")
        for key in ("majorCategory", "major_category", "majorDiscipline", "major_discipline")
    )
    return _matches_any_text(values, [text])


def _candidate_satisfies_confirmed_constraints(candidate: dict[str, Any], constraints_file: dict[str, Any]) -> bool:
    constraints = constraints_file.get("constraints") if isinstance(constraints_file, dict) else {}
    hard = constraints.get("hardConstraints") if isinstance(constraints, dict) else {}
    hard = hard if isinstance(hard, dict) else {}
    checks = (
        ("mustExcludeRegions", "region", False),
        ("mustExcludeSchools", "school", False),
        ("mustExcludeMajors", "major", False),
    )
    for key, domain, _ in checks:
        if any(_constraint_scope_matches_candidate(candidate, value, domain=domain) for value in _as_list(hard.get(key))):
            return False
    include_checks = (
        ("mustIncludeRegions", "region"),
        ("mustIncludeSchools", "school"),
        ("mustIncludeMajors", "major"),
    )
    for key, domain in include_checks:
        values = _as_list(hard.get(key))
        if values and not any(_constraint_scope_matches_candidate(candidate, value, domain=domain) for value in values):
            return False
    return True


def _candidate_replacement_score(candidate: dict[str, Any], old_items: list[dict[str, Any]], spec: ReplacementSpec) -> tuple[int, int, int, int, str]:
    old_tiers = set(spec.get("old_tiers") or [])
    old_provinces = set(spec.get("old_provinces") or [])
    old_min_tuition = _as_int(spec.get("old_min_tuition"))
    old_best_school_rank = _as_int(spec.get("old_best_school_rank"))
    old_min_admission_ratio = _as_int(spec.get("old_min_admission_ratio"))
    dims = set(spec.get("improve_dims") or [])
    markers = set(spec.get("exclude_markers") or [])
    score = 0
    candidate_tier = _normalize_tier(_item_value(candidate, "tier", "riskTier", "risk_tier"))
    if candidate_tier and candidate_tier in old_tiers:
        score += 30
    candidate_province = str(_item_value(candidate, "provinceName", "province_name", "province") or "").strip()
    if candidate_province and candidate_province in old_provinces:
        score += 10

    tuition = _item_tuition(candidate)
    if "tuition_decrease" in dims:
        if tuition > 0 and (old_min_tuition <= 0 or tuition < old_min_tuition):
            score += 40
    school_rank = _as_int(_item_value(candidate, "schoolRank", "school_rank"))
    if "school_rank_improve" in dims and school_rank > 0 and (old_best_school_rank <= 0 or school_rank < old_best_school_rank):
        score += 30
    admission_ratio = _admission_ratio(candidate)
    if "admission_ratio_increase" in dims and admission_ratio > old_min_admission_ratio:
        score += 30
    for marker in markers:
        if _replacement_marker_matches(candidate, marker):
            score -= 80

    return score, admission_ratio, -tuition if tuition > 0 else 0, -school_rank if school_rank > 0 else 0, _item_volunteer_id(candidate)


def _replacement_candidate_block_reason(
    candidate: dict[str, Any],
    *,
    old_unit_ids: set[str],
    spec: ReplacementSpec,
    constraints_file: dict[str, Any],
) -> str:
    candidate_unit_id = _item_unit_id(candidate)
    if candidate_unit_id and candidate_unit_id in old_unit_ids:
        return "same_old_unit"
    candidate_tier = _normalize_tier(_item_value(candidate, "tier", "riskTier", "risk_tier"))
    old_tiers = set(spec.get("old_tiers") or [])
    if old_tiers and candidate_tier not in old_tiers:
        return "tier_mismatch_candidate"
    if not _candidate_matches_replacement_major_keywords(candidate, spec.get("major_keywords") or []):
        return "major_direction_mismatch_candidate"
    if spec.get("constraint_carryover") and not _candidate_satisfies_confirmed_constraints(candidate, constraints_file):
        return "confirmed_requirement_candidate"
    dims = set(spec.get("improve_dims") or [])
    markers = set(spec.get("exclude_markers") or [])
    if "tuition_decrease" in dims:
        tuition = _item_tuition(candidate)
        if tuition <= 0 or tuition < 1000:
            return "missing_or_invalid_tuition_candidate"
        old_min_tuition = _as_int(spec.get("old_min_tuition"))
        if old_min_tuition > 0 and tuition >= old_min_tuition:
            return "not_lower_tuition_candidate"
    if "school_rank_improve" in dims:
        old_best_school_rank = _as_int(spec.get("old_best_school_rank"))
        school_rank = _as_int(_item_value(candidate, "schoolRank", "school_rank"))
        if old_best_school_rank > 0 and (school_rank <= 0 or school_rank >= old_best_school_rank):
            return "not_higher_rank_candidate"
    if "admission_ratio_increase" in dims:
        old_min_admission_ratio = _as_int(spec.get("old_min_admission_ratio"))
        admission_ratio = _admission_ratio(candidate)
        if old_min_admission_ratio > 0 and admission_ratio <= old_min_admission_ratio:
            return "not_higher_admission_ratio_candidate"
    if "province_match" in dims and spec.get("old_provinces"):
        province = str(_item_value(candidate, "provinceName", "province_name", "province") or "").strip()
        if province not in set(spec.get("old_provinces") or []):
            return "province_mismatch_candidate"
    for marker in markers:
        if _replacement_marker_matches(candidate, marker):
            return f"{marker}_candidate"
    return ""


async def _auto_select_replacement_candidates(
    ctx: RunContext[RequestContext],
    old_items: list[dict[str, Any]],
    spec: ReplacementSpec,
) -> tuple[list[dict[str, Any]], str]:
    if not old_items:
        return [], "missing_old_items"
    if not _replacement_spec_is_actionable(spec):
        return [], "replacement_spec_missing"
    old_unit_ids = {_item_unit_id(item) for item in old_items if _item_unit_id(item)}
    wanted = max(1, len(old_unit_ids))
    sandbox = getattr(ctx.deps, "sandbox", None)
    if sandbox is None:
        data = _sandbox_unavailable("plan/candidates.json")
    else:
        data = await sandbox.read("plan/candidates.json", query=_replacement_candidate_query(spec, wanted))
        data = data if isinstance(data, dict) else {}
    candidates = [item for item in _candidate_items(data) if _item_volunteer_id(item)]
    if not candidates:
        return [], "candidate_items_unavailable"
    old_volunteer_ids = {_item_volunteer_id(item) for item in old_items if _item_volunteer_id(item)}
    constraints_file: dict[str, Any] = {}
    if sandbox is not None and spec.get("constraint_carryover"):
        constraints_file = await sandbox.read("constraints.json")
        constraints_file = constraints_file if isinstance(constraints_file, dict) else {}
    candidates = [
        item
        for item in candidates
        if _item_volunteer_id(item) not in old_volunteer_ids
        and not _replacement_candidate_block_reason(
            item,
            old_unit_ids=old_unit_ids,
            spec=spec,
            constraints_file=constraints_file,
        )
    ]
    if not candidates:
        return [], "candidate_no_match"
    ranked = sorted(
        candidates,
        key=lambda item: _candidate_replacement_score(item, old_items, spec),
        reverse=True,
    )
    selected = ranked[:wanted]
    if len(selected) < wanted:
        return [], "candidate_insufficient"
    return selected, "ok" if selected else "candidate_no_match"


def _item_unit_id(item: dict[str, Any]) -> str:
    for key in ("unitId", "unit_id", "id"):
        text = str(item.get(key) or "").strip()
        if text:
            return text
    for nested in item.get("majorItems") or item.get("major_items") or []:
        if not isinstance(nested, dict):
            continue
        text = str(nested.get("unitId") or nested.get("unit_id") or "").strip()
        if text:
            return text
        volunteer_id = str(nested.get("volunteerId") or nested.get("volunteer_id") or "").strip()
        if "_" in volunteer_id:
            return volunteer_id.split("_", 1)[0]
    volunteer_id = str(item.get("volunteerId") or item.get("volunteer_id") or "").strip()
    if "_" in volunteer_id:
        return volunteer_id.split("_", 1)[0]
    return volunteer_id


def _item_volunteer_id(item: dict[str, Any]) -> str:
    for key in ("volunteerId", "volunteer_id", "id"):
        text = str(item.get(key) or "").strip()
        if text:
            return text
    for nested in item.get("majorItems") or item.get("major_items") or []:
        if not isinstance(nested, dict):
            continue
        text = str(nested.get("volunteerId") or nested.get("volunteer_id") or nested.get("id") or "").strip()
        if text:
            return text
    return ""


def _chinese_ordinal_value(text: str) -> int:
    value = str(text or "").strip()
    if not value:
        return 0
    digit_map = {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    if value in digit_map:
        return digit_map[value]
    if value == "十":
        return 10
    if value.startswith("十"):
        return 10 + digit_map.get(value[1:], 0)
    if "十" in value:
        left, right = value.split("十", 1)
        return digit_map.get(left, 0) * 10 + (digit_map.get(right, 0) if right else 0)
    return 0


def _target_position_value(target: str) -> int:
    text = "".join(str(target or "").split())
    if not text:
        return 0
    if any(mark in text for mark in ("-", "到", "~", "至")):
        return 0
    digits = "".join(ch for ch in text if ch.isdigit())
    if digits:
        return _as_int(digits)
    match = re.search(r"第([一二两三四五六七八九十]+)", text)
    return _chinese_ordinal_value(match.group(1)) if match else 0


def _target_position_range(target: str) -> list[int]:
    text = "".join(str(target or "").split())
    if not text:
        return []
    normalized = text.replace("第", "").replace("个", "").replace("位", "")
    for marker in ("到", "至", "~", "-"):
        if marker not in normalized:
            continue
        left, right = normalized.split(marker, 1)
        start = _as_int("".join(ch for ch in left if ch.isdigit()))
        end = _as_int("".join(ch for ch in right if ch.isdigit()))
        if start <= 0 or end <= 0:
            return []
        if start > end:
            start, end = end, start
        return list(range(start, end + 1))
    return []


def _target_position_values(target: str) -> list[int]:
    text = "".join(str(target or "").split())
    if not text or _target_tier_value(text):
        return []
    range_values = _target_position_range(text)
    if range_values:
        return range_values
    numbers = [_as_int(token) for token in re.findall(r"\d+", text)]
    numbers = [value for value in numbers if value > 0]
    if len(numbers) > 1 and any(marker in text for marker in ("和", "、", ",", "，")):
        return list(dict.fromkeys(numbers))
    return []


def _target_tier_value(target: str) -> str:
    text = str(target or "")
    for value in ("冲", "稳", "保"):
        if value in text:
            return value
    if "保底" in text or "兜底" in text:
        return "保"
    if "冲刺" in text:
        return "冲"
    if "稳妥" in text:
        return "稳"
    return ""


def _target_tier_ordinals(target: str) -> list[int]:
    text = "".join(str(target or "").split())
    if not _target_tier_value(text):
        return []
    values: list[int] = []
    word_map = {
        "第一": 1,
        "第一个": 1,
        "第一位": 1,
        "第二": 2,
        "第二个": 2,
        "第二位": 2,
        "第三": 3,
        "第三个": 3,
        "第三位": 3,
    }
    for word, ordinal in word_map.items():
        if word in text:
            values.append(ordinal)
    numbers = [_as_int(token) for token in re.findall(r"\d+", text)]
    values.extend(value for value in numbers if value > 0)
    if "前两" in text or "前2" in text:
        values.extend([1, 2])
    if "最后" in text or "末位" in text:
        values.append(-1)
    return list(dict.fromkeys(values))


def _target_tier_ordinal(target: str) -> int:
    text = "".join(str(target or "").split())
    if not _target_tier_value(text):
        return 0
    ordinal_words = {
        "第一": 1,
        "第一个": 1,
        "第一位": 1,
        "第二": 2,
        "第二个": 2,
        "第二位": 2,
        "第三": 3,
        "第三个": 3,
        "第三位": 3,
        "最后": -1,
        "末位": -1,
    }
    for word, ordinal in ordinal_words.items():
        if word in text:
            return ordinal
    digits = "".join(ch for ch in text if ch.isdigit())
    return _as_int(digits)


def _item_position(item: dict[str, Any]) -> int:
    return _as_int(_item_value(item, "position", "rank", "order"))


def _sort_plan_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: (_item_position(item) or 10**9, _item_unit_id(item), _item_volunteer_id(item)))


def _ordered_plan_unit_representatives(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    representatives: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(_sort_plan_items(items)):
        group_key = _plan_item_group_key(item, index)
        if group_key in seen:
            continue
        seen.add(group_key)
        representatives.append(item)
    return representatives


def _items_by_unit_positions(items: list[dict[str, Any]], positions: list[int]) -> list[dict[str, Any]]:
    if not positions:
        return []
    representatives = _ordered_plan_unit_representatives(items)
    by_backend_position = {
        _item_position(item): item
        for item in representatives
        if _item_position(item) > 0
    }
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for position in positions:
        item: dict[str, Any] | None = None
        if 1 <= position <= len(representatives):
            item = representatives[position - 1]
        elif position in by_backend_position:
            item = by_backend_position[position]
        if not item:
            continue
        item_id = _item_unit_id(item) or _item_volunteer_id(item) or _plan_item_group_key(item, len(seen))
        if item_id in seen:
            continue
        seen.add(item_id)
        result.append(item)
    return result


def _plan_position_group_values(value: Any) -> list[int]:
    result: list[int] = []
    for item in _as_list(value):
        position = _as_int(item)
        if position == 0:
            continue
        if position not in result:
            result.append(position)
    return result


def _items_by_tier_ordinal(items: list[dict[str, Any]], target: str) -> list[dict[str, Any]]:
    tier = _target_tier_value(target)
    ordinals = _target_tier_ordinals(target) or [_target_tier_ordinal(target)]
    ordinals = [ordinal for ordinal in ordinals if ordinal != 0]
    if not tier or not ordinals:
        return []
    tier_items = [
        item
        for item in _ordered_plan_unit_representatives(items)
        if _normalize_tier(_item_value(item, "tier", "riskTier", "risk_tier")) == tier
    ]
    if not tier_items:
        return []
    result: list[dict[str, Any]] = []
    for ordinal in ordinals:
        index = len(tier_items) - 1 if ordinal < 0 else ordinal - 1
        if 0 <= index < len(tier_items):
            result.append(tier_items[index])
    return result


def _position_for_tier_ordinal(items: list[dict[str, Any]], tier: str, ordinal: int) -> int:
    if not tier or ordinal == 0:
        return 0
    tier_items = [
        item
        for item in _ordered_plan_unit_representatives(items)
        if _normalize_tier(_item_value(item, "tier", "riskTier", "risk_tier")) == tier
    ]
    if not tier_items:
        return 0
    index = len(tier_items) - 1 if ordinal < 0 else ordinal - 1
    index = max(0, min(index, len(tier_items) - 1))
    return _item_position(tier_items[index])


def _admission_ratio(item: dict[str, Any]) -> int:
    return _as_int(_item_value(item, "admissionRatio", "admission_ratio", "admissionProbability", "probability"))


def _looks_like_id(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if any("\u4e00" <= ch <= "\u9fff" for ch in text):
        return False
    return any(ch.isdigit() for ch in text)


def _match_item_by_target(item: dict[str, Any], target: str) -> bool:
    text = str(target or "").strip()
    if not text:
        return False
    compact_target = _compact_text(text)
    if not compact_target:
        return False
    ids = [_item_unit_id(item), _item_volunteer_id(item)]
    if text in ids:
        return True
    school = str(_item_value(item, "schoolName", "school_name", "collegeName") or "").strip()
    if _matches_school_abbreviation(school, text):
        return True
    names = [school] + _item_major_names(item) + [_plan_item_snippet(item)]
    if "." in text or "·" in text or "-" in text:
        parts = [part for part in text.replace("·", ".").replace("-", ".").split(".") if part.strip()]
        return all(_matches_any_text(names, [part]) for part in parts)
    return _matches_any_text(names, [compact_target])


def _dedupe_items_by_id(items: list[dict[str, Any]], id_getter) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        item_id = str(id_getter(item) or "").strip()
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        result.append(item)
    return result


async def _resolve_plan_targets(
    ctx: RunContext[RequestContext],
    targets: list[str] | None,
    *,
    source: Literal["plan", "candidates"],
) -> tuple[list[dict[str, Any]], list[str], str]:
    raw_targets = _as_list(targets)
    if not raw_targets:
        return [], [], "missing_targets"
    if source == "plan":
        data = await _sandbox_data(ctx, "plan/items.json")
        items = _items_from_plan_file(data)
        id_getter = _item_unit_id
    else:
        data = await _sandbox_data(ctx, "plan/candidates.json")
        items = _candidate_items(data)
        id_getter = _item_volunteer_id
    resolved: list[dict[str, Any]] = []
    missing: list[str] = []
    for target in raw_targets:
        text = str(target or "").strip()
        if not text:
            continue
        if source == "plan":
            target_positions = _target_position_values(text) or _target_position_range(text)
            if not target_positions:
                single_position = _target_position_value(text)
                target_positions = [single_position] if single_position > 0 else []
            range_matches = _items_by_unit_positions(items, target_positions)
            if range_matches:
                resolved.extend(range_matches)
                continue
            tier_ordinal_matches = _items_by_tier_ordinal(items, text)
            if tier_ordinal_matches:
                resolved.extend(tier_ordinal_matches)
                continue
        direct = [
            item
            for item in items
            if str(id_getter(item) or "").strip() == text
            or (source == "plan" and str(_item_volunteer_id(item) or "").strip() == text)
        ]
        matches = direct or [item for item in items if _match_item_by_target(item, text)]
        matches = _dedupe_items_by_id(matches, id_getter)
        if len(matches) == 1:
            resolved.append(matches[0])
        elif len(matches) > 1:
            return resolved, [text], "ambiguous_targets"
        elif _looks_like_id(text):
            resolved.append({"unitId" if source == "plan" else "volunteerId": text})
        else:
            missing.append(text)
    resolved = _dedupe_items_by_id(resolved, id_getter)
    reason = "ok" if not missing else "missing_targets"
    return resolved, missing, reason


async def _plan_items_for_target_position(
    ctx: RunContext[RequestContext],
    target_position: int | None,
    filters: dict[str, Any] | None,
) -> tuple[int, dict[str, Any], str]:
    direct_position = _as_int(target_position)
    if direct_position > 0:
        return direct_position, {}, "ok"
    normalized_filters, _ = _normalize_plan_query_filters(filters if isinstance(filters, dict) else {})
    target_tier = _as_list(
        normalized_filters.pop("target_tier", None)
        or normalized_filters.pop("targetTier", None)
        or normalized_filters.pop("to_tier", None)
        or normalized_filters.pop("toTier", None)
    )
    target_ordinal = _as_int(
        normalized_filters.pop("target_ordinal", None)
        or normalized_filters.pop("targetOrdinal", None)
        or normalized_filters.pop("target_tier_ordinal", None)
        or normalized_filters.pop("targetTierOrdinal", None)
    )
    if not target_tier or target_ordinal == 0:
        return 0, normalized_filters, "missing_target_position"
    data = await _sandbox_data(ctx, "plan/items.json")
    items = _items_from_plan_file(data)
    position = _position_for_tier_ordinal(items, _normalize_tier(target_tier[0]), target_ordinal)
    if position <= 0:
        return 0, normalized_filters, "target_position_not_found"
    normalized_filters = {
        **normalized_filters,
        "target_tier": [_normalize_tier(target_tier[0])],
        "target_ordinal": target_ordinal,
    }
    return position, normalized_filters, "ok"


async def _resolve_plan_filter_selector_target(
    ctx: RunContext[RequestContext],
    filters: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    normalized_filters, _ = _normalize_plan_query_filters(filters if isinstance(filters, dict) else {})
    if not normalized_filters:
        return [], normalized_filters, "missing_filters"
    selector_sort = str(
        normalized_filters.pop("selector_sort", None)
        or normalized_filters.pop("selectorSort", None)
        or normalized_filters.pop("sort_field", None)
        or normalized_filters.pop("sortField", None)
        or normalized_filters.pop("sort_by", None)
        or normalized_filters.pop("sortBy", None)
        or normalized_filters.pop("selector", None)
        or ""
    ).strip()
    selector_rank = str(
        normalized_filters.pop("selector_rank", None)
        or normalized_filters.pop("selectorRank", None)
        or normalized_filters.pop("sort_order", None)
        or normalized_filters.pop("sortOrder", None)
        or normalized_filters.pop("rank", None)
        or ""
    ).strip()
    selector_ordinal = _as_int(
        normalized_filters.pop("selector_ordinal", None)
        or normalized_filters.pop("selectorOrdinal", None)
        or normalized_filters.pop("ordinal", None)
    )
    selector_sort = _normalize_plan_selector_sort(selector_sort)
    selector_rank = _normalize_plan_selector_rank(selector_rank)
    if selector_sort and not selector_rank:
        selector_rank = "max"
    target_keys = {
        "target_tier",
        "targetTier",
        "target_ordinal",
        "targetOrdinal",
        "target_tier_ordinal",
        "targetTierOrdinal",
        "to_tier",
        "toTier",
    }
    target_filters: dict[str, Any] = {}
    for key in list(normalized_filters):
        if key in target_keys:
            target_filters[key] = normalized_filters.pop(key, None)
    if not normalized_filters:
        return [], normalized_filters, "missing_filters"
    data = await _sandbox_data(ctx, "plan/items.json")
    items = _items_from_plan_file(data)
    if not items:
        return [], normalized_filters, "plan_items_unavailable"
    batch = getattr(ctx.deps, "batch", None) or "01"
    matches = [
        item
        for item in items
        if _matches_plan_item(item, normalized_filters, batch=batch)
    ]
    if not matches:
        return [], normalized_filters, "filter_no_match"
    matches = _sort_plan_items(matches)
    if len(matches) > 1 and not selector_sort and selector_rank != "last" and selector_ordinal <= 0:
        normalized_filters = {
            **normalized_filters,
            **target_filters,
        }
        return [], normalized_filters, "ambiguous_selector"
    if selector_sort == "admission_probability":
        reverse = selector_rank != "min"
        matches = sorted(matches, key=_admission_ratio, reverse=reverse)
    elif selector_sort == "tuition":
        reverse = selector_rank != "min"
        matches = sorted(matches, key=_item_tuition, reverse=reverse)
    elif selector_rank == "last":
        matches = list(reversed(matches))
    if selector_ordinal > 0:
        index = selector_ordinal - 1
        if index >= len(matches):
            return [], normalized_filters, "filter_no_match"
        matches = [matches[index]]
    else:
        matches = matches[:1]
    normalized_filters = {
        **normalized_filters,
        **target_filters,
        **({"selector_sort": selector_sort} if selector_sort else {}),
        **({"selector_rank": selector_rank} if selector_rank else {}),
        **({"selector_ordinal": selector_ordinal} if selector_ordinal else {}),
    }
    return _dedupe_items_by_id(matches, _item_unit_id), normalized_filters, "ok"


async def _resolve_plan_filter_targets(
    ctx: RunContext[RequestContext],
    filters: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    normalized_filters, _ = _normalize_plan_query_filters(filters if isinstance(filters, dict) else {})
    if not normalized_filters:
        return [], normalized_filters, "missing_filters"
    data = await _sandbox_data(ctx, "plan/items.json")
    items = _items_from_plan_file(data)
    if not items:
        return [], normalized_filters, "plan_items_unavailable"
    position_group_values = _plan_position_group_values(normalized_filters.get("position_group"))
    if "position_group" in normalized_filters:
        resolved = _items_by_unit_positions(items, position_group_values)
        remaining_filters = {
            key: value
            for key, value in normalized_filters.items()
            if key != "position_group"
        }
        if resolved and remaining_filters:
            batch = getattr(ctx.deps, "batch", None) or "01"
            resolved = [
                item
                for item in resolved
                if _matches_plan_item(item, remaining_filters, batch=batch)
            ]
        resolved = _dedupe_items_by_id(resolved, _item_unit_id)
        return resolved, normalized_filters, "ok" if resolved else "filter_no_match"
    batch = getattr(ctx.deps, "batch", None) or "01"
    resolved = [
        item
        for item in items
        if _matches_plan_item(item, normalized_filters, batch=batch)
    ]
    resolved = _dedupe_items_by_id(resolved, _item_unit_id)
    return resolved, normalized_filters, "ok" if resolved else "filter_no_match"


def _filter_resolved_plan_items(
    ctx: RunContext[RequestContext],
    items: list[dict[str, Any]],
    filters: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    normalized_filters, _ = _normalize_plan_query_filters(filters if isinstance(filters, dict) else {})
    if not normalized_filters:
        return items, normalized_filters, "ok"
    batch = getattr(ctx.deps, "batch", None) or "01"
    filtered = [
        item
        for item in items
        if _matches_plan_item(item, normalized_filters, batch=batch)
    ]
    filtered = _dedupe_items_by_id(filtered, _item_unit_id)
    return filtered, normalized_filters, "ok" if filtered else "filter_no_match"


def _review_issue_fallback_filters(review_issue_code: Any) -> dict[str, Any]:
    code = _canonical_review_issue_code(review_issue_code)
    if code == "high_tuition":
        return {"program_type": ["高收费"]}
    if code == "cooperative_program":
        return {"program_type": ["中外合作"]}
    return {}


async def _review_issue_action_target(
    ctx: RunContext[RequestContext],
    review_issue_code: str,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str]:
    issue = await _review_issue_by_code(ctx, review_issue_code)
    if not issue:
        code = _canonical_review_issue_code(review_issue_code)
        return None, [], "missing_review_issue_code" if not code else "review_issue_not_found"
    unit_ids = _as_list(issue.get("unit_ids"))
    volunteer_ids = _as_list(issue.get("volunteer_ids"))
    if not unit_ids and not volunteer_ids:
        return issue, [], "review_issue_without_units"
    plan_file = await _sandbox_data(ctx, "plan/items.json")
    plan_items = _items_from_plan_file(plan_file)
    by_unit_id = {_item_unit_id(item): item for item in plan_items if _item_unit_id(item)}
    by_volunteer_id = {_item_volunteer_id(item): item for item in plan_items if _item_volunteer_id(item)}
    resolved: list[dict[str, Any]] = []
    missing: list[str] = []
    for unit_id in unit_ids:
        item = by_unit_id.get(str(unit_id or "").strip())
        if item:
            resolved.append(item)
        else:
            missing.append(str(unit_id or "").strip())
    for volunteer_id in volunteer_ids:
        item = by_volunteer_id.get(str(volunteer_id or "").strip())
        if item:
            resolved.append(item)
        else:
            missing.append(str(volunteer_id or "").strip())
    resolved = _dedupe_items_by_id(resolved, _item_unit_id)
    if missing and not resolved:
        return issue, [{"unitId": item_id} for item_id in missing if item_id], "review_issue_units_not_in_plan"
    return issue, resolved, "ok"


async def _review_issue_by_code(
    ctx: RunContext[RequestContext],
    review_issue_code: str,
) -> dict[str, Any] | None:
    code = _canonical_review_issue_code(review_issue_code)
    if not code:
        return None
    review_file = await _sandbox_data(ctx, "plan/review.json")
    checks = review_file.get("checks") if isinstance(review_file.get("checks"), list) else []
    issues = [
        _normalize_review_issue(check)
        for check in checks
        if isinstance(check, dict) and _review_issue_matches(check, code)
    ]
    return next((item for item in issues if not item.get("passed")), issues[0] if issues else None)


def _review_issue_target_meta(issue: dict[str, Any]) -> dict[str, Any]:
    meta = {
        "code": issue.get("code"),
        "summary": issue.get("summary"),
        "severity": issue.get("severity"),
        "source": "plan/review.json",
    }
    if issue.get("source_code"):
        meta["source_code"] = issue.get("source_code")
    return meta


def _plan_action_family(action: str) -> tuple[str, str]:
    if action == "pin_lock":
        return "plan_mutation", "pin_or_lock_unit"
    if action == "add":
        return "plan_mutation", "add_units"
    if action == "remove":
        return "plan_mutation", "remove_units"
    if action == "move":
        return "plan_mutation", "move_ordered_unit"
    if action == "sort":
        return "plan_mutation", "sort_ordered_plan"
    if action == "generate":
        return "plan_generation", "generate_plan"
    if action == "regenerate_order":
        return "plan_generation", "regenerate_order"
    if action == "replace":
        return "plan_mutation", "replace_units"
    return "plan_mutation", action


def _action_label(action: str) -> str:
    return {
        "add": "加入方案",
        "remove": "移出方案",
        "move": "移动方案位置",
        "replace": "替换方案项",
        "sort": "重新排序",
        "generate": "生成方案",
        "regenerate_order": "重新生成排序方案",
        "pin_lock": "锁定方案位置",
    }.get(action, "调整方案")


def _plan_impact_for_action(action_family: str, summary: dict[str, Any], count: int) -> dict[str, Any]:
    tier_counts = summary.get("tier_counts") if isinstance(summary.get("tier_counts"), dict) else {}
    delta = count if action_family == "add_units" else -count if action_family in {"remove_units", "remove_ordered_unit"} else 0
    return {
        "source": "preview_plan_action",
        "affected_count": count,
        "tier_impact": {"total": delta} if delta else {},
        "before_tier_counts": dict(tier_counts),
    }


def _plan_pending_payload(
    action_family: str,
    *,
    unit_ids: list[str] | None = None,
    volunteer_ids: list[str] | None = None,
    target_position: int | None = None,
    sort_field: str | None = None,
    filters: dict[str, Any] | None = None,
    raw_user_text: str = "",
    review_issue: dict[str, Any] | None = None,
) -> dict[str, Any]:
    atomic: dict[str, Any] = {"action_type": action_family}
    payload: dict[str, Any] = {
        "action_family": action_family,
        "atomic_actions": [atomic],
        "raw_user_text": str(raw_user_text or "").strip(),
    }
    if unit_ids:
        payload["unit_ids"] = unit_ids
        atomic["unit_ids"] = unit_ids
    if volunteer_ids:
        payload["volunteer_ids"] = volunteer_ids
        atomic["volunteer_ids"] = volunteer_ids
    if target_position and target_position > 0:
        payload["target_position"] = target_position
        atomic["target_position"] = target_position
    if sort_field:
        payload["sort_field"] = sort_field
        atomic["sort_field"] = sort_field
    if filters:
        payload["filters"] = filters
        atomic["filters"] = filters
    if review_issue:
        payload["review_issue_target"] = review_issue
        atomic["review_issue_target"] = review_issue
    return payload


async def _create_plan_pending(
    ctx: RunContext[RequestContext],
    *,
    kind: str,
    action_family: str,
    summary: str,
    payload: dict[str, Any],
    affected_scope: str,
    plan_impact: dict[str, Any],
) -> dict[str, Any]:
    source_version = _as_int((await _plan_summary_data(ctx)).get("version"))
    pending_id = f"pending_{uuid.uuid4().hex}"
    now = _now_iso()
    pending_state = {
        "type": "pendingConfirmation",
        "pendingId": pending_id,
        "sessionId": str(ctx.deps.sessionid),
        "kind": kind,
        "status": "active",
        "actionFamily": action_family,
        "summary": summary,
        "affectedScope": affected_scope,
        "executionPayload": payload,
        "createdAt": now,
        "updatedAt": now,
        "sourceBackendVersion": source_version,
        "planImpact": plan_impact,
    }
    if _dry_run_state_mutations(ctx):
        sandbox = getattr(ctx.deps, "sandbox", None)
        if sandbox is not None:
            sandbox.prime(
                "pending.json",
                {
                    "active": True,
                    "pending_id": pending_id,
                    "kind": kind,
                    "action_family": action_family,
                    "summary": summary,
                    "preview_summary": summary,
                    "affected_scope": affected_scope,
                    "execution_payload": payload,
                    "source_backend_version": source_version,
                    "status": "active",
                    "raw": pending_state,
                    "dry_run": True,
                },
                version=source_version,
            )
        return {
            "created": True,
            "dry_run": True,
            "pending_id": pending_id,
            "pending_version": source_version,
            "state": pending_state,
            "backend_response": {},
        }
    if not _PERSIST_PREVIEW_PENDING:
        return {
            "created": False,
            "skipped": "persist_preview_pending_disabled",
            "pending_id": pending_id,
            "pending_version": source_version,
            "state": pending_state,
            "backend_response": {},
        }
    response = await internal_client.save_pending_confirmation(ctx.deps.sessionid, pending_state, version=source_version)
    if not _is_success_response(response):
        return {
            "created": False,
            "pending_id": pending_id,
            "pending_version": source_version,
            "state": pending_state,
            "backend_response": response,
        }
    sandbox = getattr(ctx.deps, "sandbox", None)
    if sandbox is not None:
        sandbox.prime(
            "pending.json",
            {
                "active": True,
                "pending_id": pending_id,
                "kind": kind,
                "action_family": action_family,
                "summary": summary,
                "preview_summary": summary,
                "affected_scope": affected_scope,
                "execution_payload": payload,
                "source_backend_version": source_version,
                "status": "active",
                "raw": pending_state,
            },
            version=source_version,
        )
    return {
        "created": True,
        "pending_id": pending_id,
        "pending_version": source_version,
        "state": pending_state,
        "backend_response": response,
    }


def _intent_values(payload: dict[str, Any], *keys: str) -> list[str]:
    values: list[str] = []
    for key in keys:
        values.extend(_as_list(payload.get(key)))
    return list(dict.fromkeys(value for value in values if value))


def _attribute_scope_value(key: str, value: str) -> str:
    return f"{attribute_label(key)}:{value}"


def _intent_attribute_values(payload: dict[str, Any], keys: tuple[str, ...], *, negative: bool) -> list[str]:
    values: list[str] = []
    for key in keys:
        source_key = f"negative_{key}" if negative else key
        for value in normalize_attribute_filter_values(key, _as_list(payload.get(source_key))):
            _append_unique(values, _attribute_scope_value(key, value))
    return values


def _intent_constraint_payloads(
    merged: dict[str, Any],
) -> tuple[dict[str, list[str]] | None, dict[str, list[str]] | None, dict[str, list[str]] | None]:
    major_intents = merged.get("major_intents") if isinstance(merged.get("major_intents"), dict) else {}
    school_intents = merged.get("school_intents") if isinstance(merged.get("school_intents"), dict) else {}
    city_intents = merged.get("city_intents") if isinstance(merged.get("city_intents"), dict) else {}

    def group(positive: list[str], negative: list[str]) -> dict[str, list[str]] | None:
        payload = {
            "positive": list(dict.fromkeys(value for value in positive if value)),
            "negative": list(dict.fromkeys(value for value in negative if value)),
        }
        return payload if payload["positive"] or payload["negative"] else None

    return (
        group(
            _intent_values(major_intents, "level1", "level2", "level3")
            + _intent_attribute_values(major_intents, _MAJOR_INTENT_ATTRIBUTE_KEYS, negative=False),
            _intent_values(major_intents, "negative_level1", "negative_level2", "negative_level3")
            + _intent_attribute_values(major_intents, _MAJOR_INTENT_ATTRIBUTE_KEYS, negative=True),
        ),
        group(
            _intent_values(school_intents, "colleges")
            + _intent_attribute_values(school_intents, _SCHOOL_INTENT_ATTRIBUTE_KEYS, negative=False),
            _intent_values(school_intents, "negative_colleges")
            + _intent_attribute_values(school_intents, _SCHOOL_INTENT_ATTRIBUTE_KEYS, negative=True),
        ),
        group(
            _intent_values(city_intents, "province", "city", "area"),
            _intent_values(city_intents, "negative_province", "negative_city", "negative_area"),
        ),
    )


def _tuition_budget_bounds(merged: dict[str, Any]) -> tuple[int, int]:
    budget = merged.get("tuition_budget") if isinstance(merged.get("tuition_budget"), dict) else {}
    min_tuition = _first_positive_amount(budget.get("min_tuition_per_year") or budget.get("minTuitionPerYear"))
    max_tuition = _first_positive_amount(budget.get("max_tuition_per_year") or budget.get("maxTuitionPerYear"))
    if min_tuition > 0 and max_tuition > 0 and min_tuition > max_tuition:
        return 0, 0
    return min_tuition, max_tuition


async def _sync_tuition_budget_direct(ctx: RunContext[RequestContext], merged: dict[str, Any]) -> dict[str, Any] | None:
    min_tuition, max_tuition = _tuition_budget_bounds(merged)
    if min_tuition <= 0 and max_tuition <= 0:
        return None
    try:
        response = await internal_client.update_session_tuition_range(
            ctx.deps.sessionid,
            min_tuition=min_tuition,
            max_tuition=max_tuition,
        )
    except Exception as exc:
        return {
            "triggered": True,
            "success": False,
            "min_tuition_per_year": min_tuition,
            "max_tuition_per_year": max_tuition,
            "error": str(exc),
        }
    return {
        "triggered": True,
        "success": _is_success_response(response),
        "min_tuition_per_year": min_tuition,
        "max_tuition_per_year": max_tuition,
        "backend_response": response,
    }


def _selected_values_from_pending_payload(execution_payload: dict[str, Any]) -> list[dict[str, Any]]:
    selected_data = execution_payload.get("selectedData") or execution_payload.get("selected_data")
    if isinstance(selected_data, dict):
        selected = selected_data.get("selected")
        if isinstance(selected, list):
            return [item for item in selected if isinstance(item, dict)]
    selected = execution_payload.get("selected")
    if isinstance(selected, list):
        return [item for item in selected if isinstance(item, dict)]
    return []


def _merge_selected_values(selected_values: list[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for selected in selected_values:
        value = selected.get("value") if isinstance(selected.get("value"), dict) else selected
        if not isinstance(value, dict):
            continue
        for section, section_payload in value.items():
            if str(section or "").startswith("_"):
                continue
            if not isinstance(section_payload, dict):
                continue
            target_section = merged.setdefault(section, {})
            for key, raw_values in section_payload.items():
                bucket = target_section.setdefault(key, [])
                normalized_values = _as_list(raw_values)
                normalized_key = key
                if section == "school_intents":
                    is_negative = key.startswith("negative_")
                    base_key = key.removeprefix("negative_")
                    if base_key in _SCHOOL_INTENT_ATTRIBUTE_KEYS:
                        normalized_values = normalize_attribute_filter_values(base_key, normalized_values)
                        normalized_key = f"negative_{base_key}" if is_negative else base_key
                elif section == "major_intents":
                    is_negative = key.startswith("negative_")
                    base_key = key.removeprefix("negative_")
                    if base_key in _MAJOR_INTENT_ATTRIBUTE_KEYS:
                        normalized_values = normalize_attribute_filter_values(base_key, normalized_values)
                        normalized_key = f"negative_{base_key}" if is_negative else base_key
                elif section == "tuition_budget":
                    normalized_key = _normalize_tuition_budget_key(key)
                    if normalized_key not in _TUITION_BUDGET_INTENT_KEYS:
                        continue
                    amounts = _normalize_tuition_budget_values(raw_values)
                    if not amounts:
                        continue
                    normalized_values = [str(min(amounts) if normalized_key == "max_tuition_per_year" else max(amounts))]
                bucket = target_section.setdefault(normalized_key, [])
                for item in normalized_values:
                    value: Any = _as_int(item) if section == "tuition_budget" else str(item or "").strip()
                    if value and value not in bucket:
                        bucket.append(value)
    return merged


def _pending_execution_payload(pending: dict[str, Any]) -> dict[str, Any]:
    payload = pending.get("execution_payload")
    if isinstance(payload, dict):
        return payload
    raw = pending.get("raw")
    if isinstance(raw, dict):
        payload = raw.get("executionPayload") or raw.get("execution_payload")
        if isinstance(payload, dict):
            return payload
    return {}


def _pending_source_version(pending: dict[str, Any]) -> int:
    raw = pending.get("raw")
    raw_data = raw if isinstance(raw, dict) else {}
    return _as_int(
        pending.get("source_backend_version")
        or pending.get("sourceBackendVersion")
        or raw_data.get("sourceBackendVersion")
        or raw_data.get("planningVersion")
    )


async def _mark_pending_status(ctx: RunContext[RequestContext], pending: dict[str, Any], status: str, **extra: Any) -> None:
    if _dry_run_state_mutations(ctx):
        return
    raw = pending.get("raw")
    state = dict(raw) if isinstance(raw, dict) and raw else {
        "type": "pendingConfirmation",
        "pendingId": pending.get("pending_id") or pending.get("pendingId") or "",
        "sessionId": ctx.deps.sessionid,
        "kind": pending.get("kind") or "",
        "actionFamily": pending.get("action_family") or "",
    }
    state["status"] = status
    state["updatedAt"] = _now_iso()
    state.update({key: value for key, value in extra.items() if value is not None})
    version = _as_int(
        pending.get("_extraDataVersion")
        or pending.get("dataVersion")
        or state.get("_extraDataVersion")
        or state.get("dataVersion")
        or pending.get("source_backend_version")
        or pending.get("sourceBackendVersion")
        or state.get("sourceBackendVersion")
        or state.get("source_backend_version")
    )
    await internal_client.save_pending_confirmation(ctx.deps.sessionid, state, version=version)


def _invalidate_after_pending_action(ctx: RunContext[RequestContext], kind: str, action_family: str) -> None:
    sandbox = getattr(ctx.deps, "sandbox", None)
    if sandbox is None:
        return
    paths = ["pending.json"]
    if kind == "intent_change":
        paths.extend(["profile.json", "constraints.json", "plan/candidates.json"])
        if action_family in {"generate_plan", "regenerate_order", "apply_selected_intents"}:
            paths.extend(["plan/summary.json", "plan/items.json", "plan/review.json"])
    elif kind in {"plan_mutation", "plan_generation"}:
        paths.extend(["plan/summary.json", "plan/items.json", "plan/review.json", "plan/candidates.json"])
    sandbox.invalidate(paths)


def _clear_context_pending(ctx: RunContext[RequestContext]) -> None:
    phase = getattr(ctx.deps, "conversation_phase", None)
    if phase is not None and getattr(phase, "pending", None) is not None:
        phase.clear_pending()


async def _replace_active_pending_for_new_preview(ctx: RunContext[RequestContext]) -> bool:
    if _turn_started_active_pending(ctx) is None:
        return False
    pending = await _pending_data(ctx)
    if not pending.get("active"):
        _clear_context_pending(ctx)
        return False
    kind = str(pending.get("kind") or "").strip()
    action_family = str(pending.get("action_family") or pending.get("actionFamily") or "").strip()
    await _mark_pending_status(ctx, pending, "cancelled", resultCode="replaced_by_new_preview")
    _invalidate_after_pending_action(ctx, kind, action_family)
    _clear_context_pending(ctx)
    return True


async def _latest_planning_version(ctx: RunContext[RequestContext]) -> int:
    summary = await _plan_summary_data(ctx)
    version = _as_int(summary.get("version"))
    if version > 0:
        return version
    sandbox = getattr(ctx.deps, "sandbox", None)
    return _as_int(getattr(sandbox, "latest_backend_version", 0))


async def _apply_intent_pending(
    ctx: RunContext[RequestContext],
    pending: dict[str, Any],
    *,
    apply_to_current_plan_override: bool | None = None,
) -> tuple[bool, dict[str, Any], str]:
    execution_payload = _pending_execution_payload(pending)
    merged = execution_payload.get("merged") if isinstance(execution_payload.get("merged"), dict) else {}
    if not merged:
        merged = _merge_selected_values(_selected_values_from_pending_payload(execution_payload))
    if not merged:
        return False, {"reason": "missing_intent_payload"}, "这次待确认内容缺少可执行报考要求，请重新生成预览。"

    selected_data = execution_payload.get("selectedData") if isinstance(execution_payload.get("selectedData"), dict) else {}
    intent_mode = str(
        execution_payload.get("intentMode")
        or execution_payload.get("intent_mode")
        or selected_data.get("intentMode")
        or selected_data.get("intent_mode")
        or "constraint"
    ).strip()
    if intent_mode != "constraint":
        intent_mode = "constraint"
    constraint_type = _constraint_type_from_execution_payload(execution_payload)
    apply_to_current_plan = (
        bool(apply_to_current_plan_override)
        if apply_to_current_plan_override is not None
        else _apply_to_current_plan_from_execution_payload(execution_payload)
    )

    plan_summary = await _plan_summary_data(ctx)
    has_plan = bool(plan_summary.get("has_plan"))
    diff_before: dict[str, Any] = {}
    should_validate_negative_plan_diff = has_plan and apply_to_current_plan and (
        _merged_has_negative_values(merged) or _merged_has_tuition_budget(merged)
    )
    if should_validate_negative_plan_diff:
        diff_before = await _ordered_plan_snapshot_before_action(ctx)

    major_preferences, school_preferences, region_preferences = _intent_constraint_payloads(merged)
    has_constraint_payload = any((major_preferences, school_preferences, region_preferences))
    response: dict[str, Any] = {"skipped": "no_constraint_payload"}
    constraint_success = True
    if has_constraint_payload:
        response = await internal_client.update_planning_constraint_state(
            ctx.deps.sessionid,
            intent_mode="constraint",
            major_preferences=major_preferences,
            school_preferences=school_preferences,
            region_preferences=region_preferences,
        )
        constraint_success = _is_success_response(response)
    tuition_budget_response = await _sync_tuition_budget_direct(ctx, merged)
    tuition_budget_applied = (
        True
        if tuition_budget_response is None
        else bool(tuition_budget_response.get("success"))
    )
    success = constraint_success and tuition_budget_applied
    tenant_id = getattr(ctx.deps, "tenant_id", 1)
    candidate_pool_regenerated = False
    ordered_response = None
    plan_regenerated = False
    requires_candidate_pool_rebuild = False
    if success and has_plan and apply_to_current_plan:
        ordered_response = await internal_client.generate_planning_ordered_plan(
            tenant_id,
            ctx.deps.sessionid,
        )
        plan_regenerated = _is_success_response(ordered_response)

    data = {
        "intent_mode": intent_mode,
        "constraint_type": constraint_type,
        "merged": merged,
        "backend_response": response,
        "constraint_state_applied": constraint_success,
        "tuition_budget_response": tuition_budget_response,
        "tuition_budget_applied": tuition_budget_applied,
        "has_plan": has_plan,
        "apply_to_current_plan": apply_to_current_plan,
        "requires_candidate_pool_rebuild": requires_candidate_pool_rebuild,
        "candidate_pool_regenerated": candidate_pool_regenerated,
        "plan_regenerated": plan_regenerated,
    }
    if ordered_response is not None:
        data["ordered_plan_response"] = ordered_response
    if should_validate_negative_plan_diff and plan_regenerated:
        validation = _ordered_plan_intent_exclude_validation(
            merged,
            before=diff_before,
            after=_ordered_plan_snapshot_from_response(ordered_response),
            batch=getattr(ctx.deps, "batch", None) or "01",
        )
        data["ordered_plan_diff"] = validation
    if not success:
        message = "这次报考要求没有写入成功，请重新生成预览后再确认。"
    elif has_plan and not apply_to_current_plan:
        message = "已采纳这次报考要求，后续生成或调整方案会按这个要求处理；这次先不改当前方案。"
    elif (
        has_plan
        and plan_regenerated
        and isinstance(data.get("ordered_plan_diff"), dict)
        and data["ordered_plan_diff"].get("available")
        and not data["ordered_plan_diff"].get("passed")
    ):
        message = "已采纳这次报考要求，但当前方案里仍有不符合要求的志愿，请刷新方案后重新生成或调整。"
    elif has_plan and plan_regenerated:
        message = "已采纳这次报考要求，并按新要求重新调整了当前方案。"
    elif has_plan:
        message = "已采纳这次报考要求，但当前方案暂时没有重新调整成功，请稍后重新生成方案。"
    else:
        message = "已采纳这次报考要求，后续生成方案会按这个要求处理。"
    return success, data, message


def _first_atomic_action(payload: dict[str, Any]) -> dict[str, Any]:
    actions = payload.get("atomic_actions") or payload.get("atomicActions")
    if isinstance(actions, list):
        for action in actions:
            if isinstance(action, dict):
                return action
    return {}


def _plan_unit_ids(payload: dict[str, Any], atomic: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for source in (payload, atomic, atomic.get("filters") if isinstance(atomic.get("filters"), dict) else {}):
        for key in ("unit_ids", "unitIds", "unit_id", "unitId"):
            for value in _as_list(source.get(key) if isinstance(source, dict) else None):
                _append_unique(values, value)
    return values


def _plan_volunteer_ids(payload: dict[str, Any], atomic: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for source in (payload, atomic, atomic.get("filters") if isinstance(atomic.get("filters"), dict) else {}):
        for key in ("volunteer_ids", "volunteerIds", "volunteer_id", "volunteerId"):
            for value in _as_list(source.get(key) if isinstance(source, dict) else None):
                _append_unique(values, value)
    return values


def _plan_sort_field(payload: dict[str, Any], atomic: dict[str, Any]) -> str:
    for source in (payload, atomic, atomic.get("filters") if isinstance(atomic.get("filters"), dict) else {}):
        if not isinstance(source, dict):
            continue
        for key in ("sort_field", "sortField", "field"):
            value = str(source.get(key) or "").strip()
            if value:
                return value
    return ""


def _plan_target_position(payload: dict[str, Any], atomic: dict[str, Any]) -> int:
    for source in (payload, atomic, atomic.get("filters") if isinstance(atomic.get("filters"), dict) else {}):
        if not isinstance(source, dict):
            continue
        value = _as_int(source.get("target_position") or source.get("targetPosition"))
        if value > 0:
            return value
    return 0


def _unit_volunteer_ids(item: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("volunteerId", "volunteer_id", "id"):
        value = str(item.get(key) or "").strip()
        if value:
            _append_unique(values, value)
    for key in ("volunteerIds", "volunteer_ids"):
        for value in _as_list(item.get(key)):
            text = str(value or "").strip()
            if text:
                _append_unique(values, text)
    for nested in item.get("majorItems") or item.get("major_items") or []:
        if not isinstance(nested, dict):
            continue
        for key in ("volunteerId", "volunteer_id", "id"):
            value = str(nested.get(key) or "").strip()
            if value:
                _append_unique(values, value)
    return values


def _ordered_plan_snapshot(plan_file: dict[str, Any]) -> dict[str, Any]:
    units = plan_file.get("units") if isinstance(plan_file.get("units"), list) else []
    items = _items_from_plan_file(plan_file)
    ordered_source = [item for item in units if isinstance(item, dict)] or _ordered_plan_unit_representatives(items)
    order: list[str] = []
    volunteer_ids: list[str] = []
    positions: dict[str, int] = {}
    for index, item in enumerate(ordered_source):
        unit_id = _item_unit_id(item)
        if not unit_id or unit_id in positions:
            continue
        order.append(unit_id)
        positions[unit_id] = index + 1
        for volunteer_id in _unit_volunteer_ids(item):
            _append_unique(volunteer_ids, volunteer_id)
    for item in items:
        for volunteer_id in _unit_volunteer_ids(item):
            _append_unique(volunteer_ids, volunteer_id)
    return {
        "available": bool(order or volunteer_ids),
        "unit_order": order,
        "unit_positions": positions,
        "volunteer_ids": volunteer_ids,
        "unit_total": len(order),
        "items": items or ordered_source,
    }


async def _ordered_plan_snapshot_before_action(ctx: RunContext[RequestContext]) -> dict[str, Any]:
    try:
        return _ordered_plan_snapshot(await _sandbox_data(ctx, "plan/items.json"))
    except Exception as exc:  # pragma: no cover - defensive around backend reads
        return {"available": False, "reason": type(exc).__name__}


def _ordered_plan_snapshot_from_response(response: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(response, dict):
        return {"available": False, "reason": "missing_backend_response"}
    try:
        return _ordered_plan_snapshot(_ordered_items_file_from_response(response))
    except Exception as exc:  # pragma: no cover - defensive around malformed backend responses
        return {"available": False, "reason": type(exc).__name__}


def _ordered_plan_diff_validation(
    action_family: str,
    *,
    before: dict[str, Any],
    after: dict[str, Any],
    unit_ids: list[str] | None = None,
    volunteer_ids: list[str] | None = None,
    target_position: int = 0,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "available": bool(before.get("available") and after.get("available")),
        "action_family": action_family,
        "before_unit_total": _as_int(before.get("unit_total")),
        "after_unit_total": _as_int(after.get("unit_total")),
    }
    if not result["available"]:
        result["passed"] = True
        result["changed"] = None
        result["reason"] = "snapshot_unavailable"
        return result

    before_order = [str(value) for value in before.get("unit_order") or []]
    after_order = [str(value) for value in after.get("unit_order") or []]
    before_positions = before.get("unit_positions") if isinstance(before.get("unit_positions"), dict) else {}
    after_positions = after.get("unit_positions") if isinstance(after.get("unit_positions"), dict) else {}
    after_unit_set = set(after_order)
    after_volunteer_set = {str(value) for value in after.get("volunteer_ids") or []}
    requested_units = [str(value) for value in unit_ids or [] if str(value or "").strip()]
    requested_volunteers = [str(value) for value in volunteer_ids or [] if str(value or "").strip()]
    changed = before_order != after_order
    result["changed"] = changed

    if action_family in {"remove_units", "remove_ordered_unit"}:
        remaining = [unit_id for unit_id in requested_units if unit_id in after_unit_set]
        result.update(
            {
                "passed": not remaining,
                "reason": "ok" if not remaining else "removed_units_still_present",
                "unit_ids": requested_units,
                "remaining_unit_ids": remaining,
            }
        )
        return result

    if action_family == "replace_units":
        remaining = [unit_id for unit_id in requested_units if unit_id in after_unit_set]
        missing_selected = [volunteer_id for volunteer_id in requested_volunteers if volunteer_id not in after_volunteer_set]
        result.update(
            {
                "passed": not remaining and not missing_selected,
                "reason": (
                    "ok"
                    if not remaining and not missing_selected
                    else "replace_expected_units_or_candidates_missing"
                ),
                "unit_ids": requested_units,
                "remaining_unit_ids": remaining,
                "selected_volunteer_ids": requested_volunteers,
                "missing_selected_volunteer_ids": missing_selected,
            }
        )
        return result

    if action_family in {"move_unit", "move_ordered_unit"}:
        unit_id = requested_units[0] if requested_units else ""
        before_position = _as_int(before_positions.get(unit_id))
        after_position = _as_int(after_positions.get(unit_id))
        result.update(
            {
                "passed": bool(unit_id and after_position == target_position and before_position != after_position),
                "reason": (
                    "ok"
                    if unit_id and after_position == target_position and before_position != after_position
                    else "move_position_not_changed_as_expected"
                ),
                "unit_id": unit_id,
                "before_position": before_position,
                "after_position": after_position,
                "target_position": target_position,
            }
        )
        return result

    if action_family == "sort_ordered_plan":
        result.update(
            {
                "passed": True,
                "reason": "ok" if changed else "sort_order_unchanged",
            }
        )
        return result

    result["passed"] = True
    result["reason"] = "unsupported_validation_action"
    return result


def _negative_payload_from_intent_section(
    section_payload: dict[str, Any],
    *,
    value_keys: tuple[str, ...],
    attribute_keys: tuple[str, ...] = (),
    value_key_aliases: dict[str, str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    aliases = value_key_aliases or {}
    for key in value_keys:
        values = _as_list(section_payload.get(f"negative_{key}"))
        if values:
            payload[aliases.get(key, key)] = values
    for key in attribute_keys:
        values = normalize_attribute_filter_values(key, _as_list(section_payload.get(f"negative_{key}")))
        if values:
            payload[key] = values
    return payload


def _negative_intent_checks_from_merged(merged: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    checks: list[tuple[str, dict[str, Any]]] = []
    major_intents = merged.get("major_intents") if isinstance(merged.get("major_intents"), dict) else {}
    school_intents = merged.get("school_intents") if isinstance(merged.get("school_intents"), dict) else {}
    city_intents = merged.get("city_intents") if isinstance(merged.get("city_intents"), dict) else {}
    tuition_budget = merged.get("tuition_budget") if isinstance(merged.get("tuition_budget"), dict) else {}
    major_payload = _negative_payload_from_intent_section(
        major_intents,
        value_keys=("level1", "level2", "level3"),
        attribute_keys=_MAJOR_INTENT_ATTRIBUTE_KEYS,
    )
    school_payload = _negative_payload_from_intent_section(
        school_intents,
        value_keys=("colleges",),
        attribute_keys=_SCHOOL_INTENT_ATTRIBUTE_KEYS,
        value_key_aliases={"colleges": "schools"},
    )
    region_payload = _negative_payload_from_intent_section(
        city_intents,
        value_keys=("province", "city", "area"),
    )
    if major_payload:
        checks.append(("major", major_payload))
    if school_payload:
        checks.append(("school", school_payload))
    if region_payload:
        checks.append(("region", region_payload))
    if _payload_has_values(tuition_budget):
        checks.append(("tuition_budget", tuition_budget))
    return checks


def _ordered_plan_intent_exclude_validation(
    merged: dict[str, Any],
    *,
    before: dict[str, Any],
    after: dict[str, Any],
    batch: str | None,
) -> dict[str, Any]:
    checks = _negative_intent_checks_from_merged(merged)
    result: dict[str, Any] = {
        "available": bool(after.get("available")),
        "action_family": "apply_selected_intents",
        "before_unit_total": _as_int(before.get("unit_total")),
        "after_unit_total": _as_int(after.get("unit_total")),
        "check_count": len(checks),
    }
    if not checks:
        result.update({"passed": True, "reason": "no_negative_intent_check"})
        return result
    if not after.get("available"):
        result.update({"passed": True, "reason": "snapshot_unavailable"})
        return result
    items = [item for item in after.get("items") or [] if isinstance(item, dict)]
    if not items:
        result.update({"available": False, "passed": True, "reason": "snapshot_items_unavailable"})
        return result
    remaining: list[dict[str, Any]] = []
    seen_units: set[str] = set()
    for item in items:
        if not any(_plan_item_matches_intent_payload(item, intent_type, payload) for intent_type, payload in checks):
            continue
        unit_id = _item_unit_id(item) or _item_volunteer_id(item)
        if unit_id in seen_units:
            continue
        seen_units.add(unit_id)
        remaining.append(_plan_item_brief(item))
    result.update(
        {
            "passed": not remaining,
            "reason": "ok" if not remaining else "excluded_intent_items_still_present",
            "remaining_count": len(remaining),
            "remaining_items": remaining[:8],
        }
    )
    return result


def _plan_apply_result_with_diff(
    success: bool,
    data: dict[str, Any],
    message: str,
    validation: dict[str, Any],
    *,
    no_change_message: str | None = None,
) -> tuple[bool, dict[str, Any], str]:
    data["ordered_plan_diff"] = validation
    if not validation.get("available"):
        return success, data, message
    if not validation.get("passed"):
        data["reason"] = str(validation.get("reason") or "ordered_plan_diff_failed")
        return False, data, "这次方案调整已提交，但没有在当前方案里看到预期变化，请刷新方案后重新生成预览。"
    if validation.get("reason") == "sort_order_unchanged" and no_change_message:
        return success, data, no_change_message
    return success, data, message


async def _apply_plan_pending(
    ctx: RunContext[RequestContext],
    pending: dict[str, Any],
) -> tuple[bool, dict[str, Any], str]:
    execution_payload = _pending_execution_payload(pending)
    action_family = str(
        pending.get("action_family")
        or pending.get("actionFamily")
        or execution_payload.get("action_family")
        or execution_payload.get("actionFamily")
        or ""
    ).strip()
    payload = proposal_compiler.ensure_structured_plan_payload(execution_payload, action_family=action_family)
    if not proposal_compiler.is_structured_plan_payload(payload):
        return (
            False,
            {"reason": "missing_structured_plan_payload"},
            "这次方案调整缺少可执行结构，请重新生成预览后再确认。",
        )
    atomic = _first_atomic_action(payload)
    tenant_id = getattr(ctx.deps, "tenant_id", 1)
    diff_before: dict[str, Any] = {}
    if action_family in {"replace_units", "remove_units", "remove_ordered_unit", "move_unit", "move_ordered_unit", "sort_ordered_plan"}:
        diff_before = await _ordered_plan_snapshot_before_action(ctx)

    if action_family in {"generate_plan", "plan_generation"}:
        response = await internal_client.generate_planning_initial_plan(tenant_id, ctx.deps.sessionid)
        success = _is_success_response(response)
        return success, {"action_family": action_family, "backend_response": response}, (
            "已开始生成方案。" if success else "这次方案生成没有执行成功，请稍后重试。"
        )
    if action_family == "regenerate_order":
        response = await internal_client.generate_planning_ordered_plan(tenant_id, ctx.deps.sessionid)
        success = _is_success_response(response)
        return success, {"action_family": action_family, "backend_response": response}, (
            "已按当前候选重新生成排序方案。" if success else "这次方案重排没有执行成功，请稍后重试。"
        )
    if action_family == "add_units":
        volunteer_ids = _plan_volunteer_ids(payload, atomic)
        if not volunteer_ids:
            return False, {"reason": "missing_volunteer_ids"}, "这次添加方案缺少可执行的志愿标识，请重新生成预览。"
        select_response = await internal_client.select_working_plan_items(tenant_id, ctx.deps.sessionid, volunteer_ids)
        if not _is_success_response(select_response):
            return False, {"action_family": action_family, "backend_response": select_response}, "这次加入方案没有执行成功，请重新生成预览。"
        ordered_response = await internal_client.generate_planning_ordered_plan(tenant_id, ctx.deps.sessionid)
        success = _is_success_response(ordered_response)
        return success, {
            "action_family": action_family,
            "selected_volunteer_ids": volunteer_ids,
            "select_response": select_response,
            "backend_response": ordered_response,
        }, ("已加入所选志愿并刷新排序方案。" if success else "志愿已加入，但刷新排序方案失败，请稍后查看。")
    if action_family == "replace_units":
        unit_ids = _plan_unit_ids(payload, atomic)
        volunteer_ids = _plan_volunteer_ids(payload, atomic)
        if not unit_ids or not volunteer_ids:
            return False, {"reason": "missing_replace_args"}, "这次替换方案缺少要移出的志愿组或要加入的候选志愿，请重新生成预览。"
        remove_response = await internal_client.remove_planning_ordered_plan_units(tenant_id, ctx.deps.sessionid, unit_ids)
        if not _is_success_response(remove_response):
            return False, {"action_family": action_family, "backend_response": remove_response}, "这次替换中的移出操作没有执行成功，请重新生成预览。"
        select_response = await internal_client.select_working_plan_items(tenant_id, ctx.deps.sessionid, volunteer_ids)
        if not _is_success_response(select_response):
            return False, {
                "action_family": action_family,
                "remove_response": remove_response,
                "backend_response": select_response,
            }, "已移出原志愿组，但新候选加入失败，请查看当前方案后重新调整。"
        ordered_response = await internal_client.generate_planning_ordered_plan(tenant_id, ctx.deps.sessionid)
        success = _is_success_response(ordered_response)
        data = {
            "action_family": action_family,
            "unit_ids": unit_ids,
            "selected_volunteer_ids": volunteer_ids,
            "remove_response": remove_response,
            "select_response": select_response,
            "backend_response": ordered_response,
        }
        message = "已完成替换并刷新排序方案。" if success else "已完成替换，但刷新排序方案失败，请稍后查看。"
        if success:
            validation = _ordered_plan_diff_validation(
                action_family,
                before=diff_before,
                after=_ordered_plan_snapshot_from_response(ordered_response),
                unit_ids=unit_ids,
                volunteer_ids=volunteer_ids,
            )
            return _plan_apply_result_with_diff(success, data, message, validation)
        return success, data, message
    if action_family in {"remove_units", "remove_ordered_unit"}:
        unit_ids = _plan_unit_ids(payload, atomic)
        if not unit_ids:
            return False, {"reason": "missing_unit_ids"}, "这次移出方案缺少可执行的志愿组标识，请重新生成预览。"
        response = await internal_client.remove_planning_ordered_plan_units(tenant_id, ctx.deps.sessionid, unit_ids)
        success = _is_success_response(response)
        data = {"action_family": action_family, "unit_ids": unit_ids, "backend_response": response}
        message = f"已移出{len(unit_ids)}个志愿组。" if success else "这次移出方案没有执行成功，请重新生成预览。"
        if success:
            validation = _ordered_plan_diff_validation(
                action_family,
                before=diff_before,
                after=_ordered_plan_snapshot_from_response(response),
                unit_ids=unit_ids,
            )
            return _plan_apply_result_with_diff(success, data, message, validation)
        return success, data, message
    if action_family in {"move_unit", "move_ordered_unit"}:
        unit_ids = _plan_unit_ids(payload, atomic)
        target_position = _plan_target_position(payload, atomic)
        if not unit_ids or target_position <= 0:
            return False, {"reason": "missing_move_args"}, "这次移动方案缺少目标志愿或位置，请重新生成预览。"
        response = await internal_client.move_planning_ordered_plan_unit(
            tenant_id,
            ctx.deps.sessionid,
            unit_ids[0],
            target_position,
        )
        success = _is_success_response(response)
        data = {
            "action_family": action_family,
            "unit_id": unit_ids[0],
            "target_position": target_position,
            "backend_response": response,
        }
        message = f"已把该志愿组移动到第{target_position}位。" if success else "这次移动方案没有执行成功，请重新生成预览。"
        if success:
            validation = _ordered_plan_diff_validation(
                action_family,
                before=diff_before,
                after=_ordered_plan_snapshot_from_response(response),
                unit_ids=unit_ids,
                target_position=target_position,
            )
            return _plan_apply_result_with_diff(success, data, message, validation)
        return success, data, message
    if action_family == "sort_ordered_plan":
        sort_field = _plan_sort_field(payload, atomic)
        if not sort_field:
            return False, {"reason": "missing_sort_field"}, "这次排序缺少排序字段，请重新生成预览。"
        response = await internal_client.sort_planning_ordered_plan(tenant_id, ctx.deps.sessionid, sort_field)
        success = _is_success_response(response)
        data = {"action_family": action_family, "sort_field": sort_field, "backend_response": response}
        message = "已按要求重新排序方案。" if success else "这次排序没有执行成功，请重新生成预览。"
        if success:
            validation = _ordered_plan_diff_validation(
                action_family,
                before=diff_before,
                after=_ordered_plan_snapshot_from_response(response),
            )
            return _plan_apply_result_with_diff(
                success,
                data,
                message,
                validation,
                no_change_message="这次排序后顺序没有变化，当前方案可能已经符合这个排序。",
            )
        return success, data, message

    return False, {"reason": "unsupported_action_family", "action_family": action_family}, "这类待确认方案操作还不能由新工具执行，请重新生成预览。"


async def preview_intent_change(
    ctx: RunContext[RequestContext],
    intent_type: IntentType,
    positive: dict[str, Any] | None = None,
    negative: dict[str, Any] | None = None,
    constraint_type: ConstraintType = "exclude",
    apply_to_current_plan: bool = True,
    pending_resolution: PendingResolution = "none",
    raw_user_text: str = "",
    semantic_requirements: list[dict[str, Any]] | None = None,
) -> str:
    """Preview a model-interpreted include/exclude user requirement.

    The model must decide the domain and polarity before calling this tool. The
    tool normalizes structured payloads and checks them against
    semantic_requirements; it does not infer extra requirements from raw_user_text.

    Args:
        intent_type: Domain being changed. Must be major, school, region, career, or tuition_budget.
        positive: Things the user explicitly wants, keeps, or requires.
        negative: Things the user explicitly rejects. Use this for phrases like
            "不要X", "排除X", "不考虑X", and "避开X".
        constraint_type: use exclude for direct rejection, only_keep for "只看/只保留X",
            and must_have for "要/必须有/至少有X".
        apply_to_current_plan: True means confirming this pending should immediately
            refresh the current plan if one exists. False means confirming only
            records the requirement for future generation/adjustment.
        pending_resolution: Required when the turn starts with an active pending
            operation and this call creates a new preview. Use replace_active_pending
            when the user abandons the active pending item, append_to_active_pending
            when the new requirement should be merged into an active intent preview,
            or hold_new_request when the relationship is not clear enough to create
            another pending item.
        raw_user_text: The original user message. Used only to warn when the
            tool call appears to omit a negative side; do not rely on it to fill
            entities.
        semantic_requirements: Model-interpreted requirement/reference items from
            this turn. Each item should include domain, side, strength, key, values,
            and raw_span when available. Use strength=explicit or confirmable for
            items that should be included in the pending preview; use
            strength=reference for "优先/倾向/重点关注/参考方向" items that should not
            be forced into the payload. Attribute completion only uses this
            structured list, never raw_user_text scanning.
    """
    normalized_type = str(intent_type or "").strip().lower()
    if normalized_type not in {"major", "school", "region", "career", "tuition_budget"}:
        return _json(
            {
                "data": {
                    "intent_type": intent_type,
                    "allowed_intent_types": ["major", "school", "region", "career", "tuition_budget"],
                },
                "next_step": "clarify",
                "message": "需要说明这是专业、院校、地域、发展方向还是学费预算要求。",
            }
        )
    normalized_constraint = str(constraint_type or "exclude").strip() or "exclude"
    if normalized_constraint not in {"exclude", "only_keep", "must_have"}:
        normalized_constraint = "exclude"

    batch = ctx.deps.batch or "01"
    effective_raw_user_text = _effective_raw_user_text(ctx, raw_user_text)
    positive_payload, positive_ambiguities, positive_display_aliases = _normalize_intent_side(
        normalized_type, positive, batch=batch
    )
    negative_payload, negative_ambiguities, negative_display_aliases = _normalize_intent_side(
        normalized_type, negative, batch=batch
    )
    display_aliases = _merge_display_aliases(positive_display_aliases, negative_display_aliases)
    normalized = {
        "positive": positive_payload,
        "negative": negative_payload,
    }
    if normalized_type == "major":
        normalized = _refine_major_payload_by_user_text(
            normalized,
            raw_user_text=effective_raw_user_text,
            batch=batch,
        )
    parameter_warnings: list[str] = []
    ambiguities = positive_ambiguities + negative_ambiguities
    if ambiguities:
        first = ambiguities[0]
        options = "、".join(str(item.get("name") or "") for item in first.get("candidates", []) if item.get("name"))
        return _json(
            {
                "data": {
                    "intent_type": normalized_type,
                    "constraint_type": normalized_constraint,
                    "normalized": normalized,
                    "ambiguities": ambiguities,
                },
                "next_step": "clarify",
                "message": f"“{first.get('raw_text')}”有多个可能含义：{options}。需要先确认你指哪一个。",
            }
        )

    merged = _merge_merged_intents(
        _merged_intents_from_normalized(normalized_type, normalized),
        _structured_cross_domain_attributes_from_payloads(
            normalized_type,
            positive=positive,
            negative=negative,
        ),
    )
    if display_aliases:
        merged["_display_aliases"] = display_aliases
    attribute_completion_candidates = _semantic_attribute_completion_candidates(
        normalized_type,
        merged,
        semantic_requirements=semantic_requirements,
        batch=batch,
        raw_user_text=effective_raw_user_text,
    )
    if attribute_completion_candidates:
        return _json(
            _intent_change_requires_attribute_completion_payload(
                reason="intent_change_requires_attribute_completion",
                intent_type=normalized_type,
                constraint_type=normalized_constraint,
                requested_text=effective_raw_user_text,
                normalized=normalized,
                merged=merged,
                missing_attributes=attribute_completion_candidates,
            )
        )
    replaced_active_pending = False
    merged_existing_pending = False
    if not _merged_intents_have_values(merged):
        if effective_raw_user_text and not semantic_requirements:
            return _json(
                _intent_change_requires_semantic_requirements_payload(
                    intent_type=normalized_type,
                    constraint_type=normalized_constraint,
                    requested_text=effective_raw_user_text,
                    normalized=normalized,
                    merged=merged,
                )
            )
        reference_summary = _semantic_reference_summary(semantic_requirements)
        if reference_summary:
            return _json(
                {
                    "data": {
                        "intent_type": normalized_type,
                        "constraint_type": normalized_constraint,
                        "normalized": normalized,
                        "merged": merged,
                        "apply_to_current_plan": bool(apply_to_current_plan),
                        "parameter_warnings": parameter_warnings,
                        "pending_created": False,
                        "requires_confirmation": False,
                        "reason": "reference_only_semantic_requirements",
                    },
                    "next_step": "respond",
                    "message": (
                        f"这次我先按参考方向理解：{reference_summary}。"
                        "不会直接写入报考要求，也不会改动当前方案；如果要正式采纳，可以再明确说要把这些作为报考要求。"
                    ),
                }
            )
        message = "这次没有识别到明确的报考要求，请补充要或不要的对象。"
        return _json(
            {
                "data": {
                    "intent_type": normalized_type,
                    "constraint_type": normalized_constraint,
                    "normalized": normalized,
                    "merged": merged,
                    "merged_existing_pending": merged_existing_pending,
                    "replaced_active_pending": replaced_active_pending,
                    "apply_to_current_plan": bool(apply_to_current_plan),
                    "parameter_warnings": parameter_warnings,
                    "pending_created": False,
                    "requires_confirmation": False,
                    "reason": "empty_intent_payload",
                },
                "next_step": "clarify",
                "message": message,
            }
        )
    normalized_pending_resolution = _normalize_pending_resolution(pending_resolution)
    active_pending = _turn_started_active_pending(ctx)
    if active_pending is not None:
        if normalized_pending_resolution == "none":
            return _json(
                _pending_resolution_required_payload(
                    ctx,
                    requested_kind="intent_change",
                    requested_action_family="apply_selected_intents",
                    requested_text=effective_raw_user_text,
                )
            )
        if normalized_pending_resolution == "hold_new_request":
            active_pending_conflict = _active_pending_conflict_payload(
                ctx,
                requested_kind="intent_change",
                requested_action_family="apply_selected_intents",
                requested_text=effective_raw_user_text,
            )
            if active_pending_conflict is not None:
                return _json(active_pending_conflict)
        elif normalized_pending_resolution == "replace_active_pending":
            replaced_active_pending = await _replace_active_pending_for_new_preview(ctx)
        elif normalized_pending_resolution == "append_to_active_pending":
            existing_payload = _active_intent_pending_execution_payload(ctx)
            merged, normalized_constraint, merged_existing_pending = _merge_with_intent_pending_payload(
                existing_payload,
                merged=merged,
                constraint_type=normalized_constraint,
            )
            if not merged_existing_pending:
                return _json(
                    _active_pending_append_unsupported_payload(
                        ctx,
                        requested_kind="intent_change",
                        requested_action_family="apply_selected_intents",
                        requested_text=effective_raw_user_text,
                    )
                )
            if isinstance(existing_payload, dict):
                apply_to_current_plan = bool(apply_to_current_plan) and _apply_to_current_plan_from_execution_payload(
                    existing_payload
                )
            pending = await _pending_data(ctx)
            kind = str(pending.get("kind") or "").strip()
            action_family = str(pending.get("action_family") or pending.get("actionFamily") or "").strip()
            await _mark_pending_status(ctx, pending, "cancelled", resultCode="merged_into_new_preview")
            _invalidate_after_pending_action(ctx, kind, action_family)
            _clear_context_pending(ctx)
    else:
        merged, normalized_constraint, merged_existing_pending = _merge_with_active_intent_pending(
            ctx,
            merged=merged,
            constraint_type=normalized_constraint,
        )
    active_execution_payload = _active_intent_pending_execution_payload(ctx)
    if isinstance(active_execution_payload, dict):
        apply_to_current_plan = bool(apply_to_current_plan) and _apply_to_current_plan_from_execution_payload(
            active_execution_payload
        )
    normalized_constraint = _combined_constraint_type(
        existing=normalized_constraint if merged_existing_pending else "",
        current=normalized_constraint,
        merged=merged,
    )
    merged = _canonicalize_merged_intents_for_constraint(
        merged,
        constraint_type=normalized_constraint,
    )
    display_aliases = _merge_display_aliases(
        display_aliases,
        _major_display_aliases_from_user_text(
            merged,
            effective_raw_user_text,
            batch=batch,
        ),
    )
    if display_aliases:
        merged["_display_aliases"] = display_aliases
    display_aliases = _display_aliases_from_merged(merged, display_aliases)
    summary = _intent_summary_from_merged(merged, display_aliases)

    plan_impact = await _preview_plan_impact(
        ctx,
        normalized_type,
        normalized,
        normalized_constraint,
    )
    pending_result = await _create_intent_pending(
        ctx,
        intent_type=normalized_type,
        constraint_type=normalized_constraint,
        normalized=normalized,
        plan_impact=plan_impact,
        apply_to_current_plan=bool(apply_to_current_plan),
        merged_override=merged,
        summary_override=summary,
    )
    message = _preview_message_from_merged(merged, display_aliases)
    affected_count = _as_int(plan_impact.get("affected_count"))
    if affected_count > 0:
        if apply_to_current_plan:
            message += f" 当前方案里初步看到{affected_count}个相关志愿，采纳后会按这个要求重新调整方案。"
        else:
            message += f" 当前方案里初步看到{affected_count}个相关志愿；采纳后会先记为报考要求，这次不改当前方案。"
    elif not apply_to_current_plan:
        message += " 采纳后会先记为报考要求，这次不改当前方案。"
    if not pending_result.get("created"):
        message += " 但这次待确认状态没有保存成功，请稍后重新生成预览。"
    return _json(
        {
            "data": {
                "intent_type": normalized_type,
                "constraint_type": normalized_constraint,
                "normalized": normalized,
                "merged": merged,
                "merged_existing_pending": merged_existing_pending,
                "replaced_active_pending": replaced_active_pending,
                "plan_impact": plan_impact,
                "apply_to_current_plan": bool(apply_to_current_plan),
                "parameter_warnings": parameter_warnings,
                "pending_id": pending_result.get("pending_id"),
                "pending_version": pending_result.get("pending_version"),
                "pending_created": bool(pending_result.get("created")),
                "requires_confirmation": bool(pending_result.get("created")),
            },
            "next_step": "confirm" if pending_result.get("created") else "respond",
            "message": message,
        }
    )


def _intent_fallback_from_plan_filters(filters: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(filters, dict) or not filters:
        return {}

    negative_school: dict[str, list[str]] = {}
    negative_region: dict[str, list[str]] = {}
    negative_major: dict[str, list[str]] = {}

    def add(target: dict[str, list[str]], key: str, values: Any) -> None:
        bucket = target.setdefault(key, [])
        for value in _as_list(values):
            text = str(value or "").strip()
            if text and text not in bucket:
                bucket.append(text)

    for key, value in filters.items():
        normalized_key = str(key or "").strip()
        if normalized_key in {"school_nature", "schoolNature"}:
            add(negative_school, "school_nature", value)
        elif normalized_key in {"program_type", "programType", "enrollment_type", "enrollmentType"}:
            add(negative_school, "program_type", value)
        elif normalized_key in {"school_category", "schoolCategory"}:
            add(negative_school, "school_category", value)
        elif normalized_key in {"school_level", "schoolLevel"}:
            add(negative_school, "school_level", value)
        elif normalized_key in {"school_tag", "schoolTag"}:
            add(negative_school, "school_tag", value)
        elif normalized_key in {"tuition_level", "tuitionLevel"}:
            values = {str(item).strip().lower() for item in _as_list(value)}
            if values & {"high", "高", "高收费", "expensive"}:
                add(negative_school, "program_type", ["高收费"])
        elif normalized_key in {"tuition_min", "tuitionMin"} and _as_int(value) >= 20000:
            add(negative_school, "program_type", ["高收费"])
        elif normalized_key in {"province", "province_name", "provinceName"}:
            add(negative_region, "province", value)
        elif normalized_key in {"city", "city_name", "cityName"}:
            add(negative_region, "city", value)
        elif normalized_key in {"region", "region_group", "regionGroup"}:
            add(negative_region, "region_group", value)
        elif normalized_key in {"major", "major_name", "majorName"}:
            add(negative_major, "major", value)
        elif normalized_key in {"level1", "major_discipline", "majorDiscipline"}:
            add(negative_major, "level1", value)
        elif normalized_key in {"level2", "major_category", "majorCategory"}:
            add(negative_major, "level2", value)
        elif normalized_key in {"major_tag", "majorTag", "duration"}:
            add(negative_major, "major_tag", value)

    if negative_school:
        return {"intent_type": "school", "negative": negative_school}
    if negative_region:
        return {"intent_type": "region", "negative": negative_region}
    if negative_major:
        return {"intent_type": "major", "negative": negative_major}
    return {}


async def preview_plan_action(
    ctx: RunContext[RequestContext],
    action: PlanAction,
    targets: list[str] | None = None,
    target_position: int | None = None,
    filters: dict[str, Any] | None = None,
    replacement_spec: dict[str, Any] | None = None,
    pending_resolution: PendingResolution = "none",
    raw_user_text: str = "",
    review_issue_code: ReviewIssueCode | None = None,
) -> str:
    """Preview a concrete current-plan mutation and create a structured pending operation.

    Use this for explicit plan changes, including requests to remove or replace
    items found by plan review. When the user says "审查里的高收费项", pass
    `review_issue_code="high_tuition"`; for "中外合作" review issues, pass
    `review_issue_code="cooperative_program"`. This tool only creates a
    confirmation preview; it does not apply the change until `confirm_pending`.
    For replace actions without explicit candidate targets, pass
    replacement_spec to describe the replacement direction, for example
    {"improve_dims":["tuition_decrease"],"exclude_markers":["high_tuition"]}.
    When the turn starts with an active pending operation, pass pending_resolution
    to describe whether this preview replaces the active pending item or should
    be held until the user handles it.
    """
    raw_user_text = _effective_raw_user_text(ctx, raw_user_text)
    normalized_action = str(action or "").strip().lower()
    if normalized_action not in set(_ALLOWED_PLAN_ACTIONS):
        return _json(_plan_action_requires_explicit_action_payload(action=action, requested_text=raw_user_text))

    summary = await _plan_summary_data(ctx)
    has_plan = bool(summary.get("has_plan"))
    normalized_filters = filters if isinstance(filters, dict) else {}
    kind, action_family = _plan_action_family(normalized_action)
    replaced_active_pending = False
    normalized_pending_resolution = _normalize_pending_resolution(pending_resolution)
    if _turn_started_active_pending(ctx) is not None:
        if normalized_pending_resolution == "none":
            return _json(
                _pending_resolution_required_payload(
                    ctx,
                    requested_kind=kind,
                    requested_action_family=action_family,
                    requested_text=raw_user_text,
                )
            )
        if normalized_pending_resolution == "hold_new_request":
            active_pending_conflict = _active_pending_conflict_payload(
                ctx,
                requested_kind=kind,
                requested_action_family=action_family,
                requested_text=raw_user_text,
            )
            if active_pending_conflict is not None:
                return _json(active_pending_conflict)
        elif normalized_pending_resolution == "replace_active_pending":
            replaced_active_pending = await _replace_active_pending_for_new_preview(ctx)
        elif normalized_pending_resolution == "append_to_active_pending":
            return _json(
                _active_pending_append_unsupported_payload(
                    ctx,
                    requested_kind=kind,
                    requested_action_family=action_family,
                    requested_text=raw_user_text,
                )
            )
    label = _action_label(normalized_action)

    unit_ids: list[str] = []
    volunteer_ids: list[str] = []
    affected_items: list[dict[str, Any]] = []
    affected_scope = ""
    count = 0
    review_issue_meta: dict[str, Any] | None = None

    if normalized_action == "pin_lock":
        if not has_plan:
            return _json(
                {
                    "data": {"action": "pin_lock", "has_plan": False, "reason": "no_plan"},
                    "next_step": "respond",
                    "message": "当前还没有正式方案，不能锁定方案位置。可以先生成方案。",
                }
            )
        resolved, missing, reason = await _resolve_plan_targets(ctx, targets, source="plan")
        return _json(
            {
                "data": {
                    "action": "pin_lock",
                    "action_family": "pin_or_lock_unit",
                    "targets": targets or [],
                    "unit_ids": [_item_unit_id(item) for item in resolved if _item_unit_id(item)],
                    "missing_targets": missing,
                    "reason": "unsupported_action" if reason == "ok" and resolved else reason,
                    "requires_confirmation": False,
                    "pending_created": False,
                },
                "next_step": "respond",
                "message": "这次是锁定/固定当前方案位置的动作。当前新工具还没有可执行的锁定接口，所以不会创建确认卡，也不会改动方案。可以先查看这些位置，或改用已支持的移动、移出、替换、重排。",
            }
        )

    if normalized_action in {"remove", "move"}:
        if not has_plan:
            if normalized_action == "remove":
                intent_fallback = _intent_fallback_from_plan_filters(normalized_filters)
                if intent_fallback:
                    fallback_intent_type = str(intent_fallback.get("intent_type") or "").strip()
                    fallback_negative = (
                        intent_fallback.get("negative")
                        if isinstance(intent_fallback.get("negative"), dict)
                        else {}
                    )
                    if fallback_intent_type not in {"school", "region", "major", "career"} or not fallback_negative:
                        return _json(
                            {
                                "data": {
                                    "action": normalized_action,
                                    "has_plan": False,
                                    "filters": normalized_filters,
                                    "intent_fallback": intent_fallback,
                                    "pending_created": False,
                                    "requires_confirmation": False,
                                    "reason": "invalid_requirement_fallback",
                                },
                                "next_step": "respond",
                                "message": "当前还没有正式方案，不能移出具体方案项；这次筛选条件也不能稳定转成报考要求。",
                            }
                        )
                    fallback_result = await preview_intent_change(
                        ctx,
                        intent_type=fallback_intent_type,
                        negative=fallback_negative,
                        constraint_type="exclude",
                        raw_user_text=raw_user_text,
                    )
                    try:
                        fallback_payload = json.loads(fallback_result)
                    except (TypeError, json.JSONDecodeError):
                        fallback_payload = {}
                    if isinstance(fallback_payload, dict):
                        data = fallback_payload.get("data")
                        if not isinstance(data, dict):
                            data = {}
                            fallback_payload["data"] = data
                        data["source"] = "preview_plan_action_requirement_fallback"
                        data["action"] = normalized_action
                        data["has_plan"] = False
                        data["filters"] = normalized_filters
                        data["intent_fallback"] = intent_fallback
                        data["reason"] = "no_plan_attribute_action_as_requirement"
                        data.setdefault("action_family", "apply_selected_intents")
                        fallback_payload["action_family"] = "apply_selected_intents"
                        fallback_payload["message"] = (
                            str(fallback_payload.get("message") or "").strip()
                            or "当前还没有正式方案，已先把这句话里的属性筛选整理成报考要求待确认预览。"
                        )
                        return _json(fallback_payload)
                    return fallback_result
            return _json(
                {
                    "data": {"action": normalized_action, "has_plan": False},
                    "next_step": "respond",
                    "message": "当前还没有正式方案，不能预览移出或移动操作。可以先生成方案。",
                }
            )
        if not _as_list(targets) and review_issue_code and normalized_action == "remove":
            issue, resolved, reason = await _review_issue_action_target(ctx, review_issue_code)
            missing = [] if reason in {"ok", "review_issue_units_not_in_plan"} else [str(review_issue_code)]
            if issue:
                review_issue_meta = _review_issue_target_meta(issue)
            if reason == "ok" and normalized_filters:
                resolved, normalized_filters, reason = _filter_resolved_plan_items(ctx, resolved, normalized_filters)
                missing = [] if reason == "ok" else [_describe_filters(normalized_filters)]
        elif not _as_list(targets) and normalized_filters and normalized_action == "remove":
            resolved, normalized_filters, reason = await _resolve_plan_filter_targets(ctx, normalized_filters)
            missing = [] if reason == "ok" else [_describe_filters(normalized_filters)]
        elif not _as_list(targets) and normalized_filters and normalized_action == "move":
            resolved, normalized_filters, reason = await _resolve_plan_filter_selector_target(
                ctx,
                normalized_filters,
            )
            missing = [] if reason == "ok" else [_describe_filters(normalized_filters)]
        else:
            resolved, missing, reason = await _resolve_plan_targets(ctx, targets, source="plan")
        if reason == "filter_no_match":
            return _json(
                {
                    "data": {
                        "action": normalized_action,
                        "targets": targets or [],
                        "filters": normalized_filters,
                        "review_issue_code": review_issue_code or "",
                        "missing_targets": [],
                        "reason": reason,
                    },
                    "next_step": "respond",
                    "message": f"当前方案里没有命中“{_describe_filters(normalized_filters)}”的志愿，不需要移出。",
                }
            )
        if reason == "ambiguous_selector":
            if normalized_action == "move" and raw_user_text:
                return _json(
                    _plan_action_requires_move_parameters_payload(
                        reason="plan_action_requires_move_selector",
                        requested_text=raw_user_text,
                        targets=targets,
                        filters=normalized_filters,
                        target_position=target_position,
                    )
                )
            return _json(
                {
                    "data": {
                        "action": normalized_action,
                        "targets": targets or [],
                        "filters": normalized_filters,
                        "review_issue_code": review_issue_code or "",
                        "missing_targets": [],
                        "reason": reason,
                    },
                    "next_step": "clarify",
                    "message": "当前范围里有多个志愿，需要说明按什么选择（如录取率最高、学费最低、最后一个等）。",
                }
            )
        if reason != "ok" or missing or not resolved:
            return _json(
                {
                    "data": {
                        "action": normalized_action,
                        "targets": targets or [],
                        "filters": normalized_filters,
                        "review_issue_code": review_issue_code or "",
                        "missing_targets": missing,
                        "reason": reason,
                    },
                    "next_step": "clarify",
                    "message": f"还没有唯一定位到要调整的方案项：{'、'.join(missing or targets or []) or raw_user_text or '未指定目标'}。请说明学校、专业或第几个志愿。",
                }
            )
        unit_ids = [_item_unit_id(item) for item in resolved if _item_unit_id(item)]
        affected_items = [_plan_item_brief(item) for item in resolved if item]
        count = len(unit_ids)
        affected_scope = "；".join(_plan_item_snippet(item) for item in resolved[:5])
        if normalized_filters and normalized_action == "remove" and not _as_list(targets) and not review_issue_meta:
            affected_scope = f"{_describe_filters(normalized_filters)}：{affected_scope}"
        if review_issue_meta:
            affected_scope = f"审查问题 {review_issue_meta.get('code')}：{affected_scope}"
        if normalized_action == "move":
            resolved_position, target_filters, position_reason = await _plan_items_for_target_position(
                ctx,
                target_position,
                normalized_filters,
            )
            if target_filters:
                normalized_filters = {**normalized_filters, **target_filters}
            target_position = resolved_position
        if normalized_action == "move" and _as_int(target_position) <= 0:
            if raw_user_text:
                return _json(
                    _plan_action_requires_move_parameters_payload(
                        reason="plan_action_requires_move_target_position",
                        requested_text=raw_user_text,
                        targets=targets,
                        filters=normalized_filters,
                        target_position=target_position,
                        unit_ids=unit_ids,
                    )
                )
            return _json(
                {
                    "data": {
                        "action": "move",
                        "targets": targets or [],
                        "unit_ids": unit_ids,
                        "reason": position_reason if "position_reason" in locals() else "missing_target_position",
                    },
                    "next_step": "clarify",
                    "message": "已经定位到要移动的方案项，还需要说明要移动到第几位。",
                }
            )

    elif normalized_action == "add":
        resolved, missing, reason = await _resolve_plan_targets(ctx, targets, source="candidates")
        if reason != "ok" or missing or not resolved:
            return _json(
                {
                    "data": {
                        "action": "add",
                        "targets": targets or [],
                        "missing_targets": missing,
                        "reason": reason,
                    },
                    "next_step": "clarify",
                    "message": "还没有唯一定位到要加入的候选志愿，请说明候选里的学校和专业。",
                }
            )
        volunteer_ids = [_item_volunteer_id(item) for item in resolved if _item_volunteer_id(item)]
        affected_items = [_plan_item_brief(item) for item in resolved if item]
        count = len(volunteer_ids)
        affected_scope = "；".join(_plan_item_snippet(item) for item in resolved[:5])

    elif normalized_action == "replace":
        candidate_targets = _as_list(
            normalized_filters.get("candidates")
            or normalized_filters.get("candidate_targets")
            or normalized_filters.get("candidateTargets")
        )
        explicit_replacement_spec = (
            replacement_spec
            if isinstance(replacement_spec, dict)
            else normalized_filters.get("replacement_spec") or normalized_filters.get("replacementSpec")
        )
        replacement_filter_input = {
            str(key): value
            for key, value in normalized_filters.items()
            if str(key or "").strip()
            not in {"candidates", "candidate_targets", "candidateTargets", "replacement_spec", "replacementSpec"}
        }
        old_filter_payload: dict[str, Any] = {}
        if not _as_list(targets) and review_issue_code:
            issue, old_resolved, old_reason = await _review_issue_action_target(ctx, review_issue_code)
            old_missing = [] if old_reason in {"ok", "review_issue_units_not_in_plan"} else [str(review_issue_code)]
            if issue:
                review_issue_meta = _review_issue_target_meta(issue)
            if old_reason == "ok" and replacement_filter_input:
                old_resolved, old_filter_payload, old_reason = _filter_resolved_plan_items(
                    ctx,
                    old_resolved,
                    replacement_filter_input,
                )
                old_missing = [] if old_reason == "ok" else [_describe_filters(old_filter_payload)]
            elif old_reason != "ok":
                fallback_filter_input = replacement_filter_input or _review_issue_fallback_filters(review_issue_code)
                if fallback_filter_input:
                    old_resolved, old_filter_payload, old_reason = await _resolve_plan_filter_targets(
                        ctx,
                        fallback_filter_input,
                    )
                    old_missing = [] if old_reason == "ok" else [_describe_filters(old_filter_payload)]
        elif not _as_list(targets) and replacement_filter_input:
            old_resolved, old_filter_payload, old_reason = await _resolve_plan_filter_targets(ctx, replacement_filter_input)
            old_missing = [] if old_reason == "ok" else [_describe_filters(old_filter_payload)]
        else:
            old_resolved, old_missing, old_reason = await _resolve_plan_targets(ctx, targets, source="plan")
        if old_filter_payload:
            normalized_filters = {**old_filter_payload}
            if candidate_targets:
                normalized_filters["candidate_targets"] = candidate_targets
        elif candidate_targets:
            normalized_filters = {"candidate_targets": candidate_targets}
        replacement_spec = _build_replacement_spec(
            review_issue_code=review_issue_code,
            explicit_spec=explicit_replacement_spec,
            filters=old_filter_payload or replacement_filter_input,
            old_items=old_resolved if old_reason == "ok" else [],
        )
        auto_select_reason = _replacement_auto_select_reason(replacement_spec)
        if candidate_targets:
            new_resolved, new_missing, new_reason = await _resolve_plan_targets(ctx, candidate_targets, source="candidates")
        elif old_reason == "ok" and old_resolved:
            new_resolved, new_reason = await _auto_select_replacement_candidates(ctx, old_resolved, replacement_spec)
            direction_summary = _replacement_spec_direction_summary(replacement_spec)
            new_missing = [] if new_reason == "ok" else [direction_summary or "替换方向"]
            if new_reason == "ok":
                normalized_filters = {
                    **normalized_filters,
                    "auto_selected_candidates": True,
                    "auto_select_reason": auto_select_reason,
                    "replacement_spec": replacement_spec,
                }
        else:
            new_resolved, new_missing, new_reason = [], [], "missing_old_items"
        old_target_unresolved = old_reason != "ok" or old_missing or not old_resolved
        if (
            old_target_unresolved
            and raw_user_text
            and _consume_structured_retry_budget(ctx, "preview_plan_action.replace.old_target")
        ):
            return _json(
                _plan_action_requires_replace_targets_payload(
                    requested_text=raw_user_text,
                    targets=targets,
                    filters=normalized_filters,
                    review_issue_code=review_issue_code,
                    candidate_targets=candidate_targets,
                    replacement_spec=replacement_spec,
                    missing_targets=old_missing,
                    source_reason=old_reason,
                )
            )
        if old_target_unresolved or new_reason != "ok" or new_missing or not new_resolved:
            if old_reason == "ok" and old_resolved and new_reason == "replacement_spec_missing":
                message = "已经定位到要替换的方案项，但还没听清要换成什么方向：更便宜、层次更高，还是换个城市？"
            elif old_reason == "ok" and old_resolved and not candidate_targets:
                direction_summary = _replacement_spec_direction_summary(replacement_spec)
                direction_text = f"满足“{direction_summary}”方向的" if direction_summary else "合适的"
                message = (
                    f"已经定位到要替换的方案项，但同档位候选里暂时没有找到{direction_text}候选志愿。"
                    "可以放宽到相邻档位，或说明换个专业方向。"
                )
            elif old_target_unresolved:
                message = "还没有唯一定位到要移出的当前方案项，请说明学校、专业或第几个志愿。"
            else:
                message = "替换需要同时唯一定位要移出的当前方案项和要加入的候选志愿。"
            return _json(
                {
                    "data": {
                        "action": "replace",
                        "targets": targets or [],
                        "review_issue_code": review_issue_code or "",
                        "filters": normalized_filters,
                        "candidate_targets": candidate_targets,
                        "replacement_spec": replacement_spec,
                        "missing_targets": old_missing + new_missing,
                        "reason": old_reason if old_reason != "ok" else new_reason,
                    },
                    "next_step": "clarify",
                    "message": message,
                }
            )
        unit_ids = [_item_unit_id(item) for item in old_resolved if _item_unit_id(item)]
        volunteer_ids = [_item_volunteer_id(item) for item in new_resolved if _item_volunteer_id(item)]
        affected_items = [_plan_item_brief(item) for item in old_resolved + new_resolved if item]
        count = len(unit_ids) + len(volunteer_ids)
        affected_scope = "移出：" + "；".join(_plan_item_snippet(item) for item in old_resolved[:3])
        affected_scope += "；加入：" + "；".join(_plan_item_snippet(item) for item in new_resolved[:3])
        if review_issue_meta:
            affected_scope = f"审查问题 {review_issue_meta.get('code')}：" + affected_scope

    elif normalized_action == "sort":
        if not has_plan:
            return _json(
                {
                    "data": {"action": "sort", "has_plan": False},
                    "next_step": "respond",
                    "message": "当前还没有正式方案，不能预览排序操作。可以先生成方案。",
                }
            )
        if review_issue_code:
            issue = await _review_issue_by_code(ctx, review_issue_code)
            if not issue:
                return _json(
                    {
                        "data": {
                            "action": "sort",
                            "review_issue_code": review_issue_code or "",
                            "reason": "review_issue_not_found",
                        },
                        "next_step": "clarify",
                        "message": "还没有找到对应的审查问题，请先审查方案或说明要处理的具体问题。",
                    }
                )
            review_issue_meta = _review_issue_target_meta(issue)
        sort_field = str(
            normalized_filters.get("sort_field")
            or normalized_filters.get("sortField")
            or normalized_filters.get("field")
            or "admission_ratio"
        ).strip()
        backend_sort_field = _normalize_plan_action_sort_field(sort_field)
        if not backend_sort_field:
            return _json(
                {
                    "data": {
                        "action": "sort",
                        "review_issue_code": review_issue_code or "",
                        "filters": normalized_filters,
                        "sort_field": sort_field,
                        "supported_sort_fields": ["admission_ratio", "school_rank", "comprehensive"],
                        "reason": "unsupported_sort_field",
                    },
                    "next_step": "clarify",
                    "message": "当前方案排序支持按录取率、院校排名或综合分处理；学校层次这类标签暂时不能单独作为排序字段。可以改为按院校排名或综合分重新排序。",
                }
            )
        normalized_filters = {
            **normalized_filters,
            "sort_field": backend_sort_field,
            "requested_sort_field": sort_field,
        }
        sort_label = _plan_action_sort_field_label(backend_sort_field)
        if review_issue_meta:
            normalized_filters["review_issue_code"] = review_issue_meta.get("code")
            affected_scope = f"围绕审查问题 {review_issue_meta.get('code')}，按{sort_label}重新排序当前方案"
        else:
            affected_scope = f"按{sort_label}重新排序当前方案"
        count = _as_int(summary.get("ordered_total"))

    elif normalized_action in {"generate", "regenerate_order"}:
        if review_issue_code:
            issue = await _review_issue_by_code(ctx, review_issue_code)
            if not issue:
                return _json(
                    {
                        "data": {
                            "action": normalized_action,
                            "review_issue_code": review_issue_code or "",
                            "reason": "review_issue_not_found",
                        },
                        "next_step": "clarify",
                        "message": "还没有找到对应的审查问题，请先审查方案或说明要处理的具体问题。",
                    }
                )
            review_issue_meta = _review_issue_target_meta(issue)
            normalized_filters = {
                **normalized_filters,
                "review_issue_code": review_issue_meta.get("code"),
            }
        if normalized_action == "generate":
            affected_scope = "生成新的正式方案"
        elif review_issue_meta:
            affected_scope = f"围绕审查问题 {review_issue_meta.get('code')}，基于当前候选重新生成排序方案"
        else:
            affected_scope = "基于当前候选重新生成排序方案"
        count = _as_int(summary.get("ordered_total") or summary.get("ordered_target_total"))

    payload = _plan_pending_payload(
        action_family,
        unit_ids=unit_ids,
        volunteer_ids=volunteer_ids,
        target_position=_as_int(target_position),
        sort_field=str(normalized_filters.get("sort_field") or "").strip(),
        filters=normalized_filters,
        raw_user_text=raw_user_text,
        review_issue=review_issue_meta,
    )
    plan_impact = _plan_impact_for_action(action_family, summary, count)
    plan_impact["affected_items"] = affected_items[:8]
    preview_summary = f"{label}：{affected_scope or '按你的要求调整当前方案'}。确认前不会生效。"
    pending_result = await _create_plan_pending(
        ctx,
        kind=kind,
        action_family=action_family,
        summary=preview_summary,
        payload=payload,
        affected_scope=affected_scope,
        plan_impact=plan_impact,
    )
    message = preview_summary
    if pending_result.get("created"):
        message += " 确认后我会执行这次方案调整。"
    else:
        message += " 但这次待确认状态没有保存成功，请稍后重新生成预览。"
    return _json(
        {
            "data": {
                "action": normalized_action,
                "kind": kind,
                "action_family": action_family,
                "targets": targets or [],
                "review_issue_code": review_issue_code or "",
                "review_issue_target": review_issue_meta or {},
                "target_position": _as_int(target_position),
                "execution_payload": payload,
                "plan_impact": plan_impact,
                "replaced_active_pending": replaced_active_pending,
                "pending_id": pending_result.get("pending_id"),
                "pending_version": pending_result.get("pending_version"),
                "pending_created": bool(pending_result.get("created")),
                "requires_confirmation": bool(pending_result.get("created")),
            },
            "next_step": "confirm" if pending_result.get("created") else "respond",
            "message": message,
        }
    )


async def query_plan(
    ctx: RunContext[RequestContext],
    scope: PlanScope = "plan",
    filters: dict[str, Any] | None = None,
) -> str:
    """Query current plan facts or a compact plan summary without changing state."""
    normalized_scope = str(scope or "plan").strip().lower() or "plan"
    raw_user_text = _latest_user_text(ctx)
    normalized_filters, limit = _normalize_plan_query_filters(filters if isinstance(filters, dict) else {})
    query_filters, query_controls = _extract_plan_query_controls(normalized_filters)
    summary = await _plan_summary_data(ctx)
    if not summary.get("has_plan"):
        no_plan_message = summary.get("guidance") or "当前还没有生成正式方案。"
        if query_filters:
            description = _describe_filters(query_filters)
            no_plan_message = f"当前还没有生成正式方案，暂时无法判断方案里是否有“{description}”。"
        return _json(
            {
                "data": {
                    "has_plan": False,
                    "scope": normalized_scope,
                    "filters": query_filters,
                    "query_controls": query_controls,
                    "guidance": summary.get("guidance"),
                    "no_plan_query_boundary": True,
                    **_post_query_instruction(raw_user_text),
                },
                "next_step": "respond",
                "message": no_plan_message,
            }
        )

    total = summary.get("ordered_total") or 0
    risk_count = ((summary.get("review") or {}).get("risk_count") or 0)
    description = _describe_filters(query_filters)

    if normalized_scope == "candidates":
        sandbox = getattr(ctx.deps, "sandbox", None)
        if sandbox is None:
            candidate_data = _sandbox_unavailable("plan/candidates.json")
        else:
            candidate_query = {
                "tiers": query_filters.get("tier") or [],
                "province_names": query_filters.get("province") or [],
                "school_keywords": query_filters.get("school") or [],
                "major_keywords": query_filters.get("major") or [],
                "page_size": limit,
            }
            candidate_data = await sandbox.read("plan/candidates.json", query=candidate_query)
        candidate_items = _candidate_items(candidate_data if isinstance(candidate_data, dict) else {})
        examples = candidate_items[:limit]
        total_hits = _as_int(candidate_data.get("total") or candidate_data.get("count") or len(candidate_items))
        if not total_hits:
            total_hits = len(candidate_items)
        return _json(
            {
                "data": {
                    "has_plan": True,
                    "scope": "candidates",
                    "filters": query_filters,
                    "query_controls": query_controls,
                    "limit": limit,
                    "matched_total": total_hits,
                    "returned_total": len(examples),
                    "items": [_plan_item_brief(item) for item in examples],
                    **_post_query_instruction(raw_user_text),
                },
                "next_step": "respond",
                "message": (
                    f"候选池里按“{description}”命中{total_hits}条，展示前{len(examples)}条。"
                    if total_hits
                    else f"候选池里暂时没有命中“{description}”的机会。"
                ),
            }
        )

    plan_file = await _sandbox_data(ctx, "plan/items.json")
    plan_items = _items_from_plan_file(plan_file)
    if not plan_items:
        return _json(
            {
                "data": {
                    "has_plan": True,
                    "scope": "plan",
                    "filters": query_filters,
                    "query_controls": query_controls,
                    "summary": summary,
                    "matched_total": 0,
                    "returned_total": 0,
                    "items": [],
                    "warning": "plan_items_unavailable",
                    **_post_query_instruction(raw_user_text),
                },
                "next_step": "respond",
                "message": f"当前正式方案有{total}个志愿，审查风险{risk_count}项；但暂时没有拿到可逐条扫描的方案明细。",
            }
        )

    batch = getattr(ctx.deps, "batch", None) or "01"
    matched_items = [
        item
        for item in plan_items
        if _matches_plan_item(item, query_filters, batch=batch)
    ]
    count_metrics = _plan_query_count_metrics(
        plan_items=plan_items,
        matched_items=matched_items,
        declared_total=_as_int(total),
    )
    examples = _select_plan_query_examples(matched_items, limit=limit, controls=query_controls)
    include_fields = [str(item) for item in query_controls.get("include_fields") or []]
    snippet = "；".join(_plan_item_snippet(item, include_fields=include_fields) for item in examples)
    display_scope = _plan_query_display_scope(query_filters, query_controls, len(examples))
    school_summary: list[dict[str, Any]] = []
    school_total = 0
    if _query_requests_school_summary(raw_user_text, query_filters):
        school_summary = _school_summary_items(matched_items, limit=limit)
        school_total = len(
            {
                str(_item_value(item, "schoolName", "school_name", "collegeName") or "").strip()
                for item in matched_items
                if str(_item_value(item, "schoolName", "school_name", "collegeName") or "").strip()
            }
        )
        school_snippet = "；".join(_school_summary_snippet(item) for item in school_summary)
        if school_snippet:
            display_scope = f"前{len(school_summary)}所院校"
            snippet = school_snippet
    if query_filters:
        matched_phrase = (
            f"命中{count_metrics['matched_plan_item_total']}个志愿，涉及{count_metrics['matched_detail_total']}条专业明细"
            if count_metrics.get("detail_granularity") and count_metrics["matched_detail_total"] != count_metrics["matched_plan_item_total"]
            else f"命中{count_metrics['matched_plan_item_total']}个志愿"
        )
        if school_summary:
            tier_label = _tier_display_label([str(item) for item in query_filters.get("tier") or []])
            matched_phrase = f"{tier_label or description}共{count_metrics['matched_plan_item_total']}个志愿，涉及{school_total}所院校"
        message = (
            f"当前正式方案有{total}个志愿，按“{description}”{matched_phrase}，"
            f"展示{display_scope}：{snippet}"
            if matched_items
            else f"当前正式方案有{total}个志愿，按“{description}”暂时没有命中。"
        )
    else:
        message = (
            f"当前正式方案有{total}个志愿，审查风险{risk_count}项。"
            f"展示{display_scope}：{snippet}"
        )
    return _json(
        {
            "data": {
                "has_plan": True,
                "scope": "plan",
                "filters": query_filters,
                "query_controls": query_controls,
                "limit": limit,
                "summary": summary,
                **count_metrics,
                "returned_total": len(examples),
                "items": [_plan_item_brief(item) for item in examples],
                "school_total": school_total,
                "school_summary": school_summary,
                "truncated": len(matched_items) > len(examples),
                **_post_query_instruction(raw_user_text),
            },
            "next_step": "respond",
            "message": message,
        }
    )


async def confirm_pending(
    ctx: RunContext[RequestContext],
    action: PendingAction,
    apply_to_current_plan: bool | None = None,
) -> str:
    """Confirm or cancel the active pending operation.

    The tool owns the Release 4.0 pending execution path: it validates the
    current pending file, guards against planning-version drift, dispatches
    directly to backend APIs, and invalidates affected sandbox files.
    """
    normalized_action = str(action or "").strip().lower()
    if normalized_action in {"reject", "decline"}:
        normalized_action = "cancel"
    if normalized_action in {"accept", "apply"}:
        normalized_action = "confirm"
    if normalized_action not in {"confirm", "cancel"}:
        return _json(
            {
                "data": {"action": action, "allowed_actions": ["confirm", "cancel"]},
                "next_step": "clarify",
                "message": "需要说明是确认采纳，还是取消这次待确认内容。",
            }
        )

    pending = await _pending_data(ctx)
    if not pending.get("active"):
        return _json(
            {
                "data": {
                    "active": False,
                    "action": normalized_action,
                },
                "next_step": "respond",
                "message": "当前没有待确认操作；没有上一轮待确认内容，也没有待执行的方案调整或报考要求，不会执行任何变更。",
            }
        )

    kind = str(pending.get("kind") or "").strip()
    action_family = str(pending.get("action_family") or pending.get("actionFamily") or "").strip()
    if normalized_action == "cancel":
        await _mark_pending_status(ctx, pending, "cancelled")
        _invalidate_after_pending_action(ctx, kind, action_family)
        _clear_context_pending(ctx)
        return _json(
            {
                "data": {
                    "active": False,
                    "action": "cancel",
                    "kind": kind,
                    "action_family": action_family,
                    "pending_id": pending.get("pending_id"),
                },
                "next_step": "respond",
                "message": "已取消本次待确认内容。你可以继续说明想怎么调整，我会重新给出预览。",
            }
        )

    source_version = _pending_source_version(pending)
    current_version = await _latest_planning_version(ctx)
    if source_version > 0 and current_version > source_version:
        await _mark_pending_status(
            ctx,
            pending,
            "expired",
            resultCode="version_mismatch",
            currentBackendVersion=current_version,
        )
        _invalidate_after_pending_action(ctx, kind, action_family)
        _clear_context_pending(ctx)
        return _json(
            {
                "data": {
                    "active": False,
                    "action": "confirm",
                    "kind": kind,
                    "action_family": action_family,
                    "source_backend_version": source_version,
                    "current_backend_version": current_version,
                    "error": "version_mismatch",
                },
                "next_step": "respond",
                "message": (
                    f"方案状态已经更新过（版本{source_version}到{current_version}），"
                    "上一轮待确认内容已失效。请按最新方案重新生成预览。"
                ),
            }
        )

    if _dry_run_state_mutations(ctx):
        return _json(
            {
                "data": {
                    "active": False,
                    "action": "confirm",
                    "kind": kind,
                    "action_family": action_family,
                    "pending_id": pending.get("pending_id"),
                    "applied": False,
                    "would_apply": True,
                    "apply_to_current_plan": apply_to_current_plan,
                    "dry_run": True,
                },
                "next_step": "respond",
                "message": "这次会采纳当前待确认内容；评估模式下不会实际执行。",
            }
        )

    if kind == "intent_change":
        success, data, message = await _apply_intent_pending(
            ctx,
            pending,
            apply_to_current_plan_override=apply_to_current_plan,
        )
    elif kind in {"plan_mutation", "plan_generation"}:
        success, data, message = await _apply_plan_pending(ctx, pending)
    else:
        success = False
        data = {"reason": "unsupported_pending_kind", "kind": kind}
        message = "这类待确认内容还不能由新确认工具执行，请重新生成预览。"

    status = "applied" if success else "failed"
    await _mark_pending_status(
        ctx,
        pending,
        status,
        resultCode="applied" if success else str(data.get("reason") or "apply_failed"),
        resultData=data,
    )
    _invalidate_after_pending_action(ctx, kind, action_family)
    _clear_context_pending(ctx)
    return _json(
        {
            "data": {
                "active": False,
                "action": "confirm",
                "kind": kind,
                "action_family": action_family,
                "pending_id": pending.get("pending_id"),
                "applied": success,
                "result": data,
            },
            "next_step": "respond",
            "message": message,
        }
    )
