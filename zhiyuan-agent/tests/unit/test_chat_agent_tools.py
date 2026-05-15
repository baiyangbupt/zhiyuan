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

    def test_plan_query_tool_schema_exposes_enums_for_scope_and_match_mode(self):
        from app.tools.plan_query_tool import query_volunteer_plan

        schema = Tool(query_volunteer_plan).function_schema.json_schema

        assert schema["properties"]["scope"]["enum"] == ["auto", "plan", "candidate", "plan_then_candidate"]
        assert schema["properties"]["match_mode"]["enum"] == ["and", "or"]

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
            from app.tools.city_intent_tool import extract_city_intent, extract_negative_city_intent
            from app.tools.major_intent_tool import extract_major_intent, extract_negative_major_intent
            from app.tools.school_intent_tool import extract_school_intent

            ChatAgent(client)

            registered_tools = agent_cls.call_args.kwargs["tools"]
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
            from app.tools.intent_state_tool import update_volunteer_intent_state
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
            assert update_volunteer_intent_state in registered_tools
            registered_names = {tool.__name__ for tool in registered_tools}
            assert "analyze_volunteer_intent_change" not in registered_names

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
