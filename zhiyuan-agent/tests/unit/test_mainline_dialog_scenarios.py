"""Mainline user-dialog scenario tests for Explore/Intent/Plan handoff."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart

from app.data.history_store import ChatHistoryStore
from app.resolver.career_direction_fast_router import resolve_career_direction_fast_route
from app.resolver.fast_route_arbitrator import arbitrate_fast_route_candidates
from app.resolver.major_compare_fast_router import resolve_major_compare_fast_route
from app.resolver.major_intent_fast_router import resolve_major_intent_fast_route
from app.resolver.plan_fast_router import resolve_plan_fast_route
from app.resolver.plan_query_fast_router import resolve_plan_query_fast_route
from app.service import ChatService, ChatServiceResponseEnvelope

MAINLINE_CASES_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_regression_mainline_cases.json"
SCIENCE_CASES_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_regression_science_cases.json"
FULL_JOURNEY_CASES_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_regression_full_journey_cases.json"
RELEASE_302_CASES_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_regression_302_agent_cases.json"
RELEASE_302_EXPLORE_INTENT_CASES_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_regression_302_explore_intent_cases.json"
RELEASE_302_READONLY_REAL_SESSION_CASES_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_regression_302_readonly_real_session_cases.json"
RELEASE_302_EFFECT_PERF_CASES_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_regression_302_effect_perf_cases.json"
RELEASE_303_EFFECT_PERF_CASES_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_regression_303_effect_perf_cases.json"
RELEASE_303_OPEN_QUALITY_CASES_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_regression_303_open_quality_cases.json"
RELEASE_303_REALISTIC_USER_CASES_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_regression_303_realistic_user_cases.json"
RELEASE_303_DIALOGUE_DERIVED_CASES_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_regression_303_dialogue_derived_cases.json"
MODEL_PROVIDER_303_OPEN_REALISTIC_CASES_PATH = Path(__file__).resolve().parents[2] / "examples" / "model_provider_303_open_quality_realistic_cases.json"


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


def test_release_303_fast_router_priority_matrix_prevents_cross_layer_intercepts():
    def resolved_route(prompt: str) -> str:
        result = arbitrate_fast_route_candidates(
            prompt,
            plan_fast_decision=resolve_plan_fast_route(prompt),
            plan_query_decision=resolve_plan_query_fast_route(prompt),
            major_intent_decision=resolve_major_intent_fast_route(prompt),
            major_compare_decision=resolve_major_compare_fast_route(prompt),
            career_direction_decision=resolve_career_direction_fast_route(prompt),
        )
        route_map = {
            "plan_fast_route": "plan",
            "plan_query_fast_route": "plan_query",
            "major_intent_fast_route": "major_intent",
            "major_compare_fast_route": "major_compare",
            "career_direction_fast_route": "career_direction",
        }
        return route_map.get(result.selected_path, "full_agent")

    cases = {
        "看看现在的方案，给我一个结构化一点的结论": "plan",
        "当前方案里有没有生物工程": "plan_query",
        "青岛城市学院相关专业是不是有多个，先帮我判断一下，不要直接改方案": "plan_query",
        "我倾向法学和财政学，但护理不要": "major_intent",
        "法学和财政学哪个更适合普通家庭女生，先只分析不要记偏好": "major_compare",
        "当前方案对体制内稳定就业方向承接得怎么样，先不要改方案": "career_direction",
        "删掉山东英才学院的国际商务，然后从候选里再补一个稳档": "full_agent",
        "孩子不想学医也不想护理，方案里有没有这种坑，先看看": "plan_query",
        "医学护理这些别碰，财会还能接受，先看看影响": "major_intent",
        "孩子就想去北京天津，但分数不算高，这样是不是太冒险，先别改": "full_agent",
        "一模二模差挺多，这个成绩波动填志愿咋看": "full_agent",
        "孩子数学忽高忽低，理工还能不能碰": "full_agent",
        "分数刚压本科线，别给我画大饼": "full_agent",
        "按这个成绩波动帮我调整方案": "full_agent",
    }

    for prompt, expected_route in cases.items():
        assert resolved_route(prompt) == expected_route


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


def _load_release_302_effect_perf_cases() -> list[dict]:
    return json.loads(RELEASE_302_EFFECT_PERF_CASES_PATH.read_text(encoding="utf-8"))


def _load_release_303_effect_perf_cases() -> list[dict]:
    return json.loads(RELEASE_303_EFFECT_PERF_CASES_PATH.read_text(encoding="utf-8"))


def _load_release_303_open_quality_cases() -> list[dict]:
    return json.loads(RELEASE_303_OPEN_QUALITY_CASES_PATH.read_text(encoding="utf-8"))


def _load_release_303_realistic_user_cases() -> list[dict]:
    return json.loads(RELEASE_303_REALISTIC_USER_CASES_PATH.read_text(encoding="utf-8"))


def _load_release_303_dialogue_derived_cases() -> list[dict]:
    from examples.dialog_regression_runner import _expand_case_payload

    return _expand_case_payload(json.loads(RELEASE_303_DIALOGUE_DERIVED_CASES_PATH.read_text(encoding="utf-8")))


def _load_release_303_dialogue_derived_case_definitions() -> dict:
    from examples.dialog_case_evaluation_report import _load_case_definitions

    return _load_case_definitions(str(RELEASE_303_DIALOGUE_DERIVED_CASES_PATH))


def _load_model_provider_303_open_realistic_cases() -> list[dict]:
    return json.loads(MODEL_PROVIDER_303_OPEN_REALISTIC_CASES_PATH.read_text(encoding="utf-8"))


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


def test_release_302_effect_perf_cases_cover_quality_latency_and_clean_dialogs():
    cases = _load_release_302_effect_perf_cases()

    assert len(cases) >= 8
    assert len({case["name"] for case in cases}) == len(cases)
    coverage = {tag for case in cases for tag in case["coverage"]}
    required_tags = {
        "release_3_0_2",
        "effect_quality",
        "performance_smoke",
        "clean_dialog",
        "major_model",
        "majorGroup_model",
        "move_operation",
        "unit_level_operation",
        "abbrev_tolerant",
        "ambiguity_guard",
        "soft_major_intent",
        "hard_major_constraint",
        "confirmation_boundary",
        "no_pending_guard",
        "readonly_no_workspace_card",
    }
    assert required_tags.issubset(coverage)

    banned_terms = {"payload", "stage", "action_family", "volunteerId", "草稿"}
    all_steps = [step for case in cases for step in case["prompts"]]
    for case in cases:
        assert case["assertPlanStyle"] is True
        assert case["prompts"]
        assert case["coverage"]
        for step in case["prompts"]:
            assert isinstance(step, dict)
            assert step.get("prompt")
            assert step.get("assertContains") or step.get("assertContainsAny")
            assert banned_terms.intersection(set(step.get("assertNotContains") or [])) == banned_terms
            assert step.get("warnElapsedSeconds") or step.get("maxElapsedSeconds")

    prompts = "\n".join(step["prompt"] for step in all_steps)
    assert "结构化一点的结论" in prompts
    assert "先不要改方案" in prompts
    assert "第2个志愿移到第4位" in prompts
    assert "第4个专业组移到第2位" in prompts
    assert "普通家庭女生" in prompts
    assert "确认" in prompts


def test_release_303_effect_perf_cases_treat_quality_as_first_class_gate():
    cases = _load_release_303_effect_perf_cases()

    assert len(cases) >= 6
    assert len({case["name"] for case in cases}) == len(cases)
    coverage = {tag for case in cases for tag in case["coverage"]}
    required_tags = {
        "release_3_0_3",
        "effect_quality",
        "performance_smoke",
        "plan_fast_route",
        "rich_reply",
        "reply_quality",
        "confirmation_boundary",
        "readonly_no_workspace_card",
        "readonly_no_pending_intent",
        "no_pending_guard",
        "intent_progress",
    }
    assert required_tags.issubset(coverage)

    banned_terms = {"payload", "stage", "action_family", "volunteerId", "草稿"}
    all_steps = [step for case in cases for step in case["prompts"]]
    for case in cases:
        assert case["assertPlanStyle"] is True
        assert case["prompts"]
        assert case["coverage"]
        for step in case["prompts"]:
            assert isinstance(step, dict)
            assert step.get("prompt")
            assert step.get("assertContains") or step.get("assertContainsAny")
            assert banned_terms.intersection(set(step.get("assertNotContains") or [])) == banned_terms
            if "assertThinkingNotContains" in step:
                assert banned_terms.intersection(set(step.get("assertThinkingNotContains") or [])) == banned_terms
            assert step.get("warnElapsedSeconds") or step.get("maxElapsedSeconds")

    prompts = "\n".join(step["prompt"] for step in all_steps)
    assert "结构化一点的结论" in prompts
    assert "第4个专业组移到第2位" in prompts
    assert "按院校层次排序" in prompts
    assert "先不要改方案" in prompts
    assert "先只分析不要记偏好" in prompts
    assert "确认这个偏好" in prompts
    assert any(step.get("assertThinkingContains") for step in all_steps)
    assert any("正在按你的确认更新方案" in (step.get("assertThinkingContains") or []) for step in all_steps)
    assert any("正在按你的确认更新后续参考偏好" in (step.get("assertThinkingContains") or []) for step in all_steps)


def test_release_303_open_quality_cases_cover_richer_real_user_shapes():
    cases = _load_release_303_open_quality_cases()

    assert len(cases) >= 14
    assert len({case["name"] for case in cases}) == len(cases)
    coverage = {tag for case in cases for tag in case["coverage"]}
    required_tags = {
        "release_3_0_3",
        "open_quality",
        "pending_intent",
        "impact_followup",
        "career_explore",
        "major_compare",
        "non_law_major_compare",
        "plan_query_fast_route",
        "sort_ordered_plan",
        "preview_confirm_boundary",
        "readonly_no_workspace_card",
        "readonly_no_pending_intent",
        "no_pending_guard",
        "realistic_user_input",
        "parent_colloquial",
        "colloquial_pressure",
        "candidate_lookup",
        "budget_risk",
    }
    assert required_tags.issubset(coverage)

    banned_terms = {"payload", "stage", "action_family", "volunteerId", "草稿"}
    all_steps = [step for case in cases for step in case["prompts"]]
    for case in cases:
        assert case["assertPlanStyle"] is True
        assert case["prompts"]
        assert case["coverage"]
        assert set(case["flow"]).issubset({"explore", "intent", "plan", "review", "readonly", "confirm_guard"})
        for step in case["prompts"]:
            assert isinstance(step, dict)
            assert step.get("prompt")
            assert step.get("assertContains") or step.get("assertContainsAny")
            assert banned_terms.intersection(set(step.get("assertNotContains") or [])) == banned_terms
            assert step.get("warnElapsedSeconds") or step.get("maxElapsedSeconds")

    prompts = "\n".join(step["prompt"] for step in all_steps)
    assert "先不确认" in prompts
    assert "当前方案里青岛城市学院" in prompts
    assert "按推荐系数重新排" in prompts
    assert "网络与新媒体和跨境电子商务" in prompts
    assert "考公、稳定就业和读研" in prompts
    assert "这版是不是太冲了" in prompts
    assert "家里就想让孩子以后稳一点进体制" in prompts
    assert "法学会不会太卷" in prompts
    assert "会计审计这类还行" in prompts
    assert "候选里还有没有更稳一点的会计审计" in prompts
    assert "方案里中外合作是不是有点多" in prompts
    assert "嗯那就这样" in prompts
    assert any(step.get("assertNoFollowups") is True for step in all_steps)
    assert any(step.get("maxElapsedSeconds") for step in all_steps)


def test_model_provider_303_open_realistic_cases_cover_quality_gate_fields():
    cases = _load_model_provider_303_open_realistic_cases()

    assert len(cases) >= 15
    assert len({case["name"] for case in cases}) == len(cases)
    coverage = {tag for case in cases for tag in case["coverage"]}
    required_tags = {
        "release_3_0_3",
        "provider_benchmark",
        "open_quality",
        "realistic_user_input",
        "readonly_no_workspace_card",
        "preview_confirm_boundary",
        "lazy_short_prompt",
        "school_abbreviation",
        "major_abbreviation",
        "no_pending_guard",
    }
    assert required_tags.issubset(coverage)

    banned_terms = {"payload", "stage", "action_family", "volunteerId", "草稿"}
    all_steps = [step for case in cases for step in case["prompts"]]
    for case in cases:
        assert case["assertPlanStyle"] is True
        assert case["prompts"]
        assert case["coverage"]
        assert "provider_benchmark" in case["coverage"]
        assert "realistic_user_input" in case["coverage"]
        for step in case["prompts"]:
            assert isinstance(step, dict)
            assert step.get("prompt")
            assert step.get("assertContains") or step.get("assertContainsAny")
            assert step.get("expectedKeyPoints") or step.get("expectedKeyPointGroups")
            assert step.get("forbiddenPatterns")
            assert banned_terms.intersection(set(step.get("assertNotContains") or [])) == banned_terms
            assert step.get("warnElapsedSeconds") or step.get("maxElapsedSeconds")

    prompts = "\n".join(step["prompt"] for step in all_steps)
    assert "这版是不是太冲了" in prompts
    assert "家里就想让孩子以后稳一点进体制" in prompts
    assert "法学会不会太卷" in prompts
    assert "会计审计这类还行" in prompts
    assert "候选里还有没有更稳一点的会计审计" in prompts
    assert "方案里中外合作是不是有点多" in prompts
    assert "家里预算一年最多两万多" in prompts
    assert "这方案咋样，能不能说重点" in prompts
    assert "青城那个是不是放多了" in prompts
    assert "新媒体和跨电呢" in prompts
    assert "按好学校排下看看" in prompts
    assert "嗯可以" in prompts
    assert any(step.get("minTextLengthWarn") for step in all_steps)


def test_release_303_realistic_user_cases_cover_lazy_colloquial_and_abbrev_inputs():
    cases = _load_release_303_realistic_user_cases()

    assert len(cases) >= 9
    assert len({case["name"] for case in cases}) == len(cases)
    coverage = {tag for case in cases for tag in case["coverage"]}
    required_tags = {
        "release_3_0_3",
        "realistic_user_input",
        "lazy_short_prompt",
        "school_abbreviation",
        "major_abbreviation",
        "career_short_prompt",
        "short_intent",
        "vague_confirm",
        "preview_confirm_boundary",
        "readonly_no_workspace_card",
        "no_pending_guard",
    }
    assert required_tags.issubset(coverage)

    banned_terms = {"payload", "stage", "action_family", "volunteerId", "草稿"}
    all_steps = [step for case in cases for step in case["prompts"]]
    for case in cases:
        assert case["assertPlanStyle"] is True
        assert case["prompts"]
        assert case["coverage"]
        assert "realistic_user_input" in case["coverage"]
        assert set(case["flow"]).issubset({"explore", "intent", "plan", "review", "confirm_guard"})
        for step in case["prompts"]:
            assert isinstance(step, dict)
            assert step.get("prompt")
            assert step.get("assertContains") or step.get("assertContainsAny")
            assert step.get("expectedKeyPoints")
            assert step.get("forbiddenPatterns")
            assert banned_terms.intersection(set(step.get("assertNotContains") or [])) == banned_terms
            assert step.get("warnElapsedSeconds") or step.get("maxElapsedSeconds")

    prompts = "\n".join(step["prompt"] for step in all_steps)
    assert "这方案咋样" in prompts
    assert "保底够不够啊" in prompts
    assert "青城那个是不是放多了" in prompts
    assert "按好学校排下看看" in prompts
    assert "法和财哪个更适合女孩子" in prompts
    assert "新媒体和跨电呢" in prompts
    assert "会计审计可以 土木别要" in prompts
    assert "嗯可以" in prompts


def test_release_303_dialogue_derived_cases_cover_80_plus_real_dialogue_shapes():
    cases = _load_release_303_dialogue_derived_cases()

    assert len(cases) >= 80
    assert len({case["name"] for case in cases}) == len(cases)
    coverage = {tag for case in cases for tag in case["coverage"]}
    required_tags = {
        "release_3_0_3",
        "dialogue_derived",
        "real_dialogue_source",
        "realistic_user_input",
        "score_profile",
        "eligibility_constraints",
        "major_preference",
        "region_preference",
        "career_direction",
        "budget_tuition",
        "plan_review_strategy",
        "plan_operations",
        "followup_guard",
        "medical_check",
        "special_plan",
        "english_oral_test",
        "major_compare",
        "region_safety_tradeoff",
        "civil_service",
        "sino_foreign",
        "plan_review",
        "sort_ordered_plan",
        "confirm_guard",
    }
    assert required_tags.issubset(coverage)

    banned_terms = {"payload", "stage", "action_family", "volunteerId", "草稿"}
    all_steps = [step for case in cases for step in case["prompts"]]
    for case in cases:
        assert case["assertPlanStyle"] is True
        assert case["prompts"]
        assert "dialogue_derived" in case["coverage"]
        assert "real_dialogue_source" in case["coverage"]
        assert set(case["flow"]).issubset({"explore", "intent", "plan", "review", "readonly", "confirm_guard"})
        for step in case["prompts"]:
            assert isinstance(step, dict)
            assert step.get("prompt")
            assert step.get("assertContains") or step.get("assertContainsAny")
            assert step.get("expectedKeyPoints") or step.get("expectedKeyPointGroups")
            assert step.get("forbiddenPatterns")
            assert step.get("qualityFocus")
            assert banned_terms.intersection(set(step.get("assertNotContains") or [])) == banned_terms
            assert step.get("warnElapsedSeconds") or step.get("maxElapsedSeconds")

    prompts = "\n".join(step["prompt"] for step in all_steps)
    assert "一模二模差挺多" in prompts
    assert "英语口试到底要不要报" in prompts
    assert "色弱是不是医学化工都要避开" in prompts
    assert "会计审计还行，土木别要" in prompts
    assert "北京天津想去但别最后没学上" in prompts
    assert "家里想让孩子以后考公" in prompts
    assert "中外合作贵不贵" in prompts
    assert "审查一下有没有明显坑" in prompts
    assert "按录取率从低到高排下" in prompts
    assert "嗯那就这样" in prompts


def test_release_303_dialogue_derived_cases_have_semantic_frame_expectations():
    cases = _load_release_303_dialogue_derived_cases()
    definitions = _load_release_303_dialogue_derived_case_definitions()

    missing: list[str] = []
    expected_layers: dict[str, int] = {}
    for case in cases:
        for step_index, step in enumerate(case["prompts"], start=1):
            key = f"{case['name']}#{step_index}"
            expected = definitions.get(key, {}).get("expectedSemanticFrame") or {}
            if not expected:
                missing.append(key)
                continue
            value = expected.get("taskLayer")
            values = value if isinstance(value, list) else [value]
            for item in values:
                if item:
                    expected_layers[str(item)] = expected_layers.get(str(item), 0) + 1

    assert not missing
    assert expected_layers.get("explore", 0) >= 45
    assert expected_layers.get("plan", 0) >= 15
    assert expected_layers.get("intent", 0) >= 5


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
        patch("app.service.resolve_major_intent_fast_route", return_value=MagicMock(matched=False)),
    ):
        first = _run(service.handle_message("session-mainline-57", "user-57", "想学网络与新媒体"))
        second = _run(service.handle_message("session-mainline-57", "user-57", "现在方案怎么样"))

    assert not isinstance(first, ChatServiceResponseEnvelope)
    assert first.startswith("我先把网络与新媒体整理成待确认偏好")
    assert not isinstance(second, ChatServiceResponseEnvelope)
    assert "45/45" in second
    assert "冲8 / 稳18 / 保19" in second
    assert agent.calls[1]["message_history_len"] > 0


def test_mainline_dialog_cross_border_ecommerce_uses_full_major_name_and_candidate_refresh(tmp_path):
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
        patch("app.service.resolve_major_intent_fast_route", return_value=MagicMock(matched=False)),
    ):
        reply = _run(service.handle_message("session-mainline-cross-border", "user-57", "想学跨境电商"))

    assert not isinstance(reply, ChatServiceResponseEnvelope)
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

    with (
        patch("app.service.get_user_score_detail", AsyncMock(return_value={"code": 1})),
        patch("app.service.get_user_init_profile", AsyncMock(return_value={"code": 1})),
        patch("app.service.get_planning_workspace_state", AsyncMock(return_value={"code": 1})),
        patch("app.service.get_intent_change_cache", AsyncMock(return_value={"data": {"planEditCache": None}})),
        patch("app.service.execute_plan_action", AsyncMock(return_value=execution_result)),
        patch("app.service.resolve_major_intent_fast_route", return_value=MagicMock(matched=False)),
    ):
        intent_reply = _run(service.handle_message("session-mainline-adjust", "user-57", "不想学会计"))
        preview_reply = _run(service.handle_message("session-mainline-adjust", "user-57", "那帮我替换掉"))
        apply_reply = _run(service.handle_message("session-mainline-adjust", "user-57", "确认"))

    assert not isinstance(intent_reply, ChatServiceResponseEnvelope)
    assert "待确认排除要求" in intent_reply
    assert not isinstance(preview_reply, ChatServiceResponseEnvelope)
    assert "确认后才会改动当前方案" in preview_reply
    assert isinstance(apply_reply, ChatServiceResponseEnvelope)
    assert apply_reply.primary.startswith("已移出不匹配志愿")
    assert "跨境电子商务" in apply_reply.primary
    assert _workspace_targets(apply_reply) == ["ordered", "review"]
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

    assert isinstance(reply, ChatServiceResponseEnvelope)
    assert "45/45" in reply.primary
    assert "冲8 / 稳18 / 保19" in reply.primary
    assert "风险0项" in reply.primary
    assert "提醒" in reply.primary
    assert len(reply.primary) > 60
    assert _workspace_targets(reply) == ["review"]
