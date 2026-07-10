"""全局 fixture。"""

from __future__ import annotations

import asyncio
import inspect
import os
from unittest.mock import MagicMock

import pytest

from app.config import LLMConfig

# 引入共享 fixtures，使其对所有测试可见
from tests.fixtures.mock_backend import patch_backend  # noqa: F401


_LLM_ENV_KEYS = [
    "LLM_PROVIDER", "LLM_MODEL_NAME", "LLM_API_KEY",
    "LLM_BASE_URL", "LLM_TEMPERATURE", "LLM_MAX_TOKENS",
]


@pytest.fixture(autouse=True)
def _clean_llm_env(request, monkeypatch):
    """清除 LLM_ 环境变量 + 屏蔽 .env 文件读取，防止污染单元测试。

    e2e 测试（标记 @pytest.mark.e2e）跳过此 fixture。
    """
    if "e2e" in [mark.name for mark in request.node.iter_markers()]:
        return
    for key in _LLM_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        "app.config.LLMConfig.model_config",
        {**LLMConfig.model_config, "env_file": None},
    )


@pytest.fixture
def mock_llm_config():
    """直接传参构造 LLMConfig，绕过 .env 文件。"""
    return LLMConfig(
        provider="openai",
        model_name="gpt-4o",
        api_key="sk-test-key",
        base_url="",
        temperature=0.7,
        max_tokens=4096,
    )


@pytest.fixture
def mock_llm_client(mock_llm_config, mocker):
    """Mock 掉真实 Model 创建，返回可用的 LLMClient。"""
    mocker.patch("app.llm.client.OpenAIChatModel", return_value=MagicMock())
    mocker.patch("app.llm.client.OpenAIProvider", return_value=MagicMock())

    from app.llm.client import LLMClient

    return LLMClient(mock_llm_config)


def pytest_configure(config):
    config.addinivalue_line("markers", "asyncio: mark test as asyncio-compatible")
    config.addinivalue_line("markers", "regression: regression baseline tests")


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    """在本地未安装 pytest-asyncio 时，兼容执行 async 测试。"""
    test_func = pyfuncitem.obj
    if not inspect.iscoroutinefunction(test_func):
        return None

    funcargs = {
        name: pyfuncitem.funcargs[name]
        for name in pyfuncitem._fixtureinfo.argnames
    }
    asyncio.run(test_func(**funcargs))
    return True
