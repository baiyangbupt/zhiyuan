from app.resolver.major_compare_fast_router import resolve_major_compare_fast_route


def test_major_compare_fast_route_matches_exact_two_level3_majors():
    decision = resolve_major_compare_fast_route("法学和财政学哪个更适合普通家庭女生，先只分析不要记偏好")

    assert decision.matched is True
    assert decision.major_name1 == "法学"
    assert decision.major_name2 == "财政学"
    assert decision.route_decision()["actionFamily"] == "compare_majors"


def test_major_compare_fast_route_does_not_match_category_or_abbreviation():
    assert resolve_major_compare_fast_route("计算机和电子信息怎么选").matched is False
    assert resolve_major_compare_fast_route("计科和软工哪个更好").matched is False
    assert resolve_major_compare_fast_route("法学类和财政学类哪个更适合").matched is False


def test_major_compare_fast_route_matches_unique_local_alias():
    decision = resolve_major_compare_fast_route("网络与新媒体和跨境电商哪个更适合我")

    assert decision.matched is True
    assert decision.major_name1 == "网络与新媒体"
    assert decision.major_name2 == "跨境电子商务"


def test_major_compare_fast_route_matches_colloquial_pair_with_context():
    decision = resolve_major_compare_fast_route("新媒体和跨电呢 数学不太行")

    assert decision.matched is True
    assert decision.major_name1 == "网络与新媒体"
    assert decision.major_name2 == "跨境电子商务"


def test_major_compare_fast_route_matches_high_confidence_lazy_abbreviations():
    decision = resolve_major_compare_fast_route("法和财哪个更适合女孩子，家里一般")

    assert decision.matched is True
    assert decision.major_name1 == "法学"
    assert decision.major_name2 == "财政学"


def test_major_compare_fast_route_does_not_match_intent_or_mutation_semantics():
    assert resolve_major_compare_fast_route("法学和财政学都帮我记成偏好").matched is False
    assert resolve_major_compare_fast_route("法学和财政学按这个改方案").matched is False
    assert resolve_major_compare_fast_route("法学和财政学哪个更适合，不要记偏好，按这个改方案").matched is False


def test_major_compare_fast_route_allows_readonly_negative_preference_wording():
    decision = resolve_major_compare_fast_route("法学和财政学哪个更稳妥，不要记偏好")

    assert decision.matched is True


def test_major_compare_fast_route_requires_compare_semantics():
    assert resolve_major_compare_fast_route("我喜欢法学和财政学").matched is False
