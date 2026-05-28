from app.models.semantic_router import SemanticIntentFrame, SemanticRouterShadowResult
from app.resolver.semantic_intent_router import SemanticIntentRouter, _parse_semantic_frame


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


def test_semantic_router_agent_uses_text_output_to_avoid_tool_choice_required():
    class _Client:
        model = "test"
        model_settings = {}

    router = SemanticIntentRouter(_Client())

    assert router._agent().output_type is str
