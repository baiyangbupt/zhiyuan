from app.agent.context import RequestContext
from app.data.major_data import associate_major_mappings, bachelor_major_mappings
from app.resolver.major_compare_reply_renderer import render_missing_weight_major_compare_reply


def _representative_major_by_category(mappings: dict) -> dict[str, str]:
    reps: dict[str, str] = {}
    for major_name, category_name in sorted((mappings.get("level3_to_level2") or {}).items()):
        if category_name and category_name not in reps:
            reps[category_name] = major_name
    return reps


def _assert_renderer_covers_category_representatives(*, batch: str, mappings: dict) -> None:
    reps = _representative_major_by_category(mappings)
    assert len(reps) >= 90
    categories = sorted(reps)
    context = RequestContext(userid="user-1", sessionid=f"session-{batch}", batch=batch)

    for index, category in enumerate(categories):
        other_category = categories[(index + 1) % len(categories)]
        major_name = reps[category]
        other_major_name = reps[other_category]

        reply = render_missing_weight_major_compare_reply(
            major_name1=major_name,
            major_name2=other_major_name,
            request_context=context,
        )

        assert major_name in reply
        assert category in reply
        assert "当前没有拿到可用的个性化量化评分" in reply
        assert "选择建议" in reply
        assert "请只做" not in reply
        assert "内部提示" not in reply
        assert "payload" not in reply
        assert "action_family" not in reply


def test_missing_weight_renderer_has_fallback_for_all_bachelor_major_categories():
    _assert_renderer_covers_category_representatives(batch="01", mappings=bachelor_major_mappings)


def test_missing_weight_renderer_has_fallback_for_all_associate_major_categories():
    _assert_renderer_covers_category_representatives(batch="02", mappings=associate_major_mappings)
