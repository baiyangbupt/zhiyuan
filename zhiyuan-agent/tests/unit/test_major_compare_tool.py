from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.tools.major_compare_tool import compare_majors


def test_compare_majors_does_not_summarize_empty_weight_data():
    ctx = SimpleNamespace(deps=SimpleNamespace(batch="01", sessionid="session-no-score"))

    with (
        patch(
            "app.tools.major_compare_tool.query_volunteer_analysis_weight",
            new=AsyncMock(return_value={"code": 404, "data": None, "msg": "用户分数信息不存在"}),
        ),
        patch(
            "app.tools.major_compare_tool._summarize_comparison",
            new=AsyncMock(return_value="should not be used"),
        ) as summarize_mock,
    ):
        result = asyncio.run(compare_majors(ctx, "法学", "财政学"))

    assert "暂时没有拿到当前会话可用的个性化量化权重数据" in result
    assert "综合得分相同" not in result
    summarize_mock.assert_not_awaited()
