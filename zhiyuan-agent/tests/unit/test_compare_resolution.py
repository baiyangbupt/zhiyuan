from unittest.mock import AsyncMock, patch

import pytest

from app.tools.major_compare_tool import _resolve_major_name
from app.tools.school_compare_tool import _resolve_school_name


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
