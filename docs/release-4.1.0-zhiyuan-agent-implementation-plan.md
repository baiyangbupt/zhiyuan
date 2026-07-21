# Release 4.1.0 - Zhiyuan Agent 实施计划

> 状态: M0、M1 已完成；M2 Task 1-5 与 Task 6 离线资产已完成，live final-action 因环境预置失败而未关闭，M3 不启动
> 日期: 2026-07-19
> 基线: Release 4.0.0 / 实施设计 v2.77
> 目标: 扩展 typed 方案目标和确定性联合求解能力，同时保持单 `PlanChangeSpec`、单 Proposal、单 pending、单 command 的原子执行链。

## 1. 版本结论

下一阶段使用 `4.1.0`，不继续作为 `4.0.x` 功能补丁。

原因如下：

- 计划新增用户可见的方案能力，包括冲稳保范围/比例、概率结构、安全垫、复杂 selector 和多级优先。
- `PlanChangeSpec`、后端持久化目标、Proposal dry-run、确定性求解器和 postcondition 都需要扩展。
- 多个当前 preview-only 或 fail-closed 的目标会进入可确认、可执行、可复验状态，属于功能增量，不是兼容性修复。
- 4.0.0 已完成 24 包 final-action 一次性 `178/178`，应冻结为稳定基线；继续把大功能堆进 4.0.0 会模糊发布结论和回归责任。

版本边界：

- `4.0.x` 只处理 4.0.0 已有能力的缺陷、安全问题、兼容性和必要运维修复。
- `4.1.0` 承载本文定义的新目标、新组合和新求解能力。
- 4.1.0 对现有 4.0.0 请求、持久化状态和未完成 pending 保持向后兼容，不以 minor 版本为由破坏已发布协议。
- 本文是 4.1.0 的唯一主计划。实现进度、设计变更、门禁证据和删除台账都更新在本文，不再并行维护内容重复的 roadmap、issue log 和 tracking 文档。

## 2. 4.0.0 基线

### 2.1 已完成能力

4.0.0 当前已经具备：

- 统一 Agent 自主选择 typed 工具，不恢复 3.2.0 中文场景枚举路由。
- 普通偏好默认按硬要求处理；只有用户明确限定“仅供参考/不记录/不调整”才走只读 reference。
- `fill_to_count` 精确总数目标。
- `include / exclude / only_keep` 结构化要求，以及显式 `min_count` 覆盖。
- 单档位最低数量。
- 冲、稳、保三档完整 `exact_counts` 精确配额。
- 一条 `rank_before + within_tier` 硬优先规则。
- exact review issue + strategy 的 review Proposal 选择和确认执行。
- 一个复合诉求进入一个 `PlanChangeSpec`、一个 Proposal、一个 pending 和一个 planning command。
- pending CAS、operationId 幂等、planning version guard、事务回滚和 typed postcondition。
- 当前方案查询 `query_plan`、名单发现 `discover_options`、方向分析 `explore_topic` 和实体比较 `compare_entities` 的基本边界。

### 2.2 发布验证基线

- 24 包 clone-backed final-action 一次性 `178/178`，`warnings=[]`、`failures=[]`。
- 13 包 live 完整初跑 `227/231`，四个原红 step 隔离复验 `4/4`；发布证据不合并成一次虚假的 `231/231`。
- 完整 Python `1719 passed, 42 skipped`。
- 完整 Maven 最近同轮基线 `593 tests, 0 failures/errors, 4 skipped`。
- 44 个 examples JSON、Python 编译和 `git diff --check` 通过。
- 验收后 MySQL、SQLite、候选副本清零，binlog 仅保留活动文件。

4.1.0 的每个纵切都必须保持上述已有行为。任何新能力导致 4.0.0 final-action 资产回退，都不能进入下一个里程碑。

### 2.3 当前实现限制

| 能力 | 4.0.0 状态 | 4.1.0 需要解决的问题 |
| --- | --- | --- |
| 冲稳保配额 | 只支持三档完整 `exact_counts` | 最大值、范围和比例无法表达 |
| 覆盖求解 | `CoverageSelectionSolver` 只求最低覆盖 | 不支持上界、范围、比例和多类约束联合可行性 |
| 配额复合 | 配额与普通 requirements/priority/repair 多数互斥 | 需要一次求解并统一 postcondition |
| 优先规则 | `PriorityRuleSupport` 明确只允许一条，执行器只读取第一条 | 需要确定的多级优先语义和冲突校验 |
| 概率结构 | `rebalance_tier_ratio`、`fill_probability_gap`、`add_safety_items` 仍有 preview-only 路径 | 需要 typed 目标、可执行 Proposal 和执行后验证 |
| selector | 平铺 domain/key/values，跨领域 OR 组合表达有限 | 需要有界的布尔 selector，不回退中文规则 |
| 联合执行 | 多个 enforcer 可能按顺序处理不同目标 | 必须防止后执行目标破坏前一个目标 |
| 只读决策支持 | 查询/发现边界已建立 | 比较结果仍需补齐可报性、录取率、推荐分、当前位置和来源证据 |
| Live 稳定性 | 完整初跑仍有一次性模型路由/运行波动 | 需要重复门禁和结构化重试，不继续堆 prompt 例句 |

## 3. 不变原则

### 3.1 所有用户要求默认是硬要求

- 不新增 soft preference 执行通道。
- “倾向、重点关注、优先考虑、也可以考虑”在表达报考或方案要求时，默认进入硬要求或硬优先规则。
- 纯疑问和明确 reference 保持只读，不写入目标。
- 候选不足时返回 infeasible/blocked，不自动把硬要求降级为排序加分。

### 3.2 一次逻辑变更只有一条原子链

```text
用户完整诉求
  -> 1 个 PlanChangeSpec
  -> 1 个 canonical objective set
  -> 1 个 Proposal dry-run
  -> 1 个 pending
  -> 1 个 planning command
  -> 1 份统一 postcondition report
```

- 一个 spec 可以包含多个目标和多条动作，但不能拆成多张确认卡。
- 任一硬目标不可满足时，整个 Proposal blocked；不允许成功一部分、失败一部分。
- active pending 的 append/replace/hold 关系先完成裁决，最终仍只能有一个权威 pending。

### 3.3 模型负责语义，后端负责确定性

- Agent 负责把当前上下文理解成 typed spec，不负责枚举候选或计算替换动作。
- 后端负责 canonical 校验、事实读取、可行性求解、动作生成、持久化和 postcondition。
- 不从 `raw_user_text` 扫描中文关键字补字段、猜数量、猜比例或恢复动作。
- prompt 只描述稳定的工具边界和 schema 语义，不累积 case 级执行规则。

### 3.4 Fail closed

- 缺少必要数字、范围、实体类型或数据事实时澄清。
- 求解超过受控复杂度、候选事实不完整、存在 pinned/locked 冲突或 postcondition 无法证明时 blocked。
- blocked/no-change 不创建假 pending，不输出“确认后执行”的文本承诺。

### 3.5 单一 canonical runtime

- 4.0.0 输入可继续读取，但进入后端后必须归一成同一个 canonical objective set。
- 不长期双写两套目标，不让新旧 solver 同时裁决生产请求。
- 允许在实现阶段做离线 differential benchmark；shadow 不创建 pending、不写状态、不改变回复。
- 新路径通过对应 full gate 后，立即删除已被替代的旧 evaluator/enforcer/guard 和测试资产。

### 3.6 模型 transport 与业务重试边界

- OpenAI/OpenAI-compatible provider 使用独立的 `LLM_CONNECT_TIMEOUT_SECONDS`，默认 `15s`；它只控制 DNS/TCP/TLS 建连预算，不改变模型语义、工具选择、Proposal 或持久化行为。
- 模型请求仍受 Agent direct turn `60s` 和 WebSocket `180s` 外层上限约束；不得为了门禁通过提高业务 turn 上限或放宽 `60s` latency warning。
- 保留 OpenAI SDK 自带的同一 HTTP 请求 transport retry，不在 Agent、runner 或 quality gate 增加整轮 turn/case/package 自动重放。失败 turn 不得复用可能已产生的业务副作用。
- `TimeoutError`、`ModelAPIError` 与业务 assertion 分层记录，但 final-action 同轮退出条件仍是 `warnings=[]`、`failures=[]`；focused 复验只用于定位，不能拼接成 `178/178`。

## 4. 目标架构

### 4.1 写路径

```text
Zhiyuan Agent
  -> PlanChangeSpec schema validation
  -> Agent-side canonical naming / explicit-field validation
  -> backend UserGoal request
  -> PlanningObjectiveCompiler
  -> CanonicalPlanningObjectiveSet
  -> DeterministicPlanSolver
  -> Proposal + diagnostics + postcondition plan
  -> pending freeze(version/digest/proposalId)
  -> confirm command(CAS/operationId/transaction)
  -> apply + persist objectives + refresh
  -> UnifiedPlanPostconditionValidator
```

职责边界：

- `PlanChangeSpec`：承接用户本轮完整目标，不包含候选选择结果。
- `PlanningObjectiveCompiler`：把 4.0/4.1 typed 输入和已确认目标归一成唯一约束模型。
- `DeterministicPlanSolver`：在同一候选事实快照上选择最终集合和顺序，返回可证明的可行或不可行结果。
- Proposal：冻结 solver 输入摘要、目标、动作、诊断和 source version，不在确认时重新猜语义。
- pending：只保存唯一可确认对象和 digest。
- command：确认后的唯一执行账本，继续复用 CAS、幂等和事务。
- postcondition：验证最终集合、顺序、持久化目标和刷新结果；任一失败整笔回滚。

### 4.2 只读路径

```text
用户只读问题
  -> query_plan / discover_options / explore_topic / compare_entities
  -> typed evidence result
  -> grounded reply
```

- 只读路径不创建 `PlanChangeSpec`、Proposal 或 pending。
- compare 可以读取候选池和正式方案证据，但不能借机生成调整动作。
- 用户从比较转为明确调整时，下一轮重新进入写路径。

### 4.3 Canonical objective set

后端内部统一模型至少包含：

- `selectionTarget`：最终总数和计数模式。
- `eligibilityConstraints`：exclude/only-keep、选科、体检、学费等不可违反的过滤条件。
- `coverageConstraints`：至少命中 N 个的硬覆盖。
- `tierAllocationConstraints`：冲稳保 exact、min/max/range 或 ratio 解析结果。
- `riskStructureConstraints`：概率阈值、相邻概率缺口或安全垫数量。
- `orderingConstraints`：一条或多条有明确优先级的同档排序规则。
- `lockedEntities`：不可移出或不可移动对象。
- `sourceEvidence`：用户显式目标、已确认状态或 exact review check 的来源。

这是一种后端内部 canonical 结构，不要求把所有字段直接暴露给模型。

## 5. PlanChangeSpec 4.1 契约

### 5.1 顶层结构

```json
{
  "selection_goal": {},
  "tier_quota_goal": {},
  "requirements": [],
  "selector_expression": {},
  "priority_rules": [],
  "risk_structure_goal": {},
  "repair_goal": {}
}
```

约束：

- 继续沿用现有 `tier_quota_goal` 名称，不再新增一套并行的 `tier_distribution_goal`。
- `requirements` 保持 4.0.0 向后兼容；复杂 selector 开放后，两者统一编译成 canonical selector。
- `repair_goal` 仍引用 exact review issue + strategy；不能和 `risk_structure_goal` 对同一风险重复建目标。
- 每个里程碑只开放通过组合矩阵验证的字段组合，其他组合继续 fail closed。

### 5.2 冲稳保 exact、范围和最大值

4.0.0 兼容输入：

```json
{
  "tier_quota_goal": {
    "type": "exact_counts",
    "sprint_count": 9,
    "stable_count": 17,
    "protect_count": 19
  }
}
```

M2 确认的范围输入：

```json
{
  "tier_quota_goal": {
    "type": "count_ranges",
    "update_mode": "patch",
    "sprint": {"min_count": 8, "max_count": 12},
    "stable": {"min_count": 16, "max_count": 20},
    "protect": {"min_count": 18, "max_count": 22}
  }
}
```

最大值是范围的特例：

```json
{
  "tier_quota_goal": {
    "type": "count_ranges",
    "update_mode": "patch",
    "sprint": {"max_count": 10}
  }
}
```

校验规则：

- 4.1.0 的 `count_ranges` 必须显式给出 `update_mode=patch|replace`；`patch` 是对已确认 range 的字段级增量，`replace` 是明确替换整个历史冲稳保目标。
- `patch` 遇到已确认 `count_ranges` 时只覆盖本轮显式提供的 bound，未提及的历史 bound 继续作为硬要求；当前没有历史配额时，以未表达 bound 的有效域 `0..targetCount` 创建新 range。
- `replace` 不继承历史 bound，未提供的档位使用 `0..targetCount`；Proposal 必须展示被移除的历史目标，不能静默丢弃。
- `patch` 遇到历史 `exact_counts` 或 `ratios` 时 M2 返回 typed blocked；不能自动降级历史硬目标，也不在 M2 偷开 `exact + range` 或 `ratio + range` 联合策略。用户明确同意替换后才能重提 `update_mode=replace`。
- 用户没有表达的 bound 不由 Agent 伪造成显式要求；后端求解时使用 `0..targetCount` 的有效域。
- 每个显式 bound 必须是非负整数，且 `min_count <= max_count`。
- 三档有效最小值之和必须不大于总数，有效最大值之和必须不小于总数。
- `exact_counts` 继续保持三个数量完整且合计等于最终总数；它本身就是完整目标，`update_mode` 若出现只能是 `replace`。为兼容 4.0.0，字段缺省也确定映射为完整替换，不改变旧请求和旧 pending 的冻结语义。
- 最大值是硬上界而不是贴近目标；当前实际数量已在上界内时不主动补到上界。
- Proposal 必须同时展示变更前有效目标、本轮 patch/replace、变更后有效目标、解析后的总数和 dry-run 实际数量。

### 5.3 冲稳保比例

M2 确认的比例输入：

```json
{
  "tier_quota_goal": {
    "type": "ratios",
    "update_mode": "replace",
    "sprint_weight": 3,
    "stable_weight": 4,
    "protect_weight": 3
  }
}
```

比例规则：

- `ratios` 是三个 weight 完整表达的目标，M2 只接受 `update_mode=replace`，不把它与历史 range/exact 隐式叠加。
- 三个 weight 必须完整、非负且合计大于 0。
- 后端以三个 weight 的最大公约数约分得到 canonical weights；`30:40:30` 与 `3:4:3` 语义相同，不能产生无意义的目标变更或不同 digest。用户提交值与 canonical weights 分层保留，不能只存舍入后的整数配额。
- 比例必须基于冻结的最终总数解析；没有 `selection_goal` 时冻结当前正式方案总数。
- 后端使用 largest-remainder 方法解析为三档整数 exact counts。
- 小数余数相同时使用固定 canonical tier order `sprint -> stable -> protect` 保证可重放；tie-break 顺序和解析结果必须进入 Proposal，用户在确认前可以看到最终整数配额。
- pending 冻结解析后的 exact counts，确认时不因候选池顺序或模型措辞重新舍入。
- 比例确认后继续作为持久硬目标；以后用户只改变最终总数时，在新的 Proposal 中按 canonical weights 重新解析并冻结新 counts。历史 exact 与新总数不一致时 blocked，不能把 exact 自动改成比例或范围。
- 用户只说“保底多一点”或“冲少一些”但没有可确定比例/范围时，不猜默认值；若当前 review 有 exact issue + ready strategy，可转入 `repair_goal`，否则澄清。

### 5.3.1 历史目标与历史实际结构

M2 同时考虑两类历史，但不混淆语义：

- 已确认的 `tier_quota_goal` 是历史硬目标。只有 typed `patch` 可以在同类型 range 内增量修改，或由用户明确授权 `replace`；后端不能因为新目标更容易求解而自动放宽旧目标。
- 当前正式方案的实际冲稳保数量是结构基线，不是新增用户要求，也不进入 soft preference。它只在所有硬目标都满足的可行解之间决定最小变动结果。
- 最终总数不变时，当前实际数量直接作为结构基线；总数变化时，先按当前三档占比用受 bounds 限制的 largest-remainder 投影到新总数，余数 tie-break 仍为 `sprint -> stable -> protect`。
- 求解器先最小化项目移出/补入，再在相同 churn 下最小化相对结构基线的档位数量偏移，最后按稳定 candidate identity 决定唯一结果。候选事实导致结构基线不可达时可以在硬范围内偏离，不能把结构基线误当成 exact 配额而产生假 blocked。
- 当前方案不存在或三档总数全为零时不猜默认结构；range 只按用户硬 bounds 和稳定候选顺序求解，ratio/exact 仍按各自确定目标求解。

### 5.4 概率结构与安全垫

用户明确数值目标草案：

```json
{
  "risk_structure_goal": {
    "type": "probability_gap",
    "scope": "global",
    "max_adjacent_gap_points": 15
  }
}
```

```json
{
  "risk_structure_goal": {
    "type": "safety_floor",
    "min_admission_probability": 70,
    "min_count": 8
  }
}
```

边界：

- 概率统一使用 percentage point，不混用 `0.7` 与 `70`。
- `probability_gap` 只在录取率排序方向和 scope 明确时执行。
- `safety_floor` 的阈值和数量必须来自用户显式目标或 exact review check，不使用隐式默认安全线。
- 候选缺失可靠录取率时 blocked，并返回 structured shortage/unknown-fact diagnostic。
- “把这版调稳点”继续先通过 review Proposal options 选择 exact issue/strategy；模型不能自行生成阈值。
- 现有 `rebalance_tier_ratio`、`fill_probability_gap`、`add_safety_items` 只有在 canonical solver 和 postcondition 接通后，才能从 preview-only 升级为 ready。

### 5.5 复杂 selector

第一版只支持有界表达式，不开放任意深度逻辑树：

```json
{
  "selector_expression": {
    "operator": "all_of",
    "children": [
      {
        "operator": "any_of",
        "children": [
          {"kind": "include", "domain": "region", "key": "province", "values": ["广东"]},
          {"kind": "include", "domain": "region", "key": "province", "values": ["福建"]}
        ]
      },
      {"kind": "include", "domain": "school", "key": "school_nature", "values": ["公办"]}
    ]
  }
}
```

约束：

- 支持顶层 `all_of` 和一层 `any_of` 分组。
- 第一版最多 16 个 leaf、最多两层，不支持任意嵌套和通用 `not`。
- 每个 leaf 必须显式包含 `kind`；排除使用 `kind=exclude`，不使用自由布尔取反。
- 同一 leaf 内 values 是 OR，不同 `all_of` child 是 AND。
- 现有平铺 requirements 统一编译成 `all_of` leaves，runtime 不保留两套 matcher。
- 专业门类、专业类和具体专业继续保留 taxonomy level，不因 selector 归一而降级。

### 5.6 多条和多级 priority

输入数组顺序表示优先级：

```json
{
  "priority_rules": [
    {
      "domain": "region",
      "key": "province",
      "values": ["山东"],
      "ordering_target": "rank_before",
      "scope": "within_tier"
    },
    {
      "domain": "school",
      "key": "school_nature",
      "values": ["公办"],
      "ordering_target": "rank_before",
      "scope": "within_tier"
    }
  ]
}
```

执行语义：

- 数组从前到后是 lexicographic precedence，不再增加平行的 `priority_level` 字段。
- 同一实体命中多条规则时，以最高优先级规则分组；同组内保持原相对顺序。
- 第一版最多 4 条规则，只允许 `rank_before + within_tier`。
- priority 不自动增加候选、不跨冲稳保档、不覆盖 pinned position。
- 固定位置和跨档移动仍属于 plan action，不伪装成 priority。
- postcondition 为每条规则返回 matched count、inversion count、persisted 和 satisfied，并验证高优先级没有被低优先级破坏。

## 6. 确定性联合求解

### 6.1 Solver 输入

- 冻结的 planning version 和 volunteer model。
- 当前正式方案的 item/unit 事实。
- 当前候选池及 canonical school/major/region/tier/probability 属性。
- 已确认硬要求和 hard planning objectives。
- 本轮 canonical objective set。
- pinned/locked/banned 对象。
- 稳定候选顺序和 identity key。

### 6.2 求解优先级

所有用户目标仍是硬目标。下面的顺序只表示求解和诊断次序，不表示可以牺牲前面的硬约束：

1. 校验事实完整性和 volunteer model。
2. 应用 exclude/only-keep、政策和 eligibility 硬过滤。
3. 保留 pinned/locked 对象，发现冲突立即 infeasible。
4. 满足最终总数。
5. 同时满足 coverage、tier allocation 和 risk structure 约束。
6. 在所有可行解中先最小化方案 churn，即最少移出/补入并尽量保持当前集合。
7. 对 range 等存在多个档位数量可行解的目标，在相同 churn 下最小化相对历史实际结构基线的档位数量偏移；该基线不参与硬可行性判定。
8. 继续按固定 tier order、stable candidate identity 和当前顺序打破同值结果，再执行多级 within-tier ordering。
9. 生成确定动作、目标状态变更、diagnostics 和完整 postcondition plan。

不允许先由 quota enforcer 改集合、再由 coverage enforcer 改回来，也不允许 priority 执行后破坏 tier 或 risk 目标。

### 6.3 Solver 选择 ADR

ADR-410-001 在 M0 对比：

- 扩展当前有界 DP/branch-and-bound。
- 引入成熟的约束求解库，例如 OR-Tools CP-SAT。

ADR 使用固定 4.0.0 fixture snapshot，至少覆盖 400 个候选、48 个目标项目、16 个 selector leaf、三档 bounds、4 条 priority 和概率约束。选择标准：

- 同输入稳定生成相同 proposal digest 和动作顺序。
- 能返回可解释 infeasible reason，不只返回空结果。
- 满足现有部署的 Java 版本、包体、native dependency 和启动约束。
- 本地 dry-run 性能相对 4.0.0 基线没有不可接受回退。
- 不需要在生产长期保留新旧两套 solver。

2026-07-17 已完成第一轮可重复 benchmark，决定 M1 采用 ojAlgo `48.4.2` 的 pure-Java MIP 作为 canonical selection solver 候选，不扩展 4.0 的 coverage-only DP，也不引入 OR-Tools 9.8：

- 现有 `CoverageSelectionSolver` 在 400 候选、16 个 coverage constraint 的 synthetic fixture 上触发 `20,000` state limit；即使未超限，它也只返回最小覆盖集合，不能表达目标总数、冲稳保上界、pinned、硬排除和最小 churn。
- test-scope ojAlgo 在同一 400 候选、48 个目标、16 个 coverage、三档 bounds、pinned 和硬排除组成的 20 个联合约束下返回 `OPTIMAL`；首次求解约 `298.0ms`，最终 48 个、churn 6 个，连续三次 selection digest 都为 `698bc6658c8cfd5da4fffdfefa02c95861e3c5237c574e9ea4d2d751f757421b`。
- 120 候选/12 约束 fixture 返回 `OPTIMAL`，首次约 `13.06ms`；pinned 冲档数量超过上限的 fixture 在约 `3.1ms` 返回 `INFEASIBLE`。
- ojAlgo `48.4.2` 编译目标为 Java 8、MIT license、单个 pure-Java jar 约 `1.7MiB`，test dependency tree 没有额外 solver runtime。
- OR-Tools `9.8.3296` 同样支持 Java 8，但主 POM 默认拉取 Linux/macOS/Windows、x86-64/aarch64 五个平台 native runtime；单个 macOS/Linux x86-64 jar 已约 `13.7/17.2MiB`，还依赖 JNA/protobuf。当前 400 变量规模没有证据证明这部分部署复杂度是必要的。

M0 中 ojAlgo 仍为 test scope，不进入生产包。M1 只有在 canonical objective、确定性系数、time/state limit、infeasible diagnostic 和 4.0 differential test 完成后才提升为 runtime dependency；若 M1 的真实 fixture benchmark 明显超过预算，重新打开 ADR，而不是保留两个生产 solver。

证据：

- `zhiyuan-server/src/test/resources/release-4.1.0/plan-solver-adr-cases.json`
- `zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/PlanSolver410AdrBenchmarkTest.java`
- `zhiyuan-agent/examples/plan_change_spec_410_contract.py`
- `zhiyuan-agent/examples/plan_change_spec_410_golden.json`
- `zhiyuan-agent/examples/release_410_m0_baseline_manifest.json`

### 6.4 Solver 输出

```text
status: ready | no_change | blocked
selectedEntityIds
orderedEntityIds
removeEntityIds
addEntityIds
replacementPairs
objectiveResults[]
shortages[]
conflicts[]
solverVersion
inputDigest
```

- `ready` 必须有完整可重放动作和 postcondition plan。
- solver 的选集 `no_change` 只表示无需移动方案项目；Proposal builder 还必须比较变更前后持久化目标。
- 方案和持久化目标都语义等价时才是最终 `no_change`，不创建 pending。
- 方案无需移动但新增或修改了硬目标时，最终 Proposal 仍为 `ready`，明确显示“方案项目不变，仅更新冲稳保约束”，确认后通过同一个 pending/command 原子持久化。
- `blocked` 必须包含 typed reason，例如 `tier_max_infeasible`、`probability_fact_missing`、`selector_candidate_shortage`、`pinned_conflict` 或 `solver_complexity_limit`。

## 7. 组合开放矩阵

| 组合 | 4.0.0 | 4.1.0 目标 | 计划里程碑 |
| --- | --- | --- | --- |
| fill-to-count + include/exclude/only-keep + 1 priority | 已开放 | 保持兼容 | M1 回归保护 |
| exact tier counts + fill-to-count | 已开放 | 纳入 canonical solver | M1-M2 |
| count ranges/max + fill-to-count | 未开放 | 开放 | M2 |
| tier ratios + fill-to-count | 未开放 | 开放 | M2 |
| confirmed count ranges + 同类型 range patch | 未开放 | 字段级继承历史硬 bound | M2 |
| exact/ratio 历史目标 + range patch | 未开放 | typed blocked；明确 replace 后只保留新目标 | M2 边界 |
| exact + range 或 ratio + range 同时生效 | 未开放 | 不开放，禁止隐式目标栈 | 后续版本 |
| 4.0 已确认 exact + coverage/单 priority 存量状态 | 可由分轮确认形成 | 兼容读取、regenerate 和 postcondition；禁止新请求创建或修改该组合 | M2 兼容边界 |
| tier allocation + flat requirements | 未开放 | 开放 | M3 |
| tier allocation + 多级 priority | 未开放 | 开放 | M3/M5 |
| tier allocation + selector expression | 未开放 | 开放有界组合 | M5 |
| probability goal + requirements | 未开放 | 开放具备完整概率事实的组合 | M4 |
| exact review repair + requirements | 未开放 | 先只开放能编译成同一 objective set 的策略 | M4 |
| 多个 repair issue 同时执行 | 未开放 | 4.1.0 不开放 | 后续版本 |
| priority 跨档移动 | 未开放 | 4.1.0 不开放 | 保持 plan action 边界 |
| 固定位置 + 结构性选集重算 | 有冲突保护 | 4.1.0 不自动解锁或移动 pinned | 保持 blocked |
| 任意深度 selector 布尔树 | 未开放 | 4.1.0 不开放 | 后续版本 |
| 模糊“更稳/多一点”无 review 数值事实 | 只读/澄清 | 不猜默认值 | 持续 fail closed |

开放某个单项不等于自动开放它与所有其他目标的组合。每个组合必须有独立 contract、solver、postcondition 和 final-action case。

## 8. 只读决策支持工作流

4.1.0 不恢复独立的“院校推荐 Agent”或“专业推荐 Agent”。统一 Agent 继续使用现有 typed 工具：

- 当前正式方案中的事实、数量、位置和命中情况：`query_plan`。
- 院校/专业目录、当前可报候选和推荐名单：`discover_options`。
- 地域、职业或方向适配分析：`explore_topic`。
- 两到五个院校、专业或方向的对比：`compare_entities`。

4.1.0 为 `compare_entities` 和推荐模式补充统一 evidence contract：

- canonical entity identity 和 taxonomy level。
- 当前考生是否可报、缺少哪些前置条件。
- 录取率/录取概率及数据口径。
- 推荐分和影响维度。
- 当前方案是否存在、所在档位和位置。
- 候选池来源、planning version 和数据时间。
- 无法比较的字段必须明确标为 unknown，不能用模型常识补齐当前考生事实。

“上海的有哪些”保持现有省略问法边界：上下文没有实体类型和数据范围时调用 `clarify_request(discovery_scope)`；上下文明确后直接进入对应 query/discovery，不调用泛方向分析。

## 9. 状态、兼容和升级

### 9.1 4.0.0 状态兼容

- 现有 `exact_counts`、coverage requirements 和单 priority 状态继续可读、可 regenerate、可 post-validate。
- 4.1.0 compiler 将旧状态归一成 canonical objective set，不要求一次性离线重写全部 session JSON。
- 新状态增加 schema/version 标识和 solver version，便于回滚和诊断。
- 4.1.0 不删除 4.0.0 API 字段；旧 `exact_counts` 调用方不传新字段时行为不变。`count_ranges/ratios` 属于 4.1 新类型，按各自契约强制校验 `update_mode`，不能用“兼容旧调用方”绕过新类型校验。

### 9.2 Active pending

- 升级前创建的 4.0.0 pending，若 planning version 和 digest 仍有效，4.1.0 必须能够确认或取消。
- 4.1.0 不在读取旧 pending 时悄悄升级目标或重新选择候选。
- 新目标的 pending 必须记录 canonical objective digest、solver version 和 resolved counts/bounds。
- 回滚到 4.0.x 时，4.0.x 不得错误执行无法理解的 4.1.0 pending；部署方案需在写入新目标前完成服务版本一致性检查。

### 9.3 持久化

- 优先扩展 planning state JSON DTO，不为每种新目标增加独立数据库表。
- request delta、确认后的有效 typed goal、解析上下文和冻结结果必须使用不同 DTO/字段表达，不能继续让一个 exact-only `TierQuotaGoalDTO` 同时承担输入、canonical、持久化和 postcondition 四种职责。
- 确认后的有效 typed goal 保存合并后的显式 range bounds 或 canonical ratio weights；解析上下文保存 `targetCount`、effective bounds、resolution method 和 tie-break order；冻结结果保存 resolved counts、objective digest 和 solver version。
- ratio 同时保留用户提交 weights 和约分后的 canonical weights，但语义等价判断与 digest 使用 canonical weights；不能只保存最终三个整数后丢失比例语义。
- range patch 的持久状态保存合并后的有效硬目标，不依赖后续 regenerate 重放历史对话或扫描 `raw_user_text`。
- complex selector 和 risk structure 使用独立 typed objective，不编码成若干伪 coverage requirement。
- regenerate 与 apply 使用同一 compiler/solver，不维护两套目标解释。
- apply 必须在同一事务内完成冻结选集应用、有效目标持久化、regenerate/refresh 和统一 postcondition；任一步失败都恢复旧正式方案与旧目标。

## 10. 实施里程碑

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| D0 | 版本、范围、架构原则和实施计划落档 | 已完成 |
| M0 | 基线冻结、schema/solver ADR、fixture 与 benchmark | 已完成（2026-07-18） |
| M1 | Canonical objective compiler + solver 基座，无新用户行为 | 已完成（2026-07-19） |
| M2 | 冲稳保 count ranges/max/ratios 纵切 | 实施中；Task 1-4 后端闭环已完成，Task 5 Agent 契约待开始 |
| M3 | tier allocation + requirements + priority 联合求解 | 待开始 |
| M4 | 概率缺口、安全垫和结构 review Proposal 可执行化 | 待开始 |
| M5 | 有界复杂 selector + 多条/多级 priority | 待开始 |
| M6 | 院校/专业对比 grounding + live 路由稳定性 | 待开始 |
| M7 | 4.1.0 全量发布门禁、清理和发布文档 | 待开始 |

### 10.1 M0 - 基线与 ADR

交付：

- 冻结 4.0.0 的 24 final-action、13 live、核心 planning state 和候选池 fixture 清单。
- 输出 `PlanChangeSpec 4.1` schema golden，不接生产路径。
- 完成 solver 选择 ADR 和 benchmark。
- 定义 canonical objective、solver result、diagnostic 和 postcondition DTO。
- 建立 4.0 输入到 canonical objective 的 differential test。

退出条件：

- 4.0.0 final-action `178/178` 可重复。
- 同一 fixture 重复编译/求解得到相同 digest。
- ADR 明确依赖、性能、复杂度上限和删除旧 solver 的策略。
- 没有新增业务语义、工具副作用或持久化写入；允许按 §3.6 收紧模型 transport 的确定配置边界。

当前证据：

- `PlanChangeSpec 4.1` 离线 contract golden `19/19`，覆盖 4.0 exact 兼容和 4.1 range/max/ratio/selector/priority/risk 草案；canonical digest 绑定上下文目标总数。
- M0 contract/manifest/differential unit `6/6`；manifest 与 gate 源码的 24 final-action、13 live 文件顺序及 `178/231` step 数一致。
- session 16 的两个已跟踪候选大文件只记录 path/size/SHA-256，不复制到测试目录。
- solver ADR benchmark 已通过，结果见 §6.3。
- transport hardening 已按 TDD 完成：OpenAI/OpenAI-compatible 使用独立 `LLM_CONNECT_TIMEOUT_SECONDS=15` 建连预算，非法非正值 fail fast，Anthropic 路径不变；SDK request retry、Agent `60s`、runner `180s` 和严格门禁断言均未放宽。
- transport 变更后 fresh 完整自动化为 Python `1733 passed, 42 skipped in 4.60s`、Maven `595 tests, 0 failures/errors, 4 skipped`；46 个 Agent examples JSON 和 1 个 server ADR fixture JSON（合计 47 个）可解析，Python 编译和 `git diff --check` 通过。
- 最终有效门禁 `/private/tmp/zhiyuan_410_m0_final_action_gate_clean_13` 一次串行运行 24 包，独立 JSON 聚合和 manifest 对账均为 `178/178`，`warnings=[]`、`failures=[]`，包名、包数和每包 step 数全部匹配冻结清单。
- 前一轮 clean_12 为 `177/178`、零 warning，唯一红 step 是首模型把用户显式 `9/17/18` 改为 `9/17/19`；工具与后端只收到错误 typed spec。原 case 随后清洁复验 `3/3`，clean_13 同一原始断言也通过。focused 结果仅用于定位，不与完整门禁相加。
- 历史失败已归并为三类：provider 建连预算不足、模型生成/read 长尾、首模型 typed 参数漂移。M0 只修复可确定的 transport 配置缺陷；不增加整轮 turn/case/package 重试、中文 case 规则、raw-text 字段恢复、超时放宽或断言豁免。typed 字段来源证据和 live 重复稳定性继续作为 4.1 后续里程碑内容。
- 最终清理删除 MySQL `command 52 / pending 79 / extra 287 / message 2121 / behavior 704 / freshness 94 / integration 0 / session 94`，八表复查均为 `0`；SQLite 删除 `99` 行并 `VACUUM`，候选副本删除 `247` 个，复查均为 `0`。
- 旧 M0 metrics 删除 48 个路径，只保留 clean_13 的 24 份最终 JSON。MySQL 通过 `FLUSH BINARY LOGS` 和 `PURGE BINARY LOGS TO 'binlog.000548'` 清除 `binlog.000515-000547` 共 33 个封存文件，仅保留 `198B` 活动文件；可用空间约 `22GiB -> 58GiB`。隔离 Agent、Backend 和 Rank 服务均已停止。
- M0 的 schema、ADR、fixture、benchmark、严格全量门禁、最终清理和 fresh 自动化复验全部完成，退出条件已满足。M1 现在可以进入实现，但本轮尚未启动 M1 生产路径。

#### 10.1.1 M0 transport hardening 实施计划

目标：把 Pydantic AI/OpenAI 默认 `5s` connect budget 提升为独立可配置的 `15s`，不改变 read/turn/WebSocket 上限和业务执行语义。

文件边界：

- `zhiyuan-agent/app/config.py`：新增 `LLMConfig.connect_timeout_seconds: float = 15.0`，非正数配置 fail fast。
- `zhiyuan-agent/app/llm/client.py`：OpenAI 与 OpenAI-compatible provider 创建后，把 SDK 默认 request timeout 替换为 `httpx.Timeout(600, connect=config.connect_timeout_seconds)`；provider 继续拥有并关闭原有 HTTP client。Anthropic 路径不改。
- `zhiyuan-agent/.env.example`：公开 `LLM_CONNECT_TIMEOUT_SECONDS=15`，不写真实密钥。
- `zhiyuan-agent/tests/unit/test_llm_client.py`：覆盖默认值、非法值、OpenAI/OpenAI-compatible timeout 注入和 Anthropic 不受影响。

TDD 步骤：

- [x] 先新增配置与 provider timeout 断言，运行 `pytest tests/unit/test_llm_client.py -q`，确认因字段/注入缺失而失败。
- [x] 最小实现配置校验与 OpenAI provider timeout 注入；不创建自定义 turn retry、runner retry 或新 HTTP client 生命周期。
- [x] 运行 `pytest tests/unit/test_llm_client.py -q`、完整 Python、完整 Maven、JSON parse、compileall 和 `git diff --check`。
- [x] 以新 transport 配置重启隔离 Agent，复验 clean_6/7/8 对应 focused case。
- [x] 重新执行 24 包 final-action；只有同轮 `178/178`、`warnings=[]`、`failures=[]` 才关闭 M0。
- [x] 门禁后清理测试八表、SQLite、候选副本、无效 metrics 和封存 binlog，只保留活动 binlog。

### 10.2 M1 - Canonical compiler 与 solver 基座

交付：

- 新增 `PlanningObjectiveCompiler` 和 `DeterministicPlanSolver` 接口。
- 先只承接 4.0.0 已开放的 fill、coverage、exact quota 和单 priority。
- Proposal、apply、regenerate 和 postcondition 都消费同一 canonical result。
- 通过离线 differential 验证后 hard cut 生产主路径。

退出条件：

- 4.0.0 现有 final-action 行为、动作集合、持久化和 postcondition 全部不回退。
- 不存在同一请求由新旧 solver 共同裁决。
- hard cut 后删除被替代的生产 runtime evaluator；历史文档和必要迁移 reader 可以保留，但不得以“暂时保险”为由长期保留双裁决路径。

#### 10.2.1 M1 文件边界与 TDD 执行清单

M1 只迁移 4.0.0 已开放语义，不开放 `count_ranges`、`ratios`、risk goal、complex selector、多条 priority 或 tier quota 与 requirements/priority 的新组合。`tier_quota_composite_not_supported` 在 M3 对应组合门禁通过前继续 fail closed。

Canonical contract：

- `model/dto/planning/CanonicalPlanningObjectiveSetDTO.java`：后端唯一目标结构；包含 schema version、count mode、target count、eligibility、coverage、exact tier allocation、单 priority、source version 和稳定 objective digest。普通用户偏好不进入 soft 字段，继续按硬要求编译。
- `model/dto/planning/PlanSolverInputDTO.java`：冻结候选事实、current/locked/eligible、稳定顺序、tier 和 objective match，不包含用户原文。
- `model/dto/planning/PlanSolverResultDTO.java`：统一返回 `ready/no_change/blocked`、选集、顺序、增删集、objective result、typed diagnostic、solver version、input digest、duration 和复杂度计数。
- `service/biz/PlanningObjectiveCompiler.java`：把 4.0 request、已确认 `HardConstraintsDTO`、coverage、exact quota 和单 priority 归一为上述 canonical set；同语义输入必须得到相同 digest，不能通过 raw text 恢复字段。
- `service/biz/DeterministicPlanSolver.java` 与 `OjalgoDeterministicPlanSolver.java`：一个生产 solver 接口和一个 ojAlgo `48.4.2` 实现；总数、coverage、exact tier、locked、eligibility 和最小 churn 一次求解，单 priority 只影响同档稳定顺序。

执行顺序：

- [x] RED 1：新增 `PlanningObjectiveCompilerTest`，覆盖 field/value 归一、requirements 重排的稳定 digest、4.0 persisted state 兼容、exact quota 不转 synthetic coverage、单 priority 顺序保留、unsupported 组合 fail closed；已确认因 compiler/DTO 不存在而 testCompile 失败。
- [x] GREEN 1：最小实现 canonical DTO/compiler；compiler `5/5`，连同 coverage/quota/priority focused 回归合计 `21/21`，未接 Proposal 或用户可见路径。
- [x] RED 2：新增 `OjalgoDeterministicPlanSolverTest`，先确认 input/result/interface 缺失导致 testCompile 失败；追加 null/重复 identity 防御用例后确认旧顺序在 canonical sort 阶段抛 NPE。
- [x] GREEN 2：实现 600 candidates/64 coverage/2s budget 的有界 ojAlgo solver和 typed diagnostic；solver `8/8`，compiler、ADR 与旧 enforcer focused 合计 `31/31`。400 候选 ADR 仍为同一 selection digest，最近约 `309ms`；ojAlgo 已提升为 runtime dependency，但尚未接生产 Proposal/apply。
- [x] RED 3：在现有 fill、coverage、exact quota 和单 priority fixture 上增加动作集合及 canonical metadata 断言，先确认 `FixProposalDTO` 缺少合同字段而 testCompile 失败；no-change 追加用例确认旧路径返回 null solver result。
- [x] GREEN 3：`UserGoalProposalBuilder` 的合法 fill/coverage/exact quota/priority ready、数学 blocked 和 no-change 已切到 compiler + ojAlgo solver；builder 对 `CoverageSelectionSolver` 调用为 0，quota dry-run 不再使用 synthetic coverage。compiler/solver/builder focused `71/71`。
- [x] RED 4：新增 canonical metadata mismatch、legacy reader、postcondition metadata 和 Agent pending 透传断言；Java 先因 apply/postcondition DTO 缺字段 testCompile 失败，Agent 先因 `proposal_apply` 缺 digest 返回 KeyError。
- [x] GREEN 4：Proposal response、Agent pending `proposal_apply`、server apply request、command digest 和 postcondition 已透传 objective/input digest 与 solver version；三字段部分缺失或任一 mismatch 均 409，全缺的 4.0 pending 继续走 legacy reader，新 pending 不再按 strategy fallback。Java focused `227 tests`（3 skipped），Agent focused `1/1`。
- [x] RED 5：补齐 legacy provenance、unknown tier/alias 分组、冻结 solverResult 的 apply 与 postcondition 选择/顺序一致性用例，并逐项确认旧实现按预期失败。
- [x] GREEN 5：新增单一 `CanonicalPlanningRuntime` 承接 regenerate/apply/postcondition；生产路径 hard cut 后删除 `CoverageSelectionSolver`、`CoverageObjectiveEnforcer`、`TierQuotaObjectiveEnforcer`、`PriorityObjectiveEnforcer` 和 `TierQuotaSupport.syntheticRequirements/syntheticObjectives`，对应失去生产对象的测试同步删除。apply 只消费服务端重建并校验后的冻结 solverResult，postcondition 对同一选集、顺序和 objective result 完成强校验。
- [x] VERIFY：focused compiler/solver、Proposal、state、pending 与 Agent direct 通过；fresh 完整 Maven、完整 Python、JSON parse、`compileall`、`git diff --check` 和 24 包 final-action 全部通过。修复前 `clean_3` 和失败的 `clean_8` 均不作为最终证据。
- [x] CLEAN：最终门禁后删除 superseded metrics、测试 session/command/pending/extra/message/behavior/freshness/integration、SQLite 行和候选副本；仅用 MySQL `PURGE BINARY LOGS` 清理封存 binlog，并复查活动 binlog、磁盘空间和服务端口。

硬切审计：

- 生产 Proposal、regenerate、apply 和 postcondition 不允许保留 feature flag 双跑或“新 solver 失败再回退旧 solver”。
- 离线 differential 只存在于测试代码，不创建 pending、不写 planning state。
- M1 完成时用 `rg` 审计旧类和 synthetic quota 调用为零；删除对应测试，而不是把已失去生产对象的测试长期保留。
- 旧 4.0 pending 仍按冻结的 4.0 Proposal 执行；新字段 optional，未携带 canonical metadata 的历史 pending 走明确 legacy reader，不被重新编译成 4.1 新语义。

当前证据：

- 独立评审发现的三个阻断项已关闭：legacy 只允许请求与服务端 Proposal 同时全缺三项 canonical metadata；新 Proposal 缺失、部分缺失或任一 mismatch 均拒绝。apply 使用服务端重建并校验后的冻结 solverResult，postcondition 核对 selected/ordered IDs、canonical digest、solver version/input digest 和 objective results；未知 tier fail closed，priority tier alias 统一分组。
- `CanonicalPlanningRuntime` 已接入 regenerate/apply/postcondition，旧 `CoverageSelectionSolver`、三个 objective enforcer 及 synthetic quota helper 的生产引用审计为 0；没有旧 solver fallback、feature flag 双跑或 raw-text 恢复。M3 尚未开放的 `tier_quota_composite_not_supported` 继续保留。
- Agent model-response hook 在工具执行前拒绝缺少旧项 locator 的 replace 调用。`clean_8` 第 20 包暴露另一个边界：常驻 turn context 把当前方案 `冲9/稳17/保19` 与总数一起注入模型，模型在用户只说“补齐到45个”时把当前分布误写成新 `tier_quota_goal`。修复采用上下文最小化，只从常驻摘要移除 tier 分布；planning state 和 `query_plan` 查询能力保持不变，不解析原文、不加短语规则、不丢弃用户显式精确配额。
- 上述上下文修复按 TDD 完成：`test_build_turn_context_injects_core_state` 先因仍出现 `冲12/稳18/保15` 而失败，最小实现后通过；独立真实探针返回“已达到补齐目标，本轮不需要新增”，`followupMessages=0`。显式“冲9、稳17、保19”仍在最终 tier-quota 包中生成单 Proposal/pending/command 并通过 postcondition。
- fresh 自动化为 Maven clean `611 tests, 0 failures/errors, 4 skipped`、Python `1735 passed, 42 skipped`、Agent direct `262 passed, 33 skipped`；46 个 Agent examples JSON 与 1 个 server fixture JSON 共 47 个文件可解析，`compileall`、`git diff --check` 和旧生产引用审计通过。
- 最终有效门禁 `/private/tmp/zhiyuan_410_m1_final_action_gate_clean_9` 一次串行执行 24 包。独立聚合与 `release_410_m0_baseline_manifest.json` 对账为 `178/178`、24 个 green files、包名和逐包 step 数完全匹配，`warnings={}`、`failures={}`；没有 package、case 或 turn 重试。失败的 `clean_8` 已删除，不与 focused 证据拼接。
- 最终清理删除 MySQL `command 52 / pending 79 / extra 287 / message 552 / behavior 176 / freshness 94 / integration 0 / session 94`，八表复查均为 0；主 SQLite 删除 99 行并 `VACUUM`，另两份 SQLite 保持 0；候选副本删除 247 个并复查为 0。clean_9 的 24 份最终 JSON 保留。
- MySQL 仅通过 SQL purge：先清理 `binlog.000560-000610`，测试删除事务触发轮转后再 `PURGE BINARY LOGS TO 'binlog.000612'`；最终只保留活动 `binlog.000612`（198B）。磁盘可用空间约 `12GiB -> 71GiB`，Agent `8000/8039`、Server `8080` 和 Rank `5001` 端口均已停止。M1 退出条件已满足；该门禁结束时 M2/M3 实现尚未开始。

### 10.3 M2 - 配额范围、最大值和比例

设计结论（2026-07-19）：采用 typed patch/replace 与历史实际结构基线分层方案；不采用整体覆盖，也不采用跨类型目标无条件叠加。本文 §5.2、§5.3、§5.3.1、§6.2、§6.4、§7 和 §9.3 是 M2 实现前的权威契约。

从属执行清单：[`docs/superpowers/plans/2026-07-20-zhiyuan-agent-m2-tier-allocation.md`](./superpowers/plans/2026-07-20-zhiyuan-agent-m2-tier-allocation.md)。该清单只负责逐步 TDD 执行，不建立第二套设计、状态或门禁事实源；发现设计变化时必须先回写本文。

2026-07-20 已完成执行清单自检：已覆盖 count ranges/max、ratio、历史目标 patch/replace、历史实际结构次级优化、纯目标更新、真正 no-change、blocked、apply/postcondition/rollback、4.0 exact 兼容和 M3 fail-closed；清单不存在占位标记或占位实现，DTO/字段/方法命名和测试入口完成一致性校对。相关设计说明统一使用中文，代码标识和命令保持原名。

交付：

- `count_ranges`、`ratios` 和显式 `update_mode=patch|replace` Agent schema、后端 request/persisted/canonical DTO、校验和用户展示。
- 同类型 range patch 继承历史硬 bound；跨类型 patch typed blocked；replace Proposal 展示被替换的历史目标。
- ratio weights 约分、largest-remainder resolution、固定 tie-break 和冻结结果；后续总数变更重新解析 ratio，exact 总数冲突保持 blocked。
- 历史实际档位结构投影和 solver 次级目标；最大值已满足时不主动贴近上限。
- range/ratio dry-run、目标状态 diff、pending digest、持久化、regenerate 和专用 postcondition。
- 新 final-action 包覆盖 exact、max-only、range patch/replace、ratio、纯目标状态更新、真正 no-change、跨类型冲突、候选不足、总数冲突和确认回滚。

退出条件：

- 所有成功 case 只有一个 Proposal/pending/command。
- 方案项目不变但目标状态变化的 case 必须确认后持久化；方案与目标都不变的 case 不创建 pending。
- 所有失败 case 无部分持久化、无假 pending。
- apply 或 postcondition 注入失败后，旧方案、旧 tier goal 和 planning version 保持原子一致。
- M3 未开放前，任何新请求创建或修改 tier allocation + requirements/priority/repair 组合都继续整体 fail closed，不能通过忽略已确认目标绕过 guard。4.0 已经存在的 exact + coverage/单 priority 存量状态按 §9.1 兼容读取、regenerate 和 postcondition，但该 grandfathered reader 不得接受新的组合字段，也不得扩展到 range/ratio。
- exact 4.0.0 资产继续全绿。

实施进度（2026-07-20）：

- [x] RED 1：新增 `TierAllocationSupportTest`，覆盖同类型 range patch、replace、跨类型 blocked、比例约分/largest-remainder、语义等价 ratio 和非法 bounds/update mode；`PlanningObjectiveCompilerTest` 增加比例 canonical digest 及双向历史组合 guard，同时保留 4.0 grandfathered `compileConfirmed`。运行 `mvn -q -Dtest=TierAllocationSupportTest,PlanningObjectiveCompilerTest test`，按预期在 `testCompile` 因 `TierCountRangeDTO`、`TierQuotaGoalRequestDTO`、`TierAllocationSupport` 不存在失败。
- [x] GREEN 1：实现 request/persisted/canonical/resolution DTO、统一 `TierAllocationSupport` 和 `PlanningObjectiveCompiler` hard cut；支持 exact/range/ratio canonical 编译、range patch/replace、比例约分与 largest-remainder、双向 M3 组合 guard、持久化等价判断和冻结 resolution metadata，但尚未开放 Proposal/Agent 用户路径。2026-07-20 运行 `mvn -DskipTests test-compile` 成功；`mvn -Dtest=TierAllocationSupportTest,PlanningObjectiveCompilerTest test` 为 `22/22`；`mvn -Dtest=TierQuotaSupportTest,UserGoalProposalBuilderTest test` 为 `60/60`，均无 failure/error/skip。
- [x] RED 2：新增 `TierStructureProjectionTest` 和 solver range 矩阵，覆盖 max-only/no-change、min-only、完整 bounds、候选容量不足、locked 超上界、ratio exact bounds、transport 顺序稳定、历史 anchor 不可达和 `tier_range` objective result。运行 `mvn -q -Dtest=TierStructureProjectionTest,OjalgoDeterministicPlanSolverTest test`，按预期在 `testCompile` 因 `TierStructureProjection`、`historicalTierAnchor` 和 `resolvedTierCounts` 不存在失败。
- [x] GREEN 2：增加有界历史结构投影和 solver 二级结构偏移目标；档位约束统一改为 min/max，保留 exact diagnostics，solver 升级为 `ojalgo-48.4.2-m2`，runtime 配额总数 hard cut 到 canonical `targetCount`。2026-07-20 运行 Task 1+2 组合回归 `118/118`；400-candidate ADR fixture 本轮 `OPTIMAL`、约 `310.25ms`、selection digest 保持 `698bc6658c8cfd5da4fffdfefa02c95861e3c5237c574e9ea4d2d751f757421b`，低于 2 秒上限。
- [x] RED 3：在 `UserGoalProposalBuilderTest` 增加纯目标更新 ready、真正 no-change info、range replace 前后信封、ratio submitted/canonical/resolved、实际 selected tier dry-run、跨类型 patch blocked 和 tier capacity diagnostic；按预期在 `testCompile` 因 `TierQuotaChangeDTO`/`FixProposalDTO.tierQuotaChange` 不存在失败。
- [x] GREEN 3：增加权威 `TierQuotaChangeDTO`，Proposal 状态改为同时比较 solver 方案变化与持久化目标变化；range/ratio 统一经 compiler/support，pure objective update 保持空 actions 但可确认，真正语义等价返回 info，blocked 不可确认。2026-07-20 运行 `mvn -Dtest=UserGoalProposalBuilderTest,PlanningObjectiveCompilerTest,OjalgoDeterministicPlanSolverTest test` 为 `91/91`，无 failure/error/skip。
- [x] RED 4：增加 range/ratio 持久化、旧 exact JSON、45 -> 50 ratio 重解析、exact 总数冲突、range regenerate、postcondition 成功/失败和 command 成功写入边界矩阵。随后补充三个缺口用例并逐项观察失败：range 已保存实际 counts 后被误判 `stateChanged=true`；resolution digest 被修改后 `isPersisted` 仍返回 true；range 冻结 counts 不一致时仍返回 true。
- [x] GREEN 4：`PlanningStateService` 只持久化权威 `TierQuotaChangeDTO.effectiveGoal/resolution`；新增 `UnifiedPlanPostconditionValidator` 统一验证 exact/range/ratio、实际档位数量、持久目标、冻结 resolution 和 canonical metadata，command 只负责事务顺序且在 validator 通过后才写 succeeded。状态变更比较与持久化完整性比较已分层：range 语义比较忽略 solver 实际解，postcondition 则严格比较 frozen counts、objective digest 和 solver version。
- [x] VERIFY 4：运行 `mvn -q -Dtest=TierAllocationSupportTest,PlanningStateServiceTest,PendingPlanningCommandBizServiceTest,UnifiedPlanPostconditionValidatorTest,CanonicalPlanningRuntimeTest test`，退出码 0；共 `265 tests`、`0 failures/errors`、`3 skipped`。以 `RUN_M2_ROLLBACK_INTEGRATION=1` 运行真实 Spring/MySQL `PendingPlanningCommandRollbackIntegrationTest` 为 `1/1`，validator 在 apply 后注入 `40906` 时 planning JSON、version、selected IDs、tier goal/resolution 均恢复执行前值，command 未 succeeded、pending 保持 applying；finally 对隔离 session/planningState/pending/command 四类行逐项断言为 0。
- [x] CLEAN 4：删除 `PendingPlanningCommandBizService` 中已被 validator 接管的约 470 行旧 postcondition 代码；迁移全部档位 canonical/legacy exact 职责后删除 `TierQuotaSupport.java` 和 `TierQuotaSupportTest.java`。`rg -n "TierQuotaSupport|verifyPlanChangePostcondition|syntheticRequirements|syntheticObjectives" zhiyuan-server/src/main zhiyuan-server/src/test` 为零匹配，`git diff --check` 通过。
- [x] RED 5：增加 exact/range/ratio 归一、pending 分层冻结、非 ready Proposal、M3 组合 guard 和稳定 prompt 边界矩阵，观察新类型仍被 exact-only 逻辑拒绝或冻结。确认结果补充类型化用例后，range/ratio 均稳定失败为“冲稳保精确配额”；未知类型用例稳定失败为旧 `only_exact_counts_supported` 并误报 exact 字段缺失。
- [x] GREEN 5：Agent 公开 `tier_quota_goal` 扩展为 exact/range/ratio 与 patch/replace；Python 只归一结构化请求和校验 exact 合计，不合并历史 range、不约分/舍入 ratio、不从 `raw_user_text` 恢复业务字段。pending 分别冻结 snake-case 请求 delta、camelCase 后端请求和 Proposal 权威 effective goal/resolution；确认成功文案按 postcondition 类型显示精确配额、数量范围或比例。
- [x] VERIFY 5：运行 `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_release_410_m0_contract.py tests/unit/test_zhiyuan_agent_direct.py -q`，最终结果 `290 passed, 33 skipped`。`test_release_410_plan_change_contract.py` 按 Task 6 边界尚未创建，不在本步骤提前加入。
- [x] CLEAN 5：删除过时错误码 `only_exact_counts_supported`，未知类型统一以 `tier_quota_type_invalid` fail closed；删除旧 exact prompt 场景例句并保留 M3 组合 guard。没有增加中文话术路由、文本恢复、Agent 侧比例解析或历史 bounds 合并。
- [x] RED 6：把演进中的 PlanChangeSpec/golden/normalizer 断言从冻结 M0 测试迁入 `test_release_410_plan_change_contract.py`。新测试按预期出现 6 个失败：schema 不接受 `update_mode`、API 不接受 `context_tier_goal`、ratio 未约分、golden 仍为 M0；M2 对话资产/gate 测试另按预期分别失败为文件不存在和缺少 `M2_FINAL_ACTION_CASE_FILES`。
- [x] GREEN 6：reference contract 升级为 `4.1.0-m2`，请求 delta 与持久化 context 分型；contextless range patch 只输出未解析请求增量，同类型历史 patch 才合并 effective goal，跨类型 patch 返回 `tier_patch_type_mismatch`，ratio 同时保留 submitted weights 和 GCD canonical weights。golden 扩为 26 个；新增独立 `8 cases / 21 steps` M2 包和 `m2-final-action` mode，冻结 24 包及 M0 manifest 未修改。
- [x] VERIFY 6 OFFLINE：contract runner 输出 `26/26`、`failures=[]`；M0/演进 contract/quality-gate 静态组合 `28 passed`；受控 JSON 解析和 M2 gate dry-run 通过。
- [ ] VERIFY 6 LIVE：首次结果 `0/8` 为环境无效运行，根因是 runner 默认后端误用 `18290` 且 MySQL clone 未传本地密码。修复环境后于 2026-07-20 重新完整运行同一 `8 cases / 21 steps` 包，metrics 仍写入 `/private/tmp/zhiyuan_410_m2_tier_allocation_gate.json`；本轮服务、MySQL、源 session 16、24 条 extra-data 和候选资产预检均通过，结果为 `7/21`，`failedSteps=14`，`failedByReason={content:11, backend:6, tool:1}`，已经排除环境失败。
  - 首因一：Agent 公开 schema 仍把 exact/range/ratio 放在一个 `total=False` 混合 TypedDict 中。真实 tool args 证明模型把 `3:4:3` 计算成 exact counts、把“至少45”改成 exact `45/0/0`，并给纯 ratio 注入 `requirements` 或无数字 `fill_to_count`；因此不是 solver 或 postcondition 误算。
  - 首因二：range patch 的后端 effective goal 正确，但模型把历史未修改 bounds 一并写回请求，导致 `plan_change_spec` 不再是最小 request delta。修复必须以 Proposal 权威 requested goal 冻结 delta，不能从 `raw_user_text` 恢复字段，也不能在 Agent 侧合并历史 bounds。
  - 测试资产问题：源候选实际有 `514` 个冲刺候选，原“冲刺至少45个应容量不足”假设不成立；ratio 持久化 exact-equals 断言未考虑 DTO 合法 null 字段；纯目标更新虽完整 unit DTO 因刷新变化，但 source/target 的 45 个 `unitId` 序列一致，业务选集和顺序没有 churn。
  - 纠偏设计：把三类 quota 改成 discriminator typed union 并在 schema 中明确“不得跨类型换算”；对可纠正的 typed 复合/总数冲突只允许一次 ModelRetry；pending delta 使用 Proposal requested goal；runner 支持数组字段投影后以 `unitId` 序列断言无 churn；把证伪的容量 case 改成确定性 range-total infeasible blocked case。禁止新增中文话术路由、raw-text parser、Agent 比例舍入和 package/case/turn 结果拼接。
- [x] VERIFY 7 AUTOMATION：最终聚焦 Java `362 tests`、`0 failures/errors`、`3 skipped`，Python `296 passed, 33 skipped`；最终全量 Java `655 tests`、`0 failures/errors`、`5 skipped`，Python `1763 passed, 42 skipped`；真实事务回滚集成 `1/1`，退出码 0。
- [x] CLEAN 7：`compileall`、51 个受控 JSON、`git diff --check` 通过；旧 support/synthetic/postcondition 零匹配且 M3 guard 仍存在。清理失败 live 运行复制的 24 个 `9914201-9914208` 候选文件并停止应用端口；MySQL chat session/command/pending/extra data 四类残留行和 Agent SQLite history 均为 `0`，磁盘可用约 `83GiB`。MySQL 只有活动 `binlog.000612`（约 150KB），无旧 binlog 可 purge，未删除活动日志。通用 Proposal 的 exact-only 文案已按 exact/range/ratio 类型化并增加回归。

### 10.4 M3 - 联合求解

交付：

- tier allocation 与 include/exclude/only-keep、coverage min 和 priority 的联合求解。
- 明确 pinned/locked、候选不足和目标冲突 diagnostics。
- 一个统一 postcondition 同时验证总数、筛选、覆盖、配额和顺序。
- 删除 Python `tier_quota_composite_not_supported` 等已被验证组合的旧 guard；未开放组合继续保留 typed fail-closed。

退出条件：

- 组合 case 不拆 pending，不出现后执行目标破坏前目标。
- apply 失败能够事务回滚并保持旧正式方案及目标不变。
- regenerate 后仍满足全部已确认目标。

### 10.5 M4 - 概率结构与安全垫

交付：

- `probability_gap`、`safety_floor` typed goal。
- exact review issue/strategy 到 canonical risk constraint 的编译。
- 将具备确定事实与 postcondition 的 `fill_probability_gap`、`add_safety_items`、`rebalance_tier_ratio` 从 preview-only 升级为 ready。
- 概率事实缺失、断层无候选、满容量替换和专业组模式的 typed diagnostics。

退出条件：

- 不使用模型生成概率阈值。
- Proposal 展示调整前后概率结构和替换对象。
- postcondition 能证明 gap/floor/ratio 改善或精确满足；不能证明时回滚。

### 10.6 M5 - Complex selector 与多级 priority

交付：

- 有界 selector expression compiler、matcher、持久化和 postcondition。
- 现有 flat requirements 到 canonical selector 的兼容编译。
- 最多 4 条 priority 的 lexicographic stable ordering。
- selector + tier allocation + priority 的开放组合 case。

退出条件：

- 任意运行时业务 matcher 只消费 canonical selector。
- 多条优先规则的顺序、冲突、pinned 边界和 inversion 结果可解释。
- 任意深度表达、跨档 priority 和固定位置组合继续 blocked。

### 10.7 M6 - 只读决策支持与模型稳定性

交付：

- compare/discover 的 grounded evidence contract。
- 院校、专业、候选和当前方案四类来源一致展示。
- 对首工具无效参数、unsupported filter 和结构化路由冲突使用 schema/ModelRetry 收口，不增加 case 级中文提示词。
- 对 4.0.0 曾波动 case 做重复 live gate。

退出条件：

- 只读 case 无 pending、无方案副作用。
- 关键 route case 在清洁 session 下连续重复通过。
- 未知数据不被回复包装成已有事实。

### 10.8 M7 - Release gate 与清理

交付：

- 完整 Python、Maven、JSON、编译和 diff 门禁。
- 24 包 4.0.0 final-action 基线 + 全部 4.1.0 新 final-action 包一次性运行。
- 13 包 4.0.0 live + 4.1.0 新 live 包一次性运行。
- 失败完整初跑与 focused 复验分层记录，不相加制造全绿。
- 清理测试 session、pending/command、SQLite、候选副本、过期 metrics 和封存 binlog。
- 停止隔离服务，写入 4.1.0 发布结论和剩余边界。

退出条件：

- final-action 一次性 `warnings=[]`、`failures=[]`。
- live 至少有一次清洁环境完整全绿；曾有模型波动的核心 case 需要额外重复通过。
- 数据库、SQLite 和候选副本复查为 0。
- binlog 只通过 MySQL SQL purge，保留当前活动文件。

## 11. 测试策略

### 11.1 Agent contract

- 每种新目标的合法、缺字段、未知字段、边界值和组合矩阵。
- 不从 raw text 补数字、比例、阈值或 selector。
- active pending append/replace/hold 的单 pending 约束。
- 只读、reference 和 mutation 的硬切。

### 11.2 Solver 与后端

- exact/range/ratio 数学可行性。
- 同候选满足多个 coverage/selector 的共享选择。
- min/max、总数和 locked 冲突。
- major 与 majorGroup 两种 count mode。
- 选集最小 churn 和稳定 tie-break。
- 同输入重复执行结果一致。
- state limit/timeout 返回 blocked，不返回部分解。

### 11.3 Apply 与事务

- pending owner、CAS、claim lease、operationId 和重复确认。
- planning version 漂移。
- Proposal rebuild 与冻结事实一致。
- persist objectives、apply actions、ordered/review refresh 和 postcondition 同事务。
- 任一 postcondition 失败完整回滚。

### 11.4 回归资产

- 4.0.0 24 包 final-action 是永久基线，不能因新版本删减。
- 新能力每个纵切至少包含 ready、no-change、blocked、confirm/apply 和 rollback case。
- live 资产覆盖自然表达，不按实现字段直译全部话术。
- 测试断言以首工具、typed payload、pending/command 状态和最终后端事实为准，不只检查回复包含文本。

### 11.5 性能与稳定性

- M0 记录 compile、solver、Proposal dry-run、apply 和完整对话的基线分布。
- 每个里程碑比较 p50/p95/max，不接受未解释的持续回退。
- solver 超时和复杂度上限独立于 WebSocket 180 秒总上限。
- release gate 串行执行 clone-backed final-action，避免并发 clone/cleanup 资源竞争制造假失败。
- transport 单测必须证明默认 connect timeout 为 `15s`、非法非正值 fail fast、OpenAI 与 OpenAI-compatible 共用同一配置，Anthropic 路径不被误改。
- 真实门禁必须继续把 transport failure 计红；connect timeout 调整只允许一个请求有更充分的 TLS 建连时间，不得重放整个用户 turn。

## 12. 可观测性

新增结构化事件至少包含：

- `planChangeSpecVersion`
- `objectiveTypes`
- `constraintCount`
- `selectorLeafCount`
- `solverVersion`
- `solverStatus`
- `solverDurationMs`
- `solverStateCount` 或等价复杂度指标
- `infeasibleReasonCodes`
- `selectedCount / removedCount / addedCount / reorderedCount`
- `proposalId / pendingId / commandId`
- `postconditionSatisfied`

事件不记录不必要的完整用户原文和大体积候选快照。诊断使用 canonical id、reason code 和摘要。

## 13. 旧实现删除台账

删除原则：替代路径的 focused、完整 final-action 和回滚测试全部通过后，在同一里程碑删除旧实现，不积累长期兼容分支。

| 旧实现/限制 | 删除或替换时机 | 前置证据 |
| --- | --- | --- |
| `CoverageSelectionSolver` 只支持最低覆盖的实现 | M1 canonical solver hard cut 后删除或改为唯一通用 solver | 4.0 differential + 24 包 final-action |
| `TierQuotaSupport.syntheticRequirements` 将 exact quota 临时伪装成 coverage | M1/M2 solver 原生支持 tier allocation 后删除 | exact/range/ratio solver 与 postcondition 全绿 |
| Python `tier_quota_composite_not_supported` 对已开放组合的整体拦截 | M3 按组合逐项删除 | 对应组合 final-action 全绿 |
| `PriorityRuleSupport` 的 `rules.size() > 1` 限制和执行器只读第一条 | M5 多级 priority hard cut 后删除 | multi-priority unit/final-action 全绿 |
| 已实现结构策略仍列在 `PREVIEW_ONLY_STRATEGIES` | M4 每个策略 ready/apply/postcondition 完成后逐项移除 | ready/no-change/blocked/rollback 全绿 |
| flat requirement 和复杂 selector 的重复 matcher | M5 canonical selector hard cut 后删除重复 matcher | 4.0 flat + 4.1 selector differential |
| 被后续运行覆盖的失败 metrics、临时 fixture 和候选副本 | 每个里程碑验收结束立即删除 | 文档已引用有效 metrics |

不得删除：

- 4.0.0 对外字段和读取兼容。
- 4.0.0 24 包 final-action 基线资产。
- 仍未开放组合的 typed fail-closed guard。
- pending CAS、幂等、version guard、事务和 postcondition 安全层。

## 14. 风险与控制

| 风险 | 控制 |
| --- | --- |
| 约束组合导致状态空间爆炸 | 有界 selector/priority、solver state/time limit、ADR benchmark、blocked diagnostic |
| 新 enforcer 顺序覆盖旧目标 | 所有目标先编译成 canonical objective set，一次求解和一次统一 postcondition |
| 比例舍入引发不确定结果 | largest-remainder + 固定 tie-break + pending 冻结 resolved counts |
| 概率字段缺失或口径不一致 | canonical percentage point、typed unknown、事实不足 blocked |
| 模型继续把模糊表达补成数字 | schema required fields、tool validation/ModelRetry、禁止 raw text recovery |
| 默认 `5s` connect timeout 将短暂 DNS/TCP/TLS 抖动放大为整轮失败 | 独立 `15s` connect timeout；保持 `60s` turn 上限和严格 full gate，不增加整轮重试 |
| 4.0 pending 升级后失效 | 保留旧 spec reader，不重算旧 pending，版本一致性部署 |
| 新旧 solver 长期并存 | 只允许离线 differential，生产 hard cut 后删除旧裁决路径 |
| 测试通过但留下大量状态和 binlog | 每个纵切都有清理步骤，binlog 只用 MySQL SQL purge |
| 文档再次分散 | 本文作为 4.1.0 唯一主计划，其他文档只链接，不重复维护 |

## 15. 4.1.0 完成定义

4.1.0 只有同时满足以下条件才可宣布完成：

- M0-M7 的退出条件全部满足，不以部分 schema、preview-only 或 focused 结果代替完整可执行闭环和发布门禁。
- 4.0.0 已有能力和 24 包 final-action 无回退。
- 每个新目标都有 typed input、canonical validation、deterministic dry-run、单 pending/command、持久化、regenerate 和专用 postcondition。
- 已开放组合由统一 solver 一次求解，不存在顺序 enforcer 相互覆盖。
- 普通偏好仍按硬要求处理，没有新增 soft preference runtime。
- 不从中文原话恢复业务字段，不恢复 3.2.0 场景规则罗列。
- 只读比较和发现有当前考生事实 grounding，不生成副作用。
- full gate、失败分层、清理和有效 metrics 全部落档。
- 被替代的旧实现、旧 guard、重复 matcher、无效测试资产和中间 metrics 已按删除台账清理。

## 16. 后续启动顺序

M0、M1 已关闭，M2 设计契约和从属 TDD 执行计划已完成。下一步只进入 M2 实现，不并行启动 M3-M7：

1. 按从属清单先运行 Task 1 RED，明确 request/persisted/canonical DTO hard cut 和旧 exact reader 兼容边界。
2. 按 Task 1-7 依次完成 patch/replace、ready/纯目标更新/no-change/blocked/confirm/apply/rollback，任一 RED 未观察或前一纵切未 GREEN 时不得跳步。
3. M2 完整自动化、final-action、清理和文档退出条件满足后，才进入 M3 联合求解。
4. M3 前继续保留 `tier_quota_composite_not_supported`，不得提前放开未验证组合。

任何实现中发现的新类型都先回写本文的 schema、组合矩阵和里程碑，再进入代码，避免实现先行后补文档。
