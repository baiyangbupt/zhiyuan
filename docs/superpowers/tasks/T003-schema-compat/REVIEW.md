---
task: T003
verdict: ACCEPTED
reviewer: 设计会话（Claude Opus 5）
reviewed_at: 2026-09-10
---

# T003 回收判定

## 一、判定

`ACCEPTED`。P0 解除:复杂回合 6/6 在真实 DeepSeek 端点 `status=completed`,此前逐字相同的 HTTP 400 不再出现。

## 二、自行重跑的验收(不采信报告输出)

### 命令 1:两条不变量

```
([], [])
```

### 命令 2:schema 专项测试

```
2 passed in 0.12s
```

### 命令 3:全量单测

```
2 failed, 1699 passed, 34 skipped, 22 warnings in 28.66s
```

失败恰为已知基线两项,无新增。

### 命令 4:真实端点

本人重跑 `reference-complete-history` 一次:`status=completed, errorCode=None, respType=text, toolCalls=4`。

其余 5 次核对落盘的原始 stdout 文件(`t003-run-*.json`,完整 JSON 未编辑):全部 `completed / errorCode=None`。报告与此一致。

## 三、实现质量评审

**归一化函数语义正确。** 逐类核对三类改写:

- **A 类(内联对象)**:`{**branch, "anyOf": any_of}` 键提升后,节点约束 = X ∧ (X ∨ null) = X,允许的 JSON 集合不变,可空性保留。上游已实测接受(探测 A2)。
- **B 类(标量)**:`anyOf → type 数组`,`enum`/`minimum`/`exclusiveMinimum`/`default` 原样保留,集合等价。选类型数组而非 E2(anyOf 补 type)的理由正确:E2 在 anyOf 之外多声明一层 `type: "string"`,会引入原节点没有的约束。
- **C 类(`$ref`)**:`$def` 自身声明 `["object","null"]` + 裸 `$ref`(E6 形态)。两个 `$def` 已核实只在可空位置被引用,无副作用扩散。

**探测表质量高,是本任务最有价值的资产。** 六条必录全做,并正确追加了任务书没覆盖到的形态:任务书陷阱 1 只说"A 类与 C 类不同",但没给出 A 类目标形态;实现方用 13 条微用例实测出「anyOf+补 type 会被 `An object with no properties is not allowed.` 拒绝」「type 数组不接受 object/array」这两条任务书不可能预知的规则,这是完成本任务的必要条件。探测表已收录进报告,后续换模型可直接复用。

**偏离项全部有依据,且都指向同一原则:不削弱语义。** 三处偏离(键提升而非补 type、类型数组而非 E2、断言扩展而非改写)各自在报告第六节给出了实测证据链,不构成问题。

**基线对照精确。** 总数差额恰好 = 新增的 1 个测试用例,零漂移。

## 四、复核中发现的两个次要事项(不阻塞)

1. 6 次运行里 `mcpCalls` 均为 0、`toolCalls` 计数为 0/4/8 不等,`ch-1` 的 message 提到「MCP 调用需要审批,当前审批策略为 never」。这说明 codex 的 smoke 脚本把 MCP 工具调用拦下了,只验证了"结构化输出 + 流式完成",没有验证"工具调用 + Evidence 生成"的全链路。这**不是 T003 的缺陷**(它的验收目标就是流与 schema),但提醒 P1 的真实验证需要在审批策略放行 MCP 的环境下重跑。
2. `app/tools/volunteer_tool.py` 在 `app/` 下无任何 import 引用(grep 全量),疑似悬空。仅记录,不在此任务范围内处理。

## 五、遗留与后续

- **P1 权威证据台账**:设计会话的下一个设计交付物,依赖本任务解除的 P0。
- T004(CLAUDE.md 残留 ChatAgent 引用)已在本轮由设计会话顺手修复。
