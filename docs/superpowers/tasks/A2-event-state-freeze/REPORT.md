---
task: A2
status: DONE_WITH_CONCERNS
executor: zhiyuan-07 (deepseek)
finished_at: 2026-09-20 22:40 +0800
source: docs/superpowers/plans/2026-09-20-codex-native-interaction.md
---

# A2 报告：冻结事件与状态

## 一、结论

事件合同、适配器、P2 状态覆盖、v1 入站字段四件都落地了。**但本任务的主要产出
不是这些**：做 A2 的 fixture 时录真实形状，连着撞出两个生产链路的阻断缺陷，
它们比 A2 本身更要紧——域内工具此前在生产配置下**一次都跑不通**。

## 二、生产 MCP 链路：两个阻断缺陷（本任务发现并修复）

### 2.1 域内工具全部被拒：缺 `readOnlyHint`

真实报文（`codex-cli 0.155.1`，非推测）：

```json
{"type":"mcpToolCall","server":"zhiyuan_domain","tool":"admission.get_history",
 "status":"failed","readOnlyHint":null,
 "error":{"message":"MCP tool call requires approval, but approval policy is never"}}
```

codex 对**未声明只读**的 MCP 工具一律要求审批，而生产配置是
`approval_policy="never"`（`app/config.py`）——无处可批，于是每个域内调用都失败。
对照实验（各一次真实调用）：

| 工具声明 | 结果 |
|---|---|
| 无 `annotations` | `status=failed` + `requires approval, but approval policy is never` |
| `annotations={"readOnlyHint": true}` | `status=completed`，`error=null`，结果正常返回 |

**修复过程中先修错了位置**：第一版改的是 `build_sdk_server`，而线上跑的是
`serve()` 里的手写 stdio 循环（SDK server 只留给测试用）。两份清单各写一遍，
注解只加在测试那份上，于是**单测全绿而线上照样被拒**。改成单一来源
`tool_listing()`，两条路都从它生成。

`readOnlyHint` 同时是**对外的安全承诺**（等于让这些工具免审批执行），所以它必须与
"这些工具确实只读"严格一致：`test_every_listed_tool_declares_read_only_hint`
与既有的 `test_readonly_context_cannot_call_write_capability` 是一对。

### 2.2 真实客户端握手永久挂起：未识别请求沉默

同一次排查抓到的 MCP 线上报文：

```
<<< {"id":1,"method":"tools/list"}                → 有应答
<<< {"id":2,"method":"resources/list"}            → 无应答
<<< {"id":3,"method":"resources/templates/list"}  → 无应答
```

`serve()` 只认 `initialize`/`tools/list`/`tools/call`，**其余带 id 的请求一律沉默**。
客户端在等一个永不到来的应答，握手永远完不成——实测 `mcpServerStatus/list` 超时，
且**链路上没有任何日志**。沉默不是优雅降级。

修复后真实二进制的实际返回：

```
server='zhiyuan_domain' runtimeStatus=None tools=8
  第一个工具 annotations = {"readOnlyHint": true}
```

这同时关掉了 A1 报告第八节留的"真实域内 MCP 工具清单"未验证项。

## 三、A2 本体的交付

| 路径 | 变更 |
|---|---|
| `app/gateway/ui_events.py` | 新增：`SessionKey`、`UiEvent`（白名单校验）、`resync_snapshot` |
| `app/gateway/event_adapter.py` | 新增 `adapt_notification`（白名单过滤器） |
| `app/schemas/ws.py` | v1 入站字段与控制消息；`WSResponse` 明确标注为旧格式 |
| `app/engine/result_synthesis.py` | P2：状态**只降不升** |
| `app/mcp_server/server.py` | `tool_listing()` 单一来源；未识别请求回 `-32601` |
| `tests/fixtures/conversation_v1.jsonl` | 新增：9 条**真实录制**形状 |
| `tests/unit/test_ui_events.py` | 新增：20 条 |
| `tests/integration/test_shadow_gateway.py` | 新增 2 条服务级 P2 回归 |
| `tests/unit/test_ws_compat.py` | 新增 9 条 v1 入站合同 |
| `tests/unit/test_domain_mcp_tools.py` | 新增 2 条，**跑真实子进程读真实报文** |

### P2 修法

`executionStatus` 回答"用户诉求满足了吗"，工具批次状态回答"这些调用成功了吗"——
两个不同的问题。旧代码用后者覆盖前者，于是"用户要求读+写，系统只做了读、拒了写，
然后报告 completed"。现改为：工具失败可以把 `completed` 拉低（那是真观测），
反之不允许。

文案与状态字段**分别取键**：文案按 `tool_status`（观测），状态按合并结果（诉求）。
共用一个键会在"模型说 blocked、工具其实全成功"时凭空多出一句"部分工具步骤未执行"——
那是编造观测。

### fixture 形状来源

`conversation_v1.jsonl` 的每条形状都从真实录制取（含 `item/started` 嵌套 item、
`item/reasoning/textDelta`、`turn/completed`），不是照调用方期望编的。
另有一条 `test_fixture_covers_the_required_shapes`，防止以后少录一类形状让断言静默变弱。

## 四、验收命令与原始结果

```
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_ui_events.py \
  tests/unit/test_result_synthesis.py tests/unit/test_ws_compat.py -q
# 55 passed

CODEX_APP_SERVER_BIN=<bin> .venv/bin/python -m pytest tests/ -q
# 2 failed, 1773 passed, 42 skipped
# 两条 failed 与台账基线逐字同名；passed 由 A1 后的 1741 增至 1773

# 真实二进制对生产 MCP 的确认（本报告 2.2 节输出）
mcpServerStatus/list → server='zhiyuan_domain' tools=8, 每个带 readOnlyHint
```

### 非空性证据

- 新适配器对旧实现的反证：`adapt_codex_item`（旧函数）对嵌套 item 返回 `None`，
  故新断言在旧实现上必然失败。
- P2 服务级测试的断言对是自证的：同一用例里既断言
  `trace.batchReport.status == "completed"` 又断言 `executionStatus == "partial"`，
  这两条在旧代码下不可能共存。
- `readOnlyHint` 的生产路径测试：修复前独立跑生产 stdio 循环的输出是
  `annotations = null`、`全部工具都带 readOnlyHint: False`。

## 五、未完成 / 留给下一环（不得当作已修）

1. **旧适配器 `adapt_codex_item` 仍会把未校验的模型原文当 `assistant.delta`
   发出去**。它是 `app/gateway/service.py:730/767` 走的旧路径，A2 的文件清单不含
   `service.py`（归 A3 重接）。当前状态下浏览器仍可能收到 TurnOutput 的 JSON 片段，
   与设计 §5"首期不发送 `assistant.delta`"相抵触。**A3 换路径时必须一并删掉**。
2. **`turnSteer` 的载荷位置是按判断定的**：计划写"控制消息为空串"，但转述文本
   没有别的字段可放。现规定 turnSteer 必须带非空 `content`，其余控制消息必须为空串。
   若设计侧另有约定，改 `app/schemas/ws.py` 一处即可。
3. `session.resync` 目前只有构造器（`resync_snapshot`），**没有接线**——重放与
   订阅切换属 A5/A3。
4. 事件编号（`sequence` 分配）未实现，属 A5。

## 六、证据边界

本报告所有"通过"均为 Python 层与协议层结论。页面级行为、真实浏览器、
真实 Java 业务链路均未验证，按计划归 C 线。
