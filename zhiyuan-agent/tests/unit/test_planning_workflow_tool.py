"""Unit tests for planning workflow tools."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.context import PlanningSummary, RequestContext
from app.tools.planning_workflow_tool import (
    _build_compensation_preview_facts,
    _fix_proposal_facts,
    _build_plan_status_overview_facts,
    analyze_planning_plan_adjustment,
    apply_planning_fix_proposal,
    ban_planning_draft_items,
    generate_planning_fix_proposals,
    generate_planning_initial_plan,
    generate_planning_ordered_plan,
    lock_planning_draft_items,
    move_planning_ordered_item,
    query_planning_candidate_pool,
    query_planning_draft,
    query_planning_ordered_plan,
    query_planning_plan_overview,
    query_planning_state,
    remove_planning_draft_items,
    remove_planning_ordered_items,
    run_planning_review,
    select_planning_draft_items,
    select_planning_ordered_items,
)


@pytest.fixture(autouse=True)
def _stub_user_profile_request():
    with patch(
        "app.tools.planning_workflow_tool._get_user_profile_request",
        AsyncMock(return_value={"code": 1, "data": {}}),
    ):
        yield


def _make_ctx(session_id: str = "session-123") -> MagicMock:
    ctx = MagicMock()
    ctx.deps = RequestContext(userid="user-1", sessionid=session_id)
    return ctx


def test_run_planning_review_uses_session_and_formats_result():
    ctx = _make_ctx("review-session")
    response = {
        "code": 0,
        "data": {
            "summary": {"passedCount": 9, "warnCount": 1, "riskCount": 2},
            "checks": [
                {"passed": False, "summary": "保区占比过低"},
                {"passed": False, "summary": "本省保底志愿数量不足"},
            ],
            "compensationPreview": {
                "actions": [
                    {"summary": "补充保区志愿"},
                    {"summary": "补足志愿总数量"},
                ]
            },
        },
    }

    with patch(
        "app.tools.planning_workflow_tool._run_planning_review_request",
        AsyncMock(return_value=response),
    ) as mock_request:
        result = asyncio.run(run_planning_review(ctx))

    mock_request.assert_awaited_once_with(1, "review-session")
    assert "已完成当前方案审查。" in result
    assert "风险2项，提醒1项，通过9项" in result
    assert "保区占比过低" in result
    assert "补充保区志愿" in result


def test_generate_planning_initial_plan_requires_confirmation_when_existing_plan_present():
    ctx = _make_ctx("initial-plan-session")
    ctx.deps.planning_summary = PlanningSummary(
        phase="ordered",
        version=3,
        draft_total=5,
        ordered_total=5,
        review_warn_count=0,
        review_risk_count=0,
        risk_summaries=[],
        pending_action_count=0,
        pending_action_summaries=[],
    )

    result = asyncio.run(generate_planning_initial_plan(ctx))

    assert "先在对话中明确确认" in result


def test_generate_planning_initial_plan_calls_backend_and_formats_result():
    ctx = _make_ctx("initial-plan-session")
    response = {
        "code": 0,
        "data": {
            "orderedPlanState": {
                "summary": {"total": 20, "tierCounts": {"sprint": 6, "safe": 8, "protect": 6}},
                "items": [
                    {"schoolName": "A大学", "majorName": "计算机类", "tier": "稳", "position": 1},
                    {"schoolName": "B大学", "majorName": "电子信息类", "tier": "保", "position": 2},
                ],
            }
        },
    }
    state_response = {
        "code": 0,
        "data": {
            "orderedPlanState": {
                "summary": {
                    "unitTotal": 20,
                    "targetUnitCount": 30,
                    "tierCounts": {"sprint": 6, "safe": 8, "protect": 6},
                    "gradientOk": True,
                    "safetyOk": True,
                },
                "items": [
                    {"schoolName": "A大学", "majorName": "计算机类", "tier": "稳", "position": 1},
                    {"schoolName": "B大学", "majorName": "电子信息类", "tier": "保", "position": 2},
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
    ) as mock_request, patch(
        "app.tools.planning_workflow_tool._run_planning_review_request",
        AsyncMock(return_value={"code": 0, "data": {}}),
    ), patch(
        "app.tools.planning_workflow_tool._get_planning_state_request",
        AsyncMock(return_value=state_response),
    ):
        result = asyncio.run(generate_planning_initial_plan(ctx, user_confirmed=True))

    mock_request.assert_awaited_once_with(
        1,
        "initial-plan-session",
        force_regenerate=True,
        regroup_by_tier=True,
        overwrite_existing_draft=False,
    )
    assert "已按当前条件生成一版方案。" in result
    assert "20/30" in result
    assert "当前志愿数量不足，还差 10 个" in result
    assert "A大学-计算机类" in result


def test_query_planning_state_uses_session_and_formats_result():
    ctx = _make_ctx("state-session")
    response = {
        "code": 0,
        "data": {
            "phase": "ordered",
            "version": 7,
            "staleFlags": {"candidatePool": False, "orderedPlan": False, "review": True},
            "draftPlanState": {"summary": {"total": 25}},
            "orderedPlanState": {
                "summary": {"total": 20},
                "items": [
                    {"position": 1, "schoolName": "北京大学", "majorName": "法学", "provinceName": "北京", "schoolCategory": "政法", "tier": "冲"},
                    {"position": 2, "schoolName": "上海大学", "majorName": "计算机科学与技术", "provinceName": "上海", "tier": "稳"},
                ],
            },
            "profileState": {
                "explicitProfile": {
                    "positiveRegions": ["北京"],
                    "negativeRegions": ["上海"],
                },
                "latentProfile": {
                    "futureDevelopment": {"careerTypes": ["体制内/考公导向"]},
                },
            },
            "reviewState": {
                "summary": {"warnCount": 2, "riskCount": 1},
                "checks": [{"passed": False, "summary": "保区占比过低"}],
            },
            "pendingActions": [{"summary": "补充保区志愿"}],
        },
    }
    ordered_response = {
        "code": 0,
        "data": {
            "items": response["data"]["orderedPlanState"]["items"],
            "summary": {"total": 20},
        },
    }

    with (
        patch("app.tools.planning_workflow_tool._get_planning_state_request", AsyncMock(return_value=response)) as mock_request,
        patch("app.tools.planning_workflow_tool._get_planning_ordered_plan_request", AsyncMock(return_value=ordered_response)) as mock_ordered,
    ):
        result = asyncio.run(query_planning_state(ctx))

    mock_request.assert_awaited_once_with("state-session")
    mock_ordered.assert_awaited_once_with("state-session")
    assert "当前规划状态概览：" in result
    assert "当前阶段：ordered" in result
    assert "状态版本：7" in result
    assert "当前偏好/要求：偏好地域=北京；排除地域=上海；发展方向=体制内/考公导向" in result
    assert "当前方案里较贴近的有1个，明显冲突的有1个" in result
    assert "待刷新状态：审查结果待刷新" in result


def test_query_planning_state_matches_level2_major_preferences_against_concrete_major_names():
    ctx = _make_ctx("state-session-major-category")
    response = {
        "code": 0,
        "data": {
            "phase": "ordered",
            "version": 8,
            "staleFlags": {"candidatePool": False, "orderedPlan": False, "review": False},
            "draftPlanState": {"summary": {"total": 30}},
            "orderedPlanState": {
                "summary": {"total": 30},
                "items": [
                    {"position": 1, "schoolName": "北京石油化工学院(03)", "majorName": "计算机科学与技术(4600元)", "tier": "冲"},
                    {"position": 2, "schoolName": "湖北工程学院(01)", "majorName": "自动化(4000元)", "tier": "冲"},
                    {"position": 3, "schoolName": "湖北工程学院(01)", "majorName": "电子信息工程(5200元)", "tier": "冲"},
                ],
            },
            "profileState": {
                "explicitProfile": {
                    "positiveMajors": ["计算机类", "自动化类", "电子信息类"],
                }
            },
            "reviewState": {
                "summary": {"warnCount": 1, "riskCount": 0},
                "checks": [{"passed": False, "summary": "冲区占比偏低"}],
            },
            "pendingActions": [],
        },
    }
    ordered_response = {
        "code": 0,
        "data": {
            "items": response["data"]["orderedPlanState"]["items"],
            "summary": {"total": 30},
        },
    }

    with (
        patch("app.tools.planning_workflow_tool._get_planning_state_request", AsyncMock(return_value=response)),
        patch("app.tools.planning_workflow_tool._get_planning_ordered_plan_request", AsyncMock(return_value=ordered_response)),
    ):
        result = asyncio.run(query_planning_state(ctx))

    assert "当前偏好/要求：偏好专业=计算机类,自动化类,电子信息类" in result
    assert "当前方案里较贴近的有3个，没有看到明显冲突" in result
    assert "北京石油化工学院(03)-计算机科学与技术(4600元)(冲)@1（匹配偏好专业:计算机类）" in result
    assert "湖北工程学院(01)-自动化(4000元)(冲)@2（匹配偏好专业:自动化类）" in result


def test_run_planning_review_aggregates_major_group_relation_counts_by_unit():
    ctx = _make_ctx("review-session-major-group")
    response = {
        "code": 0,
        "data": {
            "summary": {"passedCount": 9, "warnCount": 0, "riskCount": 0},
            "checks": [],
            "compensationPreview": {"actions": []},
        },
    }
    state_response = {
        "code": 0,
        "data": {
            "profileState": {
                "explicitProfile": {
                    "positiveMajors": ["计算机类", "自动化类"],
                }
            },
            "orderedPlanState": {
                "summary": {"total": 2},
                "items": [
                    {"volunteerId": "g1_m1", "position": 1, "schoolName": "北京石油化工学院(03)", "majorName": "计算机科学与技术(4600元)", "tier": "冲"},
                    {"volunteerId": "g1_m2", "position": 2, "schoolName": "北京石油化工学院(03)", "majorName": "软件工程(4600元)", "tier": "冲"},
                    {"volunteerId": "g2_m1", "position": 3, "schoolName": "湖北工程学院(01)", "majorName": "自动化(4000元)", "tier": "稳"},
                ],
            },
        },
    }
    ordered_response = {
        "code": 0,
        "data": {
            "items": state_response["data"]["orderedPlanState"]["items"],
            "summary": {"total": 2},
        },
    }

    with (
        patch("app.tools.planning_workflow_tool._run_planning_review_request", AsyncMock(return_value=response)) as mock_request,
        patch("app.tools.planning_workflow_tool._get_planning_state_request", AsyncMock(return_value=state_response)) as mock_state,
        patch("app.tools.planning_workflow_tool._get_planning_ordered_plan_request", AsyncMock(return_value=ordered_response)) as mock_ordered,
    ):
        result = asyncio.run(run_planning_review(ctx))

    mock_request.assert_awaited_once_with(1, "review-session-major-group")
    mock_state.assert_awaited_once_with("review-session-major-group")
    mock_ordered.assert_awaited_once_with("review-session-major-group")
    assert "当前偏好/要求：偏好专业=计算机类,自动化类" in result
    assert "当前方案里较贴近的有2个，没有看到明显冲突" in result
    assert "北京石油化工学院(03)-计算机科学与技术(4600元)(冲)@1（匹配偏好专业:计算机类）" in result
    assert "湖北工程学院(01)-自动化(4000元)(稳)@3（匹配偏好专业:自动化类）" in result
    assert "软件工程" not in result


def test_query_planning_plan_overview_reads_state_and_ordered_plan():
    ctx = _make_ctx("overview-session")
    state_response = {
        "code": 0,
        "data": {
            "phase": "reviewed",
            "version": 9,
            "staleFlags": {"candidatePool": False, "orderedPlan": False, "review": False},
            "draftPlanState": {"summary": {"total": 96}},
            "orderedPlanState": {"summary": {"total": 96}},
            "profileState": {
                "explicitProfile": {
                    "positiveSchools": ["重庆邮电大学"],
                    "negativeSchools": ["重庆理工大学"],
                }
            },
            "reviewState": {
                "summary": {"warnCount": 2, "riskCount": 0},
                "checks": [{"passed": False, "summary": "冲区占比偏低"}],
            },
            "pendingActions": [{"summary": "补充更稳的保底志愿"}],
        },
    }
    ordered_response = {
        "code": 0,
        "data": {
            "items": [
                {"position": 1, "schoolName": "重庆理工大学", "majorName": "计算机科学与技术", "tier": "冲"},
                {"position": 2, "schoolName": "重庆邮电大学", "majorName": "软件工程", "tier": "稳"},
            ],
            "summary": {
                "total": 96,
                "tierCounts": {"冲": 32, "稳": 32, "保": 32},
                "gradientOk": True,
                "safetyOk": True,
            },
        },
    }

    with (
        patch("app.tools.planning_workflow_tool._get_planning_state_request", AsyncMock(return_value=state_response)) as mock_state,
        patch("app.tools.planning_workflow_tool._get_planning_ordered_plan_request", AsyncMock(return_value=ordered_response)) as mock_ordered,
    ):
        result = asyncio.run(query_planning_plan_overview(ctx))

    mock_state.assert_awaited_once_with("overview-session")
    mock_ordered.assert_awaited_once_with("overview-session")
    assert "方案完整状态：" in result
    assert "当前已有排序方案：96个志愿" in result
    assert "冲稳保分布：冲32 / 稳32 / 保32" in result
    assert "方案前列：重庆理工大学-计算机科学与技术(冲)@1" in result
    assert "当前主要提醒：冲区占比偏低" in result
    assert "当前偏好/要求：偏好院校=重庆邮电大学；排除院校=重庆理工大学" in result
    assert "需关注冲突：重庆理工大学-计算机科学与技术(冲)@1（命中排除院校:重庆理工大学）" in result
    assert "待刷新状态" not in result


def test_run_planning_review_includes_intent_relation_summary():
    ctx = _make_ctx("review-session")
    response = {
        "code": 0,
        "data": {
            "summary": {"passedCount": 9, "warnCount": 1, "riskCount": 2},
            "checks": [{"passed": False, "summary": "保区占比过低"}],
            "compensationPreview": {"actions": []},
        },
    }
    state_response = {
        "code": 0,
        "data": {
            "profileState": {
                "explicitProfile": {
                    "positiveMajors": ["法学"],
                    "negativeRegions": ["上海"],
                }
            },
            "orderedPlanState": {
                "summary": {"total": 2},
                "items": [
                    {"position": 1, "schoolName": "北京大学", "majorName": "法学", "provinceName": "北京", "tier": "冲"},
                    {"position": 2, "schoolName": "上海大学", "majorName": "新闻学", "provinceName": "上海", "tier": "稳"},
                ]
            },
        },
    }
    ordered_response = {
        "code": 0,
        "data": {
            "items": state_response["data"]["orderedPlanState"]["items"],
            "summary": {"total": 2},
        },
    }

    with (
        patch("app.tools.planning_workflow_tool._run_planning_review_request", AsyncMock(return_value=response)) as mock_request,
        patch("app.tools.planning_workflow_tool._get_planning_state_request", AsyncMock(return_value=state_response)) as mock_state,
        patch("app.tools.planning_workflow_tool._get_planning_ordered_plan_request", AsyncMock(return_value=ordered_response)) as mock_ordered,
    ):
        result = asyncio.run(run_planning_review(ctx))

    mock_request.assert_awaited_once_with(1, "review-session")
    mock_state.assert_awaited_once_with("review-session")
    mock_ordered.assert_awaited_once_with("review-session")
    assert "当前偏好/要求：偏好专业=法学；排除地域=上海" in result
    assert "当前方案里较贴近的有1个，明显冲突的有1个" in result


def test_run_planning_review_prefers_latest_user_profile_over_stale_explicit_profile():
    ctx = _make_ctx("review-session-latest")
    response = {
        "code": 0,
        "data": {
            "summary": {"passedCount": 9, "warnCount": 1, "riskCount": 0},
            "checks": [{"passed": False, "summary": "部分专业组主要依靠非意向专业托底"}],
            "compensationPreview": {"actions": []},
        },
    }
    state_response = {
        "code": 0,
        "data": {
            "profileState": {
                "explicitProfile": {
                    "positiveMajors": ["哲学类", "金融学类"],
                }
            },
            "orderedPlanState": {
                "summary": {"total": 1},
                "items": [
                    {"position": 1, "schoolName": "汉口学院第01组", "majorName": "网络与新媒体", "tier": "冲"},
                ]
            },
        },
    }
    user_profile_response = {
        "code": 0,
        "data": {
            "userprofile": {
                "major_intent": {
                    "level3": ["网络与新媒体", "跨境电子商务"],
                }
            }
        },
    }
    ordered_response = {
        "code": 0,
        "data": {
            "items": state_response["data"]["orderedPlanState"]["items"],
            "summary": {"total": 1},
        },
    }

    with (
        patch("app.tools.planning_workflow_tool._run_planning_review_request", AsyncMock(return_value=response)) as mock_request,
        patch("app.tools.planning_workflow_tool._get_planning_state_request", AsyncMock(return_value=state_response)) as mock_state,
        patch("app.tools.planning_workflow_tool._get_user_profile_request", AsyncMock(return_value=user_profile_response)) as mock_profile,
        patch("app.tools.planning_workflow_tool._get_planning_ordered_plan_request", AsyncMock(return_value=ordered_response)) as mock_ordered,
    ):
        result = asyncio.run(run_planning_review(ctx))

    mock_request.assert_awaited_once_with(1, "review-session-latest")
    mock_state.assert_awaited_once_with("review-session-latest")
    mock_profile.assert_awaited_once_with("review-session-latest")
    mock_ordered.assert_awaited_once_with("review-session-latest")
    assert "当前偏好/要求：偏好专业=网络与新媒体,跨境电子商务" in result
    assert "当前方案里较贴近的有1个，没有看到明显冲突" in result


def test_analyze_planning_plan_adjustment_includes_intent_relation_summary():
    ctx = _make_ctx("adjust-session")
    adjustment_response = {
        "code": 0,
        "data": {
            "analysis": {
                "summaryText": "整体梯度还可以，但保底略弱。",
                "rules": [{"hit": True, "summary": "保区占比偏低", "suggestionTypes": ["add"]}],
            },
            "suggestions": {
                "addSuggestions": [{"title": "补充保底", "description": "补一些更稳的北京院校。"}],
                "reorderSuggestions": [],
                "replaceSuggestions": [],
                "removeSuggestions": [],
            },
        },
    }
    state_response = {
        "code": 0,
        "data": {
            "profileState": {
                "explicitProfile": {
                    "positiveRegions": ["北京"],
                },
                "latentProfile": {
                    "futureDevelopment": {"careerTypes": ["体制内/考公导向"]},
                },
            },
            "orderedPlanState": {
                "summary": {"total": 2},
                "items": [
                    {"position": 1, "schoolName": "北京大学", "majorName": "法学", "provinceName": "北京", "schoolCategory": "政法", "tier": "冲"},
                    {"position": 2, "schoolName": "武汉大学", "majorName": "计算机科学与技术", "provinceName": "湖北", "tier": "稳"},
                ]
            },
        },
    }
    ordered_response = {
        "code": 0,
        "data": {
            "items": state_response["data"]["orderedPlanState"]["items"],
            "summary": {"total": 2},
        },
    }

    with (
        patch("app.tools.planning_workflow_tool._analyze_planning_plan_adjustment_request", AsyncMock(return_value=adjustment_response)) as mock_request,
        patch("app.tools.planning_workflow_tool._get_planning_state_request", AsyncMock(return_value=state_response)) as mock_state,
        patch("app.tools.planning_workflow_tool._get_planning_ordered_plan_request", AsyncMock(return_value=ordered_response)) as mock_ordered,
    ):
        result = asyncio.run(analyze_planning_plan_adjustment(ctx))

    mock_request.assert_awaited_once_with(1, "adjust-session")
    mock_state.assert_awaited_once_with("adjust-session")
    mock_ordered.assert_awaited_once_with("adjust-session")
    assert "总体判断：整体梯度还可以，但保底略弱。" in result
    assert "当前偏好/要求：偏好地域=北京；发展方向=体制内/考公导向" in result
    assert "贴近偏好：北京大学-法学(冲)@1" in result


def test_query_planning_plan_overview_falls_back_to_draft_when_no_ordered_plan():
    ctx = _make_ctx("overview-draft-session")
    state_response = {
        "code": 0,
        "data": {
            "phase": "draft",
            "version": 4,
            "staleFlags": {"candidatePool": False, "orderedPlan": True, "review": False},
            "draftPlanState": {"summary": {"total": 12}},
            "orderedPlanState": {"summary": {"total": 0}},
            "reviewState": {"summary": {"warnCount": 0, "riskCount": 0}, "checks": []},
            "pendingActions": [],
        },
    }
    draft_response = {
        "code": 0,
        "data": {
            "items": [
                {"schoolName": "北京联合大学", "majorName": "电气工程及其自动化", "tier": "稳", "locked": True},
            ],
            "summary": {
                "total": 12,
                "tierCounts": {"冲": 4, "稳": 4, "保": 4},
            },
        },
    }

    with (
        patch("app.tools.planning_workflow_tool._get_planning_state_request", AsyncMock(return_value=state_response)) as mock_state,
        patch("app.tools.planning_workflow_tool._get_working_plan_request", AsyncMock(return_value=draft_response)) as mock_draft,
    ):
        result = asyncio.run(query_planning_plan_overview(ctx))

    mock_state.assert_awaited_once_with("overview-draft-session")
    mock_draft.assert_awaited_once_with("overview-draft-session")
    assert "当前已加入方案：12个志愿，尚未形成最终排序" in result
    assert "已加入方案示例：北京联合大学-电气工程及其自动化(稳)[锁定]" in result
    assert "待刷新状态" not in result


def test_query_planning_plan_overview_includes_target_gap_when_total_insufficient():
    ctx = _make_ctx("overview-gap-session")
    state_response = {
        "code": 0,
        "data": {
            "phase": "ordered",
            "version": 11,
            "staleFlags": {"candidatePool": False, "orderedPlan": False, "review": False},
            "candidatePoolState": {"requiredCount": 30},
            "draftPlanState": {"summary": {"unitTotal": 24, "targetUnitCount": 30}},
            "orderedPlanState": {"summary": {"unitTotal": 24, "targetUnitCount": 30}},
            "reviewState": {"summary": {"warnCount": 1, "riskCount": 1}, "checks": [{"passed": False, "summary": "当前志愿数量少于官方要求"}]},
            "pendingActions": [{"summary": "补足志愿总数量"}],
        },
    }
    ordered_response = {
        "code": 0,
        "data": {
            "items": [
                {"position": 1, "schoolName": "重庆理工大学", "majorName": "计算机科学与技术", "tier": "冲"},
            ],
            "summary": {
                "unitTotal": 24,
                "targetUnitCount": 30,
                "tierCounts": {"冲": 8, "稳": 8, "保": 8},
                "gradientOk": True,
                "safetyOk": True,
            },
        },
    }

    with (
        patch("app.tools.planning_workflow_tool._get_planning_state_request", AsyncMock(return_value=state_response)),
        patch("app.tools.planning_workflow_tool._get_planning_ordered_plan_request", AsyncMock(return_value=ordered_response)),
    ):
        result = asyncio.run(query_planning_plan_overview(ctx))

    assert "24/30个志愿" in result
    assert "当前志愿数量不足，还差 6 个" in result


def test_build_plan_status_overview_facts_includes_candidate_supply_shortage():
    planning_state = {
        "volunteerModel": "major",
        "candidatePoolState": {
            "requiredCount": 80,
            "requiredTierCounts": {"冲": 24, "稳": 24, "保": 32},
            "summary": {
                "total": 4235,
                "tierCounts": {"冲": 4235, "稳": 0, "保": 0},
            },
        },
        "orderedPlanState": {
            "summary": {
                "total": 80,
                "targetCount": 80,
                "tierCounts": {"冲": 80, "稳": 0, "保": 0},
            },
            "items": [],
        },
        "reviewState": {"summary": {"riskCount": 0, "warnCount": 0}},
    }

    facts = _build_plan_status_overview_facts(
        planning_state,
        ordered_state=planning_state["orderedPlanState"],
    )

    supply = facts["candidate_supply"]
    assert supply["candidate_total"] == 4235
    assert supply["candidate_tier_counts"] == {"冲": 4235, "稳": 0, "保": 0}
    assert supply["missing_supply_tiers"] == ["稳", "保"]
    assert "当前没有可直接补入的稳、保区候选" in supply["summary"]


def test_compensation_preview_facts_separate_legacy_add_from_structural_actions():
    facts = _build_compensation_preview_facts(
        {
            "actions": [
                {"summary": "补足志愿总数量", "volunteerIds": ["v1", "v2"], "actionType": "add"},
                {
                    "summary": "替换高收费志愿",
                    "removeVolunteerIds": ["old-1"],
                    "candidateVolunteerIds": ["new-1"],
                    "actionType": "replace",
                },
            ]
        }
    )

    assert facts["action_count"] == 2
    assert facts["estimated_fill_count"] == 2
    assert facts["legacy_add_action_count"] == 1
    assert facts["legacy_add_estimated_fill_count"] == 2


def test_query_planning_draft_uses_session_and_formats_result():
    ctx = _make_ctx("draft-session")
    response = {
        "code": 0,
        "data": {
            "items": [
                {"schoolName": "北京大学", "majorName": "经济学", "tier": "sprint", "locked": True},
                {"schoolName": "同济大学", "majorName": "建筑学", "tier": "safe"},
            ],
            "bannedVolunteerIds": ["v9"],
            "summary": {
                "total": 2,
                "tierCounts": {"sprint": 1, "safe": 1, "protect": 0},
            },
        },
    }

    with patch(
        "app.tools.planning_workflow_tool._get_working_plan_request",
        AsyncMock(return_value=response),
    ) as mock_request:
        result = asyncio.run(query_planning_draft(ctx))

    mock_request.assert_awaited_once_with("draft-session")
    assert "已加入方案概况：" in result
    assert "已加入方案数：2" in result
    assert "区间分布：冲1 / 稳1 / 保0" in result
    assert "北京大学-经济学(sprint)[锁定]" in result


def test_query_planning_draft_prefers_unit_summary_in_major_group_mode():
    ctx = _make_ctx("draft-session")
    response = {
        "code": 0,
        "data": {
            "items": [],
            "bannedVolunteerIds": [],
            "summary": {
                "unitTotal": 24,
                "total": 48,
                "unitTierCounts": {"冲": 8, "稳": 8, "保": 8},
                "tierCounts": {"冲": 16, "稳": 16, "保": 16},
            },
        },
    }

    with patch(
        "app.tools.planning_workflow_tool._get_working_plan_request",
        AsyncMock(return_value=response),
    ) as mock_request:
        result = asyncio.run(query_planning_draft(ctx))

    mock_request.assert_awaited_once_with("draft-session")
    assert "已加入方案数：24" in result
    assert "区间分布：冲8 / 稳8 / 保8" in result


def test_query_planning_candidate_pool_uses_filters_and_formats_result():
    ctx = _make_ctx("candidate-session")
    response = {
        "code": 0,
        "data": {
            "items": [
                {
                    "schoolName": "北京大学",
                    "majorName": "经济学",
                    "tier": "sprint",
                    "provinceName": "北京",
                    "volunteerId": "v101",
                    "finalScore": 95.5,
                    "admissionRatio": 35,
                    "schoolNature": "公办",
                    "tuitionPerYear": 5000,
                },
                {
                    "schoolName": "中国人民大学",
                    "majorName": "金融学",
                    "tier": "safe",
                    "provinceName": "北京",
                    "volunteerId": "v102",
                    "finalScore": 92.0,
                },
            ],
            "page": 1,
            "pageSize": 10,
            "total": 2,
            "viewSummary": {
                "poolEntryTotal": 20,
                "poolUnitTotal": 15,
                "viewEntryTotal": 2,
                "viewUnitTotal": 2,
                "loadedEntryCount": 2,
                "loadedUnitCount": 2,
            },
        },
    }

    with patch(
        "app.tools.planning_workflow_tool._query_planning_candidate_pool_request",
        AsyncMock(return_value=response),
    ) as mock_request:
        result = asyncio.run(
            query_planning_candidate_pool(
                ctx,
                tiers=["sprint", "safe"],
                province_names=["北京"],
                major_keywords=["经济", "金融"],
                sort_field="finalScore",
                sort_order="desc",
                page=1,
                page_size=10,
            )
        )

    mock_request.assert_awaited_once_with(
        1,
        "candidate-session",
        tiers=["sprint", "safe"],
        province_names=["北京"],
        city_names=None,
        school_keywords=None,
        major_keywords=["经济", "金融"],
        school_tags=None,
        major_tags=None,
        sort_field="finalScore",
        sort_order="desc",
        page=1,
        page_size=10,
    )
    assert "候选志愿查询结果：" in result
    assert "命中数量：2" in result
    assert "当前筛选视图：2条 / 2个志愿单元；完整候选池：20条 / 15个志愿单元" in result
    assert "北京大学-经济学(sprint/北京/录取率35%/公办/学费5000元/年) 分值95.5" in result
    assert "id=v101" not in result
    assert "volunteerId" not in result


def test_select_remove_lock_and_ban_planning_draft_items_use_session():
    ctx = _make_ctx("draft-edit-session")
    response = {
        "code": 0,
        "data": {
            "draftPlanState": {
                "items": [
                    {"schoolName": "北京大学", "majorName": "经济学", "tier": "sprint", "locked": True},
                ],
                "bannedVolunteerIds": ["v3"],
                "summary": {
                    "total": 1,
                    "tierCounts": {"sprint": 1, "safe": 0, "protect": 0},
                },
            }
        },
    }

    with (
        patch("app.tools.planning_workflow_tool._select_working_plan_items_request", AsyncMock(return_value=response)) as mock_select,
        patch("app.tools.planning_workflow_tool._remove_working_plan_items_request", AsyncMock(return_value=response)) as mock_remove,
        patch("app.tools.planning_workflow_tool._ban_working_plan_items_request", AsyncMock(return_value=response)) as mock_ban,
    ):
        select_result = asyncio.run(select_planning_draft_items(ctx, ["v1", "v2"]))
        remove_result = asyncio.run(remove_planning_draft_items(ctx, ["v1"]))
        lock_result = asyncio.run(lock_planning_draft_items(ctx, ["v1"], locked=True))
        ban_result = asyncio.run(ban_planning_draft_items(ctx, ["v3"]))

    mock_select.assert_awaited_once_with(1, "draft-edit-session", ["v1", "v2"], source="user_agent")
    mock_remove.assert_awaited_once_with("draft-edit-session", ["v1"])
    mock_ban.assert_awaited_once_with("draft-edit-session", ["v3"])
    assert "已加入2个志愿到方案。" in select_result
    assert "已从方案移出1个志愿。" in remove_result
    assert "新版工作台暂不提供固定/锁定志愿入口" in lock_result
    assert "已禁用1个候选志愿，并同步更新当前方案。" in ban_result


def test_query_planning_ordered_plan_uses_session_and_formats_result():
    ctx = _make_ctx("ordered-session")
    response = {
        "code": 0,
        "data": {
            "items": [
                {"position": 1, "schoolName": "北京大学", "majorName": "法学", "tier": "sprint", "pinned": True},
                {"position": 2, "schoolName": "中山大学", "majorName": "临床医学", "tier": "safe"},
            ],
            "summary": {
                "total": 2,
                "tierCounts": {"sprint": 1, "safe": 1, "protect": 0},
                "gradientOk": True,
                "safetyOk": False,
            },
        },
    }

    with patch(
        "app.tools.planning_workflow_tool._get_planning_ordered_plan_request",
        AsyncMock(return_value=response),
    ) as mock_request:
        result = asyncio.run(query_planning_ordered_plan(ctx))

    mock_request.assert_awaited_once_with("ordered-session")
    assert "方案志愿概况：" in result
    assert "排序总数：2" in result
    assert "录取率梯度是否达标：是" in result
    assert "保底是否达标：否" in result
    assert "北京大学-法学(sprint)@1" in result
    assert "[固定]" not in result


def test_generate_planning_ordered_plan_requires_confirmation():
    ctx = _make_ctx("generate-session")

    with patch(
        "app.tools.planning_workflow_tool._generate_planning_ordered_plan_request",
        AsyncMock(),
    ) as mock_request:
        result = asyncio.run(generate_planning_ordered_plan(ctx))

    mock_request.assert_not_awaited()
    assert "请先在对话中获得用户明确确认" in result


def test_generate_planning_ordered_plan_formats_ordered_state():
    ctx = _make_ctx("generate-session")
    response = {
        "code": 0,
        "data": {
            "orderedPlanState": {
                "items": [{"position": 1, "schoolName": "南开大学", "majorName": "金融学", "tier": "safe"}],
                "summary": {
                    "total": 1,
                    "tierCounts": {"sprint": 0, "safe": 1, "protect": 0},
                    "gradientOk": True,
                    "safetyOk": True,
                },
            }
        },
    }

    with patch(
        "app.tools.planning_workflow_tool._generate_planning_ordered_plan_request",
        AsyncMock(return_value=response),
    ) as mock_request, patch(
        "app.tools.planning_workflow_tool._run_planning_review_request",
        AsyncMock(return_value={"code": 0, "data": {}}),
    ), patch(
        "app.tools.planning_workflow_tool._get_planning_state_request",
        AsyncMock(return_value=response),
    ):
        result = asyncio.run(
            generate_planning_ordered_plan(
                ctx,
                user_confirmed=True,
                force_regenerate=True,
                regroup_by_tier=True,
            )
        )

    mock_request.assert_awaited_once_with(
        1,
        "generate-session",
        force_regenerate=True,
        regroup_by_tier=True,
    )
    assert "已生成最新排序方案。" in result
    assert "南开大学-金融学(safe)@1" in result


def test_remove_planning_ordered_items_refreshes_ordered_state():
    ctx = _make_ctx("ordered-remove-session")
    before_ordered_response = {
        "code": 0,
        "data": {
            "items": [{"volunteerId": "v1", "position": 1, "schoolName": "清华大学", "majorName": "法学", "tier": "sprint"}],
            "summary": {
                "total": 1,
                "tierCounts": {"sprint": 1, "safe": 0, "protect": 0},
            },
        },
    }
    remove_response = {
        "code": 0,
        "data": {
            "draftPlanState": {
                "items": [],
                "summary": {
                    "total": 0,
                    "tierCounts": {"sprint": 0, "safe": 0, "protect": 0},
                },
            }
        },
    }
    ordered_response = {
        "code": 0,
        "data": {
            "orderedPlanState": {
                "items": [{"position": 1, "schoolName": "北京大学", "majorName": "法学", "tier": "sprint"}],
                "summary": {
                    "total": 1,
                    "tierCounts": {"sprint": 1, "safe": 0, "protect": 0},
                    "gradientOk": True,
                    "safetyOk": True,
                },
            }
        },
    }

    with (
        patch(
            "app.tools.planning_workflow_tool._get_planning_ordered_plan_request",
            AsyncMock(return_value=before_ordered_response),
        ) as mock_before,
        patch(
            "app.tools.planning_workflow_tool._remove_working_plan_items_request",
            AsyncMock(return_value=remove_response),
        ) as mock_remove,
        patch(
            "app.tools.planning_workflow_tool._generate_planning_ordered_plan_request",
            AsyncMock(return_value=ordered_response),
        ) as mock_generate,
        patch(
            "app.tools.planning_workflow_tool._run_planning_review_request",
            AsyncMock(return_value={"code": 0, "data": {}}),
        ),
        patch(
            "app.tools.planning_workflow_tool._get_planning_state_request",
            AsyncMock(return_value={"code": 0, "data": ordered_response["data"]}),
        ),
    ):
        result = asyncio.run(remove_planning_ordered_items(ctx, ["v1"]))

    mock_before.assert_awaited_once_with("ordered-remove-session")
    mock_remove.assert_awaited_once_with("ordered-remove-session", ["v1"])
    mock_generate.assert_awaited_once_with(
        1,
        "ordered-remove-session",
        force_regenerate=True,
        regroup_by_tier=True,
    )
    assert "已从当前方案移出1个志愿，并同步刷新排序方案。" in result
    assert "排序总数：1" in result


def test_remove_planning_ordered_items_falls_back_to_ban_when_target_still_remains():
    ctx = _make_ctx("ordered-remove-session")
    before_ordered_response = {
        "code": 0,
        "data": {
            "items": [
                {"volunteerId": "v1", "position": 1, "schoolName": "北京大学", "majorName": "法学", "tier": "sprint"},
                {"volunteerId": "v2", "position": 2, "schoolName": "复旦大学", "majorName": "新闻学", "tier": "safe"},
            ],
            "summary": {
                "total": 2,
                "tierCounts": {"sprint": 1, "safe": 1, "protect": 0},
            },
        },
    }
    remove_response = {
        "code": 0,
        "data": {"draftPlanState": {"items": [], "summary": {"total": 1}}},
    }
    first_ordered_state = {
        "items": [
            {"volunteerId": "v1", "position": 1, "schoolName": "北京大学", "majorName": "法学", "tier": "sprint"},
            {"volunteerId": "v2", "position": 2, "schoolName": "复旦大学", "majorName": "新闻学", "tier": "safe"},
        ],
        "summary": {
            "total": 2,
            "tierCounts": {"sprint": 1, "safe": 1, "protect": 0},
            "gradientOk": True,
            "safetyOk": True,
        },
    }
    second_ordered_state = {
        "items": [
            {"volunteerId": "v2", "position": 1, "schoolName": "复旦大学", "majorName": "新闻学", "tier": "safe"},
        ],
        "summary": {
            "total": 1,
            "tierCounts": {"sprint": 0, "safe": 1, "protect": 0},
            "gradientOk": True,
            "safetyOk": True,
        },
    }
    ban_response = {
        "code": 0,
        "data": {
            "draftPlanState": {
                "items": [{"volunteerId": "v2", "schoolName": "复旦大学", "majorName": "新闻学", "tier": "safe"}],
                "bannedVolunteerIds": ["v1"],
                "summary": {"total": 1},
            }
        },
    }

    with (
        patch(
            "app.tools.planning_workflow_tool._get_planning_ordered_plan_request",
            AsyncMock(return_value=before_ordered_response),
        ),
        patch(
            "app.tools.planning_workflow_tool._remove_working_plan_items_request",
            AsyncMock(return_value=remove_response),
        ) as mock_remove,
        patch(
            "app.tools.planning_workflow_tool._ban_working_plan_items_request",
            AsyncMock(return_value=ban_response),
        ) as mock_ban,
        patch(
            "app.tools.planning_workflow_tool._generate_planning_ordered_plan_request",
            AsyncMock(
                side_effect=[
                    {"code": 0, "data": {"orderedPlanState": first_ordered_state}},
                    {"code": 0, "data": {"orderedPlanState": second_ordered_state}},
                ]
            ),
        ) as mock_generate,
        patch(
            "app.tools.planning_workflow_tool._run_planning_review_request",
            AsyncMock(return_value={"code": 0, "data": {}}),
        ),
        patch(
            "app.tools.planning_workflow_tool._get_planning_state_request",
            AsyncMock(
                side_effect=[
                    {"code": 0, "data": {"orderedPlanState": first_ordered_state}},
                    {"code": 0, "data": {"orderedPlanState": second_ordered_state}},
                ]
            ),
        ),
    ):
        result = asyncio.run(remove_planning_ordered_items(ctx, ["v1"]))

    mock_remove.assert_awaited_once_with("ordered-remove-session", ["v1"])
    mock_ban.assert_awaited_once_with("ordered-remove-session", ["v1"])
    assert mock_generate.await_count == 2
    assert "已从当前方案移出1个志愿，并同步刷新排序方案。" in result
    assert "检测到常规移除后仍有目标残留，已自动禁用这些目标" in result
    assert "移出的志愿：北京大学-法学（sprint）" in result
    assert "仍保留的志愿" not in result
    assert "排序总数：1" in result


def test_remove_planning_ordered_items_reports_lingering_target_after_ban_fallback():
    ctx = _make_ctx("ordered-remove-session")
    before_ordered_response = {
        "code": 0,
        "data": {
            "items": [
                {"volunteerId": "v1", "position": 1, "schoolName": "北京大学", "majorName": "法学", "tier": "sprint"},
                {"volunteerId": "v2", "position": 2, "schoolName": "复旦大学", "majorName": "新闻学", "tier": "safe"},
            ],
            "summary": {
                "total": 2,
                "tierCounts": {"sprint": 1, "safe": 1, "protect": 0},
            },
        },
    }
    remove_response = {
        "code": 0,
        "data": {"draftPlanState": {"items": [], "summary": {"total": 2}}},
    }
    lingering_ordered_state = {
        "items": [
            {"volunteerId": "v1", "position": 1, "schoolName": "北京大学", "majorName": "法学", "tier": "sprint"},
            {"volunteerId": "v2", "position": 2, "schoolName": "复旦大学", "majorName": "新闻学", "tier": "safe"},
        ],
        "summary": {
            "total": 2,
            "tierCounts": {"sprint": 1, "safe": 1, "protect": 0},
            "gradientOk": True,
            "safetyOk": True,
        },
    }
    ban_response = {
        "code": 0,
        "data": {
            "draftPlanState": {
                "items": [{"volunteerId": "v2", "schoolName": "复旦大学", "majorName": "新闻学", "tier": "safe"}],
                "bannedVolunteerIds": ["v1"],
                "summary": {"total": 1},
            }
        },
    }

    with (
        patch(
            "app.tools.planning_workflow_tool._get_planning_ordered_plan_request",
            AsyncMock(return_value=before_ordered_response),
        ),
        patch(
            "app.tools.planning_workflow_tool._remove_working_plan_items_request",
            AsyncMock(return_value=remove_response),
        ),
        patch(
            "app.tools.planning_workflow_tool._ban_working_plan_items_request",
            AsyncMock(return_value=ban_response),
        ) as mock_ban,
        patch(
            "app.tools.planning_workflow_tool._generate_planning_ordered_plan_request",
            AsyncMock(
                side_effect=[
                    {"code": 0, "data": {"orderedPlanState": lingering_ordered_state}},
                    {"code": 0, "data": {"orderedPlanState": lingering_ordered_state}},
                ]
            ),
        ) as mock_generate,
        patch(
            "app.tools.planning_workflow_tool._run_planning_review_request",
            AsyncMock(return_value={"code": 0, "data": {}}),
        ),
        patch(
            "app.tools.planning_workflow_tool._get_planning_state_request",
            AsyncMock(
                side_effect=[
                    {"code": 0, "data": {"orderedPlanState": lingering_ordered_state}},
                    {"code": 0, "data": {"orderedPlanState": lingering_ordered_state}},
                ]
            ),
        ),
    ):
        result = asyncio.run(remove_planning_ordered_items(ctx, ["v1"]))

    mock_ban.assert_awaited_once_with("ordered-remove-session", ["v1"])
    assert mock_generate.await_count == 2
    assert "已尝试移出1个志愿，但仍有1个志愿保留在当前方案中。" in result
    assert "仍保留的志愿：北京大学-法学（sprint）" in result
    assert "移出的志愿：北京大学-法学（sprint）" not in result


def test_select_planning_ordered_items_refreshes_ordered_state():
    ctx = _make_ctx("ordered-add-session")
    select_response = {
        "code": 0,
        "data": {
            "draftPlanState": {
                "items": [{"schoolName": "北京大学", "majorName": "法学", "tier": "sprint"}],
                "summary": {
                    "total": 1,
                    "tierCounts": {"sprint": 1, "safe": 0, "protect": 0},
                },
            }
        },
    }
    ordered_response = {
        "code": 0,
        "data": {
            "orderedPlanState": {
                "items": [{"position": 1, "schoolName": "北京大学", "majorName": "法学", "tier": "sprint"}],
                "summary": {
                    "total": 1,
                    "tierCounts": {"sprint": 1, "safe": 0, "protect": 0},
                    "gradientOk": True,
                    "safetyOk": True,
                },
            }
        },
    }

    with (
        patch(
            "app.tools.planning_workflow_tool._select_working_plan_items_request",
            AsyncMock(return_value=select_response),
        ) as mock_select,
        patch(
            "app.tools.planning_workflow_tool._generate_planning_ordered_plan_request",
            AsyncMock(return_value=ordered_response),
        ) as mock_generate,
        patch(
            "app.tools.planning_workflow_tool._run_planning_review_request",
            AsyncMock(return_value={"code": 0, "data": {}}),
        ),
        patch(
            "app.tools.planning_workflow_tool._get_planning_state_request",
            AsyncMock(return_value={"code": 0, "data": ordered_response["data"]}),
        ),
    ):
        result = asyncio.run(select_planning_ordered_items(ctx, ["v1"], source="planning_router"))

    mock_select.assert_awaited_once_with(1, "ordered-add-session", ["v1"], source="planning_router")
    mock_generate.assert_awaited_once_with(
        1,
        "ordered-add-session",
        force_regenerate=True,
        regroup_by_tier=True,
    )
    assert "已把1个志愿加入当前方案，并同步刷新排序结果。" in result
    assert "排序总数：1" in result


def test_move_keeps_ordered_backend():
    ctx = _make_ctx("move-session")
    response = {
        "code": 0,
        "data": {
            "orderedPlanState": {
                "items": [{"position": 3, "schoolName": "武汉大学", "majorName": "测绘工程", "tier": "safe"}],
                "summary": {
                    "total": 1,
                    "tierCounts": {"sprint": 0, "safe": 1, "protect": 0},
                    "gradientOk": True,
                    "safetyOk": True,
                },
            }
        },
    }

    with (
        patch("app.tools.planning_workflow_tool._move_planning_ordered_item_request", AsyncMock(return_value=response)) as mock_move,
        patch("app.tools.planning_workflow_tool._run_planning_review_request", AsyncMock(return_value={"code": 0, "data": {}})),
        patch("app.tools.planning_workflow_tool._get_planning_state_request", AsyncMock(return_value={"code": 0, "data": response["data"]})),
    ):
        move_result = asyncio.run(move_planning_ordered_item(ctx, "v1", 3))

    mock_move.assert_awaited_once_with("move-session", "v1", 3)
    assert "已将志愿移动到第3位。" in move_result


def test_generate_planning_fix_proposals_formats_status_and_warnings():
    ctx = _make_ctx("fix-preview-session")
    response = {
        "code": 0,
        "data": {
            "proposalSource": "review_check",
            "proposals": [
                {
                    "proposalSource": "review_check",
                    "title": "修复高收费",
                    "status": "preview_only",
                    "strategy": "replace_risk_items",
                    "impact": "当前问题涉及 1 个专业组、1 条志愿。",
                    "actions": [
                        {
                            "actionType": "replace_volunteers",
                            "summary": "替换风险志愿",
                            "replacementPairs": [{"fromVolunteerId": "v1", "toVolunteerId": "v2"}],
                        }
                    ],
                    "dryRunResult": {
                        "removeVolunteerCount": 1,
                        "addVolunteerCount": 1,
                        "warnings": ["当前只支持预览，不会自动执行。"],
                    },
                },
                {
                    "title": "修复数量缺口",
                    "status": "ready",
                    "strategy": "fill_missing_count",
                    "actions": [{"actionType": "fill_total_count", "summary": "补足志愿总数量"}],
                    "dryRunResult": {"removeVolunteerCount": 0, "addVolunteerCount": 2},
                },
                {
                    "title": "修复录取率梯度断层",
                    "status": "blocked",
                    "strategy": "fill_probability_gap",
                    "blockingReason": "当前候选不足。",
                    "blockingReasonCodes": ["probability_gap_candidate_insufficient"],
                    "candidateShortages": [
                        {
                            "strategy": "fill_probability_gap",
                            "sourceCheckCode": "probability_gap",
                            "scope": "candidate_pool",
                            "reasonCode": "probability_gap_candidate_insufficient",
                            "requiredCount": 1,
                            "availableCount": 0,
                            "message": "当前可用于规划的候选池里，断层中间录取率候选不足。",
                        }
                    ],
                    "actions": [],
                    "dryRunResult": {"warnings": []},
                },
            ]
        },
    }

    with patch(
        "app.tools.planning_workflow_tool._generate_planning_fix_proposals_request",
        AsyncMock(return_value=response),
    ) as mock_request:
        result = asyncio.run(generate_planning_fix_proposals(ctx))

    mock_request.assert_awaited_once_with(1, "fix-preview-session")
    assert "已生成当前方案的处理建议预览。" in result
    assert "处理高收费：仅供参考，需要进一步确认取舍" in result
    assert "预计移除1条、补入1条" in result
    assert "处理数量缺口：可确认后执行" in result
    assert "预计补入2条" in result
    assert "移除0" not in result
    assert "需要注意：当前候选不足；当前可用于规划的可选范围里，断层中间录取率候选不足" in result
    assert "候选边界" not in result
    assert "处理边界" not in result
    assert "暂不能自动处理" not in result
    assert "需要进一步取舍的建议不会直接执行" in result

    facts = _fix_proposal_facts(response["data"])
    assert facts["proposal_source"] == "review_check"
    assert facts["proposals"][0]["proposal_source"] == "review_check"
    assert facts["proposals"][2]["blocking_reason_codes"] == ["probability_gap_candidate_insufficient"]
    assert facts["proposals"][2]["candidate_shortages"][0]["scope"] == "candidate_pool"
    assert facts["proposals"][2]["candidate_shortages"][0]["reason_code"] == "probability_gap_candidate_insufficient"


def test_generate_planning_fix_proposals_prefers_hard_constraint_shortage_guidance():
    ctx = _make_ctx("fix-hard-constraint-session")
    response = {
        "code": 0,
        "data": {
            "proposals": [
                {
                    "title": "修复冲稳保结构",
                    "status": "blocked",
                    "strategy": "rebalance_tier_ratio",
                    "blockingReason": "当前候选不足。",
                    "blockingReasonCodes": ["tier_candidate_insufficient"],
                    "candidateShortages": [
                        {
                            "strategy": "rebalance_tier_ratio",
                            "sourceCheckCode": "ratio_distribution",
                            "scope": "hard_constraints",
                            "reasonCode": "tier_candidate_insufficient",
                            "targetTier": "保",
                        }
                    ],
                    "actions": [],
                    "dryRunResult": {"warnings": []},
                }
            ]
        },
    }

    with patch(
        "app.tools.planning_workflow_tool._generate_planning_fix_proposals_request",
        AsyncMock(return_value=response),
    ):
        result = asyncio.run(generate_planning_fix_proposals(ctx))

    assert "需要注意：当前候选不足；已确认的报考条件收窄了可选范围，当前可用于补位的候选不足" in result
    assert "硬性要求" not in result
    assert "处理边界：当前可用于规划的候选池里目标冲稳保区间候选不足" not in result


def test_apply_planning_fix_proposal_requires_confirmation():
    ctx = _make_ctx("fix-apply-session")

    with patch(
        "app.tools.planning_workflow_tool._apply_planning_fix_proposal_request",
        AsyncMock(),
    ) as mock_request:
        result = asyncio.run(
            apply_planning_fix_proposal(
                ctx,
                proposal_id="fp_1",
                source_version_guard=12,
            )
        )

    mock_request.assert_not_awaited()
    assert "请先让用户确认具体处理建议" in result


def test_apply_planning_fix_proposal_formats_repair_report():
    ctx = _make_ctx("fix-apply-session")
    response = {
        "code": 0,
        "data": {
            "status": "applied",
            "repairReport": {
                "strategy": "fill_missing_count",
                "proposalTitle": "补齐志愿数量",
                "proposalSummary": "当前方案数量不足，需要补充志愿。",
                "proposalImpact": "预计补充 2 条志愿。",
                "dryRunMessage": "补入 2 条，不移除现有志愿。",
                "addedVolunteerCount": 2,
                "removedVolunteerCount": 0,
                "postValidationPassed": True,
                "messages": ["已补充 2 条志愿。"],
            },
        },
    }

    with patch(
        "app.tools.planning_workflow_tool._apply_planning_fix_proposal_request",
        AsyncMock(return_value=response),
    ) as mock_request:
        result = asyncio.run(
            apply_planning_fix_proposal(
                ctx,
                proposal_id="fp_1",
                source_version_guard=12,
                user_confirmed=True,
                regenerate_ordered_plan=False,
                rerun_review=True,
            )
        )

    mock_request.assert_awaited_once_with(
        1,
        "fix-apply-session",
        proposal_id="fp_1",
        source_version_guard=12,
        regenerate_ordered_plan=False,
        rerun_review=True,
    )
    assert "已按处理建议更新方案" in result
    assert "处理内容：补齐志愿数量" in result
    assert "对应问题：当前方案数量不足，需要补充志愿。" in result
    assert "处理方式：fill_missing_count" in result
    assert "调整结果：补入2条" in result
    assert "移除0条" not in result
    assert "影响范围：预计补充 2 条志愿。" in result
    assert "处理前预览：补入 2 条，不移除现有志愿。" in result
    assert "这次对应的问题已通过检查" in result
