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
        assert "方向判断" in reply
        assert "选择建议" in reply
        assert "个性化量化评分" not in reply
        assert "系统评分" not in reply
        assert "请只做" not in reply
        assert "内部提示" not in reply
        assert "payload" not in reply
        assert "action_family" not in reply


def test_missing_weight_renderer_has_fallback_for_all_bachelor_major_categories():
    _assert_renderer_covers_category_representatives(batch="01", mappings=bachelor_major_mappings)


def test_missing_weight_renderer_has_fallback_for_all_associate_major_categories():
    _assert_renderer_covers_category_representatives(batch="02", mappings=associate_major_mappings)


def test_missing_weight_renderer_uses_recent_user_score_context():
    context = RequestContext(
        userid="user-1",
        sessionid="session-context",
        batch="01",
        chat_history=[
            {"role": "user", "content": "我是山东450分，物理历史地理，想先看看适合什么方向"},
            {"role": "assistant", "content": "可以先看几个方向。"},
            {"role": "user", "content": "网络与新媒体和跨境电子商务哪个更适合我"},
        ],
    )

    reply = render_missing_weight_major_compare_reply(
        major_name1="网络与新媒体",
        major_name2="跨境电子商务",
        request_context=context,
    )

    assert "省份=山东" in reply
    assert "分数=450" in reply
    assert "选科=物理、历史、地理" in reply
    assert "当前会话还缺分数" not in reply


def test_missing_weight_renderer_uses_category_profiles_for_media_and_ecommerce():
    context = RequestContext(
        userid="user-1",
        sessionid="session-media-ecommerce",
        batch="01",
        chat_history=[
            {"role": "user", "content": "我是山东450分，物理历史地理，想先看看适合什么方向"},
            {"role": "user", "content": "网络与新媒体和跨境电商哪个更适合我"},
        ],
    )

    reply = render_missing_weight_major_compare_reply(
        major_name1="网络与新媒体",
        major_name2="跨境电子商务",
        request_context=context,
    )

    assert "新闻传播学类" in reply
    assert "电子商务类" in reply
    assert "内容策划" in reply
    assert "跨境平台运营" in reply
    assert "当前没有沉淀专门画像" not in reply


def test_missing_weight_renderer_uses_structured_sections():
    context = RequestContext(
        userid="user-1",
        sessionid="session-structure",
        batch="01",
        chat_history=[
            {"role": "user", "content": "法学和财政学哪个更适合普通家庭女生，先只分析不要记偏好"},
        ],
    )

    reply = render_missing_weight_major_compare_reply(
        major_name1="法学",
        major_name2="财政学",
        request_context=context,
    )

    assert "**当前会话参考**" in reply
    assert "**法学**" in reply
    assert "**财政学**" in reply
    assert "**选择建议**" in reply
    assert "**下一步**" in reply
    assert "普通家庭、女生" in reply
    assert "个性化量化评分" not in reply
    assert "系统分数" not in reply
