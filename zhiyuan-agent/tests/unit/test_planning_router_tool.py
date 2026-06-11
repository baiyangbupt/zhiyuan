from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.context import RequestContext
from app.tools.planning_router_tool import handle_planning_request


def _ctx(session_id: str = "123") -> SimpleNamespace:
    return SimpleNamespace(deps=RequestContext(userid="u1", sessionid=session_id))


@pytest.mark.asyncio
async def test_handle_planning_request_routes_state_query():
    with patch(
        "app.tools.planning_router_tool._run_planned_request",
        new=AsyncMock(return_value="state ok"),
    ) as mock_query:
        result = await handle_planning_request(_ctx(), request_type="state")

    assert result == "state ok"
    mock_query.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_planning_request_returns_text_for_candidate_query():
    with patch(
        "app.tools.planning_router_tool._run_planned_request",
        new=AsyncMock(return_value="这是当前候选池查询结果。\n- 候选示例：A大学-计算机(稳/北京/录取率70%)"),
    ) as mock_run:
        result = await handle_planning_request(
            _ctx(),
            request_type="candidate_query",
            tier="稳",
            province_keyword="北京",
            school_tags=["公办", "未知"],
        )

    assert "北京" in result
    mock_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_planning_request_routes_candidate_select_by_ids():
    with patch(
        "app.tools.planning_router_tool._run_planned_request",
        new=AsyncMock(return_value="preview add ok"),
    ) as mock_select:
        result = await handle_planning_request(
            _ctx(),
            request_type="candidate_select",
            volunteer_ids=["v1", "v2"],
        )

    assert result == "preview add ok"
    mock_select.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_planning_request_routes_candidate_select_by_ids_after_confirmation():
    with patch(
        "app.tools.planning_router_tool._run_planned_request",
        new=AsyncMock(return_value="ordered add ok"),
    ) as mock_select:
        result = await handle_planning_request(
            _ctx(),
            request_type="candidate_select",
            volunteer_ids=["v1", "v2"],
            user_confirmed=True,
        )

    assert result == "ordered add ok"
    mock_select.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_planning_request_routes_candidate_select_by_filters():
    with patch(
        "app.tools.planning_router_tool._run_planned_request",
        new=AsyncMock(return_value="preview ok"),
    ) as mock_select:
        result = await handle_planning_request(
            _ctx(),
            request_type="candidate_select",
            tier="稳",
            province_keyword="北京",
            limit=3,
        )

    assert result == "preview ok"
    mock_select.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_planning_request_routes_candidate_select_by_filters_after_confirmation():
    with patch(
        "app.tools.planning_router_tool._run_planned_request",
        new=AsyncMock(return_value="apply ok"),
    ) as mock_select:
        result = await handle_planning_request(
            _ctx(),
            request_type="candidate_select",
            tier="稳",
            province_keyword="北京",
            limit=3,
            user_confirmed=True,
        )

    assert result == "apply ok"
    mock_select.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_planning_request_candidate_select_requires_ids_or_structured_filters():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=SimpleNamespace(
                summary="阶段=ordered；方案=20/30",
                draft_count=20,
                ordered_count=30,
                relation_lines=[],
                review_issues=[],
            )
        ),
    ):
        result = await handle_planning_request(_ctx(), request_type="candidate_select")

    assert "补入志愿需要先明确要加入哪些候选" in result


@pytest.mark.asyncio
async def test_handle_planning_request_returns_text_for_draft_query():
    with patch(
        "app.tools.planning_router_tool._run_planned_request",
        new=AsyncMock(return_value="这是当前草稿方案摘要。"),
    ) as mock_query:
        result = await handle_planning_request(_ctx(), request_type="draft_query")

    assert result == "这是当前草稿方案摘要。"
    mock_query.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_planning_request_returns_text_for_review():
    with patch(
        "app.tools.planning_router_tool._run_planned_request",
        new=AsyncMock(return_value="已完成当前方案审查。"),
    ) as mock_review:
        result = await handle_planning_request(_ctx(), request_type="review")

    assert result == "已完成当前方案审查。"
    mock_review.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_planning_request_requires_confirmation_for_regenerate():
    with patch(
        "app.tools.planning_router_tool.query_planning_plan_overview",
        new=AsyncMock(return_value="这是当前方案的完整状态概览。"),
    ), patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=SimpleNamespace(
                summary="阶段=ordered；方案=30/30",
                draft_count=30,
                ordered_count=30,
                relation_lines=[],
            )
        ),
    ):
        result = await handle_planning_request(_ctx(), request_type="ordered_regenerate")
    assert "计划动作：整体重排当前方案" in result
    assert "当前方案概况：" in result


@pytest.mark.asyncio
async def test_handle_planning_request_routes_regenerate_after_confirmation():
    with patch(
        "app.tools.planning_router_tool._run_planned_request",
        new=AsyncMock(return_value="ordered ok"),
    ) as mock_regenerate:
        result = await handle_planning_request(
            _ctx(),
            request_type="ordered_regenerate",
            user_confirmed=True,
        )

    assert result == "ordered ok"
    mock_regenerate.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_planning_request_routes_ordered_remove_to_ordered_workflow():
    with patch(
        "app.tools.planning_router_tool._run_planned_request",
        new=AsyncMock(return_value="这一步我先不给你直接改方案，先把影响看清楚。"),
    ) as mock_run:
        result = await handle_planning_request(
            _ctx(),
            request_type="ordered_remove",
            volunteer_ids=["v1"],
        )

    assert "先不给你直接改方案" in result
    mock_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_planning_request_routes_ordered_remove_after_confirmation():
    with patch(
        "app.tools.planning_router_tool._run_planned_request",
        new=AsyncMock(return_value="ordered remove ok"),
    ) as mock_remove:
        result = await handle_planning_request(
            _ctx(),
            request_type="ordered_remove",
            volunteer_ids=["v1"],
            user_confirmed=True,
        )

    assert result == "ordered remove ok"
    mock_remove.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_planning_request_routes_initial_plan_generate():
    with patch(
        "app.tools.planning_router_tool.generate_planning_initial_plan",
        new=AsyncMock(return_value="已按当前条件生成一版方案。"),
    ) as mock_generate:
        result = await handle_planning_request(
            _ctx(),
            request_type="initial_plan_generate",
        )

    assert result == "已按当前条件生成一版方案。"
    mock_generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_planning_request_routes_review_and_preview():
    with patch(
        "app.tools.planning_router_tool._run_planned_request",
        new=AsyncMock(side_effect=["review ok", "preview ok"]),
    ) as mock_run:
        review_result = await handle_planning_request(_ctx(), request_type="review")
        preview_result = await handle_planning_request(_ctx(), request_type="compensation_preview")

    assert review_result == "review ok"
    assert preview_result == "preview ok"
    assert mock_run.await_count == 2


@pytest.mark.asyncio
async def test_handle_planning_request_routes_plan_adjustment_analyze():
    with patch(
        "app.tools.planning_router_tool._run_planned_request",
        new=AsyncMock(return_value="adjust ok"),
    ) as mock_adjust:
        result = await handle_planning_request(_ctx(), request_type="plan_adjustment_analyze")

    assert result == "adjust ok"
    mock_adjust.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_planning_request_routes_compensation_apply():
    with patch(
        "app.tools.planning_router_tool._run_planned_request",
        new=AsyncMock(return_value="apply ok"),
    ) as mock_apply:
        result = await handle_planning_request(
            _ctx(),
            request_type="compensation_apply",
            user_confirmed=True,
        )

    assert result == "apply ok"
    mock_apply.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_planning_request_routes_ordered_remove_via_plan_pipeline():
    with patch(
        "app.tools.planning_router_tool._run_planned_request",
        new=AsyncMock(return_value="preview remove ok"),
    ) as mock_run:
        result = await handle_planning_request(
            _ctx(),
            request_type="ordered_remove",
            volunteer_ids=["v1"],
        )

    assert result == "preview remove ok"
    mock_run.assert_awaited_once()
