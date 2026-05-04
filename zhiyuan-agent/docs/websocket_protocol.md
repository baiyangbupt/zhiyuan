# WebSocket 接口协议

## 连接地址

```
ws://<host>:<port>/ws/chat
```

---

## 客户端 → 服务端（输入）

### 消息格式（WSMessage）

| 字段         | 类型     | 必填 | 默认值   | 说明             |
|------------|--------|------|---------|----------------|
| `type`       | string | 否   | `"chat"` | 消息类型，固定为 `"chat"` |
| `session_id` | string | 是   | —       | 会话 ID          |
| `user_id`    | string | 否   | `""`    | 用户 ID          |
| `content`    | string | 是   | —       | 用户输入的消息内容     |

**示例：**

```json
{
  "type": "chat",
  "session_id": "session_abc123",
  "user_id": "user_001",
  "content": "我想报考北京的大学"
}
```

---

## 服务端 → 客户端（输出）

### 响应格式（WSResponse）

| 字段         | 类型     | 说明                                    |
|------------|--------|---------------------------------------|
| `type`       | string | 响应类型，枚举值：`"reply"` / `"error"` / `"card"` |
| `session_id` | string | 会话 ID（与请求对应）                          |
| `content`    | string | 响应内容                                 |

---

### 1. 正常回复（`type: "reply"`）

Agent 经过 LLM 处理后返回的文本回复。

```json
{
  "type": "reply",
  "session_id": "session_abc123",
  "content": "好的，了解到你想报考北京的大学。请问你的高考成绩是多少分？选考了哪些科目？"
}
```

**触发条件：** Agent 正常完成对话推理，返回文本回复。

---

### 2. 卡片回复（`type: "card"`）

由 output function 直接返回，**不经过 LLM 二次处理**，前端应渲染为卡片样式。

```json
{
  "type": "card",
  "session_id": "session_abc123",
  "content": "您提到的意向已全部在方案中"
}
```

**触发条件：** Agent 判断用户信息收集充分，调用志愿方案提交工具，后端接口返回成功（`code == 0`）。

---

### 3. 错误响应（`type: "error"`）

出现异常时返回的错误消息，`content` 中包含具体错误信息。

```json
{
  "type": "error",
  "session_id": "session_abc123",
  "content": "处理消息时出错: TimeoutError"
}
```

---

## 前端处理建议

```javascript
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);

  switch (data.type) {
    case 'reply':
      // 渲染为普通文本消息气泡
      renderTextMessage(data.content);
      break;

    case 'card':
      // 渲染为可点击的卡片组件
      renderCard(data.content);
      break;

    case 'error':
      // 显示错误提示
      showError(data.content);
      break;
  }
};
```
