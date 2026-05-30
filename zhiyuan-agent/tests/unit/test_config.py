"""LLMConfig 单元测试 — 10 个用例。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import HistoryConfig, LLMConfig


# ---- 1. 完整参数构造 ----

def test_full_params():
    cfg = LLMConfig(
        provider="anthropic",
        model_name="claude-sonnet-4-5",
        api_key="sk-ant-test",
        base_url="",
        temperature=0.5,
        max_tokens=2048,
    )
    assert cfg.provider == "anthropic"
    assert cfg.model_name == "claude-sonnet-4-5"
    assert cfg.api_key == "sk-ant-test"
    assert cfg.temperature == 0.5
    assert cfg.max_tokens == 2048
    assert cfg.timeout_seconds == 0.0


# ---- 2. 默认值 ----

def test_default_values():
    cfg = LLMConfig(api_key="sk-test")
    assert cfg.provider == "openai"
    assert cfg.model_name == "gpt-4o"
    assert cfg.temperature == 0.7
    assert cfg.max_tokens == 4096
    assert cfg.base_url == ""


# ---- 3. provider openai 正常 ----

def test_provider_openai():
    cfg = LLMConfig(provider="openai", api_key="sk-test")
    assert cfg.provider == "openai"


# ---- 4. provider anthropic 正常 ----

def test_provider_anthropic():
    cfg = LLMConfig(provider="anthropic", api_key="sk-test")
    assert cfg.provider == "anthropic"


# ---- 5. openai_compatible + base_url ----

def test_provider_openai_compatible_with_base_url():
    cfg = LLMConfig(
        provider="openai_compatible",
        api_key="sk-test",
        base_url="https://my-llm.example.com/v1",
    )
    assert cfg.provider == "openai_compatible"
    assert cfg.base_url == "https://my-llm.example.com/v1"


# ---- 6. openai_compatible 缺 base_url ----

def test_openai_compatible_missing_base_url():
    with pytest.raises(ValidationError, match="LLM_BASE_URL is required"):
        LLMConfig(provider="openai_compatible", api_key="sk-test", base_url="")


# ---- 7. 缺 api_key ----

def test_missing_api_key(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(ValidationError):
        LLMConfig(provider="openai")


# ---- 8. 非法 provider ----

def test_invalid_provider():
    with pytest.raises(ValidationError):
        LLMConfig(provider="invalid_xxx", api_key="sk-test")


# ---- 9. 环境变量加载 ----

def test_load_from_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_MODEL_NAME", "claude-sonnet-4-5")
    monkeypatch.setenv("LLM_API_KEY", "sk-env-test")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.3")
    monkeypatch.setenv("LLM_MAX_TOKENS", "1024")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "45")
    cfg = LLMConfig()
    assert cfg.provider == "anthropic"
    assert cfg.model_name == "claude-sonnet-4-5"
    assert cfg.api_key == "sk-env-test"
    assert cfg.temperature == 0.3
    assert cfg.max_tokens == 1024
    assert cfg.timeout_seconds == 45


def test_negative_timeout_rejected():
    with pytest.raises(ValidationError, match="LLM_TIMEOUT_SECONDS"):
        LLMConfig(api_key="sk-test", timeout_seconds=-1)


# ---- 10. extra 字段忽略 ----

def test_extra_fields_ignored():
    cfg = LLMConfig(api_key="sk-test", unknown_field="xxx")
    assert not hasattr(cfg, "unknown_field")


def test_history_config_default_values():
    cfg = HistoryConfig(_env_file=None)
    assert cfg.db_path == "./data/chat_history.db"


def test_history_config_load_from_env(monkeypatch):
    monkeypatch.setenv("HISTORY_DB_PATH", "/tmp/test-history.db")
    cfg = HistoryConfig()
    assert cfg.db_path == "/tmp/test-history.db"
