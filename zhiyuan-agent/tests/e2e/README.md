# 端到端测试说明

## 什么是端到端测试？

`tests/e2e/` 目录下的测试会**真正调用 LLM API**，不使用 mock。

## 运行前准备

1. **创建 .env 文件**：
```bash
cp .env.example .env
```

2. **填入真实的 API key**：
```bash
# 编辑 .env 文件
LLM_PROVIDER=openai  # 或 anthropic / openai_compatible
LLM_MODEL_NAME=gpt-4o
LLM_API_KEY=sk-your-real-key-here
LLM_BASE_URL=  # openai_compatible 需要填写
```

## 运行端到端测试

```bash
# 激活虚拟环境
source .venv/bin/activate

# 仅运行 e2e 测试
pytest tests/e2e/ -v -s -m e2e

# 或运行所有测试（包括单元测试 + e2e）
pytest -v -s
```

## 测试用例

- `test_real_llm_simple_query` — 简单问答（1+1=?）
- `test_real_llm_with_tool` — 工具调用（天气查询）
- `test_real_llm_multi_turn` — 多轮对话（记住名字）
- `test_real_llm_with_hooks` — 子类钩子（日志记录）
- `test_real_llm_provider_switch` — 切换 provider

## 注意事项

⚠️ **这些测试会产生真实的 API 调用费用**

- 如果没有 .env 文件或 API key 无效，测试会自动跳过
- 建议使用便宜的模型进行测试（如 gpt-4o-mini）
