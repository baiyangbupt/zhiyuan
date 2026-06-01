"""Sync-wrapper scenario tests for planning update/review flows.

These focus on agent-side planning actions and orchestration under realistic
state transitions, without relying on pytest-asyncio.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.agent.context import PlanningSummary, RequestContext
from app.tools.plan_execution_tool import execute_plan_action
from app.tools.plan_orchestration_tool import plan_next_action
from app.tools.planning_router_tool import handle_planning_request
from app.tools.planning_workflow_tool import (
    apply_planning_compensation,
    analyze_planning_plan_adjustment,
    generate_planning_initial_plan,
    generate_planning_ordered_plan,
    preview_planning_compensation,
    query_planning_state,
    remove_planning_ordered_items,
)


def _ctx(session_id: str = "900") -> SimpleNamespace:
    return SimpleNamespace(deps=RequestContext(userid="u1", sessionid=session_id))


def _ctx_with_pending(action_family: str, session_id: str = "900") -> SimpleNamespace:
    return SimpleNamespace(
        deps=RequestContext(
            userid="u1",
            sessionid=session_id,
            chat_history=[{"role": "user", "content": "确认"}],
            pending_plan_action={"action_family": action_family},
        )
    )


def _payload(action_family: str, **kwargs) -> str:
    base = {
        "stage": "apply",
        "action_family": action_family,
        "context_summary": "阶段=ordered；方案=20/30",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": False,
        "intent_relation": "support",
        "atomic_actions": [],
    }
    base.update(kwargs)
    return json.dumps(base, ensure_ascii=False)


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
        pending_action_count=0,
        pending_action_summaries=[],
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
            "pendingActions": [
                {"summary": "补 2 个保底专业组"},
                {"summary": "微调 1 处相邻顺序"},
            ],
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
    assert "当前待处理建议：2项，主要为补 2 个保底专业组；微调 1 处相邻顺序" in result
    assert "待刷新状态：排序待刷新；审查结果待刷新" in result


def test_planning_scenario_plan_adjustment_analysis_summarizes_problem_types():
    with patch(
        "app.tools.planning_router_tool._run_planned_request",
        AsyncMock(
            return_value=(
                "我先从当前方案里帮你看了一遍可优化的地方。\n"
                "- 总体判断：当前冲稳保比例略失衡。\n"
                "- 主要问题：冲区偏多（建议：reorder / replace）；保区衔接不足（建议：add）\n"
                "- 建议概览：补充建议 1 条，顺序调整 1 条，替换建议 1 条"
            )
        ),
    ):
        result = asyncio.run(handle_planning_request(_ctx("903b"), request_type="plan_adjustment_analyze"))

    assert "可优化的地方" in result
    assert "冲区偏多" in result
    assert "建议概览" in result


def test_planning_scenario_plan_adjustment_analysis_consumes_direct_state_payload():
    ctx = _ctx("903c")
    response = {
        "code": 0,
        "data": {
            "status": "ready",
            "analysis": {
                "summaryText": "当前排序存在录取概率倒挂；当前录取概率梯度存在断层",
                "rules": [
                    {"ruleCode": "probability_inversion", "hit": True, "summary": "当前排序存在录取概率倒挂"},
                    {"ruleCode": "probability_gap", "hit": True, "summary": "当前录取概率梯度存在断层"},
                ],
            },
            "suggestions": {
                "addSuggestions": [],
                "reorderSuggestions": [{"id": "reorder_1"}],
                "replaceSuggestions": [{"id": "replace_1"}],
                "removeSuggestions": [],
            },
        },
    }

    with patch(
        "app.tools.planning_workflow_tool._analyze_planning_plan_adjustment_request",
        AsyncMock(return_value=response),
    ):
        result = asyncio.run(analyze_planning_plan_adjustment(ctx))

    assert "录取概率倒挂" in result
    assert "梯度存在断层" in result
    assert "顺序调整 1 条" in result
    assert "替换建议 1 条" in result


def test_planning_scenario_ordered_regenerate_requires_confirmation_in_router():
    with patch(
        "app.tools.planning_router_tool.query_planning_plan_overview",
        AsyncMock(return_value="这是当前方案的完整状态概览。"),
    ), patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=SimpleNamespace(
                summary="阶段=ordered；方案=30/30",
                draft_count=30,
                ordered_count=30,
                relation_lines=[],
            )
        ),
    ):
        result = asyncio.run(handle_planning_request(_ctx("904"), request_type="ordered_regenerate"))
    assert "计划动作：整体重排当前方案" in result
    assert "这是当前方案的完整状态概览。" in result


def test_planning_scenario_ordered_remove_routes_to_plan_pipeline():
    with patch(
        "app.tools.planning_router_tool._run_planned_request",
        AsyncMock(return_value="这一步我先不给你直接改方案，先把影响看清楚。"),
    ) as remove_mock:
        result = asyncio.run(
            handle_planning_request(
                _ctx("904a"),
                request_type="ordered_remove",
                volunteer_ids=["v-1"],
            )
        )

    remove_mock.assert_awaited_once()
    assert "先不给你直接改方案" in result


def test_planning_scenario_ordered_remove_requires_volunteer_id():
    result = asyncio.run(handle_planning_request(_ctx("904b"), request_type="ordered_remove"))
    assert "删除志愿需要先确认要删除哪一条" in result


def test_planning_scenario_review_returns_workspace_action():
    with patch(
        "app.tools.planning_router_tool._run_planned_request",
        AsyncMock(return_value="已完成当前方案审查。"),
    ):
        result = asyncio.run(handle_planning_request(_ctx("905"), request_type="review"))

    assert result == "已完成当前方案审查。"


def test_planning_scenario_compensation_preview_returns_workspace_action():
    with patch(
        "app.tools.planning_router_tool._run_planned_request",
        AsyncMock(return_value="已生成补偿预览。"),
    ):
        result = asyncio.run(handle_planning_request(_ctx("906"), request_type="compensation_preview"))

    assert result == "已生成补偿预览。"


def test_planning_scenario_candidate_select_by_ids_returns_workspace_action_with_refresh():
    with patch(
        "app.tools.planning_router_tool._run_planned_request",
        AsyncMock(return_value="这一步我先不给你直接改方案，先把影响看清楚。"),
    ):
        result = asyncio.run(
            handle_planning_request(
                _ctx("907"),
                request_type="candidate_select",
                volunteer_ids=["g1_a", "g2_a"],
            )
        )

    assert "先不给你直接改方案" in result


def test_planning_scenario_candidate_select_by_ids_applies_after_confirmation():
    with patch(
        "app.tools.planning_router_tool._run_planned_request",
        AsyncMock(return_value="已加入2个专业组到当前方案，并同步刷新排序结果。"),
    ):
        result = asyncio.run(
            handle_planning_request(
                _ctx("907a"),
                request_type="candidate_select",
                volunteer_ids=["g1_a", "g2_a"],
                user_confirmed=True,
            )
        )

    assert "已加入2个专业组" in result


def test_planning_scenario_candidate_query_returns_candidate_workspace_action():
    with patch(
        "app.tools.planning_router_tool._run_planned_request",
        AsyncMock(
            return_value=(
                "这是当前候选池查询结果。\n"
                "- 命中数量：12\n"
                "- 当前页：第1页，每页5条\n"
                "- 候选示例：北京联合大学-计算机科学与技术(冲/北京) id=v1 分值88.0"
            )
        ),
    ):
        result = asyncio.run(
            handle_planning_request(
                _ctx("907b"),
                request_type="candidate_query",
                province_keyword="北京",
                limit=5,
            )
        )

    assert "这是当前候选池查询结果" in result
    assert "北京" in result


def test_planning_scenario_add_units_by_filters_updates_plan_wording():
    payload = _payload(
        "add_units",
        atomic_actions=[
            {
                "action_type": "add_units",
                "volunteer_ids": [],
                "target_position": None,
                "filters": {
                    "tier": "",
                    "province_keyword": "北京",
                    "school_keyword": "",
                    "major_keyword": "",
                    "school_tags": "[]",
                    "major_tags": "[]",
                    "limit": "2",
                },
                "reason": "补两个北京的",
            }
        ],
    )
    with patch(
        "app.tools.plan_execution_tool._generate_planning_candidate_pool_request",
        AsyncMock(return_value={"code": 0, "data": {}}),
    ), patch(
        "app.tools.plan_execution_tool._query_planning_candidate_pool_request",
        AsyncMock(return_value={"code": 0, "data": {"items": [{"volunteerId": "v1"}, {"volunteerId": "v2"}]}}),
    ), patch(
        "app.tools.plan_execution_tool._select_planning_draft_items_request",
        AsyncMock(return_value={"code": 0, "data": {"draftPlanState": {"summary": {"unitTotal": 30}}}}),
    ), patch(
        "app.tools.plan_execution_tool._generate_planning_ordered_plan_request",
        AsyncMock(return_value={"code": 0, "data": {"orderedPlanState": {"summary": {"unitTotal": 30}}}}),
    ), patch(
        "app.tools.plan_execution_tool._run_planning_review_request",
        AsyncMock(return_value={"code": 0, "data": {}}),
    ), patch(
        "app.tools.plan_execution_tool._get_planning_state_request",
        AsyncMock(
            side_effect=[
                {
                    "code": 0,
                    "data": {
                        "orderedPlanState": {"summary": {"unitTotal": 28}},
                        "draftPlanState": {"summary": {"unitTotal": 28}},
                    },
                },
                {
                    "code": 0,
                    "data": {
                        "orderedPlanState": {"summary": {"unitTotal": 30}},
                        "draftPlanState": {"summary": {"unitTotal": 30}},
                        "reviewState": {"summary": {"riskCount": 0, "warnCount": 0}},
                    },
                },
            ]
        ),
    ):
        result = asyncio.run(execute_plan_action(_ctx_with_pending("add_units", "908"), payload))

    summary = json.loads(result)["summary"]
    assert "加入 2 个候选志愿" in summary
    assert "同步更新当前方案" in summary
    assert "草稿" not in summary


def test_planning_scenario_candidate_select_by_filters_previews_before_apply():
    with patch(
        "app.tools.planning_router_tool._run_planned_request",
        AsyncMock(return_value="这一步我先不给你直接改方案，先把影响看清楚。"),
    ):
        result = asyncio.run(
            handle_planning_request(
                _ctx("908x"),
                request_type="candidate_select",
                province_keyword="北京",
                limit=2,
            )
        )

    assert "先不给你直接改方案" in result


def test_planning_scenario_ordered_query_returns_workspace_action():
    with patch(
        "app.tools.planning_router_tool._run_planned_request",
        AsyncMock(return_value="这是当前排序方案摘要。\n- 排序总数：48"),
    ):
        result = asyncio.run(handle_planning_request(_ctx("908b"), request_type="ordered_query"))

    assert "排序总数：48" in result


def test_planning_scenario_regenerate_order_prefers_unit_total():
    payload = _payload("regenerate_order")
    with patch(
        "app.tools.plan_execution_tool._generate_planning_ordered_plan_request",
        AsyncMock(return_value={"code": 0, "data": {"orderedPlanState": {"summary": {"unitTotal": 48, "total": 96}}}}),
    ), patch(
        "app.tools.plan_execution_tool._run_planning_review_request",
        AsyncMock(return_value={"code": 0, "data": {}}),
    ), patch(
        "app.tools.plan_execution_tool._get_planning_state_request",
        AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "orderedPlanState": {"summary": {"unitTotal": 48, "total": 96}},
                    "reviewState": {"summary": {"riskCount": 0, "warnCount": 0}},
                },
            }
        ),
    ):
        result = asyncio.run(execute_plan_action(_ctx_with_pending("regenerate_order", "909"), payload))

    summary = json.loads(result)["summary"]
    assert "48" in summary
    assert "96" not in summary


def test_planning_scenario_replace_units_combines_remove_add_and_review():
    payload = _payload(
        "replace_units",
        should_rerun_review=True,
        atomic_actions=[
            {
                "action_type": "replace_units",
                "volunteer_ids": ["old-1"],
                "target_position": None,
                "filters": {
                    "tier": "稳",
                    "province_keyword": "北京",
                    "school_keyword": "",
                    "major_keyword": "",
                    "school_tags": "[]",
                    "major_tags": "[]",
                    "limit": "1",
                },
                "reason": "把这个换成北京的",
            }
        ],
    )
    with patch(
        "app.handlers.mutation_handlers.remove_planning_ordered_items",
        AsyncMock(return_value="已移出旧志愿"),
    ), patch(
        "app.handlers.mutation_handlers._select_candidates_by_filters_into_plan",
        AsyncMock(return_value="已补入北京候选"),
    ), patch(
        "app.tools.plan_execution_tool.run_planning_review",
        AsyncMock(return_value="复审完成"),
    ):
        result = asyncio.run(execute_plan_action(_ctx_with_pending("replace_units", "909r"), payload))

    data = json.loads(result)
    assert data["executed_actions"][0]["action"] == "replace_units"
    assert data["workspace_refresh_targets"] == ["ordered", "review"]
    assert data["review_rerun"] is True
    assert "已移出旧志愿" in data["summary"]
    assert "已补入北京候选" in data["summary"]
    assert "复审完成" in data["summary"]


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
        "app.tools.planning_workflow_tool._remove_planning_draft_items_request",
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


def test_planning_scenario_apply_compensation_prefers_unit_total_and_mentions_plan():
    payload = _payload("apply_compensation")
    with patch(
        "app.handlers.compensation_handlers._apply_planning_compensation_request",
        AsyncMock(return_value={"code": 0, "data": {"draftPlanState": {"summary": {"unitTotal": 30, "total": 60}}}}),
    ), patch(
        "app.handlers.compensation_handlers._run_planning_review_request",
        AsyncMock(return_value={"code": 0, "data": {}}),
    ), patch(
        "app.handlers.compensation_handlers._get_planning_state_request",
        AsyncMock(return_value={"code": 0, "data": {}}),
    ), patch(
        "app.handlers.compensation_handlers._get_planning_state_with_latest_profile",
        AsyncMock(return_value={"draftPlanState": {"summary": {"unitTotal": 30, "total": 60}}}),
    ):
        result = asyncio.run(execute_plan_action(_ctx_with_pending("apply_compensation", "910"), payload))

    summary = json.loads(result)["summary"]
    assert "30" in summary
    assert "60" not in summary
    assert "当前方案" in summary
    assert "草稿" not in summary


def test_planning_scenario_apply_compensation_requires_confirmation_in_workflow():
    result = asyncio.run(apply_planning_compensation(_ctx("911")))
    assert "请先在对话中获得用户明确确认" in result


def test_planning_scenario_generate_ordered_plan_requires_confirmation_in_workflow():
    result = asyncio.run(generate_planning_ordered_plan(_ctx("912")))
    assert "请先在对话中获得用户明确确认" in result


def test_planning_scenario_preview_compensation_formats_action_count_and_volunteer_count():
    response = {
        "code": 0,
        "data": {
            "actions": [
                {"summary": "补 2 个保底专业组", "volunteerIds": ["v1", "v2"]},
                {"summary": "替换 1 个高风险专业组", "volunteerIds": ["v3"]},
            ]
        },
    }
    with patch(
        "app.tools.planning_workflow_tool._preview_planning_compensation_request",
        AsyncMock(return_value=response),
    ):
        result = asyncio.run(preview_planning_compensation(_ctx("913")))

    assert "待执行动作：2项" in result
    assert "预计补入候选：3个" in result
    assert "补 2 个保底专业组" in result


def test_planning_scenario_query_state_runs_through_plan_orchestration_chain():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=SimpleNamespace(
                summary="阶段=reviewed；方案=45/45；风险=0；提醒=2",
                relation_lines=[],
            )
        ),
    ), patch(
        "app.handlers.query_handlers._get_planning_state_with_latest_profile",
        new=AsyncMock(
            return_value={
                "phase": "reviewed",
                "orderedPlanState": {"summary": {"unitTotal": 45, "targetUnitCount": 45}},
                "reviewState": {"summary": {"riskCount": 0, "warnCount": 2}},
            }
        ),
    ) as mock_state, patch(
        "app.handlers.query_handlers._get_planning_ordered_plan_request",
        new=AsyncMock(return_value={"code": 0, "data": {"items": [], "summary": {"unitTotal": 45, "targetUnitCount": 45}}}),
    ) as mock_ordered:
        plan_payload = asyncio.run(
            plan_next_action(
                _ctx("914"),
                user_goal="查询当前方案状态",
                action_family="query_state",
                current_stage="apply",
                user_confirmed=False,
            )
        )
        result = asyncio.run(execute_plan_action(_ctx("914"), plan_payload))

    payload_data = json.loads(plan_payload)
    result_data = json.loads(result)
    assert payload_data["action_family"] == "query_state"
    assert payload_data["stage"] == "apply"
    assert result_data["action_family"] == "query_state"
    assert "方案已经有了" in result_data["summary"]
    assert "45/45 个志愿" in result_data["summary"]
    assert result_data["workspace_refresh_targets"] == []
    assert result_data["facts"]["phase"] == "reviewed"
    assert result_data["facts"]["warn_count"] == 2
    mock_state.assert_awaited_once()
    mock_ordered.assert_awaited_once()


def test_planning_scenario_review_plan_runs_through_plan_orchestration_chain():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    summary="阶段=ordered；方案=30/30；风险=1；提醒=2",
                    draft_count=30,
                    ordered_count=30,
                    relation_lines=[],
                )
            ),
    ), patch(
        "app.handlers.analysis_handlers._run_planning_review_request",
        new=AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "summary": {"riskCount": 1, "warnCount": 2, "passedCount": 8},
                    "checks": [{"passed": False, "summary": "保区占比过低"}],
                },
            }
        ),
    ) as mock_review_request, patch(
        "app.handlers.analysis_handlers._get_planning_state_with_latest_profile",
        new=AsyncMock(return_value={"orderedPlanState": {"items": []}, "draftPlanState": {"items": []}}),
    ) as mock_state:
        plan_payload = asyncio.run(
            plan_next_action(
                _ctx("915"),
                user_goal="帮我审查一下",
                action_family="review_plan",
                user_confirmed=False,
            )
        )
        result = asyncio.run(execute_plan_action(_ctx("915"), plan_payload))

    payload_data = json.loads(plan_payload)
    result_data = json.loads(result)
    assert payload_data["action_family"] == "review_plan"
    assert payload_data["stage"] == "review"
    assert result_data["applied"] is True
    assert "已完成方案审查" in result_data["summary"]
    assert "保区占比过低" in result_data["summary"]
    assert result_data["result_kind"] == "review_result"
    assert result_data["workspace_refresh_targets"] == ["review"]
    assert result_data["facts"]["risk_count"] == 1
    assert result_data["facts"]["warn_count"] == 2
    mock_review_request.assert_awaited_once()
    mock_state.assert_awaited_once()


def test_plan_next_action_requires_structured_major_group_position_ref():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=SimpleNamespace(
                summary="阶段=ordered；方案=45/45；院校专业组模式",
                draft_count=0,
                ordered_count=45,
                target_count=45,
                relation_lines=[],
                review_issues=[],
            )
        ),
    ):
        resp = asyncio.run(
            plan_next_action(
                _ctx("916"),
                user_goal="把第4个专业组移到第2位",
                action_family="move_ordered_unit",
            )
        )

    payload = json.loads(resp)
    assert payload["stage"] == "analyze"
    assert payload["action_family"] == "move_ordered_unit"
    assert set(payload["missing_inputs"]) == {"unit_ids", "target_position"}
    assert payload["requires_confirmation"] is False


def test_plan_next_action_accepts_structured_major_group_position_ref():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=SimpleNamespace(
                summary="阶段=ordered；方案=45/45；院校专业组模式",
                draft_count=0,
                ordered_count=45,
                target_count=45,
                relation_lines=[],
                review_issues=[],
            )
        ),
    ):
        resp = asyncio.run(
            plan_next_action(
                _ctx("916"),
                user_goal="把第4个专业组移到第2位",
                action_family="move_ordered_unit",
                source_position=4,
                target_position=2,
            )
        )

    payload = json.loads(resp)
    assert payload["stage"] == "preview"
    assert payload["action_family"] == "move_ordered_unit"
    assert payload["missing_inputs"] == []
    assert payload["atomic_actions"][0]["source_position"] == 4
    assert payload["atomic_actions"][0]["target_position"] == 2
    assert payload["requires_confirmation"] is True


def test_plan_next_action_requires_structured_named_move_position_ref():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=SimpleNamespace(
                summary="阶段=ordered；方案=94/96",
                draft_count=0,
                ordered_count=94,
                target_count=96,
                relation_lines=[],
                review_issues=[],
            )
        ),
    ):
        resp = asyncio.run(
            plan_next_action(
                _ctx("917"),
                user_goal="把青岛城市学院的国际经济与贸易改到第3位",
                action_family="move_unit",
            )
        )

    payload = json.loads(resp)
    assert payload["stage"] == "analyze"
    assert payload["action_family"] == "move_unit"
    assert set(payload["missing_inputs"]) == {"volunteer_id", "target_position"}
    assert payload["requires_confirmation"] is False
