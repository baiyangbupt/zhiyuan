from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.tools.major_recommend_tool import get_major_recommendations


@pytest.mark.asyncio
async def test_get_major_recommendations_skips_inner_summary_llm_when_chat_service_disables_it():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="s1",
            score_detail=SimpleNamespace(sex="女生"),
            allow_explore_inner_llm=False,
        )
    )
    major_list = [
        {
            "major": "法学类",
            "gender_index": 72,
            "satisfy_index": 81,
            "salary_avg": 7600,
            "hot_index": 88,
        },
        {
            "major": "财政学类",
            "gender_index": 68,
            "satisfy_index": 84,
            "salary_avg": 7100,
            "hot_index": 76,
        },
    ]

    with (
        patch("app.tools.major_recommend_tool.get_majors_recommend", new=AsyncMock(return_value={"majorList": major_list})),
        patch("app.tools.major_recommend_tool._summarize_recommendations", new=AsyncMock()) as summary_mock,
    ):
        result = await get_major_recommendations(ctx)

    summary_mock.assert_not_awaited()
    assert "专业推荐参考" in result
    assert "法学类" in result
    assert "财政学类" in result
    assert "性别分布适配 72" in result
    assert "多维指标加权推荐模型" in result


@pytest.mark.asyncio
async def test_get_major_recommendations_keeps_inner_summary_llm_by_default():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="s2",
            score_detail=SimpleNamespace(sex="女生"),
        )
    )
    major_list = [{"major": "法学类"}]

    with (
        patch("app.tools.major_recommend_tool.get_majors_recommend", new=AsyncMock(return_value={"majorList": major_list})),
        patch("app.tools.major_recommend_tool._summarize_recommendations", new=AsyncMock(return_value="模型推荐总结")) as summary_mock,
    ):
        result = await get_major_recommendations(ctx)

    assert result == "模型推荐总结"
    summary_mock.assert_awaited_once_with(major_list, "女生")
