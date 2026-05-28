import json
from types import SimpleNamespace

import pytest

from app.agent.context import PlanningSummary, RequestContext, ScoreDetail
from app.models.conversation_phase import PendingConfirmation
from app.models.semantic_router import SemanticIntentFrame, SemanticRouterShadowResult
from app.resolver.semantic_intent_router import SemanticIntentRouter, _parse_semantic_frame
from app.config import SemanticRouterConfig


def test_semantic_intent_frame_serializes_quality_and_safety_fields():
    frame = SemanticIntentFrame(
        taskLayer="plan",
        verb="sort",
        topic="plan",
        sideEffect="preview",
        confidence=0.86,
        entities={"sortFields": ["schoolRank"], "positions": ["第3位"]},
        responseNeed={
            "depth": "normal",
            "requiredFacts": ["current_order", "sort_impact", "confirmation_boundary"],
            "mustNotDo": ["apply_without_confirm"],
        },
        reason="用户要求按院校层次排序，需先给预览。",
    )

    data = frame.model_dump()

    assert data["taskLayer"] == "plan"
    assert data["verb"] == "sort"
    assert data["sideEffect"] == "preview"
    assert data["entities"]["sortFields"] == ["schoolRank"]
    assert "confirmation_boundary" in data["responseNeed"]["requiredFacts"]


def test_semantic_router_shadow_event_payload_truncates_error_message():
    shadow = SemanticRouterShadowResult(
        status="error",
        durationMs=12,
        errorType="ModelHTTPError",
        errorMessage="x" * 500,
    )

    payload = shadow.event_payload()

    assert payload["status"] == "error"
    assert payload["errorType"] == "ModelHTTPError"
    assert len(payload["errorMessage"]) == 200


def test_parse_semantic_frame_accepts_plain_json_text():
    frame = _parse_semantic_frame(
        """
        {
          "taskLayer": "explore",
          "verb": "compare",
          "topic": "major",
          "sideEffect": "readonly",
          "confidence": 0.82,
          "responseNeed": {"depth": "rich", "requiredFacts": ["major_fit"]}
        }
        """
    )

    assert frame.taskLayer == "explore"
    assert frame.verb == "compare"
    assert frame.responseNeed.depth == "rich"
    assert frame.responseNeed.requiredFacts == ["major_fit"]


def test_parse_semantic_frame_accepts_json_code_fence_and_prefix():
    frame = _parse_semantic_frame(
        """
        结果如下：
        ```json
        {
          "taskLayer": "plan",
          "verb": "sort",
          "topic": "plan",
          "sideEffect": "preview",
          "entities": {"sortFields": ["schoolRank"]}
        }
        ```
        """
    )

    assert frame.taskLayer == "plan"
    assert frame.verb == "sort"
    assert frame.entities.sortFields == ["schoolRank"]


def test_parse_semantic_frame_normalizes_non_string_entity_items():
    frame = _parse_semantic_frame(
        {
            "taskLayer": "plan",
            "verb": "move",
            "topic": "plan",
            "sideEffect": "preview",
            "entities": {"positions": [3, {"from": 4, "to": 2}]},
        }
    )

    assert frame.entities.positions == ["3", '{"from": 4, "to": 2}']


def test_semantic_router_agent_uses_text_output_to_avoid_tool_choice_required():
    class _Client:
        model = "test"
        model_settings = {}
        config = type(
            "Config",
            (),
            {
                "provider": "openai_compatible",
                "model_name": "main-model",
                "api_key": "sk-test",
                "base_url": "https://llm.example.com/v1",
            },
        )()

    router = SemanticIntentRouter(_Client())

    assert router._agent().output_type is str


def test_semantic_router_reuses_main_llm_when_router_model_is_not_configured():
    class _Client:
        model = "main-model-instance"
        model_settings = {"temperature": 0.7}
        config = type(
            "Config",
            (),
            {
                "provider": "openai_compatible",
                "model_name": "main-model",
                "api_key": "sk-main",
                "base_url": "https://llm.example.com/v1",
            },
        )()

    client = _Client()
    router = SemanticIntentRouter(client, SemanticRouterConfig(_env_file=None))

    assert router.router_llm_client is client


def test_semantic_router_can_use_dedicated_lightweight_model(mocker):
    class _Client:
        model = "main-model-instance"
        model_settings = {"temperature": 0.7}
        config = type(
            "Config",
            (),
            {
                "provider": "openai_compatible",
                "model_name": "main-model",
                "api_key": "sk-main",
                "base_url": "https://llm.example.com/v1",
            },
        )()

    created_configs = []

    class _RouterClient:
        def __init__(self, cfg):
            created_configs.append(cfg)
            self.config = cfg
            self.model = "router-model-instance"
            self.model_settings = {"temperature": cfg.temperature, "max_tokens": cfg.max_tokens}

    mocker.patch("app.resolver.semantic_intent_router.LLMClient", _RouterClient)

    router = SemanticIntentRouter(
        _Client(),
        SemanticRouterConfig(
            _env_file=None,
            llm_model_name="fast-router-model",
            llm_temperature=0.0,
            llm_max_tokens=384,
        ),
    )

    assert router.router_llm_client.model == "router-model-instance"
    assert created_configs[0].model_name == "fast-router-model"
    assert created_configs[0].api_key == "sk-main"
    assert created_configs[0].base_url == "https://llm.example.com/v1"
    assert created_configs[0].max_tokens == 384


def test_semantic_router_can_disable_provider_thinking_for_router_model(mocker):
    class _Client:
        model = "main-model-instance"
        model_settings = {"temperature": 0.7}
        config = type(
            "Config",
            (),
            {
                "provider": "openai_compatible",
                "model_name": "main-model",
                "api_key": "sk-main",
                "base_url": "https://llm.example.com/v1",
            },
        )()

    class _RouterClient:
        def __init__(self, cfg):
            self.config = cfg
            self.model = "router-model-instance"
            self.model_settings = {"temperature": cfg.temperature, "max_tokens": cfg.max_tokens}

    mocker.patch("app.resolver.semantic_intent_router.LLMClient", _RouterClient)

    router = SemanticIntentRouter(
        _Client(),
        SemanticRouterConfig(
            _env_file=None,
            llm_model_name="deepseek-ai/DeepSeek-V4-Flash",
            llm_enable_thinking=False,
        ),
    )

    assert router._router_model_settings()["extra_body"] == {"enable_thinking": False}


def test_semantic_router_prompt_budget_keeps_valid_json():
    class _Client:
        model = "main-model-instance"
        model_settings = {}
        config = type(
            "Config",
            (),
            {
                "provider": "openai_compatible",
                "model_name": "main-model",
                "api_key": "sk-main",
                "base_url": "https://llm.example.com/v1",
            },
        )()

    router = SemanticIntentRouter(
        _Client(),
        SemanticRouterConfig(_env_file=None, max_prompt_chars=900),
    )
    context = RequestContext(
        userid="u1",
        sessionid="s1",
        chat_history=[
            {"role": "user", "content": "上一轮很长" * 300},
            {"role": "assistant", "content": "回复也很长" * 300},
            {"role": "user", "content": "继续补充" * 300},
        ],
        score_detail=ScoreDetail(
            province="山东",
            total_score=450,
            subject_list=["物理", "历史", "地理"],
            sex="女",
            volunteer_model="majorGroup",
        ),
        planning_summary=PlanningSummary(
            phase="ordered",
            version=7,
            ordered_total=45,
            ordered_target_total=48,
            review_warn_count=2,
            review_risk_count=1,
            tier_counts={"冲": 10, "稳": 20, "保": 15},
            risk_summaries=["风险说明" * 50],
            positive_regions=["北京" * 50, "天津" * 50, "上海" * 50],
            positive_majors=["法学" * 50, "财政学" * 50, "会计学" * 50],
        ),
    )
    pending = PendingConfirmation(
        kind="plan_mutation",
        action_family="sort_ordered_plan",
        preview_summary="按院校层次排序会改变方案顺序" * 30,
    )

    prompt = router._build_prompt(
        "按院校层次排一下，先看看",
        request_context=context,
        active_pending=pending,
    )
    payload = json.loads(prompt.split("\n", 1)[1])

    assert len(prompt) <= 900
    assert payload["userPrompt"] == "按院校层次排一下，先看看"
    assert payload["pending"]["actionFamily"] == "sort_ordered_plan"
    assert payload["planningSummary"]["orderedTotal"] == 45
    assert payload["scoreDetail"]["volunteerModel"] == "majorGroup"


@pytest.mark.asyncio
async def test_semantic_router_shadow_records_prompt_chars(mocker):
    class _Client:
        model = "main-model-instance"
        model_settings = {}
        config = type(
            "Config",
            (),
            {
                "provider": "openai_compatible",
                "model_name": "main-model",
                "api_key": "sk-main",
                "base_url": "https://llm.example.com/v1",
            },
        )()

    router = SemanticIntentRouter(
        _Client(),
        SemanticRouterConfig(_env_file=None, enabled=True, max_prompt_chars=900),
    )

    class _Agent:
        async def run(self, prompt, model_settings=None):
            return SimpleNamespace(
                output=json.dumps(
                    {
                        "taskLayer": "plan",
                        "verb": "sort",
                        "topic": "plan",
                        "sideEffect": "preview",
                    }
                )
            )

    mocker.patch.object(router, "_agent", return_value=_Agent())
    context = RequestContext(userid="u1", sessionid="s1")

    result = await router.route_shadow(
        "按院校层次排序",
        request_context=context,
        active_pending=None,
    )

    assert result.status == "success"
    assert result.promptChars > 0
    assert result.event_payload()["promptChars"] == result.promptChars
