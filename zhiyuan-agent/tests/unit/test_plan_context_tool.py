from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.agent.context import RequestContext
from app.tools.plan_context_tool import collect_plan_context_inputs


def _ctx(session_id: str = "ctx-1") -> SimpleNamespace:
    return SimpleNamespace(deps=RequestContext(userid="u1", sessionid=session_id))


def test_collect_plan_context_inputs_reads_existing_planning_state():
    response = {
        "code": 0,
        "data": {
            "phase": "reviewed",
            "candidatePoolState": {"requiredCount": 30},
            "draftPlanState": {"summary": {"unitTotal": 18}},
            "orderedPlanState": {
                "summary": {"unitTotal": 20, "targetUnitCount": 30},
                "items": [{"volunteerId": "v1", "schoolName": "北京工业大学", "majorName": "计算机类", "tier": "稳", "position": 1}],
            },
            "profileState": {
                "explicitProfile": {
                    "positiveRegions": ["北京"],
                    "positiveMajors": ["计算机类"],
                },
                "latentProfile": {
                    "futureDevelopment": {"careerTypes": ["system_public_service"]},
                },
            },
            "reviewState": {
                "summary": {"riskCount": 1, "warnCount": 2},
                "checks": [
                    {
                        "code": "high_tuition",
                        "passed": False,
                        "summary": "当前方案包含高收费专业",
                        "affectedVolunteerIds": ["v1"],
                    }
                ],
            },
        },
    }

    with patch(
        "app.tools.plan_context_tool.get_planning_state",
        new=AsyncMock(return_value=response),
    ), patch(
        "app.tools.plan_context_tool.get_user_profile",
        new=AsyncMock(return_value={"code": 0, "data": {}}),
    ):
        result = asyncio.run(collect_plan_context_inputs(_ctx()))

    data = json.loads(result)
    assert data["phase"] == "reviewed"
    assert data["target_count"] == 30
    assert data["ordered_count"] == 20
    assert data["positive_regions"] == ["北京"]
    assert data["positive_majors"] == ["计算机类"]
    assert data["career_types"] == ["体制内/考公导向"]
    assert data["review_issues"][0]["code"] == "high_tuition"
    assert data["review_issues"][0]["default_action_family"] == "remove_units"
    assert data["review_issue_summary_lines"] == ["高收费(1u/1v)"]
    assert "已有 20 个志愿（目标 30 个）" in data["summary"]
    assert "审查问题：高收费(1u/1v)" in data["summary"]


def test_collect_plan_context_inputs_includes_negative_preferences_and_conflict_lines():
    response = {
        "code": 0,
        "data": {
            "phase": "ordered",
            "candidatePoolState": {"requiredCount": 30},
            "draftPlanState": {"summary": {"unitTotal": 20}},
            "orderedPlanState": {
                "summary": {"unitTotal": 20, "targetUnitCount": 30},
                "items": [
                    {
                        "schoolName": "上海大学",
                        "majorName": "工商管理",
                        "tier": "冲",
                        "position": 1,
                        "provinceName": "上海",
                    }
                ],
            },
            "profileState": {
                "explicitProfile": {
                    "negativeRegions": ["上海"],
                    "negativeSchools": ["上海大学"],
                    "negativeMajors": ["工商管理"],
                }
            },
            "reviewState": {"summary": {"riskCount": 0, "warnCount": 1}},
        },
    }

    with patch(
        "app.tools.plan_context_tool.get_planning_state",
        new=AsyncMock(return_value=response),
    ), patch(
        "app.tools.plan_context_tool.get_user_profile",
        new=AsyncMock(return_value={"code": 0, "data": {}}),
    ):
        result = asyncio.run(collect_plan_context_inputs(_ctx("ctx-2")))

    data = json.loads(result)
    assert data["negative_regions"] == ["上海"]
    assert data["negative_schools"] == ["上海大学"]
    assert data["negative_majors"] == ["工商管理"]
    assert "排除地域=上海" in data["summary"]
    assert "排除院校=上海大学" in data["summary"]


def test_collect_plan_context_inputs_matches_nested_major_group_after_intent_confirm():
    response = {
        "code": 0,
        "data": {
            "phase": "ordered",
            "candidatePoolState": {"requiredCount": 45},
            "draftPlanState": {"summary": {"unitTotal": 45}},
            "orderedPlanState": {
                "summary": {"unitTotal": 45, "targetUnitCount": 45},
                "items": [
                    {
                        "schoolName": "上海建桥学院(01)",
                        "provinceName": "上海",
                        "tier": "稳",
                        "position": 12,
                        "majorItems": [
                            {
                                "majorName": "网络与新媒体",
                                "majorCategory": "新闻传播学类",
                            }
                        ],
                    },
                    {
                        "schoolName": "上海大学(01)",
                        "provinceName": "上海",
                        "tier": "冲",
                        "position": 13,
                        "majorItems": [{"majorName": "护理学"}],
                    },
                ],
            },
            "profileState": {
                "explicitProfile": {
                    "positiveMajors": ["网络与新媒体"],
                    "negativeMajors": ["护理学"],
                }
            },
            "reviewState": {"summary": {"riskCount": 0, "warnCount": 0}},
        },
    }

    with patch(
        "app.tools.plan_context_tool.get_planning_state",
        new=AsyncMock(return_value=response),
    ), patch(
        "app.tools.plan_context_tool.get_user_profile",
        new=AsyncMock(return_value={"code": 0, "data": {}}),
    ):
        result = asyncio.run(collect_plan_context_inputs(_ctx("ctx-3")))

    data = json.loads(result)
    assert data["positive_majors"] == ["网络与新媒体"]
    assert data["negative_majors"] == ["护理学"]
    assert "当前方案里较贴近的有1个，明显冲突的有1个" in data["summary"]
    assert any("上海建桥学院(01)-网络与新媒体" in line for line in data["relation_lines"])
    assert any("上海大学(01)-护理学" in line for line in data["relation_lines"])


def test_collect_plan_context_inputs_aggregates_major_group_relation_counts_by_unit():
    response = {
        "code": 0,
        "data": {
            "phase": "reviewed",
            "candidatePoolState": {"requiredCount": 30},
            "draftPlanState": {"summary": {"total": 2}},
            "orderedPlanState": {
                "summary": {"total": 2, "targetUnitCount": 30},
                "items": [
                    {
                        "position": 1,
                        "volunteerId": "g1_m1",
                        "schoolName": "北京石油化工学院(03)",
                        "majorName": "计算机科学与技术(4600元)",
                        "tier": "冲",
                    },
                    {
                        "position": 2,
                        "volunteerId": "g1_m2",
                        "schoolName": "北京石油化工学院(03)",
                        "majorName": "软件工程(4600元)",
                        "tier": "冲",
                    },
                    {
                        "position": 3,
                        "volunteerId": "g2_m1",
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
            "reviewState": {"summary": {"riskCount": 0, "warnCount": 1}},
        },
    }

    with patch(
        "app.tools.plan_context_tool.get_planning_state",
        new=AsyncMock(return_value=response),
    ), patch(
        "app.tools.plan_context_tool.get_user_profile",
        new=AsyncMock(return_value={"code": 0, "data": {}}),
    ):
        result = asyncio.run(collect_plan_context_inputs(_ctx("ctx-3-major-group")))

    data = json.loads(result)
    assert "当前方案里较贴近的有2个，明显冲突的有0个" in data["summary"]
    assert any("北京石油化工学院(03)-计算机科学与技术(4600元)" in line for line in data["relation_lines"])
    assert any("湖北工程学院(01)-自动化(4000元)" in line for line in data["relation_lines"])
    assert not any("软件工程(4600元)" in line for line in data["relation_lines"])


def test_collect_plan_context_inputs_prefers_latest_user_profile_level3_over_stale_explicit_profile():
    planning_response = {
        "code": 0,
        "data": {
            "phase": "ordered",
            "candidatePoolState": {"requiredCount": 45},
            "draftPlanState": {"summary": {"unitTotal": 45}},
            "orderedPlanState": {
                "summary": {"unitTotal": 45, "targetUnitCount": 45},
                "items": [
                    {
                        "schoolName": "上海建桥学院(01)",
                        "provinceName": "上海",
                        "tier": "稳",
                        "position": 12,
                        "majorItems": [{"majorName": "网络与新媒体"}],
                    },
                    {
                        "schoolName": "上海商学院(02)",
                        "provinceName": "上海",
                        "tier": "稳",
                        "position": 13,
                        "majorItems": [{"majorName": "跨境电子商务"}],
                    },
                ],
            },
            "profileState": {
                "explicitProfile": {
                    "positiveMajors": ["哲学类", "金融学类"],
                    "positiveRegions": ["上海"],
                }
            },
            "reviewState": {"summary": {"riskCount": 0, "warnCount": 0}},
        },
    }
    profile_response = {
        "code": 0,
        "data": {
            "userprofile": {
                "major_intent": {
                    "level2": ["哲学类", "金融学类"],
                    "level3": ["网络与新媒体", "跨境电子商务"],
                },
                "city_info": {"province": ["上海"]},
            }
        },
    }

    with patch(
        "app.tools.plan_context_tool.get_planning_state",
        new=AsyncMock(return_value=planning_response),
    ), patch(
        "app.tools.plan_context_tool.get_user_profile",
        new=AsyncMock(return_value=profile_response),
    ):
        result = asyncio.run(collect_plan_context_inputs(_ctx("ctx-4")))

    data = json.loads(result)
    assert data["positive_majors"] == ["网络与新媒体", "跨境电子商务"]
    assert "偏好专业=网络与新媒体,跨境电子商务" in data["summary"]
    assert "当前方案里较贴近的有2个，明显冲突的有0个" in data["summary"]
