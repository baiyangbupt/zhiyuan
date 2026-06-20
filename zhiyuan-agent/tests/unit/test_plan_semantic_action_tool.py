from __future__ import annotations

import inspect
import json

from app.tools.extraction_json import parse_extraction_json
from app.tools.plan_semantic_action_tool import (
    CompositeGoalDecision,
    PlanRecoveryActionDecision,
    _get_plan_action_agent,
    _normalize_composite_goal_decision,
    _normalize_plan_recovery_action_decision,
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


def test_composite_goal_decision_accepts_program_type_scope():
    raw = json.dumps(
        {
            "action": "exclude_scope",
            "confidence": 0.92,
            "reason": "用户要求排除招生项目类型",
            "scopeType": "program_type",
            "targetValues": [],
            "negativeValues": ["中外合作办学"],
            "constraintIntentType": "default",
        },
        ensure_ascii=False,
    )

    decision = parse_extraction_json(raw, CompositeGoalDecision)
    normalized = _normalize_composite_goal_decision(decision)

    assert normalized.action == "exclude_scope"
    assert normalized.scopeType == "program_type"
    assert normalized.negativeValues == ["中外合作办学"]


def test_plan_recovery_decision_accepts_empty_optional_sort_field():
    raw = json.dumps(
        {
            "actionFamily": "none",
            "confidence": 0.4,
            "reason": "用户只是继续看方向分析",
            "sortField": "",
            "sourcePosition": "",
            "targetPosition": "",
        },
        ensure_ascii=False,
    )

    decision = parse_extraction_json(raw, PlanRecoveryActionDecision)
    normalized = _normalize_plan_recovery_action_decision(decision)

    assert normalized.actionFamily == "none"
    assert normalized.sortField is None
    assert normalized.sourcePosition is None
    assert normalized.targetPosition is None


def test_plan_semantic_action_instructions_keep_direct_sort_out_of_fix_preview():
    instructions = inspect.getsource(_get_plan_action_agent)

    assert "直接说按录取率从高到低/从低到高排一下" in instructions
    assert "本质也是 sort_ordered_plan 排序动作，不是审查修复建议" in instructions
    assert "处理录取率倒挂、按录取率重排" not in instructions
