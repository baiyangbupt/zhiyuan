# 初始方案生成优化器验证（历史会话 + 分数场景，2026-10-20）

范围：只看“方案处理/优化”部分，包含初始方案生成；不看 review 修复动作链。
所有会话仅本地 test DB 操作，逐会话 HEX 备份并恢复，未改生产数据。

## 1. 方法

1. **离线 solver 模拟**：从历史上抽取 10 个会话的 planningState +
   candidatePool，直接喂 `StagedDeterministicPlanSolver`，不连库、不走 service。
2. **初始生成模拟**：选 5 个历史会话（含生产会话），清空 working/ordered/
   initialRecommendation 后调用 `generateInitialPlan`：
   - A：不设置已确认 selectionTarget（旧默认行为）；
   - B：设置 selectionTarget = requiredCount（模拟确认目标场景）。
   记录返回方案形状、selected 集合、`staged initial selection` 日志。
3. 每轮结束后恢复 planningState 原 HEX。

## 2. 离线 solver 结果

| 会话 | 场景 | target | 结果 | candidates | 耗时 |
|---|---|---|---|---|---|
| 900018 | 江西 484 / 专业组 | 80 | ready 80 | 120 | 134ms |
| 900028 | 江西 484 / 专业组 | 80 | ready 80 | 120 | 13ms |
| 900038 | 江西 484 / 专业组 | 80 | ready 80 | 120 | 11ms |
| 900045 | 江西 484 / 专业组 | 45 | ready 45 | 120 | 10ms |
| 900700 | 浙江 575 / 普通专业 | 80 | ready 80 | 120 | 9ms |
| 900016 | 江西 484 / 专业组 | 45 | ready 45 | 120 | 10ms |
| 900047 | 江西 484 / 专业组 | 45 | ready 45 | 117 | 7ms |
| 10041981 | 湖南 475 / 专业组（生产） | 45 | ready 45 | 359 | 14ms |
| 10041983 | 生产 | 80 | blocked: candidate_shortage | 15 | 0ms |
| 10041984 | 广东 499 / 专业组（生产） | 45 | ready 45 | 571 | 35ms |

说明：10041983 的 shell 导出没有独立候选池且内嵌池为空，属于模拟输入不完整，
不是 solver 失败；900040 的 planningState 超出 mysql client packet，未纳入本轮。

## 3. 初始生成模拟（修复前）

5 个会话在“设置 selectionTarget”后仍**没有** `staged initial selection` 日志：

| 会话 | 模式 | selectionTarget | 结果 |
|---|---|---|---|
| 900700 | major | 80 | ordered 80，无 solver 日志 |
| 900045 | majorGroup | 45 | 仍为 44 组，目标被忽略，无 solver 日志 |
| 10041981 | majorGroup（生产） | 45 | 45，无 solver 日志 |
| 10041984 | majorGroup（生产） | 45 | 45，无 solver 日志 |
| 900018 | majorGroup | 80 | 80，无 solver 日志 |

### 根因

`generateInitialPlan` 保存 working plan 时：

```
saveWorkingPlanState
  → syncOrderedPlanWithDraft  // 顺手生成 ordered
  → staleFlags.orderedPlan=false
```

随后 `reorderWorkingPlanInternal → generateOrderedPlan` 看到
“非强制 + ordered 非空 + stale=false”，直接返回，**根本没走到
`enforceSelection`**。所以初始生成的最后一步只是启发式结果的同步，不是
staged solver。

## 4. 修复后初始生成效果

修复：`initial_auto` 模式强制 `generateOrderedPlan(forceRegenerate=true)`，
绕过早返回，让 `enforceSelection` 真正执行。

| 会话 | 无 target | 有 target | solver 结果 | 选择集变化 |
|---|---|---|---|---|
| 900700 | 80 条，无日志 | target 80 | ready selected=80 add=0/remove=0 | set/order 完全一致 |
| 900045 | 44 组，无日志 | target 45 | ready selected=45 add=1/remove=0 | 新增 1 组 |
| 10041981 | 45 组，无日志 | target 45 | ready selected=45 add=0/remove=0 | 完全一致 |
| 10041984 | 45 组，无日志 | target 45 | ready selected=45 add=0/remove=0 | 完全一致 |
| 900018 | 80 组，无日志 | target 80 | ready selected=80 add=0/remove=0 | 完全一致 |

结论：

- **有确认目标时，初始生成现在会真正调用 staged solver**；目标与启发式一致
  的会话保持不变，目标更高的会话（900045 44→45）由 solver 补齐。
- **无确认目标时仍然不跑 solver**：`hasSelectionObjectives` 只认
  selectionTarget/coverage/tier allocation，requiredCount 不会触发。此时初始
  选择仍是旧启发式。这是下一步需要产品拍板的语义缺口。

## 5. 下一步

1. 决定“无确认目标的新会话”是否也应让 solver 主导初始选择：
   - 若应：把 initial target（requiredCount/default 45）显式编译成初始
     objective，并让 `hasSelectionObjectives` 对 initial 路径识别它；
   - 若不应：保留启发式，但把“solver 不参与”作为明确契约，不再宣称初始
     生成全面切换。
2. 用同一批历史会话做“启发式 vs solver”质量对比：coverage、tier 偏差、
   churn、本省保底、utility、耗时。
3. 扩大离线 golden corpus：补 900040、10041983 的完整候选池输入，并固定
   期望 selected/ordered/stageResults。
