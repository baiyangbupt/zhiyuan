"""Mainline user-dialog scenario tests for Explore/Intent/Plan handoff."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart

from app.data.history_store import ChatHistoryStore
from app.service import ChatService, ChatServiceResponseEnvelope

MAINLINE_CASES_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_regression_mainline_cases.json"
SCIENCE_CASES_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_regression_science_cases.json"
FULL_JOURNEY_CASES_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_regression_full_journey_cases.json"
RELEASE_302_CASES_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_regression_302_agent_cases.json"
RELEASE_302_EXPLORE_INTENT_CASES_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_regression_302_explore_intent_cases.json"
RELEASE_302_READONLY_REAL_SESSION_CASES_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_regression_302_readonly_real_session_cases.json"
RELEASE_310_REVIEW_REPAIR_CASES_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_regression_310_review_repair_cases.json"


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
                "pending_plan_action": deps.pending_plan_action if deps else None,
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


def _build_service(tmp_path, agent: _ScenarioAgent) -> ChatService:
    store = ChatHistoryStore(str(tmp_path / "history.db"))
    client = MagicMock()
    client.model = MagicMock()
    client.model_settings = {}
    with patch("app.service.ChatAgent", return_value=agent):
        return ChatService(client, store)


def _load_mainline_cases() -> list[dict]:
    return json.loads(MAINLINE_CASES_PATH.read_text(encoding="utf-8"))


def _load_science_cases() -> list[dict]:
    return json.loads(SCIENCE_CASES_PATH.read_text(encoding="utf-8"))


def _load_full_journey_cases() -> list[dict]:
    return json.loads(FULL_JOURNEY_CASES_PATH.read_text(encoding="utf-8"))


def _load_release_302_cases() -> list[dict]:
    return json.loads(RELEASE_302_CASES_PATH.read_text(encoding="utf-8"))


def _load_release_302_explore_intent_cases() -> list[dict]:
    return json.loads(RELEASE_302_EXPLORE_INTENT_CASES_PATH.read_text(encoding="utf-8"))


def _load_release_302_readonly_real_session_cases() -> list[dict]:
    return json.loads(RELEASE_302_READONLY_REAL_SESSION_CASES_PATH.read_text(encoding="utf-8"))


def _load_release_310_review_repair_payload() -> dict:
    return json.loads(RELEASE_310_REVIEW_REPAIR_CASES_PATH.read_text(encoding="utf-8"))


def _load_release_310_review_repair_cases() -> list[dict]:
    payload = _load_release_310_review_repair_payload()
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


def test_mainline_dialog_case_catalog_has_current_explore_intent_plan_scenarios():
    cases = _load_mainline_cases()

    assert len(cases) >= 36
    assert len({case["name"] for case in cases}) == len(cases)
    for case in cases:
        assert case["assertPlanStyle"] is True
        assert case["prompts"]
        assert set(case["flow"]).issubset({"explore", "intent", "plan"})
        assert case["coverage"]

    complete_flow_cases = [case for case in cases if case["flow"] == ["explore", "intent", "plan"]]
    assert len(complete_flow_cases) >= 6


def test_mainline_dialog_case_catalog_covers_session57_risks_and_plan_boundaries():
    cases = _load_mainline_cases()
    case_names = {case["name"] for case in cases}
    coverage = {tag for case in cases for tag in case["coverage"]}
    required_case_names = {
        "risk-followup-remove-preview-apply-review",
        "compensation-preview-apply-post-review",
        "ordered-move-preview-apply",
        "pin-unpin-after-review",
        "school-major-group-query-then-replace",
        "colloquial-review-remove-compensation-mainline",
        "colloquial-adjustment-then-reorder-mainline",
    }
    required_tags = {
        "positive_major_intent",
        "negative_major_intent",
        "major_alias",
        "candidate_match",
        "historical_intent",
        "no_stale_candidate_refresh",
        "plan_generate",
        "plan_query",
        "plan_status",
        "plan_analysis",
        "plan_preview",
        "plan_apply",
        "confirmation_boundary",
        "ordered_workspace",
        "review_workspace",
        "plan_review",
        "risk_followup",
        "remove_units",
        "compensation_apply",
        "move_unit",
            "no_pin_user_entry",
            "no_legacy_lock",
        "group_mode",
        "school_major_query",
        "replace_units",
    }

    assert required_case_names.issubset(case_names)
    assert required_tags.issubset(coverage)
    all_prompts = "\n".join(prompt for case in cases for prompt in case["prompts"])
    assert "网络与新媒体" in all_prompts
    assert "跨境电商" in all_prompts or "跨境电子商务" in all_prompts
    assert "审计" in all_prompts
    assert "会计" in all_prompts
    assert "确认生成" in all_prompts
    assert "确认" in all_prompts
    assert "中外合作" in all_prompts
    assert "固定住" in all_prompts
    assert "广西师范大学" in all_prompts
    assert "这版有啥问题" in all_prompts
    assert "贵的先去掉" in all_prompts
    assert "现在少的这些咋补" in all_prompts
    assert "这版怎么排更合适" in all_prompts
    assert "帮我顺一下" in all_prompts


def test_science_dialog_case_catalog_has_40_engineering_scenarios():
    cases = _load_science_cases()

    assert len(cases) == 40
    assert len({case["name"] for case in cases}) == 40
    for case in cases:
        assert case["assertPlanStyle"] is True
        assert case["prompts"]
        assert set(case["flow"]).issubset({"explore", "intent", "plan"})
        assert "plan" in case["flow"]
        assert case["coverage"]

    complete_flow_cases = [case for case in cases if case["flow"] == ["explore", "intent", "plan"]]
    assert len(complete_flow_cases) >= 12


def test_science_dialog_case_catalog_covers_main_engineering_branches_and_plan_boundaries():
    cases = _load_science_cases()
    coverage = {tag for case in cases for tag in case["coverage"]}
    required_tags = {
        "computer_science",
        "electronic_information",
        "automation",
        "mechanical_engineering",
        "civil_engineering",
        "materials",
        "biomedical_engineering",
        "subject_requirement",
        "negative_major_intent",
        "plan_preview",
        "plan_apply",
        "plan_review",
    }

    assert required_tags.issubset(coverage)
    all_prompts = "\n".join(prompt for case in cases for prompt in case["prompts"])
    assert "计算机" in all_prompts
    assert "电子信息" in all_prompts
    assert "不想学土木" in all_prompts
    assert "确认" in all_prompts


def test_full_journey_dialog_case_catalog_covers_start_explore_intent_plan_adjustment():
    cases = _load_full_journey_cases()

    assert len(cases) >= 9
    assert len({case["name"] for case in cases}) == len(cases)

    allowed_flow = {"start", "explore", "intent", "plan", "review"}
    coverage = {tag for case in cases for tag in case["coverage"]}
    all_prompts = "\n".join(
        step["prompt"] if isinstance(step, dict) else str(step)
        for case in cases
        for step in case["prompts"]
    )

    for case in cases:
        assert case["assertPlanStyle"] is True
        assert set(case["flow"]).issubset(allowed_flow)
        assert {"start", "explore", "intent", "plan"}.issubset(set(case["flow"]))
        assert case["coverage"]
        assert case["prompts"]

    required_tags = {
        "full_journey",
        "opening_context",
        "major_explore",
        "career_explore",
        "school_explore",
        "soft_major_intent",
        "soft_career_intent",
        "soft_region_intent",
        "soft_school_intent",
        "hard_major_constraint",
        "hard_region_constraint",
        "plan_query",
        "candidate_explore",
        "candidate_refresh",
        "candidate_results",
        "candidate_view_state",
        "candidate_school_major_ref",
        "candidate_search_add",
        "compensation_apply",
        "replace_units",
        "compensation_preview",
        "move_ordered_unit",
        "remove_ordered_unit",
        "remove_then_add",
        "majorGroup_mutation",
        "majorGroup_operations",
        "soft_hard_intent_mix",
        "soft_intent_stability",
        "review_accuracy",
        "review_then_adjust",
        "review_then_fix",
        "move_operation",
        "preview_confirm_apply",
        "confirmation_boundary",
        "no_premature_plan_apply",
        "review_workspace",
    }
    assert required_tags.issubset(coverage)

    assert "网络与新媒体" in all_prompts
    assert "跨境电商" in all_prompts
    assert "会计审计不要" in all_prompts
    assert "体制内" in all_prompts
    assert "江苏浙江上海" in all_prompts
    assert "东北西北不要" in all_prompts
    assert "第3个专业组移到第5位" in all_prompts
    assert "删除第5个专业组" in all_prompts
    assert "先不确认" in all_prompts
    assert "确认刚才" in all_prompts
    assert "候选列表按计算机方向刷新一下" in all_prompts
    assert "湖北工程学院的计算机科学与技术" in all_prompts
    assert "概率倒挂和高收费风险" in all_prompts
    assert "风险最大的两个" in all_prompts
    assert "电气自动化" in all_prompts
    assert "第4个专业组" in all_prompts


def test_full_journey_dialog_case_catalog_has_content_assertions_and_no_internal_terms():
    cases = _load_full_journey_cases()
    banned_terms = {"payload", "stage", "action_family", "volunteerId", "草稿"}
    mutation_prompts = []

    for case in cases:
        for step in case["prompts"]:
            assert isinstance(step, dict)
            assert step.get("prompt")
            assert step.get("assertContainsAny") or step.get("assertContains")
            assert banned_terms.intersection(set(step.get("assertNotContains") or [])) == banned_terms
            prompt = step["prompt"]
            if any(token in prompt for token in ("替换", "补", "移到", "删除")):
                mutation_prompts.append(step)

    assert mutation_prompts
    preview_steps = [step for step in mutation_prompts if "确认" not in step["prompt"]]
    direct_mutation_phrases = {"已直接调整", "已直接替换", "已直接加入", "已直接移动", "已直接删除"}
    assert any(direct_mutation_phrases.intersection(set(step.get("assertNotContains") or [])) for step in preview_steps)
    all_steps = [step for case in cases for step in case["prompts"]]
    assert any(step.get("assertFollowupTarget") == "ordered" for step in all_steps)


def test_release_302_agent_case_catalog_covers_plan_operations_and_runtime_history():
    cases = _load_release_302_cases()

    assert len(cases) >= 5
    assert len({case["name"] for case in cases}) == len(cases)
    coverage = {tag for case in cases for tag in case["coverage"]}
    required_tags = {
        "release_3_0_2",
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


def test_release_302_explore_intent_case_catalog_covers_front_layers_before_plan_tuning():
    cases = _load_release_302_explore_intent_cases()

    assert len(cases) >= 8
    assert len({case["name"] for case in cases}) == len(cases)
    coverage = {tag for case in cases for tag in case["coverage"]}
    required_tags = {
        "release_3_0_2",
        "major_explore",
        "career_explore",
        "career_compare",
        "school_explore",
        "region_explore",
        "soft_major_intent",
        "soft_career_intent",
        "soft_region_intent",
        "soft_school_intent",
        "hard_major_constraint",
        "hard_region_constraint",
        "soft_hard_intent_mix",
        "intent_revision",
        "historical_intent",
        "pending_intent",
        "no_duplicate_intent",
        "candidate_explore",
        "candidate_risk_explanation",
        "eligibility_explanation",
        "readonly_no_pending_intent",
        "no_premature_plan_apply",
        "plan_status",
        "plan_analysis",
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


def test_release_302_readonly_real_session_cases_cover_no_workspace_card_smoke():
    cases = _load_release_302_readonly_real_session_cases()

    assert len(cases) >= 2
    assert len({case["name"] for case in cases}) == len(cases)
    coverage = {tag for case in cases for tag in case["coverage"]}
    required_tags = {
        "release_3_0_2",
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


def test_release_310_review_repair_case_catalog_covers_review_and_repair_boundaries():
    payload = _load_release_310_review_repair_payload()
    cases = _load_release_310_review_repair_cases()

    assert payload["metadata"]["release"] == "3.1.0"
    assert len(cases) >= 7
    assert len({case["name"] for case in cases}) == len(cases)

    coverage = {tag for case in cases for tag in case["coverage"]}
    required_tags = {
        "release_3_1_0",
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


def test_mainline_dialog_intent_preview_then_plan_status_does_not_reopen_candidate_workspace(tmp_path):
    agent = _ScenarioAgent(
        [
            {
                "reply": "我先把网络与新媒体整理成待确认偏好。确认后再作为后续报考参考。",
                "tool_calls": [
                    _tool_call(
                        "preview_current_major_intent_confirmation",
                        {"major_intents": {"level3": ["网络与新媒体"]}},
                        "intent-1",
                    )
                ],
                "tool_returns": [
                    _tool_return(
                        "preview_current_major_intent_confirmation",
                        {"status": "pending", "items": [{"content": "网络与新媒体"}]},
                        "intent-1",
                    )
                ],
            },
            {
                "reply": "**当前方案状态**\n\n排序总数：45/45。冲8 / 稳18 / 保19。风险0项，提醒3项。",
                "tool_calls": [
                    _tool_call(
                        "execute_plan_action",
                        {"plan_payload": json.dumps({"stage": "apply", "action_family": "query_state"}, ensure_ascii=False)},
                        "plan-state-1",
                    )
                ],
                "tool_returns": [
                    _tool_return(
                        "execute_plan_action",
                        {"action_family": "query_state", "summary": "45/45，冲8 / 稳18 / 保19"},
                        "plan-state-1",
                    )
                ],
            },
        ]
    )
    service = _build_service(tmp_path, agent)

    with (
        patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})),
        patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})),
        patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})),
    ):
        first = _run(service.handle_message("session-mainline-57", "user-57", "想学网络与新媒体"))
        second = _run(service.handle_message("session-mainline-57", "user-57", "现在方案怎么样"))

    assert isinstance(first, str)
    assert "确认卡片" in first
    assert "点击采纳前" in first
    assert not isinstance(second, ChatServiceResponseEnvelope)
    assert "45/45" in second
    assert "冲8 / 稳18 / 保19" in second
    assert agent.calls[1]["message_history_len"] > 0


def test_mainline_dialog_cross_border_ecommerce_uses_full_major_name_without_candidate_refresh(tmp_path):
    agent = _ScenarioAgent(
        [
            {
                "reply": "**待确认偏好**\n\n我先把跨境电子商务整理成后续偏好。这个方向和英语、经贸类基础比较相关。",
                "tool_calls": [
                    _tool_call(
                        "preview_current_major_intent_confirmation",
                        {"major_intents": {"add": ["跨境电商"]}},
                        "intent-ecommerce",
                    )
                ],
                "tool_returns": [
                    _tool_return(
                        "preview_current_major_intent_confirmation",
                        {
                            "status": "pending",
                            "items": [{"content": "跨境电子商务"}],
                            "impactAnalysis": "候选库里有广州工商学院第201组-跨境电子商务。",
                        },
                        "intent-ecommerce",
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
        reply = _run(service.handle_message("session-mainline-cross-border", "user-57", "想学跨境电商"))

    assert isinstance(reply, str)
    assert "跨境电子商务" in reply
    assert "画像" not in reply
    assert agent.calls[0]["user_prompt"] == "想学跨境电商"


def test_mainline_dialog_negative_accounting_then_confirm_plan_adjustment_uses_model_reply(tmp_path):
    preview_payload = {
        "stage": "preview",
        "action_family": "replace_units",
        "user_goal": "移出会计和审计相关志愿，补入跨境电子商务和网络与新媒体",
        "missing_inputs": [],
        "atomic_actions": [{"action_type": "replace_units"}],
        "preview_summary": "会移出会计和审计相关志愿，再补入更匹配的新方向。",
    }
    agent = _ScenarioAgent(
        [
            {
                "reply": "我先把“不想学会计”整理成待确认排除要求。当前方案里会计学占比较高，确认后可以继续看怎么替换。",
                "tool_calls": [
                    _tool_call(
                        "preview_current_major_intent_confirmation",
                        {"major_intents": {"remove": ["会计"]}},
                        "intent-accounting",
                    )
                ],
                "tool_returns": [
                    _tool_return(
                        "preview_current_major_intent_confirmation",
                        {"status": "pending", "items": [{"content": "会计学"}]},
                        "intent-accounting",
                    )
                ],
            },
            {
                "reply": "**调整预览**\n\n计划移出会计学和审计学相关志愿，再优先补入跨境电子商务、网络与新媒体等方向。确认后才会改动当前方案。",
                "tool_calls": [
                    _tool_call(
                        "execute_plan_action",
                        {"plan_payload": json.dumps(preview_payload, ensure_ascii=False)},
                        "preview-replace",
                    )
                ],
                "tool_returns": [
                    _tool_return(
                        "execute_plan_action",
                        {
                            "applied": False,
                            "action_family": "replace_units",
                            "stage": "preview",
                            "result_kind": "preview_only",
                            "summary": "会移出会计和审计相关志愿，再补入更匹配的新方向。",
                        },
                        "preview-replace",
                    )
                ],
            },
        ]
    )
    service = _build_service(tmp_path, agent)
    execution_result = json.dumps(
        {
            "applied": True,
            "action_family": "replace_units",
            "stage": "apply",
            "result_kind": "mutation_result",
            "summary": "已移出不匹配志愿，并同步刷新排序和审查结果。新的补入方向包括跨境电子商务和网络与新媒体。",
            "workspace_refresh_targets": ["ordered", "review"],
        },
        ensure_ascii=False,
    )

    pending_state: dict[str, object] = {"value": None}

    async def save_pending_mock(session_id, pending):
        pending_state["value"] = pending
        return {"code": 0, "data": {"pendingConfirmation": pending}}

    async def get_pending_mock(session_id):
        return {"code": 0, "data": {"pendingConfirmation": pending_state.get("value")}}

    with (
        patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})),
        patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})),
        patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})),
        patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})),
        patch("app.service.save_pending_confirmation", AsyncMock(side_effect=save_pending_mock)),
        patch("app.service.get_pending_confirmation", AsyncMock(side_effect=get_pending_mock)),
        patch("app.service.execute_plan_action", AsyncMock(return_value=execution_result)) as execute_mock,
    ):
        intent_reply = _run(service.handle_message("session-mainline-adjust", "user-57", "不想学会计"))
        preview_reply = _run(service.handle_message("session-mainline-adjust", "user-57", "那帮我替换掉"))
        text_confirm_reply = _run(service.handle_message("session-mainline-adjust", "user-57", "确认"))
        pending = pending_state["value"]
        assert isinstance(pending, dict)

    assert isinstance(intent_reply, str)
    assert "待确认排除要求" in intent_reply
    assert isinstance(preview_reply, ChatServiceResponseEnvelope)
    assert preview_reply.primary == ""
    pending_cards = [item for item in preview_reply.followups if item.type == "pendingConfirmationCard"]
    assert pending_cards
    pending_card_payload = json.loads(pending_cards[0].content)
    assert "确认前不会改动当前方案" in pending_card_payload["impact"]
    assert "会计" in pending_card_payload["content"]
    assert isinstance(text_confirm_reply, ChatServiceResponseEnvelope)
    assert text_confirm_reply.primary.startswith("已移出不匹配志愿")
    assert "跨境电子商务" in text_confirm_reply.primary
    assert execute_mock.await_count == 1
    assert _workspace_targets(text_confirm_reply) == ["ordered"]
    assert len(agent.calls) == 2
    assert agent.calls[1]["pending_plan_action"] is None


def test_mainline_dialog_review_result_keeps_informative_summary_and_review_workspace(tmp_path):
    agent = _ScenarioAgent(
        [
            {
                "reply": "**审查结论**\n\n当前方案可用：45/45，冲8 / 稳18 / 保19，风险0项。\n\n主要提醒是高收费、边缘分和中外合作办学，建议先看审查页确认具体位置。",
                "tool_calls": [
                    _tool_call(
                        "execute_plan_action",
                        {"plan_payload": json.dumps({"stage": "apply", "action_family": "review_plan"}, ensure_ascii=False)},
                        "review-1",
                    )
                ],
                "tool_returns": [
                    _tool_return(
                        "execute_plan_action",
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
