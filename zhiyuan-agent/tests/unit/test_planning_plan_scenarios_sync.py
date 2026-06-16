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
from app.models.conversation_phase import ConversationPhase, PendingConfirmation, PhaseState
from app.tools.plan_execution_tool import execute_plan_action
from app.tools.plan_orchestration_tool import plan_next_action
from app.tools.planning_workflow_tool import (
    generate_planning_initial_plan,
    generate_planning_ordered_plan,
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
            chat_history=[],
            conversation_phase=ConversationPhase(
                state=PhaseState.PLAN_PREVIEWING,
                pending=PendingConfirmation(
                    kind="plan_mutation",
                    action_family=action_family,
                ),
            ),
            confirmed_via_card=True,
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
        "app.tools.plan_execution_tool._select_working_plan_items_request",
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


def test_planning_scenario_rejects_legacy_apply_compensation_action_family():
    payload = _payload("apply_compensation")
    result = asyncio.run(execute_plan_action(_ctx_with_pending("apply_compensation", "910"), payload))

    data = json.loads(result)
    assert data["applied"] is False
    assert data["action_family"] == "apply_compensation"
    assert data["result_kind"] == "error"
    assert "missing_plan_payload" in data["reply_focus"]


def test_planning_scenario_generate_ordered_plan_requires_confirmation_in_workflow():
    result = asyncio.run(generate_planning_ordered_plan(_ctx("912")))
    assert "请先在对话中获得用户明确确认" in result


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


def test_plan_next_action_accepts_source_major_names_for_remove_units():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=SimpleNamespace(
                summary="阶段=ordered；方案=45/45；专业+大学模式",
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
                user_goal="删掉方案里面的汉语言文学",
                action_family="remove_units",
                source_major_names=["汉语言文学"],
            )
        )

    payload = json.loads(resp)
    assert payload["stage"] == "preview"
    assert payload["action_family"] == "remove_units"
    assert payload["missing_inputs"] == []
    assert payload["atomic_actions"][0]["source_major_names"] == ["汉语言文学"]
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
