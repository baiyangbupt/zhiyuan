from __future__ import annotations

import json
from typing import Any, Literal

from pydantic_ai import RunContext

from app.agent.context import RequestContext
from app.models.intent_frame import ConstraintIntentType, PlanGoalConfidence, PlanGoalType
from app.tools.plan_context_tool import _collect_plan_context_inputs_model
from app.tools.plan_goal_resolution import attach_goal_entity_resolutions, scope_entity_type, scope_value_list
from app.tools.plan_orchestration_models import (
    CompositePlanProposal,
    LinkedRepairProposal,
    PlanActionPlan,
    PlanAtomicAction,
    PlanDecisionReference,
    PlanGoal,
    PlanReviewIssueTarget,
    build_plan_goal_intent_updates,
    plan_goal_requires_scope,
    resolve_plan_goal_type,
)
from app.tools.plan_user_goal_fix_proposal import (
    build_user_goal_fix_proposal_req_from_plan_goal,
    linked_repair_proposal_from_backend,
)
from app.tools.review_issue_registry import get_review_issue_rule
from app.util.internal_client import generate_user_goal_planning_fix_proposals as _generate_user_goal_fix_proposals_request


_PLAN_DEPENDENT_ACTIONS = {
    "analyze_adjustment",
    "preview_fix_proposal",
    "add_units",
    "remove_units",
    "move_unit",
    "move_ordered_unit",
    "replace_units",
    "remove_ordered_unit",
    "sort_ordered_plan",
    "regenerate_order",
    "review_plan",
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
}


def _has_selection_scope(filters: dict[str, str]) -> bool:
    for key, value in filters.items():
        if key == "limit":
            continue
        if not str(value or "").strip():
            continue
        if key in {"school_tags", "major_tags"} and str(value).strip() == "[]":
            continue
        return True
    return False


def _has_narrow_sort_scope(filters: dict[str, str]) -> bool:
    """A global sort action must not carry regional/school/major filters."""
    for key, value in filters.items():
        if key in {"limit", "sort_field", "preserve_count"}:
            continue
        if not str(value or "").strip():
            continue
        if key in {"school_tags", "major_tags"} and str(value).strip() == "[]":
            continue
        return True
    return False


def _has_existing_plan(context_inputs: object) -> bool:
    return bool(
        int(getattr(context_inputs, "draft_count", 0) or 0) > 0
        or int(getattr(context_inputs, "ordered_count", 0) or 0) > 0
    )


def _infer_intent_relation(summary: str) -> Literal["support", "conflict", "mixed", "unknown"]:
    if "冲突" in summary or "排除" in summary:
        if "命中偏好" in summary or "贴近" in summary:
            return "mixed"
        return "conflict"
    if "命中偏好" in summary or "贴近" in summary or "发展方向" in summary:
        return "support"
    return "unknown"


def _normalize_scope_values(values: Any) -> list[str]:
    if isinstance(values, list):
        return [str(item or "").strip() for item in values if str(item or "").strip()]
    value = str(values or "").strip()
    return [value] if value else []


def _append_goal_scope(scopes: list[dict[str, Any]], entity_type: str, values: Any) -> None:
    normalized_values = _normalize_scope_values(values)
    if not normalized_values:
        return
    scopes.append({"entity_type": entity_type, "values": normalized_values})


def _derive_goal_scopes_from_structured_args(
    *,
    source_major_names: list[str] | None,
    province_keyword: str | None,
    school_keyword: str | None,
    major_keyword: str | None,
    school_tags: list[str] | None,
    major_tags: list[str] | None,
    review_issue_code: str | None,
) -> list[dict[str, Any]]:
    scopes: list[dict[str, Any]] = []
    _append_goal_scope(scopes, "major", source_major_names)
    _append_goal_scope(scopes, "major", major_keyword)
    _append_goal_scope(scopes, "major_tag", major_tags)
    _append_goal_scope(scopes, "school", school_keyword)
    _append_goal_scope(scopes, "school_tag", school_tags)
    _append_goal_scope(scopes, "region", province_keyword)
    _append_goal_scope(scopes, "risk", review_issue_code)
    return scopes


def _build_plan_goal_metadata(
    *,
    user_goal: str,
    plan_goal_type: PlanGoalType | None,
    constraint_intent_type: ConstraintIntentType,
    plan_goal_confidence: PlanGoalConfidence,
    goal_target_scopes: list[dict[str, Any]] | None,
    goal_negative_scopes: list[dict[str, Any]] | None,
    source_major_names: list[str] | None,
    province_keyword: str | None,
    school_keyword: str | None,
    major_keyword: str | None,
    school_tags: list[str] | None,
    major_tags: list[str] | None,
    review_issue_code: str | None,
    batch: str | None,
) -> tuple[PlanGoal | None, list[dict[str, Any]]]:
    goal_type = resolve_plan_goal_type(plan_goal_type, constraint_intent_type)
    if goal_type is None:
        return None, []

    derived_scopes = _derive_goal_scopes_from_structured_args(
        source_major_names=source_major_names,
        province_keyword=province_keyword,
        school_keyword=school_keyword,
        major_keyword=major_keyword,
        school_tags=school_tags,
        major_tags=major_tags,
        review_issue_code=review_issue_code,
    )
    target_scopes = list(goal_target_scopes or [])
    negative_scopes = list(goal_negative_scopes or [])
    if not target_scopes and not negative_scopes:
        if goal_type == "exclude_scope":
            negative_scopes = derived_scopes
        else:
            target_scopes = derived_scopes

    has_scope = bool(target_scopes or negative_scopes)
    needs_clarification = plan_goal_requires_scope(goal_type) and not has_scope
    clarification_questions = (
        ["请补充要调整的专业、院校、地域或风险范围。"]
        if needs_clarification
        else []
    )
    plan_goal = PlanGoal(
        goal_type=goal_type,
        user_original_text=user_goal,
        target_scopes=target_scopes,
        negative_scopes=negative_scopes,
        confidence=plan_goal_confidence,
        needs_clarification=needs_clarification,
        clarification_questions=clarification_questions,
    )
    attach_goal_entity_resolutions(plan_goal, batch)
    return plan_goal, build_plan_goal_intent_updates(plan_goal)


def _scope_values_for_action(
    scopes: list[dict[str, Any]],
) -> dict[str, list[str]]:
    values_by_type: dict[str, list[str]] = {}
    for scope in scopes:
        if not isinstance(scope, dict):
            continue
        entity_type = scope_entity_type(scope)
        bucket = values_by_type.setdefault(entity_type, [])
        for value in scope_value_list(scope):
            if value and value not in bucket:
                bucket.append(value)
    return values_by_type


def _filters_from_scope_values(values_by_type: dict[str, list[str]], *, limit: int) -> dict[str, Any]:
    filters: dict[str, Any] = {"limit": str(limit)}
    if values_by_type.get("major"):
        filters["major_keyword"] = values_by_type["major"][0]
    if values_by_type.get("school"):
        filters["school_keyword"] = values_by_type["school"][0]
    if values_by_type.get("region"):
        filters["province_keyword"] = values_by_type["region"][0]
    if values_by_type.get("tag"):
        filters["major_tags"] = list(values_by_type["tag"])
    return filters


def _build_remove_action_from_scope(
    *,
    scopes: list[dict[str, Any]],
    user_goal: str,
    limit: int,
) -> PlanAtomicAction | None:
    values_by_type = _scope_values_for_action(scopes)
    filters = _filters_from_scope_values(values_by_type, limit=limit)
    source_major_names = list(values_by_type.get("major") or [])
    if not source_major_names and not any(key in filters for key in ("school_keyword", "province_keyword", "major_tags")):
        return None
    return PlanAtomicAction(
        action_type="remove_units",
        source_major_names=source_major_names,
        filters=filters,
        reason=user_goal,
    )


def _build_add_action_from_scope(
    *,
    scopes: list[dict[str, Any]],
    user_goal: str,
    limit: int,
) -> PlanAtomicAction | None:
    values_by_type = _scope_values_for_action(scopes)
    filters = _filters_from_scope_values(values_by_type, limit=max(1, limit))
    if not any(key in filters for key in ("major_keyword", "school_keyword", "province_keyword", "major_tags")):
        return None
    return PlanAtomicAction(
        action_type="add_units",
        filters=filters,
        reason=user_goal,
    )


def _build_composite_plan_actions(
    *,
    plan_goal: PlanGoal | None,
    user_goal: str,
    limit: int,
) -> tuple[list[PlanAtomicAction], list[str]]:
    if plan_goal is None or plan_goal.needs_clarification:
        return [], []
    if plan_goal.goal_type == "exclude_scope":
        action = _build_remove_action_from_scope(
            scopes=plan_goal.negative_scopes,
            user_goal=user_goal,
            limit=limit,
        )
        return ([action] if action else []), []
    if plan_goal.goal_type == "must_include_scope":
        action = _build_add_action_from_scope(
            scopes=plan_goal.target_scopes,
            user_goal=user_goal,
            limit=1,
        )
        return ([action] if action else []), []
    if plan_goal.goal_type == "only_keep_scope":
        return [], [
            "当前已能把“只保留”的范围写入待确认要求；但自动移出所有非目标范围还需要先读取当前方案并做反向范围校验，本轮不直接生成可执行删除动作。",
        ]
    return [], []


def _scope_reference_payload(scope: dict[str, Any]) -> dict[str, Any]:
    return {
        "entity_type": scope_entity_type(scope),
        "values": scope_value_list(scope),
    }


def _append_scope_decision_references(
    references: list[PlanDecisionReference],
    *,
    scopes: list[dict[str, Any]],
    dimension: str,
    label: str,
    weight_hint: Literal["hard", "high", "medium", "low", "context"],
) -> None:
    for scope in scopes:
        if not isinstance(scope, dict):
            continue
        payload = _scope_reference_payload(scope)
        if not payload["values"]:
            continue
        references.append(
            PlanDecisionReference(
                source="explicit_user_goal",
                dimension=dimension,
                label=label,
                value=payload,
                weight_hint=weight_hint,
                applies_to=list(payload["values"]),
            )
        )


def _build_decision_references(
    *,
    plan_goal: PlanGoal | None,
    intent_updates: list[dict[str, Any]],
    context_inputs: object,
) -> list[PlanDecisionReference]:
    """Build structured comparison signals for composite plan previews.

    The references intentionally describe evidence only. Selection, preview and
    apply permissions remain in execution and confirmation layers.
    """
    references: list[PlanDecisionReference] = []
    if plan_goal is not None:
        positive_weight: Literal["hard", "high", "medium", "low", "context"] = (
            "hard"
            if plan_goal.goal_type in {"only_keep_scope", "must_include_scope"}
            else "medium"
        )
        negative_weight: Literal["hard", "high", "medium", "low", "context"] = (
            "hard" if plan_goal.goal_type == "exclude_scope" else "medium"
        )
        _append_scope_decision_references(
            references,
            scopes=plan_goal.target_scopes,
            dimension="target_scope",
            label="用户明确想保留或补入的范围",
            weight_hint=positive_weight,
        )
        _append_scope_decision_references(
            references,
            scopes=plan_goal.negative_scopes,
            dimension="negative_scope",
            label="用户明确想避开或降低优先级的范围",
            weight_hint=negative_weight,
        )
        _append_scope_decision_references(
            references,
            scopes=plan_goal.structure_targets,
            dimension="structure_target",
            label="用户明确提出的结构目标",
            weight_hint="high",
        )
        _append_scope_decision_references(
            references,
            scopes=plan_goal.quality_guards,
            dimension="quality_guard",
            label="用户不希望明显牺牲的边界",
            weight_hint="high",
        )
    if intent_updates:
        references.append(
            PlanDecisionReference(
                source="confirmed_intent",
                dimension="pending_intent_update",
                label="确认后会写入后续报考参考的内容",
                value=intent_updates,
                weight_hint="hard",
            )
        )

    relation_lines = [
        str(line or "").strip()
        for line in (getattr(context_inputs, "relation_lines", []) or [])
        if str(line or "").strip()
    ]
    if relation_lines:
        references.append(
            PlanDecisionReference(
                source="current_plan",
                dimension="intent_relation",
                label="当前方案与已记录偏好/要求的关系",
                value=relation_lines[:5],
                weight_hint="context",
            )
        )
    review_lines = [
        str(line or "").strip()
        for line in (getattr(context_inputs, "review_issue_summary_lines", []) or [])
        if str(line or "").strip()
    ]
    if review_lines:
        references.append(
            PlanDecisionReference(
                source="review_rule",
                dimension="risk_or_warning",
                label="当前审查发现的风险或提醒",
                value=review_lines[:5],
                weight_hint="high",
            )
        )

    references.append(
        PlanDecisionReference(
            source="system_recommendation",
            dimension="priority_metrics",
            label="系统用于比较志愿优先级的参考指标",
            value=[
                "推荐系数",
                "录取率",
                "冲稳保层级",
                "院校层次",
                "专业热度",
                "意向匹配",
            ],
            weight_hint="context",
            evidence={
                "note": "这些指标用于排序、替换和取舍说明；已确认的报考条件仍优先于推荐系数。",
            },
        )
    )
    return references


def _build_composite_proposal(
    *,
    plan_goal: PlanGoal | None,
    intent_updates: list[dict[str, Any]],
    plan_actions: list[PlanAtomicAction],
    linked_fix_proposals: list[Any] | None,
    decision_references: list[PlanDecisionReference],
    feasibility: str,
    requires_confirmation: bool,
    planning_version: int,
    impact_summary: list[str],
    tradeoffs: list[str],
    missing_inputs: list[str],
) -> CompositePlanProposal | None:
    if plan_goal is None:
        return None
    normalized_feasibility = feasibility
    if plan_goal.needs_clarification:
        normalized_feasibility = "needs_clarification"
    elif missing_inputs:
        normalized_feasibility = "preview_only"
    elif requires_confirmation:
        normalized_feasibility = "ready"
    proposal = CompositePlanProposal(
        source_version=planning_version,
        goal=plan_goal,
        intent_updates=intent_updates,
        plan_actions=plan_actions,
        linked_fix_proposals=list(linked_fix_proposals or []),
        decision_references=decision_references,
        feasibility=normalized_feasibility,
        impact_summary=impact_summary,
        tradeoffs=tradeoffs,
        requires_confirmation=requires_confirmation and normalized_feasibility == "ready",
        post_apply_validation_plan=[
            "执行后重新读取当前方案",
            "执行后重新审查风险和提醒",
        ] if requires_confirmation and normalized_feasibility == "ready" else [],
    )
    return proposal


async def _generate_linked_user_goal_fix_proposals(
    ctx: RunContext[RequestContext],
    plan_goal: PlanGoal | None,
    planning_version: int,
) -> tuple[list[LinkedRepairProposal], list[str]]:
    if plan_goal is None or plan_goal.needs_clarification:
        return [], []
    if plan_goal.goal_type not in {"only_keep_scope", "must_include_scope", "exclude_scope"}:
        return [], []
    payload = build_user_goal_fix_proposal_req_from_plan_goal(
        plan_goal,
        planning_version,
        context={
            "entityResolutions": [
                item.model_dump()
                for item in plan_goal.entity_resolutions
            ],
        },
        evidence_source="plan_goal",
    )
    if not payload:
        return [], []
    try:
        result = await _generate_user_goal_fix_proposals_request(
            1,
            ctx.deps.sessionid,
            payload,
        )
    except Exception:
        return [], ["暂时没有拿到后端调整预览，先保留结构化目标，不自动修改方案。"]
    if result.get("code") != 0:
        return [], ["暂时没有拿到后端调整预览，先保留结构化目标，不自动修改方案。"]
    data = result.get("data") or {}
    if not isinstance(data, dict):
        return [], ["后端调整预览格式异常，先保留结构化目标，不自动修改方案。"]
    proposals = [
        proposal
        for proposal in (
            linked_repair_proposal_from_backend(
                item,
                default_source=str(data.get("proposalSource") or "user_goal"),
                default_source_version_guard=int(data.get("sourceVersionGuard") or planning_version or 0),
            )
            for item in (data.get("proposals") or [])
            if isinstance(item, dict)
        )
        if proposal is not None
    ]
    return proposals, []


def _context_review_issues(context_inputs: object) -> list[dict[str, Any]]:
    issues = getattr(context_inputs, "review_issues", []) or []
    return issues if isinstance(issues, list) else []


def _find_review_issue_by_code(review_issues: list[dict[str, Any]], code: str | None) -> dict[str, Any] | None:
    normalized = str(code or "").strip()
    if not normalized:
        return None
    for issue in review_issues:
        if str(issue.get("code") or "").strip() == normalized:
            return issue
    return None


def _review_issue_from_registry(code: str | None) -> dict[str, Any] | None:
    rule = get_review_issue_rule(code)
    if rule is None:
        return None
    return {
        "code": rule.code,
        "label": rule.label,
        "summary": rule.label,
        "scope_kind": rule.scope_kind,
        "default_action_family": rule.default_action_family,
        "affected_unit_count": 0,
        "affected_volunteer_count": 0,
        "scope_fingerprint": "",
    }


def _normalize_ordered_unit_action_family(
    *,
    action_family: str,
    volunteer_ids: list[str] | None,
    unit_ids: list[str] | None,
    source_position: int | None,
) -> tuple[str, list[str]]:
    """Prefer ordered-unit actions when the payload uses ordered-unit refs.

    This is intentionally based on structured tool arguments, not user text.
    A bare "第 N 个/第 N 位" in the plan workspace refers to the visible
    ordered unit.  In major-group mode that unit is a school-major group; in
    school-major mode it is usually one volunteer item.
    """
    has_volunteer_ref = bool(volunteer_ids)
    has_unit_ref = bool(unit_ids) or source_position is not None
    if action_family == "move_unit" and has_unit_ref and not has_volunteer_ref:
        return "move_ordered_unit", [
            "已按排序区展示单元处理位置引用：裸序号位置移动使用 ordered unit，不按单条志愿 ID 解析。"
        ]
    if action_family == "remove_units" and has_unit_ref and not has_volunteer_ref:
        return "remove_ordered_unit", [
            "已按排序区展示单元处理位置引用：裸序号删除使用 ordered unit，不按单条志愿 ID 解析。"
        ]
    return action_family, []


def _normalize_adjustment_action_family(
    action_family: str,
    user_goal: str,
    context_inputs: object,
) -> str:
    """Compatibility shim kept for older imports.

    Runtime action-family decisions must come from explicit tool arguments or
    typed intent fields. Do not infer or rewrite actions from user_goal text.
    """
    return str(action_family or "").strip()


def _build_missing_inputs(
    action_family: str,
    volunteer_ids: list[str] | None,
    unit_ids: list[str] | None,
    source_major_names: list[str] | None,
    source_position: int | None,
    target_position: int | None,
    filters: dict[str, str],
    review_issue_target: PlanReviewIssueTarget | None = None,
    user_goal: str = "",
) -> list[str]:
    missing: list[str] = []
    if (
        action_family == "remove_units"
        and not volunteer_ids
        and not source_major_names
        and not _has_selection_scope(filters)
        and review_issue_target is None
    ):
        missing.append("volunteer_ids")
    if action_family == "move_unit":
        if not volunteer_ids and source_position is None:
            missing.append("volunteer_id")
        if target_position is None:
            missing.append("target_position")
    if action_family == "move_ordered_unit":
        if not unit_ids and source_position is None:
            missing.append("unit_ids")
        if target_position is None:
            missing.append("target_position")
    if action_family == "remove_ordered_unit" and not unit_ids and source_position is None:
        missing.append("unit_ids")
    if action_family == "add_units" and not volunteer_ids and not _has_selection_scope(filters):
        missing.append("selection_scope")
    if action_family == "replace_units":
        if not volunteer_ids and review_issue_target is None:
            missing.append("volunteer_ids")
        if not _has_selection_scope(filters):
            missing.append("replacement_scope")
    if action_family == "sort_ordered_plan" and not str(filters.get("sort_field") or "").strip():
        missing.append("sort_field")
    return missing


def _infer_replace_filters_from_profile(ctx: RunContext[RequestContext], filters: dict[str, str]) -> dict[str, str]:
    if _has_selection_scope(filters):
        return filters
    profile = getattr(ctx.deps, "init_profile", None)
    if profile is None:
        return filters

    inferred = dict(filters)
    major_level2 = [value for value in getattr(profile.major, "level2", []) if str(value or "").strip()]
    if major_level2:
        inferred["major_tags"] = json.dumps(major_level2, ensure_ascii=False)
        return inferred

    major_level3 = [value for value in getattr(profile.major, "level3", []) if str(value or "").strip()]
    if major_level3 and not str(inferred.get("major_keyword") or "").strip():
        inferred["major_keyword"] = str(major_level3[0]).strip()
    return inferred


def _should_infer_replace_filters_from_profile(
    review_issue_target: PlanReviewIssueTarget | None,
) -> bool:
    # A full review issue such as "高收费/中外合作" needs an explicit
    # replacement direction from the user or backend fix proposals. Reusing
    # historical preferences here makes the preview look confirmed while the
    # actual replacement boundary was never stated.
    return review_issue_target is None


def _determine_stage(
    action_family: str,
    *,
    user_confirmed: bool,
    missing_inputs: list[str],
    current_stage: str | None,
) -> str:
    if current_stage in {"analyze", "preview", "apply", "review"}:
        if current_stage == "apply" and action_family in _MUTATING_ACTION_FAMILIES and not user_confirmed:
            return "analyze" if missing_inputs else "preview"
        return current_stage
    if action_family == "query_state":
        return "apply"
    if action_family in {"query_draft", "query_ordered", "query_candidates", "analyze_adjustment", "preview_fix_proposal"}:
        return "apply"
    if missing_inputs:
        return "analyze"
    if action_family == "review_plan":
        return "review"
    if user_confirmed:
        return "apply"
    return "preview"


async def _plan_next_action_model(
    ctx: RunContext[RequestContext],
    *,
    user_goal: str,
    action_family: Literal[
        "query_state",
        "query_draft",
        "query_ordered",
        "query_candidates",
        "generate_plan",
        "analyze_adjustment",
        "preview_fix_proposal",
        "add_units",
        "remove_units",
        "move_unit",
        "move_ordered_unit",
        "replace_units",
        "remove_ordered_unit",
        "sort_ordered_plan",
        "regenerate_order",
        "review_plan",
    ] = "query_state",
    current_stage: str | None = None,
    volunteer_ids: list[str] | None = None,
    unit_ids: list[str] | None = None,
    source_major_names: list[str] | None = None,
    source_position: int | None = None,
    target_position: int | None = None,
    sort_field: Literal["admissionRatio", "schoolRank", "finalScore"] | None = None,
    review_issue_code: str | None = None,
    review_issue_scope_mode: Literal["full_issue", "narrowed_issue", "explicit_items"] | None = None,
    tier: str | None = None,
    province_keyword: str | None = None,
    school_keyword: str | None = None,
    major_keyword: str | None = None,
    school_tags: list[str] | None = None,
    major_tags: list[str] | None = None,
    preserve_count: bool = False,
    limit: int = 5,
    user_confirmed: bool = False,
    plan_goal_type: PlanGoalType | None = None,
    constraint_intent_type: ConstraintIntentType = "default",
    plan_goal_confidence: PlanGoalConfidence = "medium",
    goal_target_scopes: list[dict[str, Any]] | None = None,
    goal_negative_scopes: list[dict[str, Any]] | None = None,
) -> PlanActionPlan:
    context_inputs = await _collect_plan_context_inputs_model(ctx)
    planning_summary = getattr(ctx.deps, "planning_summary", None)
    try:
        planning_version = int(getattr(planning_summary, "version", 0) or 0)
    except (TypeError, ValueError):
        planning_version = 0
    review_issues = _context_review_issues(context_inputs)
    base_filters = {
        "tier": tier or "",
        "province_keyword": province_keyword or "",
        "school_keyword": school_keyword or "",
        "major_keyword": major_keyword or "",
        "school_tags": json.dumps(school_tags or [], ensure_ascii=False),
        "major_tags": json.dumps(major_tags or [], ensure_ascii=False),
        "limit": str(limit),
    }
    if preserve_count:
        base_filters["preserve_count"] = "true"
    if action_family == "sort_ordered_plan" and sort_field:
        base_filters["sort_field"] = sort_field
    filters = dict(base_filters)
    sort_scope_rationale: list[str] = []
    if action_family == "sort_ordered_plan" and _has_narrow_sort_scope(base_filters):
        action_family = "query_ordered"
        filters.pop("sort_field", None)
        sort_scope_rationale = [
            "结构化参数里同时出现排序动作和局部筛选范围；当前排序只支持全方案排序，已先降为查看当前方案命中范围，避免误改全局顺序。",
        ]
    if action_family != "sort_ordered_plan":
        filters.pop("sort_field", None)
    elif sort_field:
        filters["sort_field"] = sort_field
    review_issue_target: PlanReviewIssueTarget | None = None
    matched_review_issue = _find_review_issue_by_code(review_issues, review_issue_code)
    if matched_review_issue is None:
        matched_review_issue = _review_issue_from_registry(review_issue_code)
    if matched_review_issue:
        scope_mode: Literal["full_issue", "narrowed_issue", "explicit_items"] = review_issue_scope_mode or "full_issue"
        if review_issue_scope_mode is None and volunteer_ids:
            scope_mode = "explicit_items"
        elif review_issue_scope_mode is None and (
            unit_ids
            or source_position is not None
            or target_position is not None
            or _has_selection_scope(base_filters)
        ):
            scope_mode = "narrowed_issue"
        review_issue_target = PlanReviewIssueTarget(
            code=str(matched_review_issue.get("code") or "").strip(),
            scope_mode=scope_mode,
            scope_fingerprint=str(matched_review_issue.get("scope_fingerprint") or "").strip(),
            label=str(matched_review_issue.get("label") or "").strip(),
            scope_kind=str(matched_review_issue.get("scope_kind") or "").strip(),
            default_action_family=str(matched_review_issue.get("default_action_family") or "").strip(),
            narrowed_refs=list(volunteer_ids or []) if scope_mode != "full_issue" else [],
            narrowed_filters={key: value for key, value in base_filters.items() if key != "limit" and str(value or "").strip()},
        )
        scope_kind = str(matched_review_issue.get("scope_kind") or "").strip()
        default_action_family = str(matched_review_issue.get("default_action_family") or "").strip()
        replacement_requested = _has_selection_scope(base_filters)
        if scope_kind == "item_replacement":
            if action_family == "replace_units" and not replacement_requested and default_action_family:
                action_family = default_action_family  # type: ignore[assignment]
            elif action_family not in {"review_plan", "remove_units", "replace_units"} and default_action_family:
                action_family = default_action_family  # type: ignore[assignment]
        elif scope_kind == "item_removal":
            if action_family == "replace_units" and not replacement_requested:
                action_family = "remove_units"
            elif action_family not in {"review_plan", "remove_units", "replace_units"} and default_action_family:
                action_family = default_action_family  # type: ignore[assignment]
        elif scope_kind == "structural":
            if action_family in {"add_units", "remove_units", "move_unit", "replace_units"} and default_action_family:
                action_family = default_action_family  # type: ignore[assignment]
        elif scope_kind == "informational" and action_family in {"remove_units", "replace_units"}:
            action_family = "review_plan"
    action_family = _normalize_adjustment_action_family(action_family, user_goal, context_inputs)
    action_family, ordered_unit_rationale = _normalize_ordered_unit_action_family(
        action_family=action_family,
        volunteer_ids=volunteer_ids,
        unit_ids=unit_ids,
        source_position=source_position,
    )
    if (
        action_family == "replace_units"
        and volunteer_ids
        and _should_infer_replace_filters_from_profile(review_issue_target)
    ):
        filters = _infer_replace_filters_from_profile(ctx, filters)
    missing_inputs = _build_missing_inputs(
        action_family,
        volunteer_ids,
        unit_ids,
        source_major_names,
        source_position,
        target_position,
        filters,
        review_issue_target=review_issue_target,
        user_goal=user_goal,
    )
    if action_family in _PLAN_DEPENDENT_ACTIONS and not _has_existing_plan(context_inputs):
        missing_inputs.append("existing_plan")
    stage = _determine_stage(
        action_family,
        user_confirmed=user_confirmed,
        missing_inputs=missing_inputs,
        current_stage=current_stage,
    )
    requires_confirmation = action_family not in {
        "query_state",
        "query_draft",
        "query_ordered",
        "query_candidates",
        "analyze_adjustment",
        "preview_fix_proposal",
        "review_plan",
    }
    if action_family in {"generate_plan", "sort_ordered_plan", "regenerate_order", "replace_units"}:
        requires_confirmation = True
    if stage == "analyze":
        requires_confirmation = False
    should_rerun_review = stage == "apply" and action_family in {
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
    should_refresh_workspace = stage in {"apply", "review"}
    atomic_actions: list[PlanAtomicAction] = []
    if action_family in {
        "query_candidates",
        "add_units",
        "remove_units",
        "move_unit",
        "move_ordered_unit",
        "replace_units",
        "remove_ordered_unit",
        "sort_ordered_plan",
    }:
        atomic_actions.append(
            PlanAtomicAction(
                action_type=action_family,
                volunteer_ids=volunteer_ids or [],
                unit_ids=unit_ids or [],
                source_major_names=source_major_names or [],
                source_position=source_position,
                target_position=target_position,
                filters={k: v for k, v in filters.items() if v},
                reason=user_goal,
                review_issue_target=review_issue_target,
            )
        )
    preview_summary = ""
    if stage == "preview":
        if action_family == "generate_plan":
            preview_summary = "会基于当前报考参考信息、约束和候选范围生成一版方案，并在执行后自动复审。"
        elif action_family == "regenerate_order":
            preview_summary = "会基于当前方案重新生成整体顺序，并在执行后自动复审。"
        elif action_family == "sort_ordered_plan":
            field_label = {
                "admissionRatio": "录取率",
                "schoolRank": "院校层次",
                "finalScore": "推荐系数",
            }.get(str(sort_field or "admissionRatio"), "录取率")
            preview_summary = f"会按{field_label}重新排序当前方案，排序会实际改变方案顺序和导出顺序，并让审查状态进入待重新审查。"
        elif action_family == "add_units":
            preview_summary = "会补入指定志愿或按条件补入候选，并同步刷新当前方案和审查结果。"
        elif action_family == "query_candidates":
            preview_summary = "会按当前条件读取候选机会，用于继续挑选或比较，不会直接改方案。"
        elif action_family == "remove_units":
            if review_issue_target and review_issue_target.scope_mode == "full_issue" and review_issue_target.label:
                preview_summary = f"会按当前审查命中的整批{review_issue_target.label}项执行移除，并在执行后重新审查整体结构。"
            else:
                preview_summary = "会从当前方案移出指定志愿，并在执行后重新审查整体结构。"
        elif action_family == "move_unit":
            preview_summary = "会调整指定志愿的位置，并在执行后重新审查整体结构。"
        elif action_family == "move_ordered_unit":
            preview_summary = "会整体移动指定专业组，组内专业顺序保持不变，并在执行后重新审查整体结构。"
        elif action_family == "remove_ordered_unit":
            preview_summary = "会从当前方案中删除指定专业组，组内专业会随专业组一并移出，并在执行后重新审查整体结构。"
        elif action_family == "replace_units":
            if review_issue_target and review_issue_target.scope_mode == "full_issue" and review_issue_target.label:
                preview_summary = f"会优先按当前审查命中的整批{review_issue_target.label}项生成替换预览，并在执行后重新审查整体结构。"
            else:
                preview_summary = "会先移出指定志愿，再按新的筛选条件补入候选，并在执行后重新审查整体结构。"
    rationale = [f"当前上下文：{context_inputs.summary}"]
    if matched_review_issue:
        label = str(matched_review_issue.get("label") or matched_review_issue.get("code") or "审查问题").strip()
        scope_kind = str(matched_review_issue.get("scope_kind") or "").strip()
        default_action_family = str(matched_review_issue.get("default_action_family") or "").strip()
        affected_unit_count = int(matched_review_issue.get("affected_unit_count") or 0)
        affected_volunteer_count = int(matched_review_issue.get("affected_volunteer_count") or 0)
        rationale.append(
            f"已匹配当前审查问题：{label}；类型={scope_kind}；默认动作={default_action_family or 'none'}；影响范围约 {affected_unit_count} 个专业组 / {affected_volunteer_count} 条志愿。"
        )
    if missing_inputs:
        rationale.append(f"缺少必要输入：{','.join(missing_inputs)}")
        if "existing_plan" in missing_inputs:
            rationale.append("当前还没有方案；不能审查、补齐、补稳、重排或局部调整。应先生成一版基础方案。")
    rationale.extend(sort_scope_rationale)
    rationale.extend(ordered_unit_rationale)
    if preview_summary:
        rationale.append(preview_summary)
    if matched_review_issue and str(matched_review_issue.get("scope_kind") or "").strip() == "structural":
        rationale.append("这个问题属于结构性问题，受影响条目主要用于定位上下文，不应直接当作删除清单。")
    if action_family == "replace_units" and volunteer_ids and "replacement_scope" not in missing_inputs:
        inferred_major_tags = str(filters.get("major_tags") or "").strip()
        inferred_major_keyword = str(filters.get("major_keyword") or "").strip()
        if inferred_major_tags and inferred_major_tags != "[]":
            rationale.append("未显式指定替换范围，默认按当前已记录的专业意向补入候选。")
        elif inferred_major_keyword:
            rationale.append("未显式指定替换范围，默认按当前已记录的专业方向补入候选。")
    plan_goal, intent_updates = _build_plan_goal_metadata(
        user_goal=user_goal,
        plan_goal_type=plan_goal_type,
        constraint_intent_type=constraint_intent_type,
        plan_goal_confidence=plan_goal_confidence,
        goal_target_scopes=goal_target_scopes,
        goal_negative_scopes=goal_negative_scopes,
        source_major_names=source_major_names,
        province_keyword=province_keyword,
        school_keyword=school_keyword,
        major_keyword=major_keyword,
        school_tags=school_tags,
        major_tags=major_tags,
        review_issue_code=review_issue_code,
        batch=getattr(ctx.deps, "batch", None),
    )
    if plan_goal and plan_goal.needs_clarification:
        rationale.extend(plan_goal.clarification_questions)
    composite_plan_actions, composite_tradeoffs = _build_composite_plan_actions(
        plan_goal=plan_goal,
        user_goal=user_goal,
        limit=limit,
    )
    linked_fix_proposals: list[LinkedRepairProposal] = []
    if plan_goal and not plan_goal.needs_clarification and _has_existing_plan(context_inputs):
        linked_fix_proposals, linked_warnings = await _generate_linked_user_goal_fix_proposals(
            ctx,
            plan_goal,
            planning_version,
        )
        rationale.extend(linked_warnings)
        if linked_fix_proposals:
            composite_tradeoffs.append("已基于当前方案和候选生成后端只读调整预览；这份预览不会自动执行。")
    decision_references = _build_decision_references(
        plan_goal=plan_goal,
        intent_updates=intent_updates,
        context_inputs=context_inputs,
    )
    feasibility = "needs_clarification" if plan_goal and plan_goal.needs_clarification else "preview_only"
    impact_summary = [
        line
        for line in [preview_summary, *getattr(plan_goal, "user_visible_entity_notes", [])]
        if str(line or "").strip()
    ]
    composite_proposal = _build_composite_proposal(
        plan_goal=plan_goal,
        intent_updates=intent_updates,
        plan_actions=composite_plan_actions,
        linked_fix_proposals=linked_fix_proposals,
        decision_references=decision_references,
        feasibility=feasibility,
        requires_confirmation=requires_confirmation and not missing_inputs,
        planning_version=planning_version,
        impact_summary=impact_summary,
        tradeoffs=composite_tradeoffs,
        missing_inputs=missing_inputs,
    )
    if composite_proposal and composite_proposal.feasibility == "needs_clarification":
        feasibility = "needs_clarification"
    elif composite_proposal and composite_proposal.feasibility == "ready":
        feasibility = "ready"
    return PlanActionPlan(
        stage=stage,  # type: ignore[arg-type]
        action_family=action_family,
        user_goal=user_goal,
        requires_confirmation=requires_confirmation,
        should_rerun_review=should_rerun_review,
        should_refresh_workspace=should_refresh_workspace,
        context_summary=context_inputs.summary,
        planning_version=planning_version,
        intent_relation=_infer_intent_relation(" ".join(context_inputs.relation_lines) + context_inputs.summary),
        missing_inputs=missing_inputs,
        rationale=rationale,
        atomic_actions=atomic_actions,
        composite_proposal=composite_proposal,
        preview_summary=preview_summary,
    )


async def plan_next_action(
    ctx: RunContext[RequestContext],
    user_goal: str,
    action_family: Literal[
        "query_state",
        "query_draft",
        "query_ordered",
        "query_candidates",
        "generate_plan",
        "analyze_adjustment",
        "preview_fix_proposal",
        "add_units",
        "remove_units",
        "move_unit",
        "move_ordered_unit",
        "replace_units",
        "remove_ordered_unit",
        "sort_ordered_plan",
        "regenerate_order",
        "review_plan",
    ] = "query_state",
    current_stage: str | None = None,
    volunteer_ids: list[str] | None = None,
    unit_ids: list[str] | None = None,
    source_major_names: list[str] | None = None,
    source_position: int | None = None,
    target_position: int | None = None,
    sort_field: Literal["admissionRatio", "schoolRank", "finalScore"] | None = None,
    review_issue_code: str | None = None,
    review_issue_scope_mode: Literal["full_issue", "narrowed_issue", "explicit_items"] | None = None,
    tier: str | None = None,
    province_keyword: str | None = None,
    school_keyword: str | None = None,
    major_keyword: str | None = None,
    school_tags: list[str] | None = None,
    major_tags: list[str] | None = None,
    preserve_count: bool = False,
    limit: int = 5,
    user_confirmed: bool = False,
    plan_goal_type: PlanGoalType | None = None,
    constraint_intent_type: ConstraintIntentType = "default",
    plan_goal_confidence: PlanGoalConfidence = "medium",
    goal_target_scopes: list[dict[str, Any]] | None = None,
    goal_negative_scopes: list[dict[str, Any]] | None = None,
) -> str:
    """根据用户目标和现有状态输入生成 Plan 动作计划。

    明确只读的当前方案状态查询、方案审查和调整分析不要调用本工具；
    直接调用 execute_plan_action，并传最小 PlanActionPlan JSON：
    {"stage":"apply","action_family":"query_state","user_goal":"用户原话","requires_confirmation":false}
    {"stage":"review","action_family":"review_plan","user_goal":"用户原话","requires_confirmation":false}
    {"stage":"apply","action_family":"analyze_adjustment","user_goal":"用户原话","requires_confirmation":false}
    本工具主要用于高副作用 preview、补偿/替换等复杂编排，或需要把自然语言位置/范围整理成结构化动作计划的场景。

    对移动/删除/加入学校+专业这类变更请求，不需要先查询真实 volunteerId。
    `volunteer_ids` 可以直接填写用户原始引用（如“青岛电影学院的新闻学”、
    “湖北工程学院.计算机科学与技术”、“广西师大统计”），后续执行层会解析真实 ID；
    若无法唯一定位，执行层会返回澄清，不应为了定位而先调用 query_volunteer_plan。

    对位置移动必须显式填写结构化参数：
    - 单条志愿移动：`action_family="move_unit"`，`volunteer_ids=["用户提到的学校+专业"]`，
    `target_position=N`。
    - 排序区裸序号移动：如果用户只说“第N个/第N位/第N条”而没有点名学校+专业，
      使用 `action_family="move_ordered_unit"`，显式填写 `source_position=N` 和
      `target_position=M`；执行层会按当前方案展示单元顺序解析。院校专业组模式下
      这个单元是专业组，专业+大学模式下通常是单条志愿。
    - 专业组整体移动：`action_family="move_ordered_unit"`，优先填写真实 `unit_ids`；
      如果用户只说“第N个专业组”，同样显式填写 `source_position=N` 和
      `target_position=M`，执行层会按当前专业组顺序解析。
    对单条志愿移动不要只把目标和位置写在 `user_goal` 里；缺少 `volunteer_ids`
    或 `target_position` 时，本工具会要求补充信息。按字段排序时必须显式填写
    `sort_field`：录取率=`admissionRatio`，院校层次=`schoolRank`，推荐系数=`finalScore`。
    替换操作如果要求“替换后数量不能减少/保持总数”，必须显式填写
    `preserve_count=True`，执行层才会先做候选容量预检。
    删除或替换操作如果用户要按源专业整体处理（例如“删掉方案里的汉语言文学”、
    “不想学会计/审计，把这些从方案里去掉”），必须显式填写
    `source_major_names=["汉语言文学"]` 或对应专业名列表；不要只把源范围写进
    `user_goal`。如果用户要按院校、地域或候选范围处理当前方案，使用结构化
    `school_keyword`、`province_keyword`、`major_keyword` 等字段承载范围。

    对复合目标不要靠 user_goal 文本推断。用户表达“只保留/至少要有/排除/优先”
    这类会同时影响方案和后续报考参考的诉求时，必须显式传
    `plan_goal_type` 或 `constraint_intent_type`，并用 `goal_target_scopes` /
    `goal_negative_scopes` 或已有结构化范围字段承载目标对象。本工具只把它们写入
    PlanGoal / intent_updates 预览元数据，不会直接写状态或执行 apply。
    """
    model = await _plan_next_action_model(
        ctx,
        user_goal=user_goal,
        action_family=action_family,
        current_stage=current_stage,
        volunteer_ids=volunteer_ids,
        unit_ids=unit_ids,
        source_major_names=source_major_names,
        source_position=source_position,
        target_position=target_position,
        sort_field=sort_field,
        review_issue_code=review_issue_code,
        review_issue_scope_mode=review_issue_scope_mode,
        tier=tier,
        province_keyword=province_keyword,
        school_keyword=school_keyword,
        major_keyword=major_keyword,
        school_tags=school_tags,
        major_tags=major_tags,
        preserve_count=preserve_count,
        limit=limit,
        user_confirmed=user_confirmed,
        plan_goal_type=plan_goal_type,
        constraint_intent_type=constraint_intent_type,
        plan_goal_confidence=plan_goal_confidence,
        goal_target_scopes=goal_target_scopes,
        goal_negative_scopes=goal_negative_scopes,
    )
    return json.dumps(model.model_dump(), ensure_ascii=False)
