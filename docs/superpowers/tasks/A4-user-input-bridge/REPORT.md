---
task: A4
status: DONE_WITH_CONCERNS
executor: zhiyuan-07 (deepseek)
finished_at: 2026-09-21 00:55 +0800
source: docs/superpowers/plans/2026-09-20-codex-native-interaction.md
---

# A4 报告：原生问答桥与统一澄清卡合同

## 一、结论

桥建好、接进生产装配、**并且通电了**：卡片经 WS 到达前端、答案经 WS 回到
处在等待中的那个回合。15 条集成用例（13 条 broker + 2 条端到端）在真实替身
二进制上跑通。

通电前它是惰性的：模型提问 → 服务端挂起等一个没人答的 future → 十分钟后过期，
而用户从头到尾没被告知过。这正是"桥建好但没接电"的样子，值得记一笔——
线路两端各自都有测试，**中间那一跳没有**，缺陷就住在那里。

## 二、接进生产前，原生提问是被静默吞掉的

`set_server_request_handler` 这个入口**在生产里从来没被调用过**：

```
$ grep -rn "set_server_request_handler" app/ | grep -v "def \|client.py:"
app/harness/codex.py:41:        self.client.server_request_handler = handler
```

即：真实二进制发出 `item/tool/requestUserInput` 时，`AppServerClient._read_stdout`
会走进它的默认分支，回一条 `{"result": null}`。模型的问题被当成"用户回答了空"，
而且**链路上没有任何日志**。这条在 A1 探针里没暴露，因为探针自己设了 handler。

现在 `composition.py` 装配时会建 broker 并挂上去。

## 三、契约里几条不是"防呆"而是"防错答"的约束

| 约束 | 为什么 |
|---|---|
| 身份从 threadId 反查业务绑定，**不读请求参数** | 请求参数里的 tenant/session 是运行时转述的，模型可能参与其中；拿它当隔离边界等于把边界交给被隔离的一方 |
| 选项文案留在服务端，`isOther=false` 时拒绝清单外的值 | 否则浏览器可以凭空造一个选项出来 |
| `inputKind` 是判别式，不能靠"字段在不在"猜 | choice 与 form 的答案形状完全不同，猜错就是把表单当成选择题解析 |
| 每题答案数组长度必须为 1 | 多选需要新协议版本，这一版不假装支持 |
| 过期的处理**不是**回一个 RPC error | Runtime 可能把 error 当成 `answers:{}` 继续跑，"用户没回答"就变成了"用户回答了空" |
| 同 id 同答案 = 收到；同 id 异答案 = 冲突 | 后者是客户端把两个请求搞混了，替它挑一个是错的 |

## 四、实现中改掉的三个自己的错

1. **重复作答的判定顺序反了。** 先判 `future.done()` 再判 `answered`，导致第一次作答之后
   所有重发都返回 `already_answered`——同答案重发拿不到"收到"、异答案重发也拿不到"冲突"，
   而这两种恰恰是客户端最需要区分的。
2. **`_by_rpc` 的键带上了 threadId**，而 `serverRequest/resolved` 通知里带的是 requestId，
   两边对不上，卡片永远清不掉。JSON-RPC 的 id 在一条连接内唯一，不需要额外成分。
3. **`UserInputError` 的 `str()` 只返回 detail**，于是日志与断言看到的是 `confirm`
   这种字段名而不是 `clarification_required_field_missing`。机器可读的 code 必须进正文。

## 五、未完成 / 留给下一环（**不得当作"用户已经能看见卡"**）

1. **过期的 `on_expired` 只有钩子没有实现。** 计划要求"先 interrupt 原 Turn、
   等终态、再清理 handler"，现在 `_on_expired` 是空的。超时后 broker 抛
   `clarification_expired`，而**没有人**去中断那个还在等的回合。
2. **降级路径没做**：能力不可用时校验 `TurnOutput.clarification` 并发出
   `origin=gateway` 的卡，回答作为显式用户输入开启新 turnId（计划要求
   "恰好多一次 turn/start"的独立测试）。A1 已证明原生可用，所以这条不是当前的
   阻塞项，但**能力开关一关它就必须在**。
3. `broker.snapshot` 没有接进 `session.resync`（属 A6/A7）——断线重连后
   卡片**不会**自己长回来。
4. 前端还没有渲染澄清卡的组件（属 A6）。现在推到前端的帧，前端只会当成
   未知类型丢掉。

## 六、验收命令与原始结果

```
cd zhiyuan-agent
.venv/bin/python -m pytest tests/integration/test_gateway_user_input.py -q
# 13 passed

# 端到端：卡片到前端、答案回回合（native / compat 参数化）
.venv/bin/python -m pytest tests/integration/test_gateway_live_events.py -q
# 13 passed

CODEX_APP_SERVER_BIN=<bin> .venv/bin/python -m pytest tests/ -q
# 2 failed, 1799 passed, 56 skipped
# 两条 failed 与台账基线逐字同名
```

### 非空性

- 关键回归"回包用原 rpc id"断言的是 `requestId == 9001`——替身的服务端请求 id
  从 9000 起，新开一个请求会是 9002，所以这条能真的失败。
- "回答一张卡不产生新回合"用替身的 `test/stats` 计数器断言 `turnStarts == 0`；
  计数器是新加的，之前没有可观测面。
- 端到端那条一开始写成了 `any("计算机类" in frame)`——而**卡片本身就带着
  选项文案"计算机类"**，所以光收到卡就能让断言变绿。已改成只认终态回复里的
  "收到答案 计算机类"，只有答案真的回到回合里才会出现。

## 七、真实运行时的闭环（2026-09-21 补验）

C1 落地后把两个特性开关接进了 `composition.py`，随即在**真实二进制 + 真实模型**
（codex-cli 0.155.1 + deepseek-flash）上跑通了一次完整链路：

```
[卡片事件] clarification.requested  ['which_major']   ← 模型自己决定提问
作答 → accepted                                        ← 答案经 broker 回原 rpc id
回合状态: completed | 事件数: 1429                     ← 回合带着答案继续跑完
```

另一次运行里模型一次问了两个问题（`major_choice` + `province`），
而"只答一题"被形状校验拦下（`clarification_answer_shape`）——**那是正确行为**：
答案集合必须等于题号集合，否则"没答的那题"会以空值进入模型。

这条证据同时说明：A1 探针的结论（原生提问可用）与 A4 的桥**确实接上了**，
而不只是各自在替身上通过。

## 八、证据边界

- 替身二进制不是真 codex；上面那次是真实二进制 + 真实模型，但**没有经过 WS**：
  是从 `CodexAppServerHarness` 直接驱动的，浏览器那一段仍未验。
- 提问的触发依赖模型自行判断歧义；本任务用一句明确的指令引导它提问，
  **没有测"模型不提问时是否也能正确降级"**（降级路径本身也没做）。
- 浏览器侧完全没有验证：卡片组件属 A6，真实浏览器属 C4。
