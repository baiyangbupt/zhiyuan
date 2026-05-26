from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic_ai import RunContext

from app.agent.context import RequestContext
from app.tools.plan_context_tool import _collect_plan_context_inputs_model
from app.tools.plan_orchestration_models import PlanActionPlan, PlanAtomicAction, PlanReviewIssueTarget
from app.tools.review_issue_registry import match_review_issue_code_from_goal


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
    "pin_unit",
    "unpin_unit",
    "replace_units",
    "remove_ordered_unit",
    "sort_ordered_plan",
    "regenerate_order",
    "apply_compensation",
}

_UNIT_POSITION_REF_RE = re.compile(r"第\s*\d+\s*(?:个)?(?:专业组|志愿组|组)")


# --- Deprecated: 以下关键词匹配函数将在 IntentFrame 完整接入后移除 (see ActionResolver) ---


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


def _is_plan_filled_to_target(context_inputs: object) -> bool:
    ordered_count = int(getattr(context_inputs, "ordered_count", 0) or 0)
    target_count = int(getattr(context_inputs, "target_count", 0) or 0)
    if ordered_count <= 0 or target_count <= 0:
        return False
    return ordered_count >= target_count


def _context_review_issues(context_inputs: object) -> list[dict[str, Any]]:
    issues = getattr(context_inputs, "review_issues", []) or []
    return issues if isinstance(issues, list) else []


def _infer_sort_preview_label_and_direction(user_goal: str, filters: dict[str, Any] | None = None) -> tuple[str, str]:
    filters = filters or {}
    raw_field = str(
        filters.get("sort_field")
        or filters.get("sortField")
        or filters.get("field")
        or ""
    ).strip()
    goal_text = user_goal or ""
    joined = f"{raw_field} {goal_text}"
    if any(token in joined for token in ("schoolRank", "school_rank", "schoolLevel", "school_level", "院校层次", "学校层次", "院校排名", "好学校")):
        return "院校层次", "排名靠前的排在前面"
    if any(token in joined for token in ("finalScore", "final_score", "recommendationScore", "recommendation_score", "推荐系数")):
        return "推荐系数", "推荐系数高的排在前面"
    return "录取率", "录取率低的排在前面"


def _find_review_issue_by_code(review_issues: list[dict[str, Any]], code: str | None) -> dict[str, Any] | None:
    normalized = str(code or "").strip()
    if not normalized:
        return None
    for issue in review_issues:
        if str(issue.get("code") or "").strip() == normalized:
            return issue
    return None


def _contains_narrowing_scope(text: str) -> bool:
    compact = str(text or "").strip()
    return any(token in compact for token in ("大学", "学院", "学校", "专业组", "校区", "@", "第"))


def _goal_requests_replacement(text: str) -> bool:
    compact = str(text or "").strip()
    return any(token in compact for token in ("换成", "替换成", "补回", "补上", "补入", "保持", "补齐", "凑满"))


def _goal_explicitly_requests_reorder(text: str) -> bool:
    compact = str(text or "").strip()
    return any(
        token in compact
        for token in (
            "重排",
            "重新排",
            "重新排序",
            "排一排",
            "排一下",
            "顺一下",
            "弄顺",
            "理一下顺序",
        )
    )


def _goal_mentions_major_group_unit(text: str) -> bool:
    compact = str(text or "").strip()
    return any(token in compact for token in ("专业组", "这一组", "整组", "院校专业组"))


def _goal_requests_adjustment_analysis(text: str) -> bool:
    compact = str(text or "").strip()
    return any(
        token in compact
        for token in (
            "怎么调",
            "怎么优化",
            "更合理",
            "更稳",
            "稳一点",
            "更保守",
            "保守一点",
            "风险低一点",
            "降风险",
            "按这个思路",
            "按更稳的思路",
            "弄一版",
            "优化一下",
        )
    )


def _goal_requests_stability_fill_preview(text: str) -> bool:
    compact = str(text or "").strip()
    return any(
        token in compact
        for token in (
            "更稳",
            "稳一点",
            "保底",
            "更保守",
            "风险低一点",
            "补稳",
            "可确认预览",
            "先给我一版",
        )
    )


def _goal_requests_structural_rebalance(text: str) -> bool:
    compact = str(text or "").strip()
    return (
        ("别动总数" in compact or "总数不变" in compact or "保持总数" in compact)
        and (
            "保区" in compact
            or "压冲区" in compact
            or "本地保底" in compact
            or "本省保底" in compact
        )
    )


def _goal_explicitly_requests_regeneration(text: str) -> bool:
    compact = str(text or "").strip()
    return any(
        token in compact
        for token in (
            "重新生成",
            "重生成",
            "重新出一版",
            "重新给我一版",
            "覆盖当前方案",
            "覆盖掉当前方案",
        )
    )


def _normalize_adjustment_action_family(
    action_family: str,
    user_goal: str,
    context_inputs: object,
) -> str:
    normalized_action_family = str(action_family or "").strip()
    if (
        normalized_action_family == "generate_plan"
        and _has_existing_plan(context_inputs)
        and not _goal_explicitly_requests_regeneration(user_goal)
        and _goal_requests_adjustment_analysis(user_goal)
    ):
        return "analyze_adjustment"
    if (
        normalized_action_family == "preview_compensation"
        and not _is_plan_filled_to_target(context_inputs)
        and _goal_requests_stability_fill_preview(user_goal)
    ):
        return "add_units"
    if normalized_action_family == "regenerate_order" and _goal_requests_structural_rebalance(user_goal):
        return "replace_units"
    if normalized_action_family == "preview_compensation" and _is_plan_filled_to_target(context_inputs):
        return "analyze_adjustment"
    if (
        normalized_action_family == "regenerate_order"
        and not _goal_explicitly_requests_reorder(user_goal)
        and _goal_requests_adjustment_analysis(user_goal)
    ):
        return "analyze_adjustment"
    return normalized_action_family


def _build_missing_inputs(
    action_family: str,
    volunteer_ids: list[str] | None,
    unit_ids: list[str] | None,
    target_position: int | None,
    filters: dict[str, str],
    review_issue_target: PlanReviewIssueTarget | None = None,
    user_goal: str = "",
) -> list[str]:
    missing: list[str] = []
    has_unit_position_ref = bool(_UNIT_POSITION_REF_RE.search(str(user_goal or "")))
    if action_family == "remove_units" and not volunteer_ids and review_issue_target is None:
        missing.append("volunteer_ids")
    if action_family == "move_unit":
        if not volunteer_ids:
            missing.append("volunteer_id")
        if target_position is None:
            missing.append("target_position")
    if action_family == "move_ordered_unit":
        if not unit_ids and not has_unit_position_ref:
            missing.append("unit_ids")
        if target_position is None:
            missing.append("target_position")
    if action_family == "remove_ordered_unit" and not unit_ids and not has_unit_position_ref:
        missing.append("unit_ids")
    if action_family == "add_units" and not volunteer_ids and not _has_selection_scope(filters):
        missing.append("selection_scope")
    if action_family == "replace_units":
        if not volunteer_ids and review_issue_target is None:
            missing.append("volunteer_ids")
        if not _has_selection_scope(filters):
            missing.append("replacement_scope")
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


def _infer_add_filters_for_stability(
    ctx: RunContext[RequestContext],
    context_inputs: object,
    filters: dict[str, str],
) -> dict[str, str]:
    inferred = dict(filters)
    if not str(inferred.get("tier") or "").strip():
        inferred["tier"] = "保"
    if not str(inferred.get("province_keyword") or "").strip():
        preferred_regions = list(getattr(context_inputs, "positive_regions", []) or [])
        for candidate in ("北京", "天津", "河北"):
            if candidate in preferred_regions:
                inferred["province_keyword"] = candidate
                break

    profile = getattr(ctx.deps, "init_profile", None)
    if profile is not None:
        major_level2 = [value for value in getattr(profile.major, "level2", []) if str(value or "").strip()]
        if major_level2 and str(inferred.get("major_tags") or "").strip() in {"", "[]"}:
            inferred["major_tags"] = json.dumps(major_level2, ensure_ascii=False)
    return inferred


def _infer_replace_filters_for_structural_rebalance(
    ctx: RunContext[RequestContext],
    context_inputs: object,
    filters: dict[str, str],
) -> dict[str, str]:
    inferred = dict(filters)
    if not str(inferred.get("province_keyword") or "").strip():
        preferred_regions = list(getattr(context_inputs, "positive_regions", []) or [])
        for candidate in ("北京", "天津", "河北"):
            if candidate in preferred_regions:
                inferred["province_keyword"] = candidate
                break
    if not str(inferred.get("tier") or "").strip():
        inferred["tier"] = "保"
    profile = getattr(ctx.deps, "init_profile", None)
    if profile is not None:
        major_level2 = [value for value in getattr(profile.major, "level2", []) if str(value or "").strip()]
        if major_level2 and str(inferred.get("major_tags") or "").strip() in {"", "[]"}:
            inferred["major_tags"] = json.dumps(major_level2, ensure_ascii=False)
    return inferred


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
        "pin_unit",
        "unpin_unit",
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
    target_position: int | None = None,
    tier: str | None = None,
    province_keyword: str | None = None,
    school_keyword: str | None = None,
    major_keyword: str | None = None,
    school_tags: list[str] | None = None,
    major_tags: list[str] | None = None,
    sort_field: str | None = None,
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
        "sort_field": sort_field or "",
        "limit": str(limit),
    }
    filters = dict(base_filters)
    review_issue_target: PlanReviewIssueTarget | None = None
    if _goal_mentions_major_group_unit(user_goal):
        if action_family == "move_unit":
            action_family = "move_ordered_unit"  # type: ignore[assignment]
        elif action_family == "remove_units":
            action_family = "remove_ordered_unit"  # type: ignore[assignment]
    matched_review_issue = _find_review_issue_by_code(
        review_issues,
        match_review_issue_code_from_goal(user_goal, review_issues),
    )
    if matched_review_issue:
        scope_mode: Literal["full_issue", "narrowed_issue", "explicit_items"] = "full_issue"
        if volunteer_ids:
            scope_mode = "explicit_items"
        elif _contains_narrowing_scope(user_goal) or target_position is not None:
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
        replacement_requested = _goal_requests_replacement(user_goal) or _has_selection_scope(base_filters)
        if scope_kind == "item_removal":
            if action_family == "replace_units" and not replacement_requested:
                action_family = "remove_units"
            elif action_family not in {"remove_units", "replace_units"} and default_action_family:
                action_family = default_action_family  # type: ignore[assignment]
        elif scope_kind == "structural":
            if action_family in {"add_units", "remove_units", "move_unit", "pin_unit", "unpin_unit", "replace_units"} and default_action_family:
                action_family = default_action_family  # type: ignore[assignment]
        elif scope_kind == "informational" and action_family in {"remove_units", "replace_units"}:
            action_family = "review_plan"
    action_family = _normalize_adjustment_action_family(action_family, user_goal, context_inputs)
    if action_family == "replace_units" and (volunteer_ids or review_issue_target is not None):
        filters = _infer_replace_filters_from_profile(ctx, filters)
    elif action_family == "replace_units" and _goal_requests_structural_rebalance(user_goal):
        filters = _infer_replace_filters_for_structural_rebalance(ctx, context_inputs, filters)
    elif action_family == "add_units" and _goal_requests_stability_fill_preview(user_goal):
        filters = _infer_add_filters_for_stability(ctx, context_inputs, filters)
    missing_inputs = _build_missing_inputs(
        action_family,
        volunteer_ids,
        unit_ids,
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
        "pin_unit",
        "unpin_unit",
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
        "pin_unit",
        "unpin_unit",
        "replace_units",
        "remove_ordered_unit",
        "sort_ordered_plan",
    }:
        atomic_actions.append(
            PlanAtomicAction(
                action_type=action_family,
                volunteer_ids=volunteer_ids or [],
                unit_ids=unit_ids or [],
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
            field_label, direction_text = _infer_sort_preview_label_and_direction(user_goal, filters)
            preview_summary = (
                f"会按{field_label}重新排序当前方案，{direction_text}。"
                "排序会实际改变方案顺序和导出顺序，并让审查状态进入待重新审查。"
            )
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
        elif action_family == "pin_unit":
            preview_summary = "新版工作台暂不提供固定/锁定志愿入口；如果要稳定位置，建议改用移动到指定位置或方案排序。"
        elif action_family == "unpin_unit":
            preview_summary = "新版工作台暂不提供固定/锁定志愿入口；当前无需取消固定。"
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
        "pin_unit",
        "unpin_unit",
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
    target_position: int | None = None,
    tier: str | None = None,
    province_keyword: str | None = None,
    school_keyword: str | None = None,
    major_keyword: str | None = None,
    school_tags: list[str] | None = None,
    major_tags: list[str] | None = None,
    sort_field: str | None = None,
    limit: int = 5,
    user_confirmed: bool = False,
) -> str:
    """根据用户目标和现有状态输入生成 Plan 动作计划。

    对移动/删除/加入学校+专业这类变更请求，不需要先查询真实 volunteerId。
    `volunteer_ids` 可以直接填写用户原始引用（如“青岛电影学院的新闻学”、
    “湖北工程学院.计算机科学与技术”、“广西师大统计”），后续执行层会解析真实 ID；
    若无法唯一定位，执行层会返回澄清，不应为了定位而先调用 query_volunteer_plan。
    """
    model = await _plan_next_action_model(
        ctx,
        user_goal=user_goal,
        action_family=action_family,
        current_stage=current_stage,
        volunteer_ids=volunteer_ids,
        unit_ids=unit_ids,
        target_position=target_position,
        tier=tier,
        province_keyword=province_keyword,
        school_keyword=school_keyword,
        major_keyword=major_keyword,
        school_tags=school_tags,
        major_tags=major_tags,
        sort_field=sort_field,
        limit=limit,
        user_confirmed=user_confirmed,
    )
    return json.dumps(model.model_dump(), ensure_ascii=False)
