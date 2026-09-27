# 改动单：F13 剩下的那一格——**冷加载后卡片重建**（待裁决）

状态：**待裁决**（2026-09-27 ✓，网关那半已修 ✓，F13 用例当前红在这格 ✗）

## 一、现象与已修的部分

F13（applying 时断线）用例断言三条 ✓：① 事务不被取消 ✓ ② 不双写 ✓ ③ **重连后读得到最终结果** ✓。
实测 ①② 过 ✓、③ 红 ✗：

```
[f13] before: version=0 phase=candidate_generated；after: version=3 phase=reviewed；settled: version=3
```

**已修（网关侧 ✓ 提交 602e16e ✓）**：动作收尾改挂"会话"不挂"这一轮/这条连接"
（`SessionRuntime.detach_work` ✓ + `server.py: _run_action_work` ✓）——修前掉线会把"发结果"那一步一起带走 ✗
（事件流里 `conversationAction.result` **0 条** ✗），修后同一条会话的流里有了 ✓（0 → 2 条 ✓）。

## 二、剩下的那格：卡片状态**只活在事件流里**

| 事实 | 出处 |
|---|---|
| 冷加载（刷新/第一条连接）客户端**没有游标** ✓ | `conversationCursor.mjs` 的口径三条：游标**不落盘** ✓ |
| 没有游标时服务端**只补"在飞回合"** ✗ | `app/server.py:596` → `_replay_active_turn` ✓（只回 `event.turn_id == turn.ui_turn_id` ✓） |
| 卡片状态没有第二个来源 ✗ | 消息正文走 REST `/message/page` ✓；快照的 `activeProposal` 在动作落定后就没了 ✗ |

→ 已结束回合的 `proposal.preview` / `conversationAction.result` **一条都不会重放** ✗，
于是刷新/重连后**提案卡重建不出来** ✗（页面只剩那两句文本 ✓）。

## 三、为什么"只补卡片类事件"不行 ✗（已排除，别再试）

reducer 的规矩（`zhiyuan-web/src/utils/conversationSession.mjs`）：

```
:129  别的会话的事件直接忽略（sessionId 比对）        ← 跨会话污染本就被挡 ✓
:189  sequence !== lastSequence + 1  →  resync        ← 过滤补发必被判"缺口" ✗
:146  首帧可被采纳为基线（任意序号 ✓）               ← 单帧可以 ✓，多帧不行 ✗
:133  resync 会**重置**基线（不是接在后面）           ← 拿 resync 打头也救不了第二帧 ✗
```

所以"补一段不连续的事件"这条路是死的 ✗✓——**要么整段补发（稠密 ✓）**，**要么另给一个来源** ✓。

## 四、两条可行路线（请裁一条）

**A. 协议侧：冷加载发一帧"卡片快照"** ✓
- 网关在无游标路径上多发一帧（挂在 `session.resync` 的 `baseline` 里 ✓ 或单开一类 ✓），
  内容 = 本会话**每条提案的 `{proposalRef, actionStatus}`** ✓；
- 优点：不动 Java ✓、不加 REST ✓；**单帧** ⇒ 绕开缺口规则 ✓（第一帧任意序号可采纳 ✓）；
- 代价：动协议白名单 ✓（`conversationEvents.mjs` ✓）+ reducer ✓ + 网关 ✓；前端要按它**重建卡片** ✓。

**B. 数据侧：把"最后一条提案 + 动作状态"放进快照** ✓
- Java 的工作区状态多暴露一格 ✓（例如 `lastProposal: {proposalRef, status, actionStatus}` ✓），
  网关透传 ✓，前端像今天读 `activeProposal` 一样读它 ✓；
- 优点：**不碰事件协议** ✓，前端改动更小 ✓（现有卡片渲染路径就能用 ✓）；
- 代价：动 Java ✓（快照语义 ✓）+ 网关 ✓；要定"多久之前的算 last"这个口径 ✓。

两条都**不需要**动"冷加载不补历史事件"这个既有决定 ✓（消息正文继续走 REST ✓，避免同一句渲染两遍 ✓）。

## 五、附：两条查过头的记录（免得重复走）

1. **"页面混进别的会话的内容"** ✗ → **不成立** ✓：那条文本属于会话 id **复用的那条会话**自己 ✓
   （900026：12 条里 2 条命中 ✓），不是串台 ✗；真因是池子只有 32 格 ✓（与 F08 假红同源 ✓）。
2. **"库里 2 条却渲染 8 份"** ✗ → **仍未定** ✓（`--trace retain-on-failure` 的 trace 里只见到一份
   该会话的 `/message/page` 响应 ✓），按未定记 ✗，不写成结论 ✓。
