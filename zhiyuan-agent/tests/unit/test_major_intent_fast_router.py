from app.resolver.major_intent_fast_router import resolve_major_intent_fast_route


def test_major_intent_fast_route_matches_positive_and_negative_level3_majors():
    decision = resolve_major_intent_fast_route("我倾向法学和财政学，但护理不要")

    assert decision.matched is True
    assert decision.intent_mode == "constraint"
    assert decision.major_intents == {
        "level3": ["法学", "财政学"],
        "negative_level3": ["护理学"],
    }
    assert decision.route_decision()["actionFamily"] == "preview_major_intent"


def test_major_intent_fast_route_matches_lazy_positive_with_negative_level3_majors():
    decision = resolve_major_intent_fast_route("会计审计可以 土木别要")

    assert decision.matched is True
    assert decision.intent_mode == "constraint"
    assert decision.major_intents == {
        "level3": ["会计学", "审计学"],
        "negative_level3": ["土木工程"],
    }


def test_major_intent_fast_route_matches_colloquial_soft_and_hard_terms():
    decision = resolve_major_intent_fast_route("会计审计这类还行，土木建筑那种别碰")

    assert decision.matched is True
    assert decision.intent_mode == "constraint"
    assert decision.major_intents == {
        "level3": ["会计学", "审计学"],
        "negative_level3": ["土木工程", "建筑学"],
    }


def test_major_intent_fast_route_matches_level2_categories_and_alias_surface():
    decision = resolve_major_intent_fast_route("以后优先看计算机类，不看护理类")

    assert decision.matched is True
    assert decision.intent_mode == "constraint"
    assert decision.major_intents["level2"] == ["计算机类"]
    assert decision.major_intents["negative_level2"] == ["护理学类"]


def test_major_intent_fast_route_matches_broad_medical_and_accounting_aliases():
    decision = resolve_major_intent_fast_route("医学护理这些别碰，财会还能接受，先看看影响")

    assert decision.matched is True
    assert decision.intent_mode == "constraint"
    assert decision.major_intents["negative_level2"] == [
        "临床医学类",
        "口腔医学类",
        "中医学类",
        "护理学类",
        "医学技术类",
    ]
    assert decision.major_intents["negative_level3"] == ["护理学"]
    assert decision.major_intents["level3"] == ["会计学", "审计学"]


def test_major_intent_fast_route_matches_unique_level3_alias():
    decision = resolve_major_intent_fast_route("网络与新媒体优先，跨境电商也可以考虑")

    assert decision.matched is True
    assert decision.major_intents["level3"] == ["网络与新媒体", "跨境电子商务"]


def test_major_intent_fast_route_does_not_match_readonly_compare_request():
    decision = resolve_major_intent_fast_route("法学和财政学哪个更适合普通家庭女生，先只分析不要记偏好")

    assert decision.matched is False
    assert decision.reason == "readonly_or_compare_semantics"


def test_major_intent_fast_route_does_not_match_readonly_question_with_can():
    decision = resolve_major_intent_fast_route("会计可以吗")

    assert decision.matched is False
    assert decision.reason == "readonly_question_semantics"


def test_major_intent_fast_route_does_not_match_plan_mutation_request():
    decision = resolve_major_intent_fast_route("把法学加入方案")

    assert decision.matched is False
    assert decision.reason == "plan_mutation_semantics"


def test_major_intent_fast_route_does_not_match_vague_direction():
    decision = resolve_major_intent_fast_route("我喜欢偏文一点，也想以后稳定一些")

    assert decision.matched is False
    assert decision.reason == "no_catalog_major_match"
