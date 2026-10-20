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

## 5. 无目标 initial solver 灰度开关

新增 `planning.initial.solver.enabled`（默认 false）：

- 关闭：保持旧行为；只有已有 selectionTarget/coverage/tier 目标时 solver 参与。
- 打开：`initial_auto` 把 `requiredCount/默认目标` 作为**临时** initial
  target 传给 `enforceSelection`；目标只用于本次求解，不写入
  `constraintState`，不成为 durable 用户目标。

真栈（历史会话，无 confirmed target）：

| 会话 | flag on 结果 | solver 日志 | 选择集 |
|---|---|---|---|
| 900700 | 80 条 | ready selected=80 add=0/remove=0 | 不变 |
| 900045 | 44 组 | ready selected=44 add=0/remove=0 | 不变 |
| 10041981（生产） | 45 组 | ready selected=45 add=0/remove=0 | 不变 |
| 10041984（生产） | 45 组 | ready selected=45 add=0/remove=0 | 不变 |
| 900018 | 80 组 | ready selected=80 add=0/remove=0 | 不变 |

质量对比（flag on，target=requiredCount）：

- 10041981/10041984/900700/900047/900018：solver 选择集与启发式完全一致。
- 900045/900016：启发式分别少 1 组（44/45），solver 补齐到 45；
  900016 为补足发生 7 remove/8 add，unit 数 44→45。
- 结论：flag 打开主要修复“启发式数量不足”，完整方案保持原选择；可先
  在测试环境打开，观察后再决定默认值。

## 6. 内容级核验（不只数量）

对 900016、900045、10041981 逐 unit 核对 school/province/tier/major/ratio：

| 会话 | 启发式 | solver | 内容结论 |
|---|---|---|---|
| 900016 | 44 组 / 117 条 | 45 组 / 170 条；7 remove / 8 add | 引用完整、无重复；但新增含苏区专项与医学限制组，组内专业数最大 29，item 数明显膨胀 |
| 900045 | 44 组 / 127 条 | 45 组 / 140 条；仅 add 1 | 新增华北科技学院第501组（13 个专业），无删除；补齐目标，内容自洽 |
| 10041981（生产） | 45 组 / 153 条 | 完全一致 | tier 13/13/19，ratio 46–99，1 处 ratio 逆序；内容自洽 |

通用检查：

- `contentOkAll=true`：所有选中 unit 的 major volunteerId 都能在候选池找到，
  且 `planSchoolDataId == unitId`；无重复 unit。
- 900016/900045 的候选 ratio 全为 1.0，无法用 ratio 判断冲稳保难度，
  只能验证顺序无 ratio 逆序。
- 900016 的变化说明 solver 目前只按目标/效用选 unit，**没有内容风险护栏**：
  - 新增“苏区专项”组；
  - 新增带色盲/色弱限制的医学组；
  - 单个大组 27–29 个专业，导致 item 数从 117 涨到 170。

结论：数量与引用准确性通过；内容合理性在 900016 这类稀疏/特殊类型数据上
未通过产品级验收。打开 `planning.initial.solver.enabled` 前，至少需要：

1. 风险标签护栏：special_enrollment / cooperative / high_tuition /
   admission_limit 的相对启发式不得增加；
2. 组规模护栏：新增单组专业数/总 item 数相对启发式的上限；
3. 用户意向覆盖：专业、城市、院校意向不能被 solver 改动破坏；
4. 冲稳保 ratio 数据缺失时，不允许把全 1.0 当作有效难度信号。

## 7. 内容护栏落地（initialMode）

`initial_auto` 的 `enforceSelection` 现在带内容护栏，分两层：

**求解前硬约束**（`MutationPolicyDTO.initialContentGuard`）：

1. **风险标签不增加**：special_enrollment / cooperative_program /
   high_tuition / admission_limit，solver 选中数不得高于启发式基线。
   其中 high_tuition 作为新增候选时已被 `compensate-safe` 谓词拦截；
   内容护栏作为第二道防线，并覆盖 current 条目与名称/标签旁路场景。
2. **条目不膨胀**：unit 模式按组内专业数计；允许上限
   `max(5, ceil(baselineItems * 20%))`。
3. **preferred 专业不丢失**：选中 preferred volunteer 数不得低于基线。

约束不可行时返回 `no_change` 并回退启发式初始方案，写
`initial_content_guard` 诊断；求解后的同口径校验保留为兜底。

真栈复跑（initial solver flag on）：

| 会话 | 结果 | 说明 |
|---|---|---|
| 900016 | 回退启发式 44 组 / 117 条 | 内容约束不可行（`objective_set_infeasible`），未引入第 5 个 special |
| 900045 | solver 45 组 / 140 条 | 条目增长 13 ≤ allowance，内容通过 |
| 10041981（生产） | 与启发式一致 45 / 153 | 内容无变化 |

Java 全量：**1480 / 0 / 0 / 10**。

## 8. 9 会话内容矩阵（flag on，无 durable target）

| 会话 | 启发式 → solver | 风险标签 | preferred | 单组最大专业数 | 结果 |
|---|---|---|---|---|---|
| 900016 | 44u/117i → 44u/117i | 不变 | 0 → 0 | 6 | safety 阶段不可行，回退启发式 |
| 900018 | 80u/226i → 不变 | 不变 | 0 → 0 | 6 | 内容一致 |
| 900028 | 80u/226i → 不变 | 不变 | 0 → 0 | 6 | 内容一致 |
| 900038 | 80u/226i → 不变 | 不变 | 0 → 0 | 6 | 内容一致 |
| 900045 | 44u/127i → 不变 | 不变 | 0 → 0 | 6 | 内容一致 |
| 900047 | 45u/136i → 不变 | 不变 | 47 → 47 | 6 | 内容一致 |
| 900700 | 80 items → 不变 | 不变（无风险） | 0 → 0 | 13 | 内容一致 |
| 10041981 | 45u/153i → 不变 | 不变 | 141 → 141 | 6 | 内容一致 |
| 10041984 | 45u/111i → 不变 | 不变 | 104 → 104 | 6 | 内容一致 |

- 所有会话 `contentOkAll=true`，无重复/缺失 unit。
- 8/9 会话 solver 结果与启发式内容完全一致；900016 因内容约束不可行回退，
  没有引入新增风险。
- 风险标签覆盖：special_enrollment、cooperative_program、high_tuition、
  admission_limit 在多个会话中均未增加。
- 矩阵说明：flag on 且无 durable target 时，初始目标来自 requiredCount；
  900045 此前在显式 target=45 时会补 1 组，本矩阵保持 44。
- 900016 回退根因：solver 诊断为 `objective=safety`、
  `保底阶段未证明最优，solverState=INFEASIBLE`。分数 484 →
  `minLocalProtect=2`，而候选池 0 个保档 unit；启发式基线也缺这 2 个保底。
  内容约束不是唯一可疑项，但 fallback 日志现在会带
  `reason/objective/detail`，便于后续区分 safety 与内容约束。

## 9. 下一步

1. 决定“无确认目标的新会话”是否也应让 solver 主导初始选择：
   - 若应：把 initial target（requiredCount/default 45）显式编译成初始
     objective，并让 `hasSelectionObjectives` 对 initial 路径识别它；
   - 若不应：保留启发式，但把“solver 不参与”作为明确契约，不再宣称初始
     生成全面切换。
2. 用同一批历史会话做“启发式 vs solver”质量对比：coverage、tier 偏差、
   churn、本省保底、utility、耗时。
3. 扩大离线 golden corpus：补 900040、10041983 的完整候选池输入，并固定
   期望 selected/ordered/stageResults。
