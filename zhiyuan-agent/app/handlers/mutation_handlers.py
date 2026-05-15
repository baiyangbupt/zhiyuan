"""志愿增删改类 handler。

覆盖 action_family: add_units, remove_units, move_unit, pin_unit,
unpin_unit, replace_units, regenerate_order。
最复杂，涉及 volunteer_ref 解析和多步动作组合。
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic_ai import RunContext

from app.agent.context import RequestContext
from app.handlers.registry import register_handler
from app.tools.plan_orchestration_models import PlanActionPlan, PlanExecutionResult
from app.tools.planning_workflow_tool import (
    move_planning_ordered_item,
    pin_planning_ordered_item,
    remove_planning_ordered_items,
    select_planning_ordered_items,
    unpin_planning_ordered_item,
)
from app.tools.plan_execution_tool import (
    _count_ordered_units_for_ids,
    _candidate_ref_resolution_message,
    _goal_requests_replacement,
    _ordered_ref_resolution_message,
    _parse_filter_list,
    _preview_or_block_replace_by_candidate_capacity,
    _regenerate_ordered_plan,
    _replace_no_add_clarification,
    _resolve_ordered_volunteer_refs,
    _resolve_candidate_volunteer_refs,
    _resolve_review_issue_action_scope,
    _select_candidates_by_filters_into_plan,
    _should_preflight_replace_capacity,
    _structural_review_issue_guidance,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Handler 实现
# ---------------------------------------------------------------------------


def _contains_natural_ref_text(refs: list[str]) -> bool:
    return any(any(ord(char) > 127 for char in str(ref or "")) for ref in refs)


@register_handler("add_units")
async def handle_add_units(
    ctx: RunContext[RequestContext], plan: PlanActionPlan
) -> PlanExecutionResult:
    reply_focus = ["mutation_result", "plan_update"]
    next_step_hints = ["优先说明这次加入是否已同步到草稿/方案，再根据需要补充复审影响。"]
    atomic = plan.atomic_actions[0] if plan.atomic_actions else None
    ids = atomic.volunteer_ids if atomic else []
    affected_volunteer_ids: list[str] = []

    if ids:
        existing_ids: list[str] = []
        if _contains_natural_ref_text(ids):
            existing_ids, _ = await _resolve_ordered_volunteer_refs(ctx, ids)
        existing_id_set = set(existing_ids)
        resolved_ids, missing_refs = await _resolve_candidate_volunteer_refs(ctx, ids)
        resolved_ids = [volunteer_id for volunteer_id in resolved_ids if volunteer_id not in existing_id_set]
        if existing_ids and not resolved_ids and not missing_refs:
            refs_text = "、".join(ids[:5])
            state_summary = f"{refs_text} 已经在当前方案中，无需重复加入。"
            return PlanExecutionResult(
                applied=False,
                action_family="add_units",
                stage=plan.stage,
                result_kind="error",
                executed_actions=[{"action": "add_units", "volunteerIds": [], "requestedVolunteerRefs": ids, "alreadyInPlanIds": existing_ids}],
                affected_volunteer_ids=[],
                workspace_refresh_targets=[],
                context_summary=plan.context_summary,
                state_summary=state_summary,
                summary=state_summary,
                reply_focus=["already_in_plan"],
                next_step_hints=["告诉用户目标已经在方案中，不要说已新增。可提示当前位置或建议继续排序/调整。"],
            )
        if missing_refs or not resolved_ids:
            missing_text = "、".join(missing_refs[:5]) if missing_refs else "要加入的候选志愿"
            return PlanExecutionResult(
                applied=False,
                action_family="add_units",
                stage=plan.stage,
                result_kind="error",
                executed_actions=[],
                affected_volunteer_ids=[],
                workspace_refresh_targets=["candidate"],
                context_summary=plan.context_summary,
                state_summary=_candidate_ref_resolution_message(missing_text),
                summary=_candidate_ref_resolution_message(missing_text),
                reply_focus=["missing_inputs", "needs_candidate_selection"],
                next_step_hints=["先定位候选池里的真实 volunteerId，再执行加入方案。"],
            )
        state_summary = await select_planning_ordered_items(ctx, resolved_ids, source="plan_execution")
        affected_volunteer_ids.extend(resolved_ids)
    else:
        filters = atomic.filters if atomic else {}
        state_summary = await _select_candidates_by_filters_into_plan(
            ctx,
            tier=filters.get("tier") or None,
            province_keyword=filters.get("province_keyword") or None,
            school_keyword=filters.get("school_keyword") or None,
            major_keyword=filters.get("major_keyword") or None,
            school_tags=_parse_filter_list(filters.get("school_tags")),
            major_tags=_parse_filter_list(filters.get("major_tags")),
            limit=int(filters.get("limit") or 3),
        )

    return PlanExecutionResult(
        applied=True,
        action_family="add_units",
        stage=plan.stage,
        result_kind="mutation_result",
        executed_actions=[{"action": "add_units", "volunteerIds": affected_volunteer_ids, "requestedVolunteerRefs": ids}],
        affected_volunteer_ids=affected_volunteer_ids,
        workspace_refresh_targets=["draft", "ordered"],
        context_summary=plan.context_summary,
        state_summary=state_summary,
        summary=state_summary,
        reply_focus=reply_focus,
        next_step_hints=next_step_hints,
    )


@register_handler("remove_units")
async def handle_remove_units(
    ctx: RunContext[RequestContext], plan: PlanActionPlan
) -> PlanExecutionResult:
    reply_focus: list[str] = ["mutation_result", "plan_update"]
    next_step_hints: list[str] = ["优先说明这次移除后的数量或风险影响，再决定是否建议复审或补位。"]
    result_kind = "mutation_result"
    atomic = plan.atomic_actions[0]
    resolved_ids, missing_refs = await _resolve_ordered_volunteer_refs(ctx, atomic.volunteer_ids)
    expanded_ids, _, review_issue_target, review_issue = await _resolve_review_issue_action_scope(
        ctx, plan, resolved_ids,
    )
    effective_ids = expanded_ids or resolved_ids
    executed_actions: list[dict[str, object]] = []
    affected_volunteer_ids: list[str] = []

    if review_issue and str(review_issue.get("scope_kind") or "").strip() == "structural":
        result_kind = "error"
        state_summary, next_step_hints = _structural_review_issue_guidance(review_issue)
        workspace_targets = ["ordered", "review"]
        reply_focus = ["review_issue_structural"]
    else:
        ignore_missing_refs = bool(
            review_issue_target is not None
            and effective_ids
            and str(getattr(review_issue_target, "scope_mode", "") or "") in {"full_issue", "narrowed_issue"}
        )
        if (missing_refs and not ignore_missing_refs) or not effective_ids:
            missing_text = "、".join(missing_refs[:5]) if missing_refs else "要移除的志愿"
            result_kind = "error"
            state_summary = _ordered_ref_resolution_message(missing_text, "移除")
            workspace_targets = ["ordered"]
            reply_focus = ["missing_inputs", "needs_volunteer_selection"]
            next_step_hints = ["先定位当前方案里的真实 volunteerId，再执行移除。"]
        else:
            state_summary = await remove_planning_ordered_items(ctx, effective_ids)
            executed_actions.append(
                {
                    "action": "remove_units",
                    "volunteerIds": effective_ids,
                    "requestedVolunteerRefs": atomic.volunteer_ids,
                }
            )
            affected_volunteer_ids.extend(effective_ids)
            workspace_targets = ["ordered", "review"]

    return PlanExecutionResult(
        applied=(result_kind != "error" and plan.stage in {"apply", "review"}),
        action_family="remove_units",
        stage=plan.stage,
        result_kind=result_kind,
        executed_actions=executed_actions,
        affected_volunteer_ids=affected_volunteer_ids,
        workspace_refresh_targets=workspace_targets,
        context_summary=plan.context_summary,
        state_summary=state_summary,
        summary=state_summary,
        reply_focus=reply_focus,
        next_step_hints=next_step_hints,
    )


@register_handler("move_unit")
async def handle_move_unit(
    ctx: RunContext[RequestContext], plan: PlanActionPlan
) -> PlanExecutionResult:
    reply_focus: list[str] = ["mutation_result", "plan_update"]
    next_step_hints: list[str] = ["优先说明位置调整是否完成，再根据需要补充相邻梯度或复审影响。"]
    result_kind = "mutation_result"
    atomic = plan.atomic_actions[0]
    resolved_ids, missing_refs = await _resolve_ordered_volunteer_refs(ctx, atomic.volunteer_ids)
    executed_actions: list[dict[str, object]] = []
    affected_volunteer_ids: list[str] = []

    if missing_refs or not resolved_ids:
        missing_text = "、".join(missing_refs[:5]) if missing_refs else "要移动的志愿"
        result_kind = "error"
        state_summary = _ordered_ref_resolution_message(missing_text, "移动")
        workspace_targets = ["ordered"]
        reply_focus = ["missing_inputs", "needs_volunteer_selection"]
        next_step_hints = ["先定位当前方案里的真实 volunteerId，再执行位置调整。"]
    else:
        volunteer_id = resolved_ids[0]
        state_summary = await move_planning_ordered_item(ctx, volunteer_id, atomic.target_position or 1)
        executed_actions.append(
            {
                "action": "move_unit",
                "volunteerIds": [volunteer_id],
                "requestedVolunteerRefs": atomic.volunteer_ids,
                "targetPosition": atomic.target_position,
            }
        )
        affected_volunteer_ids.append(volunteer_id)
        workspace_targets = ["ordered", "review"]

    return PlanExecutionResult(
        applied=(result_kind != "error" and plan.stage in {"apply", "review"}),
        action_family="move_unit",
        stage=plan.stage,
        result_kind=result_kind,
        executed_actions=executed_actions,
        affected_volunteer_ids=affected_volunteer_ids,
        workspace_refresh_targets=workspace_targets,
        context_summary=plan.context_summary,
        state_summary=state_summary,
        summary=state_summary,
        reply_focus=reply_focus,
        next_step_hints=next_step_hints,
    )


@register_handler("pin_unit")
async def handle_pin_unit(
    ctx: RunContext[RequestContext], plan: PlanActionPlan
) -> PlanExecutionResult:
    reply_focus: list[str] = ["mutation_result", "plan_update", "pinned_unit"]
    next_step_hints: list[str] = ["优先说明固定位置是否完成，再根据需要补充复审影响。"]
    result_kind = "mutation_result"
    atomic = plan.atomic_actions[0]
    resolved_ids, missing_refs = await _resolve_ordered_volunteer_refs(ctx, atomic.volunteer_ids)
    executed_actions: list[dict[str, object]] = []
    affected_volunteer_ids: list[str] = []

    if missing_refs or not resolved_ids:
        missing_text = "、".join(missing_refs[:5]) if missing_refs else "要固定的志愿"
        result_kind = "error"
        state_summary = _ordered_ref_resolution_message(missing_text, "固定")
        workspace_targets = ["ordered"]
        reply_focus = ["missing_inputs", "needs_volunteer_selection"]
        next_step_hints = ["先定位当前方案里的真实 volunteerId，再执行固定位置。"]
    else:
        volunteer_id = resolved_ids[0]
        state_summary = await pin_planning_ordered_item(ctx, volunteer_id, atomic.target_position or 1)
        executed_actions.append(
            {
                "action": "pin_unit",
                "volunteerIds": [volunteer_id],
                "requestedVolunteerRefs": atomic.volunteer_ids,
                "targetPosition": atomic.target_position,
            }
        )
        affected_volunteer_ids.append(volunteer_id)
        workspace_targets = ["ordered", "review"]

    return PlanExecutionResult(
        applied=(result_kind != "error" and plan.stage in {"apply", "review"}),
        action_family="pin_unit",
        stage=plan.stage,
        result_kind=result_kind,
        executed_actions=executed_actions,
        affected_volunteer_ids=affected_volunteer_ids,
        workspace_refresh_targets=workspace_targets,
        context_summary=plan.context_summary,
        state_summary=state_summary,
        summary=state_summary,
        reply_focus=reply_focus,
        next_step_hints=next_step_hints,
    )


@register_handler("unpin_unit")
async def handle_unpin_unit(
    ctx: RunContext[RequestContext], plan: PlanActionPlan
) -> PlanExecutionResult:
    reply_focus: list[str] = ["mutation_result", "plan_update", "unpinned_unit"]
    next_step_hints: list[str] = ["优先说明取消固定是否完成，再根据需要补充复审影响。"]
    result_kind = "mutation_result"
    atomic = plan.atomic_actions[0]
    resolved_ids, missing_refs = await _resolve_ordered_volunteer_refs(ctx, atomic.volunteer_ids)
    executed_actions: list[dict[str, object]] = []
    affected_volunteer_ids: list[str] = []

    if missing_refs or not resolved_ids:
        missing_text = "、".join(missing_refs[:5]) if missing_refs else "要取消固定的志愿"
        result_kind = "error"
        state_summary = _ordered_ref_resolution_message(missing_text, "取消固定")
        workspace_targets = ["ordered"]
        reply_focus = ["missing_inputs", "needs_volunteer_selection"]
        next_step_hints = ["先定位当前方案里的真实 volunteerId，再执行取消固定。"]
    else:
        volunteer_id = resolved_ids[0]
        state_summary = await unpin_planning_ordered_item(ctx, volunteer_id)
        executed_actions.append(
            {
                "action": "unpin_unit",
                "volunteerIds": [volunteer_id],
                "requestedVolunteerRefs": atomic.volunteer_ids,
            }
        )
        affected_volunteer_ids.append(volunteer_id)
        workspace_targets = ["ordered", "review"]

    return PlanExecutionResult(
        applied=(result_kind != "error" and plan.stage in {"apply", "review"}),
        action_family="unpin_unit",
        stage=plan.stage,
        result_kind=result_kind,
        executed_actions=executed_actions,
        affected_volunteer_ids=affected_volunteer_ids,
        workspace_refresh_targets=workspace_targets,
        context_summary=plan.context_summary,
        state_summary=state_summary,
        summary=state_summary,
        reply_focus=reply_focus,
        next_step_hints=next_step_hints,
    )


@register_handler("replace_units")
async def handle_replace_units(
    ctx: RunContext[RequestContext], plan: PlanActionPlan
) -> PlanExecutionResult:
    reply_focus: list[str] = ["mutation_result", "plan_update", "replacement_result"]
    next_step_hints: list[str] = ["优先说明已替换哪些志愿、补入范围和复审影响，不要把替换说成单纯重排。"]
    result_kind = "mutation_result"
    atomic = plan.atomic_actions[0]
    filters = atomic.filters
    resolved_ids, missing_refs = await _resolve_ordered_volunteer_refs(
        ctx, atomic.volunteer_ids, broad_goal_text=plan.user_goal,
    )
    effective_ids, ordered_items, review_issue_target, review_issue = await _resolve_review_issue_action_scope(
        ctx, plan, resolved_ids,
    )
    executed_actions: list[dict[str, object]] = []
    affected_volunteer_ids: list[str] = []
    state_summary = ""

    if review_issue and str(review_issue.get("scope_kind") or "").strip() == "structural":
        result_kind = "error"
        state_summary, next_step_hints = _structural_review_issue_guidance(review_issue)
        workspace_targets = ["ordered", "review"]
        reply_focus = ["review_issue_structural"]
    elif (
        review_issue
        and str(review_issue.get("scope_kind") or "").strip() == "item_removal"
        and review_issue_target is not None
        and not _goal_requests_replacement(plan.user_goal)
    ):
        state_summary = await remove_planning_ordered_items(ctx, effective_ids)
        executed_actions.append(
            {
                "action": "remove_units",
                "requestedActionFamily": "replace_units",
                "volunteerIds": effective_ids,
                "requestedVolunteerRefs": atomic.volunteer_ids,
            }
        )
        affected_volunteer_ids.extend(effective_ids)
        workspace_targets = ["ordered", "review"]
    elif ((missing_refs or not resolved_ids) and review_issue_target is None) or not effective_ids:
        missing_text = "、".join(missing_refs[:5]) if missing_refs else "要替换的志愿"
        result_kind = "error"
        state_summary = _ordered_ref_resolution_message(missing_text, "替换")
        workspace_targets: list[str] = []
        reply_focus = ["missing_inputs", "needs_volunteer_selection"]
        next_step_hints = ["先定位当前方案里的真实 volunteerId，再执行替换。"]
    else:
        replacement_count = _count_ordered_units_for_ids(ordered_items, effective_ids) or len(effective_ids)
        if _should_preflight_replace_capacity(plan, effective_ids, review_issue_target):
            blocked_result = await _preview_or_block_replace_by_candidate_capacity(
                ctx,
                plan_model=plan,
                ordered_items=ordered_items,
                effective_ids=effective_ids,
                filters=filters,
                review_issue_target=review_issue_target,
                apply_message_prefix="这次我先不执行替换",
                preview_message_prefix="我先拦一下",
            )
            if blocked_result is not None:
                result_kind = blocked_result.result_kind
                state_summary = blocked_result.summary
                workspace_targets = ["ordered", "review"]
                reply_focus = list(blocked_result.reply_focus)
                next_step_hints = list(blocked_result.next_step_hints)
        if result_kind != "error":
            remove_summary = await remove_planning_ordered_items(ctx, effective_ids)
            add_summary = await _select_candidates_by_filters_into_plan(
                ctx,
                tier=filters.get("tier") or None,
                province_keyword=filters.get("province_keyword") or None,
                school_keyword=filters.get("school_keyword") or None,
                major_keyword=filters.get("major_keyword") or None,
                school_tags=_parse_filter_list(filters.get("school_tags")),
                major_tags=_parse_filter_list(filters.get("major_tags")),
                limit=replacement_count,
                exclude_current_units=review_issue_target is not None,
                replacement_issue_code=getattr(review_issue_target, "code", None),
            )
            state_summary = f"{remove_summary}\n\n替换补入结果：\n{add_summary}"
            clarification = _replace_no_add_clarification(add_summary)
            if clarification:
                state_summary = f"{state_summary}\n{clarification}"
            executed_actions.append(
                {
                    "action": "replace_units",
                    "removedVolunteerIds": effective_ids,
                    "requestedVolunteerRefs": atomic.volunteer_ids,
                    "filters": filters,
                }
            )
            affected_volunteer_ids.extend(effective_ids)
            workspace_targets = ["ordered", "review"]

    return PlanExecutionResult(
        applied=(result_kind != "error" and plan.stage in {"apply", "review"}),
        action_family="replace_units",
        stage=plan.stage,
        result_kind=result_kind,
        executed_actions=executed_actions,
        affected_volunteer_ids=affected_volunteer_ids,
        workspace_refresh_targets=workspace_targets,
        context_summary=plan.context_summary,
        state_summary=state_summary,
        summary=state_summary,
        reply_focus=reply_focus,
        next_step_hints=next_step_hints,
    )


@register_handler("regenerate_order")
async def handle_regenerate_order(
    ctx: RunContext[RequestContext], plan: PlanActionPlan
) -> PlanExecutionResult:
    state_summary = await _regenerate_ordered_plan(ctx)

    return PlanExecutionResult(
        applied=(plan.stage in {"apply", "review"}),
        action_family="regenerate_order",
        stage=plan.stage,
        result_kind="mutation_result",
        executed_actions=[{"action": "regenerate_order"}],
        workspace_refresh_targets=["ordered", "review"],
        context_summary=plan.context_summary,
        state_summary=state_summary,
        summary=state_summary,
        reply_focus=["mutation_result", "plan_update", "regenerated_order"],
        next_step_hints=["优先说明重排后的整体数量、风险和提醒，不要只说已执行。"],
    )
