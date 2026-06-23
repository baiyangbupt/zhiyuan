from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

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


@dataclass
class FixProposalSelectionResult:
    proposal: dict[str, Any] | None = None
    selected_proposal_id: str = ""
    target_strategies: list[str] = field(default_factory=list)
    target_issue_codes: list[str] = field(default_factory=list)
    target_match_empty: bool = False
    blocking_reasons: list[str] = field(default_factory=list)


@dataclass
class RuntimeReviewFixCompiledSource:
    proposal: dict[str, Any] | None = None
    compiled: dict[str, Any] | None = None
    selection: FixProposalSelectionResult = field(default_factory=FixProposalSelectionResult)
    source_version_guard: int = 0
    proposal_source: str = "review_check"
    target_match_empty: bool = False
    blocking_reasons: list[str] = field(default_factory=list)


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
class IntentProposalInputResolution:
    allowed: bool = False
    intent_mode: str = "preference"
    constraint_intent_type: str = "default"
    blocking_reasons: list[str] = field(default_factory=list)


@dataclass
class FixProposalTargetScope:
    target_strategies: list[str] = field(default_factory=list)
    target_issue_codes: list[str] = field(default_factory=list)
    explicit: bool = False


@dataclass
class FixProposalTargetScopeResolution:
    target_strategies: list[str] = field(default_factory=list)
    target_issue_codes: list[str] = field(default_factory=list)
    explicit: bool = False
    needs_semantic_decision: bool = False
    source: str = ""
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

_PENDING_READONLY_IMPACT_USER_TOKENS = (
    "先不确认",
    "不确认",
    "暂不确认",
    "还没确认",
    "先别执行",
    "先不执行",
    "看看影响",
    "看影响",
    "有什么影响",
    "会不会影响",
    "影响当前方案",
    "影响方案",
    "当前方案吗",
    "当前方案么",
    "先看看",
)

_PENDING_READONLY_IMPACT_SCOPE_TOKENS = (
    "影响",
    "当前方案",
    "候选",
    "承接",
    "匹配",
    "冲突",
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

_PENDING_APPLY_MARKERS = (
    "确认",
    "确认执行",
    "执行",
    "执行吧",
    "采纳",
    "删完",
    "删除后",
    "移出后",
    "处理完",
    "改完",
    "应用后",
)

_PENDING_NEGATED_APPLY_MARKERS = (
    "先不确认",
    "暂不确认",
    "还没确认",
    "未确认",
    "没确认",
    "不确认",
    "先别执行",
    "先不执行",
    "暂不执行",
    "别执行",
    "不执行",
    "不要执行",
    "不用执行",
    "不采纳",
    "不要采纳",
    "不用采纳",
)

_PENDING_FOLLOWUP_READONLY_MARKERS = (
    "再看",
    "再看看",
    "看还剩",
    "还剩多少",
    "剩多少",
    "梯度",
    "风险",
    "结果",
    "当前方案",
    "审查",
    "检查",
)

_PENDING_NEW_MUTATION_MARKERS = (
    "只要",
    "只保留",
    "至少保留",
    "不要",
    "排除",
    "避开",
    "删",
    "删除",
    "移出",
    "拿掉",
    "替换",
    "换掉",
    "加入",
    "加到",
    "加进",
    "补",
    "补入",
    "生成",
    "重排",
    "排序",
    "调整",
    "改成",
    "改为",
)

_PENDING_MUTATION_OBJECT_MARKERS = (
    "方案",
    "志愿",
    "专业",
    "专业组",
    "学校",
    "院校",
    "偏好",
    "要求",
    "意向",
    "保底",
    "冲",
    "稳",
    "民办",
    "公办",
    "中外合作",
    "学费",
)

_PENDING_SOFT_DISCUSSION_MARKERS = (
    "为什么",
    "解释",
    "说明",
    "区别",
    "怎么理解",
    "什么意思",
    "能不能讲",
    "看一下影响",
    "看看影响",
    "影响哪些",
    "会影响",
)


_PENDING_EXPLICIT_IMPACT_TOKENS = (
    "影响",
    "采纳后",
    "生效后",
    "采用后",
    "后果",
)


@dataclass(frozen=True)
class _PlanQueryDimensionRule:
    name: str
    markers: tuple[str, ...]
    min_markers: tuple[str, ...] = ()
    max_markers: tuple[str, ...] = ()


@dataclass(frozen=True)
class _PlanQueryGrammar:
    readonly_markers: tuple[str, ...]
    mutation_markers: tuple[str, ...]
    current_plan_markers: tuple[str, ...]
    item_markers: tuple[str, ...]
    count_markers: tuple[str, ...]
    tail_markers: tuple[str, ...]
    head_markers: tuple[str, ...]
    pending_reference_markers: tuple[str, ...]
    tier_markers: dict[str, tuple[str, ...]]
    limit_words: dict[str, int]
    dimensions: tuple[_PlanQueryDimensionRule, ...]


@dataclass
class _PlanQueryIntent:
    matched: bool = False
    route: str = ""
    dimensions: list[str] = field(default_factory=list)
    filters: dict[str, Any] = field(default_factory=dict)
    projection: dict[str, Any] = field(default_factory=dict)
    reply_focus: list[str] = field(default_factory=list)
    blocking_reasons: list[str] = field(default_factory=list)


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


_PLAN_QUERY_GRAMMAR = _PlanQueryGrammar(
    readonly_markers=(
        "几个",
        "多少",
        "占比",
        "多吗",
        "多不多",
        "有没有",
        "哪些",
        "哪个",
        "哪几个",
        "是什么",
        "什么学校",
        "看下",
        "看一下",
        "看看",
        "再看",
        "再给我看",
        "查下",
        "查一下",
        "查查",
        "列出",
        "列一下",
    ),
    mutation_markers=(
        "删",
        "删除",
        "移出",
        "替换",
        "换掉",
        "加入",
        "加到",
        "补到",
        "调到",
        "移动",
        "控制",
        "调整",
        "改成",
    ),
    current_plan_markers=(
        "当前方案",
        "现在方案",
        "方案里",
        "方案中",
        "这版方案",
        "当前这版",
        "志愿里",
        "志愿中",
    ),
    item_markers=(
        "学校",
        "院校",
        "志愿",
        "专业",
        "专业组",
        "录取率",
        "概率",
    ),
    count_markers=(
        "几个",
        "多少",
        "占比",
        "多吗",
        "多不多",
    ),
    tail_markers=(
        "最后",
        "末尾",
        "后几个",
        "靠后",
    ),
    head_markers=(
        "前几个",
        "最前",
        "开头",
        "前面",
    ),
    pending_reference_markers=(
        "相关专业",
        "相关方向",
        "这个专业",
        "这些专业",
        "这个方向",
        "这些方向",
        "这个意向",
        "这些意向",
        "相关学校",
        "相关院校",
        "这个学校",
        "这些学校",
        "这个院校",
        "这些院校",
    ),
    tier_markers={
        "保": ("保底学校", "保底志愿", "保底", "保区", "兜底"),
        "冲": ("冲档", "冲区", "冲一冲"),
        "稳": ("稳档", "稳区", "稳妥", "稳一稳"),
    },
    limit_words={
        "一个": 1,
        "两个": 2,
        "俩个": 2,
        "三个": 3,
        "四个": 4,
        "五个": 5,
        "六个": 6,
        "七个": 7,
        "八个": 8,
        "九个": 9,
        "十个": 10,
    },
    dimensions=(
        _PlanQueryDimensionRule(
            name="tuition",
            markers=("学费", "费用", "收费", "高收费", "太贵", "贵的", "贵", "便宜"),
            min_markers=("以上", "超过", "高于", "不少于", "不低于", "贵"),
            max_markers=("以内", "以下", "不超过", "低于", "便宜"),
        ),
    ),
)


def _contains_any(compact: str, markers: tuple[str, ...]) -> bool:
    return any(marker in compact for marker in markers)


def _plan_query_has_readonly_intent(compact: str) -> bool:
    return _contains_any(compact, _PLAN_QUERY_GRAMMAR.readonly_markers)


def _plan_query_has_mutation_intent(compact: str) -> bool:
    return _contains_any(compact, _PLAN_QUERY_GRAMMAR.mutation_markers)


def _plan_query_limit(compact: str, default: int = 5) -> int:
    digit_match = re.search(r"(\d{1,2})(?:个|条|所|项)", compact)
    if digit_match:
        return max(1, min(10, int(digit_match.group(1))))
    for marker, value in _PLAN_QUERY_GRAMMAR.limit_words.items():
        if marker in compact:
            return value
    return default


def _parse_plan_query_amount(compact: str) -> int:
    explicit = re.search(r"(\d{4,6})", compact)
    if explicit:
        return _as_int(explicit.group(1))
    wan_match = re.search(r"(\d+(?:\.\d+)?)万", compact)
    if wan_match:
        try:
            return int(float(wan_match.group(1)) * 10000)
        except ValueError:
            return 0
    chinese_wan_values = {
        "一万": 10000,
        "两万": 20000,
        "二万": 20000,
        "三万": 30000,
        "四万": 40000,
        "五万": 50000,
        "六万": 60000,
        "七万": 70000,
        "八万": 80000,
        "九万": 90000,
        "十万": 100000,
    }
    for marker, value in chinese_wan_values.items():
        if marker in compact:
            return value
    return 0


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


def compile_profile_change_replan_source(
    *,
    profile_scenario: str,
    proposed_profile: dict[str, Any] | None = None,
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
    proposed_profile = _normalize_profile_payload(dict(proposed_profile or {}))
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


def _plan_query_tier(compact: str) -> str:
    for tier, markers in _PLAN_QUERY_GRAMMAR.tier_markers.items():
        if _contains_any(compact, markers):
            return tier
    return ""


def _plan_query_slice_mode(compact: str) -> str:
    if _contains_any(compact, _PLAN_QUERY_GRAMMAR.tail_markers):
        return "tail"
    return "head"


def _plan_query_projection_fields(compact: str) -> list[str]:
    fields = ["school", "major"]
    if any(marker in compact for marker in ("录取率", "概率")):
        fields.append("admission_probability")
    elif _contains_any(compact, _PLAN_QUERY_GRAMMAR.item_markers):
        fields.append("admission_probability")
    return fields


def _resolve_plan_query_intent(
    content: str | None,
    *,
    allow_pending_reference: bool = False,
) -> _PlanQueryIntent:
    compact = _compact_text(content)
    if not compact:
        return _PlanQueryIntent(blocking_reasons=["empty_query"])
    if _plan_query_has_mutation_intent(compact):
        return _PlanQueryIntent(blocking_reasons=["mutation_request_not_plan_query"])
    if not _plan_query_has_readonly_intent(compact):
        return _PlanQueryIntent(blocking_reasons=["missing_readonly_query_intent"])

    filters: dict[str, Any] = {"limit": _plan_query_limit(compact)}
    dimensions: list[str] = []
    reply_focus: list[str] = ["ordered_snapshot", "local_plan_query"]
    tier = _plan_query_tier(compact)
    if tier:
        filters["tier"] = tier

    tuition_rule = next(
        (rule for rule in _PLAN_QUERY_GRAMMAR.dimensions if rule.name == "tuition"),
        None,
    )
    if tuition_rule is not None and _contains_any(compact, tuition_rule.markers):
        amount = _parse_plan_query_amount(compact)
        if amount <= 0:
            return _PlanQueryIntent(blocking_reasons=["missing_tuition_threshold"])
        dimensions.append("tuition")
        reply_focus.extend(["plan_filter_query", "tuition"])
        if _contains_any(compact, tuition_rule.max_markers):
            filters["max_tuition_per_year"] = amount
        else:
            filters["min_tuition_per_year"] = amount

    if dimensions:
        return _PlanQueryIntent(
            matched=True,
            route="readonly_plan_query",
            dimensions=dimensions,
            filters=filters,
            projection={"mode": "count_with_examples", "limit": filters.get("limit", 5)},
            reply_focus=reply_focus,
        )

    if tier and (
        _contains_any(compact, _PLAN_QUERY_GRAMMAR.item_markers)
        or _contains_any(compact, _PLAN_QUERY_GRAMMAR.count_markers)
    ):
        filters["slice"] = _plan_query_slice_mode(compact)
        filters["include_fields"] = _plan_query_projection_fields(compact)
        return _PlanQueryIntent(
            matched=True,
            route="readonly_plan_slice_query",
            dimensions=["tier_segment"],
            filters=filters,
            projection={
                "mode": "slice_examples",
                "limit": filters.get("limit", 5),
                "fields": list(filters["include_fields"]),
            },
            reply_focus=[*reply_focus, "plan_slice_query"],
        )

    if allow_pending_reference and _contains_any(compact, _PLAN_QUERY_GRAMMAR.pending_reference_markers):
        return _PlanQueryIntent(
            matched=True,
            route="readonly_pending_reference_query",
            dimensions=["pending_reference"],
            filters=filters,
            projection={"mode": "examples", "limit": filters.get("limit", 5)},
            reply_focus=[*reply_focus, "pending_reference_query"],
        )

    if _contains_any(compact, _PLAN_QUERY_GRAMMAR.current_plan_markers):
        return _PlanQueryIntent(blocking_reasons=["unsupported_plan_query_dimension"])
    return _PlanQueryIntent(blocking_reasons=["missing_current_plan_query_scope"])


def pending_turn_looks_plan_query_while_pending(content: str | None) -> bool:
    compact = _compact_text(content)
    if _contains_any(compact, _PENDING_EXPLICIT_IMPACT_TOKENS):
        return False
    return _resolve_plan_query_intent(
        content,
        allow_pending_reference=True,
    ).matched


def pending_turn_looks_readonly_impact(content: str | None) -> bool:
    compact = _compact_text(content)
    if not compact:
        return False
    if pending_turn_looks_plan_query_while_pending(content):
        return False
    has_readonly_marker = any(token in compact for token in _PENDING_READONLY_IMPACT_USER_TOKENS)
    has_impact_marker = any(token in compact for token in _PENDING_READONLY_IMPACT_SCOPE_TOKENS)
    return has_readonly_marker and has_impact_marker


def pending_turn_looks_direct_confirmation(content: str | None, pending_kind: str | None) -> bool:
    normalized = _normalize_confirmation_only_text(content, strip_fullwidth_question=True)
    if not normalized or normalized in _READONLY_CLOSURE_ACK_PHRASES:
        return False
    pending_kind = str(pending_kind or "").strip()
    if pending_kind == "plan_mutation":
        return normalized in _PENDING_DIRECT_PLAN_CONFIRM_ACKS
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


def pending_turn_looks_apply_then_readonly(content: str | None) -> bool:
    compact = _compact_text(content)
    if not compact:
        return False
    if any(token in compact for token in _PENDING_NEGATED_APPLY_MARKERS):
        return False
    has_apply = any(token in compact for token in _PENDING_APPLY_MARKERS)
    has_followup = any(token in compact for token in _PENDING_FOLLOWUP_READONLY_MARKERS)
    return has_apply and has_followup


def pending_turn_looks_apply_then_new_request(content: str | None, pending_kind: str | None) -> bool:
    compact = _compact_text(content)
    if not compact or str(pending_kind or "").strip() != "intent_change":
        return False
    if any(token in compact for token in _PENDING_NEGATED_APPLY_MARKERS):
        return False
    has_pending_reference = any(
        token in compact
        for token in (
            "基于这些",
            "按这些",
            "就按这些",
            "按这个",
            "就这个",
            "这些要求",
            "这些偏好",
            "这个偏好",
            "这条要求",
            "这项要求",
        )
    )
    has_generation_request = any(marker in compact for marker in _PLAN_GENERATION_MARKERS)
    return has_pending_reference and has_generation_request


def pending_turn_looks_new_mutation_request(content: str | None) -> bool:
    compact = _compact_text(content)
    if not compact:
        return False
    if any(token in compact for token in _PENDING_SOFT_DISCUSSION_MARKERS):
        return False
    has_mutation = any(token in compact for token in _PENDING_NEW_MUTATION_MARKERS)
    has_object = any(token in compact for token in _PENDING_MUTATION_OBJECT_MARKERS)
    return has_mutation and has_object


_EXPLICIT_INTENT_UPDATE_MARKERS = (
    "加意向",
    "加入意向",
    "加到意向",
    "加进意向",
    "补到意向",
    "补进意向",
    "补充意向",
    "作为优先方向",
    "优先方向",
    "优先考虑",
    "优先看",
    "优先",
    "城市优先",
    "地域优先",
    "地区优先",
    "倾向",
    "偏向",
    "偏好",
    "想学",
    "想读",
    "想报",
    "排除",
)

_EXPLICIT_INTENT_ADD_MARKERS = (
    "就加",
    "都加",
    "加上",
    "补上",
    "补充",
    "纳入",
    "记到",
    "记录",
)

_EXPLICIT_INTENT_ADD_SCOPE_MARKERS = (
    "意向",
    "偏好",
    "以后",
    "后续",
    "推荐",
    "报考",
    "专业",
    "院校",
    "学校",
    "大学",
    "强基",
    "计算机",
    "电子信息",
    "互联网",
)

_EXPLICIT_INTENT_READONLY_MARKERS = (
    "看看",
    "看下",
    "看一下",
    "介绍",
    "区别",
    "适合",
    "值不值得",
    "怎么样",
    "为什么",
    "怎么",
    "能不能",
    "可不可以",
    "行不行",
    "是否",
    "吗",
    "么",
)

_EXPLICIT_INTENT_CURRENT_PLAN_MARKERS = (
    "当前方案",
    "加到方案",
    "加进方案",
    "加入方案",
    "补到方案",
    "补进方案",
    "放到方案",
    "方案里",
    "志愿里",
    "删掉",
    "删除",
    "移出",
    "拿掉",
    "替换",
    "换掉",
)

_EXPLICIT_INTENT_REGION_MARKERS = (
    "城市",
    "地域",
    "地区",
    "省份",
    "长三角",
    "珠三角",
    "南方",
    "北方",
)


def prompt_looks_explicit_intent_update(content: str | None) -> bool:
    compact = _compact_text(content)
    if not compact:
        return False
    if any(marker in compact for marker in ("只想", "只考虑", "只要", "只保留")):
        return False
    if "其他" in compact and "不要" in compact:
        return False
    if any(marker in compact for marker in _EXPLICIT_INTENT_CURRENT_PLAN_MARKERS):
        return False
    if any(marker in compact for marker in _EXPLICIT_INTENT_READONLY_MARKERS):
        return False
    if any(marker in compact for marker in _EXPLICIT_INTENT_UPDATE_MARKERS):
        return True
    has_add_marker = any(marker in compact for marker in _EXPLICIT_INTENT_ADD_MARKERS)
    has_add_scope = any(marker in compact for marker in _EXPLICIT_INTENT_ADD_SCOPE_MARKERS)
    return has_add_marker and has_add_scope


def explicit_intent_recovery_scope(content: str | None) -> str:
    compact = _compact_text(content)
    if any(marker in compact for marker in _EXPLICIT_INTENT_REGION_MARKERS):
        return "region"
    return "generic"


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


def _plan_query_profile_limit(filters: dict[str, Any], projection: dict[str, Any]) -> int:
    limit = _as_int(filters.get("limit") or projection.get("limit"), 5)
    return max(1, min(10, limit or 5))


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
    raw_filters = query_profile.get("filters") if isinstance(query_profile.get("filters"), dict) else {}
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
        reply_focus = ["ordered_snapshot", "local_plan_query"]

    if query_type == "readonly_plan_query":
        if "tuition" not in dimensions:
            return RuntimePlanQueryCompiledSource(blocking_reasons=["unsupported_plan_query_profile_dimension"])
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
        if "plan_slice_query" not in reply_focus:
            reply_focus.append("plan_slice_query")

    else:
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
    plan_query_dsl = {
        "type": "PlanQuery",
        "scopeAnchor": "current_plan",
        "sideEffect": side_effect,
        "queryType": query_type,
        "dimensions": dimensions,
        "filters": dict(filters),
        "projection": dict(projection),
        "sourceVersionGuard": planning_version,
    }
    plan_payload = {
        "stage": "apply",
        "action_family": "query_ordered",
        "user_goal": goal,
        "requires_confirmation": False,
        "planning_version": planning_version,
        "atomic_actions": [
            {
                "action_type": "query_ordered",
                "filters": dict(filters),
                "reason": goal,
            }
        ],
        "reply_focus": reply_focus,
    }
    return RuntimePlanQueryCompiledSource(
        matched=True,
        route=query_type,
        side_effect=side_effect,
        action_family="query_ordered",
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


def compile_runtime_plan_query_source(
    *,
    content: str | None,
    planning_version: int = 0,
    pending_exists: bool = False,
) -> RuntimePlanQueryCompiledSource:
    """Compile readonly current-plan query DSL into an executable plan payload.

    This is the runtime shape of 3.2.0 PlanQuery. It intentionally returns a
    structured query source instead of having service.py branch on prompt text.
    """
    intent = _resolve_plan_query_intent(content)
    if not intent.matched:
        return RuntimePlanQueryCompiledSource(blocking_reasons=list(intent.blocking_reasons))

    goal = str(content or "").strip()
    plan_query_dsl = {
        "type": "PlanQuery",
        "scopeAnchor": "current_plan",
        "sideEffect": "readonly_while_pending" if pending_exists else "readonly",
        "queryType": intent.route,
        "dimensions": list(intent.dimensions),
        "filters": dict(intent.filters),
        "projection": dict(intent.projection),
        "sourceVersionGuard": planning_version,
    }
    plan_payload = {
        "stage": "apply",
        "action_family": "query_ordered",
        "user_goal": goal,
        "requires_confirmation": False,
        "planning_version": planning_version,
        "atomic_actions": [
            {
                "action_type": "query_ordered",
                "filters": dict(intent.filters),
                "reason": goal,
            }
        ],
        "reply_focus": list(intent.reply_focus),
    }
    return RuntimePlanQueryCompiledSource(
        matched=True,
        route=intent.route,
        side_effect="readonly_while_pending" if pending_exists else "readonly",
        action_family="query_ordered",
        plan_payload=plan_payload,
        plan_query_dsl=plan_query_dsl,
        source_version_guard=planning_version,
    )


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
) -> dict[str, Any]:
    """Build the structured EvidencePlan for apply-existing-pending + readonly follow-up.

    This intentionally does not execute tools. It records what must be checked
    after the pending apply succeeds so runtime can avoid unsupported claims.
    """
    compact = _compact_text(content)
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

    target_issues: list[str] = []
    if any(token in compact for token in ("还剩多少", "剩多少", "看还剩", "数量", "多少")):
        target_issues.append("remaining_count")
    if "梯度" in compact:
        target_issues.append("tier_distribution")
    if any(token in compact for token in ("风险", "稳不稳", "稳定", "保底", "冲", "稳")):
        target_issues.append("risk_review")
    if any(token in compact for token in ("当前方案", "方案里", "方案中")) and "current_plan_state" not in target_issues:
        target_issues.append("current_plan_state")
    if not target_issues:
        target_issues.append("post_apply_state")

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

_FUTURE_REFERENCE_MARKERS = (
    "以后",
    "后续",
    "以后推荐",
    "后面推荐",
    "作为偏好",
    "作为要求",
    "记到",
    "记录",
    "意向",
    "偏好",
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

def _planning_summary_has_current_plan(planning_summary: Any) -> bool:
    if not planning_summary:
        return False
    if isinstance(planning_summary, dict):
        ordered_total = _as_int(planning_summary.get("ordered_total") or planning_summary.get("orderedTotal"))
        working_total = _as_int(planning_summary.get("working_total") or planning_summary.get("workingTotal"))
        return ordered_total > 0 or working_total > 0
    return (
        _as_int(getattr(planning_summary, "ordered_total", 0)) > 0
        or _as_int(getattr(planning_summary, "working_total", 0)) > 0
    )


def resolve_needs_plan_first_guard(
    content: str | None,
    *,
    planning_summary: Any = None,
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
    if not has_current_plan_reference or not has_plan_scope:
        return NeedsPlanFirstResolution()
    target_issues: list[str] = []
    if any(marker in compact for marker in ("民办", "公办")):
        target_issues.append("college_type")
    if "中外合作" in compact:
        target_issues.append("program_type")
    if any(marker in compact for marker in ("保底", "稳", "冲", "风险", "太冲")):
        target_issues.append("tier_or_risk")
    return NeedsPlanFirstResolution(
        side_effect="needs_plan_first",
        reference_resolution="no_referent",
        requires_model_decision=False,
        target_issues=target_issues,
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
    if pending_turn_looks_apply_then_readonly(content):
        evidence_plan = compile_post_apply_readonly_evidence_plan(content, pending_state=pending_state)
        return PendingTurnResolution(
            action="apply_pending_then_readonly",
            side_effect="apply_pending_then_readonly",
            pending_type=pending_type,
            requires_model_decision=False,
            post_apply_evidence_plan=evidence_plan,
            blocking_reasons=[],
        )
    if pending_turn_looks_apply_then_new_request(content, pending_kind):
        return PendingTurnResolution(
            action="apply_pending_then_new_request",
            side_effect="apply_pending_then_new_request",
            pending_type=pending_type,
            requires_model_decision=False,
            blocking_reasons=[],
        )
    if pending_turn_looks_readonly_impact(content):
        return PendingTurnResolution(
            action="ask_pending_impact",
            side_effect="readonly_while_pending",
            pending_type=pending_type,
            requires_model_decision=False,
        )
    if pending_turn_looks_direct_confirmation(content, pending_kind):
        return PendingTurnResolution(
            action="confirm_pending",
            side_effect="apply_existing_pending",
            pending_type=pending_type,
            requires_model_decision=False,
        )
    if pending_kind == "intent_change" and prompt_looks_explicit_intent_update(content):
        return PendingTurnResolution(
            pending_type=pending_type,
            requires_model_decision=True,
        )
    if pending_turn_looks_new_mutation_request(content):
        return PendingTurnResolution(
            action="conflict_with_existing_pending",
            side_effect="conflict_with_existing_pending",
            pending_type=pending_type,
            requires_model_decision=False,
            blocking_reasons=["active_pending_blocks_new_mutation_request"],
        )
    return PendingTurnResolution(
        pending_type=pending_type,
        requires_model_decision=True,
    )


def _parse_plan_confirmation_payload(value: Any) -> tuple[dict[str, Any], str, list[str]]:
    if isinstance(value, dict):
        return dict(value), json.dumps(value, ensure_ascii=False), []
    if not isinstance(value, str) or not value.strip():
        return {}, "", ["plan_candidate_requires_plan_payload"]
    try:
        parsed = json.loads(value)
    except Exception:
        return {}, value, ["invalid_plan_payload_json"]
    if not isinstance(parsed, dict):
        return {}, value, ["plan_payload_must_be_object"]
    return parsed, value, []


def _plan_payload_action_family(payload: dict[str, Any]) -> str:
    return str(payload.get("action_family") or payload.get("actionFamily") or "").strip()


def _plan_payload_target_view(payload: dict[str, Any]) -> str | None:
    target_view = str(payload.get("target_view") or payload.get("targetView") or "").strip()
    return target_view or None


def resolve_plan_confirmation_candidate(
    confirmation_candidate: dict[str, Any] | None,
) -> PlanConfirmationCandidateResolution:
    if not isinstance(confirmation_candidate, dict):
        return PlanConfirmationCandidateResolution(
            blocking_reasons=["missing_plan_confirmation_candidate"],
        )

    reasons: list[str] = []
    plan_payload, plan_payload_text, payload_reasons = _parse_plan_confirmation_payload(
        confirmation_candidate.get("plan_payload") or confirmation_candidate.get("planPayload")
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
        target_view=_plan_payload_target_view(plan_payload),
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
    )


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
                "planPayload": resolution.plan_payload,
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
    compact = _compact_text(user_prompt)
    if not pending_turn_looks_apply_then_new_request(user_prompt, "intent_change"):
        return ApplyThenGeneratePlanCompiledSource(
            blocking_reasons=["prompt_not_apply_then_generate_plan"],
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
    if "出方案" not in compact:
        summary = f"{summary}\n\n本次要求：{goal}"
    confirmation_candidate = {
        "action_family": "generate_plan",
        "user_goal": goal,
        "summary": summary,
        "plan_payload": json.dumps(plan_payload, ensure_ascii=False),
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
        candidate_payload = candidate.get("planPayload")
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


def explicit_fix_proposal_target_scope_from_result(result: dict[str, Any] | None) -> FixProposalTargetScope:
    if not isinstance(result, dict):
        return FixProposalTargetScope()
    strategies = normalize_fix_proposal_target_strategies(
        result.get("target_strategies")
        or result.get("targetStrategies")
        or []
    )
    issue_codes = normalize_fix_proposal_target_issue_codes(
        result.get("target_issue_codes")
        or result.get("targetIssueCodes")
        or []
    )
    return FixProposalTargetScope(
        target_strategies=strategies,
        target_issue_codes=issue_codes,
        explicit=bool(strategies or issue_codes),
    )


def semantic_decision_fix_proposal_target_scope(
    decision: Any,
    *,
    allowed_action_families: set[str],
    confidence_threshold: float,
) -> FixProposalTargetScope:
    action_family = str(getattr(decision, "actionFamily", "") or "").strip()
    if action_family not in allowed_action_families:
        return FixProposalTargetScope()
    try:
        confidence = float(getattr(decision, "confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < confidence_threshold:
        return FixProposalTargetScope()
    strategies = normalize_fix_proposal_target_strategies(
        getattr(decision, "targetStrategies", []) or []
    )
    issue_codes = normalize_fix_proposal_target_issue_codes(
        getattr(decision, "targetIssueCodes", []) or []
    )
    return FixProposalTargetScope(
        target_strategies=strategies,
        target_issue_codes=issue_codes,
        explicit=bool(strategies or issue_codes),
    )


def resolve_fix_proposal_target_scope_precheck(
    latest_plan_result: dict[str, Any] | None,
) -> FixProposalTargetScopeResolution:
    if not isinstance(latest_plan_result, dict):
        return FixProposalTargetScopeResolution(
            source="missing_result",
            blocking_reasons=["missing_latest_plan_result"],
        )
    explicit_scope = explicit_fix_proposal_target_scope_from_result(latest_plan_result)
    if explicit_scope.explicit:
        return FixProposalTargetScopeResolution(
            target_strategies=explicit_scope.target_strategies,
            target_issue_codes=explicit_scope.target_issue_codes,
            explicit=True,
            source="explicit_result_scope",
        )
    facts = latest_plan_result.get("facts") if isinstance(latest_plan_result.get("facts"), dict) else {}
    if not ready_fix_proposals(facts):
        return FixProposalTargetScopeResolution(
            source="no_ready_fix_proposal",
            blocking_reasons=["missing_ready_fix_proposal"],
        )
    if selected_fix_proposal_id(latest_plan_result, facts):
        return FixProposalTargetScopeResolution(source="selected_proposal_id")
    return FixProposalTargetScopeResolution(
        needs_semantic_decision=True,
        source="semantic_decision_required",
    )


def resolve_fix_proposal_target_scope_from_decision(
    decision: Any,
    *,
    allowed_action_families: set[str],
    confidence_threshold: float,
) -> FixProposalTargetScopeResolution:
    scope = semantic_decision_fix_proposal_target_scope(
        decision,
        allowed_action_families=allowed_action_families,
        confidence_threshold=confidence_threshold,
    )
    if not scope.explicit:
        return FixProposalTargetScopeResolution(source="semantic_decision_no_scope")
    return FixProposalTargetScopeResolution(
        target_strategies=scope.target_strategies,
        target_issue_codes=scope.target_issue_codes,
        explicit=True,
        source="semantic_decision_scope",
    )


def _fix_proposal_source_issue_codes(proposal: dict[str, Any]) -> set[str]:
    return {
        str(code or "").strip()
        for code in (proposal.get("source_check_codes") or proposal.get("sourceCheckCodes") or [])
        if str(code or "").strip()
    }


def filter_target_issue_codes_for_fix_proposals(
    issue_codes: list[str],
    context: dict[str, Any] | None,
) -> list[str]:
    available: set[str] = set()
    fix_facts = {}
    if isinstance(context, dict):
        raw_fix_facts = context.get("fixProposals") or context.get("fix_proposals")
        fix_facts = raw_fix_facts if isinstance(raw_fix_facts, dict) else {}
    proposals = fix_facts.get("proposals") if isinstance(fix_facts.get("proposals"), list) else []
    for proposal in proposals:
        if isinstance(proposal, dict):
            available.update(_fix_proposal_source_issue_codes(proposal))
    if not available:
        return normalize_fix_proposal_target_issue_codes(issue_codes)
    result: list[str] = []
    for code in normalize_fix_proposal_target_issue_codes(issue_codes):
        if code in available:
            result.append(code)
    return result


def semantic_decision_target_issue_codes_for_context(
    decision: Any,
    *,
    allowed_action_families: set[str],
    confidence_threshold: float,
    target_strategies: list[str],
    context: dict[str, Any] | None,
) -> list[str]:
    scope = semantic_decision_fix_proposal_target_scope(
        decision,
        allowed_action_families=allowed_action_families,
        confidence_threshold=confidence_threshold,
    )
    if not scope.explicit:
        return []
    if (
        target_strategies
        and scope.target_strategies
        and not (set(target_strategies) & set(scope.target_strategies))
    ):
        return []
    return filter_target_issue_codes_for_fix_proposals(scope.target_issue_codes, context)


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


def runtime_fix_proposal_confirmation_source_from_result(
    result: dict[str, Any] | None,
    *,
    plan_payload: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None
    action_family = str(result.get("action_family") or "").strip()
    result_kind = str(result.get("result_kind") or "").strip()
    if action_family != "preview_fix_proposal" or result_kind != "fix_proposal_preview":
        return None
    payload = plan_payload if isinstance(plan_payload, dict) else {}
    target_strategies = normalize_fix_proposal_target_strategies(
        payload.get("target_strategies")
        or payload.get("targetStrategies")
        or result.get("target_strategies")
        or result.get("targetStrategies")
        or []
    )
    target_issue_codes = normalize_fix_proposal_target_issue_codes(
        payload.get("target_issue_codes")
        or payload.get("targetIssueCodes")
        or result.get("target_issue_codes")
        or result.get("targetIssueCodes")
        or []
    )
    facts = result.get("facts") if isinstance(result.get("facts"), dict) else {}
    selected_id = selected_fix_proposal_id(result, facts)
    ready_match = select_ready_fix_proposal(
        facts,
        selected_proposal_id=selected_id,
        target_strategies=target_strategies,
        target_issue_codes=target_issue_codes,
    )
    if ready_match is None and not (target_strategies or target_issue_codes):
        return None
    normalized = result
    if target_strategies and "target_strategies" not in normalized and "targetStrategies" not in normalized:
        normalized = dict(normalized)
        normalized["target_strategies"] = target_strategies
    if target_issue_codes and "target_issue_codes" not in normalized and "targetIssueCodes" not in normalized:
        normalized = dict(normalized)
        normalized["target_issue_codes"] = target_issue_codes
    if target_strategies or target_issue_codes:
        normalized = dict(normalized)
        normalized["target_match_empty"] = (
            select_ready_fix_proposal(
                facts,
                target_strategies=target_strategies,
                target_issue_codes=target_issue_codes,
            )
            is None
        )
    return normalized


def select_ready_fix_proposal_for_compiled_source(
    facts: dict[str, Any] | None,
    *,
    selected_proposal_id: str = "",
    target_strategies: set[str] | list[str] | tuple[str, ...] | None = None,
    target_issue_codes: set[str] | list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any] | None:
    normalized_strategies = normalize_fix_proposal_target_strategies(target_strategies)
    normalized_issue_codes = normalize_fix_proposal_target_issue_codes(target_issue_codes)
    if selected_proposal_id:
        return select_ready_fix_proposal(facts, selected_proposal_id=selected_proposal_id)
    ready = ready_fix_proposals(facts)
    if normalized_strategies or normalized_issue_codes:
        matching = filter_ready_fix_proposals_by_target_scope(
            ready,
            normalized_strategies,
            normalized_issue_codes,
        )
        if len(matching) == 1:
            return matching[0]
        return None
    if len(ready) == 1:
        return ready[0]
    return None


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


def select_fix_proposal_candidate_for_runtime(
    latest_plan_result: dict[str, Any],
    *,
    target_strategies: set[str] | list[str] | tuple[str, ...] | None = None,
    target_issue_codes: set[str] | list[str] | tuple[str, ...] | None = None,
    target_scope_explicit: bool = False,
) -> FixProposalSelectionResult:
    facts = latest_plan_result.get("facts") if isinstance(latest_plan_result.get("facts"), dict) else {}
    selected_id = selected_fix_proposal_id(latest_plan_result, facts)
    normalized_strategies = normalize_fix_proposal_target_strategies(target_strategies)
    normalized_issue_codes = normalize_fix_proposal_target_issue_codes(target_issue_codes)
    if selected_id:
        selected_proposal = select_ready_fix_proposal(facts, selected_proposal_id=selected_id)
        return FixProposalSelectionResult(
            proposal=selected_proposal,
            selected_proposal_id=selected_id,
            target_strategies=normalized_strategies,
            target_issue_codes=normalized_issue_codes,
            blocking_reasons=[] if selected_proposal is not None else ["selected_fix_proposal_not_ready_or_missing"],
        )
    if target_scope_explicit and not normalized_strategies and not normalized_issue_codes:
        return FixProposalSelectionResult(
            target_match_empty=True,
            blocking_reasons=["explicit_target_scope_without_supported_target"],
        )
    if normalized_strategies or normalized_issue_codes:
        matching = filter_ready_fix_proposals_by_target_scope(
            ready_fix_proposals(facts),
            normalized_strategies,
            normalized_issue_codes,
        )
        if not matching:
            return FixProposalSelectionResult(
                target_strategies=normalized_strategies,
                target_issue_codes=normalized_issue_codes,
                target_match_empty=True,
                blocking_reasons=["no_ready_fix_proposal_for_target_scope"],
            )
        if len(matching) == 1:
            return FixProposalSelectionResult(
                proposal=matching[0],
                selected_proposal_id=proposal_id(matching[0]),
                target_strategies=normalized_strategies,
                target_issue_codes=normalized_issue_codes,
            )
        return FixProposalSelectionResult(
            target_strategies=normalized_strategies,
            target_issue_codes=normalized_issue_codes,
            blocking_reasons=["ambiguous_ready_fix_proposal_for_target_scope"],
        )
    proposal = select_ready_fix_proposal_for_compiled_source(facts)
    if proposal is None:
        return FixProposalSelectionResult(
            blocking_reasons=["missing_unique_ready_fix_proposal"],
        )
    return FixProposalSelectionResult(
        proposal=proposal,
        selected_proposal_id=proposal_id(proposal),
    )


def compile_runtime_review_fix_source(
    *,
    session_id: str,
    latest_plan_result: dict[str, Any],
    target_strategies: set[str] | list[str] | tuple[str, ...] | None = None,
    target_issue_codes: set[str] | list[str] | tuple[str, ...] | None = None,
    target_scope_explicit: bool = False,
) -> RuntimeReviewFixCompiledSource:
    if not isinstance(latest_plan_result, dict):
        return RuntimeReviewFixCompiledSource(
            blocking_reasons=["missing_latest_plan_result"],
        )
    facts = latest_plan_result.get("facts") if isinstance(latest_plan_result.get("facts"), dict) else {}
    fix_facts = facts.get("fix_proposals") if isinstance(facts.get("fix_proposals"), dict) else {}
    selection = select_fix_proposal_candidate_for_runtime(
        latest_plan_result,
        target_strategies=target_strategies,
        target_issue_codes=target_issue_codes,
        target_scope_explicit=target_scope_explicit,
    )
    if selection.proposal is None:
        return RuntimeReviewFixCompiledSource(
            selection=selection,
            target_match_empty=selection.target_match_empty,
            blocking_reasons=list(selection.blocking_reasons or ["missing_review_fix_proposal"]),
        )
    source_version_guard = _as_int(
        fix_facts.get("source_version_guard")
        or fix_facts.get("sourceVersionGuard")
        or latest_plan_result.get("source_backend_version")
        or latest_plan_result.get("sourceBackendVersion")
        or latest_plan_result.get("planning_version")
        or latest_plan_result.get("planningVersion")
    )
    if source_version_guard <= 0:
        return RuntimeReviewFixCompiledSource(
            proposal=selection.proposal,
            selection=selection,
            target_match_empty=selection.target_match_empty,
            blocking_reasons=["missing_source_version_guard"],
        )
    proposal_source = str(
        fix_facts.get("proposal_source")
        or fix_facts.get("proposalSource")
        or "review_check"
    ).strip() or "review_check"
    summary = str(
        selection.proposal.get("summary")
        or selection.proposal.get("impact")
        or selection.proposal.get("title")
        or "确认处理这条方案提醒"
    ).strip()
    compiled = compile_review_fix_proposal(
        session_id=session_id,
        proposal=selection.proposal,
        source_version_guard=source_version_guard,
        proposal_source=proposal_source,
        summary=summary,
    )
    return RuntimeReviewFixCompiledSource(
        proposal=selection.proposal,
        compiled=compiled,
        selection=selection,
        source_version_guard=source_version_guard,
        proposal_source=proposal_source,
        target_match_empty=selection.target_match_empty,
    )
