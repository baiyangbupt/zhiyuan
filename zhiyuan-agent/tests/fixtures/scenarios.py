"""命名场景数据，供回归 / 集成测试复用。

每个场景是一个字典，可直接传给 make_plan_context_inputs / make_planning_state_response
或用作 mock backend 返回值。
"""

from __future__ import annotations

from typing import Any

from tests.factories import (
    make_plan_context_inputs,
    make_planning_state_response,
    make_review_issue,
)

# ---------------------------------------------------------------------------
# PlanContextInputs 命名场景
# ---------------------------------------------------------------------------

EMPTY_PLAN = make_plan_context_inputs(
    phase="candidate",
    draft_count=0,
    ordered_count=0,
    target_count=30,
)

DRAFT_ONLY_20 = make_plan_context_inputs(
    phase="draft",
    draft_count=20,
    ordered_count=0,
    target_count=30,
)

ORDERED_30 = make_plan_context_inputs(
    phase="ordered",
    draft_count=30,
    ordered_count=30,
    target_count=30,
)

ORDERED_80 = make_plan_context_inputs(
    phase="ordered",
    draft_count=80,
    ordered_count=80,
    target_count=96,
)

ORDERED_FULL_96 = make_plan_context_inputs(
    phase="ordered",
    draft_count=96,
    ordered_count=96,
    target_count=96,
)

ORDERED_WITH_RISKS = make_plan_context_inputs(
    phase="ordered",
    draft_count=90,
    ordered_count=90,
    target_count=96,
    risk_count=2,
    warn_count=3,
    review_issues=[
        make_review_issue(code="high_tuition", label="高收费", scope_kind="item_removal",
                          default_action_family="remove_units", affected_unit_count=5,
                          affected_volunteer_count=15),
        make_review_issue(code="probability_inversion", label="概率倒挂", scope_kind="structural",
                          default_action_family="analyze_adjustment", affected_unit_count=3,
                          affected_volunteer_count=6),
    ],
    review_issue_summary_lines=[
        "高收费(5u/15v)",
        "概率倒挂(3u/6v)",
    ],
)

ORDERED_WITH_ALL_ISSUE_TYPES = make_plan_context_inputs(
    phase="ordered",
    draft_count=90,
    ordered_count=90,
    target_count=96,
    risk_count=3,
    warn_count=5,
    review_issues=[
        make_review_issue(code="high_tuition", label="高收费", scope_kind="item_removal",
                          default_action_family="remove_units"),
        make_review_issue(code="cooperative_program", label="中外合作", scope_kind="item_removal",
                          default_action_family="remove_units"),
        make_review_issue(code="probability_inversion", label="概率倒挂", scope_kind="structural",
                          default_action_family="analyze_adjustment"),
        make_review_issue(code="ratio_distribution", label="冲稳保配比", scope_kind="structural",
                          default_action_family="analyze_adjustment"),
        make_review_issue(code="plan_update_notice", label="招生计划更新提示", scope_kind="informational",
                          default_action_family=""),
    ],
)

ORDERED_WITH_PREFERENCES = make_plan_context_inputs(
    phase="ordered",
    draft_count=60,
    ordered_count=60,
    target_count=96,
    positive_majors=["计算机类", "电子信息类"],
    negative_majors=["医学类"],
    positive_regions=["北京", "天津"],
    negative_regions=["新疆"],
    career_types=["体制内"],
)


# ---------------------------------------------------------------------------
# Backend Response 命名场景
# ---------------------------------------------------------------------------

BACKEND_EMPTY_STATE = make_planning_state_response(
    phase="candidate",
    draft_total=0,
    ordered_total=0,
    candidate_required=30,
)

BACKEND_ORDERED_30 = make_planning_state_response(
    phase="ordered",
    draft_total=30,
    ordered_total=30,
    candidate_required=30,
)

BACKEND_ORDERED_WITH_RISKS = make_planning_state_response(
    phase="ordered",
    draft_total=90,
    ordered_total=90,
    candidate_required=96,
    risk_count=2,
    warn_count=3,
    checks=[
        {
            "code": "high_tuition",
            "passed": False,
            "level": "risk",
            "summary": "当前方案包含高收费项目",
            "affectedVolunteerIds": [f"v{i}" for i in range(1, 16)],
            "affectedUnitIds": [f"u{i}" for i in range(1, 6)],
        },
        {
            "code": "probability_inversion",
            "passed": False,
            "level": "warn",
            "summary": "存在录取概率倒挂",
            "affectedVolunteerIds": [f"v{i}" for i in range(20, 26)],
            "affectedUnitIds": [f"u{i}" for i in range(20, 23)],
        },
    ],
)
