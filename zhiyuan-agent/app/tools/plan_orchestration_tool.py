from __future__ import annotations

import json
from typing import Any, Literal

from pydantic_ai import RunContext

from app.agent.context import RequestContext
from app.domain.school_major_ref_resolver import resolve_school_major_ref
from app.tools.plan_context_tool import _collect_plan_context_inputs_model
from app.tools.plan_orchestration_models import PlanActionPlan, PlanAtomicAction, PlanReviewIssueTarget
from app.tools.review_issue_registry import get_review_issue_rule


_PLAN_DEPENDENT_ACTIONS = {
    "analyze_adjustment",
    "preview_compensation",
    "add_units",
    "remove_units",
    "move_unit",
    "move_ordered_unit",
    "replace_units",
    "remove_ordered_unit",
    "sort_ordered_plan",
    "regenerate_order",
    "apply_compensation",
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
    "apply_compensation",
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


_REVIEW_ISSUE_TEXT_ALIASES: dict[str, tuple[str, ...]] = {
    "high_tuition": (
        "高收费",
        "收费高",
        "收费太高",
        "学费高",
        "学费太高",
        "学费偏高",
        "太贵",
        "贵的",
        "费用高",
        "费用太高",
        "费用偏高",
        "预算压力",
    ),
    "cooperative_program": ("中外合作", "合作办学", "中外合办", "合作项目"),
    "admission_limit": ("限报", "受限", "报不了", "体检限制", "色弱", "色盲", "视力限制"),
    "special_enrollment": ("特殊类型", "专项", "地方专项", "国家专项", "高校专项"),
}

_REVIEW_ISSUE_REMOVE_ALIASES = ("去掉", "去除", "删除", "删掉", "移出", "剔除", "拿掉", "踢掉")
_REVIEW_ISSUE_REPLACE_ALIASES = ("替换", "换成", "换掉", "改成")
_REVIEW_ISSUE_HANDLE_ALIASES = ("处理", "解决", "清理")
_REVIEW_ISSUE_READ_ONLY_GUARDS = (
    "先别动",
    "别动方案",
    "不要动方案",
    "不动方案",
    "先别改",
    "别改方案",
    "不要改方案",
    "不改方案",
)

_SORT_FIELD_TEXT_MARKERS: dict[str, tuple[str, ...]] = {
    "admissionRatio": ("录取率", "概率", "冲稳保", "稳妥", "稳一点", "风险"),
    "schoolRank": ("院校层次", "学校层次", "院校排名", "学校排名", "好学校", "学校好", "层次"),
    "finalScore": ("推荐系数", "推荐分", "推荐度", "推荐排序", "综合推荐"),
}
_EXPLICIT_SORT_FIELD_TEXT_MARKERS: dict[str, tuple[str, ...]] = {
    "admissionRatio": ("录取率", "录取概率"),
    "schoolRank": ("院校层次", "学校层次", "院校排名", "学校排名"),
    "finalScore": ("推荐系数", "推荐分", "推荐度", "推荐排序", "综合推荐"),
}
_RANGE_MOVE_MARKERS = (
    "往前",
    "前挪",
    "提前",
    "提到前",
    "放前",
    "靠前",
    "排前",
    "往上",
    "上移",
)


def _compact_user_goal_text(user_goal: str) -> str:
    return "".join(str(user_goal or "").strip().split()).lower()


def _infer_review_issue_mutation_action(user_goal: str) -> str | None:
    text = _compact_user_goal_text(user_goal)
    if not text or any(marker in text for marker in _REVIEW_ISSUE_READ_ONLY_GUARDS):
        return None
    if any(marker in text for marker in _REVIEW_ISSUE_REPLACE_ALIASES):
        return "replace_units"
    if any(marker in text for marker in _REVIEW_ISSUE_REMOVE_ALIASES):
        return "remove_units"
    return None


def _review_issue_mutation_requested(user_goal: str) -> bool:
    text = _compact_user_goal_text(user_goal)
    if not text or any(marker in text for marker in _REVIEW_ISSUE_READ_ONLY_GUARDS):
        return False
    if _infer_review_issue_mutation_action(user_goal):
        return True
    return any(_compact_user_goal_text(marker) in text for marker in _REVIEW_ISSUE_HANDLE_ALIASES)


def _infer_review_issue_code_from_goal(
    user_goal: str,
    review_issues: list[dict[str, Any]],
) -> str | None:
    """Recover a missing review_issue_code for known item-removal issues.

    This is a narrow compatibility guard for the old direct plan_next_action
    contract: the main model should pass review_issue_code explicitly, but can
    occasionally call review_plan for a mutation request.  The guard only
    matches labels/aliases of current review issues or registered item-removal
    issues and refuses ambiguous matches.
    """
    text = _compact_user_goal_text(user_goal)
    if not text:
        return None

    matched_codes: list[str] = []
    for issue in review_issues:
        if str(issue.get("scope_kind") or "").strip() != "item_removal":
            continue
        code = str(issue.get("code") or "").strip()
        if not code:
            continue
        labels = [
            str(issue.get("label") or "").strip(),
            str(issue.get("summary") or "").strip(),
            *_REVIEW_ISSUE_TEXT_ALIASES.get(code, ()),
        ]
        aliases = [alias for alias in labels if alias]
        if any(_compact_user_goal_text(alias) in text for alias in aliases):
            matched_codes.append(code)

    unique_codes = list(dict.fromkeys(matched_codes))
    if len(unique_codes) == 1:
        return unique_codes[0]
    if unique_codes:
        return None

    registry_matches: list[str] = []
    for code, aliases in _REVIEW_ISSUE_TEXT_ALIASES.items():
        rule = get_review_issue_rule(code)
        if rule is None or rule.scope_kind != "item_removal":
            continue
        candidates = (rule.label, *(aliases or ()))
        if any(_compact_user_goal_text(alias) in text for alias in candidates if alias):
            registry_matches.append(code)
    unique_registry_matches = list(dict.fromkeys(registry_matches))
    return unique_registry_matches[0] if len(unique_registry_matches) == 1 else None


def _recover_missing_review_issue_mutation(
    *,
    action_family: str,
    review_issue_code: str | None,
    user_goal: str,
    review_issues: list[dict[str, Any]],
) -> tuple[str, str | None]:
    if review_issue_code:
        return action_family, review_issue_code
    if action_family not in {"review_plan", "preview_compensation", "remove_units", "replace_units"}:
        return action_family, review_issue_code
    mutation_action = _infer_review_issue_mutation_action(user_goal)
    if mutation_action is None:
        return action_family, review_issue_code
    inferred_code = _infer_review_issue_code_from_goal(user_goal, review_issues)
    if not inferred_code:
        return action_family, review_issue_code
    return mutation_action, inferred_code


def _sort_field_supported_by_goal(sort_field: str | None, user_goal: str) -> bool:
    field = str(sort_field or "").strip()
    if not field:
        return False
    text = _compact_user_goal_text(user_goal)
    if not text:
        return True
    markers = _SORT_FIELD_TEXT_MARKERS.get(field, ())
    return any(_compact_user_goal_text(marker) in text for marker in markers if marker)


def _infer_explicit_sort_field_from_goal(user_goal: str) -> str | None:
    text = _compact_user_goal_text(user_goal)
    if not text:
        return None
    for field, markers in _EXPLICIT_SORT_FIELD_TEXT_MARKERS.items():
        if any(_compact_user_goal_text(marker) in text for marker in markers if marker):
            return field
    return None


def _looks_like_range_move_goal_without_sort_basis(user_goal: str) -> bool:
    text = _compact_user_goal_text(user_goal)
    if not text:
        return False
    return any(_compact_user_goal_text(marker) in text for marker in _RANGE_MOVE_MARKERS)


def _guard_sort_action_misused_for_range_move(
    action_family: str,
    sort_field: str | None,
    user_goal: str,
) -> tuple[str, str | None, list[str]]:
    """Prevent vague range moves from becoming arbitrary recommendation sorts."""
    if action_family != "sort_ordered_plan":
        return action_family, sort_field, []
    if not sort_field:
        return action_family, sort_field, []
    if _sort_field_supported_by_goal(sort_field, user_goal):
        return action_family, sort_field, []
    if not _looks_like_range_move_goal_without_sort_basis(user_goal):
        return action_family, sort_field, []
    return (
        "query_ordered",
        None,
        [
            "用户是在要求把某个地域、院校或专业范围往前挪，不是指定排序维度；不能默认按推荐系数、录取率或院校层次重排。",
            "需要先读取当前方案里该范围是否存在，并请用户确认具体移动范围或目标位置。",
        ],
    )


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


def _infer_school_major_refs_from_goal(ctx: RunContext[RequestContext], user_goal: str) -> list[str]:
    resolution = resolve_school_major_ref(user_goal, getattr(ctx.deps, "batch", None) or "01")
    if not resolution.can_query or resolution.ambiguous:
        return []
    school = resolution.school_keywords[0]
    major = resolution.major_keywords[0]
    return [f"{school}的{major}"] if school and major else []


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
    if action_family in {"query_draft", "query_ordered", "query_candidates", "analyze_adjustment", "preview_compensation"}:
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
        "preview_compensation",
        "add_units",
        "remove_units",
        "move_unit",
        "move_ordered_unit",
        "replace_units",
        "remove_ordered_unit",
        "sort_ordered_plan",
        "regenerate_order",
        "apply_compensation",
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
    sort_field = sort_field or _infer_explicit_sort_field_from_goal(user_goal)
    if action_family == "sort_ordered_plan" and sort_field:
        base_filters["sort_field"] = sort_field
    filters = dict(base_filters)
    sort_guard_rationale: list[str] = []
    action_family, sort_field, sort_guard_rationale = _guard_sort_action_misused_for_range_move(
        action_family,
        sort_field,
        user_goal,
    )
    if action_family != "sort_ordered_plan":
        filters.pop("sort_field", None)
    elif sort_field:
        filters["sort_field"] = sort_field
    recovered_action_family, recovered_review_issue_code = _recover_missing_review_issue_mutation(
        action_family=action_family,
        review_issue_code=review_issue_code,
        user_goal=user_goal,
        review_issues=review_issues,
    )
    if recovered_review_issue_code:
        if recovered_action_family != action_family:
            action_family = recovered_action_family  # type: ignore[assignment]
        review_issue_code = recovered_review_issue_code
        if current_stage == "review" and action_family != "review_plan":
            current_stage = None
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
        mutation_requested = _review_issue_mutation_requested(user_goal)
        if scope_kind == "item_removal":
            if action_family in {"remove_units", "replace_units"} and not mutation_requested:
                action_family = "review_plan"
            elif action_family == "replace_units" and not replacement_requested:
                action_family = "remove_units"
            elif action_family not in {"remove_units", "replace_units"} and default_action_family and mutation_requested:
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
    if action_family == "replace_units" and (volunteer_ids or review_issue_target is not None):
        filters = _infer_replace_filters_from_profile(ctx, filters)
    if action_family == "add_units" and not volunteer_ids and not _has_selection_scope(filters):
        volunteer_ids = _infer_school_major_refs_from_goal(ctx, user_goal)
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
        "preview_compensation",
        "review_plan",
    }
    if action_family in {"generate_plan", "sort_ordered_plan", "regenerate_order", "apply_compensation", "replace_units"}:
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
        "apply_compensation",
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
                preview_summary = f"会先移出当前审查命中的整批{review_issue_target.label}项，再按新的筛选条件补入候选，并在执行后重新审查整体结构。"
            else:
                preview_summary = "会先移出指定志愿，再按新的筛选条件补入候选，并在执行后重新审查整体结构。"
        elif action_family == "apply_compensation":
            preview_summary = "会应用当前补偿建议，并同步刷新排序与审查结果。"
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
    rationale.extend(sort_guard_rationale)
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
        "preview_compensation",
        "add_units",
        "remove_units",
        "move_unit",
        "move_ordered_unit",
        "replace_units",
        "remove_ordered_unit",
        "sort_ordered_plan",
        "regenerate_order",
        "apply_compensation",
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
    )
    return json.dumps(model.model_dump(), ensure_ascii=False)
