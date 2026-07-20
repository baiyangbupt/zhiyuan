from __future__ import annotations

import httpx
import logfire
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.settings import ModelSettings

from app.config import LLMConfig, LogfireConfig


_OPENAI_DEFAULT_REQUEST_TIMEOUT_SECONDS = 600.0


def configure_logfire(logfire_config: LogfireConfig | None = None) -> None:
    """配置 Logfire 并启用 Pydantic AI instrumentation。"""
    cfg = logfire_config or LogfireConfig()
    if not cfg.enabled or not cfg.token:
        return
    logfire.configure(token=cfg.token)
    logfire.instrument_pydantic_ai()


class LLMClient:
    """根据配置创建 Pydantic AI Model 实例。"""

    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig()
        self.model: Model = self._create_model()
        settings = {
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if self.config.timeout_seconds > 0:
            settings["timeout"] = self.config.timeout_seconds
        self.model_settings = ModelSettings(**settings)

    def _create_model(self) -> Model:
        cfg = self.config
        match cfg.provider:
            case "openai":
                return OpenAIChatModel(
                    cfg.model_name,
                    provider=self._create_openai_provider(),
                )
            case "anthropic":
                provider_kwargs = {"api_key": cfg.api_key}
                if cfg.base_url:
                    provider_kwargs["base_url"] = cfg.base_url
                return AnthropicModel(
                    cfg.model_name,
                    provider=AnthropicProvider(**provider_kwargs),
                )
            case "openai_compatible":
                return OpenAIChatModel(
                    cfg.model_name,
                    provider=self._create_openai_provider(base_url=cfg.base_url),
                )
            case _:
                raise ValueError(f"Unsupported provider: {cfg.provider}")

    def _create_openai_provider(self, *, base_url: str | None = None) -> OpenAIProvider:
        if base_url is None:
            provider = OpenAIProvider(api_key=self.config.api_key)
        else:
            provider = OpenAIProvider(base_url=base_url, api_key=self.config.api_key)
        provider.client.timeout = httpx.Timeout(
            _OPENAI_DEFAULT_REQUEST_TIMEOUT_SECONDS,
            connect=self.config.connect_timeout_seconds,
        )
        return provider

    def get_model(self) -> Model:
        """返回配置好的 Model 实例。"""
        return self.model
