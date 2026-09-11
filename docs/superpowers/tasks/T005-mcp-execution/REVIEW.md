---
task: T005
verdict: ACCEPTED_WITH_FOLLOWUP
reviewer: 设计会话（Claude Opus 5）
reviewed_at: 2026-09-11
---

# T005 回收判定

## 一、判定

`ACCEPTED_WITH_FOLLOWUP`。四项改动全部经独立复核成立：只读工具真的执行了，`mcpCalls` 仪表真的有读数了，`observed.tools` 不再被服务器名污染。

后续项两条，都不是 T005 的缺陷，但都必须落账：

1. `app/engine/turn_trace.py` 是**生产代码**，改了却没留回归测试（T005 新增的那条测试测的是夹具，不是这个函数）。
2. T005 的验收门禁**本身是不稳定的**——我独立重跑 8 次，7 次 `passed=true`，1 次连 `evaluation` 字段都不产生。根因在 `app/harness/codex.py:302`，与 T005 无关，转 **T008**。

## 二、自行重跑的验收（不采信报告输出）

### 命令 1：夹具回归测试

`2 passed`。

### 命令 2：全量单测

```
FAILED tests/unit/test_dialog_quality_gate.py::test_final_action_explicit_clone_sources_have_volunteer_fixture
FAILED tests/unit/test_ops_release_smoke.py::test_release_smoke_supports_production_and_dev_web_base_paths[None-/assistant-pc/session]
2 failed, 1700 passed, 34 skipped, 22 warnings in 29.05s
```

失败恰为已知基线两项，逐字一致。通过数 1699 → 1700，差额 +1 = 新增的 `test_semantic_readonly_server_marks_every_tool_read_only`。零漂移。

### 命令 3：真实端点，`reference-complete-history` × 8

报告跑了 3 次全过。我跑了 3 次，**第 3 次挂了**，于是补跑 5 次定位。合计：

| 次 | status | output | evaluation |
|---|---|---|---|
| 1 | completed | present | `passed=True failures=[]`，mcpCalls=2 |
| 2 | completed | present | `passed=True failures=[]`，mcpCalls=2 |
| **3** | **completed** | **null** | **字段不存在** |
| 4–8 | completed | present | 5 次全部 `passed=True failures=[]` |

**7/8 通过，1/8 无读数。** 报告的 3/3 没有造假——同一门禁我前 2 次也过了，这是个低频抖动，实现方的 6 次真实运行（命令 2 两次 + 命令 3 六次）没撞上。

### 命令 4：P1a 侧回归

`mvn -o test`：`Tests run: 708, Failures: 0, Errors: 0, Skipped: 5`，`BUILD SUCCESS`。T005 的 Agent 侧改动未影响 Java。

## 三、实现质量评审

**`readOnlyHint` 的补法正确且最小。** 两个工具各加一行 `annotations`，没动 `approval_policy`、没动 `sandbox_policy`、没动 `TURN_OUTPUT_SCHEMA`、没动 `/root/dev/codex`。边界清单逐项核对，无越界。

**trace 通道改到 argv 的做法是对的。** `--trace <path>` 走 `args`，与既有的 `--authoritative` 同一条已证明可用的通路；环境变量读取保留为回退，不破坏别的调用方。仪表从"恒为 `[]`"变成"每次 2 条且与夹具自身记录一一对应"——这正是规则 4 要求的仪表自证，做到了。

**`turn_trace.py` 的过滤器我单独验过，是安全的，但结论要写死在这里以免后人误改：**

- 被过滤掉的事件，原始载荷形如 `{"type": "mcpServer/startupStatus/updated", "name": "semantic_readonly", "status": ...}`。抽取循环的 `item.get("name")` 会把 MCP **服务器名**当成工具名收进 `toolCalls`——这就是 `observed.tools` 里那个 `semantic_readonly` 的来源，实测坐实。
- 真实的 MCP 工具调用记录在本项目的载荷里 **`type` 为 `None`**，靠 `toolName` 键命中（实测：`{'toolName': 'admission.get_history', 'status': 'completed', 'invocationKey': ..., 'resultCount': ...}`）。`"mcpserver" in ""` 恒假，**过滤器不可能误伤真实工具调用**。
- 即便上游 codex 改用 `ThreadItem` 的 `type` 判别式，其 `McpToolCall` 变体序列化为 `"mcpToolCall"`（`app-server-protocol/src/protocol/v2/item.rs:230` 的 `#[serde(tag = "type", rename_all = "camelCase")]`），小写后为 `mcptoolcall`，同样不含 `mcpserver` 子串。过滤器对上游演进也是安全的。

**`ValidationError` 回退分支的附带修改是合理的。** 原来写死 `"toolCalls": []`，现在用同一份 `mcp_calls` 填。这一分支正是"模型输出不合契约"的现场，恰恰最需要知道工具到底调没调——原实现在最该有读数的地方把仪表关掉了。属规则 4 同一类问题的顺手修正，接受。

**基线纪律严格。** 12 次四场景基线如实给出 9 过 3 不过，`mixed-read-write` 0/3 的三份 `evaluation` 原文完整落盘，没有挑好看的贴。第八节把"同场景 `mcpCalls` 条数在 2/3 之间跳"这种对自己不利的观测也列了。这是本次四份报告里基线纪律最好的一份。

## 四、必须落账的两件事

### 1. `turn_trace.py` 缺回归测试（跟进项）

报告第六节承认"另用合成 payload 单测过该函数"，但那次验证是一次性的，**没有留在仓库里**。`git diff` 确认 `tests/` 下只多了夹具那两条。

这个过滤器防的是一个"错了也能跑、只是读数变脏"的失败模式——正是最容易在后续重构中被悄悄删掉的那种。补一条测试：喂一个含 `{"type": "mcpServer/startupStatus/updated", "name": "<server>"}` 与一个 `{"toolName": "<tool>"}` 的合成 payload，断言 `tool_calls` 只含后者。并入 P1c 或单独补，不阻塞本次判定。

### 2. 门禁抖动：`reference-complete-history` 1/8 无读数 → T008

run 3 的现场，逐层坐实：

- `status=completed`、`errorCode=null`、`errors=[]`、`mcpCalls=2`（工具**确实执行了**）、`elapsedMs=9189.6`。
- `output=null`，因此 `codex_semantic_smoke.py:247` 的 `isinstance(result.output, dict)` 为假，**整个 `evaluation` 键不写入**。
- 从 `item/agentMessage/delta` 重建模型原文（2810 字）：开头是 `**查询结果（2025 年 · 浙江 · 物理类 · 本科批 · 计算机科学与技术）**` 加一张 Markdown 表格，**结尾**才是一段 ` ```json … ``` ` 围栏。
- `app/harness/codex.py:302` 的 `_parse_json_object()` 只在字符串**以** ` ``` ` 开头时剥围栏。前面有散文就不剥，`json.loads` 抛错，返回 `None`。
- 判别性对照：同一条消息，把前置散文切掉只喂围栏块，`_parse_json_object` 立刻返回 `dict`，`responseType='fact'`。**内容是好的，是解析器够不着。**

两层结论：

- **产品层**：`turn/start` 的原生 `output_schema` 在 DeepSeek 上**不保证**结构化输出。模型会时不时先写散文再补围栏 JSON。harness 取不到 output，这一轮在真实 Gateway 里就是废回合。这是 P0 尚未清零的第三层，不是 T005 的锅——T005 的边界是工具执行与仪表。
- **仪表层**：`evaluation` 缺失与 `evaluation.passed == false` 在现象上不同，但**都不是 true**，而任何写成 `d.get('evaluation', {}).get('passed')` 的检查会把前者读成假值而不报错。这是规则 4 第二问（"零值/空列表能自证吗"）的又一个实例：**缺失的键比零值更危险**。

转 **T008**，并在修订计划的 P0 一节补记。

## 五、次要观察（不阻塞，仅记录）

- `mixed-read-write` 0/3 与 P0 验收条"两个复杂场景各连续 3 次 `evaluation.passed == true`"直接冲突。这不是 T005 的验收项（T005 的门禁只写了 `reference-complete-history`，且明写基线**不要求通过**），但它意味着 **P0 在 T005 收尾后仍未清零**。已在修订计划中更新。
- `mixed-read-write-3` 的模型自述里出现 `admission.get_current_plan` 返回 `unsupported call`，而夹具只声明了两个工具。即模型尝试调用了一个不存在的工具。三次失败的 failures 集中在 `proposal_missing` / `execution_status_mismatch` / `limitations_missing` / `next_step_missing`，是写操作路径的契约问题，留给 P2。
- 同一场景 `mcpCalls` 在 2 与 3 之间跳动：模型偶尔多查一次。不影响判定，`evidenceIds` 始终为 2。
