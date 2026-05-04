# RequestContext 测试报告

## 测试概述

验证 Pydantic AI 的依赖注入机制（deps）能够正确地将 `RequestContext`（包含 userid 和 sessionid）传递到 tool 函数中。

## 测试结果

✅ **所有 9 个测试用例全部通过**
✅ **所有 43 个单元测试和集成测试全部通过**

### 单元测试 (6 个)

位置：`tests/unit/test_request_context.py`

1. ✅ `test_base_agent_accepts_deps_type` - 验证 BaseAgent 接受 deps_type 参数
2. ✅ `test_run_passes_deps_to_agent_iter` - 验证 run() 方法将 deps 传递给 agent.iter()
3. ✅ `test_run_with_history_passes_deps` - 验证 run_with_history() 方法传递 deps
4. ✅ `test_tool_can_access_request_context` - 验证 tool 能访问 RequestContext
5. ✅ `test_request_context_with_different_values` - 验证不同的 userid/sessionid 值
6. ✅ `test_multiple_tools_share_same_context` - 验证多个 tool 共享同一上下文

### 集成测试 (3 个)

位置：`tests/integration/test_request_context_integration.py`

1. ✅ `test_request_context_in_real_agent_run` - 真实 Agent 运行中的上下文传递
2. ✅ `test_request_context_with_message_history` - 带历史消息的上下文传递
3. ✅ `test_different_contexts_for_different_requests` - 不同请求使用不同上下文

## 核心验证点

### 1. 上下文创建和传递
```python
context = RequestContext(userid="user_123", sessionid="session_456")
result = await agent.run("user prompt", deps=context)
```

### 2. Tool 中访问上下文
```python
async def my_tool(ctx: RunContext[RequestContext], param: str) -> str:
    userid = ctx.deps.userid
    sessionid = ctx.deps.sessionid
    # 使用 userid 和 sessionid 进行业务逻辑处理
    return f"Processed for user {userid}"
```

### 3. 类型安全
- 使用 `RunContext[RequestContext]` 提供完整的类型检查
- IDE 能够自动补全 `ctx.deps.userid` 和 `ctx.deps.sessionid`
- 类型错误会在编译时被捕获

## 测试覆盖的场景

- ✅ 单个 tool 访问上下文
- ✅ 多个 tool 共享同一上下文
- ✅ 不同请求使用不同上下文
- ✅ 带历史消息的上下文传递
- ✅ 上下文在 agent 迭代循环中的持久性

## 使用示例

### WebSocket 处理函数
```python
async def handle_websocket_request(
    userid: str,
    sessionid: str,
    user_message: str,
) -> str:
    # 1. 创建上下文
    context = RequestContext(userid=userid, sessionid=sessionid)

    # 2. 调用 agent
    response = await chat_agent.run(
        user_prompt=user_message,
        deps=context,
    )

    return response
```

### Tool 实现
```python
async def save_user_data(
    ctx: RunContext[RequestContext],
    data: dict,
) -> str:
    # 访问 userid 和 sessionid
    await database.save(
        userid=ctx.deps.userid,
        sessionid=ctx.deps.sessionid,
        data=data,
    )
    return "Data saved"
```

## 结论

✅ RequestContext 机制工作正常，能够可靠地将 userid 和 sessionid 传递到所有 tool 函数中。

## 运行测试

```bash
# 运行所有 RequestContext 测试
source .venv/bin/activate
python -m pytest tests/unit/test_request_context.py tests/integration/test_request_context_integration.py -v

# 运行单元测试
python -m pytest tests/unit/test_request_context.py -v

# 运行集成测试
python -m pytest tests/integration/test_request_context_integration.py -v
```
