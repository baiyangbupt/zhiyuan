from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.agent.context import RequestContext
from app.tools.planning_router_tool import handle_planning_request


def _ctx(session_id: str = "123") -> SimpleNamespace:
    return SimpleNamespace(deps=RequestContext(userid="u1", sessionid=session_id))


def test_handle_planning_request_candidate_select_by_ids_returns_workspace_action():
    with patch(
        "app.tools.planning_router_tool._run_planned_request",
        new=AsyncMock(return_value="preview add ok"),
    ) as mock_select:
        result = asyncio.run(
            handle_planning_request(
                _ctx(),
                request_type="candidate_select",
                volunteer_ids=["v1", "v2"],
            )
        )

    assert result == "preview add ok"
    mock_select.assert_awaited_once()
