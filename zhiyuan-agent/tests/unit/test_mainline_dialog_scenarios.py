"""Mainline user-dialog scenario tests for Explore/Intent/Plan handoff."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart

from app.data.history_store import ChatHistoryStore
from app.service import ChatService, ChatServiceResponseEnvelope

RELEASE_400_PLAN_OPERATION_CASES_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_regression_400_plan_operation_cases.json"
RELEASE_400_EXPLORE_INTENT_CASES_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_regression_400_explore_intent_cases.json"
RELEASE_400_READONLY_REAL_SESSION_CASES_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_regression_400_readonly_real_session_cases.json"
RELEASE_400_REVIEW_REPAIR_CASES_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_regression_400_review_repair_cases.json"
RELEASE_400_PRODUCTION_ABSTRACTED_CASES_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_regression_400_production_abstracted_cases.json"



def _run(coro):
    return asyncio.run(coro)


class _ScenarioAgent:
    def __init__(self, turns: list[dict]):
        self.calls: list[dict] = []
        self._turns = turns

    async def run_with_message_deltas(self, user_prompt, message_history=None, deps=None, on_progress=None):
        self.calls.append(
            {
                "user_prompt": user_prompt,
                "message_history_len": len(message_history or []),
                "pending_confirmation": (
                    deps.conversation_phase.pending if deps and deps.conversation_phase else None
                ),
                "planning_summary": deps.planning_summary if deps else None,
            }
        )
        turn = self._turns[len(self.calls) - 1]
        reply = turn["reply"]
        tool_calls = turn.get("tool_calls") or []
        tool_returns = turn.get("tool_returns") or []
        new_messages = [ModelRequest(parts=[UserPromptPart(content=user_prompt)])]
        if tool_calls:
            new_messages.append(ModelResponse(parts=tool_calls, model_name="test-model"))
        if tool_returns:
            new_messages.append(ModelRequest(parts=tool_returns))
        new_messages.append(ModelResponse(parts=[TextPart(content=reply)], model_name="test-model"))
        usage = MagicMock(
            input_tokens=1,
            output_tokens=1,
            total_tokens=2,
            requests=1,
            tool_calls=len(tool_calls),
        )
        return reply, new_messages, (message_history or []) + new_messages, usage


def _tool_call(name: str, args: dict | None = None, call_id: str = "call-1") -> ToolCallPart:
    return ToolCallPart(tool_name=name, args=args or {}, tool_call_id=call_id)


def _tool_return(name: str, content: dict, call_id: str = "call-1") -> ToolReturnPart:
    return ToolReturnPart(tool_name=name, content=json.dumps(content, ensure_ascii=False), tool_call_id=call_id)


def _workspace_targets(reply: ChatServiceResponseEnvelope) -> list[str]:
    return [json.loads(item.content)["targetView"] for item in reply.followups]


def _semantic_pending(action: str, confidence: float = 0.95, reason: str = "test"):
    return MagicMock(action=action, confidence=confidence, reason=reason)


def _semantic_composite_goal(action: str = "none", confidence: float = 0.2, reason: str = "test"):
    return MagicMock(
        action=action,
        confidence=confidence,
        reason=reason,
        scopeType="major",
        targetValues=[],
        negativeValues=["会计"],
        maxTuitionPerYear=None,
        constraintIntentType="default" if action == "none" else "default",
    )


def _planning_state_response(version: int = 12) -> dict:
    return {"code": 0, "data": {"version": version}}


def _user_goal_fix_proposal_response(
    *,
    proposal_id: str,
    strategy: str,
    source_version: int,
    title: str,
    summary: str,
    action_summaries: list[str] | None = None,
) -> dict:
    return {
        "code": 0,
        "data": {
            "proposalSource": "user_goal",
            "proposals": [
                {
                    "proposalId": proposal_id,
                    "strategy": strategy,
                    "sourceVersionGuard": source_version,
                    "title": title,
                    "summary": summary,
                    "actionSummaries": action_summaries or [summary],
                    "confidence": "high",
                    "feasibility": "ready",
                    "requiresConfirmation": True,
                    "selected": True,
                }
            ],
        },
    }


def _user_goal_fix_proposal_facts_response(
    *,
    proposal_id: str,
    strategy: str,
    source_version: int,
    title: str,
    summary: str,
) -> dict:
    return {
        "code": 0,
        "data": {
            "sourceVersionGuard": source_version,
            "proposalSource": "user_goal",
            "proposals": [
                {
                    "proposalId": proposal_id,
                    "proposalSource": "user_goal",
                    "sourceVersion": source_version,
                    "sourceVersionGuard": source_version,
                    "strategy": strategy,
                    "status": "ready",
                    "title": title,
                    "summary": summary,
                    "impact": "确认后会同步调整当前方案。",
                    "actionSummaries": [summary],
                    "requiresConfirmation": True,
                    "actions": [{"actionType": "remove_volunteers", "removeVolunteerIds": ["v-1"]}],
                    "dryRunResult": {"status": "ready"},
                }
            ],
        },
    }


def _build_service(tmp_path, agent: _ScenarioAgent) -> ChatService:
    store = ChatHistoryStore(str(tmp_path / "history.db"))
    client = MagicMock()
    client.model = MagicMock()
    client.model_settings = {}
    with patch("app.service.ZhiyuanAgent", return_value=agent):
        return ChatService(client, store)


def _load_release_400_plan_operation_cases() -> list[dict]:
    return json.loads(RELEASE_400_PLAN_OPERATION_CASES_PATH.read_text(encoding="utf-8"))


def _load_release_400_explore_intent_cases() -> list[dict]:
    return json.loads(RELEASE_400_EXPLORE_INTENT_CASES_PATH.read_text(encoding="utf-8"))


def _load_release_400_readonly_real_session_cases() -> list[dict]:
    return json.loads(RELEASE_400_READONLY_REAL_SESSION_CASES_PATH.read_text(encoding="utf-8"))


def _load_release_400_review_repair_payload() -> dict:
    return json.loads(RELEASE_400_REVIEW_REPAIR_CASES_PATH.read_text(encoding="utf-8"))


def _expand_case_payload(payload: dict) -> list[dict]:
    defaults = payload.get("defaults") or {}
    prompt_defaults = defaults.get("promptDefaults") or {}
    case_defaults = {key: value for key, value in defaults.items() if key != "promptDefaults"}
    expanded_cases = []
    for case in payload["cases"]:
        merged = {**case_defaults, **case}
        for key in ("flow", "coverage"):
            merged[key] = list(dict.fromkeys([*(case_defaults.get(key) or []), *(case.get(key) or [])]))
        merged["prompts"] = [
            {
                **prompt_defaults,
                **step,
                "assertNotContains": list(
                    dict.fromkeys([*(prompt_defaults.get("assertNotContains") or []), *(step.get("assertNotContains") or [])])
                ),
                "qualityFocus": list(
                    dict.fromkeys([*(prompt_defaults.get("qualityFocus") or []), *(step.get("qualityFocus") or [])])
                ),
            }
            for step in case["prompts"]
        ]
        expanded_cases.append(merged)
    return expanded_cases


def _load_release_400_review_repair_cases() -> list[dict]:
    payload = _load_release_400_review_repair_payload()
    return _expand_case_payload(payload)


def _load_release_400_production_abstracted_payload() -> dict:
    return json.loads(RELEASE_400_PRODUCTION_ABSTRACTED_CASES_PATH.read_text(encoding="utf-8"))


def _load_release_400_production_abstracted_cases() -> list[dict]:
    return _expand_case_payload(_load_release_400_production_abstracted_payload())


def test_release_400_plan_operation_case_catalog_covers_plan_operations_and_runtime_history():
    cases = _load_release_400_plan_operation_cases()

    assert len(cases) >= 5
    assert len({case["name"] for case in cases}) == len(cases)
    coverage = {tag for case in cases for tag in case["coverage"]}
    required_tags = {
        "release_4_0_0",
        "zhiyuan_agent_direct",
        "runtime_history",
        "major_model",
        "majorGroup_model",
        "school_rank_sort",
        "unit_level_operation",
        "name_match",
        "abbrev_tolerant",
        "preview_confirm_apply",
    }
    assert required_tags.issubset(coverage)

    banned_terms = {"payload", "stage", "action_family", "volunteerId", "草稿"}
    all_steps = [step for case in cases for step in case["prompts"]]
    for case in cases:
        assert case["assertPlanStyle"] is True
        assert case["prompts"]
        assert case["coverage"]
        assert case["flow"]
        for step in case["prompts"]:
            assert isinstance(step, dict)
            assert step.get("prompt")
            assert step.get("assertContains") or step.get("assertContainsAny")
            assert banned_terms.intersection(set(step.get("assertNotContains") or [])) == banned_terms

    assert any(step.get("assertFollowupTarget") == "ordered" for step in all_steps)
    assert any("按院校层次排序" in step["prompt"] for step in all_steps)
    assert any("第3个专业组移到第5位" in step["prompt"] for step in all_steps)
    assert any("河南农大建筑" in step["prompt"] for step in all_steps)


def test_release_400_explore_intent_case_catalog_covers_front_layers_before_plan_tuning():
    cases = _load_release_400_explore_intent_cases()

    assert len(cases) >= 8
    assert len({case["name"] for case in cases}) == len(cases)
    coverage = {tag for case in cases for tag in case["coverage"]}
    required_tags = {
        "release_4_0_0",
        "zhiyuan_agent_direct",
        "major_explore",
        "major_compare",
        "career_explore",
        "career_compare",
        "career_reference_boundary",
        "school_explore",
        "region_explore",
        "explicit_major_requirement",
        "explicit_region_requirement",
        "positive_negative_intent_mix",
        "priority_reference_boundary",
        "region_priority_reference_boundary",
        "priority_confirmable_boundary",
        "school_priority_reference_boundary",
        "pending_intent",
        "no_duplicate_intent",
        "confirmation_boundary",
        "candidate_explore",
        "candidate_match",
        "candidate_results",
        "candidate_risk_explanation",
        "eligibility_explanation",
        "readonly_no_pending_intent",
        "no_premature_plan_apply",
        "plan_status",
        "plan_analysis",
        "plan_impact",
    }
    assert required_tags.issubset(coverage)

    banned_terms = {"payload", "stage", "action_family", "volunteerId", "草稿"}
    all_steps = [step for case in cases for step in case["prompts"]]
    for case in cases:
        assert case["assertPlanStyle"] is True
        assert case["prompts"]
        assert case["coverage"]
        assert set(case["flow"]).issubset({"explore", "intent", "plan"})
        for step in case["prompts"]:
            assert isinstance(step, dict)
            assert step.get("prompt")
            assert step.get("assertContains") or step.get("assertContainsAny")
            assert banned_terms.intersection(set(step.get("assertNotContains") or [])) == banned_terms

    prompts = "\n".join(step["prompt"] for step in all_steps)
    assert "法学和财经" in prompts
    assert "体制内和读研" in prompts
    assert "护理和中西医结合不要" in prompts
    assert "北京先不要了" in prompts
    assert "天津商业大学和河北经贸大学" in prompts
    assert "先不确认" in prompts
    assert "分数刚好压线" in prompts
    assert "没有专项资格" in prompts


def test_release_400_readonly_real_session_cases_cover_no_workspace_card_smoke():
    cases = _load_release_400_readonly_real_session_cases()

    assert len(cases) >= 2
    assert len({case["name"] for case in cases}) == len(cases)
    coverage = {tag for case in cases for tag in case["coverage"]}
    required_tags = {
        "release_4_0_0",
        "zhiyuan_agent_direct",
        "real_session",
        "career_explore",
        "candidate_risk_explanation",
        "plan_analysis",
        "readonly_no_workspace_card",
    }
    assert required_tags.issubset(coverage)

    banned_terms = {"payload", "stage", "action_family", "volunteerId", "草稿"}
    all_steps = [step for case in cases for step in case["prompts"]]
    for case in cases:
        assert case["sessionId"] == "17"
        assert case["assertPlanStyle"] is True
        assert set(case["flow"]).issubset({"explore", "plan"})
        for step in case["prompts"]:
            assert isinstance(step, dict)
            assert step.get("prompt")
            assert step.get("assertContains") or step.get("assertContainsAny")
            assert step.get("assertNoFollowups") is True
            assert banned_terms.intersection(set(step.get("assertNotContains") or [])) == banned_terms

    prompts = "\n".join(step["prompt"] for step in all_steps)
    assert "体制内稳定就业" in prompts
    assert "分数刚好压线" in prompts


def test_release_400_review_repair_case_catalog_covers_review_and_repair_boundaries():
    payload = _load_release_400_review_repair_payload()
    cases = _load_release_400_review_repair_cases()

    assert payload["metadata"]["release"] == "4.0.0"
    assert len(cases) >= 7
    assert len({case["name"] for case in cases}) == len(cases)

    coverage = {tag for case in cases for tag in case["coverage"]}
    required_tags = {
        "release_4_0_0",
        "zhiyuan_agent_direct",
        "review_repair",
        "review_workspace",
        "review_then_fix",
        "candidate_shortage",
        "honest_shortage_boundary",
        "preview_confirm_apply",
        "candidate_selection_reason",
        "majorGroup_model",
        "major_group_inner_safety",
        "professional_mode",
        "excel_export",
        "review_stale",
    }
    assert required_tags.issubset(coverage)

    banned_terms = {
        "payload",
        "stage",
        "action_family",
        "volunteerId",
        "pending_plan_action",
        "pending_intent_change",
        "level1",
        "level2",
        "level3",
        "硬约束",
        "修复建议",
        "暂不可用",
        "预览验证未通过",
        "不能直接应用",
        "草稿",
    }
    all_steps = [step for case in cases for step in case["prompts"]]
    for case in cases:
        assert case["assertPlanStyle"] is True
        assert set(case["flow"]).issubset({"plan", "review"})
        assert case["coverage"]
        assert case["prompts"]
        for step in case["prompts"]:
            assert isinstance(step, dict)
            assert step.get("prompt")
            assert step.get("assertContains") or step.get("assertContainsAny")
            assert banned_terms.issubset(set(step.get("assertNotContains") or []))

    prompts = "\n".join(step["prompt"] for step in all_steps)
    assert "候选不够" in prompts
    assert "别直接动" in prompts
    assert "专业模式导出" in prompts
    assert "手动移动过志愿" in prompts
    assert any(step.get("assertFollowupType") == "pendingConfirmationCard" for step in all_steps)
    assert any(step.get("expectedActionFamily") == "review_plan" for step in all_steps)


def test_release_400_production_abstracted_cases_cover_real_dialogue_framework_risks():
    payload = _load_release_400_production_abstracted_payload()
    cases = _load_release_400_production_abstracted_cases()

    assert payload["metadata"]["release"] == "4.0.0"
    assert len(cases) >= 15
    assert len({case["name"] for case in cases}) == len(cases)

    allowed_flow = {"explore", "intent", "plan", "review"}
    coverage = {tag for case in cases for tag in case["coverage"]}
    required_tags = {
        "release_4_0_0",
        "zhiyuan_agent_direct",
        "production_dialogue_abstracted",
        "only_keep_requirement",
        "must_have_requirement",
        "negative_requirement",
        "positive_vs_negative_requirement",
        "plan_operations",
        "plan_review_strategy",
        "policy_and_requirement",
        "school_compare",
        "open_explore",
        "score_profile",
        "candidate_shortage",
        "majorGroup_model",
        "high_level_scenario",
        "scenario_to_goal_layering",
        "career_plan_scenario",
        "plan_strategy",
        "public_service_orientation",
        "no_direct_mutation",
    }
    assert required_tags.issubset(coverage)

    banned_user_terms = {
        "payload",
        "stage",
        "action_family",
        "volunteerId",
        "level1",
        "level2",
        "level3",
        "确认卡片",
        "硬要求",
        "硬约束",
        "软偏好",
        "候选池会变小",
        "不会再进入候选",
        "草稿",
    }
    all_steps = [step for case in cases for step in case["prompts"]]
    for case in cases:
        assert case["assertPlanStyle"] is True
        assert set(case["flow"]).issubset(allowed_flow)
        assert case["coverage"]
        assert case["prompts"]
        for step in case["prompts"]:
            assert isinstance(step, dict)
            assert step.get("prompt")
            assert step.get("assertContains") or step.get("assertContainsAny")
            assert banned_user_terms.issubset(set(step.get("assertNotContains") or []))

    prompts = "\n".join(step["prompt"] for step in all_steps)
    assert "我只想学临床医学" in prompts
    assert "不考虑工科，只考虑医学类" in prompts
    assert "只要电气和气象" in prompts
    assert "必须有临床医学" in prompts
    assert "仅保留江苏" in prompts
    assert "不要医学类" in prompts
    assert "预算上限20000" in prompts
    assert "淘汰掉不能要的专业" in prompts
    assert "高校专项" in prompts
    assert "方案的科学性" in prompts
    assert "航天、能源、心理学" in prompts
    assert "整体更偏体制内" in prompts
    assert "第8个志愿移到第12位" in prompts
    assert "超过6个专业的专业组" in prompts


def test_mainline_dialog_review_result_keeps_informative_summary(tmp_path):
    agent = _ScenarioAgent(
        [
            {
                "reply": "**审查结论**\n\n当前方案可用：45/45，冲8 / 稳18 / 保19，风险0项。\n\n主要提醒是高收费、边缘分和中外合作办学，建议先看审查页确认具体位置。",
                "tool_calls": [
                    _tool_call(
                        "review_plan",
                        {"focus": "overall"},
                        "review-1",
                    )
                ],
                "tool_returns": [
                    _tool_return(
                        "review_plan",
                        {
                            "applied": True,
                            "action_family": "review_plan",
                            "summary": "风险0项，提醒3项。",
                            "workspace_refresh_targets": ["review"],
                        },
                        "review-1",
                    )
                ],
            }
        ]
    )
    service = _build_service(tmp_path, agent)

    with (
        patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})),
        patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})),
        patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})),
    ):
        reply = _run(service.handle_message("session-mainline-review", "user-57", "帮我审查一下"))

    assert isinstance(reply, str)
    assert "45/45" in reply
    assert "冲8 / 稳18 / 保19" in reply
    assert "风险0项" in reply
    assert "提醒" in reply
    assert len(reply) > 60
