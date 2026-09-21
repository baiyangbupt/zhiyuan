---
task: A3
status: DONE_WITH_CONCERNS
executor: zhiyuan-07 (deepseek)
finished_at: 2026-09-21 00:20 +0800
source: docs/superpowers/plans/2026-09-20-codex-native-interaction.md
---

# A3 报告：实际流式事件与可响应的 WebSocket

## 一、结论

"终态闸门没开时前端已收到进度"这条**在真实替身二进制上成立**，两个 WS 路由的
接收器都不再被回合堵住，停止请求能拿到确认。核心断言用的不是"最终 events 数量
对得上"——数量对了也可能是终态之后补发的，那对用户就是"点了没反应然后一次性蹦出来"。

| 能力 | 落点 | 证据 |
|---|---|---|
| collect 循环内实时回调 | `harness/codex.py` `on_notification` | 真二进制 + 闸门 |
| 进程退出唤醒全部等待者 | `harness/client.py` | 单测 |
| 通知积压上限/TTL/溢出计数 | `harness/client.py` | 单测 |
| 会话运行时分发 | `gateway/session_runtime.py` | 5 条单测 |
| 每连接有界通道（256） | `ConnectionChannel` | WS 集成 |
| 回合后台跑、接收器只分发 | `server.py` 两条路由 | WS 集成（参数化） |
| 停止/转述按回合号路由 | `SessionRuntime.interrupt/steer` | 单测 + WS 集成 |

## 二、发现并修复的两个真缺陷

### 2.1 新事件被旧信封的 Literal 拒收

原生路由把 `tool.progress` 塞进 `WSResponse`（一个**冻结的 `Literal`**），
当场 ValidationError，前端收到的是"事件格式错误"。实测报文：

```json
{"type": "recoverable.error", "content": "{\"type\": \"recoverable.error\", \"message\": \"事件格式错误\"}"}
```

这正是 A2 报告里写下的那条约束——"别把新事件发进不接受它的旧 Literal"——
只是我当时没意识到它会在 A3 的第一跑就撞上。修法是**映射到旧信封已有的类型**
（`tool.progress` → `planning.status`），而不是放宽那个 Literal：放宽会让所有
老客户端收到它们解析不了的帧。

### 2.2 停止请求永远返回 `unavailable`

`SessionRuntime.interrupt` 需要**原生** turnId（`expectedTurnId`），而它只在
`bind_codex_turn` 被调用后才有值——**没有任何地方调用它**。于是用户点停止，
拿到的是"当前引擎不支持停止或补充"。

修法：`start_turn_and_collect` 增加 `on_turn_started` 回调，Gateway 在回合开始时
把原生回合号绑到运行时上。这层映射刻意**不放在浏览器里**——否则前端就能指定
改哪个原生回合。

## 三、一条回归，与它暴露的理解错误

给 `start_turn_and_collect` 平白多传 `on_notification=None`，把签名里没这个参数的
替身 harness 全部打挂（3 条回归）。计划写的是"旧调用不变"——我原以为指语义不变，
**它指的是调用形态也不变**：多传一个语义上 no-op 的参数，依然是一次破坏性改动。
现在只在真有回调时才传。

## 四、一处刻意的契约变更（需要复核）

原生接收循环原先把 `WebSocketDisconnect` **往上抛**，compat 循环则捕获后返回。
两者不一致，而客户端断开是每天发生几百次的正常结束，不是错误。

我把原生也改成捕获后返回，并相应更新了
`tests/unit/test_ws_conversation_action.py::test_gateway_websocket_rejects_missing_tenant_before_calling_gateway`：
那条测试里的 `pytest.raises(WebSocketDisconnect)` 只是**用来终止循环**，
它真正要验的是"缺 tenant 时不调用 gateway、且回了错误帧"——这两条断言一字未动。

如果设计侧认为应保留"向上抛"的语义，回退这一处即可（WS 测试需要改成容忍断开）。

## 五、验收命令与原始结果

```
cd zhiyuan-agent
CODEX_APP_SERVER_BIN=<bin> .venv/bin/python -m pytest tests/ -q
# 2 failed, 1784 passed, 56 skipped
# 两条 failed 与台账基线逐字同名；A3 新增 11 条

CODEX_TEST_REDIS_URL=redis://127.0.0.1:16379/9 ... pytest tests/ -q
# 2 failed, 1797 passed, 42 skipped
```

WS 层用例参数化覆盖 `native` / `compat` 两条路由，含：

- 回合仍在跑时收进度帧 → 发停止 → 收到确认 → 收到终态；
- 回合不存在时的停止请求**明确说"没生效"**，不假装收到。

### 非空性

- 核心断言在改动前不可能通过：`emit` 那时根本不存在，回调无处可接。
- 闸门替身的行为单独验过：未释放时 `wait_for_notification(turn/completed)` 超时，
  释放后正常终态——即"终态确实是被闸门卡住的，不是恰好没来"。
- 修 `2.1` 前抓到的实际错误帧（本报告第二节）就是反证。

## 六、未完成 / 留给下一环

1. ~~带编号的 v1 envelope 没有接线。~~ **已接（2026-09-21 补做）**：
   `ConnectionChannel` 现在接受 `store`，配了 `CODEX_EVENT_STORE_REDIS_URL` 时
   事件**先入流拿编号再发**；没配置则退回旧信封，**不假装有编号**。
   真实 Redis 上验过：发出的帧带 `protocolVersion:1`/`streamEpoch`/`sequence`，
   且按同一 epoch 重放的编号与发出的**一致**——前端去重与 resync 依赖的就是这个一致性。
   入流出错时退回旧信封发出，而不是静默少事件。
   仍未做：客户端重连时的 `session.resync` 快照（属 A7/C4）。
2. `session.resync` 未接线（A5/A7）。
3. `CODEC_EVENT_STORE_REDIS_URL` 未配置时整个 v1 路径不可用；当前默认就是不可用。
4. 慢消费者策略（队列满 → 关连接 → 重连 resume）有实现，但**没有专门的测试**
   覆盖"队列真的打满"这一分支——`on_overflow` 只有代码没有用例。
5. 没有真浏览器验证：C4 的事。

## 七、证据边界

- 替身二进制不是真 codex；真实二进制的原生问答已在 A1 验过，但**没有**用它跑过
  完整的回合流。
- WS 测试用的是 `TestClient`（同进程），**不是**真实网络栈，也没有跨进程重连。
- 停止的端到端语义（真的中断了模型）在替身上验证；真实模型的中断未验。
