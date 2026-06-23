import json

from app.tools.plan_query_profile_tool import (
    PlanQueryProfileResult,
    _build_prompt,
    _normalize_plan_query_profile,
)


def test_plan_query_profile_prompt_defines_structured_plan_query_schema():
    prompt = json.loads(_build_prompt("保底最后几个是什么学校", {"planningStateProfile": {"formalPlanPresent": True}}))

    assert "plan_query_profile" not in prompt["returnJson"]
    assert "readonly_plan_query" in prompt["allowedValues"]["queryType"]
    assert "readonly_plan_slice_query" in prompt["allowedValues"]["queryType"]
    assert "readonly_pending_reference_query" in prompt["allowedValues"]["queryType"]
    rule_text = "\n".join(prompt["schemaRules"])
    assert "queryType=none" in rule_text
    assert "pendingReferenceType=major" in rule_text


def test_plan_query_profile_normalizer_rejects_unknown_enums_without_inventing_fields():
    normalized = _normalize_plan_query_profile(
        PlanQueryProfileResult(
            queryType="delete_units",
            scopeAnchor="current_plan",
            sideEffect="plan_preview",
            dimensions=["tuition", "unknown"],
            pendingReferenceType="major",
            confidence="high",
        )
    )

    assert normalized.queryType == "none"
    assert normalized.sideEffect == "none"
    assert normalized.dimensions == ["tuition"]
    assert normalized.pendingReferenceType == "major"
    assert normalized.confidence == 0.9
