"""Tests for ChatAgent tool registration."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import Tool


class TestChatAgentToolRegistration:
    """Tests for ChatAgent tool registration."""

    def test_plan_query_progress_hint_covers_plan_and_candidate_scope(self):
        agent_mock = MagicMock()
        with patch("app.llm.client.OpenAIChatModel", return_value=MagicMock()), patch(
            "app.llm.client.OpenAIProvider", return_value=MagicMock()
        ), patch("app.agent.base_agent.Agent", return_value=agent_mock):
            from app.config import LLMConfig
            from app.llm.client import LLMClient
            from app.agent.chat_agent import ChatAgent

            config = LLMConfig(provider="openai", api_key="sk-test")
            client = LLMClient(config)
            agent = ChatAgent(client)

        assert agent.get_progress_hint("query_volunteer_plan") == "正在查当前方案和候选里的相关结果..."

    def test_admission_policy_progress_hint_is_registered(self):
        agent_mock = MagicMock()
        with patch("app.llm.client.OpenAIChatModel", return_value=MagicMock()), patch(
            "app.llm.client.OpenAIProvider", return_value=MagicMock()
        ), patch("app.agent.base_agent.Agent", return_value=agent_mock):
            from app.config import LLMConfig
            from app.llm.client import LLMClient
            from app.agent.chat_agent import ChatAgent

            config = LLMConfig(provider="openai", api_key="sk-test")
            client = LLMClient(config)
            agent = ChatAgent(client)

        assert agent.get_progress_hint("answer_admission_policy_question") == "正在核对报考规则和需要确认的官方依据..."
        assert agent.get_progress_hint("search_official_admission_sources") == "正在检索官方报考政策和招生信息..."
        assert agent.get_progress_hint("match_admission_rule_to_student") == "正在把招生规则和学生情况逐项匹配..."

    def test_execute_plan_action_progress_hint_uses_structured_preview_args(self):
        agent_mock = MagicMock()
        with patch("app.llm.client.OpenAIChatModel", return_value=MagicMock()), patch(
            "app.llm.client.OpenAIProvider", return_value=MagicMock()
        ), patch("app.agent.base_agent.Agent", return_value=agent_mock):
            from pydantic_ai.messages import ToolCallPart

            from app.agent.chat_agent import ChatAgent
            from app.config import LLMConfig
            from app.llm.client import LLMClient

            config = LLMConfig(provider="openai", api_key="sk-test")
            client = LLMClient(config)
            agent = ChatAgent(client)

        tool_call = ToolCallPart(
            tool_name="execute_plan_action",
            args={"action_family": "sort_ordered_plan", "stage": "preview"},
            tool_call_id="sort-preview",
        )

        assert agent.get_progress_hint_for_tool_call(tool_call) == "正在生成这次调整的影响预览..."

    def test_chat_agent_corrects_tiny_model_tool_name_typo_before_execution(self):
        with patch("app.agent.base_agent.Agent", return_value=MagicMock()):
            from pydantic_ai.messages import ToolCallPart

            from app.agent.chat_agent import ChatAgent
            from app.llm.client import LLMClient

            client = MagicMock(spec=LLMClient)
            client.model = TestModel()
            client.model_settings = {}
            agent = ChatAgent(client)

        tool_call = ToolCallPart(
            tool_name="analyze_current_cereer_direction",
            args={"career_directions": ["system_public_service"]},
            tool_call_id="career-typo",
        )
        observability: dict[str, object] = {}

        agent._normalize_tool_call_names([tool_call], observability)

        assert tool_call.tool_name == "analyze_current_career_direction"
        assert observability["normalizedToolNames"] == [
            {"from": "analyze_current_cereer_direction", "to": "analyze_current_career_direction"}
        ]

    def test_chat_agent_does_not_correct_distant_model_tool_name(self):
        with patch("app.agent.base_agent.Agent", return_value=MagicMock()):
            from pydantic_ai.messages import ToolCallPart

            from app.agent.chat_agent import ChatAgent
            from app.llm.client import LLMClient

            client = MagicMock(spec=LLMClient)
            client.model = TestModel()
            client.model_settings = {}
            agent = ChatAgent(client)

        tool_call = ToolCallPart(
            tool_name="analyze_current_plan_direction",
            args={},
            tool_call_id="wrong-family",
        )
        observability: dict[str, object] = {}

        agent._normalize_tool_call_names([tool_call], observability)

        assert tool_call.tool_name == "analyze_current_plan_direction"
        assert "normalizedToolNames" not in observability

    def test_intent_preview_tool_schema_exposes_closed_major_intent_keys(self):
        from app.tools.intent_preview_tool import preview_current_major_intent_confirmation

        schema = Tool(preview_current_major_intent_confirmation).function_schema.json_schema
        major_schema = schema["$defs"]["MajorIntentPreviewInput"]

        assert major_schema["additionalProperties"] is False
        assert set(major_schema["properties"].keys()) == {
            "level1",
            "level2",
            "level3",
            "negative_level1",
            "negative_level2",
            "negative_level3",
        }
        assert "interested" not in major_schema["properties"]
        assert "priority" not in major_schema["properties"]
        assert schema["properties"]["intent_mode"]["anyOf"][0]["enum"] == ["preference", "constraint"]

    def test_major_interest_tool_schema_accepts_explicit_major_intents(self):
        from app.tools.intent_preview_tool import analyze_current_major_interest

        schema = Tool(analyze_current_major_interest).function_schema.json_schema

        assert "major_intents" in schema["properties"]
        major_ref = schema["properties"]["major_intents"]["anyOf"][0]["$ref"]
        assert major_ref.endswith("MajorIntentPreviewInput")

    def test_career_direction_tool_schema_exposes_direction_slot_enum(self):
        from app.tools.intent_preview_tool import analyze_current_career_direction

        schema = Tool(analyze_current_career_direction).function_schema.json_schema
        direction_items = schema["properties"]["career_directions"]["anyOf"][0]["items"]

        assert "generic_direction" in schema["properties"]
        assert direction_items["enum"] == [
            "system_public_service",
            "stable_employment",
            "further_study",
            "market_employment",
        ]

    def test_plan_query_tool_schema_exposes_enums_for_scope_and_match_mode(self):
        from app.tools.plan_query_tool import query_volunteer_plan

        schema = Tool(query_volunteer_plan).function_schema.json_schema

        assert schema["properties"]["scope"]["enum"] == ["auto", "plan", "candidate", "plan_then_candidate"]
        assert schema["properties"]["match_mode"]["enum"] == ["and", "or"]

    def test_admission_policy_tool_schema_exposes_scope_and_domain_enums(self):
        from app.tools.admission_policy_tool import answer_admission_policy_question

        schema = Tool(answer_admission_policy_question).function_schema.json_schema

        assert schema["properties"]["consultation_scope"]["enum"] == [
            "general_policy",
            "province_policy",
            "school_rule",
            "school_user_fit",
            "plan_policy_impact",
            "missing_info",
        ]
        assert schema["properties"]["rule_domain"]["enum"] == [
            "general",
            "score_batch",
            "application_process",
            "eligibility",
            "physical_exam",
            "oral_exam",
            "subject_requirement",
            "transfer_major",
            "tuition_budget",
            "admission_fit",
        ]
        assert "fit_dimensions" in schema["properties"]

    def test_official_source_search_tool_schema_exposes_source_scope(self):
        from app.tools.official_source_search_tool import search_official_admission_sources

        schema = Tool(search_official_admission_sources).function_schema.json_schema

        assert schema["properties"]["source_scope"]["enum"] == [
            "general_official",
            "province_policy",
            "school_brochure",
            "school_admissions_notice",
        ]
        assert schema["properties"]["freshness"]["enum"] == [
            "noLimit",
            "oneDay",
            "oneWeek",
            "oneMonth",
            "oneYear",
        ]
        assert "official_domain" in schema["properties"]

    def test_admission_fit_match_tool_schema_exposes_fit_dimensions(self):
        from app.tools.admission_fit_match_tool import match_admission_rule_to_student

        schema = Tool(match_admission_rule_to_student).function_schema.json_schema

        assert schema["properties"]["fit_dimensions"]["anyOf"][0]["items"]["enum"] == [
            "score_rank",
            "subjects",
            "physical_exam",
            "oral_exam",
            "eligibility",
            "budget",
        ]
        assert "required_subjects" in schema["properties"]
        assert "tuition_per_year" in schema["properties"]

    def test_chat_agent_does_not_register_low_level_intent_extractors(self):
        agent_mock = MagicMock()
        with patch("app.llm.client.OpenAIChatModel", return_value=MagicMock()), patch(
            "app.llm.client.OpenAIProvider", return_value=MagicMock()
        ), patch("app.agent.base_agent.Agent", return_value=agent_mock) as agent_cls:
            from app.config import LLMConfig
            from app.llm.client import LLMClient

            config = LLMConfig(provider="openai", api_key="sk-test")
            client = LLMClient(config)

            from app.agent.chat_agent import ChatAgent
            from app.tools.admission_fit_match_tool import match_admission_rule_to_student
            from app.tools.admission_policy_tool import answer_admission_policy_question
            from app.tools.official_source_search_tool import search_official_admission_sources
            from app.tools.major_compare_tool import compare_major_options
            from app.tools.major_info_tool import get_major_introductions
            from app.tools.city_intent_tool import extract_city_intent, extract_negative_city_intent
            from app.tools.major_intent_tool import extract_major_intent, extract_negative_major_intent
            from app.tools.school_intent_tool import extract_school_intent

            ChatAgent(client)

            registered_tools = agent_cls.call_args.kwargs["tools"]
            assert match_admission_rule_to_student in registered_tools
            assert answer_admission_policy_question in registered_tools
            assert search_official_admission_sources in registered_tools
            assert compare_major_options in registered_tools
            assert get_major_introductions in registered_tools
            assert extract_school_intent not in registered_tools
            assert extract_major_intent not in registered_tools
            assert extract_negative_major_intent not in registered_tools
            assert extract_city_intent not in registered_tools
            assert extract_negative_city_intent not in registered_tools

    def test_chat_agent_does_not_register_redundant_planning_action_tools(self):
        agent_mock = MagicMock()
        with patch("app.llm.client.OpenAIChatModel", return_value=MagicMock()), patch(
            "app.llm.client.OpenAIProvider", return_value=MagicMock()
        ), patch("app.agent.base_agent.Agent", return_value=agent_mock) as agent_cls:
            from app.config import LLMConfig
            from app.llm.client import LLMClient

            config = LLMConfig(provider="openai", api_key="sk-test")
            client = LLMClient(config)

            from app.agent.chat_agent import ChatAgent

            ChatAgent(client)

            registered_tools = agent_cls.call_args.kwargs["tools"]
            registered_names = {tool.__name__ for tool in registered_tools}
            assert "select_candidates_to_draft" not in registered_names
            assert "regenerate_planning_order" not in registered_names
            assert "run_plan_review_action" not in registered_names
            assert "apply_plan_compensation_action" not in registered_names
            assert "query_planning_state" not in registered_names
            assert "query_planning_candidate_pool" not in registered_names
            assert "query_planning_draft" not in registered_names
            assert "query_planning_ordered_plan" not in registered_names
            assert "query_planning_plan_overview" not in registered_names
            assert "select_planning_draft_items" not in registered_names
            assert "remove_planning_draft_items" not in registered_names
            assert "lock_planning_draft_items" not in registered_names
            assert "ban_planning_draft_items" not in registered_names
            assert "generate_planning_ordered_plan" not in registered_names
            assert "move_planning_ordered_item" not in registered_names
            assert "pin_planning_ordered_item" not in registered_names
            assert "unpin_planning_ordered_item" not in registered_names
            assert "run_planning_review" not in registered_names
            assert "analyze_planning_plan_adjustment" not in registered_names
            assert "preview_planning_compensation" not in registered_names
            assert "apply_planning_compensation" not in registered_names

    def test_chat_agent_model_tool_call_can_pass_explicit_intent_mode(self):
        recorded: list[dict] = []

        async def fake_analyze_intent_change(
            ctx: RunContext,
            major_intents=None,
            school_intents=None,
            city_intents=None,
            edit_flag=None,
            analysis_stage="confirmed",
            career_intents=None,
            recovery_scope=None,
            confirm_enabled=True,
            intent_mode=None,
        ) -> str:
            recorded.append(
                {
                    "sessionid": ctx.deps.sessionid,
                    "city_intents": city_intents,
                    "intent_mode": intent_mode,
                    "confirm_enabled": confirm_enabled,
                }
            )
            return "ok"

        with patch("app.agent.base_agent.SkillsToolset", None):
            from app.agent.base_agent import BaseAgent
            from app.agent.context import RequestContext
            from app.agent.instructions.assembler import build_instructions as _build_instructions
            from app.llm.client import LLMClient

            client = LLMClient.__new__(LLMClient)
            client.model = TestModel(call_tools=["fake_analyze_intent_change"])
            client.model_settings = {}
            client.model.gen_tool_args = MagicMock(
                return_value={
                    "city_intents": {"negative_province": ["上海"]},
                    "intent_mode": "constraint",
                }
            )

            agent = BaseAgent(
                llm_client=client,
                instructions=_build_instructions,
                output_type=str,
                tools=[fake_analyze_intent_change],
                deps_type=RequestContext,
            )
            result = asyncio.run(
                agent.run(
                    "不去上海",
                    deps=RequestContext(userid="u1", sessionid="s1"),
                )
            )

        assert '"fake_analyze_intent_change":"ok"' in result
        assert recorded == [
            {
                "sessionid": "s1",
                "city_intents": {"negative_province": ["上海"]},
                "intent_mode": "constraint",
                "confirm_enabled": True,
            }
        ]

    def test_chat_agent_registers_interest_preview_tools(self):
        agent_mock = MagicMock()
        with patch("app.llm.client.OpenAIChatModel", return_value=MagicMock()), patch(
            "app.llm.client.OpenAIProvider", return_value=MagicMock()
        ), patch("app.agent.base_agent.Agent", return_value=agent_mock) as agent_cls:
            from app.config import LLMConfig
            from app.llm.client import LLMClient

            config = LLMConfig(provider="openai", api_key="sk-test")
            client = LLMClient(config)

            from app.agent.chat_agent import ChatAgent
            from app.tools.intent_preview_tool import (
                analyze_current_career_direction,
                analyze_current_interest,
                analyze_current_major_interest,
                analyze_current_region_interest,
                analyze_current_school_interest,
                preview_current_career_intent_confirmation,
                preview_current_intent_confirmation,
                preview_current_major_intent_confirmation,
                preview_current_region_intent_confirmation,
                preview_current_school_intent_confirmation,
            )

            ChatAgent(client)

            registered_tools = agent_cls.call_args.kwargs["tools"]
            assert analyze_current_career_direction in registered_tools
            assert analyze_current_interest in registered_tools
            assert analyze_current_school_interest in registered_tools
            assert analyze_current_major_interest in registered_tools
            assert analyze_current_region_interest in registered_tools
            assert preview_current_intent_confirmation in registered_tools
            assert preview_current_major_intent_confirmation in registered_tools
            assert preview_current_school_intent_confirmation in registered_tools
            assert preview_current_region_intent_confirmation in registered_tools
            assert preview_current_career_intent_confirmation in registered_tools
            registered_names = {tool.__name__ for tool in registered_tools}
            assert "analyze_volunteer_intent_change" not in registered_names
            assert "update_volunteer_intent_state" not in registered_names

    def test_chat_agent_uses_tool_reply_policy_for_direct_returns(self):
        with patch("app.agent.base_agent.Agent", return_value=MagicMock()):
            from pydantic_ai.messages import ToolReturnPart

            from app.agent.chat_agent import ChatAgent
            from app.llm.client import LLMClient

            client = MagicMock(spec=LLMClient)
            client.model = TestModel()
            client.model_settings = {}
            agent = ChatAgent(client)

        intent_returns = [
            ToolReturnPart(
                tool_name="preview_current_major_intent_confirmation",
                content="我先整理成待确认偏好。",
                tool_call_id="intent-preview-call",
            )
        ]
        assert (
            agent.should_return_directly_from_tool(
                ["preview_current_major_intent_confirmation"],
                intent_returns,
                None,
            )
            is True
        )
        assert agent.should_return_directly_from_tool(["execute_plan_action"], [], None) is False
        assert agent.should_return_directly_from_tool(
            ["preview_current_major_intent_confirmation", "query_volunteer_plan"],
            intent_returns,
            None,
        ) is False

    def test_chat_agent_direct_returns_plan_selection_blocking_error(self):
        with patch("app.agent.base_agent.Agent", return_value=MagicMock()):
            from pydantic_ai.messages import ToolReturnPart

            from app.agent.chat_agent import ChatAgent
            from app.llm.client import LLMClient

            client = MagicMock(spec=LLMClient)
            client.model = TestModel()
            client.model_settings = {}
            agent = ChatAgent(client)

        tool_returns = [
            ToolReturnPart(
                tool_name="execute_plan_action",
                content='{"result_kind":"error","summary":"我还没有唯一定位到这个志愿，请点选或补充学校专业组。","reply_focus":["missing_inputs","needs_volunteer_selection"]}',
                tool_call_id="call-1",
            )
        ]

        assert agent.should_return_directly_from_tool(["execute_plan_action"], tool_returns, None) is True
        assert (
            agent.render_direct_tool_output(["execute_plan_action"], tool_returns, None)
            == "我还没有唯一定位到这个志愿，请点选或补充学校专业组。"
        )

    def test_chat_agent_direct_returns_incomplete_plan_payload_blocking_error(self):
        with patch("app.agent.base_agent.Agent", return_value=MagicMock()):
            from pydantic_ai.messages import ToolReturnPart

            from app.agent.chat_agent import ChatAgent
            from app.llm.client import LLMClient

            client = MagicMock(spec=LLMClient)
            client.model = TestModel()
            client.model_settings = {}
            agent = ChatAgent(client)

        tool_returns = [
            ToolReturnPart(
                tool_name="execute_plan_action",
                content=(
                    '{"result_kind":"error","summary":"这次还没有形成可确认的方案调整内容。",'
                    '"reply_focus":["missing_plan_payload"]}'
                ),
                tool_call_id="call-1",
            )
        ]

        assert agent.should_return_directly_from_tool(["execute_plan_action"], tool_returns, None) is True
        assert (
            agent.render_direct_tool_output(["execute_plan_action"], tool_returns, None)
            == "这次还没有形成可确认的方案调整内容。"
        )

    def test_chat_agent_does_not_direct_return_normal_plan_preview(self):
        with patch("app.agent.base_agent.Agent", return_value=MagicMock()):
            from pydantic_ai.messages import ToolReturnPart

            from app.agent.chat_agent import ChatAgent
            from app.llm.client import LLMClient

            client = MagicMock(spec=LLMClient)
            client.model = TestModel()
            client.model_settings = {}
            agent = ChatAgent(client)

        tool_returns = [
            ToolReturnPart(
                tool_name="execute_plan_action",
                content='{"result_kind":"preview_only","summary":"会把这个志愿移动到第3位。","reply_focus":["preview_only","confirmation_required"]}',
                tool_call_id="call-1",
            )
        ]

        assert agent.should_return_directly_from_tool(["execute_plan_action"], tool_returns, None) is False

    def test_chat_agent_direct_returns_ordered_unit_preview(self):
        with patch("app.agent.base_agent.Agent", return_value=MagicMock()):
            from pydantic_ai.messages import ToolReturnPart

            from app.agent.chat_agent import ChatAgent
            from app.llm.client import LLMClient

            client = MagicMock(spec=LLMClient)
            client.model = TestModel()
            client.model_settings = {}
            agent = ChatAgent(client)

        tool_returns = [
            ToolReturnPart(
                tool_name="execute_plan_action",
                content=(
                    '{"result_kind":"preview_only","summary":"会整体移动第 4 个专业组到第 2 个专业组位置。'
                    '需要你确认后才会执行。",'
                    '"reply_focus":["preview_only","confirmation_required","unit_position_preview"]}'
                ),
                tool_call_id="call-1",
            )
        ]

        assert agent.should_return_directly_from_tool(["execute_plan_action"], tool_returns, None) is True
        assert (
            agent.render_direct_tool_output(["execute_plan_action"], tool_returns, None)
            == "会整体移动第 4 个专业组到第 2 个专业组位置。需要你确认后才会执行。"
        )

    def test_chat_agent_keeps_read_only_plan_query_result_for_model_synthesis(self):
        with patch("app.agent.base_agent.Agent", return_value=MagicMock()):
            from pydantic_ai.messages import ToolReturnPart

            from app.agent.chat_agent import ChatAgent
            from app.llm.client import LLMClient

            client = MagicMock(spec=LLMClient)
            client.model = TestModel()
            client.model_settings = {}
            agent = ChatAgent(client)

        tool_returns = [
            ToolReturnPart(
                tool_name="query_volunteer_plan",
                content="候选里共命中了 5 条符合“稳 会计 审计”的机会。下面仅展示前 5 条示例：A大学-会计学（稳，录取率62%）",
                tool_call_id="query-candidate-1",
            )
        ]

        assert agent.should_return_directly_from_tool(["query_volunteer_plan"], tool_returns, None) is False
        assert agent.render_direct_tool_output(["query_volunteer_plan"], tool_returns, None) is None

    def test_chat_agent_keeps_read_only_explore_result_for_model_synthesis(self):
        with patch("app.agent.base_agent.Agent", return_value=MagicMock()):
            from pydantic_ai.messages import ToolReturnPart

            from app.agent.chat_agent import ChatAgent
            from app.llm.client import LLMClient

            client = MagicMock(spec=LLMClient)
            client.model = TestModel()
            client.model_settings = {}
            agent = ChatAgent(client)

        tool_returns = [
            ToolReturnPart(
                tool_name="analyze_current_career_direction",
                content="这轮只做分析，不会改动你的方案。\n\n当前方案对体制内方向有一定承接。",
                tool_call_id="career-readonly-direct",
            )
        ]

        assert agent.should_return_directly_from_tool(["analyze_current_career_direction"], tool_returns, None) is False
        assert agent.render_direct_tool_output(["analyze_current_career_direction"], tool_returns, None) is None

    def test_chat_agent_does_not_direct_return_plan_query_action_boundary(self):
        with patch("app.agent.base_agent.Agent", return_value=MagicMock()):
            from pydantic_ai.messages import ToolReturnPart

            from app.agent.chat_agent import ChatAgent
            from app.llm.client import LLMClient

            client = MagicMock(spec=LLMClient)
            client.model = TestModel()
            client.model_settings = {}
            agent = ChatAgent(client)

        tool_returns = [
            ToolReturnPart(
                tool_name="query_volunteer_plan",
                content="这是补齐或调整当前方案的动作诉求，不是局部查询；应先走方案动作预览，用户确认后再执行。",
                tool_call_id="query-candidate-boundary",
            )
        ]

        assert agent.should_return_directly_from_tool(["query_volunteer_plan"], tool_returns, None) is False

    def test_chat_agent_direct_returns_compensation_preview(self):
        with patch("app.agent.base_agent.Agent", return_value=MagicMock()):
            from pydantic_ai.messages import ToolReturnPart

            from app.agent.chat_agent import ChatAgent
            from app.llm.client import LLMClient

            client = MagicMock(spec=LLMClient)
            client.model = TestModel()
            client.model_settings = {}
            agent = ChatAgent(client)

        tool_returns = [
            ToolReturnPart(
                tool_name="execute_plan_action",
                content=(
                    '{"result_kind":"compensation_preview",'
                    '"summary":"当前可先看的补齐建议共有 1 项动作，预计补入 2 个志愿。",'
                    '"reply_focus":["compensation_preview"]}'
                ),
                tool_call_id="compensation-preview-direct",
            )
        ]

        assert agent.should_return_directly_from_tool(["execute_plan_action"], tool_returns, None) is True
        assert (
            agent.render_direct_tool_output(["execute_plan_action"], tool_returns, None)
            == "当前可先看的补齐建议共有 1 项动作，预计补入 2 个志愿。"
        )

    def test_chat_agent_direct_returns_sort_ordered_plan_preview(self):
        with patch("app.agent.base_agent.Agent", return_value=MagicMock()):
            from pydantic_ai.messages import ToolReturnPart

            from app.agent.chat_agent import ChatAgent
            from app.llm.client import LLMClient

            client = MagicMock(spec=LLMClient)
            client.model = TestModel()
            client.model_settings = {}
            agent = ChatAgent(client)

        tool_returns = [
            ToolReturnPart(
                tool_name="execute_plan_action",
                content=(
                    '{"action_family":"sort_ordered_plan","result_kind":"preview_only",'
                    '"summary":"会按推荐系数重新排序当前方案，推荐系数高的排在前面。需要你确认后才会执行。",'
                    '"reply_focus":["preview_only","sort_preview"]}'
                ),
                tool_call_id="sort-preview-direct",
            )
        ]

        assert agent.should_return_directly_from_tool(["execute_plan_action"], tool_returns, None) is True
        assert (
            agent.render_direct_tool_output(["execute_plan_action"], tool_returns, None)
            == "会按推荐系数重新排序当前方案，推荐系数高的排在前面。需要你确认后才会执行。"
        )

    def test_chat_agent_keeps_empty_compensation_preview_for_model_summary(self):
        with patch("app.agent.base_agent.Agent", return_value=MagicMock()):
            from pydantic_ai.messages import ToolReturnPart

            from app.agent.chat_agent import ChatAgent
            from app.llm.client import LLMClient

            client = MagicMock(spec=LLMClient)
            client.model = TestModel()
            client.model_settings = {}
            agent = ChatAgent(client)

        tool_returns = [
            ToolReturnPart(
                tool_name="execute_plan_action",
                content=(
                    '{"result_kind":"compensation_preview",'
                    '"summary":"这轮没有拿到可直接执行的调稳补齐预览。",'
                    '"reply_focus":["compensation_preview","empty_compensation_preview"]}'
                ),
                tool_call_id="empty-compensation-preview",
            )
        ]

        assert agent.should_return_directly_from_tool(["execute_plan_action"], tool_returns, None) is False

    def test_chat_agent_registers_plan_orchestration_tools(self):
        agent_mock = MagicMock()
        with patch("app.llm.client.OpenAIChatModel", return_value=MagicMock()), patch(
            "app.llm.client.OpenAIProvider", return_value=MagicMock()
        ), patch("app.agent.base_agent.Agent", return_value=agent_mock) as agent_cls:
            from app.config import LLMConfig
            from app.llm.client import LLMClient

            config = LLMConfig(provider="openai", api_key="sk-test")
            client = LLMClient(config)

            from app.agent.chat_agent import ChatAgent
            from app.tools.plan_context_tool import collect_plan_context_inputs
            from app.tools.plan_execution_tool import execute_plan_action
            from app.tools.plan_orchestration_tool import plan_next_action

            ChatAgent(client)

            registered_tools = agent_cls.call_args.kwargs["tools"]
            assert collect_plan_context_inputs in registered_tools
            assert plan_next_action in registered_tools
            assert execute_plan_action in registered_tools
            registered_names = {tool.__name__ for tool in registered_tools}
            assert "handle_planning_request" not in registered_names
            assert "query_planning_plan_overview" not in registered_names
            assert "run_planning_review" not in registered_names
            assert "analyze_planning_plan_adjustment" not in registered_names

    def test_chat_agent_hides_skill_management_tools_from_main_dialog(self):
        agent_mock = MagicMock()
        skill_toolset = MagicMock()
        with patch("app.llm.client.OpenAIChatModel", return_value=MagicMock()), patch(
            "app.llm.client.OpenAIProvider", return_value=MagicMock()
        ), patch("app.agent.base_agent.SkillsToolset", return_value=skill_toolset), patch(
            "app.agent.base_agent.Agent", return_value=agent_mock
        ) as agent_cls:
            from app.config import LLMConfig
            from app.llm.client import LLMClient

            config = LLMConfig(provider="openai", api_key="sk-test")
            client = LLMClient(config)

            from app.agent.chat_agent import ChatAgent

            chat_agent = ChatAgent(client)

            assert chat_agent.skills_toolset is skill_toolset
            assert agent_cls.call_args.kwargs["toolsets"] == []
            agent_mock.instructions.assert_called_once()

    def test_chat_agent_model_tool_call_routes_plan_status_query_through_orchestration_chain(self):
        recorded: list[dict] = []

        async def fake_collect_plan_context_inputs(
            ctx: RunContext,
        ) -> str:
            recorded.append(
                {
                    "sessionid": ctx.deps.sessionid,
                    "tool": "collect_plan_context_inputs",
                }
            )
            return '{"phase":"reviewed","ordered_count":45,"target_count":45}'

        async def fake_plan_next_action(
            ctx: RunContext,
            user_goal: str,
            action_family: str,
            user_confirmed: bool = False,
        ) -> str:
            recorded.append(
                {
                    "sessionid": ctx.deps.sessionid,
                    "tool": "plan_next_action",
                    "user_goal": user_goal,
                    "action_family": action_family,
                    "user_confirmed": user_confirmed,
                }
            )
            return '{"stage":"apply","action_family":"query_state"}'

        async def fake_execute_plan_action(
            ctx: RunContext,
            plan_payload: str,
        ) -> str:
            recorded.append(
                {
                    "sessionid": ctx.deps.sessionid,
                    "tool": "execute_plan_action",
                    "plan_payload": plan_payload,
                }
            )
            return '{"summary":"plan status ok"}'

        with patch("app.agent.base_agent.SkillsToolset", None):
            from app.agent.base_agent import BaseAgent
            from app.agent.context import RequestContext
            from app.agent.instructions.assembler import build_instructions as _build_instructions
            from app.llm.client import LLMClient

            client = LLMClient.__new__(LLMClient)
            client.model = TestModel(
                call_tools=[
                    "fake_collect_plan_context_inputs",
                    "fake_plan_next_action",
                    "fake_execute_plan_action",
                ]
            )
            client.model_settings = {}
            client.model.gen_tool_args = MagicMock(
                side_effect=[
                    {},
                    {
                        "user_goal": "查询当前方案状态",
                        "action_family": "query_state",
                        "user_confirmed": False,
                    },
                    {
                        "plan_payload": '{"stage":"apply","action_family":"query_state"}',
                    },
                ]
            )

            agent = BaseAgent(
                llm_client=client,
                instructions=_build_instructions,
                output_type=str,
                tools=[
                    fake_collect_plan_context_inputs,
                    fake_plan_next_action,
                    fake_execute_plan_action,
                ],
                deps_type=RequestContext,
            )
            result = asyncio.run(
                agent.run(
                    "方案有了么",
                    deps=RequestContext(userid="u1", sessionid="plan-status-1"),
                )
            )

        assert '"fake_execute_plan_action":"{\\"summary\\":\\"plan status ok\\"}"' in result
        assert recorded == [
            {
                "sessionid": "plan-status-1",
                "tool": "collect_plan_context_inputs",
            },
            {
                "sessionid": "plan-status-1",
                "tool": "plan_next_action",
                "user_goal": "查询当前方案状态",
                "action_family": "query_state",
                "user_confirmed": False,
            },
            {
                "sessionid": "plan-status-1",
                "tool": "execute_plan_action",
                "plan_payload": '{"stage":"apply","action_family":"query_state"}',
            },
        ]

    def test_chat_agent_model_tool_call_can_use_new_plan_orchestration_chain(self):
        recorded: list[dict] = []

        async def fake_collect_plan_context_inputs(ctx: RunContext) -> str:
            recorded.append(
                {
                    "tool": "collect_plan_context_inputs",
                    "sessionid": ctx.deps.sessionid,
                }
            )
            return '{"phase":"reviewed","ordered_total":30}'

        async def fake_plan_next_action(
            ctx: RunContext,
            user_goal: str,
            action_family: str,
            user_confirmed: bool = False,
        ) -> str:
            recorded.append(
                {
                    "tool": "plan_next_action",
                    "sessionid": ctx.deps.sessionid,
                    "user_goal": user_goal,
                    "action_family": action_family,
                    "user_confirmed": user_confirmed,
                }
            )
            return '{"stage":"apply","action_family":"analyze_adjustment"}'

        async def fake_execute_plan_action(
            ctx: RunContext,
            plan_payload: str,
        ) -> str:
            recorded.append(
                {
                    "tool": "execute_plan_action",
                    "sessionid": ctx.deps.sessionid,
                    "plan_payload": plan_payload,
                }
            )
            return '{"summary":"当前方案可以先补强保区。"}'

        with patch("app.agent.base_agent.SkillsToolset", None):
            from app.agent.base_agent import BaseAgent
            from app.agent.context import RequestContext
            from app.agent.instructions.assembler import build_instructions as _build_instructions
            from app.llm.client import LLMClient

            client = LLMClient.__new__(LLMClient)
            client.model = TestModel(
                call_tools=[
                    "fake_collect_plan_context_inputs",
                    "fake_plan_next_action",
                    "fake_execute_plan_action",
                ]
            )
            client.model_settings = {}
            client.model.gen_tool_args = MagicMock(
                side_effect=[
                    {},
                    {
                        "user_goal": "分析当前方案还能怎么优化",
                        "action_family": "analyze_adjustment",
                        "user_confirmed": True,
                    },
                    {
                        "plan_payload": '{"stage":"apply","action_family":"analyze_adjustment"}',
                    },
                ]
            )

            agent = BaseAgent(
                llm_client=client,
                instructions=_build_instructions,
                output_type=str,
                tools=[
                    fake_collect_plan_context_inputs,
                    fake_plan_next_action,
                    fake_execute_plan_action,
                ],
                deps_type=RequestContext,
            )
            result = asyncio.run(
                agent.run(
                    "看看现在方案还能怎么优化",
                    deps=RequestContext(userid="u1", sessionid="plan-chain-1"),
                )
            )

        assert '"fake_execute_plan_action":"{\\"summary\\":\\"当前方案可以先补强保区。\\"}"' in result
        assert recorded == [
            {
                "tool": "collect_plan_context_inputs",
                "sessionid": "plan-chain-1",
            },
            {
                "tool": "plan_next_action",
                "sessionid": "plan-chain-1",
                "user_goal": "分析当前方案还能怎么优化",
                "action_family": "analyze_adjustment",
                "user_confirmed": True,
            },
            {
                "tool": "execute_plan_action",
                "sessionid": "plan-chain-1",
                "plan_payload": '{"stage":"apply","action_family":"analyze_adjustment"}',
            },
        ]

    def test_chat_agent_after_intent_confirm_followup_plan_question_stays_on_plan_chain(self):
        recorded: list[str] = []

        async def fake_collect_plan_context_inputs(ctx: RunContext) -> str:
            recorded.append("collect_plan_context_inputs")
            return '{"phase":"ordered","ordered_count":45,"positive_majors":["网络与新媒体"]}'

        async def fake_plan_next_action(
            ctx: RunContext,
            user_goal: str,
            action_family: str,
            user_confirmed: bool = False,
        ) -> str:
            recorded.append(f"plan_next_action:{action_family}:{user_goal}")
            return '{"stage":"apply","action_family":"analyze_adjustment"}'

        async def fake_execute_plan_action(ctx: RunContext, plan_payload: str) -> str:
            recorded.append("execute_plan_action")
            return '{"summary":"当前方案对网络与新媒体承接偏弱，可以先看调整建议。"}'

        async def fake_analyze_intent_change(
            ctx: RunContext,
            major_intents=None,
            school_intents=None,
            city_intents=None,
            edit_flag=None,
            analysis_stage="confirmed",
            career_intents=None,
            recovery_scope=None,
            confirm_enabled=True,
            intent_mode=None,
        ) -> str:
            recorded.append("analyze_volunteer_intent_change")
            return "should not be called"

        with patch("app.agent.base_agent.SkillsToolset", None):
            from app.agent.base_agent import BaseAgent
            from app.agent.context import RequestContext
            from app.agent.instructions.assembler import build_instructions as _build_instructions
            from app.llm.client import LLMClient

            client = LLMClient.__new__(LLMClient)
            client.model = TestModel(
                call_tools=[
                    "fake_collect_plan_context_inputs",
                    "fake_plan_next_action",
                    "fake_execute_plan_action",
                ]
            )
            client.model_settings = {}
            client.model.gen_tool_args = MagicMock(
                side_effect=[
                    {},
                    {
                        "user_goal": "结合已确认的网络与新媒体偏好分析当前方案怎么调",
                        "action_family": "analyze_adjustment",
                        "user_confirmed": True,
                    },
                    {
                        "plan_payload": '{"stage":"apply","action_family":"analyze_adjustment"}',
                    },
                ]
            )

            agent = BaseAgent(
                llm_client=client,
                instructions=_build_instructions,
                output_type=str,
                tools=[
                    fake_collect_plan_context_inputs,
                    fake_plan_next_action,
                    fake_execute_plan_action,
                    fake_analyze_intent_change,
                ],
                deps_type=RequestContext,
            )
            result = asyncio.run(
                agent.run(
                    "那现在方案怎么调",
                    deps=RequestContext(
                        userid="u1",
                        sessionid="intent-plan-1",
                        chat_history=[
                            {"role": "user", "content": "想学网络与新媒体"},
                            {"role": "assistant", "content": "如果确认要把它记成偏好，可以回复确认。"},
                            {"role": "user", "content": "确认这个偏好"},
                            {"role": "assistant", "content": "好的，我记下来了。"},
                        ],
                    ),
                )
            )

        assert "网络与新媒体承接偏弱" in result
        assert recorded == [
            "collect_plan_context_inputs",
            "plan_next_action:analyze_adjustment:结合已确认的网络与新媒体偏好分析当前方案怎么调",
            "execute_plan_action",
        ]

    def test_chat_agent_explore_followup_explicit_major_preference_routes_to_intent_preview(self):
        recorded: list[dict] = []

        async def fake_preview_current_major_intent_confirmation(
            ctx: RunContext,
            intent_mode=None,
        ) -> str:
            recorded.append(
                {
                    "tool": "preview_current_major_intent_confirmation",
                    "sessionid": ctx.deps.sessionid,
                    "intent_mode": intent_mode,
                }
            )
            return '{"status":"pending","items":[{"label":"网络与新媒体","type":"major"}],"message":"可以先确认是否记成偏好。"}'

        with patch("app.agent.base_agent.SkillsToolset", None):
            from app.agent.base_agent import BaseAgent
            from app.agent.context import RequestContext
            from app.agent.instructions.assembler import build_instructions as _build_instructions
            from app.llm.client import LLMClient

            client = LLMClient.__new__(LLMClient)
            client.model = TestModel(call_tools=["fake_preview_current_major_intent_confirmation"])
            client.model_settings = {}
            client.model.gen_tool_args = MagicMock(
                return_value={
                    "intent_mode": "preference",
                }
            )

            agent = BaseAgent(
                llm_client=client,
                instructions=_build_instructions,
                output_type=str,
                tools=[fake_preview_current_major_intent_confirmation],
                deps_type=RequestContext,
            )
            result = asyncio.run(
                agent.run(
                    "那就把网络与新媒体记成偏好",
                    deps=RequestContext(
                        userid="u1",
                        sessionid="explore-intent-1",
                        chat_history=[
                            {"role": "user", "content": "网络与新媒体适合我吗"},
                            {"role": "assistant", "content": "我先从适配度、专业特点和方案承接三个角度看了一下。"},
                        ],
                    ),
                )
            )

        assert "网络与新媒体" in result
        assert recorded == [
            {
                "tool": "preview_current_major_intent_confirmation",
                "sessionid": "explore-intent-1",
                "intent_mode": "preference",
            }
        ]

    def test_chat_agent_plain_major_preference_utterance_routes_to_intent_preview(self):
        recorded: list[dict] = []

        async def fake_preview_current_major_intent_confirmation(
            ctx: RunContext,
            major_intents=None,
            intent_mode=None,
        ) -> str:
            recorded.append(
                {
                    "tool": "preview_current_major_intent_confirmation",
                    "major_intents": major_intents,
                    "intent_mode": intent_mode,
                }
            )
            return '{"status":"pending","items":[{"content":"将网络与新媒体更新为偏好方向。"}],"message":"先确认是否记成偏好。"}'

        with patch("app.agent.base_agent.SkillsToolset", None):
            from app.agent.base_agent import BaseAgent
            from app.agent.context import PlanningSummary, RequestContext
            from app.agent.instructions.assembler import build_instructions as _build_instructions
            from app.llm.client import LLMClient

            client = LLMClient.__new__(LLMClient)
            client.model = TestModel(call_tools=["fake_preview_current_major_intent_confirmation"])
            client.model_settings = {}
            client.model.gen_tool_args = MagicMock(
                return_value={
                    "major_intents": {"add": ["网络与新媒体"]},
                    "intent_mode": "preference",
                }
            )

            agent = BaseAgent(
                llm_client=client,
                instructions=_build_instructions,
                output_type=str,
                tools=[fake_preview_current_major_intent_confirmation],
                deps_type=RequestContext,
            )
            result = asyncio.run(
                agent.run(
                    "想学网络与新媒体",
                    deps=RequestContext(
                        userid="u1",
                        sessionid="session-57",
                        planning_summary=PlanningSummary(
                            phase="ordered",
                            version=2,
                            draft_total=45,
                            ordered_total=45,
                            review_warn_count=0,
                            review_risk_count=0,
                        ),
                    ),
                )
            )

        assert "网络与新媒体" in result
        assert recorded == [
            {
                "tool": "preview_current_major_intent_confirmation",
                "major_intents": {"add": ["网络与新媒体"]},
                "intent_mode": "preference",
            }
        ]

    def test_chat_agent_cross_border_ecommerce_preference_routes_to_intent_preview_not_plan(self):
        recorded: list[str] = []

        async def fake_preview_current_major_intent_confirmation(
            ctx: RunContext,
            intent_mode=None,
        ) -> str:
            recorded.append(f"intent_mode:{intent_mode}")
            return '{"status":"pending","items":[{"content":"将跨境电子商务更新为偏好方向。"}],"message":"先确认是否记成偏好。"}'

        async def fake_collect_plan_context_inputs(ctx: RunContext) -> str:
            recorded.append("collect_plan_context_inputs")
            return "should not be called"

        async def fake_plan_next_action(
            ctx: RunContext,
            user_goal: str,
            action_family: str,
            user_confirmed: bool = False,
        ) -> str:
            recorded.append("plan_next_action")
            return "should not be called"

        async def fake_execute_plan_action(ctx: RunContext, plan_payload: str) -> str:
            recorded.append("execute_plan_action")
            return "should not be called"

        with patch("app.agent.base_agent.SkillsToolset", None):
            from app.agent.base_agent import BaseAgent
            from app.agent.context import PlanningSummary, RequestContext
            from app.agent.instructions.assembler import build_instructions as _build_instructions
            from app.llm.client import LLMClient

            client = LLMClient.__new__(LLMClient)
            client.model = TestModel(call_tools=["fake_preview_current_major_intent_confirmation"])
            client.model_settings = {}
            client.model.gen_tool_args = MagicMock(
                return_value={
                    "intent_mode": "preference",
                }
            )

            agent = BaseAgent(
                llm_client=client,
                instructions=_build_instructions,
                output_type=str,
                tools=[
                    fake_preview_current_major_intent_confirmation,
                    fake_collect_plan_context_inputs,
                    fake_plan_next_action,
                    fake_execute_plan_action,
                ],
                deps_type=RequestContext,
            )
            result = asyncio.run(
                agent.run(
                    "想学跨境电商",
                    deps=RequestContext(
                        userid="u1",
                        sessionid="session-57",
                        planning_summary=PlanningSummary(
                            phase="ordered",
                            version=2,
                            draft_total=45,
                            ordered_total=45,
                            review_warn_count=0,
                            review_risk_count=0,
                        ),
                    ),
                )
            )

        assert "跨境电子商务" in result
        assert recorded == ["intent_mode:preference"]

    def test_chat_agent_negative_audit_preference_routes_to_intent_preview_not_plan(self):
        recorded: list[str] = []

        async def fake_preview_current_major_intent_confirmation(
            ctx: RunContext,
            intent_mode=None,
        ) -> str:
            recorded.append(f"intent_mode:{intent_mode}")
            return '{"status":"pending","items":[{"content":"将审计学设为排除方向。"}],"message":"先确认是否记成要求。"}'

        async def fake_collect_plan_context_inputs(ctx: RunContext) -> str:
            recorded.append("collect_plan_context_inputs")
            return "should not be called"

        async def fake_plan_next_action(
            ctx: RunContext,
            user_goal: str,
            action_family: str,
            user_confirmed: bool = False,
        ) -> str:
            recorded.append("plan_next_action")
            return "should not be called"

        async def fake_execute_plan_action(ctx: RunContext, plan_payload: str) -> str:
            recorded.append("execute_plan_action")
            return "should not be called"

        with patch("app.agent.base_agent.SkillsToolset", None):
            from app.agent.base_agent import BaseAgent
            from app.agent.context import PlanningSummary, RequestContext
            from app.agent.instructions.assembler import build_instructions as _build_instructions
            from app.llm.client import LLMClient

            client = LLMClient.__new__(LLMClient)
            client.model = TestModel(call_tools=["fake_preview_current_major_intent_confirmation"])
            client.model_settings = {}
            client.model.gen_tool_args = MagicMock(
                return_value={
                    "intent_mode": "preference",
                }
            )

            agent = BaseAgent(
                llm_client=client,
                instructions=_build_instructions,
                output_type=str,
                tools=[
                    fake_preview_current_major_intent_confirmation,
                    fake_collect_plan_context_inputs,
                    fake_plan_next_action,
                    fake_execute_plan_action,
                ],
                deps_type=RequestContext,
            )
            result = asyncio.run(
                agent.run(
                    "不想学审计",
                    deps=RequestContext(
                        userid="u1",
                        sessionid="session-57",
                        planning_summary=PlanningSummary(
                            phase="ordered",
                            version=2,
                            draft_total=45,
                            ordered_total=45,
                            review_warn_count=0,
                            review_risk_count=0,
                        ),
                    ),
                )
            )

        assert "审计学" in result
        assert recorded == ["intent_mode:preference"]

    def test_chat_agent_negative_accounting_preference_routes_to_intent_preview_not_plan(self):
        recorded: list[str] = []

        async def fake_preview_current_major_intent_confirmation(
            ctx: RunContext,
            intent_mode=None,
        ) -> str:
            recorded.append(f"intent_mode:{intent_mode}")
            return '{"status":"pending","items":[{"content":"将会计学设为排除方向。"}],"message":"先确认是否记成要求。"}'

        async def fake_collect_plan_context_inputs(ctx: RunContext) -> str:
            recorded.append("collect_plan_context_inputs")
            return "should not be called"

        async def fake_plan_next_action(
            ctx: RunContext,
            user_goal: str,
            action_family: str,
            user_confirmed: bool = False,
        ) -> str:
            recorded.append("plan_next_action")
            return "should not be called"

        async def fake_execute_plan_action(ctx: RunContext, plan_payload: str) -> str:
            recorded.append("execute_plan_action")
            return "should not be called"

        with patch("app.agent.base_agent.SkillsToolset", None):
            from app.agent.base_agent import BaseAgent
            from app.agent.context import PlanningSummary, RequestContext
            from app.agent.instructions.assembler import build_instructions as _build_instructions
            from app.llm.client import LLMClient

            client = LLMClient.__new__(LLMClient)
            client.model = TestModel(call_tools=["fake_preview_current_major_intent_confirmation"])
            client.model_settings = {}
            client.model.gen_tool_args = MagicMock(
                return_value={
                    "intent_mode": "preference",
                }
            )

            agent = BaseAgent(
                llm_client=client,
                instructions=_build_instructions,
                output_type=str,
                tools=[
                    fake_preview_current_major_intent_confirmation,
                    fake_collect_plan_context_inputs,
                    fake_plan_next_action,
                    fake_execute_plan_action,
                ],
                deps_type=RequestContext,
            )
            result = asyncio.run(
                agent.run(
                    "不想学会计",
                    deps=RequestContext(
                        userid="u1",
                        sessionid="session-57",
                        planning_summary=PlanningSummary(
                            phase="ordered",
                            version=2,
                            draft_total=45,
                            ordered_total=45,
                            review_warn_count=0,
                            review_risk_count=0,
                        ),
                    ),
                )
            )

        assert "会计学" in result
        assert recorded == ["intent_mode:preference"]

    def test_chat_agent_mixed_major_preference_routes_to_intent_preview_not_readonly_analysis(self):
        recorded: list[str] = []

        async def fake_preview_current_major_intent_confirmation(
            ctx: RunContext,
            major_intents=None,
            intent_mode=None,
        ) -> str:
            recorded.append("preview_current_major_intent_confirmation")
            return (
                '{"status":"pending","items":['
                '{"content":"偏好会计学、审计学"},'
                '{"content":"排除土木工程、建筑学"}'
                '],"message":"先确认是否记成后续参考。"}'
            )

        async def fake_analyze_current_major_interest(
            ctx: RunContext,
            intent_mode=None,
        ) -> str:
            recorded.append("analyze_current_major_interest")
            return "should not be called"

        with patch("app.agent.base_agent.SkillsToolset", None):
            from app.agent.base_agent import BaseAgent
            from app.agent.context import RequestContext
            from app.agent.instructions.assembler import build_instructions as _build_instructions
            from app.llm.client import LLMClient

            client = LLMClient.__new__(LLMClient)
            client.model = TestModel(call_tools=["fake_preview_current_major_intent_confirmation"])
            client.model_settings = {}
            client.model.gen_tool_args = MagicMock(
                return_value={
                    "major_intents": {
                        "level3": ["会计学", "审计学"],
                        "negative_level3": ["土木工程", "建筑学"],
                    },
                    "intent_mode": "preference",
                }
            )

            agent = BaseAgent(
                llm_client=client,
                instructions=_build_instructions,
                output_type=str,
                tools=[
                    fake_preview_current_major_intent_confirmation,
                    fake_analyze_current_major_interest,
                ],
                deps_type=RequestContext,
            )
            result = asyncio.run(
                agent.run(
                    "会计审计这类还行，土木建筑那种别碰",
                    deps=RequestContext(userid="u1", sessionid="mixed-major-1"),
                )
            )

        assert "会计学" in result
        assert "土木工程" in result
        assert recorded == ["preview_current_major_intent_confirmation"]

    def test_chat_agent_intent_confirmation_updates_state_without_repreviewing_intent(self):
        recorded: list[str] = []

        async def fake_update_volunteer_intent_state(
            ctx: RunContext,
            action: str,
        ) -> str:
            recorded.append(f"update_volunteer_intent_state:{action}:{ctx.deps.sessionid}")
            return '{"status":"updated","message":"好的，我已经把网络与新媒体记成后续偏好。"}'

        async def fake_analyze_volunteer_intent_change(
            ctx: RunContext,
            major_intents=None,
            school_intents=None,
            city_intents=None,
            edit_flag=None,
            analysis_stage="confirmed",
            career_intents=None,
            recovery_scope=None,
            confirm_enabled=True,
            intent_mode=None,
        ) -> str:
            recorded.append("analyze_volunteer_intent_change")
            return "should not be called"

        with patch("app.agent.base_agent.SkillsToolset", None):
            from app.agent.base_agent import BaseAgent
            from app.agent.context import RequestContext
            from app.agent.instructions.assembler import build_instructions as _build_instructions
            from app.llm.client import LLMClient

            client = LLMClient.__new__(LLMClient)
            client.model = TestModel(call_tools=["fake_update_volunteer_intent_state"])
            client.model_settings = {}
            client.model.gen_tool_args = MagicMock(return_value={"action": "confirm"})

            agent = BaseAgent(
                llm_client=client,
                instructions=_build_instructions,
                output_type=str,
                tools=[fake_update_volunteer_intent_state, fake_analyze_volunteer_intent_change],
                deps_type=RequestContext,
            )
            result = asyncio.run(
                agent.run(
                    "确认",
                    deps=RequestContext(
                        userid="u1",
                        sessionid="intent-confirm-1",
                        chat_history=[
                            {"role": "user", "content": "那就把网络与新媒体记成偏好"},
                            {"role": "assistant", "content": "可以，我会先等你确认是否把它纳入后续偏好。"},
                        ],
                    ),
                )
            )

        assert "网络与新媒体" in result
        assert recorded == ["update_volunteer_intent_state:confirm:intent-confirm-1"]

    def test_chat_agent_confirmed_negative_career_followup_conflict_question_uses_plan_chain(self):
        recorded: list[str] = []

        async def fake_collect_plan_context_inputs(ctx: RunContext) -> str:
            recorded.append("collect_plan_context_inputs")
            return '{"phase":"ordered","ordered_count":45,"career_types":["不考虑体制内/考公导向"]}'

        async def fake_plan_next_action(
            ctx: RunContext,
            user_goal: str,
            action_family: str,
            user_confirmed: bool = False,
        ) -> str:
            recorded.append(f"plan_next_action:{action_family}:{user_goal}")
            return '{"stage":"apply","action_family":"review_plan"}'

        async def fake_execute_plan_action(ctx: RunContext, plan_payload: str) -> str:
            recorded.append("execute_plan_action")
            return '{"summary":"当前方案里需要留意体制内导向较强的专业组，可以先做一次风险审查。"}'

        async def fake_analyze_volunteer_intent_change(
            ctx: RunContext,
            major_intents=None,
            school_intents=None,
            city_intents=None,
            edit_flag=None,
            analysis_stage="confirmed",
            career_intents=None,
            recovery_scope=None,
            confirm_enabled=True,
            intent_mode=None,
        ) -> str:
            recorded.append("analyze_volunteer_intent_change")
            return "should not be called"

        with patch("app.agent.base_agent.SkillsToolset", None):
            from app.agent.base_agent import BaseAgent
            from app.agent.context import RequestContext
            from app.agent.instructions.assembler import build_instructions as _build_instructions
            from app.llm.client import LLMClient

            client = LLMClient.__new__(LLMClient)
            client.model = TestModel(
                call_tools=[
                    "fake_collect_plan_context_inputs",
                    "fake_plan_next_action",
                    "fake_execute_plan_action",
                ]
            )
            client.model_settings = {}
            client.model.gen_tool_args = MagicMock(
                side_effect=[
                    {},
                    {
                        "user_goal": "结合已确认的不考虑体制内要求审查当前方案冲突",
                        "action_family": "review_plan",
                        "user_confirmed": True,
                    },
                    {
                        "plan_payload": '{"stage":"apply","action_family":"review_plan"}',
                    },
                ]
            )

            agent = BaseAgent(
                llm_client=client,
                instructions=_build_instructions,
                output_type=str,
                tools=[
                    fake_collect_plan_context_inputs,
                    fake_plan_next_action,
                    fake_execute_plan_action,
                    fake_analyze_volunteer_intent_change,
                ],
                deps_type=RequestContext,
            )
            result = asyncio.run(
                agent.run(
                    "那现在方案哪里冲突",
                    deps=RequestContext(
                        userid="u1",
                        sessionid="intent-plan-2",
                        chat_history=[
                            {"role": "user", "content": "现在不想进体制内了"},
                            {"role": "assistant", "content": "如果确认要作为要求，我会按这个方向更新。"},
                            {"role": "user", "content": "确认"},
                            {"role": "assistant", "content": "好的，我已经按你的要求更新好了。"},
                        ],
                    ),
                )
            )

        assert "体制内导向较强" in result
        assert recorded == [
            "collect_plan_context_inputs",
            "plan_next_action:review_plan:结合已确认的不考虑体制内要求审查当前方案冲突",
            "execute_plan_action",
        ]

    def test_chat_agent_plan_status_query_should_not_need_query_volunteer_plan(self):
        recorded: list[str] = []

        async def fake_collect_plan_context_inputs(ctx: RunContext) -> str:
            recorded.append("collect_plan_context_inputs")
            return '{"phase":"reviewed","ordered_count":30,"target_count":30}'

        async def fake_plan_next_action(
            ctx: RunContext,
            user_goal: str,
            action_family: str,
            user_confirmed: bool = False,
        ) -> str:
            recorded.append(f"plan_next_action:{action_family}")
            return '{"stage":"apply","action_family":"query_state"}'

        async def fake_execute_plan_action(ctx: RunContext, plan_payload: str) -> str:
            recorded.append("execute_plan_action")
            return '{"summary":"ok"}'

        async def fake_query_volunteer_plan(ctx: RunContext, query: str, scope: str = "auto") -> str:
            recorded.append("query_volunteer_plan")
            return "should not be called"

        with patch("app.agent.base_agent.SkillsToolset", None):
            from app.agent.base_agent import BaseAgent
            from app.agent.context import RequestContext
            from app.agent.instructions.assembler import build_instructions as _build_instructions
            from app.llm.client import LLMClient

            client = LLMClient.__new__(LLMClient)
            client.model = TestModel(
                call_tools=[
                    "fake_collect_plan_context_inputs",
                    "fake_plan_next_action",
                    "fake_execute_plan_action",
                ]
            )
            client.model_settings = {}
            client.model.gen_tool_args = MagicMock(
                side_effect=[
                    {},
                    {
                        "user_goal": "查询当前方案状态",
                        "action_family": "query_state",
                        "user_confirmed": False,
                    },
                    {
                        "plan_payload": '{"stage":"apply","action_family":"query_state"}',
                    },
                ]
            )

            agent = BaseAgent(
                llm_client=client,
                instructions=_build_instructions,
                output_type=str,
                tools=[
                    fake_collect_plan_context_inputs,
                    fake_plan_next_action,
                    fake_execute_plan_action,
                    fake_query_volunteer_plan,
                ],
                deps_type=RequestContext,
            )
            asyncio.run(
                agent.run(
                    "方案有了么",
                    deps=RequestContext(userid="u1", sessionid="plan-status-2"),
                )
            )

        assert recorded == [
            "collect_plan_context_inputs",
            "plan_next_action:query_state",
            "execute_plan_action",
        ]

    def test_chat_agent_plan_local_lookup_can_use_query_volunteer_plan(self):
        recorded: list[str] = []

        async def fake_query_volunteer_plan(ctx: RunContext, query: str, scope: str = "auto") -> str:
            recorded.append(f"query_volunteer_plan:{scope}:{query}")
            return "当前排序方案里命中了 1 条和“生物工程”相关的志愿"

        with patch("app.agent.base_agent.SkillsToolset", None):
            from app.agent.base_agent import BaseAgent
            from app.agent.context import RequestContext
            from app.agent.instructions.assembler import build_instructions as _build_instructions
            from app.llm.client import LLMClient

            client = LLMClient.__new__(LLMClient)
            client.model = TestModel(call_tools=["fake_query_volunteer_plan"])
            client.model_settings = {}
            client.model.gen_tool_args = MagicMock(
                return_value={
                    "query": "当前方案里有没有生物工程",
                    "scope": "plan",
                }
            )

            agent = BaseAgent(
                llm_client=client,
                instructions=_build_instructions,
                output_type=str,
                tools=[fake_query_volunteer_plan],
                deps_type=RequestContext,
            )
            result = asyncio.run(
                agent.run(
                    "当前方案里有没有生物工程",
                    deps=RequestContext(userid="u1", sessionid="plan-query-1"),
                )
            )

        assert '"fake_query_volunteer_plan":"当前排序方案里命中了 1 条和“生物工程”相关的志愿"' in result
        assert recorded == ["query_volunteer_plan:plan:当前方案里有没有生物工程"]

    def test_chat_agent_plan_local_lookup_can_pass_structured_filters_to_query_volunteer_plan(self):
        recorded: list[dict] = []

        async def fake_query_volunteer_plan(
            ctx: RunContext,
            query: str = "",
            scope: str = "auto",
            tiers=None,
            province_names=None,
            city_names=None,
            school_keywords=None,
            major_keywords=None,
            school_tags=None,
            major_tags=None,
            match_mode: str = "and",
        ) -> str:
            recorded.append(
                {
                    "scope": scope,
                    "province_names": province_names,
                    "school_keywords": school_keywords,
                    "major_keywords": major_keywords,
                    "match_mode": match_mode,
                }
            )
            return "当前排序方案里命中了 1 条符合“院校:广西师范大学；专业:工业设计”的志愿"

        with patch("app.agent.base_agent.SkillsToolset", None):
            from app.agent.base_agent import BaseAgent
            from app.agent.context import RequestContext
            from app.agent.instructions.assembler import build_instructions as _build_instructions
            from app.llm.client import LLMClient

            client = LLMClient.__new__(LLMClient)
            client.model = TestModel(call_tools=["fake_query_volunteer_plan"])
            client.model_settings = {}
            client.model.gen_tool_args = MagicMock(
                return_value={
                    "scope": "plan",
                    "school_keywords": ["广西师范大学"],
                    "major_keywords": ["工业设计"],
                    "match_mode": "and",
                }
            )

            agent = BaseAgent(
                llm_client=client,
                instructions=_build_instructions,
                output_type=str,
                tools=[fake_query_volunteer_plan],
                deps_type=RequestContext,
            )
            result = asyncio.run(
                agent.run(
                    "当前方案里有没有广西师范大学的工业设计",
                    deps=RequestContext(userid="u1", sessionid="plan-query-structured-1"),
                )
            )

        assert "广西师范大学" in result
        assert recorded == [
            {
                "scope": "plan",
                "province_names": None,
                "school_keywords": ["广西师范大学"],
                "major_keywords": ["工业设计"],
                "match_mode": "and",
            }
        ]
