"""Release 4.0 Zhiyuan Agent direct-chain tests."""

from __future__ import annotations

import json
import os
import asyncio
import time
from datetime import datetime, timedelta, timezone
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
    _item_major_names,
    _plan_item_matches_intent_payload,
    _pending_command_execution_uncertain,
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


@pytest.fixture(autouse=True)
def _stub_pending_claim(mocker):
    async def claim(_session_id, state):
        claimed = dict(state or {})
        revision = int(claimed.get("_pendingRevision") or claimed.get("revision") or 1) + 1
        claimed["status"] = "applying"
        claimed["revision"] = revision
        claim_token = "claim-test-token"
        claim_expires_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        return {
            "code": 0,
            "data": {
                "pendingId": claimed.get("pendingId"),
                "revision": revision,
                "status": "applying",
                "claimToken": claim_token,
                "claimExpiresAt": claim_expires_at,
                "dataValue": claimed,
                "transitionApplied": True,
            },
        }

    tool_claim = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.claim_pending_confirmation",
        AsyncMock(side_effect=claim),
    )
    service_claim = mocker.patch(
        "app.service.claim_pending_confirmation",
        AsyncMock(side_effect=claim),
    )
    return tool_claim, service_claim


@pytest.fixture(autouse=True)
def _stub_pending_planning_command(mocker):
    async def execute(_tenant_id, _session_id, **kwargs):
        command_type = kwargs.get("command_type")
        if command_type in {"add_units", "replace_units"}:
            steps = [
                *(["ordered_units_removed"] if command_type == "replace_units" else []),
                "working_plan_items_selected",
                "ordered_plan_regenerated",
            ]
        else:
            steps = [
                *(["constraint_updated"] if kwargs.get("constraint_update") else []),
                *(["tuition_updated"] if kwargs.get("max_tuition_per_year") is not None else []),
                *(["ordered_plan_regenerated"] if kwargs.get("regenerate_ordered_plan") else []),
            ]
        return {
            "code": 0,
            "data": {
                "operationId": kwargs.get("operation_id"),
                "pendingId": kwargs.get("pending_id"),
                "commandType": command_type,
                "sourcePlanVersion": kwargs.get("expected_plan_version"),
                "resultPlanVersion": int(kwargs.get("expected_plan_version") or 0) + max(1, len(steps)),
                "completedSteps": steps,
                "replayed": False,
                "planningState": {
                    "version": int(kwargs.get("expected_plan_version") or 0) + max(1, len(steps)),
                    "orderedPlanState": {"units": [], "items": []},
                },
            },
        }

    return mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.execute_pending_planning_command",
        AsyncMock(side_effect=execute),
    )


def _load(text: str) -> dict[str, Any]:
    return json.loads(text)


def test_pending_command_running_conflict_is_treated_as_uncertain():
    assert _pending_command_execution_uncertain({"code": 40903, "msg": "planning command is already running"})
    assert not _pending_command_execution_uncertain(
        {"code": 40903, "msg": "operationId was used by another command"}
    )
    assert not _pending_command_execution_uncertain({"code": 40904, "msg": "planning version conflict"})


def test_item_unit_id_matches_backend_ordered_unit_id_from_nested_volunteer_id():
    item = {
        "schoolName": "泰山学院",
        "majorItems": [
            {"volunteerId": "37020261000734_37020262013962_37020262013962", "majorName": "数学与应用数学"}
        ],
    }

    assert _item_unit_id(item) == "37020261000734"


def test_item_unit_id_prefers_plan_school_data_id_over_volunteer_prefix():
    item = {
        "planSchoolDataId": "37020261000269_37020262005080",
        "volunteerId": "37020261000269_37020262005080_709",
    }

    assert _item_unit_id(item) == "37020261000269_37020262005080"


def test_no_plan_sandbox_summary_preserves_backend_version():
    summary = PlanningSummary(
        phase="profile_ready",
        version=1724,
        ordered_total=0,
        ordered_target_total=0,
    )

    sandbox = build_request_sandbox(session_id="no-plan-version", planning_summary=summary)

    plan_summary = sandbox.peek("plan/summary.json")
    assert plan_summary is not None
    assert plan_summary["has_plan"] is False
    assert plan_summary["phase"] == "profile_ready"
    assert plan_summary["version"] == 1724


def test_item_major_names_includes_direct_major_taxonomy_fields():
    item = {
        "majorName": "工程管理",
        "majorCategory": "管理科学与工程类",
        "majorDiscipline": "管理学",
        "majorItems": [
            {
                "majorName": "护理学",
                "majorCategory": "护理学类",
                "majorDiscipline": "医学",
            }
        ],
    }

    assert _item_major_names(item) == ["工程管理", "管理科学与工程类", "管理学", "护理学", "护理学类", "医学"]
    assert _plan_item_matches_intent_payload(item, "major", {"level1": ["管理学"]}) is True
    assert _plan_item_matches_intent_payload(item, "major", {"level2": ["护理学类"]}) is True


def test_plan_item_matches_structured_region_area_payload():
    item = {"provinceName": "广东", "cityName": "广州"}

    assert _plan_item_matches_intent_payload(item, "region", {"area": ["南方"]}) is True
    assert _plan_item_matches_intent_payload(item, "region", {"area": ["北方"]}) is False


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


def test_ordered_items_enrichment_resolves_legacy_major_identity_by_unique_names():
    response = {
        "code": 0,
        "data": {
            "version": 384,
            "orderedPlanState": {
                "items": [
                    {
                        "position": 1,
                        "volunteerId": "41020261005650_553",
                        "schoolName": "电子科技大学中山学院第101组(普通组)",
                        "majorName": "光电信息科学与工程",
                    }
                ],
                "units": [
                    {
                        "position": 1,
                        "unitId": "41020261005650",
                        "planSchoolDataId": "41020261005650",
                    }
                ],
            },
            "candidatePoolState": {
                "items": [
                    {
                        "volunteerId": "41020261005650_41020262033139",
                        "planSchoolDataId": "41020261005650",
                        "majorId": "553",
                        "schoolName": "电子科技大学中山学院第101组(普通组)",
                        "majorName": "光电信息科学与工程",
                        "schoolNature": "民办",
                        "tuitionPerYear": 32000,
                    }
                ]
            },
        },
    }

    items_file = _ordered_items_file_from_response(response)

    assert items_file["items"][0]["unitId"] == "41020261005650"
    assert items_file["items"][0]["schoolNature"] == "民办"
    assert items_file["items"][0]["tuitionPerYear"] == 32000


def test_direct_confirm_result_maps_to_pending_route_and_workspace_refresh():
    plan_result = {
        "data": {
            "action": "confirm",
            "kind": "plan_mutation",
            "action_family": "remove_units",
            "applied": True,
        }
    }
    plan_generation_result = {
        "data": {
            "action": "confirm",
            "kind": "plan_generation",
            "action_family": "regenerate_order",
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
    intent_record_only_result = {
        "data": {
            "action": "confirm",
            "kind": "intent_change",
            "action_family": "apply_selected_intents",
            "applied": True,
            "result": {"has_plan": True, "apply_to_current_plan": False, "plan_regenerated": False},
        }
    }
    intent_rebuild_failed_result = {
        "data": {
            "action": "confirm",
            "kind": "intent_change",
            "action_family": "apply_selected_intents",
            "applied": True,
            "result": {
                "has_plan": True,
                "requires_candidate_pool_rebuild": True,
                "candidate_pool_regenerated": False,
                "plan_regenerated": False,
            },
        }
    }

    assert _direct_confirm_routing_path(plan_result) == "direct_pending_plan_confirm"
    assert _direct_confirm_workspace_refresh_targets(plan_result) == ["ordered", "review"]
    assert _direct_confirm_routing_path(plan_generation_result) == "direct_pending_plan_confirm"
    assert _direct_confirm_workspace_refresh_targets(plan_generation_result) == ["ordered", "review"]
    assert _direct_confirm_routing_path(intent_result) == "direct_pending_intent_confirm"
    assert _direct_confirm_workspace_refresh_targets(intent_result) == ["ordered", "review"]
    assert _direct_confirm_workspace_refresh_targets(intent_record_only_result) == []
    assert _direct_confirm_workspace_refresh_targets(intent_rebuild_failed_result) == []


def _direct_context(*, with_plan: bool = True, pending: bool = False) -> RequestContext:
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
    ctx = _direct_context(with_plan=True)
    ctx.planning_summary.version = plan_version
    ctx.conversation_phase = ConversationPhase(
        state=(
            PhaseState.INTENT_PREVIEWING
            if str(pending_state.get("kind") or "") == "intent_change"
            else PhaseState.PLAN_PREVIEWING
        ),
        pending=PendingConfirmation(
            kind=str(pending_state.get("kind") or "plan_mutation"),
            pending_id=str(pending_state.get("pending_id") or pending_state.get("pendingId") or ""),
            action_family=str(pending_state.get("action_family") or pending_state.get("actionFamily") or ""),
            preview_summary=str(pending_state.get("summary") or ""),
            execution_payload=dict(pending_state.get("execution_payload") or {}),
            source_backend_version=int(pending_state.get("source_backend_version") or 0),
        ),
    )
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


def _prime_expanded_ordered_unit_plan(ctx: RequestContext) -> None:
    ctx.sandbox.prime(
        "plan/items.json",
        {
            "available": True,
            "items": [
                {
                    "unitId": "unit-alpha",
                    "volunteerId": "unit-alpha_001",
                    "schoolName": "第一大学",
                    "majorName": "计算机科学与技术",
                    "tier": "冲",
                    "position": 1,
                },
                {
                    "unitId": "unit-alpha",
                    "volunteerId": "unit-alpha_002",
                    "schoolName": "第一大学",
                    "majorName": "软件工程",
                    "tier": "冲",
                    "position": 2,
                },
                {
                    "unitId": "unit-alpha",
                    "volunteerId": "unit-alpha_003",
                    "schoolName": "第一大学",
                    "majorName": "网络工程",
                    "tier": "冲",
                    "position": 3,
                },
                {
                    "unitId": "unit-beta",
                    "volunteerId": "unit-beta_001",
                    "schoolName": "第二大学",
                    "majorName": "电子信息工程",
                    "tier": "稳",
                    "position": 4,
                },
                {
                    "unitId": "unit-gamma",
                    "volunteerId": "unit-gamma_001",
                    "schoolName": "第三大学",
                    "majorName": "自动化",
                    "tier": "稳",
                    "position": 5,
                },
            ],
        },
        version=12,
    )


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
    text = build_turn_context(_direct_context(with_plan=True, pending=True))

    assert "河北 550分 物理/化学/生物 男" in text
    assert "方案：45个志愿 (冲12/稳18/保15)" in text
    assert "风险：2项，提醒：3项" in text
    assert "待确认：有，类型=当前方案调整，动作=remove_units" in text
    assert "待确认内容：移出3个高收费志愿" in text
    assert "pending_resolution" in text


def test_zhiyuan_agent_instructions_require_plan_action_targeting_for_review_followups():
    text = build_zhiyuan_agent_instructions(make_run_context(request_context=_direct_context(with_plan=True)))

    assert "不要只传 action" in text
    assert "review_issue_code=\"high_tuition\"" in text
    assert "那高收费的别要了" in text
    assert "那如果我不接受稿费呢高高学费" in text
    assert "raw_user_text" in text
    assert "那重新审查一下" in text
    assert "必须再次调用 review_plan" in text
    assert "显式报考要求 + 当前方案同步处理" in text
    assert "不要英语相关专业，当前方案里有的话也删掉" in text
    assert "apply_to_current_plan=True" in text
    assert "候选不够也要直接说" in text
    assert "review_plan(focus=\"tier_balance\", generate_fix_proposals=True)" in text
    assert "先给我看预览" in text
    assert "地域集合也是地域要求" in text
    assert "positive={\"area\":[\"南方\"]}" in text
    assert "negative={\"area\":[\"北方\"]}" in text
    assert "倾向A和B，但Y不要" in text
    assert "我倾向会计学和审计学，但土木工程不要" in text
    assert "positive={\"major\":[\"会计学\",\"审计学\"]}" in text
    assert "negative={\"major\":[\"土木工程\"]}" in text


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
    result = _load(await read_state(make_run_context(request_context=_direct_context()), "score"))

    assert result["next_step"] == "respond"
    assert result["data"]["province"] == "河北"
    assert result["data"]["total_score"] == 550
    assert "550分" in result["message"]


async def test_read_plan_summary_with_plan():
    result = _load(await read_state(make_run_context(request_context=_direct_context()), "plan/summary"))

    assert result["next_step"] == "respond"
    assert result["data"]["has_plan"] is True
    assert result["data"]["ordered_total"] == 45
    assert result["data"]["tier_counts"] == {"冲": 12, "稳": 18, "保": 15}


async def test_read_plan_summary_no_plan():
    result = _load(await read_state(make_run_context(request_context=_direct_context(with_plan=False)), "plan/summary"))

    assert result["next_step"] == "respond"
    assert result["data"]["has_plan"] is False
    assert "还没有生成正式方案" in result["message"]


async def test_explore_career_topic():
    result = _load(
        await explore_topic(
            make_run_context(request_context=_direct_context()),
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
            make_run_context(request_context=_direct_context()),
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
            make_run_context(request_context=_direct_context()),
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
            make_run_context(request_context=_direct_context()),
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
            make_run_context(request_context=_direct_context()),
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
            make_run_context(request_context=_direct_context()),
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
            make_run_context(request_context=_direct_context()),
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
            make_run_context(request_context=_direct_context()),
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
            make_run_context(request_context=_direct_context()),
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
            make_run_context(request_context=_direct_context()),
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
            make_run_context(request_context=_direct_context()),
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
        "app.zhiyuan_agent.tools._request_policy_source_search",
        AsyncMock(
            return_value={
                "status": "ok",
                "results": [
                    {
                        "title": "河北省教育考试院投档规则",
                        "url": "https://example.edu/rule",
                        "snippet": "平行志愿按位次和志愿顺序投档。",
                    }
                ],
            }
        ),
    )

    result = _load(
        await answer_policy(
            make_run_context(request_context=_direct_context()),
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
    ctx = _direct_context(with_plan=True)
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


def _mock_candidate_pool_query(mocker, items: list[dict[str, Any]]) -> AsyncMock:
    return mocker.patch(
        "app.zhiyuan_agent.sandbox.internal_client.query_planning_candidate_pool",
        AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "version": 12,
                    "candidatePoolState": {
                        "summary": {"unitTotal": len(items)},
                        "items": items,
                    },
                },
            }
        ),
    )


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
    ctx = _direct_context(with_plan=True)
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
    assert "替换高收费志愿" in result["message"]
    proposal_mock.assert_awaited_once_with(1, ctx.sessionid)


async def test_review_plan_career_fit_includes_structured_career_slots(mocker):
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.run_planning_review",
        AsyncMock(return_value={"code": 0, "data": {}}),
    )
    ctx = _context_with_review()

    result = _load(
        await review_plan(
            make_run_context(request_context=ctx),
            focus="career_fit",
            career_slots=["system_public_service", "further_study"],
            force_refresh=False,
        )
    )

    assert result["next_step"] == "respond"
    assert result["data"]["career_slots"] == ["system_public_service", "further_study"]
    assert result["data"]["career_labels"] == ["体制内/考公导向", "深造发展导向"]
    assert "当前方案承接" in result["message"]
    assert "体制内/考公导向" in result["message"]
    assert "深造发展导向" in result["message"]
    assert "只读审查" in result["message"]
    assert result["data"]["state_mutation"] is False
    assert result["data"]["plan_mutation"] is False


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

    result = _load(await review_plan(make_run_context(request_context=_direct_context(with_plan=False))))

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
            make_run_context(request_context=_direct_context()),
            intent_type="major",
            negative={"level1": ["医学"]},
        )
    )

    assert result["next_step"] == "confirm", result
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
            make_run_context(request_context=_direct_context()),
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


async def test_preview_region_area_positive_and_negative_pending(mocker):
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
            make_run_context(request_context=_direct_context()),
            intent_type="region",
            positive={"area": ["南方"]},
            negative={"area": ["北方"]},
            constraint_type="must_have",
            raw_user_text="孩子就想去南方，北方先别考虑",
            semantic_requirements=[
                {
                    "domain": "region",
                    "side": "positive",
                    "strength": "explicit",
                    "key": "area",
                    "values": ["南方"],
                    "raw_span": "想去南方",
                },
                {
                    "domain": "region",
                    "side": "negative",
                    "strength": "explicit",
                    "key": "area",
                    "values": ["北方"],
                    "raw_span": "北方先别考虑",
                },
            ],
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["normalized"]["positive"]["area"] == ["南方"]
    assert result["data"]["normalized"]["negative"]["area"] == ["北方"]
    assert "地域要求" in result["message"]
    assert "南方" in result["message"]
    assert "北方" in result["message"]
    saved_state = save_mock.await_args.args[1]
    assert saved_state["summary"] == "地域要求：要：南方；不要：北方"
    assert saved_state["executionPayload"]["merged"] == {
        "city_intents": {"area": ["南方"], "negative_area": ["北方"]}
    }


async def test_preview_region_area_region_alias_creates_canonical_pending(mocker):
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
            make_run_context(request_context=_direct_context()),
            intent_type="region",
            positive={"area_region": ["江浙沪"]},
            negative={"area_region": ["非江浙沪地区"]},
            constraint_type="only_keep",
            raw_user_text="江浙沪就行，其他地方先别看了",
            semantic_requirements=[
                {
                    "domain": "region",
                    "side": "positive",
                    "strength": "explicit",
                    "key": "area_region",
                    "values": ["江浙沪"],
                    "raw_span": "江浙沪就行",
                },
                {
                    "domain": "region",
                    "side": "negative",
                    "strength": "explicit",
                    "key": "area_region",
                    "values": ["非江浙沪地区"],
                    "raw_span": "其他地方先别看了",
                },
            ],
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["normalized"]["positive"]["area"] == ["长三角"]
    assert result["data"]["normalized"]["negative"]["area"] == []
    assert "长三角" in result["message"]
    saved_state = save_mock.await_args.args[1]
    assert saved_state["executionPayload"]["merged"]["city_intents"] == {"area": ["长三角"]}
    assert "negative_area" not in saved_state["executionPayload"]["merged"]["city_intents"]


async def test_preview_region_area_alias_semantic_values_are_canonicalized(mocker):
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
            make_run_context(request_context=_direct_context()),
            intent_type="region",
            positive={"area": ["江浙沪"]},
            constraint_type="only_keep",
            raw_user_text="江浙沪就行，其他地方先别看了",
            semantic_requirements=[
                {
                    "domain": "region",
                    "side": "positive",
                    "strength": "explicit",
                    "key": "area",
                    "values": ["江浙沪"],
                    "raw_span": "江浙沪就行",
                },
                {
                    "domain": "region",
                    "side": "negative",
                    "strength": "explicit",
                    "key": "area",
                    "values": ["其他地方"],
                    "raw_span": "其他地方先别看了",
                },
            ],
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["normalized"]["positive"]["area"] == ["长三角"]
    assert result["data"]["normalized"]["negative"]["area"] == []
    saved_state = save_mock.await_args.args[1]
    assert saved_state["executionPayload"]["merged"]["city_intents"] == {"area": ["长三角"]}


async def test_preview_region_first_tier_area_creates_pending(mocker):
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
            make_run_context(request_context=_direct_context()),
            intent_type="region",
            positive={"area": ["北上广深"]},
            constraint_type="only_keep",
            raw_user_text="北上广深就行，不往其他城市放了",
            semantic_requirements=[
                {
                    "domain": "region",
                    "side": "positive",
                    "strength": "explicit",
                    "key": "area",
                    "values": ["北上广深"],
                    "raw_span": "北上广深就行",
                },
                {
                    "domain": "region",
                    "side": "negative",
                    "strength": "explicit",
                    "key": "area",
                    "values": ["其他城市"],
                    "raw_span": "不往其他城市放了",
                },
            ],
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["normalized"]["positive"]["area"] == ["北上广深"]
    assert result["data"]["normalized"]["negative"]["area"] == []
    saved_state = save_mock.await_args.args[1]
    assert saved_state["executionPayload"]["merged"]["city_intents"] == {"area": ["北上广深"]}




async def test_preview_region_remote_area_creates_pending(mocker):
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
            make_run_context(request_context=_direct_context()),
            intent_type="region",
            negative={"area": ["偏远地区"]},
            constraint_type="exclude",
            raw_user_text="省外可以，但太偏的地方不想去",
            semantic_requirements=[
                {
                    "domain": "region",
                    "side": "positive",
                    "strength": "reference",
                    "key": "area",
                    "values": ["省外"],
                    "raw_span": "省外可以",
                },
                {
                    "domain": "region",
                    "side": "negative",
                    "strength": "explicit",
                    "key": "area",
                    "values": ["偏远地区"],
                    "raw_span": "太偏的地方不想去",
                },
            ],
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["normalized"]["positive"]["area"] == []
    assert result["data"]["normalized"]["negative"]["area"] == ["偏远地区"]
    assert "偏远地区" in result["message"]
    saved_state = save_mock.await_args.args[1]
    assert saved_state["summary"] == "地域要求：不要：偏远地区"
    assert saved_state["executionPayload"]["merged"] == {
        "city_intents": {"negative_area": ["偏远地区"]}
    }

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
            make_run_context(request_context=_direct_context()),
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


async def test_preview_intent_preserves_user_text_major_alias_after_model_canonicalizes(mocker):
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
            make_run_context(request_context=_direct_context()),
            intent_type="major",
            positive={"level2": ["电气类", "大气科学类"]},
            constraint_type="only_keep",
            raw_user_text="只要电气和气象，其他方向都不要",
            semantic_requirements=[
                {
                    "domain": "major",
                    "side": "positive",
                    "strength": "explicit",
                    "key": "level2",
                    "values": ["电气类", "大气科学类"],
                    "raw_span": "只要电气和气象",
                }
            ],
        )
    )

    assert result["next_step"] == "confirm"
    assert "电气（电气类）" in result["message"]
    assert "气象（大气科学类）" in result["message"]
    saved_state = save_mock.await_args.args[1]
    assert "气象（大气科学类）" in saved_state["summary"]
    assert saved_state["executionPayload"]["merged"]["_display_aliases"] == {
        "电气类": "电气",
        "大气科学类": "气象",
    }


async def test_preview_intent_merges_same_turn_positive_and_negative_pending(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.simulate_plan_diff",
        AsyncMock(return_value={"code": 500}),
    )
    ctx = _direct_context()

    first = _load(
        await preview_intent_change(
            make_run_context(request_context=ctx),
            intent_type="major",
            positive={"major": ["生物医学工程", "智能医学工程"]},
            constraint_type="must_have",
        )
    )
    second = _load(
        await preview_intent_change(
            make_run_context(request_context=ctx),
            intent_type="major",
            negative={"major": ["临床医学", "口腔医学"]},
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
            make_run_context(request_context=_direct_context()),
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
            make_run_context(request_context=_direct_context()),
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


async def test_preview_intent_major_key_resolves_to_specific_major_level(mocker):
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
            make_run_context(request_context=_direct_context()),
            intent_type="major",
            positive={"major": ["法学"]},
            constraint_type="must_have",
            raw_user_text="方案里必须有法学，其他专业可以先保留",
            semantic_requirements=[
                {
                    "domain": "major",
                    "side": "positive",
                    "strength": "explicit",
                    "key": "major",
                    "values": ["法学"],
                    "raw_span": "必须有法学",
                }
            ],
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["normalized"]["positive"]["level1"] == []
    assert result["data"]["normalized"]["positive"]["level3"] == ["法学"]
    assert result["data"]["merged"]["major_intents"] == {"level3": ["法学"]}
    saved_state = save_mock.await_args.args[1]
    assert saved_state["executionPayload"]["merged"]["major_intents"] == {"level3": ["法学"]}


async def test_preview_intent_major_semantic_completion_accepts_refined_specific_major(mocker):
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
            make_run_context(request_context=_direct_context()),
            intent_type="major",
            positive={"level2": ["法学类"]},
            constraint_type="must_have",
            raw_user_text="方案里必须有法学，其他专业可以先保留",
            semantic_requirements=[
                {
                    "domain": "major",
                    "side": "positive",
                    "strength": "explicit",
                    "key": "level2",
                    "values": ["法学类"],
                    "raw_span": "方案里必须有法学",
                }
            ],
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["normalized"]["positive"]["level2"] == []
    assert result["data"]["normalized"]["positive"]["level3"] == ["法学"]
    assert result["data"]["merged"]["major_intents"] == {"level3": ["法学"]}
    saved_state = save_mock.await_args.args[1]
    assert saved_state["executionPayload"]["merged"]["major_intents"] == {"level3": ["法学"]}


async def test_preview_intent_major_semantic_completion_accepts_parent_level2_covering_child(mocker):
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
            make_run_context(request_context=_direct_context()),
            intent_type="major",
            negative={"level2": ["外国语言文学类"]},
            constraint_type="exclude",
            apply_to_current_plan=True,
            raw_user_text="不要英语相关专业，当前方案里有的话也删掉",
            semantic_requirements=[
                {
                    "domain": "major",
                    "side": "negative",
                    "strength": "explicit",
                    "key": "level2",
                    "values": ["外国语言文学类"],
                    "raw_span": "不要英语相关专业",
                }
            ],
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["normalized"]["negative"]["level2"] == ["外国语言文学类"]
    assert result["data"]["merged"]["major_intents"] == {"negative_level2": ["外国语言文学类"]}
    saved_state = save_mock.await_args.args[1]
    assert saved_state["executionPayload"]["merged"]["major_intents"] == {
        "negative_level2": ["外国语言文学类"]
    }


async def test_preview_intent_accepts_major_duration_as_tag_alias(mocker):
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
            make_run_context(request_context=_direct_context()),
            intent_type="major",
            negative={"duration": ["五年制"]},
            constraint_type="exclude",
            raw_user_text="五年制的不要了",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["normalized"]["negative"]["major_tag"] == ["学制：5年"]
    assert result["data"]["merged"]["major_intents"] == {"negative_major_tag": ["学制：5年"]}
    assert "学制：5年" in result["message"]
    saved_state = save_mock.await_args.args[1]
    assert saved_state["executionPayload"]["merged"]["major_intents"] == {
        "negative_major_tag": ["学制：5年"]
    }


async def test_preview_intent_requires_model_retry_for_missing_major_tag_from_semantic_requirements(mocker):
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
            make_run_context(request_context=_direct_context()),
            intent_type="major",
            negative={"level1": ["管理学"]},
            constraint_type="exclude",
            raw_user_text="管理学和五年制的都别要了",
            semantic_requirements=[
                {
                    "domain": "major",
                    "side": "negative",
                    "strength": "explicit",
                    "key": "level1",
                    "values": ["管理学"],
                    "raw_span": "管理学",
                },
                {
                    "domain": "major",
                    "side": "negative",
                    "strength": "explicit",
                    "key": "major_tag",
                    "values": ["五年制"],
                    "raw_span": "五年制的都别要了",
                },
            ],
        )
    )

    assert result["next_step"] == "continue"
    assert result["data"]["reason"] == "intent_change_requires_attribute_completion"
    assert result["data"]["normalized"]["negative"]["level1"] == ["管理学"]
    assert result["data"]["merged"]["major_intents"] == {"negative_level1": ["管理学"]}
    assert result["data"]["missing_attributes"] == [
        {
            "domain": "major",
            "side": "negative",
            "key": "major_tag",
            "values": ["学制：5年"],
            "target_payload_path": "negative.major_tag",
        }
    ]
    assert result["data"]["current_user_text"] == "管理学和五年制的都别要了"
    save_mock.assert_not_awaited()


async def test_preview_intent_requires_model_retry_for_missing_cross_domain_school_attribute_from_semantics(mocker):
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
            make_run_context(request_context=_direct_context()),
            intent_type="region",
            negative={"province": ["山东"]},
            constraint_type="exclude",
            raw_user_text="山东别去，民办也算了",
            semantic_requirements=[
                {
                    "domain": "region",
                    "side": "negative",
                    "strength": "explicit",
                    "key": "province",
                    "values": ["山东"],
                    "raw_span": "山东别去",
                },
                {
                    "domain": "school",
                    "side": "negative",
                    "strength": "explicit",
                    "key": "school_nature",
                    "values": ["民办"],
                    "raw_span": "民办也算了",
                },
            ],
        )
    )

    assert result["next_step"] == "continue"
    assert result["data"]["reason"] == "intent_change_requires_attribute_completion"
    assert result["data"]["merged"]["city_intents"] == {"negative_province": ["山东"]}
    assert "school_intents" not in result["data"]["merged"]
    assert result["data"]["missing_attributes"] == [
        {
            "domain": "school",
            "side": "negative",
            "key": "school_nature",
            "values": ["民办"],
            "target_payload_path": "negative.school_nature",
        }
    ]
    assert result["data"]["current_user_text"] == "山东别去，民办也算了"
    save_mock.assert_not_awaited()


async def test_preview_intent_requires_model_retry_for_missing_region_payload_from_semantics(mocker):
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
            make_run_context(request_context=_direct_context()),
            intent_type="region",
            constraint_type="only_keep",
            raw_user_text="北京先不要了，只看天津和河北",
            semantic_requirements=[
                {
                    "domain": "region",
                    "side": "negative",
                    "strength": "explicit",
                    "key": "province",
                    "values": ["北京"],
                    "raw_span": "北京先不要了",
                },
                {
                    "domain": "region",
                    "side": "positive",
                    "strength": "explicit",
                    "key": "province",
                    "values": ["天津", "河北"],
                    "raw_span": "只看天津和河北",
                },
            ],
        )
    )

    assert result["next_step"] == "continue"
    assert result["data"]["reason"] == "intent_change_requires_attribute_completion"
    assert result["data"]["missing_attributes"] == [
        {
            "domain": "region",
            "side": "negative",
            "key": "province",
            "values": ["北京"],
            "target_payload_path": "negative.province",
        },
        {
            "domain": "region",
            "side": "positive",
            "key": "province",
            "values": ["天津", "河北"],
            "target_payload_path": "positive.province",
        },
    ]
    assert result["data"]["current_user_text"] == "北京先不要了，只看天津和河北"
    save_mock.assert_not_awaited()


async def test_preview_intent_reference_major_direction_is_not_completed_as_school_attribute(mocker):
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
            make_run_context(request_context=_direct_context()),
            intent_type="major",
            negative={"major": ["护理学"], "level2": ["中西医结合类"]},
            constraint_type="exclude",
            raw_user_text="财经类可以优先，但是护理和中西医结合不要",
            semantic_requirements=[
                {
                    "domain": "major",
                    "side": "positive",
                    "strength": "reference",
                    "key": "level2",
                    "values": ["财经类"],
                    "raw_span": "财经类可以优先",
                },
                {
                    "domain": "major",
                    "side": "negative",
                    "strength": "explicit",
                    "key": "major",
                    "values": ["护理学"],
                    "raw_span": "护理不要",
                },
                {
                    "domain": "major",
                    "side": "negative",
                    "strength": "explicit",
                    "key": "level2",
                    "values": ["中西医结合类"],
                    "raw_span": "中西医结合不要",
                },
            ],
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["merged"]["major_intents"] == {
        "negative_level2": ["中西医结合类"],
        "negative_level3": ["护理学"],
    }
    assert "school_intents" not in result["data"]["merged"]
    assert "财经" not in result["message"]
    save_mock.assert_awaited_once()


async def test_preview_intent_reference_only_semantic_requirements_do_not_create_pending(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    simulate_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.simulate_plan_diff",
        AsyncMock(return_value={"code": 500}),
    )

    result = _load(
        await preview_intent_change(
            make_run_context(request_context=_direct_context()),
            intent_type="school",
            raw_user_text="天津商业大学和河北经贸大学先记为重点关注学校，后面生成方案时优先考虑",
            semantic_requirements=[
                {
                    "domain": "school",
                    "side": "positive",
                    "strength": "reference",
                    "key": "schools",
                    "values": ["天津商业大学", "河北经贸大学"],
                    "raw_span": "重点关注学校",
                }
            ],
        )
    )

    assert result["next_step"] == "respond"
    assert result["data"]["reason"] == "reference_only_semantic_requirements"
    assert result["data"]["pending_created"] is False
    assert "院校参考：天津商业大学、河北经贸大学" in result["message"]
    assert "没有识别到明确" not in result["message"]
    save_mock.assert_not_awaited()
    simulate_mock.assert_not_awaited()


async def test_preview_intent_accepts_structured_cross_domain_school_attribute(mocker):
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
            make_run_context(request_context=_direct_context()),
            intent_type="region",
            negative={"province": ["山东"], "school_nature": ["民办"]},
            constraint_type="exclude",
            raw_user_text="山东别去，民办也算了",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["merged"]["city_intents"] == {"negative_province": ["山东"]}
    assert result["data"]["merged"]["school_intents"] == {"negative_school_nature": ["民办"]}
    assert "山东" in result["message"]
    assert "民办" in result["message"]
    saved_state = save_mock.await_args.args[1]
    assert saved_state["executionPayload"]["merged"]["city_intents"] == {"negative_province": ["山东"]}
    assert saved_state["executionPayload"]["merged"]["school_intents"] == {"negative_school_nature": ["民办"]}


async def test_preview_intent_does_not_duplicate_shared_program_type_across_domains(mocker):
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
            make_run_context(request_context=_direct_context()),
            intent_type="school",
            negative={"program_type": ["中外合作"]},
            constraint_type="exclude",
            raw_user_text="中外合作算了吧",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["merged"]["school_intents"] == {"negative_program_type": ["中外合作"]}
    assert "major_intents" not in result["data"]["merged"]
    assert "专业要求" not in result["message"]
    saved_state = save_mock.await_args.args[1]
    assert saved_state["executionPayload"]["merged"]["school_intents"] == {
        "negative_program_type": ["中外合作"]
    }
    assert "major_intents" not in saved_state["executionPayload"]["merged"]


async def test_preview_intent_rejects_empty_payload_without_pending(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    simulate_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.simulate_plan_diff",
        AsyncMock(return_value={"code": 500}),
    )

    result = _load(
        await preview_intent_change(
            make_run_context(request_context=_direct_context()),
            intent_type="major",
            negative={"unknown_field": ["未知项"]},
            constraint_type="exclude",
            raw_user_text="未知项的不要了",
            semantic_requirements=[
                {
                    "domain": "major",
                    "side": "negative",
                    "strength": "explicit",
                    "key": "unknown_field",
                    "values": ["未知项"],
                    "raw_span": "未知项的不要了",
                }
            ],
        )
    )

    assert result["next_step"] == "clarify"
    assert result["data"]["pending_created"] is False
    assert result["data"]["requires_confirmation"] is False
    assert result["data"]["reason"] == "empty_intent_payload"
    assert "没有识别到明确的报考要求" in result["message"]
    save_mock.assert_not_awaited()
    simulate_mock.assert_not_awaited()


async def test_preview_intent_requires_semantic_requirements_before_empty_payload_response(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    simulate_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.simulate_plan_diff",
        AsyncMock(return_value={"code": 500}),
    )

    result = _load(
        await preview_intent_change(
            make_run_context(request_context=_direct_context()),
            intent_type="school",
            raw_user_text="天津商业大学和河北经贸大学先记为重点关注学校，后面生成方案时优先考虑",
        )
    )

    assert result["next_step"] == "continue"
    assert result["data"]["reason"] == "intent_change_requires_semantic_requirements"
    assert result["data"]["retry_required_fields"] == ["semantic_requirements", "positive", "negative"]
    assert "semantic_requirements" in result["message"]
    save_mock.assert_not_awaited()
    simulate_mock.assert_not_awaited()


async def test_preview_intent_refines_broad_major_display_from_latest_user_text(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.simulate_plan_diff",
        AsyncMock(return_value={"code": 500}),
    )
    ctx = _direct_context()
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
    ctx = _direct_context()
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


async def test_preview_intent_requires_model_retry_when_semantic_negative_missing_payload(mocker):
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
            make_run_context(request_context=_direct_context()),
            intent_type="major",
            positive={"majorList": ["生物医学工程", "智能医学工程"]},
            constraint_type="must_have",
            raw_user_text="把生物医学工程和智能医学工程加意向 排除临床医学和口腔",
            semantic_requirements=[
                {
                    "domain": "major",
                    "side": "positive",
                    "strength": "explicit",
                    "key": "major",
                    "values": ["生物医学工程", "智能医学工程"],
                    "raw_span": "把生物医学工程和智能医学工程加意向",
                },
                {
                    "domain": "major",
                    "side": "negative",
                    "strength": "explicit",
                    "key": "major",
                    "values": ["临床医学", "口腔"],
                    "raw_span": "排除临床医学和口腔",
                },
            ],
        )
    )

    assert result["next_step"] == "continue"
    assert result["data"]["reason"] == "intent_change_requires_attribute_completion"
    assert result["data"]["normalized"]["positive"]["level3"] == ["生物医学工程", "智能医学工程"]
    assert result["data"]["normalized"]["negative"]["level3"] == []
    assert result["data"]["merged"]["major_intents"] == {
        "level3": ["生物医学工程", "智能医学工程"]
    }
    assert result["data"]["missing_attributes"] == [
        {
            "domain": "major",
            "side": "negative",
            "key": "major",
            "values": ["临床医学", "口腔医学"],
            "target_payload_path": "negative.major",
        }
    ]
    save_mock.assert_not_awaited()


async def test_preview_intent_creates_structured_pending_payload(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.simulate_plan_diff",
        AsyncMock(return_value={"code": 500}),
    )
    ctx = _direct_context()

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
    ctx = _direct_context()
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
    ctx = _direct_context()

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
            make_run_context(request_context=_direct_context()),
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
            make_run_context(request_context=_direct_context()),
            intent_type="major",
            positive={"items": ["计算机"]},
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
            make_run_context(request_context=_direct_context()),
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
            make_run_context(request_context=_direct_context()),
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


async def test_preview_intent_can_record_requirement_without_current_plan_apply(mocker):
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
            make_run_context(request_context=_direct_context()),
            intent_type="region",
            negative={"province": ["山东"]},
            constraint_type="exclude",
            apply_to_current_plan=False,
            raw_user_text="排除山东，先不替换",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["apply_to_current_plan"] is False
    assert "这次不改当前方案" in result["message"]
    saved_state = save_mock.await_args.args[1]
    assert saved_state["executionPayload"]["applyToCurrentPlan"] is False
    assert saved_state["executionPayload"]["selectedData"]["applyToCurrentPlan"] is False


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
            make_run_context(request_context=_direct_context()),
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
            make_run_context(request_context=_direct_context()),
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


async def test_preview_tuition_budget_creates_independent_requirement_pending(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    simulate_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.simulate_plan_diff",
        AsyncMock(return_value={"code": 500}),
    )

    result = _load(
        await preview_intent_change(
            make_run_context(request_context=_direct_context()),
            intent_type="tuition_budget",
            positive={"max_tuition_per_year": 20000},
            constraint_type="only_keep",
            raw_user_text="太贵的学校别放了，学费最好控制在两万以内",
            semantic_requirements=[
                {
                    "domain": "tuition_budget",
                    "side": "positive",
                    "strength": "explicit",
                    "key": "max_tuition_per_year",
                    "values": ["20000"],
                    "raw_span": "学费最好控制在两万以内",
                }
            ],
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["normalized"]["positive"]["max_tuition_per_year"] == [20000]
    assert result["data"]["merged"] == {"tuition_budget": {"max_tuition_per_year": [20000]}}
    assert result["data"]["plan_impact"]["affected_count"] == 1
    assert "学费预算：每年不超过 20000 元" in result["message"]
    saved_state = save_mock.await_args.args[1]
    assert saved_state["executionPayload"]["merged"] == {"tuition_budget": {"max_tuition_per_year": [20000]}}
    assert saved_state["executionPayload"]["selectedData"]["selected"] == [
        {"tuition_budget": {"max_tuition_per_year": [20000]}}
    ]
    simulate_mock.assert_not_awaited()


async def test_confirm_pending_applies_school_attribute_constraint(mocker, _stub_pending_planning_command):
    update_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.update_planning_constraint_state",
        AsyncMock(return_value={"code": 0}),
    )
    ordered_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.generate_planning_ordered_plan",
        AsyncMock(return_value={"code": 0}),
    )
    candidate_pool_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.generate_planning_candidate_pool",
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
    assert result["data"]["result"]["requires_candidate_pool_rebuild"] is False
    assert result["data"]["result"]["candidate_pool_regenerated"] is False
    assert result["data"]["result"]["plan_regenerated"] is True
    assert "重新调整" in result["message"]
    assert "约束" not in result["message"]
    assert _stub_pending_planning_command.await_args.kwargs["constraint_update"] == {
        "intentMode": "constraint",
        "schoolPreferences": {"positive": [], "negative": ["院校性质:民办"]},
    }
    assert _stub_pending_planning_command.await_args.kwargs["regenerate_ordered_plan"] is True
    update_mock.assert_not_awaited()
    candidate_pool_mock.assert_not_awaited()
    ordered_mock.assert_not_awaited()


async def test_confirm_pending_applies_tuition_budget_without_old_constraint_state(mocker, _stub_pending_planning_command):
    update_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.update_planning_constraint_state",
        AsyncMock(return_value={"code": 0}),
    )
    tuition_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.update_session_tuition_range",
        AsyncMock(return_value={"code": 0, "data": True}),
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
            "pending_id": "pending-tuition-budget",
            "kind": "intent_change",
            "action_family": "apply_selected_intents",
            "summary": "学费预算：每年不超过 20000 元",
            "source_backend_version": 12,
            "execution_payload": {
                "merged": {"tuition_budget": {"max_tuition_per_year": [20000]}},
                "intentMode": "constraint",
                "constraintIntentType": "only_keep",
            },
            "raw": {
                "pendingId": "pending-tuition-budget",
                "kind": "intent_change",
                "actionFamily": "apply_selected_intents",
                "status": "active",
                "sourceBackendVersion": 12,
            },
        }
    )

    result = _load(await confirm_pending(make_run_context(request_context=ctx), action="confirm"))

    assert result["data"]["applied"] is True
    assert result["data"]["result"]["constraint_state_applied"] is True
    assert result["data"]["result"]["tuition_budget_applied"] is True
    assert result["data"]["result"]["plan_regenerated"] is True
    assert "重新调整" in result["message"]
    update_mock.assert_not_awaited()
    command_args = _stub_pending_planning_command.await_args.kwargs
    assert command_args["constraint_update"] is None
    assert command_args["min_tuition_per_year"] == 0
    assert command_args["max_tuition_per_year"] == 20000
    tuition_mock.assert_not_awaited()
    ordered_mock.assert_not_awaited()


async def test_confirm_pending_intent_reports_when_excluded_items_remain(mocker, _stub_pending_planning_command):
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.update_planning_constraint_state",
        AsyncMock(return_value={"code": 0}),
    )
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.generate_planning_ordered_plan",
        AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "version": 13,
                    "orderedPlanState": {
                        "items": [
                            {
                                "unitId": "unit-nanfang",
                                "volunteerId": "unit-nanfang_001",
                                "schoolName": "广州南方学院",
                                "majorName": "软件工程",
                                "schoolNature": "民办",
                                "tier": "稳",
                                "position": 18,
                            }
                        ],
                        "units": [
                            {
                                "unitId": "unit-nanfang",
                                "volunteerId": "unit-nanfang_001",
                                "schoolName": "广州南方学院",
                                "schoolNature": "民办",
                            }
                        ],
                    },
                },
            }
        ),
    )
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    _stub_pending_planning_command.side_effect = None
    _stub_pending_planning_command.return_value = {
        "code": 0,
        "data": {
            "operationId": "op-remain",
            "completedSteps": ["constraint_updated", "ordered_plan_regenerated"],
            "replayed": False,
            "planningState": {
                "version": 14,
                "orderedPlanState": {
                    "items": [{
                        "unitId": "unit-nanfang",
                        "volunteerId": "unit-nanfang_001",
                        "schoolName": "广州南方学院",
                        "majorName": "软件工程",
                        "schoolNature": "民办",
                        "tier": "稳",
                        "position": 18,
                    }],
                    "units": [{
                        "unitId": "unit-nanfang",
                        "volunteerId": "unit-nanfang_001",
                        "schoolName": "广州南方学院",
                        "schoolNature": "民办",
                    }],
                },
            },
        },
    }
    ctx = _context_with_backend_pending(
        {
            "active": True,
            "pending_id": "pending-school-attr-remain",
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
                "pendingId": "pending-school-attr-remain",
                "kind": "intent_change",
                "actionFamily": "apply_selected_intents",
                "status": "active",
                "sourceBackendVersion": 12,
            },
        }
    )

    result = _load(await confirm_pending(make_run_context(request_context=ctx), action="confirm"))

    assert result["data"]["applied"] is True
    assert result["data"]["result"]["ordered_plan_diff"]["passed"] is False
    assert result["data"]["result"]["ordered_plan_diff"]["reason"] == "excluded_intent_items_still_present"
    assert "仍有不符合要求" in result["message"]
    assert "并按新要求重新调整" not in result["message"]
    saved_state = save_mock.await_args.args[1]
    assert saved_state["status"] == "applied"
    assert saved_state["resultData"]["ordered_plan_diff"]["remaining_count"] == 1


async def test_confirm_pending_can_record_requirement_without_current_plan_apply(mocker, _stub_pending_planning_command):
    update_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.update_planning_constraint_state",
        AsyncMock(return_value={"code": 0}),
    )
    candidate_pool_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.generate_planning_candidate_pool",
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
            "pending_id": "pending-region-deferred",
            "kind": "intent_change",
            "action_family": "apply_selected_intents",
            "summary": "排除山东",
            "source_backend_version": 12,
            "execution_payload": {
                "merged": {"city_intents": {"negative_province": ["山东"]}},
                "intentMode": "constraint",
                "constraintIntentType": "exclude",
                "applyToCurrentPlan": True,
            },
            "raw": {
                "pendingId": "pending-region-deferred",
                "kind": "intent_change",
                "actionFamily": "apply_selected_intents",
                "status": "active",
                "sourceBackendVersion": 12,
            },
        }
    )

    result = _load(
        await confirm_pending(
            make_run_context(request_context=ctx),
            action="confirm",
            apply_to_current_plan=False,
        )
    )

    assert result["data"]["applied"] is True
    assert result["data"]["result"]["apply_to_current_plan"] is False
    assert result["data"]["result"]["requires_candidate_pool_rebuild"] is False
    assert result["data"]["result"]["candidate_pool_regenerated"] is False
    assert result["data"]["result"]["plan_regenerated"] is False
    assert "这次先不改当前方案" in result["message"]
    assert _stub_pending_planning_command.await_args.kwargs["constraint_update"] == {
        "intentMode": "constraint",
        "regionPreferences": {"positive": [], "negative": ["山东"]},
    }
    assert _stub_pending_planning_command.await_args.kwargs["regenerate_ordered_plan"] is False
    update_mock.assert_not_awaited()
    candidate_pool_mock.assert_not_awaited()
    ordered_mock.assert_not_awaited()


async def test_confirm_pending_applies_strongbase_program_type_constraint(mocker, _stub_pending_planning_command):
    update_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.update_planning_constraint_state",
        AsyncMock(return_value={"code": 0}),
    )
    ordered_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.generate_planning_ordered_plan",
        AsyncMock(return_value={"code": 0}),
    )
    candidate_pool_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.generate_planning_candidate_pool",
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
    assert result["data"]["result"]["requires_candidate_pool_rebuild"] is False
    assert result["data"]["result"]["candidate_pool_regenerated"] is False
    assert result["data"]["result"]["plan_regenerated"] is True
    assert _stub_pending_planning_command.await_args.kwargs["constraint_update"] == {
        "intentMode": "constraint",
        "schoolPreferences": {
            "positive": ["清华大学", "北京大学", "复旦大学", "招生类型:强基"],
            "negative": [],
        },
    }
    update_mock.assert_not_awaited()
    candidate_pool_mock.assert_not_awaited()
    ordered_mock.assert_not_awaited()


async def test_preview_plan_action_creates_remove_pending(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _direct_context()

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
    ctx = _direct_context()
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


async def test_preview_plan_action_no_plan_filter_creates_requirement_pending(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _direct_context(with_plan=False)

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="remove",
            filters={"school_nature": ["民办"]},
            raw_user_text="方案里的民办不要了",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["action_family"] == "apply_selected_intents"
    assert result["data"]["source"] == "preview_plan_action_requirement_fallback"
    assert result["data"]["reason"] == "no_plan_attribute_action_as_requirement"
    assert result["data"]["action_family"] == "apply_selected_intents"
    assert result["data"]["intent_fallback"] == {
        "intent_type": "school",
        "negative": {"school_nature": ["民办"]},
    }
    assert result["data"]["pending_created"] is True
    assert ctx.sandbox.peek("pending.json")["kind"] == "intent_change"
    save_mock.assert_awaited_once()


async def test_preview_plan_action_no_plan_position_remove_does_not_become_requirement(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _direct_context(with_plan=False)

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="remove",
            targets=["第3个"],
            raw_user_text="第3个不要了",
        )
    )

    assert result["next_step"] == "respond"
    assert result["data"]["has_plan"] is False
    assert "正式方案" in result["message"]
    save_mock.assert_not_awaited()


async def test_preview_plan_action_remove_uses_school_nature_filter(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _direct_context()

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
    ctx = _direct_context()

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
    ctx = _direct_context()

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
    ctx = _direct_context()
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
    ctx = _direct_context()

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
    ctx = _direct_context()

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
            make_run_context(request_context=_direct_context()),
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


async def test_preview_plan_action_remove_review_issue_without_units_falls_back_to_structured_filter(mocker):
    save_mock = mocker.patch(
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

    assert result["next_step"] == "confirm", result
    assert result["data"]["execution_payload"]["unit_ids"] == ["unit-nanfang", "unit-coop"]
    assert result["data"]["execution_payload"]["filters"] == {"program_type": ["高收费"]}
    save_mock.assert_awaited_once()


async def test_preview_plan_action_remove_discloses_total_when_scope_is_truncated(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _context_with_review()
    review = ctx.sandbox.peek("plan/review.json")
    review["checks"][0].pop("affectedUnitIds")
    plan = ctx.sandbox.peek("plan/items.json")
    for index in range(4):
        plan["items"].append(
            {
                "unitId": f"unit-high-tuition-{index}",
                "volunteerId": f"unit-high-tuition-{index}_001",
                "schoolName": f"高收费院校{index}",
                "majorName": f"高收费专业{index}",
                "tuitionPerYear": 30000 + index,
            }
        )

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="remove",
            review_issue_code="high_tuition",
            raw_user_text="把审查里的高收费项移出去",
        )
    )

    assert result["next_step"] == "confirm", result
    assert result["data"]["plan_impact"]["affected_count"] == 6
    assert "以上仅展示前5个，本次实际影响6个志愿组" in result["message"]
    saved_state = save_mock.await_args.args[1]
    assert "以上仅展示前5个，本次实际影响6个志愿组" in saved_state["affectedScope"]


async def test_preview_plan_action_remove_missing_review_issue_falls_back_to_structured_filter(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    mocker.patch(
        "app.zhiyuan_agent.tools._review_issue_by_code",
        AsyncMock(return_value=None),
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

    assert result["next_step"] == "confirm", result
    assert result["data"]["execution_payload"]["unit_ids"] == ["unit-nanfang", "unit-coop"]
    assert result["data"]["execution_payload"]["filters"] == {"program_type": ["高收费"]}
    save_mock.assert_awaited_once()


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
    candidate_query_mock = _mock_candidate_pool_query(mocker, ctx.sandbox.peek("plan/candidates.json")["items"])

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
    candidate_query_mock = _mock_candidate_pool_query(mocker, ctx.sandbox.peek("plan/candidates.json")["items"])

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
    candidate_query_mock.assert_awaited_once()
    query_kwargs = candidate_query_mock.await_args.kwargs
    assert query_kwargs["tiers"] == ["稳"]
    assert query_kwargs["sort_field"] == "tuitionPerYear"
    assert query_kwargs["sort_order"] == "asc"
    assert "高收费" in query_kwargs["negative_major_tags"]


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
                    "tier": "稳",
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
    candidate_query_mock = _mock_candidate_pool_query(mocker, ctx.sandbox.peek("plan/candidates.json")["items"])

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
    assert result["data"]["execution_payload"]["volunteer_ids"] == ["cand-guangwai-001", "cand-szu-001"]
    assert result["data"]["execution_payload"]["filters"]["tuition_min"] == 20000
    assert result["data"]["execution_payload"]["filters"]["auto_selected_candidates"] is True
    assert result["data"]["execution_payload"]["filters"]["auto_select_reason"] == "high_tuition"
    saved_state = save_mock.await_args.args[1]
    atomic = saved_state["executionPayload"]["atomic_actions"][0]
    assert atomic["unit_ids"] == ["unit-nanfang", "unit-coop"]
    assert atomic["volunteer_ids"] == ["cand-guangwai-001", "cand-szu-001"]
    assert atomic["filters"]["tuition_min"] == 20000
    assert "planPayload" not in saved_state["executionPayload"]
    candidate_query_mock.assert_awaited_once()
    query_kwargs = candidate_query_mock.await_args.kwargs
    assert query_kwargs["tiers"] == ["稳"]
    assert query_kwargs["sort_field"] == "tuitionPerYear"


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
    _mock_candidate_pool_query(mocker, ctx.sandbox.peek("plan/candidates.json")["items"])

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


async def test_preview_plan_action_replace_uses_explicit_replacement_spec_without_review_issue(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _direct_context()
    ctx.sandbox.prime(
        "plan/candidates.json",
        {
            "available": True,
            "items": [
                {
                    "volunteerId": "cand-lower-tuition-001",
                    "schoolName": "深圳技术大学",
                    "majorName": "计算机科学与技术",
                    "tier": "冲",
                    "provinceName": "广东",
                    "schoolNature": "公办",
                    "tuitionPerYear": 5000,
                    "admissionRatio": 45,
                }
            ],
        },
        version=12,
    )
    candidate_query_mock = _mock_candidate_pool_query(mocker, ctx.sandbox.peek("plan/candidates.json")["items"])

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="replace",
            targets=["华南理工大学"],
            replacement_spec={"improve_dims": ["tuition_decrease"], "exclude_markers": ["high_tuition"]},
            raw_user_text="华南理工这个先换个便宜点的",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["review_issue_code"] == ""
    assert result["data"]["execution_payload"]["unit_ids"] == ["unit-hnlg"]
    assert result["data"]["execution_payload"]["volunteer_ids"] == ["cand-lower-tuition-001"]
    assert result["data"]["execution_payload"]["filters"]["replacement_spec"]["source"] == "replacement_spec"
    candidate_query_mock.assert_awaited_once()
    query_kwargs = candidate_query_mock.await_args.kwargs
    assert query_kwargs["tiers"] == ["冲"]
    assert query_kwargs["sort_field"] == "tuitionPerYear"
    save_mock.assert_awaited_once()


async def test_preview_plan_action_replace_accepts_school_name_filter_alias(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _direct_context()
    ctx.sandbox.prime(
        "plan/candidates.json",
        {
            "available": True,
            "items": [
                {
                    "volunteerId": "cand-lower-tuition-001",
                    "schoolName": "深圳技术大学",
                    "majorName": "计算机科学与技术",
                    "tier": "冲",
                    "provinceName": "广东",
                    "schoolNature": "公办",
                    "tuitionPerYear": 5000,
                    "admissionRatio": 45,
                }
            ],
        },
        version=12,
    )
    candidate_query_mock = _mock_candidate_pool_query(mocker, ctx.sandbox.peek("plan/candidates.json")["items"])

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="replace",
            filters={"school_name": "华南理工大学"},
            replacement_spec={"improve_dims": ["tuition_decrease"]},
            raw_user_text="华南理工这个换个便宜点的",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["execution_payload"]["unit_ids"] == ["unit-hnlg"]
    assert result["data"]["execution_payload"]["volunteer_ids"] == ["cand-lower-tuition-001"]
    assert result["data"]["execution_payload"]["filters"]["school"] == ["华南理工大学"]
    candidate_query_mock.assert_awaited_once()
    save_mock.assert_awaited_once()


async def test_preview_plan_action_replace_clarifies_when_replacement_spec_missing(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _direct_context()

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="replace",
            targets=["华南理工大学"],
            raw_user_text="华南理工这个换掉",
        )
    )

    assert result["next_step"] == "clarify"
    assert result["data"]["reason"] == "replacement_spec_missing"
    assert "更便宜" in result["message"]
    save_mock.assert_not_awaited()


async def test_preview_plan_action_replace_requires_model_retry_for_missing_old_target(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _direct_context()

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="replace",
            replacement_spec={"improve_dims": ["tuition_decrease"], "exclude_markers": ["cooperative"]},
            raw_user_text="青岛理工那个中外合作建筑太贵了，换个正常收费的，最好不是中外合作",
        )
    )

    assert result["next_step"] == "continue"
    assert result["data"]["reason"] == "plan_action_requires_replace_target"
    assert result["data"]["source_reason"] == "missing_targets"
    assert result["data"]["current_user_text"] == "青岛理工那个中外合作建筑太贵了，换个正常收费的，最好不是中外合作"
    assert result["data"]["replacement_spec"]["improve_dims"] == ["tuition_decrease"]
    assert "targets" in result["data"]["retry_required_fields"]
    assert "replacement_spec" in result["data"]["retry_required_fields"]
    assert "preview_plan_action" in result["message"]
    save_mock.assert_not_awaited()


async def test_preview_plan_action_replace_old_target_retry_budget_falls_back_to_clarify(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _direct_context()

    first = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="replace",
            replacement_spec={"improve_dims": ["tuition_decrease"]},
            raw_user_text="青岛理工那个中外合作建筑太贵了，换个正常收费的",
        )
    )
    second = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="replace",
            replacement_spec={"improve_dims": ["tuition_decrease"]},
            raw_user_text="青岛理工那个中外合作建筑太贵了，换个正常收费的",
        )
    )

    assert first["next_step"] == "continue"
    assert second["next_step"] == "clarify"
    assert second["data"]["reason"] == "missing_targets"
    assert "学校、专业或第几个志愿" in second["message"]
    save_mock.assert_not_awaited()


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
    _mock_candidate_pool_query(mocker, ctx.sandbox.peek("plan/candidates.json")["items"])

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
                    "tier": "稳",
                    "provinceName": "广东",
                    "schoolNature": "公办",
                    "tuitionPerYear": 6060,
                    "admissionRatio": 82,
                },
            ],
        },
        version=12,
    )
    _mock_candidate_pool_query(mocker, ctx.sandbox.peek("plan/candidates.json")["items"])

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
    assert result["data"]["execution_payload"]["volunteer_ids"] == ["cand-guangwai-001", "cand-szu-001"]
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
    assert atomic["sort_field"] == "admissionRatio"
    assert atomic["filters"]["requested_sort_field"] == "admission_ratio"
    assert atomic["review_issue_target"]["code"] == "probability_inversion"
    assert "planPayload" not in saved_state["executionPayload"]


async def test_preview_plan_action_sort_maps_school_rank_to_backend_field(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=_direct_context()),
            action="sort",
            filters={"sort_field": "school_rank"},
            raw_user_text="按好学校优先排一下，先给我看",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["action_family"] == "sort_ordered_plan"
    assert result["data"]["execution_payload"]["sort_field"] == "schoolRank"
    assert result["data"]["execution_payload"]["filters"]["requested_sort_field"] == "school_rank"
    saved_state = save_mock.await_args.args[1]
    atomic = saved_state["executionPayload"]["atomic_actions"][0]
    assert atomic["sort_field"] == "schoolRank"
    assert "院校排名" in saved_state["summary"]


async def test_preview_plan_action_sort_rejects_unsupported_school_level(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=_direct_context()),
            action="sort",
            filters={"sort_field": "school_level"},
            raw_user_text="按学校层次从高到低排一下",
        )
    )

    assert result["next_step"] == "clarify"
    assert result["data"]["reason"] == "unsupported_sort_field"
    assert result["data"]["supported_sort_fields"] == ["admission_ratio", "school_rank", "comprehensive"]
    assert "院校排名" in result["message"]
    save_mock.assert_not_awaited()


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
            make_run_context(request_context=_direct_context()),
            action="remove",
            targets=["第31-32个"],
            raw_user_text="把第31-32个移出方案",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["execution_payload"]["unit_ids"] == ["unit-jnu", "unit-guanggong"]
    saved_state = save_mock.await_args.args[1]
    assert saved_state["executionPayload"]["atomic_actions"][0]["unit_ids"] == ["unit-jnu", "unit-guanggong"]


async def test_preview_plan_action_position_targets_ordered_unit_not_detail_item(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _direct_context()
    _prime_expanded_ordered_unit_plan(ctx)

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="remove",
            targets=["第三个专业组"],
            raw_user_text="第三个专业组先不要了，拿掉看看",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["execution_payload"]["unit_ids"] == ["unit-gamma"]
    assert "第3位" in result["message"]
    saved_state = save_mock.await_args.args[1]
    assert saved_state["executionPayload"]["atomic_actions"][0]["unit_ids"] == ["unit-gamma"]


async def test_preview_plan_action_position_recovers_target_from_raw_user_text(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _direct_context()
    _prime_expanded_ordered_unit_plan(ctx)

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="remove",
            raw_user_text="第三个专业组先不要了，拿掉看看",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["execution_payload"]["unit_ids"] == ["unit-gamma"]
    assert "第3位" in result["message"]
    saved_state = save_mock.await_args.args[1]
    assert saved_state["executionPayload"]["atomic_actions"][0]["unit_ids"] == ["unit-gamma"]


async def test_preview_plan_action_remove_can_resolve_position_group_filter(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _direct_context()
    _prime_expanded_ordered_unit_plan(ctx)

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="remove",
            filters={"position_group": 3},
            raw_user_text="第三个专业组先不要了，拿掉看看",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["execution_payload"]["unit_ids"] == ["unit-gamma"]
    assert result["data"]["execution_payload"]["filters"]["position_group"] == 3
    saved_state = save_mock.await_args.args[1]
    assert saved_state["executionPayload"]["atomic_actions"][0]["unit_ids"] == ["unit-gamma"]


async def test_preview_plan_action_remove_position_group_filter_accepts_alias(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _direct_context()
    _prime_expanded_ordered_unit_plan(ctx)

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="remove",
            filters={"orderedPosition": 3},
            raw_user_text="第三个专业组先不要了，拿掉看看",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["execution_payload"]["unit_ids"] == ["unit-gamma"]
    assert result["data"]["execution_payload"]["filters"]["position_group"] == 3
    saved_state = save_mock.await_args.args[1]
    assert saved_state["executionPayload"]["atomic_actions"][0]["unit_ids"] == ["unit-gamma"]


async def test_preview_plan_action_move_position_targets_ordered_unit_not_detail_item(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _direct_context()
    _prime_expanded_ordered_unit_plan(ctx)

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="move",
            targets=["第3个专业组"],
            target_position=1,
            raw_user_text="把第三个专业组挪到最前面",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["execution_payload"]["unit_ids"] == ["unit-gamma"]
    assert result["data"]["execution_payload"]["target_position"] == 1
    saved_state = save_mock.await_args.args[1]
    atomic = saved_state["executionPayload"]["atomic_actions"][0]
    assert atomic["unit_ids"] == ["unit-gamma"]
    assert atomic["target_position"] == 1


async def test_preview_plan_action_move_recovers_source_position_from_raw_user_text(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _direct_context()
    _prime_expanded_ordered_unit_plan(ctx)

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="move",
            target_position=1,
            raw_user_text="把第三个专业组挪到最前面",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["execution_payload"]["unit_ids"] == ["unit-gamma"]
    assert "第3位" in result["message"]
    saved_state = save_mock.await_args.args[1]
    atomic = saved_state["executionPayload"]["atomic_actions"][0]
    assert atomic["unit_ids"] == ["unit-gamma"]
    assert atomic["target_position"] == 1


async def test_preview_plan_action_pin_lock_is_unsupported_without_pending(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=_direct_context()),
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
    ctx = _direct_context()

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


async def test_preview_plan_action_move_requires_model_retry_for_missing_target_tier(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=_direct_context()),
            action="move",
            filters={
                "tier": ["保底"],
                "selector_sort": "admission_ratio",
                "selector_rank": "max",
            },
            raw_user_text="帮我把保底区里录取率最高的那个调到保底的第一位",
        )
    )

    assert result["next_step"] == "continue"
    assert result["data"]["reason"] == "plan_action_requires_move_target_position"
    assert result["data"]["unit_ids"] == ["unit-guanggong"]
    assert result["data"]["current_user_text"] == "帮我把保底区里录取率最高的那个调到保底的第一位"
    assert "filters.target_tier" in result["data"]["retry_required_fields"]
    save_mock.assert_not_awaited()


async def test_preview_plan_action_move_requires_model_retry_for_missing_selector(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=_direct_context()),
            action="move",
            filters={"tier": ["保底"]},
            raw_user_text="帮我把保底区里录取率最高的那个调到保底的第一位",
        )
    )

    assert result["next_step"] == "continue"
    assert result["data"]["reason"] == "plan_action_requires_move_selector"
    assert result["data"]["filters"]["tier"] == ["保"]
    assert result["data"]["current_user_text"] == "帮我把保底区里录取率最高的那个调到保底的第一位"
    assert "filters.selector_sort" in result["data"]["retry_required_fields"]
    save_mock.assert_not_awaited()


async def test_preview_plan_action_move_requires_model_retry_for_missing_action_from_latest_user_text(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _direct_context()
    ctx.chat_history = [{"role": "user", "content": "帮我把保底区里录取率最高的那个调到保底的第一位"}]

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="",
        )
    )

    assert result["next_step"] == "continue"
    assert result["data"]["reason"] == "plan_action_requires_explicit_action"
    assert result["data"]["current_user_text"] == "帮我把保底区里录取率最高的那个调到保底的第一位"
    assert "move" in result["data"]["allowed_actions"]
    assert result["data"]["retry_required_fields"] == ["action"]
    save_mock.assert_not_awaited()


async def test_preview_plan_action_move_requires_model_retry_for_ambiguous_tier_without_selector(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=_direct_context()),
            action="move",
            filters={"tier": ["保底"]},
            raw_user_text="帮我把保底区里的那个调到保底的第一位",
        )
    )

    assert result["next_step"] == "continue"
    assert result["data"]["reason"] == "plan_action_requires_move_selector"
    assert "selector_sort" in result["message"]
    save_mock.assert_not_awaited()


async def test_preview_plan_action_move_requires_target_position(mocker):
    mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=_direct_context()),
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
    ctx = _direct_context()
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


async def test_preview_plan_action_add_queries_named_school_and_major_target(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _direct_context()
    ctx.sandbox.prime("plan/candidates.json", {"available": True, "items": []}, version=12)
    original_read = ctx.sandbox.read

    async def read_with_query(path, query=None):
        if query is not None:
            assert query["school_keywords"] == ["厦门大学嘉庚学院"]
            assert query["major_keywords"] == ["建筑学"]
            return {
                "available": True,
                "items": [
                    {
                        "volunteerId": "cand-xujc-architecture",
                        "planSchoolDataId": "unit-xujc-architecture",
                        "schoolName": "厦门大学嘉庚学院",
                        "majorName": "建筑学",
                        "majorCategory": "建筑类",
                        "tier": "冲",
                    }
                ],
            }
        return await original_read(path)

    mocker.patch.object(ctx.sandbox, "read", side_effect=read_with_query)

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="add",
            targets=["厦门大学嘉庚学院.建筑学"],
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["execution_payload"]["volunteer_ids"] == ["cand-xujc-architecture"]
    assert save_mock.await_count == 1


async def test_preview_plan_action_add_selects_single_matching_candidate_group(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _direct_context()
    ctx.sandbox.prime(
        "plan/candidates.json",
        {
            "available": True,
            "items": [
                {
                    "volunteerId": "school-1_unit-architecture_major-1",
                    "planSchoolDataId": "school-1_unit-architecture",
                    "schoolName": "厦门大学嘉庚学院",
                    "majorName": "建筑学",
                    "majorCategory": "建筑类",
                    "tier": "稳",
                },
                {
                    "volunteerId": "school-1_unit-architecture_major-2",
                    "planSchoolDataId": "school-1_unit-architecture",
                    "schoolName": "厦门大学嘉庚学院",
                    "majorName": "城乡规划",
                    "majorCategory": "建筑类",
                    "tier": "稳",
                },
            ],
        },
        version=12,
    )

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="add",
            filters={"school": ["厦门大学嘉庚学院"], "major": ["建筑类"]},
        )
    )

    assert result["next_step"] == "confirm", result
    assert result["data"]["execution_payload"]["volunteer_ids"] == [
        "school-1_unit-architecture_major-1",
        "school-1_unit-architecture_major-2",
    ]
    assert save_mock.await_count == 1


async def test_preview_plan_action_add_clarifies_multiple_candidate_groups(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _direct_context()
    ctx.sandbox.prime(
        "plan/candidates.json",
        {
            "available": True,
            "items": [
                {
                    "volunteerId": "school-1_unit-architecture_major-1",
                    "planSchoolDataId": "school-1_unit-architecture",
                    "schoolName": "厦门大学嘉庚学院",
                    "majorName": "建筑学",
                    "majorCategory": "建筑类",
                    "tier": "冲",
                },
                {
                    "volunteerId": "school-1_unit-planning_major-1",
                    "planSchoolDataId": "school-1_unit-planning",
                    "schoolName": "厦门大学嘉庚学院",
                    "majorName": "城乡规划",
                    "majorCategory": "建筑类",
                    "tier": "稳",
                },
            ],
        },
        version=12,
    )

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="add",
            filters={"school": ["厦门大学嘉庚学院"], "major": ["建筑类"]},
        )
    )

    assert result["next_step"] == "clarify"
    assert result["data"]["reason"] == "candidate_ambiguous"
    assert result["data"]["matched_total"] == 2
    assert "建筑学" in result["message"]
    assert "城乡规划" in result["message"]
    save_mock.assert_not_awaited()


async def test_query_plan_with_plan():
    result = _load(
        await query_plan(
            make_run_context(request_context=_direct_context()),
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


async def test_query_plan_accepts_school_name_filter_alias():
    result = _load(
        await query_plan(
            make_run_context(request_context=_direct_context()),
            scope="plan",
            filters={"school_name": "华南理工大学"},
        )
    )

    assert result["next_step"] == "respond"
    assert result["data"]["matched_total"] == 1
    assert result["data"]["filters"]["school"] == ["华南理工大学"]
    assert result["data"]["items"][0]["school"] == "华南理工大学"


async def test_query_plan_accepts_contextual_school_abbreviation():
    ctx = _direct_context()
    plan_file = ctx.sandbox.peek("plan/items.json")
    plan_file["items"].append(
        {
            "unitId": "unit-qingdao-city",
            "volunteerId": "unit-qingdao-city_001",
            "schoolName": "青岛城市学院",
            "majorName": "工程管理",
            "schoolNature": "民办",
            "schoolCategory": "综合",
            "provinceName": "山东",
            "tier": "保",
            "position": 38,
            "tuitionPerYear": 24800,
        }
    )

    result = _load(
        await query_plan(
            make_run_context(request_context=ctx),
            scope="plan",
            filters={"school": "青城"},
        )
    )

    assert result["next_step"] == "respond"
    assert result["data"]["matched_total"] == 1
    assert result["data"]["items"][0]["school"] == "青岛城市学院"
    assert "青岛城市学院" in result["message"]


async def test_query_plan_filters_by_tuition_and_major_items():
    result = _load(
        await query_plan(
            make_run_context(request_context=_direct_context()),
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
    ctx = _direct_context()
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
            make_run_context(request_context=_direct_context()),
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
            make_run_context(request_context=_direct_context()),
            scope="plan",
            filters={},
        )
    )

    assert result["next_step"] == "respond"
    assert result["data"]["limit"] == 5
    assert result["data"]["returned_total"] <= 5
    assert "展示前" in result["message"]


async def test_query_plan_school_question_summarizes_schools_not_major_rows():
    ctx = _direct_context()
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
    adapter.add("plan/summary.json", BackendReadResult(_direct_context().sandbox.peek("plan/summary.json"), 12))
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
    ctx = _direct_context()
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
    result = _load(await query_plan(make_run_context(request_context=_direct_context(with_plan=False))))

    assert result["next_step"] == "respond"
    assert result["data"]["has_plan"] is False
    assert "还没有生成正式方案" in result["message"]


async def test_query_plan_no_plan_filter_does_not_claim_absence():
    result = _load(
        await query_plan(
            make_run_context(request_context=_direct_context(with_plan=False)),
            filters={"school_nature": "民办"},
        )
    )

    assert result["next_step"] == "respond"
    assert result["data"]["has_plan"] is False
    assert result["data"]["no_plan_query_boundary"] is True
    assert "暂时无法判断方案里是否有" in result["message"]
    assert "方案里没有" not in result["message"]


async def test_confirm_pending_no_active_pending():
    result = _load(await confirm_pending(make_run_context(request_context=_direct_context()), action="confirm"))

    assert result["next_step"] == "respond"
    assert result["data"]["active"] is False
    assert "没有待确认操作" in result["message"]
    assert "上一轮只是查询或分析" in result["message"]
    assert "没有待采纳或待执行的内容" in result["message"]
    assert "不会执行任何变更" in result["message"]
    assert "下一步" in result["message"]
    assert "生成具体调整预览" in result["message"]


async def test_confirm_pending_rejects_runtime_and_sandbox_pending_id_mismatch(mocker):
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
            "pending_id": "pending-sandbox-new",
            "kind": "intent_change",
            "action_family": "apply_selected_intents",
            "execution_payload": {
                "merged": {"city_intents": {"negative_province": ["山东"]}},
            },
        }
    )
    ctx.conversation_phase = ConversationPhase(
        state=PhaseState.INTENT_PREVIEWING,
        pending=PendingConfirmation(
            kind="intent_change",
            pending_id="pending-runtime-old",
            action_family="apply_selected_intents",
            execution_payload={
                "merged": {"school_intents": {"negative_school_nature": ["民办"]}},
            },
        ),
    )

    result = _load(await confirm_pending(make_run_context(request_context=ctx), action="confirm"))

    assert result["data"]["error"] == "pending_snapshot_mismatch"
    assert "不会执行" in result["message"]
    update_mock.assert_not_awaited()
    save_mock.assert_not_awaited()


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


async def test_confirm_pending_applies_intent_payload_directly(mocker, _stub_pending_planning_command):
    update_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.update_planning_constraint_state",
        AsyncMock(return_value={"code": 0}),
    )
    ordered_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.generate_planning_ordered_plan",
        AsyncMock(return_value={"code": 0}),
    )
    candidate_pool_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.generate_planning_candidate_pool",
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
    assert result["data"]["result"]["requires_candidate_pool_rebuild"] is False
    assert result["data"]["result"]["candidate_pool_regenerated"] is False
    assert result["data"]["result"]["plan_regenerated"] is True
    assert _stub_pending_planning_command.await_args.kwargs["constraint_update"] == {
        "intentMode": "constraint",
        "majorPreferences": {"positive": ["法学"], "negative": ["医学"]},
    }
    update_mock.assert_not_awaited()
    candidate_pool_mock.assert_not_awaited()
    ordered_mock.assert_not_awaited()
    saved_state = save_mock.await_args.args[1]
    assert saved_state["status"] == "applied"
    assert saved_state["resultCode"] == "applied"


async def test_confirm_pending_intent_without_plan_does_not_regenerate_order(mocker, _stub_pending_planning_command):
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
    ctx = _direct_context(with_plan=False)
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
    ctx.conversation_phase = ConversationPhase(
        state=PhaseState.INTENT_PREVIEWING,
        pending=PendingConfirmation(
            kind="intent_change",
            pending_id="pending-intent-no-plan",
            action_family="apply_selected_intents",
            preview_summary="排除民办",
            execution_payload=pending_state["execution_payload"],
        ),
    )
    ctx.sandbox.prime("pending.json", pending_state, version=0)

    result = _load(await confirm_pending(make_run_context(request_context=ctx), action="confirm"))

    assert result["data"]["applied"] is True
    assert result["data"]["result"]["has_plan"] is False
    assert result["data"]["result"]["plan_regenerated"] is False
    assert "后续生成方案" in result["message"]
    assert "约束" not in result["message"]
    update_mock.assert_not_awaited()
    assert _stub_pending_planning_command.await_args.kwargs["regenerate_ordered_plan"] is False
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
    assert save_mock.await_args.args[1]["_pendingClaimToken"] == "claim-test-token"
    assert save_mock.await_args.kwargs == {}


async def test_confirm_pending_marks_plan_action_failed_when_diff_misses_target(mocker):
    remove_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.remove_planning_ordered_plan_units",
        AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "version": 13,
                    "orderedPlanState": {
                        "units": [
                            {"unitId": "unit-hnlg", "volunteerId": "unit-hnlg_001"},
                            {"unitId": "unit-nanfang", "volunteerId": "unit-nanfang_001"},
                            {"unitId": "unit-jnu", "volunteerId": "unit-jnu_001"},
                        ]
                    },
                },
            }
        ),
    )
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _context_with_backend_pending(
        {
            "active": True,
            "pending_id": "pending-plan-diff-fail",
            "kind": "plan_mutation",
            "action_family": "remove_units",
            "summary": "移出民办志愿组",
            "source_backend_version": 12,
            "execution_payload": {
                "action_family": "remove_units",
                "atomic_actions": [{"action_type": "remove_units", "unit_ids": ["unit-nanfang"]}],
            },
            "raw": {
                "pendingId": "pending-plan-diff-fail",
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
    assert result["data"]["result"]["reason"] == "removed_units_still_present"
    assert "预期变化" in result["message"]
    remove_mock.assert_awaited_once_with(1, ctx.sessionid, ["unit-nanfang"])
    saved_state = save_mock.await_args.args[1]
    assert saved_state["status"] == "expired"
    assert saved_state["resultCode"] == "removed_units_still_present"
    assert saved_state["resultData"]["ordered_plan_diff"]["remaining_unit_ids"] == ["unit-nanfang"]


async def test_confirm_pending_sort_reports_no_change_when_order_unchanged(mocker):
    sort_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.sort_planning_ordered_plan",
        AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "version": 13,
                    "orderedPlanState": {
                        "units": [
                            {"unitId": "unit-hnlg", "volunteerId": "unit-hnlg_001"},
                            {"unitId": "unit-nanfang", "volunteerId": "unit-nanfang_001"},
                            {"unitId": "unit-jnu", "volunteerId": "unit-jnu_001"},
                            {"unitId": "unit-guanggong", "volunteerId": "unit-guanggong_001"},
                        ]
                    },
                },
            }
        ),
    )
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _context_with_backend_pending(
        {
            "active": True,
            "pending_id": "pending-sort-no-change",
            "kind": "plan_mutation",
            "action_family": "sort_ordered_plan",
            "summary": "按院校排名排序",
            "source_backend_version": 12,
            "execution_payload": {
                "action_family": "sort_ordered_plan",
                "atomic_actions": [{"action_type": "sort_ordered_plan", "sort_field": "schoolRank"}],
            },
            "raw": {
                "pendingId": "pending-sort-no-change",
                "kind": "plan_mutation",
                "actionFamily": "sort_ordered_plan",
                "status": "active",
                "sourceBackendVersion": 12,
            },
        }
    )

    result = _load(await confirm_pending(make_run_context(request_context=ctx), action="confirm"))

    assert result["data"]["applied"] is True
    assert "顺序没有变化" in result["message"]
    assert "已按要求重新排序" not in result["message"]
    assert result["data"]["result"]["ordered_plan_diff"]["reason"] == "sort_order_unchanged"
    sort_mock.assert_awaited_once_with(1, ctx.sessionid, "schoolRank")
    saved_state = save_mock.await_args.args[1]
    assert saved_state["status"] == "applied"
    assert saved_state["resultData"]["ordered_plan_diff"]["changed"] is False


async def test_confirm_pending_replace_accepts_selected_candidate_in_ordered_items(mocker, _stub_pending_planning_command):
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
        AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "version": 13,
                    "orderedPlanState": {
                        "units": [
                            {"unitId": "unit-hnlg", "volunteerId": "unit-hnlg_001"},
                            {"unitId": "unit-jnu", "volunteerId": "unit-jnu_001"},
                        ],
                        "items": [
                            {"unitId": "unit-hnlg", "volunteerId": "unit-hnlg_001"},
                            {"unitId": "unit-jnu", "volunteerId": "unit-jnu_001"},
                            {"unitId": "unit-new", "volunteerId": "cand-new"},
                        ],
                    },
                },
            }
        ),
    )
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    _stub_pending_planning_command.side_effect = None
    _stub_pending_planning_command.return_value = {
        "code": 0,
        "data": {
            "operationId": "op-replace",
            "completedSteps": ["ordered_units_removed", "working_plan_items_selected", "ordered_plan_regenerated"],
            "replayed": False,
            "planningState": {
                "version": 15,
                "orderedPlanState": {
                    "units": [
                        {"unitId": "unit-hnlg", "volunteerId": "unit-hnlg_001"},
                        {"unitId": "unit-jnu", "volunteerId": "unit-jnu_001"},
                    ],
                    "items": [
                        {"unitId": "unit-hnlg", "volunteerId": "unit-hnlg_001"},
                        {"unitId": "unit-jnu", "volunteerId": "unit-jnu_001"},
                        {"unitId": "unit-new", "volunteerId": "cand-new"},
                    ],
                },
            },
        },
    }
    ctx = _context_with_backend_pending(
        {
            "active": True,
            "pending_id": "pending-replace-draft-selected",
            "kind": "plan_mutation",
            "action_family": "replace_units",
            "summary": "替换民办志愿组",
            "source_backend_version": 12,
            "execution_payload": {
                "action_family": "replace_units",
                "atomic_actions": [
                    {"action_type": "replace_units", "unit_ids": ["unit-nanfang"], "volunteer_ids": ["cand-new"]}
                ],
            },
            "raw": {
                "pendingId": "pending-replace-draft-selected",
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
    assert result["data"]["result"]["ordered_plan_diff"]["passed"] is True
    assert result["data"]["result"]["ordered_plan_diff"]["missing_selected_volunteer_ids"] == []
    command_args = _stub_pending_planning_command.await_args.kwargs
    assert command_args["unit_ids"] == ["unit-nanfang"]
    assert command_args["volunteer_ids"] == ["cand-new"]
    remove_mock.assert_not_awaited()
    select_mock.assert_not_awaited()
    order_mock.assert_not_awaited()
    assert save_mock.await_args.args[1]["status"] == "applied"


async def test_confirm_pending_applies_replace_units_directly(mocker, _stub_pending_planning_command):
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
    command_args = _stub_pending_planning_command.await_args.kwargs
    assert command_args["command_type"] == "replace_units"
    assert command_args["unit_ids"] == ["unit-old"]
    assert command_args["volunteer_ids"] == ["cand-new"]
    remove_mock.assert_not_awaited()
    select_mock.assert_not_awaited()
    order_mock.assert_not_awaited()
    assert save_mock.await_args.args[1]["status"] == "applied"


async def test_confirm_pending_applies_add_units_as_single_command(mocker, _stub_pending_planning_command):
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
            "pending_id": "pending-add",
            "kind": "plan_mutation",
            "action_family": "add_units",
            "summary": "加入一个志愿",
            "source_backend_version": 12,
            "execution_payload": {
                "action_family": "add_units",
                "atomic_actions": [
                    {"action_type": "add_units", "volunteer_ids": ["cand-new"]}
                ],
            },
            "raw": {
                "pendingId": "pending-add",
                "kind": "plan_mutation",
                "actionFamily": "add_units",
                "status": "active",
                "sourceBackendVersion": 12,
            },
        }
    )

    result = _load(await confirm_pending(make_run_context(request_context=ctx), action="confirm"))

    assert result["next_step"] == "respond"
    assert result["data"]["applied"] is True
    command_args = _stub_pending_planning_command.await_args.kwargs
    assert command_args["command_type"] == "add_units"
    assert command_args["volunteer_ids"] == ["cand-new"]
    select_mock.assert_not_awaited()
    order_mock.assert_not_awaited()
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
    assert save_mock.await_args.args[1]["status"] == "expired"


async def test_confirm_pending_does_not_mutate_when_claim_was_not_acquired(mocker, _stub_pending_claim):
    tool_claim, _ = _stub_pending_claim
    tool_claim.return_value = {
        "code": 0,
        "data": {
            "pendingId": "pending-concurrent",
            "revision": 9,
            "status": "applying",
            "transitionApplied": False,
            "dataValue": {"pendingId": "pending-concurrent", "status": "applying"},
        },
    }
    tool_claim.side_effect = None
    remove_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.remove_planning_ordered_plan_units",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _context_with_backend_pending(
        {
            "active": True,
            "pending_id": "pending-concurrent",
            "kind": "plan_mutation",
            "action_family": "remove_units",
            "source_backend_version": 12,
            "execution_payload": {
                "action_family": "remove_units",
                "atomic_actions": [{"action_type": "remove_units", "unit_ids": ["u1"]}],
            },
            "raw": {
                "pendingId": "pending-concurrent",
                "kind": "plan_mutation",
                "actionFamily": "remove_units",
                "status": "active",
                "sourceBackendVersion": 12,
                "_pendingRevision": 8,
            },
        }
    )

    result = _load(await confirm_pending(make_run_context(request_context=ctx), action="confirm"))

    assert result["data"]["error"] == "pending_claim_conflict"
    remove_mock.assert_not_awaited()


async def test_service_pending_confirmation_reports_unexpired_claim_in_progress(mocker, _stub_pending_claim):
    _, service_claim = _stub_pending_claim
    pending_state = {
        "pendingId": "pending-in-progress",
        "kind": "plan_mutation",
        "status": "applying",
        "actionFamily": "remove_units",
        "executionPayload": {
            "action_family": "remove_units",
            "atomic_actions": [{"action_type": "remove_units", "unit_ids": ["u1"]}],
        },
        "_pendingClaimToken": "claim-owner",
        "_pendingClaimExpiresAt": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
    }
    mocker.patch(
        "app.service._load_pending_confirmation_state",
        AsyncMock(return_value=pending_state),
    )
    service = object.__new__(ChatService)

    reply = await service.handle_pending_confirmation(
        "session-in-progress",
        "user-in-progress",
        json.dumps(
            {
                "action": "confirm",
                "kind": "plan_mutation",
                "pendingId": "pending-in-progress",
            }
        ),
    )

    assert "正在处理中" in reply
    assert "不会重复执行" in reply
    service_claim.assert_not_awaited()


async def test_confirm_pending_keeps_applying_when_command_result_is_uncertain(
    mocker,
    _stub_pending_planning_command,
):
    _stub_pending_planning_command.side_effect = None
    _stub_pending_planning_command.return_value = {"error": "connection reset", "success": False}
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _context_with_backend_pending(
        {
            "active": True,
            "pending_id": "pending-command-uncertain",
            "kind": "plan_mutation",
            "action_family": "replace_units",
            "source_backend_version": 12,
            "execution_payload": {
                "action_family": "replace_units",
                "atomic_actions": [{
                    "action_type": "replace_units",
                    "unit_ids": ["unit-old"],
                    "volunteer_ids": ["candidate-new"],
                }],
            },
            "raw": {
                "pendingId": "pending-command-uncertain",
                "kind": "plan_mutation",
                "actionFamily": "replace_units",
                "status": "active",
                "sourceBackendVersion": 12,
            },
        }
    )

    result = _load(await confirm_pending(make_run_context(request_context=ctx), action="confirm"))

    assert result["data"]["execution_uncertain"] is True
    assert result["data"]["active"] is True
    assert "不会重复执行" in result["message"]
    save_mock.assert_not_awaited()


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


async def test_service_pending_confirmation_executes_plan_generation_bridge(mocker):
    pending_state = {
        "type": "pendingConfirmation",
        "pendingId": "pending-structured-generation",
        "sessionId": "session-structured-generation",
        "kind": "plan_generation",
        "status": "active",
        "actionFamily": "regenerate_order",
        "summary": "补一个安全一点的专业并重新生成排序方案",
        "executionPayload": {
            "action_family": "regenerate_order",
            "atomic_actions": [
                {
                    "action_type": "regenerate_order",
                    "filters": {"review_issue_code": "probability_gap"},
                }
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

    order_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.generate_planning_ordered_plan",
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
        "session-structured-generation",
        "user-structured-generation",
        json.dumps(
            {
                "action": "confirm",
                "kind": "plan_generation",
                "pendingId": "pending-structured-generation",
            },
            ensure_ascii=False,
        ),
    )

    assert getattr(reply, "primary", "") == "已按当前候选重新生成排序方案。"
    assert [item.type for item in reply.followups] == [
        "planningWorkspaceAction",
        "planningWorkspaceAction",
    ]
    review_payload = json.loads(reply.followups[1].content)
    assert review_payload["targetView"] == "review"
    assert review_payload["title"] == "需要重新审查方案"
    assert "原审查结果可能不再完全准确" in review_payload["content"]
    assert review_payload["actionText"] == "重新审查"
    order_mock.assert_awaited_once_with(1, "session-structured-generation")
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

    review_returns = [
        _tool_return(
            {
                "next_step": "respond",
                "data": {"summary": {"risk_count": 1}},
                "message": "已完成方案审查，当前正式方案有45个志愿。",
            },
            tool_name="review_plan",
        )
    ]
    assert agent.should_return_directly_from_tool(["review_plan"], review_returns, None) is True
    assert (
        agent.render_direct_tool_output(["review_plan"], review_returns, None)
        == "已完成方案审查，当前正式方案有45个志愿。"
    )

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


def test_zhiyuan_agent_direct_tool_output_combines_readonly_before_review_without_preview_heading():
    agent = ZhiyuanAgent(SimpleNamespace(model=TestModel(), model_settings={}))
    tool_returns = [
        _tool_return(
            {
                "next_step": "respond",
                "data": {"summary": "当前方案有45个志愿。"},
                "message": "当前方案有45个志愿。",
            },
            tool_name="query_plan",
        ),
        _tool_return(
            {
                "next_step": "respond",
                "data": {"summary": "风险0项，提醒3项。"},
                "message": "已完成方案审查，风险0项，提醒3项。",
            },
            tool_name="review_plan",
        ),
    ]

    rendered = agent.render_direct_tool_output(["query_plan", "review_plan"], tool_returns, None)

    assert rendered is not None
    assert rendered.startswith("当前方案有45个志愿。")
    assert "继续看审查结果" in rendered
    assert "已完成方案审查" in rendered
    assert "下面是这次待确认预览" not in rendered


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
    ctx = _direct_context(pending=True)

    result = _load(
        await preview_intent_change(
            make_run_context(request_context=ctx),
            intent_type="major",
            positive={"level2": ["计算机类"]},
            constraint_type="must_have",
            raw_user_text="计算机和自动化方向考生不考虑",
        )
    )

    assert result["data"]["reason"] == "active_pending_requires_resolution"
    assert result["next_step"] == "continue"
    assert result["data"]["pending_created"] is False
    assert result["data"]["current_user_text"] == "计算机和自动化方向考生不考虑"
    assert "pending_resolution" in result["message"]
    save_mock.assert_not_awaited()


async def test_preview_intent_change_can_replace_active_pending_when_explicit(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _direct_context(pending=True)

    result = _load(
        await preview_intent_change(
            make_run_context(request_context=ctx),
            intent_type="region",
            negative={"province": ["山东"]},
            constraint_type="exclude",
            pending_resolution="replace_active_pending",
            raw_user_text="这个先算了，改成山东别去了",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["pending_created"] is True
    assert result["data"]["replaced_active_pending"] is True
    assert "山东" in result["message"]
    assert save_mock.await_count == 2
    cancelled_state = save_mock.await_args_list[0].args[1]
    new_pending_state = save_mock.await_args_list[1].args[1]
    assert cancelled_state["status"] == "cancelled"
    assert cancelled_state["resultCode"] == "replaced_by_new_preview"
    assert new_pending_state["status"] == "active"
    assert new_pending_state["kind"] == "intent_change"
    assert new_pending_state["executionPayload"]["merged"]["city_intents"]["negative_province"] == ["山东"]


async def test_preview_intent_change_only_keep_school_nature_drops_redundant_negative_nature(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _direct_context(pending=True)

    result = _load(
        await preview_intent_change(
            make_run_context(request_context=ctx),
            intent_type="region",
            positive={"school_nature": ["公办"]},
            negative={"province": ["山东"], "school_nature": ["民办"]},
            constraint_type="only_keep",
            pending_resolution="replace_active_pending",
            raw_user_text="等下，别按这个了，改成只看公办，山东也别去",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["merged"]["school_intents"]["school_nature"] == ["公办"]
    assert "negative_school_nature" not in result["data"]["merged"]["school_intents"]
    assert result["data"]["merged"]["city_intents"]["negative_province"] == ["山东"]
    new_pending_state = save_mock.await_args_list[1].args[1]
    assert new_pending_state["executionPayload"]["merged"]["school_intents"]["school_nature"] == ["公办"]
    assert "negative_school_nature" not in new_pending_state["executionPayload"]["merged"]["school_intents"]


async def test_preview_intent_change_can_append_to_active_intent_pending(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _direct_context(pending=False)
    old_execution_payload = {
        "toolName": "confirm_pending",
        "selectedData": {
            "selected": [{"school_intents": {"negative_school_nature": ["民办"]}}],
            "intentMode": "constraint",
            "constraintIntentType": "exclude",
            "applyToCurrentPlan": True,
            "batch": ctx.batch or "01",
        },
        "merged": {"school_intents": {"negative_school_nature": ["民办"]}},
        "intentMode": "constraint",
        "constraintIntentType": "exclude",
        "applyToCurrentPlan": True,
        "batch": ctx.batch or "01",
    }
    old_pending_state = {
        "type": "pendingConfirmation",
        "pendingId": "pending-old-intent",
        "sessionId": ctx.sessionid,
        "kind": "intent_change",
        "status": "active",
        "actionFamily": "apply_selected_intents",
        "summary": "排除民办院校",
        "executionPayload": old_execution_payload,
        "sourceBackendVersion": 12,
    }
    ctx.conversation_phase = ConversationPhase(
        state=PhaseState.INTENT_PREVIEWING,
        pending=PendingConfirmation(
            kind="intent_change",
            action_family="apply_selected_intents",
            preview_summary="排除民办院校",
            execution_payload=old_execution_payload,
        ),
    )
    ctx.sandbox.prime(
        "pending.json",
        {
            "active": True,
            "pending_id": "pending-old-intent",
            "kind": "intent_change",
            "action_family": "apply_selected_intents",
            "summary": "排除民办院校",
            "preview_summary": "排除民办院校",
            "execution_payload": old_execution_payload,
            "source_backend_version": 12,
            "status": "active",
            "raw": old_pending_state,
        },
        version=12,
    )

    result = _load(
        await preview_intent_change(
            make_run_context(request_context=ctx),
            intent_type="region",
            negative={"province": ["山东"]},
            constraint_type="exclude",
            pending_resolution="append_to_active_pending",
            raw_user_text="山东也别去了",
        )
    )

    assert result["next_step"] == "confirm"
    assert result["data"]["pending_created"] is True
    assert result["data"]["merged_existing_pending"] is True
    assert result["data"]["replaced_active_pending"] is False
    assert save_mock.await_count == 2
    cancelled_state = save_mock.await_args_list[0].args[1]
    new_pending_state = save_mock.await_args_list[1].args[1]
    assert cancelled_state["status"] == "cancelled"
    assert cancelled_state["resultCode"] == "merged_into_new_preview"
    assert new_pending_state["executionPayload"]["merged"]["school_intents"]["negative_school_nature"] == ["民办"]
    assert new_pending_state["executionPayload"]["merged"]["city_intents"]["negative_province"] == ["山东"]


async def test_preview_plan_action_blocks_new_pending_when_turn_started_with_pending(mocker):
    save_mock = mocker.patch(
        "app.zhiyuan_agent.tools.internal_client.save_pending_confirmation",
        AsyncMock(return_value={"code": 0}),
    )
    ctx = _direct_context(pending=True)

    result = _load(
        await preview_plan_action(
            make_run_context(request_context=ctx),
            action="remove",
            filters={"school_nature": ["民办"]},
            raw_user_text="那把民办的删掉",
        )
    )

    assert result["data"]["reason"] == "active_pending_requires_resolution"
    assert result["next_step"] == "continue"
    assert result["data"]["pending_created"] is False
    assert result["data"]["current_user_text"] == "那把民办的删掉"
    assert "pending_resolution" in result["message"]
    save_mock.assert_not_awaited()


async def test_zhiyuan_agent_continues_after_query_plan_tool():
    client = SimpleNamespace(model=TestModel(call_tools=["query_plan"]), model_settings={})
    agent = ZhiyuanAgent(client)
    deps = _direct_context()

    reply, _, all_messages, usage = await agent.run_with_message_deltas("方案里有没有民办", deps=deps)

    assert "当前正式方案有45个志愿" in reply
    assert usage.tool_calls == 1
    assert deps.agent_observability.get("directToolReturn") is not True
    assert _tool_calls(all_messages)[0].tool_name == "query_plan"


async def test_zhiyuan_agent_continues_after_answer_policy_tool():
    client = SimpleNamespace(model=TestModel(call_tools=["answer_policy"]), model_settings={})
    agent = ZhiyuanAgent(client)
    deps = _direct_context()

    reply, _, all_messages, usage = await agent.run_with_message_deltas("分数和位次怎么参考", deps=deps)

    assert "只读规则问题" in reply
    assert usage.tool_calls == 1
    assert deps.agent_observability.get("directToolReturn") is not True
    assert _tool_calls(all_messages)[0].tool_name == "answer_policy"


async def test_zhiyuan_agent_returns_directly_after_review_plan_tool():
    client = SimpleNamespace(model=TestModel(call_tools=["review_plan"]), model_settings={})
    agent = ZhiyuanAgent(client)
    deps = _context_with_review()

    reply, _, all_messages, usage = await agent.run_with_message_deltas("审查一下当前方案", deps=deps)

    assert "方案审查" in reply
    assert usage.tool_calls == 1
    assert deps.agent_observability.get("directToolReturn") is True
    assert _tool_calls(all_messages)[0].tool_name == "review_plan"


class _FakeHistoryStore:
    def __init__(self) -> None:
        self.saved: tuple[str, list[Any]] | None = None

    async def load(self, session_id):  # noqa: ARG002
        return []

    async def save(self, session_id, history):
        self.saved = (session_id, history)


def _direct_service(fake_agent: Any) -> tuple[ChatService, _FakeHistoryStore]:
    history_store = _FakeHistoryStore()
    service = object.__new__(ChatService)
    service.zhiyuan_agent = fake_agent
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


def test_chat_service_initializes_zhiyuan_agent_direct_by_default(monkeypatch, mocker, mock_llm_client):
    monkeypatch.delenv("ZHIYUAN_AGENT_ENABLED", raising=False)
    monkeypatch.delenv("ZHIYUAN_AGENT_ROLLOUT_PERCENT", raising=False)
    fake_direct_agent = object()
    direct_ctor = mocker.patch("app.service.ZhiyuanAgent", return_value=fake_direct_agent)

    service = ChatService(mock_llm_client, _FakeHistoryStore())  # type: ignore[arg-type]

    direct_ctor.assert_called_once_with(mock_llm_client)
    assert service.zhiyuan_agent is fake_direct_agent


async def test_service_zhiyuan_agent_direct_runs_without_feature_flag():
    class FakeDirectAgent:
        called = False

        async def run_with_message_deltas(self, user_prompt, message_history=None, deps=None, on_progress=None):  # noqa: ARG002
            self.called = True
            tool_payload = {
                "next_step": "respond",
                "data": {"summary": "已按 4.0 direct 处理。"},
                "message": "已按 4.0 direct 处理。",
            }
            new_messages = _direct_messages(
                tool_name="query_plan",
                tool_payload=tool_payload,
                reply=tool_payload["message"],
            )
            return tool_payload["message"], new_messages, [*(message_history or []), *new_messages], _direct_usage()

    fake_agent = FakeDirectAgent()
    service, history_store = _direct_service(fake_agent)
    ctx = _direct_context()

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

    assert isinstance(reply, str)
    assert "4.0 direct" in reply
    assert fake_agent.called is True
    assert history_store.saved is not None


async def test_service_zhiyuan_agent_direct_runs_without_available_score():
    class FakeDirectAgent:
        called = False

        async def run_with_message_deltas(self, user_prompt, message_history=None, deps=None, on_progress=None):  # noqa: ARG002
            self.called = True
            tool_payload = {
                "next_step": "respond",
                "data": {"summary": "还缺少有效成绩，先按已有信息回答。"},
                "message": "还缺少有效成绩，先按已有信息回答。",
            }
            new_messages = _direct_messages(
                tool_name="query_plan",
                tool_payload=tool_payload,
                reply=tool_payload["message"],
            )
            return tool_payload["message"], new_messages, [*(message_history or []), *new_messages], _direct_usage()

    fake_agent = FakeDirectAgent()
    service, history_store = _direct_service(fake_agent)
    ctx = _direct_context()
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

    assert isinstance(reply, str)
    assert "缺少有效成绩" in reply
    assert fake_agent.called is True
    assert history_store.saved is not None


async def test_service_zhiyuan_agent_direct_guards_unbacked_confirmation_preview():
    raw_reply = (
        "好的，我帮你把**公办**作为明确要求，**排除民办院校**。预览如下：\n\n"
        "| 项目 | 内容 |\n"
        "|------|------|\n"
        "| 要求类型 | 只看公办 |\n"
        "| 公办 | 保留 |\n"
        "| 民办 | 排除 |\n\n"
        "确认后，当前方案里所有**民办院校**会被移出，仅保留公办院校。是否确认？"
    )

    class FakeDirectAgent:
        async def run_with_message_deltas(self, user_prompt, message_history=None, deps=None, on_progress=None):  # noqa: ARG002
            new_messages = [ModelResponse(parts=[TextPart(content=raw_reply)])]
            usage = SimpleNamespace(
                requests=1,
                input_tokens=100,
                output_tokens=20,
                total_tokens=120,
                tool_calls=0,
            )
            return raw_reply, new_messages, [*(message_history or []), *new_messages], usage

    service, history_store = _direct_service(FakeDirectAgent())
    ctx = _direct_context()

    reply = await service._maybe_handle_zhiyuan_agent_direct_route(
        session_id=ctx.sessionid,
        user_id=ctx.userid,
        content="就看公办吧",
        history=[],
        request_context=ctx,
        message_history=[],
        turn_started_at=time.monotonic(),
        on_progress=None,
    )

    assert isinstance(reply, str)
    assert "还没有生成可确认的调整预览" in reply
    assert "是否确认" not in reply
    assert history_store.saved is not None
    saved_texts = [
        part.content
        for message in history_store.saved[1]
        if isinstance(message, ModelResponse)
        for part in message.parts
        if isinstance(part, TextPart)
    ]
    assert any("还没有生成可确认的调整预览" in text for text in saved_texts)
    assert all("是否确认" not in text for text in saved_texts)


async def test_service_zhiyuan_agent_direct_error_does_not_fallback_to_legacy_agent():
    class FakeDirectAgent:
        async def run_with_message_deltas(self, user_prompt, message_history=None, deps=None, on_progress=None):  # noqa: ARG002
            raise RuntimeError("direct failed")

    service, history_store = _direct_service(FakeDirectAgent())
    ctx = _direct_context()

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

    assert isinstance(reply, str)
    assert "没有明确确认前，不会改动报考条件或方案" in reply
    assert history_store.saved is not None
    assert not hasattr(service, "agent")


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
    ctx = _direct_context(pending=True)

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
    ctx = _direct_context()
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


async def test_service_zhiyuan_agent_direct_plan_generation_pending_card():
    pending_id = "pending-direct-plan-generation"
    pending_state = {
        "type": "pendingConfirmation",
        "pendingId": pending_id,
        "sessionId": "session-direct-plan-generation",
        "kind": "plan_generation",
        "status": "active",
        "actionFamily": "regenerate_order",
        "summary": "补一个更安全的专业并重新生成排序方案。",
        "executionPayload": {
            "action_family": "regenerate_order",
            "atomic_actions": [
                {
                    "action_type": "regenerate_order",
                    "filters": {"review_issue_code": "probability_gap"},
                }
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
    ctx = _direct_context()
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
        content="专业组里面有没有录取率太悬的 能不能补一个安全一点的专业 先给我看预览",
        history=[],
        request_context=ctx,
        message_history=[],
        turn_started_at=time.monotonic(),
        on_progress=None,
    )

    assert getattr(reply, "primary", "").startswith("已列出调整预览")
    assert len(reply.followups) == 1
    card_payload = json.loads(reply.followups[0].content)
    assert card_payload["kind"] == "plan_generation"
    assert card_payload["actionFamily"] == "regenerate_order"
    assert card_payload["title"] == "确认重排方案"
    assert card_payload["pendingId"] == pending_id
    assert history_store.saved is not None


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
    ctx = _direct_context()
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
    ctx = _direct_context()
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
    ctx = _direct_context()

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


def test_observability_fields_include_direct_timing_fields():
    ctx = _direct_context()
    ctx.agent_observability["intentEntityProfileDurationMs"] = 12
    ctx.agent_observability["intentSideEffectDurationMs"] = 7

    fields = _observability_timing_fields(ctx)

    assert fields == {
        "intentEntityProfileDurationMs": 12,
        "intentSideEffectDurationMs": 7,
    }


@pytest.mark.asyncio
async def test_save_direct_guard_history_appends_route_observability(mocker):
    from app.service import _save_direct_guard_history

    saved = {}

    class FakeHistoryStore:
        async def save(self, session_id, history):
            saved["session_id"] = session_id
            saved["history"] = history

    ctx = _direct_context()

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
    assert len(route_messages) == 1
    route_text = "\n".join(
        part.content
        for message in route_messages
        for part in getattr(message, "parts", []) or []
        if isinstance(part, TextPart)
    )
    assert "conversation_turn_event" in route_text


@pytest.mark.skipif(
    os.getenv("RUN_ZHIYUAN_AGENT_DIRECT") != "1",
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
        deps = deps or _direct_context()
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

    async def test_exclude_cooperative_program_object_never_cancels_pending(self):
        _, calls, _ = await self._run_case("中外合作都不要了")
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
