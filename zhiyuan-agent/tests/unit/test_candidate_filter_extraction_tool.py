from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.candidate_filter import CandidateFilterExtractionResult
from app.tools.candidate_filter_extraction_tool import (
    extract_candidate_query_filters_async,
    normalize_candidate_query_filters_async,
)

FILTER_TAG_TREE = {
    "data": {
        "school": {
            "category": ["师范", "财经", "医药"],
            "nature": ["公办", "民办"],
            "feature": ["省会城市"],
            "level": ["本科", "双一流"],
        },
        "major": {
            "discipline": ["工学", "教育学"],
            "category": [
                {
                    "categoryName": "工学",
                    "children": [{"subCategoryName": "计算机类"}],
                },
                {
                    "categoryName": "教育学",
                    "children": [{"subCategoryName": "教育学类"}],
                },
            ],
        },
        "admission": {"type": ["普通类", "师范专业"]},
        "constraint": {"limit": ["色盲色弱"]},
    }
}


@pytest.mark.asyncio
async def test_extract_candidate_query_filters_uses_llm_schema_and_normalizes_result():
    mock_result = MagicMock()
    mock_result.output = CandidateFilterExtractionResult(
        shouldQueryCandidate=True,
        tiers=["稳"],
        schoolTags=["师范"],
        majorKeywords=["地理科学"],
        confidence=0.91,
    ).model_dump_json()
    mock_agent_instance = MagicMock()
    mock_agent_instance.run = AsyncMock(return_value=mock_result)

    with patch(
        "app.tools.candidate_filter_extraction_tool.Agent",
        return_value=mock_agent_instance,
    ) as mock_agent_cls, patch(
        "app.tools.candidate_filter_extraction_tool._get_extraction_client",
    ) as mock_client, patch(
        "app.tools.candidate_filter_extraction_tool.normalize_candidate_query_filters_async",
        new=AsyncMock(
            return_value={
                "tiers": ["稳"],
                "province_names": [],
                "city_names": [],
                "school_keywords": [],
                "major_keywords": ["地理科学"],
                "school_tags": ["师范"],
                "major_tags": [],
            }
        ),
    ) as mock_normalize:
        mock_client.return_value.model = MagicMock()

        result = await extract_candidate_query_filters_async(
            "候选里有没有更稳一点的师范类机会，先查一下别加",
            batch="01",
        )

    mock_agent_cls.assert_called_once()
    assert mock_agent_cls.call_args.kwargs["output_type"] is str
    mock_agent_instance.run.assert_awaited_once()
    mock_normalize.assert_awaited_once()
    assert result["should_query_candidate"] is True
    assert result["confidence"] == 0.91
    assert result["filters"]["tiers"] == ["稳"]
    assert result["filters"]["school_tags"] == ["师范"]
    assert result["filters"]["major_keywords"] == ["地理科学"]


@pytest.mark.asyncio
async def test_normalize_candidate_query_filters_keeps_candidate_pool_field_semantics():
    with patch(
        "app.tools.candidate_filter_extraction_tool._normalize_province_names_async",
        new=AsyncMock(return_value=["北京"]),
    ), patch(
        "app.tools.candidate_filter_extraction_tool._normalize_city_names_async",
        new=AsyncMock(return_value=[]),
    ), patch(
        "app.tools.candidate_filter_extraction_tool._normalize_school_names_async",
        new=AsyncMock(return_value=[]),
    ), patch(
        "app.tools.candidate_filter_extraction_tool._get_filter_tag_tree",
        new=AsyncMock(return_value=FILTER_TAG_TREE),
    ), patch(
        "app.tools.candidate_filter_extraction_tool.resolve_major_names_async",
        new=AsyncMock(side_effect=[["计算机类"], ["计算机科学与技术"], ["工学"]]),
    ):
        result = await normalize_candidate_query_filters_async(
            {
                "tiers": ["稳", "未知"],
                "province_names": ["北京"],
                "major_keywords": ["计科"],
                "school_tags": ["师范"],
                "major_tags": ["工学"],
            },
            batch="01",
        )

    assert result["tiers"] == ["稳"]
    assert result["province_names"] == ["北京"]
    assert result["major_keywords"] == ["计算机科学与技术"]
    assert result["school_tags"] == ["师范"]
    assert result["major_tags"] == ["工学"]


@pytest.mark.asyncio
async def test_normalize_candidate_query_filters_trims_catalog_tag_suffixes():
    with patch(
        "app.tools.candidate_filter_extraction_tool._normalize_province_names_async",
        new=AsyncMock(return_value=[]),
    ), patch(
        "app.tools.candidate_filter_extraction_tool._normalize_city_names_async",
        new=AsyncMock(return_value=[]),
    ), patch(
        "app.tools.candidate_filter_extraction_tool._normalize_school_names_async",
        new=AsyncMock(return_value=[]),
    ), patch(
        "app.tools.candidate_filter_extraction_tool._get_filter_tag_tree",
        new=AsyncMock(return_value=FILTER_TAG_TREE),
    ), patch(
        "app.tools.candidate_filter_extraction_tool.resolve_major_names_async",
        new=AsyncMock(side_effect=[[], [], ["师范类"]]),
    ):
        result = await normalize_candidate_query_filters_async(
            {
                "tiers": ["稳"],
                "school_tags": ["师范类"],
                "major_tags": ["师范类"],
            },
            batch="01",
        )

    assert result["tiers"] == ["稳"]
    assert result["school_tags"] == ["师范"]
    assert result["major_tags"] == []


@pytest.mark.asyncio
async def test_normalize_candidate_query_filters_keeps_valid_major_enum_tags():
    with patch(
        "app.tools.candidate_filter_extraction_tool._normalize_province_names_async",
        new=AsyncMock(return_value=[]),
    ), patch(
        "app.tools.candidate_filter_extraction_tool._normalize_city_names_async",
        new=AsyncMock(return_value=[]),
    ), patch(
        "app.tools.candidate_filter_extraction_tool._normalize_school_names_async",
        new=AsyncMock(return_value=[]),
    ), patch(
        "app.tools.candidate_filter_extraction_tool._get_filter_tag_tree",
        new=AsyncMock(return_value=FILTER_TAG_TREE),
    ), patch(
        "app.tools.candidate_filter_extraction_tool.resolve_major_names_async",
        new=AsyncMock(side_effect=[[], [], ["工学", "师范专业"]]),
    ):
        result = await normalize_candidate_query_filters_async(
            {
                "major_tags": ["工学", "师范专业"],
            },
            batch="01",
        )

    assert result["major_tags"] == ["工学", "师范专业"]
