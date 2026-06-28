from __future__ import annotations

import json

from app.tools.extraction_json import parse_extraction_json
from app.tools.turn_decision_tool import (
    TurnDecisionResult,
    _build_prompt,
    _normalize_turn_decision,
)


def test_turn_decision_preserves_profile_replan_payload():
    raw = json.dumps(
        {
            "taskLayer": "plan",
            "sideEffect": "profile_change_replan",
            "scopeAnchor": "current_profile",
            "scenario": "profile_update_replan",
            "profileScenario": "current_student_update",
            "proposedProfile": {"score": 620, "province": "湖北", "subjectCombo": "物化生"},
            "confidence": "high",
            "reason": "用户修正当前学生基础资料并要求重来",
        },
        ensure_ascii=False,
    )

    decision = parse_extraction_json(raw, TurnDecisionResult)
    normalized = _normalize_turn_decision(decision)

    assert normalized.taskLayer == "plan"
    assert normalized.sideEffect == "profile_change_replan"
    assert normalized.scopeAnchor == "current_profile"
    assert normalized.scenario == "profile_update_replan"
    assert normalized.profileScenario == "current_student_update"
    assert normalized.proposedProfile == {"score": 620, "province": "湖北", "subjectCombo": "物化生"}
    assert normalized.confidence == 0.9


def test_turn_decision_prompt_defines_profile_replan_scenarios():
    prompt = json.loads(
        _build_prompt(
            "分数也说错了应该是620不是630",
            {"planningStateProfile": {"formalPlanPresent": True, "pendingExists": False}},
        )
    )

    assert "profile_change_replan" in prompt["allowedValues"]["sideEffect"]
    assert "profile_replan_adhoc" in prompt["allowedValues"]["sideEffect"]
    assert "profile_replan_ambiguous" in prompt["allowedValues"]["sideEffect"]
    assert "profile_update_replan" in prompt["allowedValues"]["scenario"]
    assert "profile_adhoc_replan" in prompt["allowedValues"]["scenario"]
    assert "profile_scope_ambiguous" in prompt["allowedValues"]["scenario"]
    assert "profile_change_state_query" in prompt["allowedValues"]["scenario"]
    assert prompt["returnJson"]["profileScenario"] == "none"
    assert prompt["returnJson"]["proposedProfile"] == {}
    rule_text = "\n".join(
        [
            *prompt["hardRules"],
            *prompt["scenarioGuide"].values(),
        ]
    )
    assert "profileScenario=current_student_update" in rule_text
    assert "profileScenario=adhoc_scenario" in rule_text
    assert "profileScenario=ambiguous" in rule_text
    assert "ProfileChangeReplan" in rule_text
    assert "profile_change_state_query" in rule_text
    assert "proposedProfile" in rule_text


def test_turn_decision_prompt_defines_pending_impact_query():
    prompt = json.loads(
        _build_prompt(
            "先不确认，看看这个偏好会影响当前方案吗",
            {"planningStateProfile": {"formalPlanPresent": True, "pendingExists": True}},
        )
    )

    assert "pending_reference" in prompt["allowedValues"]["scopeAnchor"]
    assert "pending_impact_query" in prompt["allowedValues"]["scenario"]
    rule_text = "\n".join(
        [
            *prompt["hardRules"],
            *prompt["scenarioGuide"].values(),
        ]
    )
    assert "scopeAnchor=pending_reference" in rule_text
    assert "scenario=pending_impact_query" in rule_text


def test_turn_decision_prompt_keeps_new_intent_update_out_of_active_pending_conflict():
    prompt = json.loads(
        _build_prompt(
            "把华中科技大学加到意向",
            {
                "planningStateProfile": {"formalPlanPresent": True, "pendingExists": True},
                "pendingState": {"kind": "intent_change", "actionFamily": "apply_selected_intents"},
            },
        )
    )

    rule_text = "\n".join(
        [
            *prompt["schemaRules"],
            *prompt["hardRules"],
            *prompt["scenarioGuide"].values(),
        ]
    )
    assert "pendingState.kind=intent_change" in rule_text
    assert "新的未来偏好" in rule_text
    assert "intent_pending/future_reference/intent_update" in rule_text
    assert "不能误判为 pending_conflict_new_mutation" in rule_text
    assert "不能误判为 atomic_mutation/current_plan" in rule_text


def test_turn_decision_prompt_routes_school_nature_update_while_intent_pending():
    prompt = json.loads(
        _build_prompt(
            "我的意思是能加点公办院校可以考虑吗你这全是民办院校",
            {
                "planningStateProfile": {"formalPlanPresent": False, "pendingExists": True},
                "pendingState": {"kind": "intent_change", "actionFamily": "apply_selected_intents"},
            },
        )
    )

    rule_text = "\n".join(
        [
            *prompt["schemaRules"],
            *prompt["hardRules"],
            json.dumps(prompt["examples"], ensure_ascii=False),
        ]
    )
    assert "院校性质" in rule_text
    assert "公办" in rule_text
    assert "民办" in rule_text
    assert "intent_pending/future_reference/intent_update" in rule_text
    assert "我的意思是能加点公办院校可以考虑吗你这全是民办院校" in rule_text


def test_turn_decision_prompt_routes_bare_region_add_as_future_intent():
    prompt = json.loads(
        _build_prompt(
            "加入广东和江西",
            {"planningStateProfile": {"formalPlanPresent": False, "pendingExists": False}},
        )
    )

    rule_text = "\n".join(
        [
            *prompt["hardRules"],
            json.dumps(prompt["examples"], ensure_ascii=False),
        ]
    )
    assert "加入/加上/记上某省份、城市、地域" in rule_text
    assert "不能输出 add_units/plan_preview" in rule_text
    assert "加入广东和江西" in rule_text
    assert "intent_pending" in rule_text
    assert "future_reference" in rule_text


def test_turn_decision_prompt_routes_high_tuition_typo_as_future_intent():
    prompt = json.loads(
        _build_prompt(
            "那如果我不接受稿费呢高高学费",
            {"planningStateProfile": {"formalPlanPresent": True, "pendingExists": False}},
        )
    )

    rule_text = "\n".join(
        [
            *prompt["hardRules"],
            json.dumps(prompt["examples"], ensure_ascii=False),
        ]
    )
    assert "稿费" in rule_text
    assert "高高学费" in rule_text
    assert "高收费" in rule_text
    assert "intent_pending" in rule_text
    assert "future_reference" in rule_text


def test_turn_decision_preserves_profile_change_state_query():
    raw = json.dumps(
        {
            "taskLayer": "plan",
            "sideEffect": "readonly_while_pending",
            "scopeAnchor": "current_profile",
            "scenario": "profile_change_state_query",
            "confidence": "high",
            "reason": "用户追问当前正式方案是否已经按上一轮新资料重算",
        },
        ensure_ascii=False,
    )

    decision = parse_extraction_json(raw, TurnDecisionResult)
    normalized = _normalize_turn_decision(
        decision,
        payload={"planningStateProfile": {"formalPlanPresent": True, "pendingExists": True}},
    )

    assert normalized.taskLayer == "plan"
    assert normalized.sideEffect == "readonly_while_pending"
    assert normalized.scopeAnchor == "current_profile"
    assert normalized.scenario == "profile_change_state_query"
    assert normalized.confidence == 0.9


def test_turn_decision_normalization_respects_pending_absent_payload():
    decision = TurnDecisionResult(
        taskLayer="plan",
        sideEffect="readonly_while_pending",
        scopeAnchor="current_plan",
        scenario="plan_query_while_pending",
        confidence=0.95,
        reason="模型错误地认为当前有 pending",
    )

    normalized = _normalize_turn_decision(
        decision,
        payload={"planningStateProfile": {"formalPlanPresent": True, "pendingExists": False}},
    )

    assert normalized.taskLayer == "plan"
    assert normalized.sideEffect == "readonly"
    assert normalized.scopeAnchor == "current_plan"
    assert normalized.scenario == "plan_query"
    assert normalized.confidence == 0.95


def test_turn_decision_normalization_drops_pending_impact_without_active_pending():
    decision = TurnDecisionResult(
        taskLayer="pending",
        sideEffect="readonly_while_pending",
        scopeAnchor="pending_reference",
        scenario="pending_impact_query",
        confidence=0.95,
        reason="模型错误地认为当前有 pending",
    )

    normalized = _normalize_turn_decision(
        decision,
        payload={"planningStateProfile": {"formalPlanPresent": True, "pendingExists": False}},
    )

    assert normalized.sideEffect == "readonly"
    assert normalized.scopeAnchor == "current_plan"
    assert normalized.scenario == "plan_query"
