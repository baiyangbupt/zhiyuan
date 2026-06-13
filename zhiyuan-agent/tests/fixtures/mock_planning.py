"""Mock planning fixture — patch app.tools.planning_workflow_tool 函数。

使用示例：
    from tests.fixtures.mock_planning import patch_planning

    def test_xxx(patch_planning):
        patch_planning.query_planning_state.return_value = "当前方案状态..."
        ...
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

_WORKFLOW_MODULE = "app.tools.planning_workflow_tool"
_EXECUTION_TOOL_MODULE = "app.tools.plan_execution_tool"
_MUTATION_HANDLER_MODULE = "app.handlers.mutation_handlers"
_QUERY_HANDLER_MODULE = "app.handlers.query_handlers"

# 高层 workflow 函数（被 plan_execution_tool 调用）
_WORKFLOW_FUNCTIONS = [
    "query_planning_state",
    "query_planning_plan_overview",
    "query_planning_draft",
    "query_planning_candidate_pool",
    "query_planning_ordered_plan",
    "select_planning_draft_items",
    "select_planning_ordered_items",
    "remove_planning_draft_items",
    "remove_planning_ordered_items",
    "lock_planning_draft_items",
    "ban_planning_draft_items",
    "generate_planning_ordered_plan",
    "generate_planning_initial_plan",
    "move_planning_ordered_item",
    "run_planning_review",
    "analyze_planning_plan_adjustment",
]

_EXECUTION_TOOL_ALIASES = {
    "query_planning_plan_overview",
    "query_planning_draft",
    "query_planning_candidate_pool",
    "query_planning_ordered_plan",
    "select_planning_ordered_items",
    "remove_planning_ordered_items",
    "move_planning_ordered_item",
    "run_planning_review",
    "analyze_planning_plan_adjustment",
}

_MUTATION_HANDLER_ALIASES = {
    "move_planning_ordered_item",
    "remove_planning_ordered_items",
    "select_planning_ordered_items",
}

_QUERY_HANDLER_ALIASES = {
    "query_planning_candidate_pool",
    "query_planning_draft",
    "query_planning_ordered_plan",
}

# 只读 facts-builder 函数（同步）
_FACTS_FUNCTIONS = [
    "_build_plan_status_overview_facts",
    "_build_review_result_facts",
    "_build_compensation_preview_facts",
    "_build_plan_adjustment_facts",
    "_build_plan_intent_relation_lines",
]


class PlanningMocks:
    """容器，按属性名访问各 workflow 函数的 AsyncMock / Mock。"""

    def __init__(self, mocks: dict[str, Any]) -> None:
        self._mocks = mocks

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            return super().__getattribute__(name)
        if name in self._mocks:
            return self._mocks[name]
        raise AttributeError(f"PlanningMocks has no mock for '{name}'")

    def reset(self) -> None:
        for mock in self._mocks.values():
            mock.reset_mock()


@pytest.fixture
def patch_planning():
    """Fixture: patch planning_workflow_tool 的高层函数。"""
    mocks: dict[str, Any] = {}
    patchers = []

    for name in _WORKFLOW_FUNCTIONS:
        mock = AsyncMock(return_value="")
        patcher = patch(f"{_WORKFLOW_MODULE}.{name}", mock)
        patchers.append(patcher)
        mocks[name] = mock
        if name in _EXECUTION_TOOL_ALIASES:
            patchers.append(patch(f"{_EXECUTION_TOOL_MODULE}.{name}", mock))
        if name in _MUTATION_HANDLER_ALIASES:
            patchers.append(patch(f"{_MUTATION_HANDLER_MODULE}.{name}", mock))
        if name in _QUERY_HANDLER_ALIASES:
            patchers.append(patch(f"{_QUERY_HANDLER_MODULE}.{name}", mock))

    for p in patchers:
        p.start()

    container = PlanningMocks(mocks)
    yield container

    for p in patchers:
        p.stop()
