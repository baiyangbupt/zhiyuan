from __future__ import annotations

from typing import Literal
import sys

from pydantic import field_validator, model_validator
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
    connect_timeout_seconds: float = 15.0

    @model_validator(mode="after")
    def _validate(self) -> LLMConfig:
        if self.provider == "openai_compatible" and not self.base_url:
            raise ValueError(
                "LLM_BASE_URL is required when provider is 'openai_compatible'"
            )
        if self.timeout_seconds < 0:
            raise ValueError("LLM_TIMEOUT_SECONDS must be greater than or equal to 0")
        if self.connect_timeout_seconds <= 0:
            raise ValueError("LLM_CONNECT_TIMEOUT_SECONDS must be greater than 0")
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
    timeout_seconds: float = 10.0
    # 仅用于 4.0 发布迁移窗口：新 pending 表无记录时读取旧 extra-data。
    # 新写入始终只走独立 pending 资源，完成存量迁移后应删除此开关和兜底。


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


class BochaSearchConfig(BaseSettings):
    """Bocha official web search configuration."""

    model_config = {
        "env_prefix": "BOCHA_",
        "env_file": ".env",
        "extra": "ignore",
    }

    api_key: str = ""
    base_url: str = "https://api.bochaai.com/v1/web-search"
    timeout_seconds: float = 10.0


class CodexAppServerConfig(BaseSettings):
    """Codex App Server Harness 配置。"""

    model_config = {
        "env_prefix": "CODEX_APP_SERVER_",
        "env_file": ".env",
        "extra": "ignore",
    }

    bin: str = "codex"
    commit: str = "89650c6"
    transport: str = "stdio"
    timeout_seconds: float = 30.0
    approval_policy: str = "never"
    sandbox_policy: str = "read-only"
    binding_ttl_seconds: int = 900
    binding_registry_path: str = ""
    python_bin: str = sys.executable
    skill_root: str = ""
    # 原生提问走哪条路。默认取保守值：A1 探针虽然探到原生提问可用
    # （.runtime/codex-capabilities.json），但那条路径要求启动时带上
    # features.default_mode_request_user_input 与 tools.experimental_request_user_input
    # 两个开关。开关没接上之前声明成 native，就是把"没测过的组合"当默认。
    user_input_mode: Literal["native", "structured_final"] = "structured_final"


class GatewayConfig(BaseSettings):
    """Conversation Gateway 运行模式配置。"""

    model_config = {
        "env_prefix": "GATEWAY_",
        "env_file": ".env",
        "extra": "ignore",
    }

    # `codex_write`（P2）：写闭环活着的实例。它与 readonly 的差别不在模型能调什么
    # （写路径是 提案→确认→执行，模型始终没有可调的写工具），而在确认链是否接上。
    mode: Literal["legacy", "codex_shadow", "codex_readonly", "codex_write"] = "legacy"


class McpConfig(BaseSettings):
    """Domain MCP 运行配置。"""

    model_config = {
        "env_prefix": "MCP_",
        "env_file": ".env",
        "extra": "ignore",
    }

    mode: str = "readonly"
    # `MCP_WRITE_TOOLS_ENABLED`：**没有任何读者** ✗✓（启动脚本还在传 `=false` ✓）。
    # 留着它是因为"写模式"曾经被理解成"给模型开写工具" ✗；P2 重构后那条口径改了 ✓：
    # 新链路的写路径由"模型出 proposalRequest → Java 编译出待确认 → 用户确认 → 网关执行"承担 ✓，
    # **本来就没有模型可调的写工具** ✓；`codex_write` 与 `codex_readonly` 的差别在**确认链是否活着** ✓
    # （见 `app/gateway/service.py:468` 与 `composition.py` 的一致性检查 ✓）。
    # 也就是说这个开关**开与不开行为一样** ✗——真要动它，先把上面的结论推翻 ✓。
    write_tools_enabled: bool = False


class ConversationEventStoreConfig(BaseSettings):
    """对话事件流与请求幂等的存储配置。

    `redis_url` 为空表示没配置：此时事件流不可用，必须**显式失败**而不是
    退回进程内存——进程内的"事件流"在重启后就是另一条时间线，客户端拿旧
    cursor 去接会静默错位。
    """

    model_config = {
        "env_prefix": "CODEX_EVENT_STORE_",
        "env_file": ".env",
        "extra": "ignore",
    }

    redis_url: str = ""
    ttl_seconds: int = 24 * 60 * 60
    max_events: int = 2000
    max_event_bytes: int = 16 * 1024
    # 首期只允许一个 worker：进程内锁不跨进程，多 worker 会让"同一会话串行"
    # 这个前提失效（两个 worker 同时给一个会话开回合，事件流编号依然连续，
    # 但业务状态会互相覆盖）。写成启动期校验，而不是注释里的提醒。
    workers: int = 1

    @field_validator("workers")
    @classmethod
    def _single_worker_only(cls, value: int) -> int:
        if value != 1:
            raise ValueError("event_store_requires_exactly_one_worker")
        return value
