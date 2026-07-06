from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.domain.career_slots import (
    CAREER_FURTHER_STUDY,
    CAREER_MARKET_EMPLOYMENT,
    CAREER_STABLE_EMPLOYMENT,
    CAREER_SYSTEM_PUBLIC_SERVICE,
    to_career_label,
)
logger = logging.getLogger(__name__)

PENDING_PLAN_ACTION_FAMILIES = frozenset(
    {
        "generate_plan",
        "add_units",
        "remove_units",
        "move_unit",
        "move_ordered_unit",
        "remove_ordered_unit",
        "replace_units",
        "sort_ordered_plan",
        "regenerate_order",
    }
)

SUPPORTED_WORKSPACE_ACTION_TARGETS = frozenset({"candidate", "ordered", "review"})

@dataclass
class PlanConfirmationCandidateResolution:
    allowed: bool = False
    action_family: str = ""
    plan_payload: dict[str, Any] = field(default_factory=dict)
    plan_payload_text: str = ""
    source_version_guard: int = 0
    target_view: str | None = None
    intent_update: dict[str, Any] = field(default_factory=dict)
    blocking_reasons: list[str] = field(default_factory=list)


@dataclass
class RuntimePlanCompiledSource:
    confirmation_candidate: dict[str, Any] | None = None
    compiled: dict[str, Any] | None = None
    resolution: PlanConfirmationCandidateResolution = field(default_factory=PlanConfirmationCandidateResolution)
    source_version_guard: int = 0
    blocking_reasons: list[str] = field(default_factory=list)


@dataclass
class RuntimeLocalPlanActionSource:
    matched: bool = False
    route: str = ""
    action_family: str = ""
    plan_payload: dict[str, Any] = field(default_factory=dict)
    plan_action_dsl: dict[str, Any] = field(default_factory=dict)
    source_version_guard: int = 0
    blocking_reasons: list[str] = field(default_factory=list)


@dataclass
class RuntimePlanQueryCompiledSource:
    matched: bool = False
    route: str = ""
    side_effect: str = "readonly"
    action_family: str = "query_ordered"
    plan_payload: dict[str, Any] = field(default_factory=dict)
    plan_query_dsl: dict[str, Any] = field(default_factory=dict)
    source_version_guard: int = 0
    blocking_reasons: list[str] = field(default_factory=list)


@dataclass
class RuntimeIntentPreviewTurnDecisionArbitrationSource:
    matched: bool = False
    route: str = ""
    side_effect: str = "intent_pending"
    allow_intent_pending: bool = False
    arbitration_dsl: dict[str, Any] = field(default_factory=dict)
    blocking_reasons: list[str] = field(default_factory=list)


@dataclass
class RuntimeBlockedIntentPreviewReplySource:
    matched: bool = False
    route: str = ""
    side_effect: str = "reply_guard"
    primary_reply: str = ""
    display_payload: dict[str, Any] = field(default_factory=dict)
    reply_plan: dict[str, Any] = field(default_factory=dict)
    blocking_reasons: list[str] = field(default_factory=list)


@dataclass
class RuntimeReplyGuardSource:
    matched: bool = False
    route: str = ""
    side_effect: str = "reply_guard"
    guard_type: str = ""
    stripped_reply: str = ""
    display_payload: dict[str, Any] = field(default_factory=dict)
    reply_plan: dict[str, Any] = field(default_factory=dict)
    blocking_reasons: list[str] = field(default_factory=list)


@dataclass
class ConditionalCandidateReadonlyBoundaryResolution:
    matched: bool = False
    route: str = ""
    side_effect: str = "readonly"
    reason_code: str = ""
    missing_inputs: list[str] = field(default_factory=list)
    blocking_reasons: list[str] = field(default_factory=list)


@dataclass
class ProfileChangeReplanCompiledSource:
    matched: bool = False
    route: str = ""
    side_effect: str = "profile_change_replan"
    profile_change_dsl: dict[str, Any] = field(default_factory=dict)
    evidence_plan: dict[str, Any] = field(default_factory=dict)
    blocking_reasons: list[str] = field(default_factory=list)


@dataclass
class ProfileChangeStateQueryResolution:
    matched: bool = False
    route: str = ""
    side_effect: str = "readonly"
    blocking_reasons: list[str] = field(default_factory=list)


@dataclass
class PendingTurnResolution:
    action: str = "none"
    side_effect: str = "none"
    pending_type: str = ""
    requires_model_decision: bool = True
    post_apply_evidence_plan: dict[str, Any] | None = None
    blocking_reasons: list[str] = field(default_factory=list)


@dataclass
class ApplyThenGeneratePlanCompiledSource:
    confirmation_candidate: dict[str, Any] | None = None
    compiled: dict[str, Any] | None = None
    source_version_guard: int = 0
    blocking_reasons: list[str] = field(default_factory=list)


@dataclass
class NeedsPlanFirstResolution:
    side_effect: str = "none"
    reference_resolution: str = ""
    requires_model_decision: bool = True
    target_issues: list[str] = field(default_factory=list)
    primary_reply: str = ""
    display_payload: dict[str, Any] = field(default_factory=dict)
    reply_plan: dict[str, Any] = field(default_factory=dict)
    blocking_reasons: list[str] = field(default_factory=list)


@dataclass
class NoFormalPlanReviewBoundaryResolution:
    side_effect: str = "none"
    reference_resolution: str = ""
    requires_model_decision: bool = True
    reply_focus: list[str] = field(default_factory=list)
    blocking_reasons: list[str] = field(default_factory=list)


@dataclass
class UserGoalFixProposalSelection:
    proposal: dict[str, Any] | None = None
    fallback_proposal: dict[str, Any] | None = None
    source_version_guard: int = 0
    goal_type: str = ""
    blocking_reasons: list[str] = field(default_factory=list)


@dataclass
class StructuredGoalClarificationResolution:
    needed: bool = False
    questions: list[str] = field(default_factory=list)
    scope_values: list[str] = field(default_factory=list)
    blocking_reasons: list[str] = field(default_factory=list)


@dataclass
class IntentProposalInputResolution:
    allowed: bool = False
    intent_mode: str = "preference"
    constraint_intent_type: str = "default"
    blocking_reasons: list[str] = field(default_factory=list)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _append_reason(reasons: list[str], reason: str) -> None:
    if reason and reason not in reasons:
        reasons.append(reason)


def _compact_text(value: str | None) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())



def _normalize_confirmation_only_text(content: str | None, *, strip_fullwidth_question: bool = False) -> str:
    normalized = _compact_text(content)
    punctuation = "。.!！?？" if strip_fullwidth_question else "。.!！?"
    return normalized.strip(punctuation)


_READONLY_CLOSURE_ACK_PHRASES = (
    "嗯那就这样",
    "那就这样",
    "那先这样",
    "先这样",
    "先这样吧",
    "就这样",
    "就这样吧",
    "好先这样",
    "好的先这样",
    "行先这样",
    "嗯先这样",
    "嗯就这样",
    "先按这个吧",
    "先按刚才的吧",
)

_PENDING_DIRECT_CONFIRM_COMMON_ACKS = (
    "确认",
    "确定",
    "可以",
    "嗯可以",
    "好可以",
    "好的",
    "好",
    "行",
    "按这个来",
    "就按这个来",
    "按刚才的来",
    "就按刚才的来",
)

_PENDING_DIRECT_PLAN_CONFIRM_ACKS = frozenset(
    (
        *_PENDING_DIRECT_CONFIRM_COMMON_ACKS,
        "确认执行",
        "执行",
        "执行吧",
        "开始执行",
        "应用吧",
        "确认这个",
        "确认这条",
        "确认这个方案",
    )
)

_PENDING_PLAN_ACTION_CONFIRM_KEYWORDS: dict[str, tuple[str, ...]] = {
    "generate_plan": ("生成", "补齐"),
    "add_units": ("加入", "加到", "添加", "补入"),
    "remove_units": ("删除", "移出", "删掉", "去掉", "剔除"),
    "remove_ordered_unit": ("删除", "移出", "删掉", "去掉", "剔除"),
    "move_unit": ("移动", "调整", "挪动"),
    "move_ordered_unit": ("移动", "调整", "挪动"),
    "replace_units": ("替换", "换掉", "换成"),
    "sort_ordered_plan": ("排序", "重排", "调整"),
    "regenerate_order": ("重排", "排序", "重新排", "调整"),
}

_PENDING_PLAN_ACTION_CONFIRM_PREFIXES = (
    "确认执行",
    "确认",
    "执行",
    "开始执行",
    "应用",
)

_PENDING_DIRECT_INTENT_CONFIRM_ACKS = frozenset(
    (
        *_PENDING_DIRECT_CONFIRM_COMMON_ACKS,
        "采纳",
        "采纳这个",
        "采纳这条",
        "确认这个",
        "确认这条",
        "确认这个偏好",
        "确认这个要求",
        "确认这个意向",
    )
)

_NO_ACTIVE_PENDING_CONFIRMATION_ACKS = frozenset(
    (
        *_PENDING_DIRECT_PLAN_CONFIRM_ACKS,
        "确认这个偏好",
        "确认这个要求",
        "确认这个意向",
        "采纳",
        "采纳这个",
        "采纳这条",
    )
)

_PENDING_REJECT_TOKENS = (
    "取消",
    "先取消",
    "作废",
    "不用了",
    "不用执行了",
    "不要执行了",
    "不用处理了",
    "不要处理了",
    "不采纳",
    "不要采纳",
    "不用采纳",
)

_PENDING_REJECT_EXACT_ACKS = frozenset(
    (
        *_PENDING_REJECT_TOKENS,
        "先不用了",
        "这个不用了",
        "这条不用了",
        "这项不用了",
        "这个作废",
        "这条作废",
        "这项作废",
        "取消这个",
        "取消这条",
        "取消这项",
        "不采纳这个",
        "不采纳这条",
        "不采纳这项",
    )
)

_PENDING_REJECT_REFERENCE_MARKERS = (
    "这次",
    "这个",
    "这条",
    "这项",
    "刚才",
    "上一轮",
    "上一个",
    "待采纳",
    "待确认",
    "确认卡",
    "预览",
)

_PLAN_QUERY_PROFILE_TYPES = frozenset(
    {
        "readonly_plan_query",
        "readonly_plan_slice_query",
        "readonly_pending_reference_query",
    }
)
_PLAN_QUERY_PROFILE_DIMENSIONS = frozenset(
    {
        "tuition",
        "tier_segment",
        "pending_reference",
        "count_summary",
        "item_list",
        "school_presence",
        "safety_check",
    }
)
_PLAN_QUERY_PROFILE_FIELDS = frozenset(
    {
        "school",
        "major",
        "admission_probability",
    }
)
_PLAN_QUERY_PROFILE_TIER_NORMALIZATION = {
    "保": "保",
    "保底": "保",
    "保档": "保",
    "兜底": "保",
    "稳": "稳",
    "稳档": "稳",
    "冲": "冲",
    "冲档": "冲",
}


def _contains_any(compact: str, markers: tuple[str, ...]) -> bool:
    return any(marker in compact for marker in markers)


def _profile_summary(profile: dict[str, Any]) -> str:
    parts: list[str] = []
    score = _as_int(profile.get("score"))
    if score > 0:
        parts.append(f"{score}分")
    rank = _as_int(profile.get("rank"))
    if rank > 0:
        parts.append(f"位次{rank}")
    province = str(profile.get("province") or "").strip()
    if province:
        parts.append(province)
    subject_combo = str(profile.get("subjectCombo") or "").strip()
    subjects = [str(item or "").strip() for item in (profile.get("subjects") or []) if str(item or "").strip()]
    if subject_combo:
        parts.append(subject_combo)
    elif subjects:
        parts.append("、".join(subjects))
    batch = str(profile.get("batch") or "").strip()
    if batch:
        parts.append(batch)
    return "、".join(parts)


_PROFILE_CHANGE_REPLAN_RECOGNIZED_FIELDS = frozenset(
    {
        "score",
        "rank",
        "province",
        "subjects",
        "subjectCombo",
        "batch",
    }
)


def _normalize_profile_payload(profile: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in (profile or {}).items():
        key_text = str(key or "").strip()
        if not key_text:
            continue
        if key_text in {"score", "rank"}:
            numeric = _as_int(value)
            if numeric > 0:
                normalized[key_text] = numeric
            continue
        if key_text == "subjects":
            subjects = [
                str(item or "").strip()
                for item in (value or [])
                if str(item or "").strip()
            ] if isinstance(value, (list, tuple, set)) else []
            if subjects:
                normalized[key_text] = subjects
            continue
        if isinstance(value, str):
            text = value.strip()
            if text:
                normalized[key_text] = text
            continue
        if value not in (None, "", [], {}, ()):
            normalized[key_text] = value
    return normalized


def _profile_payload_has_replan_values(profile: dict[str, Any]) -> bool:
    return any(field in profile for field in _PROFILE_CHANGE_REPLAN_RECOGNIZED_FIELDS)


def _merge_profile_replan_payload(
    proposed_profile: dict[str, Any],
    previous_profile: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[str]]:
    """Merge a profile correction with the latest structured replan state.

    TurnDecision may emit only the field being corrected in a follow-up turn
    (for example score only). The compiler can safely merge missing recognized
    profile fields from the previous ProfileChangeReplan DSL because both
    inputs are structured state, not raw user wording.
    """
    proposed = _normalize_profile_payload(dict(proposed_profile or {}))
    previous = _normalize_profile_payload(dict(previous_profile or {}))
    if not proposed or not previous:
        return proposed, []
    merged = dict(previous)
    merged.update(proposed)
    merged_fields = [
        field
        for field in sorted(_PROFILE_CHANGE_REPLAN_RECOGNIZED_FIELDS)
        if field not in proposed and field in previous
    ]
    return merged, merged_fields


def compile_profile_change_replan_source(
    *,
    profile_scenario: str,
    proposed_profile: dict[str, Any] | None = None,
    previous_proposed_profile: dict[str, Any] | None = None,
    current_profile: dict[str, Any] | None = None,
    planning_version: int = 0,
) -> ProfileChangeReplanCompiledSource:
    """Compile a structured profile replan decision into runtime DSL.

    The semantic TurnDecision owns scenario understanding.  This compiler only
    consumes structured fields; it must not infer profile mode from raw text.
    """
    profile_mode = str(profile_scenario or "none").strip()
    if profile_mode not in {"adhoc_scenario", "current_student_update", "ambiguous"}:
        return ProfileChangeReplanCompiledSource(blocking_reasons=["missing_profile_replan_scenario"])
    proposed_profile, merged_from_previous_fields = _merge_profile_replan_payload(
        dict(proposed_profile or {}),
        previous_proposed_profile,
    )
    if not _profile_payload_has_replan_values(proposed_profile):
        return ProfileChangeReplanCompiledSource(blocking_reasons=["missing_profile_change_values"])

    current = _normalize_profile_payload(dict(current_profile or {}))
    missing_fields: list[str] = []
    if "score" not in proposed_profile and "rank" not in proposed_profile:
        missing_fields.append("score_or_rank")
    if "province" not in proposed_profile:
        missing_fields.append("province")
    if "subjects" not in proposed_profile and "subjectCombo" not in proposed_profile:
        missing_fields.append("subjects")
    if profile_mode == "current_student_update":
        dsl_type = "ProfileChangeReplan"
        stale_plan_policy = {
            "formalPlan": "preserve_as_old_until_recalculated",
            "candidatePool": "preserve_as_old_until_recalculated",
            "pendingConfirmation": "preserve_unless_user_replaces",
        }
        required_action = [
            "confirm_profile_update",
            "recalculate_candidate_pool",
            "regenerate_plan",
        ]
        steps = [
            "parse_profile_change_request",
            "mark_existing_plan_stale_for_proposed_profile",
            "preserve_pending_confirmation",
            "require_profile_update_before_recalculation",
        ]
        no_result_reason = "profile_change_requires_recalculation"
        route = "profile_change_replan_request"
        side_effect = "profile_change_replan"
    elif profile_mode == "adhoc_scenario":
        dsl_type = "ProfileReplanAdhoc"
        stale_plan_policy = {
            "formalPlan": "do_not_invalidate_current_plan",
            "candidatePool": "do_not_invalidate_current_candidate_pool",
            "pendingConfirmation": "preserve_unchanged",
        }
        required_action = [
            "answer_as_temporary_scenario",
            "do_not_update_profile",
            "do_not_invalidate_current_plan",
        ]
        steps = [
            "parse_adhoc_profile_scenario",
            "answer_without_profile_write",
            "preserve_current_plan_validity",
            "preserve_pending_confirmation",
        ]
        no_result_reason = "adhoc_profile_scenario_not_persisted"
        route = "profile_replan_adhoc_request"
        side_effect = "profile_replan_adhoc"
    else:
        dsl_type = "ProfileReplanAmbiguous"
        stale_plan_policy = {
            "formalPlan": "do_not_invalidate_current_plan",
            "candidatePool": "do_not_invalidate_current_candidate_pool",
            "pendingConfirmation": "preserve_unchanged",
        }
        required_action = [
            "clarify_whether_to_update_current_student_profile",
            "do_not_update_profile_before_clarification",
            "do_not_invalidate_current_plan",
        ]
        steps = [
            "parse_profile_replan_candidate",
            "ask_profile_scope_clarification",
            "preserve_current_plan_validity",
            "preserve_pending_confirmation",
        ]
        no_result_reason = "profile_replan_scope_ambiguous"
        route = "profile_replan_ambiguous_request"
        side_effect = "profile_replan_ambiguous"

    profile_change_dsl = {
        "type": dsl_type,
        "scopeAnchor": "current_profile",
        "sideEffect": side_effect,
        "profileMode": profile_mode,
        "proposedProfile": proposed_profile,
        "proposedProfileSummary": _profile_summary(proposed_profile),
        "currentProfile": current,
        "currentProfileSummary": _profile_summary(current),
        "requiredAction": required_action,
        "stalePlanPolicy": stale_plan_policy,
        "missingProfileFields": missing_fields,
        "sourceVersionGuard": planning_version,
    }
    if merged_from_previous_fields:
        profile_change_dsl["mergedFromPreviousProposedProfileFields"] = merged_from_previous_fields
    evidence_plan = {
        "requiredInputs": ["current_profile", "proposed_profile", "formal_plan_status", "active_pending_summary"],
        "steps": steps,
        "toolBudget": {"maxToolCalls": 0, "batchPreferred": False},
        "noResultReason": no_result_reason,
    }
    return ProfileChangeReplanCompiledSource(
        matched=True,
        route=route,
        side_effect=side_effect,
        profile_change_dsl=profile_change_dsl,
        evidence_plan=evidence_plan,
    )


def resolve_profile_change_replan_state_query(
    *,
    profile_change_dsl: dict[str, Any] | None,
    query_scenario: str = "",
) -> ProfileChangeStateQueryResolution:
    if not isinstance(profile_change_dsl, dict) or profile_change_dsl.get("type") != "ProfileChangeReplan":
        return ProfileChangeStateQueryResolution(blocking_reasons=["missing_profile_change_replan_state"])
    if str(profile_change_dsl.get("profileMode") or "").strip() != "current_student_update":
        return ProfileChangeStateQueryResolution(blocking_reasons=["profile_replan_state_is_adhoc"])
    if str(query_scenario or "").strip() != "profile_change_state_query":
        return ProfileChangeStateQueryResolution(blocking_reasons=["missing_profile_state_query_intent"])

    return ProfileChangeStateQueryResolution(
        matched=True,
        route="profile_change_stale_plan_state_query",
        side_effect="readonly",
        blocking_reasons=["formal_plan_not_recalculated_after_profile_change"],
    )


def _pending_plan_action_family_from_state(pending_state: dict[str, Any] | None) -> str:
    if not isinstance(pending_state, dict):
        return ""
    action_family = str(pending_state.get("actionFamily") or pending_state.get("action_family") or "").strip()
    if action_family:
        return action_family
    execution_payload = pending_state.get("executionPayload")
    if not isinstance(execution_payload, dict):
        return ""
    return str(execution_payload.get("action_family") or execution_payload.get("actionFamily") or "").strip()


def _pending_turn_looks_plan_action_scoped_confirmation(
    content: str | None,
    pending_state: dict[str, Any] | None,
) -> bool:
    normalized = _normalize_confirmation_only_text(content, strip_fullwidth_question=True)
    if not normalized or normalized in _READONLY_CLOSURE_ACK_PHRASES:
        return False
    prefix = ""
    for candidate in sorted(_PENDING_PLAN_ACTION_CONFIRM_PREFIXES, key=len, reverse=True):
        if normalized.startswith(candidate):
            prefix = candidate
            break
    if not prefix:
        return False
    action_phrase = normalized[len(prefix):]
    if not action_phrase:
        return False
    action_family = _pending_plan_action_family_from_state(pending_state)
    if action_family not in PENDING_PLAN_ACTION_FAMILIES:
        return False
    action_keywords = _PENDING_PLAN_ACTION_CONFIRM_KEYWORDS.get(action_family, ())
    if not action_keywords:
        return False
    return any(keyword in action_phrase for keyword in action_keywords)


def pending_turn_looks_direct_confirmation(
    content: str | None,
    pending_kind: str | None,
    *,
    pending_state: dict[str, Any] | None = None,
) -> bool:
    normalized = _normalize_confirmation_only_text(content, strip_fullwidth_question=True)
    if not normalized or normalized in _READONLY_CLOSURE_ACK_PHRASES:
        return False
    pending_kind = str(pending_kind or "").strip()
    if pending_kind == "plan_mutation":
        return (
            normalized in _PENDING_DIRECT_PLAN_CONFIRM_ACKS
            or _pending_turn_looks_plan_action_scoped_confirmation(content, pending_state)
        )
    if pending_kind == "intent_change":
        return normalized in _PENDING_DIRECT_INTENT_CONFIRM_ACKS
    return False


def pending_turn_looks_no_active_pending_confirmation(content: str | None) -> bool:
    normalized = _normalize_confirmation_only_text(content, strip_fullwidth_question=True)
    if not normalized or normalized in _READONLY_CLOSURE_ACK_PHRASES:
        return False
    if normalized in _NO_ACTIVE_PENDING_CONFIRMATION_ACKS:
        return True
    return normalized.startswith(("确认", "执行", "采纳")) and len(normalized) <= 10


def pending_turn_looks_reject_pending(content: str | None) -> bool:
    normalized = _normalize_confirmation_only_text(content, strip_fullwidth_question=True)
    if not normalized:
        return False
    if normalized in _PENDING_REJECT_EXACT_ACKS:
        return True
    compact = _compact_text(content)
    if not any(token in compact for token in _PENDING_REJECT_TOKENS):
        return False
    return any(marker in compact for marker in _PENDING_REJECT_REFERENCE_MARKERS)


def _model_or_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dumped if isinstance(dumped, dict) else {}
    if hasattr(value, "dict"):
        dumped = value.dict()
        return dumped if isinstance(dumped, dict) else {}
    return {}


def _as_text_list(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        text = values.strip()
        return [text] if text else []
    if not isinstance(values, (list, tuple, set)):
        values = [values]
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _scope_entity_type(scope: dict[str, Any]) -> str:
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


def _scope_value_list(scope: dict[str, Any]) -> list[str]:
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


STRUCTURED_USER_GOAL_TYPES = frozenset(
    {"only_keep_scope", "must_include_scope", "exclude_scope", "tuition_budget_scope"}
)


def structured_goal_type_from_constraint_intent_type(constraint_intent_type: str) -> str:
    if str(constraint_intent_type or "").strip() == "only_keep":
        return "only_keep_scope"
    if str(constraint_intent_type or "").strip() == "must_have":
        return "must_include_scope"
    return "exclude_scope"


def structured_goal_from_composite_proposal(source: dict[str, Any] | None) -> dict[str, Any] | None:
    """Extract a valid structured PlanGoal from a composite proposal payload."""
    if not isinstance(source, dict):
        return None
    composite = source.get("composite_proposal") or source.get("compositeProposal")
    if not isinstance(composite, dict):
        return None
    goal = composite.get("goal")
    if not isinstance(goal, dict):
        return None
    goal_type = str(goal.get("goal_type") or goal.get("goalType") or "").strip()
    if goal_type not in STRUCTURED_USER_GOAL_TYPES:
        return None
    if goal.get("needs_clarification") is True or goal.get("needsClarification") is True:
        return None
    if goal_type == "tuition_budget_scope":
        if _as_int(goal.get("max_tuition_per_year") or goal.get("maxTuitionPerYear")) <= 0:
            return None
        return goal
    if goal_type in {"only_keep_scope", "must_include_scope"} and not goal.get("target_scopes") and not goal.get("targetScopes"):
        return None
    if goal_type == "exclude_scope" and not goal.get("negative_scopes") and not goal.get("negativeScopes"):
        return None
    return goal


def resolve_structured_goal_clarification(
    source: dict[str, Any] | None,
) -> StructuredGoalClarificationResolution:
    if not isinstance(source, dict):
        return StructuredGoalClarificationResolution(blocking_reasons=["missing_structured_goal_source"])
    composite = source.get("composite_proposal") or source.get("compositeProposal")
    if not isinstance(composite, dict):
        return StructuredGoalClarificationResolution(blocking_reasons=["missing_composite_proposal"])
    if str(composite.get("feasibility") or "").strip() != "needs_clarification":
        return StructuredGoalClarificationResolution(blocking_reasons=["structured_goal_clarification_not_needed"])
    goal = composite.get("goal")
    if not isinstance(goal, dict):
        return StructuredGoalClarificationResolution(blocking_reasons=["missing_structured_goal"])
    questions = [
        str(item or "").strip()
        for item in (
            goal.get("clarification_questions")
            or goal.get("clarificationQuestions")
            or []
        )
        if str(item or "").strip()
    ]
    scope_values: list[str] = []
    scopes = (
        goal.get("target_scopes")
        or goal.get("targetScopes")
        or goal.get("negative_scopes")
        or goal.get("negativeScopes")
        or []
    )
    for scope in scopes:
        if isinstance(scope, dict):
            scope_values.extend(_scope_value_list(scope))
    return StructuredGoalClarificationResolution(
        needed=True,
        questions=questions,
        scope_values=list(dict.fromkeys(value for value in scope_values if value)),
    )


def structured_proposal_needs_clarification(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    composite = payload.get("composite_proposal") or payload.get("compositeProposal")
    if not isinstance(composite, dict):
        return False
    if str(composite.get("feasibility") or "").strip() == "needs_clarification":
        return True
    goal = composite.get("goal")
    if not isinstance(goal, dict):
        return False
    return goal.get("needs_clarification") is True or goal.get("needsClarification") is True


def _structured_goal_req_scopes_for_scope(
    scope: dict[str, Any],
    *,
    evidence_source: str,
) -> list[dict[str, Any]]:
    values = _scope_value_list(scope)
    entity_type = _scope_entity_type(scope) or "unknown"
    scope_level = str(scope.get("scope_level") or scope.get("scopeLevel") or "").strip()
    return [
        {
            "scopeType": entity_type,
            "entityType": entity_type,
            "name": value,
            "normalizedName": value,
            "rawText": value,
            "resolutionStatus": "resolved",
            **({"scopeLevel": scope_level} if scope_level else {}),
            "evidence": {
                "source": evidence_source,
                "values": values,
                **({"scopeLevel": scope_level} if scope_level else {}),
            },
        }
        for value in values
    ]


def build_structured_user_goal_fix_proposal_request(
    goal: dict[str, Any],
    planning_version: int,
    *,
    context: dict[str, Any] | None = None,
    evidence_source: str = "confirmed_intent",
) -> dict[str, Any] | None:
    """Compile a structured PlanGoal into the Java user-goal proposal request."""
    if not isinstance(goal, dict) or planning_version <= 0:
        return None
    goal_type = str(goal.get("goal_type") or goal.get("goalType") or "").strip()
    if goal_type not in STRUCTURED_USER_GOAL_TYPES:
        return None
    normalized_context = dict(context or {})
    if goal_type == "tuition_budget_scope":
        max_tuition = _as_int(
            goal.get("max_tuition_per_year")
            or goal.get("maxTuitionPerYear")
            or normalized_context.get("maxTuitionPerYear")
        )
        if max_tuition <= 0:
            return None
        normalized_context["maxTuitionPerYear"] = max_tuition
        return {
            "proposalSource": "user_goal",
            "goalType": goal_type,
            "userOriginalText": str(goal.get("user_original_text") or goal.get("userOriginalText") or "").strip(),
            "confidence": str(goal.get("confidence") or "high").strip(),
            "sourceVersionGuard": planning_version,
            "targetScopes": [],
            "negativeScopes": [],
            "qualityGuards": [
                str(item or "").strip()
                for item in (goal.get("quality_guards") or goal.get("qualityGuards") or [])
                if str(item or "").strip()
            ],
            "tradeoffGuards": [
                str(item or "").strip()
                for item in (goal.get("structure_targets") or goal.get("structureTargets") or [])
                if str(item or "").strip()
            ],
            "context": normalized_context,
        }
    target_scopes = [
        req_scope
        for item in (goal.get("target_scopes") or goal.get("targetScopes") or [])
        if isinstance(item, dict)
        for req_scope in _structured_goal_req_scopes_for_scope(item, evidence_source=evidence_source)
    ]
    negative_scopes = [
        req_scope
        for item in (goal.get("negative_scopes") or goal.get("negativeScopes") or [])
        if isinstance(item, dict)
        for req_scope in _structured_goal_req_scopes_for_scope(item, evidence_source=evidence_source)
    ]
    if goal_type in {"only_keep_scope", "must_include_scope"} and not target_scopes:
        return None
    if goal_type == "exclude_scope" and not negative_scopes:
        return None
    return {
        "proposalSource": "user_goal",
        "goalType": goal_type,
        "userOriginalText": str(goal.get("user_original_text") or goal.get("userOriginalText") or "").strip(),
        "confidence": str(goal.get("confidence") or "high").strip(),
        "sourceVersionGuard": planning_version,
        "targetScopes": target_scopes,
        "negativeScopes": negative_scopes,
        "qualityGuards": [
            str(item or "").strip()
            for item in (goal.get("quality_guards") or goal.get("qualityGuards") or [])
            if str(item or "").strip()
        ],
        "tradeoffGuards": [
            str(item or "").strip()
            for item in (goal.get("structure_targets") or goal.get("structureTargets") or [])
            if str(item or "").strip()
        ],
        "context": normalized_context,
    }


def _structured_intent_selected_item_from_goal_scope(
    *,
    scope_type: str,
    values: list[str],
    negative: bool = False,
) -> dict[str, Any] | None:
    clean_values = _as_text_list(values)
    if not clean_values:
        return None
    if scope_type == "major":
        return {"major_intents": {"negative_level3" if negative else "level3": clean_values}}
    if scope_type == "school":
        return {"school_intents": {"negative_colleges" if negative else "colleges": clean_values}}
    if scope_type == "region":
        return {"city_intents": {"negative_province" if negative else "province": clean_values}}
    if scope_type == "program_type" and negative:
        return {"physical_constraints": {"special_limits": [f"不接受{value}" for value in clean_values]}}
    return None


def structured_intent_payload_from_composite_proposal(source: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(source, dict):
        return None
    override = source.get("intent_payload_override") or source.get("intentPayloadOverride")
    if isinstance(override, dict) and isinstance(override.get("selected"), list):
        return override
    composite = source.get("composite_proposal") or source.get("compositeProposal")
    if not isinstance(composite, dict):
        return None
    goal = composite.get("goal")
    if not isinstance(goal, dict):
        return None
    goal_type = str(goal.get("goal_type") or goal.get("goalType") or "").strip()
    constraint_intent_type = "default"
    if goal_type == "only_keep_scope":
        constraint_intent_type = "only_keep"
    elif goal_type == "must_include_scope":
        constraint_intent_type = "must_have"

    selected: list[dict[str, Any]] = []
    for scope in goal.get("target_scopes") or goal.get("targetScopes") or []:
        if not isinstance(scope, dict):
            continue
        item = _structured_intent_selected_item_from_goal_scope(
            scope_type=_scope_entity_type(scope) or "",
            values=_scope_value_list(scope),
            negative=False,
        )
        if item:
            selected.append(item)
    for scope in goal.get("negative_scopes") or goal.get("negativeScopes") or []:
        if not isinstance(scope, dict):
            continue
        item = _structured_intent_selected_item_from_goal_scope(
            scope_type=_scope_entity_type(scope) or "",
            values=_scope_value_list(scope),
            negative=True,
        )
        if item:
            selected.append(item)
    if not selected:
        return None
    return {
        "selected": selected,
        "intentMode": "constraint",
        "constraintIntentType": constraint_intent_type or "default",
    }


def _plan_query_profile_limit(filters: dict[str, Any], projection: dict[str, Any]) -> int:
    limit = _as_int(filters.get("limit") or projection.get("limit"), 5)
    return max(1, min(10, limit or 5))


def _condition_filters(query_profile: dict[str, Any]) -> dict[str, Any]:
    condition = query_profile.get("condition") if isinstance(query_profile.get("condition"), dict) else {}
    return condition.get("filters") if isinstance(condition.get("filters"), dict) else {}


def _condition_text_list(condition_filters: dict[str, Any], *keys: str) -> list[str]:
    for key in keys:
        values = _as_text_list(condition_filters.get(key))
        if values:
            return values
    return []


def _add_query_filter_list(
    filters: dict[str, Any],
    *,
    list_key: str,
    single_key: str,
    values: list[str],
) -> None:
    if not values:
        return
    filters[list_key] = list(values)
    filters[single_key] = values[0]


def _pending_reference_values_from_state(
    pending_state: dict[str, Any] | None,
    entity_type: str,
) -> list[str]:
    if not isinstance(pending_state, dict):
        return []
    execution_payload = pending_state.get("executionPayload")
    if not isinstance(execution_payload, dict):
        return []
    selected_data = execution_payload.get("selectedData")
    if not isinstance(selected_data, dict):
        selected_data = execution_payload
    entity_profile = selected_data.get("entityProfile") if isinstance(selected_data.get("entityProfile"), dict) else {}
    values: list[str] = []

    def add_values(raw_values: Any) -> None:
        for raw in _as_text_list(raw_values):
            if raw not in values:
                values.append(raw)

    if entity_type == "major":
        add_values(entity_profile.get("majorValues"))
    elif entity_type == "school":
        add_values(entity_profile.get("schools"))

    selected = selected_data.get("selected") if isinstance(selected_data, dict) else None
    selected = selected if isinstance(selected, list) else []
    merged = execution_payload.get("merged") if isinstance(execution_payload.get("merged"), dict) else {}
    if isinstance(merged, dict):
        selected = [*selected, merged]
    for item in selected:
        if not isinstance(item, dict):
            continue
        if entity_type == "major":
            major_intents = item.get("major_intents") if isinstance(item.get("major_intents"), dict) else {}
            add_values(major_intents.get("level3") or major_intents.get("level2") or major_intents.get("level1"))
        elif entity_type == "school":
            school_intents = item.get("school_intents") if isinstance(item.get("school_intents"), dict) else {}
            add_values(school_intents.get("schoolNames") or school_intents.get("names") or school_intents.get("schools") or school_intents.get("colleges"))
    return values[:3]


def _compile_structured_plan_query_profile(
    *,
    content: str | None,
    query_profile: dict[str, Any],
    planning_version: int = 0,
    pending_exists: bool = False,
    pending_state: dict[str, Any] | None = None,
) -> RuntimePlanQueryCompiledSource:
    query_type = str(query_profile.get("queryType") or "").strip()
    if query_type not in _PLAN_QUERY_PROFILE_TYPES:
        return RuntimePlanQueryCompiledSource(blocking_reasons=["unsupported_plan_query_profile_type"])

    side_effect = "readonly_while_pending" if pending_exists else "readonly"
    raw_scope_anchor = str(query_profile.get("scopeAnchor") or "").strip()
    scope_anchor = raw_scope_anchor if raw_scope_anchor in {"current_plan", "pending_reference", "candidate_pool"} else "current_plan"
    raw_filters = query_profile.get("filters") if isinstance(query_profile.get("filters"), dict) else {}
    condition_filters = _condition_filters(query_profile)
    raw_projection = query_profile.get("projection") if isinstance(query_profile.get("projection"), dict) else {}
    raw_dimensions = _as_text_list(query_profile.get("dimensions"))
    dimensions = [
        dimension
        for dimension in raw_dimensions
        if dimension in _PLAN_QUERY_PROFILE_DIMENSIONS
    ]
    filters: dict[str, Any] = {"limit": _plan_query_profile_limit(raw_filters, raw_projection)}
    projection: dict[str, Any]
    reply_focus = _as_text_list(query_profile.get("replyFocus"))
    if not reply_focus:
        reply_focus = (
            ["candidate_snapshot", "local_candidate_query"]
            if scope_anchor == "candidate_pool"
            else ["ordered_snapshot", "local_plan_query"]
        )

    if scope_anchor == "candidate_pool" and query_type not in {"readonly_plan_query", "readonly_plan_slice_query"}:
        return RuntimePlanQueryCompiledSource(blocking_reasons=["unsupported_candidate_query_type"])

    if query_type == "readonly_plan_query":
        if "tuition" in dimensions:
            min_tuition = _as_int(raw_filters.get("min_tuition_per_year") or raw_filters.get("minTuitionPerYear"))
            max_tuition = _as_int(raw_filters.get("max_tuition_per_year") or raw_filters.get("maxTuitionPerYear"))
            if min_tuition <= 0 and max_tuition <= 0:
                return RuntimePlanQueryCompiledSource(blocking_reasons=["missing_tuition_threshold"])
            if min_tuition > 0:
                filters["min_tuition_per_year"] = min_tuition
            if max_tuition > 0:
                filters["max_tuition_per_year"] = max_tuition
            projection = {
                "mode": str(raw_projection.get("mode") or "count_with_examples").strip() or "count_with_examples",
                "limit": filters["limit"],
            }
            if "plan_filter_query" not in reply_focus:
                reply_focus.append("plan_filter_query")
            if "tuition" not in reply_focus:
                reply_focus.append("tuition")
        elif any(dimension in dimensions for dimension in ("count_summary", "item_list", "school_presence", "safety_check")):
            projection = {
                "mode": str(raw_projection.get("mode") or dimensions[0]).strip() or dimensions[0],
                "limit": _plan_query_profile_limit(raw_filters, raw_projection),
            }
            if raw_filters.get("item_type"):
                filters["item_type"] = str(raw_filters.get("item_type") or "").strip()
            school_keywords = _as_text_list(
                raw_filters.get("school_keywords") or raw_filters.get("schoolKeywords")
            ) or _condition_text_list(condition_filters, "schoolKeywords", "school_keywords")
            school_keyword = str(raw_filters.get("school_keyword") or raw_filters.get("schoolKeyword") or "").strip()
            if not school_keywords and school_keyword:
                school_keywords = [school_keyword]
            _add_query_filter_list(
                filters,
                list_key="school_keywords",
                single_key="school_keyword",
                values=school_keywords,
            )
            major_keywords = _as_text_list(
                raw_filters.get("major_keywords") or raw_filters.get("majorKeywords")
            ) or _condition_text_list(condition_filters, "majorKeywords", "major_keywords")
            major_keyword = str(raw_filters.get("major_keyword") or raw_filters.get("majorKeyword") or "").strip()
            if not major_keywords and major_keyword:
                major_keywords = [major_keyword]
            _add_query_filter_list(
                filters,
                list_key="major_keywords",
                single_key="major_keyword",
                values=major_keywords,
            )
            province_names = _as_text_list(
                raw_filters.get("province_names") or raw_filters.get("provinceNames")
            ) or _condition_text_list(condition_filters, "provinceNames", "province_names")
            province_keyword = str(
                raw_filters.get("province_keyword") or raw_filters.get("provinceKeyword") or ""
            ).strip()
            if not province_names and province_keyword:
                province_names = [province_keyword]
            _add_query_filter_list(
                filters,
                list_key="province_names",
                single_key="province_keyword",
                values=province_names,
            )
            city_names = _as_text_list(
                raw_filters.get("city_names") or raw_filters.get("cityNames")
            ) or _condition_text_list(condition_filters, "cityNames", "city_names")
            city_keyword = str(raw_filters.get("city_keyword") or raw_filters.get("cityKeyword") or "").strip()
            if not city_names and city_keyword:
                city_names = [city_keyword]
            _add_query_filter_list(
                filters,
                list_key="city_names",
                single_key="city_keyword",
                values=city_names,
            )
            school_tags = _as_text_list(
                raw_filters.get("school_tags") or raw_filters.get("schoolTags")
            ) or _condition_text_list(condition_filters, "schoolTags", "school_tags")
            if school_tags:
                filters["school_tags"] = school_tags
            major_tags = _as_text_list(
                raw_filters.get("major_tags") or raw_filters.get("majorTags")
            ) or _condition_text_list(condition_filters, "majorTags", "major_tags")
            if major_tags:
                filters["major_tags"] = major_tags
            if "count_summary" in dimensions and "count_summary" not in reply_focus:
                reply_focus.append("count_summary")
            if "item_list" in dimensions and "school_list_query" not in reply_focus:
                reply_focus.append("school_list_query")
            if "school_presence" in dimensions and "school_presence_query" not in reply_focus:
                reply_focus.append("school_presence_query")
            if "safety_check" in dimensions and "safety_check" not in reply_focus:
                reply_focus.append("safety_check")
        else:
            return RuntimePlanQueryCompiledSource(blocking_reasons=["unsupported_plan_query_profile_dimension"])

    elif query_type == "readonly_plan_slice_query":
        tier = _PLAN_QUERY_PROFILE_TIER_NORMALIZATION.get(str(raw_filters.get("tier") or "").strip(), "")
        if not tier:
            return RuntimePlanQueryCompiledSource(blocking_reasons=["missing_tier_scope"])
        slice_mode = str(raw_filters.get("slice") or raw_projection.get("slice") or "head").strip()
        if slice_mode not in {"head", "tail"}:
            slice_mode = "head"
        fields = [
            field
            for field in _as_text_list(raw_filters.get("include_fields") or raw_projection.get("fields"))
            if field in _PLAN_QUERY_PROFILE_FIELDS
        ]
        if not fields:
            fields = ["school", "major", "admission_probability"]
        filters.update(
            {
                "tier": tier,
                "slice": slice_mode,
                "include_fields": fields,
            }
        )
        projection = {
            "mode": str(raw_projection.get("mode") or "slice_examples").strip() or "slice_examples",
            "limit": filters["limit"],
            "fields": fields,
        }
        dimensions = ["tier_segment"]
        slice_focus = "candidate_slice_query" if scope_anchor == "candidate_pool" else "plan_slice_query"
        if slice_focus not in reply_focus:
            reply_focus.append(slice_focus)

    else:
        scope_anchor = "pending_reference"
        pending_reference_type = str(query_profile.get("pendingReferenceType") or raw_filters.get("pending_reference_type") or "").strip()
        major_keyword = str(raw_filters.get("major_keyword") or raw_filters.get("majorKeyword") or "").strip()
        school_keyword = str(raw_filters.get("school_keyword") or raw_filters.get("schoolKeyword") or "").strip()
        if not major_keyword and pending_reference_type == "major":
            major_values = _pending_reference_values_from_state(pending_state, "major")
            if major_values:
                major_keyword = major_values[0]
        if not school_keyword and pending_reference_type == "school":
            school_values = _pending_reference_values_from_state(pending_state, "school")
            if school_values:
                school_keyword = school_values[0]
        if major_keyword:
            filters["major_keyword"] = major_keyword
        if school_keyword:
            filters["school_keyword"] = school_keyword
        if not major_keyword and not school_keyword:
            return RuntimePlanQueryCompiledSource(blocking_reasons=["missing_pending_reference_entity"])
        projection = {
            "mode": str(raw_projection.get("mode") or "examples").strip() or "examples",
            "limit": filters["limit"],
        }
        dimensions = ["pending_reference"]
        if "pending_reference_query" not in reply_focus:
            reply_focus.append("pending_reference_query")

    goal = str(content or query_profile.get("userGoal") or "").strip()
    if scope_anchor == "candidate_pool":
        action_family = "query_candidates"
    elif query_type == "readonly_plan_query" and "count_summary" in dimensions and not any(
        key in filters for key in ("min_tuition_per_year", "max_tuition_per_year", "major_keyword", "school_keyword")
    ):
        action_family = "query_state"
    else:
        action_family = "query_ordered"
    result_focus = "candidate_snapshot" if action_family == "query_candidates" else "ordered_snapshot"
    if result_focus not in reply_focus:
        reply_focus.insert(0, result_focus)
    plan_query_dsl = {
        "type": "PlanQuery",
        "scopeAnchor": scope_anchor,
        "sideEffect": side_effect,
        "queryType": query_type,
        "dimensions": dimensions,
        "filters": dict(filters),
        "projection": dict(projection),
        "sourceVersionGuard": planning_version,
    }
    plan_payload = {
        "stage": "apply",
        "action_family": action_family,
        "user_goal": goal,
        "requires_confirmation": False,
        "planning_version": planning_version,
        "atomic_actions": [
            {
                "action_type": action_family,
                "filters": dict(filters),
                "reason": goal,
            }
        ],
        "reply_focus": reply_focus,
        "facts": {
            "plan_query_dsl": dict(plan_query_dsl),
            "requested_reply_focus": list(reply_focus),
        },
    }
    return RuntimePlanQueryCompiledSource(
        matched=True,
        route=query_type,
        side_effect=side_effect,
        action_family=action_family,
        plan_payload=plan_payload,
        plan_query_dsl=plan_query_dsl,
        source_version_guard=planning_version,
    )


def compile_runtime_plan_query_profile_source(
    *,
    content: str | None,
    query_profile: Any,
    planning_version: int = 0,
    pending_exists: bool = False,
    pending_state: dict[str, Any] | None = None,
) -> RuntimePlanQueryCompiledSource:
    """Compile a structured 3.2.0 PlanQuery profile into runtime DSL.

    Query intent belongs to the model/framework layer. This compiler validates
    the structured profile and builds the executable payload; it does not infer
    query dimensions from raw prompt text.
    """
    profile = _model_or_dict(query_profile)
    if not profile:
        return RuntimePlanQueryCompiledSource(blocking_reasons=["missing_plan_query_profile"])
    return _compile_structured_plan_query_profile(
        content=content,
        query_profile=profile,
        planning_version=planning_version,
        pending_exists=pending_exists,
        pending_state=pending_state,
    )


def _decision_text_field(decision: Any, field_name: str) -> str:
    data = _model_or_dict(decision)
    if field_name in data:
        return str(data.get(field_name) or "").strip()
    return str(getattr(decision, field_name, "") or "").strip()


def _decision_float_field(decision: Any, field_name: str) -> float:
    data = _model_or_dict(decision)
    value = data.get(field_name) if field_name in data else getattr(decision, field_name, 0.0)
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _current_plan_mutation_gate_from_turn_decision(decision: Any) -> list[str]:
    reasons: list[str] = []
    if decision is None:
        return ["missing_turn_decision"]
    confidence = _decision_float_field(decision, "confidence")
    task_layer = _decision_text_field(decision, "taskLayer")
    side_effect = _decision_text_field(decision, "sideEffect")
    scope_anchor = _decision_text_field(decision, "scopeAnchor")
    scenario = _decision_text_field(decision, "scenario")
    if confidence < 0.65:
        reasons.append("low_turn_decision_confidence")
    if task_layer not in {"plan", "mixed"}:
        reasons.append("unsupported_current_plan_mutation_task_layer")
    if side_effect not in {"plan_preview", "readonly_or_plan_preview"}:
        reasons.append("unsupported_current_plan_mutation_side_effect")
    if scope_anchor not in {"current_plan", "current_major_group"}:
        reasons.append("unsupported_current_plan_mutation_scope_anchor")
    if scenario != "atomic_mutation":
        reasons.append("unsupported_current_plan_mutation_scenario")
    return reasons


def _turn_decision_is_current_plan_atomic_mutation(decision: Any) -> bool:
    return not _current_plan_mutation_gate_from_turn_decision(decision)


def compile_runtime_intent_preview_turn_decision_arbitration_source(
    *,
    turn_decision: Any,
    turn_decision_blocks_intent_pending: bool,
    semantic_intent_preview_requested: bool,
    semantic_entity_kinds: list[str] | set[str] | tuple[str, ...],
    preview_payload_entity_kinds: list[str] | set[str] | tuple[str, ...],
    preview_candidate_valid: bool,
    constraint_intent_type: str = "",
) -> RuntimeIntentPreviewTurnDecisionArbitrationSource:
    """Arbitrate a soft TurnDecision hard cut against full-agent Intent evidence.

    This compiler consumes structured framework outputs only. It may allow a
    later full-agent Intent preview to create an intent pending when the initial
    TurnDecision was a general/exploratory readonly cut. High-confidence current
    plan atomic mutations remain in the Plan compiler path.
    """

    if not turn_decision_blocks_intent_pending:
        return RuntimeIntentPreviewTurnDecisionArbitrationSource(
            blocking_reasons=["turn_decision_does_not_block_intent_pending"],
        )

    task_layer = _decision_text_field(turn_decision, "taskLayer")
    side_effect = _decision_text_field(turn_decision, "sideEffect")
    scope_anchor = _decision_text_field(turn_decision, "scopeAnchor")
    scenario = _decision_text_field(turn_decision, "scenario")
    confidence = _decision_float_field(turn_decision, "confidence")
    semantic_kinds = {
        str(kind or "").strip()
        for kind in semantic_entity_kinds
        if str(kind or "").strip()
    }
    payload_kinds = {
        str(kind or "").strip()
        for kind in preview_payload_entity_kinds
        if str(kind or "").strip()
    }
    normalized_constraint_intent_type = str(constraint_intent_type or "").strip()
    current_plan_atomic_mutation = _turn_decision_is_current_plan_atomic_mutation(turn_decision)
    durable_constraint_intent = normalized_constraint_intent_type in {"must_have", "only_keep"}

    blocking_reasons: list[str] = []
    if current_plan_atomic_mutation and not durable_constraint_intent:
        blocking_reasons.append("current_plan_atomic_mutation_requires_plan_route")
    if task_layer not in {"intent", "explore", "mixed"} and not (
        current_plan_atomic_mutation and durable_constraint_intent
    ):
        blocking_reasons.append("unsupported_turn_decision_task_layer_for_intent_override")
    if side_effect not in {"readonly", "readonly_while_pending"} and not (
        current_plan_atomic_mutation and durable_constraint_intent
    ):
        blocking_reasons.append("unsupported_turn_decision_side_effect_for_intent_override")
    if scope_anchor not in {"", "general", "future_reference"} and not (
        current_plan_atomic_mutation and durable_constraint_intent
    ):
        blocking_reasons.append("unsupported_turn_decision_scope_anchor_for_intent_override")
    if scenario in {
        "plan_query",
        "plan_query_while_pending",
        "state_query_while_pending",
        "apply_pending_then_readonly_query",
        "major_group_local_policy_query",
    }:
        blocking_reasons.append("plan_query_turn_decision_cannot_be_intent_override")
    if not semantic_intent_preview_requested:
        blocking_reasons.append("semantic_decision_not_intent_preview")
    if not preview_candidate_valid:
        blocking_reasons.append("invalid_intent_preview_candidate")
    if not payload_kinds:
        blocking_reasons.append("missing_intent_preview_payload_entity_kinds")
    if semantic_kinds and not semantic_kinds.issubset(payload_kinds):
        blocking_reasons.append("semantic_payload_entity_kind_mismatch")

    arbitration_dsl = {
        "type": "IntentPreviewTurnDecisionArbitration",
        "sourceInputs": [
            "turn_decision",
            "intent_side_effect_decision",
            "intent_preview_payload",
            "intent_preview_candidate",
        ],
        "turnDecision": {
            "taskLayer": task_layer,
            "sideEffect": side_effect,
            "scopeAnchor": scope_anchor,
            "scenario": scenario,
            "confidence": confidence,
        },
        "semanticIntentPreviewRequested": bool(semantic_intent_preview_requested),
        "semanticEntityKinds": sorted(semantic_kinds),
        "previewPayloadEntityKinds": sorted(payload_kinds),
        "previewCandidateValid": bool(preview_candidate_valid),
        "constraintIntentType": normalized_constraint_intent_type,
        "durableConstraintIntent": bool(durable_constraint_intent),
    }
    if blocking_reasons:
        return RuntimeIntentPreviewTurnDecisionArbitrationSource(
            route="turn_decision_intent_preview_arbitration",
            arbitration_dsl=arbitration_dsl,
            blocking_reasons=blocking_reasons,
        )

    return RuntimeIntentPreviewTurnDecisionArbitrationSource(
        matched=True,
        route="turn_decision_intent_preview_arbitration",
        side_effect="intent_pending",
        allow_intent_pending=True,
        arbitration_dsl=arbitration_dsl,
    )


def _intent_preview_selected_item_texts(preview_payload: dict[str, Any] | None) -> list[str]:
    if not isinstance(preview_payload, dict):
        return []
    texts: list[str] = []
    for item in preview_payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        if item.get("selected") is False:
            continue
        value = item.get("value") if isinstance(item.get("value"), dict) else {}
        for group in value.values():
            if not isinstance(group, dict):
                continue
            for raw_values in group.values():
                for value_text in _as_text_list(raw_values):
                    if value_text and value_text not in texts:
                        texts.append(value_text)
        if texts:
            continue
        content = str(item.get("content") or "").strip()
        if content and content not in texts:
            texts.append(content)
    return texts[:6]


def compile_blocked_intent_preview_for_plan_route_reply_source(
    *,
    turn_decision: Any | None,
    preview_payload: dict[str, Any] | None,
) -> RuntimeBlockedIntentPreviewReplySource:
    if turn_decision is None:
        return RuntimeBlockedIntentPreviewReplySource(
            blocking_reasons=["missing_turn_decision"],
        )
    if not _turn_decision_is_current_plan_atomic_mutation(turn_decision):
        return RuntimeBlockedIntentPreviewReplySource(
            blocking_reasons=["turn_decision_not_current_plan_atomic_mutation"],
        )
    selected_texts = _intent_preview_selected_item_texts(preview_payload)
    if not selected_texts:
        return RuntimeBlockedIntentPreviewReplySource(
            blocking_reasons=["missing_intent_preview_selected_items"],
        )

    intent_mode = str((preview_payload or {}).get("intentMode") or "").strip()
    constraint_type = str((preview_payload or {}).get("constraintIntentType") or "").strip()
    focus_label = "、".join(selected_texts[:3])
    if len(focus_label) > 80:
        focus_label = focus_label[:77].rstrip() + "..."
    first_line = f"我识别到你这轮关心的是：{focus_label}。"
    if constraint_type == "must_have":
        first_line = f"我识别到你想让当前方案至少满足：{focus_label}。"
    elif constraint_type == "only_keep":
        first_line = f"我识别到你想让当前方案只保留：{focus_label}。"
    elif intent_mode == "constraint":
        first_line = f"我识别到你这轮的诉求是调整当前方案范围：{focus_label}。"

    reply = (
        f"{first_line}\n\n"
        "但这句话的锚点是当前方案调整，本轮没有形成可执行的调整内容，"
        "所以不会创建长期意向卡，也不会改动当前方案。\n\n"
        "需要先定位当前方案中的命中项并生成调整预览；确认前不会执行。"
    )
    return RuntimeBlockedIntentPreviewReplySource(
        matched=True,
        route="blocked_intent_preview_for_current_plan_mutation",
        primary_reply=reply,
        display_payload={
            "presentation": "readonly_boundary",
            "reason": "intent_preview_blocked_by_current_plan_mutation",
            "selectedItems": selected_texts,
        },
        reply_plan={
            "mode": ["readonly_boundary"],
            "focus": ["current_plan_mutation_requires_plan_preview"],
        },
    )


_LOCAL_PLAN_TIER_NORMALIZATION = {
    "保": "保",
    "保底": "保",
    "保档": "保",
    "稳": "稳",
    "稳档": "稳",
    "冲": "冲",
    "冲档": "冲",
}

_LOCAL_PLAN_SORT_FIELD_NORMALIZATION = {
    "admissionRatio": "admissionRatio",
    "admission_probability": "admissionRatio",
    "admissionProbability": "admissionRatio",
    "schoolRank": "schoolRank",
    "school_rank": "schoolRank",
    "finalScore": "finalScore",
    "final_score": "finalScore",
}

_LOCAL_PLAN_RANK_VALUES = {"highest", "lowest", "best", "worst"}
_LOCAL_PLAN_TARGET_RANK_VALUES = {"first", "last"}


def compile_runtime_local_plan_action_source(
    *,
    content: str | None,
    action_family: str,
    tier: str | None,
    sort_field: str | None,
    rank: str | None,
    target_ordinal: int | None = None,
    target_rank: str | None = None,
    planning_version: int = 0,
) -> RuntimeLocalPlanActionSource:
    """Validate a model-produced 3.2.0 LocalPlanActionDsl and build the executable payload."""
    action_family = str(action_family or "").strip()
    tier = _LOCAL_PLAN_TIER_NORMALIZATION.get(str(tier or "").strip(), "")
    sort_by = _LOCAL_PLAN_SORT_FIELD_NORMALIZATION.get(str(sort_field or "").strip(), "")
    rank = str(rank or "").strip()
    target_rank = str(target_rank or "").strip()
    target: dict[str, Any] = {}
    if target_ordinal is not None:
        try:
            ordinal = int(target_ordinal)
        except (TypeError, ValueError):
            ordinal = 0
        if ordinal > 0:
            target["targetOrdinal"] = ordinal
    elif target_rank in _LOCAL_PLAN_TARGET_RANK_VALUES:
        target["targetRank"] = target_rank
    blocking_reasons: list[str] = []
    if action_family != "move_ordered_unit":
        blocking_reasons.append("unsupported_local_plan_action_family")
    if not tier:
        blocking_reasons.append("missing_tier_scope")
    if not sort_by:
        blocking_reasons.append("missing_sort_metric")
    if rank not in _LOCAL_PLAN_RANK_VALUES:
        blocking_reasons.append("missing_selector_rank")
    if not target:
        blocking_reasons.append("missing_target_ordinal")
    if blocking_reasons:
        return RuntimeLocalPlanActionSource(blocking_reasons=blocking_reasons)

    filters: dict[str, Any] = {
        "tier": tier,
        "sortBy": sort_by,
        "rank": rank,
    }
    filters.update(target)
    goal = str(content or "").strip()
    plan_action_dsl = {
        "action": "move_ordered_unit",
        "scopeAnchor": "current_plan.tier_segment",
        "ordinalScope": "within_tier",
        "selector": {
            "tier": tier,
            "sortBy": sort_by,
            "rank": rank,
        },
        "targetPosition": {
            "tier": tier,
            "ordinalScope": "within_tier",
            **target,
        },
    }
    plan_payload: dict[str, Any] = {
        "stage": "preview",
        "action_family": action_family,
        "user_goal": goal,
        "requires_confirmation": True,
        "should_rerun_review": True,
        "should_refresh_workspace": True,
        "workspace_refresh_targets": ["ordered"],
        "atomic_actions": [
            {
                "action_type": "move_ordered_unit",
                "filters": filters,
                "reason": goal,
            }
        ],
        "reply_focus": ["local_plan_action", "tier_local_reorder"],
        "facts": {
            "planActionDsl": plan_action_dsl,
        },
    }
    if planning_version > 0:
        plan_payload["planning_version"] = int(planning_version)

    return RuntimeLocalPlanActionSource(
        matched=True,
        route="local_plan_action",
        action_family=action_family,
        plan_payload=plan_payload,
        plan_action_dsl=plan_action_dsl,
        source_version_guard=int(planning_version or 0),
    )


def compile_post_apply_readonly_evidence_plan(
    content: str | None,
    *,
    pending_state: dict[str, Any] | None,
    target_issues: list[str] | None = None,
) -> dict[str, Any]:
    """Build the structured EvidencePlan for apply-existing-pending + readonly follow-up.

    This intentionally does not execute tools. It records what must be checked
    after the pending apply succeeds so runtime can avoid unsupported claims.
    The caller should pass semantic target issues from TurnDecision; this
    compiler does not infer issue scope from the raw user prompt.
    """
    pending_kind = str((pending_state or {}).get("kind") or "").strip()
    if pending_kind == "plan_mutation":
        scope_anchor = "current_plan"
        required_inputs = ["active_pending", "formal_ordered_plan_after_apply"]
        default_targets = ["ordered", "review"]
        no_result_reason = "post_apply_plan_requires_refreshed_evidence"
    elif pending_kind == "intent_change":
        scope_anchor = "current_plan"
        required_inputs = ["active_pending", "applied_intent_profile", "formal_ordered_plan_after_apply"]
        default_targets = ["candidate", "ordered", "review"]
        no_result_reason = "post_apply_intent_requires_refreshed_evidence"
    else:
        scope_anchor = "unknown"
        required_inputs = ["refreshed_state"]
        default_targets = ["ordered"]
        no_result_reason = "post_apply_requires_refreshed_evidence"

    normalized_target_issues: list[str] = []
    for issue in target_issues or []:
        text = str(issue or "").strip()
        if text and text not in normalized_target_issues:
            normalized_target_issues.append(text)
    target_issues = normalized_target_issues
    if not target_issues:
        target_issues = (
            ["current_plan_state", "remaining_count", "tier_distribution", "risk_review"]
            if pending_kind == "plan_mutation"
            else ["post_apply_state"]
        )

    steps: list[dict[str, Any]] = [
        {
            "step": "apply_existing_pending",
            "purpose": "apply_active_pending_before_readonly_followup",
            "requiresAppliedPending": True,
        }
    ]
    if any(issue in target_issues for issue in ("remaining_count", "tier_distribution", "current_plan_state", "post_apply_state")):
        steps.append(
            {
                "step": "read_latest_plan_summary",
                "purpose": "answer_post_apply_plan_state",
                "requiresAppliedPending": True,
            }
        )
    if "risk_review" in target_issues:
        steps.append(
            {
                "step": "review_tier_gradient",
                "purpose": "answer_post_apply_risk",
                "requiresAppliedPending": True,
            }
        )
    if pending_kind == "intent_change":
        steps.append(
            {
                "step": "read_refreshed_candidate_view",
                "purpose": "answer_post_intent_candidate_impact",
                "requiresAppliedPending": True,
            }
        )

    return {
        "type": "EvidencePlan",
        "trigger": "apply_pending_then_readonly",
        "scopeAnchor": scope_anchor,
        "targetIssues": target_issues,
        "requiredInputs": required_inputs,
        "steps": steps,
        "workspaceRefreshTargets": default_targets,
        "toolBudget": {"maxToolCalls": 3, "batchPreferred": True},
        "noResultReason": no_result_reason,
        "mustNotAnswerWithoutEvidence": True,
    }


_RUNTIME_UNBACKED_CONFIRM_SENTENCE_RE = re.compile(r"(?:是否先确认|是否确认|确认要我.*执行)")


def _compact_runtime_reply_text(reply: str) -> str:
    return re.sub(r'[\s"“”‘’`\'「」『』【】\[\]（）()<>《》:：,，。.!！？?、]+', "", str(reply or ""))


def runtime_reply_has_plan_confirmation_request(reply: str) -> bool:
    compact = _compact_runtime_reply_text(reply)
    if not compact or "确认" not in compact:
        return False
    if any(marker in compact for marker in ("无法进入可执行", "没有上一轮待确认", "还没有拿到可执行", "技术问题")):
        return False
    if ("如果你确认" in compact or "你确认后" in compact) and any(
        keyword in compact
        for keyword in (
            "执行调整",
            "执行修改",
            "执行改动",
            "执行替换",
            "直接调整",
            "直接修改",
            "直接改动",
            "删除志愿",
            "移除志愿",
            "移动志愿",
            "移出",
            "重排方案",
            "调整方案",
            "改动方案",
            "更新方案",
        )
    ):
        return True
    return any(
        marker in compact
        for marker in (
            "回复确认",
            "是否先确认",
            "是否确认",
            "确认即可",
            "确认后",
            "确认应用",
            "确认执行",
            "确认替换",
            "确认生成",
            "确认重排",
            "确认添加",
            "确认加入",
            "确认加入方案",
            "确认把",
            "确认要",
        )
    )


def _runtime_line_looks_like_unbacked_plan_confirmation(compact: str) -> bool:
    if "确认" not in compact:
        return False
    normalized = _compact_runtime_reply_text(compact)
    if normalized.strip("*#：:？?") in {"确认替换吗", "确认执行吗", "确认修改吗", "确认改动吗"}:
        return True
    if "确认" in normalized and any(
        keyword in normalized
        for keyword in ("即可执行", "就执行", "立即执行", "执行替换", "执行修改", "执行改动")
    ):
        return True
    return any(
        marker in normalized
        for marker in (
            "确认后会执行",
            "确认后执行",
            "确认后我就调整",
            "确认后就调整",
            "确认后我来调整",
            "确认后我再调整",
            "确认后再调整",
            "点击确认后生效",
            "确认后生效",
            "确认即可执行",
            "回复确认即可",
            "回复确认后",
            "确认要删除吗",
            "确认要移除吗",
            "确认要去掉吗",
            "确认要调整吗",
            "确认要添加吗",
            "确认要加入吗",
            "确认添加吗",
            "确认加入吗",
            "确认加入方案吗",
            "确认把",
            "确认要这样",
            "确认要我",
            "是否先确认",
            "是否确认",
        )
    )


def strip_unbacked_plan_confirmation_copy(reply: str) -> str:
    if not isinstance(reply, str) or not reply.strip():
        return reply

    normalized_lines: list[str] = []
    for raw_line in reply.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            if normalized_lines and normalized_lines[-1] != "":
                normalized_lines.append("")
            continue
        if stripped == "**":
            continue
        compact = re.sub(r"\s+", "", stripped)
        sentence_parts = re.findall(r"[^。！？.!?]+[。！？.!?]?", raw_line)
        if len(sentence_parts) <= 1:
            if _runtime_line_looks_like_unbacked_plan_confirmation(compact):
                continue
            if _RUNTIME_UNBACKED_CONFIRM_SENTENCE_RE.search(compact):
                continue
        if not sentence_parts:
            normalized_lines.append(raw_line.rstrip())
            continue
        kept_parts = []
        for part in sentence_parts:
            compact_part = re.sub(r"\s+", "", part)
            if _runtime_line_looks_like_unbacked_plan_confirmation(compact_part):
                continue
            if _RUNTIME_UNBACKED_CONFIRM_SENTENCE_RE.search(compact_part):
                continue
            if (
                (
                    "如果确认" in compact_part
                    or "如果你确认" in compact_part
                    or "你确认后" in compact_part
                    or "是否确认" in compact_part
                    or "是否先确认" in compact_part
                )
                and any(keyword in compact_part for keyword in ("我会", "将会", "直接", "执行", "替换", "修改", "改动", "加入", "添加", "作为"))
            ):
                continue
            kept_parts.append(part)
        line = "".join(kept_parts).rstrip()
        if line.strip():
            normalized_lines.append(line)

    while normalized_lines and normalized_lines[0] == "":
        normalized_lines.pop(0)
    while normalized_lines and normalized_lines[-1] == "":
        normalized_lines.pop()
    return "\n".join(normalized_lines)


def runtime_reply_looks_like_unbacked_plan_confirmation(reply: str) -> bool:
    """Detect final reply copy that promises Plan confirmation without a card."""
    if not isinstance(reply, str) or not runtime_reply_has_plan_confirmation_request(reply):
        return False
    compact = _compact_runtime_reply_text(reply)
    if not compact:
        return False
    if any(marker in compact for marker in ("确认卡片", "点击卡片", "没有生成可点击", "不会改动当前方案")):
        return False
    intent_reference_markers = (
        "后续报考参考",
        "后续参考",
        "推荐口径",
        "优先考虑",
        "不优先考虑",
        "作为后续",
        "记入",
        "记录为",
        "作为偏好",
        "作为要求",
    )
    has_current_plan_execution_marker = any(
        marker in compact
        for marker in (
            "当前方案",
            "方案里",
            "加入方案",
            "添加到方案",
            "删除志愿",
            "移除志愿",
            "移出",
            "替换",
            "移动",
            "排序",
            "重排",
            "执行调整",
            "执行修改",
            "执行改动",
        )
    )
    if any(marker in compact for marker in intent_reference_markers) and not has_current_plan_execution_marker:
        return False
    has_plan_subject = any(
        marker in compact
        for marker in (
            "方案",
            "志愿",
            "专业组",
            "候选",
            "当前方案",
        )
    )
    has_mutation_effect = any(
        marker in compact
        for marker in (
            "删除",
            "删掉",
            "去掉",
            "移除",
            "移出",
            "加入",
            "添加",
            "替换",
            "换成",
            "移动",
            "挪到",
            "排序",
            "重排",
            "调整",
            "更新",
            "执行",
            "生效",
            "写入后续报考参考",
            "作为优先专业方向",
        )
    )
    return has_plan_subject and has_mutation_effect


def runtime_reply_looks_like_unbacked_plan_action_boundary(reply: str) -> bool:
    if not isinstance(reply, str):
        return False
    compact = _compact_runtime_reply_text(reply)
    if not compact:
        return False
    return any(
        marker in compact
        for marker in (
            "还没有生成可执行的调整内容",
            "没有生成可执行的调整内容",
            "这轮还没有生成可执行",
            "这轮还没有生成可点击的方案待采纳内容",
        )
    )


def runtime_reply_claims_intent_recorded_without_pending(reply: str) -> bool:
    """Detect final reply claims that an intent was saved without pending state."""
    compact = _compact_runtime_reply_text(reply)
    if not compact:
        return False
    if any(
        marker in compact
        for marker in (
            "不会写入后续参考",
            "不会写入后续报考参考",
            "不会作为后续参考",
            "采纳前不会生效",
            "点击采纳前不会生效",
            "点采纳前不会生效",
        )
    ):
        return False
    has_record_claim = any(
        marker in compact
        for marker in (
            "作为后续报考参考记下来",
            "作为后续参考记下来",
            "已经作为后续报考参考",
            "已作为后续报考参考",
            "已经写入后续报考参考",
            "已写入后续报考参考",
            "已经记录到后续参考",
            "已记录到后续参考",
            "已经记下来",
            "已记下来",
        )
    )
    has_unbacked_intent_confirmation_request = any(
        marker in compact
        for marker in (
            "请确认是否采纳",
            "确认是否采纳",
            "你确认要采纳",
            "确认要采纳",
            "是否采纳这条",
            "是否采纳这个",
        )
    ) and any(
        marker in compact
        for marker in (
            "报考条件",
            "报考想法",
            "院校意向",
            "专业意向",
            "地域意向",
            "偏好",
            "意向",
        )
    )
    if has_unbacked_intent_confirmation_request:
        return True
    if not has_record_claim:
        return False
    return any(
        marker in compact
        for marker in (
            "后续报考参考",
            "后续参考",
            "报考条件",
            "推荐口径",
            "优先保证",
            "生成或调整方案",
        )
    )


def compile_runtime_reply_guard_source(
    *,
    reply: str,
    guard_context: str = "auto",
    pending_card_created: bool = False,
    plan_confirmation_candidate_exists: bool = False,
    active_pending_exists: bool = False,
) -> RuntimeReplyGuardSource:
    """Compile output-only guard decisions from final reply and protocol state.

    This source never creates pending state and never infers user intent. It only
    marks unsupported final-copy commitments after structured routing has failed
    to produce a matching card or pending state.
    """
    if not isinstance(reply, str):
        return RuntimeReplyGuardSource(blocking_reasons=["reply_must_be_text"])

    if pending_card_created or plan_confirmation_candidate_exists:
        return RuntimeReplyGuardSource(blocking_reasons=["structured_confirmation_present"])

    context = str(guard_context or "auto").strip() or "auto"
    compact = _compact_runtime_reply_text(reply)

    if context in {"auto", "plan_confirmation"} and runtime_reply_looks_like_unbacked_plan_confirmation(reply):
        stripped = strip_unbacked_plan_confirmation_copy(reply).strip()
        return RuntimeReplyGuardSource(
            matched=True,
            route="unbacked_plan_confirmation_reply_guard",
            guard_type="unbacked_plan_confirmation",
            stripped_reply=stripped,
            display_payload={"presentation": "readonly_boundary"},
            reply_plan={
                "mode": ["reply_guard"],
                "focus": ["no_pending_card_boundary"],
            },
        )

    if context in {"auto", "plan_preview_without_card"}:
        if compact and (
            ("已列出" in compact or "已把" in compact or "整理成预览" in compact)
            and any(marker in compact for marker in ("调整预览", "处理预览", "方案预览", "确认前不会改动", "确认前不会执行"))
        ):
            stripped = strip_unbacked_plan_confirmation_copy(reply).strip()
            return RuntimeReplyGuardSource(
                matched=True,
                route="plan_preview_without_card_reply_guard",
                guard_type="plan_preview_without_card",
                stripped_reply=stripped,
                display_payload={"presentation": "readonly_boundary"},
                reply_plan={
                    "mode": ["reply_guard"],
                    "focus": ["no_pending_card_boundary"],
                },
            )

    if context in {"auto", "recorded_intent_without_pending"} and not active_pending_exists:
        if runtime_reply_claims_intent_recorded_without_pending(reply):
            return RuntimeReplyGuardSource(
                matched=True,
                route="recorded_intent_without_pending_reply_guard",
                guard_type="recorded_intent_without_pending",
                stripped_reply=reply.strip(),
                display_payload={"presentation": "readonly_boundary"},
                reply_plan={
                    "mode": ["reply_guard"],
                    "focus": ["no_pending_intent_boundary"],
                },
            )

    if context in {"auto", "no_tool_action_boundary"} and runtime_reply_looks_like_unbacked_plan_action_boundary(reply):
        if any(marker in compact for marker in ("重新定位影响范围并列出调整预览", "当前有效预览后才会执行")):
            return RuntimeReplyGuardSource(blocking_reasons=["action_boundary_already_specific"])
        if any(marker in compact for marker in ("志愿", "专业组", "候选")) and any(
            marker in compact for marker in ("还没有生成可执行的调整内容", "没有生成可执行的调整内容")
        ):
            return RuntimeReplyGuardSource(blocking_reasons=["action_boundary_already_entity_specific"])
        return RuntimeReplyGuardSource(
            matched=True,
            route="no_tool_action_boundary_reply_guard",
            guard_type="no_tool_action_boundary",
            stripped_reply=reply.strip(),
            display_payload={"presentation": "readonly_boundary"},
            reply_plan={
                "mode": ["reply_guard"],
                "focus": ["no_tool_no_action_boundary"],
            },
        )

    return RuntimeReplyGuardSource(blocking_reasons=["reply_guard_not_needed"])


def resolve_conditional_candidate_readonly_boundary(
    *,
    result: dict[str, Any] | None,
) -> ConditionalCandidateReadonlyBoundaryResolution:
    data = result if isinstance(result, dict) else {}
    if not data:
        return ConditionalCandidateReadonlyBoundaryResolution(
            blocking_reasons=["missing_candidate_boundary_result"],
        )

    action_family = str(data.get("action_family") or data.get("actionFamily") or "").strip()
    if action_family != "add_units":
        return ConditionalCandidateReadonlyBoundaryResolution(
            blocking_reasons=["unsupported_candidate_boundary_action_family"],
        )

    result_kind = str(data.get("result_kind") or data.get("resultKind") or "").strip()
    reply_focus = {
        str(item or "").strip()
        for item in (data.get("reply_focus") or data.get("replyFocus") or [])
        if str(item or "").strip()
    }
    missing_inputs = [
        str(item or "").strip()
        for item in (data.get("missing_inputs") or data.get("missingInputs") or [])
        if str(item or "").strip()
    ]

    if "needs_candidate_selection" in reply_focus:
        return ConditionalCandidateReadonlyBoundaryResolution(
            matched=True,
            route="conditional_candidate_selection_scope_boundary",
            reason_code="selection_scope",
            missing_inputs=missing_inputs,
        )

    if missing_inputs:
        return ConditionalCandidateReadonlyBoundaryResolution(
            matched=True,
            route="conditional_candidate_missing_inputs_boundary",
            reason_code="missing_inputs",
            missing_inputs=missing_inputs,
        )

    compact_summary = _compact_text(str(data.get("summary") or ""))
    if result_kind == "no_change" or "候选里暂时没有" in compact_summary:
        return ConditionalCandidateReadonlyBoundaryResolution(
            matched=True,
            route="conditional_candidate_no_match_boundary",
            reason_code="candidate_unavailable",
        )

    return ConditionalCandidateReadonlyBoundaryResolution(
        blocking_reasons=["candidate_boundary_not_needed"],
    )


_CURRENT_PLAN_REFERENCE_MARKERS = (
    "当前方案",
    "现在方案",
    "方案里",
    "方案中",
    "这个方案",
    "那个方案",
    "刚那个方案",
    "刚才那个方案",
    "刚刚那个方案",
    "上个方案",
    "上一版方案",
    "这版方案",
    "当前这版",
    "现在这版",
)

_CURRENT_PLAN_SCOPE_MARKERS = (
    "民办",
    "公办",
    "中外合作",
    "保底",
    "稳",
    "冲",
    "风险",
    "太冲",
    "少点",
    "多点",
    "有没有",
    "多少",
    "删",
    "移出",
    "替换",
    "调整",
)

_CURRENT_PLAN_MUTATION_MARKERS = (
    "删",
    "删除",
    "移出",
    "去掉",
    "剔除",
    "替换",
    "换成",
    "换掉",
    "调整",
    "重排",
    "重新排",
    "排序",
    "排下",
    "排一下",
    "排一排",
    "移动",
    "挪到",
    "锁定",
    "固定",
    "保护不动",
    "不要动",
    "别动",
)

_CURRENT_PLAN_ADD_MUTATION_MARKERS = (
    "加进来",
    "加进去",
    "放进来",
    "放进去",
    "加到方案",
    "加进方案",
    "加入方案",
    "放到方案",
    "放进方案",
    "纳入方案",
)

_UNSUPPORTED_PIN_LOCK_ACTION_MARKERS = (
    "锁定",
    "固定",
    "保护不动",
    "位置不要动",
    "不要动",
    "别动",
)


def content_has_current_plan_mutation_anchor(content: str | None) -> bool:
    """Return true when the utterance carries a current-plan mutation verb.

    This is only a framework guard before runtime intent pending creation. It
    does not decide the action scope or create a proposal; plan DSL/compiler
    still owns that work.
    """

    compact = _compact_text(content)
    return bool(compact and any(marker in compact for marker in _CURRENT_PLAN_MUTATION_MARKERS))


def content_has_unsupported_pin_lock_action_anchor(content: str | None) -> bool:
    compact = _compact_text(content)
    return bool(compact and any(marker in compact for marker in _UNSUPPORTED_PIN_LOCK_ACTION_MARKERS))


_INTENT_COMMIT_MARKERS = (
    "加入",
    "加到",
    "加进",
    "加意向",
    "记到",
    "记下",
    "记录",
    "作为偏好",
    "作为要求",
    "后续参考",
    "以后推荐",
    "后面推荐",
    "优先",
    "只保留",
    "仅保留",
    "只看",
    "必须有",
    "至少保留",
    "排除",
    "不要",
)

_READONLY_SCHOOL_OR_CANDIDATE_QUERY_MARKERS = (
    "有哪些",
    "有哪几个",
    "哪几个",
    "哪些",
    "适合我",
    "适不适合我",
    "值不值得",
    "推荐哪些",
    "推荐几个",
)

_SCHOOL_OR_CANDIDATE_SUBJECT_MARKERS = (
    "大学",
    "学校",
    "院校",
    "候选",
    "机会",
    "招生",
)


def content_has_readonly_school_or_candidate_query_anchor(content: str | None) -> bool:
    """Return true for school/candidate discovery questions, not preference writes."""

    compact = _compact_text(content)
    if not compact:
        return False
    if any(marker in compact for marker in _INTENT_COMMIT_MARKERS):
        return False
    return (
        any(marker in compact for marker in _READONLY_SCHOOL_OR_CANDIDATE_QUERY_MARKERS)
        and any(marker in compact for marker in _SCHOOL_OR_CANDIDATE_SUBJECT_MARKERS)
    )


def content_has_future_reference_anchor(content: str | None) -> bool:
    compact = _compact_text(content)
    return bool(compact and any(marker in compact for marker in _FUTURE_REFERENCE_MARKERS))


_FUTURE_REFERENCE_MARKERS = (
    "以后",
    "后续",
    "以后推荐",
    "后面推荐",
    "后续参考",
    "作为偏好",
    "作为要求",
    "记到",
    "记下",
    "记录",
    "加入意向",
    "加到意向",
    "加进意向",
    "加意向",
    "加入偏好",
    "加到偏好",
    "加进偏好",
    "加偏好",
)

_PLAN_GENERATION_MARKERS = (
    "生成方案",
    "生成一版",
    "帮我生成",
    "出方案",
    "出一版",
    "做一版",
    "做方案",
    "规划一版",
    "整理一版",
)

_SPECIAL_PATH_REVIEW_MARKERS = (
    "强基",
    "普通批",
    "提前批",
    "综评",
    "专项",
)

_REVIEW_BOUNDARY_MARKERS = (
    "方案合理",
    "方案合不合理",
    "合理不",
    "合理吗",
    "这版合理",
    "搭配",
    "配合",
    "怎么配",
    "是否合理",
    "有没有问题",
    "风险",
)


_CAREER_DIRECTION_MARKERS_BY_SLOT = {
    CAREER_SYSTEM_PUBLIC_SERVICE: (
        "体制内",
        "考公",
        "考编",
        "公务员",
        "事业单位",
        "编制",
        "进体制",
    ),
    CAREER_STABLE_EMPLOYMENT: (
        "稳定就业",
        "就业稳定",
        "工作稳定",
        "岗位稳定",
        "求稳",
        "抗风险",
    ),
    CAREER_FURTHER_STUDY: (
        "读研",
        "考研",
        "深造",
        "升学",
        "保研",
    ),
    CAREER_MARKET_EMPLOYMENT: (
        "市场化就业",
        "企业就业",
        "大厂",
        "互联网",
        "产业",
        "实习",
    ),
}


def _current_plan_career_focus_labels(compact: str) -> list[str]:
    labels: list[str] = []
    for slot, markers in _CAREER_DIRECTION_MARKERS_BY_SLOT.items():
        if any(marker in compact for marker in markers):
            label = to_career_label(slot)
            if label not in labels:
                labels.append(label)
    return labels


def _append_needs_plan_first_target_issues(
    target_issues: list[str],
    compact: str,
    *,
    has_current_plan_add: bool = False,
    has_current_plan_mutation: bool = False,
    has_current_plan_query: bool = False,
    recent_intent_summary: str = "",
) -> None:
    def append(issue: str) -> None:
        if issue and issue not in target_issues:
            target_issues.append(issue)

    career_focus_labels = _current_plan_career_focus_labels(compact)
    has_intent_reference = bool(recent_intent_summary) and any(
        marker in compact
        for marker in (
            "这些要求",
            "这些条件",
            "这个要求",
            "这个条件",
            "这条要求",
            "这条条件",
            "这些偏好",
            "这些想法",
            "这个偏好",
            "这个想法",
            "和这些",
            "跟这些",
            "冲突",
            "不符合",
        )
    )
    if has_intent_reference:
        append("intent_conflict_check_without_referent")
    if career_focus_labels:
        append("career_direction_support")
    if any(marker in compact for marker in ("民办", "公办")):
        append("college_type")
    if "中外合作" in compact:
        append("program_type")
    if not career_focus_labels and not has_intent_reference and any(marker in compact for marker in ("保底", "稳", "冲", "风险", "太冲")):
        append("tier_or_risk")
    if has_current_plan_add:
        append("plan_add_without_referent")
    elif has_current_plan_mutation:
        append("plan_mutation_without_referent")
    elif has_current_plan_query:
        append("current_plan_query_without_referent")


def _needs_plan_first_focus_label(compact: str, target_issues: list[str], *, recent_intent_summary: str = "") -> str:
    if "intent_conflict_check_without_referent" in target_issues:
        summary = str(recent_intent_summary or "").strip()
        if summary:
            return f"已采纳要求（{summary}）的方案冲突检查"
        return "已采纳要求的方案冲突检查"
    if "career_direction_support" in target_issues:
        labels = _current_plan_career_focus_labels(compact)
        if labels:
            return f"{'、'.join(labels[:3])}的方案承接"
        return "职业发展方向的方案承接"
    if "college_type" in target_issues:
        return "公办/民办这类要求"
    if "program_type" in target_issues:
        return "中外合作这类要求"
    if "tier_or_risk" in target_issues:
        return "冲稳保或风险这类要求"
    if "plan_add_without_referent" in target_issues:
        return "加入当前方案的候选志愿"
    return "这类方案范围要求"


def compile_no_plan_atomic_action_boundary_source(
    content: str | None,
    *,
    action_family: str,
) -> NeedsPlanFirstResolution:
    if str(action_family or "").strip() != "add_units":
        return NeedsPlanFirstResolution()
    primary_reply, display_payload, reply_plan = _compile_needs_plan_first_reply(
        content,
        target_issues=["plan_add_without_referent"],
    )
    return NeedsPlanFirstResolution(
        side_effect="needs_plan_first",
        reference_resolution="no_referent",
        requires_model_decision=False,
        target_issues=["plan_add_without_referent"],
        primary_reply=primary_reply,
        display_payload=display_payload,
        reply_plan=reply_plan,
        blocking_reasons=["missing_formal_plan"],
    )


def _compile_needs_plan_first_reply(
    content: str | None,
    *,
    target_issues: list[str],
    recent_intent_summary: str = "",
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    compact = _compact_text(content)
    focus = _needs_plan_first_focus_label(
        compact,
        target_issues,
        recent_intent_summary=recent_intent_summary,
    )
    if "intent_conflict_check_without_referent" in target_issues:
        focus_sentence = f"你这轮关注的是{focus}；需要先有正式方案，才能逐项判断哪些志愿冲突或不符合。"
    elif "career_direction_support" in target_issues:
        focus_sentence = f"你这轮关注的是{focus}；需要先有正式方案，才能评估方案内是否承接。"
    elif "current_plan_query_without_referent" in target_issues:
        focus_sentence = f"你这轮关注的是{focus}；需要先有正式方案，才能检查方案内具体情况。"
    else:
        focus_sentence = ""
    request_text = re.sub(r"\s+", " ", str(content or "").strip()).strip(" ，,。；;")
    request_sentence = f"这轮诉求是：{request_text}。" if request_text else ""
    reply = (
        "当前还没有生成正式方案，所以没法判断或调整“刚才/当前方案”里的具体志愿。"
        f"{request_sentence}"
        f"{focus_sentence}"
        f"这轮不会把{focus}写成新的报考要求，也不会改动当前方案。"
        "也就是说，这轮不会改动方案。"
        "你可以先让我生成一版方案；有了正式方案后，我再按这条要求检查或调整。"
    )
    display_payload = {
        "presentation": "readonly_boundary",
        "reason": "needs_plan_first",
        "focusLabel": focus,
        "targetIssues": list(target_issues),
    }
    if recent_intent_summary and "intent_conflict_check_without_referent" in target_issues:
        display_payload["recentIntentSummary"] = recent_intent_summary
    reply_plan = {
        "mode": ["needs_plan_first"],
        "focus": list(target_issues) or ["current_plan_no_referent"],
    }
    return reply, display_payload, reply_plan


def _planning_summary_has_current_plan(planning_summary: Any) -> bool:
    if not planning_summary:
        return False
    if isinstance(planning_summary, dict):
        ordered_total = _as_int(
            planning_summary.get("ordered_total")
            or planning_summary.get("orderedTotal")
            or planning_summary.get("ordered_total_fallback")
        )
        working_total = _as_int(planning_summary.get("working_total") or planning_summary.get("workingTotal"))
        target_total = _as_int(planning_summary.get("ordered_target_total") or planning_summary.get("orderedTargetTotal"))
        phase = str(planning_summary.get("phase") or "").strip()
        version = _as_int(planning_summary.get("version"))
        return (
            ordered_total > 0
            or working_total > 0
            or target_total > 0
            or (version > 0 and phase in {"ordered", "reviewed", "formal", "generated"})
        )
    phase = str(getattr(planning_summary, "phase", "") or "").strip()
    version = _as_int(getattr(planning_summary, "version", 0))
    return (
        _as_int(getattr(planning_summary, "ordered_total", 0)) > 0
        or _as_int(getattr(planning_summary, "working_total", 0)) > 0
        or _as_int(getattr(planning_summary, "ordered_target_total", 0)) > 0
        or (version > 0 and phase in {"ordered", "reviewed", "formal", "generated"})
    )


def full_agent_intent_pending_requires_turn_decision(planning_summary: Any) -> bool:
    """Return True when full-agent intent pending needs framework arbitration."""

    return _planning_summary_has_current_plan(planning_summary)


def resolve_needs_plan_first_guard(
    content: str | None,
    *,
    planning_summary: Any = None,
    recent_intent_summary: str = "",
) -> NeedsPlanFirstResolution:
    compact = _compact_text(content)
    if not compact or planning_summary is None or _planning_summary_has_current_plan(planning_summary):
        return NeedsPlanFirstResolution()
    if any(marker in compact for marker in _PLAN_GENERATION_MARKERS):
        return NeedsPlanFirstResolution()
    if any(marker in compact for marker in _FUTURE_REFERENCE_MARKERS) and not any(
        marker in compact for marker in _CURRENT_PLAN_REFERENCE_MARKERS
    ):
        return NeedsPlanFirstResolution()
    has_current_plan_reference = any(marker in compact for marker in _CURRENT_PLAN_REFERENCE_MARKERS)
    has_plan_scope = any(marker in compact for marker in _CURRENT_PLAN_SCOPE_MARKERS)
    has_current_plan_add = any(marker in compact for marker in _CURRENT_PLAN_ADD_MUTATION_MARKERS)
    has_current_plan_mutation = (
        any(marker in compact for marker in _CURRENT_PLAN_MUTATION_MARKERS)
        or has_current_plan_add
    )
    if not ((has_current_plan_reference and has_plan_scope) or has_current_plan_mutation):
        return NeedsPlanFirstResolution()
    target_issues: list[str] = []
    _append_needs_plan_first_target_issues(
        target_issues,
        compact,
        has_current_plan_add=has_current_plan_add,
        has_current_plan_mutation=has_current_plan_mutation,
        recent_intent_summary=recent_intent_summary,
    )
    primary_reply, display_payload, reply_plan = _compile_needs_plan_first_reply(
        content,
        target_issues=target_issues,
        recent_intent_summary=recent_intent_summary,
    )
    return NeedsPlanFirstResolution(
        side_effect="needs_plan_first",
        reference_resolution="no_referent",
        requires_model_decision=False,
        target_issues=target_issues,
        primary_reply=primary_reply,
        display_payload=display_payload,
        reply_plan=reply_plan,
        blocking_reasons=["missing_formal_plan"],
    )


def resolve_no_formal_plan_review_boundary(
    content: str | None,
    *,
    planning_summary: Any = None,
) -> NoFormalPlanReviewBoundaryResolution:
    compact = _compact_text(content)
    if not compact or planning_summary is None or _planning_summary_has_current_plan(planning_summary):
        return NoFormalPlanReviewBoundaryResolution()
    if any(marker in compact for marker in _PLAN_GENERATION_MARKERS):
        return NoFormalPlanReviewBoundaryResolution()
    if not any(marker in compact for marker in _SPECIAL_PATH_REVIEW_MARKERS):
        return NoFormalPlanReviewBoundaryResolution()
    if not (
        any(marker in compact for marker in _CURRENT_PLAN_REFERENCE_MARKERS)
        or any(marker in compact for marker in _REVIEW_BOUNDARY_MARKERS)
    ):
        return NoFormalPlanReviewBoundaryResolution()

    reply_focus: list[str] = []
    if "强基" in compact:
        reply_focus.append("strongbase")
    if "普通批" in compact:
        reply_focus.append("regular_batch")
    if "提前批" in compact:
        reply_focus.append("early_batch")
    if "综评" in compact:
        reply_focus.append("comprehensive_evaluation")
    if "专项" in compact:
        reply_focus.append("special_program")
    if not reply_focus:
        reply_focus.append("special_path")

    return NoFormalPlanReviewBoundaryResolution(
        side_effect="readonly",
        reference_resolution="special_path_without_formal_plan",
        requires_model_decision=False,
        reply_focus=reply_focus,
        blocking_reasons=["missing_formal_plan"],
    )


def resolve_no_formal_plan_current_plan_guard(
    content: str | None,
    *,
    planning_summary: Any = None,
    recent_intent_summary: str = "",
) -> NeedsPlanFirstResolution:
    """Block explicit current-plan review/analyze/mutation when no formal plan exists."""

    compact = _compact_text(content)
    if not compact or planning_summary is None or _planning_summary_has_current_plan(planning_summary):
        return NeedsPlanFirstResolution()

    if any(marker in compact for marker in _FUTURE_REFERENCE_MARKERS):
        return NeedsPlanFirstResolution()

    has_current_plan_reference = any(marker in compact for marker in _CURRENT_PLAN_REFERENCE_MARKERS)
    if not has_current_plan_reference:
        return NeedsPlanFirstResolution()

    has_review_or_analysis = any(marker in compact for marker in _REVIEW_BOUNDARY_MARKERS) or any(
        marker in compact for marker in ("分析", "审查", "看看", "检查", "优化", "调整")
    )
    has_mutation = any(marker in compact for marker in _CURRENT_PLAN_MUTATION_MARKERS)
    has_plan_scope = any(marker in compact for marker in _CURRENT_PLAN_SCOPE_MARKERS)
    if not (has_review_or_analysis or has_mutation or has_plan_scope):
        return NeedsPlanFirstResolution()

    target_issues: list[str] = []
    _append_needs_plan_first_target_issues(
        target_issues,
        compact,
        has_current_plan_mutation=has_mutation,
        has_current_plan_query=has_review_or_analysis or has_current_plan_reference or has_plan_scope,
        recent_intent_summary=recent_intent_summary,
    )
    primary_reply, display_payload, reply_plan = _compile_needs_plan_first_reply(
        content,
        target_issues=target_issues,
        recent_intent_summary=recent_intent_summary,
    )

    return NeedsPlanFirstResolution(
        side_effect="needs_plan_first",
        reference_resolution="no_referent",
        requires_model_decision=False,
        target_issues=target_issues,
        primary_reply=primary_reply,
        display_payload=display_payload,
        reply_plan=reply_plan,
        blocking_reasons=["missing_formal_plan"],
    )


def resolve_pending_turn_action(
    content: str | None,
    *,
    pending_state: dict[str, Any] | None,
) -> PendingTurnResolution:
    if not isinstance(pending_state, dict) or str(pending_state.get("status") or "active").strip() != "active":
        return PendingTurnResolution(
            requires_model_decision=False,
            blocking_reasons=["missing_active_pending"],
        )
    pending_kind = str(pending_state.get("kind") or "").strip()
    pending_type = "plan" if pending_kind == "plan_mutation" else "intent" if pending_kind == "intent_change" else ""
    compact = _compact_text(content)
    if not compact:
        return PendingTurnResolution(
            pending_type=pending_type,
            blocking_reasons=["empty_pending_turn"],
        )
    if pending_turn_looks_reject_pending(content):
        return PendingTurnResolution(
            action="reject_pending",
            side_effect="cancel_existing_pending",
            pending_type=pending_type,
            requires_model_decision=False,
        )
    if pending_turn_looks_direct_confirmation(content, pending_kind, pending_state=pending_state):
        return PendingTurnResolution(
            action="confirm_pending",
            side_effect="apply_existing_pending",
            pending_type=pending_type,
            requires_model_decision=False,
        )
    return PendingTurnResolution(
        pending_type=pending_type,
        requires_model_decision=True,
    )


def compile_runtime_pending_turn_decision_source(
    content: str | None,
    *,
    pending_state: dict[str, Any] | None,
    turn_decision: Any | None,
) -> PendingTurnResolution:
    """Compile structured TurnDecision output for an active pending turn.

    This consumes only the TurnDecision contract and pending state.  Short
    confirmation/cancel protocols stay in resolve_pending_turn_action(); this
    compiler owns business semantics such as pending impact, apply-then-query,
    apply-then-generate and conflict guards.
    """

    if not isinstance(pending_state, dict) or str(pending_state.get("status") or "").strip() != "active":
        return PendingTurnResolution(
            requires_model_decision=False,
            blocking_reasons=["missing_active_pending"],
        )
    pending_kind = str(pending_state.get("kind") or "").strip()
    pending_type = "plan" if pending_kind == "plan_mutation" else "intent" if pending_kind == "intent_change" else ""
    if turn_decision is None:
        return PendingTurnResolution(
            pending_type=pending_type,
            blocking_reasons=["missing_turn_decision"],
        )

    confidence = _decision_float_field(turn_decision, "confidence")
    task_layer = _decision_text_field(turn_decision, "taskLayer")
    side_effect = _decision_text_field(turn_decision, "sideEffect")
    scope_anchor = _decision_text_field(turn_decision, "scopeAnchor")
    scenario = _decision_text_field(turn_decision, "scenario")
    target_issues = _as_text_list(_model_or_dict(turn_decision).get("targetIssue") or getattr(turn_decision, "targetIssue", []))

    if confidence < 0.8:
        return PendingTurnResolution(
            pending_type=pending_type,
            blocking_reasons=["low_turn_decision_confidence"],
        )

    if side_effect == "readonly_while_pending" and scenario == "pending_impact_query":
        if task_layer not in {"pending", "plan", "mixed", "intent"}:
            return PendingTurnResolution(
                pending_type=pending_type,
                blocking_reasons=["unsupported_pending_impact_task_layer"],
            )
        if scope_anchor not in {"pending_reference", "future_reference", "current_plan"}:
            return PendingTurnResolution(
                pending_type=pending_type,
                blocking_reasons=["unsupported_pending_impact_scope_anchor"],
            )
        return PendingTurnResolution(
            action="ask_pending_impact",
            side_effect="readonly_while_pending",
            pending_type=pending_type,
            requires_model_decision=False,
        )

    if side_effect == "apply_pending_then_readonly" and scenario == "apply_pending_then_readonly_query":
        if task_layer not in {"pending", "plan", "mixed"}:
            return PendingTurnResolution(
                pending_type=pending_type,
                blocking_reasons=["unsupported_apply_pending_readonly_task_layer"],
            )
        return PendingTurnResolution(
            action="apply_pending_then_readonly",
            side_effect="apply_pending_then_readonly",
            pending_type=pending_type,
            requires_model_decision=False,
            post_apply_evidence_plan=compile_post_apply_readonly_evidence_plan(
                content,
                pending_state=pending_state,
                target_issues=target_issues,
            ),
        )

    if side_effect == "apply_pending_then_new_request" and scenario == "apply_intent_then_generate_plan":
        if pending_kind != "intent_change":
            return PendingTurnResolution(
                pending_type=pending_type,
                blocking_reasons=["apply_then_new_request_requires_intent_pending"],
            )
        if scope_anchor not in {"future_reference", "pending_reference"}:
            return PendingTurnResolution(
                pending_type=pending_type,
                blocking_reasons=["unsupported_apply_then_new_request_scope_anchor"],
            )
        return PendingTurnResolution(
            action="apply_pending_then_new_request",
            side_effect="apply_pending_then_new_request",
            pending_type=pending_type,
            requires_model_decision=False,
        )

    if side_effect == "conflict_with_existing_pending" and scenario == "pending_conflict_new_mutation":
        return PendingTurnResolution(
            action="conflict_with_existing_pending",
            side_effect="conflict_with_existing_pending",
            pending_type=pending_type,
            requires_model_decision=False,
        )

    return PendingTurnResolution(
        pending_type=pending_type,
        requires_model_decision=True,
        blocking_reasons=["unsupported_pending_turn_decision"],
    )


def _parse_plan_confirmation_payload(value: Any) -> tuple[dict[str, Any], str, list[str]]:
    if isinstance(value, dict):
        return dict(value), json.dumps(value, ensure_ascii=False), []
    if value in (None, "", [], {}):
        return {}, "", ["plan_candidate_requires_plan_payload"]
    return {}, str(value), ["plan_payload_must_be_object"]


def _plan_payload_action_family(payload: dict[str, Any]) -> str:
    return str(payload.get("action_family") or payload.get("actionFamily") or "").strip()


def ensure_structured_plan_payload(
    payload: dict[str, Any] | None,
    *,
    action_family: str = "",
) -> dict[str, Any]:
    """Normalize a Release 4.0 plan pending payload.

    New pending execution is driven by ``action_family`` + ``atomic_actions``.
    This helper keeps transitional producers from storing opaque nested
    payload fields while preserving concrete structured fields already
    resolved by preview.
    """
    if not isinstance(payload, dict):
        return {}
    normalized = dict(payload)
    if "planPayload" in normalized or "plan_payload" in normalized:
        return {}
    family = str(action_family or _plan_payload_action_family(normalized) or "").strip()
    if family:
        normalized["action_family"] = family
    actions = normalized.get("atomic_actions") or normalized.get("atomicActions")
    if isinstance(actions, list) and any(isinstance(item, dict) for item in actions):
        normalized["atomic_actions"] = [dict(item) for item in actions if isinstance(item, dict)]
        normalized.pop("atomicActions", None)
        return normalized
    if not family:
        return normalized
    atomic: dict[str, Any] = {"action_type": family}
    for key in (
        "unit_ids",
        "unitIds",
        "volunteer_ids",
        "volunteerIds",
        "target_position",
        "targetPosition",
        "sort_field",
        "sortField",
        "filters",
        "review_issue_target",
        "reviewIssueTarget",
    ):
        value = normalized.get(key)
        if value not in (None, "", [], {}):
            atomic[key] = value
    if "reason" not in atomic and str(normalized.get("user_goal") or normalized.get("userGoal") or "").strip():
        atomic["reason"] = str(normalized.get("user_goal") or normalized.get("userGoal") or "").strip()
    normalized["atomic_actions"] = [atomic]
    return normalized


def is_structured_plan_payload(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    family = _plan_payload_action_family(payload)
    actions = payload.get("atomic_actions") or payload.get("atomicActions")
    return bool(family and isinstance(actions, list) and any(isinstance(item, dict) for item in actions))


def _plan_payload_target_view(payload: dict[str, Any]) -> str | None:
    target_view = str(payload.get("target_view") or payload.get("targetView") or "").strip()
    return target_view or None


def _plan_confirmation_target_view(action_family: str, plan_payload: dict[str, Any]) -> str | None:
    target_view = _plan_payload_target_view(plan_payload)
    if target_view:
        return target_view
    if action_family in PENDING_PLAN_ACTION_FAMILIES:
        return "ordered"
    return None


def resolve_plan_confirmation_candidate(
    confirmation_candidate: dict[str, Any] | None,
) -> PlanConfirmationCandidateResolution:
    if not isinstance(confirmation_candidate, dict):
        return PlanConfirmationCandidateResolution(
            blocking_reasons=["missing_plan_confirmation_candidate"],
        )

    reasons: list[str] = []
    plan_payload, plan_payload_text, payload_reasons = _parse_plan_confirmation_payload(
        confirmation_candidate.get("plan_payload")
    )
    for reason in payload_reasons:
        _append_reason(reasons, reason)

    candidate_action_family = str(
        confirmation_candidate.get("action_family")
        or confirmation_candidate.get("actionFamily")
        or ""
    ).strip()
    payload_action_family = _plan_payload_action_family(plan_payload)
    action_family = candidate_action_family or payload_action_family
    if not action_family:
        _append_reason(reasons, "plan_pending_requires_action_family")
    elif action_family == "apply_fix_proposal":
        _append_reason(reasons, "plan_sink_rejects_fix_proposal_candidate")
    elif action_family not in PENDING_PLAN_ACTION_FAMILIES:
        _append_reason(reasons, "unsupported_plan_action_family")

    if candidate_action_family and payload_action_family and candidate_action_family != payload_action_family:
        _append_reason(reasons, "plan_candidate_action_family_mismatch")

    if plan_payload:
        stage = str(plan_payload.get("stage") or "").strip()
        if stage != "apply":
            _append_reason(reasons, "plan_candidate_requires_apply_stage")
        requires_confirmation = (
            plan_payload.get("requires_confirmation")
            if "requires_confirmation" in plan_payload
            else plan_payload.get("requiresConfirmation")
        )
        if requires_confirmation is True:
            _append_reason(reasons, "plan_candidate_apply_payload_must_not_require_confirmation")
        missing_inputs = plan_payload.get("missing_inputs") or plan_payload.get("missingInputs")
        if missing_inputs:
            _append_reason(reasons, "plan_candidate_has_missing_inputs")

    source_version_guard = _as_int(
        confirmation_candidate.get("source_backend_version")
        or confirmation_candidate.get("sourceBackendVersion")
        or confirmation_candidate.get("planning_version")
        or confirmation_candidate.get("planningVersion")
        or plan_payload.get("source_backend_version")
        or plan_payload.get("sourceBackendVersion")
        or plan_payload.get("planning_version")
        or plan_payload.get("planningVersion")
    )
    intent_update = confirmation_candidate.get("intent_update") or confirmation_candidate.get("intentUpdate")
    return PlanConfirmationCandidateResolution(
        allowed=not reasons,
        action_family=action_family,
        plan_payload=plan_payload,
        plan_payload_text=plan_payload_text,
        source_version_guard=source_version_guard,
        target_view=_plan_confirmation_target_view(action_family, plan_payload),
        intent_update=intent_update if isinstance(intent_update, dict) else {},
        blocking_reasons=reasons,
    )


def compile_intent_select_proposal(
    *,
    session_id: str,
    selected_data: dict[str, Any],
    merged: dict[str, Any],
    intent_mode: str,
    batch: str,
    constraint_intent_type: str,
    summary: str,
) -> dict[str, Any]:
    compiled_id = f"intent-select:{session_id}:{uuid.uuid4()}"
    return {
        "compiledProposalId": compiled_id,
        "sideEffect": "intent_pending",
        "outputType": "intent_change",
        "pendingType": "intent_change",
        "requiresConfirmation": True,
        "executionPayload": {
            "kind": "pending_intent_change",
            "actionFamilies": ["apply_selected_intents"],
            "requiresConfirmation": True,
            "targetView": None,
        },
        "intentPayload": {
            "selectedData": selected_data,
            "merged": merged,
            "intentMode": intent_mode,
            "constraintIntentType": constraint_intent_type,
            "batch": batch,
            "summary": summary,
            "scopeAnchor": "future_reference",
        },
        "displayPayload": {
            "presentation": "confirmation_card",
            "pendingCardType": "pendingConfirmationCard",
            "summary": summary,
        },
        "replyPlan": {
            "mode": ["confirmable_intent"],
            "focus": ["intent_select"],
        },
        "blockingReasons": [],
    }


def compile_intent_preview_proposal(
    *,
    session_id: str,
    selected_data: dict[str, Any],
    merged: dict[str, Any],
    intent_mode: str,
    batch: str,
    constraint_intent_type: str,
    summary: str,
) -> dict[str, Any]:
    compiled_id = f"intent-preview:{session_id}:{uuid.uuid4()}"
    return {
        "compiledProposalId": compiled_id,
        "sideEffect": "intent_pending",
        "outputType": "intent_change",
        "pendingType": "intent_change",
        "requiresConfirmation": True,
        "executionPayload": {
            "kind": "pending_intent_change",
            "actionFamilies": ["apply_selected_intents"],
            "requiresConfirmation": True,
            "targetView": None,
        },
        "intentPayload": {
            "selectedData": selected_data,
            "merged": merged,
            "intentMode": intent_mode,
            "constraintIntentType": constraint_intent_type,
            "batch": batch,
            "summary": summary,
            "scopeAnchor": "future_reference",
        },
        "displayPayload": {
            "presentation": "confirmation_card",
            "pendingCardType": "pendingConfirmationCard",
            "summary": summary,
        },
        "replyPlan": {
            "mode": ["confirmable_intent"],
            "focus": ["intent_preview"],
        },
        "blockingReasons": [],
    }

def _intent_payload_has_any_value(payload: dict[str, Any] | None, paths: list[tuple[str, str]]) -> bool:
    if not isinstance(payload, dict):
        return False
    for group_key, field_key in paths:
        group = payload.get(group_key)
        if isinstance(group, dict) and _as_text_list(group.get(field_key)):
            return True
    return False


def _intent_payload_has_tuition_budget_value(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    budget = payload.get("tuition_budget") or payload.get("tuitionBudget")
    if not isinstance(budget, dict):
        return False
    for key in ("min_tuition_per_year", "minTuitionPerYear", "max_tuition_per_year", "maxTuitionPerYear"):
        values = budget.get(key)
        raw_values = values if isinstance(values, list) else [values] if values is not None else []
        for value in raw_values:
            try:
                amount = int(value)
            except (TypeError, ValueError):
                continue
            if amount > 0:
                return True
    return False


def _intent_payload_has_positive_value(payload: dict[str, Any] | None) -> bool:
    return _intent_payload_has_any_value(
        payload,
        [
            ("major_intents", "level3"),
            ("major_intents", "level2"),
            ("major_intents", "level1"),
            ("school_intents", "colleges"),
            ("city_intents", "province"),
            ("city_intents", "city"),
            ("city_intents", "area"),
            ("career_intents", "positive"),
        ],
    ) or _intent_payload_has_tuition_budget_value(payload)


def intent_payload_has_positive_value(payload: dict[str, Any] | None) -> bool:
    return _intent_payload_has_positive_value(payload)


def _intent_payload_has_negative_value(payload: dict[str, Any] | None) -> bool:
    return _intent_payload_has_any_value(
        payload,
        [
            ("major_intents", "negative_level3"),
            ("major_intents", "negative_level2"),
            ("major_intents", "negative_level1"),
            ("major_intents", "negative"),
            ("school_intents", "negative_colleges"),
            ("city_intents", "negative_province"),
            ("city_intents", "negative_city"),
            ("city_intents", "negative_area"),
            ("career_intents", "negative"),
            ("physical_constraints", "special_limits"),
            ("physicalConstraints", "specialLimits"),
        ],
    )


def intent_payload_has_negative_value(payload: dict[str, Any] | None) -> bool:
    return _intent_payload_has_negative_value(payload)


def intent_payload_has_required_constraint_scope(
    merged: dict[str, Any] | None,
    *,
    constraint_intent_type: str,
) -> bool:
    normalized = str(constraint_intent_type or "default").strip()
    if normalized in {"only_keep", "must_have"}:
        return intent_payload_has_positive_value(merged)
    return intent_payload_has_positive_value(merged) or intent_payload_has_negative_value(merged)


def normalize_intent_constraint_type_for_payload(
    value: str | None,
    merged: dict[str, Any] | None,
    *,
    intent_mode: str,
) -> str:
    raw = str(value or "default").strip() or "default"
    if intent_mode != "constraint":
        return "default"
    if raw not in {"only_keep", "must_have", "exclude_hard", "default"}:
        raw = "default"
    if raw in {"only_keep", "must_have"} and not _intent_payload_has_positive_value(merged):
        return "default"
    return raw


def resolve_intent_proposal_input(
    *,
    source: str,
    selected_values: list[dict[str, Any]],
    merged: dict[str, Any] | None,
    intent_mode: str,
    raw_constraint_intent_type: str | None,
) -> IntentProposalInputResolution:
    normalized_source = str(source or "intent").strip() or "intent"
    selected_reason = (
        "intent_preview_requires_selected_values"
        if normalized_source == "intent_preview"
        else "intent_select_requires_selected_values"
    )
    blocking_reasons: list[str] = []
    clean_selected = [item for item in selected_values if isinstance(item, dict) and item]
    if not clean_selected:
        blocking_reasons.append(selected_reason)
    normalized_mode = str(intent_mode or "preference").strip()
    if normalized_mode not in {"preference", "constraint"}:
        normalized_mode = "preference"
    if not isinstance(merged, dict) or not merged:
        if selected_reason not in blocking_reasons:
            blocking_reasons.append(selected_reason)
    raw_constraint_type = str(raw_constraint_intent_type or "default").strip() or "default"
    constraint_type = normalize_intent_constraint_type_for_payload(
        raw_constraint_intent_type,
        merged,
        intent_mode=normalized_mode,
    )
    if normalized_mode == "constraint":
        has_positive = _intent_payload_has_positive_value(merged)
        has_negative = _intent_payload_has_negative_value(merged)
        if raw_constraint_type in {"only_keep", "must_have"}:
            if not has_positive:
                blocking_reasons.append("constraint_intent_requires_scope")
        elif not (has_positive or has_negative):
            blocking_reasons.append("constraint_intent_requires_scope")
        if constraint_type in {"only_keep", "must_have"}:
            normalized_mode = "constraint"
    return IntentProposalInputResolution(
        allowed=not blocking_reasons,
        intent_mode=normalized_mode,
        constraint_intent_type=constraint_type,
        blocking_reasons=blocking_reasons,
    )


def resolve_intent_select_input(
    *,
    selected_values: list[dict[str, Any]],
    merged: dict[str, Any] | None,
    intent_mode: str,
    raw_constraint_intent_type: str | None,
) -> IntentProposalInputResolution:
    return resolve_intent_proposal_input(
        source="intent_select",
        selected_values=selected_values,
        merged=merged,
        intent_mode=intent_mode,
        raw_constraint_intent_type=raw_constraint_intent_type,
    )


def resolve_intent_preview_input(
    *,
    selected_values: list[dict[str, Any]],
    merged: dict[str, Any] | None,
    intent_mode: str,
    raw_constraint_intent_type: str | None,
) -> IntentProposalInputResolution:
    return resolve_intent_proposal_input(
        source="intent_preview",
        selected_values=selected_values,
        merged=merged,
        intent_mode=intent_mode,
        raw_constraint_intent_type=raw_constraint_intent_type,
    )


def compile_plan_confirmation_proposal(
    *,
    session_id: str,
    confirmation_candidate: dict[str, Any],
    source: str,
    summary: str,
) -> dict[str, Any]:
    resolution = resolve_plan_confirmation_candidate(confirmation_candidate)
    action_family = resolution.action_family
    compiled_id = f"plan-candidate:{session_id}:{uuid.uuid4()}"
    workspace_refresh_targets = [resolution.target_view] if resolution.target_view else []
    return {
        "compiledProposalId": compiled_id,
        "sideEffect": "plan_pending",
        "outputType": "plan_mutation",
        "pendingType": "plan_mutation",
        "requiresConfirmation": True,
        "executionPayload": {
            "kind": "pending_plan_mutation",
            "actionFamilies": [action_family] if action_family else [],
            "actionFamily": action_family,
            "targetView": resolution.target_view,
            "requiresConfirmation": True,
        },
        "workspaceRefreshTargets": workspace_refresh_targets,
        "intentPayload": resolution.intent_update,
        "displayPayload": {
            "presentation": "confirmation_card",
            "pendingCardType": "pendingConfirmationCard",
            "summary": summary,
        },
        "proposalCandidates": [
            {
                "id": compiled_id,
                "type": "plan_confirmation_candidate",
                "source": source,
                "actionFamily": action_family,
                "plan_payload": resolution.plan_payload,
                "sourceVersionGuard": resolution.source_version_guard,
            }
        ],
        "replyPlan": {
            "mode": ["confirmable_plan_mutation"],
            "focus": ["plan_confirmation"],
        },
        "blockingReasons": list(resolution.blocking_reasons),
    }


def compile_runtime_plan_confirmation_source(
    *,
    session_id: str,
    confirmation_candidate: dict[str, Any] | None,
    source: str,
    summary: str,
) -> RuntimePlanCompiledSource:
    resolution = resolve_plan_confirmation_candidate(confirmation_candidate)
    if not resolution.allowed:
        return RuntimePlanCompiledSource(
            confirmation_candidate=confirmation_candidate if isinstance(confirmation_candidate, dict) else None,
            resolution=resolution,
            source_version_guard=resolution.source_version_guard,
            blocking_reasons=list(resolution.blocking_reasons),
        )
    compiled = compile_plan_confirmation_proposal(
        session_id=session_id,
        confirmation_candidate=confirmation_candidate or {},
        source=source,
        summary=summary,
    )
    return RuntimePlanCompiledSource(
        confirmation_candidate=confirmation_candidate,
        compiled=compiled,
        resolution=resolution,
        source_version_guard=resolution.source_version_guard,
        blocking_reasons=list(resolution.blocking_reasons),
    )


def compile_apply_then_generate_plan_source(
    *,
    session_id: str,
    user_prompt: str,
    pending_state: dict[str, Any] | None,
    source_version_guard: int = 0,
) -> ApplyThenGeneratePlanCompiledSource:
    if not isinstance(pending_state, dict):
        return ApplyThenGeneratePlanCompiledSource(
            blocking_reasons=["missing_applied_pending_state"],
        )
    if str(pending_state.get("kind") or "").strip() != "intent_change":
        return ApplyThenGeneratePlanCompiledSource(
            blocking_reasons=["apply_then_generate_requires_intent_pending"],
        )
    goal = str(user_prompt or "").strip() or "基于已采纳的报考参考生成方案"
    plan_payload = {
        "stage": "apply",
        "action_family": "generate_plan",
        "user_goal": goal,
        "requires_confirmation": False,
        "should_refresh_workspace": True,
        "should_rerun_review": True,
        "target_view": "ordered",
        "facts": {
            "composite_source": "apply_pending_then_new_request",
            "applied_pending_id": str(pending_state.get("pendingId") or "").strip(),
            "applied_pending_kind": str(pending_state.get("kind") or "").strip(),
        },
    }
    if source_version_guard > 0:
        plan_payload["planning_version"] = source_version_guard

    summary = "基于刚采纳的报考参考准备生成方案；确认后再正式生成。"
    summary = f"{summary}\n\n本次要求：{goal}"
    confirmation_candidate = {
        "action_family": "generate_plan",
        "user_goal": goal,
        "summary": summary,
        "plan_payload": plan_payload,
    }
    if source_version_guard > 0:
        confirmation_candidate["source_backend_version"] = source_version_guard
        confirmation_candidate["planning_version"] = source_version_guard

    compiled_source = compile_runtime_plan_confirmation_source(
        session_id=session_id,
        confirmation_candidate=confirmation_candidate,
        source="apply_pending_then_new_request",
        summary=summary,
    )
    if not compiled_source.compiled:
        return ApplyThenGeneratePlanCompiledSource(
            confirmation_candidate=confirmation_candidate,
            source_version_guard=compiled_source.source_version_guard,
            blocking_reasons=list(compiled_source.blocking_reasons),
        )
    return ApplyThenGeneratePlanCompiledSource(
        confirmation_candidate=confirmation_candidate,
        compiled=compiled_source.compiled,
        source_version_guard=compiled_source.source_version_guard,
        blocking_reasons=list(compiled_source.blocking_reasons),
    )


def proposal_id(proposal: dict[str, Any]) -> str:
    return str(proposal.get("proposal_id") or proposal.get("proposalId") or "").strip()


def _proposal_actions(proposal: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in proposal.get("actions") or [] if isinstance(item, dict)]


def _proposal_dry_run(proposal: dict[str, Any]) -> dict[str, Any]:
    dry_run = proposal.get("dryRunObservation") or proposal.get("dryRunResult") or proposal.get("dry_run_result") or proposal.get("dryRun")
    return dry_run if isinstance(dry_run, dict) else {}


def compile_user_goal_fix_proposal(
    *,
    session_id: str,
    proposal: dict[str, Any],
    source_version_guard: int,
    user_goal_request: dict[str, Any],
    intent_payload: dict[str, Any] | None,
    summary: str,
) -> dict[str, Any]:
    proposal_id_value = proposal_id(proposal)
    return {
        "compiledProposalId": f"user-goal-fix:{session_id}:{uuid.uuid4()}",
        "sideEffect": "plan_pending",
        "outputType": "plan_mutation",
        "pendingType": "plan_mutation",
        "requiresConfirmation": True,
        "executionPayload": {
            "kind": "pending_plan_mutation",
            "actionFamilies": ["apply_fix_proposal"],
            "targetView": "ordered",
        },
        "workspaceRefreshTargets": ["ordered"],
        "intentPayload": intent_payload if isinstance(intent_payload, dict) else {},
        "displayPayload": {
            "presentation": "confirmation_card",
            "pendingCardType": "pendingConfirmationCard",
            "summary": summary,
        },
        "proposalCandidates": [
            {
                "id": proposal_id_value,
                "proposalId": proposal_id_value,
                "type": "java_fix_proposal_reference",
                "source": "java_user_goal",
                "executionAuthority": "java_fix_proposal",
                "ready": str(proposal.get("status") or "").strip() == "ready",
                "strategy": str(proposal.get("strategy") or "").strip(),
                "actions": _proposal_actions(proposal),
                "sourceVersionGuard": source_version_guard,
                "dryRunObservation": _proposal_dry_run(proposal),
                "userGoalRequest": user_goal_request,
            }
        ],
        "replyPlan": {
            "mode": ["confirmable_plan_mutation"],
            "focus": ["constraint_preview", "java_user_goal_fix"],
        },
        "blockingReasons": [],
    }


def compile_review_fix_proposal(
    *,
    session_id: str,
    proposal: dict[str, Any],
    source_version_guard: int,
    proposal_source: str,
    summary: str,
) -> dict[str, Any]:
    proposal_id_value = proposal_id(proposal)
    return {
        "compiledProposalId": f"review-fix:{session_id}:{uuid.uuid4()}",
        "sideEffect": "plan_pending",
        "outputType": "plan_mutation",
        "pendingType": "plan_mutation",
        "requiresConfirmation": True,
        "executionPayload": {
            "kind": "pending_plan_mutation",
            "actionFamilies": ["apply_fix_proposal"],
            "targetView": "review",
        },
        "workspaceRefreshTargets": ["review"],
        "intentPayload": {},
        "displayPayload": {
            "presentation": "confirmation_card",
            "pendingCardType": "pendingConfirmationCard",
            "summary": summary,
        },
        "proposalCandidates": [
            {
                "id": proposal_id_value,
                "proposalId": proposal_id_value,
                "type": "java_fix_proposal_reference",
                "source": proposal_source or "review_check",
                "executionAuthority": "java_fix_proposal",
                "ready": str(proposal.get("status") or "").strip() == "ready",
                "strategy": str(proposal.get("strategy") or "").strip(),
                "actions": _proposal_actions(proposal),
                "sourceVersionGuard": source_version_guard,
                "dryRunObservation": _proposal_dry_run(proposal),
            }
        ],
        "replyPlan": {
            "mode": ["confirmable_plan_mutation"],
            "focus": ["review_fix_proposal"],
        },
        "blockingReasons": [],
    }


def intent_sink_contract(compiled: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not str(compiled.get("compiledProposalId") or "").strip():
        reasons.append("missing_compiled_proposal_id")
    if str(compiled.get("pendingType") or "") != "intent_change":
        reasons.append("intent_sink_requires_intent_change_pending_type")
    execution_payload = compiled.get("executionPayload")
    if not isinstance(execution_payload, dict) or execution_payload.get("kind") != "pending_intent_change":
        reasons.append("intent_sink_requires_pending_intent_change_execution")
    if not isinstance(compiled.get("intentPayload"), dict):
        reasons.append("intent_sink_requires_intent_payload")
    return not reasons, reasons


def intent_sink_metadata_or_none(
    compiled: dict[str, Any],
    *,
    session_id: str,
    source: str,
) -> dict[str, Any] | None:
    contract_ok, contract_reasons = intent_sink_contract(compiled)
    if not contract_ok:
        logger.warning(
            "Compiled intent blocked before sink: session_id=%s source=%s reasons=%s",
            session_id,
            source,
            contract_reasons,
        )
        return None
    return {
        "compiledProposalId": compiled["compiledProposalId"],
        "sinkType": "intent",
    }


def plan_sink_contract(compiled: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not str(compiled.get("compiledProposalId") or "").strip():
        reasons.append("missing_compiled_proposal_id")
    if str(compiled.get("pendingType") or "") != "plan_mutation":
        reasons.append("plan_sink_requires_plan_mutation_pending_type")
    blocking_reasons = compiled.get("blockingReasons")
    if isinstance(blocking_reasons, list):
        for reason in blocking_reasons:
            text = str(reason or "").strip()
            if text:
                _append_reason(reasons, text)
    execution_payload = compiled.get("executionPayload")
    if not isinstance(execution_payload, dict) or execution_payload.get("kind") != "pending_plan_mutation":
        reasons.append("plan_sink_requires_pending_plan_mutation_execution")
        return not reasons, reasons
    action_family = str(execution_payload.get("actionFamily") or "").strip()
    action_families = [
        str(item or "").strip()
        for item in (execution_payload.get("actionFamilies") or [])
        if str(item or "").strip()
    ]
    if not action_family and action_families:
        action_family = action_families[0]
    if not action_family:
        reasons.append("plan_pending_requires_action_family")
    if action_family == "apply_fix_proposal":
        reasons.append("plan_sink_rejects_fix_proposal_candidate")
    elif action_family and action_family not in PENDING_PLAN_ACTION_FAMILIES:
        reasons.append("unsupported_plan_action_family")
    plan_candidates = [
        candidate for candidate in (compiled.get("proposalCandidates") or [])
        if isinstance(candidate, dict)
        and str(candidate.get("type") or "").strip() == "plan_confirmation_candidate"
    ]
    if action_family and action_family != "apply_fix_proposal" and not plan_candidates:
        _append_reason(reasons, "plan_sink_requires_plan_confirmation_candidate")
    for candidate in plan_candidates:
        if not isinstance(candidate, dict):
            continue
        candidate_action_family = str(candidate.get("actionFamily") or "").strip()
        if candidate_action_family and action_family and candidate_action_family != action_family:
            _append_reason(reasons, "plan_candidate_action_family_mismatch")
        candidate_payload = candidate.get("plan_payload")
        if not isinstance(candidate_payload, dict) or not candidate_payload:
            _append_reason(reasons, "plan_candidate_requires_plan_payload")
            continue
        payload_action_family = _plan_payload_action_family(candidate_payload)
        if payload_action_family and action_family and payload_action_family != action_family:
            _append_reason(reasons, "plan_candidate_action_family_mismatch")
        if str(candidate_payload.get("stage") or "").strip() != "apply":
            _append_reason(reasons, "plan_candidate_requires_apply_stage")
        requires_confirmation = (
            candidate_payload.get("requires_confirmation")
            if "requires_confirmation" in candidate_payload
            else candidate_payload.get("requiresConfirmation")
        )
        if requires_confirmation is True:
            _append_reason(reasons, "plan_candidate_apply_payload_must_not_require_confirmation")
    return not reasons, reasons


def plan_sink_metadata_or_none(
    compiled: dict[str, Any],
    *,
    session_id: str,
    source: str,
) -> dict[str, Any] | None:
    contract_ok, contract_reasons = plan_sink_contract(compiled)
    if not contract_ok:
        logger.warning(
            "Compiled plan blocked before sink: session_id=%s source=%s reasons=%s",
            session_id,
            source,
            contract_reasons,
        )
        return None
    return {
        "compiledProposalId": compiled["compiledProposalId"],
        "sinkType": "plan",
    }


def fix_proposal_sink_contract(compiled: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not str(compiled.get("compiledProposalId") or "").strip():
        reasons.append("missing_compiled_proposal_id")
    if str(compiled.get("pendingType") or "") != "plan_mutation":
        reasons.append("fix_sink_requires_plan_mutation_pending_type")
    execution_payload = compiled.get("executionPayload")
    if not isinstance(execution_payload, dict) or execution_payload.get("kind") != "pending_plan_mutation":
        reasons.append("fix_sink_requires_pending_plan_mutation_execution")
    candidates = [
        item for item in (compiled.get("proposalCandidates") or [])
        if isinstance(item, dict) and str(item.get("type") or "").strip() == "java_fix_proposal_reference"
    ]
    if not candidates:
        reasons.append("fix_sink_requires_java_fix_proposal_reference")
        return False, reasons
    candidate = candidates[0]
    if not str(candidate.get("proposalId") or candidate.get("id") or "").strip():
        reasons.append("fix_proposal_requires_proposal_id")
    if _as_int(candidate.get("sourceVersionGuard") or candidate.get("source_version_guard")) <= 0:
        reasons.append("fix_proposal_requires_source_version_guard")
    if not _proposal_actions(candidate) and not bool(candidate.get("hasActions")):
        reasons.append("fix_proposal_requires_actions")
    if not _proposal_dry_run(candidate):
        reasons.append("fix_proposal_requires_dry_run_observation")
    return not reasons, reasons


def ready_fix_proposals(facts: dict[str, Any] | None) -> list[dict[str, Any]]:
    fix_proposals = facts.get("fix_proposals") if isinstance(facts, dict) else None
    proposals = fix_proposals.get("proposals") if isinstance(fix_proposals, dict) else None
    if not isinstance(proposals, list):
        return []
    source = str(
        fix_proposals.get("proposal_source")
        or fix_proposals.get("proposalSource")
        or ""
    ).strip()
    ready: list[dict[str, Any]] = []
    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        proposal_source = str(
            proposal.get("proposal_source")
            or proposal.get("proposalSource")
            or source
            or ""
        ).strip()
        if str(proposal.get("status") or "").strip() != "ready":
            continue
        proposal_id_value = proposal_id(proposal)
        if not proposal_id_value:
            continue
        if proposal_source and "proposal_source" not in proposal and "proposalSource" not in proposal:
            proposal = {**proposal, "proposal_source": proposal_source}
        ready.append(proposal)
    return ready


def selected_fix_proposal_id(source: dict[str, Any] | None, facts: dict[str, Any] | None) -> str:
    candidates: list[Any] = []
    if isinstance(source, dict):
        candidates.extend(
            [
                source.get("selected_proposal_id"),
                source.get("selectedProposalId"),
                source.get("target_proposal_id"),
                source.get("targetProposalId"),
            ]
        )
    fix_proposals = facts.get("fix_proposals") if isinstance(facts, dict) else None
    if isinstance(fix_proposals, dict):
        candidates.extend(
            [
                fix_proposals.get("selected_proposal_id"),
                fix_proposals.get("selectedProposalId"),
                fix_proposals.get("target_proposal_id"),
                fix_proposals.get("targetProposalId"),
            ]
        )
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text:
            return text
    return ""


def normalize_fix_proposal_target_strategies(
    target_strategies: set[str] | list[str] | tuple[str, ...] | str | None,
) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    values = [target_strategies] if isinstance(target_strategies, str) else (target_strategies or [])
    for strategy in values:
        text = str(strategy or "").strip()
        if text and text not in seen:
            normalized.append(text)
            seen.add(text)
    return normalized


def normalize_fix_proposal_target_issue_codes(
    target_issue_codes: set[str] | list[str] | tuple[str, ...] | str | None,
) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    values = [target_issue_codes] if isinstance(target_issue_codes, str) else (target_issue_codes or [])
    for code in values:
        text = str(code or "").strip()
        if text and text not in seen:
            normalized.append(text)
            seen.add(text)
    return normalized


def _fix_proposal_source_issue_codes(proposal: dict[str, Any]) -> set[str]:
    return {
        str(code or "").strip()
        for code in (proposal.get("source_check_codes") or proposal.get("sourceCheckCodes") or [])
        if str(code or "").strip()
    }


def _fix_proposal_matches_target_strategies(
    proposal: dict[str, Any],
    target_strategies: list[str],
) -> bool:
    if not target_strategies:
        return True
    strategy = str(proposal.get("strategy") or "").strip()
    return strategy in set(target_strategies)


def fix_proposal_matches_target_scope(
    proposal: dict[str, Any],
    target_strategies: list[str],
    target_issue_codes: list[str],
) -> bool:
    if target_strategies and not _fix_proposal_matches_target_strategies(proposal, target_strategies):
        return False
    if target_issue_codes:
        proposal_issue_codes = _fix_proposal_source_issue_codes(proposal)
        if not proposal_issue_codes or not (proposal_issue_codes & set(target_issue_codes)):
            return False
    return bool(target_strategies or target_issue_codes)


def filter_ready_fix_proposals_by_target_scope(
    ready: list[dict[str, Any]],
    target_strategies: list[str],
    target_issue_codes: list[str],
) -> list[dict[str, Any]]:
    if not target_strategies and not target_issue_codes:
        return ready
    return [
        proposal
        for proposal in ready
        if fix_proposal_matches_target_scope(proposal, target_strategies, target_issue_codes)
    ]


def select_ready_fix_proposal(
    facts: dict[str, Any] | None,
    *,
    selected_proposal_id: str = "",
    target_strategies: set[str] | list[str] | tuple[str, ...] | None = None,
    target_issue_codes: set[str] | list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any] | None:
    ready = ready_fix_proposals(facts)
    if not ready:
        return None
    selected_id = str(selected_proposal_id or "").strip()
    if selected_id:
        for proposal in ready:
            if proposal_id(proposal) == selected_id:
                return proposal
        return None
    normalized_strategies = normalize_fix_proposal_target_strategies(target_strategies)
    normalized_issue_codes = normalize_fix_proposal_target_issue_codes(target_issue_codes)
    if normalized_strategies or normalized_issue_codes:
        for target_strategy in normalized_strategies:
            for proposal in ready:
                if fix_proposal_matches_target_scope(
                    proposal,
                    [target_strategy],
                    normalized_issue_codes,
                ):
                    return proposal
        if not normalized_strategies:
            for proposal in ready:
                if fix_proposal_matches_target_scope(
                    proposal,
                    [],
                    normalized_issue_codes,
                ):
                    return proposal
        return None
    return ready[0]


def ready_fix_proposal_id_for_strategies(
    facts: dict[str, Any] | None,
    target_strategies: set[str] | list[str] | tuple[str, ...] | None,
) -> str:
    if not [
        str(strategy or "").strip()
        for strategy in (target_strategies or [])
        if str(strategy or "").strip()
    ]:
        return ""
    proposal = select_ready_fix_proposal(
        facts,
        target_strategies=target_strategies,
    )
    if not isinstance(proposal, dict):
        return ""
    return proposal_id(proposal)


def select_user_goal_fix_proposal(
    proposal_data: dict[str, Any] | None,
    *,
    goal_type: str,
    fallback_source_version_guard: int = 0,
) -> UserGoalFixProposalSelection:
    normalized_goal_type = str(goal_type or "").strip()
    if not isinstance(proposal_data, dict):
        return UserGoalFixProposalSelection(
            goal_type=normalized_goal_type,
            blocking_reasons=["missing_user_goal_proposal_data"],
        )
    source_version_guard = _as_int(
        proposal_data.get("sourceVersionGuard")
        or proposal_data.get("source_version_guard")
        or fallback_source_version_guard
    )
    proposals = proposal_data.get("proposals") if isinstance(proposal_data.get("proposals"), list) else []
    fallback_proposal = next((item for item in proposals if isinstance(item, dict)), None)
    if not normalized_goal_type:
        return UserGoalFixProposalSelection(
            fallback_proposal=fallback_proposal,
            source_version_guard=source_version_guard,
            goal_type=normalized_goal_type,
            blocking_reasons=["missing_user_goal_type"],
        )
    proposal = select_ready_fix_proposal(
        {"fix_proposals": proposal_data},
        target_strategies=[normalized_goal_type],
    )
    if isinstance(proposal, dict):
        normalized_proposal = dict(proposal)
        normalized_proposal.setdefault("proposalSource", "user_goal")
        return UserGoalFixProposalSelection(
            proposal=normalized_proposal,
            source_version_guard=source_version_guard,
            goal_type=normalized_goal_type,
        )
    reasons: list[str] = []
    if source_version_guard <= 0:
        reasons.append("missing_source_version_guard")
    reasons.append("no_ready_user_goal_fix_proposal_for_goal_type")
    return UserGoalFixProposalSelection(
        fallback_proposal=fallback_proposal,
        source_version_guard=source_version_guard,
        goal_type=normalized_goal_type,
        blocking_reasons=reasons,
    )
