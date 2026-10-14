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
from app.models.conversation_phase import ConversationPhase, PendingConfirmation, PhaseState
from app.schemas.user_profile import UserProfile
from app.tools.plan_orchestration_models import (
    PlanContextInputs,
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
    planning_ordered_target_total: int = 0,
    planning_draft_total: int = 0,
    planning_risk_count: int = 0,
    planning_warn_count: int = 0,
    pending_action_family: str | None = None,
    conversation_phase: ConversationPhase | None = None,
    init_profile: UserProfile | None = None,
    confirmed_via_card: bool = False,
    confirmed_via_pending: bool = False,
    confirmation_entry: str = "",
) -> RequestContext:
    score = make_score_detail(volunteer_model=volunteer_model)
    planning_summary = None
    if planning_phase:
        planning_summary = PlanningSummary(
            phase=planning_phase,
            ordered_total=planning_ordered_total,
            ordered_target_total=planning_ordered_target_total,
            draft_total=planning_draft_total,
            review_risk_count=planning_risk_count,
            review_warn_count=planning_warn_count,
        )
    if conversation_phase is None and pending_action_family:
        conversation_phase = ConversationPhase(
            state=PhaseState.PLAN_PREVIEWING,
            pending=PendingConfirmation(
                kind="plan_mutation",
                action_family=pending_action_family,
            ),
        )
    return RequestContext(
        userid=userid,
        sessionid=sessionid,
        chat_history=chat_history,
        batch=batch,
        score_detail=score,
        init_profile=init_profile,
        planning_summary=planning_summary,
        conversation_phase=conversation_phase,
        confirmed_via_card=confirmed_via_card,
        confirmed_via_pending=confirmed_via_pending,
        confirmation_entry=confirmation_entry,
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
    batch: str = "01",
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
    relation_lines: list[str] | None = None,
    review_issues: list[dict[str, Any]] | None = None,
    review_issue_summary_lines: list[str] | None = None,
    summary: str | None = None,
) -> PlanContextInputs:
    """构建 PlanContextInputs，自动拼接默认 summary。"""
    actual_summary = summary or f"阶段={phase}；方案={ordered_count}/{target_count}"
    return PlanContextInputs(
        batch=batch,
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
        relation_lines=relation_lines or [],
        review_issues=review_issues or [],
        review_issue_summary_lines=review_issue_summary_lines or [],
        summary=actual_summary,
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
    scope_kind: str = "item_replacement",
    default_action_family: str = "review_plan",
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
) -> dict[str, Any]:
    """构造 backend get_planning_state 返回的 data 部分。"""
    working_plan_state = {
        "summary": {
            "unitTotal": draft_total,
            "total": draft_total,
            "targetUnitCount": candidate_required,
            "targetCount": candidate_required,
        },
        "items": [],
    }
    return {
        "phase": phase,
        "version": 1,
        "candidatePoolState": {
            "requiredCount": candidate_required,
        },
        "workingPlanState": working_plan_state,
        "draftPlanState": working_plan_state,
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
    }
