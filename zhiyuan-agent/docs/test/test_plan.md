# 测试计划 — AI 高考志愿填报基础架构

## 一、测试基础设施

### 依赖

```
pytest >= 8.0
pytest-asyncio >= 0.24
pytest-mock >= 3.12
```

### pytest 配置（pyproject.toml）

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

### 测试文件结构

```
tests/
├── conftest.py                     # 全局 fixture
├── unit/
│   ├── test_config.py              # LLMConfig 10 个用例
│   ├── test_llm_client.py          # LLMClient 6 个用例
│   └── test_base_agent.py          # BaseAgent 12 个用例
└── integration/
    └── test_agent_integration.py   # 集成测试 5 个用例
```

### 全局 Fixture（conftest.py）

```python
import pytest
from app.config import LLMConfig
from app.llm.client import LLMClient

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
    mocker.patch(
        "app.llm.client.OpenAIChatModel", return_value=mocker.MagicMock()
    )
    mocker.patch(
        "app.llm.client.OpenAIProvider", return_value=mocker.MagicMock()
    )
    return LLMClient(mock_llm_config)
```

---

## 二、单元测试用例

### 2.1 LLMConfig（`tests/unit/test_config.py`）— 10 个用例

| # | 用例名 | 描述 | 关键断言 |
|---|--------|------|----------|
| 1 | `test_full_params` | 所有参数显式传入构造 | 各字段值与传入一致 |
| 2 | `test_default_values` | 仅传 `api_key`，其余走默认 | `provider=="openai"`, `model_name=="gpt-4o"`, `temperature==0.7`, `max_tokens==4096` |
| 3 | `test_provider_openai` | `provider="openai"` 正常构造 | 无异常 |
| 4 | `test_provider_anthropic` | `provider="anthropic"` 正常构造 | 无异常 |
| 5 | `test_provider_openai_compatible_with_base_url` | `provider="openai_compatible"` + 有效 `base_url` | 无异常，`base_url` 值正确 |
| 6 | `test_openai_compatible_missing_base_url` | `provider="openai_compatible"` 但 `base_url=""` | 抛出 `ValidationError`，错误信息含 `LLM_BASE_URL is required` |
| 7 | `test_missing_api_key` | 不传 `api_key`，无环境变量 | 抛出 `ValidationError` |
| 8 | `test_invalid_provider` | `provider="invalid_xxx"` | 抛出 `ValidationError`（Literal 校验失败） |
| 9 | `test_load_from_env` | 通过 `monkeypatch.setenv` 设置 `LLM_` 前缀环境变量 | `LLMConfig()` 读取到正确值 |
| 10 | `test_extra_fields_ignored` | 传入未定义字段 `extra_field="xxx"` | 不报错（`extra="ignore"` 生效），对象无该属性 |

#### Mock 策略

- 直接传参构造，无需 mock
- 环境变量测试用 `monkeypatch.setenv("LLM_API_KEY", "sk-test")` 等
- 需要 `monkeypatch.delenv("LLM_API_KEY", raising=False)` 确保无残留

#### 示例代码

```python
import pytest
from pydantic import ValidationError
from app.config import LLMConfig


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


def test_default_values():
    cfg = LLMConfig(api_key="sk-test")
    assert cfg.provider == "openai"
    assert cfg.model_name == "gpt-4o"
    assert cfg.temperature == 0.7
    assert cfg.max_tokens == 4096
    assert cfg.base_url == ""


def test_openai_compatible_missing_base_url():
    with pytest.raises(ValidationError, match="LLM_BASE_URL is required"):
        LLMConfig(
            provider="openai_compatible",
            api_key="sk-test",
            base_url="",
        )


def test_invalid_provider():
    with pytest.raises(ValidationError):
        LLMConfig(provider="invalid_xxx", api_key="sk-test")


def test_load_from_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_MODEL_NAME", "claude-sonnet-4-5")
    monkeypatch.setenv("LLM_API_KEY", "sk-env-test")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.3")
    cfg = LLMConfig()
    assert cfg.provider == "anthropic"
    assert cfg.api_key == "sk-env-test"
    assert cfg.temperature == 0.3
```

---

### 2.2 LLMClient（`tests/unit/test_llm_client.py`）— 6 个用例

| # | 用例名 | 描述 | 关键断言 |
|---|--------|------|----------|
| 1 | `test_create_openai_model` | `provider="openai"` | `OpenAIChatModel` 被调用，参数含 model_name 和 OpenAIProvider |
| 2 | `test_create_anthropic_model` | `provider="anthropic"` | `AnthropicModel` 被调用，参数含 model_name 和 AnthropicProvider |
| 3 | `test_create_openai_compatible_model` | `provider="openai_compatible"` + base_url | `OpenAIChatModel` 被调用，Provider 含 base_url |
| 4 | `test_model_settings_passed` | 任意 provider | `client.model_settings.temperature` 和 `max_tokens` 与 config 一致 |
| 5 | `test_config_none_auto_construct` | `config=None` | 自动调用 `LLMConfig()` 构造（需环境变量就绪） |
| 6 | `test_unsupported_provider_fallback` | 手动构造非法 provider 绕过 Literal 校验 | 抛出 `ValueError("Unsupported provider")` |

#### Mock 策略

- patch `app.llm.client.OpenAIChatModel` / `AnthropicModel` / `OpenAIProvider` / `AnthropicProvider` 的构造函数
- 用 `mocker.MagicMock()` 替代真实 Model 实例
- 用例 6 需要 `mocker.patch.object(config, "provider", "unknown")` 绕过 Literal 校验

#### 示例代码

```python
from unittest.mock import MagicMock
from app.config import LLMConfig
from app.llm.client import LLMClient


def test_create_openai_model(mocker):
    mock_provider = mocker.patch("app.llm.client.OpenAIProvider", return_value=MagicMock())
    mock_model = mocker.patch("app.llm.client.OpenAIChatModel", return_value=MagicMock())

    config = LLMConfig(provider="openai", model_name="gpt-4o", api_key="sk-test")
    client = LLMClient(config)

    mock_provider.assert_called_once_with(api_key="sk-test")
    mock_model.assert_called_once_with("gpt-4o", provider=mock_provider.return_value)
    assert client.model is mock_model.return_value


def test_create_anthropic_model(mocker):
    mock_provider = mocker.patch("app.llm.client.AnthropicProvider", return_value=MagicMock())
    mock_model = mocker.patch("app.llm.client.AnthropicModel", return_value=MagicMock())

    config = LLMConfig(provider="anthropic", model_name="claude-sonnet-4-5", api_key="sk-ant")
    client = LLMClient(config)

    mock_provider.assert_called_once_with(api_key="sk-ant")
    mock_model.assert_called_once_with("claude-sonnet-4-5", provider=mock_provider.return_value)


def test_model_settings_passed(mocker):
    mocker.patch("app.llm.client.OpenAIChatModel", return_value=MagicMock())
    mocker.patch("app.llm.client.OpenAIProvider", return_value=MagicMock())

    config = LLMConfig(provider="openai", api_key="sk-test", temperature=0.3, max_tokens=2048)
    client = LLMClient(config)

    assert client.model_settings.temperature == 0.3
    assert client.model_settings.max_tokens == 2048


def test_unsupported_provider(mocker):
    config = LLMConfig(provider="openai", api_key="sk-test")
    # 绕过 Literal 校验，直接修改属性
    object.__setattr__(config, "provider", "unknown")

    mocker.patch("app.llm.client.OpenAIProvider")
    mocker.patch("app.llm.client.OpenAIChatModel")

    import pytest
    with pytest.raises(ValueError, match="Unsupported provider"):
        LLMClient(config)
```

---

### 2.3 BaseAgent（`tests/unit/test_base_agent.py`）— 12 个用例

| # | 用例名 | 描述 | 关键断言 |
|---|--------|------|----------|
| 1 | `test_init_no_tools_no_skills` | 不传 tools 和 skill_dirs | `Agent()` 被调用，`tools=[]`, `toolsets=[]` |
| 2 | `test_init_with_tools` | 传入 tools 列表 | `Agent()` 的 `tools` 参数包含传入的工具 |
| 3 | `test_init_with_skill_dirs` | 传入 `skill_dirs=["./skills"]` | `SkillsToolset` 被创建，`toolsets` 非空 |
| 4 | `test_init_skills_toolset_unavailable` | `SkillsToolset = None`（import 失败） | `toolsets=[]`，不报错 |
| 5 | `test_run_single_node` | 模拟 iter() 返回 1 个非 End 节点 + End | `on_node` 被调用 1 次，返回 result.output |
| 6 | `test_run_multi_nodes` | 模拟 iter() 返回 3 个节点 + End | `on_node` 被调用 3 次 |
| 7 | `test_on_node_hook_called` | 默认 `on_node` 不报错 | 调用无异常 |
| 8 | `test_on_complete_hook_called` | 默认 `on_complete` 不报错 | 调用无异常 |
| 9 | `test_subclass_override_hooks` | 子类覆写 on_node/on_complete | 子类方法被调用，可记录日志 |
| 10 | `test_message_history_passed` | 传入 `message_history` | `agent.iter()` 收到 `message_history` 参数 |
| 11 | `test_output_type_passed` | `output_type=dict` | `Agent()` 的 `output_type` 参数为 dict |
| 12 | `test_skills_instructions_injected` | 传入 skill_dirs | `@agent.instructions` 装饰器被调用注册 |

#### Mock 策略

核心难点在于 mock `agent.iter()` 的异步上下文管理器和节点迭代。策略如下：

```python
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic_graph import End


def make_mock_agent_run(nodes, final_output="test output"):
    """构造模拟的 agent_run 上下文管理器。

    nodes: 非 End 节点列表，迭代完后自动返回 End。
    """
    end_node = End(data=None)
    all_nodes = list(nodes) + [end_node]

    agent_run = AsyncMock()
    agent_run.next_node = all_nodes[0]

    call_count = 0
    async def mock_next(current_node):
        nonlocal call_count
        call_count += 1
        return all_nodes[call_count]

    agent_run.next = mock_next
    agent_run.result = MagicMock()
    agent_run.result.output = final_output
    agent_run.usage = MagicMock(return_value="mock_usage")

    # 构造 AsyncContextManager
    ctx_manager = AsyncMock()
    ctx_manager.__aenter__ = AsyncMock(return_value=agent_run)
    ctx_manager.__aexit__ = AsyncMock(return_value=False)
    return ctx_manager, agent_run
```

#### 示例代码

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic_graph import End
from app.agent.base_agent import BaseAgent


@pytest.fixture
def mock_llm_client():
    client = MagicMock()
    client.model = MagicMock()
    client.model_settings = MagicMock()
    return client


def test_init_no_tools_no_skills(mock_llm_client, mocker):
    mocker.patch("app.agent.base_agent.Agent")
    agent = BaseAgent(
        llm_client=mock_llm_client,
        instructions="test",
        output_type=str,
    )
    assert agent.skills_toolset is None


def test_init_with_skill_dirs(mock_llm_client, mocker):
    mock_toolset = MagicMock()
    mocker.patch("app.agent.base_agent.SkillsToolset", return_value=mock_toolset)
    mocker.patch("app.agent.base_agent.Agent")

    agent = BaseAgent(
        llm_client=mock_llm_client,
        instructions="test",
        skill_dirs=["./skills"],
    )
    assert agent.skills_toolset is mock_toolset


def test_init_skills_toolset_unavailable(mock_llm_client, mocker):
    mocker.patch("app.agent.base_agent.SkillsToolset", None)
    mocker.patch("app.agent.base_agent.Agent")

    agent = BaseAgent(
        llm_client=mock_llm_client,
        instructions="test",
        skill_dirs=["./skills"],
    )
    assert agent.skills_toolset is None


async def test_run_single_node(mock_llm_client, mocker):
    mocker.patch("app.agent.base_agent.Agent")
    agent = BaseAgent(llm_client=mock_llm_client, instructions="test")

    node1 = MagicMock()  # 非 End 节点
    ctx_mgr, agent_run = make_mock_agent_run([node1], final_output="hello")
    agent.agent.iter = MagicMock(return_value=ctx_mgr)

    result = await agent.run("hi")
    assert result == "hello"


async def test_subclass_override_hooks(mock_llm_client, mocker):
    mocker.patch("app.agent.base_agent.Agent")

    log = []

    class TestAgent(BaseAgent[str]):
        async def on_node(self, node, agent_run):
            log.append(("node", node))

        async def on_complete(self, agent_run):
            log.append(("complete",))

    agent = TestAgent(llm_client=mock_llm_client, instructions="test")
    node1 = MagicMock()
    ctx_mgr, _ = make_mock_agent_run([node1])
    agent.agent.iter = MagicMock(return_value=ctx_mgr)

    await agent.run("hi")
    assert len(log) == 2
    assert log[0][0] == "node"
    assert log[1][0] == "complete"
```

---

## 三、集成测试用例

### 3.1 集成测试（`tests/integration/test_agent_integration.py`）— 5 个用例

| # | 用例名 | 描述 | 关键断言 |
|---|--------|------|----------|
| 1 | `test_config_to_client_to_agent` | Config → Client → BaseAgent 完整链路 | 对象正确创建，无异常 |
| 2 | `test_demo_agent_subclass` | DemoAgent 子类构造 | on_node/on_complete 钩子可调用 |
| 3 | `test_full_run_flow` | 完整 run() 流程（mock LLM 响应） | 返回预期输出 |
| 4 | `test_multi_turn_conversation` | 多轮对话，传入 message_history | 第二轮 run 收到历史消息 |
| 5 | `test_provider_switch` | 切换 provider 重建 Client | 不同 provider 的 Model 类型正确 |

#### Mock 策略

- 集成测试仍然 mock LLM 的网络调用，但不 mock 内部组件之间的交互
- patch `Agent.iter()` 返回预设的节点序列和输出
- 验证 Config → Client → Agent 的数据流完整性

#### 示例代码

```python
from unittest.mock import MagicMock, AsyncMock
from app.config import LLMConfig
from app.llm.client import LLMClient
from app.agent.base_agent import BaseAgent


def test_config_to_client_to_agent(mocker):
    """验证 Config → Client → Agent 完整链路。"""
    mocker.patch("app.llm.client.OpenAIChatModel", return_value=MagicMock())
    mocker.patch("app.llm.client.OpenAIProvider", return_value=MagicMock())
    mocker.patch("app.agent.base_agent.Agent")

    config = LLMConfig(provider="openai", model_name="gpt-4o", api_key="sk-test")
    client = LLMClient(config)
    agent = BaseAgent(llm_client=client, instructions="你是志愿填报助手")

    assert agent.llm_client is client
    assert agent.llm_client.config is config


async def test_full_run_flow(mocker):
    """验证完整 run 流程，从构造到输出。"""
    mocker.patch("app.llm.client.OpenAIChatModel", return_value=MagicMock())
    mocker.patch("app.llm.client.OpenAIProvider", return_value=MagicMock())
    mocker.patch("app.agent.base_agent.Agent")

    config = LLMConfig(provider="openai", api_key="sk-test")
    client = LLMClient(config)
    agent = BaseAgent(llm_client=client, instructions="test")

    # mock agent.iter() 的完整流程
    node1 = MagicMock()
    ctx_mgr, _ = make_mock_agent_run([node1], final_output="北京大学推荐")
    agent.agent.iter = MagicMock(return_value=ctx_mgr)

    result = await agent.run("推荐一个大学")
    assert result == "北京大学推荐"


async def test_multi_turn_conversation(mocker):
    """验证多轮对话 message_history 传递。"""
    mocker.patch("app.llm.client.OpenAIChatModel", return_value=MagicMock())
    mocker.patch("app.llm.client.OpenAIProvider", return_value=MagicMock())
    mock_agent_cls = mocker.patch("app.agent.base_agent.Agent")

    config = LLMConfig(provider="openai", api_key="sk-test")
    client = LLMClient(config)
    agent = BaseAgent(llm_client=client, instructions="test")

    history = [{"role": "user", "content": "我考了650分"}]
    ctx_mgr, _ = make_mock_agent_run([], final_output="ok")
    agent.agent.iter = MagicMock(return_value=ctx_mgr)

    await agent.run("推荐大学", message_history=history)
    agent.agent.iter.assert_called_once_with("推荐大学", message_history=history)
```

---

## 四、Mock 策略总结

| 模块 | Mock 对象 | 方式 | 说明 |
|------|-----------|------|------|
| LLMConfig | 无 | 直接传参 / monkeypatch 环境变量 | 纯数据类，无需 mock |
| LLMClient | `OpenAIChatModel`, `AnthropicModel`, `OpenAIProvider`, `AnthropicProvider` | `mocker.patch()` 替换构造函数 | 避免真实 HTTP 连接 |
| BaseAgent | `Agent` 类, `agent.iter()` | patch Agent + 自定义 AsyncContextManager | 模拟节点迭代流程 |
| SkillsToolset | `pydantic_ai_skills.SkillsToolset` | patch 为 `None` 或 `MagicMock` | 模拟 import 失败或正常加载 |

---

## 五、运行方式

```bash
# 运行全部测试
pytest

# 仅运行单元测试
pytest tests/unit/

# 仅运行集成测试
pytest tests/integration/

# 带覆盖率
pytest --cov=app --cov-report=term-missing

# 运行单个文件
pytest tests/unit/test_config.py -v
```

---

## 六、覆盖率目标

| 模块 | 目标覆盖率 |
|------|-----------|
| `app/config.py` | >= 95% |
| `app/llm/client.py` | >= 90% |
| `app/agent/base_agent.py` | >= 85% |
| 整体 | >= 90% |

---

## 七、与 init_plan 功能点对照

| init_plan 功能点 | 对应测试 |
|-----------------|---------|
| LLMConfig 环境变量加载 | test_config #9 |
| LLMConfig provider 校验 | test_config #3-#6, #8 |
| LLMConfig base_url 必填校验 | test_config #6 |
| LLMClient match/case 分发 | test_llm_client #1-#3 |
| LLMClient ModelSettings | test_llm_client #4 |
| LLMClient config=None 自动构造 | test_llm_client #5 |
| BaseAgent tools 传入 | test_base_agent #2 |
| BaseAgent skill_dirs + SkillsToolset | test_base_agent #3, #4, #12 |
| BaseAgent iter() + while 循环 | test_base_agent #5, #6 |
| BaseAgent on_node/on_complete 钩子 | test_base_agent #7-#9 |
| BaseAgent message_history | test_base_agent #10 |
| BaseAgent Generic[T] output_type | test_base_agent #11 |
| Config→Client→Agent 完整链路 | integration #1 |
| DemoAgent 子类 | integration #2 |
| 完整 run 流程 | integration #3 |
| 多轮对话 | integration #4 |
| 多 provider 切换 | integration #5 |
