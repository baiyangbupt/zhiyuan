# WebSocket 测试说明

## 启动服务器

```bash
./start_websocket.sh
```

或者直接运行：
```bash
source .venv/bin/activate
uvicorn app.server:app --host 0.0.0.0 --port 8009 --reload
```

服务器将在 `http://localhost:8009` 启动

## Postman 测试步骤

### 1. 连接 WebSocket
- 创建新的 WebSocket Request
- URL: `ws://localhost:8009/ws/chat`
- 点击 "Connect"

### 2. 发送测试消息

**消息格式（JSON）：**
```json
{
  "type": "chat",
  "session_id": "test_session_001",
  "user_id": "postman_user_123",
  "content": "你好"
}
```

**触发 save_student_info tool 的消息：**
```json
{
  "type": "chat",
  "session_id": "test_session_001",
  "user_id": "postman_user_123",
  "content": "我高考考了650分"
}
```

```json
{
  "type": "chat",
  "session_id": "test_session_001",
  "user_id": "postman_user_123",
  "content": "我在北京"
}
```

```json
{
  "type": "chat",
  "session_id": "test_session_001",
  "user_id": "postman_user_123",
  "content": "我想学计算机专业"
}
```

### 3. 查看服务器日志

在终端中会看到：
```
💾 保存学生信息 | userid=postman_user_123 | sessionid=test_session_001 | type=score | value=650
```

这证明 tool 成功获取到了 userid 和 sessionid！

### 4. 响应格式

服务器返回：
```json
{
  "type": "reply",
  "session_id": "test_session_001",
  "content": "好的，我已经记录下您的高考分数是650分..."
}
```

## 架构说明

- `app/server.py` - FastAPI WebSocket 服务器
- `app/service.py` - ChatService，负责创建 RequestContext 并传递给 Agent
- `app/agent/chat_agent.py` - ChatAgent，配置了 save_student_info tool
- `app/tools/chat_tools.py` - save_student_info tool 定义
- `app/agent/context.py` - RequestContext 数据类
