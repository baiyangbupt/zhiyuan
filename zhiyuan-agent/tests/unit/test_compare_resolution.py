from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.tools.major_compare_tool import compare_major_options, compare_majors, _resolve_major_name
from app.tools.school_compare_tool import compare_schools, _resolve_school_name


@pytest.mark.asyncio
async def test_resolve_major_name_skips_fuzzy_and_llm_when_catalog_normalizes():
    with (
        patch(
            "app.tools.major_compare_tool.resolve_major_names_async",
            new=AsyncMock(return_value=["计算机科学与技术"]),
        ) as normalize_mock,
        patch("app.tools.major_compare_tool.fuzzy_match_major_name") as fuzzy_mock,
        patch("app.tools.major_compare_tool.Agent") as agent_mock,
    ):
        result = await _resolve_major_name(
            "计科",
            {"计算机科学与技术"},
            {},
            "01",
        )

    assert result == "计算机科学与技术"
    normalize_mock.assert_awaited_once_with(["计科"], "level3", "01")
    fuzzy_mock.assert_not_called()
    agent_mock.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_school_name_skips_fuzzy_and_llm_when_catalog_normalizes():
    with (
        patch(
            "app.tools.school_compare_tool.resolve_school_names_async",
            new=AsyncMock(return_value=["北京大学"]),
        ) as normalize_mock,
        patch("app.tools.school_compare_tool.fuzzy_match_school_name") as fuzzy_mock,
        patch("app.tools.school_compare_tool.Agent") as agent_mock,
    ):
        result = await _resolve_school_name(
            "北大",
            {"北京大学"},
            {},
        )

    assert result == "北京大学"
    normalize_mock.assert_awaited_once_with(["北大"])
    fuzzy_mock.assert_not_called()
    agent_mock.assert_not_called()


@pytest.mark.asyncio
async def test_compare_majors_skips_inner_summary_llm_when_chat_service_disables_it():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="s1",
            batch="01",
            allow_explore_inner_llm=False,
        )
    )
    weights1 = {
        "gender_flag": "女生",
        "querylist": [
            {
                "gender_index": 72,
                "satisfy_index": 81,
                "salary_avg": 7600,
                "hot_index": 88,
                "major_score": 82,
                "major_score_new": 85,
                "major_remark": "较匹配",
            }
        ],
    }
    weights2 = {
        "gender_flag": "女生",
        "querylist": [
            {
                "gender_index": 68,
                "satisfy_index": 84,
                "salary_avg": 7100,
                "hot_index": 76,
                "major_score": 78,
                "major_score_new": 79,
            }
        ],
    }

    with (
        patch(
            "app.tools.major_compare_tool.query_volunteer_analysis_weight",
            new=AsyncMock(side_effect=[weights1, weights2]),
        ),
        patch("app.tools.major_compare_tool._summarize_comparison", new=AsyncMock()) as summary_mock,
    ):
        result = await compare_majors(ctx, "法学", "财政学")

    summary_mock.assert_not_awaited()
    assert "专业对比：法学（法学类） vs 财政学（财政学类）" in result
    assert "关键指标" in result
    assert "综合评分" in result
    assert "较匹配" in result
    assert "高校毕业生就业调查数据" in result


@pytest.mark.asyncio
async def test_compare_major_options_queries_multiple_majors_once_and_returns_facts():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="s1",
            batch="01",
            allow_explore_inner_llm=False,
        )
    )
    weights = {
        "gender_flag": "女生",
        "querylist": [
            {"satisfy_index": 80, "salary_avg": 7200, "hot_index": 88, "major_score_new": 82},
            {"satisfy_index": 78, "salary_avg": 7000, "hot_index": 84, "major_score_new": 80},
            {"satisfy_index": 76, "salary_avg": 6900, "hot_index": 73, "major_score_new": 75},
        ],
    }

    with patch(
        "app.tools.major_compare_tool.query_volunteer_analysis_weight",
        new=AsyncMock(return_value=weights),
    ) as query_mock:
        result = await compare_major_options(ctx, ["财务管理", "会计学", "审计学"])

    query_mock.assert_awaited_once()
    payload = query_mock.await_args.args[2]
    assert [item["major_name"] for item in payload] == ["财务管理", "会计学", "审计学"]
    assert "多专业取舍事实：财务管理、会计学、审计学" in result
    assert "专业横向对照" in result
    assert "财务管理（工商管理类）" in result
    assert "会计学（工商管理类）" in result
    assert "审计学（工商管理类）" in result
    assert "如果用户要求给出优先级" in result


@pytest.mark.asyncio
async def test_compare_majors_keeps_inner_summary_llm_by_default():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="s1",
            batch="01",
        )
    )

    with (
        patch(
            "app.tools.major_compare_tool.query_volunteer_analysis_weight",
            new=AsyncMock(side_effect=[{"querylist": []}, {"querylist": []}]),
        ),
        patch("app.tools.major_compare_tool._summarize_comparison", new=AsyncMock(return_value="模型总结")) as summary_mock,
    ):
        result = await compare_majors(ctx, "法学", "财政学")

    assert result == "模型总结"
    summary_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_compare_majors_missing_weights_returns_user_facing_facts_without_equal_score_claim():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="s2",
            batch="01",
            allow_explore_inner_llm=False,
        )
    )

    with (
        patch(
            "app.tools.major_compare_tool.query_volunteer_analysis_weight",
            new=AsyncMock(side_effect=[{"querylist": []}, {"querylist": []}]),
        ),
        patch("app.tools.major_compare_tool._summarize_comparison", new=AsyncMock()) as summary_mock,
    ):
        result = await compare_majors(ctx, "法学", "财政学")

    summary_mock.assert_not_awaited()
    assert "当前缺少完整个性化量化评分" in result
    assert "不能只按分数判断哪个一定更适合" in result
    assert "得分相同" not in result


@pytest.mark.asyncio
async def test_compare_schools_skips_inner_summary_llm_when_chat_service_disables_it():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="s3",
            batch="01",
            allow_explore_inner_llm=False,
        )
    )
    weights1 = {
        "querylist": [
            {
                "province_gdp": 90,
                "city_level": 85,
                "upgrade_ratio": 65,
                "postgraduate_recommend_ratio": 40,
                "level_score": 88,
                "college_score": 82,
                "college_score_new": 84,
                "college_remark": "较匹配",
            }
        ],
    }
    weights2 = {
        "querylist": [
            {
                "province_gdp": 76,
                "city_level": 70,
                "upgrade_ratio": 71,
                "postgraduate_recommend_ratio": 30,
                "level_score": 80,
                "college_score": 78,
            }
        ],
    }

    with (
        patch(
            "app.tools.school_compare_tool.query_school_analysis_weight",
            new=AsyncMock(side_effect=[weights1, weights2]),
        ),
        patch("app.tools.school_compare_tool._summarize_comparison", new=AsyncMock()) as summary_mock,
    ):
        result = await compare_schools(ctx, "北京大学", "天津大学")

    summary_mock.assert_not_awaited()
    assert "院校对比：北京大学 vs 天津大学" in result
    assert "关键指标" in result
    assert "综合评分" in result
    assert "较匹配" in result
    assert "国家统计局GDP数据" in result


@pytest.mark.asyncio
async def test_compare_schools_keeps_inner_summary_llm_by_default():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="s4",
            batch="01",
        )
    )

    with (
        patch(
            "app.tools.school_compare_tool.query_school_analysis_weight",
            new=AsyncMock(side_effect=[{"querylist": []}, {"querylist": []}]),
        ),
        patch("app.tools.school_compare_tool._summarize_comparison", new=AsyncMock(return_value="院校模型总结")) as summary_mock,
    ):
        result = await compare_schools(ctx, "北京大学", "天津大学")

    assert result == "院校模型总结"
    summary_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_compare_schools_missing_weights_returns_user_facing_facts_without_equal_score_claim():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="s5",
            batch="01",
            allow_explore_inner_llm=False,
        )
    )

    with (
        patch(
            "app.tools.school_compare_tool.query_school_analysis_weight",
            new=AsyncMock(side_effect=[{"querylist": []}, {"querylist": []}]),
        ),
        patch("app.tools.school_compare_tool._summarize_comparison", new=AsyncMock()) as summary_mock,
    ):
        result = await compare_schools(ctx, "北京大学", "天津大学")

    summary_mock.assert_not_awaited()
    assert "当前缺少完整个性化量化评分" in result
    assert "不能只按分数判断哪所院校一定更适合" in result
    assert "得分相同" not in result
