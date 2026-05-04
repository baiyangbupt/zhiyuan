from unittest.mock import AsyncMock, patch

import pytest

from app.data.student_info_mappings import build_studentinfo, build_studentinfo_async
from app.util.batch_subject_mapping import resolve_subject_type


def test_build_studentinfo_sync_basic():
    result = build_studentinfo(
        province="河北",
        total_score=600,
        subjects=["物理", "化学", "生物"],
        sex="男",
        strength_subjects=["数学", "物理"],
    )

    assert result["province"]["code"] == "130000"
    assert result["subjectType"]["code"] == "WL"
    assert result["subjectList"][0]["isFirst"] == 1
    assert result["strengthSubjectList"][0]["subject"] == "10"


def test_build_studentinfo_sync_reuses_province_aware_subject_type_resolution():
    result = build_studentinfo(
        province="上海",
        total_score=580,
        subjects=["物理", "化学", "生物"],
        sex="男",
        strength_subjects=["数学", "物理"],
    )

    assert result["subjectType"]["code"] == resolve_subject_type("310000", ["物理", "化学", "生物"])


@pytest.mark.asyncio
async def test_build_studentinfo_async_uses_catalog_compatible_code_lookup():
    with patch(
        "app.data.student_info_mappings.get_province_codes_async",
        new=AsyncMock(return_value=["110000"]),
    ) as province_mock:
        result = await build_studentinfo_async(
            province="北京",
            total_score=620,
            subjects=["历史", "政治", "地理"],
            sex="女",
            strength_subjects=["语文", "历史"],
        )

    province_mock.assert_awaited_once_with(["北京"])
    assert result["province"]["code"] == "110000"
    assert result["province"]["name"] == "北京"
    assert result["subjectType"]["code"] == resolve_subject_type("110000", ["历史", "政治", "地理"])
    assert result["sex"]["code"] == "female"


def test_studentinfo_subject_list_codes_are_not_gaotu_query_subject_codes():
    result = build_studentinfo(
        province="河北",
        total_score=600,
        subjects=["物理", "化学", "生物"],
        sex="男",
        strength_subjects=["数学", "物理"],
    )

    assert [item["value"] for item in result["subjectList"]] == ["01", "02", "03"]


@pytest.mark.asyncio
async def test_build_studentinfo_async_raises_when_province_unknown():
    with patch(
        "app.data.student_info_mappings.get_province_codes_async",
        new=AsyncMock(return_value=[]),
    ):
        with pytest.raises(ValueError):
            await build_studentinfo_async(
                province="火星",
                total_score=500,
                subjects=["物理"],
                sex="男",
                strength_subjects=["数学"],
            )
