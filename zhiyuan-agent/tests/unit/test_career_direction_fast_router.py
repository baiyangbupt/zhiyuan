from app.domain.career_slots import CAREER_FURTHER_STUDY, CAREER_STABLE_EMPLOYMENT, CAREER_SYSTEM_PUBLIC_SERVICE
from app.resolver.career_direction_fast_router import resolve_career_direction_fast_route


def test_career_direction_fast_route_matches_readonly_local_slots():
    decision = resolve_career_direction_fast_route("当前方案对体制内稳定就业方向承接得怎么样，先不要改方案")

    assert decision.matched is True
    assert decision.direction_slots == [CAREER_SYSTEM_PUBLIC_SERVICE, CAREER_STABLE_EMPLOYMENT]
    route = decision.route_decision()
    assert route["actionFamily"] == "analyze_current_career_direction"
    assert route["route"] == "explore"


def test_career_direction_fast_route_allows_readonly_cancel_wording():
    decision = resolve_career_direction_fast_route("体制内适不适合我，先只分析不要记偏好")

    assert decision.matched is True
    assert decision.direction_slots == [CAREER_SYSTEM_PUBLIC_SERVICE]


def test_career_direction_fast_route_matches_support_and_shortcoming_questions():
    decision = resolve_career_direction_fast_route("当前方案对考公、稳定就业和读研三个方向分别有什么支撑和短板，先不要改方案")

    assert decision.matched is True
    assert decision.direction_slots == [
        CAREER_SYSTEM_PUBLIC_SERVICE,
        CAREER_STABLE_EMPLOYMENT,
        CAREER_FURTHER_STUDY,
    ]


def test_career_direction_fast_route_does_not_match_intent_or_mutation_semantics():
    assert resolve_career_direction_fast_route("以后优先按体制内看").matched is False
    assert resolve_career_direction_fast_route("帮我把体制内记成偏好").matched is False
    assert resolve_career_direction_fast_route("按体制内方向调整方案").matched is False
    assert resolve_career_direction_fast_route("体制内方向承接怎么样，确认").matched is False


def test_career_direction_fast_route_does_not_match_generic_or_unresolved_direction():
    assert resolve_career_direction_fast_route("我适合什么方向").matched is False
    assert resolve_career_direction_fast_route("当前方案未来发展承接怎么样").matched is False
    assert resolve_career_direction_fast_route("候选里有没有体制内机会").matched is False
    assert resolve_career_direction_fast_route("先看看候选里有没有体制内机会").matched is False
