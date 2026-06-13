"""Mock backend fixture — patch app.util.internal_client 端点。

使用示例：
    from tests.fixtures.mock_backend import patch_backend

    def test_xxx(patch_backend):
        patch_backend.get_planning_state.return_value = {"data": {...}}
        ...
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

_INTERNAL_CLIENT_MODULE = "app.util.internal_client"
_EXECUTION_TOOL_MODULE = "app.tools.plan_execution_tool"
_QUERY_HANDLER_MODULE = "app.handlers.query_handlers"
_ANALYSIS_HANDLER_MODULE = "app.handlers.analysis_handlers"
_FIX_PROPOSAL_HANDLER_MODULE = "app.handlers.fix_proposal_handlers"
_GENERATE_HANDLER_MODULE = "app.handlers.generate_handler"

# 需要 patch 的 planning 相关异步函数
_PLANNING_ENDPOINTS = [
    "get_planning_state",
    "get_planning_draft",
    "get_planning_ordered_plan",
    "run_planning_review",
    "generate_planning_ordered_plan",
    "generate_planning_initial_plan",
    "generate_planning_candidate_pool",
    "query_planning_candidate_pool",
    "select_planning_draft_items",
    "remove_planning_draft_items",
    "lock_planning_draft_items",
    "ban_planning_draft_items",
    "move_planning_ordered_item",
    "analyze_planning_plan_adjustment",
    "generate_planning_fix_proposals",
]

# 需要 patch 的 profile / 其他端点
_OTHER_ENDPOINTS = [
    "get_user_profile",
    "get_user_init_profile",
    "get_user_score_detail",
    "save_user_profile",
    "update_planning_latent_profile",
    "save_intent_change_cache",
    "get_intent_change_cache",
]

_ALL_ENDPOINTS = _PLANNING_ENDPOINTS + _OTHER_ENDPOINTS

# plan_execution_tool.py 通过 `from app.util.internal_client import X as _X_request`
# 创建了绑定引用，需要在该模块上也 patch，否则 mock 不生效。
_EXECUTION_TOOL_ALIASES: dict[str, str] = {
    "generate_planning_initial_plan": "_generate_planning_initial_plan_request",
    "generate_planning_ordered_plan": "_generate_planning_ordered_plan_request",
    "generate_planning_candidate_pool": "_generate_planning_candidate_pool_request",
    "get_planning_state": "_get_planning_state_request",
    "get_planning_draft": "_get_working_plan_request",
    "get_planning_ordered_plan": "_get_planning_ordered_plan_request",
    "get_user_profile": "_get_user_profile_request",
    "run_planning_review": "_run_planning_review_request",
    "analyze_planning_plan_adjustment": "_analyze_planning_plan_adjustment_request",
    "query_planning_candidate_pool": "_query_planning_candidate_pool_request",
    "select_planning_draft_items": "_select_working_plan_items_request",
}

# handler 模块通过 `from app.util.internal_client import X as _X_request` 导入，
# 需要在 handler 模块上也 patch 绑定引用。
_QUERY_HANDLER_ALIASES: dict[str, str] = {
    "get_planning_state": "_get_planning_state_request",
    "get_planning_draft": "_get_working_plan_request",
    "get_planning_ordered_plan": "_get_planning_ordered_plan_request",
    "get_user_profile": "_get_user_profile_request",
}

_ANALYSIS_HANDLER_ALIASES: dict[str, str] = {
    "get_planning_ordered_plan": "_get_planning_ordered_plan_request",
    "get_planning_draft": "_get_working_plan_request",
    "run_planning_review": "_run_planning_review_request",
    "analyze_planning_plan_adjustment": "_analyze_planning_plan_adjustment_request",
    "generate_planning_fix_proposals": "_generate_planning_fix_proposals_request",
}

_FIX_PROPOSAL_HANDLER_ALIASES: dict[str, str] = {
    "generate_planning_fix_proposals": "_generate_planning_fix_proposals_request",
}

_GENERATE_HANDLER_ALIASES: dict[str, str] = {
    "generate_planning_candidate_pool": "_generate_planning_candidate_pool_request",
    "generate_planning_initial_plan": "_generate_planning_initial_plan_request",
    "run_planning_review": "_run_planning_review_request",
}


class BackendMocks:
    """容器，按属性名访问各 endpoint 的 AsyncMock。"""

    def __init__(self, mocks: dict[str, AsyncMock]) -> None:
        self._mocks = mocks

    def __getattr__(self, name: str) -> AsyncMock:
        if name.startswith("_"):
            return super().__getattribute__(name)  # type: ignore[return-value]
        if name in self._mocks:
            return self._mocks[name]
        raise AttributeError(f"BackendMocks has no mock for endpoint '{name}'")

    def reset(self) -> None:
        for mock in self._mocks.values():
            mock.reset_mock()

    def set_default_planning_state(self, data: dict[str, Any]) -> None:
        self._mocks["get_planning_state"].return_value = {"code": 0, "data": data}

    def set_default_profile(self, data: dict[str, Any]) -> None:
        self._mocks["get_user_profile"].return_value = {"code": 0, "data": data}

    def set_default_ordered_plan(self, data: dict[str, Any]) -> None:
        self._mocks["get_planning_ordered_plan"].return_value = {"code": 0, "data": data}

    def set_default_draft(self, data: dict[str, Any]) -> None:
        self._mocks["get_planning_draft"].return_value = {"code": 0, "data": data}


def _make_default_return(endpoint: str) -> dict[str, Any]:
    """为每个 endpoint 提供合理默认返回值。"""
    return {"code": 0, "data": {}, "success": True}


@pytest.fixture
def patch_backend():
    """Fixture: patch 所有 internal_client 端点，返回 BackendMocks 容器。

    同时 patch plan_execution_tool 中通过 ``from ... import X as _X_request``
    创建的绑定引用，确保 mock 对两处调用都生效。
    """
    mocks: dict[str, AsyncMock] = {}
    patchers = []

    for name in _ALL_ENDPOINTS:
        mock = AsyncMock(return_value=_make_default_return(name))
        patcher = patch(f"{_INTERNAL_CLIENT_MODULE}.{name}", mock)
        patchers.append(patcher)
        mocks[name] = mock

        # 同步 patch plan_execution_tool 里的别名引用
        if name in _EXECUTION_TOOL_ALIASES:
            alias = _EXECUTION_TOOL_ALIASES[name]
            alias_patcher = patch(f"{_EXECUTION_TOOL_MODULE}.{alias}", mock)
            patchers.append(alias_patcher)

        # 同步 patch handler 模块里的别名引用
        if name in _QUERY_HANDLER_ALIASES:
            alias = _QUERY_HANDLER_ALIASES[name]
            patchers.append(patch(f"{_QUERY_HANDLER_MODULE}.{alias}", mock))

        if name in _ANALYSIS_HANDLER_ALIASES:
            alias = _ANALYSIS_HANDLER_ALIASES[name]
            patchers.append(patch(f"{_ANALYSIS_HANDLER_MODULE}.{alias}", mock))

        if name in _FIX_PROPOSAL_HANDLER_ALIASES:
            alias = _FIX_PROPOSAL_HANDLER_ALIASES[name]
            patchers.append(patch(f"{_FIX_PROPOSAL_HANDLER_MODULE}.{alias}", mock))

        if name in _GENERATE_HANDLER_ALIASES:
            alias = _GENERATE_HANDLER_ALIASES[name]
            patchers.append(patch(f"{_GENERATE_HANDLER_MODULE}.{alias}", mock))

    for p in patchers:
        p.start()

    container = BackendMocks(mocks)
    yield container

    for p in patchers:
        p.stop()
