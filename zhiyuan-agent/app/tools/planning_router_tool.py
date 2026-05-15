"""Deprecated compatibility wrapper for single-step planning requests.

3.0.1 起，ChatAgent 不再注册本模块给模型直连。正式 Plan 入口是
collect_plan_context_inputs -> plan_next_action -> execute_plan_action。
本模块只保留给历史测试和兼容调用，新增能力不要继续接入这里。
"""

from __future__ import annotations

import logging

from pydantic_ai import RunContext

from app.agent.context import RequestContext
from app.tools.plan_execution_tool import _execute_plan_action_model
from app.tools.plan_orchestration_tool import _plan_next_action_model
from app.tools.planning_workflow_tool import (
    ban_planning_draft_items,
    generate_planning_initial_plan,
    lock_planning_draft_items,
    pin_planning_ordered_item,
    query_planning_candidate_pool,
    query_planning_plan_overview,
    remove_planning_draft_items,
    unpin_planning_ordered_item,
)

logger = logging.getLogger(__name__)


def _normalize_request_type(request_type: str) -> str:
    return (request_type or "").strip().lower().replace("-", "_")


def _ensure_volunteer_ids(volunteer_ids: list[str] | None, action_name: str) -> list[str] | None:
    if volunteer_ids:
        return volunteer_ids
    logger.info("handle_planning_request missing volunteer_ids for action=%s", action_name)
    return None


async def _build_plan_mutation_preview(
    ctx: RunContext[RequestContext],
    *,
    action_name: str,
    effect_text: str,
    missing_text: str | None = None,
) -> str:
    overview = await query_planning_plan_overview(ctx)
    lines = [
        "这一步我先不给你直接改方案，先把影响看清楚。",
        f"- 计划动作：{action_name}",
        f"- 预期影响：{effect_text}",
    ]
    if missing_text:
        lines.append(f"- 还缺信息：{missing_text}")
    lines.append("当前方案概况：")
    lines.append(overview)
    lines.append("如果你确认要执行，我再正式改动并在执行后重新审查。")
    return "\n".join(lines)


async def _run_planned_request(
    ctx: RunContext[RequestContext],
    *,
    user_goal: str,
    action_family: str,
    volunteer_ids: list[str] | None = None,
    target_position: int | None = None,
    tier: str | None = None,
    province_keyword: str | None = None,
    school_keyword: str | None = None,
    major_keyword: str | None = None,
    school_tags: list[str] | None = None,
    major_tags: list[str] | None = None,
    limit: int = 5,
    user_confirmed: bool = False,
) -> str:
    plan = await _plan_next_action_model(
        ctx,
        user_goal=user_goal,
        action_family=action_family,  # type: ignore[arg-type]
        volunteer_ids=volunteer_ids,
        target_position=target_position,
        tier=tier,
        province_keyword=province_keyword,
        school_keyword=school_keyword,
        major_keyword=major_keyword,
        school_tags=school_tags,
        major_tags=major_tags,
        limit=limit,
        user_confirmed=user_confirmed,
    )
    if plan.stage == "analyze":
        if plan.missing_inputs:
            if action_family == "remove_units":
                return "删除志愿需要先确认要删除哪一条，请先查询当前方案。"
            if action_family == "move_unit":
                return "调整排序需要确认想移动哪个志愿、移到第几位，请先查看当前方案。"
            return f"还缺必要信息，请补充后重试。{plan.context_summary}"
        return plan.context_summary
    if plan.stage == "preview":
        effect_text = plan.preview_summary or "会调整当前方案，并在执行后自动复审。"
        missing_text = ", ".join(plan.missing_inputs) if plan.missing_inputs else None
        action_label_map = {
            "add_units": "补入志愿",
            "remove_units": "删除志愿",
            "move_unit": "调整志愿顺序",
            "regenerate_order": "整体重排当前方案",
            "apply_compensation": "应用补偿建议",
        }
        return await _build_plan_mutation_preview(
            ctx,
            action_name=action_label_map.get(action_family, action_family),
            effect_text=effect_text,
            missing_text=missing_text,
        )
    if plan.stage == "review" and action_family == "review_plan":
        result = await _execute_plan_action_model(ctx, plan)
        return result.summary
    result = await _execute_plan_action_model(ctx, plan)
    return result.summary


async def handle_planning_request(
    ctx: RunContext[RequestContext],
    request_type: str,
    tier: str | None = None,
    province_keyword: str | None = None,
    school_keyword: str | None = None,
    major_keyword: str | None = None,
    school_tags: list[str] | None = None,
    major_tags: list[str] | None = None,
    sort_field: str = "finalScore",
    sort_order: str = "desc",
    volunteer_ids: list[str] | None = None,
    limit: int = 5,
    target_position: int | None = None,
    user_confirmed: bool = False,
) -> str:
    """处理单步 planning 请求。

    推荐用于高频、明确的当前方案诉求：
    - `state` / `draft_query` / `ordered_query`
    - `candidate_query` / `candidate_select`
    - `draft_remove` / `draft_lock` / `draft_unlock` / `draft_ban`
    - `initial_plan_generate`
    - `ordered_regenerate` / `ordered_move` / `ordered_pin` / `ordered_unpin`
    - `review` / `compensation_preview` / `compensation_apply`

    使用建议：
    - 如果用户是在干预“当前方案”，优先调用本工具，而不是直接走画像更新。
    - 需要改动方案的整体动作，如 `ordered_regenerate`、`compensation_apply`，仅在用户明确确认后传 `user_confirmed=True`。
    - `candidate_select` 优先使用 `volunteer_ids`；若用户只给了筛选条件，也可直接通过关键词从候选池选入草稿。
    """
    normalized_type = _normalize_request_type(request_type)
    logger.info(
        "handle_planning_request called: session_id=%s request_type=%s normalized=%s volunteer_ids=%s",
        ctx.deps.sessionid,
        request_type,
        normalized_type,
        volunteer_ids,
    )

    if normalized_type == "state":
        return await _run_planned_request(
            ctx,
            user_goal="查看当前方案状态",
            action_family="query_state",
            user_confirmed=True,
        )

    if normalized_type == "candidate_query":
        return await _run_planned_request(
            ctx,
            user_goal="查看当前候选机会",
            action_family="query_candidates",
            tier=tier,
            province_keyword=province_keyword,
            school_keyword=school_keyword,
            major_keyword=major_keyword,
            school_tags=school_tags,
            major_tags=major_tags,
            limit=limit,
        )

    if normalized_type == "draft_query":
        return await _run_planned_request(
            ctx,
            user_goal="查看当前已加入方案",
            action_family="query_draft",
            user_confirmed=True,
        )

    if normalized_type == "ordered_query":
        return await _run_planned_request(
            ctx,
            user_goal="查看当前排序方案",
            action_family="query_ordered",
            user_confirmed=True,
        )

    if normalized_type == "candidate_select":
        ensured_ids = _ensure_volunteer_ids(volunteer_ids, normalized_type)
        if ensured_ids:
            return await _run_planned_request(
                ctx,
                user_goal="把指定候选加入当前方案",
                action_family="add_units",
                volunteer_ids=ensured_ids,
                user_confirmed=user_confirmed,
            )
        return await _run_planned_request(
            ctx,
            user_goal="按条件补入候选到当前方案",
            action_family="add_units",
            tier=tier,
            province_keyword=province_keyword,
            school_keyword=school_keyword,
            major_keyword=major_keyword,
            school_tags=school_tags,
            major_tags=major_tags,
            limit=max(1, min(limit, 10)),
            user_confirmed=user_confirmed,
        )

    if normalized_type == "draft_remove":
        ensured_ids = _ensure_volunteer_ids(volunteer_ids, normalized_type)
        if not ensured_ids:
            return "移出草稿需要先确认要移除哪些志愿，请先查询草稿或候选列表。"
        return await remove_planning_draft_items(ctx, ensured_ids)

    if normalized_type == "draft_lock":
        ensured_ids = _ensure_volunteer_ids(volunteer_ids, normalized_type)
        if not ensured_ids:
            return "锁定草稿需要先确认要锁定哪些志愿，请先查询草稿。"
        return await lock_planning_draft_items(ctx, ensured_ids, locked=True)

    if normalized_type == "draft_unlock":
        ensured_ids = _ensure_volunteer_ids(volunteer_ids, normalized_type)
        if not ensured_ids:
            return "解除锁定需要先确认要解锁哪些志愿，请先查询草稿。"
        return await lock_planning_draft_items(ctx, ensured_ids, locked=False)

    if normalized_type == "draft_ban":
        ensured_ids = _ensure_volunteer_ids(volunteer_ids, normalized_type)
        if not ensured_ids:
            return "禁用志愿需要先确认要禁用哪些，请先查询草稿或候选列表。"
        return await ban_planning_draft_items(ctx, ensured_ids)

    if normalized_type == "ordered_regenerate":
        return await _run_planned_request(
            ctx,
            user_goal="整体重排当前方案",
            action_family="regenerate_order",
            user_confirmed=user_confirmed,
        )

    if normalized_type == "initial_plan_generate":
        return await generate_planning_initial_plan(
            ctx,
            user_confirmed=user_confirmed,
            force_regenerate=True,
            regroup_by_tier=True,
        )

    if normalized_type == "ordered_move":
        ensured_ids = _ensure_volunteer_ids(volunteer_ids, normalized_type)
        return await _run_planned_request(
            ctx,
            user_goal="调整单条志愿顺序",
            action_family="move_unit",
            volunteer_ids=ensured_ids,
            target_position=target_position,
            user_confirmed=user_confirmed,
        )

    if normalized_type == "ordered_remove":
        ensured_ids = _ensure_volunteer_ids(volunteer_ids, normalized_type)
        return await _run_planned_request(
            ctx,
            user_goal="从当前方案删除志愿",
            action_family="remove_units",
            volunteer_ids=ensured_ids,
            user_confirmed=user_confirmed,
        )

    if normalized_type == "ordered_pin":
        return "新版工作台暂不提供固定/锁定志愿入口。可以改用移动到指定位置或方案排序。"

    if normalized_type == "ordered_unpin":
        return "新版工作台暂不提供固定/锁定志愿入口。当前无需取消固定，可以改用移动到指定位置或方案排序。"

    if normalized_type == "review":
        return await _run_planned_request(
            ctx,
            user_goal="审查当前方案",
            action_family="review_plan",
            user_confirmed=True,
        )

    if normalized_type == "plan_adjustment_analyze":
        return await _run_planned_request(
            ctx,
            user_goal="分析当前方案调整建议",
            action_family="analyze_adjustment",
            user_confirmed=True,
        )

    if normalized_type == "compensation_preview":
        return await _run_planned_request(
            ctx,
            user_goal="查看补偿建议预览",
            action_family="preview_compensation",
            user_confirmed=True,
        )

    if normalized_type == "compensation_apply":
        return await _run_planned_request(
            ctx,
            user_goal="应用补偿建议",
            action_family="apply_compensation",
            user_confirmed=user_confirmed,
        )

    return (
        "未识别的 planning request_type。"
        "可用值包括：state、candidate_query、candidate_select、draft_query、ordered_query、"
        "draft_remove、draft_lock、draft_unlock、draft_ban、initial_plan_generate、ordered_regenerate、ordered_move、ordered_remove、"
        "ordered_pin、ordered_unpin、review、plan_adjustment_analyze、compensation_preview、compensation_apply。"
    )
