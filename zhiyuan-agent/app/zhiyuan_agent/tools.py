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
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

import aiohttp
from pydantic import Field
from pydantic_ai import RunContext
from pydantic_ai.messages import ToolReturnPart
from typing_extensions import NotRequired, TypedDict

from app.agent.context import RequestContext, resolve_pending_confirmation
from app.config import BochaSearchConfig
from app.domain import proposal_compiler
from app.domain.career_alignment import matching_career_evidence, matches_career_slot
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
    major_parent_mappings_for_batch,
    resolve_major_entity,
    resolve_major_mentions_from_text,
)
from app.domain.region_entity_resolver import REGION_AREA_PROVINCES, resolve_region_entity
from app.domain.school_major_ref_resolver import resolve_school_major_ref
from app.domain.school_entity_resolver import resolve_school_entity, resolve_school_mentions_from_text
from app.schemas.user_profile import UserProfile
from app.services.profile_manager import merge_confirmed_intents_into_profile
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
DiscoveryMode = Literal["catalog", "eligible", "recommend"]
DiscoveryEntityType = Literal["major", "school"]
ClarificationKind = Literal[
    "discovery_scope",
    "missing_subject",
    "missing_intent_content",
    "ambiguous_request",
]
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
IntentType = Literal["major", "school", "region", "tuition_budget"]
ConstraintType = Literal["exclude", "only_keep", "must_have"]
PlanScope = Literal["plan", "candidates"]
PendingAction = Literal["confirm", "cancel"]
PendingResolution = Literal["none", "replace_active_pending", "append_to_active_pending", "hold_new_request"]
PlanAction = Literal["add", "remove", "move", "replace", "sort", "generate", "regenerate_order"]
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


class PlanSelectionGoal(TypedDict, total=False):
    type: Literal["fill_to_count"]
    target_count: int


class PlanHardRequirement(TypedDict, total=False):
    kind: Literal["exclude", "only_keep", "include"]
    domain: Literal["school", "region", "major", "admission"]
    key: str
    values: list[str]
    min_count: int
    raw_text: str


class PlanPriorityRule(TypedDict, total=False):
    domain: Literal["school", "region", "major"]
    key: str
    values: list[str]
    ordering_target: Literal["rank_before"]
    scope: Literal["within_tier"]
    raw_text: str


class PlanTierCountBound(TypedDict, total=False):
    min_count: int
    max_count: int


class PlanExactTierQuotaGoal(TypedDict):
    type: Annotated[
        Literal["exact_counts"],
        Field(description="Only for three exact counts explicitly supplied by the user. Never convert ratios or ranges into exact counts."),
    ]
    update_mode: NotRequired[Literal["replace"]]
    sprint_count: Annotated[int, Field(description="Exact count for 冲/冲刺 tier (sprint/reach).")]
    stable_count: Annotated[int, Field(description="Exact count for 稳 tier (stable).")]
    protect_count: Annotated[int, Field(description="Exact count for 保/保底 tier (protect/safety).")]


class PlanRangeTierQuotaGoal(TypedDict):
    type: Annotated[
        Literal["count_ranges"],
        Field(description="For explicit minimum or maximum bounds. Include only bounds changed in this request; do not copy historical bounds."),
    ]
    update_mode: Literal["patch", "replace"]
    sprint: NotRequired[Annotated[PlanTierCountBound, Field(description="Bounds for 冲/冲刺 tier (sprint/reach) only.")]]
    stable: NotRequired[Annotated[PlanTierCountBound, Field(description="Bounds for 稳 tier (stable) only.")]]
    protect: NotRequired[Annotated[PlanTierCountBound, Field(description="Bounds for 保/保底 tier (protect/safety) only.")]]


class PlanRatioTierQuotaGoal(TypedDict):
    type: Annotated[
        Literal["ratios"],
        Field(description="For user-supplied ratio weights. Preserve submitted weights and never calculate exact counts in the Agent."),
    ]
    update_mode: Literal["replace"]
    sprint_weight: Annotated[int, Field(description="Submitted weight for 冲/冲刺 tier (sprint/reach).")]
    stable_weight: Annotated[int, Field(description="Submitted weight for 稳 tier (stable).")]
    protect_weight: Annotated[int, Field(description="Submitted weight for 保/保底 tier (protect/safety).")]


PlanTierQuotaGoal = (
    PlanExactTierQuotaGoal | PlanRangeTierQuotaGoal | PlanRatioTierQuotaGoal
)


class PlanRepairGoal(TypedDict, total=False):
    objective: Literal["increase_stability"]
    review_issue_code: ReviewIssueCode
    strategy: str


class PlanChangeSpec(TypedDict, total=False):
    selection_goal: Annotated[
        PlanSelectionGoal,
        Field(description="Only include when the user explicitly requests filling or completing the plan. A stated current total or preserved total is not a fill request."),
    ]
    tier_quota_goal: Annotated[
        PlanTierQuotaGoal,
        Field(description="Exactly one typed tier-allocation request. Do not derive requirements, priorities, or a selection goal from tier weights or bounds."),
    ]
    requirements: Annotated[
        list[PlanHardRequirement],
        Field(description="Only explicit school, region, major, or admission requirements. Never derive these from a tier-allocation request."),
    ]
    priority_rules: list[PlanPriorityRule]
    repair_goal: PlanRepairGoal


_DEFAULT_PLAN_QUERY_LIMIT = 5
_ALLOWED_PLAN_ACTIONS = ["add", "remove", "move", "replace", "sort", "generate", "regenerate_order"]
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


async def clarify_request(
    ctx: RunContext[RequestContext],  # noqa: ARG001
    kind: ClarificationKind,
) -> str:
    """Ask a bounded clarification when no business tool can safely choose scope.

    This is only for genuinely ambiguous requests. It cannot create pending state,
    record requirements, query business data, or mutate a plan.
    """
    messages = {
        "discovery_scope": "你想查的是院校目录、当前可报候选，还是当前正式方案里的项目？请明确一下范围。",
        "missing_subject": "请再说明要了解的是院校、专业、地域、报考规则，还是当前志愿方案。",
        "missing_intent_content": (
            "可以先保存思路且不自动改方案，但这句话里还没有具体内容。"
            "请补充要保留或排除的专业、院校、地域或预算要求；我会先列成待确认预览，确认前不会记录或改方案。"
        ),
        "ambiguous_request": "这轮还不能唯一确定要查询或处理的对象，请补充具体院校、专业、地域或方案范围。",
    }
    normalized_kind = str(kind or "ambiguous_request").strip()
    if normalized_kind not in messages:
        normalized_kind = "ambiguous_request"
    return _json(
        {
            "data": {
                "kind": normalized_kind,
                "state_mutation": False,
                "plan_mutation": False,
            },
            "next_step": "respond",
            "message": messages[normalized_kind],
        }
    )


async def respond_casual(ctx: RunContext[RequestContext]) -> str:  # noqa: ARG001
    """Reply to a greeting or non-business social message without making claims."""
    return _json(
        {
            "data": {
                "kind": "casual",
                "state_mutation": False,
                "plan_mutation": False,
            },
            "next_step": "respond",
            "message": "你好，请告诉我想了解院校、专业、报考规则，还是当前志愿方案。",
        }
    )


async def acknowledge_readonly(ctx: RunContext[RequestContext]) -> str:  # noqa: ARG001
    """Close a readonly discussion without claiming that anything was saved or changed."""
    return _json(
        {
            "data": {
                "kind": "readonly_acknowledgement",
                "state_mutation": False,
                "plan_mutation": False,
            },
            "next_step": "respond",
            "message": (
                "先按刚才的只读分析结论理解。当前没有待确认的报考要求或方案动作，"
                "不会记录要求，也不会改动当前方案。"
            ),
        }
    )


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
            else "需要说明是加入、移出、移动、替换、排序，还是生成方案。"
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


_DISCOVERY_FILTER_ALIASES = {
    "provinceNames": "province",
    "province_names": "province",
    "cityNames": "city",
    "city_names": "city",
    "schoolType": "school_type",
    "schoolTypes": "school_type",
    "school_type": "school_type",
    "school_types": "school_type",
    "ownership": "school_nature",
    "educationLevel": "education_level",
    "educationLevels": "education_level",
    "education_levels": "education_level",
    "keyword": "keyword",
    "keywords": "keyword",
    "query": "keyword",
    "majorCategory": "major",
    "major_category": "major",
    "majorDiscipline": "major",
    "major_discipline": "major",
    "majorDirection": "major",
    "major_direction": "major",
    "level1": "major",
    "level2": "major",
    "level3": "major",
    "majorLevel1": "major",
    "majorLevel2": "major",
    "majorLevel3": "major",
    "major_level1": "major",
    "major_level2": "major",
    "major_level3": "major",
    "admissionStability": "admission_stability",
    "riskPreference": "admission_stability",
    "risk_preference": "admission_stability",
    "schoolTags": "school_tags",
    "majorTags": "major_tags",
}


def _discovery_stability_tiers(value: Any) -> list[str]:
    tiers: list[str] = []
    for item in _as_list(value):
        text = _compact_text(item)
        if text in {"stable", "safe", "safer", "morestable", "稳", "稳妥", "更稳", "稳一点"}:
            for tier in ("稳", "保"):
                _append_unique(tiers, tier)
        elif text in {"protect", "protective", "safety", "保", "保底", "兜底"}:
            _append_unique(tiers, "保")
        elif text in {"sprint", "reach", "冲", "冲刺"}:
            _append_unique(tiers, "冲")
    return tiers
_DISCOVERY_LIST_FILTERS = {
    "province",
    "city",
    "school",
    "major",
    "school_nature",
    "school_type",
    "education_level",
    "keyword",
    "tier",
    "school_tags",
    "major_tags",
}


def _normalize_discovery_filters(filters: dict[str, Any] | None) -> tuple[dict[str, Any], int]:
    remapped: dict[str, Any] = {}
    for raw_key, value in (filters or {}).items():
        key = _DISCOVERY_FILTER_ALIASES.get(str(raw_key or "").strip(), str(raw_key or "").strip())
        if not key:
            continue
        if key == "admission_stability":
            stability_tiers = _discovery_stability_tiers(value)
            if stability_tiers:
                remapped["tier"] = [*_as_list(remapped.get("tier")), *stability_tiers]
            continue
        if key in remapped:
            remapped[key] = [*_as_list(remapped[key]), *_as_list(value)]
        else:
            remapped[key] = value
    normalized, embedded_limit = _normalize_plan_query_filters(remapped)
    for key in _DISCOVERY_LIST_FILTERS:
        if key not in normalized:
            continue
        values: list[str] = []
        for value in _as_list(normalized[key]):
            _append_unique(values, str(value or "").strip())
        if values:
            normalized[key] = values
        else:
            normalized.pop(key, None)
    return normalized, embedded_limit


def _catalog_response_items(response: Any) -> tuple[list[dict[str, Any]], bool]:
    if isinstance(response, list):
        return [item for item in response if isinstance(item, dict)], True
    if not isinstance(response, dict):
        return [], False
    if response.get("error") or response.get("success") is False:
        return [], False
    data = response.get("data")
    if data is None:
        return [], True
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)], True
    if isinstance(data, dict):
        return [data], True
    return [], False


def _discovery_unsupported_filters(filters: dict[str, Any], allowed: set[str]) -> list[str]:
    return sorted(key for key, value in filters.items() if value not in (None, "", [], {}) and key not in allowed)


def _catalog_school_brief(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "school_id": str(item.get("schoolId") or item.get("school_id") or "").strip(),
        "school": str(item.get("schoolName") or item.get("school_name") or "").strip(),
        "province": str(item.get("province") or item.get("provinceName") or "").strip(),
        "city": str(item.get("city") or item.get("cityName") or "").strip(),
        "school_type": str(item.get("schoolType") or item.get("school_type") or "").strip(),
        "school_nature": str(item.get("ownership") or item.get("schoolNature") or "").strip(),
        "education_level": str(item.get("educationLevel") or item.get("education_level") or "").strip(),
        "school_rank": _as_int(item.get("schoolRank") or item.get("school_rank")),
    }


def _catalog_major_brief(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "major_id": str(item.get("majorId") or item.get("major_id") or "").strip(),
        "major": str(item.get("majorName") or item.get("major_name") or "").strip(),
        "major_category": str(item.get("subCategoryName") or item.get("sub_category_name") or "").strip(),
        "major_discipline": str(item.get("categoryName") or item.get("category_name") or "").strip(),
        "education_level": str(item.get("educationLevel") or item.get("education_level") or "").strip(),
    }


def _deduplicate_discovery_items(items: list[dict[str, Any]], *, entity_type: str) -> list[dict[str, Any]]:
    deduplicated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        key = str(item.get(entity_type) or item.get(f"{entity_type}_id") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduplicated.append(item)
    return deduplicated


def _canonical_discovery_major_name(value: str, *, batch: str | None) -> str:
    raw_name = str(value or "").strip()
    mentions = resolve_major_mentions_from_text(raw_name, batch)
    if mentions:
        return mentions[0].canonical_name
    result = resolve_major_entity(raw_name, batch)
    if result.best is not None and not result.ambiguous:
        return result.best.canonical_name
    return raw_name


def _broader_discovery_major_keywords(values: list[str], *, batch: str | None) -> list[str]:
    mappings = major_parent_mappings_for_batch(batch or "01")
    level3_to_level2 = mappings.get("level3_to_level2") if isinstance(mappings, dict) else {}
    if not isinstance(level3_to_level2, dict):
        level3_to_level2 = {}
    result: list[str] = []
    for value in values:
        resolved = resolve_major_entity(value, batch)
        candidates = list(resolved.candidates) or []
        for candidate in candidates:
            canonical = str(candidate.canonical_name or "").strip()
            level = str(candidate.level or "").strip()
            if level == "level2" and canonical:
                _append_unique(result, canonical)
            parent = str(level3_to_level2.get(canonical) or "").strip()
            if parent:
                _append_unique(result, parent)
    return result


def _candidate_discovery_items(
    candidates: list[dict[str, Any]],
    *,
    entity_type: str,
    limit: int,
    batch: str | None,
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for candidate in candidates:
        raw_school = str(_item_value(candidate, "schoolName", "school_name", "collegeName") or "").strip()
        school_mentions = resolve_school_mentions_from_text(raw_school, batch)
        if len(school_mentions) == 1:
            school = school_mentions[0]
        else:
            school_result = resolve_school_entity(raw_school, batch)
            school = (
                school_result.best.canonical_name
                if school_result.best is not None and not school_result.ambiguous
                else raw_school
        )
        majors = _item_major_names(candidate)
        raw_major = majors[0] if majors else ""
        major = _canonical_discovery_major_name(raw_major, batch=batch)
        key = school if entity_type == "school" else major
        if not key:
            continue
        if key not in grouped:
            order.append(key)
            grouped[key] = {
                entity_type: key,
                "province": str(_item_value(candidate, "provinceName", "province_name", "province") or "").strip(),
                "city": str(_item_value(candidate, "cityName", "city_name", "city") or "").strip(),
                "school_nature": str(
                    _item_value(candidate, "schoolNature", "school_nature", "ownership") or ""
                ).strip(),
                "tiers": [],
                "schools": [],
                "majors": [],
                "best_admission_ratio": 0,
                "best_final_score": 0,
            }
        entry = grouped[key]
        _append_unique(entry["schools"], school)
        for name in majors:
            _append_unique(entry["majors"], _canonical_discovery_major_name(name, batch=batch))
        tier = _normalize_tier(_item_value(candidate, "tier", "riskTier", "risk_tier"))
        if tier:
            _append_unique(entry["tiers"], tier)
        entry["best_admission_ratio"] = max(
            _as_int(entry.get("best_admission_ratio")),
            _as_int(_item_value(candidate, "admissionRatio", "admission_ratio", "schoolEnrollRatio")),
        )
        entry["best_final_score"] = max(
            _as_int(entry.get("best_final_score")),
            _as_int(_item_value(candidate, "finalScore", "final_score")),
        )
    result: list[dict[str, Any]] = []
    for key in order[:limit]:
        item = grouped[key]
        item["schools"] = item["schools"][:5]
        item["majors"] = item["majors"][:5]
        result.append(item)
    return result


def _discovery_snippet(item: dict[str, Any], *, entity_type: str) -> str:
    name = str(item.get(entity_type) or "").strip()
    if not name:
        return ""
    suffixes: list[str] = []
    if entity_type == "school":
        for value in (item.get("city") or item.get("province"), item.get("school_nature"), item.get("education_level")):
            if value and value not in suffixes:
                suffixes.append(str(value))
        tiers = [str(value) for value in item.get("tiers") or [] if value]
        if tiers:
            suffixes.append("/".join(tiers))
        majors = [str(value) for value in item.get("majors") or [] if value]
        if majors:
            suffixes.append("专业：" + "、".join(majors[:2]))
    else:
        category = item.get("major_category") or item.get("major_discipline")
        if category:
            suffixes.append(str(category))
        schools = [str(value) for value in item.get("schools") or [] if value]
        if schools:
            suffixes.append("院校：" + "、".join(schools[:2]))
    return f"{name}（{'，'.join(suffixes)}）" if suffixes else name


def _discovery_clarify(*, reason: str, message: str, data: dict[str, Any] | None = None) -> str:
    return _json(
        {
            "data": {"reason": reason, "state_mutation": False, **(data or {})},
            "next_step": "clarify",
            "message": message,
        }
    )


async def _sandbox_data(
    ctx: RunContext[RequestContext],
    path: str,
    *,
    query: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sandbox = getattr(ctx.deps, "sandbox", None)
    normalized_path = normalize_sandbox_path(path)
    if sandbox is None:
        return _sandbox_unavailable(normalized_path)
    data = await sandbox.read(normalized_path, query=query)
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


async def discover_options(
    ctx: RunContext[RequestContext],
    entity_type: DiscoveryEntityType,
    mode: DiscoveryMode,
    filters: dict[str, Any] | None = None,
    limit: int = 10,
) -> str:
    """List catalog, eligible, or recommended schools/majors from an explicit data source."""
    normalized_entity = str(entity_type or "").strip().lower()
    normalized_mode = str(mode or "").strip().lower()
    if normalized_entity not in {"school", "major"}:
        return _discovery_clarify(
            reason="discovery_entity_type_required",
            message="需要先说明要查院校还是专业。",
            data={"allowed_entity_types": ["school", "major"]},
        )
    if normalized_mode not in {"catalog", "eligible", "recommend"}:
        return _discovery_clarify(
            reason="discovery_mode_required",
            message="需要先说明要查完整目录、当前可报候选，还是基于当前候选做推荐。",
            data={"allowed_modes": ["catalog", "eligible", "recommend"]},
        )

    normalized_filters, embedded_limit = _normalize_discovery_filters(filters)
    requested_limit = _as_int(limit, 10)
    if requested_limit == 10 and filters and any(key in filters for key in ("limit", "pageSize", "page_size")):
        requested_limit = embedded_limit
    requested_limit = max(1, min(requested_limit, 20))

    if normalized_mode == "catalog":
        if normalized_entity == "school":
            allowed = {
                "keyword",
                "school",
                "province",
                "city",
                "school_nature",
                "school_type",
                "education_level",
            }
            unsupported = _discovery_unsupported_filters(normalized_filters, allowed)
            if unsupported:
                return _discovery_clarify(
                    reason="catalog_school_filters_unsupported",
                    message="院校目录查询暂不支持这些筛选字段，请改用地域、院校名称、院校性质、院校类型或学历层次。",
                    data={"unsupported_filters": unsupported, "filters": normalized_filters},
                )
            has_explicit_selector = any(normalized_filters.get(key) for key in allowed)
            if not has_explicit_selector:
                return _discovery_clarify(
                    reason="catalog_school_scope_required",
                    message="请补充要查的地域、院校关键词或院校类型，避免直接返回没有边界的全国院校列表。",
                    data={"filters": normalized_filters},
                )
            for key in ("school_nature", "school_type", "education_level"):
                if len(normalized_filters.get(key) or []) > 1:
                    return _discovery_clarify(
                        reason="catalog_school_single_filter_required",
                        message="院校目录本次只能按一个院校性质、类型或学历层次查询，请先缩小范围。",
                        data={"field": key, "values": normalized_filters.get(key)},
                    )

            effective_filters = dict(normalized_filters)
            education_levels = list(effective_filters.get("education_level") or [])
            if not education_levels:
                education_levels = ["本科" if (getattr(ctx.deps, "batch", None) or "01") == "01" else "专科"]
                effective_filters["education_level"] = education_levels
            provinces = list(effective_filters.get("province") or [])
            cities = list(effective_filters.get("city") or [])
            scopes: list[tuple[str | None, str | None]] = []
            if provinces and cities:
                scopes = [(province, city) for province in provinces for city in cities]
            elif provinces:
                scopes = [(province, None) for province in provinces]
            elif cities:
                scopes = [(None, city) for city in cities]
            else:
                scopes = [(None, None)]
            responses = await asyncio.gather(
                *(
                    internal_client.catalog_list_schools(
                        province=province,
                        city=city,
                        school_type=(effective_filters.get("school_type") or [None])[0],
                        ownership=(effective_filters.get("school_nature") or [None])[0],
                        education_level=education_levels[0],
                    )
                    for province, city in scopes
                )
            )
            raw_items: list[dict[str, Any]] = []
            for response in responses:
                response_items, available = _catalog_response_items(response)
                if not available:
                    return _discovery_clarify(
                        reason="catalog_school_source_unavailable",
                        message="权威院校目录当前不可用，暂时不能可靠列出院校名单。",
                        data={"filters": effective_filters, "data_source": "school_catalog"},
                    )
                raw_items.extend(response_items)
            keywords = [
                *list(effective_filters.get("keyword") or []),
                *list(effective_filters.get("school") or []),
            ]
            items = [_catalog_school_brief(item) for item in raw_items]
            if keywords:
                items = [
                    item
                    for item in items
                    if any(_compact_text(keyword) in _compact_text(item.get("school")) for keyword in keywords)
                ]
            items = _deduplicate_discovery_items(items, entity_type="school")
            items.sort(key=lambda item: str(item.get("school") or ""))
            returned = items[:requested_limit]
            description = _describe_filters(effective_filters) or "当前目录范围"
            snippet = "；".join(_discovery_snippet(item, entity_type="school") for item in returned)
            return _json(
                {
                    "data": {
                        "entity_type": "school",
                        "mode": "catalog",
                        "filters": effective_filters,
                        "data_source": "authoritative_school_catalog",
                        "matched_total": len(items),
                        "returned_total": len(returned),
                        "items": returned,
                        "state_mutation": False,
                    },
                    "next_step": "respond",
                    "message": (
                        f"权威院校目录按“{description}”共找到{len(items)}所，展示前{len(returned)}所：{snippet}"
                        if returned
                        else f"权威院校目录按“{description}”暂时没有找到院校。"
                    ),
                }
            )

        allowed = {"keyword", "major", "education_level"}
        unsupported = _discovery_unsupported_filters(normalized_filters, allowed)
        if unsupported:
            return _discovery_clarify(
                reason="catalog_major_filters_unsupported",
                message="专业目录查询暂不支持这些筛选字段，请改用专业名称、专业类或学历层次。",
                data={"unsupported_filters": unsupported, "filters": normalized_filters},
            )
        keywords = [*list(normalized_filters.get("keyword") or []), *list(normalized_filters.get("major") or [])]
        if not keywords:
            return _discovery_clarify(
                reason="catalog_major_keyword_required",
                message="请补充专业名称或专业类关键词，例如“计算机”或“电子信息”。",
                data={"filters": normalized_filters},
            )
        education_levels = list(normalized_filters.get("education_level") or [])
        if len(education_levels) > 1:
            return _discovery_clarify(
                reason="catalog_major_single_education_level_required",
                message="专业目录本次只能查询一个学历层次，请先说明本科或专科。",
                data={"education_levels": education_levels},
            )
        education_level = (
            education_levels[0]
            if education_levels
            else ("本科" if (getattr(ctx.deps, "batch", None) or "01") == "01" else "专科")
        )
        responses = await asyncio.gather(
            *(internal_client.catalog_search_major(keyword, education_level) for keyword in keywords)
        )
        raw_items = []
        for response in responses:
            response_items, available = _catalog_response_items(response)
            if not available:
                return _discovery_clarify(
                    reason="catalog_major_source_unavailable",
                    message="权威专业目录当前不可用，暂时不能可靠列出专业名单。",
                    data={"filters": normalized_filters, "data_source": "major_catalog"},
                )
            raw_items.extend(response_items)
        items = _deduplicate_discovery_items(
            [_catalog_major_brief(item) for item in raw_items],
            entity_type="major",
        )
        items.sort(key=lambda item: str(item.get("major") or ""))
        returned = items[:requested_limit]
        effective_filters = {**normalized_filters, "education_level": [education_level]}
        description = _describe_filters(effective_filters) or "当前目录范围"
        snippet = "；".join(_discovery_snippet(item, entity_type="major") for item in returned)
        return _json(
            {
                "data": {
                    "entity_type": "major",
                    "mode": "catalog",
                    "filters": effective_filters,
                    "data_source": "authoritative_major_catalog",
                    "matched_total": len(items),
                    "returned_total": len(returned),
                    "items": returned,
                    "state_mutation": False,
                },
                "next_step": "respond",
                "message": (
                    f"权威专业目录按“{description}”共找到{len(items)}个，展示前{len(returned)}个：{snippet}"
                    if returned
                    else f"权威专业目录按“{description}”暂时没有找到专业。"
                ),
            }
        )

    allowed = {"school", "major", "province", "city", "school_nature", "tier", "school_tags", "major_tags"}
    unsupported = _discovery_unsupported_filters(normalized_filters, allowed)
    if unsupported:
        return _discovery_clarify(
            reason="candidate_discovery_filters_unsupported",
            message="当前可报候选查询暂不支持这些筛选字段，请改用院校、专业、地域、档位或候选标签。",
            data={"unsupported_filters": unsupported, "filters": normalized_filters},
        )
    sandbox = getattr(ctx.deps, "sandbox", None)
    if sandbox is None:
        return _discovery_clarify(
            reason="candidate_source_unavailable",
            message="当前会话候选池不可用，暂时不能判断哪些院校或专业可报。",
            data={"filters": normalized_filters, "data_source": "candidate_pool"},
        )
    school_tags = [
        *list(normalized_filters.get("school_tags") or []),
        *list(normalized_filters.get("school_nature") or []),
    ]
    page_size = min(50, max(requested_limit, requested_limit * (5 if normalized_entity == "school" else 3)))
    candidate_query = {
        "tiers": normalized_filters.get("tier") or [],
        "province_names": normalized_filters.get("province") or [],
        "city_names": normalized_filters.get("city") or [],
        "school_keywords": normalized_filters.get("school") or [],
        "major_keywords": normalized_filters.get("major") or [],
        "school_tags": school_tags,
        "major_tags": normalized_filters.get("major_tags") or [],
        "page_size": page_size,
        "sort_field": "finalScore",
        "sort_order": "desc",
    }
    candidate_data = await sandbox.read("plan/candidates.json", query=candidate_query)
    if candidate_data.get("error") or candidate_data.get("available") is False:
        return _discovery_clarify(
            reason="candidate_source_unavailable",
            message="当前会话候选池不可用，暂时不能可靠列出可报或推荐名单。",
            data={"filters": normalized_filters, "data_source": "candidate_pool"},
        )
    candidates = _candidate_items(candidate_data)
    items = _candidate_discovery_items(
        candidates,
        entity_type=normalized_entity,
        limit=requested_limit,
        batch=getattr(ctx.deps, "batch", None) or "01",
    )
    matched_total = _as_int(candidate_data.get("total") or (candidate_data.get("page") or {}).get("total"))
    if matched_total <= 0:
        matched_total = len(candidates)
    description = _describe_filters(normalized_filters) or "当前候选范围"
    snippet = "；".join(_discovery_snippet(item, entity_type=normalized_entity) for item in items)
    mode_label = "当前可报候选" if normalized_mode == "eligible" else "当前候选推荐顺序"
    entity_label = "院校" if normalized_entity == "school" else "专业"
    plan_summary = await _plan_summary_data(ctx)
    formal_plan_present = bool(plan_summary.get("has_plan") and _as_int(plan_summary.get("ordered_total")) > 0)
    formal_plan_boundary = (
        " 当前尚未生成正式方案，本结果只来自候选池。"
        if not formal_plan_present
        else ""
    )
    empty_result_analysis: dict[str, Any] = {}
    empty_message = f"{mode_label}按“{description}”暂时没有命中的{entity_label}。"
    if not items and normalized_entity == "major" and normalized_filters.get("major"):
        requested_majors = list(normalized_filters.get("major") or [])
        requested_tiers = list(normalized_filters.get("tier") or [])
        if requested_tiers:
            without_tier_query = {**candidate_query, "tiers": []}
            without_tier_data = await sandbox.read("plan/candidates.json", query=without_tier_query)
            if not without_tier_data.get("error") and without_tier_data.get("available") is not False:
                without_tier_candidates = _candidate_items(without_tier_data)
                without_tier_total = _as_int(
                    without_tier_data.get("total") or (without_tier_data.get("page") or {}).get("total")
                ) or len(without_tier_candidates)
                available_tiers: list[str] = []
                for candidate in without_tier_candidates:
                    tier = _normalize_tier(_item_value(candidate, "tier", "riskTier", "risk_tier"))
                    if tier:
                        _append_unique(available_tiers, tier)
                empty_result_analysis["exact_major_without_tier_total"] = without_tier_total
                empty_result_analysis["exact_major_available_tiers"] = available_tiers
                if without_tier_total > 0:
                    empty_message += (
                        f" 去掉稳/保档限制后，这些专业有{without_tier_total}条候选记录"
                        f"（当前页档位：{'、'.join(available_tiers) or '未标明'}），说明缺的是稳/保机会，不是专业名称。"
                    )

        if not empty_result_analysis.get("exact_major_without_tier_total"):
            broader_keywords = _broader_discovery_major_keywords(
                requested_majors,
                batch=getattr(ctx.deps, "batch", None) or "01",
            )
            broader_keywords = [value for value in broader_keywords if value not in requested_majors]
            if broader_keywords:
                broader_query = {**candidate_query, "major_keywords": broader_keywords}
                broader_data = await sandbox.read("plan/candidates.json", query=broader_query)
                if not broader_data.get("error") and broader_data.get("available") is not False:
                    broader_candidates = _candidate_items(broader_data)
                    broader_total = _as_int(
                        broader_data.get("total") or (broader_data.get("page") or {}).get("total")
                    ) or len(broader_candidates)
                    broader_items = _candidate_discovery_items(
                        broader_candidates,
                        entity_type="major",
                        limit=min(requested_limit, 3),
                        batch=getattr(ctx.deps, "batch", None) or "01",
                    )
                    empty_result_analysis.update(
                        {
                            "broader_major_keywords": broader_keywords,
                            "broader_matched_candidate_entry_total": broader_total,
                            "broader_items": broader_items,
                        }
                    )
                    if broader_items:
                        broader_snippet = "；".join(
                            _discovery_snippet(item, entity_type="major") for item in broader_items
                        )
                        empty_message += (
                            f" 放宽到更宽的专业类“{'、'.join(broader_keywords)}”后有{broader_total}条候选记录，"
                            f"例如：{broader_snippet}。"
                        )
                    else:
                        empty_message += f" 放宽到“{'、'.join(broader_keywords)}”后也没有稳/保档命中。"
        if empty_result_analysis.get("broader_major_keywords"):
            next_step = "下一步可以按更宽的专业类或其他档位继续看。"
        else:
            next_step = "下一步可以改查具体专业名称，或先刷新候选池再看。"
        empty_message += f" 本轮只查询，没有把任何候选加入方案；{next_step}"
    sample_boundary = (
        "这些只是当前页聚合样例，不能据此概括全量院校性质、专业或档位分布。"
    )
    return _json(
        {
            "data": {
                "entity_type": normalized_entity,
                "mode": normalized_mode,
                "filters": normalized_filters,
                "data_source": "eligible_candidate_pool"
                if normalized_mode == "eligible"
                else "candidate_pool_recommendation_overlay",
                "recommendation_basis": "finalScore" if normalized_mode == "recommend" else "",
                "matched_candidate_entry_total": matched_total,
                "returned_items_are_sample": matched_total > len(candidates) or len(items) < matched_total,
                "global_distribution_available": False,
                "returned_total": len(items),
                "items": items,
                "view_summary": candidate_data.get("view_summary") or {},
                "empty_result_analysis": empty_result_analysis,
                "formal_plan_present": formal_plan_present,
                "state_mutation": False,
            },
            "next_step": "respond",
            "message": (
                f"{mode_label}按“{description}”命中{matched_total}条候选记录，"
                f"展示前{len(items)}个{entity_label}：{snippet}。{sample_boundary}"
                if items
                else empty_message
            ) + formal_plan_boundary,
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
    """Compare 2-5 majors, major categories/directions, or schools with no state mutation."""
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
        if count > 0:
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
    code = str(issue.get("code") or "").strip()
    text = " ".join(
        str(issue.get(key) or "")
        for key in ("summary", "suggested_action", "scope_kind")
    ).lower()
    if focus == "tuition":
        if code in {"high_tuition", "cooperative_program"}:
            return True
        return any(token in text for token in ("tuition", "学费", "高收费", "费用", "中外合作", "cooperative"))
    if focus == "tier_balance":
        if code in {
            "probability_inversion",
            "probability_gap",
            "count_validation",
            "tier_gap",
            "safety_guard",
            "low_safety",
            "edge_score",
            "group_inner_safety_guard",
            "major_group_safety_intent_alignment",
        }:
            return True
        return any(
            token in text
            for token in ("tier", "ratio", "probability", "count", "录取概率", "梯度", "冲稳保", "保底", "安全垫", "志愿数量")
        )
    if focus == "career_fit":
        if code in {"career_mismatch", "major_group_safety_intent_alignment"}:
            return True
        return any(token in text for token in ("career", "intent", "专业", "职业", "偏好", "适配"))
    return True


def _review_career_labels(career_slots: list[str] | None) -> tuple[list[str], list[str]]:
    normalized = normalize_career_slots([str(value or "").strip() for value in career_slots or []])
    return normalized, [to_career_label(value) for value in normalized]


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


def _review_issue_examples_from_plan(issue: dict[str, Any], plan_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing = issue.get("examples") if isinstance(issue.get("examples"), list) else []
    if existing:
        return existing[:5]
    unit_ids = {str(value or "").strip() for value in issue.get("unit_ids") or [] if str(value or "").strip()}
    volunteer_ids = {
        str(value or "").strip()
        for value in issue.get("volunteer_ids") or []
        if str(value or "").strip()
    }
    if not unit_ids and not volunteer_ids:
        return []
    matched: list[dict[str, Any]] = []
    for item in plan_items:
        if _item_unit_id(item) not in unit_ids and _item_volunteer_id(item) not in volunteer_ids:
            continue
        matched.append(_plan_item_brief(item))
        if len(matched) >= 5:
            break
    return matched


def _review_item_search_values(item: dict[str, Any]) -> list[Any]:
    values: list[Any] = [
        _item_value(item, "schoolName", "school_name", "collegeName"),
        _item_value(item, "schoolCategory", "school_category"),
        _item_value(item, "schoolNature", "school_nature", "ownership"),
        *_item_major_names(item),
    ]
    for key in (
        "schoolRankTags",
        "schoolBasicTags",
        "schoolPopupTags",
        "schoolTags",
        "majorRankTags",
        "majorPlanTags",
        "majorTags",
        "tags",
    ):
        values.extend(_as_list(item.get(key)))
    return values


def _review_resolved_major_keywords(values: list[str] | None, *, batch: str | None) -> list[str]:
    resolved: list[str] = []
    for value in values or []:
        raw = str(value or "").strip()
        if not raw:
            continue
        result = resolve_major_entity(raw, batch)
        for candidate in result.candidates:
            _append_unique(resolved, candidate.canonical_name)
        _append_unique(resolved, raw)
    return resolved


def _review_career_evidence(
    plan_items: list[dict[str, Any]],
    *,
    career_slots: list[str],
    major_keywords: list[str],
    plan_total: int,
) -> dict[str, Any]:
    def ranked_examples(items: list[dict[str, Any]], slot: str, *, limit: int = 3) -> list[dict[str, Any]]:
        ranked = sorted(
            items,
            key=lambda item: (
                len(matching_career_evidence(_item_major_names(item), slot)),
                len(matching_career_evidence(_review_item_search_values(item), slot)),
            ),
            reverse=True,
        )
        unique: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, item in enumerate(ranked):
            key = _plan_item_group_key(item, index)
            if key in seen:
                continue
            seen.add(key)
            unique.append(_plan_item_brief(item))
            if len(unique) >= limit:
                break
        return unique

    slot_results: list[dict[str, Any]] = []
    for slot in career_slots:
        matched = [item for item in plan_items if matches_career_slot(_review_item_search_values(item), slot)]
        metrics = _plan_query_count_metrics(
            plan_items=plan_items,
            matched_items=matched,
            declared_total=plan_total,
        )
        markers: list[str] = []
        for item in matched[:10]:
            for marker in matching_career_evidence(_review_item_search_values(item), slot):
                _append_unique(markers, marker)
        slot_results.append(
            {
                "slot": slot,
                "label": to_career_label(slot),
                "matched_plan_item_total": metrics["matched_plan_item_total"],
                "matched_detail_total": metrics["matched_detail_total"],
                "evidence_markers": markers[:8],
                "examples": ranked_examples(matched, slot),
            }
        )

    major_matched = [
        item for item in plan_items
        if major_keywords and _matches_any_text(_item_major_names(item), major_keywords)
    ]
    major_metrics = _plan_query_count_metrics(
        plan_items=plan_items,
        matched_items=major_matched,
        declared_total=plan_total,
    )
    return {
        "available": bool(plan_items),
        "slots": slot_results,
        "major_keywords": major_keywords,
        "major_matched_plan_item_total": major_metrics["matched_plan_item_total"],
        "major_matched_detail_total": major_metrics["matched_detail_total"],
        "major_examples": ranked_examples(major_matched, "", limit=3),
    }


def _review_tuition_evidence(
    plan_items: list[dict[str, Any]],
    *,
    max_tuition_per_year: int,
    plan_total: int,
) -> dict[str, Any]:
    known = [item for item in plan_items if _item_tuition(item) > 0]
    over_budget = [item for item in known if _item_tuition(item) > max_tuition_per_year]
    over_budget.sort(key=_item_tuition, reverse=True)
    metrics = _plan_query_count_metrics(
        plan_items=plan_items,
        matched_items=over_budget,
        declared_total=plan_total,
    )
    return {
        "available": bool(plan_items),
        "max_tuition_per_year": max_tuition_per_year,
        "known_detail_total": len(known),
        "matched_plan_item_total": metrics["matched_plan_item_total"],
        "matched_detail_total": metrics["matched_detail_total"],
        "plan_item_total": metrics["plan_item_total"],
        "examples": [_plan_item_brief(item) for item in over_budget[:3]],
    }


def _review_cooperative_evidence(
    plan_items: list[dict[str, Any]],
    *,
    plan_total: int,
) -> dict[str, Any]:
    matched = [item for item in plan_items if match_attribute_item("program_type", item, ["中外合作"])]
    metrics = _plan_query_count_metrics(
        plan_items=plan_items,
        matched_items=matched,
        declared_total=plan_total,
    )
    examples: list[dict[str, Any]] = []
    seen_groups: set[str] = set()
    for index, item in enumerate(matched):
        group_key = _plan_item_group_key(item, index)
        if group_key in seen_groups:
            continue
        seen_groups.add(group_key)
        examples.append(_plan_item_brief(item))
        if len(examples) >= 3:
            break
    return {
        "available": bool(plan_items),
        "matched_plan_item_total": metrics["matched_plan_item_total"],
        "matched_detail_total": metrics["matched_detail_total"],
        "plan_item_total": metrics["plan_item_total"],
        "examples": examples,
    }


def _review_example_text(examples: list[dict[str, Any]], *, limit: int = 2) -> str:
    rendered: list[str] = []
    for item in examples[:limit]:
        parts = [str(item.get("school") or "").strip(), str(item.get("major") or "").strip()]
        name = "-".join(part for part in parts if part) or str(item.get("summary") or "").strip()
        suffixes: list[str] = []
        if item.get("tier"):
            suffixes.append(str(item["tier"]))
        if _as_int(item.get("tuition_per_year")) > 0:
            suffixes.append(f"{_as_int(item['tuition_per_year'])}元/年")
        text = f"{name}（{'，'.join(suffixes)}）" if name and suffixes else name
        if text:
            rendered.append(text)
    return "；".join(rendered)


def _review_proposal_matches_focus(proposal: dict[str, Any], focus: str) -> bool:
    if focus in {"full_review", "risk_only"}:
        return True
    codes = " ".join(str(code or "") for code in proposal.get("source_check_codes") or [])
    text = f"{codes} {proposal.get('strategy') or ''} {proposal.get('title') or ''} {proposal.get('summary') or ''}"
    if focus == "tuition":
        return any(token in text for token in ("tuition", "cooperative", "高收费", "中外合作", "学费"))
    if focus == "tier_balance":
        return any(
            token in text
            for token in ("tier", "probability", "count", "safety", "梯度", "冲稳保", "保底", "安全垫", "数量")
        )
    if focus == "career_fit":
        return any(token in text for token in ("career", "intent", "专业", "职业", "意向"))
    return True


def _review_proposal_lines(fix_proposals: dict[str, Any], focus: str) -> tuple[list[str], list[str]]:
    ready: list[str] = []
    blocked: list[str] = []
    for proposal in fix_proposals.get("proposals") or []:
        if not isinstance(proposal, dict) or not _review_proposal_matches_focus(proposal, focus):
            continue
        title = str(proposal.get("title") or "处理方向").strip()
        impact = str(proposal.get("impact") or "").strip()
        summary = str(proposal.get("summary") or "").strip()
        reason = str(proposal.get("blocking_reason") or "").strip()
        reason = reason.removeprefix("当前不可以先看调整预览：").removeprefix("当前不能直接处理：")
        detail = (impact or summary).rstrip("。；")
        line = f"{title}：{detail}" if detail else title
        if str(proposal.get("status") or "").strip() == "ready":
            ready.append(line)
        else:
            blocked.append(
                f"{line}；当前不能直接处理：{(reason or '还需要明确取舍或补充候选').rstrip('。；')}"
            )
    return ready[:3], blocked[:3]


def _review_plan_message(
    *,
    focus: str,
    counts: dict[str, int],
    ordered_total: int,
    target_total: int,
    tier_balance: dict[str, Any],
    issues: list[dict[str, Any]],
    tuition_evidence: dict[str, Any],
    cooperative_evidence: dict[str, Any],
    career_evidence: dict[str, Any],
    fix_proposals: dict[str, Any],
    generate_fix_proposals: bool,
) -> str:
    lines: list[str] = []
    if focus == "tuition":
        cap = _as_int(tuition_evidence.get("max_tuition_per_year"), 20000)
        matched = _as_int(tuition_evidence.get("matched_plan_item_total"))
        detail_total = _as_int(tuition_evidence.get("matched_detail_total"))
        total = _as_int(tuition_evidence.get("plan_item_total"), ordered_total)
        if tuition_evidence.get("available"):
            ratio = round(matched * 100 / total) if total > 0 else 0
            if matched <= 0:
                verdict = "没有发现超出该预算的项目"
            elif ratio >= 20:
                verdict = "偏多，需要按预算处理"
            else:
                verdict = "占比不高，但仍要逐项确认是否可承受"
            lines.append(
                f"当前正式方案有{ordered_total}个志愿。先说结论：按每年不超过{cap}元看，"
                f"当前方案有{matched}个专业组超出预算，约占{ratio}%，{verdict}。"
            )
            if detail_total != matched:
                lines.append(f"这些专业组共涉及{detail_total}条专业志愿。")
            examples = _review_example_text(tuition_evidence.get("examples") or [])
            if examples:
                lines.append(f"例如：{examples}。")
        else:
            lines.append(f"先说结论：当前没有拿到逐项学费数据，暂时不能按每年{cap}元准确统计高收费数量。")
        cooperative_total = _as_int(cooperative_evidence.get("matched_plan_item_total"))
        cooperative_detail_total = _as_int(cooperative_evidence.get("matched_detail_total"))
        if cooperative_evidence.get("available"):
            cooperative_line = f"中外合作项目命中{cooperative_total}个专业组"
            if cooperative_detail_total != cooperative_total:
                cooperative_line += f"、{cooperative_detail_total}条专业志愿"
            cooperative_examples = _review_example_text(cooperative_evidence.get("examples") or [])
            if cooperative_examples:
                cooperative_line += f"，例如{cooperative_examples}"
            lines.append(cooperative_line + "；与高收费统计可能重叠。")
        else:
            lines.append("当前没有拿到逐项项目类型，暂时不能准确统计中外合作项目。")
    elif focus == "career_fit":
        slot_results = career_evidence.get("slots") or []
        major_total = _as_int(career_evidence.get("major_matched_plan_item_total"))
        major_keywords = career_evidence.get("major_keywords") or []
        if not career_evidence.get("available"):
            lines.append("当前方案承接结论：没有拿到方案明细，暂时不能用具体志愿判断发展方向承接。")
        else:
            lines.append("当前方案承接结论：对这些方向有一定承接，但只能说明方案里存在相关专业或院校证据，不等于对应职业一定录用。")
            if major_keywords:
                lines.append(f"专业方向：按{'、'.join(major_keywords[:4])}统计，命中{major_total}个专业组。")
                examples = _review_example_text(career_evidence.get("major_examples") or [])
                if examples:
                    lines.append(f"代表项：{examples}。")
            for result in slot_results:
                count = _as_int(result.get("matched_plan_item_total"))
                markers = "、".join(result.get("evidence_markers") or [])
                line = f"{result.get('label') or '发展方向'}：命中{count}个专业组"
                if markers:
                    line += f"，主要证据是{markers}"
                examples = _review_example_text(result.get("examples") or [], limit=1)
                if examples:
                    line += f"，例如{examples}"
                lines.append(line + "。")
    elif focus == "tier_balance":
        sprint = _as_int(tier_balance.get("冲"))
        safe = _as_int(tier_balance.get("稳"))
        protect = _as_int(tier_balance.get("保"))
        issue_codes = {str(issue.get("code") or "") for issue in issues}
        if not tier_balance.get("available"):
            lines.append("先说结论：当前没拿到冲稳保数量，不能直接判断这版是否太冲或保底是否够。")
        elif protect <= 0 or "safety_guard" in issue_codes or "low_safety" in issue_codes:
            lines.append(f"先说结论：当前冲{sprint}、稳{safe}、保{protect}，保底承接不足，不能按现状判断为稳妥。")
        elif sprint > safe + protect:
            lines.append(f"先说结论：当前冲{sprint}、稳{safe}、保{protect}，冲档数量明显偏高。")
        elif issue_codes & {"probability_inversion", "probability_gap", "tier_gap"}:
            lines.append(
                f"先说结论：当前冲{sprint}、稳{safe}、保{protect}，数量上不算太冲，但排序或录取概率梯度仍有问题，不能只看保档数量就说保底够。"
            )
        else:
            lines.append(f"先说结论：当前冲{sprint}、稳{safe}、保{protect}，数量结构不偏冲，保档也不算少。")
        if target_total > ordered_total > 0:
            lines.append(f"当前方案是{ordered_total}/{target_total}个，还缺{target_total - ordered_total}个；数量未补齐也会影响最终判断。")
    else:
        lines.append(
            f"方案审查结论：当前正式方案有{ordered_total}个志愿，发现风险{counts['risk_count']}项、提醒{counts['warn_count']}项。"
        )
        if tier_balance.get("available"):
            lines.append(
                f"冲稳保为{_as_int(tier_balance.get('冲'))}/{_as_int(tier_balance.get('稳'))}/{_as_int(tier_balance.get('保'))}。"
            )

    if issues:
        details: list[str] = []
        for issue in issues[:3]:
            detail = str(issue.get("summary") or "").strip()
            affected = _as_int(issue.get("affected_count"))
            if affected > 0:
                detail += f"（涉及{affected}项）"
            examples = _review_example_text(issue.get("examples") or [], limit=1)
            if examples:
                detail += f"，例如{examples}"
            if detail:
                details.append(detail)
        if details:
            lines.append("重点问题：" + "；".join(details) + "。")

    if generate_fix_proposals:
        ready, blocked = _review_proposal_lines(fix_proposals, focus)
        if ready:
            lines.append("可以继续生成调整预览的方向：" + "；".join(ready) + "。")
        if blocked:
            lines.append("暂时不能直接补或调的方向：" + "；".join(blocked) + "。")
        if not ready and not blocked:
            lines.append("当前没有与这次关注点直接匹配的可执行处理提案，不能为了凑答案自动改方案。")

    lines.append("本轮只是只读审查，不会记录新要求，确认前不会改动方案；需要调整时会先给你确认预览。")
    return "\n".join(lines)


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
        shortages = (
            proposal.get("candidateShortages")
            if isinstance(proposal.get("candidateShortages"), list)
            else proposal.get("candidate_shortages")
            if isinstance(proposal.get("candidate_shortages"), list)
            else []
        )
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
                "action_summaries": [
                    str(action.get("summary") or "").strip()
                    for action in actions[:3]
                    if isinstance(action, dict) and str(action.get("summary") or "").strip()
                ],
                "candidate_shortages": [
                    {
                        "code": str(shortage.get("code") or "").strip(),
                        "message": str(shortage.get("message") or shortage.get("summary") or "").strip(),
                        "tier": str(shortage.get("tier") or "").strip(),
                    }
                    for shortage in shortages[:5]
                    if isinstance(shortage, dict)
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
    major_keywords: list[str] | None = None,
    tuition_max_per_year: int | None = None,
    generate_fix_proposals: bool = False,
    force_refresh: bool = True,
) -> str:
    """Run or read current plan review without changing the plan.

    Use this only for read-only questions such as "审查一下方案", "有什么风险",
    "这版稳不稳", or "高收费风险大吗". If the user explicitly asks to remove,
    delete, replace, add, sort, or handle a review issue, call
    `preview_plan_action` instead and pass the related `review_issue_code`.
    For career-fit questions, pass canonical `career_slots` and any explicitly
    named major direction through `major_keywords`. For tuition questions with
    a concrete user cap, pass `tuition_max_per_year`; otherwise 20000 yuan is
    used as the high-tuition review threshold.
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

    plan_file = await _sandbox_data(ctx, "plan/items.json")
    plan_items = _items_from_plan_file(plan_file)
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
    for issue in issues:
        examples = _review_issue_examples_from_plan(issue, plan_items)
        if examples:
            issue["examples"] = examples
        if _as_int(issue.get("affected_count")) <= 0:
            unit_count = len({str(value or "").strip() for value in issue.get("unit_ids") or [] if value})
            volunteer_count = len(
                {str(value or "").strip() for value in issue.get("volunteer_ids") or [] if value}
            )
            issue["affected_count"] = unit_count or volunteer_count or len(examples)
    filtered_issues = [
        issue for issue in issues
        if not issue.get("passed") and _review_focus_matches(issue, normalized_focus)
    ]
    counts = _review_summary_counts(review_file, issues)
    tier_balance = _tier_balance_from_plan_summary(plan_summary)
    normalized_career_slots, career_labels = _review_career_labels(career_slots)
    ordered_total = _as_int(plan_summary.get("ordered_total") or plan_summary.get("ordered_target_total"))
    target_total = _as_int(plan_summary.get("ordered_target_total") or ordered_total)
    resolved_major_keywords = _review_resolved_major_keywords(
        [str(value or "").strip() for value in major_keywords or [] if str(value or "").strip()],
        batch=getattr(ctx.deps, "batch", None) or "01",
    )
    requested_tuition_cap = _as_int(tuition_max_per_year)
    tuition_cap = requested_tuition_cap if requested_tuition_cap > 0 else 20000
    tuition_evidence = _review_tuition_evidence(
        plan_items,
        max_tuition_per_year=tuition_cap,
        plan_total=ordered_total,
    )
    cooperative_evidence = _review_cooperative_evidence(
        plan_items,
        plan_total=ordered_total,
    )
    career_evidence = _review_career_evidence(
        plan_items,
        career_slots=normalized_career_slots,
        major_keywords=resolved_major_keywords,
        plan_total=ordered_total,
    )

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

    message = _review_plan_message(
        focus=normalized_focus,
        counts=counts,
        ordered_total=ordered_total,
        target_total=target_total,
        tier_balance=tier_balance,
        issues=filtered_issues,
        tuition_evidence=tuition_evidence,
        cooperative_evidence=cooperative_evidence,
        career_evidence=career_evidence,
        fix_proposals=fix_proposals,
        generate_fix_proposals=generate_fix_proposals,
    )

    return _json(
        {
            "data": {
                "focus": normalized_focus,
                "review_source": review_source,
                "review_error": review_error,
                "summary": counts,
                "has_plan": True,
                "ordered_total": ordered_total,
                "target_total": target_total,
                "career_slots": normalized_career_slots,
                "career_labels": career_labels,
                "major_keywords": resolved_major_keywords,
                "career_evidence": career_evidence,
                "tuition_evidence": tuition_evidence,
                "cooperative_evidence": cooperative_evidence,
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
    if normalized in {"school", "major", "region", "tuition_budget"}:
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
    for domain in ("major", "school", "region"):
        values = grouped.get(domain) or []
        if values:
            parts.append(f"{labels.get(domain, '参考')}：{'、'.join(values[:6])}")
    return "；".join(parts)


def _materialize_actionable_semantic_requirements(
    intent_type: str,
    *,
    positive: dict[str, Any] | None,
    negative: dict[str, Any] | None,
    semantic_requirements: list[dict[str, Any]] | None,
    batch: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    positive_payload = dict(positive) if isinstance(positive, dict) else {}
    negative_payload = dict(negative) if isinstance(negative, dict) else {}
    if not isinstance(semantic_requirements, list):
        return positive_payload, negative_payload, []
    materialized: list[dict[str, Any]] = []
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
        if domain != intent_type:
            cross_domain_keys = _INTENT_DOMAIN_ATTRIBUTE_KEYS.get(domain, ())
            if key not in cross_domain_keys or key in _CROSS_DOMAIN_ATTRIBUTE_SUPPLEMENT_EXCLUDED_KEYS:
                continue
        values = _semantic_requirement_values(item, key, domain=domain, batch=batch)
        if not values:
            continue
        payload_key = key
        if domain == "school" and key in _SCHOOL_ENTITY_SEMANTIC_KEYS:
            payload_key = "schools"
        elif domain == "major" and key in _MAJOR_ENTITY_SEMANTIC_KEYS:
            payload_key = "major"
        target = negative_payload if side == "negative" else positive_payload
        existing = _as_list(target.get(payload_key))
        added: list[str] = []
        for value in values:
            if value not in existing:
                existing.append(value)
                added.append(value)
        if not added:
            continue
        target[payload_key] = existing
        materialized.append(
            {
                "domain": domain,
                "side": side,
                "key": payload_key,
                "values": added,
                "target_payload_path": f"{side}.{payload_key}",
            }
        )
    return positive_payload, negative_payload, materialized


_GENERIC_COMPLEMENT_MARKERS = ("其他", "其它", "其余", "剩余", "剩下")
_SEMANTIC_VALUE_SUFFIXES = ("专业", "方向", "地区", "地域", "学校", "院校", "类别", "门类", "类", "学")


def _semantic_value_is_generic_complement(value: Any) -> bool:
    compact_value = _compact_text(value)
    return bool(compact_value) and any(marker in compact_value for marker in _GENERIC_COMPLEMENT_MARKERS)


def _semantic_value_is_named_in_span(value: Any, raw_span: str) -> bool:
    compact_value = _compact_text(value)
    compact_span = _compact_text(raw_span)
    if not compact_value or not compact_span:
        return False
    candidates = {compact_value}
    for suffix in _SEMANTIC_VALUE_SUFFIXES:
        if compact_value.endswith(suffix) and len(compact_value) - len(suffix) >= 2:
            candidates.add(compact_value[: -len(suffix)])
    return any(candidate in compact_span for candidate in candidates)


def _drop_synthetic_only_keep_complement(
    intent_type: str,
    negative: dict[str, Any],
    semantic_requirements: list[dict[str, Any]] | None,
    *,
    batch: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Drop model-enumerated complements that were not named by the user.

    `only_keep` already expresses the complement through its positive scope. A
    semantic item such as raw_span="其他专业" must therefore not expand into a
    maintained list of negative disciplines. Explicitly named exclusions remain.
    """
    if not isinstance(negative, dict) or not isinstance(semantic_requirements, list):
        return negative, []

    dropped_by_key: dict[str, set[str]] = {}
    dropped: list[dict[str, Any]] = []
    for item in semantic_requirements:
        if not isinstance(item, dict) or not _semantic_requirement_is_actionable(item):
            continue
        side = _semantic_requirement_side(item.get("side") or item.get("polarity"))
        if side != "negative":
            continue
        raw_span = str(item.get("raw_span") or item.get("rawSpan") or "").strip()
        if not raw_span or not any(marker in raw_span for marker in _GENERIC_COMPLEMENT_MARKERS):
            continue
        domain = _semantic_requirement_domain(item.get("domain") or item.get("intent_type") or item.get("intentType"))
        key = str(item.get("key") or item.get("attribute_key") or item.get("attributeKey") or "").strip()
        if key.startswith("negative_"):
            key = key.removeprefix("negative_")
        key = _canonical_semantic_requirement_key(domain, key)
        if not domain or not key:
            continue
        if domain != intent_type:
            cross_domain_keys = _INTENT_DOMAIN_ATTRIBUTE_KEYS.get(domain, ())
            if key not in cross_domain_keys or key in _CROSS_DOMAIN_ATTRIBUTE_SUPPLEMENT_EXCLUDED_KEYS:
                continue
        payload_key = key
        if domain == "school" and key in _SCHOOL_ENTITY_SEMANTIC_KEYS:
            payload_key = "schools"
        elif domain == "major" and key in _MAJOR_ENTITY_SEMANTIC_KEYS:
            payload_key = "major"
        ungrounded = [
            value
            for value in _semantic_requirement_values(item, key, domain=domain, batch=batch)
            if _semantic_value_is_generic_complement(value)
            or not _semantic_value_is_named_in_span(value, raw_span)
        ]
        if not ungrounded:
            continue
        dropped_by_key.setdefault(payload_key, set()).update(_compact_text(value) for value in ungrounded)
        dropped.append(
            {
                "domain": domain,
                "key": payload_key,
                "values": ungrounded,
                "raw_span": raw_span,
            }
        )

    if not dropped_by_key:
        return negative, []
    canonical = dict(negative)
    for key, compact_values in dropped_by_key.items():
        values = [value for value in _as_list(canonical.get(key)) if _compact_text(value) not in compact_values]
        if values:
            canonical[key] = values
        else:
            canonical.pop(key, None)
    return canonical, dropped


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


def _major_requirement_conflicts(
    normalized: dict[str, Any],
    *,
    batch: str | None,
) -> list[dict[str, str]]:
    positive = normalized.get("positive") if isinstance(normalized.get("positive"), dict) else {}
    negative = normalized.get("negative") if isinstance(normalized.get("negative"), dict) else {}
    negative_by_level = {
        level: {str(value) for value in _as_list(negative.get(level)) if str(value or "").strip()}
        for level in ("level1", "level2", "level3")
    }
    mappings = major_parent_mappings_for_batch(batch)
    level2_to_level1 = mappings.get("level2_to_level1", {})
    level3_to_level2 = mappings.get("level3_to_level2", {})
    conflicts: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    def append(positive_value: str, negative_value: str, relation: str) -> None:
        key = (positive_value, negative_value, relation)
        if key in seen:
            return
        seen.add(key)
        conflicts.append(
            {
                "positive": positive_value,
                "negative": negative_value,
                "relation": relation,
            }
        )

    for level in ("level1", "level2", "level3"):
        for raw_value in _as_list(positive.get(level)):
            value = str(raw_value or "").strip()
            if not value:
                continue
            if value in negative_by_level[level]:
                append(value, value, "same_entity")
            if level == "level2":
                parent_level1 = level2_to_level1.get(value)
                if parent_level1 in negative_by_level["level1"]:
                    append(value, str(parent_level1), "excluded_parent")
            elif level == "level3":
                parent_level2 = level3_to_level2.get(value)
                parent_level1 = level2_to_level1.get(parent_level2 or "")
                if parent_level2 in negative_by_level["level2"]:
                    append(value, str(parent_level2), "excluded_parent")
                if parent_level1 in negative_by_level["level1"]:
                    append(value, str(parent_level1), "excluded_parent")
    return conflicts


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


_CANONICAL_REGION_AREA_MEMBERS = {
    "北上广深": frozenset({"北京", "上海", "广州", "深圳"}),
}


def _collapse_canonical_region_area_members(normalized: dict[str, list[str]]) -> None:
    if normalized["area"]:
        return
    explicit_members = frozenset(normalized["province"] + normalized["city"])
    for area, members in _CANONICAL_REGION_AREA_MEMBERS.items():
        if explicit_members == members:
            normalized["province"] = []
            normalized["city"] = []
            normalized["area"] = [area]
            return


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
    _collapse_canonical_region_area_members(normalized)
    return normalized, ambiguities, display_aliases


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
    if intent_type == "tuition_budget":
        return _normalize_tuition_budget_payload(payload)
    return {}, [], {}


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
    return f"我先把这次{label}整理成待确认预览：{detail}。确认前不会生效。"


def _display_intent_value(value: Any, display_aliases: dict[str, str] | None = None) -> str:
    text = str(value or "").strip()
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
        _tuition_budget_summary_part(tuition_budget),
    ]
    return "；".join(part for part in parts if part) or "本次报考要求"


def _preview_message_from_merged(merged: dict[str, Any], display_aliases: dict[str, str] | None = None) -> str:
    return f"我先把这次报考要求整理成待确认预览：{_intent_summary_from_merged(merged, display_aliases)}。确认前不会生效。"


def _merged_intents_have_values(merged: dict[str, Any]) -> bool:
    for section_name in ("major_intents", "school_intents", "city_intents", "tuition_budget"):
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
    matched_groups: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(matched):
        matched_groups.setdefault(_plan_item_group_key(item, index), item)
    tier_counts: dict[str, int] = {}
    for item in matched_groups.values():
        tier = _normalize_tier(_item_value(item, "tier", "riskTier", "risk_tier")) or "未分层"
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
    return {
        "source": "local_plan_items",
        "available": bool(items),
        "affected_count": len(matched_groups),
        "affected_detail_count": len(matched),
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
    if current_profile is None or intent_type == "tuition_budget" or not hasattr(current_profile, "to_backend_format"):
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
    response = await internal_client.save_pending_confirmation(ctx.deps.sessionid, pending_state)
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
    lowered = text.lower()
    if lowered in {"protect", "protective", "safety", "保底", "兜底", "保险"}:
        return "保"
    if lowered in {"sprint", "reach", "冲刺"}:
        return "冲"
    if lowered in {"stable", "safe", "稳妥"}:
        return "稳"
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
            "group": "group_code",
            "groupCode": "group_code",
            "majorGroup": "group_code",
            "major_group": "group_code",
            "majorGroupCode": "group_code",
            "major_group_code": "group_code",
            "schoolUnitCode": "group_code",
            "school_unit_code": "group_code",
            "pageSize": "limit",
            "page_size": "limit",
        }.get(normalized_key, normalized_key)
        normalized_key = normalize_attribute_filter_key(normalized_key)
        if normalized_key == "tier":
            values = [_normalize_tier(item) for item in normalize_attribute_filter_values("tier", _as_list(value))]
            normalized["tier"] = [item for item in values if item]
        elif normalized_key in {"school_nature", "school", "major", "province", "group_code"}:
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


def _extract_relative_province_scope(filters: dict[str, Any]) -> str:
    aliases = {
        "省内": "inside",
        "本省": "inside",
        "inside": "inside",
        "in_province": "inside",
        "省外": "outside",
        "外省": "outside",
        "outside": "outside",
        "out_of_province": "outside",
    }
    scope = ""
    explicit_values = _as_list(filters.pop("province_scope", None))
    provinces = _as_list(filters.get("province"))
    concrete_provinces: list[str] = []
    for value in [*explicit_values, *provinces]:
        text = str(value or "").strip()
        relative = aliases.get(text.lower())
        if relative:
            scope = relative
        elif value in provinces:
            _append_unique(concrete_provinces, text)
    if concrete_provinces:
        filters["province"] = concrete_provinces
    else:
        filters.pop("province", None)
    return scope


def _matches_relative_province_scope(item: dict[str, Any], *, home_province: str, scope: str) -> bool:
    if not scope:
        return True
    actual = _compact_text(_item_value(item, "provinceName", "province_name", "province"))
    home = _compact_text(home_province)
    if not actual or not home:
        return False
    return actual == home if scope == "inside" else actual != home


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


def _item_group_codes(item: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for raw_value in (
        _item_value(
            item,
            "schoolUnitCode",
            "school_unit_code",
            "majorGroupCode",
            "major_group_code",
            "groupCode",
            "group_code",
            "unitCode",
            "unit_code",
        ),
    ):
        value = str(raw_value or "").strip()
        if not value:
            continue
        result.add(value)
        if "-" in value:
            result.add(value.rsplit("-", 1)[-1])
    return result


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

    group_codes = {str(value or "").strip() for value in _as_list(filters.get("group_code")) if str(value or "").strip()}
    if group_codes and not (_item_group_codes(item) & group_codes):
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

    handled = {
        "school_nature",
        "tier",
        "school",
        "major",
        "group_code",
        "province",
        "tuition_max",
        "tuition_min",
    }
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
        "position": _as_int(
            item.get("_group_ordinal_position")
            or _item_value(item, "position", "rank", "order")
        ),
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


def _plan_item_scope_summary(
    items: list[dict[str, Any]],
    *,
    limit: int,
    total: int | None = None,
    noun: str = "专业组",
) -> str:
    visible_limit = max(1, limit)
    actual_total = max(len(items), _as_int(total))
    summary = "；".join(_plan_item_snippet(item) for item in items[:visible_limit])
    if actual_total > visible_limit:
        summary += f"；以上仅展示前{visible_limit}个，本次实际影响{actual_total}个{noun}"
    return summary


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
            "删除、排序、重排、重新调整等当前方案动作，继续调用 preview_plan_action 生成待确认预览；"
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
    for key in ("unitId", "unit_id", "planSchoolDataId", "plan_school_data_id", "id"):
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
        resolved_item = dict(item)
        resolved_item["_group_ordinal_position"] = position
        result.append(resolved_item)
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


def _add_candidate_reference_filters(
    ctx: RunContext[RequestContext],
    targets: list[str] | None,
    filters: dict[str, Any] | None,
) -> dict[str, Any]:
    normalized_filters, _ = _normalize_plan_query_filters(filters if isinstance(filters, dict) else {})
    if normalized_filters.get("school") and normalized_filters.get("major"):
        return normalized_filters

    raw_targets = _as_list(targets)
    batch = getattr(ctx.deps, "batch", None) or "01"
    if len(raw_targets) == 1:
        reference = resolve_school_major_ref(raw_targets[0], batch)
        if reference.can_query:
            normalized_filters.setdefault("school", reference.school_keywords)
            normalized_filters.setdefault("major", reference.major_keywords)
            return normalized_filters

    schools: list[str] = []
    majors: list[str] = []
    for target in raw_targets:
        school_result = resolve_school_entity(target, batch)
        if school_result.best is not None and not school_result.ambiguous:
            _append_unique(schools, school_result.best.canonical_name)
        major_result = resolve_major_entity(target, batch)
        if major_result.best is not None and not major_result.ambiguous:
            _append_unique(majors, major_result.best.canonical_name)
    if len(schools) == 1 and len(majors) == 1:
        normalized_filters.setdefault("school", schools)
        normalized_filters.setdefault("major", majors)
    return normalized_filters


def _candidate_query_for_filters(filters: dict[str, Any]) -> dict[str, Any]:
    return {
        "tiers": _as_list(filters.get("tier")),
        "province_names": _as_list(filters.get("province")),
        "school_keywords": _as_list(filters.get("school")),
        "major_keywords": _as_list(filters.get("major")),
        "page": 1,
        "page_size": 50,
        "sort_field": "finalScore",
        "sort_order": "desc",
    }


async def _resolve_add_candidate_targets(
    ctx: RunContext[RequestContext],
    targets: list[str] | None,
    filters: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    resolved, missing, direct_reason = await _resolve_plan_targets(ctx, targets, source="candidates")
    if direct_reason == "ok" and not missing and resolved:
        return resolved, {}, "ok"

    normalized_filters = _add_candidate_reference_filters(ctx, targets, filters)
    if not normalized_filters.get("school") or not normalized_filters.get("major"):
        return [], normalized_filters, direct_reason

    batch = getattr(ctx.deps, "batch", None) or "01"
    cached = await _sandbox_data(ctx, "plan/candidates.json")
    matches = [
        item
        for item in _candidate_items(cached)
        if _matches_plan_item(item, normalized_filters, batch=batch)
    ]
    if not matches:
        queried = await _sandbox_data(
            ctx,
            "plan/candidates.json",
            query=_candidate_query_for_filters(normalized_filters),
        )
        matches = [
            item
            for item in _candidate_items(queried)
            if _matches_plan_item(item, normalized_filters, batch=batch)
        ]
    matches = _dedupe_items_by_id(matches, _item_volunteer_id)
    if not matches:
        return [], normalized_filters, "candidate_no_match"

    plan_data = await _sandbox_data(ctx, "plan/items.json")
    selected_volunteer_ids = {
        _item_volunteer_id(item)
        for item in _items_from_plan_file(plan_data)
        if _item_volunteer_id(item)
    }
    matches = [item for item in matches if _item_volunteer_id(item) not in selected_volunteer_ids]
    if not matches:
        return [], normalized_filters, "candidate_already_selected"
    if len(matches) == 1:
        return matches, normalized_filters, "ok"

    unit_ids = {_item_unit_id(item) for item in matches if _item_unit_id(item)}
    if len(unit_ids) == 1:
        return matches, normalized_filters, "ok"
    return matches, normalized_filters, "candidate_ambiguous"


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
    }.get(action, "调整方案")


def _move_target_scope(filters: dict[str, Any], target_position: int) -> str:
    target_tiers = _as_list(filters.get("target_tier") or filters.get("targetTier"))
    target_ordinal = _as_int(filters.get("target_ordinal") or filters.get("targetOrdinal"))
    if target_tiers and target_ordinal > 0:
        tier_label = _tier_display_label([_normalize_tier(target_tiers[0])])
        return f"{tier_label}第{target_ordinal}位（方案第{target_position}位）"
    return f"方案第{target_position}位"


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
    source_version: int | None = None,
) -> dict[str, Any]:
    source_version = _as_int(source_version)
    if source_version <= 0:
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
    response = await internal_client.save_pending_confirmation(ctx.deps.sessionid, pending_state)
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
        or raw_data.get("sourceVersion")
        or raw_data.get("planningVersion")
    )


def _pending_command_operation_id(pending: dict[str, Any], command_type: str) -> str:
    raw = pending.get("raw") if isinstance(pending.get("raw"), dict) else {}
    # J5.5b：prepare 产出的 operationId 是幂等执行键（Java 台账按它去重），
    # 有就必须用；uuid5 只是旧卡片没有该字段时的稳定兜底。
    operation_id = str(
        pending.get("operationId") or pending.get("operation_id") or raw.get("operationId") or ""
    ).strip()
    if operation_id:
        return operation_id
    pending_id = str(pending.get("pending_id") or pending.get("pendingId") or raw.get("pendingId") or "").strip()
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"zhiyuan:{pending_id}:{command_type}"))


def _pending_claim_token(pending: dict[str, Any]) -> str:
    raw = pending.get("raw") if isinstance(pending.get("raw"), dict) else {}
    return str(raw.get("_pendingClaimToken") or raw.get("claimToken") or "").strip()


def _review_fix_candidate_from_tool_return(content: Any) -> dict[str, Any] | None:
    """从 `preview_plan_change` 的工具回包里取回只读预览冻结的确认依据。

    运行时历史可能被裁剪（`_compact_tool_return_content`），所以候选既可能在
    `data.review_fix_prepare_candidate`，也可能被提到顶层；两者都认。
    """
    if not isinstance(content, str):
        return None
    try:
        parsed = json.loads(content)
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    data = parsed.get("data") if isinstance(parsed.get("data"), dict) else {}
    candidate = data.get("review_fix_prepare_candidate")
    if not isinstance(candidate, dict):
        candidate = parsed.get("review_fix_prepare_candidate")
    if isinstance(candidate, dict):
        proposal_id = str(candidate.get("proposal_id") or candidate.get("proposalId") or "").strip()
        proposal_source = str(
            candidate.get("proposal_source") or candidate.get("proposalSource") or ""
        ).strip()
        if proposal_id and (not proposal_source or proposal_source == "review_check"):
            normalized = dict(candidate)
            normalized["proposal_id"] = proposal_id
            normalized["proposal_source"] = "review_check"
            return normalized
    proposal = data.get("proposal")
    if isinstance(proposal, dict):
        proposal_id = str(proposal.get("proposal_id") or proposal.get("proposalId") or "").strip()
        proposal_source = str(
            proposal.get("proposal_source") or proposal.get("proposalSource") or ""
        ).strip()
        if proposal_id and proposal_source == "review_check":
            proposal_apply = (
                data.get("proposal_apply") if isinstance(data.get("proposal_apply"), dict) else {}
            )
            return {
                "proposal_id": proposal_id,
                "proposal_source": "review_check",
                "source_version_guard": _as_int(
                    proposal.get("source_version")
                    or proposal.get("sourceVersion")
                    or proposal.get("sourceVersionGuard")
                ),
                "command_digest": str(
                    proposal.get("command_digest") or proposal.get("commandDigest") or ""
                ).strip(),
                "preview_digest": str(
                    proposal.get("preview_digest") or proposal.get("previewDigest") or ""
                ).strip(),
                "evaluation_version": str(
                    proposal.get("evaluation_version") or proposal.get("evaluationVersion") or ""
                ).strip(),
                "title": str(proposal.get("title") or "").strip(),
                "summary": str(proposal.get("summary") or "").strip(),
                "impact": str(proposal.get("impact") or "").strip(),
                "proposal_apply": dict(proposal_apply),
            }
    return None


def _latest_review_fix_prepare_candidate(
    ctx: RunContext[RequestContext],
) -> dict[str, Any] | None:
    """按时间倒序扫描消息历史，找最近一次只读审查修复预览的冻结候选。

    先扫当前 RunContext 的消息（本轮新产生的优先），再扫服务端补进来的
    运行时历史（直连短文本桥没有 `ctx.messages`）。两个来源不能混在一起
    倒序，否则本轮的预览会被上一轮的旧回包盖住。
    """
    sources: list[list[Any]] = []
    ctx_messages = getattr(ctx, "messages", None)
    if ctx_messages:
        sources.append(list(ctx_messages))
    agent_messages = getattr(ctx.deps, "agent_messages", None)
    if agent_messages:
        sources.append(list(agent_messages))
    for messages in sources:
        for message in reversed(messages):
            for part in reversed(list(getattr(message, "parts", []) or [])):
                if not isinstance(part, ToolReturnPart) or part.tool_name != "preview_plan_change":
                    continue
                candidate = _review_fix_candidate_from_tool_return(part.content)
                if candidate:
                    return candidate
    return None


def _pending_resource_raw(response: Any) -> dict[str, Any]:
    """从 `GET /session/pending` 回包解析 dataValue + 修订/领取信息。"""
    if not isinstance(response, dict):
        return {}
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    value = data.get("pendingConfirmation")
    if value is None:
        value = data.get("dataValue")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return {}
    if not isinstance(value, dict) or not value:
        return {}
    raw = dict(value)
    revision = _as_int(data.get("revision"))
    if revision > 0:
        raw["_pendingRevision"] = revision
        raw["revision"] = revision
    claim_token = str(data.get("claimToken") or "").strip()
    if claim_token:
        raw["_pendingClaimToken"] = claim_token
    claim_expires_at = data.get("claimExpiresAt")
    if claim_expires_at not in (None, ""):
        raw["_pendingClaimExpiresAt"] = claim_expires_at
    status = str(data.get("status") or raw.get("status") or "").strip()
    if status:
        raw.setdefault("status", status)
    return raw


def _review_fix_proposal_apply_from_pending(
    raw_pending: dict[str, Any],
    candidate: dict[str, Any],
    *,
    source_version: int,
) -> dict[str, Any]:
    """构造 `apply_plan_change_proposal` 的扁平请求体；pending 权威值优先。"""
    proposal_id = str(
        raw_pending.get("proposalId") or candidate.get("proposal_id") or ""
    ).strip()
    guard = _as_int(raw_pending.get("sourceVersion")) or _as_int(
        candidate.get("source_version_guard")
    ) or source_version
    payload: dict[str, Any] = {
        "proposalId": proposal_id,
        "proposalSource": "review_check",
        "sourceVersionGuard": guard,
        "regenerateOrderedPlan": True,
        "rerunReview": True,
    }
    for camel, candidate_key in (
        ("commandDigest", "command_digest"),
        ("previewDigest", "preview_digest"),
        ("evaluationVersion", "evaluation_version"),
        ("canonicalObjectiveDigest", "canonical_objective_digest"),
        ("solverVersion", "solver_version"),
        ("solverInputDigest", "solver_input_digest"),
        ("hardObjectiveVersion", "hard_objective_version"),
    ):
        value = raw_pending.get(camel)
        if value is None:
            value = candidate.get(candidate_key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            payload[camel] = text
    return payload


async def _prepare_review_fix_pending(
    ctx: RunContext[RequestContext],
    candidate: dict[str, Any],
) -> tuple[dict[str, Any] | None, str]:
    """只读预览的确认回合：先 prepare 冻结 pending，再交给原 claim→execute 流程。

    幂等键由 `chatSessionId + proposalId + previewDigest` 派生：同一张卡重试
    确认会命中 Java 的 requestId 重放，不会生成第二份预览/第二个 operationId。
    """
    proposal_id = str(candidate.get("proposal_id") or "").strip()
    preview_digest = str(candidate.get("preview_digest") or "").strip()
    command_digest = str(candidate.get("command_digest") or "").strip()
    evaluation_version = str(candidate.get("evaluation_version") or "").strip()
    source_version = _as_int(candidate.get("source_version_guard"))
    if not proposal_id:
        return None, "没有找到可确认的审查修复提案，请重新生成预览后再确认。"
    if source_version <= 0 or not preview_digest or not command_digest:
        return None, "这份审查修复预览缺少确认所需的冻结信息，请重新生成预览后再确认。"
    request_id = f"review-prepare:{ctx.deps.sessionid}:{proposal_id}:{preview_digest[:16]}"
    response = await internal_client.prepare_review_fix_proposal(
        getattr(ctx.deps, "tenant_id", 1),
        ctx.deps.sessionid,
        request_id=request_id,
        payload={
            "proposalId": proposal_id,
            "previewDigest": preview_digest,
            "commandDigest": command_digest,
            "evaluationVersion": evaluation_version,
            "sourceVersionGuard": source_version,
            "regenerateOrderedPlan": True,
            "rerunReview": True,
        },
    )
    if not _is_success_response(response):
        return None, (
            "这次确认没能冻结审查修复预览（方案或审查可能已变化），本轮不会改动方案；"
            "请重新生成预览后再确认。"
        )
    prepare_data = response.get("data") if isinstance(response.get("data"), dict) else {}
    status = str(prepare_data.get("status") or "").strip().lower()
    pending_id = str(prepare_data.get("pendingId") or "").strip()
    operation_id = str(prepare_data.get("operationId") or "").strip()
    if status == "superseded":
        return None, "这张审查修复卡已被更新的预览取代，本轮不会执行；请按最新预览重新确认。"
    if status == "preparing":
        return None, "这份预览的待确认内容还在生成中，请稍后再确认。"
    if status not in {"prepared", "duplicate"} or not pending_id or not operation_id:
        return None, "这次确认没有生成可执行的待确认内容，本轮不会改动方案；请重新生成预览后再确认。"
    snapshot_response = await internal_client.get_last_pending_confirmation(ctx.deps.sessionid)
    raw_pending = _pending_resource_raw(snapshot_response)
    if not raw_pending:
        return None, "这次确认没有找到对应的待确认内容，本轮不会改动方案；请刷新后重试。"
    raw_pending_id = str(
        raw_pending.get("pendingId") or raw_pending.get("pending_id") or ""
    ).strip()
    if raw_pending_id and raw_pending_id != pending_id:
        return None, "当前待确认内容已经变化，本轮不会执行；请刷新后按最新预览重新确认。"
    raw_status = str(raw_pending.get("status") or "").strip()
    if raw_status and raw_status != "active":
        return None, "这次待确认内容已被处理或已失效，本轮不会重复执行。请刷新后以最新状态为准。"
    proposal_apply = _review_fix_proposal_apply_from_pending(
        raw_pending, candidate, source_version=source_version
    )
    if not proposal_apply.get("previewDigest") or not proposal_apply.get("commandDigest"):
        return None, "这次确认缺少冻结摘要，本轮不会改动方案；请重新生成预览后再确认。"
    summary = str(
        raw_pending.get("summary")
        or candidate.get("summary")
        or candidate.get("title")
        or ""
    ).strip()
    return {
        "active": True,
        "pending_id": pending_id,
        "pendingId": pending_id,
        "operationId": operation_id,
        "kind": "plan_change_proposal",
        "action_family": "apply_plan_change_proposal",
        "summary": summary,
        "affected_scope": str(candidate.get("impact") or summary or "当前方案").strip(),
        "source_backend_version": _as_int(raw_pending.get("sourceVersion")) or source_version,
        "execution_payload": {
            "action_family": "apply_plan_change_proposal",
            "proposal_apply": proposal_apply,
            "postconditions": {
                "proposal_id": proposal_id,
                "proposal_source": "review_check",
                "post_validation_required": True,
            },
        },
        "raw": raw_pending,
    }, ""


def _pending_command_execution_uncertain(response: dict[str, Any] | None) -> bool:
    if not isinstance(response, dict):
        return True
    if response.get("error") or response.get("success") is False:
        return True
    if _as_int(response.get("code"), -1) == 40903:
        message = str(response.get("msg") or response.get("message") or "").strip().lower()
        return "already running" in message
    return "code" not in response


async def _mark_pending_status(
    ctx: RunContext[RequestContext], pending: dict[str, Any], status: str, **extra: Any
) -> dict[str, Any]:
    if _dry_run_state_mutations(ctx):
        return {"code": 0, "data": {"transitionApplied": False}}
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
    return await internal_client.save_pending_confirmation(ctx.deps.sessionid, state)


def _invalidate_after_pending_action(ctx: RunContext[RequestContext], kind: str, action_family: str) -> None:
    sandbox = getattr(ctx.deps, "sandbox", None)
    if sandbox is None:
        return
    paths = ["pending.json"]
    if kind == "intent_change":
        paths.extend(["profile.json", "constraints.json", "plan/candidates.json"])
        if action_family in {"generate_plan", "regenerate_order", "apply_selected_intents"}:
            paths.extend(["plan/summary.json", "plan/items.json", "plan/review.json"])
    elif kind in {"plan_mutation", "plan_generation", "plan_change_proposal"}:
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
    constraint_update: dict[str, Any] | None = None
    if has_constraint_payload:
        constraint_update = {"intentMode": "constraint"}
        if major_preferences is not None:
            constraint_update["majorPreferences"] = major_preferences
        if school_preferences is not None:
            constraint_update["schoolPreferences"] = school_preferences
        if region_preferences is not None:
            constraint_update["regionPreferences"] = region_preferences
    tenant_id = getattr(ctx.deps, "tenant_id", 1)
    min_tuition, max_tuition = _tuition_budget_bounds(merged)
    command_type = "apply_constraint_and_regenerate"
    response = await internal_client.execute_pending_planning_command(
        tenant_id,
        ctx.deps.sessionid,
        operation_id=_pending_command_operation_id(pending, command_type),
        pending_id=str(pending.get("pending_id") or pending.get("pendingId") or ""),
        claim_token=_pending_claim_token(pending),
        expected_plan_version=_pending_source_version(pending),
        command_type=command_type,
        constraint_update=constraint_update,
        min_tuition_per_year=min_tuition if max_tuition > 0 else None,
        max_tuition_per_year=max_tuition if max_tuition > 0 else None,
        regenerate_ordered_plan=has_plan and apply_to_current_plan,
    )
    if _pending_command_execution_uncertain(response):
        return False, {
            "reason": "pending_command_result_uncertain",
            "execution_uncertain": True,
            "backend_response": response,
        }, "这次操作结果还在确认中，不会重复执行；请稍后刷新后再确认状态。"
    success = _is_success_response(response)
    command_data = response.get("data") if isinstance(response.get("data"), dict) else {}
    completed_steps = command_data.get("completedSteps") if isinstance(command_data.get("completedSteps"), list) else []
    planning_state = command_data.get("planningState") if isinstance(command_data.get("planningState"), dict) else {}
    ordered_response = {"code": 0, "data": planning_state} if success and planning_state else None
    constraint_success = success and (not has_constraint_payload or "constraint_updated" in completed_steps)
    tuition_budget_applied = success and (max_tuition <= 0 or "tuition_updated" in completed_steps)
    plan_regenerated = success and has_plan and apply_to_current_plan and "ordered_plan_regenerated" in completed_steps

    data = {
        "intent_mode": intent_mode,
        "constraint_type": constraint_type,
        "merged": merged,
        "backend_response": response,
        "constraint_state_applied": constraint_success,
        "tuition_budget_response": response if max_tuition > 0 else None,
        "tuition_budget_applied": tuition_budget_applied,
        "has_plan": has_plan,
        "apply_to_current_plan": apply_to_current_plan,
        "requires_candidate_pool_rebuild": False,
        "candidate_pool_regenerated": False,
        "plan_regenerated": plan_regenerated,
        "operation_id": command_data.get("operationId"),
        "operation_replayed": bool(command_data.get("replayed")),
        "completed_steps": completed_steps,
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
    if constraint_success and has_constraint_payload:
        # 确认成功之后，把**同源意向**并入 userprofile（排序输入通道；评审 §五-31a）：
        # 名字/值取自同一份 merged（与 constraintUpdate 同源），只并集、正压负、写回带 code。
        # 旁路：失败只留日志，不改这次确认的结论（`merged` 里的属性键由上游走 constraintUpdate，
        # 这里只认标准键）。
        await merge_confirmed_intents_into_profile(
            ctx.deps.sessionid,
            batch=getattr(ctx.deps, "batch", None) or "01",
            major_intents=merged.get("major_intents"),
            school_intents=merged.get("school_intents"),
            region_intents=merged.get("city_intents"),
        )
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


def _tier_quota_postcondition_label(result: dict[str, Any]) -> str:
    quota_type = str(result.get("type") or "").strip()
    if not quota_type:
        effective_goal = result.get("effectiveGoal")
        if not isinstance(effective_goal, dict):
            effective_goal = result.get("effective_goal")
        if isinstance(effective_goal, dict):
            quota_type = str(effective_goal.get("type") or "").strip()
    return {
        "exact_counts": "冲稳保精确配额",
        "count_ranges": "冲稳保数量范围",
        "ratios": "冲稳保比例",
    }.get(quota_type, "冲稳保配额")


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
    if action_family == "apply_plan_change_proposal":
        proposal_apply = (
            execution_payload.get("proposal_apply")
            if isinstance(execution_payload.get("proposal_apply"), dict)
            else {}
        )
        if not proposal_apply:
            return (
                False,
                {"reason": "missing_plan_change_proposal_apply"},
                "这次方案调整预览缺少后端 Proposal 执行结构，请重新生成预览。",
            )
        command_type = "apply_plan_change_proposal"
        command_response = await internal_client.execute_pending_planning_command(
            getattr(ctx.deps, "tenant_id", 1),
            ctx.deps.sessionid,
            operation_id=_pending_command_operation_id(pending, command_type),
            pending_id=str(pending.get("pending_id") or pending.get("pendingId") or ""),
            claim_token=_pending_claim_token(pending),
            expected_plan_version=_pending_source_version(pending),
            command_type=command_type,
            proposal_apply=proposal_apply,
        )
        if _pending_command_execution_uncertain(command_response):
            return False, {
                "reason": "pending_command_result_uncertain",
                "execution_uncertain": True,
                "backend_response": command_response,
            }, "这次方案调整结果还在确认中，不会重复执行；请稍后刷新后再确认状态。"
        command_data = command_response.get("data") if isinstance(command_response.get("data"), dict) else {}
        postcondition = (
            command_data.get("postconditionReport")
            if isinstance(command_data.get("postconditionReport"), dict)
            else {}
        )
        success = _is_success_response(command_response) and postcondition.get("satisfied") is True
        data = {
            "action_family": action_family,
            "operation_id": command_data.get("operationId"),
            "operation_replayed": bool(command_data.get("replayed")),
            "completed_steps": command_data.get("completedSteps") or [],
            "postcondition_report": postcondition,
            "backend_response": command_response,
        }
        if success:
            target_count = _as_int(postcondition.get("targetCount"))
            count_mode = str(postcondition.get("countMode") or "").strip()
            domain = "专业组" if count_mode == "unit" else "志愿"
            requirement_count = _as_int(postcondition.get("requirementCount"))
            priority_rule_count = _as_int(postcondition.get("priorityRuleCount"))
            tier_quota_result = (
                postcondition.get("tierQuotaResult")
                if isinstance(postcondition.get("tierQuotaResult"), dict)
                else {}
            )
            proposal_source = str(postcondition.get("proposalSource") or "").strip()
            if proposal_source == "review_check":
                summary = str(pending.get("summary") or "").strip().rstrip("。")
                affected_unit_count = _as_int(postcondition.get("affectedUnitCount"))
                added_volunteer_count = _as_int(postcondition.get("addedVolunteerCount"))
                impact_parts: list[str] = []
                if affected_unit_count > 0:
                    impact_parts.append(f"调整{affected_unit_count}个专业组")
                if added_volunteer_count > 0:
                    impact_parts.append(f"补入{added_volunteer_count}个专业")
                result_text = "已按预览完成方案调整"
                if summary:
                    result_text += f"：{summary}"
                if impact_parts:
                    result_text += f"；{'、'.join(impact_parts)}"
                return True, data, f"{result_text}；复审校验通过。"
            if target_count > 0:
                checks = ["数量"]
                if requirement_count > 0:
                    checks.append(f"{requirement_count}条要求")
                if priority_rule_count > 0:
                    checks.append(f"{priority_rule_count}条同档优先规则")
                if tier_quota_result.get("satisfied") is True:
                    checks.append(_tier_quota_postcondition_label(tier_quota_result))
                return True, data, (
                    f"已按预览调整方案，当前共{target_count}个{domain}，"
                    f"{'和'.join(checks)}校验通过。"
                )
            return True, data, (
                f"已按预览调整方案，{priority_rule_count}条同档优先规则"
                "已持久化且排序校验通过。"
            )
        data["reason"] = "plan_change_postcondition_not_satisfied"
        return False, data, "这次调整没有通过最终目标校验，操作未完成，请按最新方案重新生成预览。"

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
        command_type = "add_units"
        command_response = await internal_client.execute_pending_planning_command(
            tenant_id,
            ctx.deps.sessionid,
            operation_id=_pending_command_operation_id(pending, command_type),
            pending_id=str(pending.get("pending_id") or pending.get("pendingId") or ""),
            claim_token=_pending_claim_token(pending),
            expected_plan_version=_pending_source_version(pending),
            command_type=command_type,
            volunteer_ids=volunteer_ids,
            regenerate_ordered_plan=True,
        )
        if _pending_command_execution_uncertain(command_response):
            return False, {
                "reason": "pending_command_result_uncertain",
                "execution_uncertain": True,
                "backend_response": command_response,
            }, "这次加入结果还在确认中，不会重复执行；请稍后刷新后再确认状态。"
        command_data = command_response.get("data") if isinstance(command_response.get("data"), dict) else {}
        planning_state = command_data.get("planningState") if isinstance(command_data.get("planningState"), dict) else {}
        ordered_response = (
            {"code": 0, "data": planning_state}
            if _is_success_response(command_response) and planning_state
            else command_response
        )
        success = _is_success_response(ordered_response)
        return success, {
            "action_family": action_family,
            "selected_volunteer_ids": volunteer_ids,
            "operation_id": command_data.get("operationId"),
            "operation_replayed": bool(command_data.get("replayed")),
            "completed_steps": command_data.get("completedSteps") or [],
            "backend_response": ordered_response,
        }, ("已加入所选志愿并刷新排序方案。" if success else "这次加入方案没有执行成功，请重新生成预览。")
    if action_family == "replace_units":
        unit_ids = _plan_unit_ids(payload, atomic)
        volunteer_ids = _plan_volunteer_ids(payload, atomic)
        if not unit_ids or not volunteer_ids:
            return False, {"reason": "missing_replace_args"}, "这次替换方案缺少要移出的志愿组或要加入的候选志愿，请重新生成预览。"
        command_type = "replace_units"
        command_response = await internal_client.execute_pending_planning_command(
            tenant_id,
            ctx.deps.sessionid,
            operation_id=_pending_command_operation_id(pending, command_type),
            pending_id=str(pending.get("pending_id") or pending.get("pendingId") or ""),
            claim_token=_pending_claim_token(pending),
            expected_plan_version=_pending_source_version(pending),
            command_type=command_type,
            unit_ids=unit_ids,
            volunteer_ids=volunteer_ids,
            regenerate_ordered_plan=True,
        )
        if _pending_command_execution_uncertain(command_response):
            return False, {
                "reason": "pending_command_result_uncertain",
                "execution_uncertain": True,
                "backend_response": command_response,
            }, "这次替换结果还在确认中，不会重复执行；请稍后刷新后再确认状态。"
        command_data = command_response.get("data") if isinstance(command_response.get("data"), dict) else {}
        planning_state = command_data.get("planningState") if isinstance(command_data.get("planningState"), dict) else {}
        ordered_response = (
            {"code": 0, "data": planning_state}
            if _is_success_response(command_response) and planning_state
            else command_response
        )
        success = _is_success_response(ordered_response)
        data = {
            "action_family": action_family,
            "unit_ids": unit_ids,
            "selected_volunteer_ids": volunteer_ids,
            "operation_id": command_data.get("operationId"),
            "operation_replayed": bool(command_data.get("replayed")),
            "completed_steps": command_data.get("completedSteps") or [],
            "backend_response": ordered_response,
        }
        message = "已完成替换并刷新排序方案。" if success else "这次替换没有执行成功，请重新生成预览。"
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
    tool normalizes structured payloads and materializes actionable items from
    semantic_requirements; it does not infer extra requirements from raw_user_text.

    Args:
        intent_type: Domain being changed. Must be major, school, region, or tuition_budget.
        positive: Things the user explicitly wants, keeps, or requires. For major
            requirements preserve the named taxonomy level: level1 for a named
            discipline such as 管理学/医学/工学, level2 for a named category such as
            工商管理类/计算机类, and major for a specific major.
        negative: Things the user explicitly rejects. Use this for phrases like
            "不要X", "排除X", "不考虑X", and "避开X". Preserve the same major
            taxonomy level and never narrow a named discipline to one category.
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
        raw_user_text: The original user message. Used for display refinement and
            diagnostics; do not rely on it to fill entities.
        semantic_requirements: Model-interpreted requirement/reference items from
            this turn. Each item should include domain, side, strength, key, values,
            and raw_span when available. Use strength=explicit or confirmable for
            items that should be included in the pending preview. Use
            strength=reference only when the user explicitly limits an item to
            reference/read-only use and says not to record or adjust it; ordinary
            "优先/倾向/重点关注" wording remains actionable. Recognized items are materialized
            into missing positive/negative fields from this structured list, never
            from raw_user_text scanning.
    """
    normalized_type = str(intent_type or "").strip().lower()
    if normalized_type not in {"major", "school", "region", "tuition_budget"}:
        return _json(
            {
                "data": {
                    "intent_type": intent_type,
                    "allowed_intent_types": ["major", "school", "region", "tuition_budget"],
                },
                "next_step": "clarify",
                "message": "需要说明这是专业、院校、地域还是学费预算要求。",
            }
        )
    normalized_constraint = str(constraint_type or "exclude").strip() or "exclude"
    if normalized_constraint not in {"exclude", "only_keep", "must_have"}:
        normalized_constraint = "exclude"

    batch = ctx.deps.batch or "01"
    effective_raw_user_text = _effective_raw_user_text(ctx, raw_user_text)
    positive, negative, materialized_semantic_requirements = _materialize_actionable_semantic_requirements(
        normalized_type,
        positive=positive,
        negative=negative,
        semantic_requirements=semantic_requirements,
        batch=batch,
    )
    dropped_only_keep_complement: list[dict[str, Any]] = []
    if normalized_constraint == "only_keep":
        negative, dropped_only_keep_complement = _drop_synthetic_only_keep_complement(
            normalized_type,
            negative,
            semantic_requirements,
            batch=batch,
        )
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
    parameter_warnings: list[str] = []
    if dropped_only_keep_complement:
        parameter_warnings.append(
            "only_keep 已由正向范围表达，已忽略未在原始语义片段中点名的负向补集"
        )
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

    if normalized_type == "major":
        requirement_conflicts = _major_requirement_conflicts(normalized, batch=batch)
        if requirement_conflicts:
            first = requirement_conflicts[0]
            if first["relation"] == "same_entity":
                detail = f"{first['positive']}同时出现在要和不要中"
            else:
                detail = f"{first['positive']}属于已排除的{first['negative']}范围"
            return _json(
                {
                    "data": {
                        "intent_type": normalized_type,
                        "constraint_type": normalized_constraint,
                        "normalized": normalized,
                        "conflicts": requirement_conflicts,
                        "pending_created": False,
                        "requires_confirmation": False,
                        "reason": "major_requirement_conflict",
                    },
                    "next_step": "clarify",
                    "message": (
                        f"这次专业要求存在冲突：{detail}。请先确认这个专业是要保留为例外，还是也要排除；"
                        "确认前不会记录要求，也不会调整方案。"
                    ),
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
    affected_detail_count = _as_int(plan_impact.get("affected_detail_count"))
    if affected_count > 0:
        affected_text = f"{affected_count}个相关专业组"
        if affected_detail_count > affected_count:
            affected_text += f"、涉及{affected_detail_count}条专业志愿"
        if apply_to_current_plan:
            message += f" 当前方案里初步看到{affected_text}，采纳后会按这个要求重新调整方案。"
        else:
            message += f" 当前方案里初步看到{affected_text}；采纳后会先记为报考要求，这次不改当前方案。"
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
                "materialized_semantic_requirements": materialized_semantic_requirements,
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


_PLAN_CHANGE_REQUIREMENT_KEYS = {
    "school": {
        "school",
        "schools",
        "school_nature",
        "program_type",
        "school_category",
        "school_level",
        "school_tag",
    },
    "region": {"province", "city", "area", "region_group"},
    "major": {"major", "level1", "level2", "level3", "major_tag"},
    "admission": {"tier"},
}
_PLAN_CHANGE_REQUIREMENT_KEY_ALIASES = {
    "schoolnature": "school_nature",
    "schoolnaturetype": "school_nature",
    "programtype": "program_type",
    "enrollment_type": "program_type",
    "enrollmenttype": "program_type",
    "schoolcategory": "school_category",
    "schoollevel": "school_level",
    "schooltag": "school_tag",
    "regiongroup": "region_group",
    "majorname": "major",
    "major_name": "major",
    "majortag": "major_tag",
    "admissionstability": "tier",
    "admission_stability": "tier",
    "risktier": "tier",
    "risk_tier": "tier",
}


def _plan_change_requirements_from_active_intent_pending(
    ctx: RunContext[RequestContext],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    execution_payload = _active_intent_pending_execution_payload(ctx)
    if not isinstance(execution_payload, dict):
        return [], [{"reason": "active_pending_is_not_mergeable_intent"}]
    merged = execution_payload.get("merged")
    if not isinstance(merged, dict) or not _merged_intents_have_values(merged):
        merged = _merge_selected_values(_selected_values_from_pending_payload(execution_payload))
    if not _merged_intents_have_values(merged):
        return [], [{"reason": "active_intent_payload_empty"}]

    constraint_type = _constraint_type_from_execution_payload(execution_payload)
    pending = _turn_started_active_pending(ctx)
    raw_text = str(getattr(pending, "preview_summary", "") or "").strip()
    section_specs = {
        "major_intents": (
            "major",
            {"level1": "level1", "level2": "level2", "level3": "level3", "major_tag": "major_tag"},
        ),
        "school_intents": (
            "school",
            {
                "colleges": "school",
                "school_nature": "school_nature",
                "program_type": "program_type",
                "school_category": "school_category",
                "school_level": "school_level",
                "school_tag": "school_tag",
            },
        ),
        "city_intents": (
            "region",
            {"province": "province", "city": "city", "area": "area"},
        ),
    }
    requirements: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    only_keep_domains: set[str] = set()
    for section, payload in merged.items():
        if str(section or "").startswith("_") or not isinstance(payload, dict):
            continue
        section_spec = section_specs.get(section)
        if section_spec is None:
            if _payload_has_values(payload):
                errors.append({"reason": "unsupported_intent_section", "section": section})
            continue
        domain, key_map = section_spec
        for raw_key, raw_values in payload.items():
            values = _as_list(raw_values)
            if not values:
                continue
            negative = str(raw_key or "").startswith("negative_")
            base_key = str(raw_key or "").removeprefix("negative_")
            key = key_map.get(base_key)
            if key is None:
                errors.append({"reason": "unsupported_intent_key", "section": section, "key": raw_key})
                continue
            kind = "exclude" if negative else "only_keep" if constraint_type == "only_keep" else "include"
            if kind == "only_keep" and domain in only_keep_domains:
                errors.append(
                    {"reason": "multiple_only_keep_keys_in_domain", "domain": domain, "key": key}
                )
                continue
            if kind == "only_keep":
                only_keep_domains.add(domain)
            requirement = {
                "kind": kind,
                "domain": domain,
                "key": key,
                "values": values,
                "raw_text": raw_text,
            }
            if kind == "include":
                requirement["min_count"] = 1
            requirements.append(requirement)
    return requirements, errors


def _merge_normalized_plan_change_requirements(
    current: list[dict[str, Any]],
    carried: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    only_keep_by_domain: dict[str, str] = {}
    errors: list[dict[str, Any]] = []
    for item in [*current, *carried]:
        identity = _json(
            {
                "kind": item.get("kind"),
                "domain": item.get("domain"),
                "key": item.get("key"),
                "values": item.get("values") or [],
                "minCount": item.get("minCount"),
            }
        )
        if identity in seen:
            continue
        if item.get("kind") == "only_keep":
            domain = str(item.get("domain") or "").strip()
            previous = only_keep_by_domain.get(domain)
            if previous is not None and previous != identity:
                errors.append({"reason": "duplicate_only_keep_domain", "domain": domain})
                continue
            only_keep_by_domain[domain] = identity
        seen.add(identity)
        merged.append(item)
    return merged, errors


def _normalize_plan_change_requirements(
    requirements: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if requirements in (None, []):
        return [], []
    if not isinstance(requirements, list):
        return [], [{"reason": "requirements_must_be_list"}]
    normalized: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    only_keep_domains: set[str] = set()
    for index, requirement in enumerate(requirements):
        if not isinstance(requirement, dict):
            errors.append({"index": index, "reason": "requirement_must_be_object"})
            continue
        unsupported_fields = sorted(
            key
            for key, value in requirement.items()
            if key not in {
                "kind", "domain", "side", "strength", "key", "values", "min_count", "minCount",
                "raw_text", "rawText",
            }
            and value not in (None, "", [], {})
        )
        raw_kind = str(requirement.get("kind") or "").strip().lower()
        side = str(requirement.get("side") or "").strip().lower()
        if not raw_kind and side == "negative":
            raw_kind = "exclude"
        domain = str(requirement.get("domain") or "").strip().lower()
        raw_key = str(requirement.get("key") or "").strip()
        compact_key = raw_key.replace("-", "_").replace(" ", "")
        key = _PLAN_CHANGE_REQUIREMENT_KEY_ALIASES.get(
            compact_key.lower(), compact_key.lower()
        )
        values = []
        for raw_value in _as_list(requirement.get("values")):
            value = str(raw_value or "").strip()
            if value and value not in values:
                values.append(value)
        invalid_tier_values: list[str] = []
        if domain == "admission" and key == "tier":
            normalized_tiers: list[str] = []
            for value in values:
                tier = _normalize_tier(value)
                if tier not in {"冲", "稳", "保"}:
                    invalid_tier_values.append(value)
                elif tier not in normalized_tiers:
                    normalized_tiers.append(tier)
            values = normalized_tiers
        strength = str(requirement.get("strength") or "explicit").strip().lower()
        raw_min_count = requirement.get("min_count", requirement.get("minCount"))
        min_count = 1 if raw_min_count is None else _as_int(raw_min_count)
        reason = ""
        if unsupported_fields:
            reason = "unsupported_fields"
        elif raw_kind not in {"exclude", "only_keep", "include"}:
            reason = "unsupported_kind"
        elif domain not in _PLAN_CHANGE_REQUIREMENT_KEYS:
            reason = "unsupported_domain"
        elif key not in _PLAN_CHANGE_REQUIREMENT_KEYS.get(domain, set()):
            reason = "unsupported_key"
        elif domain == "admission" and raw_kind != "include":
            reason = "tier_only_supported_for_include"
        elif domain == "admission" and raw_min_count is None:
            reason = "tier_min_count_required"
        elif invalid_tier_values:
            reason = "unsupported_tier_value"
        elif not values:
            reason = "values_required"
        elif raw_kind != "include" and raw_min_count is not None:
            reason = "min_count_only_supported_for_include"
        elif raw_kind == "include" and (
            isinstance(raw_min_count, bool) or min_count <= 0
        ):
            reason = "min_count_must_be_positive_integer"
        elif strength == "reference":
            reason = "reference_is_not_hard_requirement"
        elif raw_kind == "only_keep" and domain in only_keep_domains:
            reason = "duplicate_only_keep_domain"
        if reason:
            errors.append(
                {
                    "index": index,
                    "reason": reason,
                    "kind": raw_kind,
                    "domain": domain,
                    "key": key,
                    "invalid_tier_values": invalid_tier_values,
                    "unsupported_fields": unsupported_fields,
                }
            )
            continue
        if raw_kind == "only_keep":
            only_keep_domains.add(domain)
        normalized_requirement = {
            "kind": raw_kind,
            "domain": domain,
            "key": key,
            "values": values,
            "rawText": str(requirement.get("raw_text") or requirement.get("rawText") or "").strip(),
        }
        if raw_kind == "include":
            normalized_requirement["minCount"] = min_count
        normalized.append(normalized_requirement)
    return normalized, errors


def _normalize_plan_priority_rules(
    priority_rules: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if priority_rules in (None, []):
        return [], []
    if not isinstance(priority_rules, list):
        return [], [{"reason": "priority_rules_must_be_list"}]
    if len(priority_rules) != 1:
        return [], [{"reason": "exactly_one_priority_rule_supported"}]
    rule = priority_rules[0]
    if not isinstance(rule, dict):
        return [], [{"index": 0, "reason": "priority_rule_must_be_object"}]
    allowed_fields = {
        "domain", "key", "values", "ordering_target", "orderingTarget",
        "scope", "raw_text", "rawText",
    }
    unsupported_fields = sorted(
        str(key)
        for key, value in rule.items()
        if key not in allowed_fields and value not in (None, "", [], {})
    )
    domain = str(rule.get("domain") or "").strip().lower()
    raw_key = str(rule.get("key") or "").strip()
    compact_key = raw_key.replace("-", "_").replace(" ", "")
    key = _PLAN_CHANGE_REQUIREMENT_KEY_ALIASES.get(
        compact_key.lower(), compact_key.lower()
    )
    values: list[str] = []
    for raw_value in _as_list(rule.get("values")):
        value = str(raw_value or "").strip()
        if value and value not in values:
            values.append(value)
    ordering_target = str(
        rule.get("ordering_target") or rule.get("orderingTarget") or "rank_before"
    ).strip().lower()
    scope = str(rule.get("scope") or "within_tier").strip().lower()
    reason = ""
    if unsupported_fields:
        reason = "unsupported_fields"
    elif domain not in _PLAN_CHANGE_REQUIREMENT_KEYS:
        reason = "unsupported_domain"
    elif key not in _PLAN_CHANGE_REQUIREMENT_KEYS.get(domain, set()):
        reason = "unsupported_key"
    elif not values:
        reason = "values_required"
    elif ordering_target != "rank_before":
        reason = "only_rank_before_supported"
    elif scope != "within_tier":
        reason = "only_within_tier_supported"
    if reason:
        return [], [{
            "index": 0,
            "reason": reason,
            "domain": domain,
            "key": key,
            "unsupported_fields": unsupported_fields,
        }]
    return [{
        "domain": domain,
        "key": key,
        "values": values,
        "orderingTarget": "rank_before",
        "scope": "within_tier",
        "rawText": str(rule.get("raw_text") or rule.get("rawText") or "").strip(),
    }], []


def _normalize_plan_tier_quota_goal(
    tier_quota_goal: Any,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if tier_quota_goal in (None, {}):
        return None, []
    if not isinstance(tier_quota_goal, dict):
        return None, [{"reason": "tier_quota_goal_must_be_object"}]
    quota_type = str(tier_quota_goal.get("type") or "").strip().lower()
    update_mode = str(
        tier_quota_goal.get("update_mode") or tier_quota_goal.get("updateMode") or ""
    ).strip().lower()
    common_fields = {"type", "update_mode", "updateMode"}
    exact_fields = {
        "sprint_count", "sprintCount", "stable_count", "stableCount",
        "protect_count", "protectCount",
    }
    range_fields = {"sprint", "stable", "protect"}
    ratio_fields = {
        "sprint_weight", "sprintWeight", "stable_weight", "stableWeight",
        "protect_weight", "protectWeight",
    }
    allowed_fields = common_fields | (
        exact_fields if quota_type == "exact_counts" else range_fields
        if quota_type == "count_ranges" else ratio_fields
        if quota_type == "ratios" else set()
    )
    unsupported_fields = sorted(
        str(key)
        for key, value in tier_quota_goal.items()
        if key not in allowed_fields and value not in (None, "", [], {})
    )
    errors: list[dict[str, Any]] = []
    if unsupported_fields:
        errors.append({"reason": "unsupported_fields", "unsupported_fields": unsupported_fields})
    if quota_type not in {"exact_counts", "count_ranges", "ratios"}:
        errors.append({"reason": "tier_quota_type_invalid", "type": quota_type})
        return None, errors
    if quota_type == "count_ranges":
        if update_mode not in {"patch", "replace"}:
            errors.append({"reason": "tier_quota_update_mode_invalid", "update_mode": update_mode})
        normalized_ranges: dict[str, Any] = {
            "type": "count_ranges",
            "updateMode": update_mode,
        }
        explicit_bound_count = 0
        for tier in ("sprint", "stable", "protect"):
            raw_bound = tier_quota_goal.get(tier)
            if raw_bound is None:
                continue
            if not isinstance(raw_bound, dict):
                errors.append({"reason": "tier_range_bound_must_be_object", "tier": tier})
                continue
            bound_unknown = sorted(
                str(key)
                for key, value in raw_bound.items()
                if key not in {"min_count", "minCount", "max_count", "maxCount"}
                and value not in (None, "", [], {})
            )
            raw_min = raw_bound.get("min_count", raw_bound.get("minCount"))
            raw_max = raw_bound.get("max_count", raw_bound.get("maxCount"))
            invalid_fields = [
                name
                for name, value in (("minCount", raw_min), ("maxCount", raw_max))
                if value is not None
                and (isinstance(value, bool) or not isinstance(value, int) or value < 0)
            ]
            if bound_unknown:
                errors.append({
                    "reason": "unsupported_fields",
                    "tier": tier,
                    "unsupported_fields": bound_unknown,
                })
            if raw_min is None and raw_max is None:
                errors.append({"reason": "tier_range_bound_invalid", "tier": tier})
                continue
            if invalid_fields or (
                isinstance(raw_min, int)
                and not isinstance(raw_min, bool)
                and isinstance(raw_max, int)
                and not isinstance(raw_max, bool)
                and raw_min > raw_max
            ):
                errors.append({
                    "reason": "tier_range_bound_invalid",
                    "tier": tier,
                    "invalid_fields": invalid_fields,
                })
                continue
            normalized_bound: dict[str, int] = {}
            if raw_min is not None:
                normalized_bound["minCount"] = raw_min
            if raw_max is not None:
                normalized_bound["maxCount"] = raw_max
            normalized_ranges[tier] = normalized_bound
            explicit_bound_count += 1
        if explicit_bound_count == 0 and not any(
            item.get("reason") in {"tier_range_bound_must_be_object", "tier_range_bound_invalid"}
            for item in errors
        ):
            errors.append({"reason": "tier_range_empty"})
        if errors:
            return None, errors
        return normalized_ranges, []

    if quota_type == "ratios":
        if update_mode != "replace":
            errors.append({"reason": "tier_quota_update_mode_invalid", "update_mode": update_mode})
        raw_weights = {
            "sprintWeight": tier_quota_goal.get(
                "sprint_weight", tier_quota_goal.get("sprintWeight")
            ),
            "stableWeight": tier_quota_goal.get(
                "stable_weight", tier_quota_goal.get("stableWeight")
            ),
            "protectWeight": tier_quota_goal.get(
                "protect_weight", tier_quota_goal.get("protectWeight")
            ),
        }
        missing_fields = [key for key, value in raw_weights.items() if value is None]
        invalid_fields = [
            key
            for key, value in raw_weights.items()
            if value is not None
            and (isinstance(value, bool) or not isinstance(value, int) or value < 0)
        ]
        valid_weight_total = sum(
            value
            for value in raw_weights.values()
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        )
        if missing_fields or invalid_fields or (
            not missing_fields and not invalid_fields and valid_weight_total <= 0
        ):
            errors.append({
                "reason": "tier_ratio_weight_invalid",
                "missing_fields": missing_fields,
                "invalid_fields": invalid_fields,
            })
        if errors:
            return None, errors
        return {
            "type": "ratios",
            "updateMode": "replace",
            **raw_weights,
        }, []

    raw_counts = {
        "sprintCount": tier_quota_goal.get("sprint_count", tier_quota_goal.get("sprintCount")),
        "stableCount": tier_quota_goal.get("stable_count", tier_quota_goal.get("stableCount")),
        "protectCount": tier_quota_goal.get("protect_count", tier_quota_goal.get("protectCount")),
    }
    missing_fields = [key for key, value in raw_counts.items() if value is None]
    invalid_fields = [
        key for key, value in raw_counts.items()
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0)
    ]
    if quota_type == "exact_counts" and update_mode not in {"", "replace"}:
        errors.append({"reason": "tier_quota_update_mode_invalid", "update_mode": update_mode})
    if missing_fields:
        errors.append({"reason": "all_tier_counts_required", "missing_fields": missing_fields})
    if invalid_fields:
        errors.append({"reason": "tier_counts_must_be_nonnegative_integers", "invalid_fields": invalid_fields})
    if errors:
        return None, errors
    return {
        "type": "exact_counts",
        "sprintCount": raw_counts["sprintCount"],
        "stableCount": raw_counts["stableCount"],
        "protectCount": raw_counts["protectCount"],
    }, []


def _freeze_plan_tier_quota_delta(goal: dict[str, Any]) -> dict[str, Any]:
    quota_type = str(goal.get("type") or "").strip()
    frozen: dict[str, Any] = {"type": quota_type}
    update_mode = str(goal.get("updateMode") or "").strip()
    if update_mode:
        frozen["update_mode"] = update_mode
    if quota_type == "exact_counts":
        frozen.update(
            {
                "sprint_count": goal.get("sprintCount"),
                "stable_count": goal.get("stableCount"),
                "protect_count": goal.get("protectCount"),
            }
        )
        return frozen
    if quota_type == "count_ranges":
        for tier in ("sprint", "stable", "protect"):
            bound = goal.get(tier)
            if not isinstance(bound, dict):
                continue
            frozen_bound: dict[str, Any] = {}
            if bound.get("minCount") is not None:
                frozen_bound["min_count"] = bound["minCount"]
            if bound.get("maxCount") is not None:
                frozen_bound["max_count"] = bound["maxCount"]
            frozen[tier] = frozen_bound
        return frozen
    if quota_type == "ratios":
        frozen.update(
            {
                "sprint_weight": goal.get("sprintWeight"),
                "stable_weight": goal.get("stableWeight"),
                "protect_weight": goal.get("protectWeight"),
            }
        )
    return frozen


def _tier_quota_fallback_summary(goal: dict[str, Any]) -> str:
    quota_type = str(goal.get("type") or "").strip()
    if quota_type == "exact_counts":
        return (
            f"把方案调整为冲{goal.get('sprintCount')}、稳{goal.get('stableCount')}、"
            f"保{goal.get('protectCount')}"
        )
    if quota_type == "count_ranges":
        return "落实冲稳保数量范围硬目标"
    if quota_type == "ratios":
        return "落实冲稳保比例硬目标"
    return "落实冲稳保硬目标"


async def _prepare_plan_change_pending_resolution(
    ctx: RunContext[RequestContext],
    *,
    pending_resolution: PendingResolution,
    effective_raw_user_text: str,
    allow_intent_append: bool = False,
) -> tuple[bool, dict[str, Any] | None]:
    if _turn_started_active_pending(ctx) is None:
        return False, None
    kind = "plan_mutation"
    action_family = "apply_plan_change_proposal"
    normalized_pending_resolution = _normalize_pending_resolution(pending_resolution)
    if normalized_pending_resolution == "none":
        return False, _pending_resolution_required_payload(
            ctx,
            requested_kind=kind,
            requested_action_family=action_family,
            requested_text=effective_raw_user_text,
        )
    if normalized_pending_resolution == "hold_new_request":
        conflict = _active_pending_conflict_payload(
            ctx,
            requested_kind=kind,
            requested_action_family=action_family,
            requested_text=effective_raw_user_text,
        )
        return False, conflict
    if normalized_pending_resolution == "replace_active_pending":
        return await _replace_active_pending_for_new_preview(ctx), None
    if normalized_pending_resolution == "append_to_active_pending":
        if allow_intent_append:
            return False, None
        return False, _active_pending_append_unsupported_payload(
            ctx,
            requested_kind=kind,
            requested_action_family=action_family,
            requested_text=effective_raw_user_text,
        )
    return False, None


def _review_repair_proposal_view(proposal: dict[str, Any]) -> dict[str, Any]:
    dry_run = proposal.get("dryRunResult") if isinstance(proposal.get("dryRunResult"), dict) else {}
    return {
        "proposal_id": str(proposal.get("proposalId") or proposal.get("proposal_id") or "").strip(),
        "proposal_source": str(
            proposal.get("proposalSource") or proposal.get("proposal_source") or ""
        ).strip(),
        "source_version": _as_int(
            proposal.get("sourceVersionGuard")
            or proposal.get("source_version_guard")
            or proposal.get("sourceVersion")
            or proposal.get("source_version")
        ),
        "status": str(proposal.get("status") or "").strip(),
        "strategy": str(proposal.get("strategy") or "").strip(),
        "title": str(proposal.get("title") or "").strip(),
        "summary": str(proposal.get("summary") or "").strip(),
        "impact": str(proposal.get("impact") or "").strip(),
        "blocking_reason": str(
            proposal.get("blockingReason") or proposal.get("blocking_reason") or ""
        ).strip(),
        "source_check_codes": [
            str(code or "").strip()
            for code in proposal.get("sourceCheckCodes", proposal.get("source_check_codes", [])) or []
            if str(code or "").strip()
        ],
        "dry_run": dry_run,
        "candidate_shortages": proposal.get("candidateShortages") or [],
        # J5.5b：prepare 的幂等/冻结依据。预览只读也要把它们带出来——确认回合
        # 靠这份结果（消息历史里的工具回包）里冻结的 proposalId+digests 调 prepare，
        # 不再从 pending 里读（预览本来就不允许建 pending）。
        "requires_confirmation": bool(
            proposal.get("requiresConfirmation", proposal.get("requires_confirmation", True))
        ),
        "command_digest": str(
            proposal.get("commandDigest") or proposal.get("command_digest") or ""
        ).strip(),
        "preview_digest": str(
            proposal.get("previewDigest") or proposal.get("preview_digest") or ""
        ).strip(),
        "evaluation_version": str(
            proposal.get("evaluationVersion") or proposal.get("evaluation_version") or ""
        ).strip(),
        "plan_content_digest": str(
            proposal.get("planContentDigest") or proposal.get("plan_content_digest") or ""
        ).strip(),
        "canonical_objective_digest": str(
            proposal.get("canonicalObjectiveDigest")
            or proposal.get("canonical_objective_digest")
            or ""
        ).strip(),
        "solver_version": str(
            proposal.get("solverVersion") or proposal.get("solver_version") or ""
        ).strip(),
        "solver_input_digest": str(
            proposal.get("solverInputDigest") or proposal.get("solver_input_digest") or ""
        ).strip(),
        "hard_objective_version": str(
            proposal.get("hardObjectiveVersion") or proposal.get("hard_objective_version") or ""
        ).strip(),
    }


async def _generate_review_repair_proposals(
    ctx: RunContext[RequestContext],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    response = await internal_client.generate_planning_fix_proposals(
        getattr(ctx.deps, "tenant_id", 1),
        ctx.deps.sessionid,
    )
    data = _response_data(response)
    proposals = data.get("proposals") if isinstance(data.get("proposals"), list) else []
    return response, data, [item for item in proposals if isinstance(item, dict)]


async def _preview_review_repair_goal_selection(
    ctx: RunContext[RequestContext],
    *,
    objective: str,
) -> str:
    backend_response, backend_data, proposals = await _generate_review_repair_proposals(ctx)
    proposal_views = [_review_repair_proposal_view(item) for item in proposals]
    excluded_options: list[dict[str, Any]] = []
    if objective == "increase_stability":
        # Quantity belongs to selection_goal/user-goal Proposal, not repair-goal selection.
        retained_options: list[dict[str, Any]] = []
        for item in proposal_views:
            source_codes = item.get("source_check_codes") or []
            if item.get("strategy") == "fill_missing_count" or "count_validation" in source_codes:
                excluded_options.append(item)
            else:
                retained_options.append(item)
        proposal_views = retained_options
    ready_options = [
        item for item in proposal_views
        if item.get("proposal_source") == "review_check" and item.get("status") == "ready"
    ]
    if not proposal_views:
        return _json(
            {
                "data": {
                    "reason": "review_repair_options_unavailable",
                    "objective": objective,
                    "backend_response": backend_response,
                    "pending_created": False,
                    "requires_confirmation": False,
                },
                "next_step": "respond",
                "message": "当前审查没有返回可核验的处理选项，本轮不会创建待确认操作。",
            }
        )
    if not _consume_structured_retry_budget(ctx, "preview_plan_change.repair_goal_selection"):
        return _json(
            {
                "data": {
                    "reason": "review_repair_exact_selection_required",
                    "objective": objective,
                    "proposal_options": proposal_views,
                    "excluded_cross_goal_options": excluded_options,
                    "ready_option_count": len(ready_options),
                    "pending_created": False,
                    "requires_confirmation": False,
                },
                "next_step": "respond",
                "message": (
                    "当前处理方向还没有收敛到一个与本轮目标直接一致的可执行预览，"
                    "系统不会按列表顺序猜选，也不会改动方案。"
                ),
            }
        )
    return _json(
        {
            "data": {
                "reason": "review_repair_requires_exact_selection",
                "objective": objective,
                "proposal_source_version": _as_int(
                    backend_data.get("sourceVersionGuard") or backend_data.get("sourceVersion")
                ),
                "proposal_options": proposal_views,
                "excluded_cross_goal_options": excluded_options,
                "ready_option_count": len(ready_options),
                "retry_required_fields": ["repair_goal.review_issue_code", "repair_goal.strategy"],
                "selection_rule": (
                    "Only select one status=ready review_check proposal whose summary and impact directly "
                    "advance the user's objective. Never select by list order. If no ready option directly "
                    "matches, explain the available boundary without another preview call. For "
                    "increase_stability, an unrequested fill_missing_count/count_validation quantity goal is "
                    "not a direct match. Never propose combining multiple options because repair_goal is atomic."
                ),
                "pending_created": False,
                "requires_confirmation": False,
            },
            "next_step": "continue",
            "message": (
                "请根据本轮用户目标与 proposal_options 的结构化 strategy、source_check_codes、summary、"
                "impact 和 status 做语义选择；只有唯一直接匹配的 ready 选项才能用 exact repair_goal 重试。"
            ),
        }
    )


async def _preview_review_repair_plan_change(
    ctx: RunContext[RequestContext],
    *,
    repair_goal: dict[str, Any],
    replaced_active_pending: bool,
) -> str:
    requested_issue = str(repair_goal.get("review_issue_code") or "").strip()
    canonical_issue = _canonical_review_issue_code(requested_issue) or requested_issue
    requested_strategy = str(repair_goal.get("strategy") or "").strip()
    # 计数类问题在 Java 端可能暴露为 count_validation / count_target /
    # count_validation_hard 等变体，修复目标同为 fill_missing_count。
    count_repair_issues = {"count_validation", "count_target", "count_validation_hard"}
    # 覆盖类问题在 Java 端暴露为 coverage / coverage:<i> 等变体，
    # 修复目标为 must_include_scope 或 fill_missing_count；同一个覆盖目标
    # 在两侧策略名可能不同，匹配时视为等价。
    coverage_fix_strategies = {"must_include_scope", "fill_missing_count"}
    coverage_fix_goal = canonical_issue.startswith("coverage")
    coverage_preview_route = (
        coverage_fix_goal and requested_strategy in coverage_fix_strategies
    )
    # Java 的安全垫冻结提案可能以 add_safety_items 或 fill_missing_count
    # 暴露策略名，两者是同一修复目标；来源码仍须精确命中 safety_guard。
    safety_fix_strategies = {"add_safety_items", "fill_missing_count"}
    safety_preview_route = (
        canonical_issue == "safety_guard" and requested_strategy in safety_fix_strategies
    )
    if (
        canonical_issue == "probability_inversion"
        and requested_strategy == "sort_by_probability"
    ) or (
        canonical_issue in count_repair_issues
        and requested_strategy == "fill_missing_count"
    ) or coverage_preview_route or safety_preview_route:
        # J5.5b：倒挂排序、计数补齐、覆盖补齐与安全垫补齐都走新的只读冻结预览
        # （working/ordered/selected facts + previewDigest + 原 probe 预检）；
        # 旧 generate 只作为其他策略的回退。
        response = await internal_client.preview_review_fix_proposals(
            getattr(ctx.deps, "tenant_id", 1),
            ctx.deps.sessionid,
        )
        backend_response = response
        backend_data = _response_data(response)
        proposals = [
            item for item in (backend_data.get("proposals") or [])
            if isinstance(item, dict)
        ]
    else:
        backend_response, backend_data, proposals = await _generate_review_repair_proposals(ctx)
    proposal_envelope_version = _as_int(
        backend_data.get("sourceVersionGuard") or backend_data.get("sourceVersion")
    )
    matching: list[dict[str, Any]] = []
    for item in proposals:
        if not isinstance(item, dict):
            continue
        strategy = str(item.get("strategy") or "").strip()
        source_codes = [
            _canonical_review_issue_code(str(code or "").strip()) or str(code or "").strip()
            for code in item.get("sourceCheckCodes", item.get("source_check_codes", [])) or []
            if str(code or "").strip()
        ]
        if coverage_preview_route:
            # 覆盖修复的 must_include_scope / fill_missing_count 视为同一目标。
            if strategy not in coverage_fix_strategies:
                continue
        elif safety_preview_route:
            # 安全垫修复的 add_safety_items / fill_missing_count 视为同一目标。
            if strategy not in safety_fix_strategies:
                continue
        elif strategy != requested_strategy:
            continue
        if canonical_issue in count_repair_issues:
            # 计数修复目标内部等价：count_validation / count_target /
            # count_validation_hard 之间任意 count_* 来源码都算匹配。
            issue_matched = any(code.startswith("count_") for code in source_codes)
        elif coverage_fix_goal:
            # 覆盖修复目标内部等价：coverage / coverage:<i> 之间任意
            # coverage* 来源码都算匹配。
            issue_matched = any(code.startswith("coverage") for code in source_codes)
        else:
            issue_matched = canonical_issue in source_codes
        if issue_matched:
            matching.append(item)

    ready_matching = [
        item for item in matching
        if str(item.get("status") or "").strip() == "ready"
    ]
    if len(ready_matching) > 1:
        return _json(
            {
                "data": {
                    "reason": "review_repair_proposal_ambiguous",
                    "repair_goal": repair_goal,
                    "matching_proposals": [_review_repair_proposal_view(item) for item in ready_matching],
                    "pending_created": False,
                    "requires_confirmation": False,
                },
                "next_step": "respond",
                "message": "当前审查结果返回了多个同目标处理预览，暂时不能可靠选择，本轮不会创建待确认操作。",
            }
        )
    if not ready_matching:
        proposal_views = [_review_repair_proposal_view(item) for item in matching]
        blocked_message = ""
        if proposal_views:
            blocked_message = str(
                proposal_views[0].get("blocking_reason") or proposal_views[0].get("summary") or ""
            ).strip()
        return _json(
            {
                "data": {
                    "reason": "review_repair_proposal_unavailable",
                    "repair_goal": repair_goal,
                    "matching_proposals": proposal_views,
                    "backend_response": backend_response,
                    "pending_created": False,
                    "requires_confirmation": False,
                },
                "next_step": "respond",
                "message": blocked_message or "当前审查结果还不能形成这个目标的可执行预览，本轮不会改动方案。",
            }
        )

    proposal = ready_matching[0]
    proposal_view = _review_repair_proposal_view(proposal)
    proposal_id = str(proposal_view.get("proposal_id") or "")
    proposal_source = str(proposal_view.get("proposal_source") or "")
    proposal_source_version = _as_int(proposal_view.get("source_version"))
    dry_run = proposal_view.get("dry_run") if isinstance(proposal_view.get("dry_run"), dict) else {}
    dry_run_status = str(dry_run.get("status") or "").strip()
    workspace_response = await internal_client.get_planning_workspace_state(ctx.deps.sessionid)
    workspace_data = _response_data(workspace_response)
    current_source_version = _as_int(workspace_data.get("version"))
    if (
        not proposal_id
        or proposal_source != "review_check"
        or proposal_source_version <= 0
        or proposal_source_version != proposal_envelope_version
        or proposal_source_version != current_source_version
        or (dry_run_status and dry_run_status != "ready")
    ):
        return _json(
            {
                "data": {
                    "reason": "review_repair_proposal_contract_mismatch",
                    "repair_goal": repair_goal,
                    "proposal_envelope_version": proposal_envelope_version,
                    "current_source_version": current_source_version,
                    "proposal": proposal_view,
                    "pending_created": False,
                    "requires_confirmation": False,
                },
                "next_step": "respond",
                "message": "处理预览与当前方案版本或审查来源不一致，本轮不会创建待确认操作。",
            }
        )

    frozen_repair_goal = {
        **(
            {"objective": str(repair_goal.get("objective") or "").strip()}
            if str(repair_goal.get("objective") or "").strip()
            else {}
        ),
        "review_issue_code": canonical_issue,
        "strategy": requested_strategy,
    }
    command_digest = str(proposal_view.get("command_digest") or "").strip()
    preview_digest = str(proposal_view.get("preview_digest") or "").strip()
    evaluation_version = str(proposal_view.get("evaluation_version") or "").strip()
    proposal_apply = {
        "proposalId": proposal_id,
        "proposalSource": "review_check",
        "sourceVersionGuard": proposal_source_version,
        "regenerateOrderedPlan": True,
        "rerunReview": True,
    }
    for key, value in (
        ("commandDigest", command_digest),
        ("previewDigest", preview_digest),
        ("evaluationVersion", evaluation_version),
    ):
        if value:
            proposal_apply[key] = value
    for key, view_key in (
        ("canonicalObjectiveDigest", "canonical_objective_digest"),
        ("solverVersion", "solver_version"),
        ("solverInputDigest", "solver_input_digest"),
        ("hardObjectiveVersion", "hard_objective_version"),
    ):
        value = str(proposal_view.get(view_key) or "").strip()
        if value:
            proposal_apply[key] = value
    plan_impact = {
        "source": "preview_plan_change",
        "repair_goal": frozen_repair_goal,
        "before_unit_total": _as_int(dry_run.get("beforeUnitTotal")),
        "after_unit_total": _as_int(dry_run.get("afterUnitTotal")),
        "before_volunteer_total": _as_int(dry_run.get("beforeVolunteerTotal")),
        "after_volunteer_total": _as_int(dry_run.get("afterVolunteerTotal")),
        "affected_unit_count": _as_int(dry_run.get("affectedUnitCount")),
        "affected_volunteer_count": _as_int(dry_run.get("affectedVolunteerCount")),
        "add_unit_count": _as_int(dry_run.get("addUnitCount")),
        "add_volunteer_count": _as_int(dry_run.get("addVolunteerCount")),
        "remove_unit_count": _as_int(dry_run.get("removeUnitCount")),
        "remove_volunteer_count": _as_int(dry_run.get("removeVolunteerCount")),
    }
    title = str(proposal_view.get("title") or "").strip()
    summary = str(proposal_view.get("summary") or title or "").strip()
    impact = str(proposal_view.get("impact") or "").strip()
    fallback_summary = "按当前审查结果调整方案并重新校验"
    confirmable = bool(
        proposal_id
        and proposal_source_version > 0
        and preview_digest
        and command_digest
        and bool(proposal_view.get("requires_confirmation", True))
    )
    # J5.5b：预览**只读**。确认回合由 `confirm_pending` 凭这份候选先调
    # `/fix-proposals/review/prepare` 冻结 pending，再走 claim→execute→complete；
    # 预览本身绝不落 pending（`pending_created` 恒为 False）。
    review_fix_prepare_candidate = {
        "proposal_id": proposal_id,
        "proposal_source": "review_check",
        "source_version_guard": proposal_source_version,
        "command_digest": command_digest,
        "preview_digest": preview_digest,
        "evaluation_version": evaluation_version,
        "plan_content_digest": str(proposal_view.get("plan_content_digest") or "").strip(),
        "canonical_objective_digest": str(
            proposal_view.get("canonical_objective_digest") or ""
        ).strip(),
        "solver_version": str(proposal_view.get("solver_version") or "").strip(),
        "solver_input_digest": str(proposal_view.get("solver_input_digest") or "").strip(),
        "hard_objective_version": str(proposal_view.get("hard_objective_version") or "").strip(),
        "title": title,
        "summary": summary or fallback_summary,
        "impact": impact,
        "proposal_apply": proposal_apply,
    }
    message = f"{title}：{summary}" if title and summary and title != summary else summary
    message = message or f"已生成{fallback_summary}的预览。"
    if impact:
        message += f" 具体影响：{impact}"
    affected_unit_count = _as_int(plan_impact.get("affected_unit_count"))
    affected_volunteer_count = _as_int(plan_impact.get("affected_volunteer_count"))
    if not impact and (affected_unit_count or affected_volunteer_count):
        message += f" 具体影响：{affected_unit_count}个专业组、{affected_volunteer_count}条专业志愿。"
    if confirmable:
        message += " 确认后会按这次预览调整方案、重新生成排序并复审；确认前不会改动方案。"
    else:
        message += " 当前预览缺少可确认的执行信息，本轮不会创建待确认操作。"
    return _json(
        {
            "data": {
                "repair_goal": frozen_repair_goal,
                "proposal": proposal_view,
                "proposal_apply": proposal_apply,
                "plan_impact": plan_impact,
                "replaced_active_pending": replaced_active_pending,
                "review_fix_prepare_candidate": review_fix_prepare_candidate,
                "pending_created": False,
                "requires_confirmation": confirmable,
            },
            "next_step": "confirm" if confirmable else "respond",
            "message": message,
        }
    )


async def preview_plan_change(
    ctx: RunContext[RequestContext],
    spec: PlanChangeSpec,
    pending_resolution: PendingResolution = "none",
    raw_user_text: str = "",
) -> str:
    """Preview one backend-verified structural plan goal.

    Supported vertical slices are `fill_to_count` with projected hard
    requirements and an optional non-exclusive `rank_before/within_tier`
    priority rule, explicit entity or admission-tier minimum coverage while
    preserving the current plan size, one complete exact sprint/stable/protect
    quota/range/ratio goal, the same priority rule on its own, or one exact backend review-repair
    Proposal selected by issue code and strategy.
    """
    effective_raw_user_text = _effective_raw_user_text(ctx, raw_user_text)
    normalized_spec = spec if isinstance(spec, dict) else {}
    selection_goal = (
        normalized_spec.get("selection_goal")
        if isinstance(normalized_spec.get("selection_goal"), dict)
        else {}
    )
    repair_goal = (
        normalized_spec.get("repair_goal")
        if isinstance(normalized_spec.get("repair_goal"), dict)
        else {}
    )
    raw_tier_quota_goal = normalized_spec.get("tier_quota_goal")
    unsupported_top_level = [
        str(key)
        for key, value in normalized_spec.items()
        if key not in {
            "selection_goal", "tier_quota_goal", "requirements", "priority_rules", "repair_goal"
        }
        and value not in (None, "", [], {})
    ]
    unsupported_goal_fields = [
        str(key)
        for key, value in selection_goal.items()
        if key not in {"type", "target_count"} and value not in (None, "", [], {})
    ]
    unsupported_repair_goal_fields = [
        str(key)
        for key, value in repair_goal.items()
        if key not in {"objective", "review_issue_code", "strategy"}
        and value not in (None, "", [], {})
    ]
    requirements = normalized_spec.get("requirements")
    priority_rules = normalized_spec.get("priority_rules")
    normalized_pending_resolution = _normalize_pending_resolution(pending_resolution)
    append_active_intent_pending = False
    carried_requirement_specs: list[dict[str, Any]] = []
    carried_requirement_errors: list[dict[str, Any]] = []
    if (
        normalized_pending_resolution == "append_to_active_pending"
        and _turn_started_active_pending(ctx) is not None
    ):
        goal_type_for_append = str(selection_goal.get("type") or "").strip()
        if not repair_goal and not raw_tier_quota_goal and goal_type_for_append == "fill_to_count":
            carried_requirement_specs, carried_requirement_errors = (
                _plan_change_requirements_from_active_intent_pending(ctx)
            )
            append_active_intent_pending = bool(carried_requirement_specs) and not carried_requirement_errors
        else:
            carried_requirement_errors = [{"reason": "intent_append_requires_fill_to_count"}]
    normalized_requirements, requirement_errors = _normalize_plan_change_requirements(requirements)
    carried_requirements, carried_normalization_errors = _normalize_plan_change_requirements(
        carried_requirement_specs
    )
    normalized_requirements, carried_merge_errors = _merge_normalized_plan_change_requirements(
        normalized_requirements,
        carried_requirements,
    )
    requirement_errors = (
        requirement_errors
        + carried_requirement_errors
        + carried_normalization_errors
        + carried_merge_errors
    )
    normalized_priority_rules, priority_errors = _normalize_plan_priority_rules(priority_rules)
    normalized_tier_quota_goal, tier_quota_errors = _normalize_plan_tier_quota_goal(
        raw_tier_quota_goal
    )
    goal_type = str(selection_goal.get("type") or "").strip()
    repair_issue_code = str(repair_goal.get("review_issue_code") or "").strip()
    repair_strategy = str(repair_goal.get("strategy") or "").strip()
    repair_objective = str(repair_goal.get("objective") or "").strip()
    repair_goal_requested = bool(repair_goal)
    repair_exact_pair_complete = bool(repair_issue_code and repair_strategy)
    repair_exact_pair_partial = bool(repair_issue_code) != bool(repair_strategy)
    repair_selection_requested = repair_objective == "increase_stability" and not repair_exact_pair_complete
    invalid_repair_goal = repair_goal_requested and (
        repair_exact_pair_partial
        or bool(repair_objective and repair_objective != "increase_stability")
        or (not repair_exact_pair_complete and not repair_selection_requested)
        or bool(selection_goal)
        or bool(requirements)
        or bool(priority_rules)
        or bool(raw_tier_quota_goal)
    )
    tier_quota_requested = raw_tier_quota_goal not in (None, {})
    tier_quota_composite_not_supported = bool(normalized_tier_quota_goal) and (
        bool(normalized_requirements) or bool(normalized_priority_rules) or bool(repair_goal)
        or (bool(selection_goal) and goal_type != "fill_to_count")
    )
    coverage_preserve_requested = (
        not selection_goal
        and bool(normalized_requirements)
        and all(item.get("kind") == "include" for item in normalized_requirements)
    )
    coverage_counts_explicit = (
        coverage_preserve_requested
        and isinstance(requirements, list)
        and all(
            isinstance(item, dict)
            and (item.get("min_count") is not None or item.get("minCount") is not None)
            for item in requirements
        )
    )
    coverage_counts_supported = (
        coverage_counts_explicit
        and all(_as_int(item.get("minCount")) >= 2 for item in normalized_requirements)
    )
    unsupported_priority_composite = bool(normalized_priority_rules) and (
        (bool(selection_goal) and goal_type != "fill_to_count")
        or (
            bool(normalized_requirements)
            and goal_type != "fill_to_count"
            and not coverage_preserve_requested
        )
    )
    unsupported_requirements_without_fill = (
        bool(normalized_requirements)
        and goal_type != "fill_to_count"
        and not coverage_preserve_requested
    )
    if tier_quota_errors:
        return _json(
            {
                "data": {
                    "reason": "tier_quota_invalid",
                    "tier_quota_errors": tier_quota_errors,
                    "pending_created": False,
                    "requires_confirmation": False,
                },
                "next_step": "clarify",
                "message": (
                    "请同时明确最终冲、稳、保三个档位各需要多少个；数量必须是非负整数。"
                    "系统只执行三档完整的精确配额，不会补猜缺失数量。"
                ),
            }
        )
    if requirement_errors and all(
        item.get("reason") == "tier_min_count_required" for item in requirement_errors
    ):
        return _json(
            {
                "data": {
                    "reason": "tier_min_count_required",
                    "requirement_errors": requirement_errors,
                    "pending_created": False,
                    "requires_confirmation": False,
                },
                "next_step": "clarify",
                "message": (
                    "请明确希望最终至少保留多少个冲、稳或保档项目；"
                    "方案已满时还需要允许等量替换，系统不会替你猜档位数量。"
                ),
            }
        )
    if (
        unsupported_top_level
        or unsupported_goal_fields
        or unsupported_repair_goal_fields
        or requirement_errors
        or priority_errors
        or invalid_repair_goal
        or tier_quota_composite_not_supported
        or unsupported_priority_composite
        or unsupported_requirements_without_fill
    ):
        return _json(
            {
                "data": {
                    "reason": "plan_change_composite_not_supported",
                    "unsupported_fields": (
                        unsupported_top_level
                        + unsupported_goal_fields
                        + unsupported_repair_goal_fields
                    ),
                    "has_repair_goal": repair_goal_requested,
                    "repair_goal_invalid_or_composite": invalid_repair_goal,
                    "has_requirements": bool(normalized_requirements or requirements),
                    "has_priority_rules": bool(priority_rules),
                    "has_tier_quota_goal": tier_quota_requested,
                    "tier_quota_composite_not_supported": tier_quota_composite_not_supported,
                    "requirement_errors": requirement_errors,
                    "priority_rule_errors": priority_errors,
                    "priority_composite_not_supported": unsupported_priority_composite,
                    "requirements_without_fill_not_supported": unsupported_requirements_without_fill,
                },
                "next_step": "respond",
                "message": (
                    "这次诉求包含当前复合 Proposal 还不能可靠执行的要求；系统不会拆开执行，"
                    "也不会创建只承接部分条件的待确认操作。"
                ),
            }
        )
    if repair_goal_requested:
        if repair_selection_requested:
            return await _preview_review_repair_goal_selection(
                ctx,
                objective=repair_objective,
            )
        replaced_active_pending, pending_terminal = await _prepare_plan_change_pending_resolution(
            ctx,
            pending_resolution=pending_resolution,
            effective_raw_user_text=effective_raw_user_text,
        )
        if pending_terminal is not None:
            return _json(pending_terminal)
        return await _preview_review_repair_plan_change(
            ctx,
            repair_goal={
                **({"objective": repair_objective} if repair_objective else {}),
                "review_issue_code": repair_issue_code,
                "strategy": repair_strategy,
            },
            replaced_active_pending=replaced_active_pending,
        )
    if coverage_preserve_requested and not coverage_counts_supported:
        return _json(
            {
                "data": {
                    "reason": "coverage_target_count_required",
                    "requirements": normalized_requirements,
                    "coverage_count_explicit": coverage_counts_explicit,
                    "minimum_supported_count": 2,
                },
                "next_step": "clarify",
                "message": (
                    "请说明希望最终至少保留多少个匹配项目（当前需明确为2个或以上），"
                    "并确认若方案已满，是否允许等量替换其他项目；"
                    "系统需要明确数量和替换边界才能生成可验证的调整预览。"
                ),
            }
        )
    raw_target_count = selection_goal.get("target_count")
    target_count: int | None = None
    target_count_source = "not_applicable"
    backend_goal_type = (
        "fill_to_count"
        if goal_type == "fill_to_count" or coverage_preserve_requested or tier_quota_requested
        else "prioritize_within_tier" if normalized_priority_rules else goal_type
    )
    expected_strategy = (
        "fill_missing_count"
        if backend_goal_type == "fill_to_count"
        else "prioritize_within_tier"
    )
    if goal_type == "fill_to_count":
        target_count = _as_int(raw_target_count)
        target_count_source = "explicit"
        if raw_target_count is None:
            plan_summary = await _plan_summary_data(ctx)
            target_count = _as_int(
                plan_summary.get("candidate_target_total")
                or plan_summary.get("ordered_target_total")
            )
            target_count_source = "planning_state_required_count"
    elif coverage_preserve_requested or tier_quota_requested:
        plan_summary = await _plan_summary_data(ctx)
        target_count = _as_int(plan_summary.get("ordered_total"))
        target_count_source = "current_plan_preserve_count"
    invalid_fill_goal = goal_type == "fill_to_count" and (
        isinstance(raw_target_count, bool) or not target_count or target_count <= 0
    )
    invalid_coverage_preserve = coverage_preserve_requested and (
        not target_count or target_count <= 0
    )
    invalid_tier_quota_preserve = tier_quota_requested and not selection_goal and (
        not target_count or target_count <= 0
    )
    tier_quota_type = str((normalized_tier_quota_goal or {}).get("type") or "").strip()
    tier_quota_total = (
        _as_int((normalized_tier_quota_goal or {}).get("sprintCount"))
        + _as_int((normalized_tier_quota_goal or {}).get("stableCount"))
        + _as_int((normalized_tier_quota_goal or {}).get("protectCount"))
    )
    tier_quota_total_mismatch = (
        tier_quota_type == "exact_counts"
        and bool(target_count)
        and tier_quota_total != target_count
    )
    if tier_quota_total_mismatch:
        return _json(
            {
                "data": {
                    "reason": "tier_quota_total_mismatch",
                    "tier_quota_goal": normalized_tier_quota_goal,
                    "tier_quota_total": tier_quota_total,
                    "target_count": target_count,
                    "target_count_source": target_count_source,
                    "pending_created": False,
                    "requires_confirmation": False,
                },
                "next_step": "clarify",
                "message": (
                    f"冲稳保三个数量合计为{tier_quota_total}，但当前最终方案总数目标是{target_count}。"
                    "请把三档数量调整到与最终总数完全一致。"
                ),
            }
        )
    if (
        invalid_fill_goal
        or invalid_coverage_preserve
        or invalid_tier_quota_preserve
        or (
            goal_type != "fill_to_count"
            and not coverage_preserve_requested
            and not tier_quota_requested
            and not normalized_priority_rules
        )
    ):
        return _json(
            {
                "data": {
                    "reason": "plan_change_goal_invalid",
                    "supported_goals": ["fill_to_count", "prioritize_within_tier"],
                    "goal_type": goal_type,
                    "target_count": raw_target_count,
                    "target_count_source": target_count_source,
                },
                "next_step": "clarify",
                "message": (
                    "当前还没有可保持总数的正式方案，请先生成方案。"
                    if invalid_coverage_preserve or invalid_tier_quota_preserve
                    else
                    "当前规划状态里还没有目标志愿数量，请先说明希望补齐到多少个。"
                    if raw_target_count is None
                    else "补齐目标必须是大于0的整数。"
                ),
            }
        )

    replaced_active_pending, pending_terminal = await _prepare_plan_change_pending_resolution(
        ctx,
        pending_resolution=pending_resolution,
        effective_raw_user_text=effective_raw_user_text,
        allow_intent_append=append_active_intent_pending,
    )
    if pending_terminal is not None:
        return _json(pending_terminal)
    kind = "plan_mutation"
    action_family = "apply_plan_change_proposal"

    source_version = await _latest_planning_version(ctx)
    user_goal_request = {
        "proposalSource": "user_goal",
        "goalType": backend_goal_type,
        "targetCount": target_count,
        "requirements": normalized_requirements,
        "priorityRules": normalized_priority_rules,
        "userOriginalText": effective_raw_user_text,
        "confidence": "high",
        "sourceVersionGuard": source_version,
        "targetScopes": [],
        "negativeScopes": [],
        "qualityGuards": [],
        "tradeoffGuards": [],
        "sourceReviewIssueCodes": [],
    }
    if normalized_tier_quota_goal:
        user_goal_request["tierQuotaGoal"] = normalized_tier_quota_goal
    if coverage_preserve_requested or (tier_quota_requested and not selection_goal):
        user_goal_request["persistTargetCount"] = False
    tenant_id = getattr(ctx.deps, "tenant_id", 1)
    backend_response = await internal_client.generate_user_goal_planning_fix_proposals(
        tenant_id,
        ctx.deps.sessionid,
        user_goal_request,
    )
    backend_data = _response_data(backend_response)
    proposals = backend_data.get("proposals") if isinstance(backend_data.get("proposals"), list) else []
    proposal = next((item for item in proposals if isinstance(item, dict)), None)
    if proposal is None:
        return _json(
            {
                "data": {
                    "reason": "plan_change_proposal_unavailable",
                    "target_count": target_count,
                    "backend_response": backend_response,
                },
                "next_step": "respond",
                "message": "后端没有返回可核验的方案调整 Proposal，本轮不会创建待确认操作。",
            }
        )

    proposal_id = str(proposal.get("proposalId") or proposal.get("proposal_id") or "").strip()
    proposal_status = str(proposal.get("status") or "").strip()
    proposal_strategy = str(proposal.get("strategy") or "").strip()
    proposal_source_version = _as_int(
        proposal.get("sourceVersionGuard")
        or proposal.get("source_version_guard")
        or proposal.get("sourceVersion")
        or proposal.get("source_version")
    )
    summary = str(proposal.get("summary") or "").strip()
    blocking_reason = str(proposal.get("blockingReason") or proposal.get("blocking_reason") or "").strip()
    canonical_objective_digest = str(
        proposal.get("canonicalObjectiveDigest") or proposal.get("canonical_objective_digest") or ""
    ).strip()
    solver_version = str(proposal.get("solverVersion") or proposal.get("solver_version") or "").strip()
    solver_input_digest = str(
        proposal.get("solverInputDigest") or proposal.get("solver_input_digest") or ""
    ).strip()
    # S4 可选字段：仅透传，**不计入**下面的三件套硬门禁。
    hard_objective_version = str(
        proposal.get("hardObjectiveVersion") or proposal.get("hard_objective_version") or ""
    ).strip()
    canonical_metadata_count = sum(
        bool(value) for value in (canonical_objective_digest, solver_version, solver_input_digest)
    )
    dry_run = proposal.get("dryRunResult") if isinstance(proposal.get("dryRunResult"), dict) else {}
    tier_quota_change = (
        proposal.get("tierQuotaChange")
        if isinstance(proposal.get("tierQuotaChange"), dict)
        else proposal.get("tier_quota_change")
        if isinstance(proposal.get("tier_quota_change"), dict)
        else {}
    )
    effective_tier_quota_goal = (
        tier_quota_change.get("effectiveGoal")
        if isinstance(tier_quota_change.get("effectiveGoal"), dict)
        else tier_quota_change.get("effective_goal")
        if isinstance(tier_quota_change.get("effective_goal"), dict)
        else None
    )
    requested_tier_quota_goal = (
        tier_quota_change.get("requestedGoal")
        if isinstance(tier_quota_change.get("requestedGoal"), dict)
        else tier_quota_change.get("requested_goal")
        if isinstance(tier_quota_change.get("requested_goal"), dict)
        else None
    )
    tier_quota_resolution = (
        tier_quota_change.get("resolution")
        if isinstance(tier_quota_change.get("resolution"), dict)
        else None
    )
    proposal_view = {
        "proposal_id": proposal_id,
        "status": proposal_status,
        "strategy": proposal_strategy,
        "summary": summary,
        "impact": str(proposal.get("impact") or "").strip(),
        "blocking_reason": blocking_reason,
        "canonical_objective_digest": canonical_objective_digest,
        "solver_version": solver_version,
        "solver_input_digest": solver_input_digest,
        "hard_objective_version": hard_objective_version,
        "dry_run": dry_run,
        "candidate_shortages": proposal.get("candidateShortages") or [],
        "tier_quota_change": tier_quota_change,
    }
    if proposal_status != "ready":
        message = blocking_reason or summary or "当前候选和方案状态不能形成可执行的调整预览。"
        return _json(
            {
                "data": {
                    "target_count": target_count,
                    "proposal": proposal_view,
                    "pending_created": False,
                    "requires_confirmation": False,
                },
                "next_step": "respond",
                "message": message,
            }
        )
    if (
        not proposal_id
        or proposal_strategy != expected_strategy
        or proposal_source_version != source_version
        or canonical_metadata_count != 3
        or (
            tier_quota_type in {"count_ranges", "ratios"}
            and (effective_tier_quota_goal is None or tier_quota_resolution is None)
        )
    ):
        return _json(
            {
                "data": {
                    "reason": "plan_change_proposal_contract_mismatch",
                    "target_count": target_count,
                    "source_version": source_version,
                    "proposal": proposal_view,
                    "pending_created": False,
                    "requires_confirmation": False,
                },
                "next_step": "respond",
                "message": "方案调整 Proposal 与当前方案版本或策略不一致，本轮不会创建待确认操作。",
            }
        )

    proposal_apply = {
        "proposalId": proposal_id,
        "proposalSource": "user_goal",
        "sourceVersionGuard": source_version,
        "regenerateOrderedPlan": True,
        "rerunReview": True,
        "userGoalRequest": user_goal_request,
    }
    if canonical_metadata_count == 3:
        proposal_apply.update(
            {
                "canonicalObjectiveDigest": canonical_objective_digest,
                "solverVersion": solver_version,
                "solverInputDigest": solver_input_digest,
            }
        )
        # S4：硬门禁仍是上面三件套；hardObjectiveVersion 有则透传、无则不带。
        if hard_objective_version:
            proposal_apply["hardObjectiveVersion"] = hard_objective_version
    frozen_spec: dict[str, Any] = {
        "requirements": normalized_requirements,
        "priority_rules": normalized_priority_rules,
    }
    if goal_type == "fill_to_count":
        frozen_spec["selection_goal"] = {"type": "fill_to_count", "target_count": target_count}
    if normalized_tier_quota_goal:
        frozen_spec["tier_quota_goal"] = _freeze_plan_tier_quota_delta(
            requested_tier_quota_goal or normalized_tier_quota_goal
        )
    persisted_tier_quota_goal = effective_tier_quota_goal or normalized_tier_quota_goal
    execution_payload = {
        "action_family": action_family,
        "target_count_source": target_count_source,
        "plan_change_spec": frozen_spec,
        "proposal_apply": proposal_apply,
        "proposal_snapshot": proposal_view,
        "postconditions": {
            "count_mode": "backend_volunteer_model",
            "target_count": target_count,
            "operator": "equals",
            "requirements": normalized_requirements,
            "priority_rules": normalized_priority_rules,
            "tier_quota_goal": persisted_tier_quota_goal,
            **(
                {"tier_quota_resolution": tier_quota_resolution}
                if tier_quota_resolution is not None
                else {}
            ),
        },
    }
    plan_impact = {
        "source": "preview_plan_change",
        "target_count": target_count,
        "before_unit_total": _as_int(dry_run.get("beforeUnitTotal")),
        "after_unit_total": _as_int(dry_run.get("afterUnitTotal")),
        "before_volunteer_total": _as_int(dry_run.get("beforeVolunteerTotal")),
        "after_volunteer_total": _as_int(dry_run.get("afterVolunteerTotal")),
        "add_unit_count": _as_int(dry_run.get("addUnitCount")),
        "add_volunteer_count": _as_int(dry_run.get("addVolunteerCount")),
        "remove_unit_count": _as_int(dry_run.get("removeUnitCount")),
        "remove_volunteer_count": _as_int(dry_run.get("removeVolunteerCount")),
        "before_unit_tier_counts": dry_run.get("beforeUnitTierCounts") or {},
        "after_unit_tier_counts": dry_run.get("afterUnitTierCounts") or {},
        "before_volunteer_tier_counts": dry_run.get("beforeVolunteerTierCounts") or {},
        "after_volunteer_tier_counts": dry_run.get("afterVolunteerTierCounts") or {},
        "priority_matched_count": _as_int(dry_run.get("priorityMatchedCount")),
        "priority_before_inversion_count": _as_int(dry_run.get("priorityBeforeInversionCount")),
        "priority_after_inversion_count": _as_int(dry_run.get("priorityAfterInversionCount")),
        "priority_moved_target_count": _as_int(dry_run.get("priorityMovedTargetCount")),
    }
    fallback_summary = (
        f"把当前方案补齐到{target_count}个"
        if backend_goal_type == "fill_to_count"
        and not coverage_preserve_requested and not tier_quota_requested
        else f"落实覆盖数量要求并保持当前{target_count}个项目不变"
        if coverage_preserve_requested
        else _tier_quota_fallback_summary(normalized_tier_quota_goal)
        if normalized_tier_quota_goal
        else "在各冲稳保档内前置目标项目"
    )
    merged_active_intent_pending = False
    if append_active_intent_pending:
        active_pending = await _pending_data(ctx)
        kind_before_merge = str(active_pending.get("kind") or "").strip()
        action_before_merge = str(
            active_pending.get("action_family") or active_pending.get("actionFamily") or ""
        ).strip()
        cancel_response = await _mark_pending_status(
            ctx,
            active_pending,
            "cancelled",
            resultCode="merged_into_plan_change_preview",
        )
        if not _is_success_response(cancel_response):
            return _json(
                {
                    "data": {
                        "reason": "active_intent_pending_merge_failed",
                        "pending_created": False,
                        "requires_confirmation": False,
                    },
                    "next_step": "respond",
                    "message": "原待确认报考要求暂时无法安全合并，本轮不会创建新的方案调整操作。",
                }
            )
        _invalidate_after_pending_action(ctx, kind_before_merge, action_before_merge)
        _clear_context_pending(ctx)
        merged_active_intent_pending = True
    pending_result = await _create_plan_pending(
        ctx,
        kind=kind,
        action_family=action_family,
        summary=summary or fallback_summary,
        payload=execution_payload,
        affected_scope="当前方案",
        plan_impact=plan_impact,
        source_version=source_version,
    )
    message = summary or f"已生成{fallback_summary}的方案调整预览。"
    if pending_result.get("created"):
        message += " 确认后会原子执行并校验最终目标；确认前不会改动方案。"
    else:
        message += " 但待确认状态保存失败，本轮不会执行。"
    return _json(
        {
            "data": {
                "target_count": target_count,
                "target_count_source": target_count_source,
                "preserve_current_count": coverage_preserve_requested
                or (tier_quota_requested and not selection_goal),
                "tier_quota_goal": normalized_tier_quota_goal,
                "requirements": normalized_requirements,
                "priority_rules": normalized_priority_rules,
                "proposal": proposal_view,
                "plan_impact": plan_impact,
                "replaced_active_pending": replaced_active_pending,
                "merged_active_intent_pending": merged_active_intent_pending,
                "pending_id": pending_result.get("pending_id"),
                "pending_version": pending_result.get("pending_version"),
                "pending_created": bool(pending_result.get("created")),
                "requires_confirmation": bool(pending_result.get("created")),
            },
            "next_step": "confirm" if pending_result.get("created") else "respond",
            "message": message,
        }
    )


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
    The first call must include a locator in targets, filters, review_issue_code,
    or a position/tier selector; never call with action alone. For a request such
    as moving the highest-admission-rate item in the safe tier to that tier's
    first position, pass filters with tier, selector_sort, selector_rank,
    target_tier, and target_ordinal in the first call.
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
                    if fallback_intent_type not in {"school", "region", "major"} or not fallback_negative:
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
        effective_targets = _as_list(targets)
        if not effective_targets and not normalized_filters and raw_user_text:
            inferred_positions = _target_position_values(raw_user_text) or _target_position_range(raw_user_text)
            if not inferred_positions:
                single_position = _target_position_value(raw_user_text)
                if single_position > 0:
                    inferred_positions = [single_position]
            if not inferred_positions and normalized_action == "move" and _as_int(target_position) > 0:
                source_match = re.search(r"第([一二两三四五六七八九十]+|\d+)", raw_user_text)
                if source_match:
                    source_position = _as_int(source_match.group(1)) or _chinese_ordinal_value(source_match.group(1))
                    if source_position > 0:
                        inferred_positions = [source_position]
            if inferred_positions:
                effective_targets = [f"第{position}个" for position in inferred_positions]
        if not effective_targets and review_issue_code and normalized_action == "remove":
            issue, resolved, reason = await _review_issue_action_target(ctx, review_issue_code)
            missing = [] if reason in {"ok", "review_issue_units_not_in_plan"} else [str(review_issue_code)]
            if issue:
                review_issue_meta = _review_issue_target_meta(issue)
            if reason == "ok" and normalized_filters:
                resolved, normalized_filters, reason = _filter_resolved_plan_items(ctx, resolved, normalized_filters)
                missing = [] if reason == "ok" else [_describe_filters(normalized_filters)]
            elif reason != "ok":
                fallback_filters = normalized_filters or _review_issue_fallback_filters(review_issue_code)
                if fallback_filters:
                    resolved, normalized_filters, reason = await _resolve_plan_filter_targets(ctx, fallback_filters)
                    missing = [] if reason == "ok" else [_describe_filters(normalized_filters)]
        elif not effective_targets and normalized_filters and normalized_action == "remove":
            resolved, normalized_filters, reason = await _resolve_plan_filter_targets(ctx, normalized_filters)
            missing = [] if reason == "ok" else [_describe_filters(normalized_filters)]
        elif not effective_targets and normalized_filters and normalized_action == "move":
            resolved, normalized_filters, reason = await _resolve_plan_filter_selector_target(
                ctx,
                normalized_filters,
            )
            missing = [] if reason == "ok" else [_describe_filters(normalized_filters)]
        else:
            resolved, missing, reason = await _resolve_plan_targets(ctx, effective_targets, source="plan")
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
        affected_scope = _plan_item_scope_summary(resolved, limit=5, total=count)
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
        if normalized_action == "move":
            affected_scope = (
                f"{affected_scope}；目标位置："
                f"{_move_target_scope(normalized_filters, _as_int(target_position))}"
            )

    elif normalized_action == "add":
        resolved, add_filters, reason = await _resolve_add_candidate_targets(ctx, targets, normalized_filters)
        if add_filters:
            normalized_filters = add_filters
        if reason == "candidate_ambiguous":
            options = [_plan_item_brief(item) for item in resolved[:5]]
            return _json(
                {
                    "data": {
                        "action": "add",
                        "targets": targets or [],
                        "filters": normalized_filters,
                        "candidate_options": options,
                        "matched_total": len(resolved),
                        "reason": reason,
                    },
                    "next_step": "clarify",
                    "message": (
                        "当前候选池里找到多个符合条件的志愿："
                        + "；".join(_plan_item_snippet(item) for item in resolved[:5])
                        + "。请说明要加入其中哪个具体专业。"
                    ),
                }
            )
        if reason in {"candidate_no_match", "candidate_already_selected"}:
            description = _describe_filters(normalized_filters) or "、".join(_as_list(targets))
            message = (
                f"当前候选池里没有命中“{description}”的可加入志愿。"
                if reason == "candidate_no_match"
                else f"“{description}”对应的候选已经在当前方案中，不需要重复加入。"
            )
            return _json(
                {
                    "data": {
                        "action": "add",
                        "targets": targets or [],
                        "filters": normalized_filters,
                        "candidate_options": [],
                        "reason": reason,
                    },
                    "next_step": "respond",
                    "message": message,
                }
            )
        if reason != "ok" or not resolved:
            return _json(
                {
                    "data": {
                        "action": "add",
                        "targets": targets or [],
                        "filters": normalized_filters,
                        "reason": reason,
                    },
                    "next_step": "clarify",
                    "message": "还没有唯一定位到要加入的候选志愿，请同时说明候选里的学校和专业。",
                }
            )
        volunteer_ids = [_item_volunteer_id(item) for item in resolved if _item_volunteer_id(item)]
        affected_items = [_plan_item_brief(item) for item in resolved if item]
        count = len(volunteer_ids)
        affected_scope = _plan_item_scope_summary(
            resolved,
            limit=5,
            total=count,
            noun="候选志愿",
        )

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
        affected_scope = "移出：" + _plan_item_scope_summary(
            old_resolved,
            limit=3,
            total=len(unit_ids),
        )
        affected_scope += "；加入：" + _plan_item_scope_summary(
            new_resolved,
            limit=3,
            total=len(volunteer_ids),
            noun="候选志愿",
        )
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
        if normalized_filters or review_issue_meta:
            action_label = "生成方案" if normalized_action == "generate" else "重新生成排序方案"
            requested_scope = _describe_filters(normalized_filters)
            if review_issue_meta:
                issue_label = str(review_issue_meta.get("label") or review_issue_meta.get("code") or "审查问题")
                requested_scope = f"{requested_scope}；{issue_label}" if requested_scope else issue_label
            return _json(
                {
                    "data": {
                        "action": normalized_action,
                        "action_family": action_family,
                        "filters": normalized_filters,
                        "review_issue_code": review_issue_code or "",
                        "review_issue_target": review_issue_meta or {},
                        "reason": "plan_generation_goal_requires_proposal",
                        "pending_created": False,
                        "requires_confirmation": False,
                    },
                    "next_step": "clarify",
                    "message": (
                        f"已经听清这次要围绕“{requested_scope}”{action_label}，"
                        "但当前生成接口只会消费已经确认的报考要求和当前候选，"
                        "不会执行这次临时附带的筛选或修复目标，因此不会生成确认卡，也不会改动方案。"
                        "需要先生成包含具体新增、移出或排序变化的可执行处理提案。"
                    ),
                }
            )
        if normalized_action == "generate":
            affected_scope = "生成新的正式方案"
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
    relative_province_scope = _extract_relative_province_scope(query_filters)
    score = await _score_data(ctx) if relative_province_scope else {}
    home_province = str(score.get("province") or "").strip()
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
    if relative_province_scope:
        scope_label = "省内" if relative_province_scope == "inside" else "省外"
        relative_description = f"{scope_label}（相对高考省份{home_province}）" if home_province else scope_label
        description = f"{relative_description}；{description}" if description else relative_description

    if relative_province_scope and not home_province:
        return _json(
            {
                "data": {
                    "has_plan": True,
                    "scope": normalized_scope,
                    "filters": query_filters,
                    "relative_province_scope": relative_province_scope,
                    "home_province": "",
                    "matched_total": 0,
                    "returned_total": 0,
                    "items": [],
                    **_post_query_instruction(raw_user_text),
                },
                "next_step": "clarify",
                "message": "暂时没有拿到高考省份，不能准确计算方案里的省内/省外数量。请先补充高考省份。",
            }
        )

    if normalized_scope == "candidates":
        if relative_province_scope == "outside":
            return _json(
                {
                    "data": {
                        "has_plan": True,
                        "scope": "candidates",
                        "filters": query_filters,
                        "relative_province_scope": relative_province_scope,
                        "home_province": home_province,
                        "matched_total": 0,
                        "returned_total": 0,
                        "items": [],
                        **_post_query_instruction(raw_user_text),
                    },
                    "next_step": "clarify",
                    "message": "候选池暂不支持一次性统计全部省外机会；可以指定具体省份继续查询。",
                }
            )
        if relative_province_scope == "inside":
            query_filters["province"] = [home_province]
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
        and _matches_relative_province_scope(
            item,
            home_province=home_province,
            scope=relative_province_scope,
        )
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
    if query_filters or relative_province_scope:
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
                "relative_province_scope": relative_province_scope,
                "home_province": home_province,
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


def _no_active_pending_confirmation_message() -> str:
    return (
        "当前没有待确认操作；上一轮只是查询或分析，没有待采纳或待执行的内容，因此不会执行任何变更。"
        "下一步可以直接说明想查看什么，或者先让我生成具体调整预览。"
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

    runtime_pending = _turn_started_active_pending(ctx)
    pending = await _pending_data(ctx)
    if runtime_pending is None:
        candidate = (
            _latest_review_fix_prepare_candidate(ctx)
            if normalized_action == "confirm"
            else None
        )
        if candidate is None:
            return _json(
                {
                    "data": {
                        "active": False,
                        "action": normalized_action,
                    },
                    "next_step": "respond",
                    "message": _no_active_pending_confirmation_message(),
                }
            )
        # J5.5b：只读预览不建 pending，确认时先凭预览回包里冻结的
        # proposalId/digests 调 prepare，再走同一轮 claim→execute→complete。
        # 评估模式绝不能落任何状态，所以 prepare 之前就返回 would_apply。
        if _dry_run_state_mutations(ctx):
            return _json(
                {
                    "data": {
                        "active": False,
                        "action": "confirm",
                        "kind": "plan_change_proposal",
                        "action_family": "apply_plan_change_proposal",
                        "proposal_id": candidate.get("proposal_id"),
                        "applied": False,
                        "would_apply": True,
                        "dry_run": True,
                    },
                    "next_step": "respond",
                    "message": "这次会采纳当前待确认内容；评估模式下不会实际执行。",
                }
            )
        pending, prepare_message = await _prepare_review_fix_pending(ctx, candidate)
        if pending is None:
            return _json(
                {
                    "data": {
                        "active": False,
                        "action": "confirm",
                        "error": "review_fix_prepare_failed",
                        "proposal_id": candidate.get("proposal_id"),
                    },
                    "next_step": "respond",
                    "message": prepare_message,
                }
            )
    else:
        if not pending.get("active"):
            return _json(
                {
                    "data": {
                        "active": False,
                        "action": normalized_action,
                    },
                    "next_step": "respond",
                    "message": _no_active_pending_confirmation_message(),
                }
            )

        runtime_pending_id = str(getattr(runtime_pending, "pending_id", "") or "").strip()
        snapshot_pending_id = str(pending.get("pending_id") or pending.get("pendingId") or "").strip()
        if not runtime_pending_id or not snapshot_pending_id or runtime_pending_id != snapshot_pending_id:
            return _json(
                {
                    "data": {
                        "active": False,
                        "action": normalized_action,
                        "error": "pending_snapshot_mismatch",
                        "runtime_pending_id": runtime_pending_id,
                        "snapshot_pending_id": snapshot_pending_id,
                    },
                    "next_step": "respond",
                    "message": "当前待确认内容已经变化，这次不会执行。请刷新后按最新预览重新确认。",
                }
            )

    kind = str(pending.get("kind") or "").strip()
    action_family = str(pending.get("action_family") or pending.get("actionFamily") or "").strip()
    if normalized_action == "cancel":
        cancel_response = await _mark_pending_status(ctx, pending, "cancelled")
        if not _is_success_response(cancel_response):
            return _json(
                {
                    "data": {"active": True, "action": "cancel", "error": "pending_cas_conflict"},
                    "next_step": "respond",
                    "message": "当前待确认内容已经变化，这次未取消。请刷新后以最新预览为准。",
                }
            )
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

    raw_pending = pending.get("raw") if isinstance(pending.get("raw"), dict) else {}
    if str(raw_pending.get("status") or "").strip() != "applying":
        claim_response = await internal_client.claim_pending_confirmation(ctx.deps.sessionid, raw_pending)
        claim_data = claim_response.get("data") if isinstance(claim_response.get("data"), dict) else {}
        if not _is_success_response(claim_response) or claim_data.get("transitionApplied") is not True:
            return _json(
                {
                    "data": {
                        "active": False,
                        "action": "confirm",
                        "kind": kind,
                        "action_family": action_family,
                        "error": "pending_claim_conflict",
                    },
                    "next_step": "respond",
                    "message": "这次待确认内容已被处理或已经变化，不会重复执行。请刷新后以最新状态为准。",
                }
            )
        claimed_raw = claim_data.get("dataValue") if isinstance(claim_data.get("dataValue"), dict) else {}
        if claimed_raw:
            claimed_raw["_pendingRevision"] = claim_data.get("revision")
            claimed_raw["revision"] = claim_data.get("revision")
            claimed_raw["_pendingClaimToken"] = claim_data.get("claimToken")
            claimed_raw["_pendingClaimExpiresAt"] = claim_data.get("claimExpiresAt")
            pending["raw"] = claimed_raw

    if kind == "intent_change":
        success, data, message = await _apply_intent_pending(
            ctx,
            pending,
            apply_to_current_plan_override=apply_to_current_plan,
        )
    elif kind in {"plan_mutation", "plan_generation", "plan_change_proposal"}:
        success, data, message = await _apply_plan_pending(ctx, pending)
    else:
        success = False
        data = {"reason": "unsupported_pending_kind", "kind": kind}
        message = "这类待确认内容还不能由新确认工具执行，请重新生成预览。"

    if data.get("execution_uncertain"):
        _invalidate_after_pending_action(ctx, kind, action_family)
        _clear_context_pending(ctx)
        return _json(
            {
                "data": {
                    "active": True,
                    "action": "confirm",
                    "kind": kind,
                    "action_family": action_family,
                    "pending_id": pending.get("pending_id"),
                    "applied": False,
                    "execution_uncertain": True,
                    "result": data,
                },
                "next_step": "respond",
                "message": message,
            }
        )

    status = "applied" if success else "expired"
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
