# 录取率梯度、结构与多样性优化设计（草案）

日期：2026-10-27  
状态：**Phase 1 观测已实现；Phase 2 `soft` 结构阶段 + 有界效用损失已实现并在本地影子/软模式验证，默认仍为 `off`**  
样本：会话 `10042004`（江西物理类 460 分，45 组方案）  
关联：`2026-10-21-plan-quality-and-review-containment-design.md`

## 1. 问题与证据

### 1.1 表面现象

10042004 的 45 组方案中，冲档 13 组里有 7 组 `admissionRatio=1.0`。  
用户观察“旧逻辑从头贪心会堆 1%，新逻辑也有不少 1%”。

### 1.2 数据事实

- 候选池共约 1273 个专业组；冲档约 781 组。
- 冲档中 `admissionRatio=1.0` 约 **470 组，占约 60%**。
- 当前方案冲档 13 组中 1.0 占 7 组，约 54%，与候选池比例接近。
- 1.0 是产品口径的**最低录取率档（1%）**，也就是“相对当前分数很难够到”；但 470 个组完全同值，说明它更像**取整/下限聚合值**，不能区分 0.x% 与 1.x%。展示上应写“≤1%”，不要写成精确的“1% 概率”。
- 当前 45 组中 35/45 为民办，广东 18 组、江苏 12 组；这是无方向、无地域、无学费约束下的通用稿。

### 1.3 当前实现缺口

- `CandidateUtilityScorer` 的 safety 分量使用 `admissionRatio`；当 60% 候选同为 1.0 时，该项几乎没有区分度。
- `StagedDeterministicPlanSolver` 的硬阶段保证安全底线、数量和档位，但没有“同档录取率分布”目标。
- `recalculateOrderedSummary` 的 `gradientOk` 实际等于 `sequenceOk`，只检查冲→稳→保的顺序；`safetyOk` 只检查保底组数量 > 0。
- `PlanQualityEvaluationService` 目前检查档位顺序、数量、数据覆盖，没有检查录取率桶集中、相邻断层、地域/性质多样性。
- 旧贪心和新 solver 都可能出现 1.0 偏多，但根因不同：旧逻辑是顺序填充；新逻辑是数据同值 + 效用项缺少梯度约束。

## 2. 目标与非目标

### 2.1 目标

1. 把 `1.0` 作为**最低录取率档（≤1%）**，保留“很难够到”的含义，但不把它当成精确概率。
2. 在不破坏资格、数量和冲稳保硬结构的前提下，让同档录取率分布更均匀、断层更少。
3. 在用户没有明确地域/学费/性质偏好时，降低单一省份、单一办学性质、单一专业类别的过度集中。
4. 把这些质量项变成可观测、可评估、可解释的 finding，而不是隐藏权重。
5. 最终仍以用户确认的方向、地域、专项、学费、风险偏好为最高优先级；优化不能覆盖硬约束和用户明确选择。

### 2.2 非目标

- 不把 `admissionRatio` 变成录取概率，也不展示伪概率。
- 不改各省志愿槽位和官方冲稳保配额。
- 不因为梯度/多样性硬砍用户明确点名的学校或专业。
- 不恢复旧 review 规则；新规则仍走 `plan-quality-v2.x` 只读评价。
- 不做整案对话重排；普通补齐仍保持当前相对顺序。

## 3. 数据口径设计

### 3.1 保留原始值，增加解释层

候选行保留原始 `admissionRatio` / `schoolEnrollRatio`，不覆盖上游数据；新增派生字段：

- `ratioConfidence`: `computed | clamped | unknown`
- `ratioBucket`: 按档位内的区间桶
- `ratioSource`: 上游字段/算法版本/数据年份

**桶必须与用户看到的录取率同口径**：工作台/质量评价优先展示 `schoolEnrollRatio`，缺失才回退
`admissionRatio`。求解器分桶也必须走同一顺序，否则会出现“求解器按专业组 admissionRatio
认为已限制，用户仍看到大量 1.0”的错位。10042004 的首轮实现就是这个错位。

判定建议：

- 原始值缺失或非有限时标记 `unknown`；1.0 保留“最低档”语义，但大量同值聚集（例如某省冲档 >50% 都是 1.0）时标记 `clamped`，表示它可能是下限/取整。
- 1.0 可以继续参与“低安全”排序；展示为“≤1%”，质量评价不能把它当作精确概率。

### 3.2 历史线与当前计划分开

历史投档线只作为“去年门槛”事实；当前计划的结构来自候选池档位、用户约束和求解器。  
质量评价可同时展示“历史线”和“候选档位”，但不得把二者合成一个概率。

## 4. 优化架构

保持当前的“硬约束 → 结构 → 效用 → 排序”分层，增加一个**结构质量层**：

1. **资格与硬约束**：选科、专项、明确排除、安全底线；不可让步。
2. **目标与档位**：省份总组数、冲/稳/保精确配额、本省保底；不可让步。
3. **结构质量（新增，软目标）**：
   - 同档录取率桶覆盖/集中度；
   - 相邻录取率断层；
   - 地域、办学性质、专业类别多样性；
   - 未知/1.0 项占比上限。
4. **偏好与效用**：用户方向、院校/专业质量、未来发展、学费、录取安全；仍参与，但不再单独吞掉结构质量。
5. **排序与确定性**：首版冲→稳→保；同档按用户可解释质量序；普通补齐保序。
6. **质量评价**：只读 finding，不生成概率，不冒充审查通过。

建议结构质量采用**软约束/惩罚项**，而不是简单硬砍：  
先保证硬约束和档位，再在可行域内最大化“桶覆盖/多样性”，效用作为同层或后一层排序。只有用户明确选择“稳健/不要 1%”类口径时，才把某些上限升级为硬约束。

## 5. 录取率梯度设计

### 5.1 分档桶

按档位分别定义桶，避免跨档比较：

- 冲：`(0,5]`, `(5,15]`, `(15,30]`, `(30,50]`，另设 `unknown/1.0` 桶
- 稳：`(50,60]`, `(60,70]`
- 保：`(70,85]`, `(85,95]`, `(95,100]`

桶边界是产品口径，后续可用分位数替代固定阈值；首版先固定，便于解释和回归。

### 5.2 指标

- `bucketCoverage`: 实际覆盖的桶数 / 可用桶数
- `maxBucketShare`: 单桶最大占比
- `lowBucketShare`: 最低桶（含 unknown/1.0）占比
- `adjacentGap`: 同档相邻条目的录取率差（可看最大值/P90）
- `entropy`: 桶分布熵（越高越分散）

### 5.3 默认约束

示例目标（不是最终拍板）：

- 冲档 13 条：`unknown/1.0` 不超过 4 条；至少覆盖 3 个桶；
- 不允许单桶超过该档 50%；
- 相邻条目录取率差不超过 30–40 个百分点（可按档位调整）；
- 用户选择“更稳”时收紧低桶上限；选择“更冲”时放宽，但仍保留覆盖要求。

### 5.4 与风险偏好的关系

- 默认/稳健：优先减少最低桶集中，保证保底厚度。
- 激进：允许更多低录取率冲档，但必须有梯度覆盖，不能全部堆在同一桶。
- 用户明确点名学校/专业：点名项优先，但质量评价要标出集中/断层。

## 6. 多样性设计

在没有明确地域/性质偏好时，增加软约束：

- 单省组数占比上限（示例：不超过 40%）
- 单一大类/专业类别占比上限
- 公办/民办结构提示；民办占比过高时，质量评价给 warn，并在方案说明中解释学费
- 同校多组限制：同一学校不同组可以保留，但不能靠同校堆满目标

有明确偏好时，用户偏好优先；多样性只作为“是否过度集中”的解释，不做反向硬砍。

## 7. 整体打分与目标层级

建议不把所有因素揉成一个总分，而是保持分层：

1. 硬约束/安全底线：不可交换。
2. 目标/档位：不可交换。
3. 结构质量：桶覆盖、集中度、多样性、未知项占比。
4. 用户偏好与效用：方向、质量、未来发展、学费、安全。
5. 确定性/稳定序。

结构质量与效用之间可以采用两种实现：

- **推荐**：结构质量作为软惩罚项加入同一阶段，但设置上限；避免低质量候选为了“分散”被硬塞。
- 备选：先结构质量、后效用做字典序；仅用于用户明确要求“梯度优先”时。

不建议把 `admissionRatio` 再作为一个“概率权重”重复计入；它已经在安全分量里，重复计权会让 1.0 的噪声放大。

## 8. 质量评价扩展

新增只读 finding（不生成建议、不给概率）：

- `ratio_bucket_concentration`: 某档最低桶/未知桶占比过高
- `ratio_gradient_gap`: 同档相邻条目录取率断层
- `diversity_region_concentration`: 单省占比过高
- `diversity_nature_concentration`: 民办/公办结构过度集中
- `ratio_confidence_unknown`: 大量 1.0/未知值，提示不能当概率

展示措辞：

- “这版冲档有 7/13 落在最低录取率桶，梯度偏集中；不代表录取概率。”
- “候选池大量记录为 1.0，按最低档（≤1%）理解；可能是数据下限/取整，不能当成精确 1%。”

## 9. 预期效果与验收指标

以 10042004 45 组为基准，建议在影子模式对比：

- 结构硬指标不变：45 组、13/13/19、2 个本省保底、每组 ≤6 专业。
- 梯度：冲档最低桶占比从 7/13 降到 ≤4/13；桶覆盖从约 2 个提升到 ≥3 个；最大桶占比 ≤50%。
- 多样性：单省占比从 18/45 降到 ≤40%；民办占比从 35/45 降到 ≤60%（阈值待产品确认）。
- 质量：资格 pass 不下降；用户已确认偏好命中不下降；硬约束违规为 0。
- 性能：45 组求解仍应在现有时间预算内，P95 不显著上升。
- 可解释性：每个变化能追溯到“梯度/多样性”finding，而不是“模型觉得”。
- 确定性：同输入同版本结果稳定。

## 10. 推进顺序

1. **观测层（不改行为）**  
   给候选/计划计算桶、集中度、多样性指标；在质量评价里展示；记录当前基线。
2. **影子模式**  
   对 10042004、10042000、10042003 等样本并行计算“当前方案”和“梯度优化方案”，只读对比，不落库。
3. **软约束灰度**  
   开关控制，先只影响无明确方向/地域的通用稿；用户明确偏好时关闭或降权。
4. **默认启用**  
   验收指标达标后默认开启；保留回退开关。
5. **建议/UI**  
   质量面板展示 finding；只从新 finding 生成建议，不恢复旧 review 建议。

## 11. 风险与待拍板

- 1.0 是精确值还是下限/取整，需要数据侧确认；产品展示先统一为“≤1%”。
- 梯度目标可能降低“院校质量”或“用户偏好命中”；需要影子模式看权衡。
- 多样性硬上限可能与用户明确地域偏好冲突；必须让用户偏好优先。
- 桶边界是产品口径，固定阈值可能不适用所有省份/年份；后续可用分位数。
- 是否允许自动降低冲档数量/改变档位配额：不建议，省份槽位是硬约束。
- “民办占比”是否作为质量项，涉及家庭预算和产品价值判断，需要产品拍板。

## 12. 优化器具体设计

### 12.1 实现位置

优化器改动集中在：

- `CandidateSnapshotBuilder`：给每个 fact 补 `ratioConfidence / ratioBucket`；
- `StagedDeterministicPlanSolver`：新增结构质量阶段/约束；
- `CanonicalPlanningRuntime` / `PlanningObjectiveCompiler`：把策略写入 canonical objectives，进入 digest；
- `PlanQualityEvaluationService`：新增只读 findings；
- `PlanningStateService.recalculateOrderedSummary`：`gradientOk` 不再等于 `sequenceOk`；
- `CandidateUtilityScorer`：不在本轮改变权重，避免与梯度项重复计权。

### 12.2 数据模型

候选 fact 增加只读派生字段（不序列化给 agent/WS）：

```text
ratioRaw: Double              // 原始 admissionRatio
ratioConfidence: computed | clamped | unknown
ratioBucket: String           // 如 sprint_low, sprint_mid, stable_high, protect_top
ratioBucketIndex: Integer     // 档位内 0..n
```

桶边界首版固定：

```text
冲: [0,5], (5,15], (15,30], (30,50], unknown
稳: (50,60], (60,70]
保: (70,85], (85,95], (95,100]
```

`1.0` 大量同值时进入 `unknown/clamped` 桶，不参与精确概率解释。

### 12.3 决策变量与约束

沿用每个候选组的二元变量 `x_i`，新增：

```text
e_{t,b} >= 0   // 档位 t、桶 b 超出上限的个数
c_b in {0,1}   // 桶 b 是否至少选中 1 个
```

约束：

```text
for each tier t, bucket b:
    sum(x_i for i in bucket(t,b)) <= cap_{t,b} + e_{t,b}

for each tier t:
    sum(e_{t,b}) <= structureExcessAllowance

for each bucket b:
    sum(x_i for i in bucket b) >= c_b
    sum(c_b) >= minBucketCoverage
```

默认软约束：

- `cap` 先按示例：冲档 unknown/1.0 ≤ 4；其他桶按目标数量与可用容量分配；
- `structureExcessAllowance` 初始设为 0（先尝试无超额），不可行时按 1、2 递增并记录；
- `minBucketCoverage` 设为 2 或 3（按档位）；**unknown/clamped 桶不计入 coverage**，只单独受限，
  不能拿“覆盖了 unknown 桶”冒充有梯度；
- 用户明确“更稳/不要1%”时把 unknown cap 升级为硬约束；用户明确“更冲/可以多冲”时放宽 cap，但不取消覆盖。

多样性沿用现有 `DiversityPolicyDTO`，增加维度：

```text
province, schoolNature, majorCategory, schoolId
```

约束形式同现有 diversity cap：每组超出 `cap` 的计数进入 `e`，最小化 excess；有明确地域/性质偏好时关闭对应维度或提高 cap。

### 12.4 目标层级（建议）

现有顺序：

```text
safety -> priority -> churn_tier -> utility -> diversity/stable
```

建议改为：

```text
safety -> priority -> churn_tier
  -> structure_quality (梯度+多样性，软/可配置)
  -> utility
  -> stable/determinism
```

理由：

- 安全、档位仍是硬/最高优先；
- 结构质量在效用之前，避免 utility 只按质量把最低桶堆满；
- structure_quality 是**有界软目标**，不允许为了梯度无限牺牲质量；
- utility 仍在结构可行域内选择院校/专业质量；
- stableOrder 只做最终平局，不重新洗牌。

结构阶段伪代码：

```text
model = hard constraints + target + tier + safety
solve safety, fix deficit
solve priority, fix matched
solve churn/tier, fix mixed optimum

add structure variables e/c
structureObjective = w_gradient * sum(e) - w_coverage * sum(c)
solve structure
record structureExcess, coverage

if user policy == enforced:
    add hard caps for unknown bucket
    re-solve structure
fix structure excess <= recorded excess + allowance

solve utility (including preference/quality/safety/future/cost)
solve stable tie-break
```

注意：不要同时把 `admissionRatio` 放进 utility safety 和 structure penalty 两次；structure 只惩罚“分布集中”，safety 仍负责单个候选的安全分。

**有界效用（已实现）**：结构阶段前先求“无结构约束的效用最优值”`U0`，再加
`utility >= U0 * (1 - maxUtilityLossRatio)`（默认 3%）。结构阶段在此下限内最小化桶超额；
若结构阶段无法证明最优，必须同时放松覆盖率约束和效用下限，否则后续 utility 阶段会被
残余约束卡成 blocked。这样避免“为了少一个 1.0 无条件换掉高价值院校”。

**初始方案与 churn（已实现）**：初始方案不是用户已确认方案的增量修订。结构质量开启时，
`initial_auto` 不再把上一版自动方案当作 churn 保留目标（`countAsChurn=false`）；
普通补齐/替换仍保留 churn 语义。初始内容护栏（风险标签/条目数/preferred）不下调，
它会拦住那些“梯度更好但新增限报专业”的组合。

### 12.5 参数与策略版本

新增策略对象（示例）：

```json
{
  "version": "structure-quality-v1",
  "gradient": {
    "mode": "off|observe|soft|enforced",
    "unknownBucketCapRatio": 0.3,
    "minBucketCoverage": 3,
    "maxSingleBucketShare": 0.5
  },
  "diversity": {
    "provinceMaxShare": 0.4,
    "schoolNatureMaxShare": 0.6,
    "majorCategoryMaxShare": 0.5
  },
  "userRisk": "steady|default|aggressive"
}
```

策略版本进入 `CanonicalPlanningObjectiveSetDTO` 和冻结 digest；旧 pending 不含版本时走 `off`，不改变已确认语义。新生成的方案才启用。

### 12.6 与现有 `gradientOk/safetyOk` 的关系

- `gradientOk` 改为：
  - 档位顺序正确；
  - 每档桶覆盖 ≥ 阈值；
  - 最低桶占比 ≤ 阈值；
  - 无超过上限的相邻断层。
- `safetyOk` 改为：
  - 保底组数 > 0；
  - 本省保底 ≥ 规定数量；
  - 保底桶不集中在 unknown/最低桶。
- 质量评价与 summary 使用同一套阈值，避免“summary 说好、quality 说坏”。

### 12.7 失败与降级

- 结构约束不可行时，按 `allowance` 逐级放宽，不直接 blocked；
- 仍不可行时返回 `structure_quality_unavailable` 的明确 diagnostic，继续给用户一个可确认方案（如果硬约束可行），并在质量评价中标记集中/断层；
- 不允许为了结构目标破坏资格、数量、档位、本省保底；
- 用户明确点名/优先的条目不被结构目标删除；结构只能影响未点名选择。

### 12.8 测试与验收

先红后绿：

1. 合成 13 个冲档事实：7 个 1.0、6 个 8/14/22/30/38/46；启用结构策略后 unknown 桶 ≤4，覆盖 ≥3；
2. 硬约束/档位/本省保底与关闭策略时一致；
3. 普通补齐仍保持当前相对顺序，不被结构目标重排；
4. 用户点名学校不被结构删除；
5. 旧 pending 无策略版本时行为不变；
6. 10042004 影子对比：45 组、13/13/19、2 本省保底不变；冲档 1.0 从 7/13 降至 ≤4/13；省份/民办集中度下降；
7. 性能：45 组求解 P95 不超过现有预算的 1.2 倍；
8. 同输入同版本结果稳定。

### 12.9 预期效果（优化器视角）

- 不是“消灭 1.0”，而是把 1.0 作为最低档（≤1%），限制它在同档中的占比，并保留中间梯度；
- 冲档从“低桶堆满”变为覆盖多个录取率区间；
- 民办/单省集中度下降，但用户明确地域/学费偏好时仍以用户为准；
- 录用质量（preference/quality）不因结构目标被系统性拉低；
- 质量评价能解释每一项变化，不引入概率数字。

## 13. Phase 2 实现与 10042004 影子结果

### 13.1 已实现

- `StructureQualityPolicyDTO`：`mode=off|soft|enforced`、unknown/单桶上限、最小桶覆盖、
  `maxUtilityLossRatio`（默认 3%）。
- `CandidateSnapshotBuilder`：按 `schoolEnrollRatio ?? admissionRatio` 计算
  `ratioConfidence/ratioBucket/ratioBucketIndex`，与工作台/质量评价同口径。
- `StagedDeterministicPlanSolver`：
  - 结构阶段在 churn/tier 之后、utility 之前；
  - 每档按目标数量 `floor(target * share)` 设桶上限，excess 计入目标；
  - unknown 桶不计入覆盖；已知桶用 0/1 变量做最小覆盖率；
  - 结构阶段前求效用上限并加 3% 效用下限；
  - 结构阶段失败时同时放松覆盖率/效用下限，不让主链路 blocked；
  - `initial_auto` + 结构开启时关闭 churn；普通补齐保持 churn。
- `PlanningObjectiveCompiler`：策略写入 canonical objectives 和 digest；旧 pending
  （策略为 null）digest 不变。
- `PlanQualityEvaluationService`：桶口径同 `schoolEnrollRatio`；单桶上限按
  “该档已定义桶数”扣除取整下界（13 条分 2 个稳档桶，7/13=54% 是数学下界，不再误报）。
- 首版初始排序新增 `initial_tier_strict_v1`：初始方案同档严格按
  finalScore→ratio→schoolRank 排序，不再把旧方案条目无条件排在新增条目之前；
  普通补齐仍用 `initial_tier_order_v1` 保持当前相对顺序。

### 13.2 10042004（45 组，13/13/19）对比

| 方案 | 冲档最低档（≤1%） | 民办 | 广东 | 备注 |
|---|---:|---:|---:|---|
| `off`（基线） | 7/13 | 35/45 | 18/45 | 质量 finding 报冲档集中 |
| `soft` + 初始关闭 churn + 内容护栏 | 6/13 | 35/45 | 16/45 | 45 组/199 专业；质量仍报 46% > 40% |
| fresh（无 current/无护栏） | 5/13 | 29/45 | 16/45 | 梯度最好，但护栏拒绝 |

fresh 方案的护栏拒绝原因：`admission_limit increased: 3 -> 14`。也就是说，冲档 1.0 占比
还能继续下降，但代价是新增大量“限报”专业组，不能接受。**因此当前 6/13 不是 solver
没找到，而是内容护栏在保护用户。** 把效用损失从 3% 放宽到 10% 后 excess 仍为 4，
说明瓶颈不是效用值，而是护栏/数据，不应继续放宽效用。

### 13.3 结论与下一步

- 1.0 是最低录取率档（≤1%），不是精确的 1% 概率；提升空间受候选中“已知且无风险”
  的替代组数量限制。
- 结构优化能改善梯度，但不能覆盖初始内容护栏和用户明确偏好；质量面板应继续 warn，
  不要把 guarded 结果说成“已优化”。
- 若要让 10042004 进一步降到 ≤5/13，优先顺序应是：
  1. 数据侧确认 1.0 是精确值还是下限/取整，并在展示上统一“≤1%”，而不是硬选限报专业；
  2. 产品确认是否接受“限报专业”或更高学费；
  3. 再考虑多样性与更强的梯度约束。
- 默认保持 `off`；本地/灰度用 `-Dsolver.v2.structureQuality=soft`，
  影子对比用 `-Dsolver.v2.structureQualityShadow=true`，效用上限可调
  `-Dsolver.v2.structureQuality.maxUtilityLoss=0.05`。
- 全量 Java 测试已通过（`mvn test` exit 0）；新增结构上限、效用护栏回退、
  初始严格排序测试。

## 14. 代码锚点

- `CandidateUtilityScorer.java`：安全分量/效用
- `VolunteerIntervalService.java`：冲/稳/保阈值与目标数量
- `CandidateSnapshotBuilder.java`：可见录取率口径与 ratio bucket
- `StagedDeterministicPlanSolver.java`：结构阶段、效用下限、失败回退、初始严格排序
- `SolverFeatureFlags.java`：`structureQuality` / shadow / maxUtilityLoss 开关
- `PlanningObjectiveCompiler.java`：策略进入 digest
- `PlanningStateService.java`：`recalculateOrderedSummary` 的 `gradientOk/safetyOk`
- `PlanQualityEvaluationService.java`：C 质量评价与取整下界
- `CandidatePoolStateDTO.java` / `CandidateItemDTO.java`：候选事实字段
