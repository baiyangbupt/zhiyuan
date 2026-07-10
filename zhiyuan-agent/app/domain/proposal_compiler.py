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



def _contains_any(compact: str, markers: tuple[str, ...]) -> bool:
    return any(marker in compact for marker in markers)


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
            "还没有生成可确认的调整预览",
            "没有生成可确认的调整预览",
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
            marker in compact
            for marker in (
                "还没有生成可执行的调整内容",
                "没有生成可执行的调整内容",
                "还没有生成可确认的调整预览",
                "没有生成可确认的调整预览",
            )
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
