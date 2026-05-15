from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.agent.context import RequestContext
from app.tools.plan_execution_tool import (
    _select_candidates_by_filters_into_plan,
    _append_intent_relation_summary,
    clear_recent_plan_execution_result,
    consume_recent_plan_execution_result,
    execute_plan_action,
)
from app.tools.planning_workflow_tool import _format_ordered_result


def _ctx(session_id: str = "exec-1") -> SimpleNamespace:
    return SimpleNamespace(deps=RequestContext(userid="u1", sessionid=session_id))


def _ctx_with_history(
    session_id: str = "exec-1",
    *,
    chat_history: list[dict] | None = None,
    pending_plan_action: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        deps=RequestContext(
            userid="u1",
            sessionid=session_id,
            chat_history=chat_history or [],
            pending_plan_action=pending_plan_action,
        )
    )


def _ctx_with_pending(action_family: str, session_id: str = "exec-1") -> SimpleNamespace:
    return _ctx_with_history(
        session_id=session_id,
        chat_history=[{"role": "user", "content": "确认"}],
        pending_plan_action={"action_family": action_family},
    )


def test_ordered_result_marks_probability_gradient_warning_and_ratio_distribution():
    ordered_state = {
        "summary": {
            "unitTotal": 45,
            "targetUnitCount": 45,
            "unitTierCounts": {"冲": 3, "稳": 1, "保": 1},
            "gradientOk": True,
            "safetyOk": True,
        },
        "items": [
            {"schoolName": "A大学第01组", "majorName": "国际经济与贸易", "tier": "冲", "position": 1, "admissionRatio": 52},
            {"schoolName": "B大学第01组", "majorName": "网络与新媒体", "tier": "冲", "position": 2, "admissionRatio": 48},
            {"schoolName": "C大学第01组", "majorName": "跨境电子商务", "tier": "冲", "position": 3, "admissionRatio": 46},
            {"schoolName": "D大学第01组", "majorName": "英语", "tier": "稳", "position": 4, "admissionRatio": 68},
            {"schoolName": "E大学第01组", "majorName": "商务英语", "tier": "保", "position": 5, "admissionRatio": 90},
        ],
    }
    planning_state = {
        "reviewState": {
            "summary": {"riskCount": 0, "warnCount": 2},
            "checks": [
                {"passed": False, "summary": "当前排序存在录取概率倒挂"},
                {"passed": False, "summary": "当前录取概率梯度存在断层"},
            ],
        }
    }

    text = _format_ordered_result(ordered_state, planning_state)

    assert "录取率梯度是否达标：否" in text
    assert "冲档录取率范围 46%-52%，45%以下 0/3个" in text
    assert "主要提醒：当前排序存在录取概率倒挂；当前录取概率梯度存在断层" in text
    assert "网络与新媒体(冲)录取率48%@2" in text


def test_execute_plan_action_returns_preview_without_mutation():
    payload = {
        "stage": "preview",
        "action_family": "regenerate_order",
        "context_summary": "阶段=ordered；方案=20/30",
        "preview_summary": "会整体重排当前方案。",
        "missing_inputs": [],
        "atomic_actions": [],
    }

    result = asyncio.run(execute_plan_action(_ctx(), json.dumps(payload, ensure_ascii=False)))
    data = json.loads(result)
    assert data["applied"] is False
    assert data["result_kind"] == "preview_only"
    assert data["summary"] == "会整体重排当前方案。 需要你确认后才会执行。"
    assert data["reply_focus"] == ["preview_only"]


def test_execute_plan_action_move_ordered_unit_preview_uses_unit_position_language():
    payload = {
        "stage": "preview",
        "action_family": "move_ordered_unit",
        "user_goal": "把第3个专业组移到第5位",
        "context_summary": "阶段=ordered；方案=30/30",
        "preview_summary": "会整体移动指定专业组。",
        "missing_inputs": [],
        "atomic_actions": [
            {
                "action_type": "move_ordered_unit",
                "unit_ids": [],
                "target_position": 5,
                "filters": {},
                "reason": "把第3个专业组移到第5位",
            }
        ],
    }
    state = {
        "orderedPlanState": {
            "units": [
                {"unitId": "unit-1", "schoolName": "A大学第101组", "majorItems": [{"majorName": "英语"}]},
                {"unitId": "unit-2", "schoolName": "B大学第102组", "majorItems": [{"majorName": "计算机"}]},
                {
                    "unitId": "unit-3",
                    "schoolName": "桂林电子科技大学第102组",
                    "majorItems": [{"majorName": "会计学"}, {"majorName": "知识产权"}],
                },
                {"unitId": "unit-4", "schoolName": "D大学第104组", "majorItems": [{"majorName": "电气"}]},
                {"unitId": "unit-5", "schoolName": "E大学第105组", "majorItems": [{"majorName": "软件工程"}]},
            ]
        }
    }

    with patch(
        "app.tools.plan_execution_tool._get_planning_state_request",
        new=AsyncMock(return_value={"code": 0, "data": state}),
    ) as mock_state, patch(
        "app.tools.plan_execution_tool._move_planning_ordered_plan_unit_request",
        new=AsyncMock(),
    ) as mock_move:
        result = asyncio.run(execute_plan_action(_ctx(), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is False
    assert data["result_kind"] == "preview_only"
    assert "第 3 个专业组" in data["summary"]
    assert "桂林电子科技大学第102组" in data["summary"]
    assert "组内共 2 个专业" in data["summary"]
    assert "第 5 个专业组位置" in data["summary"]
    assert "不是按单条志愿位置计算" in data["summary"]
    assert "前5位" not in data["summary"]
    assert data["facts"]["source_unit_id"] == "unit-3"
    assert data["facts"]["target_unit_position"] == 5
    mock_state.assert_awaited_once()
    mock_move.assert_not_awaited()


def test_execute_plan_action_remove_ordered_unit_preview_uses_unit_position_language():
    payload = {
        "stage": "preview",
        "action_family": "remove_ordered_unit",
        "user_goal": "删除第3个专业组",
        "context_summary": "阶段=ordered；方案=30/30",
        "preview_summary": "会整体删除指定专业组。",
        "missing_inputs": [],
        "atomic_actions": [
            {
                "action_type": "remove_ordered_unit",
                "unit_ids": [],
                "target_position": None,
                "filters": {},
                "reason": "删除第3个专业组",
            }
        ],
    }
    state = {
        "orderedPlanState": {
            "units": [
                {"unitId": "unit-1", "schoolName": "A大学第101组", "majorItems": [{"majorName": "英语"}]},
                {"unitId": "unit-2", "schoolName": "B大学第102组", "majorItems": [{"majorName": "计算机"}]},
                {
                    "unitId": "unit-3",
                    "schoolName": "桂林电子科技大学第102组",
                    "majorItems": [{"majorName": "会计学"}, {"majorName": "知识产权"}],
                },
                {"unitId": "unit-4", "schoolName": "D大学第104组", "majorItems": [{"majorName": "电气"}]},
            ]
        }
    }

    with patch(
        "app.tools.plan_execution_tool._get_planning_state_request",
        new=AsyncMock(return_value={"code": 0, "data": state}),
    ) as mock_state, patch(
        "app.tools.plan_execution_tool._remove_planning_ordered_plan_units_request",
        new=AsyncMock(),
    ) as mock_remove:
        result = asyncio.run(execute_plan_action(_ctx(), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is False
    assert data["result_kind"] == "preview_only"
    assert "第 3 个专业组" in data["summary"]
    assert "桂林电子科技大学第102组" in data["summary"]
    assert "组内共 2 个专业" in data["summary"]
    assert "不是按单条志愿位置计算" in data["summary"]
    assert "方案数量将减少 2 个专业 / 1 个专业组" in data["summary"]
    assert data["facts"]["source_unit_id"] == "unit-3"
    assert data["facts"]["source_unit_position"] == 3
    assert data["facts"]["source_unit_major_count"] == 2
    assert data["facts"]["position_semantics"] == "unit_position_not_item_position"
    mock_state.assert_awaited_once()
    mock_remove.assert_not_awaited()


def test_execute_plan_action_blocks_regenerate_order_for_structural_rebalance_goal():
    payload = {
        "stage": "preview",
        "action_family": "regenerate_order",
        "user_goal": "保持总数 30 不变，把保区提到 8 以上",
        "context_summary": "阶段=reviewed；方案=30/30",
        "preview_summary": "会整体重排当前方案。",
        "missing_inputs": [],
        "atomic_actions": [],
    }

    result = asyncio.run(execute_plan_action(_ctx(), json.dumps(payload, ensure_ascii=False)))
    data = json.loads(result)
    assert data["applied"] is False
    assert data["result_kind"] == "preview_only"
    assert data["stage"] == "analyze"
    assert "不是单纯重排" in data["summary"]
    assert "structural_rebalance_requires_scope" in data["reply_focus"]


def test_execute_plan_action_sorts_ordered_plan_by_school_rank_and_marks_review_stale():
    payload = {
        "stage": "apply",
        "action_family": "sort_ordered_plan",
        "user_goal": "按院校层次给当前方案排序",
        "context_summary": "阶段=ordered；方案=30/30",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": False,
        "intent_relation": "unknown",
        "atomic_actions": [
            {
                "action_type": "sort_ordered_plan",
                "volunteer_ids": [],
                "target_position": None,
                "filters": {"sort_field": "schoolRank"},
                "reason": "按院校层次排序",
            }
        ],
    }

    with patch(
        "app.tools.plan_execution_tool._sort_planning_ordered_plan_request",
        new=AsyncMock(return_value={"code": 0, "data": {}}),
    ) as mock_sort, patch(
        "app.tools.plan_execution_tool._get_planning_state_request",
        new=AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "orderedPlanState": {"summary": {"unitTotal": 30, "targetUnitCount": 30}},
                    "reviewState": {"summary": {"riskCount": 0, "warnCount": 0}},
                },
            }
        ),
    ), patch(
        "app.tools.plan_execution_tool._get_user_profile_request",
        new=AsyncMock(return_value={"code": 0, "data": {"userprofile": {}}}),
    ):
        result = asyncio.run(execute_plan_action(_ctx_with_pending("sort_ordered_plan"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is True
    assert data["action_family"] == "sort_ordered_plan"
    assert data["workspace_refresh_targets"] == ["ordered", "review"]
    assert data["executed_actions"] == [{"action": "sort_ordered_plan", "sortField": "schoolRank"}]
    assert "已按院校层次重新排序当前方案" in data["summary"]
    assert "草稿" not in data["summary"]
    mock_sort.assert_awaited_once_with(1, "exec-1", "schoolRank")


def test_execute_plan_action_sort_accepts_success_envelope():
    payload = {
        "stage": "apply",
        "action_family": "sort_ordered_plan",
        "user_goal": "按院校层次给当前方案排序",
        "context_summary": "阶段=ordered；方案=30/30",
        "atomic_actions": [
            {
                "action_type": "sort_ordered_plan",
                "filters": {"sort_field": "schoolRank"},
            }
        ],
    }

    with patch(
        "app.tools.plan_execution_tool._sort_planning_ordered_plan_request",
        new=AsyncMock(return_value={"success": True, "data": {}}),
    ), patch(
        "app.tools.plan_execution_tool._get_planning_state_request",
        new=AsyncMock(
            return_value={
                "success": True,
                "data": {
                    "orderedPlanState": {"summary": {"unitTotal": 30, "targetUnitCount": 30}},
                },
            }
        ),
    ), patch(
        "app.tools.plan_execution_tool._get_user_profile_request",
        new=AsyncMock(return_value={"success": True, "data": {"userprofile": {}}}),
    ):
        result = asyncio.run(execute_plan_action(_ctx_with_pending("sort_ordered_plan"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is True
    assert data["result_kind"] == "mutation_result"
    assert data["workspace_refresh_targets"] == ["ordered", "review"]
    assert "已按院校层次重新排序当前方案" in data["summary"]


def test_execute_plan_action_sort_failure_does_not_refresh_workspace():
    payload = {
        "stage": "apply",
        "action_family": "sort_ordered_plan",
        "user_goal": "按院校层次给当前方案排序",
        "context_summary": "阶段=ordered；方案=30/30",
        "atomic_actions": [
            {
                "action_type": "sort_ordered_plan",
                "filters": {"sort_field": "schoolRank"},
            }
        ],
    }

    with patch(
        "app.tools.plan_execution_tool._sort_planning_ordered_plan_request",
        new=AsyncMock(return_value={"success": False, "message": "backend rejected"}),
    ):
        result = asyncio.run(execute_plan_action(_ctx_with_pending("sort_ordered_plan"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is False
    assert data["result_kind"] == "error"
    assert data["executed_actions"] == []
    assert data["workspace_refresh_targets"] == []
    assert "排序失败" in data["summary"]


def test_execute_plan_action_remove_preview_expands_broad_high_tuition_issue_scope():
    payload = {
        "stage": "preview",
        "action_family": "remove_units",
        "user_goal": "先处理高收费",
        "context_summary": "阶段=reviewed；方案=30/30",
        "preview_summary": "会先移除高收费项。",
        "missing_inputs": [],
        "atomic_actions": [
            {
                "action_type": "remove_units",
                "volunteer_ids": ["北京邮电大学世纪学院(03)-通信工程@34"],
                "target_position": None,
                "filters": {},
                "reason": "先处理高收费",
            }
        ],
    }

    ordered_items = [
        {"position": 33, "volunteerId": "u1_a", "schoolName": "北京邮电大学世纪学院(03)", "majorName": "自动化(36000元)", "tier": "稳"},
        {"position": 34, "volunteerId": "u1_b", "schoolName": "北京邮电大学世纪学院(03)", "majorName": "通信工程(41000元)", "tier": "稳"},
        {"position": 35, "volunteerId": "u1_c", "schoolName": "北京邮电大学世纪学院(03)", "majorName": "计算机科学与技术(37000元)", "tier": "稳"},
        {"position": 40, "volunteerId": "u2_a", "schoolName": "沧州交通学院(02)", "majorName": "计算机科学与技术(21000元)", "tier": "稳"},
        {"position": 41, "volunteerId": "u2_b", "schoolName": "沧州交通学院(02)", "majorName": "软件工程(21000元)", "tier": "稳"},
        {"position": 42, "volunteerId": "u2_c", "schoolName": "沧州交通学院(02)", "majorName": "数据科学与大数据技术(21000元)", "tier": "稳"},
    ]
    planning_state = {
        "reviewState": {
            "checks": [
                {
                    "code": "high_tuition",
                    "passed": False,
                    "affectedVolunteerIds": ["u1_a", "u1_b", "u1_c", "u2_a", "u2_b", "u2_c"],
                }
            ]
        }
    }

    with patch(
        "app.tools.plan_execution_tool._get_planning_ordered_plan_request",
        new=AsyncMock(return_value={"code": 0, "data": {"items": ordered_items}}),
    ), patch(
        "app.tools.plan_execution_tool._get_planning_state_request",
        new=AsyncMock(return_value={"code": 0, "data": planning_state}),
    ):
        result = asyncio.run(execute_plan_action(_ctx(), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is False
    assert data["result_kind"] == "preview_only"
    assert "共 2 个专业组，涉及 6 条志愿" in data["summary"]
    assert "整批问题项处理" in data["summary"]
    assert "review_issue_batch_scope" in data["reply_focus"]


def test_execute_plan_action_remove_preview_uses_review_issue_target_without_sample_refs():
    payload = {
        "stage": "preview",
        "action_family": "remove_units",
        "user_goal": "先处理高收费",
        "context_summary": "阶段=reviewed；方案=30/30",
        "preview_summary": "会按当前审查命中的整批高收费项执行移除。",
        "missing_inputs": [],
        "atomic_actions": [
            {
                "action_type": "remove_units",
                "volunteer_ids": [],
                "target_position": None,
                "filters": {},
                "reason": "先处理高收费",
                "review_issue_target": {
                    "code": "high_tuition",
                    "scope_mode": "full_issue",
                    "scope_fingerprint": "issue-high-1",
                    "label": "高收费",
                    "scope_kind": "item_removal",
                    "default_action_family": "remove_units",
                },
            }
        ],
    }

    ordered_items = [
        {"position": 33, "volunteerId": "u1_a", "schoolName": "北京邮电大学世纪学院(03)", "majorName": "自动化(36000元)", "tier": "稳"},
        {"position": 34, "volunteerId": "u1_b", "schoolName": "北京邮电大学世纪学院(03)", "majorName": "通信工程(41000元)", "tier": "稳"},
        {"position": 40, "volunteerId": "u2_a", "schoolName": "沧州交通学院(02)", "majorName": "计算机科学与技术(21000元)", "tier": "稳"},
    ]
    planning_state = {
        "reviewState": {
            "checks": [
                {
                    "code": "high_tuition",
                    "passed": False,
                    "summary": "当前方案包含高收费专业",
                    "affectedVolunteerIds": ["u1_a", "u1_b", "u2_a"],
                }
            ]
        }
    }

    with patch(
        "app.tools.plan_execution_tool._get_planning_ordered_plan_request",
        new=AsyncMock(return_value={"code": 0, "data": {"items": ordered_items}}),
    ), patch(
        "app.tools.plan_execution_tool._get_planning_state_request",
        new=AsyncMock(return_value={"code": 0, "data": planning_state}),
    ):
        result = asyncio.run(execute_plan_action(_ctx(), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["result_kind"] == "preview_only"
    assert "共 2 个专业组，涉及 3 条志愿" in data["summary"]
    assert "review_issue_batch_scope" in data["reply_focus"]


def test_execute_plan_action_rejects_incomplete_replace_preview_payload():
    payload = {
        "stage": "preview",
        "action_family": "replace_units",
        "user_goal": "替换生物科学",
        "context_summary": "阶段=reviewed；方案=45/45",
        "missing_inputs": [],
        "atomic_actions": [],
    }

    result = asyncio.run(execute_plan_action(_ctx(), json.dumps(payload, ensure_ascii=False)))
    data = json.loads(result)

    assert data["applied"] is False
    assert data["result_kind"] == "error"
    assert "volunteer_ids" in data["summary"]
    assert "replacement_scope" in data["summary"]
    assert data["reply_focus"] == ["missing_inputs"]


def test_execute_plan_action_returns_structured_error_when_payload_schema_is_incomplete():
    payload = {
        "action_family": "analyze_adjustment",
        "requires_confirmation": False,
    }

    result = asyncio.run(execute_plan_action(_ctx(), json.dumps(payload, ensure_ascii=False)))
    data = json.loads(result)

    assert data["applied"] is False
    assert data["result_kind"] == "error"
    assert data["action_family"] == "analyze_adjustment"
    assert data["reply_focus"] == ["missing_plan_payload"]
    assert "方案操作信息不完整" in data["summary"]


def test_execute_plan_action_runs_remove_and_review():
    payload = {
        "stage": "apply",
        "action_family": "remove_units",
        "context_summary": "阶段=ordered；方案=20/30",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": True,
        "intent_relation": "support",
        "atomic_actions": [
            {
                "action_type": "remove_units",
                "volunteer_ids": ["v1"],
                "target_position": None,
                "filters": {},
                "reason": "删掉这个学校",
            }
        ],
    }

    with patch(
        "app.handlers.mutation_handlers.remove_planning_ordered_items",
        new=AsyncMock(return_value="remove ok"),
    ) as mock_remove, patch(
        "app.tools.plan_execution_tool.run_planning_review",
        new=AsyncMock(return_value="review ok"),
    ) as mock_review:
        result = asyncio.run(execute_plan_action(_ctx_with_pending("remove_units"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is True
    assert data["result_kind"] == "mutation_result"
    assert data["review_rerun"] is True
    assert "remove ok" in data["summary"]
    assert "review ok" in data["summary"]
    assert "plan_update" in data["reply_focus"]
    mock_remove.assert_awaited_once()
    assert mock_review.await_count == 1


def test_execute_plan_action_remove_expands_broad_high_tuition_issue_scope_on_apply():
    payload = {
        "stage": "apply",
        "action_family": "remove_units",
        "user_goal": "先处理高收费",
        "context_summary": "阶段=reviewed；方案=30/30",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": True,
        "intent_relation": "support",
        "atomic_actions": [
            {
                "action_type": "remove_units",
                "volunteer_ids": ["北京邮电大学世纪学院(03)-通信工程@34", "沧州交通学院(02)-软件工程@41"],
                "target_position": None,
                "filters": {},
                "reason": "先处理高收费",
            }
        ],
    }

    ordered_items = [
        {"position": 33, "volunteerId": "u1_a", "schoolName": "北京邮电大学世纪学院(03)", "majorName": "自动化(36000元)", "tier": "稳"},
        {"position": 34, "volunteerId": "u1_b", "schoolName": "北京邮电大学世纪学院(03)", "majorName": "通信工程(41000元)", "tier": "稳"},
        {"position": 35, "volunteerId": "u1_c", "schoolName": "北京邮电大学世纪学院(03)", "majorName": "计算机科学与技术(37000元)", "tier": "稳"},
        {"position": 40, "volunteerId": "u2_a", "schoolName": "沧州交通学院(02)", "majorName": "计算机科学与技术(21000元)", "tier": "稳"},
        {"position": 41, "volunteerId": "u2_b", "schoolName": "沧州交通学院(02)", "majorName": "软件工程(21000元)", "tier": "稳"},
        {"position": 42, "volunteerId": "u2_c", "schoolName": "沧州交通学院(02)", "majorName": "数据科学与大数据技术(21000元)", "tier": "稳"},
    ]
    planning_state = {
        "reviewState": {
            "checks": [
                {
                    "code": "high_tuition",
                    "passed": False,
                    "affectedVolunteerIds": ["u1_a", "u1_b", "u1_c", "u2_a", "u2_b", "u2_c"],
                }
            ]
        }
    }

    with patch(
        "app.tools.plan_execution_tool._get_planning_ordered_plan_request",
        new=AsyncMock(return_value={"code": 0, "data": {"items": ordered_items}}),
    ), patch(
        "app.tools.plan_execution_tool._get_planning_state_request",
        new=AsyncMock(return_value={"code": 0, "data": planning_state}),
    ), patch(
        "app.handlers.mutation_handlers.remove_planning_ordered_items",
        new=AsyncMock(return_value="remove ok"),
    ) as mock_remove, patch(
        "app.tools.plan_execution_tool.run_planning_review",
        new=AsyncMock(return_value="review ok"),
    ):
        result = asyncio.run(execute_plan_action(_ctx_with_pending("remove_units"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is True
    assert data["affected_volunteer_ids"] == ["u1_a", "u1_b", "u1_c", "u2_a", "u2_b", "u2_c"]
    mock_remove.assert_awaited_once()
    assert mock_remove.await_args.args[1] == ["u1_a", "u1_b", "u1_c", "u2_a", "u2_b", "u2_c"]


def test_execute_plan_action_remove_apply_normalizes_flat_volunteer_ids_payload():
    payload = {
        "stage": "apply",
        "action_family": "remove_units",
        "user_goal": "先处理高收费",
        "context_summary": "阶段=reviewed；方案=30/30",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": True,
        "intent_relation": "support",
        "volunteer_ids": ["北京邮电大学世纪学院(03)-通信工程@34", "沧州交通学院(02)-软件工程@41"],
    }

    ordered_items = [
        {"position": 33, "volunteerId": "u1_a", "schoolName": "北京邮电大学世纪学院(03)", "majorName": "自动化(36000元)", "tier": "稳"},
        {"position": 34, "volunteerId": "u1_b", "schoolName": "北京邮电大学世纪学院(03)", "majorName": "通信工程(41000元)", "tier": "稳"},
        {"position": 35, "volunteerId": "u1_c", "schoolName": "北京邮电大学世纪学院(03)", "majorName": "计算机科学与技术(37000元)", "tier": "稳"},
        {"position": 40, "volunteerId": "u2_a", "schoolName": "沧州交通学院(02)", "majorName": "计算机科学与技术(21000元)", "tier": "稳"},
        {"position": 41, "volunteerId": "u2_b", "schoolName": "沧州交通学院(02)", "majorName": "软件工程(21000元)", "tier": "稳"},
        {"position": 42, "volunteerId": "u2_c", "schoolName": "沧州交通学院(02)", "majorName": "数据科学与大数据技术(21000元)", "tier": "稳"},
    ]
    planning_state = {
        "reviewState": {
            "checks": [
                {
                    "code": "high_tuition",
                    "passed": False,
                    "affectedVolunteerIds": ["u1_a", "u1_b", "u1_c", "u2_a", "u2_b", "u2_c"],
                }
            ]
        }
    }

    with patch(
        "app.tools.plan_execution_tool._get_planning_ordered_plan_request",
        new=AsyncMock(return_value={"code": 0, "data": {"items": ordered_items}}),
    ), patch(
        "app.tools.plan_execution_tool._get_planning_state_request",
        new=AsyncMock(return_value={"code": 0, "data": planning_state}),
    ), patch(
        "app.handlers.mutation_handlers.remove_planning_ordered_items",
        new=AsyncMock(return_value="remove ok"),
    ) as mock_remove, patch(
        "app.tools.plan_execution_tool.run_planning_review",
        new=AsyncMock(return_value="review ok"),
    ):
        result = asyncio.run(execute_plan_action(_ctx_with_pending("remove_units"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is True
    assert data["affected_volunteer_ids"] == ["u1_a", "u1_b", "u1_c", "u2_a", "u2_b", "u2_c"]
    mock_remove.assert_awaited_once()
    assert mock_remove.await_args.args[1] == ["u1_a", "u1_b", "u1_c", "u2_a", "u2_b", "u2_c"]


def test_execute_plan_action_replace_apply_coerces_broad_item_removal_issue_to_remove():
    payload = {
        "stage": "apply",
        "action_family": "replace_units",
        "user_goal": "先处理高收费",
        "context_summary": "阶段=reviewed；方案=30/30",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": True,
        "intent_relation": "support",
        "atomic_actions": [
            {
                "action_type": "replace_units",
                "volunteer_ids": [],
                "target_position": None,
                "filters": {"major_tags": json.dumps(["电子信息类"], ensure_ascii=False), "limit": "3"},
                "reason": "先处理高收费",
                "review_issue_target": {
                    "code": "high_tuition",
                    "scope_mode": "full_issue",
                    "scope_fingerprint": "issue-high-1",
                    "label": "高收费",
                    "scope_kind": "item_removal",
                    "default_action_family": "remove_units",
                },
            }
        ],
    }

    ordered_items = [
        {"position": 33, "volunteerId": "u1_a", "schoolName": "北京邮电大学世纪学院(03)", "majorName": "自动化(36000元)", "tier": "稳"},
        {"position": 34, "volunteerId": "u1_b", "schoolName": "北京邮电大学世纪学院(03)", "majorName": "通信工程(41000元)", "tier": "稳"},
        {"position": 40, "volunteerId": "u2_a", "schoolName": "沧州交通学院(02)", "majorName": "计算机科学与技术(21000元)", "tier": "稳"},
    ]
    planning_state = {
        "reviewState": {
            "checks": [
                {
                    "code": "high_tuition",
                    "passed": False,
                    "summary": "当前方案包含高收费专业",
                    "affectedVolunteerIds": ["u1_a", "u1_b", "u2_a"],
                }
            ]
        }
    }

    with patch(
        "app.tools.plan_execution_tool._get_planning_ordered_plan_request",
        new=AsyncMock(return_value={"code": 0, "data": {"items": ordered_items}}),
    ), patch(
        "app.tools.plan_execution_tool._get_planning_state_request",
        new=AsyncMock(return_value={"code": 0, "data": planning_state}),
    ), patch(
        "app.handlers.mutation_handlers.remove_planning_ordered_items",
        new=AsyncMock(return_value="remove ok"),
    ) as mock_remove, patch(
        "app.tools.plan_execution_tool.run_planning_review",
        new=AsyncMock(return_value="review ok"),
    ):
        result = asyncio.run(execute_plan_action(_ctx_with_pending("replace_units"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is True
    assert data["affected_volunteer_ids"] == ["u1_a", "u1_b", "u2_a"]
    assert data["executed_actions"][0]["action"] == "remove_units"
    mock_remove.assert_awaited_once()
    assert mock_remove.await_args.args[1] == ["u1_a", "u1_b", "u2_a"]


def test_execute_plan_action_replace_preview_blocks_when_replacement_candidates_insufficient():
    payload = {
        "stage": "preview",
        "action_family": "replace_units",
        "user_goal": "把贵的换成正常收费的，别少名额",
        "context_summary": "阶段=reviewed；方案=30/30",
        "preview_summary": "",
        "missing_inputs": [],
        "atomic_actions": [
            {
                "action_type": "replace_units",
                "volunteer_ids": [],
                "target_position": None,
                "filters": {
                    "major_tags": json.dumps(["电子信息类", "自动化类"], ensure_ascii=False),
                    "school_tags": "[]",
                    "limit": "2",
                },
                "reason": "把贵的换成正常收费的，别少名额",
                "review_issue_target": {
                    "code": "high_tuition",
                    "scope_mode": "full_issue",
                    "scope_fingerprint": "issue-high-1",
                    "label": "高收费",
                    "scope_kind": "item_removal",
                    "default_action_family": "remove_units",
                },
            }
        ],
    }

    ordered_items = [
        {"position": 1, "volunteerId": "u1_a", "schoolName": "A大学(01)", "majorName": "电子信息工程(21000元)", "tier": "稳"},
        {"position": 2, "volunteerId": "u1_b", "schoolName": "A大学(01)", "majorName": "自动化(21000元)", "tier": "稳"},
        {"position": 3, "volunteerId": "u2_a", "schoolName": "B大学(02)", "majorName": "机器人工程(22000元)", "tier": "稳"},
    ]
    planning_state = {
        "reviewState": {
            "checks": [
                {
                    "code": "high_tuition",
                    "passed": False,
                    "summary": "当前方案包含高收费专业",
                    "affectedVolunteerIds": ["u1_a", "u1_b", "u2_a"],
                }
            ]
        }
    }

    with patch(
        "app.tools.plan_execution_tool._get_planning_ordered_plan_request",
        new=AsyncMock(return_value={"code": 0, "data": {"items": ordered_items}}),
    ), patch(
        "app.tools.plan_execution_tool._get_planning_state_request",
        new=AsyncMock(return_value={"code": 0, "data": planning_state}),
    ), patch(
        "app.handlers.generate_handler._generate_planning_candidate_pool_request",
        new=AsyncMock(return_value={"code": 0}),
    ), patch(
        "app.tools.plan_execution_tool._query_planning_candidate_pool_request",
        new=AsyncMock(return_value={"code": 0, "data": {"items": [{"volunteerId": "c1_a"}], "total": 1, "totalUnitCount": 1}}),
    ):
        result = asyncio.run(execute_plan_action(_ctx(), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is False
    assert data["result_kind"] == "error"
    assert "只找到 1 个可补入候选" in data["summary"]
    assert "先删后补不回来" in data["summary"]


def test_execute_plan_action_replace_apply_blocks_before_remove_when_candidates_insufficient():
    payload = {
        "stage": "apply",
        "action_family": "replace_units",
        "user_goal": "把贵的换成正常收费的，别少名额",
        "context_summary": "阶段=reviewed；方案=30/30",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": True,
        "intent_relation": "mixed",
        "atomic_actions": [
            {
                "action_type": "replace_units",
                "volunteer_ids": [],
                "target_position": None,
                "filters": {
                    "major_tags": json.dumps(["电子信息类", "自动化类"], ensure_ascii=False),
                    "school_tags": "[]",
                    "limit": "2",
                },
                "reason": "把贵的换成正常收费的，别少名额",
                "review_issue_target": {
                    "code": "high_tuition",
                    "scope_mode": "full_issue",
                    "scope_fingerprint": "issue-high-1",
                    "label": "高收费",
                    "scope_kind": "item_removal",
                    "default_action_family": "remove_units",
                },
            }
        ],
    }

    ordered_items = [
        {"position": 1, "volunteerId": "u1_a", "schoolName": "A大学(01)", "majorName": "电子信息工程(21000元)", "tier": "稳"},
        {"position": 2, "volunteerId": "u1_b", "schoolName": "A大学(01)", "majorName": "自动化(21000元)", "tier": "稳"},
        {"position": 3, "volunteerId": "u2_a", "schoolName": "B大学(02)", "majorName": "机器人工程(22000元)", "tier": "稳"},
    ]
    planning_state = {
        "reviewState": {
            "checks": [
                {
                    "code": "high_tuition",
                    "passed": False,
                    "summary": "当前方案包含高收费专业",
                    "affectedVolunteerIds": ["u1_a", "u1_b", "u2_a"],
                }
            ]
        }
    }

    with patch(
        "app.tools.plan_execution_tool._get_planning_ordered_plan_request",
        new=AsyncMock(return_value={"code": 0, "data": {"items": ordered_items}}),
    ), patch(
        "app.tools.plan_execution_tool._get_planning_state_request",
        new=AsyncMock(return_value={"code": 0, "data": planning_state}),
    ), patch(
        "app.handlers.generate_handler._generate_planning_candidate_pool_request",
        new=AsyncMock(return_value={"code": 0}),
    ), patch(
        "app.tools.plan_execution_tool._query_planning_candidate_pool_request",
        new=AsyncMock(return_value={"code": 0, "data": {"items": [{"volunteerId": "c1_a"}], "total": 1, "totalUnitCount": 1}}),
    ), patch(
        "app.handlers.mutation_handlers.remove_planning_ordered_items",
        new=AsyncMock(return_value="remove ok"),
    ) as mock_remove:
        result = asyncio.run(execute_plan_action(_ctx_with_pending("replace_units"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is False
    assert data["result_kind"] == "error"
    assert "先不执行替换" in data["summary"]
    assert "只找到 1 个可补入候选" in data["summary"]
    mock_remove.assert_not_awaited()


def test_execute_plan_action_replace_apply_blocks_manual_batch_replace_when_candidates_insufficient():
    payload = {
        "stage": "apply",
        "action_family": "replace_units",
        "user_goal": "先补北京本地保底，再把冲区压下来",
        "context_summary": "阶段=reviewed；方案=30/30",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": True,
        "intent_relation": "mixed",
        "atomic_actions": [
            {
                "action_type": "replace_units",
                "volunteer_ids": ["a1", "a2", "a3", "a4", "a5"],
                "target_position": None,
                "filters": {
                    "province_keyword": "北京",
                    "school_tags": "[]",
                    "major_tags": "[]",
                    "limit": "5",
                },
                "reason": "把外地冲区换成北京本地保底",
            }
        ],
    }

    ordered_items = [
        {"position": 1, "volunteerId": "a1", "schoolName": "学校1", "majorName": "专业1", "tier": "冲"},
        {"position": 2, "volunteerId": "a2", "schoolName": "学校2", "majorName": "专业2", "tier": "冲"},
        {"position": 3, "volunteerId": "a3", "schoolName": "学校3", "majorName": "专业3", "tier": "冲"},
        {"position": 4, "volunteerId": "a4", "schoolName": "学校4", "majorName": "专业4", "tier": "冲"},
        {"position": 5, "volunteerId": "a5", "schoolName": "学校5", "majorName": "专业5", "tier": "冲"},
    ]

    with patch(
        "app.tools.plan_execution_tool._get_planning_ordered_plan_request",
        new=AsyncMock(return_value={"code": 0, "data": {"items": ordered_items}}),
    ), patch(
        "app.tools.plan_execution_tool._get_planning_draft_request",
        new=AsyncMock(return_value={"code": 0, "data": {"items": []}}),
    ), patch(
        "app.handlers.generate_handler._generate_planning_candidate_pool_request",
        new=AsyncMock(return_value={"code": 0}),
    ), patch(
        "app.tools.plan_execution_tool._query_planning_candidate_pool_request",
        new=AsyncMock(return_value={"code": 0, "data": {"items": [{"volunteerId": "c1"}], "total": 1, "totalUnitCount": 1}}),
    ), patch(
        "app.handlers.mutation_handlers.remove_planning_ordered_items",
        new=AsyncMock(return_value="remove should not run"),
    ) as mock_remove:
        result = asyncio.run(execute_plan_action(_ctx_with_pending("replace_units"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is False
    assert data["result_kind"] == "error"
    assert "只找到 1 个可补入候选" in data["summary"]
    assert "不足以替掉这批志愿后仍保持 5 个名额不减少" in data["summary"]
    mock_remove.assert_not_awaited()


def test_execute_plan_action_remove_preview_returns_guidance_for_structural_issue_target():
    payload = {
        "stage": "preview",
        "action_family": "remove_units",
        "user_goal": "先处理数量不足",
        "context_summary": "阶段=reviewed；方案=28/30",
        "preview_summary": "会先处理数量不足。",
        "missing_inputs": [],
        "atomic_actions": [
            {
                "action_type": "remove_units",
                "volunteer_ids": [],
                "target_position": None,
                "filters": {},
                "reason": "先处理数量不足",
                "review_issue_target": {
                    "code": "count_validation",
                    "scope_mode": "full_issue",
                    "scope_fingerprint": "issue-gap-1",
                    "label": "数量缺口",
                    "scope_kind": "structural",
                    "default_action_family": "preview_compensation",
                },
            }
        ],
    }

    planning_state = {
        "reviewState": {
            "checks": [
                {
                    "code": "count_validation",
                    "passed": False,
                    "summary": "当前志愿数量少于官方要求",
                }
            ]
        },
        "orderedPlanState": {"items": []},
    }

    with patch(
        "app.tools.plan_execution_tool._get_planning_ordered_plan_request",
        new=AsyncMock(return_value={"code": 0, "data": {"items": []}}),
    ), patch(
        "app.tools.plan_execution_tool._get_planning_state_request",
        new=AsyncMock(return_value={"code": 0, "data": planning_state}),
    ):
        result = asyncio.run(execute_plan_action(_ctx(), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is False
    assert data["result_kind"] == "preview_only"
    assert "结构性问题" in data["summary"]
    assert data["reply_focus"] == ["preview_only", "review_issue_structural"]


def test_execute_plan_action_runs_query_candidates():
    payload = {
        "stage": "apply",
        "action_family": "query_candidates",
        "context_summary": "阶段=ordered；方案=20/30",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": False,
        "intent_relation": "unknown",
        "atomic_actions": [
            {
                "action_type": "query_candidates",
                "volunteer_ids": [],
                "target_position": None,
                "filters": {
                    "tier": "稳",
                    "province_keyword": "北京",
                    "school_keyword": "",
                    "major_keyword": "",
                    "school_tags": "[\"公办\"]",
                    "major_tags": "[]",
                    "limit": "5",
                },
                "reason": "看看北京稳一点的机会",
            }
        ],
    }

    with patch(
        "app.handlers.query_handlers.query_planning_candidate_pool",
        new=AsyncMock(return_value="candidate ok"),
    ) as mock_query:
        result = asyncio.run(execute_plan_action(_ctx_with_pending("add_units"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is True
    assert data["result_kind"] == "candidate_snapshot"
    assert data["summary"] == "candidate ok"
    assert data["reply_focus"] == ["candidate_snapshot"]
    mock_query.assert_awaited_once()
    assert mock_query.await_args.kwargs["tiers"] == ["稳"]
    assert mock_query.await_args.kwargs["province_names"] == ["北京"]
    assert mock_query.await_args.kwargs["school_tags"] == ["公办"]
    assert mock_query.await_args.kwargs["major_tags"] == []
    assert mock_query.await_args.kwargs["page_size"] == 5


def test_execute_plan_action_runs_add_units_by_filters():
    payload = {
        "stage": "apply",
        "action_family": "add_units",
        "context_summary": "阶段=ordered；方案=20/30",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": False,
        "intent_relation": "support",
        "atomic_actions": [
            {
                "action_type": "add_units",
                "volunteer_ids": [],
                "target_position": None,
                "filters": {
                    "tier": "稳",
                    "province_keyword": "北京",
                    "school_keyword": "",
                    "major_keyword": "计算机",
                    "school_tags": "[]",
                    "major_tags": "[]",
                    "limit": "2",
                },
                "reason": "补两个北京计算机",
            }
        ],
    }

    with patch(
        "app.handlers.mutation_handlers._select_candidates_by_filters_into_plan",
        new=AsyncMock(return_value="add by filters ok"),
    ) as mock_select:
        result = asyncio.run(execute_plan_action(_ctx_with_pending("add_units"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is True
    assert data["result_kind"] == "mutation_result"
    assert data["summary"] == "add by filters ok"
    assert "plan_update" in data["reply_focus"]
    mock_select.assert_awaited_once()


def test_execute_plan_action_add_units_by_filters_no_candidates_is_no_change():
    payload = {
        "stage": "apply",
        "action_family": "add_units",
        "context_summary": "阶段=ordered；方案=20/30",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": True,
        "intent_relation": "support",
        "atomic_actions": [
            {
                "action_type": "add_units",
                "volunteer_ids": [],
                "target_position": None,
                "filters": {
                    "tier": "保",
                    "province_keyword": "北京",
                    "school_keyword": "",
                    "major_keyword": "",
                    "school_tags": "[]",
                    "major_tags": "[]",
                    "limit": "5",
                },
                "reason": "补几个保底",
            }
        ],
    }

    with patch(
        "app.handlers.mutation_handlers._select_candidates_by_filters_into_plan",
        new=AsyncMock(return_value="当前条件下没有找到可加入方案的候选志愿。"),
    ), patch("app.tools.plan_execution_tool.run_planning_review", new=AsyncMock(return_value="不应复审")) as review_mock:
        result = asyncio.run(execute_plan_action(_ctx_with_pending("add_units"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is False
    assert data["result_kind"] == "no_change"
    assert data["workspace_refresh_targets"] == []
    assert data["review_rerun"] is False
    assert "没有找到可加入方案的候选志愿" in data["summary"]
    assert "no_candidates" in data["reply_focus"]
    review_mock.assert_not_awaited()


def test_execute_plan_action_add_units_resolves_candidate_school_major_ref():
    payload = {
        "stage": "apply",
        "action_family": "add_units",
        "context_summary": "阶段=ordered；方案=20/30",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": False,
        "intent_relation": "support",
        "atomic_actions": [
            {
                "action_type": "add_units",
                "volunteer_ids": ["湖北工程学院的计算机科学与技术"],
                "target_position": None,
                "filters": {},
                "reason": "把湖北工程学院的计算机科学与技术加进来",
            }
        ],
    }
    candidate_items = [
        {
            "volunteerId": "cand-hbgc-cs",
            "schoolName": "湖北工程学院(01)",
            "majorName": "计算机科学与技术(办学地点:校本部)",
        }
    ]

    with patch(
        "app.tools.plan_execution_tool._get_planning_state_request",
        new=AsyncMock(return_value={"code": 0, "data": {"candidatePoolState": {"items": []}}}),
    ), patch(
        "app.tools.plan_execution_tool._query_planning_candidate_pool_request",
        new=AsyncMock(return_value={"code": 0, "data": {"items": candidate_items}}),
    ), patch(
        "app.handlers.mutation_handlers.select_planning_ordered_items",
        new=AsyncMock(return_value="add ok"),
    ) as mock_select:
        result = asyncio.run(execute_plan_action(_ctx_with_pending("add_units"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is True
    assert data["result_kind"] == "mutation_result"
    assert data["affected_volunteer_ids"] == ["cand-hbgc-cs"]
    assert data["executed_actions"] == [
        {
            "action": "add_units",
            "volunteerIds": ["cand-hbgc-cs"],
            "requestedVolunteerRefs": ["湖北工程学院的计算机科学与技术"],
        }
    ]
    mock_select.assert_awaited_once()
    assert mock_select.await_args.args[1] == ["cand-hbgc-cs"]


def test_execute_plan_action_add_units_resolves_candidate_school_major_alias_ref():
    payload = {
        "stage": "apply",
        "action_family": "add_units",
        "context_summary": "阶段=ordered；方案=20/30",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": False,
        "intent_relation": "support",
        "atomic_actions": [
            {
                "action_type": "add_units",
                "volunteer_ids": ["广西师大统计"],
                "target_position": None,
                "filters": {},
                "reason": "把广西师大统计加进来",
            }
        ],
    }
    candidate_items = [
        {
            "volunteerId": "cand-gxsd-stat",
            "schoolName": "广西师范大学006专业组",
            "majorName": "统计学",
        }
    ]

    with patch(
        "app.tools.plan_execution_tool._get_planning_state_request",
        new=AsyncMock(return_value={"code": 0, "data": {"candidatePoolState": {"items": candidate_items}}}),
    ), patch(
        "app.tools.plan_execution_tool._query_planning_candidate_pool_request",
        new=AsyncMock(),
    ) as mock_query, patch(
        "app.handlers.mutation_handlers.select_planning_ordered_items",
        new=AsyncMock(return_value="add ok"),
    ) as mock_select:
        result = asyncio.run(execute_plan_action(_ctx_with_pending("add_units"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is True
    assert data["affected_volunteer_ids"] == ["cand-gxsd-stat"]
    mock_select.assert_awaited_once()
    assert mock_select.await_args.args[1] == ["cand-gxsd-stat"]
    mock_query.assert_not_awaited()


def test_execute_plan_action_add_units_does_not_readd_existing_school_major_alias_ref():
    payload = {
        "stage": "apply",
        "action_family": "add_units",
        "context_summary": "阶段=ordered；方案=96/96",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": True,
        "intent_relation": "support",
        "atomic_actions": [
            {
                "action_type": "add_units",
                "volunteer_ids": ["广西师大统计"],
                "target_position": None,
                "filters": {},
                "reason": "把广西师大统计加进来",
            }
        ],
    }
    ordered_items = [
        {
            "position": 88,
            "volunteerId": "gxsd-stat-88",
            "schoolName": "广西师范大学",
            "majorName": "统计学",
        }
    ]
    candidate_items = [
        {
            "volunteerId": "gxsd-stat-88",
            "schoolName": "广西师范大学",
            "majorName": "统计学",
        }
    ]

    with patch(
        "app.tools.plan_execution_tool._get_planning_ordered_plan_request",
        new=AsyncMock(return_value={"code": 0, "data": {"items": ordered_items}}),
    ), patch(
        "app.tools.plan_execution_tool._get_planning_state_request",
        new=AsyncMock(return_value={"code": 0, "data": {"candidatePoolState": {"items": candidate_items}}}),
    ), patch(
        "app.tools.plan_execution_tool._query_planning_candidate_pool_request",
        new=AsyncMock(),
    ), patch(
        "app.handlers.mutation_handlers.select_planning_ordered_items",
        new=AsyncMock(return_value="add ok"),
    ) as mock_select, patch(
        "app.tools.plan_execution_tool.run_planning_review",
        new=AsyncMock(return_value="review should not run"),
    ) as mock_review:
        result = asyncio.run(execute_plan_action(_ctx_with_pending("add_units"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is False
    assert data["result_kind"] == "no_change"
    assert "已经在当前方案中" in data["summary"]
    assert "already_in_plan" in data["reply_focus"]
    assert data["affected_volunteer_ids"] == []
    assert data["workspace_refresh_targets"] == []
    mock_select.assert_not_awaited()
    mock_review.assert_not_awaited()


def test_execute_plan_action_add_units_keeps_explicit_candidate_id_without_lookup():
    payload = {
        "stage": "apply",
        "action_family": "add_units",
        "context_summary": "阶段=ordered；方案=20/30",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": False,
        "intent_relation": "support",
        "atomic_actions": [
            {
                "action_type": "add_units",
                "volunteer_ids": ["candidate-123"],
                "target_position": None,
                "filters": {},
                "reason": "把这个加进来",
            }
        ],
    }

    with patch(
        "app.tools.plan_execution_tool._get_planning_state_request",
        new=AsyncMock(),
    ) as mock_state, patch(
        "app.tools.plan_execution_tool._query_planning_candidate_pool_request",
        new=AsyncMock(),
    ) as mock_query, patch(
        "app.handlers.mutation_handlers.select_planning_ordered_items",
        new=AsyncMock(return_value="add ok"),
    ) as mock_select:
        result = asyncio.run(execute_plan_action(_ctx_with_pending("add_units"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is True
    assert data["affected_volunteer_ids"] == ["candidate-123"]
    mock_select.assert_awaited_once()
    assert mock_select.await_args.args[1] == ["candidate-123"]
    mock_state.assert_not_awaited()
    mock_query.assert_not_awaited()


def test_execute_plan_action_add_units_does_not_guess_ambiguous_candidate_ref():
    payload = {
        "stage": "apply",
        "action_family": "add_units",
        "context_summary": "阶段=ordered；方案=20/30",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": False,
        "intent_relation": "support",
        "atomic_actions": [
            {
                "action_type": "add_units",
                "volunteer_ids": ["湖北工程学院的计算机科学与技术"],
                "target_position": None,
                "filters": {},
                "reason": "把湖北工程学院的计算机科学与技术加进来",
            }
        ],
    }
    candidate_items = [
        {
            "volunteerId": "cand-hbgc01-cs",
            "schoolName": "湖北工程学院(01)",
            "majorName": "计算机科学与技术",
        },
        {
            "volunteerId": "cand-hbgc02-cs",
            "schoolName": "湖北工程学院(02)",
            "majorName": "计算机科学与技术",
        },
    ]

    with patch(
        "app.tools.plan_execution_tool._get_planning_state_request",
        new=AsyncMock(return_value={"code": 0, "data": {"candidatePoolState": {"items": []}}}),
    ), patch(
        "app.tools.plan_execution_tool._query_planning_candidate_pool_request",
        new=AsyncMock(return_value={"code": 0, "data": {"items": candidate_items}}),
    ), patch(
        "app.handlers.mutation_handlers.select_planning_ordered_items",
        new=AsyncMock(return_value="add ok"),
    ) as mock_select:
        result = asyncio.run(execute_plan_action(_ctx_with_pending("add_units"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is False
    assert data["result_kind"] == "error"
    assert "湖北工程学院的计算机科学与技术" in data["summary"]
    assert "needs_candidate_selection" in data["reply_focus"]
    mock_select.assert_not_awaited()


def test_execute_plan_action_add_units_does_not_guess_ambiguous_candidate_alias_ref():
    payload = {
        "stage": "apply",
        "action_family": "add_units",
        "context_summary": "阶段=ordered；方案=20/30",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": False,
        "intent_relation": "support",
        "atomic_actions": [
            {
                "action_type": "add_units",
                "volunteer_ids": ["湖工计科"],
                "target_position": None,
                "filters": {},
                "reason": "把湖工计科加进来",
            }
        ],
    }
    candidate_items = [
        {
            "volunteerId": "cand-hbgc-cs",
            "schoolName": "湖北工程学院(01)",
            "majorName": "计算机科学与技术",
        },
        {
            "volunteerId": "cand-hbgy-cs",
            "schoolName": "湖北工业大学(01)",
            "majorName": "计算机科学与技术",
        },
    ]

    with patch(
        "app.tools.plan_execution_tool._get_planning_state_request",
        new=AsyncMock(return_value={"code": 0, "data": {"candidatePoolState": {"items": candidate_items}}}),
    ), patch(
        "app.tools.plan_execution_tool._query_planning_candidate_pool_request",
        new=AsyncMock(),
    ), patch(
        "app.handlers.mutation_handlers.select_planning_ordered_items",
        new=AsyncMock(return_value="add ok"),
    ) as mock_select:
        result = asyncio.run(execute_plan_action(_ctx_with_pending("add_units"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is False
    assert data["result_kind"] == "error"
    assert "湖工计科" in data["summary"]
    mock_select.assert_not_awaited()


def test_select_candidates_by_filters_uses_major_tags_as_candidate_major_keywords_when_major_keyword_missing():
    with patch(
        "app.handlers.compensation_handlers._get_planning_state_request",
        new=AsyncMock(return_value={"code": 0, "data": {"orderedPlanState": {"summary": {}}, "draftPlanState": {"summary": {}}}}),
    ), patch(
        "app.tools.plan_execution_tool._get_planning_ordered_plan_request",
        new=AsyncMock(return_value={"code": 0, "data": {"items": []}}),
    ), patch(
        "app.tools.plan_execution_tool._get_planning_draft_request",
        new=AsyncMock(return_value={"code": 0, "data": {"items": []}}),
    ), patch(
        "app.handlers.generate_handler._generate_planning_candidate_pool_request",
        new=AsyncMock(return_value={"code": 0}),
    ), patch(
        "app.tools.plan_execution_tool._query_planning_candidate_pool_request",
        new=AsyncMock(return_value={"code": 0, "data": {"items": [], "total": 0}}),
    ) as mock_query:
        result = asyncio.run(
            _select_candidates_by_filters_into_plan(
                _ctx(),
                major_tags=["跨境电子商务", "网络与新媒体"],
                limit=5,
            )
        )

    assert "没有找到可加入方案" in result
    assert mock_query.await_args.kwargs["major_keywords"] == ["跨境电子商务", "网络与新媒体"]
    assert mock_query.await_args.kwargs["major_tags"] == ["跨境电子商务", "网络与新媒体"]


def test_select_candidates_by_filters_prefers_unique_candidate_units_in_major_group_mode():
    with patch(
        "app.tools.plan_execution_tool._get_planning_state_request",
        new=AsyncMock(
            side_effect=[
                {"code": 0, "data": {"orderedPlanState": {"summary": {"unitTotal": 17}}, "draftPlanState": {"summary": {"unitTotal": 17}}}},
                {
                    "code": 0,
                    "data": {
                        "orderedPlanState": {"summary": {"unitTotal": 19, "targetUnitCount": 30}},
                        "draftPlanState": {"summary": {"unitTotal": 19}},
                        "reviewState": {"summary": {"riskCount": 0, "warnCount": 0}},
                    },
                },
            ]
        ),
    ), patch(
        "app.handlers.generate_handler._generate_planning_candidate_pool_request",
        new=AsyncMock(return_value={"code": 0}),
    ), patch(
        "app.tools.plan_execution_tool._get_planning_ordered_plan_request",
        new=AsyncMock(return_value={"code": 0, "data": {"items": []}}),
    ), patch(
        "app.tools.plan_execution_tool._get_planning_draft_request",
        new=AsyncMock(return_value={"code": 0, "data": {"items": []}}),
    ), patch(
        "app.tools.plan_execution_tool._query_planning_candidate_pool_request",
        new=AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "items": [
                        {"volunteerId": "g1_a"},
                        {"volunteerId": "g1_b"},
                        {"volunteerId": "g1_c"},
                        {"volunteerId": "g2_a"},
                    ],
                    "total": 4,
                    "totalUnitCount": 2,
                },
            }
        ),
    ) as mock_query, patch(
        "app.tools.plan_execution_tool._select_planning_draft_items_request",
        new=AsyncMock(return_value={"code": 0, "data": {"draftPlanState": {"summary": {"unitTotal": 19}}}}),
    ) as mock_select, patch(
        "app.tools.plan_execution_tool._generate_planning_ordered_plan_request",
        new=AsyncMock(return_value={"code": 0, "data": {"orderedPlanState": {"summary": {"unitTotal": 19, "targetUnitCount": 30}}}}),
    ), patch(
        "app.handlers.analysis_handlers._run_planning_review_request",
        new=AsyncMock(return_value={"code": 0, "data": {}}),
    ):
        result = asyncio.run(
            _select_candidates_by_filters_into_plan(
                _ctx(),
                major_tags=["电子信息类", "自动化类"],
                limit=2,
            )
        )

    assert "加入 2 个候选志愿" in result
    assert mock_query.await_args.kwargs["major_keywords"] == ["电子信息类", "自动化类"]
    assert mock_select.await_args.args[2] == ["g1_a", "g2_a"]


def test_select_candidates_by_filters_skips_high_tuition_candidates_for_high_tuition_replacement():
    with patch(
        "app.tools.plan_execution_tool._get_planning_state_request",
        new=AsyncMock(
            side_effect=[
                {"code": 0, "data": {"orderedPlanState": {"summary": {"unitTotal": 17}}, "draftPlanState": {"summary": {"unitTotal": 17}}}},
                {
                    "code": 0,
                    "data": {
                        "orderedPlanState": {"summary": {"unitTotal": 19, "targetUnitCount": 30}},
                        "draftPlanState": {"summary": {"unitTotal": 19}},
                        "reviewState": {"summary": {"riskCount": 0, "warnCount": 0}},
                    },
                },
            ]
        ),
    ), patch(
        "app.handlers.generate_handler._generate_planning_candidate_pool_request",
        new=AsyncMock(return_value={"code": 0}),
    ), patch(
        "app.tools.plan_execution_tool._get_planning_ordered_plan_request",
        new=AsyncMock(return_value={"code": 0, "data": {"items": []}}),
    ), patch(
        "app.tools.plan_execution_tool._get_planning_draft_request",
        new=AsyncMock(return_value={"code": 0, "data": {"items": []}}),
    ), patch(
        "app.tools.plan_execution_tool._query_planning_candidate_pool_request",
        new=AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "items": [
                        {"volunteerId": "high-1", "tuitionPerYear": 36000, "majorPlanTags": ["学费：36000/年"]},
                        {"volunteerId": "ok-1", "tuitionPerYear": 18000, "majorPlanTags": ["学费：18000/年"]},
                        {"volunteerId": "ok-2", "tuitionPerYear": 20000, "majorPlanTags": ["学费：20000/年"]},
                    ],
                    "total": 3,
                    "totalUnitCount": 3,
                },
            }
        ),
    ) as mock_query, patch(
        "app.tools.plan_execution_tool._select_planning_draft_items_request",
        new=AsyncMock(return_value={"code": 0, "data": {"draftPlanState": {"summary": {"unitTotal": 19}}}}),
    ) as mock_select, patch(
        "app.tools.plan_execution_tool._generate_planning_ordered_plan_request",
        new=AsyncMock(return_value={"code": 0, "data": {"orderedPlanState": {"summary": {"unitTotal": 19, "targetUnitCount": 30}}}}),
    ), patch(
        "app.handlers.analysis_handlers._run_planning_review_request",
        new=AsyncMock(return_value={"code": 0, "data": {}}),
    ):
        result = asyncio.run(
            _select_candidates_by_filters_into_plan(
                _ctx(),
                major_tags=["计算机类"],
                limit=2,
                replacement_issue_code="high_tuition",
            )
        )

    assert "加入 2 个候选志愿" in result
    assert mock_query.await_args.kwargs["major_keywords"] == ["计算机类"]
    assert mock_select.await_args.args[2] == ["ok-1", "ok-2"]


def test_execute_plan_action_blocks_unconfirmed_mutating_apply_without_pending_context():
    payload = {
        "stage": "apply",
        "action_family": "add_units",
        "context_summary": "阶段=ordered；方案=93/96",
        "preview_summary": "会先补几个更稳的志愿，确认后再执行。",
        "missing_inputs": [],
        "should_rerun_review": True,
        "intent_relation": "support",
        "atomic_actions": [
            {
                "action_type": "add_units",
                "volunteer_ids": [],
                "target_position": None,
                "filters": {"tier": "稳", "limit": "3"},
                "reason": "帮我补几个更稳的",
            }
        ],
    }

    with patch(
        "app.handlers.mutation_handlers._select_candidates_by_filters_into_plan",
        new=AsyncMock(return_value="should not execute"),
    ) as mock_select:
        result = asyncio.run(
            execute_plan_action(
                _ctx_with_history(chat_history=[{"role": "user", "content": "帮我补几个更稳的"}]),
                json.dumps(payload, ensure_ascii=False),
            )
        )

    data = json.loads(result)
    assert data["applied"] is False
    assert data["stage"] == "preview"
    assert data["result_kind"] == "preview_only"
    assert "确认后再执行" in data["summary"]
    assert "confirmation_required" in data["reply_focus"]
    mock_select.assert_not_awaited()


def test_execute_plan_action_blocks_confirmation_apply_without_pending_context():
    payload = {
        "stage": "apply",
        "action_family": "generate_plan",
        "context_summary": "阶段=profile_ready；方案=0/80",
        "preview_summary": "会生成一版基础方案。",
        "missing_inputs": [],
        "should_rerun_review": True,
        "intent_relation": "unknown",
        "atomic_actions": [],
    }

    with patch(
        "app.handlers.generate_handler._generate_planning_initial_plan_request",
        new=AsyncMock(return_value={"code": 0, "data": {}}),
    ) as mock_generate:
        result = asyncio.run(
            execute_plan_action(
                _ctx_with_history(chat_history=[{"role": "user", "content": "确认"}]),
                json.dumps(payload, ensure_ascii=False),
            )
        )

    data = json.loads(result)
    assert data["applied"] is False
    assert data["result_kind"] == "preview_only"
    assert "确认" in data["summary"]
    mock_generate.assert_not_awaited()


def test_execute_plan_action_allows_mutating_apply_with_pending_context():
    payload = {
        "stage": "apply",
        "action_family": "add_units",
        "context_summary": "阶段=ordered；方案=93/96",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": False,
        "intent_relation": "support",
        "atomic_actions": [
            {
                "action_type": "add_units",
                "volunteer_ids": [],
                "target_position": None,
                "filters": {"tier": "稳", "limit": "3"},
                "reason": "帮我补几个更稳的",
            }
        ],
    }

    with patch(
        "app.handlers.mutation_handlers._select_candidates_by_filters_into_plan",
        new=AsyncMock(return_value="add ok"),
    ) as mock_select:
        result = asyncio.run(
            execute_plan_action(
                _ctx_with_history(
                    chat_history=[{"role": "user", "content": "确认"}],
                    pending_plan_action={"action_family": "add_units"},
                ),
                json.dumps(payload, ensure_ascii=False),
            )
        )

    data = json.loads(result)
    assert data["applied"] is True
    assert data["summary"] == "add ok"
    mock_select.assert_awaited_once()


def test_execute_plan_action_blocks_pending_apply_when_current_user_did_not_confirm():
    payload = {
        "stage": "apply",
        "action_family": "add_units",
        "context_summary": "阶段=ordered；方案=93/96",
        "preview_summary": "会先补几个更稳的志愿，确认后再执行。",
        "missing_inputs": [],
        "should_rerun_review": False,
        "intent_relation": "support",
        "atomic_actions": [
            {
                "action_type": "add_units",
                "volunteer_ids": [],
                "target_position": None,
                "filters": {"tier": "稳", "limit": "3"},
                "reason": "帮我补几个更稳的",
            }
        ],
    }

    with patch(
        "app.handlers.mutation_handlers._select_candidates_by_filters_into_plan",
        new=AsyncMock(return_value="should not execute"),
    ) as mock_select:
        result = asyncio.run(
            execute_plan_action(
                _ctx_with_history(
                    chat_history=[{"role": "user", "content": "帮我补几个更稳的"}],
                    pending_plan_action={"action_family": "add_units"},
                ),
                json.dumps(payload, ensure_ascii=False),
            )
        )

    data = json.loads(result)
    assert data["applied"] is False
    assert data["result_kind"] == "preview_only"
    assert "确认" in data["summary"]
    mock_select.assert_not_awaited()


def test_select_candidates_summary_does_not_claim_added_when_ordered_count_unchanged():
    before_state = {
        "code": 0,
        "data": {
            "orderedPlanState": {"summary": {"unitTotal": 93, "targetUnitCount": 96}},
            "draftPlanState": {"summary": {"unitTotal": 93, "targetUnitCount": 96}},
        },
    }
    after_state = {
        "code": 0,
        "data": {
            "orderedPlanState": {"summary": {"unitTotal": 93, "targetUnitCount": 96}},
            "draftPlanState": {"summary": {"unitTotal": 93, "targetUnitCount": 96}},
            "reviewState": {"summary": {"riskCount": 1, "warnCount": 4}},
        },
    }
    with patch(
        "app.tools.plan_execution_tool._get_planning_state_request",
        new=AsyncMock(side_effect=[before_state, after_state]),
    ), patch(
        "app.handlers.generate_handler._generate_planning_candidate_pool_request",
        new=AsyncMock(return_value={"code": 0, "data": {}}),
    ), patch(
        "app.tools.plan_execution_tool._query_planning_candidate_pool_request",
        new=AsyncMock(
            return_value={
                "code": 0,
                "data": {"items": [{"volunteerId": f"v{i}"} for i in range(5)]},
            }
        ),
    ), patch(
        "app.tools.plan_execution_tool._select_planning_draft_items_request",
        new=AsyncMock(return_value={"code": 0, "data": {}}),
    ), patch(
        "app.tools.plan_execution_tool._generate_planning_ordered_plan_request",
        new=AsyncMock(return_value={"code": 0, "data": {}}),
    ), patch(
        "app.handlers.analysis_handlers._run_planning_review_request",
        new=AsyncMock(return_value={"code": 0, "data": {}}),
    ):
        result = asyncio.run(_select_candidates_by_filters_into_plan(_ctx(), tier="稳", limit=5))

    assert "按条件匹配到 5 个候选志愿，但当前方案数量没有增加" in result
    assert "已按你的要求加入 5 个候选志愿" not in result
    assert "当前方案 93/96" in result


def test_select_candidates_summary_reports_ordered_count_increase():
    before_state = {
        "code": 0,
        "data": {
            "orderedPlanState": {"summary": {"unitTotal": 93, "targetUnitCount": 96}},
            "draftPlanState": {"summary": {"unitTotal": 93, "targetUnitCount": 96}},
        },
    }
    after_state = {
        "code": 0,
        "data": {
            "orderedPlanState": {"summary": {"unitTotal": 96, "targetUnitCount": 96}},
            "draftPlanState": {"summary": {"unitTotal": 96, "targetUnitCount": 96}},
            "reviewState": {"summary": {"riskCount": 0, "warnCount": 1}},
        },
    }
    with patch(
        "app.tools.plan_execution_tool._get_planning_state_request",
        new=AsyncMock(side_effect=[before_state, after_state]),
    ), patch(
        "app.handlers.generate_handler._generate_planning_candidate_pool_request",
        new=AsyncMock(return_value={"code": 0, "data": {}}),
    ), patch(
        "app.tools.plan_execution_tool._query_planning_candidate_pool_request",
        new=AsyncMock(
            return_value={
                "code": 0,
                "data": {"items": [{"volunteerId": f"v{i}"} for i in range(5)]},
            }
        ),
    ), patch(
        "app.tools.plan_execution_tool._select_planning_draft_items_request",
        new=AsyncMock(return_value={"code": 0, "data": {}}),
    ), patch(
        "app.tools.plan_execution_tool._generate_planning_ordered_plan_request",
        new=AsyncMock(return_value={"code": 0, "data": {}}),
    ), patch(
        "app.handlers.analysis_handlers._run_planning_review_request",
        new=AsyncMock(return_value={"code": 0, "data": {}}),
    ):
        result = asyncio.run(_select_candidates_by_filters_into_plan(_ctx(), tier="稳", limit=5))

    assert "已按你的要求加入 3 个候选志愿" in result
    assert "当前方案 96/96" in result


def test_execute_plan_action_runs_query_ordered():
    payload = {
        "stage": "apply",
        "action_family": "query_ordered",
        "context_summary": "阶段=ordered；方案=20/30",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": False,
        "intent_relation": "unknown",
        "atomic_actions": [],
    }

    with patch(
        "app.handlers.query_handlers.query_planning_ordered_plan",
        new=AsyncMock(return_value="ordered query ok"),
    ) as mock_query:
        result = asyncio.run(execute_plan_action(_ctx_with_pending("regenerate_order"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["result_kind"] == "ordered_snapshot"
    assert data["summary"] == "ordered query ok"
    assert data["reply_focus"] == ["ordered_snapshot"]
    mock_query.assert_awaited_once()


def test_execute_plan_action_runs_generate_plan_and_returns_structured_facts():
    payload = {
        "stage": "apply",
        "action_family": "generate_plan",
        "context_summary": "阶段=profile_ready；方案=0/30",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": True,
        "intent_relation": "support",
        "atomic_actions": [],
    }

    with patch(
        "app.handlers.generate_handler._generate_planning_candidate_pool_request",
        new=AsyncMock(return_value={"code": 0, "data": {}}),
    ), patch(
        "app.handlers.generate_handler._generate_planning_initial_plan_request",
        new=AsyncMock(return_value={"code": 0, "data": {}}),
    ) as mock_generate, patch(
        "app.handlers.generate_handler._run_planning_review_request",
        new=AsyncMock(return_value={"code": 0, "data": {}}),
    ) as mock_review, patch(
        "app.handlers.generate_handler._get_planning_state_with_latest_profile",
        new=AsyncMock(
            return_value={
                "phase": "reviewed",
                "orderedPlanState": {"summary": {"unitTotal": 30, "targetUnitCount": 30}, "items": []},
                "draftPlanState": {"summary": {"unitTotal": 30, "targetUnitCount": 30}, "items": []},
                "reviewState": {"summary": {"riskCount": 0, "warnCount": 1}},
                "profileState": {"explicitProfile": {"positiveMajors": ["网络与新媒体"]}},
            }
        ),
    ) as mock_state:
        result = asyncio.run(execute_plan_action(_ctx_with_pending("generate_plan"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert "已生成一版方案" in data["summary"]
    assert data["result_kind"] == "generation_result"
    assert data["facts"]["phase"] == "reviewed"
    assert data["facts"]["current_total"] == 30
    assert data["workspace_refresh_targets"] == ["ordered", "review"]
    assert "count_target" in data["reply_focus"]
    assert data["next_step_hints"]
    mock_generate.assert_awaited_once()
    assert mock_review.await_count >= 1
    assert mock_state.await_count >= 1


def test_execute_plan_action_runs_query_state():
    payload = {
        "stage": "apply",
        "action_family": "query_state",
        "context_summary": "阶段=reviewed；方案=45/45",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": False,
        "intent_relation": "unknown",
        "atomic_actions": [],
    }

    with patch(
        "app.handlers.query_handlers._get_planning_state_with_latest_profile",
        new=AsyncMock(
            return_value={
                "phase": "reviewed",
                "orderedPlanState": {"summary": {"unitTotal": 45, "targetUnitCount": 45}},
                "profileState": {
                    "explicitProfile": {
                        "positiveMajors": ["财政学类", "经济学类"],
                        "positiveRegions": ["北京"],
                    }
                },
                "reviewState": {"summary": {"riskCount": 0, "warnCount": 2}},
            }
        ),
    ) as mock_state, patch(
        "app.handlers.query_handlers._get_planning_ordered_plan_request",
        new=AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "items": [
                        {
                            "position": 1,
                            "schoolName": "北京财经学院第01组",
                            "majorName": "财政学",
                            "majorCategory": "财政学类",
                            "provinceName": "北京",
                            "tier": "冲",
                        }
                    ],
                    "summary": {"unitTotal": 45, "targetUnitCount": 45},
                },
            }
        ),
    ) as mock_ordered:
        result = asyncio.run(execute_plan_action(_ctx_with_pending("regenerate_order"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert "方案已经有了" in data["summary"]
    assert "45/45 个志愿" in data["summary"]
    assert "审查提醒：风险 0 项，提醒 2 项" in data["summary"]
    assert "前排示例" in data["summary"]
    assert "北京财经学院第01组-财政学(冲)第1位" in data["summary"]
    assert "@1" not in data["summary"]
    assert data["result_kind"] == "status_overview"
    assert data["workspace_refresh_targets"] == []
    assert data["facts"]["phase"] == "reviewed"
    assert data["facts"]["current_total"] == 45
    assert "risk_warning" in data["reply_focus"]
    mock_state.assert_awaited_once()
    mock_ordered.assert_awaited_once()


def test_execute_plan_action_runs_adjustment_analysis():
    payload = {
        "stage": "apply",
        "action_family": "analyze_adjustment",
        "context_summary": "阶段=ordered；方案=20/30",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": False,
        "intent_relation": "unknown",
        "atomic_actions": [],
    }

    with patch(
        "app.handlers.analysis_handlers._analyze_planning_plan_adjustment_request",
        new=AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "analysis": {
                        "summaryText": "当前方案冲区略多，保区偏弱。",
                        "rules": [{"hit": True, "summary": "冲区偏多", "suggestionTypes": ["reorder", "add"]}],
                    },
                    "suggestions": {
                        "addSuggestions": [{"title": "补保底", "description": "补 2 个保底志愿"}],
                        "reorderSuggestions": [],
                        "replaceSuggestions": [],
                        "removeSuggestions": [],
                    },
                },
            }
        ),
    ) as mock_adjust, patch(
        "app.handlers.analysis_handlers._get_planning_state_with_latest_profile",
        new=AsyncMock(
            return_value={
                "orderedPlanState": {
                    "items": [
                        {
                            "position": 33,
                            "tier": "冲",
                            "schoolName": "汉口学院第01组",
                            "majorName": "网络与新媒体",
                        }
                    ]
                },
                "draftPlanState": {"items": []},
                "profileState": {
                    "explicitProfile": {
                        "positiveMajors": ["网络与新媒体", "跨境电子商务"],
                    }
                },
            }
        ),
    ) as mock_state:
        result = asyncio.run(execute_plan_action(_ctx_with_pending("replace_units"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["result_kind"] == "adjustment_analysis"
    assert "当前方案冲区略多，保区偏弱。" in data["summary"]
    assert "当前先拿到的是分析结论，不是可直接执行的调整清单" in data["summary"]
    assert data["facts"]["summary_text"] == "当前方案冲区略多，保区偏弱。"
    assert data["facts"]["suggestion_counts"]["add"] == 1
    assert data["facts"]["actionable_suggestion_counts"]["add"] == 0
    assert data["facts"]["has_actionable_suggestions"] is False
    assert "网络与新媒体" in " ".join(data["facts"]["intent_relation"]["lines"])
    assert "suggestion_counts" in data["reply_focus"]
    mock_adjust.assert_awaited_once()
    mock_state.assert_awaited_once()


def test_execute_plan_action_adjustment_analysis_uses_review_issue_examples_when_no_structured_suggestions():
    payload = {
        "stage": "apply",
        "action_family": "analyze_adjustment",
        "context_summary": "阶段=reviewed；方案=45/45",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": False,
        "intent_relation": "unknown",
        "atomic_actions": [],
    }

    with patch(
        "app.handlers.analysis_handlers._analyze_planning_plan_adjustment_request",
        new=AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "analysis": {
                        "summaryText": "部分专业组主要依靠非意向专业托底。",
                        "rules": [{"hit": True, "summary": "部分专业组主要依靠非意向专业托底", "suggestionTypes": []}],
                    },
                    "suggestions": {
                        "addSuggestions": [],
                        "reorderSuggestions": [],
                        "replaceSuggestions": [],
                        "removeSuggestions": [],
                    },
                },
            }
        ),
    ) as mock_adjust, patch(
        "app.handlers.analysis_handlers._get_planning_state_with_latest_profile",
        new=AsyncMock(
            return_value={
                "orderedPlanState": {
                    "items": [
                        {
                            "position": 1,
                            "volunteerId": "v-high-1",
                            "tier": "冲",
                            "schoolName": "南宁学院第01组",
                            "majorName": "经济与金融",
                        },
                        {
                            "position": 2,
                            "volunteerId": "v-high-2",
                            "tier": "冲",
                            "schoolName": "南宁学院第01组",
                            "majorName": "工商管理",
                        },
                        {
                            "position": 68,
                            "volunteerId": "v-coop-1",
                            "tier": "稳",
                            "schoolName": "浙江越秀外国语学院第01组",
                            "majorName": "网络与新媒体(中外合作办学)",
                        },
                    ]
                },
                "draftPlanState": {"items": []},
                "reviewState": {
                    "checks": [
                        {
                            "code": "high_tuition",
                            "passed": False,
                            "summary": "当前方案包含高收费专业",
                            "affectedVolunteerIds": ["v-high-1", "v-high-2"],
                        },
                        {
                            "code": "cooperative_program",
                            "passed": False,
                            "summary": "当前方案包含中外合作办学项目",
                            "affectedVolunteerIds": ["v-coop-1"],
                        },
                    ]
                },
                "profileState": {
                    "explicitProfile": {
                        "positiveMajors": ["网络与新媒体", "跨境电子商务"],
                    }
                },
            }
        ),
    ) as mock_state:
        result = asyncio.run(execute_plan_action(_ctx_with_pending("replace_units"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["result_kind"] == "adjustment_analysis"
    assert data["facts"]["suggestion_counts"] == {"add": 0, "reorder": 0, "replace": 0, "remove": 0}
    assert data["facts"]["actionable_suggestion_counts"] == {"add": 0, "reorder": 0, "replace": 0, "remove": 0}
    assert data["facts"]["has_actionable_suggestions"] is False
    assert data["facts"]["review_issue_hit_plan_examples"][0]["summary"] == "当前方案包含高收费专业"
    assert "南宁学院第01组-经济与金融(冲)@1" in data["summary"]
    assert "浙江越秀外国语学院第01组-网络与新媒体(中外合作办学)(稳)@68" in data["summary"]
    assert "如果你想直接开始，我建议先把整批高收费项替换成正常收费的志愿" in data["summary"]
    assert "review_issue_hit_plan_examples" in data["reply_focus"]
    mock_adjust.assert_awaited_once()
    mock_state.assert_awaited_once()


def test_execute_plan_action_runs_compensation_preview_with_structured_facts():
    payload = {
        "stage": "apply",
        "action_family": "preview_compensation",
        "context_summary": "阶段=reviewed；方案=45/45",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": False,
        "intent_relation": "unknown",
        "atomic_actions": [],
    }

    with patch(
        "app.handlers.compensation_handlers._preview_planning_compensation_request",
        new=AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "actions": [
                        {"summary": "补 2 个保底志愿", "volunteerIds": ["v1", "v2"]},
                        {"summary": "替换 1 个高收费志愿", "volunteerIds": ["v3"]},
                    ]
                },
            }
        ),
    ) as mock_preview:
        result = asyncio.run(execute_plan_action(_ctx_with_pending("regenerate_order"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is False
    assert data["result_kind"] == "compensation_preview"
    assert data["workspace_refresh_targets"] == []
    assert data["review_rerun"] is False
    assert "当前可先看的补齐建议共有 2 项动作，预计补入 3 个志愿" in data["summary"]
    assert data["facts"]["action_count"] == 2
    assert data["facts"]["estimated_fill_count"] == 3
    assert data["facts"]["estimated_volunteer_count"] == 3
    assert data["facts"]["action_summaries"] == ["补 2 个保底志愿", "替换 1 个高收费志愿"]
    assert data["next_step_hints"]
    mock_preview.assert_awaited_once()


def test_execute_plan_action_runs_compensation_preview_counts_major_group_units():
    payload = {
        "stage": "apply",
        "action_family": "preview_compensation",
        "context_summary": "阶段=reviewed；方案=28/30",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": False,
        "intent_relation": "unknown",
        "atomic_actions": [],
    }

    with patch(
        "app.handlers.compensation_handlers._preview_planning_compensation_request",
        new=AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "actions": [
                        {
                            "summary": "补足志愿总数量",
                            "unitIds": ["u1", "u2"],
                            "volunteerIds": ["u1_m1", "u2_m1", "u2_m2"],
                        }
                    ]
                },
            }
        ),
    ) as mock_preview:
        result = asyncio.run(execute_plan_action(_ctx_with_pending("apply_compensation"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["result_kind"] == "compensation_preview"
    assert "当前可先看的补齐建议共有 1 项动作，预计补入 2 个志愿" in data["summary"]
    assert data["facts"]["estimated_fill_count"] == 2
    assert data["facts"]["estimated_volunteer_count"] == 3
    mock_preview.assert_awaited_once()


def test_execute_plan_action_blocks_compensation_apply_when_plan_is_already_full():
    payload = {
        "stage": "apply",
        "action_family": "apply_compensation",
        "context_summary": "阶段=reviewed；方案=45/45",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": True,
        "intent_relation": "mixed",
        "atomic_actions": [],
    }

    with patch(
        "app.handlers.compensation_handlers._get_planning_state_request",
        new=AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "draftPlanState": {"summary": {"unitTotal": 45, "targetUnitCount": 45}},
                    "orderedPlanState": {"summary": {"unitTotal": 45, "targetUnitCount": 45}},
                },
            }
        ),
    ), patch(
        "app.handlers.compensation_handlers._preview_planning_compensation_request",
        new=AsyncMock(
            return_value={
                "code": 0,
                "data": {"actions": [{"summary": "补充梯度断层区间的候选", "volunteerIds": ["v1", "v2"]}]},
            }
        ),
    ), patch(
        "app.handlers.compensation_handlers._apply_planning_compensation_request",
        new=AsyncMock(return_value={"code": 0, "data": {}}),
    ) as mock_apply, patch(
        "app.tools.plan_execution_tool.run_planning_review",
        new=AsyncMock(return_value="should not review"),
    ) as mock_review:
        result = asyncio.run(execute_plan_action(_ctx_with_pending("apply_compensation"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is False
    assert data["result_kind"] == "error"
    assert data["workspace_refresh_targets"] == []
    assert "已经达到目标数量 45/45" in data["summary"]
    assert "直接应用会超过目标数量" in data["summary"]
    assert "blocked_over_target" in data["reply_focus"]
    mock_apply.assert_not_awaited()
    mock_review.assert_not_awaited()


def test_execute_plan_action_blocks_compensation_apply_when_estimated_fill_exceeds_remaining_gap():
    payload = {
        "stage": "apply",
        "action_family": "apply_compensation",
        "context_summary": "阶段=reviewed；方案=44/45",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": True,
        "intent_relation": "mixed",
        "atomic_actions": [],
    }

    with patch(
        "app.handlers.compensation_handlers._get_planning_state_request",
        new=AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "draftPlanState": {"summary": {"unitTotal": 44, "targetUnitCount": 45}},
                    "orderedPlanState": {"summary": {"unitTotal": 44, "targetUnitCount": 45}},
                },
            }
        ),
    ), patch(
        "app.handlers.compensation_handlers._preview_planning_compensation_request",
        new=AsyncMock(
            return_value={
                "code": 0,
                "data": {"actions": [
                    {"summary": "补足志愿总数量", "volunteerIds": ["v1"]},
                    {"summary": "补充梯度断层区间的候选", "volunteerIds": ["v2", "v3", "v4"]},
                ]},
            }
        ),
    ), patch(
        "app.handlers.compensation_handlers._apply_planning_compensation_request",
        new=AsyncMock(return_value={"code": 0, "data": {}}),
    ) as mock_apply:
        result = asyncio.run(execute_plan_action(_ctx_with_pending("apply_compensation"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is False
    assert data["result_kind"] == "error"
    assert "距离目标数量还差 1 个" in data["summary"]
    assert "预计会再补入 4 个志愿" in data["summary"]
    assert "直接应用会超过目标数量" in data["summary"]
    mock_apply.assert_not_awaited()


def test_execute_plan_action_allows_major_group_compensation_apply_when_unit_gap_matches():
    payload = {
        "stage": "apply",
        "action_family": "apply_compensation",
        "context_summary": "阶段=reviewed；方案=28/30",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": True,
        "intent_relation": "mixed",
        "atomic_actions": [],
    }

    with patch(
        "app.handlers.compensation_handlers._get_planning_state_request",
        new=AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "draftPlanState": {"summary": {"unitTotal": 28, "targetUnitCount": 30}},
                    "orderedPlanState": {"summary": {"unitTotal": 28, "targetUnitCount": 30}},
                },
            }
        ),
    ), patch(
        "app.handlers.compensation_handlers._preview_planning_compensation_request",
        new=AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "actions": [
                        {
                            "summary": "补足志愿总数量",
                            "unitIds": ["u1", "u2"],
                            "volunteerIds": ["u1_m1", "u2_m1", "u2_m2"],
                        }
                    ]
                },
            }
        ),
    ), patch(
        "app.handlers.compensation_handlers._apply_planning_compensation_request",
        new=AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "draftPlanState": {"summary": {"unitTotal": 30, "targetUnitCount": 30}},
                },
            }
        ),
    ) as mock_apply, patch(
        "app.tools.plan_execution_tool._refresh_review_and_state",
        new=AsyncMock(
            return_value={
                "orderedPlanState": {
                    "summary": {"unitTotal": 30, "targetUnitCount": 30},
                    "items": [
                        {"position": 1, "schoolName": "A组", "majorName": "专业1", "tier": "冲"},
                    ],
                },
                "draftPlanState": {"summary": {"unitTotal": 30, "targetUnitCount": 30}},
                "profileState": {"explicitProfile": {"positiveMajors": ["计算机类"]}},
            }
        ),
    ):
        result = asyncio.run(execute_plan_action(_ctx_with_pending("apply_compensation"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is True
    assert data["result_kind"] == "mutation_result"
    assert "系统已完成当前可安全补偿的志愿补入" in data["summary"]
    mock_apply.assert_awaited_once()


def test_append_intent_relation_summary_uses_major_group_unit_count():
    text = _append_intent_relation_summary(
        "base",
        {
            "orderedPlanState": {
                "summary": {"total": 2},
                "items": [
                    {
                        "volunteerId": "g1_m1",
                        "position": 1,
                        "schoolName": "北京石油化工学院(03)",
                        "majorName": "计算机科学与技术(4600元)",
                        "tier": "冲",
                    },
                    {
                        "volunteerId": "g1_m2",
                        "position": 2,
                        "schoolName": "北京石油化工学院(03)",
                        "majorName": "软件工程(4600元)",
                        "tier": "冲",
                    },
                    {
                        "volunteerId": "g2_m1",
                        "position": 3,
                        "schoolName": "湖北工程学院(01)",
                        "majorName": "自动化(4000元)",
                        "tier": "稳",
                    },
                ],
            },
            "profileState": {
                "explicitProfile": {
                    "positiveMajors": ["计算机类", "自动化类"],
                }
            },
        },
    )

    assert "当前方案里较贴近的有2个，明显冲突的有0个" in text


def test_execute_plan_action_blocks_compensation_apply_when_preview_has_no_actionable_candidates():
    payload = {
        "stage": "apply",
        "action_family": "apply_compensation",
        "context_summary": "阶段=reviewed；方案=47/45",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": True,
        "intent_relation": "mixed",
        "atomic_actions": [],
    }

    with patch(
        "app.handlers.compensation_handlers._get_planning_state_request",
        new=AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "draftPlanState": {"summary": {"unitTotal": 47, "targetUnitCount": 45}},
                    "orderedPlanState": {"summary": {"unitTotal": 47, "targetUnitCount": 45}},
                },
            }
        ),
    ), patch(
        "app.handlers.compensation_handlers._preview_planning_compensation_request",
        new=AsyncMock(return_value={"code": 0, "data": {"actions": []}}),
    ), patch(
        "app.handlers.compensation_handlers._apply_planning_compensation_request",
        new=AsyncMock(return_value={"code": 0, "data": {}}),
    ) as mock_apply:
        result = asyncio.run(execute_plan_action(_ctx_with_pending("apply_compensation"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is False
    assert data["result_kind"] == "error"
    assert "没有可安全补入的候选志愿" in data["summary"]
    mock_apply.assert_not_awaited()


def test_execute_plan_action_blocks_compensation_apply_when_plan_is_full_and_preview_has_no_actionable_candidates():
    payload = {
        "stage": "apply",
        "action_family": "apply_compensation",
        "context_summary": "阶段=reviewed；方案=30/30",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": True,
        "intent_relation": "mixed",
        "atomic_actions": [],
    }

    with patch(
        "app.handlers.compensation_handlers._get_planning_state_request",
        new=AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "draftPlanState": {"summary": {"unitTotal": 30, "targetUnitCount": 30}},
                    "orderedPlanState": {"summary": {"unitTotal": 30, "targetUnitCount": 30}},
                },
            }
        ),
    ), patch(
        "app.handlers.compensation_handlers._preview_planning_compensation_request",
        new=AsyncMock(return_value={"code": 0, "data": {"actions": []}}),
    ), patch(
        "app.handlers.compensation_handlers._apply_planning_compensation_request",
        new=AsyncMock(return_value={"code": 0, "data": {}}),
    ) as mock_apply:
        result = asyncio.run(execute_plan_action(_ctx_with_pending("apply_compensation"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is False
    assert data["result_kind"] == "error"
    assert "没有可安全补入的候选志愿" in data["summary"]
    assert "超量志愿" not in data["summary"]
    mock_apply.assert_not_awaited()


def test_execute_plan_action_runs_review_without_duplicate_rerun():
    payload = {
        "stage": "review",
        "action_family": "review_plan",
        "context_summary": "阶段=reviewed；方案=45/45",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": True,
        "intent_relation": "unknown",
        "atomic_actions": [],
    }

    with patch(
        "app.handlers.analysis_handlers._run_planning_review_request",
        new=AsyncMock(
                return_value={
                    "code": 0,
                    "data": {
                        "summary": {"riskCount": 1, "warnCount": 2, "passedCount": 8},
                        "checks": [
                            {
                                "passed": False,
                                "summary": "保区占比过低",
                                "affectedVolunteerIds": ["v-review-1"],
                            }
                        ],
                    },
                }
            ),
        ) as mock_review_request, patch(
        "app.handlers.analysis_handlers._get_planning_state_with_latest_profile",
        new=AsyncMock(
            return_value={
                "orderedPlanState": {
                    "items": [
                        {
                            "position": 39,
                            "volunteerId": "v-review-1",
                            "tier": "稳",
                            "schoolName": "武汉东湖学院第01组",
                            "majorName": "网络与新媒体",
                        }
                    ]
                },
                "draftPlanState": {"items": []},
                "profileState": {
                    "explicitProfile": {
                        "positiveMajors": ["网络与新媒体", "跨境电子商务"],
                    }
                },
            }
        ),
    ) as mock_state:
        result = asyncio.run(execute_plan_action(_ctx_with_pending("replace_units"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["result_kind"] == "review_result"
    assert "已完成方案审查" in data["summary"]
    assert "保区占比过低" in data["summary"]
    assert data["review_rerun"] is False
    assert data["workspace_refresh_targets"] == ["review"]
    assert data["facts"]["risk_count"] == 1
    assert data["facts"]["warn_count"] == 2
    assert data["facts"]["issue_hit_plan_examples"][0]["summary"] == "保区占比过低"
    assert "武汉东湖学院第01组-网络与新媒体(稳)@39" in data["facts"]["issue_hit_plan_examples"][0]["items"][0]
    assert "网络与新媒体" in " ".join(data["facts"]["intent_relation"]["lines"])
    assert "典型涉及" in data["summary"]
    assert "review_result" in data["reply_focus"]
    mock_review_request.assert_awaited_once()
    mock_state.assert_awaited_once()


def test_execute_plan_action_remembers_recent_result_for_timeout_fallback():
    session_id = "exec-timeout"
    prompt = "帮我审查一下当前方案"
    payload = {
        "stage": "apply",
        "action_family": "review_plan",
        "context_summary": "阶段=reviewed；方案=45/45",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": False,
        "intent_relation": "unknown",
        "atomic_actions": [],
    }

    clear_recent_plan_execution_result(session_id)
    with patch(
        "app.handlers.analysis_handlers._run_planning_review_request",
        new=AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "summary": {"riskCount": 0, "warnCount": 1, "passedCount": 9},
                    "checks": [{"passed": False, "summary": "冲区梯度略紧"}],
                },
            }
        ),
    ), patch(
        "app.handlers.analysis_handlers._get_planning_state_with_latest_profile",
        new=AsyncMock(
            return_value={
                "orderedPlanState": {
                    "items": [
                        {
                            "position": 33,
                            "tier": "冲",
                            "schoolName": "汉口学院第01组",
                            "majorName": "网络与新媒体",
                        }
                    ]
                },
                "draftPlanState": {"items": []},
                "profileState": {
                    "explicitProfile": {
                        "positiveMajors": ["网络与新媒体", "跨境电子商务"],
                    }
                },
            }
        ),
    ):
        result = asyncio.run(
            execute_plan_action(
                _ctx_with_history(
                    session_id=session_id,
                    chat_history=[{"role": "user", "content": prompt}],
                ),
                json.dumps(payload, ensure_ascii=False),
            )
        )

    data = json.loads(result)
    cached = consume_recent_plan_execution_result(session_id, " 帮我审查一下当前方案 ")

    assert cached == data
    assert cached["result_kind"] == "review_result"
    assert "网络与新媒体" in " ".join(cached["facts"]["intent_relation"]["lines"])
    assert consume_recent_plan_execution_result(session_id, prompt) is None


def test_execute_plan_action_runs_regenerate_order_and_rerun_review():
    payload = {
        "stage": "apply",
        "action_family": "regenerate_order",
        "context_summary": "阶段=ordered；方案=30/30",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": True,
        "intent_relation": "support",
        "atomic_actions": [],
    }

    with patch(
        "app.handlers.mutation_handlers._regenerate_ordered_plan",
        new=AsyncMock(return_value="reorder ok"),
    ) as mock_reorder, patch(
        "app.tools.plan_execution_tool.run_planning_review",
        new=AsyncMock(return_value="review after reorder ok"),
    ) as mock_review:
        result = asyncio.run(execute_plan_action(_ctx_with_pending("regenerate_order"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["result_kind"] == "mutation_result"
    assert "reorder ok" in data["summary"]
    assert "review after reorder ok" in data["summary"]
    assert data["review_rerun"] is True
    assert data["workspace_refresh_targets"] == ["ordered", "review"]
    assert "regenerated_order" in data["reply_focus"]
    mock_reorder.assert_awaited_once()
    mock_review.assert_awaited_once()


def test_execute_plan_action_runs_replace_units_and_rerun_review():
    payload = {
        "stage": "apply",
        "action_family": "replace_units",
        "context_summary": "阶段=ordered；方案=30/30",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": True,
        "intent_relation": "mixed",
        "atomic_actions": [
            {
                "action_type": "replace_units",
                "volunteer_ids": ["old-1", "old-2"],
                "target_position": None,
                "filters": {
                    "tier": "稳",
                    "province_keyword": "北京",
                    "school_keyword": "",
                    "major_keyword": "计算机",
                    "school_tags": "[]",
                    "major_tags": "[]",
                    "limit": "2",
                },
                "reason": "换成北京计算机",
            }
        ],
    }

    with patch(
        "app.handlers.mutation_handlers.remove_planning_ordered_items",
        new=AsyncMock(return_value="remove old ok"),
    ) as mock_remove, patch(
        "app.handlers.mutation_handlers._select_candidates_by_filters_into_plan",
        new=AsyncMock(return_value="add replacement ok"),
    ) as mock_add, patch(
        "app.tools.plan_execution_tool.run_planning_review",
        new=AsyncMock(return_value="review after replace ok"),
    ) as mock_review:
        result = asyncio.run(execute_plan_action(_ctx_with_pending("replace_units"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is True
    assert data["result_kind"] == "mutation_result"
    assert data["review_rerun"] is True
    assert data["intent_effect"] == "strengthened"
    assert data["workspace_refresh_targets"] == ["ordered", "review"]
    assert data["affected_volunteer_ids"] == ["old-1", "old-2"]
    assert data["executed_actions"][0]["action"] == "replace_units"
    assert "remove old ok" in data["summary"]
    assert "add replacement ok" in data["summary"]
    assert "review after replace ok" in data["summary"]
    assert "replacement_result" in data["reply_focus"]
    mock_remove.assert_awaited_once()
    assert mock_remove.await_args.args[1] == ["old-1", "old-2"]
    mock_add.assert_awaited_once()
    assert mock_add.await_args.kwargs["province_keyword"] == "北京"
    assert mock_add.await_args.kwargs["major_keyword"] == "计算机"
    assert mock_add.await_args.kwargs["limit"] == 2
    mock_review.assert_awaited_once()


def test_execute_plan_action_replace_high_tuition_preview_counts_only_filtered_candidates():
    payload = {
        "stage": "preview",
        "action_family": "replace_units",
        "user_goal": "把贵的换成正常收费的，别少名额",
        "context_summary": "阶段=reviewed；方案=30/30",
        "preview_summary": "",
        "missing_inputs": [],
        "atomic_actions": [
            {
                "action_type": "replace_units",
                "volunteer_ids": [],
                "target_position": None,
                "filters": {
                    "major_tags": json.dumps(["计算机类"], ensure_ascii=False),
                    "school_tags": "[]",
                    "limit": "2",
                },
                "reason": "把贵的换成正常收费的，别少名额",
                "review_issue_target": {
                    "code": "high_tuition",
                    "scope_mode": "full_issue",
                    "scope_fingerprint": "issue-high-2",
                    "label": "高收费",
                    "scope_kind": "item_removal",
                    "default_action_family": "remove_units",
                },
            }
        ],
    }

    ordered_items = [
        {"position": 1, "volunteerId": "u1_a", "schoolName": "A大学(01)", "majorName": "电子信息工程(21000元)", "tier": "稳"},
        {"position": 2, "volunteerId": "u1_b", "schoolName": "A大学(01)", "majorName": "自动化(21000元)", "tier": "稳"},
        {"position": 3, "volunteerId": "u2_a", "schoolName": "B大学(02)", "majorName": "机器人工程(22000元)", "tier": "稳"},
    ]
    planning_state = {
        "reviewState": {
            "checks": [
                {
                    "code": "high_tuition",
                    "passed": False,
                    "summary": "当前方案包含高收费专业",
                    "affectedVolunteerIds": ["u1_a", "u1_b", "u2_a"],
                }
            ]
        }
    }

    with patch(
        "app.tools.plan_execution_tool._get_planning_ordered_plan_request",
        new=AsyncMock(return_value={"code": 0, "data": {"items": ordered_items}}),
    ), patch(
        "app.tools.plan_execution_tool._get_planning_state_request",
        new=AsyncMock(return_value={"code": 0, "data": planning_state}),
    ), patch(
        "app.handlers.generate_handler._generate_planning_candidate_pool_request",
        new=AsyncMock(return_value={"code": 0}),
    ), patch(
        "app.tools.plan_execution_tool._query_planning_candidate_pool_request",
        new=AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "items": [
                        {"volunteerId": "high-1", "tuitionPerYear": 36000, "majorPlanTags": ["学费：36000/年"]},
                        {"volunteerId": "ok-1", "tuitionPerYear": 18000, "majorPlanTags": ["学费：18000/年"]},
                    ],
                    "total": 2,
                    "totalUnitCount": 2,
                },
            }
        ),
    ):
        result = asyncio.run(execute_plan_action(_ctx(), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is False
    assert data["result_kind"] == "error"
    assert "只找到 1 个可补入候选" in data["summary"]


def test_execute_plan_action_replace_expands_broad_major_targets_to_all_matching_ordered_items():
    payload = {
        "stage": "apply",
        "action_family": "replace_units",
        "user_goal": "把会计审计替换成跨境电子商务和网络与新媒体",
        "context_summary": "阶段=ordered；方案=45/45",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": False,
        "intent_relation": "mixed",
        "atomic_actions": [
            {
                "action_type": "replace_units",
                "volunteer_ids": ["南宁学院第01组-会计学", "广州新华学院第01组-审计学"],
                "target_position": None,
                "filters": {
                    "major_tags": "[\"跨境电子商务\", \"网络与新媒体\"]",
                    "limit": "5",
                },
                "reason": "替换会计审计志愿",
            }
        ],
    }
    ordered_items = [
        {"volunteerId": "v1", "schoolName": "南宁学院第01组", "majorName": "会计学", "tier": "冲"},
        {"volunteerId": "v2", "schoolName": "滇池学院第01组", "majorName": "会计学(办学地点:杨林校区)", "tier": "冲"},
        {"volunteerId": "v3", "schoolName": "广州新华学院第01组", "majorName": "审计学(东莞校区)", "tier": "稳"},
        {"volunteerId": "v4", "schoolName": "广东白云学院第01组", "majorName": "审计学(办学地点:北校区)", "tier": "保"},
        {"volunteerId": "v5", "schoolName": "青岛城市学院第03组", "majorName": "英语", "tier": "保"},
    ]

    with patch(
        "app.tools.plan_execution_tool._get_planning_ordered_plan_request",
        new=AsyncMock(return_value={"code": 0, "data": {"items": ordered_items}}),
    ), patch(
        "app.handlers.mutation_handlers.remove_planning_ordered_items",
        new=AsyncMock(return_value="remove old ok"),
    ) as mock_remove, patch(
        "app.handlers.mutation_handlers._select_candidates_by_filters_into_plan",
        new=AsyncMock(return_value="add replacement ok"),
    ):
        result = asyncio.run(
                execute_plan_action(
                _ctx_with_pending("replace_units"),
                json.dumps(payload, ensure_ascii=False),
            )
        )

    data = json.loads(result)
    assert data["applied"] is True
    assert data["affected_volunteer_ids"] == ["v1", "v3", "v2", "v4"]
    mock_remove.assert_awaited_once()
    assert mock_remove.await_args.args[1] == ["v1", "v3", "v2", "v4"]


def test_execute_plan_action_replace_without_added_candidate_explains_unit_total_semantics():
    payload = {
        "stage": "apply",
        "action_family": "replace_units",
        "context_summary": "阶段=ordered；方案=45/45",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": False,
        "intent_relation": "mixed",
        "atomic_actions": [
            {
                "action_type": "replace_units",
                "volunteer_ids": ["old-1"],
                "target_position": None,
                "filters": {
                    "major_tags": "[\"电子信息类\"]",
                    "limit": "1",
                },
                "reason": "替换冲突志愿",
            }
        ],
    }

    with patch(
        "app.handlers.mutation_handlers.remove_planning_ordered_items",
        new=AsyncMock(return_value="已从当前方案移出1个志愿，并同步刷新排序方案。\n- 排序总数：45/45"),
    ), patch(
        "app.handlers.mutation_handlers._select_candidates_by_filters_into_plan",
        new=AsyncMock(return_value="当前条件下没有找到可加入方案的候选志愿。"),
    ):
        result = asyncio.run(execute_plan_action(_ctx_with_pending("replace_units"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is True
    assert "没有找到可加入方案的候选志愿" in data["summary"]
    assert "总数统计的是当前工作台里的方案项数量" in data["summary"]
    assert "该专业志愿本身已经移出" in data["summary"]


def test_execute_plan_action_normalizes_intent_relation_match_alias():
    payload = {
        "stage": "apply",
        "action_family": "replace_units",
        "context_summary": "阶段=ordered；方案=45/45",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": False,
        "intent_relation": "match",
        "atomic_actions": [
            {
                "action_type": "replace_units",
                "volunteer_ids": ["old-1"],
                "target_position": None,
                "filters": {
                    "major_tags": "[\"计算机类\"]",
                    "limit": "1",
                },
                "reason": "替换成更贴合当前意向的方向",
            }
        ],
    }

    with patch(
        "app.handlers.mutation_handlers.remove_planning_ordered_items",
        new=AsyncMock(return_value="已从当前方案移出1个志愿，并同步刷新排序方案。"),
    ), patch(
        "app.handlers.mutation_handlers._select_candidates_by_filters_into_plan",
        new=AsyncMock(return_value="已把1个志愿加入当前方案，并同步刷新排序结果。"),
    ):
        result = asyncio.run(execute_plan_action(_ctx_with_pending("replace_units"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is True
    assert data["intent_effect"] == "strengthened"
    assert data["action_family"] == "replace_units"


def test_execute_plan_action_replace_with_matched_candidates_but_no_count_increase_explains_unit_total_semantics():
    payload = {
        "stage": "apply",
        "action_family": "replace_units",
        "context_summary": "阶段=ordered；方案=47/45",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": False,
        "intent_relation": "support",
        "atomic_actions": [
            {
                "action_type": "replace_units",
                "volunteer_ids": ["old-1"],
                "target_position": None,
                "filters": {
                    "major_tags": "[\"计算机类\"]",
                    "limit": "5",
                },
                "reason": "替换成更贴合当前意向的方向",
            }
        ],
    }

    with patch(
        "app.handlers.mutation_handlers.remove_planning_ordered_items",
        new=AsyncMock(return_value="已从当前方案移出1个志愿，并同步刷新排序方案。\n- 排序总数：47/45"),
    ), patch(
        "app.handlers.mutation_handlers._select_candidates_by_filters_into_plan",
        new=AsyncMock(
            return_value=(
                "按条件匹配到 5 个候选志愿，但当前方案数量没有增加，"
                "可能这些志愿已在方案中，或没有被后端接受为新增。"
            )
        ),
    ):
        result = asyncio.run(execute_plan_action(_ctx_with_pending("replace_units"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is True
    assert "当前方案数量没有增加" in data["summary"]
    assert "总数统计的是当前工作台里的方案项数量" in data["summary"]
    assert "候选本来就在方案里" in data["summary"]


def test_execute_plan_action_replace_missing_refs_does_not_refresh_workspace():
    payload = {
        "stage": "apply",
        "action_family": "replace_units",
        "context_summary": "阶段=ordered；方案=45/45",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": True,
        "intent_relation": "mixed",
        "atomic_actions": [
            {
                "action_type": "replace_units",
                "volunteer_ids": ["广西师范大学006专业组-生物科学"],
                "target_position": None,
                "filters": {
                    "major_keyword": "电子信息",
                    "limit": "1",
                },
                "reason": "替换生物科学",
            }
        ],
    }

    with patch(
        "app.tools.plan_execution_tool._get_planning_ordered_plan_request",
        new=AsyncMock(return_value={"code": 0, "data": {"items": []}}),
    ), patch(
        "app.handlers.mutation_handlers.remove_planning_ordered_items",
        new=AsyncMock(return_value="should not remove"),
    ) as mock_remove, patch(
        "app.tools.plan_execution_tool.run_planning_review",
        new=AsyncMock(return_value="should not review"),
    ) as mock_review:
        result = asyncio.run(execute_plan_action(_ctx_with_pending("replace_units"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is False
    assert data["result_kind"] == "error"
    assert data["workspace_refresh_targets"] == []
    assert "真实编号" in data["summary"]
    assert "needs_volunteer_selection" in data["reply_focus"]
    mock_remove.assert_not_awaited()
    mock_review.assert_not_awaited()


def test_execute_plan_action_replace_preview_requires_resolved_refs_before_confirmation():
    payload = {
        "stage": "preview",
        "action_family": "replace_units",
        "context_summary": "阶段=ordered；方案=45/45",
        "preview_summary": "会先移出指定志愿，再按新的筛选条件补入候选，并在执行后重新审查整体结构。",
        "missing_inputs": [],
        "should_rerun_review": False,
        "intent_relation": "mixed",
        "atomic_actions": [
            {
                "action_type": "replace_units",
                "volunteer_ids": ["广西师范大学 生物科学"],
                "target_position": None,
                "filters": {
                    "major_tags": json.dumps(["计算机类", "电子信息类"], ensure_ascii=False),
                    "limit": "3",
                },
                "reason": "替换冲突志愿",
            }
        ],
    }

    with patch(
        "app.tools.plan_execution_tool._get_planning_ordered_plan_request",
        new=AsyncMock(return_value={"code": 0, "data": {"items": []}}),
    ), patch(
        "app.handlers.mutation_handlers.remove_planning_ordered_items",
        new=AsyncMock(return_value="should not remove"),
    ) as mock_remove:
        result = asyncio.run(execute_plan_action(_ctx_with_pending("replace_units"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is False
    assert data["stage"] == "preview"
    assert data["result_kind"] == "error"
    assert "真实编号" in data["summary"]
    assert "needs_volunteer_selection" in data["reply_focus"]
    mock_remove.assert_not_awaited()


def test_execute_plan_action_replace_resolves_short_display_ref_by_unique_partial_match():
    payload = {
        "stage": "apply",
        "action_family": "replace_units",
        "context_summary": "阶段=ordered；方案=45/45",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": True,
        "intent_relation": "mixed",
        "atomic_actions": [
            {
                "action_type": "replace_units",
                "volunteer_ids": ["广西师范大学006专业组-生物科学"],
                "target_position": None,
                "filters": {
                    "major_keyword": "电子信息",
                    "limit": "1",
                },
                "reason": "替换生物科学",
            }
        ],
    }

    with patch(
        "app.tools.plan_execution_tool._get_planning_ordered_plan_request",
        new=AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "items": [
                        {
                            "volunteerId": "bio-1",
                            "schoolName": "广西师范大学006专业组",
                            "majorName": "生物科学(不招色盲色弱及单色识别不全者)(师范类)",
                        },
                        {
                            "volunteerId": "info-1",
                            "schoolName": "广西师范大学006专业组",
                            "majorName": "电子信息工程",
                        },
                    ]
                },
            }
        ),
    ), patch(
        "app.handlers.mutation_handlers.remove_planning_ordered_items",
        new=AsyncMock(return_value="remove bio ok"),
    ) as mock_remove, patch(
        "app.handlers.mutation_handlers._select_candidates_by_filters_into_plan",
        new=AsyncMock(return_value="add info ok"),
    ) as mock_add, patch(
        "app.tools.plan_execution_tool.run_planning_review",
        new=AsyncMock(return_value="review ok"),
    ):
        result = asyncio.run(execute_plan_action(_ctx_with_pending("replace_units"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is True
    assert data["workspace_refresh_targets"] == ["ordered", "review"]
    assert data["affected_volunteer_ids"] == ["bio-1"]
    mock_remove.assert_awaited_once()
    assert mock_remove.await_args.args[1] == ["bio-1"]
    mock_add.assert_awaited_once()


def test_execute_plan_action_remove_resolves_major_ref_without_trailing_fee_suffix():
    payload = {
        "stage": "apply",
        "action_family": "remove_units",
        "context_summary": "阶段=reviewed；方案=30/30",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": True,
        "intent_relation": "unknown",
        "atomic_actions": [
            {
                "action_type": "remove_units",
                "volunteer_ids": ["武昌理工学院(02)-智能科学与技术(华为精英班)@23"],
                "target_position": None,
                "filters": {},
                "reason": "先处理高收费专业",
            }
        ],
    }

    with patch(
        "app.tools.plan_execution_tool._get_planning_ordered_plan_request",
        new=AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "items": [
                        {
                            "position": 23,
                            "volunteerId": "wclg-23",
                            "schoolName": "武昌理工学院(02)",
                            "majorName": "智能科学与技术(华为精英班)(28800元)",
                            "tier": "稳",
                        },
                    ]
                },
            }
        ),
    ), patch(
        "app.handlers.mutation_handlers.remove_planning_ordered_items",
        new=AsyncMock(return_value="remove ok"),
    ) as mock_remove, patch(
        "app.tools.plan_execution_tool.run_planning_review",
        new=AsyncMock(return_value="review ok"),
    ):
        result = asyncio.run(execute_plan_action(_ctx_with_pending("remove_units"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is True
    assert data["result_kind"] == "mutation_result"
    assert data["affected_volunteer_ids"] == ["wclg-23"]
    mock_remove.assert_awaited_once()
    assert mock_remove.await_args.args[1] == ["wclg-23"]


def test_execute_plan_action_replace_resolves_position_ref():
    payload = {
        "stage": "apply",
        "action_family": "replace_units",
        "context_summary": "阶段=ordered；方案=45/45",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": True,
        "intent_relation": "mixed",
        "atomic_actions": [
            {
                "action_type": "replace_units",
                "volunteer_ids": ["@90"],
                "target_position": None,
                "filters": {
                    "major_tags": json.dumps(["电子信息类", "自动化类"], ensure_ascii=False),
                    "limit": "3",
                },
                "reason": "替换生物科学",
            }
        ],
    }

    with patch(
        "app.tools.plan_execution_tool._get_planning_ordered_plan_request",
        new=AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "items": [
                        {
                            "position": 90,
                            "volunteerId": "bio-position-90",
                            "schoolName": "广西师范大学006专业组",
                            "majorName": "生物科学(不招色盲色弱及单色识别不全者)(师范类)",
                        },
                    ]
                },
            }
        ),
    ), patch(
        "app.handlers.mutation_handlers.remove_planning_ordered_items",
        new=AsyncMock(return_value="remove bio ok"),
    ) as mock_remove, patch(
        "app.handlers.mutation_handlers._select_candidates_by_filters_into_plan",
        new=AsyncMock(return_value="add replacements ok"),
    ) as mock_add, patch(
        "app.tools.plan_execution_tool.run_planning_review",
        new=AsyncMock(return_value="review ok"),
    ):
        result = asyncio.run(execute_plan_action(_ctx_with_pending("replace_units"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is True
    assert data["affected_volunteer_ids"] == ["bio-position-90"]
    mock_remove.assert_awaited_once()
    assert mock_remove.await_args.args[1] == ["bio-position-90"]
    mock_add.assert_awaited_once()


def test_execute_plan_action_replace_resolves_verbose_ref_with_tier_and_position_suffix():
    payload = {
        "stage": "apply",
        "action_family": "replace_units",
        "context_summary": "阶段=ordered；方案=45/45",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": True,
        "intent_relation": "mixed",
        "atomic_actions": [
            {
                "action_type": "replace_units",
                "volunteer_ids": ["广西师范大学006专业组-生物科学(不招色盲色弱及单色识别不全者)(师范类)(保)@90"],
                "target_position": None,
                "filters": {
                    "major_tags": json.dumps(["电子信息类", "自动化类"], ensure_ascii=False),
                    "limit": "2",
                },
                "reason": "替换生物科学",
            }
        ],
    }

    with patch(
        "app.tools.plan_execution_tool._get_planning_ordered_plan_request",
        new=AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "items": [
                        {
                            "position": 90,
                            "tier": "保",
                            "volunteerId": "bio-verbose-90",
                            "schoolName": "广西师范大学006专业组",
                            "majorName": "生物科学(不招色盲色弱及单色不能识别者)(师范类)",
                        },
                    ]
                },
            }
        ),
    ), patch(
        "app.handlers.mutation_handlers.remove_planning_ordered_items",
        new=AsyncMock(return_value="remove bio ok"),
    ) as mock_remove, patch(
        "app.handlers.mutation_handlers._select_candidates_by_filters_into_plan",
        new=AsyncMock(return_value="add replacements ok"),
    ) as mock_add, patch(
        "app.tools.plan_execution_tool.run_planning_review",
        new=AsyncMock(return_value="review ok"),
    ):
        result = asyncio.run(execute_plan_action(_ctx_with_pending("replace_units"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is True
    assert data["affected_volunteer_ids"] == ["bio-verbose-90"]
    mock_remove.assert_awaited_once()
    assert mock_remove.await_args.args[1] == ["bio-verbose-90"]
    mock_add.assert_awaited_once()


def test_execute_plan_action_blocks_pin_unit_in_301_workspace():
    payload = {
        "stage": "apply",
        "action_family": "pin_unit",
        "context_summary": "阶段=ordered；方案=30/30",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": True,
        "intent_relation": "unknown",
        "atomic_actions": [
            {
                "action_type": "pin_unit",
                "volunteer_ids": ["v1"],
                "target_position": 3,
                "filters": {},
                "reason": "固定到第三位",
            }
        ],
    }

    with patch(
        "app.tools.plan_execution_tool.pin_planning_ordered_item",
        new=AsyncMock(return_value="pin ok"),
    ) as mock_pin, patch(
        "app.tools.plan_execution_tool.run_planning_review",
        new=AsyncMock(return_value="review after pin ok"),
    ) as mock_review:
        result = asyncio.run(execute_plan_action(_ctx_with_pending("pin_unit"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is False
    assert data["result_kind"] == "error"
    assert data["workspace_refresh_targets"] == []
    assert "pin_disabled" in data["reply_focus"]
    assert "暂不提供固定/锁定志愿入口" in data["summary"]
    mock_pin.assert_not_awaited()
    mock_review.assert_not_awaited()


def test_execute_plan_action_runs_move_unit_after_resolving_position_ref():
    payload = {
        "stage": "apply",
        "action_family": "move_unit",
        "context_summary": "阶段=ordered；方案=30/30",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": True,
        "intent_relation": "unknown",
        "atomic_actions": [
            {
                "action_type": "move_unit",
                "volunteer_ids": ["@20"],
                "target_position": 3,
                "filters": {},
                "reason": "把第20位前移到第3位",
            }
        ],
    }

    with patch(
        "app.tools.plan_execution_tool._get_planning_ordered_plan_request",
        new=AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "items": [
                        {
                            "position": 20,
                            "volunteerId": "v20",
                            "schoolName": "湖北工程学院(01)",
                            "majorName": "计算机科学与技术",
                        }
                    ]
                },
            }
        ),
    ), patch(
        "app.handlers.mutation_handlers.move_planning_ordered_item",
        new=AsyncMock(return_value="move ok"),
    ) as mock_move, patch(
        "app.tools.plan_execution_tool.run_planning_review",
        new=AsyncMock(return_value="review after move ok"),
    ) as mock_review:
        result = asyncio.run(execute_plan_action(_ctx_with_pending("move_unit"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["result_kind"] == "mutation_result"
    assert data["affected_volunteer_ids"] == ["v20"]
    assert data["workspace_refresh_targets"] == ["ordered", "review"]
    assert "move ok" in data["summary"]
    assert "review after move ok" in data["summary"]
    mock_move.assert_awaited_once()
    assert mock_move.await_args.args[1:] == ("v20", 3)
    mock_review.assert_awaited_once()


def test_execute_plan_action_runs_move_unit_after_resolving_school_major_ref():
    payload = {
        "stage": "apply",
        "action_family": "move_unit",
        "context_summary": "阶段=ordered；方案=30/30",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": True,
        "intent_relation": "unknown",
        "atomic_actions": [
            {
                "action_type": "move_unit",
                "volunteer_ids": ["湖北工程学院的计算机科学与技术"],
                "target_position": 3,
                "filters": {},
                "reason": "把湖北工程学院的计算机科学与技术改到第3位",
            }
        ],
    }

    with patch(
        "app.tools.plan_execution_tool._get_planning_ordered_plan_request",
        new=AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "items": [
                        {
                            "position": 20,
                            "volunteerId": "hbgc-cs-20",
                            "schoolName": "湖北工程学院(01)",
                            "majorName": "计算机科学与技术(办学地点:校本部)",
                        }
                    ]
                },
            }
        ),
    ), patch(
        "app.handlers.mutation_handlers.move_planning_ordered_item",
        new=AsyncMock(return_value="move ok"),
    ) as mock_move, patch(
        "app.tools.plan_execution_tool.run_planning_review",
        new=AsyncMock(return_value="review after move ok"),
    ):
        result = asyncio.run(execute_plan_action(_ctx_with_pending("move_unit"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["result_kind"] == "mutation_result"
    assert data["affected_volunteer_ids"] == ["hbgc-cs-20"]
    mock_move.assert_awaited_once()
    assert mock_move.await_args.args[1:] == ("hbgc-cs-20", 3)


def test_execute_plan_action_runs_move_unit_after_resolving_school_major_alias_ref():
    payload = {
        "stage": "apply",
        "action_family": "move_unit",
        "context_summary": "阶段=ordered；方案=30/30",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": True,
        "intent_relation": "unknown",
        "atomic_actions": [
            {
                "action_type": "move_unit",
                "volunteer_ids": ["广西师大统计"],
                "target_position": 3,
                "filters": {},
                "reason": "把广西师大统计改到第3位",
            }
        ],
    }

    with patch(
        "app.tools.plan_execution_tool._get_planning_ordered_plan_request",
        new=AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "items": [
                        {
                            "position": 20,
                            "volunteerId": "gxsd-stat-20",
                            "schoolName": "广西师范大学006专业组",
                            "majorName": "统计学",
                        }
                    ]
                },
            }
        ),
    ), patch(
        "app.handlers.mutation_handlers.move_planning_ordered_item",
        new=AsyncMock(return_value="move ok"),
    ) as mock_move, patch(
        "app.tools.plan_execution_tool.run_planning_review",
        new=AsyncMock(return_value="review after move ok"),
    ):
        result = asyncio.run(execute_plan_action(_ctx_with_pending("move_unit"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["result_kind"] == "mutation_result"
    assert data["affected_volunteer_ids"] == ["gxsd-stat-20"]
    mock_move.assert_awaited_once()
    assert mock_move.await_args.args[1:] == ("gxsd-stat-20", 3)


def test_execute_plan_action_runs_remove_unit_after_resolving_school_major_dot_ref():
    payload = {
        "stage": "apply",
        "action_family": "remove_units",
        "context_summary": "阶段=ordered；方案=30/30",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": True,
        "intent_relation": "unknown",
        "atomic_actions": [
            {
                "action_type": "remove_units",
                "volunteer_ids": ["湖北工程学院.计算机科学与技术"],
                "target_position": None,
                "filters": {},
                "reason": "去掉湖北工程学院.计算机科学与技术",
            }
        ],
    }

    with patch(
        "app.tools.plan_execution_tool._get_planning_ordered_plan_request",
        new=AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "items": [
                        {
                            "position": 20,
                            "volunteerId": "hbgc-cs-20",
                            "schoolName": "湖北工程学院(01)",
                            "majorName": "计算机科学与技术",
                        }
                    ]
                },
            }
        ),
    ), patch(
        "app.handlers.mutation_handlers.remove_planning_ordered_items",
        new=AsyncMock(return_value="remove ok"),
    ) as mock_remove, patch(
        "app.tools.plan_execution_tool.run_planning_review",
        new=AsyncMock(return_value="review after remove ok"),
    ):
        result = asyncio.run(execute_plan_action(_ctx_with_pending("remove_units"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["result_kind"] == "mutation_result"
    assert data["affected_volunteer_ids"] == ["hbgc-cs-20"]
    mock_remove.assert_awaited_once()
    assert mock_remove.await_args.args[1] == ["hbgc-cs-20"]


def test_execute_plan_action_does_not_guess_ambiguous_school_major_ref():
    payload = {
        "stage": "apply",
        "action_family": "move_unit",
        "context_summary": "阶段=ordered；方案=30/30",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": True,
        "intent_relation": "unknown",
        "atomic_actions": [
            {
                "action_type": "move_unit",
                "volunteer_ids": ["湖北工程学院的计算机科学与技术"],
                "target_position": 3,
                "filters": {},
                "reason": "把湖北工程学院的计算机科学与技术改到第3位",
            }
        ],
    }

    with patch(
        "app.tools.plan_execution_tool._get_planning_ordered_plan_request",
        new=AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "items": [
                        {
                            "position": 20,
                            "volunteerId": "hbgc01-cs-20",
                            "schoolName": "湖北工程学院(01)",
                            "majorName": "计算机科学与技术",
                        },
                        {
                            "position": 21,
                            "volunteerId": "hbgc02-cs-21",
                            "schoolName": "湖北工程学院(02)",
                            "majorName": "计算机科学与技术",
                        },
                    ]
                },
            }
        ),
    ), patch(
        "app.handlers.mutation_handlers.move_planning_ordered_item",
        new=AsyncMock(return_value="move ok"),
    ) as mock_move, patch(
        "app.tools.plan_execution_tool.run_planning_review",
        new=AsyncMock(return_value="review after move ok"),
    ):
        result = asyncio.run(execute_plan_action(_ctx_with_pending("move_unit"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is False
    assert data["result_kind"] == "error"
    assert "湖北工程学院的计算机科学与技术" in data["summary"]
    assert "needs_volunteer_selection" in data["reply_focus"]
    mock_move.assert_not_awaited()


def test_execute_plan_action_does_not_guess_ambiguous_school_major_alias_ref():
    payload = {
        "stage": "apply",
        "action_family": "move_unit",
        "context_summary": "阶段=ordered；方案=30/30",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": True,
        "intent_relation": "unknown",
        "atomic_actions": [
            {
                "action_type": "move_unit",
                "volunteer_ids": ["湖工计科"],
                "target_position": 3,
                "filters": {},
                "reason": "把湖工计科改到第3位",
            }
        ],
    }

    with patch(
        "app.tools.plan_execution_tool._get_planning_ordered_plan_request",
        new=AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "items": [
                        {
                            "position": 20,
                            "volunteerId": "hbgc-cs-20",
                            "schoolName": "湖北工程学院(01)",
                            "majorName": "计算机科学与技术",
                        },
                        {
                            "position": 21,
                            "volunteerId": "hbgy-cs-21",
                            "schoolName": "湖北工业大学(01)",
                            "majorName": "计算机科学与技术",
                        },
                    ]
                },
            }
        ),
    ), patch(
        "app.handlers.mutation_handlers.move_planning_ordered_item",
        new=AsyncMock(return_value="move ok"),
    ) as mock_move, patch(
        "app.tools.plan_execution_tool.run_planning_review",
        new=AsyncMock(return_value="review after move ok"),
    ):
        result = asyncio.run(execute_plan_action(_ctx_with_pending("move_unit"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is False
    assert data["result_kind"] == "error"
    assert "湖工计科" in data["summary"]
    assert "needs_volunteer_selection" in data["reply_focus"]
    mock_move.assert_not_awaited()


def test_execute_plan_action_blocks_pin_unit_without_resolving_position_ref():
    payload = {
        "stage": "apply",
        "action_family": "pin_unit",
        "context_summary": "阶段=ordered；方案=30/30",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": True,
        "intent_relation": "unknown",
        "atomic_actions": [
            {
                "action_type": "pin_unit",
                "volunteer_ids": ["第3位"],
                "target_position": 3,
                "filters": {},
                "reason": "固定第3位",
            }
        ],
    }

    with patch(
        "app.tools.plan_execution_tool._get_planning_ordered_plan_request",
        new=AsyncMock(),
    ) as mock_get_ordered, patch(
        "app.tools.plan_execution_tool.pin_planning_ordered_item",
        new=AsyncMock(return_value="pin ok"),
    ) as mock_pin, patch(
        "app.tools.plan_execution_tool.run_planning_review",
        new=AsyncMock(return_value="review after pin ok"),
    ) as mock_review:
        result = asyncio.run(execute_plan_action(_ctx_with_pending("pin_unit"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is False
    assert data["result_kind"] == "error"
    assert "暂不提供固定/锁定志愿入口" in data["summary"]
    mock_get_ordered.assert_not_awaited()
    mock_pin.assert_not_awaited()
    mock_review.assert_not_awaited()


def test_execute_plan_action_blocks_unpin_unit_in_301_workspace():
    payload = {
        "stage": "apply",
        "action_family": "unpin_unit",
        "context_summary": "阶段=ordered；方案=30/30",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": True,
        "intent_relation": "unknown",
        "atomic_actions": [
            {
                "action_type": "unpin_unit",
                "volunteer_ids": ["v1"],
                "target_position": None,
                "filters": {},
                "reason": "取消固定",
            }
        ],
    }

    with patch(
        "app.tools.plan_execution_tool.unpin_planning_ordered_item",
        new=AsyncMock(return_value="unpin ok"),
    ) as mock_unpin, patch(
        "app.tools.plan_execution_tool.run_planning_review",
        new=AsyncMock(return_value="review after unpin ok"),
    ) as mock_review:
        result = asyncio.run(execute_plan_action(_ctx_with_pending("unpin_unit"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is False
    assert data["result_kind"] == "error"
    assert data["workspace_refresh_targets"] == []
    assert "pin_disabled" in data["reply_focus"]
    assert "暂不提供固定/锁定志愿入口" in data["summary"]
    mock_unpin.assert_not_awaited()
    mock_review.assert_not_awaited()


def test_execute_plan_action_replace_missing_refs_message_stays_generic():
    payload = {
        "stage": "apply",
        "action_family": "replace_units",
        "context_summary": "阶段=ordered；方案=30/30",
        "preview_summary": "",
        "missing_inputs": [],
        "should_rerun_review": True,
        "intent_relation": "mixed",
        "atomic_actions": [
            {
                "action_type": "replace_units",
                "volunteer_ids": ["湖北工程学院-计算机科学与技术"],
                "target_position": None,
                "filters": {"major_keyword": "电子信息", "limit": "1"},
                "reason": "替换为电子信息方向",
            }
        ],
    }

    with patch(
        "app.tools.plan_execution_tool._get_planning_ordered_plan_request",
        new=AsyncMock(return_value={"code": 0, "data": {"items": []}}),
    ):
        result = asyncio.run(execute_plan_action(_ctx_with_pending("replace_units"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is False
    assert data["result_kind"] == "error"
    assert "会计/审计" not in data["summary"]
    assert "按当前方案重新定位" in data["summary"]


def test_execute_plan_action_moves_major_group_unit_by_position_ref():
    payload = {
        "stage": "apply",
        "action_family": "move_ordered_unit",
        "user_goal": "把第3个专业组移到第5位",
        "context_summary": "阶段=ordered；方案=30/30",
        "missing_inputs": [],
        "atomic_actions": [
            {
                "action_type": "move_ordered_unit",
                "unit_ids": [],
                "target_position": 5,
                "filters": {},
                "reason": "把第3个专业组移到第5位",
            }
        ],
    }
    state = {
        "orderedPlanState": {
            "units": [
                {"unitId": "unit-1"},
                {"unitId": "unit-2"},
                {"unitId": "unit-3"},
            ]
        }
    }

    with patch(
        "app.tools.plan_execution_tool._get_planning_state_request",
        new=AsyncMock(return_value={"code": 0, "data": state}),
    ) as mock_state, patch(
        "app.tools.plan_execution_tool._move_planning_ordered_plan_unit_request",
        new=AsyncMock(return_value={"code": 0, "data": {"message": "move ok"}}),
    ) as mock_move:
        result = asyncio.run(execute_plan_action(_ctx_with_pending("move_ordered_unit"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is True
    assert data["action_family"] == "move_ordered_unit"
    assert data["workspace_refresh_targets"] == ["ordered", "review"]
    assert data["executed_actions"] == [{"action": "move_ordered_unit", "unitIds": ["unit-3"]}]
    assert data["summary"] == "move ok"
    mock_state.assert_awaited()
    mock_move.assert_awaited_once_with(1, "exec-1", "unit-3", 5)


def test_execute_plan_action_removes_major_group_unit_by_explicit_unit_id():
    payload = {
        "stage": "apply",
        "action_family": "remove_ordered_unit",
        "user_goal": "删除这个专业组",
        "context_summary": "阶段=ordered；方案=30/30",
        "missing_inputs": [],
        "atomic_actions": [
            {
                "action_type": "remove_ordered_unit",
                "unit_ids": ["unit-9"],
                "target_position": None,
                "filters": {},
                "reason": "删除这个专业组",
            }
        ],
    }

    with patch(
        "app.tools.plan_execution_tool._remove_planning_ordered_plan_units_request",
        new=AsyncMock(return_value={"code": 0, "data": {"message": "remove ok"}}),
    ) as mock_remove:
        result = asyncio.run(execute_plan_action(_ctx_with_pending("remove_ordered_unit"), json.dumps(payload, ensure_ascii=False)))

    data = json.loads(result)
    assert data["applied"] is True
    assert data["action_family"] == "remove_ordered_unit"
    assert data["workspace_refresh_targets"] == ["ordered", "review"]
    assert data["executed_actions"] == [{"action": "remove_ordered_unit", "unitIds": ["unit-9"]}]
    assert data["summary"] == "remove ok"
    mock_remove.assert_awaited_once_with(1, "exec-1", ["unit-9"])
