# WebSocket 测试指南

## 功能说明

通过 WebSocket 连接测试 ChatAgent，验证 tool 中能够正确获取到 userid 和 sessionid。

## 核心功能

1. **RequestContext 传递** - 每个 WebSocket 消息都会创建 RequestContext 并传递给 Agent
2. **save_student_info tool** - 当 AI 需要保存学生信息时会调用此 tool，并在日志中打印 userid 和 sessionid
3. **会话历史管理** - 每个 session_id 维护独立的对话历史

## 启动步骤

### 1. 确保环境变量配置正确

```bash
# 检查 .env 文件
cat .env

# 必须配置以下变量
LLM_PROVIDER=openai  # 或 anthropic
LLM_API_KEY=your_api_key
LLM_MODEL_NAME=gpt-4o  # 或 claude-opus-4-6
```

### 2. 安装 websockets 依赖

```bash
source .venv/bin/activate
pip install websockets
```

### 3. 启动 WebSocket 服务器

```bash
source .venv/bin/activate
python app/websocket_server.py
```

服务器将在 `http://localhost:8000` 启动。

### 4. 在另一个终端启动客户端

```bash
source .venv/bin/activate
python examples/websocket_client.py
```

## 测试场景

### 场景 1: 基本对话

```
你: 你好
🤖 AI: 你好！我是高考志愿填报顾问...
```

### 场景 2: 触发 save_student_info tool

```
你: 我高考考了650分
🤖 AI: 好的，我已经记录下您的高考分数...
```

**查看服务器日志**，你会看到类似：

```
💾 保存学生信息 | userid=test_user_123 | sessionid=abc-def-123 | type=score | value=650
```

### 场景 3: 多轮对话

```
你: 我高考考了650分
🤖 AI: 好的...

你: 我在北京
🤖 AI: 了解了...

你: 我想学计算机
🤖 AI: 根据您的情况...
```

每次 tool 调用都会在日志中显示相同的 userid 和 sessionid。

## 日志说明

### 服务器日志格式

```
📨 收到消息 | userid=test_user_123 | session_id=abc-def-123 | message=我高考考了650分
💾 保存学生信息 | userid=test_user_123 | sessionid=abc-def-123 | type=score | value=650
📤 发送响应 | userid=test_user_123 | session_id=abc-def-123 | response=好的...
```

### 关键日志标识

- 🔌 WebSocket 连接/断开
- 📨 收到客户端消息
- 💾 **save_student_info tool 调用（验证点）**
- 📤 发送响应给客户端
- ❌ 错误信息

## 验证要点

1. ✅ 每次 tool 调用日志中都能看到正确的 userid
2. ✅ 每次 tool 调用日志中都能看到正确的 sessionid
3. ✅ 同一个 WebSocket 连接中，sessionid 保持不变
4. ✅ 不同的 WebSocket 连接有不同的 sessionid

## 故障排查

### 问题 1: 连接失败

```bash
# 检查服务器是否启动
curl http://localhost:8000

# 应该返回: {"status":"ok",...}
```

### 问题 2: API 调用失败

```bash
# 检查环境变量
echo $LLM_API_KEY

# 检查 .env 文件
cat .env
```

### 问题 3: 没有看到 tool 调用日志

- AI 可能没有判断需要保存信息
- 尝试更明确的输入："请记录我的高考分数是650分"
- 检查 SYSTEM_INSTRUCTIONS 是否正确配置

## 代码位置

- WebSocket 服务器: `app/websocket_server.py`
- WebSocket 客户端: `examples/websocket_client.py`
- ChatAgent: `app/agent/chat_agent.py`
- Tool 定义: `app/tools/chat_tools.py`
- RequestContext: `app/agent/context.py`
