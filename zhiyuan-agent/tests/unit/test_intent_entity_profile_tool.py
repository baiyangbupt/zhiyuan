from app.tools.intent_entity_profile_tool import IntentEntityProfileResult, _normalize_entity_profile


def test_intent_entity_profile_result_keeps_budget_type_and_tuition_budget():
    result = IntentEntityProfileResult(
        entityType="budget",
        tuitionBudget={"max_tuition_per_year": "20000", "minTuitionPerYear": 5000},
    )

    normalized = _normalize_entity_profile(result)

    assert normalized.entityType == "budget"
    assert normalized.tuitionBudget == {
        "maxTuitionPerYear": 20000,
        "minTuitionPerYear": 5000,
    }


def test_intent_entity_profile_result_marks_mixed_when_budget_has_other_entities():
    result = IntentEntityProfileResult(
        entityType="major",
        majorValues=["计算机科学与技术"],
        tuitionBudget={"maxTuitionPerYear": 20000},
    )

    normalized = _normalize_entity_profile(result)

    assert normalized.entityType == "mixed"


def test_intent_entity_profile_result_recovers_budget_when_entity_type_is_none():
    result = IntentEntityProfileResult(
        entityType="none",
        tuitionBudget={"maxTuitionPerYear": 20000},
    )

    normalized = _normalize_entity_profile(result)

    assert normalized.entityType == "budget"


def test_intent_entity_profile_normalizes_physical_constraints_as_budget_scope():
    result = IntentEntityProfileResult(
        entityType="none",
        physicalConstraints={"special_limits": ["高收费", "中外合作"]},
        preferenceStrength={"exclude_hard": ["高收费"]},
    )

    normalized = _normalize_entity_profile(result)

    assert normalized.entityType == "budget"
    assert normalized.physicalConstraints == {"specialLimits": ["高收费", "中外合作"]}
    assert normalized.preferenceStrength == {"exclude_hard": ["高收费", "中外合作"]}
    assert normalized.entityPolaritySpans == [
        {"entity": "高收费", "entityType": "budget", "polarity": "negative", "strength": "exclude_hard"},
        {"entity": "中外合作", "entityType": "budget", "polarity": "negative", "strength": "exclude_hard"},
    ]


def test_intent_entity_profile_normalizes_school_nature_out_of_physical_constraints():
    result = IntentEntityProfileResult(
        entityType="budget",
        physicalConstraints={"specialLimits": ["公办", "民办", "高收费"]},
        preferenceStrength={"exclude_hard": ["公办"]},
        entityPolaritySpans=[
            {"entity": "公办", "entityType": "budget", "polarity": "negative", "strength": "exclude_hard"},
            {"entity": "民办", "entityType": "budget", "polarity": "negative", "strength": "exclude_hard"},
        ],
    )

    normalized = _normalize_entity_profile(
        result,
        latest_utterance="我的意思是能加点公办院校可以考虑吗你这全是民办院校",
    )

    assert normalized.entityType == "mixed"
    assert normalized.physicalConstraints == {"specialLimits": ["高收费"]}
    assert normalized.schools == ["公办", "民办"]
    assert normalized.preferenceStrength == {
        "preferred": ["公办"],
        "exclude_hard": ["民办", "高收费"],
    }
    assert {"entity": "公办", "entityType": "school", "polarity": "positive", "strength": "preferred"} in normalized.entityPolaritySpans
    assert {"entity": "民办", "entityType": "school", "polarity": "negative", "strength": "exclude_hard"} in normalized.entityPolaritySpans
    assert {"entity": "高收费", "entityType": "budget", "polarity": "negative", "strength": "exclude_hard"} in normalized.entityPolaritySpans


def test_intent_entity_profile_keeps_school_nature_as_school_entity():
    result = IntentEntityProfileResult(
        entityType="school",
        schools=["公办院校"],
        preferenceStrength={"must_have": ["公办"], "exclude_hard": ["民办"]},
        entityPolaritySpans=[
            {"entity": "公办院校", "entityType": "school", "polarity": "positive", "strength": "must_have"},
            {"entity": "民办院校", "entityType": "school", "polarity": "negative", "strength": "exclude_hard"},
        ],
    )

    normalized = _normalize_entity_profile(result, latest_utterance="保底要公办不要民办")

    assert normalized.entityType == "school"
    assert normalized.schools == ["公办", "民办"]
    assert normalized.physicalConstraints == {}
    assert normalized.preferenceStrength == {"must_have": ["公办"], "exclude_hard": ["民办"]}
    assert normalized.entityPolaritySpans == [
        {"entity": "公办", "entityType": "school", "polarity": "positive", "strength": "must_have"},
        {"entity": "民办", "entityType": "school", "polarity": "negative", "strength": "exclude_hard"},
    ]


def test_intent_entity_profile_recovers_school_nature_mention_when_model_omits_one_side():
    result = IntentEntityProfileResult(
        entityType="school",
        schools=["公办"],
        preferenceStrength={"preferred": ["公办"]},
        entityPolaritySpans=[
            {"entity": "公办", "entityType": "school", "polarity": "positive", "strength": "preferred"},
        ],
    )

    normalized = _normalize_entity_profile(
        result,
        latest_utterance="我的意思是能加点公办院校可以考虑吗你这全是民办院校",
    )

    assert normalized.entityType == "school"
    assert normalized.schools == ["公办", "民办"]
    assert normalized.preferenceStrength == {"preferred": ["公办"], "exclude_hard": ["民办"]}
    assert normalized.entityPolaritySpans == [
        {"entity": "公办", "entityType": "school", "polarity": "positive", "strength": "preferred"},
        {"entity": "民办", "entityType": "school", "polarity": "negative", "strength": "exclude_hard"},
    ]


def test_intent_entity_profile_normalizes_career_aliases_out_of_major_values():
    result = IntentEntityProfileResult(
        entityType="major",
        majorValues=["体制内", "稳定就业"],
        preferenceStrength={"primary": ["体制内"], "preferred": ["稳定就业"]},
        entityPolaritySpans=[
            {"entity": "体制内", "entityType": "major", "polarity": "positive", "strength": "primary"},
            {"entity": "稳定就业", "entityType": "major", "polarity": "positive", "strength": "preferred"},
        ],
    )

    normalized = _normalize_entity_profile(result)

    assert normalized.entityType == "career"
    assert normalized.majorValues == []
    assert normalized.careerValues == ["体制内/考公导向", "稳定就业导向"]
    assert normalized.preferenceStrength == {
        "primary": ["体制内/考公导向"],
        "preferred": ["稳定就业导向"],
    }
    assert normalized.entityPolaritySpans == [
        {"entity": "体制内/考公导向", "entityType": "career", "polarity": "positive", "strength": "primary"},
        {"entity": "稳定就业导向", "entityType": "career", "polarity": "positive", "strength": "preferred"},
    ]


def test_intent_entity_profile_normalizes_career_value_aliases_to_labels():
    result = IntentEntityProfileResult(
        entityType="career",
        careerValues=["体制内", "stable_employment"],
        preferenceStrength={"preferred": ["体制内", "stable_employment"]},
        entityPolaritySpans=[
            {"entity": "体制内", "entityType": "career", "polarity": "positive", "strength": "preferred"},
            {"entity": "stable_employment", "entityType": "career", "polarity": "positive", "strength": "preferred"},
        ],
    )

    normalized = _normalize_entity_profile(result)

    assert normalized.entityType == "career"
    assert normalized.careerValues == ["体制内/考公导向", "稳定就业导向"]
    assert normalized.preferenceStrength == {"preferred": ["体制内/考公导向", "稳定就业导向"]}
    assert normalized.entityPolaritySpans == [
        {"entity": "体制内/考公导向", "entityType": "career", "polarity": "positive", "strength": "preferred"},
        {"entity": "稳定就业导向", "entityType": "career", "polarity": "positive", "strength": "preferred"},
    ]


def test_intent_entity_profile_normalizes_adjustment_constraint_out_of_major_values():
    result = IntentEntityProfileResult(
        entityType="major",
        majorValues=["会计学", "调剂"],
        preferenceStrength={"only_keep": ["会计学"], "exclude_hard": ["调剂"]},
        entityPolaritySpans=[
            {"entity": "会计学", "entityType": "major", "polarity": "positive", "strength": "only_keep"},
            {"entity": "调剂", "entityType": "major", "polarity": "negative", "strength": "exclude_hard"},
        ],
    )

    normalized = _normalize_entity_profile(result, latest_utterance="主从会计类，不要调剂，")

    assert normalized.entityType == "mixed"
    assert normalized.majorValues == ["会计学"]
    assert normalized.physicalConstraints == {"specialLimits": ["专业调剂"]}
    assert normalized.preferenceStrength == {
        "only_keep": ["会计学"],
        "exclude_hard": ["专业调剂"],
    }
    assert normalized.entityPolaritySpans == [
        {"entity": "会计学", "entityType": "major", "polarity": "positive", "strength": "only_keep"},
        {"entity": "专业调剂", "entityType": "budget", "polarity": "negative", "strength": "exclude_hard"},
    ]


def test_intent_entity_profile_rewrites_negative_constraint_reversal_to_acceptable_major():
    result = IntentEntityProfileResult(
        entityType="major",
        majorValues=["经济学类"],
        preferenceStrength={"exclude_hard": ["经济学类"]},
        entityPolaritySpans=[
            {"entity": "经济学类", "entityType": "major", "polarity": "negative", "strength": "exclude_hard"},
        ],
    )

    normalized = _normalize_entity_profile(result, latest_utterance="不要排除经济学类啊")

    assert normalized.entityType == "major"
    assert normalized.majorValues == ["经济学类"]
    assert normalized.preferenceStrength == {"acceptable": ["经济学类"]}
    assert normalized.entityPolaritySpans == [
        {"entity": "经济学类", "entityType": "major", "polarity": "positive", "strength": "acceptable"},
    ]


def test_intent_entity_profile_recovers_negative_constraint_reversal_when_model_outputs_none():
    result = IntentEntityProfileResult(entityType="none")

    normalized = _normalize_entity_profile(result, latest_utterance="不要排除经济学类啊")

    assert normalized.entityType == "major"
    assert normalized.majorValues == ["经济学类"]
    assert normalized.preferenceStrength == {"acceptable": ["经济学类"]}
    assert normalized.entityPolaritySpans == [
        {"entity": "经济学类", "entityType": "major", "polarity": "positive", "strength": "acceptable"},
    ]


def test_intent_entity_profile_rewrites_negative_constraint_reversal_to_acceptable_school_nature():
    result = IntentEntityProfileResult(
        entityType="school",
        schools=["民办"],
        preferenceStrength={"exclude_hard": ["民办"]},
        entityPolaritySpans=[
            {"entity": "民办", "entityType": "school", "polarity": "negative", "strength": "exclude_hard"},
        ],
    )

    normalized = _normalize_entity_profile(result, latest_utterance="不要排除民办")

    assert normalized.entityType == "school"
    assert normalized.schools == ["民办"]
    assert normalized.preferenceStrength == {"acceptable": ["民办"]}
    assert normalized.entityPolaritySpans == [
        {"entity": "民办", "entityType": "school", "polarity": "positive", "strength": "acceptable"},
    ]


def test_intent_entity_profile_school_reversal_does_not_leak_school_prefix_region():
    result = IntentEntityProfileResult(entityType="none")

    normalized = _normalize_entity_profile(result, latest_utterance="别排除江西财经大学")

    assert normalized.entityType == "school"
    assert normalized.schools == ["江西财经大学"]
    assert normalized.regionValues == []
    assert normalized.preferenceStrength == {"acceptable": ["江西财经大学"]}
    assert normalized.entityPolaritySpans == [
        {
            "entity": "江西财经大学",
            "entityType": "school",
            "polarity": "positive",
            "strength": "acceptable",
        },
    ]


def test_intent_entity_profile_recovers_negative_constraint_reversal_region_when_model_outputs_none():
    result = IntentEntityProfileResult(entityType="none")

    normalized = _normalize_entity_profile(result, latest_utterance="别避开东北")

    assert normalized.entityType == "region"
    assert normalized.regionValues == ["东北"]
    assert normalized.preferenceStrength == {"acceptable": ["东北"]}
    assert normalized.entityPolaritySpans == [
        {"entity": "东北", "entityType": "region", "polarity": "positive", "strength": "acceptable"},
    ]


def test_intent_entity_profile_rewrites_negative_constraint_reversal_career_not_major():
    result = IntentEntityProfileResult(
        entityType="major",
        majorValues=["体制内"],
        preferenceStrength={"exclude_hard": ["体制内"]},
        entityPolaritySpans=[
            {"entity": "体制内", "entityType": "major", "polarity": "negative", "strength": "exclude_hard"},
        ],
    )

    normalized = _normalize_entity_profile(result, latest_utterance="不要排除体制内")

    assert normalized.entityType == "career"
    assert normalized.majorValues == []
    assert normalized.careerValues == ["体制内/考公导向"]
    assert normalized.preferenceStrength == {"acceptable": ["体制内/考公导向"]}
    assert normalized.entityPolaritySpans == [
        {
            "entity": "体制内/考公导向",
            "entityType": "career",
            "polarity": "positive",
            "strength": "acceptable",
        },
    ]


def test_intent_entity_profile_budget_negative_constraint_reversal_suppresses_unsupported_negative():
    result = IntentEntityProfileResult(
        entityType="budget",
        physicalConstraints={"specialLimits": ["高收费"]},
        preferenceStrength={"exclude_hard": ["高收费"]},
        entityPolaritySpans=[
            {"entity": "高收费", "entityType": "budget", "polarity": "negative", "strength": "exclude_hard"},
        ],
    )

    normalized = _normalize_entity_profile(result, latest_utterance="不要排除高收费")

    assert normalized.entityType == "none"
    assert normalized.physicalConstraints == {}
    assert normalized.preferenceStrength == {}
    assert normalized.entityPolaritySpans == []


def test_intent_entity_profile_reversal_only_applies_to_covered_clause():
    result = IntentEntityProfileResult(
        entityType="major",
        majorValues=["经济学类", "临床医学"],
        preferenceStrength={"exclude_hard": ["经济学类", "临床医学"]},
        entityPolaritySpans=[
            {"entity": "经济学类", "entityType": "major", "polarity": "negative", "strength": "exclude_hard"},
            {"entity": "临床医学", "entityType": "major", "polarity": "negative", "strength": "exclude_hard"},
        ],
    )

    normalized = _normalize_entity_profile(
        result,
        latest_utterance="不要排除经济学类，但临床医学还是排除",
    )

    assert normalized.entityType == "major"
    assert normalized.preferenceStrength == {
        "exclude_hard": ["临床医学"],
        "acceptable": ["经济学类"],
    }
    assert {"entity": "经济学类", "entityType": "major", "polarity": "positive", "strength": "acceptable"} in normalized.entityPolaritySpans
    assert {"entity": "临床医学", "entityType": "major", "polarity": "negative", "strength": "exclude_hard"} in normalized.entityPolaritySpans


def test_intent_entity_profile_school_reversal_keeps_explicit_region_exclusion():
    result = IntentEntityProfileResult(
        entityType="mixed",
        schools=["江西财经大学"],
        regionValues=["江西"],
        preferenceStrength={"exclude_hard": ["江西财经大学", "江西"]},
        entityPolaritySpans=[
            {"entity": "江西财经大学", "entityType": "school", "polarity": "negative", "strength": "exclude_hard"},
            {"entity": "江西", "entityType": "region", "polarity": "negative", "strength": "exclude_hard"},
        ],
    )

    normalized = _normalize_entity_profile(
        result,
        latest_utterance="别排除江西财经大学，但江西地区还是排除",
    )

    assert normalized.entityType == "mixed"
    assert normalized.schools == ["江西财经大学"]
    assert normalized.regionValues == ["江西"]
    assert normalized.preferenceStrength == {
        "exclude_hard": ["江西"],
        "acceptable": ["江西财经大学"],
    }
    assert {"entity": "江西财经大学", "entityType": "school", "polarity": "positive", "strength": "acceptable"} in normalized.entityPolaritySpans
    assert {"entity": "江西", "entityType": "region", "polarity": "negative", "strength": "exclude_hard"} in normalized.entityPolaritySpans
