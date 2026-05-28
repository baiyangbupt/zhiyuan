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
