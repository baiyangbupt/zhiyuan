from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.context import RequestContext, ScoreDetail
from app.tools.plan_validation_tool import validate_major_subjects, validate_plan_params
from app.tools.score_query_tool import query_admission_score, query_score_line


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(
        deps=RequestContext(
            userid="1",
            sessionid="23",
            batch="01",
            score_detail=ScoreDetail(
                province="北京",
                total_score=600,
                subject_list=["物理", "化学", "生物"],
                sex="男",
            ),
        )
    )


@pytest.mark.asyncio
async def test_query_score_line_normalizes_school_and_major_names_before_lookup():
    with (
        patch(
            "app.tools.score_query_tool.resolve_school_names_async",
            new=AsyncMock(return_value=["北京大学"]),
        ) as school_normalize_mock,
        patch(
            "app.tools.score_query_tool.resolve_major_names_async",
            new=AsyncMock(return_value=["计算机科学与技术"]),
        ) as major_normalize_mock,
        patch(
            "app.tools.score_query_tool.get_school_codes_async",
            new=AsyncMock(return_value=["10001"]),
        ) as school_code_mock,
        patch(
            "app.tools.score_query_tool.get_major_codes_async",
            new=AsyncMock(return_value=["574"]),
        ) as major_code_mock,
        patch(
            "app.tools.score_query_tool.get_province_codes_async",
            new=AsyncMock(return_value=["110000"]),
        ),
        patch(
            "app.tools.score_query_tool.resolve_batch_codes",
            return_value=["01"],
        ),
        patch(
            "app.tools.score_query_tool.query_school_major_score_line",
            new=AsyncMock(return_value={"data": [{"year": "2024", "minScore": "620"}]}),
        ),
    ):
        result = await query_score_line(_ctx(), "北大", "计科")

    school_normalize_mock.assert_awaited_once_with(["北大"])
    major_normalize_mock.assert_awaited_once_with(["计科"], "level3", "01")
    school_code_mock.assert_awaited_once_with(["北京大学"])
    major_code_mock.assert_awaited_once_with(["计算机科学与技术"], "level3", "01")
    assert "北京大学 - 计算机科学与技术" in result


@pytest.mark.asyncio
async def test_query_admission_score_normalizes_school_name_before_matching():
    with (
        patch(
            "app.tools.score_query_tool.resolve_school_names_async",
            new=AsyncMock(return_value=["北京大学"]),
        ) as school_normalize_mock,
        patch(
            "app.tools.score_query_tool.get_province_codes_async",
            new=AsyncMock(return_value=["110000"]),
        ),
        patch(
            "app.tools.score_query_tool.resolve_batch_codes",
            return_value=["01"],
        ),
        patch(
            "app.tools.score_query_tool.query_program_by_limit_num",
            new=AsyncMock(
                return_value={
                    "data": [
                        {
                            "volunteerLevel": "冲",
                            "records": [{"schoolUnitName": "北京大学", "schoolId": "10001"}],
                        }
                    ]
                }
            ),
        ),
        patch(
            "app.tools.score_query_tool.get_school_codes_async",
            new=AsyncMock(return_value=["10001"]),
        ) as school_code_mock,
    ):
        result = await query_admission_score(_ctx(), "北大", score=650, province="北京", subjects="物化生")

    school_normalize_mock.assert_awaited_once_with(["北大"])
    school_code_mock.assert_awaited_once_with(["北京大学"])
    assert "北京大学" in result


@pytest.mark.asyncio
async def test_validate_major_subjects_uses_normalized_major_names():
    with (
        patch(
            "app.tools.plan_validation_tool.resolve_major_names_async",
            new=AsyncMock(return_value=["计算机科学与技术"]),
        ) as normalize_mock,
        patch(
            "app.tools.plan_validation_tool.get_major_codes_async",
            new=AsyncMock(return_value=["574"]),
        ) as code_mock,
        patch(
            "app.tools.plan_validation_tool.check_major_subject_availability",
            new=AsyncMock(return_value={"data": True}),
        ),
    ):
        result = await validate_major_subjects(_ctx(), ["计科"])

    normalize_mock.assert_awaited_once_with(["计科"], "level3", "01")
    code_mock.assert_awaited_once_with(["计算机科学与技术"], "level3", "01")
    assert "计算机科学与技术" in result


@pytest.mark.asyncio
async def test_validate_plan_params_uses_normalized_major_and_school_names():
    with (
        patch(
            "app.tools.plan_validation_tool.resolve_major_names_async",
            new=AsyncMock(return_value=["计算机科学与技术"]),
        ) as major_normalize_mock,
        patch(
            "app.tools.plan_validation_tool.resolve_school_names_async",
            new=AsyncMock(return_value=["北京大学"]),
        ) as school_normalize_mock,
        patch(
            "app.tools.plan_validation_tool.get_major_codes_async",
            new=AsyncMock(return_value=["574"]),
        ),
        patch(
            "app.tools.plan_validation_tool.get_school_codes_async",
            new=AsyncMock(return_value=["10001"]),
        ) as school_code_mock,
        patch(
            "app.tools.plan_validation_tool.check_plan_param_availability",
            new=AsyncMock(return_value={"data": True}),
        ),
    ):
        result = await validate_plan_params(_ctx(), major_names=["计科"], school_names=["北大"])

    major_normalize_mock.assert_awaited_once_with(["计科"], "level3", "01")
    school_normalize_mock.assert_awaited_once_with(["北大"])
    school_code_mock.assert_awaited_once_with(["北京大学"])
    assert "计算机科学与技术" in result
    assert "北京大学" in result
