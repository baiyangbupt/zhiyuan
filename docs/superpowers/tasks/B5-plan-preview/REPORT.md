---
task: B5
status: PARTIAL
executor: zhiyuan-07 (deepseek)
finished_at: 2026-09-21 10:05 +0800
source: docs/superpowers/plans/2026-09-20-codex-domain-and-plan-transactions.md
---

# B5 报告（部分）：完整方案计算、审查与无副作用预览

## 一、结论

**契约层做完了，计算与验证层没做。** 这是目前完成度最低的一项，原因写在第五节：
它的核心是把计算从 11762 行的 `PlanningStateService` 里抽出来，并证明
"预览前后数据库快照不变"——那是一次需要整块时间的重构，不是能在一次推进里
顺手带掉的改动。

**我不打算用"看起来做了"的东西占位**：一个不调用真实计算的 calculator，
比没有 calculator 更容易让人以为预览已经无副作用了。

## 二、交付（契约层）

| 路径 | 变更 |
|---|---|
| `model/dto/planning/FrozenPlanPayloadDTO.java` | 新增：冻结载荷 + 分项摘要 + 分开的两份 trace |
| `model/dto/planning/PlanPreviewDTO.java` | 新增：预览结果 + `ready/infeasible/needs_clarification` |
| `service/biz/PlanPreviewCalculator.java` | 新增：`deepCopy` + 分项摘要 + `payloadDigest` |
| `test/.../PlanPreviewCalculatorTest.java` | 新增，6 条 |

## 三、两条写进契约的语义

**冻结的理由**：用户看到的 diff 与他确认后落库的内容必须是**同一份东西**。
确认时重跑一遍推荐，只要求解器有任何一个非确定性环节（或候选在此期间变过），
落库的就可能不是他确认的那份——而他点的是"确认"，不是"再随机一次"。

**摘要是分项的，不是合并的**：selection 与 ordering 是两次独立求解，
输入不同、产物不同。合并成一个大摘要之后，"到底是目标变了还是候选变了"
就查不出来了。所以 `objectiveDigest` / `candidateDigest` / `profileDigest` 分开存，
`payloadDigest` 由它们 + 求解器版本合成。

**trace 不参与载荷摘要**：trace 是解释，不是产物。算进去会让"内容没变但 trace
变长"被判成载荷变了，于是同一个方案反复触发重新确认。测试里专门钉了这一条。

## 四、验收

```
zhiyuan-server: mvn -o test
# Tests run: 757, Failures: 0, Errors: 0, Skipped: 6 — BUILD SUCCESS
```

## 五、未完成（B5 的主体）

1. **`PlanPreviewService` 没建**，`PlanPreviewCalculator` 目前只有 `deepCopy`
   与摘要计算——**没有 `projectConfirmedGoal` / `seedWorkingSelection` /
   `materializeOrderedPlan` / `freeze`**。也就是说它还不算"计算器"。
2. **"preview 前后数据库快照不变"这条测试没写。** 它是 B5 的**首要**要求，
   也是"预览不写正式表"的全部证据。要写它必须先有 `PlanPreviewService`。
3. **计算抽取没做。** 计划要求把 `buildInitialRecommendationState` /
   `replaceWorkingPlanWithInitialRecommendation` / `buildOrderedItemsFromWorkingPlan` /
   `buildOrderedUnitsFromOrderedItems` 的**纯计算**抽出来，并让旧写入口
   调用抽取后的纯函数（"避免复制两套算法"）。这几个方法现在都是
   11762 行那个类里的私有方法。
4. **计划点名的那处顺序陷阱没验**："不能 selection 后直接对旧/空 ordered 调
   enforceOrdering"。现有代码在 `PlanningStateService:1839` 那条路径上是**对的**
   （从 working 构建 ordered items），但新预览路径是否照做，取决于第 3 项怎么写。
5. **`plan.review` 那部分没做**：复用 `/review/run`（它会保存 reviewState 并推进
   workspaceVersion）并向用户解释"已更新审查结果，志愿内容未变"；
   "审查前后单位集合/顺序不变"这条测试也没写。
6. **MCP 工具 `plan.propose_generate` 与 `tools_planning.py`、inner 端点没建。**

## 六、为什么这项要单独安排

`PlanningStateService` 是 11762 行，本任务要动的是它内部**被多条路径共用**的
私有方法（初始推荐、工作区替换、订单构建）。抽错了的表现不是编译失败，
而是某些路径的排序悄悄变了——而现有测试未必覆盖得到每一条路径。

计划自己也说了这个顾虑（"现有 PlanningStateService 已非常大，新计算/桥接职责
放独立类，必要接入保持小改动"）。所以正确的做法是：**留一整块时间，
以"先把旧写入口切到抽取后的纯函数、确认 757 条测试全绿"为第一个检查点，
再写预览路径**。分两步走，中间那一步必须是绿的。

## 七、证据边界

- 6 条测试只覆盖深复制与摘要计算，**不覆盖任何真实方案计算**。
- 没有任何数据库参与：既没证明预览不写库，也没证明现行写路径会写库。
- `deepCopy` 用 JSON 序列化往返实现：它依赖 `PlanningStateDTO` 能被
  FastJSON 无损往返，这一条**没有单独验证**（字段级往返测试没写）。
