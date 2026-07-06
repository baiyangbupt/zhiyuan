"""Sync-wrapper scenario tests for current planning workflow helpers."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.agent.context import PlanningSummary, RequestContext
from app.tools.planning_workflow_tool import (
    generate_planning_initial_plan,
    generate_planning_ordered_plan,
    query_planning_state,
    remove_planning_ordered_items,
)


def _ctx(session_id: str = "900") -> SimpleNamespace:
    return SimpleNamespace(deps=RequestContext(userid="u1", sessionid=session_id))


def test_planning_scenario_existing_plan_blocks_initial_generate_without_confirmation():
    ctx = _ctx("901")
    ctx.deps.planning_summary = PlanningSummary(
        phase="ordered",
        version=8,
        draft_total=30,
        ordered_total=30,
        review_warn_count=1,
        review_risk_count=0,
        risk_summaries=[],
    )

    result = asyncio.run(generate_planning_initial_plan(ctx))

    assert "已经有方案" in result
    assert "明确确认" in result


def test_planning_scenario_initial_generate_formats_major_group_unit_totals():
    ctx = _ctx("902")
    response = {
        "code": 0,
        "data": {
            "orderedPlanState": {
                "summary": {
                    "unitTotal": 48,
                    "total": 96,
                    "unitTierCounts": {"冲": 14, "稳": 16, "保": 18},
                    "gradientOk": True,
                    "safetyOk": True,
                },
                "items": [
                    {"position": 1, "schoolName": "北京联合大学(15)", "majorName": "计算机科学与技术", "tier": "冲"},
                    {"position": 2, "schoolName": "北京联合大学(15)", "majorName": "软件工程", "tier": "冲"},
                ],
            }
        },
    }

    with patch(
        "app.tools.planning_workflow_tool._generate_planning_candidate_pool_request",
        AsyncMock(return_value={"code": 0, "data": {}}),
    ), patch(
        "app.tools.planning_workflow_tool._generate_planning_initial_plan_request",
        AsyncMock(return_value=response),
    ):
        result = asyncio.run(generate_planning_initial_plan(ctx, user_confirmed=True))

    assert "已按当前条件生成一版方案。" in result
    assert "排序总数：48" in result
    assert "区间分布：冲14 / 稳16 / 保18" in result


def test_planning_scenario_initial_generate_major_university_falls_back_to_total_counts():
    ctx = _ctx("902b")
    response = {
        "code": 0,
        "data": {
            "orderedPlanState": {
                "summary": {
                    "total": 96,
                    "tierCounts": {"冲": 32, "稳": 32, "保": 32},
                    "gradientOk": True,
                    "safetyOk": True,
                },
                "items": [
                    {"position": 1, "schoolName": "山东大学", "majorName": "计算机科学与技术", "tier": "冲"},
                    {"position": 2, "schoolName": "中国海洋大学", "majorName": "法学", "tier": "冲"},
                ],
            }
        },
    }

    with patch(
        "app.tools.planning_workflow_tool._generate_planning_candidate_pool_request",
        AsyncMock(return_value={"code": 0, "data": {}}),
    ), patch(
        "app.tools.planning_workflow_tool._generate_planning_initial_plan_request",
        AsyncMock(return_value=response),
    ):
        result = asyncio.run(generate_planning_initial_plan(ctx, user_confirmed=True))

    assert "已按当前条件生成一版方案。" in result
    assert "排序总数：96" in result
    assert "区间分布：冲32 / 稳32 / 保32" in result


def test_planning_scenario_query_state_surfaces_risks_pending_and_stale_flags():
    ctx = _ctx("903")
    response = {
        "code": 0,
        "data": {
            "phase": "reviewed",
            "version": 11,
            "staleFlags": {
                "candidatePool": False,
                "orderedPlan": True,
                "review": True,
            },
            "draftPlanState": {"summary": {"unitTotal": 30, "total": 60}},
            "orderedPlanState": {"summary": {"unitTotal": 28, "total": 56}},
            "reviewState": {
                "summary": {"warnCount": 2, "riskCount": 1},
                "checks": [
                    {"passed": False, "summary": "梯度有断层"},
                    {"passed": False, "summary": "个别专业组缺少安全垫"},
                ],
            },
        },
    }

    with patch(
        "app.tools.planning_workflow_tool._get_planning_state_request",
        AsyncMock(return_value=response),
    ):
        result = asyncio.run(query_planning_state(ctx))

    assert "当前阶段：reviewed" in result
    assert "已加入方案数：30" in result
    assert "当前方案数：28" in result
    assert "当前主要风险：梯度有断层；个别专业组缺少安全垫" in result
    assert "当前待处理建议" not in result
    assert "待刷新状态：排序待刷新；审查结果待刷新" in result


def test_planning_scenario_remove_units_reply_includes_removed_added_and_review_context():
    before_items = [
        {"volunteerId": "old-1", "schoolName": "南宁学院第01组", "majorName": "会计学", "tier": "冲"},
        {"volunteerId": "old-2", "schoolName": "广东白云学院第01组", "majorName": "审计学", "tier": "保"},
        {"volunteerId": "keep-1", "schoolName": "上海建桥学院第01组", "majorName": "网络与新媒体", "tier": "稳"},
    ]
    after_items = [
        before_items[2],
        {"volunteerId": "new-1", "schoolName": "广州工商学院第201组", "majorName": "跨境电子商务", "tier": "保"},
        {"volunteerId": "new-2", "schoolName": "福州大学至诚学院第001组", "majorName": "网络与新媒体", "tier": "稳"},
    ]
    refreshed_state = {
        "orderedPlanState": {
            "summary": {
                "unitTotal": 45,
                "targetUnitCount": 45,
                "unitTierCounts": {"冲": 8, "稳": 18, "保": 19},
                "gradientOk": True,
                "safetyOk": True,
            },
            "items": after_items,
        },
        "reviewState": {"summary": {"riskCount": 0, "warnCount": 1}, "checks": []},
    }

    with patch(
        "app.tools.planning_workflow_tool._get_planning_ordered_plan_request",
        AsyncMock(return_value={"code": 0, "data": {"items": before_items}}),
    ), patch(
        "app.tools.planning_workflow_tool._remove_working_plan_items_request",
        AsyncMock(return_value={"code": 0, "data": {}}),
    ), patch(
        "app.tools.planning_workflow_tool._generate_planning_ordered_plan_request",
        AsyncMock(return_value={"code": 0, "data": {"orderedPlanState": refreshed_state["orderedPlanState"]}}),
    ), patch(
        "app.tools.planning_workflow_tool._rerun_review_and_fetch_state",
        AsyncMock(return_value=refreshed_state),
    ):
        result = asyncio.run(remove_planning_ordered_items(_ctx("session-57"), ["old-1", "old-2"]))

    assert "移出的志愿：南宁学院第01组-会计学" in result
    assert "广东白云学院第01组-审计学" in result
    assert "重新补入/排序后的新增志愿：广州工商学院第201组-跨境电子商务" in result
    assert "福州大学至诚学院第001组-网络与新媒体" in result
    assert "复审结果：风险0项，提醒1项" in result


def test_planning_scenario_generate_ordered_plan_requires_confirmation_in_workflow():
    result = asyncio.run(generate_planning_ordered_plan(_ctx("912")))
    assert "请先在对话中获得用户明确确认" in result
