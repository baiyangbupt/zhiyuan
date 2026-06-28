from __future__ import annotations

import inspect
import json

from app.tools.extraction_json import parse_extraction_json
from app.tools.plan_semantic_action_tool import (
    PlanActionDslDecision,
    PlanAtomicActionDslDecision,
    PlanSemanticActionDecision,
    _get_plan_atomic_action_dsl_agent,
    _get_plan_action_agent,
    _normalize_plan_action_dsl_decision,
    _normalize_plan_atomic_action_dsl_decision,
    _normalize_plan_semantic_action_decision,
)


def test_plan_action_dsl_decision_accepts_empty_optional_sort_field():
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

    decision = parse_extraction_json(raw, PlanActionDslDecision)
    normalized = _normalize_plan_action_dsl_decision(decision)

    assert normalized.actionFamily == "none"
    assert normalized.sortField is None
    assert normalized.sourcePosition is None
    assert normalized.targetPosition is None


def test_plan_action_dsl_decision_accepts_null_optional_collection_fields():
    raw = json.dumps(
        {
            "actionFamily": "none",
            "confidence": 0.82,
            "reason": "用户要求锁定位置，当前动作空间不支持",
            "unsupportedAction": "pin_or_lock_unit",
            "volunteerIds": None,
            "unitIds": None,
            "sourceMajorNames": None,
            "schoolTags": None,
            "majorTags": None,
            "preserveCount": None,
        },
        ensure_ascii=False,
    )

    decision = parse_extraction_json(raw, PlanActionDslDecision)
    normalized = _normalize_plan_action_dsl_decision(decision)

    assert normalized.actionFamily == "none"
    assert normalized.unsupportedAction == "pin_or_lock_unit"
    assert normalized.volunteerIds == []
    assert normalized.unitIds == []
    assert normalized.sourceMajorNames == []
    assert normalized.schoolTags == []
    assert normalized.majorTags == []
    assert normalized.preserveCount is False


def test_plan_atomic_action_dsl_decision_preserves_tuition_preference_scope():
    raw = json.dumps(
        {
            "actionFamily": "remove_units",
            "confidence": 0.96,
            "reason": "用户要求删除当前方案里费用阈值且不贴合意向的志愿",
            "minTuitionPerYear": "20000",
            "preferenceFit": "unrelated",
            "limit": "",
        },
        ensure_ascii=False,
    )

    decision = parse_extraction_json(raw, PlanAtomicActionDslDecision)
    normalized = _normalize_plan_atomic_action_dsl_decision(decision)

    assert normalized.actionFamily == "remove_units"
    assert normalized.minTuitionPerYear == 20000
    assert normalized.preferenceFit == "unrelated"
    assert normalized.limit == 5


def test_plan_atomic_action_dsl_decision_accepts_false_optional_text_fields():
    raw = json.dumps(
        {
            "actionFamily": "sort_ordered_plan",
            "confidence": 0.96,
            "reason": "用户要求按院校层次重排当前方案",
            "unsupportedAction": False,
            "reviewIssueCode": False,
            "sortField": "schoolRank",
        },
        ensure_ascii=False,
    )

    decision = parse_extraction_json(raw, PlanAtomicActionDslDecision)
    normalized = _normalize_plan_atomic_action_dsl_decision(decision)

    assert normalized.actionFamily == "sort_ordered_plan"
    assert normalized.unsupportedAction is None
    assert normalized.reviewIssueCode is None
    assert normalized.sortField == "schoolRank"


def test_plan_atomic_action_dsl_decision_accepts_list_keyword_fields():
    raw = json.dumps(
        {
            "actionFamily": "add_units",
            "confidence": 0.96,
            "reason": "用户要求把点名学校和专业加入当前方案",
            "schoolKeyword": ["河南农业大学"],
            "majorKeyword": ["建筑类"],
            "provinceKeyword": [],
        },
        ensure_ascii=False,
    )

    decision = parse_extraction_json(raw, PlanAtomicActionDslDecision)
    normalized = _normalize_plan_atomic_action_dsl_decision(decision)

    assert normalized.actionFamily == "add_units"
    assert normalized.schoolKeyword == "河南农业大学"
    assert normalized.majorKeyword == "建筑类"
    assert normalized.provinceKeyword is None


def test_plan_atomic_action_dsl_instructions_expose_structured_tuition_preference_fields():
    instructions = inspect.getsource(_get_plan_atomic_action_dsl_agent)

    assert "minTuitionPerYear" in instructions
    assert "preferenceFit=unrelated" in instructions
    assert "不回复用户、不执行工具、不创建 pending" in instructions


def test_plan_semantic_action_instructions_keep_direct_sort_out_of_fix_preview():
    instructions = inspect.getsource(_get_plan_action_agent)

    assert "直接说按录取率从高到低/从低到高排一下" in instructions
    assert "本质也是 sort_ordered_plan 排序动作，不是审查修复建议" in instructions
    assert "处理录取率倒挂、按录取率重排" not in instructions


def test_plan_semantic_action_decision_preserves_profile_scenario_payload():
    raw = json.dumps(
        {
            "actionFamily": "analyze_adjustment",
            "confidence": 0.91,
            "reason": "当前学生基础资料变化",
            "replyFocus": ["profile_change_replan"],
            "targetStrategies": [],
            "targetIssueCodes": [],
            "profileScenario": "current_student_update",
            "proposedProfile": {"score": "620", "province": "湖北", "subjectCombo": "物化生"},
        },
        ensure_ascii=False,
    )

    decision = parse_extraction_json(raw, PlanSemanticActionDecision)
    normalized = _normalize_plan_semantic_action_decision(decision)

    assert normalized.actionFamily == "analyze_adjustment"
    assert normalized.profileScenario == "current_student_update"
    assert normalized.proposedProfile == {"score": "620", "province": "湖北", "subjectCombo": "物化生"}


def test_plan_semantic_action_instructions_define_profile_state_query_focus():
    instructions = inspect.getsource(_get_plan_action_agent)

    assert "profile_change_state_query" in instructions
    assert "不要把它重新判成一次新的 profile_change_replan" in instructions
    assert "那基于620湖北物化生重来" in instructions
    assert "profileScenario=adhoc_scenario" in instructions
