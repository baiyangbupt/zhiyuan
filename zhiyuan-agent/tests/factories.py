"""共享测试工厂，支持 major / majorGroup 双模式。

使用：
    from tests.factories import make_score_detail, make_request_context, ...
"""

from __future__ import annotations

import json
from dataclasses import field as dataclass_field
from types import SimpleNamespace
from typing import Any

from app.agent.context import PlanningSummary, RequestContext, ScoreDetail
from app.schemas.user_profile import UserProfile
from app.tools.plan_orchestration_models import (
    PlanActionPlan,
    PlanAtomicAction,
    PlanContextInputs,
    PlanExecutionResult,
    PlanReviewIssueTarget,
)


# ---------------------------------------------------------------------------
# ScoreDetail
# ---------------------------------------------------------------------------

def make_score_detail(
    *,
    province: str = "河北",
    total_score: int = 550,
    subject_list: list[str] | None = None,
    sex: str = "男",
    volunteer_model: str = "major",
) -> ScoreDetail:
    return ScoreDetail(
        province=province,
        total_score=total_score,
        subject_list=subject_list or ["物理", "化学", "生物"],
        sex=sex,
        volunteer_model=volunteer_model,
    )


# ---------------------------------------------------------------------------
# RequestContext
# ---------------------------------------------------------------------------

def make_request_context(
    *,
    userid: str = "test-user-1",
    sessionid: str = "test-session-1",
    chat_history: list[dict] | None = None,
    batch: str | None = "01",
    volunteer_model: str = "major",
    planning_phase: str = "",
    planning_ordered_total: int = 0,
    planning_draft_total: int = 0,
    planning_risk_count: int = 0,
    planning_warn_count: int = 0,
    pending_plan_action: dict | None = None,
    pending_intent_change: bool = False,
    init_profile: UserProfile | None = None,
) -> RequestContext:
    score = make_score_detail(volunteer_model=volunteer_model)
    planning_summary = None
    if planning_phase:
        planning_summary = PlanningSummary(
            phase=planning_phase,
            ordered_total=planning_ordered_total,
            draft_total=planning_draft_total,
            review_risk_count=planning_risk_count,
            review_warn_count=planning_warn_count,
        )
    return RequestContext(
        userid=userid,
        sessionid=sessionid,
        chat_history=chat_history,
        batch=batch,
        score_detail=score,
        init_profile=init_profile,
        planning_summary=planning_summary,
        pending_plan_action=pending_plan_action,
        pending_intent_change=pending_intent_change,
    )


# ---------------------------------------------------------------------------
# RunContext 模拟
# ---------------------------------------------------------------------------

def make_run_context(
    *,
    request_context: RequestContext | None = None,
    volunteer_model: str = "major",
    **kwargs: Any,
) -> SimpleNamespace:
    """创建一个轻量级 RunContext 替代品供测试使用。"""
    ctx = request_context or make_request_context(volunteer_model=volunteer_model, **kwargs)
    return SimpleNamespace(deps=ctx)


# ---------------------------------------------------------------------------
# PlanContextInputs
# ---------------------------------------------------------------------------

def make_plan_context_inputs(
    *,
    phase: str = "ordered",
    target_count: int = 30,
    draft_count: int = 20,
    ordered_count: int = 20,
    risk_count: int = 0,
    warn_count: int = 0,
    positive_majors: list[str] | None = None,
    negative_majors: list[str] | None = None,
    positive_schools: list[str] | None = None,
    negative_schools: list[str] | None = None,
    positive_regions: list[str] | None = None,
    negative_regions: list[str] | None = None,
    career_types: list[str] | None = None,
    relation_lines: list[str] | None = None,
    review_issues: list[dict[str, Any]] | None = None,
    review_issue_summary_lines: list[str] | None = None,
    summary: str | None = None,
) -> PlanContextInputs:
    """构建 PlanContextInputs，自动拼接默认 summary。"""
    actual_summary = summary or f"阶段={phase}；方案={ordered_count}/{target_count}"
    return PlanContextInputs(
        phase=phase,
        target_count=target_count,
        draft_count=draft_count,
        ordered_count=ordered_count,
        risk_count=risk_count,
        warn_count=warn_count,
        positive_majors=positive_majors or [],
        negative_majors=negative_majors or [],
        positive_schools=positive_schools or [],
        negative_schools=negative_schools or [],
        positive_regions=positive_regions or [],
        negative_regions=negative_regions or [],
        career_types=career_types or [],
        relation_lines=relation_lines or [],
        review_issues=review_issues or [],
        review_issue_summary_lines=review_issue_summary_lines or [],
        summary=actual_summary,
    )


# ---------------------------------------------------------------------------
# PlanActionPlan
# ---------------------------------------------------------------------------

def make_plan_action_plan(
    *,
    stage: str = "preview",
    action_family: str = "query_state",
    user_goal: str = "",
    requires_confirmation: bool = False,
    should_rerun_review: bool = False,
    should_refresh_workspace: bool = False,
    context_summary: str = "",
    intent_relation: str = "unknown",
    missing_inputs: list[str] | None = None,
    rationale: list[str] | None = None,
    atomic_actions: list[dict[str, Any]] | None = None,
    preview_summary: str = "",
) -> PlanActionPlan:
    actions = []
    if atomic_actions:
        for a in atomic_actions:
            actions.append(PlanAtomicAction(**a))
    return PlanActionPlan(
        stage=stage,  # type: ignore[arg-type]
        action_family=action_family,  # type: ignore[arg-type]
        user_goal=user_goal,
        requires_confirmation=requires_confirmation,
        should_rerun_review=should_rerun_review,
        should_refresh_workspace=should_refresh_workspace,
        context_summary=context_summary,
        intent_relation=intent_relation,  # type: ignore[arg-type]
        missing_inputs=missing_inputs or [],
        rationale=rationale or [],
        atomic_actions=actions,
        preview_summary=preview_summary,
    )


# ---------------------------------------------------------------------------
# PlanExecutionResult
# ---------------------------------------------------------------------------

def make_plan_execution_result(
    *,
    applied: bool = False,
    action_family: str = "query_state",
    stage: str = "apply",
    result_kind: str = "status_overview",
    summary: str = "",
    facts: dict[str, Any] | None = None,
    workspace_refresh_targets: list[str] | None = None,
    reply_focus: list[str] | None = None,
    next_step_hints: list[str] | None = None,
) -> PlanExecutionResult:
    return PlanExecutionResult(
        applied=applied,
        action_family=action_family,
        stage=stage,
        result_kind=result_kind,  # type: ignore[arg-type]
        summary=summary,
        facts=facts or {},
        workspace_refresh_targets=workspace_refresh_targets or [],
        reply_focus=reply_focus or [],
        next_step_hints=next_step_hints or [],
    )


# ---------------------------------------------------------------------------
# PlanningSummary
# ---------------------------------------------------------------------------

def make_planning_summary(
    *,
    phase: str = "ordered",
    version: int = 1,
    candidate_target_total: int = 0,
    draft_total: int = 0,
    draft_target_total: int = 0,
    ordered_total: int = 0,
    ordered_target_total: int = 0,
    review_warn_count: int = 0,
    review_risk_count: int = 0,
    risk_summaries: list[str] | None = None,
    pending_action_count: int = 0,
    pending_action_summaries: list[str] | None = None,
) -> PlanningSummary:
    return PlanningSummary(
        phase=phase,
        version=version,
        candidate_target_total=candidate_target_total,
        draft_total=draft_total,
        draft_target_total=draft_target_total,
        ordered_total=ordered_total,
        ordered_target_total=ordered_target_total,
        review_warn_count=review_warn_count,
        review_risk_count=review_risk_count,
        risk_summaries=risk_summaries or [],
        pending_action_count=pending_action_count,
        pending_action_summaries=pending_action_summaries or [],
    )


# ---------------------------------------------------------------------------
# UserProfile 快捷构造
# ---------------------------------------------------------------------------

def make_user_profile(
    *,
    major_level2: list[str] | None = None,
    major_level3: list[str] | None = None,
    provinces: list[str] | None = None,
    colleges: list[str] | None = None,
) -> UserProfile:
    data: dict[str, Any] = {}
    major: dict[str, Any] = {}
    if major_level2:
        major["level2"] = major_level2
    if major_level3:
        major["level3"] = major_level3
    if major:
        data["major"] = major
    if provinces:
        data["city"] = {"province": provinces}
    if colleges:
        data["school"] = {"colleges": colleges}
    return UserProfile.model_validate(data)


# ---------------------------------------------------------------------------
# Review Issue 快捷构造
# ---------------------------------------------------------------------------

def make_review_issue(
    *,
    code: str = "high_tuition",
    label: str = "高收费",
    scope_kind: str = "item_removal",
    default_action_family: str = "remove_units",
    affected_unit_count: int = 5,
    affected_volunteer_count: int = 15,
    scope_fingerprint: str = "",
) -> dict[str, Any]:
    return {
        "code": code,
        "label": label,
        "scope_kind": scope_kind,
        "default_action_family": default_action_family,
        "affected_unit_count": affected_unit_count,
        "affected_volunteer_count": affected_volunteer_count,
        "scope_fingerprint": scope_fingerprint or f"fp-{code}",
    }


# ---------------------------------------------------------------------------
# Backend Response 快捷构造
# ---------------------------------------------------------------------------

def make_planning_state_response(
    *,
    phase: str = "ordered",
    draft_total: int = 0,
    ordered_total: int = 0,
    candidate_required: int = 30,
    risk_count: int = 0,
    warn_count: int = 0,
    checks: list[dict] | None = None,
    pending_actions: list[dict] | None = None,
) -> dict[str, Any]:
    """构造 backend get_planning_state 返回的 data 部分。"""
    return {
        "phase": phase,
        "version": 1,
        "candidatePoolState": {
            "requiredCount": candidate_required,
        },
        "draftPlanState": {
            "summary": {
                "unitTotal": draft_total,
                "total": draft_total,
                "targetUnitCount": candidate_required,
                "targetCount": candidate_required,
            },
            "items": [],
        },
        "orderedPlanState": {
            "summary": {
                "unitTotal": ordered_total,
                "total": ordered_total,
                "targetUnitCount": candidate_required,
                "targetCount": candidate_required,
            },
            "items": [],
        },
        "reviewState": {
            "summary": {
                "riskCount": risk_count,
                "warnCount": warn_count,
            },
            "checks": checks or [],
        },
        "pendingActions": pending_actions or [],
    }
