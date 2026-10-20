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
扩展 golden：900501 / 900357 / 9702947 / 900019 / 900023 / 900031 /
10041939 / 10041942 / 900017 / 10041980 / 10041958 全部 ready
（80 或 45 目标，6–137ms）；10041983 因导出候选池为空继续 blocked
（输入问题）。

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

## 5. 无目标 initial solver 开关

`planning.initial.solver.enabled`（2026-10-20 起默认 **true**）：

- 关闭（显式 false）：保持旧行为；只有已有 selectionTarget/coverage/tier
  目标时 solver 参与。
- 打开：`initial_auto` 把 `requiredCount` 作为**临时** initial target 传给
  `enforceSelection`；目标只用于本次求解，不写入 `constraintState`，不成为
  durable 用户目标。
- 会话级灰度：`planning.initial.solver.sessions=10041984,900016`
  （逗号分隔 chatSessionId）；全局显式关闭时只对列出的会话启用。

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
- 结论：flag 打开主要修复“启发式数量不足”，完整方案保持原选择。

2026-10-20 的 16 会话 A/B（同一批会话，组内 MILP 默认 on）：

| 会话 | 启发式 | solver | 结论 |
|---|---|---|---|
| 900016 | 44 组 / 117 条 | 45 组 / 123 条 | 补齐 requiredCount；风险标签不变 |
| 10041984 | 45 组 / 111 条 | 45 组 / 122 条 | preferred 104 不变；高收费标签 18→15 |
| 其余 14 个 | — | — | units/items/档位/preferred/风险全部一致 |

因此将默认值改为 **true**：无确认目标的新会话也由 solver 主导初始选择；
显式 `-Dplanning.initial.solver.enabled=false` 可完整回滚，或配合
`planning.initial.solver.sessions` 只对指定会话灰度。

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

Java 全量：**1652 / 0 / 0 / 12**。

## 8. 16 会话内容矩阵（flag on，无 durable target）

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
| 900019 | 45u/132i → 不变 | 不变 | 0 → 0 | 6 | 内容一致 |
| 900357（610 分） | 45u/121i → 不变 | 不变 | 0 → 0 | 6 | 内容一致 |
| 900501（575 分 major） | 80 items → 不变 | 无风险 | 0 → 0 | 1 | 内容一致 |
| 9702947（630 分） | 45u/130i → 不变 | 不变 | 118 → 118 | 6 | 内容一致 |
| 900017（485 分） | 45u/136i → 不变 | 不变 | 0 → 0 | 6 | 内容一致 |
| 10041958（610 分） | 45u/136i → 不变 | 不变 | 0 → 0 | 6 | 内容一致 |
| 10041980（492 分） | 45u/133i → 不变 | 不变 | 0 → 0 | 6 | 内容一致 |

- 所有会话 `contentOkAll=true`，无重复/缺失 unit。
- 15/16 会话 solver 结果与启发式内容完全一致；900016 因 safety 阶段不可行
  回退，没有引入新增风险。样本覆盖 475–641 分、major 与 majorGroup。
- 风险标签覆盖：special_enrollment、cooperative_program、high_tuition、
  admission_limit 在多个会话中均未增加。
- 矩阵说明：flag on 且无 durable target 时，初始目标来自 requiredCount；
  900045 此前在显式 target=45 时会补 1 组，本矩阵保持 44。
- 900016 回退根因：solver 诊断为 `objective=safety`、
  `保底阶段未证明最优，solverState=INFEASIBLE`。分数 484 →
  `minLocalProtect=2`，而候选池 0 个保档 unit；启发式基线也缺这 2 个保底。
  内容约束不是唯一可疑项，但 fallback 日志现在会带
  `reason/objective/detail`，便于后续区分 safety 与内容约束。

## 9. 优先规则正式进入选择（J5.4，默认开）

开关 `planning.priority.selection.enabled` **默认开启**；显式设为 false 可回滚。

- 关闭：行为回到旧口径，优先规则只影响排序。
- 打开：solver 在 safety 之后增加 `priority` 阶段，最大化
  `priorityMatched` 实体数；之后再进入 churn/档位、utility。
- `MutationPolicyDTO.prioritySelection` 进入 solver inputDigest，便于审计。

历史会话真栈：

| 会话 | 规则 | 启发式匹配 | solver 匹配 | 结果 |
|---|---|---|---|---|
| 10041981 | city=北京 | 0/45 | 0/45 | 无匹配候选，不变 |
| 10041984 | province=北方 15 省 | 4/45 | 11/45 | 优先规则明显生效，45 组 / 122 条 |

内容护栏仍生效：风险标签、条目增长、preferred 丢失仍受约束。
默认已开启；如需回滚：`-Dplanning.priority.selection.enabled=false`，
行为回到“优先规则只影响排序”。

会话级 initial 灰度真栈：`planning.initial.solver.sessions=10041984` 时，
10041984 走 solver（优先匹配 4→11，45 组/122 条）；未列出的 10041981
保持启发式（45 组/153 条）。

## 10. 组内专业帽（J5.4，默认开）

`planning.group-inner.major-cap.enabled` **默认开启**；显式 false 可回滚。

- solver **新增**一个专业组时，组内专业数按
  `candidatePool.requiredMajorCount` 截断；
- 组内专业本身不足 requiredMajorCount 时**全部保留**，不补造、不截断；
- 选择口径与初始推荐 `buildPlanningUnit` 一致：先保留一个 safety major
  （admissionRatio ≥ 组 enrollRatio），再按 preferred / 未来发展 / 意向 /
  录取率 / 分数补足；
- 已有单元不做裁剪，只影响本次新增。

真栈 900045（显式 target 45，requiredMajorCount=6）：

| 配置 | units | items | 单组最大专业数 |
|---|---|---|---|
| cap 关（此前） | 45 | 140 | 13 |
| cap 开 | 45 | 133 | 6 |

说明：这是“组内专业帽”落地，不是把组内专业变量直接加进 MILP；
solver 仍以 unit 为选择实体。

## 11. 组内选择两阶段：基础切片（2026-10-20）

按两阶段方案先落基础设施，不改变现有求解行为：

- `PlanSolverResultDTO.selectedMajorIdsByUnit`：unitId → 实际选中的专业
  volunteerId 列表；
- `CanonicalPlanningRuntime.applySelection`：有 map 时按 map 精确物化，
  缺失专业 fail closed；无 map 时回退现有组内帽/全部专业；
- `InnerMajorPlanBuilder`：按 group-inner 口径为每个 unit 预处理计划专业，
  组内不足 requiredMajorCount 时全保留；
- 当前 solver 尚未写入 map，因此行为不变，为阶段 2 预留。

### 阶段 2 第一片：planned majors 进入求解输入

- `CandidateSnapshotBuilder` 在 group-inner 开关 `on` 时生成
  `plannedCandidates`，representative、utility、priorityMatched 使用计划专业；
- solver coverage 使用计划专业；
- 初始内容护栏的风险/条目/preferred 也按计划专业计数；
- solver ready 后写入 `selectedMajorIdsByUnit`；`shadow` 只打差异日志；
- `FrozenSelectionDigest/Guard` 已覆盖 selectedMajorIdsByUnit，旧 frozen
  结果（空 map）保持逐字兼容。

真栈 900045（显式 target 45，`requiredMajorCount=6`）：
**45 组 / 133 条 / 单组最大 6**，与组内帽结果一致。

Java 全量：**1652 / 0 / 0 / 12**。

## 12. 外部修复复核 + 组内 shadow（2026-10-20）

外部补充了审查/冻结链修复：

- review 修复候选生命周期失效；
- reducer/fact integrity 与 repair protection；
- claimed execution / frozen plan replay 守卫；
- 命令失败回滚后持久化；
- frozen review solver objective contract 校验。

合并后全量 Java **1652 / 0 / 0 / 12**。其中对组内有影响的修复：
current unit 的 `plannedCandidates` 改为“当前实际选中的专业”，不再按帽重选；
新增 unit 才使用组内帽/计划。

shadow 真栈 900045（target 45）：

```
group-inner major optimization shadow:
units=45 plannedMajors=133 rawMajors=194
```

结果仍按旧口径物化：45 组 / 133 条 / 单组最大 6，行为不变。

当前结论：**阶段 1 planned input + selectedMajorIdsByUnit 已通；
阶段 2 组内小 MILP 与 coverage/preferred 反馈仍未实现。**

## 13. 组内两阶段 MILP（阶段 2）落地（2026-10-20）

阶段 2 不再只是“帽 + 启发式”，而是每个专业组一个独立的小型 MILP：

- **`UnitMajorSelector`**：`requiredMajorCount` 是等式约束；组内不足时全部保留；
  有安全专业时至少选 1 个；先最大化 preferred 专业数并固定，再最大化组内效用；
  同分用原始顺序稳定平局。效用与全局 solver 同权重：意向 40、质量 25、
  安全 20、未来 10、成本 5（×100 定点，避免整数舍入抹平录取率差异）。
- 单组预算 200ms，不可证明最优/异常时回退 `GroupInnerMajorSelector`，保证可用。
- **`GroupInnerMajorPlanner`** 统一入口：`on` 走 MILP，`off` 走旧启发式；
  组内帽开关关闭时直接全保留，确保 `planning.group-inner.major-cap.enabled=false`
  仍是完整回滚路径。
- **阶段一致性**：阶段一的 `plannedCandidates` 就是阶段二复用的计划；
  `InnerMajorPlanBuilder.build` 不再重选，保证 coverage/preferred/风险基线
  与最终物化使用同一组专业。新增回归覆盖“阶段二复用阶段一计划”。
- **shadow** 现在同时计算旧启发式与新 MILP，只打日志不写结果：
  `units/rawMajors/legacyMajors/plannedMajors/changedUnits`。
- 默认值改为 **on**；显式 `-Dplanning.group-inner.major-optimization.enabled=off`
  回滚，`shadow` 只观察。

### 性能

`UnitMajorSelectorPerformanceTest`：600 个专业组 × 13 个专业、每组选 6 个，
预热后 **315ms**（预算 3s）。单组 200ms 上限只在异常/超大组触发。

### 真栈

| 会话 | 结果 | 组内差异 | 安全/偏好 |
|---|---|---|---|
| 900045（target 45） | 45 组 / 133 条 / 单组最大 6 | 8 个 unit 与旧启发式专业集合不同 | 安全专业 0 缺失，preferred 0 丢失 |
| 10041984（target 45） | 45 组 / 122 条 | 0 个 unit 不同 | 安全/偏好一致 |

说明：900045 的差异集中在大组（如 26 个专业选 6 个），MILP 按效用换掉了
旧启发式只按未来/意向单键排序选中的专业；组内仍保留至少一个安全专业。
10041984 的 preferred 覆盖很高，两种口径结果一致。

Java 全量：**1662 / 0 / 0 / 12**。

## 14. 16 会话矩阵（组内 MILP 默认 on + initial solver）

在同一批历史会话上打开 `planning.initial.solver.enabled`，组内优化使用
默认 on，逐会话生成并恢复 HEX：

| 会话 | units | items | 单组最大 | 结果 |
|---|---|---|---|---|
| 900016 | 45 | 123 | 6 | 补齐到 45；本状态未复现旧 safety 回退 |
| 900018 | 80 | 226 | 6 | 与旧矩阵一致 |
| 900028 | 80 | 226 | 6 | 与旧矩阵一致 |
| 900038 | 80 | 226 | 6 | 与旧矩阵一致 |
| 900045 | 44 | 127 | 6 | 无 durable target，按 requiredCount=44 |
| 900047 | 45 | 136 | 6 | 与旧矩阵一致 |
| 900700 | — | 80 | 13 | major 模式，内容检查通过 |
| 10041981 | 45 | 153 | 6 | 与旧矩阵一致 |
| 10041984 | 45 | 122 | 6 | 与旧矩阵一致 |
| 900019 | 45 | 132 | 6 | 与旧矩阵一致 |
| 900357 | 45 | 121 | 6 | 与旧矩阵一致 |
| 900501 | — | 80 | 1 | major 模式，内容检查通过 |
| 9702947 | 45 | 130 | 6 | 与旧矩阵一致 |
| 900017 | 45 | 136 | 6 | 与旧矩阵一致 |
| 10041958 | 45 | 136 | 6 | 与旧矩阵一致 |
| 10041980 | 45 | 133 | 6 | 与旧矩阵一致 |

- 16/16 `contentOk=true`，无 blocked、无重复 unit、无缺失引用。
- 900016 旧记录的 `safety` 回退没有复现；当前会话状态与旧矩阵快照不同
  （约束目标/计划状态已变化），不能把差异直接归因于组内 MILP。
- 900045 没有 durable target 时仍按 requiredCount=44，而不是显式 45；
  这是“无确认目标”语义缺口的已知表现。
- 本矩阵之后已把 initial solver 默认值改为 **true**；显式 false 或
  会话 allowlist 仍可按上述方式回滚/灰度。

Java 全量：**1668 / 0 / 0 / 12**。

## 15. 下一步

1. 扩大离线 golden corpus：补 900040、10041983 的完整候选池输入，并固定
   期望 selected/ordered/stageResults。
2. 对 900016 / 10041984 这类“补齐或增条”的会话做真实模型多轮
   WS/浏览器验收，确认用户侧卡面与解释一致。
3. J5.5 审查修复按 runbook 继续逐策略放量观测；默认开关仍保持关闭，
   避免与求解器默认切换叠加。
