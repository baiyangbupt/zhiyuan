from __future__ import annotations

from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings


class LLMConfig(BaseSettings):
    """LLM 配置，从环境变量加载。"""

    model_config = {
        "env_prefix": "LLM_",
        "env_file": ".env",
        "extra": "ignore",
    }

    provider: Literal["openai", "anthropic", "openai_compatible"] = "openai"
    model_name: str = "gpt-4o"
    api_key: str
    base_url: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout_seconds: float = 0.0  # 0 表示不设置模型请求层超时，仍使用外层服务超时兜底

    @model_validator(mode="after")
    def _validate(self) -> LLMConfig:
        if self.provider == "openai_compatible" and not self.base_url:
            raise ValueError(
                "LLM_BASE_URL is required when provider is 'openai_compatible'"
            )
        if self.timeout_seconds < 0:
            raise ValueError("LLM_TIMEOUT_SECONDS must be greater than or equal to 0")
        return self


class LogfireConfig(BaseSettings):
    """Logfire 配置，从环境变量加载。"""

    model_config = {
        "env_prefix": "LOGFIRE_",
        "env_file": ".env",
        "extra": "ignore",
    }

    token: str = ""
    enabled: bool = True


class InternalServiceConfig(BaseSettings):
    """内部服务配置，从环境变量加载。"""

    model_config = {
        "env_prefix": "INTERNAL_SERVICE_",
        "env_file": ".env",
        "extra": "ignore",
    }

    url: str = "https://zhiyuan.ytell.cn"


class ExtractConfig(BaseSettings):
    """意向提取配置。"""

    model_config = {
        "env_prefix": "EXTRACT_",
        "env_file": ".env",
        "extra": "ignore",
    }

    last_n_messages: int = 10  # 提取时使用的最近消息数


class PlanConfig(BaseSettings):
    """志愿方案查询配置。"""

    model_config = {
        "env_prefix": "PLAN_",
        "env_file": ".env",
        "extra": "ignore",
    }

    file_addr_format: str = "https://ytell-gaotu-test.oss-cn-beijing.aliyuncs.com/session_volunteer/{chatSessionId}_temp.json"  # URL模板，含 {chatSessionId} 占位符
    file_download_path: str = "./data/plan_cache"  # 本地缓存目录

class RankServiceConfig(BaseSettings):
    """排名服务配置，从环境变量加载。"""

    model_config = {
        "env_prefix": "RANK_SERVICE_",
        "env_file": ".env",
        "extra": "ignore",
    }

    url: str = "http://localhost:5001"

class HistoryConfig(BaseSettings):
    """会话历史持久化配置。"""

    model_config = {
        "env_prefix": "HISTORY_",
        "env_file": ".env",
        "extra": "ignore",
    }

    db_path: str = "./data/chat_history.db"
    runtime_max_messages: int = 24
    runtime_keep_pending: bool = True
    runtime_drop_tool_returns_over_chars: int = 3000
    runtime_summary_enabled: bool = False
