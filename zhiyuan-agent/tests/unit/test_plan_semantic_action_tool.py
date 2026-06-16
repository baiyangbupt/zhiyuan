from __future__ import annotations

import json

from app.tools.extraction_json import parse_extraction_json
from app.tools.plan_semantic_action_tool import (
    CompositeGoalDecision,
    _normalize_composite_goal_decision,
)


def test_composite_goal_decision_accepts_empty_optional_scope_fields():
    raw = json.dumps(
        {
            "action": "none",
            "confidence": "low",
            "reason": "用户只是查看审查结果",
            "scopeType": "",
            "targetValues": [],
            "negativeValues": [],
            "maxTuitionPerYear": "",
            "constraintIntentType": "default",
        },
        ensure_ascii=False,
    )

    decision = parse_extraction_json(raw, CompositeGoalDecision)
    normalized = _normalize_composite_goal_decision(decision)

    assert normalized.action == "none"
    assert normalized.scopeType is None
    assert normalized.maxTuitionPerYear is None
    assert normalized.confidence == 0.35
