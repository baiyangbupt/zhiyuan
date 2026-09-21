---
task: A6
status: PARTIAL
executor: zhiyuan-07 (deepseek)
finished_at: 2026-09-21 01:40 +0800
source: docs/superpowers/plans/2026-09-20-codex-native-interaction.md
---

# A6 报告（部分）：前端组件接线

## 一、结论

**A 线前端这一层能做的都做了**：事件协议、reducer、澄清卡、理解卡、
MessageList 的事件消费与渲染、出站帧构造。

按计划的完成判据（"浏览器行为交 C4"），本任务仍记 PARTIAL——**没有任何浏览器验证**。

## 二、已完成

| 路径 | 变更 | 验证 |
|---|---|---|
| `src/utils/conversationSession.mjs` | 新增：纯 reducer | 13 条 node:test |
| `src/utils/conversationSession.test.mjs` | 新增 | — |
| `src/utils/conversationEvents.mjs` | 扩展：v1 事件识别、payload 白名单、旧信封转换 | 16 条 node:test |
| `src/utils/conversationEvents.test.mjs` | 扩展 5 条 | — |
| `ConversationEvents/ClarificationCard.tsx` | 新增：澄清卡组件 | tsc 无新增错误 |
| `MessageList/index.tsx` | 消费 reducer；渲染进度/澄清卡/停止按钮 | tsc 无新增错误 |
| `hooks/useWebSocket.tsx` | 队列上限 20、换 URL 清空队列、去掉地址日志 | tsc 无新增错误 |
| `src/utils/conversationProtocol.mjs` | 新增：出站帧构造（6 条 node:test） | node:test |
| `ConversationEvents/UnderstandingCard.tsx` | 新增：理解卡 | tsc 无新增错误 |
| `conversationSession.mjs` | 加 `hasStructuredUnderstanding` 判定 | 2 条 node:test |

### reducer 的两条不变量，各自有测试钉住

- **缺口不补平**：序号跳号只允许 resync，不允许"当成正常前进"。补平会让
  用户永久看不到丢掉的那几条，而且没有任何迹象。
- **applied 不回退**：迟到的 `applying` 不能把已生效刷回确认中——否则用户会
  先看到"已生效"再看到"确认中"，然后不确定到底生效没有。

### 旧信封 → v1 的转换，带一条自我暴露

旧帧里没有序号，转换时只能分配**本地序号**。这样的序号在本次连接内可用、
跨重连不可用，所以转换产物带着 `localSequence: true`——页面据此知道
**不能**拿它做断线恢复。可重放的编号要等事件存储接进来（A3/A5 的交接点）。

## 三、实现中发现并修掉的两个自己的错

1. **reducer 的首帧分支没推进序号**。采纳代际时忘了采纳序号，导致首帧之后
   下一条正常事件立刻被判成"缺口"，永久 resync。
2. **测试自己写错了一条**：断言"未知事件类型不改变状态"时去读 `turns.t.steps`，
   而未知类型本来就不该建回合条目。改成断言 `turns.t === undefined`——
   建一个空回合会让页面上多出一条什么都没有的气泡。

## 四、验收命令与原始结果

```
cd zhiyuan-web
node --test src/utils/conversationEvents.test.mjs \
  src/utils/conversationSession.test.mjs \
  src/utils/codexLocalRewrite.test.mjs \
  src/pageComponents/sessionDetailV2/MessageList/fetchQueue.test.mjs
# tests 32 / pass 32 / fail 0

node --test src/utils/conversationProtocol.test.mjs      # 6 passed
node --test src/utils/conversationSession.test.mjs      # 15 passed

npx --no-install tsc --noEmit --incremental false
# 错误总数 24，**全部是既有基线**；本任务新增与修改的文件零错误
```

基线记录：本任务开始时该命令即报 24 条错误，全部落在 `src/pageComponents/session/`、
`src/pages/userCenter/`、`src/service/` 等既有文件。计划要求"保存基线并要求无新增错误"，
本报告即为该基线。

## 五、MessageList 里改掉的病灶

改动前，**任何**非 pong/thinking 的消息都会走同一条路：

```js
appendAgentWsMessage(data);
fetchLatestMessageList();   // 整表重拉
resetAnswerLoading();       // 结束转圈
```

于是一条工具进度事件会让转圈提前结束、同时触发一次整表重拉；模型还在跑，
用户已经看到"答完了"。现在：

| 事件 | 行为 |
|---|---|
| 进度类（tool.progress / turn.phase…） | **只更新 reducer**，不重拉、不结束 loading |
| `turn.completed` | 结束 loading + 对齐一次列表 |
| `session.resync` | 对齐一次列表（基线被重置了） |
| `conversationAction.result` 且 `actionStatus=applied` | 结束 loading + 对齐一次列表 |

最后那条是刻意收窄的：确认中、已取消、过期都**不**重拉——"确认中"去重拉会让
用户以为已经生效了。

## 六、出站帧抽成纯函数（可测）

WS 出站的形状**有对错**（服务端会拒收），埋在 1771 行的组件里只能靠人眼复核。
已抽到 `conversationProtocol.mjs` 并测了 6 条，其中三条不是格式检查而是语义：

- 作答帧走**独立字段** `clarificationAnswer`，不复用 `conversationAction`——
  后者的语义是"确认/取消一个提案"。
- 停止帧必须有回合号：没有回合号的停止是**无处可去**的，服务端会按
  `turn_mismatch` 拒掉，所以本地就拦住，而不是发出去等一个"没生效"。
- 转述帧必须带内容（服务端 `turn_steer_requires_content`），空的转述等于什么都没说。

顺带把停止的 `clientRequestId` 从 `stop-${turnId}-${Date.now()}` 改成
`stop-${turnId}`：带时间戳的话，重试会被服务端当成一个**新请求**。

## 七、未完成

1. **WorkspacePanel 的 props 接线**：计划要"页面持有 conversationEvents 并传给
   MessageList 与 WorkspacePanel"；现在状态在 MessageList 内部（它是这条 socket
   的持有者）。**已向用户报备并获准按现状继续。** 应用生效后现在会
   `setFetchFlag++` 让工作区刷新，但工作区**看不到事件细节**（比如"正在查什么"）。
2. `src/interface/conversationProtocol.ts` 没建：类型以 JSDoc + 构造器函数的形式
   放在 `.mjs` 里，好处是能被 node:test 直接跑。若后续需要 TS 类型共享再抽。
3. useWebSocket 的"连接后先 ticket/协商/resume"没做（依赖 C1 的票据）。
4. 澄清卡与停止按钮**没有任何组件测试**：项目里没有渲染测试框架，计划也明确
   "不假定已存在 Jest/Vitest"。它们的正确性只能靠 C4 的浏览器验收。

## 七、证据边界

- 纯函数层（reducer、事件转换）有真实测试；**组件与页面改动只有 tsc**，
  没有任何渲染测试或浏览器验证。组件能不能正确渲染、键盘可达性是否真的可用，
  目前**没有证据**。
- MessageList 是本任务里改动最重的一处（1771 行、无测试），接线是否正确
  **只能靠 C4 的浏览器验收**。
- 服务端现在发的是映射到旧信封的进度帧；带 `sequence` 的 v1 信封要等事件存储
  接进 WS（A3/A5 的交接点，A3 报告第六节已记）。所以前端现在走的是
  `toConversationEvent` 的**本地序号**路径，跨重连不能去重。
