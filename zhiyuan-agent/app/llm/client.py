from __future__ import annotations

import logfire
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.settings import ModelSettings

from app.config import LLMConfig, LogfireConfig


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
        self.model_settings = ModelSettings(
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )

    def _create_model(self) -> Model:
        cfg = self.config
        match cfg.provider:
            case "openai":
                return OpenAIChatModel(
                    cfg.model_name,
                    provider=OpenAIProvider(api_key=cfg.api_key),
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
                    provider=OpenAIProvider(
                        base_url=cfg.base_url,
                        api_key=cfg.api_key,
                    ),
                )
            case _:
                raise ValueError(f"Unsupported provider: {cfg.provider}")

    def get_model(self) -> Model:
        """返回配置好的 Model 实例。"""
        return self.model