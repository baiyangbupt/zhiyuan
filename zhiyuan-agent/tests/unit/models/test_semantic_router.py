from app.models.semantic_router import SemanticIntentFrame, SemanticRouterShadowResult


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
