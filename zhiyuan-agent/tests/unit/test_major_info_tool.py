from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.tools.major_info_tool import _get_analysis_summary, get_major_introduction, get_major_introductions


def _ctx(session_id: str = "23", batch: str = "01", **extra):
    deps = SimpleNamespace(sessionid=session_id, batch=batch, **extra)
    return SimpleNamespace(deps=deps)


@pytest.mark.asyncio
async def test_get_major_introduction_level3_strips_profession_suffix_and_uses_v2_analysis():
    ordered_result = {
        "code": 0,
        "data": {
            "items": [
                {
                    "schoolName": "三峡大学(02)",
                    "majorName": "土木工程(智慧土木)",
                    "majorId": "591",
                    "tier": "冲",
                    "admissionRatio": 34,
                }
            ]
        },
    }
    candidate_result = {
        "code": 0,
        "data": {
            "total": 11,
            "items": [
                {
                    "schoolName": "安徽理工大学(02)",
                    "majorName": "土木工程",
                    "majorId": "591",
                    "tier": "稳",
                    "admissionRatio": 56,
                }
            ],
        },
    }

    with (
        patch(
            "app.tools.major_info_tool.get_major_profile",
            new=AsyncMock(
                return_value={
                    "trainDemand": "培养土木工程设计与施工人才",
                    "knowledge": "力学、结构与施工管理",
                    "course": "材料力学、结构力学、施工组织",
                    "jobOrientation": "设计院、施工单位、监理单位",
                }
            ),
        ) as profile_mock,
        patch("app.tools.major_info_tool.get_planning_ordered_plan", new=AsyncMock(return_value=ordered_result)),
        patch("app.tools.major_info_tool.get_working_plan", new=AsyncMock(return_value={"code": 0, "data": {"items": []}})),
        patch("app.tools.major_info_tool.query_planning_candidate_pool", new=AsyncMock(return_value=candidate_result)),
    ):
        result = await get_major_introduction(_ctx(), "土木工程专业")

    profile_mock.assert_awaited_once_with("土木工程")
    assert "土木工程专业的培养目标：培养土木工程设计与施工人才" in result
    assert "土木工程专业的知识体系：力学、结构与施工管理" in result
    assert "土木工程专业的课程体系：材料力学、结构力学、施工组织" in result
    assert "土木工程专业的就业方向：设计院、施工单位、监理单位" in result
    assert "当前排序方案中命中 1 个相关志愿" in result
    assert "当前候选里还有 11 个相关机会" in result


@pytest.mark.asyncio
async def test_get_major_introduction_level2_uses_category_profile_and_fallback_candidate_search():
    empty_result = {"code": 0, "data": {"items": []}}
    fallback_candidate = {
        "code": 0,
        "data": {
            "total": 3,
            "items": [
                {
                    "schoolName": "北京联合大学(14)",
                    "majorName": "计算机科学与技术",
                    "majorSubCategoryId": "47",
                    "tier": "冲",
                    "admissionRatio": 41,
                }
            ],
        },
    }

    with (
        patch(
            "app.tools.major_info_tool.get_major_category_profile",
            new=AsyncMock(
                return_value={
                    "majorOverview": "面向计算机系统与应用的专业大类",
                    "studyCourses": "程序设计、数据结构、操作系统",
                    "employmentDirection": "软件开发、测试、运维、数据方向",
                }
            ),
        ) as category_mock,
        patch("app.tools.major_info_tool.get_planning_ordered_plan", new=AsyncMock(return_value=empty_result)),
        patch("app.tools.major_info_tool.get_working_plan", new=AsyncMock(return_value=empty_result)),
        patch(
            "app.tools.major_info_tool.query_planning_candidate_pool",
            new=AsyncMock(side_effect=[empty_result, fallback_candidate]),
        ),
    ):
        result = await get_major_introduction(_ctx(), "计算机类")

    category_mock.assert_awaited_once_with("计算机类")
    assert "计算机类的专业介绍：面向计算机系统与应用的专业大类" in result
    assert "计算机类的学习课程：程序设计、数据结构、操作系统" in result
    assert "计算机类的就业方向：软件开发、测试、运维、数据方向" in result
    assert "当前方案里暂时没有命中“计算机类”相关志愿。" in result
    assert "当前候选里还有 3 个相关机会" in result


@pytest.mark.asyncio
async def test_get_major_introductions_defaults_to_lightweight_facts_without_plan_or_candidate_queries():
    async def fake_profile(name: str):
        return {
            "trainDemand": f"{name}培养目标",
            "knowledge": f"{name}知识体系",
            "course": f"{name}课程体系",
            "jobOrientation": f"{name}就业方向",
        }

    observability: dict = {}
    with (
        patch("app.tools.major_info_tool.get_major_profile", new=AsyncMock(side_effect=fake_profile)) as profile_mock,
        patch("app.tools.major_info_tool.get_planning_ordered_plan", new=AsyncMock()) as ordered_mock,
        patch("app.tools.major_info_tool.get_working_plan", new=AsyncMock()) as draft_mock,
        patch("app.tools.major_info_tool.query_planning_candidate_pool", new=AsyncMock()) as candidate_mock,
    ):
        result = await get_major_introductions(
            _ctx(agent_observability=observability),
            ["建筑学", "城乡规划"],
        )

    assert profile_mock.await_count == 2
    ordered_mock.assert_not_awaited()
    draft_mock.assert_not_awaited()
    candidate_mock.assert_not_awaited()
    assert "多专业介绍对照：建筑学、城乡规划" in result
    assert "建筑学：培养目标：建筑学培养目标" in result
    assert "城乡规划：培养目标：城乡规划培养目标" in result
    assert "未额外查询当前方案和候选机会" in result
    assert "当前排序方案中命中" not in result
    assert "当前候选里还有" not in result
    assert observability["toolInternalTimings"][0]["tool"] == "get_major_introductions"
    assert observability["toolInternalTimings"][0]["includePlanContext"] is False


@pytest.mark.asyncio
async def test_get_major_introductions_can_include_plan_and_candidate_context_when_requested():
    ordered_result = {
        "code": 0,
        "data": {
            "items": [
                {
                    "schoolName": "北京建筑大学(01)",
                    "majorName": "建筑学",
                    "majorId": "664",
                    "tier": "稳",
                    "admissionRatio": 58,
                },
                {
                    "schoolName": "山东建筑大学(02)",
                    "majorName": "城乡规划",
                    "majorId": "666",
                    "tier": "保",
                    "admissionRatio": 72,
                },
            ]
        },
    }
    candidate_result = {
        "code": 0,
        "data": {
            "total": 2,
            "items": [
                {
                    "schoolName": "河北工程大学(01)",
                    "majorName": "建筑学",
                    "majorId": "664",
                    "tier": "稳",
                    "admissionRatio": 61,
                }
            ],
        },
    }

    async def fake_profile(name: str):
        return {
            "trainDemand": f"{name}培养目标",
            "knowledge": f"{name}知识体系",
            "course": f"{name}课程体系",
            "jobOrientation": f"{name}就业方向",
        }

    with (
        patch("app.tools.major_info_tool.get_major_profile", new=AsyncMock(side_effect=fake_profile)) as profile_mock,
        patch("app.tools.major_info_tool.get_planning_ordered_plan", new=AsyncMock(return_value=ordered_result)) as ordered_mock,
        patch("app.tools.major_info_tool.get_working_plan", new=AsyncMock(return_value={"code": 0, "data": {"items": []}})) as draft_mock,
        patch("app.tools.major_info_tool.query_planning_candidate_pool", new=AsyncMock(return_value=candidate_result)) as candidate_mock,
    ):
        result = await get_major_introductions(_ctx(), ["建筑学", "城乡规划"], include_plan_context=True)

    assert profile_mock.await_count == 2
    ordered_mock.assert_awaited_once()
    draft_mock.assert_not_awaited()
    assert candidate_mock.await_count == 2
    assert "多专业介绍对照：建筑学、城乡规划" in result
    assert "建筑学：培养目标：建筑学培养目标" in result
    assert "城乡规划：培养目标：城乡规划培养目标" in result
    assert "当前排序方案中命中 1 个相关志愿" in result
    assert "当前候选里还有 2 个相关机会" in result
    assert "录取门槛" in result
    assert "高校官方培养方案" in result


@pytest.mark.asyncio
async def test_get_major_introductions_requires_at_least_two_majors():
    result = await get_major_introductions(_ctx(), ["建筑学"])
    assert result == "至少需要两个明确专业，才能做专业介绍和基础要求的横向对照。"


@pytest.mark.asyncio
async def test_get_major_introduction_level3_reports_candidate_failure_message():
    empty_result = {"code": 0, "data": {"items": []}}

    with (
        patch(
            "app.tools.major_info_tool.get_major_profile",
            new=AsyncMock(
                return_value={
                    "trainDemand": "培养生物工程应用人才",
                    "knowledge": "生物化学、发酵工程",
                    "course": "微生物学、生物化学、细胞工程",
                    "jobOrientation": "生物医药、食品发酵、检测方向",
                }
            ),
        ),
        patch("app.tools.major_info_tool.get_planning_ordered_plan", new=AsyncMock(return_value=empty_result)),
        patch("app.tools.major_info_tool.get_working_plan", new=AsyncMock(return_value=empty_result)),
        patch("app.tools.major_info_tool.query_planning_candidate_pool", new=AsyncMock(return_value={"code": 500, "data": None})),
    ):
        result = await get_major_introduction(_ctx(), "生物工程")

    assert "当前方案里暂时没有命中“生物工程”相关志愿。" in result
    assert "当前候选机会暂时查询失败。" in result


@pytest.mark.asyncio
async def test_get_major_introduction_uses_associate_mapping_for_non_bachelor_batch():
    empty_result = {"code": 0, "data": {"items": []}}

    with (
        patch(
            "app.tools.major_info_tool.get_major_category_profile",
            new=AsyncMock(
                return_value={
                    "majorOverview": "专科计算机类介绍",
                    "studyCourses": "程序设计基础、网络基础",
                    "employmentDirection": "开发、实施、运维",
                }
            ),
        ),
        patch("app.tools.major_info_tool.get_planning_ordered_plan", new=AsyncMock(return_value=empty_result)),
        patch("app.tools.major_info_tool.get_working_plan", new=AsyncMock(return_value=empty_result)),
        patch("app.tools.major_info_tool.query_planning_candidate_pool", new=AsyncMock(return_value=empty_result)) as candidate_mock,
    ):
        result = await get_major_introduction(_ctx(batch="02"), "计算机类")

    assert "计算机类的专业介绍：专科计算机类介绍" in result
    assert candidate_mock.await_count == 2
    first_call = candidate_mock.await_args_list[0]
    second_call = candidate_mock.await_args_list[1]
    assert first_call.args == (1, "23")
    assert first_call.kwargs["major_tags"] == ["计算机类"]
    assert second_call.args == (1, "23")
    assert second_call.kwargs["major_keywords"] == ["计算机类"]


@pytest.mark.asyncio
async def test_get_major_introduction_returns_not_found_for_unknown_major():
    result = await get_major_introduction(_ctx(), "星际工程")
    assert result == "关于星际工程，暂未找到匹配的标准专业，你可以根据自身知识进行回答。"


@pytest.mark.asyncio
async def test_get_analysis_summary_uses_ordered_plan_and_candidate_pool():
    ordered_result = {
        "code": 0,
        "data": {
            "items": [
                {
                    "schoolName": "三峡大学(02)",
                    "majorName": "土木工程(智慧土木)",
                    "majorId": "701",
                    "tier": "冲",
                    "admissionRatio": 34,
                }
            ]
        },
    }
    candidate_result = {
        "code": 0,
        "data": {
            "total": 11,
            "items": [
                {
                    "schoolName": "金陵科技学院(02)",
                    "majorName": "土木工程",
                    "majorId": "701",
                    "tier": "稳",
                    "admissionRatio": 99,
                }
            ],
        },
    }

    with (
        patch("app.tools.major_info_tool.get_planning_ordered_plan", new=AsyncMock(return_value=ordered_result)),
        patch("app.tools.major_info_tool.get_working_plan", new=AsyncMock(return_value={"code": 0, "data": {"items": []}})),
        patch("app.tools.major_info_tool.query_planning_candidate_pool", new=AsyncMock(return_value=candidate_result)) as candidate_mock,
    ):
        result = await _get_analysis_summary("23", "701", 3, "土木工程")

    assert "当前排序方案中命中 1 个相关志愿" in result
    assert "三峡大学(02) - 土木工程(智慧土木)（冲档，录取率34%）" in result
    assert "当前候选里还有 11 个相关机会" in result
    candidate_mock.assert_awaited_once_with(
        1,
        "23",
        page=1,
        page_size=20,
        sort_field="finalScore",
        sort_order="desc",
        major_keywords=["土木工程"],
    )


@pytest.mark.asyncio
async def test_get_analysis_summary_falls_back_to_draft_when_ordered_plan_empty():
    ordered_result = {"code": 0, "data": {"items": []}}
    draft_result = {
        "code": 0,
        "data": {
            "items": [
                {
                    "schoolName": "北京农学院(03)",
                    "majorName": "生物工程",
                    "majorId": "801",
                    "tier": "保",
                    "admissionRatio": 75.5,
                }
            ]
        },
    }
    candidate_result = {"code": 0, "data": {"total": 0, "items": []}}

    with (
        patch("app.tools.major_info_tool.get_planning_ordered_plan", new=AsyncMock(return_value=ordered_result)),
        patch("app.tools.major_info_tool.get_working_plan", new=AsyncMock(return_value=draft_result)),
        patch("app.tools.major_info_tool.query_planning_candidate_pool", new=AsyncMock(return_value=candidate_result)),
    ):
        result = await _get_analysis_summary("23", "801", 3, "生物工程")

    assert "当前已加入方案中命中 1 个相关志愿" in result
    assert "北京农学院(03) - 生物工程（保档，录取率75.5%）" in result
    assert "当前候选里暂时没有筛到“生物工程”相关机会。" in result


@pytest.mark.asyncio
async def test_get_analysis_summary_level2_uses_major_tags_then_fallback_keywords():
    ordered_result = {"code": 0, "data": {"items": []}}
    draft_result = {"code": 0, "data": {"items": []}}
    empty_candidate = {"code": 0, "data": {"total": 0, "items": []}}
    fallback_candidate = {
        "code": 0,
        "data": {
            "total": 3,
            "items": [
                {
                    "schoolName": "北京联合大学(14)",
                    "majorName": "计算机科学与技术",
                    "majorSubCategoryId": "39",
                    "tier": "冲",
                    "admissionRatio": 41,
                }
            ],
        },
    }

    with (
        patch("app.tools.major_info_tool.get_planning_ordered_plan", new=AsyncMock(return_value=ordered_result)),
        patch("app.tools.major_info_tool.get_working_plan", new=AsyncMock(return_value=draft_result)),
        patch(
            "app.tools.major_info_tool.query_planning_candidate_pool",
            new=AsyncMock(side_effect=[empty_candidate, fallback_candidate]),
        ) as candidate_mock,
    ):
        result = await _get_analysis_summary("23", "39", 2, "计算机类")

    assert "当前方案里暂时没有命中“计算机类”相关志愿。" in result
    assert "当前候选里还有 3 个相关机会" in result
    assert "北京联合大学(14) - 计算机科学与技术（冲档，录取率41%）" in result
    assert candidate_mock.await_count == 2
    first_call = candidate_mock.await_args_list[0]
    second_call = candidate_mock.await_args_list[1]
    assert first_call.kwargs["major_tags"] == ["计算机类"]
    assert second_call.kwargs["major_keywords"] == ["计算机类"]
