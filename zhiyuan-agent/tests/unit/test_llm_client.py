"""LLMClient 单元测试 — 6 个用例。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.config import LLMConfig
from app.llm.client import LLMClient


def test_llm_config_defaults_connect_timeout_to_fifteen_seconds():
    config = LLMConfig(provider="openai", api_key="sk-test")

    assert config.connect_timeout_seconds == 15.0


@pytest.mark.parametrize("value", [0, -1])
def test_llm_config_rejects_non_positive_connect_timeout(value):
    with pytest.raises(ValueError, match="LLM_CONNECT_TIMEOUT_SECONDS"):
        LLMConfig(
            provider="openai",
            api_key="sk-test",
            connect_timeout_seconds=value,
        )


# ---- 1. openai provider ----

def test_create_openai_model(mocker):
    mock_provider = mocker.patch(
        "app.llm.client.OpenAIProvider", return_value=MagicMock()
    )
    mock_model = mocker.patch(
        "app.llm.client.OpenAIChatModel", return_value=MagicMock()
    )
    config = LLMConfig(provider="openai", model_name="gpt-4o", api_key="sk-test")
    client = LLMClient(config)

    mock_provider.assert_called_once_with(api_key="sk-test")
    mock_model.assert_called_once_with("gpt-4o", provider=mock_provider.return_value)
    assert client.model is mock_model.return_value


def test_create_openai_model_sets_configured_connect_timeout(mocker):
    mock_provider = mocker.patch(
        "app.llm.client.OpenAIProvider", return_value=MagicMock()
    )
    mocker.patch("app.llm.client.OpenAIChatModel", return_value=MagicMock())
    config = LLMConfig(
        provider="openai",
        model_name="gpt-4o",
        api_key="sk-test",
        connect_timeout_seconds=23,
    )

    LLMClient(config)

    assert mock_provider.return_value.client.timeout.connect == 23


# ---- 2. anthropic provider ----

def test_create_anthropic_model(mocker):
    mock_provider = mocker.patch(
        "app.llm.client.AnthropicProvider", return_value=MagicMock()
    )
    mock_model = mocker.patch(
        "app.llm.client.AnthropicModel", return_value=MagicMock()
    )
    config = LLMConfig(provider="anthropic", model_name="claude-sonnet-4-5", api_key="sk-ant")
    client = LLMClient(config)

    # base_url 为空时，只传 api_key
    mock_provider.assert_called_once_with(api_key="sk-ant")
    mock_model.assert_called_once_with(
        "claude-sonnet-4-5", provider=mock_provider.return_value
    )
    assert client.model is mock_model.return_value


# ---- 2b. anthropic provider + base_url ----

def test_create_anthropic_model_with_base_url(mocker):
    mock_provider = mocker.patch(
        "app.llm.client.AnthropicProvider", return_value=MagicMock()
    )
    mock_model = mocker.patch(
        "app.llm.client.AnthropicModel", return_value=MagicMock()
    )
    config = LLMConfig(
        provider="anthropic", model_name="claude-opus-4-6",
        api_key="sk-ant", base_url="https://proxy.example.com",
    )
    client = LLMClient(config)

    mock_provider.assert_called_once_with(
        api_key="sk-ant", base_url="https://proxy.example.com"
    )
    assert client.model is mock_model.return_value


# ---- 3. openai_compatible provider ----

def test_create_openai_compatible_model(mocker):
    mock_provider = mocker.patch(
        "app.llm.client.OpenAIProvider", return_value=MagicMock()
    )
    mock_model = mocker.patch(
        "app.llm.client.OpenAIChatModel", return_value=MagicMock()
    )
    config = LLMConfig(
        provider="openai_compatible",
        model_name="local-model",
        api_key="sk-test",
        base_url="http://localhost:8000/v1",
    )
    client = LLMClient(config)

    mock_provider.assert_called_once_with(
        base_url="http://localhost:8000/v1", api_key="sk-test"
    )
    mock_model.assert_called_once_with(
        "local-model", provider=mock_provider.return_value
    )
    assert client.model is mock_model.return_value


def test_create_openai_compatible_model_sets_configured_connect_timeout(mocker):
    mock_provider = mocker.patch(
        "app.llm.client.OpenAIProvider", return_value=MagicMock()
    )
    mocker.patch("app.llm.client.OpenAIChatModel", return_value=MagicMock())
    config = LLMConfig(
        provider="openai_compatible",
        model_name="local-model",
        api_key="sk-test",
        base_url="http://localhost:8000/v1",
        connect_timeout_seconds=19,
    )

    LLMClient(config)

    assert mock_provider.return_value.client.timeout.connect == 19


# ---- 4. model_settings 传递 ----

def test_model_settings_passed(mocker):
    mocker.patch("app.llm.client.OpenAIChatModel", return_value=MagicMock())
    mocker.patch("app.llm.client.OpenAIProvider", return_value=MagicMock())

    config = LLMConfig(
        provider="openai",
        api_key="sk-test",
        temperature=0.3,
        max_tokens=2048,
        timeout_seconds=30,
    )
    client = LLMClient(config)

    assert client.model_settings["temperature"] == 0.3
    assert client.model_settings["max_tokens"] == 2048
    assert client.model_settings["timeout"] == 30


def test_model_settings_do_not_set_timeout_by_default(mocker):
    mocker.patch("app.llm.client.OpenAIChatModel", return_value=MagicMock())
    mocker.patch("app.llm.client.OpenAIProvider", return_value=MagicMock())

    config = LLMConfig(provider="openai", api_key="sk-test")
    client = LLMClient(config)

    assert "timeout" not in client.model_settings


# ---- 5. config=None 自动构造 ----

def test_config_none_auto_construct(monkeypatch, mocker):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "sk-auto")
    monkeypatch.setenv("LLM_MODEL_NAME", "gpt-4o")
    mocker.patch("app.llm.client.OpenAIChatModel", return_value=MagicMock())
    mocker.patch("app.llm.client.OpenAIProvider", return_value=MagicMock())

    client = LLMClient(config=None)
    assert client.config.api_key == "sk-auto"


# ---- 6. 不支持的 provider ----

def test_unsupported_provider(mocker):
    config = LLMConfig(provider="openai", api_key="sk-test")
    # 绕过 Literal 校验，直接修改底层属性
    object.__setattr__(config, "provider", "unknown")

    mocker.patch("app.llm.client.OpenAIProvider")
    mocker.patch("app.llm.client.OpenAIChatModel")

    with pytest.raises(ValueError, match="Unsupported provider"):
        LLMClient(config)
