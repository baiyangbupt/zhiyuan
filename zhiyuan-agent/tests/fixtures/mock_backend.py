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

# 需要 patch 的 planning 相关异步函数
_PLANNING_ENDPOINTS = [
    "get_planning_state",
    "get_working_plan",
    "get_planning_ordered_plan",
    "run_planning_review",
    "generate_planning_ordered_plan",
    "generate_planning_initial_plan",
    "generate_planning_candidate_pool",
    "query_planning_candidate_pool",
    "select_working_plan_items",
    "remove_working_plan_items",
    "ban_working_plan_items",
    "move_planning_ordered_item",
    "generate_planning_fix_proposals",
]

# 需要 patch 的 profile / 其他端点
_OTHER_ENDPOINTS = [
    "get_user_profile",
    "get_user_init_profile",
    "get_user_score_detail",
    "save_user_profile",
    "update_planning_latent_profile",
]

_ALL_ENDPOINTS = _PLANNING_ENDPOINTS + _OTHER_ENDPOINTS

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

    def set_default_working_plan(self, data: dict[str, Any]) -> None:
        self._mocks["get_working_plan"].return_value = {"code": 0, "data": data}


def _make_default_return(endpoint: str) -> dict[str, Any]:
    """为每个 endpoint 提供合理默认返回值。"""
    return {"code": 0, "data": {}, "success": True}


@pytest.fixture
def patch_backend():
    """Fixture: patch 所有 internal_client 端点，返回 BackendMocks 容器。

    4.0 direct 路径不再维护旧 plan action execution/handler 别名 patch。
    """
    mocks: dict[str, AsyncMock] = {}
    patchers = []

    for name in _ALL_ENDPOINTS:
        mock = AsyncMock(return_value=_make_default_return(name))
        patcher = patch(f"{_INTERNAL_CLIENT_MODULE}.{name}", mock)
        patchers.append(patcher)
        mocks[name] = mock

    for p in patchers:
        p.start()

    container = BackendMocks(mocks)
    yield container

    for p in patchers:
        p.stop()
