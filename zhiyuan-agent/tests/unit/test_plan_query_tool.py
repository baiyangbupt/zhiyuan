"""Unit tests for plan_query_tool."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.tools.plan_query_tool import (
    _build_query_keywords,
    _infer_query_focus,
    _looks_like_plan_action_query,
    _matches_query,
    _normalize_query_text,
    _normalize_scope,
    _resolve_query_scope,
    query_volunteer_plan,
)


def _ctx(session_id: str = "23", batch: str = "01"):
    return SimpleNamespace(deps=SimpleNamespace(sessionid=session_id, batch=batch))


def test_normalize_query_text_strips_filler_words():
    assert _normalize_query_text("看看生物工程") == "生物工程"
    assert _normalize_query_text("当前方案里有没有北京农学院") == "北京农学院"


def test_build_query_keywords_strips_generic_related_suffixes():
    assert _build_query_keywords("当前方案里有没有网络与新媒体相关专业") == [
        "网络与新媒体相关专业",
        "网络与新媒体",
    ]


def test_resolve_query_scope_prefers_candidate_when_explicit():
    assert _resolve_query_scope("候选里还有什么生物工程") == "candidate"
    assert _resolve_query_scope("当前方案里有没有生物工程") == "plan"
    assert _resolve_query_scope("看看生物工程") == "plan_then_candidate"


def test_plan_action_query_hint_is_not_local_plan_lookup():
    assert _looks_like_plan_action_query("帮我补几个更稳的")
    assert _looks_like_plan_action_query("还差的几个怎么补")
    assert not _looks_like_plan_action_query("候选里还有什么生物工程")


def test_normalize_scope_accepts_explicit_values_and_falls_back_to_auto():
    assert _normalize_scope("plan") == "plan"
    assert _normalize_scope("candidate") == "candidate"
    assert _normalize_scope("plan-then-candidate") == "plan_then_candidate"
    assert _normalize_scope("auto") == "auto"
    assert _normalize_scope("unknown") == "auto"


def test_infer_query_focus_routes_major_school_and_province_keywords():
    assert _infer_query_focus("候选里看看生物工程", "生物工程") == "major"
    assert _infer_query_focus("候选里看看北京农学院", "北京农学院") == "school"
    assert _infer_query_focus("候选里看看北京", "北京") == "province"


@pytest.mark.asyncio
async def test_query_volunteer_plan_rejects_plan_action_query_without_fetching_plan():
    with patch("app.tools.plan_query_tool.get_planning_ordered_plan", new=AsyncMock()) as mock_ordered:
        result = await query_volunteer_plan(_ctx(), "帮我补几个更稳的")

    assert "不是局部查询" in result
    assert "方案动作预览" in result
    mock_ordered.assert_not_awaited()


def test_matches_query_checks_text_fields_and_rank_tags():
    item = {
        "schoolName": "北京联合大学(17)",
        "majorName": "机器人工程",
        "provinceName": "北京",
        "cityName": "海淀",
        "tier": "稳",
        "schoolRankTags": ["公办", "省重点"],
        "schoolBasicTags": ["理工"],
        "majorRankTags": ["专业热度80"],
        "majorPlanTags": ["中外合作办学"],
    }

    assert _matches_query(item, "机器人工程")
    assert _matches_query(item, "北京")
    assert _matches_query(item, "省重点")
    assert _matches_query(item, "中外合作")
    assert not _matches_query(item, "生物工程")


def test_matches_query_supports_school_major_combined_lookup_across_group_name():
    item = {
        "schoolName": "广西师范大学006专业组",
        "majorName": "工业设计",
        "tier": "保",
    }

    assert _matches_query(item, "广西师范大学工业设计")
    assert _matches_query(item, "广西师范大学-工业设计")


@pytest.mark.asyncio
async def test_query_volunteer_plan_returns_current_plan_hits_first():
    ordered_result = {
        "code": 0,
        "data": {
            "items": [
                {
                    "schoolName": "北京联合大学(17)",
                    "majorName": "生物工程",
                    "tier": "保",
                    "admissionRatio": 99,
                }
            ]
        },
    }

    with (
        patch("app.tools.plan_query_tool.get_planning_ordered_plan", new=AsyncMock(return_value=ordered_result)),
        patch("app.tools.plan_query_tool.get_planning_draft", new=AsyncMock(return_value={"code": 0, "data": {"items": []}})),
        patch("app.tools.plan_query_tool.query_planning_candidate_pool", new=AsyncMock()) as candidate_mock,
    ):
        result = await query_volunteer_plan(_ctx(), "看看生物工程")

    assert "当前排序方案里共命中了" in result
    assert "下面仅展示前 1 条示例" in result
    assert "北京联合大学(17)-生物工程" in result
    candidate_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_query_volunteer_plan_matches_school_and_major_across_group_name():
    ordered_result = {
        "code": 0,
        "data": {
            "items": [
                {
                    "schoolName": "广西师范大学006专业组",
                    "majorName": "工业设计",
                    "tier": "保",
                    "admissionRatio": 99,
                }
            ]
        },
    }

    with (
        patch("app.tools.plan_query_tool.get_planning_ordered_plan", new=AsyncMock(return_value=ordered_result)),
        patch("app.tools.plan_query_tool.get_planning_draft", new=AsyncMock(return_value={"code": 0, "data": {"items": []}})),
        patch("app.tools.plan_query_tool.query_planning_candidate_pool", new=AsyncMock()) as candidate_mock,
    ):
        result = await query_volunteer_plan(_ctx(), "当前方案里有没有广西师范大学工业设计")

    assert "当前排序方案里共命中了 1 条和“广西师范大学工业设计”相关的志愿" in result
    assert "广西师范大学006专业组-工业设计" in result
    candidate_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_query_volunteer_plan_structured_school_and_major_filters_support_grouped_school_name():
    ordered_result = {
        "code": 0,
        "data": {
            "items": [
                {
                    "volunteerId": "v-group-1",
                    "schoolName": "广西师范大学006专业组",
                    "majorName": "工业设计",
                    "tier": "保",
                    "admissionRatio": 99,
                }
            ]
        },
    }

    with (
        patch("app.tools.plan_query_tool.get_planning_ordered_plan", new=AsyncMock(return_value=ordered_result)),
        patch("app.tools.plan_query_tool.get_planning_draft", new=AsyncMock(return_value={"code": 0, "data": {"items": []}})),
        patch("app.tools.plan_query_tool.get_planning_state", new=AsyncMock(return_value={"code": 0, "data": {"candidatePoolState": {"items": []}}})),
        patch("app.tools.plan_query_tool.query_planning_candidate_pool", new=AsyncMock()) as candidate_mock,
    ):
        result = await query_volunteer_plan(
            _ctx(),
            scope="plan",
            school_keywords=["广西师范大学"],
            major_keywords=["工业设计"],
        )

    assert "当前排序方案里共命中了 1 条符合“院校:广西师范大学；专业:工业设计”" in result
    assert "广西师范大学006专业组-工业设计" in result
    candidate_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_query_volunteer_plan_matches_major_query_with_related_major_suffix():
    ordered_result = {
        "code": 0,
        "data": {
            "items": [
                {
                    "schoolName": "上海建桥学院第01组",
                    "majorName": "网络与新媒体",
                    "tier": "保",
                    "admissionRatio": 88,
                }
            ]
        },
    }

    with (
        patch("app.tools.plan_query_tool.get_planning_ordered_plan", new=AsyncMock(return_value=ordered_result)),
        patch("app.tools.plan_query_tool.get_planning_draft", new=AsyncMock(return_value={"code": 0, "data": {"items": []}})),
        patch("app.tools.plan_query_tool.query_planning_candidate_pool", new=AsyncMock()) as candidate_mock,
    ):
        result = await query_volunteer_plan(_ctx(), "当前方案里有没有网络与新媒体相关专业", scope="plan")

    assert "当前排序方案里共命中了 1 条和“网络与新媒体相关专业”相关的志愿" in result
    assert "上海建桥学院第01组-网络与新媒体" in result
    candidate_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_query_volunteer_plan_structured_region_and_major_filters_use_candidate_metadata_merge():
    ordered_result = {
        "code": 0,
        "data": {
            "items": [
                {
                    "volunteerId": "v1",
                    "schoolName": "上海建桥学院第01组",
                    "majorName": "网络与新媒体",
                    "tier": "保",
                    "admissionRatio": 88,
                    "provinceName": None,
                }
            ]
        },
    }
    planning_state = {
        "code": 0,
        "data": {
            "candidatePoolState": {
                "items": [
                    {
                        "volunteerId": "v1",
                        "schoolName": "上海建桥学院第01组",
                        "majorName": "网络与新媒体",
                        "provinceName": "上海",
                        "cityName": "浦东",
                        "tier": "保",
                        "schoolNature": "民办",
                        "schoolCategory": "财经",
                        "schoolRankTags": ["意向省份"],
                        "schoolBasicTags": ["上海.浦东", "本科", "民办", "财经"],
                        "majorRankTags": ["专业热度53"],
                        "majorPlanTags": ["计划数：2"],
                    }
                ]
            }
        },
    }

    with (
        patch("app.tools.plan_query_tool.get_planning_ordered_plan", new=AsyncMock(return_value=ordered_result)),
        patch("app.tools.plan_query_tool.get_planning_draft", new=AsyncMock(return_value={"code": 0, "data": {"items": []}})),
        patch("app.tools.plan_query_tool.get_planning_state", new=AsyncMock(return_value=planning_state)),
        patch("app.tools.plan_query_tool.query_planning_candidate_pool", new=AsyncMock()) as candidate_mock,
    ):
        result = await query_volunteer_plan(
            _ctx(),
            scope="plan",
            province_names=["上海"],
            major_keywords=["网络与新媒体"],
        )

    assert "当前排序方案里共命中了 1 条符合“专业:网络与新媒体；省份:上海”" in result
    assert "上海建桥学院第01组-网络与新媒体" in result
    candidate_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_query_volunteer_plan_falls_back_to_draft_when_ordered_plan_is_empty():
    ordered_result = {"code": 0, "data": {"items": []}}
    draft_result = {
        "code": 0,
        "data": {
            "items": [
                {
                    "schoolName": "北京农学院(03)",
                    "majorName": "生物工程",
                    "tier": "保",
                    "admissionRatio": 75.5,
                }
            ]
        },
    }

    with (
        patch("app.tools.plan_query_tool.get_planning_ordered_plan", new=AsyncMock(return_value=ordered_result)) as ordered_mock,
        patch("app.tools.plan_query_tool.get_planning_draft", new=AsyncMock(return_value=draft_result)) as draft_mock,
        patch("app.tools.plan_query_tool.query_planning_candidate_pool", new=AsyncMock()) as candidate_mock,
    ):
        result = await query_volunteer_plan(_ctx(), "当前方案里有没有生物工程")

    assert "当前已加入方案里共命中了" in result
    assert "75.5%" in result
    ordered_mock.assert_awaited_once_with("23")
    draft_mock.assert_awaited_once_with("23")
    candidate_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_query_volunteer_plan_falls_back_to_candidate_opportunities_when_plan_has_no_hit():
    ordered_result = {
        "code": 0,
        "data": {
            "items": [
                {
                    "schoolName": "北京工业大学",
                    "majorName": "机械工程",
                    "tier": "稳",
                    "admissionRatio": 66,
                }
            ]
        },
    }
    candidate_result = {
        "code": 0,
        "data": {
            "total": 2,
            "items": [
                {
                    "schoolName": "北京农学院(03)",
                    "majorName": "生物工程",
                    "tier": "保",
                    "admissionRatio": 99,
                    "volunteerId": "v1",
                }
            ],
        },
    }

    with (
        patch("app.tools.plan_query_tool.get_planning_ordered_plan", new=AsyncMock(return_value=ordered_result)),
        patch("app.tools.plan_query_tool.get_planning_draft", new=AsyncMock(return_value={"code": 0, "data": {"items": []}})),
        patch("app.tools.plan_query_tool.query_planning_candidate_pool", new=AsyncMock(return_value=candidate_result)),
    ):
        result = await query_volunteer_plan(_ctx(), "看看生物工程")

    assert "当前排序方案里暂时没有命中“生物工程”" in result
    assert "候选里共命中了 2 条和“生物工程”相关的机会" in result
    assert "北京农学院(03)-生物工程" in result


@pytest.mark.asyncio
async def test_query_volunteer_plan_uses_candidate_scope_when_explicit():
    candidate_result = {
        "code": 0,
        "data": {
            "total": 1,
            "items": [
                {
                    "schoolName": "北京农学院(03)",
                    "majorName": "生物工程",
                    "tier": "保",
                    "admissionRatio": 99,
                    "volunteerId": "v2",
                }
            ],
        },
    }

    with (
        patch("app.tools.plan_query_tool.get_planning_ordered_plan", new=AsyncMock()) as ordered_mock,
        patch("app.tools.plan_query_tool.get_planning_draft", new=AsyncMock()) as draft_mock,
        patch("app.tools.plan_query_tool.query_planning_candidate_pool", new=AsyncMock(return_value=candidate_result)) as candidate_mock,
    ):
        result = await query_volunteer_plan(_ctx(), "候选里还有什么生物工程")

    assert "候选里共命中了 1 条和“生物工程”相关的机会" in result
    ordered_mock.assert_not_awaited()
    draft_mock.assert_not_awaited()
    candidate_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_query_volunteer_plan_explicit_plan_scope_does_not_fall_back_to_candidate():
    ordered_result = {
        "code": 0,
        "data": {
            "items": [
                {
                    "schoolName": "北京工业大学",
                    "majorName": "机械工程",
                    "tier": "稳",
                    "admissionRatio": 66,
                }
            ]
        },
    }

    with (
        patch("app.tools.plan_query_tool.get_planning_ordered_plan", new=AsyncMock(return_value=ordered_result)),
        patch("app.tools.plan_query_tool.get_planning_draft", new=AsyncMock(return_value={"code": 0, "data": {"items": []}})),
        patch("app.tools.plan_query_tool.query_planning_candidate_pool", new=AsyncMock()) as candidate_mock,
    ):
        result = await query_volunteer_plan(_ctx(), "候选里还有什么生物工程", scope="plan")

    assert "当前排序方案里暂时没有命中“生物工程”" in result
    candidate_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_query_volunteer_plan_explicit_candidate_scope_overrides_query_text():
    candidate_result = {
        "code": 0,
        "data": {
            "total": 1,
            "items": [
                {
                    "schoolName": "北京农学院(03)",
                    "majorName": "生物工程",
                    "tier": "保",
                    "admissionRatio": 99,
                    "volunteerId": "v2",
                }
            ],
        },
    }

    with (
        patch("app.tools.plan_query_tool.get_planning_ordered_plan", new=AsyncMock()) as ordered_mock,
        patch("app.tools.plan_query_tool.get_planning_draft", new=AsyncMock()) as draft_mock,
        patch("app.tools.plan_query_tool.query_planning_candidate_pool", new=AsyncMock(return_value=candidate_result)) as candidate_mock,
    ):
        result = await query_volunteer_plan(_ctx(), "当前方案里有没有生物工程", scope="candidate")

    assert "候选里共命中了 1 条和“生物工程”相关的机会" in result
    ordered_mock.assert_not_awaited()
    draft_mock.assert_not_awaited()
    candidate_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_query_volunteer_plan_candidate_scope_passes_major_keyword_filter():
    candidate_result = {"code": 0, "data": {"total": 0, "items": []}}

    with patch(
        "app.tools.plan_query_tool.query_planning_candidate_pool",
        new=AsyncMock(return_value=candidate_result),
    ) as candidate_mock:
        await query_volunteer_plan(_ctx("66"), "候选里还有什么生物工程")

    candidate_mock.assert_awaited_once_with(
        1,
        "66",
        page=1,
        page_size=20,
        sort_field="finalScore",
        sort_order="desc",
        major_keywords=["生物工程"],
    )


@pytest.mark.asyncio
async def test_query_volunteer_plan_candidate_empty_result_is_business_empty_not_delay():
    candidate_result = {"code": 0, "data": {"total": 0, "items": []}}

    with patch(
        "app.tools.plan_query_tool.query_planning_candidate_pool",
        new=AsyncMock(return_value=candidate_result),
    ):
        result = await query_volunteer_plan(_ctx("66"), "候选里还有什么生物工程")

    assert "候选里暂时没有筛到和“生物工程”相关的机会" in result
    assert "不是系统延迟或查询失败" in result


@pytest.mark.asyncio
async def test_query_volunteer_plan_candidate_scope_passes_province_filter():
    candidate_result = {"code": 0, "data": {"total": 0, "items": []}}

    with patch(
        "app.tools.plan_query_tool.query_planning_candidate_pool",
        new=AsyncMock(return_value=candidate_result),
    ) as candidate_mock:
        await query_volunteer_plan(_ctx("66"), "候选里看看北京")

    candidate_mock.assert_awaited_once_with(
        1,
        "66",
        page=1,
        page_size=20,
        sort_field="finalScore",
        sort_order="desc",
        province_names=["北京"],
    )


@pytest.mark.asyncio
async def test_query_volunteer_plan_candidate_scope_passes_school_keyword_filter():
    candidate_result = {"code": 0, "data": {"total": 0, "items": []}}

    with patch(
        "app.tools.plan_query_tool.query_planning_candidate_pool",
        new=AsyncMock(return_value=candidate_result),
    ) as candidate_mock:
        await query_volunteer_plan(_ctx("66"), "候选里看看北京农学院")

    candidate_mock.assert_awaited_once_with(
        1,
        "66",
        page=1,
        page_size=20,
        sort_field="finalScore",
        sort_order="desc",
        school_keywords=["北京农学院"],
    )


@pytest.mark.asyncio
async def test_query_volunteer_plan_candidate_scope_supports_structured_multi_filters():
    candidate_result = {"code": 0, "data": {"total": 0, "items": []}}

    with patch(
        "app.tools.plan_query_tool.query_planning_candidate_pool",
        new=AsyncMock(return_value=candidate_result),
    ) as candidate_mock:
        await query_volunteer_plan(
            _ctx("66"),
            scope="candidate",
            province_names=["上海"],
            major_keywords=["网络与新媒体"],
        )

    candidate_mock.assert_awaited_once_with(
        1,
        "66",
        tiers=[],
        province_names=["上海"],
        city_names=[],
        school_keywords=[],
        major_keywords=["网络与新媒体"],
        school_tags=[],
        major_tags=[],
        page=1,
        page_size=20,
        sort_field="finalScore",
        sort_order="desc",
    )


@pytest.mark.asyncio
async def test_query_volunteer_plan_structured_candidate_empty_result_is_business_empty_not_delay():
    candidate_result = {"code": 0, "data": {"total": 0, "items": []}}

    with patch(
        "app.tools.plan_query_tool.query_planning_candidate_pool",
        new=AsyncMock(return_value=candidate_result),
    ):
        result = await query_volunteer_plan(
            _ctx("66"),
            scope="candidate",
            province_names=["上海"],
            major_keywords=["网络与新媒体"],
        )

    assert "候选里暂时没有筛到符合“专业:网络与新媒体；省份:上海”的机会" in result
    assert "不是系统延迟或查询失败" in result


@pytest.mark.asyncio
async def test_query_volunteer_plan_returns_candidate_failure_message():
    with patch(
        "app.tools.plan_query_tool.query_planning_candidate_pool",
        new=AsyncMock(return_value={"code": 500, "data": None}),
    ):
        result = await query_volunteer_plan(_ctx(), "候选里还有什么生物工程")

    assert result == "查询候选机会失败，请稍后重试。"
