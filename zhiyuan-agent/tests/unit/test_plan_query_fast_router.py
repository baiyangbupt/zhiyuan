from app.resolver.plan_query_fast_router import resolve_plan_query_fast_route


def test_plan_query_fast_route_matches_plan_major_lookup():
    decision = resolve_plan_query_fast_route("当前方案里有没有生物工程")

    assert decision.matched is True
    assert decision.scope == "plan"
    assert decision.major_keywords == ["生物工程"]
    assert decision.tool_args() == {
        "query": "当前方案里有没有生物工程",
        "scope": "plan",
        "major_keywords": ["生物工程"],
    }
    assert decision.route_decision()["actionFamily"] == "query_volunteer_plan"


def test_plan_query_fast_route_matches_candidate_school_major_lookup():
    decision = resolve_plan_query_fast_route("候选里看看北京农学院的生物工程")

    assert decision.matched is True
    assert decision.scope == "candidate"
    assert decision.school_keywords == ["北京农学院"]
    assert decision.major_keywords == ["生物工程"]
    assert decision.tool_args()["match_mode"] == "and"


def test_plan_query_fast_route_matches_school_related_question_with_readonly_cancel():
    decision = resolve_plan_query_fast_route("青岛城市学院相关专业是不是有多个，先帮我判断一下，不要直接改方案")

    assert decision.matched is True
    assert decision.scope == "plan_then_candidate"
    assert decision.school_keywords == ["青岛城市学院"]


def test_plan_query_fast_route_matches_high_confidence_school_abbreviation():
    decision = resolve_plan_query_fast_route("青城那个是不是放多了")

    assert decision.matched is True
    assert decision.scope == "plan_then_candidate"
    assert decision.school_keywords == ["青岛城市学院"]


def test_plan_query_fast_route_expands_colloquial_medical_and_nursing_query():
    decision = resolve_plan_query_fast_route("孩子不想学医也不想护理，方案里有没有这种坑，先看看")

    assert decision.matched is True
    assert decision.scope == "plan"
    assert {"医学", "医学类", "护理学类", "护理学"}.issubset(set(decision.major_keywords))


def test_plan_query_fast_route_does_not_steal_unscoped_intent_preview():
    decision = resolve_plan_query_fast_route("医学护理这些别碰，财会还能接受，先看看影响")

    assert decision.matched is False
    assert decision.reason == "unscoped_intent_preview_semantics"


def test_plan_query_fast_route_does_not_match_mutation_requests():
    assert resolve_plan_query_fast_route("把北京农学院的生物工程加入方案").matched is False
    assert resolve_plan_query_fast_route("删除当前方案里的生物工程").matched is False
    assert resolve_plan_query_fast_route("按院校层次排序").matched is False
    assert resolve_plan_query_fast_route("现在还差几个怎么补").matched is False


def test_plan_query_fast_route_does_not_match_explore_or_score_requests():
    assert resolve_plan_query_fast_route("法学和财政学哪个更适合").matched is False
    assert resolve_plan_query_fast_route("体制内稳定就业适不适合我").matched is False
    assert resolve_plan_query_fast_route("我是山东450分，物理历史地理，想先看看适合什么方向").matched is False
    assert resolve_plan_query_fast_route("北京农学院近三年录取分是多少").matched is False
    assert resolve_plan_query_fast_route("方案里中外合作是不是有点多，家里预算一般，帮我用大白话看下风险，先别动").matched is False
    assert resolve_plan_query_fast_route("财会、法学、新媒体这几个，哪个更不容易踩坑，先说说别记偏好").matched is False
    assert resolve_plan_query_fast_route("孩子就想去北京天津，但分数不算高，这样是不是太冒险，先别改").matched is False
    assert resolve_plan_query_fast_route("档案图书馆这种冷门是不是坑").matched is False
    assert resolve_plan_query_fast_route("财管会计审计这几个怎么排优先级").matched is False


def test_plan_query_fast_route_requires_entity_without_explicit_scope():
    decision = resolve_plan_query_fast_route("帮我看看有没有相关机会")

    assert decision.matched is False
    assert decision.reason == "missing_local_query_entity"


def test_plan_query_fast_route_requires_entity_even_with_explicit_scope():
    decision = resolve_plan_query_fast_route("方案里面省外是不是太多了")

    assert decision.matched is False
    assert decision.reason == "missing_local_query_entity"
