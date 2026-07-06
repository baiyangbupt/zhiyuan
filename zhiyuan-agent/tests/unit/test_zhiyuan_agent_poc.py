"""Release 4.0 Zhiyuan Agent PoC tests."""

from __future__ import annotations

import json
import os
import asyncio
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.test import TestModel

from app.agent.context import PlanningSummary, RequestContext
from app.llm.client import LLMClient
from app.models.conversation_phase import ConversationPhase, PendingConfirmation, PhaseState
from app.service import (
    ChatService,
    _direct_confirm_routing_path,
    _direct_confirm_workspace_refresh_targets,
    _observability_timing_fields,
)
from app.zhiyuan_agent.agent import ZhiyuanAgent
from app.zhiyuan_agent.prompt import build_turn_context, build_zhiyuan_agent_instructions
from app.zhiyuan_agent.tools import (
    _item_unit_id,
    answer_policy,
    compare_entities,
    confirm_pending,
    explore_topic,
    preview_intent_change,
    preview_plan_action,
    query_plan,
    read_state,
    review_plan,
)
from app.zhiyuan_agent.sandbox import (
    BackendAdapter,
    BackendReadResult,
    SandboxFileCache,
    _ordered_items_file_from_response,
    build_request_sandbox,
)
from tests.factories import make_request_context, make_run_context, make_user_profile


def _load(text: str) -> dict[str, Any]:
    return json.loads(text)


def test_item_unit_id_matches_backend_ordered_unit_id_from_nested_volunteer_id():
    item = {
        "schoolName": "泰山学院",
        "majorItems": [
            {"volunteerId": "37020261000734_37020262013962_37020262013962", "majorName": "数学与应用数学"}
        ],
    }

    assert _item_unit_id(item) == "37020261000734"


def test_ordered_items_enrichment_keeps_real_ordered_unit_id_for_execution():
    response = {
        "code": 0,
        "data": {
            "version": 264,
            "orderedPlanState": {
                "items": [
                    {
                        "position": 3,
                        "volunteerId": "37020261000734_37020262013962_37020262013962",
                        "schoolName": "泰山学院",
                    }
                ],
                "units": [
                    {
                        "position": 3,
                        "unitId": "37020261000734",
                        "planSchoolDataId": "37020261000734_37020262013962",
                        "schoolName": "泰山学院",
                    }
                ],
            },
            "candidatePoolState": {
                "items": [
                    {
                        "volunteerId": "37020261000734_37020262013962_37020262013962",
                        "unitId": "37020261000734_37020262013962",
                        "majorName": "数学与应用数学(师范类)",
                    }
                ]
            },
        },
    }

    items_file = _ordered_items_file_from_response(response)

    assert items_file["items"][0]["unitId"] == "37020261000734"
    assert items_file["items"][0]["planSchoolDataId"] == "37020261000734_37020262013962"
    assert items_file["items"][0]["majorName"] == "数学与应用数学(师范类)"


def test_direct_confirm_result_maps_to_pending_route_and_workspace_refresh():
    plan_result = {
        "data": {
            "action": "confirm",
            "kind": "plan_mutation",
            "action_family": "remove_units",
            "applied": True,
        }
    }
    intent_result = {
        "data": {
            "action": "confirm",
            "kind": "intent_change",
            "action_family": "apply_selected_intents",
            "applied": True,
            "result": {"has_plan": True, "plan_regenerated": True},
        }
    }

    assert _direct_confirm_routing_path(plan_result) == "direct_pending_plan_confirm"
    assert _direct_confirm_workspace_refresh_targets(plan_result) == ["ordered", "review"]
    assert _direct_confirm_routing_path(intent_result) == "direct_pending_intent_confirm"
    assert _direct_confirm_workspace_refresh_targets(intent_result) == ["ordered", "review"]


def _poc_context(*, with_plan: bool = True, pending: bool = False) -> RequestContext:
    ctx = make_request_context(
        planning_phase="ordered" if with_plan else "",
        planning_ordered_total=45 if with_plan else 0,
        planning_ordered_target_total=45 if with_plan else 0,
        planning_risk_count=2 if with_plan else 0,
        planning_warn_count=3 if with_plan else 0,
        init_profile=make_user_profile(
            major_level2=["计算机类"],
            provinces=["广东"],
        ),
    )
    if with_plan:
        ctx.planning_summary = PlanningSummary(
            phase="ordered",
            version=12,
            ordered_total=45,
            ordered_target_total=45,
            review_risk_count=2,
            review_warn_count=3,
            tier_counts={"冲": 12, "稳": 18, "保": 15},
            risk_summaries=["高收费风险：3个志愿年学费超2万"],
            sample_schools=["华南理工大学", "暨南大学"],
            positive_regions=["广东"],
            positive_majors=["计算机类"],
        )
    if pending:
        ctx.conversation_phase = ConversationPhase(
            state=PhaseState.PLAN_PREVIEWING,
            pending=PendingConfirmation(
                kind="plan_mutation",
                action_family="remove_units",
                preview_summary="移出3个高收费志愿",
                affected_scope="涉及第8、12、23位志愿",
            ),
        )
    ctx.sandbox = build_request_sandbox(
        session_id=ctx.sessionid,
        batch=ctx.batch,
        score_detail=ctx.score_detail,
        init_profile=ctx.init_profile,
        planning_summary=ctx.planning_summary,
        pending=getattr(ctx.conversation_phase, "pending", None),
    )
    if with_plan:
        ctx.sandbox.prime(
            "plan/items.json",
            {
                "available": True,
                "items": [
                    {
                        "unitId": "unit-hnlg",
                        "volunteerId": "unit-hnlg_001",
                        "schoolName": "华南理工大学",
                        "majorName": "计算机科学与技术",
                        "schoolNature": "公办",
                        "schoolCategory": "理工",
                        "schoolLevel": ["985", "211", "双一流"],
                        "schoolTags": ["985", "211", "双一流", "理工"],
                        "provinceName": "广东",
                        "tier": "冲",
                        "position": 1,
                        "tuitionPerYear": 6850,
                        "admissionRatio": 42,
                    },
                    {
                        "unitId": "unit-nanfang",
                        "volunteerId": "unit-nanfang_001",
                        "schoolName": "广州南方学院",
                        "majorName": "软件工程",
                        "schoolNature": "民办",
                        "schoolCategory": "综合",
                        "provinceName": "广东",
                        "tier": "稳",
                        "position": 18,
                        "tuitionPerYear": 29800,
                    },
                    {
                        "unitId": "unit-jnu",
                        "volunteerId": "unit-jnu_001",
                        "schoolName": "暨南大学",
                        "provinceName": "广东",
                        "tier": "保",
                        "position": 31,
                        "schoolNature": "公办",
                        "schoolCategory": "综合",
                        "schoolLevel": ["211", "双一流"],
                        "tuitionPerYear": 6850,
                        "majorItems": [
                            {"volunteerId": "unit-jnu_001", "majorName": "网络与新媒体", "majorCategory": "新闻传播学类"},
                            {"volunteerId": "unit-jnu_002", "majorName": "汉语言文学"},
                        ],
                    },
                    {
                        "unitId": "unit-guanggong",
                        "volunteerId": "unit-guanggong_001",
                        "schoolName": "广东工业大学",
                        "majorName": "自动化",
                        "schoolNature": "公办",
                        "schoolCategory": "理工",
                        "provinceName": "广东",
                        "tier": "保",
                        "position": 32,
                        "tuitionPerYear": 6850,
                        "admissionRatio": 82,
                    },
                ],
            },
            version=12,
        )
    return ctx


def test_zhiyuan_agent_disables_parallel_tool_calls():
    llm_client = SimpleNamespace(model=TestModel(), model_settings={"temperature": 0})
    agent = ZhiyuanAgent(llm_client)

    assert agent.agent.model_settings["parallel_tool_calls"] is False


def _context_with_backend_pending(pending_state: dict[str, Any], *, plan_version: int = 12) -> RequestContext:
    ctx = _poc_context(with_plan=True)
    ctx.planning_summary.version = plan_version
    ctx.sandbox.prime(
        "plan/summary.json",
        {
            "has_plan": True,
            "phase": "ordered",
            "version": plan_version,
            "ordered_total": 45,
            "ordered_target_total": 45,
            "tier_counts": {"冲": 12, "稳": 18, "保": 15},
            "review": {"risk_count": 2, "warn_count": 3},
        },
        version=plan_version,
    )
    ctx.sandbox.prime("pending.json", pending_state, version=plan_version)
    return ctx


class FakeSandboxAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        self.payloads: dict[str, list[BackendReadResult]] = {}

    def add(self, path: str, *results: BackendReadResult) -> None:
        self.payloads[path] = list(results)

    async def read(self, path: str, query: dict[str, Any] | None = None) -> BackendReadResult:
        self.calls.append((path, query))
        queue = self.payloads.get(path) or []
        if len(queue) > 1:
            return queue.pop(0)
        if queue:
            return queue[0]
        return BackendReadResult({"path": path}, 0)


def _tool_return(content: dict[str, Any], tool_name: str = "query_plan") -> ToolReturnPart:
    return ToolReturnPart(
        tool_name=tool_name,
        content=json.dumps(content, ensure_ascii=False),
        tool_call_id="call-1",
    )


def _tool_calls(messages: list[Any]) -> list[ToolCallPart]:
    calls: list[ToolCallPart] = []
    for message in messages:
        for part in getattr(message, "parts", []) or []:
            if isinstance(part, ToolCallPart):
                calls.append(part)
    return calls


def _tool_args(call: ToolCallPart) -> dict[str, Any]:
    if isinstance(call.args, dict):
        return call.args
    if isinstance(call.args, str) and call.args.strip():
        parsed = json.loads(call.args)
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _contains_text(value: Any, text: str) -> bool:
    return text in json.dumps(value, ensure_ascii=False)


def test_build_turn_context_injects_core_state():
    text = build_turn_context(_poc_context(with_plan=True, pending=True))

    assert "河北 550分 物理/化学/生物 男" in text
    assert "方案：45个志愿 (冲12/稳18/保15)" in text
    assert "风险：2项，提醒：3项" in text
    assert "待确认：remove_units" in text


def test_zhiyuan_agent_instructions_require_plan_action_targeting_for_review_followups():
    text = build_zhiyuan_agent_instructions(make_run_context(request_context=_poc_context(with_plan=True)))

    assert "不要只传 action" in text
    assert "review_issue_code=\"high_tuition\"" in text
    assert "那高收费的别要了" in text
    assert "那如果我不接受稿费呢高高学费" in text
    assert "raw_user_text" in text


async def test_sandbox_cache_hit_uses_adapter_once():
    adapter = FakeSandboxAdapter()
    adapter.add("score.json", BackendReadResult({"available": True, "total_score": 550}, 0))
    sandbox = SandboxFileCache("session-cache-hit", adapter)

    first = await sandbox.read("score.json")
    second = await sandbox.read("score")

    assert first == second == {"available": True, "total_score": 550}
    assert adapter.calls == [("score.json", None)]


async def test_sandbox_invalidate_forces_refetch():
    adapter = FakeSandboxAdapter()
    adapter.add(
        "score.json",
        BackendReadResult({"available": True, "total_score": 550}, 0),
        BackendReadResult({"available": True, "total_score": 560}, 0),
    )
    sandbox = SandboxFileCache("session-cache-invalidate", adapter)

    assert (await sandbox.read("score.json"))["total_score"] == 550
    sandbox.invalidate(["score"])
    assert (await sandbox.read("score.json"))["total_score"] == 560
    assert adapter.calls == [("score.json", None), ("score.json", None)]


async def test_sandbox_warm_prefetches_paths():
    adapter = FakeSandboxAdapter()
    adapter.add("score.json", BackendReadResult({"available": True}, 0))
    adapter.add("profile.json", BackendReadResult({"available": True}, 0))
    adapter.add("plan/summary.json", BackendReadResult({"has_plan": False}, 1))
    adapter.add("pending.json", BackendReadResult({"active": False}, 1))
    sandbox = SandboxFileCache("session-cache-warm", adapter)

    warmed = await sandbox.warm(["score", "profile", "plan/summary", "pending"])

    assert set(warmed) == {"score.json", "profile.json", "plan/summary.json", "pending.json"}
    assert [call[0] for call in adapter.calls] == [
        "score.json",
        "profile.json",
        "plan/summary.json",
        "pending.json",
    ]
    assert await sandbox.read("pending.json") == {"active": False}
    assert [call[0] for call in adapter.calls].count("pending.json") == 1


async def test_sandbox_planning_version_drift_invalidates_plan_cache():
    adapter = FakeSandboxAdapter()
    adapter.add(
        "plan/summary.json",
        BackendReadResult({"has_plan": True, "version": 1, "ordered_total": 30}, 1),
        BackendReadResult({"has_plan": True, "version": 2, "ordered_total": 45}, 2),
    )
    sandbox = SandboxFileCache("session-cache-version", adapter)

    assert (await sandbox.read("plan/summary.json"))["ordered_total"] == 30
    sandbox.update_latest_backend_version(2)
    assert (await sandbox.read("plan/summary.json"))["ordered_total"] == 45
    assert adapter.calls == [("plan/summary.json", None), ("plan/summary.json", None)]


async def test_backend_adapter_maps_eight_virtual_paths(mocker):
    planning_state = {
        "phase": "ordered",
        "version": 7,
        "constraintState": {"onlyKeep": {"schoolNature": ["公办"]}},
        "profileState": {"explicitProfile": {"positiveMajors": ["计算机类"]}},
        "candidatePoolState": {"requiredCount": 45},
        "orderedPlanState": {
            "summary": {"unitTotal": 45, "targetUnitCount": 45, "unitTierCounts": {"冲": 12}},
            "items": [{"schoolName": "华南理工大学"}],
        },
        "reviewState": {"summary": {"riskCount": 2, "warnCount": 3}, "checks": [{"summary": "高收费风险"}]},
    }
    mocker.patch(
        "app.zhiyuan_agent.sandbox.internal_client.get_user_score_detail",
        AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "userScoreDetail": {
                        "province": {"name": "河北"},
                        "totalScore": 550,
                        "subjectList": [{"name": "物理"}],
                        "sex": {"name": "男"},
                    },
                    "version": 1,
                },
            }
        ),
    )
    mocker.patch(
        "app.zhiyuan_agent.sandbox.internal_client.get_user_init_profile",
        AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "userInitProfile": {
                        "major_intent": {"level2": ["计算机类"]},
                        "city_info": {"province": ["广东"]},
                    },
                    "version": 1,
                },
            }
        ),
    )
    planning_state_mock = mocker.patch(
        "app.zhiyuan_agent.sandbox.internal_client.get_planning_state",
        AsyncMock(return_value={"code": 0, "data": planning_state}),
    )
    mocker.patch(
        "app.zhiyuan_agent.sandbox.internal_client.get_planning_workspace_state",
        AsyncMock(return_value={"code": 0, "data": planning_state}),
    )
    ordered_plan_mock = mocker.patch(
        "app.zhiyuan_agent.sandbox.internal_client.get_planning_ordered_plan",
        AsyncMock(
            return_value={
                "code": 0,
                "data": {"orderedPlanState": {"summary": {"unitTotal": 45}, "items": [{"schoolName": "暨南大学"}]}},
            }
        ),
    )
    mocker.patch(
        "app.zhiyuan_agent.sandbox.internal_client.query_planning_candidate_pool",
        AsyncMock(
            return_value={
                "code": 0,
                "data": {"candidatePoolState": {"summary": {"unitTotal": 2}, "items": [{"schoolName": "深圳大学"}]}},
            }
        ),
    )
    mocker.patch(
        "app.zhiyuan_agent.sandbox.internal_client.get_last_pending_confirmation",
        AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "dataVersion": 7,
                    "dataValue": {
                        "status": "active",
                        "kind": "plan_mutation",
                        "actionFamily": "remove_units",
                        "sourceBackendVersion": 7,
                    }
                },
            }
        ),
    )
    adapter = BackendAdapter("session-adapter")

    score = (await adapter.read("score.json")).data
    profile = (await adapter.read("profile.json")).data
    constraints = (await adapter.read("constraints.json")).data
    summary = (await adapter.read("plan/summary.json")).data
    items = (await adapter.read("plan/items.json")).data
    candidates = (await adapter.read("plan/candidates.json", query={"major_keywords": ["计算机"]})).data
    review = (await adapter.read("plan/review.json")).data
    pending = (await adapter.read("pending.json")).data

    assert score["province"] == "河北"
    assert profile["positive"]["majors"]["level2"] == ["计算机类"]
    assert constraints["constraints"] == {"onlyKeep": {"schoolNature": ["公办"]}}
    assert summary["ordered_total"] == 45
    assert items["items"] == [{"schoolName": "华南理工大学"}]
    assert candidates["items"] == [{"schoolName": "深圳大学"}]
    assert review["risk_count"] == 2
    assert pending["active"] is True
    assert pending["source_backend_version"] == 7
    assert pending["raw"]["_extraDataVersion"] == 7
    assert pending["action_family"] == "remove_units"
    assert planning_state_mock.await_count == 3
    ordered_plan_mock.assert_not_awaited()


async def test_backend_adapter_enriches_plan_items_from_candidate_pool(mocker):
    planning_state = {
        "version": 9,
        "orderedPlanState": {
            "summary": {"unitTotal": 2, "targetUnitCount": 2, "unitTierCounts": {"冲": 1, "稳": 1}},
            "items": [
                {
                    "position": 1,
                    "volunteerId": "school-1_major-1_major-1",
                    "tier": "冲",
                    "schoolName": "烟台大学",
                    "majorName": "材料科学与工程(中外合作办学)",
                },
                {
                    "position": 2,
                    "volunteerId": "school-2_major-2_major-2",
                    "tier": "稳",
                    "schoolName": "广州南方学院",
                    "majorName": "软件工程",
                },
            ],
        },
        "candidatePoolState": {
            "items": [
                {
                    "volunteerId": "school-1_major-1_major-1",
                    "schoolNature": "公办",
                    "schoolCategory": "综合",
                    "provinceName": "山东",
                    "tuitionPerYear": 40000,
                    "majorPlanTags": ["中外合作办学"],
                    "reasonCodes": ["高收费", "中外合作"],
                },
                {
                    "volunteerId": "school-2_major-2_major-2",
                    "schoolNature": "民办",
                    "schoolCategory": "综合",
                    "provinceName": "广东",
                    "tuitionPerYear": 29800,
                    "reasonCodes": ["民办", "学费：29800/年"],
                },
            ]
        },
    }
    planning_state_mock = mocker.patch(
        "app.zhiyuan_agent.sandbox.internal_client.get_planning_state",
        AsyncMock(return_value={"code": 0, "data": planning_state}),
    )
    ordered_mock = mocker.patch(
        "app.zhiyuan_agent.sandbox.internal_client.get_planning_ordered_plan",
        AsyncMock(return_value={"code": 0, "data": {}}),
    )
    adapter = BackendAdapter("session-enriched-plan")

    result = await adapter.read("plan/items.json")

    assert result.version == 9
    assert result.data["enriched"] is True
    assert result.data["items"][0]["schoolNature"] == "公办"
    assert result.data["items"][0]["tuitionPerYear"] == 40000
    assert result.data["items"][0]["reasonCodes"] == ["高收费", "中外合作"]
    assert result.data["items"][1]["schoolNature"] == "民办"
    planning_state_mock.assert_awaited_once_with("session-enriched-plan")
    ordered_mock.assert_not_awaited()


async def test_read_score():
    result = _load(await read_state(make_run_context(request_context=_poc_context()), "score"))

    assert result["next_step"] == "respond"
    assert result["data"]["province"] == "河北"
    assert result["data"]["total_score"] == 550
    assert "550分" in result["message"]


async def test_read_plan_summary_with_plan():
    result = _load(await read_state(make_run_context(request_context=_poc_context()), "plan/summary"))

    assert result["next_step"] == "respond"
    assert result["data"]["has_plan"] is True
    assert result["data"]["ordered_total"] == 45
    assert result["data"]["tier_counts"] == {"冲": 12, "稳": 18, "保": 15}


async def test_read_plan_summary_no_plan():
    result = _load(await read_state(make_run_context(request_context=_poc_context(with_plan=False)), "plan/summary"))

    assert result["next_step"] == "respond"
    assert result["data"]["has_plan"] is False
    assert "还没有生成正式方案" in result["message"]


async def test_explore_career_topic():
    result = _load(
        await explore_topic(
            make_run_context(request_context=_poc_context()),
            topic_type="career",
            user_question="建议考公吗",
        )
    )

    assert result["next_step"] == "respond"
    assert result["data"]["topic_type"] == "career"
    assert result["data"]["state_mutation"] is False
    assert "发展路径" in result["data"]["fallback_dimensions"][0]


async def test_explore_major_topic_uses_backend_profile(mocker):
    profile_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.get_major_category_profile",
        AsyncMock(
            return_value={
                "majorOverview": "计算机类覆盖软件、网络、人工智能等方向",
                "studyCourses": "程序设计、数据结构、计算机系统",
                "employmentDirection": "软件研发、算法、网络安全",
            }
        ),
    )
    result = _load(
        await explore_topic(
            make_run_context(request_context=_poc_context()),
            topic_type="major",
            user_question="计算机适合我吗",
        )
    )

    assert result["next_step"] == "respond"
    assert result["data"]["topic_type"] == "major"
    assert result["data"]["entity"] == "计算机类"
    assert result["data"]["profile_source"] == "backend_profile"
    assert {"label": "就业方向", "value": "软件研发、算法、网络安全"} in result["data"]["profile_facts"]
    profile_mock.assert_awaited_once_with(category_name="计算机类")
    assert "专业方向" in result["message"]


async def test_explore_school_topic_uses_backend_profile(mocker):
    profile_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.get_school_profile_by_name",
        AsyncMock(
            return_value={
                "schoolId": "10561",
                "authority": "教育部",
                "goatMajor": "轻工技术与工程、材料科学与工程",
                "gaotuRank": "全国前50",
            }
        ),
    )

    result = _load(
        await explore_topic(
            make_run_context(request_context=_poc_context()),
            topic_type="school",
            user_question="华南理工大学怎么样",
        )
    )

    assert result["next_step"] == "respond"
    assert result["data"]["topic_type"] == "school"
    assert result["data"]["entity"] == "华南理工大学"
    assert result["data"]["profile_source"] == "backend_profile"
    assert {"label": "排名", "value": "全国前50"} in result["data"]["profile_facts"]
    profile_mock.assert_awaited_once_with("华南理工大学")


async def test_explore_major_profile_failure_falls_back(mocker):
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.get_major_category_profile",
        AsyncMock(side_effect=RuntimeError("backend down")),
    )

    result = _load(
        await explore_topic(
            make_run_context(request_context=_poc_context()),
            topic_type="major",
            user_question="计算机适合我吗",
        )
    )

    assert result["next_step"] == "respond"
    assert result["data"]["profile_source"] == "profile_error"
    assert result["data"]["profile_facts"] == []
    assert result["data"]["fallback_dimensions"]
    assert "学什么" in result["data"]["fallback_dimensions"][0]


async def test_compare_major_entities_uses_profile_matrix(mocker):
    category_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.get_major_category_profile",
        AsyncMock(
            return_value={
                "majorOverview": "覆盖软件、网络、人工智能等方向",
                "studyCourses": "程序设计、数据结构",
                "employmentDirection": "软件研发、算法",
            }
        ),
    )
    major_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.get_major_profile",
        AsyncMock(
            return_value={
                "trainDemand": "培养软件工程实践能力",
                "course": "软件设计、项目管理",
                "jobOrientation": "软件开发、测试、架构",
            }
        ),
    )

    result = _load(
        await compare_entities(
            make_run_context(request_context=_poc_context()),
            entity_type="major",
            entities=["计算机类", "软件工程"],
            comparison_focus="就业",
        )
    )

    assert result["next_step"] == "respond"
    assert result["data"]["entity_type"] == "major"
    assert [row["name"] for row in result["data"]["rows"]] == ["计算机类", "软件工程"]
    assert result["data"]["rows"][0]["profile_source"] == "backend_profile"
    assert {"label": "就业方向", "value": "软件研发、算法"} in result["data"]["rows"][0]["facts"]
    assert result["data"]["rows"][1]["in_current_plan"] is True
    category_mock.assert_awaited_once_with(category_name="计算机类")
    major_mock.assert_awaited_once_with(major_name="软件工程")


async def test_compare_school_entities_marks_current_plan(mocker):
    school_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.get_school_profile_by_name",
        AsyncMock(
            side_effect=[
                {"schoolId": "10561", "authority": "教育部", "gaotuRank": "全国前50"},
                {"schoolId": "10559", "authority": "中央统战部", "gaotuRank": "全国前80"},
            ]
        ),
    )

    result = _load(
        await compare_entities(
            make_run_context(request_context=_poc_context()),
            entity_type="school",
            entities=["华南理工大学", "暨南大学"],
            comparison_focus="排名",
        )
    )

    assert result["next_step"] == "respond"
    assert result["data"]["entity_type"] == "school"
    assert [row["name"] for row in result["data"]["rows"]] == ["华南理工大学", "暨南大学"]
    assert all(row["in_current_plan"] for row in result["data"]["rows"])
    assert {"label": "排名/层次", "value": "全国前50"} in result["data"]["rows"][0]["facts"]
    assert school_mock.await_count == 2


async def test_compare_major_entities_returns_dimensions_template_when_profiles_missing(mocker):
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.get_major_category_profile",
        AsyncMock(return_value={}),
    )
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.get_major_profile",
        AsyncMock(return_value={}),
    )

    result = _load(
        await compare_entities(
            make_run_context(request_context=_poc_context()),
            entity_type="major",
            entities=["计算机类", "软件工程"],
            comparison_focus="就业",
        )
    )

    assert result["next_step"] == "respond"
    assert result["data"]["dimensions_template"]
    assert result["data"]["dimensions_template"][0]["fill_from"] == "llm_knowledge"
    assert all(row["facts"] == [] for row in result["data"]["rows"])


async def test_compare_entities_requires_two_entities():
    result = _load(
        await compare_entities(
            make_run_context(request_context=_poc_context()),
            entity_type="major",
            entities=["计算机类"],
        )
    )

    assert result["next_step"] == "clarify"
    assert "2到5个" in result["message"]


async def test_answer_policy_score_batch_is_readonly(mocker):
    availability_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.check_plan_param_availability",
        AsyncMock(return_value={"code": 0, "data": True}),
    )

    result = _load(
        await answer_policy(
            make_run_context(request_context=_poc_context()),
            question="分数和位次怎么参考",
            rule_domain="score_batch",
        )
    )

    assert result["next_step"] == "respond"
    assert result["data"]["rule_domain"] == "score_batch"
    assert result["data"]["state_mutation"] is False
    assert result["data"]["student_eligibility"]["score_context"]["province"] == "河北"
    assert result["data"]["student_eligibility"]["param_availability"]["checked"] is False
    assert "位次" in result["data"]["policy_facts"][0]["value"]
    assert "只读规则问题" in result["message"]
    availability_mock.assert_not_awaited()


async def test_answer_policy_school_rule_uses_school_profile(mocker):
    school_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.get_school_profile_by_name",
        AsyncMock(
            return_value={
                "schoolName": "北京工业大学",
                "recruitmentPolicy": "执行平行志愿投档，专业录取看分数优先。",
                "recruitmentPolicySourceTitle": "北京工业大学2025年本科招生章程",
                "recruitmentPolicySourceContent": "转专业按学校当年公布办法执行。",
            }
        ),
    )
    availability_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.check_plan_param_availability",
        AsyncMock(return_value={"code": 0, "data": False}),
    )

    result = _load(
        await answer_policy(
            make_run_context(request_context=_poc_context()),
            question="北京工业大学转专业难吗",
            rule_domain="transfer_major",
            school_name="北京工业大学",
            year=2025,
        )
    )

    assert result["next_step"] == "respond"
    assert result["data"]["school_name"] == "北京工业大学"
    assert result["data"]["school_profile_source"] == "backend_profile"
    assert result["data"]["student_eligibility"]["param_availability"]["available"] is False
    assert any(fact["label"] == "招生政策" for fact in result["data"]["policy_facts"])
    assert any(ref["type"] == "school_profile" for ref in result["data"]["source_references"])
    school_mock.assert_awaited_once_with("北京工业大学")
    availability_mock.assert_awaited_once()


async def test_answer_policy_subject_requirement_uses_major_and_school_targets(mocker):
    availability_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.check_plan_param_availability",
        AsyncMock(return_value={"code": 0, "data": True}),
    )
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.get_school_profile_by_name",
        AsyncMock(return_value={}),
    )

    result = _load(
        await answer_policy(
            make_run_context(request_context=_poc_context()),
            question="华南理工大学计算机科学与技术对选科有什么要求",
            rule_domain="subject_requirement",
            school_name="华南理工大学",
            major_name="计算机科学与技术",
        )
    )

    params = availability_mock.await_args.kwargs
    assert result["next_step"] == "respond"
    assert result["data"]["student_eligibility"]["missing_fields"] == []
    assert result["data"]["student_eligibility"]["param_availability"]["schools"] == ["华南理工大学"]
    assert result["data"]["student_eligibility"]["param_availability"]["majors"]["level3"] == ["计算机科学与技术"]
    assert params["schools"] and params["schools"] != ["华南理工大学"]
    assert params["majors"]["level3"]


async def test_answer_policy_can_include_official_search_result(mocker):
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.check_plan_param_availability",
        AsyncMock(return_value={"code": 0, "data": True}),
    )
    search_mock = mocker.patch(
        "app.tools.official_source_search_tool.search_official_admission_sources",
        AsyncMock(
            return_value=json.dumps(
                {
                    "status": "ok",
                    "results": [
                        {
                            "title": "河北省教育考试院投档规则",
                            "url": "https://example.edu/rule",
                            "snippet": "平行志愿按位次和志愿顺序投档。",
                        }
                    ],
                },
                ensure_ascii=False,
            )
        ),
    )

    result = _load(
        await answer_policy(
            make_run_context(request_context=_poc_context()),
            question="河北平行志愿怎么投档",
            rule_domain="enrollment_rules",
            use_official_search=True,
        )
    )

    assert result["next_step"] == "respond"
    assert result["data"]["source_lookup"]["status"] == "ok"
    assert any(ref["type"] == "official_search" for ref in result["data"]["source_references"])
    assert any(fact["label"] == "河北省教育考试院投档规则" for fact in result["data"]["policy_facts"])
    search_mock.assert_awaited_once()


def _context_with_review() -> RequestContext:
    ctx = _poc_context(with_plan=True)
    plan_file = ctx.sandbox.peek("plan/items.json")
    plan_file["items"].append(
        {
            "unitId": "unit-coop",
            "volunteerId": "unit-coop_001",
            "schoolName": "北京师范大学-香港浸会大学联合国际学院",
            "majorName": "统计学",
            "schoolNature": "中外合作",
            "schoolCategory": "师范",
            "programType": "中外合作",
            "provinceName": "广东",
            "tier": "稳",
            "position": 22,
            "tuitionPerYear": 100000,
            "majorPlanTags": ["中外合作办学"],
            "reasonCodes": ["cooperative_program"],
            "tags": ["中外合作办学"],
        }
    )
    plan_file["items"].append(
        {
            "unitId": "unit-limit",
            "volunteerId": "unit-limit_001",
            "schoolName": "南方医科大学",
            "majorName": "临床医学",
            "schoolNature": "公办",
            "schoolCategory": "医药",
            "provinceName": "广东",
            "tier": "稳",
            "position": 24,
            "tuitionPerYear": 7660,
            "reasonCodes": ["admission_limit"],
            "tags": ["限报条件"],
        }
    )
    ctx.sandbox.prime(
        "plan/review.json",
        {
            "available": True,
            "version": 12,
            "summary": {"riskCount": 2, "warnCount": 1, "passedCount": 8},
            "risk_count": 2,
            "warn_count": 1,
            "checks": [
                {
                    "code": "high_tuition",
                    "level": "risk",
                    "passed": False,
                    "summary": "3个志愿年学费超2万",
                    "affectedUnitIds": ["unit-nanfang"],
                    "suggestedAction": "建议结合预算考虑替换或下调位置",
                    "examples": [{"schoolName": "广州南方学院", "position": 18, "tier": "稳"}],
                },
                {
                    "code": "cooperative",
                    "level": "risk",
                    "passed": False,
                    "summary": "中外合作项目费用较高，涉及1个志愿",
                    "affectedItems": [
                        {
                            "unitId": "unit-coop",
                            "schoolName": "北京师范大学-香港浸会大学联合国际学院",
                            "majorName": "统计学",
                            "position": 22,
                            "tier": "稳",
                        }
                    ],
                    "suggestedAction": "如果预算一般，建议先移出或替换中外合作项目",
                },
                {
                    "code": "ratio_distribution",
                    "level": "warn",
                    "passed": False,
                    "summary": "冲区数量偏多，稳保承接不足",
                    "suggestedAction": "建议重新排序并补强稳保承接",
                },
                {
                    "code": "admission_limit",
                    "level": "risk",
                    "passed": False,
                    "summary": "限报条件涉及1个志愿",
                    "affectedVolunteerIds": ["unit-limit_001"],
                    "suggestedAction": "建议移出或替换受限志愿",
                },
                {
                    "code": "probability_inversion",
                    "level": "warn",
                    "passed": False,
                    "summary": "录取率倒挂，建议按概率重新排序",
                    "suggestedAction": "建议按录取概率重新排序",
                },
                {
                    "code": "safety_guard",
                    "level": "risk",
                    "passed": False,
                    "summary": "本省保底不足",
                    "suggestedAction": "建议补强保底志愿",
                },
                {
                    "code": "plan_update_notice",
                    "level": "info",
                    "passed": True,
                    "summary": "招生计划可能动态更新",
                },
            ],
        },
        version=12,
    )
    return ctx


async def test_review_plan_reads_sandbox_review_without_mutation(mocker):
    run_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.run_planning_review",
        AsyncMock(return_value={"code": 0, "data": {}}),
    )
    result = _load(
        await review_plan(
            make_run_context(request_context=_context_with_review()),
            focus="tuition",
            force_refresh=False,
        )
    )

    assert result["next_step"] == "respond"
    assert result["data"]["review_source"] == "sandbox"
    assert result["data"]["summary"]["risk_count"] == 2
    assert [issue["code"] for issue in result["data"]["issues"]] == ["high_tuition", "cooperative_program"]
    high_tuition_issue = next(issue for issue in result["data"]["issues"] if issue["code"] == "high_tuition")
    assert high_tuition_issue["examples"][0]["school"] == "广州南方学院"
    assert result["data"]["state_mutation"] is False
    assert result["data"]["plan_mutation"] is False
    assert "只读审查" in result["message"]
    run_mock.assert_not_awaited()


async def test_review_plan_force_refresh_primes_review_cache(mocker):
    run_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.run_planning_review",
        AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "summary": {"riskCount": 1, "warnCount": 0, "passedCount": 9},
                    "sourceVersion": 13,
                    "checks": [
                        {
                            "code": "probability_gap",
                            "level": "risk",
                            "passed": False,
                            "summary": "保底区间不够稳",
                        }
                    ],
                },
            }
        ),
    )
    ctx = _context_with_review()
    ctx.sandbox.prime("plan/candidates.json", {"available": True, "items": []}, version=12)

    result = _load(
        await review_plan(
            make_run_context(request_context=ctx),
            focus="risk_only",
            force_refresh=True,
        )
    )

    assert result["next_step"] == "respond"
    assert result["data"]["review_source"] == "run_planning_review"
    assert result["data"]["summary"]["risk_count"] == 1
    assert [issue["code"] for issue in result["data"]["issues"]] == ["probability_gap"]
    assert ctx.sandbox.peek("plan/review.json")["version"] == 13
    run_mock.assert_awaited_once_with(1, ctx.sessionid)


async def test_review_plan_no_issue_message_keeps_existing_plan_fact(mocker):
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.run_planning_review",
        AsyncMock(return_value={"code": 0, "data": {}}),
    )
    ctx = _poc_context(with_plan=True)
    ctx.sandbox.prime(
        "plan/review.json",
        {
            "available": True,
            "version": 12,
            "summary": {"riskCount": 0, "warnCount": 0, "passedCount": 8},
            "risk_count": 0,
            "warn_count": 0,
            "checks": [],
        },
        version=12,
    )

    result = _load(
        await review_plan(
            make_run_context(request_context=ctx),
            focus="tuition",
            force_refresh=False,
        )
    )

    assert result["next_step"] == "respond"
    assert result["data"]["has_plan"] is True
    assert result["data"]["ordered_total"] == 45
    assert "当前正式方案有45个志愿" in result["message"]
    assert "还没有生成具体志愿" not in result["message"]


async def test_review_plan_can_include_fix_proposals(mocker):
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.run_planning_review",
        AsyncMock(return_value={"code": 0, "data": {}}),
    )
    proposal_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.generate_planning_fix_proposals",
        AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "status": "ready",
                    "total": 1,
                    "proposals": [
                        {
                            "proposalId": "proposal-1",
                            "title": "替换高收费志愿",
                            "status": "ready",
                            "strategy": "replace",
                            "summary": "用预算更低的候选替换高收费项",
                            "sourceCheckCodes": ["high_tuition"],
                            "actions": [{"actionType": "replace_units", "summary": "替换1个志愿"}],
                        }
                    ],
                },
            }
        ),
    )
    ctx = _context_with_review()

    result = _load(
        await review_plan(
            make_run_context(request_context=ctx),
            generate_fix_proposals=True,
            force_refresh=False,
        )
    )

    assert result["next_step"] == "respond"
    assert result["data"]["fix_proposals"]["total"] == 1
    assert result["data"]["fix_proposals"]["proposals"][0]["proposal_id"] == "proposal-1"
    assert result["data"]["plan_mutation"] is False
    assert "确认前不会改动方案" in result["message"]
    proposal_mock.assert_awaited_once_with(1, ctx.sessionid)


async def test_review_plan_no_plan_is_readonly_guard(mocker):
    run_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.run_planning_review",
        AsyncMock(return_value={"code": 0, "data": {}}),
    )
    generate_initial_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.generate_planning_initial_plan",
        AsyncMock(return_value={"code": 0, "data": {}}),
    )
    generate_ordered_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.generate_planning_ordered_plan",
        AsyncMock(return_value={"code": 0, "data": {}}),
    )

    result = _load(await review_plan(make_run_context(request_context=_poc_context(with_plan=False))))

    assert result["next_step"] == "respond"
    assert result["data"]["has_plan"] is False
    assert result["data"]["state_mutation"] is False
    assert "还没有" in result["message"]
    run_mock.assert_not_awaited()
    generate_initial_mock.assert_not_awaited()
    generate_ordered_mock.assert_not_awaited()


async def test_preview_negative_major_level1(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.simulate_plan_diff",
        AsyncMock(return_value={"code": 500}),
    )
    result = _load(
        await preview_intent_change(
            make_run_context(request_context=_poc_context()),
            intent_type="major",
            negative={"level1": ["医学"]},
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["constraint_type"] == "exclude"
    assert result["data"]["normalized"]["negative"]["level1"] == ["医学"]
    assert result["data"]["normalized"]["positive"]["level1"] == []
    assert result["data"]["pending_created"] is True
    assert "确认前不会生效" in result["message"]
    assert "约束" not in result["message"]
    saved_state = save_mock.await_args.args[1]
    assert saved_state["executionPayload"]["intentMode"] == "constraint"
    assert saved_state["executionPayload"]["constraintIntentType"] == "exclude"


async def test_preview_positive_major_level2(mocker):
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.simulate_plan_diff",
        AsyncMock(return_value={"code": 500}),
    )
    result = _load(
        await preview_intent_change(
            make_run_context(request_context=_poc_context()),
            intent_type="major",
            positive={"level2": ["经济学类"]},
            constraint_type="must_have",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["constraint_type"] == "must_have"
    assert result["data"]["normalized"]["positive"]["level2"] == ["经济学类"]
    assert result["data"]["normalized"]["negative"]["level2"] == []
    assert result["data"]["pending_created"] is True


async def test_preview_intent_preserves_raw_display_alias_for_resolved_major(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.simulate_plan_diff",
        AsyncMock(return_value={"code": 500}),
    )

    result = _load(
        await preview_intent_change(
            make_run_context(request_context=_poc_context()),
            intent_type="major",
            negative={"level3": ["口腔"]},
            constraint_type="exclude",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["normalized"]["negative"]["level3"] == ["口腔医学"]
    assert "口腔（口腔医学）" in result["message"]
    saved_state = save_mock.await_args.args[1]
    assert "口腔（口腔医学）" in saved_state["summary"]
    assert saved_state["executionPayload"]["merged"]["_display_aliases"] == {"口腔医学": "口腔"}
    selected = saved_state["executionPayload"]["selectedData"]["selected"]
    assert selected == [{"major_intents": {"negative_level3": ["口腔医学"]}}]


async def test_preview_intent_merges_same_turn_positive_and_negative_pending(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.simulate_plan_diff",
        AsyncMock(return_value={"code": 500}),
    )
    ctx = _poc_context()

    first = _load(
        await preview_intent_change(
            make_run_context(request_context=ctx),
            intent_type="major",
            positive={"level2": ["生物医学工程", "智能医学工程"]},
            constraint_type="must_have",
        )
    )
    second = _load(
        await preview_intent_change(
            make_run_context(request_context=ctx),
            intent_type="major",
            negative={"level2": ["临床医学", "口腔医学"]},
            constraint_type="exclude",
        )
    )

    assert first["data"]["pending_created"] is True
    assert second["data"]["pending_created"] is True
    assert second["data"]["merged_existing_pending"] is True
    assert second["data"]["constraint_type"] == "must_have"
    assert save_mock.await_count == 2
    saved_state = save_mock.await_args.args[1]
    assert saved_state["summary"] == "专业要求：要：生物医学工程、智能医学工程；不要：临床医学、口腔医学"
    assert saved_state["executionPayload"]["constraintIntentType"] == "must_have"
    assert saved_state["executionPayload"]["merged"] == {
        "major_intents": {
            "level3": ["生物医学工程", "智能医学工程"],
            "negative_level3": ["临床医学", "口腔医学"],
        }
    }
    assert "生物医学工程" in second["message"]
    assert "临床医学" in second["message"]
    pending = ctx.sandbox.peek("pending.json")
    assert pending["raw"]["executionPayload"]["merged"] == saved_state["executionPayload"]["merged"]


async def test_preview_intent_mixed_positive_negative_normalizes_constraint_type(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.simulate_plan_diff",
        AsyncMock(return_value={"code": 500}),
    )

    result = _load(
        await preview_intent_change(
            make_run_context(request_context=_poc_context()),
            intent_type="major",
            positive={"level2": ["生物医学工程", "智能医学工程"]},
            negative={"level2": ["临床医学", "口腔医学"]},
            constraint_type="exclude",
        )
    )

    assert result["data"]["constraint_type"] == "must_have"
    saved_state = save_mock.await_args.args[1]
    assert saved_state["executionPayload"]["constraintIntentType"] == "must_have"


async def test_preview_intent_accepts_major_field_aliases(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.simulate_plan_diff",
        AsyncMock(return_value={"code": 500}),
    )

    result = _load(
        await preview_intent_change(
            make_run_context(request_context=_poc_context()),
            intent_type="major",
            positive={"major_name": ["生物医学工程", "智能医学工程"]},
            negative={"majorList": ["临床医学", "口腔"]},
            constraint_type="must_have",
            raw_user_text="把生物医学工程和智能医学工程加意向 排除临床医学和口腔",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["normalized"]["positive"]["level3"] == ["生物医学工程", "智能医学工程"]
    assert result["data"]["normalized"]["negative"]["level3"] == ["临床医学", "口腔医学"]
    assert result["data"]["parameter_warnings"] == []
    assert "口腔（口腔医学）" in result["message"]
    saved_state = save_mock.await_args.args[1]
    assert saved_state["executionPayload"]["merged"]["major_intents"] == {
        "level3": ["生物医学工程", "智能医学工程"],
        "negative_level3": ["临床医学", "口腔医学"],
    }


async def test_preview_intent_refines_broad_major_display_from_latest_user_text(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.simulate_plan_diff",
        AsyncMock(return_value={"code": 500}),
    )
    ctx = _poc_context()
    ctx.chat_history = [{"role": "user", "content": "会计学和审计学要，土木工程不要"}]

    result = _load(
        await preview_intent_change(
            make_run_context(request_context=ctx),
            intent_type="major",
            positive={"level2": ["工商管理类"], "major": ["会计学", "审计学"]},
            negative={"level2": ["土木类"]},
            constraint_type="must_have",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["normalized"]["positive"]["level2"] == []
    assert result["data"]["normalized"]["positive"]["level3"] == ["会计学", "审计学"]
    assert result["data"]["normalized"]["negative"]["level2"] == []
    assert result["data"]["normalized"]["negative"]["level3"] == ["土木工程"]
    assert "工商管理类" not in result["message"]
    assert "土木类" not in result["message"]
    assert "要：会计学、审计学" in result["message"]
    assert "不要：土木工程" in result["message"]
    saved_state = save_mock.await_args.args[1]
    assert saved_state["summary"] == "专业要求：要：会计学、审计学；不要：土木工程"
    assert saved_state["executionPayload"]["merged"]["major_intents"] == {
        "level3": ["会计学", "审计学"],
        "negative_level3": ["土木工程"],
    }


async def test_preview_intent_keeps_broad_major_scope_when_user_says_related(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.simulate_plan_diff",
        AsyncMock(return_value={"code": 500}),
    )
    ctx = _poc_context()
    ctx.chat_history = [{"role": "user", "content": "不要英语相关专业，当前方案里有的话也删掉"}]

    result = _load(
        await preview_intent_change(
            make_run_context(request_context=ctx),
            intent_type="major",
            negative={"level2": ["外国语言文学类"]},
            constraint_type="exclude",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["normalized"]["negative"]["level2"] == ["外国语言文学类"]
    assert result["data"]["normalized"]["negative"]["level3"] == []
    assert "不要：外国语言文学类" in result["message"]
    assert "不要：英语" not in result["message"]
    saved_state = save_mock.await_args.args[1]
    assert saved_state["summary"] == "专业要求：不要：外国语言文学类"
    assert saved_state["executionPayload"]["merged"]["major_intents"] == {
        "negative_level2": ["外国语言文学类"]
    }


async def test_preview_intent_warns_when_negative_text_missing_negative_payload(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.simulate_plan_diff",
        AsyncMock(return_value={"code": 500}),
    )

    result = _load(
        await preview_intent_change(
            make_run_context(request_context=_poc_context()),
            intent_type="major",
            positive={"majorList": ["生物医学工程", "智能医学工程"]},
            constraint_type="must_have",
            raw_user_text="把生物医学工程和智能医学工程加意向 排除临床医学和口腔",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["normalized"]["positive"]["level3"] == ["生物医学工程", "智能医学工程"]
    assert result["data"]["normalized"]["negative"]["level3"] == []
    assert result["data"]["parameter_warnings"] == ["negative_may_be_missing"]
    assert "预览里没有不要项" in result["message"]
    saved_state = save_mock.await_args.args[1]
    assert saved_state["executionPayload"]["merged"]["major_intents"] == {
        "level3": ["生物医学工程", "智能医学工程"]
    }


async def test_preview_intent_creates_structured_pending_payload(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.simulate_plan_diff",
        AsyncMock(return_value={"code": 500}),
    )
    ctx = _poc_context()

    result = _load(
        await preview_intent_change(
            make_run_context(request_context=ctx),
            intent_type="major",
            negative={"level1": ["医学"]},
            constraint_type="exclude",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["pending_created"] is True
    assert result["data"]["plan_impact"]["source"] == "local_plan_items"
    saved_state = save_mock.await_args.args[1]
    assert saved_state["kind"] == "intent_change"
    assert saved_state["actionFamily"] == "apply_selected_intents"
    assert saved_state["executionPayload"]["merged"] == {
        "major_intents": {"negative_level1": ["医学"]}
    }
    assert saved_state["executionPayload"]["intentMode"] == "constraint"
    assert saved_state["executionPayload"]["constraintIntentType"] == "exclude"
    pending = ctx.sandbox.peek("pending.json")
    assert pending["active"] is True
    assert pending["pending_id"] == result["data"]["pending_id"]


async def test_preview_intent_dry_run_does_not_save_pending(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.simulate_plan_diff",
        AsyncMock(return_value={"code": 500}),
    )
    ctx = _poc_context()
    ctx.dry_run_state_mutations = True

    result = _load(
        await preview_intent_change(
            make_run_context(request_context=ctx),
            intent_type="major",
            negative={"level1": ["医学"]},
            constraint_type="exclude",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["pending_created"] is True
    assert ctx.sandbox.peek("pending.json")["dry_run"] is True
    save_mock.assert_not_awaited()


async def test_preview_intent_uses_simulate_plan_diff(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    simulate_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.simulate_plan_diff",
        AsyncMock(
            return_value={
                "before": {"sprintCount": 12, "safeCount": 18, "protectCount": 15, "totalCount": 45},
                "after": {"sprintCount": 11, "safeCount": 17, "protectCount": 14, "totalCount": 42},
                "promoted": [{"schoolId": "s1", "schoolName": "深圳大学", "tier": "safe"}],
                "demoted": [{"schoolId": "s2", "schoolName": "广东医科大学", "tier": "sprint"}],
            }
        ),
    )
    ctx = _poc_context()

    result = _load(
        await preview_intent_change(
            make_run_context(request_context=ctx),
            intent_type="major",
            negative={"level1": ["医学"]},
            constraint_type="exclude",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["plan_impact"]["source"] == "simulate_plan_diff"
    assert result["data"]["plan_impact"]["affected_count"] == 2
    assert result["data"]["plan_impact"]["tier_impact"] == {"冲": -1, "稳": -1, "保": -1}
    assert result["data"]["plan_impact"]["demoted"][0]["school"] == "广东医科大学"
    simulate_mock.assert_awaited_once()
    tenant_id, session_id, proposed_profile = simulate_mock.await_args.args
    assert tenant_id == 1
    assert session_id == ctx.sessionid
    assert proposed_profile["major_intent"]["level2"] == ["计算机类"]
    assert proposed_profile["negative_major_intent"]["level1"] == ["医学"]
    saved_state = save_mock.await_args.args[1]
    assert saved_state["planImpact"]["source"] == "simulate_plan_diff"


async def test_preview_intent_reports_pending_save_failure(mocker):
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 500, "msg": "failed"}),
    )
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.simulate_plan_diff",
        AsyncMock(return_value={"code": 500}),
    )

    result = _load(
        await preview_intent_change(
            make_run_context(request_context=_poc_context()),
            intent_type="major",
            positive={"level2": ["经济学类"]},
            constraint_type="must_have",
        )
    )

    assert result["next_step"] == "respond"
    assert result["data"]["pending_created"] is False
    assert result["data"]["requires_confirmation"] is False
    assert "没有保存成功" in result["message"]


async def test_preview_ambiguous_major_clarifies():
    result = _load(
        await preview_intent_change(
            make_run_context(request_context=_poc_context()),
            intent_type="major",
            positive={"level2": ["计算机"]},
        )
    )

    assert result["next_step"] == "clarify"
    names = [item["name"] for item in result["data"]["ambiguities"][0]["candidates"]]
    assert "计算机类" in names
    assert "计算机科学与技术" in names


async def test_preview_region_normalizes_alias(mocker):
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.simulate_plan_diff",
        AsyncMock(return_value={"code": 500}),
    )
    result = _load(
        await preview_intent_change(
            make_run_context(request_context=_poc_context()),
            intent_type="region",
            positive={"province": ["内蒙"]},
            constraint_type="only_keep",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["constraint_type"] == "only_keep"
    assert result["data"]["normalized"]["positive"]["province"] == ["内蒙古"]


async def test_preview_school_nature_constraint_is_structured_and_hard(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.simulate_plan_diff",
        AsyncMock(return_value={"code": 500}),
    )

    result = _load(
        await preview_intent_change(
            make_run_context(request_context=_poc_context()),
            intent_type="school",
            negative={"school_nature": ["私立学校"]},
            constraint_type="exclude",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["normalized"]["negative"]["school_nature"] == ["民办"]
    assert result["data"]["plan_impact"]["affected_count"] == 1
    assert "重新调整方案" in result["message"]
    assert "约束" not in result["message"]
    saved_state = save_mock.await_args.args[1]
    assert saved_state["executionPayload"]["merged"] == {
        "school_intents": {"negative_school_nature": ["民办"]}
    }
    assert saved_state["executionPayload"]["intentMode"] == "constraint"
    assert saved_state["executionPayload"]["constraintIntentType"] == "exclude"


async def test_preview_school_values_detect_attribute_for_only_keep(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.simulate_plan_diff",
        AsyncMock(return_value={"code": 500}),
    )

    result = _load(
        await preview_intent_change(
            make_run_context(request_context=_poc_context()),
            intent_type="school",
            positive={"values": ["公立学校"]},
            constraint_type="only_keep",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["normalized"]["positive"]["school_nature"] == ["公办"]
    assert result["data"]["normalized"]["positive"]["schools"] == []
    assert result["data"]["plan_impact"]["affected_count"] == 1
    saved_state = save_mock.await_args.args[1]
    assert saved_state["executionPayload"]["merged"] == {
        "school_intents": {"school_nature": ["公办"]}
    }


async def test_preview_strongbase_school_intent_preserves_program_type(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.simulate_plan_diff",
        AsyncMock(return_value={"code": 500}),
    )

    result = _load(
        await preview_intent_change(
            make_run_context(request_context=_poc_context()),
            intent_type="school",
            positive={"schools": ["清华大学", "北京大学", "复旦大学"], "program_type": ["强基计划"]},
            constraint_type="must_have",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["normalized"]["positive"]["program_type"] == ["强基"]
    assert result["data"]["normalized"]["positive"]["schools"] == ["清华大学", "北京大学", "复旦大学"]
    saved_state = save_mock.await_args.args[1]
    assert saved_state["executionPayload"]["merged"] == {
        "school_intents": {
            "colleges": ["清华大学", "北京大学", "复旦大学"],
            "program_type": ["强基"],
        }
    }


async def test_confirm_pending_applies_school_attribute_constraint(mocker):
    update_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.update_planning_constraint_state",
        AsyncMock(return_value={"code": 0}),
    )
    ordered_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.generate_planning_ordered_plan",
        AsyncMock(return_value={"code": 0}),
    )
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _context_with_backend_pending(
        {
            "active": True,
            "pending_id": "pending-school-attr",
            "kind": "intent_change",
            "action_family": "apply_selected_intents",
            "summary": "排除民办",
            "source_backend_version": 12,
            "execution_payload": {
                "merged": {"school_intents": {"negative_school_nature": ["民办"]}},
                "intentMode": "constraint",
                "constraintIntentType": "exclude",
            },
            "raw": {
                "pendingId": "pending-school-attr",
                "kind": "intent_change",
                "actionFamily": "apply_selected_intents",
                "status": "active",
                "sourceBackendVersion": 12,
            },
        }
    )

    result = _load(await confirm_pending(make_run_context(request_context=ctx), action="confirm"))

    assert result["data"]["applied"] is True
    assert result["data"]["result"]["has_plan"] is True
    assert result["data"]["result"]["plan_regenerated"] is True
    assert "重新调整" in result["message"]
    assert "约束" not in result["message"]
    update_mock.assert_awaited_once_with(
        ctx.sessionid,
        intent_mode="constraint",
        major_preferences=None,
        school_preferences={"positive": [], "negative": ["院校性质:民办"]},
        region_preferences=None,
    )
    ordered_mock.assert_awaited_once_with(1, ctx.sessionid)


async def test_confirm_pending_applies_strongbase_program_type_constraint(mocker):
    update_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.update_planning_constraint_state",
        AsyncMock(return_value={"code": 0}),
    )
    ordered_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.generate_planning_ordered_plan",
        AsyncMock(return_value={"code": 0}),
    )
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _context_with_backend_pending(
        {
            "active": True,
            "pending_id": "pending-strongbase",
            "kind": "intent_change",
            "action_family": "apply_selected_intents",
            "summary": "强基意向",
            "source_backend_version": 12,
            "execution_payload": {
                "merged": {
                    "school_intents": {
                        "colleges": ["清华大学", "北京大学", "复旦大学"],
                        "program_type": ["强基"],
                    }
                },
                "intentMode": "constraint",
                "constraintIntentType": "must_have",
            },
            "raw": {
                "pendingId": "pending-strongbase",
                "kind": "intent_change",
                "actionFamily": "apply_selected_intents",
                "status": "active",
                "sourceBackendVersion": 12,
            },
        }
    )

    result = _load(await confirm_pending(make_run_context(request_context=ctx), action="confirm"))

    assert result["data"]["applied"] is True
    assert result["data"]["result"]["has_plan"] is True
    assert result["data"]["result"]["plan_regenerated"] is True
    update_mock.assert_awaited_once_with(
        ctx.sessionid,
        intent_mode="constraint",
        major_preferences=None,
        school_preferences={
            "positive": ["清华大学", "北京大学", "复旦大学", "招生类型:强基"],
            "negative": [],
        },
        region_preferences=None,
    )
    ordered_mock.assert_awaited_once_with(1, ctx.sessionid)


async def test_preview_plan_action_creates_remove_pending(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _poc_context()

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="remove",
            targets=["广州南方学院"],
            raw_user_text="把广州南方学院移出去",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["action_family"] == "remove_units"
    assert result["data"]["execution_payload"]["unit_ids"] == ["unit-nanfang"]
    assert "planPayload" not in result["data"]["execution_payload"]
    saved_state = save_mock.await_args.args[1]
    assert saved_state["kind"] == "plan_mutation"
    assert saved_state["actionFamily"] == "remove_units"
    assert saved_state["executionPayload"]["atomic_actions"][0]["unit_ids"] == ["unit-nanfang"]
    pending = ctx.sandbox.peek("pending.json")
    assert pending["active"] is True
    assert pending["action_family"] == "remove_units"


async def test_preview_plan_action_dry_run_does_not_save_pending(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _poc_context()
    ctx.dry_run_state_mutations = True

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="remove",
            filters={"school_nature": ["民办"]},
            raw_user_text="方案里的民办不要了",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["pending_created"] is True
    assert result["data"]["execution_payload"]["unit_ids"] == ["unit-nanfang"]
    assert ctx.sandbox.peek("pending.json")["dry_run"] is True
    save_mock.assert_not_awaited()


async def test_preview_plan_action_remove_uses_school_nature_filter(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _poc_context()

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="remove",
            filters={"school_nature": ["民办"]},
            raw_user_text="排除民办学校",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["action_family"] == "remove_units"
    assert result["data"]["execution_payload"]["unit_ids"] == ["unit-nanfang"]
    assert result["data"]["execution_payload"]["filters"] == {"school_nature": ["民办"]}
    assert "院校性质=民办" in result["message"]
    saved_state = save_mock.await_args.args[1]
    atomic = saved_state["executionPayload"]["atomic_actions"][0]
    assert atomic["unit_ids"] == ["unit-nanfang"]
    assert atomic["filters"] == {"school_nature": ["民办"]}
    assert "planPayload" not in saved_state["executionPayload"]


async def test_preview_plan_action_remove_uses_program_type_filter(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _context_with_review()

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="remove",
            filters={"program_type": ["中外合作办学"]},
            raw_user_text="排除中外合作",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["execution_payload"]["unit_ids"] == ["unit-coop"]
    assert result["data"]["execution_payload"]["filters"] == {"program_type": ["中外合作"]}
    assert "招生类型=中外合作" in result["message"]
    saved_state = save_mock.await_args.args[1]
    atomic = saved_state["executionPayload"]["atomic_actions"][0]
    assert atomic["unit_ids"] == ["unit-coop"]
    assert atomic["filters"] == {"program_type": ["中外合作"]}


async def test_preview_plan_action_remove_normalizes_high_tuition_level_filter(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _poc_context()

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="remove",
            filters={"tuition_level": "high"},
            raw_user_text="那高收费的别要了",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["execution_payload"]["unit_ids"] == ["unit-nanfang"]
    assert result["data"]["execution_payload"]["filters"] == {"program_type": ["高收费"]}
    assert "广州南方学院" in result["message"]
    saved_state = save_mock.await_args.args[1]
    atomic = saved_state["executionPayload"]["atomic_actions"][0]
    assert atomic["unit_ids"] == ["unit-nanfang"]
    assert atomic["filters"] == {"program_type": ["高收费"]}


async def test_preview_plan_action_remove_unknown_filter_does_not_match_all(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _poc_context()

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="remove",
            filters={"unknown_filter": "anything"},
            raw_user_text="把这类移出去",
        )
    )

    assert result["next_step"] == "respond"
    assert result["data"]["reason"] == "filter_no_match"
    save_mock.assert_not_awaited()


async def test_preview_plan_action_remove_program_type_matches_major_name(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _poc_context()
    ctx.sandbox.prime(
        "plan/items.json",
        {
            "available": True,
            "items": [
                {
                    "unitId": "unit-coop-major-name",
                    "volunteerId": "unit-coop-major-name_001",
                    "schoolName": "烟台大学",
                    "majorName": "材料科学与工程(中外合作办学)",
                    "schoolNature": "公办",
                    "tier": "冲",
                    "position": 1,
                    "tuitionPerYear": 40000,
                }
            ],
        },
        version=12,
    )

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="remove",
            filters={"program_type": ["中外合作"]},
            raw_user_text="方案里的中外合作不要了",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["plan_impact"]["affected_count"] == 1
    assert result["data"]["execution_payload"]["unit_ids"] == ["unit-coop-major-name"]
    save_mock.assert_awaited_once()


async def test_preview_plan_action_remove_uses_school_category_filter(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _poc_context()

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="remove",
            filters={"school_category": ["理工类"]},
            raw_user_text="排除理工类院校",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["execution_payload"]["unit_ids"] == ["unit-hnlg", "unit-guanggong"]
    assert result["data"]["execution_payload"]["filters"] == {"school_category": ["理工"]}
    assert "院校类型=理工" in result["message"]
    saved_state = save_mock.await_args.args[1]
    assert saved_state["executionPayload"]["atomic_actions"][0]["unit_ids"] == ["unit-hnlg", "unit-guanggong"]


async def test_preview_plan_action_remove_uses_school_level_filter(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _poc_context()

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="remove",
            filters={"school_level": ["985学校"]},
            raw_user_text="排除985学校",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["execution_payload"]["unit_ids"] == ["unit-hnlg"]
    assert result["data"]["execution_payload"]["filters"] == {"school_level": ["985"]}
    assert "院校层次=985" in result["message"]
    saved_state = save_mock.await_args.args[1]
    assert saved_state["executionPayload"]["atomic_actions"][0]["unit_ids"] == ["unit-hnlg"]


async def test_preview_plan_action_remove_filter_no_match_does_not_create_pending(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=_poc_context()),
            action="remove",
            filters={"school_category": ["医药"]},
            raw_user_text="排除医药类院校",
        )
    )

    assert result["next_step"] == "respond"
    assert result["data"]["reason"] == "filter_no_match"
    assert result["data"]["filters"] == {"school_category": ["医药"]}
    assert "不需要移出" in result["message"]
    save_mock.assert_not_awaited()


async def test_preview_plan_action_remove_uses_review_issue_scope(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _context_with_review()

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="remove",
            review_issue_code="high_tuition",
            raw_user_text="把审查里的高收费项移出去",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["review_issue_code"] == "high_tuition"
    assert result["data"]["review_issue_target"]["code"] == "high_tuition"
    assert result["data"]["execution_payload"]["unit_ids"] == ["unit-nanfang"]
    assert result["data"]["execution_payload"]["review_issue_target"]["summary"] == "3个志愿年学费超2万"
    saved_state = save_mock.await_args.args[1]
    assert saved_state["executionPayload"]["atomic_actions"][0]["review_issue_target"]["code"] == "high_tuition"
    assert "planPayload" not in saved_state["executionPayload"]


async def test_preview_plan_action_remove_intersects_review_issue_with_filters(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _context_with_review()

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="remove",
            review_issue_code="high_tuition",
            filters={"school_nature": ["民办"]},
            raw_user_text="把审查里的高收费且民办的项移出去",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["execution_payload"]["unit_ids"] == ["unit-nanfang"]
    assert result["data"]["execution_payload"]["filters"]["school_nature"] == ["民办"]
    saved_state = save_mock.await_args.args[1]
    atomic = saved_state["executionPayload"]["atomic_actions"][0]
    assert atomic["unit_ids"] == ["unit-nanfang"]
    assert atomic["filters"]["school_nature"] == ["民办"]
    assert "planPayload" not in saved_state["executionPayload"]


async def test_preview_plan_action_remove_review_issue_filter_no_match_does_not_create_pending(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _context_with_review()

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="remove",
            review_issue_code="high_tuition",
            filters={"school_nature": ["公办"]},
            raw_user_text="把审查里的高收费且公办的项移出去",
        )
    )

    assert result["next_step"] == "respond"
    assert result["data"]["reason"] == "filter_no_match"
    assert result["data"]["review_issue_code"] == "high_tuition"
    assert "不需要移出" in result["message"]
    save_mock.assert_not_awaited()


async def test_preview_plan_action_remove_uses_cooperative_review_issue_alias(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _context_with_review()

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="remove",
            review_issue_code="cooperative_program",
            raw_user_text="把审查里的中外合作项先移出去",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["review_issue_code"] == "cooperative_program"
    assert result["data"]["review_issue_target"]["code"] == "cooperative_program"
    assert result["data"]["review_issue_target"]["source_code"] == "cooperative"
    assert result["data"]["execution_payload"]["unit_ids"] == ["unit-coop"]
    saved_state = save_mock.await_args.args[1]
    atomic = saved_state["executionPayload"]["atomic_actions"][0]
    assert atomic["unit_ids"] == ["unit-coop"]
    assert atomic["review_issue_target"]["code"] == "cooperative_program"
    assert "planPayload" not in saved_state["executionPayload"]


async def test_preview_plan_action_review_issue_can_resolve_affected_volunteer_ids(mocker):
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _context_with_review()
    review = ctx.sandbox.peek("plan/review.json")
    high_tuition = review["checks"][0]
    high_tuition.pop("affectedUnitIds")
    high_tuition["affectedVolunteerIds"] = ["unit-nanfang_001"]

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="remove",
            review_issue_code="high_tuition",
            raw_user_text="把审查里的高收费项移出去",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["execution_payload"]["unit_ids"] == ["unit-nanfang"]


async def test_preview_plan_action_remove_supports_admission_limit_review_issue(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _context_with_review()

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="remove",
            review_issue_code="admission_limit",
            raw_user_text="把审查里的限报项移出去",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["review_issue_target"]["code"] == "admission_limit"
    assert result["data"]["execution_payload"]["unit_ids"] == ["unit-limit"]
    saved_state = save_mock.await_args.args[1]
    assert saved_state["executionPayload"]["atomic_actions"][0]["review_issue_target"]["code"] == "admission_limit"
    assert "planPayload" not in saved_state["executionPayload"]


async def test_preview_plan_action_review_issue_requires_units(mocker):
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _context_with_review()
    review = ctx.sandbox.peek("plan/review.json")
    review["checks"][0].pop("affectedUnitIds")

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="remove",
            review_issue_code="high_tuition",
            raw_user_text="把审查里的高收费项移出去",
        )
    )

    assert result["next_step"] == "clarify"
    assert result["data"]["reason"] == "review_issue_without_units"
    assert "唯一定位" in result["message"]


async def test_preview_plan_action_replace_review_issue_requires_candidate_when_pool_empty(mocker):
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _context_with_review()

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="replace",
            review_issue_code="high_tuition",
            raw_user_text="替换审查里的高收费项",
        )
    )

    assert result["next_step"] == "clarify"
    assert result["data"]["review_issue_code"] == "high_tuition"
    assert result["data"]["reason"] == "candidate_items_unavailable"
    assert "候选志愿" in result["message"]


async def test_preview_plan_action_replace_review_issue_rejects_unsafe_auto_candidates(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _context_with_review()
    ctx.sandbox.prime(
        "plan/candidates.json",
        {
            "available": True,
            "items": [
                {
                    "volunteerId": "unit-nanfang_999",
                    "schoolName": "广州南方学院",
                    "majorName": "软件工程",
                    "tier": "稳",
                    "provinceName": "广东",
                    "schoolNature": "民办",
                    "tuitionPerYear": 12000,
                    "admissionRatio": 90,
                },
                {
                    "volunteerId": "cand-high-001",
                    "schoolName": "广东以色列理工学院",
                    "majorName": "材料科学与工程",
                    "tier": "稳",
                    "provinceName": "广东",
                    "programType": "中外合作",
                    "tuitionPerYear": 95000,
                    "admissionRatio": 88,
                },
            ],
        },
        version=12,
    )

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="replace",
            review_issue_code="high_tuition",
            raw_user_text="替换审查里的高收费项",
        )
    )

    assert result["next_step"] == "clarify"
    assert result["data"]["reason"] == "candidate_no_match"
    save_mock.assert_not_awaited()


async def test_preview_plan_action_replace_review_issue_auto_selects_candidate(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _context_with_review()
    ctx.sandbox.prime(
        "plan/candidates.json",
        {
            "available": True,
            "items": [
                {
                    "volunteerId": "cand-szu-001",
                    "schoolName": "深圳大学",
                    "majorName": "软件工程",
                    "tier": "稳",
                    "provinceName": "广东",
                    "schoolNature": "公办",
                    "tuitionPerYear": 6850,
                    "admissionRatio": 76,
                },
                {
                    "volunteerId": "cand-coop-001",
                    "schoolName": "广东以色列理工学院",
                    "majorName": "材料科学与工程",
                    "tier": "稳",
                    "provinceName": "广东",
                    "programType": "中外合作",
                    "tuitionPerYear": 95000,
                    "admissionRatio": 88,
                },
            ],
        },
        version=12,
    )

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="replace",
            review_issue_code="high_tuition",
            raw_user_text="替换审查里的高收费项",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["action_family"] == "replace_units"
    assert result["data"]["execution_payload"]["unit_ids"] == ["unit-nanfang"]
    assert result["data"]["execution_payload"]["volunteer_ids"] == ["cand-szu-001"]
    assert result["data"]["execution_payload"]["filters"]["auto_selected_candidates"] is True
    saved_state = save_mock.await_args.args[1]
    atomic = saved_state["executionPayload"]["atomic_actions"][0]
    assert atomic["unit_ids"] == ["unit-nanfang"]
    assert atomic["volunteer_ids"] == ["cand-szu-001"]
    assert "planPayload" not in saved_state["executionPayload"]


async def test_preview_plan_action_replace_filters_auto_selects_low_tuition_candidates(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _context_with_review()
    ctx.sandbox.prime(
        "plan/candidates.json",
        {
            "available": True,
            "items": [
                {
                    "volunteerId": "cand-szu-001",
                    "schoolName": "深圳大学",
                    "majorName": "软件工程",
                    "tier": "稳",
                    "provinceName": "广东",
                    "schoolNature": "公办",
                    "tuitionPerYear": 6850,
                    "admissionRatio": 76,
                },
                {
                    "volunteerId": "cand-guangwai-001",
                    "schoolName": "广东外语外贸大学",
                    "majorName": "数字经济",
                    "tier": "保",
                    "provinceName": "广东",
                    "schoolNature": "公办",
                    "tuitionPerYear": 6060,
                    "admissionRatio": 82,
                },
                {
                    "volunteerId": "cand-coop-001",
                    "schoolName": "广东以色列理工学院",
                    "majorName": "材料科学与工程",
                    "tier": "稳",
                    "provinceName": "广东",
                    "programType": "中外合作",
                    "tuitionPerYear": 95000,
                    "admissionRatio": 88,
                },
            ],
        },
        version=12,
    )

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="replace",
            filters={"tuition_min": 20000},
            raw_user_text="方案里学费贵的太多了 能不能帮我换成便宜的",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["action_family"] == "replace_units"
    assert result["data"]["execution_payload"]["unit_ids"] == ["unit-nanfang", "unit-coop"]
    assert result["data"]["execution_payload"]["volunteer_ids"] == ["cand-szu-001", "cand-guangwai-001"]
    assert result["data"]["execution_payload"]["filters"]["tuition_min"] == 20000
    assert result["data"]["execution_payload"]["filters"]["auto_selected_candidates"] is True
    assert result["data"]["execution_payload"]["filters"]["auto_select_reason"] == "high_tuition"
    saved_state = save_mock.await_args.args[1]
    atomic = saved_state["executionPayload"]["atomic_actions"][0]
    assert atomic["unit_ids"] == ["unit-nanfang", "unit-coop"]
    assert atomic["volunteer_ids"] == ["cand-szu-001", "cand-guangwai-001"]
    assert atomic["filters"]["tuition_min"] == 20000
    assert "planPayload" not in saved_state["executionPayload"]


async def test_preview_plan_action_replace_targeted_high_tuition_item_auto_selects_candidate(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _context_with_review()
    ctx.sandbox.prime(
        "plan/candidates.json",
        {
            "available": True,
            "items": [
                {
                    "volunteerId": "cand-szu-001",
                    "schoolName": "深圳大学",
                    "majorName": "软件工程",
                    "tier": "稳",
                    "provinceName": "广东",
                    "schoolNature": "公办",
                    "tuitionPerYear": 6850,
                    "admissionRatio": 76,
                }
            ],
        },
        version=12,
    )

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="replace",
            targets=["广州南方学院"],
            raw_user_text="把高收费的换成正常收费的看看",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["action_family"] == "replace_units"
    assert result["data"]["execution_payload"]["unit_ids"] == ["unit-nanfang"]
    assert result["data"]["execution_payload"]["volunteer_ids"] == ["cand-szu-001"]
    assert result["data"]["execution_payload"]["filters"]["auto_select_reason"] == "high_tuition"
    saved_state = save_mock.await_args.args[1]
    atomic = saved_state["executionPayload"]["atomic_actions"][0]
    assert atomic["unit_ids"] == ["unit-nanfang"]
    assert atomic["volunteer_ids"] == ["cand-szu-001"]


async def test_preview_plan_action_replace_review_issue_intersects_filters(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _context_with_review()
    review = ctx.sandbox.peek("plan/review.json")
    review["checks"][0]["affectedUnitIds"] = ["unit-nanfang", "unit-coop"]
    ctx.sandbox.prime(
        "plan/candidates.json",
        {
            "available": True,
            "items": [
                {
                    "volunteerId": "cand-szu-001",
                    "schoolName": "深圳大学",
                    "majorName": "软件工程",
                    "tier": "稳",
                    "provinceName": "广东",
                    "schoolNature": "公办",
                    "tuitionPerYear": 6850,
                    "admissionRatio": 76,
                }
            ],
        },
        version=12,
    )

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="replace",
            filters={"school_nature": ["民办"]},
            review_issue_code="high_tuition",
            raw_user_text="审查里民办又贵的换掉",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["review_issue_target"]["code"] == "high_tuition"
    assert result["data"]["execution_payload"]["unit_ids"] == ["unit-nanfang"]
    assert result["data"]["execution_payload"]["volunteer_ids"] == ["cand-szu-001"]
    assert result["data"]["execution_payload"]["filters"]["school_nature"] == ["民办"]
    assert result["data"]["execution_payload"]["filters"]["auto_select_reason"] == "high_tuition"
    saved_state = save_mock.await_args.args[1]
    atomic = saved_state["executionPayload"]["atomic_actions"][0]
    assert atomic["unit_ids"] == ["unit-nanfang"]
    assert atomic["filters"]["school_nature"] == ["民办"]
    assert "planPayload" not in saved_state["executionPayload"]


async def test_preview_plan_action_replace_review_issue_falls_back_to_issue_filter(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _context_with_review()
    review = ctx.sandbox.peek("plan/review.json")
    review["checks"][0]["affectedUnitIds"] = ["stale-unit-id"]
    ctx.sandbox.prime(
        "plan/candidates.json",
        {
            "available": True,
            "items": [
                {
                    "volunteerId": "cand-szu-001",
                    "schoolName": "深圳大学",
                    "majorName": "软件工程",
                    "tier": "稳",
                    "provinceName": "广东",
                    "schoolNature": "公办",
                    "tuitionPerYear": 6850,
                    "admissionRatio": 76,
                },
                {
                    "volunteerId": "cand-guangwai-001",
                    "schoolName": "广东外语外贸大学",
                    "majorName": "数字经济",
                    "tier": "保",
                    "provinceName": "广东",
                    "schoolNature": "公办",
                    "tuitionPerYear": 6060,
                    "admissionRatio": 82,
                },
            ],
        },
        version=12,
    )

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="replace",
            review_issue_code="high_tuition",
            raw_user_text="方案里学费贵的太多了 能不能帮我换成便宜的",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["action_family"] == "replace_units"
    assert result["data"]["execution_payload"]["unit_ids"] == ["unit-nanfang", "unit-coop"]
    assert result["data"]["execution_payload"]["volunteer_ids"] == ["cand-szu-001", "cand-guangwai-001"]
    assert result["data"]["execution_payload"]["filters"]["program_type"] == ["高收费"]
    assert result["data"]["execution_payload"]["filters"]["auto_select_reason"] == "high_tuition"
    saved_state = save_mock.await_args.args[1]
    atomic = saved_state["executionPayload"]["atomic_actions"][0]
    assert atomic["unit_ids"] == ["unit-nanfang", "unit-coop"]
    assert atomic["filters"]["program_type"] == ["高收费"]
    assert "planPayload" not in saved_state["executionPayload"]


async def test_preview_plan_action_regenerate_order_can_target_tier_gap_review_issue(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _context_with_review()

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="regenerate_order",
            review_issue_code="tier_gap",
            raw_user_text="按审查里的梯度问题重新调整排序",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["kind"] == "plan_generation"
    assert result["data"]["action_family"] == "regenerate_order"
    assert result["data"]["review_issue_target"]["code"] == "tier_gap"
    assert result["data"]["review_issue_target"]["source_code"] == "ratio_distribution"
    assert result["data"]["execution_payload"]["review_issue_target"]["code"] == "tier_gap"
    assert result["data"]["execution_payload"]["filters"]["review_issue_code"] == "tier_gap"
    saved_state = save_mock.await_args.args[1]
    assert saved_state["executionPayload"]["atomic_actions"][0]["review_issue_target"]["code"] == "tier_gap"
    assert "planPayload" not in saved_state["executionPayload"]


async def test_preview_plan_action_sort_can_target_probability_inversion_review_issue(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _context_with_review()

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="sort",
            review_issue_code="probability_inversion",
            filters={"sort_field": "admission_ratio"},
            raw_user_text="按审查里的录取率倒挂重新排序",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["action_family"] == "sort_ordered_plan"
    assert result["data"]["review_issue_target"]["code"] == "probability_inversion"
    assert result["data"]["execution_payload"]["filters"]["review_issue_code"] == "probability_inversion"
    saved_state = save_mock.await_args.args[1]
    atomic = saved_state["executionPayload"]["atomic_actions"][0]
    assert atomic["sort_field"] == "admission_ratio"
    assert atomic["review_issue_target"]["code"] == "probability_inversion"
    assert "planPayload" not in saved_state["executionPayload"]


async def test_preview_plan_action_regenerate_order_can_target_safety_guard_review_issue(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _context_with_review()

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="regenerate_order",
            review_issue_code="safety_guard",
            raw_user_text="按审查里的保底不足重新调整方案",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["kind"] == "plan_generation"
    assert result["data"]["action_family"] == "regenerate_order"
    assert result["data"]["review_issue_target"]["code"] == "safety_guard"
    assert result["data"]["execution_payload"]["filters"]["review_issue_code"] == "safety_guard"
    saved_state = save_mock.await_args.args[1]
    assert saved_state["executionPayload"]["atomic_actions"][0]["review_issue_target"]["code"] == "safety_guard"
    assert "planPayload" not in saved_state["executionPayload"]


async def test_preview_plan_action_move_can_resolve_position_range(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=_poc_context()),
            action="remove",
            targets=["第31-32个"],
            raw_user_text="把第31-32个移出方案",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["execution_payload"]["unit_ids"] == ["unit-jnu", "unit-guanggong"]
    saved_state = save_mock.await_args.args[1]
    assert saved_state["executionPayload"]["atomic_actions"][0]["unit_ids"] == ["unit-jnu", "unit-guanggong"]


async def test_preview_plan_action_pin_lock_is_unsupported_without_pending(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=_poc_context()),
            action="pin_lock",
            targets=["第1个和第2个冲档"],
            raw_user_text="帮我把方案里第1个和第2个冲档锁定 位置不要动",
        )
    )

    assert result["next_step"] == "respond"
    assert result["data"]["action_family"] == "pin_or_lock_unit"
    assert result["data"]["unit_ids"] == ["unit-hnlg"]
    assert result["data"]["requires_confirmation"] is False
    assert "不会创建确认卡" in result["message"]
    save_mock.assert_not_awaited()


async def test_preview_plan_action_move_supports_tier_local_reorder_filters(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _poc_context()

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="move",
            filters={
                "tier": ["保底"],
                "selector_sort": "admission_ratio",
                "selector_rank": "max",
                "target_tier": "保底",
                "target_ordinal": 1,
            },
            raw_user_text="保底区里录取率最高的调到保底第一位",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["action_family"] == "move_ordered_unit"
    assert result["data"]["execution_payload"]["unit_ids"] == ["unit-guanggong"]
    assert result["data"]["execution_payload"]["target_position"] == 31
    assert result["data"]["execution_payload"]["filters"]["tier"] == ["保"]
    assert result["data"]["execution_payload"]["filters"]["target_tier"] == ["保"]
    saved_state = save_mock.await_args.args[1]
    atomic = saved_state["executionPayload"]["atomic_actions"][0]
    assert atomic["unit_ids"] == ["unit-guanggong"]
    assert atomic["target_position"] == 31


async def test_preview_plan_action_move_falls_back_target_tier_from_raw_text(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=_poc_context()),
            action="move",
            filters={
                "tier": ["保底"],
                "selector_sort": "admission_ratio",
                "selector_rank": "max",
            },
            raw_user_text="帮我把保底区里录取率最高的那个调到保底的第一位",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["action_family"] == "move_ordered_unit"
    assert result["data"]["execution_payload"]["unit_ids"] == ["unit-guanggong"]
    assert result["data"]["execution_payload"]["target_position"] == 31
    atomic = save_mock.await_args.args[1]["executionPayload"]["atomic_actions"][0]
    assert atomic["target_position"] == 31


async def test_preview_plan_action_move_falls_back_selector_from_raw_text(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=_poc_context()),
            action="move",
            filters={"tier": ["保底"]},
            raw_user_text="帮我把保底区里录取率最高的那个调到保底的第一位",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["action_family"] == "move_ordered_unit"
    assert result["data"]["execution_payload"]["unit_ids"] == ["unit-guanggong"]
    assert result["data"]["execution_payload"]["target_position"] == 31
    assert result["data"]["execution_payload"]["filters"]["selector_sort"] == "admission_probability"
    assert result["data"]["execution_payload"]["filters"]["selector_rank"] == "max"
    save_mock.assert_awaited_once()


async def test_preview_plan_action_move_recovers_missing_action_from_latest_user_text(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _poc_context()
    ctx.chat_history = [{"role": "user", "content": "帮我把保底区里录取率最高的那个调到保底的第一位"}]

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["action_family"] == "move_ordered_unit"
    assert result["data"]["execution_payload"]["unit_ids"] == ["unit-guanggong"]
    assert result["data"]["execution_payload"]["target_position"] == 31
    assert result["data"]["execution_payload"]["filters"]["tier"] == ["保"]
    assert result["data"]["execution_payload"]["filters"]["selector_sort"] == "admission_probability"
    assert result["data"]["execution_payload"]["filters"]["selector_rank"] == "max"
    atomic = save_mock.await_args.args[1]["executionPayload"]["atomic_actions"][0]
    assert atomic["action_type"] == "move_ordered_unit"
    assert atomic["target_position"] == 31


async def test_preview_plan_action_move_clarifies_ambiguous_tier_without_selector(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=_poc_context()),
            action="move",
            filters={"tier": ["保底"]},
            raw_user_text="帮我把保底区里的那个调到保底的第一位",
        )
    )

    assert result["next_step"] == "clarify"
    assert result["data"]["reason"] == "ambiguous_selector"
    assert "录取率最高" in result["message"]
    save_mock.assert_not_awaited()


async def test_preview_plan_action_move_requires_target_position(mocker):
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=_poc_context()),
            action="move",
            targets=["第1个"],
        )
    )

    assert result["next_step"] == "clarify"
    assert result["data"]["unit_ids"] == ["unit-hnlg"]
    assert "第几位" in result["message"]


async def test_preview_plan_action_add_uses_candidate_ids(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _poc_context()
    ctx.sandbox.prime(
        "plan/candidates.json",
        {
            "available": True,
            "items": [
                {
                    "volunteerId": "cand-szu-001",
                    "schoolName": "深圳大学",
                    "majorName": "计算机科学与技术",
                    "tier": "稳",
                    "provinceName": "广东",
                    "schoolNature": "公办",
                }
            ],
        },
        version=12,
    )

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="add",
            targets=["深圳大学.计算机科学与技术"],
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["action_family"] == "add_units"
    assert result["data"]["execution_payload"]["volunteer_ids"] == ["cand-szu-001"]
    assert save_mock.await_args.args[1]["executionPayload"]["atomic_actions"][0]["volunteer_ids"] == ["cand-szu-001"]


async def test_query_plan_with_plan():
    result = _load(
        await query_plan(
            make_run_context(request_context=_poc_context()),
            scope="plan",
            filters={"school_nature": "民办"},
        )
    )

    assert result["next_step"] == "respond"
    assert result["data"]["has_plan"] is True
    assert result["data"]["matched_total"] == 1
    assert result["data"]["items"][0]["school"] == "广州南方学院"
    assert result["data"]["items"][0]["school_nature"] == "民办"
    assert "院校性质=民办" in result["message"]


async def test_query_plan_filters_by_tuition_and_major_items():
    result = _load(
        await query_plan(
            make_run_context(request_context=_poc_context()),
            scope="plan",
            filters={"major": "网络与新媒体", "tuition_max": 20000},
        )
    )

    assert result["next_step"] == "respond"
    assert result["data"]["matched_total"] == 1
    assert result["data"]["items"][0]["school"] == "暨南大学"
    assert result["data"]["items"][0]["major"] == "网络与新媒体"
    assert "网络与新媒体" in result["message"]


async def test_query_plan_reports_volunteer_count_with_detail_count_when_rows_expand():
    ctx = _poc_context()
    ctx.sandbox.prime(
        "plan/items.json",
        {
            "available": True,
            "items": [
                {
                    "unitId": "unit-hnlg",
                    "volunteerId": "unit-hnlg_001",
                    "schoolName": "华南理工大学",
                    "majorName": "计算机科学与技术",
                    "position": 1,
                    "tier": "冲",
                },
                {
                    "unitId": "unit-hnlg",
                    "volunteerId": "unit-hnlg_002",
                    "schoolName": "华南理工大学",
                    "majorName": "软件工程",
                    "position": 1,
                    "tier": "冲",
                },
            ],
        },
        version=12,
    )

    result = _load(
        await query_plan(
            make_run_context(request_context=ctx),
            scope="plan",
            filters={"school": "华南理工大学"},
        )
    )

    assert result["data"]["matched_total"] == 1
    assert result["data"]["matched_plan_item_total"] == 1
    assert result["data"]["matched_detail_total"] == 2
    assert result["data"]["detail_granularity"] is True
    assert "命中1个志愿，涉及2条专业明细" in result["message"]


async def test_query_plan_can_show_tail_slice_with_admission_probability():
    result = _load(
        await query_plan(
            make_run_context(request_context=_poc_context()),
            scope="plan",
            filters={
                "tier": "保底",
                "slice": "tail",
                "limit": 1,
                "include_fields": ["admission_probability"],
            },
        )
    )

    assert result["next_step"] == "respond"
    assert result["data"]["matched_total"] == 2
    assert result["data"]["returned_total"] == 1
    assert result["data"]["items"][0]["school"] == "广东工业大学"
    assert result["data"]["query_controls"]["slice"] == "tail"
    assert "保底末尾1条" in result["message"]
    assert "录取率82%" in result["message"]


async def test_query_plan_defaults_to_compact_limit():
    result = _load(
        await query_plan(
            make_run_context(request_context=_poc_context()),
            scope="plan",
            filters={},
        )
    )

    assert result["next_step"] == "respond"
    assert result["data"]["limit"] == 5
    assert result["data"]["returned_total"] <= 5
    assert "展示前" in result["message"]


async def test_query_plan_school_question_summarizes_schools_not_major_rows():
    ctx = _poc_context()
    ctx.chat_history = [{"role": "user", "content": "再给我看下保底学校"}]

    result = _load(
        await query_plan(
            make_run_context(request_context=ctx),
            scope="plan",
            filters={"tier": "保"},
        )
    )

    assert result["next_step"] == "respond"
    assert result["data"]["limit"] == 5
    assert result["data"]["school_total"] == 2
    assert [item["school"] for item in result["data"]["school_summary"]] == ["暨南大学", "广东工业大学"]
    assert "涉及2所院校" in result["message"]
    assert "展示前2所院校" in result["message"]
    assert "网络与新媒体" not in result["message"]


async def test_query_plan_candidates_uses_candidate_file_query():
    adapter = FakeSandboxAdapter()
    adapter.add("plan/summary.json", BackendReadResult(_poc_context().sandbox.peek("plan/summary.json"), 12))
    adapter.add(
        "plan/candidates.json",
        BackendReadResult(
            {
                "available": True,
                "items": [
                    {
                        "schoolName": "深圳大学",
                        "majorName": "计算机科学与技术",
                        "provinceName": "广东",
                        "tier": "稳",
                        "schoolNature": "公办",
                    }
                ],
                "total": 1,
            },
            12,
        ),
    )
    ctx = _poc_context()
    ctx.sandbox = SandboxFileCache(ctx.sessionid, adapter, latest_backend_version=12)

    result = _load(
        await query_plan(
            make_run_context(request_context=ctx),
            scope="candidates",
            filters={"major": "计算机", "province": "广东", "tier": "稳", "limit": 5},
        )
    )

    assert result["next_step"] == "respond"
    assert result["data"]["scope"] == "candidates"
    assert result["data"]["matched_total"] == 1
    assert result["data"]["items"][0]["school"] == "深圳大学"
    assert adapter.calls[-1] == (
        "plan/candidates.json",
        {
            "tiers": ["稳"],
            "province_names": ["广东"],
            "school_keywords": [],
            "major_keywords": ["计算机"],
            "page_size": 5,
        },
    )


async def test_query_plan_no_plan():
    result = _load(await query_plan(make_run_context(request_context=_poc_context(with_plan=False))))

    assert result["next_step"] == "respond"
    assert result["data"]["has_plan"] is False
    assert "还没有生成正式方案" in result["message"]


async def test_confirm_pending_no_active_pending():
    result = _load(await confirm_pending(make_run_context(request_context=_poc_context()), action="confirm"))

    assert result["next_step"] == "respond"
    assert result["data"]["active"] is False
    assert "没有待确认操作" in result["message"]


async def test_confirm_pending_cancel_marks_pending_cancelled(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _context_with_backend_pending(
        {
            "active": True,
            "pending_id": "pending-cancel",
            "kind": "intent_change",
            "action_family": "apply_selected_intents",
            "summary": "排除医学",
            "source_backend_version": 12,
            "raw": {
                "pendingId": "pending-cancel",
                "kind": "intent_change",
                "actionFamily": "apply_selected_intents",
                "status": "active",
            },
        }
    )

    result = _load(await confirm_pending(make_run_context(request_context=ctx), action="cancel"))

    assert result["next_step"] == "respond"
    assert result["data"]["action"] == "cancel"
    saved_state = save_mock.await_args.args[1]
    assert saved_state["status"] == "cancelled"
    assert ctx.sandbox.peek("pending.json") is None


async def test_confirm_pending_blocks_stale_version(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    update_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.update_planning_constraint_state",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _context_with_backend_pending(
        {
            "active": True,
            "pending_id": "pending-stale",
            "kind": "intent_change",
            "action_family": "apply_selected_intents",
            "summary": "要求法学",
            "source_backend_version": 11,
            "execution_payload": {
                "merged": {"major_intents": {"level3": ["法学"]}},
                "intentMode": "constraint",
            },
            "raw": {
                "pendingId": "pending-stale",
                "kind": "intent_change",
                "actionFamily": "apply_selected_intents",
                "status": "active",
                "sourceBackendVersion": 11,
            },
        },
        plan_version=12,
    )

    result = _load(await confirm_pending(make_run_context(request_context=ctx), action="confirm"))

    assert result["next_step"] == "respond"
    assert result["data"]["error"] == "version_mismatch"
    assert "已失效" in result["message"]
    update_mock.assert_not_awaited()
    saved_state = save_mock.await_args.args[1]
    assert saved_state["status"] == "expired"
    assert saved_state["resultCode"] == "version_mismatch"


async def test_confirm_pending_applies_intent_payload_directly(mocker):
    update_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.update_planning_constraint_state",
        AsyncMock(return_value={"code": 0}),
    )
    ordered_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.generate_planning_ordered_plan",
        AsyncMock(return_value={"code": 0}),
    )
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _context_with_backend_pending(
        {
            "active": True,
            "pending_id": "pending-intent",
            "kind": "intent_change",
            "action_family": "apply_selected_intents",
            "summary": "要求法学，排除医学",
            "source_backend_version": 12,
            "execution_payload": {
                "merged": {"major_intents": {"level3": ["法学"], "negative_level1": ["医学"]}},
                "intentMode": "constraint",
            },
            "raw": {
                "pendingId": "pending-intent",
                "kind": "intent_change",
                "actionFamily": "apply_selected_intents",
                "status": "active",
                "sourceBackendVersion": 12,
            },
        }
    )

    result = _load(await confirm_pending(make_run_context(request_context=ctx), action="confirm"))

    assert result["next_step"] == "respond"
    assert result["data"]["applied"] is True
    assert result["data"]["result"]["has_plan"] is True
    assert result["data"]["result"]["plan_regenerated"] is True
    update_mock.assert_awaited_once_with(
        ctx.sessionid,
        intent_mode="constraint",
        major_preferences={"positive": ["法学"], "negative": ["医学"]},
        school_preferences=None,
        region_preferences=None,
    )
    ordered_mock.assert_awaited_once_with(1, ctx.sessionid)
    saved_state = save_mock.await_args.args[1]
    assert saved_state["status"] == "applied"
    assert saved_state["resultCode"] == "applied"


async def test_confirm_pending_intent_without_plan_does_not_regenerate_order(mocker):
    update_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.update_planning_constraint_state",
        AsyncMock(return_value={"code": 0}),
    )
    ordered_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.generate_planning_ordered_plan",
        AsyncMock(return_value={"code": 0}),
    )
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _poc_context(with_plan=False)
    pending_state = {
        "active": True,
        "pending_id": "pending-intent-no-plan",
        "kind": "intent_change",
        "action_family": "apply_selected_intents",
        "summary": "排除民办",
        "source_backend_version": 0,
        "execution_payload": {
            "merged": {"school_intents": {"negative_school_nature": ["民办"]}},
            "intentMode": "constraint",
        },
        "raw": {
            "pendingId": "pending-intent-no-plan",
            "kind": "intent_change",
            "actionFamily": "apply_selected_intents",
            "status": "active",
            "sourceBackendVersion": 0,
        },
    }
    ctx.sandbox.prime("pending.json", pending_state, version=0)

    result = _load(await confirm_pending(make_run_context(request_context=ctx), action="confirm"))

    assert result["data"]["applied"] is True
    assert result["data"]["result"]["has_plan"] is False
    assert result["data"]["result"]["plan_regenerated"] is False
    assert "后续生成方案" in result["message"]
    assert "约束" not in result["message"]
    update_mock.assert_awaited_once()
    ordered_mock.assert_not_awaited()


async def test_confirm_pending_applies_remove_units_directly(mocker):
    remove_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.remove_planning_ordered_plan_units",
        AsyncMock(return_value={"code": 0}),
    )
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _context_with_backend_pending(
        {
            "active": True,
            "pending_id": "pending-plan",
            "kind": "plan_mutation",
            "action_family": "remove_units",
            "summary": "移出两个志愿组",
            "source_backend_version": 12,
            "execution_payload": {
                "action_family": "remove_units",
                "atomic_actions": [{"action_type": "remove_units", "unit_ids": ["u1", "u2"]}],
            },
            "raw": {
                "pendingId": "pending-plan",
                "kind": "plan_mutation",
                "actionFamily": "remove_units",
                "status": "active",
                "sourceBackendVersion": 12,
            },
        }
    )

    result = _load(await confirm_pending(make_run_context(request_context=ctx), action="confirm"))

    assert result["next_step"] == "respond"
    assert result["data"]["applied"] is True
    remove_mock.assert_awaited_once_with(1, ctx.sessionid, ["u1", "u2"])
    assert save_mock.await_args.args[1]["status"] == "applied"
    assert save_mock.await_args.kwargs["version"] == 12


async def test_confirm_pending_applies_replace_units_directly(mocker):
    remove_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.remove_planning_ordered_plan_units",
        AsyncMock(return_value={"code": 0}),
    )
    select_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.select_working_plan_items",
        AsyncMock(return_value={"code": 0}),
    )
    order_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.generate_planning_ordered_plan",
        AsyncMock(return_value={"code": 0}),
    )
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _context_with_backend_pending(
        {
            "active": True,
            "pending_id": "pending-replace",
            "kind": "plan_mutation",
            "action_family": "replace_units",
            "summary": "替换一个志愿组",
            "source_backend_version": 12,
            "execution_payload": {
                "action_family": "replace_units",
                "atomic_actions": [
                    {"action_type": "replace_units", "unit_ids": ["unit-old"], "volunteer_ids": ["cand-new"]}
                ],
            },
            "raw": {
                "pendingId": "pending-replace",
                "kind": "plan_mutation",
                "actionFamily": "replace_units",
                "status": "active",
                "sourceBackendVersion": 12,
            },
        }
    )

    result = _load(await confirm_pending(make_run_context(request_context=ctx), action="confirm"))

    assert result["next_step"] == "respond"
    assert result["data"]["applied"] is True
    remove_mock.assert_awaited_once_with(1, ctx.sessionid, ["unit-old"])
    select_mock.assert_awaited_once_with(1, ctx.sessionid, ["cand-new"])
    order_mock.assert_awaited_once_with(1, ctx.sessionid)
    assert save_mock.await_args.args[1]["status"] == "applied"


async def test_confirm_pending_rejects_non_structured_plan_payload(mocker):
    remove_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.remove_planning_ordered_plan_units",
        AsyncMock(return_value={"code": 0}),
    )
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _context_with_backend_pending(
        {
            "active": True,
            "pending_id": "pending-legacy",
            "kind": "plan_mutation",
            "action_family": "remove_units",
            "source_backend_version": 12,
            "execution_payload": {"planPayload": "{\"stage\":\"apply\",\"action_family\":\"remove_units\"}"},
            "raw": {
                "pendingId": "pending-legacy",
                "kind": "plan_mutation",
                "actionFamily": "remove_units",
                "status": "active",
                "sourceBackendVersion": 12,
            },
        }
    )

    result = _load(await confirm_pending(make_run_context(request_context=ctx), action="confirm"))

    assert result["next_step"] == "respond"
    assert result["data"]["applied"] is False
    assert result["data"]["result"]["reason"] == "missing_structured_plan_payload"
    assert "缺少可执行结构" in result["message"]
    remove_mock.assert_not_awaited()
    assert save_mock.await_args.args[1]["status"] == "failed"


async def test_confirm_pending_dry_run_does_not_apply_or_save(mocker):
    update_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.update_planning_constraint_state",
        AsyncMock(return_value={"code": 0}),
    )
    order_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.generate_planning_ordered_plan",
        AsyncMock(return_value={"code": 0}),
    )
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _context_with_backend_pending(
        {
            "active": True,
            "pending_id": "pending-dry-run-intent",
            "kind": "intent_change",
            "action_family": "apply_selected_intents",
            "source_backend_version": 12,
            "execution_payload": {
                "intentMode": "constraint",
                "selectedData": {
                    "selected": [
                        {"value": {"major_intents": {"negative_level1": ["医学"]}}},
                    ]
                },
            },
            "raw": {
                "pendingId": "pending-dry-run-intent",
                "kind": "intent_change",
                "actionFamily": "apply_selected_intents",
                "status": "active",
                "sourceBackendVersion": 12,
            },
        }
    )
    ctx.dry_run_state_mutations = True

    result = _load(await confirm_pending(make_run_context(request_context=ctx), action="confirm"))

    assert result["next_step"] == "respond"
    assert result["data"]["dry_run"] is True
    assert result["data"]["would_apply"] is True
    assert result["data"]["applied"] is False
    update_mock.assert_not_awaited()
    order_mock.assert_not_awaited()
    save_mock.assert_not_awaited()


async def test_service_pending_confirmation_uses_structured_plan_bridge(mocker):
    pending_state = {
        "type": "pendingConfirmation",
        "pendingId": "pending-structured-plan",
        "sessionId": "session-structured-plan",
        "kind": "plan_mutation",
        "status": "active",
        "actionFamily": "remove_units",
        "summary": "移出两个志愿组",
        "executionPayload": {
            "action_family": "remove_units",
            "atomic_actions": [
                {"action_type": "remove_units", "unit_ids": ["u1", "u2"]}
            ],
        },
        "sourceBackendVersion": 12,
    }

    class FakeHistoryStore:
        def __init__(self):
            self.saved = None

        async def load(self, session_id):  # noqa: ARG002
            return []

        async def save(self, session_id, history):
            self.saved = (session_id, history)

    remove_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.remove_planning_ordered_plan_units",
        AsyncMock(return_value={"code": 0}),
    )
    save_pending_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    mocker.patch(
        "app.service._load_pending_confirmation_state",
        AsyncMock(return_value=pending_state),
    )
    mocker.patch(
        "app.service.get_planning_workspace_state",
        AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "version": 12,
                    "phase": "ordered",
                    "orderedPlanState": {
                        "summary": {"unitTotal": 45, "targetUnitCount": 45},
                        "items": [],
                    },
                },
            }
        ),
    )

    history_store = FakeHistoryStore()
    service = object.__new__(ChatService)
    service.history_store = history_store

    reply = await service.handle_pending_confirmation(
        "session-structured-plan",
        "user-structured-plan",
        json.dumps(
            {
                "action": "confirm",
                "kind": "plan_mutation",
                "pendingId": "pending-structured-plan",
            },
            ensure_ascii=False,
        ),
    )

    assert getattr(reply, "primary", "").startswith("已移出2个")
    assert [item.type for item in reply.followups] == [
        "planningWorkspaceAction",
        "planningWorkspaceAction",
    ]
    remove_mock.assert_awaited_once_with(1, "session-structured-plan", ["u1", "u2"])
    assert save_pending_mock.await_args.args[1]["status"] == "applied"
    assert history_store.saved is not None


def test_zhiyuan_agent_direct_tool_output_uses_next_step():
    agent = ZhiyuanAgent(SimpleNamespace(model=TestModel(), model_settings={}))
    tool_returns = [
        _tool_return(
            {
                "next_step": "confirm",
                "data": {"preview": "待确认"},
                "message": "我先整理成待确认预览，确认前不会生效。",
            },
            tool_name="preview_intent_change",
        )
    ]

    assert agent.should_return_directly_from_tool(["preview_intent_change"], tool_returns, None) is True
    assert (
        agent.render_direct_tool_output(["preview_intent_change"], tool_returns, None)
        == "我先整理成待确认预览，确认前不会生效。"
    )

    readonly_returns = [
        _tool_return(
            {
                "next_step": "respond",
                "data": {"summary": "当前方案有45个志愿。"},
                "message": "当前方案有45个志愿。",
            },
            tool_name="query_plan",
        )
    ]
    assert agent.should_return_directly_from_tool(["query_plan"], readonly_returns, None) is False

    confirm_returns = [
        _tool_return(
            {
                "next_step": "respond",
                "data": {
                    "action": "confirm",
                    "kind": "intent_change",
                    "action_family": "apply_selected_intents",
                    "applied": True,
                },
                "message": "已采纳你的报考要求。",
            },
            tool_name="confirm_pending",
        )
    ]
    assert agent.should_return_directly_from_tool(["confirm_pending"], confirm_returns, None) is True
    assert (
        agent.render_direct_tool_output(["confirm_pending"], confirm_returns, None)
        == "已采纳你的报考要求。"
    )


def test_zhiyuan_agent_direct_tool_output_combines_readonly_before_preview():
    agent = ZhiyuanAgent(SimpleNamespace(model=TestModel(), model_settings={}))
    tool_returns = [
        _tool_return(
            {
                "next_step": "respond",
                "data": {"summary": "高收费志愿占比约27%。"},
                "message": "当前方案里高收费志愿占比约27%。",
            },
            tool_name="query_plan",
        ),
        _tool_return(
            {
                "next_step": "confirm",
                "data": {"preview": "替换高收费项"},
                "message": "已列出调整预览，确认前不会改动当前方案。",
            },
            tool_name="preview_plan_action",
        ),
    ]

    rendered = agent.render_direct_tool_output(["query_plan", "preview_plan_action"], tool_returns, None)

    assert rendered is not None
    assert rendered.startswith("当前方案里高收费志愿占比约27%。")
    assert "下面是这次待确认预览" in rendered
    assert "已列出调整预览" in rendered


def test_zhiyuan_agent_retries_incomplete_plan_action_before_user_clarify():
    agent = ZhiyuanAgent(SimpleNamespace(model=TestModel(), model_settings={}))
    incomplete_plan_action = [
        _tool_return(
            {
                "next_step": "clarify",
                "data": {"reason": "missing_targets", "action": "remove"},
                "message": "还没有唯一定位到要调整的方案项，请说明学校、专业或第几个志愿。",
            },
            tool_name="preview_plan_action",
        )
    ]
    review_issue_not_in_plan = [
        _tool_return(
            {
                "next_step": "clarify",
                "data": {"reason": "review_issue_units_not_in_plan", "review_issue_code": "high_tuition"},
                "message": "还没有唯一定位到要调整的方案项，请说明学校、专业或第几个志愿。",
            },
            tool_name="preview_plan_action",
        )
    ]
    candidate_no_match = [
        _tool_return(
            {
                "next_step": "clarify",
                "data": {"reason": "candidate_no_match", "action": "replace"},
                "message": "替换需要同时唯一定位要移出的当前方案项和要加入的候选志愿。",
            },
            tool_name="preview_plan_action",
        )
    ]
    active_conflict = [
        _tool_return(
            {
                "next_step": "clarify",
                "data": {"reason": "active_pending_conflict"},
                "message": "当前已经有一项待确认操作正在等待处理。",
            },
            tool_name="preview_plan_action",
        )
    ]

    assert agent.should_return_directly_from_tool(["preview_plan_action"], incomplete_plan_action, None) is False
    assert agent.should_return_directly_from_tool(["preview_plan_action"], review_issue_not_in_plan, None) is False
    assert agent.should_return_directly_from_tool(["preview_plan_action"], candidate_no_match, None) is False
    assert agent.should_return_directly_from_tool(["preview_plan_action"], active_conflict, None) is True


def test_zhiyuan_agent_tool_call_total_guard():
    agent = ZhiyuanAgent(SimpleNamespace(model=TestModel(), model_settings={}))
    observability: dict[str, Any] = {}

    assert agent._guard_repeated_tool_calls(["query_plan"], observability) is None
    assert agent._guard_repeated_tool_calls(["explore_topic"], observability) is None
    assert agent._guard_repeated_tool_calls(["read_state"], observability) is None
    reply = agent._guard_repeated_tool_calls(["preview_intent_change"], observability)

    assert reply is not None
    assert "工具调用上限" in reply
    assert observability["guardedToolName"] == "total_tool_calls"
    assert observability["guardedToolCount"] == 4


async def test_preview_intent_change_blocks_new_pending_when_turn_started_with_pending(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _poc_context(pending=True)

    result = _load(
        await preview_intent_change(
            make_run_context(request_context=ctx),
            intent_type="major",
            positive={"level2": ["计算机类"]},
            constraint_type="must_have",
            raw_user_text="计算机和自动化方向考生不考虑",
        )
    )

    assert result["data"]["reason"] == "active_pending_conflict"
    assert result["next_step"] == "clarify"
    assert result["data"]["pending_created"] is False
    assert "不会再生成第二张待确认卡" in result["message"]
    assert "计算机和自动化方向考生不考虑" in result["message"]
    save_mock.assert_not_awaited()


async def test_preview_plan_action_blocks_new_pending_when_turn_started_with_pending(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _poc_context(pending=True)

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="remove",
            filters={"school_nature": ["民办"]},
            raw_user_text="那把民办的删掉",
        )
    )

    assert result["data"]["reason"] == "active_pending_conflict"
    assert result["next_step"] == "clarify"
    assert result["data"]["pending_created"] is False
    assert "不会再生成第二张待确认卡" in result["message"]
    assert "那把民办的删掉" in result["message"]
    save_mock.assert_not_awaited()


async def test_zhiyuan_agent_continues_after_query_plan_tool():
    client = SimpleNamespace(model=TestModel(call_tools=["query_plan"]), model_settings={})
    agent = ZhiyuanAgent(client)
    deps = _poc_context()

    reply, _, all_messages, usage = await agent.run_with_message_deltas("方案里有没有民办", deps=deps)

    assert "当前正式方案有45个志愿" in reply
    assert usage.tool_calls == 1
    assert deps.agent_observability.get("directToolReturn") is not True
    assert _tool_calls(all_messages)[0].tool_name == "query_plan"


async def test_zhiyuan_agent_continues_after_answer_policy_tool():
    client = SimpleNamespace(model=TestModel(call_tools=["answer_policy"]), model_settings={})
    agent = ZhiyuanAgent(client)
    deps = _poc_context()

    reply, _, all_messages, usage = await agent.run_with_message_deltas("分数和位次怎么参考", deps=deps)

    assert "只读规则问题" in reply
    assert usage.tool_calls == 1
    assert deps.agent_observability.get("directToolReturn") is not True
    assert _tool_calls(all_messages)[0].tool_name == "answer_policy"


async def test_zhiyuan_agent_continues_after_review_plan_tool():
    client = SimpleNamespace(model=TestModel(call_tools=["review_plan"]), model_settings={})
    agent = ZhiyuanAgent(client)
    deps = _context_with_review()

    reply, _, all_messages, usage = await agent.run_with_message_deltas("审查一下当前方案", deps=deps)

    assert "方案审查" in reply
    assert usage.tool_calls == 1
    assert deps.agent_observability.get("directToolReturn") is not True
    assert _tool_calls(all_messages)[0].tool_name == "review_plan"


async def test_service_poc_shadow_records_structured_summary(mocker):
    class FakePocAgent:
        seen_deps = None

        async def run_with_message_deltas(self, user_prompt, message_history=None, deps=None):  # noqa: ARG002
            self.seen_deps = deps
            new_messages = [
                ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="preview_intent_change",
                            args={
                                "intent_type": "major",
                                "negative": {"level1": ["医学"]},
                            },
                            tool_call_id="call-1",
                        )
                    ]
                ),
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name="preview_intent_change",
                            content=json.dumps(
                                {
                                    "next_step": "confirm",
                                    "data": {},
                                    "message": "我先整理成待确认预览。",
                                },
                                ensure_ascii=False,
                            ),
                            tool_call_id="call-1",
                        )
                    ]
                ),
                ModelResponse(parts=[TextPart(content="我先整理成待确认预览。")]),
            ]
            all_messages = [*(message_history or []), *new_messages]
            usage = SimpleNamespace(
                tool_calls=1,
                requests=1,
                input_tokens=100,
                output_tokens=20,
                total_tokens=120,
            )
            return "我先整理成待确认预览。", new_messages, all_messages, usage

    service = object.__new__(ChatService)
    service._zhiyuan_agent_poc_shadow_enabled = True
    fake_agent = FakePocAgent()
    service.zhiyuan_agent_poc = fake_agent
    log_mock = mocker.patch("app.service._log_zhiyuan_agent_poc_shadow_event")
    ctx = _poc_context(pending=True)

    shadow = await service._maybe_run_zhiyuan_agent_poc_shadow(
        session_id="session-shadow",
        user_id="user-shadow",
        content="不要医学类",
        request_context=ctx,
        message_history=[],
    )

    assert shadow is not None
    assert shadow["status"] == "running"
    task = getattr(ctx, "_zhiyuan_agent_poc_shadow_task")
    completed = await task
    assert completed["status"] == "success"
    assert completed["firstToolNames"] == ["preview_intent_change"]
    assert completed["nextSteps"] == ["confirm"]
    assert completed["firstToolArgs"]["negative"] == {"level1": ["医学"]}
    assert getattr(ctx, "_zhiyuan_agent_poc_shadow") == completed
    assert fake_agent.seen_deps is not None
    assert fake_agent.seen_deps.dry_run_state_mutations is True
    assert fake_agent.seen_deps.conversation_phase is not ctx.conversation_phase
    log_mock.assert_called_once()


class _FakeHistoryStore:
    def __init__(self) -> None:
        self.saved: tuple[str, list[Any]] | None = None

    async def load(self, session_id):  # noqa: ARG002
        return []

    async def save(self, session_id, history):
        self.saved = (session_id, history)


def _direct_service(fake_agent: Any, *, enabled: bool = True) -> tuple[ChatService, _FakeHistoryStore]:
    history_store = _FakeHistoryStore()
    service = object.__new__(ChatService)
    service._zhiyuan_agent_direct_enabled = enabled
    service._zhiyuan_agent_rollout_percent = 0.0
    service.zhiyuan_agent_poc = fake_agent
    service.history_store = history_store
    service.llm_client = SimpleNamespace(
        config=SimpleNamespace(provider="fake-provider", model_name="fake-model")
    )
    service._usage_trackers = {}
    return service, history_store


def _direct_usage() -> SimpleNamespace:
    return SimpleNamespace(
        requests=1,
        input_tokens=100,
        output_tokens=20,
        total_tokens=120,
        tool_calls=1,
    )


def _direct_messages(
    *,
    tool_name: str,
    tool_payload: dict[str, Any],
    reply: str,
    call_id: str = "call-direct",
) -> list[Any]:
    return [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=tool_name,
                    args={},
                    tool_call_id=call_id,
                )
            ]
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name=tool_name,
                    content=json.dumps(tool_payload, ensure_ascii=False),
                    tool_call_id=call_id,
                )
            ]
        ),
        ModelResponse(parts=[TextPart(content=reply)]),
    ]


async def test_service_zhiyuan_agent_direct_disabled_does_not_call_agent():
    class FakeDirectAgent:
        called = False

        async def run_with_message_deltas(self, *args, **kwargs):  # noqa: ARG002
            self.called = True
            raise AssertionError("direct agent should not be called")

    fake_agent = FakeDirectAgent()
    service, _history_store = _direct_service(fake_agent, enabled=False)
    ctx = _poc_context()

    reply = await service._maybe_handle_zhiyuan_agent_direct_route(
        session_id=ctx.sessionid,
        user_id=ctx.userid,
        content="民办的不要",
        history=[],
        request_context=ctx,
        message_history=[],
        turn_started_at=0.0,
        on_progress=None,
    )

    assert reply is None
    assert fake_agent.called is False


async def test_service_zhiyuan_agent_direct_requires_available_score():
    class FakeDirectAgent:
        called = False

        async def run_with_message_deltas(self, *args, **kwargs):  # noqa: ARG002
            self.called = True
            raise AssertionError("direct agent should not be called without score")

    fake_agent = FakeDirectAgent()
    service, _history_store = _direct_service(fake_agent)
    ctx = _poc_context()
    ctx.score_detail = None
    ctx.sandbox.prime("score.json", {"available": False, "batch": "01"}, version=12)

    reply = await service._maybe_handle_zhiyuan_agent_direct_route(
        session_id=ctx.sessionid,
        user_id=ctx.userid,
        content="我575分安徽物化生先看看",
        history=[],
        request_context=ctx,
        message_history=[],
        turn_started_at=time.monotonic(),
        on_progress=None,
    )

    assert reply is None
    assert fake_agent.called is False


async def test_service_zhiyuan_agent_direct_runs_readonly_while_pending():
    class FakeDirectAgent:
        called = False

        async def run_with_message_deltas(self, user_prompt, message_history=None, deps=None, on_progress=None):  # noqa: ARG002
            self.called = True
            tool_payload = {
                "next_step": "respond",
                "data": {"answer": "强基未通过校测后还可以按普通批方案衔接。"},
                "message": "强基未通过校测后还可以按普通批方案衔接。",
            }
            new_messages = _direct_messages(
                tool_name="answer_policy",
                tool_payload=tool_payload,
                reply=tool_payload["message"],
            )
            return tool_payload["message"], new_messages, [*(message_history or []), *new_messages], _direct_usage()

    fake_agent = FakeDirectAgent()
    service, history_store = _direct_service(fake_agent)
    ctx = _poc_context(pending=True)

    reply = await service._maybe_handle_zhiyuan_agent_direct_route(
        session_id=ctx.sessionid,
        user_id=ctx.userid,
        content="万一强基没过校测普通批怎么衔接",
        history=[],
        request_context=ctx,
        message_history=[],
        turn_started_at=time.monotonic(),
        on_progress=None,
    )

    assert isinstance(reply, str)
    assert "普通批方案衔接" in reply
    assert fake_agent.called is True
    assert history_store.saved is not None


async def test_service_zhiyuan_agent_direct_plan_pending_card():
    pending_id = "pending-direct-plan"
    pending_state = {
        "type": "pendingConfirmation",
        "pendingId": pending_id,
        "sessionId": "session-direct-plan",
        "kind": "plan_mutation",
        "status": "active",
        "actionFamily": "remove_units",
        "summary": "移出方案里的民办院校。",
        "affectedScope": "涉及2个志愿组",
        "executionPayload": {
            "action_family": "remove_units",
            "atomic_actions": [
                {"action_type": "remove_units", "filters": {"school_nature": ["民办"]}},
            ],
        },
        "sourceBackendVersion": 12,
    }
    tool_payload = {
        "next_step": "confirm",
        "data": {"pending_id": pending_id, "pending_created": True},
        "message": "已列出调整预览。",
    }

    class FakeDirectAgent:
        async def run_with_message_deltas(self, user_prompt, message_history=None, deps=None, on_progress=None):  # noqa: ARG002
            new_messages = _direct_messages(
                tool_name="preview_plan_action",
                tool_payload=tool_payload,
                reply="已列出调整预览。",
            )
            return "已列出调整预览。", new_messages, [*(message_history or []), *new_messages], _direct_usage()

    service, history_store = _direct_service(FakeDirectAgent())
    ctx = _poc_context()
    ctx.sandbox = build_request_sandbox(
        session_id=ctx.sessionid,
        batch=ctx.batch,
        score_detail=ctx.score_detail,
        init_profile=ctx.init_profile,
        planning_summary=ctx.planning_summary,
        pending_state=pending_state,
    )

    reply = await service._maybe_handle_zhiyuan_agent_direct_route(
        session_id=ctx.sessionid,
        user_id=ctx.userid,
        content="方案里的民办不要了",
        history=[],
        request_context=ctx,
        message_history=[],
        turn_started_at=time.monotonic(),
        on_progress=None,
    )

    assert getattr(reply, "primary", "").startswith("已列出调整预览")
    assert len(reply.followups) == 1
    card_payload = json.loads(reply.followups[0].content)
    assert card_payload["kind"] == "plan_mutation"
    assert card_payload["actionFamily"] == "remove_units"
    assert card_payload["pendingId"] == pending_id
    assert "确认执行" == card_payload["confirmText"]
    assert history_store.saved is not None
    assert service.get_usage_summary(ctx.sessionid)["total_tool_calls"] == 1


async def test_service_zhiyuan_agent_direct_plan_pending_card_preserves_compound_reply():
    pending_id = "pending-direct-plan-compound"
    pending_state = {
        "type": "pendingConfirmation",
        "pendingId": pending_id,
        "sessionId": "session-direct-plan-compound",
        "kind": "plan_mutation",
        "status": "active",
        "actionFamily": "remove_units",
        "summary": "移出方案里的高收费志愿。",
        "affectedScope": "涉及3个志愿组",
        "executionPayload": {
            "action_family": "remove_units",
            "atomic_actions": [
                {"action_type": "remove_units", "filters": {"program_type": ["高收费"]}},
            ],
        },
        "sourceBackendVersion": 12,
    }
    query_payload = {
        "next_step": "respond",
        "data": {"summary": "高收费志愿占比约27%。"},
        "message": "当前方案里高收费志愿占比约27%。",
    }
    preview_payload = {
        "next_step": "confirm",
        "data": {"pending_id": pending_id, "pending_created": True},
        "message": "已列出调整预览。",
    }
    compound_reply = "当前方案里高收费志愿占比约27%。\n\n下面是这次待确认预览：\n\n已列出调整预览。"

    class FakeDirectAgent:
        async def run_with_message_deltas(self, user_prompt, message_history=None, deps=None, on_progress=None):  # noqa: ARG002
            new_messages = [
                ModelResponse(
                    parts=[
                        ToolCallPart(tool_name="query_plan", args={}, tool_call_id="call-query"),
                    ]
                ),
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name="query_plan",
                            content=json.dumps(query_payload, ensure_ascii=False),
                            tool_call_id="call-query",
                        )
                    ]
                ),
                ModelResponse(
                    parts=[
                        ToolCallPart(tool_name="preview_plan_action", args={}, tool_call_id="call-preview"),
                    ]
                ),
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name="preview_plan_action",
                            content=json.dumps(preview_payload, ensure_ascii=False),
                            tool_call_id="call-preview",
                        )
                    ]
                ),
                ModelResponse(parts=[TextPart(content=compound_reply)]),
            ]
            return compound_reply, new_messages, [*(message_history or []), *new_messages], _direct_usage()

    service, history_store = _direct_service(FakeDirectAgent())
    ctx = _poc_context()
    ctx.sandbox = build_request_sandbox(
        session_id=ctx.sessionid,
        batch=ctx.batch,
        score_detail=ctx.score_detail,
        init_profile=ctx.init_profile,
        planning_summary=ctx.planning_summary,
        pending_state=pending_state,
    )

    reply = await service._maybe_handle_zhiyuan_agent_direct_route(
        session_id=ctx.sessionid,
        user_id=ctx.userid,
        content="高收费的志愿占比多少 能不能换成便宜的",
        history=[],
        request_context=ctx,
        message_history=[],
        turn_started_at=time.monotonic(),
        on_progress=None,
    )

    assert "高收费志愿占比约27%" in getattr(reply, "primary", "")
    assert "下面是这次待确认预览" in getattr(reply, "primary", "")
    assert len(reply.followups) == 1
    card_payload = json.loads(reply.followups[0].content)
    assert card_payload["kind"] == "plan_mutation"
    assert card_payload["pendingId"] == pending_id
    assert history_store.saved is not None


async def test_service_zhiyuan_agent_direct_intent_pending_card():
    pending_id = "pending-direct-intent"
    pending_state = {
        "type": "pendingConfirmation",
        "pendingId": pending_id,
        "sessionId": "session-direct-intent",
        "kind": "intent_change",
        "status": "active",
        "actionFamily": "apply_selected_intents",
        "summary": "排除民办院校。",
        "executionPayload": {
            "intentMode": "constraint",
            "constraintIntentType": "exclude",
            "merged": {"school": {"negative": {"attributes": ["院校性质:民办"]}}},
            "selectedData": {"intentMode": "constraint"},
        },
        "sourceBackendVersion": 12,
    }
    tool_payload = {
        "next_step": "confirm",
        "data": {"pending_id": pending_id, "pending_created": True},
        "message": "已整理成待确认的报考要求。",
    }

    class FakeDirectAgent:
        async def run_with_message_deltas(self, user_prompt, message_history=None, deps=None, on_progress=None):  # noqa: ARG002
            new_messages = _direct_messages(
                tool_name="preview_intent_change",
                tool_payload=tool_payload,
                reply="已整理成待确认的报考要求。",
            )
            return "已整理成待确认的报考要求。", new_messages, [*(message_history or []), *new_messages], _direct_usage()

    service, _history_store = _direct_service(FakeDirectAgent())
    ctx = _poc_context()
    ctx.sandbox = build_request_sandbox(
        session_id=ctx.sessionid,
        batch=ctx.batch,
        score_detail=ctx.score_detail,
        init_profile=ctx.init_profile,
        planning_summary=ctx.planning_summary,
        pending_state=pending_state,
    )

    reply = await service._maybe_handle_zhiyuan_agent_direct_route(
        session_id=ctx.sessionid,
        user_id=ctx.userid,
        content="民办的不要",
        history=[],
        request_context=ctx,
        message_history=[],
        turn_started_at=time.monotonic(),
        on_progress=None,
    )

    assert "报考要求" in getattr(reply, "primary", "")
    assert "报考想法" not in getattr(reply, "primary", "")
    assert "约束" not in getattr(reply, "primary", "")
    card_payload = json.loads(reply.followups[0].content)
    assert card_payload["kind"] == "intent_change"
    assert card_payload["pendingId"] == pending_id
    assert card_payload["title"] == "采纳这次报考条件"
    assert "约束" not in card_payload["summary"]


async def test_service_zhiyuan_agent_direct_readonly_reply_without_card():
    class FakeDirectAgent:
        async def run_with_message_deltas(self, user_prompt, message_history=None, deps=None, on_progress=None):  # noqa: ARG002
            tool_payload = {
                "next_step": "respond",
                "data": {"answer": "可以结合位次和预算判断。"},
                "message": "高收费是否适合，需要结合家庭预算、录取概率和专业认可度一起看。",
            }
            new_messages = _direct_messages(
                tool_name="answer_policy",
                tool_payload=tool_payload,
                reply=tool_payload["message"],
            )
            return tool_payload["message"], new_messages, [*(message_history or []), *new_messages], _direct_usage()

    service, history_store = _direct_service(FakeDirectAgent())
    ctx = _poc_context()

    reply = await service._maybe_handle_zhiyuan_agent_direct_route(
        session_id=ctx.sessionid,
        user_id=ctx.userid,
        content="太贵是不是就不建议冲",
        history=[],
        request_context=ctx,
        message_history=[],
        turn_started_at=time.monotonic(),
        on_progress=None,
    )

    assert isinstance(reply, str)
    assert "录取概率" in reply
    assert history_store.saved is not None


def test_poc_shadow_summary_uses_current_turn_messages_only():
    from app.service import _summarize_zhiyuan_agent_poc_shadow

    current_messages = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="preview_plan_action",
                    args={"action": "remove", "filters": {"program_type": "高收费"}},
                    tool_call_id="current-call",
                )
            ]
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="preview_plan_action",
                    content=json.dumps({"next_step": "confirm"}, ensure_ascii=False),
                    tool_call_id="current-call",
                )
            ]
        ),
        ModelResponse(parts=[TextPart(content="已列出调整预览")]),
    ]
    usage = SimpleNamespace(
        tool_calls=1,
        requests=1,
        input_tokens=100,
        output_tokens=20,
        total_tokens=120,
    )

    shadow = _summarize_zhiyuan_agent_poc_shadow(
        reply="已列出调整预览",
        messages=current_messages,
        usage=usage,
        duration_ms=123,
    )

    assert shadow["firstToolNames"] == ["preview_plan_action"]
    assert shadow["toolCallNames"] == ["preview_plan_action"]
    assert shadow["nextSteps"] == ["confirm"]
    assert shadow["firstToolArgs"]["filters"] == {"program_type": "高收费"}


def test_observability_fields_include_poc_shadow():
    ctx = _poc_context()
    ctx.agent_observability["turnDecisionDurationMs"] = 12
    shadow = {"enabled": True, "status": "success", "firstToolNames": ["query_plan"]}
    setattr(ctx, "_zhiyuan_agent_poc_shadow", shadow)

    fields = _observability_timing_fields(ctx)

    assert fields["turnDecisionDurationMs"] == 12
    assert fields["zhiyuanAgentPocShadow"] == shadow


async def test_observability_fields_collect_completed_poc_shadow_task():
    ctx = _poc_context()
    shadow = {"enabled": True, "status": "success", "firstToolNames": ["query_plan"]}
    task = asyncio.create_task(asyncio.sleep(0, result=shadow))
    await task
    setattr(ctx, "_zhiyuan_agent_poc_shadow_task", task)

    fields = _observability_timing_fields(ctx)

    assert fields["zhiyuanAgentPocShadow"] == shadow
    assert getattr(ctx, "_zhiyuan_agent_poc_shadow") == shadow


@pytest.mark.asyncio
async def test_save_direct_guard_history_appends_completed_shadow_observability(mocker):
    from app.service import _save_direct_guard_history

    saved = {}

    class FakeHistoryStore:
        async def save(self, session_id, history):
            saved["session_id"] = session_id
            saved["history"] = history

    ctx = _poc_context()
    setattr(
        ctx,
        "_zhiyuan_agent_poc_shadow",
        {
            "enabled": True,
            "status": "success",
            "routingPath": "zhiyuan_agent_poc",
            "firstToolNames": ["preview_plan_action"],
            "toolCallNames": ["preview_plan_action"],
            "nextSteps": ["confirm"],
        },
    )

    await _save_direct_guard_history(
        FakeHistoryStore(),
        "session-shadow",
        [],
        "民办的不要",
        "已列出这次报考想法预览",
        model_name="needs-plan-first-guard",
        turn_event={"routingPath": "needs_plan_first_guard"},
        request_context=ctx,
        user_id="user-shadow",
    )

    assert saved["session_id"] == "session-shadow"
    route_messages = [
        message
        for message in saved["history"]
        if isinstance(message, ModelResponse)
        and str(getattr(message, "model_name", "") or "") == "route-observability"
    ]
    assert len(route_messages) == 2
    route_text = "\n".join(
        part.content
        for message in route_messages
        for part in getattr(message, "parts", []) or []
        if isinstance(part, TextPart)
    )
    assert "conversation_turn_event" in route_text
    assert "zhiyuan_agent_poc_shadow_event" in route_text
    assert "preview_plan_action" in route_text


@pytest.mark.skipif(
    os.getenv("RUN_ZHIYUAN_AGENT_POC") != "1" and os.getenv("RUN_zhiyuan_agent_POC") != "1",
    reason="requires real LLM credentials and is opt-in",
)
@pytest.mark.e2e
class TestZhiyuanAgentLLMSelection:
    async def _run_case(
        self,
        prompt: str,
        *,
        deps: RequestContext | None = None,
        message_history: list[dict[str, str]] | None = None,
    ) -> tuple[str, list[ToolCallPart], Any]:
        agent = ZhiyuanAgent(LLMClient())
        deps = deps or _poc_context()
        deps.chat_history = [*(message_history or []), {"role": "user", "content": prompt}]
        reply, _, all_messages, usage = await agent.run_with_message_deltas(
            prompt,
            message_history=message_history,
            deps=deps,
        )
        assert reply.strip()
        assert usage.tool_calls <= 2
        return reply, _tool_calls(all_messages), usage

    async def test_exclude_medical(self):
        _, calls, _ = await self._run_case("不要医学类")
        assert calls
        assert calls[0].tool_name == "preview_intent_change"
        assert _tool_args(calls[0]).get("negative")

    async def test_explore_major_fit(self):
        _, calls, _ = await self._run_case("计算机适合我吗")
        assert calls
        assert calls[0].tool_name == "explore_topic"

    async def test_query_plan_school_type(self):
        _, calls, _ = await self._run_case("方案里有没有民办")
        assert calls
        assert calls[0].tool_name == "query_plan"

    async def test_double_negation(self):
        _, calls, _ = await self._run_case("不要排除经济学类")
        assert calls
        assert calls[0].tool_name == "preview_intent_change"
        assert _tool_args(calls[0]).get("positive")
        assert _tool_args(calls[0]).get("constraint_type") != "preference"

    async def test_exclude_private_school_attribute_intent(self):
        _, calls, _ = await self._run_case("不要民办学校")
        assert calls
        assert calls[0].tool_name == "preview_intent_change"
        args = _tool_args(calls[0])
        assert args.get("intent_type") == "school"
        assert args.get("constraint_type") in {None, "exclude"}
        assert _contains_text(args.get("negative"), "民办")

    async def test_spoken_private_school_attribute_intent(self):
        _, calls, _ = await self._run_case("民办就算了")
        assert calls
        assert calls[0].tool_name == "preview_intent_change"
        args = _tool_args(calls[0])
        assert args.get("intent_type") == "school"
        assert args.get("constraint_type") in {None, "exclude"}
        assert _contains_text(args.get("negative"), "民办")

    async def test_only_keep_public_school_attribute_intent(self):
        _, calls, _ = await self._run_case("只看公办学校")
        assert calls
        assert calls[0].tool_name == "preview_intent_change"
        args = _tool_args(calls[0])
        assert args.get("intent_type") == "school"
        assert args.get("constraint_type") == "only_keep"
        assert _contains_text(args.get("positive"), "公办")

    async def test_exclude_cooperative_program_attribute_intent(self):
        _, calls, _ = await self._run_case("不要中外合作")
        assert calls
        assert calls[0].tool_name == "preview_intent_change"
        args = _tool_args(calls[0])
        assert args.get("intent_type") == "school"
        assert args.get("constraint_type") in {None, "exclude"}
        assert _contains_text(args.get("negative"), "中外合作")

    async def test_exclude_normal_school_category_attribute_intent(self):
        _, calls, _ = await self._run_case("不要师范类院校")
        assert calls
        assert calls[0].tool_name == "preview_intent_change"
        args = _tool_args(calls[0])
        assert args.get("intent_type") == "school"
        assert args.get("constraint_type") in {None, "exclude"}
        assert _contains_text(args.get("negative"), "师范")

    async def test_current_plan_private_attribute_can_be_plan_action(self):
        _, calls, _ = await self._run_case("方案里的民办不要了")
        assert calls
        assert calls[0].tool_name == "preview_plan_action"
        args = _tool_args(calls[0])
        assert args.get("action") == "remove"
        assert _contains_text(args.get("filters"), "民办")

    async def test_current_plan_cooperative_attribute_can_be_plan_action(self):
        _, calls, _ = await self._run_case("当前这些中外合作都移出去")
        assert calls
        assert calls[0].tool_name == "preview_plan_action"
        args = _tool_args(calls[0])
        assert args.get("action") == "remove"
        assert _contains_text(args.get("filters"), "中外合作")

    async def test_strongbase_school_intent_preserves_program_type(self):
        _, calls, _ = await self._run_case("清华北大复旦的强基都加进意向")
        assert calls
        assert calls[0].tool_name == "preview_intent_change"
        args = _tool_args(calls[0])
        assert args.get("intent_type") == "school"
        assert args.get("constraint_type") == "must_have"
        assert _contains_text(args.get("positive"), "强基")
        assert _contains_text(args.get("positive"), "清华")
        assert _contains_text(args.get("positive"), "北大") or _contains_text(args.get("positive"), "北京大学")
        assert _contains_text(args.get("positive"), "复旦")

    async def test_plan_pin_lock_is_unsupported_plan_action(self):
        _, calls, _ = await self._run_case("帮我把方案里第1个和第2个冲档锁定 位置不要动")
        assert calls
        assert calls[0].tool_name == "preview_plan_action"
        args = _tool_args(calls[0])
        assert args.get("action") == "pin_lock"
        assert _contains_text(args.get("targets"), "冲")

    async def test_remove_specific_position_is_plan_action(self):
        _, calls, _ = await self._run_case("第3个不要了")
        assert calls
        assert calls[0].tool_name == "preview_plan_action"
        args = _tool_args(calls[0])
        assert args.get("action") == "remove"
        assert _contains_text(args.get("targets"), "第3")

    async def test_tier_local_reorder_uses_plan_move_with_filters(self):
        _, calls, _ = await self._run_case("帮我把保底区里录取率最高的那个调到保底的第一位")
        assert calls
        assert calls[0].tool_name == "preview_plan_action"
        args = _tool_args(calls[0])
        assert args.get("action") == "move"
        assert _contains_text(args.get("filters"), "保")
        assert _contains_text(args.get("filters"), "admission")

    async def test_career_explore(self):
        _, calls, _ = await self._run_case("建议考公吗")
        assert calls
        assert calls[0].tool_name == "explore_topic"

    async def test_score_batch_policy(self):
        _, calls, _ = await self._run_case("分数和位次怎么参考")
        assert calls
        assert calls[0].tool_name == "answer_policy"

    async def test_review_current_plan(self):
        _, calls, _ = await self._run_case("审查一下当前方案")
        assert calls
        assert calls[0].tool_name == "review_plan"

    async def test_g2_review_fix_boundary_is_readonly(self):
        _, calls, _ = await self._run_case("方案里高收费或者中外合作风险大的，先看看能怎么处理，别直接动")
        assert calls
        assert calls[0].tool_name == "review_plan"
        args = _tool_args(calls[0])
        assert args.get("focus") == "tuition"
        assert args.get("generate_fix_proposals") is True

    async def test_g21_readonly_review_does_not_generate_plan(self):
        _, calls, _ = await self._run_case("现在这版强基+普通批方案合理不")
        assert calls
        assert calls[0].tool_name in {"review_plan", "query_plan"}
        assert not (calls[0].tool_name == "preview_plan_action" and _tool_args(calls[0]).get("action") == "generate")
        assert not (calls[0].tool_name == "preview_plan_action" and _tool_args(calls[0]).get("action") == "regenerate_order")

    async def test_remove_review_high_tuition(self):
        _, calls, _ = await self._run_case("把审查里的高收费项移出去")
        assert calls
        assert calls[0].tool_name == "preview_plan_action"
        assert _tool_args(calls[0]).get("review_issue_code") == "high_tuition"

    async def test_review_followup_remove_high_tuition_passes_targeting(self):
        _, calls, _ = await self._run_case(
            "那高收费的别要了",
            deps=_context_with_review(),
            message_history=[
                {"role": "user", "content": "有啥问题，咋弄"},
                {"role": "assistant", "content": "方案审查发现高收费风险和中外合作费用风险，可以先移出或替换相关项。"},
            ],
        )
        assert calls
        assert calls[0].tool_name == "preview_plan_action"
        args = _tool_args(calls[0])
        assert args.get("action") == "remove"
        assert args.get("review_issue_code") == "high_tuition" or _contains_text(args.get("filters"), "高收费")
        assert args.get("raw_user_text") == "那高收费的别要了"

    async def test_remove_review_high_tuition_private_intersection(self):
        _, calls, _ = await self._run_case("把审查里的高收费且民办的项移出去")
        assert calls
        assert calls[0].tool_name == "preview_plan_action"
        args = _tool_args(calls[0])
        assert args.get("review_issue_code") == "high_tuition"
        assert _contains_text(args.get("filters"), "民办")

    async def test_remove_review_cooperative_program(self):
        _, calls, _ = await self._run_case("把审查里的中外合作项移出去")
        assert calls
        assert calls[0].tool_name == "preview_plan_action"
        assert _tool_args(calls[0]).get("review_issue_code") == "cooperative_program"

    async def test_remove_review_admission_limit(self):
        _, calls, _ = await self._run_case("把审查里的限报项移出去")
        assert calls
        assert calls[0].tool_name == "preview_plan_action"
        assert _tool_args(calls[0]).get("action") == "remove"
        assert _tool_args(calls[0]).get("review_issue_code") == "admission_limit"

    async def test_sort_review_probability_inversion(self):
        _, calls, _ = await self._run_case("按审查里的录取率倒挂重新排序")
        assert calls
        assert calls[0].tool_name == "preview_plan_action"
        assert _tool_args(calls[0]).get("action") == "sort"
        assert _tool_args(calls[0]).get("review_issue_code") == "probability_inversion"

    async def test_regenerate_review_tier_gap(self):
        _, calls, _ = await self._run_case("按审查里的梯度问题重新调整排序")
        assert calls
        assert calls[0].tool_name == "preview_plan_action"
        assert _tool_args(calls[0]).get("action") == "regenerate_order"
        assert _tool_args(calls[0]).get("review_issue_code") == "tier_gap"

    async def test_regenerate_review_safety_guard(self):
        _, calls, _ = await self._run_case("按审查里的保底不足重新调整方案")
        assert calls
        assert calls[0].tool_name == "preview_plan_action"
        assert _tool_args(calls[0]).get("action") == "regenerate_order"
        assert _tool_args(calls[0]).get("review_issue_code") == "safety_guard"
